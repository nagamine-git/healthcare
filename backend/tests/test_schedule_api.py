from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_client(temp_data_dir, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(temp_data_dir))
    monkeypatch.setenv("HAE_INGEST_TOKEN", "test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

    from app import main as main_module
    from app.config import Settings, reset_settings_cache

    reset_settings_cache()
    settings = Settings(scheduler_enabled=False, app_data_dir=temp_data_dir)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)

    app = main_module.create_app()
    with TestClient(app) as client:
        yield client


def test_schedule_today_unconfigured_is_safe(app_client):
    # 認証情報が無い環境では configured=false・events=[] を副作用なく返す。
    r = app_client.get("/api/schedule/today")
    assert r.status_code == 200
    d = r.json()
    assert d["configured"] is False
    assert d["events"] == []
    assert "date" in d and "now" in d


def test_schedule_today_maps_events(app_client, monkeypatch):
    # gcal 連携済みを装い、list_events_for_date をスタブして整形を検証。
    from app.integrations import gcal

    monkeypatch.setattr(gcal, "load_credentials", lambda: object())
    monkeypatch.setattr(
        gcal, "list_events_for_date",
        lambda *a, **k: [
            {"id": "e1", "summary": "定例MTG", "start": "2020-01-01T09:00:00+09:00",
             "end": "2020-01-01T10:00:00+09:00", "is_busy": True, "is_hc_managed": False},
        ],
    )
    r = app_client.get("/api/schedule/today")
    d = r.json()
    assert d["configured"] is True
    assert len(d["events"]) == 1
    ev = d["events"][0]
    assert ev["title"] == "定例MTG"
    assert ev["past"] is True  # 2020年 → 現在より過去
    assert ev["is_hc_managed"] is False
