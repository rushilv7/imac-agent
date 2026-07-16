from __future__ import annotations

import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from config import REGISTRY_DB, ensure_directories


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
            CREATE TABLE IF NOT EXISTS knowledge_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uuid TEXT NOT NULL UNIQUE,
                original_name TEXT,
                stored_path TEXT NOT NULL,
                sha256 TEXT NOT NULL UNIQUE,
                mime_type TEXT,
                size_bytes INTEGER,
                extension TEXT,
                category TEXT,
                status TEXT,
                summary TEXT,
                keywords_json TEXT,
                metadata_json TEXT,
                suggested_path TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_knowledge_items_created_at ON knowledge_items(created_at);
            CREATE INDEX IF NOT EXISTS idx_knowledge_items_category ON knowledge_items(category);
            """
        )


def get_duplicate_by_sha256(sha256: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM knowledge_items WHERE sha256 = ?",
            (sha256,),
        ).fetchone()
    return dict(row) if row else None


def register(
    *,
    stored_path: Path,
    sha256: str,
    original_name: str | None,
    mime_type: str | None,
    size_bytes: int,
    extension: str,
    category: str,
    status: str = "registered",
    summary: str | None = None,
    keywords: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    suggested_path: str | None = None,
) -> dict[str, Any]:
    initialize()

    now = _now()
    item_uuid = str(uuid.uuid4())
    keywords_json = json.dumps(keywords or [], ensure_ascii=False)
    metadata_json = json.dumps(metadata or {}, ensure_ascii=False)

    with _connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO knowledge_items(
                uuid,
                original_name,
                stored_path,
                sha256,
                mime_type,
                size_bytes,
                extension,
                category,
                status,
                summary,
                keywords_json,
                metadata_json,
                suggested_path,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item_uuid,
                original_name,
                str(stored_path),
                sha256,
                mime_type,
                int(size_bytes),
                extension,
                category,
                status,
                summary,
                keywords_json,
                metadata_json,
                suggested_path,
                now,
                now,
            ),
        )
        item_id = cursor.lastrowid

    if item_id is None:
        raise RuntimeError("Failed to register knowledge item (no row id).")

    item_id_int = int(item_id)

    return get(item_id_int) or {}


def get(item_id: int) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM knowledge_items WHERE id = ?",
            (int(item_id),),
        ).fetchone()
    return dict(row) if row else None


def list_newest(limit: int = 20) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 100))
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT * FROM knowledge_items
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def search(query: str, limit: int = 20) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 50))
    term = (query or "").strip()
    if not term:
        return []

    # Not using SQLite FTS in phase 1: simple LIKE across key columns.
    like = f"%{term}%"
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT * FROM knowledge_items
            WHERE original_name LIKE ?
               OR stored_path LIKE ?
               OR COALESCE(summary, '') LIKE ?
               OR COALESCE(keywords_json, '') LIKE ?
               OR COALESCE(metadata_json, '') LIKE ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (like, like, like, like, like, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def update_fields(
    item_id: int,
    *,
    metadata: dict[str, Any] | None = None,
    summary: str | None = None,
    status: str | None = None,
    suggested_path: str | None = None,
    keywords: list[str] | None = None,
) -> dict[str, Any] | None:
    assignments: list[str] = []
    values: list[Any] = []

    if metadata is not None:
        assignments.append("metadata_json = ?")
        values.append(json.dumps(metadata, ensure_ascii=False))
    if summary is not None:
        assignments.append("summary = ?")
        values.append(summary)
    if status is not None:
        assignments.append("status = ?")
        values.append(status)
    if suggested_path is not None:
        assignments.append("suggested_path = ?")
        values.append(suggested_path)
    if keywords is not None:
        assignments.append("keywords_json = ?")
        values.append(json.dumps(keywords, ensure_ascii=False))

    if not assignments:
        return get(item_id)

    assignments.append("updated_at = ?")
    values.append(_now())
    values.append(int(item_id))

    with _connect() as connection:
        connection.execute(
            f"UPDATE knowledge_items SET {', '.join(assignments)} WHERE id = ?",
            tuple(values),
        )

    return get(item_id)
