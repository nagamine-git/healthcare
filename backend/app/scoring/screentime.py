"""スマホ依存の集計・シグナル (決定論的、LLM 不要)。

日サンプル (period_type=day) を主に、直近7日平均・前週比・エンタメ比率・
上位アプリ・目標超過を出す。純関数 summarize() をユニットテスト可能にする。
"""

from __future__ import annotations

from typing import Any

TARGET_DAILY_MIN = 180  # 目安: 1日3時間 (超過で注意喚起。娯楽系の置換を促す)
_ENTERTAINMENT_KEYS = ("entertainment", "娯楽", "エンタメ", "social", "ソーシャル")


def _is_entertainment(name: str) -> bool:
    low = name.lower()
    return any(k in low for k in _ENTERTAINMENT_KEYS)


def summarize(day_samples: list[dict[str, Any]], week_sample: dict[str, Any] | None) -> dict[str, Any]:
    """day_samples: [{period_start(ISO str), daily_min, categories, top_apps}] 新しい順想定。

    week_sample: 最新の週サンプル (前週比の相手) or None。
    """
    days = sorted(day_samples, key=lambda x: x["period_start"], reverse=True)
    if not days and not week_sample:
        return {"status": "no_data"}

    recent7 = days[:7]
    avg7 = round(sum(d["daily_min"] for d in recent7) / len(recent7)) if recent7 else None

    latest = days[0] if days else None
    latest_min = latest["daily_min"] if latest else None

    # エンタメ比率 (最新日のカテゴリから)
    ent_share = None
    ent_min = None
    if latest and latest.get("categories"):
        cats = latest["categories"] or {}
        total = sum(cats.values()) or (latest_min or 0)
        ent = sum(v for k, v in cats.items() if _is_entertainment(k))
        if total > 0:
            ent_min = round(ent)
            ent_share = round(ent / total * 100)

    # 上位アプリ (最新日、無ければ最新週)
    src_apps = (latest or {}).get("top_apps") or (week_sample or {}).get("top_apps") or []
    top_apps = sorted(src_apps, key=lambda a: a.get("minutes", 0), reverse=True)[:5]

    over_target = latest_min is not None and latest_min > TARGET_DAILY_MIN

    # トレンド: 直近日 vs 週日平均
    trend = None
    week_daily = (week_sample or {}).get("daily_min")
    if latest_min is not None and week_daily:
        diff = latest_min - week_daily
        trend = "up" if diff > 15 else ("down" if diff < -15 else "flat")

    return {
        "status": "ok",
        "latest_date": latest["period_start"] if latest else None,
        "latest_daily_min": latest_min,
        "avg7_min": avg7,
        "week_daily_min": week_daily,
        "trend": trend,
        "entertainment_min": ent_min,
        "entertainment_share_pct": ent_share,
        "top_apps": top_apps,
        "target_daily_min": TARGET_DAILY_MIN,
        "over_target": over_target,
        "n_days": len(days),
    }
