import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.seed_data import seed_database

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    seed_database()


def test_api_departments_crud():
    # List
    r_list = client.get("/api/departments")
    assert r_list.status_code == 200
    assert len(r_list.json()) >= 6

    # Create
    r_create = client.post("/api/departments", json={
        "name": "Экспериментальный цех",
        "code": "EXP",
        "manager_name": "Тестов Т.Т.",
        "description": "Пошив образцов",
    })
    assert r_create.status_code == 200
    dept_id = r_create.json()["id"]

    # Update
    r_up = client.put(f"/api/departments/{dept_id}", json={"manager_name": "Обновленный О.О."})
    assert r_up.status_code == 200
    assert r_up.json()["manager_name"] == "Обновленный О.О."

    # Delete
    r_del = client.delete(f"/api/departments/{dept_id}")
    assert r_del.status_code == 200


def test_api_roles_crud_and_unified_rules_sync():
    # 1. Create Role
    r_create = client.post("/api/roles", json={
        "name": "Вышивальщица",
        "default_quota": 3,
        "description": "Машинная вышивка",
        "is_critical": False,
    })
    assert r_create.status_code == 200
    role_id = r_create.json()["id"]

    # Check that role exists in /api/roles
    r_roles = client.get("/api/roles").json()
    assert any(r["name"] == "Вышивальщица" and r["default_quota"] == 3 for r in r_roles)

    # Check that role exists in /api/rules ScheduleRule quotas
    r_rules = client.get("/api/rules").json()
    quota_rule = next(r for r in r_rules if r["rule_key"] == "max_concurrent_roles")
    assert "Вышивальщица" in quota_rule["parameters"]["quotas"]
    assert quota_rule["parameters"]["quotas"]["Вышивальщица"] == 3

    # 2. Update quota via /api/rules/role-quotas
    updated_quotas = quota_rule["parameters"]["quotas"]
    updated_quotas["Вышивальщица"] = 4
    r_up_quota = client.put("/api/rules/role-quotas", json=updated_quotas)
    assert r_up_quota.status_code == 200

    # Verify that JobRole table was updated
    r_roles2 = client.get("/api/roles").json()
    vyshiv = next(r for r in r_roles2 if r["name"] == "Вышивальщица")
    assert vyshiv["default_quota"] == 4

    # 3. Delete Role
    r_del = client.delete(f"/api/roles/{role_id}")
    assert r_del.status_code == 200

    # Verify deleted from /api/roles
    r_roles_after = client.get("/api/roles").json()
    assert not any(r["name"] == "Вышивальщица" for r in r_roles_after)

    # Verify deleted from /api/rules quotas!
    r_rules_after = client.get("/api/rules").json()
    quota_rule_after = next(r for r in r_rules_after if r["rule_key"] == "max_concurrent_roles")
    assert "Вышивальщица" not in quota_rule_after["parameters"]["quotas"]


def test_api_shifts_crud():
    # List
    r_list = client.get("/api/shifts")
    assert r_list.status_code == 200
    assert len(r_list.json()) >= 3


def test_api_vacations_with_year():
    r_2026 = client.get("/api/vacations?year=2026")
    assert r_2026.status_code == 200

    r_2027 = client.get("/api/vacations?year=2027")
    assert r_2027.status_code == 200


def test_api_sync_google_sheets():
    r = client.post("/api/employees/sync-google-sheets")
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert data["total_imported"] >= 14
    assert "Анохина Марина" in data["workers"]
    assert "Артамонова Наталья" in data["workers"]

    # Verify employees list returns the real workers
    emps = client.get("/api/employees").json()
    names = [e["full_name"] for e in emps]
    assert "Анохина Марина" in names
    assert "Иванова Татьяна Сергеевна" not in names


def test_api_bot_admins_crud():
    # 1. Create Bot Admin
    r_create = client.post("/api/bot-admins", json={
        "phone": "+79998887766",
        "full_name": "Ковалева Татьяна Ивановна",
        "role_title": "Начальник швейного цеха №1",
        "notify_on_new_request": True,
    })
    assert r_create.status_code == 200
    admin_id = r_create.json()["id"]
    assert r_create.json()["phone"] == "+79998887766"

    # 2. List Bot Admins
    r_list = client.get("/api/bot-admins")
    assert r_list.status_code == 200
    admins = r_list.json()
    assert any(a["id"] == admin_id and a["full_name"] == "Ковалева Татьяна Ивановна" for a in admins)

    # 3. Update Bot Admin
    r_update = client.put(f"/api/bot-admins/{admin_id}", json={
        "role_title": "Главный технолог",
        "notify_on_new_request": False,
    })
    assert r_update.status_code == 200
    assert r_update.json()["role_title"] == "Главный технолог"

    # 4. Delete Bot Admin
    r_del = client.delete(f"/api/bot-admins/{admin_id}")
    assert r_del.status_code == 200
    r_list_after = client.get("/api/bot-admins").json()
    assert not any(a["id"] == admin_id for a in r_list_after)


def test_api_employee_bot_access_toggle():
    emps = client.get("/api/employees").json()
    assert len(emps) > 0
    target_emp = emps[0]
    emp_id = target_emp["id"]

    # Change to PENDING
    r_pending = client.put(f"/api/employees/{emp_id}/bot-access?status=PENDING")
    assert r_pending.status_code == 200
    assert r_pending.json()["bot_access"] == "PENDING"

    emp_check = next(e for e in client.get("/api/employees").json() if e["id"] == emp_id)
    assert emp_check["bot_access"] == "PENDING"

    # Change to BLOCKED
    r_block = client.put(f"/api/employees/{emp_id}/bot-access?status=BLOCKED")
    assert r_block.status_code == 200
    assert r_block.json()["bot_access"] == "BLOCKED"

    # Restore to APPROVED
    r_approve = client.put(f"/api/employees/{emp_id}/bot-access?status=APPROVED")
    assert r_approve.status_code == 200
    assert r_approve.json()["bot_access"] == "APPROVED"


def test_webhook_access_control():
    emps = client.get("/api/employees").json()
    target_emp = emps[0]
    test_user_id = f"max_user_test_{target_emp['id']}"

    # 1. Unknown phone returns rejected message
    r_unknown = client.post("/api/chat/webhook", json={
        "user_id": test_user_id,
        "phone": "+79000000000",
    })
    assert r_unknown.status_code == 200
    assert "не найден в базе" in r_unknown.json()["text"]

    # 2. Known employee phone sends contact -> authenticated
    r_auth = client.post("/api/chat/webhook", json={
        "user_id": test_user_id,
        "phone": target_emp["phone"],
    })
    assert r_auth.status_code == 200
    first_name = target_emp["full_name"].split()[1] if len(target_emp["full_name"].split()) > 1 else target_emp["full_name"]
    assert first_name in r_auth.json()["text"]

    # 3. When bot_access is PENDING -> chat messages blocked with pending notification
    client.put(f"/api/employees/{target_emp['id']}/bot-access?status=PENDING")
    r_pending_msg = client.post("/api/chat/webhook", json={
        "user_id": test_user_id,
        "text": "Хочу в отпуск в июле",
    })
    assert r_pending_msg.status_code == 200
    assert "ожидает подтверждения администратором" in r_pending_msg.json()["text"]

    # 4. When bot_access is BLOCKED -> chat messages blocked
    client.put(f"/api/employees/{target_emp['id']}/bot-access?status=BLOCKED")
    r_blocked_msg = client.post("/api/chat/webhook", json={
        "user_id": test_user_id,
        "text": "Хочу в отпуск в июле",
    })
    assert r_blocked_msg.status_code == 200
    assert "заблокирован администратором" in r_blocked_msg.json()["text"]

    # 5. When bot_access is APPROVED -> chat messages processed successfully
    client.put(f"/api/employees/{target_emp['id']}/bot-access?status=APPROVED")
    r_approved_msg = client.post("/api/chat/webhook", json={
        "user_id": test_user_id,
        "text": "Хочу в отпуск с 10 по 23 августа 2026",
    })
    assert r_approved_msg.status_code == 200
    assert len(r_approved_msg.json()["text"]) > 0

    # 6. Admin command test
    client.post("/api/bot-admins", json={
        "phone": "+79112223344",
        "full_name": "Админ Цеха",
        "role_title": "Руководитель",
        "notify_on_new_request": True,
    })
    # Admin sends phone to authenticate
    client.post("/api/chat/webhook", json={
        "user_id": "admin_max_99",
        "phone": "+79112223344",
    })
    # Admin sends /admin
    r_adm_cmd = client.post("/api/chat/webhook", json={
        "user_id": "admin_max_99",
        "text": "/admin",
    })
    assert r_adm_cmd.status_code == 200
    assert "Панель администратора MAX" in r_adm_cmd.json()["text"]


def test_api_shift_quotas():
    # 1. Update shift quotas
    shifts = client.get("/api/shifts").json()
    assert len(shifts) >= 2
    shift_name = shifts[0]["name"]

    r = client.put("/api/rules/shift-quotas", json={shift_name: 3})
    assert r.status_code == 200

    # Verify WorkShift updated
    shifts_after = client.get("/api/shifts").json()
    sh = next(s for s in shifts_after if s["name"] == shift_name)
    assert sh["default_quota"] == 3


def test_api_incompatible_employee_groups():
    emps = client.get("/api/employees").json()
    assert len(emps) >= 3
    e1, e2, e3 = emps[0]["id"], emps[1]["id"], emps[2]["id"]

    # 1. Create group
    r_create = client.post("/api/rules/incompatible-groups", json={
        "name": "Бригада закройщиков",
        "employee_ids": [e1, e2, e3],
        "max_concurrent": 1,
        "reason": "Взаимозаменяемые на автоматическом раскройном комплексе",
    })
    assert r_create.status_code == 200
    group_data = r_create.json()
    gid = group_data["id"]
    assert len(group_data["employee_names"]) == 3

    # 2. List groups
    r_list = client.get("/api/rules/incompatible-groups")
    assert r_list.status_code == 200
    groups = r_list.json()
    assert any(g["id"] == gid and g["name"] == "Бригада закройщиков" for g in groups)

    # 3. Delete group
    r_del = client.delete(f"/api/rules/incompatible-groups/{gid}")
    assert r_del.status_code == 200
    groups_after = client.get("/api/rules/incompatible-groups").json()
    assert not any(g["id"] == gid for g in groups_after)



