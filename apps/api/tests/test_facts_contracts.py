import json
from decimal import Decimal

import pytest
from closegraph.contracts import (
    Confidence,
    ExtractionObservation,
    FactVersion,
    PdfLocator,
    Scope,
    SourceRef,
)
from pydantic import ValidationError


def source():
    return {"document_version_id": "doc-001", "content_hash": "a" * 64,
                "locator": {"kind": "csv", "row": 2, "column": "amount"},
                "context_evidence_ids": ["currency-heading", "period-heading"]}


def fact(**changes):
    data = {"scope": {"tenant_id":"t", "fund_id":"f", "pack_id":"p"},
                "fact_id": "0007", "version": 1, "metric": "nav", "entity_id": "0012", "period": "2026-Q2",
                "value_decimal": "12345678901234567890.12345678901234567890", "currency": "GBP",
                "raw_value": "12.3m", "raw_scale": "millions", "source": source(),
                "value_state": "PRESENT", "interpretation_status": "UNRESOLVED", "observation_ids": ["o1"]}
    return FactVersion(**(data | changes))


def test_exact_decimal_and_identifiers_roundtrip():
    f = fact()
    data = json.loads(f.model_dump_json())
    assert data["value_decimal"] == "12345678901234567890.12345678901234567890"
    assert data["entity_id"] == "0012"
    assert FactVersion.model_validate_json(f.model_dump_json()) == f
    assert fact(value_decimal="0").value_decimal == Decimal(0)
    assert fact(value_decimal=None, value_state="MISSING").value_decimal is None


@pytest.mark.parametrize("value", [1.1, 1, True, "NaN", "Infinity", "1e3", " 1.00", "", "1,000", ".5"])
def test_reject_lossy_or_noncanonical_decimal(value):
    with pytest.raises(ValidationError): fact(value_decimal=value)


def test_missing_is_not_zero_or_fabricated_pass():
    for changes in [{"value_decimal": None}, {"value_decimal": "0", "value_state": "MISSING"},
                    {"entity_id": 12}, {"passed": True}, {"currency": "gbp"}]:
        with pytest.raises(ValidationError): fact(**changes)


def test_locators_and_source_hash_validate_not_repair():
    with pytest.raises(ValidationError): SourceRef(**(source() | {"content_hash": "A"*64}))
    with pytest.raises(ValidationError): PdfLocator(kind="pdf", original_page=0, coordinate_system="normalised-0-1", bbox=[0,0,1,1])
    with pytest.raises(ValidationError): PdfLocator(kind="pdf", original_page=1, coordinate_system="normalised-0-1", bbox=[0.8,0,0.2,1])
    with pytest.raises(ValidationError): PdfLocator(kind="pdf", original_page=1, coordinate_system="normalised-0-1", bbox=[0,0,2,1])
    assert Scope(tenant_id="t", fund_id="f", pack_id="001").pack_id == "001"


def test_observations_have_honest_confidence_and_no_authority():
    c = Confidence(status="NOT_APPLICABLE", reason="native cell read")
    with pytest.raises(ValidationError): Confidence(status="AVAILABLE", reason="model said so")
    with pytest.raises(ValidationError): Confidence(status="UNAVAILABLE", value="0.99", reason="no score")
    o = ExtractionObservation(observation_id="o", scope={"tenant_id":"t","fund_id":"f","pack_id":"p"},
        occurrence_id="occ", parser="csv", parser_version="1", settings={}, response_id="r",
        mode="NATIVE", confidence=c, candidate={"metric":"nav","value_decimal":"0"})
    assert o.confidence.value is None
    with pytest.raises(ValidationError): ExtractionObservation(**(o.model_dump() | {"approved":True}))
