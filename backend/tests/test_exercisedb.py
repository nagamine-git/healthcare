from __future__ import annotations

from app.integrations.exercisedb import search_term


def test_search_term_maps_framework_exercises():
    assert search_term("ダンベルベンチプレス") == "dumbbell bench press"
    # 括弧付き・付帯語を吸収。値は ExerciseDB 実在名。
    assert search_term("ダンベルロー (片手)") == "dumbbell bent over row"
    assert search_term("ダンベルRDL (ルーマニアンデッドリフト)") == "dumbbell romanian deadlift"
    assert search_term("腕立て伏せ (デクライン/ダイヤモンド)") == "push-up"
    assert search_term("ダンベルゴブレットスクワット") == "dumbbell goblet squat"


def test_search_term_none_for_non_gym_moves():
    # 剣道素振り/シャドー/ジョグ/タバタ は ExerciseDB に無い → None (GIF 無し)
    assert search_term("木刀素振り連続 (心拍135)") is None
    assert search_term("シャドーボクシング (心拍130) 20分") is None
    assert search_term("ジョグ") is None
