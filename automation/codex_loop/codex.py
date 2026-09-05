"""Trusted host inference using Codex CLI and a fixed-workspace MCP broker.

The inference process uses host authentication. It is NOT the worker sandbox.
Built-in execution is disabled and a deny-all filesystem permission profile
restricts remaining host tools. Repository commands use the fixed sandbox broker.
An installed-CLI boundary/model pilot is required before worker dispatch.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import math
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

SCHEMA = {"type": "object", "properties": {
    "outcome": {"type": "string", "enum": ["complete", "changes_requested", "blocked"]},
    "summary": {"type": "string"}, "findings": {"type": "array", "items": {"type": "string"}}},
    "required": ["outcome", "summary", "findings"], "additionalProperties": False}


def parse_result(events, final, returncode):
    if returncode:
        raise RuntimeError("Codex did not complete successfully")
    rows = [json.loads(line) for line in events.splitlines() if line.strip()]
    if not any(row.get("type") == "turn.completed" for row in rows):
        raise RuntimeError("Codex has no completed turn event")
    if any(row.get("type") in ("turn.failed", "error") for row in rows):
        raise RuntimeError("Codex reported failure")
    result = json.loads(final)
    if set(result) != {"outcome", "summary", "findings"} or result["outcome"] not in ("complete", "changes_requested", "blocked"):
        raise ValueError("Invalid structured Codex result")
    if not isinstance(result["summary"], str) or not isinstance(result["findings"], list) or not all(isinstance(f, str) for f in result["findings"]):
        raise ValueError("Invalid structured Codex fields")
    return result


# Named filesystem profiles are required; legacy read-only grants host reads.
# No shell/plugin/web fallback is available if this profile is unsupported.
ISOLATION_CONFIG = {
    "approval_policy": "never",
    "default_permissions": "closegraph",
    "permissions.closegraph.filesystem": {"/": "deny"},
    "permissions.closegraph.network.enabled": False,
    "web_search": "disabled",
    "project_doc_max_bytes": 0,
    "agents.enabled": False,
    "features.code_mode_host": True,
    **{"features." + name: False for name in (
        "shell_tool", "apps", "browser_use", "browser_use_external", "computer_use", "multi_agent", "multi_agent_v2", "hooks", "plugins", "view_image", "code_mode", "image_generation", "workspace_dependencies", "skill_search", "skill_mcp_dependency_install")},
}
PILOT_PROBES = (
    "sandbox_broker_available", "allowed_sandbox_write", "outside_access_denied",
    "sibling_access_denied", "secret_access_denied", "symlink_access_denied",
    "network_access_denied", "host_filesystem_tools_denied", "authorized_model_access",
)


def toml_value(value):
    if isinstance(value, dict):
        return "{" + ", ".join(json.dumps(k) + "=" + toml_value(v) for k, v in value.items()) + "}"
    return json.dumps(value)


def isolation_args():
    return [arg for key, value in ISOLATION_CONFIG.items() for arg in ("-c", key + "=" + toml_value(value))]


def _atomic_record(path, value):
    fd, temporary = tempfile.mkstemp(prefix=".record-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _process_identity(pid, timeout=2):
    check = subprocess.run(["/bin/ps", "-ww", "-p", str(int(pid)), "-o", "lstart=", "-o", "command="],
                           cwd="/", capture_output=True, text=True, timeout=timeout, check=False)
    if check.returncode == 0:
        return check.stdout.strip() or None
    if check.returncode == 1 and not check.stderr.strip():
        return None  # ps returns 1 without diagnostics when no PID matches.
    raise RuntimeError("Cannot determine previous Codex process identity: " + check.stderr.strip())


def _record_identity(pid, timeout=2):
    # Metadata collection must not disable deadline enforcement on a host that
    # restricts process enumeration. The job lock remains authoritative; later
    # orphan checks use the durable PID and unique invocation path and fail
    # closed if they cannot query current process identity.
    try:
        return _process_identity(pid, timeout=timeout)
    except (OSError, subprocess.SubprocessError, RuntimeError):
        return None


def _kill_group(pid):
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _supervise(config_path, lock_fd):
    """Fresh trusted interpreter, independent of controller thread/process life."""
    os.fstat(lock_fd)  # The inherited flock precedes every launch/record window.
    config_path = Path(config_path)
    config = json.loads(config_path.read_text())
    folder = config_path.parent
    deadline = config["deadline_monotonic"]
    if not isinstance(deadline, (int, float)) or not math.isfinite(deadline):
        raise ValueError("Invalid supervisor deadline")
    process = None
    reason = None
    error = None
    record = {
        "kind": "supervised-codex-v1", "job": config["job"], "role": config["role"],
        "pid": os.getpid(), "supervisor_pid": os.getpid(),
        "supervisor_identity": _record_identity(os.getpid()),
        "controller_pid": config["controller_pid"], "cli_pid": None, "phase": "initializing",
        "deadline_monotonic": deadline, "started_at": time.time(),
    }

    def cancelled(signum, _frame):
        nonlocal reason
        reason = "deadline" if signum == signal.SIGALRM else "cancelled"

    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGALRM):
        signal.signal(signum, cancelled)
    try:
        _atomic_record(folder / "process.json", record)
        if os.getppid() != config["controller_pid"]:
            reason = "controller_exited"
        elif time.monotonic() >= deadline:
            reason = "deadline"
        if reason is None:
            signal.setitimer(signal.ITIMER_REAL, max(0.001, deadline - time.monotonic()))
            record["phase"] = "launching"
            _atomic_record(folder / "process.json", record)
            with (folder / "events.jsonl").open("w") as stdout, (folder / "stderr.log").open("w") as stderr:
                process = subprocess.Popen(
                    config["argv"], cwd=config["cwd"], env=dict(os.environ),
                    stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                    close_fds=True, start_new_session=True,
                )
                record.update(cli_pid=process.pid, phase="running")
                _atomic_record(folder / "process.json", record)
                record["cli_identity"] = _record_identity(process.pid, timeout=0.5)
                _atomic_record(folder / "process.json", record)
                while reason is None and process.poll() is None:
                    if os.getppid() != config["controller_pid"]:
                        reason = "controller_exited"
                        break
                    if time.monotonic() >= deadline:
                        reason = "deadline"
                        break
                    time.sleep(min(0.02, max(0.001, deadline - time.monotonic())))
                if reason is None:
                    reason = "completed"
    except BaseException as exc:  # noqa: BLE001 — persist failure after unconditional child cleanup
        reason = reason or "supervisor_error"
        error = type(exc).__name__ + ": " + str(exc)
    finally:
        # Also clean ordinary descendants when their CLI leader exits normally.
        # The broker's separate command supervisor retains workspace ownership.
        if process is not None:
            _kill_group(process.pid)
            process.wait()
        signal.setitimer(signal.ITIMER_REAL, 0)
        result = {
            "returncode": process.returncode if process is not None and reason == "completed" else 124,
            "reason": reason or "supervisor_error", "cleanup_completed": True,
            "finished_at": time.time(), "cli_pid": record["cli_pid"],
            "supervisor_pid": os.getpid(),
        }
        if error:
            result["error"] = error
        _atomic_record(folder / "completed.json", result)
        # Closing, not LOCK_UN: the parent shares this open-file description.
        os.close(lock_fd)
    return 0


class Codex:
    def __init__(self, trusted_root, artifacts, executable="codex", settings=None, timeout=3600, ports=(), verification=None):
        self.trusted_root = str(Path(trusted_root).resolve())
        self.artifacts = Path(artifacts).resolve()
        self.executable, self.settings, self.timeout, self.ports = executable, settings or {}, timeout, ports
        self.verification = Path(verification) if verification else None
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 1 <= timeout <= 3600:
            raise ValueError("Codex timeout must be 1..3600 seconds")
        if set(self.settings) - {"model", "model_reasoning_effort", "model_provider"}:
            raise ValueError("Only inherited model settings are accepted")
        self.artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)

    def verification_identity(self):
        executable = shutil.which(self.executable)
        if executable is None:
            raise RuntimeError("Selected Codex CLI is unavailable")
        version = subprocess.run([executable, "--version"], cwd=self.trusted_root,
                                 capture_output=True, text=True, timeout=15, check=True).stdout.strip()
        # Include broker and sandbox implementation: a prior pilot must not
        # activate different tool permissions, model settings or boundary code.
        digest = hashlib.sha256()
        for path in (Path(__file__), Path(__file__).with_name("broker.py"),
                     Path(__file__).parents[1] / "closegraph_loop/sandbox.py"):
            digest.update(path.read_bytes())
        return {"cli_version": version, "executable": str(Path(executable).resolve()),
                "executable_sha256": hashlib.sha256(Path(executable).read_bytes()).hexdigest(),
                "launcher_sha256": digest.hexdigest(), "settings": self.settings,
                "ports": list(self.ports)}

    def require_verified(self):
        if self.verification is None:
            raise RuntimeError("Installed Codex CLI boundary/model pilot evidence is required before activation")
        evidence = json.loads(self.verification.read_text())
        if (evidence.get("kind") != "installed-cli-pilot" or
                evidence.get("identity") != self.verification_identity()):
            raise RuntimeError("Codex pilot evidence does not match this launcher, CLI or model configuration")
        probes = evidence.get("probes", {})
        if any(not isinstance(probes.get(name), dict) or probes[name].get("passed") is not True or
               not probes[name].get("artifact") for name in PILOT_PROBES):
            raise RuntimeError("Codex pilot lacks recorded boundary/model probe evidence")
        # This file is a trusted coordinator runtime receipt, never model output
        # or an engineering approval. Fixture receipts cannot activate the CLI.
        return evidence

    @contextlib.contextmanager
    def owned_job(self, key):
        directory = self.artifacts / "job-locks"
        directory.mkdir(mode=0o700, exist_ok=True)
        lock_path = directory / (hashlib.sha256(key.encode()).hexdigest() + ".lock")
        with lock_path.open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("Codex job is still owned by a controller or CLI supervisor: " + key) from exc
            # Never explicitly unlock: a surviving supervisor shares this FD.
            yield lock.fileno()

    def ensure_idle(self, key):
        for record in self.artifacts.glob("*/process.json"):
            info = json.loads(record.read_text())
            if info["job"] != key or (record.parent / "completed.json").exists():
                continue
            identities = [(info.get("supervisor_pid", info.get("pid")), info.get("supervisor_identity")),
                          (info.get("cli_pid"), info.get("cli_identity"))]
            for pid, expected in identities:
                if pid is None:
                    continue
                actual = _process_identity(pid)
                if actual and str(record.parent) in actual and (expected is None or expected == actual):
                    raise RuntimeError("A previous Codex run is still alive for " + key +
                                       "; preserving its claim/workspace")
            if info.get("phase") == "launching" and info.get("cli_pid") is None:
                raise RuntimeError("Interrupted Codex startup has an unresolved process identity for " + key +
                                   "; preserve its artifacts before retry")

    def _run_supervised(self, args, env, folder, role, job, lock_fd):
        config = folder / "launch.json"
        _atomic_record(config, {
            "argv": args, "cwd": self.trusted_root, "job": job["key"], "role": role,
            "controller_pid": os.getpid(), "deadline_monotonic": time.monotonic() + self.timeout,
        })
        with (folder / "supervisor.stderr.log").open("w") as stderr:
            supervisor = subprocess.Popen(
                [sys.executable, "-I", str(Path(__file__).resolve()), "--supervise",
                 str(config), str(lock_fd)],
                cwd=self.trusted_root, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=stderr, close_fds=True,
                pass_fds=(lock_fd,), start_new_session=True,
            )
            try:
                code = supervisor.wait(timeout=self.timeout + 10)
            except BaseException:
                # Request cancellation; never SIGKILL the owner of a live CLI.
                # If this parent dies, its independent supervisor still enforces
                # the deadline and its inherited lock still blocks new runs.
                with contextlib.suppress(ProcessLookupError):
                    supervisor.terminate()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    supervisor.wait(timeout=5)
                raise
        if code or not (folder / "completed.json").is_file():
            raise RuntimeError("Codex supervisor did not finish cleanup; preserve its job artifacts")
        completed = json.loads((folder / "completed.json").read_text())
        if completed.get("cleanup_completed") is not True:
            raise RuntimeError("Codex supervisor cleanup was not verified")
        return completed["returncode"]

    def invoke(self, role, job, workspace, prompt):
        self.require_verified()
        return self._invoke(role, job, workspace, prompt)

    def pilot(self, workspace, prompt):
        """Trusted coordinator bootstrap only; does not publish, claim or activate jobs.

        Normal controller dispatch always uses invoke and requires a matching
        empirical receipt. The coordinator records this explicit probe's actual
        tool outcomes before issuing such a receipt; no fixture can do that.
        """
        return self._invoke("boundary pilot", {"key": "boundary-pilot", "paths": ["artifacts"]}, workspace, prompt)

    def _invoke(self, role, job, workspace, prompt):
        with self.owned_job(job["key"]) as lock_fd:
            self.ensure_idle(job["key"])
            return self._invoke_owned(role, job, workspace, prompt, lock_fd)

    def _invoke_owned(self, role, job, workspace, prompt, lock_fd):
        run_id = role + "-" + uuid.uuid4().hex
        folder = self.artifacts / run_id
        folder.mkdir(mode=0o700)
        schema, final = folder / "schema.json", folder / "result.json"
        schema.write_text(json.dumps(SCHEMA))
        args = [self.executable, "exec", "--ignore-user-config", "--ignore-rules",
                "--strict-config", "--skip-git-repo-check", "--json", "--color", "never",
                *isolation_args(),
                "--output-schema", str(schema), "--output-last-message", str(final), "-C", str(folder)]
        # Codex filesystem helpers must execute the exact installed binary.
        # Grant no parent directory, user data, broker, Python or control reads.
        executable = shutil.which(self.executable)
        if executable is None:
            raise RuntimeError("Selected Codex CLI is unavailable")
        filesystem = {"/": "deny", str(Path(executable).absolute()): "read", str(Path(executable).resolve()): "read"}
        args += ["-c", "permissions.closegraph.filesystem=" + toml_value(filesystem)]
        # Read back from trusted user config at setup time, not new model selection.
        for name, value in self.settings.items():
            args += ["-c", name + "=" + json.dumps(value)]
        broker_args = ["-m", "automation.codex_loop.broker", "--workspace", workspace]
        for port in self.ports:
            broker_args += ["--port", str(port)]
        args += ["-c", "mcp_servers.closegraph.command=" + json.dumps(sys.executable),
                 "-c", "mcp_servers.closegraph.args=" + json.dumps(broker_args),
                 "-c", "mcp_servers.closegraph.cwd=" + json.dumps(self.trusted_root),
                 "-c", "mcp_servers.closegraph.tool_timeout_sec=1250",
                 "-c", "mcp_servers.closegraph.required=true",
                 "-c", 'mcp_servers.closegraph.enabled_tools=["sandbox_run"]',
                 "-c", 'mcp_servers.closegraph.tools.sandbox_run.approval_mode="approve"']
        instruction = (
            "You are the " + role + " for CloseGraph task " + job["key"] + ". "
            "Use only mcp closegraph sandbox_run for ALL repository inspection, edits, Git and tests. "
            "Your assigned workspace is " + workspace + ". Do not use host filesystem tools, "
            "external messaging, web, credentials, network, or other repositories. "
            "No command or engineering approval is required. Read AGENTS.md and its source-of-truth specs "
            "through sandbox_run. Work only within these owned paths: " + json.dumps(job["paths"]) + ". " +
            ("Inspect the exact candidate diff and rerun relevant tests independently. Return "
             "changes_requested for missing scope, failures or unsupported claims. Do not change files. "
             if role == "independent reviewer" else
             "Implement and repair the assigned scope until its actual relevant checks pass; do not stop "
             "at review findings when you can fix them inside your owned paths. ") +
            "Preserve financial independent-approval requirements. "
            "Do not publish or merge. Findings must contain only actionable defects, never positive observations. A complete outcome must use an empty findings list. Return the structured outcome without claiming unrun tests.\n\n" + prompt)
        args.append(instruction)
        # Do not expose GitHub credentials to model tools or broker environment.
        env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "CODEX_HOME", "TMPDIR", "LANG", "LC_ALL")}
        code = self._run_supervised(args, env, folder, role, job, lock_fd)
        result = parse_result((folder / "events.jsonl").read_text(), final.read_text() if final.exists() else "", code)
        return {**result, "run_id": run_id, "artifacts": str(folder)}


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "--supervise":
        raise SystemExit("This module only exposes the trusted internal CLI supervisor")
    raise SystemExit(_supervise(sys.argv[2], int(sys.argv[3])))
