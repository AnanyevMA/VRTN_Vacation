import re
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


def test_api_sync_google_sheets(monkeypatch):
    import backend.google_sheets_importer as gsi
    monkeypatch.setattr(gsi, "fetch_csv_from_google_sheet", lambda gid, timeout=10.0: None)

    r = client.post("/api/employees/sync-google-sheets")
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert data["total_imported"] >= 14
    assert "Швея цеха 1 (Анна И.)" in data["workers"]

    # Verify employees list returns the synthetic workers
    emps = client.get("/api/employees").json()
    names = [e["full_name"] for e in emps]
    assert "Швея цеха 1 (Анна И.)" in names
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

    # 2. Known employee phone sends verified native contact -> authenticated
    r_auth = client.post("/api/chat/webhook", json={
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": test_user_id},
            "body": {
                "attachments": [
                    {
                        "type": "contact",
                        "payload": {
                            "tam_info": {
                                "user_id": test_user_id,
                                "phone": target_emp["phone"],
                            }
                        }
                    }
                ]
            }
        }
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
    r_adm_create = client.post("/api/bot-admins", json={
        "phone": "+79112223344",
        "full_name": "Админ Цеха",
        "role_title": "Руководитель",
        "notify_on_new_request": True,
    })
    adm_id = r_adm_create.json().get("id")
    # Admin sends verified native contact to authenticate
    client.post("/api/chat/webhook", json={
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": "admin_max_99"},
            "body": {
                "attachments": [
                    {
                        "type": "contact",
                        "payload": {
                            "tam_info": {
                                "user_id": "admin_max_99",
                                "phone": "+79112223344",
                            }
                        }
                    }
                ]
            }
        }
    })
    # Admin sends /admin
    r_adm_cmd = client.post("/api/chat/webhook", json={
        "user_id": "admin_max_99",
        "text": "/admin",
    })
    assert r_adm_cmd.status_code == 200
    assert "Панель администратора MAX" in r_adm_cmd.json()["text"]
    if adm_id:
        client.delete(f"/api/bot-admins/{adm_id}")



def test_webhook_contact_vcf_and_text_authentication():
    emps = client.get("/api/employees").json()
    emp = emps[1]
    phone_raw = emp["phone"]
    user_id_vcf = f"9900{emp['id']}"

    # 1. MAX contact attachment with vcf_info in message.body.attachments
    vcard_str = f"BEGIN:VCARD\r\nVERSION:3.0\r\nFN:{emp['full_name']}\r\nTEL;TYPE=CELL:{phone_raw}\r\nEND:VCARD"
    r_vcf = client.post("/api/chat/webhook", json={
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": user_id_vcf, "name": emp["full_name"]},
            "body": {
                "attachments": [
                    {
                        "type": "contact",
                        "payload": {
                            "vcf_info": vcard_str,
                        }
                    }
                ]
            }
        }
    })
    assert r_vcf.status_code == 200
    first_name = emp["full_name"].split()[1] if len(emp["full_name"].split()) > 1 else emp["full_name"]
    assert first_name in r_vcf.json()["text"]

    # 2. MAX contact attachment with attachments directly under message
    emp3 = emps[2]
    user_id_vcf2 = f"9900{emp3['id']}"
    vcard_str2 = f"BEGIN:VCARD\r\nVERSION:3.0\r\nFN:{emp3['full_name']}\r\nTEL;TYPE=CELL:{emp3['phone']}\r\nEND:VCARD"
    r_vcf2 = client.post("/api/chat/webhook", json={
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": user_id_vcf2},
            "attachments": [
                {
                    "type": "contact",
                    "payload": {
                        "vcf_info": vcard_str2,
                    }
                }
            ]
        }
    })
    assert r_vcf2.status_code == 200
    first_name3 = emp3["full_name"].split()[1] if len(emp3["full_name"].split()) > 1 else emp3["full_name"]
    assert first_name3 in r_vcf2.json()["text"]

    # 3. Anti-spoofing: plain text phone number does NOT authenticate user
    emp4 = emps[3]
    phone_clean_digits = re.sub(r"[^\d]", "", emp4["phone"])
    phone_8_format = "8" + phone_clean_digits[-10:]
    user_id_text = f"9900{emp4['id']}"
    r_text_phone = client.post("/api/chat/webhook", json={
        "user_id": user_id_text,
        "text": phone_8_format,
    })
    assert r_text_phone.status_code == 200
    assert "отправьте ваш контакт через кнопку" in r_text_phone.json()["text"]
    assert r_text_phone.json().get("request_contact_button") is True
    emp4_check = client.get(f"/api/employees/{emp4['id']}").json()
    assert emp4_check.get("max_user_id") != user_id_text

    # 4. Anti-spoofing: formatted phone in text does NOT authenticate user
    emp5 = emps[4]
    p_last = emp5["phone"][-10:]
    formatted_phone = f"+7 ({p_last[:3]}) {p_last[3:6]}-{p_last[6:8]}-{p_last[8:]}"
    user_id_text2 = f"9900{emp5['id']}"
    r_formatted = client.post("/api/chat/webhook", json={
        "user_id": user_id_text2,
        "text": f"Здравствуйте, мой номер {formatted_phone}",
    })
    assert r_formatted.status_code == 200
    assert "отправьте ваш контакт через кнопку" in r_formatted.json()["text"]
    assert r_formatted.json().get("request_contact_button") is True
    emp5_check = client.get(f"/api/employees/{emp5['id']}").json()
    assert emp5_check.get("max_user_id") != user_id_text2

    # 5. Admin authentication via vCard
    r_adm_create = client.post("/api/bot-admins", json={
        "phone": "+79990000001",
        "full_name": "Администратор Тестовый",
        "role_title": "Системный администратор",
        "notify_on_new_request": True,
    })
    adm_id = r_adm_create.json().get("id")

    vcard_admin = "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Администратор Тестовый\r\nTEL;TYPE=CELL:+79990000001\r\nEND:VCARD"
    r_adm_vcf = client.post("/api/chat/webhook", json={
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": "78699999", "name": "Администратор Тестовый"},
            "body": {
                "attachments": [
                    {
                        "type": "contact",
                        "payload": {
                            "vcf_info": vcard_admin,
                        }
                    }
                ]
            }
        }
    })
    assert r_adm_vcf.status_code == 200
    assert "Администратор Тестовый" in r_adm_vcf.json()["text"]
    assert "авторизованы как администратор" in r_adm_vcf.json()["text"]

    if adm_id:
        client.delete(f"/api/bot-admins/{adm_id}")



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


def test_api_export_and_chat_reset():
    # 1. Verify Excel T-7 export works without pandas
    r_xlsx = client.get("/api/export/excel")
    assert r_xlsx.status_code == 200
    assert "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in r_xlsx.headers.get("content-type", "")
    assert len(r_xlsx.content) > 1000

    # 2. Verify CSV export
    r_csv = client.get("/api/export/csv")
    assert r_csv.status_code == 200
    assert "text/csv" in r_csv.headers.get("content-type", "")

    # 3. Verify chat reset clears draft and chat history auto-seeds AGENT greeting
    emps = client.get("/api/employees").json()
    emp_id = emps[0]["id"]
    r_reset = client.post(f"/api/chat/reset/{emp_id}")
    assert r_reset.status_code == 200

    r_hist = client.get(f"/api/chat/history/{emp_id}")
    assert r_hist.status_code == 200
    msgs = r_hist.json()
    assert len(msgs) == 1
    assert msgs[0]["sender"] == "AGENT"
    assert msgs[0]["payload"]["action"] == "GREETING"




