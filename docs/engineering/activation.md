# Paused cron setup and activation gates

## What exists

- Private GitHub repository, mapped epics/tasks, architecture and review template.
- Native Hermes cron definitions saved in `automation/cron-jobs.json` and registered PAUSED.
- `automation.cron_tools`: read-only status/monitor plus real sandbox self-test command.
- Full-clone macOS sandbox and tests. No custom listener/controller is shipped.

The cron jobs are drafts with a hard instruction to stop whenever `dispatch_available=false`. That value is deliberately false in the current executable. Merely resuming a schedule does not implement or authorise worker execution. No real model coding/review pilot or automatic merge was performed.

## Real commands

From the repository root with Python 3.12:

```sh
npm run loop:test
npm run spec:check
python3.12 -m automation.cron_tools status
python3.12 -m automation.cron_tools monitor
python3.12 -m automation.cron_tools sandbox-self-test
python3.12 -m automation.publish_issues  # validates only; --apply is the external-write switch
hermes cron list --all
```

`automation/cron-jobs.json` records verified native job IDs and intended prompts. Their delivery is `local`: reports are saved by Hermes, not messaged into a terminal session. No model/provider override is set; global Hermes routing is unchanged. Native monitor scripts are under the default profile's `.hermes/scripts/closegraph/`; the installable source is `automation/cron_monitor.py`. Register it using the relative name `closegraph/monitor.py`, since the current cron API rejects absolute monitor paths.

## Explicitly outstanding before live work

1. Select a real coding/review CLI and authorised inference access. Prove every child capability executes inside the existing sandbox, without broad profile/credential mounts. Offline sentinel tests are not this proof.
2. Implement and verify the small trusted publishing adapter for exact changed bytes. Do not execute untrusted repo Git hooks/config with host credentials. Use one serial worker until duplicate-claim prevention and resource limits are measured.
3. Configure a distinct eligible GitHub reviewer account/App. Two jobs/tokens for one author cannot approve that author's PR. Read back actual formal reviews.
4. Establish task-specific test commands, isolated database state/roles/ports and browser runtime. Test failures cannot be hidden by generic smoke checks.
5. Run one supervised task -> sandboxed change -> tests -> PR -> independent review -> repair/re-review pilot. Track exact head AND base. Only then replace the intentional `dispatch_available=false` gate with verified readiness and obtain explicit user approval to resume.
6. Separately resolve GitHub protected-branch access, configure and read back review/stale-dismissal/conversation rules, verify serial merging and a failing post-merge smoke stop before enabling auto-merge. No hosted CI setup is required now.

## Confirmed protection blocker

`gh api repos/Sukhraj1000/closegraph/branches/main/protection` returned HTTP 403: upgrade to GitHub Pro or make the repository public. Preserve the approved private visibility. No billing/visibility changes are authorised, and local checks are not misreported as branch protection.

## Pause and recovery

Use `hermes cron pause <verified-job-id>` for the two CloseGraph jobs only; confirm `enabled=false` with a fresh list. Do not resume unrelated jobs. A missed tick is recovered by reading GitHub state. Never use a model summary as a lock or approval. Do not expose a webhook server to avoid polling.

The user owns final QA and acceptance. All original product tasks remain unimplemented until real application evidence exists; live PDF credentials/data scope is a separate product acceptance gate.
