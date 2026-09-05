"""Dagster owns collection computation; human review creates a new request."""
from dagster import asset, define_asset_job, in_process_executor, sensor, DefaultSensorStatus, RunsFilter, RunRequest, RetryPolicy

@asset(required_resource_keys={'services'},config_schema={'job_id':str},retry_policy=RetryPolicy(max_retries=1,delay=1))
def collection_input(context):
    return context.resources.services.collections.claim(context.op_execution_context.op_config['job_id'],context.run.run_id)

@asset(required_resource_keys={'services'})
def collection_processing(context,collection_input):
    if collection_input is None:return None
    try:result=context.resources.services.collections.compute(collection_input)
    except Exception as exc:result={'execution_error':type(exc).__name__+': '+str(exc)[:1000]}
    # This stage persists immutable table objects; I/O is scoped to the run.
    return {'job_id':collection_input['id'],'result':result}

@asset(required_resource_keys={'services'},retry_policy=RetryPolicy(max_retries=1,delay=1))
def collection_review_snapshot(context,collection_processing):
    if collection_processing is None:return {'applied':False}
    result=context.resources.services.collections.finish(collection_processing['job_id'],context.run.run_id,collection_processing['result'])
    context.add_output_metadata({k:v for k,v in result.items() if v is not None})
    return result


def collection_definitions(services):
    assets=[collection_input,collection_processing,collection_review_snapshot]
    job=define_asset_job('process_collection',selection=assets,executor_def=in_process_executor)
    @sensor(job=job,minimum_interval_seconds=5,default_status=DefaultSensorStatus.RUNNING)
    def collection_requests(context):
        services.collections.sweep_deadlines()
        for request in services.collections.pending():
            key=request['id'];runs=context.instance.get_runs(filters=RunsFilter(tags={'closegraph/collection-request':key}),limit=10)
            if any(not run.is_finished for run in runs):continue
            previous=request['run_id']
            if previous:
                owner=context.instance.get_run_by_id(previous)
                if owner is None or not owner.is_finished:continue
            attempt=max((int(run.tags.get('closegraph/attempt','0')) for run in runs),default=-1)+1
            if attempt>2:
                owner=previous or runs[0].run_id
                services.collections.release_failed_run(key,owner,terminal=True);continue
            if previous:services.collections.release_failed_run(key,previous)
            yield RunRequest(run_key=key+':'+str(attempt),run_config={'ops':{'collection_input':{'config':{'job_id':key}}}},tags={'closegraph/collection-request':key,'closegraph/attempt':str(attempt)})
    return assets,job,collection_requests
