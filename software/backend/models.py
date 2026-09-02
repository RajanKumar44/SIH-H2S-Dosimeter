"""
models.py
=========
SQLAlchemy ORM models for the H2S Dosimeter system.

Tables:
  safety_officers  - Admin/safety officer accounts (login)
  workers          - Oil & gas / industrial workers being monitored
  readings         - Each wristband scan result (dose measurement)
  alerts           - Threshold breach alerts
"""
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import Column, Integer, Float, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from database import Base


class SafetyOfficer(Base):
    """Admin users who log in to the dashboard."""
    __tablename__ = "safety_officers"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    hashed_password = Column(String(200), nullable=False)
    full_name = Column(String(100))
    role = Column(String(20), default="officer")   # "admin" or "officer"
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Worker(Base):
    """Industrial worker being monitored."""
    __tablename__ = "workers"

    id = Column(Integer, primary_key=True, index=True)
    worker_id = Column(String(20), unique=True, index=True, nullable=False)  # e.g. "WRK001"
    full_name = Column(String(100), nullable=False)
    department = Column(String(100))
    designation = Column(String(100))
    site = Column(String(100))               # e.g. "Refinery Unit-3"
    shift = Column(String(20))               # "A", "B", "C", "General"
    phone = Column(String(15))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    readings = relationship("Reading", back_populates="worker", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="worker", cascade="all, delete-orphan")


class Reading(Base):
    """A single wristband scan / exposure measurement."""
    __tablename__ = "readings"

    id = Column(Integer, primary_key=True, index=True)
    worker_id = Column(Integer, ForeignKey("workers.id"), nullable=False)
    badge_id = Column(String(20), index=True)           # Physical badge serial number

    # Color science measurements
    delta_E = Column(Float, nullable=False)              # CIE DE2000 color difference
    delta_E_corr = Column(Float)                         # Lighting-corrected deltaE
    R = Column(Float)
    G = Column(Float)
    B = Column(Float)
    L_star = Column(Float)                               # CIE L*
    a_star = Column(Float)                               # CIE a*
    b_star = Column(Float)                               # CIE b*

    # ML model output
    dose_ppm_hr = Column(Float, nullable=False)          # Predicted cumulative dose
    model_confidence = Column(String(10))                # "high", "medium", "low"

    # Environmental context
    temperature_c = Column(Float)
    humidity_pct = Column(Float)

    # Metadata
    scan_timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    shift_date = Column(String(10))                      # "YYYY-MM-DD"
    scanned_by = Column(String(50))                      # Officer username or "worker"
    notes = Column(Text, default="")

    worker = relationship("Worker", back_populates="readings")
    alert = relationship("Alert", back_populates="reading", uselist=False)


class Alert(Base):
    """Threshold breach alert for a worker."""
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    worker_id = Column(Integer, ForeignKey("workers.id"), nullable=False)
    reading_id = Column(Integer, ForeignKey("readings.id"), nullable=True)

    alert_type = Column(String(20), nullable=False)   # "warning" | "danger" | "critical"
    dose_at_alert = Column(Float, nullable=False)      # ppm.hr when alert triggered
    threshold = Column(Float, nullable=False)           # The limit that was crossed
    message = Column(Text)
    is_acknowledged = Column(Boolean, default=False)
    acknowledged_by = Column(String(50))
    acknowledged_at = Column(DateTime)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    worker = relationship("Worker", back_populates="alerts")
    reading = relationship("Reading", back_populates="alert")

    @property
    def worker_code(self) -> Optional[str]:
        """Human-facing worker ID (e.g. 'WRK001') from the linked worker."""
        return self.worker.worker_id if self.worker else None

    @property
    def worker_name(self) -> Optional[str]:
        """Full name from the linked worker, for display in alert lists."""
        return self.worker.full_name if self.worker else None
