"""Fixtures pytest pour les tests."""

import pytest
from pytest_asyncio import is_async_test

from app.config import Settings, get_settings


@pytest.fixture
def settings() -> Settings:
    """Retourne une instance de Settings pour les tests."""
    return get_settings()


# Configuration pour pytest-asyncio
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Marque automatiquement les tests async comme asynchrones."""
    pytest_asyncio_tests = (item for item in items if is_async_test(item))
    session_scope_marker = pytest.mark.asyncio(loop_scope="session")
    for async_test in pytest_asyncio_tests:
        async_test.add_marker(session_scope_marker, append=False)


@pytest.fixture
def sample_document_path() -> str:
    """Chemin vers un document de test."""
    return "./storage/documents/test_sample.pdf"


@pytest.fixture
def sample_claim() -> dict:
    """Claim de test."""
    return {
        "id": "claim_001",
        "statement": "Le budget annuel est de 50M€",
        "document_id": "doc_001",
        "page_number": 3,
        "metadata": {"category": "financial"},
    }


@pytest.fixture
def sample_evidence() -> dict:
    """Preuve de test."""
    return {
        "id": "ev_001",
        "content": "Le budget annuel prévisionnel s'élève à 50 millions d'euros.",
        "document_id": "doc_002",
        "page_number": 12,
        "confidence": 0.95,
    }
