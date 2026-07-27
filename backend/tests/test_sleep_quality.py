"""evaluate_last_night: 成分ごとの良好/低い判定と改善点 (personal優先/general フォールバック)。"""

from __future__ import annotations

from app.scoring.sleep_quality import evaluate_last_night


def _base(**overrides):
    """デフォルト: 深睡眠/REM/効率/中途覚醒すべて基準内、総睡眠時間も目標どおり → good。"""
    kwargs = dict(
        total_min=480,   # 8h
        deep_min=86,     # 480*0.18 ≈ 基準内 (13-23%)
        rem_min=110,     # 480*0.229 ≈ 基準内 (20-25%)
        light_min=284,
        awake_min=10,    # 効率 = 480/490 ≈ 98% (>=85%), WASO 10分 (<=20分)
        sleep_score=80.0,
        sleep_need_min=480,
    )
    kwargs.update(overrides)
    return evaluate_last_night(**kwargs)


# ----- データなし -----


def test_no_data_returns_none():
    assert evaluate_last_night(
        total_min=None, deep_min=None, rem_min=None, light_min=None,
        awake_min=None, sleep_score=None, sleep_need_min=480,
    ) is None
    assert evaluate_last_night(
        total_min=0, deep_min=None, rem_min=None, light_min=None,
        awake_min=None, sleep_score=None, sleep_need_min=480,
    ) is None


# ----- 全成分良好 -----


def test_all_good_verdict_good():
    out = _base()
    assert out["verdict"] == "good"
    assert out["improvements"] == []
    statuses = {c["key"]: c["status"] for c in out["components"]}
    assert statuses == {"deep": "good", "rem": "good", "efficiency": "good", "awake": "good", "total": "good"}


# ----- 実データ例 (deep 93/371, rem 51/371): deep=良好(基準超え含む) / rem=低い -----


def test_real_data_example_deep_good_rem_low():
    out = _base(total_min=371, deep_min=93, rem_min=51, light_min=None, awake_min=20, sleep_score=74.0)
    by_key = {c["key"]: c for c in out["components"]}
    # deep: 93/371 = 25.07% > 23% 上限だが「低くない」ので good 判定
    assert by_key["deep"]["status"] == "good"
    assert round(by_key["deep"]["pct"], 1) == 25.1
    # rem: 51/371 = 13.75% < 20% 下限 → low
    assert by_key["rem"]["status"] == "low"
    assert round(by_key["rem"]["pct"], 1) == 13.7
    assert out["verdict"] == "mixed"
    assert "深い睡眠は十分" in out["headline"]
    assert "REM" in out["headline"]
    # rem の改善点が入っている (personal 情報なしなので general)
    rem_imps = [i for i in out["improvements"] if i["component"] == "rem"]
    assert len(rem_imps) == 1
    assert rem_imps[0]["basis"] == "general"


# ----- 各成分の閾値境界 -----


def test_deep_pct_below_threshold_is_low():
    out = _base(total_min=500, deep_min=50)  # 10% < 13%
    by_key = {c["key"]: c for c in out["components"]}
    assert by_key["deep"]["status"] == "low"


def test_efficiency_below_threshold_is_low():
    # total=400, awake=100 → 効率 = 400/500 = 80% < 85%
    out = _base(total_min=400, deep_min=80, rem_min=90, awake_min=100)
    by_key = {c["key"]: c for c in out["components"]}
    assert by_key["efficiency"]["status"] == "low"
    assert round(by_key["efficiency"]["pct"], 1) == 80.0


def test_awake_above_threshold_is_high():
    out = _base(awake_min=45)  # > 20分
    by_key = {c["key"]: c for c in out["components"]}
    assert by_key["awake"]["status"] == "high"


def test_total_below_personal_target_minus_tolerance_is_low():
    # 目標480分に対し 400分 (480-30=450 を下回る) → low
    out = _base(total_min=400, deep_min=72, rem_min=92, awake_min=10, sleep_need_min=480)
    by_key = {c["key"]: c for c in out["components"]}
    assert by_key["total"]["status"] == "low"


def test_total_within_tolerance_of_personal_target_is_good():
    # 目標480分に対し 455分 (480-30=450 以上) → good
    out = _base(total_min=455, deep_min=82, rem_min=104, awake_min=10, sleep_need_min=480)
    by_key = {c["key"]: c for c in out["components"]}
    assert by_key["total"]["status"] == "good"


def test_missing_awake_skips_efficiency_and_awake_components():
    out = _base(awake_min=None)
    keys = {c["key"] for c in out["components"]}
    assert "efficiency" not in keys
    assert "awake" not in keys
    assert "deep" in keys and "rem" in keys and "total" in keys


# ----- verdict のしきい値 -----


def test_verdict_poor_when_majority_of_components_bad():
    # 5成分中4つが崩れている (deep低/rem低/efficiency低/awake高)、total だけ良好
    out = _base(
        total_min=480, deep_min=30, rem_min=40, awake_min=90,
        sleep_need_min=400,  # total は良好にする (480 >= 400-30)
    )
    by_key = {c["key"]: c["status"] for c in out["components"]}
    assert by_key["deep"] == "low"
    assert by_key["rem"] == "low"
    assert by_key["efficiency"] == "low"
    assert by_key["awake"] == "high"
    assert by_key["total"] == "good"
    assert out["verdict"] == "poor"


# ----- personal 優先 (実証済み要因があれば一般論より先) -----


def test_personal_basis_used_when_driver_quality_matches_and_powered():
    # rem が低い → outcome=sleep_score にマップされる。suggestive な要因を用意。
    out = _base(
        total_min=371, deep_min=93, rem_min=51, awake_min=20, sleep_score=74.0,
        driver_quality=[
            {
                "driver": "irregular", "label": "就寝時刻の乱れ",
                "outcome": "sleep_score", "outcome_label": "睡眠スコア",
                "direction": "悪化", "tier": "suggestive", "diff": -3.2, "p": 0.03, "q": 0.04, "n": 20,
            },
        ],
    )
    rem_imps = [i for i in out["improvements"] if i["component"] == "rem"]
    assert len(rem_imps) == 1
    assert rem_imps[0]["basis"] == "personal"
    assert "あなたのデータでは" in rem_imps[0]["why"]
    assert "就寝" in rem_imps[0]["text"]  # irregular 用の一般文言 (「就寝・起床の時刻をなるべく揃える」)


def test_personal_recommendation_text_reused_when_driver_matches():
    out = _base(
        total_min=371, deep_min=93, rem_min=51, awake_min=20, sleep_score=74.0,
        driver_quality=[
            {
                "driver": "irregular", "label": "就寝時刻の乱れ",
                "outcome": "sleep_score", "outcome_label": "睡眠スコア",
                "direction": "悪化", "tier": "strong", "diff": -3.2, "p": 0.001, "q": 0.01, "n": 40,
            },
        ],
        driver_recommendations=[
            {"text": "就寝を 23:30±30分に揃える(就寝が乱れた夜ほど睡眠が悪化)",
             "driver": "irregular", "basis": "睡眠スコアにstrong(悪化)", "tier": "strong"},
        ],
    )
    rem_imps = [i for i in out["improvements"] if i["component"] == "rem"]
    assert rem_imps[0]["text"] == "就寝を 23:30±30分に揃える(就寝が乱れた夜ほど睡眠が悪化)"


def test_weak_tier_driver_does_not_count_as_personal():
    # tier=weak は「実証済み」とみなさない → rem の改善点は general にフォールバック
    out = _base(
        total_min=371, deep_min=93, rem_min=51, awake_min=20, sleep_score=74.0,
        driver_quality=[
            {
                "driver": "irregular", "label": "就寝時刻の乱れ",
                "outcome": "sleep_score", "outcome_label": "睡眠スコア",
                "direction": "悪化", "tier": "weak", "diff": -1.0, "p": 0.4, "q": 0.5, "n": 10,
            },
        ],
    )
    rem_imps = [i for i in out["improvements"] if i["component"] == "rem"]
    assert rem_imps[0]["basis"] == "general"


def test_unrelated_outcome_driver_does_not_leak_into_other_component():
    # driver_quality の要因が efficiency 向けなら rem の改善点には影響しない
    out = _base(
        total_min=371, deep_min=93, rem_min=51, awake_min=20, sleep_score=74.0,
        driver_quality=[
            {
                "driver": "caffeine_pm", "label": "午後以降のカフェイン",
                "outcome": "efficiency", "outcome_label": "睡眠効率",
                "direction": "悪化", "tier": "strong", "diff": -5.0, "p": 0.001, "q": 0.01, "n": 30,
            },
        ],
    )
    rem_imps = [i for i in out["improvements"] if i["component"] == "rem"]
    assert rem_imps[0]["basis"] == "general"


def test_personal_improvements_sorted_before_general():
    # deep(low)は personal 情報なし(general)、rem(low)は personal あり → personal が先頭
    out = _base(
        total_min=371, deep_min=30, rem_min=51, awake_min=20, sleep_score=60.0,
        driver_quality=[
            {
                "driver": "irregular", "label": "就寝時刻の乱れ",
                "outcome": "sleep_score", "outcome_label": "睡眠スコア",
                "direction": "悪化", "tier": "strong", "diff": -3.2, "p": 0.001, "q": 0.01, "n": 40,
            },
        ],
    )
    assert len(out["improvements"]) >= 2
    assert out["improvements"][0]["basis"] == "personal"
    assert out["improvements"][0]["component"] == "rem"


def test_no_statistical_jargon_in_improvement_text():
    out = _base(
        total_min=371, deep_min=93, rem_min=51, awake_min=20, sleep_score=74.0,
        driver_quality=[
            {
                "driver": "irregular", "label": "就寝時刻の乱れ",
                "outcome": "sleep_score", "outcome_label": "睡眠スコア",
                "direction": "悪化", "tier": "strong", "diff": -3.2, "p": 0.001, "q": 0.01, "n": 40,
            },
        ],
    )
    for imp in out["improvements"]:
        for term in ("p値", "q値", "有意", "p=", "q="):
            assert term not in imp["text"]
            assert term not in imp["why"]
