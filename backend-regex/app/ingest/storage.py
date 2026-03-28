"""Storage service for documents and extracted content."""

import hashlib
import json
from pathlib import Path
from typing import Optional
from datetime import datetime
import logging

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class DocumentStorage:
    """
    Manages document storage on local filesystem.

    Structure:
    storage/
    ├── documents/          # Original uploaded files
    │   └── {doc_id}/
    │       ├── original.pdf
    │       └── metadata.json
    ├── extracted/          # OCR results
    │   └── {doc_id}/
    │   ├── content.md      # Markdown content
    │   ├── layout.json     # Layout details
    │   └── metadata.json
    └── cache/              # Temporary processing files
        └── {doc_id}/
    """

    def __init__(self, base_path: Optional[str] = None):
        """
        Initialize storage with base path.

        Args:
            base_path: Base storage path (defaults to settings.storage_documents_path)
        """
        self.base_path = Path(base_path or settings.storage_documents_path)
        self.documents_path = self.base_path / "documents"
        self.extracted_path = self.base_path / "extracted"
        self.cache_path = self.base_path / "cache"

        # Create directories
        for path in [self.documents_path, self.extracted_path, self.cache_path]:
            path.mkdir(parents=True, exist_ok=True)

        logger.info(f"DocumentStorage initialized at: {self.base_path}")

    def get_document_path(self, document_id: str) -> Path:
        """Get storage directory for a document."""
        doc_path = self.documents_path / document_id
        doc_path.mkdir(exist_ok=True)
        return doc_path

    def get_extracted_path(self, document_id: str) -> Path:
        """Get extracted content directory for a document."""
        extracted_path = self.extracted_path / document_id
        extracted_path.mkdir(exist_ok=True)
        return extracted_path

    def get_cache_path(self, document_id: str) -> Path:
        """Get cache directory for a document."""
        cache_path = self.cache_path / document_id
        cache_path.mkdir(exist_ok=True)
        return cache_path

    def save_uploaded_file(
        self,
        document_id: str,
        filename: str,
        content: bytes,
    ) -> Path:
        """
        Save an uploaded file to storage.

        Args:
            document_id: Unique document identifier
            filename: Original filename
            content: File content as bytes

        Returns:
            Path to saved file
        """
        doc_path = self.get_document_path(document_id)

        # Save with sanitized filename
        safe_filename = self._sanitize_filename(filename)
        file_path = doc_path / safe_filename

        with open(file_path, "wb") as f:
            f.write(content)

        # Calculate hash for integrity check
        file_hash = hashlib.sha256(content).hexdigest()

        # Save metadata
        metadata = {
            "document_id": document_id,
            "original_filename": filename,
            "saved_filename": safe_filename,
            "size_bytes": len(content),
            "sha256": file_hash,
            "uploaded_at": datetime.utcnow().isoformat(),
        }

        metadata_path = doc_path / "metadata.json"
        with open(metadata_path, "w") as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"Saved uploaded file: {file_path} ({len(content)} bytes)")
        return file_path

    def save_extracted_content(
        self,
        document_id: str,
        md_results: str,
        layout_details: list,
        ocr_response: dict,
    ) -> None:
        """
        Save OCR extraction results.

        Args:
            document_id: Unique document identifier
            md_results: Markdown content
            layout_details: Layout elements
            ocr_response: Full OCR response for reference
        """
        extracted_path = self.get_extracted_path(document_id)

        # Save markdown content
        md_path = extracted_path / "content.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_results)

        # Save layout as JSON
        layout_path = extracted_path / "layout.json"
        with open(layout_path, "w", encoding="utf-8") as f:
            json.dump(layout_details, f, indent=2, ensure_ascii=False)

        # Save extraction metadata
        extraction_metadata = {
            "document_id": document_id,
            "extracted_at": datetime.utcnow().isoformat(),
            "num_pages": len(layout_details),
            "num_elements": sum(len(page) for page in layout_details),
            "ocr_response": ocr_response,
        }

        metadata_path = extracted_path / "metadata.json"
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(extraction_metadata, f, indent=2, ensure_ascii=False)

        logger.info(f"Saved extracted content for: {document_id}")

    def get_file_path(self, document_id: str) -> Optional[Path]:
        """Get path to stored original file."""
        doc_path = self.get_document_path(document_id)
        metadata_path = doc_path / "metadata.json"

        if not metadata_path.exists():
            return None

        with open(metadata_path) as f:
            metadata = json.load(f)

        return doc_path / metadata["saved_filename"]

    def get_extracted_content(self, document_id: str) -> Optional[dict]:
        """
        Load extracted content for a document.

        Returns:
            Dict with 'markdown', 'layout', 'metadata' or None if not found
        """
        extracted_path = self.get_extracted_path(document_id)

        md_path = extracted_path / "content.md"
        layout_path = extracted_path / "layout.json"
        metadata_path = extracted_path / "metadata.json"

        if not all(p.exists() for p in [md_path, layout_path, metadata_path]):
            return None

        with open(md_path, encoding="utf-8") as f:
            markdown = f.read()

        with open(layout_path) as f:
            layout = json.load(f)

        with open(metadata_path) as f:
            metadata = json.load(f)

        return {
            "markdown": markdown,
            "layout": layout,
            "metadata": metadata,
        }

    def delete_document(self, document_id: str) -> bool:
        """
        Delete all stored data for a document.

        Returns:
            True if deleted, False if not found
        """
        deleted = False

        for path in [
            self.documents_path / document_id,
            self.extracted_path / document_id,
            self.cache_path / document_id,
        ]:
            if path.exists():
                for item in path.glob("*"):
                    item.unlink()
                path.rmdir()
                deleted = True

        if deleted:
            logger.info(f"Deleted all data for document: {document_id}")

        return deleted

    def list_documents(self) -> list[dict]:
        """List all stored documents with metadata."""
        documents = []

        for doc_path in self.documents_path.iterdir():
            if not doc_path.is_dir():
                continue

            metadata_path = doc_path / "metadata.json"
            if not metadata_path.exists():
                continue

            with open(metadata_path) as f:
                metadata = json.load(f)

            documents.append({
                "document_id": doc_path.name,
                "filename": metadata["original_filename"],
                "size_bytes": metadata["size_bytes"],
                "uploaded_at": metadata["uploaded_at"],
                "sha256": metadata["sha256"],
            })

        return documents

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        """
        Sanitize filename for safe filesystem storage.

        Keeps only alphanumeric, dots, hyphens, underscores.
        """
        import re
        # Remove path separators and special chars
        safe = re.sub(r'[^\w\-\.]', '_', filename)
        # Ensure it's not empty
        return safe or "unnamed"


# Singleton instance
_storage: Optional[DocumentStorage] = None


def get_storage() -> DocumentStorage:
    """Get or create the singleton DocumentStorage instance."""
    global _storage
    if _storage is None:
        _storage = DocumentStorage()
    return _storage
