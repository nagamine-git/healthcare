"""自宅フィットネスチェック: テスト定義・基準値評価・トレンド・再測定推奨。

テスト定義 (プロトコル/器具/基準値/再測定間隔) はコードに持ち、結果だけを DB
(FitnessTestResult) に永続化する (Learning のカリキュラム/進捗分離と同じ)。

# 採用テストと医学的根拠
- push_up  : 腕立て80bpm最大回数。Yang 2019 JAMA Netw Open — 活動的中年男性で
             >40回群は ≤10回群比 心血管イベント 96%減 (HR 0.04)。
- grip     : 握力 (デジタル握力計・左右ベスト)。Leong 2015 PURE (n=139,691) —
             握力5kg低下ごと全死亡 HR 1.16。全テスト中エビデンス最強。
- chair_stand: 30秒椅子立ち上がり。サルコペニア診断・要介護を予測 (器具ゼロ)。
- srt      : 座って立つテスト 0-10点。Brito 2012 EJPC — 0-3点群は8-10点群比 死亡5-6倍。

# 評価バンドの前提
基準値は日本人成人男性のエビデンスに基づくため、性別=male かつ年齢が判明している
ときのみバンドを返す。それ以外は絶対値のみ (バンド None)。

# トレンドの誤差吸収
前回比は MDC (最小検出変化) を超えたときだけ「実変化」とする。週次のノイズを
実力向上と誤認させないため。

設計: docs/superpowers/specs/2026-06-22-home-fitness-test-design.md
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from app.db import session_scope
from app.models import FitnessTestResult
from app.scoring.population_norms import pct_from
from app.scoring.profile import resolve_profile


@dataclass(frozen=True)
class FitnessTestDef:
    key: str
    label: str
    target: str  # 測る力
    protocol: str  # 手順
    equipment: str
    est_minutes: float
    unit: str
    retest_weeks: int
    warmup: str
    migraine_note: str
    mdc: float  # 最小検出変化 (これ未満の前回差はノイズ扱い)
    reference: str  # 北極星/基準値の説明
    steps: tuple[str, ...] = ()  # 初心者向けの番号付き実施手順
    higher_is_better: bool = True
    has_lr: bool = False  # 左右別入力 (握力)
    measure_mode: str | None = None  # アプリ内測定UI: "metronome_tap" | "timer_clap" | None


FITNESS_TESTS: dict[str, FitnessTestDef] = {
    "push_up": FitnessTestDef(
        key="push_up",
        label="腕立て伏せ (80bpm 最大回数)",
        target="上肢筋持久力・心血管リスク",
        protocol=(
            "メトロノームを80bpmに設定し、リズムに合わせて連続で行う。"
            "3拍以上遅れる/フォームが崩れる/疲労で続かなくなったら終了し、回数を記録。"
        ),
        equipment="メトロノーム (スマホアプリ可)",
        est_minutes=2,
        unit="回",
        retest_weeks=4,
        warmup="本番前に軽く5回行って肩・肘を温める (この試行はカウントしない)。",
        migraine_note="押し上げる局面で息を吐く。息こらえ (Valsalva) は片頭痛の労作性誘因になるため避ける。",
        mdc=2,
        reference="40回以上で心血管リスク最良域 (Yang 2019)。",
        measure_mode="metronome_tap",
        steps=(
            "メトロノームアプリを80 BPMに設定して再生する。「カチ」が1秒に約1.3回鳴る。",
            "うつ伏せになり、手は肩の真下〜少し外、足を揃える。頭・背中・腰・かかとを一直線に保つ。",
            "1拍で下げ、次の1拍で上げる。胸が床から握りこぶし1個分まで下がるのが目安。",
            "リズムに合わせて連続で行う。きつければ膝つきでも可 (メモに『膝つき』と残すと比較できる)。",
            "『3拍以上遅れた / 一直線を保てない / もう上がらない』のどれかで終了し、回数を記録する。",
        ),
    ),
    "grip": FitnessTestDef(
        key="grip",
        label="握力 (左右ベスト)",
        target="全身筋力 (全死亡の最強予測因子)",
        protocol=(
            "デジタル握力計を立位で体側に下ろし、肘を伸ばして全力で握る。"
            "左右それぞれ2回測り、各手のベスト値を入力する (高い方を採用)。"
        ),
        equipment="デジタル握力計",
        est_minutes=1,
        unit="kg",
        retest_weeks=4,
        warmup="数回軽く握って慣らす (本番は全力で短時間)。",
        migraine_note="握る瞬間に息を止めない。短い全力なので呼気を合わせる。",
        mdc=6,
        reference="日本人30代男性 平均47kg (計測は機器差を+0.5kg補正)。",
        steps=(
            "立って腕を体の横に自然に下ろし (肘は伸ばす)、握り幅を手に合わせて調整する。",
            "息を吐きながら2〜3秒、全力で握る。反動や腕の振りは使わない。",
            "片手ずつ2回ずつ測り、各手のベスト値を『左』『右』に入力する。",
            "記録すると、左右の高い方が自動で指標として採用される。",
        ),
    ),
    "chair_stand": FitnessTestDef(
        key="chair_stand",
        label="30秒椅子立ち上がり",
        target="下肢筋力・全身機能",
        protocol=(
            "肘掛けのない椅子 (座面43-45cm) に座り、腕を胸の前で組む。"
            "30秒間で完全な立ち座りを何回できるか数える。"
        ),
        equipment="肘掛けなしの椅子・ストップウォッチ",
        est_minutes=1,
        unit="回",
        retest_weeks=4,
        warmup="ゆっくり2-3回立ち座りして動作を確認 (本番前に休む)。",
        migraine_note="立ち上がりで息を吐く。反動や息こらえを使わない。",
        mdc=2.5,
        reference="30代男性 目安28-34回。",
        measure_mode="timer_clap",
        steps=(
            "肘掛けのない椅子 (座面43-45cm) を壁につけて固定し、座って背すじを伸ばす。足は肩幅で足裏全体を床につける。",
            "両腕を胸の前で組む (腕の反動を使わないため)。",
            "タイマー30秒スタートと同時に『完全に立つ→完全に座る』を繰り返す。膝が伸びきるまで立ち、お尻が座面につくまで座る。",
            "立ち上がるときに息を吐く。",
            "30秒で完了した立ち座りの回数を数えて記録する (合図の瞬間に立ち上がり途中ならその1回も数える)。",
        ),
    ),
    "srt": FitnessTestDef(
        key="srt",
        label="座って立つテスト (SRT)",
        target="柔軟性+筋力+バランスの統合 (死亡率と相関)",
        protocol=(
            "素足で、できるだけ手や膝などの支えを使わずに床に座る→立ち上がる。"
            "座り5点・立ち5点の計10点満点から、支えを使うごとに-1、ふらつきで-0.5。"
        ),
        equipment="不要 (滑らない床)",
        est_minutes=2,
        unit="点",
        retest_weeks=10,
        warmup="軽く足首・股関節を回してから (学習効果が大きいので毎回同条件で)。",
        migraine_note="ゆっくり動作。急な前屈・息こらえを避ける。",
        mdc=1,
        reference="8点以上で死亡リスク最良域 (Brito 2012)。",
        steps=(
            "滑らない床・広いスペースで、掴まれる物がない場所を選び、立った状態から始める。",
            "できるだけ手・膝・肘・前腕・体の側面で支えずに、床に座る。",
            "そのまま、できるだけ支えを使わずに立ち上がる。",
            "10点満点 (座る5点+立つ5点) から、支えた回数ごとに-1点、ぐらついたら-0.5点を引く (座る動作・立つ動作それぞれで数える)。",
            "合計点を『点』に入力する。転倒に注意し、無理はしない。",
        ),
    ),
}


@dataclass(frozen=True)
class _Band:
    status: str  # excellent | good | average | needs_work | alert
    label: str   # 優 / 良 / 平均 / 要改善 / 警報
    min_value: float  # この値以上ならこのバンド (higher_is_better 前提)


# 日本人成人男性のエビデンスに基づくバンド (降順)。
_MALE_BANDS: dict[str, list[_Band]] = {
    "push_up": [
        _Band("excellent", "優", 40),
        _Band("good", "良", 25),
        _Band("average", "平均", 10),
        _Band("needs_work", "要改善", 0),
    ],
    "grip": [
        _Band("excellent", "優", 52),
        _Band("good", "良", 47),
        _Band("average", "平均", 42),
        _Band("needs_work", "要改善", 0),
    ],
    "chair_stand": [
        _Band("excellent", "優", 34),
        _Band("good", "良", 28),
        _Band("average", "平均", 22),
        _Band("needs_work", "要改善", 0),
    ],
    "srt": [
        _Band("good", "良", 8),
        _Band("average", "平均", 6),
        _Band("needs_work", "要改善", 4),
        _Band("alert", "警報", 0),
    ],
}


# 連続値テストの母集団 mean/sd (sex × 年代帯 [lo,hi])。握力=比較的堅い、他=目安。
FITNESS_NORMS: dict[str, dict[str, list[tuple[int, int, float, float]]]] = {
    "grip": {
        "male": [(18, 29, 47, 7), (30, 49, 47, 7), (50, 69, 42, 7), (70, 200, 36, 6)],
        "female": [(18, 29, 28, 5), (30, 49, 29, 5), (50, 69, 26, 5), (70, 200, 23, 4)],
    },
    "push_up": {
        "male": [(18, 29, 30, 12), (30, 49, 22, 11), (50, 69, 15, 9), (70, 200, 9, 7)],
        "female": [(18, 29, 18, 9), (30, 49, 14, 8), (50, 69, 9, 6), (70, 200, 5, 5)],
    },
    "chair_stand": {
        "male": [(18, 29, 33, 6), (30, 49, 31, 6), (50, 69, 27, 5), (70, 200, 22, 5)],
        "female": [(18, 29, 31, 6), (30, 49, 29, 6), (50, 69, 25, 5), (70, 200, 20, 5)],
    },
}

# 予後エビデンス順の重み (握力=全死亡最強, 腕立て=CV, SRT=死亡, 椅子=サルコペニア)。
COMPOSITE_WEIGHTS: dict[str, float] = {
    "grip": 0.35,
    "push_up": 0.25,
    "srt": 0.20,
    "chair_stand": 0.20,
}


def fitness_norm(
    test_key: str, age: int | None, sex: str | None
) -> tuple[float, float] | None:
    """連続値テストの年代帯 (mean, sd)。該当無しは None。"""
    if age is None or sex is None:
        return None
    table = FITNESS_NORMS.get(test_key, {}).get(sex)
    if not table:
        return None
    for lo, hi, mean, sd in table:
        if lo <= age <= hi:
            return (mean, sd)
    return None


def fitness_percentile(
    test_key: str, value: float | None, age: int | None, sex: str | None
) -> float | None:
    """連続値テストの同年代・同性 percentile (0-100)。算出不能なら None。"""
    band = fitness_norm(test_key, age, sex)
    if band is None:
        return None
    return pct_from(value, band[0], band[1])


def srt_percentile(value: float | None) -> float | None:
    """SRT (0-10) を percentile (0-100) に線形換算 (目安)。総合点への算入用。"""
    if value is None:
        return None
    return max(0.0, min(100.0, value * 10.0))


def composite_fitness(per_test_pct: dict[str, float | None]) -> dict[str, Any] | None:
    """測定済みテストの percentile を予後エビデンス重みで加重平均 (0-100)。

    未測定テストは除外し、残りの重みで再正規化する。1 件も無ければ None。
    """
    contributions: list[dict[str, Any]] = []
    weighted_sum = 0.0
    weight_total = 0.0
    for key, weight in COMPOSITE_WEIGHTS.items():
        pct = per_test_pct.get(key)
        if pct is None:
            continue
        weighted_sum += weight * pct
        weight_total += weight
        contributions.append({"key": key, "percentile": round(pct, 1), "weight": weight})
    if weight_total <= 0:
        return None
    return {
        "score": round(weighted_sum / weight_total, 1),
        "n_tests": len(contributions),
        "contributions": contributions,
    }


def evaluate(
    test_key: str, value: float | None, age: int | None = None, sex: str | None = None
) -> dict[str, Any] | None:
    """基準値バンドを返す。年齢・性別が無い/対象外なら None (絶対値のみ表示)。"""
    if value is None:
        return None
    defn = FITNESS_TESTS.get(test_key)
    if defn is None:
        return None
    # 基準値は成人男性エビデンスベース。性別不明/年齢不明では誤評価を避け None。
    if age is None or sex != "male":
        return None
    bands = _MALE_BANDS.get(test_key)
    if not bands:
        return None
    chosen = bands[-1]
    for b in bands:
        if value >= b.min_value:
            chosen = b
            break
    return {"status": chosen.status, "label": chosen.label, "reference": defn.reference}


def compute_trend(
    test_key: str, current: float | None, previous: float | None
) -> dict[str, Any] | None:
    """前回比と MDC 判定。previous が無ければ None (初回)。"""
    if current is None or previous is None:
        return None
    defn = FITNESS_TESTS.get(test_key)
    if defn is None:
        return None
    delta = current - previous
    is_real = abs(delta) >= defn.mdc
    direction = "up" if delta > 0 else "down" if delta < 0 else "flat"
    # 良し悪しは higher_is_better で解釈 (全採用テストは高いほど良い)
    improved = None
    if direction != "flat":
        improved = (delta > 0) if defn.higher_is_better else (delta < 0)
    return {
        "delta": round(delta, 1),
        "is_real_change": is_real,
        "direction": direction,
        "improved": improved,
        "mdc": defn.mdc,
    }


def compute_due(
    test_key: str, last_on: date_type | None, today: date_type
) -> dict[str, Any]:
    """再測定の due 判定。テストごとに retest_weeks が異なる。未測定は即 due。"""
    defn = FITNESS_TESTS.get(test_key)
    weeks = defn.retest_weeks if defn else 4
    if last_on is None:
        return {"last_on": None, "due_on": None, "is_due": True, "days_until": None}
    due_on = last_on + timedelta(weeks=weeks)
    days_until = (due_on - today).days
    return {
        "last_on": last_on.isoformat(),
        "due_on": due_on.isoformat(),
        "is_due": today >= due_on,
        "days_until": days_until,
    }


def grip_best(left: float | None, right: float | None) -> float | None:
    """握力の左右ベスト (高い方)。両方 None なら None。"""
    vals = [v for v in (left, right) if v is not None]
    return max(vals) if vals else None


def _two_latest(session, test_key: str) -> tuple[FitnessTestResult | None, FitnessTestResult | None]:
    """最新と1つ前の結果 (performed_on 降順)。"""
    rows = (
        session.execute(
            select(FitnessTestResult)
            .where(FitnessTestResult.test_key == test_key)
            .order_by(FitnessTestResult.performed_on.desc())
            .limit(2)
        )
        .scalars()
        .all()
    )
    latest = rows[0] if rows else None
    prev = rows[1] if len(rows) > 1 else None
    return latest, prev


def def_payload(defn: FitnessTestDef) -> dict[str, Any]:
    """テスト定義を API/フロント向け dict に。"""
    return {
        "key": defn.key,
        "label": defn.label,
        "target": defn.target,
        "protocol": defn.protocol,
        "equipment": defn.equipment,
        "est_minutes": defn.est_minutes,
        "unit": defn.unit,
        "retest_weeks": defn.retest_weeks,
        "warmup": defn.warmup,
        "migraine_note": defn.migraine_note,
        "reference": defn.reference,
        "steps": list(defn.steps),
        "has_lr": defn.has_lr or defn.key == "grip",
        "measure_mode": defn.measure_mode,
    }


def build_overview(today: date_type) -> dict[str, Any]:
    """全テストの定義 + 最新結果 + 評価 + トレンド + 次回推奨をまとめる。"""
    prof = resolve_profile()
    tests: list[dict[str, Any]] = []
    any_due = False
    due_labels: list[str] = []
    per_test_pct: dict[str, float | None] = {}
    with session_scope() as session:
        for key, defn in FITNESS_TESTS.items():
            latest, prev = _two_latest(session, key)
            latest_value = latest.value if latest else None
            latest_on = latest.performed_on if latest else None
            evaluation = evaluate(key, latest_value, prof.age, prof.sex)
            trend = compute_trend(key, latest_value, prev.value if prev else None)
            due = compute_due(key, latest_on, today)
            if due["is_due"]:
                any_due = True
                due_labels.append(defn.label)

            # 分布 (連続3種は釣鐘、SRTは段階評価なので釣鐘なし) と総合用 percentile
            distribution: dict[str, Any] | None = None
            if key == "srt":
                pct = srt_percentile(latest_value)
            else:
                band = fitness_norm(key, prof.age, prof.sex)
                pct = pct_from(latest_value, band[0], band[1]) if band else None
                if pct is not None and band is not None:
                    distribution = {
                        "mean": band[0],
                        "sd": band[1],
                        "percentile": round(pct, 1),
                    }
            per_test_pct[key] = pct

            tests.append(
                {
                    "definition": def_payload(defn),
                    "latest": (
                        {
                            "value": latest_value,
                            "performed_on": latest_on.isoformat() if latest_on else None,
                            "detail": latest.detail_json if latest else None,
                            "note": latest.note if latest else None,
                        }
                        if latest
                        else None
                    ),
                    "evaluation": evaluation,
                    "trend": trend,
                    "due": due,
                    "distribution": distribution,
                }
            )
    return {
        "tests": tests,
        "any_due": any_due,
        "due_labels": due_labels,
        "evaluable": prof.age is not None and prof.sex == "male",
        "composite": composite_fitness(per_test_pct),
    }
