# Standing engineering authorization

Effective 2026-09-05, the user instructed: "i dont want to approve anything" and "just approve it anyways", following the choice of a Codex-led local build of the full specified MVP with automatic merging.

## Authorized workflow

The coordinator and engineering workers have standing authorization to implement the active MVP, make routine implementation decisions, create isolated branches/sandboxes, install project dependencies, run local services/tests/browser checks, repair failures and conflicts, publish/update PRs, and merge code automatically. Do not request per-command, per-issue, per-PR, integration or final engineering sign-off. This authorization persists across runs; use it instead of asking again.

Independently assess feature changes and run the relevant checks. A failed check triggers automatic diagnosis and repair, not a request to approve broken behaviour. Record real results. A GitHub COMMENT from an independent agent may supply review evidence; no formal APPROVE from a distinct GitHub account or paid branch-protection plan is required. Never impersonate another reviewer or claim a human approved something they did not review.

The trusted coordinator serializes merges, verifies the tested PR head and current base, merges through GitHub using the expected head SHA, and checks the resulting main revision. Changed revisions require renewed verification. Keep credentials outside worker code. Continue independent work when one issue is blocked. Existing sandbox isolation and exact-byte publication rules still apply.

## Completion

Replace the previous human acceptance gate with recorded automated technical acceptance: every required implementation/acceptance scenario must have actual passing evidence, including browser checks and the required live-provider test. The coordinator records the final engineering acceptance decision. User review is optional and never a prerequisite to completing this build. Do not call this customer validation or human acceptance. Missing credentials or unavailable infrastructure remain factual incomplete work, not an approval request and not a pass.

This is authorization for the active local CloseGraph MVP and its engineering workflow. Financial review inside the application retains independent preparer/reviewer identities and exact-snapshot publication rules. Production deployment, purchasing services, private-document disclosure, financial transactions and phase-two implementation are outside the selected build scope. A synthetic PDF live test can proceed when the previously promised provider access and data-handling requirements are available.

## Configuration and precedence

The repository's `.codex/config.toml` sets `approval_policy = "never"` for Codex runs that load trusted project configuration. Current task/managed permissions take precedence. This disables interactive command approval; it does not turn failed operations into successes or remove the worker sandbox. A coordinator launching child Codex processes must also supply `-c approval_policy='"never"'` so an inherited profile cannot silently restore interactive prompts.

This document and the standing authorization in `AGENTS.md` supersede earlier engineering-only requirements for manual merges, distinct approving accounts, paid branch protection and final user sign-off in README, activation/architecture documents, issue descriptions, cron drafts and runbooks. Product financial authorization requirements are unchanged.

Authorization is distinct from runner capability. The legacy `automation.cron_tools` paused-setup executable and stored cron drafts are historical tooling; this policy does not assert that a new automatic dispatcher/merge controller is installed or running. Agents may implement and activate the selected Codex workflow under this standing authorization without requesting another approval.
