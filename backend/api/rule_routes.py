import uuid
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import ScheduleRule, JobRole, WorkShift, Employee
from backend.schemas import (
    ScheduleRuleOut,
    ScheduleRuleCreate,
    ScheduleRuleUpdate,
    UpdateRulesAndRosterRequest,
    UpdateRulesAndRosterResponse,
    IncompatibleGroupCreate,
    IncompatibleGroupOut,
)
from backend.agents.manager_agent import ManagerAgent
from backend.auth import require_admin

router = APIRouter(prefix="/api/rules", tags=["Schedule Rules Engine"])


@router.get("", response_model=List[ScheduleRuleOut])
def get_rules(db: Session = Depends(get_db)):
    return db.query(ScheduleRule).order_by(ScheduleRule.id.asc()).all()


@router.post("/action", response_model=UpdateRulesAndRosterResponse, dependencies=[Depends(require_admin)])
def execute_rule_or_roster_action(req: UpdateRulesAndRosterRequest, db: Session = Depends(get_db)):
    agent = ManagerAgent(db)
    res = agent.update_rules_and_roster(action=req.action, payload=req.payload)
    return UpdateRulesAndRosterResponse(**res)


@router.put("/role-quotas", dependencies=[Depends(require_admin)])
def update_role_quotas(payload: Dict[str, int], db: Session = Depends(get_db)):
    # Update JobRole.default_quota for all matching roles
    for role_name, quota in payload.items():
        role = db.query(JobRole).filter(JobRole.name == role_name).first()
        if role:
            role.default_quota = quota

    rule = db.query(ScheduleRule).filter(ScheduleRule.rule_key == "max_concurrent_roles").first()
    if not rule:
        rule = ScheduleRule(
            rule_key="max_concurrent_roles",
            rule_type="HARD",
            parameters={"quotas": payload},
            description="Квоты одновременных отсутствий сотрудников критических ролей.",
            is_active=True,
        )
        db.add(rule)
    else:
        rule.parameters = {"quotas": payload}
    db.commit()
    return {"success": True, "message": "Квоты ролей успешно обновлены в единой базе"}


@router.put("/blackouts", dependencies=[Depends(require_admin)])
def update_blackout_periods(periods: List[Dict[str, Any]], db: Session = Depends(get_db)):
    agent = ManagerAgent(db)
    res = agent.update_rules_and_roster("UPDATE_BLACKOUTS", {"periods": periods})
    return res


@router.put("/{rule_id}/toggle", dependencies=[Depends(require_admin)])
def toggle_rule(rule_id: int, db: Session = Depends(get_db)):
    rule = db.query(ScheduleRule).filter(ScheduleRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Правило не найдено")
    rule.is_active = not rule.is_active
    db.commit()
    return {"message": f"Статус правила {rule.rule_key} изменен на {'активно' if rule.is_active else 'выключено'}", "is_active": rule.is_active}


@router.put("/shift-quotas", dependencies=[Depends(require_admin)])
def update_shift_quotas(payload: Dict[str, int], db: Session = Depends(get_db)):
    """Update concurrency quotas for work shifts across WorkShift table and ScheduleRule."""
    for shift_name, quota in payload.items():
        shift = db.query(WorkShift).filter(WorkShift.name == shift_name).first()
        if shift:
            shift.default_quota = quota

    rule = db.query(ScheduleRule).filter(ScheduleRule.rule_key == "max_concurrent_shifts").first()
    if not rule:
        rule = ScheduleRule(
            rule_key="max_concurrent_shifts",
            rule_type="HARD",
            parameters={"quotas": payload},
            description="Квоты одновременных отпусков сотрудников одной смены.",
            is_active=True,
        )
        db.add(rule)
    else:
        rule.parameters = {"quotas": payload}
    db.commit()
    return {"success": True, "message": "Квоты смен успешно обновлены в единой базе"}


@router.get("/incompatible-groups", response_model=List[IncompatibleGroupOut])
def get_incompatible_groups(db: Session = Depends(get_db)):
    """Returns list of employee groups that cannot have overlapping vacations."""
    rule = db.query(ScheduleRule).filter(ScheduleRule.rule_key == "incompatible_employee_groups").first()
    if not rule:
        return []
    groups = rule.parameters.get("groups", [])
    
    all_emps = {e.id: e.full_name for e in db.query(Employee).all()}
    result = []
    for g in groups:
        e_names = [all_emps.get(eid, f"Сотрудник #{eid}") for eid in g.get("employee_ids", [])]
        result.append(IncompatibleGroupOut(
            id=str(g.get("id", "")),
            name=g.get("name", "Группа непересечения"),
            employee_ids=g.get("employee_ids", []),
            employee_names=e_names,
            max_concurrent=g.get("max_concurrent", 1),
            reason=g.get("reason"),
        ))
    return result


@router.post("/incompatible-groups", response_model=IncompatibleGroupOut, dependencies=[Depends(require_admin)])
def create_incompatible_group(payload: IncompatibleGroupCreate, db: Session = Depends(get_db)):
    """Creates a new employee mutual-exclusion group."""
    if len(payload.employee_ids) < 2:
        raise HTTPException(status_code=400, detail="Группа должна содержать минимум 2 сотрудников")

    rule = db.query(ScheduleRule).filter(ScheduleRule.rule_key == "incompatible_employee_groups").first()
    if not rule:
        rule = ScheduleRule(
            rule_key="incompatible_employee_groups",
            rule_type="HARD",
            parameters={"groups": []},
            description="Группы сотрудников, чьи отпуска не должны пересекаться.",
            is_active=True,
        )
        db.add(rule)
        db.flush()

    groups = list(rule.parameters.get("groups", []))
    new_id = str(uuid.uuid4())[:8]
    new_group = {
        "id": new_id,
        "name": payload.name,
        "employee_ids": payload.employee_ids,
        "max_concurrent": payload.max_concurrent,
        "reason": payload.reason or "Взаимозаменяемые сотрудники",
    }
    groups.append(new_group)
    rule.parameters = {"groups": groups}
    db.commit()

    all_emps = {e.id: e.full_name for e in db.query(Employee).all()}
    e_names = [all_emps.get(eid, f"Сотрудник #{eid}") for eid in payload.employee_ids]
    return IncompatibleGroupOut(
        id=new_id,
        name=payload.name,
        employee_ids=payload.employee_ids,
        employee_names=e_names,
        max_concurrent=payload.max_concurrent,
        reason=payload.reason,
    )


@router.delete("/incompatible-groups/{group_id}", dependencies=[Depends(require_admin)])
def delete_incompatible_group(group_id: str, db: Session = Depends(get_db)):
    """Deletes an employee mutual-exclusion group by id."""
    rule = db.query(ScheduleRule).filter(ScheduleRule.rule_key == "incompatible_employee_groups").first()
    if not rule:
        raise HTTPException(status_code=404, detail="Правило не найдено")

    groups = [g for g in rule.parameters.get("groups", []) if str(g.get("id")) != str(group_id)]
    rule.parameters = {"groups": groups}
    db.commit()
    return {"success": True, "message": "Группа непересечения удалена"}

