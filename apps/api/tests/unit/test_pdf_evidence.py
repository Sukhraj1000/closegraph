import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from unittest.mock import Mock

import pytest

from closegraph.contracts import ExtractionObservation, FactSnapshot, Scope, SourceOccurrence
from closegraph.extractors.reducto import ENDPOINT, ReductoResult, decode_response
from closegraph.fixtures import SCOPE, fixture_bytes
from closegraph.services.native import evaluate_pack, ingest_sources
from closegraph.services.pdf_evidence import (
    CapturedReplay,
    PdfEvidenceService,
    provider_from_environment,
)

SCOPE_VALUE = Scope(**SCOPE)
PDF = b"%PDF-1.4\n% SYNTHETIC UNIT TEST CAPTURE\n%%EOF"
HASH = sha256(PDF).hexdigest()


class MemoryBlobs:
    def __init__(self):
        self.data = {}

    def put(self, content):
        digest = sha256(content).hexdigest()
        self.data[digest] = content
        return digest

    def get(self, digest):
        return self.data[digest]


def response():
    return json.dumps({"job_id": "synthetic-unit-job", "result": {"type": "full", "chunks": [
        {"blocks": [{"content": "SYNTHETIC report text", "type": "Text",
                     "bbox": {"left": .1, "top": .2, "width": .3, "height": .1,
                              "page": 1, "original_page": 3}}]}
    ]}}).encode()


def capture(tmp_path):
    raw = response()
    receipt = {"mode": "LIVE", "transport": "trusted-coordinator", "endpoint": ENDPOINT,
               "source_sha256": HASH, "response_sha256": sha256(raw).hexdigest(),
               "job_id": "synthetic-unit-job", "executed_at": "2026-09-05T00:00:00Z",
               "authorization_reference": "Synthetic unit-test transport fixture; no real call",
               "data_handling_note": "Synthetic fixture only; no provider request was made by this test",
               "request_settings": {"persist_results": False, "force_url_result": False}}
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "receipt.json").write_text(json.dumps(receipt))
    (tmp_path / "synthetic.pdf").write_bytes(PDF)
    (tmp_path / "parse-response.json").write_bytes(raw)
    return CapturedReplay.from_directory(tmp_path)


def receipt():
    return {"source_id": "reporting-evidence", "document_version_id": "pdf-v1",
            "content_hash": HASH, "version": 1, "filename": "synthetic.pdf",
            "media_type": "application/pdf"}


def parse(provider, content=PDF):
    return provider.parse(content, scope=SCOPE_VALUE, document_version_id="pdf-v1")


def test_default_disabled_never_calls_an_injected_transport():
    transport = Mock()
    provider = PdfEvidenceService(live_provider=transport)
    result = parse(provider)
    assert result.diagnostics == ("provider_disabled",)
    transport.parse_pdf.assert_not_called()
    assert provider_from_environment({"REDUCTO_API_KEY": "ignored"}).mode == "DISABLED"


def test_live_without_coordinator_is_explicitly_unavailable():
    result = parse(provider_from_environment({"CLOSEGRAPH_PDF_MODE": "LIVE"}))
    assert result.mode == "LIVE"
    assert result.diagnostics == ("live_transport_unavailable",)


def test_capture_is_exact_hash_replay_with_canonical_original_page(tmp_path):
    provider = PdfEvidenceService(mode="CAPTURED_REPLAY", capture=capture(tmp_path))
    result = parse(provider)
    assert result.available and result.mode == "REPLAY"
    assert result.response_id == "synthetic-unit-job"
    assert result.occurrences[0].source.locator.original_page == 3
    assert result.occurrences[0].source.locator.processed_page == 1
    assert result.occurrences[0].source.locator.bbox == pytest.approx((.1, .2, .4, .3))
    assert result.observations[0].candidate.value_decimal is None
    assert result.observations[0].confidence.calibrated is False


def test_different_pdf_has_no_silent_replay_or_live_fallback(tmp_path):
    transport = Mock()
    provider = PdfEvidenceService(mode="CAPTURED_REPLAY", capture=capture(tmp_path),
                                  live_provider=transport)
    result = parse(provider, PDF + b"different")
    assert result.diagnostics == ("captured_replay_source_hash_mismatch",)
    transport.parse_pdf.assert_not_called()


@pytest.mark.parametrize("filename", ["receipt.json", "synthetic.pdf", "parse-response.json"])
def test_modified_capture_is_rejected(tmp_path, filename):
    capture(tmp_path)
    path = tmp_path / filename
    if filename == "receipt.json":
        payload = json.loads(path.read_bytes())
        payload["job_id"] = "wrong-job"
        path.write_text(json.dumps(payload))
    else:
        path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError):
        CapturedReplay.from_directory(tmp_path)


def test_capture_mode_requires_explicit_directory():
    with pytest.raises(ValueError, match="requires"):
        provider_from_environment({"CLOSEGRAPH_PDF_MODE": "CAPTURED_REPLAY"})


def test_unavailable_provider_does_not_invent_a_page_or_fact():
    result = PdfEvidenceService().extract(receipt(), PDF, scope=SCOPE_VALUE, blobs=MemoryBlobs())
    assert result["facts"] == result["source_occurrences"] == result["extraction_observations"] == []
    evidence = result["evidence"]["reporting-evidence"]
    assert evidence["provider_status"] == "DISABLED"
    assert "locator" not in evidence
    assert result["report"]["financial_mapping"] == "UNAVAILABLE"


def test_replay_stores_response_bytes_and_unresolved_citation_fact(tmp_path):
    blobs = MemoryBlobs()
    result = PdfEvidenceService(mode="CAPTURED_REPLAY", capture=capture(tmp_path)).extract(
        receipt(), PDF, scope=SCOPE_VALUE, blobs=blobs)
    evidence = next(item for item in result["evidence"].values() if item.get("locator"))
    assert evidence["provider_mode"] == "CAPTURED_REPLAY"
    assert evidence["capture"]["original_mode"] == "LIVE"
    assert blobs.get(evidence["response_content_hash"]) == response()
    for item in result["source_occurrences"]:
        SourceOccurrence.model_validate(item)
    for item in result["extraction_observations"]:
        assert ExtractionObservation.model_validate(item).mode == "REPLAY"
    fact = result["facts"][0]
    assert fact["interpretation_status"] == "UNRESOLVED"
    assert fact["value_decimal"] is None and fact["entity_id"] is None
    assert result["report"]["unresolved_count"] == 1


def test_live_hook_preserves_real_mode_and_rejects_cross_scope():
    result = decode_response(response(), scope=SCOPE_VALUE, document_version_id="pdf-v1",
                             source_sha256=HASH, mode="LIVE")
    transport = Mock()
    transport.parse_pdf.return_value = result
    provider = PdfEvidenceService(mode="LIVE", live_provider=transport)
    assert parse(provider) == result
    wrong_scope = Scope(tenant_id="other", fund_id=SCOPE_VALUE.fund_id, pack_id=SCOPE_VALUE.pack_id)
    transport.parse_pdf.return_value = replace(result, occurrences=(
        result.occurrences[0].model_copy(update={"scope": wrong_scope}),))
    assert parse(provider).diagnostics == ("live_source_scope_mismatch",)


def test_live_hook_cannot_claim_replay_or_forge_response_hash():
    result = decode_response(response(), scope=SCOPE_VALUE, document_version_id="pdf-v1",
                             source_sha256=HASH, mode="LIVE")
    transport = Mock()
    provider = PdfEvidenceService(mode="LIVE", live_provider=transport)
    transport.parse_pdf.return_value = replace(result, mode="REPLAY")
    assert parse(provider).diagnostics == ("live_transport_provenance_mismatch",)
    transport.parse_pdf.return_value = replace(result, response_hash="0" * 64)
    assert parse(provider).diagnostics == ("live_response_hash_mismatch",)
    transport.parse_pdf.return_value = ReductoResult("AVAILABLE", HASH, mode="LIVE")
    assert parse(provider).diagnostics == ("live_response_provenance_incomplete",)


def native_state(blobs):
    state = {**SCOPE, "receipts": []}
    fixtures = fixture_bytes()
    for role, name in (("capital", "capital.csv"), ("fee-rule", "fee-rule.csv"),
                       ("original", "original.xlsx")):
        state["receipts"].append({"source_id": role, "document_version_id": role + "-v1", "version": 1,
                                  "content_hash": blobs.put(fixtures[name]), "filename": name})
    return state


@pytest.mark.parametrize("enabled", [False, True])
def test_pdf_upload_keeps_native_checks_and_blocks_unresolved_coverage(tmp_path, enabled):
    blobs = MemoryBlobs()
    state = native_state(blobs)
    baseline = ingest_sources(state, blobs, scope=SCOPE_VALUE)
    native_checks = evaluate_pack(baseline, blobs)["checks"]
    assert baseline["extraction_report"]["coverage"]["status"] == "PASS"
    state["receipts"].append(receipt())
    blobs.put(PDF)
    provider = PdfEvidenceService(mode="CAPTURED_REPLAY", capture=capture(tmp_path)) if enabled else None
    result = ingest_sources(state, blobs, scope=SCOPE_VALUE, pdf_evidence=provider)
    assert result["extraction_report"]["schema"]["status"] == baseline["extraction_report"]["schema"]["status"]
    assert result["extraction_report"]["coverage"]["status"] == "FAIL"
    assert not any("Unsupported source role" in item for item in result["extraction_report"]["errors"])
    assert not result["native"] and not result["dependency_coverage"]
    checks = evaluate_pack(result, blobs)["checks"]
    for name in ("source_inputs", "fee", "source_to_pack", "balance_sheet"):
        assert next(item for item in checks if item["id"] == name) == next(
            item for item in native_checks if item["id"] == name)
    assert len([fact for fact in result["facts"] if fact["metric"] == "reporting_evidence"]) == int(enabled)
    if enabled:
        fact = result["facts"][-1]
        public = {key: value for key, value in fact.items() if key not in ("occurrence_id",)}
        public["source"] = {key: value for key, value in public["source"].items() if key != "source_id"}
        assert FactSnapshot.model_validate(public).source.locator.kind == "pdf"


def test_actual_captured_synthetic_response_is_replay_only():
    directory = Path(__file__).resolve().parents[4] / "artifacts/live-reducto"
    if not directory.exists():
        pytest.skip("Actual synthetic capture is supplied by trusted coordinator, not checked-in fixture")
    captured = CapturedReplay.from_directory(directory)
    result = PdfEvidenceService(mode="CAPTURED_REPLAY", capture=captured).parse(
        (directory / "synthetic.pdf").read_bytes(), scope=SCOPE_VALUE, document_version_id="captured-v1")
    assert result.available
    assert result.mode == "REPLAY"
    assert result.response_id == captured.receipt["job_id"]


@pytest.mark.parametrize("with_pdf", [False, True])
def test_explicit_rule_revocation_survives_later_source_ingest(tmp_path, with_pdf):
    blobs = MemoryBlobs()
    state = native_state(blobs)
    baseline = ingest_sources(state, blobs, scope=SCOPE_VALUE)
    revoked = {**baseline["rule"], "approved": False, "version": "revoked-rule-v2"}
    state["configured_records"] = {"rule": revoked, "rule_version": "revoked-rule-v2",
                                   "policy": {"version": "pinned-policy-v2"}, "policy_version": "pinned-policy-v2"}
    if with_pdf:
        blobs.put(PDF)
        state["receipts"].append(receipt())
    patch = ingest_sources(state, blobs, scope=SCOPE_VALUE)
    assert patch["rule"] == revoked
    assert patch["rule_version"] == "revoked-rule-v2"
    assert patch["policy"] == {"version": "pinned-policy-v2"}
    assert patch["policy_version"] == "pinned-policy-v2"
    assert next(check for check in evaluate_pack(patch, blobs)["checks"] if check["id"] == "evidence")["status"] == "FAIL"
    patch["rule"]["approved"] = True
    assert state["configured_records"]["rule"]["approved"] is False


def test_unsupported_pinned_mapping_is_preserved_without_claiming_interpretation():
    blobs = MemoryBlobs()
    state = native_state(blobs)
    state["configured_records"] = {"mappings": {"version": "mapping-v2", "fields": {"old": "new"}},
                                   "mapping_version": "mapping-v2"}
    result = ingest_sources(state, blobs, scope=SCOPE_VALUE)
    assert result["mappings"] == state["configured_records"]["mappings"]
    assert result["mapping_version"] == "mapping-v2"
    assert result["extraction_report"]["coverage"]["status"] == "FAIL"
    assert all(fact["interpretation_status"] == "UNRESOLVED" for fact in result["facts"])
    assert result["dependency_coverage"] is False
