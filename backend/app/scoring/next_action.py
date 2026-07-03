"""「いまコレ」— 今この瞬間に最も価値のある行動を、サービス内外の全選択肢から1つ提示する。

問題: アプリは大量の情報を出すが「結局いま何をすべきか」を1つに絞らない。
解法: 全ドメイン (装着/生理状態/栄養ペース/記録衛生/資産/学習/就寝準備/LLM助言) の
候補ルールを決定論的スコアで順位付けし、最上位1件 + 次点を返す。

LLM は使わない (毎回瞬時・無料・説明可能)。時刻依存ルールが多いので、純関数
`build_candidates(inputs, now_jst)` に分離してユニットテスト可能にする。
優先度の設計: 安全(アラート) > 今この瞬間の生理 > タイミング固有 > 記録衛生 > 低緊急。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as date_type
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope
from app.logging import get_logger
from app.scoring.timewindow import app_today

logger = get_logger(__name__)


@dataclass
class Inputs:
    """候補生成に使う横断スナップショット。gather 失敗はフィールド単位で None (堅牢)。"""

    alerts: list[dict[str, Any]] = field(default_factory=list)  # {severity,title,action}
    advice_actions: list[dict[str, Any]] = field(default_factory=list)  # {time_jst,title,priority}
    tonight: dict[str, Any] | None = None       # {bath,bedtime,...} HH:MM
    bb_current: float | None = None             # Body Battery 直近値
    stress_recent: float | None = None          # 直近30分の平均ストレス
    minutes_since_hr: float | None = None       # 最後の心拍サンプルからの経過分 (装着検知)
    water_actual_ml: float | None = None
    water_ideal_ml: float | None = None
    protein_actual_g: float | None = None
    protein_ideal_g: float | None = None
    checkin_done: bool = False                  # 今日の主観チェックイン済みか
    intervention_logged: bool = False           # 今夜の介入を記録済みか
    journal_done: bool = False                  # 今日のジャーナル済みか
    cashflow_days_old: int | None = None        # 入出金データの鮮度 (日)。None=データなし


def _parse_hhmm(s: str | None, base: date_type) -> datetime | None:
    if not s:
        return None
    try:
        h, m = s.split(":")
        return datetime.combine(base, time(int(h) % 24, int(m)))
    except Exception:
        return None


def build_candidates(inp: Inputs, now: datetime) -> list[dict[str, Any]]:
    """優先度つき候補リスト (降順ソートは呼び出し側)。now は JST naive。"""
    c: list[dict[str, Any]] = []
    hour = now.hour + now.minute / 60

    def add(key: str, priority: float, title: str, why: str, link: str | None = None):
        c.append({"key": key, "priority": round(priority), "title": title, "why": why, "link": link})

    # --- 1. 安全網: ウェルビーイングアラート (最優先で行動に変換) ---
    for a in inp.alerts:
        sev = a.get("severity")
        action = a.get("action") or a.get("title") or ""
        if sev == "critical":
            add("alert_critical", 95, action, f"⚠ {a.get('title', 'アラート')}(critical)", None)
        elif sev == "warning":
            add("alert_warning", 70, action, f"▲ {a.get('title', 'アラート')}", None)

    # --- 2. LLM助言アクションのうち「いま」が実行時刻のもの (±45分) ---
    for act in inp.advice_actions:
        t = _parse_hhmm(act.get("time_jst"), now.date())
        if t is None or act.get("priority") not in ("high", "critical"):
            continue
        delta_min = (now - t).total_seconds() / 60
        if -45 <= delta_min <= 45:
            when = "いまが実行時刻" if delta_min >= 0 else f"あと{int(-delta_min)}分で時刻"
            add("advice_due", 82, str(act.get("title", "予定アクション")),
                f"今日の計画 {act.get('time_jst')} — {when}", None)

    # --- 3. 就寝準備 (今夜の計画の入浴〜就寝ウィンドウ) ---
    tp = inp.tonight or {}
    bath = _parse_hhmm(tp.get("bath"), now.date())
    bedtime = _parse_hhmm(tp.get("bedtime"), now.date())
    if bath and bedtime and bath - timedelta(minutes=15) <= now <= bedtime:
        add("bedtime_prep", 85, f"入浴 → {tp.get('bedtime')} 就寝の準備に入る",
            f"今夜の計画: 入浴 {tp.get('bath')} / 就寝 {tp.get('bedtime')}。ここを守ると明日が変わる", None)

    # --- 4. いまの生理状態 ---
    if inp.bb_current is not None and inp.bb_current < 25 and 11 <= hour < 19:
        add("nap", 75, "15–20分の仮眠 (またはアイマスクで横になる)",
            f"Body Battery {int(inp.bb_current)} — エネルギー枯渇中。短い仮眠が最も回収効率が高い", None)
    if inp.stress_recent is not None and inp.stress_recent >= 70:
        add("stress_break", 72, "4-7-8呼吸を2分 (画面から離れる)",
            f"直近30分のストレス平均 {int(inp.stress_recent)} — 高止まり中", None)

    # --- 5. 計測の土台: Garmin を着けていない (心拍が途絶) ---
    if inp.minutes_since_hr is not None and inp.minutes_since_hr > 90 and 8 <= hour < 23:
        add("garmin_wear", 68, "Garmin を手首につける",
            f"心拍データが {int(inp.minutes_since_hr)} 分途絶 — 全ての分析の土台が欠測中", None)

    # --- 6. カフェインカットオフ (就寝6時間前) ---
    if bedtime:
        cutoff = bedtime - timedelta(hours=6)
        d = (now - cutoff).total_seconds() / 60
        if -30 <= d <= 15:
            when = "を過ぎた — 以降は控える" if d >= 0 else f"まで {int(-d)} 分 — 飲むなら今が最後"
            add("caffeine_cutoff", 58, f"カフェインは {cutoff.strftime('%H:%M')} {when}",
                "就寝6時間前ルール (半減期): 以降の摂取は深睡眠を削る", None)

    # --- 7. 栄養ペース (7:00-23:00 の経過割合に対する不足) ---
    if inp.water_actual_ml is not None and inp.water_ideal_ml:
        frac = min(1.0, max(0.0, (hour - 7) / 16))
        expected = inp.water_ideal_ml * frac
        deficit = expected - inp.water_actual_ml
        if deficit >= 300:
            add("water", 55 if deficit >= 500 else 45,
                f"水を {min(500, int(deficit // 100 * 100))}ml 飲む",
                f"今日の水分が目標ペース比 -{int(deficit)}ml", "#tab-health")
    if (
        inp.protein_actual_g is not None and inp.protein_ideal_g
        and hour >= 15 and (inp.protein_ideal_g - inp.protein_actual_g) >= 40
    ):
        gap = inp.protein_ideal_g - inp.protein_actual_g
        add("protein", 50, "プロテイン (or タンパク質20-30g) を摂る",
            f"タンパク質が目標まであと {int(gap)}g — 夕方以降は分割摂取が有利", "#tab-health")

    # --- 8. 記録衛生 (分析の質を保つ日次ログ) ---
    if not inp.checkin_done and hour >= 10:
        add("checkin", 45, "体調チェックイン (気分/活力/ストレス 4タップ)",
            "今日の主観が未記録 — 客観データと突き合わせる要", "quicklog")
    if not inp.intervention_logged and hour >= 18:
        add("intervention_log", 48, "今夜の睡眠介入 (耳栓/アイマスク等) を記録",
            "n-of-1 検証は毎晩の記録が命 — 未記録の夜は分析から消える", "quicklog")
    if not inp.journal_done and hour >= 20:
        add("journal", 38, "今日のジャーナルを書く", "今日の分がまだ空", "#journal")

    # --- 9. 低緊急・定期 ---
    if inp.cashflow_days_old is None or inp.cashflow_days_old > 35:
        old = "未取込" if inp.cashflow_days_old is None else f"{inp.cashflow_days_old}日前"
        add("money_update", 35, "入出金CSV・資産残高を更新する",
            f"資産データが {old} — ランウェイ/配分の数字が古い", "#finance")
    if 14 <= hour < 22:
        add("learning", 30, "学習ブロック 25分 (Rust など積み残し)",
            "空いた枠の既定投資 — 上位の用事がなければこれ", "#tab-learning")

    return c


def _collect(target: date_type) -> tuple[Inputs, datetime]:
    """DB から Inputs を組む。各 gather は失敗しても他を巻き込まない。"""
    s = get_settings()
    tz = ZoneInfo(s.app_tz)
    now = datetime.now(tz).replace(tzinfo=None)
    inp = Inputs()

    def safe(fn):
        try:
            fn()
        except Exception as exc:
            logger.info("next_action_gather_failed", error=str(exc))

    def _alerts():
        from app.scoring.wellbeing_alerts import evaluate_alerts, to_dict
        with session_scope() as db:
            inp.alerts = [to_dict(a) for a in evaluate_alerts(
                db, target,
                target_weight_kg=s.target_weight_kg,
                weight_lower_kg=getattr(s, "weight_lower_kg", s.target_weight_kg - 1.0),
            )]

    def _advice():
        from app.models import LlmComment
        with session_scope() as db:
            row = db.execute(
                select(LlmComment).where(LlmComment.date == target)
                .order_by(LlmComment.generated_at.desc()).limit(1)
            ).scalars().first()
            payload = row.payload if row else None
            inp.advice_actions = list((payload or {}).get("actions") or [])

    def _tonight():
        from app.scoring.sleep_plan import compute_tonight_plan
        inp.tonight = compute_tonight_plan(target)

    def _physio():
        from app.models import BodyBattery, MetricSample
        with session_scope() as db:
            bb = db.execute(
                select(BodyBattery.value).order_by(BodyBattery.ts.desc()).limit(1)
            ).scalar()
            inp.bb_current = float(bb) if bb is not None else None
            now_utc = datetime.utcnow()
            last_hr = db.execute(
                select(MetricSample.ts)
                .where(MetricSample.metric_key.in_(("heart_rate_avg", "heart_rate_max")))
                .order_by(MetricSample.ts.desc()).limit(1)
            ).scalar()
            if last_hr is not None:
                inp.minutes_since_hr = (now_utc - last_hr).total_seconds() / 60
            stress_rows = db.execute(
                select(MetricSample.value).where(
                    MetricSample.metric_key == "stress",
                    MetricSample.value >= 0,
                    MetricSample.ts >= now_utc - timedelta(minutes=30),
                )
            ).scalars().all()
            if stress_rows:
                inp.stress_recent = sum(float(v) for v in stress_rows) / len(stress_rows)

    def _nutrition():
        from app.scoring.nutrition import aggregate_nutrition
        with session_scope() as db:
            n = aggregate_nutrition(db, target)
        targets = n.get("targets") or {}
        w = n.get("water_ml") or {}
        p = n.get("protein_g") or {}
        inp.water_actual_ml = w.get("today_actual") or 0.0
        inp.water_ideal_ml = (targets.get("water_ml") or {}).get("ideal")
        inp.protein_actual_g = p.get("today_actual") or 0.0
        inp.protein_ideal_g = (targets.get("protein_g") or {}).get("ideal")

    def _logs():
        from app.api.sleep_intervention import _target_date
        from app.models import CashflowTx, JournalEntry, SleepInterventionLog, SubjectiveCheckin
        with session_scope() as db:
            inp.checkin_done = db.get(SubjectiveCheckin, target) is not None
            inp.intervention_logged = db.get(SleepInterventionLog, _target_date()) is not None
            inp.journal_done = db.get(JournalEntry, target) is not None
            last_tx = db.execute(select(CashflowTx.date).order_by(CashflowTx.date.desc()).limit(1)).scalar()
            inp.cashflow_days_old = (target - last_tx).days if last_tx else None

    for fn in (_alerts, _advice, _tonight, _physio, _nutrition, _logs):
        safe(fn)
    return inp, now


def compute_next_action(target: date_type | None = None) -> dict[str, Any]:
    target = target or app_today()
    inp, now = _collect(target)
    cands = sorted(build_candidates(inp, now), key=lambda x: -x["priority"])
    if not cands:
        tp = inp.tonight or {}
        return {
            "primary": {
                "key": "all_clear", "priority": 0,
                "title": "いまは整っている — 自由時間",
                "why": f"次の定期アクションは就寝準備 ({tp.get('bath', '--')} 入浴)",
                "link": None,
            },
            "others": [],
            "computed_at": now.isoformat(),
        }
    return {"primary": cands[0], "others": cands[1:5], "computed_at": now.isoformat()}
