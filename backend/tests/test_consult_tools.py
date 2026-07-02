"""AI 相談の記録ツール (consult_tools) の実行テスト。DB は conftest の一時 SQLite。"""

from __future__ import annotations

from datetime import date

from app.llm.consult_tools import TOOLS, execute_tool
from app.models import CaffeineIntake, SleepInterventionLog, SubjectiveCheckin


def test_tools_schema_wellformed():
    names = {t["name"] for t in TOOLS}
    assert names == {"record_sleep_intervention", "record_caffeine", "record_checkin"}
    for t in TOOLS:
        assert t["input_schema"]["type"] == "object"


def test_record_sleep_intervention_upserts(db_engine, session):
    out = execute_tool(
        "record_sleep_intervention",
        {"date": "2026-07-01", "earplugs": True, "mouth_tape": False},
    )
    assert out["ok"] is True
    assert out["updated"] == {"earplugs": True, "mouth_tape": False}
    row = session.get(SleepInterventionLog, date(2026, 7, 1))
    assert row is not None
    assert row.earplugs is True and row.mouth_tape is False
    assert row.eyemask is None  # 未指定は据え置き


def test_record_caffeine_preset_and_unknown(db_engine, session):
    out = execute_tool("record_caffeine", {"source": "green_tea", "amount": 2})
    assert out["ok"] is True and out["mg"] == 60.0  # 30mg/杯 × 2
    rows = session.query(CaffeineIntake).all()
    assert len(rows) == 1 and rows[0].source == "green_tea"

    bad = execute_tool("record_caffeine", {"source": "espresso"})
    assert bad["ok"] is False and "valid_sources" in bad


def test_record_checkin_validates_range(db_engine, session):
    out = execute_tool("record_checkin", {"mood": 4, "stress": 9})
    assert out["ok"] is True
    assert out["updated"] == {"mood": 4}  # 範囲外 (9) は無視
    row = session.query(SubjectiveCheckin).one()
    assert row.mood == 4 and row.stress is None


def test_unknown_tool_returns_error():
    out = execute_tool("delete_everything", {})
    assert out["ok"] is False
