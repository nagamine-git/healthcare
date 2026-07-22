"""種目ステップ式フォームガイド API のテスト (LLM は monkeypatch)。"""

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


_FAKE_STEPS = {
    "setup": ["肩幅よりやや広く握る", "肩甲骨を寄せて胸を張る"],
    "execution": ["肘を45度に保ちながら下ろす", "胸につく手前で切り返す"],
    "breathing": ["下ろすときに吸う", "上げるときに吐く"],
    "mistakes": ["腰が反って肋骨が開く", "肘が開きすぎて肩がすくむ"],
    "tips": ["最下点で1秒静止する意識を持つ"],
}


def _mock_llm(monkeypatch, calls, *, result="ok"):
    async def fake(name):
        calls["n"] += 1
        if result == "none":
            return None
        return {"name_ja": name, "steps": _FAKE_STEPS, "model": "test-model"}

    import app.llm.exercise_guide as eg

    monkeypatch.setattr(eg, "generate_guide", fake)


def test_get_returns_204_when_not_cached(app_client):
    r = app_client.get("/api/exercise-guide", params={"name": "ダンベルベンチプレス"})
    assert r.status_code == 204


def test_post_generates_persists_and_idempotent(app_client, monkeypatch):
    calls = {"n": 0}
    _mock_llm(monkeypatch, calls)

    r1 = app_client.post("/api/exercise-guide", json={"name": "ダンベルベンチプレス"})
    assert r1.status_code == 200
    body = r1.json()
    assert body["cached"] is True
    assert body["name_ja"] == "ダンベルベンチプレス"
    assert body["steps"] == _FAKE_STEPS
    assert body["model"] == "test-model"
    assert calls["n"] == 1

    # 冪等: 2回目は再生成しない
    r2 = app_client.post("/api/exercise-guide", json={"name": "ダンベルベンチプレス"})
    assert r2.status_code == 200
    assert calls["n"] == 1

    # GET で保存済みが返る
    r3 = app_client.get("/api/exercise-guide", params={"name": "ダンベルベンチプレス"})
    assert r3.status_code == 200
    assert r3.json()["steps"] == _FAKE_STEPS


def test_post_force_regenerates(app_client, monkeypatch):
    calls = {"n": 0}
    _mock_llm(monkeypatch, calls)

    app_client.post("/api/exercise-guide", json={"name": "ダンベルベンチプレス"})
    r = app_client.post("/api/exercise-guide?force=true", json={"name": "ダンベルベンチプレス"})
    assert r.status_code == 200
    assert calls["n"] == 2


def test_post_503_when_llm_unavailable(app_client, monkeypatch):
    calls = {"n": 0}
    _mock_llm(monkeypatch, calls, result="none")

    r = app_client.post("/api/exercise-guide", json={"name": "存在しない種目"})
    assert r.status_code == 503

    # 保存されていないので GET は 204 のまま
    r2 = app_client.get("/api/exercise-guide", params={"name": "存在しない種目"})
    assert r2.status_code == 204


def test_normalization_key_matches_across_bracket_variants(app_client, monkeypatch):
    """括弧付き補足の有無で正規化キーが揃い、同じキャッシュを共有すること。"""
    calls = {"n": 0}
    _mock_llm(monkeypatch, calls)

    app_client.post("/api/exercise-guide", json={"name": "ダンベルロー (片手)"})
    r = app_client.get("/api/exercise-guide", params={"name": "ダンベルロー"})
    assert r.status_code == 200
    assert calls["n"] == 1


def test_exercise_guide_model_roundtrip(session):
    from app.models import ExerciseGuide

    session.add(ExerciseGuide(
        exercise_key="dumbbellrow", name_ja="ダンベルロー", steps_json=_FAKE_STEPS, model="test-model",
    ))
    session.commit()

    row = session.get(ExerciseGuide, "dumbbellrow")
    assert row is not None
    assert row.steps_json == _FAKE_STEPS
    assert set(row.steps_json.keys()) == {"setup", "execution", "breathing", "mistakes", "tips"}
