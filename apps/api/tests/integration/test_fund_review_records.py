"""Complete finding records and narrow formula scope over real PostgreSQL.

These small fixtures exercise service contracts; private/public source accuracy
and large-file acceptance remain separate from these regression cases.
"""
import base64
from copy import deepcopy
import csv
from io import BytesIO, StringIO
import json
from xml.etree import ElementTree as ET
import zipfile

from openpyxl import Workbook
import pytest

from closegraph.api.ports import DomainConflict, DomainForbidden, DomainNotFound
from .test_evidence_collaboration import service
from .test_collections import run_pending
from .test_fund_review_journey import REFERENCE, config_for


def many_records(service):
    state = service.create('preparer', 'Full records contract', 'fund-a')
    stream = StringIO(newline='')
    writer = csv.writer(stream)
    writer.writerow(['Investor ID', 'Amount', 'Amount'])
    for i in range(63):
        writer.writerow(['missing', '=1+1' if i == 0 else '\t=HYPERLINK("invalid")' if i == 1 else str(i), 'second-' + str(i)])
    for name, content in [('activity.csv', stream.getvalue().encode()), ('Investor List.csv', REFERENCE)]:
        state = service.upload(state['id'], 'preparer', state['version'], name, 'text/csv',
                               base64.b64encode(content).decode(), defer_processing=True)
    state = service.process(state['id'], 'preparer', state['version'])
    state = run_pending(service, state['id'])
    state = service.fund_review_start(state['id'], 'preparer', state['version'], config_for(service, state), 'Inspect the selected reference membership')
    state = run_pending(service, state['id'])
    item = service.fund_review_results(state['id'], 'preparer', status='difference')['findings'][0]
    return state, item


def test_all_63_affected_rows_are_paginated_and_exported_without_losing_duplicate_values(service):
    state, item = many_records(service)
    assert item['affected_count'] == item['records_total'] == 63
    assert item['records_complete'] and len(item['evidence']) == 12
    assert '_record_refs' not in json.dumps(service.fund_review_results(state['id'], 'preparer'))
    first = service.fund_review_records(state['id'], 'preparer', item['id'], 0, 50)
    second = service.fund_review_records(state['id'], 'reviewer', item['id'], 50, 50)
    assert first['complete'] and second['complete']
    assert first['total'] == second['total'] == 63
    assert len(first['records']) == 50 and len(second['records']) == 13
    records = first['records'] + second['records']
    assert len({r['row_id'] for r in records}) == 63
    assert records[0]['source_name'] == 'activity.csv'
    assert records[0]['values']['c2'] == '=1+1'
    assert records[-1]['values']['c3'] == 'second-62'
    assert [c['label'] for c in records[0]['columns']] == ['Investor ID', 'Amount', 'Amount']
    assert service.get(state['id'], 'preparer')['version'] == state['version']
    content, media_type, filename = service.fund_review_records_download(state['id'], 'preparer', item['id'])
    assert filename == 'affected-reporting-records.csv' and media_type.startswith('text/csv')
    rows = list(csv.reader(StringIO(content.decode('utf-8-sig'))))
    assert len(rows) == 64 and len(set(rows[0])) == len(rows[0])
    assert len(rows[1]) == len(rows[0])
    amount = rows[0].index('Amount')
    second_amount = rows[0].index('Amount (2)')
    assert rows[1][amount] == "'=1+1"
    assert rows[2][amount].startswith("'\t=")
    assert rows[-1][second_amount] == 'second-62'
    assert all(row[0] == 'activity.csv' and row[4] == 'Difference' for row in rows[1:])


def test_finding_record_access_is_internal_scoped_and_stale_results_require_rerun(service):
    state, item = many_records(service)
    state = service.members(state['id'], 'reviewer', state['version'], state['members'] + [
        {'actor_id': 'investor', 'party': 'investor', 'document_ids': [state['sources'][0]['document_id']], 'request_ids': []}])
    for action in (lambda: service.fund_review_records(state['id'], 'investor', item['id']),
                   lambda: service.fund_review_records_download(state['id'], 'investor', item['id'])):
        with pytest.raises(DomainForbidden):
            action()
    with pytest.raises(DomainNotFound):
        service.fund_review_records(state['id'], 'other-investor', item['id'])
    with pytest.raises(DomainNotFound):
        service.fund_review_records(state['id'], 'preparer', 'unknown-finding')
    evidence = item['evidence'][0]
    state = service.edit(state['id'], 'preparer', state['version'], evidence['dataset_id'],
                         [{'op': 'set_cell', 'row_id': evidence['row_id'], 'column_key': 'c1', 'value': 'I-1'}],
                         'Correct one identifier; its previous index is no longer current')
    with pytest.raises(DomainConflict):
        service.fund_review_records(state['id'], 'preparer', item['id'])
    with pytest.raises(DomainConflict):
        service.fund_review_records_download(state['id'], 'preparer', item['id'])


def test_legacy_sampled_results_never_claim_a_complete_record_download(service):
    state, item = many_records(service)
    with service._locked(state['id'], 'preparer', 'history') as (session, row, stored):
        result = service._fund_review_result(stored)
        for finding in result['findings']:
            for name in ('_record_refs', 'records_complete', 'records_total'):
                finding.pop(name, None)
        stored['fund_review']['result_hash'] = service._store(stored, result)
        service._revision(session, row, stored, 'system', 'restore_legacy_result_for_contract')
    listed = service.fund_review_results(state['id'], 'preparer', status='difference')['findings'][0]
    assert listed['records_complete'] is False
    page = service.fund_review_records(state['id'], 'preparer', item['id'])
    assert page['complete'] is False and page['total'] == 63
    assert len(page['records']) == 12 and 'again' in page['message']
    with pytest.raises(DomainConflict):
        service.fund_review_records_download(state['id'], 'preparer', item['id'])


def cached_formula_workbook():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'Activity'
    sheet.append(['Investor ID', 'Amount', 'Unreviewed calculation'])
    sheet.append(['I-1', 10, '=1+1'])
    sheet.append(['I-2', 20, '=2+2'])
    stream = BytesIO()
    workbook.save(stream)
    output = BytesIO()
    ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    with zipfile.ZipFile(BytesIO(stream.getvalue())) as source, zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as target:
        for member in source.infolist():
            content = source.read(member)
            if member.filename == 'xl/worksheets/sheet1.xml':
                root = ET.fromstring(content)
                for cell in root.iter(ns + 'c'):
                    if cell.find(ns + 'f') is not None:
                        cell.find(ns + 'v').text = '2' if cell.attrib['r'] == 'C2' else '4'
                content = ET.tostring(root)
            target.writestr(member, content)
    return output.getvalue()


def test_unrelated_formula_warning_allows_only_selected_scope_approval_and_stays_visible(service):
    state = service.create('preparer', 'Narrow formula scope contract', 'fund-a')
    workbook = cached_formula_workbook()
    state = service.upload(state['id'], 'preparer', state['version'], 'activity.xlsx',
                           'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', base64.b64encode(workbook).decode())
    state = run_pending(service, state['id'])
    dataset = state['datasets'][0]
    rows = service.rows(state['id'], 'preparer', dataset['id'])['rows']
    config = {'checks': [{'id': 'required-investor', 'title': 'Investor identifier is present', 'kind': 'required', 'confirmed': True,
                         'left': {'dataset_id': dataset['id'], 'columns': ['c1'], 'header_row_id': rows[0]['row_id']}}]}
    state = service.fund_review_start(state['id'], 'preparer', state['version'], config, 'Review the identifier column only')
    state = run_pending(service, state['id'])
    main = service.fund_review_results(state['id'], 'preparer', blocking=True)
    notes = service.fund_review_results(state['id'], 'preparer', blocking=False)
    assert main['total'] == 1 and main['findings'][0]['status'] == 'passed'
    assert notes['total'] == 1 and notes['findings'][0]['kind'] == 'formula_scope'
    assert notes['findings'][0]['blocking'] is False
    assert notes['summary']['blocking_needs_input'] == 0
    assert notes['summary']['nonblocking_needs_input'] == 1
    assert not notes['summary']['financially_verified']
    formula_rows = service.fund_review_records(state['id'], 'reviewer', notes['findings'][0]['id'])
    assert formula_rows['complete'] and formula_rows['total'] == 2
    state = service.fund_review_review(state['id'], 'reviewer', state['version'], 'APPROVE', 'Only the declared identifier check was independently reviewed')
    content = service.fund_review_download(state['id'], 'reviewer', True)[0]
    assert b'formulas have not been verified' in content
    assert service.download(state['id'], 'reviewer', state['sources'][0]['id'])[0] == workbook
    state = service.get(state['id'], 'preparer')
    changed = deepcopy(config)
    changed['checks'][0]['left']['columns'] = ['c3']
    state = service.fund_review_start(state['id'], 'preparer', state['version'], changed, 'Now request verification of the formula column')
    state = run_pending(service, state['id'])
    result = service.fund_review_results(state['id'], 'preparer', blocking=True)
    assert result['summary']['blocking_needs_input'] > 0
    with pytest.raises(DomainConflict):
        service.fund_review_review(state['id'], 'reviewer', state['version'], 'APPROVE', 'The selected formula cache is not verified')
    observed = service.rows(state['id'], 'preparer', dataset['id'])['rows'][1]
    assert observed['metadata']['cells']['c3']['formula']['cache_verified'] is False
