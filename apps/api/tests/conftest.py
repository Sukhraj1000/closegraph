"""Shared real-PostgreSQL test infrastructure with one schema per test."""
import os
from pathlib import Path
from uuid import uuid4
import pytest
from sqlalchemy import text
from alembic import command
from alembic.config import Config
from closegraph.storage.database import make_engine,session_factory

@pytest.fixture
def pg_sessions():
    url=os.environ.get('CLOSEGRAPH_TEST_DATABASE_URL')
    if not url: pytest.skip('Real PostgreSQL requires CLOSEGRAPH_TEST_DATABASE_URL')
    admin=make_engine(url); schema='test_'+uuid4().hex
    with admin.begin() as c:c.execute(text('CREATE SCHEMA '+schema))
    engine=make_engine(url,connect_args={'options':'-csearch_path='+schema})
    config=Config(str(Path(__file__).parents[1]/'alembic.ini'))
    with engine.begin() as c:
        config.attributes['connection']=c;command.upgrade(config,'head')
    try:yield session_factory(engine)
    finally:
        engine.dispose()
        with admin.begin() as c:c.execute(text('DROP SCHEMA '+schema+' CASCADE'))
        admin.dispose()
