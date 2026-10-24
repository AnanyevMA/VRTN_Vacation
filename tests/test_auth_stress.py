import secrets
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.seed_data import seed_database
import backend.google_sheets_importer as gsi

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    seed_database()


ADMIN_ENDPOINTS = [
    ("POST", "/api/bot-admins", {}),
    ("PUT", "/api/bot-admins/1", {}),
    ("DELETE", "/api/bot-admins/1", None),
    ("POST", "/api/rules/action", {}),
    ("PUT", "/api/rules/role-quotas", {}),
    ("PUT", "/api/rules/shift-quotas", {}),
    ("PUT", "/api/rules/blackouts", []),
    ("PUT", "/api/rules/1/toggle", None),
    ("POST", "/api/rules/incompatible-groups", {}),
    ("DELETE", "/api/rules/incompatible-groups/1", None),
    ("POST", "/api/vacations/batch-approve", None),
    ("PUT", "/api/vacations/1/status", None),
    ("DELETE", "/api/vacations/1", None),
    ("POST", "/api/employees", {}),
    ("PUT", "/api/employees/1", {}),
    ("DELETE", "/api/employees/1", None),
    ("POST", "/api/employees/sync-google-sheets", None),
    ("PUT", "/api/employees/1/bot-access", None),
    ("GET", "/api/export/csv", None),
    ("GET", "/api/export/excel", None),
]

PUBLIC_READ_ENDPOINTS = [
    "/api/employees",
    "/api/rules",
    "/api/vacations",
    "/api/export/stats",
    "/api/departments",
    "/api/roles",
    "/api/shifts",
    "/api/bot-admins",
    "/api/rules/incompatible-groups",
]


def _call(method: str, path: str, json_body=None, headers=None):
    if method == "GET":
        return client.get(path, headers=headers)
    elif method == "POST":
        return client.post(path, json=json_body, headers=headers)
    elif method == "PUT":
        return client.put(path, json=json_body, headers=headers)
    elif method == "DELETE":
        return client.delete(path, headers=headers)
    raise ValueError(f"Unknown method {method}")


def test_stress_all_20_protected_endpoints_missing_token(monkeypatch):
    """Every single administrative endpoint must return 401 when ADMIN_API_KEY is configured."""
    secret = "adm-secr3t-k3y-99!"
    monkeypatch.setenv("ADMIN_API_KEY", secret)

    for method, path, body in ADMIN_ENDPOINTS:
        res = _call(method, path, body)
        assert res.status_code == 401, f"{method} {path} returned {res.status_code}, expected 401"
        assert res.headers.get("www-authenticate") == "Bearer"
        assert "Неверный или отсутствующий ключ" in res.json().get("detail", "")


@pytest.mark.parametrize("bad_header", [
    "",
    "   ",
    "\t\r\n",
    "Bearer adm-secr3t-k3y-99!",
    "adm-secr3t-k3y",
    "adm-secr3t-k3y-99!extra",
    "ADM-SECR3T-K3Y-99!",
    "' OR '1'='1",
    "admin'--",
    "A" * 10000,
    "wrong_key_12345",
])
def test_stress_malformed_and_hostile_headers(bad_header, monkeypatch):
    """Tokens with leading/trailing mismatches, casing differences, injections, or length floods must fail with 401."""
    secret = "adm-secr3t-k3y-99!"
    monkeypatch.setenv("ADMIN_API_KEY", secret)

    res = client.get("/api/export/csv", headers={"X-Admin-Token": bad_header})
    assert res.status_code == 401
    assert "Неверный или отсутствующий ключ" in res.json().get("detail", "")


@pytest.mark.parametrize("bad_token_param", [
    "",
    "   ",
    "wrong",
    "ADM-SECR3T-K3Y-99!",
    "' OR '1'='1",
    "A" * 5000,
    "секретный_ключ",
    "%00%01%02",
])
def test_stress_malformed_query_param_token(bad_token_param, monkeypatch):
    """Malformed ?token= query parameter values must return 401."""
    secret = "adm-secr3t-k3y-99!"
    monkeypatch.setenv("ADMIN_API_KEY", secret)

    res = client.get(f"/api/export/csv?token={bad_token_param}")
    assert res.status_code == 401


def test_header_casing_insensitivity(monkeypatch):
    """HTTP headers are case-insensitive. x-admin-token and X-ADMIN-TOKEN must authenticate successfully."""
    secret = "my-secret-key"
    monkeypatch.setenv("ADMIN_API_KEY", secret)

    for h_name in ["X-Admin-Token", "x-admin-token", "X-ADMIN-TOKEN", "X-aDmIn-ToKeN"]:
        res = client.get("/api/export/csv", headers={h_name: secret})
        assert res.status_code == 200, f"Header casing {h_name} failed with {res.status_code}"


def test_token_in_query_param_on_export_and_mutations(monkeypatch):
    """?token= query param must work for export and mutations."""
    secret = "my-secret-key"
    monkeypatch.setenv("ADMIN_API_KEY", secret)

    # 1. Export CSV
    r1 = client.get(f"/api/export/csv?token={secret}")
    assert r1.status_code == 200

    # 2. Export Excel
    r2 = client.get(f"/api/export/excel?token={secret}")
    assert r2.status_code == 200

    # 3. Vacation batch-approve
    r3 = client.post(f"/api/vacations/batch-approve?token={secret}&year=2026")
    assert r3.status_code == 200


def test_header_vs_query_precedence_and_interaction(monkeypatch):
    """
    Stress-test precedence between X-Admin-Token and ?token=:
    - Valid header + valid query -> 200
    - Valid header + invalid query -> 200 (header takes precedence)
    - Invalid header + valid query -> 401 (attacker cannot bypass invalid header using query param)
    - Whitespace header + valid query -> 200 (empty header falls back to query param)
    """
    secret = "correct-token"
    monkeypatch.setenv("ADMIN_API_KEY", secret)

    # Valid header + invalid query -> 200
    res = client.get(f"/api/export/csv?token=wrong", headers={"X-Admin-Token": secret})
    assert res.status_code == 200

    # Invalid header + valid query -> 401
    res = client.get(f"/api/export/csv?token={secret}", headers={"X-Admin-Token": "wrong"})
    assert res.status_code == 401

    # Whitespace header + valid query -> 200
    res = client.get(f"/api/export/csv?token={secret}", headers={"X-Admin-Token": "   "})
    assert res.status_code == 200


def test_timing_attack_verification_oracle(monkeypatch):
    """Verify secrets.compare_digest is actively invoked for constant-time comparison."""
    secret = "secure-password-12345"
    monkeypatch.setenv("ADMIN_API_KEY", secret)

    with patch("secrets.compare_digest", wraps=secrets.compare_digest) as mock_compare:
        res = client.get("/api/export/csv", headers={"X-Admin-Token": "secure-password-wrong"})
        assert res.status_code == 401
        assert mock_compare.called
        args, _ = mock_compare.call_args
        assert args in (
            ("secure-password-wrong", secret),
            (b"secure-password-wrong", secret.encode("utf-8")),
        )


def test_public_routes_remain_accessible_under_admin_lock(monkeypatch):
    """When ADMIN_API_KEY is configured, public read endpoints and chat endpoints must not be blocked."""
    secret = "locked-down-key"
    monkeypatch.setenv("ADMIN_API_KEY", secret)

    for path in PUBLIC_READ_ENDPOINTS:
        res = client.get(path)
        assert res.status_code == 200, f"Public endpoint {path} was blocked: {res.status_code}"

    # Verify phone endpoint (public)
    res = client.post("/api/auth/verify_phone", json={"phone": "+79130000001"})
    assert res.status_code == 200

    # Verify chat history (public)
    emps = client.get("/api/employees").json()
    emp_id = emps[0]["id"]
    res = client.get(f"/api/chat/history/{emp_id}")
    assert res.status_code == 200


def test_permissive_mode_matrix(monkeypatch):
    """Verify permissive mode when ADMIN_API_KEY is unset, empty, or whitespace."""
    for empty_val in [None, "", "   ", "\t "]:
        if empty_val is None:
            monkeypatch.delenv("ADMIN_API_KEY", raising=False)
        else:
            monkeypatch.setenv("ADMIN_API_KEY", empty_val)

        res = client.get("/api/export/csv")
        assert res.status_code == 200, f"Failed for ADMIN_API_KEY={empty_val!r}"


def test_non_ascii_admin_key_passphrase(monkeypatch):
    """
    Verify that non-ASCII (e.g. Russian/Cyrillic) admin keys in environment and query parameters
    are supported and do not raise TypeError in secrets.compare_digest.
    """
    secret = "секретный_ключ_хакасия_2026"
    monkeypatch.setenv("ADMIN_API_KEY", secret)

    # Valid token via query param must authenticate (200)
    res = client.get(f"/api/export/csv?token={secret}")
    assert res.status_code == 200

    # Wrong token must reject cleanly (401) without crashing (500)
    res2 = client.get("/api/export/csv?token=wrong_secret")
    assert res2.status_code == 401

