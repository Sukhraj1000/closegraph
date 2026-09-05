import pytest
from closegraph.services.errors import DomainError
from .lifecycle_support import synthetic_service, repair


def test_independent_review_and_attestation_required():
    s=synthetic_service(); state=repair(s)
    for actor,note,attested in [("preparer","checked",True),("reviewer","",True),("reviewer","checked",False)]:
        with pytest.raises(DomainError): s.review("synthetic-pack",expected_version=state["version"],note=note,attested=attested,actor=actor,scope="synthetic-fund")
    result=s.review("synthetic-pack",expected_version=state["version"],note="Compared source and candidate",attested=True,actor="reviewer",scope="synthetic-fund")
    assert result["review_status"] == "APPROVED"
    assert result["checks"] == state["checks"]

@pytest.mark.parametrize("change", ["source_versions","rule_version","policy_version","mapping_version","dependency_coverage"])
def test_version_writers_stale_approval(change):
    s=synthetic_service(); state=repair(s)
    state=s.review("synthetic-pack",expected_version=state["version"],note="source checked",attested=True,actor="reviewer",scope="synthetic-fund")
    value={"fee-source":"v2"} if change == "source_versions" else False if change == "dependency_coverage" else "v2"
    changed=s.invalidate("synthetic-pack",expected_version=state["version"],actor="preparer",scope="synthetic-fund",changes={change:value},reason="new observed configuration")
    assert changed["review_status"] == "PENDING" and changed["freshness"] == "STALE"
    with pytest.raises(DomainError): s.publish("synthetic-pack",expected_version=changed["version"],actor="reviewer",scope="synthetic-fund")
