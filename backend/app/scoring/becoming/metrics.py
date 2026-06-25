"""フライホイールの週次ループ指標(純関数・DB非依存)。

snapshot は dict で受ける(condition / garden_intensity / garden_focus /
overall_proximity)。SQLAlchemy 行でも属性アクセスではなく dict 化して渡す。
"""

from __future__ import annotations

from collections.abc import Sequence


def loop_week(snaps: Sequence[dict], good_threshold: float) -> dict:
    """1週間分の snapshot からループ指標と診断を返す。"""
    good_days = [s for s in snaps if s.get("condition") is not None and s["condition"] >= good_threshold]
    active_days = [s for s in snaps if (s.get("garden_intensity") or 0) > 0]

    capacity_utilization = (
        sum(1 for s in good_days if (s.get("garden_intensity") or 0) > 0) / len(good_days)
        if good_days
        else None
    )
    action_alignment = (
        sum(s.get("garden_focus") or 0 for s in active_days) / len(active_days)
        if active_days
        else None
    )
    prox = [s["overall_proximity"] for s in snaps if s.get("overall_proximity") is not None]
    identity_movement = round(prox[-1] - prox[0], 4) if len(prox) >= 2 else None

    return {
        "capacity_utilization": (
            round(capacity_utilization, 4) if capacity_utilization is not None else None
        ),
        "action_alignment": round(action_alignment, 4) if action_alignment is not None else None,
        "identity_movement": identity_movement,
        "diagnosis": _diagnose(capacity_utilization, action_alignment, identity_movement, good_days),
    }


def _diagnose(
    capacity: float | None,
    alignment: float | None,
    movement: float | None,
    good_days: list,
) -> str:
    # 良好日が複数あるのに活用率が低い → 動けたのに攻めなかった
    if len(good_days) >= 2 and capacity is not None and capacity < 0.5:
        return "wasted_capacity"
    # 整合は高いのに前進していない → 行動の選択ミス(空回り)
    if alignment is not None and alignment >= 0.5 and movement is not None and movement <= 0:
        return "spinning"
    # 活用・整合・前進すべて良い → フライホイールが回っている
    if (
        capacity is not None and capacity >= 0.5
        and alignment is not None and alignment >= 0.5
        and movement is not None and movement > 0
    ):
        return "flywheel_turning"
    return "building"
