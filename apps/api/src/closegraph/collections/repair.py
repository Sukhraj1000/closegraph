"""Resolve specific extraction findings only after evidenced human repairs.

Resource limits, incomplete content, transport failures and unknown diagnostics
cannot be dismissed. Original parser evidence and coverage remain unchanged.
"""
from __future__ import annotations

from copy import deepcopy
import re

from closegraph.contracts import PdfLocator

EXCEL_ERRORS = {'#NULL!', '#DIV/0!', '#VALUE!', '#REF!', '#NAME?', '#NUM!', '#N/A',
                '#SPILL!', '#CALC!', '#GETTING_DATA'}


def _source_locations(row, column):
    values = [row.get('locators', {}).get(column)]
    values += row.get('source_locations', {}).get(column, [])
    return [value for value in values if isinstance(value, dict)]


def _location_key(locator):
    if locator.get('kind') == 'xlsx':
        return locator.get('sheet'), locator.get('cell')
    return None


def _human_value(row, column):
    value = row.get('values', {}).get(column)
    if value is None or not isinstance(value, str) or not value.strip() or value.strip().upper() in EXCEL_ERRORS:
        return False
    corrections = [entry for entry in row.get('corrections', []) if entry.get('column_key') == column]
    return bool(corrections and corrections[-1].get('value') == value and corrections[-1].get('actor_id'))


def _original_rows(row):
    # merge_rows retains original source rows; splits retain original metadata.
    yield row
    for original in row.get('source_rows', []):
        yield from _original_rows(original)


def set_pdf_citation(table, edit, *, actor, reason):
    """Apply an explicitly selected original-page box to one cell or a PDF block.

    Edit fields: op, row_id, column_key, original_page, bbox, optional
    processed_page (otherwise unknown), coordinate_system='normalised-0-1',
    apply_to='cell'|'block'. Source identity is always taken from the stored table.
    """
    if 'provider_block_index' not in table.get('metadata', {}):
        raise ValueError('PDF citations can only repair a PDF extraction dataset')
    target = next((row for row in table['rows'] if row['row_id'] == edit.get('row_id')), None)
    column = edit.get('column_key')
    if target is None or column not in target['values']:
        raise ValueError('Select an existing PDF source cell')
    apply_to = edit.get('apply_to', 'cell')
    if apply_to not in ('cell', 'block'):
        raise ValueError('Citation applies to a cell or the complete provider block')
    box = edit.get('bbox')
    if (not isinstance(box, (list, tuple)) or len(box) != 4
            or any(type(number) not in (int, float) for number in box)):
        raise ValueError('Citation needs four numeric bounding-box coordinates')
    if edit.get('coordinate_system', 'normalised-0-1') != 'normalised-0-1':
        raise ValueError('Human PDF selections use normalized original-page coordinates')
    locator = PdfLocator(original_page=edit.get('original_page'),
                         processed_page=edit.get('processed_page'),
                         coordinate_system='normalised-0-1', bbox=tuple(box)).model_dump(mode='json')
    locator.update(source_id=table['source_id'], citation_precision='human_' + apply_to,
                   authority='human_selection', selected_by=actor)
    affected = []
    for row in table['rows'] if apply_to == 'block' else [target]:
        for key in row['values'] if apply_to == 'block' else [column]:
            previous = deepcopy(row.get('locators', {}).get(key))
            row.setdefault('original_locators', deepcopy(row.get('locators', {})))
            row.setdefault('locators', {})[key] = deepcopy(locator)
            if key in row.get('lineage', {}):
                for reference in row['lineage'][key]:
                    reference.setdefault('original_locator', deepcopy(reference.get('locator')))
                    reference['locator'] = deepcopy(locator)
            row.setdefault('citation_corrections', []).append({
                'column_key': key, 'previous': previous, 'locator': deepcopy(locator),
                'actor_id': actor, 'reason': reason})
            affected.append({'row_id': row['row_id'], 'column_key': key})
    return affected


def repair_parser_issues(table, issues, *, actor, reason, related_tables=None):
    """Auto-resolve a correctable finding only when its full scope was repaired.

    related_tables contains current tables for this source, including table. It is
    required to resolve a sheet-wide formula finding split across several tables.
    The caller must load these from the same locked collection revision.
    """
    source_id = table['source_id']
    tables = [candidate for candidate in (related_tables or [table])
              if candidate.get('source_id') == source_id and candidate['table_id'] != table['table_id']]
    tables.append(table)
    by_id = {candidate['table_id']: candidate for candidate in tables}
    resolved = []
    prior_resolutions = {}
    for finding in issues:
        if (finding.get('source_id') == source_id and finding.get('resolved')
                and finding.get('resolution', {}).get('kind') == 'evidenced_human_repair'):
            prior_resolutions[finding['id']] = deepcopy(finding['resolution'])
            finding['resolved'] = False
            finding.pop('resolution', None)

    def close(finding, evidence):
        finding.update(resolved=True, resolution={'actor_id': actor, 'reason': reason,
                        'kind': 'evidenced_human_repair', 'evidence': evidence})
        resolved.append(finding['id'])

    # Index once: a worksheet with many uncached formulas must not perform one
    # complete table scan per finding/cell on each correction.
    active = [finding for finding in issues if not finding.get('resolved')
              and finding.get('source_id') == source_id]
    formula_sheets = {finding.get('details', {}).get('sheet') for finding in active
                      if finding.get('code') == 'formula_cache_missing'}
    missing_by_sheet = {sheet: set() for sheet in formula_sheets}
    if formula_sheets:
        for candidate in tables:
            for row in candidate['rows']:
                for original in _original_rows(row):
                    for column, metadata in original.get('metadata', {}).get('cells', {}).items():
                        formula = metadata.get('formula')
                        if not isinstance(formula, dict) or formula.get('cached_value') is not None:
                            continue
                        for locator in _source_locations(original, column):
                            if locator.get('kind') == 'xlsx' and locator.get('sheet') in formula_sheets:
                                missing_by_sheet[locator['sheet']].add(_location_key(locator))
    required = {location for locations in missing_by_sheet.values() for location in locations}
    required.update((finding.get('details', {}).get('sheet'), finding.get('details', {}).get('cell'))
                    for finding in active if finding.get('code') == 'spreadsheet_error')
    index = {}
    if required:
        for candidate in tables:
            for row in candidate['rows']:
                for column in row['values']:
                    locations = {_location_key(locator) for locator in _source_locations(row, column)}
                    for location in locations & required:
                        index.setdefault(location, []).append((row, column, candidate['table_id']))

    def corrected_location(location):
        matches = index.get(location, [])
        if not matches or not all(_human_value(row, column) for row, column, _ in matches):
            return None
        return [{'table_id': tid, 'row_id': row['row_id'], 'column_key': column}
                for row, column, tid in matches]

    for finding in issues:
        if finding.get('resolved') or finding.get('source_id') != source_id:
            continue
        code = finding.get('code')
        if code == 'spreadsheet_error':
            details = finding.get('details', {})
            evidence = corrected_location((details.get('sheet'), details.get('cell')))
            if evidence:
                close(finding, evidence)
        elif code == 'formula_cache_missing':
            details = finding.get('details', {})
            sheet = details.get('sheet')
            locations = missing_by_sheet.get(sheet, set())
            # Missing tables or stripped source metadata cannot silently satisfy the count.
            if type(details.get('count')) is not int or len(locations) != details['count']:
                continue
            repairs = [corrected_location(location) for location in sorted(locations)]
            if repairs and all(repairs):
                close(finding, [item for repair in repairs for item in repair])
        elif code == 'pdf_citation_missing':
            candidate = by_id.get(finding.get('table_id'))
            if not candidate or not candidate['rows']:
                continue
            cells = [(row, key) for row in candidate['rows'] for key in row['values']]
            if cells and all(any(correction.get('column_key') == key
                                  and correction.get('locator') == row.get('locators', {}).get(key)
                                  for correction in row.get('citation_corrections', []))
                             for row, key in cells):
                close(finding, [{'table_id': candidate['table_id'], 'row_id': row['row_id'],
                                 'column_key': key} for row, key in cells])
    # The legacy Reducto decoder reports invalid citations at block precision.
    # Only its exact citation/content diagnostic with separately retained, fully
    # repaired readable block content can be discharged. No wildcard dismissal.
    for finding in issues:
        if finding.get('resolved') or finding.get('source_id') != source_id or finding.get('code') != 'provider_diagnostic':
            continue
        diagnostic = finding.get('details', {}).get('diagnostic', '')
        match = re.fullmatch(r'block_([0-9]+)_malformed_citation_or_content', diagnostic)
        if not match:
            continue
        candidates = [candidate for candidate in tables
                      if candidate.get('metadata', {}).get('provider_block_index') == int(match[1])]
        if len(candidates) != 1 or not isinstance(candidates[0].get('metadata', {}).get('raw_content'), str):
            continue
        repaired = [item for item in issues if item.get('code') == 'pdf_citation_missing'
                    and item.get('table_id') == candidates[0]['table_id'] and item.get('resolved')
                    and item.get('resolution', {}).get('kind') == 'evidenced_human_repair']
        if repaired:
            close(finding, {'repaired_citation_issue': repaired[0]['id']})
    for finding in issues:
        previous = prior_resolutions.get(finding['id'])
        if previous is None:
            continue
        if finding.get('resolved'):
            # A rename/unrelated edit does not claim a new repair of the same issue.
            finding['resolution'] = previous
        else:
            finding.setdefault('resolution_history', []).append(previous)
            finding['resolution_invalidated_by'] = actor
    return [identity for identity in resolved if identity not in prior_resolutions]
