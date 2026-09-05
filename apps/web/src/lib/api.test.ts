import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, ClosegraphApi } from './api';
const serverSession={actor:{actor_id:'independent-reviewer',role:'reviewer'},scopes:[{tenant_id:'t',fund_id:'f',pack_id:'p'}],csrf_token:'server-token'};
describe('scoped API client',()=>{
 beforeEach(()=>{vi.restoreAllMocks();});
 it('uses only server session authority and sends CSRF on writes',async()=>{
  const fetchMock=vi.spyOn(globalThis,'fetch').mockResolvedValueOnce(new Response(JSON.stringify(serverSession),{status:200})).mockResolvedValueOnce(new Response(JSON.stringify({pack_id:'p'}),{status:200}));
  const api=new ClosegraphApi(),session=await api.login('person','secret');
  expect(session.role).toBe('reviewer');
  await api.correct('p',{expected_version:2,fact_id:'fee',value_decimal:'60000.00',source_id:'fee-rule',reason:'Source supports it'});
  const [url,request]=fetchMock.mock.calls[1];
  expect(url).toBe('/api/packs/p/corrections');
  expect(request?.credentials).toBe('same-origin');
  expect(request?.headers).toMatchObject({'X-CSRF-Token':'server-token'});
  const body=JSON.parse(String(request?.body));
  expect(body.value_decimal).toBe('60000.00');expect(body.role).toBeUndefined();expect(body.checks).toBeUndefined();expect(body.idempotency_key).toBeTruthy();
 });
 it('preserves server stale-version diagnostics and never substitutes data',async()=>{
  vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response(JSON.stringify({detail:'Version changed; refresh before approval'}),{status:409}));
  await expect(new ClosegraphApi().pack('p')).rejects.toMatchObject({status:409,message:'Version changed; refresh before approval'});
 });
 it('reports unavailable processing without manufactured responses',async()=>{
  vi.spyOn(globalThis,'fetch').mockRejectedValue(new TypeError('offline'));
  await expect(new ClosegraphApi().pack('p')).rejects.toBeInstanceOf(ApiError);
 });
});
