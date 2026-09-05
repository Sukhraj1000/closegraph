# Collections: extract, inspect, transform and release

Collections accepts varied source structures without selecting accounting treatment from a
filename, sheet name or sample dataset. Native readers handle CSV/XLSX; Reducto supplies
AI-assisted PDF observations. A recipe specifies what the accepted data should become.
The existing reporting-pack workflow remains available separately.

## Workflow and accuracy boundaries

1. **Upload sources.** Original bytes are stored immutably in the collection's scope. Dagster
   discovers draft tables and records parser settings, source coordinates, raw values and
   coverage findings. Every source row is retained; suggested headers require confirmation.
2. **Inspect and correct.** Compare the source with the paginated grid, follow issue links,
   confirm headers, correct values, or explicitly split, merge and exclude rows. Corrections
   retain original evidence and reasons. PDF citations keep their actual precision: a
   provider block box is not a cell box. Explicit human selections are labelled separately.
3. **Accept the input version.** Acceptance binds the dataset's exact stored hash. Correctable
   errors resolve only after the relevant recorded repair; undoing that repair reopens the
   error. Transport failures, truncation and incomplete coverage cannot be dismissed.
4. **Define and run the recipe.** Choose source tables, output fields, mappings, joins,
   calculations, classifications, allocations and reshaping explicitly. Decimal calculations
   and configured locale/date conversion execute in code. No LLM supplies accounting rules,
   generated code or hidden mappings. See [recipe syntax and export contracts](collection-recipes.md).
5. **Check and independently review.** Configure required fields, uniqueness, totals and
   balances appropriate to the task. Failed or uncomputable checks block approval. Inspect
   the output grid and downloadable **DRAFT** candidate bytes. An independent reviewer
   approves the exact candidate snapshot; preparers cannot approve their own work.
6. **Release those bytes.** Export releases the candidate already generated, reopened and
   verified before review. It also supplies a source-to-output manifest. Changing a source,
   correction, recipe, template or binding invalidates the current approval and requires a
   new run and review. Historical downloads and decisions remain historical.

Dagster owns computation and durable retry requests. Jobs finish before human review; users
never keep a job waiting for a decision. An explicit extraction retry replaces that source's
current datasets and corrections with a fresh extraction. Earlier versions remain in history.
Review changes wait for queued processing to finish.

Native extraction preserves text identifiers and original numeric XML tokens, including
long decimals and date serials. XLSX formulas and cached values are evidence only: formulas
are not recalculated, missing caches are unresolved, and existing caches are unverified.
Merged cells are not automatically filled. Embedded charts/images are not extracted as
worksheet facts. CSV delimiter ambiguity is reported; encoding and delimiter choices remain
visible. Locale conversions require explicit instructions.

Reducto can omit, merge or misread content. Its confidence is an uncalibrated observation,
not evidence of financial correctness or a hallucination-free guarantee. Review the complete
relevant dataset, including unflagged rows. Successful extraction, acceptance and passing
checks each establish only their stated conditions; none proves universal accuracy.

## Bounds and outputs

The application accepts **32 MiB per upload**, with extraction budgets of **250,000 rows**
and **4,000,000 stored cells per source**, up to 128 sheets and 1,024 discovered columns per
table. XLSX XML is streamed; returned review datasets are materialised within these bounds.
Expanded ZIP content is limited to 512 MiB, with a 256 MiB member limit. Hitting a limit
retains available evidence and reports incomplete extraction. Blank styled worksheet ranges
do not become invented data rows.

Transform and export budgets are separate: up to 200,000 output rows and two million mapped
export cells. The API accepts up to 50 recipe steps. CSV/XLSX output columns and workbook
bindings are explicit; loader schemas are not hardcoded. Plain XLSX templates support the
features documented in the recipe guide. Unsupported features or occupied mapped cells
produce an error rather than silent loss. Template selection belongs in the recipe before
review; the export request cannot introduce another template or mapping afterward.

Source-to-output manifests include original source references and derived-cell lineage.
Split/merged rows preserve their original source identities. Text is the default export type
so identifiers and long decimals survive. Typed Excel numbers must survive exact readback
within Excel's precision. CSV spreadsheet-formula escaping is recorded in verification.

A local evaluation of the four supplied anonymised XLSX files extracted **33 tables,
161,246 rows and 4,553,167 stored cells**, with no extraction errors. Counts include retained
header rows. This demonstrates broader ingestion on those files; it is not an independently
verified financial reconciliation, a completed loader mapping or evidence about PDF accuracy.

## Live PDF gateway setup

Install a reviewed copy of `scripts/reducto_gateway.py` **outside the worker checkout**.
Run it with Python 3.12 and `--config /absolute/private/reducto.json`. The private JSON file
must be a regular non-symlink file with mode `0600`, containing:

- `api_key`: the provider credential, held only by the trusted gateway.
- `token`: a random gateway capability of at least 32 characters.
- `authorized_source_hashes`: the exact lowercase SHA-256 allowlist of approved PDFs.
- `authorization_reference` and `data_handling_note`: the actual processing authorization
  and applicable data-handling record.

Configure the worker's private runtime environment with
`CLOSEGRAPH_PDF_GATEWAY_URL=http://127.0.0.1:24183/parse` and the matching
`CLOSEGRAPH_PDF_GATEWAY_TOKEN`. Restart the API/Dagster runtime after changing its environment.
The worker receives the loopback capability, never the Reducto API key or general provider
network access. Keep credentials and the private configuration out of Git and logs.

The gateway accepts only allowlisted source bytes and calls the fixed standard
`https://platform.reducto.ai` upload/parse endpoints. Requests set `persist_results: false`
and `force_url_result: false`; these settings do not establish account region, provider
retention guarantees or zero-data-retention terms. Record the applicable terms explicitly.
The gateway reloads the private allowlist per request and bounds concurrent provider calls.
Missing configuration, disallowed sources or provider failure produces an unavailable
finding. No synthetic or replay response is silently substituted for a live result.
