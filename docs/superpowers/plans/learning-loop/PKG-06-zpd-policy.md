# PKG-06 zpd-policy — Learning Loop series (7 of 15)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> You are a fresh session. Nothing outside this file, `docs/superpowers/plans/learning-loop/LEDGER.md`, `HANDOFF-00.md`/`HANDOFF-01.md`/`HANDOFF-02.md`/`HANDOFF-03.md`, and the files this prompt lists is known to you. Do not infer intent from chat history you do not have. Do not read the whole research corpus; read the sections named below.

## Package id + goal

**PKG-06 `zpd-policy`.** After this package: the ZPD policy layer exists in pure code — the hint ladder (`learning/ladder.py`), the ceiling/evidence/band/wheel-spin policy (`learning/policy.py`), the attempt and rung gates (`learning/gates.py`), the deterministic answer-leak detector and stripper (`learning/leak.py`); `sessions.loop_state` exists and round-trips through `learning/loop_state_store.py`; the six `zpd.*` event types are in `EVENT_TAXONOMY` with typed emit helpers in `learning/zpd_events.py`; invariants 4 and 5 are asserted. Nothing calls any of it yet: PKG-07 wires the loop tutor through it. `tests/test_learning_zpd_policy.py` proves it.

Branch: `feat/learning-loop-06-zpd-policy`. PR title: `feat(learning): PKG-06 zpd-policy`.

## Read before you start (in this order)

0. `docs/superpowers/specs/2026-09-26-learning-loop-design.md` **§13 Amendments log** — in force; where this file and §13 disagree, §13 wins. Re-read it before Task 1.
1. `docs/superpowers/plans/learning-loop/LEDGER.md` — refuse to start if any row is `blocked` or `in-progress`. Rows 00, 01, 02, 03 must be `done` or `verified`.
2. `docs/superpowers/plans/learning-loop/HANDOFF-03.md`, then `HANDOFF-01.md` (the constant names `params.py` actually exports) and `HANDOFF-02.md` (whether `fsrs.py` exports rating names).
3. `CLAUDE.md` §Conventions and §Gotchas — the standing rules the "Do not" list below repeats.
4. `docs/superpowers/specs/2026-09-26-learning-loop-design.md` §3.3 (ladder, ceiling, gates, bands — the table you implement exactly), §3.4 (`LEAK_NGRAM`, `ZPD_RATING_EVERY_N_CHECKS`), §4 (the PKG-06 DDL), §6 (events), §8 invariants 4 and 5, §9 (lazy sessions). Skim §3.1 for the band and weight names and §3.2 for the rating integers.
5. `docs/research/learning-loop/ZPD lever tradeoffs and upgrades.md` § "Sapling ZPD policy spec" (lines ~143–233: the STATE / LADDER / CEILING / GATES / BAND CONTROL / EVIDENCE MAPPING / LOG blocks — the spec's §3.3 is a transcription of this). Skip the rest.
6. `docs/research/learning-loop/AI tutor learning loop research.md` § "Guardrails: withhold answers, ground in verified solutions, gate the grader" (lines ~131–137, the paragraph on the deterministic solution stripper and the H7 reconciliation). Skip the rest.
7. `docs/superpowers/plans/learning-loop/README.md` — series conventions. `HANDOFF-template.md` — what you write at the end.
8. Code you will modify: `backend/services/events_service.py:97–170` (`EVENT_TAXONOMY` and the docstring table above it; `log_event` at :199), `backend/tests/test_event_capture_seams.py:84–120` (`test_event_taxonomy_is_pinned`), `backend/tests/test_learning_loop_invariants.py` (`test_inv_04`, `test_inv_05` placeholders), `backend/learning/{ladder,policy,gates,leak}.py` (PKG-00 docstring stubs), `backend/learning/params.py` (PKG-01; you may add names, never change values).
9. Code you will mirror: `backend/tests/test_graph_service.py:25–38` (`_mock_table` factory), `backend/tests/test_events_service.py:118–150` (patching `events_service.table` / `log_event` shape), `backend/db/connection.py:31–112` (`select(columns, filters=, limit=)`, `update(data, filters)` returns updated rows, `upsert(data, on_conflict=)`), `backend/routes/learn.py:36` and `:420–434` (lazy session row; `sessions` NOT NULL columns `user_id`, `mode`, `topic`), `backend/db/migrations/0025_study_integrity.sql:70–81` (the `sessions` table).

## State of the world

Verify the base before Task 1. Every row must be green.

| check | command | expected |
|---|---|---|
| hermetic suite green | `cd backend && venv/bin/python -m pytest tests/ -q -x` | `… passed` (note the count N₀) |
| lint green | `cd backend && venv/bin/ruff check .` | `All checks passed!` |
| PKG-00 | `cd backend && venv/bin/python -m pytest tests/test_learning_gate.py -q` | `11 passed` |
| PKG-00 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q` | `4 passed, 8 skipped (later packages raise the passed count)` — with 01/02/03 merged expect `≥ 6 passed` and `test_inv_04`/`test_inv_05` still skipped |
| PKG-00 | `cd backend && venv/bin/python -m pytest tests/test_learning_deps.py tests/test_learning_settings_flag.py tests/test_learning_loop_beta_migration.py -q` | `all passed` |
| PKG-00 | `grep -n "^LEARNING_LOOP_ENABLED" backend/config.py` | `1 hit` |
| PKG-00 | `ls backend/db/migrations/*_learning_loop_beta.sql` | `1 file` |
| PKG-01 | `cd backend && venv/bin/python -m pytest tests/test_learning_bkt.py -q` | `N passed (N ≥ 20)` |
| PKG-01 | `grep -cE "^def (update\|decayed_p\|propagate_prereq\|band\|tier_for)\(" backend/learning/bkt.py` | `5` |
| PKG-01 | `grep -cE "^[A-Z0-9_]+ = " backend/learning/params.py` | `≥ 40` |
| PKG-01 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k inv_03` | `1 passed` |
| PKG-02 | `cd backend && venv/bin/python -m pytest tests/test_learning_fsrs.py -q` | `N passed (N ≥ 15)` |
| PKG-02 | `grep -cE "^def (retrievability\|interval\|next_state\|rating_for\|order_due\|budget_select)\(" backend/learning/fsrs.py` | `6` |
| PKG-02 | `cd backend && venv/bin/python -c "from learning.params import FSRS_W; assert len(FSRS_W)==21; print('ok')"` | `ok` |
| PKG-03 | `cd backend && venv/bin/python -m pytest tests/test_learning_evidence_apply.py tests/test_graph_service.py -q` | `all passed` |
| PKG-03 | `ls backend/db/migrations/*_learning_learner_state.sql` | `1 file` |
| PKG-03 | `grep -c '"evidence"' backend/services/graph_service.py` | `≥ 1` |
| PKG-03 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k inv_01` | `1 passed` |
| stubs are stubs | `wc -l backend/learning/ladder.py backend/learning/policy.py backend/learning/gates.py backend/learning/leak.py` | each ≤ 5 lines (docstring only) |
| taxonomy untouched | `grep -c '"zpd\.' backend/services/events_service.py` | `0` |
| latest migration prefix | `ls backend/db/migrations \| tail -1` | a `2026…` timestamped file; your migration's prefix must sort after it |

Rule: any red row → STOP. Diagnose, repair on this branch as commit `fix(learning-loop): PKG-NN — <what>` (NN = the package whose row is red), record the deviation in `LEDGER.md` (row `NN | reopened`), append "Post-hoc changes" to that `HANDOFF-NN.md`, re-run all rows. Never build on a broken base. After the rows pass, mark row 03 `verified` in the ledger with today's date and the command → output.

## Spec

### Behaviour

1. `learning/ladder.py`: `class Rung(IntEnum)` with members `H0..H6` valued 0..6, `RUNG_INTENT: dict[Rung, str]` (what the tutor may emit at that rung — an instruction to the tutor, never prose for the student), `intent(rung) -> str`, `next_rung(rung) -> Rung` (clamped at `H6`).
2. `learning/policy.py` is pure and typed: dataclasses `StepState`, `LearnerView`, `LoopState`; enums `BandAction`, `CeilingReason`; functions `ceiling`, `ceiling_with_reason`, `attempt_first`, `evidence_for_rung`, `band_control`, `unassisted_rate`, `wheelspin`. No public function takes a `str` parameter; the module never imports `re` or `learning.gates` (invariant 4). Timestamps are `float` Unix seconds so tests pass fake clocks.
3. `ceiling(learner, step)` implements the spec §3.3 table as first-match over: `exam_mode` → `H1`; `profic` → `H1`, `H3` once `step.genuine_attempts ≥ CEILING_PROFIC_ESCALATE_FAILS`; `develop` → `H3 + genuine_attempts`, `H6` once `≥ CEILING_DEVELOP_H6_FAILS`; `novice` with `prereq_proficient` → `H5`; `novice` without → `H4` at zero attempts, `H5` after. Then the shown-work floor: `showed_work` raises the result to at least `H3`, except in exam mode (exam mode is the strictest row and wins). While a step is open, every recorded genuine attempt is a failed one (a correct attempt closes the step), so `genuine_attempts` is the failed-attempt count the table speaks of. `ceiling_with_reason` returns `(Rung, CeilingReason)`; `attempt_first(learner)` is `False` only for the novice-without-prerequisite row (worked example before any attempt).
4. `evidence_for_rung(correct, max_rung, same_session=False) -> RungEvidence(weight, counts_toward_streak, fsrs_rating)` per spec §3.3 "Evidence mapping": unassisted correct (`max_rung == H0`) → `(1.0, True, FSRS_RATING_GOOD)`; correct after `H1..H3` → `(WEIGHT_ASSISTED, False, FSRS_RATING_HARD)`; correct after `H4..H6` → `(0.0, False, FSRS_RATING_AGAIN)` — zero weight is the "no upward BKT evidence" signal PKG-07 turns into the isomorph re-ask; wrong at any rung → `(1.0, False, FSRS_RATING_AGAIN)`. `same_session=True` multiplies the weight by `WEIGHT_SAME_SESSION_RECHECK`.
5. `band_control(window, p_known, stable, *, wheelspin=False) -> BandAction`: `window` is the newest-last list of unassisted first-attempt outcomes (`bool`), at most `BAND_WINDOW × BAND_CONTROL_STOP_WINDOWS` long; the rate is the mean of the last `BAND_WINDOW`. `wheelspin` → `WHEELSPIN`; empty window → `HOLD`; rate `> BAND_CONTROL_HI` for both the last and the preceding full window AND `p_known ≥ BKT_PROFICIENT` AND `stable` → `STOP_PRACTICE`; rate `> BAND_CONTROL_HI` otherwise → `HARDER`; rate `< PRACTICE_TARGET_LO` → `EASIER_CHECK_PREREQS`; else `HOLD`.
6. `wheelspin(opps, ever_streak3, unassisted_next) -> bool` = `opps ≥ WHEELSPIN_OPPS and not ever_streak3`, or `opps ≥ WHEELSPIN_OPPS_EARLY and unassisted_next < WHEELSPIN_UNASSISTED_MAX` (`unassisted_next is None` never satisfies the second clause). The caller computes `ever_streak3 = max streak ever ≥ BKT_MASTERED_MIN_STRONG`.
7. `learning/gates.py`: `NON_ATTEMPT_PATTERNS` (exactly: `"just tell me"`, `"give me the answer"`, `"idk"`, `"i don't know"`, `"what's the answer"`), `matches_non_attempt(text) -> bool` (lowercase, apostrophes deleted, non-alphanumerics → space, whole-phrase match), `is_genuine_attempt(text_len_chars, has_shown_work, matched_non_attempt, independent_seconds, band) -> bool` (`False` when matched, when there is neither text nor shown work, or when `independent_seconds` is below `GATE_INDEPENDENT_MIN_S_NOVICE` for `novice` / `GATE_INDEPENDENT_MIN_S` otherwise), `rung_unlock(step, now) -> bool` (dwell since `last_rung_at`, or since `first_shown_at` when no rung was shown, `≥ GATE_RUNG_DWELL_MIN_S`, AND some `attempted_at` after that anchor), `h6_allowed(step, item_taught, item_graded) -> bool` (`genuine_attempts ≥ H6_MIN_GENUINE_ATTEMPTS and item_taught and not item_graded and not step.exam_mode`), `offer_allowed(band, last_attempt_wrong) -> bool` (`band in OFFER_BANDS and last_attempt_wrong`). Only `matches_non_attempt` sees text; callers append to `step.attempted_at` only when `is_genuine_attempt` is `True`.
8. `learning/leak.py`: `detect_leak(reference_answer, emitted, rung) -> LeakVerdict(leaked, detector)` with `detector ∈ {"none", "ngram", "final_answer"}`. `rung ≥ H6` → never leaked. `ngram`: any `LEAK_NGRAM` consecutive normalized tokens (`[a-z0-9]+` over lowercase) of the reference appear consecutively in the emitted text. `final_answer`: the reference's final answer — the text after its last `=`, else its last standalone number — tokenized the same way, appears as a consecutive token run in the emitted text. `final_answer(reference) -> tuple[str, ...]` is public (empty tuple when the reference has neither). `strip_leak(emitted, reference) -> str` replaces every leaked run with `[withheld]` until `detect_leak` at `H0` reports `none`; deterministic and idempotent.
9. Session loop state: migration adds `sessions.loop_state jsonb NOT NULL DEFAULT '{}'`. `LoopState.to_json()` / `LoopState.from_json()` (in `policy.py`, pure) serialise `{"v", "current", "checks_since_rating", "first_attempts", "steps": {question_hash: {rung, attempts, first_shown_at, last_rung_at, attempted_at, showed_work, exam_mode}}}` — ids, numbers, bools only; `from_json` raises `ValueError` on a malformed document. `learning/loop_state_store.py::load_loop_state(session_id) -> LoopState` (missing row or malformed JSON → fresh `LoopState()`, malformed logs WARNING) and `save_loop_state(session_id, state, *, session_row=None) -> bool` (`update` by id, `False` + WARNING when no row matched because the lazy session is not materialised yet; with `session_row={user_id, mode, topic[, offering_id]}` it `upsert`s on `id` instead, which is how PKG-07 materialises the row on the first loop turn).
10. Events: `zpd.step`, `zpd.offer`, `zpd.band_adjust`, `zpd.rating` (category `usage`) and `zpd.wheelspin`, `zpd.leak` (category `error`) join `EVENT_TAXONOMY`; `learning/zpd_events.py` exposes `emit_zpd_step`, `emit_zpd_offer`, `emit_zpd_band_adjust`, `emit_zpd_wheelspin`, `emit_zpd_leak`, `emit_zpd_rating`, keyword-only, payload keys exactly spec §6, values ids/counts/enums/bools only (no payload string longer than 64 chars — a sha256 `question_hash` is exactly 64).
11. Flag: nothing imports these modules outside `learning/` and `tests/` (a test proves it), so the flag-off product is byte-identical; the only runtime-visible changes are six extra `EVENT_TAXONOMY` strings (`log_event` does not enforce membership) and one jsonb column with a default.

### Schema (exact)

```sql
-- <ts>_learning_session_loop_state.sql
-- Learning loop series PKG-06: per-session ZPD loop state (spec §4, §9).
-- keyed by question_hash: {rung, attempts, first_shown_at, last_rung_at, attempted_at[]}; no free text.
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS loop_state jsonb NOT NULL DEFAULT '{}'::jsonb;
```

### Named constants

All live in `backend/learning/params.py`. Rows marked *exists* were written by PKG-01 — verify each with `grep -n "^NAME = " backend/learning/params.py`; if a name is missing, add it with the spec value and record "added by PKG-06" in the hand-off. Rows marked *new name* carry a value the spec states but does not name; add them (no `†`, the value is spec-given) and list them under "Constants chosen". `†` = engineering choice with no validated cut-point (spec §3.3), repeated in the hand-off.

| Name | Value | Spec | Status | Used by |
|---|---|---|---|---|
| `BAND_NOVICE_MAX` | 0.30 | §3.1 | exists | band names only (PKG-01 `bkt.band`) |
| `BAND_DEVELOP_MAX` | 0.80 | §3.1 | exists | same |
| `BKT_PROFICIENT` | 0.95 | §3.1 | exists | `band_control` STOP row |
| `BKT_MASTERED_MIN_STRONG` | 3 | §3.1 | exists | caller of `wheelspin` (`ever_streak3`) |
| `WEIGHT_ASSISTED` | 0.5 | §3.1 | exists | `evidence_for_rung` |
| `WEIGHT_SAME_SESSION_RECHECK` | 0.5 | §3.1 | exists | `evidence_for_rung` |
| `FSRS_RATING_AGAIN` / `_HARD` / `_GOOD` / `_EASY` | 1 / 2 / 3 / 4 | §3.2 rating map | new name unless PKG-02 exported equivalents (check `HANDOFF-02.md`; reuse theirs) | `evidence_for_rung` |
| `GATE_INDEPENDENT_MIN_S` | 45 † | §3.3 | exists | `is_genuine_attempt` |
| `GATE_INDEPENDENT_MIN_S_NOVICE` | 90 † | §3.3 | exists | `is_genuine_attempt` |
| `GATE_RUNG_DWELL_MIN_S` | 8 † | §3.3 | exists | `rung_unlock` |
| `H6_MIN_GENUINE_ATTEMPTS` | 2 | §3.3 | exists | `h6_allowed` |
| `OFFER_BANDS` | `frozenset({"novice"})` | §3.3 | exists | `offer_allowed` |
| `BAND_WINDOW` | 8 | §3.3 | exists | `band_control`, `LoopState` |
| `PRACTICE_TARGET_LO` | 0.65 | §3.3 bands | exists | `band_control` lower edge |
| `BAND_CONTROL_HI` | 0.90 | §3.3 band control (`> 0.90`) | new name | `band_control` |
| `BAND_CONTROL_STOP_WINDOWS` | 2 | §3.3 band control ("for 2 windows") | new name | `band_control`, `LoopState` trim |
| `CEILING_PROFIC_ESCALATE_FAILS` | 2 | §3.3 ceiling ("H3 after 2 failed") | new name | `ceiling` |
| `CEILING_DEVELOP_H6_FAILS` | 2 | §3.3 ceiling ("H6 after ≥ 2") | new name | `ceiling` |
| `WHEELSPIN_OPPS` | 10 | §3.3 | exists | `wheelspin` |
| `WHEELSPIN_OPPS_EARLY` | 6 | §3.3 wheelspin clause 2 | new name | `wheelspin` |
| `WHEELSPIN_UNASSISTED_MAX` | 0.50 | §3.3 wheelspin clause 2 | new name | `wheelspin` |
| `LEAK_NGRAM` | 6 | §3.4 | exists | `detect_leak` |
| `ZPD_RATING_EVERY_N_CHECKS` | 30 | §3.4 | exists | `LoopState.rating_due` |

The only bare numerals permitted in the new modules are `0`, `1`, `0.0`, `1.0` (identity / empty) and the `Rung` member values.

### Invariants asserted by this package (spec §8 numbering)

- (4) `policy.py`: no module-level public function has a parameter annotated `str`; the source contains neither `import re` nor `gates` nor `matches_non_attempt`. Asserted by AST scan in `test_inv_04_policy_takes_no_message_text`.
- (5) every `"zpd.…"`, `"learn.…"`, `"review.…"` string literal under `backend/` (excluding `tests/`, `venv/`) is a member of `EVENT_TAXONOMY`. Asserted by source grep in `test_inv_05_series_event_names_in_taxonomy`.
- (2) and (7) keep passing: the four pure modules import only `learning.*`, stdlib; `loop_state_store.py` has `from db.connection import table`.

### Error semantics

Pure modules never touch I/O and raise only on programmer error (`ValueError` from `LoopState.from_json`). `loop_state_store` fails soft: a malformed stored document or a missing row yields a fresh `LoopState()`; a save that matches no row returns `False` and logs WARNING — it never raises into a request. Event helpers delegate to `log_event`, which never raises. No agent runs here, so no ADR 0024 degrade path is touched.

### Events added

`zpd.step`, `zpd.offer`, `zpd.band_adjust`, `zpd.rating` (`usage`); `zpd.wheelspin`, `zpd.leak` (`error`). Payload keys per spec §6, ids/counts/enums only. Emitted by nobody in this package; PKG-07/08/10 call the helpers.

## Non-goals

- No route, agent, tool, prompt, or `chat_stream.py` change. No call to `learning.gate`. No frontend change.
- No LLM judge for leaks (the detector is deterministic; the judge is PKG-14's eval rung). No misconception logic (PKG-10), no probe/plan (PKG-08), no derived nightly metrics (`htc_k`, `assist_gap`, `in_zone` — PKG-14's `derive_zpd_metrics.py`).
- No change to `learner_state` or `apply_graph_update` (PKG-03 owns them). No `lru_cache`.

## Tasks

### Task 1: Invariants 4 and 5

**Files:**
- Modify: `backend/tests/test_learning_loop_invariants.py` (replace the two `pytest.skip` placeholders; add nothing else)

**Interfaces:**
- Consumes: `backend/learning/policy.py` source, every `*.py` under `backend/`, `services.events_service.EVENT_TAXONOMY`.
- Produces: `test_inv_04_policy_takes_no_message_text`, `test_inv_05_series_event_names_in_taxonomy`.

- [ ] **Step 1: Replace the placeholders**

Add `import ast` to the module imports, then:

```python
_TEXTLIKE_PARAM = re.compile(r"(message|text|answer|reply|prompt|content|utterance)", re.I)


def test_inv_04_policy_takes_no_message_text():
    src = (LEARNING / "policy.py").read_text()
    assert "matches_non_attempt" not in src, "policy.py must not reach the text gate"
    assert not re.search(r"^\s*(from|import)\s+(learning\.)?gates\b", src, re.M), "policy.py imports gates"
    assert not re.search(r"^\s*import\s+re\b", src, re.M), "policy.py must not process text"
    tree = ast.parse(src)
    offenders = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name.startswith("_"):
            continue
        for arg in node.args.args + node.args.kwonlyargs + node.args.posonlyargs:
            ann = ast.unparse(arg.annotation) if arg.annotation is not None else ""
            if ann == "str" or _TEXTLIKE_PARAM.search(arg.name):
                offenders.append(f"{node.name}({arg.name}: {ann or 'unannotated'})")
    assert not offenders, f"policy.py public functions take text-shaped params: {offenders}"
    assert any(isinstance(n, ast.FunctionDef) and n.name == "ceiling" for n in tree.body), "ceiling() missing"


_SERIES_EVENT_LITERAL = re.compile(r'"((?:zpd|learn|review)\.[a-z_]+)"')


def test_inv_05_series_event_names_in_taxonomy():
    from services.events_service import EVENT_TAXONOMY

    found: set[str] = set()
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND).parts
        if rel[0] in ("tests", "venv", ".venv"):
            continue
        for m in _SERIES_EVENT_LITERAL.finditer(path.read_text(errors="ignore")):
            found.add(m.group(1))
    assert found, "no series event literal found under backend/ — PKG-06 adds zpd.*"
    missing = sorted(found - EVENT_TAXONOMY)
    assert not missing, f"series event literals not in EVENT_TAXONOMY: {missing}"
```

- [ ] **Step 2: Run to see the current state**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -v -k "inv_04 or inv_05"`
Expected: `test_inv_04` FAIL — `ceiling() missing` (the stub has no functions); `test_inv_05` FAIL — `no series event literal found under backend/`.

- [ ] **Step 3: Commit**

```
git add backend/tests/test_learning_loop_invariants.py
git commit -m "test(learning-loop): PKG-06 — invariants 4 and 5

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 2: Params check + ladder

**Files:**
- Modify: `backend/learning/params.py` (add missing names only), `backend/learning/ladder.py`
- Create: `backend/tests/test_learning_zpd_policy.py`

**Interfaces:**
- Produces: `learning.ladder.Rung`, `RUNG_INTENT`, `intent(rung)`, `next_rung(rung)`; every name in §Named constants resolvable from `learning.params`.

- [ ] **Step 1: Write the failing test** (this file grows in every later task; keep the header once)

```python
"""PKG-06 ZPD policy layer (spec §3.3, §3.4, §4, §6). Pure-code tests: fake
clocks are floats, the only I/O is a mocked `table`."""
from __future__ import annotations

import logging
import pathlib
import re
from unittest.mock import MagicMock

import pytest

from learning import params

BACKEND = pathlib.Path(__file__).resolve().parents[1]
MIG_DIR = BACKEND / "db" / "migrations"

PARAM_NAMES = (
    "BKT_PROFICIENT", "BKT_MASTERED_MIN_STRONG", "WEIGHT_ASSISTED", "WEIGHT_SAME_SESSION_RECHECK",
    "FSRS_RATING_AGAIN", "FSRS_RATING_HARD", "FSRS_RATING_GOOD", "FSRS_RATING_EASY",
    "GATE_INDEPENDENT_MIN_S", "GATE_INDEPENDENT_MIN_S_NOVICE", "GATE_RUNG_DWELL_MIN_S",
    "H6_MIN_GENUINE_ATTEMPTS", "OFFER_BANDS", "BAND_WINDOW", "PRACTICE_TARGET_LO",
    "BAND_CONTROL_HI", "BAND_CONTROL_STOP_WINDOWS", "CEILING_PROFIC_ESCALATE_FAILS",
    "CEILING_DEVELOP_H6_FAILS", "WHEELSPIN_OPPS", "WHEELSPIN_OPPS_EARLY",
    "WHEELSPIN_UNASSISTED_MAX", "LEAK_NGRAM", "ZPD_RATING_EVERY_N_CHECKS",
)


# ── params + ladder ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", PARAM_NAMES)
def test_params_exports_every_pkg06_name(name):
    assert hasattr(params, name), f"learning.params lacks {name}"


def test_params_relations_hold():
    assert params.GATE_INDEPENDENT_MIN_S_NOVICE > params.GATE_INDEPENDENT_MIN_S > params.GATE_RUNG_DWELL_MIN_S
    assert params.PRACTICE_TARGET_LO < params.BAND_CONTROL_HI < params.BKT_PROFICIENT
    assert params.WHEELSPIN_OPPS_EARLY < params.WHEELSPIN_OPPS
    assert params.FSRS_RATING_AGAIN < params.FSRS_RATING_HARD < params.FSRS_RATING_GOOD < params.FSRS_RATING_EASY
    assert "novice" in params.OFFER_BANDS


def test_ladder_rungs_are_h0_to_h6_with_intent():
    from learning.ladder import RUNG_INTENT, Rung, intent, next_rung

    assert [r.name for r in Rung] == ["H0", "H1", "H2", "H3", "H4", "H5", "H6"]
    assert [int(r) for r in Rung] == list(range(len(Rung)))
    assert set(RUNG_INTENT) == set(Rung)
    for r in Rung:
        assert intent(r) and intent(r) == RUNG_INTENT[r]
    assert next_rung(Rung.H0) is Rung.H1
    assert next_rung(Rung.H6) is Rung.H6
    assert "never" in intent(Rung.H6).lower()  # practice only, never graded, never exam
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_zpd_policy.py -v`
Expected: the `FSRS_RATING_*`, `BAND_CONTROL_*`, `CEILING_*`, `WHEELSPIN_OPPS_EARLY`, `WHEELSPIN_UNASSISTED_MAX` param cases FAIL (`learning.params lacks …`) unless PKG-01/02 already named them; `test_ladder…` FAIL — `ImportError: cannot import name 'Rung'`.

- [ ] **Step 3: Implement**

`backend/learning/params.py` — append a `# PKG-06 (spec §3.3 / §3.2)` block containing only the names the grep in §Named constants showed missing, each with a one-line comment naming its spec row. If `HANDOFF-02.md` says `fsrs.py` exports rating constants under other names, do NOT add `FSRS_RATING_*`; instead alias them in `params.py` (`FSRS_RATING_AGAIN = <theirs>`) so this package's tests and PKG-07 have one spelling.

`backend/learning/ladder.py`:

```python
"""Hint ladder (spec §3.3). Pure: no imports beyond stdlib.

Each rung names what the tutor may emit. The text is an instruction to the
tutor prompt (PKG-07), never prose shown to the student.
"""
from __future__ import annotations

from enum import IntEnum


class Rung(IntEnum):
    H0 = 0
    H1 = 1
    H2 = 2
    H3 = 3
    H4 = 4
    H5 = 5
    H6 = 6


RUNG_INTENT: dict[Rung, str] = {
    Rung.H0: "Acknowledge or verify the student's correct step. No new information.",
    Rung.H1: "One pump or focus question (what is the first thing you need?). No content.",
    Rung.H2: "Concept pointer: cite the retrieved course passage or definition. No solution steps.",
    Rung.H3: "One leading question about the very next step only.",
    Rung.H4: "Worked example on an isomorph (different surface, same structure). Never the item itself.",
    Rung.H5: "Completion problem: partial solution with the last steps blanked (backward fade).",
    Rung.H6: "Full solution. Practice items only; never graded coursework; never exam mode.",
}


def intent(rung: Rung) -> str:
    return RUNG_INTENT[Rung(rung)]


def next_rung(rung: Rung) -> Rung:
    return Rung(min(int(rung) + 1, int(Rung.H6)))
```

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_zpd_policy.py tests/test_learning_bkt.py tests/test_learning_fsrs.py -q && venv/bin/ruff check .`
Expected: all passed (PKG-01/02 suites prove no value changed); `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/learning/params.py backend/learning/ladder.py backend/tests/test_learning_zpd_policy.py
git commit -m "feat(learning-loop): PKG-06 — hint ladder and policy constants

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 3: `policy.py` — state, ceiling, evidence, band control, wheel-spin

**Files:**
- Modify: `backend/learning/policy.py`, `backend/tests/test_learning_zpd_policy.py`

**Interfaces:**
- Consumes: `learning.ladder.Rung`, `learning.params`.
- Produces: `StepState`, `LearnerView`, `LoopState`, `Band`, `BandAction`, `CeilingReason`, `RungEvidence`, `ceiling`, `ceiling_with_reason`, `attempt_first`, `evidence_for_rung`, `unassisted_rate`, `band_control`, `wheelspin`.

- [ ] **Step 1: Write the failing tests** (append)

```python
# ── policy: ceiling table (spec §3.3, every row) ──────────────────────────────


def _learner(band, prereq=True, p=0.5, un=None, opps=0, streak=0):
    from learning.policy import LearnerView

    return LearnerView(p_known=p, band=band, prereq_proficient=prereq,
                       unassisted_next=un, opps=opps, streak_unassisted=streak)


def _step(fails=0, showed_work=False, exam=False, rung=0, first=1000.0, last=None, attempts=()):
    from learning.ladder import Rung
    from learning.policy import StepState

    return StepState(question_hash="q" * 64, rung=Rung(rung), genuine_attempts=fails,
                     first_shown_at=first, last_rung_at=last, attempted_at=list(attempts),
                     showed_work=showed_work, exam_mode=exam)


CEILING_CASES = [
    # (band, prereq, fails, showed_work, exam) -> rung name, reason name
    ("profic", True, 0, False, True, "H1", "EXAM"),
    ("develop", True, 3, True, True, "H1", "EXAM"),          # exam beats the shown-work floor
    ("profic", True, 0, False, False, "H1", "PROFIC"),
    ("profic", True, 1, False, False, "H1", "PROFIC"),
    ("profic", True, 2, False, False, "H3", "PROFIC_ESCALATED"),
    ("profic", True, 0, True, False, "H3", "SHOWED_WORK_FLOOR"),
    ("profic", True, 2, True, False, "H3", "PROFIC_ESCALATED"),  # already at the floor
    ("develop", True, 0, False, False, "H3", "DEVELOP"),
    ("develop", True, 1, False, False, "H4", "DEVELOP"),
    ("develop", True, 2, False, False, "H6", "DEVELOP_H6"),
    ("develop", True, 5, False, False, "H6", "DEVELOP_H6"),
    ("novice", True, 0, False, False, "H5", "NOVICE_PREREQ_OK"),
    ("novice", True, 3, False, False, "H5", "NOVICE_PREREQ_OK"),
    ("novice", False, 0, False, False, "H4", "NOVICE_WORKED_FIRST"),
    ("novice", False, 1, False, False, "H5", "NOVICE_PREREQ_GAP"),
    ("novice", False, 0, True, False, "H4", "NOVICE_WORKED_FIRST"),  # floor never lowers
]


@pytest.mark.parametrize("band,prereq,fails,showed,exam,rung,reason", CEILING_CASES)
def test_ceiling_table(band, prereq, fails, showed, exam, rung, reason):
    from learning.ladder import Rung
    from learning.policy import CeilingReason, ceiling, ceiling_with_reason

    learner, step = _learner(band, prereq), _step(fails=fails, showed_work=showed, exam=exam)
    assert ceiling(learner, step) is Rung[rung]
    assert ceiling_with_reason(learner, step) == (Rung[rung], CeilingReason[reason])


def test_ceiling_never_exceeds_h6_or_drops_below_floor():
    from learning.ladder import Rung
    from learning.policy import ceiling

    for band in ("novice", "develop", "profic"):
        for fails in range(0, 12):
            r = ceiling(_learner(band, True), _step(fails=fails, showed_work=True))
            assert Rung.H3 <= r <= Rung.H6


def test_attempt_first_false_only_for_novice_without_prereq():
    from learning.policy import attempt_first

    assert attempt_first(_learner("novice", prereq=False)) is False
    assert attempt_first(_learner("novice", prereq=True)) is True
    assert attempt_first(_learner("develop", prereq=False)) is True
    assert attempt_first(_learner("profic", prereq=False)) is True


# ── policy: evidence mapping ──────────────────────────────────────────────────

EVIDENCE_CASES = [
    # correct, max_rung, same_session -> weight, streak, rating
    (True, 0, False, 1.0, True, "FSRS_RATING_GOOD"),
    (True, 1, False, params.WEIGHT_ASSISTED, False, "FSRS_RATING_HARD"),
    (True, 3, False, params.WEIGHT_ASSISTED, False, "FSRS_RATING_HARD"),
    (True, 4, False, 0.0, False, "FSRS_RATING_AGAIN"),
    (True, 6, False, 0.0, False, "FSRS_RATING_AGAIN"),
    (False, 0, False, 1.0, False, "FSRS_RATING_AGAIN"),
    (False, 5, False, 1.0, False, "FSRS_RATING_AGAIN"),
    (True, 0, True, params.WEIGHT_SAME_SESSION_RECHECK, True, "FSRS_RATING_GOOD"),
    (True, 2, True, params.WEIGHT_ASSISTED * params.WEIGHT_SAME_SESSION_RECHECK, False, "FSRS_RATING_HARD"),
    (False, 0, True, params.WEIGHT_SAME_SESSION_RECHECK, False, "FSRS_RATING_AGAIN"),
]


@pytest.mark.parametrize("correct,rung,same,weight,streak,rating", EVIDENCE_CASES)
def test_evidence_for_rung_table(correct, rung, same, weight, streak, rating):
    from learning.ladder import Rung
    from learning.policy import evidence_for_rung

    ev = evidence_for_rung(correct, Rung(rung), same_session=same)
    assert ev == (pytest.approx(weight), streak, getattr(params, rating))
    assert ev.weight == pytest.approx(weight) and ev.counts_toward_streak is streak


# ── policy: band control + wheelspin ──────────────────────────────────────────

W = params.BAND_WINDOW


def _window(rate_last, rate_prev=None):
    """Newest-last bool window with an exact hit rate per BAND_WINDOW block."""
    def block(rate):
        hits = round(rate * W)
        return [True] * hits + [False] * (W - hits)
    return (block(rate_prev) if rate_prev is not None else []) + block(rate_last)


def test_band_control_table():
    from learning.policy import BandAction, band_control

    hi = params.BAND_CONTROL_HI + (1 - params.BAND_CONTROL_HI) / 2
    lo = params.PRACTICE_TARGET_LO / 2
    mid = (params.PRACTICE_TARGET_LO + params.BAND_CONTROL_HI) / 2
    p_ok, p_low = params.BKT_PROFICIENT, params.BKT_PROFICIENT - 0.01
    assert band_control([], p_ok, True) is BandAction.HOLD
    assert band_control(_window(1.0, 1.0), p_ok, True) is BandAction.STOP_PRACTICE
    assert band_control(_window(1.0, 1.0), p_ok, False) is BandAction.HARDER      # belief not stable
    assert band_control(_window(1.0, 1.0), p_low, True) is BandAction.HARDER      # p below proficient
    assert band_control(_window(1.0), p_ok, True) is BandAction.HARDER            # only one window high
    assert band_control(_window(1.0, mid), p_ok, True) is BandAction.HARDER       # previous window not high
    assert band_control(_window(hi), p_low, True) is BandAction.HARDER
    assert band_control(_window(mid), p_low, True) is BandAction.HOLD
    assert band_control(_window(lo), p_low, True) is BandAction.EASIER_CHECK_PREREQS
    assert band_control(_window(mid), p_ok, True, wheelspin=True) is BandAction.WHEELSPIN


def test_unassisted_rate_uses_last_window_only():
    from learning.policy import unassisted_rate

    assert unassisted_rate([]) is None
    assert unassisted_rate([False] * W + [True] * W) == pytest.approx(1.0)


def test_wheelspin_rule():
    from learning.policy import wheelspin

    n, e, u = params.WHEELSPIN_OPPS, params.WHEELSPIN_OPPS_EARLY, params.WHEELSPIN_UNASSISTED_MAX
    assert wheelspin(n, False, 0.9) is True
    assert wheelspin(n, True, 0.9) is False
    assert wheelspin(n - 1, False, None) is False
    assert wheelspin(e, True, u - 0.01) is True
    assert wheelspin(e, True, u) is False
    assert wheelspin(e - 1, False, 0.0) is False
    assert wheelspin(e, True, None) is False


# ── policy: LoopState round trip ──────────────────────────────────────────────


def test_loop_state_json_round_trip_and_trim():
    from learning.policy import LoopState

    s = LoopState()
    step = _step(fails=2, last=1010.0, attempts=(1005.0, 1020.0))
    s.steps[step.question_hash] = step
    s.current = step.question_hash
    for i in range(W * params.BAND_CONTROL_STOP_WINDOWS + 3):
        s.record_first_attempt(i % 2 == 0)
    assert len(s.first_attempts) == W * params.BAND_CONTROL_STOP_WINDOWS
    doc = s.to_json()
    assert set(doc) == {"v", "current", "checks_since_rating", "first_attempts", "steps"}
    assert set(doc["steps"][step.question_hash]) == {
        "rung", "attempts", "first_shown_at", "last_rung_at", "attempted_at", "showed_work", "exam_mode"
    }
    assert LoopState.from_json(doc) == s
    assert LoopState.from_json({}) == LoopState()
    with pytest.raises(ValueError):
        LoopState.from_json({"steps": "not-a-dict"})
    s.checks_since_rating = params.ZPD_RATING_EVERY_N_CHECKS - 1
    assert s.rating_due() is False
    s.checks_since_rating += 1
    assert s.rating_due() is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_zpd_policy.py -v -k "ceiling or evidence or band or wheelspin or loop_state or attempt_first or unassisted_rate"`
Expected: every case FAIL — `ImportError: cannot import name 'LearnerView' from 'learning.policy'`.

- [ ] **Step 3: Implement** `backend/learning/policy.py`

Structure (write it in full; cite `params.NAME`, never a numeral except `0`/`1`):

```python
"""ZPD policy (spec §3.3). Pure and typed: inputs are learner state and step
state, never student text (invariant 4). Timestamps are float Unix seconds."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, NamedTuple, Sequence

from learning import params
from learning.ladder import Rung

Band = Literal["novice", "develop", "profic"]
LOOP_STATE_VERSION = 1
WINDOW_KEEP = params.BAND_WINDOW * params.BAND_CONTROL_STOP_WINDOWS


class BandAction(str, Enum):
    STOP_PRACTICE = "stop_practice"
    HARDER = "harder"
    HOLD = "hold"
    EASIER_CHECK_PREREQS = "easier_check_prereqs"
    WHEELSPIN = "wheelspin"


class CeilingReason(str, Enum):
    EXAM = "exam"
    PROFIC = "profic"
    PROFIC_ESCALATED = "profic_escalated"
    DEVELOP = "develop"
    DEVELOP_H6 = "develop_h6"
    NOVICE_PREREQ_OK = "novice_prereq_ok"
    NOVICE_WORKED_FIRST = "novice_worked_first"
    NOVICE_PREREQ_GAP = "novice_prereq_gap"
    SHOWED_WORK_FLOOR = "showed_work_floor"


@dataclass
class StepState:
    question_hash: str
    rung: Rung = Rung.H0
    genuine_attempts: int = 0          # failed genuine attempts while the step is open
    first_shown_at: float = 0.0
    last_rung_at: float | None = None
    attempted_at: list[float] = field(default_factory=list)   # genuine attempts only
    showed_work: bool = False
    exam_mode: bool = False


@dataclass(frozen=True)
class LearnerView:
    p_known: float
    band: Band
    prereq_proficient: bool
    unassisted_next: float | None
    opps: int
    streak_unassisted: int


class RungEvidence(NamedTuple):
    weight: float
    counts_toward_streak: bool
    fsrs_rating: int
```

`ceiling_with_reason(learner, step)`: first-match rows in §Behaviour 3; `develop` computes `Rung(min(int(Rung.H3) + step.genuine_attempts, int(Rung.H6)))` below the H6 threshold; the floor is applied last and only when `not step.exam_mode` and the result `< Rung.H3`. `ceiling()` returns `ceiling_with_reason(...)[0]`. `attempt_first(learner)` = `not (learner.band == "novice" and not learner.prereq_proficient)`.

`evidence_for_rung(correct: bool, max_rung: Rung, same_session: bool = False) -> RungEvidence`: per §Behaviour 4; multiply by `params.WEIGHT_SAME_SESSION_RECHECK` when `same_session`.

`unassisted_rate(window: Sequence[bool]) -> float | None`: mean of `window[-params.BAND_WINDOW:]`, `None` when empty. `band_control(window: Sequence[bool], p_known: float, stable: bool, *, wheelspin: bool = False) -> BandAction`: per §Behaviour 5; the "previous window" is `window[-WINDOW_KEEP:-params.BAND_WINDOW]` and counts only when it holds exactly `params.BAND_WINDOW` entries. `wheelspin(opps: int, ever_streak3: bool, unassisted_next: float | None) -> bool`: per §Behaviour 6.

`LoopState` dataclass: `steps: dict[str, StepState]`, `current: str | None = None`, `checks_since_rating: int = 0`, `first_attempts: list[bool]`; `record_first_attempt(correct: bool)` appends and trims to the last `WINDOW_KEEP`; `rating_due()` is `checks_since_rating >= params.ZPD_RATING_EVERY_N_CHECKS`; `to_json()` emits `{"v": LOOP_STATE_VERSION, "current", "checks_since_rating", "first_attempts", "steps": {qh: {"rung": int, "attempts", "first_shown_at", "last_rung_at", "attempted_at", "showed_work", "exam_mode"}}}`; `from_json(data: dict)` is a `classmethod` that accepts `{}` (fresh state), ignores unknown keys, and raises `ValueError` when `steps`/`first_attempts` are not the expected container types or a step lacks a numeric `first_shown_at`.

- [ ] **Step 4: Run tests, lint, invariants**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_zpd_policy.py tests/test_learning_loop_invariants.py -q -k "not inv_05" && venv/bin/ruff check .`
Expected: all passed including `test_inv_04`; `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/learning/policy.py backend/tests/test_learning_zpd_policy.py
git commit -m "feat(learning-loop): PKG-06 — ZPD policy: ceiling, evidence mapping, band control, wheel-spin

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 4: `gates.py`

**Files:**
- Modify: `backend/learning/gates.py`, `backend/tests/test_learning_zpd_policy.py`

**Interfaces:**
- Consumes: `learning.params`, `learning.policy.StepState`.
- Produces: `NON_ATTEMPT_PATTERNS`, `matches_non_attempt`, `is_genuine_attempt`, `rung_unlock`, `h6_allowed`, `offer_allowed`.

- [ ] **Step 1: Write the failing tests** (append)

```python
# ── gates (spec §3.3 GATES) ───────────────────────────────────────────────────

IND, IND_N, DWELL = (
    params.GATE_INDEPENDENT_MIN_S, params.GATE_INDEPENDENT_MIN_S_NOVICE, params.GATE_RUNG_DWELL_MIN_S,
)


@pytest.mark.parametrize("text,expected", [
    ("just tell me", True), ("Just TELL me the steps", True), ("give me the answer!!", True),
    ("idk", True), ("IDK...", True), ("I don't know", True), ("i dont know", True),
    ("what's the answer", True), ("whats the answer?", True),
    ("I think the derivative is 2x", False), ("idkfa", False), ("the answer is 7", False), ("", False),
])
def test_matches_non_attempt(text, expected):
    from learning.gates import NON_ATTEMPT_PATTERNS, matches_non_attempt

    assert len(NON_ATTEMPT_PATTERNS) == 5
    assert matches_non_attempt(text) is expected


@pytest.mark.parametrize("chars,work,matched,secs,band,expected", [
    (12, False, False, IND, "develop", True),
    (12, False, False, IND - 1, "develop", False),
    (12, False, False, IND, "novice", False),          # novice needs the longer gate
    (12, False, False, IND_N, "novice", True),
    (0, True, False, IND, "profic", True),             # shown work counts without text
    (0, False, False, IND_N, "novice", False),         # nothing submitted
    (40, True, True, IND_N, "novice", False),          # non-attempt phrase wins
])
def test_is_genuine_attempt(chars, work, matched, secs, band, expected):
    from learning.gates import is_genuine_attempt

    assert is_genuine_attempt(chars, work, matched, secs, band) is expected


def test_rung_unlock_needs_dwell_and_an_attempt_since_last_rung():
    from learning.gates import rung_unlock

    t0 = 1000.0
    assert rung_unlock(_step(first=t0), now=t0 + DWELL) is False                      # no attempt yet
    assert rung_unlock(_step(first=t0, attempts=(t0 + 1,)), now=t0 + DWELL - 1) is False  # too soon
    assert rung_unlock(_step(first=t0, attempts=(t0 + 1,)), now=t0 + DWELL) is True
    shown = t0 + 50
    assert rung_unlock(_step(first=t0, last=shown, attempts=(t0 + 1,)), now=shown + DWELL) is False  # attempt predates rung
    assert rung_unlock(_step(first=t0, last=shown, attempts=(t0 + 1, shown + 2)), now=shown + DWELL) is True


def test_h6_allowed_and_offer_allowed():
    from learning.gates import h6_allowed, offer_allowed

    n = params.H6_MIN_GENUINE_ATTEMPTS
    assert h6_allowed(_step(fails=n), True, False) is True
    assert h6_allowed(_step(fails=n - 1), True, False) is False
    assert h6_allowed(_step(fails=n), False, False) is False       # not taught
    assert h6_allowed(_step(fails=n), True, True) is False         # graded coursework
    assert h6_allowed(_step(fails=n, exam=True), True, False) is False
    assert offer_allowed("novice", True) is True
    assert offer_allowed("novice", False) is False
    assert offer_allowed("develop", True) is False
    assert offer_allowed("profic", True) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_zpd_policy.py -v -k "non_attempt or genuine or rung_unlock or h6_allowed"`
Expected: FAIL — `ImportError: cannot import name 'matches_non_attempt' from 'learning.gates'`.

- [ ] **Step 3: Implement** `backend/learning/gates.py`

```python
"""Attempt, rung, H6 and offer gates (spec §3.3 GATES). Pure.

`matches_non_attempt` is the ONLY function in the policy layer that reads
student text, and it is a fixed phrase list, never a model. policy.py must
not import it (invariant 4)."""
from __future__ import annotations

import re

from learning import params
from learning.policy import Band, StepState

NON_ATTEMPT_PATTERNS: tuple[str, ...] = (
    "just tell me",
    "give me the answer",
    "idk",
    "i don't know",
    "what's the answer",
)

_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")


def _norm(text: str) -> str:
    text = text.lower().replace("’", "'").replace("'", "")
    return " ".join(_NON_ALNUM.sub(" ", text).split())


_NORMALIZED_PATTERNS = tuple(f" {_norm(p)} " for p in NON_ATTEMPT_PATTERNS)


def matches_non_attempt(text: str) -> bool:
    haystack = f" {_norm(text)} "
    return any(p in haystack for p in _NORMALIZED_PATTERNS)
```

Then `is_genuine_attempt`, `rung_unlock`, `h6_allowed`, `offer_allowed` exactly per §Behaviour 7 (`rung_unlock(step: StepState, now: float)`; anchor = `step.last_rung_at if step.last_rung_at is not None else step.first_shown_at`).

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_zpd_policy.py tests/test_learning_loop_invariants.py -q -k "not inv_05" && venv/bin/ruff check .`
Expected: all passed; `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/learning/gates.py backend/tests/test_learning_zpd_policy.py
git commit -m "feat(learning-loop): PKG-06 — attempt, rung, H6 and offer gates

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 5: `leak.py` — detector and stripper

**Files:**
- Modify: `backend/learning/leak.py`, `backend/tests/test_learning_zpd_policy.py`

**Interfaces:**
- Consumes: `learning.params.LEAK_NGRAM`, `learning.ladder.Rung`.
- Produces: `LeakVerdict`, `tokens`, `final_answer`, `detect_leak`, `strip_leak`.

- [ ] **Step 1: Write the failing tests** (append)

```python
# ── leak detector (spec §3.4 LEAK_NGRAM; research "Guardrails") ───────────────

REF_POWER = ("The derivative of x squared is two x because the power rule brings "
             "the exponent down and reduces it by one")
REF_EQ = "x + 3 = 10, so x = 7"
REF_VEL = "The final velocity is 9.8 m/s"
REF_SYM = "F = m a"

LEAKS = [
    (REF_POWER, "Remember: the power rule brings the exponent down, so try that.", "ngram"),
    (REF_POWER, "It reduces it by one and the power rule brings the exponent down.", "ngram"),
    (REF_EQ, "So x must be 7.", "final_answer"),
    (REF_EQ, "Check whether 7 satisfies the equation.", "final_answer"),
    (REF_VEL, "Plug in and you get 9.8 m/s.", "final_answer"),
    (REF_SYM, "Force is just m a, multiply them.", "final_answer"),
    (REF_POWER, "the derivative of x squared is two x", "ngram"),
]

SAFE = [
    (REF_POWER, "What rule applies when a variable is raised to a power?"),
    (REF_POWER, "Look at the exponent first. What happens to it?"),
    (REF_EQ, "Subtract 3 from both sides, then look at what is left."),
    (REF_EQ, "What operation undoes adding 3?"),
    (REF_VEL, "Which kinematic equation links acceleration and time?"),
    (REF_SYM, "What is force in terms of mass? Think about Newton's second law."),
    (REF_POWER, "The power rule is in section 2.3 of your notes; read the first line."),
]


@pytest.mark.parametrize("reference,emitted,detector", LEAKS)
def test_detect_leak_catches(reference, emitted, detector):
    from learning.ladder import Rung
    from learning.leak import detect_leak

    v = detect_leak(reference, emitted, Rung.H3)
    assert (v.leaked, v.detector) == (True, detector)


@pytest.mark.parametrize("reference,emitted", SAFE)
def test_detect_leak_zero_false_positives(reference, emitted):
    from learning.ladder import Rung
    from learning.leak import detect_leak, tokens

    assert detect_leak(reference, emitted, Rung.H0) == (False, "none")
    ref, em = tokens(reference), tokens(emitted)
    n = params.LEAK_NGRAM
    em_grams = {tuple(em[j:j + n]) for j in range(len(em) - n + 1)}
    assert not any(tuple(ref[i:i + n]) in em_grams for i in range(len(ref) - n + 1))


def test_h6_is_never_a_leak():
    from learning.ladder import Rung
    from learning.leak import detect_leak

    assert detect_leak(REF_EQ, REF_EQ, Rung.H6).leaked is False
    assert detect_leak(REF_EQ, REF_EQ, Rung.H5).leaked is True


def test_final_answer_extraction():
    from learning.leak import final_answer

    assert final_answer(REF_EQ) == ("7",)
    assert final_answer(REF_VEL) == ("9", "8")
    assert final_answer(REF_SYM) == ("m", "a")
    assert final_answer(REF_POWER) == ()
    assert final_answer("y = 2x + 3") == ("2x", "3")


@pytest.mark.parametrize("reference,emitted,_", LEAKS)
def test_strip_leak_makes_text_safe_and_is_idempotent(reference, emitted, _):
    from learning.ladder import Rung
    from learning.leak import detect_leak, strip_leak

    once = strip_leak(emitted, reference)
    assert "[withheld]" in once
    assert detect_leak(reference, once, Rung.H0).leaked is False
    assert strip_leak(once, reference) == once


@pytest.mark.parametrize("reference,emitted", SAFE)
def test_strip_leak_leaves_safe_text_unchanged(reference, emitted):
    from learning.leak import strip_leak

    assert strip_leak(emitted, reference) == emitted
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_zpd_policy.py -v -k "leak or final_answer"`
Expected: FAIL — `ImportError: cannot import name 'detect_leak' from 'learning.leak'`.

- [ ] **Step 3: Implement** `backend/learning/leak.py`

```python
"""Deterministic answer-leak detector + stripper (spec §3.4 LEAK_NGRAM). Pure.

Runs BEFORE any LLM judge on every tutor turn below H6 (research "Guardrails":
the supervisor architecture's deterministic solution stripper)."""
from __future__ import annotations

import re
from typing import Literal, NamedTuple

from learning import params
from learning.ladder import Rung

Detector = Literal["none", "ngram", "final_answer"]
WITHHELD = "[withheld]"

_TOKEN = re.compile(r"[a-z0-9]+")
_STANDALONE_NUMBER = re.compile(r"(?<!\w)(?<!\d\.)(-?\d+(?:\.\d+)?(?:/\d+)?)(?!\w)(?!\.\d)")


class LeakVerdict(NamedTuple):
    leaked: bool
    detector: Detector


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def final_answer(reference: str) -> tuple[str, ...]:
    """Token run of the reference's final answer: the text after its last '=',
    else its last standalone number; () when it has neither."""
    if "=" in reference:
        rhs = reference.rsplit("=", 1)[1]
        # keep only the clause up to the next sentence/clause break
        rhs = re.split(r"[,;]|\band\b|\bso\b", rhs, maxsplit=1)[0]
        return tuple(tokens(rhs))
    numbers = _STANDALONE_NUMBER.findall(reference)
    return tuple(tokens(numbers[-1])) if numbers else ()


def _ngrams(seq: list[str], n: int) -> set[tuple[str, ...]]:
    return {tuple(seq[i:i + n]) for i in range(len(seq) - n + 1)} if n > 0 else set()


def _contains_run(haystack: list[str], run: tuple[str, ...]) -> bool:
    return bool(run) and run in _ngrams(haystack, len(run))


def detect_leak(reference_answer: str, emitted: str, rung: Rung) -> LeakVerdict:
    if rung >= Rung.H6:
        return LeakVerdict(False, "none")
    ref, em = tokens(reference_answer), tokens(emitted)
    if _ngrams(ref, params.LEAK_NGRAM) & _ngrams(em, params.LEAK_NGRAM):
        return LeakVerdict(True, "ngram")
    if _contains_run(em, final_answer(reference_answer)):
        return LeakVerdict(True, "final_answer")
    return LeakVerdict(False, "none")


def _run_pattern(run: tuple[str, ...]) -> re.Pattern[str]:
    # tokens separated by any non-alphanumeric span, on token boundaries
    return re.compile(r"(?<![a-z0-9])" + r"[^a-z0-9]+".join(map(re.escape, run)) + r"(?![a-z0-9])", re.I)


def strip_leak(emitted: str, reference: str) -> str:
    out = emitted
    ref = tokens(reference)
    for gram in sorted(_ngrams(ref, params.LEAK_NGRAM)):
        out = _run_pattern(gram).sub(WITHHELD, out)
    answer = final_answer(reference)
    if answer:
        out = _run_pattern(answer).sub(WITHHELD, out)
    return out
```

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_zpd_policy.py tests/test_learning_loop_invariants.py -q -k "not inv_05" && venv/bin/ruff check .`
Expected: all passed; `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/learning/leak.py backend/tests/test_learning_zpd_policy.py
git commit -m "feat(learning-loop): PKG-06 — deterministic answer-leak detector and stripper

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 6: Migration `learning_session_loop_state` + `loop_state_store.py`

**Files:**
- Create: `backend/db/migrations/<UTC>_learning_session_loop_state.sql`, `backend/learning/loop_state_store.py`
- Modify: `backend/tests/test_learning_zpd_policy.py`

**Interfaces:**
- Consumes: `db.connection.table("sessions")`, `learning.policy.LoopState`.
- Produces: column `sessions.loop_state jsonb NOT NULL DEFAULT '{}'`; `load_loop_state(session_id) -> LoopState`; `save_loop_state(session_id, state, *, session_row=None) -> bool`.

- [ ] **Step 1: Write the failing tests** (append)

```python
# ── sessions.loop_state: migration + store ───────────────────────────────────


def test_migration_adds_loop_state_jsonb_default_empty():
    hits = sorted(MIG_DIR.glob("*_learning_session_loop_state.sql"))
    assert len(hits) == 1, f"expected exactly one loop_state migration, got {hits}"
    sql = hits[0].read_text()
    assert re.fullmatch(r"\d{14}_learning_session_loop_state\.sql", hits[0].name)
    assert re.search(r"ALTER TABLE sessions ADD COLUMN IF NOT EXISTS loop_state jsonb NOT NULL DEFAULT '\{\}'::jsonb;", sql)
    assert "PKG-06" in sql


def _sessions_table(select_rows=None, update_rows=None):
    mock = MagicMock(name="sessions")
    mock.select.return_value = select_rows if select_rows is not None else []
    mock.update.return_value = update_rows if update_rows is not None else []
    mock.upsert.return_value = [{"id": "s1"}]
    return mock


def test_load_loop_state_reads_by_session_id_and_round_trips(monkeypatch):
    from learning import loop_state_store
    from learning.policy import LoopState

    state = LoopState(current="q" * 64, checks_since_rating=4)
    state.steps[state.current] = _step(fails=1, attempts=(1001.0,))
    t = _sessions_table(select_rows=[{"loop_state": state.to_json()}])
    monkeypatch.setattr(loop_state_store, "table", lambda name: t if name == "sessions" else None)
    assert loop_state_store.load_loop_state("s1") == state
    t.select.assert_called_once_with("loop_state", filters={"id": "eq.s1"}, limit=1)


def test_load_loop_state_missing_row_or_garbage_is_fresh(monkeypatch, caplog):
    from learning import loop_state_store
    from learning.policy import LoopState

    monkeypatch.setattr(loop_state_store, "table", lambda name: _sessions_table(select_rows=[]))
    assert loop_state_store.load_loop_state("s1") == LoopState()
    monkeypatch.setattr(loop_state_store, "table",
                        lambda name: _sessions_table(select_rows=[{"loop_state": {"steps": 5}}]))
    with caplog.at_level(logging.WARNING):
        assert loop_state_store.load_loop_state("s1") == LoopState()
    assert any("loop_state" in r.getMessage() for r in caplog.records)


def test_save_loop_state_updates_by_id_and_reports_missing_row(monkeypatch, caplog):
    from learning import loop_state_store
    from learning.policy import LoopState

    state = LoopState(checks_since_rating=1)
    t = _sessions_table(update_rows=[{"id": "s1"}])
    monkeypatch.setattr(loop_state_store, "table", lambda name: t)
    assert loop_state_store.save_loop_state("s1", state) is True
    t.update.assert_called_once_with({"loop_state": state.to_json()}, filters={"id": "eq.s1"})
    t.upsert.assert_not_called()

    lazy = _sessions_table(update_rows=[])
    monkeypatch.setattr(loop_state_store, "table", lambda name: lazy)
    with caplog.at_level(logging.WARNING):
        assert loop_state_store.save_loop_state("s1", state) is False
    assert any("not materialised" in r.getMessage() for r in caplog.records)


def test_save_loop_state_with_session_row_upserts_on_id(monkeypatch):
    from learning import loop_state_store
    from learning.policy import LoopState

    t = _sessions_table()
    monkeypatch.setattr(loop_state_store, "table", lambda name: t)
    row = {"user_id": "user_andres", "mode": "socratic", "topic": "limits", "offering_id": "off1"}
    assert loop_state_store.save_loop_state("s1", LoopState(), session_row=row) is True
    t.upsert.assert_called_once_with({**row, "id": "s1", "loop_state": LoopState().to_json()}, on_conflict="id")
    t.update.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_zpd_policy.py -v -k "migration or loop_state_store or save_loop_state or load_loop_state"`
Expected: `test_migration…` FAIL — `expected exactly one loop_state migration, got []`; the rest FAIL — `ImportError: cannot import name 'loop_state_store'`.

- [ ] **Step 3: Write the migration and the store**

Prefix from `date -u +%Y%m%d%H%M%S`; content is §Spec/Schema verbatim including both comment lines.

`backend/learning/loop_state_store.py`:

```python
"""sessions.loop_state read/write (spec §4 PKG-06, §9). The only impure module
in the ZPD layer; policy.py stays free of db imports.

Sessions are lazy (routes/learn.py:36): the row may not exist until the first
chat turn. `save_loop_state` therefore updates by id and reports a miss; a
caller that owns the first loop turn passes `session_row` to materialise."""
from __future__ import annotations

import logging

from db.connection import table
from learning.policy import LoopState

logger = logging.getLogger("sapling.learning.loop_state")


def load_loop_state(session_id: str) -> LoopState:
    rows = table("sessions").select("loop_state", filters={"id": f"eq.{session_id}"}, limit=1)
    if not rows:
        return LoopState()
    try:
        return LoopState.from_json(rows[0].get("loop_state") or {})
    except (ValueError, TypeError, KeyError) as exc:
        logger.warning("load_loop_state: malformed loop_state for %s (%s); starting fresh", session_id, exc)
        return LoopState()


def save_loop_state(session_id: str, state: LoopState, *, session_row: dict | None = None) -> bool:
    doc = state.to_json()
    if session_row is not None:
        table("sessions").upsert({**session_row, "id": session_id, "loop_state": doc}, on_conflict="id")
        return True
    rows = table("sessions").update({"loop_state": doc}, filters={"id": f"eq.{session_id}"})
    if not rows:
        logger.warning("save_loop_state: sessions row %s not materialised; loop_state not saved", session_id)
        return False
    return True
```

- [ ] **Step 4: Run tests, lint, invariants**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_zpd_policy.py tests/test_learning_loop_invariants.py -q -k "not inv_05" && venv/bin/ruff check .`
Expected: all passed (`test_inv_07` sees `from db.connection import` in the store; `test_inv_08` accepts the new basename); `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/db/migrations/*_learning_session_loop_state.sql backend/learning/loop_state_store.py backend/tests/test_learning_zpd_policy.py
git commit -m "feat(learning-loop): PKG-06 — sessions.loop_state migration and store

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 7: `zpd.*` events — taxonomy, pin test, typed emit helpers, inertness proof

**Files:**
- Modify: `backend/services/events_service.py` (`EVENT_TAXONOMY` + docstring table), `backend/tests/test_event_capture_seams.py` (`test_event_taxonomy_is_pinned`), `backend/tests/test_learning_zpd_policy.py`
- Create: `backend/learning/zpd_events.py`

**Interfaces:**
- Consumes: `services.events_service.log_event`.
- Produces: six taxonomy members; `emit_zpd_step`, `emit_zpd_offer`, `emit_zpd_band_adjust`, `emit_zpd_wheelspin`, `emit_zpd_leak`, `emit_zpd_rating`.

- [ ] **Step 1: Write the failing tests** (append)

```python
# ── zpd.* events (spec §6) ────────────────────────────────────────────────────

PAYLOAD_STR_MAX = 64  # a sha256 question_hash is exactly this long; nothing longer is an id


def _recorder(monkeypatch):
    from learning import zpd_events

    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(zpd_events, "log_event", lambda et, **kw: calls.append((et, kw)))
    return calls


def _assert_ids_only(value):
    if isinstance(value, str):
        assert len(value) <= PAYLOAD_STR_MAX, f"payload string too long: {value[:20]}…"
    elif isinstance(value, dict):
        for v in value.values():
            _assert_ids_only(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _assert_ids_only(v)
    else:
        assert value is None or isinstance(value, (bool, int, float)), type(value)


def test_zpd_events_in_taxonomy_with_spec_categories():
    from services.events_service import EVENT_TAXONOMY

    for et in ("zpd.step", "zpd.offer", "zpd.band_adjust", "zpd.wheelspin", "zpd.leak", "zpd.rating"):
        assert et in EVENT_TAXONOMY


def test_emit_helpers_send_spec_payloads(monkeypatch):
    from learning import zpd_events
    from learning.ladder import Rung
    from learning.policy import BandAction, CeilingReason

    calls = _recorder(monkeypatch)
    common = dict(user_id="user_andres", request_id="req-1")
    zpd_events.emit_zpd_step(
        **common, concept_id="node-1", question_hash="q" * 64, phase="check", channel="free_response",
        band="develop", ceiling=Rung.H3, ceiling_reason=CeilingReason.DEVELOP, first_attempt_correct=False,
        n_attempts=2, max_rung_used=Rung.H2, rungs=[{"rung": 1, "dwell_ms": 9000}, {"rung": 2, "dwell_ms": 12000}],
        time_to_first_attempt_ms=61000, time_to_correct_ms=140000, independent_time_ms=61000, assisted=True,
        confidence=0.8, fsrs_rating=params.FSRS_RATING_HARD, p_known_before=0.41, p_known_after=0.52,
        r_before=0.93, item_difficulty=2,
    )
    zpd_events.emit_zpd_offer(**common, accepted=True, band="novice")
    zpd_events.emit_zpd_band_adjust(**common, direction=BandAction.HARDER, trigger="high",
                                    window_stats={"n": 8, "rate": 1.0})
    zpd_events.emit_zpd_wheelspin(**common, concept_id="node-1", opps=11, unassisted_next=0.3, htc_k=2.5,
                                  prerequisite_ids=["node-0"])
    zpd_events.emit_zpd_leak(**common, rung_emitted=Rung.H6, ceiling=Rung.H3, detector="ngram")
    zpd_events.emit_zpd_rating(**common, rating="too_hard", checks_since_last=params.ZPD_RATING_EVERY_N_CHECKS)

    got = {et: kw for et, kw in calls}
    assert set(got) == {"zpd.step", "zpd.offer", "zpd.band_adjust", "zpd.wheelspin", "zpd.leak", "zpd.rating"}
    assert {et: kw["category"] for et, kw in calls} == {
        "zpd.step": "usage", "zpd.offer": "usage", "zpd.band_adjust": "usage",
        "zpd.wheelspin": "error", "zpd.leak": "error", "zpd.rating": "usage",
    }
    assert set(got["zpd.step"]["payload"]) == {
        "concept_id", "question_hash", "phase", "channel", "band", "ceiling", "ceiling_reason",
        "first_attempt_correct", "n_attempts", "max_rung_used", "rungs", "time_to_first_attempt_ms",
        "time_to_correct_ms", "independent_time_ms", "assisted", "confidence", "fsrs_rating",
        "p_known_before", "p_known_after", "r_before", "item_difficulty",
    }
    assert got["zpd.step"]["payload"]["ceiling"] == int(Rung.H3)
    assert got["zpd.step"]["payload"]["ceiling_reason"] == "develop"
    assert set(got["zpd.offer"]["payload"]) == {"accepted", "band"}
    assert set(got["zpd.band_adjust"]["payload"]) == {"direction", "trigger", "window_stats"}
    assert got["zpd.band_adjust"]["payload"]["direction"] == "harder"
    assert set(got["zpd.wheelspin"]["payload"]) == {"concept_id", "opps", "unassisted_next", "htc_k", "prerequisite_ids"}
    assert set(got["zpd.leak"]["payload"]) == {"rung_emitted", "ceiling", "detector", "request_id"}
    assert set(got["zpd.rating"]["payload"]) == {"rating", "checks_since_last"}
    for et, kw in calls:
        assert kw["user_id"] == "user_andres" and kw["request_id"] == "req-1"
        _assert_ids_only(kw["payload"])


def test_emit_helpers_reach_log_event_without_raising(monkeypatch):
    """Through the real events_service: enqueue only, worker never runs here."""
    from learning import zpd_events
    from services import events_service

    rows: list = []
    monkeypatch.setattr(events_service, "table", lambda name: MagicMock(insert=lambda r: rows.append((name, r)) or r))
    zpd_events.emit_zpd_offer(user_id="u", request_id="r", accepted=False, band="novice")
    events_service.flush_now()
    assert any(row["event_type"] == "zpd.offer" for _, batch in rows for row in batch)


def test_zpd_layer_is_inert_nothing_imports_it():
    mods = ("learning.policy", "learning.gates", "learning.leak", "learning.ladder",
            "learning.loop_state_store", "learning.zpd_events")
    pat = re.compile(r"^\s*(from|import)\s+(" + "|".join(map(re.escape, mods)) + r")\b", re.M)
    offenders = []
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND).parts
        if rel[0] in ("tests", "learning", "venv", ".venv"):
            continue
        if pat.search(path.read_text(errors="ignore")):
            offenders.append(str(path.relative_to(BACKEND)))
    assert offenders == [], f"PKG-06 modules must stay unreferenced until PKG-07: {offenders}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_zpd_policy.py -v -k "zpd_events or emit_helpers or inert"`
Expected: `test_zpd_events_in_taxonomy…` FAIL — `assert 'zpd.step' in frozenset(...)`; `test_emit_helpers…` FAIL — `ImportError: cannot import name 'zpd_events'`; `test_zpd_layer_is_inert…` PASS.

- [ ] **Step 3: Implement**

`backend/services/events_service.py` — append to `EVENT_TAXONOMY`, after `"rag.visibility_resync_failed",`:

```python
    # Learning loop series PKG-06 (spec §6): the ZPD policy layer's log. Emitted
    # by learning/zpd_events.py only; nothing fires them until PKG-07 wires
    # the loop tutor. Payloads are ids/counts/enums — the question_hash is a
    # sha256, never the prompt. wheelspin and leak are category="error": a
    # stuck student and a revealed answer are both things an admin must count.
    "zpd.step",
    "zpd.offer",
    "zpd.band_adjust",
    "zpd.wheelspin",
    "zpd.leak",
    "zpd.rating",
```

Add six rows to the docstring table above it (event, category, payload keys from spec §6) — without quotes, so `grep -c '"zpd\.'` on the file stays exactly 6.

`backend/tests/test_event_capture_seams.py::test_event_taxonomy_is_pinned` — add the same six strings with a one-line `# PKG-06 (spec §6); emit coverage in test_learning_zpd_policy.py` comment.

`backend/learning/zpd_events.py`:

```python
"""Typed emit helpers for the zpd.* events (spec §6). Payloads carry ids,
counts, enums and bools only — never student or tutor text."""
from __future__ import annotations

from typing import Literal

from learning.ladder import Rung
from learning.policy import Band, BandAction, CeilingReason
from services.events_service import log_event

Phase = Literal["probe", "plan", "teach", "check", "feedback", "close"]
Rating = Literal["too_easy", "appropriate", "too_hard"]
Detector = Literal["none", "ngram", "final_answer"]
BandTrigger = Literal["high", "stable_high", "low", "wheelspin"]


def emit_zpd_step(*, user_id: str, request_id: str | None, concept_id: str, question_hash: str,
                  phase: Phase, channel: str, band: Band, ceiling: Rung, ceiling_reason: CeilingReason,
                  first_attempt_correct: bool, n_attempts: int, max_rung_used: Rung, rungs: list[dict],
                  time_to_first_attempt_ms: int | None, time_to_correct_ms: int | None,
                  independent_time_ms: int | None, assisted: bool, confidence: float | None,
                  fsrs_rating: int, p_known_before: float, p_known_after: float,
                  r_before: float | None, item_difficulty: int) -> None:
    log_event("zpd.step", category="usage", user_id=user_id, request_id=request_id, payload={
        "concept_id": concept_id, "question_hash": question_hash, "phase": phase, "channel": channel,
        "band": band, "ceiling": int(ceiling), "ceiling_reason": ceiling_reason.value,
        "first_attempt_correct": first_attempt_correct, "n_attempts": n_attempts,
        "max_rung_used": int(max_rung_used), "rungs": [{"rung": int(r["rung"]), "dwell_ms": int(r["dwell_ms"])} for r in rungs],
        "time_to_first_attempt_ms": time_to_first_attempt_ms, "time_to_correct_ms": time_to_correct_ms,
        "independent_time_ms": independent_time_ms, "assisted": assisted, "confidence": confidence,
        "fsrs_rating": fsrs_rating, "p_known_before": p_known_before, "p_known_after": p_known_after,
        "r_before": r_before, "item_difficulty": item_difficulty,
    })
```

Then `emit_zpd_offer(*, user_id, request_id, accepted: bool, band: Band)`, `emit_zpd_band_adjust(*, user_id, request_id, direction: BandAction, trigger: BandTrigger, window_stats: dict)` (payload `direction=direction.value`), `emit_zpd_wheelspin(*, user_id, request_id, concept_id, opps: int, unassisted_next: float | None, htc_k: float | None, prerequisite_ids: list[str])` (category `error`), `emit_zpd_leak(*, user_id, request_id, rung_emitted: Rung, ceiling: Rung, detector: Detector)` (category `error`; payload includes `request_id` per spec §6, ints for the rungs), `emit_zpd_rating(*, user_id, request_id, rating: Rating, checks_since_last: int)`. Every payload key set is exactly the spec §6 row.

- [ ] **Step 4: Run tests, lint, invariants, the pinned seams**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_zpd_policy.py tests/test_learning_loop_invariants.py tests/test_event_capture_seams.py tests/test_events_service.py -q && venv/bin/ruff check .`
Expected: all passed — `test_inv_05` now finds the six literals in `events_service.py` and `zpd_events.py` and every one is in the taxonomy; `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/services/events_service.py backend/tests/test_event_capture_seams.py backend/learning/zpd_events.py backend/tests/test_learning_zpd_policy.py
git commit -m "feat(learning-loop): PKG-06 — zpd.* events in the taxonomy with typed emit helpers

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 8: Hand-off + ledger

- [ ] **Step 1:** Write `docs/superpowers/plans/learning-loop/HANDOFF-06.md` from `HANDOFF-template.md`. "Verify commands" must be exactly these five lines (they become PKG-07/PKG-10's State-of-the-world rows):

```
cd backend && venv/bin/python -m pytest tests/test_learning_zpd_policy.py -q                    → N passed (N ≥ 25)
grep -cE "^def (ceiling|band_control|evidence_for_rung|wheelspin)\(" backend/learning/policy.py → 4
grep -c '"zpd\.' backend/services/events_service.py                                              → 6
ls backend/db/migrations/*_learning_session_loop_state.sql                                       → 1 file
cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_04 or inv_05" → 2 passed
```

Fill "Constants chosen" with every row of §Named constants, keeping `†` on `GATE_INDEPENDENT_MIN_S`, `GATE_INDEPENDENT_MIN_S_NOVICE`, `GATE_RUNG_DWELL_MIN_S`, and listing each *new name* and each *added by PKG-06* separately. Fill "Open questions for the series owner" with at least: (a) exam mode wins over the shown-work floor (spec lists both without precedence); (b) a non-attempt phrase vetoes an attempt even when work is shown; (c) a same-session re-check still counts toward `streak_unassisted`; (d) `STOP_PRACTICE` needs two *full* windows, so it cannot fire before `BAND_WINDOW × BAND_CONTROL_STOP_WINDOWS` first attempts; (e) `save_loop_state` cannot create the lazy `sessions` row without `session_row` (NOT NULL `user_id`/`mode`/`topic`); (f) `ever_streak3` needs a max-streak the `learner_state` table does not store — PKG-07 derives it from `node_mastery_events` or PKG-14 adds a column; (g) `final_answer` takes the clause after the LAST `=`, so a multi-part reference (`x = 7 and y = 3`) is covered only by the n-gram rule. Record under "Known gaps": no caller yet; the leak detector's eval fixtures (`tests/evals/loop_tutor.py`) are PKG-07's.

- [ ] **Step 2:** Ledger: add row `| 06 | zpd-policy | done | feat/learning-loop-06-zpd-policy | <sha> | N tests (test_learning_zpd_policy.py) + inv_04/05 | — | HANDOFF-06.md |`; add the `03 | … | verified | …` row you earned in State of the world if not already added. Deviations: one line per *new name* constant (`PKG-06: spec states 0.90/2/2/2/6/0.50 unnamed → named BAND_CONTROL_HI/BAND_CONTROL_STOP_WINDOWS/CEILING_PROFIC_ESCALATE_FAILS/CEILING_DEVELOP_H6_FAILS/WHEELSPIN_OPPS_EARLY/WHEELSPIN_UNASSISTED_MAX → no numeral in loop code`) and one per param added on PKG-01's behalf, if any.

- [ ] **Step 3: Commit**

```
git add docs/superpowers/plans/learning-loop/HANDOFF-06.md docs/superpowers/plans/learning-loop/LEDGER.md
git commit -m "docs(learning-loop): PKG-06 — hand-off and ledger

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 9: PR

- [ ] **Step 1:** Run the self-check loop once more (below), then:

```
gh pr create --title "feat(learning): PKG-06 zpd-policy" --body-file - <<'EOF'
Learning loop series, package 6 of 15. Spec: docs/superpowers/specs/2026-09-26-learning-loop-design.md §3.3, §3.4, §4, §6, §8 (4, 5).

- learning/ladder.py: Rung H0..H6 with per-rung tutor intent
- learning/policy.py (pure, typed): StepState / LearnerView / LoopState, ceiling table, evidence-by-rung mapping, band control, wheel-spin
- learning/gates.py: NON_ATTEMPT_PATTERNS, genuine-attempt / rung-dwell / H6 / offer gates
- learning/leak.py: deterministic n-gram + final-answer leak detector and stripper
- sessions.loop_state jsonb migration + learning/loop_state_store.py (lazy-session aware)
- zpd.step / offer / band_adjust / wheelspin / leak / rating in EVENT_TAXONOMY + typed emit helpers
- invariants 4 and 5 asserted

Nothing calls the layer yet (a test proves it); flag-off behaviour is byte-identical. † engineering constants: GATE_INDEPENDENT_MIN_S, GATE_INDEPENDENT_MIN_S_NOVICE, GATE_RUNG_DWELL_MIN_S.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
```

## Self-check loop (run after every task, and once more before the PR)

1. `cd backend && venv/bin/ruff check . && venv/bin/ruff format --check learning tests/test_learning_*.py`
2. `venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q`
3. `venv/bin/python -m pytest tests/ -q` (no `SAPLING_MODEL_MODE` exported)
4. Prompts/tool descriptions touched? **No** in this package → skip evals. (If you find yourself editing anything under `backend/agents/`, stop: scope creep.)
5. Request-path agent or route touched? **No** → skip the E2E cycle. (`services/events_service.py` gained taxonomy strings only; `log_event` behaviour is unchanged.)
6. Scope check: `git diff --stat main...HEAD` — every path must be in this prompt's Files lists. Anything else: `git checkout main -- <path>` or record a Deviation.
7. Sync check: `grep -o "E2E_[A-Z_]*" backend/agents/function_handlers_e2e.py | sort -u` unchanged from `main`.

Green = all seven clean. Max 5 iterations per loop; then write a `BLOCKED` row in `LEDGER.md` with hypothesis, commands, outputs, and stop.

## Regression guard

- Pre-series suite count N₀ (from State of the world) must be unchanged except for the tests this package adds. Zero failures, zero new skips outside `test_learning_loop_invariants.py`.
- Dependency suites unchanged and green: `tests/test_learning_bkt.py`, `tests/test_learning_fsrs.py` (PKG-01/02 — proves no `params.py` value moved), `tests/test_learning_evidence_apply.py`, `tests/test_graph_service.py` (PKG-03), `tests/test_learning_gate.py`, `tests/test_learning_deps.py` (PKG-00).
- Pre-series suites this package touches, unchanged except the six pinned strings: `tests/test_event_capture_seams.py`, `tests/test_events_service.py`; untouched and green: `tests/test_learn_routes.py`, `tests/test_learn_stream_routes.py` (sessions), `tests/test_model_mode_seam.py`.
- With `LEARNING_LOOP_ENABLED` unset or set: no route behaviour changes (nothing imports the new modules — `test_zpd_layer_is_inert_nothing_imports_it`).

## Acceptance criteria (the next session pastes these)

1. `cd backend && venv/bin/python -m pytest tests/test_learning_zpd_policy.py -q` → `N passed (N ≥ 25)`
2. `grep -cE "^def (ceiling|band_control|evidence_for_rung|wheelspin)\(" backend/learning/policy.py` → `4`
3. `grep -c '"zpd\.' backend/services/events_service.py` → `6`
4. `ls backend/db/migrations/*_learning_session_loop_state.sql` → `1 file`
5. `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_04 or inv_05"` → `2 passed`
6. `cd backend && venv/bin/python -m pytest tests/ -q` → zero failures; `venv/bin/ruff check .` → `All checks passed!`
7. `grep -rnE "^\s*(from|import)\s+learning\.(policy|gates|leak|ladder|loop_state_store|zpd_events)\b" backend --include='*.py' | grep -v "^backend/tests/\|^backend/learning/"` → no output
8. `git diff --stat main...HEAD` lists only: `backend/learning/{params,ladder,policy,gates,leak,loop_state_store,zpd_events}.py`, `backend/services/events_service.py`, `backend/db/migrations/*_learning_session_loop_state.sql`, `backend/tests/{test_learning_zpd_policy,test_learning_loop_invariants,test_event_capture_seams}.py`, `docs/superpowers/plans/learning-loop/{HANDOFF-06.md,LEDGER.md}`.
9. `LEDGER.md` has row `06 | zpd-policy | done | …` and a `03 | … | verified` row.

## Hand-off

`docs/superpowers/plans/learning-loop/HANDOFF-06.md` per the template; the Verify commands block is fixed above (Task 8). Symbols to list: every public name in `ladder.py`, `policy.py`, `gates.py`, `leak.py`, `loop_state_store.py`, `zpd_events.py`; the column `sessions.loop_state`; the six event types. Constants: the full §Named constants table with `†` and the new-name rows. Deviations, Known gaps, Open questions: as Task 8 lists them.

## Do not

- Do not call any of this from a route, agent, tool, or `services/chat_stream.py`. Do not mount `routes/learn_loop.py`. Do not touch `agents/`, `routes/`, `services/graph_service.py`, `learning/learner_state.py`, `learning/evidence.py`, `learning/bkt.py`, `learning/fsrs.py`.
- `policy.py`: no `str` parameter on any public function, no `import re`, no import of `gates` (invariant 4). The pure modules (`ladder`, `policy`, `gates`, `leak`) import only stdlib and `learning.*` (invariant 2). Only `loop_state_store.py` touches `db.connection.table` (invariant 7); no `httpx`, no `supabase` import.
- No numeral in loop code other than `0`/`1`/`0.0`/`1.0` and `Rung` member values; every threshold is a `params.NAME`. Never change a PKG-01 value; add names only.
- Migration: UTC-timestamp prefix, `_learning_` infix, spec §4 DDL verbatim, append-only, never edited after creation. `loop_state` is jsonb and unencrypted because it holds ids/numbers/bools only — never put text in it.
- Do not add a seventh event, do not put `"zpd.` in quotes anywhere in `events_service.py` other than the six taxonomy entries, do not make `log_event` enforce membership. No `lru_cache`. No LLM anywhere under `backend/learning/` (spec §12).
- Do not skip, xfail, or delete any pre-existing test. Do not hand-edit eval cassettes or baselines.
- Logscan `ALLOWLIST` in `backend/e2e_oracles/logscan.py` stays `()`.
- End every commit with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`; end the PR body with the Claude Code attribution line.

## If you get stuck

1. Re-read §Spec and the spec file's §3.3 / §6 / §8 before guessing; the ZPD report's policy block is the tie-breaker for wording, the spec for numbers.
2. Three failed iterations on one task → append a `BLOCKED` row to `LEDGER.md` (hypothesis, commands run, outputs), commit what is green, open the PR as draft, stop.
3. Never widen scope to unblock. Never disable a test to unblock. If a leak fixture and the detector disagree, fix the detector's rule and keep the fixture unless the fixture contradicts §Behaviour 8.
4. Ambiguity → choose the option closest to the spec, mark it `†` in the hand-off, continue.
