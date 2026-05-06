from __future__ import annotations

from collections.abc import Mapping


def composite_score(
    subscores: Mapping[str, float | None], weights: Mapping[str, float]
) -> float | None:
    """Weighted geometric mean.

    None subscores are skipped and weights are renormalised over the remaining keys.
    Zero values are floored at 1.0 to avoid the entire product collapsing to zero.
    """
    items: list[tuple[float, float]] = []
    for key, weight in weights.items():
        v = subscores.get(key)
        if v is None:
            continue
        items.append((max(float(v), 1.0), float(weight)))

    if not items:
        return None

    total_weight = sum(w for _, w in items)
    if total_weight == 0:
        return None

    log_sum = 0.0
    for value, weight in items:
        # log(value^w) = w * log(value); compute via math but avoid importing twice
        from math import log

        log_sum += weight * log(value)

    from math import exp

    return exp(log_sum / total_weight)
