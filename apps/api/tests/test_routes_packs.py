import json

from closegraph.api.app import create_app
from closegraph.api.ports import DomainConflict, DomainNotFound
from closegraph.contracts import PackSnapshot
from test_access_sessions import S, auth, login
from test_routes_client import ASGIClient


class RecordingFacade:
    """Only a port-contract double; never proof of domain integration."""
    def __init__(self): self.calls=[]
    def get_pack(self, scope, actor):
        self.calls.append(("get",scope,actor))
        return PackSnapshot(pack_id=scope.pack_id,version=1,fund_id=scope.fund_id,title="Synthetic contract test",
                            execution_status="PENDING",checks=[],routing_status="BLOCKED",review_status="PENDING",
                            freshness="CURRENT",facts=[],candidate=None,history=[])
    def correct(self, scope, actor, command):
        self.calls.append(("correct",scope,actor,command)); return self.get_pack(scope,actor)
    def recompute(self, scope, actor, command): raise DomainConflict("stale version")
    def review(self, scope, actor, command):
        self.calls.append(("review",scope,actor,command)); return self.get_pack(scope,actor)
    def publish(self, scope, actor, command): raise DomainConflict("required check not run")
    def download(self, scope, actor, artifact_id): raise DomainNotFound()


def test_health_is_honest_without_facade():
    c=ASGIClient(create_app(auth=auth()))
    status,_,body=c.request("GET","/api/health")
    assert status == 200 and json.loads(body)=={"status":"ok","service":"closegraph-api","domain_services":"unconfigured"}
    login(c)
    assert c.request("GET","/api/packs")[0] == 503


def test_scope_every_pack_action_and_count_without_existence_leaks():
    facade=RecordingFacade(); c=ASGIClient(create_app(auth=auth(),services=facade)); csrf,_=login(c)
    status,_,body=c.request("GET","/api/packs")
    assert status==200 and len(json.loads(body))==1
    for path in ["/api/packs/other", "/api/packs/other/artifacts/private/download"]:
        assert c.request("GET",path)[0] == 404
    command={"fact_id":"0001","value_decimal":"0.00","reason":"source-backed repair","source_id":"doc","expected_version":1}
    assert c.request("POST","/api/packs/other/corrections",command,{"x-csrf-token":csrf})[0]==404
    assert len(facade.calls)==1 and facade.calls[0][1]==S
    assert c.request("POST","/api/packs/pack/corrections",command)[0]==403
    assert c.request("POST","/api/packs/pack/corrections",command,{"x-csrf-token":csrf})[0]==200
    assert facade.calls[-2][3].value_decimal.as_tuple().exponent==-2
    assert c.request("POST","/api/packs/pack/recompute",{"expected_version":1},{"x-csrf-token":csrf})[0]==409


def test_clients_cannot_grant_roles_pass_flags_or_review():
    f=RecordingFacade(); c=ASGIClient(create_app(auth=auth(),services=f)); csrf,_=login(c)
    headers={"x-csrf-token":csrf}
    assert c.request("POST","/api/packs/pack/publish",{"expected_version":1,"passed":True},headers)[0]==422
    assert c.request("POST","/api/packs/pack/review",{"expected_version":1,"note":"reviewed","attested":True},headers)[0]==403
    assert not any(call[0]=="review" for call in f.calls)
    c=ASGIClient(create_app(auth=auth(),services=f)); csrf,_=login(c,"reviewer","another-test-password")
    assert c.request("POST","/api/packs/pack/review",{"expected_version":1,"note":"checked evidence","attested":True},{"x-csrf-token":csrf})[0]==200
    assert f.calls[-2][2].role == "REVIEWER"


def test_download_bytes_are_attachment_and_conflicts_are_domain_owned():
    from closegraph.api.ports import ArtifactDownload
    class Files(RecordingFacade):
        def download(self, scope, actor, artifact_id):
            self.calls.append(("download", scope, actor, artifact_id))
            return ArtifactDownload(content=b"synthetic artifact\n", filename="odd\r\nname.csv", media_type="text/csv")
    f = Files(); c = ASGIClient(create_app(auth=auth(), services=f)); csrf, _ = login(c)
    status, headers, body = c.request("GET", "/api/packs/pack/artifacts/a/download")
    assert status == 200 and body == b"synthetic artifact\n"
    assert headers["content-disposition"].startswith("attachment;")
    assert "\r" not in headers["content-disposition"] and "\n" not in headers["content-disposition"]
    assert headers["x-content-type-options"] == "nosniff" and headers["cache-control"] == "no-store"
    assert f.calls[-1][1] == S and f.calls[-1][2].actor_id == "preparer"
    assert c.request("POST", "/api/packs/pack/publish", {"expected_version":1}, {"x-csrf-token":csrf})[0] == 409


def test_body_cannot_override_scopes_or_smuggle_check_authority():
    f = RecordingFacade(); c = ASGIClient(create_app(auth=auth(), services=f)); csrf, _ = login(c)
    command={"fact_id":"0001", "value_decimal":"0.00", "reason":"source-backed repair", "source_id":"doc", "expected_version":1}
    for injected in [{"role":"REVIEWER"}, {"tenant_id":"other"}, {"passed":True}, {"actor_id":"reviewer"}, {"scope":S.model_dump()}]:
        assert c.request("POST", "/api/packs/pack/corrections", command|injected, {"x-csrf-token":csrf})[0] == 422
    assert f.calls == []


def test_review_work_endpoints_preserve_scope_csrf_and_server_identity():
    class Activity(RecordingFacade):
        def record_review_event(self, scope, actor, command):
            self.calls.append(("activity",scope,actor,command))
            return {"event_id":"event","event_type":command.event_type}
        def review_work(self,scope,actor):
            self.calls.append(("work",scope,actor))
            return {"provenance":"LOCAL_OBSERVED","total_events":0}
    f=Activity();c=ASGIClient(create_app(auth=auth(),services=f));csrf,_=login(c)
    command={"event_type":"VALUE_INSPECTED","observed_snapshot_version":1,"fact_id":"fee"}
    assert c.request("POST","/api/packs/pack/review-events",command)[0]==403
    assert c.request("POST","/api/packs/other/review-events",command,{"x-csrf-token":csrf})[0]==404
    assert c.request("GET","/api/packs/other/review-work")[0]==404
    assert not f.calls
    assert c.request("POST","/api/packs/pack/review-events",command|{"actor_id":"reviewer"},{"x-csrf-token":csrf})[0]==422
    assert c.request("POST","/api/packs/pack/review-events",command,{"x-csrf-token":csrf})[0]==201
    assert f.calls[-1][1]==S and f.calls[-1][2].actor_id=="preparer"
    assert c.request("GET","/api/packs/pack/review-work")[0]==200
