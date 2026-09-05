"""Deterministic evidence/check/task contracts with synthetic plain data only."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from closegraph.collections.workflow import (
    apply_task_action, create_manual_flag, evaluate_requirements, requirements_blocked,
    sync_tasks, tasks_blocked, validate_requirements, tick_deadlines, sync_processing_error,
)

NOW = "2026-09-05T12:00:00+00:00"


def fixture(kind="evidence", parameters=None):
    state = {"id": "collection", "requirements_version": 3,
             "documents": [{"id": "logical", "current_revision_id": "source-v2", "period": "2026-08"}],
             "sources": [{"id": "source-v2", "version": 2, "content_hash": "source-hash", "status": "EXTRACTED",
                          "media_type": "text/csv", "coverage": {"complete": True}, "as_of": "2026-09-04", "issues": []}],
             "datasets": [{"id": "data-v2", "source_id": "source-v2", "title": "Records", "kind": "extraction",
                           "version": 2, "data_hash": "accepted-data", "accepted_hash": "accepted-data", "accepted": True}],
             "members": [{"actor_id": "manager", "party": "account_manager"},
                             {"actor_id": "accountant", "party": "accountant"},
                             {"actor_id": "fund-manager", "party": "fund_manager"},
                             {"actor_id": "investor", "party": "investor"}],
             "requirements": [{"id": "req", "title": "Required check", "kind": kind, "blocking": True,
                               "owner_party": "accountant", "owner_actor_id": "accountant", "document_ids": ["logical"],
                               "table_title": "Records", "period": "2026-08", "parameters": parameters or {}}],
             "issues": [], "tasks": [], "notifications": []}
    table = {"table_id": "data-v2", "source_id": "source-v2", "columns": [
        {"key": key, "label": key} for key in ("account", "amount", "credit", "debit", "base", "fee", "currency")],
        "rows": [{"row_id": "row-1", "values": {"account": "001", "amount": "0.1", "credit": "100.00", "debit": None, "base": "1000", "fee": "10.00", "currency": "GBP"},
                  "locators": {key: {"kind": "csv", "row": 2, "column": index + 1} for index, key in enumerate(("account", "amount", "credit", "debit", "base", "fee", "currency"))}},
                 {"row_id": "row-2", "values": {"account": "002", "amount": "0.2", "credit": None, "debit": "-25.00", "base": "2000", "fee": "20.00", "currency": "GBP"},
                  "locators": {key: {"kind": "csv", "row": 3, "column": index + 1} for index, key in enumerate(("account", "amount", "credit", "debit", "base", "fee", "currency"))}}]}
    return state, table


def evaluate(state, table):
    return evaluate_requirements(state, lambda descriptor: table, NOW)[0]


def test_empty_policy_is_explicitly_blocking_and_does_not_call_loader():
    state, _ = fixture()
    state["requirements"] = []
    result = evaluate_requirements(state, lambda _: pytest.fail("No dataset should be read"), NOW)
    assert result[0]["status"] == result[0]["outcome"] == "MISSING_EVIDENCE"
    assert result[0]["requirement_id"] == "missing_check_policy"
    assert requirements_blocked(result)


def test_native_evidence_acceptance_binds_current_bytes_and_dataset_version():
    state, table = fixture()
    before = deepcopy(state)
    result = evaluate(state, table)
    assert result["status"] == "PASS" and not requirements_blocked([result])
    assert result["requirement_version"] == 3
    assert any(item.get("dataset_version") == 2 and item.get("accepted_hash") == "accepted-data" for item in result["inputs"])
    assert state == before
    assert evaluate_requirements(state, lambda _: table, "2026-09-05T13:00:00Z")[0]["fingerprint"] == result["fingerprint"]


@pytest.mark.parametrize("mutation,expected", [
    (lambda s: s["documents"][0].update(current_revision_id=None), "MISSING_EVIDENCE"),
    (lambda s: s["documents"][0].update(current_revision_id="absent"), "MISSING_EVIDENCE"),
    (lambda s: s["sources"][0].update(status="FAILED"), "ERROR"),
    (lambda s: s["sources"][0].update(coverage={"complete": False}), "MISSING_EVIDENCE"),
    (lambda s: s["datasets"][0].update(accepted=False), "NEEDS_REVIEW"),
    (lambda s: s["datasets"][0].update(data_hash="corrected-after-acceptance"), "NEEDS_REVIEW"),
    (lambda s: s["documents"][0].update(period="2026-07"), "NEEDS_REVIEW"),
])
def test_incomplete_missing_failed_stale_or_unaccepted_evidence_never_passes(mutation, expected):
    state, table = fixture()
    mutation(state)
    result = evaluate(state, table)
    assert result["status"] == expected and requirements_blocked([result])


def test_document_replacement_cannot_reuse_previous_dataset_or_completeness():
    state, table = fixture("total", {"column": "amount", "expected": "0.3"})
    state["documents"][0]["current_revision_id"] = "source-v3"
    state["sources"].append({**state["sources"][0], "id": "source-v3", "version": 3, "content_hash": "new-source"})
    result = evaluate(state, table)
    assert result["status"] == "MISSING_EVIDENCE"
    assert all(item["source_id"] == "source-v3" for item in result["inputs"])
    state["datasets"].append({**state["datasets"][0], "id": "data-v3", "source_id": "source-v3", "version": 3})
    state["requirements"][0].pop("table_title")
    state["requirements"][0]["dataset_id"] = "data-v2"
    assert evaluate(state, table)["status"] == "NEEDS_REVIEW"


def test_pdf_provider_complete_flag_never_replaces_explicit_hash_bound_verification():
    state, table = fixture()
    source = state["sources"][0]
    source.update(media_type="application/pdf", coverage={"complete": True, "provider_complete": True})
    assert evaluate(state, table)["status"] == "NEEDS_REVIEW"
    source["completeness_verified"] = True
    source["completeness_verified_hash"] = "other-bytes"
    assert evaluate(state, table)["status"] == "NEEDS_REVIEW"
    source["completeness_verified_hash"] = source["content_hash"]
    assert evaluate(state, table)["status"] == "PASS"


@pytest.mark.parametrize("as_of,expected", [(None, "NEEDS_REVIEW"), ("2026-01-01", "MISSING_EVIDENCE"), ("2026-09-10", "NEEDS_REVIEW"), ("nonsense", "NEEDS_REVIEW")])
def test_explicit_freshness_missing_stale_future_or_invalid_date_needs_review(as_of, expected):
    state, table = fixture()
    state["requirements"][0]["freshness_days"] = 5
    state["sources"][0]["as_of"] = as_of
    assert evaluate(state, table)["status"] == expected


def test_unresolved_source_issue_cannot_be_overridden_by_accepted_dataset():
    state, table = fixture()
    state["issues"] = [{"source_id": "source-v2", "severity": "error", "code": "incomplete_page"}]
    assert evaluate(state, table)["status"] == "NEEDS_REVIEW"


def test_required_fields_and_uniqueness_are_real_row_checks():
    state, table = fixture("required_fields", {"columns": ["account", "amount"]})
    assert evaluate(state, table)["status"] == "PASS"
    table["rows"][1]["values"]["account"] = ""
    result = evaluate(state, table)
    assert result["status"] == "FAIL" and result["actual"] == "1"
    assert result["operands"]["failures"][0] == {"row_id": "row-2", "column_key": "account"}
    state["requirements"][0].update(kind="unique", parameters={"columns": ["account"]})
    table["rows"][1]["values"]["account"] = "001"
    result = evaluate(state, table)
    assert result["status"] == "FAIL"
    assert result["operands"]["failures"][0]["duplicate_of"] == "row-1"


def test_total_is_decimal_exact_with_operands_and_citations_and_no_input_mutation():
    state, table = fixture("total", {"column": "amount", "expected": "0.3", "tolerance": "0", "currency_column": "currency", "currency": "GBP"})
    before = deepcopy(table)
    result = evaluate(state, table)
    assert result["status"] == "PASS" and result["actual"] == "0.3" and result["difference"] == "0.0"
    assert result["operands"]["values"] == ["0.1", "0.2"]
    assert result["operands"]["context"]["currency"]["checked"]
    assert {item["locator"]["row"] for item in result["citations"]} == {2, 3}
    assert table == before
    state["requirements"][0]["parameters"]["expected"] = "0.4"
    assert evaluate(state, table)["status"] == "FAIL"


def test_missing_numeric_operand_and_invalid_decimal_are_distinct_with_location():
    state, table = fixture("total", {"column": "amount", "expected": "0.3"})
    table["rows"][1]["values"]["amount"] = None
    result = evaluate(state, table)
    assert result["status"] == "MISSING_EVIDENCE" and result["citations"]
    table["rows"][1]["values"]["amount"] = "1,234"
    assert evaluate(state, table)["status"] == "ERROR"


def test_context_mismatch_is_not_a_cross_currency_sum():
    state, table = fixture("total", {"column": "amount", "expected": "0.3", "currency_column": "currency", "currency": "GBP"})
    table["rows"][1]["values"]["currency"] = "EUR"
    result = evaluate(state, table)
    assert result["status"] == "NEEDS_REVIEW" and "actual" not in result


def test_bank_balance_uses_explicit_signs_and_reports_exact_equation():
    state, table = fixture("bank_balance", {"opening": "1000", "closing": "1075", "credit_column": "credit", "debit_column": "debit", "debit_sign": "negative", "currency_column": "currency", "currency": "GBP"})
    result = evaluate(state, table)
    assert result["status"] == "PASS" and result["actual"] == "1075.00"
    assert result["operands"]["credits"] == "100.00" and result["operands"]["debits"] == "-25.00"
    state["requirements"][0]["parameters"]["closing"] = "1076"
    result = evaluate(state, table)
    assert result["status"] == "FAIL" and result["difference"] == "-1.00"
    state["requirements"][0]["parameters"]["debit_sign"] = "positive"
    assert evaluate(state, table)["status"] == "NEEDS_REVIEW"
    table["rows"][1]["values"]["debit"] = "25.00"
    state["requirements"][0]["parameters"]["closing"] = "1075"
    assert evaluate(state, table)["status"] == "PASS"


def test_bank_two_missing_sides_cannot_be_invented_as_zero():
    state, table = fixture("bank_balance", {"opening": "1000", "closing": "1000", "credit_column": "credit", "debit_column": "debit", "debit_sign": "negative"})
    table["rows"][0]["values"].update(credit=None, debit=None)
    assert evaluate(state, table)["status"] == "MISSING_EVIDENCE"


def test_fee_requires_versioned_management_approval_and_explicit_rule_math():
    parameters = {"base_column": "base", "actual_column": "fee", "rate": "0.01", "scale": 2,
                  "rule_id": "approved-fee", "rule_version": "v1", "rule_approved_by": "manager"}
    state, table = fixture("fee", parameters)
    result = evaluate(state, table)
    assert result["status"] == "PASS" and result["expected"] == "30.00"
    assert result["operands"]["formula"] == "sum(base) * rate; round once"
    assert result["operands"]["rule_version"] == "v1"
    state["requirements"][0]["parameters"]["rule_approved_by"] = "investor"
    assert evaluate(state, table)["status"] == "NEEDS_REVIEW"
    state["requirements"][0]["parameters"].pop("rule_approved_by")
    assert evaluate(state, table)["status"] == "NEEDS_REVIEW"


def test_excluded_source_rows_do_not_contribute_and_empty_included_table_is_missing():
    state, table = fixture("total", {"column": "amount", "expected": "0.1"})
    table["rows"][1]["excluded"] = True
    assert evaluate(state, table)["status"] == "PASS"
    table["rows"][0]["excluded"] = True
    assert evaluate(state, table)["status"] == "MISSING_EVIDENCE"


def test_task_lifecycle_deduplicates_notifications_then_reopens_after_new_failure():
    state, table = fixture()
    state["documents"][0]["current_revision_id"] = None
    evaluations = [evaluate(state, table)]
    sync_tasks(state, evaluations, NOW)
    task = state["tasks"][0]
    assert task["status"] == "open" and tasks_blocked(state)
    original_count = len(state["notifications"])
    sync_tasks(state, evaluations, NOW)
    assert len(state["tasks"]) == 1 and len(state["notifications"]) == original_count
    apply_task_action(state, task["id"], "acknowledge", "accountant", NOW, note="Received the request")
    assert task["status"] == "acknowledged"
    state["documents"][0]["current_revision_id"] = "source-v2"
    state["datasets"][0]["accepted"] = False
    sync_tasks(state, [evaluate(state, table)], NOW)
    assert task["status"] == "evidence_received"
    apply_task_action(state, task["id"], "request_verification", "accountant", NOW, note="Source is ready to inspect")
    assert task["status"] == "verification_pending"
    with pytest.raises(ValueError):
        apply_task_action(state, task["id"], "resolve", "manager", NOW, note="Cannot bypass the check")
    state["datasets"][0]["accepted"] = True
    sync_tasks(state, [evaluate(state, table)], NOW)
    assert task["status"] == "resolved" and not tasks_blocked(state)
    state["datasets"][0]["data_hash"] = "new-revision"
    sync_tasks(state, [evaluate(state, table)], NOW)
    assert task["cycle"] == 3 and task["status"] != "resolved"
    assert tasks_blocked(state)


def test_investor_task_has_no_investor_notification_before_manager_release():
    state, table = fixture()
    state["requirements"][0].update(owner_party="investor", owner_actor_id="investor")
    state["documents"][0]["current_revision_id"] = None
    sync_tasks(state, [evaluate(state, table)], NOW)
    task = state["tasks"][0]
    assert task["status"] == "pending_manager_release"
    assert {n["recipient_actor_id"] for n in state["notifications"]} == {"manager"}
    with pytest.raises(ValueError):
        apply_task_action(state, task["id"], "release", "accountant", NOW, note="Not a manager")
    apply_task_action(state, task["id"], "release", "manager", NOW, note="Release this checked request")
    assert task["status"] == "open" and task["released_by"] == "manager"
    assert sum(n["recipient_actor_id"] == "investor" for n in state["notifications"]) == 1


def test_unreleased_investor_request_resolving_still_does_not_notify_investor():
    state, table = fixture()
    state["requirements"][0].update(owner_party="investor", owner_actor_id="investor")
    state["documents"][0]["current_revision_id"] = None
    sync_tasks(state, [evaluate(state, table)], NOW)
    state["documents"][0]["current_revision_id"] = "source-v2"
    sync_tasks(state, [evaluate(state, table)], NOW)
    assert state["tasks"][0]["status"] == "resolved"
    assert not any(n["recipient_actor_id"] == "investor" for n in state["notifications"])


def test_missing_owner_routes_to_account_manager_triage_not_guessed_investor():
    state, table = fixture()
    state["requirements"][0].update(owner_party="investor", owner_actor_id="unknown")
    state["documents"][0]["current_revision_id"] = None
    sync_tasks(state, [evaluate(state, table)], NOW)
    assert state["tasks"][0]["owner_party"] == "account_manager"
    assert state["tasks"][0]["owner_actor_id"] == "manager"


def test_overdue_and_escalation_fire_once_per_task_cycle_across_restart():
    state, table = fixture()
    state["requirements"][0].update(due_at="2026-09-01T00:00:00Z", escalate_after_days=2)
    state["documents"][0]["current_revision_id"] = None
    evaluations = [evaluate(state, table)]
    sync_tasks(state, evaluations, NOW)
    records = deepcopy(state["notifications"])
    assert sum(n["event"] == "overdue" for n in records) == 1
    assert {n["recipient_actor_id"] for n in records if n["event"] == "escalated"} == {"manager", "fund-manager"}
    restarted = deepcopy(state)
    sync_tasks(restarted, evaluations, "2026-09-20T00:00:00Z")
    assert restarted["notifications"] == records


def test_manual_flag_idempotency_separate_blocking_and_resolution():
    state, _ = fixture()
    flag = {"id": "flag-1", "title": "Clarify document", "reason": "Missing signature",
            "owner_party": "accountant", "owner_actor_id": "accountant", "document_ids": ["logical"], "blocking": True}
    task = create_manual_flag(state, flag, "manager", NOW)
    assert tasks_blocked(state)
    assert create_manual_flag(state, deepcopy(flag), "manager", NOW)["id"] == task["id"]
    assert len(state["tasks"]) == 1
    with pytest.raises(ValueError):
        create_manual_flag(state, {**flag, "reason": "Different content"}, "manager", NOW)
    apply_task_action(state, task["id"], "resolve", "manager", NOW, note="Inspected the replacement signature")
    assert not tasks_blocked(state)
    apply_task_action(state, task["id"], "reopen", "manager", NOW, note="New revision removed signature")
    assert tasks_blocked(state) and task["cycle"] == 2


def test_removed_requirement_is_withdrawn_not_falsely_marked_passed():
    state, table = fixture()
    state["documents"][0]["current_revision_id"] = None
    sync_tasks(state, [evaluate(state, table)], NOW)
    task = state["tasks"][0]
    state["requirements"] = []
    sync_tasks(state, evaluate_requirements(state, lambda _: table, NOW), NOW)
    assert not task["active"] and task["status"] != "resolved"
    assert task["events"][-1]["action"] == "requirement_withdrawn"
    assert tasks_blocked(state)  # Empty-policy task is still blocking.


def test_invalid_policy_does_not_execute_expressions_or_accept_naive_time():
    state, table = fixture()
    with pytest.raises(ValueError):
        evaluate_requirements(state, lambda _: table, datetime(2026, 9, 5))
    with pytest.raises(ValueError):
        validate_requirements([{**state["requirements"][0], "kind": "python"}])
    with pytest.raises(ValueError):
        validate_requirements([state["requirements"][0], state["requirements"][0]])
    state["requirements"][0].update(kind="total", parameters={"column": "amount", "expected": "__import__('os')"})
    assert evaluate(state, table)["status"] == "ERROR"


def test_review_and_processing_errors_route_internally_but_missing_evidence_to_owner():
    state, table = fixture()
    state["requirements"][0].update(owner_party="investor", owner_actor_id="investor")
    state["datasets"][0]["accepted"] = False
    sync_tasks(state, [evaluate(state, table)], NOW)
    task = state["tasks"][0]
    assert task["owner_party"] == "account_manager" and task["status"] == "evidence_received"
    assert task["message"] == task["description"] and "Accept" in task["message"]
    assert not any(n["recipient_actor_id"] == "investor" for n in state["notifications"])
    state["sources"][0]["status"] = "FAILED"
    sync_tasks(state, [evaluate(state, table)], NOW)
    assert task["owner_party"] == "account_manager"
    state["documents"][0]["current_revision_id"] = None
    sync_tasks(state, [evaluate(state, table)], NOW)
    assert task["owner_party"] == "investor" and task["status"] == "pending_manager_release"


def test_changed_evidence_notification_is_once_per_material_fingerprint():
    state, table = fixture("total", {"column": "amount", "expected": "1"})
    sync_tasks(state, [evaluate(state, table)], NOW)
    state["requirements"][0]["parameters"]["expected"] = "2"
    changed = evaluate(state, table)
    sync_tasks(state, [changed], NOW)
    notifications = deepcopy(state["notifications"])
    assert len([n for n in notifications if n["event"] == "evidence_changed"]) == 1
    sync_tasks(state, [changed], "2026-09-06T12:00:00Z")
    assert state["notifications"] == notifications


def test_deadline_tick_does_not_recompute_or_rewrite_task_lifecycle():
    state, _ = fixture()
    task = create_manual_flag(state, {"id": "clock", "title": "Due later", "reason": "Need source",
                              "owner_party": "accountant", "owner_actor_id": "accountant", "document_ids": [],
                              "due_at": "2026-09-06T00:00:00Z", "escalate_after_days": 1}, "manager", NOW)
    before = deepcopy(task)
    tick_deadlines(state, "2026-09-08T00:00:00Z")
    assert task["status"] == before["status"] and task["events"] == before["events"]
    assert task["updated_at"] == before["updated_at"] and task["overdue"] and task["escalated"]
    records = deepcopy(state["notifications"])
    tick_deadlines(state, "2026-09-09T00:00:00Z")
    assert state["notifications"] == records


def test_configuring_real_policy_withdraws_empty_policy_task():
    state, table = fixture()
    policy = state["requirements"]
    state["requirements"] = []
    sync_tasks(state, evaluate_requirements(state, lambda _: table, NOW), NOW)
    empty_task = state["tasks"][0]
    state["requirements"] = policy
    sync_tasks(state, evaluate_requirements(state, lambda _: table, NOW), NOW)
    assert not empty_task["active"] and not tasks_blocked(state)


def test_response_upload_preserved_without_changing_authoritative_requirement():
    state, table = fixture()
    state["requirements"][0]["document_ids"] = []
    sync_tasks(state, [evaluate(state, table)], NOW)
    task = state["tasks"][0]
    apply_task_action(state, task["id"], "evidence_received", "accountant", NOW, note="Attached response", document_ids=["logical"])
    sync_tasks(state, [evaluate(state, table)], NOW)
    assert task["response_document_ids"] == task["document_ids"] == ["logical"]
    assert state["requirements"][0]["document_ids"] == []
    assert task["evaluation_status"] == "MISSING_EVIDENCE"


def test_processing_error_task_is_deduplicated_internal_and_requires_success_to_resolve():
    state, _ = fixture()
    task = sync_processing_error(state, "provider error secret payload", NOW)
    assert task["owner_party"] == "account_manager" and task["blocking"]
    records = deepcopy(state["notifications"])
    sync_processing_error(state, "provider error secret payload", NOW)
    assert state["notifications"] == records
    assert "secret" not in str(task) and "secret" not in str(records)
    with pytest.raises(ValueError):
        apply_task_action(state, task["id"], "resolve", "manager", NOW, note="Cannot bypass processing")
    sync_processing_error(state, None, NOW)
    assert task["status"] == "resolved" and not tasks_blocked(state)
    sync_processing_error(state, "new failure", NOW)
    assert task["status"] == "open" and task["cycle"] == 2
