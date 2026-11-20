"""Synthetic within-student trials and the power simulation of the primary
analysis (`learning_trial.analysis.fit_primary`).

Data-generating model, per student s in course k and concept c of that course:

    pretest   ~ Bernoulli(expit(mu_pre  + a_k + u_s + v_c + w_sc))            (missing w.p. pretest_missing)
    posttest  ~ Bernoulli(expit(mu_post + a_k + u_s + v_c + i_cj + w_sc + e_sc
                                + T_sc * (delta + t_s + t_c)))               (missing: attrition)

    a_k ~ N(0, sd_course)   u_s ~ N(0, sd_student)   v_c ~ N(0, sd_concept)
    w_sc ~ N(0, sd_prior)   student x concept prior knowledge, shared by both tests
    e_sc ~ N(0, sd_post)    student x concept variation after the pretest
    t_s ~ N(0, sd_effect_student), t_c ~ N(0, sd_effect_concept): the effect
                            varies by student and by concept (random slopes)
    i_cj ~ N(0, sd_item)    post-test item j of concept c, shared by the concept's
                            students; only when items_per_posttest > 1 (with one
                            item, its difficulty is the concept's)

T_sc is the arm, assigned exactly as learning/arms.py::variant_for assigns it:
the parity of the first byte of sha256(f"{label}:{user_id}:{node_id}") for a
per-student node id, so the count of treated concepts per student is binomial
and each concept is treated for about half of its students (counterbalancing).
mu_pre and mu_post are set so the marginal pretest rate and the CONTROL-arm
post-test rate hit their targets.

The effect is specified in student-ability SDs: delta = effect_sd * sd_student.
That is the scale of an IRT-scaled achievement test — the scale of Kraft's
(2020) 0.1-0.2 SD benchmarks for realistic education effects. The report also
translates each effect to the probability scale, the WWC Cox index and the
latent-total d, which put the same effect at well under half the size.

Attrition removes post-tests completely at random: `dropout_share` of it is
whole-student dropout (every post-test of the student), the rest independent
per post-test (a skipped window, an expired pose).
"""

from __future__ import annotations

import dataclasses
import hashlib
import math
import os
import random
from collections import defaultdict
from collections.abc import Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from functools import lru_cache

from learning_trial._stats import expit, norm_ppf
from learning_trial.analysis import ALPHA, COX_DIVISOR, AnalysisError, fit_primary
from learning_trial.table import CONTROL, TREATMENT, TrialRow

#: The simulation calls variant "B" the treatment. The mapping is arbitrary (the
#: hash bit is fair); the exporter takes it as an explicit argument.
TREATMENT_VARIANT = "B"
DEFAULT_SEED = 20261108


def variant_for(user_id: str, node_id: str, arm: str | None) -> str:
    """learning/arms.py::variant_for, restated so this package imports no app
    code; tests/test_learning_trial_simulate.py pins the two equal."""
    if not arm:
        return "A"
    digest = hashlib.sha256(f"{arm}:{user_id}:{node_id}".encode("utf-8")).digest()
    return "A" if digest[0] & 1 == 0 else "B"


@dataclass(frozen=True)
class Design:
    n_students: int = 150
    concepts_per_student: int = 20
    n_courses: int = 3
    concepts_per_course: int = 40
    sd_student: float = 1.0
    sd_concept: float = 0.8
    sd_course: float = 0.3
    sd_prior: float = 0.8
    sd_post: float = 0.8
    sd_effect_student: float = 0.2
    sd_effect_concept: float = 0.2
    pretest_rate: float = 0.45
    control_post_rate: float = 0.55
    pretest_missing: float = 0.2
    attrition: float = 0.3
    dropout_share: float = 0.5
    items_per_posttest: int = 1
    sd_item: float = 0.5
    window: int = 7

    def __post_init__(self) -> None:
        if self.n_students < 2 or self.n_courses < 1 or self.items_per_posttest < 1:
            raise ValueError("need at least two students, one course and one post-test item")
        if not 1 <= self.concepts_per_student <= self.concepts_per_course:
            raise ValueError("concepts_per_student must be in [1, concepts_per_course]")
        for name in ("pretest_rate", "control_post_rate"):
            if not 0.0 < getattr(self, name) < 1.0:
                raise ValueError(f"{name} must be in (0, 1)")
        for name in ("pretest_missing", "attrition", "dropout_share"):
            if not 0.0 <= getattr(self, name) < 1.0:
                raise ValueError(f"{name} must be in [0, 1)")

    @property
    def sd_pre_total(self) -> float:
        return math.sqrt(self.sd_course**2 + self.sd_student**2 + self.sd_concept**2 + self.sd_prior**2)

    @property
    def sd_post_total(self) -> float:
        """Latent SD of one control post-test response, the logistic part excluded."""
        item = self.sd_item**2 if self.items_per_posttest > 1 else 0.0
        return math.sqrt(self.sd_pre_total**2 + self.sd_post**2 + item)

    @property
    def student_dropout(self) -> float:
        return self.dropout_share * self.attrition

    @property
    def item_missing(self) -> float:
        return 1.0 - (1.0 - self.attrition) / (1.0 - self.student_dropout)


_Z = [-8.0 + 0.05 * i for i in range(321)]
_PHI = [math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi) for z in _Z]


def marginal_rate(mu: float, sd: float) -> float:
    """E[expit(mu + sd Z)], Z standard normal (trapezoid rule on [-8, 8])."""
    total = sum(expit(mu + sd * z) * w for z, w in zip(_Z, _PHI))
    edge = 0.5 * (expit(mu + sd * _Z[0]) * _PHI[0] + expit(mu + sd * _Z[-1]) * _PHI[-1])
    return (total - edge) * 0.05


@lru_cache(maxsize=64)
def intercept_for(rate: float, sd: float) -> float:
    """The mu with marginal_rate(mu, sd) == rate (bisection; cached — every
    replicate of a cell asks for the same two intercepts)."""
    lo, hi = -30.0, 30.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if marginal_rate(mid, sd) < rate:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


@dataclass(frozen=True)
class EffectScales:
    """One effect, on every scale the report uses."""

    effect_sd: float  # student-ability SDs (the simulation's input)
    log_odds: float  # conditional (subject-specific) log odds ratio
    control_rate: float
    treatment_rate: float  # marginal, including the effect's random slopes
    post_variance: float  # latent variance of a control post-test, logistic part excluded

    @property
    def risk_difference(self) -> float:
        return self.treatment_rate - self.control_rate

    @property
    def cox_d(self) -> float:
        """WWC Cox index of the marginal odds ratio."""
        t, c = self.treatment_rate, self.control_rate
        return math.log((t / (1 - t)) / (c / (1 - c))) / COX_DIVISOR

    @property
    def latent_total_d(self) -> float:
        return self.log_odds / math.sqrt(self.post_variance + math.pi**2 / 3.0)


def effect_scales(design: Design, effect_sd: float) -> EffectScales:
    delta = effect_sd * design.sd_student
    mu = intercept_for(design.control_post_rate, design.sd_post_total)
    sd_treated = math.sqrt(
        design.sd_post_total**2 + design.sd_effect_student**2 + design.sd_effect_concept**2
    )
    return EffectScales(
        effect_sd=effect_sd,
        log_odds=delta,
        control_rate=design.control_post_rate,
        treatment_rate=marginal_rate(mu + delta, sd_treated),
        post_variance=design.sd_post_total**2,
    )


def simulate(design: Design, effect_sd: float, *, seed: int) -> list[TrialRow]:
    """One synthetic long table (the primary window only). Deterministic for a
    given (design, seed); `effect_sd` changes only the treated outcomes'
    probabilities, so a fixed seed gives common random numbers across effects."""
    rng = random.Random(seed)
    gauss, uniform = rng.gauss, rng.random
    label = f"sim-{seed}"
    delta = effect_sd * design.sd_student
    mu_pre = intercept_for(design.pretest_rate, design.sd_pre_total)
    mu_post = intercept_for(design.control_post_rate, design.sd_post_total)
    q_student, q_item = design.student_dropout, design.item_missing
    n_items = design.items_per_posttest
    courses = [gauss(0.0, design.sd_course) for _ in range(design.n_courses)]
    concepts = [
        [
            (
                gauss(0.0, design.sd_concept),
                gauss(0.0, design.sd_effect_concept),
                [gauss(0.0, design.sd_item) for _ in range(n_items)] if n_items > 1 else [0.0],
            )
            for _ in range(design.concepts_per_course)
        ]
        for _ in range(design.n_courses)
    ]
    rows: list[TrialRow] = []
    pool = range(design.concepts_per_course)
    for i in range(design.n_students):
        k = i % design.n_courses
        u = gauss(0.0, design.sd_student)
        t_s = gauss(0.0, design.sd_effect_student)
        dropped = uniform() < q_student
        user_id = f"student-{i}"
        base = courses[k] + u
        for m in rng.sample(pool, design.concepts_per_student):
            v, t_c, items = concepts[k][m]
            treated = variant_for(user_id, f"node-{i}-{m}", label) == TREATMENT_VARIANT
            prior = base + v + gauss(0.0, design.sd_prior)
            pretest = None if uniform() < design.pretest_missing else uniform() < expit(mu_pre + prior)
            eta = mu_post + prior + gauss(0.0, design.sd_post)
            if treated:
                eta += delta + t_s + t_c
            observed = not dropped and uniform() >= q_item
            for j, item in enumerate(items):
                post = uniform() < expit(eta + item)
                rows.append(
                    TrialRow(
                        student=f"s{i}",
                        concept=f"k{k}-{m}",
                        arm=TREATMENT if treated else CONTROL,
                        window=design.window,
                        pretest=pretest,
                        posttest=post if observed else None,
                        status="rung0" if observed else "not_posed",
                        course=f"c{k}",
                        item=f"i{k}-{m}-{j}",
                    )
                )
    return rows


def _rep_seed(seed: int, design: Design, rep: int) -> int:
    """Per-replicate seed: a function of the design (not the effect) and the
    replicate, so cells that differ only in effect share random numbers."""
    key = f"{seed}|{dataclasses.astuple(design)}|{rep}".encode()
    return int.from_bytes(hashlib.sha256(key).digest()[:8], "big")


@dataclass(frozen=True)
class CellResult:
    design: Design
    effect_sd: float
    reps: int
    rejections: int
    failures: int  # replicates the analysis could not fit (counted as no rejection)
    mean_log_or: float  # the primary (marginal) log odds ratio, mean over replicates
    mean_risk_difference: float
    mean_outcomes: float  # analyzable post-tests per replicate

    @property
    def n_students(self) -> int:
        return self.design.n_students

    @property
    def attrition(self) -> float:
        return self.design.attrition

    @property
    def power(self) -> float:
        return self.rejections / self.reps

    @property
    def mc_se(self) -> float:
        p = self.power
        return math.sqrt(p * (1.0 - p) / self.reps)


def run_cell(
    design: Design, effect_sd: float, *, reps: int, seed: int = DEFAULT_SEED, alpha: float = ALPHA
) -> CellResult:
    """`reps` synthetic trials under `design` and `effect_sd`, each analyzed by
    the primary analysis; a rejection is p < alpha (two-sided) from a fit
    that converged."""
    rejections = failures = 0
    log_ors: list[float] = []
    rds: list[float] = []
    outcomes = 0
    for rep in range(reps):
        rows = simulate(design, effect_sd, seed=_rep_seed(seed, design, rep))
        try:
            result = fit_primary(rows, windows=(design.window,), alpha=alpha)
        except AnalysisError:
            failures += 1
            continue
        outcomes += result.n_obs
        log_ors.append(result.arm.estimate)
        rds.append(result.risk_difference.estimate)
        if result.arm.p_value < alpha and result.converged:
            rejections += 1
    return CellResult(
        design=design,
        effect_sd=effect_sd,
        reps=reps,
        rejections=rejections,
        failures=failures,
        mean_log_or=sum(log_ors) / len(log_ors) if log_ors else math.nan,
        mean_risk_difference=sum(rds) / len(rds) if rds else math.nan,
        mean_outcomes=outcomes / max(1, reps - failures),
    )


def _run_task(task: tuple[Design, float, int, int, float]) -> CellResult:
    design, effect_sd, reps, seed, alpha = task
    return run_cell(design, effect_sd, reps=reps, seed=seed, alpha=alpha)


def run_cells(
    tasks: Sequence[tuple[Design, float]],
    *,
    reps: int,
    seed: int = DEFAULT_SEED,
    alpha: float = ALPHA,
    workers: int | None = None,
) -> list[CellResult]:
    """Run each (design, effect) cell; results come back in task order whatever
    the worker scheduling (every replicate's seed is fixed by its cell)."""
    jobs = [(d, e, reps, seed, alpha) for d, e in tasks]
    workers = workers if workers is not None else (os.cpu_count() or 1)
    if workers <= 1 or len(jobs) <= 1:
        return [_run_task(j) for j in jobs]
    # the largest cells first keeps the pool busy; the dict restores task order
    order = sorted(
        range(len(jobs)),
        key=lambda i: -jobs[i][0].n_students * jobs[i][0].concepts_per_student * jobs[i][0].items_per_posttest,
    )
    with ProcessPoolExecutor(max_workers=workers) as pool:
        done = dict(zip(order, pool.map(_run_task, [jobs[i] for i in order], chunksize=1)))
    return [done[i] for i in range(len(jobs))]


def grid(
    base: Design,
    *,
    students: Iterable[int],
    effects: Iterable[float],
    attritions: Iterable[float],
) -> list[tuple[Design, float]]:
    effects = list(effects)
    students = list(students)
    return [
        (dataclasses.replace(base, n_students=n, attrition=a), e)
        for a in attritions
        for n in students
        for e in effects
    ]


def scenario_of(design: Design, base: Design) -> str:
    """How `design` differs from `base`, sample size and attrition aside:
    "name=value, ..." or "base"."""
    diffs = [
        f"{f.name}={getattr(design, f.name)}"
        for f in dataclasses.fields(Design)
        if f.name not in ("n_students", "attrition") and getattr(design, f.name) != getattr(base, f.name)
    ]
    return ", ".join(diffs) or "base"


@dataclass(frozen=True)
class SampleSize:
    design: Design  # the scenario (n_students: the bracketing cell's, or the largest simulated)
    effect_sd: float
    n_students: float | None  # None: no simulated n reached the target
    largest: int  # the largest simulated n
    smallest: int  # the smallest simulated n

    @property
    def attrition(self) -> float:
        return self.design.attrition

    def label(self) -> str:
        if self.n_students is None:
            return f"> {self.largest}"
        if self.n_students <= self.smallest:
            return f"≤ {self.smallest}"
        return f"~{int(math.ceil(self.n_students / 10.0) * 10)}"


def scenario_key(design: Design, effect_sd: float) -> tuple[Design, float]:
    """The (design apart from n, effect) group a cell belongs to."""
    return dataclasses.replace(design, n_students=2), effect_sd


def unreached(cells: Iterable[CellResult], *, target: float = 0.8) -> set[tuple[Design, float]]:
    """The groups (`scenario_key`) with an effect > 0 none of whose simulated
    sample sizes reached `target` power: the ones only a larger n can settle.
    Simulating larger n for any other group would not change
    `students_for_power`, which reads the first crossing."""
    best: dict[tuple[Design, float], float] = {}
    for c in cells:
        if c.effect_sd > 0:
            key = scenario_key(c.design, c.effect_sd)
            best[key] = max(best.get(key, 0.0), c.power)
    return {key for key, power in best.items() if power < target}


def _probit(p: float) -> float:
    return norm_ppf(min(max(p, 1e-4), 1.0 - 1e-4))


def students_for_power(cells: Iterable[CellResult], *, target: float = 0.8) -> list[SampleSize]:
    """Per scenario (the design apart from n) and effect: the number of students
    for `target` power, interpolated between the two simulated sample sizes
    that bracket it, with probit(power) linear in sqrt(n) between them (the
    Wald power curve's shape). Never extrapolated: when no simulated n reaches
    the target the answer is "more than the largest n simulated". (A fit
    through the origin over small n overstates power at large n: concept-level
    effect heterogeneity over a fixed concept pool puts a floor under the SE.)"""
    groups: dict[tuple[Design, float], list[CellResult]] = defaultdict(list)
    for c in cells:
        if c.effect_sd > 0:
            groups[scenario_key(c.design, c.effect_sd)].append(c)
    out = []
    for (_, effect), members in groups.items():
        members.sort(key=lambda c: c.n_students)
        largest, smallest = members[-1].n_students, members[0].n_students
        hit = next((i for i, c in enumerate(members) if c.power >= target), None)
        if hit is None:
            out.append(SampleSize(members[-1].design, effect, None, largest, smallest))
            continue
        if hit == 0:
            out.append(SampleSize(members[0].design, effect, float(smallest), largest, smallest))
            continue
        lo, hi = members[hit - 1], members[hit]
        x0, x1 = math.sqrt(lo.n_students), math.sqrt(hi.n_students)
        y0, y1 = _probit(lo.power), _probit(hi.power)
        x = x1 if y1 == y0 else x0 + (_probit(target) - y0) * (x1 - x0) / (y1 - y0)
        out.append(SampleSize(hi.design, effect, x * x, largest, smallest))
    return out


@dataclass(frozen=True)
class DetectableEffect:
    design: Design  # the scenario at this sample size
    effect_sd: float | None  # the effect (ability SDs) with `target` power; None: not estimable
    extrapolated: bool  # beyond the largest simulated effect


def detectable_effects(
    cells: Iterable[CellResult], *, target: float = 0.8, alpha: float = ALPHA
) -> list[DetectableEffect]:
    """Per scenario and sample size: the minimum detectable effect, from the
    same power curve read the other way — probit(power) + z_{1-alpha/2} linear in
    the effect through the origin, fitted over the simulated effects > 0 whose
    power lies in (0.02, 0.995)."""
    groups: dict[Design, list[CellResult]] = defaultdict(list)
    for c in cells:
        if c.effect_sd > 0:
            groups[c.design].append(c)
    z_alpha = norm_ppf(1.0 - alpha / 2.0)
    out = []
    for design, members in groups.items():
        usable = [c for c in members if 0.02 < c.power < 0.995]
        num = sum((norm_ppf(c.power) + z_alpha) * c.effect_sd for c in usable)
        den = sum(c.effect_sd**2 for c in usable)
        if not usable or num <= 0:
            out.append(DetectableEffect(design, None, False))
            continue
        effect = (norm_ppf(target) + z_alpha) / (num / den)
        out.append(DetectableEffect(design, effect, effect > max(c.effect_sd for c in members)))
    return out


def _pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def _n(size: SampleSize | None) -> str:
    return "n/a" if size is None else size.label()


def render_markdown(
    cells: Sequence[CellResult],
    base: Design,
    *,
    seed: int,
    alpha: float = ALPHA,
    sensitivity: Sequence[CellResult] = (),
    checks: Sequence[CellResult] = (),
    mde_students: int = 200,
    title: str = "Power of the primary analysis",
) -> str:
    """The power report: assumptions, effect scales, students needed for 80%
    power, the minimum detectable effect by n, power by n per attrition level,
    sensitivity scenarios, and checks of the extrapolated effects."""
    effects = sorted({c.effect_sd for c in cells})
    attritions = sorted({c.attrition for c in cells})
    students = sorted({c.n_students for c in cells})
    reps_by_n: dict[int, set[int]] = defaultdict(set)
    for c in cells:
        reps_by_n[c.n_students].add(c.reps)
    reps_note = "; ".join(
        f"{'/'.join(str(r) for r in sorted(reps))} per cell at n = {', '.join(str(n) for n in ns)}"
        for reps, ns in _group_by_reps(reps_by_n)
    )
    sizes = {
        (s.effect_sd, s.attrition): s for s in students_for_power(cells) if scenario_of(s.design, base) == "base"
    }
    lines = [
        f"## {title}",
        "",
        f"Two-sided α = {alpha}; seed {seed}; synthetic trials: {reps_note}. Each trial is analyzed by "
        "`learning_trial.analysis.fit_primary` (logistic GEE, two-way student x concept cluster-robust "
        "covariance, t on min(clusters) - 1 df). The Monte Carlo SE of a power p over r trials is "
        "sqrt(p(1 - p) / r): ±0.013 at 0.8 and ±0.007 at 0.05 for r = 1000; ±0.020 at 0.8 for r = 400.",
        "",
        "### Assumptions",
        "",
        "| parameter | value |",
        "|---|---|",
    ]
    for f in dataclasses.fields(base):
        if f.name not in ("n_students", "attrition"):
            lines.append(f"| {f.name} | {getattr(base, f.name)} |")
    lines += [
        "",
        "### Effect scales",
        "",
        "Effects are specified in student-ability SDs (d = δ / sd_student, δ the subject-specific log odds "
        "ratio). The other columns give the same effect on the probability scale (marginal, control rate "
        f"{base.control_post_rate}), as WWC's Cox index of the marginal odds ratio, and as a latent-total d "
        "(δ over the SD of one response).",
        "",
        "| d (ability SD) | δ (log odds) | treatment rate | risk difference | Cox d (WWC) | latent-total d |",
        "|---|---|---|---|---|---|",
    ]
    for e in effects:
        s = effect_scales(base, e)
        lines.append(
            f"| {e:.2f} | {s.log_odds:.3f} | {s.treatment_rate:.3f} | {s.risk_difference:+.3f} | "
            f"{s.cox_d:.3f} | {s.latent_total_d:.3f} |"
        )
    lines += [
        "",
        f"### Students needed for 80% power ({base.concepts_per_student} concepts per student)",
        "",
        "Interpolated between the two simulated sample sizes that bracket 80% (probit of power linear in "
        "sqrt(n) between them); never extrapolated: \"> n\" means no simulated sample size reached 80%.",
        "",
        "| d | " + " | ".join(f"attrition {_pct(a)}" for a in attritions) + " |",
        "|---|" + "---|" * len(attritions),
    ]
    for e in effects:
        if e > 0:
            lines.append(f"| {e:.2f} | " + " | ".join(_n(sizes.get((e, a))) for a in attritions) + " |")
    mdes = {
        (m.design.n_students, m.design.attrition): m
        for m in detectable_effects(cells, alpha=alpha)
        if scenario_of(m.design, base) == "base"
    }
    mde_ns = sorted({n for n, _ in mdes if sum(1 for c in cells if c.n_students == n and c.effect_sd > 0) > 1})
    if mde_ns:
        top = max(effects)
        lines += [
            "",
            f"### Minimum detectable effect with 80% power ({base.concepts_per_student} concepts per student)",
            "",
            "In student-ability SDs, from the simulated effects at each sample size (probit of power linear in "
            f"the effect); * = beyond the largest simulated effect ({top:.2f}), so extrapolated (checked by "
            "simulation below). The bracket is the same effect as a risk difference at the control rate.",
            "",
            "| students | " + " | ".join(f"attrition {_pct(a)}" for a in attritions) + " |",
            "|---|" + "---|" * len(attritions),
        ]
        for n in mde_ns:
            row = []
            for a in attritions:
                m = mdes.get((n, a))
                if m is None or m.effect_sd is None:
                    row.append("n/a")
                    continue
                rd = effect_scales(base, m.effect_sd).risk_difference
                row.append(f"{m.effect_sd:.2f}{'*' if m.extrapolated else ''} ({100 * rd:+.1f} pp)")
            lines.append(f"| {n} | " + " | ".join(row) + " |")
    by_cell = {(c.n_students, c.effect_sd, c.attrition): c for c in cells}
    for a in attritions:
        lines += [
            "",
            f"### Power by number of students, attrition {_pct(a)}",
            "",
            "| students | "
            + " | ".join("d = 0 (false-positive rate)" if e == 0 else f"d = {e:.2f}" for e in effects)
            + " | analyzable post-tests |",
            "|---|" + "---|" * (len(effects) + 1),
        ]
        for n in students:
            row = [by_cell.get((n, e, a)) for e in effects]
            if all(c is None for c in row):
                continue
            outcomes = next((c.mean_outcomes for c in row if c is not None), math.nan)
            lines.append(
                f"| {n} | " + " | ".join("–" if c is None else f"{c.power:.3f}" for c in row) + f" | {outcomes:.0f} |"
            )
        failures = sum(c.failures for c in cells if c.attrition == a)
        if failures:
            lines += ["", f"{failures} replicates could not be fitted; they count as non-rejections."]
    if sensitivity:
        sens_effects = sorted({c.effect_sd for c in sensitivity if c.effect_sd > 0})
        sens_sizes: dict[str, dict[float, SampleSize]] = defaultdict(dict)
        for s in students_for_power(sensitivity):
            sens_sizes[scenario_of(s.design, base)][s.effect_sd] = s
        sens_mde = {
            scenario_of(m.design, base): m
            for m in detectable_effects(sensitivity, alpha=alpha)
            if m.design.n_students == mde_students
        }
        nulls: dict[str, list[CellResult]] = defaultdict(list)
        for c in sensitivity:
            if c.effect_sd == 0:
                nulls[scenario_of(c.design, base)].append(c)
        sens_reps = sorted({c.reps for c in sensitivity})
        lines += [
            "",
            f"### Sensitivity, attrition {_pct(sensitivity[0].attrition)}",
            "",
            "One assumption changed at a time (the last row changes two); "
            + "/".join(str(r) for r in sens_reps)
            + " synthetic trials per cell. Students for 80% power, the minimum detectable effect at "
            f"n = {mde_students} (ability SDs), and the false-positive rate pooled over the scenario's "
            "d = 0 cells.",
            "",
            "| scenario (vs the assumptions above) | "
            + " | ".join(f"n for 80% at d = {e:.2f}" for e in sens_effects)
            + f" | MDE at n = {mde_students} | false-positive rate |",
            "|---|" + "---|" * (len(sens_effects) + 2),
        ]
        for scenario, row in sens_sizes.items():
            null = nulls.get(scenario, [])
            fpr = sum(c.rejections for c in null) / sum(c.reps for c in null) if null else math.nan
            mde = sens_mde.get(scenario)
            mde_txt = "n/a" if mde is None or mde.effect_sd is None else f"{mde.effect_sd:.2f}"
            lines.append(
                f"| {scenario} | " + " | ".join(_n(row.get(e)) for e in sens_effects) + f" | {mde_txt} | {fpr:.3f} |"
            )
    if checks:
        lines += [
            "",
            "### Check: simulated power at the extrapolated minimum detectable effects",
            "",
            f"{checks[0].reps} synthetic trials per cell, simulated directly at the extrapolated effect; "
            "each should come out near 0.80.",
            "",
            "| d | attrition | students | power | Monte Carlo SE |",
            "|---|---|---|---|---|",
        ]
        lines += [
            f"| {c.effect_sd:.2f} | {_pct(c.attrition)} | {c.n_students} | {c.power:.3f} | {c.mc_se:.3f} |"
            for c in checks
        ]
    return "\n".join(lines) + "\n"


def _group_by_reps(reps_by_n: dict[int, set[int]]) -> list[tuple[frozenset[int], list[int]]]:
    """Sample sizes grouped by the replicate counts their cells used, in n order."""
    groups: dict[frozenset[int], list[int]] = {}
    for n in sorted(reps_by_n):
        groups.setdefault(frozenset(reps_by_n[n]), []).append(n)
    return list(groups.items())
