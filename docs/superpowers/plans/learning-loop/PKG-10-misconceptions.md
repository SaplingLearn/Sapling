# PKG-10 misconceptions — Learning Loop series (13 of 17)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> You are a fresh session. Nothing outside this file, `docs/superpowers/plans/learning-loop/LEDGER.md`, the hand-offs it names, and the files this prompt lists is known to you. Do not infer intent from chat history you do not have. Do not read the whole research corpus; read the sections named below.

## Package id + goal

**PKG-10 `misconceptions`.** After this package: every graded explicit submission (`agents/tools/check.py::grade_answer`, spec §13 A16) is run through the slip / misconception / novice rule (spec §3.3) over the session's attempts on that concept; a `wrong_key` enters the rule only when the student's reason matched it, and it comes only from `services/decisions.py::match_wrong_reason` called with the grader's result as `prior` (A22/A24 — the gemini backend reuses the grader's `matched_wrong_key`, so there is no extra model call; the `mc_reason` option → key map is never recorded on its own); a `misconception` verdict lands one encrypted row per (student, concept, wrong key) in a new `misconceptions` table, incremented on repeat; the loop tutor's next model turn is told to confront a recorded misconception with a contradiction rather than a correction, and that turn routes to the deep tier (`policy.model_tier(..., misconception_active=True)`, A15); the learner brief (built once per session, A19) carries the student's open misconceptions; and a class rollup exists as a SQL function that returns nothing below `MISCONCEPTION_ROLLUP_MIN_USERS` distinct students and is callable only from the backend — never registered on a tutor (ADR 0023 §5). `tests/test_learning_misconceptions.py` proves the rule table, the store, the encryption, the seam-matched key, the rollup call shape, and that no tutor can reach the rollup.

Branch: `feat/learning-loop-10-misconceptions`. PR title: `feat(learning): PKG-10 misconceptions`.

Depends on (spec §14): **05, 05b, 06, 07, 09** — `grade_answer` and its `GradeOutcome` (05), `decisions.match_wrong_reason` (05b), `policy.LoopState`, `policy.model_tier` and `sessions.loop_state` (06), the loop route's turn assembly and item selection (07), the learner brief (09). Reopens (post-hoc, separate first commits; planned in the spec §13 header): PKG-03 (`Evidence.verdict`/`wrong_key`), PKG-06 (`policy.next_isomorph`, loop-state `attempts`/`confront`), PKG-05 (the hook and the seam-matched key in `grade_answer`), PKG-07 (the confrontation line, `misconception_active` and the isomorph re-ask in `routes/learn_loop.py`), PKG-09 (`learner_brief._open_misconception_keys` reads `open_for`).

## Read before you start (in this order)

0. `docs/superpowers/specs/2026-09-26-learning-loop-design.md` **§13 Amendments log** — in force; where this file and §13 disagree, §13 wins. Re-read it before Task 1. The rows that bind this package: **A22** (a `wrong_key` enters the rule only from a matched reason; the `mc_reason` option → key map is a prior, never a record on its own), **A24** (`match_wrong_reason` on the decision seam), **A15** (a misconception-confrontation turn is a `deep` turn), **A16** (the hook lives in `grade_answer`; no `graded_check_tool` exists), plus A19 (the learner brief is built once per session and stored), A2 (check items key on `concept_key`; the student's node comes from the caller), A6 (`GAP_CONFIDENCE_MAX` with `≤`, `NOVICE_FLOOR_IDK`), A1 (`idk` is a flag, not a channel) A23 (revealed items and the post-test reserve are never re-served), **A29** (the class rollup groups by course `concept_key` + `wrong_key`, never by the per-user `node_id`) and A27 (the isomorph re-ask goes inside PKG-07's `_activate_next_item`, the only code that sets `loop_state["active"]`).
1. The same spec's §3.5–§3.6 (cost/routing/decision constants — the `LOOP_MODEL_TIER` row that names "misconception confrontation (PKG-10)" and the soft/deep-cap downgrades that follow it; §3.6 backend selection for `match_wrong_reason`), §7 (two-phase gate), §8 (invariants 13–29 — this package adds 17 and keeps 14, 22, 23, 25, 26 and 28 green), §14 (order and dependencies).
2. `docs/superpowers/plans/learning-loop/LEDGER.md` — a package's state is its LATEST row (README "Ledger reading"); refuse to start if any earlier package's latest row is `blocked` or `in-progress`. The latest rows of 00–09, 05b and 06b must be `done`, `verified` or `reopened` (spec §14: 05, 05b, 06, 07 and 09 are this package's dependencies, and packages run strictly one at a time).
3. `docs/superpowers/plans/learning-loop/HANDOFF-03.md`, `HANDOFF-04.md`, `HANDOFF-05.md`, `HANDOFF-05b.md`, `HANDOFF-06.md`, `HANDOFF-07.md`, `HANDOFF-09.md` — §Symbols added (and §Post-hoc changes) of each. You need from them: the `Evidence` model's file and field list, including PKG-05's `grader_backend` (03); `CheckItem`'s fields (`concept_key`, `question_hash`, `difficulty`, `format`, `options`, and `common_wrong: list[WrongReason(key, text)]` — the decrypted `common_wrong_json` column) and the check-item reader in `services/check_item_service.py` (04); `grade_answer`'s canonical signature, the `GradeOutcome` fields, the private `_record` / `_wrong_key` helpers and `CheckAnswer` (05); `decisions.match_wrong_reason`'s signature, the `WrongReasonState` fields, the `Pick` result, what each backend does with `prior`, and how `grade_answer` holds the grader's result after the PKG-05b reopen (05b); `policy.LoopState` with its `to_json`/`from_json` and `policy.model_tier`'s signature (06); the check-answer handler (`_grade_submission` and the fresh `SaplingDeps` it hands `grade_answer`), the per-turn user-message assembly and its one `policy.model_tier(...)` call, the item-selection site, the check-item read (`get_check_item`), and how the loop state is loaded onto `deps.loop_state` and saved — PKG-07 carries the JSON document and records its `LoopState` mapping (07); `learner_brief.build_brief`, `store_brief`, the `_open_misconception_keys` hook, and `close_session`'s `build_close(..., misconception_keys, ...)` call (09).
4. `CLAUDE.md` §Conventions (Supabase only via `table()`/`rpc()`, encryption at write boundaries, `report_empty_result` for agent read tools) and §Gotchas (encrypted columns). The "Do not" list repeats what applies.
5. `docs/superpowers/specs/2026-09-26-learning-loop-design.md` §3.3 "Slip / misconception / novice rule" (the six verdicts and the A22 `wrong_key` bullet), §3.4 (`MISCONCEPTION_ROLLUP_MIN_USERS`, `LEARNER_BRIEF_MAX_MISCONCEPTIONS`), §4 "PKG-10" block (DDL, verbatim), §4's encryption paragraph (`evidence_text` is encrypted; `wrong_key` is the plaintext key; decrypted text only in memory, including before any decision-seam state), §5 (`Evidence`, incl. `verdict`/`wrong_key`), §7 (flag), §8 invariants 1, 7, 8, 9, 14, 17, 25, 28.
6. `docs/decisions/0023-tutor-graph-retrieval-seam.md` §Decision item 5 — why a class-aggregate read stays off the tutor until consent is code-enforced. This package keeps that stance: the rollup is a backend function with no agent tool.
7. Research, by heading: `docs/research/learning-loop/AI tutor learning loop research.md` §"Slip, misconception, or novice: three different responses" (≈ lines 86–88; the rule's evidence basis — FCI "never interpret single items", Lehman 2013 contradiction-induced confusion) and §"Prioritized recommendations for Sapling" item 9 (≈ line 173, the n ≥ 5 floor). `docs/research/learning-loop/ZPD lever tradeoffs and upgrades.md` §"Sapling ZPD policy spec" EVIDENCE MAPPING block (≈ lines 205–215: "confidence / reason tier → diagnosis only … never a hint gate") and table row 11 (≈ line 83, confidence tiers separate misconception from ignorance).
8. Code you will mirror or modify:
   - `backend/agents/tools/check.py` (PKG-05, reopened by PKG-05b and PKG-06b) — `grade_answer`, `GradeOutcome`, `_record`, `_wrong_key`; `backend/services/decisions.py` (PKG-05b) — `match_wrong_reason`, `WrongReasonState`, `Pick`; `backend/learning/policy.py` (PKG-06) — `LoopState`, `model_tier`; `backend/learning/loop_state_store.py` (PKG-06); `backend/routes/learn_loop.py` (PKG-07/08/09); `backend/learning/learner_brief.py` (PKG-09).
   - `backend/agents/tools/graph_read.py:372–575` — `read_misconceptions_for_course` / `_tool`: the existing class-aggregate read, its per-offering keyspace, and the consent check at `:516` (`share_class_context` → `[]`). Read it to understand why the rollup must not become a tutor tool here; you do not modify it.
   - `backend/services/course_context_service.py:292–316` — the existing `common_misconceptions` rollup source (quiz-context free text, hash-gated). The new table is a different, keyed source; the two coexist until PKG-14 decides.
   - `backend/services/chunk_visibility.py:1–140` — code-enforced consent precedent (`shares_class_context` fails closed). The rollup's "nothing below the floor" is the same posture: enforced in SQL, not in a prompt.
   - `backend/db/connection.py:235–240` — `rpc(function_name, params) -> list`.
   - `backend/db/migrations/20260921041555_canopy_active_users.sql` — the house model for a backend-only SQL function (comment style, REVOKE/GRANT, `NOTIFY pgrst, 'reload schema'`).
   - `backend/services/encryption.py:84–100` — `encrypt_if_present` / `decrypt_if_present`.
   - `backend/tests/test_graph_service.py:25–67` — `_mock_table` / `_cached_mock_table`; `backend/tests/test_internal_metrics_routes.py:78–80` — patching `rpc` on the importing module; `backend/tests/conftest.py:23` (`ENCRYPTION_KEY` is set for tests) and `:254–290` (`_hermetic_supabase_client`).
   - `backend/learning/params.py` (PKG-01) — confirm which of this package's constants already exist (§Named constants).
   - `backend/agents/chat_tutor.py:152–168` — `_build_tools()`; `backend/agents/loop_tutor.py` (PKG-07) — the loop tool list. The source-scan test reads both.

## State of the world

Run every row before Task 1. PKG-00's block, then the PKG-05, PKG-05b, PKG-06, PKG-07 and PKG-09 blocks (this package's spec §14 dependencies), verbatim from each package's hand-off Verify block (the series' canonical blocks).

| check | command | expected |
|---|---|---|
| PKG-00 gate | `cd backend && venv/bin/python -m pytest tests/test_learning_gate.py -q` | `13 passed` |
| PKG-00 invariants | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q` | `4 passed, 8 skipped (later packages raise the passed count)` — expect more passed now; zero failures |
| PKG-00 deps/settings/migration | `cd backend && venv/bin/python -m pytest tests/test_learning_deps.py tests/test_learning_settings_flag.py tests/test_learning_loop_beta_migration.py -q` | all passed |
| PKG-00 flag | `grep -n "^LEARNING_LOOP_ENABLED" backend/config.py` | 1 hit |
| PKG-00 migration | `ls backend/db/migrations/*_learning_loop_beta.sql` | 1 file |
| PKG-05 grading helper | `cd backend && venv/bin/python -m pytest tests/test_learning_check_tool.py -q` | N passed (N ≥ 16) |
| PKG-05 grader slot | `grep -c '"grader"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py` | ≥ 1 each |
| PKG-05 second-opinion slot | `grep -c '"grader_second"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py` | ≥ 1 each |
| PKG-05 helper symbol | `grep -c "^async def grade_answer" backend/agents/tools/check.py` | 1 |
| PKG-05 migration | `ls backend/db/migrations/*_learning_grader_backend.sql` | 1 file |
| PKG-05 invariants | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_14 or inv_28"` | 2 passed |
| PKG-05 grader evals | `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/grader.py` | every evaluator ≥ baseline |
| PKG-05b seam | `cd backend && venv/bin/python -m pytest tests/test_learning_decisions.py -q` | N passed (N ≥ 12) |
| PKG-05b decision slot | `grep -c '"decision"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py` | ≥ 1 each |
| PKG-05b events | `grep -c '"decision\.' backend/services/events_service.py` | 3 |
| PKG-05b no typesafe import | `grep -rlE "^[[:space:]]*(import\|from)[[:space:]]+typesafe" backend --include=*.py --exclude-dir=venv --exclude-dir=tests \| wc -l` | 0 |
| PKG-05b invariants | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_24 or inv_25"` | 2 passed |
| PKG-05b decision evals | `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/decisions.py` | every evaluator ≥ baseline |
| PKG-05b ADR | `ls docs/decisions/*decision-seam*.md` | 1 file |
| PKG-06 policy | `cd backend && venv/bin/python -m pytest tests/test_learning_zpd_policy.py -q` | N passed (N ≥ 35) |
| PKG-06 policy symbols | `grep -cE "^def (ceiling\|band_control\|evidence_for_rung\|wheelspin\|model_tier\|context_policy)\(" backend/learning/policy.py` | 6 |
| PKG-06 ladder symbols | `grep -cE "^def (check_pose\|deterministic_content)\(" backend/learning/ladder.py` | 2 |
| PKG-06 events | `grep -c '"zpd\.' backend/services/events_service.py` | 6 |
| PKG-06 migration | `ls backend/db/migrations/*_learning_session_loop_state.sql` | 1 file |
| PKG-06 invariants | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_02 or inv_04 or inv_05"` | 3 passed |
| PKG-07 routes | `cd backend && venv/bin/python -m pytest tests/test_learn_loop_routes.py -q` | N passed (N ≥ 25) |
| PKG-07 mount | `grep -c "learn_loop" backend/main.py` | ≥ 1 |
| PKG-07 tutor slot | `grep -c '"loop_tutor"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py` | ≥ 1 each |
| PKG-07 tier slots | `grep -ohE '"loop_tutor(_lite\|_deep)?"' backend/agents/_providers.py \| sort -u \| wc -l` | 3 |
| PKG-07 legacy tool gate | `grep -c "learning_loop" backend/agents/chat_tutor.py` | ≥ 1 |
| PKG-07 invariants | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_15 or inv_22 or inv_23 or inv_26 or inv_27 or inv_29"` | 6 passed |
| PKG-07 tutor evals | `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/loop_tutor.py` | every evaluator ≥ baseline for every tier slot |
| PKG-09 close/brief | `cd backend && venv/bin/python -m pytest tests/test_learning_close_brief.py -q` | N passed (N ≥ 14) |
| PKG-09 migration | `ls backend/db/migrations/*_learning_session_close.sql` | 1 file |
| PKG-09 brief column | `grep -c "loop_brief" backend/db/migrations/*_learning_session_close.sql` | ≥ 1 |
| PKG-09 history trim | `grep -c "LOOP_HISTORY_TRIM_BLOCK" backend/routes/learn_loop.py` | ≥ 1 |
| PKG-09 event | `grep -c '"learn\.session_closed"' backend/services/events_service.py` | 1 |
| PKG-07/09 present (reopened here) | `ls docs/superpowers/plans/learning-loop/HANDOFF-07.md docs/superpowers/plans/learning-loop/HANDOFF-09.md` | 2 files |
| hermetic suite green | `cd backend && venv/bin/python -m pytest tests/ -q -x` | `… passed` (note the count N₀) |
| lint green | `cd backend && venv/bin/ruff check .` | `All checks passed!` |
| stub is still a stub | `wc -l backend/learning/misconceptions.py` | ≤ 5 lines (docstring only) |
| latest migration prefix | `ls backend/db/migrations \| tail -1` | a `2026…` file; your prefix must sort after it |

Rule: any red row → STOP. Diagnose, repair on this branch as commit `fix(learning-loop): repair pre-series base — <what>`, record the deviation in `LEDGER.md`, re-run all rows. Never build on a broken base. Mark each dependency `verified` in the ledger (a new row each for 05, 05b, 06, 07 and 09) once its rows are green.

## Spec

### Behaviour

1. **The rule is pure.** `learning.misconceptions.slip_or_misconception(history: list[Attempt]) -> Verdict` reads only typed attempts and constants. `history` is every attempt in the current session on ONE `node_id` (the student's `graph_nodes.id`, which `grade_answer`'s caller resolves — check items are course assets keyed on `concept_key`, A2), oldest first; the verdict describes the LAST attempt. `Attempt` fields: `question_hash: str`, `node_id: str`, `correct: bool`, `wrong_key: str | None` (only a key the student's reason matched — A22), `confidence: float | None` (the STUDENT's stated confidence, 0..1, `None` when not asked — never the grader's confidence, which is diagnosis-only per spec §3.3 and never enters this rule), `difficulty: int`, `idk: bool`, `isomorph_of: str | None` (the `question_hash` of the earlier attempt this one re-asks). `Verdict` is `Literal["none", "unknown", "slip", "misconception", "gap", "not_known", "novice"]` — the six spec §3.3 verdicts plus `none` for a plain correct answer with nothing to diagnose (see Deviations).
2. **Decision order** (first match wins; `last = history[-1]`):
   - `history` empty → `none`.
   - `last.correct and last.wrong_key` → `not_known` (right answer, wrong reason — spec §3.3 "treat as a miss").
   - `last.correct and last.isomorph_of` names an earlier attempt in `history` that was wrong → `slip`.
   - `last.correct` → `none`.
   - (last is wrong from here) `last.confidence is not None and last.confidence >= MISCONCEPTION_CONFIDENCE` → `misconception`.
   - `last.wrong_key` and the number of DISTINCT `question_hash` values among wrong attempts in `history` with that same `wrong_key` ≥ `MISCONCEPTION_MIN_ISOMORPHS` → `misconception` (two isomorphs, same key; a second wrong on the SAME hash does not count).
   - misses at difficulty 1 (`not correct and difficulty == 1`, idk included) ≥ `NOVICE_FLOOR_MISSES`, or idk attempts ≥ `NOVICE_FLOOR_IDK` ("repeated `idk`", spec §13 A6 — the same threshold PKG-08's `probe.novice_floor` uses) → `novice`.
   - `last.confidence is not None and last.confidence <= GAP_CONFIDENCE_MAX` → `gap` (spec §13 A6: "`gap` when stated confidence ≤ this").
   - otherwise → `unknown` (re-ask an isomorph).
   Misconception outranks novice deliberately: PKG-08's `probe.novice_floor()` owns probe exit on its own, so returning `misconception` here loses nothing there and gains the record.
3. **Store.** `record(user_id, node_id, check_item_id, wrong_key, evidence_text) -> dict` reads the open row for `(user_id, node_id, wrong_key)` (`resolved_at` is null); if found, `update` sets `count = count + 1`, `last_seen_at = now`, `check_item_id`, `evidence_text` (encrypted, latest wins); else `insert` a new row with `id = str(uuid.uuid4())`, `count = 1`. `evidence_text` passes through `encrypt_if_present` at the write boundary; `wrong_key` stays plaintext (it is the lookup key). Returns the row dict as written (with `evidence_text` still ciphertext — callers never need it back). `resolve(user_id, node_id, wrong_key) -> int` sets `resolved_at = now` on the open row(s); returns rows touched. `open_for(user_id, node_ids) -> list[dict]` returns `[{"node_id", "wrong_key", "count"}, ...]` for open rows, `count` descending, `node_ids` empty → `[]` with no read. None of the three raise on a DB error: log at WARNING, return `{}` / `0` / `[]` (fail closed, the store is a diagnosis input, never a gate).
4. **Rollup.** `rollup(course_id) -> list[dict]` = `rpc("misconception_rollup", {"p_course_id": course_id})` → rows `{"concept_key", "wrong_key", "users"}`, DB errors → `[]` + WARNING. The SQL groups by the COURSE concept (course, `concept_key`, `wrong_key`), never by `node_id`: `graph_nodes` rows are per user, so a per-node group holds one student and could never reach the `MISCONCEPTION_ROLLUP_MIN_USERS` distinct-user floor (spec §13 A29). `concept_key` is the SQL mirror of `services/graph_service._normalize_concept` (runs of whitespace become one space, trimmed, case-folded), so it equals `check_items.concept_key` (A2), and a consumer maps a row to items with `list_items(course_id, row["concept_key"])`. Backend-only. Not registered on `chat_tutor`, `loop_tutor`, or `quiz` in this package. `quiz`'s existing `read_misconceptions_for_course` may switch to this source later — out of scope; the hand-off records it as an open question.
5. **The hook in `grade_answer`** (post-hoc PKG-05; spec §13 A16 — there is no `graded_check_tool`, and nothing here is a tutor tool). Two changes inside `agents/tools/check.py`, both reached only on the paths where `grade_answer` appends evidence (idk, the numeric mismatch, a returned grade — never `unavailable`, never `deps.learning_loop is False`):
   - **The key** (A22/A24). `match_wrong_key(item, *, prior, answer_text, deps) -> str | None` is the ONLY source of a `wrong_key`: it builds `decisions.WrongReasonState(question=<decrypted item prompt>, answer=<the text the grader saw>, wrong={key: text, …})` from the item's decrypted `common_wrong` (`CheckItem.common_wrong`, PKG-04; no identifiers — invariant 25) and awaits `decisions.match_wrong_reason(state, deps=deps, prior=<the grader's GradeResult>)`. With `prior` given the gemini backend returns the grader's own `matched_wrong_key` and makes NO model call, so grading cost is unchanged; `match_wrong_reason` is never called without `prior` (that would be an extra `decision` run counted against `STUDENT_DAILY_GRADES`). A `Pick` whose value is `"none"` or a key the item does not list, an item with no listed keys (no call), or a seam exception → `None` with a WARNING (a lost key loses a diagnosis, never evidence, and never for only one outcome). `grade_answer` feeds this key — instead of `result.matched_wrong_key` — into PKG-05's unchanged `_wrong_key(...)` A22 filter, so an `mc_reason` wrong option still carries a key only when the matched reason equals that option's key; the option → key map alone never reaches the rule or the store.
   - **The rule.** PKG-05's `_record(deps, outcome, ev)` becomes `async` and, before it appends, awaits `apply_misconception_rule(deps, *, item, grade, evidence, answer_text) -> Verdict | None` (`deps`, not a `RunContext`): `grade` is the `GradeOutcome` being returned (its `wrong_key` is the filtered key above), `evidence` the built `Evidence` (its `node_id` is the student's node, its `correct`/`idk` the outcome), `answer_text` the text the grader saw. The hook returns `None` without reading or writing anything when `deps.learning_loop` is False or `deps.loop_state is None` (a caller that loads no loop state gets no rule). Otherwise it appends this attempt to the session attempt log (the loop state's `attempts`, via the one accessor in `learning/misconceptions.py`), computes the verdict over that node's attempts and returns it; on `misconception` with a key it calls `record(...)` (via `asyncio.to_thread`) and sets the loop state's `confront = {"node_id", "wrong_key", "check_item_id"}`; on `slip` (or any other verdict) it records nothing. `_record` stamps `verdict` and `wrong_key` onto the `Evidence` before `model_dump()` and sets `GradeOutcome.verdict` (new field, default `None`). `isomorph_of` for the new attempt = the `question_hash` of the most recent earlier attempt in the log on the same `node_id` with a different `question_hash`, else `None` (derived, no selection plumbing). `Attempt.confidence` is `None`: `CheckAnswer` carries no student confidence (A16's body has none), and `grade.confidence` is the grader's — never read here.
   - `verdict` and `wrong_key` ride the Evidence dict on `deps.pending_evidence` (spec §5); `apply_graph_update` does not journal them (no column, spec §4) — the durable record is the `misconceptions` row. `grade_answer` still never persists EVIDENCE (inv 14 unchanged: `check.py` imports no `db.connection`); the misconception store write is a diagnosis write through `learning.misconceptions.record`.
6. **Isomorph re-ask** (post-hoc PKG-06). `policy.next_isomorph(item, items) -> ItemLike | None` (PKG-06's `ladder.ItemLike` Protocol; `policy.py` never imports `learning.checks`): same `concept_key`, same `format`, same `difficulty`, different `question_hash`, first match in `items` order, else `None`. Pure. The site that makes a concept's next check item `active` — PKG-07's `_activate_next_item` (spec §9, §13 A27) — prefers `next_isomorph(last_item, candidates)` when the last verdict on that node was `unknown` (the loop state's `attempts` tail says so). `candidates` is the list the site already filtered — revealed hashes and the concept's post-test reserve are excluded there (A23) — and the call passes only its servable items (`[c for c in candidates if checks.is_servable(c)]`, §13 A34: an item without a `final_answer` is never activated, because every later turn's `detect_leak` needs one and raises `ValueError` without it; `select_item` filters the same way); `next_isomorph` never widens it.
7. **Confrontation** (post-hoc PKG-07). `_confrontation_line(loop_state) -> str | None` reads the loop state's `confront` (no mutation), resolves the wrong-key text from the check item's decrypted `common_wrong` and returns exactly `The student holds misconception "<text>": create a contradiction they must resolve; do not simply state the correction.`; no marker, item gone or key absent → `None`, no error. In the per-turn plan and assembly (PKG-07's `_LoopTurn.plan` and its message assembly — HANDOFF-07 confirms the names; it runs for the ONE feedback turn after `/check/answer` and for every later model turn): `line = _confrontation_line(state)`; the one `policy.model_tier(...)` call passes `misconception_active=line is not None` (A15: the confrontation turn is `deep`; `model_tier` still applies the soft-level and deep-cap downgrades of spec §3.5 — this package never overrides them); when the tier is not `none`, the line goes into THIS turn's user message right after the phase instruction (`phase_prefix`) and before the context blocks and `[STUDENT QUESTION]` — trusted, route-assembled text outside every untrusted envelope — and the marker is cleared. For the marker to exist on the check-answer path, PKG-07's `_grade_submission` hands `grade_answer` a `SaplingDeps` carrying `loop_state=state` (the state it already loads and saves right after grading). When the tier is `none` (hard budget level, template turn) the marker is kept for the next model turn. The line never enters the stored brief, the history or the system prompt (A19: the cacheable prefix stays stable).
8. **Learner brief** (post-hoc PKG-09). PKG-09's hook `learner_brief._open_misconception_keys(user_id, node_ids_in_play, closes) -> list[str]` is repointed: the `wrong_key`s of `open_for(user_id, node_ids_in_play)` first (count descending), then PKG-09's closes union, deduplicated, order preserved; PKG-09's `open misconceptions:` section renders them (≤ `LEARNER_BRIEF_MAX_MISCONCEPTIONS`, inside `LEARNER_BRIEF_MAX_CHARS`, unchanged). A failure omits the section (PKG-09's rule). The brief is built once per session and stored (A19), so a misconception recorded this session reaches the brief from the next session; within the session the confrontation line carries it. PKG-09's `routes/learn_loop.py::close_session` passes `[r["wrong_key"] for r in open_for(user_id, <the distinct node_ids of this session's evidence rows>)]` as `build_close`'s `misconception_keys` (PKG-09 left it `[]` "until PKG-10"), so the close record and the `learn.session_closed` count carry them.
9. **Flag.** Nothing here is reachable when `learning_loop_active` is False: `learning.misconceptions` is imported only by `agents/tools/check.py`, `routes/learn_loop.py` and `learning/learner_brief.py`; `grade_answer` has no caller on the legacy path and returns before the hook when `deps.learning_loop` is False; the migration adds a table and a function nobody on the legacy path reads. Test: source scan of importers + the hook's early return.

### Schema (exact)

Verbatim from spec §4 PKG-10 block, with the header comment and the trailing `NOTIFY` the house function-migration model adds (`20260921041555_canopy_active_users.sql`; a `NOTIFY` with no listener is a no-op).

```sql
-- <ts>_learning_misconceptions.sql
-- Learning loop series PKG-10: per-student misconception store fed by the
-- grader's matched wrong key (spec §3.3 rule, §4 PKG-10 block), plus the
-- class rollup. `evidence_text` is encrypted (services/encryption.py) and is
-- never filtered on; `wrong_key` is the plaintext key from common_wrong_json.
-- The rollup returns nothing below MISCONCEPTION_ROLLUP_MIN_USERS distinct
-- students (learning/params.py mirrors the literal below; the test pins them
-- equal) and is executable by service_role only — it is a backend function,
-- not a tutor tool (ADR 0023 §5).
CREATE TABLE IF NOT EXISTS misconceptions (
  id             text PRIMARY KEY,
  user_id        text NOT NULL,
  node_id        text NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
  check_item_id  text,
  wrong_key      text NOT NULL,             -- plaintext enum key from common_wrong_json
  evidence_text  text,                      -- encrypted
  count          int NOT NULL DEFAULT 1,
  first_seen_at  timestamptz NOT NULL DEFAULT now(),
  last_seen_at   timestamptz NOT NULL DEFAULT now(),
  resolved_at    timestamptz
);
CREATE INDEX IF NOT EXISTS misconceptions_user_node_idx ON misconceptions (user_id, node_id, wrong_key);
-- graph_nodes rows are per user, so the rollup groups by the COURSE concept, never by
-- node_id (A29). concept_key mirrors services/graph_service._normalize_concept (runs of
-- whitespace become one space, trimmed, case-folded) and equals check_items.concept_key
-- (A2). SQL lower() stands in for Python casefold(): they agree on ASCII names and
-- can differ on some non-ASCII characters (e.g. ß, which casefold expands).
CREATE OR REPLACE FUNCTION misconception_rollup(p_course_id text)
RETURNS TABLE (concept_key text, wrong_key text, users int)
LANGUAGE sql SECURITY DEFINER AS $$
  SELECT lower(btrim(regexp_replace(g.concept_name, '\s+', ' ', 'g'))), m.wrong_key,
         count(DISTINCT m.user_id)::int
  FROM misconceptions m JOIN graph_nodes g ON g.id = m.node_id
  WHERE g.course_id = p_course_id AND m.resolved_at IS NULL
  GROUP BY g.course_id, lower(btrim(regexp_replace(g.concept_name, '\s+', ' ', 'g'))), m.wrong_key
  HAVING count(DISTINCT m.user_id) >= 5
$$;
REVOKE ALL ON FUNCTION misconception_rollup(text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION misconception_rollup(text) TO service_role;
NOTIFY pgrst, 'reload schema';
```

If migration replay in the E2E lane aborts on a missing `anon`/`authenticated`/`service_role` role, replace the two grant lines with the guarded `DO $$ … $$` block from `20260921041555_canopy_active_users.sql` (same statements, role-existence checked) in a NEW migration, never by editing this one, and record the deviation.

### Named constants

| Name | Value | Spec ref | Owner |
|---|---|---|---|
| `MISCONCEPTION_CONFIDENCE` | 0.7 | §3.3 | PKG-01 (verify present; add if missing → Deviation) |
| `NOVICE_FLOOR_MISSES` | 3 | §3.3 | PKG-01 (verify present) |
| `NOVICE_FLOOR_IDK` | 2 † | §13 A6 ("repeated `idk`") | PKG-08 (verify present — `probe.novice_floor` uses it; add if missing → Deviation) |
| `MISCONCEPTION_ROLLUP_MIN_USERS` | 5 | §3.4 | PKG-01 (verify present); must equal the `HAVING` literal in the migration — pinned by test |
| `LEARNER_BRIEF_MAX_MISCONCEPTIONS` | 5 | §3.4 | PKG-01 (verify present); consumed by PKG-09's `open misconceptions:` section |
| `LEARNER_BRIEF_MAX_CHARS` | 1800 | §3.4 | PKG-01; the brief's existing bound, unchanged |
| `MISCONCEPTION_MIN_ISOMORPHS` | 2 | §3.3 "wrong on ≥ 2 isomorphs with the same `wrong_key`" | this package adds to `params.py` |
| `GAP_CONFIDENCE_MAX` | 0.4 † | §13 A6 (`gap` when stated confidence ≤ this; §3.3 names no cut-point) | this package adds to `params.py` unless PKG-01 already added A6's name (`grep -n "^GAP_CONFIDENCE_MAX = " backend/learning/params.py` first; never duplicate); mark † in the hand-off as an A/B candidate |

No cost or decision constant is added: the tier comes from PKG-06's `model_tier` (§3.5 `LOOP_MODEL_TIER`), the backend from PKG-05b's §3.6 selection. Every other number in this prompt lives in test code only.

### Invariants asserted by this package (spec §8 numbering)

- (7) `learning/misconceptions.py` reaches Supabase only through `from db.connection import rpc, table` — the existing `test_inv_07` covers it once the file exists.
- (8) the migration name matches the pattern and is never modified — `test_inv_08` covers it.
- (9) `evidence_text` carries no `UNIQUE` and no `eq.` filter — extend the migration test in this package (Task 3); `test_inv_09` (PKG-04) already scans for the column name — confirm it goes green, do not duplicate.
- **(17, new)** `test_inv_17_rollup_not_a_tutor_tool`: no file under `backend/agents/` mentions `misconception_rollup` or imports `rollup` from `learning.misconceptions`; `learning.misconceptions` is imported only by the three loop-only files in §Behaviour 9.
- Kept green, not rewritten: (14) `check.py` still imports no `db.connection`, no `RunContext`, no `Tool(`; (22) nothing here reads `model_pref`; (23) no new agent run site — `match_wrong_reason` with `prior` makes no model call, and the seam's own run site already checks the budget (PKG-06b); (25) `WrongReasonState` is built from item text and the answer only; (26) no new `flush_pending` caller; (28) the hook never runs on an `unavailable` grade, so no attempt is logged for either outcome.

### Error semantics

The store fails closed and never raises (WARNING + empty result). The rule is pure and total. No model call is added (`match_wrong_reason` always gets `prior`), so no ADR 0024 degrade path is touched; a seam failure or an unlisted key → `wrong_key=None` + WARNING, and the grade and its evidence are unchanged for either outcome. The grader's `unavailable` result (PKG-05: outage or second opinion unavailable; PKG-06b: the grader cap) short-circuits before the hook — no grade, no attempt, no verdict, for either outcome (invariant 28). A confrontation line is consumed only by a model-written turn: at the hard budget level (tier `none`) it waits.

### Events added

None. `learn.session_closed` (PKG-09) already carries `misconceptions`; this package feeds it through `open_for` in `close_session` (Behaviour 8), no new type. Each `match_wrong_reason` call emits PKG-05b's `decision.made` (expected; not a new type). The taxonomy pin test is untouched.

## Non-goals

- No tutor tool for the rollup (ADR 0023 §5). No change to `agents/tools/graph_read.py::read_misconceptions_for_course` or the quiz agent.
- No student-facing confidence UI and no confidence field on `CheckAnswer` (a post-series reason/confidence tier; until then `Attempt.confidence` is `None`).
- No new decision function, prompt or backend: `match_wrong_reason` is PKG-05b's and is always called with `prior`; the Jev backend is PKG-15 (post-series).
- No tier logic and no slot choice: `policy.model_tier` is PKG-06's; this package passes `misconception_active` and nothing else, and never reads `model_pref` (invariant 22).
- No `report_empty_result` on `open_for`: it is not an agent read tool and an empty list is the common healthy state, not a signal.
- No offering/enrollment resolution: `misconception_rollup` joins `graph_nodes.course_id` (the abstract course the graph keys on), exactly as spec §4 writes it.
- No instructor surface, no admin route, no frontend, no eval dataset (no prompt is authored here; the confrontation line is route-assembled context — see Self-check step 4).

## Tasks

### Task 1: Invariant 17 — the rollup is not a tutor tool

**Files:**
- Modify: `backend/tests/test_learning_loop_invariants.py`

**Interfaces:**
- Consumes: filesystem under `backend/agents/`, `backend/learning/`, `backend/routes/`, `backend/services/`.
- Produces: `test_inv_17_rollup_not_a_tutor_tool`.

- [ ] **Step 1: Append the test** (after the last `test_inv_` function; numbers are fixed by spec §8 — 13–16 and 22–29 belong to other packages, 18 is reserved; never renumber)

```python
MISCONCEPTIONS_IMPORTERS_ALLOWED = {
    "agents/tools/check.py",
    "routes/learn_loop.py",
    "learning/learner_brief.py",
}


def test_inv_17_rollup_not_a_tutor_tool():
    """ADR 0023 §5: a class-aggregate read never ships on a tutor behind a soft
    guard. The rollup is reachable only from backend code; nothing under
    agents/ may name it, and the misconception store is imported only by the
    loop-only surfaces."""
    agents_dir = BACKEND / "agents"
    for path in agents_dir.rglob("*.py"):
        text = path.read_text()
        assert "misconception_rollup" not in text, f"{path.relative_to(BACKEND)} names the rollup"
        assert not re.search(r"from\s+learning\.misconceptions\s+import\s+[^\n]*\brollup\b", text), (
            f"{path.relative_to(BACKEND)} imports rollup"
        )
    importers = set()
    for sub in ("agents", "routes", "services", "learning"):
        for path in (BACKEND / sub).rglob("*.py"):
            if re.search(r"^\s*(from|import)\s+learning\.misconceptions\b", path.read_text(), re.M):
                importers.add(str(path.relative_to(BACKEND)))
    assert importers <= MISCONCEPTIONS_IMPORTERS_ALLOWED, f"unexpected importers: {importers - MISCONCEPTIONS_IMPORTERS_ALLOWED}"
```

- [ ] **Step 2: Run it**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k inv_17`
Expected: `1 passed` (nothing imports the stub yet). It stays green through the package; Task 5 is the one that could break it.

- [ ] **Step 3: Commit**

```
git add backend/tests/test_learning_loop_invariants.py
git commit -m "test(learning-loop): PKG-10 — inv 17, misconception rollup is not a tutor tool

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 2: Post-hoc PKG-03 + PKG-06 — `Evidence.verdict`/`wrong_key`, loop-state `attempts`/`confront`, `policy.next_isomorph`

Reopened-package protocol: one commit per reopened package, before any PKG-10 code; that package's tests stay green; ledger rows `03 | reopened` and `06 | reopened`; "Post-hoc changes" appended to `HANDOFF-03.md` and `HANDOFF-06.md` in Task 7.

**Files:**
- Modify: `backend/learning/evidence.py` (PKG-03), `backend/learning/policy.py` (PKG-06: `next_isomorph`, and `LoopState` with its `to_json`/`from_json` — or the store file HANDOFF-07's mapping names)
- Test: `backend/tests/test_learning_evidence_apply.py` (append), `backend/tests/test_learning_zpd_policy.py` (append)

**Interfaces:**
- Produces: `Evidence.verdict: str | None = None`, `Evidence.wrong_key: str | None = None` (spec §5); loop-state keys `attempts: list[dict]` (default empty) and `confront: dict | None` (default `None`) that survive a load/save; `policy.next_isomorph(item, items)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_learning_evidence_apply.py`:

```python
def test_evidence_verdict_and_wrong_key_default_none():
    """PKG-10 post-hoc: two optional diagnosis fields; nothing existing changes."""
    from learning.evidence import Evidence

    e = Evidence(node_id="n1", channel="free_response", correct=False)
    assert e.verdict is None and e.wrong_key is None
    assert Evidence(node_id="n1", channel="mc", correct=True, verdict="slip", wrong_key="k1").verdict == "slip"
```

Append to `tests/test_learning_zpd_policy.py` (use the `CheckItem` constructor HANDOFF-04 names; items key on `concept_key`, spec §13 A2 — there is no `node_id` on a check item):

```python
def _item(qh, concept_key="derivative", fmt="free", difficulty=2):
    from learning.checks import CheckItem
    return CheckItem(id=f"ci-{qh}", course_id="c1", concept_key=concept_key, document_id=None, format=fmt,
                     difficulty=difficulty, prompt="p", reference_answer="r", rubric=[], common_wrong=[],
                     source_chunk_ids=[], question_hash=qh)


def test_next_isomorph_same_concept_format_difficulty_different_hash():
    from learning.policy import next_isomorph
    a, b, c, d, e = (_item("h1"), _item("h2"), _item("h3", concept_key="integral"), _item("h4", fmt="teachback"), _item("h5", difficulty=3))
    assert next_isomorph(a, [a, c, d, e, b]) is b


def test_next_isomorph_none_when_only_self_or_mismatches():
    from learning.policy import next_isomorph
    a = _item("h1")
    assert next_isomorph(a, [a, _item("h3", concept_key="integral"), _item("h4", fmt="teachback")]) is None
    assert next_isomorph(a, []) is None


def test_loop_state_round_trips_attempts_and_confront():
    """PKG-10 post-hoc: two sibling keys in the sessions.loop_state document,
    ids/enums/bools/numbers and the plaintext key only (no free text). A save
    through PKG-06's LoopState must never drop them."""
    from learning.policy import LoopState
    doc = LoopState().to_json()
    doc["attempts"] = [{"question_hash": "h1", "node_id": "n1", "correct": False, "wrong_key": "k1",
                        "confidence": None, "difficulty": 2, "idk": False, "isomorph_of": None}]
    doc["confront"] = {"node_id": "n1", "wrong_key": "k1", "check_item_id": "ci1"}
    back = LoopState.from_json(doc).to_json()
    assert back["attempts"] == doc["attempts"] and back["confront"] == doc["confront"]
    legacy = LoopState().to_json()
    legacy.pop("attempts", None)
    legacy.pop("confront", None)
    again = LoopState.from_json(legacy).to_json()
    assert again.get("attempts", []) == [] and again.get("confront") is None
```

If `CheckItem` requires fields the helper omits, extend `_item` — do not change `CheckItem`. If HANDOFF-06/07 show the store does not round-trip through `LoopState` (spec §4: `sessions.loop_state` goes through `learning/loop_state_store.py`), write this test against the store path they name instead — the assertion is the same: the two keys survive a load/save.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_evidence_apply.py tests/test_learning_zpd_policy.py -q -k "verdict or isomorph or attempts_and_confront"`
Expected: FAIL — `ValidationError … verdict … Extra inputs are not permitted` (or `AttributeError`), `ImportError: cannot import name 'next_isomorph'`, and `KeyError: 'attempts'` (the round trip drops the key).

- [ ] **Step 3: Implement**

`learning/evidence.py` — append two fields to `Evidence`, after `grader_backend` (PKG-05's reopen; spec §5 order):
```python
    verdict: str | None = None      # PKG-10 (slip/misconception rule result); None when the rule did not run
    wrong_key: str | None = None    # PKG-10; set only when the student's reason matched the key (A22)
```
PKG-03's `apply_graph_update` evidence path validates each dict as `Evidence` and journals named columns only; the two fields have no column (spec §4) and are not journaled. Confirm with the PKG-03 tests, change nothing there.

`learning/policy.py` — append (pure; annotate with PKG-06's `ladder.ItemLike` Protocol and `collections.abc.Sequence` — reuse the module's imports if present, never import `learning.checks`; no `str` parameter, keeping inv 2 and inv 4 green):
```python
def next_isomorph(item: ItemLike, items: Sequence[ItemLike]) -> ItemLike | None:
    """The first check item in `items` that re-asks `item` in a different
    surface: same concept_key, same format, same difficulty, different
    question_hash (spec §3.3 "re-ask an isomorph"; items are course assets
    keyed on concept_key, A2). None when there is none. `items` is already
    filtered by the caller (revealed hashes, post-test reserve — A23)."""
    for cand in items:
        if (
            cand.concept_key == item.concept_key
            and cand.format == item.format
            and cand.difficulty == item.difficulty
            and cand.question_hash != item.question_hash
        ):
            return cand
    return None
```

Loop state — at runtime PKG-07 carries the `sessions.loop_state` JSON document on `deps.loop_state` (a dict: `state.get("active")`, `state["revealed"]`, `state["tutor_requests"]`) and records in HANDOFF-07 how that document maps through PKG-06's `LoopState.to_json`/`from_json` in `loop_state_store` (PKG-07/08 carried `active`, `revealed`, `tutor_requests`, `deep_requests`, `probe`, `plan` that way). Add the top-level keys `"attempts"` (list of attempt dicts, default `[]`) and `"confront"` (dict or `None`, default `None`) through the SAME mechanism — for the typed `LoopState` that is `attempts: list[dict] = field(default_factory=list)`, `confront: dict | None = None` and their `to_json`/`from_json` lines; a document without the two keys loads with the defaults (every existing row keeps loading), a present-but-malformed value raises `ValueError` like the other keys. They hold ids/enums/bools/numbers and the plaintext `wrong_key` only, so the spec §4 "no free text" rule on `sessions.loop_state` holds. Task 4 writes the accessors in `learning/misconceptions.py` for the ONE runtime shape.

- [ ] **Step 4: Run the reopened packages' suites, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_evidence_apply.py tests/test_learning_zpd_policy.py tests/test_learning_loop_invariants.py tests/test_graph_service.py -q && venv/bin/ruff check .`
Expected: all passed (`inv_02` and `inv_04` still green — `next_isomorph` takes no `str` parameter); `All checks passed!`

- [ ] **Step 5: Commit — two commits, one per reopened package**

```
git add backend/learning/evidence.py backend/tests/test_learning_evidence_apply.py
git commit -m "fix(learning-loop): PKG-03 — Evidence.verdict and Evidence.wrong_key (post-hoc for PKG-10)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git add backend/learning/policy.py backend/tests/test_learning_zpd_policy.py
git commit -m "fix(learning-loop): PKG-06 — policy.next_isomorph and loop-state attempts/confront (post-hoc for PKG-10)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 3: Migration `learning_misconceptions`

**Files:**
- Create: `backend/db/migrations/<UTC>_learning_misconceptions.sql`
- Create: `backend/tests/test_learning_misconceptions.py` (the migration class; later tasks add the rest)

**Interfaces:**
- Produces: table `misconceptions`, index `misconceptions_user_node_idx`, function `misconception_rollup(text)`.

- [ ] **Step 1: Write the failing test**

```python
"""PKG-10: misconception store, the slip/misconception/novice rule, the class
rollup. Pure-rule tests need no fixtures; store tests patch
`learning.misconceptions.table`; the rollup test patches `.rpc`."""
from __future__ import annotations

import pathlib
import re
from unittest.mock import MagicMock, patch

import pytest

from learning import params

BACKEND = pathlib.Path(__file__).resolve().parents[1]
MIG_DIR = BACKEND / "db" / "migrations"


def _migration() -> str:
    hits = sorted(MIG_DIR.glob("*_learning_misconceptions.sql"))
    assert len(hits) == 1, f"expected exactly one learning_misconceptions migration, got {hits}"
    return hits[0].read_text()


class TestMigration:
    def test_rollup_floor_literal_matches_params(self):
        sql = _migration()
        assert f"HAVING count(DISTINCT m.user_id) >= {params.MISCONCEPTION_ROLLUP_MIN_USERS}" in sql

    def test_rollup_is_backend_only(self):
        sql = _migration()
        assert re.search(r"REVOKE ALL ON FUNCTION misconception_rollup\(text\) FROM PUBLIC, anon, authenticated;", sql)
        assert re.search(r"GRANT EXECUTE ON FUNCTION misconception_rollup\(text\) TO service_role;", sql)

    def test_rollup_excludes_resolved_rows(self):
        assert "m.resolved_at IS NULL" in _migration()

    def test_rollup_groups_by_course_concept_not_node(self):
        """Spec §13 A29: graph_nodes rows are per user, so a node_id group holds
        one student and never reaches the distinct-user floor. The rollup keys on
        the course concept (the A2 concept_key) and returns it, never a node id."""
        sql = _migration()
        fn = sql[sql.index("CREATE OR REPLACE FUNCTION misconception_rollup"):]
        key = r"lower(btrim(regexp_replace(g.concept_name, '\s+', ' ', 'g')))"
        assert "RETURNS TABLE (concept_key text, wrong_key text, users int)" in fn
        assert f"GROUP BY g.course_id, {key}, m.wrong_key" in fn
        assert "m.node_id," not in fn.split("FROM", 1)[0], "the rollup must not return a node id"
        assert "GROUP BY m.node_id" not in fn

    def test_rollup_concept_key_mirrors_normalize_concept(self):
        """The SQL key must equal the A2 key check_items use. Mirror the SQL
        expression (whitespace runs → one space, trim, lower) in Python. SQL
        lower() stands in for casefold(): they agree on ASCII names and can
        differ on some non-ASCII characters (e.g. ß) — spec §13 A29's known gap."""
        from services.graph_service import _normalize_concept

        for name in ["Derivative", "  chain   Rule ", "Chain\tRule\n", "L'Hôpital's Rule", "big-O  Notation"]:
            assert re.sub(r"\s+", " ", name).strip(" ").lower() == _normalize_concept(name)

    def test_evidence_text_has_no_unique(self):
        """Spec §4 encryption rule / inv 9: an encrypted column is never a key."""
        sql = _migration()
        col = re.search(r"^\s*evidence_text\s+text,.*$", sql, re.M)
        assert col, "evidence_text column missing"
        assert "UNIQUE" not in col.group(0).upper()
        assert "UNIQUE INDEX" not in sql.upper()
        assert not re.search(r"UNIQUE\s*\([^)]*evidence_text", sql)

    def test_table_and_index_are_idempotent(self):
        sql = _migration()
        assert "CREATE TABLE IF NOT EXISTS misconceptions" in sql
        assert "CREATE INDEX IF NOT EXISTS misconceptions_user_node_idx ON misconceptions (user_id, node_id, wrong_key)" in sql
        assert "CREATE OR REPLACE FUNCTION misconception_rollup(p_course_id text)" in sql
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_misconceptions.py -v`
Expected: FAIL — `expected exactly one learning_misconceptions migration, got []` (6 failures; `test_rollup_concept_key_mirrors_normalize_concept` reads no migration and already passes). If `params.MISCONCEPTION_ROLLUP_MIN_USERS` is missing, the module errors at import: add it to `params.py` now (§Named constants) and record the deviation against PKG-01.

- [ ] **Step 3: Write the migration**

Prefix from `date -u +%Y%m%d%H%M%S`; content is §Spec/Schema verbatim, header comment included.

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_misconceptions.py tests/test_learning_loop_invariants.py -q -k "Migration or inv_08 or inv_09" && venv/bin/ruff check .`
Expected: all passed; `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/db/migrations/*_learning_misconceptions.sql backend/tests/test_learning_misconceptions.py
git commit -m "feat(learning-loop): PKG-10 — misconceptions table and misconception_rollup(text)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 4: `learning/misconceptions.py` — rule, store, rollup; two params

**Files:**
- Modify: `backend/learning/params.py` (add `MISCONCEPTION_MIN_ISOMORPHS`, and `GAP_CONFIDENCE_MAX` unless PKG-01 already added it)
- Rewrite: `backend/learning/misconceptions.py` (replace the stub)
- Test: `backend/tests/test_learning_misconceptions.py` (append)

**Interfaces:**
- Consumes: `db.connection.table`, `db.connection.rpc`, `services.encryption.encrypt_if_present`, `learning.params`.
- Produces: `Attempt`, `Verdict`, `slip_or_misconception`, `record`, `resolve`, `open_for`, `rollup`, `attempts_of`, `confront_of`, `set_confront`, `attempts_for_node`.

- [ ] **Step 1: Write the failing tests** (append to the module)

```python
from learning.params import (
    GAP_CONFIDENCE_MAX,
    MISCONCEPTION_CONFIDENCE,
    MISCONCEPTION_MIN_ISOMORPHS,
    NOVICE_FLOOR_IDK,
    NOVICE_FLOOR_MISSES,
)


def _att(qh, *, correct=False, wrong_key=None, confidence=None, difficulty=2, idk=False, isomorph_of=None, node_id="n1"):
    from learning.misconceptions import Attempt
    return Attempt(question_hash=qh, node_id=node_id, correct=correct, wrong_key=wrong_key,
                   confidence=confidence, difficulty=difficulty, idk=idk, isomorph_of=isomorph_of)


def _fresh_loop_state():
    """The runtime shape of deps.loop_state: the sessions.loop_state JSON document
    PKG-07 carries (HANDOFF-07). Return `LoopState()` instead if HANDOFF-07 says
    the route holds the typed object — and write Task 4's accessors to match."""
    return {}


HIGH = MISCONCEPTION_CONFIDENCE
MID = (GAP_CONFIDENCE_MAX + MISCONCEPTION_CONFIDENCE) / 2
LOW = GAP_CONFIDENCE_MAX / 2
assert MISCONCEPTION_MIN_ISOMORPHS == 2, "rule table below enumerates two isomorphs"
assert NOVICE_FLOOR_IDK >= 2, "one idk alone must not be 'repeated idk'"

RULE_TABLE = [
    ("empty", [], "none"),
    ("plain correct", [_att("h1", correct=True)], "none"),
    ("wrong once, no confidence", [_att("h1", wrong_key="k1")], "unknown"),
    ("wrong once, mid confidence", [_att("h1", wrong_key="k1", confidence=MID)], "unknown"),
    ("wrong then right on isomorph", [_att("h1", wrong_key="k1"), _att("h2", correct=True, isomorph_of="h1")], "slip"),
    ("right on non-isomorph after wrong", [_att("h1", wrong_key="k1"), _att("h2", correct=True)], "none"),
    ("two isomorphs same key", [_att("h1", wrong_key="k1"), _att("h2", wrong_key="k1", isomorph_of="h1")], "misconception"),
    ("two isomorphs different keys", [_att("h1", wrong_key="k1"), _att("h2", wrong_key="k2", isomorph_of="h1")], "unknown"),
    ("two isomorphs, no matched key", [_att("h1"), _att("h2", isomorph_of="h1")], "unknown"),
    ("same hash twice same key", [_att("h1", wrong_key="k1"), _att("h1", wrong_key="k1")], "unknown"),
    ("wrong, confidence at threshold", [_att("h1", wrong_key="k1", confidence=HIGH)], "misconception"),
    ("wrong, confidence at threshold, no key", [_att("h1", confidence=HIGH)], "misconception"),
    ("wrong, low confidence", [_att("h1", wrong_key="k1", confidence=LOW)], "gap"),
    ("wrong, confidence at gap max (A6: <=)", [_att("h1", wrong_key="k1", confidence=GAP_CONFIDENCE_MAX)], "gap"),
    ("right answer wrong reason", [_att("h1", correct=True, wrong_key="k1")], "not_known"),
    ("novice: misses at difficulty 1", [_att(f"h{i}", difficulty=1) for i in range(NOVICE_FLOOR_MISSES)], "novice"),
    ("novice: repeated idk", [_att(f"h{i}", idk=True, difficulty=3) for i in range(NOVICE_FLOOR_IDK)], "novice"),
    ("one idk is not novice", [_att("h1", idk=True, difficulty=3)], "unknown"),
    ("below novice floor", [_att(f"h{i}", difficulty=1) for i in range(NOVICE_FLOOR_MISSES - 1)], "unknown"),
    ("misconception outranks novice", [_att(f"h{i}", difficulty=1, wrong_key="k1") for i in range(NOVICE_FLOOR_MISSES)], "misconception"),
    ("slip after novice-count misses still slip", [_att(f"h{i}", difficulty=1) for i in range(NOVICE_FLOOR_MISSES)] + [_att("hx", correct=True, isomorph_of=f"h{NOVICE_FLOOR_MISSES - 1}")], "slip"),
]


@pytest.mark.parametrize("label,history,expected", RULE_TABLE, ids=[r[0] for r in RULE_TABLE])
def test_rule_table(label, history, expected):
    from learning.misconceptions import slip_or_misconception
    assert slip_or_misconception(history) == expected


def test_rule_is_over_one_node_only():
    from learning.misconceptions import slip_or_misconception
    with pytest.raises(ValueError):
        slip_or_misconception([_att("h1", node_id="n1"), _att("h2", node_id="n2")])


def test_attempts_for_node_filters_and_keeps_order():
    from learning.misconceptions import attempts_for_node
    log = [_att("h1", node_id="n2").model_dump(), _att("h2").model_dump(), _att("h3").model_dump()]
    got = attempts_for_node(log, "n1")
    assert [a.question_hash for a in got] == ["h2", "h3"]


def test_loop_state_accessors_use_the_one_shape():
    """One accessor set over the runtime loop-state shape (Task 2); callers never branch on it."""
    from learning.misconceptions import attempts_of, confront_of, set_confront

    s = _fresh_loop_state()
    attempts_of(s).append(_att("h1").model_dump())
    assert attempts_of(s)[0]["question_hash"] == "h1"
    marker = {"node_id": "n1", "wrong_key": "k1", "check_item_id": "ci1"}
    set_confront(s, marker)
    assert confront_of(s) == marker
    set_confront(s, None)
    assert confront_of(s) is None


# ── store ──────────────────────────────────────────────────────────────────

def _cached_tables(data: dict):
    mocks: dict = {}

    def factory(name):
        if name not in mocks:
            m = MagicMock(name=name)
            m.select.return_value = data.get(name, [])
            m.insert.return_value = []
            m.update.return_value = []
            mocks[name] = m
        return mocks[name]

    return factory, mocks


def test_record_inserts_new_row_with_encrypted_evidence():
    from learning import misconceptions
    from services.encryption import decrypt_if_present

    factory, mocks = _cached_tables({"misconceptions": []})
    with patch.object(misconceptions, "table", side_effect=factory):
        misconceptions.record("u1", "n1", "ci1", "k1", "the derivative of x^2 is x")
    m = mocks["misconceptions"]
    m.insert.assert_called_once()
    row = m.insert.call_args[0][0]
    assert row["user_id"] == "u1" and row["node_id"] == "n1" and row["wrong_key"] == "k1"
    assert row["check_item_id"] == "ci1" and row["count"] == 1 and row["id"]
    assert row["evidence_text"] != "the derivative of x^2 is x"
    assert decrypt_if_present(row["evidence_text"]) == "the derivative of x^2 is x"
    m.update.assert_not_called()


def test_record_increments_open_row():
    from learning import misconceptions

    existing = {"id": "m1", "user_id": "u1", "node_id": "n1", "wrong_key": "k1", "count": 2, "resolved_at": None}
    factory, mocks = _cached_tables({"misconceptions": [existing]})
    with patch.object(misconceptions, "table", side_effect=factory):
        misconceptions.record("u1", "n1", "ci2", "k1", "again")
    m = mocks["misconceptions"]
    m.insert.assert_not_called()
    m.update.assert_called_once()
    payload, kwargs = m.update.call_args[0][0], m.update.call_args[1]
    assert payload["count"] == 3 and payload["check_item_id"] == "ci2" and "last_seen_at" in payload
    assert payload["evidence_text"] != "again"
    assert kwargs["filters"] == {"id": "eq.m1"}


def test_record_reads_only_open_rows_by_plaintext_keys():
    from learning import misconceptions

    factory, mocks = _cached_tables({"misconceptions": []})
    with patch.object(misconceptions, "table", side_effect=factory):
        misconceptions.record("u1", "n1", None, "k1", None)
    filters = mocks["misconceptions"].select.call_args[1]["filters"]
    assert filters == {"user_id": "eq.u1", "node_id": "eq.n1", "wrong_key": "eq.k1", "resolved_at": "is.null"}
    assert "evidence_text" not in filters


def test_record_never_raises(caplog):
    from learning import misconceptions

    boom = MagicMock()
    boom.select.side_effect = RuntimeError("pg down")
    with patch.object(misconceptions, "table", return_value=boom), caplog.at_level("WARNING"):
        assert misconceptions.record("u1", "n1", None, "k1", "x") == {}
    assert any("misconceptions.record" in r.getMessage() for r in caplog.records)


def test_resolve_marks_open_rows():
    from learning import misconceptions

    factory, mocks = _cached_tables({"misconceptions": [{"id": "m1"}]})
    mocks_holder = mocks
    with patch.object(misconceptions, "table", side_effect=factory):
        assert misconceptions.resolve("u1", "n1", "k1") == 1
    payload, kwargs = mocks_holder["misconceptions"].update.call_args[0][0], mocks_holder["misconceptions"].update.call_args[1]
    assert "resolved_at" in payload
    assert kwargs["filters"]["resolved_at"] == "is.null"


def test_open_for_returns_keyed_counts_desc_and_skips_empty_input():
    from learning import misconceptions

    rows = [
        {"node_id": "n1", "wrong_key": "k1", "count": 1},
        {"node_id": "n2", "wrong_key": "k9", "count": 4},
    ]
    factory, mocks = _cached_tables({"misconceptions": rows})
    with patch.object(misconceptions, "table", side_effect=factory):
        assert misconceptions.open_for("u1", []) == []
        got = misconceptions.open_for("u1", ["n1", "n2"])
    assert got == [{"node_id": "n2", "wrong_key": "k9", "count": 4}, {"node_id": "n1", "wrong_key": "k1", "count": 1}]
    sel = mocks["misconceptions"].select.call_args
    assert sel[1]["filters"]["node_id"] == "in.(n1,n2)" and sel[1]["filters"]["resolved_at"] == "is.null"
    assert "evidence_text" not in sel[0][0]


# ── rollup ─────────────────────────────────────────────────────────────────

def test_rollup_calls_rpc_with_course_id():
    from learning import misconceptions

    rows = [{"concept_key": "chain rule", "wrong_key": "k1", "users": 7}]  # course concept, never a node id (A29)
    with patch.object(misconceptions, "rpc", return_value=rows) as rpc:
        assert misconceptions.rollup("c1") == rows
    rpc.assert_called_once_with("misconception_rollup", {"p_course_id": "c1"})


def test_rollup_degrades_to_empty(caplog):
    from learning import misconceptions

    with patch.object(misconceptions, "rpc", side_effect=RuntimeError("no fn")), caplog.at_level("WARNING"):
        assert misconceptions.rollup("c1") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_misconceptions.py -q`
Expected: collection ERROR — `ImportError: cannot import name 'GAP_CONFIDENCE_MAX' from 'learning.params'` (or `'MISCONCEPTION_MIN_ISOMORPHS'` when PKG-01 already added A6's `GAP_CONFIDENCE_MAX`).

- [ ] **Step 3: Implement**

`learning/params.py` — append, next to the other §3.3 constants (skip `GAP_CONFIDENCE_MAX` if PKG-01 already added A6's name with this value):
```python
# PKG-10 (spec §3.3 "wrong on ≥ 2 isomorphs with the same wrong_key").
MISCONCEPTION_MIN_ISOMORPHS = 2
# PKG-10 † (spec §13 A6): spec §3.3 says "wrong with low confidence → gap"
# with no cut-point. Student-stated confidence at or below this is "low";
# above it and below MISCONCEPTION_CONFIDENCE is "unknown" (re-ask an
# isomorph). A/B candidate.
GAP_CONFIDENCE_MAX = 0.4
```

`learning/misconceptions.py`:
```python
"""Per-student misconception store and the slip / misconception / novice rule
(spec §3.3), plus the class rollup (spec §4 PKG-10, n ≥
MISCONCEPTION_ROLLUP_MIN_USERS in SQL).

The rule is pure: typed attempts in, one verdict out. A wrong_key reaches it
only when the student's reason matched that key (spec §13 A22). The store
fails closed. The rollup is a backend function — never a tutor tool (ADR 0023
§5; tests/test_learning_loop_invariants.py::test_inv_17).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel

from db.connection import rpc, table
from learning.params import (
    GAP_CONFIDENCE_MAX,
    MISCONCEPTION_CONFIDENCE,
    MISCONCEPTION_MIN_ISOMORPHS,
    NOVICE_FLOOR_IDK,
    NOVICE_FLOOR_MISSES,
)
from services.encryption import encrypt_if_present

logger = logging.getLogger("sapling.learning.misconceptions")

Verdict = Literal["none", "unknown", "slip", "misconception", "gap", "not_known", "novice"]

_ROW_COLS = "id,user_id,node_id,check_item_id,wrong_key,count,first_seen_at,last_seen_at,resolved_at"


class Attempt(BaseModel):
    """One graded attempt, as the session attempt log stores it (ids, enums,
    bools, numbers — no free text, so it may live in sessions.loop_state)."""

    question_hash: str
    node_id: str                      # the student's graph_nodes.id (items key on concept_key, A2)
    correct: bool
    wrong_key: str | None = None      # only a key the student's reason matched (A22)
    confidence: float | None = None   # STUDENT-stated, 0..1; never the grader's
    difficulty: int
    idk: bool = False
    isomorph_of: str | None = None


def attempts_for_node(log: list[dict], node_id: str) -> list[Attempt]:
    """The session attempt log filtered to one concept, order preserved."""
    return [Attempt.model_validate(a) for a in log if a.get("node_id") == node_id]


def slip_or_misconception(history: list[Attempt]) -> Verdict:
    """Spec §3.3. `history` = this session's attempts on ONE node, oldest
    first; the verdict is about the last one. First matching rule wins."""
    if not history:
        return "none"
    nodes = {a.node_id for a in history}
    if len(nodes) != 1:
        raise ValueError(f"slip_or_misconception takes one node's history, got {sorted(nodes)}")
    last = history[-1]
    by_hash = {a.question_hash: a for a in history[:-1]}
    if last.correct:
        if last.wrong_key:
            return "not_known"
        prior = by_hash.get(last.isomorph_of or "")
        if prior is not None and not prior.correct:
            return "slip"
        return "none"
    if last.confidence is not None and last.confidence >= MISCONCEPTION_CONFIDENCE:
        return "misconception"
    if last.wrong_key:
        hashes = {a.question_hash for a in history if not a.correct and a.wrong_key == last.wrong_key}
        if len(hashes) >= MISCONCEPTION_MIN_ISOMORPHS:
            return "misconception"
    floor_misses = sum(1 for a in history if not a.correct and a.difficulty == 1)
    idks = sum(1 for a in history if a.idk)
    if floor_misses >= NOVICE_FLOOR_MISSES or idks >= NOVICE_FLOOR_IDK:
        return "novice"
    if last.confidence is not None and last.confidence <= GAP_CONFIDENCE_MAX:
        return "gap"
    return "unknown"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record(user_id: str, node_id: str, check_item_id: str | None, wrong_key: str, evidence_text: str | None) -> dict:
    """Upsert-or-increment on (user_id, node_id, wrong_key) among OPEN rows.
    Read then insert/update: the index is not unique (a resolved row and a new
    open row may share the key), so PostgREST's on_conflict cannot express it.
    `evidence_text` is encrypted here, at the write boundary. Never raises."""
    try:
        t = table("misconceptions")
        rows = t.select(
            _ROW_COLS,
            filters={"user_id": f"eq.{user_id}", "node_id": f"eq.{node_id}", "wrong_key": f"eq.{wrong_key}", "resolved_at": "is.null"},
        ) or []
        enc = encrypt_if_present(evidence_text)
        if rows:
            row = rows[0]
            payload = {
                "count": int(row.get("count") or 0) + 1,
                "last_seen_at": _now(),
                "check_item_id": check_item_id,
                "evidence_text": enc,
            }
            t.update(payload, filters={"id": f"eq.{row['id']}"})
            return {**row, **payload}
        payload = {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "node_id": node_id,
            "check_item_id": check_item_id,
            "wrong_key": wrong_key,
            "evidence_text": enc,
            "count": 1,
        }
        t.insert(payload)
        return payload
    except Exception as exc:  # fail closed: a diagnosis input, never a gate
        logger.warning("misconceptions.record failed for %s/%s/%s: %s", user_id, node_id, wrong_key, exc)
        return {}


def resolve(user_id: str, node_id: str, wrong_key: str) -> int:
    """Mark the open row(s) for the key resolved. Returns rows touched."""
    try:
        t = table("misconceptions")
        filters = {"user_id": f"eq.{user_id}", "node_id": f"eq.{node_id}", "wrong_key": f"eq.{wrong_key}", "resolved_at": "is.null"}
        rows = t.select("id", filters=filters) or []
        if rows:
            t.update({"resolved_at": _now()}, filters=filters)
        return len(rows)
    except Exception as exc:
        logger.warning("misconceptions.resolve failed for %s/%s/%s: %s", user_id, node_id, wrong_key, exc)
        return 0


def open_for(user_id: str, node_ids: list[str]) -> list[dict]:
    """Open misconceptions for the student on the given nodes:
    [{node_id, wrong_key, count}], count descending. Never reads evidence_text."""
    ids = [n for n in node_ids if n]
    if not ids:
        return []
    try:
        rows = table("misconceptions").select(
            "node_id,wrong_key,count",
            filters={"user_id": f"eq.{user_id}", "node_id": f"in.({','.join(ids)})", "resolved_at": "is.null"},
        ) or []
    except Exception as exc:
        logger.warning("misconceptions.open_for failed for %s: %s", user_id, exc)
        return []
    out = [{"node_id": r["node_id"], "wrong_key": r["wrong_key"], "count": int(r.get("count") or 0)} for r in rows]
    return sorted(out, key=lambda r: -r["count"])


def rollup(course_id: str) -> list[dict]:
    """Class rollup via the SECURITY DEFINER SQL function: rows
    {concept_key, wrong_key, users}, keyed on the course concept (spec §13 A29;
    concept_key == check_items.concept_key), and only at or above
    MISCONCEPTION_ROLLUP_MIN_USERS distinct students (enforced in SQL).
    Backend-only. NOT a tutor tool. The quiz agent's
    `read_misconceptions_for_course` may switch to this source later (out of
    scope here)."""
    try:
        return rpc("misconception_rollup", {"p_course_id": course_id}) or []
    except Exception as exc:
        logger.warning("misconceptions.rollup failed for course %s: %s", course_id, exc)
        return []
```

Then add the loop-state accessors for the ONE runtime shape (every caller — the hook, the route — goes through these, never the keys directly, so a shape change stays in one file). Written for the JSON document PKG-07 carries on `deps.loop_state`; if HANDOFF-07 says the route holds the typed `LoopState` instead, write the attribute form — one branch, never both:
```python
def attempts_of(loop_state: dict) -> list[dict]:
    """The session attempt log (sessions.loop_state["attempts"], PKG-10).
    Created on first use; returns the live list, callers append to it."""
    return loop_state.setdefault("attempts", [])


def confront_of(loop_state: dict) -> dict | None:
    """The pending confrontation marker {node_id, wrong_key, check_item_id}, or None."""
    return loop_state.get("confront")


def set_confront(loop_state: dict, marker: dict | None) -> None:
    """Set (the hook) or clear (the route, after a model turn used it) the marker."""
    loop_state["confront"] = marker
```

If `table().update` in `db/connection.py` takes filters under a different keyword than `filters=`, match the real signature (`db/connection.py:24–118`) and fix the tests' `call_args[1]` reads to match — do not guess.

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_misconceptions.py tests/test_learning_loop_invariants.py -q && venv/bin/ruff check .`
Expected: all passed (`inv_07` now exercises the new file); `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/learning/params.py backend/learning/misconceptions.py backend/tests/test_learning_misconceptions.py
git commit -m "feat(learning-loop): PKG-10 — slip/misconception/novice rule, misconception store, rollup

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 5: Post-hoc PKG-05 — wire the rule into `grade_answer`

Reopened-package protocol: this is the `fix(learning-loop): PKG-05 — …` commit; `tests/test_learning_check_tool.py` and `tests/test_learning_decisions.py` stay green; ledger row `05 | reopened`; "Post-hoc changes" on `HANDOFF-05.md` in Task 7. PKG-05b's and PKG-06b's reopens of the same file are already in — build on them, never revert them.

**Files:**
- Modify: `backend/agents/tools/check.py`
- Test: `backend/tests/test_learning_misconceptions.py` (append), `backend/tests/test_learning_check_tool.py` (must stay green; touch only a pin that the new field or key moves, see Step 4)

**Interfaces:**
- Consumes: HANDOFF-05's `grade_answer`, `GradeOutcome`, `_record`, `_wrong_key`, `CheckAnswer`; HANDOFF-05b's `decisions.match_wrong_reason`, `WrongReasonState`, `Pick`, and the grader result `grade_answer` holds after the 05b reopen (the `prior`); HANDOFF-04's decrypted `CheckItem` (`id`, `prompt`, `common_wrong: list[WrongReason]`, `question_hash`, `difficulty`); `deps.learning_loop`, `deps.loop_state`, `deps.user_id`.
- Produces: `agents/tools/check.py::match_wrong_key(item, *, prior, answer_text, deps) -> str | None`; `agents/tools/check.py::apply_misconception_rule(deps, *, item, grade, evidence, answer_text) -> Verdict | None`; `GradeOutcome.verdict: str | None = None`; `_record` becomes `async` and stamps `Evidence.verdict`/`Evidence.wrong_key`.

- [ ] **Step 1: Write the failing tests** (append)

Read `tests/test_learning_check_tool.py` first and reuse by import its `SaplingDeps` builder, its decrypted-item factories and the way it patches the grader after PKG-05b's reopen; the names below (`_item`, `_mc_item`, `_patch_grader`) are placeholders — substitute the real ones. `_item(qh, wrong_keys=[...])` is a decrypted `free` item listing those keys in `common_wrong`; `h1`/`h2` share `concept_key`, format and difficulty 2. Patch the seam where `check.py` looks it up (`check_mod.decisions.match_wrong_reason` — PKG-05b imports the module). The three `grade_answer` tests patch no seam function: with `prior` both the gemini and the function backend reuse `prior.matched_wrong_key` with no model call (PKG-05b), so they exercise the real seam.

```python
# ── grade_answer hook (post-hoc PKG-05) ────────────────────────────────────
import asyncio  # hoist these two imports into the module's top import block if ruff flags E402
from unittest.mock import AsyncMock


def _loop_deps(state=None):
    from agents.deps import SaplingDeps
    return SaplingDeps(user_id="u1", course_id="c1", supabase=None, request_id="r", session_id="s1",
                       learning_loop=True, loop_state=_fresh_loop_state() if state is None else state)


def _prior_attempt(qh="h1", key="k1"):
    return dict(question_hash=qh, node_id="n1", correct=False, wrong_key=key,
                confidence=None, difficulty=2, idk=False, isomorph_of=None)


def _ev(correct, **kw):
    from learning.evidence import Evidence
    return Evidence(node_id="n1", channel="free_response", correct=correct, **kw)


def test_hook_records_on_misconception_and_sets_confront():
    from agents.tools import check as check_mod
    from agents.tools.check import GradeOutcome
    from learning.misconceptions import attempts_of, confront_of

    deps = _loop_deps()
    attempts_of(deps.loop_state).append(_prior_attempt())
    item = MagicMock(id="ci2", question_hash="h2", difficulty=2)
    grade = GradeOutcome(correct=False, confidence=0.9, matched_wrong_key="k1", wrong_key="k1")
    with patch.object(check_mod, "record", return_value={"id": "m1"}) as rec:
        verdict = asyncio.run(check_mod.apply_misconception_rule(
            deps, item=item, grade=grade, evidence=_ev(False), answer_text="x is 2"))
    assert verdict == "misconception"
    rec.assert_called_once_with("u1", "n1", "ci2", "k1", "x is 2")
    assert attempts_of(deps.loop_state)[-1]["isomorph_of"] == "h1"
    assert confront_of(deps.loop_state) == {"node_id": "n1", "wrong_key": "k1", "check_item_id": "ci2"}


def test_hook_slip_records_nothing():
    from agents.tools import check as check_mod
    from agents.tools.check import GradeOutcome
    from learning.misconceptions import attempts_of, confront_of

    deps = _loop_deps()
    attempts_of(deps.loop_state).append(_prior_attempt())
    item = MagicMock(id="ci2", question_hash="h2", difficulty=2)
    with patch.object(check_mod, "record") as rec:
        verdict = asyncio.run(check_mod.apply_misconception_rule(
            deps, item=item, grade=GradeOutcome(correct=True, confidence=0.9), evidence=_ev(True), answer_text="4"))
    assert verdict == "slip"
    rec.assert_not_called()
    assert confront_of(deps.loop_state) is None


def test_hook_is_inert_without_loop_or_loop_state():
    from agents.deps import SaplingDeps
    from agents.tools import check as check_mod
    from agents.tools.check import GradeOutcome

    off = SaplingDeps(user_id="u1", course_id="c1", supabase=None, request_id="r")
    no_state = SaplingDeps(user_id="u1", course_id="c1", supabase=None, request_id="r", learning_loop=True)
    item = MagicMock(id="ci1", question_hash="h1", difficulty=1)
    grade = GradeOutcome(correct=False, confidence=0.9, matched_wrong_key="k1", wrong_key="k1")
    with patch.object(check_mod, "record") as rec:
        for deps in (off, no_state):
            verdict = asyncio.run(check_mod.apply_misconception_rule(
                deps, item=item, grade=grade, evidence=_ev(False), answer_text="?"))
            assert verdict is None and deps.loop_state is None
    rec.assert_not_called()


def test_hook_uses_student_confidence_not_grader_confidence():
    """Spec §3.3: the grader's confidence is diagnosis-only and never enters the
    rule. A grader-confident wrong answer with no student confidence is `unknown`."""
    from agents.tools import check as check_mod
    from agents.tools.check import GradeOutcome

    deps = _loop_deps()
    grade = GradeOutcome(correct=False, confidence=0.99, matched_wrong_key="k1", wrong_key="k1")
    with patch.object(check_mod, "record") as rec:
        verdict = asyncio.run(check_mod.apply_misconception_rule(
            deps, item=MagicMock(id="ci1", question_hash="h1", difficulty=2), grade=grade,
            evidence=_ev(False, confidence=0.99), answer_text="x"))
    assert verdict == "unknown"
    rec.assert_not_called()


# ── the key comes only from the decision seam (A22/A24) ────────────────────

def _wrong_item(keys=("k1",)):
    from learning.checks import WrongReason
    return MagicMock(id="ci1", prompt="What is d/dx x^2?", question_hash="h1", difficulty=2,
                     common_wrong=[WrongReason(key=k, text=f"text of {k}") for k in keys])


def test_match_wrong_key_calls_the_seam_with_prior():
    from agents.tools import check as check_mod

    prior = MagicMock(matched_wrong_key="k1")
    seam = AsyncMock(return_value=MagicMock(value="k1"))
    with patch.object(check_mod.decisions, "match_wrong_reason", seam):
        got = asyncio.run(check_mod.match_wrong_key(_wrong_item(), prior=prior, answer_text="it is x", deps=_loop_deps()))
    assert got == "k1"
    (state,), kwargs = seam.call_args
    assert kwargs["prior"] is prior
    assert state.question == "What is d/dx x^2?" and state.answer == "it is x"
    assert state.wrong == {"k1": "text of k1"}


@pytest.mark.parametrize("value", [None, "none", "", "zz_not_listed"])
def test_match_wrong_key_rejects_unavailable_none_and_unlisted_keys(value):
    """None = the seam reported the prior unavailable (PKG-05b); "none" = NO_MATCH."""
    from agents.tools import check as check_mod

    seam = AsyncMock(return_value=None if value is None else MagicMock(value=value))
    with patch.object(check_mod.decisions, "match_wrong_reason", seam):
        got = asyncio.run(check_mod.match_wrong_key(_wrong_item(), prior=MagicMock(), answer_text="a", deps=_loop_deps()))
    assert got is None


def test_match_wrong_key_no_listed_keys_no_call_and_seam_failure_is_none(caplog):
    from agents.tools import check as check_mod

    seam = AsyncMock(side_effect=RuntimeError("seam down"))
    with patch.object(check_mod.decisions, "match_wrong_reason", seam), caplog.at_level("WARNING"):
        assert asyncio.run(check_mod.match_wrong_key(_wrong_item(keys=()), prior=MagicMock(), answer_text="a", deps=_loop_deps())) is None
        seam.assert_not_called()
        assert asyncio.run(check_mod.match_wrong_key(_wrong_item(), prior=MagicMock(), answer_text="a", deps=_loop_deps())) is None
    assert any("match_wrong_reason" in r.getMessage() for r in caplog.records)


# ── through the real grade_answer ──────────────────────────────────────────

def test_grade_answer_two_isomorphs_same_matched_key_records_once(monkeypatch):
    """Two wrong free answers on two isomorphs whose reasons the grader matched
    to k1: the second is a misconception, recorded once; the Evidence dicts
    carry verdict and wrong_key."""
    from agents.tools import check as check_mod
    from agents.tools.check import CheckAnswer, grade_answer

    deps = _loop_deps()
    _patch_grader(monkeypatch, all_yes=False, matched_wrong_key="k1")
    with patch.object(check_mod, "record", return_value={"id": "m1"}) as rec:
        first = asyncio.run(grade_answer(_item("h1", wrong_keys=["k1"]), CheckAnswer(question_hash="h1", answer_text="x"),
                                         deps=deps, node_id="n1"))
        second = asyncio.run(grade_answer(_item("h2", wrong_keys=["k1"]), CheckAnswer(question_hash="h2", answer_text="x again"),
                                          deps=deps, node_id="n1"))
    assert (first.verdict, second.verdict) == ("unknown", "misconception")
    assert second.wrong_key == "k1"
    assert deps.pending_evidence[-1]["verdict"] == "misconception" and deps.pending_evidence[-1]["wrong_key"] == "k1"
    rec.assert_called_once()


def test_option_prior_alone_never_records(monkeypatch):
    """A22: an mc_reason wrong option keyed k1 whose reason matched nothing
    carries no key — twice, on two isomorphs, is still not a misconception."""
    from agents.tools import check as check_mod
    from agents.tools.check import CheckAnswer, grade_answer

    deps = _loop_deps()
    _patch_grader(monkeypatch, all_yes=False, matched_wrong_key="")
    with patch.object(check_mod, "record") as rec:
        for qh in ("h1", "h2"):
            out = asyncio.run(grade_answer(_mc_item(qh, wrong_option="B", option_key="k1"),
                                           CheckAnswer(question_hash=qh, selected_option="B", reason="because"),
                                           deps=deps, node_id="n1"))
            assert out.wrong_key is None and out.verdict == "unknown"
    rec.assert_not_called()


def test_unavailable_grade_logs_no_attempt_for_either_outcome(monkeypatch):
    """Invariant 28: no grade → no attempt, no verdict, no record — for a
    would-be-correct and a would-be-wrong answer alike."""
    from agents.tools import check as check_mod
    from agents.tools.check import CheckAnswer, grade_answer
    from learning.misconceptions import attempts_of

    deps = _loop_deps()
    _patch_grader(monkeypatch, unavailable=True)
    with patch.object(check_mod, "record") as rec:
        for text in ("the right answer", "a wrong answer"):
            out = asyncio.run(grade_answer(_item("h1", wrong_keys=["k1"]), CheckAnswer(question_hash="h1", answer_text=text),
                                           deps=deps, node_id="n1"))
            assert out.unavailable and out.verdict is None
    assert attempts_of(deps.loop_state) == [] and deps.pending_evidence == []
    rec.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_misconceptions.py -q -k "hook or match_wrong_key or grade_answer or option_prior or unavailable_grade"`
Expected: FAIL — `AttributeError: module 'agents.tools.check' has no attribute 'apply_misconception_rule'` (and `'match_wrong_key'`); the `grade_answer` tests fail on `GradeOutcome` having no `verdict`.

- [ ] **Step 3: Implement**

In `agents/tools/check.py` add `import asyncio`, a module `logger` if it has none, `from learning.misconceptions import Attempt, Verdict, attempts_for_node, attempts_of, record, set_confront, slip_or_misconception` (never `rollup` — inv 17), and `from services import decisions` unless PKG-05b's reopen already imports it (reuse its import; the tests patch the name where `check.py` looks it up). Never `from db.connection import` (inv 14). Then:

```python
async def match_wrong_key(item, *, prior, answer_text: str, deps: SaplingDeps) -> str | None:
    """PKG-10 (spec §13 A22/A24): the ONLY source of a wrong_key. The student's
    reason is matched against the item's listed wrong reasons through the
    decision seam. `prior` is the grader's result for this same answer, so the
    gemini backend reuses its matched_wrong_key with NO model call — never call
    the seam without it (that is an extra `decision` run against the grade cap).
    "none", an unlisted key, no listed keys, or a seam failure -> None: a lost
    key loses a diagnosis, never evidence, and never for only one outcome."""
    wrong = {w.key: w.text for w in item.common_wrong or [] if w.key}   # reuse PKG-05b's key→text builder if check.py has one
    if not wrong:
        return None
    state = decisions.WrongReasonState(question=item.prompt, answer=answer_text or "", wrong=wrong)
    try:
        pick = await decisions.match_wrong_reason(state, deps=deps, prior=prior)
    except Exception as exc:  # the seam has its own fallbacks; this is the last guard
        logger.warning("match_wrong_reason failed for item %s: %s", item.id, exc.__class__.__name__)
        return None
    if pick is None:  # unavailable (PKG-05b); never happens after a returned grade
        return None
    return pick.value if pick.value in wrong else None   # NO_MATCH ("none") is never a listed key


async def apply_misconception_rule(
    deps: SaplingDeps, *, item, grade: GradeOutcome, evidence: Evidence, answer_text: str | None
) -> Verdict | None:
    """PKG-10 (spec §3.3; A16: the hook lives in grade_answer). Append this
    attempt to the session attempt log, run the rule over this concept's
    attempts, and record a misconception. The key is grade.wrong_key — the
    seam-matched key after PKG-05's A22 option filter; the option -> key map
    alone never reaches here. Student-stated confidence only: CheckAnswer has
    none yet, and grade.confidence is the grader's, deliberately not read.
    None (inert) unless the loop is on and the caller loaded a loop state."""
    if not deps.learning_loop or deps.loop_state is None:
        return None
    log = attempts_of(deps.loop_state)
    node_id = evidence.node_id  # the student's graph node; items are course assets (A2)
    earlier = [a for a in log if a.get("node_id") == node_id and a.get("question_hash") != item.question_hash]
    attempt = Attempt(
        question_hash=item.question_hash,
        node_id=node_id,
        correct=bool(evidence.correct),
        wrong_key=grade.wrong_key,
        confidence=None,
        difficulty=int(item.difficulty),
        idk=bool(evidence.idk),
        isomorph_of=earlier[-1]["question_hash"] if earlier else None,
    )
    log.append(attempt.model_dump())
    verdict = slip_or_misconception(attempts_for_node(log, node_id))
    if verdict == "misconception" and grade.wrong_key:
        await asyncio.to_thread(record, deps.user_id, node_id, item.id, grade.wrong_key, answer_text)
        set_confront(deps.loop_state, {"node_id": node_id, "wrong_key": grade.wrong_key, "check_item_id": item.id})
    return verdict
```

A `misconception` with no key (the stated-confidence path, unreachable until a confidence field exists) stamps the verdict but records nothing — the store keys on `wrong_key`. If HANDOFF-05 shows `CheckAnswer` gained a student-confidence field, pass it into `Attempt.confidence` and say so in the hand-off; never `grade.confidence`.

Edits to PKG-05's code (HANDOFF-05 shows the current bodies; keep every PKG-05b/06b line):
- `GradeOutcome` gains `verdict: str | None = None  # PKG-10: the rule's verdict; None when the rule did not run`.
- In `grade_answer`, compute the grader-facing text once, BEFORE the idk branch, so all three evidence paths hand the hook the same `answer_text` (PKG-05b deleted the local `mc_reason` string; its `decisions.mc_reason_answer` builds the byte-identical one):
```python
    answer_text = (decisions.mc_reason_answer(answer.selected_option or "", answer.reason or "")
                   if item.format == "mc_reason" else answer.answer_text)
```
- Replace `matched = result.matched_wrong_key or None` with `matched = await match_wrong_key(item, prior=result, answer_text=answer_text, deps=deps)` — `result` is the `GradeResult` from PKG-05b's `result, backend = await _rubric_grade(...)` / `_reason_grade(...)` (the verdict's `.result`, which PKG-05b exposes for exactly this). `_wrong_key(item, answer, correct=correct, matched=matched)` and `matched_wrong_key=matched` stay as they are; with `prior` the seam returns the grader's own listed match, so every PKG-05 expectation holds.
- `_record` becomes async and runs the rule before it appends:
```python
async def _record(deps: SaplingDeps, outcome: GradeOutcome, ev: Evidence, *, item, answer_text: str | None) -> GradeOutcome:
    """Weight from the flags (PKG-03's evidence_weight), then the PKG-10 rule,
    then append. verdict/wrong_key ride the Evidence dict (spec §5); nothing
    journals them (no column) — the misconceptions row is the durable record."""
    ev = ev.model_copy(update={"weight": evidence_weight(ev), "wrong_key": outcome.wrong_key})
    outcome.verdict = await apply_misconception_rule(deps, item=item, grade=outcome, evidence=ev, answer_text=answer_text)
    row = ev.model_copy(update={"verdict": outcome.verdict}).model_dump()
    deps.pending_evidence.append(row)
    outcome.evidence = row
    return outcome
```
  Its call sites (idk, and the returned grade — which PKG-05 as amended folds the numeric mismatch into, after the grader returned; if HANDOFF-05 still shows a separate numeric-mismatch return, that one too) become `return await _record(deps, <outcome>, <ev>, item=item, answer_text=answer_text)`. The `deps.learning_loop is False` return and every `unavailable` return are untouched — no grade, no hook.

- [ ] **Step 4: Run the reopened package's suite, the seam's, this package, invariants, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_check_tool.py tests/test_learning_decisions.py tests/test_learning_misconceptions.py tests/test_learning_loop_invariants.py -q && venv/bin/ruff check .`
Expected: all passed — `inv_14` (check.py imports `learning.misconceptions` and `services.decisions`, never `db.connection`; no `RunContext`/`Tool(`), `inv_17` (check.py is an allowed importer and never names `rollup`), `inv_25` and `inv_28` green; `All checks passed!`. PKG-05's tests leave `deps.loop_state` unset, so the hook is inert there and their verdicts are unchanged. If a PKG-05 test pins `GradeOutcome`'s field set (new `verdict`) or compares a whole Evidence dict (its `wrong_key` now carries `GradeOutcome.wrong_key`, spec §5), update THAT assertion in the same commit and say so in HANDOFF-05's Post-hoc line — do not weaken it.

- [ ] **Step 5: Commit**

```
git add backend/agents/tools/check.py backend/tests/test_learning_misconceptions.py backend/tests/test_learning_check_tool.py
git commit -m "fix(learning-loop): PKG-05 — wire the slip/misconception rule into grade_answer (post-hoc for PKG-10)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 6: Post-hoc PKG-07 + PKG-09 — confrontation line on the deep tier, isomorph re-ask, brief hook

Two reopened packages, two commits (`fix(learning-loop): PKG-07 — …`, `fix(learning-loop): PKG-09 — …`); their suites stay green; ledger rows `07 | reopened`, `09 | reopened`; Post-hoc lines in Task 7.

**Files:**
- Modify: `backend/routes/learn_loop.py` (PKG-07: `_grade_submission`, turn plan and assembly, item selection; PKG-09: `close_session`), `backend/learning/learner_brief.py` (PKG-09)
- Test: `backend/tests/test_learn_loop_routes.py` (append), `backend/tests/test_learning_close_brief.py` (append)

**Interfaces:**
- Consumes: HANDOFF-07's `_LoopTurn.plan` (its one `policy.model_tier(...)` call) and the message assembly that prefixes `phase_prefix(...)`, `_grade_submission` (the fresh `SaplingDeps` it hands `grade_answer`), the check-answer handler that runs the ONE feedback turn, and the item-selection site; HANDOFF-04's check-item reader (call it `get_check_item(id)`); HANDOFF-09's `learner_brief._open_misconception_keys(user_id, node_ids_in_play, closes)`; `learning.misconceptions.{attempts_for_node, attempts_of, confront_of, set_confront, slip_or_misconception, open_for}`; `learning.policy.next_isomorph`.
- Produces: `routes/learn_loop.py::_confrontation_line(loop_state) -> str | None`; `_grade_submission` handing `grade_answer` the loop state; `misconception_active` wired into the tier choice; the isomorph preference at item selection; `_open_misconception_keys` reading `open_for`; `close_session` passing the session's open keys to `build_close`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_learn_loop_routes.py` (mirror that module's fixtures for the loop state, the check-answer turn and the check-item read; patch `routes.learn_loop.get_check_item` or whatever HANDOFF-04's reader is imported as):

```python
def _confront_state(key="k1"):
    from learning.misconceptions import set_confront
    s = {}   # the runtime loop-state shape (see _fresh_loop_state in test_learning_misconceptions.py)
    set_confront(s, {"node_id": "n1", "wrong_key": key, "check_item_id": "ci1"})
    return s


def test_confrontation_line_resolves_text_without_clearing(monkeypatch):
    from learning.checks import WrongReason
    from learning.misconceptions import confront_of
    from routes import learn_loop
    state = _confront_state()
    item = MagicMock(common_wrong=[WrongReason(key="k1", text="the derivative of x^2 is x")])
    monkeypatch.setattr(learn_loop, "get_check_item", lambda _id: item)
    line = learn_loop._confrontation_line(state)
    assert line == 'The student holds misconception "the derivative of x^2 is x": create a contradiction they must resolve; do not simply state the correction.'
    assert confront_of(state) is not None, "the turn assembly clears it, not this reader"


def test_confrontation_line_absent_when_key_unknown_or_item_gone(monkeypatch):
    from learning.checks import WrongReason
    from routes import learn_loop
    monkeypatch.setattr(learn_loop, "get_check_item", lambda _id: MagicMock(common_wrong=[WrongReason(key="k1", text="t")]))
    assert learn_loop._confrontation_line(_confront_state(key="zz")) is None
    monkeypatch.setattr(learn_loop, "get_check_item", lambda _id: None)
    assert learn_loop._confrontation_line(_confront_state()) is None
    assert learn_loop._confrontation_line({}) is None


def test_confronting_turn_is_deep_and_carries_the_line_once(monkeypatch):
    """A15: the turn that confronts routes deep (develop band, normal budget);
    the line sits in THIS turn's user message right after the phase
    instruction, never in the stored brief or the history (A19); the marker is
    cleared, so the next turn is not deep for this reason."""
    from learning.misconceptions import confront_of
    from routes import learn_loop
    seen = []
    real = learn_loop.model_tier   # patch where the route looks the name up

    def spy(*a, **kw):
        seen.append(kw["misconception_active"] if "misconception_active" in kw else a[4])
        return real(*a, **kw)

    monkeypatch.setattr(learn_loop, "model_tier", spy)
    # arrange: copy the module's existing feedback-turn arrange step (check-answer with a wrong answer,
    # develop band, normal budget); its load_loop_state patch returns the module's active-item state
    # plus the _confront_state() marker; patch get_check_item as above
    message, slot, state = ...  # run the feedback turn; capture the user message sent and the model slot used
    assert seen[-1] is True and slot == "loop_tutor_deep"
    assert message.count("holds misconception") == 1
    assert message.index("<phase-marker>") < message.index("holds misconception") < message.index("[STUDENT QUESTION]")
    assert confront_of(state) is None
    ...  # run the next model turn on the same state
    assert seen[-1] is False


def test_confrontation_waits_while_no_model_runs(monkeypatch):
    """At the hard budget level the tier is `none` (no model call): the marker is kept for the next model turn."""
    from learning.misconceptions import confront_of
    # arrange as above with the module's hard-budget fixture (ai_budget.check → level "hard")
    state = ...
    assert confront_of(state) is not None


def test_grade_submission_hands_the_loop_state_to_grade_answer(monkeypatch):
    """Without it the hook is inert on the check-answer path (deps.loop_state is None)."""
    from routes import learn_loop
    seen = {}
    real = learn_loop.grade_answer

    async def spy(item, answer, *, deps, **kw):
        seen["state"] = deps.loop_state
        return await real(item, answer, deps=deps, **kw)

    monkeypatch.setattr(learn_loop, "grade_answer", spy)
    # arrange: copy the module's /check/answer arrange step (active item, graded wrong answer)
    state = ...  # the loop state the handler loaded (its load_loop_state patch's return value)
    assert seen["state"] is state


def test_item_selection_prefers_isomorph_after_unknown(monkeypatch):
    from routes import learn_loop
    # arrange: attempts_of(state) tail for n1 is a single wrong attempt on h1 (verdict unknown);
    # candidates (already filtered by the site: no revealed hash, no post-test reserve) contain h2
    # (same concept_key/format/difficulty) and h3 (different difficulty). Assert h2 is chosen.
    # A34: a second run where h2 has final_answer=None (a legacy row) and h4 is another isomorph
    # with one activates h4, never h2 (next_isomorph runs over servable candidates only).
    ...
```

Fill the `...` bodies from the module's existing check-answer, feedback-turn, budget and selection tests — they exist (HANDOFF-07 §Verify) and already build the loop state; copy their arrange step, do not invent a second fixture. Replace `<phase-marker>` with the literal heading string HANDOFF-07 names for the phase-instruction block, and assert on the slot name the way the module's tier tests do.

Append to `tests/test_learning_close_brief.py`:

```python
def test_brief_lists_open_misconceptions_from_the_table(monkeypatch):
    from learning import learner_brief
    from learning.params import LEARNER_BRIEF_MAX_CHARS, LEARNER_BRIEF_MAX_MISCONCEPTIONS
    rows = [{"node_id": f"n{i}", "wrong_key": f"k{i}", "count": 9 - i} for i in range(LEARNER_BRIEF_MAX_MISCONCEPTIONS + 3)]
    monkeypatch.setattr(learner_brief, "open_for", lambda uid, ids: rows)
    keys = learner_brief._open_misconception_keys("u1", [r["node_id"] for r in rows], [])
    assert keys[: LEARNER_BRIEF_MAX_MISCONCEPTIONS] == [f"k{i}" for i in range(LEARNER_BRIEF_MAX_MISCONCEPTIONS)]
    brief = ...  # build_brief via the module's existing brief fixture, node ids n0.. in play, no closes
    assert "k0" in brief and f"k{LEARNER_BRIEF_MAX_MISCONCEPTIONS}" not in brief
    assert len(brief) <= LEARNER_BRIEF_MAX_CHARS


def test_brief_table_keys_come_before_close_keys(monkeypatch):
    from learning import learner_brief
    monkeypatch.setattr(learner_brief, "open_for", lambda uid, ids: [{"node_id": "n1", "wrong_key": "k_table", "count": 2}])
    closes = ...  # one decrypted close from the module's fixture whose misconceptions == ["k_close", "k_table"]
    assert learner_brief._open_misconception_keys("u1", ["n1"], closes) == ["k_table", "k_close"]


def test_brief_survives_open_for_failure(monkeypatch):
    from learning import learner_brief
    monkeypatch.setattr(learner_brief, "open_for", lambda uid, ids: (_ for _ in ()).throw(RuntimeError("x")))
    brief = ...  # same fixture, no closes
    assert "open misconceptions" not in brief


def test_close_session_passes_the_sessions_open_misconception_keys(monkeypatch):
    from routes import learn_loop
    seen = {}

    def fake_open_for(uid, ids):
        seen["ids"] = sorted(ids)
        return [{"node_id": "n1", "wrong_key": "k1", "count": 2}]

    real_build = learn_loop.build_close   # patch where the route looks the names up

    def spy_build(msgs, evidence, keys, deltas):
        seen["keys"] = keys
        return real_build(msgs, evidence, keys, deltas)

    monkeypatch.setattr(learn_loop, "open_for", fake_open_for)
    monkeypatch.setattr(learn_loop, "build_close", spy_build)
    # arrange: copy this module's close_session arrange step (session row, messages, two evidence rows on n1)
    ...  # await learn_loop.close_session("s1", "u1")
    assert seen["ids"] == ["n1"] and seen["keys"] == ["k1"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && venv/bin/python -m pytest tests/test_learn_loop_routes.py tests/test_learning_close_brief.py -q -k "confront or isomorph or misconception or loop_state_to_grade_answer"`
Expected: FAIL — `AttributeError: module 'routes.learn_loop' has no attribute '_confrontation_line'`; the deep-tier test fails on `misconception_active` staying `False`; the `_grade_submission` test fails on `seen["state"]` being `None`; the brief and close tests FAIL on `open_for` (`AttributeError: … has no attribute 'open_for'`).

- [ ] **Step 3: Implement**

`routes/learn_loop.py`:
```python
from learning.misconceptions import attempts_for_node, attempts_of, confront_of, set_confront, slip_or_misconception
from learning.checks import is_servable
from learning.policy import next_isomorph

_CONFRONT_LINE = 'The student holds misconception "{text}": create a contradiction they must resolve; do not simply state the correction.'


def _confrontation_line(loop_state) -> str | None:
    """PKG-10: the line for the misconception grade_answer just recorded, or
    None. Text comes from the item's decrypted common_wrong; no marker, a
    missing item or an unknown key yields None. Reads only — the turn assembly
    clears the marker once a model turn has used it."""
    confront = confront_of(loop_state)
    if not confront:
        return None
    try:
        item = get_check_item(confront["check_item_id"])
    except Exception:
        logger.warning("confrontation: check item read failed", exc_info=True)
        return None
    if item is None:
        return None
    for entry in item.common_wrong or []:
        if entry.key == confront["wrong_key"] and entry.text:
            return _CONFRONT_LINE.format(text=entry.text)
    return None
```
`get_check_item` is the read PKG-07 already imports; if it returns the decrypted dict (HANDOFF-07 — PKG-07 validates that dict into `CheckItem` before `grade_answer`), reuse PKG-07's same validation step so `common_wrong` is a list of `WrongReason`, and patch that step in the tests — never a second parser for the column.

Edit points in `_LoopTurn.plan` and its message assembly (the ONE place that calls `policy.model_tier`, shared by `_run_turn_json` and `_stream_turn`; `state` is the turn's loop state):
```python
    line = _confrontation_line(state)
    tier = routable_tier(model_tier(phase, band, rung, failed_on_concept, line is not None, ...))   # A15: the confronting turn is deep
    if tier != "none":
        prefix = phase_prefix(...) + ("\n" + line if line else "")   # right after the phase instruction, before the context blocks
        set_confront(state, None)
```
PKG-07 passes a literal `False` as `model_tier`'s fifth argument (`misconception_active`) "until PKG-10" — replace only that argument; every other argument stays. `model_tier` still applies the soft-level and deep-cap downgrades (spec §3.5) — never override them, and never read `model_pref` (invariant 22). The line never goes into `sessions.loop_brief`, the history (`_load_loop_history`) or the system prompt (A19). The route's existing `save_loop_state` call persists the cleared (or still pending) marker with the rest of the state.

`_grade_submission`: the fresh `SaplingDeps(learning_loop=True, feature="loop_check")` it passes to `grade_answer` gains `loop_state=state` — the state object it already loaded and saves right after grading, so the attempt log and the marker persist with that save. Nothing else in the handler changes (it stays the only `grade_answer`/`flush_pending` caller, invariant 26).

Item selection: the site is PKG-07's `routes/learn_loop.py::_activate_next_item` (spec §9 "Item activation and the current concept", §13 A27 — the only code that SETS `loop_state["active"]` (feedback and withdrawal only clear it); HANDOFF-07 names it). Inside it, after the exclusion set is built and before the `CHECK_ITEM_FORMATS` × `select_item` loop:
```python
    tail = attempts_for_node(attempts_of(state), node_id)
    if tail and slip_or_misconception(tail) == "unknown":
        iso = next_isomorph(last_item, [c for c in candidates if is_servable(c)])  # A34: servable only
        if iso is not None:
            item = iso  # then fall through to the existing activation bookkeeping; skip the format loop
```
(`last_item` = the item of `tail[-1].question_hash`; `candidates` = the list the site already built, with revealed hashes and the concept's post-test reserve excluded (A23) — never widen it; `next_isomorph` sees only its `checks.is_servable` items, A34.) (`last_item` is read by its `check_item_id` from the loop state — it is revealed after a wrong answer, so it is never among `candidates`.) `test_item_selection_prefers_isomorph_after_unknown` is required: it calls `_activate_next_item` directly with the module's seams (the A27 tests in `tests/test_learn_loop_routes.py` show the arrange step) and asserts the isomorph is activated. If HANDOFF-07 names the site differently, use its name; if it records that no activation site exists, STOP — that is a red PKG-07 row (spec §13 A27), repaired as a `fix(learning-loop): PKG-07 — …` reopen, never skipped.

`learning/learner_brief.py`: import `open_for` from `learning.misconceptions`; repoint PKG-09's hook:
```python
def _open_misconception_keys(user_id, node_ids_in_play, closes) -> list[str]:
    """PKG-10: the student's open rows in the misconceptions table first (count
    descending), then PKG-09's union of the closes' keys; deduplicated, order
    preserved. PKG-09's `open misconceptions:` section caps and renders them."""
    keys = [r["wrong_key"] for r in open_for(user_id, list(node_ids_in_play))]
    keys += <PKG-09's existing closes union, unchanged>
    return list(dict.fromkeys(keys))
```
PKG-09's section rules stay as they are (cap `LEARNER_BRIEF_MAX_MISCONCEPTIONS`, the `LEARNER_BRIEF_MAX_CHARS` budget, a raised error omits the section). The brief is still built once per session and stored (A19); nothing here rebuilds it.

`routes/learn_loop.py::close_session` (PKG-09): add `open_for` to the route's `learning.misconceptions` import and replace `draft = build_close(msgs, evidence, [], {})` with
```python
    keys = [r["wrong_key"] for r in open_for(user_id, sorted({e["node_id"] for e in evidence}))]
    draft = build_close(msgs, evidence, keys, {})
```
(`open_for` never raises and reads nothing for an empty id list, so a session with no evidence is unchanged.)

Order: implement and commit the PKG-07 part first (`_grade_submission`'s deps, turn plan and assembly, item selection), then the PKG-09 part (`close_session` in the same file, `learner_brief.py`), so each commit carries only its package's hunks.

- [ ] **Step 4: Run the reopened packages' suites, invariants, full suite, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learn_loop_routes.py tests/test_learning_close_brief.py tests/test_learning_loop_invariants.py -q && venv/bin/python -m pytest tests/ -q && venv/bin/ruff check .`
Expected: all passed (`inv_22`, `inv_23`, `inv_26` still green: no `model_pref`, no new run site, no new `flush_pending` caller); full suite `N₀ + (tests added by Tasks 1–6)` with zero failures; `All checks passed!`

- [ ] **Step 5: Commit — two commits**

```
git add backend/routes/learn_loop.py backend/tests/test_learn_loop_routes.py
git commit -m "fix(learning-loop): PKG-07 — confrontation line on the deep tier and isomorph re-ask on the loop route (post-hoc for PKG-10)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git add backend/learning/learner_brief.py backend/routes/learn_loop.py backend/tests/test_learning_close_brief.py
git commit -m "fix(learning-loop): PKG-09 — learner brief and session close read open misconceptions from the store (post-hoc for PKG-10)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 7: Hand-off + ledger

- [ ] **Step 1:** Write `docs/superpowers/plans/learning-loop/HANDOFF-10.md` from `HANDOFF-template.md`. "Verify commands" must be exactly these four lines:

```
cd backend && venv/bin/python -m pytest tests/test_learning_misconceptions.py -q                → N passed (N ≥ 10)
ls backend/db/migrations/*_learning_misconceptions.sql                                           → 1 file
grep -c "HAVING count(DISTINCT m.user_id) >= 5" backend/db/migrations/*_learning_misconceptions.sql → 1
grep -cE "^def (record|slip_or_misconception|rollup)\(" backend/learning/misconceptions.py        → 3
```

Constants chosen: the §Named constants table, with `GAP_CONFIDENCE_MAX = 0.4 †` and `NOVICE_FLOOR_IDK = 2 †` (both named by spec §13 A6). Deviations (also appended to `LEDGER.md` Deviations): `Verdict` carries a seventh value `none` for a plain correct attempt (spec §3.3 enumerates six) → needed because the rule runs on every graded attempt; `sessions.loop_state` gains sibling keys `attempts` and `confront` beside the per-`question_hash` entries (spec §4 describes only the latter) → ids/enums/bools/numbers and the plaintext key only, the "no free text" rule holds; any PKG-01/PKG-08 constant you had to add. Known gaps: student-stated confidence is `None` until a confidence field exists (A16's body has none; post-series reason/confidence tier), so only the two-isomorph path produces `misconception` today; a misconception recorded mid-session reaches the learner brief only from the next session (the brief is built once per session, A19 — in-session the confrontation line carries it); `resolve()` has no caller yet (PKG-12's review grading is the natural one); `rollup()` has no caller (instructor surface / quiz-agent switch are open questions). Open questions: should `quiz`'s `read_misconceptions_for_course` switch to `rollup()` (it would need the course→graph_nodes join, not offerings, and the consent check at `graph_read.py:516` stays); should `misconception_rollup` also feed `offering_concept_stats.common_misconceptions`; should every `grade_answer` caller feed the rule — today it runs wherever the caller loads `deps.loop_state` (the check route; the probe if HANDOFF-08 says it loads one), and PKG-12 (review) and PKG-14 (post-test) decide for theirs; `match_wrong_reason` is a Jev candidate (A24, PKG-15) — its promotion gates apply per decision.

- [ ] **Step 2:** Ledger rows: `| 10 | misconceptions | done | feat/learning-loop-10-misconceptions | <sha> | tests/test_learning_misconceptions.py (+ appended to 4 modules) | — | HANDOFF-10.md |`; `| 05 | grader-check-tool | verified | … | (10, <date>, tests/test_learning_check_tool.py → N passed) |`; the same `verified` row for 05b, 06, 07 and 09 (from State of the world); `reopened` rows for 03, 05, 06, 07, 09 each naming the post-hoc commit SHA. Append the "Post-hoc changes" line to `HANDOFF-03.md`, `HANDOFF-05.md`, `HANDOFF-06.md`, `HANDOFF-07.md`, `HANDOFF-09.md`: `PKG-10 <date>: <what> — commit <sha>` (HANDOFF-05's line says `grade_answer` now also writes the `misconceptions` store — a diagnosis write, not evidence — and takes its `wrong_key` from `decisions.match_wrong_reason`; HANDOFF-07's says `_grade_submission` now hands `grade_answer` the loop state and the confronting turn passes `misconception_active=True`; HANDOFF-09's says `close_session` feeds `build_close` the session's open keys).

- [ ] **Step 3: Commit**

```
git add docs/superpowers/plans/learning-loop/HANDOFF-10.md docs/superpowers/plans/learning-loop/HANDOFF-0{3,5,6,7,9}.md docs/superpowers/plans/learning-loop/LEDGER.md
git commit -m "docs(learning-loop): PKG-10 — hand-off, reopened-package notes, ledger

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 8: PR

- [ ] **Step 1: Run the self-check loop once more (all seven steps), then open the PR**

```
gh pr create --title "feat(learning): PKG-10 misconceptions" --body-file - <<'EOF'
Learning loop series, package 13 of 17. Spec: docs/superpowers/specs/2026-09-26-learning-loop-design.md §3.3, §4 (PKG-10), §13 A15, A16, A22, A24.

- `misconceptions` table + `misconception_rollup(text)` (SECURITY DEFINER, service_role only; grouped by course concept_key + wrong_key, never node_id — spec §13 A29; HAVING ≥ MISCONCEPTION_ROLLUP_MIN_USERS distinct users); `evidence_text` encrypted, `wrong_key` plaintext key
- `learning/misconceptions.py`: pure `slip_or_misconception` (unknown/slip/misconception/gap/not_known/novice, plus `none`), fail-closed `record`/`resolve`/`open_for`, backend-only `rollup` — NOT a tutor tool (ADR 0023 §5; inv 17)
- post-hoc: PKG-03 `Evidence.verdict`/`wrong_key`; PKG-06 `policy.next_isomorph`, loop-state `attempts`/`confront`; PKG-05 `grade_answer` runs the rule and records, with the `wrong_key` only from `decisions.match_wrong_reason` (prior = the grader's result, no extra model call; the mc_reason option → key map is never recorded alone — A22/A24); PKG-07 confrontation line on the deep tier (`misconception_active`, A15) + isomorph re-ask; PKG-09 brief reads open misconceptions from the store
- constants: `MISCONCEPTION_MIN_ISOMORPHS = 2`, `GAP_CONFIDENCE_MAX = 0.4 †` (A6)

Flag-off: `learning.misconceptions` is imported only by loop-only surfaces; `grade_answer` has no legacy caller and the hook returns before any read when `deps.learning_loop` is False or no loop state is loaded (tested).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
```

## Self-check loop (run after every task, and once more before the PR)

1. `cd backend && venv/bin/ruff check . && venv/bin/ruff format --check learning tests/test_learning_*.py`
2. `venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q`
3. `venv/bin/python -m pytest tests/ -q` (no `SAPLING_MODEL_MODE` exported)
4. Prompts/tool descriptions touched? **No tool description changes; the only prompt-surface change is the route-assembled confrontation line** (per-turn user-message context, not a system prompt — no `_PROMPT_HASH` changes; `GradeOutcome.verdict` is code-side and never reaches a model). Replay as a no-regression guard, never re-record: `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/loop_tutor.py && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/grader.py && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/decisions.py` → every evaluator ≥ baseline (every tier slot for `loop_tutor`). A drop means a wiring bug in this package — fix the code, not the cassette. No new agent, no new eval dataset.
5. Request-path agent or route touched? **Yes** (`agents/tools/check.py`, `routes/learn_loop.py`). Run one E2E cycle under the stack lock: `flock /tmp/claude-$(id -u)/sapling-e2e-stack.lock sh -c 'make e2e-up && (cd frontend && npx playwright test) ; (cd backend && venv/bin/python -m e2e_oracles) ; make e2e-down'` → Chapter 1 journeys pass (the loop journey `e2e/learn-loop.spec.ts` is PKG-13's; only the pre-series journeys must pass here), oracles exit 0 (the `ciphertext` oracle must not flag `misconceptions.evidence_text` — if it scans only listed columns, add the column to its list in the same commit as the migration and note it), migration replay applies `<ts>_learning_misconceptions.sql` cleanly. No new `E2E_*` constant: no new task (`match_wrong_reason` runs on PKG-05b's `decision` task, whose handler exists).
6. Scope check: `git diff --stat main...HEAD` — every path must be in this prompt's Files lists. Anything else: `git checkout main -- <path>` or record a Deviation.
7. Sync check: `grep -o "E2E_[A-Z_]*" backend/agents/function_handlers_e2e.py | sort -u` unchanged from `main`.

Green = all seven clean. Max 5 iterations per loop; then write a `BLOCKED` row in `LEDGER.md` with hypothesis, commands, outputs, and stop.

## Regression guard

- Pre-series suite count N₀ (State of the world) unchanged except for tests this package adds. Zero failures, zero new skips outside `test_learning_loop_invariants.py`.
- Dependency and reopened modules stay green and are not weakened: `tests/test_learning_check_tool.py` (05), `tests/test_learning_decisions.py` (05b), `tests/test_learning_zpd_policy.py` (06), `tests/test_learning_ai_budget.py` (06b), `tests/test_learning_evidence_apply.py` (03), `tests/test_learn_loop_routes.py` (07), `tests/test_learning_probe_planner.py` (08, a `grade_answer` caller), `tests/test_learning_close_brief.py` (09), `tests/test_learning_bkt.py`, `tests/test_learning_fsrs.py`, `tests/test_learning_check_items.py`.
- Pre-series suites this package's surface touches: `tests/test_graph_service.py` (the evidence path validates two more optional fields and journals neither), `tests/test_event_capture_seams.py` (taxonomy untouched), `tests/test_model_mode_seam.py`, `tests/test_quiz_*.py` (the quiz agent's `read_misconceptions_for_course` is untouched), `tests/test_chunk_visibility.py` (consent precedent untouched).
- Evals: `grader`, `decisions`, `loop_tutor` (every tier slot) ≥ baselines by replay (step 4 above), nothing re-recorded; `chat_tutor` cassettes untouched (its tool list does not change).
- Cost: no new model call per graded answer (`match_wrong_reason` gets `prior`); the only cost change is one confronting turn per recorded misconception on the deep tier, which `model_tier`'s soft-level and deep-cap downgrades still bound (spec §3.5).
- With `LEARNING_LOOP_ENABLED` unset: no route reads `learning.misconceptions`, `grade_answer` has no caller, the migration's table has no reader on the legacy path — byte-identical.

## Acceptance criteria (the next session pastes these)

1. `cd backend && venv/bin/python -m pytest tests/test_learning_misconceptions.py -q` → `N passed` (N ≥ 10; the rule table alone is 21 cases)
2. `ls backend/db/migrations/*_learning_misconceptions.sql` → 1 file
3. `grep -c "HAVING count(DISTINCT m.user_id) >= 5" backend/db/migrations/*_learning_misconceptions.sql` → `1`
4. `grep -cE "^def (record|slip_or_misconception|rollup)\(" backend/learning/misconceptions.py` → `3`
5. `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_07 or inv_08 or inv_09 or inv_17"` → `4 passed`
6. `grep -rn "misconception_rollup" backend/agents/` → no output
7. `grep -cE "^(MISCONCEPTION_MIN_ISOMORPHS|GAP_CONFIDENCE_MAX) = " backend/learning/params.py` → `2`
8. `cd backend && venv/bin/python -m pytest tests/ -q` → zero failures; `venv/bin/ruff check .` → `All checks passed!`
9. `git diff --stat main...HEAD` lists only: `backend/learning/{params,misconceptions,evidence,policy,learner_brief}.py`, `backend/learning/loop_state_store.py` (only if HANDOFF-07's loop-state mapping lives there), `backend/agents/tools/check.py`, `backend/routes/learn_loop.py`, `backend/db/migrations/*_learning_misconceptions.sql`, `backend/tests/test_learning_misconceptions.py`, `backend/tests/test_learning_loop_invariants.py`, `backend/tests/test_learning_evidence_apply.py`, `backend/tests/test_learning_zpd_policy.py`, `backend/tests/test_learning_check_tool.py` (only if a `GradeOutcome` field pin or a whole-Evidence-dict expectation moved), `backend/tests/test_learn_loop_routes.py`, `backend/tests/test_learning_close_brief.py`, `docs/superpowers/plans/learning-loop/{HANDOFF-10.md,HANDOFF-03.md,HANDOFF-05.md,HANDOFF-06.md,HANDOFF-07.md,HANDOFF-09.md,LEDGER.md}` — no eval cassette or baseline.
10. `LEDGER.md` has row `10 | misconceptions | done | …`, `verified` rows for 05, 05b, 06, 07 and 09, `reopened` rows for 03, 05, 06, 07, 09.
11. `grep -c "match_wrong_reason" backend/agents/tools/check.py` → `≥ 1`; `grep -c "graded_check\|RunContext" backend/agents/tools/check.py` → `0` (A16/A24: the key comes from the seam; no tool)
12. `grep -c "misconception_active" backend/routes/learn_loop.py` → `≥ 1` (A15: the confronting turn is deep); `grep -c "model_pref" backend/routes/learn_loop.py` → `0` (invariant 22)
13. `grep -c "RETURNS TABLE (concept_key text, wrong_key text, users int)" backend/db/migrations/*_learning_misconceptions.sql` → `1`; `grep -c "GROUP BY m.node_id" backend/db/migrations/*_learning_misconceptions.sql` → `0` (spec §13 A29: the floor counts students per course concept, never per per-user node)

## Hand-off

`docs/superpowers/plans/learning-loop/HANDOFF-10.md` per the template, headings fixed: What changed · Symbols added · Constants chosen · Deviations from spec · Known gaps · Verify commands (the four-line block in Task 7, verbatim) · Open questions for the series owner · Post-hoc changes. Symbols to list: `learning/misconceptions.py::{Attempt,Verdict,slip_or_misconception,record,resolve,open_for,rollup,attempts_of,confront_of,set_confront,attempts_for_node}`, `learning/policy.py::next_isomorph`, loop-state keys `attempts`/`confront` (and their `LoopState` round-trip), `learning/evidence.py::Evidence.{verdict,wrong_key}`, `agents/tools/check.py::{match_wrong_key,apply_misconception_rule}` and `GradeOutcome.verdict` (with `_record` now async), `routes/learn_loop.py::_confrontation_line` and the `misconception_active` wiring, `learning/learner_brief.py::_open_misconception_keys` (repointed), `routes/learn_loop.py::close_session` (feeds `build_close` the session's open keys), table `misconceptions`, function `misconception_rollup(text)`, params `MISCONCEPTION_MIN_ISOMORPHS`, `GAP_CONFIDENCE_MAX †`.

## Do not

- Do not register `rollup`, `misconception_rollup`, or any misconception read on `chat_tutor`, `loop_tutor`, or `quiz` (ADR 0023 §5). Do not touch `agents/tools/graph_read.py::read_misconceptions_for_course` or its consent check at `:516`.
- Do not filter, join, or `UNIQUE` on `evidence_text`; encrypt it with `encrypt_if_present` at the write boundary and never read it back into a prompt in this package.
- Do not write `graph_nodes`, `graph_edges`, `node_mastery_events`, or `learner_state` from `learning/misconceptions.py` or the hook — `verdict`/`wrong_key` ride the Evidence dict to the route's `flush_pending` → `apply_graph_update` (inv 1), which journals neither.
- Do not feed the grader's confidence into the rule; `Attempt.confidence` is the student's stated confidence or `None`.
- Do not take a `wrong_key` from anywhere but `match_wrong_key` → `decisions.match_wrong_reason` (A22/A24): never from the `mc_reason` option → key map alone, never from the grader's raw output around the seam. Never call `match_wrong_reason` without `prior` (an extra `decision` run against `STUDENT_DAILY_GRADES`). Never let a missing key change whether evidence is written.
- Do not put the confrontation line into `sessions.loop_brief`, the history or the system prompt (A19 stable prefix); it rides the current turn's user message only. Do not choose a slot, override `model_tier`'s downgrades, or read `model_pref` (invariant 22) — pass `misconception_active` and nothing else.
- Do not add a tutor tool, a `RunContext` or a `graded_check_tool` (A16); the hook is a plain async function inside `grade_answer`.
- Do not add `evidence_text` (free text) to `sessions.loop_state`; the attempt log holds ids, enums, bools, numbers only.
- Do not lower the `HAVING` literal, move it into Python, or add a code-side "n ≥ 5" that could drift from the SQL — the test pins the literal to `MISCONCEPTION_ROLLUP_MIN_USERS`.
- All Supabase access through `db/connection.py::table()`/`rpc()`; no `httpx`, no `supabase` import.
- Migrations: UTC-timestamp prefix, `_learning_` infix, append-only, never edited after creation; a role-guard fix is a NEW migration.
- No numeric literal in loop code outside `learning/params.py`; the SQL literal is the sanctioned exception, pinned by test.
- No `lru_cache` in this package. No new event type. No new `AgentTask`, no new `E2E_*` constant.
- Do not skip, xfail, weaken, or delete any pre-existing test. Do not hand-edit, re-record or re-baseline eval cassettes or baselines (step 4 replays only).
- Reopened packages get their own `fix(learning-loop): PKG-MM — …` commit first, ledger `reopened` row, and a Post-hoc line in their hand-off — never a silent edit.
- Logscan `ALLOWLIST` in `backend/e2e_oracles/logscan.py` stays `()`.
- End every commit with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; end the PR body with the Claude Code attribution line.

## If you get stuck

1. Re-read §Spec/Behaviour item 2 (the decision order) and spec §3.3 before guessing; the rule table in Task 4 IS the contract.
2. A HANDOFF-0N symbol name in this prompt is a placeholder (`get_check_item`, `_assemble_turn`, the test factories `_item`/`_mc_item`/`_patch_grader`, how `grade_answer` exposes the grader result it passes as `prior`) — the real name is in that hand-off's §Symbols added (HANDOFF-04/05/05b/07). Grep for it; never invent a parallel symbol.
3. Three failed iterations on one task → append a `BLOCKED` row to `LEDGER.md` (hypothesis, commands run, outputs), commit what is green, open the PR as draft, stop.
4. Never widen scope to unblock (no instructor route, no frontend, no quiz-agent switch). Never disable a test to unblock.
5. Ambiguity → choose the option closest to the spec, mark it `†` in the hand-off, continue.

## A38 amendments (2026-09-29)

Spec §13 A38 (owner decision 05b(g)) binds this package. **Precondition:** decision-seam messages line-quote the state text, as the grader already quotes student answers. This is built by the A38 step's lane E and must be on `feat/learning-loop` before Task 1 wires `decisions.match_wrong_reason` into `grade_answer`. Verify it first (a seam test whose state text carries a line that starts with a role or directive marker shows it quoted in the message); if it is missing, stop and append a `BLOCKED` row to `LEDGER.md` instead of wiring the call. Read `loop_state["active"]` above as `loop_state["current"]` and per-item entries as `loop_state["steps"][qh]` (A38 06(p)); write loop state only through `loop_state_store.update_loop_state` (A38 06(q)).
