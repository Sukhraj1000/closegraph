import pytest
from closegraph.storage.database import make_engine
from closegraph.storage.models import Base, DocumentVersionRow, FactVersionRow
from sqlalchemy import Numeric
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable


def test_scoped_schema_and_exact_numeric():
    expected = {"packs", "pack_revisions", "document_versions", "source_occurrences", "extraction_observations",
                "fact_versions", "check_results", "dependency_edges", "corrections", "review_decisions",
                "publications", "processing_requests", "audit_events", "artifacts"}
    assert expected <= set(Base.metadata.tables)
    for table in Base.metadata.sorted_tables:
        assert {"tenant_id","fund_id","pack_id"} <= set(table.primary_key.columns.keys())
        sql = str(CreateTable(table).compile(dialect=postgresql.dialect()))
        assert "CREATE TABLE" in sql
    amount = FactVersionRow.__table__.c.value_decimal.type
    assert isinstance(amount, Numeric) and amount.asdecimal and amount.scale is None
    assert any(set(c.columns.keys()) == {"tenant_id","fund_id","pack_id","idempotency_key"}
               for c in DocumentVersionRow.__table__.constraints)


def test_refuse_sqlite_as_production_persistence():
    with pytest.raises(ValueError, match="PostgreSQL"): make_engine("sqlite:///:memory:")
