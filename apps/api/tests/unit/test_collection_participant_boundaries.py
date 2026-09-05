"""Regression boundaries for restricted evidence participants and output release."""
from contextlib import contextmanager
from copy import deepcopy

import pytest

from closegraph.api.ports import DomainForbidden
from closegraph.collections.service import CollectionServices


class _Auth:
    def __init__(self, role):
        self.role = role

    def collection_actor(self, actor):
        return {"actor_id": actor, "role": self.role}


def _state(role):
    party = {"INVESTOR": "investor", "FUND_MANAGER": "fund_manager", "PREPARER": "accountant"}[role]
    return {
        "id": "collection", "tenant_id": "tenant", "fund_id": "fund", "version": 8,
        "title": "Collection", "status": "APPROVED", "documents": [{"id": "visible"}, {"id": "private"}],
        "sources": [{"id": "s-visible", "document_id": "visible"}, {"id": "s-private", "document_id": "private"}],
        "datasets": [{"id": "d-visible", "source_id": "s-visible"}, {"id": "d-private", "source_id": "s-private"}],
        "members": [{"actor_id": "person", "party": party, "document_ids": ["visible"]}],
        "tasks": [], "notifications": [], "comparisons": [], "issues": [], "history": [],
        "steps": [], "candidates": [], "artifacts": [], "requirements": [], "check_results": [],
        "recipe": {"secret": "full output recipe"}, "review": {"secret": "internal review"},
        "summary": {}, "idempotency": {}, "retired_datasets": [],
        "preserved_output": {"check_results": [{"secret": "private financial values"}], "review": {"actor_id": "reviewer"}},
        "recipe_checks": [{"id": "private-check", "table_id": "private-output", "passed": True}],
        "mapping_rebindings": [{"from": "private-old", "to": "private-new"}],
        "future_private_field": {"secret": "new internal state"},
    }


@pytest.mark.parametrize("role", ["INVESTOR", "FUND_MANAGER"])
def test_restricted_participant_cannot_release_even_preapproved_output(role):
    state = _state(role)

    class BoundaryServices(CollectionServices):
        @contextmanager
        def _locked(self, identity, actor, action, expected=None):
            self._authorize_state(state, actor, action, {("tenant", "fund")})
            yield None, None, state

        def _check_review_gate(self, state):
            pytest.fail("Restricted participant reached output release review gate")

    service = BoundaryServices(None, None, _Auth(role))
    with pytest.raises(DomainForbidden):
        service.export("collection", "person", 8, "known-output", "csv")
    assert state["artifacts"] == []


@pytest.mark.parametrize("role", ["INVESTOR", "FUND_MANAGER"])
def test_restricted_projection_never_exposes_preserved_or_unlisted_internal_state(role):
    service = CollectionServices(None, None, _Auth(role))
    state = _state(role)
    projected = service._project(state, "person", deepcopy(state))
    for key in ("preserved_output", "recipe_checks", "mapping_rebindings", "future_private_field"):
        assert key not in projected
    assert [source["id"] for source in projected["sources"]] == ["s-visible"]
    assert [dataset["id"] for dataset in projected["datasets"]] == ["d-visible"]
    assert state["preserved_output"]["check_results"]  # Projection never mutates authoritative state.


def test_internal_projection_also_hides_preservation_implementation_state():
    service = CollectionServices(None, None, _Auth("PREPARER"))
    state = _state("PREPARER")
    projected = service._project(state, "person", deepcopy(state))
    assert "preserved_output" not in projected
    assert projected["recipe"] == state["recipe"]
