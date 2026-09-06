"""Release guards with real authority and stored evidence; SQL sessions are stubbed."""
from copy import deepcopy
from unittest.mock import MagicMock, Mock

import pytest
from test_fund_review import reference

from closegraph.api.auth import DevAccount, LocalAuth
from closegraph.api.ports import DomainConflict, DomainForbidden, DomainNotFound
from closegraph.collections.documents import add_source_revision
from closegraph.collections.models import CollectionJobRow, CollectionRow
from closegraph.collections.service import CollectionServices
from closegraph.storage.blobs import LocalBlobStore


@pytest.fixture(scope="module")
def accounts():
    return [DevAccount.create(name, "synthetic-test-password", role, []) for name, role in (
        ("preparer", "PREPARER"), ("reviewer", "REVIEWER"))]


@pytest.fixture
def review_case(accounts, tmp_path):
    auth = LocalAuth(accounts=accounts, collection_grants={
        account.username: [("tenant", "fund")] for account in accounts})
    sessions = MagicMock()
    service = CollectionServices(sessions, LocalBlobStore(tmp_path / "blobs"), auth)
    tables, config = reference()
    state = service._initialize({
        "id": "collection", "tenant_id": "tenant", "fund_id": "fund", "version": 1,
        "title": "Synthetic reporting review", "status": "NEEDS_REVIEW",
        "sources": [], "datasets": [], "issues": [], "history": [],
        "contributors": ["preparer"], "artifacts": [], "candidates": [], "steps": [],
        "recipe": None, "review": None, "fund_review": {"config": config},
        "members": [{"actor_id": "preparer", "party": "accountant"},
                    {"actor_id": "reviewer", "party": "account_manager"}],
    })
    for table in tables:
        state["sources"].append({
            "id": table["source_id"], "filename": table["title"] + ".csv",
            "media_type": "text/csv", "status": "EXTRACTED",
            "coverage": {"complete": True}, "content_hash": service._store(state, table),
        })
        state["datasets"].append({
            "id": table["dataset_id"], "table_id": table["dataset_id"],
            "source_id": table["source_id"], "title": table["title"],
            "columns": table["columns"], "data_hash": service._store(state, table),
            "kind": "extraction", "accepted": True, "version": 1,
            "row_count": len(table["rows"]),
        })
    service._initialize(state)
    service._compute_fund_review(state)
    assert service._fund_review_gate(state)["coverage"]["complete"]
    row = CollectionRow(id=state["id"], tenant_id="tenant", fund_id="fund", version=1,
                        state=deepcopy(state))
    sessions.return_value.__enter__.return_value.scalar.return_value = row
    return service, row


def approve_brief(service, row):
    service.fund_review_review(row.id, "reviewer", row.version, "APPROVE",
                               "Inspected the selected source records")


@pytest.mark.parametrize("path", ["output", "brief"])
@pytest.mark.parametrize("change", ["disabled", "fund_grant", "role", "membership", "contributor"])
def test_release_rechecks_stored_approver_authority_and_independence(review_case, path, change):
    service, row = review_case
    if path == "brief":
        approve_brief(service, row)
    else:
        # Output financial checks have their own suite; exercise the release authority here.
        service._check_review_gate = Mock()
        state = deepcopy(row.state)
        state["status"] = "READY_FOR_REVIEW"
        state["recipe"] = {"steps": [], "outputs": []}
        state["datasets"].append({"id": "output", "table_id": "output", "kind": "output",
                                  "data_hash": service._store(state, {"rows": []})})
        state["candidates"] = [{"candidate_id": "candidate", "dataset_id": "output",
                                "format": "csv", "content_hash": service._store(state, []),
                                "manifest_hash": service._store(state, {}),
                                "filename": "output.csv", "media_type": "text/csv"}]
        row.state = state
        service.review(row.id, "reviewer", row.version, "APPROVE", "Inspected the candidate")
    if change == "disabled":
        service.auth.disable("reviewer")
    elif change == "fund_grant":
        service.auth._collection_grants["reviewer"] = frozenset({("other-tenant", "fund")})
    elif change == "role":
        service.auth._accounts["reviewer"] = service.auth._accounts["reviewer"].model_copy(
            update={"role": "PREPARER"})
    elif change == "membership":
        row.state["members"][1]["party"] = "accountant"
    else:
        row.state["contributors"].append("reviewer")
    before = deepcopy(row.state)
    version = row.version
    with pytest.raises((DomainForbidden, DomainNotFound)):
        if path == "brief":
            service.fund_review_download(row.id, "preparer", reviewed=True)
        else:
            service.export(row.id, "preparer", row.version, "output", "csv")
    assert row.state == before  # Decisions, history and artifacts remain intact.
    assert row.version == version


@pytest.mark.parametrize("operation", ["approve", "release"])
@pytest.mark.parametrize("source_id", ["Activity", None, "unknown-source"])
@pytest.mark.parametrize("stage", ["extraction", None])
def test_fund_review_blocks_unresolved_extraction_errors(review_case, operation, source_id, stage):
    service, row = review_case
    if operation == "release":
        approve_brief(service, row)
    error = {"id": "extraction-error", "severity": "error", "stage": stage,
             "code": "spreadsheet_error", "message": "The source cell contains an error"}
    if source_id is not None:
        error["source_id"] = source_id
    row.state["issues"].append(error)
    before = deepcopy(row.state)
    with pytest.raises(DomainConflict, match="extraction errors"):
        if operation == "approve":
            approve_brief(service, row)
        else:
            service.fund_review_download(row.id, "preparer", reviewed=True)
    assert row.state == before


@pytest.mark.parametrize("status", ["QUEUED", "PROCESSING"])
@pytest.mark.parametrize("reviewed", [False, True])
def test_brief_download_during_processing_preserves_job_version(review_case, status, reviewed):
    service, row = review_case
    approve_brief(service, row)
    service.evaluate(row.id, "preparer", row.version)
    session = service.sessions.return_value.__enter__.return_value
    job = next(call.args[0] for call in session.add.call_args_list
               if isinstance(call.args[0], CollectionJobRow))
    assert job.status == "PENDING" and job.version == row.version
    # Running jobs may retain QUEUED collection status until completion.
    row.state["status"] = status
    if status == "PROCESSING":
        job.status, job.dagster_run_id = "RUNNING", "verification-run"
    before = deepcopy(row.state)
    version = row.version
    with pytest.raises(DomainConflict, match="queued or running"):
        service.fund_review_download(row.id, "preparer", reviewed=reviewed)
    assert row.state == before
    assert row.version == version
    job.status, job.dagster_run_id = "RUNNING", "verification-run"
    result = service.compute({"id": job.id, "kind": job.kind, "snapshot": job.snapshot})
    assert service._finish(session, job, result, job.dagster_run_id)["applied"]
    assert job.status == "COMPLETED"


@pytest.mark.parametrize("issue", [
    {"source_id": "Activity", "severity": "warning"},
    {"source_id": "Activity", "severity": "error", "resolved": True},
])
def test_resolved_errors_and_warnings_allow_reviewed_brief(review_case, issue):
    service, row = review_case
    row.state["issues"].append({"id": "issue", "stage": "extraction", **issue})
    approve_brief(service, row)
    content, _, filename = service.fund_review_download(row.id, "preparer", reviewed=True)
    assert filename == "reviewed-fund-review.html"
    assert b"Reviewed for the selected checks" in content


def test_historical_extraction_error_does_not_block_current_review(review_case):
    service, row = review_case
    state = deepcopy(row.state)
    source = state["sources"][0]
    current = add_source_revision(
        state, {**source, "id": "corrected-source"}, document_id=source["document_id"],
        parent_revision_id=source["id"], reason="Corrected source", actor="preparer")
    state["datasets"][0]["source_id"] = current["id"]
    state["issues"].append({"id": "old-error", "source_id": source["id"],
                            "severity": "error", "stage": "extraction"})
    service._compute_fund_review(state)
    row.state = state
    approve_brief(service, row)
    assert service.fund_review_download(row.id, "preparer", reviewed=True)[2] == "reviewed-fund-review.html"
    assert row.state["issues"] == state["issues"]
