"""
test_api.py
===========

Automated API test suite for Phase 2 backend.
Tests all endpoints without needing Postman/browser.

Usage:

    # Terminal 1: start server
    uvicorn main:app --reload

    # Terminal 2: run tests
    python test_api.py
"""

import os
import sys
import time
import json

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import urllib.request
import urllib.error
import urllib.parse


BASE = "http://localhost:8000"

PASS = 0
FAIL = 0

token = None

# Sentinel meaning "caller did not pass an explicit token".
#
# Why this exists (real bug this suite used to hide):
# the old signature was ``tok=None``, and the auth expression fell back to the
# global admin ``token`` whenever ``tok`` was falsy. So if the officer login
# ever failed, ``tok=officer_token`` became ``tok=None`` and every
# "officer must be denied" assertion was silently re-issued **with the admin
# token** — turning a role-enforcement test into an admin smoke test. That is
# how "Officer CANNOT create worker" reported 201 and
# "Officer CANNOT deactivate worker" reported 404: the request was never made
# as the officer at all.
#
# With a sentinel, an explicit ``tok=<falsy>`` now means "send no credential"
# and can never escalate to admin.
_UNSET = object()


def req(
    method,
    path,
    data=None,
    headers=None,
    form=False,
    use_token=True,
    tok=_UNSET,
):
    """Simple HTTP request helper using only the Python standard library.

    use_token=False sends no Authorization header.
    tok="..."       sends that specific token instead of the global token.
    tok=None/""     sends NO token (never falls back to the admin token).
    """
    url = BASE + path

    hdrs = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    if tok is not _UNSET:
        auth = tok           # explicit caller intent — no admin fallback
    else:
        auth = token if use_token else None

    if auth:
        hdrs["Authorization"] = f"Bearer {auth}"

    if headers:
        hdrs.update(headers)

    if data and form:
        body = urllib.parse.urlencode(data).encode()
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    elif data:
        body = json.dumps(data).encode()
    else:
        body = None

    request = urllib.request.Request(
        url,
        data=body,
        headers=hdrs,
        method=method,
    )

    try:
        with urllib.request.urlopen(request, timeout=10) as resp:
            return resp.status, json.loads(resp.read())

    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}

    except Exception as e:
        return 0, {"error": str(e)}


def req_raw(method, path, use_token=True, tok=_UNSET):
    """Request helper for binary responses such as PDF.

    Uses the same no-escalation token rule as :func:`req`.

    Returns:
        (status, content_type, number_of_bytes)
    """
    url = BASE + path

    hdrs = {}

    if tok is not _UNSET:
        auth = tok
    else:
        auth = token if use_token else None

    if auth:
        hdrs["Authorization"] = f"Bearer {auth}"

    request = urllib.request.Request(
        url,
        headers=hdrs,
        method=method,
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as resp:
            return (
                resp.status,
                resp.headers.get("Content-Type", ""),
                len(resp.read()),
            )

    except urllib.error.HTTPError as e:
        return (
            e.code,
            e.headers.get("Content-Type", ""),
            len(e.read() or b""),
        )

    except Exception:
        return 0, "", 0


def check(name, condition, details=""):
    global PASS, FAIL

    if condition:
        print(f"  [PASS] {name}")
        PASS += 1
    else:
        print(f"  [FAIL] {name}  {details}")
        FAIL += 1


def section(title):
    print(f"\n{'=' * 55}")
    print(f"  {title}")
    print(f"{'=' * 55}")


def run_tests():
    global token

    print("\n" + "=" * 55)
    print("  PHASE 2 API TEST SUITE")
    print("=" * 55)

    print(f"  Target: {BASE}")
    print("  Seeding database first...")

    # Seed database before tests.
    #
    # This MUST be run by absolute path and with cwd pinned to the backend
    # directory. Previously it was `[sys.executable, "seed.py"]` with the
    # caller's cwd, so running the suite from anywhere other than
    # software/backend made seeding fail with a bare [WARN] and the run
    # continued against an UNSEEDED database. Every downstream fixture
    # (officer1, WRK004, WRK008) was then missing, which is the real origin
    # of the reported failures:
    #   * officer1 login failed  -> role tests silently ran as admin
    #   * WRK008 absent          -> DELETE returned 404
    #   * WRK004 absent          -> "Active worker 'WRK004' not found."
    #
    # Seeding is a hard precondition, so a failure now aborts the run instead
    # of producing misleading assertion results.
    import subprocess

    backend_dir = os.path.dirname(os.path.abspath(__file__))

    result = subprocess.run(
        [sys.executable, os.path.join(backend_dir, "seed.py")],
        capture_output=True,
        text=True,
        cwd=backend_dir,
    )

    if result.returncode != 0:
        print(f"  [FATAL] Seed failed — cannot trust any result below.")
        print(f"          stderr: {result.stderr[-500:]}")
        print(f"          stdout: {result.stdout[-300:]}")
        return False

    print("  [OK] Database seeded")

    # ── Health ──────────────────────────────────────────────

    section("1. System Health")

    status, body = req("GET", "/health")

    check(
        "GET /health returns 200",
        status == 200,
    )

    check(
        "Database status ok",
        body.get("database") == "ok",
        str(body),
    )

    status, body = req("GET", "/")

    check(
        "GET / returns docs link",
        "docs" in str(body),
    )

    # ── Authentication ─────────────────────────────────────

    section("2. Authentication")

    status, body = req(
        "POST",
        "/auth/login",
        data={
            "username": "admin",
            "password": "admin123",
        },
        form=True,
    )

    check(
        "POST /auth/login with valid creds returns 200",
        status == 200,
    )

    check(
        "Login returns access_token",
        "access_token" in body,
        str(body),
    )

    if "access_token" in body:
        token = body["access_token"]

    status, body = req(
        "POST",
        "/auth/login",
        data={
            "username": "admin",
            "password": "wrongpass",
        },
        form=True,
    )

    check(
        "POST /auth/login with wrong creds returns 401",
        status == 401,
    )

    status, body = req("GET", "/auth/me")

    check(
        "GET /auth/me returns officer info",
        status == 200 and body.get("username") == "admin",
    )

    # ── Authorization enforcement ──────────────────────────

    section("2b. Authorization Enforcement")

    # Valid reading body so that only authentication can cause failure.
    valid_reading = {
        "worker_id": "WRK001",
        "delta_E": 10.0,
        "dose_ppm_hr": 20.0,
    }

    protected = [
        ("GET", "/workers/", None),
        ("GET", "/readings/today", None),
        ("POST", "/readings/", valid_reading),
        ("GET", "/alerts/", None),
        ("GET", "/dashboard/summary", None),
        ("GET", "/reports/worker/WRK001/json", None),
        ("GET", "/reports/worker/WRK001/pdf", None),
    ]

    for method, path, payload in protected:
        status, _ = req(
            method,
            path,
            data=payload,
            use_token=False,
        )

        check(
            f"{method} {path} without token returns 401",
            status == 401,
            f"got {status}",
        )

    # Invalid token must also be rejected.
    status, _ = req(
        "GET",
        "/dashboard/summary",
        tok="not-a-real-token",
    )

    check(
        "GET /dashboard/summary with invalid token returns 401",
        status == 401,
        f"got {status}",
    )

    # Non-admin officer.
    status, body = req(
        "POST",
        "/auth/login",
        data={
            "username": "officer1",
            "password": "officer123",
        },
        form=True,
    )

    officer_token = body.get("access_token")

    check(
        "officer1 can log in",
        status == 200 and officer_token is not None,
        f"got {status} {str(body)[:120]}",
    )

    # The three checks below are the ONLY role-enforcement assertions in the
    # suite. If the officer token is missing they cannot test anything, and
    # (before the _UNSET fix) they would have re-run as admin and reported
    # bogus 201/404 results. Fail explicitly instead of testing the wrong role.
    if not officer_token:
        check(
            "officer role checks executable (officer token present)",
            False,
            "officer1 login produced no token — role enforcement NOT verified",
        )

    status, _ = req(
        "GET",
        "/workers/",
        tok=officer_token,
    )

    check(
        "Officer CAN list workers (200)",
        status == 200,
        f"got {status}",
    )

    status, _ = req(
        "POST",
        "/workers/",
        tok=officer_token,
        data={
            "worker_id": "OFF999",
            "full_name": "Should Fail",
        },
    )

    check(
        "Officer CANNOT create worker — admin required (403)",
        status == 403,
        f"got {status}",
    )

    status, _ = req(
        "DELETE",
        "/workers/WRK008",
        tok=officer_token,
    )

    check(
        "Officer CANNOT deactivate worker (403)",
        status == 403,
        f"got {status}",
    )

    # ── Workers CRUD ────────────────────────────────────────

    section("3. Workers CRUD")

    status, body = req(
        "GET",
        "/workers/",
    )

    check(
        "GET /workers/ returns 200",
        status == 200,
    )

    check(
        "Workers list is non-empty",
        isinstance(body, list) and len(body) > 0,
        str(body)[:100],
    )

    status, body = req(
        "GET",
        "/workers/WRK001",
    )

    check(
        "GET /workers/WRK001 returns worker",
        status == 200 and body.get("worker_id") == "WRK001",
    )

    status, body = req(
        "GET",
        "/workers/NONEXISTENT",
    )

    check(
        "GET /workers/NONEXISTENT returns 404",
        status == 404,
    )

    # Create test worker.
    new_worker = {
        "worker_id": "TST999",
        "full_name": "Test Worker",
        "department": "Testing",
        "site": "Test Site",
        "shift": "A",
    }

    status, body = req(
        "POST",
        "/workers/",
        data=new_worker,
    )

    check(
        "POST /workers/ creates worker",
        status == 201,
        str(body),
    )

    # Duplicate should fail.
    status, body = req(
        "POST",
        "/workers/",
        data=new_worker,
    )

    check(
        "POST /workers/ duplicate returns 400",
        status == 400,
    )

    # Update test worker.
    status, body = req(
        "PUT",
        "/workers/TST999",
        data={
            "designation": "API Tester",
        },
    )

    check(
        "PUT /workers/TST999 updates worker",
        status == 200
        and body.get("designation") == "API Tester",
    )

    # ── Readings & Dose Submission ─────────────────────────

    section("4. Readings & Dose Submission")

    reading_payload = {
        "worker_id": "WRK004",
        "delta_E": 18.5,
        "delta_E_corr": 18.1,
        "dose_ppm_hr": 35.0,
        "R": 120,
        "G": 140,
        "B": 100,
        "temperature_c": 28.5,
        "humidity_pct": 62.0,
        "model_confidence": "high",
        "shift_date": "2026-08-31",
        "scanned_by": "test_suite",
    }

    status, body = req(
        "POST",
        "/readings/",
        data=reading_payload,
    )

    check(
        "POST /readings/ submits reading",
        status == 201,
        str(body)[:200],
    )

    check(
        "Reading has dose_ppm_hr",
        body.get("dose_ppm_hr") == 35.0,
    )

    check(
        "Safe reading has no alert",
        body.get("alert_triggered") is False,
    )

    # Submit danger-level reading for the test worker.
    danger_payload = {
        **reading_payload,
        "worker_id": "TST999",
        "dose_ppm_hr": 85.0,
        "delta_E": 35.0,
    }

    status, body = req(
        "POST",
        "/readings/",
        data=danger_payload,
    )

    check(
        "POST danger reading (85 ppm.hr) returns 201",
        status == 201,
    )

    check(
        "Danger reading triggers alert",
        body.get("alert_triggered") is True,
        str(body),
    )

    status, body = req(
        "GET",
        "/readings/worker/WRK001",
    )

    check(
        "GET /readings/worker/WRK001 returns list",
        status == 200 and isinstance(body, list),
    )

    status, body = req(
        "GET",
        "/readings/today",
    )

    check(
        "GET /readings/today returns list",
        status == 200 and isinstance(body, list),
    )

    # ── Alerts ──────────────────────────────────────────────

    section("5. Alerts")

    status, body = req(
        "GET",
        "/alerts/",
    )

    check(
        "GET /alerts/ returns list",
        status == 200 and isinstance(body, list),
    )

    # IMPORTANT:
    # Do not use body[0].
    #
    # The API may return older/newer alerts in different order.
    # Find the specific alert generated by the danger reading
    # submitted above for TST999.
    target_alert = None

    if isinstance(body, list):
        for alert in body:
            if (
                alert.get("worker_code") == "TST999"
                and alert.get("dose_at_alert") == 85.0
            ):
                target_alert = alert
                break

    check(
        "Alert includes worker_code for danger reading",
        target_alert is not None
        and target_alert.get("worker_code") == "TST999",
        (
            f"expected TST999 danger alert, "
            f"found={target_alert}"
        ),
    )

    check(
        "Alert includes worker_name",
        target_alert is not None
        and bool(target_alert.get("worker_name")),
        (
            f"worker_name="
            f"{target_alert.get('worker_name') if target_alert else None}"
        ),
    )

    status, body = req(
        "GET",
        "/alerts/?unacknowledged_only=true",
    )

    check(
        "GET /alerts/?unacknowledged_only=true returns list",
        status == 200,
    )

    unacked = body

    if isinstance(unacked, list) and unacked:
        alert_id = unacked[0]["id"]

        status, body = req(
            "POST",
            f"/alerts/{alert_id}/acknowledge",
            data={
                "acknowledged_by": "test_suite",
            },
        )

        check(
            f"POST /alerts/{alert_id}/acknowledge works",
            status == 200,
        )

        check(
            "Alert is now acknowledged",
            body.get("is_acknowledged") is True,
        )

    status, body = req(
        "GET",
        "/alerts/summary/counts",
    )

    check(
        "GET /alerts/summary/counts returns counts dict",
        status == 200 and "warning" in body,
    )

    # ── Dashboard ───────────────────────────────────────────

    section("6. Dashboard")

    status, body = req(
        "GET",
        "/dashboard/summary",
    )

    check(
        "GET /dashboard/summary returns 200",
        status == 200,
    )

    check(
        "Has total_workers field",
        "total_workers" in body,
    )

    check(
        "Has workers list",
        isinstance(body.get("workers"), list),
    )

    check(
        "Worker statuses are valid",
        all(
            w["status"] in ("safe", "warning", "danger")
            for w in body.get("workers", [])
        ),
    )

    # ── Reports ─────────────────────────────────────────────

    section("7. Reports")

    status, body = req(
        "GET",
        "/reports/worker/WRK001/json",
    )

    check(
        "GET /reports/worker/WRK001/json returns 200",
        status == 200,
    )

    check(
        "Report has readings list",
        isinstance(body.get("readings"), list),
    )

    # PDF download must work with authentication.
    status, ctype, nbytes = req_raw(
        "GET",
        "/reports/worker/WRK001/pdf",
    )

    check(
        "GET /reports/worker/WRK001/pdf (authenticated) returns 200",
        status == 200,
        f"got {status}",
    )

    check(
        "PDF response Content-Type is application/pdf",
        "application/pdf" in ctype,
        ctype,
    )

    check(
        "PDF response is non-empty",
        nbytes > 1000,
        f"{nbytes} bytes",
    )

    # ── Final results ───────────────────────────────────────

    total = PASS + FAIL

    print(f"\n{'=' * 55}")
    print("  PHASE 2 TEST RESULTS")
    print(f"{'=' * 55}")

    print(f"  Passed : {PASS}/{total}")
    print(f"  Failed : {FAIL}/{total}")

    if FAIL == 0:
        print("  [ALL TESTS PASSED] Phase 2 backend is working!")
    else:
        print("  [SOME TESTS FAILED] Check output above")

    print(f"{'=' * 55}\n")

    return FAIL == 0


if __name__ == "__main__":
    print("Waiting 2s for server to be ready...")
    time.sleep(2)

    success = run_tests()

    sys.exit(0 if success else 1)
