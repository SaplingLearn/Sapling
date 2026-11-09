# PKG-02 fsrs-core — Learning Loop series (3 of 15)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> You are a fresh session. Nothing outside this file, `docs/superpowers/plans/learning-loop/LEDGER.md`, and the files this prompt lists is known to you. Do not infer intent from chat history you do not have. Do not read the whole research corpus; read the sections named below.

## Package id + goal

**PKG-02 `fsrs-core`.** After this package: `backend/learning/fsrs.py` is a pure FSRS-6 scheduler — forgetting curve, interval, state transition, the spec's check-to-rating map, DASH-threshold due ordering, a daily review budget, the retention-target rules, and the successive-relearning state machine — implementing spec §3.2 verbatim over the pinned `FSRS_W` weights. Nothing imports it yet (PKG-03 wires it into `apply_graph_update`; PKG-11/12 into flashcards and review). `tests/test_learning_fsrs.py` proves the maths against hand-computed reference values, and `test_inv_13` pins the weights.

Branch: `feat/learning-loop-02-fsrs-core`. PR title: `feat(learning): PKG-02 fsrs-core`.

Dependency: PKG-00 (merged). PKG-01 (`bkt-core`, owner of `learning/params.py`) may run in parallel — Task 2 handles both orders.

## Read before you start (in this order)

0. `docs/superpowers/specs/2026-09-26-learning-loop-design.md` **§13 Amendments log** — in force; where this file and §13 disagree, §13 wins. Re-read it before Task 1.
1. `docs/superpowers/plans/learning-loop/LEDGER.md` — refuse to start if any row is `blocked` or `in-progress`. Row `00` must be `done` or `verified`. Row `01` may be `planned`, `done`, or `verified` (parallel); note which, it decides Task 2.
2. `docs/superpowers/plans/learning-loop/HANDOFF-00.md` — what PKG-00 left behind. If `HANDOFF-01.md` exists, read its "Symbols added" and "Constants chosen" too.
3. `CLAUDE.md` §Conventions and §Gotchas — the standing rules the "Do not" list below repeats.
4. `docs/superpowers/specs/2026-09-26-learning-loop-design.md` §3.2 (FSRS-6: equations, weights, constants, rating map) — this is the whole spec of this package; read it twice. Also §2 (module map, `fsrs.py` line), §3.1 "Decay at read" (the one consumer of `retrievability` PKG-01/03 will write), §3.3 "Evidence mapping by rung" (the rung → rating rule the map encodes), §4 `learner_state` columns `fsrs_d`/`fsrs_s`/`fsrs_last_review_at`/`fsrs_due_at` and `flashcards` columns (the row shapes `order_due` sorts), §5 (`Evidence.channel` Literal — the channel names `rating_for` accepts), §8 invariants 2 and 7.
5. `docs/superpowers/plans/learning-loop/README.md` — series conventions.
6. `docs/superpowers/plans/learning-loop/HANDOFF-template.md` — what you write at the end.
7. Research, only these sections: `docs/research/learning-loop/AI tutor learning loop research.md` §"Schedule review with FSRS-6 at 90% retention and successive relearning" (≈ lines 98–121: the equations, the retention rules, the format-aware rating rule, the |R − 0.33| ordering, the 3-then-3 relearning protocol, the daily budget); `docs/research/learning-loop/ZPD lever tradeoffs and upgrades.md` §"Sapling ZPD policy spec" → `EVIDENCE MAPPING (into BKT / FSRS)` block (≈ lines 205–214) and the "Spaced review" row of the phase table (≈ line 59).
8. Code you will modify: `backend/learning/fsrs.py` (4-line stub from PKG-00), `backend/learning/params.py` (stub, or PKG-01's constants file — see Task 2), `backend/tests/test_learning_fsrs.py` (4-line stub), `backend/tests/test_learning_loop_invariants.py` (PKG-00's module; you append one test).
9. Code you will mirror: `backend/tests/conftest.py:63–76` (`_clear_lru_caches` — you add none), `backend/routes/flashcards.py:313` (the flashcards select columns; `last_reviewed_at` is why `order_due` takes a key override), `backend/ruff.toml` (line length 100; `ruff format` is what the self-check runs on `learning/`).

## State of the world

Verify the base is green before Task 1:

| check | command | expected |
|---|---|---|
| hermetic suite green | `cd backend && venv/bin/python -m pytest tests/ -q -x` | `… passed` (note the count N₀; it is this package's regression baseline) |
| lint green | `cd backend && venv/bin/ruff check .` | `All checks passed!` |
| PKG-00 gate | `cd backend && venv/bin/python -m pytest tests/test_learning_gate.py -q` | `11 passed` |
| PKG-00 invariants | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q` | `4 passed, 8 skipped (later packages raise the passed count)` |
| PKG-00 deps/settings/migration | `cd backend && venv/bin/python -m pytest tests/test_learning_deps.py tests/test_learning_settings_flag.py tests/test_learning_loop_beta_migration.py -q` | `all passed` |
| PKG-00 flag | `grep -n "^LEARNING_LOOP_ENABLED" backend/config.py` | `1 hit` |
| PKG-00 migration | `ls backend/db/migrations/*_learning_loop_beta.sql` | `1 file` |
| fsrs stub is inert | `grep -c "^def " backend/learning/fsrs.py; grep -rl "learning.fsrs\|from learning import fsrs" backend --include=*.py` | `0`; no files |
| params state (informational) | `grep -c "^FSRS_W" backend/learning/params.py` | `0` (PKG-01 not merged → Task 2 adds the block) or `1` (PKG-01 merged → Task 2 verifies) |

Rule: any red row → STOP. Diagnose, repair on this branch as commit `fix(learning-loop): repair pre-series base — <what>`, record the deviation in `LEDGER.md`, re-run all rows. Never build on a broken base. The "params state" row is informational and is never red.

## Spec

### Behaviour

All in `backend/learning/fsrs.py`; every formula is spec §3.2 verbatim over `params.FSRS_W` (`W`), with `w20 = W[20]` the decay and `factor = 0.9^(−1/w20) − 1` computed once at import as `FACTOR`.

1. `retrievability(days, stability) -> float` = `(1 + factor·t/S)^(−w20)`. `R(0, S) = 1`; `R(S, S) = 0.9` exactly. `days < 0` or `stability ≤ 0` → `ValueError`.
2. `interval(retention, stability) -> float` = `(S/factor)·(r^(−1/w20) − 1)`; `interval(0.9, S) == S`. `retention ∉ (0, 1]` or `stability ≤ 0` → `ValueError`.
3. `retention_target(n_scheduled, exam_within_days=None) -> float`: `exam_within_days is not None and ≤ FSRS_EXAM_WINDOW_DAYS` → `FSRS_RETENTION_EXAM`; else `n_scheduled > FSRS_LARGE_SET_CONCEPTS` → `FSRS_RETENTION_LARGE_SET`; else `FSRS_RETENTION_DEFAULT`. The exam rule wins over the large-set rule (spec §3.2 lists both without an order; exam week is the stronger, shorter-lived need — record this choice in the hand-off).
4. `Rating` is an `IntEnum` with `AGAIN=1, HARD=2, GOOD=3, EASY=4` (the FSRS grade indices). `initial_stability(G) = W[G−1]`; `initial_difficulty(G) = clamp(w4 − e^(w5·(G−1)) + 1, 1, 10)`.
5. `next_state(d, s, rating, days_since, *, same_day=False, mc_unassisted=False) -> (d', s')`:
   - `d is None or s is None` → first rating → `(initial_difficulty(G), initial_stability(G))`; nothing else runs.
   - otherwise `R = retrievability(days_since, s)`; `D' = D + (−w6·(G−3))·(10−D)/9`; `D'' = clamp(w7·D0(4) + (1−w7)·D', 1, 10)`; the difficulty update runs for every non-first rating, same-day included (spec gives one D rule, no exception).
   - `same_day=True` → `S' = S·e^(w17·(G−3+w18))·S^(−w19)`; else `G == AGAIN` → `S' = w11·D^(−w12)·((S+1)^(w13) − 1)·e^(w14·(1−R))`; else `S' = S·(e^(w8)·(11−D)·S^(−w9)·(e^(w10·(1−R)) − 1)·[w15 if Hard]·[w16 if Easy] + 1)`.
   - `mc_unassisted=True` → `S' = min(S', S·MC_STABILITY_GAIN_CAP)` after the formula (spec §3.2 rating map: "Good with `MC_STABILITY_GAIN_CAP`"). Never applies on a first rating (no prior `S` to cap).
   - No clamp, floor, or rounding beyond the spec's. `rating ∉ {1,2,3,4}`, `s ≤ 0`, `days_since < 0` → `ValueError`.
6. `rating_for(channel, correct, max_rung) -> int` (spec §3.2 rating map): `channel == "idk"` or `not correct` → `AGAIN`; `correct and max_rung == 0` and channel in `free_response`/`teachback_llm`/`mc_reasoned`/`mc` → `GOOD`; `correct and max_rung == 0` and `chat_turn` → `HARD` († the spec map omits `chat_turn`; Hard is the conservative reading of "contributes almost nothing by design" — record as a deviation); `correct and 1 ≤ max_rung ≤ RUNG_ASSISTED_MAX` → `HARD`; `correct and max_rung > RUNG_ASSISTED_MAX` → `AGAIN` (the isomorph re-ask is PKG-06/07's job, not this function's). `EASY` is never returned. Unknown channel or `max_rung < 0` → `ValueError`. Companion `mc_cap_applies(channel, correct, max_rung) -> bool` is `channel == "mc" and correct and max_rung == 0`, so PKG-03 computes the `next_state(..., mc_unassisted=...)` flag from one place.
7. `item_retrievability(item, now, *, stability_key="fsrs_s", last_review_key="fsrs_last_review_at") -> float`: R now for one row (a mapping); `now`/stored timestamps may be tz-aware `datetime` or ISO-8601 strings (PostgREST returns strings, `Z` suffix accepted; naive datetimes are treated as UTC). A row missing either key has `R = 1.0` (never reviewed, nothing to forget). `order_due(items, now, *, same keys) -> list` is a stable sort of the rows by `|R − REVIEW_ORDER_THRESHOLD|` ascending; input list untouched; ties keep input order.
8. `budget_items(budget_min=REVIEW_DAILY_BUDGET_MIN, seconds_per=REVIEW_SECONDS_PER_CHECK) -> int` = `int(budget_min·60 // seconds_per)`, `0` for a non-positive budget, `ValueError` for `seconds_per ≤ 0`. `budget_select(items, budget_min=…, seconds_per=…) -> list` returns the first `budget_items(...)` of an already-ordered list, never more.
9. `SuccessiveRelearning` — frozen dataclass `(phase, correct_in_acquisition, relearn_sessions_done, credited_session)`, `phase ∈ {"acquisition", "relearn", "done"}` (module constants `SR_ACQUISITION`/`SR_RELEARN`/`SR_DONE`). `advance(correct, *, session_id) -> SuccessiveRelearning` (returns a new instance): in `acquisition`, correct recalls count cumulatively (wrong ones neither reset nor count); reaching `SR_INITIAL_CRITERION` moves to `relearn` and records the session as `credited_session`; in `relearn`, the first correct recall of a session whose id differs from `credited_session` increments `relearn_sessions_done` and credits that session — a second correct in the same session, a wrong answer, or the criterion session itself change nothing; reaching `SR_RELEARN_SESSIONS` → `done`; `done` absorbs everything. `complete` property; `as_dict()`/`from_dict()` for JSON persistence (`sessions.loop_state`, PKG-06/12).
10. Flag-off inertness: nothing outside `backend/learning/` and `backend/tests/` imports `learning.fsrs` after this package. `test_routes_import_fsrs_only_behind_the_gate` (Task 5) pins the standing rule: any file under `backend/routes/` that imports `learning.fsrs` must also reference `learning_loop_active`.

### Schema (exact)

None. No migration in this package.

### Named constants

Values live in `backend/learning/params.py` (spec §3.2); tasks cite the NAME. Rows marked "fsrs.py" are structural constants hosted in the module because they are formula/unit facts, not tunables.

| Name | Value | Spec | Notes |
|---|---|---|---|
| `FSRS_W` | `(0.212, 1.2931, 2.3065, 8.2956, 6.4133, 0.8334, 3.0194, 0.001, 1.8722, 0.1666, 0.796, 1.4835, 0.0614, 0.2629, 1.6483, 0.6014, 1.8729, 0.5425, 0.0912, 0.0658, 0.1542)` | §3.2 | 21 weights; a tuple so nothing mutates it |
| `FSRS_RETENTION_DEFAULT` | 0.90 | §3.2 | |
| `FSRS_RETENTION_LARGE_SET` | 0.85 | §3.2 | |
| `FSRS_LARGE_SET_CONCEPTS` | 150 | §3.2 | strictly greater than → large set |
| `FSRS_RETENTION_EXAM` | 0.95 | §3.2 | |
| `FSRS_EXAM_WINDOW_DAYS` | 14 | §3.2 | inclusive |
| `FSRS_S0_GOOD` | `FSRS_W[2]` (= 2.3065 days) | §3.2 | derived, not a literal |
| `REVIEW_ORDER_THRESHOLD` | 0.33 | §3.2 | DASH threshold |
| `REVIEW_DAILY_BUDGET_MIN` | 12 | §3.2 | minutes |
| `REVIEW_SECONDS_PER_CHECK` | 45 | §3.2 | seconds |
| `MC_STABILITY_GAIN_CAP` | 2.0 | §3.2 | `S' ≤ S·cap` |
| `SR_INITIAL_CRITERION` | 3 | §3.2 | |
| `SR_RELEARN_SESSIONS` | 3 | §3.2 | |
| `RUNG_ASSISTED_MAX` | 3 | §3.2 rating map / §3.3 evidence mapping ("H1–H3") | name introduced by this package (value is the spec's); PKG-03 `Evidence.assisted` and PKG-06 `evidence_for_rung` should cite it — say so in the hand-off |
| `Rating.AGAIN/HARD/GOOD/EASY` | 1/2/3/4 | §3.2 (`G ∈ {1,2,3,4}`) | fsrs.py; FSRS grade indices |
| `_STABILITY_R` | 0.9 | §3.2 (`factor = 0.9^(−1/w20) − 1`) | fsrs.py; R at t = S by definition |
| `_D_MIN`, `_D_MAX` | 1, 10 | §3.2 (`clamp(…, 1, 10)`, `(10−D)/9`, `11−D`) | fsrs.py |
| `_SECONDS_PER_DAY`, `_SECONDS_PER_MINUTE` | 86 400, 60 | unit conversions | fsrs.py |

Reference values (derived from the table; the tests state them to 4 decimals, `abs=5e-5`): `FACTOR = 0.9803`; `R(10, 2.3065) = 0.7744`, `R(30, 2.3065) = 0.6675`; `I(0.85, 10) = 19.0643`, `I(0.95, 10) = 4.0256`, `I(0.7, 2.3065) = 21.4226`; `D0(1..4) = 6.4133, 5.1122, 2.1181, 1.0` (raw `D0(4) = −4.7716`, clamped); from a first Good `(2.1181, 2.3065)`: Good after 3 days → `(2.1170, 13.8269)` with `R = 0.8809`; Hard → `(4.7586, 9.2349)`; Again → `(7.4003, 0.6369)`; same-day Good → `(2.1170, 2.2938)`; same-day Again → `(7.4003, 0.7751)`; Good after 30 days → `S' = 37.4206`, capped → `4.6130`; `_next_difficulty(5, Good) = 4.9960`, `(5, Again) = 8.3475`, `(10, Again) = 9.9910`, `(1, Easy) = 1.0`; `budget_items() = 16`.

### Invariants asserted by this package (spec §8 numbering)

This package owns no §8 placeholder. It adds one package-specific invariant as a NEW test (Task 1), never renaming an existing one:

- (13, series-local) `test_inv_13_fsrs_weights_pinned`: `len(learning.params.FSRS_W) == 21`, `FSRS_W[:3] == (0.212, 1.2931, 2.3065)`, `FSRS_S0_GOOD == FSRS_W[2]`, and `learning/fsrs.py` imports only `learning.params` from the `learning` package (so a refit of the weights is a deliberate edit to `params.py`, and inv 02 stays true by construction).

Already-asserted invariants this package must keep green: (2) `fsrs.py` imports nothing from `agents`, `pydantic_ai`, `google`, `db`; (7) `fsrs.py` never calls `table(`/`rpc(`.

### Error semantics

Every public function raises `ValueError` on out-of-domain input (negative days, non-positive stability, retention outside `(0, 1]`, rating outside 1..4, unknown channel, negative rung, non-positive `seconds_per`). Nothing here logs, swallows, or degrades: the callers (PKG-03/11/12) decide what a bad row means. No agent runs in this package, so no ADR 0024 degrade path is touched.

### Events added

None. The taxonomy is untouched (PKG-06 adds `zpd.*`, PKG-12 adds `review.*`).

## Non-goals

- No BKT (PKG-01), no `learner_state` reads/writes or `apply_graph_update` change (PKG-03), no flashcard/quiz route change (PKG-11), no review route (PKG-12), no agent, tool, event, migration, or frontend change.
- No optimizer, no weight refit, no per-user weights: `FSRS_W` is pinned. No "fuzz", no interval rounding to whole days, no "Easy" emission.
- No isomorph re-ask scheduling (the H4–H6 → Again rule only produces the rating; PKG-06/07 schedule the re-ask).
- No `lru_cache` anywhere in this package.

## Tasks

### Task 1: Invariant 13 — weights pinned

**Files:**
- Modify: `backend/tests/test_learning_loop_invariants.py` (append one test; touch nothing above it)

**Interfaces:**
- Consumes: `learning.params.FSRS_W`, `FSRS_S0_GOOD`; source of `learning/fsrs.py`.
- Produces: `test_inv_13_fsrs_weights_pinned`.

- [ ] **Step 1: Append the test** (after `test_inv_12_one_prompt_stack_per_series_agent`; reuse the module's `LEARNING` and `_imports_of` helpers)

```python
def test_inv_13_fsrs_weights_pinned():
    """PKG-02: FSRS_W is the spec §3.2 FSRS-6 default vector, and fsrs.py reads
    it only from learning.params — a refit is a deliberate edit to params.py."""
    from learning.params import FSRS_S0_GOOD, FSRS_W

    assert len(FSRS_W) == 21
    assert tuple(FSRS_W[:3]) == (0.212, 1.2931, 2.3065)
    assert FSRS_S0_GOOD == FSRS_W[2]
    learning_imports = {
        line.split()[1]
        for line in (LEARNING / "fsrs.py").read_text().splitlines()
        if re.match(r"\s*from\s+learning", line)
    }
    assert learning_imports == {"learning.params"}, learning_imports
```

- [ ] **Step 2: Run to see the current state**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -v -k inv_13`
Expected: FAIL. With PKG-01 unmerged: `ImportError: cannot import name 'FSRS_S0_GOOD' from 'learning.params'`. With PKG-01 merged: `AssertionError: set()` (the stub `fsrs.py` imports nothing yet). Either red is correct at this point.

- [ ] **Step 3: Commit**

```
git add backend/tests/test_learning_loop_invariants.py
git commit -m "test(learning-loop): PKG-02 — inv_13 pins the FSRS-6 weights

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 2: FSRS constants in `params.py` (parallel-safe)

**Files:**
- Modify: `backend/learning/params.py` (only if `FSRS_W` is absent)

**Interfaces:**
- Produces: every `params.*` name in the Named-constants table.

- [ ] **Step 1: Decide the branch**

Run: `grep -nE "^(FSRS_W|FSRS_S0_GOOD|REVIEW_ORDER_THRESHOLD|MC_STABILITY_GAIN_CAP|SR_INITIAL_CRITERION|RUNG_ASSISTED_MAX) =" backend/learning/params.py`

- **Zero hits (PKG-01 not merged; `params.py` is the 4-line stub):** keep the stub docstring as-is and append the block in Step 2 below it. Record in the hand-off (Deviations): `spec says PKG-01 owns params.py → PKG-02 added the §3.2 block itself because PKG-01 ran in parallel → PKG-01 merges into it; the later merger keeps ONE definition of each name`.
- **All six hit:** PKG-01 landed first. Verify each value against the table (`venv/bin/python -c "from learning import params as p; print(p.FSRS_W, p.FSRS_RETENTION_DEFAULT, p.RUNG_ASSISTED_MAX)"`). Add only the names that are missing (likely `RUNG_ASSISTED_MAX`); any value that differs from the table is a STOP — do not change PKG-01's value, write a `BLOCKED` note in `LEDGER.md` and stop.
- **Some hit, some not:** add only the missing names, in the same style PKG-01 used; note it in the hand-off.

- [ ] **Step 2: The block** (append verbatim when adding; `FSRS_W` stays a tuple, and the `# fmt: skip` keeps `ruff format` from re-flowing it into 21 lines)

```python
# --- FSRS-6 (spec §3.2) — added by PKG-02; PKG-01 owns the rest of this file. ---
FSRS_W = (
    0.212, 1.2931, 2.3065, 8.2956, 6.4133, 0.8334, 3.0194, 0.001, 1.8722, 0.1666,
    0.796, 1.4835, 0.0614, 0.2629, 1.6483, 0.6014, 1.8729, 0.5425, 0.0912, 0.0658, 0.1542,
)  # fmt: skip
FSRS_RETENTION_DEFAULT = 0.90
FSRS_RETENTION_LARGE_SET = 0.85
FSRS_LARGE_SET_CONCEPTS = 150
FSRS_RETENTION_EXAM = 0.95
FSRS_EXAM_WINDOW_DAYS = 14
FSRS_S0_GOOD = FSRS_W[2]
REVIEW_ORDER_THRESHOLD = 0.33
REVIEW_DAILY_BUDGET_MIN = 12
REVIEW_SECONDS_PER_CHECK = 45
MC_STABILITY_GAIN_CAP = 2.0
SR_INITIAL_CRITERION = 3
SR_RELEARN_SESSIONS = 3
# Spec §3.2 rating map / §3.3 evidence mapping: correct after H1..H3 is "assisted"
# (FSRS Hard, WEIGHT_ASSISTED); correct after H4..H6 is FSRS Again. Name introduced
# by PKG-02; PKG-03 Evidence.assisted and PKG-06 evidence_for_rung cite it.
RUNG_ASSISTED_MAX = 3
```

- [ ] **Step 3: Verify, lint**

Run: `cd backend && venv/bin/python -c "from learning.params import FSRS_W; assert len(FSRS_W)==21; print('ok')" && venv/bin/ruff check . && venv/bin/ruff format --check learning`
Expected: `ok`; `All checks passed!`; `N files already formatted`.

- [ ] **Step 4: Commit** (skip if nothing changed)

```
git add backend/learning/params.py
git commit -m "feat(learning-loop): PKG-02 — FSRS-6 constants in learning.params

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 3: Curves — `retrievability`, `interval`, `retention_target`

**Files:**
- Modify: `backend/learning/fsrs.py` (replace the stub)
- Modify: `backend/tests/test_learning_fsrs.py` (replace the stub)

**Interfaces:**
- Consumes: `params.FSRS_W`, `FSRS_RETENTION_*`, `FSRS_LARGE_SET_CONCEPTS`, `FSRS_EXAM_WINDOW_DAYS`.
- Produces: `fsrs.FACTOR`, `retrievability`, `interval`, `retention_target`.

- [ ] **Step 1: Write the failing tests** — replace `backend/tests/test_learning_fsrs.py` with:

```python
"""learning.fsrs — FSRS-6 scheduler (spec §3.2). Pure maths, no DB, no LLM.

Reference values were computed from the spec §3.2 formulas over FSRS_W and
are stated to four decimals; ``pytest.approx(abs=5e-5)`` throughout.
"""

from __future__ import annotations

import random

import pytest

from learning import fsrs
from learning.fsrs import (
    interval,
    retention_target,
    retrievability,
)
from learning.params import (
    FSRS_EXAM_WINDOW_DAYS,
    FSRS_LARGE_SET_CONCEPTS,
    FSRS_RETENTION_DEFAULT,
    FSRS_RETENTION_EXAM,
    FSRS_RETENTION_LARGE_SET,
    FSRS_S0_GOOD,
    FSRS_W,
)

A = pytest.approx
TOL = 5e-5


def _approx(x):
    return A(x, abs=TOL)


# --- curves -----------------------------------------------------------------


def test_factor_is_derived_from_w20():
    assert fsrs.FACTOR == _approx(0.9803)
    assert fsrs.FACTOR == A(0.9 ** (-1 / FSRS_W[20]) - 1)


def test_retrievability_at_t_equals_s_is_exactly_0_9():
    for s in (0.5, FSRS_S0_GOOD, 10.0, 100.0):
        assert retrievability(s, s) == A(0.9, abs=1e-12)


def test_retrievability_reference_values():
    assert retrievability(0.0, 5.0) == 1.0
    assert retrievability(10.0, FSRS_S0_GOOD) == _approx(0.7744)
    assert retrievability(30.0, FSRS_S0_GOOD) == _approx(0.6675)


def test_retrievability_monotone_decreasing_in_days():
    rng = random.Random(2)
    for _ in range(50):
        s = rng.uniform(0.1, 200.0)
        days = sorted(rng.uniform(0.0, 400.0) for _ in range(6))
        rs = [retrievability(t, s) for t in days]
        assert all(0.0 < r <= 1.0 for r in rs)
        assert rs == sorted(rs, reverse=True)


def test_interval_is_the_inverse_of_retrievability():
    assert interval(0.9, FSRS_S0_GOOD) == A(FSRS_S0_GOOD, abs=1e-9)
    assert interval(0.9, 10.0) == A(10.0, abs=1e-9)
    assert interval(0.85, 10.0) == _approx(19.0643)
    assert interval(0.95, 10.0) == _approx(4.0256)
    assert interval(0.7, FSRS_S0_GOOD) == _approx(21.4226)
    for r in (0.7, 0.85, 0.9, 0.95):
        for s in (0.5, FSRS_S0_GOOD, 10.0, 100.0):
            assert retrievability(interval(r, s), s) == A(r, abs=1e-9)


@pytest.mark.parametrize("bad", [(-1.0, 5.0), (1.0, 0.0), (1.0, -2.0)])
def test_retrievability_rejects_bad_inputs(bad):
    with pytest.raises(ValueError):
        retrievability(*bad)


@pytest.mark.parametrize("bad", [(0.0, 5.0), (1.5, 5.0), (0.9, 0.0)])
def test_interval_rejects_bad_inputs(bad):
    with pytest.raises(ValueError):
        interval(*bad)


# --- retention target -------------------------------------------------------


def test_retention_target_rules():
    assert retention_target(10) == FSRS_RETENTION_DEFAULT
    assert retention_target(FSRS_LARGE_SET_CONCEPTS) == FSRS_RETENTION_DEFAULT
    assert retention_target(FSRS_LARGE_SET_CONCEPTS + 1) == FSRS_RETENTION_LARGE_SET
    assert retention_target(10, exam_within_days=FSRS_EXAM_WINDOW_DAYS) == FSRS_RETENTION_EXAM
    assert retention_target(10, exam_within_days=0) == FSRS_RETENTION_EXAM
    assert (
        retention_target(10, exam_within_days=FSRS_EXAM_WINDOW_DAYS + 1) == FSRS_RETENTION_DEFAULT
    )
    # exam window wins over the large-set rule
    assert retention_target(FSRS_LARGE_SET_CONCEPTS + 1, exam_within_days=1) == FSRS_RETENTION_EXAM
    assert retention_target(10, exam_within_days=None) == FSRS_RETENTION_DEFAULT
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_fsrs.py -v`
Expected: ERROR at collection — `ImportError: cannot import name 'interval' from 'learning.fsrs'`

- [ ] **Step 3: Implement** — replace `backend/learning/fsrs.py` with:

```python
"""FSRS-6 scheduler for the learning loop (spec §3.2). Pure: no I/O, no DB, no LLM.

Stability ``S`` is in days (the time for retrievability to fall to 0.9),
difficulty ``D`` is in [1, 10], retrievability ``R`` is in (0, 1]. Every
formula below is the spec's, verbatim, over the weights ``params.FSRS_W``.
Ratings are the FSRS grades 1 Again / 2 Hard / 3 Good / 4 Easy; v1 never
emits Easy (``rating_for`` returns at most Good).
"""

from __future__ import annotations

from learning.params import (
    FSRS_EXAM_WINDOW_DAYS,
    FSRS_LARGE_SET_CONCEPTS,
    FSRS_RETENTION_DEFAULT,
    FSRS_RETENTION_EXAM,
    FSRS_RETENTION_LARGE_SET,
    FSRS_W,
)

W = FSRS_W
_DECAY = W[20]
_STABILITY_R = 0.9  # R(t = S) by the definition of stability (spec §3.2)
FACTOR = _STABILITY_R ** (-1 / _DECAY) - 1


# --- curves -----------------------------------------------------------------


def retrievability(days: float, stability: float) -> float:
    """R(t, S) = (1 + factor·t/S)^(−w20). R(0, S) = 1; R(S, S) = 0.9."""
    if days < 0:
        raise ValueError(f"days must be >= 0, got {days}")
    if stability <= 0:
        raise ValueError(f"stability must be > 0, got {stability}")
    return (1 + FACTOR * days / stability) ** (-_DECAY)


def interval(retention: float, stability: float) -> float:
    """I(r, S) = (S/factor)·(r^(−1/w20) − 1): days until R falls to ``retention``."""
    if not 0 < retention <= 1:
        raise ValueError(f"retention must be in (0, 1], got {retention}")
    if stability <= 0:
        raise ValueError(f"stability must be > 0, got {stability}")
    return (stability / FACTOR) * (retention ** (-1 / _DECAY) - 1)


def retention_target(n_scheduled: int, exam_within_days: int | None = None) -> float:
    """Desired retention: exam window wins, then large set, else default (spec §3.2)."""
    if exam_within_days is not None and exam_within_days <= FSRS_EXAM_WINDOW_DAYS:
        return FSRS_RETENTION_EXAM
    if n_scheduled > FSRS_LARGE_SET_CONCEPTS:
        return FSRS_RETENTION_LARGE_SET
    return FSRS_RETENTION_DEFAULT
```

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_fsrs.py tests/test_learning_loop_invariants.py -q && venv/bin/ruff check . && venv/bin/ruff format --check learning tests/test_learning_fsrs.py`
Expected: `12 passed` in the fsrs module; invariants `5 passed` (inv_13 now green) with the rest skipped/passed as before; `All checks passed!`; formatted.

- [ ] **Step 5: Commit**

```
git add backend/learning/fsrs.py backend/tests/test_learning_fsrs.py
git commit -m "feat(learning-loop): PKG-02 — FSRS-6 forgetting curve, interval, retention target

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 4: State transition — `next_state`

**Files:**
- Modify: `backend/learning/fsrs.py`, `backend/tests/test_learning_fsrs.py`

**Interfaces:**
- Consumes: `params.MC_STABILITY_GAIN_CAP`.
- Produces: `Rating`, `initial_stability`, `initial_difficulty`, `next_state`; private `_next_difficulty`, `_stability_recall`, `_stability_lapse`, `_stability_same_day`.

- [ ] **Step 1: Write the failing tests** — extend the test module's imports (`from learning.fsrs import (...)` gains `Rating, initial_difficulty, initial_stability, next_state`; `from learning.params import (...)` gains `MC_STABILITY_GAIN_CAP`) and append:

```python
# --- first rating -----------------------------------------------------------


@pytest.mark.parametrize(
    "rating, s0, d0",
    [
        (Rating.AGAIN, 0.212, 6.4133),
        (Rating.HARD, 1.2931, 5.1122),
        (Rating.GOOD, 2.3065, 2.1181),
        (Rating.EASY, 8.2956, 1.0),  # raw D0(4) = −4.7716, clamped to 1
    ],
)
def test_first_rating_uses_s0_and_d0(rating, s0, d0):
    assert initial_stability(rating) == _approx(s0)
    assert initial_difficulty(rating) == _approx(d0)
    assert next_state(None, None, rating, 0.0) == (_approx(d0), _approx(s0))


def test_s0_good_matches_params():
    assert initial_stability(Rating.GOOD) == FSRS_S0_GOOD == FSRS_W[2]


@pytest.mark.parametrize("bad", [0, 5, -1])
def test_bad_rating_rejected(bad):
    with pytest.raises(ValueError):
        next_state(None, None, bad, 0.0)


# --- later ratings: reference trajectory from a first Good ------------------


def _after_first_good():
    return next_state(None, None, Rating.GOOD, 0.0)


def test_good_after_three_days_reference():
    d, s = _after_first_good()
    assert retrievability(3.0, s) == _approx(0.8809)
    nd, ns = next_state(d, s, Rating.GOOD, 3.0)
    assert nd == _approx(2.1170)
    assert ns == _approx(13.8269)


def test_hard_after_three_days_reference():
    d, s = _after_first_good()
    nd, ns = next_state(d, s, Rating.HARD, 3.0)
    assert nd == _approx(4.7586)
    assert ns == _approx(9.2349)


def test_again_after_three_days_reference():
    d, s = _after_first_good()
    nd, ns = next_state(d, s, Rating.AGAIN, 3.0)
    assert nd == _approx(7.4003)
    assert ns == _approx(0.6369)


def test_same_day_reference():
    d, s = _after_first_good()
    nd, ns = next_state(d, s, Rating.GOOD, 0.0, same_day=True)
    assert (nd, ns) == (_approx(2.1170), _approx(2.2938))
    nd, ns = next_state(d, s, Rating.AGAIN, 0.0, same_day=True)
    assert (nd, ns) == (_approx(7.4003), _approx(0.7751))


def test_ratings_order_stability_and_difficulty():
    for s in (0.5, FSRS_S0_GOOD, 10.0, 50.0):
        for d in (1.0, 2.1181, 5.0, 9.0):
            for days in (1.0, 3.0, 10.0, 60.0):
                d_a, s_a = next_state(d, s, Rating.AGAIN, days)
                d_h, s_h = next_state(d, s, Rating.HARD, days)
                d_g, s_g = next_state(d, s, Rating.GOOD, days)
                d_e, s_e = next_state(d, s, Rating.EASY, days)
                assert s_a < s_h < s_g < s_e
                assert d_a >= d_h >= d_g >= d_e


def test_spacing_effect_lower_r_grows_stability_more():
    d, s = _after_first_good()
    _, s_soon = next_state(d, s, Rating.GOOD, 3.0)
    _, s_late = next_state(d, s, Rating.GOOD, 30.0)
    assert s_late == _approx(37.4206)
    assert s_late > s_soon


def test_difficulty_stays_in_bounds_and_stability_positive():
    rng = random.Random(7)
    for _ in range(300):
        d = rng.uniform(1.0, 10.0)
        s = rng.uniform(0.05, 500.0)
        g = rng.choice(list(Rating))
        days = rng.uniform(0.0, 365.0)
        same_day = rng.random() < 0.2
        nd, ns = next_state(d, s, g, 0.0 if same_day else days, same_day=same_day)
        assert 1.0 <= nd <= 10.0
        assert ns > 0.0


def test_difficulty_update_reference_and_clamp():
    assert fsrs._next_difficulty(5.0, Rating.GOOD) == _approx(4.9960)
    assert fsrs._next_difficulty(5.0, Rating.AGAIN) == _approx(8.3475)
    assert fsrs._next_difficulty(10.0, Rating.AGAIN) == _approx(9.9910)
    assert fsrs._next_difficulty(1.0, Rating.EASY) == 1.0


def test_mc_cap_limits_stability_gain():
    d, s = _after_first_good()
    _, uncapped = next_state(d, s, Rating.GOOD, 30.0)
    _, capped = next_state(d, s, Rating.GOOD, 30.0, mc_unassisted=True)
    assert uncapped > s * MC_STABILITY_GAIN_CAP
    assert capped == A(s * MC_STABILITY_GAIN_CAP, abs=1e-9)
    assert capped == _approx(4.6130)
    # the cap never raises a gain that was already under it
    _, small = next_state(d, s, Rating.HARD, 1.0)
    _, small_capped = next_state(d, s, Rating.HARD, 1.0, mc_unassisted=True)
    assert small_capped == A(min(small, s * MC_STABILITY_GAIN_CAP))


def test_next_state_rejects_bad_inputs():
    with pytest.raises(ValueError):
        next_state(2.0, 0.0, Rating.GOOD, 1.0)
    with pytest.raises(ValueError):
        next_state(2.0, 2.0, Rating.GOOD, -1.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_fsrs.py -v`
Expected: ERROR at collection — `ImportError: cannot import name 'Rating' from 'learning.fsrs'`

- [ ] **Step 3: Implement** — in `fsrs.py`: add `import math` and `from enum import IntEnum` to the stdlib imports; add `MC_STABILITY_GAIN_CAP` to the `learning.params` import; add after `FACTOR`:

```python
_D_MIN, _D_MAX = 1.0, 10.0


class Rating(IntEnum):
    AGAIN = 1
    HARD = 2
    GOOD = 3
    EASY = 4
```

and append after `retention_target`:

```python
# --- state transition -------------------------------------------------------


def _clamp_d(d: float) -> float:
    return min(_D_MAX, max(_D_MIN, d))


def _check_rating(rating: int) -> int:
    g = int(rating)
    if g not in (Rating.AGAIN, Rating.HARD, Rating.GOOD, Rating.EASY):
        raise ValueError(f"rating must be 1..4, got {rating}")
    return g


def initial_stability(rating: int) -> float:
    """S0(G) = w[G−1]."""
    return W[_check_rating(rating) - 1]


def initial_difficulty(rating: int) -> float:
    """D0(G) = clamp(w4 − e^(w5·(G−1)) + 1, 1, 10)."""
    g = _check_rating(rating)
    return _clamp_d(W[4] - math.exp(W[5] * (g - 1)) + 1)


def _next_difficulty(d: float, g: int) -> float:
    """ΔD = −w6·(G−3); D' = D + ΔD·(10−D)/9; D'' = w7·D0(4) + (1−w7)·D'."""
    delta = -W[6] * (g - Rating.GOOD)
    d_prime = d + delta * (_D_MAX - d) / (_D_MAX - _D_MIN)
    d_pp = W[7] * initial_difficulty(Rating.EASY) + (1 - W[7]) * d_prime
    return _clamp_d(d_pp)


def _stability_recall(d: float, s: float, r: float, g: int) -> float:
    hard = W[15] if g == Rating.HARD else 1.0
    easy = W[16] if g == Rating.EASY else 1.0
    growth = (
        math.exp(W[8])
        * (_D_MAX + 1 - d)
        * s ** (-W[9])
        * (math.exp(W[10] * (1 - r)) - 1)
        * hard
        * easy
    )
    return s * (growth + 1)


def _stability_lapse(d: float, s: float, r: float) -> float:
    return W[11] * d ** (-W[12]) * ((s + 1) ** W[13] - 1) * math.exp(W[14] * (1 - r))


def _stability_same_day(s: float, g: int) -> float:
    return s * math.exp(W[17] * (g - Rating.GOOD + W[18])) * s ** (-W[19])


def next_state(
    d: float | None,
    s: float | None,
    rating: int,
    days_since: float,
    *,
    same_day: bool = False,
    mc_unassisted: bool = False,
) -> tuple[float, float]:
    """(D', S') after one rating. ``d``/``s`` None → first rating (D0, S0).

    ``same_day`` selects S_same_day; otherwise Again selects S_lapse and
    Hard/Good/Easy select S_recall, all at R = retrievability(days_since, s).
    ``mc_unassisted`` caps S' at S·MC_STABILITY_GAIN_CAP (spec §3.2 rating map).
    The difficulty update runs for every non-first rating.
    """
    g = _check_rating(rating)
    if d is None or s is None:
        return initial_difficulty(g), initial_stability(g)
    if s <= 0:
        raise ValueError(f"stability must be > 0, got {s}")
    r = retrievability(days_since, s)
    new_d = _next_difficulty(d, g)
    if same_day:
        new_s = _stability_same_day(s, g)
    elif g == Rating.AGAIN:
        new_s = _stability_lapse(d, s, r)
    else:
        new_s = _stability_recall(d, s, r, g)
    if mc_unassisted:
        new_s = min(new_s, s * MC_STABILITY_GAIN_CAP)
    return new_d, new_s
```

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_fsrs.py -q && venv/bin/ruff check . && venv/bin/ruff format --check learning tests/test_learning_fsrs.py`
Expected: `30 passed`; `All checks passed!`; formatted. If a reference value is off by more than `5e-5`, the formula is wrong, not the test: re-read spec §3.2 line by line (the usual slips: `11−D` vs `10−D`, `(10−D)/9`, `D0(4)` unclamped in the mean-reversion term, Hard/Easy multipliers applied to the whole S instead of the growth term, `S^(−w19)` missing from same-day).

- [ ] **Step 5: Commit**

```
git add backend/learning/fsrs.py backend/tests/test_learning_fsrs.py
git commit -m "feat(learning-loop): PKG-02 — FSRS-6 next_state (D0/S0, recall, lapse, same-day, MC cap)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 5: Rating map, due ordering, budget

**Files:**
- Modify: `backend/learning/fsrs.py`, `backend/tests/test_learning_fsrs.py`

**Interfaces:**
- Consumes: `params.RUNG_ASSISTED_MAX`, `REVIEW_ORDER_THRESHOLD`, `REVIEW_DAILY_BUDGET_MIN`, `REVIEW_SECONDS_PER_CHECK`.
- Produces: `RATING_CHANNELS`, `STRONG_GOOD_CHANNELS`, `rating_for`, `mc_cap_applies`, `item_retrievability`, `order_due`, `budget_items`, `budget_select`.

- [ ] **Step 1: Write the failing tests** — extend the test module's imports (stdlib gains `from datetime import datetime, timedelta, timezone`; `from learning.fsrs import (...)` gains `budget_items, budget_select, item_retrievability, mc_cap_applies, order_due, rating_for`; `from learning.params import (...)` gains `REVIEW_DAILY_BUDGET_MIN, REVIEW_ORDER_THRESHOLD, REVIEW_SECONDS_PER_CHECK`), add `NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)` under `TOL`, and append:

```python
# --- rating map (spec §3.2) -------------------------------------------------


@pytest.mark.parametrize(
    "channel, correct, max_rung, expected",
    [
        ("free_response", True, 0, Rating.GOOD),
        ("teachback_llm", True, 0, Rating.GOOD),
        ("mc_reasoned", True, 0, Rating.GOOD),
        ("mc", True, 0, Rating.GOOD),
        ("chat_turn", True, 0, Rating.HARD),  # † spec omits chat_turn
        ("free_response", True, 1, Rating.HARD),
        ("free_response", True, 3, Rating.HARD),
        ("mc", True, 2, Rating.HARD),
        ("free_response", True, 4, Rating.AGAIN),
        ("free_response", True, 6, Rating.AGAIN),
        ("free_response", False, 0, Rating.AGAIN),
        ("mc", False, 3, Rating.AGAIN),
        ("chat_turn", False, 0, Rating.AGAIN),
        ("idk", False, 0, Rating.AGAIN),
        ("idk", True, 0, Rating.AGAIN),
    ],
)
def test_rating_map(channel, correct, max_rung, expected):
    assert rating_for(channel, correct, max_rung) == int(expected)


def test_rating_for_never_emits_easy():
    for channel in sorted(fsrs.RATING_CHANNELS):
        for correct in (True, False):
            for max_rung in range(0, 7):
                assert rating_for(channel, correct, max_rung) != int(Rating.EASY)


def test_rating_for_rejects_unknown_channel_and_negative_rung():
    with pytest.raises(ValueError):
        rating_for("quiz", True, 0)
    with pytest.raises(ValueError):
        rating_for("mc", True, -1)


def test_mc_cap_applies_only_to_unassisted_mc_correct():
    assert mc_cap_applies("mc", True, 0) is True
    assert mc_cap_applies("mc", True, 1) is False
    assert mc_cap_applies("mc", False, 0) is False
    assert mc_cap_applies("mc_reasoned", True, 0) is False


# --- due ordering + budget --------------------------------------------------


def _row(node_id, s, days_ago):
    return {
        "node_id": node_id,
        "fsrs_s": s,
        "fsrs_last_review_at": (NOW - timedelta(days=days_ago)).isoformat(),
    }


def test_order_due_sorts_by_distance_from_threshold():
    rng = random.Random(11)
    rows = [_row(f"n{i}", rng.uniform(0.2, 60.0), rng.uniform(0.0, 120.0)) for i in range(40)]
    ordered = order_due(rows, NOW)
    dist = [abs(item_retrievability(r, NOW) - REVIEW_ORDER_THRESHOLD) for r in ordered]
    assert dist == sorted(dist)
    assert sorted(r["node_id"] for r in ordered) == sorted(r["node_id"] for r in rows)
    assert rows == [r for r in rows]  # input untouched


def test_order_due_never_reviewed_rows_sort_last():
    rows = [
        {"node_id": "fresh", "fsrs_s": None, "fsrs_last_review_at": None},
        _row("stale", FSRS_S0_GOOD, 60.0),
    ]
    assert [r["node_id"] for r in order_due(rows, NOW)] == ["stale", "fresh"]
    assert item_retrievability(rows[0], NOW) == 1.0


def test_item_retrievability_accepts_datetime_and_z_suffix():
    dt_row = {"fsrs_s": 10.0, "fsrs_last_review_at": NOW - timedelta(days=10)}
    z_row = {"fsrs_s": 10.0, "fsrs_last_review_at": "2026-09-16T12:00:00Z"}
    assert item_retrievability(dt_row, NOW) == A(0.9, abs=1e-9)
    assert item_retrievability(z_row, NOW) == A(0.9, abs=1e-9)


def test_order_due_custom_keys_for_flashcards():
    rows = [
        {"id": "a", "fsrs_s": 1.0, "last_reviewed_at": (NOW - timedelta(days=30)).isoformat()},
        {"id": "b", "fsrs_s": 1.0, "last_reviewed_at": NOW.isoformat()},
    ]
    ordered = order_due(rows, NOW, last_review_key="last_reviewed_at")
    assert [r["id"] for r in ordered] == ["a", "b"]


def test_budget_items_from_constants():
    assert budget_items() == (REVIEW_DAILY_BUDGET_MIN * 60) // REVIEW_SECONDS_PER_CHECK == 16
    assert budget_items(0) == 0
    assert budget_items(-5) == 0
    with pytest.raises(ValueError):
        budget_items(10, 0)


def test_budget_select_never_exceeds_budget():
    rng = random.Random(3)
    for _ in range(30):
        n = rng.randint(0, 60)
        budget_min = rng.choice([0, 1, 5, REVIEW_DAILY_BUDGET_MIN, 30])
        seconds_per = rng.choice([15, REVIEW_SECONDS_PER_CHECK, 120])
        items = list(range(n))
        chosen = budget_select(items, budget_min, seconds_per)
        assert len(chosen) <= budget_min * 60 // seconds_per
        assert len(chosen) <= n
        assert chosen == items[: len(chosen)]


# --- flag-off inertness -----------------------------------------------------


def test_routes_import_fsrs_only_behind_the_gate():
    """Any route that imports learning.fsrs must also consult the gate; today none does."""
    import pathlib
    import re

    routes = pathlib.Path(__file__).resolve().parents[1] / "routes"
    for path in sorted(routes.glob("*.py")):
        text = path.read_text()
        if re.search(r"^\s*(from|import)\s+learning(\.fsrs|\s+import\s+fsrs)", text, re.M):
            assert "learning_loop_active" in text, f"{path.name} imports fsrs without the gate"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_fsrs.py -v`
Expected: ERROR at collection — `ImportError: cannot import name 'budget_items' from 'learning.fsrs'`

- [ ] **Step 3: Implement** — in `fsrs.py`: stdlib imports gain `from datetime import datetime, timezone` and `from typing import Any, Iterable, Mapping, Sequence`; the `learning.params` import gains `REVIEW_DAILY_BUDGET_MIN, REVIEW_ORDER_THRESHOLD, REVIEW_SECONDS_PER_CHECK, RUNG_ASSISTED_MAX` (keep the block alphabetical — `ruff format` does not sort it, `ruff check` does not care, but the next reader does); add under `_D_MIN, _D_MAX`:

```python
_SECONDS_PER_DAY = 86_400.0
_SECONDS_PER_MINUTE = 60
```

and under the `Rating` enum:

```python
# Channels rating_for accepts (spec §5 Evidence.channel). PKG-03's Evidence
# Literal is the canonical list; tests keep the two in sync.
RATING_CHANNELS = frozenset(
    {"free_response", "mc_reasoned", "mc", "teachback_llm", "chat_turn", "idk"}
)
STRONG_GOOD_CHANNELS = frozenset({"free_response", "teachback_llm", "mc_reasoned"})
```

then append after `next_state`:

```python
# --- rating map -------------------------------------------------------------


def rating_for(channel: str, correct: bool, max_rung: int) -> int:
    """Spec §3.2 rating map. Wrong or ``idk`` → Again; unassisted correct → Good
    (chat_turn → Hard †); correct after H1..H{RUNG_ASSISTED_MAX} → Hard; correct
    after a higher rung → Again. Never Easy."""
    if channel not in RATING_CHANNELS:
        raise ValueError(f"unknown channel {channel!r}")
    if max_rung < 0:
        raise ValueError(f"max_rung must be >= 0, got {max_rung}")
    if channel == "idk" or not correct:
        return int(Rating.AGAIN)
    if max_rung == 0:
        if channel in STRONG_GOOD_CHANNELS or channel == "mc":
            return int(Rating.GOOD)
        return int(Rating.HARD)  # chat_turn †
    if max_rung <= RUNG_ASSISTED_MAX:
        return int(Rating.HARD)
    return int(Rating.AGAIN)


def mc_cap_applies(channel: str, correct: bool, max_rung: int) -> bool:
    """True exactly when the rating came from an unassisted correct ``mc`` check."""
    return channel == "mc" and bool(correct) and max_rung == 0


# --- due ordering + budget --------------------------------------------------


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def item_retrievability(
    item: Mapping[str, Any],
    now: datetime,
    *,
    stability_key: str = "fsrs_s",
    last_review_key: str = "fsrs_last_review_at",
) -> float:
    """R now for one row; a row with no FSRS state has R = 1.0 (never reviewed)."""
    s = item.get(stability_key)
    last = item.get(last_review_key)
    if s is None or last is None:
        return 1.0
    elapsed = (_as_datetime(now) - _as_datetime(last)).total_seconds()
    days = max(0.0, elapsed / _SECONDS_PER_DAY)
    return retrievability(days, float(s))


def order_due(
    items: Iterable[Mapping[str, Any]],
    now: datetime,
    *,
    stability_key: str = "fsrs_s",
    last_review_key: str = "fsrs_last_review_at",
) -> list:
    """Stable sort by |R − REVIEW_ORDER_THRESHOLD| ascending (DASH threshold)."""
    rows = list(items)
    return sorted(
        rows,
        key=lambda it: abs(
            item_retrievability(
                it, now, stability_key=stability_key, last_review_key=last_review_key
            )
            - REVIEW_ORDER_THRESHOLD
        ),
    )


def budget_items(
    budget_min: float = REVIEW_DAILY_BUDGET_MIN,
    seconds_per: float = REVIEW_SECONDS_PER_CHECK,
) -> int:
    """How many checks fit in ``budget_min`` minutes at ``seconds_per`` each."""
    if seconds_per <= 0:
        raise ValueError(f"seconds_per must be > 0, got {seconds_per}")
    if budget_min <= 0:
        return 0
    return int(budget_min * _SECONDS_PER_MINUTE // seconds_per)


def budget_select(
    items: Sequence[Any],
    budget_min: float = REVIEW_DAILY_BUDGET_MIN,
    seconds_per: float = REVIEW_SECONDS_PER_CHECK,
) -> list:
    """First ``budget_items()`` of an already-ordered list; never more."""
    return list(items)[: budget_items(budget_min, seconds_per)]
```

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_fsrs.py -q && venv/bin/ruff check . && venv/bin/ruff format --check learning tests/test_learning_fsrs.py`
Expected: `55 passed`; `All checks passed!`; formatted.

- [ ] **Step 5: Commit**

```
git add backend/learning/fsrs.py backend/tests/test_learning_fsrs.py
git commit -m "feat(learning-loop): PKG-02 — rating map, DASH due ordering, daily review budget

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 6: Successive-relearning state machine

**Files:**
- Modify: `backend/learning/fsrs.py`, `backend/tests/test_learning_fsrs.py`

**Interfaces:**
- Consumes: `params.SR_INITIAL_CRITERION`, `SR_RELEARN_SESSIONS`.
- Produces: `SR_ACQUISITION`, `SR_RELEARN`, `SR_DONE`, `SuccessiveRelearning` (`advance`, `complete`, `as_dict`, `from_dict`).

- [ ] **Step 1: Write the failing tests** — extend the imports (`from learning.fsrs import (...)` gains `SuccessiveRelearning`; `from learning.params import (...)` gains `SR_INITIAL_CRITERION, SR_RELEARN_SESSIONS`) and append:

```python
# --- successive relearning --------------------------------------------------


def test_relearning_initial_criterion_then_three_sessions():
    st = SuccessiveRelearning()
    assert st.phase == fsrs.SR_ACQUISITION and not st.complete
    st = st.advance(False, session_id="s1")
    assert st.correct_in_acquisition == 0
    for i in range(SR_INITIAL_CRITERION - 1):
        st = st.advance(True, session_id="s1")
        assert st.phase == fsrs.SR_ACQUISITION, i
    st = st.advance(True, session_id="s1")
    assert st.phase == fsrs.SR_RELEARN
    assert st.correct_in_acquisition == SR_INITIAL_CRITERION
    # a correct recall in the acquisition session does not count as a relearn session
    assert st.advance(True, session_id="s1") == st
    for k in range(1, SR_RELEARN_SESSIONS + 1):
        st = st.advance(False, session_id=f"r{k}")
        st = st.advance(True, session_id=f"r{k}")
        st = st.advance(True, session_id=f"r{k}")  # second correct in the same session: no-op
        assert st.relearn_sessions_done == k
    assert st.phase == fsrs.SR_DONE and st.complete
    assert st.advance(True, session_id="later") == st


def test_relearning_acquisition_counts_cumulative_not_consecutive():
    st = SuccessiveRelearning()
    for correct in (True, False, True, False, True):
        st = st.advance(correct, session_id="s1")
    assert st.phase == fsrs.SR_RELEARN


def test_relearning_is_immutable_and_round_trips():
    a = SuccessiveRelearning()
    b = a.advance(True, session_id="s1")
    assert a.correct_in_acquisition == 0 and b.correct_in_acquisition == 1
    assert SuccessiveRelearning.from_dict(b.as_dict()) == b
    assert SuccessiveRelearning.from_dict(None) == SuccessiveRelearning()
    assert SuccessiveRelearning.from_dict({}) == SuccessiveRelearning()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_fsrs.py -v`
Expected: ERROR at collection — `ImportError: cannot import name 'SuccessiveRelearning' from 'learning.fsrs'`

- [ ] **Step 3: Implement** — in `fsrs.py`: stdlib imports gain `from dataclasses import dataclass, replace`; the `learning.params` import gains `SR_INITIAL_CRITERION, SR_RELEARN_SESSIONS`; append:

```python
# --- successive relearning --------------------------------------------------

SR_ACQUISITION = "acquisition"
SR_RELEARN = "relearn"
SR_DONE = "done"


@dataclass(frozen=True)
class SuccessiveRelearning:
    """Rawson & Dunlosky protocol: SR_INITIAL_CRITERION correct recalls in the
    acquisition session, then SR_RELEARN_SESSIONS later sessions each to one
    correct recall. Immutable; ``advance`` returns the next state."""

    phase: str = SR_ACQUISITION
    correct_in_acquisition: int = 0
    relearn_sessions_done: int = 0
    credited_session: str | None = None

    def advance(self, correct: bool, *, session_id: str) -> SuccessiveRelearning:
        if self.phase == SR_DONE:
            return self
        if self.phase == SR_ACQUISITION:
            if not correct:
                return self
            n = self.correct_in_acquisition + 1
            if n >= SR_INITIAL_CRITERION:
                return replace(
                    self,
                    phase=SR_RELEARN,
                    correct_in_acquisition=n,
                    credited_session=session_id,
                )
            return replace(self, correct_in_acquisition=n)
        # relearn: one credit per session, never the session that met the criterion
        if not correct or session_id == self.credited_session:
            return self
        done = self.relearn_sessions_done + 1
        return replace(
            self,
            phase=SR_DONE if done >= SR_RELEARN_SESSIONS else SR_RELEARN,
            relearn_sessions_done=done,
            credited_session=session_id,
        )

    @property
    def complete(self) -> bool:
        return self.phase == SR_DONE

    def as_dict(self) -> dict:
        return {
            "phase": self.phase,
            "correct_in_acquisition": self.correct_in_acquisition,
            "relearn_sessions_done": self.relearn_sessions_done,
            "credited_session": self.credited_session,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> SuccessiveRelearning:
        if not data:
            return cls()
        return cls(
            phase=str(data.get("phase", SR_ACQUISITION)),
            correct_in_acquisition=int(data.get("correct_in_acquisition", 0)),
            relearn_sessions_done=int(data.get("relearn_sessions_done", 0)),
            credited_session=data.get("credited_session"),
        )
```

- [ ] **Step 4: Final import blocks** — after the four tasks, the two files' import blocks must read exactly as follows (order matters to a reader, not to ruff):

`backend/learning/fsrs.py`:
```python
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any, Iterable, Mapping, Sequence

from learning.params import (
    FSRS_EXAM_WINDOW_DAYS,
    FSRS_LARGE_SET_CONCEPTS,
    FSRS_RETENTION_DEFAULT,
    FSRS_RETENTION_EXAM,
    FSRS_RETENTION_LARGE_SET,
    FSRS_W,
    MC_STABILITY_GAIN_CAP,
    REVIEW_DAILY_BUDGET_MIN,
    REVIEW_ORDER_THRESHOLD,
    REVIEW_SECONDS_PER_CHECK,
    RUNG_ASSISTED_MAX,
    SR_INITIAL_CRITERION,
    SR_RELEARN_SESSIONS,
)
```

`backend/tests/test_learning_fsrs.py`:
```python
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest

from learning import fsrs
from learning.fsrs import (
    Rating,
    SuccessiveRelearning,
    budget_items,
    budget_select,
    initial_difficulty,
    initial_stability,
    interval,
    item_retrievability,
    mc_cap_applies,
    next_state,
    order_due,
    rating_for,
    retention_target,
    retrievability,
)
from learning.params import (
    FSRS_EXAM_WINDOW_DAYS,
    FSRS_LARGE_SET_CONCEPTS,
    FSRS_RETENTION_DEFAULT,
    FSRS_RETENTION_EXAM,
    FSRS_RETENTION_LARGE_SET,
    FSRS_S0_GOOD,
    FSRS_W,
    MC_STABILITY_GAIN_CAP,
    REVIEW_DAILY_BUDGET_MIN,
    REVIEW_ORDER_THRESHOLD,
    REVIEW_SECONDS_PER_CHECK,
    SR_INITIAL_CRITERION,
    SR_RELEARN_SESSIONS,
)
```

- [ ] **Step 5: Run tests, format, lint, full suite**

Run: `cd backend && venv/bin/ruff format learning/fsrs.py tests/test_learning_fsrs.py && venv/bin/python -m pytest tests/test_learning_fsrs.py -q && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q && venv/bin/python -m pytest tests/ -q && venv/bin/ruff check .`
Expected: `58 passed`; invariants: inv_13 passed, 02/07 still passing; full suite `N₀ + 59 passed` (58 + inv_13), zero failures; `All checks passed!`. If `ruff format` changed a file, look at the diff (it should be whitespace only), then commit it with this task.

- [ ] **Step 6: Commit**

```
git add backend/learning/fsrs.py backend/tests/test_learning_fsrs.py
git commit -m "feat(learning-loop): PKG-02 — successive-relearning state machine

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 7: Hand-off + ledger

- [ ] **Step 1:** Write `docs/superpowers/plans/learning-loop/HANDOFF-02.md` from `HANDOFF-template.md`, every heading present. "Verify commands" must be exactly these three lines (they become PKG-03/PKG-11's State-of-the-world rows):

```
cd backend && venv/bin/python -m pytest tests/test_learning_fsrs.py -q                          → N passed (N ≥ 15)
grep -cE "^def (retrievability|interval|next_state|rating_for|order_due|budget_select)\(" backend/learning/fsrs.py → 6
cd backend && venv/bin/python -c "from learning.params import FSRS_W; assert len(FSRS_W)==21; print('ok')" → ok
```

Fill the headings with these facts (plus anything that actually differed):
- **Symbols added**: every public name in §Spec/Behaviour, one line each with its contract; `params.RUNG_ASSISTED_MAX` (and the whole §3.2 block if Task 2 added it).
- **Constants chosen**: the Named-constants table rows, each with `spec §3.2`. Mark `†` only on `rating_for("chat_turn", True, 0) → HARD`.
- **Deviations from spec**: `spec §3.2 rating map omits chat_turn → unassisted correct chat_turn rates Hard → the channel is the tutor's ungraded judgment (G=S=0.30) and should not grow stability like a graded check †`; `spec §3.2 lists exam and large-set retention rules without precedence → exam window wins → shorter-lived, stronger need`; `spec §3.2 gives one D update rule → applied on same-day reviews too → no exception in the spec`; `rows with no FSRS state → R = 1.0 in order_due (sorted last) → nothing to forget yet; the caller (PKG-12 due_queue) decides whether never-reviewed rows are due at all`; if Task 2 added the params block: `PKG-01 owns params.py → PKG-02 appended the §3.2 block → parallel execution; PKG-01's merger keeps one definition per name`.
- **Known gaps**: the H4–H6 → Again isomorph re-ask is a rating only (PKG-06/07 schedule it); no `fsrs_due_at` writer (PKG-03 computes `due_at = last_review + interval(retention_target(...), S')`); `RATING_CHANNELS` duplicates the future `Evidence.channel` Literal — PKG-03 must add a test asserting the two sets are equal; weights are pinned, no refit path (spec §3.2 stores check type + pre-check R on review rows for a later refit — PKG-03's event columns).
- **Open questions**: whether same-day should skip the difficulty update; whether `chat_turn` should feed FSRS at all; whether `budget_select` should round the item count up when the remainder ≥ half a check.

- [ ] **Step 2:** Append the ledger row: `| 02 | fsrs-core | done | feat/learning-loop-02-fsrs-core | <sha> | 1 module (58) + inv_13 | — | HANDOFF-02.md |`. Add the Deviations lines from Step 1 to `LEDGER.md` §Deviations, prefixed `PKG-02:`. If PKG-00's State-of-the-world rows all passed, also append the verified row for 00: `| 00 | foundation | verified | … | … | … | PKG-02 2026-MM-DD, tests/test_learning_gate.py → 11 passed | HANDOFF-00.md |` (never edit PKG-00's own row).

- [ ] **Step 3: Commit**

```
git add docs/superpowers/plans/learning-loop/HANDOFF-02.md docs/superpowers/plans/learning-loop/LEDGER.md
git commit -m "docs(learning-loop): PKG-02 — hand-off and ledger

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 8: PR

- [ ] **Step 1:** Run the self-check loop once more (all seven steps below). Then:

```
git push -u origin feat/learning-loop-02-fsrs-core
gh pr create --title "feat(learning): PKG-02 fsrs-core" --body-file - <<'EOF'
Learning loop series, package 2 of 15. Spec: docs/superpowers/specs/2026-09-26-learning-loop-design.md §3.2.

- learning/fsrs.py: FSRS-6 retrievability/interval/next_state verbatim over the pinned FSRS_W, retention_target, the check→rating map (+ MC stability cap), |R − 0.33| due ordering, daily review budget, successive-relearning state machine
- learning/params.py: §3.2 constants (added here only if PKG-01 had not merged; see HANDOFF-02 Deviations) + RUNG_ASSISTED_MAX
- tests/test_learning_fsrs.py: 58 tests — reference values to 4 decimals, property checks, rating table, relearning transitions; no DB
- tests/test_learning_loop_invariants.py: test_inv_13_fsrs_weights_pinned

Pure module; nothing imports it yet. Flag-off behaviour is byte-identical.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
```

## Self-check loop (run after every task, and once more before the PR)

1. `cd backend && venv/bin/ruff check . && venv/bin/ruff format --check learning tests/test_learning_*.py`
2. `venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q`
3. `venv/bin/python -m pytest tests/ -q` (no `SAPLING_MODEL_MODE` exported)
4. Prompts/tool descriptions touched? **No** in this package → skip evals. (If you find yourself editing anything under `backend/agents/`, stop: scope creep.)
5. Request-path agent or route touched? **No** → skip the E2E cycle.
6. Scope check: `git diff --stat main...HEAD` — every path must be in this prompt's Files lists. Anything else: `git checkout main -- <path>` or record a Deviation.
7. Sync check: `grep -o "E2E_[A-Z_]*" backend/agents/function_handlers_e2e.py | sort -u` unchanged from `main`.

Green = all seven clean. Max 5 iterations per loop; then write a `BLOCKED` row in `LEDGER.md` with hypothesis, commands, outputs, and stop.

Extra check specific to this package, once before the PR: `grep -nE "[^A-Za-z_\"'][0-9]+\.[0-9]+" backend/learning/fsrs.py` — every hit must be a docstring/comment line, `_STABILITY_R`, `_D_MIN/_D_MAX`, `_SECONDS_PER_DAY`, or a `1.0`/`0.0` neutral value; any other decimal literal belongs in `params.py`.

## Regression guard

- Pre-series suite count N₀ (from State of the world) must be unchanged except for the 59 tests this package adds (58 in `test_learning_fsrs.py` + `test_inv_13`). Zero failures, zero new skips.
- PKG-00's modules stay green and untouched: `tests/test_learning_gate.py` (11), `tests/test_learning_deps.py`, `tests/test_learning_settings_flag.py`, `tests/test_learning_loop_beta_migration.py`. If PKG-01 merged before you: `tests/test_learning_bkt.py` stays green and `bkt.py` is untouched.
- Pre-series suites this package must not disturb (it touches none of their code): `tests/test_model_mode_seam.py`, `tests/test_event_capture_seams.py`, `tests/test_graph_service.py`, `tests/test_quiz_scoring_e.py` — run them explicitly once: `cd backend && venv/bin/python -m pytest tests/test_model_mode_seam.py tests/test_event_capture_seams.py tests/test_graph_service.py tests/test_quiz_scoring_e.py -q`.
- With `LEARNING_LOOP_ENABLED` unset or set: no route behaviour changes (nothing imports `learning.fsrs`; `test_routes_import_fsrs_only_behind_the_gate` proves no route does).

## Acceptance criteria (the next session pastes these)

1. `cd backend && venv/bin/python -m pytest tests/test_learning_fsrs.py -q` → `58 passed`
2. `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k inv_13` → `1 passed`
3. `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q` → `5 passed, 7 skipped` (or `6 passed, 6 skipped` if PKG-01 merged first)
4. `cd backend && venv/bin/python -m pytest tests/ -q` → zero failures
5. `cd backend && venv/bin/ruff check .` → `All checks passed!`; `venv/bin/ruff format --check learning tests/test_learning_fsrs.py` → already formatted
6. `grep -cE "^def (retrievability|interval|next_state|rating_for|order_due|budget_select)\(" backend/learning/fsrs.py` → `6`
7. `cd backend && venv/bin/python -c "from learning.params import FSRS_W; assert len(FSRS_W)==21; print('ok')"` → `ok`
8. `grep -rl "learning.fsrs\|from learning import fsrs" backend --include=*.py | grep -v "^backend/learning/\|^backend/tests/"` → nothing
9. `git diff --stat main...HEAD` lists only: `backend/learning/fsrs.py`, `backend/learning/params.py` (may be absent), `backend/tests/test_learning_fsrs.py`, `backend/tests/test_learning_loop_invariants.py`, `docs/superpowers/plans/learning-loop/{HANDOFF-02.md,LEDGER.md}`.
10. `LEDGER.md` has row `02 | fsrs-core | done | …`.

## Hand-off

`docs/superpowers/plans/learning-loop/HANDOFF-02.md` per the template; the Verify commands block is fixed above (Task 7). Consumers to name explicitly for the next sessions: PKG-03 calls `next_state(row["fsrs_d"], row["fsrs_s"], rating_for(ev.channel, ev.correct, ev.max_rung), days_since, same_day=<same calendar day as fsrs_last_review_at>, mc_unassisted=mc_cap_applies(...))` inside `apply_graph_update` and writes `fsrs_due_at = now + interval(retention_target(...), S')`; §3.1 "Decay at read" uses `retrievability(Δt, S_c)` with `S_c = FSRS_S0_GOOD` when no state exists; PKG-11 uses `order_due(..., last_review_key="last_reviewed_at")` over flashcards rows; PKG-12 composes `order_due` → `budget_select` and persists `SuccessiveRelearning.as_dict()` in `sessions.loop_state`.

## Do not

- Do not import `learning.fsrs` from any route, service, agent, or tool. Do not touch `services/graph_service.py`, `services/chat_stream.py`, `services/events_service.py`, `agents/*`, `routes/*`, `models/*`, `config.py`.
- Do not write a migration. Do not add an event type. Do not register a function-mode handler.
- Do not import `agents`, `pydantic_ai`, `google`, `db`, `httpx`, `supabase`, or anything under `services/` from `learning/fsrs.py` (inv 02/07; `test_inv_13` also pins the `learning.*` import to `learning.params` alone).
- Do not change any value in `FSRS_W` or any §3.2 constant, and do not change a value PKG-01 already wrote in `params.py` — a mismatch is a `BLOCKED` note, not a fix.
- No numeric literals in `fsrs.py` beyond the fsrs.py-hosted rows of the Named-constants table and `1.0`-neutral multipliers; all others come from `params.py`.
- No `lru_cache` in this package. No rounding, clamping, fuzzing, or flooring the spec does not state.
- Do not emit `Rating.EASY` from `rating_for`. Do not let `next_state` schedule anything (it returns `(D', S')` only).
- Do not skip, xfail, rename, or delete any pre-existing test; `test_inv_13` is appended, never substituted for a placeholder. Do not hand-edit eval cassettes or baselines.
- Logscan `ALLOWLIST` in `backend/e2e_oracles/logscan.py` stays `()`.
- End every commit with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`; end the PR body with the Claude Code attribution line.

## If you get stuck

1. Re-read §Spec/Behaviour and the spec file's §3.2 before guessing. A reference value that disagrees by more than `5e-5` means a transcription slip in the formula; recompute by hand from the equation line, do not loosen the tolerance.
2. Three failed iterations on one task → append a `BLOCKED` row to `LEDGER.md` (hypothesis, commands run, outputs), commit what is green, open the PR as draft, stop.
3. Never widen scope to unblock. Never disable a test to unblock.
4. Ambiguity → choose the option closest to the spec, mark it `†` in the hand-off, continue.
5. Merge conflict in `params.py` because PKG-01 landed mid-package → rebase onto `main`, keep exactly one definition per name (PKG-01's value if it exists), re-run Task 2 Step 3 and the full self-check loop, note it under Deviations.
