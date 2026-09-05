import os
from alembic import context
from sqlalchemy import engine_from_config, pool
from closegraph.storage.models import Base
from closegraph.collections import models as collection_models

config = context.config
if os.environ.get("CLOSEGRAPH_DATABASE_URL"):
    config.set_main_option("sqlalchemy.url", os.environ["CLOSEGRAPH_DATABASE_URL"].replace("%", "%%"))
target_metadata = Base.metadata

def run_migrations_offline():
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata,
                      literal_binds=True, dialect_opts={"paramstyle":"named"})
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    provided = config.attributes.get("connection")
    if provided is not None:
        context.configure(connection=provided, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = engine_from_config(config.get_section(config.config_ini_section), prefix="sqlalchemy.", poolclass=pool.NullPool)
    if engine.dialect.name != "postgresql":
        raise RuntimeError("Reporting persistence requires PostgreSQL")
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
