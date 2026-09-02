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
# Comma-separated list of allowed origins. Defaults to the local Vite dev server.
# Never use "*" together with credentials in production.
_DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", _DEFAULT_CORS_ORIGINS).split(",")
    if o.strip()
]
