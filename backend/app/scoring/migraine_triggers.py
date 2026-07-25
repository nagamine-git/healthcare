"""頭痛 (片頭痛) 要因分析: 時刻対応ケースクロスオーバー (DB アクセス層)。

各頭痛発症の直前 24h ウィンドウ (ケース) と、非頭痛日の同時刻 24h ウィンドウ (対照) で
候補要因の曝露を比較し、並べ替え検定 + BH 補正で有意な要因だけを返す。

- 小サンプルでは有意性を語らず status=accumulating を返す (MIN_EPISODES 既定 10)。
- 全要因が非有意なら status=no_significant_factor を返す (「実は何も寄与していない」を明示)。
- 発症時刻プロファイル (記述的) は常に返す。

設計: docs/superpowers/specs/2026-06-08-migraine-trigger-analysis-design.md
"""

from __future__ import annotations

import statistics
from datetime import UTC, datetime, timedelta
from datetime import date as date_type
from typing import Any

from sqlalchemy import select

from app.db import session_scope
from app.models import (
    AlcoholIntake,
    CaffeineIntake,
    HrvDaily,
    MetricSample,
    MigraineEpisode,
    SleepSession,
    SubjectiveCheckin,
    Workout,
)
from app.scoring import hydration
from app.scoring.caffeine import MEDICATION_CAFFEINE_SOURCES
from app.scoring.circadian import circular_mean_hour
from app.scoring.migraine_stats import benjamini_hochberg, onset_profile, permutation_test
from app.scoring.timewindow import JST

MIN_EPISODES = 10
WINDOW_H = 24  # 発症前ウィンドウ (時間)
ANALYSIS_DAYS = 120  # 遡る最大日数
FDR_Q = 0.05
MIN_GROUP = 3  # ケース/対照それぞれ最低この数の有効値が必要
# 飲水のベースライン (中央値) を出すのに必要な記録日数。
# 数日の記録から個人平均を名乗ると、たまたま多かった/少なかった日に引きずられる
MIN_WATER_DAYS = 14
# 主観ストレスのベースライン (中央値) を出すのに必要な記録日数。飲水と同じ理由。
MIN_STRESS_DAYS = 14


def _to_jst(ts: datetime) -> datetime:
    return ts.replace(tzinfo=UTC).astimezone(JST).replace(tzinfo=None)


# --- 各要因の曝露関数 (ウィンドウ [start, end] で「高いほど誘発」の値、無ければ None) ---


def _exposure_pressure_drop(rows: list[tuple[datetime, float]], start: datetime, end: datetime) -> float | None:
    vals = [v for ts, v in rows if start <= ts <= end and v is not None]
    if len(vals) < 2:
        return None
    return round(max(vals) - min(vals), 2)  # ウィンドウ内の気圧変動幅 (hPa)


def analyze_triggers(target: date_type, *, min_episodes: int = MIN_EPISODES) -> dict[str, Any]:
    window = timedelta(hours=WINDOW_H)
    since = datetime.combine(target - timedelta(days=ANALYSIS_DAYS), datetime.min.time())
    end_dt = datetime.combine(target, datetime.max.time())

    with session_scope() as session:
        episodes = session.execute(
            select(MigraineEpisode.started_at)
            .where(MigraineEpisode.started_at >= since, MigraineEpisode.started_at <= end_dt)
            .order_by(MigraineEpisode.started_at)
        ).scalars().all()

        pressure_rows = session.execute(
            select(MetricSample.ts, MetricSample.value).where(
                MetricSample.metric_key == "surface_pressure_hpa",
                MetricSample.ts >= since - window,
            )
        ).all()
        sleep_rows = {
            d: tot for d, tot in session.execute(
                select(SleepSession.date, SleepSession.total_min).where(SleepSession.date >= since.date())
            ).all()
        }
        # 睡眠中の呼吸の乱れ (ingest/sleep_extras.py が毎晩書いているが参照ゼロだった)。
        # metric_key="sleep_breath_disruption" (LOW=0/MODERATE=1/HIGH=2)、ts はその夜の
        # 対象日 07:00 マーカー (SleepSession.date と同じ日付キー、ts.date() で直接引ける)
        breath_rows = session.execute(
            select(MetricSample.ts, MetricSample.value).where(
                MetricSample.metric_key == "sleep_breath_disruption",
                MetricSample.ts >= since,
            )
        ).all()
        hrv_rows = {
            d: v for d, v in session.execute(
                select(HrvDaily.date, HrvDaily.last_night_avg).where(HrvDaily.date >= since.date())
            ).all()
        }
        # 主観ストレスは sleep_drivers.py の stress ドライバーで既に使われているが
        # 頭痛側では未接続だった。JST 暦日 1 値 (1-5, 高いほど悪い)
        stress_rows = {
            d: v for d, v in session.execute(
                select(SubjectiveCheckin.date, SubjectiveCheckin.stress).where(
                    SubjectiveCheckin.date >= since.date())
            ).all()
        }
        # 食事性カフェインのみ。頭痛薬カフェイン(イブクイック等)は頭痛の「治療」として
        # 服用するため、トリガー曝露に混ぜると逆因果の交絡になる → 除外。
        caffeine_rows = session.execute(
            select(CaffeineIntake.ts, CaffeineIntake.mg).where(
                CaffeineIntake.ts >= since - window,
                CaffeineIntake.source.notin_(MEDICATION_CAFFEINE_SOURCES),
            )
        ).all()
        alcohol_rows = session.execute(
            select(AlcoholIntake.ts, AlcoholIntake.grams).where(AlcoholIntake.ts >= since - window)
        ).all()
        # 飲水は JST 暦日の合計。記録の無い日はキーごと入らない (0 mL の日を作らない)
        water_by_day = hydration.daily_map(session, since - window, end_dt)
        # 運動負荷は alcohol と同じ「前日まるごと」窓で見る (exercise_prev_load 参照)
        workout_rows = session.execute(
            select(Workout.start, Workout.training_load).where(Workout.start >= since - window)
        ).all()

    profile = onset_profile([_to_jst(e) for e in episodes])
    episode_count = len(episodes)

    base: dict[str, Any] = {
        "episode_count": episode_count,
        "onset_profile": profile,
        "min_episodes": min_episodes,
        "tested": [],
        "factors": [],
    }

    # 件数による「精度ランク」。少なくても分析は走らせ、信頼度を明示する。
    # 片頭痛トリガー研究で安定するのは ~10 例以降だが、数例でも傾向は見たい。
    if episode_count >= 20:
        reliability = "high"
    elif episode_count >= min_episodes:
        reliability = "medium"
    elif episode_count >= 4:
        reliability = "low"
    else:
        reliability = "very_low"
    base["reliability"] = reliability

    # 4 例未満は permutation 検定が成立しない (対照との差を語れない)
    if episode_count < 4:
        base["status"] = "accumulating"
        base["remaining"] = max(0, 4 - episode_count)
        return base

    # --- 曝露の組み立て ---
    pressure = [(ts, float(v)) for ts, v in pressure_rows if v is not None]
    caffeine = [(ts, float(mg)) for ts, mg in caffeine_rows if mg is not None]
    alcohol = [(ts, float(g)) for ts, g in alcohol_rows if g is not None]

    # 個人ベースライン (window 全体平均)
    caf_daily_baseline = (sum(mg for _, mg in caffeine) / max(1, ANALYSIS_DAYS)) if caffeine else 0.0

    def caffeine_window_mg(start: datetime, end: datetime) -> float:
        return sum(mg for ts, mg in caffeine if start <= ts <= end)

    def alcohol_prev_g(onset: datetime) -> float:
        # 前日 (発症の 24-48h 前) のアルコール
        lo, hi = onset - timedelta(hours=48), onset - timedelta(hours=24)
        return sum(g for ts, g in alcohol if lo <= ts <= hi)

    workouts = [(ts, float(tl)) for ts, tl in workout_rows if tl is not None]

    def exercise_prev_load(onset: datetime) -> float:
        """前日 (発症の 24-48h 前) の運動負荷 (Workout.training_load) 合計。

        sleep_drivers.py の exercise ドライバー (睡眠側) では既に使われているが、
        頭痛側は未接続だった。運動には労作性頭痛 (exertional headache) のように
        誘発する型と、有酸素運動が発作頻度を下げるという報告 (予防効果) の両面が
        あるため、この関数では方向を決め打ちしない — 誘発/抑制のどちらかは
        後段の permutation 検定の diff 符号 (case_mean と control_mean の大小) で
        表現される。

        窓を alcohol_prev_g と同じ「前日まるごと (24-48h 前)」にする理由も同じ:
        training_load はワークアウト終了時にしか記録されないため、発症直前だけ
        切り出すと大半のケースで単に「その時間は運動していなかった」を拾って
        しまい、運動と頭痛の時間差 (労作後しばらくして痛む型) も拾えなくなる。

        ワークアウト記録の無い日の合計は 0.0 (これは「記録が無い」ではなく
        「運動しなかった」の意味— Garmin は行ったワークアウトを漏れなく記録する
        前提のため、自己申告のストレス/飲水とは違い 0 を代入しても偽陽性にならない)。
        """
        lo, hi = onset - timedelta(hours=48), onset - timedelta(hours=24)
        return sum(tl for ts, tl in workouts if lo <= ts <= hi)

    def sleep_deficit(onset: datetime) -> float | None:
        """前夜の総睡眠時間 (分) の、8h 目標からの絶対乖離。

        従来は ``480 - total`` の片側 (不足のみ) だったが、それでは「寝過ぎ」を
        誘因とする頭痛 (休日頭痛 = weekend headache のような、普段より長く寝た
        朝に出る古典的な型) を原理的に拾えなかった。abs() にして両側を見る。
        不足由来か過多由来かはこの関数では判定しない (case_mean/control_mean を
        見れば分かる) — 診断的な意味づけをしないのはこのモジュール共通の方針。
        """
        d = _to_jst(onset).date()
        tot = sleep_rows.get(d)
        return abs(480 - float(tot)) if tot is not None else None

    # ts は ingest/sleep_extras.py が対象日 07:00 に書くマーカーなので、_to_jst の
    # UTC→JST 変換は不要 (ts.date() が既に「その夜が属する日」そのもの)
    breath_by_date = {ts.date(): v for ts, v in breath_rows if v is not None}

    def breath_disruption(onset: datetime) -> float | None:
        """前夜の睡眠中の呼吸の乱れ (Garmin breathingDisruptionSeverity: LOW=0/MODERATE=1/HIGH=2)。

        ingest/sleep_extras.py が毎晩書いているが、これまでどこからも参照されて
        いなかった値。起床時頭痛の型は睡眠関連呼吸障害との関連が知られているため、
        「呼吸の乱れが多い夜の翌日に頭痛が多いか」という相関の有無だけを見る。

        ⚠️ ここでは疾患の診断・推定は一切しない。有意であっても「睡眠時無呼吸が
        ある」等の解釈をラベル・コメント・UI に書き足さないこと — 見えるのは
        あくまで統計的な関連で、それ以上の意味付けは医療機器でないこのアプリの
        範囲を超える。

        記録の無い夜 (Garmin が severity を返さなかった日) は None で除外する。
        0 (LOW) と「記録なし」を区別しないと、未記録の夜を「乱れが無かった」と
        誤読して偽陽性を生む。
        """
        d = _to_jst(onset).date()
        v = breath_by_date.get(d)
        return float(v) if v is not None else None

    def hrv_drop(onset: datetime, baseline: float) -> float | None:
        d = _to_jst(onset).date()
        v = hrv_rows.get(d)
        return (baseline - float(v)) if v is not None else None

    # 飲水の個人ベースライン = 記録のある日の中央値。
    # 平均でなく中央値なのは、一括記録で 1 日だけ極端な値が入ることがあるため
    water_vals = sorted(water_by_day.values())
    water_baseline = statistics.median(water_vals) if len(water_vals) >= MIN_WATER_DAYS else None

    def hydration_deficit(onset: datetime) -> float | None:
        """**前日**の飲水量の、個人ベースラインからの不足量 (mL)。高いほど脱水寄り。

        前日を見る理由: ``garmin_hydration_ml`` は 1 日 1 行のスナップショットで
        ``ts`` が同期時刻 (実測では毎日 09:00) なので、発症直前の実摂取量を
        切り出せない。日単位でしか信用できない以上、発症当日の「途中まで」を使うと
        同期タイミング次第で値が跳ねる。前日の完全な 1 日分の方が頑健で、
        水分制限から頭痛までに時間差がある (Blau 2004, water-deprivation headache)
        機序とも整合する。

        絶対目標 (35 mL/kg 等) ではなく個人中央値からの偏差にするのはカフェイン因子と
        同じ理由 — 目標値の定義論争を持ち込まず「その日がいつもと違ったか」だけを見る。

        ⚠️ 記録の無い日は ``None`` を返して除外する。合計 0 を「飲まなかった」と
        読むと偽の脱水日を量産し、偽陽性を生む。
        """
        if water_baseline is None:
            return None
        d = _to_jst(onset).date() - timedelta(days=1)
        v = water_by_day.get(d)
        return (water_baseline - v) if v is not None else None

    # 主観ストレスの個人ベースライン = 記録のある日の中央値。飲水と同じ理由
    # (少数記録が平均を極端な1日に引きずられないよう中央値を使う)
    stress_vals = sorted(v for v in stress_rows.values() if v is not None)
    stress_baseline = statistics.median(stress_vals) if len(stress_vals) >= MIN_STRESS_DAYS else None

    def stress_deviation(onset: datetime) -> float | None:
        """発症前日〜当日の主観ストレス (1-5, 高いほど悪い) の、個人ベースライン (中央値) からの偏差。

        片頭痛の誘因としてもっとも報告頻度が高いのがストレスだが、これまで
        sleep_drivers.py の stress ドライバー (睡眠側) でしか使われておらず、
        頭痛側には未接続だった。

        窓を「前日〜当日」の2日平均にする理由: SubjectiveCheckin は JST 暦日
        1 値の自己申告で、記録タイミングが朝晩ばらつく。発症直前だけを見ると
        「まだ入力していないだけ」で欠測扱いになりやすく、また蓄積したストレスが
        遅れて頭痛に出る型 (let-down headache 的な経過) もあるため、2 日を均して使う。

        生値でなく個人ベースライン (中央値) 偏差にする理由: 1-5 の主観評価は
        個人内較正の差が大きい (常に3と答える人・常に1と答える人がいる)。
        カフェイン/飲水と同じ理由で「絶対値」ではなく「その人にとっていつもと
        違うか」を見る。

        ⚠️ SubjectiveCheckin は記録が疎な運用が前提のため、ベースラインは
        MIN_STRESS_DAYS 件以上の記録が揃うまで作らない (作れなければ常に None
        を返し、この要因は MIN_GROUP 割れで自動的に落ちる — それが正しい挙動)。
        前日・当日ともに未記録なら None を返して除外する。0 を代入すると
        「ストレスが低かった日」を偽装し、偽陽性を生む。
        """
        if stress_baseline is None:
            return None
        d = _to_jst(onset).date()
        vals = [stress_rows[dd] for dd in (d - timedelta(days=1), d) if stress_rows.get(dd) is not None]
        if not vals:
            return None
        return (sum(vals) / len(vals)) - stress_baseline

    hrv_vals = [float(v) for v in hrv_rows.values() if v is not None]
    hrv_baseline = sum(hrv_vals) / len(hrv_vals) if hrv_vals else 0.0

    # ケースアンカー = 各発症時刻。対照アンカー = 非頭痛日の「平均発症時刻 (JST)」。
    case_anchors = list(episodes)
    headache_days = {_to_jst(e).date() for e in episodes}
    mean_onset_h = circular_mean_hour([_to_jst(e).hour + _to_jst(e).minute / 60 for e in episodes]) or 15.0
    control_anchors: list[datetime] = []
    day = target - timedelta(days=ANALYSIS_DAYS)
    while day <= target:
        if day not in headache_days:
            # JST の mean_onset_h を UTC naive に戻す
            jst_anchor = datetime.combine(day, datetime.min.time()).replace(
                tzinfo=JST) + timedelta(hours=mean_onset_h)
            control_anchors.append(
                jst_anchor.astimezone(UTC).replace(tzinfo=None))
        day += timedelta(days=1)

    # 各要因の (case値, control値) を集め検定
    factor_defs: list[dict[str, Any]] = [
        {"key": "pressure_drop", "label": "気圧変動 (低下)",
         "case": lambda a: _exposure_pressure_drop(pressure, a - window, a),
         "ctrl": lambda a: _exposure_pressure_drop(pressure, a - window, a)},
        # カフェインは「baseline からの偏差」を1因子で検定する。
        # 離脱(不足)と過多を別因子にすると符号反転の鏡像になり、必ず同じ p 値が
        # 2 行出て多重比較補正まで水増しする。偏差の符号(頭痛日に多い/少ない)で
        # 過多/離脱を後段で動的にラベルする (どちらも最適から外れる=誘発)。
        {"key": "caffeine", "label": "カフェイン (離脱/過多)",
         "case": lambda a: caffeine_window_mg(a - window, a) - caf_daily_baseline,
         "ctrl": lambda a: caffeine_window_mg(a - window, a) - caf_daily_baseline},
        # キー名は sleep_short のまま (下流の forecast.py 等が参照) だが、中身は
        # 不足/過多どちらも拾う両側乖離。ラベルもそれに合わせて中立化する。
        {"key": "sleep_short", "label": "睡眠時間の逸脱 (前夜)",
         "case": lambda a: sleep_deficit(a),
         "ctrl": lambda a: sleep_deficit(a)},
        {"key": "hrv_low", "label": "HRV 低下",
         "case": lambda a: hrv_drop(a, hrv_baseline),
         "ctrl": lambda a: hrv_drop(a, hrv_baseline)},
        {"key": "alcohol_prev", "label": "前日の飲酒",
         "case": lambda a: alcohol_prev_g(a),
         "ctrl": lambda a: alcohol_prev_g(a)},
        # 脱水は片頭痛の誘発因子として繰り返し報告されている (Blau 2004 の
        # water-deprivation headache、Kelman 2007 の誘因調査)。飲水記録が揃って
        # 初めて検定できる因子で、記録日数が足りなければ自動的に落ちる
        {"key": "dehydration", "label": "水分不足 (前日)",
         "case": lambda a: hydration_deficit(a),
         "ctrl": lambda a: hydration_deficit(a)},
        {"key": "subjective_stress", "label": "主観ストレス (前日〜当日)",
         "case": lambda a: stress_deviation(a),
         "ctrl": lambda a: stress_deviation(a)},
        {"key": "exercise_load", "label": "前日の運動負荷",
         "case": lambda a: exercise_prev_load(a),
         "ctrl": lambda a: exercise_prev_load(a)},
        # 診断はしない。「呼吸の乱れが多い夜の翌日に頭痛が多いか」の関連のみを見る
        # (breath_disruption() の docstring 参照)。
        {"key": "sleep_breath_disruption", "label": "睡眠中の呼吸の乱れ (前夜)",
         "case": lambda a: breath_disruption(a),
         "ctrl": lambda a: breath_disruption(a)},
    ]

    results = []
    for fd in factor_defs:
        case_vals = [x for a in case_anchors if (x := fd["case"](a)) is not None]
        ctrl_vals = [x for a in control_anchors if (x := fd["ctrl"](a)) is not None]
        # 全ゼロ (= データ無しと同義、例: alcohol 0 件) はスキップ
        if len(case_vals) < MIN_GROUP or len(ctrl_vals) < MIN_GROUP:
            continue
        if all(v == 0 for v in case_vals + ctrl_vals):
            continue
        p, diff = permutation_test(case_vals, ctrl_vals)
        if p is None:
            continue
        results.append({
            "key": fd["key"], "label": fd["label"], "p": round(p, 4), "diff": diff,
            "n_case": len(case_vals),
            "case_mean": round(sum(case_vals) / len(case_vals), 2),
            "control_mean": round(sum(ctrl_vals) / len(ctrl_vals), 2),
        })

    base["tested"] = [r["key"] for r in results]
    if not results:
        base["status"] = "no_data"
        return base

    qs = benjamini_hochberg([r["p"] for r in results])
    factors = []
    for r, q in zip(results, qs, strict=True):
        if r["diff"] == 0:
            continue
        # 全要因を返し、確からしさを tier で表現 (UI で薄さに反映):
        #   strong = FDR<0.05 / suggestive = p<0.1 / trend = p<0.25 / weak = それ未満
        if q < FDR_Q:
            tier = "strong"
        elif r["p"] < 0.1:
            tier = "suggestive"
        elif r["p"] < 0.25:
            tier = "trend"
        else:
            tier = "weak"
        label = r["label"]
        direction = "誘発" if r["diff"] > 0 else "抑制?"
        if r["key"] == "caffeine":
            # baseline からの偏差。頭痛日に多ければ「過多」、少なければ「離脱」。
            # どちらも最適から外れた=トリガなので direction は常に誘発。
            label = "カフェイン過多" if r["diff"] > 0 else "カフェイン離脱 (不足)"
            direction = "誘発"
        factors.append({
            "key": r["key"], "label": label,
            "direction": direction,
            "case_mean": r["case_mean"], "control_mean": r["control_mean"],
            "n_case": r["n_case"], "p": r["p"], "q": round(q, 4), "tier": tier,
        })
    # 確からしさ順 (q 昇順 = p 昇順に近い)
    factors.sort(key=lambda f: (f["q"], f["p"]))
    base["factors"] = factors
    base["status"] = "analyzed"
    return base
