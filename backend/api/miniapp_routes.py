import os
import secrets
from datetime import date
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Employee, BotAdmin, Department, WorkShift, VacationSlot, EmployeeDraft, ScheduleRule
from backend.agents.intake_agent import IntakeAgent
from backend.agents.manager_agent import ManagerAgent
from backend.solver.optimizer import VacationOptimizer
from backend.services.max_bot_client import max_bot_client

router = APIRouter(prefix="/api/miniapp", tags=["MAX Mini App"])


class MiniAppConsentIn(BaseModel):
    max_user_id: str = Field(..., min_length=1, max_length=128)
    accepted: bool = True


class MiniAppAddSlotIn(BaseModel):
    max_user_id: str = Field(..., min_length=1, max_length=128)
    start_date: date
    end_date: date


class MiniAppRemoveDraftSlotIn(BaseModel):
    max_user_id: str = Field(..., min_length=1, max_length=128)
    index: Optional[int] = None
    reset_all: bool = False


class MiniAppSubmitDraftIn(BaseModel):
    max_user_id: str = Field(..., min_length=1, max_length=128)


class MiniAppAdminSlotActionIn(BaseModel):
    max_user_id: Optional[str] = Field(None, max_length=128)
    slot_id: int
    action: str = Field(..., pattern="^(APPROVE|REJECT)$")


class MiniAppAdminBatchIn(BaseModel):
    max_user_id: Optional[str] = Field(None, max_length=128)
    year: int = Field(2026, ge=2025, le=2035)


class MiniAppAdminAccessIn(BaseModel):
    max_user_id: Optional[str] = Field(None, max_length=128)
    employee_id: int
    bot_access: str = Field(..., pattern="^(APPROVED|PENDING|BLOCKED)$")


def _check_is_admin(db: Session, max_user_id: Optional[str], x_admin_token: Optional[str]) -> Optional[BotAdmin]:
    admin = None
    if max_user_id and max_user_id.strip():
        admin = (
            db.query(BotAdmin)
            .filter(BotAdmin.max_user_id == max_user_id.strip(), BotAdmin.is_active == True)
            .first()
        )
    if admin:
        return admin

    expected_key = os.getenv("ADMIN_API_KEY", "").strip()
    if expected_key and x_admin_token:
        if secrets.compare_digest(x_admin_token.strip().encode("utf-8"), expected_key.encode("utf-8")):
            # Return a virtual BotAdmin object or first active admin
            first_admin = db.query(BotAdmin).first()
            return first_admin or BotAdmin(id=0, full_name="Администратор", role_title="Руководитель", phone="")
    return None


@router.get("/context")
def get_miniapp_context(
    max_user_id: Optional[str] = Query(None, max_length=128),
    employee_id: Optional[int] = Query(None, ge=1),
    year: int = Query(2026, ge=2025, le=2035),
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    db: Session = Depends(get_db),
):
    uid = (max_user_id or "").strip()
    employee = db.query(Employee).filter(Employee.max_user_id == uid).first() if uid else None
    if not employee and employee_id:
        cand = db.query(Employee).filter(Employee.id == employee_id, Employee.is_active == True).first()
        if cand and cand.max_user_id:
            employee = cand
            uid = cand.max_user_id.strip()
    if not employee and not uid:
        linked_emps = (
            db.query(Employee)
            .filter(Employee.is_active == True, Employee.max_user_id.isnot(None), Employee.max_user_id != "")
            .all()
        )
        if len(linked_emps) == 1:
            employee = linked_emps[0]
            uid = employee.max_user_id.strip()

    admin = _check_is_admin(db, uid, x_admin_token)

    depts = {d.id: d.name for d in db.query(Department).all()}
    shifts_list = [
        {"id": s.id, "name": s.name, "code": s.code, "default_quota": getattr(s, "default_quota", 2) or 2}
        for s in db.query(WorkShift).all()
    ]
    depts_list = [{"id": d.id, "name": d.name, "code": d.code} for d in db.query(Department).all()]

    # Blackout periods
    blackouts = []
    b_rule = db.query(ScheduleRule).filter(ScheduleRule.rule_key == "blackout_periods", ScheduleRule.is_active == True).first()
    if b_rule and isinstance(b_rule.parameters, dict):
        blackouts = b_rule.parameters.get("periods", [])

    # Company-wide vacation schedule for the selected year (without PII phones)
    all_employees = db.query(Employee).filter(Employee.is_active == True).order_by(Employee.department_id, Employee.full_name).all()
    all_year_slots = (
        db.query(VacationSlot)
        .filter(
            VacationSlot.start_date >= date(year, 1, 1),
            VacationSlot.start_date <= date(year, 12, 31),
        )
        .order_by(VacationSlot.start_date.asc())
        .all()
    )
    slots_by_emp: Dict[int, List[Dict[str, Any]]] = {}
    for sl in all_year_slots:
        slots_by_emp.setdefault(sl.employee_id, []).append({
            "id": sl.id,
            "start_date": sl.start_date.isoformat(),
            "end_date": sl.end_date.isoformat(),
            "days_count": sl.days_count,
            "is_primary_block": sl.is_primary_block,
            "status": sl.status,
        })

    company_schedule = []
    for emp_item in all_employees:
        emp_slots = slots_by_emp.get(emp_item.id, [])
        company_schedule.append({
            "employee_id": emp_item.id,
            "full_name": emp_item.full_name,
            "role": emp_item.role,
            "department_id": emp_item.department_id,
            "department_name": depts.get(emp_item.department_id, "Цех"),
            "shift": emp_item.shift or "Смена 1",
            "total_vacation_days": emp_item.total_vacation_days or 36,
            "scheduled_days": sum(s["days_count"] for s in emp_slots),
            "slots": emp_slots,
        })

    # Employee personal section
    emp_data = None
    my_slots = []
    draft_slots = []
    if employee:
        my_slots = slots_by_emp.get(employee.id, [])
        draft = db.query(EmployeeDraft).filter(EmployeeDraft.employee_id == employee.id).first()
        if draft and draft.status != "COMMITTED" and isinstance(draft.slots, list):
            for ds in draft.slots:
                try:
                    s_d = date.fromisoformat(ds["start"])
                    e_d = date.fromisoformat(ds["end"])
                    if s_d.year == year:
                        draft_slots.append({
                            "start": ds["start"],
                            "end": ds["end"],
                            "days": (e_d - s_d).days + 1,
                        })
                except Exception:
                    continue

        scheduled_days = sum(s["days_count"] for s in my_slots)
        draft_days = sum(d["days"] for d in draft_slots)
        total_days = employee.total_vacation_days or 36
        has_14_block = any(s["days_count"] >= 14 for s in my_slots) or any(d["days"] >= 14 for d in draft_slots)

        emp_data = {
            "id": employee.id,
            "full_name": employee.full_name,
            "role": employee.role,
            "department_id": employee.department_id,
            "department_name": depts.get(employee.department_id, "Швейный цех"),
            "shift": employee.shift or "Смена 1",
            "total_vacation_days": total_days,
            "scheduled_days": scheduled_days,
            "draft_days": draft_days,
            "remaining_days": max(0, total_days - scheduled_days - draft_days),
            "has_14_day_block": has_14_block,
            "consent_152fz": bool(getattr(employee, "consent_152fz", False)),
            "bot_access": getattr(employee, "bot_access", "APPROVED") or "APPROVED",
        }

    # Admin section
    admin_section = None
    if admin:
        mgr = ManagerAgent(db)
        summary = mgr.get_dashboard_summary(year=year)
        emp_map = {e.id: e for e in all_employees}
        pending_slots_out = []
        for sl in all_year_slots:
            if sl.status in ("PENDING", "CONFLICT", "NEEDS_APPROVAL"):
                e_obj = emp_map.get(sl.employee_id)
                if e_obj:
                    pending_slots_out.append({
                        "slot_id": sl.id,
                        "employee_id": e_obj.id,
                        "full_name": e_obj.full_name,
                        "role": e_obj.role,
                        "department_name": depts.get(e_obj.department_id, "Цех"),
                        "shift": e_obj.shift or "Смена 1",
                        "start_date": sl.start_date.isoformat(),
                        "end_date": sl.end_date.isoformat(),
                        "days_count": sl.days_count,
                        "is_primary_block": sl.is_primary_block,
                        "status": sl.status,
                    })

        employees_access = [
            {
                "id": e.id,
                "full_name": e.full_name,
                "role": e.role,
                "department_name": depts.get(e.department_id, "Цех"),
                "shift": e.shift or "Смена 1",
                "bot_access": getattr(e, "bot_access", "APPROVED") or "APPROVED",
                "consent_152fz": bool(getattr(e, "consent_152fz", False)),
            }
            for e in all_employees
        ]

        admin_section = {
            "admin_name": admin.full_name,
            "role_title": admin.role_title,
            "stats": summary,
            "pending_slots": pending_slots_out,
            "employees_access": employees_access,
        }

    return {
        "authenticated": bool(employee or admin),
        "resolved_max_user_id": uid,
        "is_admin": bool(admin),
        "year": year,
        "employee": emp_data,
        "my_slots": my_slots,
        "draft_slots": draft_slots,
        "blackouts": blackouts,
        "departments": depts_list,
        "shifts": shifts_list,
        "company_schedule": company_schedule,
        "admin": admin_section,
    }


@router.post("/consent")
def submit_miniapp_consent(data: MiniAppConsentIn, db: Session = Depends(get_db)):
    uid = data.max_user_id.strip()
    emp = db.query(Employee).filter(Employee.max_user_id == uid).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Профиль сотрудника не привязан к вашему аккаунту MAX")
    emp.consent_152fz = bool(data.accepted)
    db.commit()
    return {"status": "ok", "consent_152fz": emp.consent_152fz}


@router.post("/draft/add")
def add_miniapp_draft_slot(data: MiniAppAddSlotIn, db: Session = Depends(get_db)):
    uid = data.max_user_id.strip()
    emp = db.query(Employee).filter(Employee.max_user_id == uid).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Профиль сотрудника не найден")
    if not getattr(emp, "consent_152fz", False):
        raise HTTPException(status_code=403, detail="Необходимо дать согласие на обработку ПДн (152-ФЗ)")
    if data.end_date < data.start_date:
        raise HTTPException(status_code=400, detail="Дата окончания не может быть раньше даты начала")

    agent = IntakeAgent(db)
    msg_text = f"с {data.start_date.strftime('%d.%m.%Y')} по {data.end_date.strftime('%d.%m.%Y')}"
    res = agent.process_message(emp.id, msg_text, uid)
    return res


@router.post("/draft/remove")
def remove_miniapp_draft_slot(data: MiniAppRemoveDraftSlotIn, db: Session = Depends(get_db)):
    uid = data.max_user_id.strip()
    emp = db.query(Employee).filter(Employee.max_user_id == uid).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Профиль сотрудника не найден")

    draft = db.query(EmployeeDraft).filter(EmployeeDraft.employee_id == emp.id).first()
    if not draft or not isinstance(draft.slots, list):
        return {"status": "ok", "draft_slots": []}

    if data.reset_all or data.index is None:
        draft.slots = []
        draft.status = "DRAFTING"
    else:
        slots_copy = list(draft.slots)
        if 0 <= data.index < len(slots_copy):
            slots_copy.pop(data.index)
        draft.slots = slots_copy
    db.commit()
    return {"status": "ok", "draft_slots": draft.slots}


@router.post("/draft/submit")
def submit_miniapp_draft(data: MiniAppSubmitDraftIn, db: Session = Depends(get_db)):
    uid = data.max_user_id.strip()
    emp = db.query(Employee).filter(Employee.max_user_id == uid).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Профиль сотрудника не найден")

    agent = IntakeAgent(db)
    res = agent.process_message(emp.id, "подтверждаю", uid)
    if res.get("text"):
        max_bot_client.send_message(uid, res["text"], chat_id=emp.max_chat_id)
    return res


@router.post("/admin/slot-action")
def admin_slot_action(
    data: MiniAppAdminSlotActionIn,
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    db: Session = Depends(get_db),
):
    admin = _check_is_admin(db, data.max_user_id, x_admin_token)
    if not admin:
        raise HTTPException(status_code=401, detail="Доступ только для администраторов бота")

    slot = db.query(VacationSlot).filter(VacationSlot.id == data.slot_id).first()
    if not slot:
        raise HTTPException(status_code=404, detail="Период отпуска не найден")

    emp = db.query(Employee).filter(Employee.id == slot.employee_id).first()
    s_str = slot.start_date.strftime("%d.%m.%Y")
    e_str = slot.end_date.strftime("%d.%m.%Y")
    days = slot.days_count

    if data.action == "APPROVE":
        slot.status = "APPROVED"
        db.commit()
        if emp and (emp.max_user_id or emp.max_chat_id):
            max_bot_client.send_message(
                emp.max_user_id or "",
                f"✅ Ваш период отпуска **с {s_str} по {e_str}** ({days} дн.) утвержден руководителем ({admin.full_name})!",
                chat_id=emp.max_chat_id,
            )
        return {"status": "ok", "new_status": "APPROVED"}
    else:
        db.delete(slot)
        db.commit()
        if emp and (emp.max_user_id or emp.max_chat_id):
            max_bot_client.send_message(
                emp.max_user_id or "",
                f"❌ Заявка на период **с {s_str} по {e_str}** ({days} дн.) отклонена руководителем ({admin.full_name}). Пожалуйста, выберите другие даты в мини-приложении или чате.",
                chat_id=emp.max_chat_id,
            )
        return {"status": "ok", "new_status": "REJECTED"}


@router.post("/admin/batch-approve")
def admin_batch_approve(
    data: MiniAppAdminBatchIn,
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    db: Session = Depends(get_db),
):
    admin = _check_is_admin(db, data.max_user_id, x_admin_token)
    if not admin:
        raise HTTPException(status_code=401, detail="Доступ только для администраторов бота")

    optimizer = VacationOptimizer(db)
    result = optimizer.batch_resolve_year(year=data.year)
    return result


@router.post("/admin/bot-access")
def admin_set_bot_access(
    data: MiniAppAdminAccessIn,
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    db: Session = Depends(get_db),
):
    admin = _check_is_admin(db, data.max_user_id, x_admin_token)
    if not admin:
        raise HTTPException(status_code=401, detail="Доступ только для администраторов бота")

    emp = db.query(Employee).filter(Employee.id == data.employee_id).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Сотрудник не найден")

    emp.bot_access = data.bot_access
    db.commit()

    if data.bot_access == "APPROVED" and (emp.max_user_id or emp.max_chat_id):
        max_bot_client.send_message(
            emp.max_user_id or "",
            f"✅ Администратор подтвердил ваш доступ к планировщику отпусков! Откройте мини-приложение или напишите желаемые даты.",
            chat_id=emp.max_chat_id,
        )
    return {"status": "ok", "employee_id": emp.id, "bot_access": emp.bot_access}
