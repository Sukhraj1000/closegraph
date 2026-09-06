import {ApiError} from '../../lib/api';
import type {Collection, Column, DataRow} from '../collections/model';
export interface CheckSide {dataset_id:string;header_row_id?:string|null;column?:string;columns?:string[];group_by?:string[];number_format?:'dot_decimal'|'comma_decimal'}
export interface ReviewCheck {id:string;title:string;kind:'reference'|'required'|'unique'|'totals';confirmed:boolean;left:CheckSide;right?:CheckSide;tolerance?:string;rationale?:string;overlap?:{matched_distinct:number;source_distinct:number;reference_distinct:number}}
export interface ReviewConfig {checks:ReviewCheck[];confirmed_source_ids:string[];table_headers?:{dataset_id:string;header_row_id:string|null}[]}
export interface TableProfile {source_name?:string;dataset_id:string;source_id:string;document_id?:string;title:string;row_count:number;data_row_count?:number;header_row_id?:string|null;header_status?:string;header_candidates?:{row_id:string;labels:string[]}[];columns:(Column&{concept?:string})[];preview:DataRow[];issues?:string[];coverage?:Record<string,unknown>}
export interface FindingEvidence {dataset_id?:string;source_id?:string;document_id?:string;row_id?:string;column?:string;column_key?:string;raw_value?:unknown;locator?:Record<string,unknown>}
export interface Finding {id:string;match_key:string;status:'difference'|'needs_input'|'passed';title:string;explanation:string;check_id?:string;kind:string;affected_count?:number;evidence:FindingEvidence[];operands?:unknown;expected?:unknown;observed?:unknown;evidence_total?:number}
export interface FundRun {scope_note?:string;status:string;config:ReviewConfig;summary?:Record<string,unknown>;coverage?:Record<string,unknown>;changes?:Record<string,unknown>;review?:{decision?:string;reason?:string};stale?:boolean}
export type FundWork=Collection&{contributors?:string[];fund_review?:FundRun;reconciliation?:unknown;processing?:{stage:string;completed_documents:number;total_documents:number}};
export interface BriefResults {tables:TableProfile[];suggestions:ReviewCheck[];findings:Finding[];total:number;summary:Record<string,unknown>;coverage:Record<string,unknown>;changes:Record<string,unknown>;stale?:boolean;version?:number}
export const emptyConfig=():ReviewConfig=>({checks:[],confirmed_source_ids:[]});
export class FundReviewApi {
 constructor(private csrf:string){}
 private async request<T>(id:string,suffix:string,body?:unknown):Promise<T>{
  let response:Response;
  try{response=await fetch('/api/collections/'+encodeURIComponent(id)+suffix,{method:body?'POST':'GET',credentials:'same-origin',headers:{Accept:'application/json',...(body?{'Content-Type':'application/json','X-CSRF-Token':this.csrf}:{})},body:body?JSON.stringify(body):undefined});}
  catch{throw new ApiError(0,'The connection was interrupted. Refresh to see what was saved before retrying.');}
  if(!response.ok){let detail:unknown;try{detail=(await response.json()).detail;}catch{}throw new ApiError(response.status,typeof detail==='string'?detail:Array.isArray(detail)?detail.map(value=>String(value.msg??'Invalid selection')).join('; '):'This action could not be completed. Refresh and try again.');}
  return response.json();
 }
 start(work:FundWork,config:ReviewConfig,reason:string){return this.request<FundWork>(work.id,'/fund-review',{expected_version:work.version,config,reason,idempotency_key:crypto.randomUUID()});}
 results(id:string,status='',q='',offset=0){return this.request<BriefResults>(id,'/fund-review/results?'+new URLSearchParams({...status?{status}:{},q,offset:String(offset),limit:'50'}));}
 assign(work:FundWork,item_ids:string[],owner_actor_id:string,reason:string,due_at?:string){return this.request<FundWork>(work.id,'/fund-review/assign',{expected_version:work.version,item_ids,owner_actor_id,reason,...due_at?{due_at}:{}});}
 review(work:FundWork,decision:'APPROVE'|'REJECT',reason:string){return this.request<FundWork>(work.id,'/fund-review/review',{expected_version:work.version,decision,reason});}
 read(id:string,notification_ids:string[]){return this.request<FundWork>(id,'/notifications/read',{notification_ids});}
 download(id:string,reviewed=false){return '/api/collections/'+encodeURIComponent(id)+'/fund-review/download?reviewed='+reviewed;}
}
