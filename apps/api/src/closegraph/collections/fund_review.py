"""Pure, source-backed review of explicitly selected reporting-pack checks.

Discovery proposes interpretations; only confirmed checks evaluate them. This
module never infers accounting policy or labels an entire workbook verified.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal, localcontext
from hashlib import sha256
import json
import re

from .reconcile import _decimal


CONCEPTS = {
    'entity_id': {'entity id', 'legal entity id', 'legal entity identifier', 'entity code', 'le id'},
    'entity_name': {'entity', 'entity name', 'legal entity', 'legal entity name', 'fund entity', 'le', 'le name'},
    'investor_id': {'investor id', 'investor identifier', 'investor code', 'lp id'},
    'investor_name': {'investor', 'investor name', 'limited partner', 'lp name'},
    'deal_id': {'deal id', 'deal code', 'deal identifier', 'investment id'},
    'deal_name': {'deal', 'deal name', 'investment name'},
    'account_id': {'account code', 'gl code', 'gl account', 'gl account code', 'account number', 'account id'},
    'account_name': {'account name', 'gl account name', 'account description'},
    'currency': {'currency', 'currency code', 'ccy', 'transaction currency', 'entity currency', 'base currency'},
    'amount': {'amount', 'transaction amount', 'entity amount', 'base amount', 'balance', 'net amount', 'value'},
    'date': {'date', 'transaction date', 'effective date', 'posting date', 'period', 'reporting period'},
    'reference': {'reference', 'transaction id', 'journal id', 'batch id', 'batch', 'journal number'},
    'status': {'status', 'review status', 'review', 'mapping status'},
}
REFERENCE_CONCEPTS = {key for key in CONCEPTS if key.endswith(('_id', '_name'))}
MAX_EVIDENCE = 12


def _text(value):
    return '' if value is None else str(value).strip()


def _label(value):
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', _text(value))
    return re.sub(r'[^a-z0-9]+', ' ', text.lower()).strip()


def _hash(value):
    return sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:24]


def _identity(table):
    return table.get('dataset_id', table.get('table_id', table.get('id')))


def _stable_table(table):
    meta = table.get('metadata', {})
    return [table.get('document_id') or table.get('source_id'), meta.get('sheet'), table.get('title')]


def _concept(label, title=''):
    name = _label(label)
    found = [key for key, aliases in CONCEPTS.items() if name in aliases]
    if len(found) == 1:
        return found[0]
    # Vendor/source prefixes are common. This only proposes a concept; exact
    # column positions and reference scope still require explicit confirmation.
    suffixes = [(len(alias), key) for key, aliases in CONCEPTS.items() for alias in aliases
                if len(alias.split()) >= 2 and name.endswith(' ' + alias)]
    if suffixes:
        longest = max(length for length, _ in suffixes)
        concepts = {key for length, key in suffixes if length == longest}
        if len(concepts) == 1:
            return next(iter(concepts))
    # A bare Name/ID is only useful when the table title supplies one domain.
    domains = [key for key, words in {
        'entity': {'entity', 'entities'}, 'investor': {'investor', 'investors'},
        'deal': {'deal', 'deals'}, 'account': {'account', 'accounts'},
    }.items() if set(_label(title).split()) & words]
    if len(domains) == 1 and name in {'name', 'id', 'identifier', 'code'}:
        return domains[0] + ('_name' if name == 'name' else '_id')
    return None


def _header_score(values):
    labels = [_text(value) for value in values if _text(value)]
    if not labels:
        return 0
    meaningful = sum(_concept(label) is not None for label in labels)
    numeric = sum(bool(re.fullmatch(r'[+-]?[\d,.]+', label)) for label in labels)
    return meaningful if numeric < len(labels) / 2 else 0


def _profile(table, config):
    rows = table.get('rows', [])
    native = {col['key']: col.get('label', col['key']) for col in table.get('columns', [])}
    native_score = _header_score(native.values())
    candidates = [(row, _header_score(row.get('values', {}).values())) for row in rows[:30]]
    best = max([native_score] + [score for _, score in candidates])
    best_rows = [row for row, score in candidates if score == best and score > 0]
    explicit = next((item for item in config.get('table_headers', []) if item.get('dataset_id') == _identity(table)), None)
    issues = []
    header = None
    status = 'ready'
    if explicit is not None:
        header = explicit.get('header_row_id')
        if header is not None and not any(row.get('row_id') == header for row in rows):
            issues.append('The selected header is unavailable in this version. Choose its current row.')
            status = 'needs_input'
    elif native_score and native_score >= best:
        pass
    elif len(best_rows) == 1:
        header, status = best_rows[0]['row_id'], 'suggested'
    elif best_rows:
        status = 'needs_input'
        issues.append('Several rows could be headers. Confirm the header before checking this table.')
    elif table.get('metadata', {}).get('suggested_header_row_id'):
        header = table['metadata']['suggested_header_row_id']
        status = 'suggested'
    else:
        status = 'needs_input'
        issues.append('Confirm whether a source row contains the column names.')
    chosen = next((row for row in rows if row.get('row_id') == header), None) if header is not None else None
    labels = chosen.get('values', {}) if chosen else native
    index = next((i for i, row in enumerate(rows) if row.get('row_id') == header), -1) if header is not None else -1
    data = rows[index + 1:]
    formula_count = sum(bool(cell.get('formula')) for row in data for cell in row.get('metadata', {}).get('cells', {}).values())
    formula_unverified = sum(bool(cell.get('formula')) and not cell['formula'].get('cache_verified')
                             for row in data for cell in row.get('metadata', {}).get('cells', {}).values())
    coverage = table.get('coverage', {})
    if coverage.get('complete') is not True:
        issues.append('Some source content is missing or extraction coverage has not been confirmed.')
    pdf_confirmed = table.get('extraction_confirmed') or table.get('source_id') in config.get('confirmed_source_ids', [])
    if table.get('media_type') == 'application/pdf' and not pdf_confirmed:
        issues.append('Check extracted PDF values against the original before confirming a result.')
    return {
        'dataset_id': _identity(table), 'source_id': table.get('source_id'), 'document_id': table.get('document_id'),
        'title': table.get('title') or 'Document table', 'row_count': len(rows), 'data_row_count': len(data),
        'header_row_id': header, 'header_status': status,
        'header_candidates': [{'row_id': row['row_id'], 'labels': list(row.get('values', {}).values())} for row in best_rows[:8]],
        'columns': [{'key': key, 'label': _text(labels.get(key)) or _text(value),
                     'concept': _concept(labels.get(key, value), table.get('title', ''))} for key, value in native.items()],
        'preview': [{'row_id': row['row_id'], 'values': dict(row.get('values', {})), 'locators': row.get('locators', {})} for row in data[:5]],
        'issues': issues, 'warnings': [f'{formula_unverified:,} formula results have not been independently checked.'] if formula_unverified else [],
        'coverage': dict(coverage), 'formula_count': formula_count,
        'formula_unverified': formula_unverified, 'parser_mode': table.get('parser', {}).get('mode'),
    }


def _cell_provenance(row, column):
    """Project only source values and the last still-effective column correction."""
    value = row.get('values', {}).get(column)
    corrections = row.get('corrections', [])
    operation = row.get('human_operation', {})
    if operation.get('op') == 'split_row':
        # A split explicitly replaces every cell. Corrections copied from its
        # parent are historical, even when a replacement happens to match.
        inherited_count = operation.get('inherited_correction_count')
        corrections = (corrections[inherited_count:] if isinstance(inherited_count, int)
                       and 0 <= inherited_count <= len(corrections) else [])
    elif row.get('source_rows'):
        # Merge copies the first contributing row's history. That history does
        # not establish a correction of the merged cell; later direct edits do.
        inherited = row['source_rows'][0].get('corrections', [])
        corrections = corrections[len(inherited):] if corrections[:len(inherited)] == inherited else []
    latest = next((entry for entry in reversed(corrections)
                   if entry.get('column_key') == column), None)
    originals = row.get('raw_values')
    if originals is None:
        # An unedited extracted cell is its own original. Do not make that
        # assumption for corrections or rows created through split/merge lineage.
        originals = (row.get('values', {}) if latest is None and not any(
            row.get(key) for key in ('lineage', 'source_row_ids', 'source_rows', 'human_operation')) else {})
    correction = None
    # A split can inherit a correction that no longer describes its value. Only
    # inspect the latest entry for this column; an older equal value is not proof.
    if latest and 'value' in latest and latest['value'] == value and latest.get('actor_id'):
        correction = {key: latest.get(key) for key in ('actor_id', 'reason')}
    return {'original_raw_value': originals.get(column),
            'original_value_available': column in originals, 'correction': correction}


def _evidence(table, row, column):
    value = row.get('values', {}).get(column)
    return {'dataset_id': _identity(table), 'source_id': table.get('source_id'), 'document_id': table.get('document_id'),
            'row_id': row['row_id'], 'column': column, 'column_key': column,
            # raw_value is a legacy alias for the effective value, not the source original.
            'raw_value': value, 'effective_value': value, **_cell_provenance(row, column),
            'locator': row.get('locators', {}).get(column),
            'table_title': table.get('title')}


def _records(table, rows, column):
    return [{'dataset_id': _identity(table), 'row_id': row['row_id'], 'column_key': column} for row in rows]


def _finding(check, tables, key, status, title, explanation, count=0, evidence=None, records=None, **details):
    stable = [check.get('id'), check.get('kind'), [_stable_table(table) for table in tables], key]
    match_key = _hash(stable)
    evidence = evidence or []
    total = details.pop('evidence_total', len(evidence))
    complete = records is not None or total == len(evidence) and count <= len(evidence)
    refs = records if records is not None else [
        {k: e.get(k) for k in ('dataset_id', 'row_id', 'column_key')} for e in evidence if e.get('dataset_id') and e.get('row_id')]
    # Duplicate financial values remain separate records. Only repeated citations
    # to the exact same physical source row share one full-row entry.
    refs = list({(r['dataset_id'], r['row_id']): r for r in refs}.values())
    return {'id': 'fund-finding-' + match_key, 'match_key': match_key, 'check_id': check.get('id'),
            'kind': check.get('kind', 'coverage'), 'status': status, 'title': title, 'explanation': explanation,
            'affected_count': count, 'evidence': evidence[:MAX_EVIDENCE],
            'evidence_total': total, '_record_refs': refs, 'records_complete': complete,
            'records_total': len(refs) if complete else max(count, total), 'blocking': True, **details}


def _selection(side, tables, profiles, config):
    table = tables.get(side.get('dataset_id'))
    if table is None:
        raise ValueError('A selected table is unavailable in this version. Choose its replacement.')
    profile = profiles[_identity(table)]
    columns = side.get('columns') or ([side['column']] if side.get('column') else [])
    groups = side.get('group_by', [])
    if not isinstance(columns, list) or not isinstance(groups, list) or not all(isinstance(k, str) for k in columns + groups):
        raise ValueError('Choose valid columns for this check.')
    if not columns or (set(columns + groups) - {col['key'] for col in table.get('columns', [])}):
        raise ValueError('One or more selected columns are missing. Confirm the mapping for this version.')
    if len(columns) != len(set(columns)) or len(groups) != len(set(groups)):
        raise ValueError('Choose each column only once.')
    header = side.get('header_row_id', profile['header_row_id'])
    if 'header_row_id' not in side and profile['header_status'] != 'ready':
        raise ValueError('Confirm the header row for the selected table.')
    rows = table.get('rows', [])
    index = next((i for i, row in enumerate(rows) if row.get('row_id') == header), -1) if header is not None else -1
    if header is not None and index == -1:
        raise ValueError('The selected header is unavailable in this version. Confirm its current row.')
    if table.get('coverage', {}).get('complete') is not True:
        raise ValueError('Extraction coverage is incomplete. A confirmed result cannot be established.')
    if table.get('media_type') == 'application/pdf' and not (table.get('extraction_confirmed') or table.get('source_id') in config.get('confirmed_source_ids', [])):
        raise ValueError('Confirm the PDF extraction against the original before checking these values.')
    selected = []
    header_values = rows[index].get('values', {}) if index >= 0 else None
    if index >= 0 and any(rows[index].get('metadata', {}).get('cells', {}).get(column, {}).get('formula')
                          and not rows[index]['metadata']['cells'][column]['formula'].get('cache_verified') for column in columns + groups):
        raise ValueError('A selected header formula has not been independently verified. Confirm its meaning before checking.')
    for row in rows[index + 1:]:
        if row.get('excluded'):
            if not row.get('exclusion_reason') and not row.get('reason'):
                raise ValueError('An excluded row has no recorded reason. Review it before checking.')
            continue
        values = row.get('values', {})
        if not any(_text(value) for value in values.values()):
            continue
        if header_values and all(_text(values.get(k)) == _text(header_values.get(k)) for k in columns + groups):
            raise ValueError('A repeated header occurs within the selected data. Review the rows before checking.')
        for column in columns + groups:
            cell = row.get('metadata', {}).get('cells', {}).get(column, {})
            formula = cell.get('formula')
            if formula and not formula.get('cache_verified'):
                raise ValueError('A selected formula result has not been independently verified. Refresh and check its calculation first.')
            if cell.get('type') == 'e':
                raise ValueError('A selected cell contains an Excel error. Correct it before checking.')
        selected.append(row)
    if not selected:
        raise ValueError('The selected table has no data rows; an empty input cannot pass a required check.')
    return table, selected, columns, groups


def _amount(value, number_format=None):
    # Excel stores small residuals in scientific notation. Decimal preserves the
    # original token exactly; this is numeric parsing, not a tolerance override.
    raw = _text(value)
    normalized = raw.replace('.', '').replace(',', '.') if number_format == 'comma_decimal' else raw.replace(',', '') if number_format == 'dot_decimal' else raw
    if len(raw) <= 128 and re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)[eE][+-]?\d{1,3}', normalized):
        amount = Decimal(normalized)
        if amount.is_finite() and abs(amount.adjusted()) <= 60:
            return amount
        raise ValueError('Amount is outside the supported range.')
    return _decimal(value, number_format)


def _key(row, columns):
    return tuple(_text(row.get('values', {}).get(column)) for column in columns)


def _run(check, tables, profiles, config):
    selected_tables = [tables[side['dataset_id']] for side in (check.get('left', {}), check.get('right', {})) if side.get('dataset_id') in tables]
    title = _text(check.get('title')) or 'Reporting check'
    if check.get('confirmed') is not True:
        return [_finding(check, selected_tables, 'unconfirmed', 'needs_input', title,
                         'Confirm the columns, reference list and intended scope before running this check.')]
    try:
        kind = check.get('kind')
        if kind not in {'reference', 'required', 'unique', 'totals'}:
            raise ValueError('This check type is not supported. It cannot establish verification.')
        left, lrows, lcols, lgroups = _selection(check.get('left', {}), tables, profiles, config)
        right, rrows, rcols, rgroups = None, [], [], []
        if kind in {'reference', 'totals'}:
            right, rrows, rcols, rgroups = _selection(check.get('right', {}), tables, profiles, config)
            if len(lcols) != 1 or len(rcols) != 1:
                raise ValueError('Choose one value column on each side of this check.')
            if len(lgroups) != len(rgroups):
                raise ValueError('Choose matching scope columns on both sides, in the same order.')
        selected_tables = [left] + ([right] if right else [])
        findings = []
        if kind == 'required':
            for column in lcols:
                missing = [row for row in lrows if not _text(row.get('values', {}).get(column))]
                if missing:
                    findings.append(_finding(check, selected_tables, ['missing', column], 'difference', title,
                        f'{len(missing):,} records are missing a value required by this check.', len(missing),
                        [_evidence(left, row, column) for row in missing[:MAX_EVIDENCE]], evidence_total=len(missing),
                        records=_records(left, missing, column),
                        expected='A value in every selected record', observed=f'{len(missing)} blank values',
                        operands={'column': column, 'evaluated_rows': len(lrows)}))
        elif kind == 'unique':
            grouped = defaultdict(list)
            for row in lrows:
                grouped[_key(row, lcols)].append(row)
            for value, rows in grouped.items():
                if not all(value) or len(rows) > 1:
                    missing = not all(value)
                    findings.append(_finding(check, selected_tables, ['unique', value], 'difference', title,
                        'The selected business key is blank.' if missing else f'This business key occurs in {len(rows):,} records. No duplicate has been silently chosen.',
                        len(rows), [_evidence(left, row, lcols[0]) for row in rows[:MAX_EVIDENCE]], evidence_total=len(rows),
                        records=_records(left, rows, lcols[0]),
                        expected='One nonblank record per selected key', observed=list(value),
                        operands={'key_columns': lcols, 'occurrences': len(rows)}))
        elif kind == 'reference':
            reference = defaultdict(list)
            for row in rrows:
                value = _key(row, rgroups + rcols)
                if not all(value):
                    raise ValueError('The selected reference list has blank keys. Review its scope and completeness first.')
                reference[value].append(row)
            ambiguous = [key for key, rows in reference.items() if len(rows) > 1]
            if ambiguous:
                rows = reference[ambiguous[0]]
                return [_finding(check, selected_tables, 'ambiguous_reference', 'needs_input', title,
                    f'{len(ambiguous):,} reference keys occur more than once. Confirm the correct reference scope before checking membership.',
                    sum(len(reference[key]) for key in ambiguous), [_evidence(right, row, rcols[0]) for row in rows[:MAX_EVIDENCE]],
                    records=_records(right, [row for key in ambiguous for row in reference[key]], rcols[0]),
                    evidence_total=sum(len(reference[key]) for key in ambiguous),
                    expected='A unique, nonblank reference key', observed=f'{len(ambiguous)} duplicate keys')]
            unmatched = defaultdict(list)
            for row in lrows:
                value = _key(row, lgroups + lcols)
                if not all(value) or value not in reference:
                    unmatched[value].append(row)
            for value, rows in unmatched.items():
                findings.append(_finding(check, selected_tables, ['reference', value], 'difference', title,
                    'A required reference value is blank.' if not all(value) else 'This value is absent from the reference list you selected. Confirm or correct the mapping; this alone does not establish an accounting error.',
                    len(rows), [_evidence(left, row, lcols[0]) for row in rows[:MAX_EVIDENCE]], evidence_total=len(rows),
                    records=_records(left, rows, lcols[0]),
                    expected='Present in the selected reference list', observed=list(value),
                    operands={'source_column': lcols[0], 'reference_column': rcols[0], 'reference_rows': len(rrows), 'scope_columns': lgroups}))
        elif kind == 'totals':
            if not lgroups:
                raise ValueError('Choose explicit grouping columns, including the relevant entity, currency and period scope. Whole-workbook totals can hide offsetting errors.')
            tolerance = _decimal(check.get('tolerance', '0'))
            if tolerance < 0:
                raise ValueError('Tolerance cannot be negative.')
            def aggregate(rows, columns, groups, side):
                result = defaultdict(lambda: {'amount': Decimal(0), 'rows': []})
                with localcontext() as ctx:
                    ctx.prec = 160
                    for row in rows:
                        key = _key(row, groups)
                        if not all(key):
                            raise ValueError('A grouping value is blank. Confirm entity, currency and period scope before comparing totals.')
                        amount = _amount(row.get('values', {}).get(columns[0]), side.get('number_format'))
                        result[key]['amount'] += amount
                        result[key]['rows'].append(row)
                return result
            lvalues = aggregate(lrows, lcols, lgroups, check['left'])
            rvalues = aggregate(rrows, rcols, rgroups, check['right'])
            for value in sorted(set(lvalues) | set(rvalues)):
                lgroup, rgroup = lvalues.get(value), rvalues.get(value)
                expected = rgroup['amount'] if rgroup else None
                observed = lgroup['amount'] if lgroup else None
                with localcontext() as ctx:
                    ctx.prec = 160
                    difference = observed - expected if observed is not None and expected is not None else None
                if difference is not None and abs(difference) <= tolerance:
                    findings.append(_finding(check, selected_tables, ['totals', value], 'passed', title,
                        'The selected group totals agree within the configured tolerance. This does not prove individual records or accounting treatment.',
                        0, [_evidence(left, lgroup['rows'][0], lcols[0]), _evidence(right, rgroup['rows'][0], rcols[0])],
                        records=_records(left, lgroup['rows'], lcols[0]) + _records(right, rgroup['rows'], rcols[0]),
                        evidence_total=len(lgroup['rows']) + len(rgroup['rows']),
                        expected=str(expected), observed=str(observed), difference=str(difference),
                        operands={'group': list(value), 'left_rows': len(lgroup['rows']), 'right_rows': len(rgroup['rows']),
                                  'tolerance': str(tolerance), 'left_group_columns': lgroups, 'right_group_columns': rgroups}))
                else:
                    le = [_evidence(left, row, lcols[0]) for row in (lgroup or {}).get('rows', [])[:6]]
                    revidence = [_evidence(right, row, rcols[0]) for row in (rgroup or {}).get('rows', [])[:6]]
                    affected = len((lgroup or {}).get('rows', [])) + len((rgroup or {}).get('rows', []))
                    findings.append(_finding(check, selected_tables, ['totals', value], 'difference', title,
                        'This group is missing from one selected table.' if difference is None else 'The selected group totals differ beyond the explicitly configured tolerance.',
                        affected, le + revidence, evidence_total=affected,
                        records=_records(left, (lgroup or {}).get('rows', []), lcols[0]) + _records(right, (rgroup or {}).get('rows', []), rcols[0]),
                        expected=None if expected is None else str(expected), observed=None if observed is None else str(observed),
                        difference=None if difference is None else str(difference),
                        operands={'group': list(value), 'left_rows': len((lgroup or {}).get('rows', [])),
                                  'right_rows': len((rgroup or {}).get('rows', [])), 'tolerance': str(tolerance),
                                  'left_group_columns': lgroups, 'right_group_columns': rgroups}))
        if not findings:
            findings = [_finding(check, selected_tables, 'passed', 'passed', title,
                ('The selected group totals agree. Matching totals do not prove individual records or accounting treatment.' if kind == 'totals'
                 else 'The explicitly selected check passes for these source versions. Other financial rules have not been inferred.'),
                0, [_evidence(left, lrows[0], lcols[0])],
                records=_records(left, lrows, lcols[0]) + (_records(right, rrows, rcols[0]) if right else []),
                evidence_total=len(lrows) + len(rrows),
                expected='Selected check satisfied', observed='Passed',
                operands={'left_rows': len(lrows), 'right_rows': len(rrows), 'left_columns': lcols, 'right_columns': rcols})]
        return findings
    except (ValueError, TypeError, KeyError) as exc:
        return [_finding(check, selected_tables, 'blocked', 'needs_input', title, str(exc),
                         expected='Complete, unambiguous inputs and an explicit supported check', observed='Not evaluated')]


def _suggestions(envelopes, profiles, configured):
    candidates = []
    for table in envelopes:
        profile = profiles[_identity(table)]
        if profile['header_status'] == 'needs_input':
            continue
        start = next((i + 1 for i, row in enumerate(table.get('rows', [])) if row.get('row_id') == profile['header_row_id']), 0)
        rows = table.get('rows', [])[start:]
        for column in profile['columns']:
            if column['concept'] not in REFERENCE_CONCEPTS:
                continue
            counts = Counter(_text(row.get('values', {}).get(column['key'])) for row in rows)
            values = set(counts) - {''}
            if not values:
                continue
            reference_hint = bool(set(_label(profile['title']).split()) & {'mapping', 'list', 'listing', 'reference', 'master', 'mappings'})
            candidates.append({'table': table, 'profile': profile, 'column': column, 'values': values,
                               'unique': len(values) == len(rows), 'reference_hint': reference_hint})
    proposals = []
    signatures = {(c.get('kind'), c.get('left', {}).get('dataset_id'), c.get('left', {}).get('column'),
                   c.get('right', {}).get('dataset_id'), c.get('right', {}).get('column')) for c in configured}
    for left in candidates:
        options = []
        for right in candidates:
            if left['table'] is right['table'] or left['column']['concept'] != right['column']['concept']:
                continue
            if not right['unique'] or not right['reference_hint']:
                continue
            overlap = len(left['values'] & right['values'])
            if not overlap or overlap / len(left['values']) < 0.2:
                continue
            signature = ('reference', _identity(left['table']), left['column']['key'], _identity(right['table']), right['column']['key'])
            if signature in signatures:
                continue
            # Prefer a comprehensive unique list, with useful gaps surfaced in the preview.
            options.append((overlap / len(left['values']), -len(right['values']), right, overlap))
        if not options:
            continue
        _, _, right, overlap = max(options, key=lambda item: (item[0], item[1]))
        left_side = {'dataset_id': _identity(left['table']), 'column': left['column']['key'], 'header_row_id': left['profile']['header_row_id']}
        right_side = {'dataset_id': _identity(right['table']), 'column': right['column']['key'], 'header_row_id': right['profile']['header_row_id']}
        stable = [_stable_table(left['table']), left['column']['concept'], left['column']['key'], _stable_table(right['table']), right['column']['key']]
        proposals.append({'id': 'reference-' + _hash(stable), 'kind': 'reference', 'confirmed': False,
            'title': f"Check {left['column']['label']} against {right['profile']['title']}",
            'left': left_side, 'right': right_side,
            'rationale': f"The column meanings appear compatible and {overlap:,} of {len(left['values']):,} distinct source values occur exactly in this unique reference list. Confirm that this is the intended list for the same fund and period.",
            'overlap': {'matched_distinct': overlap, 'source_distinct': len(left['values']), 'reference_distinct': len(right['values'])}})
    proposals.sort(key=lambda item: (item['overlap']['matched_distinct'] == item['overlap']['source_distinct'],
                                      -item['overlap']['source_distinct']))
    return proposals[:8]


def _selected_columns(checks, tables, profiles):
    """Establish an explicit column scope without evaluating formula caches."""
    selected = defaultdict(set)
    known = bool(checks)
    for check in checks:
        kind = check.get('kind')
        if check.get('confirmed') is not True or kind not in {'reference', 'required', 'unique', 'totals'}:
            known = False
            continue
        for name in ('left', 'right') if kind in {'reference', 'totals'} else ('left',):
            side = check.get(name, {})
            table = tables.get(side.get('dataset_id'))
            columns = side.get('columns') or ([side['column']] if side.get('column') else [])
            groups = side.get('group_by', [])
            if not table or not isinstance(columns, list) or not isinstance(groups, list) or not columns or not all(isinstance(c, str) for c in columns + groups):
                known = False
                continue
            keys = set(columns + groups)
            profile = profiles[_identity(table)]
            header = side.get('header_row_id', profile['header_row_id'])
            if keys - {c['key'] for c in table['columns']} or ('header_row_id' not in side and profile['header_status'] != 'ready') or (header is not None and not any(r['row_id'] == header for r in table['rows'])):
                known = False
            selected[_identity(table)].update(keys)
    return known, selected


def analyze(envelopes, config=None):
    """Return bounded previews plus fully evaluated, source-linked findings.

    Check configuration is caller-owned and must be persisted with source/rule
    versions. Exact string identity (after surrounding whitespace) is used for
    reference keys. No fuzzy matching or accounting interpretation is performed.
    """
    config = config or {}
    tables = {_identity(table): table for table in envelopes}
    profiles = {_identity(table): _profile(table, config) for table in envelopes}
    checks = config.get('checks', [])
    findings = []
    conditions = {}
    ids = Counter(check.get('id') for check in checks)
    scope_known, selected_columns = _selected_columns(checks, tables, profiles)
    scope_known = scope_known and all(check.get('id') and ids[check['id']] == 1 for check in checks)
    for check in checks:
        if not check.get('id') or ids[check.get('id')] != 1:
            findings.append(_finding(check, [], 'invalid_id', 'needs_input', 'Confirm the check configuration',
                                     'Each check needs a distinct identifier before its results can be tracked.'))
        else:
            findings.extend(_run(check, tables, profiles, config))
    for table in envelopes:
        profile = profiles[_identity(table)]
        condition_key = _finding({'id': 'coverage-' + _hash(_stable_table(table)), 'kind': 'coverage'}, [table], 'coverage',
                                 'needs_input', '', '')['match_key']
        header_confirmed = profile['header_status'] == 'ready' or any(
            isinstance(check.get(side), dict) and check[side].get('dataset_id') == _identity(table)
            and 'header_row_id' in check[side] and check[side]['header_row_id'] == profile['header_row_id']
            and check.get('confirmed') is True
            for check in checks for side in ('left', 'right'))
        # Keep the old coverage predicate conservative: a historical request
        # about unchecked formulas must not be relabelled a passing cache check.
        conditions[condition_key] = {'kind': 'coverage', 'passed': not profile['issues'] and not profile['formula_unverified'] and header_confirmed,
            'dataset_id': _identity(table), 'document_id': table.get('document_id'),
            'reason': 'Source-reading and header-interpretation conditions are satisfied for this same table. This is not financial verification.'}
        if profile['issues']:
            findings.append(_finding({'id': 'coverage-' + _hash(_stable_table(table)), 'kind': 'coverage'}, [table], 'coverage',
                'needs_input', f"Check {profile['title']}", ' '.join(profile['issues']), profile['row_count'],
                [_evidence(table, table['rows'][0], table['columns'][0]['key'])] if table.get('rows') and table.get('columns') else [],
                records=_records(table, table.get('rows', []), table['columns'][0]['key']) if table.get('columns') else [],
                expected='Complete source coverage and confirmed interpretation', observed='Needs checking'))
        formula_check = {'id': 'formula-scope-' + _hash(_stable_table(table)), 'kind': 'formula_scope'}
        formula_key = _finding(formula_check, [table], 'formulas', 'needs_input', '', '')['match_key']
        conditions[formula_key] = {'kind': 'formula_scope', 'passed': not profile['formula_unverified'],
                                   'reason': 'No unverified formula caches remain in this table.'}
        if profile['formula_unverified']:
            start = next((i + 1 for i, row in enumerate(table['rows']) if row['row_id'] == profile['header_row_id']), 0)
            cells = [(row, column) for row in table['rows'][start:]
                     for column, cell in row.get('metadata', {}).get('cells', {}).items()
                     if cell.get('formula') and not cell['formula'].get('cache_verified')]
            outside = scope_known and all(column not in selected_columns[_identity(table)] for _, column in cells)
            explanation = (f'{len(cells):,} formula results are outside the columns used by your selected checks. These formulas have not been verified; approval covers only the selected checks.'
                           if outside else f'{len(cells):,} formula results have not been independently checked. A selected or unresolved column scope still requires review.')
            findings.append(_finding(formula_check, [table], 'formulas', 'needs_input',
                'Unreviewed formula results', explanation, len(cells),
                [_evidence(table, row, column) for row, column in cells[:MAX_EVIDENCE]],
                records=[{'dataset_id': _identity(table), 'row_id': row['row_id'], 'column_key': column} for row, column in cells],
                evidence_total=len(cells), blocking=not outside,
                expected='Independently checked calculation results', observed='Formula caches remain unverified'))
    scope_key = _finding({'id': 'check_scope', 'kind': 'configuration'}, [], 'no_checks', 'needs_input', '', '')['match_key']
    conditions[scope_key] = {'kind': 'configuration', 'passed': bool(checks) and all(
        check.get('id') and ids[check.get('id')] == 1 and check.get('confirmed') is True
        and check.get('kind') in {'reference', 'required', 'unique', 'totals'} for check in checks),
        'reason': 'Supported checks have been explicitly selected. Their findings remain separate from this configuration condition.'}
    if not checks:
        findings.append(_finding({'id': 'check_scope', 'kind': 'configuration'}, [], 'no_checks', 'needs_input',
            'Choose what this review should check',
            'Once the documents are readable, confirm a suggested check or choose the fields and totals that matter; extraction alone does not verify the figures.'))
    counts = Counter(finding['status'] for finding in findings)
    configured_findings = [finding for finding in findings if finding['kind'] not in {'coverage', 'configuration', 'formula_scope'}]
    return {'tables': list(profiles.values()), 'suggestions': _suggestions(envelopes, profiles, checks),
            'findings': findings, 'condition_outcomes': conditions,
            'summary': {'table_count': len(envelopes), 'source_count': len({table.get('source_id') for table in envelopes}),
                'row_count': sum(len(table.get('rows', [])) for table in envelopes), 'check_count': len(checks),
                'passed': counts['passed'], 'difference': counts['difference'], 'needs_input': counts['needs_input'],
                'blocking_needs_input': sum(f['status'] == 'needs_input' and f.get('blocking', True) for f in findings),
                'nonblocking_needs_input': sum(f['status'] == 'needs_input' and not f.get('blocking', True) for f in findings),
                'blocking_difference': sum(f['status'] == 'difference' and f.get('blocking', True) for f in findings),
                'scoped_checks_passed': bool(checks) and bool(configured_findings) and all(f['status'] == 'passed' for f in configured_findings),
                'financially_verified': False,
                'message': 'Results apply only to the confirmed checks and selected evidence. They do not establish whole-pack financial correctness.'},
            'coverage': {'complete': bool(envelopes) and all(table.get('coverage', {}).get('complete') is True for table in envelopes),
                         'unclassified_tables': sum(p['header_status'] == 'needs_input' for p in profiles.values()),
                         'formula_results_unverified': sum(p['formula_unverified'] for p in profiles.values())}}
