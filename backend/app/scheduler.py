"""APScheduler integration. The actual setup_scheduler() body is implemented later."""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import get_settings
from app.logging import get_logger

logger = get_logger(__name__)

_scheduler: AsyncIOScheduler | None = None


def _parse_cron(expr: str) -> CronTrigger:
    minute, hour, day, month, day_of_week = expr.split()
    return CronTrigger(
        minute=minute, hour=hour, day=day, month=month, day_of_week=day_of_week
    )


def setup_scheduler() -> AsyncIOScheduler:
    """Register all jobs and start the scheduler."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    settings = get_settings()
    scheduler = AsyncIOScheduler(timezone=settings.app_tz)

    # Lazy imports keep optional deps out of unit tests.
    from app.ingest.garmin_sync import sync_garmin_job
    from app.llm.client import morning_advice_job
    from app.scoring.recompute import recompute_today_job, refresh_baselines_job

    scheduler.add_job(
        sync_garmin_job,
        _parse_cron(settings.scheduler_garmin_cron),
        id="garmin_sync",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=600,
    )
    scheduler.add_job(
        recompute_today_job,
        _parse_cron(settings.scheduler_recompute_cron),
        id="recompute_today",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=600,
    )
    scheduler.add_job(
        morning_advice_job,
        _parse_cron(settings.scheduler_morning_advice_cron),
        id="morning_advice",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        refresh_baselines_job,
        _parse_cron(settings.scheduler_baseline_cron),
        id="baseline_refresh",
        coalesce=True,
        max_instances=1,
    )

    scheduler.start()
    _scheduler = scheduler
    logger.info("scheduler_started", jobs=[j.id for j in scheduler.get_jobs()])
    return scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def get_scheduler() -> AsyncIOScheduler | None:
    return _scheduler
