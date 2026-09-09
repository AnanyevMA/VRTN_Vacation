from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import JobRole, Department, Employee, ScheduleRule
from backend.schemas import JobRoleCreate, JobRoleUpdate, JobRoleOut

router = APIRouter(prefix="/api/roles", tags=["Job Roles & Quotas Management"])


def _sync_schedule_rule_quotas(db: Session):
    """Synchronizes ScheduleRule 'max_concurrent_roles' with the JobRole table."""
    all_roles = db.query(JobRole).all()
    quotas_dict = {r.name: r.default_quota for r in all_roles}

    rule = db.query(ScheduleRule).filter(ScheduleRule.rule_key == "max_concurrent_roles").first()
    if not rule:
        rule = ScheduleRule(
            rule_key="max_concurrent_roles",
            rule_type="HARD",
            parameters={"quotas": quotas_dict},
            description="Квоты одновременных отсутствий сотрудников критических ролей.",
            is_active=True,
        )
        db.add(rule)
    else:
        rule.parameters = {"quotas": quotas_dict}
    db.commit()


@router.get("", response_model=List[JobRoleOut])
def list_roles(db: Session = Depends(get_db)):
    roles = db.query(JobRole).order_by(JobRole.id.asc()).all()
    results = []
    for r in roles:
        dept_name = r.department.name if r.department else "Все подразделения"
        r_out = JobRoleOut(
            id=r.id,
            name=r.name,
            department_id=r.department_id,
            description=r.description,
            default_quota=r.default_quota,
            is_critical=r.is_critical,
            department_name=dept_name,
        )
        results.append(r_out)
    return results


@router.post("", response_model=JobRoleOut)
def create_role(role_in: JobRoleCreate, db: Session = Depends(get_db)):
    existing = db.query(JobRole).filter(JobRole.name == role_in.name.strip()).first()
    if existing:
        raise HTTPException(status_code=400, detail="Должность с таким наименованием уже существует")

    role = JobRole(
        name=role_in.name.strip(),
        department_id=role_in.department_id,
        description=role_in.description,
        default_quota=role_in.default_quota,
        is_critical=role_in.is_critical,
    )
    db.add(role)
    db.commit()
    db.refresh(role)

    # Sync quotas in unified rule table
    _sync_schedule_rule_quotas(db)

    dept_name = role.department.name if role.department else ""
    return JobRoleOut(
        id=role.id,
        name=role.name,
        department_id=role.department_id,
        description=role.description,
        default_quota=role.default_quota,
        is_critical=role.is_critical,
        department_name=dept_name,
    )


@router.put("/{role_id}", response_model=JobRoleOut)
def update_role(role_id: int, role_in: JobRoleUpdate, db: Session = Depends(get_db)):
    role = db.query(JobRole).filter(JobRole.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Должность не найдена")

    old_name = role.name
    new_name = role_in.name.strip() if role_in.name is not None else old_name

    # If renamed, check unique and update employee records
    if new_name != old_name:
        existing = db.query(JobRole).filter(JobRole.name == new_name, JobRole.id != role_id).first()
        if existing:
            raise HTTPException(status_code=400, detail="Должность с таким наименованием уже существует")
        
        # Cascade rename to all employees holding this role
        employees_with_role = db.query(Employee).filter(Employee.role == old_name).all()
        for emp in employees_with_role:
            emp.role = new_name

    if role_in.name is not None:
        role.name = new_name
    if role_in.department_id is not None:
        role.department_id = role_in.department_id
    if role_in.description is not None:
        role.description = role_in.description
    if role_in.default_quota is not None:
        role.default_quota = role_in.default_quota
    if role_in.is_critical is not None:
        role.is_critical = role_in.is_critical

    db.commit()

    # Sync quotas in unified rule table
    _sync_schedule_rule_quotas(db)

    dept_name = role.department.name if role.department else ""
    return JobRoleOut(
        id=role.id,
        name=role.name,
        department_id=role.department_id,
        description=role.description,
        default_quota=role.default_quota,
        is_critical=role.is_critical,
        department_name=dept_name,
    )


@router.delete("/{role_id}")
def delete_role(role_id: int, db: Session = Depends(get_db)):
    role = db.query(JobRole).filter(JobRole.id == role_id).first()
    if not role:
        raise HTTPException(status_code=404, detail="Должность не найдена")

    # Check if any active employee holds this role
    assigned_emp = db.query(Employee).filter(Employee.role == role.name, Employee.is_active == True).first()
    if assigned_emp:
        raise HTTPException(
            status_code=400,
            detail=f"Нельзя удалить должность «{role.name}», так как она назначена сотруднику ({assigned_emp.full_name}). Сначала измените должность сотрудника.",
        )

    db.delete(role)
    db.commit()

    # Sync quotas in unified rule table (deletes the key from ScheduleRule)
    _sync_schedule_rule_quotas(db)

    return {"message": f"Должность «{role.name}» успешно удалена из системы"}
