import logging
import sqlite3
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

from yoyo import read_migrations, get_backend

from config import DB_PATH, FILE_STORAGE_PATH

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

logger = logging.getLogger(__name__)


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


def _column_exists(conn, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


# Maps migration ID → predicate that returns True if the migration is already reflected in the schema.
# Used to mark pre-yoyo DBs so existing data is not re-migrated.
# Add an entry here whenever a new migration file is created.
_LEGACY_CHECKS: dict[str, "Callable"] = {
    "0001_initial": lambda conn: _tables_exist(conn),
    "0002_soft_delete": lambda conn: _column_exists(conn, "users", "deleted_at"),
    "0003_token_invalidation": lambda conn: _column_exists(conn, "users", "token_issued_at"),
}


def run_migrations():
    backend = get_backend(f"sqlite:///{DB_PATH}")
    migrations = read_migrations(str(MIGRATIONS_DIR))

    with backend.lock():
        to_apply = backend.to_apply(migrations)

        if to_apply:
            with get_conn() as conn:
                already_exists = _tables_exist(conn)

            if already_exists:
                # Pre-yoyo DB: mark any migration whose schema change is already present
                with get_conn() as conn:
                    to_mark = [m for m in to_apply if m.id in _LEGACY_CHECKS and _LEGACY_CHECKS[m.id](conn)]
                if to_mark:
                    backend.mark_migrations(to_mark)
                    to_apply = backend.to_apply(migrations)

        backend.apply_migrations(to_apply)

    # Set WAL mode once after migrations; this persists in the DB file
    with get_conn() as conn:
        conn.execute("PRAGMA journal_mode = WAL")


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
