"""SQLite-backed persistence for experiment runs."""

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
    return Path(settings.storage_experiments_db_path).resolve()


def init_experiment_history_db() -> None:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS experiment_runs (
                run_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                experiment_type TEXT NOT NULL,
                dataset_name TEXT NOT NULL,
                split TEXT,
                index_name TEXT,
                best_strategy TEXT,
                strategies_json TEXT NOT NULL,
                config_json TEXT NOT NULL,
                result_json TEXT NOT NULL,
                samples_count INTEGER NOT NULL,
                corpus_count INTEGER NOT NULL
            )
            """
        )
        connection.commit()


class ExperimentHistoryRepository:
    """Store and retrieve experiment runs."""

    def __init__(self, db_path: str | None = None):
        self.path = Path(db_path).resolve() if db_path else _db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        init_experiment_history_db()

    def save_run(
        self,
        *,
        experiment_type: str,
        config: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        run_id = str(uuid4())
        created_at = datetime.now(UTC).isoformat()
        dataset_name = str(result.get("dataset_name") or config.get("dataset_name") or "unknown")
        split = str(result.get("split") or config.get("split") or "")
        index_name = str(config.get("index_name") or "")
        comparison = result.get("comparison", {}) if isinstance(result.get("comparison"), dict) else {}
        best_strategy = str(comparison.get("best_strategy_by_recall") or "")
        strategies = comparison.get("strategies") or config.get("strategies") or []
        payload = {
            "run_id": run_id,
            "created_at": created_at,
            "experiment_type": experiment_type,
            "dataset_name": dataset_name,
            "split": split,
            "index_name": index_name,
            "best_strategy": best_strategy,
            "strategies": strategies,
            "config": config,
            "result": result,
            "samples_count": int(result.get("samples_count", 0)),
            "corpus_count": int(result.get("corpus_count", 0)),
        }
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                """
                INSERT INTO experiment_runs (
                    run_id, created_at, experiment_type, dataset_name, split, index_name,
                    best_strategy, strategies_json, config_json, result_json, samples_count, corpus_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    created_at,
                    experiment_type,
                    dataset_name,
                    split,
                    index_name,
                    best_strategy,
                    json.dumps(strategies),
                    json.dumps(config),
                    json.dumps(result),
                    int(result.get("samples_count", 0)),
                    int(result.get("corpus_count", 0)),
                ),
            )
            connection.commit()
        return payload

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT run_id, created_at, experiment_type, dataset_name, split, index_name,
                       best_strategy, strategies_json, config_json, result_json, samples_count, corpus_count
                FROM experiment_runs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        return [self._row_to_summary(row) for row in rows]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT run_id, created_at, experiment_type, dataset_name, split, index_name,
                       best_strategy, strategies_json, config_json, result_json, samples_count, corpus_count
                FROM experiment_runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        summary = self._row_to_summary(row)
        summary["config"] = json.loads(row["config_json"])
        summary["result"] = json.loads(row["result_json"])
        return summary

    def get_summary(self) -> dict[str, Any]:
        runs = self.list_runs(limit=100)
        if not runs:
            return {
                "total_runs": 0,
                "latest_run": None,
                "best_recall_strategy": None,
                "avg_recall_at_k": 0.0,
                "avg_latency_ms": 0.0,
            }

        recall_values: list[float] = []
        latency_values: list[float] = []
        best_strategy: str | None = None
        best_recall = -1.0
        for run in runs:
            result = run.get("result", {})
            comparison = result.get("comparison", {}) if isinstance(result, dict) else {}
            reports = comparison.get("reports", {}) if isinstance(comparison, dict) else {}
            for strategy, report in reports.items():
                recall = float(report.get("mean_recall_at_k", 0.0))
                latency = float(report.get("mean_latency_ms", 0.0))
                recall_values.append(recall)
                latency_values.append(latency)
                if recall > best_recall:
                    best_recall = recall
                    best_strategy = str(strategy)
        latest = runs[0]
        return {
            "total_runs": len(runs),
            "latest_run": {
                "run_id": latest["run_id"],
                "created_at": latest["created_at"],
                "dataset_name": latest["dataset_name"],
                "best_strategy": latest["best_strategy"],
            },
            "best_recall_strategy": best_strategy,
            "avg_recall_at_k": (sum(recall_values) / len(recall_values)) if recall_values else 0.0,
            "avg_latency_ms": (sum(latency_values) / len(latency_values)) if latency_values else 0.0,
        }

    @staticmethod
    def _row_to_summary(row: sqlite3.Row) -> dict[str, Any]:
        result = json.loads(row["result_json"])
        comparison = result.get("comparison", {}) if isinstance(result, dict) else {}
        reports = comparison.get("reports", {}) if isinstance(comparison, dict) else {}
        economics = {
            "avg_latency_ms": 0.0,
            "avg_recall_at_k": 0.0,
            "avg_mrr": 0.0,
            "avg_ndcg_at_k": 0.0,
            "avg_prompt_tokens": 0.0,
            "avg_completion_tokens": 0.0,
            "avg_total_tokens": 0.0,
            "avg_llm_cost_usd": 0.0,
        }
        if reports:
            values = list(reports.values())
            economics = {
                "avg_latency_ms": sum(float(item.get("mean_latency_ms", 0.0)) for item in values) / len(values),
                "avg_recall_at_k": sum(float(item.get("mean_recall_at_k", 0.0)) for item in values) / len(values),
                "avg_mrr": sum(float(item.get("mean_mrr", 0.0)) for item in values) / len(values),
                "avg_ndcg_at_k": sum(float(item.get("mean_ndcg_at_k", 0.0)) for item in values) / len(values),
            }
        return {
            "run_id": row["run_id"],
            "created_at": row["created_at"],
            "experiment_type": row["experiment_type"],
            "dataset_name": row["dataset_name"],
            "split": row["split"],
            "index_name": row["index_name"],
            "best_strategy": row["best_strategy"],
            "strategies": json.loads(row["strategies_json"]),
            "samples_count": int(row["samples_count"]),
            "corpus_count": int(row["corpus_count"]),
            "result": result,
            "summary_metrics": economics,
        }
