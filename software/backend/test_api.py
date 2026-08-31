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
import sys
import time
import json
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import urllib.request
import urllib.error
import urllib.parse

BASE = "http://localhost:8000"
PASS = 0
FAIL = 0
token = None


def req(method, path, data=None, headers=None, form=False):
    """Simple HTTP request helper (no extra deps beyond stdlib)."""
    url = BASE + path
    hdrs = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    if headers:
        hdrs.update(headers)

    if data and form:
        body = urllib.parse.urlencode(data).encode()
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    elif data:
        body = json.dumps(data).encode()
    else:
        body = None

    request = urllib.request.Request(url, data=body, headers=hdrs, method=method)
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
    print(f"  Seeding database first...")

    # Seed DB before tests
    import subprocess, sys
    result = subprocess.run([sys.executable, "seed.py"], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [WARN] Seed failed: {result.stderr[:200]}")
    else:
        print(f"  [OK] Database seeded")

    # ── Health ────────────────────────────────────────────
    section("1. System Health")
    status, body = req("GET", "/health")
    check("GET /health returns 200", status == 200)
    check("Database status ok", body.get("database") == "ok", str(body))

    status, body = req("GET", "/")
    check("GET / returns docs link", "docs" in str(body))

    # ── Auth ──────────────────────────────────────────────
    section("2. Authentication")
    status, body = req("POST", "/auth/login",
                        data={"username": "admin", "password": "admin123"}, form=True)
    check("POST /auth/login with valid creds returns 200", status == 200)
    check("Login returns access_token", "access_token" in body, str(body))
    if "access_token" in body:
        token = body["access_token"]

    status, body = req("POST", "/auth/login",
                        data={"username": "admin", "password": "wrongpass"}, form=True)
    check("POST /auth/login with wrong creds returns 401", status == 401)

    status, body = req("GET", "/auth/me")
    check("GET /auth/me returns officer info", status == 200 and body.get("username") == "admin")

    # ── Workers ───────────────────────────────────────────
    section("3. Workers CRUD")
    status, body = req("GET", "/workers/")
    check("GET /workers/ returns 200", status == 200)
    check("Workers list is non-empty", isinstance(body, list) and len(body) > 0, str(body)[:100])

    status, body = req("GET", "/workers/WRK001")
    check("GET /workers/WRK001 returns worker", status == 200 and body.get("worker_id") == "WRK001")

    status, body = req("GET", "/workers/NONEXISTENT")
    check("GET /workers/NONEXISTENT returns 404", status == 404)

    # Create a new worker
    new_worker = {"worker_id": "TST999", "full_name": "Test Worker",
                  "department": "Testing", "site": "Test Site", "shift": "A"}
    status, body = req("POST", "/workers/", data=new_worker)
    check("POST /workers/ creates worker", status == 201, str(body))

    # Duplicate should fail
    status, body = req("POST", "/workers/", data=new_worker)
    check("POST /workers/ duplicate returns 400", status == 400)

    # Update worker
    status, body = req("PUT", "/workers/TST999", data={"designation": "API Tester"})
    check("PUT /workers/TST999 updates worker", status == 200 and body.get("designation") == "API Tester")

    # ── Readings ──────────────────────────────────────────
    section("4. Readings & Dose Submission")
    reading_payload = {
        "worker_id": "WRK004",
        "delta_E": 18.5,
        "delta_E_corr": 18.1,
        "dose_ppm_hr": 35.0,
        "R": 120, "G": 140, "B": 100,
        "temperature_c": 28.5,
        "humidity_pct": 62.0,
        "model_confidence": "high",
        "shift_date": "2026-08-31",
        "scanned_by": "test_suite",
    }
    status, body = req("POST", "/readings/", data=reading_payload)
    check("POST /readings/ submits reading", status == 201, str(body)[:200])
    check("Reading has dose_ppm_hr", body.get("dose_ppm_hr") == 35.0)
    check("Safe reading has no alert", body.get("alert_triggered") == False)

    # Submit a danger-level reading
    danger_payload = {**reading_payload, "worker_id": "TST999", "dose_ppm_hr": 85.0, "delta_E": 35.0}
    status, body = req("POST", "/readings/", data=danger_payload)
    check("POST danger reading (85 ppm.hr) returns 201", status == 201)
    check("Danger reading triggers alert", body.get("alert_triggered") == True, str(body))

    status, body = req("GET", "/readings/worker/WRK001")
    check("GET /readings/worker/WRK001 returns list", status == 200 and isinstance(body, list))

    status, body = req("GET", "/readings/today")
    check("GET /readings/today returns list", status == 200 and isinstance(body, list))

    # ── Alerts ────────────────────────────────────────────
    section("5. Alerts")
    status, body = req("GET", "/alerts/")
    check("GET /alerts/ returns list", status == 200 and isinstance(body, list))

    status, body = req("GET", "/alerts/?unacknowledged_only=true")
    check("GET /alerts/?unacknowledged_only=true returns list", status == 200)
    unacked = body
    if unacked:
        alert_id = unacked[0]["id"]
        status, body = req("POST", f"/alerts/{alert_id}/acknowledge",
                           data={"acknowledged_by": "test_suite"})
        check(f"POST /alerts/{alert_id}/acknowledge works", status == 200)
        check("Alert is now acknowledged", body.get("is_acknowledged") == True)

    status, body = req("GET", "/alerts/summary/counts")
    check("GET /alerts/summary/counts returns counts dict", status == 200 and "warning" in body)

    # ── Dashboard ─────────────────────────────────────────
    section("6. Dashboard")
    status, body = req("GET", "/dashboard/summary")
    check("GET /dashboard/summary returns 200", status == 200)
    check("Has total_workers field", "total_workers" in body)
    check("Has workers list", isinstance(body.get("workers"), list))
    check("Worker statuses are valid", all(
        w["status"] in ("safe", "warning", "danger") for w in body.get("workers", [])
    ))

    # ── Reports ───────────────────────────────────────────
    section("7. Reports")
    status, body = req("GET", "/reports/worker/WRK001/json")
    check("GET /reports/worker/WRK001/json returns 200", status == 200)
    check("Report has readings list", isinstance(body.get("readings"), list))

    # ── Final results ─────────────────────────────────────
    total = PASS + FAIL
    print(f"\n{'=' * 55}")
    print(f"  PHASE 2 TEST RESULTS")
    print(f"{'=' * 55}")
    print(f"  Passed : {PASS}/{total}")
    print(f"  Failed : {FAIL}/{total}")
    if FAIL == 0:
        print(f"  [ALL TESTS PASSED] Phase 2 backend is working!")
    else:
        print(f"  [SOME TESTS FAILED] Check output above")
    print(f"{'=' * 55}\n")
    return FAIL == 0


if __name__ == "__main__":
    print("Waiting 2s for server to be ready...")
    time.sleep(2)
    success = run_tests()
    sys.exit(0 if success else 1)
