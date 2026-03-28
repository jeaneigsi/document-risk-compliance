from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.compare.history import init_compare_history_db
from app.eval.history import init_experiment_history_db


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Gestion du cycle de vie de l'application."""
    # Startup
    print(f"Starting {settings.app_name} v{settings.app_version}")
    print(f"NextPlaid URL: {settings.next_plaid_url}")
    print(f"Redis URL: {settings.redis_url}")
    init_experiment_history_db()
    init_compare_history_db()
    yield
    # Shutdown
    print("Shutting down application")


# Création de l'application FastAPI
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="API de détection d'incohérences documentaires",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Configuration CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health check endpoint
@app.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    """Vérifie que l'API fonctionne."""
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": settings.app_version,
    }


# Root endpoint
@app.get("/", tags=["root"])
async def root() -> dict[str, str]:
    """Point d'entrée de l'API."""
    return {
        "message": "Docs Regex API",
        "version": settings.app_version,
        "docs": "/docs",
    }


# Import des routes (Phase 2: ingest)
from app.api.routes import router
app.include_router(router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
    )
