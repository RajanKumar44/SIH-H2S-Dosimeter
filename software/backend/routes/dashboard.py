"""routes/dashboard.py — Aggregated dashboard statistics endpoint."""
from datetime import date
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from database import get_db
from auth import get_current_officer
import models, schemas

router = APIRouter(
    prefix="/dashboard",
    tags=["Dashboard"],
    dependencies=[Depends(get_current_officer)],
)

THRESHOLD_WARNING = 60.0
THRESHOLD_DANGER  = 80.0


@router.get("/summary", response_model=schemas.DashboardSummary)
def get_dashboard_summary(db: Session = Depends(get_db)):
    """
    Full dashboard summary: worker statuses, alert counts, today's readings.
    Used by the React admin dashboard to populate all widgets.

    Aggregates are computed with a fixed number of grouped queries (no per-worker
    query loop): active workers, today's reading count, total unacked alerts,
    per-worker reading counts, per-worker unacked alert counts, and each worker's
    latest dose via a window function.
    """
    today = date.today().isoformat()
    workers = db.query(models.Worker).filter(models.Worker.is_active == True).all()

    total_readings_today = db.query(func.count(models.Reading.id)).filter(
        models.Reading.shift_date == today
    ).scalar() or 0

    unacked_alerts = db.query(func.count(models.Alert.id)).filter(
        models.Alert.is_acknowledged == False
    ).scalar() or 0

    # Per-worker reading counts: {worker_pk: count}
    reading_counts = dict(
        db.query(models.Reading.worker_id, func.count(models.Reading.id))
        .group_by(models.Reading.worker_id)
        .all()
    )

    # Per-worker unacknowledged alert counts: {worker_pk: count}
    alert_counts = dict(
        db.query(models.Alert.worker_id, func.count(models.Alert.id))
        .filter(models.Alert.is_acknowledged == False)
        .group_by(models.Alert.worker_id)
        .all()
    )

    # Latest dose per worker via row_number() window (rn==1 is the newest scan).
    # Ordering matches the previous per-worker `.order_by(scan_timestamp.desc()).first()`.
    rn = func.row_number().over(
        partition_by=models.Reading.worker_id,
        order_by=models.Reading.scan_timestamp.desc(),
    ).label("rn")
    ranked = db.query(
        models.Reading.worker_id.label("wid"),
        models.Reading.dose_ppm_hr.label("dose"),
        rn,
    ).subquery()
    latest_dose_by_worker = {
        row.wid: row.dose
        for row in db.query(ranked.c.wid, ranked.c.dose).filter(ranked.c.rn == 1).all()
    }

    worker_summaries = []
    warnings_count = 0
    danger_count = 0

    for w in workers:
        latest_dose = latest_dose_by_worker.get(w.id)
        total_rdgs = reading_counts.get(w.id, 0)
        active_alerts = alert_counts.get(w.id, 0)

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
