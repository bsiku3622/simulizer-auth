import sqlite3
import os
from contextlib import contextmanager
from pathlib import Path

from yoyo import read_migrations, get_backend

DB_PATH = os.getenv("DB_PATH", "simulizer.db")
MIGRATIONS_DIR = Path(__file__).parent / "migrations"
FILE_STORAGE_PATH = Path(os.getenv("FILE_STORAGE_PATH", "./storage"))


def get_file_path(user_id: int, file_id: int) -> Path:
    user_dir = FILE_STORAGE_PATH / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir / str(file_id)


def get_thumbnail_path(user_id: int, file_id: int) -> Path:
    user_dir = FILE_STORAGE_PATH / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir / f"{file_id}.png"


def _tables_exist(conn) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='users'"
    ).fetchone()
    return row[0] > 0


def run_migrations():
    backend = get_backend(f"sqlite:///{DB_PATH}")
    migrations = read_migrations(str(MIGRATIONS_DIR))

    with backend.lock():
        # DB가 yoyo 없이 이미 초기화된 경우: 0001_initial을 실행 없이 적용 완료로 표시
        with get_conn() as conn:
            already_exists = _tables_exist(conn)

        to_apply = backend.to_apply(migrations)
        if already_exists:
            initial = [m for m in to_apply if m.id == "0001_initial"]
            if initial:
                backend.mark_migrations(initial)
                to_apply = backend.to_apply(migrations)

        backend.apply_migrations(to_apply)


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
