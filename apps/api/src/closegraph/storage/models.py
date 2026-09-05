"""Scoped relational records; all financial/historical records are append-only.

NUMERIC deliberately has no fixed scale: PostgreSQL preserves supplied Decimal
precision rather than rounding all monetary operands to two decimal places.
"""
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


def utcnow(): return datetime.now(timezone.utc)


class Base(DeclarativeBase): pass


class Scoped:
    tenant_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    fund_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    pack_id: Mapped[str] = mapped_column(String(256), primary_key=True)


class Record(Scoped):
    id: Mapped[str] = mapped_column(String(256), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


def scope_fk(table, local="id", remote="id"):
    return ForeignKeyConstraint(["tenant_id", "fund_id", "pack_id", local],
        [f"{table}.tenant_id", f"{table}.fund_id", f"{table}.pack_id", f"{table}.{remote}"], ondelete="RESTRICT")


def pack_fk():
    return ForeignKeyConstraint(["tenant_id", "fund_id", "pack_id"],
                                ["packs.tenant_id", "packs.fund_id", "packs.pack_id"], ondelete="RESTRICT")


class PackRow(Scoped, Base):
    __tablename__ = "packs"
    title: Mapped[str] = mapped_column(Text)
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (CheckConstraint("current_version >= 1", name="pack_positive_version"),)


class PackRevisionRow(Record, Base):
    __tablename__ = "pack_revisions"
    version: Mapped[int] = mapped_column(Integer)
    prepared_by: Mapped[str] = mapped_column(String(256))
    input_snapshot: Mapped[dict] = mapped_column(JSON)
    policy_version: Mapped[str] = mapped_column(String(256))
    __table_args__ = (pack_fk(), UniqueConstraint("tenant_id","fund_id","pack_id","version"),
                      CheckConstraint("version >= 1", name="revision_positive_version"))


class DocumentVersionRow(Record, Base):
    __tablename__ = "document_versions"
    source_id: Mapped[str] = mapped_column(String(256))
    version: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(256))
    content_hash: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(64))
    byte_size: Mapped[int] = mapped_column(Integer)
    filename: Mapped[str] = mapped_column(String(256))
    media_type: Mapped[str] = mapped_column(String(256))
    receipt_actor_id: Mapped[str] = mapped_column(String(256))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    authority_status: Mapped[str] = mapped_column(String(32), default="UNRESOLVED")
    coverage_status: Mapped[str] = mapped_column(String(32), default="UNKNOWN")
    __table_args__ = (pack_fk(), UniqueConstraint("tenant_id","fund_id","pack_id","idempotency_key"),
        UniqueConstraint("tenant_id","fund_id","pack_id","source_id","version"),
        CheckConstraint("version >= 1 AND byte_size >= 0", name="document_positive_size_version"),
        CheckConstraint("storage_key = content_hash", name="document_hash_key"))


class SourceOccurrenceRow(Record, Base):
    __tablename__ = "source_occurrences"
    document_version_id: Mapped[str] = mapped_column(String(256))
    locator: Mapped[dict] = mapped_column(JSON)
    raw_content: Mapped[str] = mapped_column(Text)
    context_evidence_ids: Mapped[list] = mapped_column(JSON)
    disposition: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (scope_fk("document_versions", "document_version_id"),)


class ExtractionObservationRow(Record, Base):
    __tablename__ = "extraction_observations"
    occurrence_id: Mapped[str] = mapped_column(String(256))
    parser: Mapped[str] = mapped_column(String(256))
    parser_version: Mapped[str] = mapped_column(String(256))
    settings: Mapped[dict] = mapped_column(JSON)
    response_id: Mapped[str] = mapped_column(String(256))
    response_content_hash: Mapped[str | None] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[dict] = mapped_column(JSON)
    candidate: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (scope_fk("source_occurrences", "occurrence_id"),)


class FactVersionRow(Record, Base):
    __tablename__ = "fact_versions"
    fact_id: Mapped[str] = mapped_column(String(256))
    version: Mapped[int] = mapped_column(Integer)
    revision_id: Mapped[str] = mapped_column(String(256))
    document_version_id: Mapped[str] = mapped_column(String(256))
    metric: Mapped[str] = mapped_column(String(256))
    entity_id: Mapped[str | None] = mapped_column(String(256))
    period: Mapped[str | None] = mapped_column(String(256))
    value_decimal: Mapped[Decimal | None] = mapped_column(Numeric(asdecimal=True))
    currency: Mapped[str | None] = mapped_column(String(3))
    raw_value: Mapped[str | None] = mapped_column(Text)
    raw_scale: Mapped[str | None] = mapped_column(String(256))
    value_state: Mapped[str] = mapped_column(String(32))
    interpretation_status: Mapped[str] = mapped_column(String(32))
    evidence: Mapped[dict] = mapped_column(JSON)
    observation_ids: Mapped[list] = mapped_column(JSON)
    interpretation_rule_id: Mapped[str | None] = mapped_column(String(256))
    correction_id: Mapped[str | None] = mapped_column(String(256))
    supersedes: Mapped[str | None] = mapped_column(String(256))
    __table_args__ = (scope_fk("document_versions", "document_version_id"), scope_fk("pack_revisions", "revision_id"),
        scope_fk("fact_versions", "supersedes"), UniqueConstraint("tenant_id","fund_id","pack_id","fact_id","version"),
        CheckConstraint("version >= 1", name="fact_positive_version"),
        CheckConstraint("(value_state != 'PRESENT' OR value_decimal IS NOT NULL) AND (value_state NOT IN ('MISSING','NOT_APPLICABLE') OR value_decimal IS NULL)", name="fact_missing_not_zero"))


class CheckResultRow(Record, Base):
    __tablename__ = "check_results"
    revision_id: Mapped[str] = mapped_column(String(256))
    check_key: Mapped[str] = mapped_column(String(256))
    rule_version: Mapped[str] = mapped_column(String(256))
    input_snapshot: Mapped[dict] = mapped_column(JSON)
    required: Mapped[bool] = mapped_column(Boolean)
    applicability: Mapped[str] = mapped_column(String(32))
    operands: Mapped[list] = mapped_column(JSON)
    difference: Mapped[Decimal | None] = mapped_column(Numeric(asdecimal=True))
    tolerance: Mapped[Decimal | None] = mapped_column(Numeric(asdecimal=True))
    status: Mapped[str] = mapped_column(String(32))
    diagnostics: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (scope_fk("pack_revisions", "revision_id"),
        UniqueConstraint("tenant_id","fund_id","pack_id","revision_id","check_key","rule_version"),
        CheckConstraint("status IN ('PASS','FAIL','UNKNOWN','NOT_RUN','NOT_APPLICABLE')", name="check_status_valid"))


class DependencyEdgeRow(Record, Base):
    __tablename__ = "dependency_edges"
    revision_id: Mapped[str] = mapped_column(String(256))
    upstream_kind: Mapped[str] = mapped_column(String(32))
    upstream_id: Mapped[str] = mapped_column(String(256))
    downstream_kind: Mapped[str] = mapped_column(String(32))
    downstream_id: Mapped[str] = mapped_column(String(256))
    provenance: Mapped[dict] = mapped_column(JSON)
    coverage_status: Mapped[str] = mapped_column(String(32))
    __table_args__ = (scope_fk("pack_revisions", "revision_id"),
        UniqueConstraint("tenant_id","fund_id","pack_id","revision_id","upstream_kind","upstream_id","downstream_kind","downstream_id"))


class CorrectionRow(Record, Base):
    __tablename__ = "corrections"
    previous_revision_id: Mapped[str] = mapped_column(String(256))
    revision_id: Mapped[str] = mapped_column(String(256))
    previous_fact_id: Mapped[str] = mapped_column(String(256))
    corrected_fact_id: Mapped[str] = mapped_column(String(256))
    source_id: Mapped[str] = mapped_column(String(256))
    actor_id: Mapped[str] = mapped_column(String(256))
    reason: Mapped[str] = mapped_column(Text)
    __table_args__ = (scope_fk("pack_revisions", "revision_id"), scope_fk("pack_revisions", "previous_revision_id"),
                      scope_fk("fact_versions", "previous_fact_id"), scope_fk("fact_versions", "corrected_fact_id"),
                      scope_fk("document_versions", "source_id"))


class ArtifactRow(Record, Base):
    __tablename__ = "artifacts"
    revision_id: Mapped[str] = mapped_column(String(256))
    storage_key: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64))
    byte_size: Mapped[int] = mapped_column(Integer)
    filename: Mapped[str] = mapped_column(String(256))
    media_type: Mapped[str] = mapped_column(String(256))
    validation: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (scope_fk("pack_revisions", "revision_id"),
                      CheckConstraint("storage_key = content_hash AND byte_size >= 0", name="artifact_integrity_fields"))


class ReviewDecisionRow(Record, Base):
    __tablename__ = "review_decisions"
    revision_id: Mapped[str] = mapped_column(String(256))
    artifact_id: Mapped[str] = mapped_column(String(256))
    actor_id: Mapped[str] = mapped_column(String(256))
    decision: Mapped[str] = mapped_column(String(32))
    note: Mapped[str] = mapped_column(Text)
    attested: Mapped[bool] = mapped_column(Boolean)
    dependency_snapshot: Mapped[dict] = mapped_column(JSON)
    policy_version: Mapped[str] = mapped_column(String(256))
    __table_args__ = (scope_fk("pack_revisions", "revision_id"), scope_fk("artifacts", "artifact_id"),
                      CheckConstraint("decision IN ('APPROVED','REJECTED','REVOKED')", name="review_decision_valid"))


class PublicationRow(Record, Base):
    __tablename__ = "publications"
    revision_id: Mapped[str] = mapped_column(String(256))
    review_decision_id: Mapped[str] = mapped_column(String(256))
    artifact_id: Mapped[str] = mapped_column(String(256))
    manifest_artifact_id: Mapped[str] = mapped_column(String(256))
    actor_id: Mapped[str] = mapped_column(String(256))
    release_key: Mapped[str] = mapped_column(String(256))
    __table_args__ = (scope_fk("pack_revisions", "revision_id"), scope_fk("review_decisions", "review_decision_id"),
                      scope_fk("artifacts", "artifact_id"), scope_fk("artifacts", "manifest_artifact_id"),
                      UniqueConstraint("tenant_id","fund_id","pack_id","release_key"),
                      UniqueConstraint("tenant_id","fund_id","pack_id","revision_id","artifact_id"))


class ProcessingRequestRow(Record, Base):
    __tablename__ = "processing_requests"
    revision_id: Mapped[str | None] = mapped_column(String(256))
    document_version_id: Mapped[str | None] = mapped_column(String(256))
    processing_key: Mapped[str] = mapped_column(String(256))
    stage: Mapped[str] = mapped_column(String(64))
    code_version: Mapped[str] = mapped_column(String(256))
    config_version: Mapped[str] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(32), default="PENDING")
    dagster_run_id: Mapped[str | None] = mapped_column(String(256))
    __table_args__ = (scope_fk("pack_revisions", "revision_id"), scope_fk("document_versions", "document_version_id"),
                      UniqueConstraint("tenant_id","fund_id","pack_id","processing_key"),
                      CheckConstraint("revision_id IS NOT NULL OR document_version_id IS NOT NULL", name="request_has_input"),
                      CheckConstraint("status IN ('PENDING','ACKNOWLEDGED','RUNNING','COMPLETED','FAILED')", name="request_status_valid"))


class ProcessingResultRow(Record, Base):
    __tablename__ = "processing_results"
    request_id: Mapped[str] = mapped_column(String(256))
    revision_id: Mapped[str] = mapped_column(String(256))
    result_hash: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON)
    applied: Mapped[bool] = mapped_column(Boolean)
    dagster_run_id: Mapped[str] = mapped_column(String(256))
    __table_args__ = (scope_fk("processing_requests", "request_id"), scope_fk("pack_revisions", "revision_id"),
                      UniqueConstraint("tenant_id", "fund_id", "pack_id", "request_id"))


class AuditEventRow(Record, Base):
    __tablename__ = "audit_events"
    actor_id: Mapped[str] = mapped_column(String(256))
    event_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str] = mapped_column(String(256))
    detail: Mapped[dict] = mapped_column(JSON)

    __table_args__ = (pack_fk(),)


APPEND_ONLY_MODELS = (PackRevisionRow, DocumentVersionRow, SourceOccurrenceRow, ExtractionObservationRow,
    FactVersionRow, CheckResultRow, DependencyEdgeRow, CorrectionRow, ArtifactRow,
    ReviewDecisionRow, PublicationRow, AuditEventRow, ProcessingResultRow)


@event.listens_for(Session, "before_flush")
def guard_history(session, flush_context, instances):
    for row in session.deleted:
        if isinstance(row, APPEND_ONLY_MODELS): raise ValueError("historical records are append-only")
    for row in session.dirty:
        if isinstance(row, APPEND_ONLY_MODELS) and session.is_modified(row, include_collections=True):
            raise ValueError("historical records are append-only")
