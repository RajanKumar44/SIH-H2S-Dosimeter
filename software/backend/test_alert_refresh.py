"""
test_alert_refresh.py
=====================
Offline regression tests for alert de-duplication / refresh
(``routes.alerts.check_and_create_alert``).

The bug these lock down was found by running real scans through
``POST /readings/scan``: a worker crossed the danger threshold twice in one
shift, and the resulting alert row read

    dose_at_alert = 92.071
    message       = "DANGER: ... has reached DGMS 8-hr limit (86.1 ppm.hr)"

The refresh branch updated ``dose_at_alert`` and ``reading_id`` but left
``message`` at its first-breach text. Every caller embeds the dose in that
message, and the message is exactly what the alert feed renders and what the
DGMS compliance PDF prints — so the stored alert contradicted itself.

Run:  python test_alert_refresh.py     (no server, no network required)
"""
import sys
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import models
from routes.alerts import check_and_create_alert
from routes.readings import (
    THRESHOLD_CRITICAL,
    THRESHOLD_DANGER,
    THRESHOLD_WARNING,
    evaluate_thresholds,
)

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
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def add_worker(db, code="WRK001", name="Deepak Singh"):
    w = models.Worker(worker_id=code, full_name=name, site="Unit-2",
                      shift="B", is_active=True)
    db.add(w)
    db.commit()
    db.refresh(w)
    return w


def add_reading(db, worker, dose):
    r = models.Reading(
        worker_id=worker.id,
        delta_E=10.0 + dose / 5.0,
        dose_ppm_hr=float(dose),
        model_confidence="medium",
        shift_date=date.today().isoformat(),
        scanned_by="admin",
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return r


def main():
    print("=" * 62)
    print("  Alert refresh / de-duplication regression tests")
    print("=" * 62)

    # ── 1. The exact reported inconsistency ───────────────────────────────
    print("\n[1] A refreshed alert stays internally consistent")
    db = make_session()
    w = add_worker(db)

    r1 = add_reading(db, w, 86.091)
    _, a1 = evaluate_thresholds(db, w, r1)
    check("First danger breach creates an alert", a1 is not None)
    check("Alert type is danger", a1.alert_type == "danger", str(a1.alert_type))
    check("dose_at_alert matches the reading", abs(a1.dose_at_alert - 86.091) < 1e-6)
    check("Message quotes the same dose", "86.1" in a1.message, a1.message)

    r2 = add_reading(db, w, 92.071)
    _, a2 = evaluate_thresholds(db, w, r2)
    check("Second breach refreshes the SAME alert row (no duplicate)", a2.id == a1.id)
    check("Only one danger alert exists",
          db.query(models.Alert).filter(models.Alert.alert_type == "danger").count() == 1)
    check("dose_at_alert updated to the newer reading", abs(a2.dose_at_alert - 92.071) < 1e-6,
          str(a2.dose_at_alert))
    check("reading_id points at the newer reading", a2.reading_id == r2.id)
    # THE REGRESSION: message must follow the dose.
    check("Message updated to the newer dose (was stale)", "92.1" in a2.message, a2.message)
    check("Message no longer quotes the OLD dose", "86.1" not in a2.message, a2.message)

    # ── 2. Consistency invariant across a whole rising shift ──────────────
    print("\n[2] dose_at_alert and message never disagree over a rising shift")
    db2 = make_session()
    w2 = add_worker(db2, "WRK004", "Rising Worker")
    for dose in (61.0, 65.5, 70.2, 81.0, 88.4, 101.3, 118.9):
        rr = add_reading(db2, w2, dose)
        evaluate_thresholds(db2, w2, rr)

    inconsistent = []
    for a in db2.query(models.Alert).all():
        # Every caller formats the dose with one decimal place.
        if f"{a.dose_at_alert:.1f}" not in a.message:
            inconsistent.append((a.alert_type, a.dose_at_alert, a.message))
    check("Every alert's message quotes its own dose_at_alert",
          not inconsistent, str(inconsistent))

    types = sorted({a.alert_type for a in db2.query(models.Alert).all()})
    check("All three bands were reached (warning/danger/critical)",
          types == ["critical", "danger", "warning"], str(types))
    check("Exactly one open alert per band",
          db2.query(models.Alert).count() == 3,
          str(db2.query(models.Alert).count()))

    # ── 3. threshold stays correct on refresh ─────────────────────────────
    print("\n[3] threshold is preserved/refreshed correctly")
    crit = db2.query(models.Alert).filter(models.Alert.alert_type == "critical").first()
    dang = db2.query(models.Alert).filter(models.Alert.alert_type == "danger").first()
    warn = db2.query(models.Alert).filter(models.Alert.alert_type == "warning").first()
    check("critical alert threshold == 100", crit.threshold == THRESHOLD_CRITICAL, str(crit.threshold))
    check("danger alert threshold == 80", dang.threshold == THRESHOLD_DANGER, str(dang.threshold))
    check("warning alert threshold == 60", warn.threshold == THRESHOLD_WARNING, str(warn.threshold))
    check("critical dose_at_alert is the LATEST critical reading",
          abs(crit.dose_at_alert - 118.9) < 1e-6, str(crit.dose_at_alert))

    # ── 4. An acknowledged alert is never silently reused ─────────────────
    print("\n[4] Acknowledged alerts are closed, not reopened")
    db3 = make_session()
    w3 = add_worker(db3, "WRK007", "Acked Worker")
    ra = add_reading(db3, w3, 84.0)
    first = check_and_create_alert(db3, w3, ra, "danger", THRESHOLD_DANGER,
                                   f"DANGER: reached {84.0:.1f} ppm.hr")
    first.is_acknowledged = True
    first.acknowledged_by = "officer1"
    db3.commit()

    rb = add_reading(db3, w3, 90.5)
    second = check_and_create_alert(db3, w3, rb, "danger", THRESHOLD_DANGER,
                                    f"DANGER: reached {90.5:.1f} ppm.hr")
    check("A NEW alert is raised after acknowledgement", second.id != first.id)
    check("Two danger alerts now exist (one closed, one open)",
          db3.query(models.Alert).filter(models.Alert.alert_type == "danger").count() == 2)
    check("The acknowledged alert was NOT mutated",
          abs(first.dose_at_alert - 84.0) < 1e-6 and "84.0" in first.message,
          f"{first.dose_at_alert} / {first.message}")
    check("The new alert carries the new dose", abs(second.dose_at_alert - 90.5) < 1e-6)

    # ── 5. Safe readings raise nothing ────────────────────────────────────
    print("\n[5] Sub-threshold readings raise no alert")
    db4 = make_session()
    w4 = add_worker(db4, "WRK002", "Safe Worker")
    for dose in (0.0, 12.5, 26.44, 59.9):
        rr = add_reading(db4, w4, dose)
        triggered, alert = evaluate_thresholds(db4, w4, rr)
        if triggered or alert is not None:
            check(f"dose={dose} must not alert", False, f"triggered={triggered}")
            break
    else:
        check("No alert for any dose below 60 ppm.hr (incl. 59.9 boundary)", True)
    check("Alert table is empty", db4.query(models.Alert).count() == 0)

    for s in (db, db2, db3, db4):
        s.close()

    total = PASS + FAIL
    print("\n" + "=" * 62)
    print(f"  ALERT REFRESH RESULTS: {PASS}/{total} passed, {FAIL} failed")
    print("=" * 62 + "\n")
    return FAIL == 0


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
