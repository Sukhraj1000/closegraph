from copy import deepcopy
import base64
import pytest
from sqlalchemy import select
from closegraph.api.auth import LocalAuth, DevAccount
from closegraph.api.ports import DomainConflict, DomainForbidden, DomainNotFound
from closegraph.collections.account_migration import migrate_business_accounts, renamed_metadata
from closegraph.collections.models import CollectionRow, CollectionRevisionRow
from .test_evidence_collaboration import service


def test_metadata_does_not_rewrite_evidence_or_user_text():
    raw = {'contributors':['preparer'], 'owner_actor_id':'reviewer',
           'values':{'actor_id':'preparer'}, 'reason':'preparer',
           'recipe':{'actor_id':'reviewer'}, 'history':[{'actor_id':'preparer'}]}
    after = renamed_metadata(raw)
    assert after['contributors'] == ['accountant']
    assert after['owner_actor_id'] == 'account_manager'
    assert after['values'] == raw['values'] and after['recipe'] == raw['recipe']
    assert after['reason'] == raw['reason']
    assert after['history'][0]['actor_id'] == 'accountant'


def test_account_migration_retains_files_history_scope_and_is_idempotent(service):
    state = service.create('preparer', 'Keep the original', 'fund-a')
    raw = b'actor_id,amount\npreparer,12.34\nreviewer,45.67\n'
    state = service.upload(state['id'], 'preparer', state['version'], 'original.csv', 'text/csv',
                           base64.b64encode(raw).decode(), defer_processing=True)
    state = service.flag(state['id'], 'preparer', state['version'], 'Question for manager', 'Please check the evidence', 'reviewer')
    with service.sessions() as session:
        history = [(r.version, deepcopy(r.state), r.actor_id) for r in session.scalars(select(CollectionRevisionRow)).all()]
        original = deepcopy(session.get(CollectionRow, state['id']).state)
    assert migrate_business_accounts(service) == [state['id']]
    assert migrate_business_accounts(service) == []
    with service.sessions() as session:
        current = session.get(CollectionRow, state['id']).state
        for version, snapshot, actor in history:
            old = session.get(CollectionRevisionRow, (state['id'], version))
            assert old.state == snapshot and old.actor_id == actor
    assert current['version'] == original['version']+1
    assert current['sources'][0]['content_hash'] == original['sources'][0]['content_hash']
    assert service._blobs(current).get(current['sources'][0]['content_hash']) == raw
    assert current['sources'][0]['uploaded_by'] == 'accountant'
    assert current['contributors'] == ['accountant']
    assert current['tasks'][0]['owner_actor_id'] == 'account_manager'
    assert current['tasks'][0]['created_by'] == 'accountant'
    assert current['notifications'][0]['recipient_actor_id'] == 'account_manager'
    assert {m['actor_id'] for m in current['members']} == {'accountant', 'account_manager'}
    scope = (current['tenant_id'], current['fund_id'])
    service.auth = LocalAuth(accounts=[DevAccount.create(n,n+'-password',r,()) for n,r in
                            [('accountant','PREPARER'),('account_manager','REVIEWER'),('investor','INVESTOR')]],
                            collection_grants={n:{scope} for n in ['accountant','account_manager','investor']})
    assert service.get(state['id'],'accountant')['access']['can_prepare']
    assert service.get(state['id'],'account_manager')['access']['can_manage']
    assert service.history(state['id'],'accountant')[0]['actor_id'] == 'accountant'
    with pytest.raises((DomainForbidden, DomainNotFound)):
        service.get(state['id'], 'investor')


def test_migration_refuses_pending_processing_without_partial_changes(service):
    state = service.create('preparer','Busy work','fund-a')
    state = service.upload(state['id'],'preparer',state['version'],'data.csv','text/csv',
                           base64.b64encode(b'Amount\n1\n').decode(),defer_processing=True)
    state = service.process(state['id'],'preparer',state['version'])
    with pytest.raises(DomainConflict):
        migrate_business_accounts(service)
    assert service.get(state['id'],'preparer')['version'] == state['version']


def test_requirement_account_change_invalidates_exact_review(service):
    state = service.create('preparer', 'Rule owners', 'fund-a')
    with service._locked(state['id'], 'preparer', 'prepare') as (session,row,current):
        current['requirements'] = [{'id':'rule','owner_actor_id':'reviewer','parameters':{'rule_approved_by':'reviewer'}}]
        current['fund_review'] = {'status':'COMPLETE','fingerprint':'original','review':{'decision':'APPROVE','actor_id':'reviewer','fingerprint':'original'}}
        service._revision(session,row,current,'preparer','fixture_setup')
    migrate_business_accounts(service)
    with service.sessions() as session:
        current = session.get(CollectionRow,state['id']).state
    assert current['requirements'][0]['parameters']['rule_approved_by'] == 'account_manager'
    assert current['requirements_version'] == 1
    assert current['fund_review']['status'] == 'STALE'
    assert current['fund_review'].get('review') is None
    assert current['notifications'][0]['recipient_actor_id'] == 'account_manager'
