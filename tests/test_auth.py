import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.seed_data import seed_database
from backend.models import Employee, VacationSlot, ScheduleRule, BotAdmin

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    seed_database()


def test_admin_auth_endpoints_enforcement(monkeypatch):
    """
    Verify that when ADMIN_API_KEY is configured in the environment:
    - Calls to administrative endpoints without X-Admin-Token return HTTP 401.
    - Calls with invalid X-Admin-Token return HTTP 401.
    - Calls with valid X-Admin-Token return HTTP 200/success.
    - Export endpoints support ?token= query parameter as fallback.
    - Non-administrative endpoints remain accessible without tokens.
    """
    secret = "test-super-secret-admin-key"
    monkeypatch.setenv("ADMIN_API_KEY", secret)

    # 1. Bot Admin endpoints
    # POST /api/bot-admins
    payload = {
        "phone": "+79991234567",
        "full_name": "Администратор Тест",
        "role_title": "Админ",
        "notify_on_new_request": True,
    }
    r = client.post("/api/bot-admins", json=payload)
    assert r.status_code == 401
    assert "WWW-Authenticate" in r.headers

    r = client.post("/api/bot-admins", json=payload, headers={"X-Admin-Token": "wrong-secret"})
    assert r.status_code == 401

    r = client.post("/api/bot-admins", json=payload, headers={"X-Admin-Token": secret})
    assert r.status_code == 200
    admin_id = r.json()["id"]

    # PUT /api/bot-admins/{id}
    r = client.put(f"/api/bot-admins/{admin_id}", json={"role_title": "Суперадмин"})
    assert r.status_code == 401

    r = client.put(f"/api/bot-admins/{admin_id}", json={"role_title": "Суперадмин"}, headers={"X-Admin-Token": secret})
    assert r.status_code == 200
    assert r.json()["role_title"] == "Суперадмин"

    # DELETE /api/bot-admins/{id}
    r = client.delete(f"/api/bot-admins/{admin_id}")
    assert r.status_code == 401

    r = client.delete(f"/api/bot-admins/{admin_id}", headers={"X-Admin-Token": secret})
    assert r.status_code == 200

    # 2. Rule endpoints
    # POST /api/rules/action
    r = client.post("/api/rules/action", json={"action": "UPDATE_BLACKOUTS", "payload": {"periods": []}})
    assert r.status_code == 401

    r = client.post("/api/rules/action", json={"action": "UPDATE_BLACKOUTS", "payload": {"periods": []}}, headers={"X-Admin-Token": secret})
    assert r.status_code == 200

    # PUT /api/rules/role-quotas
    r = client.put("/api/rules/role-quotas", json={"Швея (портной)": 3})
    assert r.status_code == 401

    r = client.put("/api/rules/role-quotas", json={"Швея (портной)": 3}, headers={"X-Admin-Token": secret})
    assert r.status_code == 200

    # PUT /api/rules/shift-quotas
    r = client.put("/api/rules/shift-quotas", json={"Смена 1 (дневная 07:00-15:30)": 2})
    assert r.status_code == 401

    r = client.put("/api/rules/shift-quotas", json={"Смена 1 (дневная 07:00-15:30)": 2}, headers={"X-Admin-Token": secret})
    assert r.status_code == 200

    # PUT /api/rules/blackouts
    r = client.put("/api/rules/blackouts", json=[{"start": "2026-08-15", "end": "2026-08-31", "reason": "Школьная форма"}])
    assert r.status_code == 401

    r = client.put("/api/rules/blackouts", json=[{"start": "2026-08-15", "end": "2026-08-31", "reason": "Школьная форма"}], headers={"X-Admin-Token": secret})
    assert r.status_code == 200

    # PUT /api/rules/{id}/toggle
    rules = client.get("/api/rules").json()
    rule_id = rules[0]["id"]
    r = client.put(f"/api/rules/{rule_id}/toggle")
    assert r.status_code == 401

    r = client.put(f"/api/rules/{rule_id}/toggle", headers={"X-Admin-Token": secret})
    assert r.status_code == 200

    # POST /api/rules/incompatible-groups
    emps = client.get("/api/employees").json()
    group_payload = {
        "name": "Тестовая группа непересечения",
        "employee_ids": [emps[0]["id"], emps[1]["id"]],
        "max_concurrent": 1,
        "reason": "Взаимозаменяемые швеи",
    }
    r = client.post("/api/rules/incompatible-groups", json=group_payload)
    assert r.status_code == 401

    r = client.post("/api/rules/incompatible-groups", json=group_payload, headers={"X-Admin-Token": secret})
    assert r.status_code == 200
    group_id = r.json()["id"]

    # DELETE /api/rules/incompatible-groups/{id}
    r = client.delete(f"/api/rules/incompatible-groups/{group_id}")
    assert r.status_code == 401

    r = client.delete(f"/api/rules/incompatible-groups/{group_id}", headers={"X-Admin-Token": secret})
    assert r.status_code == 200

    # 3. Vacation endpoints
    # POST /api/vacations/batch-approve
    r = client.post("/api/vacations/batch-approve?year=2026")
    assert r.status_code == 401

    r = client.post("/api/vacations/batch-approve?year=2026", headers={"X-Admin-Token": secret})
    assert r.status_code == 200

    # PUT /api/vacations/{id}/status & DELETE
    vacs = client.get("/api/vacations?year=2026").json()
    if vacs:
        slot_id = vacs[0]["id"]
        r = client.put(f"/api/vacations/{slot_id}/status?status=APPROVED")
        assert r.status_code == 401

        r = client.put(f"/api/vacations/{slot_id}/status?status=APPROVED", headers={"X-Admin-Token": secret})
        assert r.status_code == 200

        r = client.delete(f"/api/vacations/{slot_id}")
        assert r.status_code == 401

        r = client.delete(f"/api/vacations/{slot_id}", headers={"X-Admin-Token": secret})
        assert r.status_code == 200

    # 4. Employee endpoints
    # POST /api/employees/sync-google-sheets
    import backend.google_sheets_importer as gsi
    monkeypatch.setattr(gsi, "fetch_csv_from_google_sheet", lambda gid, timeout=10.0: None)

    r = client.post("/api/employees/sync-google-sheets")
    assert r.status_code == 401

    r = client.post("/api/employees/sync-google-sheets", headers={"X-Admin-Token": secret})
    assert r.status_code == 200

    # PUT /api/employees/{id}/bot-access
    emp_id = emps[0]["id"]
    r = client.put(f"/api/employees/{emp_id}/bot-access?status=PENDING")
    assert r.status_code == 401

    r = client.put(f"/api/employees/{emp_id}/bot-access?status=PENDING", headers={"X-Admin-Token": secret})
    assert r.status_code == 200

    # 5. Export endpoints
    # GET /api/export/csv
    r = client.get("/api/export/csv")
    assert r.status_code == 401

    r = client.get("/api/export/csv", headers={"X-Admin-Token": secret})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")

    # query parameter fallback: ?token=
    r = client.get(f"/api/export/csv?token={secret}")
    assert r.status_code == 200

    # GET /api/export/excel
    r = client.get("/api/export/excel")
    assert r.status_code == 401

    r = client.get("/api/export/excel", headers={"X-Admin-Token": secret})
    assert r.status_code == 200

    # query parameter fallback: ?token=
    r = client.get(f"/api/export/excel?token={secret}")
    assert r.status_code == 200

    # 6. Public read endpoints remain accessible without tokens
    assert client.get("/api/employees").status_code == 200
    assert client.get("/api/rules").status_code == 200
    assert client.get("/api/vacations").status_code == 200
    assert client.get("/api/export/stats").status_code == 200
    assert client.get("/api/departments").status_code == 200
    assert client.get("/api/roles").status_code == 200
    assert client.get("/api/shifts").status_code == 200


def test_admin_auth_permissive_when_unset(monkeypatch):
    """
    Verify backward-compatibility: when ADMIN_API_KEY is not configured,
    requests pass through without requiring X-Admin-Token.
    """
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)

    r = client.put("/api/rules/role-quotas", json={"Швея (портной)": 3})
    assert r.status_code == 200

    r = client.get("/api/export/csv")
    assert r.status_code == 200
