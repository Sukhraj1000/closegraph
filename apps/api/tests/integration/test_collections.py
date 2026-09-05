"""Real PostgreSQL/ASGI contracts for collection review and exact-byte release.

All inputs below are small synthetic native files. Parser computation, recipes,
exports, scoped blobs, SQL transactions and session enforcement are real.
"""
import base64
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from io import BytesIO
import json
from threading import Barrier, Event
from types import SimpleNamespace

from dagster import DagsterInstance, Definitions, ResourceDefinition
from openpyxl import load_workbook
import pytest

from closegraph.api.app import create_app
from closegraph.api.auth import DevAccount, LocalAuth
from closegraph.api.ports import DomainConflict, DomainForbidden, DomainNotFound
from closegraph.collections.models import CollectionJobRow, CollectionRevisionRow
from closegraph.collections.pipeline import collection_definitions
from closegraph.collections.service import CollectionServices
from closegraph.contracts import Scope
from closegraph.storage.blobs import LocalBlobStore
from test_access_sessions import login
from test_routes_client import ASGIClient

PASSWORD = "collections-only-test-password"
DATA = b"account,amount,currency\n001,12.30,GBP\n002,7.70,GBP\n"


@pytest.fixture(scope="module")
def collection_accounts():
    scope = Scope(tenant_id="tenant-a", fund_id="fund-a", pack_id="legacy-pack")
    return [DevAccount.create(name, PASSWORD, role, [scope]) for name, role in (
        ("preparer", "PREPARER"), ("reviewer", "REVIEWER"),
        ("outsider", "PREPARER"), ("legacy-only", "PREPARER"))]


@pytest.fixture
def collections(pg_sessions, tmp_path, collection_accounts):
    auth = LocalAuth(accounts=collection_accounts, collection_grants={
        "preparer": [("tenant-a", "fund-a")], "reviewer": [("tenant-a", "fund-a")],
        "outsider": [("tenant-b", "fund-a")],
    })
    return CollectionServices(pg_sessions, LocalBlobStore(tmp_path / "blobs", max_bytes=32 * 1024 * 1024), auth)


def create(service):
    return service.create("preparer", "Synthetic general collection", "fund-a")


def upload(service, state, data=DATA, name="unfamiliar-layout.csv"):
    return service.upload(state["id"], "preparer", state["version"], name,
                          "text/csv", base64.b64encode(data).decode())


def run_pending(service, identity):
    request = next(job for job in service.pending() if job["collection_id"] == identity and job["status"] == "PENDING")
    run_id = "synthetic-run-" + request["id"]
    job = service.claim(request["id"], run_id)
    assert job is not None
    result = service.compute(job)
    assert service.finish(request["id"], run_id, result)["applied"]
    return service.get(identity, "preparer")


def extracted(service, data=DATA):
    state = upload(service, create(service), data)
    state = run_pending(service, state["id"])
    assert state["status"] == "NEEDS_REVIEW", state["issues"]
    dataset = next(d for d in state["datasets"] if d["kind"] == "extraction")
    raw = service.rows(state["id"], "preparer", dataset["id"])["rows"]
    assert raw[0]["values"] == {"c1": "account", "c2": "amount", "c3": "currency"}
    assert not raw[0].get("excluded", False)
    state = service.edit(state["id"], "preparer", state["version"], dataset["id"],
                         [{"op": "set_header", "row_id": raw[0]["row_id"]}],
                         "Explicitly identify the synthetic source's header row")
    dataset = next(d for d in state["datasets"] if d["kind"] == "extraction")
    keys = {column["label"]: column["key"] for column in dataset["columns"]}
    return state, dataset, keys


def active_rows(service, state, dataset):
    return [row for row in service.rows(state["id"], "preparer", dataset["id"])["rows"]
            if not row.get("excluded")]


def define_recipe(service, state, dataset, keys, checks=None, export=None):
    spec = {"version": 1, "steps": [{"id": "selected-output", "op": "select", "input": dataset["table_id"],
             "columns": [keys["account"], keys["amount"], keys["currency"]]}],
            "output": "selected-output", "checks": checks if checks is not None else [
                {"type": "required", "columns": [keys["account"], keys["amount"]]},
                {"type": "total", "column": keys["amount"], "expected": "20.00"}],
            "export": export or {"formats": ["csv", "xlsx"]}}
    return service.recipe(state["id"], "preparer", state["version"], spec)


def ready(service):
    state, dataset, keys = extracted(service)
    state = service.accept(state["id"], "preparer", state["version"], dataset["id"])
    state = define_recipe(service, state, dataset, keys)
    state = service.process(state["id"], "preparer", state["version"])
    state = run_pending(service, state["id"])
    assert state["status"] == "READY_FOR_REVIEW", state["issues"]
    return state, dataset, keys


def approve(service, state):
    return service.review(state["id"], "reviewer", state["version"], "APPROVE", "Compared the exact source and output candidate")


def output_dataset(state):
    return next(d for d in state["datasets"] if d["kind"] == "output")


def test_scoped_fund_grants_do_not_follow_legacy_pack_or_same_named_foreign_fund(collections):
    state = create(collections)
    assert [s["id"] for s in collections.list("preparer")] == [state["id"]]
    assert collections.list("outsider") == collections.list("legacy-only") == []
    for actor in ("outsider", "legacy-only"):
        with pytest.raises(DomainNotFound):
            collections.get(state["id"], actor)
        with pytest.raises(DomainNotFound):
            collections.history(state["id"], actor)
    with pytest.raises(DomainForbidden):
        collections.create("legacy-only", "Must not inherit legacy pack access", "fund-a")
    with pytest.raises(DomainForbidden):
        collections.create("reviewer", "Reviewer cannot prepare", "fund-a")
    foreign = collections.create("outsider", "Other tenant", "fund-a")
    assert foreign["id"] != state["id"]
    assert [s["id"] for s in collections.list("outsider")] == [foreign["id"]]


def test_http_sessions_csrf_origin_schema_and_server_owned_scope(collections):
    app = create_app(auth=collections.auth, services=SimpleNamespace(collections=collections))
    client = ASGIClient(app)
    assert client.request("GET", "/api/collections")[0] == 401
    csrf, _ = login(client, "preparer", PASSWORD)
    command = {"title": "HTTP collection", "fund_id": "fund-a"}
    assert client.request("POST", "/api/collections", command)[0] == 403
    assert client.request("POST", "/api/collections", command, {"x-csrf-token": csrf, "origin": "https://other.invalid"})[0] == 403
    assert client.request("POST", "/api/collections", {**command, "tenant_id": "tenant-b"}, {"x-csrf-token": csrf})[0] == 422
    status, _, body = client.request("POST", "/api/collections", command, {"x-csrf-token": csrf})
    assert status == 201, body
    state = json.loads(body)
    other = ASGIClient(app)
    login(other, "outsider", PASSWORD)
    assert other.request("GET", "/api/collections/" + state["id"])[0] == 404
    assert json.loads(other.request("GET", "/api/collections")[2]) == []
    collections.auth.disable("preparer")
    assert client.request("GET", "/api/collections/" + state["id"])[0] == 401


def test_extracted_source_bytes_and_rows_are_scoped_paginated_and_immutable(collections):
    state, dataset, keys = extracted(collections)
    source = state["sources"][0]
    content, media_type, _ = collections.download(state["id"], "preparer", source["id"])
    assert content == DATA and media_type == "text/csv"
    assert not dataset["accepted"]
    header = collections.rows(state["id"], "preparer", dataset["id"], 0, 1)["rows"][0]
    assert header["excluded"] and header["values"][keys["account"]] == "account"
    page = collections.rows(state["id"], "preparer", dataset["id"], 2, 1)
    assert page["total"] == 3 and page["rows"][0]["values"][keys["account"]] == "002"
    assert page["rows"][0]["locators"][keys["amount"]]["kind"] == "csv"
    focused = collections.rows(state["id"], "reviewer", dataset["id"], 0, 1, page["rows"][0]["row_id"])
    assert focused["offset"] == 2
    for action in (lambda: collections.download(state["id"], "outsider", source["id"]),
                   lambda: collections.rows(state["id"], "outsider", dataset["id"])):
        with pytest.raises(DomainNotFound):
            action()


def test_transformation_requires_accepted_exact_dataset_revision(collections):
    state, dataset, keys = extracted(collections)
    state = define_recipe(collections, state, dataset, keys)
    with pytest.raises(DomainConflict):
        collections.process(state["id"], "preparer", state["version"])
    state = collections.accept(state["id"], "preparer", state["version"])
    assert state["status"] == "ACCEPTED"
    row = active_rows(collections, state, dataset)[0]
    changed = collections.edit(state["id"], "preparer", state["version"], dataset["id"],
                               [{"op": "set_cell", "row_id": row["row_id"], "column_key": keys["amount"], "value": "12.31"}], "Corrected visible source")
    assert not changed["datasets"][0]["accepted"]
    assert changed["datasets"][0]["version"] == dataset["version"] + 1
    with pytest.raises(DomainConflict):
        collections.process(changed["id"], "preparer", changed["version"])
    current = active_rows(collections, changed, dataset)[0]
    assert current["values"][keys["amount"]] == "12.31"
    assert current["raw_values"][keys["amount"]] == "12.30"
    assert current["locators"] == row["locators"]
    assert collections.download(state["id"], "preparer", state["sources"][0]["id"])[0] == DATA
    assert collections.history(state["id"], "reviewer")[-1]["event"] == "extraction_corrected"


def test_new_upload_supersedes_pending_snapshot_without_losing_sources(collections):
    state = upload(collections, create(collections))
    old = collections.pending()[0]
    state = upload(collections, state, b"account,amount,currency\n003,0,GBP\n", "second.csv")
    collections.pending()  # The dispatcher retires obsolete pending work without lock inversion.
    with collections.sessions() as session:
        assert session.get(CollectionJobRow, old["id"]).status == "SUPERSEDED"
    assert collections.claim(old["id"], "obsolete-run") is None
    state = run_pending(collections, state["id"])
    assert len(state["sources"]) == 2 and len(state["datasets"]) == 2
    assert state["summary"]["row_count"] == 5  # Both literal header rows remain in raw extraction.


def test_running_old_job_cannot_overwrite_new_upload(collections):
    state = upload(collections, create(collections))
    request = collections.pending()[0]
    job = collections.claim(request["id"], "old-run")
    result = collections.compute(job)
    newer = upload(collections, state, b"account,amount,currency\n003,0,GBP\n", "new.csv")
    completed = collections.finish(request["id"], "old-run", result)
    assert not completed["applied"] and completed.get("superseded")
    current = collections.get(state["id"], "preparer")
    assert current["version"] == newer["version"] and len(current["sources"]) == 2
    assert any(j["status"] == "PENDING" for j in collections.pending())
    assert len(run_pending(collections, state["id"])["datasets"]) == 2


def test_duplicate_claim_completion_and_restart_preserve_one_result(collections):
    state = upload(collections, create(collections))
    request = collections.pending()[0]
    job = collections.claim(request["id"], "owner")
    assert collections.claim(request["id"], "competitor") is None
    result = collections.compute(job)
    assert not collections.finish(request["id"], "competitor", result)["applied"]
    assert collections.finish(request["id"], "owner", result)["applied"]
    version = collections.get(state["id"], "preparer")["version"]
    assert not collections.finish(request["id"], "owner", result)["applied"]
    restarted = CollectionServices(collections.sessions, collections.blob_store, collections.auth)
    assert restarted.get(state["id"], "preparer")["version"] == version
    assert restarted.pending() == []
    assert restarted.claim(request["id"], "owner") is None


def test_mutations_except_upload_are_blocked_during_queued_work(collections):
    state, dataset, keys = extracted(collections)
    state = collections.accept(state["id"], "preparer", state["version"])
    state = define_recipe(collections, state, dataset, keys)
    queued = collections.process(state["id"], "preparer", state["version"])
    row = active_rows(collections, queued, dataset)[0]
    commands = [
        lambda: collections.accept(queued["id"], "preparer", queued["version"]),
        lambda: collections.recipe(queued["id"], "preparer", queued["version"], state["recipe"]),
        lambda: collections.process(queued["id"], "preparer", queued["version"]),
        lambda: collections.edit(queued["id"], "preparer", queued["version"], dataset["id"], [{"op": "set_cell", "row_id": row["row_id"], "column_key": keys["amount"], "value": "1"}], "Do not edit during processing"),
    ]
    for command in commands:
        with pytest.raises(DomainConflict):
            command()
    assert collections.get(queued["id"], "preparer")["version"] == queued["version"]
    assert upload(collections, queued, DATA, "additional.csv")["version"] == queued["version"] + 1


def test_required_check_failure_preserves_output_but_prevents_review_and_release(collections):
    state, dataset, keys = extracted(collections)
    state = collections.accept(state["id"], "preparer", state["version"])
    state = define_recipe(collections, state, dataset, keys, [{"type": "total", "column": keys["amount"], "expected": "999.00"}])
    state = collections.process(state["id"], "preparer", state["version"])
    state = run_pending(collections, state["id"])
    assert state["status"] == "BLOCKED"
    assert any(issue["code"] == "total_mismatch" and issue["severity"] == "error" for issue in state["issues"])
    dataset = output_dataset(state)
    assert dataset["row_count"] == 2 and state["candidates"] == []
    with pytest.raises(DomainConflict):
        approve(collections, state)
    with pytest.raises(DomainConflict):
        collections.export(state["id"], "reviewer", state["version"], dataset["id"], "csv")


def test_exact_candidate_bytes_are_previewed_then_independently_released(collections):
    state, _, _ = ready(collections)
    candidate = next(c for c in state["candidates"] if c["format"] == "xlsx")
    content, media_type, name = collections.download(state["id"], "reviewer", candidate["candidate_id"], candidate=True)
    assert name.startswith("DRAFT-")
    assert sha256(content).hexdigest() == candidate["verification"]["content_sha256"]
    book = load_workbook(BytesIO(content))
    assert book["Export"]["A2"].value == "001" and book["Export"]["B2"].value == "12.30"
    with pytest.raises(DomainConflict):
        collections.export(state["id"], "reviewer", state["version"], candidate["dataset_id"], "xlsx")
    approved = approve(collections, state)
    assert approved["review"]["snapshot_version"] == state["version"]
    release = collections.export(state["id"], "reviewer", approved["version"], candidate["dataset_id"], "xlsx")
    actual, actual_type, filename = collections.download(state["id"], "reviewer", release["artifact_id"], artifact=True)
    assert actual == content and actual_type == media_type and not filename.startswith("DRAFT-")
    manifest_id = release["manifest_url"].rsplit("/", 1)[-1]
    manifest = json.loads(collections.download(state["id"], "reviewer", manifest_id, artifact=True)[0])
    assert manifest["artifact"]["content_hash"] == sha256(content).hexdigest()
    assert manifest["review"]["actor_id"] == "reviewer"
    assert manifest["review"]["snapshot_version"] == state["version"]
    assert manifest["source_to_output"]["cells"]
    assert sha256(json.dumps(manifest["source_to_output"], sort_keys=True).encode()).hexdigest() == manifest["artifact"]["verification"]["source_manifest_sha256"]
    with pytest.raises(DomainNotFound):
        collections.download(state["id"], "outsider", release["artifact_id"], artifact=True)


def test_output_approval_rejects_contributor_even_after_role_change(collections):
    state, _, _ = ready(collections)
    with collections.auth._lock:
        account = collections.auth._accounts["preparer"]
        collections.auth._accounts["preparer"] = account.model_copy(update={"role": "REVIEWER"})
    with pytest.raises(DomainForbidden):
        collections.review(state["id"], "preparer", state["version"], "APPROVE", "Cannot approve own preparation after role change")
    assert approve(collections, state)["status"] == "APPROVED"


def test_recipe_bindings_and_format_cannot_change_after_review(collections):
    state, _, _ = ready(collections)
    approved = approve(collections, state)
    dataset = output_dataset(approved)
    for overrides in ({"bindings": {"sheet": "Another sheet"}}, {"template_source_id": "foreign-template"}):
        with pytest.raises(DomainConflict):
            collections.export(state["id"], "reviewer", approved["version"], dataset["id"], "xlsx", **overrides)
    with pytest.raises(DomainConflict):
        collections.export(state["id"], "reviewer", state["version"], dataset["id"], "xlsx")


def test_correction_invalidates_approval_candidates_and_marks_old_artifacts_historical(collections):
    state, source_dataset, keys = ready(collections)
    approved = approve(collections, state)
    output = output_dataset(approved)
    release = collections.export(state["id"], "reviewer", approved["version"], output["id"], "csv")
    historical = collections.download(state["id"], "reviewer", release["artifact_id"], artifact=True)[0]
    state = collections.get(state["id"], "preparer")
    row = active_rows(collections, state, source_dataset)[0]
    changed = collections.edit(state["id"], "preparer", state["version"], source_dataset["id"], [{"op": "set_cell", "row_id": row["row_id"], "column_key": keys["amount"], "value": "12.31"}], "New correction requires new review")
    assert changed["review"] is None and changed["candidates"] == []
    assert not any(d["kind"] == "output" for d in changed["datasets"])
    assert all(a["historical"] for a in changed["artifacts"])
    assert collections.download(state["id"], "reviewer", release["artifact_id"], artifact=True)[0] == historical
    with pytest.raises((DomainConflict, DomainNotFound)):
        collections.export(state["id"], "reviewer", changed["version"], output["id"], "csv")
    for candidate in approved["candidates"]:
        with pytest.raises(DomainNotFound):
            collections.download(state["id"], "reviewer", candidate["candidate_id"], candidate=True)


def test_excluded_rows_are_retained_for_inspection_but_not_transformed(collections):
    state, dataset, keys = extracted(collections)
    row = active_rows(collections, state, dataset)[1]
    state = collections.edit(state["id"], "preparer", state["version"], dataset["id"], [{"op": "exclude_row", "row_id": row["row_id"], "reason": "Explicit test exclusion"}], "Ignore the declared row")
    assert len(collections.rows(state["id"], "preparer", dataset["id"])["rows"]) == 3
    state = collections.accept(state["id"], "preparer", state["version"])
    state = define_recipe(collections, state, dataset, keys, [{"type": "total", "column": keys["amount"], "expected": "12.30"}])
    state = collections.process(state["id"], "preparer", state["version"])
    state = run_pending(collections, state["id"])
    assert state["status"] == "READY_FOR_REVIEW", state["issues"]
    assert output_dataset(state)["row_count"] == 1


def test_split_rows_keep_original_source_row_and_locator_lineage(collections):
    state, dataset, keys = extracted(collections)
    original = active_rows(collections, state, dataset)[0]
    values = [{keys["account"]: "001-a", keys["amount"]: "6.00", keys["currency"]: "GBP"},
              {keys["account"]: "001-b", keys["amount"]: "6.30", keys["currency"]: "GBP"}]
    state = collections.edit(state["id"], "preparer", state["version"], dataset["id"], [{"op": "split_row", "row_id": original["row_id"], "values": values}], "Explicit split of a combined record")
    state = collections.accept(state["id"], "preparer", state["version"])
    state = define_recipe(collections, state, dataset, keys)
    state = collections.process(state["id"], "preparer", state["version"])
    state = run_pending(collections, state["id"])
    output = collections.rows(state["id"], "preparer", output_dataset(state)["id"])["rows"]
    assert len(output) == 3
    for row in output[:2]:
        refs = row["lineage"][keys["amount"]]
        assert {ref["row_id"] for ref in refs} == {original["row_id"]}
        assert refs[0]["locator"] == original["locators"][keys["amount"]]


def test_explicit_reextract_retry_restores_parser_draft_and_requires_new_acceptance(collections):
    state, dataset, keys = extracted(collections)
    row = active_rows(collections, state, dataset)[0]
    state = collections.edit(state["id"], "preparer", state["version"], dataset["id"], [{"op": "set_cell", "row_id": row["row_id"], "column_key": keys["amount"], "value": "99.00"}], "Test retry discards current draft correction but preserves history")
    state = collections.accept(state["id"], "preparer", state["version"])
    queued = collections.process(state["id"], "preparer", state["version"], stage="extract", source_id=state["sources"][0]["id"])
    state = run_pending(collections, queued["id"])
    assert state["status"] == "NEEDS_REVIEW" and not state["datasets"][0]["accepted"]
    draft = collections.rows(state["id"], "preparer", state["datasets"][0]["id"])["rows"]
    assert draft[0]["values"][keys["amount"]] == "amount" and not draft[0].get("excluded")
    restored = draft[1]
    assert restored["values"][keys["amount"]] == "12.30"
    assert any(event["event"] == "extraction_corrected" for event in collections.history(state["id"], "reviewer"))


def test_optimistic_concurrent_writers_commit_only_one_revision(collections):
    state, dataset, keys = extracted(collections)
    row = active_rows(collections, state, dataset)[0]
    barrier = Barrier(2)
    def mutate(value):
        barrier.wait()
        try:
            return collections.edit(state["id"], "preparer", state["version"], dataset["id"], [{"op": "set_cell", "row_id": row["row_id"], "column_key": keys["amount"], "value": value}], "Concurrent source correction")
        except DomainConflict:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(mutate, "1.00"), pool.submit(mutate, "2.00")
        outcomes = [first.result(timeout=10), second.result(timeout=10)]
    assert sum(result is not None for result in outcomes) == 1
    assert collections.get(state["id"], "preparer")["version"] == state["version"] + 1


def test_collection_revision_history_is_append_only(collections):
    state = create(collections)
    with collections.sessions() as session, pytest.raises(ValueError, match="append-only"):
        record = session.get(CollectionRevisionRow, (state["id"], 1))
        record.event_type = "rewritten"
        session.flush()
    with collections.sessions() as session, pytest.raises(ValueError, match="append-only"):
        session.delete(session.get(CollectionRevisionRow, (state["id"], 1)))
        session.flush()
    assert collections.history(state["id"], "reviewer")[0]["event"] == "created"


def test_revocation_is_serialized_with_artifact_commit(collections, monkeypatch):
    state, _, _ = ready(collections)
    state = approve(collections, state)
    at_commit, allow_commit, started, revoked = Event(), Event(), Event(), Event()
    original = collections._revision
    def paused(session, row, snapshot, actor, event, detail=None, **kwargs):
        if event == "artifact_released":
            at_commit.set()
            assert allow_commit.wait(10)
        return original(session, row, snapshot, actor, event, detail, **kwargs)
    monkeypatch.setattr(collections, "_revision", paused)
    def revoke():
        started.set()
        collections.auth.disable("reviewer")
        revoked.set()
    with ThreadPoolExecutor(max_workers=2) as pool:
        releasing = pool.submit(collections.export, state["id"], "reviewer", state["version"], output_dataset(state)["id"], "csv")
        assert at_commit.wait(10)
        revoking = pool.submit(revoke)
        try:
            assert started.wait(5) and not revoked.wait(0.1)
        finally:
            allow_commit.set()
        artifact = releasing.result(timeout=10)
        revoking.result(timeout=10)
    assert artifact["artifact_id"] and revoked.is_set()
    with pytest.raises(DomainForbidden):
        collections.download(state["id"], "reviewer", artifact["artifact_id"], artifact=True)


def test_real_dagster_collection_run_finishes_at_human_review_boundary(collections, tmp_path):
    state = upload(collections, create(collections))
    request = collections.pending()[0]
    assets, job, sensor = collection_definitions(SimpleNamespace(collections=collections))
    definitions = Definitions(assets=assets, jobs=[job], sensors=[sensor], resources={
        "services": ResourceDefinition.hardcoded_resource(SimpleNamespace(collections=collections))})
    with DagsterInstance.ephemeral(tempdir=str(tmp_path)) as instance:
        result = definitions.resolve_job_def("process_collection").execute_in_process(
            instance=instance, run_config={"ops": {"collection_input": {"config": {"job_id": request["id"]}}}})
        assert result.success
    current = collections.get(state["id"], "preparer")
    assert current["status"] == "NEEDS_REVIEW" and current["processing"]["status"] == "COMPLETED"
    assert current["processing"]["run_id"] == result.run_id
    assert all(not dataset["accepted"] for dataset in current["datasets"])
    assert collections.pending() == []


def test_merged_rows_retain_all_original_source_membership(collections):
    state, dataset, keys = extracted(collections, b"account,amount,currency\n001,,GBP\n,12.30,GBP\n")
    original = active_rows(collections, state, dataset)
    original_ids = {row["row_id"] for row in original}
    state = collections.edit(state["id"], "preparer", state["version"], dataset["id"],
        [{"op": "merge_rows", "row_ids": [row["row_id"] for row in original]}], "Merge the explicit split source record")
    state = collections.accept(state["id"], "preparer", state["version"])
    state = define_recipe(collections, state, dataset, keys,
                          [{"type": "total", "column": keys["amount"], "expected": "12.30"}])
    state = collections.process(state["id"], "preparer", state["version"])
    state = run_pending(collections, state["id"])
    assert state["status"] == "READY_FOR_REVIEW", state["issues"]
    row = collections.rows(state["id"], "preparer", output_dataset(state)["id"])["rows"][0]
    assert row["values"][keys["amount"]] == "12.30"
    assert {ref["row_id"] for ref in row["lineage"][keys["amount"]]} == original_ids
    assert {ref["locator"]["row"] for ref in row["lineage"][keys["amount"]]} == {2, 3}


def test_http_candidate_and_release_links_serve_the_exact_reviewed_bytes(collections):
    state, _, _ = ready(collections)
    app = create_app(auth=collections.auth, services=SimpleNamespace(collections=collections))
    client = ASGIClient(app)
    csrf, _ = login(client, "reviewer", PASSWORD)
    candidate = next(c for c in state["candidates"] if c["format"] == "csv")
    status, headers, preview = client.request("GET", candidate["url"])
    assert status == 200 and "DRAFT-" in headers["content-disposition"]
    base = "/api/collections/" + state["id"]
    status, _, body = client.request("POST", base + "/review", {
        "expected_version": state["version"], "decision": "APPROVE", "reason": "Reviewed exact HTTP candidate"}, {"x-csrf-token": csrf})
    assert status == 200, body
    approved = json.loads(body)
    status, _, body = client.request("POST", base + "/exports", {
        "expected_version": approved["version"], "dataset_id": candidate["dataset_id"], "format": "csv"}, {"x-csrf-token": csrf})
    assert status == 200, body
    released = json.loads(body)
    assert client.request("GET", released["url"])[2] == preview
    status, _, manifest = client.request("GET", released["manifest_url"])
    assert status == 200 and json.loads(manifest)["artifact"]["content_hash"] == sha256(preview).hexdigest()
    other_state = collections.create("outsider", "Foreign tenant collection", "fund-a")
    assert client.request("GET", released["url"].replace(state["id"], other_state["id"]))[0] == 404
