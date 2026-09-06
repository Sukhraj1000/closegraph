"""Service contracts; real-file fidelity/adversarial acceptance lives outside Git."""
import base64
import pytest
from closegraph.api.ports import DomainConflict,DomainForbidden
from .test_evidence_collaboration import service
from .test_collections import run_pending

DATA=b'reference,account,currency,date,amount\nA,bank,GBP,2026-09-01,100\nB,bank,GBP,2026-09-02,50\n'
def inputs(service, changed=False):
 s=service.create('preparer','Reconciliation contract','fund-a')
 for side in ('statement','journal'):
  data=DATA.replace(b',50',b',60') if changed and side=='journal' else DATA
  s=service.upload(s['id'],'preparer',s['version'],side+'.csv','text/csv',base64.b64encode(data).decode(),side=side,idempotency_key=side)
 return run_pending(service,s['id'])
def start(service,s):
 config={'mappings':[{'dataset_id':d['id'],'header_row_id':'1','columns':{'reference':'c1','account':'c2','currency':'c3','date':'c4','amount':'c5'},'cash_leg_confirmed':True} for d in s['datasets']]}
 # Use actual extracted row IDs rather than assuming physical-coordinate syntax.
 for m in config['mappings']:m['header_row_id']=service.rows(s['id'],'preparer',m['dataset_id'])['rows'][0]['row_id']
 s=service.reconcile(s['id'],'preparer',s['version'],{x['id']:x['reconciliation_side'] for x in s['sources']},config,'Explicit contract')
 return run_pending(service,s['id'])
def test_complete_preview_independent_review_and_export(service):
 s=start(service,inputs(service));r=service.reconciliation_results(s['id'],'preparer')
 assert r['summary']['matched']==2,r
 assert r['coverage']['complete']
 assert service.reconciliation_download(s['id'],'preparer')[2]=='working-reconciliation.csv'
 s=service.get(s['id'],'preparer')
 with pytest.raises(DomainForbidden):service.reconciliation_review(s['id'],'preparer',s['version'],'APPROVE','Checked')
 s=service.reconciliation_review(s['id'],'reviewer',s['version'],'APPROVE','Inspected exact source and calculations')
 assert b'Reviewed reconciliation' in service.reconciliation_download(s['id'],'reviewer',True)[0]

def test_discrepancy_assignment_dedup_read_and_correction(service):
 s=start(service,inputs(service,True));r=service.reconciliation_results(s['id'],'preparer',status='difference')
 assert r['total']==1;item=r['items'][0]
 with pytest.raises(DomainConflict):service.reconciliation_review(s['id'],'reviewer',s['version'],'APPROVE','No')
 s=service.reconciliation_assign(s['id'],'reviewer',s['version'],[item['id']],'preparer','Correct the amount')
 t=next(t for t in s['tasks'] if t['kind']=='reconciliation')
 before=len(service.get(s['id'],'preparer')['notifications'])
 s=service.reconciliation_assign(s['id'],'reviewer',s['version'],[item['id']],'preparer','Correct the amount')
 assert len(service.get(s['id'],'preparer')['notifications'])==before
 s=service.task_action(s['id'],'preparer',s['version'],t['id'],'acknowledge','Investigating')
 assert next(t for t in s['tasks'] if t['kind']=='reconciliation')['status']=='acknowledged'
 with pytest.raises(ValueError):service.task_action(s['id'],'reviewer',s['version'],t['id'],'resolve','Not a manual concern')
 journal=next(d for d in s['datasets'] if any(x['id']==d['source_id'] and x['reconciliation_side']=='journal' for x in s['sources']))
 row=service.rows(s['id'],'preparer',journal['id'])['rows'][2]
 s=service.edit(s['id'],'preparer',s['version'],journal['id'],[{'op':'set_cell','row_id':row['row_id'],'column_key':'c5','value':'50'}],'Checked source')
 assert s['status']=='QUEUED'
 s=run_pending(service,s['id']);assert next(t for t in s['tasks'] if t['kind']=='reconciliation')['status']=='resolved'
 view=service.get(s['id'],'preparer');ids=[n['id'] for n in view['notifications']]
 s=service.notifications_read(s['id'],'preparer',ids);assert all(n['read_at'] for n in s['notifications'])
 assert service.reconciliation_results(s['id'],'preparer')['summary']['matched']==2

def test_revision_blocks_review_and_preserves_original(service):
 s=start(service,inputs(service));s=service.reconciliation_review(s['id'],'reviewer',s['version'],'APPROVE','Checked')
 source=s['sources'][1];doc=next(d for d in s['documents'] if d['id']==source['document_id'])
 s=service.upload(s['id'],'preparer',s['version'],'journal.csv','text/csv',base64.b64encode(DATA.replace(b',50',b',60')).decode(),document_id=doc['id'],parent_revision_id=source['id'],reason='Changed journal')
 assert not s['reconciliation'].get('review')
 assert service.download(s['id'],'preparer',source['id'])[0]==DATA
 with pytest.raises(DomainConflict):service.reconciliation_download(s['id'],'reviewer',True)
 s=run_pending(service,s['id']);assert s['reconciliation']['status']=='COMPLETE'

def test_external_participants_cannot_read_reconciliation_results(service):
 s=start(service,inputs(service))
 s=service.members(s['id'],'reviewer',s['version'],s['members']+[{'actor_id':'investor','party':'investor','document_ids':[],'request_ids':[]}])
 assert 'reconciliation' not in service.get(s['id'],'investor')
 for action in (lambda:service.reconciliation_results(s['id'],'investor'),lambda:service.reconciliation_download(s['id'],'investor')):
  with pytest.raises(DomainForbidden):action()

def test_retry_and_concurrent_start(service):
 s=inputs(service);sides={x['id']:x['reconciliation_side'] for x in s['sources']}
 first=service.reconcile(s['id'],'preparer',s['version'],sides,{},'Start','retry')
 assert service.reconcile(s['id'],'preparer',s['version'],sides,{},'Start','retry')['version']==first['version']
 with pytest.raises(DomainConflict):service.reconcile(s['id'],'preparer',s['version'],sides,{},'Other','retry')
 with pytest.raises(DomainConflict):service.reconcile(s['id'],'preparer',s['version'],sides,{},'Start')


def test_deadline_escalation_does_not_notify_unrelated_fund_manager(service):
 s=start(service,inputs(service,True))
 s=service.members(s['id'],'reviewer',s['version'],s['members']+[{'actor_id':'manager','party':'fund_manager','document_ids':[],'request_ids':[]}])
 item=service.reconciliation_results(s['id'],'preparer',status='difference')['items'][0]
 s=service.reconciliation_assign(s['id'],'reviewer',s['version'],[item['id']],'preparer','Please check this amount','2020-01-01T00:00:00+00:00')
 service.sweep_deadlines();a=service.get(s['id'],'reviewer');count=len(a['notifications']);service.sweep_deadlines()
 assert len(service.get(s['id'],'reviewer')['notifications'])==count
 assert any(n['event']=='escalated' for n in a['notifications'])
 assert service.get(s['id'],'manager')['notifications']==[]


def test_incomplete_document_cannot_establish_missing_record(service):
 s=start(service,inputs(service))
 with service._locked(s['id'],'preparer','prepare') as (_,_,state):
  source=next(x for x in state['sources'] if x['reconciliation_side']=='journal')
  source['coverage']['complete']=False
  state['datasets']=[d for d in state['datasets'] if d['source_id']!=source['id']]
  result=service._compute_reconciliation(state)
  evaluated=service._reconciliation_result(result)
  assert not evaluated['coverage']['complete']
  assert evaluated['summary']['missing']==0
  assert all(i['status']=='needs_input' for i in evaluated['items'])


def test_changed_header_does_not_inherit_cash_mapping(service):
 s=start(service,inputs(service))
 source=next(x for x in s['sources'] if x['reconciliation_side']=='journal')
 changed=DATA.replace(b'reference,account,currency,date,amount',b'reference,account,currency,date,unexplained_value')
 s=service.upload(s['id'],'preparer',s['version'],'journal.csv','text/csv',base64.b64encode(changed).decode(),document_id=source['document_id'],parent_revision_id=source['id'],reason='Changed header meaning')
 s=run_pending(service,s['id'])
 result=service.reconciliation_results(s['id'],'preparer')
 assert result['summary']['matched']==0
 assert result['summary']['needs_input']>0
 with pytest.raises(DomainConflict):service.reconciliation_review(s['id'],'reviewer',s['version'],'APPROVE','Cannot infer changed meaning')
