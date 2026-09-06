# Historical engineering architecture: native Hermes cron

> Historical record of the paused Hermes setup. The present-tense statements and gates below describe that earlier snapshot, not the current system. [Standing engineering authorization](standing-authorization.md) supersedes its manual approval, distinct approving account, branch-protection prerequisite and final user sign-off requirements. [The Codex runner guide](codex-runner.md) describes the selected engineering workflow and required runtime evidence; this notice does not assert live activation. [ARCHITECTURE.md](../../ARCHITECTURE.md) is the canonical implemented product map, and [CI](../../.github/workflows/ci.yml) defines the current repository checks. The historical body is retained for traceability.

## Scope and current state

Use existing Hermes cron instead of building another scheduler, webhook listener or controller. This engineering workflow is separate from CloseGraph's financial FastAPI/PostgreSQL/Dagster/React application. This historical design has no QA bot; hosted repository checks are now defined in `.github/workflows/ci.yml` and do not activate the paused cron workflow.

Delivery is a paused setup: an issue catalogue, native cron definitions, a read-only GitHub change monitor and a tested macOS sandbox runner. It is NOT an operational unattended issue-to-merge fleet. Live coding/review adapters and trusted publishing/merge integration remain activation work. `automation.cron_tools status` deliberately reports `dispatch_available=false`; cron prompts must stop at that gate.

## Minimal loop

    GitHub approved task / outstanding review
                  |
    Hermes engineering cron (proposed every 30 minutes)
                  |
    bounded coding run in independent macOS-sandboxed clone
                  |
    scoped change + relevant tests -> trusted publication to same PR
                  |
    Hermes reviewer cron (proposed every 15 minutes)
                  |
    independent diff/spec review + rerun relevant tests
          /                           \
    request changes              eligible formal approval
          |                           |
    repair same PR              guarded merge, when enabled
                                      |
                        deterministic main smoke, then human QA

Hermes handles scheduling and job history. Its native `monitor` facility can suppress model calls when the deterministic GitHub snapshot is unchanged. First monitor tick normally runs a baseline; the status guard still prevents dispatch. No public ingress, new daemon, SQLite event ledger or webhook service is needed. The default-profile gateway already exists; this setup does not restart it or alter unrelated jobs.

GitHub issue/PR state remains authoritative. Cron output/`context_from` is a useful hint, never an approval or an atomic work claim. Missed ticks recover by rereading current state. The initial pilot is serial; expanding to overlapping worker jobs requires a verified claim/lock and resource budget, not merely another cron entry. Begin with disjoint epic lanes only after that gate.

## Scope and ownership

See [epics](epics.md) and [published issue IDs](github-issues.json). Seven product epics plus E0 delivery setup cover every original OpenSpec task once. Each issue names scope, original paths/tests, prerequisites and parent. Contracts and scaffolding are a small shared kickoff; fixture-driven development is parallel, but final integration is genuinely dependent. Do not claim complete epics are dependency-free.

Use existing approved tasks directly. Do not create extra issue factories, work beyond the active OpenSpec change, or auto-close an epic from a partial PR. Original product checkboxes remain unchecked until implementation and acceptance evidence exist.

## Sandbox and credentials

`automation/closegraph_loop/sandbox.py` provides `create_workspace`, `run_sandbox` and `self_test`; the legacy module directory name is retained, not a custom orchestration service. Each run has a full independent clone, HOME, temp and artifact directory. macOS Seatbelt applies to the entire untrusted child and all coding/tools/tests it launches. Never repair a denial using an unrestricted file or terminal tool.

Offline is the default. Explicit IPv4 loopback ports may be allowed only for isolated disposable test services. No global Docker/SSH sockets, sibling directories, personal profile or publishing credentials are passed to tested code. The trusted host scheduler/orchestrator is outside this boundary; a cron workdir or toolset restriction is NOT itself a sandbox. A real coding CLI and authorised inference route still need a supervised integration proof.

The wrapper has actual local denial tests but is not a VM or security certification. System/toolchain paths and root-directory entries are readable. There are no hard CPU/memory/disk/process-count quotas; detached hostile descendants can evade process-group cleanup while remaining sandboxed. Do not store secrets in allowed toolchain paths or allow privileged loopback services.

Keep GitHub author/reviewer credentials in a trusted publication layer, never repository scripts/tests. That integration is deferred, not silently considered complete. An independent reviewer requires a distinct eligible account/App, not two tokens for the same author. Never execute worker-controlled Git hooks/configuration with privileged credentials. Publishing must validate scope, exact tested bytes and read back external effects.

## Review and appropriate tests

Every PR receives independent scope/correctness/security/test review. Engineers own tests for their features; the reviewer verifies selection and reruns relevant checks in its own sandbox.

- Pure computation: focused unit/regression tests and meaningful negative cases.
- API/storage/pipeline changes: affected-boundary integration tests.
- Permissions/freshness/publication: denial and race regressions.
- User journeys: relevant browser E2E, built incrementally with the application.
- Styling/docs/behaviour-preserving refactors: existing coverage may suffice; explain why no new integration test is needed.

No new integration test does not mean no checks run. Reject weakened assertions, unexplained skips, mocked boundaries claimed as real integration and provider replays claimed as live. The eventual regression path is upload -> discrepancy -> failed repair stays blocked -> evidenced correction -> distinct reviewer approval -> matching downloaded workbook/manifest.

Record repository, PR, exact head SHA, actual base SHA, commands/results and selection rationale. Same-head/base reviews are not repeated without new actionable evidence. A changed head OR base requires fresh verification. Review comments are not formal approval.

## Merge and human integration

Auto-merge is OFF. The current private-repository branch-protection request returned HTTP 403 requiring an eligible plan. Keep the repository private; do not buy an upgrade or substitute local checks while claiming native protection exists.

Before future merging: verify exact source/base, distinct eligible approval, resolved threads, no draft/fork/hold, appropriate local verification, current mergeability and supported branch rules. Admit one merge at a time. After main changes, reverify pending candidates. Run deterministic main smoke after each merge and pause subsequent admission on failure. This policy still needs a supervised real-loop proof before activation.

The user is the actual integrator/QA and owns usability, exploratory testing and final acceptance. Merged is not accepted. Stop on scope drift, stale evidence, unsafe isolation, broken main or repeated ineffective fixes. No dedicated QA agent.
