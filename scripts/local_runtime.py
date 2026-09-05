#!/usr/bin/env python3
"""Repeatable local PostgreSQL + host Seatbelt development services (macOS)."""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import secrets
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
from hashlib import sha256
from pathlib import Path
from urllib.error import URLError
from urllib.parse import quote, urlparse
from urllib.request import ProxyHandler, build_opener

PORTS = {"api": 24180, "ui": 24173, "dagster_web": 24181, "dagster_grpc": 24182}
ORDER = ("api", "dagster_grpc", "dagster_daemon", "dagster_web", "ui")
ENV_KEYS = {
    "CLOSEGRAPH_FUND_MANAGER_PASSWORD", "CLOSEGRAPH_INVESTOR_PASSWORD", "CLOSEGRAPH_PDF_MODE", "CLOSEGRAPH_PDF_CAPTURE_DIR", "CLOSEGRAPH_PDF_GATEWAY_URL", "CLOSEGRAPH_PDF_GATEWAY_TOKEN",
    "COMPOSE_PROJECT_NAME", "CLOSEGRAPH_POSTGRES_IMAGE", "CLOSEGRAPH_POSTGRES_PORT",
    "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD", "CLOSEGRAPH_DATABASE_URL",
    "CLOSEGRAPH_PREPARER_PASSWORD", "CLOSEGRAPH_REVIEWER_PASSWORD", "CLOSEGRAPH_DATA_DIR",
}
SYSTEM_READS = (
    "/System", "/bin", "/sbin", "/usr/bin", "/usr/sbin", "/usr/lib", "/usr/libexec",
    "/usr/share", "/Library/Apple/System/Library", "/Library/Developer/CommandLineTools",
    "/Library/Frameworks/Python.framework", "/opt/homebrew/Cellar", "/opt/homebrew/opt",
    "/opt/homebrew/bin", "/opt/homebrew/lib", "/opt/homebrew/share", "/usr/local/Cellar",
    "/usr/local/opt", "/usr/local/bin", "/usr/local/lib", "/usr/local/share",
    "/private/var/db/dyld",
)
SYSTEM_FILES = (
    "/private/etc/localtime", "/private/etc/passwd", "/private/etc/group", "/private/etc/hosts",
    "/private/etc/protocols", "/private/etc/services", "/private/var/select/developer_dir",
    "/private/var/select/sh", "/var", "/dev/null", "/dev/zero", "/dev/random", "/dev/urandom",
)
HEARTBEAT = (
    "import sys,time;from dagster import DagsterInstance;"
    "i=DagsterInstance.get();h=i.get_daemon_heartbeats();r=i.get_required_daemon_types();"
    "ok=bool(r) and all(k in h and time.time()-h[k].timestamp<120 and not h[k].errors for k in r);"
    "i.dispose();sys.exit(0 if ok else 1)"
)


def private_directory(path):
    path = Path(path)
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError("Runtime directories cannot traverse symlinks")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.stat().st_uid != os.getuid():
        raise ValueError("Runtime directory must be owned by the current user")
    path.chmod(0o700)
    return path


def atomic_json(path, value):
    fd, temporary = tempfile.mkstemp(prefix=".state-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_env(path):
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, raw = line.partition("=")
        if not separator or name not in ENV_KEYS:
            raise ValueError("Unsupported or malformed local environment setting: " + name)
        values[name] = json.loads(raw) if raw.startswith('"') else raw
        if not isinstance(values[name], str) or "\0" in values[name] or "\n" in values[name]:
            raise ValueError("Environment values must be single-line strings")
    return values


def process_identity(pid):
    """Only compare a recorded process identity; never scan/kill services by name."""
    result = subprocess.run(["/bin/ps", "-p", str(int(pid)), "-o", "lstart=", "-o", "command="],
                            cwd="/", capture_output=True, text=True, timeout=5, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def process_alive(record):
    return bool(record and process_identity(record["pid"]) == record.get("identity"))


def tcp_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


class LocalRuntime:
    def __init__(self, project, state_dir=None, env_file=None):
        self.project = Path(project).resolve()
        self.state_dir = Path(state_dir).absolute() if state_dir else self.project / ".local/dev-runtime"
        self.control = self.state_dir / "control"
        self.env_file = Path(env_file).absolute() if env_file else self.state_dir / ".env"
        self.state_file = self.control / "processes.json"
        self.python = self.project / "apps/api/.venv/bin/python"
        self.node = shutil.which("node")
        self.config = {}

    @contextlib.contextmanager
    def locked(self):
        private_directory(self.state_dir)
        private_directory(self.control)
        with (self.control / "runtime.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError("Another local-runtime operation is in progress") from None
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def initialize(self):
        private_directory(self.state_dir)
        private_directory(self.control)
        for name in ("home", "tmp", "data", "dagster", "logs"):
            private_directory(self.state_dir / name)
        if not self.env_file.exists():
            if self.env_file.parent != self.state_dir:
                raise ValueError("An explicit --env-file must already exist")
            database_password = secrets.token_urlsafe(24)
            values = {
                "COMPOSE_PROJECT_NAME": "closegraph-" + sha256(str(self.state_dir).encode()).hexdigest()[:10],
                "CLOSEGRAPH_POSTGRES_IMAGE": "postgres:16-alpine", "CLOSEGRAPH_POSTGRES_PORT": "55432",
                "POSTGRES_DB": "closegraph", "POSTGRES_USER": "closegraph",
                "POSTGRES_PASSWORD": database_password,
                "CLOSEGRAPH_DATABASE_URL": "postgresql+psycopg://closegraph:" + quote(database_password, safe="") +
                                         "@127.0.0.1:55432/closegraph",
                "CLOSEGRAPH_PREPARER_PASSWORD": secrets.token_urlsafe(18),
                "CLOSEGRAPH_REVIEWER_PASSWORD": secrets.token_urlsafe(18),
                "CLOSEGRAPH_FUND_MANAGER_PASSWORD": secrets.token_urlsafe(18),
                "CLOSEGRAPH_INVESTOR_PASSWORD": secrets.token_urlsafe(18),
                "CLOSEGRAPH_DATA_DIR": str(self.state_dir / "data"),
            }
            fd = os.open(self.env_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as stream:
                for name, value in values.items():
                    stream.write(name + "=" + json.dumps(value) + "\n")
        self.load()
        workspace = self.control / "workspace.yaml"
        workspace.write_text(
            "load_from:\n  - grpc_server:\n      host: 127.0.0.1\n      port: 24182\n"
            "      location_name: closegraph\n"
        )
        workspace.chmod(0o600)
        instance = self.state_dir / "dagster/dagster.yaml"
        if not instance.exists():
            instance.write_text("telemetry:\n  enabled: false\nrun_queue:\n  max_concurrent_runs: 3\nrun_monitoring:\n  enabled: true\n")
            instance.chmod(0o600)
        return {"initialized": True, "env_file": str(self.env_file),
                "state_dir": str(self.state_dir), "credentials": "Local role passwords are in the private env file"}

    def load(self):
        info = self.env_file.stat()
        if self.env_file.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("Local environment must be an owner-controlled regular file")
        if info.st_mode & 0o077:
            raise ValueError("Local environment must be private: chmod 600 the explicit env file")
        self.config = read_env(self.env_file)
        required = {"POSTGRES_PASSWORD", "CLOSEGRAPH_DATABASE_URL", "CLOSEGRAPH_PREPARER_PASSWORD",
                    "CLOSEGRAPH_REVIEWER_PASSWORD", "CLOSEGRAPH_DATA_DIR", "COMPOSE_PROJECT_NAME"}
        if any(not self.config.get(name) or self.config[name].startswith("replace-") for name in required):
            raise ValueError("Generate real local credentials with init or supply a complete private env file")
        database = urlparse(self.config["CLOSEGRAPH_DATABASE_URL"])
        if database.hostname not in ("127.0.0.1", "localhost") or not database.scheme.startswith("postgresql"):
            raise ValueError("This development runtime only accepts loopback PostgreSQL")
        port = int(self.config.get("CLOSEGRAPH_POSTGRES_PORT", "55432"))
        if not 1 <= port <= 65535 or (database.port or 5432) != port:
            raise ValueError("Database URL and PostgreSQL published port must match")
        if self.config["CLOSEGRAPH_PREPARER_PASSWORD"] == self.config["CLOSEGRAPH_REVIEWER_PASSWORD"]:
            raise ValueError("Preparer and reviewer must have distinct local passwords")
        data = Path(self.config["CLOSEGRAPH_DATA_DIR"])
        data = data if data.is_absolute() else self.project / data
        if not data.resolve().is_relative_to(self.state_dir.resolve()):
            raise ValueError("CLOSEGRAPH_DATA_DIR must stay inside this runtime's --state-dir")
        self.config["CLOSEGRAPH_DATA_DIR"] = str(data.resolve())
        return self.config

    def records(self):
        return json.loads(self.state_file.read_text()) if self.state_file.exists() else {"services": {}, "database_managed": False}

    def save(self, records):
        atomic_json(self.state_file, records)

    def compose(self, *args):
        if not shutil.which("docker"):
            raise RuntimeError("Docker Desktop/Compose is unavailable; install/start it or use up --no-db with configured PostgreSQL")
        # Docker is invoked only by this user-run parent, outside every child Seatbelt profile.
        command = ["docker", "compose", "--env-file", str(self.env_file), "-f", str(self.project / "compose.yaml"), *args]
        result = subprocess.run(command, cwd=self.project, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=120, check=False,
                                env={**os.environ, **self.config})
        if result.returncode:
            raise RuntimeError("Docker Compose failed: " + result.stderr[-3000:])
        return result.stdout.strip()

    def semaphore_prefix(self):
        return "/cg" + sha256(str(self.state_dir.resolve()).encode()).hexdigest()[:10]

    def commands(self):
        python = str(self.python)
        workspace = str(self.control / "workspace.yaml")
        return {
            "dagster_grpc": [python, "-c", "import multiprocessing,os; multiprocessing.current_process()._config['semprefix']=os.environ['CLOSEGRAPH_IPC_PREFIX']; import runpy; runpy.run_module('dagster',run_name='__main__')", "api", "grpc", "-h", "127.0.0.1", "-p", "24182",
                            "-m", "closegraph.pipeline.location", "--location-name", "closegraph",
                            "--use-python-environment-entry-point"],
            "dagster_daemon": [python, "-c", "from dagster._daemon.cli import main; main()", "run", "-w", workspace],
            "dagster_web": [python, "-m", "dagster_webserver", "-w", workspace, "-h", "127.0.0.1", "-p", "24181"],
            "api": [python, "-m", "uvicorn", "closegraph.runtime:app_factory", "--factory",
                    "--host", "127.0.0.1", "--port", "24180"],
            "ui": [self.node or "node", str(self.project / "apps/web/node_modules/vite/bin/vite.js"),
                   "--host", "127.0.0.1", "--port", "24173", "--strictPort"],
        }

    def environment(self, service):
        environment = {
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin:" + str(self.python.parent),
            "HOME": str(self.state_dir / "home"), "TMPDIR": str(self.state_dir / "tmp"),
            "TMP": str(self.state_dir / "tmp"), "TEMP": str(self.state_dir / "tmp"),
            "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8", "OPENSSL_CONF": "/dev/null",
            "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(self.project / "apps/api/src"),
            "DAGSTER_HOME": str(self.state_dir / "dagster"), "DAGSTER_TELEMETRY_ENABLED": "false",
            "CLOSEGRAPH_IPC_PREFIX": self.semaphore_prefix(),
            "CLOSEGRAPH_API_URL": "http://127.0.0.1:24180",
        }
        if service == "ui":
            # Native FSEvents notifications are unavailable under the local profile.
            environment.update(CHOKIDAR_USEPOLLING="true", CHOKIDAR_INTERVAL="500")
        if service != "ui":
            environment.update({name: self.config[name] for name in (
                "CLOSEGRAPH_DATABASE_URL", "CLOSEGRAPH_PREPARER_PASSWORD",
                "CLOSEGRAPH_REVIEWER_PASSWORD", "CLOSEGRAPH_DATA_DIR")})
            for name in ("CLOSEGRAPH_FUND_MANAGER_PASSWORD", "CLOSEGRAPH_INVESTOR_PASSWORD", "CLOSEGRAPH_PDF_MODE", "CLOSEGRAPH_PDF_CAPTURE_DIR", "CLOSEGRAPH_PDF_GATEWAY_URL", "CLOSEGRAPH_PDF_GATEWAY_TOKEN"):
                if name in self.config:
                    environment[name] = self.config[name]
        return environment

    def profile(self):
        if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").is_file():
            raise RuntimeError("macOS Seatbelt is required; there is no unsandboxed service fallback")
        quote_path = lambda path: json.dumps(str(path))
        reads = [Path(path) for path in SYSTEM_READS] + [self.project, self.python.resolve().parent.parent]
        if self.node:
            reads.append(Path(self.node).resolve().parent.parent)
        writes = [self.state_dir / name for name in ("home", "tmp", "data", "dagster", "logs")]
        writes.append(Path(self.config["CLOSEGRAPH_DATA_DIR"]))
        for name in (".vite", ".vite-temp"):
            cache = self.project / "apps/web/node_modules" / name
            private_directory(cache)
            writes.append(cache)
        ancestors = {parent for path in reads + writes for parent in path.parents}
        ports = sorted({24183, *PORTS.values(), int(self.config.get("CLOSEGRAPH_POSTGRES_PORT", "55432"))})
        network = "\n".join(
            f'(allow network-outbound (remote ip4 "localhost:{port}"))\n'
            f'(allow network-inbound (local ip4 "localhost:{port}"))\n'
            f'(allow network-bind (local ip4 "localhost:{port}"))' for port in ports)
        return (
            "(version 1)\n(deny default)\n(allow process-exec)\n(allow process-fork)\n"
            "(allow signal (target same-sandbox))\n(allow sysctl-read)\n"
            '(allow file-read-data (literal "/"))\n'
            "(allow file-read-metadata " + " ".join("(literal " + quote_path(p) + ")" for p in sorted(ancestors)) + ")\n"
            "(allow file-read* " + " ".join("(subpath " + quote_path(p) + ")" for p in reads) + " " +
            " ".join("(literal " + quote_path(p) + ")" for p in SYSTEM_FILES) + ")\n"
            "(allow file-read* file-write* " + " ".join("(subpath " + quote_path(p) + ")" for p in writes) + ")\n"
            '(allow file-write-data (literal "/dev/null"))\n' +
            '(allow ipc-posix-sem (ipc-posix-name-prefix ' + quote_path(self.semaphore_prefix()) + '))\n' + network + "\n"
        )

    def launch(self, service, argv, records):
        policy = self.control / (service + ".sb")
        policy.write_text(self.profile())
        policy.chmod(0o600)
        log = self.state_dir / "logs" / (service + ".log")
        with log.open("ab") as stream:
            log.chmod(0o600)
            process = subprocess.Popen(["/usr/bin/sandbox-exec", "-f", str(policy), *argv],
                cwd=self.project / "apps/web" if service == "ui" else self.project,
                env=self.environment(service), stdin=subprocess.DEVNULL, stdout=stream, stderr=stream,
                close_fds=True, start_new_session=True)
        # Capture identity after sandbox-exec has executed its target.
        identity = None
        deadline = time.monotonic() + 5
        while process.poll() is None and time.monotonic() < deadline:
            identity = process_identity(process.pid)
            if identity and "/usr/bin/sandbox-exec " not in identity:
                break
            time.sleep(0.05)
        if process.poll() is not None or not identity or "/usr/bin/sandbox-exec " in identity:
            if process.poll() is None:
                process.terminate()
            raise RuntimeError(service + " exited at startup; inspect " + str(log))
        record = {"pid": process.pid, "identity": identity, "log": str(log), "argv": argv,
                  "started_at": time.time()}
        records["services"][service] = record
        self.save(records)
        return record

    def healthy(self, service, record):
        if not process_alive(record):
            return False
        if service == "dagster_grpc":
            return tcp_open(PORTS[service])
        if service == "dagster_daemon":
            result = subprocess.run(["/usr/bin/sandbox-exec", "-f", str(self.control / (service + ".sb")),
                                     str(self.python), "-c", HEARTBEAT],
                cwd=self.project, env=self.environment(service), capture_output=True, timeout=15, check=False)
            return result.returncode == 0
        path = "/api/health" if service == "api" else "/"
        try:
            with build_opener(ProxyHandler({})).open("http://127.0.0.1:" + str(PORTS[service]) + path,
                                                   timeout=2) as response:
                return response.status == 200
        except (URLError, OSError):
            return False

    def stop_service(self, service, records):
        record = records["services"].get(service)
        if process_alive(record):
            os.killpg(record["pid"], signal.SIGTERM)
            deadline = time.monotonic() + 10
            while process_alive(record) and time.monotonic() < deadline:
                time.sleep(0.1)
            if process_alive(record):
                os.killpg(record["pid"], signal.SIGKILL)
        # A reused PID is never signalled.
        records["services"].pop(service, None)
        self.save(records)

    def up(self, no_db=False):
        self.initialize()
        if not self.python.is_file() or not self.node:
            raise RuntimeError("Install the locked Python environment and Node.js before startup")
        if not (self.project / "apps/web/node_modules/vite/bin/vite.js").is_file():
            raise RuntimeError("Run npm ci --prefix apps/web before startup")
        records = self.records()
        for service, port in PORTS.items():
            if tcp_open(port) and not process_alive(records["services"].get(service)):
                raise RuntimeError(f"Port {port} belongs to another process; it has not been stopped")
        if not no_db:
            self.compose("up", "-d", "--wait", "--wait-timeout", "60", "postgres")
            records["database_managed"] = True
            self.save(records)
        elif not tcp_open(int(self.config.get("CLOSEGRAPH_POSTGRES_PORT", "55432"))):
            raise RuntimeError("Configured external PostgreSQL is not listening")
        started = []
        try:
            for service in ORDER:
                existing = records["services"].get(service)
                if self.healthy(service, existing):
                    continue
                if process_alive(existing):
                    self.stop_service(service, records)
                record = self.launch(service, self.commands()[service], records)
                started.append(service)
                deadline = time.monotonic() + 90
                while not self.healthy(service, record):
                    if not process_alive(record) or time.monotonic() >= deadline:
                        raise RuntimeError(service + " failed its health check; inspect " + record["log"])
                    time.sleep(1)
            return self.status()
        except BaseException:
            for service in reversed(started):
                self.stop_service(service, records)
            raise

    def down(self, keep_db=False):
        if not self.env_file.exists():
            return {"stopped": True, "initialized": False, "database_retained": True}
        self.load()
        records = self.records()
        for service in reversed(ORDER):
            self.stop_service(service, records)
        if records.get("database_managed") and not keep_db:
            self.compose("stop", "postgres")
            records["database_managed"] = False
            self.save(records)
        return {"stopped": True, "database_retained": True, "logs": str(self.state_dir / "logs")}

    def status(self):
        if not self.env_file.exists():
            return {"initialized": False, "state_dir": str(self.state_dir)}
        self.load()
        records = self.records()
        statuses = {}
        for service in ORDER:
            record = records["services"].get(service)
            running = process_alive(record)
            statuses[service] = {"running": running, "healthy": self.healthy(service, record) if running else False,
                                 "pid": record["pid"] if running else None,
                                 "log": record["log"] if record else None}
        return {"initialized": True, "state_dir": str(self.state_dir), "services": statuses,
                "postgres_listening": tcp_open(int(self.config.get("CLOSEGRAPH_POSTGRES_PORT", "55432"))),
                "urls": {"application": "http://127.0.0.1:24173", "api": "http://127.0.0.1:24180",
                         "dagster": "http://127.0.0.1:24181"}}


def self_test():
    """No Docker or server launch; verify ownership, secrets, profiles and process guards."""
    import unittest
    from unittest.mock import patch

    class Tests(unittest.TestCase):
        def test_init_is_repeatable_and_secrets_are_private(self):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                runtime = LocalRuntime(root)
                runtime.initialize()
                first = runtime.env_file.read_bytes()
                runtime.initialize()
                self.assertEqual(runtime.env_file.read_bytes(), first)
                self.assertEqual(runtime.env_file.stat().st_mode & 0o777, 0o600)
                self.assertNotEqual(runtime.config["CLOSEGRAPH_PREPARER_PASSWORD"],
                                    runtime.config["CLOSEGRAPH_REVIEWER_PASSWORD"])
                self.assertEqual((runtime.control / "workspace.yaml").read_text().count("grpc_server:"), 1)

        def test_explicit_environment_requires_private_permissions(self):
            with tempfile.TemporaryDirectory() as directory:
                runtime = LocalRuntime(directory)
                runtime.initialize()
                runtime.env_file.chmod(0o644)
                with self.assertRaisesRegex(ValueError, "must be private"):
                    runtime.load()

        def test_shutdown_before_initialization_is_repeatable(self):
            with tempfile.TemporaryDirectory() as directory:
                runtime = LocalRuntime(directory)
                self.assertTrue(runtime.down()["stopped"])
                self.assertTrue(runtime.down()["stopped"])

        def test_child_environments_have_no_host_credentials_or_docker_capability(self):
            with tempfile.TemporaryDirectory() as directory:
                runtime = LocalRuntime(directory)
                runtime.initialize()
                with patch.dict(os.environ, {"GH_TOKEN": "fake", "REDUCTO_API_KEY": "fake"}):
                    for service in ORDER:
                        child = runtime.environment(service)
                        self.assertNotIn("GH_TOKEN", child)
                        self.assertNotIn("REDUCTO_API_KEY", child)
                        self.assertNotIn("DOCKER_HOST", child)
                    self.assertNotIn("CLOSEGRAPH_DATABASE_URL", runtime.environment("ui"))

        def test_pdf_configuration_goes_only_to_backend_services(self):
            with tempfile.TemporaryDirectory() as directory:
                runtime = LocalRuntime(directory)
                runtime.initialize()
                runtime.config.update(CLOSEGRAPH_PDF_MODE="CAPTURED_REPLAY",
                                      CLOSEGRAPH_PDF_CAPTURE_DIR=str(runtime.state_dir / "capture"))
                self.assertEqual(runtime.environment("api")["CLOSEGRAPH_PDF_MODE"], "CAPTURED_REPLAY")
                self.assertNotIn("CLOSEGRAPH_PDF_MODE", runtime.environment("ui"))

        def test_reused_process_id_is_not_signalled(self):
            with tempfile.TemporaryDirectory() as directory:
                runtime = LocalRuntime(directory)
                runtime.initialize()
                records = {"services": {"api": {"pid": 123, "identity": "old-process"}}}
                with patch(__name__ + ".process_identity", return_value="different-process"), patch("os.killpg") as kill:
                    runtime.stop_service("api", records)
                    kill.assert_not_called()

        def test_environment_parser_never_sources_shell_commands(self):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "env"
                path.write_text('POSTGRES_PASSWORD="literal $(command) text"\n')
                self.assertEqual(read_env(path)["POSTGRES_PASSWORD"], "literal $(command) text")
                path.write_text("LD_PRELOAD=/malicious\n")
                with self.assertRaises(ValueError):
                    read_env(path)

        def test_every_host_listener_binds_loopback_and_workspace_is_explicit(self):
            runtime = LocalRuntime("/tmp/synthetic-closegraph")
            commands = runtime.commands()
            for name in ("api", "ui", "dagster_web", "dagster_grpc"):
                self.assertIn("127.0.0.1", commands[name])
            self.assertIn("closegraph.pipeline.location", commands["dagster_grpc"])
            self.assertIn(str(runtime.control / "workspace.yaml"), commands["dagster_daemon"])
            self.assertIn(str(runtime.control / "workspace.yaml"), commands["dagster_web"])

    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests))
    return 0 if result.wasSuccessful() else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--state-dir", help="Dedicated runtime state; defaults to .local/dev-runtime")
    parser.add_argument("--env-file", help="Existing explicit private environment file")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    up = sub.add_parser("up")
    up.add_argument("--no-db", action="store_true", help="Use already running configured local PostgreSQL")
    down = sub.add_parser("down")
    down.add_argument("--keep-db", action="store_true")
    sub.add_parser("status")
    sub.add_parser("self-test")
    args = parser.parse_args()
    if args.command == "self-test":
        return self_test()
    runtime = LocalRuntime(args.project, args.state_dir, args.env_file)
    if args.command == "status":
        result = runtime.status()
    else:
        with runtime.locked():
            if args.command == "init":
                result = runtime.initialize()
            elif args.command == "up":
                result = runtime.up(args.no_db)
            else:
                result = runtime.down(args.keep_db)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
