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
    IncompatiblePairCreate,
    IncompatiblePairOut,
    VacationLimitsConfig,
)
from backend.agents.manager_agent import ManagerAgent
from backend.auth import require_admin

router = APIRouter(prefix="/api/rules", tags=["Schedule Rules Engine"], dependencies=[Depends(require_admin)])


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
            min_gap_days=g.get("min_gap_days", 0) or 0,
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
        "min_gap_days": payload.min_gap_days,
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
        min_gap_days=payload.min_gap_days,
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


@router.get("/incompatible-pairs", response_model=List[IncompatiblePairOut])
def get_incompatible_pairs(db: Session = Depends(get_db)):
    """Returns list of personal 1-on-1 employee pairs that cannot have overlapping vacations."""
    rule = db.query(ScheduleRule).filter(ScheduleRule.rule_key == "personal_incompatible_pairs").first()
    if not rule:
        return []
    pairs = rule.parameters.get("pairs", [])

    all_emps = {e.id: e for e in db.query(Employee).all()}
    result = []
    for p in pairs:
        aid = p.get("employee_a_id")
        bid = p.get("employee_b_id")
        emp_a = all_emps.get(aid)
        emp_b = all_emps.get(bid)
        result.append(IncompatiblePairOut(
            id=str(p.get("id", "")),
            employee_a_id=aid,
            employee_b_id=bid,
            employee_a_name=emp_a.full_name if emp_a else f"Сотрудник #{aid}",
            employee_b_name=emp_b.full_name if emp_b else f"Сотрудник #{bid}",
            employee_a_role=emp_a.role if emp_a else "",
            employee_b_role=emp_b.role if emp_b else "",
            reason=p.get("reason"),
        ))
    return result


@router.post("/incompatible-pairs", response_model=IncompatiblePairOut, dependencies=[Depends(require_admin)])
def create_incompatible_pair(payload: IncompatiblePairCreate, db: Session = Depends(get_db)):
    """Creates a new personal 1-on-1 mutual-exclusion pair between two employees."""
    if payload.employee_a_id == payload.employee_b_id:
        raise HTTPException(status_code=400, detail="Нельзя выбрать одного и того же сотрудника дважды")

    emp_a = db.query(Employee).filter(Employee.id == payload.employee_a_id).first()
    emp_b = db.query(Employee).filter(Employee.id == payload.employee_b_id).first()
    if not emp_a or not emp_b:
        raise HTTPException(status_code=404, detail="Один из выбранных сотрудников не найден")

    rule = db.query(ScheduleRule).filter(ScheduleRule.rule_key == "personal_incompatible_pairs").first()
    if not rule:
        rule = ScheduleRule(
            rule_key="personal_incompatible_pairs",
            rule_type="HARD",
            parameters={"pairs": []},
            description="Персональные запреты пересечения отпусков (кто с кем лично не может уходить в отпуск одновременно).",
            is_active=True,
        )
        db.add(rule)
        db.flush()

    pairs = list(rule.parameters.get("pairs", []))
    target_set = {payload.employee_a_id, payload.employee_b_id}
    for existing in pairs:
        if {existing.get("employee_a_id"), existing.get("employee_b_id")} == target_set:
            raise HTTPException(status_code=400, detail="Персональный запрет для этой пары сотрудников уже существует")

    new_id = str(uuid.uuid4())[:8]
    reason_str = (payload.reason or "").strip() or "Персональный запрет пересечения (напарники)"
    new_pair = {
        "id": new_id,
        "employee_a_id": payload.employee_a_id,
        "employee_b_id": payload.employee_b_id,
        "reason": reason_str,
    }
    pairs.append(new_pair)
    rule.parameters = {"pairs": pairs}
    db.commit()

    return IncompatiblePairOut(
        id=new_id,
        employee_a_id=payload.employee_a_id,
        employee_b_id=payload.employee_b_id,
        employee_a_name=emp_a.full_name,
        employee_b_name=emp_b.full_name,
        employee_a_role=emp_a.role,
        employee_b_role=emp_b.role,
        reason=reason_str,
    )


@router.delete("/incompatible-pairs/{pair_id}", dependencies=[Depends(require_admin)])
def delete_incompatible_pair(pair_id: str, db: Session = Depends(get_db)):
    """Deletes a personal 1-on-1 mutual-exclusion pair by id."""
    rule = db.query(ScheduleRule).filter(ScheduleRule.rule_key == "personal_incompatible_pairs").first()
    if not rule:
        raise HTTPException(status_code=404, detail="Правило не найдено")

    pairs = [p for p in rule.parameters.get("pairs", []) if str(p.get("id")) != str(pair_id)]
    rule.parameters = {"pairs": pairs}
    db.commit()
    return {"success": True, "message": "Персональный запрет пересечения удален"}


@router.get("/vacation-limits", response_model=VacationLimitsConfig)
def get_vacation_limits(db: Session = Depends(get_db)):
    """Returns global factory vacation duration & seasonal limits."""
    rule = db.query(ScheduleRule).filter(ScheduleRule.rule_key == "vacation_limits").first()
    if not rule or not isinstance(rule.parameters, dict):
        return VacationLimitsConfig()
    p = rule.parameters
    return VacationLimitsConfig(
        max_single_slot_days=p.get("max_single_slot_days", 21),
        max_summer_days=p.get("max_summer_days", 21),
        summer_start_month=p.get("summer_start_month", 6),
        summer_end_month=p.get("summer_end_month", 9),
        min_total_year_days=p.get("min_total_year_days", 14),
        allow_flexible_total=bool(p.get("allow_flexible_total", True)),
        is_active=bool(rule.is_active),
    )


@router.put("/vacation-limits", response_model=VacationLimitsConfig, dependencies=[Depends(require_admin)])
def update_vacation_limits(payload: VacationLimitsConfig, db: Session = Depends(get_db)):
    """Updates global factory vacation duration & seasonal limits."""
    rule = db.query(ScheduleRule).filter(ScheduleRule.rule_key == "vacation_limits").first()
    params = {
        "max_single_slot_days": payload.max_single_slot_days,
        "max_summer_days": payload.max_summer_days,
        "summer_start_month": payload.summer_start_month,
        "summer_end_month": payload.summer_end_month,
        "min_total_year_days": payload.min_total_year_days,
        "allow_flexible_total": payload.allow_flexible_total,
    }
    if not rule:
        rule = ScheduleRule(
            rule_key="vacation_limits",
            rule_type="HARD",
            parameters=params,
            description="Лимиты длительности и сезонности отпусков (макс. 21 день подряд, макс. 21 день с июня по сентябрь, мин. 14 дней в год).",
            is_active=payload.is_active,
        )
        db.add(rule)
    else:
        rule.parameters = params
        rule.is_active = payload.is_active
    db.commit()
    return payload

