import { ApiError } from '../../lib/api';
import type { Collection, CollectionMember, ComparisonPage, Edit, Recipe, Requirement, RowPage } from './model';
const path = (id:string) => '/collections/'+encodeURIComponent(id);
function requestKey(value:string){if(value.length>200)throw new Error('This request identifier exceeds the supported length.');return value;}
export class CollectionsApi {
 constructor(private csrf:string){}
 private async request<T>(route:string,method='GET',body?:unknown,signal?:AbortSignal):Promise<T>{
  let response:Response;
  try{response=await fetch('/api'+route,{method,credentials:'same-origin',headers:{Accept:'application/json',...(body===undefined?{}:{'Content-Type':'application/json'}),...(method==='GET'?{}:{'X-CSRF-Token':this.csrf})},body:body===undefined?undefined:JSON.stringify(body),signal});}
  catch(error){if((error as Error).name==='AbortError')throw error;throw new ApiError(0,'The API is unavailable. Refresh to confirm the latest saved version before retrying.');}
  if(!response.ok){let detail:unknown;try{detail=(await response.json()).detail;}catch{}const message=typeof detail==='string'?detail:Array.isArray(detail)?detail.map(item=>String(item.msg??'Invalid request')).join('; '):'The collection request could not be completed.';throw new ApiError(response.status,message);}
  return response.status===204?undefined as T:response.json() as Promise<T>;
 }
 list(signal?:AbortSignal){return this.request<Collection[]>('/collections','GET',undefined,signal);}
 get(id:string,signal?:AbortSignal){return this.request<Collection>(path(id),'GET',undefined,signal);}
 create(title:string,fund_id:string){return this.request<Collection>('/collections','POST',{title,fund_id});}
 upload(id:string,expected_version:number,file:{filename:string;media_type:string;content_base64:string},options?:{document_id?:string;parent_revision_id?:string;reason?:string;period?:string;as_of?:string;idempotency_key?:string;task_id?:string;side?:'statement'|'journal';defer_processing?:boolean}){return this.request<Collection>(path(id)+'/sources','POST',{expected_version,...file,...options});}
 requirements(id:string,expected_version:number,requirements:Requirement[]){return this.request<Collection>(path(id)+'/requirements','PUT',{expected_version,requirements});}
 evaluate(id:string,expected_version:number){return this.request<Collection>(path(id)+'/evaluate','POST',{expected_version});}
 taskAction(id:string,expected_version:number,taskId:string,action:string,reason:string,source_id?:string){return this.request<Collection>(path(id)+'/tasks/'+encodeURIComponent(taskId)+'/actions','POST',{expected_version,action,reason,idempotency_key:requestKey('action:'+taskId+':'+action+':'+expected_version),...(source_id?{source_id}:{})});}
 flag(id:string,expected_version:number,details:{title:string;reason:string;document_ids:string[];owner_party?:string;owner_actor_id:string;blocking?:boolean;idempotency_key?:string}){if(!details.owner_actor_id.trim())return Promise.reject(new Error('Choose a responsible person for this concern.'));return this.request<Collection>(path(id)+'/flags','POST',{expected_version,title:details.title,reason:details.reason,owner_actor_id:details.owner_actor_id,...(details.document_ids[0]?{document_id:details.document_ids[0]}:{}),...(details.blocking===undefined?{}:{blocking:details.blocking}),idempotency_key:requestKey(details.idempotency_key||'flag:'+id+':'+expected_version)});}
 comparison(id:string,comparisonId:string,offset=0,limit=50,signal?:AbortSignal){return this.request<ComparisonPage>(path(id)+'/comparisons/'+encodeURIComponent(comparisonId)+'?offset='+offset+'&limit='+limit,'GET',undefined,signal);}
 participants(id:string,signal?:AbortSignal){return this.request<CollectionMember[]>(path(id)+'/participants','GET',undefined,signal);}
 members(id:string,expected_version:number,members:CollectionMember[]){return this.request<Collection>(path(id)+'/members','PUT',{expected_version,members});}
 verifyCoverage(id:string,expected_version:number,sourceId:string,reason:string){return this.request<Collection>(path(id)+'/sources/'+encodeURIComponent(sourceId)+'/verify-coverage','POST',{expected_version,reason});}
 reviewComparison(id:string,expected_version:number,comparisonId:string,reason:string){return this.request<Collection>(path(id)+'/comparisons/'+encodeURIComponent(comparisonId)+'/review','POST',{expected_version,reason});}
 documentKeys(id:string,expected_version:number,documentId:string,business_keys:Record<string,{columns:string[];header_row:number}>){return this.request<Collection>(path(id)+'/documents/'+encodeURIComponent(documentId),'PUT',{expected_version,business_keys});}
 process(id:string,expected_version:number,options?:{stage:'extract';source_id:string}){return this.request<Collection>(path(id)+'/process','POST',{expected_version,...options});}
 rows(id:string,dataset:string,offset=0,limit=50,signal?:AbortSignal,row_id?:string){const query=new URLSearchParams({offset:String(offset),limit:String(limit),...(row_id?{row_id}:{})});return this.request<RowPage>(path(id)+'/datasets/'+encodeURIComponent(dataset)+'/rows?'+query,'GET',undefined,signal);}
 edit(id:string,expected_version:number,dataset_id:string,edits:Edit[],reason:string){return this.request<Collection>(path(id)+'/edits','POST',{expected_version,dataset_id,edits,reason});}
 accept(id:string,expected_version:number,dataset_id?:string){return this.request<Collection>(path(id)+'/accept','POST',{expected_version,...(dataset_id?{dataset_id}:{})});}
 recipe(id:string,expected_version:number,recipe:Recipe){return this.request<Collection>(path(id)+'/recipe','PUT',{expected_version,recipe});}
 review(id:string,expected_version:number,decision:'APPROVE'|'REJECT',reason:string){return this.request<Collection>(path(id)+'/review','POST',{expected_version,decision,reason});}
 export(id:string,expected_version:number,dataset_id:string,format:'csv'|'xlsx',options?:{template_source_id?:string;bindings?:unknown}){return this.request<{artifact_id:string;url:string;filename:string;manifest_url?:string}>(path(id)+'/exports','POST',{expected_version,dataset_id,format,...options});}
 history(id:string,signal?:AbortSignal){return this.request<Record<string,unknown>[]>(path(id)+'/history','GET',undefined,signal);}
 sourceUrl(id:string,source:string){return '/api'+path(id)+'/sources/'+encodeURIComponent(source)+'/download';}
}
export async function collectionFile(file:File){
 const extension=file.name.split('.').pop()?.toLowerCase();
 const media_type=extension==='pdf'?'application/pdf':extension==='xlsx'?'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':extension==='csv'?'text/csv':null;
 if(!media_type)throw new Error(file.name+': choose PDF, CSV or XLSX files.');
 if(file.size>32*1024*1024)throw new Error(file.name+': the upload limit is 32 MB. Split the source before uploading.');
 const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=32768)binary+=String.fromCharCode(...bytes.subarray(i,i+32768));
 return {filename:file.name,media_type,content_base64:btoa(binary)};
}
