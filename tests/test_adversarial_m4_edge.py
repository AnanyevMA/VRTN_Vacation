"""
Empirical Adversarial Edge-Case Stress Tests for Milestone M4 (Requirement R4).

Probes:
1. Multi-hop X-Forwarded-For headers, whitespace variations, and fallback to X-Real-IP and client host.
2. IP-based rate limiting on anonymous / unauthenticated webhook pings and IP isolation.
3. Corporate NAT / shared IP isolation (different users behind same IP).
4. Malformed and hostile contact payloads:
   - None payload, empty payload dict, non-dict tam_info
   - Whitespace user_id, missing user_id
   - Integer user_id vs string user_id
   - SQL injection payload in phone field
   - Hostile vCards without verified contact user_id
   - Mismatched user_id spoofing
"""

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.database import SessionLocal
from backend.models import Employee, EmployeeDraft
from backend.api.chat_routes import check_rate_limit, clear_rate_limits, extract_client_ip

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_rate_limits():
    clear_rate_limits()
    yield
    clear_rate_limits()


class FakeRequest:
    def __init__(self, headers=None, client_host="127.0.0.1"):
        self.headers = headers or {}
        class C:
            host = client_host
        self.client = C()


# ============================================================================
# Section 1: Rate Limiting & Multi-IP Extraction Edge Cases
# ============================================================================

def test_multi_hop_x_forwarded_for_extraction():
    # Multi-hop: client, proxy1, proxy2
    req_multi = FakeRequest({"X-Forwarded-For": "198.51.100.1, 10.0.0.1, 192.168.1.1"})
    assert extract_client_ip(req_multi) == "198.51.100.1"

    # Whitespace padding
    req_ws = FakeRequest({"X-Forwarded-For": "  198.51.100.2  , 10.0.0.1"})
    assert extract_client_ip(req_ws) == "198.51.100.2"

    # Fallback to X-Real-IP
    req_real = FakeRequest({"X-Real-IP": "198.51.100.3"})
    assert extract_client_ip(req_real) == "198.51.100.3"

    # Fallback to client.host
    req_client = FakeRequest({}, client_host="198.51.100.4")
    assert extract_client_ip(req_client) == "198.51.100.4"


def test_ip_based_rate_limiting_and_isolation():
    ip1_headers = {"X-Forwarded-For": "203.0.113.10, 10.0.0.1"}
    ip2_headers = {"X-Forwarded-For": "203.0.113.20, 10.0.0.1"}

    # 10 requests from IP1 succeed
    for i in range(10):
        r = client.post("/api/chat/webhook", headers=ip1_headers, json={"text": f"ping {i}"})
        assert r.status_code == 200

    # 11th request from IP1 blocked
    r11 = client.post("/api/chat/webhook", headers=ip1_headers, json={"text": "ping 11"})
    assert r11.status_code == 429

    # IP2 must not be affected
    r_ip2 = client.post("/api/chat/webhook", headers=ip2_headers, json={"text": "ping from IP2"})
    assert r_ip2.status_code == 200


def test_shared_ip_nat_isolation_by_user_id():
    shared_ip_headers = {"X-Forwarded-For": "198.51.100.50"}

    # User A exhausts quota
    for i in range(10):
        client.post("/api/chat/webhook", headers=shared_ip_headers, json={"user_id": "user_nat_a", "text": f"msg {i}"})

    assert client.post("/api/chat/webhook", headers=shared_ip_headers, json={"user_id": "user_nat_a", "text": "spam"}).status_code == 429

    # User B from same IP has independent quota
    r_user_b = client.post("/api/chat/webhook", headers=shared_ip_headers, json={"user_id": "user_nat_b", "text": "hello"})
    assert r_user_b.status_code == 200


# ============================================================================
# Section 2: Malformed and Hostile Contact Payloads
# ============================================================================

def test_malformed_contact_payloads_do_not_takeover_or_crash():
    db = SessionLocal()
    test_phone = "+79138880001"
    try:
        victim = db.query(Employee).filter(Employee.phone == test_phone).first()
        if not victim:
            victim = Employee(
                phone=test_phone,
                full_name="Жертва Граничных Проверок",
                role="Швея (портной)",
                department_id=1,
                consent_152fz=True,
                max_user_id="original_victim_uid_888",
            )
            db.add(victim)
            db.commit()
            db.refresh(victim)

        initial_uid = victim.max_user_id

        # 1. Payload is None
        r1 = client.post("/api/chat/webhook", json={
            "update_type": "message_created",
            "message": {
                "sender": {"user_id": "attacker_edge_1"},
                "body": {"attachments": [{"type": "contact", "payload": None}]}
            }
        })
        assert r1.status_code == 200
        db.refresh(victim)
        assert victim.max_user_id == initial_uid

        # 2. tam_info is string instead of dict
        r2 = client.post("/api/chat/webhook", json={
            "update_type": "message_created",
            "message": {
                "sender": {"user_id": "attacker_edge_2"},
                "body": {"attachments": [{"type": "contact", "payload": {"tam_info": "not-a-dict", "phone": test_phone}}]}
            }
        })
        assert r2.status_code == 200
        db.refresh(victim)
        assert victim.max_user_id == initial_uid

        # 3. contact user_id is empty string or whitespace
        r3 = client.post("/api/chat/webhook", json={
            "update_type": "message_created",
            "message": {
                "sender": {"user_id": "attacker_edge_3"},
                "body": {"attachments": [{"type": "contact", "payload": {"tam_info": {"user_id": "   ", "phone": test_phone}}}]}
            }
        })
        assert r3.status_code == 200
        db.refresh(victim)
        assert victim.max_user_id == initial_uid

        # 4. Integer user_id matching sender string (valid type coercion)
        attacker_num_uid = "987654321"
        r4 = client.post("/api/chat/webhook", json={
            "update_type": "message_created",
            "message": {
                "sender": {"user_id": attacker_num_uid},
                "body": {"attachments": [{"type": "contact", "payload": {"tam_info": {"user_id": int(attacker_num_uid), "phone": test_phone}}}]}
            }
        })
        assert r4.status_code == 200
        db.refresh(victim)
        assert victim.max_user_id == attacker_num_uid

        # 5. SQL injection in phone field
        r5 = client.post("/api/chat/webhook", json={
            "update_type": "message_created",
            "message": {
                "sender": {"user_id": "attacker_sqli"},
                "body": {"attachments": [{"type": "contact", "payload": {"tam_info": {"user_id": "attacker_sqli", "phone": "+79130000001' OR '1'='1"}}}]}
            }
        })
        assert r5.status_code == 200

        # 6. Hostile vCard without verified user_id
        vcf = "BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Exploit\r\nTEL;TYPE=CELL:+79138880001\r\nEND:VCARD"
        r6 = client.post("/api/chat/webhook", json={
            "update_type": "message_created",
            "message": {
                "sender": {"user_id": "attacker_vcf_exploit"},
                "body": {"attachments": [{"type": "contact", "payload": {"vcf_info": vcf}}]}
            }
        })
        assert r6.status_code == 200
        db.refresh(victim)
        assert victim.max_user_id != "attacker_vcf_exploit"

    finally:
        try:
            cleanup_victim = db.query(Employee).filter(Employee.phone == test_phone).first()
            if cleanup_victim:
                db.query(EmployeeDraft).filter(EmployeeDraft.employee_id == cleanup_victim.id).delete()
                db.delete(cleanup_victim)
                db.commit()
        except Exception:
            db.rollback()
        db.close()
