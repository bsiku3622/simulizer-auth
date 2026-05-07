from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from jose import jwt, JWTError

from config import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    JWT_SECRET,
    BACKEND_URL,
    ALLOWED_DOMAIN,
)

ALGORITHM = "HS256"
TOKEN_EXPIRE_DAYS = 7
TOKEN_EXPIRE_SECONDS = TOKEN_EXPIRE_DAYS * 24 * 60 * 60
RECOVERY_TOKEN_EXPIRE_MINUTES = 10
RECOVERY_TOKEN_EXPIRE_SECONDS = RECOVERY_TOKEN_EXPIRE_MINUTES * 60

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


def google_oauth_url(state: str | None = None, prompt: str | None = None, backend_url: str = BACKEND_URL) -> str:
    params: dict[str, str] = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": f"{backend_url}/auth/google/callback",
        "response_type": "code",
        "scope": "openid email profile",
        "hd": ALLOWED_DOMAIN,
        "access_type": "online",
    }
    if state:
        params["state"] = state
    if prompt:
        params["prompt"] = prompt
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


async def exchange_code(code: str, backend_url: str = BACKEND_URL) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": f"{backend_url}/auth/google/callback",
                "grant_type": "authorization_code",
            },
        )
        resp.raise_for_status()
        return resp.json()


async def get_google_userinfo(access_token: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json()


def validate_domain(email: str) -> bool:
    return email.endswith(f"@{ALLOWED_DOMAIN}")


def create_jwt(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=TOKEN_EXPIRE_DAYS)
    return jwt.encode(
        {"sub": str(user_id), "exp": expire, "iat": now},
        JWT_SECRET,
        algorithm=ALGORITHM,
    )


def decode_jwt(token: str) -> tuple[int, datetime]:
    payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
    iat = datetime.fromtimestamp(payload["iat"], tz=timezone.utc)
    return int(payload["sub"]), iat


def create_recovery_jwt(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=RECOVERY_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": str(user_id), "intent": "recover", "exp": expire},
        JWT_SECRET,
        algorithm=ALGORITHM,
    )


def decode_recovery_jwt(token: str) -> int:
    payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
    if payload.get("intent") != "recover":
        raise JWTError("Not a recovery token")
    return int(payload["sub"])
