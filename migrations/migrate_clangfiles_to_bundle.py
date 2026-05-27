"""One-shot migration: convert legacy single-file clangfile content blobs to
the multi-file JSON bundle format (schema v1).

Run from backend-auth/:
    python -m migrations.migrate_clangfiles_to_bundle [--dry-run]

For each clangfile row we read its on-disk content. Rows whose content already
parses as a v1 bundle are skipped (idempotent). Rows whose content is plain
C++ source (or the placeholder "{}") are wrapped as:

    {
      "version": 1,
      "entry": "main.cpp",
      "tree": [{ "type": "file", "name": "main.cpp", "content": <old> }],
      "ui": { "activeFile": "main.cpp", "openTabs": ["main.cpp"], "treeOpen": false }
    }

The display name in the DB is also stripped of any trailing .cpp/.hpp/.h-ish
extension since project bundles are no longer files of a particular suffix.
"""

import argparse
import json
import sys
from pathlib import Path

# Make this script runnable both as a module and as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import get_conn, get_file_path  # noqa: E402

EXT_SUFFIXES = (".cpp", ".cc", ".cxx", ".c++", ".hpp", ".h", ".hxx", ".h++")


def _strip_extension(name: str) -> str:
    low = name.lower()
    for ext in EXT_SUFFIXES:
        if low.endswith(ext):
            return name[: -len(ext)]
    return name


def _is_v1_bundle(raw: str) -> bool:
    try:
        b = json.loads(raw)
    except Exception:
        return False
    return isinstance(b, dict) and b.get("version") == 1 and isinstance(b.get("tree"), list)


def _wrap_as_bundle(raw: str) -> str:
    initial_content = "" if raw == "{}" else raw
    bundle = {
        "version": 1,
        "entry": "main.cpp",
        "tree": [{"type": "file", "name": "main.cpp", "content": initial_content}],
        "ui": {
            "activeFile": "main.cpp",
            "openTabs": ["main.cpp"],
            "treeOpen": False,
        },
    }
    return json.dumps(bundle)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report what would change but don't write")
    args = ap.parse_args()

    converted_content = 0
    renamed_rows = 0
    skipped = 0
    missing = 0

    with get_conn() as conn:
        rows = conn.execute(
            "SELECT idx, id, name, author_id FROM files WHERE type = 'clangfile'"
        ).fetchall()

        for row in rows:
            path = get_file_path(row["author_id"], row["idx"])
            if not path.exists():
                missing += 1
                print(f"[missing] idx={row['idx']} id={row['id']} name={row['name']!r}")
                continue
            raw = path.read_text(encoding="utf-8")

            needs_content_migration = not _is_v1_bundle(raw)
            new_name = _strip_extension(row["name"])
            needs_rename = new_name != row["name"]

            if not needs_content_migration and not needs_rename:
                skipped += 1
                continue

            if needs_content_migration:
                wrapped = _wrap_as_bundle(raw)
                print(f"[content] idx={row['idx']} id={row['id']} name={row['name']!r} "
                      f"({len(raw)} bytes legacy -> {len(wrapped)} bytes bundle)")
                if not args.dry_run:
                    tmp = path.with_suffix(".migrate.tmp")
                    tmp.write_text(wrapped, encoding="utf-8")
                    tmp.replace(path)
                converted_content += 1

            if needs_rename:
                print(f"[name]    idx={row['idx']} {row['name']!r} -> {new_name!r}")
                if not args.dry_run:
                    try:
                        conn.execute(
                            "UPDATE files SET name = ? WHERE idx = ?",
                            (new_name, row["idx"]),
                        )
                    except Exception as e:
                        # A name collision after stripping the extension (e.g.
                        # both 'foo.cpp' and 'foo' existed). Skip the rename
                        # for this row; the user can sort it out manually.
                        print(f"           skip rename: {e}")
                        continue
                renamed_rows += 1

    print()
    print(f"content migrated : {converted_content}")
    print(f"names renamed    : {renamed_rows}")
    print(f"already up-to-date: {skipped}")
    print(f"missing on disk  : {missing}")
    if args.dry_run:
        print("(dry run -- no changes written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
