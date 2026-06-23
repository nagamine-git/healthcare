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


def _fake_completion(understanding, *, next_question="次の質問です", comment="講評"):
    async def _fn(system, messages, *, model, api_key):
        return {"understanding": understanding, "next_question": next_question, "comment": comment}
    return _fn


def test_quiz_continues_below_threshold(app_client, monkeypatch):
    from app.llm import quiz

    monkeypatch.setattr(quiz, "_completion",
                        _fake_completion(40, next_question="所有権を説明して"))
    r = app_client.post("/api/learning/chapter/4/quiz", json={"messages": []})
    assert r.status_code == 200
    body = r.json()
    assert body["understanding"] == 40
    assert body["cleared"] is False
    assert "所有権" in body["reply"]
    assert "state" not in body


def test_free_word_pass_awards_points_but_not_clear(app_client, monkeypatch):
    """単発のフリーワード正解 (85%) は +50 で品質フロアを満たすが、100 点未満なのでクリアしない。"""
    from app.llm import quiz

    monkeypatch.setattr(quiz, "_completion",
                        _fake_completion(85, next_question="次は借用について説明して", comment="良い説明です"))
    msgs = [
        {"role": "assistant", "content": "所有権とは?"},
        {"role": "user", "content": "値の所有者は常に1つで、スコープを抜けると破棄される"},
    ]
    r = app_client.post("/api/learning/chapter/4/quiz", json={"messages": msgs}).json()
    assert r["understanding"] == 85
    assert r["gained"] == 50
    assert r["quiz_points"] == 50
    assert r["free_word_passed"] is True
    assert r["cleared"] is False
    assert "state" not in r


def test_two_free_word_passes_clear_chapter(app_client, monkeypatch):
    from app.llm import quiz

    monkeypatch.setattr(quiz, "_completion",
                        _fake_completion(90, next_question="次の観点を説明して", comment="良い"))
    msgs = [
        {"role": "assistant", "content": "Q"},
        {"role": "user", "content": "ある回答"},
    ]
    # 1 回目: 50 点
    app_client.post("/api/learning/chapter/4/quiz", json={"messages": msgs})
    # 2 回目: 100 点 → クリア
    r = app_client.post("/api/learning/chapter/4/quiz", json={"messages": msgs}).json()
    assert r["quiz_points"] == 100
    assert r["cleared"] is True
    ch4 = next(c for c in r["state"]["chapters"] if c["chapter"] == 4)
    assert ch4["explained"] is True
    assert all(s["explained"] for s in ch4["sections"])


def _fake_choice(correct_index=0):
    async def _fn(system, messages, *, model, api_key):
        return {
            "question": "所有権の規則として正しいのは?",
            "options": ["所有者は常に1つ", "所有者は複数可", "GCが管理", "参照は所有権を奪う"],
            "correct_index": correct_index,
            "explanation": "Rust では各値の所有者は常に1つです。",
        }
    return _fn


def test_choice_question_generation(app_client, monkeypatch):
    from app.llm import quiz

    monkeypatch.setattr(quiz, "_choice_completion", _fake_choice())
    r = app_client.post(
        "/api/learning/chapter/4/quiz",
        json={"messages": [], "format": "choice4", "action": "question"},
    ).json()
    assert len(r["options"]) == 4
    assert r["correct_index"] == 0
    assert r["format"] == "choice4"
    assert r["quiz_points"] == 0


def test_choice_answer_correct_awards_points(app_client):
    r = app_client.post(
        "/api/learning/chapter/4/quiz",
        json={"format": "choice4", "action": "answer", "selected_index": 2, "correct_index": 2},
    ).json()
    assert r["correct"] is True
    assert r["gained"] == 20
    assert r["quiz_points"] == 20
    assert r["cleared"] is False  # フリーワード未通過


def test_choice_answer_wrong_no_points(app_client):
    r = app_client.post(
        "/api/learning/chapter/4/quiz",
        json={"format": "choice2", "action": "answer", "selected_index": 0, "correct_index": 1},
    ).json()
    assert r["correct"] is False
    assert r["gained"] == 0


def test_choice_only_cannot_clear(app_client):
    # 4択を 5 回正解 = 100 点でもフリーワード未通過ならクリアしない
    for _ in range(5):
        r = app_client.post(
            "/api/learning/chapter/4/quiz",
            json={"format": "choice4", "action": "answer", "selected_index": 1, "correct_index": 1},
        ).json()
    assert r["quiz_points"] == 100
    assert r["cleared"] is False


def test_quiz_below_threshold_does_not_mark(app_client, monkeypatch):
    from app.llm import quiz

    monkeypatch.setattr(quiz, "_completion", _fake_completion(60))
    r = app_client.post("/api/learning/chapter/4/quiz", json={"messages": []}).json()
    assert r["cleared"] is False
    assert "state" not in r
    s = app_client.get("/api/learning/state").json()
    ch4 = next(c for c in s["chapters"] if c["chapter"] == 4)
    assert ch4["explained"] is False


def test_quiz_unknown_chapter(app_client):
    assert app_client.post("/api/learning/chapter/99/quiz", json={"messages": []}).status_code == 404


def _fake_tutor(reply="`所有権` は値の所有者が常に1つ、という規則です。\n\n```rust\nlet s = String::new();\n```"):
    async def _fn(system, messages, *, model, api_key):
        return reply
    return _fn


def test_review_mode_returns_reply_without_grading(app_client, monkeypatch):
    from app.llm import quiz

    monkeypatch.setattr(quiz, "_tutor_completion", _fake_tutor())
    msgs = [
        {"role": "assistant", "content": "良い説明です"},
        {"role": "user", "content": "ライフタイムをもう一度わかりやすく説明して"},
    ]
    r = app_client.post(
        "/api/learning/chapter/4/quiz", json={"messages": msgs, "mode": "review"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["review"] is True
    assert "所有権" in body["reply"]
    # 復習モードは採点しない: 合格判定や state 更新は起きない
    assert "cleared" not in body
    assert "state" not in body


def test_review_mode_does_not_call_examiner(app_client, monkeypatch):
    """review では採点用 _completion ではなく _tutor_completion が使われる。"""
    from app.llm import quiz

    def _boom(*a, **k):
        raise AssertionError("examiner completion must not be called in review mode")

    monkeypatch.setattr(quiz, "_completion", _boom)
    monkeypatch.setattr(quiz, "_tutor_completion", _fake_tutor(reply="復習だよ"))
    r = app_client.post(
        "/api/learning/chapter/4/quiz", json={"messages": [], "mode": "review"}
    ).json()
    assert r["reply"] == "復習だよ"


def test_review_mode_unknown_chapter(app_client, monkeypatch):
    from app.llm import quiz

    monkeypatch.setattr(quiz, "_tutor_completion", _fake_tutor())
    r = app_client.post("/api/learning/chapter/99/quiz", json={"messages": [], "mode": "review"})
    assert r.status_code == 404
