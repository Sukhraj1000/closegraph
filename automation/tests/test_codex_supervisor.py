"""Real harmless process fixtures; these tests do not invoke a model or provider."""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from automation.codex_loop.codex import Codex


class SupervisorCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.artifacts = self.root / "runs"
        self.fixture = self.root / "fixture-cli"
        self.fixture.write_text("#!" + sys.executable + "\n" + r"""
import json,os,subprocess,sys,time
from pathlib import Path
folder=Path(sys.argv[sys.argv.index('-C')+1])
child = subprocess.Popen([sys.executable,'-c',
    "import time;from pathlib import Path;time.sleep(3.0);Path("+repr(str(folder/'late-child'))+").write_text('escaped')"])
(folder/'cli-started.json').write_text(json.dumps({'pid':os.getpid(),'child_pid':child.pid,'environment':dict(os.environ)}))
time.sleep(3.2)
(folder/'late-cli').write_text('escaped')
time.sleep(10)
""")
        self.fixture.chmod(0o700)
        self.bootstrap = """
import os,sys
from pathlib import Path
os.environ.pop('PYTHONSAFEPATH',None)
sys.path.insert(0,sys.argv[1])
from automation.codex_loop.codex import Codex
root=Path(sys.argv[2])
c=Codex(root,root/'runs',executable=str(root/'fixture-cli'),timeout=2)
c._invoke('engineer',{'key':'same-job','paths':['src']},'/synthetic/repo','harmless fixture')
"""
        self.controllers = []
        self.fixture_pids = []

    def tearDown(self):
        for process in self.controllers:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=3)
            if process.stderr:
                process.stderr.close()
        for pid in self.fixture_pids:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def start(self, code=None):
        process = subprocess.Popen(
            [sys.executable, "-c", code or self.bootstrap,
             str(Path(__file__).resolve().parents[2]), str(self.root)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            start_new_session=True,
        )
        self.controllers.append(process)
        return process

    def wait_for(self, predicate, seconds=6):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            result = predicate()
            if result:
                return result
            time.sleep(0.02)
        diagnostics = []
        for process in self.controllers:
            if process.poll() is not None:
                diagnostics.append(process.stderr.read().decode())
        for path in self.artifacts.glob("*/supervisor.stderr.log"):
            diagnostics.append(path.read_text())
        for path in self.artifacts.glob("*/completed.json"):
            diagnostics.append(path.read_text())
        self.fail("Harmless subprocess fixture did not reach the required state: " + repr(diagnostics))

    def started(self):
        matches = list(self.artifacts.glob("*/cli-started.json"))
        return matches[0] if matches else None

    def test_controller_death_cannot_leave_cli_or_ordinary_descendant_past_deadline(self):
        for termination in (signal.SIGTERM, signal.SIGKILL):
            with self.subTest(signal=termination):
                self.artifacts = self.root / ("runs-" + str(termination))
                code = self.bootstrap.replace("root/'runs'", repr(str(self.artifacts)))
                controller = self.start(code)
                marker = self.wait_for(self.started)
                identity = json.loads(marker.read_text())
                self.fixture_pids.append(identity["pid"])
                os.killpg(controller.pid, termination)
                controller.wait(timeout=3)
                time.sleep(3.4)
                self.assertFalse((marker.parent / "late-cli").exists())
                self.assertFalse((marker.parent / "late-child").exists())
                completed = json.loads((marker.parent / "completed.json").read_text())
                self.assertNotEqual(completed["returncode"], 0)
                self.assertIn(completed["reason"], {"controller_exited", "deadline", "cancelled"})
                process = json.loads((marker.parent / "process.json").read_text())
                self.assertEqual(process["job"], "same-job")
                self.assertEqual(process["cli_pid"], identity["pid"])
                self.assertNotEqual(process["supervisor_pid"], controller.pid)

    def test_job_lock_survives_controller_death_before_process_record_exists(self):
        paused = self.root / "paused-before-record"
        code = self.bootstrap.replace(
            "c._invoke(",
            """import automation.codex_loop.codex as module
import fcntl
controller_lock=(root/'controller.lock').open('a')
fcntl.flock(controller_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
real_popen=module.subprocess.Popen
def pause_after_start(args,**kwargs):
    # Stop in a fresh interpreter before the reviewed supervisor module loads.
    # The inherited lock already exists; process.json cannot exist yet.
    stub='''import os,signal,sys
from pathlib import Path
Path(sys.argv[1]).write_text(str(os.getpid()))
os.kill(os.getpid(),signal.SIGSTOP)
os.execv(sys.argv[2],sys.argv[2:])
'''
    process=real_popen([sys.executable,'-I','-c',stub,str(root/'paused-before-record'),*args],**kwargs)
    __import__('time').sleep(20)
    return process
module.subprocess.Popen=pause_after_start
c._invoke("""
        )
        controller = self.start(code)
        self.wait_for(paused.exists)
        supervisor_pid = int(paused.read_text())
        self.assertEqual(list(self.artifacts.glob("*/process.json")), [])
        self.fixture_pids.append(supervisor_pid)
        os.killpg(controller.pid, signal.SIGKILL)
        controller.wait(timeout=3)
        # The supervisor must not retain unrelated controller descriptors.
        import fcntl
        with (self.root / "controller.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        other = Codex(self.root, self.artifacts, executable=str(self.fixture), timeout=1)
        try:
            with patch("automation.codex_loop.codex.subprocess.Popen") as launch:
                with self.assertRaisesRegex(RuntimeError, "owned"):
                    other._invoke("engineer", {"key": "same-job", "paths": ["src"]},
                                  "/synthetic/repo", "must not launch duplicate")
                launch.assert_not_called()
        finally:
            os.kill(supervisor_pid, signal.SIGCONT)
        self.wait_for(lambda: list(self.artifacts.glob("*/completed.json")))

    def test_live_controller_deadline_and_environment_are_supervised(self):
        with patch.dict(os.environ, {"GH_TOKEN": "synthetic", "GITHUB_TOKEN": "synthetic",
                                    "OPENAI_API_KEY": "synthetic", "REDUCTO_API_KEY": "synthetic"}):
            controller = self.start()
        marker = self.wait_for(self.started)
        data = json.loads(marker.read_text())
        self.fixture_pids.append(data["pid"])
        controller.wait(timeout=5)
        self.assertNotEqual(controller.returncode, 0)
        result = json.loads((marker.parent / "completed.json").read_text())
        self.assertEqual(result["reason"], "deadline")
        for name in ("GH_TOKEN", "GITHUB_TOKEN", "OPENAI_API_KEY", "REDUCTO_API_KEY"):
            self.assertNotIn(name, data["environment"])
        time.sleep(1.2)
        self.assertFalse((marker.parent / "late-child").exists())

    def test_success_reaps_ordinary_descendants_and_releases_job_for_reuse(self):
        self.fixture.write_text("#!" + sys.executable + "\n" + r"""
import json,os,subprocess,sys
from pathlib import Path
folder=Path(sys.argv[sys.argv.index('-C')+1])
(folder/'cli-started.json').write_text(json.dumps({'pid':os.getpid()}))
subprocess.Popen([sys.executable,'-c',
    "import time;from pathlib import Path;time.sleep(.7);Path("+repr(str(folder/'late-child'))+").write_text('escaped')"])
Path(sys.argv[sys.argv.index('--output-last-message')+1]).write_text(json.dumps(
    {'outcome':'complete','summary':'fixture completed','findings':[]}))
print(json.dumps({'type':'turn.completed'}),flush=True)
""")
        for _ in range(2):
            controller = self.start()
            controller.wait(timeout=5)
            self.assertEqual(controller.returncode, 0, controller.stderr.read().decode())
        completed = list(self.artifacts.glob("*/completed.json"))
        self.assertEqual(len(completed), 2)
        for path in completed:
            self.assertEqual(json.loads(path.read_text())["reason"], "completed")
            self.assertEqual(json.loads(path.read_text())["returncode"], 0)
        time.sleep(.9)
        self.assertEqual(list(self.artifacts.glob("*/late-child")), [])

    def test_explicit_supervisor_cancellation_cleans_cli_before_releasing_job(self):
        controller = self.start()
        marker = self.wait_for(self.started)
        process_record = marker.parent / "process.json"
        self.wait_for(lambda: json.loads(process_record.read_text()).get("cli_pid"))
        supervisor_pid = json.loads(process_record.read_text())["supervisor_pid"]
        os.kill(supervisor_pid, signal.SIGTERM)
        controller.wait(timeout=5)
        result = json.loads((marker.parent / "completed.json").read_text())
        self.assertEqual(result["reason"], "cancelled")
        self.assertNotEqual(result["returncode"], 0)
        with Codex(self.root, self.artifacts).owned_job("same-job"):
            pass
        time.sleep(3.4)
        self.assertFalse((marker.parent / "late-child").exists())
        self.assertFalse((marker.parent / "late-cli").exists())

    def test_durable_orphan_records_fail_closed_without_rejecting_reused_pid(self):
        folder = self.artifacts / "engineer-unique-invocation"
        folder.mkdir(parents=True)
        record = folder / "process.json"
        identity = "start-time fixture " + str(folder)
        record.write_text(json.dumps({"job": "same-job", "pid": 101, "supervisor_pid": 101,
                                     "supervisor_identity": identity, "cli_pid": 102,
                                     "cli_identity": identity, "phase": "running"}))
        codex = Codex(self.root, self.artifacts)
        # Dead supervisor with a surviving CLI is still a live job.
        with patch("automation.codex_loop.codex._process_identity", side_effect=[None, identity]), \
             self.assertRaisesRegex(RuntimeError, "still alive"):
            codex.ensure_idle("same-job")
        # A reused PID has another start identity and invocation path.
        with patch("automation.codex_loop.codex._process_identity", return_value="new-start other-command"):
            codex.ensure_idle("same-job")
        with patch("automation.codex_loop.codex._process_identity", side_effect=PermissionError("denied")), \
             self.assertRaises(PermissionError):
            codex.ensure_idle("same-job")
        # If the supervisor itself crashed across Popen, absence of a CLI PID
        # cannot be interpreted as absence of a possibly orphaned invocation.
        record.write_text(json.dumps({"job": "same-job", "pid": 101, "phase": "launching"}))
        with patch("automation.codex_loop.codex._process_identity", return_value=None), \
             self.assertRaisesRegex(RuntimeError, "unresolved process identity"):
            codex.ensure_idle("same-job")
        # A process-query failure is not evidence that a process has exited.
        from automation.codex_loop.codex import _process_identity, _record_identity
        for returncode, diagnostics in ((1, "operation denied"), (2, "invalid query")):
            failed = subprocess.CompletedProcess([], returncode, "", diagnostics)
            with patch("automation.codex_loop.codex.subprocess.run", return_value=failed):
                with self.assertRaisesRegex(RuntimeError, "Cannot determine"):
                    _process_identity(102)
                self.assertIsNone(_record_identity(102))
        with patch("automation.codex_loop.codex.subprocess.run",
                   return_value=subprocess.CompletedProcess([], 1, "", "")):
            self.assertIsNone(_process_identity(102))
        # Older records use pid for the CLI and remain recoverable.
        record.write_text(json.dumps({"job": "same-job", "pid": 102}))
        with patch("automation.codex_loop.codex._process_identity", return_value=identity), \
             self.assertRaisesRegex(RuntimeError, "still alive"):
            codex.ensure_idle("same-job")


if __name__ == "__main__":
    unittest.main()
