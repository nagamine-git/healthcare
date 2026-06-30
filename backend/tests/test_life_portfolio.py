from __future__ import annotations

from datetime import date, datetime, timedelta

from app.db import session_scope
from app.models.health import GoodActionLog
from app.scoring.life.portfolio import compute_portfolio


def test_portfolio_builds_and_ranks_by_roi(db_engine):
    with session_scope() as session:
        p = compute_portfolio(session, date(2026, 6, 30))
    assert "holdings" in p and len(p["holdings"]) > 0
    # ROI 降順
    rois = [h["roi"] for h in p["holdings"]]
    assert rois == sorted(rois, reverse=True)
    # 各 holding に目標配分/現在配分/シグナルが入る
    h = p["holdings"][0]
    assert {"target_alloc", "current_alloc", "signal", "roi_rel"} <= set(h)
    assert h["signal"] in ("buy", "hold", "funded", "trim")
    # 行動が無ければ現在配分は全て0、top_pick は存在する
    assert p["total_effort"] == 0
    assert p["top_pick"] is not None


def test_recent_actions_shift_current_allocation(db_engine):
    # creation 系の行動(coding)を直近に積むと creation の現在配分が上がる
    now = datetime(2026, 6, 30, 12, 0)
    with session_scope() as session:
        for i in range(5):
            session.add(GoodActionLog(ts=now - timedelta(days=i), kind="coding", source="manual", value=1.0))
    with session_scope() as session:
        p = compute_portfolio(session, date(2026, 6, 30))
    creation = next(h for h in p["holdings"] if h["key"] == "creation")
    assert creation["current_alloc"] == 100.0  # 全行動が creation
    assert p["total_effort"] == 5
