"""Snapshot-addressed stages. Negative financial results are successful processing."""
from copy import deepcopy

from dagster import Backoff, RetryPolicy, asset

from closegraph.contracts import Scope
from closegraph.extraction.common import ExtractionError
from closegraph.services.native import evaluate_pack, ingest_sources
from closegraph.services.repository import ScopedBlobs

RETRY=RetryPolicy(max_retries=2,delay=1,backoff=Backoff.EXPONENTIAL)
CONFIG={'tenant_id':str,'fund_id':str,'pack_id':str,'request_id':str}


@asset(required_resource_keys={'services'},config_schema=CONFIG,retry_policy=RETRY)
def processing_input(context):
    config=context.op_execution_context.op_config; scope=Scope(**{k:config[k] for k in ('tenant_id','fund_id','pack_id')})
    services=context.resources.services
    claimed=services.claim_processing(scope,config['request_id'],context.run.run_id)
    if not claimed: return {'claimed':False,'scope':scope.model_dump(),'request_id':config['request_id']}
    loaded=services.load_processing(scope,config['request_id'])
    context.add_output_metadata({'request_id':config['request_id'],'snapshot_version':loaded['state']['version']})
    # Original bytes are recovered by content address at extraction; no latest-document singleton.
    loaded.pop('content',None)
    return {**loaded,'claimed':True,'scope':scope.model_dump()}


@asset(required_resource_keys={'services'},retry_policy=RETRY)
def native_evaluation(context,processing_input):
    if not processing_input['claimed']: return processing_input
    scope=Scope(**processing_input['scope']); state=deepcopy(processing_input['state'])
    blobs=ScopedBlobs(context.resources.services.blob_store,scope)
    try:
        patch=ingest_sources(state,blobs,scope=scope,pdf_evidence=getattr(context.resources.services,'pdf_evidence',None)) if processing_input['stage']=='ingest' else {}
        state.update(patch)
        result={**patch,**evaluate_pack(state,blobs)}
    except ExtractionError as error:
        result={'execution_error':error.code}
    return {**processing_input,'result':result}


@asset(required_resource_keys={'services'},retry_policy=RETRY)
def review_snapshot(context,native_evaluation):
    if not native_evaluation['claimed']:return {'applied':False,'already_processed':True}
    result=context.resources.services.complete_processing(native_evaluation['scope'],native_evaluation['request_id'],native_evaluation['result'],context.run.run_id)
    state=result['state']; context.add_output_metadata({'applied':result['applied'],'routing_status':state.routing_status,'execution_status':state.execution_status,'snapshot_version':state.version})
    return {'applied':result['applied'],'state':state.model_dump(mode='json')}
