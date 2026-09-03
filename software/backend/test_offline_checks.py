"""
test_offline_checks.py
======================
Offline verification that does NOT require the full app to boot.

The sandbox/CI here lacks python-jose, bcrypt, and reportlab, so auth.py (and
therefore main.py / test_api.py) cannot be imported. But SQLAlchemy, Pydantic
and FastAPI ARE available, so we can still verify the two riskiest Phase 1
changes against the REAL models/schemas using an in-memory SQLite database:

  A. Dashboard N+1 refactor — the new grouped/windowed queries return output
     IDENTICAL to the previous per-worker query loop, across diverse data.
  B. Alert worker display — AlertOut now serializes worker_code / worker_name
     from the linked Worker relationship.

Run:  python test_offline_checks.py
"""
import sys
from datetime import datetime, timedelta, timezone, date

from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

import models
import schemas

PASS = 0
FAIL = 0


def check(name, condition, details=""):
    global PASS, FAIL
    if condition:
        print(f"  [PASS] {name}")
        PASS += 1
    else:
        print(f"  [FAIL] {name}  {details}")
        FAIL += 1


THRESHOLD_WARNING = 60.0
THRESHOLD_DANGER = 80.0


def make_session():
    """Fresh in-memory DB with the real ORM schema."""
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def seed(db):
    """Diverse scenarios: no readings, safe, warning, danger, inactive, ties, acked/unacked."""
    today = date.today().isoformat()
    t0 = datetime(2026, 8, 31, 6, 0, 0, tzinfo=timezone.utc)

    workers = [
        models.Worker(worker_id="WRK001", full_name="Has None", site="S1", shift="A", is_active=True),
        models.Worker(worker_id="WRK002", full_name="Safe Low", site="S1", shift="A", is_active=True),
        models.Worker(worker_id="WRK003", full_name="Warning", site="S2", shift="B", is_active=True),
        models.Worker(worker_id="WRK004", full_name="Danger", site="S2", shift="B", is_active=True),
        models.Worker(worker_id="WRK005", full_name="Inactive", site="S3", shift="C", is_active=False),
        models.Worker(worker_id="WRK006", full_name="Exactly60", site="S3", shift="C", is_active=True),
        models.Worker(worker_id="WRK007", full_name="Exactly80", site="S3", shift="C", is_active=True),
    ]
    db.add_all(workers)
    db.commit()

    # (worker_id string, [ (dose, hours_offset) ... ]) — last by timestamp is "latest"
    scenarios = {
        "WRK002": [(5, 0), (25, 1), (42, 2)],          # latest 42 -> safe
        "WRK003": [(10, 0), (70, 2), (65, 1)],          # latest by time = 70 (offset 2) -> warning
        "WRK004": [(30, 0), (55, 1), (90, 2)],          # latest 90 -> danger
        "WRK005": [(100, 0)],                            # inactive: excluded from summary
        "WRK006": [(59, 0), (60, 1)],                    # latest exactly 60 -> warning (boundary)
        "WRK007": [(79, 0), (80, 1)],                    # latest exactly 80 -> danger (boundary)
    }
    wmap = {w.worker_id: w for w in workers}
    for wid, doses in scenarios.items():
        for dose, off in doses:
            db.add(models.Reading(
                worker_id=wmap[wid].id, delta_E=float(dose), dose_ppm_hr=float(dose),
                scan_timestamp=t0 + timedelta(hours=off), shift_date=today,
            ))
    db.commit()

    # Alerts: WRK004 has 2 unacked + 1 acked; WRK003 has 1 unacked.
    w4, w3 = wmap["WRK004"].id, wmap["WRK003"].id
    db.add_all([
        models.Alert(worker_id=w4, alert_type="danger", dose_at_alert=90, threshold=80, is_acknowledged=False),
        models.Alert(worker_id=w4, alert_type="warning", dose_at_alert=70, threshold=60, is_acknowledged=False),
        models.Alert(worker_id=w4, alert_type="warning", dose_at_alert=65, threshold=60, is_acknowledged=True),
        models.Alert(worker_id=w3, alert_type="warning", dose_at_alert=70, threshold=60, is_acknowledged=False),
    ])
    db.commit()
    return today


# ─────────────────────── OLD algorithm (pre-refactor) ───────────────────────
def dashboard_old(db, today):
    workers = db.query(models.Worker).filter(models.Worker.is_active == True).all()
    total_readings_today = db.query(func.count(models.Reading.id)).filter(
        models.Reading.shift_date == today).scalar() or 0
    unacked_alerts = db.query(func.count(models.Alert.id)).filter(
        models.Alert.is_acknowledged == False).scalar() or 0

    rows, warn, danger = [], 0, 0
    for w in workers:
        latest = db.query(models.Reading).filter(
            models.Reading.worker_id == w.id
        ).order_by(models.Reading.scan_timestamp.desc()).first()
        total_rdgs = db.query(func.count(models.Reading.id)).filter(
            models.Reading.worker_id == w.id).scalar() or 0
        active_alerts = db.query(func.count(models.Alert.id)).filter(
            models.Alert.worker_id == w.id, models.Alert.is_acknowledged == False).scalar() or 0
        latest_dose = latest.dose_ppm_hr if latest else None
        if latest_dose is None:
            status = "safe"
        elif latest_dose >= THRESHOLD_DANGER:
            status = "danger"; danger += 1
        elif latest_dose >= THRESHOLD_WARNING:
            status = "warning"; warn += 1
        else:
            status = "safe"
        rows.append((w.worker_id, latest_dose, total_rdgs, active_alerts, status))
    return {"today": total_readings_today, "unacked": unacked_alerts,
            "warn": warn, "danger": danger, "rows": rows}


# ─────────────────────── NEW algorithm (from dashboard.py) ──────────────────
def dashboard_new(db, today):
    workers = db.query(models.Worker).filter(models.Worker.is_active == True).all()
    total_readings_today = db.query(func.count(models.Reading.id)).filter(
        models.Reading.shift_date == today).scalar() or 0
    unacked_alerts = db.query(func.count(models.Alert.id)).filter(
        models.Alert.is_acknowledged == False).scalar() or 0

    reading_counts = dict(
        db.query(models.Reading.worker_id, func.count(models.Reading.id))
        .group_by(models.Reading.worker_id).all())
    alert_counts = dict(
        db.query(models.Alert.worker_id, func.count(models.Alert.id))
        .filter(models.Alert.is_acknowledged == False)
        .group_by(models.Alert.worker_id).all())

    rn = func.row_number().over(
        partition_by=models.Reading.worker_id,
        order_by=models.Reading.scan_timestamp.desc()).label("rn")
    ranked = db.query(
        models.Reading.worker_id.label("wid"),
        models.Reading.dose_ppm_hr.label("dose"), rn).subquery()
    latest_dose_by_worker = {
        row.wid: row.dose
        for row in db.query(ranked.c.wid, ranked.c.dose).filter(ranked.c.rn == 1).all()}

    rows, warn, danger = [], 0, 0
    for w in workers:
        latest_dose = latest_dose_by_worker.get(w.id)
        total_rdgs = reading_counts.get(w.id, 0)
        active_alerts = alert_counts.get(w.id, 0)
        if latest_dose is None:
            status = "safe"
        elif latest_dose >= THRESHOLD_DANGER:
            status = "danger"; danger += 1
        elif latest_dose >= THRESHOLD_WARNING:
            status = "warning"; warn += 1
        else:
            status = "safe"
        rows.append((w.worker_id, latest_dose, total_rdgs, active_alerts, status))
    return {"today": total_readings_today, "unacked": unacked_alerts,
            "warn": warn, "danger": danger, "rows": rows}



def check_cors():
    """Verify the default CORS origins include both browser clients."""
    import config

    expected = {
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    }

    actual = {
        origin.strip()
        for origin in config._DEFAULT_CORS_ORIGINS.split(",")
        if origin.strip()
    }

    check(
        "CORS defaults include dashboard + mobile origins",
        expected.issubset(actual),
        f"missing={sorted(expected - actual)}",
    )

def main():
    print("\n" + "=" * 60)
    print("  OFFLINE CHECKS (no jose/bcrypt/reportlab required)")
    print("=" * 60)

    # ── A. Dashboard N+1 refactor equivalence ──────────────
    print("\n[A] Dashboard summary: new (grouped/windowed) == old (per-worker loop)")
    db = make_session()
    today = seed(db)
    old = dashboard_old(db, today)
    new = dashboard_new(db, today)

    check("total_readings_today matches", old["today"] == new["today"], f"{old['today']} vs {new['today']}")
    check("unacknowledged_alerts matches", old["unacked"] == new["unacked"], f"{old['unacked']} vs {new['unacked']}")
    check("workers_in_warning matches", old["warn"] == new["warn"], f"{old['warn']} vs {new['warn']}")
    check("workers_in_danger matches", old["danger"] == new["danger"], f"{old['danger']} vs {new['danger']}")
    check("per-worker rows identical (dose, counts, status)", old["rows"] == new["rows"],
          f"\n    old={old['rows']}\n    new={new['rows']}")

    # Spot-check the boundary + expected statuses in the NEW result
    by_id = {r[0]: r for r in new["rows"]}
    check("WRK001 (no readings) -> safe, dose None", by_id["WRK001"][1] is None and by_id["WRK001"][4] == "safe")
    check("WRK003 latest-by-time dose=70 -> warning", by_id["WRK003"][1] == 70 and by_id["WRK003"][4] == "warning")
    check("WRK004 dose=90 -> danger, 2 active alerts", by_id["WRK004"][4] == "danger" and by_id["WRK004"][3] == 2)
    check("WRK006 dose==60 boundary -> warning", by_id["WRK006"][4] == "warning")
    check("WRK007 dose==80 boundary -> danger", by_id["WRK007"][4] == "danger")
    check("Inactive WRK005 excluded from summary", "WRK005" not in by_id)

    # ── B. Alert worker_code / worker_name serialization ───
    print("\n[B] AlertOut serializes worker_code + worker_name from the relationship")
    alert = db.query(models.Alert).join(models.Worker).filter(
        models.Worker.worker_id == "WRK004").first()
    check("Alert.worker_code property == 'WRK004'", alert.worker_code == "WRK004", str(alert.worker_code))
    check("Alert.worker_name property == 'Danger'", alert.worker_name == "Danger", str(alert.worker_name))
    dumped = schemas.AlertOut.model_validate(alert).model_dump()
    check("AlertOut includes worker_code", dumped.get("worker_code") == "WRK004", str(dumped.get("worker_code")))
    check("AlertOut includes worker_name", dumped.get("worker_name") == "Danger", str(dumped.get("worker_name")))
    check("AlertOut still includes integer worker_id (compat)", isinstance(dumped.get("worker_id"), int))

    db.close()

    # ── C. CORS admission ──────────────────────────────────
    check_cors()

    total = PASS + FAIL
    print("\n" + "=" * 60)
    print(f"  OFFLINE RESULTS: {PASS}/{total} passed, {FAIL} failed")
    print("=" * 60 + "\n")
    return FAIL == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
