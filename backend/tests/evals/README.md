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

## What replay does NOT cover (read before trusting a green run)

Replay scores **frozen cassettes**, so it can only ever tell you whether the
committed transcripts still satisfy the evaluators. It cannot tell you whether
the current prompt still produces those transcripts. Concretely: delete the
`SCOPE:` paragraph from `agents/chat_tutor.py` and
`NoCourseScopeRefusalEvaluator` / `OffSyllabusTopicEngagedEvaluator` still
return 1.0 — the path filter in `.github/workflows/evals.yml` fires the job on
`backend/agents/**`, so the job runs, it just has nothing new to observe.

So for any evaluator that scores a *prompt behaviour* rather than an
extraction shape, treat the replay lane as **documentation plus a
hand-edited-cassette tripwire**, not as a behavioural gate. The gates with
teeth are elsewhere:

- Prompt text itself: plain `pytest` (e.g.
  `tests/test_chat_tutor_imports.py::TestScopeRule`,
  `tests/test_learn_routes.py::TestChatContextBlockFraming`).
- Actual model behaviour: a lane that RUNS the model against the current
  prompt. `evals.yml` declares one — the scheduled, non-blocking `behavioral`
  job (`SAPLING_EVAL_MODE=live`, chat_tutor only, pinned to the Lite tier
  because that is where the refusal bug was reported). It is deliberately not
  a required PR check: a live model is nondeterministic and would flake the
  merge queue.

A behaviour-scoring evaluator should say which of the two it is in its
docstring. `chat_tutor.py` carries that note above its scope evaluators.

## Baselines are floors, not averages to relax

A baseline is a floor to hold, and a dropping score means the run got worse —
the fix is the regression, never the number. `MasteryUpdateEmittedEvaluator`
is the cautionary tale: it once scored all 17 chat_tutor cases even though
only 10 asserted anything, so 7 genuine failures averaged out to 0.588 and got
committed as the new "baseline" — a floor low enough for real emission to fall
from 100% to 60% and still pass. An evaluator that has no opinion about a case
should return `{}` (an empty mapping records no score) rather than a vacuous
1.0, so its aggregate stays a floor over the cases it actually judges.

`baselines.json` cannot hold a comment (it is `json.loads`-parsed and rewritten
wholesale by `SAPLING_EVAL_UPDATE_BASELINES=1`), so document a surprising
number next to the evaluator that produces it.

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
