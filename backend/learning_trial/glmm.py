"""Optional: the trial's specified model itself — a crossed random-intercept
logistic GLMM,

    posttest ~ arm + pretest + pretest_missing [+ window] + (1 | student) + (1 | concept)

fitted by variational Bayes with statsmodels' BinomialBayesMixedGLM (priors:
statsmodels' defaults, N(0, 2^2) on fixed effects and N(0, 1) on each log SD).
The app venv does not carry statsmodels, and this
package must not add it there: install `requirements-analysis.txt` into a
separate analysis environment. Without it, `fit_glmm` raises
`MissingAnalysisDependency` with that instruction and nothing else in the
package is affected (statsmodels is imported only inside `fit_glmm`).

Limits: mean-field variational Bayes understates posterior SDs, and it is not
lme4's Laplace maximum likelihood. Over 40 synthetic trials (200 students,
the default `simulate.Design`, a 0.3 SD effect) the arm's posterior SD
averaged 0.060 against an empirical SD of the estimates of 0.083 (27% too
small), while the primary analysis's cluster-robust SE averaged 0.079 against
0.074; estimate over empirical SD, the power-relevant ratio, was 2.97 for the
GLMM and 2.87 for the primary analysis. With one outcome per (student,
concept), the GLMM's coefficients and SDs shrink together by the unmodelled
student x concept variance, so its ratio arm / sd_student (the ability-SD
effect) is the meaningful output, not either number alone. Treat this path as the
cross-check of the primary analysis and the source of the variance components
(for the ability-SD effect size); the confirmatory GLMM belongs in lme4
(`glmer`, formula in the preregistration draft) run by the independent
analyst.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from learning_trial.analysis import DEFAULT_SEED, PRIMARY_WINDOWS, AnalysisError, latent_total_d, theta_sd_effect
from learning_trial.table import TREATMENT, TrialRow, select

INSTALL_HINT = (
    "install the optional analysis dependencies in a SEPARATE environment: "
    "python -m venv .venv-analysis && .venv-analysis/bin/pip install -r requirements-analysis.txt "
    "(from backend/); never into the app venv"
)


class MissingAnalysisDependency(ImportError):
    """numpy, pandas or statsmodels is not installed."""


def _require():
    try:
        import numpy
        import pandas
        from statsmodels.genmod.bayes_mixed_glm import BinomialBayesMixedGLM
    except ImportError as exc:
        raise MissingAnalysisDependency(
            f"the GLMM path needs numpy, pandas and statsmodels ({exc.name or exc} is missing): {INSTALL_HINT}"
        ) from exc
    return numpy, pandas, BinomialBayesMixedGLM


@dataclass(frozen=True)
class GlmmResult:
    method: str
    formula: str
    n_obs: int
    fixed: dict[str, tuple[float, float]]  # term -> (posterior mean, posterior SD)
    sd_student: float  # exp(posterior mean of the log SD)
    sd_concept: float
    arm: float  # subject-specific log odds ratio
    arm_sd: float
    arm_low: float  # mean -/+ 1.96 SD (normal approximation to the posterior)
    arm_high: float
    theta_sd: float  # arm / sd_student: the ability-SD (Kraft-comparable) scale
    latent_total: float  # arm / sqrt(sd_student^2 + sd_concept^2 + pi^2/3)

    def render(self) -> str:
        lines = [
            f"Method: {self.method}; formula `{self.formula}` with crossed random intercepts "
            f"(1 | student) + (1 | concept); n = {self.n_obs}.",
            "",
            "| term | posterior mean | posterior SD |",
            "|---|---|---|",
        ]
        lines += [f"| {k} | {m:.3f} | {s:.3f} |" for k, (m, s) in self.fixed.items()]
        lines += [
            "",
            f"Random-intercept SDs: student {self.sd_student:.3f}, concept {self.sd_concept:.3f}.",
            f"Arm (subject-specific log odds ratio): {self.arm:.3f} "
            f"[{self.arm_low:.3f}, {self.arm_high:.3f}]; in student-ability SDs {self.theta_sd:.3f}; "
            f"latent-total d {self.latent_total:.3f}.",
        ]
        return "\n".join(lines)


def fit_glmm(
    rows: Iterable[TrialRow],
    *,
    windows: Sequence[int] = PRIMARY_WINDOWS,
    seed: int = DEFAULT_SEED,
) -> GlmmResult:
    """Fit the crossed random-intercept GLMM to the analyzable rows of
    `windows` by variational Bayes (statsmodels' posterior-mode fit does not
    converge reliably with hundreds of crossed random effects, so it is not
    offered)."""
    np, pd, model_cls = _require()
    data = select(rows, windows)
    if not data:
        raise AnalysisError("no analyzable rows")
    frame = pd.DataFrame(
        {
            "y": [int(bool(r.posttest)) for r in data],
            "arm": [1 if r.arm == TREATMENT else 0 for r in data],
            "pretest": [1 if r.pretest else 0 for r in data],
            "pretest_missing": [1 if r.pretest is None else 0 for r in data],
            "window": [r.window for r in data],
            "student": [r.student for r in data],
            "concept": [r.concept for r in data],
        }
    )
    if frame["arm"].nunique() < 2:
        raise AnalysisError("both arms must be present")
    terms = ["arm"] + [t for t in ("pretest", "pretest_missing") if frame[t].nunique() > 1]
    if frame["window"].nunique() > 1:
        terms.append("C(window)")
    formula = "y ~ " + " + ".join(terms)
    model = model_cls.from_formula(formula, {"student": "0 + C(student)", "concept": "0 + C(concept)"}, frame)
    result = model.fit_vb(rng=np.random.default_rng(seed))
    fixed = {
        name: (float(m), float(s)) for name, m, s in zip(model.fep_names, result.fe_mean, result.fe_sd)
    }
    log_sd = dict(zip(model.vcp_names, (float(v) for v in result.vcp_mean)))
    sd_student, sd_concept = math.exp(log_sd["student"]), math.exp(log_sd["concept"])
    arm, arm_sd = fixed["arm"]
    return GlmmResult(
        method="statsmodels BinomialBayesMixedGLM, variational Bayes",
        formula=formula,
        n_obs=len(frame),
        fixed=fixed,
        sd_student=sd_student,
        sd_concept=sd_concept,
        arm=arm,
        arm_sd=arm_sd,
        arm_low=arm - 1.959964 * arm_sd,
        arm_high=arm + 1.959964 * arm_sd,
        theta_sd=theta_sd_effect(arm, sd_student),
        latent_total=latent_total_d(arm, (sd_student**2, sd_concept**2)),
    )
