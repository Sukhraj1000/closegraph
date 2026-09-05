# Evidence-led collaboration

## User journey

Use Overview to see blockers and their owners. Documents contains original files and immutable uploaded revisions. Tasks contains specific requests and manually raised concerns. Review changes compares saved versions; Outputs holds draft and approved downloads. Complex recipes and parser metadata stay in Advanced details.

Accountants edit files in Excel, then choose Add document or Upload new version. A revision requires its current parent and a reason. A document's reporting period is explicit; a different period is a new document. Optional Evidence date is the source's as-of date, not its upload date. CloseGraph records the submitter and differences between submitted files; it cannot observe unsaved edits or prove the author of each changed cell.

Confirm source headers and review extraction before accepting it. PDF completeness additionally requires an explicit source review bound to the original bytes. Provider completion alone is insufficient. Native value extraction remains deterministic and preserves saved values. Date/number conversion in the output uses explicit form selections.

An account manager configures required evidence and checks, including owners, periods, freshness, tolerances and calculation rules. Evidence-only configuration without any substantive check cannot establish financial verification. Fee calculations require an explicit approved rule, base, rate and rounding; no accounting treatment is inferred.

Missing or stale evidence creates an owner request. Ambiguous extraction and processing failures route internally to the account manager. Validated inputs breaching an explicit rule create a discrepancy with recorded operands and references. Investor requests require manager release. Receipt and acknowledgement are separate from verified resolution. A new response document must be explicitly bound to the relevant requirement; attaching an arbitrary file does not satisfy it.

Manual concerns are labelled as manual, initially nonblocking, and can target only permitted recipients. The account manager can make one blocking with a reason. Requirement discrepancies resolve through reevaluation, not a manual override.

Review changes shows values, formulas and cached values separately from formatting. Explicit unique business keys support reordered records. Ambiguous keys, changed embedded content and unsupported PDF comparisons retain warnings. An independent manager may record a manual comparison review against exact before/after file hashes, without claiming automated comparison coverage or bypassing financial checks.

Independent output approval binds the current sources, mappings, rules, checks and candidate bytes. Known unrelated documents retain existing approval; unresolved dependencies invalidate it. An unchanged sheet and exact accepted column schema can carry explicit table bindings to its next revision, with the rebinding recorded. Changed or ambiguous schemas require mapping review.

## Parties and access

The accountant prepares; the account manager coordinates and independently verifies; fund managers and investors supply assigned evidence. Server roles constrain preparation/review capabilities. Per-collection assignments and document grants restrict external parties. Sharing a task does not grant a whole-file download. Restricted participants cannot release or download output artifacts or read the internal audit history.

Notifications are durable in-app records only. Retries deduplicate notifications and submissions. Required deadlines generate one overdue notice and configured escalation per request cycle. Dagster's existing sensor advances deadline notices. Refresh retrieves changes made by another user; processing refreshes automatically.

Local accounts use `preparer` and `reviewer`; optional `fund_manager` and `investor` accounts require corresponding private `CLOSEGRAPH_FUND_MANAGER_PASSWORD` and `CLOSEGRAPH_INVESTOR_PASSWORD` settings. New runtime initialization generates all four; existing runtime credentials are preserved. Account managers assign external participants and share documents explicitly. This local account model is not production identity management.

## Interfaces and compatibility

Existing Collections APIs remain, with optional revision, period, as-of, task and idempotency fields on uploads. Added endpoints cover participants/members, requirements/evaluation, comparison pagination and manual review, coverage review, document business keys, flags/task actions and the notification inbox. Mutations retain expected-version checks and current server-owned authorization.

Logical documents, requests, check results and notification records use existing PostgreSQL collection snapshots and immutable revision history. Large table/comparison bodies use scoped immutable blobs. Existing sources are mapped individually into logical documents; filenames do not merge old sources into guessed histories. Old artifacts remain historical and never gain approval under the new policy automatically.

No live spreadsheet editor, filesystem watcher, cloud connector, external notifications or accounting-system writes are implemented. Extraction tests do not establish accounting treatment or universal PDF accuracy.
