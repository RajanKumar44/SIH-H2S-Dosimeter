"""
bootstrap.py
============
Idempotent, **non-destructive** startup bootstrap for the demo worker roster.

Why this module exists
----------------------
``seed.py`` is the developer tool: it **wipes** every table and rebuilds a rich
demo dataset (officers, workers, 45 readings, 11 alerts). That is exactly what
you want on a laptop and exactly what you must never run on a deployed server.

The consequence was the Phase-1 bug: the FastAPI ``lifespan`` handler created
the default ``admin`` account but **no workers**. On any fresh database — most
importantly Render's ephemeral disk, which is recreated on every deploy and on
every cold start of a free instance — the roster was genuinely empty, so

    GET /workers/?active_only=true   ->   []

and the mobile app correctly reported "No active workers found". The backend was
not returning the wrong answer; there was simply nothing to return, and there
was no non-destructive way to fix that on a remote host.

This module closes that gap:

* **Insert-only.** It never updates, deactivates or deletes an existing row, so
  a real roster entered through the dashboard is never touched. A worker code
  that already exists (in *any* state, active or inactive) is skipped.
* **Deterministic.** The same fixed roster of eight codes, WRK001..WRK008, with
  the same names/sites/shifts as ``seed.py``. Tests and demos can rely on
  WRK001 and WRK004 existing without running the destructive seeder.
* **Readings-free.** Only the roster is created. No synthetic readings or alerts
  are injected into a deployed database, so dashboard aggregates and the alert
  feed still only ever reflect real scans.
* **Switchable.** ``BOOTSTRAP_DEMO_WORKERS=false`` disables it entirely for a
  production deployment whose roster is managed by an admin.
"""
from __future__ import annotations

import logging
import os
from typing import List

from sqlalchemy.orm import Session

import models

log = logging.getLogger(__name__)


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# Enabled by default so a freshly deployed demo instance is immediately usable
# from the phone. Set BOOTSTRAP_DEMO_WORKERS=false to manage the roster purely
# through the admin dashboard.
BOOTSTRAP_DEMO_WORKERS = _env_flag("BOOTSTRAP_DEMO_WORKERS", True)

# Deterministic demo roster. Kept byte-identical to the roster in ``seed.py`` so
# the two paths cannot drift and tests can reference WRK001/WRK004 either way.
DEMO_WORKERS: List[dict] = [
    {"worker_id": "WRK001", "full_name": "Rajesh Kumar", "department": "Drilling",
     "site": "Refinery Unit-1", "shift": "A", "designation": "Drilling Operator"},
    {"worker_id": "WRK002", "full_name": "Suresh Mehta", "department": "Extraction",
     "site": "Refinery Unit-1", "shift": "A", "designation": "Extraction Technician"},
    {"worker_id": "WRK003", "full_name": "Amit Patel", "department": "Maintenance",
     "site": "Refinery Unit-2", "shift": "B", "designation": "Maintenance Engineer"},
    {"worker_id": "WRK004", "full_name": "Deepak Singh", "department": "Processing",
     "site": "Refinery Unit-2", "shift": "B", "designation": "Process Operator"},
    {"worker_id": "WRK005", "full_name": "Vikram Rao", "department": "Safety",
     "site": "Refinery Unit-3", "shift": "C", "designation": "Safety Inspector"},
    {"worker_id": "WRK006", "full_name": "Sanjay Gupta", "department": "Drilling",
     "site": "Mine Site-A", "shift": "A", "designation": "Senior Driller"},
    {"worker_id": "WRK007", "full_name": "Ravi Verma", "department": "Welding",
     "site": "Mine Site-A", "shift": "B", "designation": "Welder"},
    {"worker_id": "WRK008", "full_name": "Mohan Das", "department": "Electrical",
     "site": "Mine Site-B", "shift": "C", "designation": "Electrician"},
]

DEMO_WORKER_CODES = tuple(w["worker_id"] for w in DEMO_WORKERS)


def ensure_demo_workers(db: Session, *, enabled: bool | None = None) -> dict:
    """
    Make sure the deterministic demo roster exists, without mutating real data.

    Args:
        db: An open session. The caller owns commit-on-success semantics only in
            the sense that this function commits its own inserts; it makes no
            other changes.
        enabled: Override the ``BOOTSTRAP_DEMO_WORKERS`` env flag (used by tests).

    Returns:
        ``{"enabled": bool, "created": [codes...], "existing": int, "total": int}``
    """
    if enabled is None:
        enabled = BOOTSTRAP_DEMO_WORKERS

    total = db.query(models.Worker).count()
    if not enabled:
        return {"enabled": False, "created": [], "existing": total, "total": total}

    # One query for every code we might insert — cheaper than eight lookups and
    # it deliberately ignores is_active, so a worker an admin has *deactivated*
    # is never silently resurrected.
    present = {
        code for (code,) in db.query(models.Worker.worker_id).filter(
            models.Worker.worker_id.in_(DEMO_WORKER_CODES)
        ).all()
    }

    created: List[str] = []
    for spec in DEMO_WORKERS:
        if spec["worker_id"] in present:
            continue
        db.add(models.Worker(**spec))
        created.append(spec["worker_id"])

    if created:
        db.commit()
        log.info("Bootstrapped demo workers: %s", ", ".join(created))

    return {
        "enabled": True,
        "created": created,
        "existing": len(present),
        "total": db.query(models.Worker).count(),
    }
