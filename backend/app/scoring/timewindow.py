"""JST 基準の日付境界を UTC naive datetime に変換するヘルパー。

DB の datetime カラムは naive UTC で保存されている。利用者にとって「今日」「昨日」は
JST 暦の単位なので、SQL クエリの範囲も「JST 00:00–24:00」を UTC で表現した境界を使う。
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")


def jst_day_bounds(target: date, *, tz: ZoneInfo = JST) -> tuple[datetime, datetime]:
    """JST 暦の ``target`` 日を UTC naive datetime の (start, end) で返す。

    Example:
        target = 2026-05-06 (JST)
        start_utc = 2026-05-05T15:00:00  (= JST 2026-05-06 00:00)
        end_utc   = 2026-05-06T15:00:00  (= JST 2026-05-07 00:00)

    DB クエリでは ``ts >= start AND ts < end`` の半開区間で使う。
    """
    start_local = datetime.combine(target, datetime.min.time(), tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(UTC).replace(tzinfo=None)
    end_utc = end_local.astimezone(UTC).replace(tzinfo=None)
    return start_utc, end_utc


def jst_window_start(days_back: int, target: date, *, tz: ZoneInfo = JST) -> datetime:
    """target から N 日前 (含む) の JST 00:00 を UTC naive で返す。"""
    start_local = datetime.combine(
        target - timedelta(days=days_back), datetime.min.time(), tzinfo=tz
    )
    return start_local.astimezone(UTC).replace(tzinfo=None)
