"""
schemas.py
==========
Pydantic request/response schemas for all API endpoints.
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


# ─────────────────────────── Auth ────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ─────────────────────────── Worker ──────────────────────────

class WorkerCreate(BaseModel):
    worker_id: str = Field(..., example="WRK001")
    full_name: str = Field(..., example="Rajesh Kumar")
    department: Optional[str] = None
    designation: Optional[str] = None
    site: Optional[str] = None
    shift: Optional[str] = Field(None, example="B")
    phone: Optional[str] = None

class WorkerUpdate(BaseModel):
    full_name: Optional[str] = None
    department: Optional[str] = None
    designation: Optional[str] = None
    site: Optional[str] = None
    shift: Optional[str] = None
    phone: Optional[str] = None
    is_active: Optional[bool] = None

class WorkerOut(BaseModel):
    id: int
    worker_id: str
    full_name: str
    department: Optional[str]
    designation: Optional[str]
    site: Optional[str]
    shift: Optional[str]
    phone: Optional[str]
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ─────────────────────────── Reading ─────────────────────────

class ReadingCreate(BaseModel):
    worker_id: str = Field(..., description="Worker ID string e.g. WRK001")
    badge_id: Optional[str] = None
    delta_E: float = Field(..., ge=0, description="CIE DE2000 color difference")
    delta_E_corr: Optional[float] = None
    R: Optional[float] = None
    G: Optional[float] = None
    B: Optional[float] = None
    L_star: Optional[float] = None
    a_star: Optional[float] = None
    b_star: Optional[float] = None
    dose_ppm_hr: float = Field(..., ge=0, description="Predicted cumulative H2S dose in ppm.hr")
    model_confidence: Optional[str] = Field("medium", example="high")
    temperature_c: Optional[float] = None
    humidity_pct: Optional[float] = None
    shift_date: Optional[str] = Field(None, example="2026-08-31")
    scanned_by: Optional[str] = None
    notes: Optional[str] = ""

class ReadingOut(BaseModel):
    id: int
    worker_id: int
    badge_id: Optional[str]
    delta_E: float
    delta_E_corr: Optional[float]
    dose_ppm_hr: float
    model_confidence: Optional[str]
    temperature_c: Optional[float]
    humidity_pct: Optional[float]
    scan_timestamp: datetime
    shift_date: Optional[str]
    scanned_by: Optional[str]
    notes: Optional[str]
    alert_triggered: bool = False

    model_config = {"from_attributes": True}


# ─────────────────────────── Alert ───────────────────────────

class AlertOut(BaseModel):
    id: int
    worker_id: int
    worker_code: Optional[str] = None   # e.g. "WRK001" (from linked worker)
    worker_name: Optional[str] = None   # worker full name (from linked worker)
    reading_id: Optional[int]
    alert_type: str
    dose_at_alert: float
    threshold: float
    message: Optional[str]
    is_acknowledged: bool
    acknowledged_by: Optional[str]
    acknowledged_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}

class AcknowledgeRequest(BaseModel):
    acknowledged_by: str


# ─────────────────────────── Dashboard ───────────────────────

class WorkerSummary(BaseModel):
    worker_id: str
    full_name: str
    site: Optional[str]
    shift: Optional[str]
    latest_dose_ppm_hr: Optional[float]
    total_readings: int
    active_alerts: int
    status: str   # "safe" | "warning" | "danger"

class DashboardSummary(BaseModel):
    total_workers: int
    active_workers: int
    total_readings_today: int
    workers_in_warning: int
    workers_in_danger: int
    unacknowledged_alerts: int
    workers: List[WorkerSummary]
