"""LLM が使えない時に構造化 advice (headline / focus / actions / rationale) を生成する。

# 優先順位 (上から順に拾い、上限 3 件に絞る)
1. critical alerts (危険検知) — そのまま action 化
2. warning alerts
3. カフェイン推奨 (recommended_mg or 服用 cutoff)
4. Focus ピーク窓 (高い時の "深い思考タスク窓")
5. 睡眠 / 入浴 タイミング (tonight_plan)
6. 気圧 warning/severe 時の予防ケア

# 設計原則
- LLM の prompt と同じく「子育て中、3 件まで、最小労力」を踏襲
- 各 action は time_jst (現在時刻以降) + category + priority を持つ
- LLM advice と互換 schema を返す (frontend は LLM 由来と同じ表示)
"""

from __future__ import annotations

from datetime import datetime, timedelta, time as time_type
from typing import Any
from zoneinfo import ZoneInfo


def build_fallback_advice(
    *,
    now: datetime,
    alerts: list[dict[str, Any]] | None = None,
    caffeine: dict[str, Any] | None = None,
    focus: dict[str, Any] | None = None,
    tonight_plan: dict[str, Any] | None = None,
    pressure: dict[str, Any] | None = None,
    morning_light: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """構造化 advice payload を生成する。

    Returns:
        ``{"headline": str, "focus": str, "actions": [...], "rationale": str}``
    """
    actions: list[dict[str, Any]] = []
    rationale_parts: list[str] = []
    used_codes: set[str] = set()

    # --- 1. critical / warning alerts ---
    for alert in alerts or []:
        if len(actions) >= 3:
            break
        sev = alert.get("severity")
        if sev not in ("critical", "warning"):
            continue
        priority = "critical" if sev == "critical" else "high"
        category = _category_for_alert(alert.get("code", ""))
        action_time = _suggest_alert_time(alert.get("code", ""), now)
        actions.append(
            {
                "time_jst": action_time,
                "title": _shorten(alert.get("action", alert.get("title", "")), 40),
                "duration_min": _duration_for_alert(alert.get("code", "")),
                "category": category,
                "priority": priority,
                "why": _shorten(alert.get("detail", ""), 80),
            }
        )
        used_codes.add(alert.get("code", ""))
        rationale_parts.append(f"{alert.get('title', '')}")

    # --- 2. カフェイン推奨 ---
    if caffeine and caffeine.get("available") and len(actions) < 3:
        rec_mg = caffeine.get("recommended_mg")
        coffee_g = caffeine.get("instant_coffee_g")
        if rec_mg and coffee_g:
            actions.append(
                {
                    "time_jst": _fmt_hhmm(now + timedelta(minutes=5)),
                    "title": f"コーヒー {coffee_g} g (≈{rec_mg} mg)",
                    "duration_min": 5,
                    "category": "nutrition",
                    "priority": "mid",
                    "why": (
                        caffeine.get("reason")
                        or "就寝までの薬物動態モデルに沿った推奨量"
                    ),
                }
            )
            rationale_parts.append(f"カフェイン {rec_mg}mg 摂取可能")
        elif caffeine.get("recommended_mg") is None and caffeine.get("reason"):
            # 飲まないほうが良い理由を rationale に転記
            rationale_parts.append("カフェイン非推奨: " + caffeine["reason"])

    # --- 3. Focus ピーク窓 (集中タスク窓) ---
    if focus and len(actions) < 3:
        windows = focus.get("peak_windows") or []
        future_windows = [
            w for w in windows if _is_future_or_now(w.get("start", ""), now)
        ]
        if future_windows:
            w = future_windows[0]
            actions.append(
                {
                    "time_jst": w["start"],
                    "title": f"ディープワーク窓 ({w['start']}–{w['end']})",
                    "duration_min": _window_duration_min(
                        w["start"], w["end"]
                    ),
                    "category": "focus",
                    "priority": "mid",
                    "why": (
                        f"予測集中スコア平均 {int(w.get('avg_score', 0))}/100、"
                        "重要な判断や創造的作業に充てる"
                    ),
                }
            )
            rationale_parts.append(f"集中ピーク窓 {w['start']}–{w['end']}")

    # --- 4. 入浴 / 就寝のタイミング (睡眠不足アラート無しの時のみ) ---
    if tonight_plan and len(actions) < 3:
        bath = tonight_plan.get("bath")
        bedtime = tonight_plan.get("bedtime")
        # 既存 actions と被らない場合のみ
        has_sleep_alert = any(
            c in used_codes
            for c in ("chronic_sleep_deficit", "recovery_failure")
        )
        if bath and not has_sleep_alert and _is_future(bath, now):
            actions.append(
                {
                    "time_jst": bath,
                    "title": f"入浴 ({bath}) → 就寝 {bedtime or '-'}",
                    "duration_min": 30,
                    "category": "recovery",
                    "priority": "mid",
                    "why": "入浴 90 分後の深部体温降下で入眠が促される",
                }
            )

    # --- 5. 気圧 warning/severe ---
    if (
        pressure
        and pressure.get("risk_level") in ("warning", "severe")
        and len(actions) < 3
        and "pressure_migraine_trigger" not in used_codes
    ):
        actions.append(
            {
                "time_jst": _fmt_hhmm(now + timedelta(minutes=10)),
                "title": "水分 500ml + 暗所 5 分",
                "duration_min": 10,
                "category": "recovery",
                "priority": "high" if pressure["risk_level"] == "severe" else "mid",
                "why": pressure.get("risk_reason", "気圧降下に対する予防ケア"),
            }
        )

    # --- headline / focus 文 ---
    headline = _build_headline(alerts, caffeine, focus, pressure)
    focus_text = _build_focus_text(actions, alerts)

    rationale = (
        "（LLM 不通のためルールベースで生成）" + " / ".join(rationale_parts[:3])
        if rationale_parts
        else "（LLM 不通のためルールベースで生成）コンディションは中庸、メンテナンス継続"
    )

    return {
        "headline": headline,
        "focus": focus_text,
        "actions": actions,
        "rationale": rationale,
    }


# ----- helpers -----


def _category_for_alert(code: str) -> str:
    if code in ("chronic_sleep_deficit", "recovery_failure"):
        return "rest"
    if code in ("hrv_chronic_decline", "caffeine_dependency_cycle"):
        return "recovery"
    if code == "weight_loss":
        return "nutrition"
    if code in ("moh_risk_high", "moh_risk_mid"):
        return "other"
    if code == "pressure_migraine_trigger":
        return "recovery"
    return "other"


def _suggest_alert_time(code: str, now: datetime) -> str:
    """alert ごとの自然な実行時刻を提案。"""
    if code == "chronic_sleep_deficit":
        # ナップは 14-15 時、それを過ぎたら今すぐ
        nap_t = now.replace(hour=14, minute=30, second=0, microsecond=0)
        if nap_t <= now:
            return _fmt_hhmm(now + timedelta(minutes=10))
        return _fmt_hhmm(nap_t)
    if code == "caffeine_dependency_cycle":
        nap_t = now.replace(hour=14, minute=30, second=0, microsecond=0)
        if nap_t <= now:
            return _fmt_hhmm(now + timedelta(minutes=15))
        return _fmt_hhmm(nap_t)
    if code in ("hrv_chronic_decline",):
        # ボックスブレシングは朝晩
        return _fmt_hhmm(now + timedelta(minutes=15))
    if code == "weight_loss":
        # 夕食前くらい
        dinner = now.replace(hour=19, minute=0, second=0, microsecond=0)
        if dinner > now:
            return _fmt_hhmm(dinner)
        return _fmt_hhmm(now + timedelta(minutes=30))
    if code in ("moh_risk_mid", "moh_risk_high"):
        # 平日 10:00 を提案 (受診予約のリマインダー)
        target = now.replace(hour=10, minute=0, second=0, microsecond=0)
        if target <= now:
            target = target + timedelta(days=1)
        return _fmt_hhmm(target)
    # 今すぐ枠
    return _fmt_hhmm(now + timedelta(minutes=10))


def _duration_for_alert(code: str) -> int:
    return {
        "chronic_sleep_deficit": 20,
        "hrv_chronic_decline": 5,
        "recovery_failure": 15,
        "weight_loss": 15,
        "moh_risk_mid": 10,
        "moh_risk_high": 10,
        "caffeine_dependency_cycle": 20,
        "pressure_migraine_trigger": 15,
    }.get(code, 10)


def _shorten(s: str, n: int) -> str:
    if not s:
        return ""
    return s if len(s) <= n else s[: n - 1] + "…"


def _fmt_hhmm(dt: datetime) -> str:
    # round to next 5 min
    minute = ((dt.minute // 5) + 1) * 5
    extra_h, minute = divmod(minute, 60)
    out = dt.replace(minute=minute, second=0, microsecond=0) + timedelta(hours=extra_h)
    return out.strftime("%H:%M")


def _is_future(hhmm: str, now: datetime) -> bool:
    """HH:MM の時刻が今より後か (同じ日内)。"""
    try:
        h, m = hhmm.split(":")
        target = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
        return target > now
    except Exception:
        return False


def _is_future_or_now(hhmm: str, now: datetime) -> bool:
    try:
        h, m = hhmm.split(":")
        target = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
        return target >= now - timedelta(minutes=30)
    except Exception:
        return False


def _window_duration_min(start: str, end: str) -> int:
    try:
        sh, sm = (int(x) for x in start.split(":"))
        eh, em = (int(x) for x in end.split(":"))
        dur = (eh * 60 + em + 30) - (sh * 60 + sm)
        return max(10, min(180, dur))
    except Exception:
        return 60


def _build_headline(
    alerts: list[dict[str, Any]] | None,
    caffeine: dict[str, Any] | None,
    focus: dict[str, Any] | None,
    pressure: dict[str, Any] | None,
) -> str:
    if alerts:
        critical = [a for a in alerts if a.get("severity") == "critical"]
        if critical:
            return _shorten(critical[0].get("title", "要注意"), 25)
        warning = [a for a in alerts if a.get("severity") == "warning"]
        if warning:
            return _shorten(warning[0].get("title", "要注意"), 25)

    if pressure and pressure.get("risk_level") in ("warning", "severe"):
        return "気圧降下、予防ケアを"

    if focus and (focus.get("level") == "high"):
        return "集中向き、ピーク窓を活かす"

    if caffeine and caffeine.get("recommended_mg"):
        return "コンディション中庸、メンテナンス日"

    return "コンディション安定、現状維持で OK"


def _build_focus_text(
    actions: list[dict[str, Any]], alerts: list[dict[str, Any]] | None
) -> str:
    critical_alerts = [
        a for a in (alerts or []) if a.get("severity") == "critical"
    ]
    if critical_alerts:
        return _shorten(
            critical_alerts[0].get("detail", "")
            + " 最小労力の対応を提示します。",
            280,
        )
    if not actions:
        return "コンディションは安定。今日は特別なアクションなしで維持してください。"
    parts = [
        f"優先 {len(actions)} 件を抽出。",
        "上から順に取り組めば最低限の状態維持に十分です。",
    ]
    return " ".join(parts)
