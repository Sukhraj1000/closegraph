# Judge demo and Batman: acceptance

6 September 2026. This verifies the current local demo instructions and UI additions, not fund accounting or customer usability.

- **106 web tests passed**, including the minute timer, four-movement cycle, pause persistence, hidden-tab scheduling and reduced-motion behavior. TypeScript and the production build passed.
- **One launcher/credential test passed**: four per-install sign-ins are read from the explicit private file; a publicly readable credential file is rejected. This check does not assert that a clean machine's dependency downloads were repeated.
- **One real browser Batman test passed**: all four animations were shown using an accelerated browser clock, screenshots inspected, input remained usable, pause worked and reduced motion suppressed visits.
- **Actual supplied GL/reference pair:** two documents, 16 tables and 56,881 displayed data rows. Browser upload, source inspection, a required-field correction, history, working brief download and refresh persistence passed. Missing Approval fields in a test-only scope went **2 → 1**.
- **Actual XLSX revision:** the existing isolated fixture filled only Mapping Gaps!G2 and G3 with a test label. Uploading it as the next version resolved the selected field-completeness check **1 → 0**. Original and revised downloads matched their respective input hashes. A nonempty Approval cell is not a financial approval.
- **Documented mapping selections:** the browser reproduced **15 missing legal-entity mappings affecting 15 records**, then **10 missing GL entity values affecting 4,450 records**. Financially verified remained false. These are exact selected-reference gaps, not proof of incorrect accounting.

The first two real-file scenarios passed together. The added mapping scenario initially failed because its test selectors omitted displayed table-title suffixes and then expected the initial check-button label after a check existed. The selectors and walkthrough were corrected; the mapping scenario passed on a targeted rerun, reusing the uploaded test collection. Prior failures are retained in the local receipts.

Private workbooks, screenshots, mutation ledger, browser exports and execution receipts remain outside Git. The rehearsal used the isolated app/database. No provider call, production deployment, new external integration or change to financial rules was made. The earlier independently checked source counts and limits remain in [fund-review acceptance](fund-review-acceptance.md).
