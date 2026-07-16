from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from config import ARTIFACTS_DIR, REGISTRY_DB, ensure_directories


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    ensure_directories()
    REGISTRY_DB.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    connection = sqlite3.connect(REGISTRY_DB, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def initialize() -> None:
    with _connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS knowledge_artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_item_ids_json TEXT NOT NULL,
                filename TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                mime_type TEXT,
                description TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_knowledge_artifacts_created_at ON knowledge_artifacts(created_at);
            """
        )


def create_artifact(
    *,
    source_item_ids: list[int],
    filename: str,
    stored_path: Path,
    mime_type: str | None,
    description: str | None,
) -> dict[str, Any]:
    initialize()

    stored_path = stored_path.expanduser().resolve()
    artifacts_root = ARTIFACTS_DIR.resolve()
    try:
        stored_path.relative_to(artifacts_root)
    except ValueError as exc:
        raise RuntimeError("Artifact stored_path must be under ~/knowledge/artifacts") from exc

    with _connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO knowledge_artifacts(
                source_item_ids_json,
                filename,
                stored_path,
                mime_type,
                description,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                json.dumps([int(x) for x in source_item_ids]),
                filename,
                str(stored_path),
                mime_type,
                description,
                _now(),
            ),
        )
        artifact_id = cursor.lastrowid

    if artifact_id is None:
        raise RuntimeError("Failed to create artifact")

    return get_artifact(int(artifact_id)) or {}


def get_artifact(artifact_id: int) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM knowledge_artifacts WHERE id = ?",
            (int(artifact_id),),
        ).fetchone()
    return dict(row) if row else None


def list_artifacts(limit: int = 20) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 100))
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT * FROM knowledge_artifacts
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]
