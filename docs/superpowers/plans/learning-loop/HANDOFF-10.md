# HANDOFF-10 — misconceptions

Written by the session that executed `PKG-10-misconceptions.md` (worktree `sapling-wt-10`, branch `feat/learning-loop-10-misconceptions`, cut from `feat/learning-loop` at 989e6733). Read by every later package that depends on 10. Keep every heading, even if the answer is "none". **LEDGER.md is not touched here** (session rule: the coordinator writes the ledger rows — see "Ledger rows to add" at the end).

## What changed

Every graded explicit submission on the loop check route now runs the spec §3.3 slip / misconception / novice rule over the session's attempts on that concept. The `wrong_key` that enters the rule comes only from `decisions.match_wrong_reason`, called with the grader's own `GradeResult` as `prior` (no model call, never called without it), filtered by PKG-05's unchanged A22 option rule and accepted only when it is a key the item lists and is identifier-shaped. A keyed `misconception` verdict marks one row per (student, node, key) in the new `misconceptions` table; the check route writes it (`evidence_text` = the text the grader saw, encrypted) AFTER its one `flush_pending`, under the grading claim, and sets a confrontation marker in `sessions.loop_state`. The next model turn with room for it (answer released, or model ceiling ≥ H4) on a tier whose eval passes (`CONFRONT_TIERS = {deep}`) carries a field-mapped confrontation line after the phase instruction, is routed deep (`misconception_active`, A15, downgrades unchanged) and clears the marker. After an `unknown` verdict `_activate_next_item` re-asks an isomorph (`policy.next_isomorph`) from its own servable candidates. The learner brief lists the student's open misconception keys from the table (then the closes'), and the session close feeds `build_close` the open keys on the session's evidence nodes. A class rollup exists as a SECURITY DEFINER SQL function (course concept_key + wrong_key, ≥ 5 distinct students, service_role only), reachable only from backend code (inv 17). A served-path eval dataset (`misconception_confront`, 7 cases × deep and standard, three fresh recordings each) decides which tier may carry the line.

## Symbols added

- `backend/learning/misconceptions.py` (was a stub):
  - `Verdict` (= `learning.evidence.MisconceptionVerdict`: `none|unknown|slip|misconception|gap|not_known|novice`), `KEY_PATTERN` (`[a-z0-9][a-z0-9_]{0,63}`), `is_key(key) -> bool`.
  - `Attempt` (pydantic, `extra="forbid"`): `question_hash, node_id, correct, wrong_key, confidence (0..1, STUDENT-stated), difficulty, idk, isomorph_of, released, after_release` — no free text. `released`: the attempt released its concept's reference (not correct, idk, or max_rung ≥ RUNG_NO_CREDIT_MIN — A76); `after_release`: it was graded as a re-check.
  - `slip_or_misconception(history: list[Attempt]) -> Verdict` — pure, one node's history (ValueError on mixed nodes), first match wins (PKG-10 Behaviour 2).
  - `attempts_of(loop_state) -> list` (the live log; a malformed stored value is replaced by `[]`), `attempts_for_node(log, node_id) -> list[Attempt]` (skips malformed rows), `confront_of(loop_state) -> dict | None` (a malformed/incomplete marker or a non-identifier key reads as None), `set_confront(loop_state, marker | None)`, `carry(loop_state, diagnosis | None)` (the route's CAS mutate: appends the attempt, sets the marker, or clears the marker it cleared only while the fresh document still holds that same marker).
  - `record(user_id, node_id, check_item_id, wrong_key, evidence_text) -> dict` (open-row insert-or-increment; `evidence_text` encrypted here; a non-identifier key is refused with no read; `{}` on any DB error; the log line carries no student text), `resolve(user_id, node_id, wrong_key) -> int` (no caller yet), `open_for(user_id, node_ids) -> [{node_id, wrong_key, count}]` (count desc, identifier keys only, no read for `[]`, `[]` on error, never reads `evidence_text`), `rollup(course_id) -> list[dict]` (`rpc("misconception_rollup", …)`, `[]` on error; backend-only).
- Fix-round symbols: `learning/misconceptions.py::last_release_on_node(loop_state, node_id) -> bool | None` (A76; replaces fix round 1's `released_on_node`), `record()` now one rpc to `misconception_record`, `open_for` filters `last_seen_at >= now − MISCONCEPTION_RECENT_DAYS`, `_utcnow()`; `learning/loop_state_store.py::recent_evidence(user_id, node_id, *, since) -> list[dict] | None` (A76; fix round 4 replaced R2-2's `latest_evidence_released`); `learning/leak.py::in_answer_position(text, start, end)` (PKG-06 reopen); `learning/checks.py::_wrong_text_answer_reasons` (PKG-04 reopen; since fix round 4 a call to `leak.confront_text_states_answer`, A77 — the round-2/3 heuristics and `leak.in_answer_position` / `quantifies_given` are gone); `learning/leak.py::confront_text_states_answer(text, *, final_answer, canonical_answer, correct_option, option_text) -> bool` (fix round 4; round 5 removed its `prompt` provenance) and `_ANSWER_AFTER` (fix round 4, served mode); `learning/misconceptions.py::recheck_after_release(user_id, node_id, loop_state, *, now, item) -> bool` (fix round 3; replaces `routes/learn_loop.py::_recheck_after_release`) and `owed_isomorph(rows, shape) -> bool` (fix round 4; no paid state and fail-closed since round 5); `routes/learn_loop.py::_requests_of`, `_confrontation_text`, `_LoopTurn.run_requests`; SQL `misconception_record(p_id, p_user_id, p_node_id, p_check_item_id, p_wrong_key, p_evidence_text) RETURNS TABLE (id text, count int)` and index `misconceptions_open_key_uidx` (migration `20260929143810_learning_misconceptions_atomic.sql`); `decision.made` payload key `prior`; params `MISCONCEPTION_RECENT_DAYS = 30 †`, `RECHECK_RELEASE_WINDOW_HOURS = 24 †`, `MISCONCEPTION_CONFRONT_MIN_RUNG = 4`.
- `backend/learning/evidence.py::MisconceptionVerdict`, `Evidence.verdict`, `Evidence.wrong_key` (PKG-03 reopen).
- `backend/learning/policy.py::next_isomorph(item, items) -> ItemLike | None` (PKG-06 reopen). Loop-state top-level keys `attempts` (list of Attempt dicts) and `confront` (`{node_id, wrong_key, check_item_id}` | null), riding `LoopState.extra`.
- `backend/agents/tools/check.py` (PKG-05 reopen): `grader_answer_text(item, answer) -> str`; `async match_wrong_key(item, *, prior, answer_text, deps) -> str | None`; `async apply_misconception_rule(deps, *, item, grade, evidence) -> Verdict | None`; `GradeOutcome.verdict`, `GradeOutcome.diagnosis` (`{attempt, confront, cleared, record}`); `_record` is async.
- `backend/routes/learn_loop.py` (PKG-07/09 reopens): `CONFRONT_TIERS = frozenset({"deep"})`, `_CONFRONT_LINE`, `_confrontation_line(loop_state) -> str | None`, `confront_line_for(text) -> str | None`, `with_confrontation(prefix, line) -> str`, `_LoopTurn._confront_line()`, `_LoopTurn.confront_line` / `confront_used`, `_isomorph_after_unknown(state, node_id, items, exclude)`, `_write_misconception(user_id, outcome, item, answer)`, `_close_misconception_keys(user_id, evidence)` (signature changed from `(user_id, session_id)`).
- `backend/learning/learner_brief.py::_open_misconception_keys` repointed at `open_for`; `_KEY` is `KEY_PATTERN`.
- `backend/agents/function_handlers_e2e.py::E2E_GRADER_WRONG_REASON_TOKEN` (`"E2E_GRADER_WRONG_REASON"`), `_WRONG_KEY_RE`; the grader handler's `matched_wrong_key` = the first `COMMON WRONG REASON <key>:` line when a not-correct answer holds the token.
- Table `misconceptions` (spec §4 PKG-10 DDL) + index `misconceptions_user_node_idx`; function `misconception_rollup(p_course_id text) RETURNS TABLE (concept_key text, wrong_key text, users int)` — migration `backend/db/migrations/20260929132008_learning_misconceptions.sql` (RLS on, no policy; PUBLIC revoked; anon/authenticated revoked and service_role granted under a role-existence guard; `SET search_path = public, pg_temp`).
- `backend/e2e_oracles/gather.py::_CIPHERTEXT_MANIFEST` + `("misconceptions", "id", "evidence_text")`.
- Eval: `backend/tests/evals/misconception_confront.py` (datasets `misconception_confront__loop_tutor_deep`, `misconception_confront__loop_tutor`; `VARIANTS`; `CONFRONT_SLOTS`, `SERVED_GATES`, `DIAGNOSTICS`, `assembled`, `check_fresh`, `record_turn`), `backend/tests/evals/_confront_judge.py` (eval-only judge, `ConfrontJudgement{confronts, only_states_correction, affirms_misconception, evidence}`, gemini-2.5-pro, cassettes `cassettes/misconception_confront_judge/`), cassettes `cassettes/misconception_confront/<slot>/`, rung-judge cassettes `loop_tutor_rung_judge/<slot>__confront_*.json`, baselines blocks for both datasets + `misconception_confront_routing` (3 runs); `run_all.py` DATASETS + `misconception_confront`.
- Tests: `tests/test_learning_misconceptions.py` (new), appended to `tests/test_learning_loop_invariants.py` (`test_inv_17_rollup_not_a_tutor_tool`, `test_inv_17_scan_self_test`), `tests/test_learning_evidence_apply.py`, `tests/test_learning_zpd_policy.py`, `tests/test_learn_loop_routes.py`, `tests/test_learning_close_brief.py`, `tests/test_e2e_function_handlers.py`; two pins moved in `tests/test_learning_decisions.py`.

## Constants chosen

- `MISCONCEPTION_MIN_ISOMORPHS = 2` (spec §3.3 "≥ 2 isomorphs").
- `MISCONCEPTION_RECENT_DAYS = 30 †` (fix round F6; spec §13 A75(i); A/B candidate).
- `RECHECK_RELEASE_WINDOW_HOURS = 24 †` (fix round 2 R2-2; spec §13 A76; A/B candidate).
- `GAP_CONFIDENCE_MAX = 0.4 †` (spec §13 A6; A/B candidate; unused on the served path until a student-confidence field exists).
- `NOVICE_FLOOR_IDK = 2 †` (spec §13 A6; PKG-08 added it — verified present).
- `MISCONCEPTION_KEY_MAX_CHARS = 64` (the PKG-09 brief's key pattern, now the store's).
- `MISCONCEPTION_CONFRONT_MIN_RUNG = 4` (spec §13 A75; eval evidence: the rung judge read every H3-ceiling confrontation as H4).
- `CONFRONT_TIERS = {"deep"}` (routes; spec §13 A75; pinned to `misconception_confront_routing`).
- Verified present (PKG-01/08): `MISCONCEPTION_CONFIDENCE = 0.7`, `NOVICE_FLOOR_MISSES = 3`, `MISCONCEPTION_ROLLUP_MIN_USERS = 5` (= the migration's HAVING literal, pinned), `LEARNER_BRIEF_MAX_MISCONCEPTIONS = 5`, `LEARNER_BRIEF_MAX_CHARS = 1800`.

## Deviations from spec

(Recorded in spec §13 A75; the LEDGER Deviations lines are for the coordinator.)

- `Verdict` has a seventh value `none` (spec §3.3 enumerates six) → the rule runs on every graded attempt, and a plain correct answer has nothing to diagnose.
- `sessions.loop_state` gains sibling keys `attempts` and `confront` (spec §4 describes per-item entries only) → ids/enums/bools/numbers and the plaintext key only; they ride `LoopState.extra` like PKG-07/08/09's top-level keys (the prompt's typed `LoopState` fields → not added: the code on disk carries later packages' keys untyped, and the accessors in `learning.misconceptions` validate).
- Prompt Behaviour 5: `apply_misconception_rule` calls `record` → it only marks the row; the check route writes it after `flush_pending` → a write before the flush let a failed flush + resubmission count one misconception twice (spec §13 A75(a)).
- The migration's grant lines → the house guarded `DO $$` block + `ALTER TABLE … ENABLE ROW LEVEL SECURITY` + `REVOKE … FROM PUBLIC` + `SET search_path` on the SECURITY DEFINER function → a plain Postgres has no Supabase roles (an unguarded REVOKE aborts), PostgREST exposes new tables to the anon key, and a definer function must pin its path. `test_rollup_is_backend_only` asserts the guarded form.
- The confrontation line text (prompt: `… create a contradiction they must resolve; do not simply state the correction.`) → field-mapped to the structured turn (A46) and quote-safe → the prompt's text scored Confronts 0.14 live on the standard slot (the key idea and the released-answer "corrective feedback" rule pulled every turn into stating the correction).
- The line is not sent below H4 (answer unreleased), on a correct-answer feedback turn, when it states the active unreleased item's answer, or on a tier outside `CONFRONT_TIERS` (the prompt: every model turn, tier from `model_tier` alone) → the ceiling is hard (§3.3), model-written text reaching a prompt passes the strict served leak check, and a tier serves the line only after its eval passes (A15/A48/A49's direction).
- A correct answer on the marked node clears a pending marker (not in the prompt) → never confront a student who has since answered the concept right.
- Prompt "no eval dataset, no new E2E constant" → a `misconception_confront` dataset (7 cases, two slots, min-of-3) and `E2E_GRADER_WRONG_REASON_TOKEN` → session rules: gate the SERVED path; every newly wired request-path decision gets a function-mode path + test.
- `FeedbackNeverEndsInAnswer` in this dataset matches the final answer as a token (loop_tutor's substring test counts a one-character answer inside any other number of a confronting case).
- `test_learning_decisions.py` (PKG-05b) pins changed: `grade_answer` emits one more `decision.made` (`match_wrong_reason`, latency 0).
- `CLAUDE.md`'s encrypted-column list gains `misconceptions.evidence_text` (fix round; the coordinator authorised this one line).

## Known gaps

- An exhausted compare-and-set on the grade's save (409, the grading claim still held) loses the misconception row: it is written only after that save confirms our claim (conformance 8), and the item is never graded again. The evidence itself is already flushed.
- The re-check rule's journal half (A76) is two extra owner-scoped reads (the node's evidence rows in the window + their items' format/difficulty) on every graded item whose session log does not already say "re-check" — since fix round 4 (the owed isomorph class) that includes most check-route grades, and every probe and review check grade; a failed read decides nothing (graded normally). A released item whose `check_items` row is gone owes on every class of the node for the window (fail closed, round 5); after a release every class-mate is a re-check for 24 h, so credit on that class is slower for the window (A76's accepted cost).
- Student-stated confidence is `None` (A16's body has no confidence field; post-series reason/confidence tier), so only the two-isomorph path yields `misconception` today, and `gap` never fires on the served path.
- A misconception recorded mid-session reaches the learner brief only from the next session (the brief is built once, A19); in-session the confrontation line carries it.
- A marker waits while no turn has room (develop-band teach turns sit below H4; soft budget/deep cap downgrade to standard): the confrontation may never happen in that session; the store row and the next brief still carry the key.
- `resolve()` has no caller (PKG-12's review grading or PKG-14's post-test is the natural one): rows stay open; since the fix round the brief and the close list only rows seen within `MISCONCEPTION_RECENT_DAYS` (30 †), so an old misconception stops re-listing, but it still counts in the rollup. `rollup()` has no caller (instructor surface / quiz-agent switch are open questions). `not_known` is unreachable on the served path (`_wrong_key` gives a correct answer no key).
- A wrong key longer than 64 characters (no length bound on drafted keys, `checks.wrong_key_form`) is never stored (WARNING).
- The probe (PKG-08) and the review (PKG-12) pass no loop state: their answers never feed the rule.
- The verdict is computed over the request's loop-state snapshot; a concurrent grade of another item in the same session (not reachable through `current`, but possible around `/check/next`) could miss one attempt in that one verdict — the log itself is re-applied to the fresh document and loses nothing.
- Deep confronting turns used an output retry in about half the cases (RetriesUsed diagnostic): the body runs past the feedback sentence limit; cost, not correctness (the validator catches it).

## Verification at hand-off

- `cd backend && venv/bin/python -m pytest tests/ -q -p no:cacheprovider --ignore=tests/evals --ignore=tests/test_docling_integration.py --ignore=tests/test_ocr_pipeline.py --ignore=tests/test_extraction_backends.py` → `7842 passed, 138 skipped` (N₀ at 989e6733: 7705 passed, 138 skipped); `tests/test_learning_misconceptions.py` → 94 passed; invariants → 30 passed, 1 skipped; `ruff check .` → All checks passed!
- `SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/run_all.py` → all 16 datasets PASS (loop_tutor ×3, grader and decisions unchanged, both `misconception_confront__*` new).
- Not run here (session rules): the E2E stack cycle, the migration replay on a fresh DB, the three independent reviews, the merge.

## Verify commands

```
cd backend && venv/bin/python -m pytest tests/test_learning_misconceptions.py -q                → N passed (N ≥ 10)
ls backend/db/migrations/*_learning_misconceptions.sql                                           → 1 file
grep -c "HAVING count(DISTINCT m.user_id) >= 5" backend/db/migrations/*_learning_misconceptions.sql → 1
grep -cE "^def (record|slip_or_misconception|rollup)\(" backend/learning/misconceptions.py        → 3
```

## Fix round (2026-09-29, after three reviews)

- **MAJOR F1 (evidence integrity).** After an unkeyed wrong answer the isomorph re-ask served the twin right after the feedback turn released the reference, graded as a full-weight unassisted first attempt (recheck detection keys on the same question_hash). Now each Attempt records `released` / `after_release`, `released_on_node(state, node)` says a concept's reference was released earlier this session, and `_grade_submission` grades such an item `same_session_recheck=True`: weight × WEIGHT_SAME_SESSION_RECHECK, the unassisted streak and the strong-channel count unchanged (graph_service's re-check rule). A twin after a CORRECT answer is unaffected. Tests through the route, grade_answer and apply_graph_update. — 3e280376, 31d5b1b2, 2ba00440
- **F2** the marker is concept-scoped (`_confront_line` needs `marker.node_id == concept_node`, so misconception_active never routes another concept deep) and `_advance_cursor` drops it. — 5d696699
- **F3** the item-drafted text (not the route's wording) is leak-checked strict with NO provenance ("stays four, not three" for 4x^3 is withheld); PKG-04 drafting refuses a wrong reason stating the final answer. — 70c40aec, 178a0f17 (70c40aec alone left the PKG-06 inertness scan red; 178a0f17 fixes it), 5d696699
- **F4** a confronting deep turn adds every model request of its run to `deep_requests`. — d2383c49, fc2e0dd2
- **F5** NEW migration `20260929143810_learning_misconceptions_atomic.sql`: open duplicates merged, partial UNIQUE index on the open key, `misconception_record(...)` INSERT … ON CONFLICT increment (`record()` is one rpc), validated on a throwaway Postgres 15; `_close_misconception_keys` de-duplicates; an integration-marked test (`tests/integration/test_misconceptions_record_db.py`, 8 concurrent records → one row, count 8; not run here). — 6408132b, 96926dba
- **F6** the rollup re-created with `g.user_id = m.user_id` (same migration); recency window `MISCONCEPTION_RECENT_DAYS = 30 †` on `open_for`. — 6408132b
- **Conformance 3** `decision.made` carries `prior`; the prior-path wrong-key match names the grader's backend. — fdac54d4
- **Conformance 8** the misconception row is written only after the save that recorded the grade under our claim. — cbfe4cbe
- **Formatting** the whole-file ruff reflows of `agents/function_handlers_e2e.py`, `tests/test_e2e_function_handlers.py` and two `routes/learn_loop.py` hunks are reverted. — e15dfc12, 2ba00440
- **Conformance 2 (eval record, stated in full)** standard's three runs: run 1 Confronts 0.43 (RetriesUsed 0.57); run 2 Confronts 0.50 with `_raised: true` (a case errored); run 3 Confronts 0.43, FeedbackNeverEndsInAnswer 0.857 (RetriesUsed 0.57). Deep: every served gate 1.0 in all three (RetriesUsed 0.57 / 0.86 / 0.71). Deep-cap interaction: a develop/profic session that has spent `LOOP_SESSION_MAX_DEEP_REQUESTS` routes the confronting turn to standard, which carries no line — the marker waits the rest of the session.
- Suite after the fix round: 7862 passed, 140 skipped (the 2 new skips are the integration-marked tests); `run_all` replay 16/16 PASS; no re-recording (≤ $1 cap: $0 spent).

## Fix round 2 (2026-09-29)

- PKG-09 integration test: `tests/integration/test_session_close_db.py` used mode `exam`, which violates `sessions_mode_check` before ON CONFLICT runs; now `expository` — 9ed50732.
- **R2-1** `released` uses the revealed rule (wrong, idk, or a worked H4/H6 answer shown) — 3557a43c, f0249d18.
- **R2-2** a session hop no longer bypasses the rule: with no attempt on the concept this session, the node's newest evidence row within `RECHECK_RELEASE_WINDOW_HOURS` decides — ad48ac1a.
- **R2-3 (decided)** only the NEXT graded item on the concept after a release is a re-check; the one after is normal — 3557a43c, ad48ac1a. Recorded as spec §13 **A76** (with a §3.3 cross-reference).
- **R2-4** the drafting lint reads a single-token numeric/boolean answer only as a stated result (answer position via `leak.in_answer_position`, a result verb, never before a condition); the reviewer's honest cases are clean, multi-token answers stay strict — 06a52643, 919afcaf.
- Docs: A75 header names the PKG-04 reopen and 05b's code change; §4's DDL block points at A75(f); A76 added.
- Suite 7889 passed, 140 skipped; replay run_all 16/16 PASS; $0 live.

## Fix round 3 (2026-09-29)

- **R3-1 (Minor)** the probe and the review graded without `same_session_recheck`: the first item on a concept after a release (session A's wrong loop answer, then a session-B probe item or a due review item) was a full-weight unassisted first attempt, and its correct row, now the journal's newest, also cleared the later session-B twin. The A76 decision is now ONE function, `learning.misconceptions.recheck_after_release(user_id, node_id, loop_state, *, now)` (session log first, then the journal within `RECHECK_RELEASE_WINDOW_HOURS`; reads only — `last_release_on_node` no longer inserts an empty `attempts` list), and the check route, the probe (grade + refusal→idk re-grade) and `review.grade_review` all pass it. A structural test (`test_every_grading_caller_decides_the_recheck_through_the_one_helper`) fails any production `grade_answer` call that omits `same_session_recheck=` or sits in a function that never calls the helper. The sequence (wrong in A → review is THE re-check → the twin after it is normal) is pinned by `test_the_review_after_a_release_is_the_recheck_and_the_twin_after_it_is_not`: the "only the next item" rule now holds across callers. Two import edges sanctioned: `misconceptions` → `loop_state_store.latest_evidence_released` (PKG-06 inertness scan) and `review` → `misconceptions` (inv 17). FSRS rating is untouched by the flag, as on the check route. — b1dc08bc, bd3aa26f. Spec A76 amended (PKG-10's own row).
- **R3-2 (Minor)** the drafting lint missed single-token answers stated with an unlisted verb ("Concludes 2.", "Writes 2 as the final answer.", "Picks 2 because …", "Arrives at 2 …", "Settles on 2 …") or before a condition ("Gets 2 only by luck.", "Says the limit is 2 for this function.", "The limit equals 2 if you simplify …"). Structural fix, no verb list: the default is inverted — a single numeric/boolean token is STATED unless, outside answer position, it plays a structural non-result role read off the surrounding characters and closed-class words (glued into an expression: `x^2`, `2n+1`, `2-step`; an operand: `by 2`, `3 + 2`, `2 and 3`, `2 to/from/as …` but not `as the (final) answer`; a quantifier of a content word — `one step`, `one of the cases` — unless that noun is the prompt's own object, `leak.quantifies_given`). The condition exemption applies to boolean answers only. `_RESULT_VERB` removed. All round-2 negatives/positives, the reviewer's eleven cases (`/tmp/claude-1000/pkg10-review3/lint3.py`), 14 new negatives, a prompt-object test, and the two single-token eval-cassette items keep their expected verdicts. — 14a47935 (PKG-06), 2699b205 (PKG-04). A75(d) amended.
- Known limit of R3-2 (accepted, the lenient/strict trade-off): a stated result followed by an unlisted content word ("Gets 2 quickly") reads as a quantifier and is not refused (serve-time strict `detect_leak` still withholds the line); an honest number after an unusual preposition ("Starts the index at 1" for answer 1) is refused and the draft is re-drafted.
- Suite 7929 passed, 140 skipped; replay `run_all` 16/16 PASS; $0 live.

## Fix round 4 (2026-09-29)

- **R4-2 + R4-3 (Minor; CONTINUE rule 1: a heuristic that kept failing review is replaced by one source of truth)** the drafting lint and the serve-time confrontation check are now ONE function, `leak.confront_text_states_answer` — spec §13 **A77** (new row: it changes PKG-04's lint and PKG-06's leak rules). `checks._wrong_text_answer_reasons` and `_LoopTurn._confront_line` both call it (a structural test pins both); the round-2/3 role heuristic is deleted. It is `detect_leak`'s strict final-answer/option rules with no reference n-grams (the serve check read them before: concept vocabulary, not the answer — 9 honest wrong reasons in the eval corpus shared one) and one provenance: "the <value>" whose value the item's prompt shows, unless in answer position (tested against every stated case of lint3/lint4: none passes). The number-word gap was real at serve time in SERVED mode (tutor text: "Write two as the final answer." leaked); answer position is now read after the hit too (`_ANSWER_AFTER`). The confrontation line's own check never had the gap (non-served strict). — d74725d6 (PKG-06), efbc4833 (PKG-04/10).
  Before/after on every reviewer case of rounds 2–4 (52 cases; "disagree" = lint ≠ serve):

  | group | n | round 3: lint refused / serve withheld / disagree | round 4: lint refused / serve withheld / disagree |
  |---|---|---|---|
  | states the answer (lint3, lint4 leaky, round-2/3 positives) | 31 | 25 / 31 / 6 | 31 / 31 / 0 |
  | honest, "the <prompt value>" ("Ignores the 2.", "Adds the two limits …") | 5 | 3 / 5 / 2 | 0 / 0 / 0 |
  | honest, no answer token ("Thinks 0! is 0 …") | 6 | 0 / 0 / 0 | 0 / 0 / 0 |
  | honest by intent, names the value unanaphorically ("Forgets to multiply by 2 …", "Counts three sides …") | 10 | 3 / 10 / 7 | 10 / 10 / 0 |

  Round 3 stored 6 stated answers ("Gets 2 quickly.", "Writes two as the final answer.", "Answers true only because …", "Reports 2 cases.", "Thinks the limit is the 2 from sin(2x).", "Takes 2 as the limit.") and stored 7 texts the line could never serve; round 4 stores none of either, and five anaphoric honest texts become servable. The 10 "honest by intent" texts are refused, and the item re-drafted, BY DESIGN (the owner's stored == servable).
- **R4-1 (Minor)** an intermediate probe/review item on the node took the "next item" re-check and its correct row became the newest, so session A's released item's isomorph twin was graded at full weight in session B. A release now opens a debt for the released item's isomorph class — (format, difficulty) on the node, the class `next_isomorph` draws twins from — paid only by the next graded item OF THAT CLASS (`misconceptions.owed_isomorph`), whatever came between; `recheck_after_release(..., item=)` = "next item after a release" OR an owed class; `loop_state_store.recent_evidence` replaces `latest_evidence_released` (one more read: the rows' items' plaintext format/difficulty). Identity choice: the class, not one twin's question_hash — the twin is picked only when served (A27), and any twin of the class carries the copy risk; the debt is bounded by `RECHECK_RELEASE_WINDOW_HOURS`. Spec A76 amended. — 27d92eff.
- Suite 8012 passed, 140 skipped; replay `run_all` 16/16 PASS; $0 live.

## Fix round 5 (2026-09-29)

Round-5 review (`/tmp/claude-1000/pkg10-review3/lint5.py`): no leaks, three Minors. Coordinator decisions: fail closed, no new word lists.

- **R5-1** the "the <value>" prompt-anaphor provenance stored lines that prime the answer ("Misses that only the 2 survives the limit.", "Treats the 2 as the final value.", "Thinks the limit tends to the 2 in the argument, not 1."), costing leak retries against the deep cap. The exemption is REMOVED (no refinement): `confront_text_states_answer` is `detect_leak`'s strict final-answer/option rules with no provenance, and its `prompt` keyword is gone; a wrong reason containing the answer's value in any form is refused at drafting and withheld at serve — stored == servable still by construction. `_ANSWER_AFTER` stays: it closes a served-mode (tutor text) leak independent of the lint. Spec A77 amended in place. — 55052633.
  Before/after, all reviewer cases of rounds 2–5 (lint refused / serve withheld / disagree):

  | group | n | round 3 | round 4 | round 5 |
  |---|---|---|---|---|
  | states the answer | 31 | 25 / 31 / 6 | 31 / 31 / 0 | 31 / 31 / 0 |
  | "the <prompt value>" (5 round-4 honest + 9 lint5 primers) | 14 | — | 1 / 1 / 0 (13 stored) | 14 / 14 / 0 |
  | honest, no answer token (incl. lint5's "Treats the true in the prompt …" for answer False) | 7 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |
  | honest intent, names the value | 10 | 3 / 10 / 7 | 10 / 10 / 0 | 10 / 10 / 0 |

  The 5 "Ignores the 2."-style honest texts are now re-drafted (accepted).
- **R5-2** the class debt was paid by the first same-class item (a due review item), so the loop twin after it was full weight. Now there is no paid state: within `RECHECK_RELEASE_WINDOW_HOURS` after a release on a node, EVERY graded item of the released isomorph class is a re-check; the "next item after a release" rule stays. Rationale in A76: every class-mate carries the copy risk; cost = slower credit on that class alone for 24 h. — 6f1347bb.
- **R5-3** a released item whose `check_items` row is gone opened no debt. Fail closed: an unreadable released row owes on EVERY class of the node for the window (and a release owes on a graded item whose own class is unknown). No migration. Spec A76 amended in place. — 6f1347bb.
- Suite 8036 passed, 140 skipped; replay `run_all` 16/16 PASS; $0 live.

## Open questions for the series owner

1. Should `quiz`'s `read_misconceptions_for_course` switch to `rollup()` (it would need the course → graph_nodes join, not offerings; the consent check at `graph_read.py:516` stays)? Took: untouched.
2. Should `misconception_rollup` also feed `offering_concept_stats.common_misconceptions`? Took: no.
3. Should the probe and the review feed the rule (they call `grade_answer` without a loop state)? Took: only the check route. (The re-check-after-release rule, A76, is a separate matter: since fix round 3 all three grade with it.)
4. `match_wrong_reason` is a Jev candidate (A24, PKG-15): with `prior` it makes no model call today, so a Jev backend would first need a reason to call it without `prior`.
5. Tighten the line's body length to cut deep retries (then re-record the three runs)? Took: diagnostic only.
6. Should a `slip` after a recorded misconception `resolve()` the row? Took: no (spec names no resolve rule).
7. (Resolved in the fix round: CLAUDE.md lists `misconceptions.evidence_text`.)

## Post-hoc changes

(Appended by later packages that modified this package's code. Format: `PKG-MM <date>: <what> — commit <sha>`.)

## Ledger rows to add (coordinator)

- `| 10 | misconceptions | done | feat/learning-loop-10-misconceptions | <this branch's head> | tests/test_learning_misconceptions.py 94 (+ appended to 7 modules); suite 7842 passed / 138 skipped; run_all replay 16/16 PASS | A75 | HANDOFF-10.md |` — PKG-10's own commits: aea56f9b (inv 17), 63f650ac (migration), 91ad538e (module), 3aa02b5f (carry), ad52bfab (eval).
- `verified` rows for 05, 05b, 06, 07, 09 (State of the world green at 989e6733: full suite 7705 passed / 138 skipped).
- `reopened` rows: 03 (1cb9d6e9), 05 (50094f1a, 3f0062e3, e0235398, f1fa4614), 05b (tests only, 50094f1a), 06 (2b796e4c), 07 (788f6249, b589620a, c5b70a42, 726b614e, e4b29423), 09 (c5efdec0).
