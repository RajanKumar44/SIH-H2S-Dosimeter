"""
main.py
=======
FastAPI application entry point for the H2S Dosimeter backend.

Run: uvicorn main:app --reload
Docs: http://localhost:8000/docs
"""
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import text
from sqlalchemy.orm import Session
from datetime import date

from database import get_db, init_db
from auth import verify_password, create_access_token, hash_password, get_current_officer
import models, schemas
from bootstrap import ensure_demo_workers
from config import CORS_ORIGINS, CORS_ORIGIN_REGEX
from routes import workers, readings, alerts, reports, dashboard

log = logging.getLogger(__name__)


# ── Lifespan (startup / shutdown) ────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Initialize DB tables, create the default admin, and make sure a worker
    roster exists.

    The roster step matters on deployed instances: this app's database is
    created from ``create_all()`` on startup, and on hosts with an ephemeral
    disk (Render free tier) that means a brand-new, empty database after every
    deploy or cold start. Previously only the admin account was created, so
    ``GET /workers/?active_only=true`` returned ``[]`` and the field app showed
    "No active workers found" with no non-destructive way to fix it remotely
    (``seed.py`` wipes every table, so it must never run against a deployment).

    ``bootstrap.ensure_demo_workers`` is insert-only and idempotent — it never
    touches a roster entered through the dashboard, and it adds no readings or
    alerts. Disable it with ``BOOTSTRAP_DEMO_WORKERS=false``.
    """
    init_db()
    db = next(get_db())
    try:
        existing = db.query(models.SafetyOfficer).filter(
            models.SafetyOfficer.username == "admin"
        ).first()
        if not existing:
            admin = models.SafetyOfficer(
                username="admin",
                hashed_password=hash_password("admin123"),
                full_name="System Administrator",
                role="admin",
            )
            db.add(admin)
            db.commit()
            print("[STARTUP] Default admin created: admin / admin123")
        else:
            print("[STARTUP] Database ready.")

        try:
            result = ensure_demo_workers(db)
            if not result["enabled"]:
                print(f"[STARTUP] Worker bootstrap disabled ({result['total']} workers present).")
            elif result["created"]:
                print(f"[STARTUP] Bootstrapped workers: {', '.join(result['created'])}")
            else:
                print(f"[STARTUP] Worker roster ready ({result['total']} workers).")
        except Exception as e:                                  # noqa: BLE001
            # A roster problem must never stop the API from serving.
            log.error("Worker bootstrap failed: %s", e)
            print(f"[STARTUP] WARNING: worker bootstrap failed: {e}")
    finally:
        db.close()
    yield


# ── App setup ───────────────────────────────────────────────
app = FastAPI(
    title="H2S Dosimeter API",
    description=(
        "Backend API for the SIH26118 Passive Colorimetric H2S Exposure-Dosimeter Wristband system.\n\n"
        "**Default login**: username=`admin`, password=`admin123`\n\n"
        "Click **Authorize** at the top right, enter credentials, then call any protected endpoint."
    ),
    version="1.0.0",
    contact={"name": "DSCE SIH Team", "url": "https://github.com/RajanKumar44/SIH-H2S-Dosimeter"},
    lifespan=lifespan,
)

# CORS — restrict to configured origins (CORS_ORIGINS env var; defaults to the
# dashboard :5173 AND the mobile PWA :5174 dev servers). In development a
# private-LAN regex is also allowed so the field app works from a real phone;
# see config.CORS_ORIGIN_REGEX. Avoid "*" together with credentials.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_origin_regex=CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ─────────────────────────────────────────────────
app.include_router(workers.router)
app.include_router(readings.router)
app.include_router(alerts.router)
app.include_router(reports.router)
app.include_router(dashboard.router)


# ── Auth endpoint ────────────────────────────────────────────
@app.post("/auth/login", response_model=schemas.TokenResponse, tags=["Auth"])
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Login with username + password. Returns a JWT bearer token."""
    officer = db.query(models.SafetyOfficer).filter(
        models.SafetyOfficer.username == form_data.username,
        models.SafetyOfficer.is_active == True,
    ).first()

    if not officer or not verify_password(form_data.password, officer.hashed_password):
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token({"sub": officer.username, "role": officer.role})
    return {"access_token": token, "token_type": "bearer"}


@app.get("/auth/me", tags=["Auth"])
def get_me(officer: models.SafetyOfficer = Depends(get_current_officer)):
    """Get currently logged-in officer info."""
    return {
        "username": officer.username,
        "full_name": officer.full_name,
        "role": officer.role,
    }


# ── Health check ─────────────────────────────────────────────
@app.get("/health", tags=["System"])
def health_check(db: Session = Depends(get_db)):
    """
    Health check endpoint for deployment monitoring.

    Also reports whether the ML scan path (``POST /readings/scan``) is ready,
    so the mobile app's Settings screen can warn the operator *before* a scan
    is attempted rather than surfacing a 503 mid-demo. The probe is lazy and
    never imports OpenCV/scikit-learn into this route.
    """
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as e:
        log.error("Health check DB error: %s", e)
        db_status = "error"

    # Roster size is reported because an empty roster is indistinguishable from
    # a broken /workers call when seen from the phone ("No active workers
    # found"). Exposing the count on the public health endpoint turns that into
    # a one-request diagnosis instead of a guess.
    try:
        active_workers = db.query(models.Worker).filter(
            models.Worker.is_active == True
        ).count()
    except Exception as e:                                  # noqa: BLE001
        log.error("Health check worker count error: %s", e)
        active_workers = None

    # Import here so the rest of the app (and the offline tests) never pull in
    # the ML bridge just to answer /health.
    try:
        from ml_inference import model_status
        st = model_status()
        ml = {
            "available": st["available"],
            "model_present": st["model_present"],
            "dependencies_present": st["dependencies_present"],
        }
        if not st["available"] and st.get("hint"):
            ml["hint"] = st["hint"]
    except Exception as e:                                  # noqa: BLE001
        log.error("Health check ML probe error: %s", e)
        ml = {"available": False, "hint": f"ML probe failed: {e}"}

    return {
        "status": "ok",
        "database": db_status,
        "active_workers": active_workers,
        "ml": ml,
        "date": date.today().isoformat(),
        "version": "1.0.0",
    }


@app.get("/", tags=["System"])
def root():
    """Root endpoint — points to docs."""
    return {
        "message": "H2S Dosimeter API is running",
        "docs": "http://localhost:8000/docs",
        "redoc": "http://localhost:8000/redoc",
        "project": "SIH26118 - DSCE",
    }
