"""取れる時系列データから「その時間に何をしていたか」を推定する。

確定情報 (睡眠・ワークアウト・カレンダー予定) を優先し、空白の時間帯は
生理・活動データ (歩数・心拍・ストレス) から状態をヒューリスティック推定する。
あくまで推定 (proxy) であり、各セグメントに確度 (confidence) を付ける。
"""

from __future__ import annotations

from dataclasses import dataclass

BIN_MIN = 15  # 推定の時間解像度 (分)


@dataclass
class Bin:
    steps: float = 0.0
    hr_sum: float = 0.0
    hr_n: int = 0
    stress_sum: float = 0.0
    stress_n: int = 0

    @property
    def hr(self) -> float | None:
        return self.hr_sum / self.hr_n if self.hr_n else None

    @property
    def stress(self) -> float | None:
        return self.stress_sum / self.stress_n if self.stress_n else None


def _classify(
    b: Bin, resting_hr: float
) -> tuple[str, float]:
    """1 ビンを (ラベル, 確度 0-1) に分類。生理データのみのフォールバック判定。"""
    steps = b.steps  # 15分あたりの歩数
    hr = b.hr
    stress = b.stress
    hr_active = resting_hr + 18  # 明確に活動的とみなす心拍

    # 移動・運動レベルの歩行
    if steps >= 600:
        return ("外出・運動", 0.7)
    if steps >= 200:
        return ("移動・家事", 0.6)

    # 低歩数帯 (座位中心) は心拍とストレスで分ける
    if hr is not None and hr >= hr_active and steps < 100:
        # 動いていないのに心拍が高い = 集中負荷 or 緊張
        return ("集中・負荷高め", 0.4)
    if stress is not None and stress >= 55:
        return ("デスクワーク・集中", 0.5)
    if stress is not None and stress < 30 and (hr is None or hr <= resting_hr + 6):
        return ("休息・リラックス", 0.5)
    if steps < 30 and (hr is None or hr <= resting_hr + 8):
        return ("安静・座位", 0.5)
    return ("デスクワーク・軽活動", 0.4)


def build_day_story(
    *,
    now_h: float | None,
    sleep: dict | None,
    workouts: list[dict],
    events: list[dict],
    steps: list[tuple[float, float]],  # (hour, steps)
    heart_rate: list[tuple[float, float]],
    stress: list[tuple[float, float]],
    resting_hr: float | None,
) -> dict:
    """セグメント一覧 + 自然言語サマリを返す。"""
    rhr = resting_hr or 50.0
    end_h = now_h if now_h is not None else 24.0

    # ビンに集約
    n_bins = int(24 * 60 / BIN_MIN)
    bins = [Bin() for _ in range(n_bins)]

    def _idx(h: float) -> int:
        return max(0, min(n_bins - 1, int(h * 60 / BIN_MIN)))

    for h, v in steps:
        bins[_idx(h)].steps += v
    for h, v in heart_rate:
        b = bins[_idx(h)]
        b.hr_sum += v
        b.hr_n += 1
    for h, v in stress:
        b = bins[_idx(h)]
        b.stress_sum += v
        b.stress_n += 1

    def _in_any(h: float, ranges: list[tuple[float, float]]) -> bool:
        return any(s <= h < e for s, e in ranges)

    sleep_ranges: list[tuple[float, float]] = []
    if sleep:
        sleep_ranges.append((max(0.0, sleep["start_h"]), sleep["end_h"]))
    workout_ranges = [(w["start_h"], w["end_h"]) for w in workouts]
    event_ranges = [(e["start_h"], e["end_h"], e["title"]) for e in events]

    # 各ビンを分類 (確定情報優先)
    labels: list[tuple[str, float, str]] = []  # (label, confidence, source)
    for i in range(n_bins):
        h = (i * BIN_MIN + BIN_MIN / 2) / 60
        if h > end_h:
            labels.append(("", 0.0, "future"))
            continue
        if _in_any(h, sleep_ranges):
            labels.append(("睡眠", 0.95, "sleep"))
        elif _in_any(h, workout_ranges):
            wt = next((w.get("type") for w in workouts if w["start_h"] <= h < w["end_h"]), None)
            labels.append((_workout_label(wt), 0.95, "workout"))
        elif any(s <= h < e for s, e, _ in event_ranges):
            title = next(t for s, e, t in event_ranges if s <= h < e)
            labels.append((title or "予定", 0.85, "calendar"))
        else:
            lab, conf = _classify(bins[i], rhr)
            labels.append((lab, conf, "inferred"))

    # 連続する同ラベルをセグメントに結合 (短すぎる断片は隣に吸収)
    segments: list[dict] = []
    for i, (lab, conf, src) in enumerate(labels):
        if src == "future" or not lab:
            continue
        start_h = round(i * BIN_MIN / 60, 2)
        end = round((i + 1) * BIN_MIN / 60, 2)
        if segments and segments[-1]["label"] == lab and segments[-1]["source"] == src:
            segments[-1]["end_h"] = end
        else:
            segments.append(
                {"start_h": start_h, "end_h": end, "label": lab,
                 "confidence": conf, "source": src}
            )

    segments = _smooth(segments)
    summary = _summarize(segments, sleep)
    return {"segments": segments, "summary": summary}


def _workout_label(wtype: str | None) -> str:
    m = {
        "strength_training": "筋トレ",
        "boxing": "ボクシング",
        "breathwork": "呼吸法",
        "walking": "ウォーキング",
        "running": "ランニング",
    }
    return m.get(wtype or "", "運動")


def _smooth(segments: list[dict]) -> list[dict]:
    """15分未満の推定セグメントは前のセグメントに吸収して読みやすくする。"""
    if not segments:
        return segments
    out: list[dict] = [segments[0]]
    for seg in segments[1:]:
        dur = seg["end_h"] - seg["start_h"]
        if seg["source"] == "inferred" and dur <= 0.25 and out:
            out[-1]["end_h"] = seg["end_h"]  # 前に吸収
        elif out and out[-1]["label"] == seg["label"]:
            out[-1]["end_h"] = seg["end_h"]
        else:
            out.append(seg)
    return out


def _summarize(segments: list[dict], sleep: dict | None) -> str:
    """セグメントの合計時間から 1-2 文のサマリを組む (rule-based、決定的)。"""
    from collections import defaultdict

    totals: dict[str, float] = defaultdict(float)
    for s in segments:
        if s["source"] in ("inferred", "workout"):
            totals[s["label"]] += s["end_h"] - s["start_h"]

    parts: list[str] = []
    if sleep:
        sh = sleep["end_h"] - max(0.0, sleep["start_h"])
        parts.append(f"睡眠{sh:.1f}h")

    # 起きている時間の最大カテゴリ
    ranked = sorted(totals.items(), key=lambda kv: -kv[1])
    main = [f"{lab}{dur:.1f}h" for lab, dur in ranked[:3] if dur >= 0.3]
    if main:
        parts.append("・".join(main) + "が中心")

    return "、".join(parts) + "の1日" if parts else "データ収集中"
