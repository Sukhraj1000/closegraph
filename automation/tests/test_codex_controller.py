from __future__ import annotations
import json
from hashlib import sha256
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

from automation.codex_loop.controller import Controller
from automation.codex_loop.github import GitHub
from automation.codex_loop.state import State, overlaps
from automation.codex_loop.workspace import validate_changes
from automation.codex_loop.codex import parse_result


class FakeGitHub:
    def __init__(self):
        self.main_sha = "base"
        self.issues = {1: {"state": "open"}, 2: {"state": "open"}}
        self.prs = {}
        self.merges = []
        self.unknown_merge = False

    def issue_states(self): return self.issues
    def open_pulls(self): return []
    def main(self): return self.main_sha
    def issue(self, number): return self.issues[number]
    def snapshot(self, sha): return {"sha": sha, "tree": "tree" if sha in ("head", "merged") else "base-tree", "files": []}
    def commit(self, sha): return {"tree": {"sha": self.snapshot(sha)["tree"]}}
    def pull(self, number): return self.prs[number]
    def publish(self, job, changes):
        self.prs[10] = {"head": {"sha": "head"}, "base": {"ref": "main"}, "merged": False}
        return {"head": "head", "tree": "tree", "pr": 10}
    def merge(self, number, head):
        self.merges.append((number, head))
        self.prs[number].update(merged=True, merge_commit_sha="merged")
        self.main_sha = "merged"
        if self.unknown_merge:
            self.unknown_merge = False
            raise URLError("Response lost after GitHub merged")
        return "merged"
    def close_issue(self, number): self.issues[number]["state"] = "closed"


class PendingPublicationGitHub(FakeGitHub):
    """Real publisher/CAS logic against an in-memory REST service; no credentials."""
    def __init__(self):
        super().__init__()
        self.repo = "synthetic/repository"
        self.branch_sha = None
        self.requests = []
        self.publications = []
        self.commits = {}
        self.cas_writes = []

    def branch(self, name):
        return self.branch_sha

    def commit(self, sha):
        return {"tree": {"sha": self.commits.get(sha, "tree" if sha == "merged" else sha + "-tree")}}

    def publish(self, job, changes):
        self.publications.append({"base": job["base"], "candidate": job["candidate"]["local"],
                                  "commit_date": job["commit_date"], "head": job.get("head"),
                                  "commit_identity": dict(job.get("commit_identity", {}))})
        return GitHub.publish(self, job, changes)

    def compare_and_swap_branch(self, branch, before, after):
        return GitHub.compare_and_swap_branch(self, branch, before, after)

    def request(self, method, endpoint, body=None):
        self.requests.append((method, endpoint, body))
        if method == "GET" and endpoint == "":
            return {"node_id": "synthetic-repository"}
        if endpoint == "git/blobs":
            return {"sha": "blob"}
        if endpoint == "git/trees":
            return {"sha": "tree"}
        if endpoint == "git/commits":
            head = sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
            self.commits[head] = body["tree"]
            return {"sha": head}
        if endpoint == "git/refs":
            if self.branch_sha is not None:
                raise AssertionError("Existing branch must not be recreated")
            self.branch_sha = body["sha"]
            return {}
        if endpoint == "graphql":
            update = body["variables"]["input"]["refUpdates"][0]
            if self.branch_sha != update["beforeOid"]:
                return {"errors": [{"message": "beforeOid mismatch"}]}
            self.cas_writes.append(update)
            self.branch_sha = update["afterOid"]
            if 10 in self.prs:
                self.prs[10]["head"]["sha"] = self.branch_sha
            return {"data": {"updateRefs": {"clientMutationId": None}}}
        if method == "GET" and endpoint.startswith("pulls?"):
            return list(self.prs.values())
        if method == "POST" and endpoint == "pulls":
            self.prs[10] = {"number": 10, "head": {"sha": self.branch_sha},
                            "base": {"ref": "main"}, "merged": False}
            return self.prs[10]
        raise AssertionError((method, endpoint, body))


class FakeSandbox:
    def __init__(self):
        self.counter = 0
        self.fail_review = False
        self.fail_postmerge = False
        self.dirty_review = False
        self.physical_match = True
        self.commands = []

    def allocate(self, key, role):
        self.counter += 1
        return role + "-" + str(self.counter)
    def sync(self, workspace, snapshot, allow_dirty=False): return "local-base"
    def capture(self, workspace, base, title, owned):
        return {"local": "local-head", "tree": "tree", "changes": [{"path": "src/app.py", "mode": "100644", "content": "eA=="}]}
    def verify(self, workspace, commands):
        self.commands.append((workspace, commands))
        passed = not (workspace.startswith("review") and self.fail_review or workspace.startswith("postmerge") and self.fail_postmerge)
        return {"passed": passed, "commands": [{"argv": ["test"], "returncode": 0 if passed else 1}]}
    def inspect(self, workspace): return {"local": "local-base", "tree": "tree", "dirty": self.dirty_review, "physical_match": self.physical_match}
    def operation(self, workspace, payload): return {"returncode": 0}


class FakeCodex:
    def __init__(self):
        self.calls = []
        self.review_outcome = "complete"
    def invoke(self, role, job, workspace, prompt):
        self.calls.append((role, workspace))
        return {"outcome": self.review_outcome if role != "engineer" else "complete",
                "summary": "Checked", "findings": [], "run_id": str(len(self.calls))}


class ControllerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "catalogue.json").write_text(json.dumps({"issues": [
            {"key": "T1", "kind": "task", "title": "Implement task", "body": "Required behaviour", "depends_on": []},
            {"key": "T2", "kind": "task", "title": "Dependent task", "body": "Required behaviour", "depends_on": ["T1"]}]}))
        (self.root / "map.json").write_text(json.dumps({"issues": [{"key": "T1", "number": 1}, {"key": "T2", "number": 2}]}))
        self.config = {"catalogue": str(self.root / "catalogue.json"), "issue_map": str(self.root / "map.json"),
                       "commit_identity": {"name": "Fixture Author", "email": "author@example.invalid"},
                       "tasks": {"T1": {"paths": ["src"], "commands": [["pytest", "tests/test_feature.py"]]}},
                       "smoke_commands": [["pytest", "tests/test_smoke.py"]]}
        self.state = State(self.root / "state.db")
        self.gh, self.sandbox, self.codex = FakeGitHub(), FakeSandbox(), FakeCodex()
        self.controller = Controller(self.config, self.state, self.gh, self.sandbox, self.codex)

    def tearDown(self):
        self.state.db.close()
        self.tmp.cleanup()

    def reviewed(self):
        self.controller.tick()  # claim/build
        self.controller.tick()  # publish/review/merge/postmerge

    def test_complete_pipeline_independent_review_exact_merge_and_closure(self):
        self.reviewed()
        job = self.state.get("T1")
        self.assertEqual(job["stage"], "done")
        self.assertEqual(self.gh.merges, [(10, "head")])
        self.assertNotEqual(job["receipt"]["review_run"], job["receipt"]["build_run"])
        self.assertEqual(self.gh.issues[1]["state"], "closed")
        self.assertEqual(len(self.codex.calls), 2)
        self.assertTrue(any(w.startswith("postmerge") for w, _ in self.sandbox.commands))

    def test_failed_independent_test_returns_to_repair_and_never_merges(self):
        self.sandbox.fail_review = True
        self.reviewed()
        self.assertEqual(self.state.get("T1")["stage"], "building")
        self.assertFalse(self.gh.merges)
        self.assertNotIn("receipt", self.state.get("T1"))

    def test_reviewer_modification_cannot_create_receipt(self):
        self.sandbox.dirty_review = True
        self.reviewed()
        self.assertFalse(self.gh.merges)

    def test_clean_git_status_cannot_merge_different_physical_bytes(self):
        self.sandbox.physical_match = False
        self.reviewed()
        self.assertFalse(self.gh.merges)
        self.assertEqual(self.state.get("T1")["stage"], "building")

    def test_review_findings_return_to_same_pr(self):
        self.codex.review_outcome = "changes_requested"
        self.reviewed()
        self.assertEqual(self.state.get("T1")["pr"], 10)
        self.assertEqual(self.state.get("T1")["stage"], "building")

    def test_base_change_before_publication_records_head_then_rebases(self):
        self.controller.tick()
        candidate = self.state.get("T1")["candidate"]
        self.gh.main_sha = "new-base"
        self.controller.tick()
        job = self.state.get("T1")
        self.assertEqual(job["stage"], "rebase")
        self.assertEqual(job["candidate"], candidate)
        self.assertEqual(job["head"], self.gh.prs[10]["head"]["sha"])
        self.assertFalse(self.gh.merges)
        self.assertEqual(self.gh.issues[1]["state"], "open")

    def interrupted_publication(self):
        self.gh = PendingPublicationGitHub()
        self.controller.github = self.gh
        self.controller.tick()
        original = self.state.get("T1")
        save = self.state.save

        class LostJournal(BaseException):
            pass

        def interrupt(job, event=None):
            if event == "published":
                raise LostJournal("Remote publication succeeded before local journal write")
            return save(job, event)

        with patch.object(self.state, "save", side_effect=interrupt):
            with self.assertRaises(LostJournal):
                self.controller.tick()
        self.assertIsNotNone(self.gh.branch_sha)
        self.assertEqual(self.state.get("T1"), original)
        self.assertNotIn("head", original)
        self.gh.main_sha = "new-base"
        self.state.db.close()
        self.state = State(self.root / "state.db")
        self.controller = Controller(self.config, self.state, self.gh, self.sandbox, self.codex)
        return original

    def test_lost_publication_journal_reconciles_original_identity_before_rebase(self):
        original = self.interrupted_publication()
        published_head = self.gh.branch_sha
        self.controller.tick()
        recovered = self.state.get("T1")
        self.assertEqual(recovered.get("head"), published_head)
        self.assertEqual(recovered["stage"], "rebase")
        for field in ("base", "candidate", "commit_date"):
            self.assertEqual(recovered[field], original[field])
        self.assertEqual(self.gh.publications[0], self.gh.publications[1])
        self.assertEqual(self.codex.calls, [("engineer", original["workspace"])])
        self.assertFalse(self.gh.merges)
        self.assertEqual(self.gh.issues[1]["state"], "open")

        with patch.object(self.sandbox, "operation", wraps=self.sandbox.operation) as operation:
            self.controller.tick()
        rebuilt = self.state.get("T1")
        self.assertEqual((rebuilt["base"], rebuilt["head"], rebuilt["stage"]),
                         ("new-base", published_head, "publishing"))
        self.assertEqual([call.args[1]["op"] for call in operation.call_args_list], ["checkout", "rebase"])
        self.assertTrue(all(call.args[1]["candidate"] == original["candidate"]["local"]
                            for call in operation.call_args_list))
        self.assertNotIn("receipt", rebuilt)
        self.assertFalse(self.gh.merges)
        self.assertEqual(self.gh.issues[1]["state"], "open")

        self.controller.tick()
        final = self.state.get("T1")
        self.assertEqual(final["stage"], "done")
        self.assertNotEqual(final["head"], published_head)
        self.assertEqual(final["receipt"]["base"], "new-base")
        self.assertNotEqual(final["receipt"]["review_run"], final["receipt"]["build_run"])
        self.assertEqual(self.gh.merges, [(10, final["head"])])
        self.assertEqual(self.gh.issues[1]["state"], "closed")
        self.assertEqual(len(self.gh.cas_writes), 1)
        self.assertEqual(self.gh.cas_writes[0]["beforeOid"], published_head)
        trees = [body for _, endpoint, body in self.gh.requests if endpoint == "git/trees"]
        self.assertEqual([tree["base_tree"] for tree in trees],
                         ["base-tree", "base-tree", "new-base-tree"])
        self.assertEqual(sum(method == "POST" and endpoint == "pulls"
                             for method, endpoint, _ in self.gh.requests), 1)

    def test_unknown_publication_keeps_pinned_identity_after_config_change_and_restart(self):
        original = self.interrupted_publication()
        head = self.gh.branch_sha
        self.config["commit_identity"] = {"name": "Later Author", "email": "later@example.invalid"}
        self.controller = Controller(self.config, self.state, self.gh, self.sandbox, self.codex)
        self.controller.tick()
        recovered = self.state.get("T1")
        self.assertEqual(recovered["head"], head)
        self.assertEqual(recovered["commit_identity"], original["commit_identity"])
        self.assertEqual(self.gh.publications[0], self.gh.publications[1])
        commits = [body for _, endpoint, body in self.gh.requests if endpoint == "git/commits"]
        self.assertEqual(commits[0], commits[1])
        self.assertEqual(commits[1]["author"]["email"], "author@example.invalid")
        self.assertEqual(commits[1]["author"], commits[1]["committer"])

    def test_catalogue_policy_and_worker_cannot_override_global_commit_identity(self):
        forged = {"name": "Worker Claim", "email": "worker@example.invalid"}
        self.controller.catalogue[0]["commit_identity"] = forged
        self.config["tasks"]["T1"]["commit_identity"] = forged
        invoke = self.codex.invoke
        with patch.object(self.codex, "invoke", side_effect=lambda *args:
                          dict(invoke(*args), commit_identity=forged)):
            self.controller.tick()
        job = self.state.get("T1")
        self.assertEqual(job["commit_identity"], self.config["commit_identity"])
        self.assertEqual(job["build_result"]["commit_identity"], forged)
        self.assertNotEqual(job["commit_identity"], forged)

    def test_pending_publication_never_rebases_over_an_external_branch_change(self):
        original = self.interrupted_publication()
        self.gh.branch_sha = "external-commit"
        for _ in range(3):
            self.controller.tick()
        paused = self.state.get("T1")
        self.assertEqual((paused["stage"], paused.get("resume_stage")), ("paused", "publishing"))
        for field in ("base", "candidate", "commit_date"):
            self.assertEqual(paused[field], original[field])
        self.assertNotIn("head", paused)
        self.assertIn("Publication branch changed outside this job", paused["last_error"])
        self.assertEqual(self.gh.branch_sha, "external-commit")
        self.assertFalse(self.gh.cas_writes)
        self.assertFalse(self.gh.merges)
        self.assertEqual(self.gh.issues[1]["state"], "open")

    def test_merge_response_loss_reconciles_without_second_merge(self):
        self.gh.unknown_merge = True
        self.reviewed()
        self.assertEqual(self.state.get("T1")["stage"], "merging")
        self.controller.tick()
        self.assertEqual(self.state.get("T1")["stage"], "done")
        self.assertEqual(len(self.gh.merges), 1)

    def test_postmerge_failure_halts_queue_and_preserves_open_issue(self):
        self.sandbox.fail_postmerge = True
        self.reviewed()
        self.assertIsNotNone(self.state.meta("halted"))
        self.assertEqual(self.gh.issues[1]["state"], "open")
        before = list(self.codex.calls)
        self.controller.tick()
        self.assertEqual(self.codex.calls, before)

    def queued_merge(self, key="A0"):
        # Sort before T1 and remain mergeable after T1's remote merge. This
        # catches both same-cycle advancement and wrong priority on restart.
        job = dict(self.state.get("T1"), key=key, stage="merge", base="merged", pr=11, number=2)
        job["receipt"] = dict(job["receipt"], base="merged")
        self.gh.prs[11] = {"head": {"sha": "head"}, "base": {"ref": "main"}, "merged": False}
        self.state.save(job)
        return job

    def test_postmerge_infrastructure_errors_block_across_restart_and_pause(self):
        original_verify = self.sandbox.verify
        def fail_postmerge(workspace, commands):
            if workspace.startswith("postmerge"):
                raise OSError("test infrastructure unavailable")
            return original_verify(workspace, commands)
        with patch.object(self.sandbox, "verify", side_effect=fail_postmerge):
            self.reviewed()
            self.queued_merge()
            self.state.db.close()
            self.state = State(self.root / "state.db")
            self.controller = Controller(self.config, self.state, self.gh, self.sandbox, self.codex)
            for _ in range(4):
                self.controller.tick()
                self.assertEqual(len(self.gh.merges), 1)
            job = self.state.get("T1")
            self.assertEqual((job["stage"], job["resume_stage"]), ("paused", "postmerge"))
            self.assertEqual(self.gh.issues[1]["state"], "open")
        # Coordinator retry resumes verification before the queued merge.
        job.update(stage=job["resume_stage"], attempts=0)
        self.state.save(job)
        self.controller.tick()
        self.assertEqual(self.state.get("T1")["stage"], "done")
        self.assertEqual(self.state.get("A0")["stage"], "done")
        self.assertEqual(len(self.gh.merges), 2)

    def test_postmerge_exception_blocks_another_merge_in_same_cycle(self):
        original_review = self.controller.review
        def review_and_queue(job):
            update = original_review(job)
            merged_job = dict(job, **update)
            next_job = dict(merged_job, key="Z2", number=2, pr=11, base="merged")
            next_job["receipt"] = dict(update["receipt"], base="merged")
            self.gh.prs[11] = {"head": {"sha": "head"}, "base": {"ref": "main"}, "merged": False}
            return update, next_job
        self.controller.tick()
        # Prepare independent merge receipts before the queue is consumed.
        job = self.state.get("T1")
        job.update(self.gh.publish(job, job["candidate"]["changes"]), stage="reviewing")
        update, next_job = review_and_queue(job)
        job.update(update)
        self.state.save(job)
        self.state.save(next_job)
        with patch.object(self.gh, "commit", side_effect=OSError("GitHub unavailable")):
            self.controller.tick()
        self.assertEqual(len(self.gh.merges), 1)
        self.assertEqual(self.state.get("T1")["stage"], "postmerge")
        self.assertEqual(self.state.get("Z2")["stage"], "merge")

    def test_unknown_merge_outcome_blocks_queue_until_reconciled(self):
        self.gh.unknown_merge = True
        self.reviewed()
        self.queued_merge()
        with patch.object(self.gh, "pull", side_effect=OSError("GitHub unavailable")):
            for _ in range(3):
                self.controller.tick()
        self.assertEqual(len(self.gh.merges), 1)
        self.assertEqual(self.state.get("T1")["resume_stage"], "merging")
        self.assertEqual(self.state.get("A0")["stage"], "merge")

    def test_live_github_dependencies_and_missing_policy_are_visible(self):
        result = {r["key"]: r for r in self.controller.ready()}
        self.assertTrue(result["T1"]["ready"])
        self.assertEqual(result["T2"]["reason"], "no configured ownership/test policy")
        self.config["tasks"]["T2"] = {"paths": ["ui"], "commands": [["test"]]}
        result = {r["key"]: r for r in self.controller.ready()}
        self.assertEqual(result["T2"]["reason"], "dependencies open")
        self.gh.issues[1]["state"] = "closed"
        result = {r["key"]: r for r in self.controller.ready()}
        self.assertTrue(result["T2"]["ready"])

    def test_changed_head_base_or_reviewer_invalidates_receipt(self):
        job = {"head": "head", "base": "base", "tree": "tree",
               "receipt": {"head": "head", "base": "base", "tree": "tree",
                           "review_run": "r", "build_run": "b", "checks": {"passed": True}}}
        pr = {"head": {"sha": "head"}, "base": {"ref": "main"}}
        self.assertTrue(Controller.receipt_valid(job, pr, "base"))
        self.assertFalse(Controller.receipt_valid(job, pr, "different"))
        pr["head"]["sha"] = "new"
        self.assertFalse(Controller.receipt_valid(job, pr, "base"))
        pr["head"]["sha"] = "head"
        job["receipt"]["review_run"] = "b"
        self.assertFalse(Controller.receipt_valid(job, pr, "base"))


class StateCase(unittest.TestCase):
    def test_claims_are_atomic_durable_and_exclusive(self):
        with tempfile.TemporaryDirectory() as d:
            first, second = State(Path(d) / "db"), State(Path(d) / "db")
            job = {"key": "a", "stage": "building", "paths": ["src"]}
            self.assertTrue(first.claim(job))
            self.assertFalse(second.claim(job))
            self.assertFalse(second.claim({"key": "b", "stage": "building", "paths": ["src/file.py"]}))
            self.assertTrue(second.claim({"key": "c", "stage": "building", "paths": ["ui"]}))
            self.assertTrue(second.claim({"key": "d", "stage": "reviewing", "paths": ["docs"]}))
            self.assertFalse(second.claim({"key": "e", "stage": "building", "paths": ["other"]}))
            first.complete(job)
            self.assertTrue(second.claim({"key": "e", "stage": "building", "paths": ["src/file.py"]}))
            first.db.close()
            second.db.close()

    def test_interrupted_completion_rolls_back_done_claims_and_event(self):
        import subprocess
        import sys
        for timing in ("BEFORE", "AFTER"):
            with self.subTest(timing=timing), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / "state.db"
                state = State(path)
                self.addCleanup(state.db.close)
                job = {"key": "T1", "stage": "postmerge", "paths": ["src"]}
                self.assertTrue(state.claim(job))
                state.db.close()
                bootstrap = """import os,sys
from automation.codex_loop.state import State
state=State(sys.argv[1])
state.db.create_function('interrupt_completion',0,lambda:os._exit(91))
state.db.execute('CREATE TRIGGER interrupt_completion '+sys.argv[2]+
                 ' DELETE ON claims BEGIN SELECT interrupt_completion(); END')
state.db.commit()
state.complete(state.get('T1'))
"""
                result = subprocess.run([sys.executable, "-c", bootstrap, str(path), timing],
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 91, result.stderr)
                # Inspect raw persisted data before State startup reconciliation
                # can hide an incorrectly committed completion.
                import sqlite3
                with sqlite3.connect(path) as db:
                    saved = json.loads(db.execute("SELECT data FROM jobs WHERE key='T1'").fetchone()[0])
                    claims = list(db.execute("SELECT path,owner FROM claims"))
                    events = list(db.execute("SELECT event FROM events WHERE event='completed'"))
                    db.execute("DROP TRIGGER interrupt_completion")
                self.assertEqual(saved["stage"], "postmerge")
                self.assertEqual(claims, [("src", "T1")])
                self.assertEqual(events, [])
                resumed = State(path)
                self.addCleanup(resumed.db.close)
                next_job = {"key": "T2", "stage": "building", "paths": ["src/app.py"]}
                self.assertFalse(resumed.claim(next_job))
                resumed.complete(resumed.get("T1"))
                self.assertEqual(resumed.get("T1")["stage"], "done")
                self.assertTrue(resumed.claim(next_job))
                self.assertEqual(list(resumed.db.execute("SELECT event FROM events WHERE event='completed'")),
                                 [("completed",)])

    def test_completion_error_keeps_memory_and_database_retryable(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as folder:
            state = State(Path(folder) / "state.db")
            self.addCleanup(state.db.close)
            job = {"key": "T1", "stage": "postmerge", "paths": ["src"]}
            self.assertTrue(state.claim(job))
            state.db.execute("""CREATE TRIGGER fail_completion BEFORE INSERT ON events
                                WHEN NEW.event='completed'
                                BEGIN SELECT RAISE(ABORT, 'injected completion failure'); END""")
            state.db.commit()
            with self.assertRaisesRegex(sqlite3.IntegrityError, "injected completion failure"):
                state.complete(job)
            self.assertEqual(job["stage"], "postmerge")
            self.assertEqual(state.get("T1"), job)
            self.assertFalse(state.db.in_transaction)
            self.assertEqual(list(state.db.execute("SELECT path,owner FROM claims")), [("src", "T1")])
            self.assertEqual(list(state.db.execute("SELECT event FROM events WHERE event='completed'")), [])
            state.db.execute("DROP TRIGGER fail_completion")
            state.db.commit()
            state.complete(job)
            self.assertEqual(job["stage"], "done")
            self.assertEqual(list(state.db.execute("SELECT path,owner FROM claims")), [])

    def test_startup_releases_only_stranded_completed_job_claims(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.db"
            state = State(path)
            self.addCleanup(state.db.close)
            for key, stage, paths in (("T1", "postmerge", ["src"]),
                                      ("paused", "paused", ["docs"]),
                                      ("active", "building", ["ui"])):
                self.assertTrue(state.claim({"key": key, "stage": stage, "paths": paths}))
            # Reproduce an older controller's interruption after saving done.
            done = state.get("T1")
            done["stage"] = "done"
            state.save(done, "completed")
            state.db.close()
            resumed = State(path)
            self.addCleanup(resumed.db.close)
            self.assertEqual(resumed.get("T1")["stage"], "done")
            self.assertEqual(set(resumed.db.execute("SELECT path,owner FROM claims")),
                             {("docs", "paused"), ("ui", "active")})
            self.assertTrue(resumed.claim({"key": "T2", "stage": "building", "paths": ["src/app.py"]}))
            self.assertFalse(resumed.claim({"key": "T3", "stage": "building", "paths": ["docs/page.md"]}))
            resumed.db.close()
            again = State(path)
            self.addCleanup(again.db.close)
            self.assertEqual(set(again.db.execute("SELECT path,owner FROM claims")),
                             {("docs", "paused"), ("ui", "active"), ("src/app.py", "T2")})

    def test_controller_lock_is_exclusive(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = State(Path(d) / "db"), State(Path(d) / "db")
            with a.controller_lock():
                with self.assertRaises(RuntimeError):
                    with b.controller_lock(): pass
            a.db.close()
            b.db.close()


class ResultCase(unittest.TestCase):
    def test_codex_requires_success_event_and_typed_structured_result(self):
        good = json.dumps({"outcome": "complete", "summary": "done", "findings": []})
        self.assertEqual(parse_result('{"type":"turn.completed"}', good, 0)["outcome"], "complete")
        for events, final, code in [("", good, 0), ('{"type":"turn.completed"}', good, 1),
                                    ('{"type":"turn.failed"}', good, 0),
                                    ('{"type":"turn.completed"}', '{"outcome":"complete"}', 0)]:
            with self.assertRaises((ValueError, RuntimeError)):
                parse_result(events, final, code)

    def test_publisher_input_forbids_scope_escape_symlinks_duplicates_and_empty(self):
        good = {"path": "src/a.py", "mode": "100644", "content": "YQ=="}
        validate_changes([good], ["src"])
        for changes in ([], [dict(good, path="../secret")], [dict(good, path="other")],
                        [dict(good, mode="120000")], [good, good], [dict(good, content="!!!!")]):
            with self.assertRaises(ValueError):
                validate_changes(changes, ["src"])


if __name__ == "__main__":
    unittest.main()
