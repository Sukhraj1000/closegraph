"""Committed outbox dispatch with Dagster-backed stable run identities."""
from dagster import sensor, RunRequest, DefaultSensorStatus, RunsFilter


def request_config(request):
    return {'ops': {'processing_input': {'config': {**request['scope'], 'request_id': request['request_id']}}}}


def dispatch_sensor(job, services):
    @sensor(job=job, minimum_interval_seconds=5, default_status=DefaultSensorStatus.RUNNING)
    def committed_processing_requests(context):
        for request in services.pending_requests(limit=30):
            key = request['request_id']
            runs = context.instance.get_runs(filters=RunsFilter(tags={'closegraph/request': key}), limit=20)
            if any(not run.is_finished for run in runs):
                continue
            attempt = max((int(run.tags.get('closegraph/attempt', '0')) for run in runs), default=-1) + 1
            previous = request.get('dagster_run_id')
            if previous:
                owner = context.instance.get_run_by_id(previous)
                # An absent owner may be alive in another Dagster instance. Never steal it.
                if owner is None or not owner.is_finished:
                    continue
            if attempt > 2:
                # A run can fail before its first asset claims the outbox row. Claim
                # the terminal result under an observed, finished attempt in that case.
                owner_id = previous or max(runs, key=lambda run: int(run.tags.get('closegraph/attempt', '0'))).run_id
                if previous or services.claim_processing(request['scope'], key, owner_id):
                    services.complete_processing(request['scope'], key, {
                        'execution_error': 'Bounded Dagster recovery exhausted; explicit recompute required'
                    }, owner_id)
                continue
            if previous and not services.release_processing(request['scope'], key, previous):
                continue
            yield RunRequest(run_key=key + ':' + str(attempt), run_config=request_config(request),
                             tags={'closegraph/request': key, 'closegraph/attempt': str(attempt)})
    return committed_processing_requests
