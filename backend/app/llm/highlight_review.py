"""ハイライトイベントの AI 評価 — 軸は「目標体型に対してベストな努力か」。

睡眠・運動・集中・家事・体調記録などの1イベントを、本人の体型目標
(目標体重/体脂肪率/FFMI) と現状・今日の栄養・睡眠・筋トレ間隔に照らして
1〜2文で評価する。VO2Max やデータ品質の話はしない (それは体型目標の従属変数)。
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope
from app.logging import get_logger
from app.scoring.timewindow import app_today

logger = get_logger(__name__)

_SYSTEM = """\
あなたは利用者専属のボディメイクコーチです。1日の中の1イベント (睡眠/運動/集中作業/
家事/体調記録 等) を、**本人の目標体型に近づくうえでベストな努力だったか**の観点だけで
1〜2文 (最大160字) で評価します。

# 評価軸 (これ以外の話はしない)
- 目標: physique_goal (目標体重/体脂肪率/FFMI帯) vs current。FFMI が目標より低ければ
  **増量・筋肥大フェーズ** = 筋トレ刺激・タンパク質・7h睡眠が三本柱。
- 睡眠イベント: 睡眠時間が筋合成に足りているか (7h未満は逆風)。就寝時刻の乱れ。
- 運動イベント: 筋肥大に効く刺激か。増量期の有酸素は心肺維持 (短時間) ならOK、
  長時間ならカロリー赤字リスクを指摘。筋トレ間隔 (days_since_strength) も見る。
- 集中/家事イベント: 座位連続や食事タイミングへの影響。NEAT は肯定。
- 体調記録イベント: 記録習慣は肯定しつつ、数値 (筋肉痛/活力) から回復状態を読み解く。
- 改善点は**1つだけ**、次に取る行動として具体的に。良ければ素直に褒める。
- tone: good / caution / info。日本語。絵文字なし。VO2Max・GPS等の計測話はしない。
"""

_TOOL: dict[str, Any] = {
    "name": "submit_review",
    "description": "イベントの評価を返す。",
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "評価 (最大160字, 1〜2文)"},
            "tone": {"type": "string", "enum": ["good", "caution", "info"]},
        },
        "required": ["text", "tone"],
    },
}


def _physique_context() -> dict[str, Any]:
    """目標体型と現状 (体重/体脂肪/FFMI) をまとめる。"""
    from app.models import WeightSample
    from app.scoring.population_norms import ffmi
    from app.scoring.profile import resolve_profile

    prof = resolve_profile()
    with session_scope() as s:
        w = s.execute(
            select(WeightSample).order_by(WeightSample.ts.desc()).limit(1)
        ).scalars().first()
        weight = w.weight_kg if w else None
        bf = w.body_fat_pct if w else None
    tgt_ffmi = None
    if prof.target_weight_kg and prof.target_body_fat_pct is not None and prof.height_cm:
        tgt_ffmi = ffmi(prof.target_weight_kg, prof.target_body_fat_pct, prof.height_cm)
    return {
        "current": {
            "weight_kg": weight, "body_fat_pct": bf,
            "ffmi": round(ffmi(weight, bf, prof.height_cm) or 0, 1) or None,
        },
        "goal": {
            "weight_kg": prof.target_weight_kg,
            "body_fat_pct": prof.target_body_fat_pct,
            "ffmi": round(tgt_ffmi, 1) if tgt_ffmi else None,
        },
    }


def _today_support_context(target: date_type) -> dict[str, Any]:
    """今日の栄養・昨夜の睡眠・筋トレ間隔 (体型目標の三本柱の現在地)。"""
    out: dict[str, Any] = {}
    try:
        from app.scoring.nutrition import aggregate_nutrition

        with session_scope() as s:
            n = aggregate_nutrition(s, target)
        out["protein_today_g"] = (n.get("protein_g") or {}).get("today_actual")
        out["protein_target_g"] = ((n.get("targets") or {}).get("protein_g") or {}).get("ideal")
        out["kcal_today"] = (n.get("kcal_intake") or {}).get("today_actual")
        out["kcal_target"] = ((n.get("targets") or {}).get("kcal_intake") or {}).get("ideal")
    except Exception:
        pass
    try:
        from app.models import SleepSession

        with session_scope() as s:
            sl = s.get(SleepSession, target)
            out["last_sleep_min"] = sl.total_min if sl else None
    except Exception:
        pass
    try:
        from app.llm.client import _days_since_last_strength_training

        out["days_since_strength"] = _days_since_last_strength_training(target)
    except Exception:
        pass
    return out


def _workout_detail(target: date_type, time_jst: str | None) -> dict[str, Any] | None:
    """イベントがワークアウトなら、近傍の Workout 実測で文脈を厚くする。"""
    if not time_jst:
        return None
    try:
        from app.models import Workout

        hh, mm = (int(x) for x in time_jst.split(":"))
        center = datetime.combine(target, datetime.min.time()).replace(hour=hh, minute=mm) - timedelta(hours=9)
        with session_scope() as s:
            w = s.execute(
                select(Workout).where(
                    Workout.start >= center - timedelta(minutes=30),
                    Workout.start <= center + timedelta(minutes=30),
                ).order_by(Workout.start).limit(1)
            ).scalars().first()
            if w is None:
                return None
            return {
                "type": w.type, "duration_min": round((w.duration_s or 0) / 60),
                "avg_hr": w.avg_hr, "max_hr": w.max_hr, "training_load": w.training_load,
                "kcal": w.kcal,
            }
    except Exception:
        return None


async def generate_review(
    *, target: date_type | None, label: str, time_jst: str | None, sub: str | None
) -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.anthropic_api_key:
        return None
    target = target or app_today()
    ctx: dict[str, Any] = {
        "event": {"label": label, "time_jst": time_jst, "detail": sub},
        "physique_goal": _physique_context(),
        "today": _today_support_context(target),
    }
    wo = _workout_detail(target, time_jst) if any(
        k in label for k in ("ラン", "筋トレ", "ボクシング", "ウォーキング", "運動", "HIIT", "サイクリング")
    ) else None
    if wo:
        ctx["workout_measured"] = wo

    import json

    try:
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        resp = await client.messages.create(
            model=settings.llm_model,
            max_tokens=400,
            system=_SYSTEM,
            messages=[{
                "role": "user",
                "content": "このイベントを目標体型の観点で評価してください:\n"
                + json.dumps(ctx, ensure_ascii=False, default=str),
            }],
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": "submit_review"},
        )
    except Exception as exc:
        logger.warning("highlight_review_failed", error=str(exc))
        return None
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use":
            inp = dict(block.input or {})
            text = str(inp.get("text") or "").strip()[:400]
            tone = inp.get("tone") if inp.get("tone") in ("good", "caution", "info") else "info"
            if text:
                return {"text": text, "tone": tone, "model": settings.llm_model}
    return None
