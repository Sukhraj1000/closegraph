# CloseGraph reviewer workspace

React/TypeScript/Vite workspace using repository-owned shadcn-style components built on Radix. The shared theme and component catalogue follow `docs/ui/design-system.md`.

The application reads its authority from a server-resolved, HTTP-only local session. Runtime data comes from the API. The eight labelled synthetic scenarios are imported only by Storybook and tests; changing the story role does not authenticate an application user.

## Local commands

Run from the repository root:

```sh
npm ci --prefix apps/web
npm --prefix apps/web run dev
npm --prefix apps/web run build
npm --prefix apps/web test
npm --prefix apps/web run storybook
npm --prefix apps/web run build-storybook
```

Vite listens on `127.0.0.1:24173`. Its same-origin `/api` proxy targets `127.0.0.1:24180`; set `CLOSEGRAPH_API_URL` for a different local API. Storybook listens on `127.0.0.1:24174`.

The backend provisions accounts and pack grants. No credentials or runtime role selector are embedded in the frontend. Sign in with the separately configured preparer and reviewer accounts.

## Workflow

Select an assigned pack and upload its capital CSV, authorised fee-rule CSV and original workbook. The backend stores the bytes and queues processing. The UI polls pending/running work, preserving separate processing, checks, routing, approval and freshness states.

Inspect any source or value, record a source-supported correction and review its recomputed results. Corrections retain original observations and history. A reader disagreement requires a recorded evidence-backed resolution before separate approval. Only an independent reviewer can attest and submit an exact-snapshot decision. Publication checks and permissions remain authoritative on the server.

Candidate workbook inspection is explicitly labelled before publication. Reviewed workbook and manifest downloads use server-provided, same-origin artifact URLs.

## Browser verification

Build Storybook, serve `apps/web/storybook-static` on localhost port 24174, then run:

```sh
npm --prefix apps/web run test:stories
```

This suite covers all eight scenarios across four pages, WCAG A/AA automated checks, a failed correction followed by repair, independent review, separate resolution, keyboard tabs/dialog/checkbox, and narrow-width reflow. Automated checks complement actual assistive-technology testing.

The native suite uses the running real API, PostgreSQL, Dagster and actual fixture files:

```sh
npm --prefix apps/web run test:native
```

Configure these environment variables before running it:

- `CLOSEGRAPH_TEST_PREPARER_USERNAME`, `CLOSEGRAPH_TEST_PREPARER_PASSWORD`
- `CLOSEGRAPH_TEST_REVIEWER_USERNAME`, `CLOSEGRAPH_TEST_REVIEWER_PASSWORD`
- `CLOSEGRAPH_TEST_PACK_ID`
- `CLOSEGRAPH_FIXTURE_DIR` containing `capital.csv`, `fee-rule.csv`, `original.xlsx`

The native suite expects a clean assigned pack and a running Dagster processor. It uploads actual files through the UI, makes the failed and successful repairs with distinct users, inspects the candidate, approves, publishes and saves workbook/manifest evidence in ignored `test-results/`. The backend acceptance tests must independently verify the downloaded workbook's mapped cells and manifest integrity.

Set `CLOSEGRAPH_UI_URL`, `CLOSEGRAPH_STORYBOOK_URL` or `PLAYWRIGHT_BROWSERS_PATH` for an isolated test installation. Browser launch infrastructure failures do not count as passing UI tests.

Original PDF citations use the exact document-version download, the 1-based original page, and declared normalized or point coordinates. PDF.js is pinned and its worker is bundled locally; PDF code loads only when PDF evidence is opened. The renderer never substitutes a processed page or guesses a missing coordinate convention. The two-page PDF used by the component browser check is a Storybook-only fixture.

Independent reviewers can explicitly sample ready values. Source openings, value inspection and ready sampling are recorded with the loaded state revision through the authenticated review-events API. The observed-work report shows server-recorded counts, first-to-last event span and reopened scope; it makes no claim about active review time, a customer baseline or savings. Context or authorised treatment changes use replacement source versions under the supported mapping.
