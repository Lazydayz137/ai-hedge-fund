"""Database session management with connection pooling."""

from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool, NullPool

from app.backend.database.config import db_settings

# Engine and SessionLocal will be created lazily
_engine = None
_SessionLocal = None


def get_engine():
    """Get or create database engine."""
    global _engine
    if _engine is None:
        _engine = create_engine(
            db_settings.database_url,
            poolclass=QueuePool,
            pool_size=db_settings.pool_size,
            max_overflow=db_settings.max_overflow,
            pool_timeout=db_settings.pool_timeout,
            pool_recycle=db_settings.pool_recycle,
            pool_pre_ping=db_settings.pool_pre_ping,
            echo=db_settings.echo_sql,
        )
    return _engine


def get_session_local():
    """Get or create session factory."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=get_engine(),
        )
    return _SessionLocal


# For backwards compatibility
engine = None  # Will be created on first use
SessionLocal = None  # Will be created on first use


def get_db() -> Generator[Session, None, None]:
    """
    Dependency function to get database session.

    Usage in FastAPI:
        @app.get("/endpoint")
        def endpoint(db: Session = Depends(get_db)):
            ...

    Yields:
        Session: SQLAlchemy database session
    """
    session_factory = get_session_local()
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


def get_db_context() -> Session:
    """
    Get database session for use in context manager.

    Usage:
        with get_db_context() as db:
            db.query(Model).all()

    Returns:
        Session: SQLAlchemy database session
    """
    session_factory = get_session_local()
    return session_factory()
