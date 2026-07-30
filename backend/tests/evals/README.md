# Agent evals (extraction-accuracy harness)

Offline accuracy harness for the migrated Pydantic AI agents (epic #152, issue
#148). It answers "did this prompt/model change make extraction worse?" without
hitting the network on every run.

## What it does

Each dataset is a set of `pydantic_evals.Case`s plus deterministic evaluators
(field accuracy, count-in-range, ISO-date shape, no-invented-dates, etc.). A
dataset runs an agent over its cases and scores the output.

Modes are selected by `SAPLING_EVAL_MODE`:

| Mode | Network | Use |
|------|---------|-----|
| `replay` (default) | none | CI + local checks. Loads frozen model outputs from `cassettes/`; a missing cassette fails loudly. |
| `record` | live Gemini | Capture/refresh cassettes. Writes `cassettes/<dataset>/<case>.json`. |
| `live` | live Gemini | One-off experimentation, no recording. |

Because replay is deterministic (the model output is frozen in the cassette), a
task's aggregate score only moves when an **evaluator**, an **expected output**,
or a **cassette** changes. CI gates on *regression below a committed baseline*
(`baselines.json`), not on "< 1.0" — the harness measures accuracy, it does not
assume perfection.

## Running

```bash
cd backend
python tests/evals/run_all.py            # all offline datasets, gate on baselines
python tests/evals/document_summary.py   # one dataset, with the full per-case table
```

Exit code is non-zero on a regression or a missing cassette.

## Refreshing after a prompt/model change

Recording hits live Gemini, so it needs `GEMINI_API_KEY` set (in `.env`).
Transient 503s are retried automatically.

```bash
cd backend
# 1. Re-record cassettes from the new prompt/model:
SAPLING_EVAL_MODE=record python tests/evals/run_all.py
# 2. Eyeball the score deltas the run prints. If the new numbers are the
#    intended new baseline, commit them:
SAPLING_EVAL_UPDATE_BASELINES=1 python tests/evals/run_all.py
# 3. Commit cassettes/ and baselines.json together:
git add tests/evals/cassettes tests/evals/baselines.json
git commit -m "evals: refresh cassettes + baselines for <change>"
```

Never hand-edit an existing case to make it pass; add a new case when
production surfaces a miss (see each dataset's module docstring).

## Coverage

Offline (in `run_all.py` + CI): `document_classification`, `document_summary`,
`concept_extraction`, `syllabus_extraction`, `quiz_generation`, and
`chat_tutor` — 96 cassettes.

`chat_tutor` records against the committed fixture course
(`fixtures/tutor_course.json`) through the TutorRetrieval seam
(`_retrieval_fixture.py`, ADR 0023), so even record/live runs never touch
Supabase. Its cassettes also freeze the model's *tool calls*, which the
graph-grounding evaluators (GraphToolUsed / MasteryUpdateEmitted /
GroundedConcept) score in replay.
