# Engineering setup: actual verification

Verified on the local macOS host with Python 3.12. This is the simplified, paused native-Hermes setup, not a live agent fleet or implemented financial application.

## Executed checks

- `npm run loop:test`: 22 tests passed, no skips. Includes 15 real full-clone/macOS sandbox tests, 4 catalogue tests and 3 read-only cron helper tests. Independent review found a resumed-publication integrity gap; added a failing-first regression and now verify exact task bodies/labels on resume plus the entire final catalogue before certifying completion.
- `npm run spec:check`: strict OpenSpec validation passed (1 change, 0 failures). All four planning artifacts are ready. This does not prove product behaviour.
- `python3.12 -m automation.cron_tools sandbox-self-test`: `ok=true`. Python, shell, Git and own-workspace writes execute. Outside-home/sibling/symlink reads/writes return EPERM; synthetic sentinels remain unchanged. Default network, unlisted loopback and Unix-daemon sockets are denied. Only the explicitly allowed loopback port connects in restricted mode.
- Self-test workspace: `/Users/sukhrajkalon/projects/closegraph-sandboxes/selftest-4c9fdb27bc9142b7/repo`.
- `python3.12 -m automation.cron_tools status`: `mode=paused-setup`, `dispatch_available=false`, `auto_merge=false`.
- Native cron monitor wrapper executed against real GitHub successfully. Two consecutive stationary snapshots matched byte-for-byte, including current main SHA.
- `python3.12 -m automation.publish_issues --apply`: exit 0. Published/read back 52 issues: 8 epics, 40 original product tasks and 4 delivery tasks. All 8 native parent/sub-issue hierarchies verified. An additional independent script reread and exactly compared every rendered remote issue body/title with the catalogue, found all open and none ready for dispatch.
- Original OpenSpec product implementation checkboxes checked: 0. Every original task mapped exactly once; dependency graph is acyclic.

## Native scheduling state

Verified by rereading default-profile native cron storage after creation and pause:

| Job | ID | Intended interval | Actual state |
|---|---|---|---|
| closegraph-engineering-loop | 30723152fd6a | 30 minutes | paused; never run |
| closegraph-independent-review-loop | c8f0dcced8c1 | 15 minutes | paused; never run |

Both use local-only delivery, terminal-only orchestration, continuity and the relative monitor `closegraph/monitor.py`. No per-job model/provider override. The existing 33 unrelated jobs remain present and were not targeted by any mutation. The creation API briefly registers enabled jobs; both were paused before their first due tick, with last-run fields null. Cron definitions are recorded in `automation/cron-jobs.json`.

## Limits and unexercised paths

- No live coding/reviewer model invocation, issue-to-PR pilot, reviewer-identity approval or automatic merge was performed. The deliberate dispatch guard stays false; the small real adapter/trusted publishing integration remains follow-up work.
- The private repository's branch protection API returned HTTP 403 requiring an eligible plan. Visibility and billing were not changed. Protected automatic merging remains unavailable/off.
- The sandbox is Seatbelt, not a VM or security certification. Allowed system/toolchain paths/root-directory listing remain readable; no hard memory/CPU/disk/process quota. Detached hostile descendants can evade process-group cleanup while still sandboxed. Real coding/browser runtimes and disposable test-service capabilities need their own supervised validation.
- No financial UI/API/Dagster workflow, browser journey, live Reducto PDF or financial output was implemented/tested here. Future test commands in product issues are acceptance requirements, not claimed results.
- Abandoned custom-controller code/tests were moved to ignored `var/abandoned-custom-controller/`, not deleted or shipped. No custom listener, scheduler, SQLite ledger or public ingress remains in the deliverable.

The independent spec review's missing-manifest finding was resolved by saving and rereading the paused native job definitions. The code review's publisher-integrity finding was fixed, regression-tested and independently re-reviewed as APPROVED. A real resumed publication then completed with all 52 issue bodies/labels and all native hierarchies verified, without duplicates.

The user remains the integrator/QA. Product epics require actual implemented acceptance; GitHub issue publication and test-run counts are not product progress.
