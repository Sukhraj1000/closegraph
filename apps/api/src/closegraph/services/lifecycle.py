"""In-process domain lifecycle; bridge interfaces (stable, duck-typed):

LifecycleService(repository, blobs, authorizer, evaluator, *, required_check_ids=None, clock=None)
repository.get(pack_id, scope, version=None) -> copied dict, immutable history
repository.create(state) -> dict (version 1)
repository.save(state, expected_version) -> dict (atomic CAS + append-only version)
blobs.put(bytes) -> sha256 hex; blobs.get(sha256 hex) -> verified bytes
authorizer.require(actor, scope, action) -> None or AccessDenied
evaluator(state_copy, blobs) -> {"checks": list[dict], "values": dict[str,str]}
evaluator.required_check_ids -> tuple[str,...] (or constructor argument)

Actions: inspect, correct, recompute, review, publish, download, invalidate.
Scope is server-resolved fund_id. Request receipts/publication indexes are JSON
inside each snapshot. PostgreSQL must wrap each WHOLE action in a scoped row-lock
transaction, including authoritative permissions, and save CAS the same row.
Write immutable blobs before state commit; losing-CAS orphan blobs are acceptable.
No factories, HTTP, live providers or independent task queue in this module.
"""
from copy import deepcopy
from datetime import datetime, timezone
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from closegraph.outputs.manifest import canonical_bytes, snapshot_digest, build_manifest, verify_manifest
from closegraph.outputs.workbook import TemplateContract, generate_workbook, verify_roundtrip
from .corrections import corrected_facts
from .errors import DomainError, Conflict, AccessDenied
from .impact import dependency_impact
from .parser_signals import compare_observations
from .repository import MemoryRepository, MemoryBlobs, MemoryAuthorizer
from .review import make_approval, verify_approval
from .publication import Download, publication_record
from .routing import explain_route, priority


class LifecycleService:
    def __init__(self, repository, blobs, authorizer, evaluator, *, required_check_ids=None, clock=None):
        self.repository, self.blobs, self.authorizer = repository, blobs, authorizer
        self.evaluator = evaluator
        self.required_check_ids = tuple(required_check_ids if required_check_ids is not None else evaluator.required_check_ids)
        if not self.required_check_ids or len(set(self.required_check_ids)) != len(self.required_check_ids):
            raise DomainError("An explicit required-check contract is required")
        self.clock = clock or (lambda: datetime.now(timezone.utc).isoformat())

    def _read(self, pack_id, actor, scope, action, version=None):
        self.authorizer.require(actor, scope, action)
        state = self.repository.get(pack_id, scope, version=version)
        if state.get("pack_id") != pack_id or state.get("fund_id") != scope:
            raise AccessDenied("Resource unavailable in scope")
        return state

    def inspect(self, pack_id, *, actor, scope, version=None):
        return self._read(pack_id, actor, scope, "inspect", version)

    def _replay(self, current, key, fingerprint):
        receipt = current.get("request_receipts", {}).get(key) if key is not None else None
        if receipt is None:
            return None
        if receipt["request_digest"] != fingerprint:
            raise Conflict("Idempotency key reused with different request")
        return self.repository.get(current["pack_id"], current["fund_id"], version=receipt["version"])

    def _begin(self, pack_id, actor, scope, expected_version, action, payload, idempotency_key, *, automatic=False):
        state = self._read(pack_id, actor, scope, action)
        if type(expected_version) is not int or expected_version < 1:
            raise DomainError("Positive integer expected_version required")
        key = None
        if idempotency_key is not None:
            if not isinstance(idempotency_key, str) or not idempotency_key.strip() or len(idempotency_key) > 200:
                raise DomainError("Invalid idempotency key")
            key = sha256(canonical_bytes([actor, "explicit", idempotency_key])).hexdigest()
        elif automatic:
            key = sha256(canonical_bytes([actor, action, expected_version])).hexdigest()
        fingerprint = sha256(canonical_bytes({"action": action, "actor": actor, "scope": scope,
                          "pack_id": pack_id, "expected_version": expected_version, "payload": payload})).hexdigest()
        replay = self._replay(state, key, fingerprint)
        if replay is not None:
            if action == "publish":
                self._current_publication(state, replay)
                self._release_gate(replay)
            return state, replay, key, fingerprint
        if state["version"] != expected_version:
            raise Conflict("Snapshot revision changed")
        return state, None, key, fingerprint

    def _commit(self, state, *, actor, action, key, fingerprint, details=None):
        expected = state["version"]
        state["version"] = expected + 1
        state.setdefault("history", []).append({"action": action, "actor": actor,
            "at": self.clock(), "input_version": expected, "version": state["version"], **(details or {})})
        if key is not None:
            state.setdefault("request_receipts", {})[key] = {"request_digest": fingerprint, "version": state["version"]}
        permission = {"CORRECTED": "correct", "RECOMPUTED": "recompute", "APPROVED": "review",
                      "PUBLISHED": "publish", "INVALIDATED": "invalidate", "REJECTED": "reject", "RESOLVED": "review"}[action]
        self.authorizer.require(actor, state["fund_id"], permission)
        try:
            return self.repository.save(state, expected)
        except Conflict:
            current = self.repository.get(state["pack_id"], state["fund_id"])
            replay = self._replay(current, key, fingerprint)
            if replay is None:
                raise
            if action == "PUBLISHED":
                self._current_publication(current, replay)
                self._release_gate(replay)
            return replay

    @staticmethod
    def _stale(state):
        state.update(freshness="STALE", routing_status="BLOCKED", review_status="PENDING",
                     execution_status="NOT_RUN", candidate=None, approval=None, publication=None, execution_error=None, soft_resolution=None,
                     routing_explanation=None,routing_reasons=["processing_required"],priority=None)

    def correct(self, pack_id, *, actor, scope, expected_version, fact_id, value_decimal,
                reason, source_id, idempotency_key=None):
        payload = dict(fact_id=fact_id, value_decimal=value_decimal, reason=reason, source_id=source_id)
        state, replay, key, fp = self._begin(pack_id, actor, scope, expected_version, "correct", payload, idempotency_key)
        if replay is not None:
            return replay
        self._evidence(state)
        facts, before = corrected_facts(state["facts"], evidence=state["evidence"], **payload)
        state["facts"] = facts
        state["contributors"] = sorted(set(state.get("contributors", [])) | {actor})
        impact = dependency_impact({fact_id}, state["dependency_edges"], {"output"},
                                   coverage_complete=state["dependency_coverage"] is True)
        state["impact"] = {"affected": sorted(impact.affected), "independent": sorted(impact.independent), "unverifiable": impact.unverifiable}
        self._stale(state)
        return self._commit(state, actor=actor, action="CORRECTED", key=key, fingerprint=fp,
                            details={**payload, "before": before, "after": next(f["value_decimal"] for f in facts if f["fact_id"] == fact_id),
                                     "impact": deepcopy(state["impact"])})

    def invalidate(self, pack_id, *, actor, scope, expected_version, changes, reason, idempotency_key=None):
        state, replay, key, fp = self._begin(pack_id, actor, scope, expected_version, "invalidate",
                                            dict(changes=changes, reason=reason), idempotency_key)
        if replay is not None:
            return replay
        allowed = {"source_versions", "rule_version", "mapping_version", "policy_version", "dependency_coverage",
                   "dependency_edges", "template", "observations", "evidence", "external_freshness", "rule", "mappings", "policy"}
        if not isinstance(reason, str) or not reason.strip() or not isinstance(changes, dict) or not changes or set(changes) - allowed:
            raise DomainError("Supported version change and reason required")
        for record_key,version_key in (("rule","rule_version"),("mappings","mapping_version"),("policy","policy_version")):
            if record_key in changes and state.get(version_key) == changes.get(version_key):
                if state.get(record_key) != changes[record_key]:
                    raise DomainError("Configured records cannot change without a new version")
        before = {k: deepcopy(state.get(k)) for k in changes}
        state.update(deepcopy(changes))
        configured = {key:deepcopy(value) for key,value in changes.items()
                      if key in {"rule","rule_version","mappings","mapping_version","template","policy","policy_version"}}
        if configured:
            state.setdefault("configured_records",{}).update(configured)
        affected = {"output"} | {kind for kind,version_key in
            (("rule","rule_version"),("mapping","mapping_version"),("policy","policy_version")) if version_key in changes}
        state["impact"] = {"affected":sorted(affected),"independent":[],
                           "unverifiable":state.get("dependency_coverage") is not True}
        state["contributors"] = sorted(set(state.get("contributors", [])) | {actor})
        self._stale(state)
        return self._commit(state, actor=actor, action="INVALIDATED", key=key, fingerprint=fp,
                            details={"reason": reason, "before": before, "changes": deepcopy(changes),
                                     "impact":deepcopy(state["impact"])})

    def _evidence(self, state):
        evidence = state.get("evidence", {})
        if not evidence or not state.get("facts"):
            raise DomainError("Required evidence unavailable")
        for source_id, source in evidence.items():
            if (not source.get("locator") or not source.get("content_hash")
                    or state.get("source_versions", {}).get(source_id) != source.get("source_version")
                    or source.get("fund_id", state["fund_id"]) != state["fund_id"]
                    or source.get("pack_id", state["pack_id"]) != state["pack_id"]):
                raise DomainError("Required evidence identity/context unavailable")
            self._blob(source["content_hash"])
        for fact in state["facts"]:
            ids = [fact.get("source", {}).get("source_id"), fact.get("correction_source_id")]
            if not ids[0]:
                raise DomainError("Fact original lineage unavailable")
            for source_id in filter(None, ids):
                source = evidence.get(source_id)
                if (not source or fact["fact_id"] not in source.get("fact_ids", [])
                        or any(not fact.get(k) or source.get(k) != fact.get(k) for k in ("entity_id", "currency", "period"))):
                    raise DomainError("Fact evidence context mismatch")

    def _blob(self, identity):
        data = self.blobs.get(identity)
        if not isinstance(data, bytes) or sha256(data).hexdigest() != identity:
            raise DomainError("Referenced bytes missing or corrupt")
        return data

    def _routing(self, state):
        impact = dependency_impact(set(), state["dependency_edges"], {"output"}, coverage_complete=state["dependency_coverage"] is True)
        signals = [compare_observations(o.get("primary", {}), o.get("secondary"), availability=o.get("availability", "NOT_RUN"))
                   for o in state.get("observations", [])]
        agreement = next((s for s in ["DISAGREE", "UNKNOWN", "UNAVAILABLE", "NOT_RUN", "NOT_APPLICABLE", "AGREE"] if s in signals), "UNKNOWN")
        decision = explain_route(state["checks"], native=state.get("native") is True,
            policy_version=state["policy_version"], agreement=agreement,confidence=state.get("confidence"),
            unverifiable=impact.unverifiable or state.get("external_freshness") == "UNKNOWN",
            required_ids=self.required_check_ids)
        state["routing_explanation"] = asdict(decision)
        state["routing_reasons"] = list(decision.reasons)
        state["priority"] = self.review_priority(state)
        return decision.route

    @staticmethod
    def review_priority(state):
        policy = state.get("priority_policy") or {}
        result = {"status":"UNAVAILABLE","level":None,"policy_version":policy.get("version"),
            "amount_decimal":None,"materiality_decimal":None,"currency":policy.get("currency"),
            "dependent_outputs":None,"impact_threshold":policy.get("impact_threshold"),"reasons":[]}
        if not policy or not isinstance(policy.get("version"),str) or not policy["version"].strip():
            result["reasons"] = ["materiality_policy_not_configured"]
            return result
        # The bounded output has one declared total; never add unlike currencies
        # or substitute a missing amount with zero.
        currencies = {fact.get("currency") for fact in state.get("facts",())}
        if not currencies or currencies != {policy.get("currency")} or None in currencies:
            result["reasons"] = ["amount_currency_context_unavailable"]
            return result
        impact = dependency_impact({fact["fact_id"] for fact in state.get("facts",())},
            state.get("dependency_edges",()),{"output"},coverage_complete=state.get("dependency_coverage") is True)
        if impact.unverifiable:
            result["reasons"] = ["downstream_impact_unverifiable"]
            return result
        raw_amount = state.get("values",{}).get("total")
        raw_materiality = policy.get("materiality_decimal")
        if any(isinstance(value,(bool,float)) or value is None for value in (raw_amount,raw_materiality)):
            result["reasons"] = ["exact_amount_or_materiality_unavailable"]
            return result
        try:
            amount,materiality = Decimal(raw_amount),Decimal(raw_materiality)
            count = len({"output"} & set(impact.affected))
            threshold = policy.get("impact_threshold",2)
            level = priority(amount,materiality,count,impact_threshold=threshold)
        except (InvalidOperation,TypeError,ValueError):
            result["reasons"] = ["invalid_configured_priority_inputs"]
            return result
        reasons=[]
        if abs(amount)>=materiality: reasons.append("amount_meets_materiality")
        if count>=threshold: reasons.append("downstream_impact_meets_threshold")
        return {**result,"status":"AVAILABLE","level":level,"amount_decimal":format(amount,"f"),
            "materiality_decimal":format(materiality,"f"),"dependent_outputs":count,"impact_threshold":threshold,
            "reasons":reasons or ["below_configured_priority_thresholds"]}

    @staticmethod
    def _contract(state):
        template = state["template"]
        return TemplateContract(template["template_hash"], tuple(tuple(b) for b in template["bindings"]), template["version"])

    def recompute(self, pack_id, *, actor, scope, expected_version, idempotency_key=None):
        state, replay, key, fp = self._begin(pack_id, actor, scope, expected_version, "recompute", {}, idempotency_key, automatic=True)
        if replay is not None:
            return replay
        self._stale(state)
        try:
            self._evidence(state)
            result = self.evaluator(deepcopy(state), self.blobs)
            state["checks"], state["values"] = deepcopy(result["checks"]), deepcopy(result["values"])
            state["required_check_ids"] = list(self.required_check_ids)
            state["routing_status"] = self._routing(state)
            state["execution_status"], state["freshness"] = "COMPLETED", "CURRENT"
            if state["routing_status"] != "BLOCKED":
                contract = self._contract(state)
                artifact = generate_workbook(self._blob(contract.template_hash), contract, state["values"])
                artifact_id = self.blobs.put(artifact)
                self._blob(artifact_id)
                state["candidate"] = {"artifact_id": artifact_id, "snapshot_version": expected_version + 1,
                                      "snapshot_digest": snapshot_digest(state), "total_decimal": state["values"].get("total")}
        except DomainError as exc:
            state.update(execution_status="FAILED", freshness="STALE", routing_status="BLOCKED", candidate=None, execution_error=str(exc))
        return self._commit(state, actor=actor, action="RECOMPUTED", key=key, fingerprint=fp,
                            details={"execution_status": state["execution_status"], "routing_status": state["routing_status"]})

    def _candidate_gate(self, state):
        if (state.get("freshness") != "CURRENT" or state.get("execution_status") != "COMPLETED"
                or not state.get("candidate") or self._routing(state) == "BLOCKED" or state["routing_status"] != self._routing(state)
                or state["candidate"]["snapshot_digest"] != snapshot_digest(state)
                or list(self.required_check_ids) != state.get("required_check_ids")):
            raise DomainError("Current checked candidate required")
        self._evidence(state)
        contract = self._contract(state)
        artifact = self._blob(state["candidate"]["artifact_id"])
        verify_roundtrip(self._blob(contract.template_hash), artifact, contract, state["values"])
        return artifact

    def resolve(self, pack_id, *, actor, scope, expected_version, reason, source_ids, idempotency_key=None):
        state, replay, key, fp = self._begin(pack_id, actor, scope, expected_version, "review",
            {"reason":reason, "source_ids":source_ids, "decision":"RESOLVE"}, idempotency_key)
        if replay is not None:
            return replay
        self._candidate_gate(state)
        from .review import independent
        independent(state, actor)
        if state["routing_status"] != "NEEDS_REVIEW" or not isinstance(reason, str) or not reason.strip():
            raise DomainError("An unresolved soft signal and evidence-backed reason are required")
        if not source_ids or any(s not in state["evidence"] for s in source_ids):
            raise DomainError("Resolution requires in-scope source evidence")
        state["soft_resolution"] = {"actor":actor, "at":self.clock(), "reason":reason.strip(),
            "source_ids":list(source_ids), "snapshot_digest":snapshot_digest(state)}
        return self._commit(state, actor=actor, action="RESOLVED", key=key, fingerprint=fp,
            details={"resolution":deepcopy(state["soft_resolution"])})

    def reject(self, pack_id, *, actor, scope, expected_version, note, idempotency_key=None):
        state, replay, key, fp = self._begin(pack_id, actor, scope, expected_version, "reject", {"note":note}, idempotency_key)
        if replay is not None:
            return replay
        if not isinstance(note, str) or not note.strip():
            raise DomainError("A revision request requires a reason")
        state["approval"] = None
        state["review_status"] = "PENDING"
        state["publication"] = None
        return self._commit(state, actor=actor, action="REJECTED", key=key, fingerprint=fp, details={"note":note.strip()})

    def review(self, pack_id, *, actor, scope, expected_version, note, attested, adjudication=None, idempotency_key=None):
        payload = dict(note=note, attested=attested, adjudication=adjudication)
        state, replay, key, fp = self._begin(pack_id, actor, scope, expected_version, "review", payload, idempotency_key)
        if replay is not None:
            return replay
        self._candidate_gate(state)
        if adjudication is None and state.get("soft_resolution"):
            resolution = state["soft_resolution"]
            if resolution["snapshot_digest"] != snapshot_digest(state):
                raise DomainError("Resolution snapshot is stale")
            payload["adjudication"] = {k:resolution[k] for k in ("reason", "source_ids")}
        state["approval"] = make_approval(state, actor=actor, at=self.clock(), **payload)
        state["review_status"] = "APPROVED"
        return self._commit(state, actor=actor, action="APPROVED", key=key, fingerprint=fp, details={"approval": deepcopy(state["approval"])})

    def _release_gate(self, state):
        artifact = self._candidate_gate(state)
        approval = verify_approval(state)
        self.authorizer.require(approval["actor"], state["fund_id"], "review")
        return artifact, approval

    @staticmethod
    def _current_publication(current, historical):
        if (current.get("freshness") != "CURRENT" or not current.get("publication")
                or current["publication"] != historical.get("publication") or snapshot_digest(current) != snapshot_digest(historical)):
            raise Conflict("Publication has been superseded")

    def publish(self, pack_id, *, actor, scope, expected_version, idempotency_key=None):
        state, replay, key, fp = self._begin(pack_id, actor, scope, expected_version, "publish", {}, idempotency_key, automatic=True)
        if replay is not None:
            return replay
        artifact, approval = self._release_gate(state)
        if state.get("publication") is not None:
            return state
        publication = publication_record(state, artifact, approval, actor=actor, at=self.clock(), blobs=self.blobs)
        self._blob(publication["manifest_id"])
        state["publication"] = publication
        state.setdefault("publications", []).append(deepcopy(publication))
        return self._commit(state, actor=actor, action="PUBLISHED", key=key, fingerprint=fp, details={"publication_id": publication["publication_id"]})

    def download(self, pack_id, *, actor, scope, publication_id=None):
        current = self._read(pack_id, actor, scope, "download")
        publication = (current.get("publication") if publication_id is None else
                       next((p for p in current.get("publications", []) if p["publication_id"] == publication_id), None))
        if publication is None:
            raise DomainError("Publication unavailable in scope")
        state = self.repository.get(pack_id, scope, version=publication["version"])
        artifact = self._candidate_gate(state)
        approval = verify_approval(state)
        manifest = self._blob(publication["manifest_id"])
        expected_manifest = build_manifest(state, artifact, approval)
        if canonical_bytes(expected_manifest) != manifest:
            raise DomainError("Stored manifest does not match publication")
        verify_manifest(expected_manifest, artifact)
        freshness = "CURRENT" if (current.get("publication") == publication and current.get("freshness") == "CURRENT"
                                   and snapshot_digest(current) == snapshot_digest(state)) else "STALE"
        return Download(artifact, manifest, freshness, publication["publication_id"], publication["snapshot_version"])
