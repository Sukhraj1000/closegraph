# Corrected reporting pack implementation plan

Goal: complete use case 1 from original sources through a checked correction to an independently approved revised pack.

Architecture: independently testable Python extraction/reconciliation tools wrapped by Dagster; application-owned evidence, review and release state. See `design.md` for the approved stack and `docs/acceptance.md` for the completion gate.

Status: implementation has not started. Every checkbox below is an implementation task, not completed specification work. Paths/commands below are proposed and do not exist until their setup task is implemented. For code tasks, write a focused failing test, verify the intended failure, implement minimally and rerun that test before broader checks. A test run must be recorded before checking a task off.

Use the repo's OpenSpec apply workflow when implementation is authorised. Use the software-development quality workflow for TDD and independent review. Do not implement phase 2 in this change.

Path convention: backend paths such as `contracts/facts.py` are relative to `apps/api/src/closegraph/`; abbreviated UI component paths are relative to `apps/web/src/features/packs/`. Test paths are repository-relative. Run a named Python test with `uv run --project apps/api pytest <test-path>` from the project root. These commands are future verification steps, not tests run during specification work.

## 1. Local runtime and labelled fixtures

- [ ] 1.1 Create `apps/api/pyproject.toml`, the `src/closegraph/` package, compatible pinned dependencies and `uv.lock`; verify `uv sync --project apps/api` and imports of FastAPI, Dagster, Polars, openpyxl and Pandera succeed.
- [ ] 1.2 Create `apps/api/tests/conftest.py` and a native synthetic fixture builder under `fixtures/synthetic/` with source CSV, value-only XLSX pack, approved fictional fee rule and expected corrected output; verify `uv run --project apps/api pytest apps/api/tests/test_fixture_contract.py` checks labels, scope and expected source anchors.
- [ ] 1.3 Create `compose.yaml`, `.env.example` and local startup instructions with PostgreSQL, one Dagster code location/webserver/daemon and localhost bindings; verify `docker compose config` and documented health checks without provisioning external services.
- [ ] 1.4 Add `apps/api/src/closegraph/api/app.py` health endpoint and `apps/web/` React/TypeScript/Vite scaffold; verify API health and `npm --prefix apps/web run build`, preserving the root OpenSpec scripts.

## 2. Evidence and canonical state

- [ ] 2.1 Add `contracts/facts.py` with decimal/context/evidence/observation contracts; verify `apps/api/tests/unit/test_facts.py` covers raw scale, exact string identifiers, missing versus zero, locator conventions and JSON decimal round trips using `uv run --project apps/api pytest apps/api/tests/unit/test_facts.py`.
- [ ] 2.2 Add `storage/models.py` and Alembic migrations for immutable source/fact versions, processing requests, check results, dependency edges, correction/review/publication records and audit events; verify upgrade/downgrade and scope/uniqueness constraints in `apps/api/tests/integration/test_storage.py` against PostgreSQL.
- [ ] 2.3 Add `storage/blobs.py` and scoped upload receipts with content hashing and resource limits; verify `apps/api/tests/integration/test_receipts.py` proves original bytes remain unchanged, retried receipts are idempotent, reused keys with changed input are rejected, new source versions persist and corrupt/missing blobs are rejected.
- [ ] 2.4 Add session/role and resource-scope services in `api/auth.py` and `api/permissions.py` with seeded localhost-only preparer/reviewer accounts; verify `apps/api/tests/security/test_access.py` covers cross-fund reads, metadata/count leakage, CSRF, spoofed roles and refusal of public development-auth operation.

## 3. Native extraction and normalisation

- [ ] 3.1 Add `extractors/csv.py` with declared layout, raw-token preservation and record dispositions; verify `apps/api/tests/unit/test_csv_extractor.py` covers supported input, delimiters, string IDs, duplicate occurrences, rejected rows and unsupported layouts.
- [ ] 3.2 Add `extractors/excel.py` preserving sheet/cell context, original values, formula text and cache status; verify `apps/api/tests/unit/test_excel_extractor.py` covers value-only extraction, formula-without-current-result, unsupported macros/links and malformed workbook limits.
- [ ] 3.3 Add `normalisers/numbers.py` and `normalisers/context.py` for explicit scale/currency/period/entity handling and authorised scoped metric mappings; verify `apps/api/tests/unit/test_normalisation.py` catches same digits with different units/periods and unresolved required context.
- [ ] 3.4 Add `validators/schema.py` and `validators/coverage.py` using actual Pandera data-level validation plus source anchors/dispositions; verify `apps/api/tests/unit/test_validation.py` detects bad rows with valid dtypes, missing source rows, malformed evidence, and missing/zero distinctions without silently dropping failures.

## 4. Reconciliation and three-signal routing

- [ ] 4.1 Add `validators/financial.py` for the supported balance-sheet, source-to-pack and approved fixture fee relationships; verify `apps/api/tests/unit/test_reconciliation.py` checks Decimal results, scoped operands, tolerance versions, unknown applicability and multi-fact diagnostics without declaring an unsupported culprit.
- [ ] 4.2 Add `services/parser_signals.py` to compare contextual parser observations and distinguish NOT_RUN, UNAVAILABLE and NOT_APPLICABLE; verify `apps/api/tests/unit/test_parser_signals.py` covers contextual disagreement, missing confidence and explicitly single-parser native policy.
- [ ] 4.3 Add `services/routing.py` with BLOCKED > NEEDS_REVIEW > READY_FOR_QUICK_REVIEW hard-gate precedence and explainable within-route priority; verify `apps/api/tests/unit/test_routing.py` covers high confidence plus failed reconciliation, unknown checks, uncalibrated AI confidence and quick review without automatic approval.
- [ ] 4.4 Add versioned review-policy fixtures and `apps/api/tests/evaluation/test_policy_cases.py`; verify labelled held-out, correlated-parser-error and materiality cases report false-ready outcomes, coverage and scope without asserting probability calibration or customer savings.

## 5. Corrections, dependencies and supported output

- [ ] 5.1 Add `services/corrections.py` to create evidenced fact/treatment versions with actor/reason; verify `apps/api/tests/integration/test_corrections.py` retains original observations and failed checks and rejects unsupported/unauthorised changes.
- [ ] 5.2 Add `services/impact.py` for scoped dependency closure and current/stale/unverifiable transitions; verify `apps/api/tests/integration/test_impact.py` covers affected outputs, established independent outputs, changed mappings/rules/policy and unknown/cyclic dependency coverage.
- [ ] 5.3 Add `outputs/workbook.py` to fill only allowed cells of the supported value-only template from recomputed values; verify `apps/api/tests/integration/test_output_template.py` reads the candidate back, compares expected values and unchanged layout/cells, and blocks unsupported formula/macro/template features.
- [ ] 5.4 Add `outputs/manifest.py` linking source/fact/rule/check/snapshot identifiers and artifact hash; verify `apps/api/tests/integration/test_manifest.py` resolves the lineage and rejects missing evidence or integrity mismatch.

## 6. Dagster orchestration and recovery

- [ ] 6.1 Add `pipeline/assets.py`, `pipeline/resources.py` and `pipeline/definitions.py` with explicit snapshot inputs and durable IO; verify `apps/api/tests/integration/test_pipeline.py` executes real native fixture files through extraction, checks, candidate generation and review snapshot without shared latest-document state.
- [ ] 6.2 Add `pipeline/sensors.py` reading committed processing requests with stable run identities; verify `apps/api/tests/integration/test_dispatch.py` handles sensor restart, repeated requests and acknowledgement interruption without lost work or duplicate business effects.
- [ ] 6.3 Persist negative financial outcomes and ineligible candidate descriptors without preventing review-snapshot materialisation; verify `apps/api/tests/integration/test_failed_checks_visible.py` shows completed processing with BLOCKED review and actual failed operands.
- [ ] 6.4 Add bounded transient retries and snapshot-scoped stage uniqueness; verify `apps/api/tests/integration/test_recovery.py` kills/restarts execution, retries after a committed write and rejects stale late completion overwriting current state.
- [ ] 6.5 Wire authorised correction events to new processing requests rather than waiting inside a job; verify `apps/api/tests/integration/test_correction_rerun.py` proves the old run finishes, a new revision reruns affected computations and the new candidate differs as expected.

## 7. PDF adapter and optional parser boundary

- [ ] 7.1 Add `extractors/reducto.py` with configured-only egress, provider response capture, page/bbox mapping and explicit availability; verify `apps/api/tests/contract/test_reducto_adapter.py` using clearly labelled synthetic/captured responses for confidence variants, malformed citations, service failure and no silent fallback.
- [ ] 7.2 Add an optional second-parser observation interface in `extractors/common.py`, without making Docling installation mandatory; verify `apps/api/tests/unit/test_second_pass.py` covers NOT_RUN/UNAVAILABLE and contextual disagreement while preserving both original observations.
- [ ] 7.3 Record approved external data scope and verify the parser's retention/region requirements before a real PDF test; with configured credentials, run `apps/api/tests/live/test_reducto_pdf.py` on an authorised synthetic PDF and retain source-to-field evidence. If permission/credentials are absent, record the blocker and leave this task unchecked; a replay or skipped test does not complete it.

## 8. Independent review and release gate

- [ ] 8.1 Add `services/review.py` for exact-snapshot independent decisions and explicit soft-signal adjudication; verify `apps/api/tests/integration/test_review.py` denies self-approval, unresolved hard blockers and revoked permission; selecting a different value/context creates a new snapshot and rechecks while retaining original parser/check history.
- [ ] 8.2 Add `services/publication.py` with trusted-state gating, scoped version locking and output integrity verification; verify `apps/api/tests/integration/test_publication.py` covers missing bytes/evidence, forged pass flags, repeated release and historical/superseded outputs.
- [ ] 8.3 Make all relevant source/rule/policy writers participate in the publication version protocol; verify `apps/api/tests/integration/test_publication_races.py` races updates, revocations and concurrent releases against approval/publication and prevents stale release.
- [ ] 8.4 Add authorised API routes for snapshots, citations, corrections, recompute, review, publication and downloads; verify `apps/api/tests/security/test_routes.py` enforces per-resource scope and treats document instructions/paths as untrusted data on every route.

## 9. Reviewer workspace

- [ ] 9.1 Implement `apps/web/src/features/packs/PackReview.tsx` with separate execution/check/routing/review/freshness states, accessible text labels and grouped failed relationships; verify `apps/web/tests/pack-states.spec.ts` against the real local API.
- [ ] 9.2 Add `SourceEvidence.tsx` and `CorrectionPanel.tsx` for cell/page evidence, original/proposed observations and evidenced correction reasons; verify `apps/web/tests/correction-review.spec.ts` traces a value and creates a new version without erasing history.
- [ ] 9.3 Add `ReviewDecision.tsx` and `ReleasePanel.tsx` showing the exact candidate snapshot, independent decision and gated download; verify `apps/web/tests/release.spec.ts` with distinct preparer/reviewer sessions and a blocked then successful repair.
- [ ] 9.4 Add an inspectable all-values view and correction/review audit timeline, without phase-2 request/deadline automation; verify `apps/web/tests/evidence-audit.spec.ts` can inspect ready items and reports observed actions rather than fabricated savings.

## 10. Full acceptance and handoff

- [ ] 10.1 Run `uv run --project apps/api pytest apps/api/tests/unit apps/api/tests/contract apps/api/tests/integration apps/api/tests/security apps/api/tests/evaluation` against the real database and configured test infrastructure; record exact results and fix required failures, without counting skipped live tests as passed.
- [ ] 10.2 Run `npm --prefix apps/web run build` and `npm --prefix apps/web exec playwright test` after a clean local startup; complete every case in `docs/acceptance.md`, inspect the downloaded revised workbook/manifest and record browser evidence.
- [ ] 10.3 Produce `docs/verification/mvp-acceptance.md` with scenario-to-test mapping, actual commands/results, artifact identities, live versus replay provenance and remaining limitations; verify every required criterion has evidence and that live PDF is either passed or explicitly removed from scope by the user, never silently waived.
- [ ] 10.4 Record the coordinator's automated technical acceptance of the working MVP under the standing engineering authorization, based on the complete test/browser/live-provider evidence from tasks 10.1–10.3; verify every required criterion is covered, unresolved requirements remain incomplete, and phase 2 has not begun early. User review is optional and is not a completion gate; do not claim human/customer acceptance.

After every implementation task and the acceptance gate are complete, use the OpenSpec archive workflow to synchronise implemented baseline specs. Only then create the separate phase-2 change for missing-evidence handoffs. Archive and phase-2 planning are follow-on lifecycle actions, not evidence that unfinished application tasks passed.
