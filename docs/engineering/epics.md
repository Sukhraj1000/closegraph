# Epic ownership and parallel execution

Eight parent epics: seven product workstreams plus the small native-Hermes delivery setup. GitHub child tasks map the original OpenSpec tasks exactly once. Epics are not separate services. No QA bot or custom listener/controller.

## Shared kickoff

T1.1 establishes Python tooling; T2.1 freezes typed contracts; T1.4 supplies API/web scaffolds. UI can then develop against contract fixtures, parsers against labelled files and rules against canonical snapshots. T2.2 owns migrations. Final integration/acceptance remains genuinely dependent.

## E0: Hermes cron engineering and independent review

Native paused Hermes cron jobs, sandboxed coding/testing, review feedback and guarded merge policy. No custom server, listener, scheduler or QA bot.

Tasks: A01, A02, A03, A04.

## E1: UI and reviewer workspace

React evidence-first correction, review and release journey. Own apps/web feature code and browser tests; API fixtures enable independent development, real API is required for final acceptance.

Tasks: T9.1, T9.2, T9.3, T9.4.

## E2: API, evidence storage and access control

Typed contracts, PostgreSQL migrations, immutable evidence, sessions, permissions and authorised API transport. Own contracts/storage/api; domain rules belong to E4/E5.

Tasks: T2.1, T2.2, T2.3, T2.4, T8.4.

## E3: Source extraction and normalisation

Bounded CSV/XLSX/PDF adapters, context/decimal normalisation and source locators. Own extractors/normalisers; candidate observations never grant financial approval.

Tasks: T3.1, T3.2, T3.3, T7.1, T7.2, T7.3.

## E4: Financial verification and review routing

Schema/coverage checks, deterministic financial rules and explainable hard-gate-first triage. Own validators, parser_signals and routing; test typed fixtures without UI or Dagster.

Tasks: T3.4, T4.1, T4.2, T4.3, T4.4.

## E5: Correction lifecycle and reviewed output

Versioned corrections, dependency impact, mapped workbook/manifest and independent snapshot-bound review/publication. Own corrections/impact/review/publication services and outputs.

Tasks: T5.1, T5.2, T5.3, T5.4, T8.1, T8.2, T8.3.

## E6: Dagster pipeline and local runtime

Scaffolding, local services, snapshot-bound computational orchestration and recovery. Own runtime manifests and pipeline; never duplicate financial or approval logic in Dagster.

Tasks: T1.1, T1.3, T1.4, T6.1, T6.2, T6.3, T6.4, T6.5.

## E7: Test harness, fixtures and technical acceptance

Labelled fixtures, deterministic integration/E2E harness and evidence reports. Each feature owns necessary tests; the coordinator records automated technical acceptance. User review is optional.

Tasks: T1.2, T10.1, T10.2, T10.3, T10.4.

## Execution policy

Native Hermes cron checks GitHub state rather than running a custom server. Engineering fixes outstanding reviews before claiming new ready work; reviewer handles changed PR revisions. Use small isolated sandboxed runs, explicit file ownership, relevant tests and formal independent reviews. Same-head repeats are skipped using actual GitHub review state. User owns final QA. Start serially; add disjoint engineering lanes only after the first supervised loop passes and capacity is measured. All new issues begin in backlog and both jobs remain paused.
