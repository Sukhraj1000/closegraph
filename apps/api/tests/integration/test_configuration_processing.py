"""Actual native evaluator keeps configured authority through durable recompute."""
import base64
from copy import deepcopy

from closegraph.api.auth import DevAccount,LocalAuth
from closegraph.api.ports import Actor
from closegraph.api.services import PostgreSQLPackServices
from closegraph.contracts import Scope,UploadRequest,ConfigurationChangeRequest
from closegraph.fixtures import SCOPE,fixture_bytes
from closegraph.runtime import empty_state
from closegraph.services.native import evaluate_pack,ingest_sources
from closegraph.services.repository import ScopedBlobs
from closegraph.storage.blobs import LocalBlobStore


def test_native_evaluator_honors_configured_rule_and_keeps_exact_new_record(pg_sessions,tmp_path):
    scope=Scope(**SCOPE)
    actor=Actor(actor_id="preparer",role="PREPARER")
    auth=LocalAuth(accounts=[DevAccount.create(actor.actor_id,"preparer-test-password",actor.role,[scope])])
    service=PostgreSQLPackServices(pg_sessions,LocalBlobStore(tmp_path/"blobs"),auth,evaluate_pack)
    state=service.create_pack(scope,actor,{**empty_state(),"priority_policy":{
        "version":"synthetic-review-priority-v1","materiality_decimal":"50000","currency":"GBP","impact_threshold":2}})
    for role,name in (("capital","capital.csv"),("fee-rule","fee-rule.csv"),("original","original.xlsx")):
        state=service.upload(scope,actor,UploadRequest(expected_version=state.version,idempotency_key=role,
            source_id=role,filename=name,media_type="text/csv" if name.endswith(".csv") else
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            content_base64=base64.b64encode(fixture_bytes()[name]).decode()))
    # Drive the real worker-facing claim/complete API, with canonical native
    # extraction and evaluator output; no fake pass result is introduced.
    for request in service.pending_requests():
        loaded=service.load_processing(scope,request["request_id"])
        parsed=ingest_sources(loaded["state"],ScopedBlobs(service.blob_store,scope))
        evaluated=evaluate_pack({**loaded["state"],**parsed},ScopedBlobs(service.blob_store,scope))
        run="native-"+request["request_id"]
        assert service.claim_processing(scope,request["request_id"],run)
        service.complete_processing(scope,request["request_id"],{**parsed,**evaluated},run)
    state=service.get_pack(scope,actor)
    assert state.routing_explanation["route"]=="BLOCKED"
    assert state.routing_explanation["reasons"][0]=="required_check:fee:FAIL"
    assert state.routing_explanation["required_check_coverage"]==[6,7]
    assert state.routing_explanation["agreement"]=="NOT_RUN"
    assert state.routing_explanation["confidence"]["status"]=="NOT_APPLICABLE"
    assert state.priority["status"]=="AVAILABLE" and state.priority["level"]=="HIGH"
    assert state.priority["amount_decimal"]=="75000" and state.priority["currency"]=="GBP"
    assert state.priority["policy_version"]=="synthetic-review-priority-v1"
    assert state.priority["dependent_outputs"]==1 and state.review_status=="PENDING"
    with service.sessions() as session:
        repository,_=service._service(session,scope)
        before=repository.get(scope.pack_id,scope.fund_id)
    rule={**before["rule"],"version":"approved-native-rule-revoked-v2","approved":False,
          "revocation_reason":"Synthetic authority changed"}
    command=ConfigurationChangeRequest(expected_version=state.version,changes={"rule":rule,"rule_version":rule["version"]},
        reason="Apply the complete changed governing rule")
    state=service.invalidate(scope,actor,command)
    request=service.pending_requests()[0]
    loaded=service.load_processing(scope,request["request_id"])
    assert loaded["state"]["rule"]==rule
    evaluated=evaluate_pack(loaded["state"],ScopedBlobs(service.blob_store,scope))
    fee=next(check for check in evaluated["checks"] if check["id"]=="fee")
    assert fee["status"]=="UNKNOWN" and fee["rule_version"]==rule["version"]
    assert service.claim_processing(scope,request["request_id"],"configured-rule")
    completed=service.complete_processing(scope,request["request_id"],evaluated,"configured-rule")["state"]
    assert completed.routing_status=="BLOCKED" and completed.candidate is None
    assert next(check for check in completed.checks if check.id=="evidence").status=="FAIL"
    with service.sessions() as session:
        repository,_=service._service(session,scope)
        after=repository.get(scope.pack_id,scope.fund_id)
    assert after["rule"]==rule and after["rule_version"]==rule["version"]
    assert after["mapping_version"]==before["mapping_version"] and after["policy_version"]==before["policy_version"]

    # Even a later unrelated source receipt cannot silently restore fixture
    # authority. The commit boundary rejects any worker output with old config.
    old_rule=deepcopy(before["rule"])
    current=service.get_pack(scope,actor)
    service.upload(scope,actor,UploadRequest(expected_version=current.version,idempotency_key="capital-v2",
        source_id="capital",filename="capital.csv",media_type="text/csv",
        content_base64=base64.b64encode(fixture_bytes()["capital.csv"]).decode()))
    request=service.pending_requests()[0]
    assert service.claim_processing(scope,request["request_id"],"old-default-config")
    wrong=service.complete_processing(scope,request["request_id"],{"rule":old_rule,"rule_version":old_rule["version"]},
        "old-default-config")["state"]
    assert wrong.execution_status=="FAILED" and wrong.routing_status=="BLOCKED" and wrong.candidate is None
    assert "pinned server configuration" in wrong.execution_error
    with service.sessions() as session:
        repository,_=service._service(session,scope)
        retained=repository.get(scope.pack_id,scope.fund_id)
    assert retained["rule"]==rule and retained["configured_records"]["rule"]==rule
