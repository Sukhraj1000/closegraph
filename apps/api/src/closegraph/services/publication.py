from dataclasses import dataclass
from hashlib import sha256
from closegraph.outputs.manifest import build_manifest, canonical_bytes


@dataclass(frozen=True)
class Download:
    artifact: bytes
    manifest: bytes
    freshness: str
    publication_id: str
    snapshot_version: int


def publication_record(state, artifact, approval, *, actor, at, blobs):
    manifest = canonical_bytes(build_manifest(state, artifact, approval))
    manifest_hash = blobs.put(manifest)
    identity = sha256(canonical_bytes({"scope": state["fund_id"], "pack": state["pack_id"],
                                      "manifest": manifest_hash})).hexdigest()
    return {"publication_id": identity, "artifact_id": state["candidate"]["artifact_id"],
            "manifest_id": manifest_hash, "snapshot_version": state["candidate"]["snapshot_version"],
            "snapshot_digest": state["candidate"]["snapshot_digest"], "actor": actor, "at": at,
            "version": state["version"] + 1, "approved_version": state["version"]}
