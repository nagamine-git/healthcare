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
    from app.ingest.freee_sync import freee_sync_job
    from app.ingest.garmin_sync import sync_garmin_job
    from app.ingest.github_sync import github_sync_job
    from app.llm.client import morning_advice_job
    from app.notifications.service import notification_tick_job
    from app.scoring.becoming.jobs import becoming_snapshot_job
    from app.scoring.garden.jobs import garden_recompute_job
    from app.scoring.identity.jobs import identity_monthly_job, identity_weekly_job
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
    scheduler.add_job(
        notification_tick_job,
        _parse_cron(settings.scheduler_notify_cron),
        id="notification_tick",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=120,
    )
    scheduler.add_job(
        identity_weekly_job,
        _parse_cron(settings.scheduler_identity_weekly_cron),
        id="identity_weekly",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        identity_monthly_job,
        _parse_cron(settings.scheduler_identity_monthly_cron),
        id="identity_monthly",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        github_sync_job,
        _parse_cron(settings.scheduler_github_sync_cron),
        id="github_sync",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=600,
    )
    scheduler.add_job(
        garden_recompute_job,
        _parse_cron(settings.scheduler_garden_recompute_cron),
        id="garden_recompute",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=600,
    )
    scheduler.add_job(
        becoming_snapshot_job,
        _parse_cron(settings.scheduler_becoming_snapshot_cron),
        id="becoming_snapshot",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=600,
    )
    from app.perf import perf_tick_job

    scheduler.add_job(
        perf_tick_job,
        _parse_cron(settings.scheduler_perf_tick_cron),
        id="perf_tick",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        freee_sync_job,
        _parse_cron(settings.scheduler_freee_sync_cron),
        id="freee_sync",
        coalesce=True,
        max_instances=1,
        misfire_grace_time=600,
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
