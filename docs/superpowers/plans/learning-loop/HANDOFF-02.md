# HANDOFF-02 — fsrs-core

Written by the session that executed `PKG-02-fsrs-core.md`. Read by every later package that depends on 02. Keep every heading, even if the answer is "none".

## What changed

`backend/learning/fsrs.py` is now a pure FSRS-6 scheduler. It implements the spec §3.2 equations over `params.FSRS_W` (the forgetting curve `retrievability`, its inverse `interval`, the first-rating `S0`/`D0`, and `next_state`: difficulty update with mean reversion, `S_recall`, `S_lapse`, `S_same_day`, and the unassisted-MC stability cap), plus the four FSRS-6 reference guards the spec's transcription omits (a same-day pass never lowers S, a lapse never raises it, mean reversion targets the unclamped `D0(4)`, and every new S is floored at `FSRS_STABILITY_MIN = 0.001` d), so `next_state` matches py-fsrs 6.3.2, whose default weights equal `FSRS_W`, to 4e-15 at every S (review fixes; Deviations, Open question 4). It also holds the spec's check→rating map (`rating_for`, with `idk` as a keyword flag per §13 A1), the retention-target rules (`retention_target`, exam window over large set per §13 A7), DASH due ordering by `|R − REVIEW_ORDER_THRESHOLD|` (`order_due`, over rows whose timestamps may be datetimes or PostgREST ISO strings), the daily review budget (`budget_items`/`budget_select`), and the Rawson & Dunlosky successive-relearning state machine (`SuccessiveRelearning`, immutable and JSON round-trippable). Every public function raises `ValueError` on out-of-domain input, NaN and ±inf included (a rung, count or day count must also be a whole number ≥ 0), and nothing logs, swallows or degrades. `fsrs.py` imports only the standard library and `learning.params`, which the new `test_inv_13_fsrs_weights_pinned` asserts along with the 21 pinned weights. `params.RUNG_ASSISTED_MAX = 3` (§13 A6) and `params.FSRS_STABILITY_MIN = 0.001` now exist; each was added as a PKG-01 reopen. Nothing outside `backend/learning/` and `backend/tests/` imports `learning.fsrs`, so flag-off behaviour is byte-identical. There is no migration, event, route, agent or frontend change.

## Symbols added

- `backend/learning/fsrs.py::FACTOR` — `0.9^(−1/w20) − 1` (≈ 0.9803), computed once at import.
- `backend/learning/fsrs.py::W` — alias of `params.FSRS_W` (the formulas read `W[i]`).
- `backend/learning/fsrs.py::Rating` — `IntEnum`: `AGAIN=1, HARD=2, GOOD=3, EASY=4` (the FSRS grade indices).
- `backend/learning/fsrs.py::RATING_CHANNELS` — `frozenset(params.CHANNELS)`: `free_response`, `mc_reasoned`, `mc`, `teachback_llm`, `chat_turn`. There is no `idk` member (§13 A1).
- `backend/learning/fsrs.py::STRONG_GOOD_CHANNELS` — `frozenset({"free_response", "teachback_llm", "mc_reasoned"})`: the channels whose unassisted correct is a plain Good.
- `backend/learning/fsrs.py::retrievability(days: float, stability: float) -> float` — `(1 + FACTOR·t/S)^(−w20)`. `R(0, S) = 1` and `R(S, S) = 0.9`. It raises on `days < 0` or NaN, and on a stability that is not finite and > 0. `days = +inf` gives 0.0, the limit.
- `backend/learning/fsrs.py::interval(retention: float, stability: float) -> float` — days until R falls to `retention`, with `interval(0.9, S) == S`. It raises on `retention ∉ (0, 1]` (NaN included) and on a stability that is not finite and > 0.
- `backend/learning/fsrs.py::retention_target(n_scheduled: int, exam_within_days: int | None = None) -> float` — `exam_within_days is not None and ≤ FSRS_EXAM_WINDOW_DAYS` gives `FSRS_RETENTION_EXAM`; else `n_scheduled > FSRS_LARGE_SET_CONCEPTS` gives `FSRS_RETENTION_LARGE_SET`; else `FSRS_RETENTION_DEFAULT`. Both arguments are whole counts ≥ 0 (`exam_within_days` is `exam_proximity.days_until_next_exam`, 0 = today); a negative, NaN, ±inf, non-integer (`2.5`) or string value raises.
- `backend/learning/fsrs.py::initial_stability(rating) -> float` — `S0(G) = W[G−1]`.
- `backend/learning/fsrs.py::initial_difficulty(rating) -> float` — `D0(G) = clamp(w4 − e^(w5·(G−1)) + 1, 1, 10)`; the first rating's D0 is always clamped.
- `backend/learning/fsrs.py::next_state(d, s, rating, days_since, *, same_day=False, mc_unassisted=False) -> tuple[float, float]` — returns `(D', S')` and nothing else (it does not schedule). If `d is None or s is None`, it returns `(D0(G), S0(G))`; this is the first rating, and the MC cap never applies to it. Otherwise:
  - `R = retrievability(days_since, s)`, and the difficulty update runs for every non-first rating. It mean-reverts toward the UNCLAMPED `D0(4) = −4.7716` (FSRS-6), then clamps to `[1, 10]`.
  - `same_day` selects `S_same_day`, whose increase `e^(w17·(G−3+w18))·S^(−w19)` is floored at 1 for Hard/Good/Easy, so a same-day pass never lowers S (Again is not floored). Otherwise Again selects `S_lapse`, capped at `S / e^(w17·w18)`, so a lapse lands below S unless the floor binds (S ≤ ≈0.00105 d); Hard/Good/Easy select `S_recall`. Each uses the pre-update D.
  - `mc_unassisted` sets `S' = min(S', S·MC_STABILITY_GAIN_CAP)`.
  - Last, `S' = max(S', FSRS_STABILITY_MIN)` (FSRS-6 `STABILITY_MIN`), so `S' ≥ 0.001` d on every path. py-fsrs floors inside each stability function and has no MC cap; the two orders agree whenever `S ≥ FSRS_STABILITY_MIN / 2`, which every S that `next_state` produces satisfies.
  - It raises on a rating that is not an integer in 1..4 (so `2.5` and `"3"` raise), on `d` outside `[1, 10]` or NaN, on a stability that is not finite and > 0, and on `days_since < 0` or NaN.
- `backend/learning/fsrs.py::rating_for(channel: str, correct: bool, max_rung: int, *, idk: bool = False) -> int` — the spec §3.2 map:
  - `idk` or `not correct` → 1 (Again).
  - `max_rung == 0` → 3 (Good) on `free_response`/`teachback_llm`/`mc_reasoned`/`mc`, and 2 (Hard) on `chat_turn` †.
  - `1 ≤ max_rung ≤ RUNG_ASSISTED_MAX` → 2 (Hard).
  - `max_rung > RUNG_ASSISTED_MAX` → 1 (Again).
  - It never returns 4. It raises on a channel not in `RATING_CHANNELS` (including `"idk"`) and on a `max_rung` that is not a whole number ≥ 0 (negative, NaN, ±inf, `2.5`, `"0"`, `None`).
- `backend/learning/fsrs.py::mc_cap_applies(channel, correct, max_rung, *, idk=False) -> bool` — `channel == "mc" and correct and not idk and max_rung == 0`. It is exactly "mc rated Good", and it is the one place PKG-03 gets `next_state(..., mc_unassisted=...)` from. It raises on exactly the inputs `rating_for` raises on (shared `_check_rating_inputs`).
- `backend/learning/fsrs.py::item_retrievability(item, now, *, stability_key="fsrs_s", last_review_key="fsrs_last_review_at") -> float` — R now for one row (a mapping).
  - `now` and the stored timestamp may be datetimes or ISO-8601 strings (a `Z` suffix is accepted); a naive value is treated as UTC.
  - A row missing either key, or holding `None`, has R = 1.0.
  - A last review later than `now` counts as 0 elapsed days.
  - A corrupt stability (≤ 0, NaN) or an unparseable timestamp raises `ValueError`.
- `backend/learning/fsrs.py::order_due(items, now, *, stability_key=…, last_review_key=…) -> list` — a new list, stable-sorted by `|R − REVIEW_ORDER_THRESHOLD|` ascending. The input is untouched, ties keep input order, and never-reviewed rows (R = 1.0) sort last.
- `backend/learning/fsrs.py::budget_items(budget_min=REVIEW_DAILY_BUDGET_MIN, seconds_per=REVIEW_SECONDS_PER_CHECK) -> int` — `int(budget_min·60 // seconds_per)`, which is 16 at the defaults. It returns 0 for a budget ≤ 0, and raises on `seconds_per` that is not finite and > 0 and on a non-finite `budget_min`.
- `backend/learning/fsrs.py::budget_select(items, budget_min=…, seconds_per=…) -> list` — the first `budget_items(...)` of an already-ordered sequence, never more.
- `backend/learning/fsrs.py::SR_ACQUISITION = "acquisition"`, `::SR_RELEARN = "relearn"`, `::SR_DONE = "done"`.
- `backend/learning/fsrs.py::SuccessiveRelearning` — frozen dataclass `(phase=SR_ACQUISITION, correct_in_acquisition=0, relearn_sessions_done=0, credited_session=None)`. Construction raises on an unknown phase or a counter that is not a whole number ≥ 0 (negative, NaN, ±inf, `1.5`, `"2"`, `None`), and stores each counter as an `int` (a stored `2.0` comes back as `2`).
  - `advance(correct, *, session_id) -> SuccessiveRelearning` returns a new instance.
  - In acquisition, correct recalls count cumulatively and wrong ones are ignored. Reaching `SR_INITIAL_CRITERION` moves to relearn and credits that session.
  - In relearn, only the first correct recall of a session other than `credited_session` counts: it increments `relearn_sessions_done` and credits that session. Reaching `SR_RELEARN_SESSIONS` moves to done.
  - done absorbs every call.
  - Also: the `complete` property, `as_dict()`, and `from_dict(data | None)` (None or `{}` gives a fresh state). `from_dict` passes stored values through uncoerced, so a corrupt stored state raises `ValueError` exactly as construction does (review fix `678c358`; it used to `int()` them first).
- Private in `fsrs.py`: `_next_difficulty(d, g)`, `_raw_initial_difficulty(g)` (unclamped D0), `_stability_recall(d, s, r, g)`, `_stability_lapse(d, s, r)`, `_stability_same_day(s, g)`, `_check_rating`, `_check_difficulty`, `_check_days`, `_check_stability`, `_check_count(name, value)` (whole number ≥ 0), `_check_rating_inputs(channel, max_rung)`, `_clamp_d`, `_as_datetime`. Structural constants: `_DECAY = W[20]`, `_STABILITY_R`, `_D_MIN`/`_D_MAX`, `_SAME_DAY_PASS_SINC_MIN`, `_D_REVERSION_TARGET`, `_SECONDS_PER_DAY`, `_SECONDS_PER_MINUTE`, `_SR_PHASES`.
- `backend/learning/params.py::RUNG_ASSISTED_MAX = 3` — the §13 A6 name for the §3.3 "H1–H3" upper bound. This is a PKG-01 reopen, commit `8708325`. PKG-03 `Evidence.assisted`, PKG-05 and PKG-06 `evidence_for_rung` cite it. The rest of the §3.2 block already existed; PKG-01 added it.
- `backend/learning/params.py::FSRS_STABILITY_MIN = 0.001` — the FSRS-6 floor on every new stability, in days (py-fsrs 6.3.2 `STABILITY_MIN`), §3.2 block. A second PKG-01 reopen, commit `9cf1919` (review fix). Only `fsrs.next_state` reads it; it is not a spec name until the owner rules on Open question (4).
- Tests: `backend/tests/test_learning_fsrs.py` (128; its `_imports_fsrs`, `_calls_gate` and `_route_violates_gate_rule` ast helpers back the route gate guard) and `backend/tests/test_learning_loop_invariants.py::test_inv_13_fsrs_weights_pinned` (invariants are now `6 passed, 7 skipped`).

Consumers, named explicitly:
- PKG-03, inside `apply_graph_update`, calls `next_state(row["fsrs_d"], row["fsrs_s"], rating_for(ev.channel, ev.correct, ev.max_rung, idk=ev.idk), days_since, same_day=<same calendar day as fsrs_last_review_at>, mc_unassisted=mc_cap_applies(ev.channel, ev.correct, ev.max_rung, idk=ev.idk))` and writes `fsrs_due_at = now + interval(retention_target(...), S')`. Passing `same_day=True` for a correct answer is safe: a same-day pass never lowers S.
- The spec §3.1 "Decay at read" uses `retrievability(Δt, S_c)`, with `S_c = FSRS_S0_GOOD` when there is no FSRS state.
- PKG-11 uses `order_due(..., last_review_key="last_reviewed_at")` over flashcards rows.
- PKG-12 composes `order_due` → `budget_select` and persists `SuccessiveRelearning.as_dict()` in `sessions.loop_state`.

## Constants chosen

All values are the spec's. PKG-01 wrote them, and PKG-02 verified each one against the prompt table (every row matched, so no BLOCKED note).

- `FSRS_W = (0.212, 1.2931, 2.3065, 8.2956, 6.4133, 0.8334, 3.0194, 0.001, 1.8722, 0.1666, 0.796, 1.4835, 0.0614, 0.2629, 1.6483, 0.6014, 1.8729, 0.5425, 0.0912, 0.0658, 0.1542)` (spec §3.2)
- `FSRS_RETENTION_DEFAULT = 0.90` (spec §3.2)
- `FSRS_RETENTION_LARGE_SET = 0.85` (spec §3.2)
- `FSRS_LARGE_SET_CONCEPTS = 150` (spec §3.2; strictly greater than → large set)
- `FSRS_RETENTION_EXAM = 0.95` (spec §3.2)
- `FSRS_EXAM_WINDOW_DAYS = 14` (spec §3.2; inclusive)
- `FSRS_S0_GOOD = FSRS_W[2]` = 2.3065 days (spec §3.2)
- `REVIEW_ORDER_THRESHOLD = 0.33` (spec §3.2)
- `REVIEW_DAILY_BUDGET_MIN = 12` (spec §3.2)
- `REVIEW_SECONDS_PER_CHECK = 45` (spec §3.2)
- `MC_STABILITY_GAIN_CAP = 2.0` (spec §3.2)
- `SR_INITIAL_CRITERION = 3` (spec §3.2)
- `SR_RELEARN_SESSIONS = 3` (spec §3.2)
- `RUNG_ASSISTED_MAX = 3` (spec §3.2 rating map / §3.3 evidence mapping "H1–H3"; name from §13 A6)
- `Rating.AGAIN/HARD/GOOD/EASY = 1/2/3/4` (spec §3.2, `G ∈ {1,2,3,4}`; fsrs.py)
- `_STABILITY_R = 0.9` (spec §3.2 `factor`; fsrs.py)
- `_D_MIN, _D_MAX = 1.0, 10.0` (spec §3.2 `clamp(…, 1, 10)`, `(10−D)/9`, `11−D`; fsrs.py)
- `_SAME_DAY_PASS_SINC_MIN = 1.0` (FSRS-6 reference, py-fsrs 6.3.2 `_short_term_stability`; not in the spec §3.2 transcription, see Deviations †; fsrs.py)
- `FSRS_STABILITY_MIN = 0.001` (FSRS-6 reference, py-fsrs 6.3.2 `STABILITY_MIN`; not in the spec §3.2 transcription, see Deviations †; params.py, PKG-01 reopen `9cf1919`)
- `_D_REVERSION_TARGET = _raw_initial_difficulty(4)` = −4.7716 (derived from `FSRS_W`; FSRS-6 reference, py-fsrs 6.3.2 `_next_difficulty` `clamp=False`; Deviations †; fsrs.py). The post-lapse cap `S / e^(w17·w18)` uses existing weights and adds no constant.
- `_SECONDS_PER_DAY = 86_400.0`, `_SECONDS_PER_MINUTE = 60` (unit conversions; fsrs.py)
- `rating_for("chat_turn", True, 0) → HARD` † (spec §3.2 omits `chat_turn`; §13 A7 records Hard)

## Deviations from spec

- Branch cut from `main` → `feat/learning-loop-02-fsrs-core` cut from `feat/learning-loop-01-bkt-core` HEAD `58b8397` → session override: the series runs on stacked branches (the PKG-00 ledger line). PRs are opened after review.
- Task 8 `git push` / `gh pr create` → not run → session override: no push and no PR in this run. The last step is the hand-off + ledger commit.
- Commit trailer `Co-Authored-By: Claude Fable 5.1` → every commit ends `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` → session override.
- State-of-the-world row "PKG-00 gate → `11 passed`" → observed `13 passed` → this is PKG-00's recorded arithmetic-slip deviation, not a red row.
- State-of-the-world row "PKG-00 invariants → `4 passed, 8 skipped`" → observed `5 passed, 7 skipped` → PKG-01 had already made inv_03 real. After PKG-02 the count is `6 passed, 7 skipped`. Acceptance 3's "`6 passed, 6 skipped` if PKG-01 merged first" is off by one: the module has 13 tests (12 spec invariants + inv_13). With 01 and 02 done, 02/03/07/08/11/13 pass and 7 skip.
- State-of-the-world row "fsrs stub is inert" `grep -rl "learning.fsrs\|from learning import fsrs" backend` → "no files" expected, observed `backend/learning/bkt.py` and `backend/tests/test_learning_bkt.py` → both hits are text, not imports: a comment at `bkt.py:98` and the strings and docstrings of PKG-01's import-guard tests. An ast scan of every backend `.py` found no module importing `learning.fsrs`. This is a grep false positive, not a red row; acceptance 8 filters both directories.
- Full suite `pytest tests/ -q` (SoW `-q -x`) → run as `venv/bin/python -m pytest tests/ -q -p no:cacheprovider --ignore=tests/evals --ignore=tests/test_docling_integration.py --ignore=tests/test_ocr_pipeline.py --ignore=tests/test_extraction_backends.py` → the OCR stack is not installed on the executing machine (session override; CI's own ignore set). Base N₀ at `58b8397` is `3036 passed, 142 skipped`. After PKG-02 it is `3126 passed, 142 skipped`: +89 `test_learning_fsrs.py` and +1 inv_13, zero failures, no new skips. After the review fixes (`d50dd25..6d6cb3b`) it is `3157 passed, 142 skipped`: `test_learning_fsrs.py` grows to 120, zero failures, no new skips. After the second review round (`678c358..9c09d95`) it is `3165 passed, 142 skipped`: `test_learning_fsrs.py` grows to 128, zero failures, no new skips.
- Acceptance 9 / self-check 6 `git diff --stat main...HEAD` → measured as `git diff --stat feat/learning-loop-01-bkt-core..HEAD` → stacked run. Against the PKG-01 head the only changed paths are `backend/learning/fsrs.py`, `backend/learning/params.py`, `backend/tests/test_learning_fsrs.py`, `backend/tests/test_learning_loop_invariants.py`, plus `HANDOFF-02.md`, `LEDGER.md`, and `HANDOFF-01.md` (the reopen's Post-hoc line).
- Task 2 "PKG-01 not merged → append the §3.2 block" → PKG-01 landed first. All 13 §3.2 values were verified equal to the prompt table, and only `RUNG_ASSISTED_MAX = 3` was added, as a separate `fix(learning-loop): PKG-01 — …` commit (`8708325`) with ledger row `01 | reopened` and a HANDOFF-01 Post-hoc line → README "Touching an earlier package's code"; §13 A6 says PKG-01 owns `params.py`.
- README "Touching an earlier package's code: a separate FIRST commit" → the reopen `8708325` is the branch's second commit, after Task 1's inv_13 test commit `55abfab` → the prompt orders Task 1 (invariant) before Task 2 (params), and the reopen is still a separate commit that precedes every PKG-02 code commit. History is not rewritten.
- Prompt: `rating_for(channel, correct, max_rung)` accepts channel `"idk"`, and `RATING_CHANNELS` has 6 members including `idk` → `rating_for(channel, correct, max_rung, *, idk=False)`, with `RATING_CHANNELS = frozenset(params.CHANNELS)` (5 members). `rating_for("idk", …)` raises `ValueError`, and `mc_cap_applies` takes the same `idk` keyword → spec §13 A1 (in force over the prompt): `Evidence.channel` is always the item's channel and `idk: bool` is a flag, matching `bkt.update(..., idk=)`. A 6-member set would break PKG-03's "Evidence Literal == RATING_CHANNELS" test.
- Spec §3.2 rating map omits `chat_turn` → an unassisted correct `chat_turn` rates Hard → the channel is the tutor's ungraded judgment (G = S = 0.30) and should not grow stability like a graded check (§13 A7 records it) †.
- Spec §3.2 lists the exam and large-set retention rules without precedence → the exam window wins → it is the shorter-lived, stronger need (§13 A7).
- Spec §3.2 gives one D update rule → it also runs on same-day reviews → the spec has no exception.
- Rows with no FSRS state → R = 1.0 in `order_due`, so they sort last → there is nothing to forget yet. The caller (PKG-12 `due_queue`) decides whether never-reviewed rows are due at all (§13 A7).
- Error semantics listed negative days, non-positive stability, retention outside (0, 1], rating outside 1..4, unknown channel, negative rung, non-positive `seconds_per` → the following also raise `ValueError`: NaN days, NaN/±inf stability, D outside `[1, 10]` or NaN, a non-integer rating (`2.5`, `"3"`), non-finite `budget_min`/`seconds_per`, a `SuccessiveRelearning` with an unknown phase or a counter that is not a whole number ≥ 0, and (review fix `d50dd25`) a `max_rung` that is not a whole number ≥ 0 in `rating_for` and `mc_cap_applies` (which now checks the channel too), and an `n_scheduled`/`exam_within_days` that is not a whole number ≥ 0 in `retention_target`; and (review fix `678c358`) `SuccessiveRelearning.from_dict` no longer `int()`s the stored counters before validating them, which had truncated `2.7` to 2, parsed `"2"`, and raised `TypeError`/`OverflowError` on `None`/`inf` → §Error semantics "every public function raises ValueError on out-of-domain input". Without these checks, a NaN stability flows to a NaN due date, and D ≤ 0 gives `ZeroDivisionError` or a complex number from `D^(−w12)`. PKG-01's review found the same NaN class in `bkt`.
- Task 1 inv_13 as written (a line regex over `from learning…`) → kept verbatim, plus an ast half over `_modules_imported_by` → the regex misses `import learning.bkt`, `from . import bkt`, and function-level imports. Mutation-checked: both shapes fail the ast half and pass the regex half.
- Task 5 `test_routes_import_fsrs_only_behind_the_gate` regex → an ast detector `_imports_fsrs` with its own 8-case test (`test_fsrs_import_detector`), walking `routes/` recursively → the regex missed `from learning import bkt, fsrs` (the shape PKG-03's prompt uses) and parenthesised lists.
- Task 5's gate half `"learning_loop_active" in text` → (review fix `0749775`) an ast `Call` to `learning_loop_active` (bare or attribute) via `_route_violates_gate_rule`, with a 6-case detector test → the substring check passed a route that imported fsrs and named the gate only in a comment, a string or an unused import. The scan stays on `routes/`, and the prompt's Regression-guard "proves no route does" overstates it: pinning "no importer outside `learning/` and `tests/`" in this module would break PKG-03 (`services/graph_service.py`) and PKG-12 (a review service), whose imports are gated upstream, and PKG-03/PKG-11 may not edit this module. Acceptance 8's grep is what pins that state today. The rule is also gate PRESENCE per module, not dominance: a route that calls the gate in one handler and uses fsrs ungated in another, or at import time, passes (second review round `9c09d95` says so in both docstrings; Known gaps).
- Task 5 `test_order_due_sorts_by_distance_from_threshold` asserted `rows == [r for r in rows]`, which is vacuous → it now compares against a `copy.deepcopy` snapshot and asserts a new list is returned.
- Spec §3.2 `S_same_day`, `S_lapse` and `D'' = w7·D0(4) + (1−w7)·D'` as transcribed, and the prompt's "no clamp, floor … beyond the spec's" with its reference values (same-day Good `2.2938`; D' `2.1170`/`4.7586`/`7.4003`; same-day Again D' `7.4003`; `_next_difficulty` `4.9960`/`8.3475`/`9.9910`) → the FSRS-6 reference forms (review fixes `a8a83e7`, `45b85ca`, `6d6cb3b`): the same-day increase is floored at 1 for Hard/Good/Easy; `S_lapse = min(…, S / e^(w17·w18))`; mean reversion targets the unclamped `D0(4) = −4.7716`. Reference values are now same-day Good and Hard `2.3065`; D' `2.1112`/`4.7529`/`7.3945`; `_next_difficulty` `4.9902`/`8.3418`/`9.9852` (stabilities `13.8269`/`9.2349`/`0.6369`/`0.7751`/`37.4206`/`4.6130` unchanged) → spec §3.2 is headed FSRS-6 and `FSRS_W` equals py-fsrs 6.3.2's default weights exactly, so the weights were fitted under the reference model. The transcription made a correct same-day answer lower S (Good for S above ~2.1 days, Hard at every realistic S: a first Good plus two same-session assisted passes ended at 0.80 days, below one Hard's S0 of 1.29), and let an Again raise S in a corner (`next_state(1.0, 0.05, AGAIN, 60)` gave 0.0572). Verified against the py-fsrs 6.3.2 source; `next_state` now matches it to 5e-15 over a 20 000-case grid. The spec text is unchanged; ratifying this as a §13 amendment is Open question (4) †.
- The same line's "`next_state` now matches py-fsrs 6.3.2 to 5e-15" held only while S' ≥ 0.001 d → (second review round, `9cf1919` + `93631c9`) a fourth FSRS-6 guard: `next_state` returns `max(S', FSRS_STABILITY_MIN)` with `FSRS_STABILITY_MIN = 0.001` in params.py, applied after the MC cap → py-fsrs 6.3.2 clamps every new stability at `STABILITY_MIN = 0.001` (`_clamp_stability`, in `_short_term_stability` and `_next_stability`). Without it, repeated same-day Agains drove S toward ≈1.5e-7 d: a first Again plus 12 same-day Agains ended at 7.7e-5 d against the reference's 0.001, and the next-day Good gave 0.0003 d, not 0.0154. A chat-heavy session that rates many wrong `chat_turn`s Again reaches that region. Floor-last rather than py-fsrs's floor-inside: py-fsrs has no MC cap, the orders agree whenever `S ≥ FSRS_STABILITY_MIN / 2`, and floor-last keeps `S' ≥ 0.001` unconditionally. Differential against py-fsrs 6.3.2 internals, 40 000 cases over S in [1e-6, 3000] d, D in [1, 10], all ratings, both paths: max relative error 3.5e-15. Every earlier reference value is unchanged (all have S' ≥ 0.001). The constant lives in params.py because the prompt puts every non-neutral decimal literal there; that makes it a second PKG-01 reopen, committed mid-branch as its own commit just before the `fsrs.py` change that reads it, not as the branch's first commit (a review round cannot rewrite history; cf. the `8708325` line below). Folded into Open question (4) †.
- Test count `58` in `test_learning_fsrs.py` → `89` → `120` after the review fixes (+21 validation cases: `retention_target` 9, rung 6, `mc_cap_applies` 3, SR counters 3; +6 gate-rule detector cases; +4 FSRS-6 guard tests: same-day pass never lowers S, same-session trajectories, lapse cap, reversion target) → `128` after the second review round (+5 `from_dict` corrupt-state cases, +1 int-storage test, +2 stability-floor tests). The 89 cases:
  - NaN/inf cases in both reject tests, and non-integer ratings.
  - `test_next_state_rejects_out_of_domain_state` (7 cases) and `test_mc_cap_never_applies_to_a_first_rating`.
  - A1: `test_rating_channels_are_the_evidence_channels` and `test_mc_cap_applies_exactly_when_mc_rates_good`; the rating table keeps 15 rows with an `idk` column.
  - `test_order_due_is_stable_on_ties` and `test_item_retrievability_rejects_a_corrupt_row`, plus naive and ISO `now` cases.
  - The detector test (8 cases) and `test_relearning_rejects_a_corrupt_stored_state` (3 cases).
- Task 6 Step 4 import blocks → `fsrs.py` also imports `CHANNELS` (A1). The test module also imports `ast`, `copy`, `pathlib` and `CHANNELS` → required by the deviations above.

## Known gaps

- The H4–H6 → Again isomorph re-ask is a rating only; PKG-06/07 schedule the re-ask.
- No `fsrs_due_at` writer: PKG-03 computes `due_at = last_review + interval(retention_target(...), S')`.
- `RATING_CHANNELS` is `frozenset(params.CHANNELS)`, while PKG-03's `Evidence.channel` Literal restates the names. PKG-03 must add a test asserting `set(get_args(Channel)) == fsrs.RATING_CHANNELS`. Per §13 A1 it has 5 members and no `idk`, not the six the PKG-03 prompt text assumes.
- `rating_for` rejects a non-integer or negative rung but not `max_rung > 6`. `LADDER_MAX_RUNG` is PKG-03's name to add (its prompt, §13 A6), and `Evidence.max_rung` validates `0..LADDER_MAX_RUNG`. Until then a rung above 6 rates Again, like H4–H6.
- Spec §3.2's formula block still shows the transcription without the four FSRS-6 guards, and the PKG-02 prompt still lists "`D0(4)` unclamped in the mean-reversion term" as a slip and pins the pre-guard reference values, so spec, prompt and code disagree there until the owner records the amendment (Open question (4)). This hand-off is the record in the meantime; a session that recomputes FSRS values from spec §3.2 alone gets different numbers.
- Flag-off inertness is pinned by acceptance 8's grep and the upstream gates, not by a test: `test_routes_import_fsrs_only_behind_the_gate` scans only `routes/` and checks gate presence per module, not that every fsrs use sits under the gate. The packages that add the sanctioned importers (PKG-03 `services/graph_service.py`, PKG-11 `routes/flashcards.py`, PKG-12's review service) should add an allowlist test, "modules importing `learning.fsrs` ⊆ {the sanctioned set}", in a module they own.
- Weights are pinned, and there is no refit path. Spec §3.2 stores check type + pre-check R on review rows for a later refit; that is PKG-03's event columns.
- `bkt._retrievability` still duplicates `fsrs.retrievability` (HANDOFF-01 Known gap (a)). PKG-03 may point it at `fsrs`. `decayed_p` validates before it calls `_retrievability` (stability finite and > 0, days clamped at 0, NaN raises, and `+inf` allowed), which is the domain `fsrs.retrievability` accepts. So the dedupe does not change behaviour.
- `SuccessiveRelearning` credits a relearn session when its id differs from the last credited one, so a return to an older session id after a newer one counts again. Session ids are unique per session in practice, so it tracks one id, not a set.
- needs local Supabase stack (supabase start): nothing in this package. There is no migration, table, route or request path; self-check item 5 skips the E2E cycle by design, and no supabase CLI / podman / docker is present on the executing machine anyway.
- Evals: not run. No prompt or tool description changed (self-check item 4).
- Flakes observed: none.

## Verify commands

```
cd backend && venv/bin/python -m pytest tests/test_learning_fsrs.py -q                          → N passed (N ≥ 15)
grep -cE "^def (retrievability|interval|next_state|rating_for|order_due|budget_select)\(" backend/learning/fsrs.py → 6
cd backend && venv/bin/python -c "from learning.params import FSRS_W; assert len(FSRS_W)==21; print('ok')" → ok
```

(Observed at hand-off: `89 passed`, `6`, `ok`. After the review fixes: `120 passed`, `6`, `ok`. After the second review round: `128 passed`, `6`, `ok`. After the CodeRabbit PR #673 round (5c9fa9f): `131 passed`, `6`, `ok`.)

## Open questions for the series owner

- (1) Should a same-day review skip the difficulty update? Option taken: no; the spec has one D rule, and py-fsrs 6.3.2 also updates D on a same-day review.
- (2) Should `chat_turn` feed FSRS at all? Option taken: yes, as Hard when correct and unassisted † (§13 A7). The alternative is to skip the FSRS update for `chat_turn` in PKG-03's adapter.
- (3) Should `budget_select` round the item count up when the remainder is at least half a check? Option taken: floor (`//`), per the prompt; at the defaults, 720 s / 45 s is exactly 16.
- (4) The spec's formulas omit four refinements of the reference FSRS-6 implementation. The review checked them against the py-fsrs 6.3.2 source, whose default weights equal `FSRS_W`:
  - (a) The mean-reversion target is the UNCLAMPED `D0(4)` (−4.7716), not the clamped 1.0; the difference is ≈ 0.006 per update.
  - (b) The same-day stability increase is floored at 1 for Hard, Good and Easy (not only Good/Easy, as this question first said from memory), so a same-day pass never lowers S. Without it a same-day Good lowered S from 2.3065 to 2.2938, and a same-day Hard to 1.3334.
  - (c) Post-lapse stability is capped at `S / e^(w17·w18)`.
  - (d) Every new stability is floored at `STABILITY_MIN = 0.001` d (`params.FSRS_STABILITY_MIN`, second review round). Without it, repeated same-day Agains drove S toward ≈1.5e-7 d.
  Option taken: adopt all four † (changed in review from "spec verbatim"; Deviations). Proposed §13 text: "A14 — §3.2 FSRS-6 reference guards: `S_same_day = S·max(1, e^(w17·(G−3+w18))·S^(−w19))` for G ≥ 2 (G = 1 unfloored); `S_lapse = min(w11·D^(−w12)·((S+1)^w13 − 1)·e^(w14·(1−R)), S / e^(w17·w18))`; `D'' = clamp(w7·D0raw(4) + (1−w7)·D', 1, 10)` with `D0raw(4) = w4 − e^(3·w5) + 1`; every new `S' = max(S', FSRS_STABILITY_MIN)`, `FSRS_STABILITY_MIN = 0.001` d, after the MC cap. Affects PKG-02." If the owner wants spec verbatim instead, revert `a8a83e7`, `45b85ca`, `6d6cb3b` and `93631c9` (their tests revert with them) as a PKG-02 reopen, and `9cf1919` as a PKG-01 reopen; PKG-03 must then not pass `same_day=True` for correct answers.

## Post-hoc changes

(Appended by later packages that modified this package's code. Format: `PKG-MM <date>: <what> — commit <sha>`.)
- CodeRabbit PR #673 review 2026-09-27: `_check_rating` now also catches `OverflowError`. `int(±inf)` raises `OverflowError`, and that escaped `initial_stability`, `initial_difficulty` and `next_state`, breaking the "every public function raises ValueError on out-of-domain input, NaN and ±inf included" contract. `test_bad_rating_rejected` gains `nan`, `inf` and `-inf` cases and now checks `next_state` (first and later rating), `initial_stability` and `initial_difficulty`. `tests/test_learning_fsrs.py` goes from 128 to 131 passed (Verify commands: `131 passed`, `6`, `ok`) — commit 5c9fa9f
- Spec amendment 2026-09-27 (docs only, no code change): Open question (4) is resolved. The four FSRS-6 reference guards (the same-day floor with the `S^(−w19)` factor, the lapse cap, mean reversion toward the unclamped `D0(4)`, and the `FSRS_STABILITY_MIN = 0.001` d floor) are ratified in spec §3.2 as §13 A28, and `FSRS_STABILITY_MIN` is in the §3.2 constants table. The proposed number "A14" was already taken by the default-on decision. The frozen PKG-02 prompt keeps its pre-guard reference values; this hand-off and A28 are the record, and Known gaps' "spec, prompt and code disagree" now applies only to the prompt.
