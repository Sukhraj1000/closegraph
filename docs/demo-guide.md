# CloseGraph demo guide

## The useful promise

“Show me exactly which records need an answer, let me give the right person a specific question, and show whether the corrected submission fixed it.”

Keep the presentation centred on an accountant and account manager. Fund managers and investors participate only when they have a specific, explicitly shared request. Do not introduce every role or every available control in one demonstration.

## A short route through the product

The local demo pack uses complete public SEC numeric records and their filing register. It contains 136,044 numeric records and 522 filing records. The large record table has reordered columns and rows and renamed headings. Exactly 63 filing references were deliberately replaced with one absent test reference; other labelled mutations exercise missing-value checks. These are test corruptions, not alleged errors in SEC filings. The corrected revision restores the original source values while retaining the reordered layout.

The same source-backed workflow supports fund reporting packs. The public files demonstrate ingestion, references and correction tracking; they do not supply private-market accounting policy.

### 1. Upload once and establish the question

Sign in as the accountant. Choose **New review**, select the two files in the demo pack's **1-upload** folder, name the review and choose **Prepare review brief**. Show the real document counts while processing.

Choose **Choose checks for this pack → Add a check**:

- Question: **Every value has a reference mapping**.
- Name: **Every reported fact belongs to a filing in the register**.
- Source table: **SEC reordered with missing references.csv**; column **Filing reference**.
- Reference table: **SEC filing register.csv**; column **adsh**, the source's filing identifier.
- Confirm the selections and choose **Save and check**.

Expected outcome: one missing-reference finding affecting **63 source records**. The rule checks membership in this selected register; it does not validate every financial amount.

For a live presentation, do this setup beforehand and start at the finding. Saved work retains its selected check.

### 2. Show an actionable exception

Open the finding and choose **View affected records**. Show page two to demonstrate that all 63 rows are available, then expand one complete source record. Its row location points back to the original file.

Choose **Download all affected records (CSV)**. This contains the complete exception list, with source locations and readable fields. Import identifier columns as text in Excel to preserve leading zeros. Original uploads remain unchanged.

### 3. Ask a precise question

Inside the finding, expand **Ask someone to resolve this**. Assign the request to the account manager and describe the missing evidence or correction. The Requests inbox opens the question and its supporting finding directly.

Reading a request does not resolve it. A reply or attachment records progress; the system check must pass on current evidence before the discrepancy is resolved.

### 4. Show what the next version fixed

In **Documents**, select the existing numeric document and choose **Upload new version**. Select the matching file in **2-corrected-version** and explain the revision. Do not choose Add document: this is the next version of the same logical document.

The reference check should pass after reevaluation, the linked request should resolve and **History** should show the change. The supplied browser acceptance also checks a single source-backed correction first: **63 → 62 → 0** affected records.

The correction file restores the public source values. Do not enter a plausible replacement merely to clear a check; use the recorded source or upload the supplied corrected revision.

### 5. Review the exact completed scope

Sign in as the independent account manager, open the work and choose **Review and release**. Explain that approval covers the selected filing-reference check and exact evidence versions. Download the reviewed brief.

The person who prepared or changed the check cannot approve their own work. Selected formula results and incomplete extraction remain blockers. Formula notes concerning unused columns remain visible without claiming those formulas were verified.

## The private-market version of the same story

Use the supplied **Investor-Level GL** and **Tranche 1 reference and verified loader** workbooks. Inspect a legal-entity mapping proposal and confirm its intended reference list and reporting scope before running it. The recorded source comparison found 15 distinct mapping values absent from the selected entity listing, and 10 GL entity values absent across 4,450 GL records. Different intended scope or approved aliases can change the interpretation; do not describe these automatically as accounting errors.

Show a specific gap, its affected rows, a request and the change after a corrected submission. Keep the original Excel template as the source of the reporting work. The current default output is a review brief and exception CSV, not a rebuilt administrator loader or certified NAV pack.

## Stress checks and demonstration limits

The **3-stress-case** file deliberately repeats a header far into the large CSV. With the corresponding original columns selected, it should require input rather than produce a confirmed comparison. This is useful reliability evidence, but it should be a short optional demonstration rather than the opening screen.

Grouped totals establish that the selected sums agree. They cannot detect offsetting errors within the same group. The product does not infer LPA, fee, NAV or valuation rules, universally recalculate spreadsheets, or verify arbitrary PDF cells automatically. PDF provider replay is labelled as replay.

The independent public data source is the [SEC Financial Statement Data Sets](https://www.sec.gov/data-research/sec-markets-data/financial-statement-data-sets), 2010 Q2. The native TSV files were converted to CSV without changing field values; original and deliberately modified files remain separate. Financial statements are not independently certified by these checks.
