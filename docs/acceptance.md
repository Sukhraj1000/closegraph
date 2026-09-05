# MVP acceptance: source-backed correction to reviewed output

Status: acceptance criteria only. No application tests or browser journeys have been run by specification setup. OpenSpec validation is not runtime verification.

## Required demonstration

Use labelled synthetic source files, one value-only reporting workbook template, an explicitly approved fictional fee rule, and distinct preparer/reviewer identities. Do not treat fixture rules as general accounting or legal advice. Preserve original files and parser observations.

1. Start the actual local API, PostgreSQL, Dagster processes and React UI from the documented clean setup.
2. Upload the native CSV/XLSX sources and pack; inspect the actual extracted records and their source coordinates.
3. Run schema/data/coverage checks and the supported financial reconciliations. Show one failed relationship with its operands, not merely a prefilled red badge.
4. Inspect the source, record an evidenced correction, and observe a new version and rerun. Make one deliberately insufficient correction to prove the failure remains visible and blocks release.
5. Apply the successful source-backed correction. Recompute affected values, regenerate the supported template and verify the revised mapped values.
6. Show that the prior snapshot/approval cannot approve this revision, while an established independent output is not unnecessarily reopened.
7. Sign in as the independent reviewer, inspect evidence and resolve soft review signals, then approve the exact passing snapshot.
8. Publish through the backend gate and download the revised workbook plus its source/check/review manifest. Read back the actual downloaded values and compare its identity to the approved artifact.
9. Run the authorised PDF path separately and verify source-linked actual Reducto results; demonstrate provider-disabled behaviour without sending a document externally.

The native journey can be demonstrated without an external provider. Full MVP acceptance remains blocked on a required live PDF run if permission/credentials are absent, unless the user explicitly approves a narrower MVP and the proposal/specs/tasks are updated. A captured response or skipped live test is not equivalent completion.

## Acceptance matrix

Every OpenSpec requirement/scenario must map to a test or recorded manual check in the eventual implementation report. This matrix groups the required behaviours; it is not a claim that they pass.

| ID | Behaviour to demonstrate | Required evidence / planned test family |
|---|---|---|
| A01 | Actual CSV/XLSX extraction with source context, original bytes and idempotent receipts | `test_csv_extractor.py`, `test_excel_extractor.py`, `test_receipts.py`; real uploaded file/record evidence |
| A02 | Correct decimal/scale/entity/period handling; exact string identifiers; missing versus zero; no implicit metric mapping | `test_facts.py`, `test_normalisation.py` |
| A03 | Coverage detects omissions, row checks execute despite valid dtypes, stale formula caches remain blocked | `test_validation.py`, `test_excel_extractor.py`; intentionally incomplete source/fixture |
| A04 | Financial checks compute operands/difference under pinned rules; ambiguous treatment and unknown required checks block | `test_reconciliation.py`; source-to-pack and supported fee calculation evidence |
| A05 | High confidence + agreement cannot cancel a failed rule; required pending/unknown checks never become ready | `test_routing.py`; real negative check through UI |
| A06 | Contextual parser disagreement, NOT_RUN/UNAVAILABLE/NOT_APPLICABLE and uncalibrated confidence remain explicit | `test_parser_signals.py`, `test_second_pass.py`, `test_routing.py` |
| A07 | Native tested single-parser policy can be quick-review eligible; quick review still requires a human | `test_routing.py`, `test_review.py`, `pack-states.spec.ts` |
| A08 | A correction creates new versions, preserves observations/failures and recomputes affected outputs | `test_corrections.py`, `test_correction_rerun.py`, `correction-review.spec.ts` |
| A09 | Unknown/cyclic dependencies block; changed mappings/rules invalidate only established affected scope | `test_impact.py`; dependent and independently scoped fixture outputs |
| A10 | Failed checks remain inspectable; infrastructure failure is distinct; a human wait holds no running job | `test_failed_checks_visible.py`, `test_pipeline.py`, `pack-states.spec.ts` |
| A11 | Sensor and worker interruption, duplicate input and late completion do not lose work or overwrite current state | `test_dispatch.py`, `test_recovery.py`; actual interruption/restart evidence |
| A12 | Independent approval, soft-signal adjudication and revoked permissions; no approval override for hard failures | `test_review.py`, `release.spec.ts`; separate authenticated sessions |
| A13 | Forged flags, corrupt/missing bytes, changed policy and publication races cannot release unsafe/stale work | `test_publication.py`, `test_publication_races.py`; actual database concurrency tests |
| A14 | Cross-fund facts, citations, graphs/counts/downloads are denied; prompt/document instructions grant no authority | `test_access.py`, `test_routes.py`; adversarial uploaded text and route probes |
| A15 | Corrected workbook preserves the supported template, blocks unsupported features and has a complete manifest | `test_output_template.py`, `test_manifest.py`; read-back of downloaded bytes and values |
| A16 | Reducto citations/confidence map correctly; disabled/unavailable provider has no silent fallback; authorised live PDF works | `test_reducto_adapter.py`, `test_reducto_pdf.py`; distinguish synthetic/captured contract fixtures from real response evidence |
| A17 | Held-out tests expose correlated errors and false-ready outcomes; ready values stay inspectable and sampled | `test_policy_cases.py`, `evidence-audit.spec.ts`; fixed dataset and versioned evaluation report |
| A18 | Historical outputs/decisions, current as-of state and observed reviewer-work metrics are honest and inspectable | `test_publication.py`, `evidence-audit.spec.ts`; no fabricated customer baseline |

## Evidence report requirements

Create `docs/verification/mvp-acceptance.md` during implementation, not as an invented success report now. Record:

- Exact application revision, dependency/rule/policy versions and fixture identity.
- Commands, exit results, passed/failed/skipped tests and execution environment.
- Per-scenario links to test names or browser evidence and the relevant acceptance-matrix ID.
- Actual input/candidate/released artifact identities and source-to-output comparisons.
- Parser mode: native, live, captured replay or synthetic observation fixture; never blur them.
- Expected-negative checks versus software test failures; a blocked financial case can be correct application behaviour.
- False-ready errors, supported coverage, missing/duplicate records and observed review actions, with denominator/scope from code.
- Remaining limits: source truth, supported layouts, accounting treatment, provider freshness, external data permissions and production security.

No required criterion is complete solely because a task was checked, a pipeline ran successfully or a reviewer clicked approve. No numeric confidence threshold is promoted from self-reported confidence alone. A policy that rejects everything is not useful: report supported coverage and reviewer burden alongside unsafe acceptance.

## Phase-2 gate

Use case 2 remains deferred until all required use-case-1 acceptance criteria have real evidence, critical failures are resolved, and the user reviews the working result. Missing permission for a required integration is a blocker or an explicitly approved scope change, not permission to silently skip it. Only then open a new OpenSpec change for evidence requests, owners, deadlines and escalation.
