from __future__ import annotations

from unittest.mock import patch

from app.integrations.exercisedb import (
    curated_id,
    infer_equipment,
    list_candidates,
    resolve_id,
    search_term,
)


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


def test_curated_id_covers_framework_exercises():
    # training_split.py の全種目は事前に本番プローブで ID を確認済み (名前検索の
    # あいまいさに依存しない)。
    assert curated_id("ダンベルベンチプレス") == "0289"
    assert curated_id("ダンベルロー (片手)") == "0292"  # 「片手」明記 → one arm 版
    assert curated_id("ダンベルRDL (ルーマニアンデッドリフト)") == "1459"


def test_curated_id_fixes_previously_mismatched_exercises():
    # 自重スクワットが器具違い(ダンベル)の画像になっていたバグ → 自重版 ID に修正
    assert curated_id("自重スクワット (スロー/ジャンプ)") == "3533"
    # レッグレイズが懸垂バー前提の画像(所有器具に無い)になっていたバグ → マット版に修正
    assert curated_id("レッグレイズ") == "0620"
    # ヒップスラストが無関係のバンド種目になっていたバグ → ベンチブリッジ系に修正
    assert curated_id("ダンベルヒップスラスト") == "3562"


def test_curated_id_none_when_no_good_match_exists():
    # スーパーマン(背面伸展)・ダンベルスイングは ExerciseDB に一致する種目が無い。
    # 誤った画像を出すより GIF 無しの方が良いので、キュレーション対象に含めない。
    assert curated_id("スーパーマン (背面伸展・自重)") is None
    assert curated_id("ダンベルスイング") is None


def test_infer_equipment_from_ja_name():
    assert infer_equipment("ダンベルベンチプレス") == "dumbbell"
    assert infer_equipment("自重スクワット (スロー/ジャンプ)") == "body weight"
    assert infer_equipment("腕立て伏せ (デクライン)") == "body weight"
    assert infer_equipment("プランク (前腕/サイド)") == "body weight"


def test_list_candidates_scores_by_keyword_overlap_within_equipment():
    pool = [
        {"id": "9001", "name": "resistance band hip thrusts on knees", "equipment": "band", "target": "glutes"},
        {"id": "9002", "name": "barbell glute bridge two legs on bench", "equipment": "barbell", "target": "glutes"},
        {"id": "9003", "name": "dumbbell bench press", "equipment": "dumbbell", "target": "pectorals"},
    ]
    with patch("app.integrations.exercisedb._fetch_equipment_pool", return_value=pool):
        cands = list_candidates("ダンベルヒップスラスト", limit=3)
    assert cands[0]["id"] == "9002"  # "glute bridge two legs on bench" と最も語が重なる


def test_resolve_id_prefers_curated_over_auto_search():
    with patch("app.integrations.exercisedb._fetch_equipment_pool") as mock_pool:
        result = resolve_id("ダンベルベンチプレス")
        mock_pool.assert_not_called()  # curated 一致があれば実行時検索は不要
    assert result == "0289"


def test_resolve_id_falls_back_to_auto_when_uncurated():
    pool = [{"id": "9099", "name": "superman push-up", "equipment": "body weight", "target": "pectorals"}]
    with patch("app.integrations.exercisedb._fetch_equipment_pool", return_value=pool):
        assert resolve_id("スーパーマン (背面伸展・自重)") == "9099"
