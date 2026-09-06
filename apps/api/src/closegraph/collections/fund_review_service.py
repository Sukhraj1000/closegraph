"""A scoped reporting review over immutable collection evidence.

Checks describe a selected review scope, never certification of a fund's accounts.
Dagster performs extraction and evaluation; this service records authority and versions.
"""
from copy import deepcopy
from datetime import datetime
from html import escape
import json
from uuid import uuid4

from closegraph.api.ports import DomainConflict, DomainForbidden, DomainNotFound
from .documents import current_sources
from .reconciliation import fingerprint, stamp


class FundReviewMixin:
    def _fund_review_fingerprint(self, state):
        sources = current_sources(state)
        ids = {s['id'] for s in sources}
        return fingerprint({
            'sources': [{k: s.get(k) for k in ('id', 'content_hash', 'status', 'coverage', 'parser', 'completeness_verified_hash')} for s in sources],
            'tables': [(d['id'], d['data_hash']) for d in state['datasets'] if d.get('source_id') in ids and d['kind'] == 'extraction'],
            'config': state.get('fund_review', {}).get('config', {}),
            'requirements': state.get('requirements', []),
            'requirements_version': state.get('requirements_version', 0),
        })

    def _invalidate_fund_review(self, state):
        review = state.get('fund_review')
        if not review:
            return
        previous = review.pop('review', None)
        if previous and previous.get('decision') == 'APPROVE':
            self._reconciliation_notice(state, 'fund_review_invalidated',
                'Reviewed reporting evidence changed. Check the revised brief.',
                [previous['actor_id']], previous['fingerprint'])
        review['status'] = 'STALE'

    def fund_review_start(self, identity, actor, expected, config, reason, idempotency_key=None):
        if not isinstance(config, dict) or len(json.dumps(config, allow_nan=False)) > 150000:
            raise ValueError('The review configuration is too large')
        checks = config.get('checks', [])
        if not isinstance(checks, list) or len(checks) > 100 or any(not isinstance(c, dict) or not isinstance(c.get('id'), str) or not c['id'].strip() for c in checks):
            raise ValueError('Choose up to 100 named checks')
        for check in checks:
            if any(name in check and not isinstance(check[name], dict) for name in ('left', 'right')):
                raise ValueError('Choose a table and columns for each side of a check')
            if 'confirmed' in check and type(check['confirmed']) is not bool:
                raise ValueError('Check confirmation must be true or false')
            for side in (check.get('left', {}), check.get('right', {})):
                if side.get('number_format') not in (None, 'dot_decimal', 'comma_decimal'):
                    raise ValueError('Choose a supported number format')
        headers = config.get('table_headers', [])
        if not isinstance(headers, list) or len(headers) > 10000 or any(not isinstance(h, dict) or not isinstance(h.get('dataset_id'), str) or h.get('header_row_id') is not None and not isinstance(h.get('header_row_id'), str) for h in headers):
            raise ValueError('Choose valid table headers')
        confirmed = config.get('confirmed_source_ids', [])
        if not isinstance(confirmed, list) or not all(isinstance(v, str) for v in confirmed):
            raise ValueError('Choose the original documents whose extraction you checked')
        if len({c['id'] for c in checks}) != len(checks):
            raise ValueError('Each check must have a different identifier')
        if not reason.strip():
            raise ValueError('Explain this review change')
        with self._locked(identity, actor, 'history') as (session, row, state):
            digest = fingerprint([config, reason])
            key = 'fund-review:' + idempotency_key if idempotency_key else None
            if key and key in state['idempotency']:
                receipt = state['idempotency'][key]
                if receipt['actor_id'] != actor or receipt['fingerprint'] != digest:
                    raise DomainConflict('Retry key belongs to a different submission')
                return self._public(state, actor)
            if expected != state['version']:
                raise DomainConflict('This review changed. Refresh before continuing.')
            self._idle(state)
            if not current_sources(state):
                raise DomainConflict('Upload the reporting pack or supporting evidence first')
            previous = state.get('fund_review', {})
            if previous.get('config') != config:
                self._invalidate_fund_review(state)
                state['contributors'] = sorted(set(state.get('contributors', [])) | {actor})
            state['fund_review'] = {**previous, 'config': deepcopy(config), 'status': 'QUEUED',
                'requested_by': actor, 'requested_at': stamp()}
            state['status'] = 'QUEUED'
            if key:
                state['idempotency'][key] = {'actor_id': actor, 'fingerprint': digest}
            self._revision(session, row, state, actor, 'fund_review_requested', {'reason': reason, 'config': deepcopy(config)})
            self._queue(session, row, state, 'fund_review')
            return self._public(state, actor)

    def _rebind_fund_review(self, state):
        """Reuse columns only when a unique table retains its explicit header meaning."""
        review = state['fund_review']
        sources = {s['id']: s for s in state['sources']}
        replacements, headers = {}, {}
        for old in state.get('retired_datasets', []):
            document = sources.get(old.get('source_id'), {}).get('document_id')
            candidates = [d for d in state['datasets'] if d['kind'] == 'extraction'
                and sources.get(d.get('source_id'), {}).get('document_id') == document
                and d['title'] == old['title'] and d['columns'] == old['columns']]
            if len(candidates) != 1:
                continue
            old_table, new_table = self._table(state, old), self._table(state, candidates[0])
            old_rows, new_rows = old_table.get('rows', []), new_table.get('rows', [])
            sides = [c[k] for c in review.get('config', {}).get('checks', []) for k in ('left', 'right')
                if isinstance(c.get(k), dict) and c[k].get('dataset_id') == old['id']]
            sides += [c for c in review.get('config', {}).get('table_headers', []) if c.get('dataset_id') == old['id']]
            requested = {c.get('header_row_id') for c in sides if 'header_row_id' in c}
            if not requested:
                requested = {old_rows[0]['row_id']} if old_rows else set()
            consistent = bool(requested)
            for header in requested:
                if header is None:
                    # Column positions in a headerless revision cannot establish
                    # unchanged business meaning. Ask for confirmation again.
                    consistent = False
                    break
                previous = next((r for r in old_rows if r['row_id'] == header), None)
                matches = [r for r in new_rows[:30] if previous and r['values'] == previous['values']]
                if len(matches) != 1:
                    consistent = False
                    break
                headers[(old['id'], header)] = matches[0]['row_id']
            if consistent:
                replacements[old['id']] = candidates[0]['id']
        def walk(value):
            if isinstance(value, list):
                return [walk(x) for x in value]
            if isinstance(value, dict):
                result = {k: walk(v) for k, v in value.items()}
                old = value.get('dataset_id')
                if old in replacements:
                    result['dataset_id'] = replacements[old]
                    if (old, value.get('header_row_id')) in headers:
                        result['header_row_id'] = headers[(old, value.get('header_row_id'))]
                return result
            return value
        previous = review.get('config', {})
        review['config'] = walk(previous)
        if previous != review['config']:
            review['mapping_rebindings'] = [{'from': k, 'to': v, 'basis': 'Same logical document, unique table, column schema and unchanged header values'} for k, v in replacements.items()]

    def _fund_rule_signatures(self, state, envelopes=()):
        sources = {s['id']: s for s in state['sources']}
        tables = {d['id']: d for d in [*state.get('retired_datasets', []), *state['datasets']]}
        cache = {t['dataset_id']: t for t in envelopes}
        table_headers = {c['dataset_id']: c.get('header_row_id') for c in state['fund_review'].get('config', {}).get('table_headers', [])}
        def semantic(value):
            if isinstance(value, list):
                return [semantic(v) for v in value]
            if isinstance(value, dict):
                result = {k: semantic(v) for k, v in value.items() if k not in ('rationale', 'overlap', 'title', 'header_row_id')}
                if value.get('dataset_id') in tables:
                    table = tables[value['dataset_id']]
                    result['dataset_id'] = [sources.get(table.get('source_id'), {}).get('document_id'), table['title'], table['columns']]
                    header = value.get('header_row_id', table_headers.get(value['dataset_id'], 'unconfirmed'))
                    result['header_selection'] = 'unconfirmed' if header == 'unconfirmed' else 'no header' if header is None else 'explicit row'
                    if header not in (None, 'unconfirmed'):
                        if value['dataset_id'] not in cache:
                            cache[value['dataset_id']] = self._table(state, table)
                        rows = cache[value['dataset_id']]['rows']
                        result['header'] = next((r['values'] for r in rows if r['row_id'] == header), 'missing header')
                return result
            return value
        return {c['id']: fingerprint(semantic(c)) for c in state['fund_review'].get('config', {}).get('checks', [])}

    def _compute_fund_review(self, state):
        from .fund_review import analyze
        review = state['fund_review']
        old = self._fund_review_result(state) if review.get('result_hash') else None
        self._rebind_fund_review(state)
        envelopes = []
        sources = current_sources(state)
        index = {s['id']: s for s in sources}
        for dataset in state['datasets']:
            source = index.get(dataset.get('source_id'))
            if not source or dataset['kind'] != 'extraction':
                continue
            table = self._table(state, dataset)
            envelopes.append({**table, 'dataset_id': dataset['id'], 'source_id': source['id'],
                'document_id': source['document_id'], 'filename': source['filename'],
                'coverage': source.get('coverage', {}), 'media_type': source['media_type'],
                'parser': source.get('parser', {}), 'accepted': dataset['accepted'],
                'extraction_confirmed': source.get('completeness_verified') is True and source.get('completeness_verified_hash') == source['content_hash']})
        result = analyze(envelopes, review.get('config', {}))
        result['rule_version'] = 'fund-review-v1'
        result['rule_signatures'] = self._fund_rule_signatures(state, envelopes)
        result['config'] = deepcopy(review.get('config', {}))
        result['source_versions'] = [{k: s.get(k) for k in ('id', 'document_id', 'filename', 'content_hash', 'parser', 'coverage', 'uploaded_by', 'uploaded_at', 'revision_number')} for s in sources]
        failed = [s for s in sources if s['status'] != 'EXTRACTED' or not s.get('coverage', {}).get('complete')]
        coverage = result.setdefault('coverage', {})
        coverage['documents'] = [{'source_id': s['id'], 'filename': s['filename'], 'status': s['status'],
            'complete': s.get('coverage', {}).get('complete') is True, 'parser': s.get('parser', {})} for s in sources]
        coverage['completed_documents'] = sum(s['status'] == 'EXTRACTED' for s in sources)
        coverage['total_documents'] = len(sources)
        for source in sources:
            key = 'source-' + fingerprint(source['document_id'])[:20]
            result.setdefault('condition_outcomes', {})[key] = {'kind': 'coverage', 'passed': source['status'] == 'EXTRACTED' and source.get('coverage', {}).get('complete') is True, 'reason': 'Current logical document extraction coverage'}
        if failed:
            coverage['complete'] = False
            for source in failed:
                key = 'source-' + fingerprint(source['document_id'])[:20]
                result['findings'].append({'id': key, 'match_key': key, 'status': 'needs_input', 'kind': 'coverage',
                    'title': 'Check ' + source['filename'], 'explanation': 'This document could not be read completely. Retry processing or upload a corrected version before relying on dependent checks.',
                    'affected_count': 1, 'evidence': [{'source_id': source['id'], 'document_id': source['document_id']} ]})
        summary = result.setdefault('summary', {})
        for status in ('difference', 'needs_input', 'passed'):
            summary[status] = sum(f['status'] == status for f in result['findings'])
        summary['financial_verified'] = False
        digest = self._fund_review_fingerprint(state)
        result['changes'] = old.get('changes', {}) if old and digest == review.get('fingerprint') else self._fund_changes(old, result)
        result['scope_note'] = 'These results cover the selected checks only. They do not establish NAV, fees, valuations, legal compliance or the correctness of every transaction.'
        key = self._store(state, result)
        if review.get('review') and (review['review'].get('fingerprint') != digest or review['review'].get('result_hash') != key):
            self._invalidate_fund_review(state)
        review.update(status='COMPLETE', result_hash=key, fingerprint=digest, summary=summary,
            coverage=coverage, changes={k: v for k, v in result['changes'].items() if k != 'items'}, completed_at=stamp(), version=state['version'])
        state['status'] = 'NEEDS_REVIEW'
        state['financial_verified'] = False
        for task in state['tasks']:
            if task.get('requirement_id') == 'missing_check_policy':
                task['active'] = False
                task['allowed_actions'] = []
        if state.get('requirements'):
            self._evaluate_state(state)
        self._sync_fund_review_requests(state, result)
        return state

    @staticmethod
    def _fund_changes(old, new):
        if not old:
            return {'available': False, 'fixed': 0, 'outstanding': 0, 'new': 0, 'withdrawn': 0, 'items': []}
        previous = {f.get('match_key', f['id']): f for f in old['findings'] if f['status'] != 'passed'}
        current = {f.get('match_key', f['id']): f for f in new['findings'] if f['status'] != 'passed'}
        passed_keys = {f.get('match_key', f['id']) for f in new['findings'] if f['status'] == 'passed'}
        valid_checks = {f.get('check_id') for f in new['findings'] if f['status'] == 'passed'}
        uncertain_checks = {f.get('check_id') for f in new['findings'] if f['status'] != 'passed'}
        counts = {'available': True, 'fixed': 0, 'outstanding': 0, 'new': 0, 'withdrawn': 0, 'items': []}
        for key, finding in previous.items():
            check = finding.get('check_id')
            same_rule = check and old.get('rule_signatures', {}).get(check) == new.get('rule_signatures', {}).get(check)
            condition = new.get('condition_outcomes', {}).get(key)
            if key in current:
                status = 'outstanding'
            elif finding.get('kind') in ('coverage', 'configuration') and condition and condition.get('passed') is True:
                status = 'fixed'
            elif same_rule and (key in passed_keys or finding.get('kind') != 'totals' and check in valid_checks and check not in uncertain_checks):
                status = 'fixed'
            else:
                status = 'withdrawn' if check not in new.get('rule_signatures', {}) else 'outstanding'
            counts[status] += 1
            counts['items'].append({'status': status, 'title': finding['title'], 'before': finding, 'after': current.get(key)})
        for key, finding in current.items():
            if key not in previous:
                counts['new'] += 1
                counts['items'].append({'status': 'new', 'title': finding['title'], 'before': None, 'after': finding})
        return counts

    def _fund_review_result(self, state):
        review = state.get('fund_review', {})
        if not review.get('result_hash'):
            raise DomainConflict('The review brief is still being prepared')
        return json.loads(self._blobs(state).get(review['result_hash']))

    def fund_review_results(self, identity, actor, status=None, q='', offset=0, limit=50):
        with self._locked(identity, actor, 'history') as (_, _, state):
            result = self._fund_review_result(state)
            findings = result.pop('findings', [])
            if status:
                findings = [f for f in findings if f['status'] == status]
            if q:
                findings = [f for f in findings if q.casefold() in json.dumps(f, ensure_ascii=False).casefold()]
            # Detailed history/evaluation payloads stay in their scoped immutable blobs.
            for source in result.get('source_versions', []):
                source.pop('content_hash', None)
            result.pop('rule_signatures', None)
            changes = result.get('changes', {})
            changes['total'] = len(changes.get('items', []))
            changes['items'] = changes.get('items', [])[:50]
            return {**result, 'findings': findings[offset:offset + limit], 'total': len(findings), 'offset': offset,
                'limit': limit, 'stale': state['fund_review']['status'] != 'COMPLETE' or state['fund_review'].get('fingerprint') != self._fund_review_fingerprint(state), 'version': state['version']}

    def fund_review_assign(self, identity, actor, expected, item_ids, owner_actor_id, reason, due_at=None):
        from .workflow import _actions, _event, _notify
        if not reason.strip():
            raise ValueError('Explain what information or correction is needed')
        if due_at:
            try:
                if datetime.fromisoformat(due_at.replace('Z', '+00:00')).tzinfo is None:
                    raise ValueError()
            except (ValueError, TypeError):
                raise ValueError('Deadline must include a timezone')
        with self._locked(identity, actor, 'history', expected) as (session, row, state):
            self._idle(state)
            result = self._current_fund_result(state)
            selected = [f for f in result['findings'] if f['id'] in item_ids and f['status'] != 'passed']
            if not selected or len(selected) != len(set(item_ids)):
                raise ValueError('Select current unresolved findings')
            member = next((m for m in state['members'] if m['actor_id'] == owner_actor_id), None)
            if not member:
                raise ValueError('Choose an assigned participant')
            if any(f['status'] == 'needs_input' for f in selected) and member['party'] not in ('accountant', 'account_manager'):
                raise ValueError('Uncertain extraction or interpretation must be checked internally first')
            signature = fingerprint([sorted(item_ids), owner_actor_id, reason, due_at, state['fund_review']['fingerprint']])
            if any(t.get('assignment_key') == signature for t in state['tasks']):
                return self._public(state, actor)
            task = {'id': 'task-' + uuid4().hex, 'kind': 'fund_review', 'title': selected[0]['title'] if len(selected) == 1 else str(len(selected)) + ' reporting findings need review',
                'description': reason, 'message': reason, 'owner_actor_id': owner_actor_id, 'owner_party': member['party'],
                'created_by': actor, 'created_at': stamp(), 'updated_at': stamp(), 'cycle': 1, 'active': True, 'blocking': True,
                'status': 'pending_manager_release' if member['party'] == 'investor' else 'open', 'document_ids': [],
                'due_at': due_at, 'escalate_after_days': 0, 'events': [], 'item_ids': list(item_ids),
                'match_keys': [f.get('match_key', f['id']) for f in selected], 'assignment_key': signature,
                'check_ids': sorted({f['check_id'] for f in selected if f.get('check_id')}),
                'rule_signatures': result.get('rule_signatures', {}), 'item_kinds': {f.get('match_key', f['id']): f.get('kind') for f in selected}, 'evaluation_fingerprint': state['fund_review']['fingerprint']}
            task['allowed_actions'] = _actions(task)
            _event(task, 'created', actor, stamp(), reason)
            state['tasks'].append(task)
            _notify(state, task, 'manager_release_required' if member['party'] == 'investor' else 'assigned', stamp())
            self._revision(session, row, state, actor, 'fund_review_assigned', {'task_id': task['id'], 'item_ids': item_ids, 'owner_actor_id': owner_actor_id, 'reason': reason})
            return self._public(state, actor)

    def _sync_fund_review_requests(self, state, result):
        from .workflow import _actions, _event, _notify
        index = {f.get('match_key', f['id']): f for f in result['findings']}
        certain = {f.get('check_id') for f in result['findings'] if f['status'] == 'passed'}
        uncertain = {f.get('check_id') for f in result['findings'] if f['status'] != 'passed'}
        for task in state['tasks']:
            if task.get('kind') != 'fund_review':
                continue
            keys, checks = task.get('match_keys', []), task.get('check_ids', [])
            linked = [index[k] for k in keys if k in index]
            rules_same = all(task.get('rule_signatures', {}).get(c) == result.get('rule_signatures', {}).get(c) for c in checks)
            explicit_passes = bool(keys) and all(k in index and index[k]['status'] == 'passed' for k in keys)
            whole_check_passes = bool(checks) and all(c in certain and c not in uncertain for c in checks) and not any(k not in index and task.get('item_kinds', {}).get(k) == 'totals' for k in keys)
            structural = bool(keys) and all(task.get('item_kinds', {}).get(k) in ('coverage', 'configuration') and result.get('condition_outcomes', {}).get(k, {}).get('passed') is True for k in keys)
            passed = structural or rules_same and (explicit_passes or whole_check_passes) and all(k not in index or index[k]['status'] == 'passed' for k in keys)
            outcome = fingerprint([rules_same, [(f.get('match_key', f['id']), f['status'], f.get('observed'), f.get('expected'), f.get('affected_count'), f.get('explanation')) for f in linked]])
            task['item_ids'] = [f['id'] for f in linked]
            if passed and task['status'] != 'resolved':
                task['status'] = 'resolved'
                task['resolved_at'] = stamp()
                _event(task, 'verification_passed', 'system', stamp(), 'The linked finding cleared when the same check ran on current evidence.')
                _notify(state, task, 'resolved', stamp(), [task['owner_actor_id'], task.get('created_by', task['owner_actor_id'])])
            elif not passed and (task['status'] == 'resolved' or task.get('outcome_fingerprint') and task['outcome_fingerprint'] != outcome):
                task['cycle'] += 1
                task['status'] = 'pending_manager_release' if task['owner_party'] == 'investor' else 'open'
                for k in ('released_at', 'released_by', 'resolved_at', 'overdue', 'escalated'):
                    task.pop(k, None)
                _event(task, 'material_change', 'system', stamp(), 'The finding, check or evidence changed. Review is still required.')
                _notify(state, task, 'material_change', stamp())
            task['outcome_fingerprint'] = outcome
            task['allowed_actions'] = _actions(task)

    def _current_fund_result(self, state):
        review = state.get('fund_review', {})
        if review.get('status') != 'COMPLETE' or review.get('fingerprint') != self._fund_review_fingerprint(state):
            raise DomainConflict('Wait for a fresh review of the current evidence')
        return self._fund_review_result(state)

    def _fund_review_gate(self, state):
        result = self._current_fund_result(state)
        checks = state['fund_review'].get('config', {}).get('checks', [])
        if not checks or any(c.get('confirmed') is not True for c in checks):
            raise DomainConflict('Confirm the intended review checks before approving the brief')
        if not result.get('findings') or any(f['status'] != 'passed' for f in result['findings']):
            raise DomainConflict('Resolve the outstanding findings before approving this review scope')
        if result.get('coverage', {}).get('complete') is not True:
            raise DomainConflict('Complete source coverage is required before approval')
        if any(t.get('active', True) and t.get('blocking') and t['status'] != 'resolved' for t in state['tasks']):
            raise DomainConflict('Resolve blocking requests before approval')
        if state.get('requirements'):
            from .workflow import evaluate_requirements
            fresh = evaluate_requirements(state, lambda d: self._table(state, d), stamp())
            if any(r.get('blocking', True) and not any(c.get('requirement_id') == r['id'] and c.get('outcome', c.get('status')) == 'PASS' for c in fresh) for r in state['requirements']):
                raise DomainConflict('Required evidence or financial checks remain incomplete')
        return result

    def fund_review_review(self, identity, actor, expected, decision, reason):
        if not reason.strip():
            raise ValueError('Record what was independently reviewed')
        with self._locked(identity, actor, 'review', expected) as (session, row, state):
            self._idle(state)
            if actor in state.get('contributors', []):
                raise DomainForbidden()
            result = self._fund_review_gate(state) if decision == 'APPROVE' else self._current_fund_result(state)
            review = state['fund_review']
            review['review'] = {'decision': decision, 'actor_id': actor, 'reason': reason, 'at': stamp(),
                'fingerprint': review['fingerprint'], 'result_hash': review['result_hash'], 'scope': result.get('scope_note')}
            self._reconciliation_notice(state, 'fund_review_reviewed', 'Reporting review ' + ('approved for the selected checks' if decision == 'APPROVE' else 'returned for correction'),
                [m['actor_id'] for m in state['members'] if m['party'] == 'accountant'], fingerprint(review['review']))
            self._revision(session, row, state, actor, 'fund_review_reviewed', review['review'])
            return self._public(state, actor)

    def fund_review_download(self, identity, actor, reviewed=False):
        with self._locked(identity, actor, 'release') as (session, row, state):
            result = self._current_fund_result(state)
            review = state['fund_review']
            if reviewed:
                self._fund_review_gate(state)
                approval = review.get('review', {})
                if approval.get('decision') != 'APPROVE' or approval.get('fingerprint') != review['fingerprint'] or approval.get('result_hash') != review['result_hash']:
                    raise DomainConflict('Independent approval of this exact review brief is required')
            def text(value):
                return escape('' if value is None else str(value))
            status_label = 'Reviewed for the selected checks' if reviewed else 'Working review — unresolved findings may remain'
            lines = ['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CloseGraph reporting review</title><style>body{font:16px/1.55 system-ui,sans-serif;color:#172b31;max-width:1000px;margin:48px auto;padding:0 24px}h1{font-size:36px}h2{margin-top:36px}article{border-top:1px solid #d6dfdd;padding:18px 0}small{color:#4b646c}table{border-collapse:collapse;width:100%;margin:12px 0}th,td{text-align:left;padding:8px;border-bottom:1px solid #d6dfdd;vertical-align:top;overflow-wrap:anywhere}aside{background:#eef3f0;padding:18px}a{color:#176855}@media print{body{margin:0}article{break-inside:avoid}}</style><body>',
                '<small>CLOSEGRAPH · FUND REPORTING REVIEW</small><h1>' + text(state['title']) + '</h1>',
                '<aside><strong>' + status_label + '</strong><p>' + text(result.get('scope_note')) + '</p></aside>',
                '<p>Prepared ' + text(review.get('completed_at')) + '. Original Excel files and formulas are unchanged.</p>', '<h2>Sources</h2><ul>']
            for s in result.get('source_versions', []):
                parser = s.get('parser') or {}
                lines.append('<li>' + text(s['filename']) + ' · version ' + text(s.get('revision_number', 1)) + ' · ' + text(parser.get('mode', parser.get('name', 'native extraction'))) + '</li>')
            lines.append('</ul><h2>Selected checks</h2><ul>')
            for check in review.get('config', {}).get('checks', []):
                lines.append('<li>' + text(check.get('title', check.get('kind'))) + ' · ' + ('confirmed' if check.get('confirmed') is True else 'needs confirmation') + '</li>')
            lines.append('</ul><h2>Findings and supporting evidence</h2>')
            sources = {s['id']: s['filename'] for s in current_sources(state)}
            for f in result['findings']:
                label = {'difference': 'Difference', 'needs_input': 'Needs your input', 'passed': 'Selected check passed'}.get(f['status'], f['status'])
                lines.append('<article><small>' + label + '</small><h3>' + text(f['title']) + '</h3><p>' + text(f.get('explanation')) + '</p>')
                if f.get('expected') is not None or f.get('observed') is not None:
                    lines.append('<p>Expected: ' + text(f.get('expected')) + '<br>Observed: ' + text(f.get('observed')) + '</p>')
                evidence = f.get('evidence', [])
                if evidence:
                    lines.append('<table><thead><tr><th>Source</th><th>Location</th><th>Value</th></tr></thead><tbody>')
                    for e in evidence:
                        loc = e.get('locator') or {}
                        location = (str(loc.get('sheet', '')) + ' ' + str(loc.get('cell', loc.get('cell_ref', loc.get('cell_address', ''))))).strip() if isinstance(loc, dict) else str(loc)
                        if not location:
                            location = 'Page ' + str(loc['page']) if isinstance(loc, dict) and loc.get('page') else str(e.get('row_number', e.get('row_id', 'See original source')))
                        lines.append('<tr><td>' + text(sources.get(e.get('source_id'), e.get('title', 'Source evidence'))) + '</td><td>' + text(location) + '</td><td>' + text(e.get('raw_value', e.get('value'))) + '</td></tr>')
                    lines.append('</tbody></table>')
                lines.append('</article>')
            changes = result.get('changes', {})
            if changes.get('available'):
                lines.append('<h2>Since the previous evaluation</h2><p>' + ' · '.join(text(changes.get(k, 0)) + ' ' + k for k in ('fixed', 'outstanding', 'new', 'withdrawn')) + '</p>')
            if reviewed:
                lines.append('<h2>Independent review</h2><p>' + text(review['review']['reason']) + '</p><small>' + text(review['review']['actor_id']) + ' · ' + text(review['review']['at']) + '</small>')
            lines.append('</body></html>')
            content = ''.join(lines).encode()
            self._revision(session, row, state, actor, 'fund_review_downloaded', {'reviewed': reviewed, 'result_hash': review['result_hash'], 'fingerprint': review['fingerprint']})
            return content, 'text/html', ('reviewed' if reviewed else 'working') + '-fund-review.html'
