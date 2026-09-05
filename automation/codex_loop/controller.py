"""Bounded engineering slots and a single durable, revision-checked merge queue."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import re
from pathlib import Path
import time
import uuid

from .github import validate_commit_identity
from .workspace import validate_paths


class Controller:
    def __init__(self, config, state, github, sandbox, codex):
        self.config, self.state, self.github = config, state, github
        self.sandbox, self.codex = sandbox, codex
        self.commit_identity = validate_commit_identity(config.get("commit_identity"))
        self.slots = config.get("slots", 3)
        if not 1 <= self.slots <= 3:
            raise ValueError("Worker slots must be 1..3")
        if not config.get("smoke_commands"):
            raise ValueError("Explicit post-merge smoke commands are required")
        numbers = {r["key"]: r["number"] for r in json.loads(Path(config["issue_map"]).read_text())["issues"]}
        self.catalogue = [dict(row, number=numbers[row["key"]]) for row in json.loads(Path(config["catalogue"]).read_text())["issues"] if row["kind"] == "task"]
        for key, spec in config["tasks"].items():
            validate_paths(spec["paths"])
            if not spec.get("commands"):
                raise ValueError("Explicit task tests required for " + key)

    def ready(self):
        # Reconcile actual GitHub state rather than treating catalogue checkboxes as execution evidence.
        observed = self.github.issue_states()
        remote = {r["key"]: observed.get(r["number"]) or self.github.issue(r["number"]) for r in self.catalogue}
        result = []
        open_pulls = self.github.open_pulls()
        for row in self.catalogue:
            reason = None
            if row["key"] not in self.config["tasks"]:
                reason = "no configured ownership/test policy"
            elif remote[row["key"]]["state"] != "open":
                reason = "issue closed"
            elif self.state.get(row["key"]):
                reason = "already recorded"
            elif any(re.search(r"(?<![0-9])#" + str(row["number"]) + r"(?![0-9])",
                               (pr.get("body") or "") + " " + pr.get("title", "")) or
                     ("[" + row["key"] + "]") in pr.get("title", "") for pr in open_pulls):
                reason = "existing open PR already covers this issue"
            elif any(remote[dep]["state"] != "closed" for dep in row["depends_on"]):
                reason = "dependencies open"
            result.append({"key": row["key"], "number": row["number"], "ready": reason is None, "reason": reason})
        return result

    def claim_ready(self):
        rows = {r["key"]: r for r in self.catalogue}
        for item in self.ready():
            if not item["ready"]:
                continue
            row = rows[item["key"]]
            policy = self.config["tasks"][row["key"]]
            job = {**row, **policy, "stage": "new", "attempts": 0,
                   "commit_identity": dict(self.commit_identity),
                   "branch": "codex/auto-" + row["key"].lower().replace(".", "-") + "-" + uuid.uuid4().hex[:8]}
            self.state.claim(job, self.slots)

    def prepare(self, job):
        if job["stage"] == "new":
            job["workspace"] = self.sandbox.allocate(job["key"], "build")
            job["base"] = self.github.main()
            job["stage"] = "preparing"
            self.state.save(job, "prepare_intent")
        if job["stage"] == "preparing":
            # No worker has started here, so an interrupted import can safely resume.
            job["base_local"] = self.sandbox.sync(job["workspace"], self.github.snapshot(job["base"]), allow_dirty=True)
            job["stage"] = "building"
            self.state.save(job, "prepared")

    def rebase(self, job):
        """Journal every replay stage; preserve the implementation before importing main."""
        if job["stage"] == "rebase":
            job["replay"] = {"base": self.github.main(), "candidate": job["candidate"]["local"],
                             "checkpoint": "recovery-" + uuid.uuid4().hex[:12], "old_base_local": job["base_local"]}
            job["stage"] = "rebase_checkout"
            self.state.save(job, "rebase_intent")
        replay, workspace = job["replay"], job["workspace"]
        if job["stage"] == "rebase_checkout":
            self.sandbox.operation(workspace, {"op": "checkout", "base": replay["old_base_local"],
                "candidate": replay["candidate"], "checkpoint": replay["checkpoint"]})
            job["stage"] = "rebase_import"
            self.state.save(job, "rebase_checkout_complete")
        if job["stage"] == "rebase_import":
            new_base = self.sandbox.sync(workspace, self.github.snapshot(replay["base"]), allow_dirty=True)
            job.update(base=replay["base"], base_local=new_base, stage="rebase_replay")
            self.state.save(job, "rebase_import_complete")
        if job["stage"] == "rebase_replay":
            # On restart a previous cherry-pick may have finished or left conflicts.
            observed = self.sandbox.inspect(workspace)
            result = {"recovered": True, "observed": observed}
            if observed["local"] == job["base_local"] and not observed["dirty"]:
                result = self.sandbox.operation(workspace, {"op": "rebase", "candidate": replay["candidate"],
                    "checkpoint": replay["checkpoint"] + "-replay"})
            job.update(stage="building", feedback="Main changed. Prior implementation preserved in " +
                replay["checkpoint"] + ". Resolve any existing cherry-pick conflicts and preserve current main changes. "
                "Revalidate the complete task. Replay evidence: " + json.dumps(result))
            job.pop("receipt", None)
            self.state.save(job, "base_changed")

    def build(self, job):
        prompt = job["body"] + "\n\nTrusted validation commands: " + json.dumps(job["commands"])
        if job.get("feedback"):
            prompt += "\n\nRepair these findings in the same candidate: " + job["feedback"]
        result = self.codex.invoke("engineer", job, job["workspace"], prompt)
        if result["outcome"] != "complete":
            raise RuntimeError(json.dumps(result))
        candidate = self.sandbox.capture(job["workspace"], job["base_local"], job["title"], job["paths"])
        verification = self.sandbox.verify(job["workspace"], job["commands"])
        if not verification["passed"]:
            raise RuntimeError("Implementation checks failed: " + json.dumps(verification))
        return {"candidate": candidate, "build_result": result, "build_checks": verification,
                "stage": "publishing", "commit_date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}

    def review(self, job):
        if self.github.main() != job["base"]:
            return {"stage": "rebase"}
        pr = self.github.pull(job["pr"])
        if pr["head"]["sha"] != job["head"] or pr["base"]["ref"] != "main":
            raise RuntimeError("PR head or destination changed outside controller")
        workspace = self.sandbox.allocate(job["key"], "review")
        base_local = self.sandbox.sync(workspace, self.github.snapshot(job["base"]))
        self.sandbox.sync(workspace, self.github.snapshot(job["head"]))
        result = self.codex.invoke("independent reviewer", job, workspace,
            "Verify the issue and candidate against local base " + base_local + ". "
            "The GitHub base is " + job["base"] + " and candidate head is " + job["head"] + ". "
            "Inspect git diff " + base_local + "..HEAD and the full specification.\n" +
            job["body"] + "\nTrusted checks: " + json.dumps(job["commands"]))
        if result["run_id"] == job["build_result"]["run_id"]:
            raise RuntimeError("Reviewer cannot be the implementation run")
        if result["outcome"] != "complete" or result["findings"]:
            return {"stage": "building", "feedback": json.dumps(result), "review_result": result}
        checks = self.sandbox.verify(workspace, job["commands"])
        observed = self.sandbox.inspect(workspace)
        if not checks["passed"] or observed["dirty"] or not observed["physical_match"] or observed["tree"] != job["tree"]:
            return {"stage": "building", "feedback": "Independent verification failed: " + json.dumps(checks),
                    "review_result": result}
        # A model's success text alone can never construct the trusted receipt.
        receipt = {"base": job["base"], "head": job["head"], "tree": job["tree"],
                   "review_run": result["run_id"], "build_run": job["build_result"]["run_id"],
                   "checks": checks, "review_workspace": workspace}
        return {"stage": "merge", "receipt": receipt, "review_result": result}

    @staticmethod
    def receipt_valid(job, pr, main):
        receipt = job.get("receipt", {})
        return (receipt.get("base") == main == job.get("base") and
                receipt.get("head") == pr["head"]["sha"] == job.get("head") and
                receipt.get("tree") == job.get("tree") and
                receipt.get("review_run") != receipt.get("build_run") and
                bool(receipt.get("review_run")) and
                receipt.get("checks", {}).get("passed") is True and
                pr["base"]["ref"] == "main")

    def merge(self, job):
        pr = self.github.pull(job["pr"])
        if pr.get("merged"):
            if pr["head"]["sha"] != job["head"]:
                raise RuntimeError("Unexpected merged PR head")
            sha = pr["merge_commit_sha"]
        else:
            main = self.github.main()
            if not self.receipt_valid(job, pr, main):
                if main != job["base"]:
                    job["stage"] = "rebase"
                    self.state.save(job, "stale_receipt")
                    return
                raise RuntimeError("Refusing merge without valid exact-revision independent receipt")
            job["stage"] = "merging"
            self.state.save(job, "merge_intent")
            sha = self.github.merge(job["pr"], job["head"])
        job["merge_sha"] = sha
        job["stage"] = "postmerge"
        self.state.save(job, "merge_observed")

    def postmerge(self, job):
        sha = job["merge_sha"]
        if self.github.commit(sha)["tree"]["sha"] != job["tree"]:
            self.state.meta("halted", {"key": job["key"], "reason": "Merged tree differs from verified candidate"})
            raise RuntimeError("Merge tree mismatch; merge queue halted")
        workspace = self.sandbox.allocate(job["key"], "postmerge")
        self.sandbox.sync(workspace, self.github.snapshot(sha))
        checks = self.sandbox.verify(workspace, self.config["smoke_commands"] + job["commands"])
        observed = self.sandbox.inspect(workspace)
        if not checks["passed"] or observed["dirty"] or not observed["physical_match"] or observed["tree"] != job["tree"]:
            self.state.meta("halted", {"key": job["key"], "reason": "Post-merge checks failed"})
            raise RuntimeError("Post-merge failure; merge queue halted: " + json.dumps(checks))
        if self.github.main() != sha:
            self.state.meta("halted", {"key": job["key"], "reason": "External main update during post-merge checks"})
            raise RuntimeError("Main advanced during checks; queue halted pending verification")
        job["postmerge_checks"] = checks
        # Closing is idempotent and happens only after recorded live checks.
        self.state.save(job, "postmerge_passed")
        self.github.close_issue(job["number"])
        self.state.complete(job)

    def failure(self, job, exc):
        job["attempts"] = job.get("attempts", 0) + 1
        job["last_error"] = str(exc)[-16000:]
        # Preserve unknown publication/merge outcomes for reconciliation at the same stage.
        if job["stage"] == "building":
            job["feedback"] = job["last_error"]
        if job["attempts"] >= self.config.get("max_attempts", 3):
            job["resume_stage"] = job["stage"]
            job["stage"] = "paused"
        self.state.save(job, "attempt_failed")

    def tick(self):
        halted = self.state.meta("halted")
        if halted:
            return {"halted": halted, "jobs": self.state.jobs()}
        self.claim_ready()
        # All SQLite transitions and GitHub publications/merges are owned by this thread.
        candidates = []
        for job in self.state.jobs():
            if job["stage"] in ("done", "paused"):
                continue
            try:
                self.prepare(job)
                if job["stage"].startswith("rebase"):
                    self.rebase(job)
                if job["stage"] == "publishing":
                    # Reconcile the original deterministic publication before a rebase
                    # can replace its base, candidate or timestamp after a lost journal.
                    published = self.github.publish(job, job["candidate"]["changes"])
                    if published["tree"] != job["candidate"]["tree"]:
                        raise RuntimeError("Published bytes differ from tested implementation tree")
                    job.update(published, stage="reviewing")
                    self.state.save(job, "published")
                    if self.github.main() != job["base"]:
                        job["stage"] = "rebase"
                        self.state.save(job, "base_changed_after_publish")
                        continue
                if job["stage"] in ("building", "reviewing"):
                    if job["stage"] == "building" and "commit_identity" not in job:
                        # A legacy job starting a new build has no unknown publication.
                        job["commit_identity"] = dict(self.commit_identity)
                        self.state.save(job, "commit_identity_pinned")
                    candidates.append(job)
            except Exception as exc:
                self.failure(job, exc)
        with ThreadPoolExecutor(max_workers=self.slots) as pool:
            work = [(j, pool.submit(self.build if j["stage"] == "building" else self.review, dict(j))) for j in candidates]
            for job, future in work:
                try:
                    update = future.result()
                    job.update(update)
                    # Findings require repair and a fresh review; never silently keep the old receipt.
                    if job["stage"] == "building":
                        job.pop("receipt", None)
                        job["attempts"] += 1
                        if job["attempts"] >= self.config.get("max_attempts", 3):
                            job.update(resume_stage="building", stage="paused")
                    self.state.save(job, "worker_finished")
                except Exception as exc:
                    self.failure(job, exc)
        # The persisted stage IS the merge barrier, including a paused unknown
        # outcome. Recover it before any new merge, regardless of job sort order.
        jobs = self.state.jobs()
        pending = [j for j in jobs if j["stage"] in ("merging", "postmerge") or
                   j["stage"] == "paused" and j.get("resume_stage") in ("merging", "postmerge")]
        for job in pending + [j for j in jobs if j["stage"] == "merge"]:
            if job["stage"] == "paused":
                break
            try:
                if job["stage"] in ("merge", "merging"):
                    self.merge(job)
                if job["stage"] == "postmerge":
                    self.postmerge(job)
            except Exception as exc:
                self.failure(job, exc)
                # Even a transport/clone/issue-close error must retain priority
                # on the next tick and after restart. Do not advance this cycle.
                break
            if self.state.meta("halted") or job["stage"] in ("merging", "postmerge"):
                break
        return {"halted": self.state.meta("halted"), "jobs": self.state.jobs()}

    def run(self, cycles=1, interval=10):
        with self.state.controller_lock():
            for count in range(cycles):
                result = self.tick()
                print(json.dumps({"cycle": count + 1, "halted": result["halted"],
                                  "jobs": [{"key": j["key"], "stage": j["stage"]} for j in result["jobs"]]}), flush=True)
                if result["halted"]:
                    return result
                if count + 1 < cycles:
                    time.sleep(min(interval, 60))
            return result
