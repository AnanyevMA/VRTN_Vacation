from datetime import date
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Department, JobRole, WorkShift, Employee, ScheduleRule, VacationSlot
from backend.agents.intake_agent import IntakeAgent
from backend.agents.solver_agent import SolverAgent
from backend.agents.manager_agent import ManagerAgent


@pytest.fixture
def agent_test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine)
    db = TestingSession()

    dept = Department(name="Швейный цех №1", code="SEW_1", manager_name="Ковалева Т.И.")
    db.add(dept)
    db.commit()

    role1 = JobRole(name="Швея (портной)", department_id=dept.id, default_quota=1)
    db.add(role1)
    db.commit()

    shift1 = WorkShift(name="Смена 1 (дневная)", code="SHIFT_1")
    db.add(shift1)
    db.commit()

    emp1 = Employee(
        phone="+79001112233",
        max_user_id="max_user_01",
        full_name="Иванова Татьяна Сергеевна",
        role="Швея (портной)",
        department_id=dept.id,
        shift="Смена 1 (дневная)",
        region="Республика Хакасия",
        total_vacation_days=36,
        seniority_years=7,
    )
    emp2 = Employee(
        phone="+79002223344",
        max_user_id="max_user_02",
        full_name="Петрова Светлана Александровна",
        role="Швея (портной)",
        department_id=dept.id,
        shift="Смена 1 (дневная)",
        region="Республика Хакасия",
        total_vacation_days=36,
        seniority_years=3,
    )
    db.add_all([emp1, emp2])
    db.commit()

    r1 = ScheduleRule(
        rule_key="max_concurrent_roles",
        rule_type="HARD",
        parameters={"quotas": {"Швея (портной)": 1}},
        is_active=True,
    )
    db.add(r1)

    # Pre-existing slot for Ivanova: 01.07.2027 - 14.07.2027
    s1 = VacationSlot(
        employee_id=emp1.id,
        start_date=date(2027, 7, 1),
        end_date=date(2027, 7, 14),
        days_count=14,
        is_primary_block=True,
        status="APPROVED",
    )
    db.add(s1)
    db.commit()

    yield db
    db.close()


def test_accumulative_draft_and_confirmation(agent_test_db):
    intake_agent = IntakeAgent(agent_test_db)
    emp2 = agent_test_db.query(Employee).filter(Employee.phone == "+79002223344").first()

    # Step 1: Send 1st interval (14 days in August 2027)
    r1 = intake_agent.process_message(emp2.id, "с 1 по 14 августа 2027")
    assert r1["payload"]["action"] == "DRAFT_UPDATED"
    assert r1["payload"]["accum_days"] == 14
    assert r1["payload"]["rem_days"] == 22

    # Step 2: Send 2nd interval (22 days in November 2027) -> reaches 36 days!
    r2 = intake_agent.process_message(emp2.id, "и с 1 по 22 ноября 2027")
    assert r2["payload"]["action"] == "AWAITING_CONFIRMATION"
    assert r2["payload"]["show_confirm_buttons"] is True
    assert "Проверьте ваш итоговый график" in r2["text"]

    # Step 3: Employee confirms submission
    r3 = intake_agent.process_message(emp2.id, "Подтверждаю")
    assert r3["payload"]["action"] == "SUBMISSION_CONFIRMED"
    assert "официально отправлена" in r3["text"]

    # Check committed slots
    slots = agent_test_db.query(VacationSlot).filter(VacationSlot.employee_id == emp2.id).all()
    assert len(slots) == 2
    assert sum(s.days_count for s in slots) == 36
