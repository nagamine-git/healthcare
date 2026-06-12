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
    energy: float = 0.0  # active_energy 合計 (活動強度の proxy)
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


def _classify(b: Bin, resting_hr: float, bb_slope: float | None) -> tuple[str, float]:
    """1 ビンを (ラベル, 確度) に分類。

    Garmin の生理状態を主信号にする (歩数では遠隔デスクワーク中の精神的活動を
    捉えられないため):
    - stress = 自律神経の負荷帯 (安息<26 / 低<51 / 中<76 / 高)。心理ストレスでなく
      交感/副交感のバランス。デスクワークでも上がる。
    - bb_slope = Body Battery の増減 (負=消耗→活動/負荷、正=回復→休息)。
    - steps/energy = 身体的な動き。
    """
    steps = b.steps  # 15分あたりの歩数
    hr = b.hr
    stress = b.stress
    energy = b.energy

    # 信号がほぼ無いビンは「推定」ではなく「記録の谷間」(時計を外した等)。
    # 確度を低くして UI で薄く出す (データ不足を確度0.4の安静に偽装しない)。
    if b.hr_n == 0 and b.stress_n == 0 and steps < 1 and energy < 0.5:
        return ("記録の谷間", 0.12)

    # まず身体的な動き (歩数/消費カロリー) が大きければ移動・運動
    if steps >= 600 or (hr is not None and hr >= resting_hr + 25):
        return ("外出・運動", 0.7)
    if steps >= 200:
        return ("移動・歩き回り", 0.6)
    # 少しの動き = 家事・育児・対人など (歩数は少ないが座りっぱなしではない)
    if steps >= 70:
        return ("活動・家事など", 0.45)

    # 以降は座位中心。Garmin の自律神経 (覚醒度) で「関わっている/休んでいる」を分ける。
    # 注意: 覚醒度は仕事でも育児でも来客でも上がる → 活動の "種類" は断定しない。
    draining = bb_slope is not None and bb_slope <= -3.0  # BB がはっきり減っている
    charging = bb_slope is not None and bb_slope >= 1.5

    if stress is not None:
        if stress >= 76:
            return ("高負荷・緊張", 0.5)
        if stress >= 51:
            return ("集中・活動 (高め)", 0.5)
        if stress >= 26:
            # 中程度の覚醒 = 何かに関わっている (作業・対人・育児など)
            return ("集中・活動", 0.45 if draining else 0.4)
        # 安息帯: BB が回復なら休息、消耗なら軽い在席
        if charging or steps < 20:
            return ("休息・リラックス", 0.55)
        return ("在席・ゆったり", 0.4)

    # stress が無い時間帯は HR/BB で粗く
    if draining and (hr is None or hr >= resting_hr + 8):
        return ("活動中", 0.35)
    if energy > 5:
        return ("軽い活動", 0.35)
    return ("安静・座位", 0.4)


def build_day_story(
    *,
    now_h: float | None,
    sleep: dict | None,
    workouts: list[dict],
    events: list[dict],
    steps: list[tuple[float, float]],  # (hour, steps)
    heart_rate: list[tuple[float, float]],
    stress: list[tuple[float, float]],
    body_battery: list[tuple[float, float]] | None = None,
    active_energy: list[tuple[float, float]] | None = None,
    intensity_min: tuple[float, float] | None = None,  # (moderate, vigorous)
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
    for h, v in active_energy or []:
        bins[_idx(h)].energy += v
    for h, v in heart_rate:
        b = bins[_idx(h)]
        b.hr_sum += v
        b.hr_n += 1
    for h, v in stress:
        b = bins[_idx(h)]
        b.stress_sum += v
        b.stress_n += 1

    # Body Battery を各ビンの代表値に変換 (carry-forward) して傾きを出す
    bb_at: list[float | None] = [None] * n_bins
    for h, v in sorted(body_battery or []):
        bb_at[_idx(h)] = v
    last: float | None = None
    for i in range(n_bins):
        if bb_at[i] is None:
            bb_at[i] = last
        else:
            last = bb_at[i]
    # 傾きは 45分 (3ビン) のスパンで取る。瞬時値はノイズが大きく信頼できない
    # (Firstbeat 合成スコアの独立検証は薄く、トレンドで使うべき: 2024-2025 review)。
    bb_slope: list[float | None] = [None] * n_bins
    for i in range(n_bins):
        cur = bb_at[i]
        past = bb_at[i - 3] if i >= 3 else None
        if cur is not None and past is not None:
            bb_slope[i] = cur - past

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
            lab, conf = _classify(bins[i], rhr, bb_slope[i])
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
    insights = _insights(
        segments=segments,
        steps_total=sum(v for _, v in steps),
        workouts=workouts,
        intensity_min=intensity_min,
        now_h=end_h,
        awake_from=sleep["end_h"] if sleep else 7.0,
    )
    return {"segments": segments, "summary": summary, "insights": insights}


# 座位中心とみなすラベル (立ち上がり提案の対象)。動きを伴う「活動・家事など」は除く
_SEDENTARY = {
    "安静・座位", "在席・ゆったり", "軽い活動",
    "集中・活動", "集中・活動 (高め)", "高負荷・緊張",
}


def _insights(
    *,
    segments: list[dict],
    steps_total: float,
    workouts: list[dict],
    intensity_min: tuple[float, float] | None,
    now_h: float,
    awake_from: float,
) -> list[dict]:
    """1日の集計から「次にやること」付きの気づきを最大 3 件。データ事実ベース。"""
    out: list[dict] = []
    sedentary_labels = _SEDENTARY

    # 1) 連続して座っている最長ブロック (起床後・現在まで)
    longest = 0.0
    cur = 0.0
    for s in segments:
        if s["source"] == "inferred" and s["label"] in sedentary_labels:
            cur += s["end_h"] - s["start_h"]
            longest = max(longest, cur)
        else:
            cur = 0.0
    # 連続座位の閾値は Diaz 2023 RCT (30分ごと5分歩行で血糖 iAUC 有意低下) に基づく。
    # 1時間超の連続座位は中断推奨ラインとして提示。
    if longest >= 1.0:
        out.append({
            "icon": "sit",
            "tone": "warn",
            "text": f"{longest:.1f}時間ほぼ座りっぱなし",
            "action": "30分ごとに5分歩く (血糖・血圧に効く)。今すぐ立って一周",
        })

    # 2) 運動の有無 (確定情報 + Garmin の強度分)
    did_workout = any(w for w in workouts)
    mod, vig = intensity_min or (0.0, 0.0)
    if did_workout or vig + mod >= 10:
        detail = f"高強度{int(vig)}分・中強度{int(mod)}分" if (vig + mod) > 0 else "運動を記録"
        out.append({
            "icon": "ok",
            "tone": "good",
            "text": f"今日は体を動かせている ({detail})",
            "action": "回復のため水分とタンパク質を忘れずに",
        })
    elif now_h >= 16:
        out.append({
            "icon": "run",
            "tone": "warn",
            "text": "まだ運動の記録がない",
            "action": "10分でいいので有酸素 (シャドーボクシング/加重足踏み) を1本",
        })

    # 3) 歩数 (活動量)。日中をどれだけ過ぎたかで基準を按分
    day_frac = max(0.2, min(1.0, (now_h - awake_from) / (22.0 - awake_from)))
    target_now = 7000 * day_frac
    if steps_total < target_now * 0.6 and now_h >= 12:
        out.append({
            "icon": "walk",
            "tone": "warn",
            "text": f"歩数 {int(steps_total):,} 歩 (この時間帯にしては少なめ)",
            "action": "買い物や休憩を散歩に変えて +1000 歩",
        })
    elif steps_total >= 7000:
        out.append({
            "icon": "ok",
            "tone": "good",
            "text": f"歩数 {int(steps_total):,} 歩 (十分動けている)",
            "action": "この調子。夜は座位を増やしてリラックスに",
        })

    return out[:3]


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
        prev = out[-1]
        # 30分未満の推定の断片は前のセグメントに吸収 (読みやすさ優先)。
        # ただし確定情報 (睡眠/運動/予定) は推定で延ばさない (睡眠が朝まで伸びるバグ防止)
        if seg["source"] == "inferred" and dur < 0.5 and prev["source"] == "inferred":
            prev["end_h"] = seg["end_h"]
        elif prev["label"] == seg["label"] and prev["source"] == seg["source"]:
            prev["end_h"] = seg["end_h"]
        else:
            out.append(seg)
    # 2 周目: 隣接で同ラベルになったものを再結合
    merged: list[dict] = [out[0]]
    for seg in out[1:]:
        if merged[-1]["label"] == seg["label"] and merged[-1]["source"] == seg["source"]:
            merged[-1]["end_h"] = seg["end_h"]
        else:
            merged.append(seg)
    return merged


def _summarize(segments: list[dict], sleep: dict | None) -> str:
    """セグメントの合計時間から 1-2 文のサマリを組む (rule-based、決定的)。"""
    from collections import defaultdict

    # 似たラベルは大分類にまとめてサマリを読みやすく (例: 仕事・集中(負荷高め)→仕事)
    def _bucket(label: str) -> str | None:
        if label == "記録の谷間":
            return None
        if "集中" in label or "負荷" in label or "緊張" in label:
            return "集中・活動"
        if "家事" in label:
            return "家事・育児など"
        if "休息" in label or "リラックス" in label or "ゆったり" in label or "在席" in label:
            return "休息・在席"
        if "外出" in label or "移動" in label or "運動" in label:
            return "活動・運動"
        if "ボクシング" in label or "筋トレ" in label:
            return "運動"
        return label

    totals: dict[str, float] = defaultdict(float)
    for s in segments:
        if s["source"] not in ("inferred", "workout"):
            continue
        b = _bucket(s["label"])
        if b:
            totals[b] += s["end_h"] - s["start_h"]

    parts: list[str] = []
    if sleep:
        sh = sleep["end_h"] - max(0.0, sleep["start_h"])
        parts.append(f"睡眠{sh:.1f}h")

    ranked = sorted(totals.items(), key=lambda kv: -kv[1])
    main = [f"{lab}{dur:.1f}h" for lab, dur in ranked[:3] if dur >= 0.4]
    if main:
        parts.append("・".join(main) + "が中心")

    return "、".join(parts) + "の1日" if parts else "データ収集中"
