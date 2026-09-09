from datetime import date
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Department, Employee, ScheduleRule, VacationSlot
from backend.solver.optimizer import VacationOptimizer


@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine)
    db = TestingSession()

    dept = Department(name="IT", code="IT", manager_name="Manager")
    db.add(dept)
    db.commit()

    # Employee 1: Senior Dev, Khakassia (36 days)
    emp1 = Employee(
        phone="+79001112233",
        full_name="Иванов Иван",
        role="Ведущий разработчик",
        department_id=dept.id,
        region="Республика Хакасия",
        total_vacation_days=36,
        seniority_years=5,
    )
    # Employee 2: Senior Dev (Same role!), Khakassia (36 days)
    emp2 = Employee(
        phone="+79002223344",
        full_name="Петров Петр",
        role="Ведущий разработчик",
        department_id=dept.id,
        region="Республика Хакасия",
        total_vacation_days=36,
        seniority_years=2,
    )
    db.add_all([emp1, emp2])
    db.commit()

    # Rule: TK RF min 14 days
    r1 = ScheduleRule(
        rule_key="tk_rf_min_block",
        rule_type="HARD",
        parameters={"min_days": 14},
        is_active=True,
    )
    # Rule: Max concurrent quota = 1 for Senior Dev
    r2 = ScheduleRule(
        rule_key="max_concurrent_roles",
        rule_type="HARD",
        parameters={"quotas": {"Ведущий разработчик": 1}},
        is_active=True,
    )
    # Rule: Blackout period in late December
    r3 = ScheduleRule(
        rule_key="blackout_periods",
        rule_type="HARD",
        parameters={"periods": [{"name": "Годовой релиз", "start": "2026-12-20", "end": "2026-12-31"}]},
        is_active=True,
    )
    db.add_all([r1, r2, r3])
    db.commit()

    # Existing approved slot for emp1: 01.07.2026 - 14.07.2026
    slot1 = VacationSlot(
        employee_id=emp1.id,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 14),
        days_count=14,
        is_primary_block=True,
        status="APPROVED",
    )
    db.add(slot1)
    db.commit()

    yield db
    db.close()


def test_tk_rf_validation_failure(test_db):
    optimizer = VacationOptimizer(test_db)
    emp2 = test_db.query(Employee).filter(Employee.phone == "+79002223344").first()

    # Request total days = 20 (expected 36) without 14-day block
    slots = [{"start": date(2026, 8, 1), "end": date(2026, 8, 10)}]  # 10 days only
    res = optimizer.validate_and_check_slots(emp2.id, slots)
    assert res["status"] == "INVALID_TK"
    assert len(res["violations"]) >= 1


def test_role_quota_conflict_and_alternatives(test_db):
    optimizer = VacationOptimizer(test_db)
    emp2 = test_db.query(Employee).filter(Employee.phone == "+79002223344").first()

    # Request dates that overlap with emp1 (01.07.2026 - 14.07.2026) + 22 days in autumn = 36 days total
    slots = [
        {"start": date(2026, 7, 1), "end": date(2026, 7, 14)},   # 14 days - CONFLICT with emp1!
        {"start": date(2026, 10, 1), "end": date(2026, 10, 22)}, # 22 days
    ]
    res = optimizer.validate_and_check_slots(emp2.id, slots)
    assert res["status"] == "CONFLICT"
    assert "Ведущий разработчик" in res["conflicting_with_roles"]
    assert len(res["suggested_alternatives"]) == 3

    # Check that option 1 alternative slot does NOT conflict with emp1
    alt1_slot1 = res["suggested_alternatives"][0]["slots"][0]
    st1 = date.fromisoformat(alt1_slot1["start"])
    en1 = date.fromisoformat(alt1_slot1["end"])
    assert optimizer.is_slot_valid(emp2, st1, en1) is True


def test_blackout_period_conflict(test_db):
    optimizer = VacationOptimizer(test_db)
    emp2 = test_db.query(Employee).filter(Employee.phone == "+79002223344").first()

    # Request slots hitting late December blackout
    slots = [
        {"start": date(2026, 8, 1), "end": date(2026, 8, 14)},   # 14 days
        {"start": date(2026, 12, 10), "end": date(2026, 12, 31)}, # 22 days - Hits blackout 20-31 Dec!
    ]
    res = optimizer.validate_and_check_slots(emp2.id, slots)
    assert res["status"] == "CONFLICT"
    assert any("блэкаут" in v.lower() for v in res["violations"])


def test_shift_quota_conflict_and_alternatives(test_db):
    dept = test_db.query(Department).first()
    s1 = Employee(
        phone="+79501112233",
        full_name="Швея Анна",
        role="Швея 1",
        shift="Смена 1 (дневная)",
        department_id=dept.id,
        total_vacation_days=36,
    )
    s2 = Employee(
        phone="+79502223344",
        full_name="Швея Белла",
        role="Швея 2",
        shift="Смена 1 (дневная)",
        department_id=dept.id,
        total_vacation_days=36,
    )
    test_db.add_all([s1, s2])
    test_db.commit()

    shift_rule = ScheduleRule(
        rule_key="max_concurrent_shifts",
        rule_type="HARD",
        parameters={"quotas": {"Смена 1 (дневная)": 1}},
        is_active=True,
    )
    test_db.add(shift_rule)

    slot = VacationSlot(
        employee_id=s1.id,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 14),
        days_count=14,
        is_primary_block=True,
        status="APPROVED",
    )
    test_db.add(slot)
    test_db.commit()

    optimizer = VacationOptimizer(test_db)
    slots = [
        {"start": date(2026, 6, 5), "end": date(2026, 6, 18)},
        {"start": date(2026, 9, 1), "end": date(2026, 9, 22)},
    ]
    res = optimizer.validate_and_check_slots(s2.id, slots)
    assert res["status"] == "CONFLICT"
    assert any("Смена 1 (дневная)" in v for v in res["violations"])
    assert len(res["suggested_alternatives"]) == 3

    alt = res["suggested_alternatives"][0]["slots"][0]
    st = date.fromisoformat(alt["start"])
    en = date.fromisoformat(alt["end"])
    assert optimizer.is_slot_valid(s2, st, en) is True


def test_incompatible_employee_groups_conflict_and_alternatives(test_db):
    dept = test_db.query(Department).first()
    w1 = Employee(
        phone="+79601112233",
        full_name="Портная Мария",
        role="Портная",
        shift="Смена 1 (дневная)",
        department_id=dept.id,
        total_vacation_days=36,
    )
    w2 = Employee(
        phone="+79602223344",
        full_name="Портная Дарья",
        role="Портная",
        shift="Смена 2 (вечерняя)",
        department_id=dept.id,
        total_vacation_days=36,
    )
    w3 = Employee(
        phone="+79603334455",
        full_name="Портная Екатерина",
        role="Портная",
        shift="2/2",
        department_id=dept.id,
        total_vacation_days=36,
    )
    test_db.add_all([w1, w2, w3])
    test_db.commit()

    incomp_rule = ScheduleRule(
        rule_key="incompatible_employee_groups",
        rule_type="HARD",
        parameters={
            "groups": [
                {
                    "id": "g1",
                    "name": "Ведущие мастера пошива",
                    "employee_ids": [w1.id, w2.id, w3.id],
                    "max_concurrent": 1,
                    "reason": "Взаимозаменяемые на главном потоке",
                }
            ]
        },
        is_active=True,
    )
    test_db.add(incomp_rule)

    slot1 = VacationSlot(
        employee_id=w1.id,
        start_date=date(2026, 5, 10),
        end_date=date(2026, 5, 23),
        days_count=14,
        is_primary_block=True,
        status="APPROVED",
    )
    test_db.add(slot1)
    test_db.commit()

    optimizer = VacationOptimizer(test_db)
    slots = [
        {"start": date(2026, 5, 15), "end": date(2026, 5, 28)},
        {"start": date(2026, 11, 1), "end": date(2026, 11, 22)},
    ]
    res = optimizer.validate_and_check_slots(w2.id, slots)
    assert res["status"] == "CONFLICT"
    assert any("Ведущие мастера пошива" in v for v in res["violations"])
    assert any("Портная Мария" in v for v in res["violations"])
    assert any("Взаимозаменяемые на главном потоке" in v for v in res["violations"])
    assert len(res["suggested_alternatives"]) == 3

    alt = res["suggested_alternatives"][0]["slots"][0]
    st = date.fromisoformat(alt["start"])
    en = date.fromisoformat(alt["end"])
    assert optimizer.is_slot_valid(w2, st, en) is True

