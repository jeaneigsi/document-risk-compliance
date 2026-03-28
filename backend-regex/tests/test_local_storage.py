"""Tests for local filesystem DocumentStorage fallback."""

from app.ingest import storage as storage_module
from app.ingest.storage import DocumentStorage


def test_save_uploaded_file_and_get_file_path(tmp_path):
    """Uploaded file is persisted with metadata and retrievable path."""
    storage = DocumentStorage(base_path=str(tmp_path / "storage"))
    content = b"hello-world"

    saved_path = storage.save_uploaded_file(
        document_id="doc_1",
        filename="my report.pdf",
        content=content,
    )

    assert saved_path.exists()
    assert saved_path.name == "my_report.pdf"

    loaded_path = storage.get_file_path("doc_1")
    assert loaded_path == saved_path


def test_save_and_load_extracted_content(tmp_path):
    """Extracted OCR artifacts are saved and loaded consistently."""
    storage = DocumentStorage(base_path=str(tmp_path / "storage"))
    storage.save_uploaded_file("doc_2", "source.pdf", b"pdf-content")

    storage.save_extracted_content(
        document_id="doc_2",
        md_results="# Title\n\nBody",
        layout_details=[[{"index": 1, "label": "text", "content": "Body"}]],
        ocr_response={"id": "task-1", "model": "glm-ocr"},
    )

    extracted = storage.get_extracted_content("doc_2")
    assert extracted is not None
    assert extracted["markdown"] == "# Title\n\nBody"
    assert extracted["metadata"]["num_pages"] == 1
    assert extracted["metadata"]["num_elements"] == 1


def test_get_extracted_content_missing_returns_none(tmp_path):
    """Missing extracted assets should return None."""
    storage = DocumentStorage(base_path=str(tmp_path / "storage"))
    assert storage.get_extracted_content("missing") is None


def test_list_documents_and_delete_document(tmp_path):
    """Documents listing and deletion should reflect persisted state."""
    storage = DocumentStorage(base_path=str(tmp_path / "storage"))

    storage.save_uploaded_file("doc_a", "a.pdf", b"a")
    storage.save_uploaded_file("doc_b", "b.pdf", b"b")

    docs = storage.list_documents()
    assert len(docs) == 2
    assert {doc["document_id"] for doc in docs} == {"doc_a", "doc_b"}

    assert storage.delete_document("doc_a") is True
    assert storage.get_file_path("doc_a") is None
    assert storage.delete_document("does-not-exist") is False


def test_sanitize_filename():
    """Filename sanitization keeps only safe characters."""
    assert DocumentStorage._sanitize_filename("weird / report?.pdf") == "weird___report_.pdf"
    assert DocumentStorage._sanitize_filename("") == "unnamed"


def test_get_storage_singleton(monkeypatch, tmp_path):
    """get_storage should reuse a singleton instance."""
    storage_module._storage = None
    monkeypatch.setattr(storage_module.settings, "storage_documents_path", str(tmp_path / "singleton-root"))

    s1 = storage_module.get_storage()
    s2 = storage_module.get_storage()

    assert s1 is s2
