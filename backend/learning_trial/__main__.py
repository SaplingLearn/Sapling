"""`python -m learning_trial power|analyze` (run from backend/).

    power    the power simulation of the primary analysis -> markdown.
             Full mode (default): 7 sample sizes (60-300) x 4 effects x 4 attrition
             levels at 1000 synthetic trials per cell; larger sample sizes (400-3200)
             for the non-zero effects at 400 per cell, so where 80% power is reached
             is simulated rather than extrapolated; one-change sensitivity
             scenarios; and checks of the extrapolated minimum detectable effects.
             About half an hour on 10 cores. --fast: a small grid with 100 trials
             per cell, seconds, for CI and smoke runs. Deterministic for a given
             --seed whatever --workers is.
    analyze  the preregistered analyses of an exported long table -> markdown.
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import sys
import time

from learning_trial import analysis, simulate
from learning_trial.table import read_csv

FULL = {
    "students": (60, 90, 120, 150, 200, 250, 300),
    "effects": (0.0, 0.1, 0.15, 0.2),
    "attritions": (0.2, 0.3, 0.4, 0.5),
    "reps": 1000,
}
FAST = {"students": (60, 120, 200), "effects": (0.0, 0.2), "attritions": (0.3,), "reps": 100}
#: larger trials, simulated for the non-zero effects only (2/5 of --reps per cell)
EXTENDED_STUDENTS = (400, 600, 800, 1200, 1600, 2400, 3200)
#: one-change scenarios against simulate.Design(), run at SENSITIVITY_ATTRITION:
#: concepts per student (the trial's main lever), the student-ability SD (the
#: effect scale's denominator), an easier post-test, and a three-item post-test
#: per concept (the product poses one item today)
SENSITIVITY = (
    {"concepts_per_student": 10},
    {"concepts_per_student": 30},
    {"concepts_per_student": 40},
    {"sd_student": 0.7},
    {"sd_student": 1.4},
    {"control_post_rate": 0.7},
    {"items_per_posttest": 3},
)
SENSITIVITY_ATTRITION = 0.3
#: the scenarios' effects (the null for calibration) and their larger sample sizes
SENSITIVITY_EFFECTS = (0.0, 0.2)
SENSITIVITY_EXTENDED = (400, 600, 800, 1200, 1600)
#: sample sizes whose extrapolated minimum detectable effect is checked by simulation
CHECK_STUDENTS = (120, 200)


def _floats(raw: str) -> tuple[float, ...]:
    return tuple(float(x) for x in raw.split(",") if x.strip())


def _ints(raw: str) -> tuple[int, ...]:
    return tuple(int(x) for x in raw.split(",") if x.strip())


def _emit(text: str, out: str | None) -> None:
    if out:
        with open(out, "w", encoding="utf-8") as handle:
            handle.write(text)
        print(f"wrote {out}", file=sys.stderr)
    else:
        sys.stdout.write(text)


def power_main(args: argparse.Namespace) -> int:
    cfg = FAST if args.fast else FULL
    students = args.students or cfg["students"]
    effects = args.effects or cfg["effects"]
    attritions = args.attritions or cfg["attritions"]
    reps = args.reps or cfg["reps"]
    workers = args.workers if args.workers is not None else (os.cpu_count() or 1)
    full = not args.fast
    ext_reps = max(1, (reps * 2) // 5)
    sens_reps = max(1, reps // 2)
    base = simulate.Design()
    started = time.perf_counter()
    tasks = simulate.grid(base, students=students, effects=effects, attritions=attritions)
    cells = simulate.run_cells(tasks, reps=reps, seed=args.seed, workers=workers)
    if full and not args.no_extended:
        # large n only for the effects: where 80% power is reached is simulated, not extrapolated
        tasks = simulate.grid(
            base, students=EXTENDED_STUDENTS, effects=[e for e in effects if e > 0], attritions=attritions
        )
        cells += simulate.run_cells(tasks, reps=ext_reps, seed=args.seed, workers=workers)
    sensitivity: list[simulate.CellResult] = []
    if full and not args.no_sensitivity:
        tasks = []
        for overrides in SENSITIVITY:
            design = dataclasses.replace(base, **overrides)
            tasks += simulate.grid(
                design, students=students, effects=SENSITIVITY_EFFECTS, attritions=(SENSITIVITY_ATTRITION,)
            )
        sensitivity = simulate.run_cells(tasks, reps=sens_reps, seed=args.seed, workers=workers)
        tasks = []
        for overrides in SENSITIVITY:
            design = dataclasses.replace(base, **overrides)
            tasks += simulate.grid(
                design,
                students=SENSITIVITY_EXTENDED,
                effects=[e for e in SENSITIVITY_EFFECTS if e > 0],
                attritions=(SENSITIVITY_ATTRITION,),
            )
        sensitivity += simulate.run_cells(tasks, reps=ext_reps, seed=args.seed, workers=workers)
    checks: list[simulate.CellResult] = []
    if full and not args.no_checks:
        # simulate directly at the minimum detectable effects the report extrapolates
        tasks = [
            (m.design, round(m.effect_sd, 2))
            for m in simulate.detectable_effects(cells)
            if m.design.attrition == SENSITIVITY_ATTRITION
            and m.extrapolated
            and m.effect_sd
            and m.design.n_students in CHECK_STUDENTS
        ]
        if tasks:
            checks = simulate.run_cells(tasks, reps=ext_reps, seed=args.seed, workers=workers)
    text = simulate.render_markdown(cells, base, seed=args.seed, sensitivity=sensitivity, checks=checks)
    print(f"power simulation: {time.perf_counter() - started:.0f} s on {workers} worker(s)", file=sys.stderr)
    _emit(text, args.out)
    return 0


def analyze_main(args: argparse.Namespace) -> int:
    rows = read_csv(args.table)
    windows = args.windows or analysis.PRIMARY_WINDOWS
    primary = analysis.fit_primary(
        rows,
        windows=windows,
        clustering=args.clustering,
        course_effects=args.course_effects,
        arm_by_window=args.arm_by_window,
    )
    paired = analysis.paired_difference(rows, windows=windows, n_boot=args.boot, seed=args.seed)
    randomization = None
    if args.randomization:
        randomization = analysis.randomization_test(
            rows,
            windows=windows,
            n_perm=args.randomization,
            seed=args.seed,
            clustering=args.clustering,
            course_effects=args.course_effects,
            arm_by_window=args.arm_by_window,
        )
    glmm = None
    if args.glmm:
        from learning_trial.glmm import MissingAnalysisDependency, fit_glmm

        try:
            glmm = fit_glmm(rows, windows=windows, seed=args.seed)
        except MissingAnalysisDependency as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    flows = {w: analysis.flow(rows, w) for w in sorted({r.window for r in rows})}
    _emit(analysis.render_report(primary, paired, randomization=randomization, flows=flows, glmm=glmm), args.out)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m learning_trial", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    power = sub.add_parser("power", help="power simulation of the primary analysis")
    power.add_argument("--fast", action="store_true", help="small grid, 100 trials per cell (CI)")
    power.add_argument("--reps", type=int, help="synthetic trials per cell")
    power.add_argument("--seed", type=int, default=simulate.DEFAULT_SEED)
    power.add_argument("--workers", type=int, help="processes (default: all cores; 1 = serial)")
    power.add_argument("--students", type=_ints, help="comma-separated sample sizes")
    power.add_argument("--effects", type=_floats, help="comma-separated effects (student-ability SDs)")
    power.add_argument("--attritions", type=_floats, help="comma-separated attrition rates")
    power.add_argument("--no-extended", action="store_true", help="skip the 400-3200 sample sizes")
    power.add_argument("--no-sensitivity", action="store_true")
    power.add_argument("--no-checks", action="store_true")
    power.add_argument("--out", help="write the markdown here instead of stdout")
    power.set_defaults(func=power_main)

    analyze = sub.add_parser("analyze", help="analyze an exported long table")
    analyze.add_argument("table", help="CSV written by scripts/export_learning_trial.py")
    analyze.add_argument("--windows", type=_ints, help="post-test windows to analyze (default 7)")
    analyze.add_argument("--clustering", choices=analysis.CLUSTERINGS, default="two-way")
    analyze.add_argument("--course-effects", action="store_true", help="course fixed effects (sensitivity)")
    analyze.add_argument("--arm-by-window", action="store_true", help="arm x window (pooled windows)")
    analyze.add_argument("--boot", type=int, default=2000, help="bootstrap resamples (paired analysis)")
    analyze.add_argument("--randomization", type=int, default=0, help="re-randomizations (0 = skip)")
    analyze.add_argument("--glmm", action="store_true", help="also fit the GLMM (needs requirements-analysis.txt)")
    analyze.add_argument("--seed", type=int, default=analysis.DEFAULT_SEED)
    analyze.add_argument("--out", help="write the markdown here instead of stdout")
    analyze.set_defaults(func=analyze_main)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
