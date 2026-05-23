import secrets
import shutil
import string

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, PlainTextResponse
from sqlite3 import IntegrityError

from database import get_conn, get_file_path, get_thumbnail_path
from dependencies import get_current_user, get_optional_user
from schemas import (
    FileCreate, FileContentUpdate, FileDetail, FileOut, FileRename,
    FileVisibilityUpdate, MAX_THUMBNAIL_BYTES,
)

router = APIRouter(prefix="/files", tags=["files"])

_ALPHANUM = string.ascii_letters + string.digits


def _generate_file_id() -> str:
    return "".join(secrets.choice(_ALPHANUM) for _ in range(8))


def _row_to_out(row) -> FileOut:
    return FileOut(
        idx=row["idx"],
        id=row["id"],
        author_id=row["author_id"],
        name=row["name"],
        type=row["type"],
        visibility=row["visibility"],
        thumbnail_custom=bool(row["thumbnail_custom"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _require_readable_file(conn, file_id: str, user: dict | None):
    row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    if user is not None and row["author_id"] == user["id"]:
        return row
    if row["visibility"] == "link":
        return row
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")


def _require_file(conn, file_id: str, author_id: int):
    row = conn.execute(
        "SELECT * FROM files WHERE id = ? AND author_id = ?", (file_id, author_id)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return row


def _read_content(user_id: int, file_idx: int) -> str:
    path = get_file_path(user_id, file_idx)
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="File data missing on disk",
        )
    return path.read_text(encoding="utf-8")


def _write_content(user_id: int, file_idx: int, content: str):
    final_path = get_file_path(user_id, file_idx)
    tmp_path = final_path.with_suffix(".tmp")
    try:
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(final_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _delete_content(user_id: int, file_idx: int):
    path = get_file_path(user_id, file_idx)
    if path.exists():
        path.unlink()


@router.get("", response_model=list[FileOut])
def list_files(user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM files WHERE author_id = ? ORDER BY updated_at DESC",
            (user["id"],),
        ).fetchall()
    return [_row_to_out(r) for r in rows]


@router.post("", response_model=FileDetail, status_code=status.HTTP_201_CREATED)
def create_file(body: FileCreate, user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        try:
            pub_id = _generate_file_id()
            conn.execute(
                "INSERT INTO files (id, author_id, name, type) VALUES (?, ?, ?, ?)",
                (pub_id, user["id"], body.name, body.type),
            )
            row = conn.execute(
                "SELECT * FROM files WHERE author_id = ? AND name = ?",
                (user["id"], body.name),
            ).fetchone()
            _write_content(user["id"], row["idx"], body.content)
        except IntegrityError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A file with that name already exists",
            )
    return FileDetail(**_row_to_out(row).model_dump(), content=body.content)


@router.get("/{file_id}", response_model=FileDetail)
def get_file(file_id: str, user: dict | None = Depends(get_optional_user)):
    with get_conn() as conn:
        row = _require_readable_file(conn, file_id, user)
    content = _read_content(row["author_id"], row["idx"])
    return FileDetail(**_row_to_out(row).model_dump(), content=content)


@router.put("/{file_id}", response_model=FileOut)
def save_file(file_id: str, body: FileContentUpdate, user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        row = _require_file(conn, file_id, user["id"])
        _write_content(user["id"], row["idx"], body.content)
        conn.execute(
            "UPDATE files SET updated_at = datetime('now') WHERE idx = ?",
            (row["idx"],),
        )
        row = conn.execute("SELECT * FROM files WHERE idx = ?", (row["idx"],)).fetchone()
    return _row_to_out(row)


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file(file_id: str, user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        row = _require_file(conn, file_id, user["id"])
        conn.execute("DELETE FROM files WHERE idx = ?", (row["idx"],))
    _delete_content(user["id"], row["idx"])
    for manual in (False, True):
        p = get_thumbnail_path(user["id"], row["idx"], manual=manual)
        if p.exists():
            p.unlink()


@router.patch("/{file_id}/name", response_model=FileOut)
def rename_file(file_id: str, body: FileRename, user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        row = _require_file(conn, file_id, user["id"])
        try:
            conn.execute(
                "UPDATE files SET name = ?, updated_at = datetime('now') WHERE idx = ?",
                (body.name, row["idx"]),
            )
            row = conn.execute("SELECT * FROM files WHERE idx = ?", (row["idx"],)).fetchone()
        except IntegrityError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A file with that name already exists",
            )
    return _row_to_out(row)


@router.patch("/{file_id}/visibility", response_model=FileOut)
def update_file_visibility(
    file_id: str,
    body: FileVisibilityUpdate,
    user: dict = Depends(get_current_user),
):
    with get_conn() as conn:
        row = _require_file(conn, file_id, user["id"])
        conn.execute(
            "UPDATE files SET visibility = ?, updated_at = datetime('now') WHERE idx = ?",
            (body.visibility, row["idx"]),
        )
        row = conn.execute("SELECT * FROM files WHERE idx = ?", (row["idx"],)).fetchone()
    return _row_to_out(row)


@router.post("/{file_id}/duplicate", response_model=FileDetail, status_code=status.HTTP_201_CREATED)
def duplicate_file(file_id: str, user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        src = _require_readable_file(conn, file_id, user)

        base_name = src["name"]
        candidate = f"{base_name} copy"
        existing = {
            r["name"]
            for r in conn.execute(
                "SELECT name FROM files WHERE author_id = ?", (user["id"],)
            ).fetchall()
        }
        counter = 2
        while candidate in existing:
            candidate = f"{base_name} copy {counter}"
            counter += 1

        try:
            content = _read_content(src["author_id"], src["idx"])
            pub_id = _generate_file_id()
            conn.execute(
                "INSERT INTO files (id, author_id, name, type, thumbnail_custom) VALUES (?, ?, ?, ?, ?)",
                (pub_id, user["id"], candidate, src["type"], 1 if src["thumbnail_custom"] else 0),
            )
            new_row = conn.execute(
                "SELECT * FROM files WHERE author_id = ? AND name = ?",
                (user["id"], candidate),
            ).fetchone()
            _write_content(user["id"], new_row["idx"], content)
        except IntegrityError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Could not duplicate file",
            )
    for manual in (False, True):
        sp = get_thumbnail_path(src["author_id"], src["idx"], manual=manual)
        if sp.exists():
            shutil.copy2(sp, get_thumbnail_path(user["id"], new_row["idx"], manual=manual))
    return FileDetail(**_row_to_out(new_row).model_dump(), content=content)


_PREVIEW_BYTES = 1500

_NO_CACHE_HEADERS = {"Cache-Control": "no-cache, must-revalidate"}


def _detect_image_media_type(data: bytes) -> str | None:
    """Detect a thumbnail's image media type from its magic bytes.

    Returns None if the bytes don't match a supported format. We only allow
    formats every modern browser can render and that round-trip cleanly.
    """
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "image/gif"
    if len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


@router.get("/{file_id}/preview", response_class=PlainTextResponse)
def get_file_preview(file_id: str, user: dict | None = Depends(get_optional_user)):
    with get_conn() as conn:
        row = _require_readable_file(conn, file_id, user)
    path = get_file_path(row["author_id"], row["idx"])
    if not path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No preview",
            headers=_NO_CACHE_HEADERS,
        )
    with path.open("rb") as f:
        data = f.read(_PREVIEW_BYTES)
    return PlainTextResponse(
        data.decode("utf-8", errors="replace"),
        headers=_NO_CACHE_HEADERS,
    )


@router.get("/{file_id}/thumbnail")
def get_file_thumbnail(file_id: str, user: dict | None = Depends(get_optional_user)):
    with get_conn() as conn:
        row = _require_readable_file(conn, file_id, user)
    manual_path = get_thumbnail_path(row["author_id"], row["idx"], manual=True)
    auto_path = get_thumbnail_path(row["author_id"], row["idx"], manual=False)
    if row["thumbnail_custom"] and manual_path.exists():
        path = manual_path
    elif auto_path.exists():
        path = auto_path
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No thumbnail",
            headers=_NO_CACHE_HEADERS,
        )
    # Auto thumbnails are always PNG (we generate them); for manual uploads we
    # accept multiple formats but store as a generic `.manual.png` blob, so
    # sniff the actual media type from the first bytes to serve the right
    # Content-Type. Falls back to image/png if magic bytes are unrecognized
    # (an old/legacy upload).
    with path.open("rb") as f:
        head = f.read(12)
    media_type = _detect_image_media_type(head) or "image/png"
    return FileResponse(path, media_type=media_type, headers=_NO_CACHE_HEADERS)


@router.delete("/{file_id}/thumbnail", status_code=status.HTTP_204_NO_CONTENT)
def delete_file_thumbnail(file_id: str, user: dict = Depends(get_current_user)):
    with get_conn() as conn:
        row = _require_file(conn, file_id, user["id"])
        conn.execute(
            "UPDATE files SET thumbnail_custom = 0 WHERE idx = ?",
            (row["idx"],),
        )
    manual = get_thumbnail_path(user["id"], row["idx"], manual=True)
    if manual.exists():
        manual.unlink()


@router.put("/{file_id}/thumbnail", status_code=status.HTTP_204_NO_CONTENT)
async def save_file_thumbnail(
    file_id: str,
    request: Request,
    user: dict = Depends(get_current_user),
    manual: bool = False,
):
    content_type = request.headers.get("content-type", "")
    if not content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Thumbnail must be an image",
        )

    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_THUMBNAIL_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Thumbnail too large")

    body = await request.body()
    if len(body) > MAX_THUMBNAIL_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Thumbnail too large")

    # For manual uploads, sniff actual image bytes — Content-Type can be
    # spoofed and we don't want random binary masquerading as image/*.
    # Auto thumbnails come from our own canvas → always PNG, no need to check.
    if manual and _detect_image_media_type(body[:12]) is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Thumbnail must be PNG, JPEG, GIF, or WebP",
        )

    # Resolve file ownership first (read-only), then write to disk BEFORE
    # committing the thumbnail_custom flag — that way a disk-write failure
    # doesn't leave the DB pointing at a non-existent file.
    with get_conn() as conn:
        row = _require_file(conn, file_id, user["id"])
    target_path = get_thumbnail_path(user["id"], row["idx"], manual=manual)
    target_path.write_bytes(body)
    if manual:
        with get_conn() as conn:
            conn.execute(
                "UPDATE files SET thumbnail_custom = 1 WHERE idx = ?",
                (row["idx"],),
            )
