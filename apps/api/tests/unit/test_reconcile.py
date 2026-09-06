from copy import deepcopy
import pytest
from closegraph.collections.reconcile import propose, reconcile


def table(side, rows, **extra):
    columns = ['reference', 'account', 'currency', 'date', 'amount']
    return {'dataset_id': side, 'source_id': side, 'side': side, 'columns': [{'key': k, 'label': k} for k in columns],
            'rows': [{'row_id': str(i), 'values': dict(zip(columns, row))} for i, row in enumerate(rows)],
            'coverage': {'complete': True}, **extra}


def sample():
    row = ['abc', 'account-1', 'GBP', '2026-09-01', '100.01']
    return [table('statement', [row]), table('journal', [row])]


def config():
    return {'mappings': [{'dataset_id': side, 'columns': {k: k for k in ('reference','account','currency','date','amount')}, 'cash_leg_confirmed': True} for side in ('statement','journal')]}


def test_exact_decimal_matches_and_no_mutation():
    tables, settings = sample(), config()
    before = deepcopy(tables)
    result = reconcile(tables, settings)
    assert result['summary']['matched'] == 1
    assert result['items'][0]['difference'] == '0.00'
    assert tables == before


def test_changed_amount_is_difference_with_stable_binding():
    tables = sample()
    before = reconcile(tables, config())['items'][0]
    tables[1]['rows'][0]['values']['amount'] = '100.02'
    tables[1]['source_id'] = 'new-revision'
    after = reconcile(tables, config())['items'][0]
    assert after['status'] == 'difference' and after['difference'] == '-0.01'
    assert before['match_key'] == after['match_key']


def test_duplicate_reference_cannot_be_selected():
    tables = sample()
    tables[0]['rows'].append({**tables[0]['rows'][0], 'row_id':'another'})
    result = reconcile(tables, config())
    assert result['summary']['matched'] == 0
    assert result['items'][0]['status'] == 'needs_input'
    assert len(result['items'][0]['statement']) == 2


def test_missing_only_if_other_sources_complete():
    tables = sample()
    tables[1]['rows'][0]['values']['reference'] = 'other'
    assert reconcile(tables, config())['summary']['missing'] == 2
    tables.append(table('statement', [['content']], dataset_id='other', source_id='other', columns=[{'key':'text','label':'text'}]))
    result = reconcile(tables, config())
    assert result['summary']['missing'] == 0
    assert result['coverage'][-1]['unclassified_rows'] == 1


def test_cash_leg_confirmation_is_mandatory():
    settings = config(); settings['mappings'][1].pop('cash_leg_confirmed')
    assert reconcile(sample(), settings)['summary']['matched'] == 0


def test_pdf_requires_evidence_confirmation():
    tables = sample(); tables[0]['media_type'] = 'application/pdf'
    assert reconcile(tables, config())['summary']['matched'] == 0
    tables[0]['extraction_confirmed'] = True
    assert reconcile(tables, config())['summary']['matched'] == 1


def test_composite_opt_in_and_duplicate_ambiguity():
    tables = sample()
    for t in tables:t['rows'][0]['values']['reference'] = ''
    settings = config()
    assert reconcile(tables, settings)['summary']['matched'] == 0
    settings['composite_confirmed'] = True
    assert reconcile(tables, settings)['summary']['matched'] == 1
    tables[1]['rows'].append({**tables[1]['rows'][0], 'row_id':'dup'})
    assert reconcile(tables, settings)['summary']['matched'] == 0


def test_ambiguous_dates_and_numbers_require_explicit_format():
    tables = sample()
    for t in tables:
        t['rows'][0]['values'].update(date='01/02/2026', amount='1,000.20')
    settings = config()
    assert reconcile(tables, settings)['summary']['matched'] == 0
    for m in settings['mappings']:m.update(date_format='day_first', number_format='dot_decimal')
    assert reconcile(tables, settings)['summary']['matched'] == 1


def test_mapped_formula_cache_blocks_but_unrelated_formula_does_not():
    tables = sample()
    tables[0]['rows'][0]['metadata'] = {'cells':{'amount':{'formula':{'cache_verified':False}}}}
    assert reconcile(tables, config())['summary']['matched'] == 0
    tables[0]['rows'][0]['metadata']['cells'] = {'unrelated':{'formula':{'cache_verified':False}}}
    assert reconcile(tables, config())['summary']['matched'] == 1


def test_raw_header_found_without_filename_rules():
    t = table('statement', [['Reference','Account','Currency','Date','Amount'], ['abc','acct','GBP','2026-09-01','1']])
    t['columns'] = [{'key':k,'label':str(i)} for i,k in enumerate(['reference','account','currency','date','amount'])]
    suggestion = propose([t])['suggestions'][0]
    assert suggestion['header_row_id'] == '0'
    assert suggestion['columns']['amount'] == 'amount'
    assert reconcile([t])['coverage'][0]['header_rows'] == 1


def test_all_rows_accounted_and_exclusion_requires_reason():
    tables = sample(); settings=config()
    settings['mappings'][0].update(exclude=True)
    with pytest.raises(ValueError, match='reason'): reconcile(tables,settings)
    settings['mappings'][0]['reason'] = 'Supporting document'
    result = reconcile(tables,settings)
    assert result['coverage'][0]['excluded_rows'] == 1


def test_cash_filter_and_direction_do_not_net_whole_journal():
    tables=sample(); journal=tables[1]
    journal['columns'] += [{'key':'type','label':'Entry type'}, {'key':'direction','label':'Debit flag'}]
    journal['rows'][0]['values'].update(type='Cash',direction='Yes')
    journal['rows'].append({'row_id':'counter','values':{**journal['rows'][0]['values'],'type':'Expense','direction':'No'}})
    settings=config(); settings['mappings'][1].update(cash_leg={'column':'type','values':['Cash']},direction={'column':'direction','signs':{'Yes':1,'No':-1}})
    result=reconcile(tables,settings)
    assert result['summary']['matched']==1 and result['coverage'][1]['excluded_rows']==1


def test_tolerance_cannot_be_negative():
    with pytest.raises(ValueError, match='negative'):reconcile(sample(),{**config(),'tolerance':'-1'})


def test_context_is_source_scoped_and_pdf_pages_share_group():
    tables=sample(); t=tables[0];t['media_type']='application/pdf'
    for row in t['rows']:row['values'].pop('account');row['values'].pop('currency')
    t['columns']=[c for c in t['columns'] if c['key'] not in ('account','currency')]
    metadata={'dataset_id':'metadata','source_id':'statement','side':'statement','media_type':'application/pdf','columns':[{'key':'a','label':'a'},{'key':'b','label':'b'}],'rows':[{'row_id':'a','values':{'a':'Account number','b':'account-1'}},{'row_id':'b','values':{'a':'Currency','b':'GBP'}}]}
    other=deepcopy(t);other['dataset_id']='page2'
    result=propose([t,metadata,other])['suggestions']
    assert result[0]['context']=={'account':'account-1','currency':'GBP'}
    assert result[0]['dataset_ids']==['statement','page2']
    assert result[1]['kind']=='supporting'


def test_signed_debits_and_narrative_rows_are_preserved():
    tables=sample();t=tables[0];t['columns'].append({'key':'debit','label':'Debit amount'})
    t['rows'][0]['values']['debit']='-100.01'
    t['rows'].append({'row_id':'note','values':{'reference':'Narrative','account':'Description'}})
    settings=config();settings['mappings'][0]['columns'].pop('amount');settings['mappings'][0]['columns']['debit']='debit'
    tables[1]['rows'][0]['values']['amount']='-100.01'
    result=reconcile(tables,settings)
    assert result['summary']['matched']==1
    assert result['coverage'][0]['supporting_rows']==1
    assert len(result['items'][0]['supporting_evidence'])==1


def test_lookup_unique_only_and_evidence_retained():
    tables=sample();tables[1]['rows'][0]['values']['account']='friendly account'
    lookup=table('journal',[],dataset_id='lookup',source_id='lookup')
    lookup['rows']=[{'row_id':'lookuprow','values':{'account':'friendly account','reference':'account-1'}}]
    tables.append(lookup)
    settings=config();settings['mappings'][1]['lookups']=[{'table_id':'lookup','source_column':'account','key_column':'account','value_column':'reference','target':'account'}]
    settings['mappings'].append({'dataset_id':'lookup','exclude':True,'reason':'Reference table'})
    result=reconcile(tables,settings)
    assert result['summary']['matched']==1
    assert len(result['items'][0]['mapping_evidence'])==1
    lookup['rows'].append({'row_id':'duplookup','values':lookup['rows'][0]['values']})
    assert reconcile(tables,settings)['summary']['matched']==0


def test_composite_tolerance_and_ambiguity_are_order_independent():
    tables=sample();settings={**config(),'match_mode':'composite','composite_confirmed':True,'tolerance':'0.01'}
    tables[1]['rows'][0]['values']['amount']='100.01000000001'
    assert reconcile(tables,settings)['summary']['matched']==1
    tables[1]['rows'].append({'row_id':'another','values':{**tables[1]['rows'][0]['values'],'amount':'100.015'}})
    assert reconcile(tables,settings)['summary']['matched']==0
