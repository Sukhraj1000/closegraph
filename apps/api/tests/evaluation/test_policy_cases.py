"""Pinned synthetic policy evaluation, separate from routing inputs.

Labels assess review eligibility on these scenarios, not universal financial truth,
probability calibration, user time, or customer savings.
"""
import json
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

from closegraph.services.parser_signals import compare_observations
from closegraph.services.routing import NATIVE_POLICY, explain_route, priority

FIXTURES = Path(__file__).parents[1] / "fixtures"


def load():
    policy = json.loads((FIXTURES / "review-policy-v1.json").read_text())
    dataset = json.loads((FIXTURES / "review-policy-cases-v1.json").read_text())
    return policy, dataset


def predict(features, policy):
    """Only observable features and the pinned policy enter routing, never labels."""
    values = deepcopy(features)
    checks = values.pop("checks")
    amount, dependent_outputs = values.pop("amount"), values.pop("dependent_outputs")
    if "secondary" in values:
        values["agreement"] = compare_observations(values.pop("primary"), values.pop("secondary"))
    values.setdefault("policy_version", policy["policy_version"])
    result = explain_route(checks, required_ids=policy["required_check_ids"], **values)
    return {**asdict(result), "priority": priority(Decimal(amount),
            Decimal(policy["priority"]["materiality"]), dependent_outputs,
            impact_threshold=policy["priority"]["impact_threshold"])}


def report(predictions, held_out, policy, dataset):
    categories = Counter(predictions[case["id"]]["route"] for case in held_out)
    false_ready = [case["id"] for case in held_out
                   if predictions[case["id"]]["route"] == "READY_FOR_QUICK_REVIEW"
                   and case["label"]["safe_for_quick_review"] is False]
    return {"policy_version": policy["policy_version"], "policy_revision": policy["revision"],
            "dataset_id": dataset["dataset_id"], "scope": dataset["scope"], "split": "held_out",
            "case_count": len(held_out), "false_ready_count": len(false_ready),
            "false_ready_case_ids": false_ready, "route_counts": dict(categories),
            "required_check_coverage": {
                "satisfied": sum(predictions[case["id"]]["required_check_coverage"][0] for case in held_out),
                "expected": sum(predictions[case["id"]]["required_check_coverage"][1] for case in held_out)},
            "error_classes": dict(Counter(case["label"]["error_class"] for case in held_out
                                         if case["label"]["error_class"])),
            "cases": [{"id": case["id"], "observed": predictions[case["id"]],
                       "label": case["label"]} for case in held_out]}


def test_versioned_policy_on_separate_held_out_cases_records_actual_outcomes(tmp_path):
    policy, dataset = load()
    assert policy["policy_version"] == NATIVE_POLICY
    assert policy["probabilistic_quick_review"] is False
    development = {case["id"] for case in dataset["cases"] if case["split"] == "development"}
    held_out = [case for case in dataset["cases"] if case["split"] == "held_out"]
    assert development.isdisjoint(case["id"] for case in held_out)
    predictions = {case["id"]: predict(case["features"], policy) for case in held_out}
    for case in held_out:
        assert predictions[case["id"]]["route"] == case["label"]["expected_route"]
        assert predictions[case["id"]]["review_status"] == "PENDING"
    result = report(predictions, held_out, policy, dataset)
    assert result["case_count"] == 13
    assert result["false_ready_count"] == 0
    assert result["error_classes"]["correlated_parser_error"] == 1
    assert result["error_classes"]["missed_record"] == 1
    assert result["error_classes"]["rejected_record"] == 1
    (tmp_path / "review-policy-evaluation-v1.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({key: value for key, value in result.items() if key != "cases"}, sort_keys=True))


def test_agreeing_correlated_errors_do_not_become_proof_of_correctness():
    policy, dataset = load()
    case = next(case for case in dataset["cases"] if case["label"]["error_class"] == "correlated_parser_error")
    result = predict(case["features"], policy)
    assert result["agreement"] == "AGREE"
    assert result["route"] == "NEEDS_REVIEW"
    assert case["label"]["safe_for_quick_review"] is False


def test_false_ready_report_counts_an_unsafe_prediction_instead_of_erasing_it():
    policy, dataset = load()
    cases = [case for case in dataset["cases"] if case["split"] == "held_out"]
    predictions = {case["id"]: predict(case["features"], policy) for case in cases}
    # Deliberately emulate a candidate policy regression, not the live policy.
    predictions["heldout-correlated-parser-error"]["route"] = "READY_FOR_QUICK_REVIEW"
    result = report(predictions, cases, policy, dataset)
    assert result["false_ready_count"] == 1
    assert result["false_ready_case_ids"] == ["heldout-correlated-parser-error"]


def test_priority_and_later_reviewer_labels_do_not_silently_modify_policy():
    policy, dataset = load()
    frozen_policy = deepcopy(policy)
    cases = {case["id"]: case for case in dataset["cases"]}
    standard = predict(cases["heldout-zero-is-present"]["features"], policy)
    material = predict(cases["heldout-material-native"]["features"], policy)
    impact = predict(cases["heldout-downstream-impact"]["features"], policy)
    assert {standard["route"], material["route"], impact["route"]} == {"READY_FOR_QUICK_REVIEW"}
    assert standard["priority"] == "STANDARD"
    assert material["priority"] == impact["priority"] == "HIGH"
    cases["heldout-zero-is-present"]["label"]["safe_for_quick_review"] = False
    assert predict(cases["heldout-zero-is-present"]["features"], policy) == standard
    assert policy == frozen_policy
