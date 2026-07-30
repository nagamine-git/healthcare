"""「時間あたりの回復効率」分析 (`scoring/sleep_efficiency.py`) のユニットテスト。

DB非依存の純関数なので `sleep_drivers._collect()` と同じ形の dict を手組みして渡す。
実データ (n=86夜) で確認済みの傾向 (時間は説明力ほぼゼロ・効率は強い・約6時間で頭打ち) を
合成データで再現し、飽和点判定・reliable フラグ・相関・安全文言が期待通りになることを検証する。
"""

from __future__ import annotations

from app.scoring.sleep_efficiency import analyze_recovery_efficiency


def _row(duration_min: float, bb: float | None, efficiency: float | None = None,
         deep_min: float | None = None, energy: float | None = None) -> dict:
    return {
        "duration": duration_min, "morning_bb": bb,
        "efficiency": efficiency, "deep_min": deep_min, "energy": energy,
    }


def test_empty_rows_do_not_crash():
    out = analyze_recovery_efficiency([])
    assert out["n_nights"] == 0
    assert out["per_hour"]["n"] == 0
    assert out["saturation"]["peak"] is None
    assert all(b["n"] == 0 and b["reliable"] is False for b in out["saturation"]["bins"])
    assert out["correlations"]["duration"]["r"] is None
    assert out["caveat"]  # 安全文言は空データでも必ず出る


def test_saturation_peaks_around_six_hours_and_thin_bins_are_unreliable():
    """睡眠時間を伸ばしてもBBはある点で頭打ちになる合成データで、
    ピークが正しいビンに出て、薄い最終ビンが reliable=False になることを確認する。"""
    rows: list[dict] = []
    # 〜5.5h: 23夜, 平均BB 69.9相当
    for i in range(23):
        rows.append(_row(duration_min=280 + (i % 5) * 5, bb=68 + (i % 4)))
    # 5.5-6.5h: 37夜, 平均BB 72.3相当 (ここがピーク)
    for i in range(37):
        rows.append(_row(duration_min=340 + (i % 10) * 5, bb=71 + (i % 3)))
    # 6.5-7.5h: 21夜, 平均BB 71.1相当 (ピークよりわずかに低い)
    for i in range(21):
        rows.append(_row(duration_min=410 + (i % 6) * 5, bb=70 + (i % 3)))
    # 7.5h+: 4夜のみ (薄い) BBは低め → n<8 のため reliable=False で結論に使われない
    for i in range(4):
        rows.append(_row(duration_min=460 + i * 5, bb=60 + i))

    out = analyze_recovery_efficiency(rows)
    bins = {b["label"]: b for b in out["saturation"]["bins"]}
    assert bins["〜5.5h"]["n"] == 23
    assert bins["5.5-6.5h"]["n"] == 37
    assert bins["6.5-7.5h"]["n"] == 21
    assert bins["7.5h+"]["n"] == 4

    assert bins["〜5.5h"]["reliable"] is True
    assert bins["5.5-6.5h"]["reliable"] is True
    assert bins["6.5-7.5h"]["reliable"] is True
    assert bins["7.5h+"]["reliable"] is False  # n=4 < 8 → データ不足

    peak = out["saturation"]["peak"]
    assert peak is not None
    assert peak["peak_bin"] == "5.5-6.5h"  # 頭打ちの点は信頼できるビンの中で最良
    assert peak["hours"] == 6.5
    assert peak["observed_within_range"] is True  # 青天井ビンがピークではない


def test_saturation_not_claimed_when_best_bin_is_open_ended_and_thin():
    """最良平均BBのビンが薄い最終ビン(青天井)しかない場合、そこを飽和点として
    採用しない (=「長く寝ても意味がない」と薄いデータから言わせない安全弁)。"""
    rows: list[dict] = []
    for i in range(10):
        rows.append(_row(duration_min=280 + i, bb=65))  # 〜5.5h: reliable, 平均65
    for i in range(4):
        rows.append(_row(duration_min=460 + i, bb=90))  # 7.5h+: n=4 (unreliable) だが平均は最高

    out = analyze_recovery_efficiency(rows)
    bins = {b["label"]: b for b in out["saturation"]["bins"]}
    assert bins["7.5h+"]["reliable"] is False
    peak = out["saturation"]["peak"]
    # reliable なビンが1つしかない(〜5.5h)ので、比較可能な2ビン未満 → peak は出せない
    assert peak is None


def test_correlation_duration_near_zero_efficiency_strong_positive():
    """睡眠時間はBBとほぼ無相関、効率は強い正の相関、という実データの傾向を再現する。"""
    rows: list[dict] = []
    import random
    rnd = random.Random(42)
    for _i in range(60):
        # duration はランダム (BBと無関係)
        duration = rnd.uniform(280, 480)
        # efficiency は BB と強く連動させる
        efficiency = rnd.uniform(90, 100)
        bb = 40 + (efficiency - 90) * 4 + rnd.uniform(-2, 2)
        rows.append(_row(duration_min=duration, bb=bb, efficiency=efficiency))

    out = analyze_recovery_efficiency(rows)
    corr = out["correlations"]
    assert corr["duration"]["n"] == 60
    assert abs(corr["duration"]["r"]) < 0.3  # 時間はほぼ無相関
    assert corr["efficiency"]["r"] > 0.7     # 効率は強い正の相関


def test_per_hour_top_group_has_higher_efficiency_than_bottom():
    """「時間あたりの回復量」が高い夜ほど効率が高い、という「時間より効率」を
    具体的な数字で見せられることを確認する。"""
    rows: list[dict] = []
    # 短時間・高効率・高BB (時間対効果が良い夜)
    for _i in range(10):
        rows.append(_row(duration_min=330, bb=80, efficiency=98, deep_min=90))
    # 長時間・低効率・低BB (時間対効果が悪い夜)
    for _i in range(10):
        rows.append(_row(duration_min=480, bb=55, efficiency=88, deep_min=60))

    out = analyze_recovery_efficiency(rows)
    ph = out["per_hour"]
    assert ph["n"] == 20
    assert ph["top_avg_efficiency"] > ph["bottom_avg_efficiency"]
    assert ph["top_avg_deep_min"] > ph["bottom_avg_deep_min"]
    # 上位群は実際に bb_per_hour が高いこと
    assert ph["top"][0]["bb_per_hour"] > ph["bottom"][0]["bb_per_hour"]


def test_drivers_extracted_from_efficiency_and_deep_only_reuses_sleep_drivers_output():
    """sleep_drivers.analyze() の quality 結果から efficiency/deep_min 向けの要因だけを
    抜き出し、それ以外 (例: morning_bb を outcome とする next_day 系) は含めないこと。
    統計は再実装せず、既に計算済みの factor をそのまま使う。"""
    driver_quality = [
        {"driver": "steps", "label": "日中の歩数", "outcome": "efficiency",
         "outcome_label": "睡眠効率", "direction": "改善", "diff": 1.2, "p": 0.01,
         "q": 0.02, "tier": "strong", "n": 40},
        {"driver": "alcohol_eve", "label": "夜の飲酒", "outcome": "deep_min",
         "outcome_label": "深睡眠", "direction": "悪化", "diff": -5.0, "p": 0.02,
         "q": 0.03, "tier": "strong", "n": 40},
        {"driver": "midpoint", "label": "就寝が遅い", "outcome": "sleep_score",
         "outcome_label": "睡眠スコア", "direction": "悪化", "diff": -3.0, "p": 0.03,
         "q": 0.04, "tier": "suggestive", "n": 40},
    ]
    out = analyze_recovery_efficiency([_row(360, 70)], driver_quality=driver_quality)
    drivers = out["drivers"]
    assert {d["driver"] for d in drivers} == {"steps", "alcohol_eve"}
    assert all(d["outcome"] in ("efficiency", "deep_min") for d in drivers)


def test_caveat_never_reads_as_sleep_less():
    """安全性の線: 「短く寝ろ」と読める文言がないこと、翌日指標と長期健康を
    明確に切り分ける記述と、目標睡眠時間を自動で下げない旨が含まれること。"""
    out = analyze_recovery_efficiency([])
    caveat_text = "".join(out["caveat"])
    assert "短く寝る" not in caveat_text or "全く別" in caveat_text
    assert "長期" in caveat_text
    assert "自動で引き下げ" in caveat_text or "自動で下げ" in caveat_text
    assert "データ不足" in caveat_text or "薄く表示" in caveat_text


def test_caveats_cover_reverse_causation_and_short_sleep():
    """安全性の但し書きが消えていないこと (これが無いと有害な誤読を招く)。

    - 「時間を伸ばしても伸びない」を「短く寝る方が良い」と読ませない
    - 「長く寝た夜ほど BB が低い」を「長く寝ると悪い」と読ませない
      (逆因果: 不調な日ほど長く寝る、が同じデータを説明する)
    """
    from app.scoring.sleep_efficiency import CAVEATS

    blob = "".join(CAVEATS)
    # 短期指標であること
    assert "短期" in blob or "翌日の準備状態" in blob
    # 短時間睡眠の是認をしていないこと
    assert "短く寝る方が良い" in blob and "別" in blob
    # 逆因果に触れていること
    assert "逆" in blob
    assert "体調が悪い日ほど長く眠る" in blob or "回復が必要な日だったから長く寝た" in blob
