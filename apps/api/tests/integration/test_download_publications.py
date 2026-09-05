"""Actual PostgreSQL/HTTP regressions for identical bytes across publications."""
import json
from urllib.parse import unquote

import pytest
from test_access_sessions import login
from test_routes_client import ASGIClient

from closegraph.api.app import create_app
from closegraph.api.ports import DomainNotFound
from closegraph.contracts import CorrectionRequest, ReviewRequest, VersionAction

from . import test_postgresql_lifecycle as fixtures
from .test_postgresql_lifecycle import PREPARER, REVIEWER, SCOPE, repair, run_pending

application = fixtures.application
database = fixtures.database


def release(service, state):
    approved = service.review(SCOPE, REVIEWER, ReviewRequest(
        expected_version=state.version, note="Checked the exact source-backed output", attested=True))
    return service.publish(SCOPE, REVIEWER, VersionAction(expected_version=approved.version))


def first_release_with_repeatable_bytes(application, monkeypatch):
    ready = repair(application)
    original = application.download(SCOPE, PREPARER, ready.candidate.artifact_id).content
    # Reuse valid output bytes to eliminate incidental ZIP timestamps. All financial
    # evaluation, PostgreSQL revisions, approvals and download gates remain real.
    monkeypatch.setattr("closegraph.api.services.generate_workbook", lambda *_: original)
    return release(application, ready), original


def two_releases(application, monkeypatch):
    first, content = first_release_with_repeatable_bytes(application, monkeypatch)
    ready = run_pending(application, first.version, suffix="-second")
    assert ready.candidate.artifact_id == first.candidate.artifact_id
    second = release(application, ready)
    assert len(second.publications) == 2
    assert first.publication["manifest_id"] != second.publication["manifest_id"]
    return first, second, content


def test_identical_rechecked_bytes_are_preview_then_current_publication(application, monkeypatch):
    first, content = first_release_with_repeatable_bytes(application, monkeypatch)
    ready = run_pending(application, first.version, suffix="-second")
    assert ready.candidate.artifact_id == first.candidate.artifact_id
    preview = application.download(SCOPE, PREPARER, ready.candidate.artifact_id)
    assert preview.content == content
    assert preview.filename == f"pack-v{ready.candidate.checked_version}-UNAPPROVED-PREVIEW.xlsx"

    second = release(application, ready)
    current = application.download(SCOPE, REVIEWER, second.candidate.artifact_id)
    assert current.content == content
    assert current.filename == f"pack-v{second.candidate.checked_version}-current.xlsx"
    manifest = application.download(SCOPE, REVIEWER, second.publication["manifest_id"])
    assert json.loads(manifest.content)["review"]["snapshot_version"] == second.candidate.checked_version
    assert manifest.filename == f"pack-v{second.candidate.checked_version}-current-manifest.json"


def test_publication_bound_http_links_preserve_exact_history_and_scope(application, monkeypatch):
    first, second, content = two_releases(application, monkeypatch)
    historical = application.get_history(SCOPE, REVIEWER, first.version)
    assert "publication_id=" + first.publication["publication_id"] in historical.candidate.download_url
    assert "publication_id=" + second.publication["publication_id"] in second.candidate.download_url
    client = ASGIClient(create_app(auth=application.auth, services=application))
    login(client, "reviewer", "reviewer-test-password")

    for snapshot, freshness in ((historical, "stale"), (second, "current")):
        status, headers, body = client.request("GET", snapshot.candidate.download_url)
        assert status == 200 and body == content
        assert f"pack-v{snapshot.candidate.checked_version}-{freshness}.xlsx" in unquote(headers["content-disposition"])
        status, headers, body = client.request("GET", snapshot.candidate.manifest_url)
        assert status == 200
        assert json.loads(body)["review"]["snapshot_version"] == snapshot.candidate.checked_version
        assert f"pack-v{snapshot.candidate.checked_version}-{freshness}-manifest.json" in unquote(headers["content-disposition"])

    base = f"/api/packs/pack/artifacts/{first.publication['manifest_id']}/download"
    assert client.request("GET", base + "?publication_id=" + second.publication["publication_id"])[0] == 404
    assert client.request("GET", base + "?publication_id=unknown")[0] == 404
    assert client.request("GET", second.candidate.download_url.replace("/packs/pack/", "/packs/other/"))[0] == 404
    with pytest.raises(DomainNotFound):
        application.download(SCOPE, REVIEWER, "unrelated-artifact",
                             publication_id=first.publication["publication_id"])


def test_legacy_hash_download_uses_latest_stale_release_after_mutation(application, monkeypatch):
    first, second, content = two_releases(application, monkeypatch)
    changed = application.correct(SCOPE, PREPARER, CorrectionRequest(
        expected_version=second.version, fact_id="fee", value_decimal="9",
        reason="New source-backed dispute", source_id="fee-source"))
    assert changed.candidate is None and changed.publication is None
    legacy = application.download(SCOPE, REVIEWER, second.candidate.artifact_id)
    assert legacy.content == content
    assert legacy.filename == f"pack-v{second.candidate.checked_version}-stale.xlsx"
    exact = application.download(SCOPE, REVIEWER, first.candidate.artifact_id,
                                 publication_id=first.publication["publication_id"])
    assert exact.content == content
    assert exact.filename == f"pack-v{first.candidate.checked_version}-stale.xlsx"
