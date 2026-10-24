import os
import re
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.main import app
from backend.database import SessionLocal, migrate_db, engine
from backend.models import Employee, BotAdmin, EmployeeDraft
from backend.agents.intake_agent import IntakeAgent
from backend.api.chat_routes import mask_phone, check_rate_limit, clear_rate_limits

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_rate_limits():
    """Ensure rate limiter state is fresh for every test."""
    clear_rate_limits()
    yield
    clear_rate_limits()


# ============================================================================
# 1. WEBHOOK_SECRET Enforcement Tests (Requirement R4)
# ============================================================================

def test_webhook_secret_enforcement_when_configured(monkeypatch):
    """When WEBHOOK_SECRET is set, requests without valid token must receive HTTP 401."""
    monkeypatch.setenv("WEBHOOK_SECRET", "super-secret-max-token-2026")

    # 1. No token supplied -> 401
    r_no_token = client.post("/api/chat/webhook", json={"text": "ping"})
    assert r_no_token.status_code == 401
    assert "Invalid webhook secret" in r_no_token.json()["detail"]

    # 2. Invalid header token -> 401
    r_bad_header = client.post(
        "/api/chat/webhook",
        headers={"X-Max-Bot-Token": "wrong-token"},
        json={"text": "ping"},
    )
    assert r_bad_header.status_code == 401

    # 3. Valid header token -> 200
    r_valid_header = client.post(
        "/api/chat/webhook",
        headers={"X-Max-Bot-Token": "super-secret-max-token-2026"},
        json={"text": "ping"},
    )
    assert r_valid_header.status_code == 200

    # 4. Valid query parameter token -> 200
    r_valid_param = client.post(
        "/api/chat/webhook?token=super-secret-max-token-2026",
        json={"text": "ping"},
    )
    assert r_valid_param.status_code == 200


def test_webhook_secret_allows_unauthenticated_when_unset(monkeypatch):
    """When WEBHOOK_SECRET is unset or empty, requests are allowed without token (dev/test)."""
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)

    r = client.post("/api/chat/webhook", json={"text": "ping"})
    assert r.status_code == 200


# ============================================================================
# 2. Account Takeover & Anti-Spoofing Tests (Requirement R4)
# ============================================================================

def test_anti_spoofing_text_message_with_phone_rejected():
    """
    Sending a plain text message containing another person's phone number
    must NOT bind or authenticate the user. It must prompt for native contact sharing.
    """
    db = SessionLocal()
    try:
        # Create an employee
        emp = db.query(Employee).filter(Employee.phone == "+79135550011").first()
        if not emp:
            emp = Employee(
                phone="+79135550011",
                full_name="Смирнова Мария Павловна",
                role="Швея (портной)",
                department_id=1,
                consent_152fz=True,
            )
            db.add(emp)
            db.commit()
            db.refresh(emp)

        attacker_uid = "attacker_max_user_999"

        # Attacker tries to send Maria's phone in plain text
        r = client.post("/api/chat/webhook", json={
            "user_id": attacker_uid,
            "text": "Здравствуйте, мой телефон +79135550011 авторизуйте меня",
        })
        assert r.status_code == 200
        # Must return prompt asking to send contact via the button
        assert "отправьте ваш контакт через кнопку" in r.json()["text"]
        assert r.json().get("request_contact_button") is True

        # Verify attacker_uid was NOT bound to Maria's account in DB!
        db.refresh(emp)
        assert emp.max_user_id != attacker_uid
    finally:
        db.close()


def test_anti_spoofing_contact_with_mismatched_user_id_rejected():
    """
    If a contact attachment contains a user_id that differs from the sender's user_id,
    the webhook must reject it as a spoofing attempt and NOT bind the account.
    """
    db = SessionLocal()
    try:
        emp = db.query(Employee).filter(Employee.phone == "+79135550022").first()
        if not emp:
            emp = Employee(
                phone="+79135550022",
                full_name="Ковалева Надежда Ивановна",
                role="Швея (портной)",
                department_id=1,
                consent_152fz=True,
            )
            db.add(emp)
            db.commit()
            db.refresh(emp)

        sender_user_id = "attacker_user_888"
        victim_contact_user_id = "victim_user_777"

        # Attacker sends contact attachment with tam_info belonging to victim
        r = client.post("/api/chat/webhook", json={
            "update_type": "message_created",
            "message": {
                "sender": {"user_id": sender_user_id},
                "body": {
                    "attachments": [
                        {
                            "type": "contact",
                            "payload": {
                                "tam_info": {
                                    "user_id": victim_contact_user_id,
                                    "phone": "+79135550022",
                                }
                            }
                        }
                    ]
                }
            }
        })
        assert r.status_code == 200
        data = r.json()
        assert data.get("status") == "error"
        assert "чужого контакта не допускается" in data.get("text", "")

        # Verify emp was NOT bound to attacker's user_id
        db.refresh(emp)
        assert emp.max_user_id != sender_user_id
    finally:
        db.close()


def test_legitimate_contact_with_matching_user_id_authenticates():
    """When sender.user_id matches contact.user_id, authentication succeeds."""
    db = SessionLocal()
    try:
        emp = db.query(Employee).filter(Employee.phone == "+79135550033").first()
        if not emp:
            emp = Employee(
                phone="+79135550033",
                full_name="Васильева Вера Сергеевна",
                role="Швея (портной)",
                department_id=1,
                consent_152fz=True,
            )
            db.add(emp)
            db.commit()
            db.refresh(emp)

        legit_user_id = "legit_user_555"

        r = client.post("/api/chat/webhook", json={
            "update_type": "message_created",
            "message": {
                "sender": {"user_id": legit_user_id},
                "body": {
                    "attachments": [
                        {
                            "type": "contact",
                            "payload": {
                                "tam_info": {
                                    "user_id": legit_user_id,
                                    "phone": "+79135550033",
                                }
                            }
                        }
                    ]
                }
            }
        })
        assert r.status_code == 200
        assert "Вера" in r.json()["text"]

        db.refresh(emp)
        assert emp.max_user_id == legit_user_id
    finally:
        db.close()


# ============================================================================
# 3. Sliding Window Rate Limiter Tests (Requirement R4)
# ============================================================================

def test_sliding_window_rate_limiter_blocks_11th_request():
    """
    In-memory rate limiter allows 10 requests per minute per user_id/IP.
    The 11th request must receive HTTP 429 with Russian retry message.
    """
    test_uid = "rate_limit_test_user_42"

    # 10 requests must succeed
    for i in range(10):
        r = client.post("/api/chat/webhook", json={"user_id": test_uid, "text": f"msg {i}"})
        assert r.status_code == 200, f"Request {i+1} failed with status {r.status_code}"

    # 11th request must be rate-limited (HTTP 429)
    r_11 = client.post("/api/chat/webhook", json={"user_id": test_uid, "text": "msg 11"})
    assert r_11.status_code == 429
    assert "Слишком много запросов" in r_11.json()["detail"]

    # Different user must NOT be blocked
    r_other = client.post("/api/chat/webhook", json={"user_id": "rate_limit_test_user_43", "text": "hello"})
    assert r_other.status_code == 200


# ============================================================================
# 4. 152-ФЗ Consent Dialog Tests (Requirement R4)
# ============================================================================

def test_152fz_consent_dialog_flow():
    """
    Tests the 152-ФЗ consent dialog lifecycle:
    1. First interaction: asks for consent with inline buttons.
    2. Decline: explains consent requirement under 152-ФЗ.
    3. Accept: marks consent_152fz = True in DB, welcomes user to plan vacation.
    4. Next message: processes vacation dates without asking for consent again.
    """
    db = SessionLocal()
    test_phone = "+79139991122"
    try:
        # Pre-cleanup in case a previous aborted run left the record in vacations.db
        existing = db.query(Employee).filter(Employee.phone == test_phone).first()
        if existing:
            db.query(EmployeeDraft).filter(EmployeeDraft.employee_id == existing.id).delete()
            db.delete(existing)
            db.commit()

        emp = Employee(
            phone=test_phone,
            full_name="Тестова Полина Дмитриевна",
            role="Швея (портной)",
            department_id=1,
            consent_152fz=False,
        )
        db.add(emp)
        db.commit()
        db.refresh(emp)

        agent = IntakeAgent(db)

        # Step 1: User sends first message without consent
        res1 = agent.process_message(emp.id, "Здравствуйте, хочу в отпуск")
        assert res1["payload"]["action"] == "CONSENT_REQUEST"
        assert "152-ФЗ" in res1["text"]
        assert "Пожалуйста, подтвердите согласие" in res1["text"]
        db.refresh(emp)
        assert emp.consent_152fz is False

        # Step 2: User declines consent
        res2 = agent.process_message(emp.id, "❌ Отказаться")
        assert res2["payload"]["action"] == "CONSENT_REQUEST"
        assert "без согласия на обработку персональных данных" in res2["text"]
        db.refresh(emp)
        assert emp.consent_152fz is False

        # Step 3: User accepts consent
        res3 = agent.process_message(emp.id, "✅ Согласна")
        assert res3["payload"]["action"] == "CONSENT_GRANTED"
        assert "Согласие на обработку персональных данных (152-ФЗ) принято" in res3["text"]
        db.refresh(emp)
        assert emp.consent_152fz is True

        # Step 4: Now user can send vacation dates normally
        res4 = agent.process_message(emp.id, "с 1 по 14 июля 2026")
        assert res4["payload"]["action"] == "DRAFT_UPDATED"
        assert res4["payload"]["accum_days"] == 14
        assert "14" in res4["text"]
    finally:
        # Post-cleanup ensures test idempotency on subsequent pytest runs
        try:
            cleanup_emp = db.query(Employee).filter(Employee.phone == test_phone).first()
            if cleanup_emp:
                db.query(EmployeeDraft).filter(EmployeeDraft.employee_id == cleanup_emp.id).delete()
                db.delete(cleanup_emp)
                db.commit()
        except Exception:
            db.rollback()
        db.close()


# ============================================================================
# 5. Phone Number Masking Tests
# ============================================================================

def test_mask_phone_formats():
    """Verify mask_phone formats various Russian numbers to +7 913 *** ** 01."""
    assert mask_phone("+79131234501") == "+7 913 *** ** 01"
    assert mask_phone("89131234501") == "+7 913 *** ** 01"
    assert mask_phone("+7 (913) 123-45-01") == "+7 913 *** ** 01"
    assert mask_phone("79131234501") == "+7 913 *** ** 01"
    assert mask_phone("") == ""
    assert mask_phone(None) == ""


# ============================================================================
# 6. Database Migration & Column Verification
# ============================================================================

def test_consent_152fz_column_exists_in_database():
    """Verify consent_152fz column exists in SQLite employees table."""
    migrate_db()
    with engine.connect() as conn:
        cols = conn.execute(text("PRAGMA table_info(employees)")).fetchall()
        col_names = [c[1] for c in cols]
        assert "consent_152fz" in col_names, f"Column consent_152fz not found in employees table: {col_names}"
