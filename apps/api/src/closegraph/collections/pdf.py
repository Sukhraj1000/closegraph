"""Reducto draft tables and text with the provider's actual citation precision.

The exact response is retained as base64 for immutable storage by the collection
service. HTML is parsed as data, never rendered; links and scripts are not fetched.
Table-level boxes remain table-level for every parsed cell. Missing citations are
visible errors rather than guessed coordinates or silently discarded content.
"""
from __future__ import annotations

import base64
import json
import re
from hashlib import sha256
from html.parser import HTMLParser

from closegraph.contracts import PdfLocator
from closegraph.extractors.reducto import ADAPTER_VERSION, MAX_BLOCKS, MAX_RESPONSE_BYTES
from closegraph.collections.extract import ExtractionLimit


class _HTMLTable(HTMLParser):
    def __init__(self, limits):
        super().__init__(convert_charrefs=True)
        self.limits, self.rows, self.row, self.cell = limits, [], None, None
        self.spans, self.reserved, self.depth = [], {}, 0
        self.column = 0
        self.inert = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.inert += 1
            return
        if self.inert:
            return
        if tag == 'table':
            self.depth += 1
            if self.depth > 1:
                raise ValueError('Nested table requires manual review')
        elif tag == 'tr':
            if self.row is not None:
                raise ValueError('Unclosed table row')
            self.row, self.column = {}, 0
        elif tag in ('td', 'th'):
            if self.row is None or self.cell is not None:
                raise ValueError('Cell outside row or nested cell')
            attributes = dict(attrs)
            colspan = int(attributes.get('colspan') or '1')
            rowspan = int(attributes.get('rowspan') or '1')
            if not 1 <= colspan <= self.limits.max_columns or not 1 <= rowspan <= self.limits.max_rows:
                raise ExtractionLimit('pdf_table_span_limit')
            while self.reserved.get(self.column, 0) > len(self.rows):
                self.column += 1
            if self.column + colspan > self.limits.max_columns:
                raise ExtractionLimit('column_limit')
            if any(self.reserved.get(c, 0) > len(self.rows) for c in range(self.column, self.column + colspan)):
                raise ValueError('Overlapping table spans')
            self.cell = {'text': [], 'column': self.column, 'colspan': colspan,
                         'rowspan': rowspan, 'header': tag == 'th'}
        elif tag == 'br' and self.cell is not None:
            self.cell['text'].append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.inert = max(0, self.inert - 1)
            return
        if self.inert:
            return
        if tag in ('td', 'th') and self.cell is not None:
            cell = self.cell
            text = ''.join(cell['text'])
            if len(text) > self.limits.max_text_chars:
                raise ExtractionLimit('cell_text_limit')
            self.row[cell['column']] = text
            if cell['rowspan'] > 1 or cell['colspan'] > 1:
                self.spans.append({'row': len(self.rows) + 1, 'column': cell['column'] + 1,
                                   'rowspan': cell['rowspan'], 'colspan': cell['colspan']})
            for column in range(cell['column'], cell['column'] + cell['colspan']):
                self.reserved[column] = len(self.rows) + cell['rowspan']
            self.column += cell['colspan']
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            if self.cell is not None:
                raise ValueError('Unclosed table cell')
            if len(self.rows) >= self.limits.max_rows:
                raise ExtractionLimit('row_limit')
            self.rows.append(self.row)
            self.row = None
        elif tag == 'table':
            self.depth -= 1

    def handle_data(self, data):
        if self.cell is not None and not self.inert:
            self.cell['text'].append(data)


def _markdown_line(line):
    # Escaped separators remain literal content; whitespace is formatting in Markdown.
    pieces = re.split(r'(?<!\\)\|', line.strip())
    if pieces and not pieces[0].strip():
        pieces.pop(0)
    if pieces and not pieces[-1].strip():
        pieces.pop()
    return [piece.strip().replace(r'\|', '|') for piece in pieces]


def _table_rows(content, limits):
    if re.search(r'<table(?:\s|>)', content, re.I):
        parser = _HTMLTable(limits)
        parser.feed(content)
        parser.close()
        if parser.depth or parser.row is not None or parser.cell is not None or not parser.rows:
            raise ValueError('Incomplete HTML table')
        return parser.rows, {'format': 'html', 'spans': parser.spans}
    lines = content.splitlines()
    if len(lines) >= 2 and '|' in lines[0]:
        separator = _markdown_line(lines[1])
        if separator and all(re.fullmatch(r':?-{3,}:?', value) for value in separator):
            rows = []
            for number, line in enumerate(lines):
                if number == 1 or not line.strip():
                    continue
                values = _markdown_line(line)
                if len(values) > limits.max_columns or len(rows) >= limits.max_rows:
                    raise ExtractionLimit('pdf_table_limit')
                rows.append(dict(enumerate(values)))
            return rows, {'format': 'markdown', 'formatting_separator_line': 2}
    return None, {}


def _locator(block):
    box = block.get('bbox')
    if not isinstance(box, dict):
        return None
    try:
        coords = [box[name] for name in ('left', 'top', 'width', 'height')]
        if any(type(value) not in (int, float) for value in coords):
            return None
        left, top, width, height = coords
        locator = PdfLocator(original_page=box['original_page'], processed_page=box['page'],
                             coordinate_system='normalised-0-1',
                             bbox=(left, top, left + width, top + height))
        return {**locator.model_dump(mode='json'), 'citation_precision': 'block'}
    except (KeyError, ValueError, TypeError, OverflowError):
        return None


def extract_pdf(content, *, result, provider, scope):
    parser = {'name': 'reducto', 'version': ADAPTER_VERSION, 'mode': 'UNAVAILABLE'}
    if not content.startswith(b'%PDF-'):
        result.report('unsupported_pdf_signature', 'The source does not have a PDF signature.', 'error')
        return result.finish(parser)
    if provider is None:
        result.report('provider_unavailable', 'Configure a live Reducto provider to extract this PDF.', 'error')
        return result.finish(parser)
    try:
        method = getattr(provider, 'parse', None) or getattr(provider, 'parse_pdf', None)
        if method is None:
            raise ValueError('Unsupported PDF provider')
        response = method(content, scope=scope, document_version_id=result.document_version_id)
    except Exception:
        # Never surface provider exception bodies containing request credentials or URLs.
        result.report('provider_failure', 'PDF provider failed; original source is retained for retry.', 'error')
        return result.finish(parser)
    if response.source_hash != sha256(content).hexdigest():
        result.report('provider_source_mismatch', 'Provider result does not belong to this source.', 'error')
        return result.finish(parser)
    parser.update({'mode': response.mode, 'availability': response.availability,
                   'response_id': response.response_id, 'response_sha256': response.response_hash,
                   'settings': response.request_settings, 'confidence_is_calibrated': False})
    raw = response.raw_response
    if raw is not None:
        if len(raw) > MAX_RESPONSE_BYTES or sha256(raw).hexdigest() != response.response_hash:
            result.report('provider_response_mismatch', 'PDF response integrity or byte limit failed.', 'error')
            return result.finish(parser)
        parser['raw_response_base64'] = base64.b64encode(raw).decode('ascii')
    if response.upload_response is not None:
        parser['upload_response_base64'] = base64.b64encode(response.upload_response).decode('ascii')
    for reason in response.diagnostics:
        result.report('provider_diagnostic', 'PDF provider reported incomplete extraction.', 'error',
                      details={'diagnostic': str(reason)})
    if not response.available and not response.diagnostics:
        result.report('provider_unavailable', 'PDF provider is unavailable; no passing fallback is substituted.', 'error')
    if raw is None:
        if response.available:
            result.report('provider_response_missing', 'Exact provider response is unavailable.', 'error')
        return result.finish(parser)
    try:
        payload = json.loads(raw)
        parsed = payload['result']
        if parsed.get('type') != 'full':
            raise ValueError('External result references are not fetched')
        chunks = parsed['chunks']
        if not isinstance(chunks, list):
            raise ValueError('Chunks must be a list')
        blocks = [block for chunk in chunks for block in chunk['blocks']]
        if not blocks or len(blocks) > MAX_BLOCKS:
            raise ValueError('Block count outside limits')
        parser['provider_model_version'] = payload.get('model_version')
    except (KeyError, ValueError, TypeError, AttributeError):
        result.report('malformed_pdf_response', 'Provider response does not contain bounded inline document blocks.', 'error')
        return result.finish(parser)
    parsed_blocks = 0
    try:
        for index, block in enumerate(blocks):
            if not isinstance(block, dict) or not isinstance(block.get('content'), str):
                result.report('pdf_block_content_missing', 'A provider block has no readable text.', 'error',
                              details={'block_index': index})
                continue
            text = block['content']
            if len(text) > result.limits.max_text_chars:
                raise ExtractionLimit('pdf_block_text_limit')
            locator = _locator(block)
            table = result.table('PDF block ' + str(index + 1), ['pdf', index],
                                 provider_block_index=index, provider_block_type=block.get('type'),
                                 provider_confidence=block.get('confidence'),
                                 provider_granular_confidence=block.get('granular_confidence'),
                                 raw_content=text, header_consumed=False,
                                 citation_precision='block' if locator else 'unavailable')
            if locator is None:
                result.report('pdf_citation_missing', 'Block content is retained without a valid source box; inspect the original.',
                              'error', table_id=table['table_id'], details={'block_index': index})
            try:
                rows, metadata = _table_rows(text, result.limits)
            except (ValueError, ExtractionLimit):
                rows, metadata = None, {}
                result.report('pdf_table_unresolved', 'Table structure could not be resolved; exact block text is retained.',
                              table_id=table['table_id'])
            table['metadata'].update(metadata)
            if rows is None:
                rows = [{0: text}]
                table['metadata']['structure'] = 'text_block'
            else:
                table['metadata']['structure'] = 'table'
            for number, values in enumerate(rows, 1):
                row = {'row_id': 'pdf:b' + str(index) + ':r' + str(number),
                       'values': {'c' + str(column + 1): value for column, value in values.items()},
                       'locators': {'c' + str(column + 1): dict(locator) for column in values} if locator else {},
                       'metadata': {'provider_block_index': index, 'parsed_row': number}}
                result.append(table, row, {'c' + str(column + 1): 'Column ' + str(column + 1) for column in values})
            parsed_blocks += 1
    except ExtractionLimit as exc:
        result.report(str(exc), 'PDF extraction limit reached; retained blocks are incomplete.', 'error')
    result.report('pdf_extraction_requires_review', 'Provider extraction is a draft; inspect all relevant rows before acceptance.',
                  'info', details={'confidence_is_proof': False})
    return result.finish(parser, provider_blocks=len(blocks), extracted_blocks=parsed_blocks,
                         expected_document_rows=None, row_completeness='UNVERIFIED')
