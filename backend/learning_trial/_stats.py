"""Small numerical kernels for the trial analysis: stdlib only.

The app venv has no numpy or scipy, and this package must not add them to the
app's requirements, so the few pieces the analysis needs are written out here:
the logistic link, normal and Student-t distribution functions, and dense
linear algebra for the small (p x p, p < ~40) matrices of a regression with a
handful of fixed effects.
"""

from __future__ import annotations

import math
from functools import lru_cache
from statistics import NormalDist

_NORMAL = NormalDist()
_FPMIN = 1e-300


class SingularMatrixError(ValueError):
    """The matrix has no usable inverse (collinear design columns)."""


def expit(x: float) -> float:
    """The logistic function, without overflow for large |x|."""
    if x >= 0.0:
        return 1.0 / (1.0 + math.exp(-x))
    z = math.exp(x)
    return z / (1.0 + z)


def logit(p: float) -> float:
    return math.log(p / (1.0 - p))


def norm_cdf(x: float) -> float:
    return _NORMAL.cdf(x)


def norm_ppf(q: float) -> float:
    return _NORMAL.inv_cdf(q)


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (modified Lentz)."""
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > _FPMIN else _FPMIN)
    h = d
    for m in range(1, 500):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > _FPMIN else _FPMIN)
        c = 1.0 + aa / c
        c = c if abs(c) > _FPMIN else _FPMIN
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > _FPMIN else _FPMIN)
        c = 1.0 + aa / c
        c = c if abs(c) > _FPMIN else _FPMIN
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-15:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """The regularized incomplete beta function I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_front = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    front = math.exp(log_front)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def t_two_sided_p(stat: float, df: float) -> float:
    """P(|T| >= |stat|) for Student t with `df` degrees of freedom (normal when
    df is infinite). Computed from the tail directly, so tiny p-values keep
    their precision."""
    if math.isinf(df):
        return 2.0 * norm_cdf(-abs(stat))
    return betainc(df / 2.0, 0.5, df / (df + stat * stat))


def t_cdf(stat: float, df: float) -> float:
    tail = 0.5 * t_two_sided_p(stat, df)
    return 1.0 - tail if stat > 0 else tail


@lru_cache(maxsize=256)
def t_ppf(q: float, df: float) -> float:
    """The q-quantile of Student t (bisection on t_cdf; cached: the analysis
    asks for the same few quantiles many times in a power simulation)."""
    if not 0.0 < q < 1.0:
        raise ValueError("q must be in (0, 1)")
    if math.isinf(df):
        return norm_ppf(q)
    if q < 0.5:
        return -t_ppf(1.0 - q, df)
    lo, hi = 0.0, 1.0
    while t_cdf(hi, df) < q:
        hi *= 2.0
        if hi > 1e8:
            return math.inf
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if t_cdf(mid, df) < q:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-12 * max(1.0, hi):
            break
    return 0.5 * (lo + hi)


def mat_inv(a: list[list[float]]) -> list[list[float]]:
    """Inverse of a square matrix by Gauss-Jordan elimination with partial
    pivoting. Raises SingularMatrixError on a (numerically) singular matrix."""
    n = len(a)
    scale = max((abs(v) for row in a for v in row), default=0.0)
    if scale == 0.0:
        raise SingularMatrixError("zero matrix")
    m = [[float(v) for v in row] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) <= 1e-12 * scale:
            raise SingularMatrixError(f"singular at column {col}")
        if pivot != col:
            m[col], m[pivot] = m[pivot], m[col]
        inv_p = 1.0 / m[col][col]
        prow = [v * inv_p for v in m[col]]
        m[col] = prow
        for r in range(n):
            if r == col:
                continue
            f = m[r][col]
            if f != 0.0:
                row = m[r]
                m[r] = [rv - f * pv for rv, pv in zip(row, prow)]
    return [row[n:] for row in m]


def sym_eigen(a: list[list[float]], *, max_sweeps: int = 100) -> tuple[list[float], list[list[float]]]:
    """Eigenvalues and eigenvectors (the columns of the returned matrix) of a
    symmetric matrix, by cyclic Jacobi rotations."""
    n = len(a)
    m = [[float(v) for v in row] for row in a]
    vec = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    scale = sum(m[i][i] ** 2 for i in range(n)) or 1.0
    for _ in range(max_sweeps):
        off = sum(m[i][j] ** 2 for i in range(n) for j in range(n) if i != j)
        if off <= 1e-30 * scale:
            break
        for p in range(n - 1):
            for q in range(p + 1, n):
                if m[p][q] == 0.0:
                    continue
                theta = (m[q][q] - m[p][p]) / (2.0 * m[p][q])
                t = (1.0 if theta >= 0 else -1.0) / (abs(theta) + math.sqrt(theta * theta + 1.0))
                c = 1.0 / math.sqrt(t * t + 1.0)
                s = t * c
                for k in range(n):
                    mkp, mkq = m[k][p], m[k][q]
                    m[k][p], m[k][q] = c * mkp - s * mkq, s * mkp + c * mkq
                for k in range(n):
                    mpk, mqk = m[p][k], m[q][k]
                    m[p][k], m[q][k] = c * mpk - s * mqk, s * mpk + c * mqk
                for k in range(n):
                    vkp, vkq = vec[k][p], vec[k][q]
                    vec[k][p], vec[k][q] = c * vkp - s * vkq, s * vkp + c * vkq
    return [m[i][i] for i in range(n)], vec


def psd_part(a: list[list[float]]) -> tuple[list[list[float]], bool]:
    """The positive semi-definite part of a symmetric matrix (its negative
    eigenvalues set to zero) and whether anything was clipped beyond rounding."""
    values, vectors = sym_eigen(a)
    tol = 1e-12 * max((abs(v) for v in values), default=0.0)
    clipped = any(v < -tol for v in values)
    kept = [max(v, 0.0) for v in values]
    n = len(a)
    out = [
        [sum(vectors[i][k] * kept[k] * vectors[j][k] for k in range(n)) for j in range(n)] for i in range(n)
    ]
    return out, clipped


def mat_mul(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    bt = list(zip(*b))
    return [[sum(x * y for x, y in zip(row, col)) for col in bt] for row in a]


def sandwich(bread_inv: list[list[float]], meat: list[list[float]]) -> list[list[float]]:
    """bread_inv @ meat @ bread_inv (the bread is symmetric)."""
    return mat_mul(mat_mul(bread_inv, meat), bread_inv)


def quad_form(v: list[float], m: list[list[float]]) -> float:
    """v' m v."""
    return sum(vi * sum(mij * vj for mij, vj in zip(row, v)) for vi, row in zip(v, m))
