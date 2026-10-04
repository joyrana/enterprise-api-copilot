"""Deterministic metrics and uncertainty estimates.

Binary relevance throughout (a document is relevant or not). Rank-based metrics return
``None`` for examples with no relevant documents; those are excluded from the mean and
counted separately so unanswerable questions cannot inflate retrieval scores.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterable, Sequence


def recall_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float | None:
    if not relevant:
        return None
    return len(set(ranked[:k]) & relevant) / len(relevant)


def precision_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float | None:
    if not relevant:
        return None
    top = list(ranked[:k])
    return len([d for d in top if d in relevant]) / k


def reciprocal_rank(ranked: Sequence[str], relevant: set[str]) -> float | None:
    if not relevant:
        return None
    for i, doc in enumerate(ranked, start=1):
        if doc in relevant:
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float | None:
    if not relevant:
        return None
    dcg = sum(
        1.0 / math.log2(i + 1) for i, doc in enumerate(ranked[:k], start=1) if doc in relevant
    )
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(relevant), k) + 1))
    return dcg / ideal if ideal else 0.0


def set_prf(predicted: Iterable[str], expected: Iterable[str]) -> tuple[int, int, int]:
    """True positives, false positives, false negatives for one example."""
    p, e = set(predicted), set(expected)
    return len(p & e), len(p - e), len(e - p)


def prf_from_counts(tp: int, fp: int, fn: int) -> dict[str, float]:
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4)}


def mean(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def bootstrap_ci(
    values: Sequence[float], *, seed: int = 20261003, resamples: int = 2000, alpha: float = 0.05
) -> tuple[float, float] | None:
    """Percentile bootstrap CI of the mean. ``None`` for fewer than 5 values."""
    if len(values) < 5:
        return None
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(rng.choice(values) for _ in range(n)) / n for _ in range(resamples))
    lo = means[int((alpha / 2) * resamples)]
    hi = means[min(resamples - 1, int((1 - alpha / 2) * resamples))]
    return round(lo, 4), round(hi, 4)


def percentile(values: Sequence[float], q: float) -> float | None:
    """Nearest-rank percentile; ``None`` when the sample is too small to support it."""
    min_n = {50: 1, 95: 20, 99: 100}.get(int(q), 1)
    if len(values) < min_n:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return round(ordered[rank - 1], 3)


def summarise(values: Sequence[float]) -> dict[str, object]:
    return {"mean": mean(values), "ci95": bootstrap_ci(values), "n": len(values)}


def paired_bootstrap_diff(
    treatment: Sequence[float],
    baseline: Sequence[float],
    *,
    seed: int = 20261004,
    resamples: int = 4000,
    alpha: float = 0.05,
) -> dict[str, object]:
    """Mean of per-example differences (treatment - baseline) with a paired percentile
    bootstrap CI, plus win/loss/tie counts. Pairs are resampled together, so the interval
    reflects the comparison on the same examples rather than two independent samples."""
    if len(treatment) != len(baseline):
        raise ValueError("paired comparison needs equal-length samples")
    diffs = [t - b for t, b in zip(treatment, baseline, strict=True)]
    n = len(diffs)
    out: dict[str, object] = {
        "mean_diff": round(sum(diffs) / n, 4) if n else None,
        "wins": sum(d > 0 for d in diffs),
        "losses": sum(d < 0 for d in diffs),
        "ties": sum(d == 0 for d in diffs),
        "n": n,
        "ci95": None,
    }
    if n >= 5:
        rng = random.Random(seed)
        means = sorted(sum(rng.choice(diffs) for _ in range(n)) / n for _ in range(resamples))
        out["ci95"] = (
            round(means[int(alpha / 2 * resamples)], 4),
            round(means[min(resamples - 1, int((1 - alpha / 2) * resamples))], 4),
        )
    return out
