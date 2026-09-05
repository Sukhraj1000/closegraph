from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker


def make_engine(url: str, **kwargs):
    if make_url(url).get_backend_name() != "postgresql":
        raise ValueError("CloseGraph domain persistence requires PostgreSQL; SQLite is not equivalent")
    return create_engine(url, pool_pre_ping=True, **kwargs)


def session_factory(engine):
    return sessionmaker(engine, expire_on_commit=False, autoflush=False)
