from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from datetime import date as date_type
from typing import Any

from sqlalchemy import func, select

from app.config import get_settings
from app.db import session_scope
from app.llm.prompts import build_messages
from app.logging import get_logger
from app.models import (
    BodyBatteryDaily,
    DailyScore,
    HrvDaily,
    LlmComment,
    SleepSession,
    WeightSample,
)

logger = get_logger(__name__)

_FALLBACK_MESSAGE = (
    "本日のデータが揃ったら、優先度の高いコンディション要因を一言で伝えます。"
    "根拠: スコアまたはサブスコアが未計算の状態です。"
)


def _gather_today_payload(target: date_type) -> dict[str, Any]:
    from app.models import BodyBattery

    with session_scope() as session:
        score = session.get(DailyScore, target)
        sleep = session.get(SleepSession, target)
        hrv = session.get(HrvDaily, target)
        bb = session.get(BodyBatteryDaily, target)
        latest_weight = session.execute(
            select(WeightSample).order_by(WeightSample.ts.desc()).limit(1)
        ).scalar_one_or_none()
        bb_latest = session.execute(
            select(BodyBattery).order_by(BodyBattery.ts.desc()).limit(1)
        ).scalar_one_or_none()

        return {
            "score": {
                "total": score.total,
                "sleep_sub": score.sleep_sub,
                "hrv_sub": score.hrv_sub,
                "bb_sub": score.bb_sub,
                "load_sub": score.load_sub,
                "weight_sub": score.weight_sub,
                "body_fat_sub": score.body_fat_sub,
            }
            if score
            else None,
            "sleep": {
                "total_min": sleep.total_min,
                "sleep_score": sleep.sleep_score,
                "deep_min": sleep.deep_min,
                "rem_min": sleep.rem_min,
            }
            if sleep
            else None,
            "hrv": {
                "last_night_avg": hrv.last_night_avg,
                "weekly_avg": hrv.weekly_avg,
                "status": hrv.status,
            }
            if hrv
            else None,
            "body_battery": {
                "morning": bb.morning_value if bb else None,
                "current": bb_latest.value if bb_latest else None,
                "current_ts": bb_latest.ts.isoformat() if bb_latest else None,
            },
            "weight_kg": latest_weight.weight_kg if latest_weight else None,
            "body_fat_pct": latest_weight.body_fat_pct if latest_weight else None,
        }


def _gather_baselines(target: date_type, window_days: int = 28) -> dict[str, Any]:
    start = target - timedelta(days=window_days)
    with session_scope() as session:
        avg_total = session.execute(
            select(func.avg(DailyScore.total)).where(DailyScore.date >= start)
        ).scalar()
        avg_hrv = session.execute(
            select(func.avg(HrvDaily.last_night_avg)).where(HrvDaily.date >= start)
        ).scalar()
        avg_sleep_min = session.execute(
            select(func.avg(SleepSession.total_min)).where(SleepSession.date >= start)
        ).scalar()
        avg_weight = session.execute(
            select(func.avg(WeightSample.weight_kg)).where(
                WeightSample.ts >= datetime.combine(start, datetime.min.time())
            )
        ).scalar()
    return {
        "avg_total_score_28d": float(avg_total) if avg_total is not None else None,
        "avg_hrv_28d": float(avg_hrv) if avg_hrv is not None else None,
        "avg_sleep_min_28d": float(avg_sleep_min) if avg_sleep_min is not None else None,
        "avg_weight_kg_28d": float(avg_weight) if avg_weight is not None else None,
    }


def _hash_messages(system: list[dict[str, Any]], messages: list[dict[str, Any]]) -> str:
    blob = json.dumps({"system": system, "messages": messages}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _store_comment(
    target: date_type,
    model: str,
    prompt_hash: str,
    comment: str,
    payload: dict[str, Any] | None = None,
) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    with session_scope() as session:
        session.add(
            LlmComment(
                date=target,
                generated_at=now,
                model=model,
                prompt_hash=prompt_hash,
                comment=comment,
                payload=payload,
            )
        )


async def _call_anthropic(
    *,
    system: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    model: str,
    api_key: str,
    max_tokens: int = 1024,
) -> dict[str, Any] | None:
    """Anthropic を tool_use で呼び出して構造化 input を返す。

    submit_advice ツールの呼び出し input (``{focus, actions, rationale}``) を返す。
    呼び出しが失敗したり tool_use が無い場合は None。
    """
    from anthropic import AsyncAnthropic

    from app.llm.prompts import SUBMIT_ADVICE_TOOL

    client = AsyncAnthropic(api_key=api_key)
    resp = await client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
        tools=[SUBMIT_ADVICE_TOOL],
        tool_choice={"type": "tool", "name": "submit_advice"},
    )
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", "") == "submit_advice":
            payload = block.input
            return payload if isinstance(payload, dict) else None
    return None


def _payload_to_prose(payload: dict[str, Any]) -> str:
    """構造化 advice を従来の人間可読プロンプト風テキストに整形 (バックアップ表示用)。"""
    lines: list[str] = []
    if focus := payload.get("focus"):
        lines.append(f"【今日のフォーカス】\n{focus}\n")
    actions = payload.get("actions") or []
    if actions:
        lines.append("【推奨アクション】")
        for a in actions:
            t = a.get("time_jst", "")
            title = a.get("title", "")
            dur = a.get("duration_min")
            intensity = a.get("intensity")
            extras = []
            if dur:
                extras.append(f"{dur}分")
            if intensity:
                extras.append(intensity)
            tail = f" ({', '.join(extras)})" if extras else ""
            lines.append(f"- [{t}] {title}{tail}")
        lines.append("")
    if rationale := payload.get("rationale"):
        lines.append(f"【根拠】\n{rationale}")
    return "\n".join(lines).strip()


async def generate_advice_for_date(target: date_type, *, force: bool = False) -> dict[str, Any]:
    settings = get_settings()
    api_key = settings.anthropic_api_key

    if not force:
        with session_scope() as session:
            today_count = session.execute(
                select(func.count(LlmComment.date)).where(LlmComment.date == target)
            ).scalar()
            if today_count and today_count >= settings.llm_max_regenerations_per_day:
                logger.info("llm_skip_rate_limit", date=str(target), count=today_count)
                return {"status": "rate_limited"}

    today_payload = _gather_today_payload(target)
    baselines = _gather_baselines(target)

    # Calendar 既存予定を取り込む (gcal 未設定なら空リスト)
    calendar_events: list[dict[str, Any]] = []
    try:
        from app.integrations.gcal import list_events_for_date

        calendar_events = list_events_for_date(target)
    except Exception as exc:
        logger.info("gcal_events_unavailable", error=str(exc))

    system, messages = build_messages(
        target=target,
        today_payload=today_payload,
        baselines=baselines,
        calendar_events=calendar_events,
    )
    prompt_hash = _hash_messages(system, messages)

    if not api_key:
        comment = _FALLBACK_MESSAGE
        _store_comment(target, "fallback", prompt_hash, comment)
        return {"status": "fallback", "comment": comment, "payload": None}

    try:
        payload = await _call_anthropic(
            system=system, messages=messages, model=settings.llm_model, api_key=api_key
        )
        if not payload:
            _store_comment(target, "fallback", prompt_hash, _FALLBACK_MESSAGE)
            return {"status": "fallback", "comment": _FALLBACK_MESSAGE, "payload": None}
        prose = _payload_to_prose(payload)
        _store_comment(target, settings.llm_model, prompt_hash, prose, payload=payload)
        return {
            "status": "ok",
            "comment": prose,
            "payload": payload,
            "model": settings.llm_model,
        }
    except Exception as exc:
        logger.warning("llm_call_failed", error=str(exc))
        _store_comment(target, "fallback", prompt_hash, _FALLBACK_MESSAGE)
        return {
            "status": "fallback",
            "comment": _FALLBACK_MESSAGE,
            "payload": None,
            "error": str(exc),
        }


async def morning_advice_job() -> dict[str, Any]:
    target = datetime.now().date()
    return await generate_advice_for_date(target)
