"""スマホ依存: summarize 純関数 + import/GET API (OCR は monkeypatch)。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.scoring.screentime import summarize


@pytest.fixture
def app_client(temp_data_dir, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(temp_data_dir))
    from app import main as main_module
    from app.config import Settings, reset_settings_cache

    reset_settings_cache()
    settings = Settings(scheduler_enabled=False, app_data_dir=temp_data_dir)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    app = main_module.create_app()
    with TestClient(app) as client:
        yield client


def test_summarize_avg_and_entertainment_and_target():
    days = [
        {"period_start": "2026-07-04", "daily_min": 504,
         "categories": {"Entertainment": 185, "Productivity & Finance": 148, "Other": 50}, "top_apps": [{"name": "YouTube", "minutes": 184}]},
        {"period_start": "2026-07-03", "daily_min": 200, "categories": {}, "top_apps": []},
    ]
    week = {"period_start": "2026-06-28", "daily_min": 457, "top_apps": [{"name": "Safari", "minutes": 707}]}
    s = summarize(days, week)
    assert s["status"] == "ok"
    assert s["latest_daily_min"] == 504
    assert s["avg7_min"] == 352  # (504+200)/2
    assert s["over_target"] is True  # 504 > 180
    assert s["entertainment_share_pct"] == 48  # 185 / 383 = 48.3
    assert s["trend"] == "up"  # 504 vs 週日平均457
    assert s["top_apps"][0]["name"] == "YouTube"


def test_summarize_no_data():
    assert summarize([], None)["status"] == "no_data"


def test_import_upserts_day_and_week(app_client, monkeypatch):
    outs = iter([
        {"period_type": "day", "period_start": "2026-07-04", "daily_min": 504,
         "categories": [{"name": "Entertainment", "minutes": 185}],
         "top_apps": [{"name": "YouTube", "minutes": 184}]},
        {"period_type": "week", "period_start": "2026-06-28", "daily_min": 457, "total_min": 3200,
         "categories": [], "top_apps": [{"name": "Safari", "minutes": 707}]},
    ])

    async def fake_extract(*, image_b64, media_type="image/png", today=None):
        return next(outs)

    import app.llm.screentime_ocr as ocr

    monkeypatch.setattr(ocr, "extract_screentime", fake_extract)

    r = app_client.post("/api/screentime/import", json={"images": [
        {"image_base64": "x"}, {"image_base64": "y"},
    ]})
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["latest_daily_min"] == 504
    assert body["week"]["daily_min"] == 457
    assert len(body["days"]) == 1


def test_import_empty_422(app_client):
    r = app_client.post("/api/screentime/import", json={})
    assert r.status_code == 422
