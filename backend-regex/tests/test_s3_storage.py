"""Tests for MinIO S3 storage service."""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.ingest.s3_storage import MinIOStorage, get_minio_storage


@pytest.fixture
def mock_s3_client():
    """Mock boto3 S3 client."""
    with patch("app.ingest.s3_storage.boto3.client") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client


@pytest.fixture
def minio_storage(mock_s3_client):
    """Create MinIOStorage instance with mocked S3 client."""
    mock_s3_client.head_bucket.return_value = {}  # Buckets exist
    return MinIOStorage(
        endpoint="localhost:9000",
        access_key="test_key",
        secret_key="test_secret",
        secure=False,
    )


class TestMinIOStorageInit:
    """Tests for MinIOStorage initialization."""

    def test_init_creates_buckets(self, mock_s3_client):
        """Test that initialization creates buckets if they don't exist."""
        from botocore.exceptions import ClientError

        # First call says bucket doesn't exist (404)
        error_response = {"Error": {"Code": "404", "Message": "Not found"}}
        mock_s3_client.head_bucket.side_effect = ClientError(error_response, "HeadBucket")
        mock_s3_client.create_bucket.return_value = {}

        storage = MinIOStorage(
            endpoint="localhost:9000",
            access_key="test",
            secret_key="test",
        )

        # Should attempt to create buckets
        assert mock_s3_client.create_bucket.call_count == 3

    def test_init_buckets_exist(self, mock_s3_client):
        """Test initialization when buckets already exist."""
        mock_s3_client.head_bucket.return_value = {}

        storage = MinIOStorage(
            endpoint="localhost:9000",
            access_key="test",
            secret_key="test",
        )

        # Should not create buckets
        mock_s3_client.create_bucket.assert_not_called()


class TestSaveUploadedFile:
    """Tests for save_uploaded_file method."""

    def test_save_pdf_file(self, minio_storage, mock_s3_client):
        """Test saving a PDF file."""
        content = b"%PDF-1.4 fake content"

        key = minio_storage.save_uploaded_file(
            document_id="doc_123",
            filename="test.pdf",
            content=content,
        )

        assert key == "doc_123/test.pdf"
        # Verify file upload
        mock_s3_client.put_object.assert_any_call(
            Bucket="documents",
            Key="doc_123/test.pdf",
            Body=content,
            ContentType="application/pdf",
        )
        # Verify metadata upload
        assert any(
            call.kwargs["Key"] == "doc_123/metadata.json"
            for call in mock_s3_client.put_object.call_args_list
        )

    def test_save_jpeg_file(self, minio_storage, mock_s3_client):
        """Test saving a JPEG file."""
        content = b"\xff\xd8\xff\xe0 fake jpeg"

        key = minio_storage.save_uploaded_file(
            document_id="doc_123",
            filename="test.jpg",
            content=content,
        )

        assert key == "doc_123/test.jpg"
        mock_s3_client.put_object.assert_any_call(
            Bucket="documents",
            Key="doc_123/test.jpg",
            Body=content,
            ContentType="image/jpeg",
        )


class TestSaveExtractedContent:
    """Tests for save_extracted_content method."""

    def test_save_extracted_content(self, minio_storage, mock_s3_client):
        """Test saving OCR extracted content."""
        md_results = "# Test Document\n\nSome content"
        layout_details = [
            [{"index": 1, "label": "text", "bbox_2d": [0, 0, 1, 1], "content": "Test"}]
        ]
        ocr_response = {"model": "glm-ocr", "id": "task_123"}

        minio_storage.save_extracted_content(
            document_id="doc_123",
            md_results=md_results,
            layout_details=layout_details,
            ocr_response=ocr_response,
        )

        # Verify markdown saved
        mock_s3_client.put_object.assert_any_call(
            Bucket="extracted",
            Key="doc_123/content.md",
            Body=md_results.encode("utf-8"),
            ContentType="text/markdown",
        )
        # Verify layout saved
        assert any(
            call.kwargs["Key"] == "doc_123/layout.json"
            for call in mock_s3_client.put_object.call_args_list
        )
        # Verify metadata saved
        assert any(
            call.kwargs["Key"] == "doc_123/metadata.json"
            for call in mock_s3_client.put_object.call_args_list
        )


class TestGetExtractedContent:
    """Tests for get_extracted_content method."""

    def test_get_content_success(self, minio_storage, mock_s3_client):
        """Test getting extracted content."""
        # Create proper mock bodies with decode support
        class MockBody:
            def __init__(self, data):
                self.data = data
            def read(self):
                return self.data

        # Mock S3 responses - note: boto3 returns a dict-like object
        # but get_object() returns an object with Body attribute
        # The code uses response["Body"] which works with boto3's objects
        mock_s3_client.get_object.side_effect = [
            # Markdown
            {"Body": MockBody(b"# Test")},
            # Layout
            {"Body": MockBody(b'[[{"index":1}]]')},
            # Metadata (called twice)
            {"Body": MockBody(b'{"num_pages":1}')},
            {"Body": MockBody(b'{"num_pages":1}')},
        ]

        content = minio_storage.get_extracted_content("doc_123")

        assert content is not None
        assert content["markdown"] == "# Test"
        assert content["layout"] == [[{"index": 1}]]
        assert content["metadata"]["num_pages"] == 1

    def test_get_content_not_found(self, minio_storage, mock_s3_client):
        """Test getting content for non-existent document."""
        from botocore.exceptions import ClientError

        error = ClientError(
            {"Error": {"Code": "NoSuchKey", "Message": "Not found"}},
            "GetObject",
        )
        mock_s3_client.get_object.side_effect = error

        content = minio_storage.get_extracted_content("doc_123")

        assert content is None


class TestDeleteDocument:
    """Tests for delete_document method."""

    def test_delete_document(self, minio_storage, mock_s3_client):
        """Test deleting a document."""
        # Mock list_objects to return some files
        mock_s3_client.get_paginator.return_value.paginate.return_value = [
            {
                "Contents": [
                    {"Key": "doc_123/file.pdf"},
                    {"Key": "doc_123/metadata.json"},
                ]
            }
        ]

        deleted = minio_storage.delete_document("doc_123")

        assert deleted is True
        # Verify delete_objects was called for each bucket
        assert mock_s3_client.delete_objects.call_count >= 1

    def test_delete_nonexistent_document(self, minio_storage, mock_s3_client):
        """Test deleting a document that doesn't exist."""
        # Mock empty listings
        mock_s3_client.get_paginator.return_value.paginate.return_value = []

        deleted = minio_storage.delete_document("doc_123")

        assert deleted is False


class TestListDocuments:
    """Tests for list_documents method."""

    def test_list_documents(self, minio_storage, mock_s3_client):
        """Test listing all documents."""
        # Mock S3 list_objects_v2 response
        mock_s3_client.get_paginator.return_value.paginate.return_value = [
            {
                "CommonPrefixes": [
                    {"Prefix": "doc_1/"},
                    {"Prefix": "doc_2/"},
                ]
            }
        ]

        # Create proper mock bodies
        class MockBody:
            def __init__(self, data):
                self.data = data
            def read(self):
                return self.data

        body1 = MockBody(json.dumps({
            "document_id": "doc_1",
            "original_filename": "test1.pdf",
            "size_bytes": 1024,
            "uploaded_at": "2024-01-01T00:00:00",
        }).encode())

        body2 = MockBody(json.dumps({
            "document_id": "doc_2",
            "original_filename": "test2.pdf",
            "size_bytes": 2048,
            "uploaded_at": "2024-01-02T00:00:00",
        }).encode())

        # Mock metadata for each document - return dict with Body
        def mock_get_object(Bucket, Key):
            if "doc_1" in Key:
                return {"Body": body1}
            else:
                return {"Body": body2}

        mock_s3_client.get_object.side_effect = mock_get_object

        documents = minio_storage.list_documents()

        assert len(documents) == 2
        assert documents[0]["document_id"] == "doc_1"
        assert documents[0]["filename"] == "test1.pdf"
        assert documents[1]["document_id"] == "doc_2"


class TestHealthCheck:
    """Tests for health_check method."""

    def test_health_check_success(self, minio_storage, mock_s3_client):
        """Test successful health check."""
        mock_s3_client.list_buckets.return_value = {"Buckets": []}

        result = minio_storage.health_check()

        assert result is True

    def test_health_check_failure(self, minio_storage, mock_s3_client):
        """Test health check with connection failure."""
        mock_s3_client.list_buckets.side_effect = Exception("Connection failed")

        result = minio_storage.health_check()

        assert result is False


class TestCacheOperations:
    """Tests for cache operations."""

    def test_cache_set_and_get(self, minio_storage, mock_s3_client):
        """Test cache set and get operations."""
        data = b"cached data"

        minio_storage.cache_set("doc_123", "test_key", data)

        mock_s3_client.put_object.assert_called_with(
            Bucket="cache",
            Key="doc_123/test_key",
            Body=data,
        )

        # Test get - create proper mock body
        class MockBody:
            def __init__(self, data):
                self.data = data
            def read(self):
                return self.data

        body = MockBody(data)
        mock_s3_client.get_object.return_value = {"Body": body}

        result = minio_storage.cache_get("doc_123", "test_key")

        assert result == data

    def test_cache_delete(self, minio_storage, mock_s3_client):
        """Test cache delete."""
        minio_storage.cache_delete("doc_123", "test_key")

        mock_s3_client.delete_object.assert_called_with(
            Bucket="cache",
            Key="doc_123/test_key",
        )

    def test_processing_status_roundtrip(self, minio_storage, mock_s3_client):
        """Status payload should be persisted/retrieved from cache bucket."""
        minio_storage.set_processing_status(
            document_id="doc_123",
            status="processing",
            progress=0.5,
            pages_processed=1,
            total_pages=2,
            details={"stage": "ocr_running"},
        )
        assert any(
            call.kwargs["Key"] == "doc_123/status.json"
            for call in mock_s3_client.put_object.call_args_list
        )

        class MockBody:
            def __init__(self, data):
                self.data = data
            def read(self):
                return self.data

        mock_s3_client.get_object.return_value = {
            "Body": MockBody(
                json.dumps(
                    {
                        "document_id": "doc_123",
                        "status": "processing",
                        "progress": 0.5,
                        "pages_processed": 1,
                        "total_pages": 2,
                        "error": None,
                    }
                ).encode("utf-8")
            )
        }
        status = minio_storage.get_processing_status("doc_123")
        assert status is not None
        assert status["status"] == "processing"
        assert status["progress"] == 0.5


class TestUtilities:
    """Tests for utility methods."""

    def test_sanitize_filename(self):
        """Test filename sanitization."""
        assert MinIOStorage._sanitize_filename("test file.pdf") == "test_file.pdf"
        assert MinIOStorage._sanitize_filename("file@#$%.txt") == "file____.txt"  # @#$% -> ____ (4 underscores)
        assert MinIOStorage._sanitize_filename("") == "unnamed"

    def test_get_content_type(self):
        """Test content type detection."""
        assert MinIOStorage._get_content_type("test.pdf") == "application/pdf"
        assert MinIOStorage._get_content_type("test.jpg") == "image/jpeg"
        assert MinIOStorage._get_content_type("test.png") == "image/png"
        assert MinIOStorage._get_content_type("test.json") == "application/json"
        assert MinIOStorage._get_content_type("test.unknown") == "application/octet-stream"


class TestSingleton:
    """Tests for singleton pattern."""

    def test_get_minio_storage_singleton(self, mock_s3_client):
        """Test that get_minio_storage returns singleton."""
        mock_s3_client.head_bucket.return_value = {}

        storage1 = get_minio_storage()
        storage2 = get_minio_storage()

        assert storage1 is storage2
