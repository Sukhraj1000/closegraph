"""Real macOS Seatbelt tests; synthetic fixtures only, no providers/credentials."""
from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from closegraph_loop import sandbox

PYTHON = str(Path(sys.executable).resolve())
MACOS = sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").is_file()


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cgt-", dir="/private/tmp" if sys.platform == "darwin" else None)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.base = self.root / "base"
        self.base.mkdir()
        self.git("init", "-q", str(self.base), cwd=self.root)
        (self.base / "hello.txt").write_text("synthetic committed content\n")
        self.git("add", ".")
        self.git("-c", "user.name=Synthetic", "-c", "user.email=test@example.invalid", "commit", "-qm", "fixture")
        self.sandboxes = self.root / "sandboxes"

    def git(self, *args, cwd=None):
        return subprocess.run(["/usr/bin/git", "-c", "core.hooksPath=/dev/null", *args], cwd=cwd or self.base,
                              env={"PATH": "/usr/bin:/bin", "HOME": str(self.root), "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"},
                              check=True, capture_output=True, text=True).stdout.strip()

    def workspace(self, name="run-1"):
        return sandbox.create_workspace(self.base, self.sandboxes, name)

    def python(self, code, workspace, **kwargs):
        return sandbox.run_sandbox([PYTHON, "-I", "-c", code], workspace, **kwargs)


class CloneTests(Fixture):
    def test_full_independent_clone_and_isolated_layout(self):
        workspace = self.workspace()
        self.assertEqual(workspace, self.sandboxes / "run-1" / "repo")
        for name in ("repo", "home", "tmp", "artifacts"):
            self.assertTrue((workspace.parent / name).is_dir(), name)
        self.assertTrue((workspace / ".git").is_dir())
        self.assertFalse((workspace / ".git/objects/info/alternates").exists())
        self.assertFalse((workspace / ".git/commondir").exists())
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=workspace), self.git("rev-parse", "HEAD"))
        original_inodes = {p.stat().st_ino for p in (self.base / ".git/objects").rglob("*") if p.is_file()}
        cloned_inodes = {p.stat().st_ino for p in (workspace / ".git/objects").rglob("*") if p.is_file()}
        self.assertTrue(cloned_inodes)
        self.assertFalse(original_inodes & cloned_inodes)
        shutil.rmtree(self.base)
        self.assertEqual(self.git("show", "HEAD:hello.txt", cwd=workspace), "synthetic committed content")

    def test_reject_unsafe_ids_reuse_and_unrelated_roots(self):
        for name in ("", ".", "..", "../escape", "/tmp/escape", "a/b", "a\\b", "a\n", "-option", "x" * 100):
            with self.subTest(name=name), self.assertRaises((ValueError, OSError)):
                self.workspace(name)
        self.workspace()
        with self.assertRaises((ValueError, OSError)):
            self.workspace()
        for root in (self.base, self.base / "nested", self.root, Path("/"), Path.home()):
            with self.subTest(root=root), self.assertRaises((ValueError, OSError)):
                sandbox.create_workspace(self.base, root, "bad-root")

    def test_reject_symlink_inputs_and_uncommitted_repository(self):
        link = self.root / "base-link"
        link.symlink_to(self.base, target_is_directory=True)
        with self.assertRaises((ValueError, OSError)):
            sandbox.create_workspace(link, self.sandboxes, "bad")
        self.sandboxes.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises((ValueError, OSError)):
            self.workspace()
        self.sandboxes.unlink()
        empty = self.root / "empty"
        self.git("init", "-q", str(empty), cwd=self.root)
        with self.assertRaises((ValueError, OSError, subprocess.CalledProcessError)):
            sandbox.create_workspace(empty, self.sandboxes, "empty")

    def test_clone_does_not_run_inherited_git_config_or_repo_hooks(self):
        marker = self.root / "hook-ran"
        hook = self.base / ".git/hooks/post-checkout"
        hook.write_text(f"#!/bin/sh\ntouch '{marker}'\n")
        hook.chmod(0o700)
        template = self.root / "templates"
        (template / "hooks").mkdir(parents=True)
        shutil.copy2(hook, template / "hooks/post-checkout")
        with mock.patch.dict(os.environ, {"GIT_TEMPLATE_DIR": str(template), "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.hooksPath", "GIT_CONFIG_VALUE_0": str(template / "hooks")}):
            workspace = self.workspace()
        self.assertFalse(marker.exists())
        self.assertFalse((workspace / ".git/hooks/post-checkout").exists())


@unittest.skipUnless(MACOS, "Requires actual macOS sandbox-exec; no emulation")
class RuntimeTests(Fixture):
    def test_python_shell_env_and_descendant_boundary(self):
        workspace = self.workspace()
        code = "import os,json,pathlib,subprocess; pathlib.Path('allowed').write_text('ok'); print(json.dumps(dict(os.environ)), flush=True); subprocess.run(['/bin/sh','-c','printf shell-ok'],check=True)"
        with mock.patch.dict(os.environ, {"GH_TOKEN": "SYNTHETIC", "OPENAI_API_KEY": "SYNTHETIC", "SSH_AUTH_SOCK": "/synthetic/socket", "BASH_ENV": "/synthetic/hook", "PYTHONPATH": "/synthetic/modules", "DYLD_INSERT_LIBRARIES": "/synthetic/library", "GIT_CONFIG_COUNT": "1"}):
            result = self.python(code, workspace)
        self.assertEqual(result["returncode"], 0, result)
        self.assertIn("shell-ok", result["stdout"])
        env = json.loads(result["stdout"].splitlines()[0])
        self.assertEqual(env["HOME"], str(workspace.parent / "home"))
        self.assertEqual(env["TMPDIR"].rstrip("/"), str(workspace.parent / "tmp"))
        for key in ("GH_TOKEN", "OPENAI_API_KEY", "SSH_AUTH_SOCK", "BASH_ENV", "PYTHONPATH", "DYLD_INSERT_LIBRARIES", "GIT_CONFIG_COUNT"):
            self.assertNotIn(key, env)
        self.assertEqual((workspace / "allowed").read_text(), "ok")

    def test_git_can_read_and_commit_only_its_independent_clone(self):
        workspace = self.workspace()
        original_head = self.git("rev-parse", "HEAD")
        for args in (["status", "--porcelain"], ["log", "-1", "--format=%H"]):
            result = sandbox.run_sandbox(["/usr/bin/git", *args], workspace)
            self.assertEqual(result["returncode"], 0, result)
            self.assertEqual(result["stderr"], "", result)
        (workspace / "new-synthetic.txt").write_text("SYNTHETIC")
        for args in (["add", "new-synthetic.txt"], ["commit", "-qm", "sandbox synthetic change"]):
            result = sandbox.run_sandbox(["/usr/bin/git", *args], workspace)
            self.assertEqual(result["returncode"], 0, result)
            self.assertEqual(result["stderr"], "", result)
        self.assertEqual(self.git("rev-parse", "HEAD"), original_head)
        self.assertNotEqual(self.git("rev-parse", "HEAD", cwd=workspace), original_head)
        self.assertFalse((self.base / "new-synthetic.txt").exists())

    def test_real_file_denials_and_symlink_escape(self):
        workspace = self.workspace()
        sibling = self.workspace("sibling")
        paths = [self.root / "outside", sibling / "sentinel", self.base / "sentinel",
                 self.sandboxes / ".control" / "sentinel"]
        # The only home file tested is created here; never inspect actual secrets.
        with tempfile.TemporaryDirectory(prefix=".closegraph-synthetic-", dir=Path.home()) as home:
            paths.append(Path(home) / "sentinel")
            for path in paths:
                path.write_text("SYNTHETIC-NOT-A-SECRET")
            (workspace / "escape").symlink_to(paths[0])
            code = f'''import errno,json,pathlib,subprocess
results=[]
for p in {list(map(str, paths + [workspace / "escape"]))!r}:
 for mode in ('r','w'):
  try:
   with open(p,mode) as f:
    if mode == 'w': f.write('escaped')
   results.append([p,mode,0])
  except OSError as e: results.append([p,mode,e.errno])
print(json.dumps(results))
'''
            result = self.python(code, workspace)
            self.assertEqual(result["returncode"], 0, result)
            for path, mode, error in json.loads(result["stdout"]):
                self.assertIn(error, (errno.EPERM, errno.EACCES), (path, mode, error))
            for path in paths:
                self.assertEqual(path.read_text(), "SYNTHETIC-NOT-A-SECRET")
            child = sandbox.run_sandbox(["/bin/sh", "-c", f"exec /bin/cat '{paths[-1]}'"], workspace)
            self.assertNotEqual(child["returncode"], 0, child)

    def test_tool_selector_alias_does_not_grant_directory_reads(self):
        workspace = self.workspace()
        paths = ["/var", "/private/var", "/Users", "/Library", "/private",
                 str(Path.home()), str(self.sandboxes / ".control")]
        code = f'''import os,json
r={{}}
for p in {paths!r}:
 try:os.listdir(p);r[p]=0
 except OSError as e:r[p]=e.errno
print(json.dumps(r))
'''
        result = self.python(code, workspace)
        self.assertEqual(result["returncode"], 0, result)
        rows = json.loads(result["stdout"])
        self.assertEqual(set(rows), set(paths))
        for path, error in rows.items():
            self.assertIn(error, (errno.EPERM, errno.EACCES), (path, error))

    def test_real_network_offline_and_explicit_loopback_only(self):
        workspace = self.workspace()
        with socket.socket() as allowed, socket.socket() as denied:
            for server in (allowed, denied):
                server.bind(("127.0.0.1", 0))
                server.listen()
            port = allowed.getsockname()[1]
            other = denied.getsockname()[1]
            code = f'''import json,socket
r=[]
for host,port in [('127.0.0.1',{port}),('127.0.0.1',{other}),('1.1.1.1',443)]:
 s=socket.socket();s.settimeout(1)
 try: s.connect((host,port));r.append([host,port,0])
 except OSError as e:r.append([host,port,e.errno])
 finally:s.close()
print(json.dumps(r))
'''
            offline = self.python(code, workspace)
            self.assertEqual(offline["returncode"], 0, offline)
            for row in json.loads(offline["stdout"]):
                self.assertIn(row[2], (errno.EPERM, errno.EACCES), row)
            online = self.python(code, workspace, network_ports=(port,))
            self.assertEqual(online["returncode"], 0, online)
            rows = json.loads(online["stdout"])
            self.assertEqual(rows[0][2], 0, rows)
            for row in rows[1:]:
                self.assertIn(row[2], (errno.EPERM, errno.EACCES), row)

    def test_unix_daemon_sockets_blocked_even_with_loopback(self):
        workspace = self.workspace()
        for socket_path in (self.root / "daemon.sock", workspace / "daemon.sock"):
            with self.subTest(path=socket_path), socket.socket(socket.AF_UNIX) as server:
                server.bind(str(socket_path))
                server.listen()
                result = self.python(f"import socket; s=socket.socket(socket.AF_UNIX); s.connect({str(socket_path)!r})", workspace, network_ports=(54321,))
                self.assertNotEqual(result["returncode"], 0, result)
                self.assertIn("PermissionError", result["stderr"])

    def test_reject_unregistered_workspace_symlinks_shell_strings_and_ports(self):
        workspace = self.workspace()
        for path in (self.base, self.root, workspace.parent, workspace / "nested"):
            with self.subTest(path=path), self.assertRaises((ValueError, OSError)):
                sandbox.run_sandbox(["/usr/bin/true"], path)
        for argv in ("echo unsafe", [], [""], ["/missing/program"], ["/usr/bin/true\0"], ["../base/program"]):
            with self.subTest(argv=argv), self.assertRaises((ValueError, OSError)):
                sandbox.run_sandbox(argv, workspace)
        for ports in ((0,), (-1,), (65536,), (True,), ("80",), "80"):
            with self.subTest(ports=ports), self.assertRaises((ValueError, TypeError)):
                sandbox.run_sandbox(["/usr/bin/true"], workspace, network_ports=ports)
        (workspace.parent / "home").rmdir()
        (workspace.parent / "home").symlink_to(self.root)
        with self.assertRaises((ValueError, OSError)):
            sandbox.run_sandbox(["/usr/bin/true"], workspace)

    def test_fail_closed_without_sandbox_exec(self):
        workspace = self.workspace()
        with mock.patch.object(sandbox, "SANDBOX_EXEC", str(self.root / "missing-sandbox-exec")):
            with self.assertRaises((RuntimeError, OSError, ValueError)):
                sandbox.run_sandbox(["/usr/bin/touch", str(workspace / "fallback")], workspace)
        self.assertFalse((workspace / "fallback").exists())

    def test_profile_is_outside_child_writable_run_root(self):
        workspace = self.workspace()
        real_popen = subprocess.Popen
        profiles = []
        def inspect(args, **kwargs):
            if args[0] == sandbox.SANDBOX_EXEC:
                policy = Path(args[args.index("-f") + 1])
                self.assertFalse(policy.is_relative_to(workspace.parent))
                self.assertIn("(deny default)", policy.read_text())
                profiles.append(policy)
            return real_popen(args, **kwargs)
        with mock.patch.object(subprocess, "Popen", side_effect=inspect):
            result = sandbox.run_sandbox(["/usr/bin/true"], workspace)
        self.assertEqual(result["returncode"], 0, result)
        self.assertTrue(profiles)
        self.assertTrue(all(not p.exists() for p in profiles))

    def test_timeout_kills_process_group_and_normal_exit_descendants(self):
        workspace = self.workspace()
        for sleeping_parent in (True, False):
            with self.subTest(timeout=sleeping_parent):
                child_file = workspace / f"child-{sleeping_parent}"
                code = f'''import os,time,pathlib
pid=os.fork()
if pid==0:
 time.sleep(1.2)
 pathlib.Path({str(child_file)!r}).write_text('survived')
else:
 print(pid,flush=True)
 {'time.sleep(20)' if sleeping_parent else 'os._exit(0)'}
'''
                started = time.monotonic()
                result = self.python(code, workspace, timeout=0.35)
                self.assertLess(time.monotonic() - started, 2.5, result)
                if sleeping_parent:
                    self.assertTrue(result.get("timed_out"), result)
                time.sleep(1.3)
                self.assertFalse(child_file.exists(), result)

    def test_self_test_returns_real_structured_evidence(self):
        result = sandbox.self_test(self.base, self.sandboxes)
        self.assertTrue(result["ok"], json.dumps(result, indent=2))
        self.assertTrue(result["probes"])
        self.assertTrue(all(p["passed"] for p in result["probes"].values()), result)
        self.assertIn("limitations", result)


if __name__ == "__main__":
    unittest.main()
