from __future__ import annotations

from datetime import UTC, datetime, timedelta

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


def test_presets_returns_all_sources(app_client):
    resp = app_client.get("/api/caffeine/presets")
    assert resp.status_code == 200
    body = resp.json()
    for k in (
        "instant_coffee",
        "canned_coffee",
        "nespresso",
        "ibuquick",
        "bufferin_premium",
        "manual",
    ):
        assert k in body
        assert "unit" in body[k]
        assert "mg_per_unit" in body[k]
    # 標準値の検算
    assert body["instant_coffee"]["mg_per_unit"] == 60.0  # config default
    assert body["canned_coffee"]["default_mg"] == 100.0
    assert body["nespresso"]["default_mg"] == 70.0
    # 添付文書ベース: 1錠40mg × 2錠 = 80mg
    assert body["ibuquick"]["default_mg"] == 80.0
    assert body["bufferin_premium"]["default_mg"] == 80.0


def test_add_canned_coffee_records_100mg(app_client):
    resp = app_client.post(
        "/api/caffeine", json={"source": "canned_coffee", "amount": 1.0}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["mg"] == 100.0
    assert body["unit"] == "本"


def test_add_ibuquick_records_80mg_per_2tab(app_client):
    resp = app_client.post(
        "/api/caffeine", json={"source": "ibuquick", "amount": 2.0}
    )
    assert resp.status_code == 200
    assert resp.json()["mg"] == 80.0


def test_add_bufferin_premium_records_80mg_per_2tab(app_client):
    resp = app_client.post(
        "/api/caffeine", json={"source": "bufferin_premium", "amount": 2.0}
    )
    assert resp.status_code == 200
    assert resp.json()["mg"] == 80.0


def test_add_manual_records_arbitrary_mg(app_client):
    resp = app_client.post(
        "/api/caffeine", json={"source": "manual", "amount": 42.5}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["mg"] == 42.5
    assert body["unit"] == "mg"


def test_add_instant_coffee_uses_config_per_g(app_client):
    # config の instant_coffee_mg_per_g = 60.0
    resp = app_client.post(
        "/api/caffeine", json={"source": "instant_coffee", "amount": 2.0}
    )
    assert resp.status_code == 200
    assert resp.json()["mg"] == 120.0


def test_list_returns_recent_items_sorted(app_client):
    for src in ("canned_coffee", "nespresso", "ibuquick"):
        app_client.post("/api/caffeine", json={"source": src, "amount": 1.0})

    resp = app_client.get("/api/caffeine?hours=24")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 3
    # total: 100 + 70 + 40 (1錠=40mg) = 210
    assert body["total_mg"] == pytest.approx(210.0)
    # 時刻昇順
    ts_list = [it["ts"] for it in body["items"]]
    assert ts_list == sorted(ts_list)


def test_delete_removes_record(app_client):
    add = app_client.post(
        "/api/caffeine", json={"source": "canned_coffee", "amount": 1.0}
    )
    intake_id = add.json()["id"]

    resp = app_client.delete(f"/api/caffeine/{intake_id}")
    assert resp.status_code == 200
    assert resp.json()["deleted"] == intake_id

    list_resp = app_client.get("/api/caffeine")
    assert list_resp.json()["items"] == []


def test_delete_not_found(app_client):
    resp = app_client.delete("/api/caffeine/99999")
    assert resp.status_code == 404


def test_patch_updates_amount_and_recomputes_mg(app_client):
    add = app_client.post(
        "/api/caffeine", json={"source": "ibuquick", "amount": 2.0}
    )
    iid = add.json()["id"]
    # 2 錠 (80mg) → 1 錠 (40mg)
    resp = app_client.patch(f"/api/caffeine/{iid}", json={"amount": 1.0})
    assert resp.status_code == 200
    body = resp.json()
    assert body["amount"] == 1.0
    assert body["mg"] == 40.0


def test_patch_changes_source_and_unit(app_client):
    add = app_client.post(
        "/api/caffeine", json={"source": "canned_coffee", "amount": 1.0}
    )
    iid = add.json()["id"]
    resp = app_client.patch(
        f"/api/caffeine/{iid}",
        json={"source": "bufferin_premium", "amount": 2.0},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "bufferin_premium"
    assert body["unit"] == "錠"
    assert body["mg"] == 80.0


def test_patch_updates_ts(app_client):
    add = app_client.post(
        "/api/caffeine", json={"source": "canned_coffee", "amount": 1.0}
    )
    iid = add.json()["id"]
    new_ts = "2026-05-20T08:00:00+09:00"
    resp = app_client.patch(f"/api/caffeine/{iid}", json={"ts_iso": new_ts})
    assert resp.status_code == 200
    # ts_jst は同日なら "08:00"、別日なら "05/20 08:00" になる
    assert "08:00" in resp.json()["ts_jst"]


def test_patch_not_found(app_client):
    resp = app_client.patch("/api/caffeine/99999", json={"amount": 1.0})
    assert resp.status_code == 404


def test_add_unknown_source_rejected(app_client):
    resp = app_client.post(
        "/api/caffeine", json={"source": "espresso_double_shot", "amount": 1.0}
    )
    assert resp.status_code in (400, 422)


def test_current_residual_decays_existing_intake(app_client):
    """6h 前に 200mg 飲んでいれば半減期 5h で残量 ≈ 87mg。"""
    from app.api.caffeine import current_residual_mg
    from app.db import session_scope
    from app.models import CaffeineIntake

    six_h_ago = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=6)
    with session_scope() as session:
        session.add(
            CaffeineIntake(
                ts=six_h_ago,
                source="manual",
                amount=200,
                unit="mg",
                mg=200,
            )
        )

    from zoneinfo import ZoneInfo

    now_jst = datetime.now(ZoneInfo("Asia/Tokyo"))
    residual = current_residual_mg(now_jst, half_life_h=5.0)
    # 200 * exp(-ln2 * 6/5) ≈ 87.06
    assert 80 < residual < 95


def test_today_api_includes_caffeine_with_residual_after_intake(app_client):
    # 摂取記録なし → existing_residual_mg=0 のはず
    from app.db import session_scope
    from app.models import WeightSample

    with session_scope() as session:
        session.add(
            WeightSample(
                ts=datetime.now(UTC).replace(tzinfo=None),
                weight_kg=56.0,
                source="hae",
            )
        )

    resp = app_client.get("/api/today")
    assert resp.status_code == 200
    caffeine = resp.json().get("caffeine")
    assert caffeine is not None
    assert caffeine["available"] is True
    assert caffeine["existing_residual_mg"] == 0

    # 缶コーヒー 1 本記録 → 体内残量に反映
    app_client.post("/api/caffeine", json={"source": "canned_coffee", "amount": 1.0})
    resp2 = app_client.get("/api/today")
    caffeine2 = resp2.json()["caffeine"]
    assert caffeine2["existing_residual_mg"] > 90  # 即時なら 100mg 近く残ってる
