# Fund reporting review: automated acceptance

Date: 6 September 2026. Scope: local private-markets reporting review POC, issues #72–#74.

## Decision and limits

The local workflow is technically accepted for explicit required-value, uniqueness, reference-list and grouped-total checks, evidence inspection, correction/revision, scoped requests, exact-version independent review and a separate HTML brief. Existing Collections data and advanced workflows remain available.

This is not customer validation or approval of fund accounts. No independently approved full GL-to-loader, NAV, fee, valuation or LPA answer was supplied. Whole-pack financial verification remains false. Suggested relationships require confirmation of columns, meaning, fund and period. A file or sheet called “verified” supplies no authority.

## Automated checks

- Full API suite: 572 passed, 2 opt-in provider tests skipped (95.44 seconds).
- Affected engine, review journey and evidence-collaboration tests after final service fixes: 43 passed (20.28 seconds).
- Final pure-engine suite after suggestion-identity fix: 23 passed.
- Final web suite: 75 passed across 16 files; TypeScript and production build passed.
- Two real-file browser workflows: 2 passed (1.4 minutes), with screenshots and downloaded briefs inspected.

The two skips require an opt-in live-provider receipt/capture location. No new paid provider call was made. Previously captured provider responses are explicitly replayed, never labelled as a fresh live extraction.

Service regressions cover concurrent/retried submissions, unchanged-result approval preservation, changed-header interpretation, changed/withdrawn checks remaining unresolved, removed total groups, blocking concerns invalidating approval, exact-version independent review, scoped request access and investor release. Existing collaboration tests cover durable notices, deduplication and deadline behavior. A system finding cannot be resolved by acknowledging it or merely uploading evidence.

## Supplied workbooks and independent comparisons

All four supplied XLSX files were parsed without row/cell truncation: 161,246 stored rows, 4,553,167 cells and 33 extracted tables across 32 sheets. Stored rows include headers; the browser's data-row count excludes selected headers. Individual extraction times ranged from about 1.6 to 22.4 seconds on this machine; these are observed test times, not service guarantees.

Independent openpyxl reads established the selected comparisons separately from product logic:

- Legal-entity mapping against the selected entity listing: 15 distinct values absent across 15 of 84 records.
- GL legal entities against that listing: 10 distinct values absent across 4,450 of 33,902 GL records.
- Investor-name mapping: duplicate reference names correctly required a scoped key, rather than silently matching.
- Movement comparison: 52 rows lacked complete entity/account scope. The all-row comparison stayed blocked. A separately documented test scope excluded those exact rows for the offsetting-error experiment; the original files were not altered or hidden.

These are exact selected-list gaps, not proof of incorrect accounting. A different intended reference scope or approved alias mapping can change the interpretation.

Seven adversarial experiments used copies of real extracted data: reordered records, duplicate keys, a changed entity identifier, a repeated header, incomplete coverage, offsetting amount changes that preserved the grand total, and unverified formula caches. The grouped comparison detected both offsetting changes. Decimal scientific notation from real Excel residuals is preserved exactly. Most experiments mutated extracted copies; the browser revision below separately exercised genuine modified XLSX bytes.

## Real browser correction and Excel revision

An isolated test database held the actual GL, reference workbook and large loader: three documents, 17 tables and 151,335 displayed data rows. Upload/extraction ran successfully before the resumed browser acceptance; resuming avoided another expensive large-file upload.

An explicitly configured required-value check found two blank Approval cells in the supplied Mapping Gaps sheet. This is a field-completeness check, not legal or financial approval. The browser opened the exact cited record, entered an isolated test correction with a reason and observed the count fall to one. It verified history, original-file byte identity, a working HTML download and refresh persistence.

A genuine Excel revision was then uploaded. Its independent mutation ledger changed only Mapping Gaps!G2 and G3 to a clearly labelled isolated-test value; all other ZIP parts were byte-identical. The existing check rebound to the compatible revision, passed and appeared as fixed in history. Both downloaded original and revised files matched their respective input hashes. Unrelated uncertainties remained open, and the pack was not labelled financially verified.

This run found and fixed three real UI integration issues: empty result-filter parameters, an inaccessible check-type label, and correction controls becoming active before their cited source row loaded.

## Actual PDF evidence

Seven supplied bank PDFs were checked using captured provider replay: 16 pages, 100 transactions, 71 raw tables, 345 raw rows and 1,562 valid block locators. Values matched previously independently audited captures. Explicit bank-account reference membership passed for the 100 staging rows across seven accounts. Corrupt receipts and incomplete coverage failed closed; unconfirmed PDF content remained Needs your input.

This reused the previous source audit rather than repeating every visual cell check. One previously known narrative-punctuation difference remains; citations are block-level where the parser provides blocks. This does not prove journal correctness or guarantee every PDF cell is accurate.

## Evidence handling

Private source files, mutation ledgers, source values, captures, screenshots and HTML exports remain outside tracked Git files. Test collections are separate from the user's working collections. Before/after branches and three focused user-authored commits preserve the implementation history. No OpenSpec files, hosting, paid infrastructure or external notifications were added.
