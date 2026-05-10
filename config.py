import os
from pathlib import Path

GOOGLE_CLIENT_ID: str = os.environ["GOOGLE_CLIENT_ID"]
GOOGLE_CLIENT_SECRET: str = os.environ["GOOGLE_CLIENT_SECRET"]
JWT_SECRET: str = os.environ["JWT_SECRET"]
BACKEND_URL: str = os.environ["BACKEND_URL"]
DEV_BACKEND_URL: str = os.getenv("DEV_BACKEND_URL") or BACKEND_URL
FRONTEND_URL: str = os.environ["FRONTEND_URL"]
DEV_FRONTEND_URL: str = os.getenv("DEV_FRONTEND_URL") or FRONTEND_URL
ALLOWED_DOMAIN: str = os.environ["ALLOWED_DOMAIN"]
COOKIE_DOMAIN: str | None = os.getenv("COOKIE_DOMAIN") or None

TOKEN_EXPIRE_DAYS: int = int(os.getenv("TOKEN_EXPIRE_DAYS", "7"))
RECOVERY_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("RECOVERY_TOKEN_EXPIRE_MINUTES", "10"))
SOFT_DELETE_RETENTION_DAYS: int = int(os.getenv("SOFT_DELETE_RETENTION_DAYS", "30"))

DB_PATH: str = os.getenv("DB_PATH", "simulizer.db")
FILE_STORAGE_PATH: Path = Path(os.getenv("FILE_STORAGE_PATH", "./storage"))
