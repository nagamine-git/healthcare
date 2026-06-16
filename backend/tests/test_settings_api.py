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


def test_get_settings_returns_defaults(app_client):
    body = app_client.get("/api/settings").json()
    assert body["source"] == "default"
    # 派生値が入っている
    assert body["caffeine_half_life_h"] == pytest.approx(5.0)
    assert body["caffeine_target_mg_per_kg"] == 1.0
    assert body["max_hr"] == 187  # 208 - 0.7*30 (既定 age=30)
    # 全フィールドが未設定 = 自動 (overrides は全 None)
    assert all(v is None for v in body["overrides"].values())


def test_overrides_reflect_set_then_clear(app_client):
    app_client.put("/api/settings", json={"age": 40})
    body = app_client.get("/api/settings").json()
    assert body["overrides"]["age"] == 40  # 明示設定
    assert body["age"] == 40
    # クリア (null) で自動に戻る
    app_client.put("/api/settings", json={"age": None})
    body2 = app_client.get("/api/settings").json()
    assert body2["overrides"]["age"] is None
    assert body2["age"] == 30  # config デフォルト


def test_put_smoker_shortens_half_life(app_client):
    resp = app_client.put("/api/settings", json={"caffeine_smoker": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "db"
    assert body["caffeine_smoker"] is True
    assert body["caffeine_half_life_h"] == pytest.approx(3.0, abs=0.01)


def test_put_sensitivity_changes_target(app_client):
    body = app_client.put("/api/settings", json={"caffeine_sensitivity": "high"}).json()
    assert body["caffeine_sensitivity"] == "high"
    assert body["caffeine_target_mg_per_kg"] == 0.5


def test_put_is_partial_and_does_not_clobber(app_client):
    app_client.put("/api/settings", json={"caffeine_smoker": True})
    app_client.put("/api/settings", json={"sleep_need_min": 450})
    body = app_client.get("/api/settings").json()
    # 後の更新で smoker が消えない
    assert body["caffeine_smoker"] is True
    assert body["sleep_need_min"] == 450


def test_put_max_hr_override_then_clear(app_client):
    b1 = app_client.put("/api/settings", json={"max_hr": 195}).json()
    assert b1["max_hr"] == 195
    # null 明示で式に戻る
    b2 = app_client.put("/api/settings", json={"max_hr": None}).json()
    assert b2["max_hr"] == 187


def test_put_validation_rejects_out_of_range(app_client):
    assert app_client.put("/api/settings", json={"age": 5}).status_code == 422
    assert app_client.put("/api/settings", json={"caffeine_half_life_override_h": 99}).status_code == 422
    assert app_client.put("/api/settings", json={"wake_time": "99:99"}).status_code == 422
    assert app_client.put("/api/settings", json={"chronotype": "lizard"}).status_code == 422


def test_half_life_override_takes_precedence(app_client):
    body = app_client.put(
        "/api/settings", json={"caffeine_smoker": True, "caffeine_half_life_override_h": 6.5}
    ).json()
    # override があれば喫煙係数を無視
    assert body["caffeine_half_life_h"] == pytest.approx(6.5)
