from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED
import pytest
from openpyxl import Workbook
from closegraph.extraction.excel import ExcelLayout, extract_excel
from closegraph.extraction.common import ExtractionError, ExtractionLimits

def workbook():
    w=Workbook(); w.active.title="Pack"; w.active["A1"]="001"; w.active["B1"]=75000; w.active["B2"]="=B1*0.8"
    b=BytesIO(); w.save(b); return b.getvalue()

def rewrite(data,name,fn):
    b=BytesIO()
    with ZipFile(BytesIO(data)) as src, ZipFile(b,"w",ZIP_DEFLATED) as out:
        for item in src.infolist():
            p=src.read(item.filename); out.writestr(item,fn(p) if item.filename==name else p)
    return b.getvalue()

def test_values_formula_missing_and_locators():
    data=workbook(); r=extract_excel(data,document_version_id="v",layout=ExcelLayout("Pack",("A1","B1","B2","C2")))
    assert r["source_bytes"]==data
    a,b,f,m=r["observations"]
    assert a["raw_value"]=="001" and b["raw_value"]=="75000"
    assert b["source"]["locator"]=={"kind":"xlsx","sheet":"Pack","cell":"B1"}
    assert f["formula"]=="=B1*0.8" and f["cache_status"]=="MISSING"
    assert f["interpretation_status"]=="FORMULA_UNRESOLVED" and m["interpretation_status"]=="MISSING"

def test_cached_formula_not_current():
    from xml.etree import ElementTree as ET
    def supply_cache(payload):
        ns="{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
        tree=ET.fromstring(payload)
        cell=next(c for c in tree.iter(ns+"c") if c.get("r")=="B2")
        assert cell.find(ns+"f").text=="B1*0.8"
        value=cell.find(ns+"v")
        if value is None:
            value=ET.SubElement(cell,ns+"v")
        value.text="60000"
        return ET.tostring(tree,encoding="utf-8")
    data=rewrite(workbook(),"xl/worksheets/sheet1.xml",supply_cache)
    f=extract_excel(data,document_version_id="v",layout=ExcelLayout("Pack",("B2",)))["observations"][0]
    assert f["cached_value"]=="60000" and f["cache_status"]=="UNVERIFIED" and f["interpretation_status"]=="FORMULA_UNRESOLVED"

def test_numeric_xml_not_float_roundtrip():
    data=rewrite(workbook(),"xl/worksheets/sheet1.xml",lambda p:p.replace(b"<v>75000</v>",b"<v>12345678901234567890.123456789</v>"))
    assert extract_excel(data,document_version_id="v",layout=ExcelLayout("Pack",("B1",)))["observations"][0]["raw_value"]=="12345678901234567890.123456789"

@pytest.mark.parametrize("name,payload,code",[("xl/vbaProject.bin",b"no","unsupported_macros"),("xl/externalLinks/externalLink1.xml",b"<x/>","unsupported_external_links"),("../escape",b"x","unsafe_zip_member")])
def test_unsafe_archive(name,payload,code):
    b=BytesIO(workbook())
    with ZipFile(b,"a") as z:z.writestr(name,payload)
    with pytest.raises(ExtractionError,match=code):extract_excel(b.getvalue(),document_version_id="v",layout=ExcelLayout("Pack",("B1",)))

def test_bad_layout_and_limits():
    for data,layout,limits,code in [(b"not zip",ExcelLayout("Pack",("B1",)),ExtractionLimits(),"invalid_xlsx"),(workbook(),ExcelLayout("Missing",("B1",)),ExtractionLimits(),"unsupported_layout"),(workbook(),ExcelLayout("Pack",("B1",)),ExtractionLimits(max_cells=1),"limit")]:
        with pytest.raises(ExtractionError,match=code):extract_excel(data,document_version_id="v",layout=layout,limits=limits)
