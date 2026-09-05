// Synthetic fixtures: imported by Storybook/tests only, never by the real API entrypoint.
import type { Check, HistoryEntry, PackSnapshot } from './model';
import { eligibleForReview, normalizeAmount } from './model';
export const scenarios = [
  { id: 'correction', name: 'Fee correction — start here' }, { id: 'missing', name: 'Missing fee agreement' },
  { id: 'disagreement', name: 'Document readers disagree' }, { id: 'dependency', name: 'Unknown effect on a statement' },
  { id: 'provider', name: 'PDF processing unavailable' }, { id: 'ready', name: 'Ready for independent review' },
  { id: 'stale', name: 'Source changed after approval' }, { id: 'template', name: 'Unsupported workbook feature' },
] as const;
export type ScenarioId = typeof scenarios[number]['id'];
export interface SyntheticState {
  scenario: ScenarioId; version: number; fee: string; role: 'accountant' | 'reviewer';
  evidence: boolean; provider: boolean; dependency: boolean; template: boolean;
  capitalFresh: boolean; stale: boolean; resolved: boolean; approvedVersion: number | null; history: HistoryEntry[];
}
export type SyntheticAction = { type: 'correct'; value: string; reason: string } | { type: 'role'; role: SyntheticState['role'] } | { type: 'repair' | 'receive' | 'recheck' } | { type: 'resolve'; note: string } | { type: 'approve'; note: string; attested: boolean };
export function initialScenario(scenario: ScenarioId): SyntheticState {
  const corrected = ['disagreement', 'dependency', 'ready', 'stale', 'template'].includes(scenario);
  const history: HistoryEntry[] = [{ version: 1, title: 'Original pack received', note: 'Synthetic original workbook retained.' }, { version: 2, title: 'Fee rule updated', note: 'FT-002 supports $60,000; original pack reports $75,000.' }];
  if (corrected) history.push({ version: 3, title: 'First correction left a failed check', note: 'Capital statement remained $15,000 below corrected NAV.', checks: [{ id: 'capital', label: 'Capital statement agrees', status: 'FAIL', required: true, detail: 'Original statement remained $20,000,000.' }] }, { version: 4, title: 'Capital statement updated', note: 'Synthetic fee $60,000; NAV and capital statement $20,015,000.' });
  if (scenario === 'stale') history.push({ version: 4, title: 'Approved by Morgan Ellis', note: 'Historical only. Covers the previous source version.' }, { version: 5, title: 'Source changed after approval', note: 'Capital source v2 arrived. Checks and independent approval need renewing.' });
  return { scenario, version: scenario === 'stale' ? 5 : corrected ? 4 : 2, fee: corrected ? '60000.00' : '75000.00', role: ['disagreement', 'ready'].includes(scenario) ? 'reviewer' : 'accountant', evidence: scenario !== 'missing', provider: scenario === 'provider', dependency: scenario !== 'dependency', template: scenario !== 'template', capitalFresh: true, stale: scenario === 'stale', resolved: false, approvedVersion: scenario === 'stale' ? 4 : null, history };
}
function decimal(cents: bigint): string { return `${cents / 100n}.${String(cents % 100n).padStart(2, '0')}`; }
export function snapshot(s: SyntheticState): PackSnapshot {
  const fee = BigInt(s.fee.replace('.', '')), liabilities = decimal(67500000n + fee), nav = decimal(2075000000n - (67500000n + fee));
  const check = (id: string, label: string, status: Check['status'], detail: string): Check => ({ id, label, status: s.stale ? 'NOT_RUN' : s.provider ? (id === 'documents' ? 'UNKNOWN' : 'NOT_RUN') : status, detail: s.stale ? 'Source changed; results are out of date. Recheck this version.' : s.provider ? 'Required PDF processing is unavailable. No substitute values were checked.' : detail, required: true });
  const checks: Check[] = [
    check('documents', 'Required documents are available', s.evidence ? 'PASS' : 'UNKNOWN', s.evidence ? 'Fee rule, capital input and original workbook are linked.' : 'Approved fee agreement is missing. Terms cannot be checked.'),
    check('fee', 'Fee matches the approved rule', !s.evidence ? 'UNKNOWN' : s.fee === '60000.00' ? 'PASS' : 'FAIL', !s.evidence ? 'No approved rule is available.' : `FT-002 expects $60,000.00; recorded ${s.fee} USD. Allowed difference $0.01.`),
    check('nav', 'Net assets agree with the balance sheet', 'PASS', `Assets 20750000.00 less liabilities ${liabilities} equals NAV ${nav} USD.`),
    check('capital', 'Capital statement agrees with net asset value', !s.dependency ? 'UNKNOWN' : s.capitalFresh ? 'PASS' : 'FAIL', !s.dependency ? 'The effect on the statement is unknown; do not assume it is unaffected.' : s.capitalFresh ? 'Current capital statement and NAV agree.' : `Capital statement remains 20000000.00; current NAV is ${nav}.`),
    check('template', 'Workbook output is supported', s.template ? 'PASS' : 'FAIL', s.template ? 'Supported formulas and output structure.' : 'An unsupported macro prevents equivalent output, even when financial checks pass.'),
  ];
  const hardPass = checks.every(c => c.status === 'PASS'), disagreement = s.scenario === 'disagreement' && !s.resolved, available = !s.provider && !s.stale;
  const values = [ ['management_fee', 'Management fee', s.fee, '75000.00', 'Fees!F18'], ['total_assets', 'Total assets', '20750000.00', '20750000.00', 'NAV!H10'], ['total_liabilities', 'Total liabilities', liabilities, '750000.00', 'NAV!H16'], ['net_asset_value', 'Net asset value', nav, '20000000.00', 'NAV!H22'], ['capital_statement', 'Capital statement', s.capitalFresh ? nav : '20000000.00', '20000000.00', 'Capital!G24'] ];
  return { pack_id: 'synthetic-harbour-q2', fund_id: 'Synthetic Harbour Fund I', title: 'Q2 reporting pack', version: s.version, execution_status: s.provider ? 'FAILED' : 'COMPLETED', checks,
    routing_status: !hardPass ? 'BLOCKED' : disagreement ? 'NEEDS_REVIEW' : 'READY_FOR_QUICK_REVIEW', unresolved_soft_signals: disagreement, resolution: s.resolved ? { reason: 'Source-backed synthetic resolution recorded', source_ids: ['rule'] } : null,
    review_status: s.approvedVersion === s.version && !s.stale ? 'APPROVED' : hardPass && !disagreement ? 'AWAITING_REVIEW' : 'BLOCKED', freshness: s.stale ? 'STALE' : 'CURRENT',
    policy_version: 'synthetic-native-tabular-v1',
    evidence: {
      rule: {source_id:'rule',document_name:'Fee rule',filename:'synthetic-fee-rule-FT-002.csv',locator:'FT-002 · clause 2',entity_id:'Synthetic Harbour Fund I',currency:'USD',period:'Q2 2026',status:!s.evidence||s.provider?'UNAVAILABLE':'AVAILABLE',preview_rows:[{label:'Opening fee eligible capital',value:'$20,000,000'},{label:'Annual rate',value:'1.20%'},{label:'Quarter of the annual fee',value:'¼'},{label:'Expected fee',value:'$60,000.00'}]},
      capital: {source_id:'capital',document_name:'Capital',filename:'synthetic-capital-inputs.xlsx',locator:'Capital!B4',currency:'USD',period:'Q2 2026',source_version:s.scenario==='stale'?'v2':'v1',preview_rows:[{label:'Fee eligible capital',value:'$20,000,000'}]},
      original: {source_id:'original',document_name:'Original pack',filename:'synthetic-quarterly-pack-v2.xlsx',locator:'Fees!F18',currency:'USD',period:'Q2 2026',preview_rows:[{label:'Original management fee',value:'$75,000.00'}]},
    },
    observations:s.scenario==='disagreement'?[{reader:'Reader A (synthetic replay)',value:'60000.00',currency:'USD',period:'Q2 2026',score:'0.96 · uncalibrated'},{reader:'Reader B (synthetic replay)',value:'75000.00',currency:'USD',period:'Q2 2026',score:'0.98 · uncalibrated',agreement:'DISAGREE'}]:[{reader:'Native workbook values (synthetic)',confidence:'NOT_APPLICABLE',second_reader:'NOT_RUN'}],
    facts: values.map(([fact_id, metric, value, raw, locator]) => ({ fact_id, metric, value_decimal: available && !(fact_id === 'capital_statement' && !s.dependency) ? value : '', raw_value: raw, raw_scale: '1', currency: 'USD', period: 'Q2 2026', entity_id: 'synthetic-harbour', source: { source_id: fact_id === 'management_fee' ? (s.evidence && !s.provider ? 'rule' : '') : 'original', document_name: 'Original reporting pack.xlsx', locator, context: 'Synthetic source; original values are immutable.' } })),
    candidate: available && s.template ? { artifact_id: `synthetic-v${s.version}`, total_decimal: nav, total_label: 'Net asset value', download_url: null } : null, history: s.history };
}
export function transition(state: SyntheticState, action: SyntheticAction): SyntheticState {
  const s = { ...state, history: [...state.history] };
  const record = (title: string, note: string) => s.history.push({ version: s.version, title, note, actor: s.role === 'reviewer' ? 'Morgan Ellis (synthetic)' : 'Jamie Park (synthetic)', checks: snapshot(s).checks.map(c => ({ ...c })) });
  if (action.type === 'role') return { ...s, role: action.role };
  if (action.type === 'correct') {
    if (s.role !== 'accountant' || !s.evidence || s.provider) throw new Error('An authorised preparer and available evidence are required.');
    const value = normalizeAmount(action.value); if (!action.reason.trim()) throw new Error('Explain why you are changing the fee.');
    s.fee = value; s.version++; s.capitalFresh = false; s.stale = false; s.resolved = false; record('Correction saved by Jamie Park', action.reason.trim());
  }
  if (action.type === 'repair') {
    if (s.role !== 'accountant' || s.fee !== '60000.00' || !s.evidence || !s.dependency || s.provider || s.stale) throw new Error('Resolve the source and fee blockers before updating the statement.');
    s.version++; s.capitalFresh = true; record('Capital statement updated', 'Synthetic statement now agrees with NAV. Independent approval is still required.');
  }
  if (action.type === 'receive') { if (s.role !== 'accountant') throw new Error('Only the preparer can add the example source.'); s.evidence = true; s.version++; record('Example fee agreement added', 'Adding evidence does not correct the fee mismatch.'); }
  if (action.type === 'recheck') { if (s.role !== 'accountant' || s.provider) throw new Error('The preparer must resolve processing and recheck.'); s.stale = false; record('Current source version checked', 'Prior approval remains historical; new independent approval is required.'); }
  if (action.type === 'resolve') {
    if (s.role !== 'reviewer' || s.scenario !== 'disagreement' || !snapshot(s).checks.every(c => c.status === 'PASS')) throw new Error('Independent reviewer and passed checks required.');
    if (!action.note.trim()) throw new Error('Add evidence and a reason for accepting this reading.');
    s.resolved = true; record('Reader disagreement resolved by Morgan', `${action.note.trim()} Both original readings are retained. This is not an approval.`);
  }
  if (action.type === 'approve') {
    if (s.role !== 'reviewer') throw new Error('An independent reviewer is required.');
    if (!eligibleForReview(snapshot(s))) throw new Error('Resolve required checks, evidence and freshness before approval.');
    if (!action.attested) throw new Error('Attest that you inspected this exact version.');
    if (!action.note.trim()) throw new Error('Add a review note.');
    if (s.approvedVersion === s.version) throw new Error('This version is already approved.');
    s.approvedVersion = s.version; record('Approved by Morgan Ellis', `${action.note.trim()} Approval applies only to version ${s.version} and its sources. No files published.`);
  }
  return s;
}
