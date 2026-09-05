from dagster import Definitions,define_asset_job,in_process_executor
from closegraph.pipeline.assets import processing_input,native_evaluation,review_snapshot
from closegraph.pipeline.resources import services_resource,RunScopedJSONIOManager
from closegraph.pipeline.sensors import dispatch_sensor,request_config


def build_definitions(services,io_dir):
    job=define_asset_job('process_reporting_pack',selection=[processing_input,native_evaluation,review_snapshot],executor_def=in_process_executor)
    return Definitions(assets=[processing_input,native_evaluation,review_snapshot],jobs=[job],sensors=[dispatch_sensor(job,services)],resources={'services':services_resource(services),'io_manager':RunScopedJSONIOManager(io_dir)})


def run_request(definitions,instance,request):
    return definitions.resolve_job_def('process_reporting_pack').execute_in_process(instance=instance,run_config=request_config(request),tags={'closegraph/request':request['request_id'],'closegraph/attempt':'0'})
