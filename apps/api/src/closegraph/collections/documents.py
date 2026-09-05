"""Logical source revisions and bounded, deterministic native-file comparisons.

State helpers have no I/O. They update the supplied working state, leaving immutable
collection history and source bytes to the service. add_source_revision appends its
source itself. Existing source/revision IDs remain stable. No filename establishes
revision membership, sheet equivalence, row identity, or accounting meaning.

compare_sources(..., business_keys={"Sheet": {"columns": ["A", "C"],
"header_row": 1}}) aligns only explicit unique keys. CSV uses sheet "csv" and accepts
c1/c2 keys or Excel column letters. Omitted keys compare original positions. Results
contain bounded changes/ambiguities plus complete scan counts when feasible; a
truncated change list or unresolved alignment never claims a complete comparison.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
import re
from xml.etree import ElementTree as ET
import zipfile

from .extract import (ExtractionLimit, ExtractionLimits, NS, REL, _SafeXML, _coordinate,
                      _relationships, _xml, _iter_xml, _column, extract_source, identifier)

XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
CSV = 'text/csv'


def _text(value, name, maximum=256, *, optional=False):
    if optional and value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(name + ' must be nonempty bounded text')
    return value


def initialize_documents(state: dict) -> dict:
    """Add deterministic one-document-per-source mappings for legacy collections.

    Idempotent; adds metadata only. Existing history entries are never rewritten.
    An inconsistent existing revision graph fails rather than selecting a head.
    """
    sources = state.setdefault('sources', [])
    documents = state.setdefault('documents', [])
    by_source = {source['id']: source for source in sources}
    if len(by_source) != len(sources):
        raise ValueError('Duplicate immutable source revision ID')
    by_document = {document['id']: document for document in documents}
    if len(by_document) != len(documents):
        raise ValueError('Duplicate logical document ID')
    uploaded = {event.get('detail', {}).get('source_id'): event.get('at') for event in state.get('history', [])
                if event.get('event') == 'source_uploaded' and event.get('at')}
    membership = {}
    for document in documents:
        revisions = document.get('revisions')
        if not isinstance(revisions, list) or not revisions or len(set(revisions)) != len(revisions):
            raise ValueError('Logical document requires distinct source revisions')
        if document.get('current_revision_id') != revisions[-1]:
            raise ValueError('Current revision must be the last immutable document revision')
        for position, revision_id in enumerate(revisions):
            if revision_id not in by_source or revision_id in membership:
                raise ValueError('Source revision membership is missing or ambiguous')
            source = by_source[revision_id]
            if source.get('document_id') not in (None, document['id']):
                raise ValueError('Source revision belongs to a different document')
            expected_parent = revisions[position - 1] if position else None
            if 'parent_revision_id' in source and source['parent_revision_id'] != expected_parent:
                raise ValueError('Source revision parent does not match the revision chain')
            source.setdefault('document_id', document['id'])
            source.setdefault('revision_id', source['id'])
            source.setdefault('parent_revision_id', expected_parent)
            source.setdefault('period', document.get('period'))
            source.setdefault('uploaded_at', source.get('created_at') or uploaded.get(source['id']))
            source.setdefault('reason', 'Imported existing source' if not position else 'Existing revision')
            source.setdefault('parser_provenance', deepcopy(source.get('parser', {})))
            membership[revision_id] = document['id']
    for source in sources:
        if source['id'] in membership:
            continue
        if source.get('document_id') is not None:
            raise ValueError('Source declares a document without revision membership')
        identity = 'document-' + identifier('source-document', source['id'])
        if identity in by_document:
            raise ValueError('Logical document identifier collision')
        document = {'id': identity, 'title': source.get('filename') or source['id'],
                    'period': source.get('period'), 'current_revision_id': source['id'],
                    'revisions': [source['id']]}
        documents.append(document)
        by_document[identity] = document
        source.update(document_id=identity, revision_id=source['id'], parent_revision_id=None)
        source.setdefault('uploaded_at', source.get('created_at') or uploaded.get(source['id']))
        source.setdefault('reason', 'Imported existing source')
        source.setdefault('period', document['period'])
        source.setdefault('parser_provenance', deepcopy(source.get('parser', {})))
    return state


def add_source_revision(state: dict, source: dict, *, document_id=None,
                        parent_revision_id=None, reason: str, period=None, actor: str) -> dict:
    """Append a new immutable source and advance one explicitly chosen logical head.

    The service serializes this with its expected collection version. An existing
    document requires its current parent ID, preventing accidental forks. Period
    and media type remain consistent within a document. The input source dict is
    copied so caller-owned metadata is not changed.
    """
    _text(reason, 'Revision reason', 2000)
    _text(actor, 'Actor')
    _text(source.get('id'), 'Source ID', 64)
    _text(source.get('filename'), 'Filename')
    _text(source.get('media_type'), 'Media type')
    _text(period, 'Period', optional=True)
    initialize_documents(state)
    if any(existing['id'] == source['id'] for existing in state['sources']):
        raise ValueError('Source revision ID already exists')
    incoming = deepcopy(source)
    if document_id is None:
        if parent_revision_id is not None:
            raise ValueError('A parent revision requires an explicit logical document')
        document = {'id': 'document-' + identifier('source-document', source['id']),
                    'title': source['filename'], 'period': period,
                    'current_revision_id': source['id'], 'revisions': []}
        if any(existing['id'] == document['id'] for existing in state['documents']):
            raise ValueError('Logical document identifier collision')
    else:
        document = next((item for item in state['documents'] if item['id'] == document_id), None)
        if document is None:
            raise ValueError('Unknown logical document')
        if parent_revision_id != document['current_revision_id']:
            raise ValueError('Revision parent is stale; refresh the current document revision')
        parent = next(item for item in state['sources'] if item['id'] == parent_revision_id)
        if parent['media_type'] != incoming['media_type']:
            raise ValueError('Different file formats require separate logical documents')
        if period is not None and period != document.get('period'):
            raise ValueError('Different reporting periods require separate logical documents')
        period = document.get('period')
    incoming.update(document_id=document['id'], revision_id=source['id'],
                    parent_revision_id=parent_revision_id, uploaded_at=datetime.now(timezone.utc).isoformat(),
                    uploaded_by=actor, reason=reason, period=period,
                    parser_provenance=deepcopy(source.get('parser', {})))
    if document_id is None:
        state['documents'].append(document)
    state['sources'].append(incoming)
    document['revisions'].append(incoming['id'])
    document['current_revision_id'] = incoming['id']
    return incoming


def current_sources(state: dict) -> list[dict]:
    initialize_documents(state)
    by_id = {source['id']: source for source in state['sources']}
    return [by_id[document['current_revision_id']] for document in state['documents']]


def document_fingerprint(state: dict, *, dataset_hashes=None, recipe=None) -> str:
    """Explicit current revision/hash dependencies; no inferred financial links."""
    active = current_sources(state)
    payload = {'documents': sorted((source['document_id'], source['id'], source.get('content_hash'))
                                    for source in active),
               'datasets': dataset_hashes or {}, 'recipe': recipe}
    return sha256(_bytes(payload)).hexdigest()


def output_dependency_ids(state: dict) -> dict:
    """Return the complete explicitly declared output/check source dependency set.

    Unresolvable, stale, ambiguous or unsupported references make known=False.
    Include every executed recipe step/check, selected output, export template and
    requirement binding. An unknown graph must never preserve a prior approval.
    """
    reasons, source_ids, document_ids = [], set(), set()
    try:
        active = current_sources(state)
    except (KeyError, TypeError, ValueError) as exc:
        return {'known': False, 'source_ids': [], 'document_ids': [],
                'reasons': ['Invalid document graph: ' + str(exc)]}
    active_by_id = {source['id']: source for source in active}
    documents = {document['id']: document for document in state['documents']}
    datasets = [dataset for dataset in state.get('datasets', []) if dataset.get('kind') == 'extraction']
    references = defaultdict(list)
    for dataset in datasets:
        for name in set(filter(None, (dataset.get('id'), dataset.get('table_id')))):
            references[name].append(dataset)

    def add_source(source_id):
        if not isinstance(source_id, str) or source_id not in active_by_id:
            reasons.append('Missing or stale source revision: ' + str(source_id))
            return
        source_ids.add(source_id)
        document_ids.add(active_by_id[source_id]['document_id'])

    def add_document(document_id):
        document = documents.get(document_id) if isinstance(document_id, str) else None
        if document is None:
            reasons.append('Unknown required logical document: ' + str(document_id))
            return
        add_source(document['current_revision_id'])

    resolved = {}
    def resolve(reference, available_steps):
        if not isinstance(reference, str):
            reasons.append('Dataset/step reference must be an explicit ID')
            return set()
        if reference in available_steps:
            return set(available_steps[reference])
        matches = references.get(reference, [])
        if len(matches) != 1:
            reasons.append('Unknown or ambiguous dataset/step: ' + reference)
            return set()
        source_id = matches[0].get('source_id')
        add_source(source_id)
        return {source_id} if source_id in active_by_id else set()

    recipe = state.get('recipe')
    if not isinstance(recipe, dict) or recipe.get('version') != 1 or not isinstance(recipe.get('steps'), list):
        reasons.append('No supported explicit recipe')
    else:
        operations = {'select', 'filter', 'rename', 'derive', 'sort', 'join', 'lookup',
                      'aggregate', 'classify', 'allocate', 'reshape'}
        for step in recipe['steps']:
            if not isinstance(step, dict) or step.get('op') not in operations:
                reasons.append('Unsupported recipe operation or step')
                continue
            identity = step.get('id')
            if not isinstance(identity, str) or not identity or identity in resolved or identity in references:
                reasons.append('Missing or conflicting recipe step ID')
                continue
            dependencies = resolve(step.get('input', step.get('left')), resolved)
            if 'left' in step and 'input' in step:
                dependencies |= resolve(step['left'], resolved)
            if step['op'] in ('join', 'lookup') or 'right' in step:
                dependencies |= resolve(step.get('right'), resolved)
            resolved[identity] = dependencies
        resolve(recipe.get('output'), resolved)
        checks = recipe.get('checks', [])
        if not isinstance(checks, list):
            reasons.append('Invalid recipe check dependencies')
        else:
            for check in checks:
                if not isinstance(check, dict):
                    reasons.append('Invalid recipe check')
                else:
                    resolve(check.get('table', recipe.get('output')), resolved)
        export = recipe.get('export', {})
        if not isinstance(export, dict):
            reasons.append('Invalid export dependency configuration')
        elif export.get('template_source_id') is not None:
            add_source(export['template_source_id'])
    requirements = state.get('requirements', [])
    if not isinstance(requirements, list):
        reasons.append('Invalid requirement dependency list')
        requirements = []
    for requirement in requirements:
        if not isinstance(requirement, dict):
            reasons.append('Invalid requirement')
            continue
        bound = requirement.get('document_ids', [])
        if not isinstance(bound, list) or not bound or any(not isinstance(identity, str) for identity in bound):
            reasons.append('Requirement has no explicit logical-document bindings')
            continue
        for identity in bound:
            add_document(identity)
        selector = requirement.get('dataset_selector')
        if selector is None and requirement.get('table_title') is not None:
            selector = {'document_id': bound[0] if len(bound) == 1 else None,
                        'table_title': requirement['table_title']}
        if selector is not None:
            if not isinstance(selector, dict) or selector.get('document_id') not in bound:
                reasons.append('Requirement selector is outside its explicit document bindings')
            else:
                document = documents.get(selector['document_id'])
                matches = [dataset for dataset in datasets if document
                           and dataset.get('source_id') == document['current_revision_id']
                           and dataset.get('title') == selector.get('table_title')]
                if not isinstance(selector.get('table_title'), str) or len(matches) != 1:
                    reasons.append('Requirement selector is missing or ambiguous')
                else:
                    add_source(matches[0]['source_id'])
        if requirement.get('dataset_id') is not None:
            identity = requirement['dataset_id']
            matches = references.get(identity, []) if isinstance(identity, str) else []
            if len(matches) != 1 or not any(documents.get(identity, {}).get('current_revision_id') == matches[0].get('source_id') for identity in bound):
                reasons.append('Requirement dataset is missing, stale or outside its documents')
            else:
                add_source(matches[0]['source_id'])
    return {'known': not reasons, 'source_ids': sorted(source_ids),
            'document_ids': sorted(document_ids), 'reasons': sorted(set(reasons))}


def _bytes(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                      allow_nan=False).encode()


def _node(element):
    return {'tag': element.tag.rsplit('}', 1)[-1], 'attributes': dict(sorted(element.attrib.items())),
            'text': element.text if element.text and element.text.strip() else None,
            'children': [_node(child) for child in element]}


def _digest(value):
    return sha256(_bytes(value)).hexdigest()


@dataclass(frozen=True)
class ComparisonLimits:
    max_changes: int = 100_000
    max_ambiguities: int = 2_000
    max_business_key_rows: int = 250_000
    max_change_bytes: int = 32 * 1024 * 1024
    max_ambiguity_bytes: int = 4 * 1024 * 1024

    def __post_init__(self):
        if any(type(value) is not int or value <= 0 for value in asdict(self).values()):
            raise ValueError('Comparison limits must be positive integers')


class _Comparison:
    def __init__(self, before, after, media_type, limits):
        self.before_hash, self.after_hash = sha256(before).hexdigest(), sha256(after).hexdigest()
        self.media_type, self.limits = media_type, limits
        self.changes, self.ambiguities = [], []
        self.kinds, self.fields = Counter(), Counter()
        self.ambiguity_count, self.scanned_before, self.scanned_after = 0, 0, 0
        self.scan_complete = True
        self.alignment = {}
        self.change_bytes = self.ambiguity_bytes = 0
        self.change_details_full = self.ambiguity_details_full = False

    def change(self, kind, *, sheet=None, before=None, after=None, before_locator=None,
               after_locator=None, fields=(), business_key=None):
        self.kinds[kind] += 1
        self.fields.update(fields)
        if self.change_details_full or len(self.changes) >= self.limits.max_changes:
            return
        change = {'id': identifier(self.before_hash, self.after_hash, kind, sheet,
                                    before_locator, after_locator, sum(self.kinds.values())),
                  'kind': kind, 'sheet': sheet, 'before_locator': before_locator,
                  'after_locator': after_locator, 'before': deepcopy(before), 'after': deepcopy(after),
                  'fields': list(fields)}
        if business_key is not None:
            change['business_key'] = list(business_key)
        size = len(_bytes(change))
        if self.change_bytes + size > self.limits.max_change_bytes:
            self.change_details_full = True
            return
        self.change_bytes += size
        self.changes.append(change)

    def ambiguity(self, code, message, *, sheet=None, side=None, **detail):
        self.ambiguity_count += 1
        if not self.ambiguity_details_full and len(self.ambiguities) < self.limits.max_ambiguities:
            item = {'id': identifier(self.before_hash, self.after_hash, code,
                                                       self.ambiguity_count),
                                     'code': code, 'message': message, 'sheet': sheet,
                                     'side': side, **detail}
            size = len(_bytes(item))
            if self.ambiguity_bytes + size > self.limits.max_ambiguity_bytes:
                self.ambiguity_details_full = True
                return
            self.ambiguity_bytes += size
            self.ambiguities.append(item)

    def finish(self, **extra):
        change_count = sum(self.kinds.values())
        changes_complete = len(self.changes) == change_count
        return {'version': 1, 'before_sha256': self.before_hash, 'after_sha256': self.after_hash,
                'media_type': self.media_type, 'summary': {
                    'identical_bytes': self.before_hash == self.after_hash,
                    'change_count': change_count, 'by_kind': dict(self.kinds),
                    'by_field': dict(self.fields), 'ambiguity_count': self.ambiguity_count,
                    'before_cells_scanned': self.scanned_before,
                    'after_cells_scanned': self.scanned_after,
                    'alignment': self.alignment, **extra},
                'changes': self.changes, 'ambiguities': self.ambiguities,
                'coverage': {'complete': self.scan_complete and changes_complete and not self.ambiguity_count,
                             'source_scan_complete': self.scan_complete,
                             'changes_complete': changes_complete,
                             'ambiguities_complete': len(self.ambiguities) == self.ambiguity_count,
                             'limits': asdict(self.limits),
                             'interpretation': 'Raw source comparison; no financial treatment inferred'}}


class _Workbook:
    def __init__(self, content, limits):
        if len(content) > limits.max_source_bytes:
            raise ExtractionLimit('source_size_limit')
        self.limits = limits
        self.archive = zipfile.ZipFile(io.BytesIO(content))
        self.sheets, self.layout, self.shared, self.styles = {}, {}, [], []
        self.rows_seen = self.cells_seen = 0
        entries = self.archive.infolist()
        names = [entry.filename for entry in entries]
        if len(entries) > limits.max_zip_members or len(set(names)) != len(names):
            raise ExtractionLimit('archive_member_limit_or_duplicate')
        if sum(entry.file_size for entry in entries) > limits.max_uncompressed_bytes:
            raise ExtractionLimit('uncompressed_limit')
        if any(entry.file_size > limits.max_member_bytes or entry.flag_bits & 1 for entry in entries):
            raise ExtractionLimit('member_limit_or_encrypted')
        if any(name.startswith('/') or '..' in name.split('/') or '\\' in name for name in names):
            raise ValueError('Unsafe archive path')
        self.names = set(names)
        workbook = _xml(self.archive, 'xl/workbook.xml')
        links = _relationships(self.archive, 'xl/workbook.xml')
        self.properties = [_node(child) for child in workbook if child.tag != NS + 'sheets']
        for sheet in workbook.findall(NS + 'sheets/' + NS + 'sheet'):
            title = sheet.get('name')
            if not title or title in self.sheets or len(self.sheets) >= limits.max_sheets:
                raise ValueError('Missing, duplicate or excessive worksheet names')
            part = links.get(sheet.get(REL + 'id'))
            if not part or part not in self.names or not part.startswith('xl/worksheets/'):
                raise ValueError('Missing or unsupported worksheet relationship')
            self.sheets[title] = {'part': part, 'state': sheet.get('state', 'visible')}
            self.layout[title] = []
        if not self.sheets:
            raise ValueError('No supported worksheets found')
        if 'xl/sharedStrings.xml' in self.names:
            for node in _iter_xml(self.archive, 'xl/sharedStrings.xml', 'si'):
                if len(self.shared) >= limits.max_shared_strings:
                    raise ExtractionLimit('shared_string_limit')
                # Rich text runs are content; phonetic annotations are not duplicated into it.
                value = ''.join(item.text or '' for item in node.findall(NS + 't') +
                                node.findall(NS + 'r/' + NS + 't'))
                if len(value) > limits.max_text_chars:
                    raise ExtractionLimit('cell_text_limit')
                self.shared.append(value)
        self.style_catalog = None
        if 'xl/styles.xml' in self.names:
            styles = _xml(self.archive, 'xl/styles.xml')
            self.style_catalog = _digest(_node(styles))
            formats = {node.get('numFmtId'): node.get('formatCode')
                       for node in styles.findall(NS + 'numFmts/' + NS + 'numFmt')}
            resources = {kind: [_node(child) for child in styles.find(NS + kind)]
                         if styles.find(NS + kind) is not None else []
                         for kind in ('fonts', 'fills', 'borders', 'cellStyleXfs')}
            for xf in styles.findall(NS + 'cellXfs/' + NS + 'xf'):
                semantic = _node(xf)
                attributes = semantic['attributes']
                for key, group in (('fontId', 'fonts'), ('fillId', 'fills'), ('borderId', 'borders'),
                                   ('xfId', 'cellStyleXfs')):
                    index = int(attributes.pop(key, '0'))
                    values = resources[group]
                    if index < 0 or index >= len(values) and index != 0:
                        raise ValueError('Invalid style resource reference')
                    semantic[group] = values[index] if index < len(values) else None
                format_id = attributes.pop('numFmtId', '0')
                number_format = formats.get(format_id, {'builtin_id': format_id})
                semantic['number_format'] = number_format
                self.styles.append({'fingerprint': _digest(semantic), 'number_format': number_format})
        if not self.styles:
            self.styles.append({'fingerprint': _digest({}), 'number_format': {'builtin_id': '0'}})

    def close(self):
        self.archive.close()

    def _cell(self, node, row_number):
        reference = node.get('r')
        actual_row, column = _coordinate(reference)
        if actual_row != row_number or column > 16384:
            raise ValueError('Invalid worksheet cell coordinate')
        kind = node.get('t', 'n')
        value_node, formula_node = node.find(NS + 'v'), node.find(NS + 'f')
        token = value_node.text if value_node is not None else None
        value = token
        if kind == 's' and token is not None:
            index = int(token)
            if index < 0 or index >= len(self.shared):
                raise ValueError('Invalid shared string reference')
            value = self.shared[index]
        elif kind == 'inlineStr':
            inline = node.find(NS + 'is')
            value = ''.join(item.text or '' for item in inline.findall(NS + 't') +
                            inline.findall(NS + 'r/' + NS + 't')) if inline is not None else ''
        if value is not None and len(value) > self.limits.max_text_chars:
            raise ExtractionLimit('cell_text_limit')
        style_id = int(node.get('s', '0'))
        if style_id < 0 or style_id >= len(self.styles):
            raise ValueError('Invalid cell style reference')
        formula = {'text': formula_node.text, 'attributes': dict(formula_node.attrib)} if formula_node is not None else None
        # Canonical string category avoids false content changes when a writer switches
        # from shared strings to inline strings. Exact source tokens remain available.
        category = 'text' if kind in ('s', 'inlineStr', 'str') else kind
        return column, {'value': value, 'value_type': category, 'formula': formula,
                        'cached_value': token if formula is not None else None,
                        'style': self.styles[style_id]}

    def rows(self, sheet):
        previous = 0
        part = self.sheets[sheet]['part']
        with self.archive.open(part) as stream:
            stack = []
            for event, node in ET.iterparse(_SafeXML(stream), events=('start', 'end')):
                if event == 'start':
                    stack.append(node)
                    continue
                if node.tag == NS + 'row':
                    row_number = int(node.get('r', previous + 1))
                    if row_number <= previous or row_number > 1048576:
                        raise ValueError('Invalid worksheet row sequence')
                    previous = row_number
                    self.rows_seen += 1
                    if self.rows_seen > self.limits.max_rows:
                        raise ExtractionLimit('row_limit')
                    cells = {}
                    for cell in node.findall(NS + 'c'):
                        self.cells_seen += 1
                        if self.cells_seen > self.limits.max_cells:
                            raise ExtractionLimit('cell_limit')
                        column, value = self._cell(cell, row_number)
                        if column in cells:
                            raise ValueError('Duplicate worksheet cell')
                        cells[column] = value
                    if len(cells) > self.limits.max_columns:
                        raise ExtractionLimit('column_limit')
                    attributes = {key: value for key, value in node.attrib.items() if key not in ('r', 'spans')}
                    yield row_number, cells, attributes
                    node.clear()
                    if len(stack) > 1:
                        stack[-2].clear()
                elif len(stack) == 2 and node.tag != NS + 'sheetData':
                    self.layout[sheet].append(_node(node))
                    node.clear()
                stack.pop()

    def other_parts(self):
        interpreted = {'xl/workbook.xml', 'xl/styles.xml', 'xl/sharedStrings.xml',
                       'xl/_rels/workbook.xml.rels'} | {sheet['part'] for sheet in self.sheets.values()}
        result = {}
        for name in sorted(self.names - interpreted):
            digest = sha256()
            with self.archive.open(name) as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
            result[name] = digest.hexdigest()
        return result


def _locator(media_type, sheet, row, column):
    if row is None:
        return None
    if media_type == CSV:
        return {'kind': 'csv', 'row': row, 'column': column}
    return {'kind': 'xlsx', 'sheet': sheet, 'cell': _column(column) + str(row)}


def _compare_row(result, sheet, before, after, key=None):
    br, bc, bp = before if before is not None else (None, {}, {})
    ar, ac, ap = after if after is not None else (None, {}, {})
    if br is not None and ar is not None and br != ar and key is not None:
        result.change('row_moved', sheet=sheet, before={'row': br}, after={'row': ar},
                      before_locator=_locator(result.media_type, sheet, br, 1),
                      after_locator=_locator(result.media_type, sheet, ar, 1),
                      fields=('position',), business_key=key)
    if bp != ap:
        result.change('row_properties_changed', sheet=sheet, before=bp, after=ap,
                      before_locator=_locator(result.media_type, sheet, br, 1),
                      after_locator=_locator(result.media_type, sheet, ar, 1), fields=('row_style',), business_key=key)
    for column in sorted(bc.keys() | ac.keys()):
        left, right = bc.get(column), ac.get(column)
        if left == right:
            continue
        fields = []
        for name in ('value', 'value_type', 'formula', 'cached_value', 'style'):
            if (left or {}).get(name) != (right or {}).get(name):
                if name == 'value' and (left or {}).get('formula') is not None and (right or {}).get('formula') is not None:
                    continue  # Formula result differences are labelled cached_value.
                fields.append(name)
        kind = 'cell_added' if left is None else 'cell_removed' if right is None else 'cell_changed'
        result.change(kind, sheet=sheet, before=left, after=right,
                      before_locator=_locator(result.media_type, sheet, br, column) if left is not None else None,
                      after_locator=_locator(result.media_type, sheet, ar, column) if right is not None else None,
                      fields=fields or ('presence',), business_key=key)


def _position_rows(result, sheet, before_rows, after_rows):
    left, right = iter(before_rows), iter(after_rows)
    a, b = next(left, None), next(right, None)
    while a is not None or b is not None:
        if b is None or a is not None and a[0] < b[0]:
            _compare_row(result, sheet, a, None)
            a = next(left, None)
        elif a is None or b[0] < a[0]:
            _compare_row(result, sheet, None, b)
            b = next(right, None)
        else:
            _compare_row(result, sheet, a, b)
            a, b = next(left, None), next(right, None)


def _key_config(value):
    if isinstance(value, list):
        value = {'columns': value}
    if not isinstance(value, dict) or set(value) - {'columns', 'header_row'}:
        raise ValueError('Business keys use columns and optional header_row')
    columns = value.get('columns')
    if not isinstance(columns, list) or not 1 <= len(columns) <= 16:
        raise ValueError('Business keys require 1..16 explicit columns')
    numbers = []
    for column in columns:
        if isinstance(column, str) and re.fullmatch(r'c[1-9][0-9]*', column):
            number = int(column[1:])
        elif isinstance(column, str) and re.fullmatch(r'[A-Z]{1,3}', column):
            _, number = _coordinate(column + '1')
        else:
            raise ValueError('Business-key columns use Excel letters or c1/c2 keys')
        if not 1 <= number <= 16384 or number in numbers:
            raise ValueError('Business-key columns must be distinct and in range')
        numbers.append(number)
    header = value.get('header_row')
    if header is not None and (type(header) is not int or not 1 <= header <= 1048576):
        raise ValueError('header_row must be an explicit positive source row')
    return numbers, header


def _keyed_rows(result, sheet, before_rows, after_rows, config):
    columns, header = _key_config(config)
    prefixes = []
    maps = []
    invalid = set()
    for side, rows in (('before', before_rows), ('after', after_rows)):
        mapping, prefix = {}, []
        for count, row in enumerate(rows, 1):
            if count > result.limits.max_business_key_rows:
                raise ExtractionLimit('business_key_row_limit')
            if header is not None and row[0] <= header:
                prefix.append(row)
                continue
            values = tuple(row[1].get(column, {}).get('value') for column in columns)
            if any(value is None or value == '' for value in values):
                result.ambiguity('missing_business_key', 'Row has an empty explicit key; no row match was guessed.',
                                 sheet=sheet, side=side, row=row[0], columns=[_column(c) for c in columns])
                continue
            key = tuple((row[1][column].get('value_type'), value) for column, value in zip(columns, values))
            if any(row[1][column].get('formula') is not None for column in columns):
                result.ambiguity('formula_business_key', 'Formula-based keys require explicit evaluated values before alignment.',
                                 sheet=sheet, side=side, row=row[0], key=list(values))
                invalid.add(key)
                continue
            if key in mapping:
                result.ambiguity('duplicate_business_key', 'Duplicate explicit key; matching rows remain ambiguous.',
                                 sheet=sheet, side=side, rows=[mapping[key][0], row[0]], key=list(values))
                invalid.add(key)
            else:
                mapping[key] = row
        prefixes.append(prefix)
        maps.append(mapping)
    _position_rows(result, sheet, prefixes[0], prefixes[1])
    left, right = maps
    for key in sorted(left.keys() | right.keys(), key=_bytes):
        if key in invalid:
            continue
        _compare_row(result, sheet, left.get(key), right.get(key), key=[value for _, value in key])


def _csv_rows(content, side, result, extraction_limits):
    extracted = extract_source(content, filename='source.csv', media_type=CSV,
                               source_id=side, document_version_id=side, limits=extraction_limits)
    for finding in extracted['issues']:
        if finding['code'] == 'header_candidate':
            continue
        result.ambiguity('csv_' + finding['code'], finding['message'], sheet='csv', side=side,
                         details=finding.get('details', {}))
        if finding['severity'] == 'error':
            result.scan_complete = False
    rows = []
    for table in extracted['tables']:
        for row in table['rows']:
            values = {int(key[1:]): {'value': value, 'value_type': 'text', 'formula': None,
                                    'cached_value': None, 'style': None}
                      for key, value in row['values'].items()}
            rows.append((row['metadata']['source_record'], values, {}))
    return rows, extracted['parser']


def compare_sources(before_bytes: bytes, after_bytes: bytes, media_type: str,
                    business_keys=None, *, limits=None, extraction_limits=None) -> dict:
    """Compare raw native revisions; unsupported PDF comparisons are explicit.

    Cell values remain exact strings. Formula text, cached values and effective
    style fingerprints are separate fields. Exact position is the default; only
    supplied unique business keys align moved rows. No network or arbitrary code.
    """
    if not isinstance(before_bytes, bytes) or not isinstance(after_bytes, bytes):
        raise TypeError('Comparison requires immutable source bytes')
    limits = limits or ComparisonLimits()
    extraction_limits = extraction_limits or ExtractionLimits()
    result = _Comparison(before_bytes, after_bytes, media_type, limits)
    if business_keys is None:
        business_keys = {}
    if not isinstance(business_keys, dict) or any(not isinstance(key, str) for key in business_keys):
        raise ValueError('Business keys must map exact sheet names to key configuration')
    for config in business_keys.values():
        _key_config(config)
    if media_type not in (XLSX, CSV):
        result.scan_complete = False
        result.ambiguity('unsupported_comparison_format', 'Raw comparison currently supports XLSX and CSV; this format requires separate evidence review.')
        return result.finish()
    books = []
    try:
        if media_type == CSV:
            before, left_parser = _csv_rows(before_bytes, 'before', result, extraction_limits)
            after, right_parser = _csv_rows(after_bytes, 'after', result, extraction_limits)
            result.scanned_before = sum(len(row[1]) for row in before)
            result.scanned_after = sum(len(row[1]) for row in after)
            for sheet in business_keys:
                if sheet != 'csv':
                    result.ambiguity('unknown_key_sheet', 'Configured business-key sheet was not found.', sheet=sheet)
            result.alignment['csv'] = 'business_keys' if 'csv' in business_keys else 'position'
            if left_parser != right_parser:
                result.change('parser_settings_changed', sheet='csv', before=left_parser, after=right_parser,
                              fields=('parser_settings',))
            if 'csv' in business_keys:
                _keyed_rows(result, 'csv', before, after, business_keys['csv'])
            else:
                _position_rows(result, 'csv', before, after)
            return result.finish()
        before = _Workbook(before_bytes, extraction_limits)
        books.append(before)
        after = _Workbook(after_bytes, extraction_limits)
        books.append(after)
        if before.properties != after.properties:
            result.change('workbook_properties_changed', before=before.properties, after=after.properties,
                          fields=('workbook_properties',))
        if list(before.sheets) != list(after.sheets):
            result.change('sheet_order_changed', before=list(before.sheets), after=list(after.sheets),
                          fields=('sheet_order',))
        if before.style_catalog != after.style_catalog:
            result.change('style_catalog_changed', before=before.style_catalog, after=after.style_catalog,
                          fields=('style_catalog',))
        for sheet in business_keys:
            if sheet not in before.sheets or sheet not in after.sheets:
                result.ambiguity('unknown_key_sheet', 'Configured business-key sheet is absent from one revision; no sheet rename was guessed.', sheet=sheet)
        for sheet in dict.fromkeys([*before.sheets, *after.sheets]):
            left = before.rows(sheet) if sheet in before.sheets else ()
            right = after.rows(sheet) if sheet in after.sheets else ()
            if sheet not in before.sheets:
                result.change('sheet_added', sheet=sheet, after=after.sheets[sheet], fields=('sheet',))
            elif sheet not in after.sheets:
                result.change('sheet_removed', sheet=sheet, before=before.sheets[sheet], fields=('sheet',))
            elif before.sheets[sheet]['state'] != after.sheets[sheet]['state']:
                result.change('sheet_visibility_changed', sheet=sheet, before=before.sheets[sheet]['state'],
                              after=after.sheets[sheet]['state'], fields=('visibility',))
            result.alignment[sheet] = 'business_keys' if sheet in business_keys else 'position'
            if sheet in business_keys:
                _keyed_rows(result, sheet, left, right, business_keys[sheet])
            else:
                _position_rows(result, sheet, left, right)
            if before.layout.get(sheet, []) != after.layout.get(sheet, []):
                result.change('sheet_properties_changed', sheet=sheet,
                              before=before.layout.get(sheet), after=after.layout.get(sheet), fields=('layout',))
        old_parts, new_parts = before.other_parts(), after.other_parts()
        for part in sorted(old_parts.keys() | new_parts.keys()):
            if old_parts.get(part) != new_parts.get(part):
                result.change('package_part_changed', before={'part': part, 'sha256': old_parts.get(part)},
                              after={'part': part, 'sha256': new_parts.get(part)}, fields=('package_metadata',))
                if part.startswith(('xl/media/', 'xl/charts/', 'xl/embeddings/')):
                    result.ambiguity('unmodeled_content_changed', 'Embedded visual/object content changed; cell comparison cannot interpret its impact.', part=part)
    except (ExtractionLimit, ValueError, KeyError, ET.ParseError, zipfile.BadZipFile, OSError,
            RuntimeError, OverflowError) as exc:
        result.scan_complete = False
        result.ambiguity('comparison_incomplete', 'Source comparison could not finish within supported structure and bounds.',
                         reason=str(exc)[:300])
    finally:
        if books:
            result.scanned_before = books[0].cells_seen
        if len(books) > 1:
            result.scanned_after = books[1].cells_seen
        for book in books:
            book.close()
    return result.finish()
