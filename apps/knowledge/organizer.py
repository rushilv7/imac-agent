from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from config import (
    ARTIFACTS_DIR,
    DATA_DIR,
    DOCUMENTS_DIR,
    IMAGES_DIR,
    INCOMING_DIR,
    KNOWLEDGE_ROOT,
    OTHER_DIR,
    ensure_directories,
)
from registry import get, update_fields


class OrganizerError(RuntimeError):
    pass


DESTINATION_KEYS: dict[str, Path] = {
    "documents:resumes": DOCUMENTS_DIR / "resumes",
    "documents:finance": DOCUMENTS_DIR / "finance",
    "documents:legal": DOCUMENTS_DIR / "legal",
    "documents:architecture": DOCUMENTS_DIR / "architecture",
    "documents:general": DOCUMENTS_DIR / "general",
    "data:csv": DATA_DIR / "csv",
    "data:excel": DATA_DIR / "excel",
    "images": IMAGES_DIR,
    "other": OTHER_DIR,
}


def allowed_destination_keys() -> list[str]:
    return sorted(DESTINATION_KEYS)


def suggest_destination(item: dict[str, Any]) -> str:
    ext = str(item.get("extension") or "").lower().lstrip(".")
    mime_type = str(item.get("mime_type") or "")
    name = str(item.get("original_name") or "").lower()

    if ext in {"csv", "tsv"}:
        return "data:csv"
    if ext in {"xlsx", "xls", "xlsm"}:
        return "data:excel"
    if ext in {"png", "jpg", "jpeg", "gif", "webp", "tiff", "bmp"}:
        return "images"

    # Deterministic name-based routing.
    if "resume" in name or re.search(r"\bcv\b", name):
        return "documents:resumes"
    if any(token in name for token in ("invoice", "receipt", "statement", "tax", "rrsp", "t4")):
        return "documents:finance"
    if any(token in name for token in ("contract", "agreement", "lease", "nda")):
        return "documents:legal"
    if "architecture" in name or "diagram" in name:
        return "documents:architecture"

    if mime_type.startswith("text/") or ext in {"pdf", "txt", "md", "json", "yaml", "yml", "log"}:
        return "documents:general"

    return "other"


def _validated_under_root(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    root = KNOWLEDGE_ROOT.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise OrganizerError("Path is outside knowledge root") from exc
    return resolved


def _validated_source(path: Path) -> Path:
    resolved = _validated_under_root(path)
    incoming = INCOMING_DIR.resolve()
    try:
        resolved.relative_to(incoming)
    except ValueError as exc:
        raise OrganizerError("Source is not under incoming") from exc
    if not resolved.is_file():
        raise OrganizerError("Source file is missing")
    return resolved


def _unique_destination(dest_dir: Path, filename: str) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    base = Path(filename).stem
    suffix = Path(filename).suffix

    candidate = dest_dir / f"{base}{suffix}"
    if not candidate.exists():
        return candidate

    for index in range(2, 1000):
        candidate = dest_dir / f"{base}_{index}{suffix}"
        if not candidate.exists():
            return candidate

    raise OrganizerError("Could not find a unique destination filename")


def organize(item_id: int, destination_key: str) -> dict[str, Any]:
    ensure_directories()

    destination_key = destination_key.strip()
    dest_root = DESTINATION_KEYS.get(destination_key)
    if dest_root is None:
        raise OrganizerError("Destination key is not allowlisted")

    item = get(int(item_id))
    if not item:
        raise OrganizerError("Knowledge item not found")

    source = _validated_source(Path(str(item["stored_path"])))
    dest_dir = _validated_under_root(dest_root)

    destination = _unique_destination(dest_dir, source.name)
    destination = _validated_under_root(destination)

    # Copy only; never move.
    shutil.copy2(source, destination)

    update_fields(
        int(item_id),
        status="organized",
        suggested_path=str(destination),
    )

    return {
        "ok": True,
        "knowledge_item_id": int(item_id),
        "source": str(source),
        "destination": str(destination),
        "destination_key": destination_key,
    }
