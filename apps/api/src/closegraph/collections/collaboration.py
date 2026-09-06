"""Collection collaboration authority and evidence commands; no external delivery."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from uuid import uuid4
from sqlalchemy import select
from closegraph.api.ports import DomainConflict, DomainForbidden, DomainNotFound
from .models import CollectionRow

PARTIES={'PREPARER':'accountant','REVIEWER':'account_manager','FUND_MANAGER':'fund_manager','INVESTOR':'investor'}
def timestamp(): return datetime.now(timezone.utc).isoformat()
def digest(value):return sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

class CollaborationMixin:
    def _initialize(self,state):
        from .documents import initialize_documents
        initialize_documents(state)
        for name in ('members','requirements','check_results','tasks','notifications','comparisons'):
            state.setdefault(name,[])
        state.setdefault('requirements_version',0)
        state.setdefault('idempotency',{})
        return state

    def _access(self,state,actor):
        role=self.auth.collection_actor(actor)['role']
        member=next((m for m in state.get('members',[]) if m['actor_id']==actor),None)
        party=member['party'] if member else PARTIES[role]
        internal=party in ('accountant','account_manager') and role in ('PREPARER','REVIEWER')
        return {'actor_id':actor,'party':party,'can_prepare':internal and party=='accountant','can_manage':internal and party=='account_manager',
                'can_review':internal and party=='account_manager','restricted':not internal,'can_flag':True,'member':member}

    def _authorize_state(self,state,actor,action,grants):
        access=self._access(state,actor)
        if (state['tenant_id'],state['fund_id']) not in grants: raise DomainNotFound()
        if access['restricted'] and not access['member']:raise DomainNotFound()
        if action=='prepare' and not access['can_prepare']:raise DomainForbidden()
        if action in ('review','manage') and not access['can_manage']:raise DomainForbidden()
        if action in ('history','release') and access['restricted']:raise DomainForbidden()
        return access

    def _allowed_document_ids(self,state,actor):
        access=self._access(state,actor)
        if not access['restricted']:return {d['id'] for d in state['documents']}
        return set((access['member'] or {}).get('document_ids',[]))

    def _visible_tasks(self,state,actor):
        access=self._access(state,actor)
        if not access['restricted']:return state['tasks']
        return [t for t in state['tasks'] if t.get('owner_actor_id')==actor and (t.get('owner_party')!='investor' or bool(t.get('released_at'))) and t.get('status')!='pending_manager_release']

    def _project(self,state,actor,value):
        access=self._access(state,actor);value['access']={k:v for k,v in access.items() if k!='member'}
        value['notifications']=[n for n in value.get('notifications',[]) if n.get('recipient_actor_id',n.get('recipient'))==actor]
        value.pop('idempotency',None);value.pop('retired_datasets',None);value.pop('preserved_output',None)
        for c in value.get('comparisons',[]):c.pop('data_hash',None)
        value['flag_recipients']=[{'actor_id':m['actor_id'],'party':m['party'],'display_name':m['actor_id'].replace('_',' ').title()} for m in state['members'] if not access['restricted'] or m['party']=='account_manager']
        for task in value.get('tasks',[]):
            task['allowed_actions']=[a for a in task.get('allowed_actions',[]) if (access['can_manage'] if a in ('release','resolve','reopen','make_blocking') else access['can_manage'] or task.get('owner_actor_id')==actor)]
            if access['can_manage'] and task.get('kind')=='manual' and task.get('active',True) and not task.get('blocking') and task.get('status')!='resolved':task['allowed_actions'].append('make_blocking')
        if not access['restricted']:return value
        documents=self._allowed_document_ids(state,actor)
        value['documents']=[d for d in value['documents'] if d['id'] in documents]
        value['sources']=[s for s in value['sources'] if s.get('document_id') in documents]
        source_ids={s['id'] for s in value['sources']}
        value['datasets']=[d for d in value['datasets'] if d.get('source_id') in source_ids]
        visible={t['id'] for t in self._visible_tasks(state,actor)}
        value['tasks']=[t for t in value['tasks'] if t['id'] in visible]
        # Shared tasks are request summaries, never implicit source or workbook grants.
        for task in value['tasks']:
            for key in ('evaluation','evidence','operands','citations','details','result','check_result','rule_signatures','match_keys','item_ids','check_ids','evaluation_fingerprint','assignment_key','outcome_fingerprint','item_kinds'):task.pop(key,None)
        value.update(requirements=[],check_results=[],members=[],comparisons=[],issues=[],history=[],steps=[],candidates=[],artifacts=[],recipe=None,review=None,summary={})
        allowed={'id','title','fund_id','version','status','access','documents','sources','datasets','tasks','notifications','requirements','check_results','members','comparisons','issues','history','steps','candidates','artifacts','recipe','review','summary','flag_recipients'}
        return {k:v for k,v in value.items() if k in allowed}

    def participants(self,identity,actor):
        with self._locked(identity,actor,'manage') as (_,_,state):
            return [{**p,'display_name':p['actor_id'].replace('_',' ').title(),'party':PARTIES[p['role']]} for p in self.auth.collection_participants(state['tenant_id'],state['fund_id'])]

    def members(self,identity,actor,expected,members):
        with self._locked(identity,actor,'manage',expected) as (session,row,state):
            self._idle(state)
            candidates={p['actor_id']:p for p in self.auth.collection_participants(state['tenant_id'],state['fund_id'])}
            ids=[m['actor_id'] for m in members]
            if len(ids)!=len(set(ids)):raise ValueError('Each person may have one collection assignment')
            if not any(m['party']=='account_manager' for m in members):raise ValueError('Keep at least one account manager responsible for this collection')
            docs={d['id'] for d in state['documents']}
            for m in members:
                if m['actor_id'] not in candidates or m['party'] not in PARTIES.values():raise ValueError('Choose an authorised participant and party')
                default=PARTIES[candidates[m['actor_id']]['role']]
                if m['party'] in ('accountant','account_manager') and m['party']!=default:raise ValueError('Preparation and review capabilities require matching server roles')
                if not set(m.get('document_ids',[]))<=docs:raise ValueError('Unknown document grant')
            if any(t.get('owner_actor_id') not in ids and t.get('owner_party') in ('investor','fund_manager') and t.get('status')!='resolved' for t in state['tasks']):raise DomainConflict('Reassign open tasks before removing their owner')
            state['members']=deepcopy(members)
            self._revision(session,row,state,actor,'members_updated',{'members':members})
            return self._public(state,actor)

    def requirements(self,identity,actor,expected,requirements):
        from .workflow import validate_requirements
        with self._locked(identity,actor,'manage',expected) as (session,row,state):
            self._idle(state)
            requirements=deepcopy(requirements)
            candidates={p['actor_id']:PARTIES[p['role']] for p in self.auth.collection_participants(state['tenant_id'],state['fund_id'])}
            candidates.update({m['actor_id']:m['party'] for m in state['members']})
            for r in requirements:
                if r.get('owner_actor_id') and candidates.get(r['owner_actor_id'])!=r.get('owner_party'):raise ValueError('Requirement owner must match an authorised party')
                if r.get('owner_party') in ('investor','fund_manager') and not any(m['actor_id']==r.get('owner_actor_id') for m in state['members']):raise ValueError('Assign the evidence owner to this collection first')
                if r.get('kind')=='fee':r.setdefault('parameters',{})['rule_approved_by']=actor
            validate_requirements(requirements)
            self._invalidate_fund_review(state)
            state['requirements']=requirements;state['requirements_version']+=1
            state['check_results']=[];state['review']=None
            for a in state['artifacts']:a['historical']=True
            if state['status']=='APPROVED':state['status']='NEEDS_REVIEW'
            self._revision(session,row,state,actor,'requirements_updated',{'requirements_version':state['requirements_version']})
            return self._public(state,actor)

    def evaluate(self,identity,actor,expected):
        with self._locked(identity,actor,'inspect',expected) as (session,row,state):
            if self._access(state,actor)['restricted']:raise DomainForbidden()
            self._idle(state);state['status']='QUEUED'
            self._revision(session,row,state,actor,'verification_requested')
            self._queue(session,row,state,'evaluate')
            return self._public(state,actor)

    def verify_coverage(self,identity,actor,expected,source_id,reason):
        with self._locked(identity,actor,'prepare',expected) as (session,row,state):
            self._idle(state)
            source=next((s for s in state['sources'] if s['id']==source_id),None)
            if not source:raise DomainNotFound()
            if source['status']!='EXTRACTED' or not source.get('coverage',{}).get('complete'):raise DomainConflict('Incomplete processing cannot be confirmed complete')
            source['completeness_verified']=True;source['completeness_verified_hash']=source['content_hash'];source['completeness_review']={'actor_id':actor,'reason':reason,'at':timestamp()}
            self._invalidate(state,actor)
            if state.get('fund_review'):
                state['status']='QUEUED'
            self._revision(session,row,state,actor,'source_coverage_verified',{'source_id':source_id,'reason':reason})
            if state.get('fund_review'):
                self._queue(session,row,state,'fund_review')
            return self._public(state,actor)

    def comparison(self,identity,actor,comparison_id,offset=0,limit=100):
        with self._locked(identity,actor,'inspect') as (_,_,state):
            item=next((c for c in state['comparisons'] if c['id']==comparison_id),None)
            if not item or item['document_id'] not in self._allowed_document_ids(state,actor):raise DomainNotFound()
            if not item.get('data_hash'):return {**item,'changes':[],'total':0,'offset':offset,'limit':limit}
            value=json.loads(self._blobs(state).get(item['data_hash']))
            changes=value.pop('changes',[])
            return {**value,'changes':changes[offset:offset+limit],'total':len(changes),'offset':offset,'limit':limit}

    def configure_document(self,identity,actor,expected,document_id,business_keys):
        with self._locked(identity,actor,'manage',expected) as (session,row,state):
            self._idle(state)
            doc=next((d for d in state['documents'] if d['id']==document_id),None)
            if not doc:raise DomainNotFound()
            doc['business_keys']=deepcopy(business_keys)
            state['review']=None;state['status']='QUEUED'
            for comparison in state['comparisons']:
                if comparison['document_id']==document_id:comparison.pop('review',None)
            for artifact in state['artifacts']:artifact['historical']=True
            self._revision(session,row,state,actor,'comparison_keys_updated',{'document_id':document_id})
            self._queue(session,row,state,'compare')
            return self._public(state,actor)

    def _evaluate_state(self,state):
        from .workflow import evaluate_requirements,sync_tasks
        state['check_results']=evaluate_requirements(state,lambda d:self._table(state,d),timestamp())
        sync_tasks(state,state['check_results'],timestamp())
        state['verification_fingerprint']=self._verification_fingerprint(state)
        state['financial_verified']=self._financial_ready(state)
        return state

    def _verification_fingerprint(self,state):
        from .documents import output_dependency_ids
        graph=output_dependency_ids(state)
        ids=set(graph['source_ids']) if graph['known'] else {s['id'] for s in state['sources']}
        return digest({'requirements':state.get('requirements'),'requirements_version':state.get('requirements_version'),
            'sources':[(s['id'],s.get('content_hash'),s.get('completeness_verified')) for s in state['sources'] if s['id'] in ids],
            'datasets':[(d['id'],d.get('data_hash'),d.get('accepted_hash'),d.get('accepted')) for d in state['datasets'] if d.get('source_id') in ids or d['kind']=='output'],
            'recipe':state.get('recipe')})

    def _financial_ready(self,state):
        required=[r for r in state.get('requirements',[]) if r.get('blocking',True)]
        checks=state.get('check_results',[])
        substantive=any(r.get('kind')!='evidence' for r in required) or bool(state.get('recipe_checks')) and all(c.get('passed') is True for c in state['recipe_checks'])
        return bool(required) and substantive and all(any(c.get('requirement_id')==r['id'] and c.get('outcome',c.get('status'))=='PASS' for c in checks) for r in required) and not any(t.get('active',True) and t.get('blocking') and t.get('status')!='resolved' for t in state.get('tasks',[]))

    def _check_review_gate(self,state):
        if not self._financial_ready(state):raise DomainConflict('Configure and pass all required evidence and financial checks before approval')
        if state.get('verification_fingerprint')!=self._verification_fingerprint(state):raise DomainConflict('Evidence changed; run checks again before approval')
        from .documents import output_dependency_ids
        graph=output_dependency_ids(state)
        if not graph['known']:raise DomainConflict('Output dependencies are unresolved; review the document mappings')
        relevant=[c for c in state.get('comparisons',[]) if c['document_id'] in graph['document_ids'] and any(d['current_revision_id']==c['after_revision_id'] for d in state['documents'])]
        if any(c['status']!='COMPLETED' and not self._comparison_reviewed(state,c) for c in relevant):raise DomainConflict('Resolve incomplete or ambiguous document comparisons before approval')
        from .workflow import evaluate_requirements
        fresh=evaluate_requirements(state,lambda d:self._table(state,d),timestamp())
        for r in state['requirements']:
            if r.get('blocking',True) and not any(c.get('requirement_id')==r['id'] and c.get('outcome',c.get('status'))=='PASS' for c in fresh):raise DomainConflict('Required evidence is stale or no longer passes')

    def _attach_task_evidence(self,state,actor,task_id,source):
        from .workflow import task_action
        task=next((t for t in self._visible_tasks(state,actor) if t['id']==task_id),None)
        if not task or task.get('owner_actor_id')!=actor and not self._access(state,actor)['can_manage']:raise DomainForbidden()
        # A response upload grants its submitter access only to that document.
        member=next((m for m in state['members'] if m['actor_id']==actor),None)
        if member and source['document_id'] not in member.setdefault('document_ids',[]):member['document_ids'].append(source['document_id'])
        task_action(state,task_id,'evidence_received',actor,now=timestamp(),note='Evidence uploaded',document_ids=[source['document_id']])

    def flag(self,identity,actor,expected,title,reason,owner_actor_id,document_id=None,blocking=False,idempotency_key=None):
        from .workflow import create_manual_flag
        with self._locked(identity,actor,'inspect') as (session,row,state):
            fingerprint=digest({'title':title,'reason':reason,'owner':owner_actor_id,'document':document_id,'blocking':blocking})
            key='flag:'+idempotency_key if idempotency_key else None
            if key and key in state['idempotency']:
                old=state['idempotency'][key]
                if old['actor_id']!=actor or old['fingerprint']!=fingerprint:raise DomainConflict('Submission key already used')
                return self._public(state,actor)
            if expected!=state['version']:raise DomainConflict('Collection changed; refresh before continuing')
            self._idle(state)
            access=self._access(state,actor)
            if blocking and not access['can_manage']:raise DomainForbidden()
            if document_id and document_id not in self._allowed_document_ids(state,actor):raise DomainNotFound()
            candidates={p['actor_id']:PARTIES[p['role']] for p in self.auth.collection_participants(state['tenant_id'],state['fund_id'])}
            candidates.update({m['actor_id']:m['party'] for m in state['members']})
            if owner_actor_id not in candidates:raise ValueError('Choose an authorised recipient')
            if access['restricted'] and candidates[owner_actor_id]!='account_manager' and owner_actor_id!=actor:raise DomainForbidden()
            if candidates[owner_actor_id] in ('investor','fund_manager') and not any(m['actor_id']==owner_actor_id for m in state['members']):raise ValueError('Assign the recipient to this collection first')
            create_manual_flag(state,{'id':'flag-'+uuid4().hex,'title':title,'reason':reason,'owner_actor_id':owner_actor_id,'owner_party':candidates[owner_actor_id],'document_ids':[document_id] if document_id else [],'blocking':blocking},actor,timestamp())
            if key:state['idempotency'][key]={'actor_id':actor,'fingerprint':fingerprint}
            if blocking:
                state['review']=None;state['financial_verified']=False
                self._invalidate_fund_review(state)
            self._revision(session,row,state,actor,'manual_flag_raised',{'title':title,'owner_actor_id':owner_actor_id,'blocking':blocking})
            return self._public(state,actor)

    def task_action(self,identity,actor,expected,task_id,action,reason='',source_id=None,idempotency_key=None):
        from .workflow import task_action
        with self._locked(identity,actor,'inspect') as (session,row,state):
            fingerprint=digest({'task':task_id,'action':action,'reason':reason,'source':source_id})
            key='action:'+idempotency_key if idempotency_key else None
            if key and key in state['idempotency']:
                old=state['idempotency'][key]
                if old['actor_id']!=actor or old['fingerprint']!=fingerprint:raise DomainConflict('Submission key already used')
                return self._public(state,actor)
            if expected!=state['version']:raise DomainConflict('Collection changed; refresh before continuing')
            self._idle(state)
            task=next((t for t in self._visible_tasks(state,actor) if t['id']==task_id),None)
            if not task:raise DomainNotFound()
            access=self._access(state,actor)
            if action in ('release','resolve','reopen','make_blocking') and not access['can_manage']:raise DomainForbidden()
            if not access['can_manage'] and task.get('owner_actor_id')!=actor:raise DomainForbidden()
            documents=[]
            if source_id:
                source=next((s for s in state['sources'] if s['id']==source_id and s.get('document_id') in self._allowed_document_ids(state,actor)),None)
                if not source:raise DomainNotFound()
                documents=[source['document_id']]
            if action=='make_blocking':
                if task.get('kind')!='manual' or not task.get('active',True) or task['status']=='resolved':raise ValueError('Only an active manual concern can be made blocking')
                if not reason.strip():raise ValueError('Explain why this concern blocks approval')
                task['blocking']=True;task['blocking_reason']=reason;state['review']=None
                self._invalidate_fund_review(state)
            else:task_action(state,task_id,action,actor,now=timestamp(),note=reason,document_ids=documents)
            if key:state['idempotency'][key]={'actor_id':actor,'fingerprint':fingerprint}
            self._revision(session,row,state,actor,'task_updated',{'task_id':task_id,'action':action,'reason':reason})
            return self._public(state,actor)

    def inbox(self,actor):
        return [{'collection_id':c['id'],'collection_title':c['title'],**n} for c in self.list(actor) for n in c.get('notifications',[])]

    def _rebind_recipe(self,state):
        if not state.get('recipe'):return
        inputs={d['id']:d for d in state['datasets'] if d['kind']=='extraction'}
        retired={d['id']:d for d in state.get('retired_datasets',[])}
        sources={s['id']:s for s in state['sources']}
        replacements={}
        for key,old in retired.items():
            document=sources.get(old.get('source_id'),{}).get('document_id')
            candidates=[d for d in inputs.values() if sources.get(d.get('source_id'),{}).get('document_id')==document and d['title']==old['title']]
            if len(candidates)==1 and candidates[0]['columns']==old['columns'] and candidates[0]['accepted']:
                replacements[key]=candidates[0]['id']
        def walk(value):
            if isinstance(value,dict):return {k:(replacements.get(v,v) if k in ('input','left','right','output','table_id','dataset_id','table') and isinstance(v,str) else walk(v)) for k,v in value.items()}
            if isinstance(value,list):return [walk(v) for v in value]
            return value
        state['recipe']=walk(state['recipe'])
        state['mapping_rebindings']=[{'from':k,'to':v} for k,v in replacements.items()]

    def sweep_deadlines(self):
        from .workflow import tick_deadlines
        with self.sessions() as session,session.begin():
            for row in session.scalars(select(CollectionRow).with_for_update(skip_locked=True)):
                state=self._initialize(deepcopy(row.state))
                if state['status'] in ('QUEUED','PROCESSING'):continue
                before=digest({'tasks':state['tasks'],'notifications':state['notifications']})
                tick_deadlines(state,timestamp())
                if before!=digest({'tasks':state['tasks'],'notifications':state['notifications']}):
                    self._revision(session,row,state,'system','request_deadline_updated')

    def _review_notice(self,state,event,recipients):
        for recipient in sorted(set(recipients)):
            key='notification-'+digest([state['id'],event,self._verification_fingerprint(state),recipient])[:24]
            if any(n['id']==key for n in state['notifications']):continue
            state['notifications'].append({'id':key,'recipient_actor_id':recipient,'event':event,
                'title':'Output ready for review' if event=='review_requested' else 'Output review completed',
                'message':'Review the changes, evidence and checks.' if event=='review_requested' else 'The independent reviewer has recorded a decision.',
                'created_at':timestamp(),'delivery':'in_app','read_at':None})

    def review_comparison(self,identity,actor,expected,comparison_id,reason):
        with self._locked(identity,actor,'review',expected) as (session,row,state):
            self._idle(state)
            if actor in state['contributors']:raise DomainForbidden()
            comparison=next((c for c in state['comparisons'] if c['id']==comparison_id),None)
            if not comparison:raise DomainNotFound()
            doc=next(d for d in state['documents'] if d['id']==comparison['document_id'])
            if doc['current_revision_id']!=comparison['after_revision_id']:raise DomainConflict('Review the current document revision')
            sources={s['id']:s for s in state['sources']}
            comparison['review']={'actor_id':actor,'reason':reason,'at':timestamp(),'before_hash':sources[comparison['before_revision_id']]['content_hash'],'after_hash':sources[comparison['after_revision_id']]['content_hash'],'comparison_hash':comparison.get('data_hash')}
            self._revision(session,row,state,actor,'comparison_reviewed',{'comparison_id':comparison_id,**comparison['review']})
            return self._public(state,actor)

    def _comparison_reviewed(self,state,comparison):
        review=comparison.get('review')
        if not review:return False
        sources={s['id']:s for s in state['sources']}
        return review.get('before_hash')==sources[comparison['before_revision_id']]['content_hash'] and review.get('after_hash')==sources[comparison['after_revision_id']]['content_hash'] and review.get('comparison_hash')==comparison.get('data_hash')
