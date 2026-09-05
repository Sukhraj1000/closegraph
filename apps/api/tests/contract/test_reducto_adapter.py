"""Synthetic provider contract fixtures: these are not live-provider evidence."""
import json
from copy import deepcopy
from hashlib import sha256
from unittest.mock import Mock

import pytest

from closegraph.contracts import Scope
from closegraph.extractors.reducto import (
    ProviderFailure,
    ReductoAdapter,
    ReductoConfig,
    decode_response,
)

SCOPE = Scope(tenant_id="synthetic-tenant", fund_id="synthetic-fund", pack_id="synthetic-pack")
PDF = b"%PDF-1.4\nSYNTHETIC CONTRACT FIXTURE ONLY"
DIGEST = sha256(PDF).hexdigest()


def response(confidence="high", numeric=0.92):
    return {"job_id": "synthetic-job", "result": {"type": "full", "chunks": [{"blocks": [{
        "type": "Text", "content": "SYNTHETIC NAV GBP 1000.00",
        "bbox": {"left": 0.1, "top": 0.2, "width": 0.3, "height": 0.1,
                 "page": 1, "original_page": 5},
        "confidence": confidence, "granular_confidence": {"parse_confidence": numeric}
    }]}]}}


def decode(data):
    raw = json.dumps(data).encode()
    return decode_response(raw, scope=SCOPE, document_version_id="synthetic-doc-v1",
                           source_sha256=DIGEST, settings={"page_range": {"start": 5, "end": 5}},
                           mode="SYNTHETIC")


def enabled():
    return ReductoConfig(enabled=True, api_key="synthetic-not-a-real-key",
                         authorized_source_hashes=frozenset({DIGEST}),
                         authorization_reference="synthetic-test-authorization",
                         data_handling_note="Synthetic mocked transport only")


def test_preserves_pages_bbox_raw_response_and_untrusted_observation():
    payload = response()
    result = decode(payload)
    assert result.available
    occurrence, observation = result.occurrences[0], result.observations[0]
    assert occurrence.source.locator.original_page == 5
    assert occurrence.source.locator.processed_page == 1
    assert occurrence.source.locator.bbox == pytest.approx((0.1, 0.2, 0.4, 0.3))
    assert occurrence.disposition == "UNRESOLVED"
    assert occurrence.source.content_hash == DIGEST
    assert observation.confidence.status == "AVAILABLE"
    assert str(observation.confidence.value) == "0.92"
    assert observation.confidence.calibrated is False
    assert observation.candidate.value_decimal is None
    assert observation.candidate.metric is None
    assert observation.settings["provider_confidence"] == "high"
    assert observation.mode == "SYNTHETIC"
    assert result.response_hash == sha256(result.raw_response).hexdigest()
    assert json.loads(result.raw_response) == payload


@pytest.mark.parametrize("categorical", ["high", "low", None, "unrecognised-provider-label"])
def test_categorical_confidence_is_preserved_without_inventing_percentage(categorical):
    result = decode(response(confidence=categorical, numeric=None))
    confidence = result.observations[0].confidence
    assert confidence.status == "UNAVAILABLE"
    assert confidence.value is None
    assert result.observations[0].settings["provider_confidence"] == categorical


@pytest.mark.parametrize("numeric", [False, -0.1, 1.1, "NaN", "Infinity", "not-a-number", []])
def test_malformed_granular_confidence_is_explicitly_unavailable(numeric):
    result = decode(response(numeric=numeric))
    assert result.observations[0].confidence.status == "UNAVAILABLE"
    assert json.loads(result.raw_response)["result"]["chunks"][0]["blocks"][0]["granular_confidence"]["parse_confidence"] == numeric


@pytest.mark.parametrize("patch", [
    {"original_page": None}, {"original_page": 0}, {"original_page": True},
    {"page": 0}, {"left": -1}, {"width": 0}, {"width": 2}, {"top": "0.1"}
])
def test_malformed_citations_never_become_valid_source_evidence(patch):
    payload = response()
    payload["result"]["chunks"][0]["blocks"][0]["bbox"].update(patch)
    result = decode(payload)
    assert not result.available
    assert not result.observations
    assert result.raw_response is not None
    assert "malformed_citation" in result.diagnostics[0]


def test_partial_valid_response_preserves_evidence_but_is_not_complete():
    payload = response()
    invalid = deepcopy(payload["result"]["chunks"][0]["blocks"][0])
    invalid["bbox"].pop("original_page")
    payload["result"]["chunks"][0]["blocks"].append(invalid)
    result = decode(payload)
    assert not result.available
    assert len(result.observations) == 1
    assert len(result.diagnostics) == 1


@pytest.mark.parametrize("config", [
    ReductoConfig(), ReductoConfig(enabled=True),
    ReductoConfig(enabled=True, api_key="synthetic-key"),
    ReductoConfig(enabled=True, api_key="synthetic-key", authorized_source_hashes=frozenset({DIGEST}))
])
def test_no_egress_when_disabled_unconfigured_or_unauthorized(config):
    transport = Mock()
    result = ReductoAdapter(config, transport).parse_pdf(PDF, scope=SCOPE, document_version_id="doc")
    assert not result.available
    transport.upload.assert_not_called()
    transport.parse.assert_not_called()


def test_provider_failure_has_no_native_or_fixture_fallback():
    transport = Mock()
    transport.upload.side_effect = ProviderFailure("provider_http_503")
    result = ReductoAdapter(enabled(), transport).parse_pdf(PDF, scope=SCOPE, document_version_id="doc")
    assert not result.available
    assert result.observations == ()
    assert result.diagnostics == ("provider_http_503",)
    transport.parse.assert_not_called()


def test_mock_transport_contract_disables_retention_and_captures_raw_bytes():
    transport = Mock()
    transport.upload.return_value = b'{"file_id":"reducto://synthetic.pdf"}'
    transport.parse.return_value = json.dumps(response()).encode()
    result = ReductoAdapter(enabled(), transport).parse_pdf(PDF, scope=SCOPE, document_version_id="doc")
    assert result.available
    assert transport.parse.call_args.args[1] == {"persist_results": False, "force_url_result": False}
    assert result.upload_response == transport.upload.return_value
    assert "synthetic-not-a-real-key" not in repr(enabled())


def test_url_response_is_not_fetched_or_silently_substituted():
    result = decode({"job_id": "synthetic", "result": {"type": "url", "url": "http://169.254.169.254/secret"}})
    assert not result.available
    assert result.diagnostics == ("external_result_url_unsupported_no_automatic_fetch",)


@pytest.mark.parametrize("payload", [b"not json", b"[]", b"{}", b'{"job_id":"x","result":null}'])
def test_malformed_provider_body_is_retained_with_unavailability(payload):
    result = decode_response(payload, scope=SCOPE, document_version_id="doc",
                             source_sha256=DIGEST, mode="SYNTHETIC")
    assert not result.available
    assert result.raw_response == payload
