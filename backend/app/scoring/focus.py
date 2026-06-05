"""集中力 (認知準備度) の proxy スコアと今日のピーク窓予測。

医学的免責: これは EEG/瞳孔径測定のような直接的な認知測定ではなく、
複数の生理学的指標から推定する **proxy** (代替指標) である。

採用する指標と根拠:
- HRV 当夜値 (vs 28d baseline): 高 HRV ↔ 前頭前野の executive function (Thayer 2009, Forte 2019)
- Body Battery 現在値: HRV + ストレス + 睡眠 + 活動の複合 (Garmin/Firstbeat 自律神経モデル)
- 直近ストレス: HRV-derived。慢性高ストレスは PFC 機能低下 (Arnsten 2009)
- 前夜の睡眠スコア: 1夜の睡眠不足で PVT lapse 倍増 (Lim & Dinges 2010)
- 概日リズム時刻補正: 起床後 2-4h と 9-11h の 2 峰性 (Schmidt 2007 ほか)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from app.scoring.baselines import Baseline


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def circadian_factor(now: time, *, wake: time = time(6, 30)) -> float:
    """概日リズムによる認知パフォーマンス係数 (0.0-1.0)。

    起床後の経過時間に応じて 2 峰性カーブを返す:
    - 起床直後 (1h以内): 睡眠慣性で低 (0.50)
    - +1-4h: 第1ピーク (0.70 → 1.00)
    - +4-6h: ピーク維持 (1.00 → 0.85)
    - +6-8h: 食後の dip (0.85 → 0.60)
    - +8-11h: 第2ピーク (0.60 → 0.90)
    - +11-14h: 緩やかな低下 (0.90 → 0.60)
    - +14h-: 単調減少 (>0.30 で下限)
    """
    now_min = now.hour * 60 + now.minute
    wake_min = wake.hour * 60 + wake.minute
    delta_h = ((now_min - wake_min) % (24 * 60)) / 60

    if delta_h < 1:
        return 0.50
    if delta_h < 4:
        return 0.70 + 0.30 * (delta_h - 1) / 3
    if delta_h < 6:
        return 1.00 - 0.15 * (delta_h - 4) / 2
    if delta_h < 8:
        return 0.85 - 0.25 * (delta_h - 6) / 2
    if delta_h < 11:
        return 0.60 + 0.30 * (delta_h - 8) / 3
    if delta_h < 14:
        return 0.90 - 0.30 * (delta_h - 11) / 3
    return max(0.30, 0.60 - 0.10 * (delta_h - 14))


def _hrv_component(value: float | None, baseline: Baseline | None) -> float | None:
    if value is None or baseline is None:
        return None
    z = (float(value) - baseline.mean) / baseline.std
    z = max(-2.0, min(2.0, z))
    return _clamp(50.0 + 25.0 * z)


def _stress_component(stress_avg: float | None) -> float | None:
    """Garmin stress (0-100) を 反転して集中可能性に変換。

    stress 25 未満は良好 → ほぼ 100、50+ は高ストレス → 50 未満。
    """
    if stress_avg is None:
        return None
    return _clamp(100.0 - float(stress_avg))


def _sleep_component(sleep_score: float | None, total_min: int | None) -> float | None:
    """前夜の睡眠の質。Garmin sleep_score 優先、なければ duration ベース。"""
    if sleep_score is not None:
        return _clamp(float(sleep_score))
    if total_min is None or total_min <= 0:
        return None
    # 7-9h (420-540 min) を 100、4h で 50、それ未満で急落
    if total_min < 240:
        return 20.0
    if total_min < 420:
        return 50.0 + (total_min - 240) / 180 * 40
    if total_min <= 540:
        return 100.0
    if total_min <= 660:
        return 100.0 - (total_min - 540) / 120 * 30
    return 60.0


@dataclass(frozen=True)
class FocusComponents:
    hrv: float | None
    body_battery: float | None
    stress: float | None
    sleep: float | None
    circadian: float | None
    air_quality: float | None = None  # PM2.5 から導出 (高いほど良好)
    morning_light: float | None = None  # 朝光暴露 proxy (高いほど良好)


@dataclass(frozen=True)
class FocusReadiness:
    score: float | None  # 0-100, 欠損で None
    level: str  # "high" | "mid" | "low" | "unknown"
    components: FocusComponents
    rationale: str


# 重み: 「いま集中できるか」への寄与度。Body Battery が最も即時、HRV と睡眠は土台、
# circadian は時刻補正、stress は急性、air_quality と morning_light は環境補正。
_WEIGHTS = {
    "body_battery": 3.0,
    "hrv": 2.0,
    "sleep": 2.0,
    "circadian": 2.0,
    "stress": 1.0,
    "air_quality": 1.0,
    "morning_light": 1.0,
}


def _air_quality_component(pm2_5: float | None) -> float | None:
    """PM2.5 (μg/m³) を 0-100 にマップ。WHO/EPA 基準ベース。

    - < 12 (Good): 100
    - 12-35 (Moderate): 100 → 70 線形
    - 35-55 (Unhealthy for sensitive): 70 → 40
    - 55-150 (Unhealthy): 40 → 20
    - > 150: 10
    """
    if pm2_5 is None:
        return None
    p = float(pm2_5)
    if p < 12:
        return 100.0
    if p < 35:
        return 100.0 - (p - 12) / (35 - 12) * 30.0
    if p < 55:
        return 70.0 - (p - 35) / (55 - 35) * 30.0
    if p < 150:
        return 40.0 - (p - 55) / (150 - 55) * 20.0
    return 10.0


def _morning_light_component(score_0_100: float | None) -> float | None:
    """朝の屋外光暴露 proxy (0-100) をそのまま受け取る。

    呼び出し側 (dashboard など) で歩数等から算出する。
    """
    if score_0_100 is None:
        return None
    return _clamp(float(score_0_100))


def compute_focus_readiness(
    *,
    now: datetime,
    hrv_value: float | None,
    hrv_baseline: Baseline | None,
    body_battery_current: float | None,
    stress_recent_avg: float | None,
    sleep_score: float | None,
    sleep_total_min: int | None,
    wake_time: time | None = None,
    pm2_5: float | None = None,
    morning_light_score: float | None = None,
) -> FocusReadiness:
    """現在時刻における集中可能性 (0-100) を返す。

    各成分は欠損可能で、欠損成分は重みから除外して再正規化する。
    全成分欠損なら score=None。
    """
    hrv_c = _hrv_component(hrv_value, hrv_baseline)
    bb_c = float(body_battery_current) if body_battery_current is not None else None
    if bb_c is not None:
        bb_c = _clamp(bb_c)
    stress_c = _stress_component(stress_recent_avg)
    sleep_c = _sleep_component(sleep_score, sleep_total_min)
    circ_c = circadian_factor(now.time(), wake=wake_time or time(6, 30)) * 100.0
    air_c = _air_quality_component(pm2_5)
    light_c = _morning_light_component(morning_light_score)

    components = FocusComponents(
        hrv=hrv_c,
        body_battery=bb_c,
        stress=stress_c,
        sleep=sleep_c,
        circadian=circ_c,
        air_quality=air_c,
        morning_light=light_c,
    )

    items: list[tuple[float, float]] = []
    if hrv_c is not None:
        items.append((hrv_c, _WEIGHTS["hrv"]))
    if bb_c is not None:
        items.append((bb_c, _WEIGHTS["body_battery"]))
    if stress_c is not None:
        items.append((stress_c, _WEIGHTS["stress"]))
    if sleep_c is not None:
        items.append((sleep_c, _WEIGHTS["sleep"]))
    items.append((circ_c, _WEIGHTS["circadian"]))  # 時刻は常に取れる
    if air_c is not None:
        items.append((air_c, _WEIGHTS["air_quality"]))
    if light_c is not None:
        items.append((light_c, _WEIGHTS["morning_light"]))

    if not items:
        return FocusReadiness(
            score=None,
            level="unknown",
            components=components,
            rationale="生理データが揃っていません",
        )

    # 重み付き幾何平均
    total_w = sum(w for _, w in items)
    import math

    log_sum = sum(w * math.log(max(v, 1e-3)) for v, w in items)
    score = math.exp(log_sum / total_w)
    score = _clamp(score)

    if score >= 70:
        level = "high"
    elif score >= 50:
        level = "mid"
    else:
        level = "low"

    rationale = _build_rationale(score, components)
    return FocusReadiness(score=score, level=level, components=components, rationale=rationale)


def _build_rationale(score: float, c: FocusComponents) -> str:
    """最も寄与の小さい/大きい成分を 1 文で説明。"""
    # 何が引き下げているか
    candidates: list[tuple[str, float]] = []
    if c.body_battery is not None:
        candidates.append(("Body Battery", c.body_battery))
    if c.hrv is not None:
        candidates.append(("HRV", c.hrv))
    if c.sleep is not None:
        candidates.append(("前夜の睡眠", c.sleep))
    if c.stress is not None:
        candidates.append(("ストレス耐性", c.stress))
    if c.circadian is not None:
        candidates.append(("時間帯 (概日)", c.circadian))
    if c.air_quality is not None:
        candidates.append(("大気質 (PM2.5)", c.air_quality))
    if c.morning_light is not None:
        candidates.append(("朝光暴露", c.morning_light))

    if not candidates:
        return "データ不足"

    worst = min(candidates, key=lambda x: x[1])
    if worst[1] < 50:
        return f"{worst[0]} が低い ({int(worst[1])}/100) のが主因"
    best = max(candidates, key=lambda x: x[1])
    if score >= 70:
        return f"{best[0]} が高水準 ({int(best[1])}/100)"
    return f"いずれも中庸 (主要因: {worst[0]} {int(worst[1])})"


@dataclass(frozen=True)
class FocusWindow:
    """連続したピーク/低下区間。"""

    start_hhmm: str
    end_hhmm: str
    level: str  # "peak" | "dip"
    avg_score: float


def predict_today_curve(
    *,
    now: datetime,
    hrv_value: float | None,
    hrv_baseline: Baseline | None,
    body_battery_current: float | None,
    stress_recent_avg: float | None,
    sleep_score: float | None,
    sleep_total_min: int | None,
    wake_time: time | None = None,
    bb_decay_per_hour: float = 1.5,
    pm2_5: float | None = None,
    morning_light_score: float | None = None,
) -> list[dict[str, float | str]]:
    """現在時刻以降、本日中 (23:30 まで) の 30 分刻みの focus 予測曲線。

    body_battery は単純な線形減衰 (デフォルト 1.5/h) を仮定し、
    他の生理指標は当夜値で固定。circadian だけが時刻で変動。
    """
    points: list[dict[str, float | str]] = []
    cur = now.replace(minute=(0 if now.minute < 30 else 30), second=0, microsecond=0)
    end = now.replace(hour=23, minute=30, second=0, microsecond=0)
    if cur < now:
        cur = cur + timedelta(minutes=30)

    while cur <= end:
        elapsed_h = (cur - now).total_seconds() / 3600
        bb_proj = (
            max(0.0, float(body_battery_current) - elapsed_h * bb_decay_per_hour)
            if body_battery_current is not None
            else None
        )
        fr = compute_focus_readiness(
            now=cur,
            hrv_value=hrv_value,
            hrv_baseline=hrv_baseline,
            body_battery_current=bb_proj,
            stress_recent_avg=stress_recent_avg,
            sleep_score=sleep_score,
            sleep_total_min=sleep_total_min,
            wake_time=wake_time,
            pm2_5=pm2_5,
            morning_light_score=morning_light_score,
        )
        if fr.score is not None:
            points.append(
                {
                    "time": cur.strftime("%H:%M"),
                    "score": round(fr.score, 1),
                    "level": fr.level,
                }
            )
        cur = cur + timedelta(minutes=30)

    return points


def extract_peak_windows(
    curve: list[dict[str, float | str]],
    *,
    peak_threshold: float = 65.0,
    min_duration_min: int = 60,
) -> list[FocusWindow]:
    """予測曲線から peak_threshold 以上の連続区間を抽出する。

    短すぎる窓 (min_duration_min 未満) は除外。
    """
    windows: list[FocusWindow] = []
    if not curve:
        return windows

    run_start_idx: int | None = None
    run_scores: list[float] = []

    def _flush(end_idx: int) -> None:
        if run_start_idx is None:
            return
        start_t = str(curve[run_start_idx]["time"])
        end_t = str(curve[end_idx]["time"])
        duration = _duration_min(start_t, end_t)
        if duration >= min_duration_min and run_scores:
            windows.append(
                FocusWindow(
                    start_hhmm=start_t,
                    end_hhmm=end_t,
                    level="peak",
                    avg_score=round(sum(run_scores) / len(run_scores), 1),
                )
            )

    for i, p in enumerate(curve):
        score = float(p["score"])  # type: ignore[arg-type]
        if score >= peak_threshold:
            if run_start_idx is None:
                run_start_idx = i
                run_scores = [score]
            else:
                run_scores.append(score)
        else:
            if run_start_idx is not None:
                _flush(i - 1)
                run_start_idx = None
                run_scores = []

    if run_start_idx is not None:
        _flush(len(curve) - 1)
    return windows


def _duration_min(start_hhmm: str, end_hhmm: str) -> int:
    sh, sm = (int(x) for x in start_hhmm.split(":"))
    eh, em = (int(x) for x in end_hhmm.split(":"))
    # end は 30 分刻みの開始時刻なので、窓の終端は +30 分とみなす
    return (eh * 60 + em + 30) - (sh * 60 + sm)
