# Collections technical verification — 2026-09-05

This records automated engineering verification of the directly authorized collections implementation. It is not customer validation or financial approval of the supplied workbooks. OpenSpec was left unchanged as requested.

## Verified behavior

- General CSV/XLSX extraction and configured Reducto PDF extraction produce dynamic review datasets with original bytes, raw values and source coordinates.
- Explicit human corrections, header choices, acceptance, immutable revisions and recorded reasons precede transformation. Provider/truncation errors cannot be dismissed; repaired findings reopen if invalidated.
- Deterministic versioned recipes use Decimal arithmetic, explicit joins/mappings and required checks. No LLM supplies accounting decisions or generated execution code.
- Scoped PostgreSQL transactions and Dagster requests handle concurrent writes, revoked grants, retries, stale results and exact candidate approval. Database triggers protect revision history.
- The browser journey uploads two unfamiliar CSVs, confirms their headers, accepts both versions, joins a reference table, doubles values and requires a total of 40.60. A separate reviewer downloads the draft, approves the snapshot and physically downloads byte-identical released CSV. The two rows are A / 12.20 / North / 24.40 and B / 8.10 / South / 16.20.

## Actual checks

| Check | Result |
|---|---|
| Full API suite against real PostgreSQL | 439 passed, 2 conditional historical-capture tests skipped initially; 71.85 seconds |
| Those two conditional capture tests with the retained actual provider receipt configured | 2 passed; 0.92 seconds |
| Web unit suite | 46 passed |
| TypeScript and production Vite build | Passed |
| Real API / Dagster / Chromium collection journey | 1 passed; 50.2 seconds |
| Changed-file whitespace validation | Passed |

Focused runs during repair found and corrected multiline CSV delimiter handling, missing failed-expression lineage, stale integration header assumptions and browser download handling. Final passing evidence supersedes those failures; the failures were not counted as passes. Browser downloads reuse the existing component that checks HTTP errors and then downloads a blob. The isolated development UI was restarted to discard its stale module cache.

## Supplied workbook evaluation

No sample filenames, sheet names, entity IDs, business fields or target cells were added to product logic. The four anonymised XLSX files were processed locally; private PDF files were not sent externally.

| Workbook | Tables | Retained rows | Stored cells | Native extraction seconds |
|---|---:|---:|---:|---:|
| Sample loader | 1 | 94,455 | 2,550,171 | 21.391 |
| Investor-level GL | 2 | 33,994 | 1,458,095 | 11.673 |
| Reference and verified loader | 14 | 22,904 | 463,052 | 3.735 |
| Bank-to-journal working workbook | 16 | 9,893 | 81,849 | 0.921 |

All four returned complete bounded native extraction with zero extraction errors. Counts include raw header rows, which need an explicit review decision. They do not establish accounting accuracy or a completed business mapping. The largest workbook also passed the running API → Dagster → immutable storage flow in 44.34 seconds, retained 94,455 rows, and successfully returned a 100-row page starting at row offset 94,000. Its serialized extraction was approximately 258 MB; pagination bounds the response, while server-side access still loads the stored table.

## Fresh live provider result

A fresh request through the running API, Dagster and the trusted loopback gateway processed only the previously authorized labelled synthetic PDF. It reached NEEDS_REVIEW with four source-linked text blocks in 16.07 seconds; no extracted dataset was auto-accepted.

- Provider job: `6a7e30f0-5e09-47a7-a60a-a2130cea6574`.
- Dagster run: `4892a5f1-adc4-4e54-8e53-d801a957aa8b`.
- Source SHA-256: `4b3b1adfb44bf2b76f2e45dd4a5c8f659ead318d84419331d70b6daa7411ead1`.
- Response SHA-256: `9c06785ddd591e9442fedaa063ef8eb418e86425f66542109e747f37b4a0ed3e`.
- Fixed endpoint: `https://platform.reducto.ai`; request settings: `persist_results=false`, `force_url_result=false`.
- Provider model version was not reported. Confidence remains uncalibrated and citations retain actual block precision.

The configured gateway allows only explicitly authorized source hashes. This test does not authorize private PDFs, establish account residency/retention terms, or demonstrate accuracy on arbitrary PDFs. Reducto remains AI-assisted; human input review and deterministic required checks are the accuracy controls.

## Reproducing and extending

Use the regular API test command with a disposable real PostgreSQL schema via `CLOSEGRAPH_TEST_DATABASE_URL`, `npm --prefix apps/web test`, `npm --prefix apps/web run build`, and the Playwright `collections` project with explicit test accounts and the local runtime. The two optional historical receipt checks require `artifacts/live-reducto` and `CLOSEGRAPH_REDUCTO_LIVE_RECEIPT`; see the retained fixture README. A fresh live test requires the separately configured authorized gateway.

See [workflow and configuration](../engineering/collections-workflow.md) and [recipe syntax](../engineering/collection-recipes.md). Universal PDF accuracy, formula recalculation, unrestricted workbook templates, automatic accounting treatment, live Ylookup posting and production identity/deployment remain outside this implementation.
