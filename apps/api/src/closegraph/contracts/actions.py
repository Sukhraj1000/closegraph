from typing import Annotated, Literal

from pydantic import Field, StrictBool, model_validator

from .evidence import SourceRef
from .types import Contract, ExactDecimal, Identifier, Version


class VersionAction(Contract):
    expected_version: Version
    idempotency_key: Annotated[str, Field(min_length=1, max_length=200)] | None = None


class CorrectionRequest(VersionAction):
    fact_id: Identifier
    value_decimal: ExactDecimal
    reason: Annotated[str, Field(min_length=1, max_length=4000)]
    source_id: Identifier

    @model_validator(mode="after")
    def reason_required(self):
        if not self.reason.strip(): raise ValueError("reason cannot be blank")
        return self


class Adjudication(Contract):
    reason: Annotated[str, Field(min_length=1, max_length=4000)]
    source_ids: tuple[Identifier, ...]


class ReviewRequest(VersionAction):
    note: Annotated[str, Field(min_length=1, max_length=4000)]
    attested: StrictBool
    adjudication: Adjudication | None = None

    @model_validator(mode="after")
    def attestation_required(self):
        if not self.attested or not self.note.strip():
            raise ValueError("review requires explicit attestation and a note")
        return self


class CheckSummary(Contract):
    id: Identifier
    label: str
    status: Literal["PASS", "FAIL", "UNKNOWN", "NOT_RUN", "NOT_APPLICABLE"]
    required: StrictBool
    detail: str
    operands: tuple[dict, ...] = ()
    difference: ExactDecimal | None = None
    tolerance: ExactDecimal | None = None
    rule_version: str | None = None
    expected_decimal: ExactDecimal | None = None
    actual_decimal: ExactDecimal | None = None
    applicable: StrictBool | None = None
    justification: str | None = None
    diagnostics: tuple[str, ...] = ()


class FactSnapshot(Contract):
    fact_id: Identifier
    metric: Identifier
    value_decimal: ExactDecimal | None
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] | None
    period: str | None
    entity_id: Identifier | None
    raw_value: str | None
    raw_scale: str | None
    source: SourceRef
    derived: StrictBool = False
    fact_version: Version = 1
    value_state: str = "PRESENT"
    interpretation_status: str = "UNRESOLVED"
    observation_ids: tuple[Identifier, ...] = ()
    correction_source_id: Identifier | None = None


class CandidateSnapshot(Contract):
    artifact_id: Identifier
    total_decimal: ExactDecimal
    download_url: str
    checked_version: Version | None = None
    total_label: str = "Checked output total"
    released: StrictBool = False
    manifest_url: str | None = None


class PackSnapshot(Contract):
    pack_id: Identifier
    version: Version
    fund_id: Identifier
    title: str
    execution_status: Literal["PENDING", "RUNNING", "COMPLETED", "FAILED"]
    checks: tuple[CheckSummary, ...]
    routing_status: Literal["BLOCKED", "NEEDS_REVIEW", "READY_FOR_QUICK_REVIEW"]
    review_status: Literal["PENDING", "APPROVED"]
    freshness: Literal["CURRENT", "STALE"]
    facts: tuple[FactSnapshot, ...]
    candidate: CandidateSnapshot | None
    history: tuple[dict, ...]
    evidence: dict[str, dict] = {}
    observations: tuple[dict, ...] = ()
    extraction_observations: tuple[dict, ...] = ()
    source_occurrences: tuple[dict, ...] = ()
    dependency_edges: tuple[tuple[str, str], ...] = ()
    impact: dict = {}
    routing_reasons: tuple[str, ...] = ()
    routing_explanation: dict | None = None
    priority: dict = {}
    policy_version: str | None = None
    execution_error: str | None = None
    publication: dict | None = None
    publications: tuple[dict, ...] = ()
    review: dict | None = None
    resolution: dict | None = None
    external_freshness: str | None = None


class UploadRequest(VersionAction):
    source_id: Identifier
    filename: Annotated[str, Field(min_length=1, max_length=256)]
    media_type: Annotated[str, Field(min_length=1, max_length=256)]
    content_base64: Annotated[str, Field(min_length=1, max_length=44739244)]


class RejectRequest(VersionAction):
    note: Annotated[str, Field(min_length=1, max_length=4000)]


class ResolutionRequest(VersionAction):
    reason: Annotated[str, Field(min_length=1, max_length=4000)]
    source_ids: tuple[Identifier, ...]


class ReviewEventRequest(Contract):
    event_type: Literal["SOURCE_OPENED", "VALUE_INSPECTED", "READY_ITEM_SAMPLED"]
    observed_snapshot_version: Version
    fact_id: Identifier | None = None
    document_version_id: Identifier | None = None
    idempotency_key: Annotated[str, Field(min_length=1, max_length=200)] | None = None

    @model_validator(mode="after")
    def target_required(self):
        if self.event_type == "SOURCE_OPENED" and self.document_version_id is None:
            raise ValueError("Source opening requires its immutable document version")
        if self.event_type == "VALUE_INSPECTED" and self.fact_id is None:
            raise ValueError("Value inspection requires a fact")
        return self


class ConfigurationChangeRequest(VersionAction):
    """Trusted server-side configured records, never an HTTP rule override."""
    changes: dict
    reason: Annotated[str, Field(min_length=1, max_length=4000)]

    @model_validator(mode="after")
    def complete_versioned_records(self):
        allowed = {"rule","rule_version","mappings","mapping_version","policy","policy_version","template"}
        if not self.reason.strip() or not self.changes or set(self.changes) - allowed:
            raise ValueError("A supported configured change and reason are required")
        found = False
        for record_key,version_key in (("rule","rule_version"),("mappings","mapping_version"),("policy","policy_version")):
            if record_key in self.changes or version_key in self.changes:
                found = True
                record,version = self.changes.get(record_key),self.changes.get(version_key)
                if (not isinstance(record,dict) or len(record)<2 or not isinstance(version,str)
                        or not version.strip() or len(version)>256 or record.get("version") != version):
                    raise ValueError("A complete configured record must accompany its matching version")
        if not found:
            raise ValueError("Template updates require a versioned mapping record")
        if "mappings" in self.changes:
            template=self.changes.get("template")
            if not isinstance(template,dict) or self.changes["mappings"].get("template") != template:
                raise ValueError("Mapping records must pin the complete output template contract")
        elif "template" in self.changes:
            raise ValueError("Template updates require a versioned mapping record")
        return self
