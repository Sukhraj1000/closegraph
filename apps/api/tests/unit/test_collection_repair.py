"""Human repairs cannot relabel incomplete parser coverage as a passing extraction."""
from copy import deepcopy

import pytest

from closegraph.collections.editing import apply_edits


def xlsx_table(identity='one', row_number=1, *, formula=True):
    row={'row_id':'Sheet:'+str(row_number),'values':{'c1':None if formula else '#REF!'},
         'locators':{'c1':{'kind':'xlsx','sheet':'Sheet','cell':'A'+str(row_number)}},
         'metadata':{'cells':{'c1':{'type':'n','formula':{'expression':'B1+1','cached_value':None}} if formula else {'type':'e'}}}}
    return {'table_id':identity,'source_id':'source','columns':[{'key':'c1','label':'Value'}],
            'rows':[row],'metadata':{'sheet':'Sheet'}}


def finding(code, identity='issue', **fields):
    return {'id':identity,'source_id':'source','severity':'error','code':code,'message':code,**fields}


def correct(table,value='42',**kwargs):
    return apply_edits(table,[{'op':'set_cell','row_id':table['rows'][0]['row_id'],
                              'column_key':'c1','value':value}],kwargs.pop('issues'),
                       'Checked original source','preparer',**kwargs)


def test_formula_repairs_require_every_original_cell_across_source_tables():
    first,second=xlsx_table(),xlsx_table('two',4)
    issues=[finding('formula_cache_missing',details={'sheet':'Sheet','count':2})]
    correct(first,issues=issues,related_tables=[first,second])
    assert not issues[0].get('resolved')
    # Incomplete related table list cannot satisfy the original provider count.
    correct(second,issues=issues)
    assert not issues[0].get('resolved')
    correct(second,issues=issues,related_tables=[first,second])
    assert issues[0]['resolved'] is True
    assert len(issues[0]['resolution']['evidence'])==2
    assert first['rows'][0]['metadata']['cells']['c1']['formula']['cached_value'] is None


def test_error_cell_needs_an_actual_correction_to_the_bound_source_cell():
    table=xlsx_table(formula=False)
    issues=[finding('spreadsheet_error',details={'sheet':'Sheet','cell':'A1'})]
    apply_edits(table,[{'op':'rename_column','column_key':'c1','label':'Renamed'}],issues,'Header correction','preparer')
    assert not issues[0].get('resolved')
    correct(table,value='#DIV/0!',issues=issues)
    assert not issues[0].get('resolved')
    correct(table,issues=issues)
    assert issues[0]['resolved'] is True
    assert table['rows'][0]['raw_values']['c1']=='#REF!'


def test_limits_and_unknown_provider_errors_never_become_resolved_by_edits():
    table=xlsx_table(formula=False)
    issues=[finding('row_limit','limit'),finding('provider_diagnostic','provider',details={'diagnostic':'malformed_provider_response'})]
    correct(table,issues=issues)
    assert all(not item.get('resolved') for item in issues)
    with pytest.raises(ValueError):
        apply_edits(table,[{'op':'resolve_issue','issue_id':'limit'}],issues,'Dismiss','preparer')


def pdf_table():
    return {'table_id':'pdf-table','source_id':'source','columns':[{'key':'c1','label':'Name'},{'key':'c2','label':'Amount'}],
            'rows':[{'row_id':'pdf:b0:r1','values':{'c1':'Account','c2':'12.50'},'locators':{}}],
            'metadata':{'provider_block_index':0,'raw_content':'Account | 12.50'}}


def citation(**overrides):
    return {'op':'set_pdf_citation','row_id':'pdf:b0:r1','column_key':'c1','original_page':3,
            'bbox':[.1,.2,.8,.4],**overrides}


def test_block_citation_repair_preserves_actual_human_precision_and_clears_only_matching_diagnostic():
    table=pdf_table()
    issues=[finding('pdf_citation_missing','missing',table_id='pdf-table'),
            finding('provider_diagnostic','legacy',details={'diagnostic':'block_0_malformed_citation_or_content'}),
            finding('provider_diagnostic','other',details={'diagnostic':'block_1_malformed_citation_or_content'})]
    apply_edits(table,[citation(apply_to='block',source_id='attacker-selected-source')],issues,
                'Selected the source table region','preparer')
    assert issues[0]['resolved'] is True and issues[1]['resolved'] is True
    assert not issues[2].get('resolved')
    locator=table['rows'][0]['locators']['c2']
    assert locator['source_id']=='source'
    assert locator['citation_precision']=='human_block'
    assert locator['original_page']==3
    assert locator['processed_page'] is None
    assert table['rows'][0]['original_locators']=={}
    assert table['metadata']['raw_content']=='Account | 12.50'


def test_single_cell_citation_does_not_clear_unrepaired_table_content():
    table=pdf_table();issues=[finding('pdf_citation_missing',table_id='pdf-table')]
    apply_edits(table,[citation()],issues,'Selected a cell','preparer')
    assert not issues[0].get('resolved')
    apply_edits(table,[citation(column_key='c2')],issues,'Selected second cell','preparer')
    assert issues[0]['resolved'] is True
    assert table['rows'][0]['locators']['c1']['citation_precision']=='human_cell'


@pytest.mark.parametrize('patch',[{'original_page':0},{'original_page':True},{'bbox':[0,0,2,1]},
                                  {'bbox':[0,0,0,1]},{'bbox':[False,0,1,1]},
                                  {'coordinate_system':'imaginary-space'}])
def test_invalid_human_citation_is_rejected(patch):
    with pytest.raises(ValueError):
        apply_edits(pdf_table(),[citation(**patch)],[],'Invalid box','preparer')


def test_merge_locators_follow_actual_contributing_values_not_first_row():
    first=xlsx_table(formula=False);one=first['rows'][0];one['values']['c1']=None
    two=deepcopy(one);two['row_id']='Sheet:2';two['values']['c1']='123'
    two['locators']['c1']['cell']='A2';first['rows'].append(two)
    apply_edits(first,[{'op':'merge_rows','row_ids':['Sheet:1','Sheet:2']}],[],'Join split source row','preparer')
    merged=first['rows'][0]
    assert merged['values']['c1']=='123'
    assert merged['locators']['c1']['cell']=='A2'
    assert [location['cell'] for location in merged['source_locations']['c1']]==['A1','A2']
    assert len(merged['source_rows'])==2


def test_merge_conflict_has_no_fabricated_single_source_locator():
    first=xlsx_table(formula=False);second=deepcopy(first['rows'][0]);second['row_id']='Sheet:2'
    second['values']['c1']='123';second['locators']['c1']['cell']='A2';first['rows'].append(second);issues=[]
    apply_edits(first,[{'op':'merge_rows','row_ids':['Sheet:1','Sheet:2']}],issues,'Merge','preparer')
    assert first['rows'][0]['values']['c1'] is None
    assert 'c1' not in first['rows'][0]['locators']
    assert issues[0]['code']=='merge_conflict'


def test_previously_repaired_errors_reopen_when_the_repair_is_undone():
    table=xlsx_table(formula=False)
    issues=[finding('spreadsheet_error',details={'sheet':'Sheet','cell':'A1'})]
    correct(table,issues=issues)
    assert issues[0]['resolved'] is True
    correct(table,value='#REF!',issues=issues)
    assert issues[0]['resolved'] is False
    assert 'resolution' not in issues[0]
    assert len(issues[0]['resolution_history'])==1
    correct(table,value='99',issues=issues)
    assert issues[0]['resolved'] is True


def test_formula_repair_reopens_when_one_cell_becomes_unresolved_again():
    table=xlsx_table()
    issues=[finding('formula_cache_missing',details={'sheet':'Sheet','count':1})]
    correct(table,issues=issues)
    assert issues[0]['resolved'] is True
    correct(table,value=None,issues=issues)
    assert issues[0]['resolved'] is False


def test_split_and_repeated_merge_keep_original_source_lineage_ids():
    table=xlsx_table(formula=False);table['rows'][0]['values']['c1']='12'
    apply_edits(table,[{'op':'split_row','row_id':'Sheet:1','values':[{'c1':'5'},{'c1':'7'}]}],[],
                'Split source amount','preparer')
    ids=[row['row_id'] for row in table['rows']]
    for row in table['rows']:
        assert row['lineage']['c1'][0]['row_id']=='Sheet:1'
        assert row['lineage']['c1'][0]['locator']['cell']=='A1'
    apply_edits(table,[{'op':'merge_rows','row_ids':ids}],[],'Recombine rows','preparer')
    assert len(table['rows'][0]['lineage']['c1'])==1
    assert table['rows'][0]['lineage']['c1'][0]['row_id']=='Sheet:1'


def test_pdf_citation_after_split_updates_lineage_and_retains_original_locator():
    table=pdf_table()
    apply_edits(table,[{'op':'split_row','row_id':'pdf:b0:r1',
                       'values':[{'c1':'A','c2':'10'},{'c1':'B','c2':'2.50'}]}],[],'Split','preparer')
    identity=table['rows'][0]['row_id']
    apply_edits(table,[citation(row_id=identity,apply_to='block')],[],'Selected original table','preparer')
    reference=table['rows'][0]['lineage']['c1'][0]
    assert reference['row_id']=='pdf:b0:r1'
    assert reference['original_locator'] is None
    assert reference['locator']['original_page']==3
