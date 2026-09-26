# Learning Loop — implementation prompt series

Fifteen packages, one prompt file each, executed in order by fresh Claude Code sessions. Each prompt is self-contained: it tells the session what to read, how to verify the base it builds on, what to build (TDD), how to check itself, and how to hand off.

Spec of record: `docs/superpowers/specs/2026-09-26-learning-loop-design.md`. Research: `docs/research/learning-loop/`.

## Before the first package

- The prompts run backend commands as `cd backend && venv/bin/python …` (house convention). If `backend/venv` does not exist on the machine: `cd backend && python -m venv venv && venv/bin/pip install -r requirements.txt`.
- The spec's **§13 Amendments log** overrides any prompt text it contradicts. It was written after the prompts, during the consistency pass; every prompt's "Read before you start" points at it.

## How to run one package

1. Open a fresh Claude Code session in the repo root, on `main`, with the previous package's PR merged.
2. Paste the whole `PKG-NN-<slug>.md` file as the first message. Nothing else.
3. The session reads `LEDGER.md` first and refuses to start if an earlier row is `blocked` or `in-progress`.
4. It runs every "State of the world" verify command before Task 1. A red row means STOP and repair, never build on.
5. It works the tasks in TDD order, runs the self-check loop after each task, opens a PR titled `feat(learning): PKG-NN <slug>`, writes `HANDOFF-NN.md`, and appends its ledger row.
6. You review the PR and the hand-off; merge; start the next package.

## Order and parallelism

```
PKG-00 foundation
  ├─ PKG-01 bkt-core        (parallel with 02, 04)
  ├─ PKG-02 fsrs-core
  └─ PKG-04 check-items
PKG-03 evidence-state       needs 01, 02
PKG-05 grader-check-tool    needs 03, 04
PKG-06 zpd-policy           needs 03
PKG-07 loop-tutor           needs 05, 06
PKG-08 probe-planner        needs 07
PKG-09 close-brief          needs 07
PKG-10 misconceptions       needs 05, 06
PKG-11 quiz-flashcards      needs 02, 03
PKG-12 review-surfaces      needs 05, 11
PKG-13 frontend-e2e         needs 08, 09, 12
PKG-14 eval-ladder-cutover  needs all
```
Parallel packages each cut their own branch from `main`; merge conflicts are resolved by the later merger, and the ledger's `verified-by` column records which package re-verified what.

## Conventions (every prompt repeats these)

- Branch `feat/learning-loop-NN-<slug>` from `main`, never stacked. PR title `feat(learning): PKG-NN <slug>`. Commits `feat|fix|test|evals(learning-loop): PKG-NN — <summary>`, ending with the configured `Co-Authored-By` line.
- Touching an earlier package's code: a separate first commit `fix(learning-loop): PKG-MM — <what>`; MM's tests stay green; ledger row `MM | reopened`; "Post-hoc changes" appended to `HANDOFF-MM.md`.
- Migrations: `backend/db/migrations/<UTC yyyymmddhhmmss>_learning_<desc>.sql`, never edited after creation. Schema fixes are new migrations.
- Everything behind `LEARNING_LOOP_ENABLED` + `user_settings.learning_loop_beta` until PKG-14.
- Constants are named in `backend/learning/params.py` and cited by name. A numeric literal in loop code is a review failure.
- `backend/tests/test_learning_loop_invariants.py` grows in every package's Task 1 and is the first thing the self-check loop runs.

## Files in this directory

- `LEDGER.md` — append-only status; the series' memory.
- `HANDOFF-template.md` — the hand-off note shape; `HANDOFF-NN.md` files are written by each package.
- `PKG-00-foundation.md` … `PKG-14-eval-ladder-cutover.md` — the prompts.
