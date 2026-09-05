"""Confidence and contextual agreement remain distinct signals."""
from copy import deepcopy
from decimal import Decimal

import pytest

from closegraph.contracts import Confidence, ObservationCandidate
from closegraph.services.parser_signals import compare_observations, confidence_signal

CANDIDATE = {"entity_id": "synthetic-entity", "metric": "nav", "period": "2026-Q2",
             "currency": "GBP", "raw_scale": "units", "value_decimal": "1000.00"}


@pytest.mark.parametrize("status", ["NOT_RUN", "UNAVAILABLE", "NOT_APPLICABLE"])
def test_optional_parser_absence_keeps_its_actual_state(status):
    assert compare_observations(CANDIDATE, None, availability=status) == status


def test_invalid_absence_state_cannot_invent_agreement():
    assert compare_observations(CANDIDATE, None, availability="AGREE") == "UNKNOWN"


@pytest.mark.parametrize("field,value", [
    ("entity_id", "different-entity"), ("metric", "gross_nav"), ("period", "2025-Q2"),
    ("currency", "USD"), ("raw_scale", "thousands"), ("value_decimal", "999.00"),
])
def test_same_digits_with_different_context_are_not_agreement(field, value):
    second = {**CANDIDATE, field: value}
    original = deepcopy(CANDIDATE)
    assert compare_observations(CANDIDATE, second) == "DISAGREE"
    assert CANDIDATE == original
    assert second[field] == value


@pytest.mark.parametrize("value", [None, "", "NaN", "Infinity", True, 1000.0, []])
def test_missing_nonfinite_or_binary_float_candidates_cannot_agree(value):
    assert compare_observations(CANDIDATE, {**CANDIDATE, "value_decimal": value}) == "UNKNOWN"


def test_numeric_spelling_can_differ_after_explicit_exact_normalization():
    assert compare_observations(CANDIDATE, {**CANDIDATE, "value_decimal": Decimal(1000)}) == "AGREE"


def test_unresolved_context_is_unknown_even_when_both_candidates_omit_it():
    assert compare_observations({**CANDIDATE, "period": None},
                                {**CANDIDATE, "period": None}) == "UNKNOWN"


def test_native_policy_marks_confidence_not_applicable_without_a_percentage():
    signal = confidence_signal(None, native=True)
    assert signal["status"] == "NOT_APPLICABLE"
    assert signal["value"] is None
    assert confidence_signal(None)["status"] == "UNAVAILABLE"


def test_reported_confidence_is_preserved_without_becoming_agreement():
    confidence = {"status": "AVAILABLE", "value": "0.999", "kind": "provider-score",
                  "provenance": "synthetic-response", "calibrated": False}
    assert confidence_signal(confidence) == confidence
    assert compare_observations(CANDIDATE, None) == "NOT_RUN"
    assert confidence_signal({"status": "AVAILABLE", "value": "0.99"})["status"] == "UNAVAILABLE"


def test_canonical_candidates_and_confidence_use_the_same_policy_contract():
    candidate = ObservationCandidate(**CANDIDATE)
    assert compare_observations(candidate, ObservationCandidate(**CANDIDATE)) == "AGREE"
    confidence = Confidence(status="NOT_APPLICABLE", reason="Native extraction")
    assert confidence_signal(confidence, native=True)["status"] == "NOT_APPLICABLE"
