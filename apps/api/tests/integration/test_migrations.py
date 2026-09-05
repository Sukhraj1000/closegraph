"""Actual Alembic downgrade/re-upgrade against an isolated PostgreSQL schema."""
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from closegraph.storage.models import Base


def test_actual_postgresql_downgrade_then_upgrade_restores_contract(pg_sessions):
    with pg_sessions() as session:
        engine=session.bind
    config=Config(str(Path(__file__).parents[2]/'alembic.ini'))
    with engine.begin() as connection:
        config.attributes['connection']=connection
        assert set(Base.metadata.tables).issubset(set(inspect(connection).get_table_names()))
        command.downgrade(config,'base')
        remaining=set(inspect(connection).get_table_names())
        assert remaining <= {'alembic_version'}
        assert connection.scalar(text('SELECT count(*) FROM alembic_version'))==0
        command.upgrade(config,'head')
        assert set(Base.metadata.tables).issubset(set(inspect(connection).get_table_names()))
        assert connection.scalar(text('SELECT count(*) FROM alembic_version'))==1
