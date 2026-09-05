"""Fail-closed macOS Seatbelt execution for disposable, independent Git clones.

The controller and this module are trusted. Never import/run the clone's copy of
this controller outside Seatbelt. This is not a VM or a security certification:
allowed toolchains/system resources are readable, CPU/memory/disk are not quota
limited, and an explicitly allowed loopback service is a capability (including
any proxy/SQL functionality it exposes). Only use disposable test services.
"""
from __future__ import annotations

import errno
import json
import math
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import uuid

SANDBOX_EXEC = "/usr/bin/sandbox-exec"
GIT = "/usr/bin/git"
_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
# Do not grant /Users, /Library, /private, /opt or all of /usr/local.
_SYSTEM_READS = (
    "/System", "/bin", "/sbin", "/usr/bin", "/usr/sbin", "/usr/lib",
    "/usr/libexec", "/usr/share", "/Library/Apple/System/Library",
    "/Library/Developer/CommandLineTools", "/Library/Frameworks/Python.framework",
    "/opt/homebrew/Cellar", "/opt/homebrew/opt", "/opt/homebrew/bin",
    "/opt/homebrew/lib", "/opt/homebrew/share", "/usr/local/Cellar",
    "/usr/local/opt", "/usr/local/bin", "/usr/local/lib", "/usr/local/share",
    "/private/var/db/dyld",
)
_SYSTEM_FILES = (
    "/private/etc/localtime", "/private/etc/passwd", "/private/etc/group",
    "/private/etc/hosts", "/private/etc/protocols", "/private/etc/services",
    # Apple's /usr/bin/git and /bin/sh are tool selectors. Read only their
    # selection links, not /private/var or unrelated daemon/configuration data.
    "/private/var/select/developer_dir", "/private/var/select/sh",
    # readlink('/var/select/developer_dir') also checks the /var alias itself.
    # This literal grants symlink data, NOT a /private/var directory listing.
    "/var",
    "/dev/null", "/dev/zero", "/dev/random", "/dev/urandom",
)
LIMITATIONS = [
    "macOS sandbox-exec/Seatbelt is deprecated, host-version dependent, and not a VM or security certification.",
    "The filesystem root directory listing, system binaries/libraries and enumerated Homebrew/Python/uv toolchains are readable; do not store secrets there.",
    "No CPU, memory, disk or process-count quotas; timeout kills the process group, but hostile setsid/double-fork descendants can evade group cleanup while remaining sandboxed.",
    "Explicit IPv4 loopback ports grant access to everything that test service exposes, including any proxy/SQL capabilities; never allow a privileged daemon.",
    "The trusted same-UID controller, its base Git repository, toolchains, and sandbox-root ancestors must not be concurrently modified by unsandboxed adversaries.",
]


def _path(value: str | os.PathLike[str], *, exists: bool = True) -> Path:
    """No lexical traversal or symlink components, including dangling links."""
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or "\0" in raw:
        raise ValueError("Expected a nonempty filesystem path")
    p = Path(raw)
    if not p.is_absolute() or ".." in p.parts:
        raise ValueError("Use an absolute, traversal-free path (resolve system /tmp aliases first)")
    for component in reversed((p, *p.parents)):
        if component.is_symlink():
            raise ValueError(f"Symlink path component is forbidden: {component}")
    if exists and not p.is_dir():
        raise ValueError(f"Directory does not exist: {p}")
    return p


def _private_dir(path: Path, *, create: bool = False) -> None:
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    _path(path)
    info = path.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise ValueError(f"Directory must be owned by this user and not group/world writable: {path}")


def _toolchain_reads() -> tuple[Path, ...]:
    # uv-managed interpreters live in HOME, but granting all of .local leaks
    # other environments. Grant only this trusted interpreter distribution.
    roots: list[Path] = []
    base = Path(sys.base_prefix).resolve()
    uv_python = Path.home() / ".local/share/uv/python"
    if base.is_relative_to(uv_python.resolve()) and base != uv_python.resolve():
        roots.append(base)
    # uv's standalone executable is allowed as a file, not its enclosing HOME.
    uv = Path.home() / ".local/bin/uv"
    if uv.is_file():
        target = uv.resolve()
        if target.is_relative_to(Path.home() / ".local"):
            roots.append(target)
    return tuple(roots)


def _environment(home: Path, tmp: Path, artifacts: Path) -> dict[str, str]:
    runtime_bin = str(Path(sys.executable).resolve().parent)
    return {
        "PATH": f"/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin:{runtime_bin}",
        "HOME": str(home), "TMPDIR": str(tmp), "TMP": str(tmp), "TEMP": str(tmp),
        "CLOSEGRAPH_ARTIFACTS": str(artifacts), "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8",
        # Repository imports are intentional inside Seatbelt (including python -m).
        # The environment is rebuilt here, so host PYTHONPATH/startup hooks cannot leak in.
        "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "OPENSSL_CONF": "/dev/null",
        "XDG_CONFIG_HOME": str(home / ".config"), "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_DATA_HOME": str(home / ".local/share"), "UV_CACHE_DIR": str(home / ".cache/uv"),
        "UV_OFFLINE": "1", "UV_PYTHON_DOWNLOADS": "never", "PIP_NO_INDEX": "1",
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_ATTR_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
        "GIT_AUTHOR_NAME": "CloseGraph Sandbox", "GIT_AUTHOR_EMAIL": "sandbox@example.invalid",
        "GIT_COMMITTER_NAME": "CloseGraph Sandbox", "GIT_COMMITTER_EMAIL": "sandbox@example.invalid",
        "GIT_PAGER": "cat", "PAGER": "cat", "TERM": "dumb",
    }


def _git(args: list[str], cwd: Path, env: dict[str, str]) -> str:
    result = subprocess.run(
        [GIT, "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
         "-c", "protocol.allow=never", "-c", "protocol.file.allow=always", *args],
        cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
        timeout=120, check=True, close_fds=True,
    )
    return result.stdout.strip()


def create_workspace(base_repo: str | os.PathLike[str], sandbox_root: str | os.PathLike[str], run_id: str) -> Path:
    """Clone committed local Git history with --no-local; never reuse a run ID.

    Only the sandbox root, its trusted .control records, and the new run are
    written. No source hooks, templates, inherited Git config, linked objects,
    submodule recursion, credentials or remote fetch are used.
    """
    if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
        raise ValueError("Invalid run_id: use 1-64 ASCII letters/digits/underscore/hyphen, starting alphanumeric")
    base = _path(base_repo)
    root = _path(sandbox_root, exists=False)
    if base.is_relative_to(root) or root.is_relative_to(base):
        raise ValueError("Base repository and sandbox root must be disjoint, not ancestors")
    if root == Path.home() or len(root.parts) < 3:
        raise ValueError("Use a dedicated sandbox root, not a filesystem/home root")
    if not (base / ".git").is_dir() or (base / ".git").is_symlink():
        raise ValueError("Base must be a full non-bare Git repository, not a linked worktree")
    _private_dir(root, create=True)
    control = root / ".control"
    _private_dir(control, create=True)
    record = control / f"{run_id}.json"
    if record.exists() or record.is_symlink():
        raise ValueError("Run ID was already allocated")
    run = root / run_id
    run.mkdir(mode=0o700)  # exclusive reservation: reuse/symlinks fail
    try:
        for name in ("home", "tmp", "artifacts"):
            (run / name).mkdir(mode=0o700)
        env = _environment(run / "home", run / "tmp", run / "artifacts")
        top = _git(["rev-parse", "--show-toplevel"], base, env)
        if Path(top) != base:
            raise ValueError("base_repo must be the exact Git repository root")
        _git(["rev-parse", "--verify", "HEAD^{commit}"], base, env)
        workspace = run / "repo"
        _git(["clone", "--no-local", "--no-hardlinks", "--template=", "--no-recurse-submodules", "--", str(base), str(workspace)], base, env)
        for rel in (".git/commondir", ".git/objects/info/alternates", ".git/shallow"):
            if (workspace / rel).exists():
                raise ValueError(f"Clone is not independent/full: {rel}")
        if any(p.is_symlink() for p in (workspace / ".git").rglob("*")):
            raise ValueError("Symlinks in clone Git metadata are forbidden")
        info = {"version": 1, "workspace": str(workspace), "run_inode": run.stat().st_ino,
                "run_device": run.stat().st_dev, "base_repo": str(base)}
        with record.open("x", encoding="utf-8") as f:
            os.chmod(record, 0o600)
            json.dump(info, f)
        return workspace
    except BaseException:
        # Keep the reserved failed run as evidence; never recursively delete an
        # untrusted tree here or silently recycle an ID.
        raise


def _workspace(value: str | os.PathLike[str]) -> tuple[Path, Path, Path]:
    workspace = _path(value)
    run, root = workspace.parent, workspace.parent.parent
    if workspace.name != "repo" or not _RUN_ID.fullmatch(run.name):
        raise ValueError("Not a registered <sandbox_root>/<run_id>/repo workspace")
    for p in (root, run, root / ".control", workspace, *(run / n for n in ("home", "tmp", "artifacts"))):
        _private_dir(p)
    record = root / ".control" / f"{run.name}.json"
    if record.is_symlink() or not record.is_file():
        raise ValueError("Workspace has no trusted allocation record")
    info_stat = record.stat()
    if info_stat.st_uid != os.getuid() or info_stat.st_mode & 0o022:
        raise ValueError("Unsafe allocation record permissions")
    info = json.loads(record.read_text())
    if (info.get("version"), info.get("workspace"), info.get("run_inode"), info.get("run_device")) != (1, str(workspace), run.stat().st_ino, run.stat().st_dev):
        raise ValueError("Workspace allocation does not match filesystem")
    if not (workspace / ".git").is_dir() or (workspace / ".git").is_symlink():
        raise ValueError("Workspace must retain independent .git directory")
    for rel in (".git/commondir", ".git/objects/info/alternates"):
        if (workspace / rel).exists() or (workspace / rel).is_symlink():
            raise ValueError("Linked Git metadata is forbidden")
    return workspace, run, root / ".control"


def _profile(run: Path, ports: tuple[int, ...]) -> str:
    quote = lambda p: json.dumps(str(p), ensure_ascii=True)
    reads = [f"(subpath {quote(p)})" for p in _SYSTEM_READS]
    for p in _toolchain_reads():
        reads.append(f"({'subpath' if p.is_dir() else 'literal'} {quote(p)})")
    reads += [f"(literal {quote(p)})" for p in _SYSTEM_FILES]
    # Metadata on ancestor directories permits path traversal, not directory
    # listing/data reads. No blanket file-read* on HOME, /private or /Library.
    ancestors = {str(p) for p in run.parents}
    for p in (*_SYSTEM_READS, *_toolchain_reads()):
        ancestors.update(str(a) for a in Path(p).parents)
    metadata = " ".join(f"(literal {quote(p)})" for p in sorted(ancestors))
    network = "\n".join(f'(allow network-outbound (remote ip4 "localhost:{port}"))\n(allow network-inbound (local ip4 "localhost:{port}"))\n(allow network-bind (local ip4 "localhost:{port}"))' for port in ports)
    return f'''(version 1)
(deny default)
(allow process-exec)
(allow process-fork)
(allow signal (target same-sandbox))
(allow sysctl-read)
; macOS runtime startup aborts without the root vnode read. This is a literal,
; not a subtree permission; HOME, /private and sibling data remain denied.
(allow file-read-data (literal "/"))
(allow file-read-metadata {metadata})
(allow file-read* {' '.join(reads)})
(allow file-read* file-write* (subpath {quote(run)}))
(allow file-write-data (literal "/dev/null"))
{network}
'''


def _argv(value, workspace: Path, env: dict[str, str], run: Path) -> list[str]:
    if not isinstance(value, (list, tuple)) or not value or any(not isinstance(a, str) or not a or "\0" in a for a in value):
        raise ValueError("argv must be a nonempty list/tuple of nonempty strings, not a shell command string")
    executable = value[0]
    if "/" in executable:
        candidate = Path(executable)
        if not candidate.is_absolute():
            candidate = workspace / candidate
        if ".." in candidate.parts:
            raise ValueError("Executable traversal is forbidden")
    else:
        found = shutil.which(executable, path=env["PATH"])
        if found is None:
            raise ValueError(f"Executable unavailable in sanitized PATH: {executable}")
        candidate = Path(found)
    resolved = candidate.resolve(strict=True)
    allowed = (run, *(Path(p).resolve() for p in _SYSTEM_READS), *_toolchain_reads())
    if not any(resolved == p or (p.is_dir() and resolved.is_relative_to(p)) for p in allowed):
        raise ValueError(f"Executable is outside allowed workspace/toolchains: {candidate}")
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise ValueError(f"Not an executable file: {candidate}")
    # Validate the resolved target but retain the invocation path: Python uses
    # the venv executable path to discover pyvenv.cfg and installed dependencies.
    return [str(candidate), *value[1:]]


def _execute(command: list[str], cwd: Path, env: dict[str, str], timeout: float) -> dict:
    """Drain pipes without waiting for inherited pipes after the leader exits."""
    start = time.monotonic()
    proc = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            close_fds=True, start_new_session=True)
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    timed_out = False
    selector = selectors.DefaultSelector()
    try:
        for name in buffers:
            pipe = getattr(proc, name)
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, name)
        while proc.poll() is None:
            remaining = timeout - (time.monotonic() - start)
            if remaining <= 0:
                timed_out = True
                break
            for key, _ in selector.select(min(0.05, remaining)):
                data = os.read(key.fd, 65536)
                if data:
                    buffers[key.data].extend(data)
                else:
                    selector.unregister(key.fileobj)
    finally:
        # Kill ordinary descendants on success/error/timeout, not just leader.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
        for key in list(selector.get_map().values()):
            while True:
                try:
                    data = os.read(key.fd, 65536)
                except BlockingIOError:
                    break
                if not data:
                    break
                buffers[key.data].extend(data)
        selector.close()
        if proc.stdout is not None:
            proc.stdout.close()
        if proc.stderr is not None:
            proc.stderr.close()
    result = {"returncode": proc.returncode, **{name: data.decode("utf-8", errors="replace") for name, data in buffers.items()}}
    if timed_out:
        result["timed_out"] = True
    return result


def run_sandbox(argv, workspace, timeout=120, network_ports=()) -> dict:
    """Run argv under a deny-default inherited macOS sandbox, never a fallback.

    network_ports admits ONLY those IPv4 127.0.0.1 ports (client or listener).
    Unix sockets, IPv6, DNS, external network and unlisted ports remain denied.
    Shell execution is explicit argv, e.g. ['/bin/sh', '-c', '...']; startup
    hooks/credentials are neither inherited nor made readable.
    """
    if sys.platform != "darwin" or not Path(SANDBOX_EXEC).is_file() or not os.access(SANDBOX_EXEC, os.X_OK):
        raise RuntimeError("macOS sandbox-exec is required; unsandboxed fallback is forbidden")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 1200:
        raise ValueError("timeout must be finite, positive and at most 1200 seconds")
    if not isinstance(network_ports, (list, tuple)) or any(type(p) is not int or not 1 <= p <= 65535 for p in network_ports):
        raise ValueError("network_ports must be a list/tuple of integer ports 1..65535")
    ports = tuple(sorted(set(network_ports)))
    workspace, run, control = _workspace(workspace)
    env = _environment(run / "home", run / "tmp", run / "artifacts")
    command = _argv(argv, workspace, env, run)
    # The policy is outside every granted write subtree, created exclusively.
    # Never put the policy in run/tmp or let a previous child rewrite it.
    fd, profile = tempfile.mkstemp(prefix="policy-", suffix=".sb", dir=control)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(_profile(run, ports))
        return _execute([SANDBOX_EXEC, "-f", profile, *command], workspace, env, float(timeout))
    finally:
        Path(profile).unlink(missing_ok=True)


def self_test(base_repo, sandbox_root) -> dict:
    """Exercise real enforcement with ONLY newly-created synthetic sentinels.

    A failed launch/parser/interpreter is a failed probe, never a denial pass.
    Artifacts/clone remain in the run; external synthetic fixtures are removed.
    """
    workspace = create_workspace(base_repo, sandbox_root, f"selftest-{uuid.uuid4().hex[:16]}")
    probes: dict[str, dict] = {}
    python = str(Path(sys.executable).resolve())
    with tempfile.TemporaryDirectory(prefix=".closegraph-synthetic-", dir=Path.home()) as home_tmp, tempfile.TemporaryDirectory(prefix="synthetic-", dir=workspace.parent.parent / ".control") as sibling_tmp, tempfile.TemporaryDirectory(prefix="cg-net-", dir="/private/tmp") as socket_tmp:
        home = Path(home_tmp).resolve() / "sentinel"
        sibling = Path(sibling_tmp).resolve() / "sentinel"
        for p in (home, sibling):
            p.write_text("SYNTHETIC-NOT-A-SECRET")
        (workspace / "escape").symlink_to(home)
        code = f'''import errno,json,pathlib,subprocess
r={{}}
p=pathlib.Path('allowed-synthetic');p.write_text('ok');r['workdir_write']={{'passed':p.read_text()=='ok'}}
r['python_execution']={{'passed':True}}
s=subprocess.run(['/bin/sh','-c','printf shell-ok'],capture_output=True,text=True)
r['shell_execution']={{'passed':s.returncode==0 and s.stdout=='shell-ok','returncode':s.returncode,'stderr':s.stderr}}
g=subprocess.run(['/usr/bin/git','status','--porcelain'],capture_output=True,text=True)
r['git_execution']={{'passed':g.returncode==0,'returncode':g.returncode,'stderr':g.stderr}}
for name,p in {[("outside_home", str(home)), ("outside_sibling", str(sibling)), ("symlink_escape", str(workspace / "escape"))]!r}:
 for mode in ('r','w'):
  error=0
  try:
   with open(p,mode): pass
  except OSError as e:error=e.errno
  r[name+'_'+mode]={{'passed':error in (errno.EACCES,errno.EPERM),'errno':error}}
print(json.dumps(r))
'''
        result = run_sandbox([python, "-I", "-c", code], workspace)
        if result["returncode"] == 0:
            try:
                probes.update(json.loads(result["stdout"]))
            except (ValueError, TypeError):
                probes["file_probes"] = {"passed": False, "execution": result}
        else:
            probes["file_probes"] = {"passed": False, "execution": result}
        probes["sentinels_unchanged"] = {"passed": all(p.read_text() == "SYNTHETIC-NOT-A-SECRET" for p in (home, sibling))}
        with socket.socket() as service, socket.socket() as blocked, socket.socket(socket.AF_UNIX) as daemon:
            service.bind(("127.0.0.1", 0)); service.listen()
            blocked.bind(("127.0.0.1", 0)); blocked.listen()
            socket_path = str(Path(socket_tmp) / "daemon.sock")
            daemon.bind(socket_path); daemon.listen()
            port, other = service.getsockname()[1], blocked.getsockname()[1]
            net_code = f'''import errno,json,socket
r={{}}
for name,family,address in [('loopback_allowed',socket.AF_INET,('127.0.0.1',{port})),('loopback_unlisted',socket.AF_INET,('127.0.0.1',{other})),('outbound',socket.AF_INET,('1.1.1.1',443)),('unix_daemon',socket.AF_UNIX,{socket_path!r})]:
 s=socket.socket(family);s.settimeout(1);error=0
 try:s.connect(address)
 except OSError as e:error=e.errno
 finally:s.close()
 r[name]={{'errno':error}}
print(json.dumps(r))
'''
            for name, ports in (("offline", ()), ("restricted", (port,))):
                execution = run_sandbox([python, "-I", "-c", net_code], workspace, network_ports=ports)
                try:
                    if execution["returncode"] != 0:
                        raise ValueError("Probe did not execute")
                    rows = json.loads(execution["stdout"])
                    for target, row in rows.items():
                        expected_allowed = name == "restricted" and target == "loopback_allowed"
                        row["passed"] = row["errno"] == 0 if expected_allowed else row["errno"] in (errno.EPERM, errno.EACCES)
                        probes[f"{name}_{target}"] = row
                except (ValueError, TypeError):
                    probes[f"{name}_network"] = {"passed": False, "execution": execution}
    return {"ok": bool(probes) and all(p["passed"] for p in probes.values()), "workspace": str(workspace),
            "probes": probes, "limitations": LIMITATIONS}
