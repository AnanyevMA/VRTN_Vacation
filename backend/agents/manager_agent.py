from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session

from backend.models import Employee, ScheduleRule, VacationSlot, Department
from backend.solver.optimizer import VacationOptimizer


class ManagerAgent:
    """
    Agent 3: Manager Admin & Dashboard Agent
    Handles employee roster management, business rules configuration, conflict arbitration, and analytics.
    """

    def __init__(self, db: Session):
        self.db = db
        self.optimizer = VacationOptimizer(db)

    def update_rules_and_roster(self, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Tool 3: update_rules_and_roster
        Action types:
          - 'ADD_RULE', 'UPDATE_RULE', 'TOGGLE_RULE'
          - 'ADD_USER', 'UPDATE_USER', 'DELETE_USER'
          - 'UPDATE_ROLE_QUOTAS', 'UPDATE_BLACKOUTS'
        """
        action = action.upper()

        if action == "ADD_RULE":
            rule_key = payload.get("rule_key")
            existing = self.db.query(ScheduleRule).filter(ScheduleRule.rule_key == rule_key).first()
            if existing:
                return {"success": False, "affected_rows": 0, "message": f"Правило с ключом {rule_key} уже существует"}

            rule = ScheduleRule(
                rule_key=rule_key,
                rule_type=payload.get("rule_type", "HARD"),
                parameters=payload.get("parameters", {}),
                description=payload.get("description", ""),
                is_active=payload.get("is_active", True),
            )
            self.db.add(rule)
            self.db.commit()
            return {"success": True, "affected_rows": 1, "message": "Правило успешно добавлено", "data": {"id": rule.id}}

        elif action == "UPDATE_RULE":
            rule_id = payload.get("id") or payload.get("rule_id")
            rule_key = payload.get("rule_key")
            rule = None
            if rule_id:
                rule = self.db.query(ScheduleRule).filter(ScheduleRule.id == rule_id).first()
            elif rule_key:
                rule = self.db.query(ScheduleRule).filter(ScheduleRule.rule_key == rule_key).first()

            if not rule:
                return {"success": False, "affected_rows": 0, "message": "Правило не найдено"}

            if "parameters" in payload:
                rule.parameters = payload["parameters"]
            if "description" in payload:
                rule.description = payload["description"]
            if "is_active" in payload:
                rule.is_active = payload["is_active"]
            if "rule_type" in payload:
                rule.rule_type = payload["rule_type"]

            self.db.commit()
            return {"success": True, "affected_rows": 1, "message": "Правило успешно обновлено"}

        elif action == "UPDATE_ROLE_QUOTAS":
            rule = self.db.query(ScheduleRule).filter(ScheduleRule.rule_key == "max_concurrent_roles").first()
            if not rule:
                rule = ScheduleRule(
                    rule_key="max_concurrent_roles",
                    rule_type="HARD",
                    parameters={"quotas": payload.get("quotas", {})},
                    description="Квоты одновременных отсутствий сотрудников критических ролей.",
                    is_active=True,
                )
                self.db.add(rule)
            else:
                rule.parameters = {"quotas": payload.get("quotas", {})}
            self.db.commit()
            return {"success": True, "affected_rows": 1, "message": "Квоты ролей успешно сохранены"}

        elif action == "UPDATE_BLACKOUTS":
            rule = self.db.query(ScheduleRule).filter(ScheduleRule.rule_key == "blackout_periods").first()
            if not rule:
                rule = ScheduleRule(
                    rule_key="blackout_periods",
                    rule_type="HARD",
                    parameters={"periods": payload.get("periods", [])},
                    description="Блэкаут-периоды (запрет на отпуска).",
                    is_active=True,
                )
                self.db.add(rule)
            else:
                rule.parameters = {"periods": payload.get("periods", [])}
            self.db.commit()
            return {"success": True, "affected_rows": 1, "message": "Блэкаут-периоды успешно обновлены"}

        elif action == "ADD_USER":
            phone = payload.get("phone", "").strip()
            existing = self.db.query(Employee).filter(Employee.phone == phone).first()
            if existing:
                return {"success": False, "affected_rows": 0, "message": f"Сотрудник с телефоном {phone} уже существует"}

            dept_id = payload.get("department_id")
            if not dept_id:
                first_dept = self.db.query(Department).first()
                dept_id = first_dept.id if first_dept else 1

            emp = Employee(
                phone=phone,
                full_name=payload.get("full_name", ""),
                role=payload.get("role", "Специалист"),
                department_id=dept_id,
                region=payload.get("region", "Республика Хакасия"),
                total_vacation_days=payload.get("total_vacation_days", 36),
                seniority_years=payload.get("seniority_years", 1),
                social_priority=payload.get("social_priority", "NONE"),
                is_active=payload.get("is_active", True),
            )
            self.db.add(emp)
            self.db.commit()
            return {"success": True, "affected_rows": 1, "message": "Сотрудник успешно зарегистрирован", "data": {"id": emp.id}}

        elif action == "UPDATE_USER":
            emp_id = payload.get("id") or payload.get("employee_id")
            emp = self.db.query(Employee).filter(Employee.id == emp_id).first()
            if not emp:
                return {"success": False, "affected_rows": 0, "message": "Сотрудник не найден"}

            for key in ["full_name", "phone", "role", "department_id", "region", "total_vacation_days", "seniority_years", "social_priority", "is_active", "max_user_id"]:
                if key in payload and payload[key] is not None:
                    setattr(emp, key, payload[key])

            self.db.commit()
            return {"success": True, "affected_rows": 1, "message": "Данные сотрудника обновлены"}

        elif action == "DELETE_USER":
            emp_id = payload.get("id") or payload.get("employee_id")
            emp = self.db.query(Employee).filter(Employee.id == emp_id).first()
            if not emp:
                return {"success": False, "affected_rows": 0, "message": "Сотрудник не найден"}

            self.db.delete(emp)
            self.db.commit()
            return {"success": True, "affected_rows": 1, "message": "Сотрудник удален из базы"}

        return {"success": False, "affected_rows": 0, "message": f"Неизвестное действие: {action}"}

    def get_dashboard_summary(self) -> Dict[str, Any]:
        """Calculates high-level stats and KPIs for Manager Dashboard."""
        total_employees = self.db.query(Employee).filter(Employee.is_active == True).count()
        
        all_slots = self.db.query(VacationSlot).join(Employee).filter(Employee.is_active == True).all()
        approved_slots = [s for s in all_slots if s.status == "APPROVED"]
        requested_slots = [s for s in all_slots if s.status in ["REQUESTED", "REVISED"]]
        conflict_slots = [s for s in all_slots if s.status == "CONFLICT"]

        submitted_emp_ids = set(s.employee_id for s in all_slots)
        submission_rate = (len(submitted_emp_ids) / total_employees * 100) if total_employees else 0

        return {
            "total_employees": total_employees,
            "submitted_count": len(submitted_emp_ids),
            "submission_rate_percent": round(submission_rate, 1),
            "approved_slots_count": len(approved_slots),
            "pending_slots_count": len(requested_slots),
            "conflict_slots_count": len(conflict_slots),
        }
