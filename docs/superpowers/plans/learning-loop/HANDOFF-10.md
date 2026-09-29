# HANDOFF-10 — misconceptions

Written by the session that executed `PKG-10-misconceptions.md` (worktree `sapling-wt-10`, branch `feat/learning-loop-10-misconceptions`, cut from `feat/learning-loop` at 989e6733). Read by every later package that depends on 10. Keep every heading, even if the answer is "none". **LEDGER.md is not touched here** (session rule: the coordinator writes the ledger rows — see "Ledger rows to add" at the end).

## What changed

Every graded explicit submission on the loop check route now runs the spec §3.3 slip / misconception / novice rule over the session's attempts on that concept. The `wrong_key` that enters the rule comes only from `decisions.match_wrong_reason`, called with the grader's own `GradeResult` as `prior` (no model call, never called without it), filtered by PKG-05's unchanged A22 option rule and accepted only when it is a key the item lists and is identifier-shaped. A keyed `misconception` verdict marks one row per (student, node, key) in the new `misconceptions` table; the check route writes it (`evidence_text` = the text the grader saw, encrypted) AFTER its one `flush_pending`, under the grading claim, and sets a confrontation marker in `sessions.loop_state`. The next model turn with room for it (answer released, or model ceiling ≥ H4) on a tier whose eval passes (`CONFRONT_TIERS = {deep}`) carries a field-mapped confrontation line after the phase instruction, is routed deep (`misconception_active`, A15, downgrades unchanged) and clears the marker. After an `unknown` verdict `_activate_next_item` re-asks an isomorph (`policy.next_isomorph`) from its own servable candidates. The learner brief lists the student's open misconception keys from the table (then the closes'), and the session close feeds `build_close` the open keys on the session's evidence nodes. A class rollup exists as a SECURITY DEFINER SQL function (course concept_key + wrong_key, ≥ 5 distinct students, service_role only), reachable only from backend code (inv 17). A served-path eval dataset (`misconception_confront`, 7 cases × deep and standard, three fresh recordings each) decides which tier may carry the line.

## Symbols added

- `backend/learning/misconceptions.py` (was a stub):
  - `Verdict` (= `learning.evidence.MisconceptionVerdict`: `none|unknown|slip|misconception|gap|not_known|novice`), `KEY_PATTERN` (`[a-z0-9][a-z0-9_]{0,63}`), `is_key(key) -> bool`.
  - `Attempt` (pydantic, `extra="forbid"`): `question_hash, node_id, correct, wrong_key, confidence (0..1, STUDENT-stated), difficulty, idk, isomorph_of` — no free text.
  - `slip_or_misconception(history: list[Attempt]) -> Verdict` — pure, one node's history (ValueError on mixed nodes), first match wins (PKG-10 Behaviour 2).
  - `attempts_of(loop_state) -> list` (the live log; a malformed stored value is replaced by `[]`), `attempts_for_node(log, node_id) -> list[Attempt]` (skips malformed rows), `confront_of(loop_state) -> dict | None` (a malformed/incomplete marker or a non-identifier key reads as None), `set_confront(loop_state, marker | None)`, `carry(loop_state, diagnosis | None)` (the route's CAS mutate: appends the attempt, sets the marker, or clears the marker it cleared only while the fresh document still holds that same marker).
  - `record(user_id, node_id, check_item_id, wrong_key, evidence_text) -> dict` (open-row insert-or-increment; `evidence_text` encrypted here; a non-identifier key is refused with no read; `{}` on any DB error; the log line carries no student text), `resolve(user_id, node_id, wrong_key) -> int` (no caller yet), `open_for(user_id, node_ids) -> [{node_id, wrong_key, count}]` (count desc, identifier keys only, no read for `[]`, `[]` on error, never reads `evidence_text`), `rollup(course_id) -> list[dict]` (`rpc("misconception_rollup", …)`, `[]` on error; backend-only).
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
- `CLAUDE.md`'s encrypted-column list is NOT updated with `misconceptions.evidence_text` (session rule: this session does not edit CLAUDE.md) → coordinator item.

## Known gaps

- Student-stated confidence is `None` (A16's body has no confidence field; post-series reason/confidence tier), so only the two-isomorph path yields `misconception` today, and `gap` never fires on the served path.
- A misconception recorded mid-session reaches the learner brief only from the next session (the brief is built once, A19); in-session the confrontation line carries it.
- A marker waits while no turn has room (develop-band teach turns sit below H4; soft budget/deep cap downgrade to standard): the confrontation may never happen in that session; the store row and the next brief still carry the key.
- `resolve()` has no caller (PKG-12's review grading or PKG-14's post-test is the natural one); `rollup()` has no caller (instructor surface / quiz-agent switch are open questions).
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

## Open questions for the series owner

1. Should `quiz`'s `read_misconceptions_for_course` switch to `rollup()` (it would need the course → graph_nodes join, not offerings; the consent check at `graph_read.py:516` stays)? Took: untouched.
2. Should `misconception_rollup` also feed `offering_concept_stats.common_misconceptions`? Took: no.
3. Should the probe and the review feed the rule (they call `grade_answer` without a loop state)? Took: only the check route.
4. `match_wrong_reason` is a Jev candidate (A24, PKG-15): with `prior` it makes no model call today, so a Jev backend would first need a reason to call it without `prior`.
5. Tighten the line's body length to cut deep retries (then re-record the three runs)? Took: diagnostic only.
6. Should a `slip` after a recorded misconception `resolve()` the row? Took: no (spec names no resolve rule).
7. CLAUDE.md's encryption list gains `misconceptions.evidence_text` (coordinator).

## Post-hoc changes

(Appended by later packages that modified this package's code. Format: `PKG-MM <date>: <what> — commit <sha>`.)

## Ledger rows to add (coordinator)

- `| 10 | misconceptions | done | feat/learning-loop-10-misconceptions | <this branch's head> | tests/test_learning_misconceptions.py 94 (+ appended to 7 modules); suite 7842 passed / 138 skipped; run_all replay 16/16 PASS | A75 | HANDOFF-10.md |` — PKG-10's own commits: aea56f9b (inv 17), 63f650ac (migration), 91ad538e (module), 3aa02b5f (carry), ad52bfab (eval).
- `verified` rows for 05, 05b, 06, 07, 09 (State of the world green at 989e6733: full suite 7705 passed / 138 skipped).
- `reopened` rows: 03 (1cb9d6e9), 05 (50094f1a, 3f0062e3, e0235398, f1fa4614), 05b (tests only, 50094f1a), 06 (2b796e4c), 07 (788f6249, b589620a, c5b70a42, 726b614e, e4b29423), 09 (c5efdec0).
