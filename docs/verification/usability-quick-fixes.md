# Request and review usability fixes — 6 September 2026

## Delivered

- Requests opens an assigned-to-me inbox across accessible reviews. Review and assignment selectors filter the list; selecting a review is no longer required. Unread updates are separate from active request counts, grouped by request and refreshed while the page is visible, with manual Refresh retained.
- Reference/uniqueness finding titles include the observed business key and affected record count. A finding's next action precedes long evidence lists. No entity or accounting treatment is inferred.
- Advanced extraction JSON uses the surrounding review's light surface, text and border colours.
- Send reply records an actor, time and note without resolving a request. Attachment notes and document links are retained in request activity. Further evidence can be attached while evidence is received or verification is pending. Existing permission and investor-release checks apply. Retry idempotency prevents duplicate events and notices.
- History defaults to newest material events. Routine processing and notification reads remain in complete activity; unchanged before/after findings can be expanded. Changed operands/counts remain visible even if a finding stays outstanding.
- Original bytes are reused on identical blob retries. New writes reserve 64 MiB for recovery; actual disk/quota failures remain handled. Failed extraction identifies storage exhaustion and retains original files. If the immutable job receipt cannot be stored, its failed snapshot is retained transactionally in PostgreSQL, with the job failed rather than stranded running. This guard is per write, not a reservation for an entire concurrent job or a guarantee against a full database volume.

## Automated evidence

- Web: 112 tests passed across 21 files; production TypeScript/Vite build passed.
- API: 118 tests passed against PostgreSQL using a separate temporary schema per integration test. Scope: blob storage, deterministic fund-review checks, evidence workflow, evidence collaboration, fund-review journey and collections.
- Added regression scenarios cover zero-free-space deduplication, refusal of new writes, failure-receipt recovery, retained source bytes, successful retry, permission-restricted/idempotent replies, repeated attachments with separate notes/notices, immediate cross-review assignments, visible notification events, unchanged request state after replies/reads, and history ordering.

## Actual UI walkthrough

Used separate accountant, account manager, fund manager and investor accounts in the isolated app at port 24273. Working collections in the normal app were not used for test mutations.

- Account manager: opened assigned work without selecting a review; sent a reply on an acknowledged system finding. The request stayed acknowledged. Opened the linked entity finding, with its actual business key, 1,860 affected records and exact source citation; next action was above the source examples.
- Extraction JSON: inspected visually and checked computed foreground rgb(32,44,42) on rgb(255,255,255).
- History: the newly sent reply was first, with account manager and readable time. Unchanged before/after cards were not expanded by default.
- Fund manager: initial inbox showed only the assigned scope request; sent a reply after evidence receipt. Status remained Evidence received and attachment controls remained available.
- Investor: initial inbox showed only the previously released personal request; replied successfully, with no fund GL or another party's request visible. Status remained Acknowledged.
- Account manager: received visible event-specific updates for the fund manager and investor replies. Marking the investor's grouped updates read changed the total from 15 to 12; the next link opened the fund-manager request, still Evidence received.
- Accountant: the previously failed original GL/reference pair showed Storage is full beside each file and a clear Retry processing action. Retried through the UI. Both original workbooks completed: 2/2 documents, 16 tables, 56,881 rows. The brief required confirmed checks and did not claim financial verification.

Screenshots are retained locally under the task workspace's outputs/closegraph-quick-fixes directory. Private workbooks, test responses and screenshots are not committed to Git. Repeated attachments were verified in PostgreSQL integration tests; this walkthrough did not add another real-file attachment or make any financial approval. No paid parser calls or external notifications were used.
