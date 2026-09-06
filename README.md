# CloseGraph

CloseGraph helps private-market fund teams answer **what is holding up this reporting pack, where is the evidence, and who needs to act?** An accountant uploads messy workbooks, confirms the question being checked, inspects the affected records and requests a correction. An account manager sees the changes and independently reviews the selected completed scope.

Interviews with fund managers, accountants and account managers identified repeated manual workbook checks, unclear sources of truth, and long chains of requests for missing information. This POC keeps the question, source record, owner and correction history together. It supports an existing administrator workflow; it does not produce or certify NAV, fees or final accounts.

## Judges: run the local demo

Prerequisites: **macOS**, Docker Desktop running, **uv**, Python 3.12 and Node.js 20.19+ (or a supported later version). Ports 24173, 24180, 24181, 24182 and 55432 must be free. From this repository:

```sh
npm run demo
```

This installs locked Python/web dependencies, generates local accounts and starts PostgreSQL, FastAPI, Dagster and the UI. Open **http://127.0.0.1:24173**. First-run dependency downloads require internet; the recommended XLSX demo makes no model/provider calls. The local runtime uses macOS Seatbelt; Windows/Linux startup and private hosting are not delivered in this POC.

View the passwords generated for your own installation:

```sh
npm run demo:accounts
```

| Username | Role | What to demonstrate |
| --- | --- | --- |
| `accountant` | Accountant | Upload, confirm checks, inspect records, request evidence and submit corrections. |
| `account_manager` | Account manager | Coordinate requests, explicitly share evidence, inspect changes and independently approve. |
| `fund_manager` | Fund manager | Respond only to assigned fund-level requests and shared evidence. |
| `investor` | Investor | Respond only to a relevant request released by the account manager. |

Each is a separate account with a separate password; there is no role chooser. Passwords live in the owner-only `.local/dev-runtime/.env`, not this repository. `demo:accounts` prints them only to your local terminal. For a custom runtime, pass its explicit private environment file: `npm run demo:accounts -- /path/to/runtime/.env`. The two external-party accounts start with no shared work; an empty Requests screen is expected until they are explicitly included. Assignment alone does not grant document access. Anyone who prepared or changed the selected scope cannot approve it.

Status: `uv run --project apps/api python scripts/local_runtime.py status`. Stop: `uv run --project apps/api python scripts/local_runtime.py down`. Restarting retains accounts and saved work. For ports, recovery and PDF configuration, see [local runtime setup](docs/engineering/local-runtime.md).

## Which supplied workbooks to use

Unzip the organiser's **Ylookup Hackathon Datasets (1).zip** locally. The dataset files are distributed separately and are not included in Git.

| Priority | File inside the dataset | Purpose |
| --- | --- | --- |
| **Main demo** | `02-investor-level-gl-to-loader/source/Investor-Level GL - Q2 activity - all entities (anonymised).xlsx` | Real investor-level activity; 33,902 GL data records for the selected entity-reference check. |
| **Upload with it** | `02-investor-level-gl-to-loader/output/Tranche 1 - reference and verified loader v4c (anonymised).xlsx` | Reference lists, mappings, Mapping Gaps and movement reconciliation across 14 sheets. “Verified” in the filename is not an approval by CloseGraph. |
| Optional scale test | `02-investor-level-gl-to-loader/source/Phase I loader - sample (anonymised).xlsx` | 94,454 data records in a single large loader; use for loading, coverage and preview, not an inferred end-to-end transformation. |
| Optional separate workflow | `01-bank-statements-to-journal-entries/workbook/Bank statement to journal entries - working file (anonymised).xlsx` | Bank staging and reference sheets. The accompanying PDFs need configured extraction; they are not necessary for the private-market workbook demo. |

Do not upload interview transcripts as accounting evidence. Begin with the **two main workbooks**, not the whole ZIP or every file. The supplied files have previously passed complete extraction checks; the [acceptance record](docs/verification/fund-review-acceptance.md) distinguishes actual results from unresolved accounting interpretation.

## Five-minute UI demo

1. **Accountant → New review.** Upload the two main workbooks, name the review and click **Prepare review brief**. During preparation, show the real document count. A prepared review can be reopened from **Recent work** to avoid spending the presentation on ingestion.
2. **Choose checks for this pack → Add a check.** Select **Every value has a reference mapping**. Source: **LE Mapping**, **Legal Entity** (header is row 2). Reference: **Entity Listing**, **Entity**. Inspect the preview, confirm the scope and choose **Save and check**. The supplied originals previously yielded **15 missing values affecting 15 of 84 mapping records**. These are gaps against the selected list, not automatically accounting errors.
3. **Open a difference → View affected records / See complete source record.** Show the exact workbook, sheet and row. Download the full exception CSV. Optionally choose **Review selected checks → Add a check** and compare **Investor-Level GL → Legal Entity** to **Entity Listing → Entity**: the supplied originals yielded **10 missing entity values affecting 4,450 of 33,902 GL records**. Each entity has its own finding; the 4,450 records are spread across those findings.
4. **Ask someone to resolve this → Requests.** Give the account manager a specific question: “Confirm whether this entity belongs in this reporting scope and provide the approved mapping or revised reference list.” Open the request, its evidence and activity. Acknowledging or replying must leave a system discrepancy open until reevaluation passes.
5. **Documents / History → Download brief.** Show original-file access, version submitter and changes. Download a working brief with unresolved questions visible. For the correction-to-approval sequence, follow the isolated, explicitly labelled rehearsal in [the detailed walkthrough](docs/judge-demo.md); do not invent a mapping merely to turn the screen green.

Lead with one useful question and one source record. Keep the accountant and account manager central. Show fund manager/investor access only if a specific request has been set up for them. Each check needs explicit meaning and scope; uploading alone is not a conclusion.

## What is working, and what is not claimed

- **Working:** native CSV/XLSX extraction; explicit required-value, uniqueness, reference and grouped-total checks; paginated evidence and complete affected-record CSVs; corrections and uploaded revisions; scoped in-app requests; quiet history; independent approval tied to exact versions; HTML review briefs.
- **Accuracy boundary:** native spreadsheet parsing and deterministic checks use no LLM. Decimal comparisons use explicit scope and zero monetary tolerance by default. Ambiguity, duplicate reference keys, missing evidence and unverified selected formula caches require input. Group totals cannot establish that every underlying transaction is right.
- **PDF boundary:** Reducto is AI-assisted. Captured replay is labelled. The fresh local workbook demo needs neither a paid API key nor provider calls. Previous real-PDF acceptance reused audited captures; it is not a blanket live-provider accuracy claim.
- **Not delivered:** universal GL-to-loader conversion, arbitrary Excel recalculation, inferred LPA/fee/NAV rules, autonomous financial approval, live Excel collaboration, external notifications, production identity management or regulatory certification.
- **Validation:** [the current demo acceptance](docs/verification/judge-demo-acceptance.md) records 106 web tests, the animated-browser check and the actual workbook rehearsal. No measured customer time saving, customer adoption or human usability acceptance is asserted.

Batman appears beside processing status and makes one brief visit per minute, rotating four animations. The small corner button pauses/resumes visits. Hidden tabs pause the schedule; reduced-motion settings keep the loader static and disable visits. It does not change processing results or represent progress.

## Product-track framing and submission

The organiser's product-track slides allocate **25% each to problem identification, product, UI and code review**. Show the interview pain, one completed evidence/request workflow, a readable source-linked screen and the actual acceptance/architecture evidence. See [the detailed demo and rehearsal checklist](docs/judge-demo.md), [fund reporting workflow](docs/fund-reporting-review.md), [technical acceptance](docs/verification/fund-review-acceptance.md) and [architecture](docs/product-architecture.md).

Submission handoff still needs a **3–5 minute recorded demo**, the organiser's submission form, and repository access that meets the organiser's public-repository requirement. This change does not make the repository public. Private datasets, credentials and interview documents must remain outside the repository. Hosting is optional in the judging materials and is not needed for this local demonstration.

## Existing Collections infrastructure

The earlier Collections workspace provides **Overview, Documents, Tasks, Review changes and Outputs** behind the current guided review journey. Edit workbooks in Excel, upload a new version against the existing document, compare saved changes, and route evidence requests to explicit owners. Account managers configure required checks and independently approve exact outputs. See [evidence-led collaboration](docs/engineering/evidence-collaboration.md).

The underlying collection services accept varied CSV/XLSX layouts and configured Reducto PDF extraction. Review source-linked tables, resolve errors, select headers and accept the exact input version. Reusable versioned recipes define mappings, joins, Decimal calculations, classification, allocation, reshaping and required checks. An independent account manager inspects exact draft exports before those bytes can be released.

See the [collection workflow and limits](docs/engineering/collections-workflow.md), [recipe reference](docs/engineering/collection-recipes.md), and [collection verification](docs/verification/collections-acceptance.md). PDF extraction is AI-assisted and requires review; confidence is not proof of correctness. Native spreadsheet extraction and transformations do not use an LLM. The direct collections implementation leaves OpenSpec unchanged, as requested.

## Existing reporting packs

The use-case-1 MVP is implemented and has passed automated technical acceptance. The [acceptance evidence](docs/verification/mvp-acceptance.md) records actual commands, scenario coverage, artifact identities and coverage limits. It is the completion record; a successful pipeline alone does not establish financial correctness.

The native workflow supports declared CSV/XLSX layouts, explicit entity/period/currency context, an approved fictional fee rule, deterministic Decimal reconciliations and one value-only XLSX output template. PDF evidence uses Reducto observations with original-page citations. Disabled providers and unsupported financial mappings remain visible blockers. Captured replay is explicitly distinguished from the separately executed synthetic live-provider test.

React/TypeScript provides source-to-value review, corrections, check explanations, audit history and observed review activity. FastAPI and PostgreSQL own scoped evidence, immutable versions, decisions and publication. Dagster executes extraction, calculation and checks; jobs finish before independent review begins. Original evidence and failed checks remain inspectable after correction.

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

The repository contains labelled synthetic inputs. Private datasets, interview PDFs, LP details and provider credentials remain outside Git. Supported mappings and accounting treatment must be explicit; universal document accuracy, general spreadsheet recalculation, live Ylookup integration, production IAM/compliance and autonomous accounting are not claimed.

Collections now includes scoped missing-evidence requests, owners, deadlines and deduplicated in-app escalation. External delivery and live source connectors remain outside this version. This build does not deploy production services, provision paid infrastructure, distribute investor reports or post accounting transactions.
