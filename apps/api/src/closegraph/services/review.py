"""Approval records bind a candidate; they never modify financial checks."""
from copy import deepcopy
from closegraph.outputs.manifest import snapshot_digest
from .errors import DomainError


def independent(state, actor):
    preparers = set(state.get("contributors", [])) | {state.get("prepared_by")}
    if actor in preparers:
        raise DomainError("Independent reviewer required")


def make_approval(state, *, actor, note, attested, at, adjudication=None):
    independent(state, actor)
    if not isinstance(note, str) or not note.strip() or attested is not True:
        raise DomainError("Review note and explicit attestation required")
    if state["routing_status"] == "NEEDS_REVIEW":
        if (not isinstance(adjudication, dict) or not isinstance(adjudication.get("reason"), str)
                or not adjudication["reason"].strip() or not adjudication.get("source_ids")
                or not isinstance(adjudication["source_ids"], list)
                or any(s not in state["evidence"] for s in adjudication["source_ids"])):
            raise DomainError("Evidence-backed soft-signal adjudication required")
    return {"decision": "APPROVED", "actor": actor, "at": at, "scope": state["fund_id"],
            "pack_id": state["pack_id"], "note": note.strip(), "attested": True,
            "snapshot_version": state["candidate"]["snapshot_version"],
            "snapshot_digest": snapshot_digest(state), "artifact_id": state["candidate"]["artifact_id"],
            "adjudication": deepcopy(adjudication)}


def verify_approval(state):
    approval = state.get("approval")
    candidate = state.get("candidate")
    if (state.get("review_status") != "APPROVED" or not approval or not candidate
            or approval.get("decision") != "APPROVED" or approval.get("attested") is not True
            or approval.get("scope") != state["fund_id"] or approval.get("pack_id") != state["pack_id"]
            or approval.get("snapshot_version") != candidate["snapshot_version"]
            or approval.get("snapshot_digest") != snapshot_digest(state)
            or approval.get("artifact_id") != candidate["artifact_id"]):
        raise DomainError("Current exact-snapshot approval required")
    expected = make_approval(state, actor=approval["actor"], note=approval["note"],
                             attested=approval["attested"], at=approval["at"],
                             adjudication=approval.get("adjudication"))
    if expected != approval:
        raise DomainError("Approval record mismatch")
    return approval
