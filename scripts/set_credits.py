"""Credit Manager TUI — search users by email and set their credits.

Run it (no args):
    cd backend-auth && python scripts/set_credits.py
    # or:  python backend-auth/scripts/set_credits.py   (from repo root)

Interactive loop: type part of an email to filter, pick a row by number, then
enter the new balance. 1 credit = $0.01 ($1 = 100 credits). Changes take effect
on the next request — no backend-auth restart needed.

Resolves the DB the same way the app does: DB_PATH from backend-auth/.env
(default simulizer.db), relative to the backend-auth/ directory.
"""
import os
import sqlite3
import sys
from pathlib import Path

# This file is backend-auth/scripts/set_credits.py → the auth dir is two up.
AUTH_DIR = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(AUTH_DIR / ".env")
except Exception:
    pass

DB_PATH = AUTH_DIR / os.getenv("DB_PATH", "simulizer.db")


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def search(con: sqlite3.Connection, term: str) -> list[sqlite3.Row]:
    term = (term or "").strip()
    if term:
        return con.execute(
            "SELECT id, email, credits FROM users WHERE email LIKE ? ORDER BY email",
            (f"%{term}%",),
        ).fetchall()
    return con.execute("SELECT id, email, credits FROM users ORDER BY email").fetchall()


def print_table(rows: list[sqlite3.Row]) -> None:
    if not rows:
        print("  (no matching users)")
        return
    w = max(len("email"), max(len(r["email"]) for r in rows))
    print(f"  {'#':>2}  {'id':>4}  {'email':<{w}}  {'credits':>12}")
    print(f"  {'-' * 2}  {'-' * 4}  {'-' * w}  {'-' * 12}")
    for i, r in enumerate(rows, 1):
        print(f"  {i:>2}  {r['id']:>4}  {r['email']:<{w}}  {r['credits']:>12,}")


def ask(prompt: str) -> str | None:
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None


def main() -> None:
    if not DB_PATH.exists():
        print(f"DB not found: {DB_PATH}")
        sys.exit(1)
    con = connect()
    print(f"=== Credit Manager - {DB_PATH} ===")
    print("1 credit = $0.01  ($1 = 100 credits).  q to quit.\n")

    while True:
        term = ask("Search email (substring; Enter = all): ")
        if term is None or term.lower() in ("q", "quit", "exit"):
            break
        rows = search(con, term)
        print_table(rows)
        if not rows:
            continue

        pick = ask("Select # to edit (Enter = new search): ")
        if pick is None:
            break
        if not pick:
            continue
        if not pick.isdigit() or not (1 <= int(pick) <= len(rows)):
            print("  invalid selection\n")
            continue

        u = rows[int(pick) - 1]
        print(f"  {u['email']} - current: {u['credits']:,} credits")
        val = ask("  New credit amount: ")
        if val is None:
            break
        if not val.lstrip("-").isdigit():
            print("  not a number, skipped\n")
            continue

        amount = int(val)
        con.execute(
            "UPDATE users SET credits = ?, updated_at = datetime('now') WHERE id = ?",
            (amount, u["id"]),
        )
        con.commit()
        print(f"  OK  {u['email']} -> {amount:,} credits\n")

    con.close()
    print("bye")


if __name__ == "__main__":
    main()
