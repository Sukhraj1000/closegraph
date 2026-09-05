import base64,json
from io import BytesIO
from openpyxl import load_workbook
from dagster import DagsterInstance
from closegraph.api.auth import DevAccount,LocalAuth
from closegraph.api.ports import Actor
from closegraph.api.services import PostgreSQLPackServices
from closegraph.contracts import Scope,UploadRequest,CorrectionRequest,ReviewRequest,VersionAction
from closegraph.fixtures import SCOPE,fixture_bytes
from closegraph.runtime import empty_state
from closegraph.pipeline.definitions import build_definitions, run_request
from closegraph.services.native import evaluate_pack
from closegraph.storage.blobs import LocalBlobStore


def test_real_dagster_native_sources_failed_then_repaired_and_published(pg_sessions,tmp_path):
    scope=Scope(**SCOPE); preparer=Actor(actor_id='preparer',role='PREPARER'); reviewer=Actor(actor_id='reviewer',role='REVIEWER')
    auth=LocalAuth(accounts=[DevAccount.create(a.actor_id,a.actor_id+'-test-password',a.role,[scope]) for a in (preparer,reviewer)])
    service=PostgreSQLPackServices(pg_sessions,LocalBlobStore(tmp_path/'blobs'),auth,evaluate_pack)
    state=service.create_pack(scope,preparer,empty_state())
    files=fixture_bytes()
    for role,name in [('capital','capital.csv'),('fee-rule','fee-rule.csv'),('original','original.xlsx')]:
        state=service.upload(scope,preparer,UploadRequest(expected_version=state.version,idempotency_key=role,source_id=role,filename=name,media_type='text/csv' if name.endswith('.csv') else 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',content_base64=base64.b64encode(files[name]).decode()))
    definitions=build_definitions(service,str(tmp_path/'io'))
    with DagsterInstance.ephemeral(tempdir=str(tmp_path)) as instance:
        for request in service.pending_requests():
            result=run_request(definitions,instance,request)
            assert result.success
        state=service.get_pack(scope,preparer)
        assert state.execution_status=='COMPLETED' and state.routing_status=='BLOCKED'
        assert next(c for c in state.checks if c.id=='fee').status=='FAIL'
        for metric,expected_route in [('fee','BLOCKED'),('statement_fee','READY_FOR_QUICK_REVIEW')]:
            source_id=next(key for key,evidence in state.evidence.items() if metric in evidence.get('fact_ids',[]) and evidence.get('source_id')=='fee-rule')
            state=service.correct(scope,preparer,CorrectionRequest(expected_version=state.version,fact_id=metric,value_decimal='60000',reason='Synthetic approved capital and rate yield 60,000',source_id=source_id))
            assert state.execution_status=='PENDING'
            for request in service.pending_requests():assert run_request(definitions,instance,request).success
            state=service.get_pack(scope,preparer)
            assert state.routing_status==expected_route, state.model_dump()
    state=service.review(scope,reviewer,ReviewRequest(expected_version=state.version,note='Compared exact source anchors and both revised output cells',attested=True))
    state=service.publish(scope,reviewer,VersionAction(expected_version=state.version))
    book=load_workbook(BytesIO(service.download(scope,reviewer,state.candidate.artifact_id).content))
    assert book['Pack']['B6'].value==book['Pack']['B7'].value==book['Pack']['B8'].value==60000
    manifest=json.loads(service.download(scope,reviewer,state.publication['manifest_id']).content)
    assert manifest['artifact_sha256']==state.candidate.artifact_id and manifest['sources']
