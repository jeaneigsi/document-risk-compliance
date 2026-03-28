"""Tests for evaluation dataset adapters (phase 8 helpers)."""

from app.eval.datasets import (
    build_find_eval_pack_from_rows,
    build_wikipedia_contradict_eval_pack_from_rows,
    export_rows_to_jsonl,
    load_find_eval_pack,
    load_rows_from_jsonl,
    stream_take,
)


def test_stream_take_limits_rows():
    rows = [{"id": i} for i in range(10)]
    picked = stream_take(rows, 3)
    assert picked == [{"id": 0}, {"id": 1}, {"id": 2}]


def test_export_and_load_jsonl_roundtrip(tmp_path):
    rows = [{"a": 1}, {"b": "x"}]
    output = tmp_path / "sample.jsonl"
    export_rows_to_jsonl(rows, str(output))
    loaded = load_rows_from_jsonl(str(output))
    assert loaded == rows


def test_build_find_eval_pack_from_rows():
    rows = [
        {
            "id": "s1",
            "problem_text": "budget mismatch",
            "evidence_dicts": [
                {"id": "ev-1", "text": "Budget is 900 EUR", "score": 2.0},
                {"id": "ev-2", "text": "Approved budget: 1200 EUR", "score": 1.0},
            ],
        }
    ]
    pack = build_find_eval_pack_from_rows(rows, index_name="contracts")
    assert pack["samples_count"] == 1
    assert pack["corpus_count"] == 2
    sample = pack["samples"][0]
    assert sample.index_name == "contracts"
    assert sample.relevant_ids == {"ev-1", "ev-2"}
    assert sample.metadata["problem_text"] == "budget mismatch"


def test_load_find_eval_pack_streaming(monkeypatch):
    fake_rows = [
        {
            "id": "s1",
            "problem_text": "deadline mismatch",
            "evidence_dicts": [{"id": "ev-1", "text": "Deadline is 2026-04-01"}],
        },
        {
            "id": "s2",
            "problem_text": "budget mismatch",
            "evidence_dicts": [{"id": "ev-2", "text": "Budget is 900 EUR"}],
        },
    ]

    def _fake_load_streaming_dataset(name: str, split: str, cache_dir=None):
        assert name == "kensho/FIND"
        assert split == "validation"
        return fake_rows

    monkeypatch.setattr("app.eval.datasets.load_streaming_dataset", _fake_load_streaming_dataset)
    pack = load_find_eval_pack(split="validation", max_samples=1, streaming=True)

    assert pack["samples_count"] == 1
    assert pack["corpus_count"] == 1


def test_build_find_eval_pack_from_rows_supports_tokenized_evidence_schema():
    rows = [
        {
            "id": "s1",
            "problem_text": "deadline mismatch",
            "evidence": ["Deadline is 2026-04-01"],
            "evidence_dicts": [{"start": 10, "end": 20, "token": "Deadline is 2026-04-01"}],
        }
    ]
    pack = build_find_eval_pack_from_rows(rows, index_name="default")
    assert pack["samples_count"] == 1
    assert pack["corpus_count"] == 1


def test_build_find_eval_pack_from_rows_skips_too_long_queries():
    rows = [
        {
            "id": "s1",
            "problem_text": "x" * 100,
            "evidence_dicts": [{"id": "ev-1", "text": "Budget is 900 EUR"}],
        }
    ]
    pack = build_find_eval_pack_from_rows(rows, index_name="default", max_query_chars=32)
    assert pack["samples_count"] == 0
    assert pack["skipped_too_long_queries"] == 1
    assert pack["max_query_chars"] == 32


def test_build_wikipedia_contradict_eval_pack_from_rows():
    rows = [
        {
            "question_ID": 1,
            "question": "Which compound is present?",
            "context1": "Apomorphine is present.",
            "context2": "Aporphine is present.",
            "contradictType": "Implicit",
            "WikipediaArticleTitle": "Example",
        }
    ]
    pack = build_wikipedia_contradict_eval_pack_from_rows(rows, index_name="default")
    assert pack["samples_count"] == 1
    assert pack["corpus_count"] == 2
    assert pack["samples"][0].relevant_ids == {"1:context1", "1:context2"}
    assert pack["samples"][0].metadata["contradict_type"] == "Implicit"
