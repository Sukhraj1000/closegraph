# CloseGraph UI reference

## Authority and source inspection

- [closegraph-wireframe.html](closegraph-wireframe.html) is the byte-for-byte user-approved reference, copied from the read-only `/Users/sukhrajkalon/Documents/Codex/2026-09-05/can-x20/outputs/closegraph-wireframe.html`.
- SHA-256: `4c9950687749aa901df7f5dde5f48d286ef34b189f542187a6c49f528517af88` (85,892 bytes). Full source review and a credential/private-reference pattern scan found no private interview material or provider credentials. The fund, people, financial values, approvals and parser observations are explicitly fictional/synthetic.
- The snapshot retains its original wrapper, scripts and styles. It references public Floating UI and Lucide scripts on unpkg; use an offline/network-blocked viewer if no egress is wanted. Its actions only mutate example state: role switching is not authentication, export preview generates no workbook, and processing is not a live provider integration.
- At the time this source snapshot was reviewed, the financial application and `apps/web/` implementation had not yet been built. That historical finding explains this handoff, but it is no longer the repository's current state: the React/Vite application and Storybook catalogue now exist. See [`ARCHITECTURE.md`](../../ARCHITECTURE.md) for the implemented system and deployment boundaries.
- CloseGraph-specific CSS starts at HTML line 1028; navigation/scenario controls at 1167–1168; check/status logic at 1182–1207; source and correction compositions at 1215–1227; checks/approval at 1229–1239; scenario initialisation at 1243–1248. Generic renderer CSS earlier in the file is not the product theme.

## Shared implementation contract

Use **shadcn/ui with Radix-based interactive primitives and repository-owned source components**, not a separately styled component library or a wholesale copy of the prototype's DOM renderer. Retain semantic native elements for Input, Textarea, Table and Native Select. Proposed ownership: `apps/web/src/components/ui/` for primitives, `apps/web/src/components/closegraph/` for shared compositions, and one shared theme stylesheet under `apps/web/src/styles/`. These are future paths, not files created by this handoff.

Define semantic tokens and typed variants centrally; all pages and Storybook stories consume the same components. No per-page inventions for colours, control dimensions, status styles, focus rings or spacing. Promote a justified new variant into the central catalogue before using it on a page.

| Token / role | CloseGraph value |
| --- | --- |
| Canvas / charcoal | `#171B20` |
| Primary / active lime | `#D5F6A1`; dark label `#17220B` |
| Document paper | `#FBFCF8`; text `#26322C`; muted `#526258` |
| Panel / sidebar | `#20262D` / `#12161A` |
| Text / muted | `#F1F4F2` / `#BEC8C4` |
| Divider / input border | `#404C54` / `#7D8A92` |
| Warning / warning surface | `#F3CF89` / `#30291E` |
| Error / error surface | `#FFBAB2` / `#342321` |
| Focus on dark / paper | `#F1D46B` / `#527C28`; clearly visible, not clipped |
| Typography | System sans; body **16px**, line-height **1.55**; tabular numerals for amounts |
| Control size / corner | Approximately **46px** minimum control height; shared **6px** corner |

Keep the dark workspace and white-paper document contrast. The source has local 5/8/10px radii, 40/44px secondary controls and a tweakable outer shell; preserve those bytes in the reference, but use the approved shared 6px/approximately 46px implementation tokens rather than proliferating exceptions. Textareas grow vertically. The desktop rail is fixed/persistent with numbered navigation (source fixed-width rail: 166px); prevent it from covering content or focus at narrow widths and zoom.

## Component mapping and Storybook catalogue

Catalogue every component below under the CloseGraph theme. Show every variant in default, hover (interactive only), disabled, error/invalid and keyboard `focus-visible` states where meaningful; record **not applicable with a reason** for non-interactive components rather than inventing focusable badges or disabled tables. Include long labels, wrapping and content overflow. Storybook is required implementation work, not delivered here.

| Owned component | Reference mapping / contract | Required state coverage |
| --- | --- | --- |
| Sidebar | `.cf-sidebar`, `.cf-nav`: fixed desktop rail; links `01 Overview`, `02 Correction`, `03 Checks`, `04 Approval`; lime text, left accent and tinted active surface; `aria-current="page"`. Use real links for route navigation. | Active/inactive, unavailable destination with explanation, keyboard focus; workflow blockers are not arbitrary navigation errors. |
| Button | `.cf-primary`, `.cf-secondary`, `.cf-link`: primary lime, outlined secondary, underlined text action. Central `primary`, `outline`, `link` variants. | Each variant: hover, disabled/no activation, focus; pending action and adjacent action-error message without inventing a danger button style. |
| Alert + Button | `.cf-task`: attention panel with left accent, heading, explanation and **one clear next action** when actionable. Central normal/warning/danger tones. A non-actionable blocker explains the next step, not a fake enabled action. | Each tone, no action, disabled action, focused action, processing failure; announce newly arriving urgent errors, not every static panel. |
| Field + Input + Textarea | `.cf-field`, `.cf-error`: persistent visible label, helper and error; `htmlFor`/ID, `aria-describedby`, `aria-invalid`, required semantics. Preserve input and correction reason on failure. | Empty/filled, required, disabled/read-only, invalid amount, missing reason/review note/resolution, keyboard focus including invalid focus. |
| Tabs | `.cf-source-switch`: underlined `Fee rule`, `Capital`, `Original pack`; source IDs `rule`, `capital`, `original`; active lime underline, not pills. Use Radix Tabs semantics and linked panels. | Each selected panel, disabled tab, arrow/Home/End navigation, focus; unavailable source shown explicitly inside its panel. |
| Table | `.cf-table`, `.cf-sheet`: semantic caption/header cells, right-aligned tabular amounts, subtle row dividers, source locators and original/current version headings; retain the source-sheet variant centrally. | Passed/failed/unknown/pending rows, unavailable values as `—` with explanation, long content and overflow. Table itself has no disabled/focus state; any cell actions do. |
| Badge | `.cf-tag`: text **and symbol**; `PASS` → `✓ Passed`, `FAIL` → `× Failed`, `UNKNOWN` → `! Unknown`, `PENDING` → `! Not checked`. Keep pending distinct from unknown even when both use warning colour. | All four central status variants. Non-interactive: disabled/focus not applicable; failure is a check outcome, not an input error. |
| Accordion | `.cf-details`: processing/check/source details and version/review history, including saved historical check results. Use Radix Accordion `type="multiple"`; several sections can stay open. | Closed/open/multiple-open, disabled trigger, focus and keyboard operation; nested historical checks and error content remain readable. |
| Checkbox | `.cf-checkbox`: approval attestation; entire associated label is clickable, with visible focus and readable version-specific text. | Unchecked/checked/indeterminate, disabled, invalid required attestation, focus; approval remains disabled until requirements are met. |
| Native Select | Scenario/person selectors in `.cf-demo`: semantic `<select>` with persistent label, same approximately 46px size, 6px corner, padding/border/focus treatment as inputs. Do not substitute a custom menu. | Placeholder/selected, long option, disabled, invalid, focus and native keyboard selection. Demo role selection stays story-only. |
| DocumentPreview | Reusable `.cf-paper` composition for source and candidate pack: white-paper surface, structured label/value rows, document identity/context/locator, prominent total and optional source-sheet Table. | Fee rule/capital/original/candidate, long values, missing/unavailable/stale evidence; no fabricated total. Static paper is not focusable; its source actions have disabled/error/focus coverage. |
| ApprovalPanel | Reusable composition from `review()`: exact-version heading, DocumentPreview alongside review details, Field/Textarea, full-label Checkbox, primary Button, status/history and gated export preview. | Preparer handoff, reviewer awaiting attestation, missing note, blocked/unresolved/stale, submitting/disabled, approved exact version and historical-only approval; focus after validation/action. |

## Eight workflow stories — exact source scenarios

Use these exact selector values and display names from `[data-scenario]`, in source order, as the eight assembled Storybook scenarios. Keep all fixture values and roles labelled synthetic. Additional component-state stories do not replace any scenario.

| Source value | Exact source scenario name | Behaviour to preserve and test |
| --- | --- | --- |
| `correction` | Fee correction — start here | Review original $75,000 against supported $60,000; saving creates a version with the capital-statement check still failed; repair, independent approval and export preview follow. Failed attempts remain in history. |
| `missing` | Missing fee agreement | Missing source yields unknown checks and blocks correction/approval; adding the example agreement does not itself fix the fee mismatch. |
| `disagreement` | Document readers disagree | Both original readings remain visible; passing financial checks do not settle the disagreement. Reviewer records evidence-backed resolution before separate approval. |
| `dependency` | Unknown effect on a statement | Unknown capital-statement dependency blocks approval; never infer that the output is unaffected. |
| `provider` | PDF processing unavailable | Required PDF unavailable; checks are unknown/not evaluated, not passing fixture replacements; approval stays blocked. |
| `ready` | Ready for independent review | Version 4 is eligible, not already approved; reviewer must inspect, attest and provide a note before approval/export preview. |
| `stale` | Source changed after approval | Version 4 approval is historical only; version 5 has pending/out-of-date checks. Recheck then require new independent approval. |
| `template` | Unsupported workbook feature | Financial checks can pass while an unsupported macro prevents equivalent output and blocks approval. |

## Assembled accessibility and workflow gates

These are future acceptance checks, not claims that the standalone prototype or an unbuilt application passes them:

- Run Storybook interaction/a11y checks for the component matrix and all eight stories, plus keyboard-only and screen-reader checks through Overview → Correction → Checks → Approval. Verify landmarks, heading order, skip-to-task behaviour, logical focus order, visible/unobscured focus and useful focus placement after navigation, validation and rerendering.
- Test Radix Tabs arrow/Home/End operation, independent multiple-open accordions, native select keyboard behaviour and the full clickable checkbox label. Check accessible names, selected/expanded/checked/disabled state announcements, helper/error associations and focus on the first invalid field. Announce processing/check/version changes without duplicate or overwhelming live output.
- Check text/control/focus contrast on both charcoal and paper, colour-independent status meaning, 200% zoom and narrow-width reflow; keep all actions reachable and table overflow contained and keyboard accessible. Honour reduced motion. Automated a11y scans alone are not a workflow pass.
- Exercise invalid amounts, empty reasons/notes, disabled approval, missing/unavailable evidence, failed repair, unresolved disagreement and stale approval. Verify no keyboard or pointer action bypasses a gate; preserve entered text and original observations/checks/history. Keep processing, check outcome, review routing, approval and freshness separate.
- The source uses grouped pressed buttons rather than true tabs, and resolution/review-note errors lack the full invalid/error associations used by the amount field. Correct these in owned components and test the assembled workflow; do not mutate the reference to conceal prototype limitations.
- UI gates do not establish authorisation: real implementation must enforce independent, exact-snapshot approval and release server-side. Follow the implemented [reviewer-workspace spec](../../openspec/specs/reviewer-workspace/spec.md) and [MVP acceptance gate](../acceptance.md). Storybook/prototype success cannot substitute for the real API, stored-output and permission checks.
