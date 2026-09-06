"""Deterministic, side-effect-free reconciliation. Never calls an AI provider.

Inputs are extraction table envelopes. Config has mappings (one per selected
 dataset), composite_confirmed, and tolerance. Unselected tables stay accounted
 for in coverage; interpretation ambiguity never becomes a confirmed match.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from hashlib import sha256
import json
import re

ALIASES = {
    'reference': {'reference', 'transaction reference', 'transaction id', 'reference number', 'bank reference'},
    'account': {'account', 'account number', 'bank account', 'bank account number', 'iban'},
    'currency': {'currency', 'ccy', 'currency code', 'transaction currency'},
    'date': {'date', 'transaction date', 'booking date', 'value date', 'effective date'},
    'amount': {'amount', 'transaction amount', 'net amount', 'amount local'},
    'debit': {'debit', 'debit amount', 'withdrawal', 'withdrawals', 'money out'},
    'credit': {'credit', 'credit amount', 'deposit', 'deposits', 'money in'},
    'batch': {'batch', 'batch id', 'journal batch', 'journal number'},
}


def _hash(value):
    return sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:24]


def _text(value):
    return '' if value is None else str(value).strip()


def _label(value):
    return re.sub(r'[^a-z0-9]+', ' ', _text(value).lower()).strip()


def _guess(labels):
    found = {role: [key for key, label in labels.items() if _label(label) in names]
             for role, names in ALIASES.items()}
    return {role: keys[0] for role, keys in found.items() if len(keys) == 1}


def _mapping(config, identity):
    return next((m for m in config.get('mappings', []) if m.get('dataset_id') == identity or identity in m.get('dataset_ids', [])), None)


def _identity(table):
    return table.get('dataset_id', table.get('table_id', table.get('id')))


def propose(envelopes, config=None):
    config = config or {}
    suggestions = []
    contexts = defaultdict(lambda: defaultdict(set))
    for table in envelopes:
        if table.get('media_type') != 'application/pdf':
            continue
        for row in table.get('rows', []):
            values = list(row.get('values', {}).values())
            for label, value in zip(values, values[1:]):
                for role in ('account', 'currency'):
                    if _label(label) in (ALIASES[role] - {'iban'} if role == 'account' else ALIASES[role]) and _text(value):
                        contexts[table.get('source_id')][role].add(_text(value))
    for table in envelopes:
        identity = _identity(table)
        explicit = _mapping(config, identity)
        columns = {c['key']: c.get('label', c['key']) for c in table['columns']}
        candidates = [(None, _guess(columns))]
        for row in table.get('rows', [])[:30]:
            candidates.append((row['row_id'], _guess(row.get('values', {}))))
        useful = [(rowid, mapping) for rowid, mapping in candidates
                  if ('amount' in mapping or 'debit' in mapping or 'credit' in mapping)
                  and ('date' in mapping or 'reference' in mapping)]
        best = max((len(m) for _, m in useful), default=0)
        useful = [(r, m) for r, m in useful if len(m) == best]
        context = {role: next(iter(values)) for role, values in contexts[table.get('source_id')].items() if len(values) == 1}
        issues = []
        if explicit:
            mapping = dict(explicit.get('columns', {}))
            header = explicit.get('header_row_id')
            if header and not any(r['row_id'] == header for r in table.get('rows', [])):
                possible = [rowid for rowid, guessed in useful if all(guessed.get(role) == key for role,key in mapping.items() if role in guessed)]
                if explicit.get('dataset_ids') and len(possible) == 1:
                    header = possible[0]
                else:
                    header = None
                    issues.append('The selected header is unavailable; confirm the header in this revision.')
        elif len(useful) == 1:
            header, mapping = useful[0]
        else:
            header, mapping = None, {}
            issues.append('Choose the transaction table and confirm its columns.')
        if table.get('side') == 'journal' and not (explicit and explicit.get('cash_leg_confirmed')):
            issues.append('Confirm which records are journal cash entries before comparing.')
        if not ('amount' in mapping or 'credit' in mapping or 'debit' in mapping):
            issues.append('Choose the amount or debit/credit columns.')
        if not ('account' in mapping or (explicit or {}).get('account') or context.get('account')):
            issues.append('Confirm the bank account for these records.')
        if not ('currency' in mapping or (explicit or {}).get('currency') or context.get('currency')):
            issues.append('Confirm the currency for these records.')
        labels = list(columns.values()) if header is None else list(next(r for r in table['rows'] if r['row_id'] == header)['values'].values())
        kind = 'transactions' if mapping else 'unclassified'
        header_labels = {_label(v) for r in table.get('rows', [])[:1] for v in r.get('values', {}).values()}
        reference_headers = {'legal entity','vendor','account number','bank account','account','project code','related party','deal name','investor','security id','stage','allocation rules'}
        if not mapping and header_labels & reference_headers and not any(_guess(r.get('values', {})).get(role) for r in table.get('rows', [])[:1] for role in ('date','amount','debit','credit')):
            kind, issues = 'supporting', []
        if not mapping and table.get('media_type') == 'application/pdf':
            rows = table.get('rows', [])
            key_value = rows and all(_label(next(iter(r.get('values', {}).values()), '')) in {
                'account name', 'account number', 'currency', 'account currency', 'iban', 'bank',
                'statement date', 'statement period', 'opening balance', 'closing balance', 'from', 'to',
                'bank name','location','bic','account status','account type'
            } for r in rows)
            narrative = len(columns) == 1 and all(not re.search(r'\d+[.,]\d{2}(?:\s|$)', _text(v)) for r in rows for v in r.get('values', {}).values())
            if key_value or narrative:
                kind, issues = 'supporting', []
        suggestions.append({'dataset_id': identity, 'group_id': _hash([table.get('side'), [_label(v) for v in labels]]),
                            'context': context, 'kind': kind, 'side': table.get('side'),
                            'title': table.get('title', 'Document table'), 'columns': mapping,
                            'header_row_id': header, 'status': 'needs_input' if issues else 'ready',
                            'issues': issues, 'preview': table.get('rows', [])[:5],
                            'available_columns': table['columns']})
    # Multiple candidate tables from a source must be selected explicitly.
    candidates = Counter(t.get('source_id') for t, s in zip(envelopes, suggestions)
                         if s['columns'] and not _mapping(config, _identity(t)))
    for table, suggestion in zip(envelopes, suggestions):
        if candidates[table.get('source_id')] > 1 and table.get('media_type') != 'application/pdf' and not _mapping(config, _identity(table)):
            suggestion['issues'].append('Several tables could contain transactions; select the relevant table.')
            suggestion['status'] = 'needs_input'
    groups = defaultdict(list)
    for suggestion in suggestions:
        groups[suggestion['group_id']].append(suggestion['dataset_id'])
    for suggestion in suggestions:
        suggestion['dataset_ids'] = groups[suggestion['group_id']]
    return {'suggestions': suggestions}


def _decimal(value, number_format=None):
    text = _text(value)
    if not text or len(text) > 128:
        raise ValueError('Missing or invalid amount.')
    if text.startswith('(') and text.endswith(')'):
        text = '-' + text[1:-1]
    if number_format == 'comma_decimal':
        text = text.replace('.', '').replace(',', '.')
    elif number_format == 'dot_decimal':
        text = text.replace(',', '')
    elif ',' in text:
        if re.fullmatch(r'[+-]?\d{1,3}(?:,\d{3})+\.\d+', text):
            text = text.replace(',', '')
        else:
            raise ValueError('Confirm the number format.')
    if not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)', text):
        raise ValueError('Amount is not an explicit decimal number.')
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise ValueError('Invalid amount.') from None
    if not value.is_finite() or abs(value.adjusted()) > 60:
        raise ValueError('Amount is outside the supported range.')
    return value


def _date(value, date_format=None):
    text = _text(value)
    if not text:
        return ''
    try:
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}(?:T.*)?', text):
            return datetime.fromisoformat(text).date().isoformat()
        if re.fullmatch(r'\d{1,2} [A-Za-z]{3} \d{4}', text):
            return datetime.strptime(text, '%d %b %Y').date().isoformat()
        formats = {'day_first': '%d/%m/%Y', 'month_first': '%m/%d/%Y'}
        if date_format in ('excel_1900', 'excel_1904'):
            serial = _decimal(text)
            if serial != serial.to_integral_value() or abs(serial) > 1000000:
                raise ValueError('Invalid Excel date serial.')
            epoch = datetime(1899, 12, 30) if date_format == 'excel_1900' else datetime(1904, 1, 1)
            return (epoch + timedelta(days=int(serial))).date().isoformat()
        if date_format in formats:
            return datetime.strptime(text.replace('-', '/'), formats[date_format]).date().isoformat()
    except ValueError:
        pass
    raise ValueError('Confirm the date interpretation.')


def _source(table, row):
    return {'dataset_id': _identity(table), 'source_id': table.get('source_id'),
            'document_id': table.get('document_id'), 'row_id': row['row_id'],
            'values': row.get('values', {}), 'locators': row.get('locators', {}),
            'lineage': row.get('lineage', {})}


def _records(table, suggestion, config, envelopes):
    explicit = _mapping(config, _identity(table)) or {}
    mapping = suggestion['columns']
    records, coverage = [], {'dataset_id': _identity(table), 'source_id': table.get('source_id'),
        'total_rows': len(table.get('rows', [])), 'transaction_rows': 0, 'excluded_rows': 0,
        'unclassified_rows': 0, 'header_rows': 0, 'issues': []}
    rows = table.get('rows', [])
    header_id = suggestion['header_row_id']
    header_index = next((i for i, row in enumerate(rows) if row['row_id'] == header_id), -1)
    if explicit.get('exclude'):
        if not _text(explicit.get('reason')):
            raise ValueError('Excluding a table requires a reason.')
        coverage.update(excluded_rows=len(rows), exclusion_reason=explicit['reason'])
        return records, coverage
    if suggestion.get('kind') == 'supporting':
        coverage['supporting_rows'] = len(rows)
        return records, coverage
    if not mapping:
        coverage['unclassified_rows'] = len(rows)
        coverage['issues'].append('Table interpretation is unresolved.')
        return records, coverage
    if set(mapping.values()) - {c['key'] for c in table['columns']}:
        raise ValueError('Mapping refers to an unknown column.')
    debit_values = [r.get('values', {}).get(mapping.get('debit')) for r in rows[header_index + 1:]]
    debit_negative = any(_text(v).startswith('-') for v in debit_values)
    debit_positive = any(_text(v) and not _text(v).startswith('-') and _text(v) not in ('0','0.00') for v in debit_values)
    lookup_indexes = []
    lookup_problems = []
    for lookup in explicit.get('lookups', []):
        target = lookup.get('target')
        other = next((t for t in envelopes if _identity(t) == lookup.get('table_id')), None)
        if target not in ('account', 'currency', 'reference'):
            raise ValueError('Invalid reference mapping.')
        if other is None:
            lookup_problems.append('The reference table is unavailable in this revision.')
            continue
        keys = {c['key'] for c in other['columns']}
        if lookup.get('key_column') not in keys or lookup.get('value_column') not in keys:
            raise ValueError('Reference mapping columns do not exist.')
        indexed = defaultdict(list)
        for refrow in other['rows']:
            if refrow.get('excluded') or refrow['row_id'] == lookup.get('header_row_id'):
                continue
            key = _text(refrow.get('values', {}).get(lookup['key_column']))
            if key:
                indexed[key].append(refrow)
        lookup_indexes.append((lookup, other, indexed))
    for index, row in enumerate(rows):
        if index <= header_index:
            coverage['header_rows'] += 1
            continue
        if row.get('excluded'):
            coverage['excluded_rows'] += 1
            continue
        values = row.get('values', {})
        if not any(_text(v) for v in values.values()):
            coverage['excluded_rows'] += 1
            continue
        if (_label(next(iter(values.values()), '')) in ('narrative','description','transaction details') or (table.get('media_type') == 'application/pdf' and re.match(r'^(?:balance as at close|balance brought forward|opening balance|closing balance)\b', _label(next(iter(values.values()), ''))))) and not any(_text(values.get(mapping.get(role))) for role in ('date','amount','debit','credit')):
            coverage['supporting_rows'] = coverage.get('supporting_rows', 0) + 1
            if records:
                records[-1].setdefault('supporting_evidence', []).append(_source(table, row))
            continue
        if _guess(values) == mapping:
            coverage['header_rows'] += 1
            continue
        cash = explicit.get('cash_leg')
        if cash and explicit.get('cash_leg_confirmed'):
            if cash.get('column') not in {c['key'] for c in table['columns']}:
                raise ValueError('Cash filter refers to an unknown column.')
            if _text(values.get(cash['column'])) not in [_text(v) for v in cash.get('values', [])]:
                coverage['excluded_rows'] += 1
                continue
        get = lambda role: values.get(mapping.get(role, ''))
        issues = list(suggestion['issues']) + lookup_problems
        for key in mapping.values():
            formula = row.get('metadata', {}).get('cells', {}).get(key, {}).get('formula')
            if formula and not formula.get('cache_verified'):
                issues.append('A required formula result has not been independently verified.')
        source_coverage = table.get('coverage', {})
        if source_coverage.get('complete') is not True:
            issues.append('Source coverage is incomplete or unconfirmed.')
        if table.get('media_type') == 'application/pdf' and not table.get('extraction_confirmed', False):
            issues.append('Confirm extracted PDF transaction values against the original.')
        amount = None
        try:
            if 'amount' in mapping:
                amount = _decimal(get('amount'), explicit.get('number_format'))
                direction = explicit.get('direction')
                if direction:
                    raw_direction = _text(values.get(direction.get('column')))
                    signs = {_text(k): v for k, v in direction.get('signs', {}).items()}
                    if raw_direction not in signs or signs[raw_direction] not in (-1, 1):
                        raise ValueError('Confirm the amount direction.')
                    amount *= signs[raw_direction]
            else:
                debit, credit = get('debit'), get('credit')
                if not _text(debit) and not _text(credit):
                    raise ValueError('Missing amount; blank debit and credit are not zero.')
                credit_value = _decimal(credit, explicit.get('number_format')) if _text(credit) else Decimal(0)
                debit_value = _decimal(debit, explicit.get('number_format')) if _text(debit) else Decimal(0)
                if debit_negative and debit_positive and explicit.get('debit_sign') not in ('signed','positive'):
                    raise ValueError('Debit amounts have mixed signs; confirm their interpretation.')
                signed = explicit.get('debit_sign') == 'signed' or (not explicit.get('debit_sign') and debit_negative and not debit_positive)
                amount = credit_value + debit_value if signed else credit_value - debit_value
            amount *= _decimal(explicit.get('amount_multiplier', '1'))
        except ValueError as exc:
            issues.append(str(exc))
        resolved = {}
        lookup_refs = []
        for lookup, other, indexed in lookup_indexes:
            matches = indexed.get(_text(values.get(lookup['source_column'])), [])
            if len(matches) != 1 or not _text(matches[0]['values'].get(lookup['value_column'])):
                issues.append('Reference mapping is missing or ambiguous.')
            else:
                if other.get('coverage', {}).get('complete') is not True:
                    issues.append('Reference source coverage is incomplete or unconfirmed.')
                refrow = matches[0]
                formula = refrow.get('metadata', {}).get('cells', {}).get(lookup['value_column'], {}).get('formula')
                if formula and not formula.get('cache_verified'):
                    issues.append('Reference mapping formula has not been verified.')
                resolved[lookup['target']] = refrow['values'][lookup['value_column']]
                lookup_refs.append(_source(other, refrow))
        account = _text(resolved.get('account') or get('account') or explicit.get('account') or suggestion.get('context', {}).get('account'))
        currency = _text(resolved.get('currency') or get('currency') or explicit.get('currency') or suggestion.get('context', {}).get('currency')).upper()
        if not account:
            issues.append('Bank account is missing.')
        if not currency:
            issues.append('Currency is missing.')
        try:
            date = _date(get('date'), explicit.get('date_format'))
        except ValueError as exc:
            date = _text(get('date')); issues.append(str(exc))
        record = {'refs': [_source(table, row)], 'side': table['side'], 'account': account,
                  'currency': currency, 'date': date, 'reference': _text(resolved.get('reference') or get('reference')), 'mapping_evidence': lookup_refs,
                  'batch': _text(get('batch')), 'amount': amount, 'issues': sorted(set(issues))}
        records.append(record)
        coverage['transaction_rows'] += 1
    return records, coverage


def _item(left, right, status, reason):
    records = left + right
    first = records[0]
    def total(group):
        return None if not group or any(r['amount'] is None for r in group) else sum((r['amount'] for r in group), Decimal(0))
    la, ra = total(left), total(right)
    return {'id': _hash([[r['refs'] for r in left], [r['refs'] for r in right]]),
            'match_key': _hash([first['account'], first['currency'], first['reference']]) if first['reference'] else None,
            'status': status, 'reason': reason,
            'statement': [ref for r in left for ref in r['refs']],
            'journal': [ref for r in right for ref in r['refs']],
            **{k: first[k] for k in ('account', 'currency', 'date', 'reference')},
            'statement_amount': str(la) if la is not None else None,
            'journal_amount': str(ra) if ra is not None else None,
            'difference': str(la - ra) if la is not None and ra is not None else None,
            'issues': sorted({issue for r in records for issue in r['issues']}),
            'mapping_evidence': [ref for r in records for ref in r.get('mapping_evidence', [])],
            'supporting_evidence': [ref for r in records for ref in r.get('supporting_evidence', [])]}


def reconcile(envelopes, config=None):
    """Compare immutable envelope values; source edits/authorization live in services."""
    with localcontext() as context:
        context.prec = 100
        return _reconcile(envelopes, config or {})


def _reconcile(envelopes, config):
    suggestions = propose(envelopes, config)['suggestions']
    all_records, coverage = [], []
    for table, suggestion in zip(envelopes, suggestions):
        records, table_coverage = _records(table, suggestion, config, envelopes)
        all_records.extend(records); coverage.append(table_coverage)
    present = {_identity(table) for table in envelopes}
    for mapping in config.get('mappings', []):
        selected = set(mapping.get('dataset_ids', [])) or {mapping.get('dataset_id')}
        if not mapping.get('exclude') and selected - present:
            coverage.append({'dataset_id': mapping.get('dataset_id'), 'total_rows': 0, 'transaction_rows': 0, 'excluded_rows': 0, 'unclassified_rows': 0, 'header_rows': 0, 'issues': ['A selected transaction table is unavailable in this revision.']})
    items, available = [], []
    for record in all_records:
        if record['issues']:
            items.append(_item([record] if record['side'] == 'statement' else [],
                               [record] if record['side'] == 'journal' else [], 'needs_input',
                               record['issues'][0]))
        else:
            available.append(record)
    # Grouping is opt-in and only under an explicit journal batch key.
    if config.get('group_batches_confirmed'):
        grouped = defaultdict(list)
        ungrouped = []
        for record in available:
            if record['side'] == 'journal' and record['batch']:
                grouped[(record['account'], record['currency'], record['batch'])].append(record)
            else:
                ungrouped.append(record)
        for group in grouped.values():
            if len({r['reference'] for r in group}) != 1 or len({r['date'] for r in group}) != 1:
                items.append(_item([], group, 'needs_input', 'Batch contains conflicting dates or references.'))
            else:
                ungrouped.append({**group[0], 'amount': sum((r['amount'] for r in group), Decimal(0)),
                                  'refs': [ref for r in group for ref in r['refs']]})
        available = ungrouped
    grouped = defaultdict(lambda: {'statement': [], 'journal': []})
    for record in available:
        if record['reference'] and config.get('match_mode') != 'composite':
            key = ('reference', record['account'], record['currency'], record['reference'])
        elif config.get('composite_confirmed') and record['date']:
            key = ('composite', record['account'], record['currency'], record['date'])
        else:
            items.append(_item([record] if record['side'] == 'statement' else [],
                               [record] if record['side'] == 'journal' else [], 'needs_input',
                               'No unique reference; confirm the fallback matching rule.'))
            continue
        grouped[key][record['side']].append(record)
    tolerance = _decimal(config.get('tolerance', '0'))
    if tolerance < 0:
        raise ValueError('Tolerance cannot be negative.')
    unresolved_coverage = any(c['unclassified_rows'] or c['issues'] for c in coverage) or any(r['issues'] for r in all_records)
    for group_key, group in grouped.items():
        left, right = group['statement'], group['journal']
        if group_key[0] == 'composite' and left and right:
            # Accept only mutually unique candidates; no greedy order-dependent assignment.
            sorted_right = sorted((r['amount'], j) for j,r in enumerate(right))
            right_amounts = [amount for amount,_ in sorted_right]
            left_amounts = sorted(r['amount'] for r in left)
            candidates = {}
            for i, record in enumerate(left):
                low = bisect_left(right_amounts, record['amount'] - tolerance)
                high = bisect_right(right_amounts, record['amount'] + tolerance)
                candidates[i] = (high - low, sorted_right[low][1] if high - low == 1 else None)
            reverse = {j: bisect_right(left_amounts, r['amount'] + tolerance) - bisect_left(left_amounts, r['amount'] - tolerance) for j,r in enumerate(right)}
            pairs = [(i, candidate) for i, (count,candidate) in candidates.items() if count == 1 and reverse[candidate] == 1]
            used_left, used_right = {i for i, _ in pairs}, {j for _, j in pairs}
            for i, j in pairs:
                items.append(_item([left[i]], [right[j]], 'matched', 'Unique account, currency, date and amount match under the confirmed fallback rule.'))
            remaining_left = [r for i, r in enumerate(left) if i not in used_left]
            remaining_right = [r for j, r in enumerate(right) if j not in used_right]
            if remaining_left or remaining_right:
                ambiguous_left = [r for i,r in enumerate(left) if i not in used_left and candidates[i][0]]
                ambiguous_right = [r for j,r in enumerate(right) if j not in used_right and reverse[j]]
                if ambiguous_left or ambiguous_right:
                    items.append(_item(ambiguous_left, ambiguous_right, 'needs_input', 'Multiple records share this matching key; no match was selected.'))
                for record in remaining_left + remaining_right:
                    if record in ambiguous_left or record in ambiguous_right:
                        continue
                    status = 'needs_input' if unresolved_coverage else 'missing'
                    items.append(_item([record] if record['side'] == 'statement' else [], [record] if record['side'] == 'journal' else [], status, 'No unique amount match under the confirmed fallback rule.'))
            continue
        if len(left) > 1 or len(right) > 1:
            items.append(_item(left, right, 'needs_input', 'Multiple records share this matching key; no match was selected.'))
        elif left and right:
            difference = left[0]['amount'] - right[0]['amount']
            status = 'matched' if abs(difference) <= tolerance else 'difference'
            items.append(_item(left, right, status, 'Amounts agree under the selected rule.' if status == 'matched' else 'Statement and journal amounts differ.'))
        else:
            status = 'needs_input' if unresolved_coverage else 'missing'
            items.append(_item(left, right, status, 'Other inputs need review before absence can be established.' if unresolved_coverage else 'No corresponding record exists on the other side.'))
    counts = Counter(item['status'] for item in items)
    return {'suggestions': suggestions, 'items': items,
            'summary': {**{key: counts[key] for key in ('matched', 'difference', 'missing', 'needs_input')},
                        'statement_records': sum(len(i['statement']) for i in items),
                        'journal_records': sum(len(i['journal']) for i in items),
                        'financially_verified': False},
            'coverage': coverage}
