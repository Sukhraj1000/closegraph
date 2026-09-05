"""Real PostgreSQL migration checks, including preservation of collection history."""
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import inspect, text

from closegraph.collections.models import CollectionRow, CollectionRevisionRow
from closegraph.storage.models import Base


COLLECTION_TABLES = {"collections", "collection_revisions", "collection_jobs"}


def configuration(connection):
    config = Config(str(Path(__file__).parents[2] / "alembic.ini"))
    config.attributes["connection"] = connection
    return config


def test_current_downgrade_refuses_to_destroy_collection_history(pg_sessions):
    with pg_sessions() as session, session.begin():
        session.add(CollectionRow(id="retained", tenant_id="tenant", fund_id="fund", version=1, state={}))
        session.flush()
        session.add(CollectionRevisionRow(collection_id="retained", version=1, actor_id="preparer",
                                           event_type="created", detail={}, state={}))
    with pg_sessions() as session:
        engine = session.bind
    with engine.begin() as connection:
        tables_before = set(inspect(connection).get_table_names())
        assert set(Base.metadata.tables) <= tables_before
        with pytest.raises(RuntimeError, match="history must be preserved"):
            command.downgrade(configuration(connection), "base")
        assert set(inspect(connection).get_table_names()) == tables_before
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0002_collections"
        assert connection.scalar(text("SELECT count(*) FROM collection_revisions WHERE collection_id='retained'")) == 1
        command.upgrade(configuration(connection), "head")
        assert connection.scalar(text("SELECT count(*) FROM collection_revisions WHERE collection_id='retained'")) == 1


def test_legacy_revision_can_downgrade_and_reupgrade_in_separate_empty_schema(pg_sessions):
    # Exercise the historical reversible migration without stamping over or
    # bypassing the new retention gate on an existing collection database.
    with pg_sessions() as session:
        engine = session.bind
    schema = "legacy_migration_" + uuid4().hex
    expected = set(Base.metadata.tables) - COLLECTION_TABLES
    with engine.begin() as connection:
        connection.execute(text("CREATE SCHEMA " + schema))
        original = connection.scalar(text("SELECT current_schema()"))
        try:
            connection.execute(text("SET LOCAL search_path TO " + schema))
            config = configuration(connection)
            command.upgrade(config, "0001_scoped_reporting")
            assert expected <= set(inspect(connection).get_table_names(schema=schema))
            assert not (COLLECTION_TABLES & set(inspect(connection).get_table_names(schema=schema)))
            command.downgrade(config, "base")
            assert set(inspect(connection).get_table_names(schema=schema)) <= {"alembic_version"}
            assert connection.scalar(text("SELECT count(*) FROM alembic_version")) == 0
            command.upgrade(config, "0001_scoped_reporting")
            assert expected <= set(inspect(connection).get_table_names(schema=schema))
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0001_scoped_reporting"
        finally:
            connection.execute(text("SET LOCAL search_path TO " + original))
            connection.execute(text("DROP SCHEMA " + schema + " CASCADE"))
