import os

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    """Parent class for all database tables."""


# Bound to an engine by configure(); use as `with SessionLocal() as session: ...`.
SessionLocal = sessionmaker()


def configure(url: str | None = None) -> Engine:
    """Connect to the database and create any missing tables.

    The URL comes from DATABASE_URL, defaulting to a local SQLite file. Switching to
    PostgreSQL later is just e.g. DATABASE_URL=postgresql+psycopg://user:pw@host/db.
    """
    url = url or os.getenv("DATABASE_URL", "sqlite:///./gateway.db")

    kwargs = {}
    if url.startswith("sqlite"):
        # FastAPI runs sync endpoints in a thread pool, so SQLite must allow
        # connections to be used from threads other than the one that made them.
        kwargs["connect_args"] = {"check_same_thread": False}
        if url in ("sqlite://", "sqlite:///:memory:"):
            # An in-memory database lives inside one connection; share that single
            # connection, otherwise every new connection sees a fresh empty database.
            kwargs["poolclass"] = StaticPool

    engine = create_engine(url, **kwargs)
    SessionLocal.configure(bind=engine)

    # Import the table classes so create_all() knows about them.
    from app import models  # noqa: F401

    Base.metadata.create_all(engine)
    return engine
