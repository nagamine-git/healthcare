"""「昨夜の睡眠」を成分ごとに評価し、崩れている成分への改善点を返す (DB 非依存の純関数)。

# 割合の分母について (⚠️ 事前に既存コードを確認して決めた)
``SleepSession.total_min`` は「総睡眠時間」であって「床上時間」ではない。
- ``ingest/garmin_client.py`` は Garmin の ``sleepTimeSeconds`` (中途覚醒を含まない実睡眠時間)
  をそのまま ``total_min`` に入れている。
- ``ingest/hae_parser.py`` も ``totalSleep``(無ければ deep+rem+core の合算、awake を含まない)
  を ``total_min`` にしている。
- 既存の睡眠効率計算 (``scoring/sleep_drivers.py`` / ``scoring/sleep_interventions.py``) は
  いずれも ``efficiency = total_min / (total_min + awake_min) * 100`` としており、
  ``total_min`` を「awake を含まない実睡眠」として扱っている前提と一致する。
よって深睡眠(deep)・REM の「割合」は **総睡眠時間 (total_min) に対する比率** とする
(床上時間 = total_min + awake_min に対する比率ではない)。これは深睡眠/REM 比率の
臨床文献 (Ohayon et al. 2017 等) が一般に "% of total sleep time" で報告している慣習とも合う。

# 改善点の出し方 (n-of-1 優先、無ければ一般論)
崩れた成分ごとに、まず本人データの ``scoring/sleep_drivers.py:analyze()`` が出す
``quality`` 要因 (tier が strong/suggestive = 実証済みとみなす) の中から対応する
outcome を探し、あれば「あなたのデータでは」型の改善点を優先して出す。無ければ
一般的な睡眠生理の機序に基づく改善点 (根拠はコメント参照) にフォールバックする。
どちらの根拠かは ``basis: "personal" | "general"`` で区別する。
統計用語 (有意・p値・q値) は利用者向け文言に出さない (``next_action`` の作法に合わせる)。

このモジュールは医学的診断を行わない (本アプリは医療機器ではない)。
"""

from __future__ import annotations

from typing import Any, Literal

Status = Literal["good", "low", "high"]
Basis = Literal["personal", "general"]
Verdict = Literal["good", "mixed", "poor"]

# --- 臨床の目安値 (誰にでも共通。個人設定ではないためここではモジュール定数として持つ) ---

# 深睡眠(N3)の総睡眠時間に対する割合。成人でおおむね 13-23% 程度が目安とされる
# (Ohayon M et al. 2017, "National Sleep Foundation's sleep quality recommendations:
#  first report", Sleep Health 3(1) のコンセンサス目安として一般に引用される範囲)。
# 上限を超えても問題視しない (深睡眠は回復的な段階であり、多い分には基本的に不利益がない)。
DEEP_PCT_LOW = 13.0
DEEP_PCT_HIGH = 23.0

# REM の総睡眠時間に対する割合。概ね 20-25% が目安 (同上 Ohayon 2017 系のコンセンサス目安)。
# 深睡眠と同様、上限超過は判定に使わない (参考表示のみ)。
REM_PCT_LOW = 20.0
REM_PCT_HIGH = 25.0

# 睡眠効率 (total_min / (total_min + awake_min) * 100)。85% 以上が一般に良好とされる目安
# (AASM/NSF 系のコンセンサスで広く使われる閾値)。
EFFICIENCY_GOOD_MIN = 85.0

# 中途覚醒時間 (WASO: wake after sleep onset) の目安上限。成人 (18-64歳) では
# 20分以下が「適切」とされる (Ohayon et al. 2017 の年齢別推奨レンジ)。
AWAKE_GOOD_MAX_MIN = 20.0

# 総睡眠時間の個人目標 (sleep_need_min) に対する許容誤差。1 回の睡眠周期 (約90分) の
# 半分未満のばらつきは夜ごとの自然変動として許容し、毎晩「不足」と判定しないための
# 緩衝 (personal な厳密さではなく、判定のノイズ耐性のための固定値)。
SLEEP_TOTAL_TOLERANCE_MIN = 30.0

# --- 崩れた成分 → sleep_drivers.analyze()["quality"] の対応する outcome key ---
# sleep_drivers の outcome には rem_min や awake 専用の項目が無い。REM は総合指標である
# sleep_score を代理指標として使い、中途覚醒(awake)は定義上そのまま efficiency に効くため
# efficiency を使う。total(総睡眠時間)は sleep_drivers 側に対応する outcome が無いため
# 常に一般論にフォールバックする (personal な要因分析の対象外)。
_COMPONENT_OUTCOME_KEYS: dict[str, tuple[str, ...]] = {
    "deep": ("deep_min",),
    "rem": ("sleep_score",),
    "efficiency": ("efficiency",),
    "awake": ("efficiency",),
    "total": (),
}

_PERSONAL_TIERS = ("strong", "suggestive")
_TIER_JA = {"strong": "確度: 強い", "suggestive": "確度: 示唆的"}

# ドライバーが「悪化(direction=悪化, 高いほど悪化)」のときの一般的な対処文言。
# sleep_plan.py の具体アンカー(時刻計算)には依存しない、簡潔な行動レベルの文言に留める
# (このモジュールは DB/時刻に依存しない純関数として保つため)。
_DRIVER_AVOID_HINTS: dict[str, str] = {
    "midpoint": "今より早めに就寝する",
    "irregular": "就寝・起床の時刻をなるべく揃える",
    "caffeine_pm": "夕方以降のカフェインを控える",
    "alcohol_eve": "就寝前の飲酒を控える(アルコールはREMを抑制する)",
    "stress": "就寝前にリラックスする時間を作る(呼吸法・入浴等)",
    "steps": "就寝直前の高強度な活動を避ける",
    "medication": "頭痛薬の使用状況を見直す",
    "duration": "睡眠不足が続かないようにする",
}
# ドライバーが「改善(direction=改善, 高いほど改善)」のときの一般的な後押し文言。
_DRIVER_ENCOURAGE_HINTS: dict[str, str] = {
    "exercise": "日中の運動習慣を続ける",
    "steps": "日中こまめに動く",
    "duration": "睡眠時間を今の水準以上に確保する",
    "morning_light": "起床後に朝の光を浴びる習慣を続ける",
    "caffeine_pm": "今のカフェイン習慣を維持する(悪影響なし)",
}

# --- 成分ごとの一般論フォールバック (personal な実証要因が無い場合) ---
# 根拠:
# - deep: 深睡眠は睡眠前半に偏って出現し、深部体温の上昇やカフェインの残留で
#   妨げられやすい (Dijk DJ 2009 睡眠段階の概日/ホメオスタシス制御に関する総説等)。
# - rem: REM は睡眠後半に偏って出現するため、総睡眠時間が短いと真っ先に削られやすい。
#   アルコールは REM を抑制する (Ebrahim IO et al. 2013, "Alcohol and sleep I", Alcohol
#   Clin Exp Res のレビュー)。
# - efficiency: 入眠潜時や中途覚醒の増加が効率を下げる。就寝前の光・カフェイン・
#   スマートフォン使用は入眠を妨げやすい (Chang AM et al. 2015, PNAS など)。
# - awake: 中途覚醒は寝室環境(温度・光・音)や自律神経の高ぶりで増えやすい。
# - total: 単純に必要睡眠時間に対して実睡眠時間が不足している。
_GENERAL_IMPROVEMENTS: dict[str, dict[str, str]] = {
    "deep": {
        "text": "就寝直前の高強度な運動・カフェインを避け、寝室を涼しく保つ",
        "why": "深睡眠は睡眠の前半に偏って出現し、高体温やカフェインの残留で妨げられやすい",
    },
    "rem": {
        "text": "総睡眠時間を長めに確保し、夜の飲酒を控える",
        "why": "REMは睡眠後半に偏って出現するため総睡眠時間が短いと削られやすく、"
        "アルコールはREM自体を抑制する",
    },
    "efficiency": {
        "text": "就寝前の強い光・カフェイン・スマートフォン使用を控える",
        "why": "入眠に時間がかかったり中途覚醒が増えたりすると睡眠効率が下がる",
    },
    "awake": {
        "text": "寝室の温度・光・音を整え、就寝前にリラックスする時間を作る",
        "why": "中途覚醒は寝室環境や自律神経の高ぶりで増えやすい",
    },
    "total": {
        "text": "就寝時刻を早める、または起床時刻を遅らせる",
        "why": "必要睡眠時間に対して実際の睡眠時間が不足している",
    },
}

_GOOD_PHRASE: dict[str, str] = {
    "deep": "深い睡眠は十分",
    "rem": "REMは十分",
    "efficiency": "睡眠効率は良好",
    "awake": "中途覚醒は少ない",
    "total": "睡眠時間は足りている",
}
_BAD_PHRASE: dict[str, str] = {
    "deep": "深い睡眠が少ない",
    "rem": "REMが短い",
    "efficiency": "睡眠効率が低い",
    "awake": "中途覚醒が多い",
    "total": "睡眠時間が足りない",
}
_HEADLINE_ORDER = ("deep", "efficiency", "rem", "awake", "total")


def _round1(v: float | None) -> float | None:
    return round(v, 1) if v is not None else None


def _pct(part: float | None, whole: float | None) -> float | None:
    if part is None or whole is None or whole <= 0:
        return None
    return part / whole * 100


def _component_deep(total_min: int, deep_min: int | None) -> dict[str, Any] | None:
    if deep_min is None:
        return None
    pct = _pct(deep_min, total_min)
    status: Status = "low" if pct is not None and pct < DEEP_PCT_LOW else "good"
    return {
        "key": "deep", "label": "深睡眠", "minutes": deep_min, "pct": _round1(pct),
        "status": status, "reference": f"{DEEP_PCT_LOW:.0f}-{DEEP_PCT_HIGH:.0f}%",
    }


def _component_rem(total_min: int, rem_min: int | None) -> dict[str, Any] | None:
    if rem_min is None:
        return None
    pct = _pct(rem_min, total_min)
    status: Status = "low" if pct is not None and pct < REM_PCT_LOW else "good"
    return {
        "key": "rem", "label": "REM", "minutes": rem_min, "pct": _round1(pct),
        "status": status, "reference": f"{REM_PCT_LOW:.0f}-{REM_PCT_HIGH:.0f}%",
    }


def _component_efficiency(total_min: int, awake_min: int | None) -> dict[str, Any] | None:
    if awake_min is None:
        return None
    tib = total_min + awake_min
    if tib <= 0:
        return None
    eff = total_min / tib * 100
    status: Status = "good" if eff >= EFFICIENCY_GOOD_MIN else "low"
    return {
        "key": "efficiency", "label": "睡眠効率", "minutes": None, "pct": _round1(eff),
        "status": status, "reference": f"{EFFICIENCY_GOOD_MIN:.0f}%以上",
    }


def _component_awake(total_min: int, awake_min: int | None) -> dict[str, Any] | None:
    if awake_min is None:
        return None
    tib = total_min + awake_min
    status: Status = "good" if awake_min <= AWAKE_GOOD_MAX_MIN else "high"
    return {
        "key": "awake", "label": "中途覚醒", "minutes": awake_min,
        "pct": _round1(_pct(awake_min, tib)),
        "status": status, "reference": f"{AWAKE_GOOD_MAX_MIN:.0f}分以下",
    }


def _component_total(total_min: int, sleep_need_min: int) -> dict[str, Any]:
    status: Status = "good" if total_min >= sleep_need_min - SLEEP_TOTAL_TOLERANCE_MIN else "low"
    return {
        "key": "total", "label": "総睡眠時間", "minutes": total_min,
        "pct": _round1(_pct(total_min, sleep_need_min)),
        "status": status, "reference": f"{sleep_need_min}分(目標)",
    }


def _best_personal_factor(
    driver_quality: list[dict[str, Any]], outcome_keys: tuple[str, ...]
) -> dict[str, Any] | None:
    """指定 outcome に対応する、tier が strong/suggestive (=実証済み) な要因のうち最有力のもの。"""
    if not outcome_keys:
        return None
    tier_rank = {"strong": 2, "suggestive": 1}
    candidates = [
        f for f in driver_quality
        if f.get("outcome") in outcome_keys and f.get("tier") in _PERSONAL_TIERS
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda f: -tier_rank.get(f.get("tier"), 0))
    return candidates[0]


def _personal_improvement(
    component_key: str,
    factor: dict[str, Any],
    rec_by_driver: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    driver = factor.get("driver")
    hints = _DRIVER_AVOID_HINTS if factor.get("direction") == "悪化" else _DRIVER_ENCOURAGE_HINTS
    # 既に文章化済みの recommendations (具体的な時刻アンカー入り) があれば優先して使い、
    # 無ければこのモジュール内の簡潔な一般文言にフォールバックする。
    rec = rec_by_driver.get(driver)
    text = rec["text"] if rec is not None else hints.get(driver, f"{factor.get('label')}を見直す")
    return {
        "text": text,
        "why": f"あなたのデータでは、{factor.get('label')}が{factor.get('outcome_label')}と"
        f"関連しています({_TIER_JA.get(factor.get('tier'), '')})",
        "basis": "personal",
        "component": component_key,
    }


def _general_improvement(component_key: str) -> dict[str, Any] | None:
    g = _GENERAL_IMPROVEMENTS.get(component_key)
    if g is None:
        return None
    return {"text": g["text"], "why": g["why"], "basis": "general", "component": component_key}


def _headline(components: list[dict[str, Any]]) -> str:
    by_key = {c["key"]: c for c in components}
    bads = [_BAD_PHRASE[k] for k in _HEADLINE_ORDER if k in by_key and by_key[k]["status"] != "good"]
    goods = [_GOOD_PHRASE[k] for k in _HEADLINE_ORDER if k in by_key and by_key[k]["status"] == "good"]
    if not bads:
        return "睡眠の質は良好でした" if goods else "睡眠データを評価しました"
    lead = f"{goods[0]}。" if goods else ""
    return lead + "・".join(bads[:2])


def _verdict(components: list[dict[str, Any]]) -> Verdict:
    total = len(components)
    if total == 0:
        return "mixed"
    bad = sum(1 for c in components if c["status"] != "good")
    if bad == 0:
        return "good"
    # 崩れている成分が過半数を大きく超える (目安6割以上) なら poor、それ以外は mixed。
    # 臨床的な閾値ではなく UX 上の目安 (product judgement)。
    if bad / total >= 0.6:
        return "poor"
    return "mixed"


def evaluate_last_night(
    *,
    total_min: int | None,
    deep_min: int | None,
    rem_min: int | None,
    light_min: int | None,
    awake_min: int | None,
    sleep_score: float | None,
    sleep_need_min: int,
    driver_quality: list[dict[str, Any]] | None = None,
    driver_recommendations: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """昨夜の睡眠を成分ごとに評価し、崩れている成分への改善点を返す。

    Args:
        total_min/deep_min/rem_min/light_min/awake_min/sleep_score: ``SleepSession`` の該当フィールド。
        sleep_need_min: 個人の目標睡眠時間 (分、``scoring/profile.py:resolve_profile().sleep_need_min``)。
        driver_quality: ``scoring/sleep_drivers.py:analyze()`` が返す ``quality`` (dict の list)。
            未指定なら personal な改善点は出さず、一般論のみになる。
        driver_recommendations: 同 ``analyze()`` の ``recommendations``。文言の使い回し用 (無くても可)。

    Returns:
        その夜のデータが無ければ ``None`` (呼び出し側は ``available: false`` にして何も描かない)。
    """
    if total_min is None or total_min <= 0:
        return None

    components = [
        c for c in (
            _component_deep(total_min, deep_min),
            _component_efficiency(total_min, awake_min),
            _component_rem(total_min, rem_min),
            _component_awake(total_min, awake_min),
            _component_total(total_min, sleep_need_min),
        )
        if c is not None
    ]

    rec_by_driver = {
        r["driver"]: r for r in (driver_recommendations or []) if r.get("driver")
    }
    improvements: list[dict[str, Any]] = []
    for c in components:
        if c["status"] == "good":
            continue
        factor = None
        if driver_quality:
            factor = _best_personal_factor(driver_quality, _COMPONENT_OUTCOME_KEYS.get(c["key"], ()))
        if factor is not None:
            improvements.append(_personal_improvement(c["key"], factor, rec_by_driver))
        else:
            general = _general_improvement(c["key"])
            if general is not None:
                improvements.append(general)
    # personal な根拠を先に出す (ユーザー承認済みの方針)。同 basis 内は成分の優先順を保つ (stable sort)。
    improvements.sort(key=lambda i: 0 if i["basis"] == "personal" else 1)

    return {
        "sleep_score": sleep_score,
        "total_min": total_min,
        "verdict": _verdict(components),
        "headline": _headline(components),
        "components": components,
        "improvements": improvements,
    }
