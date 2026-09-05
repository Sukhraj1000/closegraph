import json
from hashlib import sha256

from closegraph.services.errors import DomainError


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def snapshot_digest(state):
    keys = ("tenant_id", "pack_id", "fund_id", "evidence", "external_freshness", "required_check_ids", "facts", "checks", "source_versions", "rule_version", "mapping_version",
            "policy_version", "rule", "mappings", "policy", "configured_records", "source_occurrences", "extraction_observations", "dependency_edges", "dependency_coverage", "template", "values", "observations")
    return sha256(canonical_bytes({k: state.get(k) for k in keys})).hexdigest()


def build_manifest(state, artifact_bytes, approval):
    candidate = state.get("candidate")
    if not candidate or sha256(artifact_bytes).hexdigest() != candidate["artifact_id"]:
        raise DomainError("Artifact hash mismatch")
    if not approval or approval.get("snapshot_digest") != snapshot_digest(state) or approval.get("artifact_id") != candidate["artifact_id"]:
        raise DomainError("Approval does not bind the exact output snapshot")
    evidence = state["evidence"]
    sources = []
    for fact in state["facts"]:
        ids = [fact.get("source", {}).get("source_id"), fact.get("correction_source_id")]
        for source_id in filter(None, ids):
            source = evidence.get(source_id)
            if not source or not source.get("content_hash") or not source.get("locator"):
                raise DomainError("Manifest evidence missing")
            sources.append({**source, "source_role":source.get("source_id", source_id), "source_id":source_id})
        if not any(ids):
            raise DomainError("Fact has no manifest lineage")
    unique = {s["source_id"]: s for s in sources}
    return {
        "schema_version":"closegraph-manifest-v1", "tenant_id":state.get("tenant_id"), "pack_id":state["pack_id"], "fund_id":state["fund_id"],
        "snapshot_version":candidate["snapshot_version"], "snapshot_digest":snapshot_digest(state),
        "artifact_sha256":candidate["artifact_id"], "as_of":approval["at"],
        "sources":[unique[k] for k in sorted(unique)], "source_versions":state["source_versions"],
        "facts":state["facts"], "checks":state["checks"], "rules":{k:state[k] for k in ("rule_version","mapping_version","policy_version")},
        "configuration_records":{k:state.get(k) for k in ("rule","mappings","policy")},
        "dependencies":state["dependency_edges"], "template":state["template"], "review":approval,
        "external_copies_recallable":False,
    }


def verify_manifest(manifest, artifact_bytes):
    if sha256(artifact_bytes).hexdigest() != manifest.get("artifact_sha256"):
        raise DomainError("Manifest artifact integrity mismatch")
    if not manifest.get("sources") or not manifest.get("checks") or not manifest.get("review"):
        raise DomainError("Incomplete manifest")
    return True
