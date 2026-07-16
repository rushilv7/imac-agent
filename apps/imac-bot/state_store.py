from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


STATE_DIR = Path.home() / ".local" / "state" / "imac-bot"
DB_PATH = STATE_DIR / "state.db"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    STATE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def initialize() -> None:
    with _connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                status TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                payload TEXT NOT NULL,
                result TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT
            );

            CREATE TABLE IF NOT EXISTS actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                action_key TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                job_id INTEGER,
                FOREIGN KEY(job_id) REFERENCES jobs(id)
            );

            CREATE TABLE IF NOT EXISTS uploads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_unique_id TEXT,
                original_name TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                mime_type TEXT,
                size_bytes INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS active_uploads (
                chat_id INTEGER NOT NULL,
                upload_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                added_at TEXT NOT NULL,
                PRIMARY KEY(chat_id, upload_id),
                FOREIGN KEY(upload_id) REFERENCES uploads(id)
            );

            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
            CREATE INDEX IF NOT EXISTS idx_actions_code ON actions(code);
            CREATE INDEX IF NOT EXISTS idx_uploads_created_at ON uploads(created_at);
            CREATE INDEX IF NOT EXISTS idx_active_uploads_chat ON active_uploads(chat_id);
            """
        )

        connection.execute(
            """
            UPDATE jobs
            SET status = 'failed',
                error = 'Bot restarted while this job was running.',
                finished_at = ?
            WHERE status = 'running'
            """,
            (_now(),),
        )


def create_job(kind: str, chat_id: int, payload: str) -> int:
    with _connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO jobs(kind, status, chat_id, payload, created_at)
            VALUES (?, 'queued', ?, ?, ?)
            """,
            (kind, chat_id, payload, _now()),
        )
        return int(cursor.lastrowid)


def get_job(job_id: int) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
    return dict(row) if row else None


def list_jobs(limit: int = 10) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 50))
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT * FROM jobs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_queued_job_ids() -> list[int]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT id FROM jobs
            WHERE status = 'queued'
            ORDER BY id ASC
            """
        ).fetchall()
    return [int(row["id"]) for row in rows]


def mark_job_running(job_id: int) -> bool:
    with _connect() as connection:
        cursor = connection.execute(
            """
            UPDATE jobs
            SET status = 'running',
                started_at = ?
            WHERE id = ? AND status = 'queued'
            """,
            (_now(), job_id),
        )
        return cursor.rowcount == 1


def complete_job(job_id: int, result: str) -> None:
    with _connect() as connection:
        connection.execute(
            """
            UPDATE jobs
            SET status = 'completed',
                result = ?,
                finished_at = ?
            WHERE id = ?
            """,
            (result, _now(), job_id),
        )


def fail_job(job_id: int, error: str) -> None:
    with _connect() as connection:
        connection.execute(
            """
            UPDATE jobs
            SET status = 'failed',
                error = ?,
                finished_at = ?
            WHERE id = ?
            """,
            (error, _now(), job_id),
        )


def cancel_job(job_id: int) -> bool:
    with _connect() as connection:
        cursor = connection.execute(
            """
            UPDATE jobs
            SET status = 'cancelled',
                finished_at = ?
            WHERE id = ? AND status = 'queued'
            """,
            (_now(), job_id),
        )
        return cursor.rowcount == 1


def create_action(
    *,
    code: str,
    action_key: str,
    description: str,
    chat_id: int,
    ttl_minutes: int = 10,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=ttl_minutes)

    with _connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO actions(
                code,
                action_key,
                description,
                status,
                chat_id,
                created_at,
                expires_at
            )
            VALUES (?, ?, ?, 'pending', ?, ?, ?)
            """,
            (
                code,
                action_key,
                description,
                chat_id,
                now.isoformat(),
                expires.isoformat(),
            ),
        )
        action_id = int(cursor.lastrowid)

    return get_action_by_id(action_id) or {}


def get_action_by_id(action_id: int) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM actions WHERE id = ?",
            (action_id,),
        ).fetchone()
    return dict(row) if row else None


def get_action_by_code(code: str) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT * FROM actions
            WHERE UPPER(code) = UPPER(?)
            """,
            (code.strip(),),
        ).fetchone()
    return dict(row) if row else None


def approve_action(code: str, chat_id: int) -> dict[str, Any]:
    now = datetime.now(timezone.utc)

    with _connect() as connection:
        row = connection.execute(
            """
            SELECT * FROM actions
            WHERE UPPER(code) = UPPER(?)
            """,
            (code.strip(),),
        ).fetchone()

        if not row:
            return {"ok": False, "reason": "not_found"}

        action = dict(row)

        if int(action["chat_id"]) != int(chat_id):
            return {"ok": False, "reason": "wrong_chat"}

        if action["status"] != "pending":
            return {
                "ok": False,
                "reason": "not_pending",
                "status": action["status"],
            }

        expires_at = datetime.fromisoformat(action["expires_at"])
        if expires_at <= now:
            connection.execute(
                """
                UPDATE actions
                SET status = 'expired'
                WHERE id = ?
                """,
                (action["id"],),
            )
            return {"ok": False, "reason": "expired"}

        cursor = connection.execute(
            """
            UPDATE actions
            SET status = 'approved'
            WHERE id = ? AND status = 'pending'
            """,
            (action["id"],),
        )

        if cursor.rowcount != 1:
            return {"ok": False, "reason": "race"}

    approved = get_action_by_id(int(action["id"]))
    return {"ok": True, "action": approved}


def reject_action(code: str, chat_id: int) -> dict[str, Any]:
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT * FROM actions
            WHERE UPPER(code) = UPPER(?)
            """,
            (code.strip(),),
        ).fetchone()

        if not row:
            return {"ok": False, "reason": "not_found"}

        action = dict(row)

        if int(action["chat_id"]) != int(chat_id):
            return {"ok": False, "reason": "wrong_chat"}

        cursor = connection.execute(
            """
            UPDATE actions
            SET status = 'rejected'
            WHERE id = ? AND status = 'pending'
            """,
            (action["id"],),
        )

        if cursor.rowcount != 1:
            return {
                "ok": False,
                "reason": "not_pending",
                "status": action["status"],
            }

    return {"ok": True}


def attach_action_job(action_id: int, job_id: int) -> None:
    with _connect() as connection:
        connection.execute(
            """
            UPDATE actions
            SET status = 'queued',
                job_id = ?
            WHERE id = ?
            """,
            (job_id, action_id),
        )


def mark_action_finished(
    action_id: int,
    *,
    succeeded: bool,
) -> None:
    with _connect() as connection:
        connection.execute(
            """
            UPDATE actions
            SET status = ?
            WHERE id = ?
            """,
            ("completed" if succeeded else "failed", action_id),
        )


def list_pending_actions(
    chat_id: int,
    limit: int = 10,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 50))
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT * FROM actions
            WHERE chat_id = ? AND status = 'pending'
            ORDER BY id DESC
            LIMIT ?
            """,
            (chat_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def record_upload(
    *,
    file_unique_id: str | None,
    original_name: str,
    stored_path: str,
    mime_type: str | None,
    size_bytes: int,
) -> int:
    with _connect() as connection:
        cursor = connection.execute(
            """
            INSERT INTO uploads(
                file_unique_id,
                original_name,
                stored_path,
                mime_type,
                size_bytes,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                file_unique_id,
                original_name,
                stored_path,
                mime_type,
                size_bytes,
                _now(),
            ),
        )
        return int(cursor.lastrowid)


def list_uploads(limit: int = 10) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 50))
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT * FROM uploads
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_upload(upload_id: int) -> dict[str, Any] | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM uploads WHERE id = ?",
            (upload_id,),
        ).fetchone()
    return dict(row) if row else None


def set_active_uploads(chat_id: int, upload_ids: list[int]) -> None:
    unique_ids: list[int] = []
    seen: set[int] = set()
    for upload_id in upload_ids:
        value = int(upload_id)
        if value <= 0:
            continue
        if value in seen:
            continue
        seen.add(value)
        unique_ids.append(value)

    with _connect() as connection:
        connection.execute(
            "DELETE FROM active_uploads WHERE chat_id = ?",
            (chat_id,),
        )
        for index, upload_id in enumerate(unique_ids, start=1):
            connection.execute(
                """
                INSERT INTO active_uploads(chat_id, upload_id, position, added_at)
                VALUES (?, ?, ?, ?)
                """,
                (chat_id, upload_id, index, _now()),
            )


def add_active_upload(chat_id: int, upload_id: int) -> bool:
    upload_id = int(upload_id)
    if upload_id <= 0:
        return False

    with _connect() as connection:
        existing = connection.execute(
            """
            SELECT 1 FROM active_uploads
            WHERE chat_id = ? AND upload_id = ?
            """,
            (chat_id, upload_id),
        ).fetchone()
        if existing:
            return False

        row = connection.execute(
            """
            SELECT COALESCE(MAX(position), 0) AS max_position
            FROM active_uploads
            WHERE chat_id = ?
            """,
            (chat_id,),
        ).fetchone()
        max_position = int(row["max_position"] or 0) if row else 0

        connection.execute(
            """
            INSERT INTO active_uploads(chat_id, upload_id, position, added_at)
            VALUES (?, ?, ?, ?)
            """,
            (chat_id, upload_id, max_position + 1, _now()),
        )

    return True


def clear_active_uploads(chat_id: int) -> None:
    with _connect() as connection:
        connection.execute(
            "DELETE FROM active_uploads WHERE chat_id = ?",
            (chat_id,),
        )


def list_active_uploads(chat_id: int, limit: int = 10) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 50))
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT
                au.chat_id,
                au.upload_id,
                au.position,
                au.added_at,
                u.original_name,
                u.stored_path,
                u.mime_type,
                u.size_bytes,
                u.created_at
            FROM active_uploads au
            JOIN uploads u ON u.id = au.upload_id
            WHERE au.chat_id = ?
            ORDER BY au.position ASC
            LIMIT ?
            """,
            (chat_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]
