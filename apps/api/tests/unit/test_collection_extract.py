"""Unseen, synthetic layouts; no provider network calls or private dataset fixtures."""
import base64
import io
import json
import zipfile
from hashlib import sha256
from xml.sax.saxutils import escape

import pytest

from closegraph.collections.extract import ExtractionLimits, extract_source
from closegraph.contracts import Scope
from closegraph.extractors.reducto import ReductoResult, decode_response

SCOPE = Scope(tenant_id='test', fund_id='fund', pack_id='collection')
MAIN = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
RELS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PDF = b'%PDF-1.4\nSynthetic unit test only'


def extract(content, filename='arbitrary.csv', **kwargs):
    return extract_source(content, filename=filename, media_type='', source_id='source',
                          document_version_id='version', **kwargs)


def workbook(sheets, *, shared=(), styles=None, tables=None, extra=None):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
        sheet_nodes, links = [], []
        for index, (name, data) in enumerate(sheets, 1):
            sheet_nodes.append(f'<sheet name="{escape(name)}" sheetId="{index}" r:id="r{index}"/>')
            links.append(f'<Relationship Id="r{index}" Target="worksheets/sheet{index}.xml"/>')
            output.writestr(f'xl/worksheets/sheet{index}.xml',
                            f'<worksheet xmlns="{MAIN}">{data}</worksheet>')
        output.writestr('xl/workbook.xml', f'<workbook xmlns="{MAIN}" xmlns:r="{RELS}">'
                        '<workbookPr date1904="1"/><sheets>' + ''.join(sheet_nodes) + '</sheets></workbook>')
        output.writestr('xl/_rels/workbook.xml.rels', '<Relationships>' + ''.join(links) + '</Relationships>')
        if shared:
            output.writestr('xl/sharedStrings.xml', f'<sst xmlns="{MAIN}">' +
                            ''.join('<si><t>' + escape(value) + '</t></si>' for value in shared) + '</sst>')
        if styles:
            output.writestr('xl/styles.xml', f'<styleSheet xmlns="{MAIN}">{styles}</styleSheet>')
        if tables:
            output.writestr('xl/worksheets/_rels/sheet1.xml.rels', '<Relationships>' +
                            ''.join(f'<Relationship Id="t{i}" Target="../tables/t{i}.xml"/>'
                                    for i in range(len(tables))) + '</Relationships>')
            for index, (name, ref) in enumerate(tables):
                output.writestr(f'xl/tables/t{index}.xml',
                                f'<table xmlns="{MAIN}" displayName="{name}" ref="{ref}"/>')
        for name, value in (extra or {}).items():
            output.writestr(name, value)
    return archive.getvalue()


def codes(result):
    return {issue['code'] for issue in result['issues']}


def rows(result):
    return [row for table in result['tables'] for row in table['rows']]


def test_csv_preserves_identifiers_decimal_tokens_and_multiline_source_records():
    result = extract(b'Identifier;Amount;Note\r\n000019;123456789012345.6789;"two\nlines"\r\n')
    table = result['tables'][0]
    assert table['rows'][1]['values'] == {'c1': '000019', 'c2': '123456789012345.6789', 'c3': 'two\nlines'}
    assert table['rows'][1]['locators']['c3'] == {'kind': 'csv', 'row': 2, 'column': 3}
    assert table['rows'][1]['metadata']['physical_line_end'] == 3
    assert table['metadata']['suggested_header_row_id'] == 'csv:r1'
    assert len(table['rows']) == 2  # Suggested header has not silently disappeared.
    assert result['coverage']['complete'] is True


def test_ragged_csv_is_preserved_without_padding_or_shifting():
    result = extract(b'name,value\nA,1,extra\nB\n')
    assert rows(result)[1]['values']['c3'] == 'extra'
    assert rows(result)[2]['values'] == {'c1': 'B'}
    assert 'ragged_rows' in codes(result)


def test_csv_utf16_and_windows_encoding_are_explicit():
    utf16 = extract('Name\tValue\nCrème\t12,34\n'.encode('utf-16'), filename='input.tsv')
    assert rows(utf16)[1]['values'] == {'c1': 'Crème', 'c2': '12,34'}
    windows = extract('Name;Value\nCrème;12,34\n'.encode('cp1252'))
    assert 'encoding_assumed' in codes(windows)
    assert windows['parser']['settings']['encoding'] == 'cp1252'


def test_malformed_csv_preserves_prefix_and_reports_error():
    result = extract(b'name,value\nA,1\n"unterminated')
    assert rows(result)[1]['values']['c2'] == '1'
    assert 'malformed_csv' in codes(result)
    assert result['coverage']['complete'] is False


def test_csv_limits_make_truncation_explicit():
    result = extract(b'a,b\n1,2\n3,4\n', limits=ExtractionLimits(max_rows=2))
    assert len(rows(result)) == 2
    assert 'row_limit' in codes(result)
    assert result['coverage']['complete'] is False


def test_xlsx_discovers_multiple_sheets_regions_sparse_cells_and_raw_numbers():
    first = '<sheetData><row r="3"><c r="B3" t="s"><v>0</v></c><c r="D3" t="s"><v>1</v></c></row>' \
            '<row r="4"><c r="B4" t="s"><v>2</v></c><c r="D4"><v>123456789012345.67890</v></c></row>' \
            '<row r="40"><c r="C40" t="inlineStr"><is><t>Footnote</t></is></c></row></sheetData>'
    second = '<sheetData><row r="1"><c r="A1"><v>-2.1E-07</v></c></row></sheetData>'
    result = extract(workbook([('Transactions', first), ('Different name', second)],
                             shared=['Account', 'Amount', '000007']), filename='not-a-pack.xlsx')
    assert len(result['tables']) == 3
    assert result['tables'][0]['rows'][1]['values'] == {'c2': '000007', 'c4': '123456789012345.67890'}
    assert result['tables'][0]['rows'][1]['locators']['c4']['cell'] == 'D4'
    assert result['tables'][2]['rows'][0]['values']['c1'] == '-2.1E-07'
    assert result['parser']['settings']['date_epoch'] == '1904'
    assert result['coverage']['complete'] is True


def test_xlsx_formula_cache_and_format_evidence_are_not_evaluated():
    sheet = '<sheetData><row r="1"><c r="A1" s="0"><v>45200</v></c>' \
            '<c r="B1"><f>A1*2</f><v>90400</v></c><c r="C1"><f>A1+1</f></c></row></sheetData>'
    styles = '<numFmts><numFmt numFmtId="164" formatCode="yyyy-mm-dd"/></numFmts>' \
             '<cellXfs><xf numFmtId="164"/></cellXfs>'
    result = extract(workbook([('Dates', sheet)], styles=styles), filename='dates.xlsx')
    row = rows(result)[0]
    assert row['values'] == {'c1': '45200', 'c2': '90400', 'c3': None}
    assert row['metadata']['cells']['c1']['number_format'] == 'yyyy-mm-dd'
    assert row['metadata']['cells']['c2']['formula']['cache_verified'] is False
    assert row['metadata']['cells']['c3']['formula']['expression'] == 'A1+1'
    assert {'formula_cache_missing', 'formula_cache_unverified'} <= codes(result)


def test_xlsx_merged_headers_do_not_fill_nonexistent_values():
    sheet = '<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Group</t></is></c>' \
            '<c r="B1" s="0"/></row></sheetData><mergeCells><mergeCell ref="A1:C1"/></mergeCells>'
    result = extract(workbook([('Merged', sheet)]), filename='merged.xlsx')
    assert rows(result)[0]['values'] == {'c1': 'Group'}
    assert 'merged_cells' in codes(result)
    assert result['tables'][0]['metadata']['merged_ranges'] == ['A1:C1']


def test_declared_tables_and_residual_grid_preserve_each_cell_once():
    sheet = '<sheetData><row r="1"><c r="A1"><v>1</v></c><c r="D1"><v>2</v></c>' \
            '<c r="H1"><v>3</v></c></row></sheetData>'
    result = extract(workbook([('Mix', sheet)], tables=[('First', 'A1:B4'), ('Second', 'D1:F3')]),
                     filename='tables.xlsx')
    assert {table['title'] for table in result['tables']} == {'First', 'Second', 'Mix · row 1'}
    assert sum(len(row['values']) for row in rows(result)) == 3
    assert result['coverage']['complete'] is True


def test_xlsx_does_not_trust_inflated_used_range_or_style_only_rows():
    sheet = '<dimension ref="A1:XFD1048576"/><sheetData><row r="1"><c r="A1"><v>42</v></c></row>' \
            '<row r="1048576"><c r="XFD1048576" s="123"/></row></sheetData>'
    result = extract(workbook([('Sparse', sheet)]), filename='huge-dimensions.xlsx')
    assert len(rows(result)) == 1
    assert rows(result)[0]['values']['c1'] == '42'
    assert result['coverage']['complete'] is True


def test_xlsx_streams_one_hundred_thousand_data_rows():
    sheet = '<sheetData>' + ''.join(f'<row r="{i}"><c r="A{i}"><v>{i}</v></c></row>'
                                    for i in range(1, 100_002)) + '</sheetData>'
    result = extract(workbook([('Unseen ledger', sheet)]), filename='large.xlsx')
    assert result['coverage']['complete'] is True
    assert result['coverage']['extracted_rows'] == 100_001
    assert rows(result)[-1]['values']['c1'] == '100001'


def test_workbook_limits_and_invalid_xml_never_pass():
    data = workbook([('One', '<sheetData><row r="1"><c r="A1"><v>1</v></c></row></sheetData>')])
    bounded = extract(data, filename='one.xlsx', limits=ExtractionLimits(max_uncompressed_bytes=20))
    assert 'uncompressed_limit' in codes(bounded)
    invalid = extract(workbook([('Bad', '<!DOCTYPE x [<!ENTITY a "x">]><sheetData/>')]), filename='bad.xlsx')
    assert 'malformed_workbook' in codes(invalid)
    assert invalid['coverage']['complete'] is False


def test_ids_are_deterministic_but_document_version_changes_table_identity():
    first = extract(b'a,b\n1,2')
    again = extract(b'a,b\n1,2')
    other = extract_source(b'a,b\n1,2', filename='x.csv', media_type='text/csv',
                           source_id='source', document_version_id='next')
    assert first['tables'][0]['table_id'] == again['tables'][0]['table_id']
    assert first['tables'][0]['table_id'] != other['tables'][0]['table_id']


def provider(blocks):
    raw = json.dumps({'job_id': 'synthetic-unit-only', 'model_version': 'mock',
                      'result': {'type': 'full', 'chunks': [{'blocks': blocks}]}}).encode()
    result = decode_response(raw, scope=SCOPE, document_version_id='version',
                             source_sha256=sha256(PDF).hexdigest(), mode='SYNTHETIC')
    class Provider:
        def parse(self, source, **kwargs):
            assert source == PDF
            return result
    return Provider(), raw


def block(content, kind='Table'):
    return {'type': kind, 'content': content, 'confidence': 'high',
            'bbox': {'original_page': 5, 'page': 1, 'left': .1, 'top': .2, 'width': .5, 'height': .2}}


def test_pdf_html_table_preserves_raw_response_and_block_precision():
    parser, raw = provider([block('<table><tr><th>Identifier</th><th>Value</th></tr>'
                                 '<tr><td>00001</td><td>1,234.50</td></tr></table>')])
    result = extract(PDF, filename='whatever.pdf', pdf_provider=parser, scope=SCOPE)
    row = rows(result)[1]
    assert row['values'] == {'c1': '00001', 'c2': '1,234.50'}
    assert row['locators']['c2']['original_page'] == 5
    assert row['locators']['c2']['citation_precision'] == 'block'
    assert row['locators']['c1']['bbox'] == row['locators']['c2']['bbox']
    assert base64.b64decode(result['parser']['raw_response_base64']) == raw
    assert result['parser']['mode'] == 'SYNTHETIC'
    assert result['coverage']['row_completeness'] == 'UNVERIFIED'


def test_pdf_spans_do_not_duplicate_values_into_merged_cells():
    parser, _ = provider([block('<table><tr><td rowspan="2">A</td><td colspan="2">B</td></tr>'
                               '<tr><td>C</td><td>D</td></tr></table>')])
    result = extract(PDF, filename='test.pdf', pdf_provider=parser, scope=SCOPE)
    assert rows(result)[0]['values'] == {'c1': 'A', 'c2': 'B'}
    assert rows(result)[1]['values'] == {'c2': 'C', 'c3': 'D'}
    assert len(result['tables'][0]['metadata']['spans']) == 2


def test_pdf_markdown_table_and_unstructured_text_are_both_retained():
    parser, _ = provider([block('| Account | Amount |\n| --- | ---: |\n| A\\|B | -12.40 |'),
                          block('Unmapped narrative remains evidence.', 'Text')])
    result = extract(PDF, filename='test.pdf', pdf_provider=parser, scope=SCOPE)
    assert result['tables'][0]['rows'][1]['values'] == {'c1': 'A|B', 'c2': '-12.40'}
    assert result['tables'][1]['rows'][0]['values']['c1'] == 'Unmapped narrative remains evidence.'
    assert result['coverage']['extracted_blocks'] == 2


def test_pdf_bad_citation_does_not_destroy_extracted_text_or_invent_a_box():
    bad = block('Preserve this text', 'Text')
    bad['bbox'].pop('original_page')
    parser, _ = provider([bad])
    result = extract(PDF, filename='bad.pdf', pdf_provider=parser, scope=SCOPE)
    assert rows(result)[0]['values']['c1'] == 'Preserve this text'
    assert rows(result)[0]['locators'] == {}
    assert {'pdf_citation_missing', 'provider_diagnostic'} <= codes(result)
    assert result['coverage']['complete'] is False


def test_pdf_disabled_and_mismatched_provider_never_substitute_fixture():
    disabled = extract(PDF, filename='missing.pdf')
    assert disabled['tables'] == []
    assert 'provider_unavailable' in codes(disabled)
    class Wrong:
        def parse_pdf(self, source, **kwargs):
            return ReductoResult('AVAILABLE', '0' * 64)
    wrong = extract(PDF, filename='wrong.pdf', pdf_provider=Wrong(), scope=SCOPE)
    assert 'provider_source_mismatch' in codes(wrong)
    assert wrong['tables'] == []


def test_pdf_malformed_html_falls_back_to_exact_text():
    content = '<table><tr><td>Unclosed value'
    parser, _ = provider([block(content)])
    result = extract(PDF, filename='broken.pdf', pdf_provider=parser, scope=SCOPE)
    assert rows(result)[0]['values']['c1'] == content
    assert 'pdf_table_unresolved' in codes(result)


def test_xlsx_invalid_shared_string_and_error_cell_are_explicit():
    invalid = '<sheetData><row r="1"><c r="A1" t="s"><v>-1</v></c></row></sheetData>'
    result = extract(workbook([('Broken', invalid)], shared=['safe']), filename='bad.xlsx')
    assert 'malformed_workbook' in codes(result)
    error = '<sheetData><row r="1"><c r="A1" t="e"><v>#REF!</v></c></row></sheetData>'
    result = extract(workbook([('Error', error)]), filename='errors.xlsx')
    assert 'spreadsheet_error' in codes(result)
    assert rows(result)[0]['values']['c1'] == '#REF!'


def test_unsupported_file_and_invalid_limit_configuration():
    result = extract(b'not an xls workbook', filename='ancient.xls')
    assert 'unsupported_format' in codes(result)
    with pytest.raises(ValueError):
        ExtractionLimits(max_rows=0)


def test_delimiter_detection_reports_equal_record_evidence_as_ambiguous():
    result = extract(b'Label;Value,Note\nA;12,other\n')
    assert 'delimiter_ambiguous' in codes(result)
    diagnostic = next(item for item in result['issues'] if item['code'] == 'delimiter_ambiguous')
    assert set(diagnostic['details']['candidates']) == {',', ';'}
    assert result['parser']['settings']['delimiter'] == ','


def test_csv_record_detection_handles_newlines_and_embedded_decimal_commas():
    result = extract(b'Name;Amount;Note\nA;12,50;"first\nsecond"\nB;2,30;ordinary\n')
    assert result['parser']['settings']['delimiter'] == ';'
    assert rows(result)[1]['values'] == {'c1': 'A', 'c2': '12,50', 'c3': 'first\nsecond'}
    assert rows(result)[2]['values']['c2'] == '2,30'
