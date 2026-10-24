import io
import os
import re
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

from backend.main import app
from backend.auth import require_admin
from backend.api.export_routes import sanitize_formula_injection, sanitize_row
from backend.services.llm_service import sanitize_prompt_pii
from backend.schemas import (
    ChatMessageIn,
    EmployeeCreate,
    EmployeeUpdate,
    JobRoleCreate,
    JobRoleUpdate,
    WorkShiftCreate,
    WorkShiftUpdate,
    OptimizeVacationRequest,
    ScheduleRuleCreate,
    ScheduleRuleUpdate,
)

client = TestClient(app)


# ============================================================================
# 1. Formula Injection (CWE-1236) Stress Tests
# ============================================================================

@pytest.mark.parametrize("payload", [
    "=cmd|' /C calc'!A0",
    "@SUM(1,2)",
    "+12345",
    "-500",
])
def test_formula_injection_standard_prefixes_escaped(payload):
    """Standard formula injection prefixes must be escaped with a single quote."""
    escaped = sanitize_formula_injection(payload)
    assert escaped.startswith("'"), f"Failed to escape payload: {payload!r}"
    assert escaped == f"'{payload}"


@pytest.mark.parametrize("whitespace_payload", [
    " =cmd|' /C calc'!A0",
    "   =cmd|' /C calc'!A0",
    "\t=cmd|' /C calc'!A0",
    "\r\n=cmd|' /C calc'!A0",
    " @SUM(1,2)",
    "\t@SUM(1,2)",
    " +12345",
    "\t+12345",
    " -500",
    "\t-500",
    "\t=1+1",
    "\r=1+1",
])
def test_formula_injection_leading_whitespace_vulnerability(whitespace_payload):
    """
    Empirical test: Does sanitize_formula_injection escape formula triggers
    when preceded by leading whitespace, tabs, or carriage returns?
    Spreadsheet software (Excel, LibreOffice) trims leading whitespace when opening CSV/Excel
    and executes the formula.
    """
    res = sanitize_formula_injection(whitespace_payload)
    escaped = isinstance(res, str) and (res.startswith("'") or res.lstrip().startswith("'"))
    assert escaped, f"VULNERABILITY: Formula payload with leading whitespace/tab was NOT escaped: {whitespace_payload!r} -> {res!r}"


def test_benign_inputs_not_corrupted_by_sanitizer():
    """Verify that numbers, None, and normal Russian strings are untouched."""
    assert sanitize_formula_injection("Иванова Анна") == "Иванова Анна"
    assert sanitize_formula_injection(123) == 123
    assert sanitize_formula_injection(0) == 0
    assert sanitize_formula_injection(-5) == -5  # integer, not string
    assert sanitize_formula_injection(None) is None
    assert sanitize_formula_injection("") == ""


# ============================================================================
# 2. Prompt PII Stripping (152-ФЗ) Adversarial Tests
# ============================================================================

def test_prompt_pii_multiline_and_russian_phones():
    """Test various Russian phone formats across multiple lines."""
    multiline_text = (
        "Заявка на отпуск:\n"
        "Сотрудник: Петрова Елена\n"
        "Телефон 1: +7 913 999 88 77\n"
        "Телефон 2: 8 (913) 777-66-55\n"
        "Телефон 3: 89136665544\n"
        "Телефон 4: +7-913-555-44-33\n"
        "Почта: elena.petrova@factory-sew.ru\n"
        "Желаемый период: первые две недели августа"
    )
    cleaned = sanitize_prompt_pii(multiline_text)
    
    assert "+7 913 999 88 77" not in cleaned
    assert "8 (913) 777-66-55" not in cleaned
    assert "89136665544" not in cleaned
    assert "+7-913-555-44-33" not in cleaned
    assert "elena.petrova@factory-sew.ru" not in cleaned
    assert "первые две недели августа" in cleaned
    assert "Петрова Елена" in cleaned


@pytest.mark.parametrize("phone_format", [
    "+7 913 111 22 33",
    "8 913 111 22 33",
    "8(913)111-22-33",
    "+7(913)111-22-33",
    "+79131112233",
    "89131112233",
    "+7-913-111-22-33",
    "8-913-111-22-33",
])
def test_prompt_pii_russian_mobile_formats(phone_format):
    """All standard Russian mobile formats must be stripped."""
    text = f"Позвоните мне по номеру {phone_format} насчет отпуска"
    cleaned = sanitize_prompt_pii(text)
    assert phone_format not in cleaned
    assert "насчет отпуска" in cleaned


@pytest.mark.parametrize("exotic_pii", [
    "8.913.111.22.33",           # Dotted phone format
    "anna@фабрика.рф",            # Cyrillic IDN email domain
    "секретарь@швея-хакасия.рф",  # Cyrillic localpart and domain
])
def test_prompt_pii_exotic_formats(exotic_pii):
    """
    Test dotted phone numbers and Cyrillic (.рф) emails.
    Documents whether current regex covers Russian IDN emails or dotted formats.
    """
    text = f"Контакты: {exotic_pii}, отпуск в сентябре"
    cleaned = sanitize_prompt_pii(text)
    assert exotic_pii not in cleaned, f"PII leak detected: {exotic_pii} was not stripped from prompt"


def test_prompt_pii_false_positive_date_destruction():
    """
    CRITICAL EMPIRICAL TEST:
    Does PHONE_REGEX accidentally destroy valid vacation dates formatted as ISO or hyphenated?
    e.g. '2026-07-01' or '01-07-2026'
    """
    iso_text = "Прошу отпуск с 2026-07-01 по 2026-07-14 на 14 дней"
    cleaned_iso = sanitize_prompt_pii(iso_text)
    
    hyphen_text = "Прошу отпуск с 01-07-2026 по 14-07-2026 на две недели"
    cleaned_hyphen = sanitize_prompt_pii(hyphen_text)
    
    # If the date was destroyed, the LLM will never receive the date intervals!
    assert "2026-07-01" in cleaned_iso, f"FALSE POSITIVE: ISO date 2026-07-01 was wiped by PII filter: {cleaned_iso!r}"
    assert "01-07-2026" in cleaned_hyphen, f"FALSE POSITIVE: Hyphenated date 01-07-2026 was wiped by PII filter: {cleaned_hyphen!r}"


# ============================================================================
# 3. Pydantic Schema Boundary Validation Tests
# ============================================================================

def test_chat_message_in_boundaries():
    """ChatMessageIn: exact 500 characters passes, 501 characters rejects."""
    # 500 ASCII characters -> must pass
    c500 = ChatMessageIn(employee_id=1, message="X" * 500)
    assert len(c500.message) == 500
    
    # 501 ASCII characters -> must fail
    with pytest.raises(ValidationError) as exc_info:
        ChatMessageIn(employee_id=1, message="X" * 501)
    assert "string_too_long" in str(exc_info.value)
    
    # 500 Cyrillic characters (1000 UTF-8 bytes) -> must pass (Python len counts characters)
    c500_cyr = ChatMessageIn(employee_id=1, message="ш" * 500)
    assert len(c500_cyr.message) == 500
    
    # 501 Cyrillic characters -> must fail
    with pytest.raises(ValidationError):
        ChatMessageIn(employee_id=1, message="ш" * 501)


def test_employee_total_vacation_days_exact_boundaries():
    """EmployeeCreate / EmployeeUpdate: boundary conditions for total_vacation_days (1..120)."""
    # 1 -> pass
    e1 = EmployeeCreate(phone="+79130000010", full_name="Тест", role="Швея", department_id=1, total_vacation_days=1)
    assert e1.total_vacation_days == 1
    
    # 120 -> pass
    e120 = EmployeeCreate(phone="+79130000011", full_name="Тест", role="Швея", department_id=1, total_vacation_days=120)
    assert e120.total_vacation_days == 120
    
    # 0 -> fail
    with pytest.raises(ValidationError):
        EmployeeCreate(phone="+79130000012", full_name="Тест", role="Швея", department_id=1, total_vacation_days=0)
        
    # 121 -> fail
    with pytest.raises(ValidationError):
        EmployeeCreate(phone="+79130000013", full_name="Тест", role="Швея", department_id=1, total_vacation_days=121)
        
    # -1 -> fail
    with pytest.raises(ValidationError):
        EmployeeCreate(phone="+79130000014", full_name="Тест", role="Швея", department_id=1, total_vacation_days=-1)


def test_quotas_exact_boundaries():
    """JobRole and WorkShift default_quota boundaries (0..50)."""
    # 0 -> pass
    assert JobRoleCreate(name="Швея-1", default_quota=0).default_quota == 0
    assert WorkShiftCreate(name="Смена-1", default_quota=0).default_quota == 0
    
    # 50 -> pass
    assert JobRoleCreate(name="Швея-2", default_quota=50).default_quota == 50
    assert WorkShiftCreate(name="Смена-2", default_quota=50).default_quota == 50
    
    # -1 -> fail
    with pytest.raises(ValidationError):
        JobRoleCreate(name="Швея-3", default_quota=-1)
    with pytest.raises(ValidationError):
        WorkShiftCreate(name="Смена-3", default_quota=-1)
        
    # 51 -> fail
    with pytest.raises(ValidationError):
        JobRoleCreate(name="Швея-4", default_quota=51)
    with pytest.raises(ValidationError):
        WorkShiftCreate(name="Смена-4", default_quota=51)


def test_window_search_days_exact_boundaries():
    """OptimizeVacationRequest and ScheduleRule boundaries (1..90)."""
    # 1 -> pass
    assert OptimizeVacationRequest(employee_id=1, requested_slots=[], window_search_days=1).window_search_days == 1
    assert ScheduleRuleCreate(rule_key="r1", rule_type="HARD", parameters={"window_search_days": 1}).parameters["window_search_days"] == 1
    
    # 90 -> pass
    assert OptimizeVacationRequest(employee_id=1, requested_slots=[], window_search_days=90).window_search_days == 90
    assert ScheduleRuleCreate(rule_key="r2", rule_type="HARD", parameters={"window_search_days": 90}).parameters["window_search_days"] == 90
    
    # 0 -> fail
    with pytest.raises(ValidationError):
        OptimizeVacationRequest(employee_id=1, requested_slots=[], window_search_days=0)
    with pytest.raises(ValidationError):
        ScheduleRuleCreate(rule_key="r3", rule_type="HARD", parameters={"window_search_days": 0})
        
    # 91 -> fail
    with pytest.raises(ValidationError):
        OptimizeVacationRequest(employee_id=1, requested_slots=[], window_search_days=91)
    with pytest.raises(ValidationError):
        ScheduleRuleCreate(rule_key="r4", rule_type="HARD", parameters={"window_search_days": 91})


# ============================================================================
# 4. Cyrillic / UTF-8 Auth Token Tests
# ============================================================================

def test_cyrillic_token_in_query_param(monkeypatch):
    """Cyrillic admin key passed via ?token= query parameter."""
    secret = "секретный_ключ_хакасия_2026"
    monkeypatch.setenv("ADMIN_API_KEY", secret)
    
    # Exact match -> 200
    res = client.get(f"/api/export/csv?token={secret}")
    assert res.status_code == 200
    
    # Typo in Cyrillic key -> 401
    res_wrong = client.get("/api/export/csv?token=секретный_ключ_ошибка")
    assert res_wrong.status_code == 401


def test_cyrillic_token_homoglyph_attack(monkeypatch):
    """
    Homoglyph attack: Replace Cyrillic 'с' (U+0441) with Latin 'c' (U+0063).
    Must return 401, never 200.
    """
    secret = "секрет"  # All Cyrillic
    monkeypatch.setenv("ADMIN_API_KEY", secret)
    
    # 'c' is Latin U+0063 instead of Cyrillic 'с' U+0441
    homoglyph_token = "\u0063\u0435\u043A\u0440\u0435\u0442"
    res = client.get(f"/api/export/csv?token={homoglyph_token}")
    assert res.status_code == 401


def test_cyrillic_token_in_http_header_transport_limitation(monkeypatch):
    """
    RFC 7230 / ASGI transport documentation:
    Passing non-ASCII (Cyrillic) token inside HTTP Header 'X-Admin-Token'.
    HTTP/1.1 header values are restricted to ASCII/Latin-1. HTTP client libraries
    (httpx, requests) raise UnicodeEncodeError before transmission.
    Therefore, Cyrillic administrative tokens are supported strictly via ?token= query parameter.
    """
    secret = "секретный_ключ_хакасия_2026"
    monkeypatch.setenv("ADMIN_API_KEY", secret)
    
    # Direct Cyrillic string in header raises UnicodeEncodeError in httpx
    with pytest.raises(UnicodeEncodeError):
        client.get("/api/export/csv", headers={"X-Admin-Token": secret})
