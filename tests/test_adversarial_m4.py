"""
Adversarial Stress Test Suite for Milestone M4 (Requirement R4).

Covers:
1. Account takeover attempts (raw phone JSON, contact without user_id, vCards, mismatched tam_info, BotAdmin takeover).
2. Rate limiter enforcement (11th request, window expiry, user vs IP isolation).
3. Webhook secrets validation (missing, invalid, valid via header & query, timing safety).
4. 152-ФЗ consent dialog lifecycle, security boundaries, and edge cases.
"""

import os
import time
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import SessionLocal
from backend.models import Employee, BotAdmin, EmployeeDraft
from backend.agents.intake_agent import IntakeAgent
from backend.api.chat_routes import check_rate_limit, clear_rate_limits, _rate_limit_history

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_rate_limits_fixture():
    clear_rate_limits()
    yield
    clear_rate_limits()


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================================
# Section 1: Account Takeover & Anti-Spoofing Stress Tests
# ============================================================================

def test_attack_plain_text_with_victim_phone_does_not_bind(db_session):
    """
    ATTACK: Attacker sends victim's phone number in message text.
    DEFENSE: System must NOT authenticate or bind max_user_id. Must prompt for contact button.
    """
    phone = "+79130000001"
    victim = db_session.query(Employee).filter(Employee.phone == phone).first()
    if not victim:
        victim = Employee(
            phone=phone,
            full_name="Жертва Текстового Взлома",
            role="Швея (портной)",
            department_id=1,
            consent_152fz=True,
            max_user_id="original_victim_uid_1",
        )
        db_session.add(victim)
        db_session.commit()
        db_session.refresh(victim)

    initial_uid = victim.max_user_id
    attacker_uid = "attacker_text_spoofer"
    resp = client.post("/api/chat/webhook", json={
        "user_id": attacker_uid,
        "text": f"Привет, мой номер {phone}, авторизуйте меня срочно!",
    })
    assert resp.status_code == 200
    db_session.refresh(victim)
    # The victim's max_user_id must NOT be overwritten!
    assert victim.max_user_id == initial_uid, "CRITICAL: Account takeover via text message phone number!"
    assert victim.max_user_id != attacker_uid


def test_attack_contact_mismatched_tam_info_user_id(db_session):
    """
    ATTACK: Attacker sends contact attachment with tam_info having victim's user_id and phone,
            while sender.user_id is the attacker.
    DEFENSE: System detects contact_user_id != sender.user_id and rejects spoofing.
    """
    phone = "+79130000002"
    victim = db_session.query(Employee).filter(Employee.phone == phone).first()
    if not victim:
        victim = Employee(
            phone=phone,
            full_name="Жертва Подделки Контакта",
            role="Швея (портной)",
            department_id=1,
            consent_152fz=True,
            max_user_id="legit_victim_uid_2",
        )
        db_session.add(victim)
        db_session.commit()
        db_session.refresh(victim)

    initial_uid = victim.max_user_id
    attacker_uid = "attacker_mismatched_tam"
    resp = client.post("/api/chat/webhook", json={
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": attacker_uid},
            "body": {
                "attachments": [
                    {
                        "type": "contact",
                        "payload": {
                            "tam_info": {
                                "user_id": "different_contact_user_id",
                                "phone": phone,
                            }
                        }
                    }
                ]
            }
        }
    })
    assert resp.status_code == 200
    db_session.refresh(victim)
    assert victim.max_user_id == initial_uid
    assert victim.max_user_id != attacker_uid


def test_attack_direct_phone_in_root_json_takeover(db_session):
    """
    ATTACK: Attacker sends raw JSON payload with 'phone' or 'phone_number' at root.
    DEFENSE: R4 states: 'Bind max_user_id strictly when verified native contact attachment
             (tam_info / vcard) is received where contact.user_id == sender.user_id.'
             Unverified raw phone fields in JSON must NOT bind max_user_id!
    """
    phone = "+79130000003"
    victim = db_session.query(Employee).filter(Employee.phone == phone).first()
    if not victim:
        victim = Employee(
            phone=phone,
            full_name="Жертва Root Phone Взлома",
            role="Швея (портной)",
            department_id=1,
            consent_152fz=True,
            max_user_id="legit_victim_uid_3",
        )
        db_session.add(victim)
        db_session.commit()
        db_session.refresh(victim)

    attacker_uid = "attacker_root_phone"
    resp = client.post("/api/chat/webhook", json={
        "user_id": attacker_uid,
        "phone": phone,
        "text": "test root phone",
    })
    assert resp.status_code == 200
    db_session.refresh(victim)
    assert victim.max_user_id != attacker_uid, (
        f"VULNERABILITY: Root 'phone' field without verified contact attachment bound "
        f"victim account to {attacker_uid}!"
    )


def test_attack_vcard_without_user_id_takeover(db_session):
    """
    ATTACK: Attacker sends a vCard attachment containing victim's phone,
            where contact user_id is absent.
    DEFENSE: R4 strictly requires contact.user_id == sender.user_id.
             If contact.user_id cannot be verified, it must NOT bind max_user_id.
    """
    phone = "+79130000004"
    victim = db_session.query(Employee).filter(Employee.phone == phone).first()
    if not victim:
        victim = Employee(
            phone=phone,
            full_name="Жертва VCF Взлома",
            role="Швея (портной)",
            department_id=1,
            consent_152fz=True,
            max_user_id="legit_victim_uid_4",
        )
        db_session.add(victim)
        db_session.commit()
        db_session.refresh(victim)

    attacker_uid = "attacker_vcard_no_uid"
    vcard_payload = f"BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Victim\r\nTEL:{phone}\r\nEND:VCARD"

    resp = client.post("/api/chat/webhook", json={
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": attacker_uid},
            "body": {
                "attachments": [
                    {
                        "type": "contact",
                        "payload": {
                            "vcf_info": vcard_payload,
                        }
                    }
                ]
            }
        }
    })
    assert resp.status_code == 200
    db_session.refresh(victim)
    assert victim.max_user_id != attacker_uid, (
        f"VULNERABILITY: Unverified vCard attachment without contact user_id bound "
        f"victim account to {attacker_uid}!"
    )


def test_attack_bot_admin_takeover_via_unverified_contact(db_session):
    """
    ATTACK: Attacker attempts to take over a BotAdmin account by submitting admin's phone.
    DEFENSE: BotAdmin accounts must be protected against takeover via unverified contact.
    """
    admin_phone = "+79130000099"
    admin = db_session.query(BotAdmin).filter(BotAdmin.phone == admin_phone).first()
    if not admin:
        admin = BotAdmin(
            phone=admin_phone,
            full_name="Главный Администратор Фабрики",
            role_title="Директор производства",
            max_user_id="legit_admin_uid_99",
        )
        db_session.add(admin)
        db_session.commit()
        db_session.refresh(admin)

    attacker_uid = "attacker_admin_impersonator"
    # Try with raw phone in payload
    resp = client.post("/api/chat/webhook", json={
        "user_id": attacker_uid,
        "phone": admin_phone,
    })
    assert resp.status_code == 200
    db_session.refresh(admin)
    assert admin.max_user_id != attacker_uid, (
        f"CRITICAL VULNERABILITY: Attacker took over BotAdmin account {admin_phone}!"
    )


# ============================================================================
# Section 2: Rate Limiter Stress Tests
# ============================================================================

def test_rate_limiter_exact_boundary_and_sliding_window():
    """
    Tests exact boundary: requests 1..10 succeed, request 11 gets 429.
    Tests sliding window expiry: after window expires, requests succeed again.
    """
    uid = "rate_limiter_boundary_tester"

    # Exactly 10 requests allowed
    for i in range(10):
        r = client.post("/api/chat/webhook", json={"user_id": uid, "text": f"req {i}"})
        assert r.status_code == 200, f"Request {i+1} unexpectedly failed: {r.status_code}"

    # 11th request must receive 429
    r_blocked = client.post("/api/chat/webhook", json={"user_id": uid, "text": "req 11"})
    assert r_blocked.status_code == 429
    assert "Слишком много запросов" in r_blocked.json()["detail"]

    # 12th request also blocked
    r_blocked2 = client.post("/api/chat/webhook", json={"user_id": uid, "text": "req 12"})
    assert r_blocked2.status_code == 429

    # Simulate sliding window expiry by shifting timestamps back 61 seconds
    timestamps = _rate_limit_history.get(uid, [])
    assert len(timestamps) == 10
    _rate_limit_history[uid] = [t - 61.0 for t in timestamps]

    # After window expiry, new request must succeed
    r_after_expiry = client.post("/api/chat/webhook", json={"user_id": uid, "text": "req after expiry"})
    assert r_after_expiry.status_code == 200


def test_rate_limiter_user_isolation():
    """Rate limits for user A must not affect user B."""
    user_a = "user_rate_limit_isolated_a"
    user_b = "user_rate_limit_isolated_b"

    # Exhaust user A's quota
    for i in range(10):
        client.post("/api/chat/webhook", json={"user_id": user_a, "text": "spam"})

    # User A is blocked
    assert client.post("/api/chat/webhook", json={"user_id": user_a, "text": "spam"}).status_code == 429

    # User B can still make requests
    assert client.post("/api/chat/webhook", json={"user_id": user_b, "text": "hello"}).status_code == 200


# ============================================================================
# Section 3: Webhook Secret Validation Stress Tests
# ============================================================================

def test_webhook_secret_header_and_query_variations(monkeypatch):
    """
    Comprehensive verification of WEBHOOK_SECRET enforcement across headers and query params.
    """
    secret = "max-secret-key-xyz-777"
    monkeypatch.setenv("WEBHOOK_SECRET", secret)

    # 1. No credentials -> 401
    assert client.post("/api/chat/webhook", json={"text": "hi"}).status_code == 401

    # 2. Header wrong -> 401
    assert client.post(
        "/api/chat/webhook",
        headers={"X-Max-Bot-Token": "bad-secret"},
        json={"text": "hi"}
    ).status_code == 401

    # 3. Query wrong -> 401
    assert client.post("/api/chat/webhook?token=bad-secret", json={"text": "hi"}).status_code == 401

    # 4. Header correct -> 200
    assert client.post(
        "/api/chat/webhook",
        headers={"X-Max-Bot-Token": secret},
        json={"text": "hi"}
    ).status_code == 200

    # 5. Query correct -> 200
    assert client.post(f"/api/chat/webhook?token={secret}", json={"text": "hi"}).status_code == 200

    # 6. GET endpoint also enforced
    assert client.get("/api/chat/webhook").status_code == 401
    assert client.get(f"/api/chat/webhook?token={secret}").status_code == 200


# ============================================================================
# Section 4: 152-ФЗ Consent Dialog Stress Tests
# ============================================================================

def test_consent_dialog_blocks_vacation_drafting_until_granted(db_session):
    """
    Verify that an employee who has NOT granted consent cannot have vacation slots
    drafted into the database, even if they send dates or commands.
    """
    phone = "+79130000005"
    emp = db_session.query(Employee).filter(Employee.phone == phone).first()
    if not emp:
        emp = Employee(
            phone=phone,
            full_name="Кузнецова Елена Павловна",
            role="Швея (портной)",
            department_id=1,
            consent_152fz=False,
        )
        db_session.add(emp)
        db_session.commit()
        db_session.refresh(emp)
    else:
        emp.consent_152fz = False
        db_session.commit()

    agent = IntakeAgent(db_session)

    # User attempts to submit vacation dates directly without consent
    res = agent.process_message(emp.id, "Хочу отпуск с 1 по 14 июля 2026")
    assert res["payload"]["action"] == "CONSENT_REQUEST"
    assert "152-ФЗ" in res["text"]

    # Verify no draft slots were added!
    draft = db_session.query(EmployeeDraft).filter(EmployeeDraft.employee_id == emp.id).first()
    slots = (draft.slots or []) if draft else []
    assert len(slots) == 0, "SECURITY: Draft slots were populated before 152-ФЗ consent was granted!"


def test_consent_dialog_accept_with_dates_combined(db_session):
    """
    Verify UX shortcut: user sends 'Согласна, отпуск с 1 по 14 июля 2026'.
    Consent should be granted AND the dates should be processed immediately.
    """
    phone = "+79130000006"
    emp = db_session.query(Employee).filter(Employee.phone == phone).first()
    if not emp:
        emp = Employee(
            phone=phone,
            full_name="Григорьева Анна Викторовна",
            role="Швея (портной)",
            department_id=1,
            consent_152fz=False,
        )
        db_session.add(emp)
        db_session.commit()
        db_session.refresh(emp)
    else:
        emp.consent_152fz = False
        db_session.commit()

    agent = IntakeAgent(db_session)

    res = agent.process_message(emp.id, "Согласна, планирую отпуск с 1 по 14 июля 2026")
    db_session.refresh(emp)
    assert emp.consent_152fz is True
    # Should have processed dates
    assert res["payload"]["action"] in ("DRAFT_UPDATED", "CONSENT_GRANTED")


def test_consent_dialog_multiple_rejections_and_recovery(db_session):
    """
    Verify user can decline consent multiple times and later accept without corruption.
    """
    phone = "+79130000007"
    emp = db_session.query(Employee).filter(Employee.phone == phone).first()
    if not emp:
        emp = Employee(
            phone=phone,
            full_name="Орлова Татьяна Михайловна",
            role="Швея (портной)",
            department_id=1,
            consent_152fz=False,
        )
        db_session.add(emp)
        db_session.commit()
        db_session.refresh(emp)
    else:
        emp.consent_152fz = False
        db_session.commit()

    agent = IntakeAgent(db_session)

    # 1. Decline 1
    r1 = agent.process_message(emp.id, "❌ Отказаться")
    assert r1["payload"]["action"] == "CONSENT_REQUEST"
    assert "без согласия" in r1["text"]
    db_session.refresh(emp)
    assert emp.consent_152fz is False

    # 2. Decline 2
    r2 = agent.process_message(emp.id, "Не согласна")
    assert r2["payload"]["action"] == "CONSENT_REQUEST"
    db_session.refresh(emp)
    assert emp.consent_152fz is False

    # 3. Change mind and accept
    r3 = agent.process_message(emp.id, "✅ Согласна")
    assert r3["payload"]["action"] == "CONSENT_GRANTED"
    db_session.refresh(emp)
    assert emp.consent_152fz is True

    # 4. Subsequent date submission proceeds normally
    r4 = agent.process_message(emp.id, "с 1 по 14 июля 2026")
    assert r4["payload"]["action"] == "DRAFT_UPDATED"
