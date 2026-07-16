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


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row["name"]) for row in rows}


def _ensure_column(connection: sqlite3.Connection, *, table: str, column: str, ddl: str) -> None:
    columns = _table_columns(connection, table)
    if column in columns:
        return
    connection.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def _fts_available(connection: sqlite3.Connection) -> bool:
    try:
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?",
            ("knowledge_items_fts",),
        ).fetchone()
        return row is not None
    except sqlite3.OperationalError:
        return False


def _ensure_fts(connection: sqlite3.Connection) -> None:
    try:
        connection.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_items_fts USING fts5(
                original_name,
                summary,
                keywords,
                extracted_text,
                metadata,
                tokenize='unicode61'
            );
            """
        )
    except sqlite3.OperationalError:
        # FTS5 not available. Phase 1 LIKE search remains.
        return


def _fts_upsert(connection: sqlite3.Connection, item: dict[str, Any]) -> None:
    if not _fts_available(connection):
        return
    try:
        connection.execute("DELETE FROM knowledge_items_fts WHERE rowid = ?", (int(item["id"]),))
        connection.execute(
            """
            INSERT INTO knowledge_items_fts(
                rowid,
                original_name,
                summary,
                keywords,
                extracted_text,
                metadata
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                int(item["id"]),
                str(item.get("original_name") or ""),
                str(item.get("summary") or ""),
                str(item.get("keywords_json") or ""),
                str(item.get("extracted_text") or ""),
                str(item.get("metadata_json") or ""),
            ),
        )
    except sqlite3.OperationalError:
        # If the DB was created before FTS5 existed, keep going.
        return


def rebuild_fts() -> None:
    """Rebuild the FTS index from the authoritative knowledge_items table."""
    initialize()
    with _connect() as connection:
        if not _fts_available(connection):
            return
        try:
            connection.execute("DELETE FROM knowledge_items_fts")
        except sqlite3.OperationalError:
            return

        rows = connection.execute("SELECT * FROM knowledge_items").fetchall()
        for row in rows:
            _fts_upsert(connection, dict(row))


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
                extracted_text TEXT,
                suggested_path TEXT,
                named_entities_json TEXT,
                document_type TEXT,
                suggested_category TEXT,
                enrichment_status TEXT,
                enrichment_timestamp TEXT,
                enrichment_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_knowledge_items_created_at ON knowledge_items(created_at);
            CREATE INDEX IF NOT EXISTS idx_knowledge_items_category ON knowledge_items(category);
            """
        )

        # Phase 2 migrations for earlier Phase 1 databases.
        _ensure_column(
            connection,
            table="knowledge_items",
            column="extracted_text",
            ddl="extracted_text TEXT",
        )
        _ensure_column(
            connection,
            table="knowledge_items",
            column="named_entities_json",
            ddl="named_entities_json TEXT",
        )
        _ensure_column(
            connection,
            table="knowledge_items",
            column="document_type",
            ddl="document_type TEXT",
        )
        _ensure_column(
            connection,
            table="knowledge_items",
            column="suggested_category",
            ddl="suggested_category TEXT",
        )
        _ensure_column(
            connection,
            table="knowledge_items",
            column="enrichment_status",
            ddl="enrichment_status TEXT",
        )
        _ensure_column(
            connection,
            table="knowledge_items",
            column="enrichment_timestamp",
            ddl="enrichment_timestamp TEXT",
        )
        _ensure_column(
            connection,
            table="knowledge_items",
            column="enrichment_error",
            ddl="enrichment_error TEXT",
        )

        _ensure_fts(connection)


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
    extracted_text: str | None = None,
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
                extracted_text,
                suggested_path,
                named_entities_json,
                document_type,
                suggested_category,
                enrichment_status,
                enrichment_timestamp,
                enrichment_error,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                extracted_text,
                suggested_path,
                json.dumps([], ensure_ascii=False),
                None,
                None,
                "pending",
                None,
                None,
                now,
                now,
            ),
        )
        item_id = cursor.lastrowid

    if item_id is None:
        raise RuntimeError("Failed to register knowledge item (no row id).")

    item_id_int = int(item_id)

    item = get(item_id_int) or {}
    with _connect() as connection:
        _fts_upsert(connection, item)
    return item


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

    # Phase 2: try FTS5 first. Fall back to Phase 1 LIKE if unavailable.
    with _connect() as connection:
        if _fts_available(connection):
            try:
                rows = connection.execute(
                    """
                    SELECT ki.*
                    FROM knowledge_items_fts f
                    JOIN knowledge_items ki ON ki.id = f.rowid
                    WHERE knowledge_items_fts MATCH ?
                    ORDER BY bm25(knowledge_items_fts) ASC
                    LIMIT ?
                    """,
                    (term, limit),
                ).fetchall()
                return [dict(row) for row in rows]
            except sqlite3.OperationalError:
                pass

        # Not using SQLite FTS in phase 1: simple LIKE across key columns.
        like = f"%{term}%"
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


def search_ranked(query: str, limit: int = 20) -> list[dict[str, Any]]:
    """Return best matching items with FTS rank + excerpt when possible."""
    limit = max(1, min(int(limit), 50))
    term = (query or "").strip()
    if not term:
        return []

    with _connect() as connection:
        if not _fts_available(connection):
            # Fall back to unranked phase 1 search.
            return [
                {"rank": None, "excerpt": "", **row}
                for row in search(term, limit)
            ]

        try:
            rows = connection.execute(
                """
                SELECT
                    ki.*, 
                    bm25(knowledge_items_fts) AS rank,
                    snippet(knowledge_items_fts, 3, '[', ']', '…', 18) AS excerpt
                FROM knowledge_items_fts f
                JOIN knowledge_items ki ON ki.id = f.rowid
                WHERE knowledge_items_fts MATCH ?
                ORDER BY rank ASC
                LIMIT ?
                """,
                (term, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            return [
                {"rank": None, "excerpt": "", **row}
                for row in search(term, limit)
            ]

        return [dict(row) for row in rows]


def update_fields(
    item_id: int,
    *,
    metadata: dict[str, Any] | None = None,
    summary: str | None = None,
    status: str | None = None,
    suggested_path: str | None = None,
    keywords: list[str] | None = None,
    extracted_text: str | None = None,
    named_entities: list[str] | None = None,
    document_type: str | None = None,
    suggested_category: str | None = None,
    enrichment_status: str | None = None,
    enrichment_timestamp: str | None = None,
    enrichment_error: str | None = None,
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
    if extracted_text is not None:
        assignments.append("extracted_text = ?")
        values.append(extracted_text)
    if named_entities is not None:
        assignments.append("named_entities_json = ?")
        values.append(json.dumps(named_entities, ensure_ascii=False))
    if document_type is not None:
        assignments.append("document_type = ?")
        values.append(document_type)
    if suggested_category is not None:
        assignments.append("suggested_category = ?")
        values.append(suggested_category)
    if enrichment_status is not None:
        assignments.append("enrichment_status = ?")
        values.append(enrichment_status)
    if enrichment_timestamp is not None:
        assignments.append("enrichment_timestamp = ?")
        values.append(enrichment_timestamp)
    if enrichment_error is not None:
        assignments.append("enrichment_error = ?")
        values.append(enrichment_error)

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

    updated = get(item_id)
    if updated is None:
        return None
    with _connect() as connection:
        _fts_upsert(connection, updated)
    return updated


def list_enrichment_candidates(
    *,
    statuses: tuple[str, ...] = ("pending", "failed"),
    limit: int = 20,
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 100))
    placeholders = ",".join("?" for _ in statuses) or "?"
    with _connect() as connection:
        rows = connection.execute(
            f"""
            SELECT * FROM knowledge_items
            WHERE COALESCE(enrichment_status, 'pending') IN ({placeholders})
            ORDER BY id ASC
            LIMIT ?
            """,
            (*statuses, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def enrichment_status_summary() -> dict[str, Any]:
    initialize()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT
                COALESCE(enrichment_status, 'pending') AS status,
                COUNT(*) AS count
            FROM knowledge_items
            GROUP BY COALESCE(enrichment_status, 'pending')
            """
        ).fetchall()
    counts = {str(row["status"]): int(row["count"] or 0) for row in rows}
    return {
        "counts": counts,
        "total": sum(counts.values()),
    }
