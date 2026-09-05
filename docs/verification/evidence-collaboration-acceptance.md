# Evidence collaboration acceptance — 6 September 2026

Implemented uploaded document revisions, bounded asynchronous comparisons, versioned evidence requirements, scoped four-party tasks, durable in-app notifications, and independent dependency-bound approval. The standard interface uses Overview, Documents, Tasks, Review changes and Outputs. See the engineering workflow guide for configuration and limits.

## Verification

- Full API suite: 513 passed, 2 existing conditional tests skipped.
- Final affected integration/access suite after final fixes: 16 passed.
- Web suite: 62 passed; TypeScript and production Vite build passed.
- Integrated browser workflow passed: upload and extraction review; configure evidence and total checks; create and independently approve output; upload revision; compare changed value; observe failing total; correct the explicit requirement; reevaluate; approve and download the revised output.
- Covered retry idempotency, stale-parent rejection, raw originals, reordered and ambiguous keys, formulas/caches, missing policy and extraction blocks, stale evidence, task response linkage, scoped participants, self-approval rejection, notification deduplication and approval invalidation.
- Checks used isolated database schemas and a separate browser database. No trial records were inserted into working collections.

## Supplied bank workbook trial

A private in-memory fixture retained 15 sheets, 16 tables, 9,893 rows and 81,849 cells without native extraction errors. All 100 populated transaction amount tokens matched independent saved workbook XML. Eight explicitly scoped currency/debit-credit totals matched independent workbook references. Unaccepted extraction produced Needs review. After simulated fixture acceptance, a configured counterparty check identified 52 missing values and one blocking task.

This trial verifies extraction and declared arithmetic, not the accounting validity of that counterparty rule, all original workbook cells, final journal treatment, or PDF bank balances. No private workbook data or fixture-specific mappings are committed. This implementation adds no new live provider acceptance claim.

## Product limits

Business rules, tolerances, ownership and evidence scope must be explicitly configured. Upload history records submitters and changes between saved revisions, not unsaved Excel edits or each original cell editor. Unsupported or incomplete comparisons require a recorded independent review; they never claim automatic comparison coverage. Notifications are in-app; use Refresh for changes made by another participant. No email, live editing, shared filesystem or external connectors were added.
