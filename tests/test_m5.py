"""
Milestone M5 Verification Tests.
Tests DevSecOps hardening configurations:
- deploy/docker-compose.yml
- deploy/Dockerfile
- deploy/nginx_max.conf
- deploy/deploy_vps.sh
"""
from pathlib import Path
import re

DEPLOY_DIR = Path(__file__).resolve().parent.parent / "deploy"


def test_docker_compose_m5_configuration():
    compose_path = DEPLOY_DIR / "docker-compose.yml"
    assert compose_path.exists(), "deploy/docker-compose.yml must exist"
    content = compose_path.read_text(encoding="utf-8")

    # Verify memory limit is 192m
    assert re.search(r"mem_limit:\s*192m", content, re.IGNORECASE), "mem_limit must be 192m"

    # Verify data directory mount (WAL protection) instead of single file
    assert "../data:/app/data" in content, "Must mount ../data:/app/data for SQLite WAL mode protection"
    assert "vacations.db:/app/vacations.db" not in content, "Must not mount single vacations.db file"

    # Verify DATABASE_URL points to /app/data/vacations.db
    assert re.search(r"DATABASE_URL=.*\/app\/data\/vacations\.db", content), "DATABASE_URL must point to /app/data/vacations.db"

    # Verify production and security environment variables
    for var in ["ENVIRONMENT", "CORS_ORIGINS", "ADMIN_API_KEY", "WEBHOOK_SECRET", "GOOGLE_SPREADSHEET_ID"]:
        assert f"- {var}=" in content or f"{var}:" in content or f"- {var}" in content, f"{var} must be passed in environment block"


def test_dockerfile_m5_configuration():
    dockerfile_path = DEPLOY_DIR / "Dockerfile"
    assert dockerfile_path.exists(), "deploy/Dockerfile must exist"
    content = dockerfile_path.read_text(encoding="utf-8")

    # Base image must be python:3.12.8-slim-bookworm
    assert "FROM python:3.12.8-slim-bookworm" in content, "Base image must be python:3.12.8-slim-bookworm"

    # Non-root user appuser with UID 1000
    assert re.search(r"useradd\s+.*-u\s+1000.*appuser", content), "Must create appuser with UID 1000"

    # Data directory created and owned by appuser
    assert "/app/data" in content, "Must create /app/data directory"
    assert re.search(r"chown\s+-R\s+appuser:appuser\s+/app", content), "Must chown /app to appuser"

    # USER appuser directive before EXPOSE / CMD
    user_match = re.search(r"^\s*USER\s+appuser\s*$", content, re.MULTILINE)
    assert user_match, "Must have USER appuser directive"
    cmd_match = re.search(r"^\s*CMD\s+", content, re.MULTILINE)
    assert cmd_match and user_match.start() < cmd_match.start(), "USER appuser must be declared before CMD"


def test_nginx_max_m5_configuration():
    nginx_path = DEPLOY_DIR / "nginx_max.conf"
    assert nginx_path.exists(), "deploy/nginx_max.conf must exist"
    content = nginx_path.read_text(encoding="utf-8")

    # Docs blocking
    assert re.search(r"location\s+~\s+\^/vacation/\(docs\|redoc\|openapi\\\.json\)", content), "Must block docs/redoc/openapi.json"
    assert "return 403;" in content, "Blocked docs must return 403"

    # Webhook location scoped under /vacation/api/chat/webhook (no collision with root /api/)
    assert "location /vacation/api/chat/webhook" in content, "Webhook must be routed under /vacation/api/chat/webhook"
    assert "location /api/chat/webhook" not in content, "Root /api/chat/webhook must not be used to avoid collision with WB FBS"

    # proxy_cache off
    assert "proxy_cache off;" in content, "proxy_cache off must be present"

    # Security headers in /vacation/
    assert 'add_header X-Frame-Options "SAMEORIGIN"' in content
    assert 'add_header X-Content-Type-Options "nosniff"' in content
    assert 'add_header Referrer-Policy "strict-origin-when-cross-origin"' in content
    assert 'add_header X-XSS-Protection "1; mode=block"' in content


def test_deploy_vps_m5_configuration():
    deploy_path = DEPLOY_DIR / "deploy_vps.sh"
    assert deploy_path.exists(), "deploy/deploy_vps.sh must exist"
    content = deploy_path.read_text(encoding="utf-8")

    # Data directory creation
    assert 'mkdir -p "$APP_DIR/data"' in content, "Must create $APP_DIR/data directory"

    # chmod 600 .env enforcement
    assert 'chmod 600 "$APP_DIR/.env"' in content or 'chmod 600 .env' in content, "Must enforce chmod 600 on .env"

    # Memory limits in systemd unit
    assert "MemoryMax=192M" in content, "MemoryMax must be 192M"
    assert "MemoryHigh=160M" in content, "MemoryHigh must be 160M"

    # Linux Namespaces sandboxing
    assert "ProtectSystem=strict" in content, "Must enable ProtectSystem=strict"
    assert "ProtectHome=true" in content, "Must enable ProtectHome=true"
    assert "PrivateTmp=true" in content, "Must enable PrivateTmp=true"
    assert "NoNewPrivileges=true" in content, "Must enable NoNewPrivileges=true"
    assert "ReadWritePaths=$APP_DIR/data $APP_DIR" in content, "Must configure ReadWritePaths"
    assert "Environment=DATABASE_URL=sqlite:///$APP_DIR/data/vacations.db" in content, "Must set DATABASE_URL in service"
