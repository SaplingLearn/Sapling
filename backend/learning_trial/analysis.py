"""The trial's analyses over the long table (`learning_trial.table`).

PRIMARY — `fit_primary`: post-test correctness (rung 0) regressed on
arm + pretest (+ a missing-pretest indicator) + window (+ prespecified
pre-randomization covariates) by logistic regression — the GEE estimator with
an independence working correlation — with a TWO-WAY (student x concept)
cluster-robust covariance (Cameron, Gelbach & Miller 2011), CR1 small-sample
factors, and Student t inference on min(#students, #concepts) - 1 degrees of
freedom. It is the marginal (population-averaged) analogue of the crossed
random-intercept logistic GLMM the trial specifies; that GLMM itself is the
optional `learning_trial.glmm` path (it needs statsmodels, which the app venv
does not carry). Why this stand-in and where it falls short: see the
preregistration draft, docs/research/learning-loop/2026-11-08-within-student-
trial-preregistration.md §7.

SECONDARY — `paired_difference`: per student, the mean post-test correctness
over treatment concepts minus that over control concepts; the mean over
students with a student-cluster (resample students) percentile bootstrap CI,
and the within-subject standardized mean difference d_av (Lakens 2013).

ROBUSTNESS — `randomization_test`: re-randomizes the arm of every (student,
concept) unit with the design's fair coin (learning/arms.py hashes to one bit)
and refits, giving a p-value that is exact under the sharp null whatever the
clustering structure.

Effect sizes: the log odds ratio; the average marginal effect (risk
difference, probability scale); the WWC Cox index d = ln(OR) / 1.65 (What Works
Clearinghouse Procedures and Standards Handbook v5.0, for dichotomous
outcomes). The Cox index standardizes by the spread of ONE response, so under
the simulation's assumptions it runs at about two fifths of the same effect in
student-ability SDs (the scale of Kraft's test-score benchmarks);
`learning_trial.simulate` reports both.
"""

from __future__ import annotations

import math
import random
import statistics
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from learning_trial._stats import expit, quad_form, t_ppf, t_two_sided_p
from learning_trial.logistic import FitError, fit_logit, multiway_vcov
from learning_trial.table import CONTROL, TREATMENT, TrialRow, analyzable, select

ALPHA = 0.05
#: WWC's Cox index divisor for a log odds ratio
COX_DIVISOR = 1.65
#: the primary outcome's window (spec §13 A112: the 7-day post-test)
PRIMARY_WINDOWS = (7,)
DEFAULT_SEED = 20261108

CLUSTERINGS = ("two-way", "student", "concept")


class AnalysisError(ValueError):
    """The data cannot support the requested analysis."""


@dataclass(frozen=True)
class Estimate:
    estimate: float
    se: float
    low: float
    high: float


@dataclass(frozen=True)
class Coefficient:
    name: str
    estimate: float
    se: float
    stat: float
    p_value: float
    low: float
    high: float


@dataclass(frozen=True)
class PrimaryResult:
    method: str
    windows: tuple[int, ...]
    alpha: float
    clustering: str
    n_obs: int
    n_students: int
    n_concepts: int
    n_by_arm: dict[str, int]
    rate_by_arm: dict[str, float]
    terms: tuple[str, ...]
    dropped_terms: tuple[str, ...]
    coefficients: tuple[Coefficient, ...]
    arm: Coefficient  # log odds ratio, treatment vs control (at the reference window)
    odds_ratio: Estimate  # se is that of the log odds ratio
    risk_difference: Estimate  # average marginal effect of arm, probability scale
    cox_d: Estimate  # WWC Cox index of the adjusted odds ratio
    df: float
    clusters: dict[str, int]
    se_arm_by_clustering: dict[str, float]
    converged: bool
    notes: tuple[str, ...]


@dataclass(frozen=True)
class _Design:
    names: tuple[str, ...]
    x: list[tuple[float, ...]]
    y: list[bool]
    rows: list[TrialRow]
    dropped: tuple[str, ...]
    arm_index: int
    interactions: tuple[tuple[int, int], ...]  # (arm:window column, window column)


def _design(
    rows: Sequence[TrialRow],
    *,
    course_effects: bool,
    covariates: Sequence[str],
    arm_by_window: bool,
    arm_of: Mapping[tuple[str, str], str] | None = None,
) -> _Design:
    """The design matrix. Columns: intercept, arm, pretest, pretest_missing,
    window dummies (first window = reference), optional arm x window, optional
    course dummies (first course = reference), covariates. Columns constant
    over the data are dropped (e.g. window when one window is analyzed).
    `arm_of` overrides the arm per (student, concept) — the randomization
    test's re-assignment."""
    usable = [r for r in rows if all(r.covariate(c) is not None for c in covariates)]
    if not usable:
        raise AnalysisError("no analyzable rows")
    windows = sorted({r.window for r in usable})
    courses = sorted({r.course for r in usable}) if course_effects else []
    names = ["intercept", "arm", "pretest", "pretest_missing"]
    names += [f"window[{w}]" for w in windows[1:]]
    if arm_by_window:
        names += [f"arm:window[{w}]" for w in windows[1:]]
    names += [f"course[{c}]" for c in courses[1:]]
    names += [f"cov[{c}]" for c in covariates]
    later_windows = windows[1:]
    later_courses = courses[1:]
    memo: dict[tuple, tuple[float, ...]] = {}
    full: list[tuple[float, ...]] = []
    for r in usable:
        arm = r.arm if arm_of is None else arm_of[(r.student, r.concept)]
        key = (arm, r.pretest, r.window, r.course if course_effects else None,
               tuple(r.covariate(c) for c in covariates))
        vec = memo.get(key)
        if vec is None:
            a = 1.0 if arm == TREATMENT else 0.0
            wd = [1.0 if r.window == w else 0.0 for w in later_windows]
            vec = (
                (1.0, a, 1.0 if r.pretest else 0.0, 1.0 if r.pretest is None else 0.0)
                + tuple(wd)
                + (tuple(a * v for v in wd) if arm_by_window else ())
                + tuple(1.0 if r.course == c else 0.0 for c in later_courses)
                + tuple(float(r.covariate(c)) for c in covariates)
            )
            memo[key] = vec
        full.append(vec)
    distinct = list(memo.values())
    keep = [0] + [j for j in range(1, len(names)) if len({v[j] for v in distinct}) > 1]
    dropped = tuple(names[j] for j in range(len(names)) if j not in keep)
    if 1 not in keep:
        raise AnalysisError("both arms must be present")
    if len(keep) == len(names):
        x = full
    else:
        project = {v: tuple(v[j] for j in keep) for v in distinct}
        x = [project[v] for v in full]
    kept = tuple(names[j] for j in keep)
    interactions = tuple(
        (kept.index(f"arm:window[{w}]"), kept.index(f"window[{w}]"))
        for w in later_windows
        if f"arm:window[{w}]" in kept and f"window[{w}]" in kept
    )
    return _Design(
        names=kept,
        x=x,
        y=[bool(r.posttest) for r in usable],
        rows=usable,
        dropped=dropped,
        arm_index=kept.index("arm"),
        interactions=interactions,
    )


def _counterfactual(x: tuple[float, ...], design: _Design, arm: float) -> list[float]:
    v = list(x)
    v[design.arm_index] = arm
    for inter, window in design.interactions:
        v[inter] = arm * x[window]
    return v


def _average_marginal_effect(design: _Design, beta: Sequence[float], vcov) -> tuple[float, float]:
    """Mean over the analyzed rows of P(y | treatment, x) - P(y | control, x),
    and its delta-method standard error under `vcov`."""
    p = len(beta)
    total = 0.0
    grad = [0.0] * p
    n = len(design.x)
    for x, count in Counter(design.x).items():
        x1 = _counterfactual(x, design, 1.0)
        x0 = _counterfactual(x, design, 0.0)
        m1 = expit(sum(b * v for b, v in zip(beta, x1)))
        m0 = expit(sum(b * v for b, v in zip(beta, x0)))
        total += count * (m1 - m0)
        w1, w0 = m1 * (1.0 - m1), m0 * (1.0 - m0)
        for j in range(p):
            grad[j] += count * (w1 * x1[j] - w0 * x0[j])
    grad = [g / n for g in grad]
    return total / n, math.sqrt(max(quad_form(grad, vcov), 0.0))


def fit_primary(
    rows: Iterable[TrialRow],
    *,
    windows: Sequence[int] = PRIMARY_WINDOWS,
    clustering: str = "two-way",
    course_effects: bool = False,
    covariates: Sequence[str] = (),
    arm_by_window: bool = False,
    alpha: float = ALPHA,
    _arm_of: Mapping[tuple[str, str], str] | None = None,
) -> PrimaryResult:
    """The primary analysis over the analyzable rows of `windows` (see the
    module docstring). `clustering`: "two-way" (student and concept; the
    preregistered choice), or one-way "student" / "concept" (sensitivity).
    With several windows the window dummies enter (and, with
    `arm_by_window`, arm x window, making `arm` the effect at the first
    window)."""
    if clustering not in CLUSTERINGS:
        raise ValueError(f"clustering must be one of {CLUSTERINGS}")
    data = select(rows, windows)
    design = _design(
        data, course_effects=course_effects, covariates=covariates, arm_by_window=arm_by_window,
        arm_of=_arm_of,
    )
    try:
        fit = fit_logit(design.x, design.y)
        students = [r.student for r in design.rows]
        concepts = [r.concept for r in design.rows]
        dims = {"two-way": [students, concepts], "student": [students], "concept": [concepts]}[clustering]
        robust = multiway_vcov(fit, design.x, design.y, dims)
    except FitError as exc:
        raise AnalysisError(str(exc)) from None
    vcov, df = robust.vcov, robust.df
    crit = t_ppf(1.0 - alpha / 2.0, df)
    coefficients = []
    for j, name in enumerate(design.names):
        est = fit.beta[j]
        se = math.sqrt(max(vcov[j][j], 0.0))  # a rounding-level negative is a zero variance
        if se > 0:
            stat = est / se
            p_value = t_two_sided_p(stat, df)
        else:  # a degenerate (zero) variance supports no test
            stat = p_value = math.nan
        coefficients.append(Coefficient(name, est, se, stat, p_value, est - crit * se, est + crit * se))
    arm = coefficients[design.arm_index]
    rd, rd_se = _average_marginal_effect(design, fit.beta, vcov)
    ia = design.arm_index
    se_by: dict[str, float] = {"model": math.sqrt(max(fit.bread_inv[ia][ia], 0.0))}
    dim_names = {"two-way": ("student", "concept"), "student": ("student",), "concept": ("concept",)}[clustering]
    for name, one in zip(dim_names, robust.one_way):
        se_by[name] = math.sqrt(max(one[ia][ia], 0.0))
    se_by[clustering] = arm.se
    if not arm.se > 0:
        raise AnalysisError("the arm coefficient has no variance: the data cannot test it")
    n_by_arm = {TREATMENT: 0, CONTROL: 0}
    hits = {TREATMENT: 0, CONTROL: 0}
    for r, yi in zip(design.rows, design.y):
        a = r.arm if _arm_of is None else _arm_of[(r.student, r.concept)]
        n_by_arm[a] += 1
        hits[a] += yi
    notes = []
    if robust.fixed:
        notes.append(robust.fixed)
    if not fit.converged:
        notes.append("the likelihood did not converge (possible separation): treat as unreliable")
    if len(data) != len(design.rows):
        notes.append(f"{len(data) - len(design.rows)} rows dropped for a missing covariate")
    return PrimaryResult(
        method=(
            "logistic GEE (independence working correlation) with "
            + {"two-way": "two-way student x concept", "student": "student", "concept": "concept"}[clustering]
            + " cluster-robust (CR1) covariance; t reference on min(clusters) - 1 df"
        ),
        windows=tuple(sorted({r.window for r in design.rows})),
        alpha=alpha,
        clustering=clustering,
        n_obs=len(design.rows),
        n_students=len(set(students)),
        n_concepts=len(set(concepts)),
        n_by_arm=n_by_arm,
        rate_by_arm={a: (hits[a] / n_by_arm[a] if n_by_arm[a] else math.nan) for a in n_by_arm},
        terms=design.names,
        dropped_terms=design.dropped,
        coefficients=tuple(coefficients),
        arm=arm,
        odds_ratio=Estimate(math.exp(arm.estimate), arm.se, math.exp(arm.low), math.exp(arm.high)),
        risk_difference=Estimate(rd, rd_se, rd - crit * rd_se, rd + crit * rd_se),
        cox_d=Estimate(
            arm.estimate / COX_DIVISOR, arm.se / COX_DIVISOR, arm.low / COX_DIVISOR, arm.high / COX_DIVISOR
        ),
        df=df,
        clusters=dict(zip(dim_names, robust.clusters)),
        se_arm_by_clustering=se_by,
        converged=fit.converged,
        notes=tuple(notes),
    )


@dataclass(frozen=True)
class PairedResult:
    windows: tuple[int, ...]
    alpha: float
    n_students: int  # students with outcomes in both arms
    n_students_one_arm: int  # students left out: outcomes in one arm only
    mean_treatment: float  # mean over students of their treatment-concept rate
    mean_control: float
    difference: Estimate  # mean paired difference; bootstrap SE and percentile CI
    d_av: Estimate  # difference / mean of the two per-student SDs; bootstrap CI
    d_z: float  # difference / SD of the differences
    t_p_value: float  # paired t-test (cross-check)
    n_boot: int
    seed: int


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    """Linear-interpolation quantile (type 7) of already-sorted values."""
    if not sorted_values:
        return math.nan
    pos = q * (len(sorted_values) - 1)
    lo = math.floor(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (pos - lo) * (sorted_values[hi] - sorted_values[lo])


def _paired_stats(pairs: Sequence[tuple[float, float]]) -> tuple[float, float]:
    diff = statistics.fmean(t - c for t, c in pairs)
    sd_t = statistics.stdev(t for t, _ in pairs)
    sd_c = statistics.stdev(c for _, c in pairs)
    denom = (sd_t + sd_c) / 2.0
    return diff, (diff / denom if denom > 0 else math.nan)


def paired_difference(
    rows: Iterable[TrialRow],
    *,
    windows: Sequence[int] = PRIMARY_WINDOWS,
    n_boot: int = 2000,
    seed: int = DEFAULT_SEED,
    alpha: float = ALPHA,
) -> PairedResult:
    """The secondary analysis (see the module docstring). Deterministic for a
    given `seed`."""
    per_student: dict[str, dict[str, list[bool]]] = {}
    for r in select(rows, windows):
        per_student.setdefault(r.student, {TREATMENT: [], CONTROL: []})[r.arm].append(bool(r.posttest))
    pairs = [
        (sum(arms[TREATMENT]) / len(arms[TREATMENT]), sum(arms[CONTROL]) / len(arms[CONTROL]))
        for arms in per_student.values()
        if arms[TREATMENT] and arms[CONTROL]
    ]
    if len(pairs) < 3:
        raise AnalysisError("the paired analysis needs at least three students with outcomes in both arms")
    n = len(pairs)
    diff, d_av = _paired_stats(pairs)
    sd_diff = statistics.stdev(t - c for t, c in pairs)
    d_z = diff / sd_diff if sd_diff > 0 else math.nan
    t_stat = diff / (sd_diff / math.sqrt(n)) if sd_diff > 0 else math.inf
    rng = random.Random(seed)
    boot_diff: list[float] = []
    boot_dav: list[float] = []
    for _ in range(n_boot):
        sample = [pairs[rng.randrange(n)] for _ in range(n)]
        try:
            b_diff, b_dav = _paired_stats(sample)
        except statistics.StatisticsError:
            continue
        boot_diff.append(b_diff)
        if not math.isnan(b_dav):
            boot_dav.append(b_dav)
    boot_diff.sort()
    boot_dav.sort()
    lo_q, hi_q = alpha / 2.0, 1.0 - alpha / 2.0
    return PairedResult(
        windows=tuple(sorted(set(windows))),
        alpha=alpha,
        n_students=n,
        n_students_one_arm=len(per_student) - n,
        mean_treatment=statistics.fmean(t for t, _ in pairs),
        mean_control=statistics.fmean(c for _, c in pairs),
        difference=Estimate(
            diff,
            statistics.stdev(boot_diff) if len(boot_diff) > 1 else math.nan,
            _quantile(boot_diff, lo_q),
            _quantile(boot_diff, hi_q),
        ),
        d_av=Estimate(
            d_av,
            statistics.stdev(boot_dav) if len(boot_dav) > 1 else math.nan,
            _quantile(boot_dav, lo_q),
            _quantile(boot_dav, hi_q),
        ),
        d_z=d_z,
        t_p_value=t_two_sided_p(t_stat, n - 1),
        n_boot=n_boot,
        seed=seed,
    )


@dataclass(frozen=True)
class RandomizationResult:
    observed_stat: float
    p_value: float  # (1 + #{|stat_perm| >= |observed|}) / (1 + valid permutations)
    n_perm: int
    n_valid: int
    seed: int


def randomization_test(
    rows: Iterable[TrialRow],
    *,
    windows: Sequence[int] = PRIMARY_WINDOWS,
    n_perm: int = 2000,
    seed: int = DEFAULT_SEED,
    **primary_kwargs,
) -> RandomizationResult:
    """Randomization inference for the primary Wald statistic: each (student,
    concept) unit's arm is redrawn by a fair coin — the design's own
    assignment mechanism (a sha256 bit per unit) — and the primary model
    refitted. Exact under the sharp null of no effect for any unit."""
    data = select(rows, windows)
    observed = fit_primary(data, windows=windows, **primary_kwargs).arm.stat
    units = sorted({(r.student, r.concept) for r in data})
    rng = random.Random(seed)
    extreme = valid = 0
    for _ in range(n_perm):
        arm_of = {u: (TREATMENT if rng.random() < 0.5 else CONTROL) for u in units}
        try:
            stat = fit_primary(data, windows=windows, _arm_of=arm_of, **primary_kwargs).arm.stat
        except AnalysisError:
            continue
        valid += 1
        extreme += abs(stat) >= abs(observed) - 1e-12
    return RandomizationResult(
        observed_stat=observed,
        p_value=(1 + extreme) / (1 + valid),
        n_perm=n_perm,
        n_valid=valid,
        seed=seed,
    )


# ── effect-size scales ─────────────────────────────────────────────────────────


def cox_index(log_odds_ratio: float) -> float:
    """WWC's standardized effect for a dichotomous outcome: ln(OR) / 1.65."""
    return log_odds_ratio / COX_DIVISOR


def theta_sd_effect(conditional_log_odds_ratio: float, sd_student: float) -> float:
    """A subject-specific (GLMM) log odds ratio in student-ability SDs: the
    scale of an IRT-scaled test score, so the one Kraft's (2020) 0.1-0.2 SD
    benchmarks speak to."""
    return conditional_log_odds_ratio / sd_student


def latent_total_d(conditional_log_odds_ratio: float, variances: Iterable[float]) -> float:
    """A subject-specific log odds ratio over the total latent SD of one
    response (every random-effect variance plus the logistic pi^2/3; Westfall,
    Kenny & Judd 2014 for crossed designs)."""
    return conditional_log_odds_ratio / math.sqrt(sum(variances) + math.pi**2 / 3.0)


# ── flow and attrition ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ArmFlow:
    due: int  # rows: the window opened for this (student, concept)
    analyzable: int
    by_status: dict[str, int]
    excluded: dict[str, int]
    pretest_available: int

    @property
    def attrition(self) -> float:
        return 1.0 - self.analyzable / self.due if self.due else math.nan


def flow(rows: Iterable[TrialRow], window: int) -> dict[str, ArmFlow]:
    """Per arm, for one window: rows due, analyzable outcomes, the status mix,
    the item exclusions and pretest availability — the CONSORT-style flow
    and the overall/differential attrition the WWC attrition standard reads."""
    out: dict[str, ArmFlow] = {}
    for arm in (TREATMENT, CONTROL):
        mine = [r for r in rows if r.window == window and r.arm == arm]
        out[arm] = ArmFlow(
            due=len(mine),
            analyzable=sum(1 for r in mine if analyzable(r)),
            by_status=dict(Counter(r.status for r in mine)),
            excluded=dict(Counter(r.exclusion for r in mine if r.exclusion)),
            pretest_available=sum(1 for r in mine if r.pretest is not None),
        )
    return out


# ── report ─────────────────────────────────────────────────────────────────────


def _fmt(x: float, digits: int = 3) -> str:
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{digits}f}"


def render_report(
    primary: PrimaryResult,
    paired: PairedResult | None = None,
    *,
    randomization: RandomizationResult | None = None,
    flows: Mapping[int, Mapping[str, ArmFlow]] | None = None,
    glmm=None,
) -> str:
    """A markdown report of the analyses (no ids: counts and estimates only)."""
    lines = ["# Within-student trial: analysis report", ""]
    if flows:
        lines += ["## Flow and attrition", "", "| window | arm | due | analyzable | attrition | pretest available |",
                  "|---|---|---|---|---|---|"]
        for window, arms in sorted(flows.items()):
            for arm, f in arms.items():
                lines.append(
                    f"| {window} | {arm} | {f.due} | {f.analyzable} | {_fmt(f.attrition)} | {f.pretest_available} |"
                )
            t, c = arms.get(TREATMENT), arms.get(CONTROL)
            if t and c and t.due and c.due:
                overall = 1.0 - (t.analyzable + c.analyzable) / (t.due + c.due)
                lines.append(
                    f"| {window} | overall / differential | | | {_fmt(overall)} / "
                    f"{_fmt(abs(t.attrition - c.attrition))} | |"
                )
        lines.append("")
    a = primary.arm
    lines += [
        "## Primary analysis",
        "",
        f"Method: {primary.method}.",
        f"Windows: {list(primary.windows)}; n = {primary.n_obs} outcomes from {primary.n_students} students "
        f"and {primary.n_concepts} concepts; treatment {primary.n_by_arm[TREATMENT]} "
        f"(rate {_fmt(primary.rate_by_arm[TREATMENT])}), control {primary.n_by_arm[CONTROL]} "
        f"(rate {_fmt(primary.rate_by_arm[CONTROL])}).",
        f"Terms: {', '.join(primary.terms)}"
        + (f"; dropped as constant: {', '.join(primary.dropped_terms)}" if primary.dropped_terms else "")
        + ".",
        "",
        "| quantity | estimate | SE | 95% CI | p |",
        "|---|---|---|---|---|",
        f"| log odds ratio (arm) | {_fmt(a.estimate)} | {_fmt(a.se)} | [{_fmt(a.low)}, {_fmt(a.high)}] "
        f"| {_fmt(a.p_value, 4)} |",
        f"| odds ratio | {_fmt(primary.odds_ratio.estimate)} | | [{_fmt(primary.odds_ratio.low)}, "
        f"{_fmt(primary.odds_ratio.high)}] | |",
        f"| risk difference (AME) | {_fmt(primary.risk_difference.estimate)} | "
        f"{_fmt(primary.risk_difference.se)} | [{_fmt(primary.risk_difference.low)}, "
        f"{_fmt(primary.risk_difference.high)}] | |",
        f"| Cox index d (WWC) | {_fmt(primary.cox_d.estimate)} | {_fmt(primary.cox_d.se)} | "
        f"[{_fmt(primary.cox_d.low)}, {_fmt(primary.cox_d.high)}] | |",
        "",
        f"t reference df = {primary.df:.0f}; clusters: "
        + ", ".join(f"{k} {v}" for k, v in primary.clusters.items())
        + "; SE(arm) by clustering: "
        + ", ".join(f"{k} {_fmt(v)}" for k, v in primary.se_arm_by_clustering.items())
        + ".",
    ]
    for note in primary.notes:
        lines.append(f"Note: {note}.")
    lines += ["", "| term | estimate | SE | p |", "|---|---|---|---|"]
    lines += [f"| {c.name} | {_fmt(c.estimate)} | {_fmt(c.se)} | {_fmt(c.p_value, 4)} |" for c in primary.coefficients]
    if randomization is not None:
        lines += [
            "",
            f"Randomization test of the Wald statistic ({randomization.n_valid} valid of "
            f"{randomization.n_perm} re-randomizations, seed {randomization.seed}): "
            f"p = {_fmt(randomization.p_value, 4)}.",
        ]
    if paired is not None:
        d = paired.difference
        lines += [
            "",
            "## Secondary: per-student paired difference",
            "",
            f"{paired.n_students} students with outcomes in both arms ({paired.n_students_one_arm} with one arm "
            f"left out). Mean treatment rate {_fmt(paired.mean_treatment)}, control {_fmt(paired.mean_control)}.",
            "",
            "| quantity | estimate | bootstrap SE | 95% CI (student-cluster bootstrap) |",
            "|---|---|---|---|",
            f"| paired difference (probability) | {_fmt(d.estimate)} | {_fmt(d.se)} | [{_fmt(d.low)}, {_fmt(d.high)}] |",
            f"| d_av (SD units) | {_fmt(paired.d_av.estimate)} | {_fmt(paired.d_av.se)} | "
            f"[{_fmt(paired.d_av.low)}, {_fmt(paired.d_av.high)}] |",
            "",
            f"d_z = {_fmt(paired.d_z)}; paired t-test p = {_fmt(paired.t_p_value, 4)}; "
            f"{paired.n_boot} bootstrap resamples, seed {paired.seed}.",
        ]
    if glmm is not None:
        lines += ["", "## Optional: crossed random-intercept GLMM", "", glmm.render()]
    return "\n".join(lines) + "\n"
