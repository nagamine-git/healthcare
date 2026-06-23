from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_client(temp_data_dir, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(temp_data_dir))
    monkeypatch.setenv("HAE_INGEST_TOKEN", "test")
    from app import main as main_module
    from app.config import Settings, reset_settings_cache

    reset_settings_cache()
    settings = Settings(scheduler_enabled=False, app_data_dir=temp_data_dir)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    app = main_module.create_app()
    with TestClient(app) as client:
        yield client


def test_tests_overview_first_run(app_client):
    r = app_client.get("/api/fitness/tests")
    assert r.status_code == 200
    data = r.json()
    assert data["any_due"] is True
    keys = {t["definition"]["key"] for t in data["tests"]}
    assert keys == {"push_up", "grip", "chair_stand", "srt"}


def test_record_and_reflect(app_client):
    r = app_client.post("/api/fitness/results", json={"test_key": "push_up", "value": 42})
    assert r.status_code == 200
    assert r.json()["value"] == 42

    ov = app_client.get("/api/fitness/tests").json()
    pu = next(t for t in ov["tests"] if t["definition"]["key"] == "push_up")
    assert pu["latest"]["value"] == 42
    assert pu["due"]["is_due"] is False  # 直後なので next 推奨はまだ


def test_history_includes_id_and_delete(app_client):
    app_client.post(
        "/api/fitness/results",
        json={"test_key": "push_up", "value": 30, "performed_on": "2026-06-01"},
    )
    app_client.post(
        "/api/fitness/results",
        json={"test_key": "push_up", "value": 35, "performed_on": "2026-06-08"},
    )
    hist = app_client.get("/api/fitness/history/push_up").json()
    assert len(hist["items"]) == 2
    assert all("id" in it for it in hist["items"])
    target = hist["items"][0]["id"]

    r = app_client.delete(f"/api/fitness/results/{target}")
    assert r.status_code == 200
    hist2 = app_client.get("/api/fitness/history/push_up").json()
    assert len(hist2["items"]) == 1
    assert target not in {it["id"] for it in hist2["items"]}


def test_measure_mode_exposed(app_client):
    data = app_client.get("/api/fitness/tests").json()
    modes = {t["definition"]["key"]: t["definition"]["measure_mode"] for t in data["tests"]}
    assert modes["push_up"] == "metronome_tap"
    assert modes["chair_stand"] == "timer_clap"
    assert modes["grip"] is None
    assert modes["srt"] is None


def test_record_grip_left_right_best(app_client):
    r = app_client.post(
        "/api/fitness/results", json={"test_key": "grip", "left": 44, "right": 47}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["value"] == 47  # ベスト採用
    assert body["detail"] == {"left": 44, "right": 47}


def test_record_upsert_same_day(app_client):
    app_client.post(
        "/api/fitness/results",
        json={"test_key": "push_up", "value": 40, "performed_on": "2026-06-22"},
    )
    app_client.post(
        "/api/fitness/results",
        json={"test_key": "push_up", "value": 43, "performed_on": "2026-06-22"},
    )
    hist = app_client.get("/api/fitness/history/push_up").json()
    # 同日は UPSERT で 1 件のまま、値は上書き
    same_day = [i for i in hist["items"] if i["performed_on"] == "2026-06-22"]
    assert len(same_day) == 1
    assert same_day[0]["value"] == 43


def test_unknown_test_key_rejected(app_client):
    r = app_client.post("/api/fitness/results", json={"test_key": "bogus", "value": 1})
    assert r.status_code == 400


def test_missing_value_rejected(app_client):
    r = app_client.post("/api/fitness/results", json={"test_key": "push_up"})
    assert r.status_code == 400
