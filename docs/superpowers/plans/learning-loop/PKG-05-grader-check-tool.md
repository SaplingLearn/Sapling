# PKG-05 grader-check-tool — Learning Loop series (6 of 15)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> You are a fresh session. Nothing outside this file, `docs/superpowers/plans/learning-loop/LEDGER.md`, the hand-offs it names, and the files this prompt lists is known to you. Do not infer intent from chat history you do not have. Do not read the whole research corpus; read the sections named below.

## Package id + goal

**PKG-05 `grader-check-tool`.** After this package: a `grader` agent exists that sees the stored reference answer and judges each rubric item yes/no without ever solving the problem or restating the key; a `graded_check_tool` exists that turns one student answer into one `Evidence` dict accumulated on `deps.pending_evidence` — and never writes a graph table; `learning/evidence.py::flush_pending` is the one helper a ROUTE calls to persist that list through `apply_graph_update` once per turn; the function-mode seam serves the grader deterministically; `tests/evals/grader.py` gates reference leakage and rubric agreement. Nothing is registered on the tutor yet (PKG-07 does `_build_tools(learning_loop=True)`), so flag-off behaviour is byte-identical. `tests/test_learning_check_tool.py` proves it.

Branch: `feat/learning-loop-05-grader-check-tool`. PR title: `feat(learning): PKG-05 grader-check-tool`.

## Read before you start (in this order)

0. `docs/superpowers/specs/2026-09-26-learning-loop-design.md` **§13 Amendments log** — in force; where this file and §13 disagree, §13 wins. Re-read it before Task 1.
1. `docs/superpowers/plans/learning-loop/LEDGER.md` — refuse to start if any row is `blocked` or `in-progress`. Rows 00, 01, 02, 03, 04 must be `done` or `verified`.
2. `docs/superpowers/plans/learning-loop/HANDOFF-03.md` and `HANDOFF-04.md` — §Symbols added is the contract. Before Task 1 write down: the check-item read function's name in `services/check_item_service.py` (this prompt: `get_by_question_hash(question_hash)`), the `learning.checks.CheckItem` attributes (this prompt: `id, node_id, format, difficulty, prompt, reference_answer, rubric, common_wrong, question_hash`; `rubric` = list of `{"id","text"}`, `common_wrong` = list of `{"key","text"}`, both DECRYPTED by the service), and whether `learning/evidence.py` exports `evidence_weight`. A differing name → use the real one everywhere; a lookup, not a deviation.
3. `CLAUDE.md` §Conventions and §Gotchas — the standing rules the "Do not" list below repeats.
4. `docs/superpowers/specs/2026-09-26-learning-loop-design.md` §3.1 (weights table + channel table), §3.3 "Evidence mapping by rung", §3.4 (`GRADER_LIMITS`, `GRADER_LOW_CONFIDENCE`, `LEAK_NGRAM`), §5 (Evidence model + the single-writer sentence), §7 (the `_build_tools(learning_loop=)` line), §8 invariants 1, 6, 12, §10 rung 1 (what `tests/evals/grader.py` must gate).
5. `docs/superpowers/plans/learning-loop/README.md` — series conventions, especially "Touching an earlier package's code" (Task 5 reopens PKG-03).
6. `docs/superpowers/plans/learning-loop/HANDOFF-template.md` — what you write at the end.
7. Research, only these sections: `docs/research/learning-loop/AI tutor learning loop research.md` §"Check: free response and teach-back for credit" (≈ lines 78–80) and §"Guardrails … gate the grader" (≈ lines 131–137; the last paragraph is the grader's brief: sees the key, never solves, per-item binary + confidence, strictness is the safer bias); `docs/research/learning-loop/ZPD lever tradeoffs and upgrades.md` §"Sapling ZPD policy spec" → `EVIDENCE MAPPING` block (≈ lines 200–212).
8. Code you will modify: `backend/agents/__init__.py:83–87` (`TUTOR_LIMITS` shape; `GRADER_LIMITS` goes beside it), `backend/agents/_providers.py:39–49` (`AgentTask` Literal) and `:52–105` (`_DEFAULTS`), `backend/agents/function_handlers_e2e.py:190–205` (`_structured_output`) and `:250–275` (concept_describe section — the registration comment style), `backend/tests/test_agent_output_schemas.py:63–90` (the frozen roster sets), `backend/tests/evals/run_all.py:34` (`DATASETS`), `backend/tests/evals/baselines.json`, `backend/learning/evidence.py` (PKG-03's; Task 5), `backend/tests/test_learning_loop_invariants.py::test_inv_06_*` (PKG-04's shape).
9. Code you will mirror: `backend/agents/concept_describe.py` (tool-less flash-lite structured agent, `retries=2`), `backend/routes/notes.py:50–82` (`_run_note_worker` — the two-exception honest-degrade shape), `backend/agents/tools/graph.py:130–156` (tool signature + appending to `ctx.deps.*`), `backend/agents/chat_tutor.py:152–168` (`_build_tools` — fresh `Tool` per agent), `backend/tests/test_model_mode_seam.py:140–200` (scripted `ToolCallPart` through a real agent), `backend/tests/evals/chat_tutor.py` + `_replay.py::run_with_cassette` (dataset shape).

## State of the world

Verify the base before Task 1. Every row must match.

| check | command | expected |
|---|---|---|
| ledger | `grep -E "^\| 0[0-4] " docs/superpowers/plans/learning-loop/LEDGER.md \| tail -5` | each of 00–04 has a latest row `done` or `verified` |
| hermetic suite green | `cd backend && venv/bin/python -m pytest tests/ -q -x` | `… passed`, zero failures (note the count N₀) |
| lint green | `cd backend && venv/bin/ruff check .` | `All checks passed!` |
| PKG-00 | `cd backend && venv/bin/python -m pytest tests/test_learning_gate.py -q` | `11 passed` |
| PKG-00 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q` | `N passed, M skipped` with no failures (later packages raise the passed count) |
| PKG-00 | `cd backend && venv/bin/python -m pytest tests/test_learning_deps.py tests/test_learning_settings_flag.py tests/test_learning_loop_beta_migration.py -q` | all passed |
| PKG-00 | `grep -n "^LEARNING_LOOP_ENABLED" backend/config.py` | 1 hit |
| PKG-00 | `ls backend/db/migrations/*_learning_loop_beta.sql` | 1 file |
| PKG-03 | `cd backend && venv/bin/python -m pytest tests/test_learning_evidence_apply.py tests/test_graph_service.py -q` | all passed |
| PKG-03 | `ls backend/db/migrations/*_learning_learner_state.sql` | 1 file |
| PKG-03 | `grep -c '"evidence"' backend/services/graph_service.py` | ≥ 1 |
| PKG-03 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k inv_01` | 1 passed |
| PKG-04 | `cd backend && venv/bin/python -m pytest tests/test_learning_check_items.py -q` | N passed (N ≥ 10) |
| PKG-04 | `ls backend/db/migrations/*_learning_check_items.sql` | 1 file |
| PKG-04 | `grep -c '"check_items"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py` | ≥ 1 each |
| PKG-04 | `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/check_items.py` | every evaluator ≥ baseline |
| PKG-04 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_06 or inv_09 or inv_12"` | 3 passed |
| stubs still inert | `wc -l backend/agents/grader.py backend/agents/tools/check.py` | each ≤ 5 lines (docstring only) |
| deps ready | `grep -c "pending_evidence\|learning_loop" backend/agents/deps.py` | ≥ 2 |

Rule: any red row → STOP. Diagnose, repair on this branch as commit `fix(learning-loop): repair pre-series base — <what>`, record the deviation in `LEDGER.md`, re-run all rows. Never build on a broken base.

## Spec

### Behaviour

1. **Grader agent** (`agents/grader.py`, task `"grader"`, default `gemini-2.5-flash-lite`, tool-less, `retries=2`, `output_type=GraderOutput`). ONE user message from `build_grader_message(item, format=, student_answer=)`: question, reference answer, rubric items (`RUBRIC ITEM <id>: <text>`, one per line), common wrong reasons (`COMMON WRONG REASON <key>: <text>`), format, student answer. FLAT output: `item_results: list[str]` of `"<rubric_id>:yes|no"`, `confidence` in [0, 1], `matched_wrong_key` (a listed key or `""`), `feedback_hint` (≤ `FEEDBACK_HINT_MAX_SENTENCES` sentences, ≤ `GRADER_HINT_MAX_CHARS` chars, never the reference). System prompt: judge each rubric item strictly against the reference; never solve the problem; never restate, quote or paraphrase the reference; when unsure answer `no` and lower `confidence` (strictness is the safer bias).
2. **`grade(item, *, format, student_answer, deps) -> GradeResult`** (async, `agents/grader.py`) is the only caller of the agent: `grader_agent.run(message, deps=deps, usage_limits=GRADER_LIMITS)`, then `record_agent_usage(result, feature=deps.feature, task="grader", user_id=deps.user_id)`, then `parse_item_results` (missing/malformed id → `False`; ids outside the rubric dropped) into a code-side `GradeResult(item_results, all_yes, confidence, matched_wrong_key, feedback_hint, low_confidence=confidence < GRADER_LOW_CONFIDENCE)`. Second opinion (spec §3.4): `confidence < GRADER_SECOND_OPINION_CONFIDENCE` → ONE more run (same message, own limits, own usage row); still below → `GradeResult(unavailable=True)`.
3. **Honest degrade** (ADR 0024): `UsageLimitExceeded` or `UnexpectedModelBehavior` from either call → `logger.warning("grader unavailable for item %s: %s", item.id, exc)` and `GradeResult(unavailable=True)`. No second prompt stack, no fallback text, no retry beyond pydantic-ai's `retries=2`. No event is emitted in this package (PKG-06 owns the taxonomy; the WARNING line is the observable).
4. **`graded_check_tool(ctx, answer: CheckAnswerInput) -> str`** (`agents/tools/check.py`, wire name `graded_check`; input fields in Task 4). Behaviour, in order:
   - `ctx.deps.learning_loop is False` → return `"graded_check is not enabled for this session."`; append nothing; call nothing.
   - load the item with `_load_item(question_hash)` (module-level wrapper over `check_item_service.get_by_question_hash`, run in `asyncio.to_thread`; an exception is logged at WARNING and treated as `None`); `None` → return `"No check item matches that question_hash."`; append nothing.
   - `format == "idk"` → append `Evidence(channel="idk", correct=False, weight=1.0, confidence=None, …)`; return the idk summary. The grader is NOT called.
   - else `grade(item, format=, student_answer=<answer_text, or for mc_reason "Selected option: …\nReason: …">, deps=ctx.deps)`; `unavailable` → append nothing; return the unavailable summary.
   - correct: `free`/`teachback` → `all_yes`; `mc_reason` → `all_yes AND _option_matches(selected_option, item.reference_answer)` (case/whitespace-insensitive equality; if HANDOFF-04 gives `CheckItem` a dedicated correct-option attribute, compare against that).
   - channel: `free → free_response`, `teachback → teachback_llm`, `mc_reason → mc_reasoned`. assisted: `RUNG_ASSISTED_MIN <= max_rung_used <= RUNG_ASSISTED_MAX`.
   - weight: `correct and max_rung_used >= RUNG_NO_CREDIT_MIN` → `0.0` (spec §3.3: no upward evidence after H4–H6; the Evidence is still appended so the route writes FSRS Again + the event); else `evidence_weight(assisted=, same_session_recheck=, low_confidence=result.low_confidence)` — wrong answers at any rung get the same rule ("standard incorrect observation").
   - append `Evidence(...).model_dump()` to `ctx.deps.pending_evidence` (`confidence=result.confidence`, `session_id=ctx.deps.session_id`, `check_item_id=item.id`, `question_hash`).
   - return a short summary for the model: per-item yes/no, correct/not, assisted + max rung, `matched_wrong_key` if any, `feedback_hint`, and for no-credit "recorded with no upward credit; an isomorph is re-asked next session". It NEVER contains `item.reference_answer` (tested by substring).
5. **The tool never persists.** `agents/tools/check.py` imports nothing from `db.connection` and calls neither `apply_graph_update` nor any `table(...)`. The only writer is the route, through `learning.evidence.flush_pending(deps, course_id)`.
6. **`flush_pending(deps, course_id) -> list`** (`learning/evidence.py`, Task 5): empty list → return `[]`, call nothing; else `apply_graph_update(deps.user_id, {"evidence": list(deps.pending_evidence)}, course_id)` exactly once (local import — PKG-03's `graph_service` imports `learning.evidence`, so a module-level import is circular), clear the list, return the changes. Tools never call it; PKG-07 wires it into the loop route after the turn.
7. **Function-mode handler** (task `"grader"`): reads the last user prompt, extracts rubric ids with `re.findall(r"^RUBRIC ITEM (\S+):", text, re.M)`; `E2E_GRADER_CORRECT_TOKEN` in the text → every id `yes`, else every id `no`; `confidence=E2E_GRADER_CONFIDENCE`, `feedback_hint=E2E_GRADER_HINT`; emits through `info.output_tools[0]` so the real schema validates it.
8. **Tool export.** `GRADED_CHECK_TOOL_NAME = "graded_check"` and `make_graded_check_tool() -> Tool` (a fresh `Tool(graded_check_tool, name=…, takes_ctx=True)` per call — `chat_tutor._build_tools` `:152–155` builds fresh Tool objects per agent so none lands on two agents). Nothing outside tests calls it in this package.
9. **Flag inertness.** `LEARNING_LOOP_ENABLED` unset changes nothing: no agent registers the tool, no route calls `grade`/`flush_pending`, and the tool body returns early when `deps.learning_loop` is False (`test_tool_is_inert_when_learning_loop_false`).

### Schema (exact)

No migration in this package. The `Evidence` model is PKG-03's (spec §5); the `check_items` table is PKG-04's (spec §4). Both are read-only inputs here. The two Pydantic shapes this package sends to or receives from Gemini — `GraderOutput` (4 flat fields, Task 2) and `CheckAnswerInput` (8 flat fields, Task 4) — are written out in full in those tasks and stay inside the `agents/__init__.py` schema budget.

### Named constants

Every number this package uses, once. Tasks cite the NAME. `†` = engineering choice with no validated cut-point (add to `learning/params.py` and record in the hand-off as a deviation).

| Name | Value | Where it lives | Spec ref |
|---|---|---|---|
| `GRADER_LIMITS` | `UsageLimits(request_limit=2, tool_calls_limit=0, total_tokens_limit=20_000)` | `agents/__init__.py` (beside `TUTOR_LIMITS`, the house location for limits) | §3.4 |
| `GRADER_LOW_CONFIDENCE` | 0.6 | `learning/params.py` (PKG-01 created it; verify with grep) | §3.4 |
| `GRADER_SECOND_OPINION_CONFIDENCE` † | 0.4 | `learning/params.py` (the VALUE is in §3.4; the NAME is new — add it) | §3.4 |
| `WEIGHT_ASSISTED` | 0.5 | `learning/params.py` (PKG-01) | §3.1 |
| `WEIGHT_SAME_SESSION_RECHECK` | 0.5 | `learning/params.py` (PKG-01) | §3.1 |
| `WEIGHT_LOW_CONFIDENCE` | 0.5 | `learning/params.py` (PKG-01) | §3.1 |
| `LEAK_NGRAM` | 6 | `learning/params.py` (PKG-01) | §3.4 |
| `RUNG_ASSISTED_MIN` / `RUNG_ASSISTED_MAX` | 1 / 3 | `learning/params.py` (new names for §3.3 "H1–H3"; add if PKG-01 did not) | §3.3 |
| `RUNG_NO_CREDIT_MIN` | 4 | `learning/params.py` (new name for §3.3 "H4–H6"; add if absent) | §3.3 |
| `FEEDBACK_HINT_MAX_SENTENCES` † | 2 | `learning/params.py` | brief; not in spec |
| `GRADER_HINT_MAX_CHARS` † | 300 | `learning/params.py` | schema guard; not in spec |
| `GRADER_EVAL_MAX_CASES` | 8 | `tests/evals/grader.py` (an assert on `len(CASES)`) | series rule |
| `E2E_GRADER_CORRECT_TOKEN` | `"E2E_GRADER_CORRECT"` | `agents/function_handlers_e2e.py` | — |
| `E2E_GRADER_CONFIDENCE` | 0.95 | `agents/function_handlers_e2e.py` (a fixture value, ≥ `GRADER_LOW_CONFIDENCE` so E2E evidence is full-weight) | — |
| `E2E_GRADER_HINT` | `"[e2e-function-model] Deterministic grader hint: check the base case first."` | `agents/function_handlers_e2e.py` | — |

`GRADER_LIMITS.request_limit` is 2 while `retries=2` on the agent means a second validation retry trips `UsageLimitExceeded` rather than `UnexpectedModelBehavior`. That distinction matters at `routes/notes.py` (413 vs 500); it does not matter here, because both exceptions degrade to the same `unavailable` result. Keep the spec value.

### Invariants asserted by this package (spec §8 numbering)

- (6) extended: `"grader"` is in the series-task tuple that `test_inv_06_series_agent_tasks_have_function_handlers` checks against `agents.function_handlers_e2e`'s registrations.
- (12) already asserted by PKG-04 for every series agent module: `agents/grader.py` defines exactly one system prompt and one `Agent(`. Do not add a `_fallback_prompt`.
- (14, new — series extension of §8.1) `test_inv_14_tools_never_write_graph_tables`: a source scan of `backend/agents/tools/*.py` finds no `table("graph_nodes")`, `table("graph_edges")`, `table("node_mastery_events")`, `table("learner_state")`, and `agents/tools/check.py` contains neither `apply_graph_update` nor `from db.connection import`.

### Error semantics

- Grader budget/behaviour failure → `GradeResult(unavailable=True)` + WARNING; the tool appends nothing and tells the model the grader is unavailable. Never raises into the agent loop.
- Unknown `question_hash`, or `_load_item` raising (logged at WARNING) → plain message; appends nothing.
- `flush_pending` does NOT catch: `apply_graph_update` errors propagate to the route (PKG-07 decides the HTTP shape). It clears the list only after a successful call.

### Events added

None. The taxonomy is untouched (PKG-06 adds `zpd.*`). `record_agent_usage` writes `llm_usage` rows for every grader call under `task="grader"`, which is the cost trail the admin analytics already reads.

## Non-goals

- No tutor registration (`chat_tutor._build_tools(learning_loop=)` is PKG-07), no route, no stream event, no frontend.
- No leak detector (`learning/leak.py::detect_leak` is PKG-06; PKG-06 routes `feedback_hint` through it). The eval's `NoReferenceLeak` is this package's only leakage gate.
- No misconception recording: `matched_wrong_key` reaches only the tool's summary string (spec §5's `Evidence` has no field for it); PKG-10 decides where it persists. No FSRS rating here — `rating_for` runs inside `apply_graph_update` (PKG-03); the tool only sets `weight`, `assisted`, `max_rung`.
- No taxonomy change, no migration, no `lru_cache`.

## Tasks

### Task 1: Invariants — extend inv_06, add inv_14

**Files:**
- Modify: `backend/tests/test_learning_loop_invariants.py`

**Interfaces:**
- Consumes: `agents.function_handlers_e2e` (import registers handlers), filesystem under `backend/agents/tools/`.
- Produces: `test_inv_06_*` now covers `"grader"`; new `test_inv_14_tools_never_write_graph_tables`.

- [ ] **Step 1: Extend inv_06.** PKG-04 wrote the test over the series task names (grep `"check_items"` in the module). Add `"grader"` beside it. If PKG-04 hard-coded a single name, hoist the names into a module-level tuple `SERIES_AGENT_TASKS = ("check_items", "grader")  # PKG-07 appends "loop_tutor"` and assert every member is in `agents._providers._FUNCTION_HANDLERS` after importing `agents.function_handlers_e2e` on a cold registry (`clear_function_handlers()` + `_ENV_HANDLERS_LOADED=False` + `sys.modules.pop`, restored in `finally` — the `tests/test_e2e_function_handlers.py::_clean_function_registry` posture).

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
    """Series extension of spec §8.1: agent tools accumulate evidence on deps;
    only the route persists it through apply_graph_update."""
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
```

- [ ] **Step 3: Run**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -v -k "inv_06 or inv_14"`
Expected: `test_inv_06` FAIL — `no function-mode handler registered for ['grader']`; `test_inv_14` PASS. `graph_read.py` reads `table("graph_nodes")` with `.select` — if inv_14 fails on it, narrow `GRAPH_TABLE_CALLS` to lines that also contain `.insert(`/`.update(`/`.upsert(`/`.delete(` and record a deviation; never weaken the `check.py` assertions.

- [ ] **Step 4: Commit** (red is expected; Task 3 turns inv_06 green)

```
git add backend/tests/test_learning_loop_invariants.py
git commit -m "test(learning-loop): PKG-05 — inv_06 covers grader; inv_14 tools never write graph tables

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 2: Grader agent

**Files:**
- Modify: `backend/agents/__init__.py` (`GRADER_LIMITS` + `__all__`), `backend/agents/_providers.py` (`AgentTask`, `_DEFAULTS`), `backend/learning/params.py` (only the names the table marks "add if absent" / †), `backend/tests/test_agent_output_schemas.py` (`EXPECTED_STRUCTURED_AGENTS` += `"grader_agent"`)
- Replace stub: `backend/agents/grader.py`
- Test: `backend/tests/test_learning_check_tool.py` (grader section)

**Interfaces:**
- Consumes: `agents._providers.model_for("grader")`, `agents.usage.record_agent_usage`, `learning.params.{GRADER_LOW_CONFIDENCE, GRADER_SECOND_OPINION_CONFIDENCE, GRADER_HINT_MAX_CHARS, FEEDBACK_HINT_MAX_SENTENCES}`.
- Produces: `agents.grader.{GraderOutput, GradeResult, grader_agent, build_grader_message, parse_item_results, grade}`; `agents.GRADER_LIMITS`.

- [ ] **Step 1: Write the failing tests** — replace the stub `backend/tests/test_learning_check_tool.py` with this module. It grows in Tasks 3–5; keep the helpers at the top.

```python
"""PKG-05: grader agent + graded_check_tool + flush_pending.

Hermetic: the grader agent runs on a FunctionModel; Supabase reads are
monkeypatched at the module-level `_load_item` seam; apply_graph_update is a
spy. Nothing here may touch table() for a graph table."""
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
    RUNG_ASSISTED_MAX,
    RUNG_NO_CREDIT_MIN,
    WEIGHT_ASSISTED,
    WEIGHT_LOW_CONFIDENCE,
    WEIGHT_SAME_SESSION_RECHECK,
)

REFERENCE = "The base case stops the recursion; without it the stack grows until overflow."


def _item(**over):
    base = dict(
        id="ci-1",
        node_id="node-recursion",
        format="free",
        difficulty=1,
        prompt="Why does every recursive function need a base case?",
        reference_answer=REFERENCE,
        rubric=[{"id": "r1", "text": "names the base case"}, {"id": "r2", "text": "explains unbounded growth"}],
        common_wrong=[{"key": "w_loop", "text": "confuses recursion with a loop"}],
        question_hash="qh-1",
    )
    base.update(over)
    return SimpleNamespace(**base)


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
    assert res.low_confidence is False
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
    assert res.matched_wrong_key == "w_loop"


def test_grade_second_opinion_then_unavailable(monkeypatch):
    import agents.grader as g

    low = GRADER_SECOND_OPINION_CONFIDENCE / 2
    model, calls = _scripted_grader([_good(low), _good(low)])
    monkeypatch.setattr(g, "record_agent_usage", lambda r, **kw: r)
    with g.grader_agent.override(model=model):
        res = asyncio.run(g.grade(_item(), format="free", student_answer="x", deps=_deps()))
    assert calls["n"] == 2
    assert res.unavailable is True


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
# call from inside graded_check_tool, charged via record_agent_usage(
# task="grader"), never against TUTOR_LIMITS. Both UsageLimitExceeded and
# UnexpectedModelBehavior degrade to the same `unavailable`, so a request
# limit below WORKER_LIMITS' 1 + 2-retry ladder costs no diagnosability.
GRADER_LIMITS = UsageLimits(
    request_limit=2,
    tool_calls_limit=0,
    total_tokens_limit=20_000,
)
```
and add `"GRADER_LIMITS"` to `__all__`.

`backend/agents/_providers.py`: add `"grader"` to `AgentTask` (after PKG-04's `"check_items"`) and `"grader": "gemini-2.5-flash-lite",` to `_DEFAULTS` with a one-line comment (short per-item binary judgments → lite tier, spec §2).

`backend/learning/params.py`: grep each Named-constants name; add the missing ones beside the other `GRADER_*`/`WEIGHT_*` rows with a one-line comment citing the spec § or `†`. `backend/tests/test_agent_output_schemas.py`: add `"grader_agent"` to `EXPECTED_STRUCTURED_AGENTS` (frozen roster; `retries=2` satisfies the bounded-retry pin).

`backend/agents/grader.py`:
```python
"""Rubric grader for the learning loop (PKG-05; spec §2, §3.4).

Sees the stored reference answer and judges each rubric item yes/no. Never
solves the problem, never restates the key. Runs as its own agent call from
inside `agents/tools/check.py::graded_check_tool` under GRADER_LIMITS and is
charged to the request through record_agent_usage(task="grader").

Exactly one system prompt and one Agent (spec §8.12).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.exceptions import UnexpectedModelBehavior, UsageLimitExceeded

from agents import GRADER_LIMITS
from agents._providers import model_for
from agents.deps import SaplingDeps
from agents.usage import record_agent_usage
from learning.params import (
    FEEDBACK_HINT_MAX_SENTENCES,
    GRADER_HINT_MAX_CHARS,
    GRADER_LOW_CONFIDENCE,
    GRADER_SECOND_OPINION_CONFIDENCE,
)

logger = logging.getLogger("sapling.agents.grader")


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
    """Code-side result of grade(); `unavailable=True` is the ADR 0024 degrade."""

    unavailable: bool = False
    item_results: dict[str, bool] = field(default_factory=dict)
    all_yes: bool = False
    confidence: float = 0.0
    matched_wrong_key: str = ""
    feedback_hint: str = ""
    low_confidence: bool = False


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


async def _run_once(message: str, deps: SaplingDeps) -> GraderOutput:
    result = await grader_agent.run(message, deps=deps, usage_limits=GRADER_LIMITS)
    record_agent_usage(result, feature=deps.feature, task="grader", user_id=deps.user_id)
    return result.output


async def grade(item, *, format: str, student_answer: str, deps: SaplingDeps) -> GradeResult:
    """Grade one answer. Honest degrade (ADR 0024): budget or behaviour failure →
    GradeResult(unavailable=True) + WARNING, never a second prompt stack."""
    message = build_grader_message(item, format=format, student_answer=student_answer)
    rubric_ids = [r["id"] for r in item.rubric]
    try:
        out = await _run_once(message, deps)
        if out.confidence < GRADER_SECOND_OPINION_CONFIDENCE:
            out = await _run_once(message, deps)  # spec §3.4: one second opinion
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
    )
```

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_check_tool.py tests/test_agent_output_schemas.py -q && venv/bin/ruff check .`
Expected: the grader tests pass; `test_agent_roster_is_frozen` and `test_output_schema_within_budget[grader_agent]` pass; `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/agents/__init__.py backend/agents/_providers.py backend/agents/grader.py backend/learning/params.py backend/tests/test_agent_output_schemas.py backend/tests/test_learning_check_tool.py
git commit -m "feat(learning-loop): PKG-05 — grader agent (flash-lite, flat rubric output, honest degrade)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 3: Function-mode handler for `grader`

**Files:**
- Modify: `backend/agents/function_handlers_e2e.py`
- Test: `backend/tests/test_learning_check_tool.py` (handler section)

**Interfaces:**
- Consumes: `_last_user_prompt_text` (already in the module), `register_function_handler`.
- Produces: constants `E2E_GRADER_CORRECT_TOKEN`, `E2E_GRADER_CONFIDENCE`, `E2E_GRADER_HINT`; handler for task `"grader"`.

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
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_check_tool.py -v -k e2e_grader`
Expected: FAIL — `UnregisteredHandlerError: SAPLING_MODEL_MODE=function but no handler is registered for task 'grader'`.

- [ ] **Step 3: Implement** — append to `backend/agents/function_handlers_e2e.py` (add `import re` at the top):

```python
# ── Learning loop grader (PKG-05) ───────────────────────────────────────────
#
# graded_check_tool runs grader_agent as its OWN call inside a tutor turn, so
# the E2E lane needs a handler. Content-driven in exactly one way: a student
# answer containing E2E_GRADER_CORRECT_TOKEN grades every rubric item yes,
# anything else every item no. Rubric ids come off the prompt's `RUBRIC ITEM
# <id>:` lines (agents/grader.py::build_grader_message), so any seeded item
# works. Emits through the OUTPUT tool → the real schema validates. Contract:
# tests/test_learning_check_tool.py; PKG-13's learn-loop.spec.ts types the token.

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
```

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_check_tool.py tests/test_learning_loop_invariants.py tests/test_e2e_function_handlers.py -q && venv/bin/ruff check .`
Expected: all passed (inv_06 now green); `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/agents/function_handlers_e2e.py backend/tests/test_learning_check_tool.py
git commit -m "feat(learning-loop): PKG-05 — function-mode grader handler (E2E_GRADER_*)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 4: `graded_check_tool`

**Files:**
- Replace stub: `backend/agents/tools/check.py`
- Test: `backend/tests/test_learning_check_tool.py` (tool section)

**Interfaces:**
- Consumes: `agents.grader.grade`, `services.check_item_service.get_by_question_hash` (name per HANDOFF-04), `learning.evidence.{Evidence, evidence_weight}`, `learning.params.{RUNG_ASSISTED_MIN, RUNG_ASSISTED_MAX, RUNG_NO_CREDIT_MIN}`.
- Produces: `agents.tools.check.{CheckAnswerInput, CHANNEL_FOR_FORMAT, GRADED_CHECK_TOOL_NAME, graded_check_tool, make_graded_check_tool, _load_item}`.

`evidence_weight`: if HANDOFF-03 lists it, use its signature. If not, do Task 5 first — it adds `evidence_weight(*, assisted, same_session_recheck, low_confidence) -> float` (product of the three `WEIGHT_*` for each True flag).

- [ ] **Step 1: Write the failing tests** — append:

```python
# ── graded_check_tool ─────────────────────────────────────────────────────


def _ctx(deps=None):
    return SimpleNamespace(deps=deps or _deps())


def _answer(**over):
    from agents.tools.check import CheckAnswerInput

    kw = dict(question_hash="qh-1", format="free", answer_text="It stops the calls.",
              selected_option=None, reason_text=None, confidence=None,
              max_rung_used=0, same_session_recheck=False)
    kw.update(over)
    return CheckAnswerInput(**kw)


@pytest.fixture
def check(monkeypatch):
    """The tool module with its two seams stubbed: item load + grader."""
    import agents.grader as g
    import agents.tools.check as c

    from agents.grader import GradeResult

    state = {"item": _item(), "result": GradeResult(item_results={"r1": True, "r2": True}, all_yes=True,
                                                     confidence=0.9, feedback_hint="Think about what stops the calls."),
             "grade_calls": []}

    def _load(qh):
        return state["item"] if qh == state["item"].question_hash else None

    async def _grade(item, *, format, student_answer, deps):
        state["grade_calls"].append((format, student_answer))
        return state["result"]

    monkeypatch.setattr(c, "_load_item", _load)
    monkeypatch.setattr(c, "grade", _grade)
    return c, state


def _run(check_mod, deps, answer):
    return asyncio.run(check_mod.graded_check_tool(_ctx(deps), answer))


def test_tool_is_inert_when_learning_loop_false(check):
    c, state = check
    deps = _deps(learning_loop=False)
    out = _run(c, deps, _answer())
    assert "not enabled" in out and deps.pending_evidence == [] and state["grade_calls"] == []


def test_idk_is_incorrect_idk_channel_without_grader(check):
    c, state = check
    deps = _deps()
    out = _run(c, deps, _answer(format="idk", answer_text="", max_rung_used=1))
    assert state["grade_calls"] == []
    [ev] = deps.pending_evidence
    assert ev["channel"] == "idk" and ev["correct"] is False and ev["weight"] == 1.0
    assert ev["node_id"] == "node-recursion" and ev["check_item_id"] == "ci-1"
    assert ev["question_hash"] == "qh-1" and ev["session_id"] == "s1"
    assert "don't know" in out.lower() or "idk" in out.lower()


@pytest.mark.parametrize("fmt,channel", [("free", "free_response"), ("teachback", "teachback_llm"), ("mc_reason", "mc_reasoned")])
def test_channel_mapping(check, fmt, channel):
    c, state = check
    state["item"] = _item(format=fmt, reference_answer="B" if fmt == "mc_reason" else REFERENCE)
    deps = _deps()
    _run(c, deps, _answer(format=fmt, selected_option="b", reason_text="because it stops"))
    [ev] = deps.pending_evidence
    assert ev["channel"] == channel and ev["correct"] is True


def test_mc_reason_wrong_option_is_incorrect_even_with_yes_rubric(check):
    c, state = check
    state["item"] = _item(format="mc_reason", reference_answer="B")
    deps = _deps()
    _run(c, deps, _answer(format="mc_reason", selected_option="C", reason_text="because"))
    [ev] = deps.pending_evidence
    assert ev["correct"] is False and ev["channel"] == "mc_reasoned"
    assert state["grade_calls"][0][1].startswith("Selected option: C")


def test_unassisted_correct_is_full_weight(check):
    c, _ = check
    deps = _deps()
    _run(c, deps, _answer())
    [ev] = deps.pending_evidence
    assert ev["correct"] is True and ev["assisted"] is False and ev["weight"] == 1.0 and ev["max_rung"] == 0
    assert ev["confidence"] == 0.9


def test_assisted_rungs_halve_weight(check):
    c, _ = check
    deps = _deps()
    _run(c, deps, _answer(max_rung_used=RUNG_ASSISTED_MAX))
    [ev] = deps.pending_evidence
    assert ev["assisted"] is True and ev["weight"] == WEIGHT_ASSISTED


def test_recheck_and_low_confidence_multiply(check):
    from agents.grader import GradeResult

    c, state = check
    state["result"] = GradeResult(item_results={"r1": True, "r2": True}, all_yes=True,
                                  confidence=GRADER_LOW_CONFIDENCE / 2, feedback_hint="h", low_confidence=True)
    deps = _deps()
    _run(c, deps, _answer(max_rung_used=RUNG_ASSISTED_MAX, same_session_recheck=True))
    [ev] = deps.pending_evidence
    assert ev["weight"] == pytest.approx(WEIGHT_ASSISTED * WEIGHT_SAME_SESSION_RECHECK * WEIGHT_LOW_CONFIDENCE)
    assert ev["same_session_recheck"] is True


def test_correct_after_h4_plus_has_zero_weight_but_is_appended(check):
    c, _ = check
    deps = _deps()
    out = _run(c, deps, _answer(max_rung_used=RUNG_NO_CREDIT_MIN))
    [ev] = deps.pending_evidence
    assert ev["correct"] is True and ev["weight"] == 0.0 and ev["max_rung"] == RUNG_NO_CREDIT_MIN
    assert ev["assisted"] is False
    assert "no upward credit" in out


def test_wrong_after_h4_plus_keeps_standard_weight(check):
    from agents.grader import GradeResult

    c, state = check
    state["result"] = GradeResult(item_results={"r1": True, "r2": False}, confidence=0.9,
                                  matched_wrong_key="w_loop", feedback_hint="h")
    deps = _deps()
    out = _run(c, deps, _answer(max_rung_used=RUNG_NO_CREDIT_MIN + 1))
    [ev] = deps.pending_evidence
    assert ev["correct"] is False and ev["weight"] == 1.0 and "w_loop" in out and "r2" in out


def test_pending_evidence_accumulates_across_calls(check):
    c, _ = check
    deps = _deps()
    _run(c, deps, _answer())
    _run(c, deps, _answer(same_session_recheck=True))
    assert len(deps.pending_evidence) == 2
    assert deps.pending_evidence[1]["weight"] == WEIGHT_SAME_SESSION_RECHECK


def test_grader_unavailable_appends_nothing_and_says_so(check):
    from agents.grader import GradeResult

    c, state = check
    state["result"] = GradeResult(unavailable=True)
    deps = _deps()
    out = _run(c, deps, _answer())
    assert deps.pending_evidence == [] and "unavailable" in out.lower()


def test_summary_never_contains_reference(check):
    c, _ = check
    for fmt in ("free", "teachback", "idk"):
        assert REFERENCE not in _run(c, _deps(), _answer(format=fmt))


def test_tool_never_touches_graph_tables(check, monkeypatch):
    """Spy on db.connection.table: the tool must not resolve ANY table."""
    import db.connection as dbconn

    names = []
    monkeypatch.setattr(dbconn, "table", lambda name, *a, **k: names.append(name) or SimpleNamespace())
    c, _ = check
    _run(c, _deps(), _answer())
    _run(c, _deps(), _answer(format="idk"))
    assert names == []


def test_tool_registers_with_wire_name_and_validates_input():
    """A throwaway agent with the real Tool: wire name + schema, no tutor needed."""
    from pydantic_ai import Agent
    from pydantic_ai.messages import TextPart

    from agents.tools.check import GRADED_CHECK_TOOL_NAME, make_graded_check_tool

    assert GRADED_CHECK_TOOL_NAME == "graded_check"
    seen = {}

    def handler(messages, info):
        seen["tools"] = [t.name for t in info.function_tools]
        return ModelResponse(parts=[TextPart(content="ok")])

    agent = Agent[SaplingDeps, str](model=FunctionModel(handler), deps_type=SaplingDeps,
                                    output_type=str, tools=[make_graded_check_tool()])
    agent.run_sync("hi", deps=_deps())
    assert seen["tools"] == ["graded_check"]
    assert make_graded_check_tool() is not make_graded_check_tool()
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_check_tool.py -v -k "tool or idk or channel or weight or recheck or h4 or pending or unavailable or reference or load_item"`
Expected: ERROR — `AttributeError: module 'agents.tools.check' has no attribute '_load_item'`.

- [ ] **Step 3: Implement** `backend/agents/tools/check.py`:

```python
"""graded_check_tool — the tutor's only strong-evidence source (PKG-05).

Turns one student answer into one learning.evidence Evidence dict on
`ctx.deps.pending_evidence`. NEVER persists: the route calls
learning.evidence.flush_pending once per turn (spec §5, §8.1; inv_14). No
db.connection import here by design. PKG-07 registers it (spec §7).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import RunContext, Tool

from agents.deps import SaplingDeps
from agents.grader import grade
from learning.evidence import Evidence, evidence_weight
from learning.params import RUNG_ASSISTED_MAX, RUNG_ASSISTED_MIN, RUNG_NO_CREDIT_MIN
from services import check_item_service

logger = logging.getLogger("sapling.agents.tools.check")

GRADED_CHECK_TOOL_NAME = "graded_check"

CHANNEL_FOR_FORMAT: dict[str, str] = {
    "free": "free_response",
    "teachback": "teachback_llm",
    "mc_reason": "mc_reasoned",
}


class CheckAnswerInput(BaseModel):
    """What the tutor model emits after the student answers a check item."""

    question_hash: str = Field(description="question_hash of the check item the student answered.")
    format: Literal["free", "teachback", "mc_reason", "idk"] = Field(
        description="The item format, or 'idk' when the student said they don't know."
    )
    answer_text: str = Field(default="", description="The student's answer verbatim (free/teachback).")
    selected_option: str | None = Field(default=None, description="mc_reason: the option the student chose.")
    reason_text: str | None = Field(default=None, description="mc_reason: the student's one-sentence reason.")
    confidence: float | None = Field(default=None, ge=0.0, le=1.0, description="Student-stated confidence, if given.")
    max_rung_used: int = Field(default=0, ge=0, le=6, description="Highest hint rung shown before this answer (0 = none).")
    same_session_recheck: bool = Field(default=False, description="True if this question_hash was already checked this session.")


def _load_item(question_hash: str):
    """Seam for tests. Name per HANDOFF-04 §Symbols added."""
    return check_item_service.get_by_question_hash(question_hash)


def _option_matches(selected: str | None, reference: str | None) -> bool:
    return bool(selected) and bool(reference) and " ".join(selected.split()).lower() == " ".join(reference.split()).lower()


def _summary(*, correct: bool, results: dict[str, bool], assisted: bool, max_rung: int,
             wrong_key: str, hint: str, no_credit: bool) -> str:
    items = ", ".join(f"{rid}: {'yes' if ok else 'no'}" for rid, ok in results.items())
    parts = [f"Graded {'correct' if correct else 'not yet correct'} ({items}).",
             f"Assisted: {'yes' if assisted else 'no'} (max rung {max_rung})."]
    parts += [f"Matched common wrong reason: {wrong_key}."] if wrong_key else []
    parts += ["Recorded with no upward credit; an isomorph is re-asked next session."] if no_credit else []
    parts += [f"Hint to adapt (never give the answer): {hint}"] if hint else []
    return " ".join(parts)


async def graded_check_tool(ctx: RunContext[SaplingDeps], answer: CheckAnswerInput) -> str:
    """Grade the student's answer to the current check item and record evidence.

    Call this exactly once per student answer to a check item, including when
    the student says they don't know (format 'idk'). Never reveal the
    reference answer; use the returned hint to shape your next turn.
    """
    deps = ctx.deps
    if not deps.learning_loop:
        return "graded_check is not enabled for this session."
    try:
        item = await asyncio.to_thread(_load_item, answer.question_hash)
    except Exception as exc:  # DB error → treated as missing, never raised into the agent loop
        logger.warning("graded_check: item load failed for %s: %s", answer.question_hash, exc)
        item = None
    if item is None:
        return "No check item matches that question_hash."

    common = dict(
        node_id=item.node_id,
        max_rung=answer.max_rung_used,
        session_id=deps.session_id,
        check_item_id=item.id,
        question_hash=answer.question_hash,
        same_session_recheck=answer.same_session_recheck,
    )
    assisted = RUNG_ASSISTED_MIN <= answer.max_rung_used <= RUNG_ASSISTED_MAX

    if answer.format == "idk":
        deps.pending_evidence.append(
            Evidence(channel="idk", correct=False, assisted=assisted, weight=1.0, confidence=None, **common).model_dump()
        )
        return (
            "Student answered 'I don't know'. Recorded as an incorrect attempt. "
            "Do not reveal the answer; offer the next rung the policy allows."
        )

    student_answer = answer.answer_text
    if answer.format == "mc_reason":
        student_answer = f"Selected option: {answer.selected_option or ''}\nReason: {answer.reason_text or ''}"
    result = await grade(item, format=answer.format, student_answer=student_answer, deps=deps)
    if result.unavailable:
        return "Grader unavailable; no evidence recorded. Ask the student to try again or rephrase."

    correct = result.all_yes
    if answer.format == "mc_reason":
        correct = correct and _option_matches(answer.selected_option, item.reference_answer)
    no_credit = correct and answer.max_rung_used >= RUNG_NO_CREDIT_MIN
    weight = 0.0 if no_credit else evidence_weight(
        assisted=assisted,
        same_session_recheck=answer.same_session_recheck,
        low_confidence=result.low_confidence,
    )
    deps.pending_evidence.append(
        Evidence(
            channel=CHANNEL_FOR_FORMAT[answer.format],
            correct=correct,
            assisted=assisted,
            weight=weight,
            confidence=result.confidence,
            **common,
        ).model_dump()
    )
    return _summary(
        correct=correct, results=result.item_results, assisted=assisted,
        max_rung=answer.max_rung_used, wrong_key=result.matched_wrong_key,
        hint=result.feedback_hint, no_credit=no_credit,
    )


def make_graded_check_tool() -> Tool:
    """A fresh Tool per agent (chat_tutor._build_tools registers fresh
    instances so no Tool object lands on two agents)."""
    return Tool(graded_check_tool, name=GRADED_CHECK_TOOL_NAME, takes_ctx=True)
```

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_check_tool.py tests/test_learning_loop_invariants.py -q && venv/bin/ruff check .`
Expected: all passed (inv_14 stays green with the real module); `All checks passed!`. If PKG-03's `Evidence` field set differs from spec §5, follow HANDOFF-03 and record a Deviation; never edit the model.

- [ ] **Step 5: Commit**

```
git add backend/agents/tools/check.py backend/tests/test_learning_check_tool.py
git commit -m "feat(learning-loop): PKG-05 — graded_check_tool accumulates Evidence on deps, never writes

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 5: `flush_pending` (reopens PKG-03)

**Files:**
- Modify: `backend/learning/evidence.py` (PKG-03's module — README "Touching an earlier package's code" applies: separate commit prefixed `fix(learning-loop): PKG-03 —`, ledger row `03 | reopened`, "Post-hoc changes" line in `HANDOFF-03.md`)
- Test: `backend/tests/test_learning_check_tool.py` (flush section)

**Interfaces:**
- Consumes: `services.graph_service.apply_graph_update` (local import).
- Produces: `learning.evidence.flush_pending(deps, course_id) -> list`; `learning.evidence.evidence_weight(...)` if HANDOFF-03 did not already provide it.

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
                                  {"node_id": "n1", "channel": "idk", "correct": False}])
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


def test_evidence_weight_products():
    from learning.evidence import evidence_weight

    assert evidence_weight(assisted=False, same_session_recheck=False, low_confidence=False) == 1.0
    assert evidence_weight(assisted=True, same_session_recheck=False, low_confidence=False) == WEIGHT_ASSISTED
    assert evidence_weight(assisted=True, same_session_recheck=True, low_confidence=True) == pytest.approx(
        WEIGHT_ASSISTED * WEIGHT_SAME_SESSION_RECHECK * WEIGHT_LOW_CONFIDENCE
    )
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_check_tool.py -v -k "flush or evidence_weight"`
Expected: FAIL — `AttributeError: module 'learning.evidence' has no attribute 'flush_pending'`.

- [ ] **Step 3: Implement** — append to `backend/learning/evidence.py` (keep everything PKG-03 wrote unchanged):

```python
def evidence_weight(*, assisted: bool, same_session_recheck: bool, low_confidence: bool) -> float:
    """Product of the applicable §3.1 observation weights; 1.0 when none apply."""
    w = 1.0
    if assisted:
        w *= WEIGHT_ASSISTED
    if same_session_recheck:
        w *= WEIGHT_SAME_SESSION_RECHECK
    if low_confidence:
        w *= WEIGHT_LOW_CONFIDENCE
    return w


def flush_pending(deps, course_id: str | None) -> list:
    """Persist `deps.pending_evidence` through the single graph writer, once.

    Called by the ROUTE after an agent turn (PKG-07), never by a tool. Errors
    propagate; the list is cleared only after a successful write so the
    route can decide whether to retry or report.
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

Skip `evidence_weight` if PKG-03 already provides it (the test then passes as-is). Import the three `WEIGHT_*` names from `learning.params` at the top of the module if they are not already imported.

- [ ] **Step 4: Run PKG-03's tests, this module, invariants, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_evidence_apply.py tests/test_graph_service.py tests/test_learning_check_tool.py tests/test_learning_loop_invariants.py -q && venv/bin/ruff check .`
Expected: all passed (inv_01 and inv_02 unchanged — `evidence.py` is not in `PURE_MODULES`); `All checks passed!`

- [ ] **Step 5: Reopen bookkeeping** — append to `HANDOFF-03.md` "Post-hoc changes": `PKG-05 <date>: added learning/evidence.py::flush_pending (+ evidence_weight if absent) — commit <sha>`; append ledger row `| 03 | evidence-state | reopened | feat/learning-loop-05-grader-check-tool | <sha> | +3 (in test_learning_check_tool.py) | PKG-05, <date>, tests/test_learning_evidence_apply.py → all passed | HANDOFF-03.md |`.

- [ ] **Step 6: Commit**

```
git add backend/learning/evidence.py backend/tests/test_learning_check_tool.py docs/superpowers/plans/learning-loop/HANDOFF-03.md docs/superpowers/plans/learning-loop/LEDGER.md
git commit -m "fix(learning-loop): PKG-03 — flush_pending: the route's one-call evidence persister (reopened by PKG-05)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 6: Eval dataset `tests/evals/grader.py`

**Files:**
- Create: `backend/tests/evals/grader.py`, `backend/tests/evals/cassettes/grader/*.json` (recorded)
- Modify: `backend/tests/evals/run_all.py` (`DATASETS` += `"grader"`), `backend/tests/evals/baselines.json` (`"grader"` block, written by the harness)

**Interfaces:**
- Consumes: `agents.grader.{grader_agent, GraderOutput, build_grader_message}`, `_replay.{run_with_cassette, cli_main}`, `learning.params.LEAK_NGRAM`.
- Produces: dataset `grader` with evaluators `NoReferenceLeakEvaluator`, `RubricAgreementEvaluator`, `StrictOnWrongEvaluator`, `ConfidenceInRangeEvaluator`.

- [ ] **Step 1: Write the dataset**

```python
"""pydantic-evals cases for grader_agent (learning loop PKG-05; spec §10 rung 1).
    cd backend && SAPLING_EVAL_MODE=record|replay python tests/evals/grader.py
One (item, student answer) per case, gold per-rubric labels in metadata. Gates:
NoReferenceLeak (hint shares no LEAK_NGRAM-token window with the reference),
StrictOnWrong (a gold-wrong answer never comes back all-yes), ConfidenceInRange;
RubricAgreement is measured, not assumed 1.0. Never hand-edit a case; add one on a miss.
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


@dataclass
class NoReferenceLeakEvaluator(Evaluator[GradeCase, GraderOutput]):
    def evaluate(self, ctx: EvaluatorContext[GradeCase, GraderOutput]) -> float:
        ref = _ngrams(_tokens(ctx.inputs.reference_answer), LEAK_NGRAM)
        hint = _ngrams(_tokens(ctx.output.feedback_hint if ctx.output else ""), LEAK_NGRAM)
        return 0.0 if ref & hint else 1.0


@dataclass
class RubricAgreementEvaluator(Evaluator[GradeCase, GraderOutput]):
    def evaluate(self, ctx: EvaluatorContext[GradeCase, GraderOutput]) -> float:
        gold: dict[str, bool] = (ctx.metadata or {}).get("gold", {})
        got = parse_item_results(ctx.output.item_results if ctx.output else [], list(gold))
        return sum(got[k] == v for k, v in gold.items()) / max(1, len(gold))


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
        ],
    )


if __name__ == "__main__":
    cli_main(make_dataset, _run)
```

- [ ] **Step 2: Record once** (needs `GEMINI_API_KEY` in `backend/.env`; `run_with_cassette` runs the agent without `usage_limits`, like every other dataset)

Run: `cd backend && SAPLING_EVAL_MODE=record venv/bin/python tests/evals/grader.py`
Expected: one cassette per case under `tests/evals/cassettes/grader/`. `NoReferenceLeakEvaluator`, `StrictOnWrongEvaluator`, `ConfidenceInRangeEvaluator` should each be `1.000`; if leak or strictness is below that, tighten those system-prompt lines, re-record, note the wording change in the hand-off. `RubricAgreementEvaluator` is measured, not assumed.

Then: `cd backend && SAPLING_EVAL_UPDATE_BASELINES=1 venv/bin/python tests/evals/grader.py` → `Updated baselines for grader`. Add `"grader"` to `DATASETS` in `run_all.py`.

No key available → do NOT add `"grader"` to `DATASETS` (an unbaselined dataset fails CI closed), commit the dataset file only, and write a Deviation + Known gap ("grader eval unrecorded; record + update baselines before PKG-07"); the canonical verify line cannot pass — say so in the ledger row.

- [ ] **Step 3: Replay + full harness**

Run: `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/grader.py && venv/bin/python tests/evals/run_all.py`
Expected: every evaluator ≥ baseline; `PASS grader` in the summary; no other dataset moves.

- [ ] **Step 4: Commit**

```
git add backend/tests/evals/grader.py backend/tests/evals/cassettes/grader backend/tests/evals/run_all.py backend/tests/evals/baselines.json
git commit -m "evals(learning-loop): PKG-05 — grader dataset (leak, agreement, strictness, confidence)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 7: Hand-off + ledger

- [ ] **Step 1:** Write `docs/superpowers/plans/learning-loop/HANDOFF-05.md` from `HANDOFF-template.md`. Symbols added must list: `agents.GRADER_LIMITS`; `agents/_providers.py::AgentTask "grader"`; `agents/grader.py::{GraderOutput, GradeResult, grader_agent, build_grader_message, parse_item_results, grade}`; `agents/tools/check.py::{CheckAnswerInput, CHANNEL_FOR_FORMAT, GRADED_CHECK_TOOL_NAME, graded_check_tool, make_graded_check_tool}`; `learning/evidence.py::flush_pending` (+ `evidence_weight` if added); `agents/function_handlers_e2e.py::{E2E_GRADER_CORRECT_TOKEN, E2E_GRADER_CONFIDENCE, E2E_GRADER_HINT}`; `tests/evals/grader.py` dataset `grader`; params names added. Constants chosen: the Named-constants table, `†` rows marked. Open questions: (a) whether `Evidence(channel="idk")` needs the item's format channel for the §3.1 idk likelihood (`S_IDK` with the format's `G`) — PKG-03 can recover it via `check_item_id → check_items.format`; option taken: `channel="idk"`; (b) PKG-06 must route `feedback_hint` through `leak.detect_leak` before the tutor sees it; (c) PKG-07 wires `flush_pending` after `stream_agent_turn`'s `on_complete` and decides the HTTP shape of an `apply_graph_update` failure. "Verify commands" must be exactly:

```
cd backend && venv/bin/python -m pytest tests/test_learning_check_tool.py -q                    → N passed (N ≥ 12)
grep -c '"grader"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py          → ≥ 1 each
grep -c "^async def graded_check_tool" backend/agents/tools/check.py                             → 1
cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/grader.py                     → every evaluator ≥ baseline
```

- [ ] **Step 2:** Ledger. Append `| 03 | evidence-state | verified | … | PKG-05, <date>, tests/test_learning_evidence_apply.py tests/test_graph_service.py -q → all passed | HANDOFF-03.md |` and `| 04 | check-items | verified | … | PKG-05, <date>, tests/test_learning_check_items.py -q → N passed | HANDOFF-04.md |` (the State-of-the-world rows you ran), then `| 05 | grader-check-tool | done | feat/learning-loop-05-grader-check-tool | <sha> | tests/test_learning_check_tool.py (N), inv_06 ext, inv_14, evals/grader | — | HANDOFF-05.md |`. Deviations: every `†` row, plus the `evidence_weight` addition if you made it, plus any narrowing of inv_14's `GRAPH_TABLE_CALLS`.

- [ ] **Step 3: Commit**

```
git add docs/superpowers/plans/learning-loop/HANDOFF-05.md docs/superpowers/plans/learning-loop/LEDGER.md
git commit -m "docs(learning-loop): PKG-05 — hand-off and ledger

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 8: PR

- [ ] **Step 1:** Run the self-check loop once more (below), then:

```
gh pr create --title "feat(learning): PKG-05 grader-check-tool" --body-file - <<'EOF'
Learning loop series, package 5 of 15. Spec: docs/superpowers/specs/2026-09-26-learning-loop-design.md §3.1, §3.3, §3.4, §5, §8.

- agents/grader.py: task "grader" (flash-lite), flat GraderOutput, sees the key, never solves, never restates; own agent call under GRADER_LIMITS charged via record_agent_usage; UsageLimitExceeded/UnexpectedModelBehavior → GradeResult(unavailable=True) + WARNING
- agents/tools/check.py: graded_check_tool → Evidence on deps.pending_evidence (idk / free / teachback / mc_reason; assisted + no-credit weights per §3.3); never writes a graph table (inv_14)
- learning/evidence.py::flush_pending — the route's one-call persister (PKG-03 reopened)
- function-mode grader handler (E2E_GRADER_*), tests/evals/grader.py (leak / agreement / strictness / confidence)
- Not registered on the tutor: PKG-07 does _build_tools(learning_loop=True). Flag-off behaviour byte-identical.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
```

## Self-check loop (run after every task, and once more before the PR)

1. `cd backend && venv/bin/ruff check . && venv/bin/ruff format --check learning tests/test_learning_*.py`
2. `venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q`
3. `venv/bin/python -m pytest tests/ -q` (no `SAPLING_MODEL_MODE` exported)
4. Prompts/tool descriptions touched? **Yes** (`agents/grader.py` prompt + `GraderOutput` descriptions; `CheckAnswerInput` descriptions + tool docstring) → once Task 6 exists, `SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/run_all.py` must pass; a prompt edit after recording means re-record `grader` and refresh its baseline. `chat_tutor` cassettes untouched.
5. Request-path agent or route touched? **Agent yes, route no.** No route calls the grader or the tool yet → skip the E2E cycle; the handler is proven in-process by `test_e2e_grader_handler_all_yes_on_token`. PKG-07 runs the stack.
6. Scope check: `git diff --stat main...HEAD` — every path must be in this prompt's Files lists. Anything else: `git checkout main -- <path>` or record a Deviation.
7. Sync check: `grep -o "E2E_[A-Z_]*" backend/agents/function_handlers_e2e.py | sort -u` differs from `main` by exactly `E2E_GRADER_CONFIDENCE`, `E2E_GRADER_CORRECT_TOKEN`, `E2E_GRADER_HINT`.

Green = all seven clean. Max 5 iterations per loop; then write a `BLOCKED` row in `LEDGER.md` with hypothesis, commands, outputs, and stop. Before the PR also run `grep -nE "[^A-Za-z_\"'][0-9]+\.[0-9]+" backend/agents/grader.py backend/agents/tools/check.py backend/learning/evidence.py` — only `ge=0.0, le=1.0` bounds and the `1.0`/`0.0` identity weights may print; every threshold and rung is a `learning.params` name.

## Regression guard

- Pre-series suite count N₀ (from State of the world) unchanged except for the tests this package adds. Zero failures, zero new skips outside `test_learning_loop_invariants.py`.
- Dependency suites green, their code unmodified except `learning/evidence.py` (Task 5, append-only): `tests/test_learning_evidence_apply.py`, `tests/test_graph_service.py` (PKG-03); `tests/test_learning_check_items.py` + `tests/evals/check_items.py` replay (PKG-04); `tests/test_learning_bkt.py`, `tests/test_learning_fsrs.py` (PKG-01/02).
- Pre-series suites touched: `tests/test_agent_output_schemas.py` (roster + budget), `tests/test_e2e_function_handlers.py` (existing `E2E_*` constants byte-identical), `tests/test_model_mode_seam.py`, `tests/test_event_capture_seams.py` (taxonomy pin untouched), `tests/evals/run_all.py` replay. `LEARNING_LOOP_ENABLED` unset or `true`: no route behaviour changes — nothing calls `grade`, the tool, or `flush_pending` until PKG-07.

## Acceptance criteria (the next session pastes these)

1. `cd backend && venv/bin/python -m pytest tests/test_learning_check_tool.py -q` → `N passed`, N ≥ 12
2. `grep -c '"grader"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py` → ≥ 1 each
3. `grep -c "^async def graded_check_tool" backend/agents/tools/check.py` → `1`
4. `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/grader.py` → every evaluator ≥ baseline (or the Known-gap note if unrecorded)
5. `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_06 or inv_14"` → `2 passed`
6. `cd backend && venv/bin/python -m pytest tests/ -q` → zero failures; `venv/bin/ruff check .` → `All checks passed!`
7. `grep -c "graded_check" backend/agents/chat_tutor.py backend/routes/learn.py` → `0` and `0`; `grep -c "from db.connection import\|apply_graph_update" backend/agents/tools/check.py` → `0`
8. `git diff --stat main...HEAD` lists only: `backend/agents/__init__.py`, `backend/agents/_providers.py`, `backend/agents/grader.py`, `backend/agents/tools/check.py`, `backend/agents/function_handlers_e2e.py`, `backend/learning/params.py`, `backend/learning/evidence.py`, `backend/tests/test_learning_check_tool.py`, `backend/tests/test_learning_loop_invariants.py`, `backend/tests/test_agent_output_schemas.py`, `backend/tests/evals/{grader.py,run_all.py,baselines.json,cassettes/grader/*}`, `docs/superpowers/plans/learning-loop/{HANDOFF-05.md,HANDOFF-03.md,LEDGER.md}`.
9. `LEDGER.md` has rows `03 | … | reopened`, `03 | … | verified`, `04 | … | verified`, `05 | grader-check-tool | done | …`.

## Hand-off

`docs/superpowers/plans/learning-loop/HANDOFF-05.md` per the template; the Verify commands block is fixed above (Task 7). Open questions to record are listed in Task 7 Step 1 — the idk channel shape, the leak-detector routing (PKG-06), and the `flush_pending` failure shape (PKG-07).

## Do not

- Do not register `graded_check` on any tutor agent or call `grade`/`flush_pending` from any route. Do not touch `agents/chat_tutor.py`, `routes/learn.py`, `services/chat_stream.py`, `services/events_service.py`, `services/graph_service.py`, `learning/checks.py`, `services/check_item_service.py`.
- Do not write `graph_nodes`/`graph_edges`/`node_mastery_events`/`learner_state` from a tool (inv_14). No `db.connection` import in `agents/tools/check.py`; no Supabase access anywhere in this package's new code (the item read is PKG-04's service).
- One prompt, one `Agent(` in `agents/grader.py` (inv_12). Never the reference answer, or anything derived from it, in the tool's return string.
- No event type (taxonomy is PKG-06's; WARNING logs are the degrade signal). No nested models in `GraderOutput`/`CheckAnswerInput` (`tests/test_agent_output_schemas.py` gates the budget).
- No numeric literals for weights/thresholds/rungs in `agents/grader.py`, `agents/tools/check.py`, `learning/evidence.py` — `learning/params.py` names only; `GRADER_LIMITS` values live in `agents/__init__.py` per spec §3.4.
- The grader never runs inside `TUTOR_LIMITS`: its own `agent.run` with `usage_limits=GRADER_LIMITS`.
- No migration, no `lru_cache`, no `httpx`, no `supabase` import.
- Do not skip, xfail, or delete any pre-existing test. Do not hand-edit eval cassettes or baselines (record + `SAPLING_EVAL_UPDATE_BASELINES=1` only).
- Logscan `ALLOWLIST` in `backend/e2e_oracles/logscan.py` stays `()`.
- End every commit with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`; end the PR body with the Claude Code attribution line.

## If you get stuck

1. Re-read §Spec and the spec file's §3.3 "Evidence mapping by rung", §3.4, §5 before guessing. HANDOFF-03/04 name a symbol differently → use the real name (not a deviation); lack one this prompt needs → add the smallest version under the reopen rule (Task 5 shape) and record it.
2. Three failed iterations on one task → append a `BLOCKED` row to `LEDGER.md` (hypothesis, commands run, outputs), commit what is green, open the PR as draft, stop.
3. Never widen scope to unblock. Never disable a test to unblock.
4. Ambiguity → choose the option closest to the spec, mark it `†` in the hand-off, continue.
