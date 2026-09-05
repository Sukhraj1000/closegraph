"""Native draft extraction without financial interpretation or generated execution.

CSV values remain text. XLSX values are their original XML tokens (including date
serials); number formats, formulas and cached values are separate evidence. Headers
are suggested, never silently consumed: set_header is an explicit review action.
XML input is streamed; returned tables are bounded, materialised review datasets.
"""
from __future__ import annotations

import csv
from collections import Counter
from fractions import Fraction
import io
import json
import posixpath
import re
import zipfile
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET

NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
CELL = re.compile(r'^([A-Z]{1,3})([1-9][0-9]*)$')
NUMERIC = re.compile(r'^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$')


@dataclass(frozen=True)
class ExtractionLimits:
    max_source_bytes: int = 64 * 1024 * 1024
    max_uncompressed_bytes: int = 512 * 1024 * 1024
    max_member_bytes: int = 256 * 1024 * 1024
    max_zip_members: int = 4096
    max_rows: int = 250_000
    max_cells: int = 4_000_000
    max_columns: int = 1024
    max_sheets: int = 128
    max_tables: int = 10_000
    max_text_chars: int = 200_000
    max_shared_strings: int = 1_000_000

    def __post_init__(self):
        if any(type(value) is not int or value <= 0 for value in asdict(self).values()):
            raise ValueError('Extraction limits must be positive integers')


class ExtractionLimit(ValueError):
    pass


def identifier(*parts):
    return sha256(json.dumps(parts, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()[:24]


def issue(code, message, *, source_id, severity='warning', **context):
    return {'id': identifier(source_id, code, context), 'source_id': source_id,
            'severity': severity, 'code': code, 'message': message, **context}


def _column(index):
    result = ''
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _coordinate(value):
    match = CELL.fullmatch(value or '')
    if not match:
        raise ValueError('Invalid worksheet cell coordinate')
    column = 0
    for char in match[1]:
        column = column * 26 + ord(char) - 64
    return int(match[2]), column


def _range(value):
    start, _, end = value.partition(':')
    r1, c1 = _coordinate(start.replace('$', ''))
    r2, c2 = _coordinate((end or start).replace('$', ''))
    if r1 > r2 or c1 > c2:
        raise ValueError('Reversed worksheet range')
    return r1, c1, r2, c2


class _Result:
    def __init__(self, source_id, document_version_id, limits):
        self.source_id, self.document_version_id, self.limits = source_id, document_version_id, limits
        self.tables, self.issues = [], []
        self.row_count = self.cell_count = self.empty_rows = 0
        self.complete = True

    def report(self, code, message, severity='warning', **context):
        self.issues.append(issue(code, message, source_id=self.source_id,
                                 severity=severity, **context))
        if severity == 'error':
            self.complete = False

    def table(self, title, region, **metadata):
        if len(self.tables) >= self.limits.max_tables:
            raise ExtractionLimit('table_limit')
        table = {'table_id': identifier(self.document_version_id, region),
                 'source_id': self.source_id, 'title': title, 'columns': [], 'rows': [],
                 'metadata': metadata}
        self.tables.append(table)
        return table

    def append(self, table, row, column_labels):
        count = len(row['values'])
        if self.row_count >= self.limits.max_rows:
            raise ExtractionLimit('row_limit')
        if self.cell_count + count > self.limits.max_cells:
            raise ExtractionLimit('cell_limit')
        if len(column_labels) > self.limits.max_columns:
            raise ExtractionLimit('column_limit')
        if any(value is not None and len(value) > self.limits.max_text_chars
               for value in row['values'].values()):
            raise ExtractionLimit('cell_text_limit')
        table['rows'].append(row)
        self.row_count += 1
        self.cell_count += count
        existing = {item['key'] for item in table['columns']}
        for key, label in column_labels.items():
            if key not in existing:
                table['columns'].append({'key': key, 'label': label})
        table['columns'].sort(key=lambda column: int(column['key'][1:]))

    def finish(self, parser, **coverage):
        for table in self.tables:
            if not table['rows']:
                continue
            row = table['rows'][0]
            values = [value for value in row['values'].values() if value is not None and value != '']
            # A draft hint only: every source row, including this row, is retained.
            if len(values) >= 2 and all(not NUMERIC.fullmatch(value.strip()) for value in values):
                table['metadata']['suggested_header_row_id'] = row['row_id']
                table['metadata']['suggested_headers'] = dict(row['values'])
                self.report('header_candidate', 'Possible header row retained in data; confirm it in review.',
                            'info', table_id=table['table_id'], row_id=row['row_id'])
            table['row_count'] = len(table['rows'])
        return {'tables': self.tables, 'issues': self.issues, 'parser': parser,
                'coverage': {'complete': self.complete, 'extracted_rows': self.row_count,
                             'extracted_cells': self.cell_count, 'empty_rows': self.empty_rows,
                             'table_count': len(self.tables), 'limits': asdict(self.limits),
                             'financial_interpretation': 'NOT_PERFORMED', **coverage}}


class _SafeXML:
    """Reject DTD/entity declarations even when they straddle streamed reads."""
    def __init__(self, stream):
        self.stream, self.tail = stream, b''

    def read(self, size=-1):
        chunk = self.stream.read(size)
        probe = (self.tail + chunk).replace(b'\0', b'').upper()
        if b'<!DOCTYPE' in probe or b'<!ENTITY' in probe:
            raise ValueError('XML declarations are not supported')
        self.tail = (self.tail + chunk)[-32:]
        return chunk


def _xml(archive, name):
    with archive.open(name) as stream:
        return ET.parse(_SafeXML(stream)).getroot()


def _iter_xml(archive, name, tag):
    with archive.open(name) as stream:
        iterator = ET.iterparse(_SafeXML(stream), events=('start', 'end'))
        _, root = next(iterator)
        for event, element in iterator:
            if event == 'end' and element.tag == NS + tag:
                yield element
                element.clear()
                # Detach completed rows/strings to keep parsing memory bounded.
                if tag == 'si':
                    root.clear()
                elif tag == 'row':
                    data = root.find(NS + 'sheetData')
                    if data is not None:
                        data.clear()


def _relationship_path(part):
    path = PurePosixPath(part)
    return str(path.parent / '_rels' / (path.name + '.rels'))


def _relationships(archive, part):
    name = _relationship_path(part)
    if name not in archive.namelist():
        return {}
    result = {}
    for node in _xml(archive, name):
        if node.get('TargetMode', '').lower() == 'external':
            continue
        target = node.get('Target', '')
        resolved = posixpath.normpath(target.lstrip('/') if target.startswith('/')
                                    else posixpath.join(posixpath.dirname(part), target))
        if resolved.startswith('../') or resolved.startswith('/') or '\\' in resolved:
            raise ValueError('Unsafe workbook relationship')
        result[node.get('Id')] = resolved
    return result


def _csv_dialect(sample, filename, result):
    """Compare parsed records, not physical lines, when discovering delimiters.

    Sniffer's line-frequency fallback misreads quoted multiline fields. Each
    candidate here uses the CSV parser itself; inconclusive ties stay visible.
    """
    dialects, scores = {}, {}
    for delimiter in (',', ';', '\t', '|'):
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=delimiter)
        except csv.Error:
            dialect = None
        dialects[delimiter] = dialect
        reader = csv.reader(io.StringIO(sample, newline=''), dialect=dialect or 'excel',
                            delimiter=delimiter, strict=True)
        widths = []
        try:
            for row in reader:
                if row:
                    widths.append(len(row))
                if len(widths) >= 100:
                    break
        except csv.Error:
            # A bounded sample may end inside a quoted record. Only completed
            # records vote; the full source parser still reports malformed input.
            pass
        multiple = [width for width in widths if width > 1]
        if multiple:
            scores[delimiter] = (Fraction(len(multiple), len(widths)),
                                 Fraction(Counter(multiple).most_common(1)[0][1], len(widths)))
    preferred = '\t' if filename.lower().endswith('.tsv') else ','
    if not scores:
        result.report('delimiter_assumed', 'Delimiter detection was inconclusive; inspect the draft grid.',
                      details={'delimiter': preferred})
        return preferred, dialects[preferred]
    strongest = max(scores.values())
    candidates = [delimiter for delimiter, score in scores.items() if score == strongest]
    delimiter = preferred if preferred in candidates else candidates[0]
    if len(candidates) > 1:
        result.report('delimiter_ambiguous', 'Several delimiters fit the records; inspect the draft grid.',
                      details={'delimiter': delimiter, 'candidates': candidates})
    return delimiter, dialects[delimiter]


def _csv(content, result, filename):
    encoding = 'utf-8-sig'
    if content.startswith((b'\xff\xfe', b'\xfe\xff')):
        encoding = 'utf-16'
    try:
        content.decode(encoding)
    except UnicodeDecodeError:
        encoding = 'cp1252'
        try:
            content.decode(encoding)
        except UnicodeDecodeError:
            result.report('unsupported_encoding', 'File is not supported UTF-8, UTF-16 or Windows-1252.', 'error')
            return result.finish({'name': 'csv', 'version': 'native-v1', 'mode': 'NATIVE'})
        result.report('encoding_assumed', 'UTF decoding failed; Windows-1252 is a draft interpretation.',
                      details={'encoding': encoding})
    sample = content[:min(len(content), 65536)].decode(encoding, errors='ignore')
    if '\0' in sample:
        result.report('invalid_text', 'NUL bytes found; file is not supported delimited text.', 'error')
        return result.finish({'name': 'csv', 'version': 'native-v1', 'mode': 'NATIVE'})
    delimiter, dialect = _csv_dialect(sample, filename, result)
    table = result.table(filename, 'csv', encoding=encoding, delimiter=delimiter, header_consumed=False)
    stream = io.TextIOWrapper(io.BytesIO(content), encoding=encoding, newline='')
    reader = csv.reader(stream, dialect=dialect or 'excel', delimiter=delimiter, strict=True)
    widths, records = set(), 0
    try:
        for record_number, values in enumerate(reader, 1):
            records = record_number
            if not values:
                result.empty_rows += 1
                continue
            if len(values) > result.limits.max_columns:
                raise ExtractionLimit('column_limit')
            widths.add(len(values))
            row = {'row_id': 'csv:r' + str(record_number),
                   'values': {'c' + str(i): value for i, value in enumerate(values, 1)},
                   'locators': {'c' + str(i): {'kind': 'csv', 'row': record_number, 'column': i}
                                for i in range(1, len(values) + 1)},
                   'metadata': {'source_record': record_number, 'physical_line_end': reader.line_num}}
            result.append(table, row, {'c' + str(i): 'Column ' + str(i) for i in range(1, len(values) + 1)})
    except ExtractionLimit as exc:
        result.report(str(exc), 'Extraction limit reached; retained rows are incomplete.', 'error')
    except (csv.Error, UnicodeDecodeError):
        result.report('malformed_csv', 'CSV parsing failed; retained rows are incomplete.', 'error',
                      details={'physical_line': reader.line_num})
    if not result.row_count:
        result.report('no_tabular_content', 'No delimited records were found.')
    if len(widths) > 1:
        result.report('ragged_rows', 'Records have different column counts; no values were shifted or discarded.',
                      table_id=table['table_id'], details={'widths': sorted(widths)})
    return result.finish({'name': 'csv', 'version': 'native-v1', 'mode': 'NATIVE',
                          'settings': {'encoding': encoding, 'delimiter': delimiter}}, source_records_seen=records)


def _xlsx(content, result):
    parser = {'name': 'xlsx-xml', 'version': 'native-v1', 'mode': 'NATIVE'}
    sheets_seen = 0
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(entries) > result.limits.max_zip_members or len(names) != len(set(names)):
                raise ExtractionLimit('archive_member_limit_or_duplicate')
            if sum(item.file_size for item in entries) > result.limits.max_uncompressed_bytes:
                raise ExtractionLimit('uncompressed_limit')
            if any(item.file_size > result.limits.max_member_bytes or item.flag_bits & 1 for item in entries):
                raise ExtractionLimit('member_limit_or_encrypted')
            if any(name.startswith('/') or '..' in PurePosixPath(name).parts or '\\' in name for name in names):
                raise ValueError('Unsafe archive path')
            workbook = _xml(archive, 'xl/workbook.xml')
            relationships = _relationships(archive, 'xl/workbook.xml')
            shared = []
            if 'xl/sharedStrings.xml' in names:
                for node in _iter_xml(archive, 'xl/sharedStrings.xml', 'si'):
                    if len(shared) >= result.limits.max_shared_strings:
                        raise ExtractionLimit('shared_string_limit')
                    value = ''.join(item.text or '' for item in node.iter(NS + 't'))
                    if len(value) > result.limits.max_text_chars:
                        raise ExtractionLimit('cell_text_limit')
                    shared.append(value)
            formats, style_ids = {}, []
            if 'xl/styles.xml' in names:
                styles = _xml(archive, 'xl/styles.xml')
                formats = {item.get('numFmtId'): item.get('formatCode')
                           for item in styles.findall(NS + 'numFmts/' + NS + 'numFmt')}
                style_ids = [item.get('numFmtId', '0')
                             for item in styles.findall(NS + 'cellXfs/' + NS + 'xf')]
            props = workbook.find(NS + 'workbookPr')
            epoch = '1904' if props is not None and props.get('date1904') in ('1', 'true') else '1900'
            parser['settings'] = {'date_epoch': epoch, 'numeric_conversion': 'NONE', 'formula_evaluation': 'NONE'}
            non_cell_parts = [name for name in names if name.startswith(('xl/media/', 'xl/charts/'))]
            if non_cell_parts:
                result.report('non_cell_content_unparsed', 'Embedded images and charts remain in the original workbook; this extraction covers stored cells.',
                              details={'part_count': len(non_cell_parts)})
            if any(name.startswith('xl/externalLinks/') for name in names):
                result.report('external_links_not_resolved', 'External workbook links were preserved but not fetched.')
            for sheet in workbook.findall(NS + 'sheets/' + NS + 'sheet'):
                if sheets_seen >= result.limits.max_sheets:
                    raise ExtractionLimit('sheet_limit')
                sheets_seen += 1
                title = sheet.get('name', 'Sheet ' + str(sheets_seen))
                part = relationships.get(sheet.get(REL + 'id'))
                if not part or part not in names:
                    result.report('worksheet_missing', 'Worksheet relationship is unavailable.', 'error',
                                  details={'sheet': title})
                    continue
                if not part.startswith('xl/worksheets/'):
                    result.report('non_worksheet_sheet', 'This workbook sheet is not a cell worksheet.',
                                  details={'sheet': title, 'part': part})
                    continue
                # Declared Excel tables preserve intentional ranges; remaining cells form grids.
                regions = []
                for target in _relationships(archive, part).values():
                    if target.startswith('xl/tables/') and target in names:
                        declared = _xml(archive, target)
                        bounds = _range(declared.get('ref', ''))
                        label = declared.get('displayName') or declared.get('name') or title
                        regions.append((bounds, result.table(label, [part, target], sheet=title,
                                        declared_range=declared.get('ref'), header_consumed=False)))
                fallback, previous_row, last_row, formula_missing = None, 0, 0, 0
                merged_ranges, formula_caches = [], 0
                # Read merge metadata independently without retaining the entire worksheet tree.
                with archive.open(part) as stream:
                    for _, node in ET.iterparse(_SafeXML(stream), events=('end',)):
                        if node.tag == NS + 'mergeCell':
                            merged_ranges.append(node.get('ref'))
                        node.clear()
                for row_node in _iter_xml(archive, part, 'row'):
                    row_number = int(row_node.get('r', last_row + 1))
                    if row_number <= last_row:
                        raise ValueError('Non-monotonic worksheet rows')
                    last_row = row_number
                    cells = {}
                    for cell in row_node.findall(NS + 'c'):
                        ref = cell.get('r')
                        if not ref:
                            raise ValueError('Cell is missing its coordinate')
                        actual_row, column = _coordinate(ref)
                        if actual_row != row_number or column > 16384 or ref in cells:
                            raise ValueError('Invalid or duplicate worksheet coordinate')
                        kind = cell.get('t', 'n')
                        raw_node, formula = cell.find(NS + 'v'), cell.find(NS + 'f')
                        raw = raw_node.text if raw_node is not None else None
                        value = raw
                        if kind == 's' and raw is not None:
                            index = int(raw)
                            if index < 0 or index >= len(shared):
                                raise ValueError('Invalid shared string index')
                            value = shared[index]
                        elif kind == 'inlineStr':
                            value = ''.join(item.text or '' for item in cell.iter(NS + 't'))
                        if value is None and formula is None:
                            continue  # Style-only cells contain no source values.
                        metadata = {'type': kind}
                        if raw is not None and kind == 's':
                            metadata['shared_string_index'] = raw
                        if 's' in cell.attrib:
                            style = int(cell.get('s'))
                            if style < 0 or style >= len(style_ids):
                                raise ValueError('Invalid cell style')
                            format_id = style_ids[style]
                            metadata.update({'style_index': style, 'number_format_id': format_id,
                                             'number_format': formats.get(format_id)})
                        if formula is not None:
                            metadata['formula'] = {'expression': formula.text, 'attributes': dict(formula.attrib),
                                                   'cached_value': raw, 'cache_verified': False}
                            formula_missing += raw is None
                            formula_caches += raw is not None
                        if kind == 'e':
                            result.report('spreadsheet_error', 'Worksheet cell contains an Excel error value.',
                                          'error', row_id=title + ':' + str(row_number), column_key='c' + str(column),
                                          details={'sheet': title, 'cell': ref, 'value': value})
                        cells[ref] = (column, value, metadata)
                    if not cells:
                        result.empty_rows += 1
                        continue
                    grouped = {}
                    for ref, entry in cells.items():
                        column, _, _ = entry
                        matches = [table for (r1, c1, r2, c2), table in regions
                                   if r1 <= row_number <= r2 and c1 <= column <= c2]
                        if len(matches) > 1:
                            raise ValueError('Overlapping declared worksheet tables')
                        if matches:
                            table = matches[0]
                        else:
                            if fallback is None or row_number > previous_row + 1:
                                fallback = result.table(title + ' · row ' + str(row_number),
                                    [part, 'grid', row_number], sheet=title, start_row=row_number,
                                    hidden=sheet.get('state', 'visible') != 'visible',
                                    merged_ranges=merged_ranges, header_consumed=False)
                            table = fallback
                            previous_row = row_number
                        grouped.setdefault(table['table_id'], (table, {}))[1][ref] = entry
                    for table, values in grouped.values():
                        row = {'row_id': title + ':' + str(row_number), 'values': {}, 'locators': {},
                               'metadata': {'source_row': row_number, 'hidden': row_node.get('hidden') == '1',
                                            'cells': {}}}
                        for ref, (column, value, metadata) in values.items():
                            key = 'c' + str(column)
                            row['values'][key] = value
                            row['locators'][key] = {'kind': 'xlsx', 'sheet': title, 'cell': ref}
                            row['metadata']['cells'][key] = metadata
                        result.append(table, row, {'c' + str(column): _column(column)
                                                  for column, _, _ in values.values()})
                if merged_ranges:
                    result.report('merged_cells', 'Merged ranges retain only their actual stored cells; no values were filled.',
                                  details={'sheet': title, 'ranges': merged_ranges})
                if formula_missing:
                    result.report('formula_cache_missing', 'Formula cells lack cached results; values remain unresolved.',
                                  'error', details={'sheet': title, 'count': formula_missing})
                if formula_caches:
                    result.report('formula_cache_unverified', 'Formula caches are preserved but not recalculated or verified.',
                                  details={'sheet': title, 'count': formula_caches})
            if not result.tables:
                result.report('no_tabular_content', 'No stored worksheet values were found.', 'warning')
    except ExtractionLimit as exc:
        result.report(str(exc), 'Extraction limit reached; retained data is incomplete.', 'error')
    except (zipfile.BadZipFile, KeyError, ValueError, ET.ParseError, OSError, RuntimeError, OverflowError):
        result.report('malformed_workbook', 'Workbook structure could not be read safely; retained data is incomplete.', 'error')
    return result.finish(parser, sheets_seen=sheets_seen)


def extract_source(content: bytes, *, filename: str, media_type: str, source_id: str,
                   document_version_id: str, pdf_provider=None, scope=None,
                   limits: ExtractionLimits | None = None) -> dict:
    """Return draft tables, machine findings, parser provenance and honest coverage.

    Optional trusted limits configure resource budgets; source content cannot change
    them. PDF providers use the existing parse/parse_pdf protocol and scoped policy.
    """
    limits = limits or ExtractionLimits()
    result = _Result(source_id, document_version_id, limits)
    if not isinstance(content, bytes):
        raise TypeError('Source bytes are required')
    if len(content) > limits.max_source_bytes:
        result.report('source_size_limit', 'Source exceeds configured extraction byte limit.', 'error')
        return result.finish({'name': 'unselected', 'version': 'v1', 'mode': 'NATIVE'})
    media_type = media_type.partition(';')[0].strip().lower()
    suffix = PurePosixPath(filename).suffix.lower()
    if content.startswith(b'%PDF-') or suffix == '.pdf' or media_type == 'application/pdf':
        from closegraph.collections.pdf import extract_pdf
        return extract_pdf(content, result=result, provider=pdf_provider, scope=scope)
    if suffix == '.xlsx' or media_type == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':
        return _xlsx(content, result)
    if suffix in ('.csv', '.tsv', '.txt') or media_type in ('text/csv', 'text/tab-separated-values', 'text/plain'):
        return _csv(content, result, filename)
    result.report('unsupported_format', 'Supported draft extraction formats are PDF, CSV, TSV and XLSX.', 'error')
    return result.finish({'name': 'unselected', 'version': 'v1', 'mode': 'NATIVE'})
