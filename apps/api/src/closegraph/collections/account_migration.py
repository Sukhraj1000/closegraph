"""One-time local account rename. Evidence and immutable history are never rewritten."""
from copy import deepcopy
from sqlalchemy import select
from closegraph.api.ports import DomainConflict
from .models import CollectionRow, CollectionJobRow
from .presentation import canonical_actor, actor_name

# Only application-owned identity metadata. Never traverse document values,
# recipes, operands, parser output, user replies or source contents.
ACTOR_FIELDS = {'actor_id', 'actor', 'owner_actor_id', 'verifier_actor_id',
                'recipient_actor_id', 'recipient', 'created_by', 'updated_by',
                'uploaded_by', 'accepted_by', 'submitted_by', 'prepared_by', 'requested_by',
                'approved_by', 'rule_approved_by', 'released_by', 'resolved_by'}
CONTAINERS = {'members', 'sources', 'documents', 'revisions', 'tasks', 'events',
              'notifications', 'history', 'requirements', 'params', 'review',
              'fund_review', 'reconciliation', 'evidence_links', 'attachments',
              'replies', 'decisions', 'comparisons', 'check_results', 'detail',
              'parameters', 'completeness_review', 'datasets', 'steps', 'issues', 'resolution'}

def renamed_metadata(value):
    result = deepcopy(value)
    if isinstance(result, list):
        return [renamed_metadata(item) for item in result]
    if not isinstance(result, dict):
        return result
    for key, item in result.items():
        if key in ACTOR_FIELDS and isinstance(item, str):
            result[key] = canonical_actor(item)
        elif key == 'contributors' and isinstance(item, list):
            result[key] = [canonical_actor(actor) for actor in item]
        elif key in CONTAINERS:
            result[key] = renamed_metadata(item)
        elif key == 'idempotency' and isinstance(item, dict):
            result[key] = {token: renamed_metadata(receipt) for token, receipt in item.items()}
    if 'actor_id' in result and 'display_name' in result:
        result['display_name'] = actor_name(result['actor_id'])
    return result


def migrate_business_accounts(service):
    """Append updated heads transactionally before accepting new sessions/jobs."""
    changed = []
    with service.sessions() as session, session.begin():
        rows = session.scalars(select(CollectionRow).order_by(CollectionRow.id).with_for_update()).all()
        pending = session.scalar(select(CollectionJobRow.id).where(CollectionJobRow.status.in_(['PENDING', 'RUNNING'])).limit(1))
        for row in rows:
            previous = deepcopy(row.state)
            state = renamed_metadata(previous)
            if state == previous:
                continue
            if pending:
                raise DomainConflict('Finish active document processing before updating accounts')
            ids = [m['actor_id'] for m in state.get('members', [])]
            if len(ids) != len(set(ids)):
                raise DomainConflict('Existing account memberships conflict with the account update')
            service._initialize(state)
            # Changing a rule's responsible people changes its exact fingerprint.
            # Keep evidence/results, but require fresh evaluation and approval.
            if state.get('requirements') != previous.get('requirements'):
                state['requirements_version'] = state.get('requirements_version', 0) + 1
                service._invalidate_fund_review(state)
                service._invalidate_reconciliation(state)
            if state.get('review'):
                state['review'] = None
                if state.get('status') == 'APPROVED':
                    state['status'] = 'READY_FOR_REVIEW'
            service._revision(session, row, state, 'system', 'accounts_updated',
                              {'reason': 'Business accounts now own existing work; source files and original history are preserved.'})
            changed.append(row.id)
    return changed
