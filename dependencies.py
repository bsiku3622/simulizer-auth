from fastapi import Cookie, HTTPException, status
from jose import JWTError

from auth import decode_jwt, decode_recovery_jwt
from database import get_conn


def get_current_user(token: str | None = Cookie(default=None, alias="token")) -> dict:
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        user_id = decode_jwt(token)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ? AND deleted_at IS NULL", (user_id,)
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return dict(row)


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
