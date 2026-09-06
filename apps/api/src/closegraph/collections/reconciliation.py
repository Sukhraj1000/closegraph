"""Versioned reconciliation orchestration; computed evidence is never approval."""
from copy import deepcopy
from hashlib import sha256
from datetime import datetime, timezone
from uuid import uuid4
import csv, io, json
from closegraph.api.ports import DomainConflict, DomainForbidden, DomainNotFound
from .documents import current_sources


def stamp():return datetime.now(timezone.utc).isoformat()
def fingerprint(value):return sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

class ReconciliationMixin:
    def _reconciliation_fingerprint(self,state):
        r=state.get('reconciliation',{})
        ids={s['id'] for s in current_sources(state) if r.get('source_sides',{}).get(s['id'])}
        return fingerprint({'sources':[(s['id'],s['content_hash'],s.get('coverage'),s.get('status')) for s in state['sources'] if s['id'] in ids],
            'tables':[(d['id'],d['data_hash']) for d in state['datasets'] if d.get('source_id') in ids], 'config':r.get('config',{}),'sides':r.get('source_sides',{})})

    def _reconciliation_notice(self,state,event,title,recipients,revision,task_id=None):
        for actor in set(recipients):
            key='notice-'+fingerprint([state['id'],event,actor,revision])[:24]
            if any(n['id']==key for n in state['notifications']):continue
            state['notifications'].append({'id':key,'recipient_actor_id':actor,'event':event,'title':title,'message':title,'created_at':stamp(),'read_at':None,'delivery':'in_app','task_id':task_id,'collection_id':state['id']})

    def _invalidate_reconciliation(self,state):
        r=state.get('reconciliation')
        if not r:return
        if r.get('review',{} ) and r['review'].get('decision')=='APPROVE':
            self._reconciliation_notice(state,'review_invalidated','Reviewed inputs changed. Review the revised reconciliation.',[r['review']['actor_id']],r.get('fingerprint'))
        r.pop('review',None);r['status']='STALE'

    def reconcile(self,identity,actor,expected,source_sides,config,reason,idempotency_key=None):
        if not isinstance(config,dict) or len(json.dumps(config))>100000:raise ValueError('Invalid reconciliation configuration')
        if not isinstance(source_sides,dict) or any(v not in ('statement','journal') for v in source_sides.values()):raise ValueError('Choose a statement or journal role for each input')
        with self._locked(identity,actor,'prepare') as (session,row,state):
            digest=fingerprint([source_sides,config,reason])
            if idempotency_key and idempotency_key in state['idempotency']:
                receipt=state['idempotency'][idempotency_key]
                if receipt['actor_id']!=actor or receipt['fingerprint']!=digest:raise DomainConflict('Retry key belongs to another submission')
                return self._public(state,actor)
            if expected!=state['version']:raise DomainConflict('Work changed; refresh before reconciling')
            sources={s['id']:s for s in current_sources(state)}
            if not source_sides or not set(source_sides)<=set(sources):raise ValueError('Reconciliation inputs must be current document versions')
            if set(source_sides.values())!={'statement','journal'}:raise ValueError('Add both bank statements and a journal/workbook')
            self._invalidate_reconciliation(state)
            previous=state.get('reconciliation',{})
            state['reconciliation']={**previous,'source_sides':deepcopy(source_sides),'config':deepcopy(config),'status':'QUEUED','requested_by':actor,'requested_at':stamp()}
            state['contributors']=sorted(set(state.get('contributors',[]))|{actor})
            for sid,side in source_sides.items():sources[sid]['reconciliation_side']=side
            state['status']='QUEUED'
            if idempotency_key:state['idempotency'][idempotency_key]={'actor_id':actor,'fingerprint':digest}
            self._revision(session,row,state,actor,'reconciliation_requested',{'reason':reason,'config':deepcopy(config),'source_sides':deepcopy(source_sides)})
            self._queue(session,row,state,'reconcile')
            return self._public(state,actor)

    def _rebind_reconciliation(self,state):
        r=state['reconciliation'];current={d['id']:d for d in state['datasets']};sources={s['id']:s for s in state['sources']};replacements={}
        for old in state.get('retired_datasets',[]):
            doc=sources.get(old.get('source_id'),{}).get('document_id')
            candidates=[d for d in current.values() if sources.get(d.get('source_id'),{}).get('document_id')==doc and d['title']==old['title'] and d['columns']==old['columns']]
            if len(candidates)==1:
                # Spreadsheet column letters alone do not establish unchanged meaning.
                old_table=self._table(state,old);new_table=self._table(state,candidates[0])
                configured=next((m for m in r.get('config',{}).get('mappings',[]) if m.get('dataset_id')==old['id']),{})
                header=configured.get('header_row_id')
                def header_values(table):
                    rows=table.get('rows',[])
                    return next((row.get('values') for row in rows if row.get('row_id')==header),None) if header else (rows[0].get('values') if rows else None)
                if header_values(old_table)==header_values(new_table) and header_values(old_table) is not None:
                    replacements[old['id']]=candidates[0]['id']
        def walk(value):
            if isinstance(value,dict):return {k:(replacements.get(v,v) if k in ('dataset_id','table_id') and isinstance(v,str) else walk(v)) for k,v in value.items()}
            if isinstance(value,list):return [walk(v) for v in value]
            return value
        previous=r.get('config',{});updated=walk(previous)
        if previous!=updated:
            r['config']=updated;r['mapping_rebindings']=[{'from':k,'to':v,'basis':'Same logical document, table title, column schema and header values'} for k,v in replacements.items()]

    def _compute_reconciliation(self,state):
        from .reconcile import reconcile
        self._rebind_reconciliation(state)
        r=state['reconciliation'];envelopes=[]
        sources={s['id']:s for s in current_sources(state)}
        # Map a revised logical document to its previous side; record any uniquely determined table rebinding above.
        for source in sources.values():
            side=source.get('reconciliation_side')
            if side:r.setdefault('source_sides',{})[source['id']]=side
        r['source_sides']={sid:side for sid,side in r.get('source_sides',{}).items() if sid in sources}
        for d in state['datasets']:
            source=sources.get(d.get('source_id'));side=r['source_sides'].get(d.get('source_id'))
            if not source or not side or d['kind']!='extraction':continue
            table=self._table(state,d)
            envelopes.append({**table,'dataset_id':d['id'],'source_id':source['id'],'document_id':source['document_id'],'side':side,'coverage':source.get('coverage',{}),'media_type':source['media_type'],'accepted':d['accepted'],'filename':source['filename'],'parser':source.get('parser',{}),'extraction_confirmed':source['id'] in r.get('config',{}).get('confirmed_source_ids',[])})
        result=reconcile(envelopes,r.get('config',{}))
        tables=result.get('coverage',[])
        if isinstance(tables,list):result['coverage']={'tables':tables,'complete':bool(tables) and all(not c.get('unclassified_rows') and not c.get('issues') for c in tables)}
        failed=[s['filename'] for sid,s in sources.items() if sid in r['source_sides'] and (s['status']!='EXTRACTED' or not s.get('coverage',{}).get('complete'))]
        if failed:
            result.setdefault('coverage',{})['source_errors']=failed;result['coverage']['complete']=False
            # Absence cannot be established from an incomplete selected document.
            for item in result.get('items',[]):
                if item['status']=='missing':
                    item['status']='needs_input'
                    item['reason']='A selected document could not be read completely. Check source coverage before deciding whether this record is missing.'
                    result['summary']['missing']-=1;result['summary']['needs_input']+=1
        result['source_versions']=[{'source_id':s['id'],'document_id':s['document_id'],'content_hash':s['content_hash'],'parser':s.get('parser',{})} for sid,s in sources.items() if sid in r['source_sides']]
        result['rule_version']='bank-reconciliation-v1';result['config']=deepcopy(r.get('config',{}))
        key=self._store(state,result);digest=self._reconciliation_fingerprint(state)
        r.update(status='COMPLETE',result_hash=key,fingerprint=digest,summary=result.get('summary',{}),coverage=result.get('coverage',{}),suggestions=result.get('suggestions',[]),completed_at=stamp(),version=state['version'])
        state['status']='NEEDS_REVIEW'
        # The new workflow derives checks from its explicit reconciliation contract, not the old empty-policy setup task.
        for task in state['tasks']:
            if task.get('requirement_id')=='missing_check_policy':task['active']=False;task['allowed_actions']=[]
        self._sync_reconciliation_requests(state,result)
        return state

    def _reconciliation_result(self,state):
        r=state.get('reconciliation',{})
        if not r.get('result_hash'):raise DomainConflict('Reconciliation results are not ready yet')
        return json.loads(self._blobs(state).get(r['result_hash']))

    def reconciliation_results(self,identity,actor,status=None,q='',offset=0,limit=50):
        with self._locked(identity,actor,'history') as (_,_,state):
            result=self._reconciliation_result(state);items=result.get('items',[])
            if status:items=[x for x in items if x['status']==status]
            if q:items=[x for x in items if q.casefold() in json.dumps(x,ensure_ascii=False).casefold()]
            return {'items':items[offset:offset+limit],'total':len(items),'offset':offset,'limit':limit,'summary':result.get('summary',{}),'coverage':result.get('coverage',{}),'stale':state['reconciliation']['status']!='COMPLETE','version':state['version']}

    def notifications_read(self,identity,actor,notification_ids):
        with self._locked(identity,actor,'inspect') as (session,row,state):
            self._idle(state)
            changed=[]
            for n in state['notifications']:
                if n['id'] in notification_ids and n.get('recipient_actor_id',n.get('recipient'))==actor and not n.get('read_at'):n['read_at']=stamp();changed.append(n['id'])
            if changed:self._revision(session,row,state,actor,'notifications_read',{'notification_ids':changed})
            return self._public(state,actor)

    def reconciliation_assign(self,identity,actor,expected,item_ids,owner_actor_id,reason,due_at=None):
        from .workflow import _actions, _event, _notify
        if not reason.strip():raise ValueError('Explain what evidence or action is needed')
        if due_at:
            try:
                due=datetime.fromisoformat(due_at.replace('Z','+00:00'))
                if due.tzinfo is None:raise ValueError()
            except ValueError:raise ValueError('Deadline must include a timezone')
        with self._locked(identity,actor,'history',expected) as (session,row,state):
            result=self._reconciliation_result(state)
            if state['reconciliation']['status']!='COMPLETE':raise DomainConflict('Wait for the current reconciliation')
            selected=[i for i in result['items'] if i['id'] in item_ids and i['status']!='matched']
            if len(selected)!=len(set(item_ids)) or not selected:raise ValueError('Select current unresolved items')
            member=next((m for m in state['members'] if m['actor_id']==owner_actor_id),None)
            if not member:raise ValueError('Choose an assigned participant')
            if any(i['status']=='needs_input' for i in selected) and member['party'] not in ('accountant','account_manager'):raise ValueError('Uncertain extraction must be checked internally first')
            signature=fingerprint([sorted(item_ids),owner_actor_id,reason,due_at,state['reconciliation']['fingerprint']])
            if any(t.get('assignment_key')==signature for t in state['tasks']):return self._public(state,actor)
            task={'id':'task-'+uuid4().hex,'kind':'reconciliation','title':str(len(selected))+' reconciliation item'+('s' if len(selected)!=1 else '')+' need review','description':reason,'message':reason,'owner_actor_id':owner_actor_id,'owner_party':member['party'],'created_by':actor,'created_at':stamp(),'updated_at':stamp(),'cycle':1,'active':True,'blocking':True,'status':'pending_manager_release' if member['party']=='investor' else 'open','document_ids':[],'due_at':due_at,'escalate_after_days':0,'events':[],'item_ids':list(item_ids),'match_keys':[(i.get('match_key') or i['id']) for i in selected],'assignment_key':signature,'evaluation_fingerprint':state['reconciliation']['fingerprint']}
            task['allowed_actions']=_actions(task);_event(task,'created',actor,stamp(),reason);state['tasks'].append(task)
            _notify(state,task,'manager_release_required' if member['party']=='investor' else 'assigned',stamp())
            self._revision(session,row,state,actor,'reconciliation_assigned',{'task_id':task['id'],'item_ids':item_ids,'owner_actor_id':owner_actor_id,'reason':reason})
            return self._public(state,actor)

    def _sync_reconciliation_requests(self,state,result):
        from .workflow import _actions,_event,_notify
        index={}
        for item in result.get('items',[]):index.setdefault((item.get('match_key') or item['id']),[]).append(item)
        for task in state['tasks']:
            if task.get('kind')!='reconciliation':continue
            keys=task.get('match_keys',[]);linked=[i for key in keys for i in index.get(key,[])]
            passed=bool(keys) and all(key in index and all(i['status']=='matched' for i in index[key]) for key in keys)
            outcome=fingerprint([((i.get('match_key') or i['id']),i['status'],i.get('difference'),i.get('reason')) for i in linked])
            task['item_ids']=[i['id'] for i in linked]
            if passed and task['status']!='resolved':
                task['status']='resolved';task['resolved_at']=stamp();_event(task,'verification_passed','system',stamp(),'Linked transactions match after reevaluation')
                _notify(state,task,'resolved',stamp(),recipients=[task['owner_actor_id'],task.get('created_by',task['owner_actor_id'])])
            elif not passed and (task['status']=='resolved' or task.get('outcome_fingerprint') and task['outcome_fingerprint']!=outcome):
                task['cycle']+=1;task['status']='pending_manager_release' if task['owner_party']=='investor' else 'open'
                for k in ('released_at','released_by','resolved_at','overdue','escalated'):task.pop(k,None)
                _event(task,'material_change','system',stamp(),'The linked result changed or could not be found; review required')
                _notify(state,task,'material_change',stamp())
            task['outcome_fingerprint']=outcome;task['allowed_actions']=_actions(task)

    def _reconciliation_gate(self,state):
        r=state.get('reconciliation',{});result=self._reconciliation_result(state)
        if r.get('status')!='COMPLETE' or r.get('fingerprint')!=self._reconciliation_fingerprint(state):raise DomainConflict('Reconcile current inputs before review')
        if not result.get('items') or any(i['status']!='matched' for i in result['items']):raise DomainConflict('Resolve outstanding reconciliation findings before reviewed release')
        if result.get('coverage',{}).get('complete') is not True:raise DomainConflict('Complete source coverage is required')
        if any(t.get('active',True) and t.get('blocking') and t['status']!='resolved' for t in state['tasks']):raise DomainConflict('Resolve blocking requests before release')
        return result

    def reconciliation_review(self,identity,actor,expected,decision,reason):
        if not reason.strip():raise ValueError('Record an independent review reason')
        with self._locked(identity,actor,'review',expected) as (session,row,state):
            if actor in state.get('contributors',[]):raise DomainForbidden()
            if decision=='APPROVE':self._reconciliation_gate(state)
            r=state.get('reconciliation')
            if not r:raise DomainNotFound()
            r['review']={'decision':decision,'actor_id':actor,'reason':reason,'at':stamp(),'fingerprint':r.get('fingerprint'),'result_hash':r.get('result_hash')}
            self._reconciliation_notice(state,'review_completed','Reconciliation '+('approved' if decision=='APPROVE' else 'returned for changes'),[m['actor_id'] for m in state['members'] if m['party']=='accountant'],fingerprint(r['review']))
            self._revision(session,row,state,actor,'reconciliation_reviewed',r['review'])
            return self._public(state,actor)

    def reconciliation_download(self,identity,actor,reviewed=False):
        with self._locked(identity,actor,'release') as (session,row,state):
            result=self._reconciliation_result(state);r=state['reconciliation']
            if r.get('status')!='COMPLETE' or r.get('fingerprint')!=self._reconciliation_fingerprint(state):raise DomainConflict('Reconcile current inputs before download')
            if reviewed:
                self._reconciliation_gate(state);review=r.get('review',{})
                if review.get('decision')!='APPROVE' or review.get('fingerprint')!=r['fingerprint'] or review.get('result_hash')!=r['result_hash']:raise DomainConflict('Independent approval of this result is required')
            out=io.StringIO();writer=csv.writer(out);fields=['status','date','account','currency','reference','statement_amount','journal_amount','difference','reason']
            writer.writerow(['Reviewed reconciliation' if reviewed else 'Working reconciliation — not approved']);writer.writerow(fields+['statement_evidence','journal_evidence'])
            for item in result['items']:
                values=[item.get(k,'') for k in fields]+[json.dumps(item.get(k,[]),ensure_ascii=False) for k in ('statement','journal')]
                writer.writerow([("'"+str(v)) if str(v).startswith(('=','+','-','@','\t','\r')) and not str(v).replace('-','',1).replace('.','',1).isdigit() else v for v in values])
            content=out.getvalue().encode('utf-8-sig');content_hash=self._blobs(state).put(content)
            self._revision(session,row,state,actor,'reconciliation_downloaded',{'reviewed':reviewed,'result_hash':r['result_hash'],'content_hash':content_hash})
            return content,'text/csv',('reviewed-' if reviewed else 'working-')+'reconciliation.csv'
