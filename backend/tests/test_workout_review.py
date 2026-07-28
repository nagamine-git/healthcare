"""ワークアウト一言評価 API のテスト (LLM は monkeypatch)。"""

from __future__ import annotations

from datetime import datetime, timedelta

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


def _add_workout(session, wid="w1", wtype="running"):
    from app.models import Workout

    session.add(Workout(
        id=wid, source="garmin", start=datetime.utcnow() - timedelta(hours=2),
        end=datetime.utcnow() - timedelta(hours=1, minutes=45),
        type=wtype, duration_s=900, distance_m=2400.0, avg_hr=155.0, max_hr=183.0,
    ))
    session.commit()


def test_list_empty(app_client):
    r = app_client.get("/api/workout-reviews")
    assert r.status_code == 200
    assert r.json()["items"] == []


def test_generate_persist_and_idempotent(app_client, session, monkeypatch):
    _add_workout(session)
    calls = {"n": 0}

    async def fake_generate(workout_id):
        calls["n"] += 1
        return {"text": "GPS未捕捉で距離が出ていません。次回は捕捉を待ってから。", "tone": "caution", "model": "test"}

    import app.llm.workout_review as wr

    monkeypatch.setattr(wr, "generate_review", fake_generate)

    r1 = app_client.post("/api/workout-reviews/w1")
    assert r1.status_code == 200
    assert r1.json()["review_tone"] == "caution"
    assert calls["n"] == 1

    # 冪等: 2回目は再生成しない
    r2 = app_client.post("/api/workout-reviews/w1")
    assert r2.status_code == 200 and calls["n"] == 1

    # force で再生成
    r3 = app_client.post("/api/workout-reviews/w1?force=1")
    assert r3.status_code == 200 and calls["n"] == 2

    # 一覧に保存済み評価が乗る
    r4 = app_client.get("/api/workout-reviews")
    item = next(i for i in r4.json()["items"] if i["workout_id"] == "w1")
    assert "GPS未捕捉" in item["review_text"]
    assert item["type_label"] == "ランニング"


def test_unknown_workout_404(app_client):
    r = app_client.post("/api/workout-reviews/nope")
    assert r.status_code == 404


# --- _gather_context: exercise_sets 有無でコンテキストが分岐する -----------------


def _add_strength_workout(session, wid, start, exercise_sets=None):
    from app.models import Workout

    raw_json = {"activityId": 1} if exercise_sets is None else {
        "activityId": 1, "exercise_sets": exercise_sets,
    }
    session.add(Workout(
        id=wid, source="garmin", start=start, end=start + timedelta(minutes=15),
        type="strength_training", duration_s=900, avg_hr=110.0, max_hr=140.0,
        raw_json=raw_json,
    ))
    session.commit()


SAMPLE_SETS = {
    "sets": [
        {"category": "ROW", "name": None, "reps": 8, "weight_kg": 12.0,
         "duration_s": 59.3, "start": "2026-07-26T08:09:21.0"},
        {"category": "ROW", "name": None, "reps": 8, "weight_kg": 12.0,
         "duration_s": 39.4, "start": "2026-07-26T08:11:24.0"},
        {"category": "CURL", "name": None, "reps": 6, "weight_kg": 8.0,
         "duration_s": 24.0, "start": "2026-07-26T08:19:55.0"},
    ]
}


def test_gather_context_includes_exercise_detail_when_present(app_client, session):
    """exercise_sets があれば種目単位のボリューム/rep レンジ + 既往情報 + 直近セッションを渡す。"""
    from app.llm.workout_review import _gather_context

    _add_strength_workout(
        session, "w-prev", datetime.utcnow() - timedelta(days=3), exercise_sets=SAMPLE_SETS
    )
    _add_strength_workout(
        session, "w-today", datetime.utcnow() - timedelta(hours=1), exercise_sets=SAMPLE_SETS
    )

    ctx = _gather_context("w-today")
    assert ctx is not None
    exercises = ctx["workout"]["exercises"]
    assert {e["category"] for e in exercises} == {"ROW", "CURL"}
    row = next(e for e in exercises if e["category"] == "ROW")
    assert row["set_count"] == 2
    assert row["rep_range"] == [8, 8]
    assert row["volume_kg"] == 12.0 * 8 * 2

    assert "user_injury_notes" in ctx
    assert any("腰" in note for note in ctx["user_injury_notes"])

    assert len(ctx["recent_exercise_sessions"]) == 1
    assert ctx["recent_exercise_sessions"][0]["exercises"][0]["category"] == "ROW"


def test_gather_context_falls_back_when_no_exercise_sets(app_client, session):
    """exercise_sets が無い (未対応/古いワークアウト) 場合は従来どおりのコンテキストのまま
    種目情報を捏造しない (workout.exercises / recent_exercise_sessions が乗らない)。"""
    from app.llm.workout_review import _gather_context

    _add_strength_workout(session, "w-plain", datetime.utcnow() - timedelta(hours=1))

    ctx = _gather_context("w-plain")
    assert ctx is not None
    assert "exercises" not in ctx["workout"]
    assert "recent_exercise_sessions" not in ctx
    assert "user_injury_notes" not in ctx


def test_gather_context_attaches_prev_volume_for_same_exercise(app_client, session):
    """前回同種目 (category+name) のボリュームが prev_volume_kg / delta として付く
    (LLM に前回比の数字を作らせず、サーバー側で決定論的に計算する)。"""
    from app.llm.workout_review import _gather_context

    prev_sets = {
        "sets": [
            {"category": "ROW", "name": None, "reps": 10, "weight_kg": 10.0},
            {"category": "ROW", "name": None, "reps": 10, "weight_kg": 10.0},
        ]
    }
    _add_strength_workout(
        session, "w-prev2", datetime.utcnow() - timedelta(days=2), exercise_sets=prev_sets
    )
    _add_strength_workout(
        session, "w-today2", datetime.utcnow() - timedelta(hours=1), exercise_sets=SAMPLE_SETS
    )

    ctx = _gather_context("w-today2")
    row = next(e for e in ctx["workout"]["exercises"] if e["category"] == "ROW")
    # 前回 ROW ボリューム = 10*10*2 = 200、今回 = 12*8*2 = 192 (SAMPLE_SETS)
    assert row["prev_volume_kg"] == 200.0
    assert row["volume_delta_kg"] == round(192.0 - 200.0, 1)
    assert row["volume_delta_pct"] is not None

    curl = next(e for e in ctx["workout"]["exercises"] if e["category"] == "CURL")
    # 前回セッションに CURL が無いので prev_volume_kg は None
    assert curl["prev_volume_kg"] is None
    assert curl["volume_delta_kg"] is None


# --- 種目名の日本語化 -------------------------------------------------------


def test_ja_label_prefers_name_then_category_then_fallback():
    from app.llm.workout_review import _ja_label

    assert _ja_label("SQUAT", "GOBLET_SQUAT") == "ゴブレットスクワット"
    # name が無い (Garmin が詳細検出できない) 場合は category のラベルにフォールバック
    assert _ja_label("CALF_RAISE", None) == "カーフレイズ"
    assert _ja_label("PLANK", None) == "プランク"
    # どちらも未収録なら生の文字列を出す (空白で落とさない)
    assert _ja_label("SOME_NEW_CATEGORY", None) == "SOME_NEW_CATEGORY"
    assert _ja_label(None, None) == "種目不明"


# --- LLM の種目別短評とサーバー計算スタッツのマージ --------------------------


def test_merge_exercise_review_matches_by_category_and_name_and_falls_back():
    from app.llm.workout_review import _merge_exercise_review

    computed = [
        {"category": "SQUAT", "name": "GOBLET_SQUAT", "set_count": 3, "volume_kg": 312.0},
        {"category": "PLANK", "name": None, "set_count": 3, "volume_kg": None},
    ]
    llm_exercises = [
        # 順序が computed と違っても category+name で正しく突き合う
        {"category": "PLANK", "name": "", "comment": "終盤で保持時間が落ちている。", "tone": "caution"},
        {"category": "SQUAT", "name": "GOBLET_SQUAT", "comment": "前回よりボリューム増加。", "tone": "good"},
    ]
    merged = _merge_exercise_review(computed, llm_exercises)
    squat = next(e for e in merged if e["category"] == "SQUAT")
    assert squat["comment"] == "前回よりボリューム増加。"
    assert squat["tone"] == "good"
    plank = next(e for e in merged if e["category"] == "PLANK")
    assert plank["comment"] == "終盤で保持時間が落ちている。"

    # LLM が返さなかった種目にはフォールバック文が入る (空欄にしない)
    merged2 = _merge_exercise_review(computed, [])
    assert all(e["comment"] for e in merged2)
    assert all(e["tone"] == "info" for e in merged2)


# --- API: 構造化評価の永続化・再分析のレート制限 -----------------------------


def test_create_review_persists_structured_exercises(app_client, session, monkeypatch):
    """LLM が返す overall/exercises 構造が WorkoutReview.exercises_json に保存され、
    一覧 API (review_exercises) からも取れる。"""
    _add_strength_workout(
        session, "w-struct", datetime.utcnow() - timedelta(hours=1), exercise_sets=SAMPLE_SETS
    )

    async def fake_generate(workout_id):
        return {
            "text": "全体的にボリュームは前回並み。ROW はやや疲労が見える。",
            "tone": "info",
            "model": "test",
            "exercises": [
                {
                    "category": "ROW", "name": None, "name_ja": "ロー (背中)", "set_count": 2,
                    "rep_range": [8, 8], "volume_kg": 192.0, "prev_volume_kg": None,
                    "volume_delta_kg": None, "volume_delta_pct": None,
                    "comment": "終盤フォームが崩れがち。", "tone": "caution",
                },
                {
                    "category": "CURL", "name": None, "name_ja": "カール (上腕二頭筋)", "set_count": 1,
                    "rep_range": [6, 6], "volume_kg": 48.0, "prev_volume_kg": None,
                    "volume_delta_kg": None, "volume_delta_pct": None,
                    "comment": "軽負荷で丁寧にこなせている。", "tone": "good",
                },
            ],
        }

    import app.llm.workout_review as wr

    monkeypatch.setattr(wr, "generate_review", fake_generate)

    r = app_client.post("/api/workout-reviews/w-struct")
    assert r.status_code == 200
    body = r.json()
    assert body["review_exercises"] is not None
    assert len(body["review_exercises"]) == 2
    assert body["review_exercises"][0]["name_ja"] == "ロー (背中)"

    items = app_client.get("/api/workout-reviews").json()["items"]
    item = next(i for i in items if i["workout_id"] == "w-struct")
    assert item["review_exercises"][1]["comment"] == "軽負荷で丁寧にこなせている。"


def test_non_strength_review_has_no_exercises(app_client, session, monkeypatch):
    """種目データが無い運動 (ラン等) は review_exercises が None のまま (従来どおり総合のみ)。"""
    _add_workout(session, wid="w-run")

    async def fake_generate(workout_id):
        return {"text": "ペースは安定。", "tone": "good", "model": "test", "exercises": None}

    import app.llm.workout_review as wr

    monkeypatch.setattr(wr, "generate_review", fake_generate)

    r = app_client.post("/api/workout-reviews/w-run")
    assert r.status_code == 200
    assert r.json()["review_exercises"] is None


def test_regenerate_rate_limit(app_client, session, monkeypatch):
    """「再分析」(force かつ既存あり) は日次上限 (既定 Settings.llm_max_regenerations_per_day=3)
    を超えると 429 で LLM を呼ばない。初回生成はカウント対象外。"""
    _add_workout(session, wid="w-cap")
    calls = {"n": 0}

    async def fake_generate(workout_id):
        calls["n"] += 1
        return {"text": f"評価{calls['n']}", "tone": "info", "model": "test", "exercises": None}

    import app.llm.workout_review as wr

    monkeypatch.setattr(wr, "generate_review", fake_generate)

    # 初回生成 (force なし) はカウント対象外
    r0 = app_client.post("/api/workout-reviews/w-cap")
    assert r0.status_code == 200 and calls["n"] == 1

    # 既定の上限まで force 再生成できる
    for _ in range(3):
        r = app_client.post("/api/workout-reviews/w-cap?force=1")
        assert r.status_code == 200
    assert calls["n"] == 4

    # 上限超過は 429、LLM も呼ばれない
    r_over = app_client.post("/api/workout-reviews/w-cap?force=1")
    assert r_over.status_code == 429
    assert calls["n"] == 4

    # 直前の評価はそのまま残っている (壊れていない)
    items = app_client.get("/api/workout-reviews").json()["items"]
    item = next(i for i in items if i["workout_id"] == "w-cap")
    assert item["review_text"] == "評価4"


def test_time_based_exercise_keeps_duration():
    """プランク等の等尺種目は rep/重量でなく保持時間で評価できる形にする。

    回帰テスト: 集約時に duration_s を捨てていたため、Garmin が「0:48 / 1回 / 体重」と
    記録しているプランクが「1rep」としか見えず、AI が保持時間の落ち込みを評価できなかった。
    """
    from app.llm.workout_review import _summarize_exercise_sets

    sets = [
        {"category": "PLANK", "name": None, "reps": 1, "weight_kg": None, "duration_s": 47.9},
        {"category": "PLANK", "name": None, "reps": 1, "weight_kg": None, "duration_s": 26.2},
        {"category": "PLANK", "name": None, "reps": 1, "weight_kg": None, "duration_s": 16.8},
    ]
    (ex,) = _summarize_exercise_sets(sets)
    assert ex["time_based"] is True
    assert ex["volume_kg"] is None            # 加重が無いので重量ボリュームは出さない
    assert ex["hold_range_s"] == [16.8, 47.9]  # 保持時間で評価できる
    assert ex["total_duration_s"] == 90.9
    assert all(s["duration_s"] is not None for s in ex["set_details"])


def test_weighted_exercise_is_not_time_based():
    """加重種目は従来どおりボリュームで評価する (時間種目扱いにしない)。"""
    from app.llm.workout_review import _summarize_exercise_sets

    sets = [
        {"category": "SQUAT", "name": "GOBLET_SQUAT", "reps": 14, "weight_kg": 8.0, "duration_s": 38.8},
        {"category": "SQUAT", "name": "GOBLET_SQUAT", "reps": 15, "weight_kg": 8.0, "duration_s": 33.9},
    ]
    (ex,) = _summarize_exercise_sets(sets)
    assert not ex.get("time_based")
    assert ex["volume_kg"] == 232.0
    assert ex["total_duration_s"] == 72.7  # 時間も併せて持つ (捨てない)
