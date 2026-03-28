"""Tests for PDF parser helpers."""

from types import SimpleNamespace

import pytest

from app.ingest import parser as parser_module


def test_parse_pdf_file_not_found():
    with pytest.raises(FileNotFoundError):
        parser_module.parse_pdf("/tmp/definitely-missing.pdf")


def test_parse_pdf_uses_fitz(monkeypatch, tmp_path):
    path = tmp_path / "sample.pdf"
    path.write_bytes(b"%PDF-1.4")

    class FakePage:
        def __init__(self, idx):
            self.idx = idx

        def get_text(self, mode):
            assert mode == "text"
            return f"page-{self.idx}"

    class FakeDoc:
        metadata = {"author": "tester"}

        def __len__(self):
            return 2

        def __getitem__(self, idx):
            return FakePage(idx + 1)

    fake_fitz = SimpleNamespace(open=lambda _: FakeDoc())
    monkeypatch.setattr(parser_module, "_load_fitz", lambda: fake_fitz)

    parsed = parser_module.parse_pdf(path)
    assert parsed.total_pages == 2
    assert parsed.metadata["author"] == "tester"
    assert parsed.pages[0].text == "page-1"
    assert parsed.pages[1].page_number == 2


def test_parse_pdf_with_table_extraction(monkeypatch, tmp_path):
    path = tmp_path / "sample.pdf"
    path.write_bytes(b"%PDF-1.4")

    class FakePage:
        def get_text(self, mode):
            return "text"

    class FakeDoc:
        metadata = {}

        def __len__(self):
            return 1

        def __getitem__(self, idx):
            return FakePage()

    class FakeTable:
        page = 1
        df = SimpleNamespace(shape=(2, 3))

    fake_fitz = SimpleNamespace(open=lambda _: FakeDoc())
    fake_camelot = SimpleNamespace(read_pdf=lambda *args, **kwargs: [FakeTable()])
    monkeypatch.setattr(parser_module, "_load_fitz", lambda: fake_fitz)
    monkeypatch.setattr(parser_module, "_load_camelot", lambda: fake_camelot)

    parsed = parser_module.parse_pdf(path, extract_tables=True)
    assert len(parsed.pages[0].tables) == 1
    assert parsed.pages[0].tables[0]["shape"] == (2, 3)

