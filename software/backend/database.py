"""
database.py
===========
SQLAlchemy database setup. Uses SQLite for development (zero-config).
Switch to PostgreSQL for production by changing DATABASE_URL env variable.
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

# SQLite for dev; override with env var for production (PostgreSQL)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./h2s_dosimeter.db")

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
