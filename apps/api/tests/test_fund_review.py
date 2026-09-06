from copy import deepcopy

from closegraph.collections.fund_review import analyze


def table(identity, columns, rows, **extra):
    return {'dataset_id': identity, 'source_id': identity, 'document_id': 'document-' + identity,
            'title': identity, 'columns': [{'key': key, 'label': key} for key in columns],
            'rows': [{'row_id': str(i), 'values': dict(zip(columns, values))} for i, values in enumerate(rows)],
            'coverage': {'complete': True}, **extra}


def reference():
    tables = [table('Activity', ['Investor ID', 'Amount'], [['I-1', '2.10'], ['I-2', '3.20']]),
              table('Investor List', ['Investor ID', 'Investor Name'], [['I-1', 'First'], ['I-2', 'Second']])]
    check = {'id': 'investors', 'kind': 'reference', 'title': 'Investor reference membership', 'confirmed': True,
             'left': {'dataset_id': 'Activity', 'column': 'Investor ID', 'header_row_id': None},
             'right': {'dataset_id': 'Investor List', 'column': 'Investor ID', 'header_row_id': None}}
    return tables, {'checks': [check]}


def selected(result, kind='reference'):
    return [finding for finding in result['findings'] if finding['kind'] == kind]


def test_discovery_never_financially_verifies_or_mutates():
    tables, _ = reference()
    before = deepcopy(tables)
    result = analyze(tables)
    assert result['suggestions'][0]['confirmed'] is False
    assert result['suggestions'][0]['overlap']['matched_distinct'] == 2
    assert result['summary']['financially_verified'] is False
    assert result['summary']['scoped_checks_passed'] is False
    assert tables == before


def test_confirmed_reference_membership_has_evidence_and_scoped_pass():
    tables, config = reference()
    result = analyze(tables, config)
    assert selected(result)[0]['status'] == 'passed'
    assert selected(result)[0]['evidence'][0]['raw_value'] == 'I-1'
    assert result['summary']['scoped_checks_passed'] is True
    assert result['summary']['financially_verified'] is False


def test_reference_difference_reproduces_counts_and_preserves_raw():
    tables, config = reference()
    tables[0]['rows'].append({'row_id': 'third', 'values': {'Investor ID': ' I-3 ', 'Amount': '1.00'}})
    tables[0]['rows'].append({'row_id': 'fourth', 'values': {'Investor ID': 'I-3', 'Amount': '2.00'}})
    finding = selected(analyze(tables, config))[0]
    assert finding['status'] == 'difference'
    assert finding['observed'] == ['I-3']
    assert finding['affected_count'] == 2
    assert finding['evidence'][0]['raw_value'] == ' I-3 '
    assert finding['operands']['reference_rows'] == 2


def test_duplicate_reference_cannot_silently_pick_one():
    tables, config = reference()
    tables[1]['rows'].append({'row_id': 'dup', 'values': {'Investor ID': 'I-1', 'Investor Name': 'Another'}})
    finding = selected(analyze(tables, config))[0]
    assert finding['status'] == 'needs_input'
    assert 'more than once' in finding['explanation']


def test_explicit_scope_disambiguates_cross_fund_identifier():
    tables, config = reference()
    for source in tables:
        source['columns'].append({'key': 'Entity', 'label': 'Entity'})
        for row in source['rows']:
            row['values']['Entity'] = 'Fund A'
    tables[1]['rows'].append({'row_id': 'other', 'values': {'Investor ID': 'I-1', 'Investor Name': 'Other investor', 'Entity': 'Fund B'}})
    assert selected(analyze(tables, config))[0]['status'] == 'needs_input'
    for side in ['left', 'right']:
        config['checks'][0][side]['group_by'] = ['Entity']
    assert selected(analyze(tables, config))[0]['status'] == 'passed'


def test_incomplete_coverage_and_unknown_checks_never_pass():
    tables, config = reference()
    tables[1]['coverage']['complete'] = False
    assert selected(analyze(tables, config))[0]['status'] == 'needs_input'
    tables[1]['coverage']['complete'] = True
    config['checks'][0]['kind'] = 'magic_accounting'
    result = analyze(tables, config)
    assert result['summary']['scoped_checks_passed'] is False
    assert result['summary']['needs_input'] > 0


def test_pdf_confirmation_cannot_override_incomplete_coverage():
    tables, config = reference()
    tables[0]['media_type'] = 'application/pdf'
    assert selected(analyze(tables, config))[0]['status'] == 'needs_input'
    config['confirmed_source_ids'] = ['Activity']
    assert selected(analyze(tables, config))[0]['status'] == 'passed'
    tables[0]['coverage']['complete'] = False
    assert selected(analyze(tables, config))[0]['status'] == 'needs_input'


def test_stale_formula_cache_and_excel_error_block_selected_values():
    tables, config = reference()
    tables[0]['rows'][0]['metadata'] = {'cells': {'Investor ID': {'formula': {'expression': 'LOOKUP(A1)', 'cached_value': 'I-1', 'cache_verified': False}}}}
    assert selected(analyze(tables, config))[0]['status'] == 'needs_input'
    tables[0]['rows'][0]['metadata']['cells']['Investor ID'] = {'type': 'e'}
    assert selected(analyze(tables, config))[0]['status'] == 'needs_input'


def test_selected_check_requires_confirmation():
    tables, config = reference()
    config['checks'][0]['confirmed'] = False
    assert selected(analyze(tables, config))[0]['status'] == 'needs_input'


def test_reordered_rows_and_source_revision_keep_business_finding_identity():
    tables, config = reference()
    tables[0]['rows'][0]['values']['Investor ID'] = 'missing'
    before = selected(analyze(tables, config))[0]
    tables[0]['rows'].reverse()
    tables[0]['source_id'] = 'uploaded-version-two'
    tables[0]['rows'][1]['row_id'] = 'changed-position'
    after = selected(analyze(tables, config))[0]
    assert before['match_key'] == after['match_key']
    assert before['id'] == after['id']
    assert after['evidence'][0]['row_id'] == 'changed-position'


def test_native_headers_are_proposed_not_silently_confirmed():
    tables, config = reference()
    tables[0] = table('Activity', ['c1', 'c2'], [['Investor ID', 'Amount'], ['I-1', '2.10'], ['I-2', '3.20']])
    result = analyze(tables)
    profile = result['tables'][0]
    assert profile['header_row_id'] == '0'
    assert profile['columns'][0]['label'] == 'Investor ID'
    config['checks'][0]['left'] = {'dataset_id': 'Activity', 'column': 'c1'}
    assert selected(analyze(tables, config))[0]['status'] == 'needs_input'
    config['checks'][0]['left']['header_row_id'] = '0'
    assert selected(analyze(tables, config))[0]['status'] == 'passed'


def test_repeated_headers_and_unavailable_header_require_input():
    tables, config = reference()
    tables[0] = table('Activity', ['c1', 'c2'], [['Investor ID', 'Amount'], ['I-1', '2.10'], ['Investor ID', 'Amount'], ['I-2', '3.20']])
    assert analyze(tables)['tables'][0]['header_status'] == 'needs_input'
    config['checks'][0]['left'] = {'dataset_id': 'Activity', 'column': 'c1', 'header_row_id': '0'}
    assert 'repeated header' in selected(analyze(tables, config))[0]['explanation']
    config['checks'][0]['left']['header_row_id'] = 'unavailable'
    assert selected(analyze(tables, config))[0]['status'] == 'needs_input'


def totals():
    columns = ['Entity', 'Currency', 'Investor ID', 'Amount']
    rows = [['Fund', 'GBP', 'I-1', '10.01'], ['Fund', 'GBP', 'I-2', '20.02']]
    tables = [table('Source', columns, rows), table('Report', columns, rows)]
    check = {'id': 'tieout', 'kind': 'totals', 'confirmed': True,
             'left': {'dataset_id': 'Source', 'column': 'Amount', 'group_by': ['Entity', 'Currency', 'Investor ID'], 'header_row_id': None},
             'right': {'dataset_id': 'Report', 'column': 'Amount', 'group_by': ['Entity', 'Currency', 'Investor ID'], 'header_row_id': None}}
    return tables, {'checks': [check]}


def test_decimal_group_totals_persist_exact_operands_and_catch_offsetting_errors():
    tables, config = totals()
    result = analyze(tables, config)
    assert len(selected(result, 'totals')) == 2
    assert {f['expected'] for f in selected(result, 'totals')} == {'10.01', '20.02'}
    assert all(f['difference'] == '0.00' for f in selected(result, 'totals'))
    tables[1]['rows'][0]['values']['Amount'] = '11.01'
    tables[1]['rows'][1]['values']['Amount'] = '19.02'
    findings = selected(analyze(tables, config), 'totals')
    assert len(findings) == 2
    assert all(f['status'] == 'difference' for f in findings)
    assert {f['difference'] for f in findings} == {'-1.00', '1.00'}


def test_totals_require_scope_and_number_interpretation_and_default_zero_tolerance():
    tables, config = totals()
    tables[1]['rows'][0]['values']['Amount'] = '10.010000000000001'
    assert selected(analyze(tables, config), 'totals')[0]['status'] == 'difference'
    config['checks'][0]['tolerance'] = '0.0000001'
    assert all(f['status'] == 'passed' for f in selected(analyze(tables, config), 'totals'))
    tables[1]['rows'][0]['values']['Amount'] = '10,01'
    assert selected(analyze(tables, config), 'totals')[0]['status'] == 'needs_input'
    config['checks'][0]['right']['number_format'] = 'comma_decimal'
    tables[1]['rows'][1]['values']['Amount'] = '20,02'
    assert all(f['status'] == 'passed' for f in selected(analyze(tables, config), 'totals'))
    config['checks'][0]['left']['group_by'] = []
    config['checks'][0]['right']['group_by'] = []
    assert selected(analyze(tables, config), 'totals')[0]['status'] == 'needs_input'


def test_missing_groups_blank_reference_and_empty_inputs_do_not_pass():
    tables, config = totals()
    tables[0]['rows'].pop()
    result = selected(analyze(tables, config), 'totals')
    assert any(f['status'] == 'difference' and f['observed'] is None for f in result)
    tables, config = reference()
    tables[1]['rows'][0]['values']['Investor ID'] = ''
    assert selected(analyze(tables, config))[0]['status'] == 'needs_input'
    tables[1]['rows'] = []
    assert selected(analyze(tables, config))[0]['status'] == 'needs_input'


def test_required_fields_and_compound_uniqueness_are_explicit():
    tables, _ = reference()
    tables[0]['rows'].append({'row_id': 'third', 'values': {'Investor ID': 'I-1', 'Amount': ''}})
    config = {'checks': [{'id': 'required', 'kind': 'required', 'confirmed': True,
                         'left': {'dataset_id': 'Activity', 'columns': ['Amount'], 'header_row_id': None}},
                        {'id': 'unique', 'kind': 'unique', 'confirmed': True,
                         'left': {'dataset_id': 'Activity', 'columns': ['Investor ID'], 'header_row_id': None}}]}
    result = analyze(tables, config)
    assert selected(result, 'required')[0]['affected_count'] == 1
    assert selected(result, 'unique')[0]['affected_count'] == 2


def test_evidence_is_bounded_without_losing_affected_count():
    tables, config = reference()
    tables[0]['rows'] = [{'row_id': str(i), 'values': {'Investor ID': 'missing', 'Amount': '1'}} for i in range(1000)]
    finding = selected(analyze(tables, config))[0]
    assert finding['affected_count'] == finding['evidence_total'] == 1000
    assert len(finding['evidence']) == 12
    assert finding['records_complete'] and finding['records_total'] == 1000
    assert len(finding['_record_refs']) == 1000
    assert len({ref['row_id'] for ref in finding['_record_refs']}) == 1000


def test_all_duplicate_reference_groups_have_full_record_indexes():
    tables, config = reference()
    tables[1]['rows'] = [{'row_id': str(i), 'values': {'Investor ID': 'I-' + str(i % 2), 'Investor Name': 'Repeated'}} for i in range(60)]
    item = selected(analyze(tables, config))[0]
    assert item['status'] == 'needs_input'
    assert item['affected_count'] == item['records_total'] == item['evidence_total'] == 60
    assert len(item['_record_refs']) == 60


def test_group_total_record_indexes_include_every_contributing_row_on_both_sides():
    tables, config = totals()
    for source in tables:
        source['rows'] = [{'row_id': str(i), 'values': {'Entity': 'Fund', 'Currency': 'GBP', 'Investor ID': 'I-1', 'Amount': '1'}} for i in range(31)]
    tables[1]['rows'][0]['values']['Amount'] = '2'
    item = selected(analyze(tables, config), 'totals')[0]
    assert item['affected_count'] == item['records_total'] == 62
    assert len(item['evidence']) == 12 and len(item['_record_refs']) == 62
    assert {r['dataset_id'] for r in item['_record_refs']} == {'Source', 'Report'}


def test_unselected_formula_columns_remain_explicitly_unverified_without_blocking_scoped_checks():
    tables, config = reference()
    tables[0]['rows'][0]['metadata'] = {'cells': {'Amount': {'formula': {'expression': '1+1', 'cached_value': '2', 'cache_verified': False}}}}
    before = deepcopy(tables)
    result = analyze(tables, config)
    warning = selected(result, 'formula_scope')[0]
    assert warning['status'] == 'needs_input' and warning['blocking'] is False
    assert 'have not been verified' in warning['explanation']
    assert result['summary']['blocking_needs_input'] == 0
    assert result['summary']['nonblocking_needs_input'] == 1
    assert result['summary']['scoped_checks_passed'] is True
    assert result['summary']['financially_verified'] is False
    assert tables == before
    config['checks'][0] = {'id': 'required-amount', 'kind': 'required', 'confirmed': True,
                           'left': {'dataset_id': 'Activity', 'columns': ['Amount'], 'header_row_id': None}}
    result = analyze(tables, config)
    assert selected(result, 'formula_scope')[0]['blocking'] is True
    assert selected(result, 'required')[0]['status'] == 'needs_input'


def test_unknown_scope_and_incomplete_coverage_cannot_hide_behind_nonblocking_formula_notes():
    tables, config = reference()
    tables[0]['rows'][0]['metadata'] = {'cells': {'Amount': {'formula': {'expression': '1+1', 'cached_value': '2', 'cache_verified': False}}}}
    for candidate in ({}, {'checks': [{**config['checks'][0], 'kind': 'unknown'}]}, {'checks': [{**config['checks'][0], 'confirmed': False}]}):
        result = analyze(tables, candidate)
        assert selected(result, 'formula_scope')[0]['blocking'] is True
        assert result['summary']['blocking_needs_input'] > 0
    tables[0]['coverage']['complete'] = False
    assert analyze(tables, config)['summary']['blocking_needs_input'] > 0



def test_structural_condition_outcomes_never_claim_financial_pass():
    tables, config = reference()
    tables[0]['coverage']['complete'] = False
    before = analyze(tables, config)
    issue = next(f for f in before['findings'] if f['kind'] == 'coverage')
    assert before['condition_outcomes'][issue['match_key']]['passed'] is False
    tables[0]['coverage']['complete'] = True
    after = analyze(tables, config)
    assert after['condition_outcomes'][issue['match_key']]['passed'] is True
    assert after['summary']['financially_verified'] is False
    # A missing table cannot supply a successful structural condition.
    removed = analyze(tables[1:], config)
    assert issue['match_key'] not in removed['condition_outcomes']


def test_unknown_or_unconfirmed_checks_do_not_clear_scope_selection_condition():
    tables, config = reference()
    empty = analyze(tables)
    finding = next(f for f in empty['findings'] if f['kind'] == 'configuration')
    key = finding['match_key']
    assert empty['condition_outcomes'][key]['passed'] is False
    assert analyze(tables, config)['condition_outcomes'][key]['passed'] is True
    config['checks'][0]['kind'] = 'unknown_financial_rule'
    assert analyze(tables, config)['condition_outcomes'][key]['passed'] is False
    config['checks'][0]['kind'] = 'reference'
    config['checks'][0]['confirmed'] = False
    assert analyze(tables, config)['condition_outcomes'][key]['passed'] is False


def test_vendor_prefixed_labels_are_only_unconfirmed_proposals():
    tables = [table('Activity', ['Provider Investor Name', 'Amount'], [['A', '1'], ['B', '2']]),
              table('Investor List', ['Investor Name', 'Investor ID'], [['A', '1'], ['B', '2']])]
    result = analyze(tables)
    assert result['tables'][0]['columns'][0]['concept'] == 'investor_name'
    assert result['suggestions'] and result['suggestions'][0]['confirmed'] is False
    assert result['summary']['passed'] == 0


def test_duplicate_header_labels_keep_distinct_columns_and_single_column_list_is_profiled():
    source = table('Activity', ['c1', 'c2', 'c3'], [['Investor ID', 'Date', 'Date'], ['A', '2026-01-01', '2026-02-01']])
    profile = analyze([source])['tables'][0]
    assert profile['header_row_id'] == '0'
    assert [c['key'] for c in profile['columns']] == ['c1', 'c2', 'c3']
    single = table('Investor List', ['c1'], [['Investor ID'], ['A'], ['B']])
    assert analyze([single])['tables'][0]['header_row_id'] == '0'


def test_scientific_excel_residuals_remain_exact_and_bounded():
    from decimal import Decimal
    import pytest
    from closegraph.collections.fund_review import _amount
    assert _amount('1.164153218269348e-10') == Decimal('0.0000000001164153218269348')
    assert _amount('-2.5E+3') == Decimal('-2500')
    assert _amount('1,5e-9', 'comma_decimal') == Decimal('0.0000000015')
    for bad in ('NaN', 'Inf', '1e999', '1e-999', '1e99999999'):
        with pytest.raises(ValueError):
            _amount(bad)


def test_two_columns_with_the_same_concept_have_distinct_suggestions():
    inputs = [table('Activity', ['Source Investor ID', 'Target Investor ID'], [['I-1', 'I-2'], ['I-2', 'I-1']]),
              table('Investor List', ['Investor ID', 'Investor Name'], [['I-1', 'One'], ['I-2', 'Two']])]
    suggestions = analyze(inputs)['suggestions']
    assert len(suggestions) == 2
    assert len({s['id'] for s in suggestions}) == 2
