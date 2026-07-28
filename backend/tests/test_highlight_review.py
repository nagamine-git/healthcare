"""ハイライトイベント評価 API のテスト (LLM は monkeypatch)。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


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


def _mock_llm(monkeypatch, calls):
    async def fake(*, target, label, time_jst, sub):
        calls["n"] += 1
        return {"text": f"{label}: 睡眠5.8hは筋合成にやや不足。7hを狙って。", "tone": "caution", "model": "test"}

    import app.llm.highlight_review as hr

    monkeypatch.setattr(hr, "generate_review", fake)


def test_create_persist_idempotent_and_list(app_client, monkeypatch):
    calls = {"n": 0}
    _mock_llm(monkeypatch, calls)
    # 一覧 API は既定で直近3日 (app_today-3) に絞るため、日付は「今日」基準の相対で作る。
    # 固定日付だと実時刻が進むと窓から外れてテストが時限で壊れる。
    from app.scoring.timewindow import app_today

    day = app_today().isoformat()
    body = {"date": day, "event_key": "01:32|就寝", "label": "就寝", "time_jst": "01:32"}

    r1 = app_client.post("/api/highlight-reviews", json=body)
    assert r1.status_code == 200 and r1.json()["tone"] == "caution" and calls["n"] == 1

    r2 = app_client.post("/api/highlight-reviews", json=body)  # 冪等
    assert r2.status_code == 200 and calls["n"] == 1

    r3 = app_client.post("/api/highlight-reviews", json={**body, "force": True})
    assert r3.status_code == 200 and calls["n"] == 2

    lst = app_client.get("/api/highlight-reviews").json()["items"]
    assert any(i["event_key"] == "01:32|就寝" and i["date"] == day for i in lst)


def test_same_key_different_date_is_separate(app_client, monkeypatch):
    calls = {"n": 0}
    _mock_llm(monkeypatch, calls)
    a = {"date": "2026-07-04", "event_key": "20:59|ランニング", "label": "ランニング"}
    b = {"date": "2026-07-05", "event_key": "20:59|ランニング", "label": "ランニング"}
    assert app_client.post("/api/highlight-reviews", json=a).status_code == 200
    assert app_client.post("/api/highlight-reviews", json=b).status_code == 200
    assert calls["n"] == 2


def test_invalid_date_400(app_client):
    r = app_client.post("/api/highlight-reviews", json={"date": "not-a-date", "event_key": "x", "label": "x"})
    assert r.status_code == 400


def test_force_regeneration_is_rate_limited(app_client, monkeypatch):
    """再分析 (force) には日次上限がかかる。初回生成は上限を消費しない。

    force は必ず LLM を1回叩くので、UI のボタンから無制限に叩けると費用が青天井になる。
    アドバイス再生成と同じ上限値 (llm_max_regenerations_per_day) を機能別枠で使う。
    """
    calls = {"n": 0}
    _mock_llm(monkeypatch, calls)
    from app.config import get_settings
    from app.scoring.timewindow import app_today

    limit = get_settings().llm_max_regenerations_per_day
    day = app_today().isoformat()
    body = {"date": day, "event_key": "07:00|筋トレ", "label": "筋トレ", "time_jst": "07:00"}

    # 初回生成 (上限は消費しない)
    assert app_client.post("/api/highlight-reviews", json=body).status_code == 200
    assert calls["n"] == 1

    # 上限まで再分析できる
    for _ in range(limit):
        assert app_client.post("/api/highlight-reviews", json={**body, "force": True}).status_code == 200
    assert calls["n"] == 1 + limit

    # 超過すると 429 で、LLM は叩かれない
    over = app_client.post("/api/highlight-reviews", json={**body, "force": True})
    assert over.status_code == 429
    assert calls["n"] == 1 + limit

    # 上限に達しても、保存済みの取得 (force なし) は従来どおり通る
    assert app_client.post("/api/highlight-reviews", json=body).status_code == 200
