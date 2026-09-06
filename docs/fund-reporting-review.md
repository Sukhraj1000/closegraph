# Fund reporting review POC

CloseGraph helps an accountant and an account manager inspect a reporting pack, trace a finding to its source and see whether a correction resolved it. Original Excel files, formulas and templates are retained; the review brief is a separate download.

## A short demonstration

1. Sign in as the accountant. Choose **New review** and upload the reporting workbook plus the relevant ledger, reference lists or other evidence. Choose **Prepare review brief**.
2. Read the coverage summary. **Choose checks for this pack** shows proposed reference checks with real source previews. Confirm only the list, columns, fund and period you intend to compare. Proposals are not accounting instructions.
3. Open a finding. Compare its observed value, selected rule and source row. **View affected records** paginates every indexed source record and offers a complete CSV exception download. Older saved reviews with sample citations require a rerun before a complete download is available. Follow the original-file link or **Inspect or correct this extraction**. A correction needs a reason and reruns the review.
4. If someone else must respond, assign a specific request. Reading it or uploading evidence does not resolve a system finding; a fresh check must clear it. Requests open directly to response controls and, for internal participants, the linked finding.
5. Use **History** for the before/after outcome. An unavailable or withdrawn check is not recorded as a fix. Download a working HTML review brief while issues remain.
6. An account manager who did not prepare the data or change its check configuration can approve the exact completed review scope after outstanding findings and blocking requests are cleared. This approves the selected checks, not the fund's accounts.

**Documents** retains every uploaded version. For an Excel correction, edit the permitted original in Excel and choose **Upload new version** with the previous revision and a reason. The system tracks submitted differences, not unsaved Excel edits or the identity of every original cell author.

## Four parties

- The accountant uploads, confirms proposed mappings, investigates findings and supplies corrected evidence.
- The account manager coordinates requests and performs independent review. **People and access** adds existing authorised accounts and grants selected documents explicitly.
- The fund manager answers an assigned fund-level request and sees only permitted evidence.
- The investor sees an explicitly assigned request after account-manager release. Assignment alone grants no workbook access.

Not every review needs all four parties. A manager who changes check configuration becomes a contributor and needs another reviewer for approval.

## What the POC checks

The generic analyzer supports required values, unique business keys, reference-list membership and grouped totals. Column headings and exact value overlap suggest possible checks. The user confirms their meaning and scope. Grouped totals use decimal arithmetic, explicit grouping and zero monetary tolerance by default. Matching totals do not establish the correctness of individual transactions.

Missing coverage, ambiguous headers, duplicate reference keys, unconfirmed PDF extraction and selected unverified formula results remain open. Unverified formulas used only in unselected columns appear as supporting notes; they do not block approval of the exact supported check scope, and their caches are never relabelled verified. Small numeric values stored by Excel in scientific notation are preserved as exact decimals. No financial rule is inferred from a filename, a worksheet labelled “verified”, a narrative instruction or an AI parser's confidence.

Current limitations:

- No autonomous fee, LPA, NAV or valuation interpretation; those require explicitly established accounting rules and independent source evidence.
- No universal mapping from an arbitrary GL to an administrator's loader. Existing advanced transformation services remain available, but this POC produces a review brief rather than rebuilding a formatted workbook.
- PDF blocks and unclassified content remain accessible. A successful parse is not verified cell accuracy, and a captured response is identified as replayed extraction.
- No live Excel editing, external notifications, new connectors or hosting changes.
- Automated acceptance demonstrates technical behavior. First-time customer validation and an approved financial answer remain separate gates.

## Technical path

The React fund-review workspace uses the existing scoped Collections API. Immutable original files and extracted tables stay in scoped blob storage; PostgreSQL stores revisions, jobs, check configuration, requests and notices. Dagster runs extraction and evaluation. A pure `fund_review.analyze` function produces profiles, proposed checks, evidence-linked findings and structural readiness outcomes. Scoped services bind those results and independent approval to exact input fingerprints.

Changes rebind a configured table only when its logical document, unique table, column schema and header values agree. Otherwise the mapping needs confirmation again. Large results and before/after detail are stored in immutable blobs; normal result pages and previews are bounded.

Notifications remain durable and in-app. Assignments are batched, passing checks are quiet, and deadlines produce one overdue notice plus one configured escalation per request cycle. Old failures and decisions remain in history. External participants cannot fetch the internal brief, its results or history without the corresponding internal authority.

## Business accounts

Sign in as `accountant`, `account_manager`, `fund_manager` or `investor` using the corresponding configured password. Role selection chooses an account; it does not bypass authentication or change permissions. The accountant/account-manager login names resolve to the existing immutable preparer/reviewer identities so saved memberships, contributions and approvals retain their meaning. Existing passwords and legacy logins remain valid. Normal account labels and participant names use the business roles.

Processing stages and document counts appear only when available. Older saved jobs with only operational identifiers show a readable status without invented document counts.
