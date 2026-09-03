"""routes/readings.py — Exposure reading submission and retrieval."""
import logging
from datetime import datetime, date, timezone
from typing import List, Optional, Tuple
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from database import get_db
from auth import get_current_officer
import models, schemas
from routes.alerts import check_and_create_alert

log = logging.getLogger(__name__)

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

# Accepted upload MIME types for POST /readings/scan. Some mobile browsers omit
# or generalise the type, so octet-stream is tolerated and the real check is
# whether OpenCV can actually decode the bytes.
ALLOWED_UPLOAD_TYPES = {
    "image/jpeg", "image/jpg", "image/pjpeg", "image/png",
    "application/octet-stream",
}


# ── Shared helpers (used by BOTH POST /readings/ and POST /readings/scan) ────
#
# Threshold evaluation lives here once. Any new ingestion path must call
# `evaluate_thresholds` rather than re-deriving the bands, so the backend stays
# the single source of truth for alert severity.

def _resolve_active_worker(db: Session, worker_code: str) -> models.Worker:
    """Look up an active worker by their code (e.g. WRK001), or 404."""
    worker = db.query(models.Worker).filter(
        models.Worker.worker_id == worker_code,
        models.Worker.is_active == True,
    ).first()
    if not worker:
        raise HTTPException(
            status_code=404,
            detail=f"Active worker '{worker_code}' not found.",
        )
    return worker


def evaluate_thresholds(
    db: Session,
    worker: models.Worker,
    reading: models.Reading,
) -> Tuple[bool, Optional[models.Alert]]:
    """
    Apply the DGMS thresholds to a stored reading and create/refresh its alert.

    The single place where dose is compared against the warning/danger/critical
    bands. Returns ``(alert_triggered, alert_or_None)`` so callers can report
    the backend's own verdict instead of recomputing it.
    """
    dose = reading.dose_ppm_hr

    if dose >= THRESHOLD_CRITICAL:
        alert = check_and_create_alert(
            db, worker, reading, "critical", THRESHOLD_CRITICAL,
            f"CRITICAL: {worker.full_name} has reached {dose:.1f} ppm.hr — IMMEDIATE EVACUATION")
        return True, alert

    if dose >= THRESHOLD_DANGER:
        alert = check_and_create_alert(
            db, worker, reading, "danger", THRESHOLD_DANGER,
            f"DANGER: {worker.full_name} has reached DGMS 8-hr limit ({dose:.1f} ppm.hr)")
        return True, alert

    if dose >= THRESHOLD_WARNING:
        alert = check_and_create_alert(
            db, worker, reading, "warning", THRESHOLD_WARNING,
            f"WARNING: {worker.full_name} approaching DGMS limit ({dose:.1f} ppm.hr)")
        return True, alert

    return False, None


@router.post("/", response_model=schemas.ReadingOut, status_code=201)
def submit_reading(payload: schemas.ReadingCreate, db: Session = Depends(get_db)):
    """
    Submit a new wristband scan reading from the mobile app.
    Automatically checks DGMS thresholds and creates alerts if needed.
    """
    # Resolve worker string ID -> DB row
    worker = _resolve_active_worker(db, payload.worker_id)

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
    alert_triggered, _ = evaluate_thresholds(db, worker, reading)

    result = schemas.ReadingOut.model_validate(reading)
    result.alert_triggered = alert_triggered
    return result


@router.post("/scan", response_model=schemas.ScanReadingOut, status_code=201)
async def scan_reading(
    worker_id: str = Form(..., description="Worker code, e.g. WRK001"),
    image: UploadFile = File(..., description="Strip photo (JPEG or PNG)"),
    badge_id: Optional[str] = Form(None),
    temperature_c: Optional[float] = Form(None),
    humidity_pct: Optional[float] = Form(None),
    shift_date: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    officer: models.SafetyOfficer = Depends(get_current_officer),
):
    """
    Analyse an uploaded strip photo and store the resulting reading.

    Pipeline (every stage reuses existing code):

        upload -> decode -> image_processor.process_strip_array()
               -> model_trainer.predict()
               -> models.Reading  -> evaluate_thresholds()  [same as POST /readings/]

    The dose is computed by the ML model from the photo; it is never derived
    from the image colour by this route directly, and the alert severity comes
    from :func:`evaluate_thresholds`, shared with ``POST /readings/``.

    The uploaded image is analysed in memory and discarded — there is no image
    storage mechanism in this project.

    Returns the stored reading plus the ML and alert details the dashboard needs.
    """
    # Import lazily so OpenCV / scikit-learn stay out of the backend's import
    # graph for every other route and for the offline test suite.
    from ml_inference import (
        InvalidImage,
        MLUnavailable,
        analyze_strip_image,
        model_status,
    )

    # 1. Worker must exist and be active — before doing expensive image work.
    worker = _resolve_active_worker(db, worker_id)

    # 2. Basic upload validation.
    content_type = (image.content_type or "").lower().split(";")[0].strip()
    if content_type and content_type not in ALLOWED_UPLOAD_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(f"Unsupported image type '{content_type}'. "
                    f"Upload a JPEG or PNG."),
        )

    try:
        image_bytes = await image.read()
    except Exception as e:                                   # noqa: BLE001
        raise HTTPException(status_code=400,
                            detail=f"Could not read the uploaded file: {e}") from e
    finally:
        await image.close()

    if not image_bytes:
        raise HTTPException(status_code=400, detail="Uploaded image is empty.")

    # 3. Fail fast with a clear message if the pipeline cannot run at all.
    st = model_status()
    if not st["available"]:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=st.get("hint", "ML pipeline unavailable."),
        )

    # 4. Colour + ML analysis.
    try:
        analysis = analyze_strip_image(image_bytes)
    except InvalidImage as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except MLUnavailable as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=str(e)) from e
    except Exception as e:                                   # noqa: BLE001
        # Never leak a stack trace or take the worker process down.
        log.exception("Unexpected failure analysing a scan upload")
        raise HTTPException(status_code=500,
                            detail=f"Image analysis failed: {e}") from e

    # 5. Persist using the same ORM model as POST /readings/.
    reading = models.Reading(
        worker_id=worker.id,
        badge_id=(badge_id or "").strip() or None,
        delta_E=analysis["delta_E"],
        delta_E_corr=analysis["delta_E_corr"],
        R=analysis["R"], G=analysis["G"], B=analysis["B"],
        L_star=analysis["L_star"], a_star=analysis["a_star"], b_star=analysis["b_star"],
        dose_ppm_hr=analysis["dose_ppm_hr"],
        model_confidence=analysis["model_confidence"],
        temperature_c=temperature_c,
        humidity_pct=humidity_pct,
        shift_date=(shift_date or "").strip() or date.today().isoformat(),
        scanned_by=officer.username,
        notes=(notes or "").strip() or "Camera scan",
    )
    db.add(reading)
    db.commit()
    db.refresh(reading)

    # 6. Threshold evaluation — the SAME shared function POST /readings/ uses.
    alert_triggered, alert = evaluate_thresholds(db, worker, reading)

    return schemas.ScanReadingOut(
        reading=schemas.ReadingOut.model_validate(reading),
        worker_code=worker.worker_id,
        worker_name=worker.full_name,
        delta_E=analysis["delta_E"],
        delta_E_corr=analysis["delta_E_corr"],
        dose_ppm_hr=analysis["dose_ppm_hr"],
        model_confidence=analysis["model_confidence"],
        model_name=analysis["model_name"],
        image_confidence=analysis["image_confidence"],
        roi_detected=analysis["roi_detected"],
        roi_method=analysis["roi_method"],
        roi_confidence=analysis["roi_confidence"],
        lighting_corrected=analysis["lighting_corrected"],
        alert_triggered=alert_triggered,
        alert=schemas.AlertOut.model_validate(alert) if alert else None,
        exposure_status=(alert.alert_type if alert else "safe"),
        scan_timestamp=reading.scan_timestamp,
    )



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
