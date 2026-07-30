"""「時間あたりの回復効率」分析。DB非依存の純関数。

背景 (本人データ n=86夜で確認済み):
  相関 睡眠時間 → 翌朝BB : r≈+0.02 (説明力ほぼゼロ)
  相関 睡眠効率 → 翌朝BB : r≈+0.28 (時間より遥かに強い)
  時間帯別の翌朝BBは概ね 5.5-6.5h 付近をピークに頭打ちし、それ以上時間を伸ばしても
  この人のデータでは翌朝の回復指標(BB・活力)は伸びていない。

⚠️ **安全性の線 (最優先・絶対に外さない)**:
  BB・主観活力は「翌日の準備状態」を表す短期指標に過ぎない。慢性的な短時間睡眠が
  心血管・代謝・認知に与える悪影響は年単位で蓄積するため、数十〜百夜規模の観測には
  原理的に映らない。「これ以上時間を伸ばしても翌日の回復指標が伸びない」という事実と
  「短く寝る方が良い」は全く別の主張であり、後者を示唆する表現はここでは一切作らない。
  この module は常に「同じ睡眠時間からより多くの回復を引き出す (効率・深睡眠を上げる)」
  方向の情報だけを返し、睡眠時間の目標を下げる方向の助言は生成しない。
  夜数が薄いビン (n<`_RELIABLE_MIN_N`) は `reliable=False` とし、そこから結論を出さない。
"""

from __future__ import annotations

import math
from typing import Any

# 時間ビンの境界 (時間単位)。半時間 (30分) オフセットの1時間刻みにしているのは、
# 典型的な睡眠時間の整数値 (5h/6h/7h/8h) をビンの中央に収めるため
# (例: 6h は 5.5-6.5h ビンの中央に来る)。両端は開放 (「〜5.5h」「7.5h+」) にして
# データの分布がどこにあっても全ての夜を必ずどこかのビンに収める。
_BIN_EDGES_H: tuple[float, ...] = (5.5, 6.5, 7.5)

# このビンの夜数未満では「傾向」を語らない (薄いビンからの結論を防ぐ安全弁)。
_RELIABLE_MIN_N = 8

# 相関を出すのに最低限必要なペア数 (2点未満だと定義できず、3点未満だと分散が
# ほぼ意味を持たないため少なくとも3を要求する)。
_MIN_CORR_PAIRS = 3

# 「時間あたりの回復量」の上位/下位比較で見せる夜数の上限。
_TOP_BOTTOM_MAX = 5

CAVEATS: list[str] = [
    "ここでの「回復」は起床時ボディバッテリーや主観活力など、あくまで翌日の準備状態を"
    "表す短期指標です。長期の健康指標そのものではありません。",
    "慢性的な短時間睡眠が心血管・代謝・認知に与える悪影響は年単位で蓄積するため、"
    "数十〜百夜規模のこの観測には原理的に映りません。"
    "「これ以上時間を伸ばしても翌日の回復指標が伸びなかった」ことと"
    "「短く寝る方が良い」ことは全く別の話です。",
    "以下で示す「飽和点」はあくまで翌日の回復指標(BB・活力)での飽和であり、"
    "長期的な健康への影響とは別問題です。目標睡眠時間を自動で引き下げることはありません。",
    "夜数が少ないビンは「データ不足」として薄く表示しており、そこから結論は出していません。",
]


def _bin_label(lo: float | None, hi: float | None) -> str:
    if lo is None and hi is not None:
        return f"〜{hi:g}h"
    if hi is None and lo is not None:
        return f"{lo:g}h+"
    return f"{lo:g}-{hi:g}h"  # pragma: no cover (lo/hi どちらも None にはならない)


def _duration_bins(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """睡眠時間 (時間) のビン別に、夜数・平均翌朝BB・平均翌日活力を集計する。

    n はビンごとの夜数を必ず持たせ、`_RELIABLE_MIN_N` 未満なら `reliable=False`。
    """
    edges = _BIN_EDGES_H
    bounds: list[tuple[float | None, float | None]] = [(None, edges[0])]
    for i in range(len(edges) - 1):
        bounds.append((edges[i], edges[i + 1]))
    bounds.append((edges[-1], None))

    bins: list[dict[str, Any]] = []
    for lo, hi in bounds:
        n = 0
        bb_vals: list[float] = []
        energy_vals: list[float] = []
        for r in rows:
            dur = r.get("duration")
            if dur is None:
                continue
            h = dur / 60.0
            if lo is not None and h < lo:
                continue
            if hi is not None and h >= hi:
                continue
            n += 1
            if r.get("morning_bb") is not None:
                bb_vals.append(r["morning_bb"])
            if r.get("energy") is not None:
                energy_vals.append(r["energy"])
        bins.append({
            "label": _bin_label(lo, hi),
            "lower_h": lo,
            "upper_h": hi,
            "n": n,
            "reliable": n >= _RELIABLE_MIN_N,
            "avg_bb": round(sum(bb_vals) / len(bb_vals), 1) if bb_vals else None,
            "avg_energy": round(sum(energy_vals) / len(energy_vals), 2) if energy_vals else None,
        })
    return bins


def _saturation_point(bins: list[dict[str, Any]]) -> dict[str, Any] | None:
    """信頼できる(reliable)ビンの中で翌朝BBが最も高いビンを「飽和点」とみなす。

    最良ビンが最後の青天井ビン (例: 「7.5h+」) だった場合、データ範囲内では
    まだ伸びが続いている可能性があり「頭打ちを観測できた」とは言えないため
    `observed_within_range=False` を立てて呼び出し側に伝える
    (安全性の線: 薄い長時間ビンを根拠に「長く寝ても意味がない」と言わせない)。
    """
    reliable = [b for b in bins if b["reliable"] and b["avg_bb"] is not None]
    if len(reliable) < 2:
        return None
    best = max(reliable, key=lambda b: b["avg_bb"])
    return {
        "peak_bin": best["label"],
        "hours": best["upper_h"] if best["upper_h"] is not None else best["lower_h"],
        "avg_bb": best["avg_bb"],
        "observed_within_range": best["upper_h"] is not None,
    }


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < _MIN_CORR_PAIRS:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x <= 0 or var_y <= 0:
        return None
    return cov / math.sqrt(var_x * var_y)


def _correlation_to_bb(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    pairs = [
        (r[key], r["morning_bb"])
        for r in rows
        if r.get(key) is not None and r.get("morning_bb") is not None
    ]
    r = _pearson([p[0] for p in pairs], [p[1] for p in pairs])
    return {"r": round(r, 3) if r is not None else None, "n": len(pairs)}


def _per_hour_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """「1時間あたりの回復量」(翌朝BB / 睡眠時間h) を夜ごとに出し、上位/下位を比較する。

    どういう夜が時間対効果が良かったかを見るための材料として、上位/下位グループの
    平均効率・平均深睡眠も添える (「時間より効率」を具体的な数字で見せるため)。
    """
    entries: list[dict[str, Any]] = []
    for r in rows:
        dur = r.get("duration")
        bb = r.get("morning_bb")
        if not dur or dur <= 0 or bb is None:
            continue
        hours = dur / 60.0
        entries.append({
            "duration_h": round(hours, 2),
            "bb_per_hour": round(bb / hours, 2),
            "morning_bb": bb,
            "efficiency": r.get("efficiency"),
            "deep_min": r.get("deep_min"),
        })

    empty = {
        "n": 0, "top": [], "bottom": [],
        "top_avg_efficiency": None, "bottom_avg_efficiency": None,
        "top_avg_deep_min": None, "bottom_avg_deep_min": None,
    }
    if not entries:
        return empty

    entries.sort(key=lambda e: -e["bb_per_hour"])
    n = len(entries)
    k = min(_TOP_BOTTOM_MAX, max(1, n // 2)) if n >= 2 else n
    top = entries[:k]
    bottom = entries[-k:] if n > k else []

    def _avg(vals: list[float | None]) -> float | None:
        clean = [v for v in vals if v is not None]
        return round(sum(clean) / len(clean), 1) if clean else None

    return {
        "n": n, "top": top, "bottom": bottom,
        "top_avg_efficiency": _avg([e["efficiency"] for e in top]),
        "bottom_avg_efficiency": _avg([e["efficiency"] for e in bottom]),
        "top_avg_deep_min": _avg([e["deep_min"] for e in top]),
        "bottom_avg_deep_min": _avg([e["deep_min"] for e in bottom]),
    }


def _extract_drivers(driver_quality: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """`sleep_drivers.analyze()` の quality 結果から、時間ではなく効率・深睡眠を
    上げ下げする要因だけを抜き出す (統計は再実装せず再利用する)。

    quality は呼び出し元 (sleep_drivers.analyze) 側で既に確度順にソート済みなので
    その順序をそのまま使う。
    """
    return [f for f in driver_quality if f.get("outcome") in ("efficiency", "deep_min")][:5]


def analyze_recovery_efficiency(
    rows: list[dict[str, Any]],
    driver_quality: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """「時間あたりの回復効率」の分析結果を返す。

    rows は `sleep_drivers._collect()` と同じ形の dict のリスト
    (duration/morning_bb/energy/efficiency/deep_min 等)。
    driver_quality は `sleep_drivers.analyze()` の結果の `quality` (省略可)。
    """
    bins = _duration_bins(rows)
    return {
        "n_nights": len(rows),
        "per_hour": _per_hour_summary(rows),
        "saturation": {
            "bins": bins,
            "peak": _saturation_point(bins),
        },
        "correlations": {
            "duration": _correlation_to_bb(rows, "duration"),
            "efficiency": _correlation_to_bb(rows, "efficiency"),
            "deep_min": _correlation_to_bb(rows, "deep_min"),
        },
        "drivers": _extract_drivers(driver_quality or []),
        "caveat": CAVEATS,
    }
