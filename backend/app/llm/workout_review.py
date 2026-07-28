"""ワークアウトの AI 評価 (タップ時のみ生成、WorkoutReview に永続化)。

コンテキスト: 当該ワークアウトの実測 (HR/TE/HRゾーン/距離/BB増減) + 同種目の直近比較 +
今夜の就寝計画 + 前回筋トレからの日数。筋トレ系で Garmin exerciseSets (種目/rep/重量) が
取れていれば、種目ごとのボリューム・直近比較も渡す (garmin_sync が Workout.raw_json に
``exercise_sets`` として保存する。無ければ従来どおりの全体指標評価にフォールバックする)。

出力は tool_use で **総合 (overall) + 種目ごと (exercises)** の構造を強制する。
種目ごとのボリューム/rep レンジ/前回比などの「数字」は LLM に語らせず本サーバー側で
決定論的に計算し (`_summarize_exercise_sets` / `_attach_prev_volume`)、LLM には各種目の
短評テキストだけを埋めさせて `_merge_exercise_review` で突き合わせる。数字のハルシネーション
を防ぎ、種目が増減してもズレない (category+name で突き合わせるため順序非依存)。
GPS 欠測 (距離が歩数と乖離) 等のデータ品質問題にも言及させる。
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
比較して評価します。出力は「総合 (overall)」1つと、種目データがあれば「種目ごと (exercises)」
の短評をそれぞれ返してください。

# 総合 (overall, 最大200字)
- セッション全体のボリューム・所要時間・強度・部位バランスを俯瞰し、次回への一手を1つ添える。
- 就寝への影響: 終了時刻が就寝計画の3時間以内なら必ず指摘 (深睡眠が削れる)。
- データ品質: distance_m が歩数から見て明らかに小さい (GPS 未捕捉) 等があれば指摘し、
  次回の対策を1つ添える (VO2Max 等の推定が欠測する実害も)。
- workout.exercises が無い/空の場合はこれまでどおり duration/HR/TE 等の全体指標だけで評価する
  (種目データが無いのに種目名を捏造しない)。

# 種目ごと (exercises, 各最大140字。workout.exercises が空なら空配列でよい)
- workout.exercises の **各要素と同じ category / name をそのまま返す** こと
  (突き合わせに使うので改変しない。要素数もできる限り一致させる)。
- set_count・rep_range・volume_kg・prev_volume_kg (前回同種目) は既に数値が渡っているので、
  それを踏まえた一言のみを書く (数字を書き直す必要はないが、増減の傾向には触れてよい)。
- rep_range が目的とズレていないか触れる (目安: 筋肥大 6-12 rep、筋力寄り 1-5 rep)。
- set_details (セット順の reps/weight_kg) で終盤の落ち込みが大きい場合は疲労のサインとして触れる。
- user_injury_notes にある既往 (腰への高負荷ヒンジ系の重量上限など) に抵触する種目・重量が
  あれば、その種目のコメントで最優先・安全側に指摘する。医療的な診断/治療の助言はしない
  (トレーニング強度・フォームの注意喚起に留める)。

# 共通
- 具体数字で1点だけ刺す (良かった点 or 注意点)。総花的な感想は書かない。
- tone: 良い内容=good / 注意・警告=caution / 中立=info。
- 日本語。断定しすぎない。絵文字は使わない。
"""

_TOOL: dict[str, Any] = {
    "name": "submit_review",
    "description": "ワークアウトの評価 (総合 + 種目ごと) を返す。",
    "input_schema": {
        "type": "object",
        "properties": {
            "overall": {
                "type": "object",
                "description": "セッション全体の評価",
                "properties": {
                    "text": {"type": "string", "description": "総合評価 (最大200字)"},
                    "tone": {"type": "string", "enum": ["good", "caution", "info"]},
                },
                "required": ["text", "tone"],
            },
            "exercises": {
                "type": "array",
                "description": (
                    "workout.exercises がある場合のみ、各要素と同じ category/name で短評を返す。"
                    "無い/空の場合は空配列。"
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string", "description": "入力と同じ category"},
                        "name": {
                            "type": "string",
                            "description": "入力と同じ name (無ければ空文字)",
                        },
                        "comment": {"type": "string", "description": "この種目の短評 (最大140字)"},
                        "tone": {"type": "string", "enum": ["good", "caution", "info"]},
                    },
                    "required": ["category", "name", "comment", "tone"],
                },
            },
        },
        "required": ["overall", "exercises"],
    },
}

# Garmin exerciseSets の name (詳細種目) → 日本語表示名。実データ (garmin_sync 保存分) と
# 過去のワークアウトログに出現するものを優先して収録。未収録の name は category のラベルに
# フォールバックする。
_NAME_JA: dict[str, str] = {
    "GOBLET_SQUAT": "ゴブレットスクワット",
    "ALTERNATING_DUMBBELL_LUNGE": "オルタネイティングダンベルランジ",
    "DUMBBELL_LUNGE": "ダンベルランジ",
    "WALKING_LUNGE": "ウォーキングランジ",
    "BULGARIAN_SPLIT_SQUAT": "ブルガリアンスクワット",
    "BARBELL_BENCH_PRESS": "バーベルベンチプレス",
    "DUMBBELL_BENCH_PRESS": "ダンベルベンチプレス",
    "BENT_OVER_ROW": "ベントオーバーロー",
    "ONE_ARM_ROW": "ワンアームロー",
    "SEATED_ROW": "シーテッドロー",
    "BICEPS_CURL": "バイセップスカール",
    "HAMMER_CURL": "ハンマーカール",
    "STANDING_CALF_RAISE": "スタンディングカーフレイズ",
    "SINGLE_LEG_DEADLIFT": "片脚デッドリフト",
    "ROMANIAN_DEADLIFT": "ルーマニアンデッドリフト",
}

# category (種目大分類) → 日本語ラベル。name が未収録/null (Garmin が詳細検出できなかった
# 場合。実データで CALF_RAISE/PLANK は name=null になる) のフォールバック先。
_CATEGORY_JA: dict[str, str] = {
    "SQUAT": "スクワット系",
    "LUNGE": "ランジ系",
    "CALF_RAISE": "カーフレイズ",
    "PLANK": "プランク",
    "ROW": "ロー (背中)",
    "CURL": "カール (上腕二頭筋)",
    "BENCH_PRESS": "ベンチプレス",
    "DEADLIFT": "デッドリフト",
    "HYPEREXTENSION": "バックエクステンション",
    "LEG_RAISE": "レッグレイズ",
    "SHOULDER_PRESS": "ショルダープレス",
    "LATERAL_RAISE": "サイドレイズ",
    "TRICEPS_EXTENSION": "トライセップスエクステンション",
    "SHRUG": "シュラッグ",
    "SIT_UP": "シットアップ",
    "CRUNCH": "クランチ",
    "PUSH_UP": "腕立て伏せ",
    "PULL_UP": "懸垂",
    "FLYE": "フライ",
    "CORE": "体幹",
    "HIP_RAISE": "ヒップレイズ",
    "HIP_SWING": "ヒップスイング",
    "LEG_CURL": "レッグカール",
    "LEG_EXTENSION": "レッグエクステンション",
    "TOTAL_BODY": "全身複合",
    "WARM_UP": "ウォームアップ",
}


def _ja_label(category: str | None, name: str | None) -> str:
    """Garmin の category/name (UPPER_SNAKE) を日本語表示名にする。

    name の方が具体的なので優先。name が無い/未収録なら category のラベル、
    どちらも無ければ生の文字列 (未知の新カテゴリでも空白で落ちないように)。
    """
    if name and name in _NAME_JA:
        return _NAME_JA[name]
    if category and category in _CATEGORY_JA:
        return _CATEGORY_JA[category]
    return name or category or "種目不明"


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
            "name_ja": _ja_label(key[0], key[1]),
            "set_count": len(items),
            "set_details": items,
            "rep_range": [min(reps), max(reps)] if reps else None,
            "volume_kg": round(volume, 1) if volume else None,
        })
    return out


def _attach_prev_volume(
    exercises: list[dict[str, Any]], recent_sessions: list[dict[str, Any]]
) -> None:
    """直近セッション (新しい順) から同種目 (category+name) の直近ボリュームを探し、
    prev_volume_kg / volume_delta_kg / volume_delta_pct を付与する (in-place)。

    数字はサーバー側で決定論的に計算する (LLM に前回比を計算させない/ハルシネーション防止)。
    """
    for ex in exercises:
        key = (ex.get("category"), ex.get("name"))
        prev_volume: float | None = None
        for sess in recent_sessions:
            match = next(
                (e for e in sess["exercises"] if (e.get("category"), e.get("name")) == key),
                None,
            )
            if match is not None and match.get("volume_kg") is not None:
                prev_volume = match["volume_kg"]
                break
        ex["prev_volume_kg"] = prev_volume
        if prev_volume is not None and ex.get("volume_kg") is not None:
            ex["volume_delta_kg"] = round(ex["volume_kg"] - prev_volume, 1)
            ex["volume_delta_pct"] = (
                round((ex["volume_kg"] - prev_volume) / prev_volume * 100, 1)
                if prev_volume
                else None
            )
        else:
            ex["volume_delta_kg"] = None
            ex["volume_delta_pct"] = None


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
            exercises = _summarize_exercise_sets(exercise_sets)
            ctx["workout"]["exercises"] = exercises
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
            # 前回同種目比較 (LLM に数字を作らせず決定論的に計算)
            _attach_prev_volume(exercises, recent_exercise_sessions)
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


def _merge_exercise_review(
    computed: list[dict[str, Any]], llm_exercises: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """サーバー側で計算した種目別スタッツ (computed: category/name/set_count/rep_range/
    volume_kg/prev_volume_kg 等) と LLM の短評 (llm_exercises: category/name/comment/tone)
    を category+name で突き合わせる。突き合わせは key ベースなので LLM 側が順序を変えても
    (要素を1つ落としても) 壊れない。一致しない種目には汎用フォールバック文を入れる
    (種目データはあるのに評価が空欄になるのを避ける)。
    """
    llm_map: dict[tuple[Any, Any], dict[str, Any]] = {}
    for e in llm_exercises:
        key = (e.get("category") or None, e.get("name") or None)
        llm_map[key] = e

    out: list[dict[str, Any]] = []
    for ex in computed:
        key = (ex.get("category"), ex.get("name"))
        m = llm_map.get(key)
        item = dict(ex)
        comment = str((m or {}).get("comment") or "").strip()
        if comment:
            item["comment"] = comment[:200]
            tone = (m or {}).get("tone")
            item["tone"] = tone if tone in ("good", "caution", "info") else "info"
        else:
            vol = ex.get("volume_kg")
            item["comment"] = f"{ex.get('set_count', 0)}セット・ボリューム{vol if vol is not None else '—'}kg。"
            item["tone"] = "info"
        out.append(item)
    return out


async def generate_review(workout_id: str) -> dict[str, Any] | None:
    """LLM で評価を生成 (総合 + 種目ごと)。api_key 無し/失敗/対象なしは None。

    戻り値: {"text": 総合評価, "tone": 総合トーン, "model": ..., "exercises": [...] | None}
    exercises は種目データが無いワークアウト (ラン等) では None。
    """
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
            # 種目ごとの短評を複数返しうるので、単一テキストの頃 (400) より余裕を持たせる。
            max_tokens=1500,
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

    computed_exercises = ctx.get("workout", {}).get("exercises") or []

    for block in resp.content:
        if getattr(block, "type", None) != "tool_use":
            continue
        inp = dict(block.input or {})
        overall = inp.get("overall") if isinstance(inp.get("overall"), dict) else {}
        text = str(overall.get("text") or "").strip()[:400]
        if not text:
            continue
        tone = overall.get("tone") if overall.get("tone") in ("good", "caution", "info") else "info"
        llm_exercises = inp.get("exercises") if isinstance(inp.get("exercises"), list) else []
        exercises = (
            _merge_exercise_review(computed_exercises, llm_exercises) if computed_exercises else None
        )
        return {"text": text, "tone": tone, "model": settings.llm_model, "exercises": exercises}
    return None
