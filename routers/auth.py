import logging
import shutil
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

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
)
from config import BACKEND_URL, COOKIE_DOMAIN, DEV_BACKEND_URL, DEV_FRONTEND_URL, FRONTEND_URL, SOFT_DELETE_RETENTION_DAYS
from database import FILE_STORAGE_PATH, get_conn
from dependencies import get_current_user, get_recovery_user
from schemas import RecoveryUserOut, UserOut

limiter = Limiter(key_func=get_remote_address)
router = APIRouter(prefix="/auth", tags=["auth"])

_DELETE_STATE = "delete_account"
_LOCALHOST_HOSTNAMES = frozenset({"localhost", "127.0.0.1", "::1"})
_ALLOWED_FRONTENDS = frozenset(filter(None, [FRONTEND_URL, DEV_FRONTEND_URL]))

logger = logging.getLogger(__name__)


def _resolve_backend_url(request: Request) -> str:
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    hostname = host.split(":")[0].lower()
    if hostname in _LOCALHOST_HOSTNAMES:
        return DEV_BACKEND_URL
    return f"https://{host}"


def _resolve_frontend_url(request: Request) -> str:
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    hostname = host.split(":")[0].lower()
    if hostname in _LOCALHOST_HOSTNAMES:
        return DEV_FRONTEND_URL
    return FRONTEND_URL


def _encode_state(action: str = "", frontend_url: str = "") -> str | None:
    if not action and not frontend_url:
        return None
    return f"{action}|{frontend_url}"


def _decode_state(state: str | None) -> tuple[str, str | None]:
    """Returns (action, frontend_url). frontend_url is None if not embedded in state."""
    if state is None:
        return "", None
    if "|" in state:
        action, frontend_url = state.split("|", 1)
        return action, frontend_url or None
    return state, None  # legacy: "delete_account" without pipe


def _validated_return_to(return_to: str | None) -> str | None:
    """Returns return_to only if it's in the allowed frontends list."""
    if return_to and return_to in _ALLOWED_FRONTENDS:
        return return_to
    return None


def _backend_hostname(request: Request) -> str:
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    return host.split(":")[0].lower()


def _cookie_context(request: Request, frontend_url: str | None = None) -> str:
    """
    Returns 'local', 'prod', or 'cross' to determine cookie attributes.

    - local: both frontend and backend are localhost → lax, insecure
    - prod:  both are production domains → lax, secure
    - cross: localhost frontend + production backend (dev against prod auth)
             → SameSite=None; Secure required for cross-site cookie sending
    """
    if frontend_url is None:
        # API calls (logout, recover): read frontend origin from Origin header
        origin = request.headers.get("origin", "")
        frontend_url = origin or _resolve_frontend_url(request)

    frontend_host = urlparse(frontend_url).hostname or ""
    backend_host = _backend_hostname(request)

    frontend_local = frontend_host in _LOCALHOST_HOSTNAMES
    backend_local = backend_host in _LOCALHOST_HOSTNAMES

    if frontend_local and backend_local:
        return "local"
    if not frontend_local and not backend_local:
        return "prod"
    return "cross"


def _cookie_kwargs(context: str) -> dict:
    if context == "local":
        return {"secure": False, "samesite": "lax", "domain": None}
    if context == "cross":
        return {"secure": True, "samesite": "none", "domain": COOKIE_DOMAIN}
    return {"secure": True, "samesite": "lax", "domain": COOKIE_DOMAIN}


def _set_token_cookie(response: Response, token: str, context: str = "prod"):
    response.set_cookie(
        key="token", value=token,
        httponly=True,
        max_age=TOKEN_EXPIRE_SECONDS,
        **_cookie_kwargs(context),
    )


def _delete_token_cookie(response: Response, context: str = "prod"):
    response.delete_cookie(
        key="token",
        httponly=True,
        **_cookie_kwargs(context),
    )


def _set_recovery_cookie(response: Response, token: str, context: str = "prod"):
    response.set_cookie(
        key="recovery_token", value=token,
        httponly=True,
        max_age=RECOVERY_TOKEN_EXPIRE_SECONDS,
        **_cookie_kwargs(context),
    )


def _delete_recovery_cookie(response: Response, context: str = "prod"):
    response.delete_cookie(
        key="recovery_token",
        httponly=True,
        **_cookie_kwargs(context),
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


def _handle_delete_flow(google_id: str, frontend_url: str, context: str = "prod") -> RedirectResponse:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE google_id = ? AND deleted_at IS NULL", (google_id,)
        ).fetchone()
        if row is None:
            return RedirectResponse(f"{frontend_url}/login")
        conn.execute(
            "UPDATE users SET deleted_at = datetime('now'), updated_at = datetime('now') WHERE id = ?",
            (row["id"],),
        )
    response = RedirectResponse(f"{frontend_url}/login?account_deleted=1")
    _delete_token_cookie(response, context=context)
    return response


def _handle_login_flow(google_id: str, name: str, picture_url: str | None, email: str, frontend_url: str, context: str = "prod") -> RedirectResponse:
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
        resp = RedirectResponse(f"{frontend_url}/recover")
        _set_recovery_cookie(resp, recovery_token, context=context)
        return resp

    if user_id_to_delete is not None:
        _delete_user_files(user_id_to_delete)

    token = create_jwt(new_user_id)
    response = RedirectResponse(f"{frontend_url}/dashboard")
    _set_token_cookie(response, token, context=context)
    return response


@router.get("/google")
@limiter.limit("10/minute")
def login_google(request: Request, return_to: str | None = None):
    frontend_url = _validated_return_to(return_to)
    state = _encode_state(frontend_url=frontend_url or "")
    return RedirectResponse(google_oauth_url(state=state, backend_url=_resolve_backend_url(request)))


@router.get("/google/delete")
@limiter.limit("10/minute")
def login_google_for_delete(request: Request, return_to: str | None = None):
    frontend_url = _validated_return_to(return_to)
    state = _encode_state(action=_DELETE_STATE, frontend_url=frontend_url or "")
    return RedirectResponse(google_oauth_url(state=state, prompt="select_account", backend_url=_resolve_backend_url(request)))


@router.get("/google/callback")
@limiter.limit("20/minute")
async def google_callback(request: Request, code: str | None = None, error: str | None = None, state: str | None = None):
    action, frontend_url_from_state = _decode_state(state)
    frontend_url = frontend_url_from_state or _resolve_frontend_url(request)

    if error or not code:
        return RedirectResponse(f"{frontend_url}/login?error=oauth_denied")

    backend_url = _resolve_backend_url(request)
    try:
        tokens = await exchange_code(code, backend_url=backend_url)
        userinfo = await get_google_userinfo(tokens["access_token"])
    except Exception:
        logger.exception("OAuth exchange failed")
        return RedirectResponse(f"{frontend_url}/login?error=oauth_failed")

    email: str = userinfo.get("email", "")

    google_id = userinfo["sub"]

    context = _cookie_context(request, frontend_url=frontend_url)

    if action == _DELETE_STATE:
        return _handle_delete_flow(google_id, frontend_url, context=context)

    return _handle_login_flow(
        google_id,
        name=userinfo.get("name", email),
        picture_url=userinfo.get("picture"),
        email=email,
        frontend_url=frontend_url,
        context=context,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, token: str | None = Cookie(default=None, alias="token")):
    _delete_token_cookie(response, context=_cookie_context(request))
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
def recover_confirm(request: Request, response: Response, user: dict = Depends(get_recovery_user)):
    context = _cookie_context(request)
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET deleted_at = NULL, last_login_at = datetime('now'), updated_at = datetime('now') WHERE id = ?",
            (user["id"],),
        )
    token = create_jwt(user["id"])
    _set_token_cookie(response, token, context=context)
    _delete_recovery_cookie(response, context=context)


@router.post("/recover/cancel", status_code=status.HTTP_204_NO_CONTENT)
def recover_cancel(request: Request, response: Response, user: dict = Depends(get_recovery_user)):
    context = _cookie_context(request)
    with get_conn() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user["id"],))
    _delete_user_files(user["id"])
    _delete_recovery_cookie(response, context=context)
