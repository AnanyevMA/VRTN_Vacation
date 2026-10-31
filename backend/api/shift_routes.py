from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.auth import require_admin
from backend.database import get_db
from backend.models import WorkShift
from backend.schemas import WorkShiftCreate, WorkShiftUpdate, WorkShiftOut

router = APIRouter(prefix="/api/shifts", tags=["Work Shifts Management"], dependencies=[Depends(require_admin)])


@router.get("", response_model=List[WorkShiftOut])
def list_shifts(db: Session = Depends(get_db)):
    return db.query(WorkShift).order_by(WorkShift.id.asc()).all()


@router.post("", response_model=WorkShiftOut)
def create_shift(shift_in: WorkShiftCreate, db: Session = Depends(get_db)):
    existing = db.query(WorkShift).filter(WorkShift.name == shift_in.name.strip()).first()
    if existing:
        raise HTTPException(status_code=400, detail="Смена с таким наименованием уже существует")

    shift = WorkShift(
        name=shift_in.name.strip(),
        code=shift_in.code,
        description=shift_in.description,
        default_quota=shift_in.default_quota or 2,
        is_active=shift_in.is_active,
    )
    db.add(shift)
    db.commit()
    db.refresh(shift)
    return shift


@router.put("/{shift_id}", response_model=WorkShiftOut)
def update_shift(shift_id: int, shift_in: WorkShiftUpdate, db: Session = Depends(get_db)):
    shift = db.query(WorkShift).filter(WorkShift.id == shift_id).first()
    if not shift:
        raise HTTPException(status_code=404, detail="Смена не найдена")

    if shift_in.name is not None:
        shift.name = shift_in.name.strip()
    if shift_in.code is not None:
        shift.code = shift_in.code
    if shift_in.description is not None:
        shift.description = shift_in.description
    if shift_in.default_quota is not None:
        shift.default_quota = shift_in.default_quota
    if shift_in.is_active is not None:
        shift.is_active = shift_in.is_active

    db.commit()
    return shift


@router.delete("/{shift_id}")
def delete_shift(shift_id: int, db: Session = Depends(get_db)):
    shift = db.query(WorkShift).filter(WorkShift.id == shift_id).first()
    if not shift:
        raise HTTPException(status_code=404, detail="Смена не найдена")

    db.delete(shift)
    db.commit()
    return {"message": "Смена удалена"}
