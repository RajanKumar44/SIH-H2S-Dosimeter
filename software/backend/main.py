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

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import date

from database import get_db, init_db
from auth import verify_password, create_access_token, hash_password, get_current_officer
import models, schemas
from routes import workers, readings, alerts, reports, dashboard

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
)

# Allow all origins for dev (restrict in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
    """Health check endpoint for deployment monitoring."""
    try:
        db.execute(__import__("sqlalchemy").text("SELECT 1"))
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {e}"
    return {
        "status": "ok",
        "database": db_status,
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


# ── Startup ──────────────────────────────────────────────────
@app.on_event("startup")
def on_startup():
    """Initialize DB tables and create default admin if not exists."""
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
    finally:
        db.close()
