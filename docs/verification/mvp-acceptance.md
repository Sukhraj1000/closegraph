# MVP acceptance evidence — 2026-09-05

**Status: automated technical acceptance recorded for the implemented use-case-1 MVP.** The coordinator records acceptance under [standing engineering authorization](../engineering/standing-authorization.md), based on the actual evidence below. All 27 requirements, 56 scenarios and A01–A18 criteria have implementation/test evidence. All three independent product-review findings were repaired and re-reviewed. This is a synthetic automated demonstration, not human/customer acceptance or measured customer savings. Phase 2 remains unstarted.

## Revision, environment and fixture identity

The API suite and independent review ran on product candidate `15125d41793589008f83338128ed5223e7d610a0` (tree `2360cc275152bb3e0bd4b6bf560dc46115a25060`). The subsequent UI review ran on `13610a8f19ae523fdb5b73c17f6baf5f2332c931` (tree `c90367c0ff9a538498bb91ae37abd2e703ef61c7`), with every recorded API file unchanged. Final browser harness `23eeb5191cb9775b9cfaf773ca6647488dfa8ea2` adds exact-source and publication-download assertions; application implementation is unchanged. The portable source-digest manifests bind tests to bytes across the final documentation/archive commit and rebase. GitHub PR/head/merge receipts are recorded separately by the coordinator after publication; the containing commit cannot embed its own final hash. Acceptance does not waive independent final-composition review, expected-head merging or post-merge byte/check verification.

| Item | Recorded identity / limit |
|---|---|
| Independent review | Initial whole-product review found workbook fidelity, same-byte publication identity and selected source-occurrence defects. Repairs `d800f17`, `41067f9` and `395f8c1` passed independent re-review; no unresolved product findings. Readable [API](evidence/api-review.json) and [UI](evidence/ui-review.json) records preserve scope and exact candidate hashes. |
| API environment | Real PostgreSQL on isolated loopback 55432; backend lane separately used 55431. Python 3.12 and locked dependencies. No SQLite substitution. Commands executed through the trusted sandbox bridge. |
| Local application | API 24180, UI 24173, Dagster webserver 24181/code location 24182, managed PostgreSQL 55433. Five application services healthy after down/up; repeated up reused healthy processes. Explicit UI restart loaded transferred source before final browser verification. |
| Dependency identity | `apps/api/pyproject.toml`, `apps/api/uv.lock`, `apps/web/package.json` and its lockfile are included in source digests. Browser image/runtime identity is retained in `browser-reviewed/browser-environment.json`. |
| Native fixture | [Fixture builder](../../apps/api/src/closegraph/fixtures.py): labelled SYNTHETIC tenant/fund/pack; entity string `0012`, period `2026-Q1`, GBP. Capital 12,000,000; fee rate 0.005; original workbook fee/statement fee/total 75,000. |
| Approved fictional computation | `fictional-fee-v1`, approval `synthetic-approved-fee-rule`, tolerance `0.01`, tolerance version `penny-v1`. Supported fee = 12,000,000 × 0.005 = 60,000. Fixture authority is not general accounting treatment. |
| Output mapping | `synthetic-template-v1`, template format `value-only-v1`; `Pack!B6` fee, `B7` statement fee, `B8` total. Final values all 60,000. |
| Routing | `native-single-parser-v1`; configured `synthetic-review-priority-v1`, GBP materiality 50,000 and impact threshold 2. Unconfigured priority remains unavailable; queue priority is not correctness probability. |
| Snapshot identity | Current `PackSnapshot.version` is journal/CAS revision; `candidate.checked_version` is the computed artifact snapshot. Final native checked revision 89, released journal revision 91. |

## Execution ledger

These are actual executions with retained logs. Counts overlap; do not add historical or focused runs to the final totals. Paths in backticks below are members of the [portable archive](evidence/README.md), whose [inventory](evidence/evidence-index.json) binds every byte.

| Execution | Actual command / evidence | Result and scope |
|---|---|---|
| Final independent API | `uv run --offline --locked --project apps/api python -m pytest apps/api/tests -q --junitxml=artifacts/verification/product-review-final/api-junit.xml`; real PG 55432, retained live receipt configured. `api-reviewed/api-run.json`, stdout, JUnit and source digests. | **288 passed in 56.77s; 0 failed/errors/skipped.** Includes process recovery, migrations, integrity, source/fact versions, permissions/CAS races, provider contracts and recorded live receipt verification. |
| Final independent UI | `npm --prefix apps/web test` and `npm --prefix apps/web run build`; exact recorded arguments in `ui-reviewed/ui-run.json`. | **32 unit tests passed; production build passed.** Two additional reviewer-authored tests also passed using native/API-shaped distinct B6=75000/B7=80000 data. The combined independent run is 34 total, not 34 additional. |
| Final native API/browser | `npm --prefix apps/web run test:native -- --output test-results/native-after-review`; fixed isolated browser relay and distinct scoped development accounts. `browser-reviewed/native-after-review-browser-results.json`. | **1/1 passed in 81.494535s**, 19:49:42 UTC. Actual upload → failed repair → blocked release → successful repair → independent sample/approval → publication → downloaded-byte/readback verification. Final source-occurrence and filename/publication-ID assertions passed. |
| Final Storybook browser | Fresh `npm --prefix apps/web run build-storybook`, then `npm --prefix apps/web run test:stories -- --output test-results/stories-after-review`; fresh static server and HTTP bundle-hash proof. | **13/13 passed in 96.982451s**, 19:51:19 UTC. Eight separate state stories plus correction/review, soft resolution, primitives/accessibility, reflow and original-page PDF citation. These fixtures are separate from the real API journey. |
| PDF DISABLED API/browser | Historical `browser-reviewed/pdf-disabled-browser-results.json`, 18:48:34 UTC. | **1/1 passed in 35.057891s.** Completed but BLOCKED, no extraction observations; provider/source-coverage blockers prevent review/publication. |
| PDF CAPTURED_REPLAY API/browser | Historical `browser-reviewed/pdf-replay-browser-results.json`, 19:08:48 UTC. | **1/1 passed in 30.653543s.** Fresh matching PDF upload produced canonical REPLAY observations, exact source/response hashes, original-page canvas/bbox/text. It is not another live request or financial mapping. These two PDF mode runs preceded the final three repairs; final API and PDF Storybook checks followed them. |
| Actual live provider | Authorised synthetic request at 18:06:42.102894 UTC; `provider/receipt.json`, `parse-response.json`, `synthetic.pdf`. | Actual Reducto job and hashes recorded below. The later **1 passed in 0.23s** receipt test and final 288-test suite verify that retained actual response; neither duration is provider processing time or a new network call. |
| Runtime/recovery | `runtime/final-runtime-restart-result.json`, `final-ui-source-restart.json`, compose/IPC/recovery records. | Real services healthy after clean down/up; repeated up idempotent. Three actual child-process interruption/recovery checks pass and are included in the final API suite. Six migration/balance regressions are also included. |
| Held-out routing | [Policy test][POLICY], retained `api/review-policy-evaluation-v1.json` and origin/hash record. | **13 synthetic cases: 5 BLOCKED / 5 NEEDS_REVIEW / 3 READY; false-ready 0; required-check coverage 22/26.** Unsafe-prediction counter-test ensures failures are counted. No universal calibration/customer savings claim. |

The [final browser index](evidence/browser-index.json) records commands, source hashes, browser image, zero unexpected/skipped/flaky cases, screenshots, exact artifact identities and coverage limits. The native viewport was visually inspected. HTTP source-marker and static-bundle proofs establish that the final tests used the repaired UI. A stopped relay and stale Vite transforms caused two earlier final attempts to fail before acceptance; an explicit restart corrected the infrastructure state. Those attempts are not relabelled as successful business negatives.

Engineering runner isolation, CLI pilots, review and merge recovery are tracked separately in PR #55 and its coordinator receipts. They do not replace financial approval or this product evidence. The application was built with coordinated parallel sandboxes; this report does not claim the runner autonomously dispatched all 40 product tasks.

## Live, replay and native provenance

The authorised external data scope was a **705-byte synthetic PDF**, not private/client inputs. The actual live source SHA-256 was `4b3b1adfb44bf2b76f2e45dd4a5c8f659ead318d84419331d70b6daa7411ead1`; actual Reducto job ID was `07886b8c-5eeb-4808-beab-2389db7d7572`. The retained files are `artifacts/live-reducto/receipt.json`, `parse-response.json`, and `synthetic.pdf`. The approved receipt, response and synthetic input are retained in `provider/` inside the portable archive and in the labelled fixture capture. Credentials are excluded.

The coordinator reports reviewing official provider documentation and using the recorded `https://platform.reducto.ai` endpoint with `persist_results=false` and `force_url_result=false`. Account/region residency entitlement was **not independently confirmed**. Documented Growth-plan 24-hour expiry and no-training terms are conditional; this report makes **no ZDR, verified-region or unconditional no-training claim**. This synthetic-only exercise does not authorise broader private-document processing. The exact approved capture and replay setup are retained in [the synthetic capture](../../fixtures/captured/reducto-live-20260905/README.md). Reviewed provider references: [quickstart](https://docs.reducto.ai/quickstart), [security policies](https://docs.reducto.ai/security/policies), and [EU residency](https://docs.reducto.ai/security/eu-data-residency).

Parser modes remain distinct:

| Mode | Meaning and available evidence |
|---|---|
| NATIVE | Actual declared CSV/XLSX extraction; coordinates/raw observations retained; no model probability. |
| LIVE | The actual authorised provider request and captured receipt/job/hash above. |
| CAPTURED_REPLAY / observation REPLAY | Deliberate local loading of captured bytes for the exact matching source hash; never counted as another live request. Actual API/browser replay passed 1/1 in 30.7s with a fresh PDF upload, exact source/response hashes and original-page canvas/bbox/text. |
| Synthetic observation fixture | Contract/policy/Storybook test data, explicitly labelled; not a provider response or customer pilot. |
| Disabled / unavailable | No authorised configured egress, or explicit provider failure. No implicit alternative provider, model, URL download or native fallback for the PDF. |

The PDF evidence role is `reporting-evidence`. It does not authorise arbitrary PDF financial mappings. Citation-bearing observations can remain unresolved and block source coverage while original-page evidence stays inspectable.

## Artifact identity and value ledger

| Artifact / comparison | Verified result |
|---|---|
| Original uploads | Final native source version 9. Capital SHA-256 `8321e47f55741e6ed9a80342605c8ddfe84e2524b561f3ee4f6eef56429ba2d7`; fee rule `1eaac127c949537b5d4e0e048c3252f0c4fb339d711b0dd08321af488828aeb8`; original workbook `9214501f237c869275ea5672aeff4f15ea0bbf4bd6610c5442adc997f286cdc7`. Exact receipt/document IDs and distinct B6/B7 anchors are in the browser index. |
| Insufficient repair | Revision **87**: fee 60,000 and statement fee 75,000. Required `source_to_pack` FAIL persists; no eligible release. Actual snapshot retained in `browser-reviewed/native-failed-repair.json`. |
| Successful repair | Checked snapshot **89**, both source-backed corrections 60,000, required checks pass. Balance sheet is explicitly NOT_APPLICABLE for this declared fixture. Candidate stays unapproved until distinct reviewer decision. |
| Independent approval | Actor `reviewer`, snapshot 89 at `2026-09-05T19:50:52.434232+00:00`. Snapshot digest `fca6877e251dea4dd9912fb7174e55529fe22e4513cce3eaa0ed08cd651d8e4f`. |
| Published output | Publication `b70e2fe7c50434ef552ffe5f472ab35df2d9b85a4a929cdab4b8ddb6c3de3cd3`, journal revision **91**, at `19:50:52.812794+00:00`. Workbook SHA-256 **`1cb40981c066c0c6ebd494931d7ed781611246e6711308ce71877df14874d967`**; manifest **`89acc9c0ca31fbb896e7e88b47e8c0e99c0dab98774c8a2f1da1a04a704a1234`**. |
| Actual downloads | `synthetic-pack-v89-current.xlsx` and `synthetic-pack-v89-current-manifest.json`; query publication ID and response/suggested filenames verified. Reviewed bytes equal inspected candidate; downloaded B6/B7/B8 all `60000.00`. Manifest binds exact source/correction anchors, checked snapshot and output hash. |
| Workbook fidelity | Positive supported OOXML grammar rejects unsupported features, including custom views. Only mapped numeric cell XML is changed; every other package part is preserved byte-for-byte. Full-package comparison and independent openpyxl readback pass. [Regression suite][WORKBOOK]. |
| Same bytes across snapshots | [Publication download regressions][DOWNLOAD] prove current and historical publications keep distinct identity/filenames even when workbook hashes coincide; mismatched/cross-scope publication IDs are refused. |
| Independent output | Real PG tests use a separate scoped investor/output pack. Correcting the primary pack preserves exact other revision/candidate/approval/publication/bytes. This proves independence at the current one-output-per-pack boundary. |
| PDF | Live source hash/job above. Historical captured-replay revision 9 has canonical REPLAY observations and visible source text; financial route stays BLOCKED without supported mapping. Response SHA-256 `afc4b4a12164fdc6213d96f06e90be77afb6954be975f6e2e961eb92cf0f05f7`. |

Expected-negative business results—malformed evidence, required FAIL/UNKNOWN, insufficient repair, unsupported mappings, revoked authority and denied publication—are passing safety tests. Infrastructure/test failures remain recorded separately.

## Acceptance A01–A18

Each criterion below is covered by the recorded final API/UI/browser evidence. Coverage levels and scope qualifications are preserved.

| ID | Actual evidence | Current qualification |
|---|---|---|
| A01 | [CSV], [XLSX], [PG] receipt idempotency/conflict/original bytes, [PIPE]; native browser uploads. | Tested in final API and native browser runs; actual receipt/hash archive retained. |
| A02 | [FACT], [NORM], [FIN], [PG] missing-value/provenance projection. | Tested exact Decimal/string IDs/scale/context/missing semantics. |
| A03 | [VALID], [XLSX] cached formula/layout/limits, [NATIVE] role and source-input gates. | Tested independent coverage/dispositions and data-level validation. |
| A04 | [FIN], [PIPE], [CONFIG]; coordinator's balanced/inconsistent cases. | Tested calculations and unknown/ambiguous authority, including the additional migration/balance checks in the final API suite. |
| A05 | [ROUTE], [RPROJ], [STORY]; native first repair/publication blocked. | Tested; priority/confidence cannot override a failed required relationship. |
| A06 | [SIGNAL], [SECOND], [ADAPTER], [PDF], [ROUTE]. | Tested separate contextual/availability signals; both DISABLED and CAPTURED_REPLAY API/browser paths passed. |
| A07 | [PIPE], [REVIEW], [RPROJ], [STORY]; native ready/sample/approval journey. | Tested ready-but-unapproved behaviour, persisted sample and separate independent approval/download in the passed native browser journey. |
| A08 | [CORR], [PG], [NATIVE], [PIPE], [STORY], native complete two-repair journey. | Backend, Storybook and complete native API/browser correction/download journey passed. |
| A09 | [IMPACT], [PG] independent output and configuration races, [CONFIG]. | Tested at declared separate output-pack scope; unknown/cycles fail conservatively. |
| A10 | [PIPE], [PG], [STORY], native completed-but-blocked step; provider failure contracts. | Tested; DISABLED API/browser showed completed processing with provider/source-coverage blockers and disabled review/publication. |
| A11 | [RECOVERY], [IO], [PG] durable outbox/retries/late result; coordinator's actual SIGKILL. | Actual SIGKILL/restart/dispatch tests included in final API run; coordinator recovery/IPC evidence retained. |
| A12 | [REVIEW], [PG] separate resolution/independence/revocation, [STORY]. | Domain/API and Storybook cover the separate soft-resolution branch; the real native core journey proves independent reviewer release. These are distinct coverage levels. |
| A13 | [PUB], [PG] real source/rule/mapping/policy/correction/revocation races, [HTTP], [CONFIG]. | Tested trusted-state/CAS/integrity gates. |
| A14 | [SESSION], [HTTP], [PG] cross-scope tests, [ADAPTER] untrusted content. | Final API suite covers scoped source/document/history/audit access and untrusted provider data. API logs and source hashes are retained; do not imply every negative has a dedicated browser journey. |
| A15 | [OUTPUT], [MANIFEST], [PIPE], [PG] actual backend byte readback. | Actual backend and native browser download/identity/readback passed. Final API includes positive supported XML grammar, package fidelity and publication identity regressions. |
| A16 | [ADAPTER], [SECOND], [PDF], [LIVE], actual page-2 browser component. | Actual LIVE receipt, DISABLED and CAPTURED_REPLAY API/browser verified; provider account-region limitations remain recorded. |
| A17 | [POLICY], [RPROJ], [PG] review sampling, native persisted sample. | Synthetic evaluation JSON is archived with the final API run; persisted ready sampling and routing explanations have domain/API and browser/story coverage, not universal calibration. |
| A18 | [PUB], [PG] history/metrics, [HTTP] review-work API, native sample without CAS change. | Observed local events and complete core browser journey verified; actual cumulative counts appear below and in the retained work report. No measured customer savings. |

## Complete implemented-spec scenario mapping

All **27 requirements and 56 scenarios** across the five implemented capability specs are mapped below. Test aliases resolve to actual implementation test files in the evidence index. Some test names differ from the proposed names in the initial task checklist; proposed filenames are not evidence.


### correction-verification

Source: [implemented specification](../../openspec/specs/correction-verification/spec.md).

#### Explicit versioned financial checks

| Scenario | Acceptance | Actual evidence | Evidence status |
|---|---|---|---|
| High-confidence inconsistent balance sheet | A04 | [FIN] `test_decimal_fee_and_multi_operand_diagnostics`; coordinator's balanced/inconsistent equation regression (six-check run). | Backend tested in the final 288-test run. |
| Unknown required check | A04, A05 | [FIN] `test_context_duplicates_and_rule_ambiguity_never_pass`, `test_balance_sheet_unknown_if_partially_present`; [ROUTE]. | Backend tested. |
| Actual data validation | A03, A04 | [VALID] `test_schema_checks_values_not_only_dtypes`. | Backend tested. |

#### Explicit mappings and supported computations

| Scenario | Acceptance | Actual evidence | Evidence status |
|---|---|---|---|
| Authorised fee treatment | A04 | [NATIVE] `test_all_latest_receipts_ingest_and_two_step_repair_preserves_observations`; [PIPE] `test_real_dagster_native_sources_failed_then_repaired_and_published`; [CONFIG]. | Backend and complete native browser journey tested. |
| Ambiguous mapping | A02, A04 | [NORM] `test_mapping_authority`, `test_context_formula_unknown`; [FIN] `test_context_duplicates_and_rule_ambiguity_never_pass`; [PDF] `test_unsupported_pinned_mapping_is_preserved_without_claiming_interpretation`. | Backend tested; unsupported interpretation stays blocked. [FACTVER] verifies a new immutable fact version and matching canonical SQL provenance. |

#### Versioned source-backed corrections

| Scenario | Acceptance | Actual evidence | Evidence status |
|---|---|---|---|
| Correct an extracted value | A08 | [CORR] `test_failed_then_successful_repair_preserves_history_and_output`; [PG] `test_pending_correction_automatically_has_one_processing_request`; [NATIVE] preserves original observations. | Backend tested; native browser exercised both corrections. |
| Attempt to approve an unresolved failed check | A05, A12 | [PG] `test_actual_postgres_failed_then_successful_correction_download_and_manifest`; [PUB] `test_publication_hard_denials`; native browser blocked first publication. | Backend and core native browser tested. |

#### Evidence-backed impact propagation

| Scenario | Acceptance | Actual evidence | Evidence status |
|---|---|---|---|
| Scoped correction | A09 | [PG] `test_scoped_independent_output_retains_exact_signoff_and_release`; [IMPACT] `test_transitive_closure_and_proven_independence`. | Backend tested for separate scoped output packs; no same-pack multi-artifact claim. |
| Unknown dependency | A09 | [IMPACT] `test_unknown_and_cycle_never_claim_independence`; [RPROJ] `test_missing_currency_threshold_amount_and_dependency_proof_are_not_invented`. | Backend tested. |

#### Recoverable snapshot execution

| Scenario | Acceptance | Actual evidence | Evidence status |
|---|---|---|---|
| Process interruption and replay | A11 | [RECOVERY] actual SIGKILL after `processing_input` and `native_evaluation` stage writes; [PG] recovery/claim tests; [IO]. | Three actual interruption/recovery tests passed, included in the final 288-test API suite; logs and runtime/recovery proof are retained in the portable archive. |
| Older run finishes last | A11 | [PG] `test_restart_and_late_processing_do_not_overwrite_newer_state`, `test_configuration_change_rejects_late_worker_result_without_losing_new_request`. | Real PostgreSQL tested. |

#### Failed checks remain inspectable

| Scenario | Acceptance | Actual evidence | Evidence status |
|---|---|---|---|
| Reconciliation failure | A10 | [PIPE]; [PG] failed-then-successful repair; [RPROJ] `test_required_relationship_is_leading_reason_even_with_high_priority`; [STORY]. | Backend and story browser tested; native first repair stayed blocked. |
| Parser service outage | A10, A16 | [ADAPTER] `test_provider_failure_has_no_native_or_fixture_fallback`; [PDF] PDF upload coverage test. Provider availability is separate from actual native financial outcomes. | Backend tested; actual DISABLED API/browser passed with explicit diagnostics. |

### reporting-evidence

Source: [implemented specification](../../openspec/specs/reporting-evidence/spec.md).

#### Immutable scoped source receipts

| Scenario | Acceptance | Actual evidence | Evidence status |
|---|---|---|---|
| Repeated upload request | A01, A11 | [PG] `test_upload_receipt_idempotency_conflict_and_original_bytes`. | Real PostgreSQL tested. |
| Conflicting idempotency key | A01 | [PG] `test_upload_receipt_idempotency_conflict_and_original_bytes`. | Real PostgreSQL tested. |
| Source revision | A01, A08 | [NATIVE] `test_real_source_replacement_pins_new_governing_input_and_keeps_old_observations`; [PG] upload receipt tests and scoped document download implementation. | Backend and native browser tested; final source versions are 9 with exact receipt/hash evidence retained in the UI checkpoints. |

#### Bounded extraction capabilities

| Scenario | Acceptance | Actual evidence | Evidence status |
|---|---|---|---|
| Supported tabular source | A01, A03 | [CSV] `test_raw_tokens_ids_duplicates_rejects`, `test_delimiter_multiline_empty_tokens`; [XLSX] `test_values_formula_missing_and_locators`; [PIPE]. | Backend tested; actual native browser uploaded all three sources. |
| Unsupported layout | A03 | [CSV] `test_fail_closed`, `test_limits_and_hash`; [XLSX] `test_bad_layout_and_limits`, `test_unsafe_archive`; [NATIVE] unsupported role test. | Backend tested. |

#### Contextual canonical facts

| Scenario | Acceptance | Actual evidence | Evidence status |
|---|---|---|---|
| Scaled amount | A02 | [NORM] `test_scoped_mapping_explicit_scale`, `test_numbers`; [FACT] exact Decimal/identifier roundtrip. | Backend tested. |
| Unresolved period or currency | A02, A04 | [NORM] `test_context_formula_unknown`; [FIN] context/duplicate/rule ambiguity test. | Backend tested. |

#### Source and parser provenance

| Scenario | Acceptance | Actual evidence | Evidence status |
|---|---|---|---|
| PDF citation | A16 | [ADAPTER] `test_preserves_pages_bbox_raw_response_and_untrusted_observation`; [PDF] capture original-page test; [STORY] `PDF citation renders original page, visible bounding box and accessible source text`. | Actual component page 2/overlay/text/axe and both DISABLED/CAPTURED_REPLAY API/browser modes passed. |
| Missing confidence | A06 | [FACT] `test_observations_have_honest_confidence_and_no_authority`; [RPROJ] ready explanation test; [SIGNAL]. | Backend tested; no native percentage fabricated. |

#### Completeness and formula limitations

| Scenario | Acceptance | Actual evidence | Evidence status |
|---|---|---|---|
| Missing source row | A03, A17 | [VALID] `test_coverage_preserves_every_source_occurrence`; [POLICY] held-out omission/coverage cases. | Backend tested. |
| Formula without a current result | A03, A15 | [XLSX] `test_cached_formula_not_current`, `test_values_formula_missing_and_locators`; [OUTPUT] `test_template_denials`. | Backend tested; cached value is not executed calculation evidence. |

#### External processor authorisation and honest availability

| Scenario | Acceptance | Actual evidence | Evidence status |
|---|---|---|---|
| External processing disabled | A16 | [ADAPTER] `test_no_egress_when_disabled_unconfigured_or_unauthorized`; [PDF] `test_pdf_upload_keeps_native_checks_and_blocks_unresolved_coverage`. | No-egress backend tests and actual DISABLED API/browser demonstration passed. |
| Explicit replay mode | A16 | [PDF] `test_capture_is_exact_hash_replay_with_canonical_original_page`, `test_actual_captured_synthetic_response_is_replay_only`, `test_different_pdf_has_no_silent_replay_or_live_fallback`. | Backend and actual fresh-upload CAPTURED_REPLAY API/browser tested; canonical observations remain labelled REPLAY. |

### review-routing

Source: [implemented specification](../../openspec/specs/review-routing/spec.md).

#### Hard-gate routing precedence

| Scenario | Acceptance | Actual evidence | Evidence status |
|---|---|---|---|
| Confidence cannot cancel financial failure | A05 | [ROUTE] `test_failed_relationship_leads_even_with_high_confidence_and_agreement`; [RPROJ] `test_required_relationship_is_leading_reason_even_with_high_priority`. | Backend tested; financial failure leads explanation. |
| Pending required checks | A05, A10 | [ROUTE] required-check coverage cases; [RPROJ] `test_current_mutation_clears_old_ready_explanation_and_priority`; [STORY]. | Backend and story browser tested. |

#### Separate and contextual parser signals

| Scenario | Acceptance | Actual evidence | Evidence status |
|---|---|---|---|
| Same digits with different scale | A06 | [SIGNAL] contextual comparison cases; [SECOND] `test_same_digits_with_different_currency_or_period_are_disagreement`; [NORM]. | Backend tested; context is part of agreement. |
| Optional second pass absent | A06 | [SECOND] `test_not_run_does_not_call_optional_parser_or_invent_agreement`; [SIGNAL] absent-state cases. | Backend tested. |

#### Conservative quick-review eligibility

| Scenario | Acceptance | Actual evidence | Evidence status |
|---|---|---|---|
| Supported native extraction | A07 | [PIPE]; [RPROJ] `test_ready_explanation_keeps_checks_signals_and_human_approval_separate`. | Backend tested; native browser inspected ready-but-unapproved state before separate independent approval. |
| Unevaluated AI threshold | A05, A06 | [ROUTE] probabilistic quick-review policy cases; [POLICY] versioned policy cases. | Backend tested; unsupported AI readiness is at least NEEDS_REVIEW. |
| Parser disagreement without a hard blocker | A06, A12 | [PG] `test_soft_resolution_is_separate_and_required_before_approval`; [SECOND] preserves both observations; [STORY] reader-resolution journey. | Domain/API and synthetic story browser tested. No separate real API soft-signal browser journey is claimed. |

#### Explainable priority without false certainty

| Scenario | Acceptance | Actual evidence | Evidence status |
|---|---|---|---|
| User opens a ready item | A07, A17 | [RPROJ] ready explanation; [PG] `test_review_activity_is_scoped_durable_and_does_not_change_financial_revision`; native browser independently sampled ready item without CAS change. | Domain/API routing/priority projection and the core native ready-item sample passed; Storybook covers presentation. No separate native journey for every policy edge is claimed. |
| Material failed relationship | A04, A05 | [FIN] operand/difference diagnostics; [RPROJ] required relationship leading reason; [STORY] separate-state pages. | Domain/API diagnostics and priority projection plus Storybook presentation tested. |

#### Policy evaluation and correction feedback

| Scenario | Acceptance | Actual evidence | Evidence status |
|---|---|---|---|
| Agreeing parsers are both wrong | A17 | [POLICY] `test_agreeing_correlated_errors_do_not_become_proof_of_correctness`, `test_false_ready_report_counts_an_unsafe_prediction_instead_of_erasing_it`. | Held-out synthetic evaluation tested; not calibrated correctness. |
| Reviewer corrects a case | A17, A18 | [POLICY] `test_priority_and_later_reviewer_labels_do_not_silently_modify_policy`; [PG] separate resolution and immutable correction history. | Backend tested; live thresholds are not automatically changed. |

### reviewed-pack-release

Source: [implemented specification](../../openspec/specs/reviewed-pack-release/spec.md).

#### Independent exact-snapshot approval

| Scenario | Acceptance | Actual evidence | Evidence status |
|---|---|---|---|
| Preparer attempts self-approval | A12 | [REVIEW] `test_independent_review_and_attestation_required`; [PG] `test_independence_applies_to_correction_contributors_even_with_reviewer_grant`. | Backend tested. |
| Reviewer resolves a soft signal | A12 | [PG] `test_soft_resolution_is_separate_and_required_before_approval`; [STORY] `reader resolution remains separate from approval and retains both readings`. | Domain/API and synthetic browser tested; no separate real API soft-branch browser journey claimed. |
| Reviewer selects a different value | A08, A12 | [CORR] versioned correction cases; [NATIVE] governing input and source-replacement cases; [PG] correction invalidates approval; [PDF] unsupported configured mapping preservation. | Domain/API tests cover the value/source-version path and unsupported treatment stays blocked. UI provides source replacement; this edge path is not claimed as a separate native browser journey. No arbitrary treatment override. |

#### Backend release eligibility

| Scenario | Acceptance | Actual evidence | Evidence status |
|---|---|---|---|
| Forged pass request | A13, A14 | [HTTP] `test_clients_cannot_grant_roles_pass_flags_or_review`, `test_body_cannot_override_scopes_or_smuggle_check_authority`. | API tested. |
| Missing bytes or required evidence | A13 | [PG] `test_missing_output_bytes_deny_publication_without_erasing_checks`; [PUB] hard denials; [MANIFEST]. | Backend tested. |

#### Version freshness and race safety

| Scenario | Acceptance | Actual evidence | Evidence status |
|---|---|---|---|
| Change between approval and release | A09, A13 | [PG] `test_all_relevant_configuration_and_source_writers_race_publication`, `test_simultaneous_publication_and_correction_serialize_at_current_snapshot`, revocation commit-order tests; [CONFIG]. | Real PostgreSQL source/rule/mapping/policy/correction/revocation races tested. |
| Unobserved external state | A13, A18 | [PUB] `test_publication_hard_denials`; freshness gate and external observation metadata remain explicit. | Backend tested for declared UNKNOWN freshness; no external freshness inferred. |

#### Idempotent publication and historical evidence

| Scenario | Acceptance | Actual evidence | Evidence status |
|---|---|---|---|
| Duplicate release request | A13, A18 | [PG] `test_actual_postgres_failed_then_successful_correction_download_and_manifest`; [PUB] `test_real_publication_download_and_idempotent_retry`. | Real PostgreSQL and pure lifecycle tested. |
| Inspect superseded output | A18 | [PG] `test_correction_invalidates_approval_and_historical_release_remains_labelled`; [PUB] `test_historical_download_remains_permissioned_and_stale`. | Backend historical-output access tested; the core native browser's current publication/download also passed. |

#### Permissioned review and evidence access

| Scenario | Acceptance | Actual evidence | Evidence status |
|---|---|---|---|
| Cross-fund access | A14 | [PG] `test_cross_tenant_fund_and_pack_access_has_no_evidence_leak`; [HTTP] scope/count/forged-body tests; [SESSION] local/session/CSRF boundary tests. | Backend/API scoped access tests passed in the final suite; evidence levels remain domain/API rather than a browser journey for every negative. |
| Document instruction masquerades as approval | A14 | [ADAPTER] `test_preserves_pages_bbox_raw_response_and_untrusted_observation`; [HTTP] refuses submitted authority; deterministic ingestion does not execute document instructions. | Contract/API tests preserve untrusted uploaded/provider content without granting instruction or approval authority. |

#### Supported template-preserving output

| Scenario | Acceptance | Actual evidence | Evidence status |
|---|---|---|---|
| Corrected output download | A15 | [PIPE]; [PG] actual correction/download/manifest test; [OUTPUT] roundtrip; [MANIFEST]. | Actual backend and complete native browser workbook/manifest readback passed. |
| Unsupported output feature | A15 | [OUTPUT] `test_template_denials`; [WORKBOOK] OOXML extension, external relationship and inline/shared rich/phonetic regressions; [XLSX] unsafe archive/cache tests. | Backend tested; unsupported features are not silently stripped. |

### reviewer-workspace

Source: [implemented specification](../../openspec/specs/reviewer-workspace/spec.md).

#### Separate business state and processing state

| Scenario | Acceptance | Actual evidence | Evidence status |
|---|---|---|---|
| Pipeline succeeds with inconsistent data | A10 | [PIPE] actual native failure; [STORY] eight separate-state scenarios; [RPROJ]. | Backend/story tested; real native first repair remained BLOCKED with completed processing. |
| Pending human review | A07, A10 | [PIPE] worker finishes before separate API review; [PG] separate approval; [STORY] reviewable states. | Backend/story tested; independent native reviewer acted without a live processing wait. |

#### Evidence-first review and navigation

| Scenario | Acceptance | Actual evidence | Evidence status |
|---|---|---|---|
| Trace and correct a value | A08, A16 | [PG] exact source-backed correction; [STORY] synthetic correction loop and source views; [NATIVE_BROWSER]. | Complete native browser source/correction/output journey and both DISABLED/CAPTURED_REPLAY PDF API/browser paths passed. |
| Inspect a green item | A07, A17 | [PG] scoped review activity; [STORY] ready/source pages; [NATIVE_BROWSER] reviewer sample persisted with unchanged financial version. | Backend and core native browser tested. |

#### Complete correction-loop interaction

| Scenario | Acceptance | Actual evidence | Evidence status |
|---|---|---|---|
| Failed repair followed by successful repair | A08, A15 | [PIPE]; [PG] failed/successful output readback; [STORY] `complete synthetic failed correction, repair and separate independent approval`; [NATIVE_BROWSER]. | Backend, Storybook and complete core native browser journey passed, including exact downloaded-byte verification. |

#### Observed review-work measurement

| Scenario | Acceptance | Actual evidence | Evidence status |
|---|---|---|---|
| Demonstration report | A18 | [PG] `test_review_activity_is_scoped_durable_and_does_not_change_financial_revision`; [HTTP] review-work endpoints; [POLICY]; this report's observed-evidence ledger. | Observed local events tested; the complete-journey work report is retained and actual cumulative counts are reported below. No customer savings measured. |

## Observed review work and policy evaluation

`browser-reviewed/index.json` and `native-observed-review-work.json` retain the actual counts. Review activity is stored separately from financial CAS revisions, with server-resolved actor, timestamp, loaded revision and scoped fact/document targets. Ready sampling requires an authorised reviewer and a current checked ready snapshot; retries do not double count.

In the final journey `READY_ITEM_SAMPLED` increased **5 → 6**, while CAS remained **89 → 89**. Cumulative recorded counts are `SOURCE_OPENED=5`, `VALUE_INSPECTED=0`, `READY_ITEM_SAMPLED=6`, total 11. Actions: `CORRECTED=14`, `RESOLVED=0`, `APPROVED=4`, `REJECTED=0`. The span **4310.646498 seconds** runs from `18:39:00.695360` to `19:50:51.341858` UTC, including repeated automated synthetic activity and pauses. It is not active human review time, pipeline duration or measured savings. The final single journey performed three uploads, two corrections, one ready sample, one independent approval and one publication.

Policy fixtures are [review-policy-v1.json](../../apps/api/tests/fixtures/review-policy-v1.json) and [review-policy-cases-v1.json](../../apps/api/tests/fixtures/review-policy-cases-v1.json). The 13 held-out synthetic cases include correlated wrong-parser observations and contextual/coverage negatives. False-ready 0/13 is limited to this fixture/policy, with 22/26 required-check coverage and 5 blocked / 5 review / 3 ready. An unsafe-prediction counter-test verifies failures are counted. Retained evaluation JSON SHA-256: `3db87f9c68f0f60cc35586acb493f5f1ee839810afcd06e48b3e26201344920f`.

## Acceptance decision and bounded limitations

The coordinator accepts the implemented use-case-1 MVP on the documented synthetic, localhost scope. All 40 implementation/acceptance tasks have recorded evidence; all 27 requirements and 56 scenarios map to real tests or documented browser checks. The five baseline capability specs are synchronised without weakening requirements and the completed change is archived. No phase-2 work is started by this decision.

All eight state stories and soft resolution have browser coverage using Storybook fixtures; the core native correction/review/release journey uses the real API. Alternative-value/context and policy edge cases have unit/domain/API coverage. No separate native browser journey for every branch is asserted. The PDF mode runs are historical and labelled, while final API/PDF component checks follow the repairs. Actual synthetic live-provider evidence is preserved separately from replay.

Supported scope is deliberately bounded: declared CSV/XLSX layouts, exact context and explicit scoped mappings, a fictional approved fee relationship, supported balance-sheet/source-to-pack checks, and a value-only workbook template. Formula caches are not execution; unsupported macros, external links, rich workbook features, mappings and unproven dependency coverage remain blocked. A separate scoped pack is the current independent output/review boundary.

Canonical provenance does not establish source truth. Agreement does not make correlated observations independent proof, and a model's reported confidence is not a correctness probability. Accounting treatment and materiality require the appropriate explicit configured authority; unknown context cannot be supplied by reviewer prose alone. Governing inputs remain tied to their immutable source observations; source replacement creates new evidence, while unsupported treatment changes stay unresolved.

Authentication is loopback-only development authentication with one API worker, server configured preparer/reviewer grants, opaque sessions and CSRF. Its publication/revocation lock semantics are verified for that declared runtime, not asserted as production IAM. External freshness is only the last permitted observation; local manifests do not recall downloaded copies. Broader private-data processing, production residency/security claims and phase-2 evidence-request automation are outside this demonstrated scope.

## Evidence index

Test links below resolve to implementation files. Raw logs, JUnit, source digests, screenshots and downloads are durable members of the portable archive.

[FACT]: ../../apps/api/tests/test_facts_contracts.py
[NORM]: ../../apps/api/tests/unit/test_normalisation.py
[CSV]: ../../apps/api/tests/unit/test_csv_extractor.py
[XLSX]: ../../apps/api/tests/unit/test_excel_extractor.py
[VALID]: ../../apps/api/tests/unit/test_validation.py
[FIN]: ../../apps/api/tests/unit/test_reconciliation.py
[NATIVE]: ../../apps/api/tests/unit/test_native_processing.py
[SIGNAL]: ../../apps/api/tests/unit/test_parser_signals.py
[ROUTE]: ../../apps/api/tests/unit/test_routing.py
[SECOND]: ../../apps/api/tests/unit/test_second_pass.py
[ADAPTER]: ../../apps/api/tests/contract/test_reducto_adapter.py
[PDF]: ../../apps/api/tests/unit/test_pdf_evidence.py
[LIVE]: ../../apps/api/tests/live/test_reducto_pdf.py
[POLICY]: ../../apps/api/tests/evaluation/test_policy_cases.py
[PG]: ../../apps/api/tests/integration/test_postgresql_lifecycle.py
[CONFIG]: ../../apps/api/tests/integration/test_configuration_processing.py
[CORR]: ../../apps/api/tests/integration/test_corrections.py
[IMPACT]: ../../apps/api/tests/integration/test_impact.py
[PIPE]: ../../apps/api/tests/integration/test_pipeline.py
[IO]: ../../apps/api/tests/integration/test_pipeline_io.py
[RECOVERY]: ../../apps/api/tests/integration/test_pipeline_recovery.py
[RPROJ]: ../../apps/api/tests/integration/test_routing_projection.py
[REVIEW]: ../../apps/api/tests/integration/test_review.py
[PUB]: ../../apps/api/tests/integration/test_publication.py
[OUTPUT]: ../../apps/api/tests/integration/test_output_template.py
[MANIFEST]: ../../apps/api/tests/integration/test_manifest.py
[HTTP]: ../../apps/api/tests/test_routes_packs.py
[SESSION]: ../../apps/api/tests/test_access_sessions.py
[STORY]: ../../apps/web/tests/stories.spec.ts
[NATIVE_BROWSER]: ../../apps/web/tests/native-journey.spec.ts

[FACTVER]: ../../apps/api/tests/integration/test_fact_interpretation_versions.py
[WORKBOOK]: ../../apps/api/tests/unit/test_workbook_features.py
[PDF_BROWSER]: ../../apps/web/tests/native-pdf.spec.ts
[API_RUN]: evidence/evidence-index.json
[API_LOG]: evidence/evidence-index.json
[API_JUNIT]: evidence/evidence-index.json
[API_HASHES]: evidence/evidence-index.json
[POLICY_REPORT]: evidence/evidence-index.json
[POLICY_ARTIFACT]: evidence/evidence-index.json

[UI_INDEX]: evidence/browser-index.json

[DOWNLOAD]: ../../apps/api/tests/integration/test_download_publications.py

## Portable evidence and final local runtime

The [portable archive](evidence/README.md) and [per-file inventory](evidence/evidence-index.json) retain the evidence. Archive SHA-256: `6cf0efacc4b22c34fcb0ade31c6e969979d437847be190416e35ca5d5000c184`. The API source-digest manifest hash is `81fb8fd7d77b038bb9604008a953d4b57de3f7433f86aaa438b56ee54976caa9`; UI digest manifest `cee8f9e87562ebdcf41045217e9148f389a68cd9ae697a06ddeb03572eb2e338`. Final browser index hash: `b08ec8175b4e7ec8534175f9bce5d9a789b8c97ac5e71d357dc97191fef32b4d`.

The integration runtime completed `down --keep-db`, `up`, then another `up`. API, Dagster code location, daemon, webserver and UI were healthy; repeated startup reused healthy processes. PostgreSQL uses loopback 55433, distinct from acceptance database 55432. PDF mode was explicitly `CAPTURED_REPLAY`. After transferring final source, an explicit UI restart and HTTP source verification preceded the passing native journey; restart the affected service after code updates instead of relying on transferred-file watcher events.
