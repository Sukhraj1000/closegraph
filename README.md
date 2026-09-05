# CloseGraph

A correction-and-verification layer for private-fund reporting: **what changed, what does it affect, and is the corrected pack ready for approval?**

## Current engineering authorization

The user authorized a Codex-led local MVP build with automatic engineering decisions, review, repair and merging, and no final human engineering sign-off. See [standing authorization](docs/engineering/standing-authorization.md); it supersedes the historical setup/activation restrictions below. Financial approvals within the application still follow the product specification. This authorization does not itself claim the new runner is implemented.

## Status

The financial application remains a specification workspace: OpenSpec is initialised, but no financial UI/API or live Ylookup integration is implemented. All 40 product implementation tasks remain unchecked. Repository-local engineering automation is a separate deliverable under `automation/`, built for paused operation; see its [architecture](docs/engineering/architecture.md), [activation gates](docs/engineering/activation.md) and [verification report](docs/verification/engineering-automation.md). No production security/compliance claim is made.

- **MVP / use case 1:** verify a corrected reporting pack, from source-backed correction through affected-output checks to exact-version independent approval and download.
- **Next / use case 2:** missing-evidence requests, ownership and deadline escalation, only after the MVP acceptance gate passes.
- **Later:** separately justified integrations and features; no automatic scope expansion.

## Start here

1. [Product brief and interview grounding](docs/product-brief.md)
2. [Phase sequence and acceptance gate](docs/roadmap.md)
3. [Active OpenSpec proposal](openspec/changes/verify-corrected-reporting-pack/proposal.md)
4. [Technical design](openspec/changes/verify-corrected-reporting-pack/design.md)
5. [Implementation tasks](openspec/changes/verify-corrected-reporting-pack/tasks.md)
6. [Acceptance scenarios](docs/acceptance.md)

The approved stack is React/TypeScript, FastAPI/Pydantic, Dagster, Polars/openpyxl, Pandera and PostgreSQL. Reducto is the PDF adapter; Docling is an optional evaluated second pass. The application owns review, financial validity and publication; Dagster runs the Python extraction/transformation/reconciliation tools. No parallel queue platform is required.

## OpenSpec tooling

Requires Node.js >=20.19.0. OpenSpec is pinned to 1.10.0 as a development dependency, not an application runtime service.

```sh
cd /Users/sukhrajkalon/projects/closegraph
npm ci
npm run spec:check
npm run spec:list
npx --no-install openspec instructions apply --change verify-corrected-reporting-pack --json
```

The final command prints implementation guidance; it does not build the application. `spec:check` validates specification structure and reports artifact readiness, not financial correctness or working software.

Shared OpenSpec agent skills are in `.agents/skills/`. Read `AGENTS.md` before making changes. After review, ask the coding agent to apply `verify-corrected-reporting-pack`. Do not archive the change until the application and acceptance evidence exist. The main `openspec/specs/` directory is intentionally empty because there is no implemented baseline yet.

## Product boundary

CloseGraph performs source-backed extraction, deterministic transformations and financial reconciliations for supported workflows. It can also consume Ylookup/accountant exports without assuming an available live API. Authorised people establish accounting/legal treatment; probabilistic parsers do not supply financial authority.

Review uses evidence/financial hard gates, parser confidence and contextual parser agreement. BLOCKED overrides NEEDS_REVIEW, which overrides READY_FOR_QUICK_REVIEW. Approval is a separate exact-version decision; it never erases an original extraction or converts a failed check into a pass. Corrections trigger recomputation and renewed review.

External PDF processing requires approved data scope and configured credentials. A captured response tests adapter behaviour, not a live integration. The default no-egress test path uses native CSV/XLSX extraction; missing PDF credentials remain visibly unavailable.

The MVP does not interpret arbitrary LPAs, calculate fund valuations autonomously, replace the accountant, or guarantee universal accuracy. A ready status means the declared checks passed for the specified evidence, policy and observed versions.

## Data and repository safety

Private datasets and interview PDFs stay outside this repository. The product brief references the local research workspace; public/demo fixtures must be explicitly synthetic or separately cleared for use. Never include `.env` files, raw LP details or internal commercial calls in a commit.

The repository is private at https://github.com/Sukhraj1000/closegraph. Specification and engineering-tool publication were explicitly authorised. No deployment, external service provisioning, live agent execution or accounting-system writes are part of this setup. Engineering dispatch and automatic merging remain disabled.

## Engineering workflow

- [Architecture and ways of working](docs/engineering/architecture.md)
- [Independent epic ownership](docs/engineering/epics.md)
- [Published epic/task issues](docs/engineering/github-issues.json)
- [Activation and agent adapter contract](docs/engineering/activation.md)
- [Actual automation verification evidence](docs/verification/engineering-automation.md)

The intended engineering/reviewer loops use native Hermes cron and full macOS-sandboxed clones; the paused draft jobs cannot yet dispatch real coding/review adapters. The reviewer must check the exact head/base revision and relevant tests. Engineers add integration/E2E coverage where needed, and the user is the human integrator. There is no autonomous QA bot and no hosted CI configuration in this pass.

From the repository root, use Python 3.12:

```sh
python3.12 -m unittest discover -s automation/tests -v
python3.12 -m automation.cron_tools --help
python3.12 -m automation.publish_issues  # catalogue validation only; no writes
```

The protected `AGENTS.md` retains the earlier product-specification setup wording: an attempted update was not approved. The engineering architecture documents this later, explicitly authorised paused tooling scope without changing the financial product scope.

## Project structure

```text
.agents/skills/                         generated OpenSpec workflows
AGENTS.md                              project boundaries and working instructions
docs/                                  product, roadmap and acceptance criteria
openspec/config.yaml                   project context and artifact rules
openspec/changes/verify-corrected-reporting-pack/
  proposal.md                          why and scope
  design.md                            proposed architecture
  tasks.md                             unchecked implementation checklist
  specs/*/spec.md                      proposed behavioural requirements
openspec/specs/                         empty until implementation/archive
package.json + package-lock.json       reproducible specification tooling
```

Proposed application paths in the design/tasks do not exist yet. The earlier research architecture is historical context; this project's design takes precedence, especially on the Dagster processing pipeline, permitted extraction/reconciliation tools and deferral of use case 2.

OpenSpec upstream: https://github.com/Fission-AI/openspec
