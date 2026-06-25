"""現在地 vs 理想プロファイルのギャップ算出と、多角測定の合成 (DB 非依存)。

設計方針:
- 各次元の「現在地」は 0-100。SJT ベースラインを起点に、意思決定ログの観測を
  EWMA で畳み込んで最新値を出す (training load の急性/慢性と同じ指数平滑)。
- 「理想への近さ (proximity)」は achievement.upper_achievement を流用し、
  目標未満は線形、目標到達で 100 に正規化する (高いほど理想に近い、で統一)。
- 層別・全体の「アイデンティティ整合度」は composite.composite_score
  (加重幾何平均) を流用する。1 次元でも極端に低いと全体が引っ張られる
  = 「弱い次元を放置しない」性質が望ましいので幾何平均が適切。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.scoring.achievement import _clamp, upper_achievement
from app.scoring.baselines import ewma
from app.scoring.composite import composite_score
from app.scoring.identity.dimensions import BY_ID, MINDSET_IDS, VALUE_IDS

# 意思決定ログ 1 件の信号 (-1..+1) を観測スコアへ変換する際の振れ幅 (点)。
# signal=+1 で baseline から +SIGNAL_SCALE、-1 で -SIGNAL_SCALE 振れた行動が
# 観測されたと解釈する。
SIGNAL_SCALE = 40.0

# 現在地合成 EWMA の既定 span (観測数ベース)。新しい観測ほど重い。
DEFAULT_EWMA_SPAN = 8

# proximity 算出のフロア。0 から目標まで線形に伸ばす。
PROXIMITY_FLOOR = 0.0


def signal_to_observation(baseline: float, signal: float) -> float:
    """意思決定ログの信号 (-1..+1) を 0-100 の観測スコアに変換する。

    baseline (SJT 現在地) を中心に SIGNAL_SCALE だけ振らせる。
    """
    return _clamp(float(baseline) + float(signal) * SIGNAL_SCALE)


def blend_current(
    sjt_baseline: float | None,
    observations: Sequence[float] | None = None,
    span: int = DEFAULT_EWMA_SPAN,
) -> float | None:
    """SJT ベースライン + 意思決定ログ観測 (時系列, 0-100) を EWMA 合成する。

    観測は古い順。ベースラインを系列の先頭アンカーに置き、観測を重ねて最新値を返す。
    観測が無ければベースラインそのもの、ベースラインが無ければ観測の EWMA を返す。
    """
    obs = [float(o) for o in (observations or [])]
    if sjt_baseline is None:
        return ewma(obs, span=span) if obs else None
    series: list[float] = [float(sjt_baseline), *obs]
    return ewma(series, span=span)


def proximity_to_target(current: float | None, target: float) -> float | None:
    """現在地の「理想への近さ」を 0-100 で返す。目標到達で 100。"""
    if current is None:
        return None
    if target <= PROXIMITY_FLOOR:
        return 100.0
    return upper_achievement(float(current), PROXIMITY_FLOOR, float(target))


def dimension_gap(current: float | None, target: float) -> float | None:
    """残ギャップ (目標 - 現在地、下限 0)。大きいほど伸びしろが大きい。"""
    if current is None:
        return None
    return max(0.0, float(target) - float(current))


def identity_alignment(
    currents: Mapping[str, float | None],
    targets: Mapping[str, float],
    weights: Mapping[str, float],
) -> float | None:
    """次元別の proximity を重み付き幾何平均して全体整合度 (0-100) を返す。"""
    proximities: dict[str, float | None] = {}
    for dim_id, target in targets.items():
        proximities[dim_id] = proximity_to_target(currents.get(dim_id), target)
    return composite_score(proximities, weights)


def compute_gap_report(
    currents: Mapping[str, float | None],
    targets: Mapping[str, float],
    weights: Mapping[str, float],
) -> dict:
    """ダッシュボード用のギャップ集計を組み立てる。

    返り値:
      dimensions: 次元別の {id, layer, name, current, target, proximity, gap, weight}
      layers: 層別整合度 {values, mindset}
      overall: 全体アイデンティティ整合度
      weakest: ギャップの大きい順の次元 id (推薦の起点)
    """
    dims_out: list[dict] = []
    for dim_id, target in targets.items():
        dim = BY_ID.get(dim_id)
        cur = currents.get(dim_id)
        dims_out.append(
            {
                "id": dim_id,
                "layer": dim.layer if dim else None,
                "name": dim.name_ja if dim else dim_id,
                "current": cur,
                "target": float(target),
                "proximity": proximity_to_target(cur, target),
                "gap": dimension_gap(cur, target),
                "weight": float(weights.get(dim_id, 1.0)),
            }
        )

    value_targets = {k: v for k, v in targets.items() if k in VALUE_IDS}
    mindset_targets = {k: v for k, v in targets.items() if k in MINDSET_IDS}

    layers = {
        "values": identity_alignment(currents, value_targets, weights),
        "mindset": identity_alignment(currents, mindset_targets, weights),
    }
    overall = identity_alignment(currents, targets, weights)

    # ギャップが算出できた次元を伸びしろの大きい順に並べる (推薦の起点)。
    ranked = [d for d in dims_out if d["gap"] is not None]
    ranked.sort(key=lambda d: d["gap"], reverse=True)
    weakest = [d["id"] for d in ranked]

    return {
        "dimensions": dims_out,
        "layers": layers,
        "overall": overall,
        "weakest": weakest,
    }
