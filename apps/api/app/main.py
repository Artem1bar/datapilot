"""FastAPI application factory with lifespan, CORS, and all routers."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown hooks."""
    # Startup
    yield
    # Shutdown
    from app.services.progress import close_redis
    from app.services.rate_limit import close_redis_pool

    await close_redis()
    await close_redis_pool()

    from app.db.engine import engine

    await engine.dispose()


def create_app() -> FastAPI:
    """Build the FastAPI application with all routers and middleware."""
    app = FastAPI(
        title="DataPilot API",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Guard: wildcard origin + credentials is rejected by browsers and insecure
    if "*" in settings.cors_origins_list:
        raise ValueError(
            "CORS wildcard origin '*' is incompatible with allow_credentials=True. "
            "Set CORS_ORIGINS to explicit origins (e.g. 'http://localhost:5174')."
        )

    # CORS — explicit methods/headers instead of wildcards
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Accept"],
    )

    # --- Mount routers ---
    from app.routers.analysis import router as analysis_router
    from app.routers.auth import router as auth_router
    from app.routers.cleaning import router as cleaning_router
    from app.routers.datasets import router as datasets_router
    from app.routers.dictionary import router as dictionary_router
    from app.routers.exports import router as exports_router
    from app.routers.health import router as health_router
    from app.routers.jobs import router as jobs_router
    from app.routers.manipulation import router as manipulation_router
    from app.routers.recipes import router as recipes_router
    from app.routers.ws import router as ws_router

    # Health check at root level
    app.include_router(health_router)

    # All API routes under /api/v1
    app.include_router(auth_router, prefix="/api/v1/auth")
    app.include_router(datasets_router, prefix="/api/v1/datasets")
    app.include_router(jobs_router, prefix="/api/v1/jobs")
    app.include_router(cleaning_router, prefix="/api/v1/cleaning")
    app.include_router(recipes_router, prefix="/api/v1/recipes")
    app.include_router(analysis_router, prefix="/api/v1/analysis")
    app.include_router(manipulation_router, prefix="/api/v1/manipulation")
    app.include_router(exports_router, prefix="/api/v1/exports")
    app.include_router(dictionary_router, prefix="/api/v1/datasets")

    # WebSocket routes (not versioned)
    app.include_router(ws_router)

    return app


app = create_app()
