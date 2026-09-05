"""Exercise exact-byte workspace operations with real Git inside the test sandbox."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from automation.codex_loop.workspace import OPERATIONS
from automation.codex_loop.broker import dispatch


def supervisor_fixture(root):
    """Real supervisor IPC/session/deadlines, inside the enclosing sandbox.

    Registration and the nested Seatbelt launch alone are adapted: nested
    sandbox-exec cannot expand the permissions of this test's outer sandbox.
    This fixture is never selected by production code or pilot receipts.
    """
    return """import os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from automation.codex_loop import broker
from automation.closegraph_loop.sandbox import _execute
root=Path(ROOT)
broker._workspace=lambda value:(root/'run/repo',root/'run',root/'control')
broker.run_sandbox=lambda argv,workspace,timeout,network_ports:_execute(argv,root,dict(os.environ),timeout)
broker.supervisor_main()
""".replace("ROOT", repr(str(root)))


class WorkspaceCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.env = dict(os.environ, GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL="test@example.invalid",
                        GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL="test@example.invalid")
        self.git("init", "-q")
        (self.repo / "a.txt").write_bytes(b"old\r\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD").strip()

    def tearDown(self): self.tmp.cleanup()

    def git(self, *args):
        return subprocess.run(["/usr/bin/git", "-c", "core.hooksPath=/dev/null", *args], cwd=self.repo,
                              env=self.env, check=True, capture_output=True, text=True).stdout

    def operation(self, payload):
        path = self.repo.parent / (self.repo.name + "-payload.json")
        path.write_text(json.dumps(payload))
        try:
            result = subprocess.run([sys.executable, "-I", "-c", OPERATIONS, str(path)],
                                    cwd=self.repo, env=self.env, capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(result.stderr)
            return json.loads(result.stdout)
        finally:
            path.unlink()

    def test_capture_preserves_raw_bytes_executable_mode_and_deletion(self):
        (self.repo / "a.txt").unlink()
        (self.repo / "script").write_bytes(b"#!/bin/sh\nprintf 'exact\\r\\n'\n")
        (self.repo / "script").chmod(0o755)
        result = self.operation({"op": "capture", "base": self.base, "message": "Implement"})
        by_path = {c["path"]: c for c in result["changes"]}
        self.assertIsNone(by_path["a.txt"]["content"])
        self.assertEqual(by_path["script"]["mode"], "100755")
        self.assertEqual(base64.b64decode(by_path["script"]["content"]), (self.repo / "script").read_bytes())
        self.assertFalse(self.operation({"op": "inspect"})["dirty"])


    def test_capture_renames_export_deletions_and_reconstruct_exact_candidate_tree(self):
        source = self.repo / "changes/active"
        (source / "nested").mkdir(parents=True)
        (source / "proposal.md").write_bytes(b"original proposal\r\n")
        executable = source / "nested/tool"
        executable.write_bytes(b"#!/bin/sh\nexit 0\n")
        executable.chmod(0o755)
        (self.repo / "unchanged").write_bytes(b"keep original bytes\x00\r\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "active change")
        base = self.git("rev-parse", "HEAD").strip()
        self.git("config", "diff.renames", "true")
        (self.repo / "archive").mkdir()
        self.git("mv", "a.txt", "archive/renamed file.txt")
        self.git("mv", "changes/active", "archive/completed change")
        candidate = self.operation({"op": "capture", "base": base, "message": "Archive change"})
        # Establish that Git's default presentation really sees renames.
        displayed = self.git("diff", "--name-status", base, candidate["local"])
        self.assertEqual(sum(line.startswith("R100\t") for line in displayed.splitlines()), 3)

        # Rebuild from the base using only the exported delta, like GitHub's
        # base_tree + explicit blob additions/deletions. No candidate checkout
        # or candidate-tree lookup is used to construct the resulting tree.
        index = self.repo / ".git/export-index"
        env = dict(self.env, GIT_INDEX_FILE=str(index))
        def index_git(*args, data=None):
            result = subprocess.run(
                ["/usr/bin/git", "-c", "core.hooksPath=/dev/null", *args],
                cwd=self.repo, env=env, input=data, capture_output=True, check=True,
            )
            return result.stdout.decode().strip()
        index_git("read-tree", base)
        changes = {item["path"]: item for item in candidate["changes"]}
        for item in candidate["changes"]:
            if item["content"] is None:
                index_git("update-index", "--force-remove", "--", item["path"])
            else:
                blob = index_git("hash-object", "-w", "--stdin",
                                 data=base64.b64decode(item["content"]))
                index_git("update-index", "--add", "--cacheinfo", item["mode"], blob, item["path"])
        self.assertEqual(index_git("write-tree"), candidate["tree"])
        deleted = {"a.txt", "changes/active/proposal.md", "changes/active/nested/tool"}
        added = {"archive/renamed file.txt", "archive/completed change/proposal.md",
                 "archive/completed change/nested/tool"}
        self.assertEqual(set(changes), deleted | added)
        self.assertTrue(all(changes[name]["content"] is None for name in deleted))
        self.assertEqual(changes["archive/completed change/nested/tool"]["mode"], "100755")
        self.assertEqual(base64.b64decode(changes["archive/renamed file.txt"]["content"]), b"old\r\n")
        self.assertEqual(self.git("rev-parse", "HEAD^{tree}").strip(), candidate["tree"])

    def test_snapshot_import_is_idempotent_and_refuses_dirty_worker(self):
        blob = b"new\x00exact\r\n"
        tree = self.git("rev-parse", "HEAD^{tree}").strip()
        snapshot = {"sha": "remote", "tree": tree,
                    "files": [{"path": "a.txt", "mode": "100644", "content": base64.b64encode(blob).decode()}]}
        # Force a non-identical claimed tree to exercise materialization (outer adapter compares truth).
        snapshot["tree"] = "not-yet-known"
        first = self.operation({"op": "sync", "snapshot": snapshot})
        snapshot["tree"] = first["tree"]
        second = self.operation({"op": "sync", "snapshot": snapshot})
        self.assertEqual(first, second)
        self.assertEqual((self.repo / "a.txt").read_bytes(), blob)
        (self.repo / "a.txt").write_text("partial worker edit")
        with self.assertRaisesRegex(RuntimeError, "Dirty workspace retained"):
            self.operation({"op": "sync", "snapshot": snapshot})
        self.assertEqual((self.repo / "a.txt").read_text(), "partial worker edit")
        resumed = self.operation({"op": "sync", "snapshot": snapshot, "allow_dirty": True})
        self.assertEqual(resumed["tree"], first["tree"])

    def test_directory_to_file_transition_preserves_unrelated_untracked_content(self):
        (self.repo / "folder/nested").mkdir(parents=True)
        (self.repo / "folder/nested/file.txt").write_text("tracked")
        self.git("add", "-A")
        self.git("commit", "-qm", "directory")
        (self.repo / "untracked.txt").write_text("preserve")
        snapshot = {"sha": "remote", "tree": "different", "files": [
            {"path": "folder", "mode": "100755", "content": base64.b64encode(b"replacement").decode()}]}
        result = self.operation({"op": "sync", "snapshot": snapshot})
        self.assertEqual((self.repo / "folder").read_bytes(), b"replacement")
        self.assertTrue((self.repo / "folder").stat().st_mode & 0o111)
        self.assertEqual((self.repo / "untracked.txt").read_text(), "preserve")
        self.assertEqual(self.git("ls-files").splitlines(), ["folder"])
        snapshot["tree"] = result["tree"]
        self.assertEqual(self.operation({"op": "sync", "snapshot": snapshot}), result)
        snapshot.update(tree="new-tree", files=[
            {"path": "folder/child.txt", "mode": "100644", "content": "eA=="}])
        self.operation({"op": "sync", "snapshot": snapshot})
        self.assertEqual((self.repo / "folder/child.txt").read_bytes(), b"x")
        self.assertEqual((self.repo / "untracked.txt").read_text(), "preserve")

    def test_interrupted_directory_transitions_resume_without_overwriting_untracked_bytes(self):
        import shutil
        (self.repo / "folder").mkdir()
        (self.repo / "folder/tracked.txt").write_text("old")
        self.git("add", "-A")
        self.git("commit", "-qm", "directory")
        # Crash after materialization but before staging the new snapshot.
        shutil.rmtree(self.repo / "folder")
        (self.repo / "folder").write_bytes(b"x")
        snapshot = {"sha": "remote", "tree": "different", "files": [
            {"path": "folder", "mode": "100755", "content": "eA=="}]}
        self.operation({"op": "sync", "allow_dirty": True, "snapshot": snapshot})
        self.assertEqual(self.git("ls-files").splitlines(), ["folder"])
        self.assertTrue((self.repo / "folder").stat().st_mode & 0o111)
        # The reverse transition can also have been materialized before staging.
        (self.repo / "folder").unlink()
        (self.repo / "folder").mkdir()
        (self.repo / "folder/child").write_bytes(b"y")
        (self.repo / "folder/unrelated").write_text("keep")
        snapshot["files"] = [{"path": "folder/child", "mode": "100644", "content": "eQ=="}]
        self.operation({"op": "sync", "allow_dirty": True, "snapshot": snapshot})
        self.assertEqual(self.git("ls-files").splitlines(), ["folder/child"])
        self.assertEqual((self.repo / "folder/child").read_bytes(), b"y")
        self.assertEqual((self.repo / "folder/unrelated").read_text(), "keep")

    def test_directory_collision_keeps_untracked_and_original_tracked_bytes(self):
        (self.repo / "folder").mkdir()
        (self.repo / "folder/tracked.txt").write_text("tracked")
        (self.repo / ".gitignore").write_text("*.local\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "directory")
        (self.repo / "folder/keep.local").write_text("untracked")
        before = self.git("rev-parse", "HEAD")
        with self.assertRaisesRegex(RuntimeError, "Untracked content blocks snapshot"):
            self.operation({"op": "sync", "allow_dirty": True, "snapshot": {
                "sha": "remote", "tree": "different",
                "files": [{"path": "folder", "mode": "100644", "content": "eA=="}]}})
        self.assertEqual(self.git("rev-parse", "HEAD"), before)
        self.assertEqual((self.repo / "folder/tracked.txt").read_text(), "tracked")
        self.assertEqual((self.repo / "folder/keep.local").read_text(), "untracked")
        self.assertEqual((self.repo / "a.txt").read_bytes(), b"old\r\n")

    def test_import_rejects_git_metadata_and_traversal(self):
        for path in (".git/config", "../escape", "/outside"):
            with self.assertRaisesRegex(RuntimeError, "Unsafe path"):
                self.operation({"op": "sync", "snapshot": {"sha": "remote", "tree": "different",
                    "files": [{"path": path, "mode": "100644", "content": "eA=="}]}, "allow_dirty": True})

    def test_clean_filter_cannot_hide_different_physical_test_bytes(self):
        (self.repo / ".gitattributes").write_text("a.txt filter=cloak\n")
        self.git("config", "filter.cloak.clean", "/usr/bin/printf clean")
        self.git("add", "--renormalize", "a.txt")
        self.git("add", "-A")
        self.git("commit", "-qm", "filter configured")
        (self.repo / "a.txt").write_bytes(b"different code could run here")
        self.git("add", "a.txt")  # Clean filter keeps the original blob but updates index stat data.
        self.assertEqual(self.git("status", "--porcelain").strip(), "")
        observed = self.operation({"op": "inspect"})
        self.assertFalse(observed["dirty"])
        self.assertFalse(observed["physical_match"])

    def test_multicommit_task_replay_preserves_every_commit(self):
        (self.repo / "first.txt").write_text("first implementation")
        self.git("add", "-A")
        self.git("commit", "-qm", "first worker commit")
        (self.repo / "second.txt").write_text("second implementation")
        self.git("add", "-A")
        self.git("commit", "-qm", "second worker commit")
        original = self.git("rev-parse", "HEAD").strip()
        candidate = self.operation({"op": "capture", "base": self.base, "message": "complete task"})["local"]
        self.assertEqual(self.git("rev-parse", candidate + "^").strip(), self.base)
        self.assertEqual(self.git("rev-parse", "preserved-before-capture-" + original[:12]).strip(), original)
        self.operation({"op": "checkout", "base": self.base, "candidate": candidate, "checkpoint": "task-preserved"})
        (self.repo / "main.txt").write_text("independent main update")
        self.git("add", "-A")
        self.git("commit", "-qm", "main update")
        result = self.operation({"op": "rebase", "candidate": candidate, "checkpoint": "task-replay"})
        self.assertEqual(result["returncode"], 0)
        self.assertEqual((self.repo / "first.txt").read_text(), "first implementation")
        self.assertEqual((self.repo / "second.txt").read_text(), "second implementation")
        self.assertEqual((self.repo / "main.txt").read_text(), "independent main update")

    def test_rebase_preserves_original_commit_and_keeps_conflicts_for_repair(self):
        (self.repo / "a.txt").write_text("candidate")
        candidate = self.operation({"op": "capture", "base": self.base, "message": "candidate"})["local"]
        self.operation({"op": "checkout", "base": self.base, "candidate": candidate, "checkpoint": "preserved"})
        (self.repo / "a.txt").write_text("new main")
        self.git("add", "-A")
        self.git("commit", "-qm", "main advanced")
        result = self.operation({"op": "rebase", "candidate": candidate, "checkpoint": "preserved-replay"})
        self.assertNotEqual(result["returncode"], 0)
        self.assertEqual(self.git("rev-parse", "preserved").strip(), candidate)
        self.assertIn("<<<<<<<", (self.repo / "a.txt").read_text())


class CloneRuntimeCase(unittest.TestCase):
    def test_real_clone_has_independent_objects_home_tmp_and_test_state(self):
        import shutil
        from automation.closegraph_loop.sandbox import create_workspace, _environment
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            base = root / "base"
            base.mkdir()
            env = _environment(root / "home", root / "tmp", root / "artifacts")
            def git(*args, cwd=base):
                return subprocess.run(["/usr/bin/git", "-c", "core.hooksPath=/dev/null", *args],
                                      cwd=cwd, env=env, check=True, capture_output=True, text=True,
                                      timeout=30).stdout.strip()
            git("init", "-q")
            (base / "fixture.txt").write_bytes(b"independent history")
            git("add", "-A")
            git("commit", "-qm", "fixture")
            first = create_workspace(base, root / "sandboxes", "first")
            second = create_workspace(base, root / "sandboxes", "second")
            self.assertEqual(git("rev-parse", "HEAD", cwd=first), git("rev-parse", "HEAD", cwd=second))
            object_inodes = []
            for repo in (base, first, second):
                self.assertFalse((repo / ".git/objects/info/alternates").exists())
                self.assertFalse((repo / ".git/commondir").exists())
                self.assertFalse((repo / ".git/shallow").exists())
                object_inodes.append({p.stat().st_ino for p in (repo / ".git/objects").rglob("*") if p.is_file()})
            self.assertTrue(all(object_inodes))
            for i, left in enumerate(object_inodes):
                for right in object_inodes[i + 1:]:
                    self.assertFalse(left & right)
            for name in ("home", "tmp", "artifacts"):
                self.assertTrue((first.parent / name).is_dir())
                self.assertTrue((second.parent / name).is_dir())
                (first.parent / name / "state").write_text("first worker only")
                self.assertFalse((second.parent / name / "state").exists())
            shutil.rmtree(base)
            self.assertEqual(git("show", "HEAD:fixture.txt", cwd=first), "independent history")
            self.assertEqual(git("show", "HEAD:fixture.txt", cwd=second), "independent history")


class EnvironmentCase(unittest.TestCase):
    def test_sanitized_environment_runs_module_validation_without_bootstrap(self):
        from automation.closegraph_loop.sandbox import _environment
        with tempfile.TemporaryDirectory() as folder:
            run = Path(folder)
            workspace = run / "repo"
            workspace.mkdir()
            for name in ("home", "tmp", "artifacts"):
                (run / name).mkdir()
            (workspace / "test_local.py").write_text(
                "import unittest\nclass Local(unittest.TestCase):\n"
                " def test_module(self): self.assertTrue(True)\n")
            with patch.dict(os.environ, {"PYTHONSAFEPATH": "1", "PYTHONPATH": "/synthetic/modules",
                                         "GH_TOKEN": "synthetic"}):
                env = _environment(run / "home", run / "tmp", run / "artifacts")
            for name in ("PYTHONSAFEPATH", "PYTHONPATH", "GH_TOKEN"):
                self.assertNotIn(name, env)
            result = subprocess.run(["python3.12", "-m", "unittest", "test_local"],
                                    cwd=workspace, env=env, text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Ran 1 test", result.stderr)

    def test_validated_venv_invocation_path_and_openssl_config_are_preserved(self):
        from automation.closegraph_loop.sandbox import _argv, _environment
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            workspace = root / "repo"
            interpreter = workspace / ".venv/bin/python"
            interpreter.parent.mkdir(parents=True)
            interpreter.symlink_to(Path(sys.executable).resolve())
            env = _environment(root / "home", root / "tmp", root / "artifacts")
            with patch("automation.closegraph_loop.sandbox._toolchain_reads", return_value=(Path(sys.base_prefix),)):
                argv = _argv([str(interpreter), "-c", "pass"], workspace, env, root)
            self.assertEqual(argv[0], str(interpreter))
            self.assertNotEqual(argv[0], str(interpreter.resolve()))
            self.assertEqual(env["OPENSSL_CONF"], "/dev/null")


class CodexBoundaryCase(unittest.TestCase):
    def test_builtin_tools_get_deny_all_profile_without_legacy_read_access(self):
        import tomllib
        from automation.codex_loop.codex import isolation_args
        args = isolation_args()
        config = tomllib.loads("\n".join(args[1::2]))
        self.assertEqual(config["default_permissions"], "closegraph")
        self.assertEqual(config["permissions"]["closegraph"]["filesystem"], {"/": "deny"})
        self.assertFalse(config["permissions"]["closegraph"]["network"]["enabled"])
        self.assertFalse(config["features"]["shell_tool"])
        self.assertEqual(config["web_search"], "disabled")
        self.assertNotIn("sandbox_mode", config)
        self.assertEqual(config["approval_policy"], "never")

    def test_missing_stale_fixture_or_incomplete_pilot_cannot_launch_codex(self):
        from automation.codex_loop.codex import Codex, PILOT_PROBES
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            codex = Codex(root, root / "runs")
            with patch("automation.codex_loop.codex.subprocess.Popen") as launch:
                with self.assertRaisesRegex(RuntimeError, "pilot evidence"):
                    codex.invoke("engineer", {"key": "T1"}, "/synthetic/repo", "task")
                launch.assert_not_called()
            codex.verification = root / "pilot.json"
            identity = {"fixture_identity": True}
            with patch.object(codex, "verification_identity", return_value=identity):
                probes = {name: {"passed": True, "artifact": "fixture-transcript"} for name in PILOT_PROBES}
                for evidence in (
                    {"kind": "fixture", "identity": identity, "probes": probes},
                    {"kind": "installed-cli-pilot", "identity": {"stale": True}, "probes": probes},
                    {"kind": "installed-cli-pilot", "identity": identity, "probes": {}},
                    {"kind": "installed-cli-pilot", "identity": identity,
                     "probes": dict(probes, host_filesystem_tools_denied={"passed": False, "artifact": "failure"})},
                ):
                    codex.verification.write_text(json.dumps(evidence))
                    with self.assertRaises(RuntimeError):
                        codex.require_verified()

    def test_invalid_execution_timeouts_fail_before_process_start(self):
        from automation.closegraph_loop.sandbox import run_sandbox
        from automation.codex_loop.codex import Codex
        with tempfile.TemporaryDirectory() as folder:
            for timeout in (True, 0, -1, float("inf"), float("nan"), 3601):
                with self.assertRaises(ValueError):
                    Codex(folder, Path(folder) / "runs", timeout=timeout)
            with patch("automation.closegraph_loop.sandbox._workspace") as resolve:
                for timeout in (True, 0, -1, float("inf"), float("nan"), 1201):
                    with self.assertRaises(ValueError):
                        run_sandbox(["/usr/bin/true"], folder, timeout=timeout)
                resolve.assert_not_called()


class BrokerCase(unittest.TestCase):

    def test_controller_commands_and_snapshot_transfer_respect_broker_ownership(self):
        import fcntl
        from automation.codex_loop.workspace import Sandbox
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);control=root/'control';control.mkdir();worker=root/'run';(worker/'tmp').mkdir(parents=True)
            sandbox=Sandbox('/base','/sandboxes')
            with (control/'codex-broker-run.lock').open('a') as held:
                fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with patch('automation.codex_loop.workspace._workspace',return_value=(worker/'repo',worker,control)), \
                     patch('automation.codex_loop.workspace.run_owned') as execute:
                    with self.assertRaisesRegex(RuntimeError,'owned'):
                        sandbox.run(str(worker/'repo'),['/usr/bin/true'])
                    with self.assertRaisesRegex(RuntimeError,'owned'):
                        sandbox.operation(str(worker/'repo'),{'op':'inspect'})
                    execute.assert_not_called()
                    self.assertEqual(list((worker/'tmp').iterdir()),[])


    def test_supervisor_returns_command_results_and_cleans_transfers_on_success_and_failure(self):
        from automation.codex_loop.workspace import Sandbox
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            control, worker = root / "control", root / "run"
            control.mkdir()
            (worker / "tmp").mkdir(parents=True)
            sandbox = Sandbox("/base", "/sandboxes")
            with patch("automation.codex_loop.workspace._workspace",
                       return_value=(worker / "repo", worker, control)), \
                 patch("automation.codex_loop.broker.SUPERVISOR_BOOTSTRAP", supervisor_fixture(root)):
                # More than a pipe buffer in both directions exercises IPC,
                # not just short success strings. Nonzero exits are preserved.
                result = sandbox.run(worker / "repo", [sys.executable, "-c",
                    "import sys;print('x'*131072);print('failure',file=sys.stderr);sys.exit(7)"])
                self.assertEqual(result, {"returncode": 7, "stdout": "x" * 131072 + "\n",
                                          "stderr": "failure\n"})
                payload = {"op": "fixture", "data": "x" * 131072}
                code = ("import json,sys;from pathlib import Path;"
                        "print(json.dumps({'payload':json.loads(Path(sys.argv[1]).read_text()),"
                        "'path':sys.argv[1]}))")
                with patch("automation.codex_loop.workspace.OPERATIONS", code):
                    result = sandbox.operation(worker / "repo", payload)
                self.assertEqual(result["payload"], payload)
                self.assertEqual(Path(result["path"]).parent, worker / "tmp")
                self.assertFalse(Path(result["path"]).exists())
                with patch("automation.codex_loop.workspace.OPERATIONS", "raise RuntimeError('fixture failure')"):
                    with self.assertRaisesRegex(RuntimeError, "fixture failure"):
                        sandbox.operation(worker / "repo", payload)
                self.assertEqual(list((worker / "tmp").iterdir()), [])
                with self.assertRaisesRegex(RuntimeError, "FileNotFoundError"):
                    sandbox.run(worker / "repo", [str(root / "missing-executable")])
                result = sandbox.run(worker / "repo", [sys.executable, "-c", "import time;time.sleep(30)"],
                                     timeout=.15)
                self.assertTrue(result["timed_out"])
                self.assertNotEqual(result["returncode"], 0)
                # Failed and timed-out calls released their lock for reuse.
                self.assertEqual(sandbox.run(worker / "repo", ["/usr/bin/true"])["returncode"], 0)

    def test_controller_termination_supervises_commands_and_transfers_through_cleanup(self):
        # Real subprocesses, flock and deadlines under the enclosing test
        # sandbox. Only registration/Seatbelt relaunch are fixture adapters.
        import fcntl
        import signal
        import time
        for operation in (False, True):
            for termination in (signal.SIGTERM, signal.SIGKILL):
                with self.subTest(operation=operation, signal=termination), tempfile.TemporaryDirectory() as folder:
                    root = Path(folder).resolve()
                    (root / "control").mkdir()
                    (root / "run/tmp").mkdir(parents=True)
                    started, late = root / "started", root / "late"
                    code = ("from pathlib import Path;import json,os,time;"
                            "Path(" + repr(str(started)) + ").write_text('started');"
                            "child=os.fork();time.sleep(1.5);"
                            "Path(" + repr(str(late)) + ").write_text('late');print(json.dumps({'ok':True}))")
                    bootstrap = """import fcntl,os,sys
from pathlib import Path
from automation.codex_loop import broker,workspace
from automation.tests.test_codex_workspace import supervisor_fixture
root=Path(sys.argv[1])
workspace._workspace=lambda value:(root/'run/repo',root/'run',root/'control')
broker.SUPERVISOR_BOOTSTRAP=supervisor_fixture(root)
# An unrelated controller lock must not be inherited by the supervisor.
controller_lock=(root/'controller.lock').open('a')
fcntl.flock(controller_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
sandbox=workspace.Sandbox('/base','/sandboxes',timeout=1)
if sys.argv[2]=='operation':
 workspace.OPERATIONS=sys.argv[3]
 sandbox.operation(str(root/'run/repo'),{'op':'fixture'})
else:
 sandbox.run(str(root/'run/repo'),[sys.executable,'-c',sys.argv[3]])
"""
                    process = subprocess.Popen([sys.executable, "-c", bootstrap, str(root),
                                                "operation" if operation else "run", code],
                                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                               start_new_session=True)
                    try:
                        deadline = time.monotonic() + 8
                        while not started.exists() and process.poll() is None and time.monotonic() < deadline:
                            time.sleep(.02)
                        self.assertTrue(started.exists(), "controller command never started")
                        if operation:
                            self.assertEqual(len(list((root / "run/tmp").glob("controller-*.json"))), 1)
                        os.killpg(process.pid, termination)
                        process.wait(timeout=3)
                        with (root / "controller.lock").open("a") as controller_lock:
                            try:
                                fcntl.flock(controller_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                                controller_released = True
                            except BlockingIOError:
                                controller_released = False
                        with (root / "control/codex-broker-run.lock").open("a") as lock:
                            try:
                                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                                owned = False
                            except BlockingIOError:
                                owned = True
                            deadline = time.monotonic() + 4
                            acquired = False
                            while time.monotonic() < deadline:
                                try:
                                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                                    acquired = True
                                    break
                                except BlockingIOError:
                                    time.sleep(.02)
                            # Wait beyond the child's attempted late write,
                            # including on the original faulty implementation.
                            time.sleep(1.65)
                            self.assertTrue(owned, "controller death released an executing workspace")
                            self.assertTrue(controller_released, "supervisor retained an unrelated controller lock")
                            self.assertTrue(acquired, "controller death left an unbounded lock owner")
                            self.assertFalse(late.exists(), "command or descendant escaped its deadline")
                            self.assertEqual(list((root / "run/tmp").iterdir()), [], "transfer cleanup was lost")
                    finally:
                        if process.poll() is None:
                            os.killpg(process.pid, signal.SIGKILL)
                            process.wait(timeout=3)
                        if process.stderr:
                            process.stderr.close()

    def test_broker_termination_retains_lock_until_bounded_command_is_reaped(self):
        # Real process/lock/cancellation test. The executor is patched to the
        # actual bounded process runner; Seatbelt denials are tested separately.
        import fcntl
        import signal
        import time
        for termination in (signal.SIGTERM, signal.SIGKILL):
            with self.subTest(signal=termination), tempfile.TemporaryDirectory() as folder:
                root = Path(folder).resolve()
                (root / 'control').mkdir()
                started, late = root / 'started', root / 'late'
                command = [sys.executable, '-c',
                           'from pathlib import Path;import time;Path(' + repr(str(started)) +
                           ').write_text("started");time.sleep(1.5);Path(' + repr(str(late)) + ').write_text("late")']
                bootstrap = """import json,os,sys
from pathlib import Path
from automation.codex_loop import broker
from automation.tests.test_codex_workspace import supervisor_fixture
root=Path(sys.argv[1])
broker._workspace=lambda workspace:(root/'repo',root/'run',root/'control')
broker.SUPERVISOR_BOOTSTRAP=supervisor_fixture(root)
sys.argv=['broker','--workspace',str(root/'repo')]
broker.main()
"""
                process = subprocess.Popen([sys.executable, '-c', bootstrap, str(root)],
                                           stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.PIPE, text=True, start_new_session=True)
                try:
                    request = {'jsonrpc':'2.0','id':1,'method':'tools/call',
                               'params':{'name':'sandbox_run','arguments':{'argv':command,'timeout':1}}}
                    process.stdin.write(json.dumps(request) + '\n');process.stdin.flush()
                    deadline=time.monotonic()+8
                    while not started.exists() and process.poll() is None and time.monotonic()<deadline:
                        time.sleep(.02)
                    self.assertTrue(started.exists(), 'broker command never started')
                    os.killpg(process.pid,termination);process.wait(timeout=3)
                    with (root/'control/codex-broker-run.lock').open('a') as lock:
                        with self.assertRaises(BlockingIOError):
                            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                        deadline=time.monotonic()+4
                        acquired=False
                        while time.monotonic()<deadline:
                            try:
                                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);acquired=True;break
                            except BlockingIOError:
                                time.sleep(.02)
                        self.assertTrue(acquired,'dead broker left an unbounded lock owner')
                    time.sleep(.65)
                    self.assertFalse(late.exists(),'command escaped its deadline after broker termination')
                finally:
                    if process.poll() is None:
                        os.killpg(process.pid,signal.SIGKILL);process.wait(timeout=3)
                    if process.stdin:process.stdin.close()
                    if process.stderr:process.stderr.close()

    def test_broker_forwards_only_fixed_workspace_and_ports(self):
        with patch("automation.codex_loop.broker.run_sandbox", return_value={"returncode": 0, "stdout": "ok", "stderr": ""}) as run:
            reply = dispatch("tools/call", {"name": "sandbox_run", "arguments": {"argv": ["pwd"], "timeout": 7}},
                             "/fixed/repo", [12345])
            run.assert_called_once_with(["pwd"], "/fixed/repo", timeout=7, network_ports=[12345])
            self.assertFalse(reply["isError"])
        with self.assertRaises(ValueError):
            dispatch("tools/call", {"name": "sandbox_run", "arguments": {"argv": ["pwd"], "workspace": "/other"}}, "/fixed", [])
        with self.assertRaises(ValueError):
            dispatch("tools/call", {"name": "arbitrary"}, "/fixed", [])


if __name__ == "__main__":
    unittest.main()
