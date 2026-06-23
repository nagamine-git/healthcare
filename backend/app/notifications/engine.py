"""「今この瞬間に送るべき通知」を選定する純粋ロジック。

# 設計方針 (通知疲れの回避を最優先)
- 鳴らすのは「明らかにやるべき / 明らかに危険」だけに絞る:
  1. critical アラート → 1 日 1 回まとめて (digest)
  2. priority が critical/high で time_jst を持つ advice アクション → その時刻に
  3. 就寝リマインド (任意) → 目標就寝の少し前に 1 回
- warning/info アラート、時刻なし・急がないアクション (体型計画等) は対象外。
- 出力はあくまで「候補」。実際の送信可否 (重複排除) は service 層が NotificationLog で判定する。
  本モジュールは外部 I/O を一切持たず、与えられた now と素材から候補を組み立てるだけ。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

# 通知の重要度。フロントの showNotification で requireInteraction 等に反映する。
_PRIORITY_RANK = {"critical": 0, "high": 1, "normal": 2}


@dataclass(frozen=True)
class DueNotification:
    """送信候補 1 件。

    dedup_key: 同一日に二重送信しないための冪等キー (NotificationLog の主キー)。
    """

    dedup_key: str
    title: str
    body: str
    tag: str
    url: str
    priority: str  # "critical" | "high" | "normal"


def _parse_hhmm_today(hhmm: str | None, now: datetime) -> datetime | None:
    """"HH:MM" を now と同じ日付・tz の datetime にする。失敗時 None。"""
    if not hhmm:
        return None
    try:
        h, _, m = hhmm.partition(":")
        return now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
    except (ValueError, TypeError):
        return None


def _slug(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:8]


def collect_due_notifications(
    *,
    now: datetime,
    alerts: list[dict[str, Any]] | None = None,
    advice_actions: list[dict[str, Any]] | None = None,
    tonight_plan: dict[str, Any] | None = None,
    bedtime_reminder: bool = True,
    action_window_min: int = 60,
    critical_alert_after_hour: int = 7,
    bedtime_lead_min: int = 15,
) -> list[DueNotification]:
    """now 時点で送るべき通知候補を返す (重要度順)。

    Args:
        now: 現在時刻 (tz-aware, JST 想定)。
        alerts: ``wellbeing_alerts.to_dict`` 形式の dict リスト。
        advice_actions: advice payload の ``actions`` (time_jst/priority/title/why)。
        tonight_plan: ``compute_tonight_plan`` の戻り (bedtime を使う)。
        action_window_min: time_jst を過ぎてから何分まで通知を有効とみなすか。
            サーバ停止明け等に古いリマインドを一斉送信しないためのガード。
        critical_alert_after_hour: critical アラート digest を出し始める時刻 (時)。
            早朝の睡眠中に鳴らさないため既定 7 時。
        bedtime_lead_min: 目標就寝の何分前にリマインドするか。
    """
    out: list[DueNotification] = []
    day = now.date().isoformat()

    # --- 1. critical アラート (1 日 1 回 digest) ---
    criticals = [a for a in (alerts or []) if a.get("severity") == "critical"]
    if criticals and now.hour >= critical_alert_after_hour:
        titles = [a.get("title", "") for a in criticals if a.get("title")]
        out.append(
            DueNotification(
                dedup_key=f"alert:{day}",
                title="⚠️ 健康アラート",
                body=" / ".join(titles) or "状態を確認してください",
                tag="hc-alert",
                url="/",
                priority="critical",
            )
        )

    # --- 2. 時間依存の high/critical アクション ---
    for a in advice_actions or []:
        prio = a.get("priority")
        if prio not in ("critical", "high"):
            continue
        t_str = a.get("time_jst")
        t = _parse_hhmm_today(t_str, now)
        if t is None:
            continue
        delta_min = (now - t).total_seconds() / 60.0
        # 開始時刻以降、かつ window 以内のものだけ「今がその時刻」とみなす。
        if delta_min < 0 or delta_min > action_window_min:
            continue
        title = a.get("title") or "リマインダー"
        out.append(
            DueNotification(
                dedup_key=f"action:{day}:{t_str}:{_slug(title)}",
                title=title,
                body=a.get("why") or "",
                tag=f"hc-action-{t_str}",
                url="/",
                priority="critical" if prio == "critical" else "high",
            )
        )

    # --- 3. 就寝リマインド (任意) ---
    if bedtime_reminder and tonight_plan:
        bedtime = tonight_plan.get("bedtime")
        bt = _parse_hhmm_today(bedtime, now)
        if bt is not None:
            remind_at = bt - timedelta(minutes=bedtime_lead_min)
            delta_min = (now - remind_at).total_seconds() / 60.0
            if 0 <= delta_min <= action_window_min:
                out.append(
                    DueNotification(
                        dedup_key=f"bedtime:{day}",
                        title="そろそろ就寝準備",
                        body=f"今日の目標就寝は {bedtime}。照明を落として整えましょう。",
                        tag="hc-bedtime",
                        url="/",
                        priority="normal",
                    )
                )

    out.sort(key=lambda n: _PRIORITY_RANK.get(n.priority, 9))
    return out
