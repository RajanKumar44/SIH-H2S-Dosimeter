"""
database.py
===========
SQLAlchemy database setup. Uses SQLite for development (zero-config).
Switch to PostgreSQL for production by changing DATABASE_URL env variable.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from config import DATABASE_URL

# SQLite needs check_same_thread=False for FastAPI's async requests
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency: yields a DB session and closes it after use."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables. Called at app startup."""
    from models import Worker, Reading, Alert, SafetyOfficer  # noqa: F401
    Base.metadata.create_all(bind=engine)
