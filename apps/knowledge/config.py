from __future__ import annotations

from pathlib import Path


KNOWLEDGE_ROOT = Path.home() / "knowledge"
INCOMING_DIR = KNOWLEDGE_ROOT / "incoming"
LIBRARY_DIR = KNOWLEDGE_ROOT / "library"
DOCUMENTS_DIR = LIBRARY_DIR / "documents"
DATA_DIR = LIBRARY_DIR / "data"
IMAGES_DIR = LIBRARY_DIR / "images"
OTHER_DIR = LIBRARY_DIR / "other"
ARTIFACTS_DIR = KNOWLEDGE_ROOT / "artifacts"
ARCHIVE_DIR = KNOWLEDGE_ROOT / "archive"
INDEX_DIR = KNOWLEDGE_ROOT / "index"
TMP_DIR = KNOWLEDGE_ROOT / "tmp"
WORKFLOWS_DIR = KNOWLEDGE_ROOT / "workflows"
REGISTRY_DB = INDEX_DIR / "knowledge.db"


def ensure_directories() -> None:
    for path in (
        INCOMING_DIR,
        DOCUMENTS_DIR,
        DATA_DIR,
        IMAGES_DIR,
        OTHER_DIR,
        ARTIFACTS_DIR,
        ARCHIVE_DIR,
        INDEX_DIR,
        TMP_DIR,
        WORKFLOWS_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)
