"""Real-PostgreSQL reporting review contracts, separate from private-file accuracy acceptance."""
import base64
from copy import deepcopy

import pytest

from closegraph.api.ports import DomainConflict, DomainForbidden, DomainNotFound
from .test_evidence_collaboration import service
from .test_collections import run_pending

ACTIVITY = b'Investor ID,Amount\nI-1,10.00\nI-2,20.00\n'
REFERENCE = b'Investor ID,Investor Name\nI-1,First investor\nI-2,Second investor\n'


def upload_pack(service, *, missing=False):
    state = service.create('preparer', 'Reporting review service contract', 'fund-a')
    for name, content in [('activity.csv', ACTIVITY.replace(b'I-2', b'I-3') if missing else ACTIVITY),
                          ('Investor List.csv', REFERENCE)]:
        state = service.upload(state['id'], 'preparer', state['version'], name, 'text/csv',
                               base64.b64encode(content).decode(), defer_processing=True,
                               idempotency_key='upload-' + name)
    state = service.process(state['id'], 'preparer', state['version'])
    return run_pending(service, state['id'])


def config_for(service, state):
    sides = {}
    for dataset in state['datasets']:
        source = next(s for s in state['sources'] if s['id'] == dataset['source_id'])
        name = 'left' if source['filename'] == 'activity.csv' else 'right'
        sides[name] = {'dataset_id': dataset['id'], 'column': 'c1',
                       'header_row_id': service.rows(state['id'], 'preparer', dataset['id'])['rows'][0]['row_id']}
    return {'checks': [{'id': 'investor-membership', 'title': 'Check the selected investor list',
                        'kind': 'reference', 'confirmed': True, **sides}],
            'table_headers': [{'dataset_id': s['dataset_id'], 'header_row_id': s['header_row_id']} for s in sides.values()]}


def review_pack(service, *, missing=False):
    state = upload_pack(service, missing=missing)
    config = config_for(service, state)
    state = service.fund_review_start(state['id'], 'preparer', state['version'], config,
                                      'Check membership against this explicitly selected reference list')
    return run_pending(service, state['id'])


def finding(service, state):
    result = service.fund_review_results(state['id'], 'preparer', status='difference')
    assert result['total'] == 1, result
    return result['findings'][0]


def task(state):
    return next(t for t in state['tasks'] if t['kind'] == 'fund_review')


def correct_investor(service, state, investor='I-2'):
    left = state['fund_review']['config']['checks'][0]['left']
    rows = service.rows(state['id'], 'preparer', left['dataset_id'])['rows']
    return service.edit(state['id'], 'preparer', state['version'], left['dataset_id'],
                        [{'op': 'set_cell', 'row_id': rows[2]['row_id'], 'column_key': 'c1', 'value': investor}],
                        'Correct this selected identifier against the original source')


def assign(service, state, owner='preparer'):
    item = finding(service, state)
    return service.fund_review_assign(state['id'], 'reviewer', state['version'], [item['id']], owner,
                                     'Please confirm the identifier for this assigned finding')


def test_fund_review_upload_correct_independent_approval_and_export(service):
    state = review_pack(service, missing=True)
    result = service.fund_review_results(state['id'], 'preparer')
    assert result['summary']['source_count'] == 2
    assert result['summary']['difference'] == 1
    assert not result['stale'] and result['coverage']['complete']
    original = state['sources'][0]
    assert service.download(state['id'], 'preparer', original['id'])[0] == ACTIVITY.replace(b'I-2', b'I-3')
    with pytest.raises(DomainConflict):
        service.fund_review_review(state['id'], 'reviewer', state['version'], 'APPROVE', 'Outstanding difference')
    content, media_type, filename = service.fund_review_download(state['id'], 'preparer')
    assert media_type == 'text/html' and filename == 'working-fund-review.html'
    assert b'Working review' in content and b'I-3' in content
    state = service.get(state['id'], 'preparer')
    state = assign(service, state)
    state = correct_investor(service, state)
    assert state['status'] == 'QUEUED'
    state = run_pending(service, state['id'])
    result = service.fund_review_results(state['id'], 'preparer')
    assert result['summary']['difference'] == 0
    assert result['changes']['fixed'] == 1
    assert task(state)['status'] == 'resolved'
    assert service.download(state['id'], 'preparer', original['id'])[0] == ACTIVITY.replace(b'I-2', b'I-3')
    with pytest.raises(DomainForbidden):
        service.fund_review_review(state['id'], 'preparer', state['version'], 'APPROVE', 'Self approval is prohibited')
    state = service.fund_review_review(state['id'], 'reviewer', state['version'], 'APPROVE',
                                       'Independently inspected the exact source versions and selected membership check')
    content, _, filename = service.fund_review_download(state['id'], 'reviewer', True)
    assert filename == 'reviewed-fund-review.html'
    assert b'Reviewed for the selected checks' in content
    assert b'Original Excel files and formulas are unchanged' in content
    assert b'These results cover the selected checks only' in content


def test_assignment_is_deduplicated_and_read_or_manual_resolve_cannot_close(service):
    state = review_pack(service, missing=True)
    item = finding(service, state)
    state = assign(service, state)
    before = len(service.get(state['id'], 'preparer')['notifications'])
    state = service.fund_review_assign(state['id'], 'reviewer', state['version'], [item['id']], 'preparer',
                                       'Please confirm the identifier for this assigned finding')
    assert len([t for t in state['tasks'] if t['kind'] == 'fund_review']) == 1
    assert len(service.get(state['id'], 'preparer')['notifications']) == before
    request = task(state)
    state = service.task_action(state['id'], 'preparer', state['version'], request['id'], 'acknowledge', 'Investigating the source')
    assert task(state)['status'] == 'acknowledged'
    with pytest.raises(ValueError):
        service.task_action(state['id'], 'reviewer', state['version'], request['id'], 'resolve', 'This is not a manual concern')
    notices = service.get(state['id'], 'preparer')['notifications']
    state = service.notifications_read(state['id'], 'preparer', [n['id'] for n in notices])
    assert task(state)['status'] == 'acknowledged'


def test_changing_missing_identifier_to_another_missing_value_keeps_request_open(service):
    state = assign(service, review_pack(service, missing=True))
    state = correct_investor(service, state, 'I-4')
    state = run_pending(service, state['id'])
    result = service.fund_review_results(state['id'], 'preparer')
    assert result['summary']['difference'] == 1
    assert task(state)['status'] != 'resolved'
    assert result['changes']['fixed'] == 0
    assert not any(e['action'] == 'verification_passed' for e in task(state)['events'])


def test_withdrawing_or_changing_check_does_not_falsely_resolve_request(service):
    state = assign(service, review_pack(service, missing=True))
    config = deepcopy(state['fund_review']['config'])
    config['checks'] = []
    state = service.fund_review_start(state['id'], 'preparer', state['version'], config,
                                      'Remove this check from the current scope; do not claim it passed')
    state = run_pending(service, state['id'])
    result = service.fund_review_results(state['id'], 'preparer')
    assert task(state)['status'] != 'resolved'
    assert result['changes']['withdrawn'] >= 1 and result['changes']['fixed'] == 0
    with pytest.raises(DomainConflict):
        service.fund_review_review(state['id'], 'reviewer', state['version'], 'APPROVE', 'No selected checks')


def test_changed_shared_header_does_not_retain_prior_rule_authority(service):
    state = review_pack(service, missing=True)
    left_id = state['fund_review']['config']['checks'][0]['left']['dataset_id']
    source_rows = service.rows(state['id'], 'preparer', left_id)['rows']
    state = service.edit(state['id'], 'preparer', state['version'], left_id, [
        {'op': 'set_cell', 'row_id': source_rows[1]['row_id'], 'column_key': 'c1', 'value': 'I-3'},
        {'op': 'set_cell', 'row_id': source_rows[2]['row_id'], 'column_key': 'c1', 'value': 'I-1'}],
        'Reorder the source identifiers for the scope-change regression')
    state = run_pending(service, state['id'])
    config = deepcopy(state['fund_review']['config'])
    config['checks'][0]['left'].pop('header_row_id')
    state = service.fund_review_start(state['id'], 'preparer', state['version'], config, 'Use the explicitly confirmed shared header')
    state = run_pending(service, state['id'])
    state = assign(service, state)
    left = config['checks'][0]['left']['dataset_id']
    rows = service.rows(state['id'], 'preparer', left)['rows']
    # Moving the header changes the evaluated row scope; it is a rule change,
    # never evidence that the previously missing investor was corrected.
    config['table_headers'][0 if config['table_headers'][0]['dataset_id'] == left else 1]['header_row_id'] = rows[1]['row_id']
    state = service.fund_review_start(state['id'], 'preparer', state['version'], config, 'Changed row scope must be reviewed')
    state = run_pending(service, state['id'])
    assert task(state)['status'] != 'resolved'
    assert service.fund_review_results(state['id'], 'preparer')['changes']['fixed'] == 0


def test_investor_release_grants_request_only_and_attachment_does_not_resolve(service):
    state = review_pack(service, missing=True)
    state = service.members(state['id'], 'reviewer', state['version'], state['members'] + [
        {'actor_id': 'investor', 'party': 'investor', 'document_ids': [], 'request_ids': []}])
    state = assign(service, state, 'investor')
    request = task(state)
    assert service.get(state['id'], 'investor')['tasks'] == []
    state = service.task_action(state['id'], 'reviewer', state['version'], request['id'], 'release',
                                'Share only this specific investor request')
    view = service.get(state['id'], 'investor')
    assert len(view['tasks']) == 1 and view['sources'] == [] and view['datasets'] == []
    assert 'fund_review' not in view
    for key in ['rule_signatures', 'item_ids', 'match_keys', 'check_ids', 'evaluation_fingerprint']:
        assert key not in view['tasks'][0]
    with pytest.raises(DomainForbidden):
        service.fund_review_results(state['id'], 'investor')
    with pytest.raises(DomainForbidden):
        service.fund_review_download(state['id'], 'investor')
    with pytest.raises(DomainNotFound):
        service.download(state['id'], 'investor', state['sources'][0]['id'])
    state = service.upload(state['id'], 'investor', state['version'], 'my-response.csv', 'text/csv',
                           base64.b64encode(b'Investor ID,Comment\nI-3,Please check the administrator record\n').decode(),
                           task_id=request['id'], idempotency_key='investor-response')
    assert task(state)['status'] == 'evidence_received'
    state = run_pending(service, state['id'])
    assert task(state)['status'] != 'resolved'
    attached = task(state)['response_document_ids']
    assert len(attached) == 1
    view = service.get(state['id'], 'investor')
    assert all(s['document_id'] in attached for s in view['sources'])
    assert service.list('other-investor') == []


def test_retry_conflict_and_stale_async_completion_are_safe(service):
    state = upload_pack(service)
    config = config_for(service, state)
    original_version = state['version']
    queued = service.fund_review_start(state['id'], 'preparer', original_version, config, 'Initial review', 'same-command')
    retried = service.fund_review_start(state['id'], 'preparer', original_version, config, 'Initial review', 'same-command')
    assert retried['version'] == queued['version']
    with pytest.raises(DomainConflict):
        service.fund_review_start(state['id'], 'preparer', original_version, config, 'Different reason', 'same-command')
    with pytest.raises(DomainConflict):
        service.fund_review_start(state['id'], 'preparer', original_version, config, 'Initial review')
    request = next(j for j in service.pending() if j['collection_id'] == state['id'] and j['status'] == 'PENDING')
    run_id = 'fund-review-superseded-run'
    job = service.claim(request['id'], run_id)
    computed = service.compute(job)
    source = next(s for s in queued['sources'] if s['filename'] == 'activity.csv')
    newer = service.upload(queued['id'], 'preparer', queued['version'], 'activity.csv', 'text/csv',
                           base64.b64encode(ACTIVITY.replace(b'I-2', b'I-3')).decode(),
                           document_id=source['document_id'], parent_revision_id=source['id'],
                           reason='A newer upload supersedes the running snapshot')
    assert service.finish(request['id'], run_id, computed)['applied'] is False
    state = run_pending(service, newer['id'])
    assert service.fund_review_results(state['id'], 'preparer')['summary']['difference'] == 1


def test_unchanged_headers_rebind_revisions_and_changed_meaning_blocks_approval(service):
    state = review_pack(service)
    state = service.fund_review_review(state['id'], 'reviewer', state['version'], 'APPROVE', 'Independently checked membership')
    source = next(s for s in state['sources'] if s['filename'] == 'activity.csv')
    previous_dataset = state['fund_review']['config']['checks'][0]['left']['dataset_id']
    replacement = ACTIVITY.replace(b'I-1,10.00\nI-2,20.00', b'I-2,20.00\nI-1,10.00')
    state = service.upload(state['id'], 'preparer', state['version'], 'activity.csv', 'text/csv',
                           base64.b64encode(replacement).decode(), document_id=source['document_id'],
                           parent_revision_id=source['id'], reason='Reordered the records in Excel')
    assert not state['fund_review'].get('review')
    with pytest.raises(DomainConflict):
        service.fund_review_download(state['id'], 'reviewer', True)
    state = run_pending(service, state['id'])
    result = service.fund_review_results(state['id'], 'preparer')
    assert result['summary']['difference'] == 0 and result['summary']['needs_input'] == 0
    assert state['fund_review']['config']['checks'][0]['left']['dataset_id'] != previous_dataset
    assert service.download(state['id'], 'preparer', source['id'])[0] == ACTIVITY
    current = next(s for s in state['sources'] if s['document_id'] == source['document_id'] and s['id'] != source['id'])
    state = service.upload(state['id'], 'preparer', state['version'], 'activity.csv', 'text/csv',
                           base64.b64encode(replacement.replace(b'Investor ID', b'Unexplained label')).decode(),
                           document_id=current['document_id'], parent_revision_id=current['id'], reason='Changed the meaning of the selected header')
    state = run_pending(service, state['id'])
    result = service.fund_review_results(state['id'], 'preparer')
    assert result['summary']['needs_input'] > 0
    with pytest.raises(DomainConflict):
        service.fund_review_review(state['id'], 'reviewer', state['version'], 'APPROVE', 'Cannot infer the new column meaning')



def test_removing_a_total_group_from_both_versions_is_not_a_passing_correction(service):
    state = service.create('preparer', 'Explicit grouped-total review contract', 'fund-a')
    for name, content in [('activity.csv', ACTIVITY), ('report.csv', ACTIVITY.replace(b'20.00', b'21.00'))]:
        state = service.upload(state['id'], 'preparer', state['version'], name, 'text/csv',
                               base64.b64encode(content).decode(), defer_processing=True)
    state = service.process(state['id'], 'preparer', state['version'])
    state = run_pending(service, state['id'])
    sides = {}
    for dataset in state['datasets']:
        source = next(s for s in state['sources'] if s['id'] == dataset['source_id'])
        side = 'left' if source['filename'] == 'activity.csv' else 'right'
        sides[side] = {'dataset_id': dataset['id'], 'column': 'c2', 'group_by': ['c1'],
                       'header_row_id': service.rows(state['id'], 'preparer', dataset['id'])['rows'][0]['row_id']}
    config = {'checks': [{'id': 'investor-totals', 'title': 'Compare explicitly scoped investor totals',
                          'kind': 'totals', 'confirmed': True, **sides}]}
    state = service.fund_review_start(state['id'], 'preparer', state['version'], config,
                                      'Compare these two statements in their declared fund and currency scope')
    state = run_pending(service, state['id'])
    state = assign(service, state)
    sources = deepcopy(state['sources'])
    for index, source in enumerate(sources):
        state = service.upload(state['id'], 'preparer', state['version'], source['filename'], 'text/csv',
                               base64.b64encode(b'Investor ID,Amount\nI-1,10.00\n').decode(),
                               document_id=source['document_id'], parent_revision_id=source['id'],
                               reason='Remove the previously discrepant group from this source', defer_processing=index == 0)
    state = run_pending(service, state['id'])
    result = service.fund_review_results(state['id'], 'preparer')
    assert result['summary']['difference'] == 0
    assert task(state)['status'] != 'resolved'
    assert result['changes']['fixed'] == 0


def test_identical_rerun_preserves_review_but_blocking_concern_invalidates_it(service):
    state = review_pack(service)
    state = service.fund_review_review(state['id'], 'reviewer', state['version'], 'APPROVE', 'Checked this exact scope')
    approval = deepcopy(state['fund_review']['review'])
    state = service.fund_review_start(state['id'], 'preparer', state['version'], state['fund_review']['config'], 'Repeat unchanged checks')
    state = run_pending(service, state['id'])
    assert state['fund_review']['review'] == approval
    service.fund_review_download(state['id'], 'reviewer', True)
    state = service.get(state['id'], 'reviewer')
    state = service.flag(state['id'], 'reviewer', state['version'], 'Review the accounting scope', 'The selected reference scope needs a decision', 'preparer', blocking=True)
    assert not state['fund_review'].get('review')
    assert any(n['event'] == 'fund_review_invalidated' for n in state['notifications'])
    with pytest.raises(DomainConflict):
        service.fund_review_download(state['id'], 'reviewer', True)
