# HANDOFF-01 — bkt-core

Written by the session that executed `PKG-01-bkt-core.md`. Read by every later package that depends on 01. Keep every heading, even if the answer is "none".

## What changed

`backend/learning/params.py` now holds every named constant of spec §3.1–§3.4 (76 module-level `NAME = value` lines plus the annotated `CHANNELS` dict), under the spec's names, and imports only the standard library. It defines `validate_channels(channels, t)` and calls it on `CHANNELS`/`BKT_T` at import, so an invalid channel row fails the first import. `backend/learning/bkt.py` is the pure BKT core. It covers the van de Sande update with a per-channel guess/slip pair, the `idk=True` flag (the channel's G with `S_IDK`), and weighted interpolation with the learn step only at full weight. It also has decay-at-read toward `BKT_L0` on the FSRS-6 curve, one-hop asymmetric propagation, and the `band`/`tier_for`/`is_proficient`/`is_mastered` cuts. `bkt.py` imports only `typing` and `learning.params`. `tests/test_learning_bkt.py` (153 tests) pins the hand-computed posteriors: 0.30 → 0.854 / 0.825 / 0.666 / 0.642 / 0.575, 0.90 → 0.570 → 0.257 through `update`, and the observation-only chain 0.90 → 0.495 → 0.096. It also pins the decay values (0.845, 0.717, 0.183). Invariant 3 is now asserted directly over the raw `CHANNELS` table. Nothing outside `backend/learning/` and `backend/tests/` imports either module, so flag-off behaviour is byte-identical. No migration, event, route, agent or frontend change.

## Symbols added

- `backend/learning/params.py::validate_channels(channels: Mapping[str, Mapping[str, float | bool]], t: float) -> None`. It raises `ValueError` naming the channel and the inequality it breaks: `t <= 0` (message names `BKT_T`), `G <= 0` or `S <= 0`, `G + S >= 1`, `G > BKT_G_MAX`, `S > BKT_S_MAX`, or `t >= 1 − S/(1−G)` (message names `BKT_T`). It is called at import as `validate_channels(CHANNELS, BKT_T)`.
- `backend/learning/params.py::CHANNELS: dict[str, dict[str, float | bool]]` — keys `free_response`, `mc_reasoned`, `mc`, `teachback_llm`, `chat_turn`; each value is exactly `{"G": float, "S": float, "strong": bool}`. There is no `idk` row.
- `backend/learning/params.py` constant names (values per spec §3; name list only):
  - §3.1: `BKT_L0`, `BKT_T`, `BKT_G_MAX`, `BKT_S_MAX`, `BKT_PROFICIENT`, `BKT_MASTERED`, `BKT_MASTERED_MIN_STRONG`, `BAND_NOVICE_MAX`, `BAND_DEVELOP_MAX`, `TIER_UNEXPLORED_MAX`, `WEIGHT_ASSISTED`, `WEIGHT_SAME_SESSION_RECHECK`, `WEIGHT_PROPAGATION`, `WEIGHT_LOW_CONFIDENCE`, `S_IDK`, `CHANNELS`, `STRONG_CHANNELS`, `PROPAGATION_CHANNEL`, `EDGE_PREREQ_SOURCE_IS_PREREQ`.
  - §3.2: `FSRS_W` (a 21-tuple), `FSRS_RETENTION_DEFAULT`, `FSRS_RETENTION_LARGE_SET`, `FSRS_LARGE_SET_CONCEPTS`, `FSRS_RETENTION_EXAM`, `FSRS_EXAM_WINDOW_DAYS`, `FSRS_S0_GOOD` (`= FSRS_W[2]`), `REVIEW_ORDER_THRESHOLD`, `REVIEW_DAILY_BUDGET_MIN`, `REVIEW_SECONDS_PER_CHECK`, `MC_STABILITY_GAIN_CAP`, `SR_INITIAL_CRITERION`, `SR_RELEARN_SESSIONS`.
  - §3.3: `GATE_INDEPENDENT_MIN_S`, `GATE_INDEPENDENT_MIN_S_NOVICE`, `GATE_RUNG_DWELL_MIN_S`, `H6_MIN_GENUINE_ATTEMPTS`, `OFFER_BANDS`, `BAND_WINDOW`, `PROBE_TARGET_LO`, `PROBE_TARGET_HI`, `ACQ_TARGET_LO`, `ACQ_TARGET_HI`, `PRACTICE_TARGET_LO`, `PRACTICE_TARGET_HI`, `EXAM_TARGET_LO`, `EXAM_TARGET_HI`, `PI_LO`, `PI_HI`, `PI_MIN_ROOM`, `WHEELSPIN_OPPS`, `MISCONCEPTION_CONFIDENCE`, `NOVICE_FLOOR_MISSES`.
  - §3.4: `PROBE_ITEMS_PER_SKILL_MIN`, `PROBE_ITEMS_PER_SKILL_MAX`, `PROBE_SESSION_CAP`, `PROBE_STOP_DELTA`, `PLAN_MAX_CONCEPTS`, `PLAN_MAX_COUPLED`, `PLAN_ORDER`, `STEP_MAX_SENTENCES`, `STEP_QUESTIONS_PER_TURN`, `LOOP_HISTORY_MAX_MESSAGES`, `LEARNER_BRIEF_MAX_CHARS`, `LEARNER_BRIEF_LAST_CLOSES`, `LEARNER_BRIEF_TOP_STATES`, `LEARNER_BRIEF_MAX_MISCONCEPTIONS`, `LOOP_LIMITS`, `GRADER_LIMITS`, `GRADER_LOW_CONFIDENCE`, `GRADER_RETRY_BELOW`, `LEAK_NGRAM`, `CHECK_ITEM_FORMATS`, `CHECK_ITEM_DIFFICULTIES`, `CHECK_ITEM_MIN_RUBRIC`, `CHECK_ITEM_MIN_WRONG`, `MISCONCEPTION_ROLLUP_MIN_USERS`, `ZPD_RATING_EVERY_N_CHECKS`.
- `backend/learning/bkt.py::update(p: float, channel: str, correct: bool, *, weight: float = 1.0, idk: bool = False) -> float`. `weight` and `idk` are KEYWORD-ONLY. The update is the observation posterior from the channel's G/S, then `P' = P + weight·(P_post − P)`, then the learn step `P' + (1 − P')·BKT_T` only when `weight == 1.0`. `idk=True` ignores `correct`: the observation is incorrect with the channel's G and `S_IDK`. It raises `ValueError` for a `channel` not in `CHANNELS` (including `"idk"`) and for `p` or `weight` outside `[0, 1]`. The result is clamped to `[0, 1]`. `weight=0.0` returns `p` unchanged, so no caller-side guard is needed.
- `backend/learning/bkt.py::decayed_p(p_stored: float, days_since: float, stability: float | None) -> float`. It returns `BKT_L0 + (p_stored − BKT_L0)·R(days_since, S)`. `stability=None` means `FSRS_S0_GOOD`, and `stability <= 0` raises `ValueError`. A negative `days_since` is clamped to 0, and `days_since == 0` returns `p_stored` exactly. The positional order is `(p, days, stability)`.
- `backend/learning/bkt.py::propagate_prereq(evidence_correct: bool, parents: list[str], children: list[str]) -> list[Propagation]`. When correct it returns `[(parent_id, PROPAGATION_CHANNEL, True, WEIGHT_PROPAGATION), …]`; when incorrect, `[(child_id, PROPAGATION_CHANNEL, False, WEIGHT_PROPAGATION), …]`. Order is preserved, there is no dedup, and empty input gives `[]`. It takes node-id lists, not edges: the caller resolves parents and children from `graph_edges` with `EDGE_PREREQ_SOURCE_IS_PREREQ`.
- `backend/learning/bkt.py::band(p: float) -> Band` — `p < BAND_NOVICE_MAX` → `"novice"`, `p < BAND_DEVELOP_MAX` → `"develop"`, else `"profic"`.
- `backend/learning/bkt.py::tier_for(p: float) -> Tier` — `< TIER_UNEXPLORED_MAX` → `"unexplored"`, `< BAND_NOVICE_MAX` → `"struggling"`, `< BKT_PROFICIENT` → `"learning"`, else `"mastered"` (only `graph_nodes.mastery_tier` CHECK values). It does not replace `config.get_mastery_tier`.
- `backend/learning/bkt.py::is_proficient(p: float) -> bool` — `p >= BKT_PROFICIENT`.
- `backend/learning/bkt.py::is_mastered(p: float, n_strong_unassisted: int) -> bool` — `p >= BKT_MASTERED and n_strong_unassisted >= BKT_MASTERED_MIN_STRONG`.
- `backend/learning/bkt.py::_posterior(p, g, s, correct) -> float` (private) — the observation-only Bayes step. When the denominator is 0 it returns `p`.
- `backend/learning/bkt.py::_retrievability(t, s) -> float` (private) — the spec §3.2 `R(t, S) = (1 + factor·t/S)^(−w20)` from `FSRS_W`; `R(S, S) = 0.9`.
- `backend/learning/bkt.py::Band = Literal["novice", "develop", "profic"]`, `::Tier = Literal["unexplored", "struggling", "learning", "mastered"]`, `::Propagation = tuple[str, str, bool, float]` (node_id, channel, correct, weight).
- Test: `backend/tests/test_learning_bkt.py` (153). `backend/tests/test_learning_loop_invariants.py::test_inv_03_channel_guess_slip_bounds` is now real (invariants `5 passed, 7 skipped`).

## Constants chosen

- `GATE_INDEPENDENT_MIN_S = 45` † (spec §3.3)
- `GATE_INDEPENDENT_MIN_S_NOVICE = 90` † (spec §3.3)
- `GATE_RUNG_DWELL_MIN_S = 8` † (spec §3.3)
- `STRONG_CHANNELS = frozenset({"free_response", "mc_reasoned"})` ‡ — derived at import from the `strong` column of the spec §3.1 channel table.
- `PROPAGATION_CHANNEL = "chat_turn"` ‡ — spec §3.1 propagation's "chat_turn-strength observation".
- `LOOP_LIMITS = {"request_limit": 14, "tool_calls_limit": 14, "total_tokens_limit": 120_000}` ‡ — spec §3.4 values; the plain-dict shape is PKG-01's choice so `params.py` never imports `pydantic_ai`.
- `GRADER_LIMITS = {"request_limit": 2, "tool_calls_limit": 0, "total_tokens_limit": 20_000}` ‡ — spec §3.4; same shape.
- `GRADER_RETRY_BELOW = 0.4` ‡ — spec §3.4 `GRADER_LOW_CONFIDENCE` row, "below 0.4 → route to a second grader call". §13 A6 separately names `GRADER_SECOND_OPINION_CONFIDENCE = 0.4` for its owning package, so the same threshold may end up under two names (see Known gaps).

## Deviations from spec

- Branch cut from `main` → `feat/learning-loop-01-bkt-core` cut from `feat/learning-loop-00-foundation` HEAD `3d1c7db` → session override: the series runs on stacked branches (the PKG-00 ledger line). PRs are opened after review.
- Task 7 `git push` / `gh pr create` → not run → session override: no push, no PR in this run. The last step is the hand-off + ledger commit.
- Commit trailer `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` → every commit ends `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` → session override.
- State-of-the-world row "PKG-00 gate → `11 passed`" → observed `13 passed` → this is PKG-00's recorded arithmetic-slip deviation (the prompt's own tests collect 13), not a red row. The `00 | verified` ledger row records 13.
- Full suite `pytest tests/ -q` (and SoW `-q -x`) → run as `venv/bin/python -m pytest tests/ -q -p no:cacheprovider --ignore=tests/evals --ignore=tests/test_docling_integration.py --ignore=tests/test_ocr_pipeline.py --ignore=tests/test_extraction_backends.py` → the OCR stack is not installed on the executing machine (session override; this is CI's own ignore set). Base N₀ at `3d1c7db` was `2748 passed, 143 skipped`. After PKG-01 it is `2902 passed, 142 skipped`: the 153 `test_learning_bkt.py` tests plus inv_03 moving from skipped to passed, with zero failures and no new skips.
- Acceptance 8 / self-check 6 `git diff --stat main...HEAD` → measured as `git diff --stat feat/learning-loop-00-foundation..HEAD` → against `main`, the stacked run also shows the planning base and PKG-00. Against the PKG-00 head, the only changed paths are the six this prompt lists.

No value in `params.py` differs from the prompt's Named-constants table or from spec §3.

## Known gaps

- (a) `bkt._retrievability` duplicates spec §3.2 `R`, which PKG-02 also implements as `learning.fsrs.retrievability`. Once both are on main, PKG-03 may dedupe by pointing `_retrievability` at `fsrs`; the private name stays, so `decayed_p` does not change. `bkt.py` must not import `learning.fsrs` before then.
- (b) The band-control cut-points are unnamed in the spec and are not in `params.py`: spec §3.3 `unassisted_next > 0.90`, `< 0.65`, "2 windows", and the wheelspin `opps ≥ 6` / `unassisted_next < 0.50` arm. PKG-06 names them; do not assume they exist.
- (c) `bkt.update` takes `idk=True` on the item's channel and refuses `"idk"` as a channel. §13 A1 already removed `"idk"` from the `Evidence.channel` Literal, so PKG-03 passes `channel=<item channel>, idk=ev.idk` straight through; no mapping is needed unless a caller still produces `channel == "idk"`.
- (d) `tier_for` exists, but nothing writes it to `graph_nodes` until PKG-03. `config.get_mastery_tier` / `MASTERY_*_MIN` (0.1/0.45/0.75) remain the flag-off tiers until PKG-14; `test_tier_for_is_not_the_legacy_tier` pins that the two differ at 0.80.
- (e) `LOOP_LIMITS`/`GRADER_LIMITS` are plain dicts; PKG-05/07 build `UsageLimits(**…)` in `agents/`.
- (f) PKG-03's "Interfaces consumed (ASSUMED)" table does not match what shipped. The hand-off wins, so PKG-03 adapts only its named adapters. `update`'s `weight` is keyword-only and `idk` exists. `decayed_p`'s third argument accepts `None`. `propagate_prereq` is `(evidence_correct, parents, children) -> list[(node_id, channel, correct, weight)]`, not `(node_id, correct, edges) -> list[(target, correct)]`, so `_propagation_targets` must split the edges into parents/children itself using `EDGE_PREREQ_SOURCE_IS_PREREQ`.
- (g) §13 A6's constants are NOT in `params.py`: A6 says each package adds its own. §13 A5's `params.gate_seconds(name)` is not there either. A5 scales by `config.LEARNING_GATE_TIME_SCALE`, but `params.py` must not import `config`: `test_params_imports_only_stdlib` forbids it, and so does this prompt's "Do not" list. So PKG-06 must take the scale another way (pass it in, or put the scaling in `gates.py`) and record the choice. PKG-03 plans to add `EVIDENCE_NO_UPWARD_MIN_RUNG` / `LADDER_MAX_RUNG`. A6 also names `LADDER_MAX_RUNG = 6`, so the first package to add it owns it, and the next must reuse it, not redefine it.
- (h) Only `update` range-checks `p`. `decayed_p`, `band`, `tier_for`, `is_proficient` and `is_mastered` accept any float, as the prompt's task code does. Behaviour 3 lists `decayed_p`'s errors exhaustively as `stability <= 0`, and its output is clamped to `[0, 1]` when `days_since > 0`. The generic §Error semantics line ("raise on out-of-range `p`") is broader than that code; see Open questions.
- needs local Supabase stack (supabase start): nothing in this package. There is no migration, table, route or request path; self-check item 5 skips the E2E cycle by design, and no supabase CLI / podman / docker is present on the executing machine anyway.
- Evals: not run. No prompt or tool description changed (self-check item 4).
- Flakes observed: none.

## Verify commands

```
cd backend && venv/bin/python -m pytest tests/test_learning_bkt.py -q                           → N passed (N ≥ 20)
grep -cE "^def (update|decayed_p|propagate_prereq|band|tier_for)\(" backend/learning/bkt.py    → 5
grep -cE "^[A-Z0-9_]+ = " backend/learning/params.py                                            → ≥ 40
cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k inv_03    → 1 passed
```

(Observed at hand-off: `153 passed`, `5`, `76`, `1 passed`.)

## Open questions for the series owner

- (1) Which channel's `G` should an explicit "I don't know" use when the check item's format is unknown? Option taken: none. `update` refuses `"idk"` as a channel, and §13 A1 makes `Evidence.channel` always the item's channel, so the caller must name the channel explicitly (PKG-03/05).
- (2) Does `EDGE_PREREQ_SOURCE_IS_PREREQ = True` (source = prerequisite, target = dependent) match live `graph_edges` data? PKG-08 verifies and may flip it. `propagate_prereq` is direction-agnostic by design: it receives already-resolved parent and child id lists.
- (3) Should `decayed_p`/`band`/`tier_for`/`is_*` raise on `p` outside `[0, 1]`, as the generic §Error semantics line suggests? Option taken: no, following the task code and Behaviour 3. `learner_state` values come only from `update`, which is range-checked and clamped. If the owner wants it, the check is one line per function plus a test, done as a PKG-01 reopen.

## Post-hoc changes

(Appended by later packages that modified this package's code. Format: `PKG-MM <date>: <what> — commit <sha>`.)
