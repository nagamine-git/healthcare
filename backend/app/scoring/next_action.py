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
    days_since_strength: int | None = None      # 最後の筋トレからの日数。None=記録なし
    trained_today: bool = False                 # 今日すでに何かトレーニング済みか
    morning_bb: float | None = None             # 今朝の Body Battery (6時固定・回復状態の代理)
    strength_days_14: int = 0                   # 直近14日の筋トレ日数 (週頻度の判定)
    last_night_min: float | None = None         # 前夜 (target 付け) の総睡眠分。睡眠負債の算定に使う
    target_sleep_min: int = 480                 # 目標睡眠分 (負債の基準。settings.target_sleep_min)
    sleep_experiment: dict[str, Any] | None = None  # 今夜の睡眠実験 (探索/活用/交絡崩し) の提案
    atlas_focus: dict[str, Any] | None = None  # 全体マップで「達成度低×重み高」の最優先領域


# --- 仮眠の科学ベース設計パラメータ ---
# 深睡眠 (N3) に入る前に起きれば睡眠慣性 (grogginess) を避けられる → パワーナップ上限20分。
# 30-60分は最悪の「グロッグ帯」なので絶対に提案しない。大きな睡眠負債があり時間に余裕が
# あるときだけ、1睡眠周期 (約90分) を完走して REM 末で目覚める案に切り替える。
# 遅い仮眠は夜間の睡眠圧 (アデノシン) を削るので、16:00 か 就寝6時間前の早い方までに終える。
_POWER_NAP_MAX_MIN = 20
_POWER_NAP_MIN_MIN = 10          # これ未満しか取れないなら仮眠の価値が薄い → 提案しない
_FULL_CYCLE_MIN = 90
_NAP_DEBT_FOR_CYCLE_MIN = 90     # 前夜がこの分以上不足していればフルサイクルを正当化
_NAP_LATEST_CLOCK = time(16, 0)  # これ以降に終わる仮眠は夜間睡眠を削る
_NAP_BEDTIME_GUARD_H = 6         # 就寝この時間前以降は仮眠しない (睡眠圧を残す)


def recommend_nap(
    now: datetime,
    bb_current: float | None,
    last_night_min: float | None,
    bedtime: datetime | None,
    target_sleep_min: int,
) -> dict[str, Any] | None:
    """科学ベースの仮眠プランを返す。発火条件を満たさなければ None。

    返り値: {minutes, kind ("power"|"cycle"), wake_by (datetime), cutoff (datetime), debt}
    now は JST naive。bedtime は同日の HH:MM を表す datetime か None。
    """
    # 発火はエネルギー枯渇時のみ (従来踏襲)。午前11時より前は昼夜リズム的に非推奨。
    if bb_current is None or bb_current >= 25:
        return None
    if now.hour + now.minute / 60 < 11:
        return None
    # カットオフ = min(16:00, 就寝6時間前)。仮眠はこの時刻までに「終える」。
    cutoff = datetime.combine(now.date(), _NAP_LATEST_CLOCK)
    if bedtime is not None:
        guard = bedtime - timedelta(hours=_NAP_BEDTIME_GUARD_H)
        if guard < cutoff:
            cutoff = guard
    available = (cutoff - now).total_seconds() / 60
    if available < _POWER_NAP_MIN_MIN:
        return None  # もう遅い — 夜まで我慢するのが正解
    debt = max(0.0, target_sleep_min - last_night_min) if last_night_min is not None else 0.0
    if debt >= _NAP_DEBT_FOR_CYCLE_MIN and available >= _FULL_CYCLE_MIN + 5:
        minutes, kind = _FULL_CYCLE_MIN, "cycle"
    else:
        # パワーナップ: 20分上限。使える時間が短ければ詰める (最低10分)。30-60帯は構造上不可能。
        minutes = int(max(_POWER_NAP_MIN_MIN, min(_POWER_NAP_MAX_MIN, available)))
        kind = "power"
    return {
        "minutes": minutes,
        "kind": kind,
        "wake_by": now + timedelta(minutes=minutes),
        "cutoff": cutoff,
        "debt": debt,
    }


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
    plan = recommend_nap(now, inp.bb_current, inp.last_night_min, bedtime, inp.target_sleep_min)
    if plan is not None:
        wake = plan["wake_by"].strftime("%H:%M")
        cutoff = plan["cutoff"].strftime("%H:%M")
        if plan["kind"] == "cycle":
            add("nap", 75, f"90分の仮眠（1睡眠周期・{wake} 起床）",
                f"前夜が目標比 -{int(plan['debt'])}分 — 1周期(約90分)を完走すれば REM 末で"
                f"目覚めやすく慣性が小さい。{cutoff} までに終える", None)
        else:
            m = plan["minutes"]
            add("nap", 75, f"{m}分のパワーナップ（{wake} までに起床）",
                f"Body Battery {int(inp.bb_current)} — {m}分で深睡眠に入る前に起き睡眠慣性を回避。"
                f"夜の睡眠を守るため {cutoff} 以降は不可", None)
    if inp.stress_recent is not None and inp.stress_recent >= 70:
        add("stress_break", 72, "4-7-8呼吸を2分 (画面から離れる)",
            f"直近30分のストレス平均 {int(inp.stress_recent)} — 高止まり中", None)

    # --- 4.5 トレーニングギャップ (筋トレ/HIIT/ラッキング) ---
    # 可否は「今のBB」ではなく「今朝のBB (回復状態の代理)」で見る。夜は誰でもBBが自然に
    # 下がるので、それで抑制すると under-training を助長する (鶏卵)。週の筋トレ頻度が
    # 目標 (週3回=14日6回) 未満なら積極的に背中を押す。
    behind = inp.strength_days_14 < 6  # 週3回=14日6回 未満なら頻度不足
    if (
        inp.days_since_strength is not None and inp.days_since_strength >= 2
        and not inp.trained_today
        and 8 <= hour < 21
        and (inp.morning_bb is None or inp.morning_bb >= 30)  # 本当に低回復の朝だけ休む
    ):
        n = inp.days_since_strength
        pri = 56
        if behind:
            pri = 70 if n >= 5 else 66  # 頻度不足なら底上げ (water/protein より上)
        elif n >= 5:
            pri = 65
        can_high = (inp.morning_bb or 0) >= 60
        menu = "筋トレ / HIIT / ラッキング" if can_high else "筋トレ (短時間でも可)"
        week_n = inp.strength_days_14  # 直近14日だが「今週」の体感として提示
        why = f"前回の筋トレから{n}日 / 直近2週で{week_n}回"
        if behind:
            why += "（目標 週3回に不足 — 積極的に刺激を）"
        else:
            why += " — 筋タンパク合成は48-72hで基線に戻る"
        # 就寝3時間前以降なら短時間を促す
        bed = _parse_hhmm((inp.tonight or {}).get("bedtime"), now.date())
        if bed and now >= bed - timedelta(hours=3):
            menu = "軽めの筋トレ (就寝2h前までに短時間で)"
        add("training_gap", pri, menu, why, None)

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

    # --- 6.4 全体マップの主戦場: 達成度が低く優先(重み)が高い領域を「いまコレ」に ---
    af = inp.atlas_focus
    if af and af.get("pri", 0) >= 30:
        # 優先度 = 55 + スケール。伸びしろ(100-score)×重み が大きいほど上げ、ルーティン
        # (水/プロテイン/学習)より前に出す。安全網(アラート)より下に収める(最大 ~90)。
        pri = 55 + min(35.0, af["pri"] * 0.18)
        add("atlas_focus", round(pri),
            f"『{af['label']}』に一手を割く (達成 {int(af['score'])} / 優先 ×{af['weight']:.1f})",
            "達成度が低く優先の高い領域。伸びしろ×重みが最大 — ここが一番効く", "#tab-summary")

    # --- 6.5 就寝前: 今夜の睡眠実験 (何で寝るべきか / データ取得のための探索+活用) ---
    se = inp.sleep_experiment
    if se and hour >= 19 and not inp.intervention_logged:
        add("sleep_experiment", 60, str(se.get("text", "今夜の睡眠介入を決める")),
            str(se.get("reason", "")), None)

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
    inp.target_sleep_min = s.target_sleep_min

    def safe(fn):
        try:
            fn()
        except Exception as exc:
            logger.info("next_action_gather_failed", error=str(exc))

    def _alerts():
        from app.scoring.profile import resolve_profile
        from app.scoring.wellbeing_alerts import evaluate_alerts, to_dict
        # 低体重下限は身長ベースの BMI18.5 で(dashboard と統一)。目標−1 は誤り(偽陽性の原因)。
        prof = resolve_profile()
        bmi_floor = round(18.5 * (prof.height_cm / 100) ** 2, 1)
        with session_scope() as db:
            inp.alerts = [to_dict(a) for a in evaluate_alerts(
                db, target,
                target_weight_kg=prof.target_weight_kg,
                weight_lower_kg=bmi_floor,
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
            # 今朝の BB (回復状態の代理。夜の自然低下と区別する)
            from app.models import BodyBatteryDaily

            mbb = db.execute(
                select(BodyBatteryDaily.morning_value).where(BodyBatteryDaily.date == target)
            ).scalar()
            inp.morning_bb = float(mbb) if mbb is not None else None
            # 前夜 (target 付け) の総睡眠分 — 仮眠の長さ算定 (睡眠負債) に使う
            from app.models import SleepSession

            ln = db.execute(
                select(SleepSession.total_min).where(SleepSession.date == target)
            ).scalar()
            inp.last_night_min = float(ln) if ln is not None else None

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

    def _training():
        from app.llm.client import _days_since_last_strength_training, _strength_days_in_window
        from app.models import Workout
        from app.scoring.timewindow import jst_day_bounds

        inp.days_since_strength = _days_since_last_strength_training(target)
        inp.strength_days_14 = _strength_days_in_window(target, days=14)
        lo, hi = jst_day_bounds(target)
        with session_scope() as db:
            first = db.execute(
                select(Workout.start).where(Workout.start >= lo, Workout.start < hi).limit(1)
            ).scalar()
            inp.trained_today = first is not None

    def _sleep_exp():
        from app.scoring.sleep_interventions import analyze as analyze_interventions
        inp.sleep_experiment = analyze_interventions(target).get("suggestion")

    def _atlas():
        # 全体マップの第1階層で「伸びしろ(100-score)×重み」が最大の領域を拾う
        from app.scoring.atlas import build_atlas
        with session_scope() as db:
            tree = build_atlas(db)
        best = None
        for c in tree.get("children", []):
            sc = c.get("score")
            w = c.get("weight", 1.0)
            if sc is None or w <= 0:
                continue
            pri = max(0.0, 100 - sc) * w
            if best is None or pri > best["pri"]:
                best = {"label": c["label"], "score": sc, "weight": w, "key": c["key"], "pri": pri}
        inp.atlas_focus = best

    for fn in (_alerts, _advice, _tonight, _physio, _nutrition, _logs, _training, _sleep_exp, _atlas):
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
