import json
import unittest
from io import BytesIO
from unittest.mock import patch
from urllib.error import URLError

from automation.codex_loop.github import GitHub


class FakeREST(GitHub):
    def __init__(self):
        self.repo = "owner/repo"
        self.branch_sha = None
        self.prs = []
        self.fail_ref_after_write = False
        self.fail_pr_after_write = False
        self.calls = []
        self.race_head = None
        self.fail_cas_after_write = False
    def branch(self, name): return self.branch_sha
    def request(self, method, endpoint, body=None):
        self.calls.append((method, endpoint, body))
        if method == "GET" and endpoint == "": return {"node_id": "repository-id"}
        if endpoint == "graphql":
            update = body["variables"]["input"]["refUpdates"][0]
            if self.race_head:
                self.branch_sha, self.race_head = self.race_head, None
            if self.branch_sha != update["beforeOid"]:
                return {"errors": [{"message": "beforeOid mismatch"}]}
            self.branch_sha = update["afterOid"]
            if self.fail_cas_after_write:
                self.fail_cas_after_write = False
                raise URLError("lost CAS response")
            return {"data": {"updateRefs": {"clientMutationId": None}}}
        if endpoint == "git/commits/base": return {"tree": {"sha": "base-tree"}}
        if endpoint == "git/blobs": return {"sha": "blob"}
        if endpoint == "git/trees": return {"sha": "tree"}
        if endpoint == "git/commits": return {"sha": "head"}
        if endpoint == "git/refs":
            self.branch_sha = body["sha"]
            if self.fail_ref_after_write:
                self.fail_ref_after_write = False
                raise URLError("lost response")
            return {}
        if method == "GET" and endpoint.startswith("pulls?"): return self.prs
        if method == "POST" and endpoint == "pulls":
            self.prs = [{"number": 10}]
            if self.fail_pr_after_write:
                self.fail_pr_after_write = False
                raise URLError("lost response")
            return self.prs[0]
        raise AssertionError((method, endpoint, body))


class TransportCase(unittest.TestCase):
    def test_atomic_replacement_uses_exact_repository_root_and_graphql_urls(self):
        github = GitHub("owner/repo", token="synthetic-test-token")
        calls = []
        replies = [
            {"node_id": "repository-id"},
            {"data": {"updateRefs": {"clientMutationId": None}}},
            {"object": {"sha": "after"}},
        ]

        def transport(request, *, timeout):
            index = len(calls)
            calls.append(request)
            expected = [
                ("GET", "https://api.github.com/repos/owner/repo"),
                ("POST", "https://api.github.com/graphql"),
                ("GET", "https://api.github.com/repos/owner/repo/git/ref/heads/codex%2Ftask"),
            ]
            self.assertEqual((request.get_method(), request.full_url), expected[index])
            self.assertEqual(timeout, 45)
            return BytesIO(json.dumps(replies[index]).encode())

        with patch("automation.codex_loop.github.urlopen", side_effect=transport):
            github.compare_and_swap_branch("codex/task", "before", "after")
        self.assertEqual(len(calls), 3)
        update = json.loads(calls[1].data)["variables"]["input"]
        self.assertEqual(update["repositoryId"], "repository-id")
        self.assertEqual(update["refUpdates"], [{
            "name": "refs/heads/codex/task", "beforeOid": "before",
            "afterOid": "after", "force": True,
        }])


class PublicationCase(unittest.TestCase):
    def setUp(self):
        self.gh = FakeREST()
        self.job = {"base": "base", "branch": "codex/task", "title": "Task", "number": 1,
                    "key": "T1", "commit_date": "2026-09-05T12:00:00Z",
                    "commit_identity": {"name": "Fixture Author", "email": "author@example.invalid"}}
        self.changes = [{"path": "src/a.py", "mode": "100644", "content": "YQ=="}]

    def test_author_and_committer_use_the_pinned_identity(self):
        self.gh.publish(self.job, self.changes)
        commit = next(body for _, endpoint, body in self.gh.calls if endpoint == "git/commits")
        expected = dict(self.job["commit_identity"], date=self.job["commit_date"])
        self.assertEqual(commit["author"], expected)
        self.assertEqual(commit["committer"], expected)

    def test_missing_or_invalid_identity_fails_before_remote_requests(self):
        for value in (None, {}, {"name": "", "email": "author@example.invalid"},
                      {"name": "Injected\nName", "email": "author@example.invalid"},
                      {"name": "Fixture", "email": "invalid"},
                      {"name": "Fixture", "email": "author@example.invalid", "date": "forged"}):
            with self.subTest(identity=value):
                self.job["commit_identity"] = value
                with self.assertRaises(ValueError):
                    self.gh.publish(self.job, self.changes)
                self.assertEqual(self.gh.calls, [])

    def test_ref_and_pr_unknown_outcome_reconcile(self):
        self.gh.fail_ref_after_write = self.gh.fail_pr_after_write = True
        first = self.gh.publish(self.job, self.changes)
        second = self.gh.publish(self.job, self.changes)
        self.assertEqual(first, second)
        self.assertEqual(sum(method == "POST" and endpoint == "pulls" for method, endpoint, _ in self.gh.calls), 1)
        commits = [body for method, endpoint, body in self.gh.calls if endpoint == "git/commits"]
        self.assertEqual(commits[0], commits[1])

    def test_external_branch_change_is_not_overwritten(self):
        self.gh.branch_sha = "someone-elses-commit"
        with self.assertRaisesRegex(RuntimeError, "changed outside"):
            self.gh.publish(self.job, self.changes)
        self.assertFalse(any(method == "PATCH" for method, _, _ in self.gh.calls))

    def test_race_after_branch_read_atomically_preserves_external_commit(self):
        self.job["head"] = self.gh.branch_sha = "previous-head"
        self.gh.race_head = "external-racing-head"
        with self.assertRaisesRegex(RuntimeError, "Atomic publication rejected"):
            self.gh.publish(self.job, self.changes)
        self.assertEqual(self.gh.branch_sha, "external-racing-head")
        self.assertFalse(any(method == "PATCH" for method, _, _ in self.gh.calls))
        self.assertFalse(self.gh.prs)

    def test_expected_head_replacement_and_lost_response_reconcile(self):
        self.job["head"] = self.gh.branch_sha = "previous-head"
        self.gh.fail_cas_after_write = True
        first = self.gh.publish(self.job, self.changes)
        self.assertEqual(self.gh.branch_sha, "head")
        self.assertEqual(first, self.gh.publish(self.job, self.changes))
        requests = [body for _, endpoint, body in self.gh.calls if endpoint == "graphql"]
        self.assertEqual(len(requests), 1)
        update = requests[0]["variables"]["input"]["refUpdates"][0]
        self.assertEqual(update, {"name": "refs/heads/codex/task", "beforeOid": "previous-head",
                                  "afterOid": "head", "force": True})

    def test_deletion_preserves_null_sha(self):
        self.gh.publish(self.job, [{"path": "src/old.py", "mode": "100644", "content": None}])
        tree = next(body for _, endpoint, body in self.gh.calls if endpoint == "git/trees")
        self.assertIsNone(tree["tree"][0]["sha"])

    def test_merge_uses_exact_expected_head(self):
        calls = []
        def request(method, endpoint, body):
            calls.append((method, endpoint, body))
            return {"merged": True, "sha": "merge"}
        self.gh.request = request
        self.assertEqual(self.gh.merge(10, "verified-head"), "merge")
        self.assertEqual(calls[0][2], {"sha": "verified-head", "merge_method": "squash"})


if __name__ == "__main__":
    unittest.main()
