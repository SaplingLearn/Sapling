"""learning_trial: the within-student trial's analysis code (direction audit
rec. 6; docs/research/learning-loop/2026-11-08-within-student-trial-
preregistration.md). Pure Python, no DB, no model: the numerical kernels
against known values and hand-rolled definitions, the primary analysis
recovering a planted effect, and its false-positive rate under the null."""

from __future__ import annotations

import io
import math
import random
import sys

import pytest

from learning_trial import analysis, simulate
from learning_trial._stats import (
    SingularMatrixError,
    betainc,
    expit,
    logit,
    mat_inv,
    mat_mul,
    psd_part,
    sym_eigen,
    t_ppf,
    t_two_sided_p,
)
from learning_trial.logistic import fit_logit, multiway_vcov
from learning_trial.table import CONTROL, TREATMENT, TableError, TrialRow, read_csv, write_csv


def _row(student, concept, arm, post, *, pre=None, window=7, status="rung0", exclusion=""):
    return TrialRow(
        student=student,
        concept=concept,
        arm=arm,
        window=window,
        pretest=pre,
        posttest=post if status == "rung0" else None,
        status=status,
        exclusion=exclusion,
    )


def _planted(n_students=400, concepts=20, *, delta=0.0, base=0.0, pre_slope=0.0, seed=1):
    """Rows from a plain logistic model with no random effects: arm by a fair
    coin per (student, concept), a pretest, and a known treatment log odds."""
    rng = random.Random(seed)
    rows = []
    for s in range(n_students):
        for c in range(concepts):
            arm = TREATMENT if rng.random() < 0.5 else CONTROL
            pre = rng.random() < 0.5
            eta = base + pre_slope * pre + (delta if arm == TREATMENT else 0.0)
            rows.append(_row(f"s{s}", f"c{c}", arm, rng.random() < expit(eta), pre=pre))
    return rows


# ── numerical kernels ──────────────────────────────────────────────────────────


def test_student_t_matches_tabulated_values():
    assert t_ppf(0.975, 10) == pytest.approx(2.228139, abs=1e-5)
    assert t_ppf(0.975, 119) == pytest.approx(1.980100, abs=1e-5)
    assert t_ppf(0.975, math.inf) == pytest.approx(1.959964, abs=1e-6)
    assert t_two_sided_p(2.228139, 10) == pytest.approx(0.05, abs=1e-6)
    assert t_two_sided_p(0.0, 5) == pytest.approx(1.0)
    assert t_ppf(0.025, 10) == pytest.approx(-2.228139, abs=1e-5)
    assert betainc(2.0, 3.0, 0.4) == pytest.approx(0.5248, abs=1e-4)  # I_0.4(2, 3)


def test_eigen_fix_keeps_a_psd_matrix_and_clips_a_negative_direction():
    psd = [[2.0, 0.5], [0.5, 1.0]]
    kept, clipped = psd_part(psd)
    assert not clipped
    assert all(kept[i][j] == pytest.approx(psd[i][j], abs=1e-12) for i in range(2) for j in range(2))
    values, _ = sym_eigen([[1.0, 2.0], [2.0, 1.0]])  # eigenvalues 3 and -1
    assert sorted(values) == pytest.approx([-1.0, 3.0])
    fixed, clipped = psd_part([[1.0, 2.0], [2.0, 1.0]])
    assert clipped and fixed[0][0] == pytest.approx(1.5) and fixed[0][1] == pytest.approx(1.5)


def test_matrix_inverse_round_trips_and_refuses_singular():
    a = [[4.0, 1.0, 0.5], [1.0, 3.0, 0.2], [0.5, 0.2, 2.0]]
    ident = mat_mul(a, mat_inv(a))
    for i in range(3):
        for j in range(3):
            assert ident[i][j] == pytest.approx(1.0 if i == j else 0.0, abs=1e-12)
    with pytest.raises(SingularMatrixError):
        mat_inv([[1.0, 2.0], [2.0, 4.0]])


def test_logistic_fit_is_the_exact_mle_on_a_saturated_design():
    """One binary covariate: the MLE is the two observed log odds."""
    x = [(1.0, 0.0)] * 100 + [(1.0, 1.0)] * 100
    y = [i < 30 for i in range(100)] + [i < 60 for i in range(100)]
    fit = fit_logit(x, y)
    assert fit.converged
    assert fit.beta[0] == pytest.approx(logit(0.3), abs=1e-9)
    assert fit.beta[1] == pytest.approx(logit(0.6) - logit(0.3), abs=1e-9)
    # model-based variance of a saturated logit: 1/(n p (1-p)) per cell
    assert fit.bread_inv[0][0] == pytest.approx(1 / (100 * 0.3 * 0.7), rel=1e-9)


def _reference_two_way(x, y, beta, students, concepts):
    """CGM two-way variance written out longhand (CR1 per term)."""
    n, p = len(x), len(x[0])
    mu = [expit(sum(b * v for b, v in zip(beta, xi))) for xi in x]
    resid = [(1.0 if yi else 0.0) - m for yi, m in zip(y, mu)]
    info = [[sum(m * (1 - m) * xi[a] * xi[b] for xi, m in zip(x, mu)) for b in range(p)] for a in range(p)]
    bread = mat_inv(info)

    def meat(ids):
        sums = {}
        for xi, r, g in zip(x, resid, ids):
            s = sums.setdefault(g, [0.0] * p)
            for j in range(p):
                s[j] += xi[j] * r
        g = len(sums)
        scale = g / (g - 1) * (n - 1) / (n - p)
        return [[scale * sum(s[a] * s[b] for s in sums.values()) for b in range(p)] for a in range(p)]

    ms, mc, mi = meat(students), meat(concepts), meat(list(zip(students, concepts)))
    total = [[ms[a][b] + mc[a][b] - mi[a][b] for b in range(p)] for a in range(p)]
    return mat_mul(mat_mul(bread, total), bread)


def test_two_way_cluster_robust_variance_matches_its_definition():
    rows = simulate.simulate(simulate.Design(n_students=40, concepts_per_student=10), 0.3, seed=5)
    data = [r for r in rows if r.posttest is not None]
    x = [(1.0, 1.0 if r.arm == TREATMENT else 0.0, 1.0 if r.pretest else 0.0) for r in data]
    y = [bool(r.posttest) for r in data]
    fit = fit_logit(x, y)
    students = [r.student for r in data]
    concepts = [r.concept for r in data]
    robust = multiway_vcov(fit, x, y, [students, concepts])
    reference = _reference_two_way(x, y, fit.beta, students, concepts)
    for a in range(3):
        for b in range(3):
            assert robust.vcov[a][b] == pytest.approx(reference[a][b], rel=1e-9, abs=1e-12)
    assert robust.clusters == (len(set(students)), len(set(concepts)))
    assert robust.df == min(robust.clusters) - 1


# ── the primary analysis ───────────────────────────────────────────────────────


def test_primary_recovers_a_planted_log_odds_ratio():
    """No random effects: the marginal and conditional effects coincide, so the
    estimate must land on the planted log odds ratio."""
    delta = 0.4
    result = analysis.fit_primary(_planted(delta=delta, base=-0.2, pre_slope=0.8))
    assert result.converged
    assert abs(result.arm.estimate - delta) < 3 * result.arm.se
    assert result.arm.low < delta < result.arm.high
    assert result.arm.p_value < 1e-6
    pre = next(c for c in result.coefficients if c.name == "pretest")
    assert abs(pre.estimate - 0.8) < 3 * pre.se
    assert result.cox_d.estimate == pytest.approx(result.arm.estimate / 1.65)
    assert result.odds_ratio.estimate == pytest.approx(math.exp(result.arm.estimate))
    assert set(result.se_arm_by_clustering) == {"model", "student", "concept", "two-way"}


def test_primary_recovers_a_planted_effect_under_the_trial_design():
    """The full design (crossed random effects, random slopes, attrition, missing
    pretests): the analysis finds the planted effect, and its average marginal
    effect sits on the design's true risk difference."""
    design = simulate.Design(n_students=600, attrition=0.3)
    effect = 0.6
    rows = simulate.simulate(design, effect, seed=11)
    result = analysis.fit_primary(rows)
    truth = simulate.effect_scales(design, effect)
    assert result.arm.p_value < 1e-4 and result.arm.estimate > 0
    assert abs(result.risk_difference.estimate - truth.risk_difference) < 3 * result.risk_difference.se
    paired = analysis.paired_difference(rows, n_boot=300)
    assert paired.difference.low > 0
    assert abs(paired.difference.estimate - truth.risk_difference) < 3 * paired.difference.se


def test_false_positive_rate_is_near_nominal_under_the_null_fast():
    """Fast mode: 300 synthetic null trials (80 students, 16 concepts each,
    30% attrition, crossed random effects and random slopes). The two-way
    cluster-robust test must reject at close to its nominal 5%."""
    cell = simulate.run_cell(
        simulate.Design(n_students=80, concepts_per_student=16), 0.0, reps=300, seed=20261108
    )
    assert cell.failures == 0
    assert 0.02 <= cell.power <= 0.09, f"false-positive rate {cell.power:.3f}"
    assert abs(cell.mean_log_or) < 0.05


def test_power_rises_with_the_effect_fast():
    design = simulate.Design(n_students=80, concepts_per_student=16)
    null = simulate.run_cell(design, 0.0, reps=40, seed=3)
    large = simulate.run_cell(design, 0.8, reps=40, seed=3)
    assert large.power > 0.6 > null.power


def test_one_window_carries_no_window_term_and_two_windows_do():
    rows = _planted(n_students=60, concepts=8)
    assert not any(t.startswith("window") for t in analysis.fit_primary(rows).terms)
    rng = random.Random(3)  # the 28-day outcome: forgetting flips some answers
    later = [
        _row(r.student, r.concept, r.arm, r.posttest if rng.random() < 0.7 else not r.posttest, pre=r.pretest,
             window=28)
        for r in rows
    ]
    pooled = analysis.fit_primary(rows + later, windows=(7, 28), arm_by_window=True)
    assert "window[28]" in pooled.terms and "arm:window[28]" in pooled.terms
    assert pooled.windows == (7, 28)


def test_only_analyzable_rows_are_modelled():
    rows = _planted(n_students=60, concepts=8)
    noise = [
        _row("s0", "c0", TREATMENT, None, status="expired"),
        _row("s1", "c1", CONTROL, True, exclusion="retired_item"),
        _row("s2", "c2", TREATMENT, None, status="assisted"),
    ]
    assert analysis.fit_primary(rows + noise).n_obs == analysis.fit_primary(rows).n_obs == len(rows)


def test_primary_needs_both_arms():
    rows = [_row(f"s{i}", f"c{i % 3}", TREATMENT, i % 2 == 0) for i in range(30)]
    with pytest.raises(analysis.AnalysisError):
        analysis.fit_primary(rows)


def test_one_way_clusterings_are_available_as_sensitivity():
    rows = _planted(n_students=80, concepts=10, delta=0.3)
    two = analysis.fit_primary(rows)
    by_student = analysis.fit_primary(rows, clustering="student")
    assert by_student.arm.estimate == pytest.approx(two.arm.estimate)
    assert by_student.se_arm_by_clustering["student"] == pytest.approx(two.se_arm_by_clustering["student"])
    assert by_student.df == by_student.clusters["student"] - 1


# ── secondary and robustness ───────────────────────────────────────────────────


def test_paired_difference_is_deterministic_and_counts_students():
    rows = _planted(n_students=60, concepts=10, delta=0.5)
    rows.append(_row("lonely", "c0", TREATMENT, True))  # one arm only: left out, counted
    a = analysis.paired_difference(rows, n_boot=200, seed=4)
    b = analysis.paired_difference(rows, n_boot=200, seed=4)
    assert a == b
    assert a.n_students == 60 and a.n_students_one_arm == 1
    assert a.difference.low <= a.difference.estimate <= a.difference.high
    assert a.d_av.low <= a.d_av.estimate <= a.d_av.high
    assert a.difference.estimate == pytest.approx(a.mean_treatment - a.mean_control)


def test_randomization_test_separates_an_effect_from_the_null():
    strong = analysis.randomization_test(_planted(n_students=40, concepts=10, delta=1.2), n_perm=99, seed=2)
    assert strong.n_valid == 99 and strong.p_value == pytest.approx(0.01)
    null = analysis.randomization_test(_planted(n_students=40, concepts=10, delta=0.0, seed=9), n_perm=99, seed=2)
    assert null.p_value > 0.05


def test_flow_reports_attrition_and_exclusions_per_arm():
    rows = [
        _row("s0", "c0", TREATMENT, True, pre=True),
        _row("s0", "c1", TREATMENT, None, status="expired"),
        _row("s0", "c2", CONTROL, False, exclusion="reported_item"),
        _row("s0", "c3", CONTROL, True),
    ]
    flows = analysis.flow(rows, 7)
    assert flows[TREATMENT].due == 2 and flows[TREATMENT].analyzable == 1
    assert flows[TREATMENT].attrition == pytest.approx(0.5)
    assert flows[CONTROL].excluded == {"reported_item": 1}
    assert flows[TREATMENT].pretest_available == 1


def test_effect_size_conversions():
    assert analysis.cox_index(0.33) == pytest.approx(0.2)
    assert analysis.theta_sd_effect(0.3, 1.5) == pytest.approx(0.2)
    assert analysis.latent_total_d(0.5, [1.0, 0.64]) == pytest.approx(0.5 / math.sqrt(1.64 + math.pi**2 / 3))


def test_report_renders_every_section():
    rows = _planted(n_students=60, concepts=10, delta=0.4)
    text = analysis.render_report(
        analysis.fit_primary(rows),
        analysis.paired_difference(rows, n_boot=100),
        flows={7: analysis.flow(rows, 7)},
    )
    for heading in ("## Flow and attrition", "## Primary analysis", "## Secondary: per-student paired difference"):
        assert heading in text


# ── the table ──────────────────────────────────────────────────────────────────


def test_long_table_round_trips_through_csv():
    rows = [
        TrialRow("s_1", "k_1", TREATMENT, 7, True, False, course="c_1", item="i_1", days_since_evidence=8.31,
                 covariates=(("baseline", 1.5),)),
        TrialRow("s_1", "k_2", CONTROL, 28, None, None, status="expired"),
    ]
    buf = io.StringIO()
    assert write_csv(rows, buf) == 2
    back = read_csv(io.StringIO(buf.getvalue()))
    assert back[0].pretest is True and back[0].posttest is False and back[0].covariate("baseline") == 1.5
    assert back[0].days_since_evidence == pytest.approx(8.3)  # written to one decimal
    assert back[1].status == "expired" and back[1].posttest is None and back[1].pretest is None


def test_long_table_refuses_unknown_columns_and_bad_values():
    header = "student,course,concept,arm,window,pretest,posttest,status,exclusion,item,days_since_evidence"
    with pytest.raises(TableError, match="unknown columns"):
        read_csv(io.StringIO(header + ",name\ns,c,k,treatment,7,1,1,rung0,,,,Ada\n"))
    with pytest.raises(TableError):
        read_csv(io.StringIO(header + "\ns,c,k,treatment,7,1,1,expired,,,\n"))  # outcome on a non-rung0 row
    with pytest.raises(TableError):
        TrialRow("s", "k", "B", 7, None, None)  # arms are treatment/control, never a raw variant


# ── the optional GLMM path ─────────────────────────────────────────────────────


def test_glmm_path_without_statsmodels_says_how_to_install(monkeypatch):
    from learning_trial import glmm

    monkeypatch.setitem(sys.modules, "statsmodels", None)
    monkeypatch.setitem(sys.modules, "statsmodels.genmod", None)
    monkeypatch.setitem(sys.modules, "statsmodels.genmod.bayes_mixed_glm", None)
    with pytest.raises(glmm.MissingAnalysisDependency, match="requirements-analysis.txt"):
        glmm.fit_glmm(_planted(n_students=20, concepts=5))


def test_cli_glmm_without_statsmodels_exits_2(monkeypatch, tmp_path, capsys):
    from learning_trial.__main__ import main

    path = tmp_path / "trial.csv"
    write_csv(_planted(n_students=30, concepts=6, delta=0.5), path)
    monkeypatch.setitem(sys.modules, "statsmodels", None)
    monkeypatch.setitem(sys.modules, "statsmodels.genmod", None)
    monkeypatch.setitem(sys.modules, "statsmodels.genmod.bayes_mixed_glm", None)
    assert main(["analyze", str(path), "--boot", "50", "--glmm"]) == 2
    assert "requirements-analysis.txt" in capsys.readouterr().err


def test_glmm_recovers_a_planted_subject_specific_effect():
    pytest.importorskip("statsmodels")
    from learning_trial.glmm import fit_glmm

    design = simulate.Design(n_students=300, sd_prior=0.0, sd_post=0.0, sd_effect_student=0.0,
                             sd_effect_concept=0.0, sd_course=0.0, attrition=0.2)
    result = fit_glmm(simulate.simulate(design, 0.5, seed=3))
    assert abs(result.arm - 0.5) < 0.15
    assert 0.7 < result.sd_student < 1.3
    assert result.theta_sd == pytest.approx(result.arm / result.sd_student)


# ── the CLI ────────────────────────────────────────────────────────────────────


def test_cli_analyze_writes_the_report(tmp_path):
    from learning_trial.__main__ import main

    table_path, report = tmp_path / "trial.csv", tmp_path / "report.md"
    write_csv(simulate.simulate(simulate.Design(n_students=60), 0.3, seed=2), table_path)
    assert main(["analyze", str(table_path), "--boot", "100", "--randomization", "19", "--out", str(report)]) == 0
    text = report.read_text()
    assert "## Primary analysis" in text and "Randomization test" in text


def test_cli_power_fast_prints_the_markdown_tables(capsys):
    from learning_trial.__main__ import main

    assert main(["power", "--fast", "--workers", "1", "--reps", "10", "--students", "60,90", "--effects", "0,0.4"]) == 0
    out = capsys.readouterr().out
    assert "### Students needed for 80% power" in out
    assert "### Power by number of students, attrition 30%" in out
    assert "| 60 |" in out and "| 90 |" in out
