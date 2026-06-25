"""Garden の純粋な判定ロジック(DB・ネット非依存、単体テスト対象)。"""

from __future__ import annotations


def _catalog_entry(kind: str, catalog: list[dict]) -> dict | None:
    for c in catalog:
        if c["kind"] == kind:
            return c
    return None


def weight_factor(
    kind: str, catalog: list[dict], gaps: dict[str, float | None], gamma: float
) -> float:
    """行動 kind の重み係数。紐づく次元の最大 gap(0-100)で 1〜(1+gamma) 倍。

    紐づく次元が全て未測定(None)/欠落なら 1.0 にフォールバック。
    """
    entry = _catalog_entry(kind, catalog)
    if entry is None:
        return 1.0
    present = [g for d in entry["dimensions"] if (g := gaps.get(d)) is not None]
    if not present:
        return 1.0
    return 1.0 + gamma * (max(present) / 100.0)


def bucket_level(intensity: float, thresholds: list[float]) -> int:
    """intensity を 0-4 のレベルへ。thresholds=[t0,t1,t2,t3]。

    intensity<=t0 → 0、t0<..<=t1 → 1、t1<..<=t2 → 2、t2<..<=t3 → 3、t3< → 4。
    """
    if intensity <= thresholds[0]:
        return 0
    for i, t in enumerate(thresholds[1:], start=1):
        if intensity <= t:
            return i
    return len(thresholds)


def cell_focus(contributions: dict[str, float], catalog: list[dict], gamma: float) -> float:
    """その日の努力の「重点度」を 0..1 で返す(寄与で重み付けした平均)。

    重みは gap 連動 (contrib = base * (1 + gamma*gap/100)) なので、
    保存済み contributions と base から重点度 (gap/100) を逆算できる。
    1.0 = 盲点(重点)に全振り、0.0 = すでに強い領域への努力。
    """
    if gamma <= 0:
        return 0.0
    base = {c["kind"]: c["base"] for c in catalog}
    total = sum(contributions.values())
    if total <= 0:
        return 0.0
    fsum = 0.0
    for kind, contrib in contributions.items():
        b = base.get(kind)
        if not b:
            continue
        focus_k = max(0.0, (contrib / b - 1.0) / gamma)
        fsum += contrib * focus_k
    return round(fsum / total, 4)


def compute_garden_day(
    active_kinds: set[str],
    catalog: list[dict],
    gaps: dict[str, float | None],
    gamma: float,
    thresholds: list[float],
) -> dict:
    """その日に観測された行動種別から草の強さ・レベル・寄与を算出。"""
    contributions: dict[str, float] = {}
    for kind in active_kinds:
        entry = _catalog_entry(kind, catalog)
        if entry is None:
            continue
        contributions[kind] = round(entry["base"] * weight_factor(kind, catalog, gaps, gamma), 4)
    intensity = round(sum(contributions.values()), 4)
    return {
        "intensity": intensity,
        "level": bucket_level(intensity, thresholds),
        "contributions": contributions,
    }
