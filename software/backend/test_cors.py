"""
test_cors.py
============
CORS allow-list verification for the H2S Dosimeter backend.

Why this suite exists
---------------------
The Android app (Capacitor WebView) reported "Cannot reach the server" while
https://sih-h2s-backend.onrender.com/health opened fine in the phone's browser.
The backend was healthy — the failure was CORS: the native WebView sends a
fixed, non-http Origin (``https://localhost`` / ``capacitor://localhost``) that
was matched by neither the explicit CORS_ORIGINS list nor the dev LAN regex
(which is disabled in production anyway). With no Access-Control-Allow-Origin
in the response, the WebView aborted the request before the app saw it.

These tests lock the fix in place, in BOTH development and production mode, and
assert that unknown/malicious origins are still rejected — i.e. the fix must
never regress to ``allow_origins=["*"]``.

Run:  python -m pytest test_cors.py -q
      python test_cors.py          (standalone, no pytest needed)
"""
import importlib
import os
import sys
from contextlib import contextmanager

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

# Origins the phone / browser clients actually send.
VERCEL_ORIGIN = "https://sih-h2s-dosimeter.vercel.app"
CAPACITOR_HTTPS = "https://localhost"        # Android, androidScheme https
CAPACITOR_HTTP = "http://localhost"          # Android, androidScheme http
CAPACITOR_SCHEME = "capacitor://localhost"   # iOS / custom scheme
IONIC_SCHEME = "ionic://localhost"           # legacy Ionic WebView
DASHBOARD_DEV = "http://localhost:5173"
MOBILE_DEV = "http://localhost:5174"
LAN_DEV = "http://192.168.1.5:5174"
EVIL_ORIGIN = "https://evil.example.com"
EVIL_LOOKALIKE = "https://sih-h2s-dosimeter.vercel.app.evil.example.com"


# ── Harness ─────────────────────────────────────────────────

@contextmanager
def config_env(**env):
    """Reload config.py with a specific environment, then restore it."""
    saved = {}
    keys = ("APP_ENV", "CORS_ORIGINS", "CORS_ORIGIN_REGEX",
            "ALLOW_NATIVE_APP_ORIGINS", "SECRET_KEY")
    for k in keys:
        saved[k] = os.environ.get(k)
        os.environ.pop(k, None)
    # Production refuses to boot without a real SECRET_KEY; supply one so the
    # production-mode CORS behaviour can be tested in isolation.
    os.environ["SECRET_KEY"] = "test-only-secret-not-used-for-signing-anything-real"
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        import config
        yield importlib.reload(config)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        import config
        importlib.reload(config)


def make_client(cfg):
    """Minimal app wired with the SAME middleware arguments main.py uses."""
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.CORS_ORIGINS,
        allow_origin_regex=cfg.CORS_ORIGIN_REGEX,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/auth/login")
    def login():
        return {"access_token": "x", "token_type": "bearer"}

    return TestClient(app)


def preflight(client, origin, method="POST", path="/auth/login"):
    """Send a CORS preflight (OPTIONS) exactly as a browser/WebView would."""
    return client.options(
        path,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )


def simple_get(client, origin, path="/health"):
    """Send an actual (non-preflight) cross-origin request."""
    return client.get(path, headers={"Origin": origin})


def origin_allowed(client, origin) -> bool:
    """True only if BOTH the preflight and the real request are CORS-approved.

    A browser needs Access-Control-Allow-Origin on the actual response too —
    a passing preflight alone is not enough.
    """
    pre = preflight(client, origin)
    if pre.status_code != 200:
        return False
    allow = pre.headers.get("access-control-allow-origin")
    if allow not in (origin, "*"):
        return False
    got = simple_get(client, origin)
    return got.headers.get("access-control-allow-origin") in (origin, "*")


# ── Reporting (works standalone and under pytest) ───────────
PASS = 0
FAIL = 0
FAILURES = []


def check(name, condition, details=""):
    global PASS, FAIL
    if condition:
        print(f"  [PASS] {name}")
        PASS += 1
    else:
        print(f"  [FAIL] {name}  {details}")
        FAIL += 1
        FAILURES.append(name)
    return bool(condition)


# ── Tests ───────────────────────────────────────────────────

def test_production_allows_native_and_vercel_origins():
    """PRODUCTION: the exact origin matrix from the bug report."""
    print("\n[1] PRODUCTION (APP_ENV=production, no CORS_ORIGINS override)")
    with config_env(APP_ENV="production") as cfg:
        client = make_client(cfg)
        check("regex disabled in production", cfg.CORS_ORIGIN_REGEX is None,
              f"got {cfg.CORS_ORIGIN_REGEX!r}")
        check("no wildcard in allow-list", "*" not in cfg.CORS_ORIGINS,
              str(cfg.CORS_ORIGINS))

        for origin in (VERCEL_ORIGIN, CAPACITOR_HTTPS, CAPACITOR_HTTP,
                       CAPACITOR_SCHEME, IONIC_SCHEME):
            check(f"ALLOWED  {origin}", origin_allowed(client, origin))

        for origin in (EVIL_ORIGIN, EVIL_LOOKALIKE):
            check(f"BLOCKED  {origin}", not origin_allowed(client, origin))

        # The dev LAN origin must NOT be reachable in production.
        check(f"BLOCKED  {LAN_DEV} (dev-only LAN origin)",
              not origin_allowed(client, LAN_DEV))
    assert FAIL == 0, FAILURES


def test_development_allows_dev_servers_and_native():
    """DEVELOPMENT: dev servers, LAN phone, and native origins all work."""
    print("\n[2] DEVELOPMENT (APP_ENV=development)")
    with config_env(APP_ENV="development") as cfg:
        client = make_client(cfg)
        check("regex enabled in development", cfg.CORS_ORIGIN_REGEX is not None)
        for origin in (DASHBOARD_DEV, MOBILE_DEV, LAN_DEV, VERCEL_ORIGIN,
                       CAPACITOR_HTTPS, CAPACITOR_HTTP, CAPACITOR_SCHEME,
                       IONIC_SCHEME):
            check(f"ALLOWED  {origin}", origin_allowed(client, origin))
        check(f"BLOCKED  {EVIL_ORIGIN}", not origin_allowed(client, EVIL_ORIGIN))
    assert FAIL == 0, FAILURES


def test_custom_cors_origins_still_keeps_native():
    """Overriding CORS_ORIGINS must not break the Android app."""
    print("\n[3] CORS_ORIGINS override keeps native origins")
    with config_env(APP_ENV="production",
                    CORS_ORIGINS="https://ops.example.com") as cfg:
        client = make_client(cfg)
        check("custom origin allowed",
              origin_allowed(client, "https://ops.example.com"))
        for origin in (CAPACITOR_HTTPS, CAPACITOR_SCHEME, IONIC_SCHEME,
                       CAPACITOR_HTTP):
            check(f"native still allowed  {origin}", origin_allowed(client, origin))
        check("vercel NOT auto-added when overridden",
              not origin_allowed(client, VERCEL_ORIGIN))
        check(f"BLOCKED  {EVIL_ORIGIN}", not origin_allowed(client, EVIL_ORIGIN))
    assert FAIL == 0, FAILURES


def test_native_origins_can_be_disabled():
    """ALLOW_NATIVE_APP_ORIGINS=false is an explicit, working opt-out."""
    print("\n[4] ALLOW_NATIVE_APP_ORIGINS=false opt-out")
    with config_env(APP_ENV="production",
                    ALLOW_NATIVE_APP_ORIGINS="false") as cfg:
        client = make_client(cfg)
        check("native origins removed from list",
              all(o not in cfg.CORS_ORIGINS for o in cfg.NATIVE_APP_ORIGINS),
              str(cfg.CORS_ORIGINS))
        check(f"BLOCKED  {CAPACITOR_SCHEME}",
              not origin_allowed(client, CAPACITOR_SCHEME))
        check("vercel still allowed", origin_allowed(client, VERCEL_ORIGIN))
    assert FAIL == 0, FAILURES


def test_build_cors_origins_helper():
    """Unit-level checks on the list builder (dedup, order, normalisation)."""
    print("\n[5] build_cors_origins() helper")
    with config_env(APP_ENV="production") as cfg:
        out = cfg.build_cors_origins("https://a.example.com/,https://a.example.com",
                                     allow_native=False)
        check("trailing slash normalised + de-duplicated",
              out == ["https://a.example.com"], str(out))

        out = cfg.build_cors_origins("capacitor://localhost", allow_native=True)
        check("no duplicate when native origin already configured",
              out.count("capacitor://localhost") == 1, str(out))

        out = cfg.build_cors_origins("https://a.example.com", allow_native=True)
        check("configured origin comes before native ones",
              out[0] == "https://a.example.com", str(out))
        check("all four native origins appended",
              all(o in out for o in cfg.NATIVE_APP_ORIGINS), str(out))

        out = cfg.build_cors_origins("  ,  , https://b.example.com ,",
                                     allow_native=False)
        check("blank entries ignored", out == ["https://b.example.com"], str(out))
    assert FAIL == 0, FAILURES


def test_preflight_reflects_credentials_and_headers():
    """Preflight must permit the Authorization header and credentials."""
    print("\n[6] Preflight allows Authorization + credentials")
    with config_env(APP_ENV="production") as cfg:
        client = make_client(cfg)
        pre = preflight(client, CAPACITOR_HTTPS)
        check("preflight 200", pre.status_code == 200, str(pre.status_code))
        check("allow-credentials true",
              pre.headers.get("access-control-allow-credentials") == "true")
        allow_headers = (pre.headers.get("access-control-allow-headers") or "").lower()
        check("authorization header allowed", "authorization" in allow_headers,
              allow_headers)
        check("POST method allowed",
              "post" in (pre.headers.get("access-control-allow-methods") or "").lower())
    assert FAIL == 0, FAILURES


TESTS = [
    test_production_allows_native_and_vercel_origins,
    test_development_allows_dev_servers_and_native,
    test_custom_cors_origins_still_keeps_native,
    test_native_origins_can_be_disabled,
    test_build_cors_origins_helper,
    test_preflight_reflects_credentials_and_headers,
]


def main():
    print("=" * 60)
    print("  CORS ALLOW-LIST VERIFICATION")
    print("=" * 60)
    for t in TESTS:
        try:
            t()
        except AssertionError:
            pass  # individual checks already reported
    print("\n" + "=" * 60)
    print(f"  CORS RESULTS: {PASS}/{PASS + FAIL} passed, {FAIL} failed")
    print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
