# Learning Loop — implementation prompt series

Seventeen packages — 00–14 plus 05b (decision seam) and 06b (AI budget and usage) — plus PKG-15 (Jev backend), post-series. One prompt file per package, executed in order by fresh Claude Code sessions. Each prompt is self-contained: it tells the session what to read, how to verify the base it builds on, what to build (TDD), how to check itself, and how to hand off.

Spec of record: `docs/superpowers/specs/2026-09-26-learning-loop-design.md`. Research: `docs/research/learning-loop/`.

## Before the first package

- The prompts run backend commands as `cd backend && venv/bin/python …` (house convention). If `backend/venv` does not exist on the machine: `cd backend && python -m venv venv && venv/bin/pip install -r requirements.txt`.
- The spec's **§13 Amendments log** overrides any prompt text it contradicts. It was written after the prompts, during the consistency pass; every prompt's "Read before you start" points at it.
- Also read spec §3.5/§3.6 (cost and decision constants: tier routing, caps and degradation ladder, decision-seam settings) and §14 (execution order and dependencies). Every unbuilt prompt lists them right after §13.

## How to run one package

1. Open a fresh Claude Code session in the repo root, on `main`, with the previous package's PR merged.
2. Paste the whole `PKG-NN-<slug>.md` file as the first message. Nothing else.
3. The session reads `LEDGER.md` first and refuses to start if an earlier row is `blocked` or `in-progress`.
4. It runs every "State of the world" verify command before Task 1. A red row means STOP and repair, never build on.
5. It works the tasks in TDD order, runs the self-check loop after each task, opens a PR titled `feat(learning): PKG-NN <slug>`, writes `HANDOFF-NN.md`, and appends its ledger row.
6. You review the PR and the hand-off; merge; start the next package. Exception: the PKG-14 half B PR is merged only as step 2 of the owner-run launch runbook (spec §11.7), after production is pinned `LEARNING_LOOP_ENABLED=false` (step 1).

## Order and dependencies

Strictly one package at a time, in this order (spec §14 is authoritative; where this section disagrees, §14 wins):

**00, 01, 02, 03, 04, 05, 05b, 06, 06b, 07, 08, 09, 10, 11, 12, 13, 14** (14 = half A, then half B after the §11.1 launch gate).

PKG-11 already ran, early — right after PKG-03's review round (branch `feat/learning-loop-11-quiz-flashcards`; ledger `11 | done`). It is kept (its code dependencies 02 and 03 were met); the order skips it when it reaches 11, and its prompt is frozen (spec §14).

```
PKG-00  foundation            needs —
PKG-01  bkt-core              needs 00
PKG-02  fsrs-core             needs 00
PKG-03  evidence-state        needs 01, 02
PKG-04  check-items           needs 00            (Task 0 reopens PKG-00)
PKG-05  grader-check-tool     needs 03, 04        (reopens PKG-03; renames PKG-01's GRADER_RETRY_BELOW)
PKG-05b decision-seam         needs 05            (reopens PKG-05)
PKG-06  zpd-policy            needs 03, 04
PKG-06b ai-budget-and-usage   needs 03, 06        (reopens PKG-05 and PKG-05b run sites)
PKG-07  loop-tutor            needs 05, 05b, 06, 06b
PKG-08  probe-planner         needs 07 (and 04, 05, 06b through it)
PKG-09  close-brief           needs 07, 08, 06b   (post-hoc edit of PKG-08's /plan/approve)
PKG-10  misconceptions        needs 05, 05b, 06, 07, 09
PKG-11  quiz-flashcards       needs 02, 03        (built early, after 03; prompt frozen)
PKG-12  review-surfaces       needs 05, 06b, 07, 11
PKG-13  frontend-e2e          needs 08, 09, 12 (and 06b for the cap journey)
PKG-14  eval-ladder-cutover   needs all of 00–13, 05b, 06b   (half B = the launch, spec §11)
PKG-15  jev-backend           post-series; needs 05b + the A24 privacy gate; not part of the launch gate
```
"needs" lists code dependencies only; the order above is stricter (e.g. 06b needs only 03 and 06 but runs after 05 and 05b because it wires `ai_budget.check` into their run sites as reopen commits). The ledger's `verified-by` column records which package re-verified what.

## Conventions (every prompt repeats these)

- Branch `feat/learning-loop-NN-<slug>` from `main`, never stacked. PR title `feat(learning): PKG-NN <slug>`. Commits `feat|fix|test|evals(learning-loop): PKG-NN — <summary>`, ending with the configured `Co-Authored-By` line (the unbuilt prompts spell it `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; the frozen 00–03 and 11 prompts still spell `Claude Fable 5.1`. When the executing session's configured attribution differs from a prompt's spelling, the configured line wins — not a deviation).
- Touching an earlier package's code: a separate first commit `fix(learning-loop): PKG-MM — <what>`; MM's tests stay green; ledger row `MM | reopened`; "Post-hoc changes" appended to `HANDOFF-MM.md`.
- Migrations: `backend/db/migrations/<UTC yyyymmddhhmmss>_learning_<desc>.sql`, never edited after creation. Schema fixes are new migrations.
- **End state: the loop is the default learning system for every student — no opt-in (spec §13 A14).** While the series is being built, everything ships dark behind `LEARNING_LOOP_ENABLED` (default off) so a merged partial package never reaches students; `user_settings.learning_loop_beta` is only a staff/QA toggle for local and staging test accounts. PKG-14 half B is the launch: it flips the default on for everyone. `learning_loop_beta` is readable, not student-patchable, set by SQL (PKG-04 Task 0 reopens PKG-00); launch runbook: spec §11.7.
- Built prompts (00–02, and PKG-11, which ran early) and the in-progress PKG-03 prompt are never edited; changes to their code are reopen commits in later packages, and wording changes reach their hand-offs as "Post-hoc changes" lines (spec §13 header, §14).
- Ledger reading: the ledger is append-only, so a package's state is its LATEST row. A ledger precondition ("rows 00–NN must be `done` or `verified`") means: the latest row of each listed package is `done`, `verified` or `reopened` (a `reopened` row records a sanctioned post-hoc change whose own tests stayed green; the State-of-the-world rows re-verify it); a latest row that is `planned`, `blocked` or `in-progress` is red. Never `tail -N` the ledger to check this.
- Constants are named in `backend/learning/params.py` and cited by name. A numeric literal in loop code is a review failure.
- `backend/tests/test_learning_loop_invariants.py` grows in every package's Task 1 and is the first thing the self-check loop runs.

## Files in this directory

- `LEDGER.md` — append-only status; the series' memory.
- `HANDOFF-template.md` — the hand-off note shape; `HANDOFF-NN.md` files are written by each package.
- `PKG-00-foundation.md` … `PKG-14-eval-ladder-cutover.md`, plus `PKG-05b-decision-seam.md` and `PKG-06b-ai-budget-and-usage.md` — the prompts. Their branches follow the convention: `feat/learning-loop-05b-decision-seam`, `feat/learning-loop-06b-ai-budget-and-usage`.
- PKG-15 (Jev backend, post-series) has no prompt here yet; spec §13 A24 and §14 define it.
