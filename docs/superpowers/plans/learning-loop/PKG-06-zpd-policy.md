# PKG-06 zpd-policy — Learning Loop series (8 of 17)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> You are a fresh session. Nothing outside this file, `docs/superpowers/plans/learning-loop/LEDGER.md`, `HANDOFF-00.md`/`HANDOFF-01.md`/`HANDOFF-02.md`/`HANDOFF-03.md`/`HANDOFF-04.md`, and the files this prompt lists is known to you. Do not infer intent from chat history you do not have. Do not read the whole research corpus; read the sections named below.

## Package id + goal

**PKG-06 `zpd-policy`.** After this package: the ZPD policy layer exists in pure code — the hint ladder with the deterministic check pose and H2/H4/H6 template content (`learning/ladder.py`: `check_pose`, `deterministic_content`, spec §13 A17), the ceiling/evidence/band/wheel-spin policy plus the tutor tier router and the per-phase context policy (`learning/policy.py`: `model_tier` per A15 and the §3.5 `LOOP_MODEL_TIER` table, `context_policy` per A18), the attempt and rung gates (`learning/gates.py`), the deterministic answer-leak detector and stripper (`learning/leak.py`); `sessions.loop_state` exists and round-trips through `learning/loop_state_store.py`; the six `zpd.*` event types are in `EVENT_TAXONOMY` with typed emit helpers in `learning/zpd_events.py` (`zpd.step` carries `tier` and `grader_backend`, A15/A24); invariants 4 and 5 are asserted and invariant 2 is extended (A17). Nothing calls any of it yet: PKG-07 wires the loop tutor through it. `tests/test_learning_zpd_policy.py` proves it.

Branch: `feat/learning-loop-06-zpd-policy`. PR title: `feat(learning): PKG-06 zpd-policy`.

Depends on (spec §14): **03, 04** (code). The series runs strictly one package at a time in the §14 order (… 04, 05, 05b, **06**, 06b, 07 …), so 05 and 05b are merged before you start and 06b comes after you.

## Read before you start (in this order)

0. `docs/superpowers/specs/2026-09-26-learning-loop-design.md` **§13 Amendments log** — in force; where this file and §13 disagree, §13 wins. Re-read it before Task 1.
1. Same spec: §3.5–§3.6 (cost/routing/decision constants — `LOOP_MODEL_TIER`, `LOOP_RAG_K_TEACH*`, `LOOP_SOURCE_CHUNKS_MAX`), §7 (two-phase gate), §8 (invariants 13–29 — which numbers exist and who owns them), §14 (order and dependencies).
2. `docs/superpowers/plans/learning-loop/LEDGER.md` — refuse to start if any row is `blocked` or `in-progress`. Rows 00, 01, 02, 03, 04, 05, 05b must be `done` or `verified` (§14 order; your code depends on 03 and 04).
3. `docs/superpowers/plans/learning-loop/HANDOFF-03.md`, then `HANDOFF-04.md` (the `CheckItem` field names — `question_hash`, `concept_key`, `format`, `difficulty`, `prompt`, `reference_answer`, `stepwise` — that `ladder.ItemLike` mirrors), `HANDOFF-01.md` (the constant names `params.py` actually exports) and `HANDOFF-02.md` (whether `fsrs.py` exports rating names).
4. `CLAUDE.md` §Conventions and §Gotchas — the standing rules the "Do not" list below repeats.
5. `docs/superpowers/specs/2026-09-26-learning-loop-design.md` §3.3 (ladder, ceiling, gates, bands — the table you implement exactly), §3.4 (`LEAK_NGRAM`, `ZPD_RATING_EVERY_N_CHECKS`), §3.5 (the `LOOP_MODEL_TIER` table you implement exactly, and the loop-tutor constants table), §4 (the PKG-06 DDL), §6 (events — `zpd.step` gains `tier` and `grader_backend`), §8 invariants 2 (A17 extension), 4 and 5, §9 (lazy sessions), §13 rows **A15** (`model_tier`), **A17** (`check_pose`, `deterministic_content`), **A18** (`context_policy`), A24 (`zpd.step` keys). Skim §3.1 for the band and weight names and §3.2 for the rating integers.
6. `docs/research/learning-loop/ZPD lever tradeoffs and upgrades.md` § "Sapling ZPD policy spec" (lines ~143–233: the STATE / LADDER / CEILING / GATES / BAND CONTROL / EVIDENCE MAPPING / LOG blocks — the spec's §3.3 is a transcription of this). Skip the rest.
7. `docs/research/learning-loop/AI tutor learning loop research.md` § "Guardrails: withhold answers, ground in verified solutions, gate the grader" (lines ~131–137, the paragraph on the deterministic solution stripper and the H7 reconciliation). Skip the rest.
8. `docs/superpowers/plans/learning-loop/README.md` — series conventions. `HANDOFF-template.md` — what you write at the end.
9. Code you will modify: `backend/services/events_service.py:97–170` (`EVENT_TAXONOMY` and the docstring table above it; `log_event` at :199 — line numbers drift: PKG-04 and PKG-05b appended entries), `backend/tests/test_event_capture_seams.py:84–120` (`test_event_taxonomy_is_pinned`), `backend/tests/test_learning_loop_invariants.py` (`test_inv_04`, `test_inv_05` placeholders; `test_inv_02`, which you extend), `backend/learning/{ladder,policy,gates,leak}.py` (PKG-00 docstring stubs), `backend/learning/params.py` (PKG-01; you may add names, never change values).
10. Code you will mirror: `backend/learning/checks.py` (PKG-04 `CheckItem` — the attribute names `ItemLike` declares; never import it from `ladder.py`), `backend/tests/test_graph_service.py:25–38` (`_mock_table` factory), `backend/tests/test_events_service.py:118–150` (patching `events_service.table` / `log_event` shape), `backend/db/connection.py:31–112` (`select(columns, filters=, limit=)`, `update(data, filters)` returns updated rows, `upsert(data, on_conflict=)`), `backend/routes/learn.py:36` and `:420–434` (lazy session row; `sessions` NOT NULL columns `user_id`, `mode`, `topic`), `backend/db/migrations/0025_study_integrity.sql:70–81` (the `sessions` table).

## State of the world

Verify the base before Task 1. Every row must be green.

| check | command | expected |
|---|---|---|
| hermetic suite green | `cd backend && venv/bin/python -m pytest tests/ -q -x` | `… passed` (note the count N₀) |
| lint green | `cd backend && venv/bin/ruff check .` | `All checks passed!` |
| PKG-00 | `cd backend && venv/bin/python -m pytest tests/test_learning_gate.py -q` | `13 passed` |
| PKG-00 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q` | `4 passed, 8 skipped (later packages raise the passed count)` — with 01–05b merged the passed count is higher, zero failures, and `test_inv_04`/`test_inv_05` are still skipped |
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
| PKG-04 | `cd backend && venv/bin/python -m pytest tests/test_learning_check_items.py -q` | `N passed (N ≥ 14)` |
| PKG-04 | `ls backend/db/migrations/*_learning_check_items.sql` | `1 file` |
| PKG-04 | `grep -c '"check_items"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py` | `≥ 1 each` |
| PKG-04 | `grep -ohE "options_json\|correct_option\|answer_kind\|canonical_answer\|canonical_verified\|stepwise" backend/db/migrations/*_learning_check_items.sql \| sort -u \| wc -l` | `6` |
| PKG-04 | `grep -c -- "--all-courses" backend/scripts/backfill_check_items.py` | `≥ 1` |
| PKG-04 | `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/check_items.py` | `every evaluator ≥ baseline` |
| PKG-04 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_06 or inv_09 or inv_12"` | `3 passed` |
| stubs are stubs | `wc -l backend/learning/ladder.py backend/learning/policy.py backend/learning/gates.py backend/learning/leak.py` | each ≤ 5 lines (docstring only) |
| taxonomy untouched | `grep -c '"zpd\.' backend/services/events_service.py` | `0` |
| latest migration prefix | `ls backend/db/migrations \| tail -1` | a `2026…` timestamped file; your migration's prefix must sort after it |

Rule: any red row → STOP. Diagnose, repair on this branch as commit `fix(learning-loop): PKG-NN — <what>` (NN = the package whose row is red), record the deviation in `LEDGER.md` (row `NN | reopened`), append "Post-hoc changes" to that `HANDOFF-NN.md`, re-run all rows. Never build on a broken base. After the rows pass, mark rows 03 and 04 (your code dependencies) `verified` in the ledger with today's date and the command → output — new rows; the ledger is append-only, so an earlier `verified` row from PKG-05 stays.

## Spec

### Behaviour

1. `learning/ladder.py`: `class Rung(IntEnum)` with members `H0..H6` valued 0..6, `RUNG_INTENT: dict[Rung, str]` (what the tutor may emit at that rung — an instruction to the tutor, never prose for the student), `intent(rung) -> str`, `next_rung(rung) -> Rung` (clamped at `H6`); plus the deterministic-turn helpers of Behaviour 14 (`check_pose`, `deterministic_content`, `ItemLike`, `DeterministicPayload`).
2. `learning/policy.py` is pure and typed: dataclasses `StepState`, `LearnerView`, `LoopState`; enums `BandAction`, `CeilingReason`; `Literal` aliases `Band`, `Tier`, `TurnPhase`, `ContextPhase`, `BudgetLevel`, `ToolChoice`; `ContextPolicy`; functions `ceiling`, `ceiling_with_reason`, `attempt_first`, `evidence_for_rung`, `band_control`, `unassisted_rate`, `wheelspin`, `model_tier` (Behaviour 12), `context_policy` (Behaviour 13). No public function takes a `str` parameter; `model_tier` and `context_policy` take only `Literal`/enum/`bool`/`int` parameters; the module never imports `re` or `learning.gates` (invariant 4). Timestamps are `float` Unix seconds so tests pass fake clocks.
3. `ceiling(learner, step)` implements the spec §3.3 table as first-match over: `exam_mode` → `H1`; `profic` → `H1`, `H3` once `step.genuine_attempts ≥ CEILING_PROFIC_ESCALATE_FAILS`; `develop` → `H3 + genuine_attempts`, `H6` once `≥ CEILING_DEVELOP_H6_FAILS`; `novice` with `prereq_proficient` → `H5`; `novice` without → `H4` at zero attempts, `H5` after. Then the shown-work floor: `showed_work` raises the result to at least `H3`, except in exam mode (exam mode is the strictest row and wins). While a step is open, every recorded genuine attempt is a failed one (a correct attempt closes the step), so `genuine_attempts` is the failed-attempt count the table speaks of. `ceiling_with_reason` returns `(Rung, CeilingReason)`; `attempt_first(learner)` is `False` only for the novice-without-prerequisite row (worked example before any attempt).
4. `evidence_for_rung(correct, max_rung, same_session=False) -> RungEvidence(weight, counts_toward_streak, fsrs_rating)` per spec §3.3 "Evidence mapping": unassisted correct (`max_rung == H0`) → `(1.0, True, FSRS_RATING_GOOD)`; correct after `H1..H3` → `(WEIGHT_ASSISTED, False, FSRS_RATING_HARD)`; correct after `H4..H6` → `(0.0, False, FSRS_RATING_AGAIN)` — zero weight is the "no upward BKT evidence" signal PKG-07 turns into the isomorph re-ask; wrong at any rung → `(1.0, False, FSRS_RATING_AGAIN)`. `same_session=True` multiplies the weight by `WEIGHT_SAME_SESSION_RECHECK`.
5. `band_control(window, p_known, stable, *, wheelspin=False) -> BandAction`: `window` is the newest-last list of unassisted first-attempt outcomes (`bool`), at most `BAND_WINDOW × BAND_CONTROL_STOP_WINDOWS` long; the rate is the mean of the last `BAND_WINDOW`. `wheelspin` → `WHEELSPIN`; empty window → `HOLD`; rate `> BAND_CONTROL_HI` for both the last and the preceding full window AND `p_known ≥ BKT_PROFICIENT` AND `stable` → `STOP_PRACTICE`; rate `> BAND_CONTROL_HI` otherwise → `HARDER`; rate `< PRACTICE_TARGET_LO` → `EASIER_CHECK_PREREQS`; else `HOLD`.
6. `wheelspin(opps, ever_streak3, unassisted_next) -> bool` = `opps ≥ WHEELSPIN_OPPS and not ever_streak3`, or `opps ≥ WHEELSPIN_OPPS_EARLY and unassisted_next < WHEELSPIN_UNASSISTED_MAX` (`unassisted_next is None` never satisfies the second clause). The caller computes `ever_streak3 = max streak ever ≥ BKT_MASTERED_MIN_STRONG`.
7. `learning/gates.py`: `NON_ATTEMPT_PATTERNS` (exactly: `"just tell me"`, `"give me the answer"`, `"idk"`, `"i don't know"`, `"what's the answer"`), `matches_non_attempt(text) -> bool` (lowercase, apostrophes deleted, non-alphanumerics → space, whole-phrase match), `is_genuine_attempt(text_len_chars, has_shown_work, matched_non_attempt, independent_seconds, band) -> bool` (`False` when matched, when there is neither text nor shown work, or when `independent_seconds` is below `GATE_INDEPENDENT_MIN_S_NOVICE` for `novice` / `GATE_INDEPENDENT_MIN_S` otherwise), `rung_unlock(step, now) -> bool` (dwell since `last_rung_at`, or since `first_shown_at` when no rung was shown, `≥ GATE_RUNG_DWELL_MIN_S`, AND some `attempted_at` after that anchor), `h6_allowed(step, item_taught, item_graded) -> bool` (`genuine_attempts ≥ H6_MIN_GENUINE_ATTEMPTS and item_taught and not item_graded and not step.exam_mode`), `offer_allowed(band, last_attempt_wrong) -> bool` (`band in OFFER_BANDS and last_attempt_wrong`). Only `matches_non_attempt` sees text; callers append to `step.attempted_at` only when `is_genuine_attempt` is `True`.
8. `learning/leak.py`: `detect_leak(reference_answer, emitted, rung) -> LeakVerdict(leaked, detector)` with `detector ∈ {"none", "ngram", "final_answer"}`. `rung ≥ H6` → never leaked. `ngram`: any `LEAK_NGRAM` consecutive normalized tokens (`[a-z0-9]+` over lowercase) of the reference appear consecutively in the emitted text. `final_answer`: the reference's final answer — the text after its last `=`, else its last standalone number — tokenized the same way, appears as a consecutive token run in the emitted text. `final_answer(reference) -> tuple[str, ...]` is public (empty tuple when the reference has neither). `strip_leak(emitted, reference) -> str` replaces every leaked run with `[withheld]` until `detect_leak` at `H0` reports `none`; deterministic and idempotent.
9. Session loop state: migration adds `sessions.loop_state jsonb NOT NULL DEFAULT '{}'`. `LoopState.to_json()` / `LoopState.from_json()` (in `policy.py`, pure) serialise `{"v", "current", "checks_since_rating", "first_attempts", "steps": {question_hash: {rung, attempts, first_shown_at, last_rung_at, attempted_at, showed_work, exam_mode}}}` — ids, numbers, bools only; `from_json` raises `ValueError` on a malformed document. `learning/loop_state_store.py::load_loop_state(session_id) -> LoopState` (missing row or malformed JSON → fresh `LoopState()`, malformed logs WARNING) and `save_loop_state(session_id, state) -> bool` (`update` by id, `False` + WARNING when no row matched because the lazy session is not materialised yet). It NEVER inserts or upserts a `sessions` row (spec §9, §13 A11: never `upsert` on `sessions`): PKG-07's loop turns materialise the lazy row through the legacy `routes.learn._consume_pending` insert before they save, and later loop writes that may precede materialisation use PKG-09's A11 insert-if-missing helper (`learning/session_close.py::ensure_session_row`).
10. Events: `zpd.step`, `zpd.offer`, `zpd.band_adjust`, `zpd.rating` (category `usage`) and `zpd.wheelspin`, `zpd.leak` (category `error`) join `EVENT_TAXONOMY` — PKG-06 adds only these six; `decision.*` came from PKG-05b and `ai.budget_capped` comes from PKG-06b. `learning/zpd_events.py` exposes `emit_zpd_step`, `emit_zpd_offer`, `emit_zpd_band_adjust`, `emit_zpd_wheelspin`, `emit_zpd_leak`, `emit_zpd_rating`, keyword-only, payload keys exactly spec §6, values ids/counts/enums/bools only (no payload string longer than 64 chars — a sha256 `question_hash` is exactly 64). `emit_zpd_step` also takes `tier: Tier | None = None` (A15: the tier served) and `grader_backend: GraderBackend | None = None` (A22/A24: `deterministic`/`gemini`/`gemini_second`/`jev`, spec §5); each key is in the payload only when its value is not `None` — omitted, never zeroed or blanked. (`variant`, A8, is PKG-14's.)
11. Flag: nothing imports these modules outside `learning/` and `tests/` (a test proves it), so the flag-off product is byte-identical; the only runtime-visible changes are six extra `EVENT_TAXONOMY` strings (`log_event` does not enforce membership) and one jsonb column with a default.
12. Tutor tier routing (A15): `model_tier(phase: TurnPhase, band: Band, rung: Rung, failed_genuine_attempts: int, misconception_active: bool, *, deterministic_payload: bool = False, budget_level: BudgetLevel = "normal", deep_cap_reached: bool = False, novice_deep_cap_reached: bool = False, arm_session: bool = False) -> Tier` implements the spec §3.5 `LOOP_MODEL_TIER` table exactly. `Tier = Literal["lite", "standard", "deep", "none"]` (`none` = no model call: a template or a pause). `TurnPhase = Literal["opener", "teach", "check_pose", "hint", "feedback_correct", "feedback_wrong"]` names the turn being produced: `hint` is any ladder-rung turn (H0 step verification through H6, from `/hint`, `/step/attempt` or `[ACTION: hint]`); `feedback_correct`/`feedback_wrong` is the ONE feedback turn after a graded explicit submission (A16). `deterministic_payload` is `True` only when the caller already holds a leak-clean payload for this rung (Behaviour 14 + `leak.detect_leak`). `deep_cap_reached` = the session's deep requests ≥ `LOOP_SESSION_MAX_DEEP_REQUESTS`; `novice_deep_cap_reached` = ≥ `LOOP_SESSION_MAX_DEEP_REQUESTS_NOVICE` (both PKG-06b constants; the caller compares, this function takes the booleans). First match wins:
    1. `budget_level == "hard"` → `none` (deterministic only; `loop_arm` sessions pause here too).
    2. `check_pose`; `hint` at H2 or H4 with `deterministic_payload`; `hint` at H6 → `none` (template).
    3. `feedback_correct`; proficient-band verification = `hint` at H0 with `band == "profic"` † → `lite`.
    4. `teach` in the novice band; `hint` at H4 (reaching here means no usable sibling); `hint` at H5; `misconception_active` (PKG-10's confrontation); `failed_genuine_attempts ≥ LOOP_TIER_DEEP_MIN_FAILS` → `deep`.
    5. Everything else → `standard`: the opener; `teach` in the develop or proficient band; `hint` at H1/H3; `feedback_wrong`; and † the model turns the table does not name (`hint` at H2 with no clean payload, `hint` at H0 outside the proficient band).
    Then, only when the base tier is `deep` and `arm_session` is `False`: develop/profic turns → `standard` when `budget_level == "soft"` or `deep_cap_reached`; novice turns → `standard` only when `novice_deep_cap_reached` (the $-based soft level never downgrades novice deep turns, and `deep_cap_reached` is not the novice cap). No adjustment ever raises a tier.
13. Context and tool policy (A18): `context_policy(phase: ContextPhase, *, opener: bool, budget_level: BudgetLevel) -> ContextPolicy(rag_k, graph_block, source_chunks, catalog, tool_choice)` with `ContextPhase = Literal["teach", "check", "hint", "feedback"]` and `ToolChoice = Literal["auto", "none"]`. `teach` → `rag_k = LOOP_RAG_K_TEACH`, `graph_block = True`, `source_chunks = 0`, `tool_choice = "auto"`; at `soft` (and at `hard`, where no model runs anyway) `rag_k = LOOP_RAG_K_TEACH_SOFT` and `tool_choice = "none"`. `hint` and `feedback` → `rag_k = 0`, no graph block, `source_chunks = LOOP_SOURCE_CHUNKS_MAX` (the item's own source chunks, which PKG-07 resolves through the visibility-aware reader), `tool_choice = "none"`. `check` → nothing (`0`, `False`, `0`, `"none"`). `catalog = opener` in every phase (catalog on the opener only). `tool_choice = "none"` is the whole tool policy: PKG-07 keeps both tool declarations in every phase and passes `ModelSettings(tool_choice='none')`.
14. Deterministic turns (A17), in `ladder.py`, pure: `check_pose(prompt: str) -> str` returns the item prompt verbatim (no model call; the prompt was leak-checked at generation) and raises `ValueError` on a blank prompt. `ItemLike` is a `typing.Protocol` with the attributes `question_hash`, `concept_key`, `format`, `difficulty`, `prompt`, `reference_answer`, `stepwise` (PKG-04's `CheckItem` satisfies it structurally; `ladder.py` never imports `learning.checks`). `DeterministicPayload(rung, text, source, revealed_hash=None)` is a `NamedTuple` with `source ∈ {"passages", "sibling", "reference"}`. `deterministic_content(rung, item: ItemLike, siblings: Sequence[ItemLike], passages: Sequence[str]) -> DeterministicPayload | None`: H2 → the first `LOOP_SOURCE_CHUNKS_MAX` non-blank `passages` (stripped) joined by a blank line, `None` when none is left; H4 → the FIRST sibling with the same `concept_key`, `format` and `difficulty`, a different `question_hash`, `stepwise` true † and a non-blank reference, as its prompt and reference joined by a blank line, `revealed_hash` = the sibling's `question_hash` (PKG-07 appends it to `loop_state["revealed"]`, A23), `None` when no sibling qualifies; H6 → the item's own `reference_answer` (`None` when blank); every other rung → `None`. `passages` is resolved, visibility-filtered, decrypted text the caller passes in (invariant 2). This function never leak-checks and never checks `gates.h6_allowed`: the caller runs `leak.detect_leak(item.reference_answer, payload.text, payload.rung)` on every payload before emitting it (invariant 27, PKG-07) and asks for H6 only under `h6_allowed`.

### Schema (exact)

```sql
-- <ts>_learning_session_loop_state.sql
-- Learning loop series PKG-06: per-session ZPD loop state (spec §4, §9).
-- keyed by question_hash: {rung, attempts, first_shown_at, last_rung_at, attempted_at[]}; no free text.
-- top-level id lists added later: "revealed" (A23, H4 siblings shown), "probe", "plan", "sr", "review" (PKG-08/12).
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS loop_state jsonb NOT NULL DEFAULT '{}'::jsonb;
```

### Named constants

All live in `backend/learning/params.py`. Rows marked *exists* were written by PKG-01 — verify each with `grep -n "^NAME = " backend/learning/params.py`; if a name is missing, add it with the spec value and record "added by PKG-06" in the hand-off. Rows marked *spec-new* are named and valued by spec §3.5 (§13 A15–A18, written after PKG-01 was built): grep first, add each missing one with the spec value and the spec's `†`, and list them under "Constants chosen". Rows marked *new name* carry a value the spec states but does not name; add them (no `†`, the value is spec-given) and list them under "Constants chosen". `†` = engineering choice with no validated cut-point (spec §3.3, §3.5), repeated in the hand-off. The budget constants (`STUDENT_*`, `LOOP_SESSION_MAX_*`) are PKG-06b's and the thinking/visible-token constants PKG-07's — `model_tier` and `context_policy` take the budget level and the cap booleans as arguments and never read them.

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
| `LOOP_RAG_K_TEACH` | 5 | §3.5 (A18; unchanged from legacy) | spec-new | `context_policy` teach |
| `LOOP_RAG_K_TEACH_SOFT` | 3 † | §3.5 (A18; soft budget level) | spec-new | `context_policy` teach at soft/hard |
| `LOOP_SOURCE_CHUNKS_MAX` | 2 † | §3.5 (A17/A18) | spec-new | `context_policy` hint/feedback, `deterministic_content` H2 |
| `LOOP_TIER_DEEP_MIN_FAILS` | 2 | §3.5 `LOOP_MODEL_TIER` ("≥ 2 failed genuine attempts" → deep) | new name | `model_tier` |

The only bare numerals permitted in the new modules are `0`, `1`, `0.0`, `1.0` (identity / empty) and the `Rung` member values.

### Invariants asserted by this package (spec §8 numbering)

- (4) `policy.py`: no module-level public function has a parameter whose annotation mentions `str`; `ceiling`, `band_control`, `model_tier` and `context_policy` exist; every parameter of `model_tier` and `context_policy` is annotated with one of `bool`, `int`, `Rung`, `Band`, `TurnPhase`, `ContextPhase`, `BudgetLevel`, and `Band`/`Tier`/`TurnPhase`/`ContextPhase`/`BudgetLevel` are `Literal[...]` aliases; the source contains neither `import re` nor `gates` nor `matches_non_attempt`. Asserted by AST scan in `test_inv_04_policy_takes_no_message_text` (Task 1 writes it; Task 3b extends it for the two routing functions).
- (5) every `"zpd.…"`, `"learn.…"`, `"review.…"`, `"ai.…"`, `"decision.…"` string literal under `backend/` (excluding `tests/`, `venv/`) is a member of `EVENT_TAXONOMY`, and at least one `zpd.*` literal exists. Asserted by source grep in `test_inv_05_series_event_names_in_taxonomy`.
- (2) extended (A17): `ladder.py` imports nothing from `services`/`routes` either, and `deterministic_content`'s parameters are exactly `(rung, item, siblings, passages)` — passage text arrives as an argument, never resolved inside `learning/`. Asserted by extending PKG-00's `test_inv_02_pure_modules_import_nothing_impure` in place (Task 5b).
- (7) keeps passing: the four pure modules import only `learning.*`, stdlib; `loop_state_store.py` has `from db.connection import table`.

### Error semantics

Pure modules never touch I/O and raise only on programmer error (`ValueError` from `LoopState.from_json`; `ValueError` from `check_pose` on a blank prompt — PKG-04's validator never stores one). `model_tier` and `context_policy` are total over their `Literal` domains and never raise. `deterministic_content` never raises for missing content: no passages, no qualifying sibling or a blank reference returns `None`, and the caller lets the LLM write the rung. `loop_state_store` fails soft: a malformed stored document or a missing row yields a fresh `LoopState()`; a save that matches no row returns `False` and logs WARNING — it never raises into a request. Event helpers delegate to `log_event`, which never raises. No agent runs here, so no ADR 0024 degrade path is touched.

### Events added

`zpd.step`, `zpd.offer`, `zpd.band_adjust`, `zpd.rating` (`usage`); `zpd.wheelspin`, `zpd.leak` (`error`). Payload keys per spec §6, ids/counts/enums only; `zpd.step` carries `tier` and `grader_backend` when the caller passes them (omitted when `None`). Only these six are added here: `decision.made`/`decision.shadow`/`decision.fallback` are PKG-05b's, `ai.budget_capped` is PKG-06b's. Emitted by nobody in this package; PKG-07/08/10 call the helpers.

## Non-goals

- No route, agent, tool, prompt, or `chat_stream.py` change. No call to `learning.gate`. No frontend change.
- No LLM judge for leaks (the detector is deterministic; the judge is PKG-14's eval rung). `services/decisions.judge_leak` exists since PKG-05b but stays unwired — nothing in this package calls it. No misconception logic (PKG-10), no probe/plan (PKG-08), no derived nightly metrics (`htc_k`, `assist_gap`, `in_zone` — PKG-14's `derive_zpd_metrics.py`).
- No change to `learner_state` or `apply_graph_update` (PKG-03 owns them). No `lru_cache`.
- No budget logic: no `ai_budget` call, no `llm_usage` read, no budget or session-cap constants (PKG-06b). `model_tier`/`context_policy` receive the level and the cap booleans. No tier slots, thinking budgets or `model_for` calls (PKG-07). No `rag_service.chunks_for_ids`, no `seen_hashes`/`revealed_hashes` (PKG-07). No `ai.*` or `decision.*` taxonomy entries.

## Tasks

### Task 1: Invariants 4 and 5

**Files:**
- Modify: `backend/tests/test_learning_loop_invariants.py` (replace the two `pytest.skip` placeholders; add nothing else — Task 3b extends `test_inv_04` and Task 5b extends `test_inv_02` in place)

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
            if re.search(r"\bstr\b", ann) or _TEXTLIKE_PARAM.search(arg.name):
                offenders.append(f"{node.name}({arg.name}: {ann or 'unannotated'})")
    assert not offenders, f"policy.py public functions take text-shaped params: {offenders}"
    for name in ("ceiling", "band_control"):
        assert any(isinstance(n, ast.FunctionDef) and n.name == name for n in tree.body), f"{name}() missing"


# Spec §8.5 as amended: zpd/learn/review plus ai (PKG-06b) and decision (PKG-05b).
_SERIES_EVENT_LITERAL = re.compile(r'"((?:zpd|learn|review|ai|decision)\.[a-z_]+)"')


def test_inv_05_series_event_names_in_taxonomy():
    from services.events_service import EVENT_TAXONOMY

    found: set[str] = set()
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND).parts
        if rel[0] in ("tests", "venv", ".venv"):
            continue
        for m in _SERIES_EVENT_LITERAL.finditer(path.read_text(errors="ignore")):
            found.add(m.group(1))
    assert any(f.startswith("zpd.") for f in found), "no zpd.* literal found under backend/ — PKG-06 adds them"
    missing = sorted(found - EVENT_TAXONOMY)
    assert not missing, f"series event literals not in EVENT_TAXONOMY: {missing}"
```

- [ ] **Step 2: Run to see the current state**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -v -k "inv_04 or inv_05"`
Expected: `test_inv_04` FAIL — `ceiling() missing` (the stub has no functions); `test_inv_05` FAIL — `no zpd.* literal found under backend/` (PKG-04's `learn.check_items_failed` and PKG-05b's `decision.*` literals are found and are already members; a `missing` failure here instead means an earlier package broke the taxonomy — STOP and repair it as a reopen).

- [ ] **Step 3: Commit**

```
git add backend/tests/test_learning_loop_invariants.py
git commit -m "test(learning-loop): PKG-06 — invariants 4 and 5

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
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
    "LOOP_RAG_K_TEACH", "LOOP_RAG_K_TEACH_SOFT", "LOOP_SOURCE_CHUNKS_MAX", "LOOP_TIER_DEEP_MIN_FAILS",
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
    assert 0 < params.LOOP_RAG_K_TEACH_SOFT < params.LOOP_RAG_K_TEACH
    assert params.LOOP_SOURCE_CHUNKS_MAX >= 1 and params.LOOP_TIER_DEEP_MIN_FAILS >= 1


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
Expected: the `FSRS_RATING_*`, `BAND_CONTROL_*`, `CEILING_*`, `WHEELSPIN_OPPS_EARLY`, `WHEELSPIN_UNASSISTED_MAX`, `LOOP_*` param cases FAIL (`learning.params lacks …`) unless an earlier package already named them; `test_params_relations_hold` FAIL (`AttributeError`); `test_ladder…` FAIL — `ImportError: cannot import name 'Rung'`.

- [ ] **Step 3: Implement**

`backend/learning/params.py` — append a `# PKG-06 (spec §3.2 / §3.3 / §3.5)` block containing only the names the grep in §Named constants showed missing, each with a one-line comment naming its spec row (and `†` in the comment where the table has one). If `HANDOFF-02.md` says `fsrs.py` exports rating constants under other names, do NOT add `FSRS_RATING_*`; instead alias them in `params.py` (`FSRS_RATING_AGAIN = <theirs>`) so this package's tests and PKG-07 have one spelling.

`backend/learning/ladder.py`:

```python
"""Hint ladder (spec §3.3) and deterministic turns (spec §13 A17). Pure:
stdlib and learning.* only (invariant 2).

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

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
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

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 3b: `policy.py` — tutor tier routing and context policy (A15, A18)

**Files:**
- Modify: `backend/learning/policy.py`, `backend/tests/test_learning_zpd_policy.py`, `backend/tests/test_learning_loop_invariants.py` (extend `test_inv_04` in place; never a new test function, never delete an assertion)

**Interfaces:**
- Consumes: `learning.ladder.Rung`, `learning.params` (`LOOP_RAG_K_TEACH`, `LOOP_RAG_K_TEACH_SOFT`, `LOOP_SOURCE_CHUNKS_MAX`, `LOOP_TIER_DEEP_MIN_FAILS`).
- Produces: `Tier`, `TurnPhase`, `ContextPhase`, `BudgetLevel`, `ToolChoice`, `ContextPolicy`, `model_tier`, `context_policy`. PKG-07 calls both per turn; PKG-06b's `BudgetDecision.tier_ceiling` reuses `Tier`; PKG-10 passes `misconception_active=True`.

- [ ] **Step 1: Write the failing tests** (append to `test_learning_zpd_policy.py`; extend `test_inv_04`)

```python
# ── policy: tutor tier routing (spec §3.5 LOOP_MODEL_TIER, A15) ────────────────

TIER_ORDER = {"none": 0, "lite": 1, "standard": 2, "deep": 3}
FAILS = params.LOOP_TIER_DEEP_MIN_FAILS

TIER_CASES = [
    # (phase, band, rung, fails, misconception, kwargs) -> tier
    ("teach", "develop", 0, 0, False, {"budget_level": "hard"}, "none"),
    ("feedback_wrong", "novice", 0, FAILS, True, {"budget_level": "hard", "arm_session": True}, "none"),
    ("check_pose", "novice", 0, 0, False, {}, "none"),
    ("check_pose", "develop", 0, FAILS, True, {}, "none"),                    # the pose is a template, always
    ("hint", "develop", 2, 0, False, {"deterministic_payload": True}, "none"),
    ("hint", "novice", 4, 0, False, {"deterministic_payload": True}, "none"),
    ("hint", "develop", 6, 0, False, {}, "none"),
    ("feedback_correct", "novice", 0, 0, False, {}, "lite"),
    ("feedback_correct", "develop", 0, FAILS, False, {}, "lite"),             # a correct answer closed the step
    ("hint", "profic", 0, 0, False, {}, "lite"),                              # proficient-band verification †
    ("teach", "novice", 0, 0, False, {}, "deep"),
    ("hint", "novice", 4, 0, False, {}, "deep"),                              # H4 with no usable sibling
    ("hint", "develop", 5, 0, False, {}, "deep"),
    ("teach", "develop", 0, 0, True, {}, "deep"),                             # misconception confrontation
    ("hint", "develop", 1, FAILS, False, {}, "deep"),
    ("feedback_wrong", "profic", 0, FAILS, False, {}, "deep"),
    ("opener", "novice", 0, 0, False, {}, "standard"),
    ("teach", "develop", 0, 0, False, {}, "standard"),
    ("teach", "profic", 0, 0, False, {}, "standard"),
    ("hint", "develop", 1, FAILS - 1, False, {}, "standard"),
    ("hint", "novice", 3, 0, False, {}, "standard"),
    ("feedback_wrong", "develop", 0, FAILS - 1, False, {}, "standard"),
    ("hint", "develop", 2, 0, False, {}, "standard"),                         # H2, no clean payload †
    ("hint", "develop", 0, 0, False, {}, "standard"),                         # H0 outside profic †
    # then-rows: downgrades (deep -> standard only)
    ("teach", "develop", 0, 0, True, {"budget_level": "soft"}, "standard"),
    ("hint", "profic", 5, 0, False, {"deep_cap_reached": True}, "standard"),
    ("teach", "develop", 0, 0, True, {"budget_level": "soft", "arm_session": True}, "deep"),
    ("teach", "novice", 0, 0, False, {"budget_level": "soft"}, "deep"),     # $-soft never downgrades novice deep
    ("teach", "novice", 0, 0, False, {"deep_cap_reached": True}, "deep"),   # the develop/profic cap is not the novice cap
    ("teach", "novice", 0, 0, False, {"novice_deep_cap_reached": True}, "standard"),
    ("teach", "novice", 0, 0, False, {"novice_deep_cap_reached": True, "arm_session": True}, "deep"),
    ("hint", "develop", 5, 0, False, {"novice_deep_cap_reached": True}, "deep"),
    ("feedback_correct", "develop", 0, 0, False, {"budget_level": "soft"}, "lite"),
]


@pytest.mark.parametrize("phase,band,rung,fails,misc,kw,tier", TIER_CASES)
def test_model_tier_table(phase, band, rung, fails, misc, kw, tier):
    from learning.ladder import Rung
    from learning.policy import model_tier

    assert model_tier(phase, band, Rung(rung), fails, misc, **kw) == tier


def test_model_tier_adjustments_never_raise_a_tier():
    import itertools
    from typing import get_args

    from learning.ladder import Rung
    from learning.policy import Tier, TurnPhase, model_tier

    flags = [{"budget_level": "soft"}, {"deep_cap_reached": True}, {"novice_deep_cap_reached": True},
             {"budget_level": "soft", "arm_session": True}]
    for phase, band, rung, fails, misc, det in itertools.product(
        get_args(TurnPhase), ("novice", "develop", "profic"), list(Rung), range(FAILS + 1), (False, True), (False, True)
    ):
        base = model_tier(phase, band, rung, fails, misc, deterministic_payload=det)
        assert base in get_args(Tier)
        assert model_tier(phase, band, rung, fails, misc, deterministic_payload=det, budget_level="hard") == "none"
        assert model_tier(phase, band, rung, fails, misc, deterministic_payload=det, arm_session=True) == base
        for kw in flags:
            adjusted = model_tier(phase, band, rung, fails, misc, deterministic_payload=det, **kw)
            assert TIER_ORDER[adjusted] <= TIER_ORDER[base], (phase, band, rung, fails, misc, det, kw)
            assert adjusted == base or (base, adjusted) == ("deep", "standard")


# ── policy: context and tool policy by phase (A18) ────────────────────────────


def test_context_policy_by_phase():
    from learning.policy import ContextPolicy, context_policy

    k, k_soft, chunks = params.LOOP_RAG_K_TEACH, params.LOOP_RAG_K_TEACH_SOFT, params.LOOP_SOURCE_CHUNKS_MAX
    assert context_policy("teach", opener=False, budget_level="normal") == ContextPolicy(k, True, 0, False, "auto")
    assert context_policy("teach", opener=True, budget_level="normal") == ContextPolicy(k, True, 0, True, "auto")
    for level in ("soft", "hard"):
        assert context_policy("teach", opener=False, budget_level=level) == ContextPolicy(k_soft, True, 0, False, "none")
    for phase in ("hint", "feedback"):
        for level in ("normal", "soft", "hard"):
            assert context_policy(phase, opener=False, budget_level=level) == ContextPolicy(0, False, chunks, False, "none")
    assert context_policy("check", opener=False, budget_level="normal") == ContextPolicy(0, False, 0, False, "none")


def test_context_policy_catalog_only_on_the_opener_and_tools_only_in_normal_teach():
    from typing import get_args

    from learning.policy import BudgetLevel, ContextPhase, context_policy

    for phase in get_args(ContextPhase):
        for level in get_args(BudgetLevel):
            assert context_policy(phase, opener=False, budget_level=level).catalog is False
            assert context_policy(phase, opener=True, budget_level=level).catalog is True
            expected = "auto" if (phase == "teach" and level == "normal") else "none"
            assert context_policy(phase, opener=False, budget_level=level).tool_choice == expected
```

Extend `test_inv_04_policy_takes_no_message_text` in `backend/tests/test_learning_loop_invariants.py`. Module level, next to `_TEXTLIKE_PARAM`:

```python
_ROUTING_FUNCS = ("model_tier", "context_policy")
_ROUTING_ANN = re.compile(r"bool|int|Rung|Band|TurnPhase|ContextPhase|BudgetLevel")
```

Appended at the end of the `test_inv_04` body:

```python
    # A15/A18 (PKG-06 Task 3b): the routing functions take typed state only.
    aliases = {t.id: ast.unparse(n.value) for n in tree.body if isinstance(n, ast.Assign)
               for t in n.targets if isinstance(t, ast.Name)}
    for alias in ("Band", "Tier", "TurnPhase", "ContextPhase", "BudgetLevel"):
        assert aliases.get(alias, "").startswith("Literal["), f"{alias} must be a Literal alias"
    for name in _ROUTING_FUNCS:
        node = next((n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name), None)
        assert node is not None, f"{name}() missing"
        for arg in node.args.args + node.args.kwonlyargs + node.args.posonlyargs:
            ann = ast.unparse(arg.annotation) if arg.annotation is not None else ""
            assert _ROUTING_ANN.fullmatch(ann), f"{name}({arg.name}: {ann or 'unannotated'}): Literal/enum/bool/int only"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_zpd_policy.py tests/test_learning_loop_invariants.py -v -k "model_tier or context_policy or inv_04"`
Expected: the tier and context cases FAIL — `ImportError: cannot import name 'model_tier' from 'learning.policy'`; `test_inv_04` FAIL — `Tier must be a Literal alias`.

- [ ] **Step 3: Implement** — add to `backend/learning/policy.py` (the `Band` alias from Task 3 stays; put the new aliases next to it):

```python
Tier = Literal["lite", "standard", "deep", "none"]          # "none" = no model call (template or pause)
TurnPhase = Literal["opener", "teach", "check_pose", "hint", "feedback_correct", "feedback_wrong"]
ContextPhase = Literal["teach", "check", "hint", "feedback"]
BudgetLevel = Literal["normal", "soft", "hard"]
ToolChoice = Literal["auto", "none"]


class ContextPolicy(NamedTuple):
    rag_k: int
    graph_block: bool
    source_chunks: int          # how many of the item's source_chunk_ids the caller resolves
    catalog: bool
    tool_choice: ToolChoice     # "none" -> ModelSettings(tool_choice='none'); declarations unchanged


def _base_tier(phase: TurnPhase, band: Band, rung: Rung, failed_genuine_attempts: int,
               misconception_active: bool, deterministic_payload: bool) -> Tier:
    """LOOP_MODEL_TIER rows 2-5 (spec §3.5), first match wins."""
    hint = phase == "hint"
    if phase == "check_pose" or (hint and rung == Rung.H6) or (
        hint and rung in (Rung.H2, Rung.H4) and deterministic_payload
    ):
        return "none"
    if phase == "feedback_correct" or (hint and rung == Rung.H0 and band == "profic"):
        return "lite"
    if (
        (phase == "teach" and band == "novice")
        or (hint and rung in (Rung.H4, Rung.H5))
        or misconception_active
        or failed_genuine_attempts >= params.LOOP_TIER_DEEP_MIN_FAILS
    ):
        return "deep"
    return "standard"   # opener, develop/profic teach, H1/H3, feedback_wrong; † any turn the table does not name


def model_tier(phase: TurnPhase, band: Band, rung: Rung, failed_genuine_attempts: int,
               misconception_active: bool, *, deterministic_payload: bool = False,
               budget_level: BudgetLevel = "normal", deep_cap_reached: bool = False,
               novice_deep_cap_reached: bool = False, arm_session: bool = False) -> Tier:
    """Tutor tier for one turn (spec §3.5 LOOP_MODEL_TIER, §13 A15). Typed state in,
    tier out; never the student's text (invariant 4). Adjustments only lower deep."""
    if budget_level == "hard":
        return "none"
    tier = _base_tier(phase, band, Rung(rung), failed_genuine_attempts, misconception_active, deterministic_payload)
    if tier != "deep" or arm_session:
        return tier
    if band == "novice":
        return "standard" if novice_deep_cap_reached else "deep"
    return "standard" if (budget_level == "soft" or deep_cap_reached) else "deep"
```

`context_policy(phase: ContextPhase, *, opener: bool, budget_level: BudgetLevel) -> ContextPolicy` per §Behaviour 13: `constrained = budget_level != "normal"`; `teach` → `ContextPolicy(params.LOOP_RAG_K_TEACH_SOFT if constrained else params.LOOP_RAG_K_TEACH, True, 0, opener, "none" if constrained else "auto")`; `hint`/`feedback` → `ContextPolicy(0, False, params.LOOP_SOURCE_CHUNKS_MAX, opener, "none")`; `check` → `ContextPolicy(0, False, 0, opener, "none")`.

- [ ] **Step 4: Run tests, lint, invariants**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_zpd_policy.py tests/test_learning_loop_invariants.py -q -k "not inv_05" && venv/bin/ruff check .`
Expected: all passed including the extended `test_inv_04`; `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/learning/policy.py backend/tests/test_learning_zpd_policy.py backend/tests/test_learning_loop_invariants.py
git commit -m "feat(learning-loop): PKG-06 — tutor tier routing and context policy (A15, A18)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
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

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
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

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 5b: `ladder.py` — check pose and deterministic H2/H4/H6 content (A17)

**Files:**
- Modify: `backend/learning/ladder.py`, `backend/tests/test_learning_zpd_policy.py`, `backend/tests/test_learning_loop_invariants.py` (extend `test_inv_02` in place; never a new test function, never delete an assertion)

**Interfaces:**
- Consumes: `learning.params.LOOP_SOURCE_CHUNKS_MAX`; in tests only, `learning.leak.detect_leak` (the caller-side check, invariant 27).
- Produces: `ItemLike`, `DeterministicPayload`, `PAYLOAD_JOIN`, `check_pose(prompt)`, `deterministic_content(rung, item, siblings, passages)`. PKG-07 calls both, resolves `passages` through `rag_service.chunks_for_ids(ids, user_id=…)`, leak-checks every payload, and appends `revealed_hash` to `loop_state["revealed"]`.

- [ ] **Step 1: Write the failing tests** (append to `test_learning_zpd_policy.py`; extend `test_inv_02`)

```python
# ── ladder: deterministic turns (spec §13 A17) ────────────────────────────────

ACTIVE_HASH = "a" * 64


def _item(question_hash, **over):
    """Structural stand-in for PKG-04's CheckItem (ladder.ItemLike)."""
    from types import SimpleNamespace

    base = dict(question_hash=question_hash, concept_key="power_rule", format="free", difficulty=2,
                prompt="Differentiate x^3.", reference_answer="Bring the exponent down: 3x^2", stepwise=True)
    return SimpleNamespace(**{**base, **over})


def test_check_pose_is_the_item_prompt_verbatim():
    from learning.ladder import check_pose

    prompt = "Differentiate x^3. Show the first step."
    assert check_pose(prompt) == prompt
    with pytest.raises(ValueError):
        check_pose("   ")


def test_deterministic_h2_joins_at_most_the_source_chunk_cap():
    from learning.ladder import PAYLOAD_JOIN, Rung, deterministic_content

    item = _item(ACTIVE_HASH)
    passages = [f"Passage {i} on the power rule." for i in range(params.LOOP_SOURCE_CHUNKS_MAX + 2)]
    p = deterministic_content(Rung.H2, item, [], ["  "] + passages)
    assert (p.rung, p.source, p.revealed_hash) == (Rung.H2, "passages", None)
    assert p.text == PAYLOAD_JOIN.join(passages[: params.LOOP_SOURCE_CHUNKS_MAX])
    assert deterministic_content(Rung.H2, item, [], []) is None
    assert deterministic_content(Rung.H2, item, [], ["", "  "]) is None


def test_deterministic_h4_takes_the_first_true_isomorph():
    from learning.ladder import PAYLOAD_JOIN, Rung, deterministic_content

    item = _item(ACTIVE_HASH)
    good = _item("b" * 64, prompt="Differentiate x^5.", reference_answer="1. Bring 5 down. 2. Lower the exponent: 5x^4")
    later = _item("g" * 64, prompt="Differentiate x^7.")
    not_isomorphs = [
        _item(ACTIVE_HASH),                          # the active item itself
        _item("c" * 64, concept_key="chain_rule"),   # other concept
        _item("d" * 64, format="teachback"),         # other format
        _item("e" * 64, difficulty=3),               # other difficulty
        _item("f" * 64, stepwise=False),             # not a worked solution
        _item("h" * 64, reference_answer="  "),      # nothing to show
    ]
    p = deterministic_content(Rung.H4, item, [*not_isomorphs, good, later], [])
    assert p == (Rung.H4, PAYLOAD_JOIN.join((good.prompt, good.reference_answer)), "sibling", "b" * 64)
    assert deterministic_content(Rung.H4, item, not_isomorphs, ["a passage"]) is None


def test_deterministic_h6_is_the_reference_and_other_rungs_have_none():
    from learning.ladder import Rung, deterministic_content

    item = _item(ACTIVE_HASH)
    assert deterministic_content(Rung.H6, item, [], []) == (Rung.H6, item.reference_answer, "reference", None)
    assert deterministic_content(Rung.H6, _item(ACTIVE_HASH, reference_answer=""), [], []) is None
    for rung in (Rung.H0, Rung.H1, Rung.H3, Rung.H5):
        assert deterministic_content(rung, item, [_item("b" * 64)], ["a passage"]) is None


def test_deterministic_payloads_are_leak_checked_by_the_caller():
    """Invariant 27's contract: deterministic_content never filters; the caller's
    detect_leak does. A passage quoting the reference leaks at H2; a pointer does not."""
    from learning.ladder import Rung, deterministic_content
    from learning.leak import detect_leak

    item = _item(ACTIVE_HASH, reference_answer=REF_POWER)
    leaking = deterministic_content(Rung.H2, item, [], ["From the notes: " + REF_POWER])
    pointer = deterministic_content(Rung.H2, item, [], ["The power rule is in section 2.3 of your notes; read the first line."])
    assert detect_leak(item.reference_answer, leaking.text, leaking.rung).leaked is True
    assert detect_leak(item.reference_answer, pointer.text, pointer.rung).leaked is False
```

Extend `test_inv_02_pure_modules_import_nothing_impure` in `backend/tests/test_learning_loop_invariants.py` — append at the end of the function body (`ast` was imported in Task 1):

```python
    # A17 extension (PKG-06): passage text reaches ladder.deterministic_content as an
    # argument — ladder.py never resolves, reads or decrypts passages itself.
    ladder = LEARNING / "ladder.py"
    bad = [r for r in _imports_of(ladder) if r in ("services", "routes", "httpx", "supabase")]
    assert not bad, f"ladder.py imports {bad}: passages must be passed in"
    fn = next((n for n in ast.parse(ladder.read_text()).body
               if isinstance(n, ast.FunctionDef) and n.name == "deterministic_content"), None)
    assert fn is not None, "ladder.deterministic_content() missing"
    assert [a.arg for a in fn.args.args] == ["rung", "item", "siblings", "passages"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_zpd_policy.py tests/test_learning_loop_invariants.py -v -k "check_pose or deterministic or inv_02"`
Expected: the ladder cases FAIL — `ImportError: cannot import name 'check_pose' from 'learning.ladder'` (or `'PAYLOAD_JOIN'`); `test_inv_02` FAIL — `ladder.deterministic_content() missing`.

- [ ] **Step 3: Implement** — extend `backend/learning/ladder.py` (keep `Rung`, `RUNG_INTENT`, `intent`, `next_rung` unchanged):

```python
from typing import Literal, NamedTuple, Protocol, Sequence

from learning import params

PAYLOAD_JOIN = "\n\n"
PayloadSource = Literal["passages", "sibling", "reference"]


class ItemLike(Protocol):
    """The check-item fields the ladder reads (PKG-04 CheckItem; spec A2/A22).
    Structural, so ladder.py never imports learning.checks or storage."""

    question_hash: str
    concept_key: str
    format: str
    difficulty: int
    prompt: str
    reference_answer: str
    stepwise: bool


class DeterministicPayload(NamedTuple):
    rung: Rung
    text: str
    source: PayloadSource
    revealed_hash: str | None = None   # H4: the sibling shown (loop_state["revealed"], A23)


def check_pose(prompt: str) -> str:
    """The check-phase turn: the item prompt verbatim, no model call (A17)."""
    if not prompt.strip():
        raise ValueError("check_pose: blank item prompt")
    return prompt


def _is_isomorph(sibling: ItemLike, item: ItemLike) -> bool:
    return (
        sibling.concept_key == item.concept_key
        and sibling.format == item.format
        and sibling.difficulty == item.difficulty
        and sibling.question_hash != item.question_hash
        and bool(sibling.stepwise)
        and bool(sibling.reference_answer.strip())
    )


def deterministic_content(rung: Rung, item: ItemLike, siblings: Sequence[ItemLike],
                          passages: Sequence[str]) -> DeterministicPayload | None:
    """Template content for H2/H4/H6 (spec A17). `passages` is resolved,
    visibility-filtered, decrypted text passed in (invariant 2). The caller runs
    leak.detect_leak(item.reference_answer, payload.text, payload.rung) before
    emitting any payload (invariant 27) and asks for H6 only under
    gates.h6_allowed. None -> the LLM writes the rung."""
    rung = Rung(rung)
    if rung == Rung.H2:
        kept = [p.strip() for p in passages if p.strip()][: params.LOOP_SOURCE_CHUNKS_MAX]
        return DeterministicPayload(rung, PAYLOAD_JOIN.join(kept), "passages") if kept else None
    if rung == Rung.H4:
        for sibling in siblings:
            if _is_isomorph(sibling, item):
                text = PAYLOAD_JOIN.join((sibling.prompt, sibling.reference_answer))
                return DeterministicPayload(rung, text, "sibling", sibling.question_hash)
        return None
    if rung == Rung.H6 and item.reference_answer.strip():
        return DeterministicPayload(rung, item.reference_answer, "reference")
    return None
```

If `HANDOFF-04.md` spells a field differently (e.g. `answer_format`), use PKG-04's spelling in `ItemLike` and `_is_isomorph` and record it under "Deviations"; never add an adapter that imports `learning.checks`.

- [ ] **Step 4: Run tests, lint, invariants**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_zpd_policy.py tests/test_learning_loop_invariants.py -q -k "not inv_05" && venv/bin/ruff check .`
Expected: all passed including the extended `test_inv_02`; `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/learning/ladder.py backend/tests/test_learning_zpd_policy.py backend/tests/test_learning_loop_invariants.py
git commit -m "feat(learning-loop): PKG-06 — check pose and deterministic H2/H4/H6 content (A17)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 6: Migration `learning_session_loop_state` + `loop_state_store.py`

**Files:**
- Create: `backend/db/migrations/<UTC>_learning_session_loop_state.sql`, `backend/learning/loop_state_store.py`
- Modify: `backend/tests/test_learning_zpd_policy.py`

**Interfaces:**
- Consumes: `db.connection.table("sessions")`, `learning.policy.LoopState`.
- Produces: column `sessions.loop_state jsonb NOT NULL DEFAULT '{}'`; `load_loop_state(session_id) -> LoopState`; `save_loop_state(session_id, state) -> bool` (update only — never inserts or upserts a `sessions` row, A11).

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


def test_save_loop_state_never_inserts_or_upserts_sessions(monkeypatch):
    """Spec §9 / §13 A11: never `upsert` on `sessions`. A missing row is reported,
    never created here (PKG-07 materialises through _consume_pending; PKG-09 owns
    the insert-if-missing helper)."""
    import inspect

    from learning import loop_state_store
    from learning.policy import LoopState

    assert list(inspect.signature(loop_state_store.save_loop_state).parameters) == ["session_id", "state"]
    t = _sessions_table(update_rows=[])
    monkeypatch.setattr(loop_state_store, "table", lambda name: t)
    assert loop_state_store.save_loop_state("s1", LoopState()) is False
    t.upsert.assert_not_called()
    t.insert.assert_not_called()
    src = inspect.getsource(loop_state_store)
    assert ".upsert(" not in src and ".insert(" not in src
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_zpd_policy.py -v -k "migration or loop_state_store or save_loop_state or load_loop_state"`
Expected: `test_migration…` FAIL — `expected exactly one loop_state migration, got []`; the rest FAIL — `ImportError: cannot import name 'loop_state_store'`.

- [ ] **Step 3: Write the migration and the store**

Prefix from `date -u +%Y%m%d%H%M%S`; content is §Spec/Schema verbatim including all three comment lines.

`backend/learning/loop_state_store.py`:

```python
"""sessions.loop_state read/write (spec §4 PKG-06, §9). The only impure module
in the ZPD layer; policy.py stays free of db imports.

Sessions are lazy (routes/learn.py:36): the row may not exist until the first
chat turn. `save_loop_state` therefore updates by id and reports a miss; it
never inserts or upserts a sessions row (spec §9, §13 A11). The row is
materialised by the legacy `_consume_pending` insert (PKG-07) or by the A11
insert-if-missing helper (PKG-09)."""
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


def save_loop_state(session_id: str, state: LoopState) -> bool:
    doc = state.to_json()
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

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
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
        r_before=0.93, item_difficulty=2, tier="standard", grader_backend="gemini",
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
        "p_known_before", "p_known_after", "r_before", "item_difficulty", "tier", "grader_backend",
    }
    assert got["zpd.step"]["payload"]["ceiling"] == int(Rung.H3)
    assert got["zpd.step"]["payload"]["ceiling_reason"] == "develop"
    assert (got["zpd.step"]["payload"]["tier"], got["zpd.step"]["payload"]["grader_backend"]) == ("standard", "gemini")
    assert set(got["zpd.offer"]["payload"]) == {"accepted", "band"}
    assert set(got["zpd.band_adjust"]["payload"]) == {"direction", "trigger", "window_stats"}
    assert got["zpd.band_adjust"]["payload"]["direction"] == "harder"
    assert set(got["zpd.wheelspin"]["payload"]) == {"concept_id", "opps", "unassisted_next", "htc_k", "prerequisite_ids"}
    assert set(got["zpd.leak"]["payload"]) == {"rung_emitted", "ceiling", "detector", "request_id"}
    assert set(got["zpd.rating"]["payload"]) == {"rating", "checks_since_last"}
    for et, kw in calls:
        assert kw["user_id"] == "user_andres" and kw["request_id"] == "req-1"
        _assert_ids_only(kw["payload"])


def test_zpd_step_omits_tier_and_grader_backend_when_unset(monkeypatch):
    """A15/A24 keys are omitted when None — never zeroed or blanked."""
    from learning import zpd_events
    from learning.ladder import Rung
    from learning.policy import CeilingReason

    calls = _recorder(monkeypatch)
    zpd_events.emit_zpd_step(
        user_id="u", request_id=None, concept_id="node-1", question_hash="q" * 64, phase="probe",
        channel="free_response", band="novice", ceiling=Rung.H4, ceiling_reason=CeilingReason.NOVICE_WORKED_FIRST,
        first_attempt_correct=True, n_attempts=1, max_rung_used=Rung.H0, rungs=[], time_to_first_attempt_ms=None,
        time_to_correct_ms=None, independent_time_ms=None, assisted=False, confidence=None,
        fsrs_rating=params.FSRS_RATING_GOOD, p_known_before=0.2, p_known_after=0.3, r_before=None, item_difficulty=1,
    )
    [(event_type, kw)] = calls
    assert event_type == "zpd.step"
    assert "tier" not in kw["payload"] and "grader_backend" not in kw["payload"]


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

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_zpd_policy.py -v -k "zpd_events or zpd_step or emit_helpers or inert"`
Expected: `test_zpd_events_in_taxonomy…` FAIL — `assert 'zpd.step' in frozenset(...)`; `test_emit_helpers…` and `test_zpd_step_omits…` FAIL — `ImportError: cannot import name 'zpd_events'`; `test_zpd_layer_is_inert…` PASS.

- [ ] **Step 3: Implement**

`backend/services/events_service.py` — append to `EVENT_TAXONOMY`, after its last existing entry (PKG-05b's `decision.*` block; `"rag.visibility_resync_failed",` if that block sits elsewhere). Add only these six — never `ai.budget_capped` (PKG-06b) and never another `decision.*`:

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

Add six rows to the docstring table above it (event, category, payload keys from spec §6; the `zpd.step` row lists `tier` and `grader_backend` as optional) — without quotes, so `grep -c '"zpd\.'` on the file stays exactly 6.

`backend/tests/test_event_capture_seams.py::test_event_taxonomy_is_pinned` — add the same six strings with a one-line `# PKG-06 (spec §6); emit coverage in test_learning_zpd_policy.py` comment.

`backend/learning/zpd_events.py`:

```python
"""Typed emit helpers for the zpd.* events (spec §6). Payloads carry ids,
counts, enums and bools only — never student or tutor text."""
from __future__ import annotations

from typing import Literal

from learning.ladder import Rung
from learning.policy import Band, BandAction, CeilingReason, Tier
from services.events_service import log_event

Phase = Literal["probe", "plan", "teach", "check", "feedback", "close"]
Rating = Literal["too_easy", "appropriate", "too_hard"]
Detector = Literal["none", "ngram", "final_answer"]
BandTrigger = Literal["high", "stable_high", "low", "wheelspin"]
GraderBackend = Literal["deterministic", "gemini", "gemini_second", "jev"]   # spec §5 (A22/A24)


def emit_zpd_step(*, user_id: str, request_id: str | None, concept_id: str, question_hash: str,
                  phase: Phase, channel: str, band: Band, ceiling: Rung, ceiling_reason: CeilingReason,
                  first_attempt_correct: bool, n_attempts: int, max_rung_used: Rung, rungs: list[dict],
                  time_to_first_attempt_ms: int | None, time_to_correct_ms: int | None,
                  independent_time_ms: int | None, assisted: bool, confidence: float | None,
                  fsrs_rating: int, p_known_before: float, p_known_after: float,
                  r_before: float | None, item_difficulty: int,
                  tier: Tier | None = None, grader_backend: GraderBackend | None = None) -> None:
    payload = {
        "concept_id": concept_id, "question_hash": question_hash, "phase": phase, "channel": channel,
        "band": band, "ceiling": int(ceiling), "ceiling_reason": ceiling_reason.value,
        "first_attempt_correct": first_attempt_correct, "n_attempts": n_attempts,
        "max_rung_used": int(max_rung_used), "rungs": [{"rung": int(r["rung"]), "dwell_ms": int(r["dwell_ms"])} for r in rungs],
        "time_to_first_attempt_ms": time_to_first_attempt_ms, "time_to_correct_ms": time_to_correct_ms,
        "independent_time_ms": independent_time_ms, "assisted": assisted, "confidence": confidence,
        "fsrs_rating": fsrs_rating, "p_known_before": p_known_before, "p_known_after": p_known_after,
        "r_before": r_before, "item_difficulty": item_difficulty,
    }
    # A15/A24: present only when known — omitted, never zeroed or blanked.
    if tier is not None:
        payload["tier"] = tier
    if grader_backend is not None:
        payload["grader_backend"] = grader_backend
    log_event("zpd.step", category="usage", user_id=user_id, request_id=request_id, payload=payload)
```

Then `emit_zpd_offer(*, user_id, request_id, accepted: bool, band: Band)`, `emit_zpd_band_adjust(*, user_id, request_id, direction: BandAction, trigger: BandTrigger, window_stats: dict)` (payload `direction=direction.value`), `emit_zpd_wheelspin(*, user_id, request_id, concept_id, opps: int, unassisted_next: float | None, htc_k: float | None, prerequisite_ids: list[str])` (category `error`), `emit_zpd_leak(*, user_id, request_id, rung_emitted: Rung, ceiling: Rung, detector: Detector)` (category `error`; payload includes `request_id` per spec §6, ints for the rungs), `emit_zpd_rating(*, user_id, request_id, rating: Rating, checks_since_last: int)`. Every payload key set is exactly the spec §6 row (`zpd.step`: `tier`/`grader_backend` only when passed; `variant` is PKG-14's, A8).

- [ ] **Step 4: Run tests, lint, invariants, the pinned seams**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_zpd_policy.py tests/test_learning_loop_invariants.py tests/test_event_capture_seams.py tests/test_events_service.py -q && venv/bin/ruff check .`
Expected: all passed — `test_inv_05` now finds the six `zpd.*` literals in `events_service.py` and `zpd_events.py` (plus PKG-04's `learn.*` and PKG-05b's `decision.*`) and every one is in the taxonomy; `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/services/events_service.py backend/tests/test_event_capture_seams.py backend/learning/zpd_events.py backend/tests/test_learning_zpd_policy.py
git commit -m "feat(learning-loop): PKG-06 — zpd.* events in the taxonomy with typed emit helpers

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 8: Hand-off + ledger

- [ ] **Step 1:** Write `docs/superpowers/plans/learning-loop/HANDOFF-06.md` from `HANDOFF-template.md`. "Verify commands" must be exactly these six lines (they become PKG-07/PKG-10/PKG-14's State-of-the-world rows):

```
cd backend && venv/bin/python -m pytest tests/test_learning_zpd_policy.py -q                    → N passed (N ≥ 35)
grep -cE "^def (ceiling|band_control|evidence_for_rung|wheelspin|model_tier|context_policy)\(" backend/learning/policy.py → 6
grep -cE "^def (check_pose|deterministic_content)\(" backend/learning/ladder.py                  → 2
grep -c '"zpd\.' backend/services/events_service.py                                              → 6
ls backend/db/migrations/*_learning_session_loop_state.sql                                       → 1 file
cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_02 or inv_04 or inv_05" → 3 passed
```

Fill "Constants chosen" with every row of §Named constants, keeping `†` on `GATE_INDEPENDENT_MIN_S`, `GATE_INDEPENDENT_MIN_S_NOVICE`, `GATE_RUNG_DWELL_MIN_S`, `LOOP_RAG_K_TEACH_SOFT`, `LOOP_SOURCE_CHUNKS_MAX`, and listing each *new name*, each *spec-new* and each *added by PKG-06* separately. Fill "Open questions for the series owner" with at least: (a) exam mode wins over the shown-work floor (spec lists both without precedence); (b) a non-attempt phrase vetoes an attempt even when work is shown; (c) a same-session re-check still counts toward `streak_unassisted`; (d) `STOP_PRACTICE` needs two *full* windows, so it cannot fire before `BAND_WINDOW × BAND_CONTROL_STOP_WINDOWS` first attempts; (e) `save_loop_state` cannot create the lazy `sessions` row without `session_row` (NOT NULL `user_id`/`mode`/`topic`); (f) `ever_streak3` needs a max-streak the `learner_state` table does not store — PKG-07 derives it from `node_mastery_events` or PKG-14 adds a column; (g) `final_answer` takes the clause after the LAST `=`, so a multi-part reference (`x = 7 and y = 3`) is covered only by the n-gram rule; (h) "proficient-band verification" (`LOOP_MODEL_TIER` lite row) is read as a `hint` turn at H0 in the proficient band †; (i) model turns the table does not name — `hint` at H2 with no leak-clean payload, `hint` at H0 outside the proficient band — default to `standard` †; (j) `context_policy` at the `hard` level returns the soft policy (no model runs at hard, so this only matters if a caller ignores `model_tier`); (k) the H4 payload is the sibling's prompt and reference joined by a blank line, with no framing text †; (l) `LoopState.from_json` ignores unknown top-level keys and `to_json` does not re-emit them, so a later package that stores a top-level key in `loop_state` (`revealed` A23, `tutor_requests`/`deep_requests` §3.5, `probe`/`plan`/`sr`/`review`) must add it as a `LoopState` field or the next save drops it. Record under "Known gaps": no caller yet; the leak detector's eval fixtures (`tests/evals/loop_tutor.py`) are PKG-07's; `services/decisions.judge_leak` stays unwired; `zpd.step.variant` (A8) is PKG-14's; `seen_hashes`/`revealed_hashes` (A23) and `rag_service.chunks_for_ids` are PKG-07's; no tier is routable until it passes PKG-07's per-tier evals (A15).

- [ ] **Step 2:** Ledger: add row `| 06 | zpd-policy | done | feat/learning-loop-06-zpd-policy | <sha> | N tests (test_learning_zpd_policy.py) + inv_04/05, inv_02 extended | — | HANDOFF-06.md |`; add the `03 | … | verified | …` and `04 | … | verified | …` rows you earned in State of the world if not already added. Deviations: one line per *new name* constant (`PKG-06: spec states 0.90/2/2/2/6/0.50/2 unnamed → named BAND_CONTROL_HI/BAND_CONTROL_STOP_WINDOWS/CEILING_PROFIC_ESCALATE_FAILS/CEILING_DEVELOP_H6_FAILS/WHEELSPIN_OPPS_EARLY/WHEELSPIN_UNASSISTED_MAX/LOOP_TIER_DEEP_MIN_FAILS → no numeral in loop code`), one per param added on PKG-01's behalf, if any, and one per `ItemLike` field spelled differently from this prompt, if any.

- [ ] **Step 3: Commit**

```
git add docs/superpowers/plans/learning-loop/HANDOFF-06.md docs/superpowers/plans/learning-loop/LEDGER.md
git commit -m "docs(learning-loop): PKG-06 — hand-off and ledger

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 9: PR

- [ ] **Step 1:** Run the self-check loop once more (below), then:

```
gh pr create --title "feat(learning): PKG-06 zpd-policy" --body-file - <<'EOF'
Learning loop series, package 8 of 17. Spec: docs/superpowers/specs/2026-09-26-learning-loop-design.md §3.3, §3.4, §3.5 (LOOP_MODEL_TIER), §4, §6, §8 (2, 4, 5), §13 A15/A17/A18/A24.

- learning/ladder.py: Rung H0..H6 with per-rung tutor intent; check_pose (template check pose) and deterministic_content (H2 passages / H4 isomorph sibling / H6 reference; passages passed in, caller leak-checks)
- learning/policy.py (pure, typed): StepState / LearnerView / LoopState, ceiling table, evidence-by-rung mapping, band control, wheel-spin; model_tier (LOOP_MODEL_TIER, lite/standard/deep/none) and context_policy (RAG k, graph block, source chunks, catalog, tool_choice by phase)
- learning/gates.py: NON_ATTEMPT_PATTERNS, genuine-attempt / rung-dwell / H6 / offer gates
- learning/leak.py: deterministic n-gram + final-answer leak detector and stripper
- sessions.loop_state jsonb migration + learning/loop_state_store.py (lazy-session aware)
- zpd.step / offer / band_adjust / wheelspin / leak / rating in EVENT_TAXONOMY + typed emit helpers; zpd.step carries tier and grader_backend when known
- invariants 4 and 5 asserted (4 covers model_tier/context_policy; 5 scans zpd/learn/review/ai/decision); invariant 2 extended (passages as an argument)

Nothing calls the layer yet (a test proves it); flag-off behaviour is byte-identical. † engineering constants: GATE_INDEPENDENT_MIN_S, GATE_INDEPENDENT_MIN_S_NOVICE, GATE_RUNG_DWELL_MIN_S, LOOP_RAG_K_TEACH_SOFT, LOOP_SOURCE_CHUNKS_MAX.

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
- Dependency suites unchanged and green: `tests/test_learning_bkt.py`, `tests/test_learning_fsrs.py` (PKG-01/02 — proves no `params.py` value moved), `tests/test_learning_evidence_apply.py`, `tests/test_graph_service.py` (PKG-03), `tests/test_learning_check_items.py` (PKG-04), `tests/test_learning_check_tool.py` (PKG-05), `tests/test_learning_decisions.py` (PKG-05b), `tests/test_learning_gate.py`, `tests/test_learning_deps.py` (PKG-00).
- Pre-series suites this package touches, unchanged except the six pinned strings: `tests/test_event_capture_seams.py`, `tests/test_events_service.py`; untouched and green: `tests/test_learn_routes.py`, `tests/test_learn_stream_routes.py` (sessions), `tests/test_model_mode_seam.py`.
- With `LEARNING_LOOP_ENABLED` unset or set: no route behaviour changes (nothing imports the new modules — `test_zpd_layer_is_inert_nothing_imports_it`).

## Acceptance criteria (the next session pastes these)

1. `cd backend && venv/bin/python -m pytest tests/test_learning_zpd_policy.py -q` → `N passed (N ≥ 35)`
2. `grep -cE "^def (ceiling|band_control|evidence_for_rung|wheelspin|model_tier|context_policy)\(" backend/learning/policy.py` → `6`
3. `grep -cE "^def (check_pose|deterministic_content)\(" backend/learning/ladder.py` → `2`
4. `grep -c '"zpd\.' backend/services/events_service.py` → `6`
5. `ls backend/db/migrations/*_learning_session_loop_state.sql` → `1 file`
6. `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_02 or inv_04 or inv_05"` → `3 passed`
7. `cd backend && venv/bin/python -m pytest tests/ -q` → zero failures; `venv/bin/ruff check .` → `All checks passed!`
8. `grep -rnE "^\s*(from|import)\s+learning\.(policy|gates|leak|ladder|loop_state_store|zpd_events)\b" backend --include='*.py' | grep -v "^backend/tests/\|^backend/learning/"` → no output
9. `git diff --stat main...HEAD` lists only: `backend/learning/{params,ladder,policy,gates,leak,loop_state_store,zpd_events}.py`, `backend/services/events_service.py`, `backend/db/migrations/*_learning_session_loop_state.sql`, `backend/tests/{test_learning_zpd_policy,test_learning_loop_invariants,test_event_capture_seams}.py`, `docs/superpowers/plans/learning-loop/{HANDOFF-06.md,LEDGER.md}`.
10. `LEDGER.md` has row `06 | zpd-policy | done | …` and `03 | … | verified` and `04 | … | verified` rows.

## Hand-off

`docs/superpowers/plans/learning-loop/HANDOFF-06.md` per the template; the Verify commands block is fixed above (Task 8). Symbols to list: every public name in `ladder.py` (incl. `check_pose`, `deterministic_content`, `ItemLike`, `DeterministicPayload`), `policy.py` (incl. `model_tier`, `context_policy`, `ContextPolicy`, `Tier`, `TurnPhase`, `ContextPhase`, `BudgetLevel`), `gates.py`, `leak.py`, `loop_state_store.py`, `zpd_events.py` (incl. the `tier`/`grader_backend` keywords on `emit_zpd_step`); the column `sessions.loop_state`; the six event types. Constants: the full §Named constants table with `†`, the spec-new and the new-name rows. Deviations, Known gaps, Open questions: as Task 8 lists them.

## Do not

- Do not call any of this from a route, agent, tool, or `services/chat_stream.py`. Do not mount `routes/learn_loop.py`. Do not touch `agents/`, `routes/`, `services/graph_service.py`, `learning/learner_state.py`, `learning/evidence.py`, `learning/bkt.py`, `learning/fsrs.py`.
- `policy.py`: no `str` parameter on any public function, no `import re`, no import of `gates` (invariant 4); `model_tier`/`context_policy` take `Literal`/enum/`bool`/`int` only and never read budgets, `llm_usage`, `model_pref` or config. The pure modules (`ladder`, `policy`, `gates`, `leak`) import only stdlib and `learning.*` (invariant 2): `ladder.py` never imports `learning.checks`, `services/*` or `rag_service` — items are an `ItemLike` Protocol and passages are strings passed in. Only `loop_state_store.py` touches `db.connection.table` (invariant 7); no `httpx`, no `supabase` import.
- No numeral in loop code other than `0`/`1`/`0.0`/`1.0` and `Rung` member values; every threshold is a `params.NAME`. Never change a PKG-01 value; add names only.
- Migration: UTC-timestamp prefix, `_learning_` infix, spec §4 DDL verbatim, append-only, never edited after creation. `loop_state` is jsonb and unencrypted because it holds ids/numbers/bools only — never put text in it.
- Do not add a seventh event, do not put `"zpd.` in quotes anywhere in `events_service.py` other than the six taxonomy entries, do not make `log_event` enforce membership. Do not add `ai.budget_capped` (PKG-06b) or any `decision.*` (PKG-05b) to the taxonomy. Do not zero or blank `tier`/`grader_backend` when unknown — omit them. Do not wire `services/decisions.judge_leak` or call `ai_budget`. No `lru_cache`. No LLM anywhere under `backend/learning/` (spec §12).
- Do not skip, xfail, or delete any pre-existing test. Do not hand-edit eval cassettes or baselines.
- Logscan `ALLOWLIST` in `backend/e2e_oracles/logscan.py` stays `()`.
- End every commit with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; end the PR body with the Claude Code attribution line.

## If you get stuck

1. Re-read §Spec and the spec file's §3.3 / §6 / §8 before guessing; the ZPD report's policy block is the tie-breaker for wording, the spec for numbers.
2. Three failed iterations on one task → append a `BLOCKED` row to `LEDGER.md` (hypothesis, commands run, outputs), commit what is green, open the PR as draft, stop.
3. Never widen scope to unblock. Never disable a test to unblock. If a leak fixture and the detector disagree, fix the detector's rule and keep the fixture unless the fixture contradicts §Behaviour 8.
4. Ambiguity → choose the option closest to the spec, mark it `†` in the hand-off, continue.
