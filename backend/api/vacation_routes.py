from typing import List, Optional
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import VacationSlot, Employee, Department
from backend.schemas import (
    VacationSlotOut,
    VacationSlotCreate,
    OptimizeVacationRequest,
    OptimizeVacationResponse,
)
from backend.agents.solver_agent import SolverAgent
from backend.solver.optimizer import VacationOptimizer
from backend.auth import require_admin

router = APIRouter(prefix="/api/vacations", tags=["Vacation Slots & Scheduling"])


@router.get("", response_model=List[VacationSlotOut])
def list_vacations(
    year: Optional[int] = None,
    department_id: Optional[int] = None,
    role: Optional[str] = None,
    shift: Optional[str] = None,
    status: Optional[str] = None,
    employee_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    query = db.query(VacationSlot).join(Employee)

    if year:
        start_year = date(year, 1, 1)
        end_year = date(year, 12, 31)
        # Matches slots in this year
        query = query.filter(
            (VacationSlot.start_date <= end_year) & (VacationSlot.end_date >= start_year)
        )

    if department_id:
        query = query.filter(Employee.department_id == department_id)
    if role:
        query = query.filter(Employee.role == role)
    if shift:
        query = query.filter(Employee.shift == shift)
    if status:
        query = query.filter(VacationSlot.status == status)
    if employee_id:
        query = query.filter(VacationSlot.employee_id == employee_id)

    slots = query.order_by(VacationSlot.start_date.asc()).all()

    results = []
    for s in slots:
        emp = s.employee
        dept_name = emp.department.name if emp.department else ""
        slot_out = VacationSlotOut(
            id=s.id,
            employee_id=s.employee_id,
            start_date=s.start_date,
            end_date=s.end_date,
            days_count=s.days_count,
            is_primary_block=s.is_primary_block,
            status=s.status,
            conflict_reason=s.conflict_reason,
            created_at=s.created_at,
            updated_at=s.updated_at,
            employee_name=emp.full_name if emp else "",
            employee_role=emp.role if emp else "",
            employee_shift=emp.shift if emp else "",
            department_name=dept_name,
        )
        results.append(slot_out)

    return results


@router.post("/optimize", response_model=OptimizeVacationResponse)
def run_optimizer_tool(req: OptimizeVacationRequest, db: Session = Depends(get_db)):
    solver_agent = SolverAgent(db)
    slots_dicts = [{"start": s.start, "end": s.end} for s in req.requested_slots]
    result = solver_agent.run_vacation_optimizer(
        employee_id=req.employee_id,
        requested_slots=slots_dicts,
        window_search_days=req.window_search_days,
    )
    return OptimizeVacationResponse(**result)


@router.post("/batch-approve", dependencies=[Depends(require_admin)])
def batch_approve_vacations(year: Optional[int] = None, db: Session = Depends(get_db)):
    optimizer = VacationOptimizer(db)
    result = optimizer.batch_optimize_all_pending(year=year)
    return result


@router.put("/{slot_id}/status", dependencies=[Depends(require_admin)])
def update_slot_status(slot_id: int, status: str, db: Session = Depends(get_db)):
    slot = db.query(VacationSlot).filter(VacationSlot.id == slot_id).first()
    if not slot:
        raise HTTPException(status_code=404, detail="Слот отпуска не найден")

    status = status.upper()
    if status not in ["APPROVED", "REJECTED", "CONFLICT", "REQUESTED"]:
        raise HTTPException(status_code=400, detail="Неверный статус")

    slot.status = status
    if status == "APPROVED":
        slot.conflict_reason = None
    db.commit()
    return {"message": f"Статус слота изменен на {status}"}


@router.delete("/{slot_id}", dependencies=[Depends(require_admin)])
def delete_slot(slot_id: int, db: Session = Depends(get_db)):
    slot = db.query(VacationSlot).filter(VacationSlot.id == slot_id).first()
    if not slot:
        raise HTTPException(status_code=404, detail="Слот отпуска не найден")
    db.delete(slot)
    db.commit()
    return {"message": "Слот удален"}
