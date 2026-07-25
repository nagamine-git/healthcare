"""就寝前の「認知的覚醒」(反芻思考・頭が止まらない状態) に対して瞑想プロトコルを出し分ける。

``scoring/wind_down.py`` (呼吸法) との**役割分担**が設計の要:

- **wind_down (呼吸法)**: HRV低下・安静時心拍上昇・カフェイン残量など**生理的覚醒**の指標を見て、
  cyclic_sigh / slow_6 のような**呼吸を意図的に操作する**プロトコルを処方する。
  交感神経優位を最速で鎮めたい急性局面が対象。
- **meditation (このモジュール)**: 主観ストレス (「頭が止まらない」反芻思考) という
  **認知的覚醒**の指標を見て、body_scan / breath_awareness のような
  **呼吸を操作せずただ観察する**プロトコルを処方する。時間に余裕がある局面が対象。

呼吸法との決定的な違いは「呼吸を操作するか否か」である。Balban MY et al. 2023
(*Cell Reports Medicine*, RCT) は cyclic sighing (呼吸法) とマインドフルネス瞑想を
別群として比較し、急性の気分改善では呼吸法が優れることを示した — 裏を返せば
両者は代替可能な同じ介入ではなく、対象とする状態も機序も異なるという設計上の根拠になる。

# 判定の優先順 (先に該当した分岐を採用)
1. **none (就寝目標超過)**: 就寝目標をすでに過ぎている。瞑想より睡眠そのものを優先する。
   wind_down 側の sleep_now と衝突しないよう、瞑想はここでは絶対に勧めない。
2. **body_scan (主観ストレスが高い)**: 反芻思考が走っている時ほど、抽象的な「呼吸」よりも
   足→頭と辿る具体的な**身体感覚のアンカー**の方が注意を維持しやすい。ボディスキャンは
   MBSR/MBTI (mindfulness-based therapy for insomnia) の中核要素であり、
   Ong JC et al. 2014 (*Sleep*, RCT) は MBTI が不眠重症度を有意に低下させたことを示した。
3. **breath_awareness (それ以外で時間がある)**: 呼吸の出入りを**操作せずただ観る**、
   最もシンプルで導入しやすいマインドフルネス実践。Black DS et al. 2015
   (*JAMA Internal Medicine*, 高齢者 RCT) はマインドフルネス実践が睡眠の質を
   改善することを示した。
4. **none (時間不足)**: 選ばれたプロトコルの最低所要分数すら就寝までに確保できない場合は、
   中途半端なセッションを強いるより自然な wind-down に任せる (無理に割り込ませない)。

呼び出し側 (API) が既存の睡眠逆算 (``scoring/sleep_plan.py``) と直近の主観チェックイン
(``models/health.py:SubjectiveCheckin.stress``) から数値を集め、ここには渡すだけにする
(DB/時刻に依存しない純関数)。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

Action = Literal["meditate", "none"]
Protocol = Literal["body_scan", "breath_awareness"] | None

# --- ボディスキャンで辿る部位の順序 (clinical: MBSR/MBTI の標準的な順序、個人差で変えない) ---
_BODY_SCAN_ORDER: tuple[str, ...] = (
    "足の裏",
    "脚",
    "骨盤",
    "お腹",
    "胸",
    "背中",
    "手",
    "腕",
    "肩",
    "首",
    "顔",
    "頭",
)

# --- プロトコルの手順 (clinical: 誰にでも共通の固定手順) ---
_BODY_SCAN_STEPS: tuple[str, ...] = (
    "楽な姿勢で目を閉じ、まず全身の重みを感じる",
    "呼吸は変えようとせず、あるがままの自然な呼吸に任せる (ここが呼吸法との違い)",
    "案内に合わせて意識を体の部位へ順に移し、そこにある感覚 (温度・重さ・圧・しびれ等) をただ観察する",
    "考えが逸れたことに気づいたら、責めずにそっと今の部位の感覚へ意識を戻す",
)
_BREATH_AWARENESS_STEPS: tuple[str, ...] = (
    "楽な姿勢で目を閉じ、呼吸を変えようとせず、あるがままの自然な呼吸に任せる (操作しない)",
    "息が鼻先・胸・お腹を出入りする感覚をただ観察する — 深くしたり整えたりしない",
    "考えが逸れたことに気づいたら、責めずにそっと呼吸の感覚へ意識を戻す",
)

_PROTOCOL_LABELS = {"body_scan": "ボディスキャン", "breath_awareness": "呼吸瞑想 (観るだけ)"}


def _minutes_to_bedtime(now: datetime, target_bedtime: datetime) -> float:
    return (target_bedtime - now).total_seconds() / 60.0


def _session_minutes(available_min: float, lo: int, hi: int, target_min: int) -> int:
    """就寝までの残り時間に収まるよう、セッション分数を決める。

    ``wind_down.py:_protocol_minutes`` と同じ発想だが、こちらは急性の生理的鎮静を
    急がないため「できるだけ ``target_min`` (config の meditation_target_min) に寄せ、
    [lo, hi] の範囲でクランプし、最後に残り時間で上から抑える」という優先順にする。
    """
    if available_min <= 0:
        return 0
    preferred = min(max(target_min, lo), hi)
    capped = min(float(preferred), available_min)
    if capped < lo:
        return max(1, int(capped))
    return int(capped)


def _body_scan_segments(total_minutes: int) -> list[dict[str, Any]]:
    """総分数を部位の数で等分し、余りは先頭のセグメントから 1 秒ずつ配って
    合計が ``total_minutes * 60`` 秒に厳密に一致するようにする。"""
    total_sec = total_minutes * 60
    n = len(_BODY_SCAN_ORDER)
    base_sec, remainder = divmod(total_sec, n)
    return [
        {"label": label, "seconds": base_sec + (1 if i < remainder else 0)}
        for i, label in enumerate(_BODY_SCAN_ORDER)
    ]


def _breath_awareness_segments(total_minutes: int) -> list[dict[str, Any]]:
    """breath_awareness は単一セグメント (「呼吸をただ観る」の 1 本)。"""
    return [{"label": "呼吸をただ観る", "seconds": total_minutes * 60}]


def recommend_meditation(
    *,
    now: datetime,
    target_bedtime: datetime,
    stress_level: int | None = None,
    minutes_target: int = 15,
    stress_high_threshold: int = 4,
    body_scan_min_min: int = 8,
    body_scan_max_min: int = 15,
    breath_awareness_min_min: int = 5,
    breath_awareness_max_min: int = 12,
    bell_interval_sec: int | None = 90,
) -> dict[str, Any]:
    """現在の状態から瞑想の推奨 (ボディスキャン/呼吸瞑想/不要) を返す。

    Args:
        now: 現在時刻 (TZ-aware)
        target_bedtime: 今夜の就寝目標時刻 (TZ-aware、``now`` と同じ TZ)。
            wind_down api と同様に ``scoring/sleep_plan.py:compute_tonight_plan`` の
            ``bedtime`` を呼び出し側で datetime に組み立てて渡す想定。
        stress_level: 直近の主観ストレス (1-5、高いほど悪い。``SubjectiveCheckin.stress``)。
            None の場合は「反芻思考が強い」とは判定せず breath_awareness 側に倒す。
        minutes_target: 1 セッションの目標分数 (config の ``meditation_target_min``、
            personal: 1 日の瞑想目標の per-session 版として再利用)。
        残りの ``*_min`` / ``stress_high_threshold`` / ``bell_interval_sec`` は
        ``config.py`` の同名 (``meditation_*``) 設定のデフォルトと一致させている。
        呼び出し側は ``get_settings()`` の値を明示的に渡すこと (このモジュール自体は
        設定を読まない DB/設定非依存の純関数)。

    Returns:
        ``{action, protocol, minutes, headline, reason, steps, segments,
        bell_interval_sec}`` に加え、判定根拠の診断値
        (``minutes_to_bedtime``, ``stress_level``) を含む。
    """
    minutes_to_bedtime = _minutes_to_bedtime(now, target_bedtime)
    past_bedtime = minutes_to_bedtime <= 0

    base = {
        "minutes_to_bedtime": round(minutes_to_bedtime, 1),
        "stress_level": stress_level,
    }

    # 1. 就寝目標をすでに過ぎている → 瞑想より睡眠 (wind_down の sleep_now と衝突させない)
    if past_bedtime:
        return {
            **base,
            "action": "none",
            "protocol": None,
            "minutes": 0,
            "headline": "そのまま就寝を",
            "reason": "就寝目標を過ぎている。瞑想より睡眠そのものを優先する",
            "steps": [],
            "segments": [],
            "bell_interval_sec": None,
        }

    high_stress = stress_level is not None and stress_level >= stress_high_threshold
    if high_stress:
        protocol: Protocol = "body_scan"
        lo, hi = body_scan_min_min, body_scan_max_min
    else:
        protocol = "breath_awareness"
        lo, hi = breath_awareness_min_min, breath_awareness_max_min

    # 4. 選んだプロトコルの最低所要分数すら就寝までに確保できない → 無理に割り込ませず不要
    if minutes_to_bedtime < lo:
        return {
            **base,
            "action": "none",
            "protocol": None,
            "minutes": 0,
            "headline": "そのまま就寝を",
            "reason": "就寝まで時間が足りない。中途半端なセッションより自然な wind-down に任せる",
            "steps": [],
            "segments": [],
            "bell_interval_sec": None,
        }

    minutes = _session_minutes(minutes_to_bedtime, lo, hi, minutes_target)

    if protocol == "body_scan":
        return {
            **base,
            "action": "meditate",
            "protocol": "body_scan",
            "minutes": minutes,
            "headline": "ボディスキャンで思考を鎮める",
            "reason": (
                f"主観ストレスが{stress_level}/5と高め (反芻思考が走りやすい状態)。"
                "こういう時は呼吸のような抽象的な対象より、足から頭へ辿る具体的な"
                "身体感覚をアンカーにする方が注意を維持しやすい (MBTI の中核要素; "
                "Ong JC et al. 2014, Sleep)。呼吸法とは異なり、ここでは呼吸を操作せず"
                "自然なまま観察する"
            ),
            "steps": list(_BODY_SCAN_STEPS),
            "segments": _body_scan_segments(minutes),
            "bell_interval_sec": None,  # 部位が切り替わるたびに注意が自然に再アンカーされるため不要
        }

    # 3. breath_awareness
    return {
        **base,
        "action": "meditate",
        "protocol": "breath_awareness",
        "minutes": minutes,
        "headline": "呼吸瞑想でwind-down",
        "reason": (
            "強い反芻思考の兆候はなく、就寝まで時間もある。呼吸を操作せずただ観察する"
            "呼吸瞑想はマインドフルネス実践の最も基本的な形で、睡眠の質改善の"
            "エビデンスがある (Black DS et al. 2015, JAMA Internal Medicine)"
        ),
        "steps": list(_BREATH_AWARENESS_STEPS),
        "segments": _breath_awareness_segments(minutes),
        # 単一セグメントで部位の切り替えによる自然な再アンカーが無いため、
        # 定期ベルで注意を呼吸へ戻す (body_scan と違いこちらは None にしない)
        "bell_interval_sec": bell_interval_sec,
    }


def protocol_label(protocol: Protocol) -> str | None:
    """protocol key → 表示ラベル。API/UI から使う小ヘルパー。"""
    if protocol is None:
        return None
    return _PROTOCOL_LABELS.get(protocol)
