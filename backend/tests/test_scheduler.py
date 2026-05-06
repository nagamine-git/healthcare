from __future__ import annotations

import asyncio

import pytest

from app.scheduler import _parse_cron, setup_scheduler, shutdown_scheduler


def test_parse_cron_returns_trigger():
    trigger = _parse_cron("5 * * * *")
    # Just verify the trigger has at least one field set to 5
    fields = {f.name: str(f) for f in trigger.fields}
    assert fields["minute"] == "5"
    assert fields["hour"] == "*"


@pytest.mark.asyncio
async def test_setup_and_shutdown_scheduler(temp_data_dir, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(temp_data_dir))
    from app.config import reset_settings_cache

    reset_settings_cache()

    scheduler = setup_scheduler()
    try:
        ids = {j.id for j in scheduler.get_jobs()}
        assert {
            "garmin_sync",
            "recompute_today",
            "morning_advice",
            "baseline_refresh",
        }.issubset(ids)
        assert scheduler.running
    finally:
        shutdown_scheduler()
        await asyncio.sleep(0)
