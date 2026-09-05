"""Collection heads, immutable revisions and durable Dagster request records."""
from sqlalchemy import JSON, DateTime, ForeignKeyConstraint, Integer, String, Text, event
from sqlalchemy.orm import Mapped, Session, mapped_column
from closegraph.storage.models import Base, utcnow


class CollectionRow(Base):
    __tablename__ = 'collections'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    fund_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)


class CollectionRevisionRow(Base):
    __tablename__ = 'collection_revisions'
    collection_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(256))
    event_type: Mapped[str] = mapped_column(String(64))
    detail: Mapped[dict] = mapped_column(JSON)
    state: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (ForeignKeyConstraint(['collection_id'], ['collections.id'], ondelete='RESTRICT'),)


class CollectionJobRow(Base):
    __tablename__ = 'collection_jobs'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    collection_id: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default='PENDING')
    snapshot: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    dagster_run_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (ForeignKeyConstraint(['collection_id','version'], ['collection_revisions.collection_id','collection_revisions.version'], ondelete='RESTRICT'),)


@event.listens_for(Session, 'before_flush')
def immutable_collection_history(session, flush_context, instances):
    for row in session.deleted:
        if isinstance(row, CollectionRevisionRow):
            raise ValueError('Collection history is append-only')
    for row in session.dirty:
        if isinstance(row, CollectionRevisionRow) and session.is_modified(row, include_collections=True):
            raise ValueError('Collection history is append-only')
