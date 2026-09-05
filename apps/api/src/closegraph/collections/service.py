"""Versioned collection workflow. Parsers propose; people accept; code transforms."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import base64
import json
import re
from uuid import uuid4

from sqlalchemy import select
from closegraph.api.ports import DomainConflict, DomainForbidden, DomainNotFound
from closegraph.contracts import Scope
from closegraph.services.repository import ScopedBlobs
from .models import CollectionRow, CollectionRevisionRow, CollectionJobRow


def now(): return datetime.now(timezone.utc).isoformat()
def uid(prefix): return prefix+'-'+uuid4().hex

def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()

def issue(code, message, **fields):
    return {'id':uid('issue'),'severity':'error','code':code,'message':message,**fields}


def snapshot_digest(state):
    return sha256(encoded({k:state.get(k) for k in ('sources','datasets','issues','recipe','candidates')})).hexdigest()


class CollectionServices:
    def __init__(self, sessions, blobs, auth, *, pdf_provider=None):
        self.sessions, self.blob_store, self.auth, self.pdf_provider = sessions, blobs, auth, pdf_provider

    def _scope(self, state):
        return Scope(tenant_id=state['tenant_id'], fund_id=state['fund_id'], pack_id=state['id'])

    def _blobs(self, state): return ScopedBlobs(self.blob_store, self._scope(state))

    def _store(self, state, obj): return self._blobs(state).put(encoded(obj))

    def _table(self, state, dataset):
        return json.loads(self._blobs(state).get(dataset['data_hash']))

    def _dataset(self, state, identity):
        found=next((d for d in state['datasets'] if d['id']==identity or d['table_id']==identity),None)
        if not found: raise DomainNotFound()
        return found

    def _public(self, state):
        value=deepcopy(state)
        for d in value['datasets']: d.pop('data_hash',None);d.pop('original_hash',None)
        for s in value['sources']: s.pop('content_hash',None)
        for c in value['candidates']:
            c.pop('content_hash',None)
            c.pop('manifest_hash',None)
            c['url']='/api/collections/'+value['id']+'/candidates/'+c['candidate_id']
        for a in value['artifacts']:a.pop('content_hash',None)
        value.pop('tenant_id',None)
        value['summary']={'source_count':len(value['sources']), 'dataset_count':len(value['datasets']),
            'row_count':sum(d['row_count'] for d in value['datasets'] if d['kind']=='extraction'),
            'accepted_datasets':sum(d['accepted'] for d in value['datasets'] if d['kind']=='extraction'),
            'open_issues':sum(not i.get('resolved') for i in value['issues']),
            'error_count':sum(i['severity']=='error' and not i.get('resolved') for i in value['issues'])}
        return value

    def _revision(self, session, row, state, actor, event, detail=None, *, initial=False):
        state['version']=1 if initial else row.version+1
        state['updated_at']=now()
        state['history']=[*state.get('history',[]),{'version':state['version'],'actor_id':actor,'event':event,'at':state['updated_at'],'detail':detail or {}}][-200:]
        row.version=state['version'];row.state=deepcopy(state)
        session.add(CollectionRevisionRow(collection_id=row.id,version=row.version,actor_id=actor,event_type=event,detail=detail or {},state=deepcopy(state)))
        session.flush()

    @contextmanager
    def _locked(self, identity, actor, action, expected=None):
        # Check grants and hold authority lock until the database commit completes.
        with self.auth.collection_authorized(actor, action=action) as grants:
            with self.sessions() as session, session.begin():
                row=session.scalar(select(CollectionRow).where(CollectionRow.id==identity).with_for_update())
                if row is None or (row.tenant_id,row.fund_id) not in grants: raise DomainNotFound()
                if expected is not None and expected!=row.version: raise DomainConflict('Collection changed; refresh before continuing')
                yield session,row,deepcopy(row.state)

    def list(self, actor):
        with self.auth.collection_authorized(actor,action='inspect') as grants:
            with self.sessions() as session:
                rows=session.scalars(select(CollectionRow).order_by(CollectionRow.created_at.desc())).all()
                return [self._public(r.state) for r in rows if (r.tenant_id,r.fund_id) in grants]

    def create(self, actor, title, fund_id):
        if not isinstance(title,str) or not title.strip() or len(title)>200:raise ValueError('Collection title cannot be blank or exceed 200 characters')
        title=title.strip()
        with self.auth.collection_authorized(actor,action='prepare') as grants:
            pairs=[g for g in grants if g[1]==fund_id]
            if len(pairs)!=1: raise DomainForbidden()
            tenant,fund=pairs[0];identity=uid('collection')
            state={'id':identity,'tenant_id':tenant,'fund_id':fund,'title':title,'version':1,'status':'EMPTY','sources':[],'datasets':[],'issues':[],'recipe':None,'steps':[],'history':[],'review':None,'artifacts':[],'candidates':[],'contributors':[actor]}
            with self.sessions() as session,session.begin():
                row=CollectionRow(id=identity,tenant_id=tenant,fund_id=fund,version=1,state=state);session.add(row);session.flush()
                self._revision(session,row,state,actor,'created',initial=True)
            return self._public(state)

    def get(self, identity, actor):
        with self._locked(identity,actor,'inspect') as (_,_,state): return self._public(state)

    def history(self, identity, actor):
        with self._locked(identity,actor,'inspect') as (session,row,state):
            return [{'version':r.version,'actor_id':r.actor_id,'event':r.event_type,'detail':r.detail,'at':r.created_at.isoformat()} for r in session.scalars(select(CollectionRevisionRow).where(CollectionRevisionRow.collection_id==identity).order_by(CollectionRevisionRow.version)).all()]

    def rows(self, identity, actor, dataset_id, offset=0, limit=100, row_id=None):
        with self._locked(identity,actor,'inspect') as (_,_,state):
            dataset=self._dataset(state,dataset_id);table=self._table(state,dataset)
            position=None
            if row_id is not None:
                position=next((i for i,r in enumerate(table['rows']) if r['row_id']==row_id),None)
                if position is None: raise DomainNotFound()
                offset=position//limit*limit
            return {'dataset_id':dataset['id'],'columns':table['columns'],'rows':table['rows'][offset:offset+limit], 'total':len(table['rows']),'offset':offset,'limit':limit,'offset_of_row':position,'version':dataset['version']}

    def _invalidate(self,state,actor):
        state['datasets']=[d for d in state['datasets'] if d['kind']=='extraction']
        state['issues']=[i for i in state['issues'] if i.get('stage')!='transform' and i['code']!='processing_failed']
        state['review']=None;state['candidates']=[];state['steps']=[]
        state['contributors']=sorted(set(state['contributors'])|{actor})
        # Past downloads retain immutable history but cannot authorize a new revision.
        for artifact in state['artifacts']:artifact['historical']=True

    def _queue(self,session,row,state,kind):
        job=CollectionJobRow(id=uid('job'),collection_id=row.id,version=state['version'],kind=kind,status='PENDING',snapshot=deepcopy(state))
        session.add(job)

    def _idle(self,state):
        if state['status'] in ('QUEUED','PROCESSING'):raise DomainConflict('Processing is queued or running; wait for its result')

    def upload(self,identity,actor,expected,filename,media_type,content_base64):
        try: content=base64.b64decode(content_base64,validate=True)
        except (ValueError,TypeError) as exc:raise ValueError('Invalid base64 source') from exc
        if not content or len(content)>32*1024*1024:raise ValueError('Source must contain 1..33554432 bytes')
        suffix=filename.rsplit('.',1)[-1].lower()
        expected_types={'csv':'text/csv','xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','pdf':'application/pdf'}
        if expected_types.get(suffix)!=media_type:raise ValueError('Supported source types are CSV, XLSX and PDF')
        with self._locked(identity,actor,'prepare',expected) as (session,row,state):
            key=self._blobs(state).put(content);source_id=uid('source')
            state['sources'].append({'id':source_id,'filename':filename,'media_type':media_type,'content_hash':key,'byte_size':len(content),'status':'PENDING','uploaded_by':actor})
            self._invalidate(state,actor);state['status']='QUEUED'
            self._revision(session,row,state,actor,'source_uploaded',{'source_id':source_id,'filename':filename,'sha256':key})
            self._queue(session,row,state,'extract')
            return self._public(state)

    def process(self,identity,actor,expected,stage=None,source_id=None):
        with self._locked(identity,actor,'prepare',expected) as (session,row,state):
            self._idle(state)
            if not state['sources']:raise DomainConflict('Upload at least one source')
            if source_id and stage!='extract':raise ValueError('A source retry requires stage extract')
            if stage=='extract':
                sources=[s for s in state['sources'] if source_id is None or s['id']==source_id]
                if not sources:raise DomainNotFound()
                for source in sources:source['status']='PENDING'
            pending=any(s['status']!='EXTRACTED' for s in state['sources'])
            kind='extract' if pending else 'transform'
            if kind=='transform':
                inputs=[d for d in state['datasets'] if d['kind']=='extraction']
                if not inputs or any(not d['accepted'] for d in inputs):raise DomainConflict('Check and accept the extracted datasets first')
                if not state['recipe']:raise DomainConflict('Define a transformation recipe first')
                if any(i['severity']=='error' and not i.get('resolved') for i in state['issues'] if i.get('stage')!='transform'):raise DomainConflict('Resolve extraction errors before transforming')
            self._invalidate(state,actor);state['status']='QUEUED'
            self._revision(session,row,state,actor,'processing_requested',{'kind':kind});self._queue(session,row,state,kind)
            return self._public(state)

    def edit(self,identity,actor,expected,dataset_id,edits,reason):
        from .editing import apply_edits
        with self._locked(identity,actor,'prepare',expected) as (session,row,state):
            self._idle(state)
            dataset=self._dataset(state,dataset_id)
            if dataset['kind']!='extraction':raise DomainConflict('Correct source data or the recipe, then rerun outputs')
            table=self._table(state,dataset)
            related=[self._table(state,d) for d in state['datasets'] if d['kind']=='extraction' and d['source_id']==dataset['source_id'] and d['id']!=dataset['id']]
            applied=apply_edits(table,edits,state['issues'],reason,actor,related_tables=related)
            dataset['data_hash']=self._store(state,table);dataset['columns']=table['columns'];dataset['row_count']=len(table['rows']);dataset['version']+=1;dataset['accepted']=False
            dataset['metadata']=table.get('metadata',{})
            for source in state['sources']:source['issues']=[i for i in state['issues'] if i.get('source_id')==source['id'] and i.get('stage')!='transform']
            self._invalidate(state,actor);state['status']='NEEDS_REVIEW'
            self._revision(session,row,state,actor,'extraction_corrected',{'dataset_id':dataset_id,'reason':reason,'edits':applied})
            return self._public(state)

    def accept(self,identity,actor,expected,dataset_id=None):
        with self._locked(identity,actor,'prepare',expected) as (session,row,state):
            self._idle(state)
            selected=[self._dataset(state,dataset_id)] if dataset_id else [d for d in state['datasets'] if d['kind']=='extraction']
            if not selected or any(d['kind']!='extraction' for d in selected):raise DomainConflict('No extraction dataset to accept')
            for d in selected:
                for i in state['issues']:
                    if i.get('resolved') or i['severity']!='error' or i.get('stage')=='transform':continue
                    if i.get('table_id') in (None,d['table_id']) and i.get('source_id') in (None,d['source_id']):raise DomainConflict('Resolve the extraction error before accepting this dataset: '+i['message'])
                d['accepted']=True;d['accepted_by']=actor;d['accepted_hash']=d['data_hash'];d['accepted_at']=now()
            self._invalidate(state,actor)
            state['status']='ACCEPTED' if all(d['accepted'] for d in state['datasets']) and all(s['status']=='EXTRACTED' for s in state['sources']) else 'NEEDS_REVIEW'
            self._revision(session,row,state,actor,'extraction_accepted',{'datasets':[d['id'] for d in selected]})
            return self._public(state)

    def recipe(self,identity,actor,expected,recipe):
        if not isinstance(recipe,dict) or recipe.get('version')!=1 or not isinstance(recipe.get('steps'),list) or len(recipe['steps'])>50 or not isinstance(recipe.get('output'),str):raise ValueError('Recipe needs version 1, up to 50 steps and an output table/step ID')
        if len(encoded(recipe))>250000:raise ValueError('Recipe configuration exceeds limit')
        with self._locked(identity,actor,'prepare',expected) as (session,row,state):
            self._idle(state)
            self._invalidate(state,actor);state['recipe']=deepcopy(recipe)
            state['status']='ACCEPTED' if state['datasets'] and all(d['accepted'] for d in state['datasets']) else 'NEEDS_REVIEW'
            self._revision(session,row,state,actor,'recipe_updated',{'sha256':sha256(encoded(recipe)).hexdigest()})
            return self._public(state)

    def review(self,identity,actor,expected,decision,reason):
        with self._locked(identity,actor,'review',expected) as (session,row,state):
            if actor in state['contributors']:raise DomainForbidden()
            if state['status'] not in ('READY_FOR_REVIEW','APPROVED'):raise DomainConflict('Validated output candidates must be ready before independent review')
            if decision=='APPROVE' and (not state['candidates'] or any(i['severity']=='error' and not i.get('resolved') for i in state['issues'])):raise DomainConflict('Required errors prevent approval')
            state['review']={'actor_id':actor,'decision':decision,'reason':reason,'snapshot_version':state['version'],'snapshot_digest':snapshot_digest(state),'at':now()}
            state['status']='APPROVED' if decision=='APPROVE' else 'NEEDS_REVIEW'
            self._revision(session,row,state,actor,'output_reviewed',state['review'])
            return self._public(state)

    def export(self,identity,actor,expected,dataset_id,format,template_source_id=None,bindings=None):
        with self._locked(identity,actor,'download',expected) as (session,row,state):
            review=state.get('review')
            if state['status']!='APPROVED' or not review or review['decision']!='APPROVE' or review['snapshot_digest']!=snapshot_digest(state):raise DomainConflict('Independent approval of this exact output is required')
            dataset=self._dataset(state,dataset_id)
            if dataset['kind']!='output':raise DomainConflict('Only reviewed output datasets can be released')
            candidate=next((c for c in state['candidates'] if c['dataset_id']==dataset['id'] and c['format']==format),None)
            if not candidate:raise DomainConflict('Requested format was not generated and reviewed')
            configured=state['recipe'].get('export',{})
            if template_source_id is not None and template_source_id!=configured.get('template_source_id') or bindings is not None and bindings!=configured.get('bindings'):raise DomainConflict('Template or bindings changed; update recipe and review a new candidate')
            # Integrity check immediately before release; actual candidate bytes were prepared before review.
            self._blobs(state).get(candidate['content_hash'])
            artifact={**candidate,'artifact_id':uid('artifact'),'review':deepcopy(review),'historical':False}
            state['artifacts'].append(artifact)
            lineage=json.loads(self._blobs(state).get(candidate['manifest_hash']))
            manifest={'collection_id':identity,'dataset':dataset,'sources':state['sources'],'recipe':state['recipe'],'steps':state['steps'],'issues':state['issues'],'review':review,'artifact':candidate,'source_to_output':lineage,'lineage_data_hash':dataset['data_hash']}
            manifest_hash=self._store(state,manifest)
            manifest_artifact={'artifact_id':uid('manifest'),'content_hash':manifest_hash,'media_type':'application/json','filename':'source-to-output-manifest.json','historical':False,'review':deepcopy(review)}
            state['artifacts'].append(manifest_artifact)
            self._revision(session,row,state,actor,'artifact_released',{'artifact_id':artifact['artifact_id'],'content_hash':artifact['content_hash']})
            base='/api/collections/'+identity+'/artifacts/'
            return {'artifact_id':artifact['artifact_id'],'url':base+artifact['artifact_id'],'filename':artifact['filename'],'manifest_url':base+manifest_artifact['artifact_id']}

    def download(self,identity,actor,resource_id,*,artifact=False,candidate=False):
        with self._locked(identity,actor,'download') as (_,_,state):
            items=state['candidates'] if candidate else state['artifacts'] if artifact else state['sources'];key='candidate_id' if candidate else 'artifact_id' if artifact else 'id'
            item=next((x for x in items if x[key]==resource_id),None)
            if not item:raise DomainNotFound()
            return self._blobs(state).get(item['content_hash']),item['media_type'],('DRAFT-' if candidate else '')+item['filename']

    def pending(self):
        with self.sessions() as session,session.begin():
            pending=[]
            for j in session.scalars(select(CollectionJobRow).where(CollectionJobRow.status.in_(['PENDING','RUNNING'])).order_by(CollectionJobRow.created_at).limit(30).with_for_update(skip_locked=True)).all():
                version=session.scalar(select(CollectionRow.version).where(CollectionRow.id==j.collection_id))
                if j.status=='PENDING' and version!=j.version:j.status='SUPERSEDED';continue
                pending.append({'id':j.id,'collection_id':j.collection_id,'run_id':j.dagster_run_id,'status':j.status})
            return pending

    def claim(self,job_id,run_id):
        with self.sessions() as session,session.begin():
            job=session.scalar(select(CollectionJobRow).where(CollectionJobRow.id==job_id).with_for_update())
            if job is None or job.status in ('COMPLETED','FAILED','SUPERSEDED'):return None
            if job.status=='RUNNING' and job.dagster_run_id!=run_id:return None
            version=session.scalar(select(CollectionRow.version).where(CollectionRow.id==job.collection_id))
            if version!=job.version:job.status='SUPERSEDED';return None
            job.status='RUNNING';job.dagster_run_id=run_id
            return {'id':job.id,'kind':job.kind,'snapshot':deepcopy(job.snapshot)}

    def release_failed_run(self,job_id,run_id,*,terminal=False):
        with self.sessions() as session,session.begin():
            job=session.scalar(select(CollectionJobRow).where(CollectionJobRow.id==job_id).with_for_update())
            if job is None or job.status not in ('PENDING','RUNNING') or job.dagster_run_id not in (None,run_id):return
            if terminal:
                job.status='RUNNING';job.dagster_run_id=run_id
                self._finish(session,job,{'execution_error':'Bounded Dagster recovery exhausted; retry processing explicitly'},run_id)
            else:job.status='PENDING';job.dagster_run_id=None

    def compute(self,job):
        from .extract import extract_source
        from .transform import run_recipe
        from .export import export_table
        state=deepcopy(job['snapshot']);blobs=self._blobs(state)
        if job['kind']=='extract':
            for source in state['sources']:
                if source['status']=='EXTRACTED':continue
                state['issues']=[i for i in state['issues'] if i.get('source_id')!=source['id']]
                state['datasets']=[d for d in state['datasets'] if d['source_id']!=source['id']]
                try:
                    extracted=extract_source(blobs.get(source['content_hash']),filename=source['filename'],media_type=source['media_type'],source_id=source['id'],document_version_id=source['id'],pdf_provider=self.pdf_provider,scope=self._scope(state))
                    tables=extracted['tables'];newissues=extracted.get('issues',[])
                    if not tables and not any(i.get('severity')=='error' for i in newissues):newissues.append(issue('no_extracted_data','No data was extracted; inspect the source'))
                    for i in newissues:i.setdefault('source_id',source['id']);i.setdefault('stage','extraction')
                    parser={k:v for k,v in extracted.get('parser',{}).items() if not k.endswith('_base64')}
                    state['issues'].extend(newissues);source.update(parser=parser,coverage=extracted.get('coverage',{}),issues=newissues)
                    # Exact provider response provenance remains in a scoped immutable object.
                    source['extraction_hash']=self._store(state,extracted)
                    for table in tables:
                        data_hash=self._store(state,table)
                        state['datasets'].append({'id':table['table_id'],'table_id':table['table_id'],'source_id':source['id'],'title':table['title'],'columns':table['columns'],'metadata':table.get('metadata',{}),'row_count':len(table['rows']),'accepted':False,'version':1,'kind':'extraction','data_hash':data_hash,'original_hash':data_hash})
                    source['status']='FAILED' if any(i['severity']=='error' for i in newissues) and not tables else 'EXTRACTED'
                except Exception as exc:
                    source['status']='FAILED';state['issues'].append(issue('extraction_failed',str(exc)[:500],source_id=source['id'],stage='extraction'))
            state['status']='BLOCKED' if any(i['severity']=='error' and not i.get('resolved') for i in state['issues']) else 'NEEDS_REVIEW'
        else:
            inputs=[d for d in state['datasets'] if d['kind']=='extraction']
            if not inputs or any(not d['accepted'] or d.get('accepted_hash')!=d['data_hash'] for d in inputs):raise ValueError('Unaccepted input snapshot')
            tables=[self._table(state,d) for d in inputs]
            for table in tables:table['rows']=[r for r in table['rows'] if not r.get('excluded')]
            recipe=state['recipe'];result=run_recipe(tables,{k:v for k,v in recipe.items() if k!='export'})
            state['steps']=result.get('steps',[]);state['issues']=[i for i in state['issues'] if i.get('stage')!='transform']
            for i in result.get('issues',[]):i.setdefault('stage','transform')
            state['issues'].extend(result.get('issues',[]));state['datasets']=inputs;state['candidates']=[]
            config=recipe.get('export',{});formats=config.get('formats',['csv','xlsx'])
            if not isinstance(formats,list) or not formats or any(f not in ('csv','xlsx') for f in formats):raise ValueError('Export formats must be csv/xlsx')
            template=None
            if config.get('template_source_id'):
                source=next((s for s in state['sources'] if s['id']==config['template_source_id']),None)
                if not source or not source['filename'].lower().endswith('.xlsx'):raise ValueError('Template must reference a scoped XLSX source')
                template=blobs.get(source['content_hash'])
            for n,table in enumerate(result['tables']):
                key=uid('output');table=deepcopy(table);previous_id=table['table_id'];table['table_id']=key
                for finding in state['issues']:
                    if finding.get('stage')=='transform' and finding.get('table_id')==previous_id:finding['table_id']=key
                data_hash=self._store(state,table)
                descriptor={'id':key,'table_id':key,'source_id':None,'title':table.get('title','Transformed output'),'columns':table['columns'],'row_count':len(table['rows']),'accepted':False,'version':state['version'],'kind':'output','data_hash':data_hash}
                state['datasets'].append(descriptor)
                if not any(i['severity']=='error' and not i.get('resolved') for i in state['issues']):
                    for fmt in formats:
                        try:
                            exported=export_table(table,fmt,template_bytes=template if fmt=='xlsx' else None,bindings=config.get('bindings'))
                            key_hash=blobs.put(exported['content'])
                            verification=deepcopy(exported['verification']);manifest_hash=self._store(state,verification.pop('source_manifest'))
                            state['candidates'].append({'candidate_id':uid('candidate'),'dataset_id':key,'format':fmt,'filename':exported['filename'],'media_type':exported['media_type'],'content_hash':key_hash,'manifest_hash':manifest_hash,'verification':verification,'byte_size':len(exported['content'])})
                        except Exception as exc:state['issues'].append(issue('export_validation_failed',str(exc)[:500],table_id=key,stage='transform'))
            if not result['tables']:state['issues'].append(issue('no_output','Recipe produced no output dataset',stage='transform'))
            state['status']='BLOCKED' if any(i['severity']=='error' and not i.get('resolved') for i in state['issues']) else 'READY_FOR_REVIEW'
        return state

    def _finish(self,session,job,result,run_id):
        if job.status!='RUNNING' or job.dagster_run_id!=run_id:return {'applied':False}
        row=session.scalar(select(CollectionRow).where(CollectionRow.id==job.collection_id).with_for_update())
        job.result={'data_hash':self._store(job.snapshot,result),'applied':row.version==job.version};job.status='FAILED' if result.get('execution_error') else 'COMPLETED';job.dagster_run_id=run_id
        if row.version!=job.version:return {'applied':False,'superseded':True}
        if result.get('execution_error'):
            state=deepcopy(row.state);state['status']='BLOCKED';state['issues'].append(issue('processing_failed',result['execution_error'],stage=job.kind))
        else:state=result
        state['processing']={'job_id':job.id,'run_id':run_id,'kind':job.kind,'status':job.status}
        self._revision(session,row,state,'system','processing_completed',{'job_id':job.id,'run_id':run_id,'status':job.status})
        return {'applied':True,'collection_id':row.id,'version':row.version,'status':state['status']}

    def finish(self,job_id,run_id,result):
        with self.sessions() as session,session.begin():
            job=session.scalar(select(CollectionJobRow).where(CollectionJobRow.id==job_id).with_for_update())
            if not job:raise ValueError('Unknown collection job')
            return self._finish(session,job,result,run_id)
