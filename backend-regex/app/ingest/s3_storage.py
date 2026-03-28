"""MinIO S3 storage service for documents and extracted content."""

import json
import logging
from typing import Optional
from datetime import datetime
import hashlib

import boto3
from botocore.client import Config as BotoConfig
from botocore.exceptions import ClientError

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class MinIOStorage:
    """
    MinIO S3-compatible storage service.

    Buckets:
    - documents: Original uploaded files
    - extracted: OCR results (markdown, layout JSON, metadata)
    - cache: Temporary processing files

    All data stored under {bucket}/{document_id}/...
    """

    def __init__(
        self,
        endpoint: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        secure: Optional[bool] = None,
    ):
        """
        Initialize MinIO S3 client.

        Args:
            endpoint: MinIO server endpoint (defaults to settings.minio_endpoint)
            access_key: Access key (defaults to settings.minio_access_key)
            secret_key: Secret key (defaults to settings.minio_secret_key)
            secure: Use HTTPS (defaults to settings.minio_secure)
        """
        self.endpoint = endpoint or settings.minio_endpoint
        self.access_key = access_key or settings.minio_access_key
        self.secret_key = secret_key or settings.minio_secret_key
        self.secure = secure if secure is not None else settings.minio_secure

        # Bucket names
        self.bucket_documents = settings.minio_bucket_documents
        self.bucket_extracted = settings.minio_bucket_extracted
        self.bucket_cache = settings.minio_bucket_cache

        # Initialize S3 client
        self.s3_client = boto3.client(
            "s3",
            endpoint_url=f"http{'s' if self.secure else ''}://{self.endpoint}",
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            config=BotoConfig(
                signature_version="s3v4",
                connect_timeout=5,
                read_timeout=10,
                retries={"max_attempts": 3},
            ),
        )

        # Ensure buckets exist
        self._ensure_buckets()

        logger.info(f"MinIOStorage initialized: {self.endpoint}")

    def _ensure_buckets(self):
        """Create buckets if they don't exist."""
        for bucket in [self.bucket_documents, self.bucket_extracted, self.bucket_cache]:
            try:
                self.s3_client.head_bucket(Bucket=bucket)
                logger.debug(f"Bucket exists: {bucket}")
            except ClientError as e:
                if e.response["Error"]["Code"] == "404":
                    try:
                        self.s3_client.create_bucket(Bucket=bucket)
                        logger.info(f"Created bucket: {bucket}")
                    except ClientError as create_error:
                        logger.error(f"Failed to create bucket {bucket}: {create_error}")
                        raise
                else:
                    logger.error(f"Error checking bucket {bucket}: {e}")
                    raise

    # ========================================================================
    # Document Upload
    # ========================================================================

    def save_uploaded_file(
        self,
        document_id: str,
        filename: str,
        content: bytes,
    ) -> str:
        """
        Save an uploaded file to MinIO.

        Args:
            document_id: Unique document identifier
            filename: Original filename
            content: File content as bytes

        Returns:
            S3 object key
        """
        safe_filename = self._sanitize_filename(filename)
        key = f"{document_id}/{safe_filename}"

        # Upload file
        self.s3_client.put_object(
            Bucket=self.bucket_documents,
            Key=key,
            Body=content,
            ContentType=self._get_content_type(filename),
        )

        # Create and upload metadata
        file_hash = hashlib.sha256(content).hexdigest()
        metadata = {
            "document_id": document_id,
            "original_filename": filename,
            "saved_filename": safe_filename,
            "size_bytes": len(content),
            "sha256": file_hash,
            "uploaded_at": datetime.utcnow().isoformat(),
        }

        metadata_key = f"{document_id}/metadata.json"
        self.s3_client.put_object(
            Bucket=self.bucket_documents,
            Key=metadata_key,
            Body=json.dumps(metadata, indent=2).encode("utf-8"),
            ContentType="application/json",
        )

        logger.info(f"Saved uploaded file to MinIO: {self.bucket_documents}/{key} ({len(content)} bytes)")
        return key

    # ========================================================================
    # Extracted Content
    # ========================================================================

    def save_extracted_content(
        self,
        document_id: str,
        md_results: str,
        layout_details: list,
        ocr_response: dict,
    ) -> None:
        """
        Save OCR extraction results to MinIO.

        Args:
            document_id: Unique document identifier
            md_results: Markdown content
            layout_details: Layout elements (list of list of LayoutElement)
            ocr_response: Full OCR response for reference
        """
        # Save markdown content
        md_key = f"{document_id}/content.md"
        self.s3_client.put_object(
            Bucket=self.bucket_extracted,
            Key=md_key,
            Body=md_results.encode("utf-8"),
            ContentType="text/markdown",
        )

        # Convert LayoutElement objects to dicts for JSON serialization
        layout_serializable = []
        for page in layout_details:
            page_elements = []
            for element in page:
                # Handle both dict and LayoutElement objects
                if hasattr(element, "model_dump"):
                    element_dict = element.model_dump()
                elif hasattr(element, "dict"):
                    element_dict = element.dict()
                else:
                    element_dict = element
                page_elements.append(element_dict)
            layout_serializable.append(page_elements)

        # Save layout as JSON
        layout_key = f"{document_id}/layout.json"
        self.s3_client.put_object(
            Bucket=self.bucket_extracted,
            Key=layout_key,
            Body=json.dumps(layout_serializable, indent=2, ensure_ascii=False).encode("utf-8"),
            ContentType="application/json",
        )

        # Save extraction metadata
        extraction_metadata = {
            "document_id": document_id,
            "extracted_at": datetime.utcnow().isoformat(),
            "num_pages": len(layout_details),
            "num_elements": sum(len(page) for page in layout_details),
            "ocr_response": ocr_response,
        }

        metadata_key = f"{document_id}/metadata.json"
        self.s3_client.put_object(
            Bucket=self.bucket_extracted,
            Key=metadata_key,
            Body=json.dumps(extraction_metadata, indent=2, ensure_ascii=False).encode("utf-8"),
            ContentType="application/json",
        )

        logger.info(f"Saved extracted content to MinIO: {document_id}")

    # ========================================================================
    # Retrieval
    # ========================================================================

    def get_file_content(self, document_id: str, filename: Optional[str] = None) -> Optional[bytes]:
        """
        Get original file content from MinIO.

        Args:
            document_id: Document identifier
            filename: Optional specific filename (if None, looks for first file)

        Returns:
            File content as bytes or None if not found
        """
        try:
            # If filename not specified, get from metadata
            if filename is None:
                metadata = self._get_metadata(document_id, self.bucket_documents)
                if metadata:
                    filename = metadata.get("saved_filename")
                else:
                    return None

            key = f"{document_id}/{filename}"
            response = self.s3_client.get_object(Bucket=self.bucket_documents, Key=key)
            return response["Body"].read()
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                logger.warning(f"File not found: {document_id}/{filename}")
                return None
            raise

    def get_extracted_content(self, document_id: str) -> Optional[dict]:
        """
        Load extracted content for a document.

        Returns:
            Dict with 'markdown', 'layout', 'metadata' or None if not found
        """
        try:
            # Get markdown
            md_key = f"{document_id}/content.md"
            md_response = self.s3_client.get_object(Bucket=self.bucket_extracted, Key=md_key)
            markdown = md_response["Body"].read().decode("utf-8")

            # Get layout
            layout_key = f"{document_id}/layout.json"
            layout_response = self.s3_client.get_object(Bucket=self.bucket_extracted, Key=layout_key)
            layout = json.loads(layout_response["Body"].read().decode("utf-8"))

            # Get metadata
            metadata = self._get_metadata(document_id, self.bucket_extracted)

            return {
                "markdown": markdown,
                "layout": layout,
                "metadata": metadata or {},
            }
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                logger.warning(f"Extracted content not found: {document_id}")
                return None
            raise

    def _get_metadata(self, document_id: str, bucket: str) -> Optional[dict]:
        """Get metadata JSON for a document."""
        try:
            metadata_key = f"{document_id}/metadata.json"
            response = self.s3_client.get_object(Bucket=bucket, Key=metadata_key)
            return json.loads(response["Body"].read().decode("utf-8"))
        except ClientError:
            return None

    # ========================================================================
    # Listing & Deletion
    # ========================================================================

    def list_documents(self) -> list[dict]:
        """List all stored documents with metadata."""
        documents = []

        try:
            paginator = self.s3_client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket_documents, Delimiter="/"):
                for prefix in page.get("CommonPrefixes", []):
                    document_id = prefix["Prefix"].strip("/")
                    metadata = self._get_metadata(document_id, self.bucket_documents)
                    if metadata:
                        documents.append({
                            "document_id": document_id,
                            "filename": metadata.get("original_filename"),
                            "size_bytes": metadata.get("size_bytes", 0),
                            "uploaded_at": metadata.get("uploaded_at"),
                            "sha256": metadata.get("sha256"),
                        })
        except ClientError as e:
            logger.error(f"Error listing documents: {e}")

        return documents

    def delete_document(self, document_id: str) -> bool:
        """
        Delete all stored data for a document.

        Returns:
            True if deleted, False if not found
        """
        deleted = False

        for bucket in [self.bucket_documents, self.bucket_extracted, self.bucket_cache]:
            try:
                # List all objects with document_id prefix
                paginator = self.s3_client.get_paginator("list_objects_v2")
                objects_to_delete = []

                for page in paginator.paginate(Bucket=bucket, Prefix=f"{document_id}/"):
                    for obj in page.get("Contents", []):
                        objects_to_delete.append({"Key": obj["Key"]})

                if objects_to_delete:
                    self.s3_client.delete_objects(
                        Bucket=bucket,
                        Delete={"Objects": [{"Key": o["Key"]} for o in objects_to_delete]}
                    )
                    deleted = True
                    logger.info(f"Deleted {len(objects_to_delete)} objects from {bucket}/{document_id}")

            except ClientError as e:
                logger.error(f"Error deleting from {bucket}: {e}")

        if deleted:
            logger.info(f"Deleted all data for document: {document_id}")

        return deleted

    # ========================================================================
    # Cache Operations
    # ========================================================================

    def cache_get(self, document_id: str, key: str) -> Optional[bytes]:
        """Get cached data."""
        cache_key = f"{document_id}/{key}"
        try:
            response = self.s3_client.get_object(Bucket=self.bucket_cache, Key=cache_key)
            return response["Body"].read()
        except ClientError:
            return None

    def cache_set(self, document_id: str, key: str, data: bytes, ttl_seconds: int = 3600) -> None:
        """Store data in cache."""
        cache_key = f"{document_id}/{key}"
        self.s3_client.put_object(
            Bucket=self.bucket_cache,
            Key=cache_key,
            Body=data,
        )

    def cache_delete(self, document_id: str, key: Optional[str] = None) -> None:
        """Delete cached data. If key is None, delete all cache for document."""
        if key is None:
            # Delete all cache for document
            try:
                paginator = self.s3_client.get_paginator("list_objects_v2")
                objects_to_delete = []

                for page in paginator.paginate(Bucket=self.bucket_cache, Prefix=f"{document_id}/"):
                    for obj in page.get("Contents", []):
                        objects_to_delete.append({"Key": obj["Key"]})

                if objects_to_delete:
                    self.s3_client.delete_objects(
                        Bucket=self.bucket_cache,
                        Delete={"Objects": [{"Key": o["Key"]} for o in objects_to_delete]}
                    )
            except ClientError:
                pass
        else:
            cache_key = f"{document_id}/{key}"
            try:
                self.s3_client.delete_object(Bucket=self.bucket_cache, Key=cache_key)
            except ClientError:
                pass

    def set_processing_status(
        self,
        document_id: str,
        status: str,
        progress: float = 0.0,
        pages_processed: int = 0,
        total_pages: int = 0,
        error: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> None:
        """Persist ingestion status/progress in cache bucket."""
        payload = {
            "document_id": document_id,
            "status": status,
            "progress": max(0.0, min(1.0, float(progress))),
            "pages_processed": int(pages_processed),
            "total_pages": int(total_pages),
            "error": error,
            "details": details or {},
            "updated_at": datetime.utcnow().isoformat(),
        }
        key = f"{document_id}/status.json"
        self.s3_client.put_object(
            Bucket=self.bucket_cache,
            Key=key,
            Body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            ContentType="application/json",
        )

    def get_processing_status(self, document_id: str) -> Optional[dict]:
        """Read ingestion status/progress from cache bucket."""
        key = f"{document_id}/status.json"
        try:
            response = self.s3_client.get_object(Bucket=self.bucket_cache, Key=key)
            return json.loads(response["Body"].read().decode("utf-8"))
        except ClientError:
            return None
        else:
            cache_key = f"{document_id}/{key}"
            try:
                self.s3_client.delete_object(Bucket=self.bucket_cache, Key=cache_key)
            except ClientError:
                pass

    # ========================================================================
    # Utilities
    # ========================================================================

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        """Sanitize filename for safe S3 key storage."""
        import re
        safe = re.sub(r'[^\w\-\.]', '_', filename)
        return safe or "unnamed"

    @staticmethod
    def _get_content_type(filename: str) -> str:
        """Get content type based on filename extension."""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        content_types = {
            "pdf": "application/pdf",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "json": "application/json",
            "md": "text/markdown",
            "txt": "text/plain",
        }
        return content_types.get(ext, "application/octet-stream")

    def health_check(self) -> bool:
        """Check if MinIO is accessible."""
        try:
            # Try to list buckets (lightweight operation)
            self.s3_client.list_buckets()
            return True
        except Exception as e:
            logger.warning(f"MinIO health check failed: {e}")
            return False


# Singleton instance
_storage: Optional[MinIOStorage] = None


def get_minio_storage() -> MinIOStorage:
    """Get or create the singleton MinIOStorage instance."""
    global _storage
    if _storage is None:
        _storage = MinIOStorage()
    return _storage
