# CloseGraph

A local correction-and-verification workspace for supported private-fund reporting: inspect the source, correct a discrepancy, rerun its checks, and release the exact independently reviewed workbook.

## Current scope

The use-case-1 MVP is implemented and has passed automated technical acceptance. The [acceptance evidence](docs/verification/mvp-acceptance.md) records actual commands, scenario coverage, artifact identities and coverage limits. It is the completion record; a successful pipeline alone does not establish financial correctness.

The native workflow supports declared CSV/XLSX layouts, explicit entity/period/currency context, an approved fictional fee rule, deterministic Decimal reconciliations and one value-only XLSX output template. PDF evidence uses Reducto observations with original-page citations. Disabled providers and unsupported financial mappings remain visible blockers. Captured replay is explicitly distinguished from the separately executed synthetic live-provider test.

React/TypeScript provides source-to-value review, corrections, check explanations, audit history and observed review activity. FastAPI and PostgreSQL own scoped evidence, immutable versions, decisions and publication. Dagster executes extraction, calculation and checks; jobs finish before independent review begins. Original evidence and failed checks remain inspectable after correction.

## Run locally

Requires macOS, Python 3.12, uv, Node.js and Docker Desktop. Follow [local runtime setup](docs/engineering/local-runtime.md) for the complete configuration, health checks and shutdown process.

```sh
uv sync --locked --project apps/api
npm ci --prefix apps/web
python3.12 scripts/local_runtime.py init
python3.12 scripts/local_runtime.py up
python3.12 scripts/local_runtime.py status
```

Open [CloseGraph](http://127.0.0.1:24173). `init` creates distinct random local `preparer` and `reviewer` passwords in the owner-only `.local/dev-runtime/.env`; it prints the location without printing secrets. Seeded packs separate the native reporting journey from the PDF evidence demonstration. Use the explicitly labelled files in [fixtures/synthetic](fixtures/synthetic/README.md). These fictional rules are test authority, not general accounting treatment.

Stop with `python3.12 scripts/local_runtime.py down`; the managed database volume and source bytes are retained. Services bind to localhost and run under macOS Seatbelt. The runtime does not inherit provider, GitHub or Codex credentials and has no external provider egress.

## Engineering without repeated approvals

The user supplied [standing engineering authorization](docs/engineering/standing-authorization.md) for implementation, testing, independent review, repairs, PR publication and automatic merging. Routine engineering work requires no additional approval. This does not fabricate a human review or override financial approval inside the application.

The [Codex runner](https://github.com/Sukhraj1000/closegraph/pull/55) uses isolated clones, up to three disjoint ownership claims, a sandbox-only command broker, a separate review run, exact revision checks, serial merging and post-merge verification. Its installed CLI boundary must pass an empirical pilot before activation. The earlier Hermes schedules remain paused. Historical paused-setup documents are retained as history; the standing authorization and current runner documentation describe the selected workflow.

## Verification

```sh
uv run --locked --project apps/api pytest apps/api/tests -q
npm --prefix apps/web test
npm --prefix apps/web run build
npm --prefix apps/web run test:browser
python3.12 -m unittest discover -s automation/tests -v
npm ci
npm run spec:check
```

Database tests require an isolated real PostgreSQL database through `CLOSEGRAPH_TEST_DATABASE_URL`. The actual browser journeys require the local services and explicit test accounts; the PDF contract suite and retained live receipt have distinct configuration. See the [acceptance evidence](docs/verification/mvp-acceptance.md) for reproducible command environments and actual results. A missing prerequisite is not a passing test.

OpenSpec is pinned locally. The [completed implementation checklist](openspec/changes/archive/2026-09-05-verify-corrected-reporting-pack/tasks.md), [design](openspec/changes/archive/2026-09-05-verify-corrected-reporting-pack/design.md), [acceptance criteria](docs/acceptance.md) and [product brief](docs/product-brief.md) define scope. OpenSpec validation checks specification structure; it does not test the application. The five implemented [baseline specs](openspec/specs/) are synchronised; no phase-2 change is active.

## Product and data boundaries

Checks, parser observations, review decisions, execution state and version freshness remain separate. Hard blockers override soft confidence. Corrections create new versions, and publication requires an independent decision over the exact current checked artifact. A downloaded historical output remains historical; the application cannot recall copies.

The repository contains labelled synthetic inputs. Private datasets, interview PDFs, LP details and provider credentials remain outside Git. Supported mappings and accounting treatment must be explicit; arbitrary documents, general spreadsheet recalculation, live Ylookup integration, production IAM/compliance and autonomous accounting are not claimed.

Use case 2—missing-evidence requests, owners, deadlines and escalation—remains deferred. This build does not deploy production services, provision paid infrastructure, distribute investor reports or post accounting transactions.
