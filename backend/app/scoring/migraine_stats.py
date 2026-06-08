"""頭痛 (片頭痛) 要因分析の統計コア (DB 非依存の純関数群)。

- onset_profile: 発症時刻の記述的プロファイル (循環統計 + 4 区分)。
- permutation_test: ケース群 vs 対照群の平均差の並べ替え検定 (小サンプル・非正規に頑健)。
- benjamini_hochberg: 多重比較の FDR 補正。

小サンプルでも嘘をつかないことを最優先する。並べ替えは決定的 (乱数を使わず、
組合せ列挙または index ベースの擬似シャッフルで再現性を保つ)。
"""

from __future__ import annotations

from datetime import datetime
from itertools import combinations

from app.scoring.circadian import circular_mean_hour, circular_sd_hours

# 発症時刻の 4 区分 (JST hour)。深夜は 23-24 と 0-4 をまたぐ循環区分。
_BUCKETS: list[tuple[str, int, int]] = [
    ("早朝〜午前", 4, 11),
    ("昼〜午後", 11, 17),
    ("夕〜夜", 17, 23),
    ("深夜", 23, 28),  # 23-24, 0-4 (時刻+24 で表現)
]


def _bucket_label(hour: float) -> str:
    h = hour % 24
    for label, lo, hi in _BUCKETS:
        if hi <= 24:
            if lo <= h < hi:
                return label
        else:  # 深夜: 23-24 or 0-4
            if h >= lo or h < (hi - 24):
                return label
    return "深夜"


def onset_profile(onsets: list[datetime]) -> dict:
    """発症時刻 (JST naive) のプロファイル。記述的で有意性主張はしない。"""
    hours = [d.hour + d.minute / 60.0 for d in onsets]
    counts: dict[str, int] = {label: 0 for label, _, _ in _BUCKETS}
    for h in hours:
        counts[_bucket_label(h)] += 1
    buckets = [{"label": label, "count": counts[label]} for label, _, _ in _BUCKETS]
    peak = max(buckets, key=lambda b: b["count"]) if hours else None
    mean_h = circular_mean_hour(hours) if hours else None
    sd_h = circular_sd_hours(hours) if len(hours) >= 2 else None
    return {
        "mean_hour": round(mean_h, 2) if mean_h is not None else None,
        "sd_hour": round(sd_h, 2) if sd_h is not None else None,
        "peak_bucket": peak["label"] if peak and peak["count"] > 0 else None,
        "buckets": buckets,
    }


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def permutation_test(
    case: list[float],
    control: list[float],
    *,
    iterations: int = 5000,
) -> tuple[float | None, float | None]:
    """ケース群 vs 対照群の平均差の両側並べ替え検定。

    返り値 (p, observed_diff)。観測差 = mean(case) - mean(control)。
    データ不足 (どちらか空) は (None, None)。

    小サンプルでは全 |case| 通りの組合せを厳密列挙 (決定的・正確 p)。
    大きい場合は index ベースの決定的サンプリングにフォールバック。
    """
    if not case or not control:
        return None, None
    pooled = case + control
    n = len(pooled)
    k = len(case)
    observed = _mean(case) - _mean(control)
    abs_obs = abs(observed)

    # 厳密列挙が現実的なら全組合せ (C(n,k))。決定的で正確。
    from math import comb

    total_combos = comb(n, k)
    if total_combos <= iterations:
        count = 0
        for idx in combinations(range(n), k):
            sel = set(idx)
            cs = [pooled[i] for i in idx]
            ct = [pooled[i] for i in range(n) if i not in sel]
            diff = _mean(cs) - _mean(ct)
            if abs(diff) >= abs_obs - 1e-12:
                count += 1
        return count / total_combos, round(observed, 3)

    # フォールバック: 決定的な擬似シャッフル (線形合同で index を回す)
    count = 0
    a, c, m = 1103515245, 12345, 2**31
    seed = 0
    for _ in range(iterations):
        order = list(range(n))
        # Fisher-Yates with deterministic LCG
        for i in range(n - 1, 0, -1):
            seed = (a * seed + c) % m
            j = seed % (i + 1)
            order[i], order[j] = order[j], order[i]
        cs = [pooled[order[i]] for i in range(k)]
        ct = [pooled[order[i]] for i in range(k, n)]
        if abs(_mean(cs) - _mean(ct)) >= abs_obs - 1e-12:
            count += 1
    return count / iterations, round(observed, 3)


def benjamini_hochberg(pvalues: list[float]) -> list[float]:
    """Benjamini-Hochberg FDR 補正後の q 値 (入力と同じ順序で返す)。"""
    n = len(pvalues)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: pvalues[i])
    q = [0.0] * n
    prev = 1.0
    # 大きい順に単調化
    for rank in range(n, 0, -1):
        idx = order[rank - 1]
        val = min(prev, pvalues[idx] * n / rank)
        q[idx] = val
        prev = val
    return q
