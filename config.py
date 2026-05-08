import os
from pathlib import Path

GOOGLE_CLIENT_ID: str = os.environ["GOOGLE_CLIENT_ID"]
GOOGLE_CLIENT_SECRET: str = os.environ["GOOGLE_CLIENT_SECRET"]
JWT_SECRET: str = os.environ["JWT_SECRET"]
BACKEND_URL: str = os.environ["BACKEND_URL"]
DEV_BACKEND_URL: str = os.getenv("DEV_BACKEND_URL") or BACKEND_URL
FRONTEND_URL: str = os.getenv("FRONTEND_URL", "https://simulizer.net")
DEV_FRONTEND_URL: str = os.getenv("DEV_FRONTEND_URL", "http://localhost:3000")
ALLOWED_DOMAIN: str = os.getenv("ALLOWED_DOMAIN", "ksa.hs.kr")
COOKIE_SECURE: bool = os.getenv("COOKIE_SECURE", "false").lower() == "true"
COOKIE_DOMAIN: str | None = os.getenv("COOKIE_DOMAIN") or None

DB_PATH: str = os.getenv("DB_PATH", "simulizer.db")
FILE_STORAGE_PATH: Path = Path(os.getenv("FILE_STORAGE_PATH", "./storage"))
