"""Synthetic audit projections; storage/locking are stubbed, no providers or SQL."""
import csv
import json
from contextlib import contextmanager
from copy import deepcopy
from io import StringIO

import pytest

from closegraph.collections.editing import apply_edits
from closegraph.collections.fund_review import _evidence, analyze
from closegraph.collections.fund_review_service import FundReviewMixin


def source_table():
    return {
        'dataset_id': 'activity', 'table_id': 'activity', 'source_id': 'source',
        'title': 'Activity', 'coverage': {'complete': True},
        'columns': [{'key': 'c1', 'label': 'Investor ID'}, {'key': 'c2', 'label': 'Amount'}],
        'rows': [
            {'row_id': 'r1', 'values': {'c1': '001', 'c2': '=1+1'},
             'locators': {'c1': {'kind': 'csv', 'row': 2}, 'c2': {'kind': 'csv', 'row': 2}}},
            {'row_id': 'r2', 'values': {'c1': '002', 'c2': None}},
        ],
    }


def edit(table, column, value, actor='preparer', reason='Checked source', row_id='r1'):
    apply_edits(table, [{'op': 'set_cell', 'row_id': row_id, 'column_key': column, 'value': value}],
                [], reason, actor)


class RecordService(FundReviewMixin):
    """Exercise the real finding, page projection and CSV code with in-memory rows."""

    def __init__(self, table):
        self.table = table
        self.state = {
            'sources': [{'id': 'source', 'filename': 'activity.csv', 'media_type': 'text/csv'}],
            'datasets': [{'id': 'activity', 'source_id': 'source', 'kind': 'extraction',
                          'columns': table['columns']}],
            'fund_review': {'result_hash': 'internal-result-hash'},
        }
        self.result = analyze([table], {'checks': [{
            'id': 'required', 'kind': 'required', 'title': 'Investor identifier', 'confirmed': True,
            'left': {'dataset_id': 'activity', 'column': 'c1', 'header_row_id': None},
        }]})
        self.result['source_versions'] = self.state['sources']
        self.finding = next(f for f in self.result['findings'] if f['kind'] == 'required')

    @contextmanager
    def _locked(self, *_):
        yield None, None, self.state

    def _current_fund_result(self, _):
        return self.result

    def _table(self, *_):
        return self.table

    def _revision(self, *_):
        pass


def test_latest_column_correction_is_distinct_from_original_in_findings_pages_and_csv():
    table = source_table()
    edit(table, 'c1', 'first', reason='Earlier correction')
    edit(table, 'c1', '003', actor='reviewer', reason='Latest identifier correction')
    edit(table, 'c2', '\t=2+2', actor='@amount-editor', reason='\ufeff =Amount reason')
    table['rows'][0]['metadata'] = {'internal_only': 'Do not expose parser internals'}
    table['rows'][0]['corrections'][-1]['internal_only'] = 'Do not expose audit internals'
    before = deepcopy(table)
    service = RecordService(table)
    evidence = service.finding['evidence'][0]
    assert evidence['raw_value'] == evidence['effective_value'] == '003'
    assert evidence['original_value_available'] and evidence['original_raw_value'] == '001'
    assert evidence['correction'] == {'actor_id': 'reviewer', 'reason': 'Latest identifier correction'}
    pages = [service.fund_review_records('work', 'reader', service.finding['id'], offset, 1)
             for offset in (0, 1)]
    assert all(page['complete'] and page['total'] == 2 for page in pages)
    first, second = [page['records'][0] for page in pages]
    assert first['values'] == {'c1': '003', 'c2': '\t=2+2'}
    assert first['original_values'] == {'c1': '001', 'c2': '=1+1'}
    assert first['corrections'] == {
        'c1': evidence['correction'],
        'c2': {'actor_id': '@amount-editor', 'reason': '\ufeff =Amount reason'},
    }
    assert second['original_values'] == second['values'] == {'c1': '002', 'c2': None}
    assert second['correction'] is None and second['corrections'] == {}
    assert 'internal' not in json.dumps(pages)
    content, media_type, filename = service.fund_review_records_download('work', 'reader', service.finding['id'])
    assert filename == 'affected-reporting-records.csv' and media_type == 'text/csv; charset=utf-8'
    rows = list(csv.DictReader(StringIO(content.decode('utf-8-sig'))))
    assert len(rows) == 2
    assert rows[0]['Investor ID — Effective value'] == '003'
    assert rows[0]['Investor ID — Original extracted value'] == '001'
    assert rows[0]['Investor ID — Correction actor'] == 'reviewer'
    assert rows[0]['Investor ID — Correction reason'] == 'Latest identifier correction'
    assert rows[0]['Amount — Effective value'] == "'\t=2+2"
    assert rows[0]['Amount — Original extracted value'] == "'=1+1"
    assert rows[0]['Amount — Correction actor'] == "'@amount-editor"
    assert rows[0]['Amount — Correction reason'] == "'\ufeff =Amount reason"
    assert rows[1]['Amount — Original extracted value'] == ''
    assert rows[1]['Amount — Correction actor'] == rows[1]['Amount — Correction reason'] == ''
    assert table == before


@pytest.mark.parametrize('original', [None, '', '0', ' 001.00 '])
def test_original_null_blank_zero_and_precision_survive_repeated_edits(original):
    table = source_table()
    table['rows'][0]['values']['c1'] = original
    edit(table, 'c1', 'intermediate')
    edit(table, 'c1', None, actor='reviewer', reason='Confirm blank')
    evidence = _evidence(table, table['rows'][0], 'c1')
    assert evidence['raw_value'] is evidence['effective_value'] is None
    assert evidence['original_value_available'] and evidence['original_raw_value'] == original
    assert evidence['correction'] == {'actor_id': 'reviewer', 'reason': 'Confirm blank'}


def test_unknown_originals_and_stale_corrections_never_fall_back_to_effective_values():
    table = source_table()
    edit(table, 'c1', '003', reason='Older equal value')
    edit(table, 'c1', '004', reason='Latest correction')
    row = table['rows'][0]
    del row['raw_values']
    row['values']['c1'] = '003'  # A later operation no longer matches the latest correction.
    evidence = _evidence(table, row, 'c1')
    assert evidence['original_raw_value'] is None and not evidence['original_value_available']
    assert evidence['correction'] is None
    row['raw_values'] = {}  # An explicitly unavailable original is not an unedited cell.
    assert not _evidence(table, row, 'c2')['original_value_available']


def test_split_preserves_source_original_but_does_not_misattribute_changed_values():
    table = source_table()
    edit(table, 'c1', '003')
    apply_edits(table, [{'op': 'split_row', 'row_id': 'r1', 'values': [
        {'c1': '004', 'c2': '1'}, {'c1': '003', 'c2': '1'},
    ]}], [], 'Split the source row', 'splitter')
    changed, retained = [_evidence(table, row, 'c1') for row in table['rows'][:2]]
    assert changed['original_raw_value'] == retained['original_raw_value'] == '001'
    assert changed['correction'] is None
    assert retained['correction'] is None
    edit(table, 'c1', '005', row_id=table['rows'][0]['row_id'], reason='Correct the split cell')
    corrected = _evidence(table, table['rows'][0], 'c1')
    assert corrected['correction']['reason'] == 'Correct the split cell'
    assert corrected['original_raw_value'] == '001'


def test_repeated_splits_do_not_revive_a_superseded_correction():
    table = source_table()
    edit(table, 'c1', '002', actor='alice', reason='First correction')
    apply_edits(table, [{'op': 'split_row', 'row_id': 'r1', 'values': [
        {'c1': '003', 'c2': '1'}, {'c1': '004', 'c2': '1'},
    ]}], [], 'First split', 'bob')
    split_id = table['rows'][0]['row_id']
    apply_edits(table, [{'op': 'split_row', 'row_id': split_id, 'values': [
        {'c1': '002', 'c2': '1'}, {'c1': '005', 'c2': '1'},
    ]}], [], 'Second split', 'carol')
    revived = _evidence(table, table['rows'][0], 'c1')
    assert revived['effective_value'] == '002'
    assert revived['correction'] is None


def test_new_correction_on_a_legacy_split_row_keeps_its_provenance():
    table = source_table()
    edit(table, 'c1', '002', actor='alice', reason='Inherited correction')
    apply_edits(table, [{'op': 'split_row', 'row_id': 'r1', 'values': [
        {'c1': '003', 'c2': '1'}, {'c1': '004', 'c2': '1'},
    ]}], [], 'Legacy split', 'bob')
    row = table['rows'][0]
    del row['human_operation']['inherited_correction_count']
    edit(table, 'c1', '005', actor='carol', reason='Post-migration correction', row_id=row['row_id'])
    evidence = _evidence(table, row, 'c1')
    assert evidence['original_raw_value'] == '001'
    assert evidence['correction'] == {'actor_id': 'carol', 'reason': 'Post-migration correction'}


def test_merge_does_not_invent_one_original_or_inherit_first_row_correction():
    table = source_table()
    edit(table, 'c1', '002')
    apply_edits(table, [{'op': 'merge_rows', 'row_ids': ['r1', 'r2']}], [], 'Merge rows', 'merger')
    merged = table['rows'][0]
    evidence = _evidence(table, merged, 'c1')
    assert evidence['effective_value'] == '002'
    assert evidence['original_raw_value'] is None and not evidence['original_value_available']
    assert evidence['correction'] is None
    edit(table, 'c1', '003', row_id=merged['row_id'], reason='Correct merged identifier')
    service = RecordService(table)
    record = service.fund_review_records('work', 'reader', service.finding['id'])['records'][0]
    assert record['original_values'] == {}
    assert record['correction'] == {'actor_id': 'preparer', 'reason': 'Correct merged identifier'}
    assert not {'source_rows', 'source_row_ids', 'metadata', 'human_operation', 'lineage'} & record.keys()
    content, _, _ = service.fund_review_records_download('work', 'reader', service.finding['id'])
    row = next(csv.DictReader(StringIO(content.decode('utf-8-sig'))))
    assert row['Investor ID — Effective value'] == '003'
    assert row['Investor ID — Original extracted value'] == '[unavailable]'
    assert row['Investor ID — Correction reason'] == 'Correct merged identifier'


@pytest.mark.parametrize('label', ['Amount', '\t=Amount'])
def test_csv_provenance_headings_remain_unique_and_safe_for_duplicate_source_labels(label):
    table = source_table()
    for column in table['columns']:
        column['label'] = label
    service = RecordService(table)
    content, _, _ = service.fund_review_records_download('work', 'reader', service.finding['id'])
    rows = list(csv.reader(StringIO(content.decode('utf-8-sig'))))
    assert len(rows[0]) == len(set(rows[0])) == 13
    assert all(len(row) == len(rows[0]) for row in rows)
    safe_label = "'" + label.strip() if label.startswith('\t=') else label
    assert rows[0][5:] == [
        f'{safe_label} — {field}{suffix}' for suffix in ('', ' (2)')
        for field in ('Effective value', 'Original extracted value', 'Correction actor', 'Correction reason')
    ]
    assert rows[1][5:7] == ['001', '001']
    assert rows[1][9:11] == ["'=1+1", "'=1+1"]


def test_legacy_finding_projection_marks_original_unknown_without_rewriting_history():
    legacy = {'evidence': [{'dataset_id': 'activity', 'row_id': 'r1', 'raw_value': 'corrected'}],
              '_record_refs': [{'dataset_id': 'activity', 'row_id': 'r1'}]}
    before = deepcopy(legacy)
    public = FundReviewMixin._public_fund_records(legacy)
    assert '_record_refs' not in public
    assert public['evidence'][0] == {
        'dataset_id': 'activity', 'row_id': 'r1', 'raw_value': 'corrected',
        'effective_value': 'corrected', 'original_raw_value': None,
        'original_value_available': False, 'correction': None,
    }
    assert legacy == before
