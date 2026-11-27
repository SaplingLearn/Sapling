"""The analysis side of Sapling's planned within-student learning trial
(docs/research/learning-loop/2026-11-07-direction-audit.md rec. 6; the
preregistration draft is docs/research/learning-loop/2026-11-08-within-student-
trial-preregistration.md).

Outside the request path, in both directions: no application module imports
this package (pinned by tests/test_learning_trial_import_guard.py), and this
package imports no application module. Stdlib only, so it runs in the app venv;
the one optional path, `learning_trial.glmm`, needs the separate
requirements-analysis.txt and says so when it is missing.

Modules:
    table       the de-identified long table: schema, CSV read/write
    analysis    primary: logistic GEE with two-way (student x concept)
                cluster-robust covariance; secondary: per-student paired
                difference with a student-cluster bootstrap; a randomization
                test; effect-size scales; the markdown report
    simulate    synthetic trials under the design, the power simulation
    deidentify  per-export salted pseudonyms (used by
                scripts/export_learning_trial.py)
    glmm        optional crossed random-intercept GLMM (statsmodels)

CLI (from backend/):
    python -m learning_trial power [--fast]        # the power simulation -> markdown
    python -m learning_trial analyze TABLE.csv     # the analyses -> markdown
"""
