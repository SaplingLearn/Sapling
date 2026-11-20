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
| `record` | live model | Capture/refresh cassettes. Writes `cassettes/<dataset>/<case>.json`. |
| `live` | live model | One-off experimentation, no recording. |

Because replay is deterministic (the model output is frozen in the cassette), a
task's aggregate score only moves when an **evaluator**, an **expected output**,
or a **cassette** changes. CI gates on *regression below a committed baseline*
(`baselines.json`), not on "< 1.0" — the harness measures accuracy, it does not
assume perfection. A case that raises, or an evaluator that raises on a case
(scored 0.0 there), fails the run.

A cassette replays only under what it was recorded with. The loop datasets
(`loop_tutor`, `misconception_confront`), `session_close`, `grader` (per run of
`grade()`), `decisions`, `check_items` and `chat_tutor` store the agent's prompt
hash (extended by the tool definitions it sends), the output schema's hash, the
slot's model and the hash of the exact message plus the model and run
settings; replay raises `StaleRecordingError` on any difference, so a prompt
swapped for an injection can never replay the old answer. A cassette written
before its dataset stored these fails closed until it is re-recorded (today:
`grader`, `decisions` and `check_items`, whose re-record waits on Gemini
billing). The rung and confront judge cassettes store the sha of the served
text they judged; `tests/test_eval_served_cassettes.py` re-derives every served
text from the committed recordings with the current production code and fails
when a judgement, or a `session_close` recording, no longer matches it.

## Running

```bash
cd backend
python tests/evals/run_all.py            # all offline datasets, gate on baselines
python tests/evals/document_summary.py   # one dataset, with the full per-case table
```

Exit code is non-zero on a regression or a missing cassette.

The harness never touches a database, in any mode. The AI budget check the
grader, decision, close and tutor paths run (`services/ai_budget.py`) reads an
empty in-memory store instead of `llm_usage` (`_replay.py::hermetic_budget`, around
every `evaluate_dataset` and `grader_agreement.py`'s grading), so the eval user
has no recorded spend whatever `backend/.env` names, and the run logs no
`ai_budget: llm_usage read failed` warning. A record or live run's model usage
is captured rather than queued for `llm_usage` (`_replay.py::usage_log`). With
`SAPLING_EVAL_USAGE_LOG=<path>`, each run appends one JSON line: dataset,
task, model, prompt, completion, cached and thinking tokens, requests, and
cost_usd as `llm_usage` would cost it. A re-record therefore measures what
`scripts/project_loop_cost.py` estimates (spec §13 A137).
`tests/test_eval_budget_hermetic.py` pins both.

## Refreshing after a prompt/model change

Recording hits each agent's live model — Claude since ADR 0030 — so it needs
`ANTHROPIC_API_KEY` set (in `.env`; `GEMINI_API_KEY` for every slot still on a
`gemini-*` model: the loop tutor tiers, the grader, check_items, session_close
and the eval judges). Transient 429/503/529s are retried automatically. The
Claude datasets were re-recorded on 2026-10-22 (`chat_tutor` again, three runs,
on 2026-11-18); the Gemini-era recordings are in git history. Follow the
three-run procedure below for every re-record.

Never hand-edit an existing case to make it pass; add a new case when
production surfaces a miss (see each dataset's module docstring).

### The re-record procedure: floors from three recordings (spec §13 A40 06(s), PKG-14)

A floor set from ONE recording is not accepted. Every re-record is:

1. **Record three times** with a run log. Each record run rewrites the
   dataset's cassettes, so the committed cassettes are the **last run's** and
   replay scores sit at or above the floor:

   ```bash
   cd backend
   for i in 1 2 3; do
     SAPLING_EVAL_MODE=record SAPLING_EVAL_RUNS_LOG=/tmp/runs.jsonl python tests/evals/<dataset>.py
   done
   ```

2. **Floors = the minimum of the three runs**, per evaluator, written by
   `floors.py` (never by hand, never from one run). For a routed dataset the
   same call rewrites its **routing block**: the three per-run score blocks
   (`_raised` set for a run in which a case or an evaluator raised) and
   `recorded_under`, the model, prompt hash and schema hash every run was
   recorded under (runs of different prompts or models are refused):

   ```bash
   # the loop tutor tiers (agents/loop_tutor.LOOP_ROUTABLE_TIERS reads the block)
   python tests/evals/floors.py --log /tmp/runs.jsonl --runs 3 \
       --datasets loop_tutor_lite,loop_tutor,loop_tutor_deep --routing loop_tutor_routing
   # the confronting turn (services/loop/guard.CONFRONT_TIERS reads the block)
   python tests/evals/floors.py --log /tmp/runs.jsonl --runs 3 \
       --datasets misconception_confront__loop_tutor_deep,misconception_confront__loop_tutor \
       --routing misconception_confront_routing
   # a dataset that routes nothing
   python tests/evals/floors.py --log /tmp/runs.jsonl --runs 3 --datasets chat_tutor
   ```

   `SAPLING_EVAL_UPDATE_BASELINES=1` does the same for a routed dataset: with
   `SAPLING_EVAL_RUNS_LOG` naming a log of its three recorded runs it rewrites
   the floor and the routing block together, and with fewer it refuses. For a
   dataset that routes nothing it still writes one run's scores, which
   `floors.py --check` then rejects wherever a run log exists.

3. **Commit the run log** of a dataset that routes nothing as
   `tests/evals/runs/<dataset>_<YYYY-MM-DD>.jsonl` (a routed dataset's runs
   live in its routing block), with the cassettes and `baselines.json`:

   ```bash
   cp /tmp/runs.jsonl tests/evals/runs/<dataset>_$(date -u +%Y-%m-%d).jsonl
   git add tests/evals/cassettes tests/evals/baselines.json tests/evals/runs
   git commit -m "evals: re-record <dataset> for <change>"
   ```

`python tests/evals/floors.py --check` (also run by `tests/test_eval_floors.py`)
fails when a floor is not the minimum of its recorded runs: a routed dataset's
routing block (written at up to three decimals before floors.py wrote them), or
the newest committed run log of any other dataset. A floor with neither must be
named in `floors.SINGLE_RECORDING_FLOORS`: the datasets recorded once before
this rule, each until its next re-record. `floors.py --dry-run` prints every run
and the floor without writing; it refuses fewer than three runs.

One committed dataset breaks "the cassettes are the last run's" until its next
re-record: `misconception_confront__loop_tutor`'s cassettes are a fourth
recording, not one of its three routing runs (they replay Confronts 0.429,
FeedbackNeverEndsInAnswer 1.0, RetriesUsed 0.857; no run scored that), and its
floors were once that recording's scores. Its floors (and the deep slot's
RetriesUsed) are now the minimum of the three routing runs, as the rule says:
FeedbackNeverEndsInAnswer 0.857, RetriesUsed 0.571. The loop and confront
cassettes and routing runs were recorded under prompt hash `10676b7d004e`; the
current loop prompt hashes differently, so those datasets, and the routing
pins in `tests/test_loop_tutor_agent.py` and `tests/test_learning_misconceptions.py`
that compare `recorded_under` with the current prompt and slot model, fail
until the Gemini re-record.

## Coverage

Offline (in `run_all.py` + CI): `document_classification`, `document_summary`,
`concept_extraction`, `syllabus_extraction`, `quiz_generation`, `chat_tutor`,
`loop_tutor` (three tier slots), `loop_rung_judge`, `check_items`, `grader`,
`decisions`, `session_close` and `misconception_confront` (two slots) — 255
cassettes, judge cassettes included.

Added by #866 (Z23, Z24), written as code and recorded in the A111 pass (three
runs each, floors from their minimum); until then each fails closed:

- **Replayed from the start** (they score paths the loop serves by default):
  `check_items`' two three-concept cases (production drafts
  `CHECK_ITEM_CONCEPTS_PER_CALL` concepts per call; `ConceptsCovered` scores
  that every concept gets a stored item), `loop_tutor`'s and
  `misconception_confront`'s worked-example-first cases (spec §13 A122), and
  `check_item_gates.py`'s `check_items_verify` (the A119 alignment check),
  `check_items_solve` (the A124 blind solve and key match) and
  `check_items_topup` (the A37 mc_reason top-up), each on its own slot and
  scored by production's own reading of its answers (`item_alignment.align`,
  `item_keys.compare`, `check_items_key_match.matches`).

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

`loop_tutor` (PKG-07) runs the same 10 cases once per tier slot (the series' 8, plus the novice worked-example-first teach turn and its H4 hint, spec §13 A122, added by #866 Z23 and recorded in the A111 pass) (`loop_tutor_lite`, `loop_tutor`, `loop_tutor_deep`), each with its own cassettes and baselines block, on the SERVED path (Task 9): a cassette is a `LoopRecording` — the raw `LoopTurnOut`, every raw attempt, request/retry counts, tool calls, and the `prompt_hash` / `schema_hash` / `model` / `input_sha256` it was recorded under (replay raises `StaleRecordingError` on any mismatch, and `tests/test_loop_tutor_agent.py` pins every cassette to the current hashes) — and replay recomputes the served text with production code (`turn_shape.render_turn`, then `services.loop.served.served_model_text` at `loop_leak_rung`), which the rung judge reads (`ajudge_rung`, `cassettes/loop_tutor_rung_judge/<slot>__<case>.json`). Served gates: ServedAnswerLeak, ServedNoReveal, CeilingCompliance, MaxSentences, OneQuestion, FeedbackNeverEndsInAnswer, SycophancyResists, NoControlTags, PlainMathBelowH6; diagnostics (baselined, never routing): RawAnswerLeak, RetriesUsed (1.0 = first attempt served). `agents/loop_tutor.LOOP_ROUTABLE_TIERS` is exactly the tiers whose three routing runs (`baselines.json` `loop_tutor_routing`) all score 1.0 on every served gate with no case raised (pinned by `test_loop_routable_tiers_match_baselines`; a routable tier's own floors are 1.0 on every served gate, `test_a_routable_tier_floors_at_one_on_every_served_gate`); in the 2026-09-29 runs that is standard and deep (lite raised a case in one run and scored CeilingCompliance 0.75 in another).

`loop_rung_judge` (PKG-07 Task 9, 8 cassettes under `cassettes/loop_tutor_rung_judge/`) calibrates the eval-side rung judge `_rung_judge.py`, which replaces `loop_tutor._infer_rung` (a marker classifier that scores any unmarked reply as H3, so no reply to an H1/H2-ceiling case can pass). The judge is an eval-only pydantic-ai agent (`RUNG_JUDGE_MODEL`, default `gemini-2.5-pro`, env-overridable; no production slot, no function-mode handler) prompted with `learning.ladder.RUNG_INTENT` verbatim, and returns `RungJudgement{rung 0..6, reveals_final_answer, evidence}`. `judge_rung(case_id, slot, served_text, item)` (and `await ajudge_rung(...)`) records to `cassettes/loop_tutor_rung_judge/<slot>__<case>.json` = `{served_sha256, judge_model, judge_prompt_hash, output}`; replay RAISES when the served text, the judge prompt (instructions, item block or output schema) or the judge model changed, so a stale judgement never scores. The calibration's eight hand-written replies span H0..H6 (two are plain H1/H2 text `_infer_rung` misreads; one is an unmarked full solution it under-counts); `RungJudgeAgreement` and `RevealAgreement` are gated at 1.0. On a miss fix the judge prompt, never the gold, and re-record.

`misconception_confront` (PKG-10, spec §13 A75) scores the confronting turn — the loop tutor plus the route's confrontation line (`services.loop.guard.confront_line_for` / `with_confrontation`, used by the eval so it scores what the route sends) — on the SERVED path, one dataset per slot a confronting turn can land on (`misconception_confront__loop_tutor_deep`, `misconception_confront__loop_tutor`; 8 cases each: five feedback turns incl. an instruction smuggled into the item-drafted misconception text, a hint at H4 on an unreleased isomorph, a novice teach turn, and a worked-example-first novice's H4 hint — spec §13 A122, #866 Z23, recorded in the A111 pass). Recording format, stale checks and served text are `loop_tutor.py`'s (cassettes `cassettes/misconception_confront/<slot>/`). Served gates: the loop tutor's (ServedAnswerLeak, ServedNoReveal, CeilingCompliance via the rung judge, MaxSentences, OneQuestion, FeedbackNeverEndsInAnswer — the final answer matched as a token — NoControlTags, PlainMathBelowH6) plus Confronts and NoAffirmation (the eval-only confront judge `_confront_judge.py`, gemini-2.5-pro, cassettes `cassettes/misconception_confront_judge/`, reading the model's part of the turn), VerdictHeld and NoInstructionEcho; diagnostics RawAnswerLeak, RetriesUsed. `baselines.json` `misconception_confront_routing` holds three fresh recordings per slot, keyed by the dataset name (`misconception_confront__<slot>`) as floors.py writes it; `services.loop.guard.CONFRONT_TIERS` is exactly the tiers whose three runs all score 1.0 on every served gate (pinned by `tests/test_learning_misconceptions.py`): deep only in the 2026-09-29 recordings (standard: Confronts 0.43/0.50/0.43).
