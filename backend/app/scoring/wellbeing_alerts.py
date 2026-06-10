"""「ヤバい状態」を自動検知するルールベースのアラートシステム。

# 設計原則
- 子育て中・余裕なしのユーザーが「気づけない兆候」を system が監視
- 各 alert は (1) 状況の事実、(2) ヤバさレベル、(3) **最小労力で取れる対応 1 つ** を提示
- ルールベース (LLM 不要) で即時・コストゼロ
- 過剰アラート (alert fatigue) を避けるため、しきい値は保守的に設定

# 11 のルール
1. 慢性睡眠不足 (Belenky 2003)
2. HRV 慢性低下 (Plews 2013)
3. 回復不全 (Body Battery)
4. 体重低下 (子育て・忙殺時に出やすい筋肉減少)
5. MOH = Medication Overuse Headache (鎮痛薬乱用)
6. カフェイン依存サイクル (睡眠不足↔カフェイン)
7. 気圧急降下 + 偏頭痛履歴
8. 睡眠時 SpO2 低下継続 (無呼吸スクリーニング。手首式は誤検出が多いため複数夜で判定)
9. 安静呼吸数のベースライン超過 (感染症・過労の早期サイン)
10. Training Readiness 低値連続 (回復日推奨)
11. 睡眠中点の乱れ (概日リズム。偏頭痛トリガーでもある)

注: 8-11 は診断ではなく「注意・受診のきっかけ」の文言にとどめる。
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

    # ルール 8-11: 生理指標 (sleep raw_json / Training Readiness 由来)
    for check in (
        _check_sleep_spo2_low,
        _check_respiration_elevated,
        _check_readiness_low_streak,
        _check_sleep_irregular,
    ):
        a = check(session, target)
        if a:
            alerts.append(a)

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
                "酒気帯び運転に近い注意力低下が報告される水準で、判断ミスが増えやすい"
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
    """直近 7 日中央値が健康下限 (lower_kg = BMI 18.5 相当の体重) を下回る。

    増量目標 (target > 現体重) との差ではなく、**絶対的な低体重 (BMI<18.5)** で判定する。
    目標未達と低体重は別物なので、健康域にいる限り発火しない。
    子育て・忙殺時の食事不規則 + 睡眠不足による筋肉減少が低体重まで進んだ場合の安全網。
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
    if median < lower_kg:
        return WellbeingAlert(
            code="weight_loss",
            severity="critical",
            title=f"低体重域 (BMI 18.5 相当 {lower_kg:.1f}kg) を下回る",
            detail=(
                f"直近 7 日中央値 {median:.1f}kg は健康下限を {lower_kg - median:.1f}kg 下回る。"
                "睡眠不足 × 食事不規則時の筋肉減少サインの可能性"
            ),
            action="今日タンパク質を +20g (夜のプロテイン or 鶏むね 100g 追加)",
        )
    return None


def _check_moh_risk(session: Session, target: date) -> WellbeingAlert | None:
    """頭痛薬の服用「日数」で MOH (Medication Overuse Headache) リスクを警告。

    国際頭痛分類 (ICHD-3): 複合鎮痛薬・トリプタン・NSAIDs は月 10 日以上、
    単純鎮痛薬 (アセトアミノフェン単剤) は月 15 日以上の服用が 3 ヶ月以上 **かつ**
    頭痛が月 15 日以上で MOH と診断される。ここでは服用日数だけを見るため
    「診断」ではなく「乱用リスク域」として提示する。1 日に複数回飲んでも 1 日。
    保守的に 8 日で warning、12 日で critical。
    """
    thirty_days_ago = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=30)
    # JST 日付ごとに distinct 集計 (同日複数回は 1 日)
    day_expr = func.date(CaffeineIntake.ts, "+9 hours")
    days = session.execute(
        select(func.count(func.distinct(day_expr))).where(
            CaffeineIntake.ts >= thirty_days_ago,
            CaffeineIntake.source.in_(("ibuquick", "bufferin_premium")),
        )
    ).scalar()
    days = int(days or 0)
    if days >= 12:
        return WellbeingAlert(
            code="moh_risk_high",
            severity="critical",
            title=f"鎮痛薬を 30 日で {days} 日服用",
            detail=(
                "月 10 日以上の服用が続くと薬物乱用頭痛 (MOH) の乱用リスク域。"
                "予防薬や頓挫薬の見直しを医師に相談する価値あり"
            ),
            action="今月中に頭痛外来の予約を取る (神経内科 or 頭痛専門医)",
        )
    if days >= 8:
        return WellbeingAlert(
            code="moh_risk_mid",
            severity="warning",
            title=f"鎮痛薬を 30 日で {days} 日",
            detail="月 10 日が MOH の乱用域の目安。あと少しで検討ライン",
            action="頻発するなら頭痛専門医を一度受診し、予防薬の選択肢を相談",
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


def _daily_metric_values(
    session: Session, key: str, target: date, days: int
) -> list[float]:
    """直近 days 日 (target 含む) の MetricSample 値を新しい順で返す。

    日次 1 サンプル想定。窓は target-(days-1) 日の 00:00 から。
    `target - days` にすると days+1 夜分が入り、「直近 3 夜中 2 夜」の
    判定に 4 夜目の古い値が混入して誤発火する (SpO2 で実例あり)。
    """
    from app.models import MetricSample

    start = datetime.combine(target - timedelta(days=days - 1), datetime.min.time())
    rows = session.execute(
        select(MetricSample.value)
        .where(MetricSample.metric_key == key, MetricSample.ts >= start)
        .order_by(MetricSample.ts.desc())
    ).all()
    return [float(r[0]) for r in rows if r[0] is not None]


def _check_sleep_spo2_low(session: Session, target: date) -> WellbeingAlert | None:
    """直近 3 夜中 2 夜が 平均 SpO2 <93% または 最低 SpO2 <80%。

    成人の正常域は 95% 以上。平均が保たれていても最低値が 80% を切る
    間欠的脱飽和は睡眠時無呼吸の典型像で、最低値の方が感度が高い。
    手首式 PPG は誤検出・外れ値が多いため単夜では出さず、複数夜の継続時のみ
    「受診のきっかけ」として提示する (診断ではない)。
    """
    avg_vals = _daily_metric_values(session, "sleep_spo2_avg", target, 3)
    low_vals = _daily_metric_values(session, "sleep_spo2_lowest", target, 3)
    avg_low_nights = [v for v in avg_vals if v < 93.0]
    desat_nights = [v for v in low_vals if v < 80.0]
    if len(avg_low_nights) >= 2 or len(desat_nights) >= 2:
        parts: list[str] = []
        if avg_low_nights:
            parts.append(f"平均 {min(avg_low_nights):.0f}%")
        if desat_nights:
            parts.append(f"最低 {min(desat_nights):.0f}%")
        return WellbeingAlert(
            code="sleep_spo2_low",
            severity="warning",
            title="睡眠中の血中酸素が低め",
            detail=(
                f"直近 3 夜のうち複数夜で低酸素 ({' / '.join(parts)})。"
                "手首計測の誤差もあるが、継続するなら睡眠時無呼吸の可能性"
            ),
            action="まず装着位置 (手首骨の上を避けて密着) を確認。来週も続くなら睡眠外来へ",
        )
    return None


def _check_respiration_elevated(
    session: Session, target: date
) -> WellbeingAlert | None:
    """直近 3 夜平均の睡眠時呼吸数が 28 日 baseline +2 brpm 以上。

    安静呼吸数の上昇は発熱・感染症・過労の先行指標になりうる。
    """
    all_values = _daily_metric_values(session, "sleep_respiration_avg", target, 28)
    if len(all_values) < 10:
        return None
    recent = all_values[:3]
    baseline_vals = all_values[3:]
    if len(recent) < 3 or not baseline_vals:
        return None
    recent_avg = sum(recent) / len(recent)
    baseline = sum(baseline_vals) / len(baseline_vals)
    if recent_avg - baseline >= 2.0:
        return WellbeingAlert(
            code="respiration_elevated",
            severity="info",
            title="睡眠時呼吸数が普段より高い",
            detail=(
                f"直近 3 夜平均 {recent_avg:.1f}/分 (普段 {baseline:.1f}/分)。"
                "体調変化 (感染・過労) の先行サインのことがある"
            ),
            action="今日は負荷を抑えめにして、水分と睡眠を優先",
        )
    return None


def _check_readiness_low_streak(
    session: Session, target: date
) -> WellbeingAlert | None:
    """Training Readiness <30 が 3 日連続。Garmin の合成回復指標が底のとき。"""
    values = _daily_metric_values(session, "training_readiness", target, 3)
    if len(values) >= 3 and all(v < 30 for v in values):
        return WellbeingAlert(
            code="readiness_low_streak",
            severity="warning",
            title="Readiness 低値が 3 日連続",
            detail=(
                f"Training Readiness が 3 日続けて 30 未満 (平均 {sum(values)/len(values):.0f})。"
                "身体は回復を要求している"
            ),
            action="今日は完全休息 or 散歩程度に。トレーニングは Readiness 50 回復後に再開",
        )
    return None


def _check_sleep_irregular(session: Session, target: date) -> WellbeingAlert | None:
    """睡眠中点の 14 日 循環 SD >1.5h。

    睡眠規則性の低下は睡眠時間と独立に心身リスクと相関し、
    概日リズムの乱れは偏頭痛のトリガーにもなる。中点は時刻 (循環量) なので
    0 時をまたぐ人でも正しく評価するため循環統計を使う。
    """
    from app.scoring.circadian import circular_sd_hours

    values = _daily_metric_values(session, "sleep_midpoint_hour", target, 14)
    if len(values) < 7:
        return None
    sd = circular_sd_hours(values)
    if sd is not None and sd > 1.5:
        return WellbeingAlert(
            code="sleep_irregular",
            severity="info",
            title="就寝リズムが乱れ気味",
            detail=(
                f"睡眠中点の 14 日ばらつきが ±{sd:.1f}h。"
                "リズムの乱れは睡眠の質低下・偏頭痛のトリガーになる"
            ),
            action="今夜はいつもの就寝時刻 ±30 分以内を目標に",
        )
    return None


def to_dict(a: WellbeingAlert) -> dict[str, Any]:
    return {
        "code": a.code,
        "severity": a.severity,
        "title": a.title,
        "detail": a.detail,
        "action": a.action,
    }
