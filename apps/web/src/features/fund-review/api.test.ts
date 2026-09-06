import {afterEach,describe,it,expect,vi} from 'vitest';
import {FundReviewApi} from './api';
afterEach(()=>vi.restoreAllMocks());
describe('fund review results request contract',()=>{
 it('omits an empty status rather than sending an invalid literal',async()=>{const fetcher=vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response('{}'));await new FundReviewApi('csrf').results('review/a','','source value',50);const query=new URL(String(fetcher.mock.calls[0][0]),'http://localhost');expect(query.pathname).toBe('/api/collections/review%2Fa/fund-review/results');expect(query.searchParams.has('status')).toBe(false);expect(query.searchParams.get('q')).toBe('source value');expect(query.searchParams.get('offset')).toBe('50');});
 it('sends an explicitly selected status',async()=>{const fetcher=vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response('{}'));await new FundReviewApi('csrf').results('review','difference');expect(new URL(String(fetcher.mock.calls[0][0]),'http://localhost').searchParams.get('status')).toBe('difference');});
});
