"""Pinned hard-gate routing and explainable priority; neither grants approval."""
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from .parser_signals import confidence_signal

NATIVE_POLICY = "native-single-parser-v1"


@dataclass(frozen=True)
class RouteDecision:
    route: str
    policy_version: str
    reasons: tuple[str, ...]
    required_check_ids: tuple[str, ...]
    unsatisfied_check_ids: tuple[str, ...]
    required_check_coverage: tuple[int, int]
    agreement: str
    confidence: dict
    review_status: str = "PENDING"


def check_satisfied(check):
    if not isinstance(check, Mapping):
        return False
    return check.get("status") == "PASS" or (
        check.get("status") == "NOT_APPLICABLE"
        and check.get("applicable") is False
        and isinstance(check.get("justification"), str)
        and bool(check["justification"].strip())
    )


def explain_route(checks, *, native=False, policy_version=NATIVE_POLICY, agreement="NOT_RUN",
                  confidence=None, unverifiable=False, evidence_complete=True,
                  context_complete=True, soft_unresolved=False, required_ids=()):
    """Return the exact reasons and coverage behind the backwards-compatible route."""
    checks = tuple(checks)
    confidence = confidence_signal(confidence, native=native is True)
    required_ids = tuple(required_ids)
    malformed = any(not isinstance(check, Mapping)
                    or not isinstance(check.get("id"), str) or not check["id"].strip()
                    or type(check.get("required")) is not bool for check in checks)
    indexed = {check["id"]: check for check in checks
               if isinstance(check, Mapping) and isinstance(check.get("id"), str)}
    required = [check for check in checks
                if isinstance(check, Mapping) and check.get("required") is True]
    required_names = tuple(dict.fromkeys([check.get("id", "") for check in required] + list(required_ids)))
    failed = tuple(check.get("id", "") for check in required if not check_satisfied(check))
    missing = tuple(name for name in required_ids
                    if name not in indexed or indexed[name].get("required") is not True)
    unsatisfied = tuple(dict.fromkeys(failed + missing))
    coverage = (sum(check_satisfied(indexed.get(name))
                    and indexed.get(name, {}).get("required") is True for name in required_names),
                len(required_names))
    reasons = []
    # Failed relationships lead the explanation; do not invent one culpable operand.
    reasons.extend("required_check:" + name + ":" + str(indexed.get(name, {}).get("status", "MISSING"))
                   for name in failed)
    reasons.extend("missing_required_check:" + name for name in missing)
    if malformed:
        reasons.append("malformed_check_record")
    if len(indexed) != len(checks):
        reasons.append("duplicate_or_missing_check_identity")
    if not required:
        reasons.append("no_required_check_coverage")
    if unverifiable is not False:
        reasons.append("dependencies_unverifiable")
    if evidence_complete is not True:
        reasons.append("material_evidence_incomplete")
    if context_complete is not True:
        reasons.append("material_context_unresolved")
    if reasons:
        selected = "BLOCKED"
    else:
        if native is not True:
            reasons.append("probabilistic_quick_review_not_evaluated")
        if policy_version != NATIVE_POLICY:
            reasons.append("unsupported_policy_version")
        if soft_unresolved is not False:
            reasons.append("unresolved_interpretation")
        if agreement not in {"NOT_RUN", "NOT_APPLICABLE", "AGREE"}:
            reasons.append("parser_agreement:" + str(agreement))
        if native is True and confidence.get("status") != "NOT_APPLICABLE":
            reasons.append("native_confidence_not_applicable_required")
        selected = "NEEDS_REVIEW" if reasons else "READY_FOR_QUICK_REVIEW"
        if not reasons:
            reasons.append("supported_native_policy_and_required_checks_pass")
    return RouteDecision(selected, policy_version, tuple(reasons), required_names, unsatisfied,
                         coverage, agreement, confidence)


def route(checks, *, native=False, policy_version=NATIVE_POLICY, agreement="NOT_RUN", confidence=None,
          unverifiable=False, evidence_complete=True, soft_unresolved=False, required_ids=(),
          context_complete=True):
    """Hard gates first. A confidence score has no authority at any value."""
    return explain_route(
        checks, native=native, policy_version=policy_version, agreement=agreement,
        confidence=confidence, unverifiable=unverifiable, evidence_complete=evidence_complete,
        context_complete=context_complete, soft_unresolved=soft_unresolved,
        required_ids=required_ids,
    ).route


def priority(amount: Decimal, materiality: Decimal, dependent_outputs: int, *,
             impact_threshold: int = 2):
    """Rank items only within their route using declared amount/impact thresholds."""
    if not isinstance(amount, Decimal) or not isinstance(materiality, Decimal):
        raise TypeError("Decimal values required")
    if type(dependent_outputs) is not int or type(impact_threshold) is not int:
        raise TypeError("Integer output counts and thresholds required")
    if (not amount.is_finite() or not materiality.is_finite() or materiality < 0
            or dependent_outputs < 0 or impact_threshold <= 0):
        raise ValueError("Invalid priority inputs")
    return "HIGH" if abs(amount) >= materiality or dependent_outputs >= impact_threshold else "STANDARD"
