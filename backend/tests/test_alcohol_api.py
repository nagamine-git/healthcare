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


def test_presets_include_all_sources(app_client):
    resp = app_client.get("/api/alcohol/presets")
    assert resp.status_code == 200
    body = resp.json()
    for k in (
        "beer_glass",
        "beer_can_500",
        "wine_glass",
        "sake_go",
        "shochu_mizuwari",
        "highball",
        "strong_chuhai",
        "manual",
    ):
        assert k in body


def test_add_beer_glass_records_14g(app_client):
    resp = app_client.post(
        "/api/alcohol", json={"source": "beer_glass", "amount": 1.0}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["grams"] == 14.0


def test_add_strong_chuhai_records_25g(app_client):
    resp = app_client.post(
        "/api/alcohol", json={"source": "strong_chuhai", "amount": 1.0}
    )
    assert resp.status_code == 200
    assert resp.json()["grams"] == 25.0


def test_add_with_override_ml_abv(app_client):
    # 500ml × 7% × 0.8 = 28g
    resp = app_client.post(
        "/api/alcohol",
        json={
            "source": "beer_can_500",
            "amount": 1.0,
            "override_ml": 500,
            "override_abv_pct": 7.0,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["grams"] == pytest.approx(28.0, abs=0.1)
    assert body["abv_pct"] == 7.0


def test_add_manual_records_arbitrary_grams(app_client):
    resp = app_client.post(
        "/api/alcohol", json={"source": "manual", "amount": 22.5}
    )
    assert resp.status_code == 200
    assert resp.json()["grams"] == 22.5


def test_list_aggregates_total_and_drinks(app_client):
    app_client.post("/api/alcohol", json={"source": "beer_can_500", "amount": 1.0})  # 20g
    app_client.post("/api/alcohol", json={"source": "wine_glass", "amount": 2.0})  # 32g
    resp = app_client.get("/api/alcohol")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_grams"] == pytest.approx(52.0)
    assert body["drinks_equivalent"] == 5.2


def test_delete_removes_record(app_client):
    add = app_client.post(
        "/api/alcohol", json={"source": "beer_glass", "amount": 1.0}
    )
    aid = add.json()["id"]
    resp = app_client.delete(f"/api/alcohol/{aid}")
    assert resp.status_code == 200
    assert app_client.get("/api/alcohol").json()["items"] == []


def test_unknown_source_rejected(app_client):
    resp = app_client.post(
        "/api/alcohol", json={"source": "tequila_shot", "amount": 1.0}
    )
    assert resp.status_code in (400, 422)
