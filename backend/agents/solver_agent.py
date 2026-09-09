from typing import List, Dict, Any
from sqlalchemy.orm import Session

from backend.solver.optimizer import VacationOptimizer
from backend.models import VacationSlot, Employee
from backend.solver.nlp_date_parser import calculate_slot_days


class SolverAgent:
    """
    Agent 2: Constraint Solver & Optimizer Agent
    Executes deterministic constraint satisfaction and alternative generation.
    """

    def __init__(self, db: Session):
        self.db = db
        self.optimizer = VacationOptimizer(db)

    def run_vacation_optimizer(
        self,
        employee_id: int,
        requested_slots: List[Dict[str, Any]],
        window_search_days: int = 45,
    ) -> Dict[str, Any]:
        """
        Tool 2: run_vacation_optimizer
        Validates slots against all Hard and Soft rules and returns Top-3 alternatives on collision.
        """
        return self.optimizer.validate_and_check_slots(
            employee_id=employee_id,
            requested_slots=requested_slots,
            window_search_days=window_search_days,
        )

    def commit_approved_slots(
        self, employee_id: int, slots: List[Dict[str, Any]], status: str = "REQUESTED"
    ) -> List[VacationSlot]:
        """
        Persists newly confirmed vacation slots for the employee in the database.
        Replaces previous pending/conflict slots with the new ones.
        """
        # Clear existing unapproved/conflict/requested slots for this employee
        self.db.query(VacationSlot).filter(
            VacationSlot.employee_id == employee_id,
            VacationSlot.status.in_(["REQUESTED", "CONFLICT", "REVISED"]),
        ).delete()

        created_slots = []
        for s in slots:
            st = s["start"] if hasattr(s["start"], "strftime") else s["start"]
            en = s["end"] if hasattr(s["end"], "strftime") else s["end"]
            
            from datetime import date
            if isinstance(st, str):
                st = date.fromisoformat(st)
            if isinstance(en, str):
                en = date.fromisoformat(en)

            dur = calculate_slot_days(st, en)
            v_slot = VacationSlot(
                employee_id=employee_id,
                start_date=st,
                end_date=en,
                days_count=dur,
                is_primary_block=(dur >= 14),
                status=status,
            )
            self.db.add(v_slot)
            created_slots.append(v_slot)

        self.db.commit()
        return created_slots
