"""「今日の流れ」タイムライン用の集約 API。

時刻を持つ全データを 1 本の帯 (横軸 0-span 時間) に正規化して返す。
ウィンドウは 2 種類:
  - window=day  : JST 暦日 (00:00-24:00)。日付指定可。
  - window=24h  : 直近 24 時間 (日付をまたぐ。深夜でも空にならない)。
クライアントは offset(0-span) をそのまま SVG の x にマップできる。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.db import session_scope
from app.models import (
    BodyBattery,
    CaffeineIntake,
    MetricSample,
    MigraineEpisode,
    SleepSession,
    SubjectiveCheckin,
    Workout,
)
from app.scoring.timewindow import app_today, jst_day_bounds

router = APIRouter()
JST = ZoneInfo("Asia/Tokyo")
SPAN_H = 24.0
# 24h ビューの構成: 過去21h + 未来3h (= 予測の精度が保てる範囲)
FUTURE_PAST_H = 21.0
FUTURE_AHEAD_H = 3.0


def _resolve_window(window: str, date: str | None):
    """(origin_utc_naive, start_utc, end_utc, now_off, date_label, origin_jst) を返す。

    offset = (ts_utc - origin_utc) 時間。x 軸は常に 0..SPAN_H。
    """
    from datetime import date as date_type

    now_jst = datetime.now(JST)
    if window == "24h":
        # 直近 21h + 未来 3h の窓。右端に未来枠を作り、予測可能な系列
        # (カフェイン減衰・集中窓) だけが現在線の右に伸びる。
        origin_jst = now_jst - timedelta(hours=FUTURE_PAST_H)
        end_jst = now_jst + timedelta(hours=FUTURE_AHEAD_H)
        start_utc = origin_jst.astimezone(UTC).replace(tzinfo=None)
        end_utc = end_jst.astimezone(UTC).replace(tzinfo=None)
        return start_utc, start_utc, end_utc, FUTURE_PAST_H, None, origin_jst
    # 暦日
    target = date_type.fromisoformat(date) if date else app_today()
    start_utc, end_utc = jst_day_bounds(target)
    origin_jst = datetime(target.year, target.month, target.day, tzinfo=JST)
    now_off = (now_jst.astimezone(UTC).replace(tzinfo=None) - start_utc).total_seconds() / 3600
    now_off = round(now_off, 2) if 0 <= now_off <= SPAN_H else None
    return start_utc, start_utc, end_utc, now_off, target.isoformat(), origin_jst


def _offsetter(origin_utc: datetime):
    def off(ts_naive_utc: datetime) -> float:
        h = (ts_naive_utc - origin_utc).total_seconds() / 3600
        return round(max(0.0, min(SPAN_H, h)), 2)
    return off


def _sleep_blocks(session, start_utc, end_utc, off) -> list[dict[str, float]]:
    """ウィンドウに重なる睡眠ブロックを絶対時刻で復元して offset 化。

    睡眠は (date, midpoint_hour, total_min) から絶対時刻を組み立てる。
    midpoint は date の早朝 (0-9時想定) に属するものとして date 00:00 + midpoint。
    """
    # ウィンドウが触れる JST 日付 ± 1 を候補に
    start_jst = start_utc.replace(tzinfo=UTC).astimezone(JST).date()
    end_jst = end_utc.replace(tzinfo=UTC).astimezone(JST).date()
    cand = {start_jst, end_jst, start_jst + timedelta(days=1)}
    blocks: list[dict[str, float]] = []
    for d in sorted(cand):
        total_min = session.execute(
            select(SleepSession.total_min).where(SleepSession.date == d)
        ).scalar()
        d_start, d_end = jst_day_bounds(d)
        midpoint = session.execute(
            select(MetricSample.value).where(
                MetricSample.metric_key == "sleep_midpoint_hour",
                MetricSample.ts >= d_start,
                MetricSample.ts < d_end,
            )
        ).scalar()
        if not total_min or midpoint is None:
            continue
        mid_jst = datetime(d.year, d.month, d.day, tzinfo=JST) + timedelta(hours=float(midpoint))
        half = timedelta(minutes=float(total_min) / 2)
        s_utc = (mid_jst - half).astimezone(UTC).replace(tzinfo=None)
        e_utc = (mid_jst + half).astimezone(UTC).replace(tzinfo=None)
        if e_utc <= start_utc or s_utc >= end_utc:
            continue
        blocks.append({"start_h": off(s_utc), "end_h": off(e_utc)})
    return blocks


def _gather(start_utc, end_utc, off) -> dict[str, Any]:
    """ウィンドウ内の全シリーズを offset 化して返す (両エンドポイント共通)。"""
    out: dict[str, Any] = {}
    with session_scope() as session:
        bb = session.execute(
            select(BodyBattery.ts, BodyBattery.value)
            .where(BodyBattery.ts >= start_utc, BodyBattery.ts < end_utc, BodyBattery.value.isnot(None))
            .order_by(BodyBattery.ts)
        ).all()
        out["body_battery"] = [{"h": off(t), "v": float(v)} for t, v in bb]

        def metric(key: str):
            return session.execute(
                select(MetricSample.ts, MetricSample.value).where(
                    MetricSample.metric_key == key,
                    MetricSample.value >= 0,
                    MetricSample.ts >= start_utc,
                    MetricSample.ts < end_utc,
                ).order_by(MetricSample.ts)
            ).all()

        out["stress"] = [{"h": off(t), "v": float(v)} for t, v in metric("stress")]
        out["_steps"] = [(off(t), float(v)) for t, v in metric("step_count")]
        hr_pairs = [(off(t), float(v)) for t, v in metric("heart_rate_avg")]
        out["_hr"] = hr_pairs
        out["heart_rate"] = [{"h": h, "v": v} for h, v in hr_pairs]
        out["_energy"] = [(off(t), float(v)) for t, v in metric("active_energy")]

        out["sleep_blocks"] = _sleep_blocks(session, start_utc, end_utc, off)

        wk = session.execute(
            select(Workout.start, Workout.end, Workout.type, Workout.duration_s)
            .where(Workout.start >= start_utc, Workout.start < end_utc).order_by(Workout.start)
        ).all()
        out["workouts"] = [
            {"start_h": off(s), "end_h": off(e) if e else off(s + timedelta(seconds=dur or 1800)),
             "type": ty}
            for s, e, ty, dur in wk
        ]

        caff = session.execute(
            select(CaffeineIntake.ts, CaffeineIntake.mg, CaffeineIntake.source)
            .where(CaffeineIntake.ts >= start_utc, CaffeineIntake.ts < end_utc).order_by(CaffeineIntake.ts)
        ).all()
        out["caffeine"] = [{"h": off(t), "mg": float(mg), "source": src} for t, mg, src in caff]

        eps = session.execute(
            select(MigraineEpisode.started_at, MigraineEpisode.ended_at, MigraineEpisode.severity)
            .where(
                MigraineEpisode.started_at < end_utc,
                (MigraineEpisode.ended_at.is_(None)) | (MigraineEpisode.ended_at >= start_utc),
            )
        ).all()
        out["migraine"] = [
            {"start_h": off(s), "end_h": off(e) if e else None, "severity": sev}
            for s, e, sev in eps
        ]

        ck_rows = session.execute(
            select(SubjectiveCheckin).where(SubjectiveCheckin.date >= start_utc.date() - timedelta(days=1))
        ).scalars().all()
        checkin = None
        for ck in ck_rows:
            if ck.updated_at and start_utc <= ck.updated_at < end_utc:
                checkin = {
                    "h": off(ck.updated_at), "mood": ck.mood, "energy": ck.energy,
                    "stress": ck.stress, "soreness": ck.soreness,
                }
        out["checkin"] = checkin

        rhr = session.execute(
            select(MetricSample.value).where(MetricSample.metric_key == "resting_heart_rate")
            .order_by(MetricSample.ts.desc()).limit(1)
        ).scalar()
        out["_resting_hr"] = float(rhr) if rhr is not None else None

        def daily(key: str) -> float:
            v = session.execute(
                select(MetricSample.value).where(
                    MetricSample.metric_key == key,
                    MetricSample.ts >= start_utc, MetricSample.ts < end_utc,
                ).order_by(MetricSample.ts.desc()).limit(1)
            ).scalar()
            return float(v) if v is not None else 0.0

        out["_intensity"] = (daily("intensity_minutes_moderate"), daily("intensity_minutes_vigorous"))
    return out


def _caffeine_curve(origin_utc, start_utc, end_utc, off):
    """体内カフェイン残量 (mg) の推移を 15分刻みで返す。1コンパートメント PK。

    ウィンドウ開始前 (最大18h) の摂取も残存するので遡って取得する。
    閾値 = 就寝時に血中濃度 0.5mg/L を超えない残量 (mg) = threshold * Vd * 体重。
    """
    from app.config import get_settings
    from app.scoring.caffeine import half_life_decay
    from app.scoring.profile import resolve_profile

    s = get_settings()
    half_life = s.caffeine_half_life_h
    lookback = (start_utc - timedelta(hours=18))
    with session_scope() as session:
        intakes = session.execute(
            select(CaffeineIntake.ts, CaffeineIntake.mg)
            .where(CaffeineIntake.ts >= lookback, CaffeineIntake.ts < end_utc, CaffeineIntake.mg > 0)
        ).all()
    if not intakes:
        return [], None

    points: list[dict[str, float]] = []
    step = timedelta(minutes=15)
    cur = start_utc
    while cur <= end_utc:
        total = 0.0
        for ts, mg in intakes:
            elapsed_h = (cur - ts).total_seconds() / 3600
            if elapsed_h >= 0:
                total += half_life_decay(float(mg), elapsed_h, half_life_h=half_life)
        points.append({"h": off(cur), "mg": round(total, 1)})
        cur += step

    prof = resolve_profile()
    weight = prof.target_weight_kg or 60.0
    # 当日 (origin の JST 日付) の摂取合計 = 1日上限 (EFSA 400mg) と比較する量
    day_start = origin_utc.replace(tzinfo=UTC).astimezone(JST)
    day_start = day_start.replace(hour=0, minute=0, second=0, microsecond=0)
    day_s = day_start.astimezone(UTC).replace(tzinfo=None)
    day_e = day_s + timedelta(days=1)
    today_total = round(sum(float(mg) for ts, mg in intakes if day_s <= ts < day_e))
    info = {
        # 就寝安全: 血中 0.5mg/L (Drake 2013) 相当の体内残量
        "bedtime_safe_mg": round(s.caffeine_bedtime_threshold_mg_per_l * s.caffeine_vd_l_per_kg * weight, 1),
        # 覚醒効果の下限: 最低有効量 ~1mg/kg (Smith 2002 メタ解析)。これ以上残れば効果継続
        "alert_floor_mg": round(s.caffeine_min_cognitive_mg, 1),
        # 1日摂取の安全上限 (EFSA 2015: 健常成人 400mg/日)
        "today_total_mg": today_total,
        "daily_limit_mg": 400,
    }
    return points, info


def _hhmm_to_off(hhmm: str, origin_utc, off) -> float | None:
    """'HH:MM' (JST) を、ウィンドウ origin の JST 日付に合わせて offset 化。"""
    try:
        h, _, m = hhmm.partition(":")
        origin_jst = origin_utc.replace(tzinfo=UTC).astimezone(JST)
        # origin と同じ日付の HH:MM。HH < origin の時 (日跨ぎ) は翌日扱い
        cand = origin_jst.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
        if cand < origin_jst:
            cand = cand + timedelta(days=1)
        return off(cand.astimezone(UTC).replace(tzinfo=None))
    except Exception:
        return None


def _context_windows(target, origin_utc, start_utc, end_utc, off, g):
    """同一時間軸に重ねる「文脈ウィンドウ」: 集中ピーク窓 / 就寝(メラトニン)窓 / 回復ゾーン。"""
    from datetime import time as _time

    from app.config import get_settings
    from app.models import HrvDaily
    from app.scoring.focus import extract_peak_windows, predict_today_curve
    from app.scoring.recompute import _hrv_baseline
    from app.scoring.sleep_plan import compute_tonight_plan

    s = get_settings()
    now_jst = datetime.now(JST)
    out: dict[str, Any] = {"focus_windows": [], "sleep_window": None, "recovery_bands": []}

    # --- 集中ピーク窓 (現在以降の予測。今日のみ意味を持つ) ---
    try:
        with session_scope() as session:
            hrv = session.get(HrvDaily, target)
            sleep = session.get(SleepSession, target)
            bb_cur = session.execute(
                select(BodyBattery.value).where(BodyBattery.ts < end_utc)
                .order_by(BodyBattery.ts.desc()).limit(1)
            ).scalar()
            since = now_jst.astimezone(UTC).replace(tzinfo=None) - timedelta(minutes=60)
            srows = session.execute(
                select(MetricSample.value).where(
                    MetricSample.metric_key == "stress", MetricSample.ts >= since,
                    MetricSample.value >= 0,
                )
            ).all()
            stress_recent = sum(float(r[0]) for r in srows) / len(srows) if srows else None
            baseline = _hrv_baseline(session, target)
        wake_t = None
        try:
            h, _, m = s.target_wake_time.partition(":")
            wake_t = _time(int(h), int(m))
        except Exception:
            wake_t = None
        curve = predict_today_curve(
            now=now_jst, hrv_value=hrv.last_night_avg if hrv else None, hrv_baseline=baseline,
            body_battery_current=float(bb_cur) if bb_cur is not None else None,
            stress_recent_avg=stress_recent,
            sleep_score=sleep.sleep_score if sleep else None,
            sleep_total_min=sleep.total_min if sleep else None, wake_time=wake_t,
        )
        for w in extract_peak_windows(curve):
            so = _hhmm_to_off(w.start, origin_utc, off)
            eo = _hhmm_to_off(w.end, origin_utc, off)
            if so is not None and eo is not None and eo > so:
                out["focus_windows"].append({"start_h": so, "end_h": eo, "score": round(w.avg_score)})
    except Exception:
        pass

    # --- 就寝/メラトニン窓 (メラトニン上昇 ≈ 就寝2h前 〜 就寝) ---
    try:
        plan = compute_tonight_plan(target)
        bed = _hhmm_to_off(plan["bedtime"], origin_utc, off)
        if bed is not None:
            out["sleep_window"] = {"melatonin_h": max(0.0, bed - 2.0), "bedtime_h": bed}
    except Exception:
        pass

    # --- 回復ゾーン (Garmin ストレス安息帯 <26 が続く時間 = 副交感優位) ---
    rec: list[dict[str, float]] = []
    cur_start: float | None = None
    for p in g["stress"]:
        if p["v"] < 26:
            if cur_start is None:
                cur_start = p["h"]
            last = p["h"]
        else:
            if cur_start is not None and last - cur_start >= 0.5:
                rec.append({"start_h": cur_start, "end_h": last})
            cur_start = None
    if cur_start is not None and g["stress"] and g["stress"][-1]["h"] - cur_start >= 0.5:
        rec.append({"start_h": cur_start, "end_h": g["stress"][-1]["h"]})
    out["recovery_bands"] = rec
    return out


def _water_curve(target, origin_utc, start_utc, end_utc, off, energy_pairs):
    """水分の累積摂取カーブ (実測スナップショット) + 目標・発汗・収支。

    個別飲水の時刻ログは Garmin/HAE とも取れないため、同期ごとの累積総量
    (hydration_cumulative_ml) を時系列化して摂取カーブを近似する。発汗は
    Garmin の sweatLossInML (実測) を活動量で時間配分し、収支を出す。
    """
    import json as _json

    from app.scoring.profile import resolve_profile

    with session_scope() as session:
        snaps = session.execute(
            select(MetricSample.ts, MetricSample.value).where(
                MetricSample.metric_key == "hydration_cumulative_ml",
                MetricSample.ts >= start_utc, MetricSample.ts < end_utc,
                MetricSample.value.isnot(None),
            ).order_by(MetricSample.ts)
        ).all()
        # 目標・発汗 (当日の Garmin hydration raw_json)
        d_start, d_end = jst_day_bounds(target)
        hyd = session.execute(
            select(MetricSample.value, MetricSample.raw_json).where(
                MetricSample.metric_key == "garmin_hydration_ml",
                MetricSample.ts >= d_start, MetricSample.ts < d_end,
            ).order_by(MetricSample.ts.desc()).limit(1)
        ).first()
        # HAE フォールバック (Garmin が無い日)
        hae = None
        if not hyd:
            hae = session.execute(
                select(func.sum(MetricSample.value)).where(
                    MetricSample.metric_key == "dietary_water",
                    MetricSample.ts >= d_start, MetricSample.ts < d_end,
                )
            ).scalar()

    intake_total = None
    goal_ml = None
    sweat_ml = 0.0
    if hyd:
        intake_total = float(hyd[0]) if hyd[0] is not None else None
        raw = hyd[1]
        if isinstance(raw, str):
            try:
                raw = _json.loads(raw)
            except Exception:
                raw = {}
        if isinstance(raw, dict):
            goal_ml = float(raw.get("goalInML")) if raw.get("goalInML") else None
            sweat_ml = float(raw.get("sweatLossInML") or 0.0)
    elif hae is not None:
        intake_total = float(hae)

    if intake_total is None and not snaps:
        return None, None

    prof = resolve_profile()
    weight = prof.target_weight_kg or 60.0
    # ベースライン水分損失 (発汗以外: 尿・不感蒸泄) ≈ 1.5L/日 を 24h に配分
    baseline_per_h = 1500.0 / 24.0
    if goal_ml is None and weight:
        goal_ml = round(weight * 35.0)  # 35ml/kg/日 の目安

    # 摂取カーブ: スナップショット (実測累積) を段階線に。なければ末尾に総量1点
    intake_pts = [{"h": off(t), "ml": float(v)} for t, v in snaps]
    if not intake_pts and intake_total is not None:
        intake_pts = [{"h": off(end_utc - timedelta(minutes=1)), "ml": intake_total}]

    out = {
        "intake_curve": intake_pts,
        "intake_total_ml": round(intake_total) if intake_total is not None else None,
        "goal_ml": round(goal_ml) if goal_ml else None,
        "sweat_ml": round(sweat_ml),
        "source": "garmin" if hyd else ("hae" if hae is not None else None),
    }
    return out, baseline_per_h


def _prediction_text(now_off, caffeine_curve, caf_info, pressure_curve, ctx) -> str | None:
    """予測可能な系列 (カフェイン消失・気圧3h・集中窓) を 1-2 文の予測文に。"""
    import math

    from app.config import get_settings

    now_jst = datetime.now(JST)
    parts: list[str] = []

    # カフェイン: 就寝安全域に入る時刻 (半減期で解析的に算出)
    if caffeine_curve and caf_info and now_off is not None:
        near = min(caffeine_curve, key=lambda p: abs(p["h"] - now_off))
        now_mg = near["mg"]
        safe = caf_info.get("bedtime_safe_mg")
        if safe and now_mg > safe:
            s = get_settings()
            t_h = s.caffeine_half_life_h * math.log2(now_mg / safe)
            if 0 < t_h <= 14:
                clk = now_jst + timedelta(hours=t_h)
                parts.append(f"カフェインは{clk.strftime('%H:%M')}頃に就寝安全域へ")

    # 気圧: 未来3hの変化
    if pressure_curve and now_off is not None:
        fut = [p for p in pressure_curve if p["h"] > now_off]
        cur = min(pressure_curve, key=lambda p: abs(p["h"] - now_off))["hpa"]
        if fut:
            d = round(fut[-1]["hpa"] - cur, 1)
            if d <= -3:
                parts.append(f"気圧が3時間で{d}hPa低下 (頭痛注意)")
            elif d <= -1.5:
                parts.append(f"気圧やや低下 ({d}hPa/3h)")

    # 集中ピーク窓 (これからの分)
    fw = [w for w in (ctx.get("focus_windows") or []) if now_off is None or w["end_h"] > now_off]
    if fw:
        w = fw[0]
        s_clk = now_jst + timedelta(hours=w["start_h"] - (now_off or 0))
        e_clk = now_jst + timedelta(hours=w["end_h"] - (now_off or 0))
        if w["start_h"] >= (now_off or 0):
            parts.append(f"集中しやすいのは{s_clk.strftime('%H:%M')}〜{e_clk.strftime('%H:%M')}")
        else:
            parts.append(f"いま集中ピーク (〜{e_clk.strftime('%H:%M')})")

    return "／".join(parts) if parts else None


def _pressure_curve(start_utc, end_utc, off):
    """毎時の気圧 (実測+予報) を window に合わせて offset 化。片頭痛トリガーの可視化。

    Open-Meteo は JST naive 時刻を返すので UTC naive に変換して窓で絞る。
    予報を含むので未来枠 (現在線の右) に気圧トレンドが伸びる。
    """
    from app.integrations.weather import get_pressure_hourly

    try:
        series = get_pressure_hourly()
    except Exception:
        return []
    out: list[dict[str, float]] = []
    for jst_naive, hpa in series:
        utc_naive = jst_naive - timedelta(hours=9)  # JST → UTC
        if start_utc <= utc_naive < end_utc:
            out.append({"h": off(utc_naive), "hpa": round(hpa, 1)})
    return out


def _bin_steps(step_pairs, bin_h: float = 0.25):
    """歩数を bin_h 時間ごとに集計 (運動量バー用)。"""
    bins: dict[int, float] = {}
    for h, v in step_pairs:
        idx = int(h / bin_h)
        bins[idx] = bins.get(idx, 0.0) + v
    return [{"h": round(i * bin_h + bin_h / 2, 2), "steps": round(v)} for i, v in sorted(bins.items())]


def _forecast_curves(g: dict[str, Any], now_off: float | None) -> dict[str, list[dict[str, float]]]:
    """未来ゾーン (now → SPAN_H) の心拍・Body Battery を予測して埋める。

    - Body Battery: 直近2hの最小二乗スロープを線形外挿 (消耗トレンドの継続)。
    - 心拍: 安静時心拍へ指数的に減衰 (安静を仮定。運動すれば外れる低確度の見通し)。
    どちらも実測ではない予測。フロントは破線+薄色で「予測ゾーン」に描く。
    """
    import math

    out: dict[str, list[dict[str, float]]] = {"body_battery": [], "heart_rate": [], "stress": []}
    if now_off is None:
        return out
    step = 0.25

    def ls_slope(pts: list[tuple[float, float]]) -> float:
        n = len(pts)
        mx = sum(p[0] for p in pts) / n
        my = sum(p[1] for p in pts) / n
        denom = sum((p[0] - mx) ** 2 for p in pts)
        return sum((p[0] - mx) * (p[1] - my) for p in pts) / denom if denom else 0.0

    def ease_curve(pairs, target, tau, clamp_lo, clamp_hi):
        """最後の実測 → target へ tau[h] で指数的に戻る曲線を SPAN_H まで。"""
        if not pairs:
            return []
        h0, v0 = pairs[-1]
        if h0 >= SPAN_H:
            return []
        pts = []
        h = h0
        while h <= SPAN_H + 1e-6:
            v = target + (v0 - target) * math.exp(-(h - h0) / tau)
            pts.append({"h": round(h, 2), "v": round(max(clamp_lo, min(clamp_hi, v)), 1)})
            h += step
        return pts

    bb = [(p["h"], p["v"]) for p in (g.get("body_battery") or [])]
    hr = g.get("_hr") or []
    stress = [(p["h"], p["v"]) for p in (g.get("stress") or [])]
    rest = g.get("_resting_hr")

    # 直近データからの経過 (= ギャップ)。長い=未装着/同期遅れ → 休息ベースラインへ戻す。
    last_h = max((p[0] for p in (bb + hr + stress)), default=None)
    stale = last_h is not None and (now_off - last_h) > 2.0

    # Body Battery: 鮮度高→直近スロープで短時間外挿、古い→休息で典型(~60)へ回復
    if len(bb) >= 3:
        if stale:
            out["body_battery"] = ease_curve(bb, 60.0, 3.0, 5.0, 100.0)
        else:
            slope = ls_slope(bb[-4:])
            h0, v0 = bb[-1]
            if h0 < SPAN_H:
                h = h0
                while h <= SPAN_H + 1e-6:
                    v = max(5.0, min(100.0, v0 + slope * (h - h0)))
                    out["body_battery"].append({"h": round(h, 2), "v": round(v, 1)})
                    h += step

    # 心拍: 安静時心拍へ tau=1h で戻る
    if hr and rest is not None:
        out["heart_rate"] = ease_curve(hr, rest, 1.0, 30.0, 200.0)

    # ストレス: 休息レベル(~22)へ tau=2h で戻る
    if stress:
        out["stress"] = ease_curve(stress, 22.0, 2.0, 0.0, 100.0)
    return out


def _gather_events(start_utc, end_utc, off) -> list[dict[str, Any]]:
    """カレンダー予定 (gcal 未設定なら空)。ウィンドウが触れる JST 日付を走査。終日除外。"""
    start_jst_d = start_utc.replace(tzinfo=UTC).astimezone(JST).date()
    end_jst_d = end_utc.replace(tzinfo=UTC).astimezone(JST).date()
    dates = {start_jst_d, end_jst_d}
    events: list[dict[str, Any]] = []
    try:
        from app.integrations.gcal import list_events_for_date

        for d in sorted(dates):
            for e in list_events_for_date(d):
                s, en = e.get("start") or "", e.get("end") or ""
                if len(s) <= 10 or len(en) <= 10:
                    continue
                sd = datetime.fromisoformat(s).astimezone(UTC).replace(tzinfo=None)
                ed = datetime.fromisoformat(en).astimezone(UTC).replace(tzinfo=None)
                if ed <= start_utc or sd >= end_utc:
                    continue
                events.append({"start_h": off(sd), "end_h": off(ed), "title": e.get("summary") or "予定"})
    except Exception:
        pass
    return events


@router.get("/api/timeline")
async def day_timeline(
    date: str | None = Query(default=None),
    window: str = Query(default="day"),
) -> dict[str, Any]:
    origin_utc, start_utc, end_utc, now_off, date_label, origin_jst = _resolve_window(window, date)
    off = _offsetter(origin_utc)
    g = _gather(start_utc, end_utc, off)

    # 主観チェックインが無い時間帯用の「推定主観」(客観指標から)。補完表示用
    from datetime import date as date_type

    from app.api.checkin import _objective_suggestions

    est_date = date_type.fromisoformat(date_label) if date_label else app_today()
    try:
        checkin_estimated = _objective_suggestions(est_date)
    except Exception:
        checkin_estimated = None

    caffeine_curve, caf_info = _caffeine_curve(origin_utc, start_utc, end_utc, off)
    pressure_curve = _pressure_curve(start_utc, end_utc, off)
    ctx = _context_windows(est_date, origin_utc, start_utc, end_utc, off, g)
    water, _ = _water_curve(est_date, origin_utc, start_utc, end_utc, off, g["_energy"])
    prediction_text = _prediction_text(now_off, caffeine_curve, caf_info, pressure_curve, ctx)
    _fc = _forecast_curves(g, now_off)

    return {
        "window": window,
        "date": date_label,
        "origin_jst": origin_jst.isoformat(),
        "span_h": SPAN_H,
        "now_h": now_off,
        "body_battery": g["body_battery"],
        "stress": g["stress"],
        "heart_rate": g["heart_rate"],
        "heart_rate_forecast": _fc["heart_rate"],
        "body_battery_forecast": _fc["body_battery"],
        "stress_forecast": _fc["stress"],
        "resting_hr": g["_resting_hr"],
        "steps_binned": _bin_steps(g["_steps"]),
        "sleep_blocks": g["sleep_blocks"],
        "workouts": g["workouts"],
        "caffeine": g["caffeine"],
        "migraine": g["migraine"],
        "checkin": g["checkin"],
        "checkin_estimated": checkin_estimated,
        "caffeine_curve": caffeine_curve,
        "caffeine_bedtime_safe_mg": caf_info["bedtime_safe_mg"] if caf_info else None,
        "caffeine_alert_floor_mg": caf_info["alert_floor_mg"] if caf_info else None,
        "caffeine_today_mg": caf_info["today_total_mg"] if caf_info else None,
        "caffeine_daily_limit_mg": caf_info["daily_limit_mg"] if caf_info else None,
        "pressure_curve": pressure_curve,
        "prediction_text": prediction_text,
        "focus_windows": ctx["focus_windows"],
        "sleep_window": ctx["sleep_window"],
        "recovery_bands": ctx["recovery_bands"],
        "water": water,
        "events": _gather_events(start_utc, end_utc, off),
    }


@router.get("/api/day-story")
async def day_story(
    date: str | None = Query(default=None),
    window: str = Query(default="day"),
) -> dict[str, Any]:
    from app.scoring.day_story import build_day_story

    origin_utc, start_utc, end_utc, now_off, date_label, origin_jst = _resolve_window(window, date)
    off = _offsetter(origin_utc)
    g = _gather(start_utc, end_utc, off)
    events = _gather_events(start_utc, end_utc, off)

    # 睡眠ブロックは複数あり得るが、build_day_story は1つ想定 → 最長を渡す
    sleep = max(g["sleep_blocks"], key=lambda b: b["end_h"] - b["start_h"], default=None)

    story = build_day_story(
        now_h=now_off,
        sleep=sleep,
        workouts=g["workouts"],
        events=events,
        steps=g["_steps"],
        heart_rate=g["_hr"],
        stress=[(p["h"], p["v"]) for p in g["stress"]],
        body_battery=[(p["h"], p["v"]) for p in g["body_battery"]],
        active_energy=g["_energy"],
        intensity_min=g["_intensity"],
        resting_hr=g["_resting_hr"],
    )
    # クイック統計 (情報量を補う数値サマリ)
    stress_vals = [p["v"] for p in g["stress"]]
    mod, vig = g["_intensity"]
    story["stats"] = {
        "steps": int(sum(v for _, v in g["_steps"])),
        "active_kcal": round(sum(v for _, v in g["_energy"])),
        "sleep_h": round(sleep["end_h"] - sleep["start_h"], 1) if sleep else None,
        "stress_avg": round(sum(stress_vals) / len(stress_vals)) if stress_vals else None,
        "caffeine_mg": round(sum(c["mg"] for c in g["caffeine"])),
        "intensity_min": int(mod + vig),
    }
    story["window"] = window
    story["date"] = date_label
    story["origin_jst"] = origin_jst.isoformat()
    story["span_h"] = SPAN_H
    story["now_h"] = now_off
    return story
