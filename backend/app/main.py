from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import activity as activity_api
from app.api import admin as admin_api
from app.api import advice_feedback as advice_feedback_api
from app.api import airgap as airgap_api
from app.api import airgap_insight as airgap_insight_api
from app.api import alcohol as alcohol_api
from app.api import appointment_plan as appointment_plan_api
from app.api import atlas as atlas_api
from app.api import becoming as becoming_api
from app.api import body_comp as body_comp_api
from app.api import body_distribution as body_distribution_api
from app.api import body_measurement as body_measurement_api
from app.api import bodyload as bodyload_api
from app.api import caffeine as caffeine_api
from app.api import checkin as checkin_api
from app.api import checkup as checkup_api
from app.api import consult as consult_api
from app.api import corporate_finance as corporate_finance_api
from app.api import dashboard, debug, health_export
from app.api import domain as domain_api
from app.api import equipment as equipment_api
from app.api import exercise as exercise_api
from app.api import finance as finance_api
from app.api import fitness as fitness_api
from app.api import food as food_api
from app.api import garden as garden_api
from app.api import highlight_review as highlight_review_api
from app.api import identity as identity_api
from app.api import imputation as imputation_api
from app.api import journal as journal_api
from app.api import learning as learning_api
from app.api import life as life_api
from app.api import meditation as meditation_api
from app.api import mental as mental_api
from app.api import migraine as migraine_api
from app.api import next_action as next_action_api
from app.api import perf as perf_api
from app.api import profile as profile_api
from app.api import push as push_api
from app.api import schedule as schedule_api
from app.api import screentime as screentime_api
from app.api import sleep_drivers as sleep_drivers_api
from app.api import sleep_efficiency as sleep_efficiency_api
from app.api import sleep_intervention as sleep_intervention_api
from app.api import sleep_plan_override as sleep_plan_override_api
from app.api import sleep_quality as sleep_quality_api
from app.api import speech as speech_api
from app.api import tide as tide_api
from app.api import timeline as timeline_api
from app.api import weather as weather_api
from app.api import wind_down as wind_down_api
from app.api import workout_review as workout_review_api
from app.config import get_settings
from app.db import create_all, init_engine
from app.logging import configure_logging, get_logger
from app.scheduler import setup_scheduler, shutdown_scheduler

logger = get_logger(__name__)


async def _warm_analysis_cache() -> None:
    """n-of-1 分析 (置換検定) をバックグラウンドで先に計算しておく。

    ``migraine_stats.permutation_test`` は純粋・決定的なのでメモ化してあるが、
    キャッシュはプロセス内にしか無く**デプロイで再起動するたび空になる**。
    その状態で最初に ``/api/next-action`` を叩いた人が 3.3s 待たされる
    (実測: 56 検定 × 5000 反復)。起動直後に一度走らせておけば、利用者が
    最初に開いた時点でキャッシュが埋まっている。

    ⚠️ ここは**あくまで先読み**。失敗しても本体は各リクエストで計算できるので、
    例外は握りつぶしてログだけ残す (起動を壊さないことを最優先)。
    """
    import anyio

    def _run() -> None:
        from app.scoring import sleep_drivers
        from app.scoring.timewindow import app_today

        today = app_today()
        sleep_drivers.analyze(today)

    try:
        await anyio.to_thread.run_sync(_run)
        logger.info("analysis_cache_warmed")
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # 先読みの失敗で起動を壊さない
        logger.warning("analysis_cache_warm_failed", error=str(exc))


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.app_log_level)
    init_engine(settings.resolved_db_path())
    create_all()
    if settings.scheduler_enabled:
        setup_scheduler()
    logger.info("startup_complete", db=str(settings.resolved_db_path()))
    warm_task = asyncio.create_task(_warm_analysis_cache()) if settings.scheduler_enabled else None
    yield
    if warm_task is not None:
        warm_task.cancel()
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

    # 常駐パフォーマンス監視: 全リクエストの応答時間を計測・記録。
    from app.perf import perf_middleware

    app.middleware("http")(perf_middleware)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(health_export.router)
    app.include_router(airgap_api.router)
    app.include_router(airgap_insight_api.router)
    app.include_router(dashboard.router)
    app.include_router(life_api.router)
    app.include_router(domain_api.router)
    app.include_router(learning_api.router)
    app.include_router(speech_api.router)
    app.include_router(admin_api.router)
    app.include_router(caffeine_api.router)
    app.include_router(tide_api.router)
    app.include_router(bodyload_api.router)
    app.include_router(sleep_drivers_api.router)
    app.include_router(sleep_efficiency_api.router)
    app.include_router(sleep_intervention_api.router)
    app.include_router(sleep_quality_api.router)
    app.include_router(next_action_api.router)
    app.include_router(equipment_api.router)
    app.include_router(schedule_api.router)
    app.include_router(screentime_api.router)
    app.include_router(highlight_review_api.router)
    app.include_router(workout_review_api.router)
    app.include_router(imputation_api.router)
    app.include_router(checkin_api.router)
    app.include_router(mental_api.router)
    app.include_router(advice_feedback_api.router)
    app.include_router(migraine_api.router)
    app.include_router(profile_api.router)
    app.include_router(push_api.router)
    app.include_router(food_api.router)
    app.include_router(fitness_api.router)
    app.include_router(garden_api.router)
    app.include_router(becoming_api.router)
    app.include_router(checkup_api.router)
    app.include_router(journal_api.router)
    app.include_router(body_distribution_api.router)
    app.include_router(body_comp_api.router)
    app.include_router(body_measurement_api.router)
    app.include_router(atlas_api.router)
    app.include_router(exercise_api.router)
    app.include_router(consult_api.router)
    app.include_router(finance_api.router)
    app.include_router(corporate_finance_api.router)
    app.include_router(perf_api.router)
    app.include_router(activity_api.router)
    app.include_router(alcohol_api.router)
    app.include_router(timeline_api.router)
    app.include_router(weather_api.router)
    app.include_router(identity_api.router)
    app.include_router(wind_down_api.router)
    app.include_router(meditation_api.router)
    app.include_router(appointment_plan_api.router)
    app.include_router(sleep_plan_override_api.router)
    app.include_router(debug.router)
    return app


app = create_app()
