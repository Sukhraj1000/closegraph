# Rehearse the private-market demo

## The point to make

“An accountant receives a messy reporting pack. Instead of checking every sheet again and sending a vague email, they can show exactly which records need an answer, attach the source and ask the right person. The next upload shows whether that question was resolved.”

Show one check well. A useful incomplete result is more credible than a green screen produced by an invented accounting rule.

## Files and expected results

Upload these two organiser files together in **New review**:

- **Investor-Level GL - Q2 activity - all entities (anonymised).xlsx** from `02-investor-level-gl-to-loader/source`.
- **Tranche 1 - reference and verified loader v4c (anonymised).xlsx** from `02-investor-level-gl-to-loader/output`.

The first contains the GL; the second supplies reference/mapping sheets. Use **Phase I loader - sample (anonymised).xlsx** separately for a scale demonstration after the main journey works. Its 94,454 data rows show loading and preview performance, but do not establish an approved loader transformation. Save the bank workbook/PDF workflow for a separate demonstration with configured extraction.

Use these exact selections on the unmodified originals:

| Check | Source table and column | Reference | Previously independently checked outcome |
| --- | --- | --- | --- |
| Entity mapping coverage | **LE Mapping → Legal Entity**, headers on Excel row **2** | **Entity Listing → Entity**, headers on row **1** | **15** absent entity values affecting **15 of 84** mapping records. |
| GL entity scope | **Investor-Level GL → Legal Entity**, headers on row **1** | **Entity Listing → Entity** | **10** absent entity values affecting **4,450 of 33,902** GL records. |
| Mapping field completeness | **Mapping Gaps → Approval**, headers on row **1**; choose **Required values are present** | No reference table | **2** missing fields at **G2** and **G3**. This does not establish actual financial or legal approval. |

Inspect previews before confirming. If LE Mapping shows the banner “KESTREL Data” as column names, use **Documents**, open that table, select row 2 as its header, save the interpretation and reopen the check. Do not confirm a check against the banner row. Do not rely on automatic suggestions to establish accounting meaning.

For the mapping checks, describe a finding as **“not present in the selected reference list”**. The dataset has not supplied an independently authorised replacement for every absent mapping. Investor-name checks also contain duplicate names: that needs a scoped identifier and should remain **Needs your input**.

## Four-to-five-minute recording

### 0:00–0:30 — Explain the job

State the reporting-pack question above. Name the accountant and account manager. Keep the other two roles for a specific request, rather than changing accounts four times just to show them.

### 0:30–1:00 — Start with the original workbooks

Sign in as **accountant**. Select **New review**, upload the GL/reference pair, name it “Demo — Q2 entity mapping review” and choose **Prepare review brief**. Show processing briefly; do the actual upload before recording and reopen it through **Recent work → Open work** for a tighter presentation.

### 1:00–2:00 — Show one specific conclusion

Choose **Choose checks for this pack → Add a check → Every value has a reference mapping**. Name it “Entity mapping coverage” and use the first table selection above. Inspect the previews, tick the confirmation and choose **Save and check**.

Open one difference. Show **See complete source record**, the source workbook/sheet/row, and **View affected records**. Choose **Download all affected records (CSV)** to show the full list for that finding. After the first check is saved, the button becomes **Review selected checks**; use it to add another check. For the larger GL check, show pagination inside a finding with many affected records. There are ten entity findings; do not describe 4,450 as the size of every individual finding or export.

Say: “This entity is absent from the reference list we selected. We need its approved mapping or confirmation that it is outside this scope.” Do not say the GL is wrong or the full fund has been reconciled.

### 2:00–3:00 — Make the question somebody's work

In the finding, expand **Ask someone to resolve this**. Select **Account manager**, add a deadline if useful, and write the specific request above. Open **Requests → View request**. Show its linked evidence and activity. Sign in as **account_manager** to show the assigned request and respond.

Check that acknowledging the request or attaching evidence changes its activity/state but does not falsely close the system finding. Notifications are for an actionable assignment/update, not one noisy alert for every GL row.

To demonstrate the fund manager, the account manager first uses **People and access** to add the account and explicitly shares only the relevant document/request evidence. Investors require an account-manager release. A fresh external-party login sees no unrelated workbook. Skip this optional branch if it distracts from the core example.

### 3:00–4:00 — Show what changed

For genuine mapping issues, keep the request open until an authorised revised mapping is supplied. Use **Documents → Upload new version** on the existing document, record a reason and allow reevaluation. **History** shows the submitter, time and saved changes. It does not identify unsaved Excel edits or each original cell author.

For a repeatable correction demonstration without inventing a financial answer, use the separate test-only rehearsal below. Do not alter the original mapping to make a presentation pass.

### 4:00–5:00 — Deliver an honest output

Choose **Download brief**. Show the question, evidence and any unresolved findings. It is a review brief, not a rebuilt loader, signed fund accounts or a NAV certificate.

On a separate fully resolved selected scope, **account_manager → Review and release** can independently approve and download the reviewed brief. The account manager must not have prepared or corrected that scope. Unresolved selected checks and stale evidence must prevent this. For a previously verified complete correction→approval path, the [public SEC demo](demo-guide.md) supplies a known corrected source revision and independent expected results; it is labelled as a public-data test, not fund-accounting truth.

## Optional isolated correction rehearsal: 2 → 1 → 0

Create a **separate** review containing the original reference workbook. Add only the **Mapping field completeness** check above. Name this work “TEST ONLY — correction and revision rehearsal”. Two empty Approval fields are the expected starting result.

1. Open the missing-field finding and its complete source record. Choose **Inspect or correct this extraction**. In this isolated rehearsal only, fill G2 with an explicit test label and a reason stating that it is a workflow test, not a real financial approval. Save the extraction decision. Expect **2 → 1** missing fields; the original workbook download remains unchanged.
2. Open **History** and find that decision and reason. This demonstrates how an evidenced extraction correction is recorded; actual work requires a real supported value.
3. Upload the separately provided **TEST ONLY - Tranche reference revision.xlsx** as a **new version of the same document**, not another document. This is an existing test fixture: only Mapping Gaps!G2 and G3 were filled with “Isolated test evidence recorded”; the accompanying mutation ledger records those exact changes. The supplied original and all other XLSX ZIP parts are unchanged. Expect **1 → 0** for this completeness check after reevaluation.
4. A linked system request should resolve only when the selected check passes. Unrelated missing mappings remain unresolved in their own reviews. A field being nonempty does not establish actual approval authority.

The private original files, test revision and mutation ledger are distributed locally outside Git. Judges who do not have that test revision can rehearse the first three mapping/request steps on the originals or use the separately provided public demo pack. Do not claim an unavailable fixture is included in a fresh clone.

## Before you record

- The two named workbook previews show readable headers and original-source links; no column mapping requires JSON.
- The mapping counts match the selections above, or the changed interpretation is explicitly explained.
- A finding opens its actual record; pagination/CSV includes all affected rows for that finding.
- Request ownership, a reply and activity are understandable without coaching; acknowledgement is not resolution.
- Original versus uploaded revision is clear in Documents/History. The original source still downloads unchanged.
- A working brief visibly retains unresolved questions. Independent approval does not become available merely because processing finished.
- Fund-manager/investor accounts see only explicitly shared requests and evidence.
- Batman remains decorative. Once a minute he briefly runs, flips, glides or grapples; a random starting point/side varies the four-movement loop. The corner button pauses visits. Reduced motion disables visits and leaves a static loading sprite.

Do not claim a measured time saving until an accountant/account manager has completed the same task in their existing workflow and in CloseGraph. Technical acceptance and a polished recording are not customer validation.
