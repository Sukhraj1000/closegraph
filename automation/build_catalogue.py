"""Build the issue catalogue from exact OpenSpec tasks and approved epic ownership."""
from pathlib import Path
import json
import re

ROOT=Path(__file__).resolve().parents[1]
CHANGE='openspec/changes/verify-corrected-reporting-pack'
EPICS={
'E0':('Hermes cron engineering and independent review','Native paused Hermes cron jobs, sandboxed coding/testing, review feedback and guarded merge policy. No custom server, listener, scheduler or QA bot.',['A01','A02','A03','A04']),
'E1':('UI and reviewer workspace','React evidence-first correction, review and release journey. Own apps/web feature code and browser tests; API fixtures enable independent development, real API is required for final acceptance.',['9.1','9.2','9.3','9.4']),
'E2':('API, evidence storage and access control','Typed contracts, PostgreSQL migrations, immutable evidence, sessions, permissions and authorised API transport. Own contracts/storage/api; domain rules belong to E4/E5.',['2.1','2.2','2.3','2.4','8.4']),
'E3':('Source extraction and normalisation','Bounded CSV/XLSX/PDF adapters, context/decimal normalisation and source locators. Own extractors/normalisers; candidate observations never grant financial approval.',['3.1','3.2','3.3','7.1','7.2','7.3']),
'E4':('Financial verification and review routing','Schema/coverage checks, deterministic financial rules and explainable hard-gate-first triage. Own validators, parser_signals and routing; test typed fixtures without UI or Dagster.',['3.4','4.1','4.2','4.3','4.4']),
'E5':('Correction lifecycle and reviewed output','Versioned corrections, dependency impact, mapped workbook/manifest and independent snapshot-bound review/publication. Own corrections/impact/review/publication services and outputs.',['5.1','5.2','5.3','5.4','8.1','8.2','8.3']),
'E6':('Dagster pipeline and local runtime','Scaffolding, local services, snapshot-bound computational orchestration and recovery. Own runtime manifests and pipeline; never duplicate financial or approval logic in Dagster.',['1.1','1.3','1.4','6.1','6.2','6.3','6.4','6.5']),
'E7':('Test harness, fixtures and human acceptance','Labelled fixtures, deterministic integration/E2E harness and evidence reports. Each feature owns necessary tests; user owns exploratory QA and final acceptance. No QA bot.',['1.2','10.1','10.2','10.3','10.4'])}
TITLES={
'1.1':'Bootstrap pinned Python runtime','1.2':'Build labelled synthetic reporting fixtures','1.3':'Configure isolated local PostgreSQL and Dagster services','1.4':'Bootstrap FastAPI health and React application',
'2.1':'Define canonical fact and evidence contracts','2.2':'Implement versioned storage schema and migrations','2.3':'Implement immutable scoped source receipts','2.4':'Enforce scoped sessions and independent roles',
'3.1':'Extract declared CSV layouts without losing raw tokens','3.2':'Extract XLSX values and preserve formula limitations','3.3':'Normalise explicit numeric and entity context','3.4':'Execute data-level validation and source coverage checks',
'4.1':'Compute versioned financial reconciliations','4.2':'Compare parser observations in full context','4.3':'Route review using hard-gate precedence','4.4':'Evaluate versioned review policies on held-out cases',
'5.1':'Record source-backed correction versions','5.2':'Propagate evidenced dependency impact','5.3':'Generate and round-trip the supported workbook','5.4':'Generate complete source-to-output manifests',
'6.1':'Execute snapshot-bound native Dagster assets','6.2':'Dispatch durable processing requests idempotently','6.3':'Preserve negative check diagnostics in review','6.4':'Recover safely from interrupted and late execution','6.5':'Trigger new computation from correction revisions',
'7.1':'Implement the configured-only Reducto adapter','7.2':'Add optional second-parser observation interface','7.3':'Verify the authorised live PDF path',
'8.1':'Enforce independent exact-snapshot review decisions','8.2':'Gate publication on trusted state and artifact integrity','8.3':'Prevent stale publication under concurrent writes','8.4':'Expose authorised scoped workflow API routes',
'9.1':'Render separate execution and business states','9.2':'Build source evidence and correction interactions','9.3':'Build independent review and gated release interactions','9.4':'Expose all-values inspection and audit history',
'10.1':'Run the complete backend verification matrix','10.2':'Exercise the real browser correction-to-download journey','10.3':'Produce source-linked MVP acceptance evidence','10.4':'Obtain human acceptance of the working MVP'}
DEPS={
'1.2':['2.1'],'1.3':['1.1'],'1.4':['1.1'],'2.1':['1.1'],'2.2':['2.1','1.3'],'2.3':['2.2'],'2.4':['2.2','1.4'],
'3.1':['2.1'],'3.2':['2.1'],'3.3':['2.1'],'3.4':['2.1','1.2'],'4.1':['2.1','1.2'],'4.2':['2.1'],'4.3':['4.1','4.2'],'4.4':['4.3','1.2'],
'5.1':['2.2','2.4'],'5.2':['2.2'],'5.3':['2.1','1.2'],'5.4':['2.1'],'6.1':['1.3','2.3','3.1','3.2','3.3','3.4','4.1','4.3','5.3','5.4'],
'6.2':['1.3','2.2'],'6.3':['6.1'],'6.4':['6.1','6.2'],'6.5':['5.1','5.2','6.1','6.2'],
'7.1':['2.1'],'7.2':['2.1'],'7.3':['7.1'],'8.1':['2.4','5.1','5.2'],'8.2':['8.1','5.3','5.4'],'8.3':['8.2'],'8.4':['2.4','5.1','6.2','8.1','8.2'],
'9.1':['1.4','2.1'],'9.2':['1.4','2.1'],'9.3':['1.4','2.1'],'9.4':['1.4','2.1'],
'10.1':['2.3','3.4','4.4','6.4','6.5','7.2','8.3','8.4'],'10.2':['10.1','9.1','9.2','9.3','9.4'],'10.3':['10.2','7.3'],'10.4':['10.3']}
AUTO={
'A01':('Configure paused native Hermes engineering/reviewer cron jobs','Use native Hermes cron with deterministic monitor output, one engineering job and one independent-review job. Keep both paused and local-only. No custom listener/controller. Verify actual job IDs, prompts, schedules, enabled=false and unchanged unrelated jobs.',['automation/cron_tools.py','automation/cron-jobs.json'],[]),
'A02':('Verify macOS sandbox and isolated worker/test execution','Full independent clones, isolated HOME/TMPDIR and test state; all coding/tools/tests inherit sandbox. Prove allowed in-sandbox writes and denied outside/sibling/secret/symlink/network access. No unsandboxed fallback. Bound execution and concurrency. Selected real coding CLI and authorised model access must be tested before activation.',['automation/closegraph_loop/sandbox.py','automation/tests/test_sandbox.py'],[]),
'A03':('Enforce scope, review feedback and appropriate integration tests','Engineering repairs the same PR after changes requested. Reviewer independently reads issue/spec/diff and runs relevant tests; adds integration/E2E requirements only where changed boundaries/journeys need them. Verify current head/base, formal review identity, no self-approval, no duplicate jobs or phase-2 expansion. Human integrates/accepts.',['automation/prompts/engineer.md','automation/prompts/reviewer.md','docs/engineering/architecture.md'],['A01','A02']),
'A04':('Complete supervised activation and protected auto-merge gates','Operator gate: current private repository protection API returns403 requiring GitHub Pro/public. Keep private and auto-merge off; no billing change. Authorise distinct eligible reviewer principal, scoped coding/runtime access and real task test plan. Verify branch rules, exact-head review, serial merge and post-merge smoke before explicit user resume. No autonomous QA bot or hosted CI required now.',['docs/engineering/activation.md'],['A03'])}


def build():
    text=(ROOT/CHANGE/'tasks.md').read_text()
    tasks=dict(re.findall(r'^- \[ \] (\d+\.\d+) (.+)$',text,re.M))
    mapped=[t for _,_,ts in EPICS.values() for t in ts if not t.startswith('A')]
    assert sorted(mapped)==sorted(tasks) and len(mapped)==len(set(mapped))
    issues=[]
    for epic,(title,scope,keys) in EPICS.items():
        body=f'## Outcome\n{scope}\n\n## Ownership and parallel work\nThis is a workstream in one repository, not a separate service. Own only the named responsibilities; shared contracts/migrations have explicit ownership. Task-level prerequisites are listed on children. Fixture/contract development may run in parallel; final integration cannot be declared independent.\n\n## Definition of done\n- [ ] All child scope and acceptance criteria have real evidence.\n- [ ] Relevant regression/integration/E2E tests pass; no unexplained skips.\n- [ ] Changes received independent review.\n- [ ] User-reviewed integration/acceptance where applicable.\n\n## Boundaries\nNo automatic phase-2 evidence requests/deadline alerts, arbitrary financial agents, production deployment, external data uploads or scope expansion. Product source: `{CHANGE}/tasks.md`, its capability specs, and `docs/acceptance.md`. Engineering method: native Hermes cron, macOS sandbox, independent review, tests and human QA.'
        issues.append(dict(key=epic,title=f'[Epic {epic}] {title}',kind='epic',epic=None,spec_tasks=[],labels=['epic',f'area:{epic.lower()}'],depends_on=[],body=body))
        for key in keys:
            if key.startswith('A'):
                title,detail,paths,deps=AUTO[key]
                body=f'## Scope\n{detail}\n\n## Files\n'+ '\n'.join(f'- `{p}`' for p in paths)+'\n\n## Acceptance\n- [ ] Implement the bounded scope above.\n- [ ] Exercise actual local commands and record results.\n- [ ] Distinguish fixture tests from real agent/GitHub operation.\n- [ ] Keep dispatch and auto-merge disabled until explicit activation approval.\n\n## Status\nSetup work may exist locally; this issue is not a claim of end-to-end live acceptance.'
                spec_tasks=[]
                child_key=key
            else:
                title=TITLES[key];child_key='T'+key;spec_tasks=[key];deps=['T'+x for x in DEPS.get(key,[])]
                body=f'## Original OpenSpec task {key}\n{tasks[key]}\n\n## Source of truth\n- `{CHANGE}/tasks.md`, task {key}\n- `{CHANGE}/design.md` and relevant `specs/*/spec.md` scenarios\n- `docs/acceptance.md`\n\nBackend abbreviated paths are relative to `apps/api/src/closegraph/`; UI component paths to `apps/web/src/features/packs/`. Python test paths are repository-relative; run a named test with `uv run --project apps/api pytest <test-path>`. Commands in the source task are future implementation verification, not tests already run.\n\n## Acceptance\n- [ ] Implement only the original task and its stated failure cases.\n- [ ] Run the exact named verification above and retain actual output.\n- [ ] Preserve source/decimal/context/version/security semantics from the capability specs.\n- [ ] Add/update integration or browser E2E only where changed boundaries/journeys need it; run existing relevant coverage regardless and explain selection.\n- [ ] Independent reviewer verifies scope and exact head/base evidence.\n\n## Parallel development versus completion\nUse typed fixtures/contract adapters to work independently of unfinished neighbours. Required real API/database/browser/provider acceptance remains outstanding until actually exercised. UI tasks can begin after scaffolding/contracts, but cannot close solely on mocked API results. Missing Reducto permission/credentials remains a blocker, never a passing replay.\n\n## Out of scope\nOther epics\' ownership, automatic phase-2 work, unapproved infrastructure, private data disclosure and unrelated refactors. Product implementation has not started at issue creation.'
            issues.append(dict(key=child_key,title=f'[{child_key}] {title}',kind='task',epic=epic,spec_tasks=spec_tasks,labels=['task',f'area:{epic.lower()}','automation' if epic=='E0' else 'mvp'],depends_on=deps,body=body))
    out=ROOT/'docs/engineering';out.mkdir(parents=True,exist_ok=True)
    (out/'issue-catalog.json').write_text(json.dumps(dict(schema_version=1,repo='Sukhraj1000/closegraph',issues=issues),indent=2)+'\n')
    sections=['# Epic ownership and parallel execution\n\nEight parent epics: seven product workstreams plus the small native-Hermes delivery setup. GitHub child tasks map the original OpenSpec tasks exactly once. Epics are not separate services. No QA bot or custom listener/controller.\n\n## Shared kickoff\n\nT1.1 establishes Python tooling; T2.1 freezes typed contracts; T1.4 supplies API/web scaffolds. UI can then develop against contract fixtures, parsers against labelled files and rules against canonical snapshots. T2.2 owns migrations. Final integration/acceptance remains genuinely dependent.\n']
    for k,(title,scope,ts) in EPICS.items():
        sections.append(f'## {k}: {title}\n\n{scope}\n\nTasks: '+', '.join(t if t.startswith('A') else 'T'+t for t in ts)+'.\n')
    sections.append('## Execution policy\n\nNative Hermes cron checks GitHub state rather than running a custom server. Engineering fixes outstanding reviews before claiming new ready work; reviewer handles changed PR revisions. Use small isolated sandboxed runs, explicit file ownership, relevant tests and formal independent reviews. Same-head repeats are skipped using actual GitHub review state. User owns final QA. Start serially; add disjoint engineering lanes only after the first supervised loop passes and capacity is measured. All new issues begin in backlog and both jobs remain paused.\n')
    (out/'epics.md').write_text('\n'.join(sections))
    print(json.dumps({'issues':len(issues),'epics':len(EPICS),'original_tasks':len(mapped),'automation_tasks':len(AUTO)}))

if __name__=='__main__':build()
