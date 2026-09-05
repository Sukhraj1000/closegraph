## Context

This is a specification-only greenfield project. See `proposal.md` for the interview-led job and `docs/product-brief.md` for evidence. The approved refinement permits our own source-backed extraction and financial reconciliation tools, selects Dagster for computational orchestration, and retains use case 1 before use case 2.

The supplied datasets do not contain the interview's historical NAV revisions or side letter. Use labelled synthetic files for the correction demonstration; do not infer formula lineage from value-only workbooks or claim a captured response is live processing.

## Goals / Non-Goals

**Goals:** A bounded but real file-to-corrected-pack pipeline; deterministic checks outside models; explicit three-signal review routing; source/version integrity; independently reviewable corrections; restartable processing; a small local installation.

**Non-Goals:** A general agent framework, universal document semantics, an Excel calculation engine, licensed fund administration, autonomous legal interpretation, a second scheduler, production deployment, phase-2 requests/deadlines or MCP. No claim that a passing gate proves source truth.

## Decisions

### 1. One Python tool layer and one computational orchestrator

Use Python 3.12+, FastAPI/Pydantic, Dagster, Polars, openpyxl, Pandera, SQLAlchemy/Alembic and PostgreSQL. Use React/TypeScript with Vite for the reviewer UI. Pin compatible runtime versions and generate lockfiles during implementation; only OpenSpec tooling is currently installed in this repository.

Ordinary Python functions perform extraction, normalisation, checks, impact analysis and supported output generation. Dagster wraps those functions as assets and owns computational scheduling/retries. Domain services own authorisation, corrections, review and publication. Keep the two testable separately.

Alternative: a PostgreSQL-backed task queue was appropriate for receipt-only coordination, but is not selected now that reproducible multi-stage extraction/reconciliation is core. Do not add Procrastinate, Celery, Redis, Kafka, NiFi or Temporal beside Dagster. A relational dependency-edge table is enough; no graph database.

### 2. Explicit source routing with bounded capabilities

- CSV: Polars with declared delimiter/encoding/schema; preserve raw tokens and string identifiers before typed conversion.
- XLSX: openpyxl for cell coordinates, values, formulas, styles and caches; Polars for tabular operations. Never execute macros or fetch external workbook links. openpyxl is not a formula evaluator. Unsupported formula-dependent values remain blocked unless a separately supported Python computation supplies an evidenced result.
- PDF: a Reducto adapter converts actual returned blocks/citations into the shared contract. It preserves original page versus processed page, bounding-box coordinate system, raw response and parser settings. Reducto is an AI-backed external dependency, not a deterministic truth source.
- Optional second pass: a shared observation interface accepts a future Docling adapter. Do not install/run a second parser by default. Test NOT_RUN/UNAVAILABLE and explicitly labelled disagreement fixtures; add live Docling only if a bounded evaluation justifies it.
- Provider/export: an adapter can accept Ylookup/accountant outputs with explicit provenance. No assumed Ylookup API or unverified live integration.

Initial format support is declared per layout, not "any private-market file". Build a native CSV source plus a simple value-only XLSX reporting template first; add a supported PDF fixture through Reducto after data-use permission/credentials exist. The native journey can run without egress, but full live PDF acceptance remains blocked until tested or explicitly removed from MVP scope by the user.

Use size/page/row/time/memory limits, file-signature checks and low-privilege parsing without default network. Only the authorised external-parser adapter has narrowly configured egress. Store uploads outside the web root; reject arbitrary paths/URLs, malicious ZIP/XML expansion and document instructions that request privileged actions.

### 3. Canonical records preserve meaning, not just digits

Pydantic validates the nested contract; Pandera validates collected Polars DataFrames with schema AND data checks. Do not mistake LazyFrame schema validation for executed financial/data validation. Retain rejects and exclusion reasons; never drop bad rows to obtain green totals.

Core records in PostgreSQL:
- `DocumentVersion`: scope, immutable storage key/hash, receipt identity, authority/coverage status, observed time.
- `SourceOccurrence`: document version, exact locator, raw content, context evidence and disposition.
- `ExtractionObservation`: parser/version/settings, response identity, value/context candidate, actual confidence type/value; separate observations for each parser.
- `FactVersion`: metric key, entity, period/as-of, decimal value, currency, original unit/scale, evidence, approved interpretation/correction and superseded version.
- `CheckResult`: check/rule version, input snapshot, required/applicability status, operands, difference, tolerance, result and diagnostics.
- `DependencyEdge`: scoped upstream fact/rule version to downstream fact/check/output, provenance and coverage status.
- `Correction`, `ReviewDecision`, `Publication`: separate append-only decisions/version records with authority and exact snapshot references.
- `ProcessingRequest` and `AuditEvent`: durable launch intent and business event history. These are not a second job scheduler.

Money uses Python Decimal and PostgreSQL NUMERIC. JSON serialises normalised decimal values as strings; raw scale and currency are explicit. IDs remain strings. Zero is not missing. Normalisation does not silently equate revenue labels or ownership concepts without an approved scoped mapping.

Illustrative contract shape, not a runtime result:

```json
{
  "fact_id": "synthetic-ebitda",
  "version": "v1",
  "entity_id": "synthetic-entity",
  "metric": "ebitda",
  "value_decimal": "920000.00",
  "currency": "GBP",
  "period": "2026-Q2",
  "raw_value": "920k",
  "raw_scale": "thousands",
  "source": {
    "document_version_id": "synthetic-document-v1",
    "content_hash": "<computed-on-ingestion>",
    "locator": {"kind": "pdf", "original_page": 17, "coordinate_system": "normalised-0-1", "bbox": [0.21, 0.42, 0.72, 0.47]},
    "context_evidence_ids": ["synthetic-period-heading", "synthetic-currency-heading"]
  },
  "observation_ids": ["primary-observation", "secondary-observation"],
  "check_snapshot_id": "checks-v1",
  "review_decision_ids": [],
  "supersedes": null
}
```

Do not hard-code these synthetic values or create one generic `status=approved` field that overwrites extraction/check history. Keep execution, validation, triage, review, freshness and publication separate.

### 4. Deterministic reconciliation and hard gates

Start with declared balance-sheet tie-outs, source-to-pack equality and one explicitly authorised fixture-specific fee calculation/allocation. All operands include entity, period and currency. Rule version, rounding and tolerances are pinned; a balanced relationship alone does not prove correct classification. Unknown rule applicability is not NOT_APPLICABLE. Required unknowns block.

Check coverage includes source boundaries/totals where available, record dispositions and output dependency coverage. A parser's own row count is not independent completeness evidence. A failed relationship links all contributing facts; do not falsely accuse a single field.

Route precedence:
1. BLOCKED: required FAIL/UNKNOWN/NOT_RUN, material evidence/context missing, unsupported scope, or unverifiable dependencies.
2. NEEDS_REVIEW: no hard blocker but unresolved parser disagreement, uncertain interpretation or probabilistic extraction lacking a tested quick-review policy.
3. READY_FOR_QUICK_REVIEW: all hard requirements pass and the observation pattern meets a versioned supported policy; human approval is still required.

Keep confidence provenance and agreement separate. Compare the complete contextual tuple, not digits alone. Optional second pass absent is NOT_RUN, not AGREE. Native extraction may use a tested single-parser policy with confidence NOT_APPLICABLE. Initially route probabilistic extraction to review unless explicitly evaluated policy supports quick review. Never invent a confidence threshold or present an uncalibrated score as probability of correctness.

For MVP, use transparent within-route priority tiers from configured materiality and dependent-output impact, not an opaque weighted risk number. Priority cannot move an item across hard-gate boundaries. Human evidence-backed adjudication can resolve soft signals for a snapshot without erasing the observations. Material failed checks must actually be resolved and rerun.

### 5. Snapshot-bound Dagster assets

```text
source_receipts -> extracted_occurrences -> canonical_snapshot
                                               |
                                      reconciliation_results
                                               |
                                        candidate_pack
                                               |
                                        review_snapshot
                                               |
                                  application review/decision
                                               |
                                  backend publication gate
```

Assets pass immutable snapshot references through function inputs/IO managers. `deps=[...]` alone only declares dependencies, not data passing or per-document isolation. A processing unit is an immutable pack revision with an explicit document-version set and pinned configuration. Use its processing key as a run/partition identity; concurrent packs must never share an unqualified "latest document" lookup.

The API commits a `ProcessingRequest` with its domain mutation. A Dagster sensor reads committed requests and emits runs with stable run keys; Dagster owns retries. Reconcile acknowledgement/cursor recovery against persisted run identities so a sensor restart cannot lose work. Stage writes have database uniqueness keys including snapshot, stage and code/config versions. At-least-once execution must have idempotent effects; late runs remain historical.

Financial FAIL is a persisted result, not an infrastructure exception. `candidate_pack` returns an ineligible descriptor when generation is unsafe, and `review_snapshot` still records facts/diagnostics. Do not place blocking Dagster checks on a path that suppresses the review queue. Use explicitly blocking ERROR checks only on actual downstream release computations, and always retain the application's independent publication gate.

Human review does not keep a run alive. An authorised correction writes a new fact/pack revision and a new processing request. Dagster reruns the affected supported functions; application dependency records determine financial impact. Dagster's asset graph is not field-level accounting lineage.

### 6. Corrections and exact-template output

The preparer records evidence, reason and scope for a correction or approved rule change. The system retains original observations, traverses declared dependencies, stales affected checks/approvals and recomputes derived values. Unknown dependency coverage conservatively blocks the potentially affected scope. Independence must be established before preserving an unrelated output's current sign-off.

Generate a candidate XLSX using one declared value-only template and an allowlist of mapped cells. Reuse its layout/styles and verify unmapped cells/structure are preserved. Compute supported derived values in Python; do not insert unevaluated formulas and imply they are calculated. Validate the generated artifact by reading it back and comparing mapped values, layout contract and hash. Retain the original template and every candidate.

The reviewer sees the candidate bytes/preview and exact snapshot before approval. If a future provider returns the revised pack instead, it must pass the same source-to-output checks; this does not create a second approval path. Unsupported macros/layouts/calculations block output generation.

### 7. Application review, permissions and publication

Proposed API: upload sources; inspect pack/review snapshot and citations; create an evidenced correction; request recomputation; submit an independent review decision; request publication; download an authorised artifact/manifest. Clients submit actions, never trusted pass flags or arbitrary storage paths.

Use server-resolved sessions and seeded preparer/reviewer accounts for localhost development, with password hashes, HTTP-only session cookies, CSRF protection on mutations and per-resource authorisation. Seeded development auth must refuse non-local/public operation. Production identity integration and deployment remain separate decisions. Apply scope filters to facts, citations, filenames, graphs, counts and diagnostics, not just downloads.

A reviewer cannot finally approve a scope they prepared/corrected. A soft disagreement needs explicit evidence-backed resolution. Failed/unknown required checks cannot be waived in this MVP. Revoked role/approval, new rules/policy, or changed dependencies invalidate current release eligibility.

Store candidate bytes durably before approval. The publication service locks the scoped current-version record (or uses an equivalent compare-and-swap transaction), rechecks current dependencies/policy/approval and actual output integrity, then atomically registers the publication and audit events. All version-changing writers participate in the same scoped lock/version protocol. Do not hold database locks while running parsers or waiting for people. Storage and SQL are not one transaction: an orphan blob is tolerable; a visible publication pointing to missing/unchecked bytes is not.

Repeated identical release requests return the existing publication. Historical packs remain permissioned and visibly stale/superseded after revision. Export a separate version/as-of source/check/review manifest; do not claim downloaded external copies can be recalled. No external accounting writes or investor distribution.

### 8. Storage, local operation and evaluation

Use local content-addressed files under ignored `var/` behind a storage interface. Do not introduce S3/MinIO merely for the local demo. Use PostgreSQL for domain state and an isolated Dagster metadata database/schema; the application does not treat Dagster metadata as business authority. Bind API/UI/operator services to localhost. Business audit events belong in the application; Dagster logs support diagnosis but are not the compliance audit record.

Proposed code layout:

```text
apps/api/src/closegraph/
  api/                 routes, sessions and authorisation
  contracts/           canonical records and typed input/output contracts
  extractors/          csv, excel, reducto, observation interface
  normalisers/         numbers, context and approved mappings
  validators/          schema, coverage and supported financial checks
  services/            corrections, impact, routing, review and publication
  pipeline/            Dagster assets, resources and request sensor
  storage/             immutable blob and database repositories
  outputs/             mapped XLSX template writer and manifest
apps/api/tests/        unit, contract, integration and security tests
apps/web/              React review interface and Playwright tests
fixtures/synthetic/    labelled inputs, expected values and scenario metadata
```

Keep fixed and held-out source-labelled cases with expected value/context/evidence, gate outcomes and output values. Include both parsers wrong together, high confidence with financial failure, omitted records, unit/period errors, stale formula caches, missing providers, duplicate inputs and unauthorised requests. Record false-ready errors alongside coverage and review burden. Do not change thresholds live from reviewer feedback; version candidate policy and compare before adoption. No AI self-confidence threshold is considered calibrated merely because a finite synthetic test passes.

## Risks / Trade-offs

- [Unknown source truth or legal treatment] -> preserve uncertainty, require approved scoped rules and block unsupported conclusions; no universal accuracy claim.
- [Parser agreement shares an error] -> contextual comparisons, independent financial/source anchors, held-out errors and audit sampling of ready items.
- [External parser cost/privacy or credentials unavailable] -> no egress by default, native-file first slice, explicit consent/configuration and capability-specific acceptance evidence; never fake live results.
- [Dagster adds deployment components] -> one local code location and one orchestration system; do not expose it as the customer UI.
- [Dependency maintenance becomes expensive] -> one supported workflow with declared mappings; prove correction value before a universal mapper.
- [Formula/template loss] -> value-only initial template, explicit capabilities and round-trip checks; unsupported features block.
- [False sense of security from approval] -> separate states, independent roles and finite-test limitations visible in the UI/report.

## Migration Plan

There is no running application or production state to migrate. Implement native extraction/checking first, wrap it in Dagster, then integrate the review/correction/release UI. Add the authorised PDF adapter path without changing the canonical contract. Use reversible database migrations and isolated synthetic data for local resets; never delete source artifacts as a side effect of retry.

Do not deploy, upload private documents, create external accounts or begin phase 2 during specification work. Full MVP acceptance requires real execution evidence; absent PDF authorisation leaves live PDF acceptance blocked unless the user explicitly narrows scope. Archive/sync implemented baseline specs only after the change is implemented and verified.

## References

- https://docs.dagster.io/guides/build/assets/defining-assets
- https://docs.dagster.io/api/dagster/asset-checks
- https://docs.reducto.ai/parse/overview
- https://docs.reducto.ai/configs/extract/citations
- https://pandera.readthedocs.io/en/stable/polars.html
- https://openpyxl.readthedocs.io/en/3.1/tutorial.html

These inform the design, not proof that this project is implemented or financially correct.
