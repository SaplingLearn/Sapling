"""learning_trial.simulate: synthetic within-student trials and the power
simulation. The arm assignment is the product's own (learning/arms.py), the
generator hits its design targets, and the power summary inverts the power
curve it fits."""

from __future__ import annotations

import dataclasses
import itertools
import random
from collections import Counter, defaultdict

import pytest

from learning import arms
from learning_trial import simulate
from learning_trial._stats import expit, norm_cdf, norm_ppf
from learning_trial.table import TREATMENT


def test_arm_assignment_is_the_products_variant_for():
    labels = ["trial-2027s", "x", "sim-42", ""]
    users = [f"user_{i}" for i in range(15)]
    nodes = [f"node-{i}" for i in range(15)]
    for label, user, node in itertools.product(labels, users, nodes):
        assert simulate.variant_for(user, node, label) == arms.variant_for(user, node, label or None)


def test_simulation_is_deterministic_with_common_random_numbers_across_effects():
    design = simulate.Design(n_students=30)
    a = simulate.simulate(design, 0.2, seed=7)
    assert a == simulate.simulate(design, 0.2, seed=7)
    b = simulate.simulate(design, 0.0, seed=7)
    # the effect moves only treated post-test probabilities: arms, pretests and
    # missingness are identical, so cells differing only in effect are paired
    assert [(r.student, r.concept, r.arm, r.pretest, r.status) for r in a] == [
        (r.student, r.concept, r.arm, r.pretest, r.status) for r in b
    ]
    assert simulate.simulate(design, 0.2, seed=8) != a


@pytest.mark.parametrize("rate,sd", [(0.45, 1.54), (0.55, 1.73), (0.7, 2.5), (0.2, 0.0)])
def test_intercepts_hit_their_marginal_rates(rate, sd):
    mu = simulate.intercept_for(rate, sd)
    assert simulate.marginal_rate(mu, sd) == pytest.approx(rate, abs=1e-9)
    rng = random.Random(1)
    draws = [expit(mu + sd * rng.gauss(0.0, 1.0)) for _ in range(100_000)]
    assert sum(draws) / len(draws) == pytest.approx(rate, abs=0.005), "the quadrature is the expectation"


def test_generator_hits_its_rates_and_attrition():
    """One course and a large concept pool, so the realized random effects
    barely move the sample rates off their expectations."""
    design = simulate.Design(
        n_students=1500, n_courses=1, concepts_per_course=600, sd_course=0.0, attrition=0.4, pretest_missing=0.25
    )
    rows = simulate.simulate(design, 0.0, seed=3)
    observed = [r for r in rows if r.posttest is not None]
    assert len(observed) / len(rows) == pytest.approx(0.6, abs=0.02)
    assert sum(r.posttest for r in observed) / len(observed) == pytest.approx(design.control_post_rate, abs=0.03)
    pretests = [r.pretest for r in rows if r.pretest is not None]
    assert len(pretests) / len(rows) == pytest.approx(0.75, abs=0.01)
    assert sum(pretests) / len(pretests) == pytest.approx(design.pretest_rate, abs=0.03)
    by_student = defaultdict(list)
    for r in rows:
        by_student[r.student].append(r.posttest is None)
    dropped = sum(all(v) for v in by_student.values()) / len(by_student)
    assert dropped == pytest.approx(design.student_dropout, abs=0.04)


def test_arms_are_balanced_and_counterbalanced_across_students():
    rows = simulate.simulate(simulate.Design(n_students=300), 0.0, seed=4)
    assert sum(r.arm == TREATMENT for r in rows) / len(rows) == pytest.approx(0.5, abs=0.02)
    per_concept = defaultdict(Counter)
    for r in rows:
        per_concept[r.concept][r.arm] += 1
    assert all(len(arms_seen) == 2 for arms_seen in per_concept.values()), "every concept is in both arms"


def test_multi_item_posttests_share_the_unit_and_its_arm():
    rows = simulate.simulate(simulate.Design(n_students=20, items_per_posttest=3), 0.0, seed=1)
    units = defaultdict(list)
    for r in rows:
        units[(r.student, r.concept)].append(r)
    assert all(len(v) == 3 and len({r.arm for r in v}) == 1 and len({r.item for r in v}) == 3 for v in units.values())


def test_effect_scales_translate_ability_sds():
    design = simulate.Design()
    zero = simulate.effect_scales(design, 0.0)
    two = simulate.effect_scales(design, 0.2)
    assert two.log_odds == pytest.approx(0.2 * design.sd_student)
    assert abs(zero.risk_difference) < 0.002
    assert 0.0 < two.risk_difference < 0.05
    assert two.cox_d < 0.5 * two.effect_sd, "one response's spread makes the WWC scale far smaller"


def _cells_from_curve(slope, students, effect=0.2, reps=1000):
    """CellResults whose power lies exactly on Phi(slope sqrt(n) - z)."""
    z = norm_ppf(0.975)
    base = simulate.Design()
    return [
        simulate.CellResult(
            design=dataclasses.replace(base, n_students=n),
            effect_sd=effect,
            reps=reps,
            rejections=round(reps * norm_cdf(slope * n**0.5 - z)),
            failures=0,
            mean_log_or=0.0,
            mean_risk_difference=0.0,
            mean_outcomes=0.0,
        )
        for n in students
    ]


def test_students_for_power_interpolates_and_never_extrapolates():
    slope = 0.12
    expected = ((norm_ppf(0.8) + norm_ppf(0.975)) / slope) ** 2  # ~545
    (inside,) = simulate.students_for_power(_cells_from_curve(slope, (200, 400, 600, 800)))
    assert inside.n_students == pytest.approx(expected, rel=0.02)
    assert inside.label() == "~550"
    (short,) = simulate.students_for_power(_cells_from_curve(slope, (60, 120, 200, 300)))
    assert short.n_students is None and short.label() == "> 300"
    (already,) = simulate.students_for_power(_cells_from_curve(slope, (600, 800)))
    assert already.label() == "≤ 600"


def test_only_groups_short_of_the_target_need_larger_trials():
    reached = _cells_from_curve(0.12, (400, 600, 800), effect=0.2)  # 80% near n = 545
    short = _cells_from_curve(0.12, (60, 120, 200), effect=0.15)
    null = [dataclasses.replace(c, effect_sd=0.0) for c in short]
    assert simulate.unreached(reached + short + null) == {simulate.scenario_key(short[0].design, 0.15)}


def test_detectable_effect_inverts_the_curve_in_the_effect():
    z = norm_ppf(0.975)
    slope = 9.0  # probit(power) + z = slope * d at this n
    design = dataclasses.replace(simulate.Design(), n_students=200)
    cells = [
        simulate.CellResult(design, d, 1000, round(1000 * norm_cdf(slope * d - z)), 0, 0.0, 0.0, 0.0)
        for d in (0.0, 0.1, 0.15, 0.2)
    ]
    (mde,) = simulate.detectable_effects(cells)
    assert mde.effect_sd == pytest.approx((norm_ppf(0.8) + z) / slope, rel=0.02)  # ~0.31
    assert mde.extrapolated


def test_power_report_renders_its_tables():
    cells = _cells_from_curve(0.12, (60, 120, 200, 300, 400, 600, 800))
    null = [dataclasses.replace(c, effect_sd=0.0, rejections=50) for c in cells[:4]]
    text = simulate.render_markdown(null + cells, simulate.Design(), seed=1)
    assert "| 0.20 | ~550 |" in text
    assert "| 300 | 0.050 |" in text and "| 400 | – |" in text  # no null cell simulated at 400
    short = simulate.render_markdown(null + cells[:4], simulate.Design(), seed=1)
    assert "| 0.20 | > 300 |" in short


def test_parallel_cells_equal_serial_cells():
    tasks = simulate.grid(simulate.Design(), students=(60,), effects=(0.0, 0.3), attritions=(0.3,))
    serial = simulate.run_cells(tasks, reps=4, seed=5, workers=1)
    parallel = simulate.run_cells(tasks, reps=4, seed=5, workers=2)
    assert serial == parallel


def test_scenario_labels_name_what_changed():
    base = simulate.Design()
    assert simulate.scenario_of(dataclasses.replace(base, n_students=999, attrition=0.5), base) == "base"
    assert simulate.scenario_of(dataclasses.replace(base, items_per_posttest=3), base) == "items_per_posttest=3"
