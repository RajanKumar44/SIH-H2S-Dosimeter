"""routes/workers.py — Worker CRUD endpoints."""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from auth import get_current_officer, require_admin
import models, schemas

# Every worker endpoint requires an authenticated officer. Roster mutations
# (create / update / deactivate) additionally require the admin role.
router = APIRouter(
    prefix="/workers",
    tags=["Workers"],
    dependencies=[Depends(get_current_officer)],
)


@router.post("/", response_model=schemas.WorkerOut, status_code=status.HTTP_201_CREATED)
def create_worker(
    payload: schemas.WorkerCreate,
    db: Session = Depends(get_db),
    _: models.SafetyOfficer = Depends(require_admin),
):
    """Register a new worker in the system."""
    existing = db.query(models.Worker).filter(models.Worker.worker_id == payload.worker_id).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Worker ID '{payload.worker_id}' already exists.")
    worker = models.Worker(**payload.model_dump())
    db.add(worker)
    db.commit()
    db.refresh(worker)
    return worker


@router.get("/", response_model=List[schemas.WorkerOut])
def list_workers(
    site: Optional[str] = None,
    shift: Optional[str] = None,
    active_only: bool = True,
    db: Session = Depends(get_db),
):
    """List all workers, optionally filtered by site/shift."""
    q = db.query(models.Worker)
    if active_only:
        q = q.filter(models.Worker.is_active == True)
    if site:
        q = q.filter(models.Worker.site.ilike(f"%{site}%"))
    if shift:
        q = q.filter(models.Worker.shift == shift)
    return q.order_by(models.Worker.worker_id).all()


@router.get("/{worker_id}", response_model=schemas.WorkerOut)
def get_worker(worker_id: str, db: Session = Depends(get_db)):
    """Get a single worker by their worker_id string (e.g. WRK001)."""
    worker = db.query(models.Worker).filter(models.Worker.worker_id == worker_id).first()
    if not worker:
        raise HTTPException(status_code=404, detail=f"Worker '{worker_id}' not found.")
    return worker


@router.put("/{worker_id}", response_model=schemas.WorkerOut)
def update_worker(
    worker_id: str,
    payload: schemas.WorkerUpdate,
    db: Session = Depends(get_db),
    _: models.SafetyOfficer = Depends(require_admin),
):
    """Update worker details."""
    worker = db.query(models.Worker).filter(models.Worker.worker_id == worker_id).first()
    if not worker:
        raise HTTPException(status_code=404, detail=f"Worker '{worker_id}' not found.")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(worker, field, value)
    db.commit()
    db.refresh(worker)
    return worker


@router.delete("/{worker_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_worker(
    worker_id: str,
    db: Session = Depends(get_db),
    _: models.SafetyOfficer = Depends(require_admin),
):
    """Soft-delete (deactivate) a worker."""
    worker = db.query(models.Worker).filter(models.Worker.worker_id == worker_id).first()
    if not worker:
        raise HTTPException(status_code=404, detail=f"Worker '{worker_id}' not found.")
    worker.is_active = False
    db.commit()
