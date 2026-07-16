from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

STATE_DB = Path.home() / ".local" / "state" / "imac-bot" / "state.db"
INBOX_DIR = (Path.home() / "knowledge" / "incoming" / "telegram").resolve()
KNOWLEDGE_ROOT = (Path.home() / "knowledge").resolve()
MAX_TEXT_CHARS = 30000
MAX_CSV_ROWS = 200

UPLOAD_PATTERN = re.compile(r"\bupload\s*#?(\d+)\b", re.IGNORECASE)
KNOWLEDGE_PATTERN = re.compile(r"\b(?:knowledge\s+item|item)\s*#?(\d+)\b", re.IGNORECASE)
NATURAL_PATTERN = re.compile(
    r"\b(this\s+(?:file|document|spreadsheet))\b",
    re.IGNORECASE,
)

# Phase 2: multi-document retrieval caps.
MAX_AUTO_KNOWLEDGE_ITEMS = 5
MAX_AUTO_CONTEXT_CHARS = 60000

# Allow importing the knowledge registry without packaging.
KNOWLEDGE_DIR = Path("/home/rushil/projects/imac-agent/apps/knowledge")
if str(KNOWLEDGE_DIR) not in sys.path:
    sys.path.insert(0, str(KNOWLEDGE_DIR))

try:
    from registry import get as knowledge_get  # type: ignore
    from registry import list_newest as knowledge_list_newest  # type: ignore
    from registry import search_ranked as knowledge_search_ranked  # type: ignore
except Exception:
    knowledge_get = None
    knowledge_list_newest = None
    knowledge_search_ranked = None


class UploadContextError(RuntimeError):
    pass


def referenced_upload_ids(question: str) -> list[int]:
    seen: set[int] = set()
    result: list[int] = []
    for match in UPLOAD_PATTERN.finditer(question):
        upload_id = int(match.group(1))
        if upload_id not in seen:
            seen.add(upload_id)
            result.append(upload_id)
    return result[:3]


def referenced_knowledge_item_ids(question: str) -> list[int]:
    seen: set[int] = set()
    result: list[int] = []
    for match in KNOWLEDGE_PATTERN.finditer(question):
        item_id = int(match.group(1))
        if item_id not in seen:
            seen.add(item_id)
            result.append(item_id)
    return result[:3]


def _get_upload(upload_id: int) -> dict | None:
    if not STATE_DB.is_file():
        return None
    connection = sqlite3.connect(STATE_DB)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            "SELECT * FROM uploads WHERE id = ?",
            (upload_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        connection.close()


def _get_active_uploads(chat_id: int) -> list[dict]:
    if not STATE_DB.is_file():
        return []
    connection = sqlite3.connect(STATE_DB)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT
                au.upload_id,
                au.position,
                u.file_unique_id,
                u.original_name,
                u.stored_path,
                u.mime_type,
                u.size_bytes,
                u.created_at
            FROM active_uploads au
            JOIN uploads u ON u.id = au.upload_id
            WHERE au.chat_id = ?
            ORDER BY au.position ASC
            LIMIT 10
            """,
            (chat_id,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def _validated_path(stored_path: str) -> Path:
    path = Path(stored_path).expanduser().resolve()
    try:
        path.relative_to(INBOX_DIR)
    except ValueError as exc:
        raise UploadContextError("Stored upload path is outside the Telegram inbox.") from exc
    if not path.is_file():
        raise UploadContextError("Stored upload file is missing.")
    return path


def _validated_knowledge_path(stored_path: str) -> Path:
    # Knowledge items must live under the allowlisted knowledge root.
    path = Path(stored_path).expanduser().resolve()
    try:
        path.relative_to(KNOWLEDGE_ROOT)
    except ValueError as exc:
        raise UploadContextError("Stored knowledge path is outside the knowledge root") from exc
    if not path.is_file():
        raise UploadContextError("Stored knowledge file is missing.")
    return path


def _read_text(path: Path) -> str:
    data = path.read_bytes()[: MAX_TEXT_CHARS * 4]
    return data.decode("utf-8", errors="replace")[:MAX_TEXT_CHARS]


def _read_csv(path: Path) -> str:
    text = _read_text(path)
    reader = csv.reader(io.StringIO(text))
    rows: list[list[str]] = []
    for index, row in enumerate(reader):
        if index >= MAX_CSV_ROWS:
            break
        rows.append(row)

    if not rows:
        return "CSV file is empty."

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerows(rows)
    sample = output.getvalue()[:MAX_TEXT_CHARS]
    return (
        f"CSV sample containing up to {MAX_CSV_ROWS} rows. "
        "The file may contain additional rows not included here.\n\n" + sample
    )


def _extract_path(
    path: Path,
    *,
    label: str,
    mime_type: str | None = None,
    size_bytes: int | None = None,
) -> str:
    suffix = path.suffix.lower()
    mime = (mime_type or "unknown").strip()

    header = f"{label}: {path.name}\nMIME type: {mime}\n"
    if size_bytes is not None:
        header += f"Size bytes: {size_bytes}\n"

    if suffix == ".csv" or mime in {"text/csv", "application/csv"}:
        body = _read_csv(path)
    elif suffix in {".txt", ".md", ".json", ".log", ".tsv", ".yaml", ".yml"} or mime.startswith("text/"):
        body = _read_text(path)
    elif suffix == ".pdf" or mime == "application/pdf":
        try:
            result = subprocess.run(
                ["pdftotext", "-layout", str(path), "-"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except FileNotFoundError:
            body = "PDF extraction is unavailable because pdftotext is not installed."
        except subprocess.TimeoutExpired:
            body = "PDF extraction timed out."
        else:
            if result.returncode != 0:
                body = "PDF extraction failed: " + (
                    result.stderr.strip() or "unknown pdftotext error"
                )
            else:
                extracted = result.stdout.strip()
                body = (
                    extracted[:MAX_TEXT_CHARS]
                    if extracted
                    else "PDF contained no extractable text."
                )
    else:
        body = (
            "Binary file detected. This file type is not supported for "
            "content extraction yet. Analyze the available metadata only."
        )

    return header + "\nExtracted content:\n" + body


def _extract_upload(upload_id: int) -> str:
    upload = _get_upload(upload_id)
    if upload is None:
        raise UploadContextError(f"Upload #{upload_id} was not found.")

    path = _validated_path(str(upload["stored_path"]))
    return _extract_path(
        path,
        label=f"Upload ID: #{upload_id} (Telegram upload)",
        mime_type=str(upload.get("mime_type") or "unknown"),
        size_bytes=int(upload.get("size_bytes") or 0),
    )


def _extract_upload_row(upload: dict) -> str:
    upload_id = int(upload["upload_id"])
    path = _validated_path(str(upload["stored_path"]))
    return _extract_path(
        path,
        label=f"Upload ID: #{upload_id} (Active file)",
        mime_type=str(upload.get("mime_type") or "unknown"),
        size_bytes=int(upload.get("size_bytes") or 0),
    )


def _extract_knowledge_item(item_id: int) -> str:
    if knowledge_get is None:
        raise UploadContextError("Knowledge platform is unavailable.")

    item = knowledge_get(int(item_id))
    if not item:
        raise UploadContextError(f"Knowledge item #{item_id} was not found.")

    path = _validated_knowledge_path(str(item.get("stored_path") or ""))
    return _extract_path(
        path,
        label=f"Knowledge Item ID: #{item_id}",
        mime_type=str(item.get("mime_type") or "unknown"),
        size_bytes=int(item.get("size_bytes") or 0),
    )


def build_active_upload_context(chat_id: int) -> str:
    uploads = _get_active_uploads(chat_id)
    if not uploads:
        return ""

    sections: list[str] = []
    for upload in uploads:
        try:
            sections.append(_extract_upload_row(upload))
        except UploadContextError as exc:
            sections.append(f"Upload #{upload.get('upload_id')}: ERROR: {exc}")

    return "\n\n===== ACTIVE TELEGRAM FILE CONTEXT =====\n\n" + "\n\n---\n\n".join(
        sections
    )


def build_upload_context(question: str) -> str:
    upload_ids = referenced_upload_ids(question)
    if not upload_ids:
        return ""

    sections: list[str] = []
    for upload_id in upload_ids:
        try:
            sections.append(_extract_upload(upload_id))
        except UploadContextError as exc:
            sections.append(f"Upload #{upload_id}: ERROR: {exc}")

    return "\n\n===== REFERENCED TELEGRAM UPLOADS =====\n\n" + "\n\n---\n\n".join(sections)


def _auto_select_knowledge_items(question: str) -> list[int]:
    if knowledge_search_ranked is None:
        return []

    # Only auto-select if the user didn't explicitly reference items.
    if referenced_knowledge_item_ids(question):
        return []

    raw = (question or "").strip()
    if not raw:
        return []

    # Convert free-form question text into an FTS-friendly query.
    tokens = re.findall(r"[A-Za-z0-9]{3,}", raw)
    seen: set[str] = set()
    cleaned: list[str] = []
    for token in tokens:
        t = token.lower()
        if t in seen:
            continue
        seen.add(t)
        cleaned.append(token)
        if len(cleaned) >= 8:
            break
    term = " OR ".join(cleaned)
    if not term:
        return []

    try:
        hits = knowledge_search_ranked(term, MAX_AUTO_KNOWLEDGE_ITEMS)
    except Exception:
        return []

    ids: list[int] = []
    for hit in hits:
        try:
            ids.append(int(hit["id"]))
        except Exception:
            continue
    return ids[:MAX_AUTO_KNOWLEDGE_ITEMS]


def build_knowledge_context(question: str, *, chat_id: int | None = None) -> str:
    item_ids = referenced_knowledge_item_ids(question)

    # Natural references like "this file" use the newest ingested knowledge item.
    if not item_ids and chat_id is not None and NATURAL_PATTERN.search(question):
        if knowledge_list_newest is not None:
            try:
                newest = knowledge_list_newest(1)
                if newest:
                    item_ids = [int(newest[0]["id"])]
            except Exception:
                item_ids = []

    if not item_ids and chat_id is not None:
        item_ids = _auto_select_knowledge_items(question)

    if not item_ids:
        return ""

    sections: list[str] = []
    total_chars = 0
    for item_id in item_ids[:MAX_AUTO_KNOWLEDGE_ITEMS]:
        try:
            extracted = _extract_knowledge_item(item_id)
        except UploadContextError as exc:
            extracted = f"Knowledge item #{item_id}: ERROR: {exc}"

        if total_chars + len(extracted) > MAX_AUTO_CONTEXT_CHARS:
            break

        sections.append(extracted)
        total_chars += len(extracted)

    if not sections:
        return ""

    return "\n\n===== KNOWLEDGE ITEM CONTEXT =====\n\n" + "\n\n---\n\n".join(sections)
