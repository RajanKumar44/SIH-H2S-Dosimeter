"""routes/readings.py — Exposure reading submission and retrieval."""
from datetime import datetime, date, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from auth import get_current_officer
import models, schemas
from routes.alerts import check_and_create_alert

# All reading endpoints require an authenticated officer. The future mobile
# ingestion client (Phase 4) will authenticate as an officer/service account.
router = APIRouter(
    prefix="/readings",
    tags=["Readings"],
    dependencies=[Depends(get_current_officer)],
)

# DGMS thresholds (ppm.hr cumulative)
THRESHOLD_WARNING = 60.0   # 75% of 8-hr TWA limit (10ppm x 8hr = 80 ppm.hr)
THRESHOLD_DANGER  = 80.0   # DGMS 8-hr TWA limit reached
THRESHOLD_CRITICAL = 100.0  # 25% over limit — immediate action


@router.post("/", response_model=schemas.ReadingOut, status_code=201)
def submit_reading(payload: schemas.ReadingCreate, db: Session = Depends(get_db)):
    """
    Submit a new wristband scan reading from the mobile app.
    Automatically checks DGMS thresholds and creates alerts if needed.
    """
    # Resolve worker string ID -> DB row
    worker = db.query(models.Worker).filter(
        models.Worker.worker_id == payload.worker_id,
        models.Worker.is_active == True,
    ).first()
    if not worker:
        raise HTTPException(status_code=404, detail=f"Active worker '{payload.worker_id}' not found.")

    # Build reading
    reading_data = payload.model_dump(exclude={"worker_id"})
    reading = models.Reading(
        worker_id=worker.id,
        shift_date=reading_data.pop("shift_date", None) or date.today().isoformat(),
        **reading_data,
    )
    db.add(reading)
    db.commit()
    db.refresh(reading)

    # Auto-alert if thresholds breached
    alert_triggered = False
    dose = reading.dose_ppm_hr
    if dose >= THRESHOLD_CRITICAL:
        check_and_create_alert(db, worker, reading, "critical", THRESHOLD_CRITICAL,
            f"CRITICAL: {worker.full_name} has reached {dose:.1f} ppm.hr — IMMEDIATE EVACUATION")
        alert_triggered = True
    elif dose >= THRESHOLD_DANGER:
        check_and_create_alert(db, worker, reading, "danger", THRESHOLD_DANGER,
            f"DANGER: {worker.full_name} has reached DGMS 8-hr limit ({dose:.1f} ppm.hr)")
        alert_triggered = True
    elif dose >= THRESHOLD_WARNING:
        check_and_create_alert(db, worker, reading, "warning", THRESHOLD_WARNING,
            f"WARNING: {worker.full_name} approaching DGMS limit ({dose:.1f} ppm.hr)")
        alert_triggered = True

    result = schemas.ReadingOut.model_validate(reading)
    result.alert_triggered = alert_triggered
    return result


@router.get("/worker/{worker_id}", response_model=List[schemas.ReadingOut])
def get_worker_readings(
    worker_id: str,
    shift_date: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """Get all readings for a specific worker, optionally filtered by date."""
    worker = db.query(models.Worker).filter(models.Worker.worker_id == worker_id).first()
    if not worker:
        raise HTTPException(status_code=404, detail=f"Worker '{worker_id}' not found.")

    q = db.query(models.Reading).filter(models.Reading.worker_id == worker.id)
    if shift_date:
        q = q.filter(models.Reading.shift_date == shift_date)

    readings = q.order_by(models.Reading.scan_timestamp.desc()).limit(limit).all()
    return readings


@router.get("/today", response_model=List[schemas.ReadingOut])
def get_todays_readings(db: Session = Depends(get_db)):
    """Get all readings submitted today."""
    today = date.today().isoformat()
    return db.query(models.Reading).filter(
        models.Reading.shift_date == today
    ).order_by(models.Reading.scan_timestamp.desc()).all()


@router.get("/{reading_id}", response_model=schemas.ReadingOut)
def get_reading(reading_id: int, db: Session = Depends(get_db)):
    """Get a specific reading by ID."""
    reading = db.query(models.Reading).filter(models.Reading.id == reading_id).first()
    if not reading:
        raise HTTPException(status_code=404, detail="Reading not found.")
    return reading
