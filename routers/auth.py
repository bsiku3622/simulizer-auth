import os
import shutil
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import RedirectResponse

from auth import (
    create_jwt,
    create_recovery_jwt,
    exchange_code,
    get_google_userinfo,
    google_oauth_url,
    validate_domain,
)
from database import get_conn, FILE_STORAGE_PATH
from dependencies import get_current_user, get_recovery_user
from schemas import RecoveryUserOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
TOKEN_EXPIRE_SECONDS = 7 * 24 * 60 * 60
RECOVERY_TOKEN_EXPIRE_SECONDS = 10 * 60
SOFT_DELETE_RETENTION_DAYS = 30

_DELETE_STATE = "delete_account"


def _set_token_cookie(response: Response, token: str):
    response.set_cookie(
        key="token", value=token,
        httponly=True, secure=COOKIE_SECURE, samesite="lax",
        max_age=TOKEN_EXPIRE_SECONDS,
    )


def _set_recovery_cookie(response: Response, token: str):
    response.set_cookie(
        key="recovery_token", value=token,
        httponly=True, secure=COOKIE_SECURE, samesite="lax",
        max_age=RECOVERY_TOKEN_EXPIRE_SECONDS,
    )


def _hard_delete_user(user_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    user_dir = FILE_STORAGE_PATH / str(user_id)
    if user_dir.exists():
        shutil.rmtree(user_dir)


def _parse_deleted_at(deleted_at_str: str) -> datetime:
    return datetime.fromisoformat(deleted_at_str.replace(" ", "T")).replace(tzinfo=timezone.utc)


@router.get("/google")
def login_google():
    return RedirectResponse(google_oauth_url())


@router.get("/google/delete")
def login_google_for_delete():
    return RedirectResponse(google_oauth_url(state=_DELETE_STATE, prompt="select_account"))


@router.get("/google/callback")
def google_callback(code: str | None = None, error: str | None = None, state: str | None = None):
    if error or not code:
        return RedirectResponse(f"{FRONTEND_URL}/login?error=oauth_denied")

    try:
        tokens = exchange_code(code)
        userinfo = get_google_userinfo(tokens["access_token"])
    except Exception:
        return RedirectResponse(f"{FRONTEND_URL}/login?error=oauth_failed")

    email: str = userinfo.get("email", "")
    if not validate_domain(email):
        return RedirectResponse(f"{FRONTEND_URL}/login?error=unauthorized_domain")

    google_id = userinfo["sub"]

    # ── Delete intent: soft-delete the re-authenticated user ──────────────
    if state == _DELETE_STATE:
        with get_conn() as conn:
            row = conn.execute("SELECT id FROM users WHERE google_id = ?", (google_id,)).fetchone()
            if row is None:
                return RedirectResponse(f"{FRONTEND_URL}/login")
            conn.execute(
                "UPDATE users SET deleted_at = datetime('now'), updated_at = datetime('now') WHERE id = ?",
                (row["id"],),
            )
        response = RedirectResponse(f"{FRONTEND_URL}/login?account_deleted=1")
        response.delete_cookie("token")
        return response

    # ── Normal login: check for soft-deleted account ───────────────────────
    with get_conn() as conn:
        existing = conn.execute("SELECT * FROM users WHERE google_id = ?", (google_id,)).fetchone()

    if existing and existing["deleted_at"]:
        deleted_at = _parse_deleted_at(existing["deleted_at"])
        age = datetime.now(timezone.utc) - deleted_at

        if age < timedelta(days=SOFT_DELETE_RETENTION_DAYS):
            # Within retention window → offer recovery
            recovery_token = create_recovery_jwt(existing["id"])
            resp = RedirectResponse(f"{FRONTEND_URL}/recover")
            _set_recovery_cookie(resp, recovery_token)
            return resp
        else:
            # Past retention window → hard delete and fall through to registration
            _hard_delete_user(existing["id"])

    # ── Upsert user ────────────────────────────────────────────────────────
    name = userinfo.get("name", email)
    picture_url = userinfo.get("picture")

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO users (google_id, email, name, picture_url, last_login_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            ON CONFLICT(google_id) DO UPDATE SET
                email          = excluded.email,
                name           = excluded.name,
                picture_url    = excluded.picture_url,
                last_login_at  = datetime('now'),
                updated_at     = datetime('now')
            """,
            (google_id, email, name, picture_url),
        )
        row = conn.execute("SELECT id FROM users WHERE google_id = ?", (google_id,)).fetchone()

    token = create_jwt(row["id"])
    response = RedirectResponse(f"{FRONTEND_URL}/dashboard")
    _set_token_cookie(response, token)
    return response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response):
    response.delete_cookie("token")


@router.get("/me", response_model=UserOut)
def me(user: dict = Depends(get_current_user)):
    return UserOut(**user)


# ── Recovery endpoints ─────────────────────────────────────────────────────

@router.get("/recover/me", response_model=RecoveryUserOut)
def recover_me(user: dict = Depends(get_recovery_user)):
    deleted_at = _parse_deleted_at(user["deleted_at"])
    expiry = deleted_at + timedelta(days=SOFT_DELETE_RETENTION_DAYS)
    days_remaining = max(0, (expiry - datetime.now(timezone.utc)).days)
    return RecoveryUserOut(**UserOut(**user).model_dump(), days_remaining=days_remaining)


@router.post("/recover/confirm", status_code=status.HTTP_204_NO_CONTENT)
def recover_confirm(response: Response, user: dict = Depends(get_recovery_user)):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET deleted_at = NULL, last_login_at = datetime('now'), updated_at = datetime('now') WHERE id = ?",
            (user["id"],),
        )
    token = create_jwt(user["id"])
    _set_token_cookie(response, token)
    response.delete_cookie("recovery_token")


@router.post("/recover/cancel", status_code=status.HTTP_204_NO_CONTENT)
def recover_cancel(response: Response, user: dict = Depends(get_recovery_user)):
    _hard_delete_user(user["id"])
    response.delete_cookie("recovery_token")
