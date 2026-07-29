# 0021: Extraction-accuracy eval harness with committed baselines

- Status: accepted
- Date: 2026-07-28
- Relates to: #152 (agent migration epic), #148 (this issue); extends 0019 (test seams for agents)

## Context

The feature-surface agent migrations (#143–#147) are complete: `classifier`,
`summary`, `concepts`, `syllabus`, `quiz` and friends all run through Pydantic
AI. But they were only smoke-tested — nothing measured whether a prompt or model
change made *extraction accuracy* worse. #148 asks for an evaluation harness so
migrations can be validated and compared, and so the final `gemini_service`
cutover (#151) can lean on evidence rather than vibes.

A record/replay harness scaffold already existed under `backend/tests/evals`
(`_replay.py` + per-task `pydantic_evals` datasets), but it was non-functional:
only 4 of ~95 cases had cassettes, `quiz_generation`/`chat_tutor` had none, the
runner failed on any evaluator score `< 1.0` (wrong for an accuracy harness),
and the CI workflow was `workflow_dispatch`-only because of the coverage gap.

## Decision

Complete the harness and gate agent changes on it.

1. **Record cassettes for all five offline datasets** (`document_classification`,
   `document_summary`, `concept_extraction`, `syllabus_extraction`,
   `quiz_generation`) against live Gemini — 80 cassettes committed. Recording
   retries transient 503/UNAVAILABLE/429 so a blip can't leave a permanent gap.

2. **Gate on regression below a committed baseline, not on `< 1.0`.** Replay is
   deterministic (the model output is frozen in the cassette), so a task's
   aggregate score only moves when an evaluator, an expected output, or a
   cassette changes. `baselines.json` records the current per-evaluator scores;
   a run fails when a score drops below its baseline or a case raises (missing
   cassette). `SAPLING_EVAL_UPDATE_BASELINES=1` rewrites baselines from the
   current scores (refused if the run had failures).

3. **One command, one CI job.** `tests/evals/run_all.py` runs every offline
   dataset and prints a per-task accuracy summary. `evals.yml` runs it in replay
   mode (no Gemini key) on every PR touching `backend/agents/**` or the harness.

4. **`chat_tutor` stays out of the offline harness.** Its retrieval tool reads a
   live Supabase and cannot run against cassettes; it moves in with the
   graph-grounded tutor work (#149).

5. **Cross-platform robustness:** the runner forces UTF-8 on stdout/stderr so
   non-ASCII cases (e.g. a Mandarin syllabus) don't crash `rich` on a Windows
   cp1252 console.

## Baseline numbers (2026-07-28, current per-task models)

| Dataset | Evaluators | Score |
|---------|-----------|-------|
| document_classification | Category / SyllabusFlag | 0.80 / 0.88 |
| document_summary | AbstractLength | 0.933 (Headline / KeyPointsCount / NoMarkdownLeak: 1.00) |
| concept_extraction | all four | 1.00 |
| syllabus_extraction | NoInventedDates | 0.933 (all six others: 1.00) |
| quiz_generation | all seven | 1.00 |

These are the outputs of the frozen cassettes under the current models; they are
a floor, not a target. Re-record and re-baseline when a prompt or model changes,
reviewing the score deltas the run prints.

## Consequences

- (+) Prompt/model regressions on the migrated agents surface as a red PR check
  instead of a production incident, unblocking the #151 cutover with evidence.
- (+) Refresh is a two-command, reviewable diff (`record` then update baselines),
  committed alongside the change that moved the numbers.
- (−) Cassettes are frozen samples: replay validates evaluators/expectations
  against a snapshot, it does not re-exercise the live model. Catching a live
  model *regression* still requires a periodic `record` pass — a deliberate
  trade for a deterministic, keyless CI gate.
- (−) `chat_tutor` accuracy remains unmeasured until #149 gives it an offline
  retrieval seam.
