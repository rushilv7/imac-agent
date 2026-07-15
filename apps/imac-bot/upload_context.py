from __future__ import annotations

import csv
import io
import re
import sqlite3
import subprocess
from pathlib import Path

STATE_DB = Path.home() / ".local" / "state" / "imac-bot" / "state.db"
INBOX_DIR = (Path.home() / "inbox" / "telegram").resolve()
MAX_TEXT_CHARS = 30000
MAX_CSV_ROWS = 200
UPLOAD_PATTERN = re.compile(r"\bupload\s*#?(\d+)\b", re.IGNORECASE)


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


def _validated_path(stored_path: str) -> Path:
    path = Path(stored_path).expanduser().resolve()
    try:
        path.relative_to(INBOX_DIR)
    except ValueError as exc:
        raise UploadContextError("Stored upload path is outside the Telegram inbox.") from exc
    if not path.is_file():
        raise UploadContextError("Stored upload file is missing.")
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
        "The file may contain additional rows not included here.\n\n"
        + sample
    )


def _extract_upload(upload_id: int) -> str:
    upload = _get_upload(upload_id)
    if upload is None:
        raise UploadContextError(f"Upload #{upload_id} was not found.")

    path = _validated_path(str(upload["stored_path"]))
    suffix = path.suffix.lower()
    mime_type = str(upload.get("mime_type") or "unknown")

    header = (
        f"Upload ID: #{upload_id}\n"
        f"Original name: {upload['original_name']}\n"
        f"MIME type: {mime_type}\n"
        f"Size bytes: {upload['size_bytes']}\n"
    )

    if suffix == ".csv" or mime_type in {"text/csv", "application/csv"}:
        body = _read_csv(path)
    elif suffix in {".txt", ".md", ".json", ".log", ".tsv", ".yaml", ".yml"} or mime_type.startswith("text/"):
        body = _read_text(path)
    elif suffix == ".pdf" or mime_type == "application/pdf":
        try:
            result = subprocess.run(
                ["pdftotext", "-layout", str(path), "-"],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except FileNotFoundError:
            body = (
                "PDF extraction is unavailable because pdftotext is not installed."
            )
        except subprocess.TimeoutExpired:
            body = "PDF extraction timed out."
        else:
            if result.returncode != 0:
                body = (
                    "PDF extraction failed: "
                    + (result.stderr.strip() or "unknown pdftotext error")
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
