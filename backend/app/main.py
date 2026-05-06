from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin as admin_api
from app.api import dashboard, health_export
from app.config import get_settings
from app.db import create_all, init_engine
from app.logging import configure_logging, get_logger
from app.scheduler import setup_scheduler, shutdown_scheduler

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.app_log_level)
    init_engine(settings.resolved_db_path())
    create_all()
    if settings.scheduler_enabled:
        setup_scheduler()
    logger.info("startup_complete", db=str(settings.resolved_db_path()))
    yield
    if settings.scheduler_enabled:
        shutdown_scheduler()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Healthcare Dashboard", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(health_export.router)
    app.include_router(dashboard.router)
    app.include_router(admin_api.router)
    return app


app = create_app()
