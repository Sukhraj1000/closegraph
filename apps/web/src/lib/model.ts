export type CheckStatus = 'PASS' | 'FAIL' | 'UNKNOWN' | 'NOT_RUN' | 'NOT_APPLICABLE';
export interface Check { id: string; label: string; status: CheckStatus; required: boolean; detail: string; justification?: string; expected_decimal?: string; actual_decimal?: string; difference?: string; tolerance?: string; applicable?: boolean; diagnostics?: unknown }
export interface Source { source_id?: string; document_name?: string; filename?: string; locator?: string | Record<string, unknown>; context?: string; status?: string; [key: string]: unknown }
export interface Fact { derived?: boolean; value_state?: string; fact_id: string; metric: string; value_decimal: string; currency: string; period: string; entity_id: string; raw_value: string | number | null; raw_scale: string | number | null; source: Source | string | null }
export interface HistoryEntry { version?: number; title?: string; action?: string; note?: string; actor?: string; timestamp?: string; checks?: Check[]; [key: string]: unknown }
export interface PackSnapshot {
  pack_id: string; version: number; fund_id: string; title: string;
  execution_status: string; checks: Check[]; routing_status: string; review_status: string; freshness: string;
  facts: Fact[]; candidate: { artifact_id: string; total_decimal: string; download_url: string | null; released?: boolean; manifest_url?: string | null; content_hash?: string; total_label?: string; checked_version?: number } | null;
  history: HistoryEntry[];
  evidence?: Record<string, Source>; observations?: Record<string, unknown>[]; extraction_observations?: Record<string, unknown>[];
  dependency_edges?: [string, string][]; impact?: unknown; routing_reasons?: string[];
  routing_explanation?:{route:string;policy_version:string;reasons:string[];required_check_ids:string[];unsatisfied_check_ids:string[];required_check_coverage:[number,number];agreement:string;confidence:{status:string;value?:number;reason?:string};review_status:string};
  priority?:{status:'AVAILABLE'|'UNAVAILABLE';level:'HIGH'|'STANDARD'|null;policy_version:string|null;amount_decimal:string|null;materiality_decimal:string|null;currency:string|null;dependent_outputs:number|null;impact_threshold:number|null;reasons:string[]};
  policy_version?: string; execution_error?: string | null; publication?: unknown;
  publications?: unknown[]; review?: unknown; unresolved_soft_signals?: boolean; resolution?: {actor?:string;at?:string;reason:string;source_ids:string[];snapshot_digest?:string}|null;
}
export interface Session { username: string; role: string; csrf_token: string; scopes?: {tenant_id:string;fund_id:string;pack_id:string}[] }
export type Page = 'overview' | 'correction' | 'checks' | 'review';
export interface Correction { fact_id: string; value_decimal: string; reason: string; source_id: string; expected_version: number }
export const isCurrent = (pack: PackSnapshot) => ['CURRENT', 'FRESH'].includes(pack.freshness.toUpperCase());
export const isApproved = (pack: PackSnapshot) => isCurrent(pack) && ['APPROVED', 'PUBLISHED'].includes(pack.review_status.toUpperCase());
export function eligibleForReview(pack: PackSnapshot): boolean {
  const required = pack.checks.filter(c => c.required);
  return !(pack.unresolved_soft_signals && !pack.resolution) && !(pack.routing_status === 'NEEDS_REVIEW' && !pack.resolution) && required.length > 0 && required.every(c => c.status === 'PASS' || (c.status === 'NOT_APPLICABLE' && Boolean(c.justification || c.detail))) && isCurrent(pack) &&
    ['COMPLETED', 'SUCCEEDED', 'COMPLETE'].includes(pack.execution_status.toUpperCase()) &&
    ['READY_FOR_REVIEW', 'READY_FOR_QUICK_REVIEW', 'READY', 'REVIEW_REQUIRED', 'NEEDS_REVIEW'].includes(pack.routing_status.toUpperCase()) && Boolean(pack.candidate);
}
export function normalizeAmount(input: string): string {
  const raw = input.trim();
  if (!/^\d+(?:\.\d{1,2})?$/.test(raw)) throw new Error('Enter an amount such as 60000.00, without commas or a currency symbol.');
  const [whole, fraction = ''] = raw.split('.');
  const cents = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0'));
  if (cents > 2000000000n) throw new Error('Enter an amount between 0 and 20,000,000 USD.');
  return `${BigInt(whole)}.${fraction.padEnd(2, '0')}`;
}
export function formatDecimal(value: string | null | undefined, currency = ''): string {
  if (!value || !/^-?\d+(?:\.\d+)?$/.test(value)) return '—';
  const [whole, fraction] = value.split('.');
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return `${currency === 'USD' ? '$' : currency ? `${currency} ` : ''}${grouped}${fraction ? `.${fraction}` : ''}`;
}
export function formatFactValue(fact: Fact): string {
  return formatDecimal(fact.value_decimal, fact.metric === 'fee_rate' ? '' : fact.currency);
}
export const humanize = (value: string) => value.replace(/_/g, ' ').toLowerCase().replace(/^./, c => c.toUpperCase());
export function sourceOf(fact: Fact): Source { return typeof fact.source === 'string' ? { source_id: fact.source, document_name: fact.source } : fact.source ?? {}; }
export function safeDownloadURL(raw: string | null | undefined): string | null {
  if (!raw) return null;
  try { const url = new URL(raw, window.location.origin); return url.origin === window.location.origin && ['https:', 'http:'].includes(url.protocol) ? url.pathname + url.search : null; } catch { return null; }
}

export function locatorText(locator: Source['locator']): string {
  if (!locator) return 'Location unavailable';
  if (typeof locator === 'string') return locator;
  const sheet = locator.sheet ?? locator.sheet_name, cell = locator.cell ?? locator.coordinate;
  if (sheet || cell) return [sheet, cell].filter(Boolean).join('!');
  if (locator.original_page ?? locator.page) return 'Page ' + String(locator.original_page ?? locator.page) + (locator.bbox ? ' · ' + JSON.stringify(locator.bbox) : '');
  return Object.entries(locator).map(([key, value]) => key + ': ' + (typeof value === 'object' ? JSON.stringify(value) : String(value))).join(' · ');
}
export const canPrepare = (session: Session) => ['accountant', 'preparer', 'administrator'].includes(session.role.toLowerCase());
export const canReview = (session: Session) => session.role.toLowerCase() === 'reviewer';

// The API supports bounded decimal strings across currencies; story-only fee limits
// are deliberately separate from this general correction input.
export function normalizeCorrectionAmount(input:string):string {
 const raw=input.trim();
 if(!/^-?\d+(?:\.\d{1,12})?$/.test(raw))throw new Error('Enter a plain decimal amount, without commas, a currency symbol or exponent.');
 const negative=raw.startsWith('-'),unsigned=negative?raw.slice(1):raw;
 const [whole,fraction='']=unsigned.split('.');
 const trimmed=whole.replace(/^0+(?=\d)/,'');
 if((trimmed+fraction).replace(/^0+/,'').length>28)throw new Error('The amount exceeds the supported 28-digit precision.');
 return (negative && /[1-9]/.test(unsigned)?'-':'')+trimmed+(fraction?'.'+fraction:'.00');
}

export const snapshotVersion = (pack:PackSnapshot) => pack.candidate?.checked_version ?? pack.version;
