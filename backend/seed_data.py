from datetime import date
from backend.database import SessionLocal, engine, Base, migrate_db
from backend.models import Department, JobRole, WorkShift, Employee, ScheduleRule, VacationSlot, EmployeeDraft
from backend.google_sheets_importer import sync_real_employees_to_db


def seed_database():
    migrate_db()
    db = SessionLocal()

    if db.query(Department).count() > 0:
        # Check if real employees are synced
        synth = db.query(Employee).filter(Employee.full_name == "Иванова Татьяна Сергеевна").first()
        if synth or db.query(Employee).count() == 0:
            sync_real_employees_to_db(db)
        ensure_default_rules(db)
        db.close()
        return

    # 1. Departments for Garment Factory (Швейное производство)
    depts_data = [
        {"name": "Швейный цех №1", "code": "SEW_1", "manager_name": "Ковалева Татьяна Ивановна", "description": "Пошив базового ассортимента и трикотажных изделий"},
        {"name": "Швейный цех №2", "code": "SEW_2", "manager_name": "Степанова Ольга Викторовна", "description": "Пошив коллекций WB и спецзаказов"},
        {"name": "Раскройный цех", "code": "CUT", "manager_name": "Медведев Сергей Анатольевич", "description": "Настилание тканей, автоматический и ручной раскрой лекал"},
        {"name": "Участок ВТО и упаковки", "code": "VTO", "manager_name": "Павлова Марина Юрьевна", "description": "Влажно-тепловая обработка, маркировка и упаковка готовой продукции"},
        {"name": "Конструкторско-технологический отдел", "code": "TECH", "manager_name": "Григорьева Елена Николаевна", "description": "Разработка лекал, градация размеров и технологические карты"},
        {"name": "Склад материалов и фурнитуры", "code": "WH", "manager_name": "Борисов Андрей Петрович", "description": "Приемка, хранение и выдача тканей, ниток и фурнитуры"},
        {"name": "Администрация и управление", "code": "ADM", "manager_name": "Соколов Валерий Дмитриевич", "description": "Дирекция, кадровая служба и бухгалтерия"},
    ]

    dept_objs = {}
    for d_data in depts_data:
        dept = Department(**d_data)
        db.add(dept)
        db.flush()
        dept_objs[dept.code] = dept

    # 2. Job Roles (Должности швейного производства)
    roles_data = [
        {"name": "Швея (портной)", "department_id": dept_objs["SEW_1"].id, "default_quota": 3, "description": "Выполнение пооперационного пошива швейных изделий"},
        {"name": "Закройщик", "department_id": dept_objs["CUT"].id, "default_quota": 1, "description": "Раскрой полотен и материалов по лекалам"},
        {"name": "Технолог швейного производства", "department_id": dept_objs["TECH"].id, "default_quota": 1, "description": "Контроль соблюдения технологии пошива и нормативов"},
        {"name": "Конструктор-лекальщик", "department_id": dept_objs["TECH"].id, "default_quota": 1, "description": "Построение базовых конструкций и моделирование"},
        {"name": "Оператор ВТО (утюжильщик)", "department_id": dept_objs["VTO"].id, "default_quota": 1, "description": "Влажно-тепловая обработка полуфабрикатов и готовых изделий"},
        {"name": "Мастер смены / цеха", "department_id": dept_objs["SEW_1"].id, "default_quota": 1, "description": "Руководство швейной бригадой и контроль выработки"},
        {"name": "Механик швейного оборудования", "department_id": dept_objs["SEW_1"].id, "default_quota": 1, "description": "Обслуживание и наладка швейных машин, оверлоков и прессов"},
        {"name": "Контролер ОТК", "department_id": dept_objs["VTO"].id, "default_quota": 1, "description": "Проверка соответствия качества швов и готовых изделий ГОСТ/ТУ"},
        {"name": "Кладовщик фурнитуры", "department_id": dept_objs["WH"].id, "default_quota": 1, "description": "Учет и комплектование заказов фурнитурой"},
    ]

    for r_data in roles_data:
        role = JobRole(**r_data)
        db.add(role)
    db.commit()

    # 3. Work Shifts (Смены)
    shifts_data = [
        {"name": "Смена 1 (дневная 07:00-15:30)", "code": "SHIFT_1", "description": "Основная утренняя смена швейного цеха"},
        {"name": "Смена 2 (вечерняя 15:30-00:00)", "code": "SHIFT_2", "description": "Вторая смена цеха пошива"},
        {"name": "Сменный график 2/2", "code": "SHIFT_2_2", "description": "Два через два по 12 часов (раскрой и ВТО)"},
        {"name": "Пятидневка 5/2 (08:00-17:00)", "code": "SHIFT_5_2", "description": "Технологи, конструкторы, администрация"},
    ]

    for s_data in shifts_data:
        shift = WorkShift(**s_data)
        db.add(shift)
    db.commit()

    # 4. Schedule Rules
    rules_data = [
        {
            "rule_key": "tk_rf_min_block",
            "rule_type": "HARD",
            "parameters": {"min_days": 14},
            "description": "Минимум один неделимый период отпуска должен составлять не менее 14 календарных дней (ст. 125 ТК РФ).",
            "is_active": True,
        },
        {
            "rule_key": "max_concurrent_roles",
            "rule_type": "HARD",
            "parameters": {
                "quotas": {
                    "Швея (портной)": 3,
                    "Закройщик": 1,
                    "Технолог швейного производства": 1,
                    "Конструктор-лекальщик": 1,
                    "Оператор ВТО (утюжильщик)": 1,
                    "Мастер смены / цеха": 1,
                    "Механик швейного оборудования": 1,
                    "Контролер ОТК": 1,
                    "Кладовщик фурнитуры": 1,
                }
            },
            "description": "Квоты одновременных отсутствий сотрудников критических должностей швейного цеха.",
            "is_active": True,
        },
        {
            "rule_key": "blackout_periods",
            "rule_type": "HARD",
            "parameters": {
                "periods": [
                    {
                        "name": "Сезонная сдача школьной коллекции / Госзаказ",
                        "start": "2026-08-15",
                        "end": "2026-08-31",
                        "description": "Пиковая загрузка швейных потоков",
                    },
                    {
                        "name": "Годовая инвентаризация и ТО оборудования",
                        "start": "2026-12-25",
                        "end": "2026-12-31",
                        "description": "Закрытие года и переучет на складе",
                    },
                    {
                        "name": "Весенний запуск весенне-летней коллекции 2027",
                        "start": "2027-03-20",
                        "end": "2027-04-05",
                        "description": "Массовый запуск раскроя новых моделей",
                    }
                ]
            },
            "description": "Блэкаут-периоды (запрет на отпуска в пиковые производственные сезоны).",
            "is_active": True,
        },
        {
            "rule_key": "soft_seniority_weight",
            "rule_type": "SOFT",
            "parameters": {"weight": 2.0},
            "description": "Приоритет выбора дат сотрудниками с большим стажем работы.",
            "is_active": True,
        },
        {
            "rule_key": "soft_min_fragmentation",
            "rule_type": "SOFT",
            "parameters": {"min_recommended_days": 7, "penalty_score": 1.5},
            "description": "Минимизация дробления отпуска на микро-периоды менее 7 дней.",
            "is_active": True,
        },
        {
            "rule_key": "max_concurrent_shifts",
            "rule_type": "HARD",
            "parameters": {
                "quotas": {
                    "Смена 1 (дневная 07:00-15:30)": 2,
                    "Смена 2 (вечерняя 15:30-00:00)": 2,
                    "Сменный график 2/2": 2,
                    "Пятидневка 5/2 (08:00-17:00)": 2,
                }
            },
            "description": "Квоты одновременных отпусков сотрудников одной смены.",
            "is_active": True,
        },
        {
            "rule_key": "incompatible_employee_groups",
            "rule_type": "HARD",
            "parameters": {"groups": []},
            "description": "Группы сотрудников, чьи отпуска не должны пересекаться (взаимозаменяемые швеи и специалисты).",
            "is_active": True,
        },
    ]

    for r_data in rules_data:
        rule = ScheduleRule(**r_data)
        db.add(rule)
    db.commit()

    # 5. Import Employees from Google Sheets or Synthetic Fallback
    sync_real_employees_to_db(db)
    db.close()


def ensure_default_rules(db):
    """Ensures shift quotas and incompatible employee group rules exist in existing databases."""
    # 1. Shift quotas rule
    shift_rule = db.query(ScheduleRule).filter(ScheduleRule.rule_key == "max_concurrent_shifts").first()
    if not shift_rule:
        shifts = db.query(WorkShift).all()
        quotas = {s.name: getattr(s, "default_quota", 2) or 2 for s in shifts} if shifts else {
            "Смена 1 (дневная 07:00-15:30)": 2,
            "Смена 2 (вечерняя 15:30-00:00)": 2,
            "Сменный график 2/2": 2,
            "Пятидневка 5/2 (08:00-17:00)": 2,
        }
        shift_rule = ScheduleRule(
            rule_key="max_concurrent_shifts",
            rule_type="HARD",
            parameters={"quotas": quotas},
            description="Квоты одновременных отпусков сотрудников одной смены.",
            is_active=True,
        )
        db.add(shift_rule)
        db.commit()

    # 2. Incompatible employee groups rule
    incomp_rule = db.query(ScheduleRule).filter(ScheduleRule.rule_key == "incompatible_employee_groups").first()
    if not incomp_rule:
        incomp_rule = ScheduleRule(
            rule_key="incompatible_employee_groups",
            rule_type="HARD",
            parameters={"groups": []},
            description="Группы сотрудников, чьи отпуска не должны пересекаться (взаимозаменяемые швеи и специалисты).",
            is_active=True,
        )
        db.add(incomp_rule)
        db.commit()


if __name__ == "__main__":
    seed_database()
    print("Garment factory database seeded successfully with Google Sheets workers!")
