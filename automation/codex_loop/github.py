"""Trusted GitHub REST adapter; never executes repository Git or hooks on host."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


class GitHub:
    def __init__(self, repo, token=None):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise ValueError("Invalid owner/repository")
        self.repo = repo
        self._immutable_cache = {}
        self.token = token or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if not self.token:
            self.token = subprocess.run(["gh", "auth", "token", "--hostname", "github.com"],
                                        cwd="/", capture_output=True, text=True, check=True).stdout.strip()

    def request(self, method, endpoint, body=None):
        cacheable = method == "GET" and any(endpoint.startswith(prefix) for prefix in ("git/blobs/", "git/trees/", "git/commits/"))
        if cacheable and endpoint in self._immutable_cache:
            return self._immutable_cache[endpoint]
        data = None if body is None else json.dumps(body).encode()
        url = ("https://api.github.com/graphql" if endpoint == "graphql" else
               "https://api.github.com/repos/" + self.repo + ("/" + endpoint if endpoint else ""))
        request = Request(url,
                          data=data, method=method, headers={
            "Authorization": "Bearer " + self.token, "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"})
        # Mutations have semantic reconciliation at their caller, not blind HTTP retries.
        for attempt in range(3 if method == "GET" else 1):
            try:
                with urlopen(request, timeout=45) as response:
                    raw = response.read()
                    result = json.loads(raw) if raw else None
                    if cacheable:
                        self._immutable_cache[endpoint] = result
                    return result
            except (HTTPError, URLError) as exc:
                if method != "GET" or attempt == 2 or isinstance(exc, HTTPError) and exc.code < 500:
                    raise
                time.sleep(0.2 * 2 ** attempt)

    def main(self):
        return self.request("GET", "git/ref/heads/main")["object"]["sha"]

    def commit(self, sha):
        return self.request("GET", "git/commits/" + quote(sha, safe=""))

    def issue_states(self):
        result, page = {}, 1
        while True:
            rows = self.request("GET", "issues?state=all&per_page=100&page=" + str(page))
            result.update({row["number"]: row for row in rows if "pull_request" not in row})
            if len(rows) < 100:
                return result
            page += 1

    def open_pulls(self):
        results, page = [], 1
        while True:
            rows = self.request("GET", "pulls?state=open&per_page=100&page=" + str(page))
            results.extend(rows)
            if len(rows) < 100:
                return results
            page += 1

    def issue(self, number):
        return self.request("GET", "issues/" + str(int(number)))

    def pull(self, number):
        return self.request("GET", "pulls/" + str(int(number)))

    def snapshot(self, sha):
        tree = self.commit(sha)["tree"]["sha"]
        result = self.request("GET", "git/trees/" + tree + "?recursive=1")
        if result.get("truncated"):
            raise RuntimeError("Truncated GitHub tree; refusing an incomplete snapshot")
        files = []
        for item in result["tree"]:
            if item["type"] == "tree":
                continue
            if item["type"] != "blob" or item["mode"] not in ("100644", "100755"):
                raise RuntimeError("Snapshot contains unsupported symlink/submodule: " + item["path"])
            blob = self.request("GET", "git/blobs/" + item["sha"])
            content = blob["content"]
            raw = base64.b64decode(content)
            if hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() != item["sha"]:
                raise RuntimeError("GitHub blob integrity failure")
            files.append({"path": item["path"], "mode": item["mode"],
                          "content": base64.b64encode(raw).decode()})
        return {"sha": sha, "tree": tree, "files": files}

    def branch(self, name):
        try:
            return self.request("GET", "git/ref/heads/" + quote(name, safe=""))["object"]["sha"]
        except HTTPError as exc:
            if exc.code == 404:
                return None
            raise

    def compare_and_swap_branch(self, branch, before, after):
        # REST update-ref has no expected-old condition. GraphQL updateRefs
        # checks beforeOid atomically, even for a non-fast-forward replacement.
        repository_id = self.request("GET", "")["node_id"]
        result = self.request("POST", "graphql", {
            "query": "mutation($input: UpdateRefsInput!) { updateRefs(input: $input) { clientMutationId } }",
            "variables": {"input": {"repositoryId": repository_id, "refUpdates": [{
                "name": "refs/heads/" + branch, "beforeOid": before, "afterOid": after, "force": True}]}}})
        if result.get("errors") or not isinstance(result.get("data", {}).get("updateRefs"), dict):
            raise RuntimeError("Atomic publication rejected: " + json.dumps(result.get("errors", result)))
        if self.branch(branch) != after:
            raise RuntimeError("Publication branch changed outside this job after update")

    def publish(self, job, changes):
        """Stable commit timestamp makes object creation retry-safe after unknown outcomes."""
        base = job["base"]
        entries = []
        for change in changes:
            if change["content"] is None:
                entries.append({"path": change["path"], "mode": "100644", "type": "blob", "sha": None})
            else:
                blob = self.request("POST", "git/blobs", {"content": change["content"], "encoding": "base64"})
                entries.append({"path": change["path"], "mode": change["mode"], "type": "blob", "sha": blob["sha"]})
        tree = self.request("POST", "git/trees", {"base_tree": self.commit(base)["tree"]["sha"], "tree": entries})
        identity = {"name": "CloseGraph Automation", "email": "automation@example.invalid", "date": job["commit_date"]}
        commit = self.request("POST", "git/commits", {
            "message": job["title"] + "\n\nCloseGraph task " + job["key"],
            "tree": tree["sha"], "parents": [base], "author": identity, "committer": identity})
        branch = job["branch"]
        current = self.branch(branch)
        if current is None:
            try:
                self.request("POST", "git/refs", {"ref": "refs/heads/" + branch, "sha": commit["sha"]})
            except (HTTPError, URLError):
                if self.branch(branch) != commit["sha"]:
                    raise
        elif current != commit["sha"]:
            # Only our persisted previous head can be replaced. Never clobber external work.
            if current != job.get("head"):
                raise RuntimeError("Publication branch changed outside this job")
            try:
                self.compare_and_swap_branch(branch, job["head"], commit["sha"])
            except (HTTPError, URLError):
                if self.branch(branch) != commit["sha"]:
                    raise
        pulls = self.request("GET", "pulls?state=open&head=" + quote(self.repo.split("/")[0] + ":" + branch, safe=""))
        if pulls:
            pr = pulls[0]
        else:
            body = "Implements #" + str(job["number"]) + ".\n\nIndependent automated review and exact revision test receipts are recorded by the controller. No human approval is asserted."
            try:
                pr = self.request("POST", "pulls", {"title": job["title"], "head": branch, "base": "main", "body": body})
            except (HTTPError, URLError):
                found = self.request("GET", "pulls?state=open&head=" + quote(self.repo.split("/")[0] + ":" + branch, safe=""))
                if not found:
                    raise
                pr = found[0]
        return {"head": commit["sha"], "tree": tree["sha"], "pr": pr["number"]}

    def merge(self, number, head):
        try:
            result = self.request("PUT", "pulls/" + str(number) + "/merge", {"sha": head, "merge_method": "squash"})
        except (HTTPError, URLError):
            pr = self.pull(number)
            if not pr.get("merged") or pr["head"]["sha"] != head:
                raise
            return pr["merge_commit_sha"]
        if not result.get("merged"):
            raise RuntimeError("GitHub did not merge: " + result.get("message", "unknown"))
        return result["sha"]

    def close_issue(self, number):
        self.request("PATCH", "issues/" + str(number), {"state": "closed", "state_reason": "completed"})
