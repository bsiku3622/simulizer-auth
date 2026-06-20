import secrets
from datetime import datetime, timezone

from fastapi import Cookie, Header, HTTPException, status
from jose import JWTError

from auth import decode_jwt, decode_recovery_jwt
from config import SERVICE_SECRET
from database import get_conn


def require_service(x_service_secret: str | None = Header(default=None, alias="X-Service-Secret")) -> None:
    """Guard internal service-to-service endpoints (e.g. AI server calls).

    The caller must present the shared service secret. Identity of the acting
    user is established separately via the forwarded user JWT.
    """
    if x_service_secret is None or not secrets.compare_digest(x_service_secret, SERVICE_SECRET):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service credentials")


def _resolve_user_from_token(token: str) -> dict:
    user_id, token_iat = decode_jwt(token)

    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ? AND deleted_at IS NULL", (user_id,)
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    if row["token_issued_at"]:
        valid_from = datetime.fromisoformat(row["token_issued_at"]).replace(tzinfo=timezone.utc)
        if token_iat < valid_from:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token revoked")

    return dict(row)


def get_current_user(token: str | None = Cookie(default=None, alias="token")) -> dict:
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        return _resolve_user_from_token(token)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def get_optional_user(token: str | None = Cookie(default=None, alias="token")) -> dict | None:
    if token is None:
        return None
    try:
        return _resolve_user_from_token(token)
    except (JWTError, HTTPException):
        return None


def get_recovery_user(recovery_token: str | None = Cookie(default=None, alias="recovery_token")) -> dict:
    if recovery_token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No recovery session")
    try:
        user_id = decode_recovery_jwt(recovery_token)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid recovery token")

    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ? AND deleted_at IS NOT NULL", (user_id,)
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recovery session not found")

    return dict(row)
