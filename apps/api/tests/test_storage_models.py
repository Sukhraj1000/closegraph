import pytest
from closegraph.storage.database import make_engine
from closegraph.storage.models import Base, DocumentVersionRow, FactVersionRow
from closegraph.collections.models import CollectionRow, CollectionRevisionRow, CollectionJobRow
from sqlalchemy import Numeric
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable


COLLECTION_TABLES = {"collections", "collection_revisions", "collection_jobs"}


def test_scoped_schema_and_exact_numeric():
    expected = {"packs", "pack_revisions", "document_versions", "source_occurrences", "extraction_observations",
                "fact_versions", "check_results", "dependency_edges", "corrections", "review_decisions",
                "publications", "processing_requests", "audit_events", "artifacts"}
    assert expected <= set(Base.metadata.tables)
    for table in Base.metadata.sorted_tables:
        if table.name not in COLLECTION_TABLES:
            assert {"tenant_id", "fund_id", "pack_id"} <= set(table.primary_key.columns.keys())
        sql = str(CreateTable(table).compile(dialect=postgresql.dialect()))
        assert "CREATE TABLE" in sql
    amount = FactVersionRow.__table__.c.value_decimal.type
    assert isinstance(amount, Numeric) and amount.asdecimal and amount.scale is None
    assert any(set(c.columns.keys()) == {"tenant_id", "fund_id", "pack_id", "idempotency_key"}
               for c in DocumentVersionRow.__table__.constraints)


def test_collections_have_explicit_scope_and_children_reference_exact_parent_revision():
    # A collection has a globally unique ID and immutable fund/tenant owner, rather
    # than inheriting an unrelated reporting-pack ID. Service tests enforce grants.
    parent, revisions, jobs = CollectionRow.__table__, CollectionRevisionRow.__table__, CollectionJobRow.__table__
    assert set(parent.primary_key.columns.keys()) == {"id"}
    assert all(not parent.c[key].nullable for key in ("id", "tenant_id", "fund_id", "version"))
    assert {tuple(index.columns.keys()) for index in parent.indexes} >= {("tenant_id",), ("fund_id",)}
    assert set(revisions.primary_key.columns.keys()) == {"collection_id", "version"}
    revision_parent = list(revisions.foreign_key_constraints)
    assert len(revision_parent) == 1
    assert [(element.parent.name, element.target_fullname) for element in revision_parent[0].elements] == [("collection_id", "collections.id")]
    assert revision_parent[0].ondelete == "RESTRICT"
    job_parent = list(jobs.foreign_key_constraints)
    assert len(job_parent) == 1
    assert {(element.parent.name, element.target_fullname) for element in job_parent[0].elements} == {
        ("collection_id", "collection_revisions.collection_id"), ("version", "collection_revisions.version")}
    assert job_parent[0].ondelete == "RESTRICT"
    assert all(not jobs.c[key].nullable for key in ("collection_id", "version"))


def test_refuse_sqlite_as_production_persistence():
    with pytest.raises(ValueError, match="PostgreSQL"):
        make_engine("sqlite:///:memory:")
