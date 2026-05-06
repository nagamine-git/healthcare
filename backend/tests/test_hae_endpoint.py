from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select


@pytest.fixture
def app_client(temp_data_dir, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(temp_data_dir))
    monkeypatch.setenv("HAE_INGEST_TOKEN", "test-hae-token")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

    # Reset cached settings so env changes take effect.
    from app.config import reset_settings_cache

    reset_settings_cache()

    # Disable scheduler in tests.
    os.environ["SCHEDULER_ENABLED"] = "false"

    # We can't easily re-trigger lifespan; build app with scheduler disabled by patching settings.
    from app import main as main_module
    from app.config import Settings

    settings = Settings(scheduler_enabled=False, app_data_dir=temp_data_dir)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    # Also patch in modules that imported get_settings directly.
    from app.api import health_export as he

    monkeypatch.setattr(he, "get_settings", lambda: settings)

    app = main_module.create_app()
    with TestClient(app) as client:
        yield client


def test_healthz_returns_ok(app_client):
    resp = app_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ingest_requires_bearer(app_client):
    resp = app_client.post("/ingest/health-auto-export", json={"data": {}})
    assert resp.status_code == 401


def test_ingest_rejects_wrong_token(app_client):
    resp = app_client.post(
        "/ingest/health-auto-export",
        json={"data": {}},
        headers={"Authorization": "Bearer wrong"},
    )
    assert resp.status_code == 401


def test_ingest_accepts_valid_payload_and_persists(app_client):
    payload = {
        "data": {
            "metrics": [
                {
                    "name": "step_count",
                    "units": "count",
                    "data": [{"qty": 1234, "date": "2026-05-01 10:00:00 +0900"}],
                },
                {
                    "name": "weight_body_mass",
                    "units": "kg",
                    "data": [{"qty": 70.0, "date": "2026-05-01 06:30:00 +0900"}],
                },
            ]
        }
    }
    resp = app_client.post(
        "/ingest/health-auto-export",
        json=payload,
        headers={"Authorization": "Bearer test-hae-token"},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "ok"
    assert body["counts"]["samples"] == 1
    assert body["counts"]["weights"] == 1

    # Verify persistence
    from app.db import session_scope
    from app.models import MetricSample, WeightSample

    with session_scope() as session:
        samples = session.execute(select(MetricSample)).scalars().all()
        weights = session.execute(select(WeightSample)).scalars().all()
        assert len(samples) == 1
        assert samples[0].metric_key == "step_count"
        assert len(weights) == 1
        assert abs(weights[0].weight_kg - 70.0) < 0.01


def test_ingest_is_idempotent(app_client):
    payload = {
        "data": {
            "metrics": [
                {
                    "name": "step_count",
                    "units": "count",
                    "data": [{"qty": 1234, "date": "2026-05-01 10:00:00 +0900"}],
                }
            ]
        }
    }
    headers = {"Authorization": "Bearer test-hae-token"}
    app_client.post("/ingest/health-auto-export", json=payload, headers=headers)
    app_client.post("/ingest/health-auto-export", json=payload, headers=headers)

    from app.db import session_scope
    from app.models import MetricSample

    with session_scope() as session:
        rows = session.execute(select(MetricSample)).scalars().all()
        assert len(rows) == 1  # upsert dedup


def test_today_endpoint_handles_empty_db(app_client):
    resp = app_client.get("/api/today")
    assert resp.status_code == 200
    body = resp.json()
    assert "date" in body
    assert body["score"] is None
    assert body["advice"] is None


def test_ingest_handles_large_payload(app_client):
    """SQLite のパラメータ上限 (32766) を超える行数でも動くこと。"""
    metrics = [
        {
            "name": "step_count",
            "units": "count",
            "data": [
                {"qty": i, "date": f"2026-05-01 {(i % 24):02d}:{(i % 60):02d}:00 +0900"}
                for i in range(1, 6001)
            ],
        }
    ]
    resp = app_client.post(
        "/ingest/health-auto-export",
        json={"data": {"metrics": metrics}},
        headers={"Authorization": "Bearer test-hae-token"},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["counts"]["samples"] > 0
