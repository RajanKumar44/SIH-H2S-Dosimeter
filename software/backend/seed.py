"""
seed.py
=======
Seeds the database with realistic demo data for testing the API.

Creates:
  - 1 admin + 1 safety officer
  - 8 workers across 3 sites and 3 shifts
  - 40+ readings with realistic dose progression
  - Several alerts (warning, danger, critical)

Usage:
  python seed.py

WARNING: This wipes and re-seeds the database. Only use for development.
"""
import sys
import os
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from datetime import datetime, timedelta, timezone, date
from database import engine, SessionLocal, init_db
import models
from auth import hash_password

# DGMS limits
THRESHOLD_WARNING = 60.0
THRESHOLD_DANGER  = 80.0
THRESHOLD_CRITICAL = 100.0


def seed():
    print("=" * 55)
    print("  H2S Dosimeter DB Seeder")
    print("=" * 55)

    # Initialize tables
    init_db()
    db = SessionLocal()

    # Clear existing data
    db.query(models.Alert).delete()
    db.query(models.Reading).delete()
    db.query(models.Worker).delete()
    db.query(models.SafetyOfficer).delete()
    db.commit()
    print("[1/4] Cleared existing data")

    # ── Officers ─────────────────────────────────────────
    officers = [
        models.SafetyOfficer(username="admin",    hashed_password=hash_password("admin123"),
                              full_name="System Administrator", role="admin"),
        models.SafetyOfficer(username="officer1", hashed_password=hash_password("officer123"),
                              full_name="Priya Sharma", role="officer"),
    ]
    db.add_all(officers)
    db.commit()
    print(f"[2/4] Created {len(officers)} safety officers")

    # ── Workers ───────────────────────────────────────────
    workers_data = [
        {"worker_id": "WRK001", "full_name": "Rajesh Kumar",    "department": "Drilling",    "site": "Refinery Unit-1", "shift": "A", "designation": "Drilling Operator"},
        {"worker_id": "WRK002", "full_name": "Suresh Mehta",    "department": "Extraction",  "site": "Refinery Unit-1", "shift": "A", "designation": "Extraction Technician"},
        {"worker_id": "WRK003", "full_name": "Amit Patel",      "department": "Maintenance", "site": "Refinery Unit-2", "shift": "B", "designation": "Maintenance Engineer"},
        {"worker_id": "WRK004", "full_name": "Deepak Singh",    "department": "Processing",  "site": "Refinery Unit-2", "shift": "B", "designation": "Process Operator"},
        {"worker_id": "WRK005", "full_name": "Vikram Rao",      "department": "Safety",      "site": "Refinery Unit-3", "shift": "C", "designation": "Safety Inspector"},
        {"worker_id": "WRK006", "full_name": "Sanjay Gupta",    "department": "Drilling",    "site": "Mine Site-A",     "shift": "A", "designation": "Senior Driller"},
        {"worker_id": "WRK007", "full_name": "Ravi Verma",      "department": "Welding",     "site": "Mine Site-A",     "shift": "B", "designation": "Welder"},
        {"worker_id": "WRK008", "full_name": "Mohan Das",       "department": "Electrical",  "site": "Mine Site-B",     "shift": "C", "designation": "Electrician"},
    ]
    worker_objs = [models.Worker(**w) for w in workers_data]
    db.add_all(worker_objs)
    db.commit()
    print(f"[3/4] Created {len(worker_objs)} workers")

    # ── Readings + Alerts ─────────────────────────────────
    today = date.today().isoformat()
    base_time = datetime.now(timezone.utc).replace(hour=6, minute=0, second=0, microsecond=0)

    dose_scenarios = {
        "WRK001": [15, 30, 45, 65, 78, 88, 95],   # Danger -> Critical
        "WRK002": [5, 12, 25, 40, 55, 68],          # Safe -> Warning
        "WRK003": [8, 20, 35, 50, 70, 82],          # Warning -> Danger
        "WRK004": [3, 10, 18, 28, 35, 42],          # Safe
        "WRK005": [2, 8, 15, 24, 32],               # Safe
        "WRK006": [20, 45, 72, 90, 105],            # Danger -> Critical
        "WRK007": [10, 25, 38, 55, 67],             # Warning
        "WRK008": [5, 15, 28, 44, 58],              # Safe
    }

    total_readings = 0
    total_alerts = 0

    for worker in worker_objs:
        doses = dose_scenarios.get(worker.worker_id, [10, 20, 30])
        for i, dose in enumerate(doses):
            scan_time = base_time + timedelta(hours=i * 1.2)

            # Simulate realistic color features from dose
            import math
            delta_E = 3.0 + (dose / 120.0) * 40.0 + (hash(f"{worker.worker_id}{i}") % 100) * 0.05

            reading = models.Reading(
                worker_id=worker.id,
                badge_id=f"BADGE-{worker.worker_id}",
                delta_E=round(delta_E, 3),
                delta_E_corr=round(delta_E * 0.98, 3),
                dose_ppm_hr=float(dose),
                model_confidence="high" if dose < 80 else "medium",
                temperature_c=round(28 + (hash(f"{worker.worker_id}{i}") % 20) * 0.5, 1),
                humidity_pct=round(55 + (hash(f"{worker.worker_id}{i}") % 30), 1),
                scan_timestamp=scan_time,
                shift_date=today,
                scanned_by="officer1",
            )
            db.add(reading)
            db.flush()
            total_readings += 1

            # Create alerts
            if dose >= THRESHOLD_CRITICAL:
                alert = models.Alert(
                    worker_id=worker.id, reading_id=reading.id,
                    alert_type="critical", dose_at_alert=dose, threshold=THRESHOLD_CRITICAL,
                    message=f"CRITICAL: {worker.full_name} reached {dose} ppm.hr - IMMEDIATE EVACUATION",
                )
                db.add(alert)
                total_alerts += 1
            elif dose >= THRESHOLD_DANGER:
                alert = models.Alert(
                    worker_id=worker.id, reading_id=reading.id,
                    alert_type="danger", dose_at_alert=dose, threshold=THRESHOLD_DANGER,
                    message=f"DANGER: {worker.full_name} reached DGMS limit ({dose} ppm.hr)",
                )
                db.add(alert)
                total_alerts += 1
            elif dose >= THRESHOLD_WARNING:
                alert = models.Alert(
                    worker_id=worker.id, reading_id=reading.id,
                    alert_type="warning", dose_at_alert=dose, threshold=THRESHOLD_WARNING,
                    message=f"WARNING: {worker.full_name} approaching limit ({dose} ppm.hr)",
                    is_acknowledged=True, acknowledged_by="officer1",
                    acknowledged_at=scan_time + timedelta(minutes=5),
                )
                db.add(alert)
                total_alerts += 1

    db.commit()
    print(f"[4/4] Created {total_readings} readings, {total_alerts} alerts")

    print("\n" + "=" * 55)
    print("  SEED COMPLETE")
    print("=" * 55)
    print(f"  Officers : admin/admin123, officer1/officer123")
    print(f"  Workers  : WRK001 - WRK008")
    print(f"  Readings : {total_readings}")
    print(f"  Alerts   : {total_alerts}")
    print("=" * 55)
    db.close()


if __name__ == "__main__":
    seed()
