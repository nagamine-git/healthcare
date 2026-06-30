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


def test_registry_records_slow_request_and_error():
    from app.perf import registry

    registry.endpoints.clear()
    registry.issues.clear()
    registry.record_request("GET /api/x", 1200, 200)  # 遅い
    registry.record_request("GET /api/y", 50, 500)    # エラー
    kinds = {i["kind"] for i in registry.issues}
    assert "slow_request" in kinds and "error" in kinds
    snap = registry.snapshot()
    assert any(e["label"] == "GET /api/x" for e in snap["endpoints"])


def test_record_query_normalizes_and_thresholds():
    from app.perf import registry

    registry.issues.clear()
    registry.record_query("SELECT * FROM t WHERE id = 42 AND x IN (1,2,3)", 5)  # 速い→無視
    registry.record_query("SELECT * FROM t WHERE id = 42 AND x IN (1,2,3)", 500)  # 遅い
    sq = [i for i in registry.issues if i["kind"] == "slow_query"]
    assert len(sq) == 1
    assert "?" in sq[0]["label"] and "42" not in sq[0]["label"]  # 数値が伏せられる


def test_perf_endpoint_flushes_and_returns(app_client):
    from app.perf import registry

    registry.record_request("GET /api/test", 999, 200)
    r = app_client.get("/api/admin/perf")
    assert r.status_code == 200
    body = r.json()
    assert "live" in body and "issues" in body
    # flush 後、slow_request が DB issue に出る
    assert any(i["kind"] == "slow_request" for i in body["issues"])
