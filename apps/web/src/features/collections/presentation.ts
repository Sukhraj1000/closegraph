import type { Collection, Dataset, EvidenceDocument } from './model';
export function documentsFor(collection:Collection):EvidenceDocument[]{
 if(collection.documents)return collection.documents;
 return collection.sources.map(source=>({id:source.document_id??source.id,title:source.filename,period:source.period,current_revision_id:source.id,revisions:[source.id]}));
}
export function revisionId(revision:EvidenceDocument['revisions'][number]){return typeof revision==='string'?revision:revision.source_id;}
export function datasetLabel(dataset:Dataset,index=0){
 if(!/^PDF block \d+$/.test(dataset.title))return dataset.title;
 return dataset.metadata?.structure==='text_block'?'Text section '+(index+1):'Table '+(index+1);
}
export function documentName(collection:Collection,id:string){return documentsFor(collection).find(d=>d.id===id)?.title??'Shared document';}
export function statusLabel(status:string){return ({NEEDS_REVIEW:'Needs review',READY_FOR_REVIEW:'Ready for approval',APPROVED:'Approved',ACCEPTED:'Data checked',QUEUED:'Waiting to read',PROCESSING:'Reading documents',EMPTY:'Getting started',BLOCKED:'Needs attention',PASS:'Passed',FAIL:'Check failed',ERROR:'Unable to check',MISSING_EVIDENCE:'Missing evidence',NOT_RUN:'Not checked',pending_manager_release:'Awaiting manager release',evidence_received:'Evidence received',verification_pending:'Verification requested',open:'Open',acknowledged:'Acknowledged',resolved:'Resolved'} as Record<string,string>)[status]??status.replace(/_/g,' ').replace(/^./,x=>x.toUpperCase());}

