# Verify a corrected reporting pack

## Why

Fund managers repeatedly reconstruct evidence and recheck reporting packs because they cannot tell whether a correction has propagated consistently. CloseGraph must compute source-backed checks and deliver a reviewed revised output, not just store files or produce another AI issue memo.

## What Changes

- Extract supported CSV, XLSX and PDF inputs into source-linked canonical facts, preserving original bytes, raw values, entity, period, currency and scale.
- Run explicit Python transformations and financial reconciliations through Dagster; keep these tools independently testable and do not build autonomous financial agents.
- Route review using evidence/financial hard gates plus parser confidence and contextual parser agreement. Use BLOCKED, NEEDS_REVIEW and READY_FOR_QUICK_REVIEW; a priority score cannot cancel a failed required check.
- Record source-backed corrections as new versions, recompute affected results, compare the revised pack and reopen only demonstrably affected reviews.
- Require independent approval of the exact current snapshot before releasing the revised pack and evidence manifest in one supported existing template.
- Keep extraction observations, validation results, review decisions and release status separate. Failed checks remain visible; human approval never changes them into passes.

## Capabilities

### New Capabilities

- `reporting-evidence`: Supported extraction adapters, immutable source versions, canonical facts and contextual provenance.
- `correction-verification`: Deterministic reconciliation, versioned corrections, dependency impact and recoverable reruns.
- `review-routing`: Explainable three-signal triage with hard gates, explicit unavailable signals and evaluation requirements.
- `reviewed-pack-release`: Independent scoped decisions, secure exact-version publication and preserved history.
- `reviewer-workspace`: Source-to-value review, correction-to-output navigation and observable reviewer-work measures.

### Modified Capabilities

None. There is no implemented application baseline yet.

## Impact

Proposed modules under `apps/api/` and `apps/web/` will use FastAPI/Pydantic, Dagster, Polars/openpyxl, Pandera, PostgreSQL and a React review interface. Reducto is the PDF adapter; Docling is an optional second pass only where evaluation justifies it. Original artifacts use local immutable storage for the demo. No second queue platform is required.

CloseGraph can extract and reconcile directly while also accepting Ylookup/accountant exports. It does not assume a live Ylookup API. Accounting/legal treatment remains explicitly authorised. Reducto is AI-backed; external uploads require data-use approval. Synthetic fixtures and captured parser responses must be labelled, and are not evidence of a live integration.

## Non-goals

Arbitrary file/layout understanding; unconstrained model-generated financial values; autonomous legal interpretation; investment advice; full accounting-system replacement; universal accuracy; production compliance certification; accounting posting; general spreadsheet recalculation; Kafka/NiFi/Temporal; phase-2 requests/deadline alerts; MCP; automatic investor distribution.

## MVP completion gate

From a clean local start, ingest real supported fixture files, expose a discrepancy, make an authorised correction, rerun affected calculations/checks, show an intentionally failed repair and a successful repair, obtain independent renewed approval, and download the corrected pack plus its evidence manifest. Demonstrate hard-gate precedence, preserved failed results, blocked incomplete inputs, contextual parser disagreement, safe retries, stale-approval rejection, publication-race protection and scoped access.

The complete gate and evidence requirements are in `docs/acceptance.md`. Record actual runtime/browser results and measure reviewer actions without inventing savings. Use case 2 becomes a separate change only after this MVP passes its automated technical acceptance gate. User review is optional under the standing engineering authorization; phase-two implementation remains separately scoped.
