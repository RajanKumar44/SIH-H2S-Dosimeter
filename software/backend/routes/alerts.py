"""routes/alerts.py — Alert generation, listing, and acknowledgement."""
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from database import get_db
from auth import get_current_officer
import models, schemas

router = APIRouter(
    prefix="/alerts",
    tags=["Alerts"],
    dependencies=[Depends(get_current_officer)],
)


# ── Internal helper (called by readings.py) ─────────────────

def check_and_create_alert(
    db: Session,
    worker: models.Worker,
    reading: models.Reading,
    alert_type: str,
    threshold: float,
    message: str,
) -> models.Alert:
    """
    Create an alert for this worker. Avoids duplicate alerts for the same
    type within the same shift_date.
    """
    existing = db.query(models.Alert).filter(
        models.Alert.worker_id == worker.id,
        models.Alert.alert_type == alert_type,
        models.Alert.is_acknowledged == False,
    ).first()

    if existing:
        # Update dose on existing unacknowledged alert instead of creating duplicate
        existing.dose_at_alert = reading.dose_ppm_hr
        existing.reading_id = reading.id
        db.commit()
        return existing

    alert = models.Alert(
        worker_id=worker.id,
        reading_id=reading.id,
        alert_type=alert_type,
        dose_at_alert=reading.dose_ppm_hr,
        threshold=threshold,
        message=message,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


# ── API Endpoints ───────────────────────────────────────────

@router.get("/", response_model=List[schemas.AlertOut])
def list_alerts(
    unacknowledged_only: bool = False,
    alert_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """List all alerts. Filter by type or acknowledgement status."""
    q = db.query(models.Alert).options(joinedload(models.Alert.worker))
    if unacknowledged_only:
        q = q.filter(models.Alert.is_acknowledged == False)
    if alert_type:
        q = q.filter(models.Alert.alert_type == alert_type)
    return q.order_by(models.Alert.created_at.desc()).all()


@router.get("/worker/{worker_id}", response_model=List[schemas.AlertOut])
def get_worker_alerts(worker_id: str, db: Session = Depends(get_db)):
    """Get all alerts for a specific worker."""
    worker = db.query(models.Worker).filter(models.Worker.worker_id == worker_id).first()
    if not worker:
        raise HTTPException(status_code=404, detail=f"Worker '{worker_id}' not found.")
    return db.query(models.Alert).options(
        joinedload(models.Alert.worker)
    ).filter(
        models.Alert.worker_id == worker.id
    ).order_by(models.Alert.created_at.desc()).all()


@router.post("/{alert_id}/acknowledge", response_model=schemas.AlertOut)
def acknowledge_alert(
    alert_id: int,
    payload: schemas.AcknowledgeRequest,
    db: Session = Depends(get_db),
    officer: models.SafetyOfficer = Depends(get_current_officer),
):
    """Mark an alert as acknowledged by a safety officer."""
    alert = db.query(models.Alert).filter(models.Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found.")
    alert.is_acknowledged = True
    alert.acknowledged_by = payload.acknowledged_by or officer.username
    alert.acknowledged_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(alert)
    return alert


@router.get("/summary/counts")
def alert_counts(db: Session = Depends(get_db)):
    """Quick count of alerts by type and acknowledgement status."""
    from sqlalchemy import func
    rows = db.query(
        models.Alert.alert_type,
        models.Alert.is_acknowledged,
        func.count(models.Alert.id).label("count"),
    ).group_by(models.Alert.alert_type, models.Alert.is_acknowledged).all()

    summary = {"warning": {"total": 0, "unacked": 0},
               "danger":  {"total": 0, "unacked": 0},
               "critical":{"total": 0, "unacked": 0}}
    for row in rows:
        atype = row.alert_type
        if atype in summary:
            summary[atype]["total"] += row.count
            if not row.is_acknowledged:
                summary[atype]["unacked"] += row.count
    return summary
