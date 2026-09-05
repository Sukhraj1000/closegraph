# Product brief: verify the correction, not just the upload

## One job

When an accountant corrects a reporting-pack figure, let the reviewer see its evidence, the dependent outputs and the checks proving the supported correction was carried through, without reconstructing the whole pack again.

Fit sentence: CloseGraph extends the reporting work produced by Ylookup and existing administrators with cross-version correction verification, so reviewers can make a source-backed decision about the revised pack.

## Users and workflow

- **Administrator/accountant:** uploads original sources and packs, runs supported extraction/reconciliation tools, records source-backed corrections and approved treatment, and inspects recomputed outputs and failed checks.
- **Independent reviewer:** approves the exact revised snapshot or requests further revision, with source and check evidence.
- **Fund manager:** sees readiness, changes and decisions needing their attention. The product must not require them to maintain a new processing platform.

Before: a draft arrives; the reviewer searches original documents; the accountant corrects it; another draft arrives; everyone rechecks because change scope and treatment are unclear.

After: original sources become traceable facts; explicit rules compute reconciliations; evidence and parser signals prioritise review; a correction creates a new version and recomputes affected outputs; the reviewer approves the exact supported snapshot. A failed correction remains open rather than producing another opaque issue memo.

## Evidence versus interpretation

### User's own interview notes (provided in conversation)

Observed themes: calculator-based tie-outs, repeated human cleanup, locating contributions/equity/fee evidence, outsourced parties working across formats, keeping reporting templates, knowing exactly what changed, long missing-information chains, and auditability.

These notes support the problems, not a quantitative savings claim or validated willingness to pay. Different interviewees may have different bottlenecks.

### Supplied anonymised NAV interview

Source: `03-call-transcripts/call-1-nav-workflow-review.pdf` in the separate local research workspace.

- The manager describes repeated correction rounds and a side-letter fee treatment repeatedly mishandled.
- "The issue is not data intake, it is processing. Understanding how it is supposed to work and then making it work that way."
- "What I care about is the count of turns. That is the drag on my time."
- This manager says valuations are quick using a standard template. Do not generalise the user's other notes about slow valuation packs to every fund manager.
- The recording is condensed and partial; vendor statements are not independent customer evidence.

Inference: a correction must reach a checked, useful revised output. A dashboard, file version history or notification system alone does not satisfy this job. Tracking stale approvals is useful only if it reduces the actual correction/review burden.

### Dataset limits

The separate inspection found value-only workbooks and source/template/output stages, not historical NAV pack revisions with formulas and approvals. Treat those supplied files as authorised local adapter/evaluation material, not as the architecture's schema or perfect ground truth.

The MVP demo should create clearly labelled synthetic pack versions, review events and a fictional authorised fee treatment. Do not present these as actual investor agreements, accountant approvals or Ylookup responses. No private sources are copied by this project setup.

## Scope decision

Use case 1 is the active MVP. Use case 2 is the next phase after the acceptance gate, not a parallel implementation lane. A missing-evidence blocker is necessary in the MVP; automated requests, owners/deadlines and escalation are phase 2.

## Assurance and sponsor boundaries

- Preserve evidence and original outputs; no universal source-truth claim.
- Processor output can be wrong. Required deterministic checks must execute against the selected snapshot; imported `passed` flags are not authoritative.
- An authorised person establishes accounting/legal treatment; the application checks a narrowly declared contract, not arbitrary financial correctness.
- Dependencies must be explicit and evidenced. Unknown dependencies prevent selective "unaffected" claims.
- Build actual source-backed extraction and reconciliation tools; do not prohibit them merely because Ylookup also processes documents. Ylookup/export inputs remain complementary interfaces, with live access and sponsor overlap to verify.
- Keep tools independently testable; Dagster coordinates their execution rather than supplies financial meaning.
- Reducto is an external AI-backed parser. Require data-use approval for uploads; record its actual response and never fabricate confidence or a live integration.
- Triage uses hard gates before parser confidence/agreement. Compare entity, metric, period, currency, scale and value; agreement can be correlated. A required failed/unknown check blocks release even if confidence is high.
- Keep observations, validation and approval separate. A reviewer cannot convert a failed reconciliation into a pass.
- Native CSV/XLSX supports a no-egress vertical demo; a bounded manual export adapter avoids dependency on an unconfirmed Ylookup API.

## Measures and validation questions

Measure review actions, reopened output scope, unresolved issues, elapsed supported processing time and correction cycles on recorded cases. Compare against a defined manual baseline only when actually observed; never convert fixture automation into an invented customer savings percentage.

Before a pilot, confirm with an administrator/reviewer:
1. Does the change summary and evidence replace meaningful rechecking?
2. Can a declared dependency manifest be produced affordably for one real pack?
3. Which calculations/treatments are authoritative and who may approve them?
4. Which existing Ylookup/export interface can supply versions and evidence?
5. Does the existing sponsor product already cover the proposed cross-version loop?

## Local research references (not repository dependencies)

Workspace: `/Users/sukhrajkalon/.hermes/workspaces/ylookup-dataset-review/`

- `analysis/transcript-findings.md`
- `Ylookup Hackathon Datasets/03-call-transcripts/call-1-nav-workflow-review.pdf`
- `MVP_CONTEXT.md`
- `CLOSEGRAPH_ARCHITECTURE.md` (historical broader design; use this project's current design for extraction scope, triage and phase sequencing)

Original strategy PDFs remain under `/Users/sukhrajkalon/Downloads/`. The current project is self-contained enough to implement without distributing these sources. The internal commercial call is not public demo material.
