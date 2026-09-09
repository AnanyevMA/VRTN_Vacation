from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Department, Employee
from backend.schemas import DepartmentCreate, DepartmentUpdate, DepartmentOut

router = APIRouter(prefix="/api/departments", tags=["Departments Management"])


@router.get("", response_model=List[DepartmentOut])
def list_departments(db: Session = Depends(get_db)):
    depts = db.query(Department).order_by(Department.id.asc()).all()
    results = []
    for d in depts:
        count = db.query(Employee).filter(Employee.department_id == d.id, Employee.is_active == True).count()
        d_out = DepartmentOut(
            id=d.id,
            name=d.name,
            code=d.code,
            manager_name=d.manager_name,
            description=d.description,
            employee_count=count,
        )
        results.append(d_out)
    return results


@router.post("", response_model=DepartmentOut)
def create_department(dept_in: DepartmentCreate, db: Session = Depends(get_db)):
    existing = db.query(Department).filter(Department.name == dept_in.name.strip()).first()
    if existing:
        raise HTTPException(status_code=400, detail="Подразделение с таким названием уже существует")

    dept = Department(
        name=dept_in.name.strip(),
        code=dept_in.code,
        manager_name=dept_in.manager_name,
        description=dept_in.description,
    )
    db.add(dept)
    db.commit()
    db.refresh(dept)
    return DepartmentOut(
        id=dept.id,
        name=dept.name,
        code=dept.code,
        manager_name=dept.manager_name,
        description=dept.description,
        employee_count=0,
    )


@router.put("/{dept_id}", response_model=DepartmentOut)
def update_department(dept_id: int, dept_in: DepartmentUpdate, db: Session = Depends(get_db)):
    dept = db.query(Department).filter(Department.id == dept_id).first()
    if not dept:
        raise HTTPException(status_code=404, detail="Подразделение не найдено")

    if dept_in.name is not None:
        dept.name = dept_in.name.strip()
    if dept_in.code is not None:
        dept.code = dept_in.code
    if dept_in.manager_name is not None:
        dept.manager_name = dept_in.manager_name
    if dept_in.description is not None:
        dept.description = dept_in.description

    db.commit()
    count = db.query(Employee).filter(Employee.department_id == dept.id, Employee.is_active == True).count()
    return DepartmentOut(
        id=dept.id,
        name=dept.name,
        code=dept.code,
        manager_name=dept.manager_name,
        description=dept.description,
        employee_count=count,
    )


@router.delete("/{dept_id}")
def delete_department(dept_id: int, db: Session = Depends(get_db)):
    dept = db.query(Department).filter(Department.id == dept_id).first()
    if not dept:
        raise HTTPException(status_code=404, detail="Подразделение не найдено")

    has_employees = db.query(Employee).filter(Employee.department_id == dept_id).first()
    if has_employees:
        raise HTTPException(status_code=400, detail="Нельзя удалить подразделение, в котором числятся сотрудники")

    db.delete(dept)
    db.commit()
    return {"message": "Подразделение удалено"}
