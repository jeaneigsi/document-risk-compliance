"""Tests de la configuration."""

from app.config import Settings, get_settings


def test_settings_singleton():
    """Vérifie que get_settings retourne toujours la même instance."""
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2


def test_settings_defaults():
    """Vérifie les valeurs par défaut des settings."""
    settings = Settings()
    assert settings.next_plaid_url == "http://localhost:8081"
    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.app_name == "Docs Regex API"
    assert settings.app_version == "0.1.0"
    assert settings.api_prefix == "/api/v1"
    assert settings.embedding_model.startswith("openrouter/qwen/qwen3-embedding-4b")
    assert settings.search_auto_index is True
    assert settings.search_default_index == "default"
    assert settings.monitoring_enabled is True
    assert settings.otel_service_name == "docs-regex-backend"


def test_settings_cors_origins():
    """Vérifie la configuration CORS par défaut."""
    settings = Settings()
    assert "http://localhost:3000" in settings.cors_origins
    assert "http://localhost:8000" in settings.cors_origins


def test_settings_storage_paths():
    """Vérifie les chemins de stockage par défaut."""
    settings = Settings()
    assert settings.storage_documents_path == "./storage/documents"
    assert settings.storage_indices_path == "./storage/indices"
    assert settings.storage_cache_path == "./storage/cache"


def test_settings_celery_config():
    """Vérifie la configuration Celery par défaut."""
    settings = Settings()
    assert settings.celery_broker_url == "redis://localhost:6379/1"
    assert settings.celery_result_backend == "redis://localhost:6379/2"
    assert settings.celery_task_timeout == 300
