from dataclasses import replace
import json
import pytest
from closegraph.outputs.manifest import verify_manifest, build_manifest
from closegraph.services.errors import DomainError
from .lifecycle_support import synthetic_service, repair, approve


def test_manifest_resolves_evidence_checks_and_integrity():
    s=synthetic_service(); state=approve(s,repair(s)); s.publish("synthetic-pack",expected_version=state["version"],actor="reviewer",scope="synthetic-fund")
    data=s.download("synthetic-pack",actor="reviewer",scope="synthetic-fund"); m=json.loads(data.manifest)
    assert verify_manifest(m,data.artifact)
    assert {f["fact_id"] for f in m["facts"]} == {"gross","fee"}
    assert m["sources"] and all(c["status"] == "PASS" for c in m["checks"])
    with pytest.raises(DomainError): verify_manifest(m,b"bad")
    state=s.repository.get("synthetic-pack","synthetic-fund"); state["evidence"]={}
    with pytest.raises(DomainError): build_manifest(state,data.artifact,state["approval"])
