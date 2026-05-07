import logging
import shutil
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Cookie, Depends, Request, Response, status
from fastapi.responses import RedirectResponse
from jose import JWTError
from slowapi import Limiter
from slowapi.util import get_remote_address

from auth import (
    TOKEN_EXPIRE_SECONDS,
    RECOVERY_TOKEN_EXPIRE_SECONDS,
    create_jwt,
    create_recovery_jwt,
    decode_jwt,
    exchange_code,
    get_google_userinfo,
    google_oauth_url,
    validate_domain,
)
from config import BACKEND_URL, COOKIE_SECURE, DEV_BACKEND_URL, FRONTEND_URL
from database import FILE_STORAGE_PATH, get_conn
from dependencies import get_current_user, get_recovery_user
from schemas import RecoveryUserOut, UserOut

limiter = Limiter(key_func=get_remote_address)
router = APIRouter(prefix="/auth", tags=["auth"])

SOFT_DELETE_RETENTION_DAYS = 30

_DELETE_STATE = "delete_account"
_LOCALHOST_HOSTNAMES = frozenset({"localhost", "127.0.0.1", "::1"})

logger = logging.getLogger(__name__)


def _resolve_backend_url(request: Request) -> str:
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    hostname = host.split(":")[0].lower()
    if hostname in _LOCALHOST_HOSTNAMES:
        return DEV_BACKEND_URL
    return BACKEND_URL


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


def _delete_user_files(user_id: int):
    user_dir = FILE_STORAGE_PATH / str(user_id)
    try:
        if user_dir.exists():
            shutil.rmtree(user_dir)
    except OSError:
        logger.error("Failed to delete files for user %d", user_id)


def _parse_deleted_at(deleted_at_str: str) -> datetime:
    return datetime.fromisoformat(deleted_at_str.replace(" ", "T")).replace(tzinfo=timezone.utc)


def _handle_delete_flow(google_id: str) -> RedirectResponse:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE google_id = ? AND deleted_at IS NULL", (google_id,)
        ).fetchone()
        if row is None:
            return RedirectResponse(f"{FRONTEND_URL}/login")
        conn.execute(
            "UPDATE users SET deleted_at = datetime('now'), updated_at = datetime('now') WHERE id = ?",
            (row["id"],),
        )
    response = RedirectResponse(f"{FRONTEND_URL}/login?account_deleted=1")
    response.delete_cookie("token")
    return response


def _handle_login_flow(google_id: str, name: str, picture_url: str | None, email: str) -> RedirectResponse:
    user_id_to_delete: int | None = None
    recovery_user_id: int | None = None
    new_user_id: int | None = None

    with get_conn() as conn:
        existing = conn.execute("SELECT * FROM users WHERE google_id = ?", (google_id,)).fetchone()

        if existing and existing["deleted_at"]:
            deleted_at = _parse_deleted_at(existing["deleted_at"])
            age = datetime.now(timezone.utc) - deleted_at

            if age < timedelta(days=SOFT_DELETE_RETENTION_DAYS):
                recovery_user_id = existing["id"]
            else:
                conn.execute("DELETE FROM users WHERE id = ?", (existing["id"],))
                user_id_to_delete = existing["id"]

        if recovery_user_id is None:
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
            new_user_id = row["id"]

    if recovery_user_id is not None:
        recovery_token = create_recovery_jwt(recovery_user_id)
        resp = RedirectResponse(f"{FRONTEND_URL}/recover")
        _set_recovery_cookie(resp, recovery_token)
        return resp

    if user_id_to_delete is not None:
        _delete_user_files(user_id_to_delete)

    token = create_jwt(new_user_id)
    response = RedirectResponse(f"{FRONTEND_URL}/dashboard")
    _set_token_cookie(response, token)
    return response


@router.get("/google")
@limiter.limit("10/minute")
def login_google(request: Request):
    return RedirectResponse(google_oauth_url(backend_url=_resolve_backend_url(request)))


@router.get("/google/delete")
@limiter.limit("10/minute")
def login_google_for_delete(request: Request):
    return RedirectResponse(google_oauth_url(state=_DELETE_STATE, prompt="select_account", backend_url=_resolve_backend_url(request)))


@router.get("/google/callback")
@limiter.limit("20/minute")
async def google_callback(request: Request, code: str | None = None, error: str | None = None, state: str | None = None):
    if error or not code:
        return RedirectResponse(f"{FRONTEND_URL}/login?error=oauth_denied")

    backend_url = _resolve_backend_url(request)
    try:
        tokens = await exchange_code(code, backend_url=backend_url)
        userinfo = await get_google_userinfo(tokens["access_token"])
    except Exception:
        logger.exception("OAuth exchange failed")
        return RedirectResponse(f"{FRONTEND_URL}/login?error=oauth_failed")

    email: str = userinfo.get("email", "")
    if not validate_domain(email):
        return RedirectResponse(f"{FRONTEND_URL}/login?error=unauthorized_domain")

    google_id = userinfo["sub"]

    if state == _DELETE_STATE:
        return _handle_delete_flow(google_id)

    return _handle_login_flow(
        google_id,
        name=userinfo.get("name", email),
        picture_url=userinfo.get("picture"),
        email=email,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response, token: str | None = Cookie(default=None, alias="token")):
    response.delete_cookie("token")
    if token:
        try:
            user_id, _ = decode_jwt(token)
            with get_conn() as conn:
                conn.execute(
                    "UPDATE users SET token_issued_at = datetime('now') WHERE id = ?",
                    (user_id,),
                )
        except JWTError:
            pass


@router.get("/me", response_model=UserOut)
def me(user: dict = Depends(get_current_user)):
    return UserOut(**user)


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
    with get_conn() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user["id"],))
    _delete_user_files(user["id"])
    response.delete_cookie("recovery_token")
