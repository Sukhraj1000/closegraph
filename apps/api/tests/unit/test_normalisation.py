from decimal import Decimal
import pytest
from closegraph.extraction.numbers import parse_decimal, normalise_number, NumericFormat, NumericError
from closegraph.extraction.context import normalise_fact

def observation(raw="60",**kw):return {"occurrence_id":"o1","raw_value":raw,"raw_scale":"thousands","metric":"Management fee","entity_id":"0001","currency":"GBP","period":"2026-Q2","source":{"document_version_id":"v1","content_hash":"a"*64,"locator":{"kind":"xlsx","sheet":"Pack","cell":"B2"}},**kw}
M={"version":"metrics-v1","approved":True,"approval_id":"synthetic-approval","entity_id":"0001","period":"2026-Q2","mapping":{"Management fee":"management_fee"}}

def test_scoped_mapping_explicit_scale():
    o=observation(); r=normalise_fact(o,mapping=M)
    assert r["value_decimal"]=="60000" and r["raw_value"]=="60" and r["raw_scale"]=="thousands"
    assert r["metric"]=="management_fee" and r["entity_id"]=="0001" and r["interpretation_status"]=="RESOLVED"
    assert o["metric"]=="Management fee"

@pytest.mark.parametrize("raw,expected",[("(1,234.50)",Decimal("-1234.50")),("0",Decimal("0")),("",None),("NA",None)])
def test_numbers(raw,expected):assert parse_decimal(raw)==expected

def test_float_ambiguous_nonfinite_implicit_units_forbidden():
    for raw in [0.1,True,"NaN","Infinity","1,23","12k","1e9999999"]:
        with pytest.raises(NumericError):parse_decimal(raw)
    assert parse_decimal("1.234,50",NumericFormat(decimal_separator=",",thousands_separator="."))==Decimal("1234.50")
    assert normalise_number("2",scale="millions")["value_decimal"]=="2000000"
    with pytest.raises(NumericError):normalise_number("2",scale=None)

@pytest.mark.parametrize("kw",[{"currency":None},{"period":None},{"entity_id":None},{"raw_scale":None},{"period":"2026-Q1"},{"interpretation_status":"FORMULA_UNRESOLVED"}])
def test_context_formula_unknown(kw):assert normalise_fact(observation(**kw),mapping=M)["interpretation_status"]!="RESOLVED"

def test_mapping_authority():
    for kw in [{"approved":False},{"approval_id":None}]:assert normalise_fact(observation(),mapping={**M,**kw})["interpretation_status"]!="RESOLVED"
