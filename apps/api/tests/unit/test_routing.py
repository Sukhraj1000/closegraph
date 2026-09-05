from decimal import Decimal

import pytest

from closegraph.services.routing import NATIVE_POLICY, explain_route, priority, route

CHECKS = [{"id": "coverage", "required": True, "status": "PASS"},
          {"id": "balance-sheet", "required": True, "status": "PASS"}]


def test_failed_relationship_leads_even_with_high_confidence_and_agreement():
    checks = [CHECKS[0], {**CHECKS[1], "status": "FAIL", "fact_ids": ["assets", "liabilities", "equity"]}]
    result = explain_route(checks, native=False, agreement="AGREE",
                           confidence={"status": "AVAILABLE", "value": "0.999", "kind": "vendor",
                                       "provenance": "synthetic", "calibrated": False})
    assert result.route == "BLOCKED"
    assert result.reasons[0] == "required_check:balance-sheet:FAIL"
    assert result.unsatisfied_check_ids == ("balance-sheet",)
    assert checks[1]["fact_ids"] == ["assets", "liabilities", "equity"]
    assert result.required_check_coverage == (1, 2)


@pytest.mark.parametrize("status", ["UNKNOWN", "NOT_RUN", "FAIL"])
def test_pending_or_unknown_required_checks_block(status):
    assert route([{**CHECKS[0], "status": status}], native=True) == "BLOCKED"


@pytest.mark.parametrize("flags", [
    {"evidence_complete": False}, {"context_complete": False}, {"unverifiable": True},
    {"required_ids": ("not-produced",)}, {"evidence_complete": "true"},
])
def test_missing_required_scope_cannot_receive_ready(flags):
    assert route(CHECKS, native=True, **flags) == "BLOCKED"


def test_missing_duplicate_and_malformed_checks_fail_closed():
    for checks in ([], [CHECKS[0], CHECKS[0]], [{"status": "PASS"}],
                   [{"id": "coverage", "required": "true", "status": "PASS"}]):
        assert route(checks, native=True) == "BLOCKED"


def test_not_applicable_requires_explicit_applicability_and_reason():
    check = {"id": "fee", "required": True, "status": "NOT_APPLICABLE"}
    assert route([check], native=True) == "BLOCKED"
    assert route([{**check, "applicable": False, "justification": "No fee in declared scope"}],
                 native=True) == "READY_FOR_QUICK_REVIEW"


def test_unevaluated_or_missing_ai_confidence_never_defaults_to_quick_review():
    for confidence in (None, {"status": "UNAVAILABLE", "reason": "Not supplied"},
                       {"status": "AVAILABLE", "value": "0.9999", "kind": "model-score",
                        "provenance": "synthetic", "calibrated": False}):
        assert route(CHECKS, agreement="AGREE", confidence=confidence) == "NEEDS_REVIEW"


def test_supported_native_single_parser_is_ready_but_unapproved():
    result = explain_route(CHECKS, native=True)
    assert result.route == "READY_FOR_QUICK_REVIEW"
    assert result.policy_version == NATIVE_POLICY
    assert result.agreement == "NOT_RUN"
    assert result.confidence["status"] == "NOT_APPLICABLE"
    assert result.confidence["value"] is None
    assert result.review_status == "PENDING"
    assert result.required_check_coverage == (2, 2)


def test_changed_policy_and_unresolved_disagreement_require_review():
    assert route(CHECKS, native=True, policy_version="native-v-next") == "NEEDS_REVIEW"
    for agreement in ("DISAGREE", "UNKNOWN", "UNAVAILABLE"):
        assert route(CHECKS, native=True, agreement=agreement) == "NEEDS_REVIEW"
    assert route(CHECKS, native=True, soft_unresolved=True) == "NEEDS_REVIEW"


def test_materiality_and_impact_rank_only_within_the_same_route():
    decisions = [route(CHECKS, native=True) for _ in range(3)]
    assert len(set(decisions)) == 1
    assert priority(Decimal(9), Decimal(100), 1) == "STANDARD"
    assert priority(Decimal(-100), Decimal(100), 0) == "HIGH"
    assert priority(Decimal(9), Decimal(100), 2) == "HIGH"
    assert priority(Decimal(9), Decimal(100), 2, impact_threshold=3) == "STANDARD"


@pytest.mark.parametrize("count", [True, 1.5, "2"])
def test_priority_counts_are_not_coerced(count):
    with pytest.raises(TypeError):
        priority(Decimal(1), Decimal(100), count)


def test_nonfinite_priority_is_rejected():
    with pytest.raises(ValueError):
        priority(Decimal("NaN"), Decimal(100), 0)
