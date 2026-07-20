"""_dynamic_impulse_hold: 衝動買い保留閾値の計算 (MoneyForward予算スナップショット優先)。"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.db import session_scope
from app.models.health import CashflowTx
from app.scoring.finance import get_state
from app.scoring.next_action import _dynamic_impulse_hold
from app.scoring.timewindow import app_today


def _set_budget_snapshot(
    session, *, remaining: float, days_remaining: int, captured_days_ago: int = 0,
    period_month: str | None = None,
) -> None:
    st = get_state(session)
    st.budget_variable_remaining_jpy = remaining
    st.budget_days_remaining = days_remaining
    st.budget_captured_at = datetime.combine(
        app_today() - timedelta(days=captured_days_ago), datetime.min.time(),
    )
    st.budget_period_month = period_month or app_today().strftime("%Y-%m")


def _add_variable_expense(session, amount: float = 9000.0) -> None:
    # avg_monthly_income が無いので discretionary 分岐はスキップされ、
    # avg_monthly_variable ÷30 のフォールバック分岐に落ちる (basis に「予算」を含まない)。
    session.add(CashflowTx(
        id="t1", date=app_today(), amount_jpy=-amount, major_category="日用品", counted=True,
    ))


def test_uses_fresh_budget_snapshot_captured_today(db_engine):
    with session_scope() as session:
        _set_budget_snapshot(session, remaining=13172, days_remaining=12, captured_days_ago=0)
    with session_scope() as session:
        result = _dynamic_impulse_hold(session)
    assert result is not None
    hold, basis = result
    assert hold == round(13172 / 12)
    assert "予算" in basis


def test_budget_snapshot_ages_forward_with_elapsed_days(db_engine):
    # 3日前に撮影・当時「あと12日」→ 今日時点では残り9日として再計算する
    with session_scope() as session:
        _set_budget_snapshot(session, remaining=13172, days_remaining=12, captured_days_ago=3)
    with session_scope() as session:
        result = _dynamic_impulse_hold(session)
    assert result is not None
    hold, _basis = result
    assert hold == round(13172 / 9)


def test_budget_snapshot_ignored_when_days_exhausted(db_engine):
    # 5日前に「あと2日」で撮影 → 経過補正すると既にマイナス → スナップショットは無視
    with session_scope() as session:
        _set_budget_snapshot(session, remaining=13172, days_remaining=2, captured_days_ago=5)
        _add_variable_expense(session)
    with session_scope() as session:
        result = _dynamic_impulse_hold(session)
    assert result is not None
    hold, basis = result
    assert "予算" not in basis
    assert hold == 500  # 実際の変動費÷30 (9000/30=300 → 最低500円でクランプ)


def test_budget_snapshot_ignored_when_different_month(db_engine):
    with session_scope() as session:
        _set_budget_snapshot(
            session, remaining=13172, days_remaining=12, captured_days_ago=0, period_month="2000-01",
        )
        _add_variable_expense(session)
    with session_scope() as session:
        result = _dynamic_impulse_hold(session)
    assert result is not None
    hold, basis = result
    assert "予算" not in basis
    assert hold == 500


def test_no_snapshot_falls_back_to_existing_average_calc(db_engine):
    with session_scope() as session:
        _add_variable_expense(session)
    with session_scope() as session:
        result = _dynamic_impulse_hold(session)
    assert result is not None
    hold, basis = result
    assert "予算" not in basis
    assert hold == 500
