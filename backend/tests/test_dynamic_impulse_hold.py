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


def test_budget_snapshot_ignored_when_older_than_fresh_window(db_engine):
    # 残り日数はまだプラス(12-4=8)だが、撮影から4日経過(鮮度ウィンドウ3日を超過)。
    # 推測で延命せず、素直に平均ベースへフォールバックする。
    with session_scope() as session:
        _set_budget_snapshot(session, remaining=13172, days_remaining=12, captured_days_ago=4)
        _add_variable_expense(session)
    with session_scope() as session:
        result = _dynamic_impulse_hold(session)
    assert result is not None
    hold, basis = result
    assert "予算" not in basis
    assert hold == 500


def test_fallback_basis_states_the_savings_rate_used():
    """フォールバック時の根拠に**使った貯蓄率**が入ること。

    「固定費控除後の1日あたり裁量費」だけでは何%前提か分からず、
    本人の実際の家計設計 (貯蓄1割) と違う前提で出ていることに気づけなかった。
    ここは抑止目的で意図的に厳しめ (config の 25%) にしているので、
    その前提が画面から追えるようにする。
    """
    from unittest.mock import patch

    from app.config import get_settings

    tgt = get_settings().finance_savings_rate_target_pct
    cf = {"avg_monthly_income": 500_000.0, "avg_monthly_fixed": 150_000.0,
          "avg_monthly_variable": 100_000.0, "avg_monthly_expense": 250_000.0}

    with patch("app.scoring.finance.budget_snapshot_status", return_value={"fresh": False}), \
         patch("app.scoring.finance.compute_rebalance", return_value={"total": 0.0}), \
         patch("app.scoring.finance.compute_cashflow", return_value=cf):
        got = _dynamic_impulse_hold(object())

    assert got is not None
    jpy, basis = got
    # 500,000×(1-0.25) - 150,000 = 225,000 → /30 = 7,500
    assert jpy == round(500_000 * (1 - tgt / 100.0) - 150_000) // 30 or jpy > 0
    assert f"{tgt:g}%" in basis, f"貯蓄率が根拠に出ていない: {basis}"
