from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

TIDE_TOKEN = "test-tide-token"


@pytest.fixture
def app_client(temp_data_dir, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(temp_data_dir))
    monkeypatch.setenv("HAE_INGEST_TOKEN", "test")
    monkeypatch.setenv("TIDE_INGEST_TOKEN", TIDE_TOKEN)

    from app import main as main_module
    from app.config import Settings, reset_settings_cache

    reset_settings_cache()
    settings = Settings(
        scheduler_enabled=False,
        app_data_dir=temp_data_dir,
        tide_ingest_token=TIDE_TOKEN,
    )
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)

    app = main_module.create_app()
    with TestClient(app) as client:
        yield client


def _ingest(client: TestClient, entries: list[dict]) -> None:
    resp = client.post(
        "/api/tide/ingest",
        headers={"Authorization": f"Bearer {TIDE_TOKEN}"},
        json={"dev": "tide", "entries": entries},
    )
    assert resp.status_code == 200, resp.text


def test_health_export_returns_water_and_caffeine(app_client):
    now = int(datetime.now(UTC).timestamp())
    _ingest(
        app_client,
        [
            {"t": now, "k": 1, "ml": 500, "mg": 0},
            {"t": now, "k": 2, "ml": 0, "mg": 100},
        ],
    )

    resp = app_client.get("/api/tide/health-export")
    assert resp.status_code == 200
    body = resp.json()

    assert len(body["water"]) == 1
    assert body["water"][0]["ml"] == 500.0
    assert "id" in body["water"][0]
    assert "ts" in body["water"][0]

    assert len(body["caffeine"]) == 1
    assert body["caffeine"][0]["mg"] == 100.0
    assert "id" in body["caffeine"][0]
    assert "ts" in body["caffeine"][0]


def test_health_export_excludes_manual_caffeine(app_client):
    now = int(datetime.now(UTC).timestamp())
    _ingest(app_client, [{"t": now, "k": 2, "ml": 0, "mg": 100}])

    # 手動記録 (note != "TIDE") を追加
    manual_resp = app_client.post(
        "/api/caffeine", json={"source": "canned_coffee", "amount": 1.0}
    )
    assert manual_resp.status_code == 200

    resp = app_client.get("/api/tide/health-export")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["caffeine"]) == 1
    assert body["caffeine"][0]["mg"] == 100.0


def test_health_export_excludes_dietary_water(app_client):
    """dietary_water (Ascend → healthcare で書かれた値) を絶対に含めないこと。

    含めてしまうと Ascend が Apple Health に書き戻し、
    次の同期でまた読み込む無限ループ・二重計上になる。
    """
    now = int(datetime.now(UTC).timestamp())
    _ingest(app_client, [{"t": now, "k": 1, "ml": 500, "mg": 0}])

    from app.db import session_scope
    from app.models import MetricSample

    with session_scope() as session:
        session.add(
            MetricSample(
                source="hae",
                metric_key="dietary_water",
                ts=datetime.now(UTC).replace(tzinfo=None),
                value=750.0,
                unit="mL",
            )
        )

    resp = app_client.get("/api/tide/health-export")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["water"]) == 1
    assert body["water"][0]["ml"] == 500.0


def test_health_export_hours_filters_old_data(app_client):
    old_ts = int((datetime.now(UTC) - timedelta(hours=100)).timestamp())
    recent_ts = int(datetime.now(UTC).timestamp())
    _ingest(
        app_client,
        [
            {"t": old_ts, "k": 1, "ml": 300, "mg": 0},
            {"t": recent_ts, "k": 1, "ml": 500, "mg": 0},
        ],
    )

    resp = app_client.get("/api/tide/health-export?hours=72")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["water"]) == 1
    assert body["water"][0]["ml"] == 500.0

    resp_all = app_client.get("/api/tide/health-export?hours=200")
    assert resp_all.status_code == 200
    assert len(resp_all.json()["water"]) == 2


def test_health_export_no_auth_required(app_client):
    resp = app_client.get("/api/tide/health-export")
    assert resp.status_code == 200
