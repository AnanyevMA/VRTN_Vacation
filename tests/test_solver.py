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


def test_personal_incompatible_pairs_conflict_and_alternatives(test_db):
    dept = test_db.query(Department).first()
    p1 = Employee(
        phone="+79701112233",
        full_name="Напарница Ольга",
        role="Оператор ВТО",
        shift="Смена 1 (дневная)",
        department_id=dept.id,
        total_vacation_days=36,
    )
    p2 = Employee(
        phone="+79702223344",
        full_name="Напарница Светлана",
        role="Контролер ОТК",
        shift="Смена 2 (вечерняя)",
        department_id=dept.id,
        total_vacation_days=36,
    )
    test_db.add_all([p1, p2])
    test_db.commit()

    pair_rule = ScheduleRule(
        rule_key="personal_incompatible_pairs",
        rule_type="HARD",
        parameters={
            "pairs": [
                {
                    "id": "pair1",
                    "employee_a_id": p1.id,
                    "employee_b_id": p2.id,
                    "reason": "Подменяют друг друга на приемке",
                }
            ]
        },
        is_active=True,
    )
    test_db.add(pair_rule)

    slot1 = VacationSlot(
        employee_id=p1.id,
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 14),
        days_count=14,
        is_primary_block=True,
        status="APPROVED",
    )
    test_db.add(slot1)
    test_db.commit()

    optimizer = VacationOptimizer(test_db)
    slots = [
        {"start": date(2026, 4, 5), "end": date(2026, 4, 18)},
        {"start": date(2026, 10, 1), "end": date(2026, 10, 22)},
    ]
    res = optimizer.validate_and_check_slots(p2.id, slots)
    assert res["status"] == "CONFLICT"
    assert any("Напарница Ольга" in v for v in res["violations"])
    assert any("Подменяют друг друга на приемке" in v for v in res["violations"])
    assert len(res["suggested_alternatives"]) == 3

    alt = res["suggested_alternatives"][0]["slots"][0]
    st = date.fromisoformat(alt["start"])
    en = date.fromisoformat(alt["end"])
    assert optimizer.is_slot_valid(p2, st, en) is True


def test_miniapp_full_role_workflow(test_db):
    from backend.models import BotAdmin
    from backend.api.miniapp_routes import (
        get_miniapp_context,
        submit_miniapp_consent,
        add_miniapp_draft_slot,
        select_miniapp_alternative,
        remove_miniapp_draft_slot,
        submit_miniapp_draft,
        admin_batch_approve,
        admin_slot_action,
        MiniAppConsentIn,
        MiniAppAddSlotIn,
        MiniAppSelectAlternativeIn,
        MiniAppRemoveDraftSlotIn,
        MiniAppSubmitDraftIn,
        MiniAppAdminBatchIn,
        MiniAppAdminSlotActionIn,
    )

    dept = test_db.query(Department).first()
    emp_a = Employee(
        phone="+79801112233",
        max_user_id="uid_emp_a",
        full_name="Швея Алина",
        role="Швея (портной)",
        shift="Смена 1 (дневная)",
        department_id=dept.id,
        total_vacation_days=36,
        consent_152fz=True,
    )
    emp_b = Employee(
        phone="+79802223344",
        max_user_id="uid_emp_b",
        full_name="Швея Полина",
        role="Швея (портной)",
        shift="Смена 1 (дневная)",
        department_id=dept.id,
        total_vacation_days=36,
        consent_152fz=False,
    )
    admin = BotAdmin(
        phone="+79809998877",
        max_user_id="uid_admin_boss",
        full_name="Руководитель Цеха",
        role_title="Директор производства",
        is_active=True,
    )
    test_db.add_all([emp_a, emp_b, admin])
    test_db.commit()

    # Personal non-overlapping pair between emp_a and emp_b
    pair_rule = ScheduleRule(
        rule_key="personal_incompatible_pairs",
        rule_type="HARD",
        parameters={
            "pairs": [
                {
                    "id": "p_ab",
                    "employee_a_id": emp_a.id,
                    "employee_b_id": emp_b.id,
                    "reason": "Сменщицы на закрепочной машине",
                }
            ]
        },
        is_active=True,
    )
    test_db.add(pair_rule)

    # emp_a already has an approved vacation 2026-06-01 .. 2026-06-14
    slot_a = VacationSlot(
        employee_id=emp_a.id,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 14),
        days_count=14,
        is_primary_block=True,
        status="APPROVED",
    )
    test_db.add(slot_a)
    test_db.commit()

    # 1. Context for emp_b includes my_restrictions with emp_a
    ctx = get_miniapp_context(max_user_id="uid_emp_b", employee_id=None, year=2026, x_admin_token=None, db=test_db)
    assert ctx["employee"]["full_name"] == "Швея Полина"
    assert ctx["employee"]["consent_152fz"] is False
    assert len(ctx["my_restrictions"]) == 1
    assert ctx["my_restrictions"][0]["partner_name"] == "Швея Алина"

    # 2. Accept 152-FZ consent
    res_consent = submit_miniapp_consent(MiniAppConsentIn(max_user_id="uid_emp_b", accepted=True), db=test_db)
    assert res_consent["consent_152fz"] is True

    # 3. Try adding a conflicting single period (overlaps with emp_a 2026-06-05..2026-06-18) -> immediate pre-check catches it!
    res_conflict = add_miniapp_draft_slot(
        MiniAppAddSlotIn(max_user_id="uid_emp_b", start_date=date(2026, 6, 5), end_date=date(2026, 6, 18)),
        db=test_db,
    )
    assert res_conflict["payload"]["action"] == "OFFER_ALTERNATIVES"
    assert len(res_conflict["payload"]["suggested_alternatives"]) >= 1

    # 4. Select single-slot alternative via select_miniapp_alternative
    first_alt = res_conflict["payload"]["suggested_alternatives"][0]
    res_alt = select_miniapp_alternative(
        MiniAppSelectAlternativeIn(
            max_user_id="uid_emp_b",
            slots=first_alt["slots"],
            replace_draft=first_alt.get("replace_draft", False),
        ),
        db=test_db,
    )
    assert res_alt["payload"]["action"] == "DRAFT_UPDATED"
    assert res_alt["payload"]["accum_days"] == 14

    # 5. Add second period (22 days in September) -> reaches 36 days (AWAITING_CONFIRMATION)
    res_add2 = add_miniapp_draft_slot(
        MiniAppAddSlotIn(max_user_id="uid_emp_b", start_date=date(2026, 9, 1), end_date=date(2026, 9, 22)),
        db=test_db,
    )
    assert res_add2["payload"]["action"] == "AWAITING_CONFIRMATION"

    # 6. Remove second period from draft -> status resets to DRAFTING so first 14-day period is preserved!
    res_rem = remove_miniapp_draft_slot(
        MiniAppRemoveDraftSlotIn(max_user_id="uid_emp_b", index=1, reset_all=False),
        db=test_db,
    )
    assert len(res_rem["draft_slots"]) == 1

    # Re-add second period (22 days in October) -> reaches 36 days without wiping first period
    res_add3 = add_miniapp_draft_slot(
        MiniAppAddSlotIn(max_user_id="uid_emp_b", start_date=date(2026, 10, 1), end_date=date(2026, 10, 22)),
        db=test_db,
    )
    assert res_add3["payload"]["action"] == "AWAITING_CONFIRMATION"
    assert len(res_add3["payload"]["draft_slots"]) == 2

    # 7. Submit draft -> returns SUBMISSION_CONFIRMED
    res_sub = submit_miniapp_draft(MiniAppSubmitDraftIn(max_user_id="uid_emp_b"), db=test_db)
    assert res_sub["payload"]["action"] == "SUBMISSION_CONFIRMED"

    # 8. Manager batch approve & slot action in Mini App
    res_batch = admin_batch_approve(
        MiniAppAdminBatchIn(max_user_id="uid_admin_boss", year=2026),
        x_admin_token=None,
        db=test_db,
    )
    assert res_batch["success"] is True
    assert res_batch["approved_count"] == 2


def test_miniapp_edit_draft_and_recall_submitted_slots(test_db):
    from backend.api.miniapp_routes import (
        add_miniapp_draft_slot,
        update_miniapp_draft_slot,
        recall_submitted_slots_to_draft,
        submit_miniapp_draft,
        MiniAppAddSlotIn,
        MiniAppUpdateDraftSlotIn,
        MiniAppRecallSlotsIn,
        MiniAppSubmitDraftIn,
    )

    dept = test_db.query(Department).first()

    # Persona 1 & 2: Employee edits period in draft before submission, and recalls submitted unapproved slots
    emp_edit = Employee(
        phone="+79811112233",
        max_user_id="uid_emp_edit",
        full_name="Швея Татьяна",
        role="Швея (портной)",
        shift="Смена 1 (дневная)",
        department_id=dept.id,
        total_vacation_days=36,
        consent_152fz=True,
    )
    # Persona 3: Employee who already has 14 APPROVED days and plans remaining 22 days
    emp_partial = Employee(
        phone="+79812223344",
        max_user_id="uid_emp_partial",
        full_name="Закройщик Галина",
        role="Закройщик",
        shift="Смена 2 (вечерняя)",
        department_id=dept.id,
        total_vacation_days=36,
        consent_152fz=True,
    )
    test_db.add_all([emp_edit, emp_partial])
    test_db.commit()

    # Add 14 + 22 = 36 days to draft for emp_edit
    add_miniapp_draft_slot(
        MiniAppAddSlotIn(max_user_id="uid_emp_edit", start_date=date(2026, 7, 1), end_date=date(2026, 7, 14)),
        db=test_db,
    )
    res_36 = add_miniapp_draft_slot(
        MiniAppAddSlotIn(max_user_id="uid_emp_edit", start_date=date(2026, 9, 1), end_date=date(2026, 9, 22)),
        db=test_db,
    )
    assert res_36["payload"]["action"] == "AWAITING_CONFIRMATION"

    # Edit second period in-place (shift September vacation to 05.09..26.09)
    res_upd = update_miniapp_draft_slot(
        MiniAppUpdateDraftSlotIn(
            max_user_id="uid_emp_edit",
            index=1,
            start_date=date(2026, 9, 5),
            end_date=date(2026, 9, 26),
        ),
        db=test_db,
    )
    assert res_upd["payload"]["action"] == "AWAITING_CONFIRMATION"
    assert res_upd["payload"]["draft_slots"][1]["start"] == "2026-09-05"
    assert res_upd["payload"]["draft_slots"][1]["end"] == "2026-09-26"

    # Submit draft -> creates 2 REQUESTED slots
    res_sub = submit_miniapp_draft(MiniAppSubmitDraftIn(max_user_id="uid_emp_edit"), db=test_db)
    assert res_sub["payload"]["action"] == "SUBMISSION_CONFIRMED"

    # Recall unapproved slots back to draft for editing
    res_recall = recall_submitted_slots_to_draft(
        MiniAppRecallSlotsIn(max_user_id="uid_emp_edit", year=2026),
        db=test_db,
    )
    assert res_recall["status"] == "ok"
    assert len(res_recall["draft_slots"]) == 2
    assert test_db.query(VacationSlot).filter(VacationSlot.employee_id == emp_edit.id).count() == 0

    # Edit after recall and submit again
    update_miniapp_draft_slot(
        MiniAppUpdateDraftSlotIn(
            max_user_id="uid_emp_edit",
            index=1,
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 22),
        ),
        db=test_db,
    )
    res_sub2 = submit_miniapp_draft(MiniAppSubmitDraftIn(max_user_id="uid_emp_edit"), db=test_db)
    assert res_sub2["payload"]["action"] == "SUBMISSION_CONFIRMED"

    # Persona 3 test: emp_partial already has 14 APPROVED days in May 2026
    approved_slot = VacationSlot(
        employee_id=emp_partial.id,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 14),
        days_count=14,
        is_primary_block=True,
        status="APPROVED",
    )
    test_db.add(approved_slot)
    test_db.commit()

    # Adding remaining 22 days in October 2026 reaches 14 + 22 = 36 days -> AWAITING_CONFIRMATION!
    res_p3 = add_miniapp_draft_slot(
        MiniAppAddSlotIn(max_user_id="uid_emp_partial", start_date=date(2026, 10, 5), end_date=date(2026, 10, 26)),
        db=test_db,
    )
    assert res_p3["payload"]["action"] == "AWAITING_CONFIRMATION"
    res_p3_sub = submit_miniapp_draft(MiniAppSubmitDraftIn(max_user_id="uid_emp_partial"), db=test_db)
    assert res_p3_sub["payload"]["action"] == "SUBMISSION_CONFIRMED"
    emp_partial_slots = test_db.query(VacationSlot).filter(VacationSlot.employee_id == emp_partial.id).all()
    assert sum(s.days_count for s in emp_partial_slots) == 36


def test_factory_21_day_summer_and_gap_rules(test_db):
    from fastapi import HTTPException
    from backend.api.miniapp_routes import (
        add_miniapp_draft_slot,
        submit_miniapp_draft,
        MiniAppAddSlotIn,
        MiniAppSubmitDraftIn,
    )

    dept = test_db.query(Department).first()
    p1 = Employee(
        phone="+79821112233",
        max_user_id="uid_poleshchuk",
        full_name="Полещук",
        role="Швея (портной)",
        shift="Смена 1",
        department_id=dept.id,
        total_vacation_days=36,
        consent_152fz=True,
    )
    p2 = Employee(
        phone="+79822223344",
        max_user_id="uid_artamonova",
        full_name="Артамонова",
        role="Швея (портной)",
        shift="Смена 1",
        department_id=dept.id,
        total_vacation_days=36,
        consent_152fz=True,
    )
    test_db.add_all([p1, p2])
    test_db.commit()

    # Enable vacation_limits rule: max 21 single, max 21 summer (June-Sept), min 14 total/year (flexible)
    limits_rule = ScheduleRule(
        rule_key="vacation_limits",
        rule_type="HARD",
        parameters={
            "max_single_slot_days": 21,
            "max_summer_days": 21,
            "summer_start_month": 6,
            "summer_end_month": 9,
            "min_total_year_days": 14,
            "allow_flexible_total": True,
        },
        is_active=True,
    )
    test_db.add(limits_rule)

    # Group with min_gap_days = 7 (1 week mandatory break between vacations)
    gap_group_rule = test_db.query(ScheduleRule).filter(ScheduleRule.rule_key == "incompatible_employee_groups").first()
    group_entry = {
        "id": "grp_gap7",
        "name": "Полещук, Артамонова, Белянкина",
        "employee_ids": [p1.id, p2.id],
        "max_concurrent": 1,
        "min_gap_days": 7,
        "reason": "Между отпусками должен быть перерыв 1 неделя",
    }
    if not gap_group_rule:
        gap_group_rule = ScheduleRule(
            rule_key="incompatible_employee_groups",
            rule_type="HARD",
            parameters={"groups": [group_entry]},
            is_active=True,
        )
        test_db.add(gap_group_rule)
    else:
        gap_group_rule.parameters = {"groups": [group_entry]}
    test_db.commit()

    # 1. Poleshchuk takes 14 days in July: 01.07.2026 - 14.07.2026 and submits immediately (flexible total >= 14 days!)
    add_miniapp_draft_slot(
        MiniAppAddSlotIn(max_user_id="uid_poleshchuk", start_date=date(2026, 7, 1), end_date=date(2026, 7, 14)),
        db=test_db,
    )
    res_sub_p1 = submit_miniapp_draft(MiniAppSubmitDraftIn(max_user_id="uid_poleshchuk"), db=test_db)
    assert res_sub_p1["payload"]["action"] == "SUBMISSION_CONFIRMED"

    # 2. Artamonova tries to take 22 days in a single vacation -> rejected (> 21 days in one vacation)
    with pytest.raises(HTTPException) as exc_22:
        add_miniapp_draft_slot(
            MiniAppAddSlotIn(max_user_id="uid_artamonova", start_date=date(2026, 10, 1), end_date=date(2026, 10, 22)),
            db=test_db,
        )
    assert exc_22.value.status_code == 400
    assert "21" in exc_22.value.detail

    # 3. Artamonova tries to start vacation on 18.07.2026 (only 3 days after Poleshchuk's 14.07 end, needs 7 days gap!)
    res_gap = add_miniapp_draft_slot(
        MiniAppAddSlotIn(max_user_id="uid_artamonova", start_date=date(2026, 7, 18), end_date=date(2026, 7, 31)),
        db=test_db,
    )
    assert res_gap["payload"]["action"] == "OFFER_ALTERNATIVES"
    assert "перерыв минимум 7 дн." in res_gap["text"]

    # 4. Artamonova starts on 22.07.2026 (7 full days gap: 15,16,17,18,19,20,21 July) for 14 days -> succeeds!
    res_ok = add_miniapp_draft_slot(
        MiniAppAddSlotIn(max_user_id="uid_artamonova", start_date=date(2026, 7, 22), end_date=date(2026, 8, 4)),
        db=test_db,
    )
    assert res_ok["payload"]["action"] == "DRAFT_UPDATED"

    # 5. Artamonova tries to add another 10 days in September (14 + 10 = 24 summer days > 21 max summer days!) -> rejected
    with pytest.raises(HTTPException) as exc_summer:
        add_miniapp_draft_slot(
            MiniAppAddSlotIn(max_user_id="uid_artamonova", start_date=date(2026, 9, 1), end_date=date(2026, 9, 10)),
            db=test_db,
        )
    assert exc_summer.value.status_code == 400
    assert "июня по сентябрь" in exc_summer.value.detail





