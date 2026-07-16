from __future__ import annotations

import os
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from state_store import record_upload, set_active_uploads

INBOX_DIR = Path.home() / "inbox" / "telegram"
MAX_FILE_BYTES = 20 * 1024 * 1024


def _safe_name(name: str) -> str:
    base = Path(name).name.strip() or "upload.bin"
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", base)
    return cleaned[:180] or "upload.bin"


def save_document(
    document: dict[str, Any],
    *,
    chat_id: int | None = None,
    telegram_request: Callable[..., Any],
    bot_token: str,
    set_as_active: bool = True,
) -> dict[str, Any]:
    size = int(document.get("file_size") or 0)
    if size <= 0:
        raise RuntimeError("Telegram did not provide a valid file size.")
    if size > MAX_FILE_BYTES:
        raise RuntimeError("File is too large for the Telegram inbox. Maximum: 20 MB.")

    file_id = str(document.get("file_id") or "")
    if not file_id:
        raise RuntimeError("Telegram document is missing file_id.")

    original_name = _safe_name(str(document.get("file_name") or "upload.bin"))
    info = telegram_request("getFile", {"file_id": file_id})
    remote_path = str(info.get("file_path") or "")
    if not remote_path:
        raise RuntimeError("Telegram did not return a downloadable file path.")

    INBOX_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = INBOX_DIR / f"{stamp}_{original_name}"

    url = f"https://api.telegram.org/file/bot{bot_token}/{remote_path}"
    request = urllib.request.Request(url, headers={"User-Agent": "imac-bot"})
    with urllib.request.urlopen(request, timeout=60) as response:
        with destination.open("wb") as output:
            remaining = MAX_FILE_BYTES + 1
            total = 0
            while True:
                chunk = response.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                output.write(chunk)
                total += len(chunk)
                remaining = MAX_FILE_BYTES + 1 - total
                if total > MAX_FILE_BYTES:
                    output.close()
                    destination.unlink(missing_ok=True)
                    raise RuntimeError("Downloaded file exceeded the 20 MB limit.")

    os.chmod(destination, 0o600)
    upload_id = record_upload(
        file_unique_id=document.get("file_unique_id"),
        original_name=original_name,
        stored_path=str(destination),
        mime_type=document.get("mime_type"),
        size_bytes=destination.stat().st_size,
    )

    if set_as_active and chat_id is not None:
        # Requirement: every uploaded file becomes the active file for this chat.
        # Multi-file context is supported via /add_file.
        set_active_uploads(chat_id, [upload_id])

    return {
        "upload_id": upload_id,
        "original_name": original_name,
        "stored_path": str(destination),
        "size_bytes": destination.stat().st_size,
        "mime_type": document.get("mime_type") or "unknown",
    }
