"""
config.py
=========
Central, environment-driven configuration for the H2S Dosimeter backend.

All environment-dependent values are read here once, so the rest of the app
imports from a single place. See ``.env.example`` for the supported variables.

Security note:
  In production (APP_ENV=production) a real SECRET_KEY MUST be provided via the
  environment — the app refuses to start with the insecure development default.
"""
import os
import logging

log = logging.getLogger(__name__)

# ── Environment ─────────────────────────────────────────────
APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
IS_PRODUCTION = APP_ENV in ("production", "prod")

# ── Database ────────────────────────────────────────────────
# SQLite for dev (zero-config); override with a PostgreSQL URL in production.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./h2s_dosimeter.db")

# ── JWT / Auth ──────────────────────────────────────────────
# Dev-only fallback secret. It is intentionally obvious that it is NOT a secret;
# production must supply its own via the SECRET_KEY env var.
_DEV_SECRET_KEY = "dev-insecure-secret-change-me-do-not-use-in-production"

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    if IS_PRODUCTION:
        raise RuntimeError(
            "SECRET_KEY is required when APP_ENV=production. "
            "Set the SECRET_KEY environment variable to a long random string "
            "(e.g. `python -c \"import secrets; print(secrets.token_urlsafe(48))\"`)."
        )
    SECRET_KEY = _DEV_SECRET_KEY
    log.warning(
        "Using the INSECURE development SECRET_KEY. Set the SECRET_KEY env var "
        "before deploying (APP_ENV=production will refuse to start without it)."
    )

JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("TOKEN_EXPIRE_MINUTES", "480"))  # 8-hour shift

# ── CORS ────────────────────────────────────────────────────
# Comma-separated list of allowed origins.
#
# Two browser clients ship in this repo and BOTH must be allowed by default,
# otherwise the browser blocks the request before the route is ever reached:
#   * dashboard  — Vite dev server on :5173 (software/dashboard)
#   * mobile PWA — Vite dev server on :5174 (software/mobile_app)
# Never use "*" together with credentials in production.
_DEV_SERVER_ORIGINS = tuple(
    f"http://{host}:{port}"
    for host in ("localhost", "127.0.0.1")
    for port in (5173, 5174)
)

# ── Capacitor / Cordova native WebView origins ──────────────
# The Android build (software/mobile_app + Capacitor) does NOT run on an
# http://<lan-ip>:<port> origin. Inside the native WebView the page is served
# from the app bundle, so the browser sends one of these fixed Origin headers
# depending on platform / Capacitor `server.androidScheme` configuration:
#
#   https://localhost        Android, androidScheme: "https"  (Capacitor 4+ default)
#   http://localhost         Android, androidScheme: "http"   (legacy)
#   capacitor://localhost    iOS / Capacitor custom scheme
#   ionic://localhost        legacy Ionic WebView scheme
#
# None of these can be matched by the dev LAN regex below:
#   * "capacitor://" / "ionic://" are not http(s) schemes at all, and Starlette's
#     allow_origin_regex is anchored against the literal Origin header.
#   * the regex is disabled entirely in production (IS_PRODUCTION).
#
# That is exactly why the phone showed "Cannot reach the server" while
# https://sih-h2s-backend.onrender.com/health opened fine in Chrome: the
# backend was up, but the preflight/actual response carried no
# Access-Control-Allow-Origin for the native origin, so the WebView killed
# the request before the app ever saw a response.
#
# These origins are therefore ALWAYS appended to the allow-list (in production
# too) unless explicitly disabled with ALLOW_NATIVE_APP_ORIGINS=false. They are
# a fixed, finite, non-guessable-by-attacker set — a malicious website cannot
# make a browser send `Origin: capacitor://localhost`.
NATIVE_APP_ORIGINS = (
    "https://localhost",
    "http://localhost",
    "capacitor://localhost",
    "ionic://localhost",
)


def _env_flag(name: str, default: bool = True) -> bool:
    """Parse a boolean environment variable ('0', 'false', 'no', 'off' → False)."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


ALLOW_NATIVE_APP_ORIGINS = _env_flag("ALLOW_NATIVE_APP_ORIGINS", True)

# ── Deployed web origins ────────────────────────────────────
# The dashboard / PWA is deployed on Vercel. Its production origin must be
# allowed by default so a fresh Render deploy works without first having to
# set CORS_ORIGINS by hand.
DEPLOYED_WEB_ORIGINS = (
    "https://sih-h2s-dosimeter.vercel.app",
)

_DEFAULT_CORS_ORIGINS = ",".join(_DEV_SERVER_ORIGINS + DEPLOYED_WEB_ORIGINS)


def _normalize_origin(origin: str) -> str:
    """Trim whitespace and any trailing slash so comparisons are exact."""
    return origin.strip().rstrip("/")


def build_cors_origins(
    raw: str | None = None,
    allow_native: bool | None = None,
) -> list[str]:
    """Build the final, de-duplicated CORS allow-list.

    ``raw``  — the CORS_ORIGINS value (None → the built-in default list).
    ``allow_native`` — None → use the ALLOW_NATIVE_APP_ORIGINS setting.

    The native WebView origins are merged in *after* the configured list, so an
    operator who overrides CORS_ORIGINS for the dashboard cannot accidentally
    break the Android app. Order is preserved and duplicates removed.
    """
    if raw is None:
        raw = _DEFAULT_CORS_ORIGINS
    if allow_native is None:
        allow_native = ALLOW_NATIVE_APP_ORIGINS

    configured = [_normalize_origin(o) for o in raw.split(",") if o.strip()]
    if allow_native:
        configured += [_normalize_origin(o) for o in NATIVE_APP_ORIGINS]

    seen: set[str] = set()
    ordered: list[str] = []
    for origin in configured:
        if origin and origin not in seen:
            seen.add(origin)
            ordered.append(origin)
    return ordered


CORS_ORIGINS = build_cors_origins(os.getenv("CORS_ORIGINS"))

# The field mobile app runs on a phone, so its origin is never one of the fixed
# localhost entries above and cannot be known ahead of time. Two shapes occur:
#
#   1. LAN IP        http://192.168.1.5:5174   — phone on the same Wi-Fi
#   2. HTTPS tunnel  https://5174-abc.<tunnel> — required because the camera
#                    (getUserMedia) only works in a secure context
#
# In DEVELOPMENT ONLY both are matched by a regex so a handset demo works
# without editing config. Production ignores the regex entirely and uses the
# strict explicit CORS_ORIGINS list.

# RFC1918 / loopback / link-local hosts only — never arbitrary public IPs.
_PRIVATE_HOST = (
    r"(?:"
    r"localhost"
    r"|127\.0\.0\.1"
    r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r"|169\.254\.\d{1,3}\.\d{1,3}"
    r")"
)

# Dev-tunnel providers used to obtain the HTTPS origin the camera requires.
# Matched as exact domain suffixes (a leading dot), so "notngrok-free.app"
# cannot slip through.
_TUNNEL_DOMAINS = (
    "ngrok-free.app",
    "ngrok.io",
    "ngrok.app",
    "trycloudflare.com",
    "loca.lt",
    "github.dev",
    "gitpod.io",
    "e2b.dev",
    "sandbox.novita.ai",
)
_TUNNEL_SUFFIX = "|".join(d.replace(".", r"\.") for d in _TUNNEL_DOMAINS)

_DEV_CORS_ORIGIN_REGEX = (
    rf"^https?://(?:{_PRIVATE_HOST}(?::\d+)?"
    rf"|[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.(?:{_TUNNEL_SUFFIX})(?::\d+)?)$"
)

# Explicit override always wins; otherwise the regex is dev-only.
CORS_ORIGIN_REGEX = os.getenv("CORS_ORIGIN_REGEX") or (
    None if IS_PRODUCTION else _DEV_CORS_ORIGIN_REGEX
)
