"""「ヤバい状態」を自動検知するルールベースのアラートシステム。

# 設計原則
- 子育て中・余裕なしのユーザーが「気づけない兆候」を system が監視
- 各 alert は (1) 状況の事実、(2) ヤバさレベル、(3) **最小労力で取れる対応 1 つ** を提示
- ルールベース (LLM 不要) で即時・コストゼロ
- 過剰アラート (alert fatigue) を避けるため、しきい値は保守的に設定

# 7 つのルール
1. 慢性睡眠不足 (Belenky 2003)
2. HRV 慢性低下 (Plews 2013)
3. 回復不全 (Body Battery)
4. 体重低下 (子育て・忙殺時に出やすい筋肉減少)
5. MOH = Medication Overuse Headache (鎮痛薬乱用)
6. カフェイン依存サイクル (睡眠不足↔カフェイン)
7. 気圧急降下 + 偏頭痛履歴
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    BodyBatteryDaily,
    CaffeineIntake,
    HrvDaily,
    MigraineEpisode,
    SleepSession,
    WeightSample,
)
from app.scoring.timewindow import jst_window_start


@dataclass(frozen=True)
class WellbeingAlert:
    code: str  # "chronic_sleep_deficit" など
    severity: str  # "critical" | "warning" | "info"
    title: str  # 短い見出し (20 字以内)
    detail: str  # 1 文の事実説明
    action: str  # 最小労力で取れる対応 1 つ


def evaluate_alerts(
    session: Session,
    target: date,
    *,
    pressure_risk_level: str | None = None,
    target_weight_kg: float = 56.5,
    weight_lower_kg: float = 55.5,
) -> list[WellbeingAlert]:
    """target 日時点のリスク評価を返す。"""
    alerts: list[WellbeingAlert] = []

    # ルール 1: 慢性睡眠不足
    a1 = _check_chronic_sleep_deficit(session, target)
    if a1:
        alerts.append(a1)

    # ルール 2: HRV 慢性低下
    a2 = _check_hrv_decline(session, target)
    if a2:
        alerts.append(a2)

    # ルール 3: 回復不全 (朝 BB 低下継続)
    a3 = _check_recovery_failure(session, target)
    if a3:
        alerts.append(a3)

    # ルール 4: 体重低下
    a4 = _check_weight_loss(session, target, weight_lower_kg, target_weight_kg)
    if a4:
        alerts.append(a4)

    # ルール 5: MOH リスク
    a5 = _check_moh_risk(session, target)
    if a5:
        alerts.append(a5)

    # ルール 6: カフェイン依存サイクル
    a6 = _check_caffeine_dependency_cycle(session, target)
    if a6:
        alerts.append(a6)

    # ルール 7: 気圧急降下 + 偏頭痛履歴
    if pressure_risk_level in ("warning", "severe"):
        a7 = _check_pressure_migraine(session, target, pressure_risk_level)
        if a7:
            alerts.append(a7)

    # 重要度順 (critical -> warning -> info)
    rank = {"critical": 0, "warning": 1, "info": 2}
    alerts.sort(key=lambda a: rank.get(a.severity, 9))
    return alerts


# ----- 個別ルール -----


def _check_chronic_sleep_deficit(
    session: Session, target: date
) -> WellbeingAlert | None:
    """直近 3 日のうち 2 日以上が 5h (300 分) 未満。

    Belenky 2003: 1 夜の追い込みは 3 夜の回復睡眠が必要。連続短時間睡眠は
    PVT lapse を倍々に増やす (Van Dongen 2003 累積効果)。
    """
    rows = session.execute(
        select(SleepSession.total_min)
        .where(
            SleepSession.date <= target,
            SleepSession.date > target - timedelta(days=3),
        )
        .order_by(SleepSession.date.desc())
    ).all()
    short_nights = [r[0] for r in rows if r[0] is not None and r[0] < 300]
    if len(short_nights) >= 2:
        avg_h = sum(short_nights) / len(short_nights) / 60
        return WellbeingAlert(
            code="chronic_sleep_deficit",
            severity="critical",
            title="3 日中 2 夜が 5 時間未満",
            detail=(
                f"短時間睡眠が {len(short_nights)} 日続き、平均 {avg_h:.1f}h。"
                "認知機能は BAC 0.05-0.1% (酒気帯び相当) まで低下"
            ),
            action="今日は重要判断を避け、可能なら 20 分のパワーナップを 14-15 時に",
        )
    return None


def _check_hrv_decline(session: Session, target: date) -> WellbeingAlert | None:
    """直近 7 日 avg HRV が 28 日 baseline の -20% 以下。

    Plews 2013: long-term HRV downward drift = overreaching / burnout の前兆。
    """
    rows_28 = session.execute(
        select(HrvDaily.last_night_avg)
        .where(
            HrvDaily.date <= target,
            HrvDaily.date > target - timedelta(days=28),
            HrvDaily.last_night_avg.is_not(None),
        )
    ).all()
    values_28 = [float(r[0]) for r in rows_28 if r[0] is not None]
    if len(values_28) < 14:
        return None
    baseline = sum(values_28) / len(values_28)

    rows_7 = session.execute(
        select(HrvDaily.last_night_avg)
        .where(
            HrvDaily.date <= target,
            HrvDaily.date > target - timedelta(days=7),
            HrvDaily.last_night_avg.is_not(None),
        )
    ).all()
    values_7 = [float(r[0]) for r in rows_7 if r[0] is not None]
    if len(values_7) < 4:
        return None
    recent = sum(values_7) / len(values_7)

    if baseline <= 0:
        return None
    drop_pct = (recent - baseline) / baseline * 100
    if drop_pct <= -20:
        return WellbeingAlert(
            code="hrv_chronic_decline",
            severity="warning",
            title=f"HRV が 7 日 baseline 比 {drop_pct:+.0f}%",
            detail=(
                f"直近 7 日平均 {recent:.0f}ms / 28 日 baseline {baseline:.0f}ms。"
                "自律神経の回復不全、burnout 前兆の可能性"
            ),
            action="今週は HIIT・高負荷を控え、軽い有酸素 + ボックスブレシング 5 分を朝晩",
        )
    return None


def _check_recovery_failure(
    session: Session, target: date
) -> WellbeingAlert | None:
    """朝 Body Battery < 30 が 3 日連続。"""
    rows = session.execute(
        select(BodyBatteryDaily.morning_value)
        .where(
            BodyBatteryDaily.date <= target,
            BodyBatteryDaily.date > target - timedelta(days=3),
        )
        .order_by(BodyBatteryDaily.date.desc())
    ).all()
    values = [float(r[0]) for r in rows if r[0] is not None]
    if len(values) >= 3 and all(v < 30 for v in values):
        return WellbeingAlert(
            code="recovery_failure",
            severity="warning",
            title="朝の回復が 3 日続けて不十分",
            detail=(
                f"朝 BB が {len(values)} 日連続で 30 未満 (平均 {sum(values)/len(values):.0f})。"
                "睡眠で回復しきれていない"
            ),
            action="今日はトレ予定があれば完全休息に振替、夜は通常より 1 時間早く就寝",
        )
    return None


def _check_weight_loss(
    session: Session,
    target: date,
    lower_kg: float,
    target_kg: float,
) -> WellbeingAlert | None:
    """直近 7 日中央値が目標下限 -1kg 以下。

    子育て・忙殺時に食事不規則 + 睡眠不足で筋肉減少が起きやすい。
    BMI 軽すぎ + パフォーマンス低下の悪循環の前兆。
    """
    seven_days_ago = jst_window_start(7, target)
    rows = session.execute(
        select(WeightSample.weight_kg)
        .where(
            WeightSample.ts >= seven_days_ago,
            WeightSample.weight_kg.is_not(None),
        )
    ).all()
    values = sorted(float(r[0]) for r in rows if r[0] is not None)
    if not values:
        return None
    n = len(values)
    median = values[n // 2] if n % 2 == 1 else (values[n // 2 - 1] + values[n // 2]) / 2
    diff = median - lower_kg
    if diff <= -1.0:
        return WellbeingAlert(
            code="weight_loss",
            severity="critical",
            title=f"体重が目標下限 {lower_kg:.1f}kg を {-diff:.1f}kg 下回る",
            detail=(
                f"直近 7 日中央値 {median:.1f}kg。"
                "睡眠不足 × 食事不規則時の筋肉減少サインの可能性"
            ),
            action="今日タンパク質を +20g (夜のプロテイン or 鶏むね 100g 追加)",
        )
    return None


def _check_moh_risk(session: Session, target: date) -> WellbeingAlert | None:
    """月の頭痛薬服用回数で MOH (Medication Overuse Headache) リスクを警告。

    国際頭痛分類 (ICHD-3): 月 10 日以上の鎮痛薬服用が 3 ヶ月以上で MOH と分類。
    保守的に月 8 回で amber、12 回で rose。
    """
    thirty_days_ago = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=30)
    count = session.execute(
        select(func.count(CaffeineIntake.id)).where(
            CaffeineIntake.ts >= thirty_days_ago,
            CaffeineIntake.source.in_(("ibuquick", "bufferin_premium")),
        )
    ).scalar()
    count = int(count or 0)
    if count >= 12:
        return WellbeingAlert(
            code="moh_risk_high",
            severity="critical",
            title=f"鎮痛薬 30 日で {count} 回服用",
            detail=(
                "月 10 回以上 × 3 ヶ月で薬物乱用頭痛 (MOH) と診断される閾値超え。"
                "予防薬の医師相談を検討"
            ),
            action="今週中に頭痛外来の予約を取る (神経内科 or 頭痛専門医)",
        )
    if count >= 8:
        return WellbeingAlert(
            code="moh_risk_mid",
            severity="warning",
            title=f"鎮痛薬 30 日で {count} 回",
            detail="月 10 日が MOH の閾値。あと少しで予防薬の検討域",
            action="頻発するなら頭痛専門医を一度受診、予防薬の選択肢を相談",
        )
    return None


def _check_caffeine_dependency_cycle(
    session: Session, target: date
) -> WellbeingAlert | None:
    """直近 7 日: avg sleep < 360 分 (6h) かつ avg daily caffeine > 200mg。

    睡眠不足→カフェイン→入眠悪化→さらに睡眠不足、の悪循環指標。
    """
    # 直近 7 日の sleep
    sleep_rows = session.execute(
        select(SleepSession.total_min)
        .where(
            SleepSession.date <= target,
            SleepSession.date > target - timedelta(days=7),
            SleepSession.total_min.is_not(None),
        )
    ).all()
    sleeps = [float(r[0]) for r in sleep_rows if r[0] is not None]
    if len(sleeps) < 4:
        return None
    avg_sleep = sum(sleeps) / len(sleeps)
    if avg_sleep >= 360:
        return None

    # 直近 7 日の caffeine
    seven_days_ago = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=7)
    cf_rows = session.execute(
        select(CaffeineIntake.mg).where(CaffeineIntake.ts >= seven_days_ago)
    ).all()
    total_mg = sum(float(r[0]) for r in cf_rows if r[0] is not None)
    daily_mg = total_mg / 7
    if daily_mg < 200:
        return None

    return WellbeingAlert(
        code="caffeine_dependency_cycle",
        severity="warning",
        title="睡眠不足 × カフェイン過多",
        detail=(
            f"7 日平均: 睡眠 {avg_sleep/60:.1f}h / カフェイン {daily_mg:.0f}mg/日。"
            "悪循環に入っている可能性"
        ),
        action="今日は午後カフェインゼロにして、14-15 時に 20 分ナップ",
    )


def _check_pressure_migraine(
    session: Session, target: date, pressure_risk_level: str
) -> WellbeingAlert | None:
    """気圧急降下 (warning/severe) + 直近 30 日に偏頭痛 3 回以上で alert。"""
    thirty_days_ago = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=30)
    count = session.execute(
        select(func.count(MigraineEpisode.id)).where(
            MigraineEpisode.started_at >= thirty_days_ago,
            MigraineEpisode.ended_at.is_not(None),
        )
    ).scalar()
    count = int(count or 0)
    if count < 3:
        return None

    severity = "critical" if pressure_risk_level == "severe" else "warning"
    return WellbeingAlert(
        code="pressure_migraine_trigger",
        severity=severity,
        title="気圧降下 × 頭痛多発期",
        detail=(
            f"直近 30 日に偏頭痛 {count} 回、本日の気圧は "
            f"{pressure_risk_level}。発症リスク高"
        ),
        action="今日は屋外活動を控え、頭痛薬を手元に。光・音刺激を最小化",
    )


def to_dict(a: WellbeingAlert) -> dict[str, Any]:
    return {
        "code": a.code,
        "severity": a.severity,
        "title": a.title,
        "detail": a.detail,
        "action": a.action,
    }
