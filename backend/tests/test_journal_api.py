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


def test_entry_upsert_and_list_and_delete(app_client):
    r = app_client.put("/api/journal/entry", json={"date": "2026-06-27", "text": "テスト日記"})
    assert r.status_code == 200
    assert r.json()["entries"][0]["text"] == "テスト日記"
    # 同一日付は upsert
    app_client.put("/api/journal/entry", json={"date": "2026-06-27", "text": "更新"})
    entries = app_client.get("/api/journal/entries").json()["entries"]
    assert len(entries) == 1 and entries[0]["text"] == "更新"
    # 削除
    d = app_client.delete("/api/journal/entry/2026-06-27")
    assert d.status_code == 200
    assert d.json()["entries"] == []


def test_entry_save_marks_journaling_in_garden_and_delete_removes_it(app_client):
    # 控え(JournalEntry)= その日のジャーナリング実施。庭の contributions に反映される。
    from datetime import date

    from app.db import session_scope
    from app.models.health import GardenDaily
    from app.scoring.garden.recompute import recompute_garden_for_date

    d = "2026-06-27"
    r1 = app_client.put("/api/journal/entry", json={"date": d, "text": "今日の控え"})
    assert r1.json()["journaling_logged"] is True  # 新規作成
    r2 = app_client.put("/api/journal/entry", json={"date": d, "text": "編集後"})
    assert r2.json()["journaling_logged"] is False  # 既存編集

    with session_scope() as session:
        row = session.get(GardenDaily, date.fromisoformat(d))
        assert row is not None and "journaling" in (row.contributions or {})

    # 控えを消すと journaling も外れる(控えが source of truth)。
    app_client.delete(f"/api/journal/entry/{d}")
    with session_scope() as session:
        recompute_garden_for_date(session, date.fromisoformat(d))
        row = session.get(GardenDaily, date.fromisoformat(d))
        assert "journaling" not in (row.contributions or {})


def test_extract_proposes_and_marks_already_logged(app_client, monkeypatch):
    import app.api.journal as japi

    async def fake_extract(text, catalog):
        # catalog 内の kind のみ返る前提
        return [
            {"kind": "reading", "evidence": "14時 読書", "confidence": "high"},
            {"kind": "journaling", "evidence": "今日の控え", "confidence": "high"},
        ]

    monkeypatch.setattr(japi, "extract_actions", fake_extract)
    # 先に控えを保存 → journaling は既に記録済みになる
    app_client.put("/api/journal/entry", json={"date": "2026-06-27", "text": "x"})
    r = app_client.post("/api/journal/extract", json={"date": "2026-06-27", "text": "14時 読書"})
    props = {p["kind"]: p for p in r.json()["proposals"]}
    assert props["reading"]["already_logged"] is False
    assert props["journaling"]["already_logged"] is True  # 控え保存で記録済み


def test_extract_commit_is_idempotent_and_skips_existing(app_client):
    # reading をコミット → 記録される
    r1 = app_client.post(
        "/api/journal/extract/commit", json={"date": "2026-06-27", "kinds": ["reading"]}
    )
    assert r1.json()["logged"] == ["reading"]
    # 再コミットしても二重計上しない
    r2 = app_client.post(
        "/api/journal/extract/commit", json={"date": "2026-06-27", "kinds": ["reading"]}
    )
    assert r2.json()["logged"] == []

    from app.db import session_scope
    from app.models.health import GoodActionLog

    with session_scope() as session:
        rows = session.query(GoodActionLog).filter_by(kind="reading").all()
        assert len(rows) == 1 and rows[0].source == "journal"


def test_transcribe_uses_llm(app_client, monkeypatch):
    import app.api.journal as japi

    async def fake(**kwargs):
        return "# 起こした本文\n- 感謝: [?]"

    monkeypatch.setattr(japi, "transcribe_journal", fake)
    r = app_client.post("/api/journal/transcribe", json={"image_base64": "x"})
    assert r.status_code == 200
    assert "起こした本文" in r.json()["text"]
