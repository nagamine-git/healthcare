from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin as admin_api
from app.api import advice_feedback as advice_feedback_api
from app.api import alcohol as alcohol_api
from app.api import bodyload as bodyload_api
from app.api import caffeine as caffeine_api
from app.api import checkin as checkin_api
from app.api import dashboard, debug, health_export
from app.api import domain as domain_api
from app.api import body_distribution as body_distribution_api
from app.api import fitness as fitness_api
from app.api import food as food_api
from app.api import imputation as imputation_api
from app.api import learning as learning_api
from app.api import life as life_api
from app.api import migraine as migraine_api
from app.api import profile as profile_api
from app.api import push as push_api
from app.api import sleep_drivers as sleep_drivers_api
from app.api import speech as speech_api
from app.api import timeline as timeline_api
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
    app.include_router(life_api.router)
    app.include_router(domain_api.router)
    app.include_router(learning_api.router)
    app.include_router(speech_api.router)
    app.include_router(admin_api.router)
    app.include_router(caffeine_api.router)
    app.include_router(bodyload_api.router)
    app.include_router(sleep_drivers_api.router)
    app.include_router(imputation_api.router)
    app.include_router(checkin_api.router)
    app.include_router(advice_feedback_api.router)
    app.include_router(migraine_api.router)
    app.include_router(profile_api.router)
    app.include_router(push_api.router)
    app.include_router(food_api.router)
    app.include_router(fitness_api.router)
    app.include_router(body_distribution_api.router)
    app.include_router(alcohol_api.router)
    app.include_router(timeline_api.router)
    app.include_router(debug.router)
    return app


app = create_app()
