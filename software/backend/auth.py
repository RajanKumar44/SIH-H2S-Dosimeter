"""
auth.py
=======
JWT authentication for safety officers / admins.
Default credentials (dev): admin / admin123
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from jose import JWTError, jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from database import get_db
import models
from config import SECRET_KEY, JWT_ALGORITHM as ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


# ── Password helpers (direct bcrypt — no passlib needed) ───

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ── JWT ─────────────────────────────────────────────────────

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None


# ── Dependencies ────────────────────────────────────────────

def get_current_officer(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> models.SafetyOfficer:
    """FastAPI dependency — returns the logged-in officer or raises 401."""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    username = payload.get("sub")
    officer = db.query(models.SafetyOfficer).filter(
        models.SafetyOfficer.username == username,
        models.SafetyOfficer.is_active == True,
    ).first()
    if not officer:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Officer not found")
    return officer


def get_optional_officer(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Optional[models.SafetyOfficer]:
    """Like get_current_officer but returns None instead of raising (for open endpoints)."""
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    username = payload.get("sub")
    return db.query(models.SafetyOfficer).filter(
        models.SafetyOfficer.username == username,
        models.SafetyOfficer.is_active == True,
    ).first()


def require_admin(officer: models.SafetyOfficer = Depends(get_current_officer)):
    """Require admin role."""
    if officer.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return officer
