"""SQLAlchemy engine, sessions, declarative base, and request dependency."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from rop.config import get_settings

settings = get_settings()

# Creating an engine does not open a database connection. Connections are
# acquired only when a session first executes database work.
engine: Engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for future ORM models; no domain models are defined yet."""


def get_db() -> Generator[Session, None, None]:
    """Yield a request-scoped session and close it after use."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
