# PKG-05 grader-check-tool — Learning Loop series (6 of 17)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> You are a fresh session. Nothing outside this file, `docs/superpowers/plans/learning-loop/LEDGER.md`, the hand-offs it names, and the files this prompt lists is known to you. Do not infer intent from chat history you do not have. Do not read the whole research corpus; read the sections named below.

## Package id + goal

**PKG-05 `grader-check-tool`.** After this package: a `grader` agent exists that sees the stored reference answer and judges each rubric item yes/no without ever solving the problem or restating the key, with ONE second opinion on the `grader_second` slot (same agent, same prompt, `gemini-2.5-flash` with thinking 0, spec §13 A22); `agents/tools/check.py::grade_answer` is the single grading ROUTE helper (spec §13 A16) — it turns one explicit student submission into a code-side `GradeOutcome` plus one `Evidence` dict appended to `deps.pending_evidence`, applies the A22 deterministic pre-checks (the `mc_reason` option compared in code with the reason check run for BOTH outcomes; a numeric gate that can only ever say "incorrect"), records nothing for either outcome when the grader is unavailable (invariant 28), stamps `grader_backend`, and never writes a graph table; `Evidence.grader_backend` and its `node_mastery_events` column exist (PKG-03 reopened); `learning/evidence.py::flush_pending` is the one helper a ROUTE calls to persist that list through `apply_graph_update` once per submission; the function-mode seam serves both grader slots deterministically; `tests/evals/grader.py` gates reference leakage and rubric agreement and logs confidence against gold agreement. `grade_answer` is not a tool: nothing in this package is registered on any agent, and no route calls it yet (PKG-07's `/check/answer` is the first caller), so behaviour with `LEARNING_LOOP_ENABLED` unset or `true` is byte-identical. `tests/test_learning_check_tool.py` proves it.

Depends on (spec §14): PKG-03, PKG-04 (code). Runs after PKG-04 and before PKG-05b in the §14 order. Later reopens of this package's code: PKG-05b (`grade_answer` calls through `services/decisions.py`), PKG-06b (`grade()` checks the grader cap first), PKG-10 (the misconception hook in `grade_answer`).

Branch: `feat/learning-loop-05-grader-check-tool`. PR title: `feat(learning): PKG-05 grader-check-tool`.

## Read before you start (in this order)

0. `docs/superpowers/specs/2026-09-26-learning-loop-design.md` **§13 Amendments log** — in force; where this file and §13 disagree, §13 wins. Re-read it before Task 0. Rows A1, A2, A16 and A22 shape this package; A20 and A24 define what it must not build (see Non-goals).
1. The same spec, §3.5–§3.6 (cost/routing/decision constants), §7 (two-phase gate), §8 (invariants 13–29), §14 (order and dependencies).
2. `docs/superpowers/plans/learning-loop/LEDGER.md` — a package's state is its LATEST row (README "Ledger reading"); refuse to start if any earlier package's latest row is `blocked` or `in-progress`. The latest rows of 00, 01, 02, 03, 04 must be `done`, `verified` or `reopened`.
3. `docs/superpowers/plans/learning-loop/HANDOFF-03.md` and `HANDOFF-04.md` — §Symbols added is the contract. Before Task 0 write down: (a) the `learning.evidence.Evidence` field set — it must carry `idk: bool` (A1: there is no `"idk"` channel) — and the weight function (this prompt: `evidence_weight(ev) -> float`, computed from the flags: assisted only on a correct answer, same-session recheck, the grader's `confidence` below `GRADER_LOW_CONFIDENCE`, and `0.0` for a correct answer at H4–H6; PKG-03's `max_rung ≥ 1 → assisted` coercion applies); (b) where `services/graph_service.py::_apply_evidence` builds the `node_mastery_events` row dict and the test helpers PKG-03 left in `tests/test_learning_evidence_apply.py` (this prompt: `_ev`, `_apply`, `_event_rows`); (c) the `learning.checks.CheckItem` attributes (this prompt, per A2/A22: `id, course_id, concept_key, format, difficulty, prompt, reference_answer, rubric, common_wrong, options, correct_option, answer_kind, canonical_answer, tolerance, canonical_verified, stepwise, question_hash`; `rubric` = `{"id","text"}` entries, `common_wrong` = `{"key","text"}` entries, `options` = `Option{letter, text, wrong_key}` with `wrong_key == ""` on the correct option, all DECRYPTED by the service; if HANDOFF-04 gives `rubric`/`common_wrong` as models, use attribute access in `build_grader_message` and the eval). There is no `node_id` on an item — items are course assets keyed per concept (A2) — so `grade_answer`'s caller passes the student's `node_id`. A differing name → use the real one everywhere; a lookup, not a deviation. `Evidence` without `idk` → STOP and write a `BLOCKED` row (A1 belongs to PKG-03's model and `bkt.update`).
4. `CLAUDE.md` §Conventions and §Gotchas — the standing rules the "Do not" list below repeats.
5. `docs/superpowers/specs/2026-09-26-learning-loop-design.md` §3.1 (weights table + channel table), §3.3 "Evidence mapping by rung" and the slip/misconception bullet on `wrong_key` (A22), §3.4 (`GRADER_LIMITS`, `GRADER_LOW_CONFIDENCE`, `LEAK_NGRAM`), §3.5 (`GRADER_SECOND_OPINION_SLOT`, the `grader_second` slot row, the grader-cap row, the validity rule), §4 (the PKG-05 `grader_backend` DDL; the encryption paragraph), §5 (Evidence model + the two single-writer paragraphs), §7 ("Deps and tools": no grading tool on the loop), §8 invariants 1, 6, 12, 14, 28, §10 rung 1 (what `tests/evals/grader.py` must gate and log), §12 (no verdict cache; no code-issued "correct" on a strong channel).
6. `docs/superpowers/plans/learning-loop/README.md` — series conventions, especially "Touching an earlier package's code" (Tasks 0 and 5 reopen PKG-03; Task 0b reopens PKG-01 — read `HANDOFF-01.md` Known gaps (i) and (k) first).
7. `docs/superpowers/plans/learning-loop/HANDOFF-template.md` — what you write at the end.
8. Research, only these sections: `docs/research/learning-loop/AI tutor learning loop research.md` §"Check: free response and teach-back for credit" (≈ lines 78–80) and §"Guardrails … gate the grader" (≈ lines 131–137; the last paragraph is the grader's brief: sees the key, never solves, per-item binary + confidence, strictness is the safer bias); `docs/research/learning-loop/ZPD lever tradeoffs and upgrades.md` §"Sapling ZPD policy spec" → `EVIDENCE MAPPING` block (≈ lines 200–212).
9. Code you will modify: `backend/learning/evidence.py` (PKG-03's; Tasks 0 and 5), `backend/services/graph_service.py::_apply_evidence` (the evidence journal-row dict only; Task 0), `backend/tests/test_learning_evidence_apply.py` (PKG-03's; Task 0 appends), `backend/agents/__init__.py:83–87` (`TUTOR_LIMITS` shape; `GRADER_LIMITS` goes beside it), `backend/agents/_providers.py:39–49` (`AgentTask` Literal) and `:52–105` (`_DEFAULTS`), `backend/agents/function_handlers_e2e.py:190–205` (`_structured_output`) and `:250–275` (concept_describe section — the registration comment style), `backend/tests/test_agent_output_schemas.py:63–90` (the frozen roster sets), `backend/tests/evals/run_all.py:34` (`DATASETS`), `backend/tests/evals/baselines.json`, `backend/tests/test_learning_loop_invariants.py::test_inv_06_*` (PKG-04's shape).
10. Code you will mirror: `backend/agents/concept_describe.py` (tool-less flash-lite structured agent, `retries=2`), `backend/agents/flashcard.py:44–54` (`GoogleModelSettings(google_thinking_config=ThinkingConfig(thinking_budget=0))` — the `grader_second` settings shape), `backend/routes/notes.py:50–82` (`_run_note_worker` — the two-exception honest-degrade shape), `backend/tests/test_model_mode_seam.py:140–200` (scripted `ToolCallPart` through a real agent's output tool), `backend/tests/test_learning_learner_state_migration.py` (PKG-03's migration-test style), `backend/tests/evals/chat_tutor.py` + `_replay.py::run_with_cassette` (dataset shape).

## State of the world

Verify the base before Task 0. Every row must match.

| check | command | expected |
|---|---|---|
| ledger | `grep -E "^\| 0[0-4] " docs/superpowers/plans/learning-loop/LEDGER.md` | 00–04: the LATEST row of each listed package is `done`, `verified` or `reopened` (README "Ledger reading"; earlier rows are history); no package's latest row is `planned`, `blocked` or `in-progress` |
| hermetic suite green | `cd backend && venv/bin/python -m pytest tests/ -q -x` | `… passed`, zero failures (note the count N₀) |
| lint green | `cd backend && venv/bin/ruff check .` | `All checks passed!` |
| PKG-00 | `cd backend && venv/bin/python -m pytest tests/test_learning_gate.py -q` | `13 passed` |
| PKG-00 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q` | `4 passed, 8 skipped` (later packages raise the passed count) |
| PKG-00 | `cd backend && venv/bin/python -m pytest tests/test_learning_deps.py tests/test_learning_settings_flag.py tests/test_learning_loop_beta_migration.py -q` | all passed |
| PKG-00 | `grep -n "^LEARNING_LOOP_ENABLED" backend/config.py` | 1 hit |
| PKG-00 | `ls backend/db/migrations/*_learning_loop_beta.sql` | 1 file |
| PKG-03 | `cd backend && venv/bin/python -m pytest tests/test_learning_evidence_apply.py tests/test_graph_service.py -q` | all passed |
| PKG-03 | `ls backend/db/migrations/*_learning_learner_state.sql` | 1 file |
| PKG-03 | `grep -c '"evidence"' backend/services/graph_service.py` | ≥ 1 |
| PKG-03 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k inv_01` | 1 passed |
| PKG-04 | `cd backend && venv/bin/python -m pytest tests/test_learning_check_items.py -q` | N passed (N ≥ 14) |
| PKG-04 | `ls backend/db/migrations/*_learning_check_items.sql` | 1 file |
| PKG-04 | `grep -c '"check_items"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py` | ≥ 1 each |
| PKG-04 | `grep -ohE "options_json\|correct_option\|answer_kind\|canonical_answer\|canonical_verified\|stepwise" backend/db/migrations/*_learning_check_items.sql \| sort -u \| wc -l` | 6 |
| PKG-04 | `grep -c -- "--all-courses" backend/scripts/backfill_check_items.py` | ≥ 1 |
| PKG-04 | `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/check_items.py` | every evaluator ≥ baseline |
| PKG-04 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_06 or inv_09 or inv_12"` | 3 passed |
| stubs still inert | `wc -l backend/agents/grader.py backend/agents/tools/check.py` | each ≤ 5 lines (docstring only) |
| deps ready | `grep -c "pending_evidence\|learning_loop" backend/agents/deps.py` | ≥ 2 |
| PKG-03 reopen not yet applied | `grep -c "grader_backend" backend/learning/evidence.py backend/services/graph_service.py` | `0` and `0` |

Rule: any red row → STOP. Diagnose, repair on this branch as commit `fix(learning-loop): repair pre-series base — <what>`, record the deviation in `LEDGER.md`, re-run all rows. Never build on a broken base.

## Spec

### Behaviour

1. **Grader agent** (`agents/grader.py`, task `"grader"`, default `gemini-2.5-flash-lite`, tool-less, `retries=2`, `output_type=GraderOutput`). ONE user message from `build_grader_message(item, format=, student_answer=)`: question, reference answer, rubric items (`RUBRIC ITEM <id>: <text>`, one per line), common wrong reasons (`COMMON WRONG REASON <key>: <text>`), format, student answer. FLAT output: `item_results: list[str]` of `"<rubric_id>:yes|no"`, `confidence` in [0, 1], `matched_wrong_key` (a listed key or `""`), `feedback_hint` (≤ `FEEDBACK_HINT_MAX_SENTENCES` sentences, ≤ `GRADER_HINT_MAX_CHARS` chars, never the reference). System prompt: judge each rubric item strictly against the reference; never solve the problem; never restate, quote or paraphrase the reference; when unsure answer `no` and lower `confidence` (strictness is the safer bias).
2. **`grade(item, *, format, student_answer, deps) -> GradeResult`** (async, `agents/grader.py`) is the only caller of the agent and the single Gemini grader (PKG-05b wraps it without changing the prompt): `grader_agent.run(message, deps=deps, usage_limits=GRADER_LIMITS)`, then `record_agent_usage(result, feature=deps.feature, task="grader", user_id=deps.user_id)`, then `parse_item_results` (missing/malformed id → `False`; ids outside the rubric dropped) into a code-side `GradeResult(item_results, all_yes, confidence, matched_wrong_key, feedback_hint, low_confidence=confidence < GRADER_LOW_CONFIDENCE, backend)`. Second opinion (spec §3.4, A22): `confidence < GRADER_SECOND_OPINION_CONFIDENCE` → ONE more run of the SAME agent and message on slot `GRADER_SECOND_OPINION_SLOT` (`grader_agent.run(..., model=model_for("grader_second"), model_settings=_SECOND_OPINION_SETTINGS)`, own limits, own usage row with `task="grader_second"`); its verdict is used with `backend="gemini_second"`; still below → `GradeResult(unavailable=True)`. A first-run verdict carries `backend="gemini"`. `AgentTask` gains `"grader"` and `"grader_second"`; `_DEFAULTS["grader_second"] = "gemini-2.5-flash"`.
3. **Honest degrade** (ADR 0024): `UsageLimitExceeded` or `UnexpectedModelBehavior` from either call → `logger.warning("grader unavailable for item %s: %s", item.id, exc)` and `GradeResult(unavailable=True)`. No second prompt stack, no fallback text, no retry beyond pydantic-ai's `retries=2`. No event is emitted in this package (PKG-06 owns the `zpd.*` taxonomy, PKG-05b `decision.*`, PKG-06b `ai.*`; the WARNING line is the observable).
4. **`grade_answer(item, answer, *, deps, node_id, max_rung=0, same_session_recheck=False) -> GradeOutcome`** (async, `agents/tools/check.py`) — the single grading ROUTE helper (A16), shared by the check route (PKG-07), probe (PKG-08), review (PKG-12) and post-test (PKG-14). `item` is a decrypted `CheckItem` the caller loaded by `answer.question_hash`; `node_id` is the student's `graph_nodes.id` for `item.concept_key` (the caller resolves it, A2). `CheckAnswer` is FLAT: `question_hash, answer_text, selected_option, reason, idk`. `GradeOutcome` (dataclass): `correct: bool | None, confidence: float | None, feedback_hint: str, matched_wrong_key: str | None, wrong_key: str | None, unavailable: bool, grader_backend: str | None, evidence: dict | None`. In order:
   - `deps.learning_loop is False` → `GradeOutcome(unavailable=True)`; append nothing; call nothing.
   - channel = `CHANNEL_FOR_FORMAT[item.format]` (`free → free_response`, `teachback → teachback_llm`, `mc_reason → mc_reasoned`); `assisted = RUNG_ASSISTED_MIN <= max_rung <= RUNG_ASSISTED_MAX`.
   - `answer.idk` (A1) → `Evidence(channel=<item's channel>, idk=True, correct=False, confidence=None, grader_backend=None, …)`; the grader is NOT called.
   - `grade(item, format=item.format, student_answer=<answer_text, or for mc_reason "Selected option: …\nReason: …">, deps=deps)` — for EVERY non-idk attempt. For `mc_reason` this reason check runs for BOTH outcomes of the option comparison; for a numeric item it runs for both outcomes of the numeric gate too (below), so a grader outage or the grade cap records nothing for either outcome (invariant 28).
   - numeric gate (A22; `free`/`teachback` items), applied AFTER the grader returned: `item.answer_kind == "numeric"` AND `item.canonical_verified` AND both `answer.answer_text` and `item.canonical_answer` parse as finite floats AND `|answer − canonical| > (item.tolerance or 0.0)` → incorrect with `grader_backend="deterministic"`, `confidence=None`, overriding the grader's verdict (the grader's `matched_wrong_key` still feeds `wrong_key`). A match, a parse failure or an unverified key keeps the grader's verdict. Code never issues "correct" on a strong channel. (No call is saved — the gate buys a deterministic "incorrect", never a cheaper grade: a gate that skipped the grader would record a clear mismatch under an outage or the cap while a matching answer recorded nothing — one outcome only.)
   - `unavailable` (outage, second opinion unavailable; the cap from PKG-06b) → `GradeOutcome(unavailable=True)`; append nothing for EITHER outcome (A22, invariant 28).
   - correct: `free`/`teachback` → `all_yes`; `mc_reason` → the selected option equals the decrypted `item.correct_option` (compared in code, case/whitespace-insensitive) AND `all_yes`.
   - `wrong_key` (A22): `None` when correct or when the grader matched nothing; `free`/`teachback` → the grader's `matched_wrong_key`; `mc_reason` wrong option → that option's `wrong_key` only when it equals the grader's `matched_wrong_key`, else `None` (the option → key map is only a prior); `mc_reason` right option with a failed reason → the grader's `matched_wrong_key` (the student's reason matched it, spec §3.3).
   - weight: PKG-03's `evidence_weight(ev)` on the built `Evidence` (the grader's `confidence` is set for BOTH outcomes, so a low-confidence reason check weighs a correct and a wrong answer alike; a correct answer at `max_rung ≥ RUNG_NO_CREDIT_MIN` gets `0.0` and is still appended so the route writes FSRS Again + the event, spec §3.3).
   - append the `Evidence(...).model_dump()` (with `session_id=deps.session_id`, `check_item_id=item.id`, `question_hash=item.question_hash`, `grader_backend`) to `deps.pending_evidence` and return it as `GradeOutcome.evidence`, with `confidence`, `feedback_hint`, `matched_wrong_key`, `wrong_key`, `grader_backend`. The outcome NEVER contains `item.reference_answer` (tested by substring). `feedback_hint` is optional downstream: the A16 feedback turn writes the student-facing text.
5. **`grade_answer` never persists.** `agents/tools/check.py` imports nothing from `db.connection`, calls neither `apply_graph_update` nor any `table(...)`, and defines no `Tool`/`RunContext` — it is not a tutor tool (A16; `_build_tools(learning_loop=True)` registers no grading tool, spec §7). The only writer is the calling route, through `learning.evidence.flush_pending(deps, course_id)`.
6. **`flush_pending(deps, course_id) -> list`** (`learning/evidence.py`, Task 5): empty list → return `[]`, call nothing; else `apply_graph_update(deps.user_id, {"evidence": list(deps.pending_evidence)}, course_id)` exactly once (local import — PKG-03's `graph_service` imports `learning.evidence`, so a module-level import is circular), clear the list, return the changes. `grade_answer` never calls it; PKG-07 wires it into `/check/answer` between `grade_answer` and the feedback turn (A16).
7. **Function-mode handler** (tasks `"grader"` AND `"grader_second"`, one handler): reads the last user prompt, extracts rubric ids with `re.findall(r"^RUBRIC ITEM (\S+):", text, re.M)`; `E2E_GRADER_CORRECT_TOKEN` in the text → every id `yes`, else every id `no`; `confidence=E2E_GRADER_CONFIDENCE`, `feedback_hint=E2E_GRADER_HINT`; emits through `info.output_tools[0]` so the real schema validates it.
8. **`Evidence.grader_backend`** (Task 0, reopens PKG-03; spec §5, A22): `grader_backend: Literal["deterministic","gemini","gemini_second","jev"] | None = None`; `_apply_evidence` journals it on the `node_mastery_events` row (key always present, null when `None`); migration `<ts>_learning_grader_backend.sql` adds the nullable, CHECK-constrained plaintext column. Values written by this package: `"gemini"` (first grader run's verdict), `"gemini_second"` (second opinion's verdict), `"deterministic"` (numeric mismatch), `None` (idk — no verdict was computed †). `"jev"` is reserved for PKG-15.
9. **Flag inertness.** `LEARNING_LOOP_ENABLED` unset (or `true`) changes nothing in this package: nothing registers or calls `grade_answer`, `grade` or `flush_pending`, and `grade_answer` returns `GradeOutcome(unavailable=True)` without calling anything when `deps.learning_loop` is False (`test_grade_answer_is_inert_when_learning_loop_false`). The new `node_mastery_events` column is nullable and written only on evidence rows, so every legacy journal row is unchanged.

### Schema (exact)

One migration, written by Task 0 as a reopen of PKG-03 (spec §4, A22):

```sql
-- PKG-05: <ts>_learning_grader_backend.sql  (A22)
ALTER TABLE node_mastery_events ADD COLUMN IF NOT EXISTS grader_backend text
  CHECK (grader_backend IS NULL OR grader_backend IN ('deterministic','gemini','gemini_second','jev'));
```

`grader_backend` is plaintext (spec §4 encryption paragraph). The `Evidence` model is PKG-03's (spec §5; this package adds only `grader_backend`); the `check_items` table is PKG-04's (spec §4) and read-only here — `options_json`, `correct_option` and `canonical_answer` arrive decrypted on `CheckItem`. The one Pydantic shape this package sends to or receives from Gemini — `GraderOutput` (4 flat fields, Task 2) — is written out in full and stays inside the `agents/__init__.py` schema budget. `CheckAnswer` (5 flat fields) and `GradeOutcome` (8 fields) are code-side shapes, never sent to a model.

### Named constants

Every number this package uses, once. Tasks cite the NAME. `†` = engineering choice with no validated cut-point (add to `learning/params.py` and record in the hand-off as a deviation).

| Name | Value | Where it lives | Spec ref |
|---|---|---|---|
| `GRADER_LIMITS` | `UsageLimits(request_limit=2, tool_calls_limit=0, total_tokens_limit=20_000)` | `agents/__init__.py` (beside `TUTOR_LIMITS`, the house location for limits) | §3.4 |
| `GRADER_LOW_CONFIDENCE` | 0.6 | `learning/params.py` (PKG-01 created it; verify with grep) | §3.4 |
| `GRADER_SECOND_OPINION_CONFIDENCE` | 0.4 | `learning/params.py` — RENAMED from PKG-01's `GRADER_RETRY_BELOW` (same value, same §3.4 threshold) in Task 0b; never added beside it, no alias (HANDOFF-01 Known gaps (i), (k)) | §3.4, A6 |
| `GRADER_SECOND_OPINION_SLOT` | `"grader_second"` | `learning/params.py` (add) | §3.5, A22 |
| `_DEFAULTS["grader_second"]` | `"gemini-2.5-flash"` | `agents/_providers.py` | §3.5 slot table |
| `_SECOND_OPINION_SETTINGS` | `GoogleModelSettings(google_thinking_config=ThinkingConfig(thinking_budget=0))` | `agents/grader.py` (per-run settings for the `grader_second` slot) | §3.5 slot table |
| `WEIGHT_ASSISTED` | 0.5 | `learning/params.py` (PKG-01) | §3.1 |
| `WEIGHT_SAME_SESSION_RECHECK` | 0.5 † | `learning/params.py` (PKG-01) | §3.1 (unvalidated heuristic, §13 A30) |
| `WEIGHT_LOW_CONFIDENCE` | 0.5 | `learning/params.py` (PKG-01) | §3.1 |
| `LEAK_NGRAM` | 6 | `learning/params.py` (PKG-01) | §3.4 |
| `RUNG_ASSISTED_MIN` / `RUNG_ASSISTED_MAX` | 1 / 3 | `learning/params.py` (A6 names for §3.3 "H1–H3"; add if PKG-01 did not) | §3.3, A6 |
| `RUNG_NO_CREDIT_MIN` | 4 | `learning/params.py` (A6 name for §3.3 "H4–H6"; add if absent — PKG-03's `evidence_weight` applies the same cut under the name HANDOFF-03 lists) | §3.3, A6 |
| `FEEDBACK_HINT_MAX_SENTENCES` † | 2 | `learning/params.py` | brief; not in spec |
| `GRADER_HINT_MAX_CHARS` † | 300 | `learning/params.py` | schema guard; not in spec |
| `GRADER_EVAL_MAX_CASES` | 8 | `tests/evals/grader.py` (an assert on `len(CASES)`) | series rule |
| `E2E_GRADER_CORRECT_TOKEN` | `"E2E_GRADER_CORRECT"` | `agents/function_handlers_e2e.py` | — |
| `E2E_GRADER_CONFIDENCE` | 0.95 | `agents/function_handlers_e2e.py` (a fixture value, ≥ `GRADER_LOW_CONFIDENCE` so E2E evidence is full-weight and the second opinion never fires in E2E) | — |
| `E2E_GRADER_HINT` | `"[e2e-function-model] Deterministic grader hint: check the base case first."` | `agents/function_handlers_e2e.py` | — |

`GRADER_LIMITS.request_limit` is 2 while `retries=2` on the agent means a second validation retry trips `UsageLimitExceeded` rather than `UnexpectedModelBehavior`. That distinction matters at `routes/notes.py` (413 vs 500); it does not matter here, because both exceptions degrade to the same `unavailable` result. Keep the spec value. The second opinion is a separate run with its own `GRADER_LIMITS`.

### Invariants asserted by this package (spec §8 numbering)

- (6) extended: `"grader"` and `"grader_second"` are series `AgentTask` literals (spec §8.6) with a handler registered in `agents/function_handlers_e2e.py`, checked by `test_inv_06_series_agent_tasks_have_function_handlers`.
- (12) already asserted by PKG-04 for every series agent module: `agents/grader.py` defines exactly one system prompt and one `Agent(`. The `grader_second` slot is a per-run `model=`, never a second `Agent(`. Do not add a `_fallback_prompt`.
- (14) `test_inv_14_tools_never_write_graph_tables` (series extension of §8.1; covers `agents/tools/check.py::grade_answer`): a source scan of `backend/agents/tools/*.py` finds no `table("graph_nodes")`, `table("graph_edges")`, `table("node_mastery_events")`, `table("learner_state")`, and `agents/tools/check.py` contains neither `apply_graph_update`, `from db.connection import`, `RunContext` nor `Tool(`.
- (28, new — outage half) `test_inv_28_symmetric_missingness`: with `grade` monkeypatched to `unavailable`, `grade_answer` on a correct and on a wrong `mc_reason` attempt appends zero evidence in both cases, and the reason check was attempted for both (behavioural; no DB). PKG-06b extends it with the `STUDENT_DAILY_GRADES` cap half.

### Error semantics

- Grader budget/behaviour failure, or a second opinion still below `GRADER_SECOND_OPINION_CONFIDENCE` → `GradeResult(unavailable=True)` + WARNING; `grade_answer` returns `GradeOutcome(unavailable=True)` and appends nothing for either outcome (A22, invariant 28). Never raises into the caller for a grader failure; the caller decides the response shape (PKG-07/08/12/14).
- `deps.learning_loop` False → `GradeOutcome(unavailable=True)`, nothing called.
- An unknown `question_hash` is the caller's concern: `grade_answer` receives a loaded item and never reads storage.
- A numeric parse failure is not an error: the answer goes to the rubric grader.
- `flush_pending` does NOT catch: `apply_graph_update` errors propagate to the route (PKG-07 decides the HTTP shape). It clears the list only after a successful call.

### Events added

None. The taxonomy is untouched (PKG-05b adds `decision.*`, PKG-06 `zpd.*`, PKG-06b `ai.budget_capped`). `record_agent_usage` writes `llm_usage` rows for every grader call under `task="grader"` or `task="grader_second"`, which is the cost trail the admin analytics already reads (and the grade count PKG-06b's `STUDENT_DAILY_GRADES` cap reads).

## Non-goals

- No tool and no registration of anything on any agent: `grade_answer` is a route helper (A16); `chat_tutor._build_tools(learning_loop=True)` is PKG-07 and registers no grading tool (spec §7). No route (PKG-07 `/check/answer`, PKG-08 probe, PKG-12 review and PKG-14 post-test call `grade_answer`), no stream event, no frontend.
- No `ai_budget` call (A20): PKG-06b reopens `agents/grader.py::grade` to call `ai_budget.check(user_id, "grader")` before the first run (invariant 23) and extends `test_inv_28` with the cap half. This package's grader runs uncapped.
- No decision seam (A24): `services/decisions.py`, the `decision` slot and any Jev code are PKG-05b / PKG-15. PKG-05b reopens `grade_answer` to call through `decisions.grade_rubric_items` / `decisions.reason_is_correct` with byte-identical prompts. Do not pre-build any of it.
- No leak detector (`learning/leak.py::detect_leak` is PKG-06). The eval's `NoReferenceLeak` is this package's only leakage gate; any consumer that shows `feedback_hint` itself routes it through `detect_leak` first.
- No misconception recording: `matched_wrong_key` and `wrong_key` reach only `GradeOutcome` (spec §5's `Evidence.wrong_key`/`verdict` are PKG-10's reopen of PKG-03); PKG-10 decides where they persist. No FSRS rating here — `rating_for` runs inside `apply_graph_update` (PKG-03); `grade_answer` only sets the flags and `weight`.
- No verdict cache, no embedding pre-screen, no `symbolic`/`exact` answer kinds (spec §12). No taxonomy change, no `lru_cache`. The one migration is Task 0's `grader_backend` column.

## Tasks

### Task 0: Reopen PKG-03 — `Evidence.grader_backend` and its `node_mastery_events` column

This is the package's FIRST commit (README "Touching an earlier package's code": separate commit, PKG-03's tests stay green, ledger `03 | reopened`, HANDOFF-03 "Post-hoc changes").

**Files:**
- Create: `backend/db/migrations/<UTC>_learning_grader_backend.sql`, `backend/tests/test_learning_grader_backend_migration.py`
- Modify: `backend/learning/evidence.py` (one field + one `Literal`), `backend/services/graph_service.py` (`_apply_evidence`: one key on the evidence journal row), `backend/tests/test_learning_evidence_apply.py` (append `TestGraderBackend`), `docs/superpowers/plans/learning-loop/HANDOFF-03.md`, `docs/superpowers/plans/learning-loop/LEDGER.md`

**Interfaces:**
- Consumes: PKG-03's `Evidence`, `_apply_evidence`, test helpers `_ev`, `_apply`, `_event_rows` (names per HANDOFF-03).
- Produces: `learning.evidence.GraderBackend`, `Evidence.grader_backend`; column `node_mastery_events.grader_backend`.

- [ ] **Step 1: Write the failing tests.** Create `backend/tests/test_learning_grader_backend_migration.py`:

```python
"""PKG-05's reopen of PKG-03 (spec §4, §13 A22): node_mastery_events.grader_backend.
Live schema is proven by migration replay in the E2E lane; this guards the DDL."""
import pathlib
import re

MIG_DIR = pathlib.Path(__file__).resolve().parents[1] / "db" / "migrations"
GRADER_BACKENDS = ("deterministic", "gemini", "gemini_second", "jev")


def _migration() -> tuple[str, str]:
    hits = sorted(MIG_DIR.glob("*_learning_grader_backend.sql"))
    assert len(hits) == 1, f"expected exactly one grader_backend migration, got {hits}"
    return hits[0].name, hits[0].read_text()


def test_grader_backend_column_is_nullable_and_checked():
    _, sql = _migration()
    assert "ALTER TABLE node_mastery_events ADD COLUMN IF NOT EXISTS grader_backend text" in sql
    assert "NOT NULL" not in sql, "legacy journal writers never set it"
    m = re.search(r"CHECK \(grader_backend IS NULL OR grader_backend IN \(([^)]*)\)\)", sql)
    assert m, sql
    assert tuple(v.strip().strip("'") for v in m.group(1).split(",")) == GRADER_BACKENDS


def test_migration_prefix_is_a_utc_timestamp_after_pkg03():
    name, _ = _migration()
    assert re.fullmatch(r"\d{14}_learning_grader_backend\.sql", name), name
    prior = sorted(MIG_DIR.glob("*_learning_learner_state.sql"))[0].name
    assert name > prior, "must sort after PKG-03's migration"
```

Append to `backend/tests/test_learning_evidence_apply.py` (reuse the module's `_ev`, `_apply`, `_event_rows`, `ValidationError` imports):

```python
# ── grader_backend (reopened by PKG-05; spec §5, §13 A22) ─────────────────────


class TestGraderBackend:
    def test_field_defaults_to_none_and_accepts_only_the_four_backends(self):
        assert _ev().grader_backend is None
        for backend in ("deterministic", "gemini", "gemini_second", "jev"):
            assert _ev(grader_backend=backend).grader_backend == backend
        with pytest.raises(ValidationError):
            _ev(grader_backend="gpt")

    def test_evidence_row_journals_grader_backend_null_when_absent(self):
        _, mocks, _ = _apply({"evidence": [
            {"node_id": "n1", "channel": "free_response", "correct": True, "grader_backend": "gemini"},
            {"node_id": "n1", "channel": "mc", "correct": False},
        ]}, edges=[])
        first, second = _event_rows(mocks)
        assert first["grader_backend"] == "gemini"
        assert "grader_backend" in second and second["grader_backend"] is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_grader_backend_migration.py tests/test_learning_evidence_apply.py -v -k "grader_backend or GraderBackend"`
Expected: the two migration tests FAIL — `expected exactly one grader_backend migration, got []`; both `TestGraderBackend` tests FAIL — `grader_backend` is not an `Evidence` field yet (`AttributeError`, or `KeyError` on the journal row).

- [ ] **Step 3: Implement**

`backend/learning/evidence.py` (keep everything PKG-03 wrote; add beside `Channel`):
```python
#: Which backend produced an evidence verdict (spec §5, §13 A22). "jev" is PKG-15's.
GraderBackend = Literal["deterministic", "gemini", "gemini_second", "jev"]
```
and, as the last field of `Evidence` before any validator (after the fields PKG-03 declared):
```python
    grader_backend: GraderBackend | None = None  # A22 provenance; PKG-05 reopen of PKG-03
```

`backend/services/graph_service.py::_apply_evidence`: add `"grader_backend": ev.grader_backend` to the evidence journal-row dict it passes to `_insert_mastery_event` (the key is always present, `None` when unset — the same rule as PKG-03's other evidence columns). `_insert_mastery_event` and the legacy paths are not modified.

Migration: generate the prefix with `date -u +%Y%m%d%H%M%S`; file `backend/db/migrations/<UTC>_learning_grader_backend.sql`:
```sql
-- Learning loop PKG-05 (reopens PKG-03; spec §4, §13 A22): which backend
-- produced an evidence verdict. Plaintext enum; written only on evidence rows
-- by apply_graph_update, null on every legacy journal row.
ALTER TABLE node_mastery_events ADD COLUMN IF NOT EXISTS grader_backend text
  CHECK (grader_backend IS NULL OR grader_backend IN ('deterministic','gemini','gemini_second','jev'));
```

- [ ] **Step 4: Run PKG-03's verify block, the new tests, migration naming, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_grader_backend_migration.py tests/test_learning_evidence_apply.py tests/test_graph_service.py tests/test_learning_loop_invariants.py tests/test_migration_naming.py tests/test_migrations.py -q && venv/bin/ruff check .`
Expected: all passed (inv_01 and inv_08 green; PKG-03's legacy byte-identity trace unchanged — the legacy path never builds an evidence row); `All checks passed!`

- [ ] **Step 5: Reopen bookkeeping** — append to `HANDOFF-03.md` "Post-hoc changes": `PKG-05 <date>: Evidence.grader_backend + node_mastery_events.grader_backend (migration <file>; spec §13 A22) — commit <sha>`; append ledger row `| 03 | evidence-state | reopened | feat/learning-loop-05-grader-check-tool | <sha> | +4 (test_learning_grader_backend_migration.py 2, test_learning_evidence_apply.py 2) | PKG-05, <date>, tests/test_learning_evidence_apply.py tests/test_graph_service.py → all passed | HANDOFF-03.md |`.

- [ ] **Step 6: Commit**

```
git add backend/db/migrations/*_learning_grader_backend.sql backend/learning/evidence.py backend/services/graph_service.py backend/tests/test_learning_grader_backend_migration.py backend/tests/test_learning_evidence_apply.py docs/superpowers/plans/learning-loop/HANDOFF-03.md docs/superpowers/plans/learning-loop/LEDGER.md
git commit -m "fix(learning-loop): PKG-03 — Evidence.grader_backend and its node_mastery_events column

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 0b: Reopen PKG-01 — rename `GRADER_RETRY_BELOW` → `GRADER_SECOND_OPINION_CONFIDENCE`

The package's SECOND commit, separate from Task 0 (README "Touching an earlier package's code"). PKG-01 shipped spec §3.4's "below 0.4 → second grader call" threshold as `GRADER_RETRY_BELOW = 0.4` ‡; spec §13 A6 names the same threshold `GRADER_SECOND_OPINION_CONFIDENCE`, and §13 wins. HANDOFF-01 Known gaps (i) and (k) and the ledger deviation for PKG-01 fix the method: RENAME, no alias, never a second name beside the first.

**Files:**
- Modify: `backend/learning/params.py` (the one line: `GRADER_RETRY_BELOW = 0.4  # ‡ …` → `GRADER_SECOND_OPINION_CONFIDENCE = 0.4  # spec §3.4 / §13 A6 — below this, ONE second grader call on slot grader_second (A22)`), `backend/tests/test_learning_bkt.py` (`SPEC_34_NAMES`: the name; `SPEC_VALUES`: the key; `test_ordered_pairs_are_ordered`: `params.GRADER_SECOND_OPINION_CONFIDENCE < params.GRADER_LOW_CONFIDENCE`), `docs/superpowers/plans/learning-loop/HANDOFF-01.md`, `docs/superpowers/plans/learning-loop/LEDGER.md`

- [ ] **Step 1: Confirm the starting point.** `grep -rn "GRADER_RETRY_BELOW" backend --include=*.py` → exactly `backend/learning/params.py` and `backend/tests/test_learning_bkt.py` (HANDOFF-01: it has no reader). `grep -rn "GRADER_SECOND_OPINION_CONFIDENCE" backend --include=*.py` → nothing. Any other hit: rename it too and list it in the commit body.
- [ ] **Step 2: Rename** in the three places above, in one edit; value unchanged.
- [ ] **Step 3: Run** `cd backend && venv/bin/python -m pytest tests/test_learning_bkt.py tests/test_learning_loop_invariants.py -q && venv/bin/ruff check . && grep -rn "GRADER_RETRY_BELOW" backend --include=*.py | wc -l`
Expected: PKG-01's count unchanged (its Verify block: `N passed (N ≥ 20)`, the params `NAME = ` grep unchanged — a rename neither adds nor removes a name), `All checks passed!`, `0`.
- [ ] **Step 4: Reopen bookkeeping** — append to `HANDOFF-01.md` "Post-hoc changes": `PKG-05 <date>: renamed GRADER_RETRY_BELOW → GRADER_SECOND_OPINION_CONFIDENCE (value 0.4 unchanged; spec §13 A6; Known gaps (i)/(k) closed); tests/test_learning_bkt.py SPEC_34_NAMES / SPEC_VALUES / test_ordered_pairs_are_ordered updated in the same commit — commit <sha>`; append ledger row `| 01 | bkt-core | reopened | feat/learning-loop-05-grader-check-tool | <sha> | 0 (rename; tests/test_learning_bkt.py N passed) | PKG-05, <date>, tests/test_learning_bkt.py → N passed | HANDOFF-01.md |`.
- [ ] **Step 5: Commit**

```
git add backend/learning/params.py backend/tests/test_learning_bkt.py docs/superpowers/plans/learning-loop/HANDOFF-01.md docs/superpowers/plans/learning-loop/LEDGER.md
git commit -m "fix(learning-loop): PKG-01 — GRADER_RETRY_BELOW is GRADER_SECOND_OPINION_CONFIDENCE (spec §13 A6; one threshold, one name)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 1: Invariants — extend inv_06, inv_14 covers grade_answer, add inv_28

**Files:**
- Modify: `backend/tests/test_learning_loop_invariants.py`

**Interfaces:**
- Consumes: `agents.function_handlers_e2e` (import registers handlers), `agents._providers.AgentTask`, filesystem under `backend/agents/tools/`, `agents.tools.check.{grade_answer, CheckAnswer}` and `agents.grader.GradeResult` (inv_28; red until Task 4).
- Produces: `test_inv_06_*` now covers `"grader"` and `"grader_second"`; new `test_inv_14_tools_never_write_graph_tables`; new `test_inv_28_symmetric_missingness`.

- [ ] **Step 1: Extend inv_06.** PKG-04 wrote the test over the spec §8.6 series-task tuple intersected with `AgentTask`'s literals (grep `"check_items"` in the module; HANDOFF-04 names it). Adding `"grader"` and `"grader_second"` to `AgentTask` in Task 2 brings both under the check with no edit here — confirm the tuple holds both names. If PKG-04 hard-coded a single name instead, hoist the names into a module-level tuple `SERIES_AGENT_TASKS = ("check_items", "grader", "grader_second", "decision", "loop_tutor", "loop_tutor_lite", "loop_tutor_deep", "session_close")  # spec §8.6`, iterate the members that are in `typing.get_args(agents._providers.AgentTask)`, and assert each is in `agents._providers._FUNCTION_HANDLERS` after importing `agents.function_handlers_e2e` on a cold registry (`clear_function_handlers()` + `_ENV_HANDLERS_LOADED=False` + `sys.modules.pop`, restored in `finally` — the `tests/test_e2e_function_handlers.py::_clean_function_registry` posture).

- [ ] **Step 2: Add inv_14** at the end of the module:

```python
TOOLS_DIR = BACKEND / "agents" / "tools"
GRAPH_TABLE_CALLS = (
    'table("graph_nodes")',
    'table("graph_edges")',
    'table("node_mastery_events")',
    'table("learner_state")',
)


def test_inv_14_tools_never_write_graph_tables():
    """Series extension of spec §8.1, covering agents/tools/check.py::grade_answer:
    evidence accumulates on deps; only a route persists it through
    apply_graph_update. grade_answer is a route helper, not a tutor tool (A16)."""
    offenders = []
    for path in sorted(TOOLS_DIR.glob("*.py")):
        text = path.read_text()
        for needle in GRAPH_TABLE_CALLS:
            if needle in text:
                offenders.append(f"{path.name}: {needle}")
    assert not offenders, offenders
    check = (TOOLS_DIR / "check.py").read_text()
    assert "apply_graph_update" not in check, "check.py must not persist evidence"
    assert "from db.connection import" not in check, "check.py must not touch Supabase"
    assert "RunContext" not in check and "Tool(" not in check, "grade_answer is not a tutor tool (A16)"
```

- [ ] **Step 3: Add inv_28 (outage half)** at the end of the module:

```python
def test_inv_28_symmetric_missingness(monkeypatch):
    """Spec §8.28 (A20/A22), outage half: with the grader unavailable, a correct
    and a wrong mc_reason attempt both record nothing — missingness never
    depends on the outcome. PKG-06b adds the STUDENT_DAILY_GRADES cap half."""
    import asyncio
    from types import SimpleNamespace

    from agents.grader import GradeResult
    import agents.tools.check as check
    from agents.deps import SaplingDeps

    reason_checks = []

    async def _unavailable(item, *, format, student_answer, deps):
        reason_checks.append(student_answer)
        return GradeResult(unavailable=True)

    monkeypatch.setattr(check, "grade", _unavailable)
    options = [SimpleNamespace(letter="A", text="right", wrong_key=""),
               SimpleNamespace(letter="B", text="wrong", wrong_key="w_1")]
    item = SimpleNamespace(id="ci-28", format="mc_reason", options=options, correct_option="A",
                           answer_kind="free", canonical_verified=False, question_hash="qh-28")
    for option in ("A", "B"):  # the correct option, then a wrong one
        deps = SaplingDeps(user_id="u1", course_id="c1", supabase=None, request_id="r1",
                           session_id="s1", feature="tutor", learning_loop=True)
        answer = check.CheckAnswer(question_hash="qh-28", selected_option=option, reason="because")
        out = asyncio.run(check.grade_answer(item, answer, deps=deps, node_id="n-28"))
        assert out.unavailable is True and out.evidence is None, option
        assert deps.pending_evidence == [], option
    assert len(reason_checks) == 2, "the reason check must run for BOTH outcomes"
    # A numeric item with a VERIFIED key: a clear mismatch and a match both record nothing
    # (the A22 numeric gate runs only after the grader returned).
    numeric = SimpleNamespace(id="ci-28n", format="free", options=None, correct_option=None,
                              answer_kind="numeric", canonical_answer="9.81", tolerance=0.01,
                              canonical_verified=True, question_hash="qh-28n")
    for text in ("12.5", "9.81"):
        deps = SaplingDeps(user_id="u1", course_id="c1", supabase=None, request_id="r1",
                           session_id="s1", feature="tutor", learning_loop=True)
        out = asyncio.run(check.grade_answer(numeric, check.CheckAnswer(question_hash="qh-28n", answer_text=text),
                                             deps=deps, node_id="n-28"))
        assert out.unavailable is True and deps.pending_evidence == [], text
```

- [ ] **Step 4: Run**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -v -k "inv_06 or inv_14 or inv_28"`
Expected: `test_inv_06` PASS (the grader slots are not `AgentTask` literals yet — Task 2 adds them and turns it red, Task 3 green); `test_inv_14` PASS; `test_inv_28` FAIL — `ImportError: cannot import name 'GradeResult' from 'agents.grader'` (Task 4 turns it green). `graph_read.py` reads `table("graph_nodes")` with `.select` — if inv_14 fails on it, narrow `GRAPH_TABLE_CALLS` to lines that also contain `.insert(`/`.update(`/`.upsert(`/`.delete(` and record a deviation; never weaken the `check.py` assertions.

- [ ] **Step 5: Commit** (red is expected; Task 4 turns inv_28 green)

```
git add backend/tests/test_learning_loop_invariants.py
git commit -m "test(learning-loop): PKG-05 — inv_06 covers both grader slots; inv_14 covers grade_answer; inv_28 outage half

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 2: Grader agent (+ the `grader_second` slot)

**Files:**
- Modify: `backend/agents/__init__.py` (`GRADER_LIMITS` + `__all__`), `backend/agents/_providers.py` (`AgentTask`, `_DEFAULTS`), `backend/learning/params.py` (only the names the table marks "add" / "add if absent" / †), `backend/tests/test_agent_output_schemas.py` (`EXPECTED_STRUCTURED_AGENTS` += `"grader_agent"`)
- Replace stub: `backend/agents/grader.py`
- Test: `backend/tests/test_learning_check_tool.py` (grader section)

**Interfaces:**
- Consumes: `agents._providers.model_for("grader")` / `model_for("grader_second")`, `agents.usage.record_agent_usage`, `learning.params.{GRADER_LOW_CONFIDENCE, GRADER_SECOND_OPINION_CONFIDENCE, GRADER_SECOND_OPINION_SLOT, GRADER_HINT_MAX_CHARS, FEEDBACK_HINT_MAX_SENTENCES}`.
- Produces: `agents.grader.{GraderOutput, GradeResult, grader_agent, build_grader_message, parse_item_results, grade}`; `agents.GRADER_LIMITS`; `AgentTask` literals `"grader"`, `"grader_second"`.

- [ ] **Step 1: Write the failing tests** — replace the stub `backend/tests/test_learning_check_tool.py` with this module. It grows in Tasks 3–5; keep the helpers at the top.

```python
"""PKG-05: grader agent (+ grader_second) + grade_answer + flush_pending.

Hermetic: the grader agent runs on a FunctionModel; grade_answer's one seam
(the module-level `grade`) is stubbed; apply_graph_update is a spy. Nothing
here may touch table() for a graph table."""
from __future__ import annotations

import asyncio
import re
from types import SimpleNamespace

import pytest
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from agents import GRADER_LIMITS
from agents.deps import SaplingDeps
from learning.params import (
    GRADER_LOW_CONFIDENCE,
    GRADER_SECOND_OPINION_CONFIDENCE,
    GRADER_SECOND_OPINION_SLOT,
    RUNG_ASSISTED_MAX,
    RUNG_NO_CREDIT_MIN,
    WEIGHT_ASSISTED,
    WEIGHT_LOW_CONFIDENCE,
    WEIGHT_SAME_SESSION_RECHECK,
)

REFERENCE = "The base case stops the recursion; without it the stack grows until overflow."
NODE = "node-recursion"


def _item(**over):
    """A decrypted CheckItem stand-in (A2 keys, A22 columns)."""
    base = dict(
        id="ci-1",
        course_id="c1",
        concept_key="recursion",
        format="free",
        difficulty=1,
        prompt="Why does every recursive function need a base case?",
        reference_answer=REFERENCE,
        rubric=[{"id": "r1", "text": "names the base case"}, {"id": "r2", "text": "explains unbounded growth"}],
        common_wrong=[{"key": "w_loop", "text": "confuses recursion with a loop"}],
        options=None,
        correct_option=None,
        answer_kind="free",
        canonical_answer=None,
        tolerance=None,
        canonical_verified=False,
        stepwise=False,
        question_hash="qh-1",
    )
    base.update(over)
    return SimpleNamespace(**base)


def _mc_item(**over):
    options = [SimpleNamespace(letter=letter, text=text, wrong_key=key) for letter, text, key in (
        ("A", "It stops the recursion", ""),
        ("B", "It makes recursion faster", "w_speed"),
        ("C", "Recursion is a loop that ends on its own", "w_loop"),
    )]
    base = dict(format="mc_reason", options=options, correct_option="A",
                common_wrong=[{"key": "w_loop", "text": "confuses recursion with a loop"},
                              {"key": "w_speed", "text": "says the base case is only for speed"}])
    base.update(over)
    return _item(**base)


def _numeric_item(**over):
    base = dict(answer_kind="numeric", canonical_answer="9.81", tolerance=0.01, canonical_verified=True)
    base.update(over)
    return _item(**base)


def _deps(**over) -> SaplingDeps:
    kw = dict(user_id="u1", course_id="c1", supabase=None, request_id="r1",
              session_id="s1", feature="tutor", learning_loop=True)
    kw.update(over)
    return SaplingDeps(**kw)


def _scripted_grader(outputs: list[dict]):
    """A FunctionModel that emits each dict in turn through the output tool."""
    calls = {"n": 0}

    def handler(messages, info):
        payload = outputs[min(calls["n"], len(outputs) - 1)]
        calls["n"] += 1
        return ModelResponse(parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=payload)])

    return FunctionModel(handler), calls


def _good(conf: float = 0.9) -> dict:
    return {"item_results": ["r1:yes", "r2:yes"], "confidence": conf,
            "matched_wrong_key": "", "feedback_hint": "Think about what stops the calls."}


def _partial(conf: float = 0.9) -> dict:
    return {**_good(conf), "item_results": ["r1:yes", "r2:no"], "matched_wrong_key": "w_loop"}


# ── grader agent ──────────────────────────────────────────────────────────


def test_build_grader_message_has_every_section():
    from agents.grader import build_grader_message

    text = build_grader_message(_item(), format="free", student_answer="It stops the calls.")
    assert "QUESTION:" in text and REFERENCE in text and "FORMAT: free" in text
    assert re.search(r"^RUBRIC ITEM r1:", text, re.M) and re.search(r"^RUBRIC ITEM r2:", text, re.M)
    assert re.search(r"^COMMON WRONG REASON w_loop:", text, re.M) and text.rstrip().endswith("It stops the calls.")
    assert GRADER_LIMITS.tool_calls_limit == 0


def test_parse_item_results_is_strict():
    from agents.grader import parse_item_results

    got = parse_item_results(["r1:yes", "r2:NO", "r9:yes", "garbage"], ["r1", "r2", "r3"])
    assert got == {"r1": True, "r2": False, "r3": False}


def test_grade_returns_all_yes_and_records_usage(monkeypatch):
    import agents.grader as g

    model, calls = _scripted_grader([_good()])
    recorded = []
    monkeypatch.setattr(g, "record_agent_usage", lambda r, **kw: recorded.append(kw) or r)
    with g.grader_agent.override(model=model):
        res = asyncio.run(g.grade(_item(), format="free", student_answer="x", deps=_deps()))
    assert res.unavailable is False and res.all_yes is True
    assert res.item_results == {"r1": True, "r2": True}
    assert res.low_confidence is False and res.backend == "gemini"
    assert calls["n"] == 1
    assert recorded == [{"feature": "tutor", "task": "grader", "user_id": "u1"}]


def test_grade_flags_low_confidence(monkeypatch):
    import agents.grader as g

    conf = (GRADER_SECOND_OPINION_CONFIDENCE + GRADER_LOW_CONFIDENCE) / 2
    model, _ = _scripted_grader([_partial(conf)])
    monkeypatch.setattr(g, "record_agent_usage", lambda r, **kw: r)
    with g.grader_agent.override(model=model):
        res = asyncio.run(g.grade(_item(), format="free", student_answer="x", deps=_deps()))
    assert res.low_confidence is True and res.all_yes is False
    assert res.matched_wrong_key == "w_loop" and res.backend == "gemini"


def test_grade_second_opinion_then_unavailable(monkeypatch):
    import agents.grader as g

    low = GRADER_SECOND_OPINION_CONFIDENCE / 2
    model, calls = _scripted_grader([_good(low), _good(low)])
    monkeypatch.setattr(g, "record_agent_usage", lambda r, **kw: r)
    monkeypatch.setattr(g, "model_for", lambda slot: model)  # the second run's per-run model
    with g.grader_agent.override(model=model):
        res = asyncio.run(g.grade(_item(), format="free", student_answer="x", deps=_deps()))
    assert calls["n"] == 2
    assert res.unavailable is True


def test_grade_second_opinion_runs_on_grader_second_slot(monkeypatch):
    """A22: the second call is the SAME agent and message on another model,
    thinking off, with its own usage row; its verdict is marked gemini_second."""
    import agents.grader as g

    seen = []

    async def _run(message, **kw):
        seen.append((message, kw))
        conf = GRADER_SECOND_OPINION_CONFIDENCE / 2 if len(seen) == 1 else 0.9
        return SimpleNamespace(output=g.GraderOutput(**_good(conf)))

    tasks = []
    monkeypatch.setattr(g.grader_agent, "run", _run)
    monkeypatch.setattr(g, "model_for", lambda slot: f"model:{slot}")
    monkeypatch.setattr(g, "record_agent_usage", lambda r, **kw: tasks.append(kw["task"]) or r)
    res = asyncio.run(g.grade(_item(), format="free", student_answer="x", deps=_deps()))
    (first_msg, first_kw), (second_msg, second_kw) = seen
    assert first_msg == second_msg and "model" not in first_kw
    assert second_kw["model"] == f"model:{GRADER_SECOND_OPINION_SLOT}"
    assert second_kw["model_settings"] == g._SECOND_OPINION_SETTINGS
    assert first_kw["usage_limits"] is GRADER_LIMITS and second_kw["usage_limits"] is GRADER_LIMITS
    assert tasks == ["grader", GRADER_SECOND_OPINION_SLOT]
    assert res.unavailable is False and res.backend == "gemini_second" and res.confidence == 0.9


@pytest.mark.parametrize("exc", [UsageLimitExceeded("budget"), UnexpectedModelBehavior("garbage")])
def test_grade_degrades_honestly(monkeypatch, caplog, exc):
    import agents.grader as g

    async def _boom(*a, **k):
        raise exc

    monkeypatch.setattr(g.grader_agent, "run", _boom)
    with caplog.at_level("WARNING"):
        res = asyncio.run(g.grade(_item(), format="free", student_answer="x", deps=_deps()))
    assert res.unavailable is True
    assert any("grader unavailable" in r.getMessage() for r in caplog.records)
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_check_tool.py -v -k "grader or grade or parse or build"`
Expected: ERROR at import — `ImportError: cannot import name 'GRADER_LIMITS' from 'agents'`.

- [ ] **Step 3: Implement**

`backend/agents/__init__.py`, after `CONTINUATION_LIMITS`:
```python
# Learning loop PKG-05 (spec §3.4): the rubric grader runs as its OWN agent
# call from agents/tools/check.py::grade_answer (a route helper, A16), charged
# via record_agent_usage(task="grader" / "grader_second"), never against
# TUTOR_LIMITS. Both UsageLimitExceeded and UnexpectedModelBehavior degrade to
# the same `unavailable`, so a request limit below WORKER_LIMITS' 1 + 2-retry
# ladder costs no diagnosability. The second opinion is a separate run with
# its own GRADER_LIMITS.
GRADER_LIMITS = UsageLimits(
    request_limit=2,
    tool_calls_limit=0,
    total_tokens_limit=20_000,
)
```
and add `"GRADER_LIMITS"` to `__all__`.

`backend/agents/_providers.py`: add `"grader", "grader_second"` to `AgentTask` (after PKG-04's `"check_items"`) and to `_DEFAULTS`, each with a one-line comment:
```python
    # Learning loop grader (PKG-05): short per-item binary judgments → lite tier (spec §2).
    "grader": "gemini-2.5-flash-lite",
    # One second opinion on a DIFFERENT model, same agent and prompt (spec §3.5, A22);
    # thinking is pinned off per run in agents/grader.py.
    "grader_second": "gemini-2.5-flash",
```

`backend/learning/params.py`: grep each Named-constants name; add the missing ones beside the other `GRADER_*`/`WEIGHT_*` rows with a one-line comment citing the spec § or `†`. `GRADER_SECOND_OPINION_SLOT = "grader_second"  # spec §3.5, A22` is new. `backend/tests/test_agent_output_schemas.py`: add `"grader_agent"` to `EXPECTED_STRUCTURED_AGENTS` (frozen roster; `retries=2` satisfies the bounded-retry pin).

`backend/agents/grader.py`:
```python
"""Rubric grader for the learning loop (PKG-05; spec §2, §3.4, §3.5).

Sees the stored reference answer and judges each rubric item yes/no. Never
solves the problem, never restates the key. Runs as its own agent call from
`agents/tools/check.py::grade_answer` (the route helper, spec §13 A16) under
GRADER_LIMITS and is charged to the request through record_agent_usage. One
second opinion runs on the `grader_second` slot: same agent, same prompt, a
per-run model (A22).

Exactly one system prompt and one Agent (spec §8.12).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Literal

from google.genai.types import ThinkingConfig
from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.models.google import GoogleModelSettings

from agents import GRADER_LIMITS
from agents._providers import model_for
from agents.deps import SaplingDeps
from agents.usage import record_agent_usage
from learning.params import (
    FEEDBACK_HINT_MAX_SENTENCES,
    GRADER_HINT_MAX_CHARS,
    GRADER_LOW_CONFIDENCE,
    GRADER_SECOND_OPINION_CONFIDENCE,
    GRADER_SECOND_OPINION_SLOT,
)

logger = logging.getLogger("sapling.agents.grader")

# spec §3.5 slot table: grader_second runs with thinking off. Flash accepts
# thinking_budget=0 (unlike Pro) — the agents/flashcard.py shape.
_SECOND_OPINION_SETTINGS = GoogleModelSettings(
    google_thinking_config=ThinkingConfig(thinking_budget=0),
)


class GraderOutput(BaseModel):
    """Flat output (agents/__init__.py schema budget)."""

    item_results: list[str] = Field(
        description='One entry per rubric item, exactly "<rubric_id>:yes" or "<rubric_id>:no".'
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Your confidence in the whole judgment, 0 to 1.")
    matched_wrong_key: str = Field(
        default="",
        description="The COMMON WRONG REASON key the student's reasoning matches, or an empty string.",
    )
    feedback_hint: str = Field(
        max_length=GRADER_HINT_MAX_CHARS,
        description="A short hint for the tutor to adapt. Never the answer, never the reference.",
    )


@dataclass
class GradeResult:
    """Code-side result of grade(); `unavailable=True` is the ADR 0024 degrade.
    `backend` names the run whose verdict is used (A22 provenance)."""

    unavailable: bool = False
    item_results: dict[str, bool] = field(default_factory=dict)
    all_yes: bool = False
    confidence: float = 0.0
    matched_wrong_key: str = ""
    feedback_hint: str = ""
    low_confidence: bool = False
    backend: Literal["gemini", "gemini_second"] | None = None


_SYSTEM_PROMPT = (
    "You grade one student answer against a stored reference answer and a rubric. "
    "You receive the question, the reference answer, the rubric items, the common "
    "wrong reasons, the answer format, and the student's answer.\n\nRules:\n"
    "- Judge EVERY rubric item strictly: yes only if the student's answer clearly "
    "satisfies it; otherwise no. When unsure, answer no and lower your confidence. "
    "Strictness is the safer error.\n"
    "- Never solve the problem yourself. Compare against the reference only.\n"
    "- Never restate, quote, paraphrase, or hint at the reference answer in "
    "feedback_hint. The hint names what to reconsider, not what the answer is.\n"
    f"- feedback_hint is at most {FEEDBACK_HINT_MAX_SENTENCES} sentences.\n"
    "- matched_wrong_key: the key of the common wrong reason the student's reasoning "
    "matches; otherwise an empty string.\n"
    "- For format mc_reason grade the REASON against the rubric; the option is checked in code.\n"
    "- item_results: exactly one entry per rubric item, formatted <rubric_id>:yes or <rubric_id>:no."
)
_PROMPT_HASH = hashlib.sha256(_SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]

grader_agent = Agent[SaplingDeps, GraderOutput](
    model=model_for("grader"),
    deps_type=SaplingDeps,
    output_type=GraderOutput,
    retries=2,  # #153 output-validation budget; tool-less so retries= is that budget
    system_prompt=_SYSTEM_PROMPT,
    metadata={"prompt_version": _PROMPT_HASH, "agent": "grader"},
)


def build_grader_message(item, *, format: str, student_answer: str) -> str:
    """The single user message. Line shapes are load-bearing: the function-mode
    handler regexes `^RUBRIC ITEM <id>:` to script per-item results."""
    lines = ["QUESTION:", item.prompt, "", "REFERENCE ANSWER (never reveal):", item.reference_answer, ""]
    for r in item.rubric:
        lines.append(f"RUBRIC ITEM {r['id']}: {r['text']}")
    lines.append("")
    for w in item.common_wrong:
        lines.append(f"COMMON WRONG REASON {w['key']}: {w['text']}")
    lines += ["", f"FORMAT: {format}", "STUDENT ANSWER:", student_answer]
    return "\n".join(lines)


def parse_item_results(entries: list[str], rubric_ids: list[str]) -> dict[str, bool]:
    """Strict: a missing or malformed id is False; ids outside the rubric are dropped."""
    seen: dict[str, bool] = {}
    for entry in entries:
        rid, sep, verdict = str(entry).partition(":")
        if not sep:
            continue
        seen[rid.strip()] = verdict.strip().lower() == "yes"
    return {rid: seen.get(rid, False) for rid in rubric_ids}


async def _run_once(message: str, deps: SaplingDeps, *, second_opinion: bool = False) -> GraderOutput:
    if second_opinion:  # A22: another model, same agent and prompt, own limits and usage row
        result = await grader_agent.run(
            message,
            deps=deps,
            usage_limits=GRADER_LIMITS,
            model=model_for(GRADER_SECOND_OPINION_SLOT),
            model_settings=_SECOND_OPINION_SETTINGS,
        )
    else:
        result = await grader_agent.run(message, deps=deps, usage_limits=GRADER_LIMITS)
    task = GRADER_SECOND_OPINION_SLOT if second_opinion else "grader"
    record_agent_usage(result, feature=deps.feature, task=task, user_id=deps.user_id)
    return result.output


async def grade(item, *, format: str, student_answer: str, deps: SaplingDeps) -> GradeResult:
    """Grade one answer. Honest degrade (ADR 0024): budget or behaviour failure →
    GradeResult(unavailable=True) + WARNING, never a second prompt stack. The
    single Gemini grader: PKG-05b wraps it without changing the prompt."""
    message = build_grader_message(item, format=format, student_answer=student_answer)
    rubric_ids = [r["id"] for r in item.rubric]
    backend = "gemini"
    try:
        out = await _run_once(message, deps)
        if out.confidence < GRADER_SECOND_OPINION_CONFIDENCE:
            out = await _run_once(message, deps, second_opinion=True)  # spec §3.4: ONE second opinion
            backend = "gemini_second"
            if out.confidence < GRADER_SECOND_OPINION_CONFIDENCE:
                logger.warning("grader unavailable for item %s: confidence below floor twice", item.id)
                return GradeResult(unavailable=True)
    except (UsageLimitExceeded, UnexpectedModelBehavior) as exc:
        logger.warning("grader unavailable for item %s: %s", item.id, exc)
        return GradeResult(unavailable=True)
    results = parse_item_results(out.item_results, rubric_ids)
    return GradeResult(
        item_results=results,
        all_yes=bool(results) and all(results.values()),
        confidence=out.confidence,
        matched_wrong_key=out.matched_wrong_key or "",
        feedback_hint=out.feedback_hint,
        low_confidence=out.confidence < GRADER_LOW_CONFIDENCE,
        backend=backend,
    )
```

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_check_tool.py tests/test_agent_output_schemas.py -q && venv/bin/ruff check .`
Expected: the grader tests pass; `test_agent_roster_is_frozen` and `test_output_schema_within_budget[grader_agent]` pass; `All checks passed!` `test_inv_06` is now red (both slots are `AgentTask` literals without a handler) — expected until Task 3.

- [ ] **Step 5: Commit**

```
git add backend/agents/__init__.py backend/agents/_providers.py backend/agents/grader.py backend/learning/params.py backend/tests/test_agent_output_schemas.py backend/tests/test_learning_check_tool.py
git commit -m "feat(learning-loop): PKG-05 — grader agent (flash-lite, flat rubric output, grader_second opinion, honest degrade)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 3: Function-mode handler for `grader` and `grader_second`

**Files:**
- Modify: `backend/agents/function_handlers_e2e.py`
- Test: `backend/tests/test_learning_check_tool.py` (handler section)

**Interfaces:**
- Consumes: `_last_user_prompt_text` (already in the module), `register_function_handler`.
- Produces: constants `E2E_GRADER_CORRECT_TOKEN`, `E2E_GRADER_CONFIDENCE`, `E2E_GRADER_HINT`; one handler registered for tasks `"grader"` and `"grader_second"`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_learning_check_tool.py`:

```python
# ── function-mode handler ─────────────────────────────────────────────────


@pytest.fixture
def _clean_registry(monkeypatch):
    """Cold seam, env-module lane (the test_e2e_function_handlers posture)."""
    import sys

    import agents._providers as providers

    providers.clear_function_handlers()
    monkeypatch.setattr(providers, "_ENV_HANDLERS_LOADED", False)
    sys.modules.pop("agents.function_handlers_e2e", None)
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv("SAPLING_FUNCTION_HANDLERS", "agents.function_handlers_e2e")
    yield
    providers.clear_function_handlers()
    sys.modules.pop("agents.function_handlers_e2e", None)


def test_e2e_grader_handler_all_yes_on_token(_clean_registry, monkeypatch):
    import agents.grader as g
    from agents._providers import model_for

    monkeypatch.setattr(g, "record_agent_usage", lambda r, **kw: r)
    with g.grader_agent.override(model=model_for("grader")):
        from agents.function_handlers_e2e import E2E_GRADER_CORRECT_TOKEN, E2E_GRADER_HINT

        yes = asyncio.run(g.grade(_item(), format="free",
                                  student_answer=f"answer {E2E_GRADER_CORRECT_TOKEN}", deps=_deps()))
        no = asyncio.run(g.grade(_item(), format="free", student_answer="a loop", deps=_deps()))
    assert yes.all_yes is True and yes.item_results == {"r1": True, "r2": True}
    assert yes.feedback_hint == E2E_GRADER_HINT and yes.low_confidence is False
    assert no.unavailable is False and no.item_results == {"r1": False, "r2": False}


def test_e2e_grader_handler_serves_both_slots(_clean_registry, monkeypatch):
    """Invariant 6: the grader_second slot has the same fixed handler."""
    import agents.grader as g
    from agents._providers import model_for

    monkeypatch.setattr(g, "record_agent_usage", lambda r, **kw: r)
    for slot in ("grader", GRADER_SECOND_OPINION_SLOT):
        with g.grader_agent.override(model=model_for(slot)):
            from agents.function_handlers_e2e import E2E_GRADER_CORRECT_TOKEN

            res = asyncio.run(g.grade(_item(), format="free",
                                      student_answer=f"x {E2E_GRADER_CORRECT_TOKEN}", deps=_deps()))
        assert res.unavailable is False and res.all_yes is True, slot
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_check_tool.py -v -k e2e_grader`
Expected: FAIL — `UnregisteredHandlerError: SAPLING_MODEL_MODE=function but no handler is registered for task 'grader'`.

- [ ] **Step 3: Implement** — append to `backend/agents/function_handlers_e2e.py` (add `import re` at the top):

```python
# ── Learning loop grader (PKG-05) ───────────────────────────────────────────
#
# grade_answer (a route helper, spec §13 A16) runs grader_agent as its OWN
# call, so the E2E lane needs a handler — for both slots: the second opinion
# runs the same agent on the "grader_second" slot (A22). Content-driven in
# exactly one way: a student answer containing E2E_GRADER_CORRECT_TOKEN grades
# every rubric item yes, anything else every item no. Rubric ids come off the
# prompt's `RUBRIC ITEM <id>:` lines (agents/grader.py::build_grader_message),
# so any seeded item works. E2E_GRADER_CONFIDENCE sits above the second-opinion
# floor, so the second slot never fires in E2E. Emits through the OUTPUT tool →
# the real schema validates. Contract: tests/test_learning_check_tool.py;
# PKG-13's learn-loop.spec.ts types the token.

E2E_GRADER_CORRECT_TOKEN = "E2E_GRADER_CORRECT"
E2E_GRADER_CONFIDENCE = 0.95
E2E_GRADER_HINT = "[e2e-function-model] Deterministic grader hint: check the base case first."

_RUBRIC_ID_RE = re.compile(r"^RUBRIC ITEM (\S+):", re.M)


def _grader_handler(messages, info) -> ModelResponse:
    text = _last_user_prompt_text(messages)
    verdict = "yes" if E2E_GRADER_CORRECT_TOKEN in text else "no"
    args = {
        "item_results": [f"{rid}:{verdict}" for rid in _RUBRIC_ID_RE.findall(text)],
        "confidence": E2E_GRADER_CONFIDENCE,
        "matched_wrong_key": "",
        "feedback_hint": E2E_GRADER_HINT,
    }
    return ModelResponse(parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=args)])


register_function_handler("grader", _grader_handler)
register_function_handler("grader_second", _grader_handler)
```

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_check_tool.py tests/test_learning_loop_invariants.py tests/test_e2e_function_handlers.py -q && venv/bin/ruff check .`
Expected: all passed except `test_inv_28` (red until Task 4); inv_06 now green; `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/agents/function_handlers_e2e.py backend/tests/test_learning_check_tool.py
git commit -m "feat(learning-loop): PKG-05 — function-mode grader handler for both slots (E2E_GRADER_*)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 4: `grade_answer` — the route helper

**Files:**
- Replace stub: `backend/agents/tools/check.py`
- Test: `backend/tests/test_learning_check_tool.py` (grade_answer section)

**Interfaces:**
- Consumes: `agents.grader.{grade, GradeResult}`, `learning.evidence.{Evidence, evidence_weight}` (PKG-03; `evidence_weight(ev)` per HANDOFF-03 — do not write a second weight function), `learning.params.{RUNG_ASSISTED_MIN, RUNG_ASSISTED_MAX}`, `learning.checks.CheckItem` (typing only).
- Produces: `agents.tools.check.{CheckAnswer, GradeOutcome, CHANNEL_FOR_FORMAT, grade_answer}` with the canonical signature `async def grade_answer(item: CheckItem, answer: CheckAnswer, *, deps: SaplingDeps, node_id: str, max_rung: int = 0, same_session_recheck: bool = False) -> GradeOutcome` (PKG-07/08/10/12/14 take it from HANDOFF-05).

- [ ] **Step 1: Write the failing tests** — append:

```python
# ── grade_answer (the route helper, A16) ──────────────────────────────────


def _result(**over):
    from agents.grader import GradeResult

    base = dict(item_results={"r1": True, "r2": True}, all_yes=True, confidence=0.9,
                feedback_hint="Think about what stops the calls.", backend="gemini")
    base.update(over)
    return GradeResult(**base)


def _answer(**over):
    from agents.tools.check import CheckAnswer

    kw = dict(question_hash="qh-1", answer_text="It stops the calls.")
    kw.update(over)
    return CheckAnswer(**kw)


@pytest.fixture
def check(monkeypatch):
    """grade_answer with its one seam stubbed: the grader."""
    import agents.tools.check as c

    state = {"item": _item(), "result": _result(), "grade_calls": []}

    async def _grade(item, *, format, student_answer, deps):
        state["grade_calls"].append((format, student_answer))
        return state["result"]

    monkeypatch.setattr(c, "grade", _grade)
    return c, state


def _run(check, deps, answer, **kw):
    c, state = check
    return asyncio.run(c.grade_answer(state["item"], answer, deps=deps, node_id=NODE, **kw))


def test_grade_answer_is_inert_when_learning_loop_false(check):
    _, state = check
    deps = _deps(learning_loop=False)
    out = _run(check, deps, _answer())
    assert out.unavailable is True and out.evidence is None and out.correct is None
    assert deps.pending_evidence == [] and state["grade_calls"] == []


def test_idk_is_incorrect_on_the_items_channel_without_grader(check):
    _, state = check
    deps = _deps()
    out = _run(check, deps, _answer(idk=True, answer_text=""), max_rung=1)
    assert state["grade_calls"] == []
    [ev] = deps.pending_evidence
    assert ev == out.evidence and out.correct is False and out.unavailable is False
    assert ev["channel"] == "free_response" and ev["idk"] is True and ev["correct"] is False
    assert ev["weight"] == 1.0 and ev["grader_backend"] is None and ev["max_rung"] == 1
    assert ev["node_id"] == NODE and ev["check_item_id"] == "ci-1"
    assert ev["question_hash"] == "qh-1" and ev["session_id"] == "s1"


@pytest.mark.parametrize("fmt,channel", [("free", "free_response"), ("teachback", "teachback_llm"), ("mc_reason", "mc_reasoned")])
def test_channel_mapping(check, fmt, channel):
    _, state = check
    state["item"] = _mc_item() if fmt == "mc_reason" else _item(format=fmt)
    deps = _deps()
    _run(check, deps, _answer(selected_option="a", reason="because it stops"))
    [ev] = deps.pending_evidence
    assert ev["channel"] == channel and ev["correct"] is True


def test_mc_reason_reason_check_runs_for_both_outcomes(check):
    _, state = check
    state["item"] = _mc_item()
    for option in ("A", "C"):
        _run(check, _deps(), _answer(selected_option=option, reason="because it stops"))
    assert state["grade_calls"] == [
        ("mc_reason", "Selected option: A\nReason: because it stops"),
        ("mc_reason", "Selected option: C\nReason: because it stops"),
    ]


def test_mc_reason_wrong_option_is_incorrect_even_with_yes_rubric(check):
    _, state = check
    state["item"] = _mc_item()
    deps = _deps()
    out = _run(check, deps, _answer(selected_option="C", reason="because"))
    [ev] = deps.pending_evidence
    assert out.correct is False and ev["correct"] is False and ev["channel"] == "mc_reasoned"


def test_mc_reason_right_option_with_failed_reason_is_incorrect(check):
    _, state = check
    state["item"] = _mc_item()
    state["result"] = _result(item_results={"r1": True, "r2": False}, all_yes=False)
    deps = _deps()
    out = _run(check, deps, _answer(selected_option="A", reason="it just is"))
    [ev] = deps.pending_evidence
    assert out.correct is False and ev["correct"] is False


def test_wrong_key_only_when_the_reason_matches_the_chosen_option(check):
    _, state = check
    state["item"] = _mc_item()
    state["result"] = _result(item_results={"r1": False, "r2": False}, all_yes=False, matched_wrong_key="w_loop")
    matched = _run(check, _deps(), _answer(selected_option="C", reason="it loops until done"))    # C → w_loop
    unmatched = _run(check, _deps(), _answer(selected_option="B", reason="it loops until done"))  # B → w_speed
    right_option = _run(check, _deps(), _answer(selected_option="A", reason="it loops until done"))
    assert matched.wrong_key == "w_loop" and matched.matched_wrong_key == "w_loop"
    assert unmatched.wrong_key is None and unmatched.matched_wrong_key == "w_loop"
    assert right_option.correct is False and right_option.wrong_key == "w_loop"  # the reason matched (§3.3)


@pytest.mark.parametrize("fmt,option", [("mc_reason", "A"), ("mc_reason", "C"), ("free", None)])
def test_symmetric_missingness_when_grader_unavailable(check, fmt, option):
    from agents.grader import GradeResult

    _, state = check
    state["item"] = _mc_item() if fmt == "mc_reason" else _item()
    state["result"] = GradeResult(unavailable=True)
    deps = _deps()
    out = _run(check, deps, _answer(selected_option=option, reason="because"))
    assert out.unavailable is True and out.correct is None and out.evidence is None
    assert deps.pending_evidence == [] and len(state["grade_calls"]) == 1


def test_numeric_clear_mismatch_is_deterministic_incorrect(check):
    _, state = check
    state["item"] = _numeric_item()
    state["result"] = _result()  # the grader said yes; the verified key overrides it
    deps = _deps()
    out = _run(check, deps, _answer(answer_text="12.5"))
    assert len(state["grade_calls"]) == 1, "the grader runs for both numeric outcomes (inv 28)"
    [ev] = deps.pending_evidence
    assert ev["correct"] is False and ev["grader_backend"] == "deterministic"
    assert out.correct is False and out.grader_backend == "deterministic" and out.confidence is None


@pytest.mark.parametrize("answer_text", ["12.5", "9.81"])  # a clear mismatch, then a match
def test_numeric_item_under_grader_outage_records_neither_outcome(check, answer_text):
    """Invariant 28: the numeric gate never records one outcome while the other is dropped."""
    _, state = check
    state["item"] = _numeric_item()
    state["result"] = _result(unavailable=True)
    deps = _deps()
    out = _run(check, deps, _answer(answer_text=answer_text))
    assert out.unavailable is True and out.evidence is None and deps.pending_evidence == []


@pytest.mark.parametrize("answer_text,over", [
    ("9.815", {}),                              # within tolerance → the rubric grader decides
    ("about nine point eight", {}),             # parse failure → the rubric grader
    ("12.5", {"canonical_verified": False}),    # unverified key → the rubric grader
])
def test_numeric_gate_never_issues_correct(check, answer_text, over):
    _, state = check
    state["item"] = _numeric_item(**over)
    state["result"] = _result(item_results={"r1": False, "r2": False}, all_yes=False)
    deps = _deps()
    out = _run(check, deps, _answer(answer_text=answer_text))
    assert len(state["grade_calls"]) == 1 and out.grader_backend == "gemini"
    assert out.correct is False  # the grader said no; code never turned a match into "correct"


def test_grader_backend_values(check):
    _, state = check
    deps = _deps()
    _run(check, deps, _answer())
    state["result"] = _result(backend="gemini_second")
    _run(check, deps, _answer())
    _run(check, deps, _answer(idk=True))
    assert [ev["grader_backend"] for ev in deps.pending_evidence] == ["gemini", "gemini_second", None]


def test_unassisted_correct_is_full_weight(check):
    deps = _deps()
    _run(check, deps, _answer())
    [ev] = deps.pending_evidence
    assert ev["correct"] is True and ev["assisted"] is False and ev["weight"] == 1.0 and ev["max_rung"] == 0
    assert ev["confidence"] == 0.9


def test_assisted_rungs_halve_weight(check):
    deps = _deps()
    _run(check, deps, _answer(), max_rung=RUNG_ASSISTED_MAX)
    [ev] = deps.pending_evidence
    assert ev["assisted"] is True and ev["weight"] == WEIGHT_ASSISTED


def test_recheck_and_low_confidence_multiply(check):
    _, state = check
    state["result"] = _result(confidence=GRADER_LOW_CONFIDENCE / 2, low_confidence=True)
    deps = _deps()
    _run(check, deps, _answer(), max_rung=RUNG_ASSISTED_MAX, same_session_recheck=True)
    [ev] = deps.pending_evidence
    assert ev["weight"] == pytest.approx(WEIGHT_ASSISTED * WEIGHT_SAME_SESSION_RECHECK * WEIGHT_LOW_CONFIDENCE)
    assert ev["same_session_recheck"] is True


def test_low_confidence_weighs_both_outcomes(check):
    """A22: the reason check's confidence sets the weight of a correct AND a wrong answer."""
    _, state = check
    state["item"] = _mc_item()
    state["result"] = _result(confidence=GRADER_LOW_CONFIDENCE / 2, low_confidence=True)
    deps = _deps()
    _run(check, deps, _answer(selected_option="A", reason="because it stops"))
    _run(check, deps, _answer(selected_option="C", reason="because it stops"))
    right, wrong = deps.pending_evidence
    assert (right["correct"], wrong["correct"]) == (True, False)
    assert right["weight"] == wrong["weight"] == WEIGHT_LOW_CONFIDENCE
    assert right["confidence"] == wrong["confidence"] == GRADER_LOW_CONFIDENCE / 2


def test_correct_after_h4_plus_has_zero_weight_but_is_appended(check):
    deps = _deps()
    _run(check, deps, _answer(), max_rung=RUNG_NO_CREDIT_MIN)
    [ev] = deps.pending_evidence
    assert ev["correct"] is True and ev["weight"] == 0.0 and ev["max_rung"] == RUNG_NO_CREDIT_MIN


def test_wrong_after_h4_plus_keeps_standard_weight(check):
    _, state = check
    state["result"] = _result(item_results={"r1": True, "r2": False}, all_yes=False, matched_wrong_key="w_loop")
    deps = _deps()
    out = _run(check, deps, _answer(), max_rung=RUNG_NO_CREDIT_MIN + 1)
    [ev] = deps.pending_evidence
    assert ev["correct"] is False and ev["weight"] == 1.0 and out.wrong_key == "w_loop"


def test_pending_evidence_accumulates_across_calls(check):
    deps = _deps()
    _run(check, deps, _answer())
    _run(check, deps, _answer(), same_session_recheck=True)
    assert len(deps.pending_evidence) == 2
    assert deps.pending_evidence[1]["weight"] == WEIGHT_SAME_SESSION_RECHECK


def test_outcome_never_carries_the_reference(check):
    import dataclasses

    for answer in (_answer(), _answer(idk=True)):
        out = _run(check, _deps(), answer)
        assert REFERENCE not in repr(dataclasses.asdict(out))


def test_grade_answer_never_touches_db_tables(check, monkeypatch):
    """Spy on db.connection.table: grade_answer must not resolve ANY table."""
    import db.connection as dbconn

    names = []
    monkeypatch.setattr(dbconn, "table", lambda name, *a, **k: names.append(name) or SimpleNamespace())
    _run(check, _deps(), _answer())
    _run(check, _deps(), _answer(idk=True))
    assert names == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_check_tool.py -v`
Expected: the Task 2/3 tests pass; every `grade_answer` test ERRORs at setup — `AttributeError: <module 'agents.tools.check' …> has no attribute 'grade'`.

- [ ] **Step 3: Implement** `backend/agents/tools/check.py`:

```python
"""grade_answer — the single grading ROUTE helper (PKG-05; spec §13 A16, A22).

Turns one explicit student submission into one learning.evidence Evidence dict
on `deps.pending_evidence` and a code-side GradeOutcome. It is not a tutor
tool (A16): the check route (PKG-07), the probe (PKG-08), review (PKG-12) and
the post-test (PKG-14) call it. It NEVER persists: the calling route runs
learning.evidence.flush_pending once (spec §5, §8.1; inv_14). No db.connection
import here by design.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

from agents.deps import SaplingDeps
from agents.grader import grade
from learning.evidence import Evidence, evidence_weight
from learning.params import RUNG_ASSISTED_MAX, RUNG_ASSISTED_MIN

if TYPE_CHECKING:
    from learning.checks import CheckItem

CHANNEL_FOR_FORMAT: dict[str, str] = {
    "free": "free_response",
    "teachback": "teachback_llm",
    "mc_reason": "mc_reasoned",
}


class CheckAnswer(BaseModel):
    """One explicit submission (the A16 body fields). Flat by design."""

    question_hash: str
    answer_text: str = ""
    selected_option: str | None = None  # mc_reason: the letter chosen
    reason: str | None = None  # mc_reason: the one-sentence reason
    idk: bool = False  # explicit "I don't know" (A1)


@dataclass
class GradeOutcome:
    """Code-side verdict. `unavailable=True` → nothing was appended, for either
    outcome (A22, invariant 28). Never carries the reference answer."""

    correct: bool | None = None
    confidence: float | None = None
    feedback_hint: str = ""  # optional downstream: the A16 feedback turn writes student text
    matched_wrong_key: str | None = None  # the grader's reason match, as returned
    wrong_key: str | None = None  # what PKG-10 may record (A22 rule in _wrong_key)
    unavailable: bool = False
    grader_backend: Literal["deterministic", "gemini", "gemini_second", "jev"] | None = None
    evidence: dict | None = None  # the Evidence dict appended to deps.pending_evidence


def _norm(text: str | None) -> str:
    return " ".join((text or "").split()).casefold()


def _option_matches(selected: str | None, correct_option: str | None) -> bool:
    return bool(_norm(selected)) and _norm(selected) == _norm(correct_option)


def _parse_number(text: str | None) -> float | None:
    try:
        value = float((text or "").strip())
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _numeric_mismatch(item, answer: CheckAnswer) -> bool:
    """A22 numeric gate: True only for a clear mismatch against a VERIFIED key.
    A match, a parse failure or an unverified key → False (the rubric grader
    decides). It can only ever say "incorrect", never "correct"."""
    if item.answer_kind != "numeric" or not item.canonical_verified:
        return False
    got, want = _parse_number(answer.answer_text), _parse_number(item.canonical_answer)
    if got is None or want is None:
        return False
    return abs(got - want) > (item.tolerance or 0.0)


def _wrong_key(item, answer: CheckAnswer, *, correct: bool, matched: str | None) -> str | None:
    """A22: a key enters PKG-10's rule only when the student's reason matched it.
    An mc_reason wrong option carries its own key only when the grader matched
    that same key; the option → key map alone is a prior, never a record."""
    if correct or not matched:
        return None
    if item.format != "mc_reason" or _option_matches(answer.selected_option, item.correct_option):
        return matched
    chosen = next((o for o in item.options or [] if _norm(o.letter) == _norm(answer.selected_option)), None)
    return matched if chosen is not None and chosen.wrong_key == matched else None


def _record(deps: SaplingDeps, outcome: GradeOutcome, ev: Evidence) -> GradeOutcome:
    """Weight from the flags (PKG-03's evidence_weight: assisted, recheck, the
    grader's confidence for BOTH outcomes, zero after H4–H6), then append."""
    row = ev.model_copy(update={"weight": evidence_weight(ev)}).model_dump()
    deps.pending_evidence.append(row)
    outcome.evidence = row
    return outcome


async def grade_answer(
    item: CheckItem,
    answer: CheckAnswer,
    *,
    deps: SaplingDeps,
    node_id: str,
    max_rung: int = 0,
    same_session_recheck: bool = False,
) -> GradeOutcome:
    """Grade one explicit submission and append its Evidence to deps.pending_evidence.

    `item` is a decrypted CheckItem the caller loaded by `answer.question_hash`;
    `node_id` is the student's graph_nodes id for `item.concept_key` (the
    caller resolves it: items are course assets keyed per concept, A2).
    """
    if not deps.learning_loop:
        return GradeOutcome(unavailable=True)
    base = dict(
        node_id=node_id,
        channel=CHANNEL_FOR_FORMAT[item.format],
        assisted=RUNG_ASSISTED_MIN <= max_rung <= RUNG_ASSISTED_MAX,
        max_rung=max_rung,
        session_id=deps.session_id,
        check_item_id=item.id,
        question_hash=item.question_hash,
        same_session_recheck=same_session_recheck,
    )

    if answer.idk:  # A1: an incorrect observation on the item's channel; no grader call
        return _record(deps, GradeOutcome(correct=False), Evidence(idk=True, correct=False, **base))

    student_answer = answer.answer_text
    if item.format == "mc_reason":  # the reason check runs for BOTH option outcomes (A22)
        student_answer = f"Selected option: {answer.selected_option or ''}\nReason: {answer.reason or ''}"
    result = await grade(item, format=item.format, student_answer=student_answer, deps=deps)
    if result.unavailable:  # A22 / invariant 28: nothing for EITHER outcome
        return GradeOutcome(unavailable=True)

    correct = result.all_yes
    if item.format == "mc_reason":
        correct = correct and _option_matches(answer.selected_option, item.correct_option)
    matched = result.matched_wrong_key or None
    backend, confidence = result.backend, result.confidence
    if item.format != "mc_reason" and _numeric_mismatch(item, answer):
        # A22 numeric gate, AFTER the grader returned (it ran for both outcomes, so an
        # outage or the grade cap above recorded nothing for either — invariant 28).
        # It can only ever say "incorrect".
        correct, backend, confidence = False, "deterministic", None
    outcome = GradeOutcome(
        correct=correct,
        confidence=confidence,
        feedback_hint=result.feedback_hint,
        matched_wrong_key=matched,
        wrong_key=_wrong_key(item, answer, correct=correct, matched=matched),
        grader_backend=backend,
    )
    ev = Evidence(correct=correct, confidence=confidence, grader_backend=backend, **base)
    return _record(deps, outcome, ev)
```

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_check_tool.py tests/test_learning_loop_invariants.py -q && venv/bin/ruff check .`
Expected: all passed (inv_14 green with the real module; inv_28 now green); `All checks passed!`. If PKG-03's `Evidence` field set or `evidence_weight` signature differs from spec §5 / this prompt, follow HANDOFF-03 and record a Deviation; never edit the model beyond Task 0's field.

- [ ] **Step 5: Commit**

```
git add backend/agents/tools/check.py backend/tests/test_learning_check_tool.py
git commit -m "feat(learning-loop): PKG-05 — grade_answer: the route grading helper (A16/A22), never writes

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 5: `flush_pending` (reopens PKG-03)

**Files:**
- Modify: `backend/learning/evidence.py` (PKG-03's module — README "Touching an earlier package's code" applies: separate commit prefixed `fix(learning-loop): PKG-03 —`, ledger row `03 | reopened`, "Post-hoc changes" line in `HANDOFF-03.md`)
- Test: `backend/tests/test_learning_check_tool.py` (flush section)

**Interfaces:**
- Consumes: `services.graph_service.apply_graph_update` (local import).
- Produces: `learning.evidence.flush_pending(deps, course_id) -> list`. (`evidence_weight` is PKG-03's; do not add a second one.)

- [ ] **Step 1: Write the failing tests** — append:

```python
# ── flush_pending (route persistence contract) ────────────────────────────


def test_flush_pending_calls_apply_graph_update_once_and_clears(monkeypatch):
    import services.graph_service as gs
    from learning import evidence as ev

    calls = []
    monkeypatch.setattr(gs, "apply_graph_update", lambda uid, gu, cid=None: calls.append((uid, gu, cid)) or [{"concept": "x"}])
    deps = _deps()
    deps.pending_evidence.extend([{"node_id": "n1", "channel": "free_response", "correct": True},
                                  {"node_id": "n1", "channel": "free_response", "idk": True, "correct": False}])
    out = ev.flush_pending(deps, "c1")
    assert out == [{"concept": "x"}]
    assert len(calls) == 1
    uid, gu, cid = calls[0]
    assert uid == "u1" and cid == "c1" and set(gu) == {"evidence"} and len(gu["evidence"]) == 2
    assert deps.pending_evidence == []


def test_flush_pending_empty_is_a_noop(monkeypatch):
    import services.graph_service as gs
    from learning import evidence as ev

    monkeypatch.setattr(gs, "apply_graph_update", lambda *a, **k: pytest.fail("must not be called"))
    assert ev.flush_pending(_deps(), "c1") == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_check_tool.py -v -k flush`
Expected: FAIL — `AttributeError: module 'learning.evidence' has no attribute 'flush_pending'`.

- [ ] **Step 3: Implement** — append to `backend/learning/evidence.py` (keep everything PKG-03 and Task 0 wrote unchanged):

```python
def flush_pending(deps, course_id: str | None) -> list:
    """Persist `deps.pending_evidence` through the single graph writer, once.

    Called by the ROUTE after grade_answer (PKG-07's /check/answer, A16), never
    by grade_answer itself. Errors propagate; the list is cleared only after a
    successful write so the route can decide whether to retry or report.
    """
    if not deps.pending_evidence:
        return []
    # Local import: services.graph_service imports this module (PKG-03), so a
    # module-level import here would be circular.
    from services.graph_service import apply_graph_update

    changes = apply_graph_update(deps.user_id, {"evidence": list(deps.pending_evidence)}, course_id)
    deps.pending_evidence.clear()
    return changes
```

- [ ] **Step 4: Run PKG-03's tests, this module, invariants, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_evidence_apply.py tests/test_graph_service.py tests/test_learning_check_tool.py tests/test_learning_loop_invariants.py -q && venv/bin/ruff check .`
Expected: all passed (inv_01 and inv_02 unchanged — `evidence.py` is not in `PURE_MODULES`); `All checks passed!` PKG-03's `test_no_production_caller_passes_evidence_yet` must stay green: no route calls `flush_pending` in this package. If that guard flags `learning/evidence.py::flush_pending` itself, exempt exactly that function in the guard in this same reopen commit, record it in HANDOFF-03 Post-hoc changes, and leave retiring the guard to the package that adds the first route caller (PKG-07).

- [ ] **Step 5: Reopen bookkeeping** — append to `HANDOFF-03.md` "Post-hoc changes": `PKG-05 <date>: added learning/evidence.py::flush_pending — commit <sha>`; append ledger row `| 03 | evidence-state | reopened | feat/learning-loop-05-grader-check-tool | <sha> | +2 (in test_learning_check_tool.py) | PKG-05, <date>, tests/test_learning_evidence_apply.py → all passed | HANDOFF-03.md |`.

- [ ] **Step 6: Commit**

```
git add backend/learning/evidence.py backend/tests/test_learning_check_tool.py docs/superpowers/plans/learning-loop/HANDOFF-03.md docs/superpowers/plans/learning-loop/LEDGER.md
git commit -m "fix(learning-loop): PKG-03 — flush_pending: the route's one-call evidence persister (reopened by PKG-05)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 6: Eval dataset `tests/evals/grader.py`

**Files:**
- Create: `backend/tests/evals/grader.py`, `backend/tests/evals/cassettes/grader/*.json` (recorded)
- Modify: `backend/tests/evals/run_all.py` (`DATASETS` += `"grader"`), `backend/tests/evals/baselines.json` (`"grader"` block, written by the harness)

**Interfaces:**
- Consumes: `agents.grader.{grader_agent, GraderOutput, build_grader_message, parse_item_results}`, `_replay.{run_with_cassette, cli_main}`, `learning.params.LEAK_NGRAM`.
- Produces: dataset `grader` with gated evaluators `NoReferenceLeakEvaluator`, `RubricAgreementEvaluator`, `StrictOnWrongEvaluator`, `ConfidenceInRangeEvaluator`, plus the logged-only label `ConfidenceAgreementLabel` (spec §10: confidence vs gold agreement, for a later `GRADER_LOW_CONFIDENCE` calibration).

- [ ] **Step 1: Write the dataset**

```python
"""pydantic-evals cases for grader_agent (learning loop PKG-05; spec §10 rung 1).
    cd backend && SAPLING_EVAL_MODE=record|replay python tests/evals/grader.py
One (item, student answer) per case, gold per-rubric labels in metadata. Gates:
NoReferenceLeak (hint shares no LEAK_NGRAM-token window with the reference),
StrictOnWrong (a gold-wrong answer never comes back all-yes), ConfidenceInRange;
RubricAgreement is measured, not assumed 1.0. ConfidenceAgreementLabel is LOGGED,
never gated: a str result is a pydantic-evals label, so it never enters
baselines.json; it pairs confidence with gold agreement so GRADER_LOW_CONFIDENCE
can be calibrated later. Never hand-edit a case; add one on a miss.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).parent))

from pydantic import BaseModel
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Evaluator, EvaluatorContext

from _replay import cli_main, run_with_cassette
from agents.grader import GraderOutput, build_grader_message, grader_agent, parse_item_results
from learning.params import LEAK_NGRAM

GRADER_EVAL_MAX_CASES = 8


class GradeCase(BaseModel):
    """Case input: the item fields the grader sees plus the student's answer."""

    prompt: str
    reference_answer: str
    rubric: list[dict]
    common_wrong: list[dict]
    format: str
    student_answer: str


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _ngrams(tokens: list[str], n: int) -> set[tuple[str, ...]]:
    return {tuple(tokens[i : i + n]) for i in range(max(0, len(tokens) - n + 1))}


def _agreement(ctx: EvaluatorContext[GradeCase, GraderOutput]) -> float:
    gold: dict[str, bool] = (ctx.metadata or {}).get("gold", {})
    got = parse_item_results(ctx.output.item_results if ctx.output else [], list(gold))
    return sum(got[k] == v for k, v in gold.items()) / max(1, len(gold))


@dataclass
class NoReferenceLeakEvaluator(Evaluator[GradeCase, GraderOutput]):
    def evaluate(self, ctx: EvaluatorContext[GradeCase, GraderOutput]) -> float:
        ref = _ngrams(_tokens(ctx.inputs.reference_answer), LEAK_NGRAM)
        hint = _ngrams(_tokens(ctx.output.feedback_hint if ctx.output else ""), LEAK_NGRAM)
        return 0.0 if ref & hint else 1.0


@dataclass
class RubricAgreementEvaluator(Evaluator[GradeCase, GraderOutput]):
    def evaluate(self, ctx: EvaluatorContext[GradeCase, GraderOutput]) -> float:
        return _agreement(ctx)


@dataclass
class StrictOnWrongEvaluator(Evaluator[GradeCase, GraderOutput]):
    def evaluate(self, ctx: EvaluatorContext[GradeCase, GraderOutput]) -> float:
        gold: dict[str, bool] = (ctx.metadata or {}).get("gold", {})
        if all(gold.values()):
            return 1.0
        got = parse_item_results(ctx.output.item_results if ctx.output else [], list(gold))
        return 0.0 if all(got.values()) else 1.0


@dataclass
class ConfidenceInRangeEvaluator(Evaluator[GradeCase, GraderOutput]):
    def evaluate(self, ctx: EvaluatorContext[GradeCase, GraderOutput]) -> float:
        c = ctx.output.confidence if ctx.output else -1.0
        return 1.0 if 0.0 <= c <= 1.0 else 0.0


@dataclass
class ConfidenceAgreementLabel(Evaluator[GradeCase, GraderOutput]):
    """Logged, never gated (a str is a label, not a score)."""

    def evaluate(self, ctx: EvaluatorContext[GradeCase, GraderOutput]) -> str:
        c = ctx.output.confidence if ctx.output else -1.0
        return f"confidence={c:.2f} agreement={_agreement(ctx):.2f}"


_RECURSION = dict(
    prompt="Why does every recursive function need a base case?",
    reference_answer="The base case stops the recursion; without it each call makes another call and the stack grows until it overflows.",
    rubric=[{"id": "r1", "text": "says the base case stops the recursion"},
            {"id": "r2", "text": "explains that without it calls never end / stack overflows"}],
    common_wrong=[{"key": "w_loop", "text": "treats recursion as a loop that ends on its own"},
                  {"key": "w_speed", "text": "says the base case is only for speed"}],
)
_DERIV = dict(
    prompt="What does the derivative of a function at a point represent?",
    reference_answer="The instantaneous rate of change of the function at that point; geometrically, the slope of the tangent line there.",
    rubric=[{"id": "r1", "text": "rate of change / slope"},
            {"id": "r2", "text": "at a single point (instantaneous, tangent)"}],
    common_wrong=[{"key": "w_area", "text": "confuses derivative with area under the curve"},
                  {"key": "w_avg", "text": "describes average rate over an interval"}],
)

CASES: list[Case[GradeCase, GraderOutput]] = [
    Case(name="recursion_full_credit",
         inputs=GradeCase(**_RECURSION, format="free",
                          student_answer="The base case is what stops it; otherwise it keeps calling itself and the stack blows up."),
         metadata={"gold": {"r1": True, "r2": True}}),
    Case(name="recursion_partial_missing_growth",
         inputs=GradeCase(**_RECURSION, format="free", student_answer="It's the case where the function stops recursing."),
         metadata={"gold": {"r1": True, "r2": False}}),
    Case(name="recursion_wrong_loop_misconception",
         inputs=GradeCase(**_RECURSION, format="free",
                          student_answer="You don't really need one, recursion just runs until the loop is done like a for loop."),
         metadata={"gold": {"r1": False, "r2": False}, "wrong_key": "w_loop"}),
    Case(name="recursion_teachback_confident_wrong",
         inputs=GradeCase(**_RECURSION, format="teachback",
                          student_answer="I'm sure about this: the base case is an optimization that makes recursion faster; without it the answer is still correct but slower."),
         metadata={"gold": {"r1": False, "r2": False}, "wrong_key": "w_speed"}),
    Case(name="derivative_average_rate_confusion",
         inputs=GradeCase(**_DERIV, format="free",
                          student_answer="The change in y over the change in x between two points on the curve."),
         metadata={"gold": {"r1": True, "r2": False}, "wrong_key": "w_avg"}),
    Case(name="derivative_mc_reason_wrong_reason",
         inputs=GradeCase(**_DERIV, format="mc_reason",
                          student_answer="Selected option: B\nReason: it's the total area accumulated under the graph up to that point."),
         metadata={"gold": {"r1": False, "r2": False}, "wrong_key": "w_area"}),
]
assert len(CASES) <= GRADER_EVAL_MAX_CASES, len(CASES)


async def _run(case_input: GradeCase) -> GraderOutput:
    item = SimpleNamespace(**case_input.model_dump(exclude={"format", "student_answer"}))
    message = build_grader_message(item, format=case_input.format, student_answer=case_input.student_answer)
    name = next(c.name for c in CASES if c.inputs == case_input)
    return await run_with_cassette(
        dataset="grader", case_name=name, agent=grader_agent, case_input=message, output_model=GraderOutput,
    )


def make_dataset() -> Dataset[GradeCase, GraderOutput]:
    return Dataset(
        name="grader",
        cases=CASES,
        evaluators=[
            NoReferenceLeakEvaluator(),
            RubricAgreementEvaluator(),
            StrictOnWrongEvaluator(),
            ConfidenceInRangeEvaluator(),
            ConfidenceAgreementLabel(),
        ],
    )


if __name__ == "__main__":
    cli_main(make_dataset, _run)
```

- [ ] **Step 2: Record once** (needs `GEMINI_API_KEY` in `backend/.env`; `run_with_cassette` runs the agent on the `grader` slot without `usage_limits`, like every other dataset)

Run: `cd backend && SAPLING_EVAL_MODE=record venv/bin/python tests/evals/grader.py`
Expected: one cassette per case under `tests/evals/cassettes/grader/`. `NoReferenceLeakEvaluator`, `StrictOnWrongEvaluator`, `ConfidenceInRangeEvaluator` should each be `1.000`; if leak or strictness is below that, tighten those system-prompt lines, re-record, note the wording change in the hand-off. `RubricAgreementEvaluator` is measured, not assumed. The report shows one `ConfidenceAgreementLabel` per case; copy the six labels into the hand-off (calibration data, not a gate).

Then: `cd backend && SAPLING_EVAL_UPDATE_BASELINES=1 venv/bin/python tests/evals/grader.py` → `Updated baselines for grader`. Confirm the `"grader"` block in `baselines.json` holds exactly the four gated evaluators (a label never becomes a baseline). Add `"grader"` to `DATASETS` in `run_all.py`.

No key available → do NOT add `"grader"` to `DATASETS` (an unbaselined dataset fails CI closed), commit the dataset file only, and write a Deviation + Known gap ("grader eval unrecorded; record + update baselines before PKG-07"); the canonical verify line cannot pass — say so in the ledger row.

- [ ] **Step 3: Replay + full harness**

Run: `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/grader.py && venv/bin/python tests/evals/run_all.py`
Expected: every evaluator ≥ baseline; `PASS grader` in the summary; no other dataset moves.

- [ ] **Step 4: Commit**

```
git add backend/tests/evals/grader.py backend/tests/evals/cassettes/grader backend/tests/evals/run_all.py backend/tests/evals/baselines.json
git commit -m "evals(learning-loop): PKG-05 — grader dataset (leak, agreement, strictness, confidence; confidence-vs-gold label)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 7: Hand-off + ledger

- [ ] **Step 1:** Write `docs/superpowers/plans/learning-loop/HANDOFF-05.md` from `HANDOFF-template.md`. Symbols added must list: `agents.GRADER_LIMITS`; `agents/_providers.py::AgentTask "grader", "grader_second"` and their `_DEFAULTS`; `agents/grader.py::{GraderOutput, GradeResult (incl. backend), grader_agent, build_grader_message, parse_item_results, grade, _SECOND_OPINION_SETTINGS}`; `agents/tools/check.py::{CheckAnswer, GradeOutcome, CHANNEL_FOR_FORMAT, grade_answer}` with the canonical signature `async def grade_answer(item: CheckItem, answer: CheckAnswer, *, deps: SaplingDeps, node_id: str, max_rung: int = 0, same_session_recheck: bool = False) -> GradeOutcome` and the `GradeOutcome` field list; `learning/evidence.py::{GraderBackend, Evidence.grader_backend, flush_pending}`; migration `<ts>_learning_grader_backend.sql` (column `node_mastery_events.grader_backend`); `agents/function_handlers_e2e.py::{E2E_GRADER_CORRECT_TOKEN, E2E_GRADER_CONFIDENCE, E2E_GRADER_HINT}` (one handler, both slots); `tests/evals/grader.py` dataset `grader`; params names added (incl. `GRADER_SECOND_OPINION_SLOT`). Constants chosen: the Named-constants table, `†` rows marked, plus the six `ConfidenceAgreementLabel` values. Open questions: (a) PKG-07 wires `flush_pending` into `/check/answer` between `grade_answer` and the feedback turn (A16) and decides the HTTP shape of an `apply_graph_update` failure; (b) any consumer that shows `feedback_hint` itself routes it through `leak.detect_leak` (PKG-06) first — the A16 feedback turn normally writes the student-facing text instead; (c) callers resolve `node_id` from `item.concept_key` (A2) — HANDOFF-07/08 should name the shared resolver; (d) `GRADER_LOW_CONFIDENCE` calibration from the confidence-vs-gold labels. Deviations: every `†` row; `grader_backend=None` on idk evidence (no verdict was computed) †; any narrowing of inv_14's `GRAPH_TABLE_CALLS`; any `test_no_production_caller_passes_evidence_yet` exemption. "Verify commands" must be exactly:

```
cd backend && venv/bin/python -m pytest tests/test_learning_check_tool.py -q                    → N passed (N ≥ 16)
grep -c '"grader"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py          → ≥ 1 each
grep -c '"grader_second"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py   → ≥ 1 each
grep -c "^async def grade_answer" backend/agents/tools/check.py                                  → 1
ls backend/db/migrations/*_learning_grader_backend.sql                                           → 1 file
cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_14 or inv_28" → 2 passed
cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/grader.py                     → every evaluator ≥ baseline
```

- [ ] **Step 2:** Ledger. Append `| 03 | evidence-state | verified | … | PKG-05, <date>, tests/test_learning_evidence_apply.py tests/test_graph_service.py -q → all passed | HANDOFF-03.md |` and `| 04 | check-items | verified | … | PKG-05, <date>, tests/test_learning_check_items.py -q → N passed | HANDOFF-04.md |` (the State-of-the-world rows you ran), then `| 05 | grader-check-tool | done | feat/learning-loop-05-grader-check-tool | <sha> | tests/test_learning_check_tool.py (N), inv_06 ext, inv_14, inv_28, evals/grader | — | HANDOFF-05.md |`. Deviations: as listed in Step 1.

- [ ] **Step 3: Commit**

```
git add docs/superpowers/plans/learning-loop/HANDOFF-05.md docs/superpowers/plans/learning-loop/LEDGER.md
git commit -m "docs(learning-loop): PKG-05 — hand-off and ledger

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 8: PR

- [ ] **Step 1:** Run the self-check loop once more (below), then:

```
gh pr create --title "feat(learning): PKG-05 grader-check-tool" --body-file - <<'EOF'
Learning loop series, package 6 of 17. Spec: docs/superpowers/specs/2026-09-26-learning-loop-design.md §3.1, §3.3, §3.4, §3.5, §4, §5, §8, §13 (A1, A2, A16, A22).

- PKG-03 reopened: Evidence.grader_backend + node_mastery_events.grader_backend (migration <ts>_learning_grader_backend.sql); learning/evidence.py::flush_pending, the route's one-call persister
- agents/grader.py: task "grader" (flash-lite) + slot "grader_second" (2.5-flash, thinking 0; same agent and prompt) for the one second opinion; flat GraderOutput, sees the key, never solves, never restates; own agent call under GRADER_LIMITS charged via record_agent_usage; UsageLimitExceeded/UnexpectedModelBehavior → GradeResult(unavailable=True) + WARNING
- agents/tools/check.py::grade_answer — the single grading ROUTE helper (A16), not a tool: idk on the item's channel (A1); mc_reason option compared in code with the reason check run for both outcomes; a numeric gate that only ever says incorrect and runs only after the grader returned (A22; symmetric under outage and the cap); grader unavailable → no evidence for either outcome (inv_28); grader_backend stamped; never writes a graph table (inv_14)
- function-mode grader handler for both slots (E2E_GRADER_*); tests/evals/grader.py (leak / agreement / strictness / confidence gated; confidence vs gold agreement logged as a label)
- Nothing registered on any agent and no route calls grade_answer yet (PKG-07's /check/answer is first). Flag unset or true: behaviour byte-identical.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
```

## Self-check loop (run after every task, and once more before the PR)

1. `cd backend && venv/bin/ruff check . && venv/bin/ruff format --check learning tests/test_learning_*.py`
2. `venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q`
3. `venv/bin/python -m pytest tests/ -q` (no `SAPLING_MODEL_MODE` exported)
4. Prompts touched? **Yes** (`agents/grader.py` prompt + `GraderOutput` descriptions) → once Task 6 exists, `SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/run_all.py` must pass; a prompt edit after recording means re-record `grader` and refresh its baseline. No tool descriptions exist (`grade_answer` is a route helper). `chat_tutor` cassettes untouched.
5. Request-path agent or route touched? **Agent yes, route no.** No route calls `grade_answer` yet → skip the E2E cycle; the handler is proven in-process by `test_e2e_grader_handler_all_yes_on_token` and `test_e2e_grader_handler_serves_both_slots`. PKG-07 runs the stack.
6. Scope check: `git diff --stat main...HEAD` — every path must be in this prompt's Files lists. Anything else: `git checkout main -- <path>` or record a Deviation.
7. Sync check: `grep -o "E2E_[A-Z_]*" backend/agents/function_handlers_e2e.py | sort -u` differs from `main` by exactly `E2E_GRADER_CONFIDENCE`, `E2E_GRADER_CORRECT_TOKEN`, `E2E_GRADER_HINT`.

Green = all seven clean (Tasks 1–3 leave `test_inv_06`/`test_inv_28` red by design, as their Run steps say; from Task 4 on, green means green). Max 5 iterations per loop; then write a `BLOCKED` row in `LEDGER.md` with hypothesis, commands, outputs, and stop. Before the PR also run `grep -nE "[^A-Za-z_\"'][0-9]+\.[0-9]+" backend/agents/grader.py backend/agents/tools/check.py backend/learning/evidence.py` — only `ge=0.0, le=1.0` bounds and the `1.0`/`0.0` identity values (weights, the default numeric tolerance) may print; every threshold and rung is a `learning.params` name.

## Regression guard

- Pre-series suite count N₀ (from State of the world) unchanged except for the tests this package adds. Zero failures, zero new skips outside `test_learning_loop_invariants.py`.
- Dependency suites green, their code unmodified except the PKG-03 reopens — `learning/evidence.py` (Task 0: the `grader_backend` field; Task 5: `flush_pending`, append-only) and `services/graph_service.py::_apply_evidence` (Task 0: one journal-row key) — and the PKG-01 rename (Task 0b: one `params.py` line, three references in `tests/test_learning_bkt.py`). Suites: `tests/test_learning_evidence_apply.py`, `tests/test_graph_service.py` (PKG-03, including its legacy byte-identity trace); `tests/test_learning_check_items.py` + `tests/evals/check_items.py` replay (PKG-04); `tests/test_learning_bkt.py`, `tests/test_learning_fsrs.py` (PKG-01/02).
- Pre-series suites touched: `tests/test_agent_output_schemas.py` (roster + budget), `tests/test_e2e_function_handlers.py` (existing `E2E_*` constants byte-identical), `tests/test_model_mode_seam.py`, `tests/test_event_capture_seams.py` (taxonomy pin untouched), `tests/test_migration_naming.py`, `tests/test_migrations.py`, `tests/evals/run_all.py` replay. `LEARNING_LOOP_ENABLED` unset or `true`: no route behaviour changes — nothing calls `grade`, `grade_answer`, or `flush_pending` until PKG-07; legacy `node_mastery_events` rows are unchanged (the new column is nullable and set only on evidence rows).

## Acceptance criteria (the next session pastes these)

1. `cd backend && venv/bin/python -m pytest tests/test_learning_check_tool.py -q` → `N passed`, N ≥ 16
2. `grep -c '"grader"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py` → ≥ 1 each; `grep -c '"grader_second"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py` → ≥ 1 each
3. `grep -c "^async def grade_answer" backend/agents/tools/check.py` → `1`; `grep -c "graded_check\|make_graded_check_tool\|GRADED_CHECK_TOOL_NAME\|RunContext" backend/agents/tools/check.py` → `0`
4. `ls backend/db/migrations/*_learning_grader_backend.sql` → 1 file; `cd backend && venv/bin/python -m pytest tests/test_learning_grader_backend_migration.py tests/test_learning_evidence_apply.py tests/test_graph_service.py -q` → all passed
5. `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/grader.py` → every evaluator ≥ baseline (or the Known-gap note if unrecorded)
6. `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_06 or inv_14 or inv_28"` → `3 passed`
7. `cd backend && venv/bin/python -m pytest tests/ -q` → zero failures; `venv/bin/ruff check .` → `All checks passed!`
8. `grep -c "grade_answer\|graded_check" backend/agents/chat_tutor.py backend/routes/learn.py` → `0` and `0`; `grep -c "from db.connection import\|apply_graph_update" backend/agents/tools/check.py` → `0`
9. `git diff --stat main...HEAD` lists only: `backend/agents/__init__.py`, `backend/agents/_providers.py`, `backend/agents/grader.py`, `backend/agents/tools/check.py`, `backend/agents/function_handlers_e2e.py`, `backend/learning/params.py`, `backend/learning/evidence.py`, `backend/services/graph_service.py`, `backend/db/migrations/<ts>_learning_grader_backend.sql`, `backend/tests/test_learning_grader_backend_migration.py`, `backend/tests/test_learning_evidence_apply.py`, `backend/tests/test_learning_bkt.py` (Task 0b rename only), `backend/tests/test_learning_check_tool.py`, `backend/tests/test_learning_loop_invariants.py`, `backend/tests/test_agent_output_schemas.py`, `backend/tests/evals/{grader.py,run_all.py,baselines.json,cassettes/grader/*}`, `docs/superpowers/plans/learning-loop/{HANDOFF-05.md,HANDOFF-03.md,HANDOFF-01.md,LEDGER.md}`.
10. `LEDGER.md` has rows `03 | … | reopened` (Tasks 0 and 5), `01 | … | reopened` (Task 0b), `03 | … | verified`, `04 | … | verified`, `05 | grader-check-tool | done | …`.
11. `grep -rn "GRADER_RETRY_BELOW" backend --include=*.py | wc -l` → `0`; `grep -c "^GRADER_SECOND_OPINION_CONFIDENCE = 0.4" backend/learning/params.py` → `1`

## Hand-off

`docs/superpowers/plans/learning-loop/HANDOFF-05.md` per the template; the Verify commands block is fixed above (Task 7). It must spell out `grade_answer`'s canonical signature and the `GradeOutcome` fields — PKG-05b, 07, 08, 10, 12 and 14 take them from here. Open questions to record are listed in Task 7 Step 1 — the `flush_pending` failure shape (PKG-07), the `feedback_hint` leak routing (PKG-06), the `node_id` resolver (A2), and the `GRADER_LOW_CONFIDENCE` calibration data.

## Do not

- Do not build a tool: no `graded_check_tool`, no `make_graded_check_tool`, no `GRADED_CHECK_TOOL_NAME`, no `Tool(`/`RunContext` in `agents/tools/check.py`; register nothing on any agent. Do not call `grade_answer`, `grade` or `flush_pending` from any route (PKG-07/08/12/14 do). Do not touch `agents/chat_tutor.py`, `routes/learn.py`, `services/chat_stream.py`, `services/events_service.py`, `learning/checks.py`, `services/check_item_service.py`; touch `services/graph_service.py` only for Task 0's one journal-row key.
- Do not write `graph_nodes`/`graph_edges`/`node_mastery_events`/`learner_state` from `agents/tools/` (inv_14). No `db.connection` import in `agents/tools/check.py`; no Supabase access anywhere in this package's new code (the caller loads the item through PKG-04's service).
- One prompt, one `Agent(` in `agents/grader.py` (inv_12); the `grader_second` slot is a per-run `model=`. Never the reference answer, or anything derived from it, in a `GradeOutcome`.
- Never issue a code-side `correct=True` on a strong channel (A22; the numeric gate only ever says incorrect). Never append evidence for one outcome of an attempt while dropping the other (inv_28): an unavailable reason check records nothing for either `mc_reason` outcome. Never record an `mc_reason` option's `wrong_key` unless the grader matched that same key.
- No `ai_budget` call (PKG-06b), no `services/decisions.py` or `decision` slot (PKG-05b), no Jev or `typesafe` code (PKG-15), no verdict cache (spec §12).
- No event type (taxonomy is PKG-05b/06/06b's; WARNING logs are the degrade signal). No nested models in `GraderOutput`/`CheckAnswer` (`tests/test_agent_output_schemas.py` gates the budget).
- No numeric literals for weights/thresholds/rungs in `agents/grader.py`, `agents/tools/check.py`, `learning/evidence.py` — `learning/params.py` names only; `GRADER_LIMITS` values live in `agents/__init__.py` per spec §3.4; the second-opinion thinking budget lives in `_SECOND_OPINION_SETTINGS` per spec §3.5.
- The grader never runs inside `TUTOR_LIMITS`: its own `agent.run` with `usage_limits=GRADER_LIMITS`, for both slots.
- One migration only (Task 0, spec §4 DDL verbatim); never edit an applied migration. No `lru_cache`, no `httpx`, no `supabase` import.
- Do not skip, xfail, or delete any pre-existing test. Do not hand-edit eval cassettes or baselines (record + `SAPLING_EVAL_UPDATE_BASELINES=1` only).
- Logscan `ALLOWLIST` in `backend/e2e_oracles/logscan.py` stays `()`.
- End every commit with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; end the PR body with the Claude Code attribution line.

## If you get stuck

1. Re-read §Spec and the spec file's §3.3 "Evidence mapping by rung", §3.4, §3.5, §5 and §13 A16/A22 before guessing. HANDOFF-03/04 name a symbol differently → use the real name (not a deviation); lack one this prompt needs → add the smallest version under the reopen rule (Task 0/5 shape) and record it.
2. Three failed iterations on one task → append a `BLOCKED` row to `LEDGER.md` (hypothesis, commands run, outputs), commit what is green, open the PR as draft, stop.
3. Never widen scope to unblock. Never disable a test to unblock.
4. Ambiguity → choose the option closest to the spec, mark it `†` in the hand-off, continue. Already decided here: `grade_answer` takes the student's `node_id` from its caller (A2 removed `node_id` from items); idk evidence carries `grader_backend=None`; an `mc_reason` right option with a failed reason carries the grader's matched key (spec §3.3).
