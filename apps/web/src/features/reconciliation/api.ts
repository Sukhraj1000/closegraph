import { ApiError } from '../../lib/api';
import type { Collection } from '../collections/model';
export type Side='statement'|'journal';
export interface Mapping {dataset_id:string;dataset_ids?:string[];direction?:{column:string;signs:Record<string,number>};lookups?:{table_id:string;key_column:string;value_column:string;source_column:string;target:string}[];columns:Record<string,string>;header_row_id?:string;account?:string;currency?:string;date_format?:string;number_format?:string;cash_leg?:{column:string;values:string[]};cash_leg_confirmed?:boolean;exclude?:boolean;reason?:string}
export interface Suggestion {dataset_id:string;group_id?:string;dataset_ids?:string[];kind?:string;context?:{account?:string;currency?:string};side:Side;title:string;columns:Record<string,string>;header_row_id?:string;status:string;issues:string[];preview:Record<string,unknown>[]}
export interface Run {status:string;summary:Record<string,number>;suggestions:Suggestion[];source_sides:Record<string,Side>;config:{mappings?:Mapping[];composite_confirmed?:boolean;match_mode?:string;confirmed_source_ids?:string[]};review?:{decision?:string};coverage?:Record<string,unknown>}
export type Work=Collection&{processing?:{stage:string;completed_documents:number;total_documents:number};reconciliation?:Run};
export interface ResultItem {id:string;status:string;message?:string;reason?:string;statement?:Record<string,unknown>[];journal?:Record<string,unknown>[];difference?:string;[key:string]:unknown}
export interface Results {items:ResultItem[];total:number;summary:Record<string,number>;coverage:Record<string,unknown>}
export class ReconciliationApi {
 constructor(private csrf:string){}
 private async request<T>(id:string,suffix:string,body?:unknown):Promise<T>{const r=await fetch('/api/collections/'+encodeURIComponent(id)+suffix,{method:body?'POST':'GET',credentials:'same-origin',headers:{Accept:'application/json',...(body?{'Content-Type':'application/json','X-CSRF-Token':this.csrf}:{})},body:body?JSON.stringify(body):undefined});if(!r.ok){let detail;try{detail=(await r.json()).detail;}catch{}throw new ApiError(r.status,typeof detail==='string'?detail:'This action could not be completed. Refresh and try again.');}return r.json();}
 start(work:Work,source_sides:Record<string,Side>,config:Run['config'],reason='Reconcile the selected documents'){return this.request<Work>(work.id,'/reconciliation',{expected_version:work.version,source_sides,config,reason});}
 results(id:string,status:string,q:string,offset:number){return this.request<Results>(id,'/reconciliation/results?'+new URLSearchParams({...status?{status}:{},q,offset:String(offset),limit:'50'}));}
 review(work:Work,decision:string,reason:string){return this.request<Work>(work.id,'/reconciliation/review',{expected_version:work.version,decision,reason});}
 assign(work:Work,item_ids:string[],owner_actor_id:string,reason:string,due_at?:string){return this.request<Work>(work.id,'/reconciliation/assign',{expected_version:work.version,item_ids,owner_actor_id,reason,...due_at?{due_at}:{}});}
 read(id:string,notification_ids:string[]){return this.request<Work>(id,'/notifications/read',{notification_ids});}
 download(id:string,reviewed=false){return '/api/collections/'+encodeURIComponent(id)+'/reconciliation/download?reviewed='+reviewed;}
}
