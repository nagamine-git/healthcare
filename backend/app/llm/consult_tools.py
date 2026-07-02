"""AI 相談の「記録 tool use」。会話から実データを直接書けるようにする。

「昨日耳栓つけてた」「今コーヒー1杯飲んだ」「今日は気分3」→ ツール実行で DB に記録し、
結果を会話に返す。実装は既存 API ハンドラと同じ DB 操作 (upsert/追記) をミラーする。
ツールは副作用が明確な3つに限定 (YAGNI): 睡眠介入 / カフェイン / 主観チェックイン。
"""

from __future__ import annotations

from datetime import UTC, datetime
from datetime import date as date_type
from typing import Any

from app.db import session_scope
from app.logging import get_logger
from app.models import CaffeineIntake, SleepInterventionLog, SubjectiveCheckin
from app.scoring.timewindow import app_today

logger = get_logger(__name__)

_INTERVENTION_FLAGS = ("earplugs", "eyemask", "nose_strip", "mouth_tape")
_CHECKIN_FIELDS = ("mood", "energy", "stress", "soreness")

# Anthropic tools スキーマ。description は LLM が使い所を誤らないよう具体的に。
TOOLS: list[dict[str, Any]] = [
    {
        "name": "record_sleep_intervention",
        "description": (
            "就寝前の介入 (耳栓/アイマスク/ノーズブリーズ/口テープ) の着脱を記録する。"
            "ユーザーが「昨日耳栓つけてた」「今夜は口テープする」等、介入の事実を伝えたら使う。"
            "date はその眠りの起床日 (YYYY-MM-DD)。「昨日の夜」なら今日の日付、"
            "「今夜」なら明日の日付。省略時はサーバが今夜として解決する。"
            "指定したフラグだけ更新される (true=着けた, false=外した)。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "起床日 YYYY-MM-DD (省略可)"},
                "earplugs": {"type": "boolean"},
                "eyemask": {"type": "boolean"},
                "nose_strip": {"type": "boolean"},
                "mouth_tape": {"type": "boolean"},
            },
        },
    },
    {
        "name": "record_caffeine",
        "description": (
            "カフェイン摂取を記録する。ユーザーが「コーヒー飲んだ」等と伝えたら使う。"
            "source: instant_coffee(単位g)/canned_coffee(本)/nespresso(カプセル)/"
            "green_tea(杯)/ibuquick(錠)/bufferin_premium(錠)/manual(mg直接)。"
            "amount は各単位の量 (省略時1。manual のときは mg そのもの)。"
            "該当プリセットが無い飲み物は manual で mg を概算して記録する。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "プリセット名 or manual"},
                "amount": {"type": "number", "description": "杯数/単位数 (manual時はmg)。既定1"},
            },
            "required": ["source"],
        },
    },
    {
        "name": "record_checkin",
        "description": (
            "いまの主観コンディション (mood=気分/energy=活力/stress=ストレス/soreness=だるさ、"
            "各1-5) を今日の記録として保存する。ユーザーが体感を数値で伝えたら使う。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "mood": {"type": "integer", "minimum": 1, "maximum": 5},
                "energy": {"type": "integer", "minimum": 1, "maximum": 5},
                "stress": {"type": "integer", "minimum": 1, "maximum": 5},
                "soreness": {"type": "integer", "minimum": 1, "maximum": 5},
            },
        },
    },
]


def _record_sleep_intervention(inp: dict[str, Any]) -> dict[str, Any]:
    from app.api.sleep_intervention import _target_date

    target = date_type.fromisoformat(inp["date"]) if inp.get("date") else _target_date()
    updated: dict[str, bool] = {}
    with session_scope() as session:
        row = session.get(SleepInterventionLog, target)
        if row is None:
            row = SleepInterventionLog(date=target)
            session.add(row)
        for f in _INTERVENTION_FLAGS:
            if isinstance(inp.get(f), bool):
                setattr(row, f, inp[f])
                updated[f] = inp[f]
        row.updated_at = datetime.now(UTC).replace(tzinfo=None)
    return {"ok": True, "date": target.isoformat(), "updated": updated}


def _record_caffeine(inp: dict[str, Any]) -> dict[str, Any]:
    from app.api.caffeine import PRESET_DEFAULTS
    from app.config import get_settings

    source = str(inp.get("source") or "")
    if source not in PRESET_DEFAULTS:
        return {"ok": False, "error": f"unknown source: {source}",
                "valid_sources": sorted(PRESET_DEFAULTS.keys())}
    settings = get_settings()
    amount = float(inp.get("amount") or 1.0)
    preset = PRESET_DEFAULTS[source]
    mg_per_unit = (
        settings.instant_coffee_mg_per_g
        if source == "instant_coffee"
        else float(preset["mg_per_unit"])
    )
    mg = amount * mg_per_unit
    with session_scope() as session:
        session.add(CaffeineIntake(
            ts=datetime.now(UTC).replace(tzinfo=None), source=source,
            amount=amount, unit=str(preset.get("unit", "cup")), mg=mg,
        ))
    return {"ok": True, "source": source, "amount": amount, "mg": round(mg, 1)}


def _record_checkin(inp: dict[str, Any]) -> dict[str, Any]:
    target = app_today()
    updated: dict[str, int] = {}
    with session_scope() as session:
        row = session.get(SubjectiveCheckin, target)
        if row is None:
            row = SubjectiveCheckin(date=target)
            session.add(row)
        for f in _CHECKIN_FIELDS:
            v = inp.get(f)
            if isinstance(v, int) and 1 <= v <= 5:
                setattr(row, f, v)
                updated[f] = v
        row.updated_at = datetime.now(UTC).replace(tzinfo=None)
    return {"ok": True, "date": target.isoformat(), "updated": updated}


_EXECUTORS = {
    "record_sleep_intervention": _record_sleep_intervention,
    "record_caffeine": _record_caffeine,
    "record_checkin": _record_checkin,
}


def execute_tool(name: str, inp: dict[str, Any]) -> dict[str, Any]:
    """ツールを実行し、tool_result として返せる dict を返す (失敗も dict で返す)。"""
    fn = _EXECUTORS.get(name)
    if fn is None:
        return {"ok": False, "error": f"unknown tool: {name}"}
    try:
        return fn(inp or {})
    except Exception as exc:  # ツール失敗で相談全体を落とさない
        logger.warning("consult_tool_failed", tool=name, error=str(exc))
        return {"ok": False, "error": str(exc)}
