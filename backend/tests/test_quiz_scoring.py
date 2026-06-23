from __future__ import annotations

import pytest

from app.scoring import learning


@pytest.fixture
def db(temp_data_dir, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(temp_data_dir))
    from app.config import reset_settings_cache

    reset_settings_cache()
    from app.db import create_all, init_engine

    init_engine(temp_data_dir / "test.sqlite3")
    create_all()
    yield


def _points(chapter: int) -> int:
    return learning.chapter_quiz_progress(chapter)["quiz_points"]


# --- 配点 ---


def test_free_word_full_awards_50_and_sets_floor(db):
    r = learning.award_quiz_points(1, free_understanding=85)
    assert r["gained"] == 50
    assert r["quiz_points"] == 50
    assert r["free_word_passed"] is True
    assert r["cleared"] is False  # 100 未満


def test_free_word_partial_awards_15_no_floor(db):
    r = learning.award_quiz_points(1, free_understanding=60)
    assert r["gained"] == 15
    assert r["free_word_passed"] is False


def test_free_word_low_awards_zero(db):
    r = learning.award_quiz_points(1, free_understanding=30)
    assert r["gained"] == 0


def test_choice4_correct_awards_20(db):
    r = learning.award_quiz_points(1, choice_correct=True, fmt="choice4")
    assert r["gained"] == 20


def test_choice2_correct_awards_10(db):
    r = learning.award_quiz_points(1, choice_correct=True, fmt="choice2")
    assert r["gained"] == 10


def test_choice_wrong_awards_zero(db):
    r = learning.award_quiz_points(1, choice_correct=False, fmt="choice4")
    assert r["gained"] == 0


# --- 累積とクリア判定 ---


def test_points_accumulate_across_calls(db):
    learning.award_quiz_points(1, choice_correct=True, fmt="choice4")  # 20
    learning.award_quiz_points(1, choice_correct=True, fmt="choice2")  # 10
    assert _points(1) == 30


def test_two_free_word_passes_clear_chapter(db):
    learning.award_quiz_points(1, free_understanding=90)  # 50, floor set
    r = learning.award_quiz_points(1, free_understanding=85)  # 100
    assert r["cleared"] is True
    assert "state" in r


def test_choice_only_cannot_clear_without_free_word(db):
    # 4択を 5 回正解 = 100 点だが、フリーワード正解が無いのでクリアしない
    for _ in range(5):
        r = learning.award_quiz_points(1, choice_correct=True, fmt="choice4")
    assert r["quiz_points"] == 100
    assert r["free_word_passed"] is False
    assert r["cleared"] is False


def test_free_word_plus_choices_clear(db):
    learning.award_quiz_points(1, free_understanding=85)  # 50, floor
    learning.award_quiz_points(1, choice_correct=True, fmt="choice4")  # 70
    learning.award_quiz_points(1, choice_correct=True, fmt="choice4")  # 90
    r = learning.award_quiz_points(1, choice_correct=True, fmt="choice2")  # 100
    assert r["cleared"] is True


def test_clear_marks_chapter_explained(db):
    learning.award_quiz_points(1, free_understanding=90)
    r = learning.award_quiz_points(1, free_understanding=90)
    assert r["cleared"] is True
    # ch1 の全節が explained になっている
    st = r["state"]
    ch1 = next(c for c in st["chapters"] if c["chapter"] == 1)
    assert ch1["sections"]  # 節がある
    assert all(s["explained"] for s in ch1["sections"])


def test_unknown_chapter_raises(db):
    with pytest.raises(ValueError):
        learning.award_quiz_points(99, free_understanding=90)
