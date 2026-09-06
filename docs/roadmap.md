# Roadmap: one verified workflow before expansion

This is the phase index. Phase 1 has recorded automated technical acceptance in [the acceptance report](verification/mvp-acceptance.md). Its 40-task checklist is archived; no phase-2 change is active.

This index retains the archived OpenSpec plan's phase boundary. Subsequent direct Collections work implements bounded in-app requests, owners, deadlines and deduplicated escalation outside that OpenSpec phase. It does not open phase 2 or amend the archived checklist/baseline specs. External delivery and live source connectors remain deferred. See the [implemented-system map](../ARCHITECTURE.md) and [Collections workflow](engineering/collections-workflow.md) for current runtime scope.

## Phase 1 — Verify a corrected reporting pack (implemented MVP)

Completed change: [verify-corrected-reporting-pack](../openspec/changes/archive/2026-09-05-verify-corrected-reporting-pack/tasks.md). Five implemented capabilities live in [baseline specs](../openspec/specs/).

Outcome: "The accountant changed a figure. Here is the evidence, here is the effect on the pack, and here are the checks and renewed approval for this exact revision."

Deliver a single local end-to-end path:
1. Ingest original supported files and a reporting pack; extract source-linked facts through the Dagster pipeline.
2. Run schema/data checks and explicit financial reconciliations; triage using hard gates and parser signals.
3. Record a disputed figure and authorised correction with a reason; retain the original observation.
4. Recompute supported dependent values, compare the revised pack, and show an intentionally failed repair before a successful repair.
5. Obtain independent scoped approval and download the revised artifact in the supported template plus its review manifest.

Use a small synthetic reporting-pack fixture in an existing stable template. Keep its specific fee policy in a versioned fixture/workflow contract, not in the general data model.

### Gate before phase 2

All of the following must have recorded evidence in the phase-1 acceptance report:

- The clean-start browser journey in `docs/acceptance.md` works against the real local API, PostgreSQL, Dagster execution and stored artifacts, not UI-only fixtures.
- Every required scenario has an associated passing automated test or documented browser check; no unresolved critical release or access-control failures remain.
- A failed correction cannot be released; a successful correction is visible in the downloaded output and source-linked manifest.
- Hard-gate precedence, contextual parser disagreement, independent review, unknown dependencies, invalidated approvals, retries/restarts and publication races behave as specified.
- Native CSV/XLSX has actual runtime evidence. PDF adapter contract tests use labelled captured/synthetic responses, and full MVP acceptance requires an authorised live Reducto test. If provider approval/credentials are absent, the native demo can proceed but full acceptance and phase 2 remain blocked unless the user explicitly approves a narrower scope and the specs are updated.
- The coordinator records automated technical acceptance under `docs/engineering/standing-authorization.md`; user review is optional. The report distinguishes tested behaviour from unresolved live-provider/pilot assumptions and does not claim human/customer acceptance.

After this gate, open a separate OpenSpec change for phase 2. Do not pre-build a generic workflow platform "to prepare" for it.

## Phase 2 — Resolve missing-evidence handoffs (OpenSpec phase unopened)

Outcome: "This deliverable is blocked by this specific evidence, this person owns the next action, and the request is tracked to verified resolution."

Historical candidate follow-on scope, to refine against the working MVP and the bounded in-app Collections functionality now implemented outside this phase:
- Expected-evidence records attached to the existing pack/issue.
- Authorised owners, configured due dates/timezones and visible downstream blocking.
- Permission-scoped requests and acknowledgements.
- Deduplicated reminders/escalation using durable delivery records.
- Link incoming evidence to the original request; recheck before resolving the blocker.
- Keep overdue/acknowledged/received/verified states distinct. Deadlines never override release gates.

Reuse phase-1 snapshots, evidence, checks, audit events and permissions. Do not create a separate file-management system or duplicate status database. External notifications require explicit destination/provider authorisation and read-back/delivery evidence when implemented.

There is deliberately no active phase-2 OpenSpec change or phase-2 implementation checklist yet.

## Later — Only when a concrete need is validated

Potential additions: verified Ylookup integration, more bounded source adapters, evaluated Docling second-pass execution, read-only permissioned MCP, more reporting templates and richer cross-party visibility. Dagster is already the selected MVP computational runner; do not add a second orchestration platform. These additions are not implied MVP requirements.

Not on the automatic roadmap: investment recommendations, autonomous legal interpretation, becoming a licensed fund administrator, general accounting replacement, universal parsing or guaranteed accuracy.
