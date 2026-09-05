"""Reference in-process adapters; production adapters must preserve these semantics."""
from copy import deepcopy
from hashlib import sha256
from threading import RLock
from typing import Protocol
from .errors import AccessDenied, Conflict, DomainError


class Repository(Protocol):
    def create(self, state: dict) -> dict: ...
    def get(self, pack_id: str, scope: str, *, version: int | None = None) -> dict: ...
    def save(self, state: dict, expected_version: int) -> dict: ...


class Blobs(Protocol):
    def put(self, data: bytes) -> str: ...
    def get(self, content_hash: str) -> bytes: ...


class Authorizer(Protocol):
    def require(self, actor: str, scope: str, action: str) -> None: ...


class MemoryRepository:
    """Copies on both boundaries; save is atomic CAS + request receipt + snapshot.

    PostgreSQL adapters must implement save in one transaction with a locked
    scoped current pointer. Request receipts live inside the snapshot dict.
    Versions are append-only, contiguous, and never overwritten.
    """
    def __init__(self):
        self._states = {}
        self._lock = RLock()

    def create(self, state):
        with self._lock:
            key = (state["fund_id"], state["pack_id"])
            if key in self._states or state.get("version") != 1:
                raise Conflict("Initial snapshot identity conflict")
            self._states[key] = [deepcopy(state)]
            return deepcopy(state)

    def get(self, pack_id, scope, *, version=None):
        with self._lock:
            versions = self._states.get((scope, pack_id))
            if not versions or (version is not None and
                                (type(version) is not int or not 1 <= version <= len(versions))):
                raise AccessDenied("Resource unavailable in scope")
            return deepcopy(versions[-1] if version is None else versions[version - 1])

    def save(self, state, expected_version):
        with self._lock:
            key = (state["fund_id"], state["pack_id"])
            current = self.get(state["pack_id"], state["fund_id"])
            if type(expected_version) is not int or current["version"] != expected_version:
                raise Conflict("Snapshot revision changed")
            if state.get("version") != expected_version + 1:
                raise Conflict("Snapshot version must advance once")
            prior_history = current.get("history", [])
            history = state.get("history", [])
            if history[:len(prior_history)] != prior_history or len(history) != len(prior_history) + 1:
                raise Conflict("History must append exactly one event")
            if any(state.get("request_receipts", {}).get(k) != v
                   for k, v in current.get("request_receipts", {}).items()):
                raise Conflict("Request receipts are immutable")
            self._states[key].append(deepcopy(state))
            return deepcopy(state)


class MemoryBlobs:
    """Content-addressed bytes. Public data is only a test fault-injection seam."""
    def __init__(self):
        self.data = {}
        self._lock = RLock()

    def put(self, data):
        if not isinstance(data, bytes):
            raise DomainError("Blob must contain actual bytes")
        identity = sha256(data).hexdigest()
        with self._lock:
            if identity in self.data and self.data[identity] != data:
                raise Conflict("Immutable blob identity conflict")
            self.data[identity] = data
        return identity

    def get(self, content_hash):
        with self._lock:
            data = self.data.get(content_hash)
            if data is None or sha256(data).hexdigest() != content_hash:
                raise DomainError("Referenced bytes missing or corrupt")
            return data


class MemoryAuthorizer:
    """Demo-only server-owned grants; never initialise from request role labels."""
    def __init__(self, grants):
        self._grants = {key: frozenset(actions) for key, actions in grants.items()}

    def require(self, actor, scope, action):
        if action not in self._grants.get((actor, scope), ()):
            raise AccessDenied("Resource unavailable in scope")

    def revoke(self, actor):
        self._grants = {key: value for key, value in self._grants.items() if key[0] != actor}


class ScopedBlobs:
    """Adapt immutable local storage to one exact server-resolved scope."""
    def __init__(self, store, scope):
        self.store, self.scope = store, scope

    def put(self, data):
        return self.store.put(self.scope, data)

    def get(self, content_hash):
        from closegraph.storage.blobs import BlobNotFound, BlobIntegrityError
        try:
            return self.store.read(self.scope, content_hash)
        except (BlobNotFound, BlobIntegrityError, ValueError) as exc:
            raise DomainError("Referenced bytes missing or corrupt") from exc


class ScopedAuthorizer:
    def __init__(self, auth, scope):
        self.auth, self.scope = auth, scope

    def require(self, actor, fund_id, action):
        if fund_id != self.scope.fund_id:
            raise AccessDenied("Resource unavailable in scope")
        self.auth.require(actor, self.scope, action)


class PostgreSQLRepository:
    """Transaction-bound immutable snapshots with a locked, scoped current row.

    A facade creates one instance inside one transaction for each whole action.
    This keeps review, publication, permission rechecks and pointer advancement in
    the same serialized critical section. No process-local state is authoritative.
    """
    def __init__(self, session, scope, blobs):
        self.session, self.scope, self.blobs = session, scope, blobs

    def _query(self, model):
        from sqlalchemy import select
        return select(model).filter_by(**self.scope.model_dump())

    def _identity(self, pack_id, fund_id):
        if (pack_id, fund_id) != (self.scope.pack_id, self.scope.fund_id):
            raise AccessDenied("Resource unavailable in scope")

    def lock(self):
        from closegraph.storage.models import PackRow
        row = self.session.scalar(self._query(PackRow).with_for_update())
        if row is None:
            raise AccessDenied("Resource unavailable in scope")
        return row

    def create(self, state):
        from closegraph.storage.models import PackRow
        self._identity(state["pack_id"], state["fund_id"])
        if state.get("tenant_id", self.scope.tenant_id) != self.scope.tenant_id or state.get("version") != 1:
            raise Conflict("Initial snapshot identity conflict")
        if self.session.scalar(self._query(PackRow)) is not None:
            raise Conflict("Initial snapshot identity conflict")
        state = deepcopy(state)
        state["tenant_id"] = self.scope.tenant_id
        self.session.add(PackRow(**self.scope.model_dump(), title=state.get("title", state["pack_id"]), current_version=1))
        self.session.flush()
        self._append(state)
        return deepcopy(state)

    def get(self, pack_id, scope, *, version=None):
        from closegraph.storage.models import PackRow, PackRevisionRow
        self._identity(pack_id, scope)
        pack = self.session.scalar(self._query(PackRow))
        if pack is None:
            raise AccessDenied("Resource unavailable in scope")
        requested = pack.current_version if version is None else version
        if type(requested) is not int or requested < 1:
            raise AccessDenied("Resource unavailable in scope")
        row = self.session.scalar(self._query(PackRevisionRow).filter_by(version=requested))
        if row is None:
            raise AccessDenied("Resource unavailable in scope")
        return deepcopy(row.input_snapshot)

    def save(self, state, expected_version):
        self._identity(state["pack_id"], state["fund_id"])
        pack = self.lock()
        if type(expected_version) is not int or pack.current_version != expected_version:
            raise Conflict("Snapshot revision changed")
        if state.get("tenant_id", self.scope.tenant_id) != self.scope.tenant_id or state.get("version") != expected_version + 1:
            raise Conflict("Snapshot must advance once within its exact tenant")
        current = self.get(state["pack_id"], state["fund_id"])
        before, after = current.get("history", []), state.get("history", [])
        if after[:len(before)] != before or len(after) != len(before) + 1:
            raise Conflict("History must append exactly one event")
        if any(state.get("request_receipts", {}).get(k) != v for k, v in current.get("request_receipts", {}).items()):
            raise Conflict("Request receipts are immutable")
        state = deepcopy(state)
        state["tenant_id"] = self.scope.tenant_id
        self._append(state)
        pack.current_version = state["version"]
        self.session.flush()
        return deepcopy(state)

    def _row(self, model, identity):
        return self.session.scalar(self._query(model).filter_by(id=identity))

    def _append(self, state):
        """Persist the exact snapshot plus indexed canonical evidence records."""
        import json
        from datetime import datetime, timezone
        from decimal import Decimal
        from closegraph.storage.models import (
            PackRevisionRow, DocumentVersionRow, FactVersionRow, CheckResultRow,
            DependencyEdgeRow, AuditEventRow, ArtifactRow, ReviewDecisionRow,
            PublicationRow, CorrectionRow, SourceOccurrenceRow, ExtractionObservationRow,
        )
        from closegraph.outputs.manifest import canonical_bytes

        state = json.loads(canonical_bytes(state))
        scoped = self.scope.model_dump()
        revision_id = "revision:" + str(state["version"])
        self.session.add(PackRevisionRow(**scoped, id=revision_id, version=state["version"],
            prepared_by=state["prepared_by"], policy_version=state["policy_version"], input_snapshot=state))
        self.session.flush()
        evidence = state.get("evidence", {})
        document_ids = {}
        for source_id, source in evidence.items():
            number = source.get("source_version", 1)
            number = int(str(number).removeprefix("v"))
            doc_id = source.get("document_version_id", source_id + ":v" + str(number))
            document_ids[source_id] = doc_id
            existing_document = self._row(DocumentVersionRow, doc_id)
            if existing_document is not None and (existing_document.content_hash != source["content_hash"] or existing_document.version != number):
                raise Conflict("A source version cannot change its immutable bytes")
            if existing_document is None:
                data = self.blobs.get(source["content_hash"])
                at = source.get("observed_at")
                self.session.add(DocumentVersionRow(**scoped, id=doc_id, source_id=source_id,
                    version=number, idempotency_key="initial:" + doc_id,
                    content_hash=source["content_hash"], storage_key=source["content_hash"],
                    byte_size=len(data), filename=source.get("filename", source_id + ".csv"),
                    media_type=source.get("media_type", "text/csv"), receipt_actor_id=source.get("receipt_actor_id", state["prepared_by"]),
                    observed_at=datetime.fromisoformat(at) if at else datetime.now(timezone.utc),
                    authority_status=source.get("authority_status", "UNRESOLVED"),
                    coverage_status=source.get("coverage_status", "UNKNOWN")))
        self.session.flush()

        for item in state.get("source_occurrences", []):
            identity = item["occurrence_id"]
            if self._row(SourceOccurrenceRow, identity) is None:
                source = item["source"]
                self.session.add(SourceOccurrenceRow(**scoped, id=identity,
                    document_version_id=source["document_version_id"],
                    locator=source["locator"], raw_content=item["raw_content"],
                    context_evidence_ids=source.get("context_evidence_ids", []),
                    disposition=item["disposition"], reason=item.get("reason")))
        self.session.flush()
        for item in state.get("extraction_observations", []):
            identity = item["observation_id"]
            if self._row(ExtractionObservationRow, identity) is None:
                self.session.add(ExtractionObservationRow(**scoped, id=identity,
                    occurrence_id=item["occurrence_id"], parser=item["parser"], parser_version=item["parser_version"],
                    settings=item["settings"], response_id=item["response_id"], response_content_hash=item.get("response_content_hash"),
                    mode=item["mode"], confidence=item["confidence"], candidate=item["candidate"]))
        self.session.flush()
        for fact in state.get("facts", []):
            number = fact.get("fact_version", fact.get("version", 1))
            identity = fact["fact_id"] + ":v" + str(number)
            source_id = fact["source"]["source_id"]
            source = evidence[source_id]
            source_ref = {"document_version_id": document_ids[source_id], "content_hash": source["content_hash"],
                          "locator": fact["source"].get("locator", source["locator"]),
                          "context_evidence_ids": list(fact["source"].get("context_evidence_ids", []))}
            supersedes = fact.get("supersedes")
            if type(supersedes) is int:
                supersedes = fact["fact_id"] + ":v" + str(supersedes)
            canonical = dict(
                document_version_id=document_ids[source_id],metric=fact.get("metric",fact["fact_id"]),
                entity_id=fact.get("entity_id"),period=fact.get("period"),currency=fact.get("currency"),
                value_decimal=Decimal(fact["value_decimal"]) if fact.get("value_decimal") is not None else None,
                raw_value=fact.get("raw_value"),raw_scale=fact.get("raw_scale"),
                value_state=fact.get("value_state","PRESENT" if fact.get("value_decimal") is not None else "MISSING"),
                interpretation_status=fact.get("interpretation_status","CORRECTED" if fact.get("correction_source_id") else "UNRESOLVED"),
                interpretation_rule_id=fact.get("interpretation_rule_id"),correction_id=fact.get("correction_id"),
                evidence=source_ref,observation_ids=list(fact.get("observation_ids",[])),supersedes=supersedes)
            existing_fact = self._row(FactVersionRow,identity)
            if existing_fact is not None:
                if any(getattr(existing_fact,key) != value for key,value in canonical.items()):
                    raise Conflict("A fact version cannot change its value, context, interpretation or provenance")
                continue
            self.session.add(FactVersionRow(**scoped,id=identity,fact_id=fact["fact_id"],version=number,
                revision_id=revision_id,**canonical))
        self.session.flush()

        for index, check in enumerate(state.get("checks", [])):
            self.session.add(CheckResultRow(**scoped, id=revision_id + ":check:" + str(index), revision_id=revision_id,
                check_key=check["id"], rule_version=check.get("rule_version", state["rule_version"]),
                input_snapshot={"source_versions":state.get("source_versions", {}), "version":state["version"]},
                required=check.get("required") is True, applicability=check.get("applicability", "APPLICABLE"),
                operands=check.get("operands", []), difference=Decimal(str(check.get("difference",check.get("delta_decimal")))) if check.get("difference",check.get("delta_decimal")) is not None else None,
                tolerance=Decimal(str(check.get("tolerance",check.get("tolerance_decimal")))) if check.get("tolerance",check.get("tolerance_decimal")) is not None else None,
                status=check["status"], diagnostics=check))
        for index, (upstream, downstream) in enumerate(state.get("dependency_edges", [])):
            self.session.add(DependencyEdgeRow(**scoped, id=revision_id + ":edge:" + str(index), revision_id=revision_id,
                upstream_kind="fact_or_rule", upstream_id=upstream, downstream_kind="check_or_output", downstream_id=downstream,
                provenance={"mapping_version":state["mapping_version"], "rule_version":state["rule_version"]},
                coverage_status="COMPLETE" if state.get("dependency_coverage") is True else "UNKNOWN"))

        candidate = state.get("candidate")
        if candidate and self._row(ArtifactRow, candidate["artifact_id"]) is None:
            data = self.blobs.get(candidate["artifact_id"])
            self.session.add(ArtifactRow(**scoped, id=candidate["artifact_id"], revision_id=revision_id,
                storage_key=candidate["artifact_id"], content_hash=candidate["artifact_id"], byte_size=len(data),
                filename=state["pack_id"] + "-v" + str(candidate["snapshot_version"]) + ".xlsx",
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                validation={"snapshot_digest":candidate["snapshot_digest"], "template":state["template"]}))
        self.session.flush()

        approval = state.get("approval")
        if approval:
            review_id = "review:" + sha256(canonical_bytes(approval)).hexdigest()
            if self._row(ReviewDecisionRow, review_id) is None:
                self.session.add(ReviewDecisionRow(**scoped, id=review_id, revision_id=revision_id,
                    artifact_id=approval["artifact_id"], actor_id=approval["actor"], decision=approval["decision"],
                    note=approval["note"], attested=approval["attested"], dependency_snapshot=approval,
                    policy_version=state["policy_version"]))
        self.session.flush()
        publication = state.get("publication")
        if publication and self._row(PublicationRow, publication["publication_id"]) is None:
            data = self.blobs.get(publication["manifest_id"])
            self.session.add(ArtifactRow(**scoped, id=publication["manifest_id"], revision_id=revision_id,
                storage_key=publication["manifest_id"], content_hash=publication["manifest_id"], byte_size=len(data),
                filename=state["pack_id"] + "-v" + str(publication["snapshot_version"]) + "-manifest.json",
                media_type="application/json", validation={"snapshot_digest":publication["snapshot_digest"]}))
            self.session.flush()
            self.session.add(PublicationRow(**scoped, id=publication["publication_id"], revision_id=revision_id,
                review_decision_id=review_id, artifact_id=publication["artifact_id"], manifest_artifact_id=publication["manifest_id"],
                actor_id=publication["actor"], release_key=publication["publication_id"]))
        if state.get("history"):
            event = state["history"][-1]
            self.session.add(AuditEventRow(**scoped, id=revision_id + ":audit", actor_id=event["actor"],
                event_type=event["action"], resource_id=revision_id, detail=event))
            if event["action"] == "CORRECTED":
                fact = next(f for f in state["facts"] if f["fact_id"] == event["fact_id"])
                number = fact.get("fact_version", 1)
                self.session.add(CorrectionRow(**scoped, id=revision_id + ":correction",
                    previous_revision_id="revision:" + str(event["input_version"]), revision_id=revision_id,
                    previous_fact_id=fact["fact_id"] + ":v" + str(number - 1),
                    corrected_fact_id=fact["fact_id"] + ":v" + str(number),
                    source_id=document_ids[event["source_id"]], actor_id=event["actor"], reason=event["reason"]))
        self.session.flush()
