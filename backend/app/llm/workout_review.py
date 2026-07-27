"""ワークアウトの AI 一言評価 (タップ時のみ生成、WorkoutReview に永続化)。

コンテキスト: 当該ワークアウトの実測 (HR/TE/HRゾーン/距離/BB増減) + 同種目の直近比較 +
今夜の就寝計画 + 前回筋トレからの日数。筋トレ系で Garmin exerciseSets (種目/rep/重量) が
取れていれば、種目ごとのボリューム・直近比較も渡す (garmin_sync が Workout.raw_json に
``exercise_sets`` として保存する。無ければ従来どおりの全体指標評価にフォールバックする)。
tool_use で {text ≤160字, tone} を強制する。GPS 欠測 (距離が歩数と乖離) 等のデータ品質
問題にも言及させる。
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope
from app.logging import get_logger
from app.models import Workout
from app.scoring.timewindow import app_today

logger = get_logger(__name__)

_SYSTEM = """\
あなたは利用者専属のトレーニングコーチです。1件のワークアウト実績を、本人の直近データと
比較して**1〜2文 (最大160字)** で評価します。

# 方針
- 具体数字で1点だけ刺す (良かった点 or 注意点)。総花的な感想は書かない。
- workout.exercises (種目ごとのセット明細) がある場合は **必ず種目単位で** 評価する
  (category/name を名指しする):
  - ボリューム (volume_kg = 重量×rep×セット合計) を recent_exercise_sessions の同種目直近実績と
    比べ、増減を数字で示す。
  - rep_range が目的とズレていないか触れる (目安: 筋肥大 6-12 rep、筋力寄り 1-5 rep)。
  - set_details (セット順の reps/weight_kg) で終盤の落ち込みが大きい場合は疲労のサインとして触れる。
    左右差の情報があればそれも見る。
  - user_injury_notes にある既往 (腰への高負荷ヒンジ系の重量上限など) に抵触する種目・重量が
    あれば、それを最優先で安全側に指摘する。医療的な診断/治療の助言はしない
    (トレーニング強度・フォームの注意喚起に留める)。
  - exercises が無い/空の場合は、種目データが無いのに種目名を捏造せず、
    従来どおり duration/HR/TE 等の全体指標で評価する。
- 比較対象: 同種目の直近実績 (recent_same_type)。改善/悪化があれば数字で。
- 就寝への影響: 終了時刻が就寝計画の3時間以内なら必ず指摘 (深睡眠が削れる)。
- データ品質: distance_m が歩数から見て明らかに小さい (GPS 未捕捉) 等があれば指摘し、
  次回の対策を1つ添える (VO2Max 等の推定が欠測する実害も)。
- tone: 良い内容=good / 注意・警告=caution / 中立=info。
- 日本語。断定しすぎない。絵文字は使わない。
"""

_TOOL: dict[str, Any] = {
    "name": "submit_review",
    "description": "ワークアウトの一言評価を返す。",
    "input_schema": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "評価 (最大160字, 1〜2文)"},
            "tone": {"type": "string", "enum": ["good", "caution", "info"]},
        },
        "required": ["text", "tone"],
    },
}


def _pick_raw(raw: dict | None) -> dict[str, Any]:
    """raw_json から評価に効くフィールドだけ抜く (トークン節約)。"""
    if not raw:
        return {}
    keys = (
        "steps", "averageRunningCadenceInStepsPerMinute", "aerobicTrainingEffect",
        "anaerobicTrainingEffect", "trainingEffectLabel", "differenceBodyBattery",
        "avgPower", "hasPolyline",
    )
    out = {k: raw[k] for k in keys if raw.get(k) is not None}
    zones = {k: raw[k] for k in raw if k.startswith("hrTimeInZone_")}
    if zones:
        out["hr_zones_sec"] = zones
    return out


def _extract_exercise_sets(raw: dict | None) -> list[dict[str, Any]]:
    """raw_json["exercise_sets"]["sets"] (garmin_sync が保存する ACTIVE セット) を取り出す。

    無い/形が壊れている場合は [] (呼び出し側はこれを「種目データなし」として扱い、
    従来どおりの全体指標評価にフォールバックする)。
    """
    if not isinstance(raw, dict):
        return []
    exercise_sets = raw.get("exercise_sets")
    if not isinstance(exercise_sets, dict):
        return []
    sets = exercise_sets.get("sets")
    return sets if isinstance(sets, list) else []


def _summarize_exercise_sets(sets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """ACTIVE セットを種目 (category+name) ごとに集約する (トークン節約 + LLM が
    ボリューム比較・rep レンジ・セット間の落ち込みを判断しやすい形)。
    """
    groups: dict[tuple[Any, Any], list[dict[str, Any]]] = {}
    order: list[tuple[Any, Any]] = []
    for s in sets:
        key = (s.get("category"), s.get("name"))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append({"reps": s.get("reps"), "weight_kg": s.get("weight_kg")})

    out: list[dict[str, Any]] = []
    for key in order:
        items = groups[key]
        reps = [it["reps"] for it in items if it["reps"] is not None]
        volume = sum((it["reps"] or 0) * (it["weight_kg"] or 0) for it in items)
        out.append({
            "category": key[0],
            "name": key[1],
            "set_count": len(items),
            "set_details": items,
            "rep_range": [min(reps), max(reps)] if reps else None,
            "volume_kg": round(volume, 1) if volume else None,
        })
    return out


def _gather_context(workout_id: str) -> dict[str, Any] | None:
    from app.llm.client import _days_since_last_strength_training
    from app.scoring.sleep_plan import compute_tonight_plan

    with session_scope() as s:
        w = s.get(Workout, workout_id)
        if w is None:
            return None
        same = s.execute(
            select(Workout).where(
                Workout.type == w.type, Workout.id != w.id, Workout.start < w.start
            ).order_by(Workout.start.desc()).limit(5)
        ).scalars().all()

        def brief(x: Workout) -> dict[str, Any]:
            jst = x.start + timedelta(hours=9)
            return {
                "date": jst.date().isoformat(),
                "duration_min": round((x.duration_s or 0) / 60, 1),
                "distance_km": round((x.distance_m or 0) / 1000, 2),
                "avg_hr": x.avg_hr, "max_hr": x.max_hr, "training_load": x.training_load,
            }

        ctx = {
            "workout": {
                **brief(w),
                "type": w.type,
                "start_jst": (w.start + timedelta(hours=9)).strftime("%H:%M"),
                "kcal": w.kcal,
                **_pick_raw(w.raw_json),
            },
            "recent_same_type": [brief(x) for x in same],
        }

        # 筋トレ系で exerciseSets が取れている場合のみ、種目単位の詳細評価用データを足す。
        # 無ければキーごと省略し、システムプロンプト側のフォールバック指示に委ねる
        # (種目データが無いのに LLM に種目名を捏造させない)。
        exercise_sets = _extract_exercise_sets(w.raw_json)
        if exercise_sets:
            ctx["workout"]["exercises"] = _summarize_exercise_sets(exercise_sets)
            ctx["user_injury_notes"] = get_settings().user_injury_notes
            recent_exercise_sessions = []
            for x in same:
                x_sets = _extract_exercise_sets(x.raw_json)
                if not x_sets:
                    continue
                recent_exercise_sessions.append({
                    "date": (x.start + timedelta(hours=9)).date().isoformat(),
                    "exercises": _summarize_exercise_sets(x_sets),
                })
            if recent_exercise_sessions:
                ctx["recent_exercise_sessions"] = recent_exercise_sessions
    try:
        from app.api.workout_review import _est_vo2max
        with session_scope() as s2:
            w2 = s2.get(Workout, workout_id)
            ctx["est_vo2max"] = _est_vo2max(s2, w2) if w2 else None
    except Exception:
        ctx["est_vo2max"] = None
    try:
        ctx["tonight_plan"] = compute_tonight_plan(app_today())
    except Exception:
        ctx["tonight_plan"] = None
    try:
        ctx["days_since_strength"] = _days_since_last_strength_training(app_today())
    except Exception:
        ctx["days_since_strength"] = None
    return ctx


async def generate_review(workout_id: str) -> dict[str, Any] | None:
    """LLM で評価を生成。api_key 無し/失敗/対象なしは None。"""
    settings = get_settings()
    if not settings.anthropic_api_key:
        return None
    ctx = _gather_context(workout_id)
    if ctx is None:
        return None
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
                "content": "このワークアウトを評価してください:\n"
                + json.dumps(ctx, ensure_ascii=False, default=str),
            }],
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": "submit_review"},
        )
    except Exception as exc:
        logger.warning("workout_review_failed", error=str(exc))
        return None
    for block in resp.content:
        if getattr(block, "type", None) == "tool_use":
            inp = dict(block.input or {})
            text = str(inp.get("text") or "").strip()[:400]
            tone = inp.get("tone") if inp.get("tone") in ("good", "caution", "info") else "info"
            if text:
                return {"text": text, "tone": tone, "model": settings.llm_model}
    return None
