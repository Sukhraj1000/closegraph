"""Labelled independent-parser fixtures; no Docling installation or live call."""
from unittest.mock import Mock

from closegraph.contracts import Confidence, ExtractionObservation, ObservationCandidate, Scope
from closegraph.extractors.common import compare_observations, run_second_pass

SCOPE = Scope(tenant_id="t", fund_id="f", pack_id="p")


def observation(parser="primary", **changes):
    candidate = {"metric": "nav", "value_decimal": "1000.00", "entity_id": "synthetic-entity",
                 "period": "2026-Q2", "currency": "GBP", "raw_value": "1,000.00", "raw_scale": "units"}
    candidate.update(changes)
    return ExtractionObservation(
        scope=SCOPE, observation_id=parser + "-observation", occurrence_id="same-source-occurrence",
        parser=parser, parser_version="synthetic-v1", settings={}, response_id=parser + "-response",
        mode="SYNTHETIC", confidence=Confidence(status="UNAVAILABLE", reason="synthetic fixture"),
        candidate=ObservationCandidate(**candidate))


def test_not_run_does_not_call_optional_parser_or_invent_agreement():
    first, parser = observation(), Mock()
    result = run_second_pass((first,), b"synthetic", scope=SCOPE, document_version_id="doc", parser=parser)
    assert result.status == "NOT_RUN"
    assert result.primary == (first,)
    assert result.comparisons == ()
    parser.observe.assert_not_called()


def test_unconfigured_and_failed_second_parser_are_unavailable():
    first = observation()
    missing = run_second_pass((first,), b"synthetic", scope=SCOPE, document_version_id="doc", requested=True)
    assert missing.status == "UNAVAILABLE"
    parser = Mock()
    parser.observe.side_effect = RuntimeError("service unavailable")
    failed = run_second_pass((first,), b"synthetic", scope=SCOPE, document_version_id="doc",
                             requested=True, parser=parser)
    assert failed.status == "UNAVAILABLE"
    assert failed.primary == (first,)
    assert failed.secondary == ()


def test_same_digits_with_different_currency_or_period_are_disagreement():
    first = observation()
    for changes in ({"currency": "USD"}, {"period": "2025-Q2"}, {"entity_id": "another"},
                    {"metric": "gross_nav"}, {"raw_scale": "thousands"}, {"value_decimal": "999"}):
        second = observation("secondary", **changes)
        result = compare_observations(first, second)
        assert result.status == "DISAGREE"


def test_success_preserves_both_original_observations_and_contextual_comparison():
    first, second = observation(), observation("secondary")
    parser = Mock()
    parser.observe.return_value = (second,)
    result = run_second_pass((first,), b"synthetic", scope=SCOPE, document_version_id="doc",
                             requested=True, parser=parser)
    assert result.status == "COMPLETED"
    assert result.primary[0] is first
    assert result.secondary[0] is second
    assert result.comparisons[0].status == "AGREE"
    assert first.confidence.status == second.confidence.status == "UNAVAILABLE"


def test_missing_context_and_ambiguous_occurrence_cannot_establish_agreement():
    first = observation()
    assert compare_observations(first, observation("secondary", period=None)).status == "UNKNOWN"
    parser = Mock()
    parser.observe.return_value = (observation("secondary"), observation("third"))
    result = run_second_pass((first,), b"synthetic", scope=SCOPE, document_version_id="doc",
                             requested=True, parser=parser)
    assert result.comparisons[0].status == "UNKNOWN"
    assert len(result.secondary) == 2
