"""Tests for evidence unit mapping."""

from app.search.evidence import build_evidence_units_from_ocr, map_find_to_evidence_units


def test_map_find_to_evidence_units():
    record = {
        "problem_text": "Date contradiction",
        "evidence_dicts": [
            {
                "type": "date_conflict",
                "spans": [
                    {"text": "2026-03-25", "page": 2, "start": 10, "end": 20},
                    {"text": "2026-04-01", "page": 4, "start": 30, "end": 40},
                ],
            }
        ],
    }

    units = map_find_to_evidence_units(record, document_id="find-doc-1")
    assert len(units) == 2
    assert units[0].document_id == "find-doc-1"
    assert units[0].source_type == "date_conflict"
    assert units[0].page_number == 2
    assert units[0].metadata["problem_text"] == "Date contradiction"


def test_map_find_to_evidence_units_ignores_empty_spans():
    record = {"evidence_dicts": [{"type": "x", "spans": [{"text": ""}, {"text": "ok"}]}]}
    units = map_find_to_evidence_units(record, document_id="doc")
    assert len(units) == 1
    assert units[0].content == "ok"


def test_build_evidence_units_from_ocr_layout():
    layout_details = [
        [{"index": 1, "label": "text", "content": "Alpha"}],
        [{"index": 2, "label": "table", "content": "Beta"}],
    ]
    units = build_evidence_units_from_ocr(
        document_id="doc-1",
        filename="file.pdf",
        md_results="# md",
        layout_details=layout_details,
    )
    assert len(units) == 2
    assert units[0].evidence_id == "doc-1:p1:e0"
    assert units[1].page_number == 2


def test_build_evidence_units_from_ocr_fallback_to_markdown():
    units = build_evidence_units_from_ocr(
        document_id="doc-1",
        filename="file.pdf",
        md_results="markdown payload",
        layout_details=[],
    )
    assert len(units) == 1
    assert units[0].source_type == "markdown"


def test_build_evidence_units_from_ocr_adds_missing_markdown_blocks():
    units = build_evidence_units_from_ocr(
        document_id="doc-1",
        filename="file.pdf",
        md_results="Alpha\n\nBeta paragraph\n\nGamma paragraph",
        layout_details=[[{"index": 1, "label": "text", "content": "Alpha"}]],
    )
    assert len(units) == 3
    assert units[0].content == "Alpha"
    assert units[1].source_type == "markdown_block"
    assert units[1].content == "Beta paragraph"
    assert units[2].content == "Gamma paragraph"
