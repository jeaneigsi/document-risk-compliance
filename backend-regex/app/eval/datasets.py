"""Dataset adapters for evaluation and phase-8 experiments."""

from collections.abc import Iterable
import json
from pathlib import Path
from typing import Any

from app.eval.models import SearchEvalSample
from app.ingest.datasets import load_find_dataset, load_hf_dataset, load_wikipedia_contradict


class FindEvalPackError(RuntimeError):
    """Raised when FIND experiment pack cannot be prepared reliably."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def materialize_dataset(
    name: str,
    split: str,
    cache_dir: str | None = None,
):
    """Load a dataset split and materialize it in local HF cache."""
    kwargs: dict[str, Any] = {}
    if cache_dir:
        kwargs["cache_dir"] = cache_dir
    return load_hf_dataset(name=name, split=split, **kwargs)


def load_streaming_dataset(
    name: str,
    split: str,
    cache_dir: str | None = None,
):
    """Load a dataset using HF streaming mode."""
    kwargs: dict[str, Any] = {"streaming": True}
    if cache_dir:
        kwargs["cache_dir"] = cache_dir
    return load_hf_dataset(name=name, split=split, **kwargs)


def _iter_rows(dataset_like: Any) -> Iterable[dict[str, Any]]:
    if isinstance(dataset_like, list):
        for row in dataset_like:
            if isinstance(row, dict):
                yield row
        return

    # HF Dataset supports iteration directly.
    for row in dataset_like:
        if isinstance(row, dict):
            yield row


def stream_take(dataset_like: Any, n: int) -> list[dict[str, Any]]:
    """Take first n rows from an iterable dataset."""
    if n <= 0:
        return []
    rows: list[dict[str, Any]] = []
    for row in _iter_rows(dataset_like):
        rows.append(row)
        if len(rows) >= n:
            break
    return rows


def export_rows_to_jsonl(rows: list[dict[str, Any]], output_path: str) -> str:
    """Persist a small sampled subset for reproducible local experiments."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return str(path)


def load_rows_from_jsonl(input_path: str) -> list[dict[str, Any]]:
    """Load rows from a local JSONL file."""
    rows: list[dict[str, Any]] = []
    path = Path(input_path)
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def build_find_eval_pack_from_rows(
    rows: list[dict[str, Any]],
    index_name: str = "default",
    dataset_name: str = "kensho/FIND",
    split: str = "custom",
    max_query_chars: int = 8192,
) -> dict[str, Any]:
    """Convert normalized FIND-like rows to eval samples + corpus."""
    samples: list[SearchEvalSample] = []
    corpus_map: dict[str, dict] = {}
    skipped_too_long_queries = 0

    for i, row in enumerate(rows):
        query = str(
            row.get("problem_text")
            or row.get("query")
            or row.get("claim")
            or row.get("description")
            or ""
        ).strip()
        query = " ".join(query.split())
        if not query:
            continue
        if len(query) > max_query_chars:
            skipped_too_long_queries += 1
            continue

        evidence_rows = row.get("evidence_dicts") or []
        evidence_texts = row.get("evidence") if isinstance(row.get("evidence"), list) else []
        relevant_ids: set[str] = set()
        relevance_by_id: dict[str, float] = {}

        for j, evidence in enumerate(evidence_rows):
            if not isinstance(evidence, dict):
                continue
            doc_id = str(
                evidence.get("id")
                or evidence.get("evidence_id")
                or evidence.get("document_id")
                or f"find-{i}-ev-{j}"
            )
            text = str(
                evidence.get("text")
                or evidence.get("evidence_text")
                or evidence.get("content")
                or evidence.get("token")
                or ""
            ).strip()
            if not text and j < len(evidence_texts):
                text = str(evidence_texts[j] or "").strip()
            score = float(evidence.get("score", 1.0))
            if not text:
                continue

            relevant_ids.add(doc_id)
            relevance_by_id[doc_id] = score
            if doc_id not in corpus_map:
                corpus_map[doc_id] = {
                    "id": doc_id,
                    "text": text,
                    "metadata": {
                        "source": "find",
                        "sample_index": i,
                    },
                }

        if not relevant_ids:
            continue

        sample_id = str(row.get("id") or row.get("sample_id") or f"find-sample-{i}")
        samples.append(
            SearchEvalSample(
                sample_id=sample_id,
                query=query,
                relevant_ids=relevant_ids,
                relevance_by_id=relevance_by_id,
                index_name=index_name,
                metadata={
                    "dataset_name": dataset_name,
                    "split": split,
                    "problem_text": str(row.get("problem_text") or "").strip(),
                    "claim": str(row.get("claim") or "").strip(),
                    "description": str(row.get("description") or "").strip(),
                    "raw_row_keys": sorted(row.keys()),
                },
            )
        )

    return {
        "dataset_name": dataset_name,
        "split": split,
        "samples": samples,
        "corpus": list(corpus_map.values()),
        "samples_count": len(samples),
        "corpus_count": len(corpus_map),
        "skipped_too_long_queries": skipped_too_long_queries,
        "max_query_chars": max_query_chars,
    }


def load_find_eval_pack(
    split: str = "validation",
    max_samples: int = 50,
    index_name: str = "default",
    streaming: bool = False,
    cache_dir: str | None = None,
    max_query_chars: int = 8192,
) -> dict[str, Any]:
    """Convert FIND rows to search eval samples + a lightweight corpus."""
    try:
        if streaming:
            dataset = load_streaming_dataset("kensho/FIND", split=split, cache_dir=cache_dir)
        else:
            if cache_dir:
                dataset = materialize_dataset("kensho/FIND", split=split, cache_dir=cache_dir)
            else:
                dataset = load_find_dataset(split=split)
    except Exception as exc:
        reason = f"{type(exc).__name__}: {str(exc)}".strip()
        raise FindEvalPackError(
            "dataset_access_error",
            (
                "Unable to load `kensho/FIND`. Ensure access terms are accepted and HF token is configured "
                f"(HF_TOKEN/HUGGINGFACE_HUB_TOKEN in backend `.env` or environment). Cause: {reason}"
            ),
        ) from exc

    rows = stream_take(dataset, n=max_samples)
    if not rows:
        raise FindEvalPackError(
            "empty_split",
            f"No rows found for split `{split}` in `kensho/FIND`.",
        )

    pack = build_find_eval_pack_from_rows(
        rows=rows,
        index_name=index_name,
        dataset_name="kensho/FIND",
        split=split,
        max_query_chars=max_query_chars,
    )
    if int(pack.get("samples_count", 0)) == 0:
        row_keys = sorted(rows[0].keys()) if isinstance(rows[0], dict) else []
        skipped = int(pack.get("skipped_too_long_queries", 0))
        raise FindEvalPackError(
            "schema_mismatch",
            (
                "Rows were loaded but no evaluable samples were built. "
                f"First row keys: {row_keys}. Expected query fields (`problem_text`/`description`) "
                "and evidence field (`evidence_dicts`). "
                f"Skipped too-long queries: {skipped} (max_query_chars={max_query_chars})."
            ),
        )
    return pack


def build_wikipedia_contradict_eval_pack_from_rows(
    rows: list[dict[str, Any]],
    index_name: str = "default",
    dataset_name: str = "ibm-research/Wikipedia_contradict_benchmark",
    split: str = "train",
) -> dict[str, Any]:
    samples: list[SearchEvalSample] = []
    corpus: list[dict[str, Any]] = []

    for i, row in enumerate(rows):
        query = str(row.get("question") or "").strip()
        context1 = str(row.get("context1") or "").strip()
        context2 = str(row.get("context2") or "").strip()
        if not query or not context1 or not context2:
            continue

        sample_id = str(row.get("question_ID") or f"wiki-contradict-{i}")
        ctx1_id = f"{sample_id}:context1"
        ctx2_id = f"{sample_id}:context2"
        corpus.append(
            {
                "id": ctx1_id,
                "text": context1,
                "metadata": {
                    "source": "wikipedia_contradict",
                    "question_id": sample_id,
                    "contradict_type": row.get("contradictType"),
                    "article_title": row.get("WikipediaArticleTitle"),
                    "context_side": "context1",
                },
            }
        )
        corpus.append(
            {
                "id": ctx2_id,
                "text": context2,
                "metadata": {
                    "source": "wikipedia_contradict",
                    "question_id": sample_id,
                    "contradict_type": row.get("contradictType"),
                    "article_title": row.get("WikipediaArticleTitle"),
                    "context_side": "context2",
                },
            }
        )
        samples.append(
            SearchEvalSample(
                sample_id=sample_id,
                query=query,
                relevant_ids={ctx1_id, ctx2_id},
                relevance_by_id={ctx1_id: 1.0, ctx2_id: 1.0},
                index_name=index_name,
                metadata={
                    "dataset_name": dataset_name,
                    "split": split,
                    "contradict_type": str(row.get("contradictType") or ""),
                    "article_title": str(row.get("WikipediaArticleTitle") or ""),
                    "question": query,
                },
            )
        )

    return {
        "dataset_name": dataset_name,
        "split": split,
        "samples": samples,
        "corpus": corpus,
        "samples_count": len(samples),
        "corpus_count": len(corpus),
        "skipped_too_long_queries": 0,
        "max_query_chars": None,
    }


def load_wikipedia_contradict_eval_pack(
    split: str = "train",
    max_samples: int = 50,
    index_name: str = "default",
    cache_dir: str | None = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if cache_dir:
        kwargs["cache_dir"] = cache_dir
    try:
        dataset = load_wikipedia_contradict(split=split) if not cache_dir else load_hf_dataset(
            name="ibm-research/Wikipedia_contradict_benchmark",
            split=split,
            **kwargs,
        )
    except Exception as exc:
        reason = f"{type(exc).__name__}: {str(exc)}".strip()
        raise FindEvalPackError(
            "dataset_access_error",
            f"Unable to load `ibm-research/Wikipedia_contradict_benchmark`. Cause: {reason}",
        ) from exc

    rows = stream_take(dataset, n=max_samples)
    if not rows:
        raise FindEvalPackError(
            "empty_split",
            f"No rows found for split `{split}` in `ibm-research/Wikipedia_contradict_benchmark`.",
        )
    pack = build_wikipedia_contradict_eval_pack_from_rows(
        rows=rows,
        index_name=index_name,
        split=split,
    )
    if int(pack.get("samples_count", 0)) == 0:
        raise FindEvalPackError(
            "schema_mismatch",
            "Rows were loaded but no evaluable samples were built for Wikipedia Contradict.",
        )
    return pack
