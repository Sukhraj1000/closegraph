import { afterEach, describe, expect, it, vi } from 'vitest';
import { CollectionsApi, collectionFile } from './api';
afterEach(()=>vi.restoreAllMocks());
describe('scoped collection API',()=>{
 it('sends CSRF and expected revision with explicit edits',async()=>{const fetcher=vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response('{}',{status:200}));await new CollectionsApi('scoped-csrf').edit('collection/a',9,'data-1',[{op:'mark_unresolved',message:'Inspect original'}],'Original differs');expect(fetcher).toHaveBeenCalledWith('/api/collections/collection%2Fa/edits',expect.objectContaining({method:'POST',credentials:'same-origin',headers:expect.objectContaining({'X-CSRF-Token':'scoped-csrf'}),body:JSON.stringify({expected_version:9,dataset_id:'data-1',edits:[{op:'mark_unresolved',message:'Inspect original'}],reason:'Original differs'})}));});
 it('uses row IDs for issue navigation instead of assuming an index',async()=>{const fetcher=vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response('{}'));await new CollectionsApi('csrf').rows('col','data',0,50,undefined,'row/unknown');expect(fetcher.mock.calls[0][0]).toBe('/api/collections/col/datasets/data/rows?offset=0&limit=50&row_id=row%2Funknown');});
 it('preserves conflict status for explicit stale handling',async()=>{vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response(JSON.stringify({detail:'Another correction was saved'}),{status:409}));await expect(new CollectionsApi('csrf').accept('col',4,'table')).rejects.toMatchObject({status:409,message:'Another correction was saved'});});
 it('refuses unsupported formats and oversized files before encoding',async()=>{await expect(collectionFile(new File(['x'],'commands.exe'))).rejects.toThrow('PDF, CSV or XLSX');const file=new File(['x'],'large.csv');Object.defineProperty(file,'size',{value:33*1024*1024});await expect(collectionFile(file)).rejects.toThrow('32 MB');});
 it('serializes manual concerns to the strict singular-document contract with a stable retry key',async()=>{
  const fetcher=vi.spyOn(globalThis,'fetch').mockImplementation(async()=>new Response('{}',{status:200})),api=new CollectionsApi('csrf');
  const details={title:'Check this value',reason:'The source appears inconsistent.',document_ids:['doc-1'],owner_party:'investor',owner_actor_id:'manager-1'};
  await api.flag('collection/a',9,details);await api.flag('collection/a',9,details);
  expect(fetcher.mock.calls[0][0]).toBe('/api/collections/collection%2Fa/flags');
  expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body))).toEqual({expected_version:9,title:'Check this value',reason:'The source appears inconsistent.',owner_actor_id:'manager-1',document_id:'doc-1',idempotency_key:'flag:collection/a:9'});
  expect(fetcher.mock.calls[0][1]?.body).toBe(fetcher.mock.calls[1][1]?.body);
 });
 it('requires a manual concern owner and omits an absent document instead of sending a list',async()=>{
  const fetcher=vi.spyOn(globalThis,'fetch').mockImplementation(async()=>new Response('{}'));
  await expect(new CollectionsApi('csrf').flag('col',4,{title:'Missing evidence',reason:'Please investigate.',document_ids:[],owner_actor_id:''})).rejects.toThrow('responsible person');expect(fetcher).not.toHaveBeenCalled();
  await new CollectionsApi('csrf').flag('col',4,{title:'Missing evidence',reason:'Please investigate.',document_ids:[],owner_actor_id:'manager'});
  expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body))).toEqual({expected_version:4,title:'Missing evidence',reason:'Please investigate.',owner_actor_id:'manager',idempotency_key:'flag:col:4'});
 });
 it('uses the same action retry key for the same task action and revision',async()=>{
  const fetcher=vi.spyOn(globalThis,'fetch').mockImplementation(async()=>new Response('{}')),api=new CollectionsApi('csrf');
  await api.taskAction('col',7,'task-1','make_blocking','Must be resolved before release.');await api.taskAction('col',7,'task-1','make_blocking','Must be resolved before release.');
  expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body))).toEqual({expected_version:7,action:'make_blocking',reason:'Must be resolved before release.',idempotency_key:'action:task-1:make_blocking:7'});
  expect(fetcher.mock.calls[0][1]?.body).toBe(fetcher.mock.calls[1][1]?.body);
 });

});
