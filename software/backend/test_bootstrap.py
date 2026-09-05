"""
test_bootstrap.py
=================
Regression tests for the worker-roster bootstrap (``bootstrap.py``).

These cover the Phase-1 production bug directly: on a fresh database — which is
what a Render free instance has after every deploy and every cold start — the
old startup path created only the ``admin`` account, so

    GET /workers/?active_only=true   ->   []

and the field app showed "No active workers found" with no way to fix it
remotely, because ``seed.py`` wipes every table.

Nothing here is mocked away: the tests run the REAL ORM against an in-memory
SQLite database and assert on the real function's behaviour.

Run:  python test_bootstrap.py     (no server, no network required)
"""
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models
from bootstrap import DEMO_WORKER_CODES, ensure_demo_workers

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


def make_session():
    """Fresh in-memory DB using the real ORM schema."""
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def active_codes(db):
    return sorted(
        c for (c,) in db.query(models.Worker.worker_id)
        .filter(models.Worker.is_active == True).all()
    )


def all_codes(db):
    return sorted(c for (c,) in db.query(models.Worker.worker_id).all())


def main():
    print("=" * 60)
    print("  Worker-roster bootstrap regression tests")
    print("=" * 60)

    # ── 1. Empty database: the exact Phase-1 failure ──────────────────────
    print("\n[1] Fresh/empty database gets a deterministic roster")
    db = make_session()
    check("Precondition: database really is empty", all_codes(db) == [])

    result = ensure_demo_workers(db, enabled=True)
    check("Bootstrap reports enabled", result["enabled"] is True)
    check(
        f"All {len(DEMO_WORKER_CODES)} demo workers created",
        sorted(result["created"]) == sorted(DEMO_WORKER_CODES),
        str(result["created"]),
    )
    check(
        "active_only=true would now be NON-empty (the reported bug)",
        len(active_codes(db)) == len(DEMO_WORKER_CODES),
        str(active_codes(db)),
    )
    check("WRK001 exists (referenced by tests/demos)", "WRK001" in all_codes(db))
    check("WRK004 exists (was missing in earlier test runs)", "WRK004" in all_codes(db))
    check("Every worker is created active", len(active_codes(db)) == len(all_codes(db)))

    # The roster must NOT drag synthetic exposure data into a deployment.
    check("No readings fabricated", db.query(models.Reading).count() == 0)
    check("No alerts fabricated", db.query(models.Alert).count() == 0)
    check("No officer rows touched", db.query(models.SafetyOfficer).count() == 0)

    # ── 2. Idempotency ────────────────────────────────────────────────────
    print("\n[2] Running again is a no-op (idempotent across restarts)")
    before = all_codes(db)
    second = ensure_demo_workers(db, enabled=True)
    check("Second run creates nothing", second["created"] == [], str(second["created"]))
    check("Roster unchanged", all_codes(db) == before)
    check("No duplicate rows", len(all_codes(db)) == len(set(all_codes(db))))

    # ── 3. A deactivated worker is never resurrected ──────────────────────
    print("\n[3] Admin decisions are respected (no resurrection)")
    w = db.query(models.Worker).filter(models.Worker.worker_id == "WRK003").first()
    w.is_active = False
    db.commit()

    ensure_demo_workers(db, enabled=True)
    w = db.query(models.Worker).filter(models.Worker.worker_id == "WRK003").first()
    check("Deactivated WRK003 stays inactive after restart", w.is_active is False)
    check("WRK003 excluded from the active list", "WRK003" not in active_codes(db))
    check("No duplicate WRK003 inserted", all_codes(db).count("WRK003") == 1)

    # ── 4. Real roster data is never mutated ──────────────────────────────
    print("\n[4] Real (dashboard-entered) data is left alone")
    db.add(models.Worker(worker_id="REAL001", full_name="Real Employee",
                         site="Plant-9", shift="A", is_active=True))
    db.commit()
    # Rename a demo row as an admin would; bootstrap must not overwrite it.
    w1 = db.query(models.Worker).filter(models.Worker.worker_id == "WRK001").first()
    w1.full_name = "Renamed By Admin"
    db.commit()

    ensure_demo_workers(db, enabled=True)
    w1 = db.query(models.Worker).filter(models.Worker.worker_id == "WRK001").first()
    check("Admin's rename to WRK001 preserved", w1.full_name == "Renamed By Admin", w1.full_name)
    check("Manually added REAL001 still present", "REAL001" in all_codes(db))

    # ── 5. The opt-out switch works ───────────────────────────────────────
    print("\n[5] BOOTSTRAP_DEMO_WORKERS=false disables bootstrapping")
    db2 = make_session()
    off = ensure_demo_workers(db2, enabled=False)
    check("Reports disabled", off["enabled"] is False)
    check("Creates nothing when disabled", all_codes(db2) == [], str(all_codes(db2)))

    db.close()
    db2.close()

    total = PASS + FAIL
    print("\n" + "=" * 60)
    print(f"  BOOTSTRAP RESULTS: {PASS}/{total} passed, {FAIL} failed")
    print("=" * 60 + "\n")
    return FAIL == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
