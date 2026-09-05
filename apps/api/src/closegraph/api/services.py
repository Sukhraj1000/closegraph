"""PostgreSQL-backed local application facade and durable Dagster handoff.

HTTP mutations only persist requests. The Dagster worker loads immutable inputs,
executes tools outside a database transaction, then commits a result through the
same current-version lock used by correction, review and publication.
"""
import base64
import binascii
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import select

from closegraph.contracts import (
    Scope, PackSnapshot, FactSnapshot, SourceRef, CheckSummary, CandidateSnapshot,
)
from closegraph.outputs.manifest import canonical_bytes, snapshot_digest
from closegraph.outputs.workbook import generate_workbook
from closegraph.services.errors import DomainError, Conflict, AccessDenied
from closegraph.services.lifecycle import LifecycleService
from closegraph.services.repository import PostgreSQLRepository, ScopedBlobs, ScopedAuthorizer
from closegraph.storage.models import (
    DocumentVersionRow, ProcessingRequestRow, ProcessingResultRow, PackRevisionRow, AuditEventRow,
)
from .ports import ArtifactDownload, DomainNotFound, DomainConflict


def _now():
    return datetime.now(timezone.utc).isoformat()


class PostgreSQLPackServices:
    def __init__(self, sessions, blobs, auth, evaluator, *, ingestor=None):
        self.sessions, self.blob_store, self.auth = sessions, blobs, auth
        self.evaluator, self.ingestor = evaluator, ingestor
        self.required_check_ids = tuple(evaluator.required_check_ids)

    def _service(self, session, scope):
        blobs = ScopedBlobs(self.blob_store, scope)
        repository = PostgreSQLRepository(session, scope, blobs)
        service = LifecycleService(repository, blobs, ScopedAuthorizer(self.auth, scope), self.evaluator)
        return repository, service

    @staticmethod
    def _raise(exc):
        if isinstance(exc, AccessDenied):
            raise DomainNotFound() from exc
        if isinstance(exc, DomainError):
            raise DomainConflict(str(exc)) from exc
        raise exc

    def create_pack(self, scope, actor, state):
        """Server-side bootstrap only; there is deliberately no unscoped create route."""
        self.auth.require(actor.actor_id, scope, "upload")
        with self.auth.authorized(actor.actor_id,scope,'upload'), self.sessions.begin() as session:
            repository, _ = self._service(session, scope)
            state = deepcopy(state)
            state.update(tenant_id=scope.tenant_id, fund_id=scope.fund_id, pack_id=scope.pack_id,
                         version=1, prepared_by=actor.actor_id)
            repository.create(state)
        return self.get_pack(scope, actor)

    def _perform(self, scope, actor, action, command=None, *, version=None):
        self.auth.require(actor.actor_id, scope, action)
        try:
            with self.auth.authorized(actor.actor_id,scope,action), self.sessions.begin() as session:
                repository, service = self._service(session, scope)
                repository.lock()
                if action == "inspect":
                    state = service.inspect(scope.pack_id, actor=actor.actor_id, scope=scope.fund_id, version=version)
                else:
                    payload = command.model_dump(mode="json")
                    if action == "review":
                        current = repository.get(scope.pack_id, scope.fund_id)
                        if current["routing_status"] == "NEEDS_REVIEW" and not current.get("soft_resolution"):
                            raise DomainError("Record source-backed resolution before independent approval")
                    state = getattr(service, action)(scope.pack_id, actor=actor.actor_id, scope=scope.fund_id, **payload)
                    if action in ("correct","invalidate"):
                        key = ("correction:" if action == "correct" else "configuration:") + str(state["version"])
                        existing = session.scalar(select(ProcessingRequestRow).filter_by(**scope.model_dump(),processing_key=key))
                        if existing is None:
                            self._enqueue(session,scope,state,actor,"recompute",key=key)
                current_version = repository.get(scope.pack_id, scope.fund_id)["version"]
                return self._snapshot(state, current_version=current_version)
        except DomainError as exc:
            self._raise(exc)

    def get_pack(self, scope, actor):
        return self._perform(scope, actor, "inspect")

    def get_history(self, scope, actor, version):
        return self._perform(scope, actor, "inspect", version=version)

    def record_review_event(self, scope, actor, command):
        """Append observed local UI activity without changing financial revisions."""
        permission = "review" if command.event_type == "READY_ITEM_SAMPLED" else "inspect"
        payload = command.model_dump(mode="json", exclude={"idempotency_key"})
        identity = "interaction:" + (sha256(canonical_bytes([actor.actor_id,command.idempotency_key])).hexdigest()
                                      if command.idempotency_key else uuid4().hex)
        with self.auth.authorized(actor.actor_id,scope,permission), self.sessions.begin() as session:
            repository, service = self._service(session,scope)
            # This short lock orders READY sampling against corrections without
            # ever adding a new pack revision or affecting a computation lease.
            try:
                current = repository.lock()
            except DomainError as exc:
                self._raise(exc)
            previous = session.scalar(select(AuditEventRow).filter_by(**scope.model_dump(),id=identity))
            if previous:
                if previous.actor_id != actor.actor_id or previous.detail["request"] != payload:
                    raise DomainConflict("Review event idempotency key reused for a different interaction")
                return previous.detail["event"]
            try:
                state = repository.get(scope.pack_id,scope.fund_id,version=command.observed_snapshot_version)
            except DomainError as exc:
                self._raise(exc)
            if command.fact_id is not None and not any(f["fact_id"] == command.fact_id for f in state.get("facts",())):
                raise DomainNotFound()
            if command.document_version_id is not None:
                document = session.scalar(select(DocumentVersionRow).filter_by(
                    **scope.model_dump(),id=command.document_version_id))
                snapshot = self._snapshot(state)
                document_ids = {f.source.document_version_id for f in snapshot.facts}
                document_ids.update(r["document_version_id"] for r in state.get("receipts",()))
                document_ids.update(e.get("document_version_id") for e in state.get("evidence",{}).values())
                if document is None or command.document_version_id not in document_ids:
                    raise DomainNotFound()
            if command.event_type == "READY_ITEM_SAMPLED":
                if current.current_version != command.observed_snapshot_version:
                    raise DomainConflict("Ready-item sampling requires the current snapshot")
                if (state.get("routing_status") != "READY_FOR_QUICK_REVIEW"
                        or state.get("freshness") != "CURRENT" or state.get("execution_status") != "COMPLETED"
                        or not state.get("candidate")):
                    raise DomainConflict("Only a current checked ready item can be sampled")
            event = {"event_id":identity,"actor_id":actor.actor_id,"recorded_at":_now(),**payload}
            session.add(AuditEventRow(**scope.model_dump(),id=identity,actor_id=actor.actor_id,
                event_type=command.event_type,resource_id="revision:"+str(command.observed_snapshot_version),
                detail={"request":payload,"event":event,"provenance":"LOCAL_OBSERVED"}))
            return event

    def review_work(self, scope, actor):
        with self.auth.authorized(actor.actor_id,scope,"inspect"), self.sessions() as session:
            repository,_ = self._service(session,scope)
            try:
                state = repository.get(scope.pack_id,scope.fund_id)
            except DomainError as exc:
                self._raise(exc)
            event_types = ("SOURCE_OPENED","VALUE_INSPECTED","READY_ITEM_SAMPLED")
            rows = session.scalars(select(AuditEventRow).filter_by(**scope.model_dump()).where(
                AuditEventRow.event_type.in_(event_types)).order_by(AuditEventRow.created_at,AuditEventRow.id)).all()
            counts = {kind:sum(row.event_type == kind for row in rows) for kind in event_types}
            timestamps = [datetime.fromisoformat(row.detail["event"]["recorded_at"]) for row in rows]
            first,last = (min(timestamps),max(timestamps)) if timestamps else (None,None)
            history = state.get("history",[])
            actions = {kind:sum(event.get("action") == kind for event in history)
                       for kind in ("CORRECTED","RESOLVED","APPROVED","REJECTED")}
            reopened = [{"at":event.get("at"),"version":event.get("version"),"reason":event.get("reason"),
                         "impact":event.get("impact",{})}
                        for event in history if event.get("action") in ("CORRECTED","INVALIDATED","SOURCE_RECEIVED")]
            return {"provenance":"LOCAL_OBSERVED","counts":counts,"total_events":len(rows),
                    "first_event_at":first.isoformat() if first else None,
                    "last_event_at":last.isoformat() if last else None,
                    "elapsed_seconds":(last-first).total_seconds() if first else None,
                    "actions":actions,"reopened_scope":reopened}

    def invalidate(self, scope, actor, command):
        # Only trusted application configuration code calls this facade. There
        # is intentionally no route accepting arbitrary accounting-rule JSON.
        from closegraph.contracts import ConfigurationChangeRequest
        command = ConfigurationChangeRequest.model_validate(command)
        return self._perform(scope,actor,"invalidate",command)

    def correct(self, scope, actor, command):
        return self._perform(scope, actor, "correct", command)

    def review(self, scope, actor, command):
        return self._perform(scope, actor, "review", command)

    def reject(self, scope, actor, command):
        return self._perform(scope, actor, "reject", command)

    def resolve(self, scope, actor, command):
        # Authorizer maps the persisted resolution to reviewer permission.
        self.auth.require(actor.actor_id, scope, "review")
        try:
            with self.auth.authorized(actor.actor_id,scope,'review'), self.sessions.begin() as session:
                repository, service = self._service(session, scope)
                repository.lock()
                state = service.resolve(scope.pack_id, actor=actor.actor_id, scope=scope.fund_id,
                                        **command.model_dump(mode="json"))
                return self._snapshot(state)
        except DomainError as exc:
            self._raise(exc)

    def publish(self, scope, actor, command):
        return self._perform(scope, actor, "publish", command)

    @staticmethod
    def _event(repository, state, actor, action, detail=None):
        old = state["version"]
        state["version"] = old + 1
        state.setdefault("history", []).append({"actor":actor, "action":action, "at":_now(),
            "input_version":old, "version":old + 1, **(detail or {})})
        return repository.save(state, old)

    def _enqueue(self, session, scope, state, actor, stage, *, document_id=None, key=None):
        identity = "processing:" + uuid4().hex
        request = ProcessingRequestRow(**scope.model_dump(), id=identity,
            revision_id="revision:" + str(state["version"]), document_version_id=document_id,
            processing_key=key or identity, stage=stage, code_version=getattr(self.evaluator, "code_version", "local-v1"),
            config_version=state["policy_version"], status="PENDING")
        session.add(request)
        session.flush()
        return request

    def recompute(self, scope, actor, command):
        return self.request_recompute(scope, actor, command)

    def request_recompute(self, scope, actor, command):
        self.auth.require(actor.actor_id, scope, "recompute")
        fingerprint = sha256(canonical_bytes({"actor":actor.actor_id, "scope":scope.model_dump(),
            "expected_version":command.expected_version, "action":"recompute"})).hexdigest()
        key = "recompute:" + (sha256(canonical_bytes([actor.actor_id,command.idempotency_key])).hexdigest()
                              if command.idempotency_key else fingerprint)
        try:
            with self.auth.authorized(actor.actor_id,scope,'recompute'), self.sessions.begin() as session:
                repository, service = self._service(session, scope)
                repository.lock()
                state = repository.get(scope.pack_id, scope.fund_id)
                prior = session.scalar(select(ProcessingRequestRow).filter_by(**scope.model_dump(), processing_key=key))
                if prior:
                    prior_state = repository.get(scope.pack_id, scope.fund_id,
                                                 version=int(prior.revision_id.split(":")[-1]))
                    if prior_state["history"][-1].get("request_digest") != fingerprint:
                        raise Conflict("Idempotency key reused with a different request")
                    return self._snapshot(state)
                if state["version"] != command.expected_version:
                    raise Conflict("Snapshot revision changed")
                active = session.scalar(select(ProcessingRequestRow).filter_by(
                    **scope.model_dump(),revision_id="revision:"+str(state["version"])).where(
                        ProcessingRequestRow.status.in_(("PENDING","ACKNOWLEDGED","RUNNING"))))
                if active is not None:
                    return self._snapshot(state)
                service._stale(state)
                state["execution_status"] = "PENDING"
                state = self._event(repository, state, actor.actor_id, "PROCESSING_REQUESTED",
                                    {"request_digest":fingerprint})
                self._enqueue(session, scope, state, actor, "recompute", key=key)
                return self._snapshot(state)
        except DomainError as exc:
            self._raise(exc)

    def upload(self, scope, actor, command):
        self.auth.require(actor.actor_id, scope, "upload")
        if not command.idempotency_key:
            raise DomainConflict("Upload requires an idempotency key")
        if command.filename != command.filename.replace("\\", "/").split("/")[-1] or any(ord(c) < 32 for c in command.filename):
            raise DomainConflict("Upload filename must be a plain filename")
        supported = {"text/csv", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/pdf"}
        if command.media_type not in supported:
            raise DomainConflict("Unsupported source media type")
        try:
            content = base64.b64decode(command.content_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise DomainConflict("Invalid base64 source bytes") from exc
        if not content or len(content) > self.blob_store.max_bytes:
            raise DomainConflict("Source bytes exceed the supported size")
        identity_hash = sha256(content).hexdigest()
        try:
            with self.auth.authorized(actor.actor_id,scope,'upload'), self.sessions.begin() as session:
                repository, service = self._service(session, scope)
                repository.lock()
                prior = session.scalar(select(DocumentVersionRow).filter_by(
                    **scope.model_dump(), idempotency_key=command.idempotency_key))
                state = repository.get(scope.pack_id, scope.fund_id)
                if prior:
                    if (prior.content_hash, prior.source_id, prior.filename, prior.media_type) != (
                            identity_hash,command.source_id,command.filename,command.media_type):
                        raise Conflict("Upload idempotency key reused for different bytes or source identity")
                    return self._snapshot(state)
                if state["version"] != command.expected_version:
                    raise Conflict("Snapshot revision changed")
                latest = session.scalar(select(DocumentVersionRow).filter_by(
                    **scope.model_dump(), source_id=command.source_id).order_by(DocumentVersionRow.version.desc()))
                number = latest.version + 1 if latest else 1
                doc_id = "document:" + uuid4().hex
                blob = service.blobs.put(content)
                row = DocumentVersionRow(**scope.model_dump(), id=doc_id, source_id=command.source_id,
                    version=number, idempotency_key=command.idempotency_key, content_hash=blob,storage_key=blob,
                    byte_size=len(content), filename=command.filename, media_type=command.media_type,
                    receipt_actor_id=actor.actor_id, observed_at=datetime.now(timezone.utc),
                    authority_status="UNRESOLVED", coverage_status="UNKNOWN")
                session.add(row)
                session.flush()
                service._stale(state)
                state["execution_status"] = "PENDING"
                state["contributors"] = sorted(set(state.get("contributors", [])) | {actor.actor_id})
                state.setdefault("receipts", []).append(self._document(row))
                state["impact"] = {"affected":["output","source:"+command.source_id],
                                   "independent":[],"unverifiable":state.get("dependency_coverage") is not True}
                state = self._event(repository, state, actor.actor_id, "SOURCE_RECEIVED",
                                    {"document_version_id":doc_id,"source_id":command.source_id,"content_hash":blob,
                                     "impact":deepcopy(state["impact"])})
                self._enqueue(session, scope, state, actor, "ingest", document_id=doc_id)
                return self._snapshot(state)
        except DomainError as exc:
            self._raise(exc)

    @staticmethod
    def _document(row):
        return {"document_version_id":row.id,"source_id":row.source_id,"version":row.version,
            "content_hash":row.content_hash,"storage_key":row.storage_key,"filename":row.filename,
            "media_type":row.media_type,"byte_size":row.byte_size,"receipt_actor_id":row.receipt_actor_id,
            "observed_at":row.observed_at.isoformat(),"authority_status":row.authority_status,
            "coverage_status":row.coverage_status}

    def pending_requests(self, limit=10):
        with self.sessions() as session:
            rows = session.scalars(select(ProcessingRequestRow).where(
                ProcessingRequestRow.status.in_(("PENDING","ACKNOWLEDGED","RUNNING"))).order_by(
                    ProcessingRequestRow.created_at).limit(limit)).all()
            return [{"scope":{"tenant_id":r.tenant_id,"fund_id":r.fund_id,"pack_id":r.pack_id},
                     "request_id":r.id,"stage":r.stage,"snapshot_version":int(r.revision_id.split(":")[-1]),
                     "document_version_id":r.document_version_id,"dagster_run_id":r.dagster_run_id,"status":r.status}
                    for r in rows]

    def load_processing(self, scope, request_id):
        scope = Scope.model_validate(scope)
        with self.sessions() as session:
            repository, service = self._service(session, scope)
            request = session.scalar(select(ProcessingRequestRow).filter_by(**scope.model_dump(), id=request_id))
            if not request:
                raise DomainNotFound()
            state = repository.get(scope.pack_id, scope.fund_id, version=int(request.revision_id.split(":")[-1]))
            result = {"state":state, "stage":request.stage, "request_id":request.id}
            if request.document_version_id:
                document = session.scalar(select(DocumentVersionRow).filter_by(
                    **scope.model_dump(),id=request.document_version_id))
                result.update(document=self._document(document), content=service.blobs.get(document.content_hash))
            return result

    def claim_processing(self, scope, request_id, dagster_run_id):
        scope = Scope.model_validate(scope)
        with self.sessions.begin() as session:
            request = session.scalar(select(ProcessingRequestRow).filter_by(
                **scope.model_dump(),id=request_id).with_for_update())
            if not request or request.status in ("COMPLETED","FAILED"):
                return False
            if request.dagster_run_id and request.dagster_run_id != dagster_run_id:
                return False
            request.status, request.dagster_run_id = "RUNNING", dagster_run_id
            return True

    def release_processing(self, scope, request_id, dagster_run_id):
        """Worker recovery after Dagster confirms the previous run stopped."""
        scope = Scope.model_validate(scope)
        with self.sessions.begin() as session:
            request = session.scalar(select(ProcessingRequestRow).filter_by(
                **scope.model_dump(),id=request_id).with_for_update())
            if not request or request.status != "RUNNING" or request.dagster_run_id != dagster_run_id:
                return False
            request.status,request.dagster_run_id = "PENDING",None
            return True

    def _prepare_processing(self, scope, request_id, result):
        # All potentially expensive validation/output generation happens without
        # a current-pack lock. The commit below checks the immutable input version.
        loaded = self.load_processing(scope,request_id)
        state = loaded["state"]
        with self.sessions() as session:
            _,service = self._service(session,scope)
            service._stale(state)
            allowed = {"facts","evidence","source_versions","source_occurrences","extraction_observations",
                "observations","native","dependency_edges","dependency_coverage","template","values","checks",
                "rule_version","mapping_version","policy_version","external_freshness","routing_reasons",
                "rule","mappings","policy","coverage","extraction_report","sources","total_label"}
            if set(result) - allowed - {"execution_error"}:
                raise DomainConflict("Unsupported processing result fields")
            configured = state.get("configured_records",{})
            if any(key in result and result[key] != value for key,value in configured.items()):
                state.update(execution_status="FAILED",freshness="STALE",routing_status="BLOCKED",
                             execution_error="Processing output conflicts with pinned server configuration")
                return state
            state.update(deepcopy({key:value for key,value in result.items() if key in allowed}))
            state["required_check_ids"] = list(self.required_check_ids)
            if result.get("execution_error"):
                state.update(execution_status="FAILED",execution_error=str(result["execution_error"]),
                             freshness="STALE",routing_status="BLOCKED")
                return state
            try:
                state["routing_status"] = service._routing(state)
                state.update(execution_status="COMPLETED",freshness="CURRENT")
                if state["routing_status"] != "BLOCKED":
                    service._evidence(state)
                    contract = service._contract(state)
                    data = generate_workbook(service._blob(contract.template_hash),contract,state["values"])
                    artifact_id = service.blobs.put(data)
                    state["candidate"] = {"artifact_id":artifact_id,"snapshot_version":state["version"]+1,
                        "snapshot_digest":snapshot_digest(state),"total_decimal":state["values"].get("total")}
            except DomainError as exc:
                state.update(execution_status="FAILED",execution_error=str(exc),freshness="STALE",
                             routing_status="BLOCKED",candidate=None)
            return state

    def complete_processing(self, scope, request_id, result, dagster_run_id):
        scope = Scope.model_validate(scope)
        result_hash = sha256(canonical_bytes(result)).hexdigest()
        prepared = self._prepare_processing(scope,request_id,result)
        with self.sessions.begin() as session:
            repository, service = self._service(session, scope)
            current = repository.lock()
            request = session.scalar(select(ProcessingRequestRow).filter_by(
                **scope.model_dump(),id=request_id).with_for_update())
            if not request:
                raise DomainNotFound()
            if request.dagster_run_id != dagster_run_id or request.status not in ("RUNNING","COMPLETED","FAILED"):
                raise DomainConflict("Processing result does not match the claimed Dagster run")
            previous = session.scalar(select(ProcessingResultRow).filter_by(**scope.model_dump(),request_id=request_id))
            if previous:
                if previous.result_hash != result_hash:
                    raise DomainConflict("Processing request already has a different immutable result")
                return {"applied":previous.applied,"state":self._snapshot(repository.get(scope.pack_id,scope.fund_id))}
            input_version = int(request.revision_id.split(":")[-1])
            applied = current.current_version == input_version
            state = prepared
            if applied:
                state = self._event(repository,state,"dagster","PROCESSED",
                    {"request_id":request_id,"dagster_run_id":dagster_run_id,"input_snapshot":input_version,
                     "checks":deepcopy(state.get("checks",[])),"execution_status":state["execution_status"],
                     "routing_status":state["routing_status"]})
            session.add(ProcessingResultRow(**scope.model_dump(),id="result:"+uuid4().hex,request_id=request_id,
                revision_id=request.revision_id,result_hash=result_hash,result=deepcopy(result),
                applied=applied,dagster_run_id=dagster_run_id))
            request.status = "FAILED" if prepared.get("execution_status")=="FAILED" else "COMPLETED"
            return {"applied":applied,"state":self._snapshot(state if applied else repository.get(scope.pack_id,scope.fund_id))}

    def evidence(self, scope, actor, source_id):
        self.auth.require(actor.actor_id, scope, "inspect")
        with self.sessions() as session:
            repository,_ = self._service(session,scope)
            try:
                state = repository.get(scope.pack_id,scope.fund_id)
            except DomainError as exc:
                self._raise(exc)
            source = state.get("evidence",{}).get(source_id)
            if source is None:
                # Newly received or unsupported files remain inspectable.
                source = next((r for r in reversed(state.get("receipts",[])) if r["source_id"]==source_id),None)
            if source is None:
                raise DomainNotFound()
            return deepcopy(source)

    def document(self, scope, actor, document_version_id):
        self.auth.require(actor.actor_id, scope, "inspect")
        with self.sessions() as session:
            row=session.scalar(select(DocumentVersionRow).filter_by(**scope.model_dump(),id=document_version_id))
            if row is None:
                raise DomainNotFound()
            return self._document(row)

    def download_document(self, scope, actor, document_version_id):
        source=self.document(scope,actor,document_version_id)
        try:
            content=ScopedBlobs(self.blob_store,scope).get(source["content_hash"])
        except DomainError as exc:
            self._raise(exc)
        return ArtifactDownload(content,source["filename"],source["media_type"])

    def download_evidence(self, scope, actor, source_id):
        source = self.evidence(scope,actor,source_id)
        try:
            content = ScopedBlobs(self.blob_store,scope).get(source["content_hash"])
        except DomainError as exc:
            self._raise(exc)
        return ArtifactDownload(content,source.get("filename",source_id),source.get("media_type","application/octet-stream"))

    def download(self, scope, actor, artifact_id, *, publication_id=None):
        self.auth.require(actor.actor_id, scope, "download")
        try:
            with self.sessions() as session:
                repository,service = self._service(session,scope)
                state = repository.get(scope.pack_id,scope.fund_id)
                publications = state.get("publications", [])
                if publication_id is not None:
                    publication = next((p for p in publications
                        if p["publication_id"] == publication_id
                        and artifact_id in (p["artifact_id"], p["manifest_id"])), None)
                    if publication is None:
                        raise DomainNotFound()
                else:
                    publication = state.get("publication")
                    if not publication or artifact_id not in (publication["artifact_id"], publication["manifest_id"]):
                        candidate = state.get("candidate")
                        if candidate and artifact_id == candidate["artifact_id"]:
                            content = service._candidate_gate(state)
                            return ArtifactDownload(content,
                                scope.pack_id+"-v"+str(candidate["snapshot_version"])+"-UNAPPROVED-PREVIEW.xlsx",
                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                        # Content hashes can be shared by distinct publications. Legacy
                        # links resolve the latest match; explicit links retain history.
                        publication = max((p for p in publications
                            if artifact_id in (p["artifact_id"], p["manifest_id"])),
                            key=lambda p: (p["snapshot_version"], p["version"], p["publication_id"]),
                            default=None)
                if publication:
                    downloaded = service.download(scope.pack_id,actor=actor.actor_id,scope=scope.fund_id,
                                                  publication_id=publication["publication_id"])
                    is_manifest = artifact_id==publication["manifest_id"]
                    return ArtifactDownload(downloaded.manifest if is_manifest else downloaded.artifact,
                        scope.pack_id+"-v"+str(downloaded.snapshot_version)+
                        ("-"+downloaded.freshness.lower()+"-manifest.json" if is_manifest else "-"+downloaded.freshness.lower()+".xlsx"),
                        "application/json" if is_manifest else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                raise DomainNotFound()
        except DomainError as exc:
            self._raise(exc)

    @staticmethod
    def _snapshot(state, *, current_version=None):
        evidence = deepcopy(state.get("evidence",{}))
        for receipt in state.get("receipts",[]):
            evidence.setdefault(receipt["source_id"], deepcopy(receipt))
        facts = []
        for fact in state.get("facts",[]):
            raw_source = fact["source"]
            source = state.get("evidence",{}).get(raw_source["source_id"],{})
            ref = SourceRef(document_version_id=source.get("document_version_id",
                raw_source["source_id"]+":v"+str(source.get("source_version",1)).removeprefix("v")),
                content_hash=source["content_hash"],locator=raw_source.get("locator",source["locator"]),
                context_evidence_ids=raw_source.get("context_evidence_ids",()))
            facts.append(FactSnapshot(fact_id=fact["fact_id"],metric=fact.get("metric",fact["fact_id"]),
                value_decimal=fact.get("value_decimal"),currency=fact.get("currency"),period=fact.get("period"),
                entity_id=fact.get("entity_id"),raw_value=fact.get("raw_value"),raw_scale=fact.get("raw_scale"),source=ref,
                derived=fact.get("derived") is True,fact_version=fact.get("fact_version",1),value_state=fact.get("value_state","PRESENT" if fact.get("value_decimal") is not None else "MISSING"),
                interpretation_status=fact.get("interpretation_status","UNRESOLVED"),
                observation_ids=fact.get("observation_ids",()),correction_source_id=fact.get("correction_source_id")))
        checks = []
        for check in state.get("checks",[]):
            difference=check.get("difference",check.get("delta_decimal"))
            tolerance=check.get("tolerance",check.get("tolerance_decimal"))
            detail=check.get("detail") or check.get("reason") or check.get("justification")
            diagnostics=[str(d) for d in check.get("diagnostics",[]) if d]
            if not detail and diagnostics:
                detail="; ".join(diagnostics)
            if not detail and difference is not None:
                detail="Difference "+str(difference)+"; tolerance "+str(tolerance)
            checks.append(CheckSummary(id=check["id"],label=check.get("label",check["id"].replace("_"," ").capitalize()),
                status=check["status"],required=check.get("required") is True,detail=detail or "",
                operands=check.get("operands",()),difference=difference,tolerance=tolerance,
                rule_version=check.get("rule_version"),expected_decimal=check.get("expected_decimal"),
                actual_decimal=check.get("actual_decimal"),applicable=check.get("applicable"),
                justification=check.get("justification"),diagnostics=diagnostics))
        base = "/api/packs/"+state["pack_id"]+"/artifacts/"
        candidate,publication = state.get("candidate"),state.get("publication")
        output = None
        if candidate:
            publication_query = "?publication_id="+publication["publication_id"] if publication else ""
            output = CandidateSnapshot(artifact_id=candidate["artifact_id"],
                total_decimal=candidate.get("total_decimal") or "0",download_url=base+candidate["artifact_id"]+"/download"+publication_query,
                checked_version=candidate["snapshot_version"],total_label=state.get("total_label","Checked output total"),released=bool(publication),manifest_url=base+publication["manifest_id"]+"/download"+publication_query if publication else None)
        historical = current_version is not None and current_version!=state["version"]
        return PackSnapshot(pack_id=state["pack_id"],version=state["version"],fund_id=state["fund_id"],
            title=state.get("title",state["pack_id"]),execution_status={"NOT_RUN":"PENDING"}.get(
                state.get("execution_status","PENDING"),state.get("execution_status","PENDING")),
            checks=checks,routing_status=state.get("routing_status","BLOCKED"),review_status=state.get("review_status","PENDING"),
            freshness="STALE" if historical else state.get("freshness","STALE"),facts=facts,candidate=output,
            history=state.get("history",()),evidence=evidence,observations=state.get("observations",()),
            extraction_observations=state.get("extraction_observations",()),source_occurrences=state.get("source_occurrences",()),
            dependency_edges=state.get("dependency_edges",()),impact=state.get("impact",{}),
            routing_reasons=state.get("routing_reasons",()),routing_explanation=state.get("routing_explanation")
                if state.get("routing_explanation",{} ) and state["routing_explanation"].get("route")==state.get("routing_status") else None,
            priority=state.get("priority") or {"status":"UNAVAILABLE","level":None,"policy_version":None,
                "amount_decimal":None,"materiality_decimal":None,"currency":None,"dependent_outputs":None,
                "impact_threshold":None,"reasons":["current_priority_not_evaluated"]},policy_version=state.get("policy_version"),
            execution_error=state.get("execution_error"),publication=publication,publications=state.get("publications",()),
            review=state.get("approval"),resolution=state.get("soft_resolution"),external_freshness=state.get("external_freshness"))
