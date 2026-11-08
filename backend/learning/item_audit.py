"""A stratified audit sample of check-item keys and the key-error rate it
measures (spec §13 A124; the 2026-11-07 direction audit's stage 0: "an
instructor or TA audits a stratified sample of generated items for key
errors").

Pure: imports learning.params only (pure), so it is listed in
tests/test_learning_loop_invariants.py::PURE_MODULES.

The independent solve (learning/item_keys.py) is a model checking a model; the
audit is the human measurement of how often a stored key is still wrong. Staff
judge each sampled item's key correct, wrong or ambiguous
(services/check_item_service.py::record_item_audit, the admin route and
scripts/audit_check_item_keys.py), and `summary` reports the course's
key-error rate with a Wilson 95% interval — overall and by the key's status
when it was audited (verified by the solve, held, or unverified), so the audit
also measures what the solve check catches and what it lets through.

The sample (`stratified_sample`) is stratified by format × difficulty ×
concept: the n items are allocated over the format × difficulty strata in
proportion to their sizes (largest remainder), and each stratum's quota is
filled one item at a time, in turn across the strata, with the item whose
concept has been sampled least so far (ties by a seeded pseudo-random rank of
its question hash). Every format and difficulty is covered in proportion, and
no concept is sampled twice before every concept of a stratum has been
sampled once. A course holds about one item per (format, difficulty,
concept), so a full three-way proportional allocation would round every
stratum to zero; this is that allocation's balanced equivalent. Within a
stratum the inclusion probabilities stay equal up to the concept spread, so
the plain proportion and its Wilson interval are the estimate (the sample is
treated as self-weighting). Deterministic: the same population and seed give
the same sample.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence

from learning.params import CHECK_ITEM_FORMATS, ITEM_AUDIT_VERDICTS, WILSON_Z_95

CORRECT, WRONG, AMBIGUOUS = ITEM_AUDIT_VERDICTS
#: The key's status when it was audited (check_item_audits.key_status).
KEY_STATUSES = ("verified", "held", "unverified")

_SEP = "\x1f"


def _rank(seed: str, *parts) -> str:
    """A seeded pseudo-random rank: the sha256 of the seed and `parts`."""
    body = _SEP.join(str(p) for p in (seed, *parts))
    return hashlib.sha256(body.encode("utf-8", errors="replace")).hexdigest()


def _format_order(fmt) -> int:
    return CHECK_ITEM_FORMATS.index(fmt) if fmt in CHECK_ITEM_FORMATS else len(CHECK_ITEM_FORMATS)


def _attr(item, name):
    return item.get(name) if isinstance(item, dict) else getattr(item, name, None)


def _allocate(n: int, sizes: dict, *, seed: str) -> dict:
    """Largest-remainder proportional allocation of `n` over strata of `sizes`
    (each quota at most its stratum's size); ties by a seeded rank."""
    total = sum(sizes.values())
    exact = {k: n * size / total for k, size in sizes.items()}
    quota = {k: min(sizes[k], math.floor(v)) for k, v in exact.items()}
    left = n - sum(quota.values())
    order = sorted(
        (k for k in sizes if quota[k] < sizes[k]),
        key=lambda k: (-(exact[k] - math.floor(exact[k])), _rank(seed, "stratum", *k)),
    )
    for k in order[:left]:
        quota[k] += 1
    return quota


def stratified_sample(items: Iterable, n: int, *, seed: str) -> list:
    """`n` of `items` (CheckItems, or dicts with the same plaintext fields:
    id, question_hash, concept_key, format, difficulty), stratified by format
    × difficulty × concept as the module docstring says; every item when there
    are no more than `n`. Ordered by stratum (format, then difficulty), then
    as picked."""
    pool = list(items)
    if n <= 0 or not pool:
        return []
    by_stratum: dict[tuple, list] = defaultdict(list)
    for item in pool:
        fmt, level = _attr(item, "format"), _attr(item, "difficulty")
        key = (_format_order(fmt), str(fmt), level if isinstance(level, int) else 0)
        by_stratum[key].append(item)
    strata = sorted(by_stratum)
    for key in strata:
        by_stratum[key].sort(key=lambda i: _rank(seed, _attr(i, "question_hash"), _attr(i, "id")))
    if n >= len(pool):
        return [i for key in strata for i in by_stratum[key]]
    quota = _allocate(n, {k: len(by_stratum[k]) for k in strata}, seed=seed)
    taken: dict[tuple, list[int]] = {k: [] for k in strata}
    concept_counts: Counter = Counter()
    remaining = dict(quota)
    while any(remaining.values()):
        for key in strata:
            if not remaining[key]:
                continue
            stratum = by_stratum[key]
            left = [j for j in range(len(stratum)) if j not in taken[key]]
            # rank order is the list's: min() keeps the first of equal counts
            best = min(left, key=lambda j: concept_counts[_attr(stratum[j], "concept_key")])
            taken[key].append(best)
            concept_counts[_attr(stratum[best], "concept_key")] += 1
            remaining[key] -= 1
    return [by_stratum[key][j] for key in strata for j in taken[key]]


def wilson(k: int, n: int, z: float = WILSON_Z_95) -> tuple[float, float] | None:
    """The Wilson score interval of k successes in n trials (None for n = 0):
    a proportion's interval that stays inside [0, 1] and is not degenerate at
    0 or n successes, unlike the normal approximation."""
    if n <= 0:
        return None
    p = k / n
    z2 = z * z
    denom = 1 + z2 / n
    center = (p + z2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    # at 0 or n successes the bound on that side is exactly 0 or 1 (in exact
    # arithmetic center ∓ half is): set it, not a float a hair inside it
    low = 0.0 if k <= 0 else max(0.0, center - half)
    high = 1.0 if k >= n else min(1.0, center + half)
    return low, high


def _rate(k: int, n: int) -> dict:
    ci = wilson(k, n)
    return {
        "rate": k / n if n else None,
        "ci_low": ci[0] if ci else None,
        "ci_high": ci[1] if ci else None,
    }


def _counts(verdicts: Sequence[str]) -> dict:
    counted = Counter(v for v in verdicts if v in ITEM_AUDIT_VERDICTS)
    audited = sum(counted.values())
    return {
        "audited": audited,
        **{v: counted[v] for v in ITEM_AUDIT_VERDICTS},
        # the key-error rate: a key the auditor found wrong
        "key_error": _rate(counted[WRONG], audited),
        # the upper reading: a wrong key or one that admits another answer
        "key_error_or_ambiguous": _rate(counted[WRONG] + counted[AMBIGUOUS], audited),
    }


def summary(rows: Iterable[dict]) -> dict:
    """The course's audit summary over its check_item_audits rows (verdict,
    key_status): counts, the key-error rate with its Wilson 95% interval, the
    same counting an ambiguous key as an error, and both by key status."""
    rows = list(rows)
    out = _counts([r.get("verdict") for r in rows])
    out["by_key_status"] = {
        status: _counts([r.get("verdict") for r in rows if r.get("key_status") == status])
        for status in KEY_STATUSES
    }
    return out
