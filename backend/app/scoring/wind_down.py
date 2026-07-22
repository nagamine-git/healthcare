"""就寝前の状態から「すぐ寝ろ」か「どの呼吸法を何分か」を出し分ける。

一律に瞑想/呼吸法を勧めるのではなく、今の生理指標 (睡眠負債・HRV・安静時心拍・
カフェイン残量) と就寝目標までの残り時間から、4 択の中で最も ROI の高い一手を返す。

# 判定の優先順 (先に該当した分岐を採用)
1. **sleep_now**: 就寝目標を過ぎている、または (睡眠負債が大きい AND 就寝目標まで残りわずか)。
   呼吸法より睡眠そのものを優先する — 起きている1分が負債を増やす局面。
2. **breathe / cyclic_sigh**: 強い過覚醒 (HRV がベースライン比で大きく低下、または
   安静時心拍がベースラインより明確に高い)。
   Balban MY et al. 2023, *Cell Reports Medicine* (RCT): cyclic sighing
   (二段吸気+長い呼気を反復) は箱呼吸(box breathing)やマインドフルネス瞑想より
   気分改善が大きく、呼吸数の低下も大きかった。急な交感神経優位を最速で鎮める用途に
   最も強いエビデンス。
3. **breathe / slow_6**: wind-down 窓 (就寝目標の直前) にいて、軽度の過覚醒
   またはカフェイン残量あり。
   毎分約6呼吸・吸気4秒/呼気6秒 (呼気を吸気より長くする) は、副交感神経(迷走神経)緊張を
   最大化する共鳴周波数呼吸に近い (Lehrer PM & Gevirtz R 2014; Steffen PR et al. 2017 の
   メタ解析で HRV/迷走神経緊張の増加が確認されている、心理生理学的エビデンスとしては最厚)。
4. **none**: 過覚醒の兆候が無く、就寝までまだ時間がある。無理に呼吸法を割り込ませず
   自然な wind-down に任せる。

呼び出し側 (API) が既存の睡眠逆算 (``scoring/sleep_plan.py``)・HRV ベースライン
(``scoring/baselines.py``)・カフェイン残量 (``scoring/caffeine.py``) 等から数値を集め、
ここには渡すだけにする (DB/時刻に依存しない純関数)。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

Action = Literal["sleep_now", "breathe", "none"]
Protocol = Literal["cyclic_sigh", "slow_6"] | None

# --- 呼吸法プロトコルの手順 (clinical: 誰にでも共通の固定手順、個人差では変えない) ---
_CYCLIC_SIGH_STEPS: tuple[str, ...] = (
    "鼻からゆっくり大きく吸う (肺を満たす)",
    "肺が最大まで膨らんだところで、鼻からもう一度短く鋭く吸い足す (二段吸気)",
    "口からゆっくり長く吐き切る (吸気の合計より長く、ため息のように)",
)
_SLOW_6_STEPS: tuple[str, ...] = (
    "鼻から4秒かけて吸う",
    "口(または鼻)から6秒かけてゆっくり吐く (吸気より長い呼気で迷走神経緊張を上げる)",
    "これを毎分約6呼吸 (10秒/呼吸) のペースで繰り返す",
)

_PROTOCOL_LABELS = {"cyclic_sigh": "サイクリック・サイ", "slow_6": "スロー共鳴呼吸 (6呼吸/分)"}


def _protocol_minutes(available_min: float, lo: int, hi: int) -> int:
    """就寝までの残り時間に収まるよう、プロトコル分数を [lo, hi] の範囲で決める。

    残り時間が hi を超えるなら hi (上限あり)。lo 未満しか残っていない場合は
    収まる分だけ (最低 1 分) を返す。
    """
    if available_min <= 0:
        return 0
    capped = min(float(hi), available_min)
    if capped < lo:
        return max(1, int(capped))
    return int(capped)


def _minutes_to_bedtime(now: datetime, target_bedtime: datetime) -> float:
    return (target_bedtime - now).total_seconds() / 60.0


def _hrv_drop_pct(hrv_last: float | None, hrv_baseline: float | None) -> float | None:
    """HRV のベースライン比の低下率 (0.3 = 30% 低下)。上昇時は負値。"""
    if hrv_last is None or hrv_baseline is None or hrv_baseline <= 0:
        return None
    return (hrv_baseline - hrv_last) / hrv_baseline


def _rhr_rise(resting_hr: float | None, resting_hr_baseline: float | None) -> float | None:
    """安静時心拍のベースライン比の上昇幅 (bpm)。低下時は負値。"""
    if resting_hr is None or resting_hr_baseline is None:
        return None
    return resting_hr - resting_hr_baseline


def recommend_wind_down(
    *,
    now: datetime,
    target_bedtime: datetime,
    sleep_debt_min: float | None = None,
    hrv_last: float | None = None,
    hrv_baseline: float | None = None,
    resting_hr: float | None = None,
    resting_hr_baseline: float | None = None,
    caffeine_mg_on_board: float | None = None,
    wind_down_window_min: int = 45,
    large_sleep_debt_min: float = 90.0,
    bedtime_soon_min: float = 20.0,
    hrv_drop_strong_pct: float = 0.30,
    hrv_drop_mild_pct: float = 0.15,
    rhr_rise_strong_bpm: float = 8.0,
    rhr_rise_mild_bpm: float = 4.0,
    caffeine_residual_mg_threshold: float = 30.0,
    cyclic_sigh_min_min: int = 3,
    cyclic_sigh_max_min: int = 5,
    slow6_min_min: int = 5,
    slow6_max_min: int = 10,
) -> dict[str, Any]:
    """現在の状態から睡眠導入の推奨 (すぐ寝る/呼吸法/不要) を返す。

    Args:
        now: 現在時刻 (TZ-aware)
        target_bedtime: 今夜の就寝目標時刻 (TZ-aware、``now`` と同じ TZ)。
            就寝逆算は既存 ``scoring/sleep_plan.py:compute_tonight_plan`` の
            ``bedtime`` を呼び出し側で datetime に組み立てて渡す想定。
        sleep_debt_min: 睡眠負債 (分、正=不足)。既存の直接的な算出モジュールは
            無いため、呼び出し側 (API) が直近日数の不足合計などから計算して渡す。
        hrv_last / hrv_baseline: 直近 HRV とそのベースライン (同一スケール、通常 rMSSD ms)。
        resting_hr / resting_hr_baseline: 安静時心拍とそのベースライン (bpm)。
        caffeine_mg_on_board: 現時点の体内カフェイン推定量 (mg)。
        残りの ``*_min`` / ``*_pct`` / ``*_bpm`` / ``*_mg`` は閾値・プロトコル分数レンジで、
        既定値は ``config.py`` の同名 (``wind_down_*``) 設定のデフォルトと一致させている。
        呼び出し側は ``get_settings()`` の値を明示的に渡すこと (このモジュール自体は
        設定を読まない DB/設定非依存の純関数)。

    Returns:
        ``{action, protocol, minutes, reason, headline}`` に加え、判定根拠の
        診断値 (``minutes_to_bedtime``, ``hrv_drop_pct``, ``rhr_rise_bpm``, ``steps``) を含む。
    """
    minutes_to_bedtime = _minutes_to_bedtime(now, target_bedtime)
    past_bedtime = minutes_to_bedtime <= 0
    hrv_drop = _hrv_drop_pct(hrv_last, hrv_baseline)
    rhr_rise = _rhr_rise(resting_hr, resting_hr_baseline)

    strong_hyperarousal = (hrv_drop is not None and hrv_drop >= hrv_drop_strong_pct) or (
        rhr_rise is not None and rhr_rise >= rhr_rise_strong_bpm
    )
    mild_hyperarousal = (not strong_hyperarousal) and (
        (hrv_drop is not None and hrv_drop >= hrv_drop_mild_pct)
        or (rhr_rise is not None and rhr_rise >= rhr_rise_mild_bpm)
        or (
            caffeine_mg_on_board is not None
            and caffeine_mg_on_board >= caffeine_residual_mg_threshold
        )
    )
    in_wind_down_window = (not past_bedtime) and (0 <= minutes_to_bedtime <= wind_down_window_min)

    base = {
        "minutes_to_bedtime": round(minutes_to_bedtime, 1),
        "hrv_drop_pct": round(hrv_drop, 3) if hrv_drop is not None else None,
        "rhr_rise_bpm": round(rhr_rise, 1) if rhr_rise is not None else None,
    }

    # 1. すぐ寝ろ
    large_debt_and_soon = (
        sleep_debt_min is not None
        and sleep_debt_min >= large_sleep_debt_min
        and not past_bedtime
        and minutes_to_bedtime <= bedtime_soon_min
    )
    if past_bedtime or large_debt_and_soon:
        return {
            **base,
            "action": "sleep_now",
            "protocol": None,
            "minutes": 0,
            "headline": "すぐ寝る",
            "reason": "今は瞑想より睡眠。起きている1分が負債を増やす",
            "steps": [],
        }

    # 2. サイクリック・サイ (強い過覚醒。wind-down 窓の外でも最優先で鎮める)
    if strong_hyperarousal:
        available = minutes_to_bedtime if minutes_to_bedtime > 0 else float(cyclic_sigh_max_min)
        minutes = _protocol_minutes(available, cyclic_sigh_min_min, cyclic_sigh_max_min)
        cause = (
            f"HRV がベースライン比 {hrv_drop * 100:.0f}%低下"
            if hrv_drop is not None and hrv_drop >= hrv_drop_strong_pct
            else f"安静時心拍がベースライン比 +{rhr_rise:.0f}bpm"
        )
        return {
            **base,
            "action": "breathe",
            "protocol": "cyclic_sigh",
            "minutes": minutes,
            "headline": "サイクリック・サイで鎮める",
            "reason": (
                f"{cause}で強い過覚醒 (交感神経優位)。"
                "二段吸気+長い呼気の cyclic sighing は box breathing や瞑想より"
                "気分改善・呼吸数低下が大きいと RCT で確認されている "
                "(Balban 2023, Cell Reports Medicine)。今すぐ最速で鎮める"
            ),
            "steps": list(_CYCLIC_SIGH_STEPS),
        }

    # 3. スロー共鳴呼吸 (wind-down 窓内 + 軽度過覚醒/カフェイン残量)
    if in_wind_down_window and mild_hyperarousal:
        minutes = _protocol_minutes(minutes_to_bedtime, slow6_min_min, slow6_max_min)
        causes = []
        if hrv_drop is not None and hrv_drop >= hrv_drop_mild_pct:
            causes.append(f"HRV がベースライン比 {hrv_drop * 100:.0f}%低下")
        if rhr_rise is not None and rhr_rise >= rhr_rise_mild_bpm:
            causes.append(f"安静時心拍がベースライン比 +{rhr_rise:.0f}bpm")
        if caffeine_mg_on_board is not None and caffeine_mg_on_board >= caffeine_residual_mg_threshold:
            causes.append(f"体内カフェイン残量 約{caffeine_mg_on_board:.0f}mg")
        cause_text = "・".join(causes) if causes else "軽度の過覚醒兆候"
        return {
            **base,
            "action": "breathe",
            "protocol": "slow_6",
            "minutes": minutes,
            "headline": "6呼吸/分でwind-down",
            "reason": (
                f"就寝{wind_down_window_min}分前の wind-down 窓内で{cause_text}。"
                "吸気4秒/呼気6秒・毎分6呼吸の延長呼気呼吸は迷走神経緊張を高め、"
                "HRV バイオフィードバックのエビデンスとして最も厚い "
                "(Lehrer & Gevirtz 2014; Steffen 2017 メタ解析)"
            ),
            "steps": list(_SLOW_6_STEPS),
        }

    # 4. 不要
    return {
        **base,
        "action": "none",
        "protocol": None,
        "minutes": 0,
        "headline": "そのままで大丈夫",
        "reason": "今は落ち着いている。無理に呼吸法をやらず自然に wind-down を",
        "steps": [],
    }


def protocol_label(protocol: Protocol) -> str | None:
    """protocol key → 表示ラベル。API/UI から使う小ヘルパー。"""
    if protocol is None:
        return None
    return _PROTOCOL_LABELS.get(protocol)
