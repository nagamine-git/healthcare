from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

# ⚠️ 日付を固定で書かない。/api/body-measurement/history は「今日から N 日」で絞るため、
# 固定日付はその窓を外れた日に必ず落ちる時限爆弾になる (2026-08-19 に発火した)。
D0 = (date.today() - timedelta(days=2)).isoformat()
D_OLD = (date.today() - timedelta(days=60)).isoformat()
D_MID = (date.today() - timedelta(days=30)).isoformat()


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


def test_get_with_no_data_returns_nulls(app_client):
    r = app_client.get("/api/body-measurement")
    assert r.status_code == 200
    data = r.json()
    assert data["latest"] is None
    assert data["whtr"] is None
    assert data["navy_body_fat_pct"] is None


def test_put_upserts_by_date_and_evaluates(app_client):
    r = app_client.put(
        "/api/body-measurement",
        json={"date": D0, "waist_cm": 85.0, "neck_cm": 38.0},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["latest"]["waist_cm"] == 85.0
    # デフォルトプロファイル: 男性・身長170cm (config.py の既定値)
    assert data["whtr"] == 0.5
    assert data["whtr_status"] == "caution"  # 0.5 ちょうどは "未満" ではない
    assert data["navy_body_fat_pct"] is not None
    assert abs(data["navy_body_fat_pct"] - 17.9) < 0.2

    # 同一日付は upsert (重複させない)
    app_client.put("/api/body-measurement", json={"date": D0, "waist_cm": 84.0, "neck_cm": 38.0})
    hist = app_client.get("/api/body-measurement/history?days=30").json()["history"]
    assert len(hist) == 1
    assert hist[0]["waist_cm"] == 84.0


def test_put_rejects_all_empty(app_client):
    r = app_client.put("/api/body-measurement", json={"date": D0, "note": "起床後"})
    assert r.status_code == 422


def test_history_range(app_client):
    app_client.put("/api/body-measurement", json={"date": D_OLD, "waist_cm": 86.0})
    app_client.put("/api/body-measurement", json={"date": D_MID, "waist_cm": 85.0})
    hist = app_client.get("/api/body-measurement/history?days=400").json()["history"]
    assert [h["date"] for h in hist] == [D_OLD, D_MID]


def test_discrepancy_uses_bia_trend(app_client):
    from datetime import datetime

    from app.db import session_scope
    from app.models import WeightSample

    with session_scope() as s:
        s.add(WeightSample(ts=datetime(2026, 7, 19, 22, 0), weight_kg=70.0,
                            body_fat_pct=26.0, source="hae"))

    app_client.put("/api/body-measurement", json={"date": D0, "waist_cm": 85.0, "neck_cm": 38.0})
    data = app_client.get("/api/body-measurement").json()
    assert data["bia_body_fat_pct"] == 26.0
    assert data["discrepancy"]["status"] == "large"  # BIA 26% vs navy ~17.9%
