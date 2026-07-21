from __future__ import annotations

from unittest.mock import patch

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


def test_exercise_gif_404_when_unmapped(app_client):
    r = app_client.get("/api/exercise-gif", params={"name": "剣道素振り"})
    assert r.status_code == 404


def test_exercise_gif_uses_curated_id(app_client):
    with patch("app.integrations.exercisedb.fetch_gif_by_id", return_value=b"GIF89a") as mock_fetch:
        r = app_client.get("/api/exercise-gif", params={"name": "ダンベルベンチプレス"})
    assert r.status_code == 200
    assert r.content == b"GIF89a"
    mock_fetch.assert_called_once_with("0289")


def test_exercise_gif_id_param_bypasses_resolution(app_client):
    with patch("app.integrations.exercisedb.fetch_gif_by_id", return_value=b"GIF89a") as mock_fetch:
        r = app_client.get("/api/exercise-gif", params={"name": "ダンベルベンチプレス", "id": "9999"})
    assert r.status_code == 200
    mock_fetch.assert_called_once_with("9999")


def test_exercise_candidates_marks_curated_selection(app_client):
    pool = [
        {"id": "0289", "name": "dumbbell bench press", "equipment": "dumbbell", "target": "pectorals"},
        {"id": "0301", "name": "dumbbell decline bench press", "equipment": "dumbbell", "target": "pectorals"},
    ]
    with patch("app.integrations.exercisedb._fetch_equipment_pool", return_value=pool):
        r = app_client.get("/api/exercise-candidates", params={"name": "ダンベルベンチプレス"})
    assert r.status_code == 200
    data = r.json()
    assert data["selected"]["id"] == "0289"
    assert data["selected"]["source"] == "curated"
    selected_flags = {c["id"]: c["selected"] for c in data["candidates"]}
    assert selected_flags["0289"] is True
    assert selected_flags["0301"] is False


def test_save_and_use_override(app_client):
    r = app_client.post("/api/exercise-override", json={
        "name": "ヒップスラスト", "exercisedb_id": "1234", "exercisedb_name": "some other exercise",
    })
    assert r.status_code == 200

    with patch("app.integrations.exercisedb.fetch_gif_by_id", return_value=b"OVERRIDE") as mock_fetch:
        r = app_client.get("/api/exercise-gif", params={"name": "ヒップスラスト"})
    assert r.content == b"OVERRIDE"
    mock_fetch.assert_called_once_with("1234")  # curated (3562) より override が優先される

    pool: list[dict] = []
    with patch("app.integrations.exercisedb._fetch_equipment_pool", return_value=pool):
        cands = app_client.get("/api/exercise-candidates", params={"name": "ヒップスラスト"}).json()
    assert cands["selected"]["id"] == "1234"
    assert cands["selected"]["source"] == "override"


def test_delete_override_reverts_to_curated(app_client):
    app_client.post("/api/exercise-override", json={
        "name": "ヒップスラスト", "exercisedb_id": "1234", "exercisedb_name": "x",
    })
    r = app_client.delete("/api/exercise-override", params={"name": "ヒップスラスト"})
    assert r.status_code == 200

    with patch("app.integrations.exercisedb.fetch_gif_by_id", return_value=b"CURATED") as mock_fetch:
        r = app_client.get("/api/exercise-gif", params={"name": "ヒップスラスト"})
    assert r.content == b"CURATED"
    mock_fetch.assert_called_once_with("3562")


def test_candidates_reports_unconfigured_when_api_key_missing(app_client):
    """API キー未設定を「候補なし」と区別できること。

    区別できないと、配線漏れで連携が死んでいても UI は「候補が見つかりませんでした」と
    出すだけで、原因が種目名なのか設定なのか永久に判別できない (実際にそれで気づけなかった)。
    """
    r = app_client.get("/api/exercise-candidates", params={"name": "ダンベルベンチプレス"})
    assert r.status_code == 200
    body = r.json()
    assert body["configured"] is False
    assert body["candidates"] == []
