"""PHQ-2 + GAD-2 メンタルスクリーニングの定義とスコア判定 (純ロジック中心)。

臨床検証済みの超短縮版:
- PHQ-2 (うつ): 2項目、合計 0-6。≥3 でうつの一次スクリーニング陽性。
- GAD-2 (不安): 2項目、合計 0-6。≥3 で不安の一次スクリーニング陽性。
- PHQ-4 = PHQ-2 + GAD-2 (0-12): 全体の心理的苦痛度を段階化。

医療機器ではない。陽性=受診の目安であって診断ではない、という保守的枠組みで扱う。
参考: Kroenke et al. 2003 (PHQ-2), Kroenke et al. 2007 (GAD-2), Löwe et al. 2010 (PHQ-4)。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type
from datetime import timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.models import MentalScreening

# 過去2週間、以下の問題にどのくらいの頻度で悩まされましたか。
PHQ2_ITEMS: list[dict] = [
    {"id": "phq2_1", "layer": "depression", "text": "物事に対してほとんど興味がない、または楽しめない"},
    {"id": "phq2_2", "layer": "depression", "text": "気分が落ち込む、憂うつになる、または絶望的な気持ちになる"},
]
GAD2_ITEMS: list[dict] = [
    {"id": "gad2_1", "layer": "anxiety", "text": "神経過敏、不安、またはイライラを感じる"},
    {"id": "gad2_2", "layer": "anxiety", "text": "心配することを止められない、またはコントロールできない"},
]
# 各項目の回答 (0-3)。
SCALE_OPTIONS: list[dict] = [
    {"value": 0, "label": "全くない"},
    {"value": 1, "label": "数日"},
    {"value": 2, "label": "半分以上"},
    {"value": 3, "label": "ほとんど毎日"},
]

# 一次スクリーニング陽性のカットオフ (各サブスケール ≥3)。
POSITIVE_CUTOFF = 3
# 定期チェックの推奨間隔と、不調サイン時の短縮間隔 (日)。
CADENCE_DAYS = 14
BAD_SIGNAL_WINDOW_DAYS = 3


@dataclass(frozen=True)
class MentalResult:
    phq2: int
    gad2: int
    phq4: int
    depression_positive: bool
    anxiety_positive: bool
    severity: str  # none | mild | moderate | severe
    severity_label: str


def _severity(phq4: int) -> tuple[str, str]:
    """PHQ-4 (0-12) を苦痛度に段階化 (Löwe 2010 の区分)。"""
    if phq4 <= 2:
        return "none", "なし"
    if phq4 <= 5:
        return "mild", "軽度"
    if phq4 <= 8:
        return "moderate", "中等度"
    return "severe", "重度"


def score_screening(phq2_1: int, phq2_2: int, gad2_1: int, gad2_2: int) -> MentalResult:
    """4項目 (各 0-3) からサブスケール合計・陽性判定・苦痛度を算出 (純関数)。"""
    for v in (phq2_1, phq2_2, gad2_1, gad2_2):
        if not (0 <= v <= 3):
            raise ValueError(f"回答は 0-3 の範囲: {v}")
    phq2 = phq2_1 + phq2_2
    gad2 = gad2_1 + gad2_2
    phq4 = phq2 + gad2
    sev, sev_label = _severity(phq4)
    return MentalResult(
        phq2=phq2, gad2=gad2, phq4=phq4,
        depression_positive=phq2 >= POSITIVE_CUTOFF,
        anxiety_positive=gad2 >= POSITIVE_CUTOFF,
        severity=sev, severity_label=sev_label,
    )


def distress_achievement(phq4: int | None) -> float | None:
    """PHQ-4 を「精神状態」の達成度 (0-100、高いほど良好) に反転写像。

    苦痛が無い (phq4=0) → 100、最悪 (phq4=12) → 0。未実施は None (未計測)。
    """
    if phq4 is None:
        return None
    return round(max(0.0, 100.0 - phq4 / 12.0 * 100.0), 1)


# ---- DB ヘルパ (scoring 層に集約し、api/next_action/alerts から共用) ----

# 不調サインの閾値: 主観 mood<=2 / stress>=4、または Garmin 平均ストレス level>=50。
_SUBJ_MOOD_LOW = 2
_SUBJ_STRESS_HIGH = 4
_GARMIN_STRESS_HIGH = 50.0


def latest_screening(
    session: Session, today: date_type, within_days: int = 14
) -> MentalScreening | None:
    """直近 within_days 日で最も新しいスクリーニング行 (無ければ None)。"""
    from app.models import MentalScreening

    return (
        session.query(MentalScreening)
        .filter(MentalScreening.date <= today,
                MentalScreening.date > today - timedelta(days=within_days))
        .order_by(MentalScreening.date.desc(), MentalScreening.id.desc())
        .first()
    )


def days_since_last(session: Session, today: date_type) -> int | None:
    """最終スクリーニングからの経過日数 (未実施は None)。"""
    from app.models import MentalScreening

    row = session.query(MentalScreening).order_by(
        MentalScreening.date.desc(), MentalScreening.id.desc()
    ).first()
    return (today - row.date).days if row else None


def bad_signal(session: Session, today: date_type) -> bool:
    """直近数日の主観 (気分/ストレス) と Garmin 平均ストレスから不調サインを判定。"""
    from sqlalchemy import func, select

    from app.models import MetricSample, SubjectiveCheckin
    from app.scoring.timewindow import jst_day_bounds

    since = today - timedelta(days=BAD_SIGNAL_WINDOW_DAYS)
    rows = session.execute(
        select(SubjectiveCheckin).where(SubjectiveCheckin.date >= since)
    ).scalars().all()
    for r in rows:
        if (r.mood is not None and r.mood <= _SUBJ_MOOD_LOW) or (
            r.stress is not None and r.stress >= _SUBJ_STRESS_HIGH
        ):
            return True
    start, _ = jst_day_bounds(since)
    _, end = jst_day_bounds(today)
    avg = session.execute(
        select(func.avg(MetricSample.value)).where(
            MetricSample.metric_key == "stress",
            MetricSample.value >= 0,
            MetricSample.ts >= start,
            MetricSample.ts < end,
        )
    ).scalar()
    return avg is not None and float(avg) >= _GARMIN_STRESS_HIGH


def prompt_status(session: Session, today: date_type) -> dict:
    """should_prompt を DB から解決 (api/next_action 共用)。"""
    return should_prompt(
        days_since_last=days_since_last(session, today),
        bad_signal=bad_signal(session, today),
    )


def should_prompt(
    *, days_since_last: int | None, bad_signal: bool,
    cadence_days: int = CADENCE_DAYS, bad_window_days: int = BAD_SIGNAL_WINDOW_DAYS,
) -> dict:
    """メンタルチェックを今このタイミングで促すべきか (純関数)。

    - 未実施: 常に促す (初回)。
    - 心身の不調サインあり かつ 最終実施から bad_window_days 以上: 促す。
    - サイン無くても cadence_days 以上経過: 定期チェックとして促す。
    """
    if days_since_last is None:
        return {"due": True, "reason": "はじめての心の健康チェック", "urgency": "normal"}
    if bad_signal and days_since_last >= bad_window_days:
        return {"due": True, "reason": "最近の心身のサインが下向き。2分の確認を", "urgency": "elevated"}
    if days_since_last >= cadence_days:
        return {"due": True, "reason": "定期の心の健康チェック", "urgency": "normal"}
    return {"due": False, "reason": "", "urgency": "none"}
