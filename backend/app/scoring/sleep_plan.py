"""今夜のスリープリズムを起床時刻から逆算する。

- 起床時刻 (config の target_wake_time) を翌日として固定
- bedtime = wake - target_sleep_min
- bath_time = bedtime - bath_to_bed_lead_min
- dinner_cutoff = bedtime - dinner_to_bed_lead_min

夜遅くにトレーニングがあるなど現実的に難しい場合は LLM 側で調整するため、
ここでは「理想の時刻」を返すだけにとどめる。
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.config import get_settings


def _parse_hhmm(s: str) -> time:
    h, _, m = s.partition(":")
    return time(int(h), int(m))


def compute_tonight_plan(
    target: date_type,
    *,
    last_training_end_jst: datetime | None = None,
) -> dict[str, Any]:
    """target の「今夜→翌朝」のリズムを返す。

    Args:
        target: 今日の日付 (JST)
        last_training_end_jst: 当日のトレーニング終了時刻 (JST aware datetime)。
            これより後の bath / bedtime しか取れない場合は調整する。

    Returns:
        ``{wake, bedtime, bath, dinner_cutoff}`` 各 HH:MM 文字列、
        + メタ情報 (compressed: 理想に届かない bool, sleep_min_estimate, notes)
    """
    s = get_settings()
    tz = ZoneInfo(s.app_tz)

    wake_t = _parse_hhmm(s.target_wake_time)
    # wake は target + 1 day で作る (今日の夜→明朝)
    wake_dt = datetime.combine(target + timedelta(days=1), wake_t, tz)
    bedtime_dt = wake_dt - timedelta(minutes=s.target_sleep_min)
    bath_dt = bedtime_dt - timedelta(minutes=s.bath_to_bed_lead_min)
    dinner_dt = bedtime_dt - timedelta(minutes=s.dinner_to_bed_lead_min)

    notes: list[str] = []
    compressed = False
    sleep_min = s.target_sleep_min

    # 当日のトレーニング終了時刻が bath_dt より遅い場合、現実的な bedtime を再計算
    if last_training_end_jst is not None:
        # 入浴は最短でもトレ後 + 30 分のクールダウン
        earliest_bath = last_training_end_jst + timedelta(minutes=30)
        if earliest_bath > bath_dt:
            bath_dt = earliest_bath
            new_bedtime = bath_dt + timedelta(minutes=s.bath_to_bed_lead_min)
            if new_bedtime > bedtime_dt:
                bedtime_dt = new_bedtime
                actual_sleep = (wake_dt - bedtime_dt).total_seconds() / 60
                if actual_sleep < s.target_sleep_min:
                    compressed = True
                    sleep_min = int(actual_sleep)
                    notes.append(
                        f"トレーニング終了 ({last_training_end_jst.strftime('%H:%M')}) を考慮すると "
                        f"理想睡眠 {s.target_sleep_min} 分は確保できません。"
                        f"現実的には {sleep_min} 分程度。"
                    )

    return {
        "wake": wake_dt.strftime("%H:%M"),
        "bedtime": bedtime_dt.strftime("%H:%M"),
        "bath": bath_dt.strftime("%H:%M"),
        "dinner_cutoff": dinner_dt.strftime("%H:%M"),
        "target_sleep_min": s.target_sleep_min,
        "estimated_sleep_min": sleep_min,
        "compressed": compressed,
        "notes": notes,
    }
