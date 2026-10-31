from typing import List, Optional, Dict
from collections import defaultdict
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from backend.database import get_db
from backend.models import Employee, Department, VacationSlot
from backend.schemas import EmployeeCreate, EmployeeUpdate, EmployeeOut
from backend.agents.manager_agent import ManagerAgent
from backend.auth import require_admin

router = APIRouter(prefix="/api/employees", tags=["Employee Management"], dependencies=[Depends(require_admin)])


@router.get("", response_model=List[EmployeeOut])
def list_employees(
    department_id: Optional[int] = None,
    role: Optional[str] = None,
    shift: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(Employee).options(joinedload(Employee.department))
    if department_id:
        query = query.filter(Employee.department_id == department_id)
    if role:
        query = query.filter(Employee.role == role)
    if shift:
        query = query.filter(Employee.shift == shift)
    if search:
        s = f"%{search}%"
        query = query.filter((Employee.full_name.ilike(s)) | (Employee.phone.ilike(s)) | (Employee.role.ilike(s)))

    employees = query.order_by(Employee.id.asc()).all()
    if not employees:
        return []

    emp_ids = [e.id for e in employees]
    all_slots = db.query(VacationSlot).filter(VacationSlot.employee_id.in_(emp_ids)).all()
    slots_by_emp: Dict[int, List[VacationSlot]] = defaultdict(list)
    for sl in all_slots:
        slots_by_emp[sl.employee_id].append(sl)

    results = []
    for emp in employees:
        slots = slots_by_emp.get(emp.id, [])
        scheduled_days = sum(s.days_count for s in slots)
        total = emp.total_vacation_days or 36
        rem = max(0, total - scheduled_days)

        if not slots:
            status_summary = "NOT_SUBMITTED"
        elif any(s.status == "CONFLICT" for s in slots):
            status_summary = "CONFLICT"
        elif all(s.status == "APPROVED" for s in slots):
            status_summary = "APPROVED"
        else:
            status_summary = "PENDING"


        emp_out = EmployeeOut(
            id=emp.id,
            phone=emp.phone,
            max_user_id=emp.max_user_id,
            full_name=emp.full_name,
            role=emp.role,
            department_id=emp.department_id,
            shift=emp.shift or "Смена 1 (дневная)",
            region=emp.region,
            total_vacation_days=total,
            seniority_years=emp.seniority_years,
            social_priority=emp.social_priority,
            bot_access=emp.bot_access or "APPROVED",
            is_active=emp.is_active,
            created_at=emp.created_at,
            department_name=emp.department.name if emp.department else "",
            scheduled_days=scheduled_days,
            remaining_days=rem,
            status_summary=status_summary,
        )
        results.append(emp_out)

    return results


@router.post("", response_model=EmployeeOut, dependencies=[Depends(require_admin)])
def create_employee(emp_in: EmployeeCreate, db: Session = Depends(get_db)):
    agent = ManagerAgent(db)
    res = agent.update_rules_and_roster("ADD_USER", emp_in.model_dump())
    if not res["success"]:
        raise HTTPException(status_code=400, detail=res["message"])

    emp = db.query(Employee).filter(Employee.id == res["data"]["id"]).first()
    return EmployeeOut(
        id=emp.id,
        phone=emp.phone,
        max_user_id=emp.max_user_id,
        full_name=emp.full_name,
        role=emp.role,
        department_id=emp.department_id,
        shift=emp.shift or "Смена 1 (дневная)",
        region=emp.region,
        total_vacation_days=emp.total_vacation_days,
        seniority_years=emp.seniority_years,
        social_priority=emp.social_priority,
        bot_access=emp.bot_access or "APPROVED",
        is_active=emp.is_active,
        created_at=emp.created_at,
        department_name=emp.department.name if emp.department else "",
        scheduled_days=0,
        remaining_days=emp.total_vacation_days,
        status_summary="NOT_SUBMITTED",
    )


@router.put("/{employee_id}", dependencies=[Depends(require_admin)])
def update_employee(employee_id: int, emp_up: EmployeeUpdate, db: Session = Depends(get_db)):
    agent = ManagerAgent(db)
    payload = emp_up.model_dump(exclude_unset=True)
    payload["employee_id"] = employee_id
    res = agent.update_rules_and_roster("UPDATE_USER", payload)
    if not res["success"]:
        raise HTTPException(status_code=400, detail=res["message"])
    return {"message": "Сотрудник успешно обновлен"}


@router.delete("/{employee_id}", dependencies=[Depends(require_admin)])
def delete_employee(employee_id: int, db: Session = Depends(get_db)):
    agent = ManagerAgent(db)
    res = agent.update_rules_and_roster("DELETE_USER", {"employee_id": employee_id})
    if not res["success"]:
        raise HTTPException(status_code=400, detail=res["message"])
    return {"message": "Сотрудник удален"}


@router.post("/sync-google-sheets", dependencies=[Depends(require_admin)])
def sync_google_sheets(db: Session = Depends(get_db)):
    from backend.google_sheets_importer import sync_real_employees_to_db
    res = sync_real_employees_to_db(db)
    return res


@router.put("/{employee_id}/bot-access", dependencies=[Depends(require_admin)])
def update_bot_access(employee_id: int, status: str = Query(..., pattern="^(APPROVED|PENDING|BLOCKED)$"), db: Session = Depends(get_db)):
    emp = db.query(Employee).filter(Employee.id == employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    emp.bot_access = status
    db.commit()
    return {"message": f"Статус доступа к боту для {emp.full_name} изменен на {status}", "bot_access": status}


