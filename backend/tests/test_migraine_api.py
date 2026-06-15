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


def test_start_creates_active_episode(app_client):
    resp = app_client.post("/api/migraine/start", json={"severity": 6})
    assert resp.status_code == 200
    body = resp.json()
    assert body["active"] is True
    assert body["severity"] == 6
    assert body["ended_at"] is None


def test_start_when_active_returns_409(app_client):
    app_client.post("/api/migraine/start", json={"severity": 5})
    resp = app_client.post("/api/migraine/start", json={"severity": 7})
    assert resp.status_code == 409


def test_stale_open_episode_does_not_block_start(app_client):
    """48h超で未終了の放置エピソードは active 扱いせず、新規開始を弾かない。"""
    from datetime import datetime, timedelta

    from sqlalchemy import select

    from app.db import session_scope
    from app.models import MigraineEpisode

    old = datetime.utcnow() - timedelta(days=200)  # 200日前・未終了の放置レコード
    with session_scope() as s:
        s.add(MigraineEpisode(started_at=old, ended_at=None, severity=3))

    resp = app_client.post("/api/migraine/start", json={"severity": 6})
    assert resp.status_code == 200  # 409 にならない

    with session_scope() as s:
        stale = s.execute(
            select(MigraineEpisode).where(MigraineEpisode.started_at == old)
        ).scalar_one()
        assert stale.ended_at is not None  # 放置レコードは finite 化


def test_end_closes_active_episode(app_client):
    app_client.post("/api/migraine/start", json={"severity": 5})
    resp = app_client.post("/api/migraine/end", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["active"] is False
    assert body["ended_at"] is not None
    assert body["duration_min"] is not None


def test_end_without_active_returns_404(app_client):
    resp = app_client.post("/api/migraine/end", json={})
    assert resp.status_code == 404


def test_list_returns_history_and_active(app_client):
    # 完了した過去エピソードを seed
    from app.db import session_scope
    from app.models import MigraineEpisode

    now = datetime.now(UTC).replace(tzinfo=None)
    with session_scope() as session:
        session.add(
            MigraineEpisode(
                started_at=now - timedelta(days=5, hours=2),
                ended_at=now - timedelta(days=5),
                severity=4,
            )
        )

    # 今 active を作る
    app_client.post("/api/migraine/start", json={"severity": 6})

    resp = app_client.get("/api/migraine?days=30")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count_30d"] == 1  # 完了は 1
    assert body["active"] is not None
    assert body["active"]["severity"] == 6
    assert len(body["items"]) == 2


def test_delete_removes_episode(app_client):
    add = app_client.post("/api/migraine/start", json={"severity": 5})
    eid = add.json()["id"]
    app_client.post("/api/migraine/end", json={})

    resp = app_client.delete(f"/api/migraine/{eid}")
    assert resp.status_code == 200
    list_resp = app_client.get("/api/migraine")
    assert list_resp.json()["items"] == []


def test_end_before_start_rejected(app_client):
    app_client.post("/api/migraine/start", json={"severity": 5})
    # 過去時刻で end を試みる
    past = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
    resp = app_client.post("/api/migraine/end", json={"ts_iso": past})
    assert resp.status_code == 400


def test_severity_out_of_range_rejected(app_client):
    resp = app_client.post("/api/migraine/start", json={"severity": 15})
    assert resp.status_code == 422  # pydantic validation


def test_patch_updates_started_at_severity_and_note(app_client):
    add = app_client.post("/api/migraine/start", json={"severity": 5})
    eid = add.json()["id"]
    app_client.post("/api/migraine/end", json={})

    new_start = "2026-05-20T10:00:00+09:00"
    resp = app_client.patch(
        f"/api/migraine/{eid}",
        json={"started_at_iso": new_start, "severity": 8, "note": "改訂"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["started_at_jst"] == "05/20 10:00"
    assert body["severity"] == 8
    assert body["note"] == "改訂"


def test_patch_clear_ended_at_reactivates(app_client):
    add = app_client.post("/api/migraine/start", json={"severity": 5})
    eid = add.json()["id"]
    app_client.post("/api/migraine/end", json={})

    resp = app_client.patch(
        f"/api/migraine/{eid}", json={"clear_ended_at": True}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["active"] is True
    assert body["ended_at"] is None


def test_patch_invalid_end_before_start_rejected(app_client):
    add = app_client.post("/api/migraine/start", json={"severity": 5})
    eid = add.json()["id"]
    app_client.post("/api/migraine/end", json={})

    past = "2020-01-01T00:00:00+09:00"
    resp = app_client.patch(f"/api/migraine/{eid}", json={"ended_at_iso": past})
    assert resp.status_code == 400


def test_patch_not_found(app_client):
    resp = app_client.patch("/api/migraine/99999", json={"severity": 5})
    assert resp.status_code == 404


def test_note_concatenation_on_end(app_client):
    app_client.post(
        "/api/migraine/start", json={"severity": 5, "note": "右側、ズキズキ"}
    )
    resp = app_client.post(
        "/api/migraine/end", json={"note": "ロキソニンで治った"}
    )
    note = resp.json()["note"]
    assert "右側" in note
    assert "ロキソニン" in note


def test_triggers_endpoint_accumulating(app_client):
    # エピソードを2件だけ作る → 判定保留
    app_client.post("/api/migraine/start", json={"severity": 5})
    app_client.post("/api/migraine/end", json={})
    resp = app_client.get("/api/migraine/triggers")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "accumulating"
    assert "onset_profile" in body
    assert body["episode_count"] >= 1
    assert "remaining" in body
