import os
from datetime import datetime, timedelta, timezone

import httpx
from jose import jwt, JWTError

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
JWT_SECRET = os.getenv("JWT_SECRET", "changeme")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
ALLOWED_DOMAIN = "ksa.hs.kr"

ALGORITHM = "HS256"
TOKEN_EXPIRE_DAYS = 7
RECOVERY_TOKEN_EXPIRE_MINUTES = 10

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


def google_oauth_url(state: str | None = None, prompt: str | None = None) -> str:
    from urllib.parse import urlencode
    redirect_uri = f"{BACKEND_URL}/auth/google/callback"
    params: dict[str, str] = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
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


def exchange_code(code: str) -> dict:
    redirect_uri = f"{BACKEND_URL}/auth/google/callback"
    with httpx.Client() as client:
        resp = client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        resp.raise_for_status()
        return resp.json()


def get_google_userinfo(access_token: str) -> dict:
    with httpx.Client() as client:
        resp = client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        resp.raise_for_status()
        return resp.json()


def validate_domain(email: str) -> bool:
    return email.endswith(f"@{ALLOWED_DOMAIN}")


def create_jwt(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=TOKEN_EXPIRE_DAYS)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)


def decode_jwt(token: str) -> int:
    payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
    return int(payload["sub"])


def create_recovery_jwt(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=RECOVERY_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "intent": "recover", "exp": expire}
    return jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)


def decode_recovery_jwt(token: str) -> int:
    payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
    if payload.get("intent") != "recover":
        raise JWTError("Not a recovery token")
    return int(payload["sub"])
