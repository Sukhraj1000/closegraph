# Codex engineering runner

The runner implements persisted task/file claims, up to three worker slots, a separate Codex reviewer, exact GitHub tree publication, serial expected-head squash merges, and post-merge checks. Standing authorization removes interactive engineering approvals. Financial approvals in CloseGraph remain unchanged.

Run a reviewed, installed copy of `automation/` outside the source repository and worker sandboxes. The installed controller, configuration, toolchain and state are trusted. Never import the worker's controller source on the credentialed host. This is a local command-line controller, not a hosted service or scheduler.

## Boundary and actual capabilities

The trusted host Codex process uses the user's existing authentication and inherited model settings. It is **not** inside Seatbelt. Its built-in shell tool is disabled. Remaining built-in filesystem tools receive a named permission profile that denies access to `/`; web search and host tool integrations are disabled. The launcher uses strict configuration parsing and never falls back to the legacy read-only profile, which allows host reads. Repository tools execute through a fixed-workspace stdio MCP broker, which invokes the existing deny-default Seatbelt executor with a sanitized environment. Workers receive no GitHub credentials. The broker holds an exclusive lock outside the worker write subtree. Broker calls, controller validation commands and snapshot transfers all use a trusted supervisor in a separate process session. It starts a fresh interpreter and inherits only the workspace lock, avoiding Python execution after fork in the controller's worker threads and inheritance of unrelated controller/slot locks. CLI, broker or controller termination leaves the supervisor enforcing the command deadline and cleaning up ordinary descendants; another caller cannot acquire the workspace until cleanup finishes. The supervisor creates and removes snapshot transfer files while retaining ownership, even if the controller dies. Repository commands do not inherit the lock descriptor. Only this fixed capability has `mcp_servers.closegraph.tools.sandbox_run.approval_mode="approve"`, implementing the standing authorization without auto-approving other tools.

Each Codex inference invocation also has its own trusted supervisor in a fresh isolated Python interpreter. A per-job file lock is acquired before launch artifacts or child startup and is inherited only by the supervisor, so controller SIGTERM/SIGKILL cannot allow a duplicate invocation during startup or execution. The supervisor enforces the original monotonic deadline, detects controller death, handles cancellation, and stops the CLI process group and ordinary descendants before recording completion and releasing ownership. Atomic process records retain the invocation path, PID and observed start/command identity for orphan detection after restart. An ambiguous interrupted startup fails closed; artifacts and claims are preserved for coordinator recovery. Identity capture is best-effort when host process enumeration is unavailable; the inherited lock still protects a living supervisor. Restart cannot assume an orphan has exited when enumeration fails, so it preserves the job and reports the error. This does not promise cleanup of deliberately detached sessions/descendants or survival of forced termination of the trusted supervisor itself.

The configured model/reasoning settings are copied from the trusted user configuration; no new model is selected. The current inherited settings are `gpt-6-astra` and `xhigh`. The launcher explicitly supplies `approval_policy="never"`, ignores unrelated user/project execution rules and user MCP configuration, and starts each review in a new invocation and fresh sandbox.

A harmless installed Codex/MCP pilot must establish broker availability, allowed sandbox writes, outside/sibling/synthetic-secret/symlink/network denials, denial through every available built-in host filesystem tool, and authorised model access before production dispatch. `run` and every worker invocation require a trusted `codex_verification` receipt matching the launcher/broker/sandbox source hash, executable path/hash/version, inherited model settings and allowed ports. A missing, stale, fixture-labelled or incomplete receipt fails closed. This is runtime evidence under standing engineering authorization, not another activation approval. The trusted inference process still handles authentication; Seatbelt is not a VM.

## Trusted configuration and commands

Save configuration outside repositories. Include the existing copied issue catalogue and issue-number map. Task policies explicitly assign non-overlapping file/directory prefixes and real validation argv; the runner never executes commands supplied by issue text or a model as trusted acceptance checks. Configure every task intended for autonomous dispatch. Unconfigured tasks are reported as such, not silently marked ready.

Set `commit_identity` to the user's configured Git name and email in the trusted configuration outside the repository; the example values are placeholders. The controller pins a copy in each durable job before publication and uses it for both Git author and committer. Catalogue text, task-level overrides and worker output cannot choose the identity. Configuration changes affect newly claimed jobs, while existing pinned jobs retain their original metadata across restart and publication retries. Legacy jobs starting a new build can pin current configuration; a legacy pending publication without a pin fails before remote requests and needs its original trusted identity restored for reconciliation. There is no silent Automation-author fallback.

Example configuration shape (replace the identity placeholders and paths with actual configured values):

```json
{
  "repo": "Sukhraj1000/closegraph",
  "commit_identity": {"name": "YOUR_GIT_NAME", "email": "YOUR_GIT_EMAIL"},
  "base_repo": "/trusted/base/closegraph",
  "sandbox_root": "/trusted/closegraph-sandboxes",
  "catalogue": "/trusted/closegraph-runner/issue-catalog.json",
  "issue_map": "/trusted/closegraph-runner/github-issues.json",
  "state": "/trusted/closegraph-runner/state/controller.sqlite",
  "artifacts": "/trusted/closegraph-runner/state/codex",
  "inherited_codex_settings": {
    "model": "gpt-6-astra",
    "model_reasoning_effort": "xhigh"
  },
  "codex_verification": "/trusted/closegraph-runner/state/installed-cli-pilot.json",
  "slots": 3,
  "max_attempts": 3,
  "test_timeout": 1200,
  "codex_timeout": 3600,
  "ports": [],
  "dependency_seeds": {},
  "smoke_commands": [["python3.12", "-m", "unittest", "automation.tests.test_codex_controller", "automation.tests.test_codex_github", "automation.tests.test_codex_workspace", "automation.tests.test_codex_supervisor"]],
  "tasks": {
    "A02": {
      "paths": ["automation/codex_loop", "automation/closegraph_loop/sandbox.py", "automation/tests/test_codex_controller.py", "automation/tests/test_codex_github.py", "automation/tests/test_codex_workspace.py", "automation/tests/test_codex_supervisor.py", "docs/engineering/codex-runner.md"],
      "commands": [["python3.12", "-m", "unittest", "automation.tests.test_codex_controller", "automation.tests.test_codex_github", "automation.tests.test_codex_workspace", "automation.tests.test_codex_supervisor"]]
    }
  }
}
```

The example only configures A02; it is not the full product task policy. Product work also needs its provisioned Python/Node/browser dependencies and isolated disposable PostgreSQL roles/databases, storage and allowed loopback ports. The runner does not install services or fabricate unavailable dependencies. Set `dependency_seeds` to map `.venv`, `apps/api/.venv`, `node_modules` or `apps/web/node_modules` to trusted pre-provisioned directories. Allocation copies these into each clone without running host repository code, refuses tracked-file collisions and rejects external symlinks except the current trusted Python executable. The seed must be portable at its destination; rebuild environments with absolute entrypoints when needed. Other test-service provisioning belongs to the coordinator.

From the trusted installation:

```sh
python3.12 -m automation.codex_loop --config /trusted/closegraph-runner/config.json dry-run
python3.12 -m automation.codex_loop --config /trusted/closegraph-runner/config.json status
python3.12 -m automation.codex_loop --config /trusted/closegraph-runner/config.json run --cycles 100 --interval 10
python3.12 -m automation.codex_loop --config /trusted/closegraph-runner/config.json retry T2.1
```

`dry-run` reads GitHub main, issue states, dependencies and existing open PRs without publishing. `run` holds one controller lock for its full lifetime. Each cycle starts ready work within three occupied claims, repairs findings on the same job/PR, and completes each serial merge's verification before another merge. `retry` resumes a paused job and preserves its workspace, branch, receipts and errors; it does not ask for approval.

## Revision checks and recovery

- Issue and overlapping path claims survive process restarts. Completion persists the done stage, releases claims and records its completed event in one SQLite transaction. Startup releases stranded claims belonging to durably completed jobs from older interrupted runs, preserving active and paused claims. Paused jobs retain path ownership. Existing open PR references prevent duplicate task dispatch. A live orphaned Codex process, broker, or bounded command supervisor prevents a new run from taking its workspace.
- Interrupted implementation resumes in its existing workspace. Snapshot preparation and rebase stages are journaled; original commits remain in recovery branches, and cherry-pick conflicts remain for the engineer to resolve.
- Publication transfers regular-file bytes and executable modes, including explicit deletions, via GitHub Git objects. Initial ref creation rejects existing refs; replacements use GraphQL `updateRefs` with the persisted `beforeOid` and desired `afterOid`, so an intervening branch change is rejected atomically. There is no unconditional REST force-update fallback. It refuses symlinks/submodules, traversal, scope escape, unexpected branch movement and a published tree different from the tested local tree.
- Deterministic commit metadata and read-back reconciliation make a lost ref/PR publication response retryable. A lost merge response is reconciled from the PR's actual merged state instead of merging twice.
- A new independent reviewer reads the exact base/candidate diff in a fresh sandbox. The controller runs configured checks itself and verifies the reviewer did not alter the tree. It hashes physical tracked regular-file bytes and executable modes against the Git tree, so clean/smudge filters cannot hide different code behind a clean Git status. Only then does it create a receipt containing head SHA, base SHA, tree SHA and distinct model run IDs.
- Head or base changes invalidate receipts. Main changes trigger a preserved three-way replay, repair and fresh review. Unexpected externally edited PR heads are preserved and paused after bounded retries, rather than overwritten.
- Immediately before merge the controller rereads main and PR head and submits the expected head SHA. GitHub does not provide an atomic base-SHA condition for this endpoint. An external main race is detected by comparing the merged tree and current main, then halting further merges.
- Failed post-merge checks halt the queue and leave the issue open. Transport, clone, test-launch and issue-close exceptions retain the persisted `merging`/`postmerge` barrier. These jobs take priority over every new merge after restart and keep the barrier when paused at the retry limit; successful verification and completion release it. The coordinator repairs/reverts through a reviewed PR and reruns checks before restarting the queue; the runner does not call a failing main healthy. Three repeated worker failures pause that job for coordinator diagnosis while disjoint work continues. No human sign-off is requested.

The private repository currently has no GitHub-enforced branch protection. These are local controller gates, not a claim of native protected-branch enforcement. The runner does not post messages to people or impersonate a human or second GitHub approving identity.

## Verification

Run the controller tests inside a registered sandbox. They use fake GitHub/Codex adapters and real local Git operations to exercise duplicate claims, path overlap, slot bounds, stale head/base receipts, failed/altered review, post-merge halt, publication retries, lost-merge recovery, exact bytes/modes/deletions, preserved rebase conflicts and the fixed broker capability.

The existing `automation/tests/test_sandbox.py` tests the separate Seatbelt boundary. A live model pilot and one real issue-to-merge pilot must be recorded separately from fixture tests. No live activation or merge is asserted by this document.

For the installed-CLI receipt, the trusted coordinator records `kind: "installed-cli-pilot"`, `identity` from `Codex.verification_identity()`, and a `probes` object with every name in `PILOT_PROBES`. Each probe needs `passed: true` and an `artifact` identifying its actual CLI transcript/results. Use synthetic sentinels, never real secrets. The coordinator must inspect tool-level evidence rather than accept model success text. Existing pilot evidence for the broad read-only profile cannot activate the revised profile. Fixture tests of receipt rejection do not constitute pilot evidence.

## Actual local verification — 2026-09-05

All inspection, edits, Git commands and tests for this repair ran through the assigned `closegraph sandbox_run` capability. The exact trusted validation command was:

~~~sh
python3.12 -m unittest automation.tests.test_codex_controller automation.tests.test_codex_github automation.tests.test_codex_workspace
~~~

**46 tests passed in 61.783 seconds**, with no skips. `git diff --check` also passed. This suite includes real local Git/clones and process execution, but GitHub and model adapters remain fixtures.

The three initial fault-injection regressions produced seven failures before repair: four controller-cancellation cases (commands/transfers under SIGTERM/SIGKILL), interruptions immediately before and after claim deletion, and startup with an older stranded completed-job claim. After repair, the complete suite verifies:

- Controller and broker SIGTERM/SIGKILL leave the workspace locked until the command deadline and cleanup complete. Ordinary descendants cannot write their late sentinel; transfer files are removed. An unrelated controller lock is released immediately so disjoint work can resume.
- Supervisor IPC preserves large payloads/results, failed exits and timeouts; successful and failed transfers clean up before lock reuse.
- Abrupt SQLite-process exits before/after deletion roll back completion, claims and events together. Event-insertion failure also preserves retryable in-memory state. Restart reconciliation frees older completed claims without releasing active or paused ownership.

The process regressions use actual subprocesses, signals, file locks, SQLite and the bounded executor inside the enclosing test sandbox. Workspace registration and nested Seatbelt launch are explicit fixture adapters; these tests do not constitute a new host denial or live CLI pilot.

The previous installed candidate recorded 41 passing regressions, 19 actual Seatbelt self-test probes, and an actual Codex 0.153.4/MCP pilot. Those historical host/model probes were not rerun during this repair. This change updates the broker source included in `Codex.verification_identity()`, so previous installed-CLI receipts cannot activate these new bytes. The coordinator must install the reviewed candidate, renew the actual boundary/model pilot and record the matching receipt before dispatch, under standing engineering authorization with no additional approval. Live GitHub PR/review/merge and post-merge acceptance remain awaiting the coordinator's recorded execution; local fixture results do not establish that outcome.

## CLI lifetime regression verification

The focused `automation.tests.test_codex_supervisor` suite uses a harmless executable fixture, with real subprocesses, file locks and signals. It covers controller SIGTERM/SIGKILL, the interval before a process record exists, live deadline expiry, cancellation, ordinary descendant cleanup after success, repeated job ownership, stripped credential environment variables and orphan identity recovery. No model or provider is invoked by these tests. The installed coordinator must rerun the actual Codex/MCP pilot after installing these changed launcher bytes; the older receipt cannot activate them.

The final combined fixture suite passed **55 tests in 82.916 seconds**, with no skips, using `automation.tests.test_codex_controller`, `automation.tests.test_codex_github`, `automation.tests.test_codex_workspace` and `automation.tests.test_codex_supervisor`. This includes the current publication-recovery controller and all six CLI-supervisor regressions. Ruff and `git diff --check` passed. These results establish local process/recovery behavior, not live provider or GitHub outcomes.
