"""Synthetic revision, exact native-diff and dependency-coverage regressions."""
from copy import deepcopy
import io
import zipfile

import pytest

from closegraph.collections.documents import (CSV, XLSX, ComparisonLimits, add_source_revision,
    compare_sources, current_sources, document_fingerprint, initialize_documents, output_dependency_ids)
from closegraph.collections.extract import ExtractionLimits

MAIN='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL='http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def source(identity='s1',filename='Ledger.xlsx'):
    return {'id':identity,'filename':filename,'media_type':XLSX,'content_hash':'a'*64,'status':'EXTRACTED'}


def workbook(sheets, *, styles=None, shared=None, extra=None, properties=''):
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        names=[];links=[]
        for i,(name,rows) in enumerate(sheets,1):
            names.append(f'<sheet name="{name}" sheetId="{i}" r:id="r{i}"/>')
            links.append(f'<Relationship Id="r{i}" Target="worksheets/s{i}.xml"/>')
            archive.writestr(f'xl/worksheets/s{i}.xml',f'<worksheet xmlns="{MAIN}">{rows}</worksheet>')
        archive.writestr('xl/workbook.xml',f'<workbook xmlns="{MAIN}" xmlns:r="{REL}"><sheets>'+''.join(names)+'</sheets>'+properties+'</workbook>')
        archive.writestr('xl/_rels/workbook.xml.rels','<Relationships>'+''.join(links)+'</Relationships>')
        if styles:archive.writestr('xl/styles.xml',f'<styleSheet xmlns="{MAIN}">{styles}</styleSheet>')
        if shared:archive.writestr('xl/sharedStrings.xml',f'<sst xmlns="{MAIN}">'+''.join('<si><t>'+s+'</t></si>' for s in shared)+'</sst>')
        for name,content in (extra or {}).items():archive.writestr(name,content)
    return output.getvalue()


def sheet(rows):
    return '<sheetData>'+''.join('<row r="'+str(number)+'">'+cells+'</row>' for number,cells in rows)+'</sheetData>'


def number(cell,value,style=None):
    return '<c r="'+cell+'"'+(' s="'+str(style)+'"' if style is not None else '')+'><v>'+value+'</v></c>'


def string(cell,value):
    return '<c r="'+cell+'" t="inlineStr"><is><t>'+value+'</t></is></c>'


def cells(result):
    return [change for change in result['changes'] if change['kind'].startswith('cell_')]


def test_legacy_mapping_is_idempotent_and_never_groups_filenames_or_rewrites_history():
    history=[{'event':'source_uploaded','at':'2026-01-01T00:00:00Z','detail':{'source_id':'s1'}}]
    state={'sources':[source(),source('s2')],'history':deepcopy(history)}
    initialize_documents(state);before=deepcopy(state);initialize_documents(state)
    assert state==before
    assert len(state['documents'])==2
    assert state['sources'][0]['uploaded_at']=='2026-01-01T00:00:00Z'
    assert state['sources'][1]['uploaded_at'] is None
    assert state['history']==history


def test_new_revision_preserves_original_source_and_exposes_only_active_heads():
    state={'sources':[]}
    first=add_source_revision(state,source(),reason='Initial evidence',period='2026-Q1',actor='author')
    old=deepcopy(first);raw=source('s2')
    new=add_source_revision(state,raw,document_id=first['document_id'],parent_revision_id='s1',
                            reason='Corrected administrator file',actor='author')
    assert state['sources'][0]==old
    assert new['parent_revision_id']=='s1' and new['period']=='2026-Q1'
    assert state['documents'][0]['revisions']==['s1','s2']
    assert [s['id'] for s in current_sources(state)]==['s2']
    assert 'document_id' not in raw


def test_stale_parent_and_period_or_type_changes_are_rejected():
    state={'sources':[]};one=add_source_revision(state,source(),reason='First',period='Q1',actor='author')
    for kwargs in ({'parent_revision_id':'wrong'},{'parent_revision_id':'s1','period':'Q2'}):
        with pytest.raises(ValueError):add_source_revision(state,source('s2'),document_id=one['document_id'],reason='Changed',actor='author',**kwargs)
    csv=source('s2');csv['media_type']=CSV
    with pytest.raises(ValueError):add_source_revision(state,csv,document_id=one['document_id'],parent_revision_id='s1',reason='Changed',actor='author')
    assert len(state['sources'])==1


def test_inconsistent_existing_graph_does_not_guess_a_head():
    state={'sources':[source()]};initialize_documents(state)
    state['documents'][0]['revisions'].append('missing')
    with pytest.raises(ValueError):current_sources(state)


def test_raw_decimal_changes_are_exact_below_float_precision():
    before=workbook([('Any name',sheet([(7,number('C7','123456789012345.678901'))]))])
    after=workbook([('Any name',sheet([(7,number('C7','123456789012345.678902'))]))])
    result=compare_sources(before,after,XLSX);change=cells(result)[0]
    assert change['fields']==['value']
    assert change['before']['value']=='123456789012345.678901'
    assert change['after_locator']=={'kind':'xlsx','sheet':'Any name','cell':'C7'}
    assert result['coverage']['complete'] is True


def test_formula_text_cache_and_styles_are_separate_change_fields():
    styles='<fonts><font/></fonts><fills><fill/></fills><borders><border/></borders><cellStyleXfs><xf/></cellStyleXfs><cellXfs><xf numFmtId="0"/><xf numFmtId="14"/></cellXfs>'
    old='<c r="A1"><f>B1+1</f><v>4</v></c>'
    new='<c r="A1" s="1"><f>B1+2</f><v>5</v></c>'
    result=compare_sources(workbook([('Data',sheet([(1,old)]))],styles=styles),
                           workbook([('Data',sheet([(1,new)]))],styles=styles),XLSX)
    assert set(cells(result)[0]['fields'])=={'formula','cached_value','style'}
    assert cells(result)[0]['after']['formula']['text']=='B1+2'


def test_formula_change_with_unchanged_cache_is_still_detected():
    old='<c r="A1"><f>B1+1</f><v>4</v></c>';new='<c r="A1"><f>C1+1</f><v>4</v></c>'
    result=compare_sources(workbook([('Sheet',sheet([(1,old)]))]),workbook([('Sheet',sheet([(1,new)]))]),XLSX)
    assert cells(result)[0]['fields']==['formula']


def test_style_definition_changes_are_detected_even_when_cell_style_id_is_unchanged():
    base='<fonts><font>{font}</font></fonts><fills><fill/></fills><borders><border/></borders><cellStyleXfs><xf/></cellStyleXfs><cellXfs><xf fontId="0"/></cellXfs>'
    data=[('Sheet',sheet([(1,number('A1','42'))]))]
    result=compare_sources(workbook(data,styles=base.format(font='<b/>')),
                           workbook(data,styles=base.format(font='<i/>')),XLSX)
    assert cells(result)[0]['fields']==['style']
    assert result['summary']['by_kind']['style_catalog_changed']==1


def test_style_only_cells_and_row_layout_are_not_silently_omitted():
    old=workbook([('Sheet','<sheetData><row r="1"><c r="A1"/></row></sheetData>')])
    new=workbook([('Sheet','<sheetData><row r="1" hidden="1"><c r="A1"/><c r="B1"/></row></sheetData>')])
    result=compare_sources(old,new,XLSX)
    assert result['summary']['by_kind']['cell_added']==1
    assert result['summary']['by_kind']['row_properties_changed']==1


def test_sheet_renames_are_added_and_removed_not_guessed_matches():
    data=sheet([(1,number('A1','42'))])
    result=compare_sources(workbook([('Old',data)]),workbook([('New',data)]),XLSX)
    assert result['summary']['by_kind']['sheet_added']==1
    assert result['summary']['by_kind']['sheet_removed']==1
    assert {c['kind'] for c in cells(result)}=={'cell_added','cell_removed'}


def test_shared_and_inline_storage_rewrites_do_not_change_string_content():
    before=workbook([('Sheet',sheet([(1,'<c r="A1" t="s"><v>0</v></c>')]))],shared=['000123'])
    after=workbook([('Sheet',sheet([(1,string('A1','000123'))]))])
    result=compare_sources(before,after,XLSX)
    assert cells(result)==[]
    assert result['summary']['identical_bytes'] is False


def test_explicit_business_keys_align_moves_and_value_changes():
    before=workbook([('Sheet',sheet([(1,string('A1','ID')+string('B1','Amount')),
                                    (2,string('A2','0001')+number('B2','10')),
                                    (3,string('A3','0002')+number('B3','20'))]))])
    after=workbook([('Sheet',sheet([(1,string('A1','ID')+string('B1','Amount')),
                                   (2,string('A2','0002')+number('B2','21')),
                                   (3,string('A3','0001')+number('B3','10'))]))])
    result=compare_sources(before,after,XLSX,{'Sheet':{'columns':['A'],'header_row':1}})
    assert result['summary']['by_kind']['row_moved']==2
    assert len(cells(result))==1
    assert cells(result)[0]['business_key']==['0002']
    assert cells(result)[0]['before_locator']['cell']=='B3'
    assert cells(result)[0]['after_locator']['cell']=='B2'


def test_duplicate_and_missing_keys_remain_ambiguous():
    before=b'id,value\nA,1\nA,2\n,3\n';after=b'id,value\nA,4\nB,3\n'
    result=compare_sources(before,after,CSV,{'csv':{'columns':['c1'],'header_row':1}})
    codes={item['code'] for item in result['ambiguities']}
    assert {'duplicate_business_key','missing_business_key'}<=codes
    assert not any(c.get('business_key')==['A'] for c in result['changes'])
    assert result['coverage']['complete'] is False


def test_formula_business_keys_are_not_inferred_from_unverified_caches():
    data=workbook([('Sheet',sheet([(1,'<c r="A1"><f>B1</f><v>42</v></c>')]))])
    result=compare_sources(data,data,XLSX,{'Sheet':['A']})
    assert 'formula_business_key' in {item['code'] for item in result['ambiguities']}


def test_csv_keeps_quoted_newline_and_leading_zero_values():
    result=compare_sources(b'Identifier;Note\n0001;"first\nline"\n',
                           b'Identifier;Note\n0001;"second\nline"\n',CSV)
    change=cells(result)[0]
    assert change['before']['value']=='first\nline'
    assert change['after_locator']=={'kind':'csv','row':2,'column':2}


def test_change_pagination_bounds_preserve_full_counts_and_explicit_incompleteness():
    before=b'A,B\n1,2\n';after=b'A,B\n3,4\n'
    result=compare_sources(before,after,CSV,limits=ComparisonLimits(max_changes=1))
    assert result['summary']['change_count']==2
    assert len(result['changes'])==1
    assert result['coverage']['source_scan_complete'] is True
    assert result['coverage']['changes_complete'] is False
    assert result['coverage']['complete'] is False


def test_source_bounds_and_malformed_inputs_cannot_report_clean_comparison():
    data=workbook([('Sheet',sheet([(1,number('A1','1')),(2,number('A2','2'))]))])
    result=compare_sources(data,data,XLSX,extraction_limits=ExtractionLimits(max_rows=1))
    assert result['coverage']['source_scan_complete'] is False
    assert 'comparison_incomplete' in {item['code'] for item in result['ambiguities']}
    assert compare_sources(b'bad',b'bad',XLSX)['coverage']['complete'] is False


def test_changed_visual_package_parts_have_unknown_interpretation():
    data=[('Sheet',sheet([(1,number('A1','1'))]))]
    result=compare_sources(workbook(data,extra={'xl/media/image1.png':b'old'}),
                           workbook(data,extra={'xl/media/image1.png':b'new'}),XLSX)
    assert 'unmodeled_content_changed' in {item['code'] for item in result['ambiguities']}
    assert result['summary']['by_kind']['package_part_changed']==1


def dependency_state():
    state={'sources':[source('s1'),source('s2'),source('s3')],'datasets':[
        {'id':'table1','table_id':'table1','source_id':'s1','kind':'extraction','title':'Ledger'},
        {'id':'table2','table_id':'table2','source_id':'s2','kind':'extraction','title':'Map'}],
        'recipe':{'version':1,'steps':[{'id':'joined','op':'join','input':'table1','right':'table2'}],
                  'output':'joined','checks':[{'type':'required','columns':['c1']}]},'requirements':[]}
    initialize_documents(state)
    return state


def test_dependency_graph_includes_joins_checks_templates_and_explicit_requirements():
    state=dependency_state();state['recipe']['export']={'template_source_id':'s3'}
    state['requirements']=[{'id':'evidence','kind':'evidence','document_ids':[state['documents'][0]['id']]}]
    result=output_dependency_ids(state)
    assert result['known'] is True
    assert result['source_ids']==['s1','s2','s3']
    assert len(result['document_ids'])==3


def test_unrelated_document_is_not_an_output_dependency_but_missing_edges_are_unknown():
    state=dependency_state();assert output_dependency_ids(state)['source_ids']==['s1','s2']
    state['recipe']['steps'][0]['right']='missing'
    assert output_dependency_ids(state)['known'] is False


def test_stale_revision_dependency_and_ambiguous_required_dataset_are_unknown():
    state=dependency_state();doc=state['documents'][0]
    add_source_revision(state,source('s4'),document_id=doc['id'],parent_revision_id='s1',reason='Corrected',actor='author')
    assert output_dependency_ids(state)['known'] is False
    state=dependency_state();state['datasets'].append({**state['datasets'][0],'id':'other','table_id':'other'})
    state['requirements']=[{'document_ids':[state['documents'][0]['id']],
                            'dataset_selector':{'document_id':state['documents'][0]['id'],'table_title':'Ledger'}}]
    assert output_dependency_ids(state)['known'] is False


def test_dependency_fingerprint_pins_selected_revisions_and_rule_configuration():
    state=dependency_state();first=document_fingerprint(state,recipe={'rule':'a'})
    assert first!=document_fingerprint(state,recipe={'rule':'b'})
    doc=state['documents'][0]
    add_source_revision(state,source('s4'),document_id=doc['id'],parent_revision_id='s1',reason='Corrected',actor='author')
    assert first!=document_fingerprint(state,recipe={'rule':'a'})
