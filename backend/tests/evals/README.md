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
`concept_extraction`, `syllabus_extraction`, `quiz_generation`, `chat_tutor`,
and `check_items` — 106 cassettes.

`check_items` (learning loop PKG-04, 6 cassettes) drafts one course concept's
nine items per case from `fixtures/tutor_course.json` passages and scores them
with the same code rules the service stores by (`learning/checks.py::
validate_draft`) plus grounding (cited chunk ids are input ids; no reference
leaks into the prompt) and `FinalAnswerValid` (spec §13 A34, required 1.0:
every accepted draft's final answer is a verbatim copy from its reference).
Its baseline was re-recorded by PKG-06's A34 reopen of PKG-04 (29af030; one
recording on the final prompt — DraftValid 0.722, WrongReasonCount 0.667,
both lower than the first recording; HANDOFF-04/HANDOFF-06), then by the A37
reopen (spec §13 A37: the mc_reason options as objects, 48a65bc), its
review round (options alike in length), its third review (the reference
as a strong student's reason, never the model thinking aloud) and its round 4
(each distractor states its own misconception; the item's wrong reasons are
read off the distractors, and WrongReasonCount scores those for mc_reason).
`McOptionsValid` (required 1.0) and `McReasonValid` score the mc_reason
drafts; `McCorrectNotLongest` is the share of stored mc_reason drafts whose
correct option is not strictly the longest, gated at its recorded rate.

`chat_tutor` records against the committed fixture course
(`fixtures/tutor_course.json`) through the TutorRetrieval seam
(`_retrieval_fixture.py`, ADR 0023), so even record/live runs never touch
Supabase. Its cassettes also freeze the model's *tool calls*, which the
graph-grounding evaluators (GraphToolUsed / MasteryUpdateEmitted /
GroundedConcept) score in replay.

`loop_tutor` (PKG-07) runs the same 8 cases once per tier slot (`loop_tutor_lite`, `loop_tutor`, `loop_tutor_deep`), each with its own cassettes and baselines block, on the SERVED path (Task 9): a cassette is a `LoopRecording` — the raw `LoopTurnOut`, every raw attempt, request/retry counts, tool calls, and the `prompt_hash` / `schema_hash` / `model` / `input_sha256` it was recorded under (replay raises `StaleRecordingError` on any mismatch, and `tests/test_loop_tutor_agent.py` pins every cassette to the current hashes) — and replay recomputes the served text with production code (`turn_shape.render_turn`, then `routes.learn_loop.served_model_text` at `loop_leak_rung`), which the rung judge reads (`ajudge_rung`, `cassettes/loop_tutor_rung_judge/<slot>__<case>.json`). Served gates: ServedAnswerLeak, ServedNoReveal, CeilingCompliance, MaxSentences, OneQuestion, FeedbackNeverEndsInAnswer, SycophancyResists, NoControlTags, PlainMathBelowH6; diagnostics (baselined, never routing): RawAnswerLeak, RetriesUsed (1.0 = first attempt served). `agents/loop_tutor.LOOP_ROUTABLE_TIERS` is exactly the slots at 1.0 on every served gate (pinned by `test_loop_routable_tiers_match_baselines`); in the 2026-09-29 recording that is `loop_tutor` alone (HANDOFF-07).

`loop_rung_judge` (PKG-07 Task 9, 8 cassettes under `cassettes/loop_tutor_rung_judge/`) calibrates the eval-side rung judge `_rung_judge.py`, which replaces `loop_tutor._infer_rung` (a marker classifier that scores any unmarked reply as H3, so no reply to an H1/H2-ceiling case can pass). The judge is an eval-only pydantic-ai agent (`RUNG_JUDGE_MODEL`, default `gemini-2.5-pro`, env-overridable; no production slot, no function-mode handler) prompted with `learning.ladder.RUNG_INTENT` verbatim, and returns `RungJudgement{rung 0..6, reveals_final_answer, evidence}`. `judge_rung(case_id, slot, served_text, item)` (and `await ajudge_rung(...)`) records to `cassettes/loop_tutor_rung_judge/<slot>__<case>.json` = `{served_sha256, judge_model, judge_prompt_hash, output}`; replay RAISES when the served text, the judge prompt (instructions, item block or output schema) or the judge model changed, so a stale judgement never scores. The calibration's eight hand-written replies span H0..H6 (two are plain H1/H2 text `_infer_rung` misreads; one is an unmarked full solution it under-counts); `RungJudgeAgreement` and `RevealAgreement` are gated at 1.0. On a miss fix the judge prompt, never the gold, and re-record.
