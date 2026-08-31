"""routes/dashboard.py — Aggregated dashboard statistics endpoint."""
from datetime import date
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
import models, schemas

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

THRESHOLD_WARNING = 60.0
THRESHOLD_DANGER  = 80.0


@router.get("/summary", response_model=schemas.DashboardSummary)
def get_dashboard_summary(db: Session = Depends(get_db)):
    """
    Full dashboard summary: worker statuses, alert counts, today's readings.
    Used by the React admin dashboard to populate all widgets.
    """
    today = date.today().isoformat()
    workers = db.query(models.Worker).filter(models.Worker.is_active == True).all()

    total_readings_today = db.query(func.count(models.Reading.id)).filter(
        models.Reading.shift_date == today
    ).scalar() or 0

    unacked_alerts = db.query(func.count(models.Alert.id)).filter(
        models.Alert.is_acknowledged == False
    ).scalar() or 0

    worker_summaries = []
    warnings_count = 0
    danger_count = 0

    for w in workers:
        # Latest reading for this worker
        latest = db.query(models.Reading).filter(
            models.Reading.worker_id == w.id
        ).order_by(models.Reading.scan_timestamp.desc()).first()

        # Reading count
        total_rdgs = db.query(func.count(models.Reading.id)).filter(
            models.Reading.worker_id == w.id
        ).scalar() or 0

        # Active unacknowledged alerts
        active_alerts = db.query(func.count(models.Alert.id)).filter(
            models.Alert.worker_id == w.id,
            models.Alert.is_acknowledged == False,
        ).scalar() or 0

        latest_dose = latest.dose_ppm_hr if latest else None

        if latest_dose is None:
            status = "safe"
        elif latest_dose >= THRESHOLD_DANGER:
            status = "danger"
            danger_count += 1
        elif latest_dose >= THRESHOLD_WARNING:
            status = "warning"
            warnings_count += 1
        else:
            status = "safe"

        worker_summaries.append(schemas.WorkerSummary(
            worker_id=w.worker_id,
            full_name=w.full_name,
            site=w.site,
            shift=w.shift,
            latest_dose_ppm_hr=latest_dose,
            total_readings=total_rdgs,
            active_alerts=active_alerts,
            status=status,
        ))

    return schemas.DashboardSummary(
        total_workers=len(workers),
        active_workers=len(workers),
        total_readings_today=total_readings_today,
        workers_in_warning=warnings_count,
        workers_in_danger=danger_count,
        unacknowledged_alerts=unacked_alerts,
        workers=worker_summaries,
    )
