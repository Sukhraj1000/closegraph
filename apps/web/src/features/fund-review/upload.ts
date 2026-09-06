import {ApiError} from '../../lib/api';
import type {CollectionsApi} from '../collections/api';
import {processing} from '../collections/model';
import type {FundWork} from './api';

/** Refresh after file preparation, preserving the parent the uploader selected. */
export async function uploadPreparedFile(api:CollectionsApi,work:FundWork,file:Parameters<CollectionsApi['upload']>[2],options:Parameters<CollectionsApi['upload']>[3]):Promise<FundWork> {
 const latest=await api.get(work.id);
 if(work.access?.actor_id&&latest.access?.actor_id!==work.access.actor_id)throw new ApiError(403,'The signed-in account changed. Refresh your access before submitting this file.');
 if(processing(latest))throw new ApiError(409,'Checks are still running. Wait for the current review before uploading.');
 if(options?.document_id){const document=latest.documents?.find(item=>item.id===options.document_id);if(!document||document.current_revision_id!==options.parent_revision_id)throw new ApiError(409,'This document has a newer version. Inspect that version before submitting your replacement.');}
 // Keep both optimistic concurrency and the exact parent check on the server.
 // A conflict is shown to the user; this mutation is never automatically retried.
 return api.upload(latest.id,latest.version,file,options);
}
