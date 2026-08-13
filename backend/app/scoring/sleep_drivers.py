"""個人「睡眠ドライバー分析」。

ドライバー (就寝タイミング/規則性・午後のカフェイン・夜の飲酒・運動・活動量・ストレス・
睡眠時間) が、睡眠の質 (効率/深睡眠/スコア/夜間HRV) と翌日パフォーマンス (朝の回復BB/
主観活力) にどう効くかを、本人データで統計的に出す。

手法: 偏頭痛トリガー分析と同じ並べ替え検定 + BH-FDR を流用。各ドライバーを中央値で
高/低に二分し、アウトカム平均差を検定。全ての (アウトカム×ドライバー) を FDR 補正。
件数が少なければ tier=weak (薄く表示)。すべてのアウトカムは「高いほど良い」向きに統一済み。
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope
from app.models import (
    AlcoholIntake,
    BodyBatteryDaily,
    CaffeineIntake,
    DailySummary,
    MetricSample,
    SleepSession,
    SubjectiveCheckin,
    Workout,
)
from app.scoring.caffeine import is_dietary_caffeine
from app.scoring.migraine_stats import benjamini_hochberg, permutation_test
from app.scoring.morning_light import compute_morning_light_score
from app.scoring.timewindow import app_today

_DAYS = 120        # 解析窓
_MIN_PAIRS = 8     # これ以上 & 各群>=_MIN_GROUP で「有意性を語れる (powered)」
_MIN_GROUP = 3     # 高/低 各群の最小数 (powered 判定)
_MIN_PAIRS_PRELIM = 4    # これ以上あれば暫定シグナル (方向+効果量) を出す
_MIN_GROUP_PRELIM = 2    # 暫定シグナルの高/低 各群の最小数
FDR_Q = 0.05

# アウトカム (すべて「高いほど良い」)。(key, ラベル, グループ)
#
# ⚠️ **睡眠効率は睡眠時間と交絡する。** 効率 = 睡眠時間 / 床上時間 なので、
# 短時間で一気に寝落ちした夜ほど高く出る (寝付きが速く中途覚醒も入りにくい)。
# そのため「就寝時刻の乱れ → 効率 改善」のような生理学的に逆に見える行が出ることが
# ある。実データでも irregular×efficiency = 改善 (p=0.013) に対し、同じ irregular の
# sleep_score は 悪化 (p=0.027) と反対を向いた。これは符号バグではなく交絡なので、
# より総合的な sleep_score / deep_min の方を信頼すること。
# 効率単独の「改善」から生活変更を勧めてはいけない (_action_text は改善方向の
# irregular に文言を持たず、結果として助言化されない作りになっている)。
#
# restlessness_inv (体動の少なさ) は上記の交絡への対処として追加した指標。
# 体動回数 (Garmin restlessMomentsCount) は「床上時間に対する睡眠時間の割合」
# ではなく実際の身体の動きそのものを数えるため、効率のように睡眠時間の長短に
# 引きずられにくい (寝付きの速さでは変わらない、時間非依存の質指標)。効率単独では
# 語れない夜も、体動回数となら安全に語れる場面がある。
# ⚠️ 元データは「体動が多いほど悪い」向きなので、符号を反転して格納する
# (他の全アウトカムと同じ「高いほど良い」に統一するため)。
# ⚠️ ただし体動の「絶対回数」は寝ている時間が長いほど機会が増えて自明に増える
# (実データで duration↑→restlessness_inv↓, p=0.0 を確認)。efficiency 等と同じ
# 理由で duration ドライバーの対象からは除外している (analyze() 内)。
_OUTCOMES: list[tuple[str, str, str]] = [
    ("efficiency", "睡眠効率", "quality"),
    ("deep_min", "深睡眠", "quality"),
    ("sleep_score", "睡眠スコア", "quality"),
    ("hrv_overnight", "夜間HRV", "quality"),
    ("restlessness_inv", "体動の少なさ", "quality"),
    ("morning_bb", "翌朝の回復(BB)", "next_day"),
    ("energy", "翌日の活力", "next_day"),
]
# ドライバー (key, ラベル)
#
# ⚠️ morning_light は実測 lux ではない。scoring/morning_light.py が
# 「起床+3h の歩数 (屋内デスクワーク等は歩数が伸びないことを利用した proxy) /
# Apple Watch の time_in_daylight (取得できていれば優先)」から 0-100 に推定した
# 間接指標。lux センサー実測ではないことを混同しないこと。
_DRIVERS: list[tuple[str, str]] = [
    ("midpoint", "就寝が遅い"),
    ("irregular", "就寝時刻の乱れ"),
    ("caffeine_pm", "午後以降のカフェイン(食事性)"),
    ("medication", "頭痛薬の使用"),
    ("alcohol_eve", "夜の飲酒"),
    # ⚠️ ラベルは**実体そのもの**を書く。「活動量」「運動量」は紛らわしく、
    # どちらが歩数でどちらがワークアウト負荷か利用者が判別できなかった。
    ("exercise", "ワークアウト負荷"),   # Workout.training_load (強度×時間)
    ("steps", "日中の歩数"),            # DailySummary.steps (日常の NEAT 寄りの動き)
    ("stress", "ストレス(主観)"),
    ("duration", "睡眠時間"),
    ("morning_light", "朝の光(推定・実測lux不可)"),
    # 外気温を**室温の代理**として使う。暑さは睡眠の質 (特に深睡眠・中途覚醒) を強く
    # 落とすことが知られており、室温そのものは測れないが外気温は日々の変動をよく追う。
    # ⚠️ 代理指標であることをラベルに明示する (室温を測ったと誤解させない)。
    ("temp_night", "夜間の外気温(室温の代理)"),
]


def _jst(ts: datetime) -> datetime:
    return ts + timedelta(hours=9)


def _collect(target: date_type) -> list[dict[str, Any]]:
    """睡眠のある各夜について、アウトカムとドライバーをまとめた行を返す。"""
    start = target - timedelta(days=_DAYS)
    lo = datetime.combine(start - timedelta(days=2), datetime.min.time())
    hi = datetime.combine(target + timedelta(days=1), datetime.min.time())

    with session_scope() as s:
        sleeps = s.execute(
            select(SleepSession).where(SleepSession.date >= start, SleepSession.date <= target)
        ).scalars().all()
        sleep_rows = {
            r.date: {
                "total": r.total_min, "deep": r.deep_min, "awake": r.awake_min,
                "score": r.sleep_score, "hrv": r.hrv_overnight_avg,
            }
            for r in sleeps
        }
        bb = {
            r.date: r.morning_value
            for r in s.execute(
                select(BodyBatteryDaily).where(BodyBatteryDaily.date >= start, BodyBatteryDaily.date <= target)
            ).scalars()
            if r.morning_value is not None
        }
        checkin: dict[date_type, dict[str, Any]] = {}
        for r in s.execute(
            select(SubjectiveCheckin).where(SubjectiveCheckin.date >= start, SubjectiveCheckin.date <= target)
        ).scalars():
            checkin[r.date] = {"energy": r.energy, "stress": r.stress}
        steps = {
            r.date: r.steps
            for r in s.execute(
                select(DailySummary).where(DailySummary.date >= start, DailySummary.date <= target)
            ).scalars()
            if r.steps is not None
        }
        midpoint: dict[date_type, float] = {}
        for ts, v in s.execute(
            select(MetricSample.ts, MetricSample.value)
            .where(MetricSample.metric_key == "sleep_midpoint_hour", MetricSample.ts >= lo, MetricSample.ts < hi)
        ):
            if v is not None:
                midpoint[_jst(ts).date()] = float(v)
        # 体動回数 (Garmin restlessMomentsCount)。ingest/sleep_extras.py が
        # 睡眠セッションと同じ日付規約 (target 07:00) で MetricSample に書いている。
        restless: dict[date_type, float] = {}
        for ts, v in s.execute(
            select(MetricSample.ts, MetricSample.value)
            .where(MetricSample.metric_key == "sleep_restless_moments", MetricSample.ts >= lo, MetricSample.ts < hi)
        ):
            if v is not None:
                restless[_jst(ts).date()] = float(v)
        caf_rows = [(_jst(ts), float(mg), src) for ts, mg, src in s.execute(
            select(CaffeineIntake.ts, CaffeineIntake.mg, CaffeineIntake.source)
            .where(CaffeineIntake.ts >= lo, CaffeineIntake.ts < hi)
        ) if mg is not None]
        # 食事性カフェイン (コーヒー/茶) と頭痛薬カフェインを分離 (交絡対策)
        caf = [(t, mg) for t, mg, src in caf_rows if is_dietary_caffeine(src)]
        med = [(t, mg) for t, mg, src in caf_rows if not is_dietary_caffeine(src)]
        alc = [(_jst(ts), float(g)) for ts, g in s.execute(
            select(AlcoholIntake.ts, AlcoholIntake.grams).where(AlcoholIntake.ts >= lo, AlcoholIntake.ts < hi)
        ) if g is not None]
        loads = [(_jst(ts), float(ld)) for ts, ld in s.execute(
            select(Workout.start, Workout.training_load).where(Workout.start >= lo, Workout.start < hi)
        ) if ld is not None]
        # 朝の光 (推定 proxy): 「その夜の睡眠」に効くのは前日(prev)朝の光暴露。
        # steps/stress と同じ prev 起点の作法に揃える (就寝前の日中の話なので)。
        wake_hhmm = str(get_settings().target_wake_time)
        # 夜間 (前日22時〜当日06時 JST) の外気温平均を「その夜」の値にする。
        # ⚠️ ts は UTC 保存・日付は JST なので、UTC-9h の窓で切る (日単位の
        # date(ts) で束ねると9時間ずれる)。窓は睡眠の中心帯に合わせている。
        temp_night: dict[date_type, float] = {}
        temp_rows = s.execute(
            select(MetricSample.ts, MetricSample.value).where(
                MetricSample.metric_key == "surface_temperature_c",
                MetricSample.ts >= lo, MetricSample.ts < hi,
            )
        ).all()
        _acc: dict[date_type, list[float]] = {}
        for ts, val in temp_rows:
            if val is None:
                continue
            jst = ts + timedelta(hours=9)
            # 22:00-23:59 は「翌朝が起床日」の夜、00:00-05:59 はその日が起床日
            if jst.hour >= 22:
                night = (jst + timedelta(days=1)).date()
            elif jst.hour < 6:
                night = jst.date()
            else:
                continue
            _acc.setdefault(night, []).append(float(val))
        for d_, vs in _acc.items():
            temp_night[d_] = sum(vs) / len(vs)

        morning_light: dict[date_type, float] = {}
        for pd in {d - timedelta(days=1) for d in sleep_rows}:
            score = compute_morning_light_score(s, pd, wake_hhmm=wake_hhmm).get("score")
            if score is not None:
                morning_light[pd] = float(score)

    # midpoint の中央値 (規則性=ここからの逸脱)
    mid_vals = sorted(midpoint.values())
    mid_med = mid_vals[len(mid_vals) // 2] if mid_vals else None

    rows: list[dict[str, Any]] = []
    for d, sl in sleep_rows.items():
        total, awake = sl["total"], sl["awake"]
        eff = (total / (total + awake) * 100) if (total and awake is not None and (total + awake) > 0) else None
        prev = d - timedelta(days=1)
        # 夜の窓 [prev 12:00 → d 04:00] JST で評価する行動
        w_lo = datetime.combine(prev, datetime.min.time()).replace(hour=12)
        w_hi = datetime.combine(d, datetime.min.time()).replace(hour=4)
        caf_pm = sum(mg for t, mg in caf if w_lo <= t <= w_hi)  # 食事性のみ
        alc_eve = sum(g for t, g in alc if w_lo <= t <= w_hi)
        # 頭痛薬カフェインは「その日に頭痛薬を使ったか」のマーカー (頭痛日の代理)
        med_day = sum(
            mg for t, mg in med
            if datetime.combine(prev, datetime.min.time()) <= t <= datetime.combine(d, datetime.min.time()).replace(hour=6)
        )
        load = sum(ld for t, ld in loads if prev <= t.date() <= d)
        mid = midpoint.get(d)
        rm = restless.get(d)
        rows.append({
            # outcomes
            "efficiency": eff, "deep_min": sl["deep"], "sleep_score": sl["score"],
            "hrv_overnight": sl["hrv"],
            "restlessness_inv": (-rm if rm is not None else None),  # 符号反転 (少ないほど良い→高いほど良い)
            "morning_bb": bb.get(d),
            "energy": checkin.get(d, {}).get("energy"),
            # drivers
            "midpoint": (mid + 24 if mid is not None and mid < 12 else mid),
            "irregular": (abs(mid - mid_med) if mid is not None and mid_med is not None else None),
            "caffeine_pm": caf_pm, "alcohol_eve": alc_eve, "exercise": load,
            "medication": med_day,
            "steps": steps.get(prev), "stress": checkin.get(prev, {}).get("stress"),
            "duration": total,
            "morning_light": morning_light.get(prev),
            "temp_night": temp_night.get(d),
        })
    return rows


def analyze(target: date_type | None = None) -> dict[str, Any]:
    target = target or app_today()
    rows = _collect(target)
    n = len(rows)
    base: dict[str, Any] = {"n_nights": n, "quality": [], "next_day": []}

    # 全 (アウトカム×ドライバー) を検定。各群 >=_MIN_GROUP_PRELIM で暫定シグナルを出す。
    # powered = ペア>=_MIN_PAIRS & 各群>=_MIN_GROUP & n>=_MIN_PAIRS のときだけ FDR で有意性を語る。
    tests: list[dict[str, Any]] = []
    for okey, olabel, group in _OUTCOMES:
        for dkey, dlabel in _DRIVERS:
            if dkey == "duration" and okey in (
                "efficiency", "deep_min", "sleep_score", "hrv_overnight", "restlessness_inv",
            ):
                # 睡眠時間→睡眠の質は自明寄りなので翌日のみ対象。restlessness_inv (体動回数の
                # 符号反転) も、寝ている時間が長いほど体動の絶対回数が増える自明の関係が
                # 実データで確認できた (duration↑→restlessness_inv↓, p=0.0) ため同様に除外。
                continue
            pairs = [(r[dkey], r[okey]) for r in rows if r.get(dkey) is not None and r.get(okey) is not None]
            if len(pairs) < _MIN_PAIRS_PRELIM:
                continue
            # 順位ベースで上位半分(high)/下位半分(low)。二値ドライバーの同値偏りを避ける。
            pairs.sort(key=lambda p: p[0])
            mid = len(pairs) // 2
            low = [o for _, o in pairs[:mid]]
            high = [o for _, o in pairs[mid:]]
            if len(high) < _MIN_GROUP_PRELIM or len(low) < _MIN_GROUP_PRELIM:
                continue
            # 高低で差が無い(全ドライバー値が同一)なら無意味なのでスキップ
            if pairs[0][0] == pairs[-1][0]:
                continue
            p, diff = permutation_test(high, low)
            if p is None or diff is None:
                continue
            powered = (
                len(pairs) >= _MIN_PAIRS and len(high) >= _MIN_GROUP
                and len(low) >= _MIN_GROUP and n >= _MIN_PAIRS
            )
            tests.append({
                "outcome": okey, "outcome_label": olabel, "group": group,
                "driver": dkey, "label": dlabel, "p": round(p, 4), "diff": diff,
                "n": len(pairs), "powered": powered,
            })

    if not tests:
        base["status"] = "accumulating" if n < _MIN_PAIRS else "no_data"
        base["remaining"] = max(0, _MIN_PAIRS - n)
        return base

    powered_tests = [t for t in tests if t["powered"]]
    qmap: dict[int, float] = {}
    if powered_tests:
        qs = benjamini_hochberg([t["p"] for t in powered_tests])
        for t, q in zip(powered_tests, qs, strict=True):
            qmap[id(t)] = q
    for t in tests:
        if abs(t["diff"]) < 1e-9:
            continue
        if t["powered"]:
            q = qmap[id(t)]
            if q < FDR_Q:
                tier = "strong"
            elif t["p"] < 0.1:
                tier = "suggestive"
            elif t["p"] < 0.25:
                tier = "trend"
            else:
                tier = "weak"
            qv: float | None = round(q, 4)
        else:
            tier = "preliminary"
            qv = None
        # diff>0: ドライバー高い日に outcome が高い (全 outcome 高いほど良い)
        factor = {
            "driver": t["driver"], "label": t["label"],
            "outcome": t["outcome"], "outcome_label": t["outcome_label"],
            "direction": "改善" if t["diff"] > 0 else "悪化",
            "diff": round(t["diff"], 1), "p": t["p"], "q": qv,
            "tier": tier, "n": t["n"],
        }
        base[t["group"]].append(factor)

    anchors = _anchors(rows)
    base["anchors"] = anchors
    # 確度高い順: tier (strong>suggestive>trend>weak) 降順 → 同 tier 内は q 昇順。
    def _conf_key(f: dict[str, Any]) -> tuple[int, float, float]:
        return (-_TIER_RANK.get(f.get("tier"), 0),
                f["q"] if f["q"] is not None else 1.0,
                f["p"] if f.get("p") is not None else 1.0)
    base["quality"].sort(key=_conf_key)
    base["next_day"].sort(key=_conf_key)
    base["recommendations"] = _recommendations(base["quality"] + base["next_day"], anchors)
    base["reliability"] = "high" if n >= 45 else ("medium" if n >= 21 else "low")
    if powered_tests:
        base["status"] = "analyzed"
    else:
        base["status"] = "preliminary"
        base["remaining"] = max(0, _MIN_PAIRS - n)
    return base


_TIER_RANK = {"strong": 3, "suggestive": 2, "trend": 1, "weak": 0}


def _hhmm(h: float) -> str:
    h = h % 24
    hh = int(h)
    mm = round((h - hh) * 60)
    if mm == 60:
        hh = (hh + 1) % 24
        mm = 0
    return f"{hh:02d}:{mm:02d}"


def _anchors(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """就寝中央時刻から逆算した具体アンカー (就寝/カフェイン6h前/運動3h前/標準睡眠時間)。"""
    mids = sorted(r["midpoint"] for r in rows if r.get("midpoint") is not None)
    durs = sorted(r["duration"] for r in rows if r.get("duration") is not None)
    if not mids or not durs:
        return None
    mid = mids[len(mids) // 2]      # 睡眠中点 (JST, 早朝は+24で連続化済)
    dur = durs[len(durs) // 2]      # 睡眠時間 (分)
    bedtime = mid - dur / 120.0     # 就寝 = 中点 - 半分
    # 締切のラグは config を正とする (今夜の計画 sleep_plan.py と同じ値を使い、
    # 「助言では3h前と言うのに計画では別の時刻」という食い違いを作らない)。
    s = get_settings()
    caffeine_h = s.caffeine_cutoff_hours_before_bed
    exercise_h = s.exercise_to_bed_lead_min / 60.0
    # 歩数の中央値 = 検定で「多い/少ない」を分けている実際の境界。
    # 「こまめに歩く」だけでは何歩を目指せばよいか分からないので、助言に埋める。
    step_vals = sorted(r["steps"] for r in rows if r.get("steps") is not None)
    steps_median = step_vals[len(step_vals) // 2] if step_vals else None
    return {
        "bedtime": _hhmm(bedtime),
        "caffeine_cutoff": _hhmm(bedtime - caffeine_h),
        "exercise_cutoff": _hhmm(bedtime - exercise_h),
        "alcohol_cutoff": _hhmm(bedtime - exercise_h),
        "dur_h": round(dur / 60, 1),
        "steps_median": int(steps_median) if steps_median is not None else None,
    }


def _action_text(driver: str, direction: str, a: dict[str, Any] | None) -> str | None:
    """ドライバー×方向 → 具体的な行動文 (アンカーで時刻を埋める)。"""
    bt = a["bedtime"] if a else None
    if direction == "悪化":  # 避ける
        if driver == "irregular":
            return f"就寝を {bt}±30分に揃える（就寝が乱れた夜ほど睡眠が悪化）" if a else "就寝・起床の時刻を ±30分 に揃える"
        if driver == "midpoint":
            return f"{bt} より早く就寝する（夜更かしの日ほど悪化）" if a else "今より早めに就寝する"
        if driver == "caffeine_pm":
            return f"{a['caffeine_cutoff']} 以降のカフェインを控える（就寝6h前まで）" if a else "夕方以降のカフェインを控える"
        if driver == "alcohol_eve":
            return f"{a['alcohol_cutoff']} 以降の飲酒を控える（就寝3h前まで）" if a else "就寝前の飲酒を控える"
        if driver == "stress":
            return "就寝1時間前から画面を切り、4-7-8呼吸 or 入浴で落ち着く"
        if driver == "exercise":
            # 「悪化」= 負荷が高い日ほど悪い → 就寝前の高強度を避ける
            return f"{a['exercise_cutoff']} 以降の高強度運動を避ける（就寝3h前まで）" if a else "就寝3時間前以降の高強度運動を避ける"
        if driver == "steps":
            # ⚠️ steps は**歩数**。以前ここに exercise 用の「高強度運動を避ける」文言が
            # 入っており、歩数の話が運動強度の話にすり替わっていた。
            # 歩数が多い日ほど悪い、という向きは考えにくいが、出た場合は
            # 「歩数そのもの」ではなく時間帯の問題として扱う。
            return "夜遅くの活動を減らし、歩くのは日中に寄せる"
    else:  # 続ける
        if driver == "exercise":
            return f"運動は日中〜{a['exercise_cutoff']} までに済ませる（運動した日ほど深睡眠/翌朝が良い）" if a else "運動は日中〜夕方に済ませる"
        if driver == "steps":
            # 何歩を目指すのかを出す (検定の分割点 = 中央値がそのまま目標になる)
            if a and a.get("steps_median"):
                return f"日中こまめに歩く（1日 {a['steps_median']:,} 歩超を目安に）"
            return "日中こまめに歩く（歩数が多い日ほど深く眠れている）"
        if driver == "duration":
            return f"睡眠時間は {a['dur_h']} 時間前後を確保する" if a else "睡眠時間をしっかり確保する"
        if driver == "caffeine_pm":
            return "今のカフェイン習慣は睡眠に悪影響なし（無理に変えなくてよい）"
    return None


def _recommendations(factors: list[dict[str, Any]], anchors: dict[str, Any] | None) -> list[dict[str, Any]]:
    """有意な要因から「今夜やること」を具体アクションで最大3件。ドライバー単位で重複排除。"""
    recs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for f in sorted(factors, key=lambda x: -_TIER_RANK.get(x["tier"], 0)):
        # 具体的な生活変更の推奨は trend 以上に限る (weak/preliminary は暗示に留める)
        if f["tier"] in ("weak", "preliminary") or f["driver"] in seen:
            continue
        text = _action_text(f["driver"], f["direction"], anchors)
        if not text:
            continue
        seen.add(f["driver"])
        recs.append({
            "text": text, "driver": f["driver"],
            "basis": f"{f['outcome_label']}に{f['tier']}（{f['direction']}）",
            "tier": f["tier"],
        })
        if len(recs) >= 3:
            break
    return recs
