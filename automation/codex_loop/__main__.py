"""Run a REVIEWED installed copy outside repositories and worker sandboxes."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

from .codex import Codex
from .controller import Controller
from .github import GitHub, validate_commit_identity
from .state import State
from .workspace import Sandbox


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Trusted controller JSON configuration")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    sub.add_parser("dry-run")
    run = sub.add_parser("run")
    run.add_argument("--cycles", type=int, default=1)
    run.add_argument("--interval", type=int, default=10)
    retry = sub.add_parser("retry")
    retry.add_argument("key")
    args = parser.parse_args()
    config_path = Path(args.config).resolve()
    config = json.loads(config_path.read_text())
    root = Path(__file__).resolve().parents[2]
    # The trusted installation must not itself be a Git worker/source checkout.
    if (root / ".git").exists() or any(root.is_relative_to(Path(p).resolve()) for p in (config["base_repo"], config["sandbox_root"])):
        raise RuntimeError("Install the reviewed controller outside Git repositories and sandboxes first")
    state = State(config["state"])
    if args.command == "status":
        print(json.dumps({"halted": state.meta("halted"), "jobs": state.jobs()}, indent=2))
        return
    if args.command == "retry":
        with state.controller_lock():
            job = state.get(args.key)
            if not job or job["stage"] != "paused":
                raise ValueError("Only a paused known job can be retried")
            job["stage"], job["attempts"] = job["resume_stage"], 0
            state.save(job, "retry_requested")
        return
    config["commit_identity"] = validate_commit_identity(config.get("commit_identity"))
    github = GitHub(config.get("repo", "Sukhraj1000/closegraph"))
    sandbox = Sandbox(config["base_repo"], config["sandbox_root"], config.get("test_timeout", 1200), config.get("ports", []), config.get("dependency_seeds", {}))
    codex = Codex(root, config["artifacts"], settings=config.get("inherited_codex_settings", {}),
                  timeout=config.get("codex_timeout", 3600), ports=config.get("ports", []),
                  verification=config.get("codex_verification"))
    controller = Controller(config, state, github, sandbox, codex)
    if args.command == "dry-run":
        print(json.dumps({"main": github.main(), "tasks": controller.ready(), "slots": controller.slots}, indent=2))
    elif args.command == "run":
        if args.cycles < 1:
            raise ValueError("cycles must be positive")
        codex.require_verified()
        controller.run(args.cycles, args.interval)


if __name__ == "__main__":
    main()
