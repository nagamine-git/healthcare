from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_client(temp_data_dir, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(temp_data_dir))
    monkeypatch.setenv("HAE_INGEST_TOKEN", "test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")

    from app import main as main_module
    from app.config import Settings, reset_settings_cache

    reset_settings_cache()
    settings = Settings(scheduler_enabled=False, app_data_dir=temp_data_dir)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)

    app = main_module.create_app()
    with TestClient(app) as client:
        yield client


def _fake_completion(reply=None, *, passed=None, feedback=""):
    async def _fn(system, messages, *, model, api_key):
        if passed is None:
            return {"text": reply or "次の質問です: 所有権とは何ですか?", "verdict": None}
        return {"text": "", "verdict": {"passed": passed, "feedback": feedback}}
    return _fn


def test_quiz_continues_without_verdict(app_client, monkeypatch):
    from app.llm import quiz

    monkeypatch.setattr(quiz, "_completion", _fake_completion("所有権を説明して"))
    r = app_client.post("/api/learning/chapter/4/quiz", json={"messages": []})
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"]["decided"] is False
    assert "所有権" in body["reply"]
    assert "state" not in body


def test_quiz_pass_marks_chapter_explained(app_client, monkeypatch):
    from app.llm import quiz

    monkeypatch.setattr(quiz, "_completion", _fake_completion(passed=True, feedback="良い説明です"))
    msgs = [
        {"role": "assistant", "content": "所有権とは?"},
        {"role": "user", "content": "値の所有者は常に1つで、スコープを抜けると破棄される"},
    ]
    r = app_client.post("/api/learning/chapter/4/quiz", json={"messages": msgs}).json()
    assert r["verdict"]["decided"] is True
    assert r["verdict"]["passed"] is True
    # 章4の全節 explained が立ち、章の explained=True に
    ch4 = next(c for c in r["state"]["chapters"] if c["chapter"] == 4)
    assert ch4["explained"] is True
    assert all(s["explained"] for s in ch4["sections"])


def test_quiz_fail_does_not_mark(app_client, monkeypatch):
    from app.llm import quiz

    monkeypatch.setattr(quiz, "_completion", _fake_completion(passed=False, feedback="4.2を読み直し"))
    r = app_client.post("/api/learning/chapter/4/quiz", json={"messages": []}).json()
    assert r["verdict"]["passed"] is False
    assert "state" not in r
    s = app_client.get("/api/learning/state").json()
    ch4 = next(c for c in s["chapters"] if c["chapter"] == 4)
    assert ch4["explained"] is False


def test_quiz_unknown_chapter(app_client):
    assert app_client.post("/api/learning/chapter/99/quiz", json={"messages": []}).status_code == 404
