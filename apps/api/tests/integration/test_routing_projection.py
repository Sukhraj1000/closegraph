from copy import deepcopy

from closegraph.api.services import PostgreSQLPackServices
from closegraph.services.lifecycle import LifecycleService
from .lifecycle_support import synthetic_service,repair


def checked_state():
    service=synthetic_service()
    state=repair(service)
    state["priority_policy"]={"version":"synthetic-review-priority-v1","materiality_decimal":"1000",
                              "currency":"GBP","impact_threshold":2}
    return service,state


def test_ready_explanation_keeps_checks_signals_and_human_approval_separate():
    service,state=checked_state()
    assert service._routing(state)=="READY_FOR_QUICK_REVIEW"
    response=PostgreSQLPackServices._snapshot(state)
    explanation=response.routing_explanation
    assert explanation["required_check_coverage"]==(1,1)
    assert explanation["unsatisfied_check_ids"]==()
    assert explanation["agreement"]=="NOT_RUN"
    assert explanation["confidence"]["status"]=="NOT_APPLICABLE"
    assert response.review_status=="PENDING" and explanation["review_status"]=="PENDING"
    assert response.priority["level"]=="STANDARD"
    assert response.priority["amount_decimal"]=="990.00"
    assert response.priority["reasons"]==["below_configured_priority_thresholds"]
    assert "probability" not in response.priority


def test_required_relationship_is_leading_reason_even_with_high_priority():
    service,state=checked_state()
    state["checks"][0]["status"]="FAIL"
    state["priority_policy"]["materiality_decimal"]="1"
    state["observations"]=[{"primary":{"entity_id":"e","metric":"fee","period":"p","currency":"GBP",
                                     "raw_scale":"1","value_decimal":"10"},
                            "secondary":{"entity_id":"e","metric":"fee","period":"p","currency":"GBP",
                                         "raw_scale":"1","value_decimal":"10"}}]
    assert service._routing(state)=="BLOCKED"
    assert state["priority"]["level"]=="HIGH"
    explanation=state["routing_explanation"]
    assert explanation["reasons"][0]=="required_check:fee:FAIL"
    assert explanation["unsatisfied_check_ids"]==("fee",)
    assert explanation["agreement"]=="AGREE"


def test_missing_currency_threshold_amount_and_dependency_proof_are_not_invented():
    service,original=checked_state()
    for mutate,reason in [
        (lambda s:s.pop("priority_policy"),"materiality_policy_not_configured"),
        (lambda s:s["facts"][0].update(currency=None),"amount_currency_context_unavailable"),
        (lambda s:s["values"].pop("total"),"exact_amount_or_materiality_unavailable"),
        (lambda s:s.update(dependency_coverage=False),"downstream_impact_unverifiable"),
        (lambda s:s["priority_policy"].update(materiality_decimal=1000.0),"exact_amount_or_materiality_unavailable"),
    ]:
        state=deepcopy(original);mutate(state)
        priority=LifecycleService.review_priority(state)
        assert priority["status"]=="UNAVAILABLE" and priority["level"] is None
        assert priority["reasons"]==[reason]


def test_current_mutation_clears_old_ready_explanation_and_priority():
    service,state=checked_state()
    service._routing(state)
    service._stale(state)
    response=PostgreSQLPackServices._snapshot(state)
    assert response.routing_status=="BLOCKED" and response.execution_status=="PENDING"
    assert response.routing_explanation is None and response.priority["status"]=="UNAVAILABLE"
    assert response.routing_reasons==("processing_required",)
