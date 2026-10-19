# PKG-01 bkt-core — Learning Loop series (2 of 15)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> You are a fresh session. Nothing outside this file, `docs/superpowers/plans/learning-loop/LEDGER.md`, `docs/superpowers/plans/learning-loop/HANDOFF-00.md`, and the files this prompt lists is known to you. Do not infer intent from chat history you do not have. Do not read the whole research corpus; read the sections named below.

## Package id + goal

**PKG-01 `bkt-core`.** After this package: every named constant of spec §3.1–§3.4 lives in `backend/learning/params.py` under the name the spec uses, the channel table is validated at import time (van de Sande validity, spec §3.1), and `backend/learning/bkt.py` is the pure Bayesian Knowledge Tracing core — `update`, `decayed_p`, `propagate_prereq`, `band`, `tier_for`, `is_proficient`, `is_mastered` — with hand-computed posteriors pinned by `tests/test_learning_bkt.py`. No database, no agent, no I/O, no route. Nothing imports either module yet (PKG-03 wires them into `apply_graph_update`). Depends on PKG-00 only; runs in parallel with PKG-02 (`fsrs-core`) and PKG-04 (`check-items`), so it must not import `learning.fsrs`.

Branch: `feat/learning-loop-01-bkt-core`. PR title: `feat(learning): PKG-01 bkt-core`.

## Read before you start (in this order)

0. `docs/superpowers/specs/2026-09-26-learning-loop-design.md` **§13 Amendments log** — in force; where this file and §13 disagree, §13 wins. Re-read it before Task 1.
1. `docs/superpowers/plans/learning-loop/LEDGER.md` — refuse to start if any row is `blocked` or `in-progress`. Row `00 | foundation` must be `done` or `verified`. Rows `02` and `04` may be `in-progress` (parallel branches); that is the one exception to the refuse rule.
2. `docs/superpowers/plans/learning-loop/HANDOFF-00.md` — what PKG-00 left; its "Verify commands" are your State-of-the-world rows.
3. `CLAUDE.md` §Conventions and §Gotchas — the standing rules the "Do not" list below repeats.
4. `docs/superpowers/specs/2026-09-26-learning-loop-design.md` §1 (invariant statement), §2 (module map — `params.py`, `bkt.py` rows), **§3.1–§3.4 in full** (every constant you write), §5 (the `Evidence` model that will call `update` in PKG-03 — read only; do not build it), §8 invariants 2, 3, 10.
5. `docs/superpowers/plans/learning-loop/README.md` — series conventions.
6. `docs/superpowers/plans/learning-loop/HANDOFF-template.md` — what you write at the end.
7. Research, only these sections:
   - `docs/research/learning-loop/AI tutor learning loop research.md` §"Replace the scalar mastery score with per-channel BKT plus decay" (lines ~13–56): the update equations (~28–34), validity bounds (~36), the channel table (~40–48), the worked example whose numbers your tests pin (~50), decay-at-read composition (~52), one-hop asymmetric propagation (~54).
   - `docs/research/learning-loop/ZPD lever tradeoffs and upgrades.md` §"Sapling ZPD policy spec" STATE block (lines ~148–158): the `novice`/`develop`/`profic` band cuts; §"Set the target by phase and format" mastery-gate row (~61): proficient 0.95 / mastered 0.98 with ≥ 3 strong unassisted observations.
8. Code you will modify: `backend/learning/params.py` (docstring-only stub from PKG-00), `backend/learning/bkt.py` (stub), `backend/tests/test_learning_bkt.py` (stub), `backend/tests/test_learning_loop_invariants.py` (the `test_inv_03_channel_guess_slip_bounds` placeholder, `pytest.skip("asserted by PKG-01")`).
9. Code you will mirror but NOT change: `backend/config.py:113–118` (`MASTERY_*_MIN`, `get_mastery_tier` — the legacy flag-off tiers; `tier_for` is the loop-path mirror with different cuts, spec §3.1), `backend/services/quiz_config.py:103–115` (legacy quiz deltas; untouched until PKG-14), `backend/tests/conftest.py:1–30` (sys.path setup — `from learning import bkt` resolves when pytest runs from `backend/`), `backend/tests/test_mastery_tier_unification.py` (pins the legacy tiers; must stay green).

## State of the world

Verify the base before Task 1. Every row must be green.

| check | command | expected |
|---|---|---|
| PKG-00 gate | `cd backend && venv/bin/python -m pytest tests/test_learning_gate.py -q` | `11 passed` |
| PKG-00 invariants | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q` | `4 passed, 8 skipped` (later packages raise the passed count) |
| PKG-00 deps/settings/migration | `cd backend && venv/bin/python -m pytest tests/test_learning_deps.py tests/test_learning_settings_flag.py tests/test_learning_loop_beta_migration.py -q` | all passed |
| PKG-00 flag | `grep -n "^LEARNING_LOOP_ENABLED" backend/config.py` | 1 hit |
| PKG-00 migration | `ls backend/db/migrations/*_learning_loop_beta.sql` | 1 file |
| stubs are inert | `wc -l backend/learning/params.py backend/learning/bkt.py backend/tests/test_learning_bkt.py` | each ≤ 5 lines (docstring only) |
| hermetic suite green | `cd backend && venv/bin/python -m pytest tests/ -q -x` | `… passed` (note the count N₀; regression baseline for this package) |
| lint green | `cd backend && venv/bin/ruff check .` | `All checks passed!` |
| ledger | `grep -E "^\| 00 \| foundation \| (done\|verified)" docs/superpowers/plans/learning-loop/LEDGER.md` | 1 hit |

Rule: any red row → STOP. Diagnose, repair on this branch as commit `fix(learning-loop): repair pre-series base — <what>` (or `fix(learning-loop): PKG-00 — <what>` if the fault is in PKG-00's code, with a `00 | reopened` ledger row and a "Post-hoc changes" line in `HANDOFF-00.md`), record the deviation in `LEDGER.md`, re-run all rows. Never build on a broken base.

## Spec

### Behaviour

1. `learning.params` defines every constant in the Named-constants table below, at module level, under exactly those names, with exactly those values. It imports only the standard library. It defines `validate_channels(channels, t) -> None`, which raises `ValueError` naming the offending channel and inequality when any channel violates spec §3.1 validity: `G + S < 1`, `G ≤ BKT_G_MAX`, `S ≤ BKT_S_MAX`, `0 < t < 1 − S/(1−G)`. The module calls `validate_channels(CHANNELS, BKT_T)` at import, so a bad edit to the table fails the first import, not the first student.
2. `learning.bkt.update(p, channel, correct, *, weight=1.0, idk=False) -> float` is the van de Sande step (spec §3.1): `P_post` from the channel's `G`/`S` and `correct`; `P' = P + weight·(P_post − P)`; then the learn step `P'' = P' + (1 − P')·BKT_T` **only when `weight == 1.0`**. `idk=True` forces an incorrect observation with the channel's `G` and `S_IDK` in place of the channel's `S` (`correct` is ignored). `channel` must be a key of `CHANNELS`; `"idk"` is not a key — it is the flag — and passing it raises `ValueError`. `p` outside `[0, 1]` or `weight` outside `[0, 1]` raises `ValueError`. The result is always inside `[0, 1]`.
3. `learning.bkt.decayed_p(p_stored, days_since, stability) -> float` is decay-at-read (spec §3.1): `BKT_L0 + (p_stored − BKT_L0) · R(days_since, stability)` where `R` is spec §3.2 retrievability computed by a private `_retrievability(t, s)` inside `bkt.py` from `FSRS_W` (PKG-02 writes the public `learning.fsrs.retrievability`; PKG-03 may point `bkt._retrievability` at it once both are merged — record that as a Known gap). `stability is None` → `FSRS_S0_GOOD`. `stability <= 0` → `ValueError`. Negative `days_since` (clock skew) is clamped to `0.0`. At `days_since == 0` the result equals `p_stored` exactly; as `days_since → ∞` it approaches `BKT_L0` from either side.
4. `learning.bkt.propagate_prereq(evidence_correct, parents, children) -> list[tuple[str, str, bool, float]]` is one-hop asymmetric propagation (spec §3.1): correct → one `(parent_id, PROPAGATION_CHANNEL, True, WEIGHT_PROPAGATION)` per prerequisite parent, children untouched; incorrect → one `(child_id, PROPAGATION_CHANNEL, False, WEIGHT_PROPAGATION)` per dependent child, parents untouched. Order preserved, no dedup, empty input → `[]`. The caller (PKG-03) resolves `parents`/`children` from `graph_edges` using `EDGE_PREREQ_SOURCE_IS_PREREQ`; this function never sees an edge.
5. `learning.bkt.band(p) -> Literal["novice", "develop", "profic"]`: `p < BAND_NOVICE_MAX → "novice"`, `p < BAND_DEVELOP_MAX → "develop"`, else `"profic"`.
6. `learning.bkt.tier_for(p) -> str` is the loop-path mirror into `graph_nodes.mastery_tier` (spec §3.1): `p < TIER_UNEXPLORED_MAX → "unexplored"`, `p < BAND_NOVICE_MAX → "struggling"`, `p < BKT_PROFICIENT → "learning"`, else `"mastered"`. It returns only values the `mastery_tier` CHECK accepts. It does NOT replace `config.get_mastery_tier`; the legacy function and its cuts stay until PKG-14.
7. `learning.bkt.is_proficient(p) -> bool` is `p >= BKT_PROFICIENT`. `learning.bkt.is_mastered(p, n_strong_unassisted) -> bool` is `p >= BKT_MASTERED and n_strong_unassisted >= BKT_MASTERED_MIN_STRONG`.
8. `bkt.py` imports only the standard library and `learning.params`. Neither module imports `agents`, `pydantic_ai`, `google`, `db`, `config`, or `learning.fsrs`.
9. Flag: nothing in this package is reachable from a request. `learning_loop_active` is not called; no route, agent, or service imports `learning.bkt` or `learning.params`. The flag-off product is byte-identical. The proof is `grep -rn "learning.bkt\|learning.params\|from learning import" backend --include=*.py | grep -v "backend/learning/\|backend/tests/"` → empty (Acceptance criterion 7).

### Schema (exact)

None. No migration in this package.

### Named constants

Every value below appears in `backend/learning/params.py` under exactly this name. Tasks and code cite the NAME. Legend: `†` = engineering choice with no validated cut-point (spec marks it; first A/B candidates; repeat `†` in the hand-off). `‡` = value is in the spec but the NAME is assigned by this package (spec left it unnamed or gave a shape, not a symbol); list these under "Constants chosen" in the hand-off.

BKT (spec §3.1):

| Name | Value | Note |
|---|---|---|
| `BKT_L0` | `0.35` | prior P(known) for a new concept |
| `BKT_T` | `0.15` | learn-transition per opportunity |
| `BKT_G_MAX` | `0.30` | guess bound (Cognitive Tutor) |
| `BKT_S_MAX` | `0.30` | slip ceiling for the noisiest channel |
| `BKT_PROFICIENT` | `0.95` | proficient threshold |
| `BKT_MASTERED` | `0.98` | mastered threshold |
| `BKT_MASTERED_MIN_STRONG` | `3` | strong-channel unassisted observations for "mastered" |
| `BAND_NOVICE_MAX` | `0.30` | p below → `novice` |
| `BAND_DEVELOP_MAX` | `0.80` | p below → `develop`; else `profic` |
| `TIER_UNEXPLORED_MAX` | `0.10` | loop-path tier mirror: p below → `unexplored` |
| `WEIGHT_ASSISTED` | `0.5` | correct after H1–H3 |
| `WEIGHT_SAME_SESSION_RECHECK` | `0.5` | re-check of the same `question_hash` in one session |
| `WEIGHT_PROPAGATION` | `0.5` | one-hop prerequisite propagation |
| `WEIGHT_LOW_CONFIDENCE` | `0.5` | grader confidence below `GRADER_LOW_CONFIDENCE` |
| `S_IDK` | `0.02` | slip used for an explicit "I don't know" |
| `CHANNELS` | dict, rows below | keyed by channel name; each value `{"G": float, "S": float, "strong": bool}` |
| `STRONG_CHANNELS` ‡ | `frozenset` of the rows with `strong=True` | derived from `CHANNELS` at import: `{"free_response", "mc_reasoned"}` |
| `PROPAGATION_CHANNEL` ‡ | `"chat_turn"` | the "chat_turn-strength observation" of spec §3.1 propagation, named so `bkt.py` carries no string literal |
| `EDGE_PREREQ_SOURCE_IS_PREREQ` | `True` | `graph_edges.source_node_id` = prerequisite, `target_node_id` = dependent; PKG-08 verifies and may flip |

`CHANNELS` rows (spec §3.1 channel table):

| key | `G` | `S` | `strong` |
|---|---|---|---|
| `free_response` | `0.08` | `0.10` | `True` |
| `mc_reasoned` | `0.10` | `0.10` | `True` |
| `mc` | `0.25` | `0.10` | `False` |
| `teachback_llm` | `0.25` | `0.20` | `False` |
| `chat_turn` | `0.30` | `0.30` | `False` |

(`idk` is not a row: it is the `idk=True` flag on `update`, using the item channel's `G` and `S_IDK`.)

FSRS-6 (spec §3.2; PKG-02 consumes these, PKG-01 only defines them):

| Name | Value | Note |
|---|---|---|
| `FSRS_W` | `[0.212, 1.2931, 2.3065, 8.2956, 6.4133, 0.8334, 3.0194, 0.001, 1.8722, 0.1666, 0.796, 1.4835, 0.0614, 0.2629, 1.6483, 0.6014, 1.8729, 0.5425, 0.0912, 0.0658, 0.1542]` | 21 weights, a `tuple` |
| `FSRS_RETENTION_DEFAULT` | `0.90` | |
| `FSRS_RETENTION_LARGE_SET` | `0.85` | |
| `FSRS_LARGE_SET_CONCEPTS` | `150` | |
| `FSRS_RETENTION_EXAM` | `0.95` | |
| `FSRS_EXAM_WINDOW_DAYS` | `14` | |
| `FSRS_S0_GOOD` | `FSRS_W[2]` | written literally as `FSRS_S0_GOOD = FSRS_W[2]` |
| `REVIEW_ORDER_THRESHOLD` | `0.33` | |
| `REVIEW_DAILY_BUDGET_MIN` | `12` | |
| `REVIEW_SECONDS_PER_CHECK` | `45` | |
| `MC_STABILITY_GAIN_CAP` | `2.0` | |
| `SR_INITIAL_CRITERION` | `3` | |
| `SR_RELEARN_SESSIONS` | `3` | |

Ladder, ceiling, gates, bands (spec §3.3; PKG-06 consumes):

| Name | Value | Note |
|---|---|---|
| `GATE_INDEPENDENT_MIN_S` | `45` † | |
| `GATE_INDEPENDENT_MIN_S_NOVICE` | `90` † | |
| `GATE_RUNG_DWELL_MIN_S` | `8` † | |
| `H6_MIN_GENUINE_ATTEMPTS` | `2` | |
| `OFFER_BANDS` | `frozenset({"novice"})` | |
| `BAND_WINDOW` | `8` | rolling first-attempt window |
| `PROBE_TARGET_LO` / `PROBE_TARGET_HI` | `0.50` / `0.62` | two constants |
| `ACQ_TARGET_LO` / `ACQ_TARGET_HI` | `0.75` / `0.90` | |
| `PRACTICE_TARGET_LO` / `PRACTICE_TARGET_HI` | `0.65` / `0.85` | |
| `EXAM_TARGET_LO` / `EXAM_TARGET_HI` | `0.70` / `0.85` | |
| `PI_LO` / `PI_HI` | `0.35` / `0.70` | |
| `PI_MIN_ROOM` | `5` | |
| `WHEELSPIN_OPPS` | `10` | |
| `MISCONCEPTION_CONFIDENCE` | `0.7` | |
| `NOVICE_FLOOR_MISSES` | `3` | |

Probe, plan, step, brief, limits (spec §3.4; PKG-04/05/07/08/09/10 consume):

| Name | Value | Note |
|---|---|---|
| `PROBE_ITEMS_PER_SKILL_MIN` / `PROBE_ITEMS_PER_SKILL_MAX` | `4` / `6` | |
| `PROBE_SESSION_CAP` | `12` | |
| `PROBE_STOP_DELTA` | `0.05` | |
| `PLAN_MAX_CONCEPTS` | `5` | |
| `PLAN_MAX_COUPLED` | `2` | |
| `PLAN_ORDER` | `("due_reviews", "new_material", "interleaved_siblings")` | tuple of phase keys, in spec order |
| `STEP_MAX_SENTENCES` | `5` | |
| `STEP_QUESTIONS_PER_TURN` | `1` | |
| `LOOP_HISTORY_MAX_MESSAGES` | `20` | |
| `LEARNER_BRIEF_MAX_CHARS` | `1800` | |
| `LEARNER_BRIEF_LAST_CLOSES` | `3` | |
| `LEARNER_BRIEF_TOP_STATES` | `5` | |
| `LEARNER_BRIEF_MAX_MISCONCEPTIONS` | `5` | |
| `LOOP_LIMITS` ‡ | `{"request_limit": 14, "tool_calls_limit": 14, "total_tokens_limit": 120_000}` | plain dict; PKG-07 builds `UsageLimits(**LOOP_LIMITS)` in `agents/__init__.py` (params.py must not import pydantic_ai) |
| `GRADER_LIMITS` ‡ | `{"request_limit": 2, "tool_calls_limit": 0, "total_tokens_limit": 20_000}` | same shape; PKG-05 |
| `GRADER_LOW_CONFIDENCE` | `0.6` | below → `WEIGHT_LOW_CONFIDENCE` |
| `GRADER_RETRY_BELOW` ‡ | `0.4` | spec §3.4 "below 0.4 → second grader call"; PKG-05 |
| `LEAK_NGRAM` | `6` | |
| `CHECK_ITEM_FORMATS` | `("free", "teachback", "mc_reason")` | |
| `CHECK_ITEM_DIFFICULTIES` | `(1, 2, 3)` | |
| `CHECK_ITEM_MIN_RUBRIC` | `2` | |
| `CHECK_ITEM_MIN_WRONG` | `1` | |
| `MISCONCEPTION_ROLLUP_MIN_USERS` | `5` | |
| `ZPD_RATING_EVERY_N_CHECKS` | `30` | |

Not named here, on purpose: the band-control cut-points in spec §3.3 (`unassisted_next > 0.90`, `< 0.65`, "2 windows", the wheelspin `opps ≥ 6 AND unassisted_next < 0.50` arm) are unnamed in the spec and belong to `policy.band_control`/`policy.wheelspin`; PKG-06 names them in `params.py`. Record this in the hand-off Known gaps so PKG-06 does not assume they exist.

Hand-computed expectations the tests pin (spec §3.1 equations with the table above; every value is derived, none is a constant — the research report's "0.83/0.85, 0.61/0.67, 0.50, ≈0.50, ≈0.09" are these same numbers rounded):

| case | `P_post` (observation only) | after learn step (`weight == 1.0`) |
|---|---|---|
| p=0.30, `free_response`, correct | 0.828 | 0.854 |
| p=0.30, `mc_reasoned`, correct | 0.794 | 0.825 |
| p=0.30, `mc`, correct | 0.607 | 0.666 |
| p=0.30, `teachback_llm`, correct | 0.578 | 0.642 |
| p=0.30, `chat_turn`, correct | 0.500 | 0.575 |
| p=0.90, `free_response`, wrong | 0.495 | 0.570 |
| p=0.570 (previous row's output), `free_response`, wrong | 0.126 | 0.257 |
| p=0.495 (observation-only chain, no learn step between), `free_response`, wrong | 0.096 | — |
| p=0.90, `free_response`, `idk=True` | 0.164 | 0.289 |
| p=0.30, `free_response`, correct, `weight=0.5` | 0.828 | 0.564 (no learn step: `0.30 + 0.5·(0.828 − 0.30)`) |

Decay expectations (spec §3.2 curve with `FSRS_W`; `factor = 0.9^(−1/w20) − 1 ≈ 0.98035`): `R(S, S) = 0.90` exactly for any `S`, so `decayed_p(0.90, FSRS_S0_GOOD, FSRS_S0_GOOD) = 0.35 + 0.55·0.90 = 0.845`; `R(30, FSRS_S0_GOOD) ≈ 0.6675` so `decayed_p(0.90, 30, None) ≈ 0.717` and `decayed_p(0.10, 30, None) ≈ 0.183` (rises toward the prior).

Note on the research's "second wrong → ≈0.09": that figure chains two observation-only posteriors (0.90 → 0.495 → 0.096). The spec's `update` applies the learn step after every full-weight observation, correct or not, so two consecutive `update` calls give 0.570 then 0.257. Both are pinned; the test names say which is which. Do not "fix" the learn step to reproduce 0.09.

### Invariants asserted by this package (spec §8 numbering)

- (3) every row of `params.CHANNELS` satisfies `G + S < 1`, `G ≤ BKT_G_MAX`, `S ≤ BKT_S_MAX`, `0 < BKT_T < 1 − S/(1−G)` — asserted directly over the dict in `test_inv_03_channel_guess_slip_bounds` (not via `validate_channels`, so the invariant does not trust the validator it is checking). Also asserts `S_IDK + G < 1` for every channel, since `idk` substitutes `S_IDK` for `S`.
- (2) and (7) already pass on the stubs; they must still pass on the filled `bkt.py` and `params.py` (no forbidden imports; no `table(`/`rpc(`).
- (10) `lru_cache` — not triggered; this package adds none.

### Error semantics

Pure functions raise `ValueError` on out-of-range input (`p`, `weight`, unknown `channel`, `stability <= 0`) and never on valid input. `params` raises `ValueError` at import on an invalid channel table. No logging, no events, no fallback values: a bad number is a programming error, not a runtime condition to degrade through.

### Events added

None. The taxonomy is untouched (PKG-06 adds `zpd.*`).

## Non-goals

- No FSRS scheduler (`interval`, `next_state`, `rating_for`, `order_due`, `budget_select`) — PKG-02. Only the retrievability curve is reproduced privately here for decay.
- No `Evidence` model, no `learner_state` table, no `apply_graph_update` change — PKG-03.
- No change to `config.get_mastery_tier` / `MASTERY_*_MIN`, `services/quiz_config.py`, `agents/tools/graph.py` — legacy paths stay until PKG-14.
- No policy, gates, ladder — PKG-06. No naming of the band-control cut-points (see Named constants).
- No migration, no event, no agent, no route, no frontend.
- No nightly pyBKT refit, no per-concept parameter fitting (research §"Replace the scalar" describes it; out of series scope).

## Tasks

### Task 1: Invariant 3 — channel bounds

**Files:**
- Modify: `backend/tests/test_learning_loop_invariants.py` (replace the `test_inv_03_channel_guess_slip_bounds` placeholder only)

**Interfaces:**
- Consumes: `learning.params.CHANNELS`, `BKT_T`, `BKT_G_MAX`, `BKT_S_MAX`, `S_IDK`.
- Produces: a red test that Task 2 turns green.

- [ ] **Step 1: Replace the placeholder**

Find:
```python
def test_inv_03_channel_guess_slip_bounds():
    pytest.skip("asserted by PKG-01")
```
Replace with:
```python
def test_inv_03_channel_guess_slip_bounds():
    """Spec §3.1 validity, asserted over the raw table so this does not depend
    on params.validate_channels being correct."""
    from learning import params

    assert set(params.CHANNELS) == {"free_response", "mc_reasoned", "mc", "teachback_llm", "chat_turn"}
    assert "idk" not in params.CHANNELS, "idk is a flag on update(), not a channel row"
    for name, row in params.CHANNELS.items():
        g, s = row["G"], row["S"]
        assert isinstance(row["strong"], bool), name
        assert 0.0 < g and 0.0 < s, name
        assert g + s < 1.0, f"{name}: G + S = {g + s}"
        assert g <= params.BKT_G_MAX, f"{name}: G {g} > BKT_G_MAX"
        assert s <= params.BKT_S_MAX, f"{name}: S {s} > BKT_S_MAX"
        assert 0.0 < params.BKT_T < 1.0 - s / (1.0 - g), f"{name}: BKT_T outside (0, 1 - S/(1-G))"
        assert g + params.S_IDK < 1.0, f"{name}: idk observation would invert"
```

- [ ] **Step 2: Run to see it fail**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k inv_03`
Expected: FAIL — `AttributeError: module 'learning.params' has no attribute 'CHANNELS'`

- [ ] **Step 3: Commit (red is expected)**

```
git add backend/tests/test_learning_loop_invariants.py
git commit -m "test(learning-loop): PKG-01 — invariant 3 channel guess/slip bounds

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 2: `learning/params.py`

**Files:**
- Modify: `backend/learning/params.py` (replace the stub)
- Modify: `backend/tests/test_learning_bkt.py` (replace the stub; this task writes the params section, later tasks append)

**Interfaces:**
- Consumes: nothing (stdlib only).
- Produces: every name in §Named constants; `validate_channels(channels: Mapping[str, Mapping[str, float | bool]], t: float) -> None`.

- [ ] **Step 1: Write the failing tests** — replace `backend/tests/test_learning_bkt.py` with:

```python
"""PKG-01: learning.params constants + learning.bkt pure BKT (spec §3.1).

Hand-computed expectations are derived from the spec §3.1 equations with the
§3.1 channel table; see PKG-01-bkt-core.md §Spec "Hand-computed expectations".
No DB, no LLM, no fixtures beyond monkeypatch.
"""
from __future__ import annotations

import pytest

from learning import params

# ---------------------------------------------------------------- params


SPEC_31_NAMES = (
    "BKT_L0", "BKT_T", "BKT_G_MAX", "BKT_S_MAX", "BKT_PROFICIENT", "BKT_MASTERED",
    "BKT_MASTERED_MIN_STRONG", "BAND_NOVICE_MAX", "BAND_DEVELOP_MAX", "TIER_UNEXPLORED_MAX",
    "WEIGHT_ASSISTED", "WEIGHT_SAME_SESSION_RECHECK", "WEIGHT_PROPAGATION",
    "WEIGHT_LOW_CONFIDENCE", "S_IDK", "CHANNELS", "STRONG_CHANNELS", "PROPAGATION_CHANNEL",
    "EDGE_PREREQ_SOURCE_IS_PREREQ",
)
SPEC_32_NAMES = (
    "FSRS_W", "FSRS_RETENTION_DEFAULT", "FSRS_RETENTION_LARGE_SET", "FSRS_LARGE_SET_CONCEPTS",
    "FSRS_RETENTION_EXAM", "FSRS_EXAM_WINDOW_DAYS", "FSRS_S0_GOOD", "REVIEW_ORDER_THRESHOLD",
    "REVIEW_DAILY_BUDGET_MIN", "REVIEW_SECONDS_PER_CHECK", "MC_STABILITY_GAIN_CAP",
    "SR_INITIAL_CRITERION", "SR_RELEARN_SESSIONS",
)
SPEC_33_NAMES = (
    "GATE_INDEPENDENT_MIN_S", "GATE_INDEPENDENT_MIN_S_NOVICE", "GATE_RUNG_DWELL_MIN_S",
    "H6_MIN_GENUINE_ATTEMPTS", "OFFER_BANDS", "BAND_WINDOW",
    "PROBE_TARGET_LO", "PROBE_TARGET_HI", "ACQ_TARGET_LO", "ACQ_TARGET_HI",
    "PRACTICE_TARGET_LO", "PRACTICE_TARGET_HI", "EXAM_TARGET_LO", "EXAM_TARGET_HI",
    "PI_LO", "PI_HI", "PI_MIN_ROOM", "WHEELSPIN_OPPS", "MISCONCEPTION_CONFIDENCE",
    "NOVICE_FLOOR_MISSES",
)
SPEC_34_NAMES = (
    "PROBE_ITEMS_PER_SKILL_MIN", "PROBE_ITEMS_PER_SKILL_MAX", "PROBE_SESSION_CAP",
    "PROBE_STOP_DELTA", "PLAN_MAX_CONCEPTS", "PLAN_MAX_COUPLED", "PLAN_ORDER",
    "STEP_MAX_SENTENCES", "STEP_QUESTIONS_PER_TURN", "LOOP_HISTORY_MAX_MESSAGES",
    "LEARNER_BRIEF_MAX_CHARS", "LEARNER_BRIEF_LAST_CLOSES", "LEARNER_BRIEF_TOP_STATES",
    "LEARNER_BRIEF_MAX_MISCONCEPTIONS", "LOOP_LIMITS", "GRADER_LIMITS",
    "GRADER_LOW_CONFIDENCE", "GRADER_RETRY_BELOW", "LEAK_NGRAM", "CHECK_ITEM_FORMATS",
    "CHECK_ITEM_DIFFICULTIES", "CHECK_ITEM_MIN_RUBRIC", "CHECK_ITEM_MIN_WRONG",
    "MISCONCEPTION_ROLLUP_MIN_USERS", "ZPD_RATING_EVERY_N_CHECKS",
)


@pytest.mark.parametrize("name", SPEC_31_NAMES + SPEC_32_NAMES + SPEC_33_NAMES + SPEC_34_NAMES)
def test_every_spec_constant_is_defined(name):
    assert hasattr(params, name), f"spec §3 constant {name} missing from learning.params"


def test_channel_table_shape():
    for name, row in params.CHANNELS.items():
        assert set(row) == {"G", "S", "strong"}, name
    assert params.STRONG_CHANNELS == frozenset({"free_response", "mc_reasoned"})
    assert params.PROPAGATION_CHANNEL in params.CHANNELS
    assert params.PROPAGATION_CHANNEL not in params.STRONG_CHANNELS


def test_fsrs_weights_and_s0():
    assert len(params.FSRS_W) == 21
    assert params.FSRS_S0_GOOD == params.FSRS_W[2]
    assert isinstance(params.FSRS_W, tuple)


def test_ordered_pairs_are_ordered():
    assert params.BKT_PROFICIENT < params.BKT_MASTERED
    assert params.TIER_UNEXPLORED_MAX < params.BAND_NOVICE_MAX < params.BAND_DEVELOP_MAX
    assert params.PROBE_TARGET_LO < params.PROBE_TARGET_HI
    assert params.ACQ_TARGET_LO < params.ACQ_TARGET_HI
    assert params.PRACTICE_TARGET_LO < params.PRACTICE_TARGET_HI
    assert params.EXAM_TARGET_LO < params.EXAM_TARGET_HI
    assert params.PI_LO < params.PI_HI
    assert params.PROBE_ITEMS_PER_SKILL_MIN < params.PROBE_ITEMS_PER_SKILL_MAX
    assert params.GRADER_RETRY_BELOW < params.GRADER_LOW_CONFIDENCE


def test_limits_are_plain_dicts_with_usage_limits_keys():
    for limits in (params.LOOP_LIMITS, params.GRADER_LIMITS):
        assert set(limits) == {"request_limit", "tool_calls_limit", "total_tokens_limit"}


def test_validate_channels_accepts_the_shipped_table():
    params.validate_channels(params.CHANNELS, params.BKT_T)


@pytest.mark.parametrize(
    "row, needle",
    [
        ({"G": 0.5, "S": 0.6, "strong": False}, r"G \+ S"),
        ({"G": 0.31, "S": 0.10, "strong": False}, "BKT_G_MAX"),
        ({"G": 0.10, "S": 0.31, "strong": False}, "BKT_S_MAX"),
    ],
)
def test_validate_channels_rejects_bad_rows(row, needle):
    with pytest.raises(ValueError, match=needle):
        params.validate_channels({"bad": row}, params.BKT_T)


def test_validate_channels_rejects_bad_t():
    with pytest.raises(ValueError, match="BKT_T"):
        params.validate_channels(params.CHANNELS, 0.95)
    with pytest.raises(ValueError, match="BKT_T"):
        params.validate_channels(params.CHANNELS, 0.0)


def test_params_imports_only_stdlib():
    import pathlib

    src = pathlib.Path(params.__file__).read_text()
    for root in ("agents", "pydantic_ai", "google", "db", "config", "learning.fsrs"):
        assert f"import {root}" not in src and f"from {root}" not in src, root
```

- [ ] **Step 2: Run to see it fail**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_bkt.py -q`
Expected: many FAIL — `AssertionError: spec §3 constant BKT_L0 missing from learning.params`, `AttributeError: module 'learning.params' has no attribute 'CHANNELS'`

- [ ] **Step 3: Write `backend/learning/params.py`**

Replace the stub with the module below. Every value is the Named-constants table; do not retype from memory — copy each row.

```python
"""Learning loop named constants — the single source (spec §3).

Every number the loop uses lives here under the spec's name; code cites the
name. A numeric literal in loop code is a review failure (series README).
Stdlib only: the pure modules (bkt, fsrs, policy, gates, ladder, leak) depend
on this one and are forbidden any dependency on agents/, pydantic_ai, google,
db/ (spec §8 invariant 2), so nothing impure may enter here either.

Legend in comments: † = engineering choice without a validated cut-point
(first A/B candidates); ‡ = value from the spec, name assigned by PKG-01.
Spec: docs/superpowers/specs/2026-09-26-learning-loop-design.md §3.1–§3.4.
"""
from __future__ import annotations

from collections.abc import Mapping

# --------------------------------------------------------------- §3.1 BKT
BKT_L0 = 0.35
BKT_T = 0.15
BKT_G_MAX = 0.30
BKT_S_MAX = 0.30
BKT_PROFICIENT = 0.95
BKT_MASTERED = 0.98
BKT_MASTERED_MIN_STRONG = 3
BAND_NOVICE_MAX = 0.30
BAND_DEVELOP_MAX = 0.80
TIER_UNEXPLORED_MAX = 0.10
WEIGHT_ASSISTED = 0.5
WEIGHT_SAME_SESSION_RECHECK = 0.5
WEIGHT_PROPAGATION = 0.5
WEIGHT_LOW_CONFIDENCE = 0.5
S_IDK = 0.02

# Per-channel guess/slip (KT-IDEM). `idk` is NOT a row: it is the idk=True
# flag on bkt.update, which uses the item channel's G with S_IDK.
CHANNELS: dict[str, dict[str, float | bool]] = {
    "free_response": {"G": 0.08, "S": 0.10, "strong": True},
    "mc_reasoned": {"G": 0.10, "S": 0.10, "strong": True},
    "mc": {"G": 0.25, "S": 0.10, "strong": False},
    "teachback_llm": {"G": 0.25, "S": 0.20, "strong": False},
    "chat_turn": {"G": 0.30, "S": 0.30, "strong": False},
}
STRONG_CHANNELS = frozenset(k for k, v in CHANNELS.items() if v["strong"])  # ‡
PROPAGATION_CHANNEL = "chat_turn"  # ‡ spec §3.1: "chat_turn-strength observation"
EDGE_PREREQ_SOURCE_IS_PREREQ = True  # PKG-08 verifies against live data

# ------------------------------------------------------------ §3.2 FSRS-6
FSRS_W = (
    0.212, 1.2931, 2.3065, 8.2956, 6.4133, 0.8334, 3.0194, 0.001, 1.8722, 0.1666,
    0.796, 1.4835, 0.0614, 0.2629, 1.6483, 0.6014, 1.8729, 0.5425, 0.0912, 0.0658, 0.1542,
)
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

# ------------------------------------- §3.3 ladder, ceiling, gates, bands
GATE_INDEPENDENT_MIN_S = 45  # †
GATE_INDEPENDENT_MIN_S_NOVICE = 90  # †
GATE_RUNG_DWELL_MIN_S = 8  # †
H6_MIN_GENUINE_ATTEMPTS = 2
OFFER_BANDS = frozenset({"novice"})
BAND_WINDOW = 8
PROBE_TARGET_LO = 0.50
PROBE_TARGET_HI = 0.62
ACQ_TARGET_LO = 0.75
ACQ_TARGET_HI = 0.90
PRACTICE_TARGET_LO = 0.65
PRACTICE_TARGET_HI = 0.85
EXAM_TARGET_LO = 0.70
EXAM_TARGET_HI = 0.85
PI_LO = 0.35
PI_HI = 0.70
PI_MIN_ROOM = 5
WHEELSPIN_OPPS = 10
MISCONCEPTION_CONFIDENCE = 0.7
NOVICE_FLOOR_MISSES = 3
# Band-control cut-points (unassisted_next 0.90 / 0.65, "2 windows", the
# wheelspin opps>=6 arm) are unnamed in spec §3.3; PKG-06 names them here.

# ------------------------------------- §3.4 probe, plan, step, brief, limits
PROBE_ITEMS_PER_SKILL_MIN = 4
PROBE_ITEMS_PER_SKILL_MAX = 6
PROBE_SESSION_CAP = 12
PROBE_STOP_DELTA = 0.05
PLAN_MAX_CONCEPTS = 5
PLAN_MAX_COUPLED = 2
PLAN_ORDER = ("due_reviews", "new_material", "interleaved_siblings")
STEP_MAX_SENTENCES = 5
STEP_QUESTIONS_PER_TURN = 1
LOOP_HISTORY_MAX_MESSAGES = 20
LEARNER_BRIEF_MAX_CHARS = 1800
LEARNER_BRIEF_LAST_CLOSES = 3
LEARNER_BRIEF_TOP_STATES = 5
LEARNER_BRIEF_MAX_MISCONCEPTIONS = 5
# ‡ plain dicts: PKG-07/05 build pydantic_ai UsageLimits(**X) in agents/__init__.py
LOOP_LIMITS = {"request_limit": 14, "tool_calls_limit": 14, "total_tokens_limit": 120_000}
GRADER_LIMITS = {"request_limit": 2, "tool_calls_limit": 0, "total_tokens_limit": 20_000}
GRADER_LOW_CONFIDENCE = 0.6
GRADER_RETRY_BELOW = 0.4  # ‡ spec §3.4 "below 0.4 → second grader call"
LEAK_NGRAM = 6
CHECK_ITEM_FORMATS = ("free", "teachback", "mc_reason")
CHECK_ITEM_DIFFICULTIES = (1, 2, 3)
CHECK_ITEM_MIN_RUBRIC = 2
CHECK_ITEM_MIN_WRONG = 1
MISCONCEPTION_ROLLUP_MIN_USERS = 5
ZPD_RATING_EVERY_N_CHECKS = 30


# ------------------------------------------------------ §3.1 validity check
def validate_channels(channels: Mapping[str, Mapping[str, float | bool]], t: float) -> None:
    """Raise ValueError unless every channel satisfies spec §3.1 validity.

    G + S < 1 (else the update inverts and correct answers lower belief),
    G <= BKT_G_MAX, S <= BKT_S_MAX, and 0 < t < 1 - S/(1-G) (van de Sande 2013).
    """
    if not 0.0 < t:
        raise ValueError(f"BKT_T must be > 0, got {t}")
    for name, row in channels.items():
        g = float(row["G"])
        s = float(row["S"])
        if not (0.0 < g and 0.0 < s):
            raise ValueError(f"channel {name}: G and S must be > 0, got G={g} S={s}")
        if g + s >= 1.0:
            raise ValueError(f"channel {name}: G + S = {g + s} must be < 1")
        if g > BKT_G_MAX:
            raise ValueError(f"channel {name}: G {g} exceeds BKT_G_MAX {BKT_G_MAX}")
        if s > BKT_S_MAX:
            raise ValueError(f"channel {name}: S {s} exceeds BKT_S_MAX {BKT_S_MAX}")
        t_max = 1.0 - s / (1.0 - g)
        if not t < t_max:
            raise ValueError(f"channel {name}: BKT_T {t} must be < 1 - S/(1-G) = {t_max:.4f}")


validate_channels(CHANNELS, BKT_T)
```

- [ ] **Step 4: Run tests, format, lint**

Run: `cd backend && venv/bin/ruff format learning/params.py tests/test_learning_bkt.py && venv/bin/python -m pytest tests/test_learning_bkt.py tests/test_learning_loop_invariants.py -q && venv/bin/ruff check .`
Expected: all `test_learning_bkt.py` tests pass; invariants `5 passed, 7 skipped` (inv_03 now green); `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/learning/params.py backend/tests/test_learning_bkt.py
git commit -m "feat(learning-loop): PKG-01 — learning/params.py, every spec §3 constant + channel validity

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 3: `bkt.update`

**Files:**
- Modify: `backend/learning/bkt.py` (replace the stub)
- Modify: `backend/tests/test_learning_bkt.py` (append)

**Interfaces:**
- Consumes: `params.CHANNELS`, `params.BKT_T`, `params.S_IDK`.
- Produces: `bkt.update(p, channel, correct, *, weight=1.0, idk=False) -> float`; private `bkt._posterior(p, g, s, correct) -> float`.

- [ ] **Step 1: Append the failing tests** — add `from learning import bkt` beside `from learning import params` in the top import block, then append:

```python
# ------------------------------------------------------------------ update


P_LOW = 0.30
P_HIGH = 0.90
TOL = 1e-3


@pytest.mark.parametrize(
    "channel, post, final",
    [
        ("free_response", 0.8282, 0.8540),
        ("mc_reasoned", 0.7941, 0.8250),
        ("mc", 0.6067, 0.6657),
        ("teachback_llm", 0.5783, 0.6416),
        ("chat_turn", 0.5000, 0.5750),
    ],
)
def test_correct_from_p_low_matches_hand_computation(channel, post, final):
    g, s = params.CHANNELS[channel]["G"], params.CHANNELS[channel]["S"]
    assert bkt._posterior(P_LOW, g, s, True) == pytest.approx(post, abs=TOL)
    assert bkt.update(P_LOW, channel, True) == pytest.approx(final, abs=TOL)


def test_wrong_free_response_from_p_high_twice():
    """0.90 → 0.570 → 0.257 through update (learn step after each full-weight
    observation). The research report's ≈0.50 / ≈0.09 are the observation-only
    posteriors, pinned in the next test."""
    once = bkt.update(P_HIGH, "free_response", False)
    assert once == pytest.approx(0.5703, abs=TOL)
    twice = bkt.update(once, "free_response", False)
    assert twice == pytest.approx(0.2572, abs=TOL)


def test_wrong_free_response_observation_only_chain():
    g, s = params.CHANNELS["free_response"]["G"], params.CHANNELS["free_response"]["S"]
    once = bkt._posterior(P_HIGH, g, s, False)
    assert once == pytest.approx(0.4945, abs=TOL)
    assert bkt._posterior(once, g, s, False) == pytest.approx(0.0961, abs=TOL)


def test_idk_uses_channel_g_with_s_idk_and_ignores_correct():
    g = params.CHANNELS["free_response"]["G"]
    assert bkt._posterior(P_HIGH, g, params.S_IDK, False) == pytest.approx(0.1636, abs=TOL)
    got = bkt.update(P_HIGH, "free_response", False, idk=True)
    assert got == pytest.approx(0.2891, abs=TOL)
    assert bkt.update(P_HIGH, "free_response", True, idk=True) == got
    # idk drops belief harder than an ordinary wrong answer on the same channel
    assert got < bkt.update(P_HIGH, "free_response", False)


def test_weight_interpolates_and_skips_learn_step():
    half = bkt.update(P_LOW, "free_response", True, weight=0.5)
    assert half == pytest.approx(0.5641, abs=TOL)
    assert bkt.update(P_LOW, "free_response", True, weight=0.0) == pytest.approx(P_LOW)
    full = bkt.update(P_LOW, "free_response", True, weight=1.0)
    assert half < full


def test_learn_step_applies_only_at_full_weight():
    # weight=1.0 wrong from a low p can still RISE (learn step); weight<1 cannot
    assert bkt.update(0.0, "chat_turn", False) == pytest.approx(params.BKT_T)
    assert bkt.update(0.0, "chat_turn", False, weight=0.999) == pytest.approx(0.0)


@pytest.mark.parametrize("channel", sorted(params.CHANNELS))
@pytest.mark.parametrize("p", [0.0, 0.05, 0.35, 0.5, 0.8, 0.95, 1.0])
def test_monotone_and_bounded(channel, p):
    up = bkt.update(p, channel, True)
    down = bkt.update(p, channel, False, weight=0.5)
    assert 0.0 <= up <= 1.0 and 0.0 <= down <= 1.0
    assert up >= p
    assert down <= p


def test_stronger_channel_moves_more():
    fr = bkt.update(P_LOW, "free_response", True)
    mcr = bkt.update(P_LOW, "mc_reasoned", True)
    mc = bkt.update(P_LOW, "mc", True)
    chat = bkt.update(P_LOW, "chat_turn", True)
    assert fr > mcr > mc > chat > P_LOW


def test_one_graded_check_outweighs_a_chat_turn():
    """Spec §1: a chat-turn "correct" is undone, and more, by one graded wrong."""
    chat = bkt.update(P_LOW, "chat_turn", True)
    assert chat > P_LOW
    assert bkt.update(chat, "free_response", False) < P_LOW


def test_update_rejects_bad_inputs():
    with pytest.raises(ValueError, match="channel"):
        bkt.update(P_LOW, "idk", True)
    with pytest.raises(ValueError, match="channel"):
        bkt.update(P_LOW, "essay", True)
    with pytest.raises(ValueError, match="p"):
        bkt.update(1.5, "mc", True)
    with pytest.raises(ValueError, match="p"):
        bkt.update(-0.1, "mc", True)
    with pytest.raises(ValueError, match="weight"):
        bkt.update(P_LOW, "mc", True, weight=1.5)
    with pytest.raises(ValueError, match="weight"):
        bkt.update(P_LOW, "mc", True, weight=-0.5)
```

- [ ] **Step 2: Run to see it fail**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_bkt.py -q -k "update or posterior or idk or weight or monotone or stronger or graded_check or learn_step"`
Expected: FAIL — `AttributeError: module 'learning.bkt' has no attribute '_posterior'` / `'update'`

- [ ] **Step 3: Write `backend/learning/bkt.py`** (this task fills `update`; Tasks 4–5 append the rest)

```python
"""Bayesian Knowledge Tracing core (spec §3.1). Pure: stdlib + learning.params.

Only graded checks change what Sapling believes a student knows (spec §1).
This module is the arithmetic of that belief: van de Sande's closed-form
update with a separate guess/slip pair per evidence channel, decay toward the
prior along the FSRS-6 forgetting curve at read time, one-hop asymmetric
prerequisite propagation, and the band/tier cuts. It never touches the
database, the graph, or an agent; PKG-03's apply_graph_update calls it.
"""
from __future__ import annotations

from learning.params import BKT_T, CHANNELS, S_IDK

_FULL_WEIGHT = 1.0
_P_MIN = 0.0
_P_MAX = 1.0


def _posterior(p: float, g: float, s: float, correct: bool) -> float:
    """Observation-only Bayes step (spec §3.1 `correct:` / `incorrect:` lines)."""
    if correct:
        num = p * (1.0 - s)
        den = num + (1.0 - p) * g
    else:
        num = p * s
        den = num + (1.0 - p) * (1.0 - g)
    if den == 0.0:  # only reachable at p in {0, 1} with a degenerate g/s; keep p
        return p
    return num / den


def _clamp01(x: float) -> float:
    return min(_P_MAX, max(_P_MIN, x))


def update(
    p: float,
    channel: str,
    correct: bool,
    *,
    weight: float = _FULL_WEIGHT,
    idk: bool = False,
) -> float:
    """One BKT opportunity (spec §3.1).

    P' = P + weight·(P_post − P); learn step P'' = P' + (1 − P')·BKT_T only
    when weight == 1.0. idk=True is an incorrect observation with the item
    channel's G and S_IDK (`correct` is ignored). `channel` must be a key of
    CHANNELS; "idk" is the flag, not a channel.
    """
    if channel not in CHANNELS:
        raise ValueError(f"unknown channel {channel!r}; idk is the idk=True flag, not a channel")
    if not _P_MIN <= p <= _P_MAX:
        raise ValueError(f"p must be in [0, 1], got {p}")
    if not _P_MIN <= weight <= _FULL_WEIGHT:
        raise ValueError(f"weight must be in [0, 1], got {weight}")
    row = CHANNELS[channel]
    g = float(row["G"])
    s = S_IDK if idk else float(row["S"])
    observed = False if idk else bool(correct)
    p_post = _posterior(p, g, s, observed)
    p_new = p + weight * (p_post - p)
    if weight == _FULL_WEIGHT:
        p_new = p_new + (1.0 - p_new) * BKT_T
    return _clamp01(p_new)
```

- [ ] **Step 4: Run tests, format, lint**

Run: `cd backend && venv/bin/ruff format learning/bkt.py tests/test_learning_bkt.py && venv/bin/python -m pytest tests/test_learning_bkt.py tests/test_learning_loop_invariants.py -q && venv/bin/ruff check .`
Expected: all passed; invariants `5 passed, 7 skipped`; `All checks passed!` (the import block grows in Tasks 4–5; import only what each task uses so F401 never fires — never add a `# noqa`).

- [ ] **Step 5: Commit**

```
git add backend/learning/bkt.py backend/tests/test_learning_bkt.py
git commit -m "feat(learning-loop): PKG-01 — bkt.update, van de Sande step with per-channel guess/slip

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 4: `bkt.decayed_p`

**Files:**
- Modify: `backend/learning/bkt.py` (append)
- Modify: `backend/tests/test_learning_bkt.py` (append)

**Interfaces:**
- Consumes: `params.BKT_L0`, `params.FSRS_W`, `params.FSRS_S0_GOOD`.
- Produces: `bkt.decayed_p(p_stored, days_since, stability) -> float`; private `bkt._retrievability(t, s) -> float`.

- [ ] **Step 1: Append the failing tests**

```python
# --------------------------------------------------------------- decayed_p


def test_retrievability_is_point_nine_at_t_equals_s():
    for s in (0.5, params.FSRS_S0_GOOD, 10.0, 100.0):
        assert bkt._retrievability(s, s) == pytest.approx(0.9, abs=1e-9)
    assert bkt._retrievability(0.0, params.FSRS_S0_GOOD) == pytest.approx(1.0)


def test_decay_hand_computed():
    s0 = params.FSRS_S0_GOOD
    assert bkt.decayed_p(P_HIGH, s0, s0) == pytest.approx(0.845, abs=TOL)
    assert bkt.decayed_p(P_HIGH, 30.0, None) == pytest.approx(0.7171, abs=TOL)
    assert bkt.decayed_p(0.10, 30.0, None) == pytest.approx(0.1831, abs=TOL)


def test_no_time_no_decay():
    for p in (0.0, 0.10, params.BKT_L0, 0.7, 1.0):
        assert bkt.decayed_p(p, 0.0, None) == p
        assert bkt.decayed_p(p, -3.0, None) == p  # clock skew clamps to 0


def test_decay_moves_toward_prior_from_both_sides_and_is_monotone():
    above = [bkt.decayed_p(P_HIGH, d, None) for d in (0, 1, 7, 30, 365, 3650)]
    below = [bkt.decayed_p(0.05, d, None) for d in (0, 1, 7, 30, 365, 3650)]
    assert above == sorted(above, reverse=True)
    assert below == sorted(below)
    assert all(params.BKT_L0 <= x <= P_HIGH for x in above)
    assert all(0.05 <= x <= params.BKT_L0 for x in below)
    # power-law tail: ten years still leaves belief well above the prior
    assert above[-1] < above[0] and above[-1] > params.BKT_L0


def test_prior_is_a_fixed_point_of_decay():
    for d in (0.0, 1.0, 30.0, 1000.0):
        assert bkt.decayed_p(params.BKT_L0, d, None) == pytest.approx(params.BKT_L0)


def test_higher_stability_decays_slower():
    slow = bkt.decayed_p(P_HIGH, 30.0, 60.0)
    fast = bkt.decayed_p(P_HIGH, 30.0, params.FSRS_S0_GOOD)
    assert slow > fast


def test_missing_stability_uses_s0_good():
    assert bkt.decayed_p(P_HIGH, 9.0, None) == bkt.decayed_p(P_HIGH, 9.0, params.FSRS_S0_GOOD)


def test_decayed_p_rejects_nonpositive_stability():
    with pytest.raises(ValueError, match="stability"):
        bkt.decayed_p(P_HIGH, 1.0, 0.0)
    with pytest.raises(ValueError, match="stability"):
        bkt.decayed_p(P_HIGH, 1.0, -2.0)
```

- [ ] **Step 2: Run to see it fail**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_bkt.py -q -k "decay or retrievability or stability or prior"`
Expected: FAIL — `AttributeError: module 'learning.bkt' has no attribute '_retrievability'`

- [ ] **Step 3: Append to `backend/learning/bkt.py`** — extend the import to `from learning.params import BKT_L0, BKT_T, CHANNELS, FSRS_S0_GOOD, FSRS_W, S_IDK`, then append:

```python
# Spec §3.2 retrievability, reproduced privately so PKG-01 and PKG-02 can merge
# in either order. PKG-03 may replace the body with `learning.fsrs.retrievability`
# once both are on main; keep the name so decayed_p does not change.
_W20 = FSRS_W[20]
_FSRS_FACTOR = 0.9 ** (-1.0 / _W20) - 1.0


def _retrievability(t: float, s: float) -> float:
    """R(t, S) = (1 + factor·t/S)^(−w20); R(S, S) = 0.9 by construction."""
    return (1.0 + _FSRS_FACTOR * t / s) ** (-_W20)


def decayed_p(p_stored: float, days_since: float, stability: float | None) -> float:
    """Decay-at-read (spec §3.1): P_now = L0 + (P_stored − L0)·R(Δt, S_c).

    stability None → FSRS_S0_GOOD (no FSRS state yet). Negative days_since
    (clock skew) reads as 0. The prior is a fixed point; every other p moves
    toward it from its own side and never crosses.
    """
    s_c = FSRS_S0_GOOD if stability is None else stability
    if s_c <= 0.0:
        raise ValueError(f"stability must be > 0, got {stability}")
    t = max(0.0, days_since)
    if t == 0.0:
        return p_stored
    return _clamp01(BKT_L0 + (p_stored - BKT_L0) * _retrievability(t, s_c))
```

- [ ] **Step 4: Run tests, format, lint**

Run: `cd backend && venv/bin/ruff format learning/bkt.py tests/test_learning_bkt.py && venv/bin/python -m pytest tests/test_learning_bkt.py tests/test_learning_loop_invariants.py -q && venv/bin/ruff check .`
Expected: all passed; `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/learning/bkt.py backend/tests/test_learning_bkt.py
git commit -m "feat(learning-loop): PKG-01 — bkt.decayed_p, decay toward the prior on the FSRS-6 curve

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 5: Propagation, bands, tiers, mastery predicates

**Files:**
- Modify: `backend/learning/bkt.py` (append)
- Modify: `backend/tests/test_learning_bkt.py` (append)

**Interfaces:**
- Consumes: `params.WEIGHT_PROPAGATION`, `PROPAGATION_CHANNEL`, `BAND_*`, `TIER_UNEXPLORED_MAX`, `BKT_PROFICIENT`, `BKT_MASTERED`, `BKT_MASTERED_MIN_STRONG`.
- Produces: `bkt.propagate_prereq(evidence_correct, parents, children) -> list[Propagation]`, `bkt.band(p) -> Band`, `bkt.tier_for(p) -> Tier`, `bkt.is_proficient(p) -> bool`, `bkt.is_mastered(p, n_strong_unassisted) -> bool`.

- [ ] **Step 1: Append the failing tests** — add `import math` to the top import block (stdlib group), then append:

```python
# ------------------------------------------- propagate / band / tier / mastery


def test_propagation_correct_goes_to_parents_only():
    out = bkt.propagate_prereq(True, ["pre_a", "pre_b"], ["dep_c"])
    assert out == [
        ("pre_a", params.PROPAGATION_CHANNEL, True, params.WEIGHT_PROPAGATION),
        ("pre_b", params.PROPAGATION_CHANNEL, True, params.WEIGHT_PROPAGATION),
    ]


def test_propagation_incorrect_goes_to_children_only():
    out = bkt.propagate_prereq(False, ["pre_a", "pre_b"], ["dep_c", "dep_d"])
    assert out == [
        ("dep_c", params.PROPAGATION_CHANNEL, False, params.WEIGHT_PROPAGATION),
        ("dep_d", params.PROPAGATION_CHANNEL, False, params.WEIGHT_PROPAGATION),
    ]


def test_propagation_empty_and_shape():
    assert bkt.propagate_prereq(True, [], ["dep_c"]) == []
    assert bkt.propagate_prereq(False, ["pre_a"], []) == []
    for node_id, channel, correct, weight in bkt.propagate_prereq(True, ["x"], []):
        assert isinstance(node_id, str) and channel in params.CHANNELS
        assert isinstance(correct, bool) and 0.0 < weight < 1.0


def test_propagated_observation_is_weak():
    """A propagated hop is a half-weight chat-strength observation: it never
    triggers the learn step and moves belief less than the direct check."""
    (node_id, channel, correct, weight), = bkt.propagate_prereq(True, ["pre_a"], [])
    hop = bkt.update(P_LOW, channel, correct, weight=weight)
    direct = bkt.update(P_LOW, "free_response", True)
    assert P_LOW < hop < direct
    assert hop - P_LOW < 0.15


def _just_below(x: float) -> float:
    return math.nextafter(x, 0.0)


def test_band_boundaries():
    assert bkt.band(0.0) == "novice"
    assert bkt.band(_just_below(params.BAND_NOVICE_MAX)) == "novice"
    assert bkt.band(params.BAND_NOVICE_MAX) == "develop"
    assert bkt.band(_just_below(params.BAND_DEVELOP_MAX)) == "develop"
    assert bkt.band(params.BAND_DEVELOP_MAX) == "profic"
    assert bkt.band(1.0) == "profic"


def test_tier_boundaries_and_check_values():
    assert bkt.tier_for(0.0) == "unexplored"
    assert bkt.tier_for(_just_below(params.TIER_UNEXPLORED_MAX)) == "unexplored"
    assert bkt.tier_for(params.TIER_UNEXPLORED_MAX) == "struggling"
    assert bkt.tier_for(_just_below(params.BAND_NOVICE_MAX)) == "struggling"
    assert bkt.tier_for(params.BAND_NOVICE_MAX) == "learning"
    assert bkt.tier_for(_just_below(params.BKT_PROFICIENT)) == "learning"
    assert bkt.tier_for(params.BKT_PROFICIENT) == "mastered"
    assert bkt.tier_for(1.0) == "mastered"
    allowed = {"unexplored", "struggling", "learning", "mastered"}  # graph_nodes.mastery_tier CHECK
    assert {bkt.tier_for(p / 100) for p in range(0, 101)} <= allowed


def test_tier_for_is_not_the_legacy_tier():
    """Loop-path cuts differ from config.get_mastery_tier (legacy stays until PKG-14)."""
    import config

    assert bkt.tier_for(0.80) == "learning"
    assert config.get_mastery_tier(0.80) == "mastered"
    assert config.MASTERY_MASTERED_MIN == 0.75  # pinned by test_mastery_tier_unification; untouched


def test_proficient_and_mastered():
    assert bkt.is_proficient(params.BKT_PROFICIENT) is True
    assert bkt.is_proficient(_just_below(params.BKT_PROFICIENT)) is False
    assert bkt.is_mastered(params.BKT_MASTERED, params.BKT_MASTERED_MIN_STRONG) is True
    assert bkt.is_mastered(params.BKT_MASTERED, params.BKT_MASTERED_MIN_STRONG - 1) is False
    assert bkt.is_mastered(_just_below(params.BKT_MASTERED), 10) is False
    assert bkt.is_mastered(1.0, 0) is False


def test_mastered_implies_proficient():
    for p in (0.98, 0.99, 1.0):
        if bkt.is_mastered(p, params.BKT_MASTERED_MIN_STRONG):
            assert bkt.is_proficient(p)


def test_bkt_imports_only_stdlib_and_params():
    import pathlib

    src = pathlib.Path(bkt.__file__).read_text()
    for root in ("agents", "pydantic_ai", "google", "db", "config", "learning.fsrs", "services"):
        assert f"import {root}" not in src and f"from {root}" not in src, root
```

- [ ] **Step 2: Run to see it fail**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_bkt.py -q -k "propagat or band or tier or proficient or mastered or imports_only"`
Expected: FAIL — `AttributeError: module 'learning.bkt' has no attribute 'propagate_prereq'`

- [ ] **Step 3: Append to `backend/learning/bkt.py`** — add `from typing import Literal` to the stdlib imports; extend the params import to the full list `BAND_DEVELOP_MAX, BAND_NOVICE_MAX, BKT_L0, BKT_MASTERED, BKT_MASTERED_MIN_STRONG, BKT_PROFICIENT, BKT_T, CHANNELS, FSRS_S0_GOOD, FSRS_W, PROPAGATION_CHANNEL, S_IDK, TIER_UNEXPLORED_MAX, WEIGHT_PROPAGATION`; add the three aliases below the imports; then append the functions.

```python
Band = Literal["novice", "develop", "profic"]
Tier = Literal["unexplored", "struggling", "learning", "mastered"]
Propagation = tuple[str, str, bool, float]  # (node_id, channel, correct, weight)
```

```python
def propagate_prereq(
    evidence_correct: bool, parents: list[str], children: list[str]
) -> list[Propagation]:
    """One-hop asymmetric propagation (spec §3.1).

    correct at c   → each prerequisite parent gets a PROPAGATION_CHANNEL-strength
                     correct observation at WEIGHT_PROPAGATION; children untouched.
    incorrect at c → each dependent child gets the incorrect observation; parents
                     untouched (an error can be local).
    The caller resolves parents/children from graph_edges using
    EDGE_PREREQ_SOURCE_IS_PREREQ; this function never sees an edge.
    """
    targets = parents if evidence_correct else children
    return [(node_id, PROPAGATION_CHANNEL, bool(evidence_correct), WEIGHT_PROPAGATION) for node_id in targets]


def band(p: float) -> Band:
    """Spec §3.1 / ZPD STATE block: novice < BAND_NOVICE_MAX ≤ develop < BAND_DEVELOP_MAX ≤ profic."""
    if p < BAND_NOVICE_MAX:
        return "novice"
    if p < BAND_DEVELOP_MAX:
        return "develop"
    return "profic"


def tier_for(p: float) -> Tier:
    """Loop-path mirror into graph_nodes.mastery_tier (spec §3.1). Not the legacy
    config.get_mastery_tier, which keeps its own cuts until PKG-14."""
    if p < TIER_UNEXPLORED_MAX:
        return "unexplored"
    if p < BAND_NOVICE_MAX:
        return "struggling"
    if p < BKT_PROFICIENT:
        return "learning"
    return "mastered"


def is_proficient(p: float) -> bool:
    return p >= BKT_PROFICIENT


def is_mastered(p: float, n_strong_unassisted: int) -> bool:
    """Mastered needs the belief AND BKT_MASTERED_MIN_STRONG strong-channel
    unassisted observations (spec §3.1); belief alone is never enough."""
    return p >= BKT_MASTERED and n_strong_unassisted >= BKT_MASTERED_MIN_STRONG
```

- [ ] **Step 4: Run tests, format, lint, count**

Run: `cd backend && venv/bin/ruff format learning/bkt.py tests/test_learning_bkt.py && venv/bin/python -m pytest tests/test_learning_bkt.py tests/test_learning_loop_invariants.py -q && venv/bin/ruff check . && grep -cE "^def (update|decayed_p|propagate_prereq|band|tier_for)\(" learning/bkt.py && grep -cE "^[A-Z0-9_]+ = " learning/params.py`
Expected: all passed (≥ 20 in `test_learning_bkt.py`; invariants `5 passed, 7 skipped`); `All checks passed!`; `5`; `≥ 40` (the table above yields 76 — `CHANNELS` carries a type annotation, so the grep skips it).

If `ruff format` wrapped the `def propagate_prereq(` signature onto one line or split `def band(p: float) -> Band:`, that is fine — the grep counts `^def name(` and a multi-line signature still starts with it.

- [ ] **Step 5: Commit**

```
git add backend/learning/bkt.py backend/tests/test_learning_bkt.py
git commit -m "feat(learning-loop): PKG-01 — propagate_prereq, band, tier_for, mastery predicates

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 6: Hand-off + ledger

**Files:**
- Create: `docs/superpowers/plans/learning-loop/HANDOFF-01.md`
- Modify: `docs/superpowers/plans/learning-loop/LEDGER.md` (append rows only)

- [ ] **Step 1:** Write `HANDOFF-01.md` from `HANDOFF-template.md`, every heading present. Content to include:
  - **Symbols added**: `learning/params.py::validate_channels`, `learning/params.py::CHANNELS` (+ every constant name, grouped by spec section — a name list, not values), `learning/bkt.py::update`, `::decayed_p`, `::propagate_prereq`, `::band`, `::tier_for`, `::is_proficient`, `::is_mastered`, private `::_posterior`, `::_retrievability`, type aliases `Band`, `Tier`, `Propagation`.
  - **Constants chosen**: every `†` (the three `GATE_*` seconds) and every `‡` (`STRONG_CHANNELS`, `PROPAGATION_CHANNEL`, `LOOP_LIMITS`/`GRADER_LIMITS` dict shape, `GRADER_RETRY_BELOW`) with the spec §ref.
  - **Deviations from spec**: none expected. If any value differs from §Named constants, that is a deviation line here AND in `LEDGER.md`.
  - **Known gaps**: (a) `bkt._retrievability` duplicates spec §3.2 `R` that PKG-02 also implements as `learning.fsrs.retrievability`; PKG-03 may dedupe by importing from `fsrs` once both are on main — the private name stays. (b) Band-control cut-points (spec §3.3 `0.90`/`0.65`/"2 windows"/wheelspin `≥ 6`/`< 0.50`) are unnamed in the spec and not in `params.py`; PKG-06 names them. (c) The `Evidence.channel` Literal (spec §5) includes `"idk"` but `bkt.update` takes `idk=True` on the item's channel; PKG-03 must map `channel == "idk"` to the check item's format channel + `idk=True` (open question below). (d) `tier_for` exists but nothing writes it to `graph_nodes` until PKG-03. (e) `LOOP_LIMITS`/`GRADER_LIMITS` are dicts; PKG-05/07 build `UsageLimits(**…)`.
  - **Verify commands** — exactly these four lines:

```
cd backend && venv/bin/python -m pytest tests/test_learning_bkt.py -q                           → N passed (N ≥ 20)
grep -cE "^def (update|decayed_p|propagate_prereq|band|tier_for)\(" backend/learning/bkt.py    → 5
grep -cE "^[A-Z0-9_]+ = " backend/learning/params.py                                            → ≥ 40
cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k inv_03    → 1 passed
```

  - **Open questions for the series owner**: (1) which channel's `G` an `Evidence(channel="idk")` should use when the check item's format is unknown — option taken: none; `update` refuses `"idk"` as a channel so PKG-03 has to decide explicitly. (2) Whether `EDGE_PREREQ_SOURCE_IS_PREREQ` matches live `graph_edges` data — PKG-08 verifies; `propagate_prereq` is direction-agnostic by design.

- [ ] **Step 2:** Append the ledger row: `| 01 | bkt-core | done | feat/learning-loop-01-bkt-core | <sha> | tests/test_learning_bkt.py (N) + inv_03 | — | HANDOFF-01.md |`. Then, because you ran PKG-00's verify rows in State of the world, append a `verified` row for 00: `| 00 | foundation | verified | … | … | … | PKG-01 <date>: tests/test_learning_gate.py → 11 passed; invariants → 4 passed, 8 skipped | HANDOFF-00.md |` (copy branch/sha/tests from the `done` row; never rewrite it). Add to Deviations only what differed from this prompt.

- [ ] **Step 3: Commit**

```
git add docs/superpowers/plans/learning-loop/HANDOFF-01.md docs/superpowers/plans/learning-loop/LEDGER.md
git commit -m "docs(learning-loop): PKG-01 — hand-off and ledger

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 7: PR

- [ ] **Step 1:** Run the full self-check loop once more (below). All seven clean.

- [ ] **Step 2:** Open the PR.

```
git push -u origin feat/learning-loop-01-bkt-core
gh pr create --title "feat(learning): PKG-01 bkt-core" --body-file - <<'EOF'
Learning loop series, package 1 of 15. Spec: docs/superpowers/specs/2026-09-26-learning-loop-design.md §3.

- learning/params.py: every named constant of spec §3.1–§3.4 (76 module-level names); channel table validated at import (G+S<1, G≤BKT_G_MAX, S≤BKT_S_MAX, 0<T<1−S/(1−G))
- learning/bkt.py: update (van de Sande, per-channel guess/slip, weighted interpolation, learn step at full weight only, idk), decayed_p (decay toward the prior on the FSRS-6 curve), propagate_prereq (one hop, asymmetric), band, tier_for, is_proficient, is_mastered
- tests/test_learning_bkt.py pins the hand-computed posteriors (0.30 → 0.854 / 0.666 / 0.575; 0.90 → 0.570 → 0.257) and decay; invariant 3 asserted
- Pure: stdlib + params only. No DB, no agent, no route, no migration, no event. Nothing imports these modules yet (PKG-03 wires them), so flag-off behaviour is byte-identical.

Hand-off: docs/superpowers/plans/learning-loop/HANDOFF-01.md

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

Package-specific step 1 note: `ruff format --check` now covers two real modules and one real test file. Run `venv/bin/ruff format learning/params.py learning/bkt.py tests/test_learning_bkt.py` before each commit rather than hand-aligning; the code blocks above are written to survive it but the formatter is the authority.

## Regression guard

- Pre-series suite count N₀ (from State of the world) must be unchanged except for the tests this package adds (`tests/test_learning_bkt.py` and the one un-skipped invariant). Zero failures, zero new skips.
- PKG-00 modules unchanged and green: `tests/test_learning_gate.py` (11), `tests/test_learning_deps.py`, `tests/test_learning_settings_flag.py`, `tests/test_learning_loop_beta_migration.py`; `tests/test_learning_loop_invariants.py` goes from `4 passed, 8 skipped` to `5 passed, 7 skipped` and nothing else.
- Pre-series suites this package's territory borders, unchanged and green: `tests/test_mastery_tier_unification.py` (legacy tier cuts — `tier_for` is a second function, not a change to `config.get_mastery_tier`), `tests/test_quiz_scoring_e.py` (legacy quiz deltas untouched), `tests/test_graph_service.py` (no `apply_graph_update` change), `tests/test_model_mode_seam.py`, `tests/test_event_capture_seams.py`.
- With `LEARNING_LOOP_ENABLED` unset or `true`: no route behaviour changes (nothing imports `learning.bkt`/`learning.params` outside `backend/learning/` and `backend/tests/`).

## Acceptance criteria (the next session pastes these)

1. `cd backend && venv/bin/python -m pytest tests/test_learning_bkt.py -q` → `N passed` with N ≥ 20, zero failures, zero skips
2. `grep -cE "^def (update|decayed_p|propagate_prereq|band|tier_for)\(" backend/learning/bkt.py` → `5`
3. `grep -cE "^[A-Z0-9_]+ = " backend/learning/params.py` → ≥ 40
4. `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q` → `5 passed, 7 skipped` (and `-k inv_03` → `1 passed`)
5. `cd backend && venv/bin/python -m pytest tests/ -q` → zero failures; `venv/bin/ruff check .` → `All checks passed!`; `venv/bin/ruff format --check learning tests/test_learning_*.py` → clean
6. `cd backend && venv/bin/python -c "from learning import params, bkt; print(len(params.FSRS_W), bkt.update(0.30, 'free_response', True))"` → `21 0.8539…`
7. `grep -rln "learning.bkt\|learning.params\|from learning import" backend --include=*.py | grep -v "^backend/learning/\|^backend/tests/"` → empty (nothing outside the package and its tests imports the new modules)
8. `git diff --stat main...HEAD` lists only: `backend/learning/params.py`, `backend/learning/bkt.py`, `backend/tests/test_learning_bkt.py`, `backend/tests/test_learning_loop_invariants.py`, `docs/superpowers/plans/learning-loop/{HANDOFF-01.md,LEDGER.md}`.
9. `LEDGER.md` has row `01 | bkt-core | done | …` and a `00 | foundation | verified | …` row.

## Hand-off

`docs/superpowers/plans/learning-loop/HANDOFF-01.md` per the template, content per Task 6. The "Verify commands" block is fixed (Task 6, Step 1) — PKG-03's State of the world pastes it verbatim. Open questions to record: the `Evidence(channel="idk")` mapping (PKG-03) and the prerequisite edge direction (PKG-08).

## Do not

- Do not import `learning.fsrs` from `bkt.py` (PKG-02 may not be merged); keep `_retrievability` private in `bkt.py`.
- Do not import `agents`, `pydantic_ai`, `google`, `db`, `config`, or `services` from `learning/params.py` or `learning/bkt.py` (spec §8 invariant 2 — and `config` would drag env parsing into a pure module).
- Do not change `config.MASTERY_*_MIN` / `get_mastery_tier`, `services/quiz_config.py`, `agents/tools/graph.py`, `services/graph_service.py`, `frontend/src/components/screens/Learn.tsx::tierForScore` — legacy tiers and deltas live until PKG-14.
- Do not call the gate, mount `routes/learn_loop.py`, or make any route/service/agent import the new modules.
- No numeric literal in `bkt.py` other than the arithmetic identities `0.0`, `1.0`, `0.9` (the FSRS curve's defining retention, spec §3.2 `R(S,S)=0.9`) and the `FSRS_W[20]` index; every threshold, weight, bound and prior comes from `params`. No numeric constant in any other loop code; add to `params.py` under a spec name.
- Do not name the band-control cut-points (spec §3.3 `0.90`/`0.65`/wheelspin `6`/`0.50`) — PKG-06 owns them.
- No `lru_cache` in this package. No migration. No event. No `# noqa`.
- Do not "correct" the learn step to reproduce the research's ≈0.09 second-wrong figure; the spec applies the learn step after every full-weight observation (see §Spec note).
- All Supabase access through `db/connection.py::table()` — moot here: this package touches no table.
- Do not skip, xfail, or delete any pre-existing test. Do not hand-edit eval cassettes or baselines.
- Logscan `ALLOWLIST` in `backend/e2e_oracles/logscan.py` stays `()`.
- End every commit with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`; end the PR body with the Claude Code attribution line.

## If you get stuck

1. Re-read §Spec and the spec file's §3.1–§3.2 before guessing. If a hand-computed expectation in the tests disagrees with your implementation by more than `TOL`, recompute it by hand from the §3.1 equations with the channel table before touching either — the table in §Spec shows the intermediate `P_post` for exactly this purpose.
2. `ruff format --check` red after you ran `ruff format` → you edited after formatting; run it again, never hand-align.
3. Three failed iterations on one task → append a `BLOCKED` row to `LEDGER.md` (hypothesis, commands run, outputs), commit what is green, open the PR as draft, stop.
4. Never widen scope to unblock. Never disable a test to unblock.
5. Ambiguity → choose the option closest to the spec, mark it `†` in the hand-off, continue.
