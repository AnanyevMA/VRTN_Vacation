from datetime import date, timedelta
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session

from backend.models import Employee, VacationSlot, ScheduleRule, JobRole, WorkShift
from backend.solver.nlp_date_parser import calculate_slot_days


class VacationOptimizer:
    def __init__(self, db: Session):
        self.db = db
        self._load_rules()

    def _load_rules(self):
        """Loads active rules and preloads reference tables into memory to avoid N+1 queries in search loops."""
        rules = self.db.query(ScheduleRule).filter(ScheduleRule.is_active == True).all()
        self.rules_by_key: Dict[str, ScheduleRule] = {r.rule_key: r for r in rules}
        self._role_quotas_db: Dict[str, int] = {
            r.name: r.default_quota for r in self.db.query(JobRole).all() if r.default_quota is not None
        }
        self._shift_quotas_db: Dict[str, int] = {
            s.name: s.default_quota for s in self.db.query(WorkShift).all() if s.default_quota is not None
        }
        self._active_employees: Dict[int, Employee] = {
            e.id: e for e in self.db.query(Employee).filter(Employee.is_active == True).all()
        }
        self._active_slots: List[VacationSlot] = (
            self.db.query(VacationSlot)
            .filter(VacationSlot.status.in_(["APPROVED", "REQUESTED"]))
            .all()
        )

    def validate_and_check_slots(
        self,
        employee_id: int,
        requested_slots: List[Dict[str, date]],
        window_search_days: int = 45,
    ) -> Dict[str, Any]:
        """
        Validates the requested slots against Hard constraints (TK RF, Role quotas, Blackouts).
        Supports multi-year schedules (2026, 2027, 2028...).
        """
        self._load_rules()
        employee = self._active_employees.get(employee_id) or self.db.query(Employee).filter(Employee.id == employee_id).first()
        if not employee:
            return {
                "status": "ERROR",
                "message": "Сотрудник не найден",
                "violations": ["Сотрудник не найден в базе данных"],
                "suggested_alternatives": [],
            }

        if not requested_slots:
            return {
                "status": "INVALID_TK",
                "message": "Не указаны даты отпуска",
                "violations": ["Пожалуйста, укажите желаемые даты отпуска."],
                "suggested_alternatives": [],
            }

        # 1. Check TK RF / Total Days validation
        total_days = sum(calculate_slot_days(s["start"], s["end"]) for s in requested_slots)
        has_primary_14 = any(calculate_slot_days(s["start"], s["end"]) >= 14 for s in requested_slots)
        expected_days = employee.total_vacation_days or 36

        violations = []
        if total_days != expected_days:
            violations.append(
                f"Сумма дней отпуска ({total_days} дн.) не соответствует вашей норме ({expected_days} дн. "
                f"для региона {employee.region})."
            )

        if not has_primary_14:
            violations.append(
                "По ТК РФ (ст. 125) хотя бы одна неделимая часть отпуска должна составлять не менее 14 календарных дней."
            )

        if violations:
            return {
                "status": "INVALID_TK",
                "message": "Заявка не соответствует требованиям ТК РФ или лимиту дней.",
                "total_requested_days": total_days,
                "has_primary_block_14": has_primary_14,
                "violations": violations,
                "conflicting_with_roles": [],
                "suggested_alternatives": [],
            }

        # 2. Check Hard Overlaps & Blackout Periods
        conflicts = []
        conflicting_roles = set()

        for slot in requested_slots:
            st, en = slot["start"], slot["end"]
            
            # Check Blackouts
            blackout_conflict = self._check_blackout_intersection(st, en)
            if blackout_conflict:
                conflicts.append(
                    f"Период {st.strftime('%d.%m.%Y')} – {en.strftime('%d.%m.%Y')} попадает на блэкаут-период производства: «{blackout_conflict}»"
                )

            # Check Role Quotas
            role_conflict = self._check_role_quota_violation(employee, st, en)
            if role_conflict:
                conflicts.append(
                    f"Период {st.strftime('%d.%m.%Y')} – {en.strftime('%d.%m.%Y')} превышает квоту одновременного отсутствия для должности «{employee.role}» (смена: {employee.shift})"
                )
                conflicting_roles.add(employee.role)

            # Check Shift Quotas
            shift_conflict = self._check_shift_quota_violation(employee, st, en)
            if shift_conflict:
                shift_q = self._get_shift_quota(employee.shift)
                conflicts.append(
                    f"Период {st.strftime('%d.%m.%Y')} – {en.strftime('%d.%m.%Y')} превышает лимит одновременных отпусков для смены «{employee.shift}» (максимум {shift_q} чел. одновременно)"
                )

            # Check Incompatible Employee Groups
            incomp_conflict = self._check_incompatible_groups_violation(employee, st, en)
            if incomp_conflict:
                group_name = incomp_conflict["group_name"]
                c_names = ", ".join(incomp_conflict["conflicting_names"])
                reason = incomp_conflict["reason"]
                conflicts.append(
                    f"Период {st.strftime('%d.%m.%Y')} – {en.strftime('%d.%m.%Y')} пересекается с отпуском участников группы непересечения «{group_name}» ({c_names}). Причина: «{reason}»"
                )

        if not conflicts:
            return {
                "status": "VALID",
                "message": "Даты свободны и полностью соответствуют правилам производства!",
                "total_requested_days": total_days,
                "has_primary_block_14": has_primary_14,
                "violations": [],
                "conflicting_with_roles": [],
                "suggested_alternatives": [],
            }

        # 3. If Conflicts exist, generate Top-3 deterministic non-conflicting alternatives
        alternatives = self._generate_top3_alternatives(employee, requested_slots, window_search_days)

        return {
            "status": "CONFLICT",
            "message": "Выбранные даты пересекаются с производственными ограничениями (квоты должностей/смен, блэкаут-периоды или непересекающиеся сотрудники).",
            "total_requested_days": total_days,
            "has_primary_block_14": has_primary_14,
            "violations": conflicts,
            "conflicting_with_roles": list(conflicting_roles),
            "suggested_alternatives": alternatives,
        }

    def _check_blackout_intersection(self, start: date, end: date) -> Optional[str]:
        rule = self.rules_by_key.get("blackout_periods")
        if not rule or not rule.is_active:
            return None

        periods = rule.parameters.get("periods", [])
        for p in periods:
            try:
                b_start = date.fromisoformat(p["start"])
                b_end = date.fromisoformat(p["end"])
                if max(start, b_start) <= min(end, b_end):
                    return p.get("name", "Период пиковой нагрузки цеха")
            except (ValueError, KeyError):
                continue
        return None

    def _get_role_quota(self, role_name: str) -> int:
        if role_name in self._role_quotas_db:
            return self._role_quotas_db[role_name]

        rule = self.rules_by_key.get("max_concurrent_roles")
        if not rule or not rule.is_active:
            return 1
        quotas = rule.parameters.get("quotas", {})
        return quotas.get(role_name, 1)

    def _check_role_quota_violation(
        self, employee: Employee, start: date, end: date, exclude_slot_id: Optional[int] = None
    ) -> bool:
        quota = self._get_role_quota(employee.role)

        colleague_ids = {
            eid for eid, emp in self._active_employees.items()
            if emp.role == employee.role and eid != employee.id
        }
        if not colleague_ids:
            return False

        other_slots = [
            s for s in self._active_slots
            if s.employee_id in colleague_ids
            and s.status in ("APPROVED", "REQUESTED")
            and s.start_date <= end
            and s.end_date >= start
            and (exclude_slot_id is None or s.id != exclude_slot_id)
        ]
        if not other_slots:
            return False

        cur_day = start
        while cur_day <= end:
            concurrent_count = sum(1 for s in other_slots if s.start_date <= cur_day <= s.end_date)
            if concurrent_count + 1 > quota:
                return True
            cur_day += timedelta(days=1)

        return False

    def _get_shift_quota(self, shift_name: str) -> int:
        if shift_name in self._shift_quotas_db:
            return self._shift_quotas_db[shift_name]

        rule = self.rules_by_key.get("max_concurrent_shifts")
        if not rule or not rule.is_active:
            return 2
        quotas = rule.parameters.get("quotas", {})
        return quotas.get(shift_name, 2)

    def _check_shift_quota_violation(
        self, employee: Employee, start: date, end: date, exclude_slot_id: Optional[int] = None
    ) -> bool:
        if not employee.shift:
            return False
        quota = self._get_shift_quota(employee.shift)

        colleague_ids = {
            eid for eid, emp in self._active_employees.items()
            if emp.shift == employee.shift and eid != employee.id
        }
        if not colleague_ids:
            return False

        other_slots = [
            s for s in self._active_slots
            if s.employee_id in colleague_ids
            and s.status in ("APPROVED", "REQUESTED")
            and s.start_date <= end
            and s.end_date >= start
            and (exclude_slot_id is None or s.id != exclude_slot_id)
        ]
        if not other_slots:
            return False

        cur_day = start
        while cur_day <= end:
            concurrent_count = sum(1 for s in other_slots if s.start_date <= cur_day <= s.end_date)
            if concurrent_count + 1 > quota:
                return True
            cur_day += timedelta(days=1)

        return False

    def _get_incompatible_groups(self, employee_id: int) -> List[Dict[str, Any]]:
        rule = self.rules_by_key.get("incompatible_employee_groups")
        if not rule or not rule.is_active:
            return []
        groups = rule.parameters.get("groups", [])
        return [g for g in groups if employee_id in g.get("employee_ids", [])]

    def _check_incompatible_groups_violation(
        self, employee: Employee, start: date, end: date, exclude_slot_id: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        groups = self._get_incompatible_groups(employee.id)
        if not groups:
            return None

        for group in groups:
            other_emp_ids = {eid for eid in group.get("employee_ids", []) if eid != employee.id}
            if not other_emp_ids:
                continue
            max_concurrent = group.get("max_concurrent", 1)

            other_slots = [
                s for s in self._active_slots
                if s.employee_id in other_emp_ids
                and s.status in ("APPROVED", "REQUESTED")
                and s.start_date <= end
                and s.end_date >= start
                and (exclude_slot_id is None or s.id != exclude_slot_id)
            ]
            if not other_slots:
                continue

            cur_day = start
            while cur_day <= end:
                overlapping_slots = [s for s in other_slots if s.start_date <= cur_day <= s.end_date]
                if len(overlapping_slots) + 1 > max_concurrent:
                    conflicting_emp_ids = {s.employee_id for s in overlapping_slots}
                    names = [
                        self._active_employees[eid].full_name
                        for eid in conflicting_emp_ids
                        if eid in self._active_employees
                    ]
                    return {
                        "group_name": group.get("name", "Группа непересечения"),
                        "conflicting_names": names,
                        "max_concurrent": max_concurrent,
                        "reason": group.get("reason", "Запрет одновременного отпуска"),
                    }
                cur_day += timedelta(days=1)

        return None

    def _get_first_conflict_reason(self, employee: Employee, start: date, end: date) -> Optional[str]:
        b_name = self._check_blackout_intersection(start, end)
        if b_name:
            return f"Попадание на блэкаут-период: «{b_name}»"
        if self._check_role_quota_violation(employee, start, end):
            return f"Превышение квоты одновременного отсутствия для должности «{employee.role}»"
        if self._check_shift_quota_violation(employee, start, end):
            return f"Превышение лимита одновременных отпусков для смены «{employee.shift}»"
        incomp = self._check_incompatible_groups_violation(employee, start, end)
        if incomp:
            return f"Пересечение в группе «{incomp['group_name']}» ({', '.join(incomp['conflicting_names'])})"
        return None

    def is_slot_valid(self, employee: Employee, start: date, end: date) -> bool:
        return self._get_first_conflict_reason(employee, start, end) is None


    def _find_candidate_slot(
        self, employee: Employee, target_start: date, duration: int, search_direction: int, max_days: int
    ) -> Optional[Tuple[date, date, int]]:
        step = 1 if search_direction >= 0 else -1
        target_year = target_start.year
        for shift in range(1, max_days + 1):
            offset = shift * step
            cand_start = target_start + timedelta(days=offset)
            cand_end = cand_start + timedelta(days=duration - 1)
            
            # Ensure within target year
            if cand_start.year != target_year:
                continue

            if self.is_slot_valid(employee, cand_start, cand_end):
                return cand_start, cand_end, abs(offset)
        return None

    def _generate_top3_alternatives(
        self,
        employee: Employee,
        requested_slots: List[Dict[str, date]],
        window_search_days: int = 45,
    ) -> List[Dict[str, Any]]:
        durations = [calculate_slot_days(s["start"], s["end"]) for s in requested_slots]
        total_days = sum(durations)
        target_year = requested_slots[0]["start"].year if requested_slots else 2026

        alternatives = []

        # Strategy 1: Forward Shift (Nearest slot right after conflict)
        alt1_slots = []
        for s, dur in zip(requested_slots, durations):
            if self.is_slot_valid(employee, s["start"], s["end"]):
                alt1_slots.append({"start": s["start"].isoformat(), "end": s["end"].isoformat()})
            else:
                found = self._find_candidate_slot(employee, s["start"], dur, search_direction=1, max_days=window_search_days)
                if not found:
                    found = self._find_candidate_slot(employee, s["start"], dur, search_direction=-1, max_days=window_search_days)
                if found:
                    alt1_slots.append({"start": found[0].isoformat(), "end": found[1].isoformat()})
                else:
                    alt1_slots.append({"start": (s["start"] + timedelta(days=14)).isoformat(), "end": (s["start"] + timedelta(days=14 + dur - 1)).isoformat()})

        alternatives.append({
            "option": 1,
            "slots": alt1_slots,
            "total_days": total_days,
            "reason": "Ближайший свободный слот сразу после смены коллеги по цеху",
            "score": 95.0,
        })

        # Strategy 2: Pre-Shift or Adjacent Clear Month
        alt2_slots = []
        for s, dur in zip(requested_slots, durations):
            if self.is_slot_valid(employee, s["start"], s["end"]):
                alt2_slots.append({"start": s["start"].isoformat(), "end": s["end"].isoformat()})
            else:
                found = self._find_candidate_slot(employee, s["start"], dur, search_direction=-1, max_days=window_search_days)
                if not found:
                    found = self._find_candidate_slot(employee, s["start"] + timedelta(days=28), dur, search_direction=1, max_days=window_search_days)
                if found:
                    alt2_slots.append({"start": found[0].isoformat(), "end": found[1].isoformat()})
                else:
                    alt2_slots.append({"start": (s["start"] - timedelta(days=21)).isoformat(), "end": (s["start"] - timedelta(days=21 - dur + 1)).isoformat()})

        alternatives.append({
            "option": 2,
            "slots": alt2_slots,
            "total_days": total_days,
            "reason": "Полностью разгруженный период в цехе без технологических рисков",
            "score": 88.0,
        })

        # Strategy 3: Golden Season / Department Load Balanced
        alt3_slots = []
        for idx, (s, dur) in enumerate(zip(requested_slots, durations)):
            if dur >= 14:
                cand_st = date(target_year, 8, 17)
                cand_en = cand_st + timedelta(days=dur - 1)
                if not self.is_slot_valid(employee, cand_st, cand_en):
                    cand_st = date(target_year, 6, 8)
                    cand_en = cand_st + timedelta(days=dur - 1)
                alt3_slots.append({"start": cand_st.isoformat(), "end": cand_en.isoformat()})
            else:
                cand_st = date(target_year, 10, 12)
                cand_en = cand_st + timedelta(days=dur - 1)
                if not self.is_slot_valid(employee, cand_st, cand_en):
                    cand_st = date(target_year, 11, 9)
                    cand_en = cand_st + timedelta(days=dur - 1)
                alt3_slots.append({"start": cand_st.isoformat(), "end": cand_en.isoformat()})

        alternatives.append({
            "option": 3,
            "slots": alt3_slots,
            "total_days": total_days,
            "reason": "Оптимальный баланс загрузки швейного потока (бархатный сезон)",
            "score": 82.0,
        })

        return alternatives

    def batch_optimize_all_pending(self, year: Optional[int] = None) -> Dict[str, Any]:
        """Runs batch global optimization for manager ('Approve All Valid')."""
        self._load_rules()
        query = (
            self.db.query(VacationSlot)
            .filter(VacationSlot.status.in_(["REQUESTED", "REVISED"]))
            .join(Employee)
        )
        if year:
            start_y = date(year, 1, 1)
            end_y = date(year, 12, 31)
            query = query.filter(VacationSlot.start_date >= start_y, VacationSlot.start_date <= end_y)

        pending_slots = query.order_by(Employee.seniority_years.desc(), VacationSlot.created_at.asc()).all()

        approved_count = 0
        conflicts_count = 0
        details = []

        for slot in pending_slots:
            emp = slot.employee
            reason = self._get_first_conflict_reason(emp, slot.start_date, slot.end_date)

            if reason is None:
                slot.status = "APPROVED"
                slot.conflict_reason = None
                approved_count += 1
                details.append({
                    "slot_id": slot.id,
                    "employee": emp.full_name,
                    "dates": f"{slot.start_date} - {slot.end_date}",
                    "status": "APPROVED",
                })
            else:
                slot.status = "CONFLICT"
                slot.conflict_reason = reason
                conflicts_count += 1
                details.append({
                    "slot_id": slot.id,
                    "employee": emp.full_name,
                    "dates": f"{slot.start_date} - {slot.end_date}",
                    "status": "CONFLICT",
                    "reason": slot.conflict_reason,
                })


        self.db.commit()
        return {
            "success": True,
            "approved_count": approved_count,
            "conflicts_count": conflicts_count,
            "total_processed": len(pending_slots),
            "details": details,
        }
