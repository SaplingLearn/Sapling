"""Logistic regression (maximum likelihood) with multiway cluster-robust
variance, stdlib only.

`fit_logit` is the GEE estimator with an independence working correlation —
the same point estimates as an ordinary logistic regression. `multiway_vcov`
is the Cameron, Gelbach & Miller (2011, JBES 29(2):238-249) multiway sandwich:
for two dimensions (student, concept)

    V = c_s B M_s B + c_c B M_c B - c_sc B M_sc B

where B = (X'WX)^-1, M_g sums the outer products of the per-cluster score sums
for dimension g, M_sc clusters by the intersection, and c_g = G/(G-1) * (n-1)/(n-p)
is the CR1 small-sample factor of each term. The sum need not be positive
semi-definite in a finite sample; when it is not, its negative eigenvalues are
set to zero (CGM's fix, which only raises variances). Inference uses Student t
with min(G) - 1 degrees of freedom (CGM's conservative choice).

Fitting collapses identical design rows into (pattern, n, successes) cells, so
a design of a few binary columns fits in microseconds whatever n is; only the
sandwich walks the rows.
"""

from __future__ import annotations

import math
from collections.abc import Hashable, Sequence
from dataclasses import dataclass, field
from itertools import combinations

from learning_trial._stats import SingularMatrixError, expit, mat_inv, psd_part, sandwich


class FitError(ValueError):
    """The model cannot be fitted to these data (no outcome variation, a
    singular design, or separation)."""


#: |coefficient| beyond which the likelihood is treated as diverging (separation)
_DIVERGED = 25.0


def _log1pexp(eta: float) -> float:
    return eta + math.log1p(math.exp(-eta)) if eta > 0 else math.log1p(math.exp(eta))


@dataclass(frozen=True)
class LogitFit:
    beta: tuple[float, ...]
    bread_inv: list[list[float]]  # (X'WX)^-1 at beta: the model-based covariance
    loglik: float
    iterations: int
    converged: bool
    n: int
    p: int
    mu: dict[tuple, float] = field(repr=False)  # fitted probability per design pattern

    def predict(self, x: Sequence[float]) -> float:
        return expit(sum(b * v for b, v in zip(self.beta, x)))


def fit_logit(
    x_rows: Sequence[tuple[float, ...]],
    y: Sequence[bool | int],
    *,
    max_iter: int = 60,
    tol: float = 1e-10,
) -> LogitFit:
    """Maximum-likelihood logistic regression by Newton-Raphson with step
    halving. `x_rows` are tuples (they key the pattern collapse)."""
    n = len(x_rows)
    if n == 0 or n != len(y):
        raise FitError("need equal, non-zero numbers of rows and outcomes")
    p = len(x_rows[0])
    cells: dict[tuple, list[int]] = {}
    for x, yi in zip(x_rows, y):
        cell = cells.get(x)
        if cell is None:
            cells[x] = [1, 1 if yi else 0]
        else:
            cell[0] += 1
            cell[1] += 1 if yi else 0
    keys = list(cells)
    counts = [cells[k][0] for k in keys]
    successes = [cells[k][1] for k in keys]
    total = sum(successes)
    if total == 0 or total == n:
        raise FitError("the outcome does not vary")

    def loglik(beta: list[float]) -> float:
        out = 0.0
        for k, nk, n1 in zip(keys, counts, successes):
            eta = sum(b * v for b, v in zip(beta, k))
            out += n1 * eta - nk * _log1pexp(eta)
        return out

    def score_and_info(beta: list[float]) -> tuple[list[float], list[list[float]]]:
        g = [0.0] * p
        h = [[0.0] * p for _ in range(p)]
        for k, nk, n1 in zip(keys, counts, successes):
            mu = expit(sum(b * v for b, v in zip(beta, k)))
            resid = n1 - nk * mu
            w = nk * mu * (1.0 - mu)
            for a in range(p):
                ka = k[a]
                if ka == 0.0:
                    continue
                g[a] += ka * resid
                wa = w * ka
                row = h[a]
                for b in range(p):
                    row[b] += wa * k[b]
        return g, h

    beta = [0.0] * p
    ll = loglik(beta)
    converged = False
    iterations = 0
    for iterations in range(1, max_iter + 1):
        g, h = score_and_info(beta)
        try:
            h_inv = mat_inv(h)
        except SingularMatrixError as exc:
            raise FitError(f"singular information matrix: {exc}") from None
        step = [sum(hij * gj for hij, gj in zip(row, g)) for row in h_inv]
        scale = 1.0
        while True:
            trial = [b + scale * s for b, s in zip(beta, step)]
            new_ll = loglik(trial)
            if new_ll >= ll - 1e-12 or scale < 1e-8:
                break
            scale *= 0.5
        delta = max(abs(scale * s) for s in step)
        beta, ll_prev, ll = trial, ll, new_ll
        if max(abs(b) for b in beta) > _DIVERGED:
            break
        if delta < tol * (1.0 + max(abs(b) for b in beta)) or abs(ll - ll_prev) < tol * (1.0 + abs(ll)):
            converged = True
            break
    _, h = score_and_info(beta)
    try:
        bread_inv = mat_inv(h)
    except SingularMatrixError as exc:
        raise FitError(f"singular information matrix: {exc}") from None
    mu = {k: expit(sum(b * v for b, v in zip(beta, k))) for k in keys}
    return LogitFit(
        beta=tuple(beta),
        bread_inv=bread_inv,
        loglik=ll,
        iterations=iterations,
        converged=converged and max(abs(b) for b in beta) <= _DIVERGED,
        n=n,
        p=p,
        mu=mu,
    )


def _meat(
    x_rows: Sequence[tuple[float, ...]],
    resid: Sequence[float],
    ids: Sequence[Hashable],
    p: int,
) -> tuple[list[list[float]], int]:
    """Sum over clusters of (sum_i x_i r_i)(sum_i x_i r_i)'; and the cluster count."""
    sums: dict[Hashable, list[float]] = {}
    for x, r, g in zip(x_rows, resid, ids):
        s = sums.get(g)
        sums[g] = [v * r for v in x] if s is None else [a + v * r for a, v in zip(s, x)]
    meat = [[0.0] * p for _ in range(p)]
    for s in sums.values():
        for a in range(p):
            sa = s[a]
            if sa == 0.0:
                continue
            row = meat[a]
            for b in range(p):
                row[b] += sa * s[b]
    return meat, len(sums)


@dataclass(frozen=True)
class RobustVcov:
    vcov: list[list[float]]  # the multiway (or one-way) cluster-robust covariance
    clusters: tuple[int, ...]  # cluster count per dimension, in the order given
    df: float  # min(clusters) - 1: the t reference
    one_way: tuple[list[list[float]], ...]  # the one-way covariance per dimension
    fixed: str | None  # set when the multiway matrix was not PSD and its negative part was removed


def multiway_vcov(
    fit: LogitFit,
    x_rows: Sequence[tuple[float, ...]],
    y: Sequence[bool | int],
    dims: Sequence[Sequence[Hashable]],
) -> RobustVcov:
    """The CGM multiway cluster-robust covariance over `dims` (each a sequence
    of cluster ids aligned with the rows), by inclusion-exclusion over every
    non-empty subset of dimensions, each term clustered by the intersection
    and scaled by its own CR1 factor. One dimension = the usual one-way
    cluster-robust covariance."""
    if not dims:
        raise ValueError("at least one clustering dimension")
    n, p = fit.n, fit.p
    resid = [(1.0 if yi else 0.0) - fit.mu[x] for x, yi in zip(x_rows, y)]
    small = (n - 1) / (n - p) if n > p else 1.0
    terms: dict[tuple[int, ...], tuple[list[list[float]], int]] = {}
    for size in range(1, len(dims) + 1):
        for subset in combinations(range(len(dims)), size):
            ids = dims[subset[0]] if size == 1 else list(zip(*(dims[i] for i in subset)))
            terms[subset] = _meat(x_rows, resid, ids, p)
    total = [[0.0] * p for _ in range(p)]
    for subset, (meat, groups) in terms.items():
        if groups < 2:
            raise FitError("cluster-robust variance needs at least two clusters per dimension")
        sign = 1.0 if len(subset) % 2 == 1 else -1.0
        factor = sign * groups / (groups - 1) * small
        for a in range(p):
            for b in range(p):
                total[a][b] += factor * meat[a][b]
    one_way = tuple(
        sandwich(fit.bread_inv, [[terms[(i,)][1] / (terms[(i,)][1] - 1) * small * v for v in row]
                                 for row in terms[(i,)][0]])
        for i in range(len(dims))
    )
    vcov = sandwich(fit.bread_inv, total)
    fixed = None
    if len(dims) > 1:
        # CGM (2011) §2.3: the inclusion-exclusion sum need not be positive
        # semi-definite in a finite sample; set its negative eigenvalues to zero.
        # That can only raise each variance, so the fix is conservative.
        repaired, clipped = psd_part(vcov)
        if clipped:
            vcov = repaired
            fixed = "multiway covariance was not positive semi-definite; its negative eigenvalues were set to zero"
    clusters = tuple(terms[(i,)][1] for i in range(len(dims)))
    return RobustVcov(
        vcov=vcov,
        clusters=clusters,
        df=float(min(clusters) - 1),
        one_way=one_way,
        fixed=fixed,
    )
