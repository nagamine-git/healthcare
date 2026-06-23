"""未来予測 (forecast)。確度の高い順に複数の見通しを返す。

階層 (確度):
- 【高】片頭痛リスク予報 (24-48h): 検証済み個人トリガー(気圧変動) × Open-Meteo の48h気圧予報。
- 【中】今日この先のエネルギー(Body Battery)推移: 直近の消耗スロープから枯渇時刻を外挿。
- 【低】明日の一次指標: 欠損補完エンジンを翌日に適用(決定的特徴+慣性)。ベイズ天井で参考値。

各予測に confidence(high/medium/low) を付け、UI は確度で濃淡を付ける。
気圧予報は実スキルがあり検証済みトリガーと組むため濃い。明日のHRV等は薄い。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope
from app.integrations.weather import get_pressure_hourly
from app.models import BodyBattery
from app.scoring.migraine_triggers import WINDOW_H, _exposure_pressure_drop, analyze_triggers
from app.scoring.timewindow import JST, app_today


def _now_jst() -> datetime:
    return datetime.now(JST).replace(tzinfo=None)


def _rel_label(d_offset: int) -> str:
    return {0: "今日", 1: "明日", 2: "明後日"}.get(d_offset, "")


def _first_onset(series, now_jst: datetime, elev_thr: float, case_mean: float | None):
    """気圧変動が誘発域 (elev_thr) に最初に達する時刻を 1h 刻みで探す。

    返り値: (現在からの時間, 時刻ラベル, その時点のリスク) or (None, None, None)。
    24h 窓の変動なので「いつから危険な気圧変化が始まるか」= 何時間後からを示せる。
    """
    severe_thr = get_settings().pressure_drop_severe_hpa
    h = now_jst
    end = now_jst + timedelta(hours=48)
    while h <= end:
        sw = _exposure_pressure_drop(series, h - timedelta(hours=WINDOW_H), h)
        if sw is not None and sw >= elev_thr:
            hours = (h - now_jst).total_seconds() / 3600
            d_off = (h.date() - now_jst.date()).days
            label = f"{_rel_label(d_off)}{h.hour:02d}時頃" if hours >= 1 else "まもなく"
            high = sw >= (case_mean if case_mean is not None else severe_thr)
            return round(hours), label, ("high" if high else "elevated")
        h += timedelta(hours=1)
    return None, None, None


def _pressure_forecast(series, now_jst: datetime, pf: dict | None, tr: dict) -> dict[str, Any] | None:
    """気圧トリガーの 48h 予報 (12h バケット + 何時間後から)。

    pf=検証済み誘発トリガー(個人閾値) / None=一般基準フォールバック。
    """
    s = get_settings()
    warn_thr, severe_thr = s.pressure_drop_warning_hpa, s.pressure_drop_severe_hpa
    if pf is not None:
        conf = {"strong": "high", "suggestive": "medium"}.get(pf["tier"], "low")
        case_mean, control_mean = pf.get("case_mean"), pf.get("control_mean")
        elev_thr = (case_mean + control_mean) / 2
    else:
        # 未検証 (個人閾値なし) のフォールバックは一般基準 = config の気圧降下閾値に揃える
        # (forecast 独自のマジックナンバーを持たず warning/severe を一元管理する)。
        conf, case_mean, control_mean, elev_thr = "low", None, None, warn_thr

    def classify(swing: float) -> str:
        if case_mean is not None and control_mean is not None:
            if swing >= case_mean:
                return "high"
            return "elevated" if swing >= elev_thr else "low"
        return "high" if swing >= severe_thr else ("elevated" if swing >= warn_thr else "low")

    buckets: list[dict[str, Any]] = []
    for b in range(4):
        bstart = now_jst + timedelta(hours=b * 12)
        bend = bstart + timedelta(hours=12)
        swings = []
        h = bstart
        while h < bend:
            w = _exposure_pressure_drop(series, h - timedelta(hours=WINDOW_H), h)
            if w is not None:
                swings.append(w)
            h += timedelta(hours=3)
        if not swings:
            continue
        swing = max(swings)
        d_off = (bstart.date() - now_jst.date()).days
        part = "午前" if bstart.hour < 12 else ("午後" if bstart.hour < 18 else "夜")
        buckets.append({
            "label": f"{_rel_label(d_off)}{part}",
            "start": bstart.isoformat(timespec="hours"),
            "swing_hpa": round(swing, 1),
            "risk": classify(swing),
        })
    if not buckets:
        return None
    rank = {"high": 2, "elevated": 1, "low": 0}
    peak = max(buckets, key=lambda x: rank[x["risk"]])
    if peak["risk"] == "low":
        return None  # 日内変動レベルなら出さない (狼少年回避)

    onset_h, onset_label, onset_risk = _first_onset(series, now_jst, elev_thr, case_mean)
    return {
        "confidence": conf,
        "buckets": buckets,
        "peak": peak,
        "is_trigger_validated": pf is not None,
        "onset_in_hours": onset_h,
        "onset_label": onset_label,
        "onset_risk": onset_risk,
    }


def _current_personal_risk(now_jst: datetime, triggers: list[dict]) -> list[dict[str, Any]]:
    """検証済みトリガーの『今の曝露』を評価し、現在リスクが誘発域の誘因だけ返す。

    曝露は各トリガーの case_mean/control_mean と同じ単位。mid 以上=elevated、
    case_mean 以上=high。今が誘発域でなければ何も返さない (= バナー非表示)。
    """
    from app.models import CaffeineIntake, SleepSession
    from app.scoring.caffeine import MEDICATION_CAFFEINE_SOURCES
    from app.scoring.migraine_triggers import ANALYSIS_DAYS

    now_utc = now_jst - timedelta(hours=9)  # JST naive → UTC naive
    active: list[dict[str, Any]] = []
    with session_scope() as s:
        for t in triggers:
            cm, ctrl = t.get("case_mean"), t.get("control_mean")
            if cm is None or ctrl is None:
                continue
            mid = (cm + ctrl) / 2
            cur: float | None = None
            if t["key"] == "caffeine":
                since = now_utc - timedelta(hours=24)
                last24 = sum(
                    r[0] for r in s.execute(
                        select(CaffeineIntake.mg).where(
                            CaffeineIntake.ts >= since,
                            CaffeineIntake.source.notin_(MEDICATION_CAFFEINE_SOURCES),
                        )
                    ).all() if r[0]
                )
                base_since = now_utc - timedelta(days=ANALYSIS_DAYS)
                base_total = sum(
                    r[0] for r in s.execute(
                        select(CaffeineIntake.mg).where(
                            CaffeineIntake.ts >= base_since,
                            CaffeineIntake.source.notin_(MEDICATION_CAFFEINE_SOURCES),
                        )
                    ).all() if r[0]
                )
                cur = last24 - base_total / ANALYSIS_DAYS  # baseline からの偏差
            elif t["key"] == "sleep_short":
                row = s.execute(
                    select(SleepSession.total_min).order_by(SleepSession.date.desc()).limit(1)
                ).first()
                if row and row[0] is not None:
                    cur = 480 - float(row[0])  # 8h からの不足分
            if cur is None:
                continue
            if cur >= cm:
                level = "high"
            elif cur >= mid:
                level = "elevated"
            else:
                continue  # 今は誘発域でない → 出さない
            active.append({
                "key": t["key"], "label": t["label"], "tier": t["tier"],
                "level": level, "current": round(cur, 1),
            })
    return active


def _typical_onset(now_jst: datetime, onset_profile: dict) -> dict[str, Any] | None:
    """過去の発症時刻プロファイルから「何時頃に出やすいか」を推定する (記述的)。

    mean_hour を中心に、今からの時間差 (今日のピークがまだ先なら) を返す。
    """
    mh = onset_profile.get("mean_hour")
    if mh is None:
        return None
    clock = f"{int(mh):02d}:{round((mh % 1) * 60) % 60:02d}"
    now_h = now_jst.hour + now_jst.minute / 60.0
    diff = mh - now_h
    return {
        "clock": clock,
        "peak_bucket": onset_profile.get("peak_bucket"),
        "sd_hour": onset_profile.get("sd_hour"),
        "hours_from_now": round(diff) if diff > 0.25 else None,  # 今日のピークがまだ先
        "passed": diff <= 0.25,  # 典型時間帯を既に過ぎた
    }


def _recent_episode_count(now_jst: datetime, days: int = 30) -> int:
    """直近 days 日の完了済み片頭痛発作数 (多発期の文脈)。

    旧『気圧降下×頭痛多発期』アラートが持っていた『直近30日にN回』をここに集約する。
    進行中 (ended_at=None) は除外し、確定した発作だけ数える。
    """
    from sqlalchemy import func

    from app.models import MigraineEpisode

    since = now_jst - timedelta(hours=9) - timedelta(days=days)  # JST naive → UTC naive
    with session_scope() as s:
        n = s.execute(
            select(func.count(MigraineEpisode.id)).where(
                MigraineEpisode.started_at >= since,
                MigraineEpisode.ended_at.is_not(None),
            )
        ).scalar()
    return int(n or 0)


def _migraine_forecast(now_jst: datetime) -> dict[str, Any] | None:
    """片頭痛リスク予報。本人の検証済みトリガーで個人化する。

    - 気圧: 本人データで「誘発」と検証されたら個人閾値で予報。検証したのに誘発でない
      (本人の頭痛は気圧と無関係/逆) なら気圧予報は出さない。未検証なら一般基準で低確度。
    - 気圧以外の本人の誘因 (カフェイン/睡眠など、誘発方向・有意) を personal_triggers として返す。
    """
    tr = analyze_triggers(app_today())
    factors = tr.get("factors", [])
    pf = next((f for f in factors if f["key"] == "pressure_drop"), None)

    # 本人の検証済み誘因 (誘発方向・強/中、気圧以外) = この人の本当のリスク要因
    personal_triggers = [
        {"key": f["key"], "label": f["label"], "tier": f["tier"],
         "case_mean": f.get("case_mean"), "control_mean": f.get("control_mean")}
        for f in factors
        if f.get("direction") == "誘発" and f.get("tier") in ("strong", "suggestive")
        and f["key"] != "pressure_drop"
    ]

    pressure_validated = pf is not None and pf.get("direction") == "誘発"
    # 本人データが「気圧は誘因でない」と有意に示すなら気圧予報は出さない (パーソナライズ)
    pressure_refuted = (
        pf is not None and pf.get("direction") != "誘発" and pf.get("tier") in ("strong", "suggestive")
    )

    pressure_section = None
    series = get_pressure_hourly()
    if series and not pressure_refuted:
        pressure_section = _pressure_forecast(series, now_jst, pf if pressure_validated else None, tr)

    # 「今の曝露」が誘発域にある誘因だけ抽出 (常時表示しない)
    active_triggers = _current_personal_risk(now_jst, personal_triggers)

    # 気圧予報も無く、今まさにリスクの高い誘因も無ければ非表示
    if pressure_section is None and not active_triggers:
        return None

    # 「何時から痛くなるか」= 過去の発症時刻プロファイル (記述的) からの推定
    likely_onset = _typical_onset(now_jst, tr.get("onset_profile", {}))

    # 全体リスクレベル: 気圧ピーク or 今の誘因が誘発域 high なら「高」。それ以外は「やや高」。
    peak_high = bool(pressure_section and pressure_section["peak"]["risk"] == "high")
    active_high = any(t["level"] == "high" for t in active_triggers)
    level = "high" if (peak_high or active_high) else "elevated"

    # 旧『気圧降下×頭痛多発期』の対処アクションを集約 (リスク高のときのみ)
    actions = (
        ["屋外活動を控える", "頭痛薬を手元に", "光・音刺激を最小化"]
        if level == "high"
        else []
    )

    out: dict[str, Any] = {
        "reliability": tr.get("reliability"),
        "episode_count": tr.get("episode_count"),
        "recent_count": _recent_episode_count(now_jst),
        "level": level,
        "actions": actions,
        "personal_triggers": personal_triggers,
        "active_triggers": active_triggers,
        "likely_onset": likely_onset,
        "pressure_refuted": pressure_refuted,
        "pressure": pressure_section,
    }
    if pressure_section:
        out.update(pressure_section)  # 後方互換: peak/confidence 等を top-level にも
    return out


def _energy_today(now_jst: datetime) -> dict[str, Any] | None:
    """直近の Body Battery スロープから、残りの一日の推移と枯渇時刻を外挿。"""
    now_utc = now_jst - timedelta(hours=9)
    with session_scope() as s:
        rows = s.execute(
            select(BodyBattery.ts, BodyBattery.value)
            .where(BodyBattery.ts >= now_utc - timedelta(hours=4), BodyBattery.ts <= now_utc)
            .order_by(BodyBattery.ts)
        ).all()
    pts = [(ts, float(v)) for ts, v in rows if v is not None]
    if len(pts) < 3:
        return None
    # 時間(h) を x とした最小二乗の傾き
    t0 = pts[0][0]
    xs = [(ts - t0).total_seconds() / 3600 for ts, _ in pts]
    ys = [v for _, v in pts]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / denom  # /h
    current = ys[-1]
    eta = None
    floor = 20.0
    if slope < -0.5 and current > floor:
        hours_to_floor = (current - floor) / (-slope)
        if hours_to_floor < 18:
            eta = (now_jst + timedelta(hours=hours_to_floor)).isoformat(timespec="minutes")
    return {
        "confidence": "medium",
        "current": round(current),
        "slope_per_h": round(slope, 1),
        "empty_eta": eta,
        "floor": int(floor),
    }


def _tomorrow_metrics() -> dict[str, Any]:
    """翌日の一次指標を補完エンジンで予測 (決定的特徴+慣性)。ベイズ天井で低確度。"""
    from app.scoring.imputation import impute_day
    return impute_day(app_today() + timedelta(days=1), only_missing=True)


def forecast(*, now_jst: datetime | None = None) -> dict[str, Any]:
    now_jst = now_jst or _now_jst()
    return {
        "generated_at": now_jst.isoformat(timespec="minutes"),
        "location": "Tokyo",
        "migraine": _migraine_forecast(now_jst),
        "energy_today": _energy_today(now_jst),
        "tomorrow": _tomorrow_metrics(),
    }
