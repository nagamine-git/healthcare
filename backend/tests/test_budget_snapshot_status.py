"""budget_snapshot_status: MoneyForward「予算」スクショの鮮度判定。"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.db import session_scope
from app.scoring.finance import budget_snapshot_status, get_state
from app.scoring.timewindow import app_today


def test_missing_when_never_captured(db_engine):
    with session_scope() as session:
        status = budget_snapshot_status(session)
    assert status == {"fresh": False, "elapsed_days": None, "reason": "missing"}


def test_fresh_when_captured_today(db_engine):
    with session_scope() as session:
        st = get_state(session)
        st.budget_variable_remaining_jpy = 13172
        st.budget_days_remaining = 12
        st.budget_captured_at = datetime.combine(app_today(), datetime.min.time())
        st.budget_period_month = app_today().strftime("%Y-%m")
    with session_scope() as session:
        status = budget_snapshot_status(session)
    assert status["fresh"] is True
    assert status["elapsed_days"] == 0


def test_stale_when_older_than_fresh_window(db_engine):
    with session_scope() as session:
        st = get_state(session)
        st.budget_variable_remaining_jpy = 13172
        st.budget_days_remaining = 20
        st.budget_captured_at = datetime.combine(app_today() - timedelta(days=4), datetime.min.time())
        st.budget_period_month = app_today().strftime("%Y-%m")
    with session_scope() as session:
        status = budget_snapshot_status(session)
    assert status["fresh"] is False
    assert status["reason"] == "stale"
    assert status["elapsed_days"] == 4


def test_different_month_is_not_fresh(db_engine):
    with session_scope() as session:
        st = get_state(session)
        st.budget_variable_remaining_jpy = 13172
        st.budget_days_remaining = 12
        st.budget_captured_at = datetime.combine(app_today(), datetime.min.time())
        st.budget_period_month = "2000-01"
    with session_scope() as session:
        status = budget_snapshot_status(session)
    assert status == {"fresh": False, "elapsed_days": None, "reason": "different_month"}
