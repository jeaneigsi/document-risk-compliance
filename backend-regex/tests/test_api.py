"""Tests de l'API FastAPI."""

from fastapi.testclient import TestClient

from app.api.main import app


def test_health_check():
    """Test du endpoint health."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "service" in data
    assert "version" in data


def test_root_endpoint():
    """Test du endpoint racine."""
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert "version" in data
    assert data["docs"] == "/docs"


def test_cors_headers():
    """Test que les headers CORS sont présents."""
    client = TestClient(app)
    response = client.get("/", headers={"Origin": "http://localhost:3000"})
    assert response.status_code == 200
    # Vérifie la présence du header CORS (FastAPI le gère via middleware)
    assert "access-control-allow-origin" in response.headers


def test_docs_endpoint():
    """Test que la documentation Swagger est accessible."""
    client = TestClient(app)
    response = client.get("/docs")
    assert response.status_code == 200


def test_redoc_endpoint():
    """Test que la documentation ReDoc est accessible."""
    client = TestClient(app)
    response = client.get("/redoc")
    assert response.status_code == 200
