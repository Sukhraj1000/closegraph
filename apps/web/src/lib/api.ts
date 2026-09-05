import type { ReviewEventInput,ReviewWork } from '../features/packs/ReviewWork';
import type { Correction, PackSnapshot, Session } from './model';
import type { ResolutionInput, ReviewInput } from '../features/packs/ReviewDecision';
export class ApiError extends Error { constructor(public status:number,message:string){super(message);this.name='ApiError';} }
interface ServerSession { actor:{actor_id:string;role:string}; scopes:{tenant_id:string;fund_id:string;pack_id:string}[];csrf_token:string;collection_funds?:{tenant_id:string;fund_id:string}[] }
export interface UploadInput {expected_version:number;source_id:string;filename:string;media_type:string;content_base64:string}
function messageOf(body:unknown):string {
 if(!body||typeof body!=='object')return 'The server could not complete this request.';
 const detail=(body as Record<string,unknown>).detail??(body as Record<string,unknown>).message;
 if(typeof detail==='string')return detail;
 if(Array.isArray(detail))return detail.map(item=>{const d=item as Record<string,unknown>;return (Array.isArray(d.loc)?d.loc.slice(1).join('.')+': ':'')+String(d.msg??'Invalid request');}).join('; ');
 return 'The server could not complete this request.';
}
export class ClosegraphApi {
 private csrf='';
 private async request<T>(path:string,method='GET',body?:unknown,signal?:AbortSignal):Promise<T> {
  const headers:Record<string,string>={Accept:'application/json'};
  if(body!==undefined)headers['Content-Type']='application/json';
  if(method!=='GET'&&this.csrf)headers['X-CSRF-Token']=this.csrf;
  let response:Response;
  try{response=await fetch('/api'+path,{method,headers,credentials:'same-origin',body:body===undefined?undefined:JSON.stringify(body),signal});}
  catch(error){if((error as Error).name==='AbortError')throw error;throw new ApiError(0,'The local API is unavailable. Check its status and retry; your changes have not been confirmed.');}
  if(!response.ok){let body:unknown;try{body=await response.json();}catch{}throw new ApiError(response.status,messageOf(body));}
  if(response.status===204)return undefined as T;
  return response.json() as Promise<T>;
 }
 private acceptSession(data:ServerSession):Session {this.csrf=data.csrf_token;return {username:data.actor.actor_id,role:data.actor.role,scopes:data.scopes,collection_funds:data.collection_funds,csrf_token:data.csrf_token};}
 async session(){return this.acceptSession(await this.request<ServerSession>('/session'));}
 async login(username:string,password:string){return this.acceptSession(await this.request<ServerSession>('/session/login','POST',{username,password}));}
 async logout(){await this.request('/session/logout','POST',{});this.csrf='';}
 list(signal?:AbortSignal){return this.request<PackSnapshot[]>('/packs','GET',undefined,signal);}
 pack(id:string,signal?:AbortSignal){return this.request<PackSnapshot>('/packs/'+encodeURIComponent(id),'GET',undefined,signal);}
 private mutate(id:string,action:string,input:object){return this.request<PackSnapshot>('/packs/'+encodeURIComponent(id)+'/'+action,'POST',{...input,idempotency_key:crypto.randomUUID()});}
 reviewWork(id:string,signal?:AbortSignal){return this.request<ReviewWork>('/packs/'+encodeURIComponent(id)+'/review-work','GET',undefined,signal);}
 recordEvent(id:string,input:ReviewEventInput){return this.request('/packs/'+encodeURIComponent(id)+'/review-events','POST',{...input,idempotency_key:crypto.randomUUID()});}
 correct(id:string,input:Correction){return this.mutate(id,'corrections',input);}
 recompute(id:string,expected_version:number){return this.mutate(id,'recompute',{expected_version});}
 review(id:string,input:ReviewInput){return this.mutate(id,'review',input);}
 resolve(id:string,input:ResolutionInput){return this.mutate(id,'review/resolve',input);}
 reject(id:string,input:{expected_version:number;note:string}){return this.mutate(id,'review/reject',input);}
 publish(id:string,expected_version:number){return this.mutate(id,'publish',{expected_version});}
 upload(id:string,input:UploadInput){return this.mutate(id,'uploads',input);}
}
export async function fileBase64(file:File):Promise<string>{
 if(file.size>20*1024*1024)throw new Error('Choose a file of 20 MB or less.');
 const bytes=new Uint8Array(await file.arrayBuffer());let binary='';
 for(let i=0;i<bytes.length;i+=32768)binary+=String.fromCharCode(...bytes.subarray(i,i+32768));
 return btoa(binary);
}
