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
_DEFAULT_CORS_ORIGINS = ",".join(
    f"http://{host}:{port}"
    for host in ("localhost", "127.0.0.1")
    for port in (5173, 5174)
)
CORS_ORIGINS = [
    o.strip().rstrip("/")
    for o in os.getenv("CORS_ORIGINS", _DEFAULT_CORS_ORIGINS).split(",")
    if o.strip()
]

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
