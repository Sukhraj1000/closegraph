import {afterEach,describe,expect,it,vi} from 'vitest';
import {ApiError} from '../../lib/api';
import {CollectionsApi} from '../collections/api';
import {uploadPreparedFile} from './upload';
import type {FundWork} from './api';

afterEach(()=>vi.restoreAllMocks());
const work={id:'review',version:3,status:'NEEDS_REVIEW',access:{actor_id:'accountant'},documents:[{id:'report',current_revision_id:'original'}]} as unknown as FundWork;
const file={filename:'Reporting.csv',media_type:'text/csv',content_base64:'YSxiCg=='};
const options={document_id:'report',parent_revision_id:'original',reason:'Updated reporting evidence',idempotency_key:'same-submission',defer_processing:true};
describe('fund document upload concurrency',()=>{
 it('uses the current collection version after file preparation and retains the selected parent',async()=>{const api=new CollectionsApi('csrf');const latest={...work,version:8};vi.spyOn(api,'get').mockResolvedValue(latest);const upload=vi.spyOn(api,'upload').mockResolvedValue({...latest,version:9});await uploadPreparedFile(api,work,file,options);expect(upload).toHaveBeenCalledOnce();expect(upload).toHaveBeenCalledWith('review',8,file,options);});
 it('does not silently rebase a replacement onto another submitted revision',async()=>{const api=new CollectionsApi('csrf');vi.spyOn(api,'get').mockResolvedValue({...work,version:8,documents:[{id:'report',title:'Report',current_revision_id:'someone-elses-revision',revisions:['original','someone-elses-revision']}]});const upload=vi.spyOn(api,'upload');await expect(uploadPreparedFile(api,work,file,options)).rejects.toThrow('This document has a newer version');expect(upload).not.toHaveBeenCalled();});
 it('never retries the mutation if state changes after the preflight read',async()=>{const api=new CollectionsApi('csrf');const read=vi.spyOn(api,'get').mockResolvedValue({...work,version:8});const upload=vi.spyOn(api,'upload').mockRejectedValue(new ApiError(409,'Collection changed; refresh before uploading'));await expect(uploadPreparedFile(api,work,file,options)).rejects.toThrow('Collection changed');expect(read).toHaveBeenCalledOnce();expect(upload).toHaveBeenCalledOnce();});
 it('does not submit the file under a changed account',async()=>{const api=new CollectionsApi('csrf');vi.spyOn(api,'get').mockResolvedValue({...work,version:8,access:{...work.access!,actor_id:'someone-else'}});const upload=vi.spyOn(api,'upload');await expect(uploadPreparedFile(api,work,file,options)).rejects.toThrow('The signed-in account changed');expect(upload).not.toHaveBeenCalled();});
});
