"""概日リズム指標 (時刻=循環量) の循環統計。

睡眠中点のような「時刻 (0-24h)」は 0 と 24 が同一点の循環量なので、
通常の算術平均/標準偏差では 0 時をまたぐ人で破綻する
(例: 23:50 と 0:10 を行き来する人は実際 ±0.2h なのに線形 SD は ~12h)。
角度に変換して扱う (Mardia の円周統計)。
"""

from __future__ import annotations

import math


def _to_angles(hours: list[float]) -> list[float]:
    return [(h % 24.0) / 24.0 * 2.0 * math.pi for h in hours]


def circular_mean_hour(hours: list[float]) -> float | None:
    """時刻リストの循環平均 (0-24h)。空なら None。"""
    if not hours:
        return None
    angles = _to_angles(hours)
    s = sum(math.sin(a) for a in angles)
    c = sum(math.cos(a) for a in angles)
    if abs(s) < 1e-12 and abs(c) < 1e-12:
        return None  # 完全に打ち消し合う (対蹠) → 平均は定義不能
    mean_angle = math.atan2(s, c)
    if mean_angle < 0:
        mean_angle += 2.0 * math.pi
    return mean_angle / (2.0 * math.pi) * 24.0


def circular_sd_hours(hours: list[float]) -> float | None:
    """時刻リストの循環標準偏差 (時間単位)。2 点未満は None。

    R = 平均合成ベクトル長。SD = sqrt(-2 ln R) (ラジアン) を時間に換算。
    R→1 で SD→0 (集中)、R→0 で SD→大 (散らばり)。
    """
    if len(hours) < 2:
        return None
    angles = _to_angles(hours)
    n = len(angles)
    s = sum(math.sin(a) for a in angles) / n
    c = sum(math.cos(a) for a in angles) / n
    r = math.sqrt(s * s + c * c)
    if r <= 1e-9:
        # ほぼ一様分布。SD は時計の最大ばらつき (約 6.9h) で頭打ち
        return 24.0 / (2.0 * math.pi) * math.sqrt(-2.0 * math.log(1e-9))
    sd_rad = math.sqrt(-2.0 * math.log(r))
    return sd_rad / (2.0 * math.pi) * 24.0
