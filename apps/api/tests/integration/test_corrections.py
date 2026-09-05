import pytest
from closegraph.services.lifecycle import LifecycleService, MemoryRepository, MemoryBlobs, DomainError, Conflict
from .lifecycle_support import synthetic_service


def test_failed_then_successful_repair_preserves_history_and_output():
    service = synthetic_service()
    initial = service.inspect("synthetic-pack", actor="preparer", scope="synthetic-fund")
    assert initial["routing_status"] == "BLOCKED"
    bad = service.correct("synthetic-pack", actor="preparer", scope="synthetic-fund", expected_version=initial["version"], fact_id="fee", value_decimal="9", reason="Check against source fee", source_id="fee-source")
    assert bad["freshness"] == "STALE"
    bad = service.recompute("synthetic-pack", expected_version=bad["version"], actor="preparer", scope="synthetic-fund")
    assert bad["execution_status"] == "COMPLETED"
    assert bad["routing_status"] == "BLOCKED"
    assert bad["candidate"] is None
    with pytest.raises(DomainError):
        service.review("synthetic-pack", expected_version=bad["version"], note="waive", attested=True, actor="reviewer", scope="synthetic-fund")
    fixed = service.correct("synthetic-pack", actor="preparer", scope="synthetic-fund", expected_version=bad["version"], fact_id="fee", value_decimal="10.00", reason="Read declared source fee", source_id="fee-source")
    fixed = service.recompute("synthetic-pack", expected_version=fixed["version"], actor="preparer", scope="synthetic-fund")
    assert fixed["routing_status"] == "READY_FOR_QUICK_REVIEW"
    assert fixed["candidate"]["total_decimal"] == "990.00"
    assert fixed["review_status"] == "PENDING"
    assert initial["facts"][1]["value_decimal"] == "20.00"
    assert service.repository.get("synthetic-pack", "synthetic-fund", version=1)["checks"][0]["status"] == "FAIL"
    assert any(h["action"] == "CORRECTED" and h["before"] == "20.00" for h in fixed["history"])


@pytest.mark.parametrize("field,value", [("reason", ""), ("source_id", "missing"), ("value_decimal", "NaN"), ("value_decimal", 0.1), ("fact_id", "missing"), ("scope", "other-fund"), ("actor", "reviewer")])
def test_correction_denials(field, value):
    s = synthetic_service()
    args=dict(actor="preparer",scope="synthetic-fund",expected_version=1,fact_id="fee",value_decimal="10",reason="source fee",source_id="fee-source")
    args[field]=value
    with pytest.raises(DomainError): s.correct("synthetic-pack", **args)
    assert s.inspect("synthetic-pack",actor="preparer",scope="synthetic-fund")["version"] == 1


def test_cas_rejects_old_correction():
    s=synthetic_service()
    kwargs=dict(actor="preparer",scope="synthetic-fund",expected_version=1,fact_id="fee",value_decimal="10",reason="source fee",source_id="fee-source")
    s.correct("synthetic-pack",**kwargs)
    with pytest.raises(Conflict): s.correct("synthetic-pack",**kwargs)
