"""「何時にどこに居たいか」から逆算して、その日の起床時刻を出す。DB 非依存の純関数。

既存の逆算チェーンの**前段**を足すだけ::

    到着 ──移動──▶ 出発 ──身支度──▶ 布団を出る ──布団の中──▶ 目覚め ──睡眠──▶ 寝つく ──入眠潜時──▶ 布団に入る
    │                                    │
    └── ここが新しく足す部分 ──────────────┘   └── ここから先は sleep_plan が既にやっている

⚠️ **新しい逆算チェーンを作らない。** 求めた「布団を出る時刻」を、その日の起床時刻
オーバーライド (``SleepPlanOverride``) として既存の ``compute_tonight_plan`` に流し込む。
そうすれば就寝・入浴・夕食・カフェイン・PC仕事の締切まで全部が自動で追随する。
ここで独自に就寝時刻を計算すると、同じ逆算が2箇所に増えて必ず食い違う。
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, time, timedelta
from typing import Any

# 逆算に使う移動時間の上限 (分)。これを超える入力は打ち間違いとみなす
# (深夜バスや長距離移動は「前日に出発」の話になり、1日の逆算では表せない)。
MAX_TRAVEL_MIN = 12 * 60

# 身支度時間の上限 (分)。同じく打ち間違い避け。
MAX_PREP_MIN = 6 * 60


def _parse_hhmm(s: str) -> time:
    h, _, m = s.partition(":")
    return time(int(h), int(m))


def plan_from_appointment(
    target: date_type,
    arrive_hhmm: str,
    *,
    travel_min: int,
    prep_min: int,
    tz: Any,
) -> dict[str, Any]:
    """到着時刻から「布団を出る時刻」を逆算する。

    Args:
        target: 到着する日 (JST)
        arrive_hhmm: 到着したい時刻 "HH:MM"
        travel_min: 移動にかかる分数
        prep_min: 起きてから家を出るまでの身支度の分数
        tz: JST 等の tzinfo

    Returns:
        ``{arrive, depart, wake, wake_time, crosses_midnight, ...}``
        ``wake_time`` は ``SleepPlanOverride.wake_time`` にそのまま入れる "HH:MM"。

    Raises:
        ValueError: 入力が範囲外、または逆算すると前日にはみ出す場合。
    """
    if not 0 <= travel_min <= MAX_TRAVEL_MIN:
        raise ValueError(f"移動時間は 0〜{MAX_TRAVEL_MIN} 分で指定してください")
    if not 0 <= prep_min <= MAX_PREP_MIN:
        raise ValueError(f"身支度の時間は 0〜{MAX_PREP_MIN} 分で指定してください")

    arrive_dt = datetime.combine(target, _parse_hhmm(arrive_hhmm), tz)
    depart_dt = arrive_dt - timedelta(minutes=travel_min)
    wake_dt = depart_dt - timedelta(minutes=prep_min)

    # ⚠️ 逆算が前日にはみ出したら**黙って前日の時刻を返さない**。
    # SleepPlanOverride は「その日の起床時刻」を HH:MM で持つので、前日にはみ出すと
    # 24時間ずれた計画になり、静かに間違った就寝時刻を提示してしまう。
    if wake_dt.date() != target:
        raise ValueError(
            f"到着 {arrive_hhmm} から移動{travel_min}分・身支度{prep_min}分を引くと"
            f"前日 {wake_dt.strftime('%H:%M')} になります。"
            "前泊が要る予定なので、この逆算では表せません。"
        )

    return {
        "date": target.isoformat(),
        "arrive": arrive_dt.strftime("%H:%M"),
        "depart": depart_dt.strftime("%H:%M"),
        "wake": wake_dt.strftime("%H:%M"),
        "wake_time": wake_dt.strftime("%H:%M"),  # override にそのまま入れる値
        "travel_min": travel_min,
        "prep_min": prep_min,
    }
