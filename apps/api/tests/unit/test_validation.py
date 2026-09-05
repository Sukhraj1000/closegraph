import polars as pl
from closegraph.validators.schema import validate_rows
from closegraph.validators.coverage import coverage_check


def test_schema_checks_values_not_only_dtypes():
    good={'entity_id':'0012','period':'2026-Q1','currency':'GBP','metric':'capital','value':'0','scale':'units'}
    assert validate_rows(pl.DataFrame([good]))['status']=='PASS'
    for field,value in [('currency','ZZZ'),('value',''),('period','2026-Q5'),('scale','unknown'),('entity_id','')]:
        row={**good,field:value}
        result=validate_rows(pl.DataFrame([row]))
        assert result['status']=='FAIL'
        assert result['diagnostics']


def test_coverage_preserves_every_source_occurrence():
    source={'document_version_id':'doc1','content_hash':'a'*64,'locator':{'kind':'csv','row':2}}
    rows=[{'occurrence_id':'one','disposition':'ACCEPTED','source':source}]
    assert coverage_check(['one'],rows)['status']=='PASS'
    assert coverage_check(['one','two'],rows)['status']=='FAIL'
    assert coverage_check(['one'],rows*2)['status']=='FAIL'
    assert coverage_check(['one'],[{**rows[0],'source':{}}])['status']=='FAIL'
    assert coverage_check(['one'],[{**rows[0],'disposition':'REJECTED'}])['status']=='FAIL'
