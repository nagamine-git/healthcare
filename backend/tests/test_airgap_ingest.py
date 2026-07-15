from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_client(temp_data_dir, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(temp_data_dir))
    monkeypatch.setenv("HAE_INGEST_TOKEN", "test-token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

    from app import main as main_module
    from app.api import airgap as airgap_module
    from app.config import Settings, reset_settings_cache

    reset_settings_cache()
    settings = Settings(scheduler_enabled=False, app_data_dir=temp_data_dir,
                        hae_ingest_token="test-token")
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    monkeypatch.setattr(airgap_module, "get_settings", lambda: settings)

    app = main_module.create_app()
    with TestClient(app) as client:
        yield client


PAYLOAD = {
    "date": "2026-07-15", "score": 72, "completed_min": 45, "failures": 1,
    "goal_min": 60, "waste_min": None, "waste_limit_min": 60, "sessions": 2,
    "source": "airgap",
}


def test_rejects_without_token(app_client):
    assert app_client.post("/ingest/airgap", json=PAYLOAD).status_code == 401


def test_rejects_bad_token(app_client):
    r = app_client.post("/ingest/airgap", json=PAYLOAD,
                        headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_ingest_and_upsert(app_client):
    h = {"Authorization": "Bearer test-token"}
    r = app_client.post("/ingest/airgap", json=PAYLOAD, headers=h)
    assert r.status_code == 202
    assert r.json()["score"] == 72
    # 同日 upsert (スコア更新)
    r2 = app_client.post("/ingest/airgap", json={**PAYLOAD, "score": 88, "waste_min": 20},
                         headers=h)
    assert r2.status_code == 202

    from datetime import date

    from app.db import session_scope
    from app.models import AirgapDaily
    with session_scope() as s:
        row = s.get(AirgapDaily, date(2026, 7, 15))
        assert row is not None
        assert row.score == 88
        assert row.waste_min == 20


def test_airgap_feeds_atlas_and_life_tree(app_client):
    # 今日の日付で push → 全体マップの leaf と 精神状態「デジタル節制」に載る
    from app.scoring.timewindow import app_today

    today = app_today().isoformat()
    h = {"Authorization": "Bearer test-token"}
    r = app_client.post("/ingest/airgap", json={**PAYLOAD, "date": today, "score": 77},
                        headers=h)
    assert r.status_code == 202

    atlas = app_client.get("/api/atlas").json()["tree"]

    def find(node, key):
        if node["key"] == key:
            return node
        for c in node.get("children", []):
            if (hit := find(c, key)) is not None:
                return hit
        return None

    leaf = find(atlas, "airgap")
    assert leaf is not None
    assert leaf["current"] == 77
    assert leaf["score"] == 77

    life = app_client.get("/api/life/tree").json()
    mind = next(c for c in life["capitals"] if c["key"] == "mind")
    digital = next(x for x in mind["leaves"] if "デジタル節制" in x["label"])
    assert digital["achievement"] == 77
