"""Evidence-led collaboration using real PostgreSQL, native inputs and scoped actors."""
import base64
from copy import deepcopy
import pytest
from closegraph.api.auth import DevAccount,LocalAuth
from closegraph.api.ports import DomainConflict,DomainForbidden,DomainNotFound
from closegraph.collections.service import CollectionServices
from closegraph.storage.blobs import LocalBlobStore
from .test_collections import PASSWORD,DATA,create,upload,run_pending,extracted,define_recipe,ready,approve,output_dataset

@pytest.fixture
def service(pg_sessions,tmp_path):
    roles=[('preparer','PREPARER'),('reviewer','REVIEWER'),('manager','FUND_MANAGER'),('investor','INVESTOR'),('other-investor','INVESTOR')]
    accounts=[DevAccount.create(n,PASSWORD,r,[]) for n,r in roles]
    auth=LocalAuth(accounts=accounts,collection_grants={n:[('tenant-a','fund-a')] for n,r in roles})
    return CollectionServices(pg_sessions,LocalBlobStore(tmp_path/'blobs',max_bytes=32*1024*1024),auth)

def test_upload_retry_and_revision_parent(service):
    s=create(service);args=(s['id'],'preparer',s['version'],'ledger.csv','text/csv',base64.b64encode(DATA).decode())
    first=service.upload(*args,idempotency_key='first')
    retry=service.upload(*args,idempotency_key='first')
    assert retry['version']==first['version'] and len(retry['sources'])==1
    with pytest.raises(DomainConflict):service.upload(*args[:-1],base64.b64encode(DATA+b'new').decode(),idempotency_key='first')
    first=run_pending(service,first['id']);doc=first['documents'][0];old=first['sources'][0]
    second=service.upload(first['id'],'preparer',first['version'],'ledger.csv','text/csv',base64.b64encode(DATA.replace(b'12.30',b'13.30')).decode(),document_id=doc['id'],parent_revision_id=old['id'],reason='Correct amount',idempotency_key='second')
    assert len(second['documents'])==1 and len(second['sources'])==2
    assert service.download(first['id'],'preparer',old['id'])[0]==DATA
    with pytest.raises((ValueError,DomainConflict)):
        service.upload(second['id'],'preparer',second['version'],'ledger.csv','text/csv',base64.b64encode(DATA).decode(),document_id=doc['id'],parent_revision_id=old['id'],reason='stale parent')
    second=run_pending(service,second['id'])
    c=second['comparisons'][0];page=service.comparison(second['id'],'reviewer',c['id'],0,1)
    assert page['total']>=1 and len(page['changes'])==1

def test_empty_check_policy_never_approves(service):
    s,d,k=extracted(service);s=service.accept(s['id'],'preparer',s['version'])
    s=service.recipe(s['id'],'preparer',s['version'],{'version':1,'steps':[],'output':d['id'],'checks':[]})
    s=service.process(s['id'],'preparer',s['version']);s=run_pending(service,s['id'])
    assert not s['financial_verified']
    with pytest.raises(DomainConflict):approve(service,s)

def test_investors_need_explicit_membership_and_document_grants(service):
    s=upload(service,create(service));s=run_pending(service,s['id'])
    assert service.list('investor')==[]
    with pytest.raises(DomainNotFound):service.get(s['id'],'investor')
    s=service.members(s['id'],'reviewer',s['version'],s['members']+[{'actor_id':'investor','party':'investor','document_ids':[],'request_ids':[]}])
    view=service.get(s['id'],'investor')
    assert view['access']['restricted'] and view['sources']==[] and view['datasets']==[]
    with pytest.raises(DomainNotFound):service.download(s['id'],'investor',s['sources'][0]['id'])
    with pytest.raises(DomainForbidden):service.history(s['id'],'investor')
    with pytest.raises(DomainForbidden):service.requirements(s['id'],'investor',s['version'],[])
    assert service.list('other-investor')==[]

def test_manual_investor_request_release_dedup_and_resolution(service):
    s=create(service)
    s=service.members(s['id'],'reviewer',s['version'],s['members']+[{'actor_id':'investor','party':'investor','document_ids':[],'request_ids':[]}])
    old=s
    s=service.flag(s['id'],'reviewer',s['version'],'Please supply your statement','Required for this period','investor',idempotency_key='flag1')
    retry=service.flag(old['id'],'reviewer',old['version'],'Please supply your statement','Required for this period','investor',idempotency_key='flag1')
    assert s['version']==retry['version'] and service.get(s['id'],'investor')['tasks']==[]
    t=s['tasks'][0];s=service.task_action(s['id'],'reviewer',s['version'],t['id'],'release','Authorised request')
    assert len(service.get(s['id'],'investor')['tasks'])==1
    s=service.task_action(s['id'],'investor',s['version'],t['id'],'acknowledge','I will provide it',idempotency_key='ack')
    assert s['tasks'][0]['status']=='acknowledged'
    s=service.upload(s['id'],'investor',s['version'],'response.csv','text/csv',base64.b64encode(DATA).decode(),task_id=t['id'],idempotency_key='response')
    assert s['tasks'][0]['status']=='evidence_received'
    run_pending(service,s['id']);s=service.get(s['id'],'reviewer')
    with pytest.raises(DomainForbidden):service.task_action(s['id'],'investor',s['version'],t['id'],'resolve','Done')
    s=service.task_action(s['id'],'reviewer',s['version'],t['id'],'resolve','Compared the supplied evidence')
    assert next(item for item in s['tasks'] if item['id']==t['id'])['status']=='resolved'

def test_persisted_evidence_and_independent_approval(service):
    s,d,k=ready(service)
    assert s['financial_verified'] and s['check_results']
    assert s['recipe_checks']
    with pytest.raises(DomainForbidden):service.review(s['id'],'preparer',s['version'],'APPROVE','Self')
    s=approve(service,s)
    result=service.export(s['id'],'reviewer',s['version'],output_dataset(s)['id'],'csv')
    manifest=service.download(s['id'],'reviewer',result['manifest_url'].split('/')[-1],artifact=True)[0]
    assert b'check_results' in manifest and b'requirements' in manifest

def test_blocking_manual_flag_revokes_release(service):
    s,d,k=ready(service);s=approve(service,s)
    s=service.flag(s['id'],'reviewer',s['version'],'Investigate treatment','Unresolved treatment','preparer',blocking=True)
    with pytest.raises(DomainConflict):service.export(s['id'],'reviewer',s['version'],output_dataset(s)['id'],'csv')

def test_unrelated_document_preserves_exact_output_approval(service):
    s,d,k=ready(service);s=approve(service,s);review=deepcopy(s['review'])
    s=service.upload(s['id'],'preparer',s['version'],'unrelated.csv','text/csv',base64.b64encode(b'Note\nUnrelated source\n').decode(),idempotency_key='unrelated')
    s=run_pending(service,s['id'])
    assert s['status']=='APPROVED' and s['review']==review
    service.export(s['id'],'reviewer',s['version'],output_dataset(s)['id'],'csv')

def test_recipe_change_clears_old_verification(service):
    s,d,k=ready(service)
    recipe=deepcopy(s['recipe']);recipe['checks']=[]
    s=service.recipe(s['id'],'preparer',s['version'],recipe)
    assert not s['recipe_checks'] and not s['financial_verified']
    s=service.evaluate(s['id'],'reviewer',s['version']);s=run_pending(service,s['id'])
    assert not s['financial_verified'] and s['status']!='READY_FOR_REVIEW'

def test_required_failure_cannot_be_manually_resolved(service):
    s,d,k=extracted(service);s=service.accept(s['id'],'preparer',s['version'])
    source=s['sources'][0]
    s=service.requirements(s['id'],'reviewer',s['version'],[{'id':'actual-total','title':'Agreed total','kind':'total','owner_actor_id':'preparer','owner_party':'accountant','blocking':True,'document_ids':[source['document_id']],'dataset_selector':{'document_id':source['document_id'],'table_title':d['title']},'parameters':{'column':k['amount'],'expected':'999','tolerance':'0'}}])
    s=service.evaluate(s['id'],'reviewer',s['version']);s=run_pending(service,s['id'])
    check=s['check_results'][0];assert check['outcome']=='FAIL'
    task=next(t for t in s['tasks'] if t.get('requirement_id')=='actual-total')
    assert task['owner_actor_id']=='preparer'
    with pytest.raises(ValueError):service.task_action(s['id'],'reviewer',s['version'],task['id'],'resolve','Override')


def test_unreleased_investor_task_does_not_leak_when_resolved(service):
    s=create(service)
    s=service.members(s['id'],'reviewer',s['version'],s['members']+[{'actor_id':'investor','party':'investor','document_ids':[],'request_ids':[]}])
    s=service.flag(s['id'],'reviewer',s['version'],'Unreleased concern','Internal triage before sending','investor')
    private=deepcopy(s);private['tasks'][0]['status']='resolved'
    assert service._visible_tasks(private,'investor')==[]


def test_manager_can_configure_comparison_without_becoming_preparer(service):
    s,d,k=ready(service)
    s=service.configure_document(s['id'],'reviewer',s['version'],s['documents'][0]['id'],{'csv':{'columns':['A'],'header_row':1}})
    s=run_pending(service,s['id']);assert s['status']=='READY_FOR_REVIEW'
    assert 'reviewer' not in s['contributors']
    assert approve(service,s)['status']=='APPROVED'
