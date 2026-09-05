import { describe, expect, it } from 'vitest';
import { initialScenario, transition, scenarios, snapshot } from './synthetic';
import { eligibleForReview, formatDecimal, normalizeAmount, normalizeCorrectionAmount } from './model';
describe('synthetic exact-version workflow', () => {
  it('keeps failed correction results, requires repair, review and attestation', () => {
    let state = initialScenario('correction');
    state = transition(state, { type: 'correct', value: '60000.00', reason: 'FT-002 supports this value.' });
    expect(state.version).toBe(3);
    expect(snapshot(state).checks.find(c => c.id === 'capital')?.status).toBe('FAIL');
    expect(eligibleForReview(snapshot(state))).toBe(false);
    state = transition(state, { type: 'repair' });
    expect(eligibleForReview(snapshot(state))).toBe(true);
    expect(() => transition(state, { type: 'approve', note: 'Checked.', attested: true })).toThrow(/independent/i);
    state = transition(state, { type: 'role', role: 'reviewer' });
    expect(() => transition(state, { type: 'approve', note: '', attested: true })).toThrow(/note/i);
    expect(() => transition(state, { type: 'approve', note: 'Checked.', attested: false })).toThrow(/attest/i);
    state = transition(state, { type: 'approve', note: 'Checked FT-002 and all affected values.', attested: true });
    expect(snapshot(state).review_status).toBe('APPROVED');
    expect(state.history.find(h => h.version === 3)?.checks?.some(c => c.status === 'FAIL')).toBe(true);
  });
  it('never marks blockers eligible and preserves unknown versus not checked', () => {
    expect(scenarios).toHaveLength(8);
    for (const id of ['missing', 'disagreement', 'dependency', 'provider', 'stale', 'template'] as const) {
      expect(eligibleForReview(snapshot(initialScenario(id)))).toBe(false);
    }
    expect(snapshot(initialScenario('provider')).checks.some(c => c.status === 'UNKNOWN')).toBe(true);
    expect(snapshot(initialScenario('stale')).checks.every(c => c.status === 'NOT_RUN')).toBe(true);
  });
  it('adding a source does not fix the mismatch; stale approval is historical', () => {
    let missing = transition(initialScenario('missing'), { type: 'receive' });
    expect(snapshot(missing).checks.find(c => c.id === 'fee')?.status).toBe('FAIL');
    let stale = transition(initialScenario('stale'), { type: 'recheck' });
    expect(stale.approvedVersion).toBe(4);
    expect(stale.version).toBe(5);
    expect(snapshot(stale).review_status).toBe('AWAITING_REVIEW');
  });
  it('requires a recorded resolution separately from approval', () => {
    let s = initialScenario('disagreement');
    expect(() => transition(s, { type: 'resolve', note: '' })).toThrow(/evidence/i);
    s = transition(s, { type: 'resolve', note: 'FT-002 and Capital!B4 support Reader A.' });
    expect(eligibleForReview(snapshot(s))).toBe(true);
    expect(snapshot(s).review_status).not.toBe('APPROVED');
  });
});
describe('decimal input without financial floating-point conversion', () => {
  it('normalizes plain cents and rejects ambiguous input', () => {
    expect(normalizeAmount('60000')).toBe('60000.00');
    expect(normalizeAmount('0.1')).toBe('0.10');
    for (const bad of ['1e4', '$60,000', '-1', '1.001', '', '20000000.01']) expect(() => normalizeAmount(bad)).toThrow();
    expect(formatDecimal('9007199254740993.01', 'USD')).toBe('$9,007,199,254,740,993.01');
  });
});

describe('general correction decimal input',()=> {
 it('preserves supported currencies and precision without fixture-specific limits',()=>{
  expect(normalizeCorrectionAmount('9007199254740993.01')).toBe('9007199254740993.01');
  expect(normalizeCorrectionAmount('-10.125')).toBe('-10.125');
  expect(normalizeCorrectionAmount('00060')).toBe('60.00');
  expect(()=>normalizeCorrectionAmount('1e3')).toThrow();
  expect(()=>normalizeCorrectionAmount('1.1234567890123')).toThrow();
 });
});
