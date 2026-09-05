# Authorised synthetic Reducto capture — 2026-09-05

These are exact bytes retained from one real, authorised provider request using the labelled 705-byte synthetic PDF. They contain no customer documents or credentials. `receipt.json` records the actual execution time, job, endpoint and hashes. The endpoint was `https://platform.reducto.ai`; the account's regional entitlement and Growth-plan status were not independently confirmed. The note records conditional published terms without asserting ZDR or verified residency.

Using these files later is **captured replay or verification of historical live evidence**, never another live request. The local application labels configuration `CAPTURED_REPLAY` and canonical observations `REPLAY`. Its PDF observations have no approved financial mapping and remain blocked for financial release.

The original receipt paths are retained unchanged. From the repository root, prepare the ignored replay directory:

```sh
mkdir -p artifacts/live-reducto
cp fixtures/captured/reducto-live-20260905/receipt.json artifacts/live-reducto/
cp fixtures/captured/reducto-live-20260905/parse-response.json artifacts/live-reducto/
cp fixtures/captured/reducto-live-20260905/synthetic.pdf artifacts/live-reducto/
```

Then explicitly set `CLOSEGRAPH_REDUCTO_LIVE_RECEIPT=artifacts/live-reducto/receipt.json` to verify this actual historical receipt in the live-evidence test. See the local runtime guide for `CAPTURED_REPLAY` configuration and a fresh PDF upload to create new application evidence. No provider key or network permission is needed to replay. This synthetic exercise does not authorise private-document processing.
