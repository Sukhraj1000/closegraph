from io import BytesIO
import json
import pytest
from openpyxl import load_workbook
from closegraph.services.errors import DomainError
from .lifecycle_support import synthetic_service, repair, approve


def test_real_publication_download_and_idempotent_retry():
    s=synthetic_service(); state=approve(s,repair(s)); version=state["version"]
    published=s.publish("synthetic-pack",expected_version=version,actor="reviewer",scope="synthetic-fund")
    repeat=s.publish("synthetic-pack",expected_version=version,actor="reviewer",scope="synthetic-fund")
    assert repeat == published
    download=s.download("synthetic-pack",actor="reviewer",scope="synthetic-fund")
    assert load_workbook(BytesIO(download.artifact))["Pack"]["B4"].value == 990
    manifest=json.loads(download.manifest)
    assert manifest["review"]["actor"] == "reviewer"
    assert manifest["artifact_sha256"] == published["candidate"]["artifact_id"]
    assert download.freshness == "CURRENT"
    assert len([h for h in published["history"] if h["action"] == "PUBLISHED"]) == 1


@pytest.mark.parametrize("kind", ["unapproved","missing","corrupt","evidence","permission","cross-scope"])
def test_publication_hard_denials(kind):
    s=synthetic_service(); state=repair(s)
    if kind != "unapproved": state=approve(s,state)
    if kind == "missing": del s.blobs.data[state["candidate"]["artifact_id"]]
    if kind == "corrupt": s.blobs.data[state["candidate"]["artifact_id"]]=b"corrupt"
    if kind == "evidence": del s.blobs.data[s.repository.get("synthetic-pack","synthetic-fund")["evidence"]["fee-source"]["content_hash"]]
    if kind == "permission": s.authorizer.revoke("reviewer")
    with pytest.raises(DomainError): s.publish("synthetic-pack",expected_version=state["version"],actor="reviewer",scope="other" if kind == "cross-scope" else "synthetic-fund")


def test_historical_download_remains_permissioned_and_stale():
    s=synthetic_service(); state=approve(s,repair(s)); state=s.publish("synthetic-pack",expected_version=state["version"],actor="reviewer",scope="synthetic-fund")
    original=s.download("synthetic-pack",actor="reviewer",scope="synthetic-fund")
    s.invalidate("synthetic-pack",expected_version=state["version"],actor="preparer",scope="synthetic-fund",changes={"rule_version":"v2"},reason="rule revision")
    historical=s.download("synthetic-pack",actor="reviewer",scope="synthetic-fund",publication_id=state["publication"]["publication_id"])
    assert historical.artifact == original.artifact and historical.freshness == "STALE"
    with pytest.raises(DomainError): s.download("synthetic-pack",actor="reviewer",scope="other",publication_id=state["publication"]["publication_id"])
