import json
from io import BytesIO

from openpyxl import load_workbook

from closegraph.contracts import Scope
from closegraph.fixtures import SCOPE, fixture_bytes
from closegraph.outputs.manifest import build_manifest
from closegraph.runtime import empty_state
from closegraph.services.lifecycle import LifecycleService
from closegraph.services.native import evaluate_pack, ingest_sources
from closegraph.services.repository import MemoryAuthorizer, MemoryBlobs, MemoryRepository


def released_native_pack():
    blobs = MemoryBlobs()
    fixtures = fixture_bytes()
    state = {**empty_state(), **SCOPE, "version": 1, "receipts": []}
    for role, name in (("capital", "capital.csv"), ("fee-rule", "fee-rule.csv"),
                       ("original", "original.xlsx")):
        state["receipts"].append({
            "source_id": role, "document_version_id": role + "-v1", "version": 1,
            "content_hash": blobs.put(fixtures[name]), "filename": name,
        })
    state.update(ingest_sources(state, blobs, scope=Scope(**SCOPE)))
    repository = MemoryRepository()
    repository.create(state)
    fund, pack = SCOPE["fund_id"], SCOPE["pack_id"]
    auth = MemoryAuthorizer({
        ("preparer", fund): {"inspect", "correct", "recompute"},
        ("reviewer", fund): {"inspect", "review", "publish", "download"},
    })
    lifecycle = LifecycleService(repository, blobs, auth, evaluate_pack)
    correction_anchor = next(key for key, item in state["evidence"].items()
                             if item["source_id"] == "fee-rule")
    for fact_id in ("fee", "statement_fee"):
        state = lifecycle.correct(pack, actor="preparer", scope=fund,
                                  expected_version=state["version"], fact_id=fact_id,
                                  value_decimal="60000", reason="Synthetic capital and approved fee rate",
                                  source_id=correction_anchor)
    state = lifecycle.recompute(pack, actor="preparer", scope=fund,
                                expected_version=state["version"])
    assert state["routing_status"] == "READY_FOR_QUICK_REVIEW"
    state = lifecycle.review(pack, actor="reviewer", scope=fund,
                             expected_version=state["version"],
                             note="Checked original and correction source anchors", attested=True)
    state = lifecycle.publish(pack, actor="reviewer", scope=fund,
                              expected_version=state["version"])
    downloaded = lifecycle.download(pack, actor="reviewer", scope=fund)
    return state, downloaded, blobs, fixtures


def test_every_original_and_correction_reference_resolves_to_its_exact_manifest_anchor():
    state, downloaded, _, _ = released_native_pack()
    manifest = json.loads(downloaded.manifest)
    references = {identity for fact in state["facts"]
                  for identity in (fact["source"]["source_id"], fact.get("correction_source_id"))
                  if identity is not None}
    sources = {item["source_id"]: item for item in manifest["sources"]}
    assert len(sources) == len(manifest["sources"]) == len(references) == 4
    assert set(sources) == references
    for identity in references:
        original = state["evidence"][identity]
        assert sources[identity]["locator"] == original["locator"]
        assert sources[identity]["document_version_id"] == original["document_version_id"]
        assert sources[identity]["content_hash"] == original["content_hash"]
        assert sources[identity]["fact_ids"] == original["fact_ids"]
        assert sources[identity]["source_role"] == original["source_id"]
    originals = [item for item in manifest["sources"] if item["source_role"] == "original"]
    assert {item["locator"]["cell"] for item in originals} == {"B6", "B7"}


def test_released_native_output_and_manifest_preserve_the_source_template_and_both_citations():
    state, downloaded, blobs, fixtures = released_native_pack()
    book = load_workbook(BytesIO(downloaded.artifact))
    assert [book["Pack"][cell].value for cell in ("B6", "B7", "B8")] == [60000] * 3
    assert blobs.get(state["template"]["template_hash"]) == fixtures["original.xlsx"]
    manifest = json.loads(downloaded.manifest)
    assert manifest == build_manifest(state, downloaded.artifact, state["approval"])
    assert manifest["review"]["actor"] == "reviewer"
    assert manifest["artifact_sha256"] == state["candidate"]["artifact_id"]
    assert downloaded.freshness == "CURRENT"
    by_id = {source["source_id"]: source for source in manifest["sources"]}
    for fact in manifest["facts"]:
        assert by_id[fact["source"]["source_id"]]["locator"] == fact["source"]["locator"]
        if fact.get("correction_source_id"):
            assert by_id[fact["correction_source_id"]]["source_role"] == "fee-rule"
