import json
from typing import Any, Union

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration de l'application via variables d'environnement."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # NextPlaid
    next_plaid_url: str = "http://localhost:8081"
    next_plaid_timeout: int = 30

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # OCR API
    ocr_api_url: str = ""
    ocr_api_timeout: int = 60
    ocr_api_key: str = ""

    # LLM
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_default_model: str = "anthropic/claude-3-haiku"
    llm_timeout: int = 120
    llm_max_tokens: int = 4096
    llm_input_price_per_1k: float = 0.0
    llm_output_price_per_1k: float = 0.0
    embedding_model: str = "openrouter/qwen/qwen3-embedding-4b"
    embedding_dimensions: int | None = None
    search_auto_index: bool = True
    search_default_index: str = "default"
    hf_token: str = ""
    huggingface_hub_token: str = ""

    # Monitoring
    monitoring_enabled: bool = True
    otel_service_name: str = "docs-regex-backend"
    langfuse_host: str = "https://cloud.langfuse.com"
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""

    # Application
    app_name: str = "Docs Regex API"
    app_version: str = "0.1.0"
    debug: bool = False
    api_prefix: str = "/api/v1"

    # CORS - accepts string (comma-separated / JSON array) or list
    cors_origins: Union[str, list[str]] = (
        "http://localhost:3000,http://127.0.0.1:3000,"
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:8000,http://127.0.0.1:8000"
    )

    # Celery
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    celery_task_timeout: int = 300

    # Storage (local fallback)
    storage_documents_path: str = "./storage/documents"
    storage_indices_path: str = "./storage/indices"
    storage_cache_path: str = "./storage/cache"
    storage_experiments_db_path: str = "./storage/experiments.db"

    # MinIO S3 Configuration
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin123"
    minio_secure: bool = False
    minio_bucket_documents: str = "documents"
    minio_bucket_extracted: str = "extracted"
    minio_bucket_cache: str = "cache"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Any) -> list[str]:
        """Parse CORS origins from comma-separated string or list."""
        if isinstance(v, str):
            value = v.strip()
            if value.startswith("["):
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, list):
                        return [str(origin).strip() for origin in parsed if str(origin).strip()]
                except json.JSONDecodeError:
                    pass
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return v

    @field_validator("embedding_dimensions", mode="before")
    @classmethod
    def parse_optional_int(cls, v: Any) -> int | None:
        """Allow empty env values for optional integer settings."""
        if v in (None, ""):
            return None
        return int(v)


# Instance globale des settings
settings = Settings()


def get_settings() -> Settings:
    """Retourne l'instance des settings (pour dependency injection)."""
    return settings
