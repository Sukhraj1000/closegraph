"""Canonical interpretation changes append new fact versions in PostgreSQL."""
import base64
from copy import deepcopy

import pytest
from sqlalchemy import select

from closegraph.api.auth import DevAccount,LocalAuth
from closegraph.api.ports import Actor
from closegraph.api.services import PostgreSQLPackServices
from closegraph.contracts import Scope,UploadRequest,ConfigurationChangeRequest
from closegraph.fixtures import SCOPE,fixture_bytes
from closegraph.runtime import empty_state
from closegraph.services.errors import Conflict
from closegraph.services.native import evaluate_pack,ingest_sources
from closegraph.services.repository import ScopedBlobs
from closegraph.storage.blobs import LocalBlobStore
from closegraph.storage.models import FactVersionRow


@pytest.fixture
def native_application(pg_sessions,tmp_path):
    scope=Scope(**SCOPE); actor=Actor(actor_id="preparer",role="PREPARER")
    auth=LocalAuth(accounts=[DevAccount.create(actor.actor_id,"synthetic-test-password",actor.role,[scope])])
    service=PostgreSQLPackServices(pg_sessions,LocalBlobStore(tmp_path/"blobs"),auth,evaluate_pack)
    state=service.create_pack(scope,actor,empty_state())
    for role,name in (("capital","capital.csv"),("fee-rule","fee-rule.csv"),("original","original.xlsx")):
        state=service.upload(scope,actor,UploadRequest(expected_version=state.version,idempotency_key=role,
            source_id=role,filename=name,media_type="text/csv" if name.endswith(".csv") else
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            content_base64=base64.b64encode(fixture_bytes()[name]).decode()))
    for request in service.pending_requests():
        execute_ingestion(service,scope,request["request_id"])
    return service,scope,actor


def execute_ingestion(service,scope,request_id):
    loaded=service.load_processing(scope,request_id);blobs=ScopedBlobs(service.blob_store,scope)
    patch=ingest_sources(loaded["state"],blobs)
    result={**patch,**evaluate_pack({**loaded["state"],**patch},blobs)}
    assert service.claim_processing(scope,request_id,"run-"+request_id)
    return service.complete_processing(scope,request_id,result,"run-"+request_id)["state"]


def test_unsupported_mapping_versions_interpretations_without_mutating_canonical_history(native_application):
    service,scope,actor=native_application
    state=service.get_pack(scope,actor)
    with service.sessions() as session:
        repository,_=service._service(session,scope)
        original=repository.get(scope.pack_id,scope.fund_id)
    assert all(f["interpretation_status"]=="RULE_MAPPED" for f in original["facts"])
    template=deepcopy(original["template"])
    changed=service.invalidate(scope,actor,ConfigurationChangeRequest(expected_version=state.version,
        changes={"mapping_version":"unsupported-native-v2","mappings":{"version":"unsupported-native-v2","template":template},
                 "template":template},reason="Record unsupported configured mapping without inferring its meaning"))
    service.upload(scope,actor,UploadRequest(expected_version=changed.version,idempotency_key="capital-new",
        source_id="capital",filename="capital.csv",media_type="text/csv",
        content_base64=base64.b64encode(fixture_bytes()["capital.csv"]).decode()))
    request=service.pending_requests()[-1]
    current=execute_ingestion(service,scope,request["request_id"])
    assert current.execution_status=="COMPLETED" and current.routing_status=="BLOCKED" and current.candidate is None
    assert all(f.interpretation_status=="UNRESOLVED" for f in current.facts)
    with service.sessions() as session:
        rows=session.scalars(select(FactVersionRow).filter_by(**scope.model_dump()).order_by(FactVersionRow.fact_id,FactVersionRow.version)).all()
        by_fact={}
        for row in rows: by_fact.setdefault(row.fact_id,[]).append(row)
        for fact in current.facts:
            versions=by_fact[fact.fact_id]
            assert [v.version for v in versions]==[1,2], (fact.fact_id,[(v.version,v.interpretation_status) for v in versions])
            assert versions[0].interpretation_status=="RULE_MAPPED"
            assert versions[1].interpretation_status=="UNRESOLVED"
            assert versions[1].interpretation_rule_id is None
            assert versions[1].supersedes==fact.fact_id+":v1"
            assert fact.fact_version==2
        repository,_=service._service(session,scope)
        snapshot=repository.get(scope.pack_id,scope.fund_id)
    repeated=ingest_sources(snapshot,ScopedBlobs(service.blob_store,scope))
    assert all(f["fact_version"]==2 and f["interpretation_status"]=="UNRESOLVED" for f in repeated["facts"])


@pytest.mark.parametrize("field,value",[
    ("interpretation_status","UNRESOLVED"),("interpretation_rule_id","different-rule"),
    ("observation_ids",["different-observation"]),("value_state","AMBIGUOUS"),
    ("correction_id","different-correction"),("supersedes",99),
    ("source_locator",{"kind":"csv","row":999,"column":"value"}),
])
def test_same_fact_version_cannot_silently_change_interpretation_or_provenance(native_application,field,value):
    service,scope,actor=native_application
    with pytest.raises(Conflict,match="fact version"):
        with service.sessions.begin() as session:
            repository,_=service._service(session,scope)
            repository.lock()
            state=repository.get(scope.pack_id,scope.fund_id)
            if field=="source_locator":
                state["facts"][0]["source"]["locator"]=value
            else:
                state["facts"][0][field]=value
            service._event(repository,state,actor.actor_id,"TEST_CONFLICT")
