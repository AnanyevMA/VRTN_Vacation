import os
import secrets
from typing import Optional
from fastapi import Header, Query, HTTPException, status


def require_admin(
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    token: Optional[str] = Query(None),
) -> None:
    """
    Lightweight administrative authorization dependency.
    Validates X-Admin-Token header or ?token= query parameter against ADMIN_API_KEY.
    If ADMIN_API_KEY is not set or empty, requests are permitted (backward-compatible / local dev mode).
    If ADMIN_API_KEY is set, requests without valid token fail with HTTP 401.
    """
    admin_api_key = os.getenv("ADMIN_API_KEY", "").strip()
    if not admin_api_key:
        return None

    provided_token = None
    if isinstance(x_admin_token, str) and x_admin_token.strip():
        provided_token = x_admin_token.strip()
    elif isinstance(token, str) and token.strip():
        provided_token = token.strip()

    if not provided_token or not secrets.compare_digest(provided_token.encode("utf-8"), admin_api_key.encode("utf-8")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный или отсутствующий ключ администратора",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return None
