"""SQLite-backed persistence for compare runs."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sqlite3
from typing import Any
from uuid import uuid4

from app.config import get_settings


def _db_path() -> Path:
    settings = get_settings()
    return Path(settings.storage_compare_runs_db_path).resolve()


def init_compare_history_db() -> None:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS compare_runs (
                run_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT NOT NULL,
                left_document_id TEXT NOT NULL,
                right_document_id TEXT NOT NULL,
                strategy TEXT NOT NULL,
                index_name TEXT NOT NULL,
                model TEXT,
                config_json TEXT NOT NULL,
                result_json TEXT,
                error_text TEXT
            )
            """
        )
        connection.commit()


class CompareRunRepository:
    """Store and retrieve async compare runs."""

    def __init__(self, db_path: str | None = None):
        self.path = Path(db_path).resolve() if db_path else _db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        init_compare_history_db()

    def create_run(
        self,
        *,
        left_document_id: str,
        right_document_id: str,
        strategy: str,
        index_name: str,
        model: str | None,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        run_id = str(uuid4())
        now = datetime.now(UTC).isoformat()
        payload = {
            "run_id": run_id,
            "created_at": now,
            "updated_at": now,
            "status": "queued",
            "left_document_id": left_document_id,
            "right_document_id": right_document_id,
            "strategy": strategy,
            "index_name": index_name,
            "model": model,
            "config": config,
            "result": None,
            "error": None,
        }
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO compare_runs (
                    run_id, created_at, updated_at, status, left_document_id, right_document_id,
                    strategy, index_name, model, config_json, result_json, error_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    now,
                    now,
                    "queued",
                    left_document_id,
                    right_document_id,
                    strategy,
                    index_name,
                    model,
                    json.dumps(config),
                    None,
                    None,
                ),
            )
            connection.commit()
        return payload

    def mark_running(self, run_id: str) -> None:
        self._update_status(run_id=run_id, status="running")

    def mark_completed(self, run_id: str, result: dict[str, Any]) -> None:
        self._update_status(run_id=run_id, status="completed", result=result, error=None)

    def mark_failed(self, run_id: str, error: str) -> None:
        self._update_status(run_id=run_id, status="failed", result=None, error=error)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT run_id, created_at, updated_at, status, left_document_id, right_document_id,
                       strategy, index_name, model, config_json, result_json, error_text
                FROM compare_runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_payload(row)

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT run_id, created_at, updated_at, status, left_document_id, right_document_id,
                       strategy, index_name, model, config_json, result_json, error_text
                FROM compare_runs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        return [self._row_to_payload(row) for row in rows]

    def _update_status(
        self,
        *,
        run_id: str,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                UPDATE compare_runs
                SET updated_at = ?, status = ?, result_json = ?, error_text = ?
                WHERE run_id = ?
                """,
                (
                    now,
                    status,
                    json.dumps(result) if result is not None else None,
                    error,
                    run_id,
                ),
            )
            connection.commit()

    @staticmethod
    def _row_to_payload(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "run_id": row["run_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "status": row["status"],
            "left_document_id": row["left_document_id"],
            "right_document_id": row["right_document_id"],
            "strategy": row["strategy"],
            "index_name": row["index_name"],
            "model": row["model"],
            "config": json.loads(row["config_json"]) if row["config_json"] else {},
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "error": row["error_text"],
        }
