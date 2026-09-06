# Local bank reconciliation

The main journey is New reconciliation → upload statements and a journal → Reconcile → inspect results → resolve or request evidence → download. Recent work resumes saved runs. Requests opens the assigned request directly. Existing Collections storage and permissions remain in place.

## Use the demo

1. Upload the bank PDFs together and the working workbook. Processing stages and document counts are real; refreshing does not cancel a job.
2. Choose the journal transaction table from the workbook. Other sheets remain supporting evidence. Confirm cash-entry selection and any ambiguous account, currency, number, date or reference interpretation using the actual previews. A full journal must be filtered to its cash legs.
3. Inspect Matched, Differences, Missing and Needs your input. Matching confirms only the selected reconciliation rule, not accounting classification. Duplicate/composite ambiguity stays unresolved.
4. Open an item to inspect both source records. Correct extraction in Documents, upload a new Excel version, change an interpretation, or assign a specific request. Reconciliation reruns after relevant changes.
5. Download a working result at any point once processing completes. It is labelled with unresolved findings. Reviewed release requires an independent account manager and unchanged source/rule/output dependencies.

## Useful records and alerts

Item activity retains evidence, reasons and request transitions. History retains uploaded revisions, mapping changes, evaluations, decisions and downloads. Operational diagnostics remain restricted. Upload submitter is not represented as the original spreadsheet editor.

Notifications are durable, deduplicated and scoped to affected participants. Assignment or material change can notify; each unmatched row does not. Evidence receipt and reading a notice cannot resolve a discrepancy. System findings resolve through reevaluation. Deadline processing sends one overdue notice and one account-manager escalation per cycle. Investors require explicit release and do not gain workbook access through assignment.

## Accuracy and limits

The private acceptance corpus uses the supplied bank PDFs and actual journal cash entries with explicitly established fixture mappings. At zero tolerance, all 100 bank transactions and 100 journal cash entries are retained: 77 unique matches, 4 unmatched records (two pairs with tiny saved-number differences), and 8 ambiguous groups containing 21 transactions. Group counts must not be read as transaction counts. An explicitly configured precision tolerance can change results; no tolerance is silently added.

PDF acceptance replays hash-bound captured responses from the previous live extraction and independent source audit. The interface labels these replays. This does not establish current provider reliability on other PDFs. Malformed or mismatched receipts fail closed. Previously measured large-workbook extraction fidelity is reused; accounting mappings across all those workbooks are not established by extraction fidelity.

Fifteen real-data mutation checks passed, including offsetting errors that preserve totals, duplicates, currency changes, broken reference mappings, ambiguous formats, repeated/renamed headers and stale formula caches. Real-data mutations test matching safety without embedding expected answers in product logic. Service regression tests additionally cover correction propagation, independent approval, original preservation, concurrency/idempotency, request permissions, and notification behaviour. Small service fixtures do not substitute for real-file accuracy evidence.

## Role walkthrough criteria

- Accountant: upload, identify the relevant table, inspect both sides, correct and rerun without losing evidence.
- Account manager: see changes and unresolved items; independently review exact current versions.
- Fund manager: receive a specific justified request, respond with permitted evidence, and retain pending verification.
- Investor: receive only explicitly released requests with evidence access separately controlled.

Engineering tests are not first-time user validation. An uncoached accountant/account-manager session remains a release gate before calling this a validated customer experience. Fund/investor request wording also needs real-user feedback. Private hosting is deliberately deferred.

## Verified local build

The full API run passed 537 tests (two conditional skips); after integration fixes, 78 affected API tests passed. The web suite passed 65 tests and the production build passed. Two real-file browser workflows passed: upload, interpretation, inspection and working download; then a real journal amount correction, automatic reevaluation, exact restoration and download. The restored result again contains 77 matches, 4 unmatched records and 8 ambiguous groups. These are automated checks, not human acceptance.
