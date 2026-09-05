import polars as pl
import pytest
from closegraph.extraction.csv import CSVLayout, extract_csv
from closegraph.extraction.common import ExtractionError, ExtractionLimits
L=CSVLayout(columns=("entity_id","amount"),required_fields=("entity_id",))

def test_raw_tokens_ids_duplicates_rejects():
    data=b'entity_id,amount\n001,"1,000.00"\n001,0\n002,3,extra\n,9\n'
    r=extract_csv(data,document_version_id="v",layout=L)
    assert r["source_bytes"]==data
    assert r["frame"].schema=={"entity_id":pl.String,"amount":pl.String}
    assert r["frame"].to_dicts()==[{"entity_id":"001","amount":"1,000.00"},{"entity_id":"001","amount":"0"}]
    assert [d["disposition"] for d in r["dispositions"]]==["ACCEPTED","ACCEPTED","REJECTED","REJECTED"]
    assert len({d["occurrence_id"] for d in r["dispositions"]})==4
    assert r["observations"][0]["raw_record"]=='001,"1,000.00"\n'
    assert r["observations"][0]["source"]["locator"]["row"]==2
    assert extract_csv(data,document_version_id="v",layout=L)["dispositions"]==r["dispositions"]

def test_delimiter_multiline_empty_tokens():
    r=extract_csv(b'entity_id;amount\r\n001;"1\n2"\r\n002;NA\r\n003;\r\n',document_version_id="v",layout=CSVLayout(columns=L.columns,delimiter=";"))
    assert r["frame"]["amount"].to_list()==["1\n2","NA",""]
    assert r["observations"][1]["source"]["locator"]["row"]==4

@pytest.mark.parametrize("data,code",[(b'x,y\n1,2',"unsupported_layout"),(b'entity_id,amount\n001,"bad',"malformed_csv"),(b'entity_id,amount\n\xff,2',"invalid_encoding")])
def test_fail_closed(data,code):
    with pytest.raises(ExtractionError,match=code):extract_csv(data,document_version_id="v",layout=L)

def test_limits_and_hash():
    with pytest.raises(ExtractionError,match="limit"):extract_csv(b'entity_id,amount\n001,2\n002,3',document_version_id="v",layout=L,limits=ExtractionLimits(max_rows=1))
    with pytest.raises(ExtractionError,match="hash_mismatch"):extract_csv(b'entity_id,amount\n001,2',document_version_id="v",layout=L,content_hash="0"*64)
