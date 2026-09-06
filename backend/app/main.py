"""Application entry point: `uvicorn --factory app.main:create_app`.

Deliberately no module-level `app = create_app()`: the application (and config
validation) is created only when the process starts, so `import app.main` works
without a full set of environment variables (tests, alembic, OpenAPI export).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import get_engine
from app.routers import clients, health, imports


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = get_engine()
    yield
    engine.dispose()


def create_app() -> FastAPI:
    # Fail-fast: a missing environment variable is a startup error, not a 500 on the first request.
    settings = get_settings()
    # Swagger/OpenAPI outside prod only — a public /openapi.json is a free map of the API.
    docs = settings.app_env != "prod"
    app = FastAPI(
        title="Charm Skin API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs else None,
    )
    # The frontend (Astro, different origin) calls the API via fetch from the browser —
    # without CORS the browser blocks the response even though the backend works.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(clients.router)
    app.include_router(clients.visits_router)
    app.include_router(imports.router)
    return app
