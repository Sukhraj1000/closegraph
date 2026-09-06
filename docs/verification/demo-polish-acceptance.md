# Reporting demo polish acceptance — 6 September 2026

Scope: preserve the current private-market reporting review product; make complete exceptions accessible, clarify selected review scope and test a large independent financial dataset. Issues #76, #77 and #78. No OpenSpec changes, paid extraction calls, hosting or private datasets in Git.

## Independent large-file evidence

The complete public SEC 2010 Q2 Financial Statement Data Sets NUM and SUB files were downloaded from the [official archive](https://www.sec.gov/files/dera/data/financial-statement-data-sets/2010q2.zip). The source is described on the [SEC dataset page](https://www.sec.gov/data-research/sec-markets-data/financial-statement-data-sets). Original TSV fields were converted to CSV without changing values. This is historical corporate reporting data, not private-fund accounting ground truth.

- NUM: 136,044 data records, 10 fields, 1,360,450 cells including its header.
- SUB: 522 filing records, 36 fields, 18,828 cells including its header.
- Independent, local source comparison checks every extracted raw field and row order, rather than using the product's own expected result.
- Adversarial copies reverse rows and columns, rename headings, corrupt 63 references, blank 41 selected amount cells (one was already blank), and repeat a header deep into the large file. A separate mutation ledger records source rows, before/after values and hashes. Product rules contain no dataset-specific answers.

All raw fields matched the independent reader across the original files and three variants. Native CSV extraction took approximately 2.4 seconds for each 136,044-record file on this machine; this is extraction-only timing, not an end-to-end upload SLA.

| Input | Missing-reference records | Blank value records | Interpretation |
|---|---:|---:|---|
| Original NUM | 0 | 600 | Membership in the selected filing register |
| Reordered and deliberately modified | 63 | 640 | Exactly the ledger's reference changes and newly blank cells |
| Restored revision, reordered layout retained | 0 | 600 | Original values restored |
| Header repeated deep into the file | No confirmed comparison | No confirmed comparison | Needs your input; no silent confirmed result |

Blank values are counted under an explicitly selected test rule. These counts are not accusations that SEC filings are incorrect. Every affected record was indexed, including repeated financial values at distinct physical source rows.

This test exposed a genuine ingestion defect: dialect detection sampled an early segment without embedded quotes and disabled standard doubled-quote escaping. Later quoted text could then be corrupted or split into extra fields. The reader now preserves those fields. Comma, semicolon and tab regression cases cover quotes appearing after the sampling window.

## Automated checks

- 94 API, extraction, review, access/session and evidence-collaboration checks passed against isolated PostgreSQL.
- 89 web component tests and the production TypeScript/Vite build passed.
- All full-file source/mutation comparisons passed.
- The large browser journey uses a separate database and original-file directory; it does not write to the user's working collections.

Service coverage includes 50/13 pagination across 63 records, complete CSV export, distinct duplicate headings, formula-prefix escaping for Excel, permission denial, stale-result rejection, legacy sampled-result handling, immutable original downloads and selected-column formula gating. An unselected formula remains a visible unverified note; a selected unverified formula still blocks approval. No check sets whole-financial verification to true.

The final fresh browser run passed in 2.2 minutes: upload both complete files, configure the reference check, inspect 63 affected rows over pages of 50 and 13, download all 63 with distinct source locations, assign a request, correct one source-backed value (63 → 62, request still open), upload the restored revision (62 → 0), observe automatic request resolution, inspect history, sign in as a separate reviewer, approve the exact selected scope and download the reviewed HTML brief. Original-upload bytes matched their SHA-256 after revision; whole-financial verification remained false. The final screenshots were visually inspected.

The browser checks exposed two workflow defects that were repaired: a download audit update unnecessarily closed the finding panel, and uploading a prepared revision used a stale collection version. The upload now refreshes state after file preparation without changing the selected parent or retrying conflicts. Investigation also identified a deadline sensor adding an absent `overdue: false` flag to tasks with no deadline. That no-op write created an unnecessary version and an intermittent upload conflict. No-deadline/future-deadline sweeps now leave unchanged state untouched; real overdue transitions still create exactly one overdue notice and escalation. Earlier failed attempts remain recorded locally.

## Limits and useful demo claim

The useful claim is: locate all exceptions to a confirmed reporting check, trace them to the source, request a specific correction, and show whether the next evidence version fixed the problem. The [demo guide](../demo-guide.md) gives the exact route and expected results.

Prior acceptance used the supplied private GL/loader workbooks; those results are recorded separately in [fund-review acceptance](fund-review-acceptance.md). This pass adds independent public-data scale and field-level accuracy evidence. It does not repeat a live PDF provider evaluation or certify NAV, fees, LP allocations, a final journal or financial statements. Grouped totals still cannot detect offsetting errors inside a group. There has been no uncoached customer usability test or measured time-saving study.
