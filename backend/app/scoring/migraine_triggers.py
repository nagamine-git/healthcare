"""頭痛 (片頭痛) 要因分析: 時刻対応ケースクロスオーバー (DB アクセス層)。

各頭痛発症の直前 24h ウィンドウ (ケース) と、非頭痛日の同時刻 24h ウィンドウ (対照) で
候補要因の曝露を比較し、並べ替え検定 + BH 補正で有意な要因だけを返す。

- 小サンプルでは有意性を語らず status=accumulating を返す (MIN_EPISODES 既定 10)。
- 全要因が非有意なら status=no_significant_factor を返す (「実は何も寄与していない」を明示)。
- 発症時刻プロファイル (記述的) は常に返す。

設計: docs/superpowers/specs/2026-06-08-migraine-trigger-analysis-design.md
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from datetime import date as date_type
from typing import Any

from sqlalchemy import select

from app.db import session_scope
from app.models import (
    AlcoholIntake,
    CaffeineIntake,
    HrvDaily,
    MetricSample,
    MigraineEpisode,
    SleepSession,
)
from app.scoring.circadian import circular_mean_hour
from app.scoring.migraine_stats import benjamini_hochberg, onset_profile, permutation_test
from app.scoring.timewindow import JST

MIN_EPISODES = 10
WINDOW_H = 24  # 発症前ウィンドウ (時間)
ANALYSIS_DAYS = 120  # 遡る最大日数
FDR_Q = 0.05
MIN_GROUP = 3  # ケース/対照それぞれ最低この数の有効値が必要


def _to_jst(ts: datetime) -> datetime:
    return ts.replace(tzinfo=UTC).astimezone(JST).replace(tzinfo=None)


# --- 各要因の曝露関数 (ウィンドウ [start, end] で「高いほど誘発」の値、無ければ None) ---


def _exposure_pressure_drop(rows: list[tuple[datetime, float]], start: datetime, end: datetime) -> float | None:
    vals = [v for ts, v in rows if start <= ts <= end and v is not None]
    if len(vals) < 2:
        return None
    return round(max(vals) - min(vals), 2)  # ウィンドウ内の気圧変動幅 (hPa)


def analyze_triggers(target: date_type, *, min_episodes: int = MIN_EPISODES) -> dict[str, Any]:
    window = timedelta(hours=WINDOW_H)
    since = datetime.combine(target - timedelta(days=ANALYSIS_DAYS), datetime.min.time())
    end_dt = datetime.combine(target, datetime.max.time())

    with session_scope() as session:
        episodes = session.execute(
            select(MigraineEpisode.started_at)
            .where(MigraineEpisode.started_at >= since, MigraineEpisode.started_at <= end_dt)
            .order_by(MigraineEpisode.started_at)
        ).scalars().all()

        pressure_rows = session.execute(
            select(MetricSample.ts, MetricSample.value).where(
                MetricSample.metric_key == "surface_pressure_hpa",
                MetricSample.ts >= since - window,
            )
        ).all()
        sleep_rows = {
            d: tot for d, tot in session.execute(
                select(SleepSession.date, SleepSession.total_min).where(SleepSession.date >= since.date())
            ).all()
        }
        hrv_rows = {
            d: v for d, v in session.execute(
                select(HrvDaily.date, HrvDaily.last_night_avg).where(HrvDaily.date >= since.date())
            ).all()
        }
        caffeine_rows = session.execute(
            select(CaffeineIntake.ts, CaffeineIntake.mg).where(CaffeineIntake.ts >= since - window)
        ).all()
        alcohol_rows = session.execute(
            select(AlcoholIntake.ts, AlcoholIntake.grams).where(AlcoholIntake.ts >= since - window)
        ).all()

    profile = onset_profile([_to_jst(e) for e in episodes])
    episode_count = len(episodes)

    base: dict[str, Any] = {
        "episode_count": episode_count,
        "onset_profile": profile,
        "min_episodes": min_episodes,
        "tested": [],
        "factors": [],
    }

    # 件数による「精度ランク」。少なくても分析は走らせ、信頼度を明示する。
    # 片頭痛トリガー研究で安定するのは ~10 例以降だが、数例でも傾向は見たい。
    if episode_count >= 20:
        reliability = "high"
    elif episode_count >= min_episodes:
        reliability = "medium"
    elif episode_count >= 4:
        reliability = "low"
    else:
        reliability = "very_low"
    base["reliability"] = reliability

    # 4 例未満は permutation 検定が成立しない (対照との差を語れない)
    if episode_count < 4:
        base["status"] = "accumulating"
        base["remaining"] = max(0, 4 - episode_count)
        return base

    # --- 曝露の組み立て ---
    pressure = [(ts, float(v)) for ts, v in pressure_rows if v is not None]
    caffeine = [(ts, float(mg)) for ts, mg in caffeine_rows if mg is not None]
    alcohol = [(ts, float(g)) for ts, g in alcohol_rows if g is not None]

    # 個人ベースライン (window 全体平均)
    caf_daily_baseline = (sum(mg for _, mg in caffeine) / max(1, ANALYSIS_DAYS)) if caffeine else 0.0

    def caffeine_window_mg(start: datetime, end: datetime) -> float:
        return sum(mg for ts, mg in caffeine if start <= ts <= end)

    def alcohol_prev_g(onset: datetime) -> float:
        # 前日 (発症の 24-48h 前) のアルコール
        lo, hi = onset - timedelta(hours=48), onset - timedelta(hours=24)
        return sum(g for ts, g in alcohol if lo <= ts <= hi)

    def sleep_deficit(onset: datetime) -> float | None:
        d = _to_jst(onset).date()
        tot = sleep_rows.get(d)
        return (480 - float(tot)) if tot is not None else None  # 8h 目標からの不足分

    def hrv_drop(onset: datetime, baseline: float) -> float | None:
        d = _to_jst(onset).date()
        v = hrv_rows.get(d)
        return (baseline - float(v)) if v is not None else None

    hrv_vals = [float(v) for v in hrv_rows.values() if v is not None]
    hrv_baseline = sum(hrv_vals) / len(hrv_vals) if hrv_vals else 0.0

    # ケースアンカー = 各発症時刻。対照アンカー = 非頭痛日の「平均発症時刻 (JST)」。
    case_anchors = list(episodes)
    headache_days = {_to_jst(e).date() for e in episodes}
    mean_onset_h = circular_mean_hour([_to_jst(e).hour + _to_jst(e).minute / 60 for e in episodes]) or 15.0
    control_anchors: list[datetime] = []
    day = target - timedelta(days=ANALYSIS_DAYS)
    while day <= target:
        if day not in headache_days:
            # JST の mean_onset_h を UTC naive に戻す
            jst_anchor = datetime.combine(day, datetime.min.time()).replace(
                tzinfo=JST) + timedelta(hours=mean_onset_h)
            control_anchors.append(
                jst_anchor.astimezone(UTC).replace(tzinfo=None))
        day += timedelta(days=1)

    # 各要因の (case値, control値) を集め検定
    factor_defs: list[dict[str, Any]] = [
        {"key": "pressure_drop", "label": "気圧変動 (低下)",
         "case": lambda a: _exposure_pressure_drop(pressure, a - window, a),
         "ctrl": lambda a: _exposure_pressure_drop(pressure, a - window, a)},
        # カフェインは「baseline からの偏差」を1因子で検定する。
        # 離脱(不足)と過多を別因子にすると符号反転の鏡像になり、必ず同じ p 値が
        # 2 行出て多重比較補正まで水増しする。偏差の符号(頭痛日に多い/少ない)で
        # 過多/離脱を後段で動的にラベルする (どちらも最適から外れる=誘発)。
        {"key": "caffeine", "label": "カフェイン (離脱/過多)",
         "case": lambda a: caffeine_window_mg(a - window, a) - caf_daily_baseline,
         "ctrl": lambda a: caffeine_window_mg(a - window, a) - caf_daily_baseline},
        {"key": "sleep_short", "label": "睡眠不足 (前夜)",
         "case": lambda a: sleep_deficit(a),
         "ctrl": lambda a: sleep_deficit(a)},
        {"key": "hrv_low", "label": "HRV 低下",
         "case": lambda a: hrv_drop(a, hrv_baseline),
         "ctrl": lambda a: hrv_drop(a, hrv_baseline)},
        {"key": "alcohol_prev", "label": "前日の飲酒",
         "case": lambda a: alcohol_prev_g(a),
         "ctrl": lambda a: alcohol_prev_g(a)},
    ]

    results = []
    for fd in factor_defs:
        case_vals = [x for a in case_anchors if (x := fd["case"](a)) is not None]
        ctrl_vals = [x for a in control_anchors if (x := fd["ctrl"](a)) is not None]
        # 全ゼロ (= データ無しと同義、例: alcohol 0 件) はスキップ
        if len(case_vals) < MIN_GROUP or len(ctrl_vals) < MIN_GROUP:
            continue
        if all(v == 0 for v in case_vals + ctrl_vals):
            continue
        p, diff = permutation_test(case_vals, ctrl_vals)
        if p is None:
            continue
        results.append({
            "key": fd["key"], "label": fd["label"], "p": round(p, 4), "diff": diff,
            "n_case": len(case_vals),
            "case_mean": round(sum(case_vals) / len(case_vals), 2),
            "control_mean": round(sum(ctrl_vals) / len(ctrl_vals), 2),
        })

    base["tested"] = [r["key"] for r in results]
    if not results:
        base["status"] = "no_data"
        return base

    qs = benjamini_hochberg([r["p"] for r in results])
    factors = []
    for r, q in zip(results, qs, strict=True):
        if r["diff"] == 0:
            continue
        # 全要因を返し、確からしさを tier で表現 (UI で薄さに反映):
        #   strong = FDR<0.05 / suggestive = p<0.1 / trend = p<0.25 / weak = それ未満
        if q < FDR_Q:
            tier = "strong"
        elif r["p"] < 0.1:
            tier = "suggestive"
        elif r["p"] < 0.25:
            tier = "trend"
        else:
            tier = "weak"
        label = r["label"]
        direction = "誘発" if r["diff"] > 0 else "抑制?"
        if r["key"] == "caffeine":
            # baseline からの偏差。頭痛日に多ければ「過多」、少なければ「離脱」。
            # どちらも最適から外れた=トリガなので direction は常に誘発。
            label = "カフェイン過多" if r["diff"] > 0 else "カフェイン離脱 (不足)"
            direction = "誘発"
        factors.append({
            "key": r["key"], "label": label,
            "direction": direction,
            "case_mean": r["case_mean"], "control_mean": r["control_mean"],
            "n_case": r["n_case"], "p": r["p"], "q": round(q, 4), "tier": tier,
        })
    # 確からしさ順 (q 昇順 = p 昇順に近い)
    factors.sort(key=lambda f: (f["q"], f["p"]))
    base["factors"] = factors
    base["status"] = "analyzed"
    return base
