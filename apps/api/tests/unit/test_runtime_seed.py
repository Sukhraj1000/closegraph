from copy import deepcopy
from unittest.mock import Mock

import pytest

from closegraph import runtime
from closegraph.api.ports import DomainNotFound
from closegraph.contracts import Scope


def test_runtime_seeds_two_distinct_scoped_packs_without_overwriting_existing(monkeypatch, tmp_path):
    monkeypatch.setenv("CLOSEGRAPH_DATABASE_URL", "postgresql+psycopg://unit-only")
    monkeypatch.setenv("CLOSEGRAPH_PREPARER_PASSWORD", "synthetic-preparer-password")
    monkeypatch.setenv("CLOSEGRAPH_REVIEWER_PASSWORD", "synthetic-reviewer-password")
    monkeypatch.setenv("CLOSEGRAPH_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLOSEGRAPH_PDF_MODE", "DISABLED")
    monkeypatch.setattr(runtime, "make_engine", Mock(return_value=object()))
    monkeypatch.setattr(runtime, "session_factory", Mock(return_value=object()))
    packs = {}

    class FakeServices:
        def __init__(self, sessions, blobs, auth, evaluator):
            self.auth = auth

        def get_pack(self, scope, actor):
            self.auth.require(actor.actor_id, scope, "inspect")
            if scope.pack_id not in packs:
                raise DomainNotFound()
            return deepcopy(packs[scope.pack_id])

        def create_pack(self, scope, actor, state):
            self.auth.require(actor.actor_id, scope, "upload")
            assert scope.pack_id not in packs
            packs[scope.pack_id] = deepcopy(state)

    monkeypatch.setattr(runtime, "PostgreSQLPackServices", FakeServices)
    services = runtime.build_services(seed=True)
    assert set(packs) == {"synthetic-pack", "synthetic-pdf-pack"}
    assert packs["synthetic-pack"]["title"] != packs["synthetic-pdf-pack"]["title"]
    assert services.pdf_evidence.mode == "DISABLED"
    scopes = runtime.development_scopes()
    assert scopes[0].tenant_id == scopes[1].tenant_id
    assert scopes[0].fund_id == scopes[1].fund_id
    assert scopes[0].pack_id != scopes[1].pack_id
    for actor in ("preparer", "reviewer"):
        for scope in scopes:
            services.auth.require(actor, scope, "inspect")
        with pytest.raises(DomainNotFound):
            services.auth.require(actor, Scope(tenant_id="foreign", fund_id=scopes[0].fund_id,
                                               pack_id=scopes[0].pack_id), "inspect")
    packs["synthetic-pdf-pack"]["evidence"]["pdf-only"] = {"value": "synthetic"}
    packs["synthetic-pack"]["publications"].append({"id": "existing-release"})
    assert packs["synthetic-pack"]["evidence"] == {}
    assert packs["synthetic-pdf-pack"]["publications"] == []
    runtime.build_services(seed=True)
    assert packs["synthetic-pack"]["publications"] == [{"id": "existing-release"}]
    assert packs["synthetic-pdf-pack"]["evidence"]["pdf-only"]["value"] == "synthetic"


def test_empty_states_share_no_mutable_evidence_or_facts():
    native, pdf = runtime.empty_state(), runtime.empty_state(pdf=True)
    pdf["facts"].append({"raw_value": "synthetic PDF"})
    pdf["source_versions"]["pdf-only"] = 1
    assert native["facts"] == [] and native["source_versions"] == {}
    assert native["native"] is True and pdf["native"] is False
