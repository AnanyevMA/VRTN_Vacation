import os
import secrets
from datetime import date, timedelta
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import Employee, BotAdmin, Department, WorkShift, VacationSlot, EmployeeDraft, ScheduleRule
from backend.agents.intake_agent import IntakeAgent
from backend.agents.manager_agent import ManagerAgent
from backend.solver.optimizer import VacationOptimizer
from backend.solver.nlp_date_parser import calculate_slot_days
from backend.services.max_bot_client import max_bot_client

router = APIRouter(prefix="/api/miniapp", tags=["MAX Mini App"])


class MiniAppConsentIn(BaseModel):
    max_user_id: str = Field(..., min_length=1, max_length=128)
    accepted: bool = True


class MiniAppAddSlotIn(BaseModel):
    max_user_id: str = Field(..., min_length=1, max_length=128)
    start_date: date
    end_date: date


class MiniAppSelectAlternativeIn(BaseModel):
    max_user_id: str = Field(..., min_length=1, max_length=128)
    slots: List[Dict[str, str]]
    replace_draft: bool = True
    edit_index: Optional[int] = None


class MiniAppUpdateDraftSlotIn(BaseModel):
    max_user_id: str = Field(..., min_length=1, max_length=128)
    index: int = Field(..., ge=0)
    start_date: date
    end_date: date


class MiniAppRecallSlotsIn(BaseModel):
    max_user_id: str = Field(..., min_length=1, max_length=128)
    year: int = Field(2026, ge=2025, le=2035)
    slot_id: Optional[int] = None


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
    year: Optional[int] = Query(None, ge=2025, le=2035),
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

    if year is None:
        # Auto-select year where employee or company has planned slots (default 2026)
        year = 2026
        if employee:
            emp_slot = (
                db.query(VacationSlot)
                .filter(VacationSlot.employee_id == employee.id)
                .order_by(VacationSlot.start_date.desc())
                .first()
            )
            if emp_slot and emp_slot.start_date.year in (2026, 2027):
                year = emp_slot.start_date.year
        else:
            any_slot = db.query(VacationSlot).order_by(VacationSlot.start_date.desc()).first()
            if any_slot and any_slot.start_date.year in (2026, 2027):
                year = any_slot.start_date.year

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
    my_restrictions = []
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

        # Collect personal non-overlapping partners (1-on-1 pairs + mutual-exclusion groups)
        emp_by_id = {e.id: e for e in all_employees}
        pair_rule = db.query(ScheduleRule).filter(
            ScheduleRule.rule_key == "personal_incompatible_pairs",
            ScheduleRule.is_active == True,
        ).first()
        if pair_rule and isinstance(pair_rule.parameters, dict):
            for p in pair_rule.parameters.get("pairs", []):
                aid, bid = p.get("employee_a_id"), p.get("employee_b_id")
                partner_id = bid if aid == employee.id else (aid if bid == employee.id else None)
                if partner_id and partner_id in emp_by_id:
                    partner = emp_by_id[partner_id]
                    my_restrictions.append({
                        "partner_id": partner.id,
                        "partner_name": partner.full_name,
                        "partner_role": partner.role,
                        "reason": p.get("reason") or "Персональный запрет пересечения",
                        "slots": slots_by_emp.get(partner.id, []),
                    })

        group_rule = db.query(ScheduleRule).filter(
            ScheduleRule.rule_key == "incompatible_employee_groups",
            ScheduleRule.is_active == True,
        ).first()
        if group_rule and isinstance(group_rule.parameters, dict):
            seen_pids = {r["partner_id"] for r in my_restrictions}
            for g in group_rule.parameters.get("groups", []):
                eids = g.get("employee_ids", [])
                if employee.id in eids:
                    for pid in eids:
                        if pid != employee.id and pid not in seen_pids and pid in emp_by_id:
                            partner = emp_by_id[pid]
                            seen_pids.add(pid)
                            my_restrictions.append({
                                "partner_id": partner.id,
                                "partner_name": partner.full_name,
                                "partner_role": partner.role,
                                "reason": g.get("name") or "Группа непересечения",
                                "slots": slots_by_emp.get(partner.id, []),
                            })

        scheduled_days = sum(s["days_count"] for s in my_slots)
        draft_days = sum(d["days"] for d in draft_slots)
        total_days = employee.total_vacation_days or 36
        has_14_block = any(s["days_count"] >= 14 for s in my_slots) or any(d["days"] >= 14 for d in draft_slots)
        role_lower = (employee.role or "").lower()
        is_shift_lead = any(k in role_lower for k in ("мастер", "технолог", "руковод", "начальник", "старш"))

        emp_data = {
            "id": employee.id,
            "full_name": employee.full_name,
            "role": employee.role,
            "is_shift_lead": is_shift_lead,
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
        summary = mgr.get_dashboard_summary()
        emp_map = {e.id: e for e in all_employees}
        pending_slots_out = []
        for sl in all_year_slots:
            if sl.status in ("REQUESTED", "REVISED", "PENDING", "CONFLICT", "NEEDS_APPROVAL"):
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
                        "conflict_reason": sl.conflict_reason,
                    })
        summary["pending_slots_count"] = len([s for s in pending_slots_out if s["status"] != "CONFLICT"])
        summary["conflict_slots_count"] = len([s for s in pending_slots_out if s["status"] == "CONFLICT"])

        # Sort employees_access so PENDING access requests appear first
        access_order = {"PENDING": 0, "APPROVED": 1, "BLOCKED": 2}
        sorted_emps_for_access = sorted(
            all_employees,
            key=lambda x: (access_order.get(getattr(x, "bot_access", "APPROVED") or "APPROVED", 1), x.full_name),
        )
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
            for e in sorted_emps_for_access
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
        "my_restrictions": my_restrictions,
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

    # Immediate single-slot CSP pre-check so employee sees conflicts right away
    optimizer = VacationOptimizer(db)
    conflict_reason = optimizer._get_first_conflict_reason(emp, data.start_date, data.end_date)
    if conflict_reason:
        dur = calculate_slot_days(data.start_date, data.end_date)
        single_alts = []
        cand_after = optimizer._find_candidate_slot(emp, data.start_date, dur, search_direction=1, max_days=60)
        if cand_after:
            single_alts.append({
                "option": 1,
                "slots": [{"start": cand_after[0].isoformat(), "end": cand_after[1].isoformat()}],
                "total_days": dur,
                "reason": "Ближайшее свободное окно после выбранных дат",
                "replace_draft": False,
            })
        cand_before = optimizer._find_candidate_slot(emp, data.start_date, dur, search_direction=-1, max_days=60)
        if cand_before and (not cand_after or cand_before[0] != cand_after[0]):
            single_alts.append({
                "option": len(single_alts) + 1,
                "slots": [{"start": cand_before[0].isoformat(), "end": cand_before[1].isoformat()}],
                "total_days": dur,
                "reason": "Свободное окно перед выбранными датами",
                "replace_draft": False,
            })
        cand_shift = optimizer._find_candidate_slot(
            emp, data.start_date + timedelta(days=21), dur, search_direction=1, max_days=60
        )
        if cand_shift and all(cand_shift[0].isoformat() != a["slots"][0]["start"] for a in single_alts):
            single_alts.append({
                "option": len(single_alts) + 1,
                "slots": [{"start": cand_shift[0].isoformat(), "end": cand_shift[1].isoformat()}],
                "total_days": dur,
                "reason": "Разгруженный период без пересечений со сменой",
                "replace_draft": False,
            })

        s_str = data.start_date.strftime("%d.%m.%Y")
        e_str = data.end_date.strftime("%d.%m.%Y")
        full_conflict_msg = f"Период {s_str} – {e_str} недоступен: {conflict_reason}"
        return {
            "sender": "AGENT",
            "text": full_conflict_msg,
            "payload": {
                "action": "OFFER_ALTERNATIVES",
                "conflicts": [full_conflict_msg],
                "violations": [full_conflict_msg],
                "suggested_alternatives": single_alts,
            },
        }

    agent = IntakeAgent(db)
    msg_text = f"с {data.start_date.strftime('%d.%m.%Y')} по {data.end_date.strftime('%d.%m.%Y')}"
    res = agent.process_message(emp.id, msg_text, uid)
    return res


@router.post("/draft/select-alternative")
def select_miniapp_alternative(data: MiniAppSelectAlternativeIn, db: Session = Depends(get_db)):
    uid = data.max_user_id.strip()
    emp = db.query(Employee).filter(Employee.max_user_id == uid).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Профиль сотрудника не найден")
    if not getattr(emp, "consent_152fz", False):
        raise HTTPException(status_code=403, detail="Необходимо дать согласие на обработку ПДн (152-ФЗ)")

    if not data.slots:
        raise HTTPException(status_code=400, detail="Пустой список периодов")

    # If editing a specific index in draft via alternative button
    if data.edit_index is not None and len(data.slots) == 1:
        st = date.fromisoformat(data.slots[0]["start"])
        en = date.fromisoformat(data.slots[0]["end"])
        return update_miniapp_draft_slot(
            MiniAppUpdateDraftSlotIn(
                max_user_id=uid,
                index=data.edit_index,
                start_date=st,
                end_date=en,
            ),
            db=db,
        )

    # If adding a single period, pass its dates through IntakeAgent
    if not data.replace_draft and len(data.slots) == 1:
        st = date.fromisoformat(data.slots[0]["start"])
        en = date.fromisoformat(data.slots[0]["end"])
        agent = IntakeAgent(db)
        msg_text = f"с {st.strftime('%d.%m.%Y')} по {en.strftime('%d.%m.%Y')}"
        return agent.process_message(emp.id, msg_text, uid)

    # Full schedule alternative replacement
    draft = db.query(EmployeeDraft).filter(EmployeeDraft.employee_id == emp.id).first()
    if not draft:
        draft = EmployeeDraft(employee_id=emp.id, target_year=2026, slots=[], status="DRAFTING")
        db.add(draft)
        db.flush()

    new_slots = []
    for s in data.slots:
        st = date.fromisoformat(s["start"])
        en = date.fromisoformat(s["end"])
        new_slots.append({
            "start": st.isoformat(),
            "end": en.isoformat(),
            "days": calculate_slot_days(st, en),
        })

    target_year = date.fromisoformat(new_slots[0]["start"]).year
    approved_days = sum(
        s.days_count
        for s in db.query(VacationSlot)
        .filter(
            VacationSlot.employee_id == emp.id,
            VacationSlot.status == "APPROVED",
            VacationSlot.start_date >= date(target_year, 1, 1),
            VacationSlot.start_date <= date(target_year, 12, 31),
        )
        .all()
    )
    total_days = sum(x["days"] for x in new_slots) + approved_days
    expected_days = emp.total_vacation_days or 36
    draft.slots = new_slots
    draft.target_year = target_year
    draft.status = "AWAITING_CONFIRMATION" if total_days == expected_days else "DRAFTING"
    db.commit()
    return {
        "sender": "AGENT",
        "text": "Выбранный вариант добавлен в черновик!",
        "payload": {
            "action": draft.status,
            "draft_slots": new_slots,
        },
    }


@router.post("/draft/update")
def update_miniapp_draft_slot(data: MiniAppUpdateDraftSlotIn, db: Session = Depends(get_db)):
    uid = data.max_user_id.strip()
    emp = db.query(Employee).filter(Employee.max_user_id == uid).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Профиль сотрудника не найден")
    if not getattr(emp, "consent_152fz", False):
        raise HTTPException(status_code=403, detail="Необходимо дать согласие на обработку ПДн (152-ФЗ)")
    if data.end_date < data.start_date:
        raise HTTPException(status_code=400, detail="Дата окончания не может быть раньше даты начала")

    draft = db.query(EmployeeDraft).filter(EmployeeDraft.employee_id == emp.id).first()
    if not draft or not isinstance(draft.slots, list) or not (0 <= data.index < len(draft.slots)):
        raise HTTPException(status_code=404, detail="Редактируемый период не найден в черновике")

    target_year = data.start_date.year
    approved_slots = (
        db.query(VacationSlot)
        .filter(
            VacationSlot.employee_id == emp.id,
            VacationSlot.status == "APPROVED",
            VacationSlot.start_date >= date(target_year, 1, 1),
            VacationSlot.start_date <= date(target_year, 12, 31),
        )
        .all()
    )

    # 1. Check self-overlap with OTHER slots in draft or already APPROVED slots
    for ap in approved_slots:
        if max(data.start_date, ap.start_date) <= min(data.end_date, ap.end_date):
            raise HTTPException(
                status_code=400,
                detail=f"Новые даты пересекаются с вашим уже утвержденным отпуском ({ap.start_date.strftime('%d.%m.%Y')}–{ap.end_date.strftime('%d.%m.%Y')})",
            )

    for idx, s in enumerate(draft.slots):
        if idx == data.index:
            continue
        s_st = date.fromisoformat(s["start"])
        s_en = date.fromisoformat(s["end"])
        if max(data.start_date, s_st) <= min(data.end_date, s_en):
            raise HTTPException(
                status_code=400,
                detail=f"Новые даты накладываются на другой период в вашем черновике ({s_st.strftime('%d.%m.%Y')}–{s_en.strftime('%d.%m.%Y')})",
            )

    # 2. Check CSP solver rules (blackouts, role/shift quotas, personal incompatible pairs)
    optimizer = VacationOptimizer(db)
    conflict_reason = optimizer._get_first_conflict_reason(emp, data.start_date, data.end_date)
    if conflict_reason:
        dur = calculate_slot_days(data.start_date, data.end_date)
        single_alts = []
        cand_after = optimizer._find_candidate_slot(emp, data.start_date, dur, search_direction=1, max_days=60)
        if cand_after:
            single_alts.append({
                "option": 1,
                "slots": [{"start": cand_after[0].isoformat(), "end": cand_after[1].isoformat()}],
                "total_days": dur,
                "reason": "Ближайшее свободное окно после выбранных дат",
                "replace_draft": False,
                "edit_index": data.index,
            })
        cand_before = optimizer._find_candidate_slot(emp, data.start_date, dur, search_direction=-1, max_days=60)
        if cand_before and (not cand_after or cand_before[0] != cand_after[0]):
            single_alts.append({
                "option": len(single_alts) + 1,
                "slots": [{"start": cand_before[0].isoformat(), "end": cand_before[1].isoformat()}],
                "total_days": dur,
                "reason": "Свободное окно перед выбранными датами",
                "replace_draft": False,
                "edit_index": data.index,
            })
        s_str = data.start_date.strftime("%d.%m.%Y")
        e_str = data.end_date.strftime("%d.%m.%Y")
        full_conflict_msg = f"Период {s_str} – {e_str} недоступен: {conflict_reason}"
        return {
            "sender": "AGENT",
            "text": full_conflict_msg,
            "payload": {
                "action": "OFFER_ALTERNATIVES",
                "conflicts": [full_conflict_msg],
                "violations": [full_conflict_msg],
                "suggested_alternatives": single_alts,
                "draft_slots": draft.slots,
            },
        }

    # 3. Update the slot in place
    new_dur = calculate_slot_days(data.start_date, data.end_date)
    slots_copy = list(draft.slots)
    slots_copy[data.index] = {
        "start": data.start_date.isoformat(),
        "end": data.end_date.isoformat(),
        "days": new_dur,
    }
    expected_days = emp.total_vacation_days or 36
    approved_days = sum(s.days_count for s in approved_slots)
    total_days = approved_days + sum(s["days"] for s in slots_copy)

    if total_days > expected_days:
        raise HTTPException(
            status_code=400,
            detail=f"Превышен лимит дней отпуска: получилось {total_days} дн. при норме {expected_days} дн. (лишних: {total_days - expected_days} дн.)",
        )

    has_14 = any(s.days_count >= 14 for s in approved_slots) or any(s["days"] >= 14 for s in slots_copy)
    draft.slots = slots_copy
    draft.target_year = target_year
    draft.status = "AWAITING_CONFIRMATION" if (total_days == expected_days and has_14) else "DRAFTING"
    db.commit()

    return {
        "sender": "AGENT",
        "text": "Даты периода успешно обновлены в черновике!",
        "payload": {
            "action": draft.status,
            "draft_slots": draft.slots,
        },
    }


@router.post("/slots/recall")
def recall_submitted_slots_to_draft(data: MiniAppRecallSlotsIn, db: Session = Depends(get_db)):
    """Moves unapproved (REQUESTED / CONFLICT / REVISED) slots back into the employee's draft for easy editing."""
    uid = data.max_user_id.strip()
    emp = db.query(Employee).filter(Employee.max_user_id == uid).first()
    if not emp:
        raise HTTPException(status_code=404, detail="Профиль сотрудника не найден")

    q = db.query(VacationSlot).filter(
        VacationSlot.employee_id == emp.id,
        VacationSlot.status.in_(["REQUESTED", "CONFLICT", "REVISED", "PENDING", "NEEDS_APPROVAL"]),
        VacationSlot.start_date >= date(data.year, 1, 1),
        VacationSlot.start_date <= date(data.year, 12, 31),
    )
    if data.slot_id:
        q = q.filter(VacationSlot.id == data.slot_id)

    recalled_slots = q.order_by(VacationSlot.start_date.asc()).all()
    if not recalled_slots:
        raise HTTPException(status_code=400, detail="Нет отправленных периодов на согласовании для возврата в черновик")

    draft = db.query(EmployeeDraft).filter(EmployeeDraft.employee_id == emp.id).first()
    if not draft:
        draft = EmployeeDraft(employee_id=emp.id, target_year=data.year, slots=[], status="DRAFTING")
        db.add(draft)
        db.flush()

    existing_draft = list(draft.slots or []) if draft.status != "COMMITTED" else []
    for sl in recalled_slots:
        st_iso = sl.start_date.isoformat()
        en_iso = sl.end_date.isoformat()
        if not any(d["start"] == st_iso and d["end"] == en_iso for d in existing_draft):
            existing_draft.append({
                "start": st_iso,
                "end": en_iso,
                "days": sl.days_count,
            })
        db.delete(sl)

    existing_draft.sort(key=lambda x: x["start"])
    approved_slots = (
        db.query(VacationSlot)
        .filter(
            VacationSlot.employee_id == emp.id,
            VacationSlot.status == "APPROVED",
            VacationSlot.start_date >= date(data.year, 1, 1),
            VacationSlot.start_date <= date(data.year, 12, 31),
        )
        .all()
    )
    expected_days = emp.total_vacation_days or 36
    total_days = sum(s.days_count for s in approved_slots) + sum(d["days"] for d in existing_draft)
    has_14 = any(s.days_count >= 14 for s in approved_slots) or any(d["days"] >= 14 for d in existing_draft)

    draft.slots = existing_draft
    draft.target_year = data.year
    draft.status = "AWAITING_CONFIRMATION" if (total_days == expected_days and has_14) else "DRAFTING"
    db.commit()

    return {
        "status": "ok",
        "message": "Периоды возвращены в черновик. Нажмите «✏️ Изменить» у нужного периода, чтобы поправить даты.",
        "draft_slots": draft.slots,
    }


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
        draft.status = "DRAFTING"
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
    result = optimizer.batch_optimize_all_pending(year=data.year)
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
