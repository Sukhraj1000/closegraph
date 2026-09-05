"""Minimal MCP stdio server with one fixed-workspace Seatbelt capability.

Launch only from the trusted installed controller. Repository processes never
inherit the model process environment or GitHub token. stdout is protocol only.
"""
from __future__ import annotations
import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from automation.closegraph_loop.sandbox import run_sandbox, _workspace


TOOLS = [{"name": "sandbox_run", "description": "Run an explicit argv inside the assigned isolated CloseGraph workspace. All repository reads, edits, Git operations and tests must use this tool. Shell syntax requires explicit /bin/sh -c. The workspace and loopback capabilities cannot be changed.",
          "inputSchema": {"type": "object", "properties": {
              "argv": {"type": "array", "items": {"type": "string"}, "minItems": 1},
              "timeout": {"type": "integer", "minimum": 1, "maximum": 1200}},
              "required": ["argv"], "additionalProperties": False}}]



# Exec a fresh trusted interpreter rather than running Python after fork in
# the controller's worker threads. Only the workspace lock crosses exec; no
# SQLite, controller lock, or other slot's descriptors survive.
SUPERVISOR_BOOTSTRAP = """import sys
sys.path.insert(0, sys.argv[1])
from automation.codex_loop.broker import supervisor_main
supervisor_main()
"""


def supervisor_main():
    """Retain ownership until sandbox execution AND transfer cleanup finish."""
    os.fstat(int(sys.argv[2]))
    try:
        request = json.load(sys.stdin)
        argv = request["argv"]
        workspace = request["workspace"]
        path = None
        try:
            if "payload" in request:
                _, worker, _ = _workspace(workspace)
                fd, path = tempfile.mkstemp(prefix="controller-", suffix=".json", dir=worker / "tmp")
                with os.fdopen(fd, "w") as out:
                    json.dump(request["payload"], out)
                argv = [*argv, path]
            result = run_sandbox(argv, workspace, timeout=request["timeout"], network_ports=request["ports"])
        finally:
            if path is not None:
                Path(path).unlink(missing_ok=True)
    except BaseException as exc:
        result = {"supervisor_error": type(exc).__name__ + ": " + str(exc)}
    try:
        print(json.dumps(result), flush=True)
    except BrokenPipeError:
        # The controller/broker died. Execution and cleanup have completed;
        # avoid a second failing stdout flush during interpreter shutdown.
        os._exit(0)


def run_owned(argv, workspace, timeout, ports, lock_fd, *, payload=None):
    """A separate session enforces deadlines after caller SIGTERM/SIGKILL.

    The supervisor alone inherits the trusted workspace lock. Repository
    processes run exclusively through run_sandbox with close_fds=True.
    Transfer files are created and removed by the supervisor while it owns
    the lock, including when the requesting controller has already died.
    """
    os.fstat(lock_fd)  # Refuse a missing/closed trusted lock before dispatch.
    request = {"argv": argv, "workspace": os.fspath(workspace), "timeout": timeout, "ports": ports}
    if payload is not None:
        request["payload"] = payload
    encoded = json.dumps(request)  # Refuse unserialisable requests before launch.
    trusted_root = str(Path(__file__).resolve().parents[2])
    process = subprocess.Popen(
        [sys.executable, "-I", "-c", SUPERVISOR_BOOTSTRAP, trusted_root, str(lock_fd)],
        cwd=trusted_root, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, close_fds=True, pass_fds=(lock_fd,),
        start_new_session=True,
        env={k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL")},
    )
    try:
        output, _ = process.communicate(encoded)
    finally:
        # A Python-level cancellation closes pipes but does not cancel the
        # surviving supervisor. It retains ownership through bounded cleanup.
        for stream in (process.stdin, process.stdout):
            stream.close()
        process.wait()
    if process.returncode != 0 or not output:
        raise RuntimeError("Sandbox supervisor did not return a completed command")
    result = json.loads(output)
    if "supervisor_error" in result:
        raise RuntimeError(result["supervisor_error"])
    return result


def dispatch(method, params, workspace, ports, lock_fd=None):
    if method == "initialize":
        return {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                "serverInfo": {"name": "closegraph-sandbox", "version": "1.0.0"}}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "ping":
        return {}
    if method == "tools/call":
        if params.get("name") != "sandbox_run":
            raise ValueError("Unknown tool")
        args = params.get("arguments", {})
        if set(args) - {"argv", "timeout"}:
            raise ValueError("Unknown arguments")
        timeout = args.get("timeout", 120)
        if type(timeout) is not int or not 1 <= timeout <= 1200:
            raise ValueError("Invalid timeout")
        output = (run_owned(args["argv"], workspace, timeout, ports, lock_fd) if lock_fd is not None
                  else run_sandbox(args["argv"], workspace, timeout=timeout, network_ports=ports))
        return {"content": [{"type": "text", "text": json.dumps(output)}],
                "isError": output["returncode"] != 0}
    raise ValueError("Unsupported method")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--workspace", required=True)
    p.add_argument("--port", action="append", type=int, default=[])
    args = p.parse_args()
    _, run, control = _workspace(args.workspace)
    # This trusted lock is outside the worker write subtree. A per-command
    # supervisor also holds it until bounded command cleanup has completed.
    lock = (control / ("codex-broker-" + run.name + ".lock")).open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    for line in sys.stdin:
        try:
            request = json.loads(line)
            if "id" not in request:
                continue
            try:
                result = dispatch(request["method"], request.get("params", {}), args.workspace, args.port, lock.fileno())
                response = {"jsonrpc": "2.0", "id": request["id"], "result": result}
            except Exception as exc:
                response = {"jsonrpc": "2.0", "id": request["id"], "error": {"code": -32602, "message": str(exc)}}
            print(json.dumps(response), flush=True)
        except (ValueError, KeyError):
            print(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Invalid JSON-RPC"}}), flush=True)


if __name__ == "__main__":
    main()
