# PKG-10 misconceptions — Learning Loop series (11 of 15)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> You are a fresh session. Nothing outside this file, `docs/superpowers/plans/learning-loop/LEDGER.md`, the hand-offs it names, and the files this prompt lists is known to you. Do not infer intent from chat history you do not have. Do not read the whole research corpus; read the sections named below.

## Package id + goal

**PKG-10 `misconceptions`.** After this package: every wrong answer the grader matches to a `common_wrong_json` key is run through the slip / misconception / novice rule (spec §3.3) over the session's attempts on that concept; a `misconception` verdict lands one encrypted row per (student, concept, wrong key) in a new `misconceptions` table, incremented on repeat; the loop tutor is told to confront a recorded misconception with a contradiction rather than a correction; the learner brief carries the student's open misconceptions; and a class rollup exists as a SQL function that returns nothing below `MISCONCEPTION_ROLLUP_MIN_USERS` distinct students and is callable only from the backend — never registered on a tutor (ADR 0023 §5). `tests/test_learning_misconceptions.py` proves the rule table, the store, the encryption, the rollup call shape, and that no tutor can reach the rollup.

Branch: `feat/learning-loop-10-misconceptions`. PR title: `feat(learning): PKG-10 misconceptions`.

Depends on: PKG-05 (`graded_check_tool`, the grader's `matched_wrong_key`), PKG-06 (`learning/policy.py`, `sessions.loop_state`). Reopens (post-hoc, separate first commits): PKG-03 (`Evidence` fields), PKG-06 (`policy.next_isomorph`, loop-state `attempts`), PKG-05 (the hook in `agents/tools/check.py`), PKG-07 (the prefix line in `routes/learn_loop.py`), PKG-09 (`learner_brief.build_brief` reads `open_for`).

## Read before you start (in this order)

0. `docs/superpowers/specs/2026-09-26-learning-loop-design.md` **§13 Amendments log** — in force; where this file and §13 disagree, §13 wins. Re-read it before Task 1.
1. `docs/superpowers/plans/learning-loop/LEDGER.md` — refuse to start if any row is `blocked` or `in-progress`. Rows 00–09 must be `done` or `verified`.
2. `docs/superpowers/plans/learning-loop/HANDOFF-03.md`, `HANDOFF-05.md`, `HANDOFF-06.md`, `HANDOFF-07.md`, `HANDOFF-09.md` — §Symbols added of each. You need from them: the `Evidence` model's file and field list (03); `graded_check_tool`'s signature, its grader result type and the name of its `matched_wrong_key` field, and where it appends to `ctx.deps.pending_evidence` (05); the loop-state type on `SaplingDeps.loop_state` and how `routes/learn_loop.py` persists it (06/07); the name of the function that assembles the loop tutor's per-turn prefix and the name of the learner-brief block inside it (07); `learner_brief.build_brief`'s signature and how it bounds itself (09); the check-item CRUD reader in `services/check_item_service.py` (04, via HANDOFF-04.md §Symbols added).
3. `CLAUDE.md` §Conventions (Supabase only via `table()`/`rpc()`, encryption at write boundaries, `report_empty_result` for agent read tools) and §Gotchas (encrypted columns). The "Do not" list repeats what applies.
4. `docs/superpowers/specs/2026-09-26-learning-loop-design.md` §3.3 "Slip / misconception / novice rule" (the six verdicts), §3.4 (`MISCONCEPTION_ROLLUP_MIN_USERS`, `LEARNER_BRIEF_MAX_MISCONCEPTIONS`), §4 "PKG-10" block (DDL, verbatim), §4's encryption paragraph (`evidence_text` is encrypted; `wrong_key` is the plaintext key), §5 (`Evidence`), §7 (flag), §8 invariants 1, 7, 8, 9.
5. `docs/decisions/0023-tutor-graph-retrieval-seam.md` §Decision item 5 — why a class-aggregate read stays off the tutor until consent is code-enforced. This package keeps that stance: the rollup is a backend function with no agent tool.
6. Research, by heading: `docs/research/learning-loop/AI tutor learning loop research.md` §"Slip, misconception, or novice: three different responses" (≈ lines 86–88; the rule's evidence basis — FCI "never interpret single items", Lehman 2013 contradiction-induced confusion) and §"Prioritized recommendations for Sapling" item 9 (≈ line 173, the n ≥ 5 floor). `docs/research/learning-loop/ZPD lever tradeoffs and upgrades.md` §"Sapling ZPD policy spec" EVIDENCE MAPPING block (≈ lines 205–215: "confidence / reason tier → diagnosis only … never a hint gate") and table row 11 (≈ line 83, confidence tiers separate misconception from ignorance).
7. Code you will mirror or modify:
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

Run every row before Task 1. PKG-00's block, then PKG-05's and PKG-06's, verbatim from the series' canonical table.

| check | command | expected |
|---|---|---|
| PKG-00 gate | `cd backend && venv/bin/python -m pytest tests/test_learning_gate.py -q` | `11 passed` |
| PKG-00 invariants | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q` | `4 passed, 8 skipped (later packages raise the passed count)` — expect more passed now; zero failures |
| PKG-00 deps/settings/migration | `cd backend && venv/bin/python -m pytest tests/test_learning_deps.py tests/test_learning_settings_flag.py tests/test_learning_loop_beta_migration.py -q` | all passed |
| PKG-00 flag | `grep -n "^LEARNING_LOOP_ENABLED" backend/config.py` | 1 hit |
| PKG-00 migration | `ls backend/db/migrations/*_learning_loop_beta.sql` | 1 file |
| PKG-05 check tool | `cd backend && venv/bin/python -m pytest tests/test_learning_check_tool.py -q` | N passed (N ≥ 12) |
| PKG-05 grader slot | `grep -c '"grader"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py` | ≥ 1 each |
| PKG-05 tool symbol | `grep -c "^async def graded_check_tool" backend/agents/tools/check.py` | 1 |
| PKG-05 grader evals | `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/grader.py` | every evaluator ≥ baseline |
| PKG-06 policy | `cd backend && venv/bin/python -m pytest tests/test_learning_zpd_policy.py -q` | N passed (N ≥ 25) |
| PKG-06 policy symbols | `grep -cE "^def (ceiling\|band_control\|evidence_for_rung\|wheelspin)\(" backend/learning/policy.py` | 4 |
| PKG-06 events | `grep -c '"zpd\.' backend/services/events_service.py` | 6 |
| PKG-06 migration | `ls backend/db/migrations/*_learning_session_loop_state.sql` | 1 file |
| PKG-06 invariants | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_04 or inv_05"` | 2 passed |
| PKG-07/09 present (reopened here) | `ls docs/superpowers/plans/learning-loop/HANDOFF-07.md docs/superpowers/plans/learning-loop/HANDOFF-09.md` | 2 files |
| hermetic suite green | `cd backend && venv/bin/python -m pytest tests/ -q -x` | `… passed` (note the count N₀) |
| lint green | `cd backend && venv/bin/ruff check .` | `All checks passed!` |
| stub is still a stub | `wc -l backend/learning/misconceptions.py` | ≤ 5 lines (docstring only) |
| latest migration prefix | `ls backend/db/migrations \| tail -1` | a `2026…` file; your prefix must sort after it |

Rule: any red row → STOP. Diagnose, repair on this branch as commit `fix(learning-loop): repair pre-series base — <what>`, record the deviation in `LEDGER.md`, re-run all rows. Never build on a broken base. Mark PKG-05 and PKG-06 `verified` in the ledger (new rows) once their rows are green.

## Spec

### Behaviour

1. **The rule is pure.** `learning.misconceptions.slip_or_misconception(history: list[Attempt]) -> Verdict` reads only typed attempts and constants. `history` is every attempt in the current session on ONE `node_id`, oldest first; the verdict describes the LAST attempt. `Attempt` fields: `question_hash: str`, `node_id: str`, `correct: bool`, `wrong_key: str | None`, `confidence: float | None` (the STUDENT's stated confidence, 0..1, `None` when not asked — never the grader's confidence, which is diagnosis-only per spec §3.3 and never enters this rule), `difficulty: int`, `idk: bool`, `isomorph_of: str | None` (the `question_hash` of the earlier attempt this one re-asks). `Verdict` is `Literal["none", "unknown", "slip", "misconception", "gap", "not_known", "novice"]` — the six spec §3.3 verdicts plus `none` for a plain correct answer with nothing to diagnose (see Deviations).
2. **Decision order** (first match wins; `last = history[-1]`):
   - `history` empty → `none`.
   - `last.correct and last.wrong_key` → `not_known` (right answer, wrong reason — spec §3.3 "treat as a miss").
   - `last.correct and last.isomorph_of` names an earlier attempt in `history` that was wrong → `slip`.
   - `last.correct` → `none`.
   - (last is wrong from here) `last.confidence is not None and last.confidence >= MISCONCEPTION_CONFIDENCE` → `misconception`.
   - `last.wrong_key` and the number of DISTINCT `question_hash` values among wrong attempts in `history` with that same `wrong_key` ≥ `MISCONCEPTION_MIN_ISOMORPHS` → `misconception` (two isomorphs, same key; a second wrong on the SAME hash does not count).
   - misses at difficulty 1 (`not correct and difficulty == 1`, idk included) ≥ `NOVICE_FLOOR_MISSES`, or idk attempts ≥ `NOVICE_FLOOR_MISSES` → `novice`.
   - `last.confidence is not None and last.confidence < GAP_CONFIDENCE_MAX` → `gap`.
   - otherwise → `unknown` (re-ask an isomorph).
   Misconception outranks novice deliberately: PKG-08's `probe.novice_floor()` owns probe exit on its own, so returning `misconception` here loses nothing there and gains the record.
3. **Store.** `record(user_id, node_id, check_item_id, wrong_key, evidence_text) -> dict` reads the open row for `(user_id, node_id, wrong_key)` (`resolved_at` is null); if found, `update` sets `count = count + 1`, `last_seen_at = now`, `check_item_id`, `evidence_text` (encrypted, latest wins); else `insert` a new row with `id = str(uuid.uuid4())`, `count = 1`. `evidence_text` passes through `encrypt_if_present` at the write boundary; `wrong_key` stays plaintext (it is the lookup key). Returns the row dict as written (with `evidence_text` still ciphertext — callers never need it back). `resolve(user_id, node_id, wrong_key) -> int` sets `resolved_at = now` on the open row(s); returns rows touched. `open_for(user_id, node_ids) -> list[dict]` returns `[{"node_id", "wrong_key", "count"}, ...]` for open rows, `count` descending, `node_ids` empty → `[]` with no read. None of the three raise on a DB error: log at WARNING, return `{}` / `0` / `[]` (fail closed, the store is a diagnosis input, never a gate).
4. **Rollup.** `rollup(course_id) -> list[dict]` = `rpc("misconception_rollup", {"p_course_id": course_id})`, DB errors → `[]` + WARNING. Backend-only. Not registered on `chat_tutor`, `loop_tutor`, or `quiz` in this package. `quiz`'s existing `read_misconceptions_for_course` may switch to this source later — out of scope; the hand-off records it as an open question.
5. **Check-tool hook** (post-hoc PKG-05). After `graded_check_tool` has the grader result and built its `Evidence`, it calls `apply_misconception_rule(ctx, item=..., grade=..., evidence=..., answer_text=...)` which: appends this attempt to the session attempt log (`loop_state.attempts`), computes the verdict over that node's attempts, sets `evidence.verdict`, `evidence.wrong_key`; on `misconception` it calls `record(...)` (via `asyncio.to_thread`) and sets `loop_state.confront = {"node_id", "wrong_key", "check_item_id"}`; on `slip` it does nothing further; on every verdict it returns the verdict string so the tool can include it in its return value to the model. It never runs when `ctx.deps.learning_loop` is False (the tool is only registered on the loop tool set — spec §7 — and the hook double-gates). `isomorph_of` for the new attempt = the `question_hash` of the most recent earlier attempt in the log on the same `node_id` with a different `question_hash`, else `None` (derived, no selection plumbing).
6. **Isomorph re-ask** (post-hoc PKG-06). `policy.next_isomorph(item, items) -> CheckItem | None`: same `node_id`, same `format`, same `difficulty`, different `question_hash`, first match in `items` order, else `None`. Pure. `routes/learn_loop.py`'s item-selection call site prefers `next_isomorph(last_item, candidates)` when the last verdict on that node was `unknown` (the `loop_state.attempts` tail says so).
7. **Confrontation** (post-hoc PKG-07). When the loop tutor prefix is assembled and `loop_state.confront` is set, the route resolves the wrong-key text from the check item's decrypted `common_wrong_json`, appends exactly one line — `The student holds misconception "<text>": create a contradiction they must resolve; do not simply state the correction.` — after the learner-brief block and before the phase instruction, then clears `loop_state.confront`. Text missing (item gone, key absent) → no line, no error.
8. **Learner brief** (post-hoc PKG-09). `build_brief` reads `open_for(user_id, node_ids_in_brief)` and appends up to `LEARNER_BRIEF_MAX_MISCONCEPTIONS` lines `- misconception <wrong_key> on <concept_name> (×<count>)`, still inside `LEARNER_BRIEF_MAX_CHARS`. Failure → no lines.
9. **Flag.** Nothing here is reachable when `learning_loop_active` is False: `learning.misconceptions` is imported only by `agents/tools/check.py`, `routes/learn_loop.py` and `learning/learner_brief.py`; the migration adds a table and a function nobody on the legacy path reads. Test: source scan of importers + the hook's early return.

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
CREATE OR REPLACE FUNCTION misconception_rollup(p_course_id text)
RETURNS TABLE (node_id text, wrong_key text, users int)
LANGUAGE sql SECURITY DEFINER AS $$
  SELECT m.node_id, m.wrong_key, count(DISTINCT m.user_id)::int
  FROM misconceptions m JOIN graph_nodes g ON g.id = m.node_id
  WHERE g.course_id = p_course_id AND m.resolved_at IS NULL
  GROUP BY m.node_id, m.wrong_key
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
| `MISCONCEPTION_ROLLUP_MIN_USERS` | 5 | §3.4 | PKG-01 (verify present); must equal the `HAVING` literal in the migration — pinned by test |
| `LEARNER_BRIEF_MAX_MISCONCEPTIONS` | 5 | §3.4 | PKG-01 (verify present); consumed by the PKG-09 hook |
| `LEARNER_BRIEF_MAX_CHARS` | 1800 | §3.4 | PKG-01; the brief's existing bound, unchanged |
| `MISCONCEPTION_MIN_ISOMORPHS` | 2 | §3.3 "wrong on ≥ 2 isomorphs with the same `wrong_key`" | this package adds to `params.py` |
| `GAP_CONFIDENCE_MAX` | 0.4 † | none — spec §3.3 says "wrong with low confidence → gap" without a cut-point | this package adds to `params.py`; record in the hand-off as a deviation and an A/B candidate |

Every other number in this prompt lives in test code only.

### Invariants asserted by this package (spec §8 numbering)

- (7) `learning/misconceptions.py` reaches Supabase only through `from db.connection import rpc, table` — the existing `test_inv_07` covers it once the file exists.
- (8) the migration name matches the pattern and is never modified — `test_inv_08` covers it.
- (9) `evidence_text` carries no `UNIQUE` and no `eq.` filter — extend the migration test in this package (Task 3); `test_inv_09` (PKG-04) already scans for the column name — confirm it goes green, do not duplicate.
- **(17, new)** `test_inv_17_rollup_not_a_tutor_tool`: no file under `backend/agents/` mentions `misconception_rollup` or imports `rollup` from `learning.misconceptions`; `learning.misconceptions` is imported only by the three loop-only files in §Behaviour 9.

### Error semantics

The store fails closed and never raises (WARNING + empty result). The rule is pure and total. No agent call is added, so no ADR 0024 degrade path is touched; the grader's existing `unavailable` result (PKG-05) short-circuits the hook — no grade, no attempt, no verdict.

### Events added

None. `learn.session_closed` (PKG-09) already carries `misconceptions`; this package feeds it through `open_for`, no new type. The taxonomy pin test is untouched.

## Non-goals

- No tutor tool for the rollup (ADR 0023 §5). No change to `agents/tools/graph_read.py::read_misconceptions_for_course` or the quiz agent.
- No student-facing confidence UI (PKG-13 may add the tier; until then `Attempt.confidence` is `None` unless PKG-05's tool already accepts it).
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

- [ ] **Step 1: Append the test** (after the last `test_inv_` function; keep the numbering gap — 13–16 belong to earlier packages)

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

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 2: Post-hoc PKG-03 + PKG-06 — `Evidence.verdict`/`wrong_key`, loop-state `attempts`/`confront`, `policy.next_isomorph`

Reopened-package protocol: one commit per reopened package, before any PKG-10 code; that package's tests stay green; ledger rows `03 | reopened` and `06 | reopened`; "Post-hoc changes" appended to `HANDOFF-03.md` and `HANDOFF-06.md` in Task 7.

**Files:**
- Modify: `backend/learning/evidence.py` (PKG-03), `backend/learning/policy.py` (PKG-06), the loop-state type named in HANDOFF-06 (PKG-06)
- Test: `backend/tests/test_learning_evidence_apply.py` (append), `backend/tests/test_learning_zpd_policy.py` (append)

**Interfaces:**
- Produces: `Evidence.verdict: str | None = None`, `Evidence.wrong_key: str | None = None`; loop-state `attempts: list[dict]` (default empty) and `confront: dict | None` (default `None`); `policy.next_isomorph(item, items)`.

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

Append to `tests/test_learning_zpd_policy.py` (use the `CheckItem` constructor HANDOFF-04 names; the field names below are spec §4):

```python
def _item(qh, node_id="n1", fmt="free", difficulty=2):
    from learning.checks import CheckItem
    return CheckItem(id=f"ci-{qh}", node_id=node_id, course_id="c1", format=fmt, difficulty=difficulty,
                     prompt="p", reference_answer="r", rubric_json=[], common_wrong_json=[],
                     question_hash=qh)


def test_next_isomorph_same_node_format_difficulty_different_hash():
    from learning.policy import next_isomorph
    a, b, c, d, e = (_item("h1"), _item("h2"), _item("h3", node_id="n2"), _item("h4", fmt="teachback"), _item("h5", difficulty=3))
    assert next_isomorph(a, [a, c, d, e, b]) is b


def test_next_isomorph_none_when_only_self_or_mismatches():
    from learning.policy import next_isomorph
    a = _item("h1")
    assert next_isomorph(a, [a, _item("h3", node_id="n2"), _item("h4", fmt="teachback")]) is None
    assert next_isomorph(a, []) is None
```

If `CheckItem` requires fields the helper omits, extend `_item` — do not change `CheckItem`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_evidence_apply.py tests/test_learning_zpd_policy.py -q -k "verdict or isomorph"`
Expected: FAIL — `ValidationError … verdict … Extra inputs are not permitted` (or `AttributeError`) and `ImportError: cannot import name 'next_isomorph'`.

- [ ] **Step 3: Implement**

`learning/evidence.py` — append two fields to `Evidence`, after `same_session_recheck`:
```python
    verdict: str | None = None      # PKG-10: slip_or_misconception verdict for this attempt
    wrong_key: str | None = None    # PKG-10: grader-matched common_wrong_json key, if any
```
PKG-03's `apply_graph_update` evidence path ignores unknown-to-it fields (it reads named keys); confirm with the PKG-03 tests, change nothing there.

`learning/policy.py` — append (pure; imports only `learning.checks` types under `TYPE_CHECKING` if you need the annotation, keeping inv 2 green):
```python
def next_isomorph(item, items):
    """The first check item in `items` that re-asks `item` in a different
    surface: same node_id, same format, same difficulty, different
    question_hash (spec §3.3 "re-ask an isomorph"). None when there is none."""
    for cand in items:
        if (
            cand.node_id == item.node_id
            and cand.format == item.format
            and cand.difficulty == item.difficulty
            and cand.question_hash != item.question_hash
        ):
            return cand
    return None
```

Loop state — HANDOFF-06 names the type on `SaplingDeps.loop_state`. If it is a Pydantic model or dataclass, add `attempts: list[dict] = Field(default_factory=list)` (or `field(...)`) and `confront: dict | None = None`, and make sure PKG-07's serializer writes and reads them (they are ids/enums/bools/numbers only, so the spec §4 "no free text" rule on `sessions.loop_state` holds). If it is a plain dict, no code change: the keys `"attempts"` and `"confront"` are created on first use by Task 5. Whichever it is, write ONE accessor in `learning/misconceptions.py` (Task 4) — not both branches.

- [ ] **Step 4: Run the reopened packages' suites, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_evidence_apply.py tests/test_learning_zpd_policy.py tests/test_learning_loop_invariants.py tests/test_graph_service.py -q && venv/bin/ruff check .`
Expected: all passed (`inv_02` and `inv_04` still green); `All checks passed!`

- [ ] **Step 5: Commit — two commits, one per reopened package**

```
git add backend/learning/evidence.py backend/tests/test_learning_evidence_apply.py
git commit -m "fix(learning-loop): PKG-03 — Evidence.verdict and Evidence.wrong_key (post-hoc for PKG-10)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git add backend/learning/policy.py backend/tests/test_learning_zpd_policy.py <loop-state file if changed>
git commit -m "fix(learning-loop): PKG-06 — policy.next_isomorph and loop-state attempts/confront (post-hoc for PKG-10)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
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
Expected: FAIL — `expected exactly one learning_misconceptions migration, got []` (5 failures). If `params.MISCONCEPTION_ROLLUP_MIN_USERS` is missing, the module errors at import: add it to `params.py` now (§Named constants) and record the deviation against PKG-01.

- [ ] **Step 3: Write the migration**

Prefix from `date -u +%Y%m%d%H%M%S`; content is §Spec/Schema verbatim, header comment included.

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_misconceptions.py tests/test_learning_loop_invariants.py -q -k "Migration or inv_08 or inv_09" && venv/bin/ruff check .`
Expected: all passed; `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/db/migrations/*_learning_misconceptions.sql backend/tests/test_learning_misconceptions.py
git commit -m "feat(learning-loop): PKG-10 — misconceptions table and misconception_rollup(text)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 4: `learning/misconceptions.py` — rule, store, rollup; two params

**Files:**
- Modify: `backend/learning/params.py` (add `MISCONCEPTION_MIN_ISOMORPHS`, `GAP_CONFIDENCE_MAX`)
- Rewrite: `backend/learning/misconceptions.py` (replace the stub)
- Test: `backend/tests/test_learning_misconceptions.py` (append)

**Interfaces:**
- Consumes: `db.connection.table`, `db.connection.rpc`, `services.encryption.encrypt_if_present`, `learning.params`.
- Produces: `Attempt`, `Verdict`, `slip_or_misconception`, `record`, `resolve`, `open_for`, `rollup`, `attempts_of`, `attempts_for_node`.

- [ ] **Step 1: Write the failing tests** (append to the module)

```python
from learning.params import (
    GAP_CONFIDENCE_MAX,
    MISCONCEPTION_CONFIDENCE,
    MISCONCEPTION_MIN_ISOMORPHS,
    NOVICE_FLOOR_MISSES,
)


def _att(qh, *, correct=False, wrong_key=None, confidence=None, difficulty=2, idk=False, isomorph_of=None, node_id="n1"):
    from learning.misconceptions import Attempt
    return Attempt(question_hash=qh, node_id=node_id, correct=correct, wrong_key=wrong_key,
                   confidence=confidence, difficulty=difficulty, idk=idk, isomorph_of=isomorph_of)


HIGH = MISCONCEPTION_CONFIDENCE
MID = (GAP_CONFIDENCE_MAX + MISCONCEPTION_CONFIDENCE) / 2
LOW = GAP_CONFIDENCE_MAX / 2
assert MISCONCEPTION_MIN_ISOMORPHS == 2, "rule table below enumerates two isomorphs"

RULE_TABLE = [
    ("empty", [], "none"),
    ("plain correct", [_att("h1", correct=True)], "none"),
    ("wrong once, no confidence", [_att("h1", wrong_key="k1")], "unknown"),
    ("wrong once, mid confidence", [_att("h1", wrong_key="k1", confidence=MID)], "unknown"),
    ("wrong then right on isomorph", [_att("h1", wrong_key="k1"), _att("h2", correct=True, isomorph_of="h1")], "slip"),
    ("right on non-isomorph after wrong", [_att("h1", wrong_key="k1"), _att("h2", correct=True)], "none"),
    ("two isomorphs same key", [_att("h1", wrong_key="k1"), _att("h2", wrong_key="k1", isomorph_of="h1")], "misconception"),
    ("two isomorphs different keys", [_att("h1", wrong_key="k1"), _att("h2", wrong_key="k2", isomorph_of="h1")], "unknown"),
    ("same hash twice same key", [_att("h1", wrong_key="k1"), _att("h1", wrong_key="k1")], "unknown"),
    ("wrong, confidence at threshold", [_att("h1", wrong_key="k1", confidence=HIGH)], "misconception"),
    ("wrong, confidence at threshold, no key", [_att("h1", confidence=HIGH)], "misconception"),
    ("wrong, low confidence", [_att("h1", wrong_key="k1", confidence=LOW)], "gap"),
    ("right answer wrong reason", [_att("h1", correct=True, wrong_key="k1")], "not_known"),
    ("novice: misses at difficulty 1", [_att(f"h{i}", difficulty=1) for i in range(NOVICE_FLOOR_MISSES)], "novice"),
    ("novice: repeated idk", [_att(f"h{i}", idk=True, difficulty=3) for i in range(NOVICE_FLOOR_MISSES)], "novice"),
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

    with patch.object(misconceptions, "rpc", return_value=[{"node_id": "n1", "wrong_key": "k1", "users": 7}]) as rpc:
        assert misconceptions.rollup("c1") == [{"node_id": "n1", "wrong_key": "k1", "users": 7}]
    rpc.assert_called_once_with("misconception_rollup", {"p_course_id": "c1"})


def test_rollup_degrades_to_empty(caplog):
    from learning import misconceptions

    with patch.object(misconceptions, "rpc", side_effect=RuntimeError("no fn")), caplog.at_level("WARNING"):
        assert misconceptions.rollup("c1") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_misconceptions.py -q`
Expected: collection ERROR — `ImportError: cannot import name 'GAP_CONFIDENCE_MAX' from 'learning.params'`.

- [ ] **Step 3: Implement**

`learning/params.py` — append, next to the other §3.3 constants:
```python
# PKG-10 (spec §3.3 "wrong on ≥ 2 isomorphs with the same wrong_key").
MISCONCEPTION_MIN_ISOMORPHS = 2
# PKG-10 †: spec §3.3 says "wrong with low confidence → gap" with no cut-point.
# Student-stated confidence below this is "low"; between this and
# MISCONCEPTION_CONFIDENCE is "unknown" (re-ask an isomorph). A/B candidate.
GAP_CONFIDENCE_MAX = 0.4
```

`learning/misconceptions.py`:
```python
"""Per-student misconception store and the slip / misconception / novice rule
(spec §3.3), plus the class rollup (spec §4 PKG-10, n ≥
MISCONCEPTION_ROLLUP_MIN_USERS in SQL).

The rule is pure: typed attempts in, one verdict out. The store fails closed.
The rollup is a backend function — never a tutor tool (ADR 0023 §5;
tests/test_learning_loop_invariants.py::test_inv_17).
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
    node_id: str
    correct: bool
    wrong_key: str | None = None
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
    if floor_misses >= NOVICE_FLOOR_MISSES or idks >= NOVICE_FLOOR_MISSES:
        return "novice"
    if last.confidence is not None and last.confidence < GAP_CONFIDENCE_MAX:
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
    """Class rollup via the SECURITY DEFINER SQL function; rows exist only
    above MISCONCEPTION_ROLLUP_MIN_USERS distinct students (enforced in SQL).
    Backend-only. NOT a tutor tool. The quiz agent's
    `read_misconceptions_for_course` may switch to this source later (out of
    scope here)."""
    try:
        return rpc("misconception_rollup", {"p_course_id": course_id}) or []
    except Exception as exc:
        logger.warning("misconceptions.rollup failed for course %s: %s", course_id, exc)
        return []
```

Then add the one loop-state accessor Task 2 decided on (dict key or model attribute — one branch):
```python
def attempts_of(loop_state) -> list[dict]:
    """The session attempt log on the typed loop state (PKG-06); created empty on first use."""
    ...
```

If `table().update` in `db/connection.py` takes filters under a different keyword than `filters=`, match the real signature (`db/connection.py:24–118`) and fix the tests' `call_args[1]` reads to match — do not guess.

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_misconceptions.py tests/test_learning_loop_invariants.py -q && venv/bin/ruff check .`
Expected: all passed (`inv_07` now exercises the new file); `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/learning/params.py backend/learning/misconceptions.py backend/tests/test_learning_misconceptions.py
git commit -m "feat(learning-loop): PKG-10 — slip/misconception/novice rule, misconception store, rollup

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 5: Post-hoc PKG-05 — wire the rule into `graded_check_tool`

Reopened-package protocol: this is the `fix(learning-loop): PKG-05 — …` commit; `tests/test_learning_check_tool.py` stays green; ledger row `05 | reopened`; "Post-hoc changes" on `HANDOFF-05.md` in Task 7.

**Files:**
- Modify: `backend/agents/tools/check.py`
- Test: `backend/tests/test_learning_misconceptions.py` (append), `backend/tests/test_learning_check_tool.py` (unchanged, must stay green)

**Interfaces:**
- Consumes: HANDOFF-05's grader result type (`correct`, `matched_wrong_key`), the `CheckItem` the tool graded against, the tool's `answer` argument, `ctx.deps.loop_state`, `ctx.deps.learning_loop`.
- Produces: `agents/tools/check.py::apply_misconception_rule(ctx, *, item, grade, evidence, answer_text) -> str`; `graded_check_tool`'s return value gains a `verdict` field.

- [ ] **Step 1: Write the failing tests** (append)

Read `tests/test_learning_check_tool.py` first and reuse its `RunContext`/`SaplingDeps` builder and its grader-result and item factories by import; the names below (`_deps`, `_ctx`, `_grade`, `_item_row`) are placeholders — substitute the real ones.

```python
# ── check-tool hook (post-hoc PKG-05) ──────────────────────────────────────

def _loop_deps(**kw):
    from agents.deps import SaplingDeps
    d = SaplingDeps(user_id="u1", course_id="c1", supabase=None, request_id="r", session_id="s1",
                    learning_loop=True, loop_state=kw.pop("loop_state", {}))
    return d


def test_hook_records_on_misconception_and_marks_evidence():
    import asyncio
    from agents.tools import check as check_mod
    from learning.evidence import Evidence

    deps = _loop_deps()
    deps.loop_state["attempts"] = [dict(question_hash="h1", node_id="n1", correct=False, wrong_key="k1",
                                        confidence=None, difficulty=2, idk=False, isomorph_of=None)]
    ctx = MagicMock(); ctx.deps = deps
    item = MagicMock(id="ci2", node_id="n1", question_hash="h2", difficulty=2)
    grade = MagicMock(correct=False, matched_wrong_key="k1", confidence=0.9)
    ev = Evidence(node_id="n1", channel="free_response", correct=False, check_item_id="ci2", question_hash="h2")
    with patch.object(check_mod, "record", return_value={"id": "m1"}) as rec:
        verdict = asyncio.run(check_mod.apply_misconception_rule(ctx, item=item, grade=grade, evidence=ev, answer_text="x is 2"))
    assert verdict == "misconception" and ev.verdict == "misconception" and ev.wrong_key == "k1"
    rec.assert_called_once_with("u1", "n1", "ci2", "k1", "x is 2")
    assert deps.loop_state["attempts"][-1]["isomorph_of"] == "h1"
    assert deps.loop_state["confront"] == {"node_id": "n1", "wrong_key": "k1", "check_item_id": "ci2"}


def test_hook_slip_records_nothing():
    import asyncio
    from agents.tools import check as check_mod
    from learning.evidence import Evidence

    deps = _loop_deps()
    deps.loop_state["attempts"] = [dict(question_hash="h1", node_id="n1", correct=False, wrong_key="k1",
                                        confidence=None, difficulty=2, idk=False, isomorph_of=None)]
    ctx = MagicMock(); ctx.deps = deps
    item = MagicMock(id="ci2", node_id="n1", question_hash="h2", difficulty=2)
    grade = MagicMock(correct=True, matched_wrong_key=None, confidence=0.9)
    ev = Evidence(node_id="n1", channel="free_response", correct=True)
    with patch.object(check_mod, "record") as rec:
        verdict = asyncio.run(check_mod.apply_misconception_rule(ctx, item=item, grade=grade, evidence=ev, answer_text="4"))
    assert verdict == "slip" and ev.verdict == "slip"
    rec.assert_not_called()
    assert deps.loop_state.get("confront") is None


def test_hook_is_inert_when_flag_off():
    import asyncio
    from agents.deps import SaplingDeps
    from agents.tools import check as check_mod
    from learning.evidence import Evidence

    deps = SaplingDeps(user_id="u1", course_id="c1", supabase=None, request_id="r")
    ctx = MagicMock(); ctx.deps = deps
    ev = Evidence(node_id="n1", channel="free_response", correct=False)
    with patch.object(check_mod, "record") as rec:
        verdict = asyncio.run(check_mod.apply_misconception_rule(
            ctx, item=MagicMock(id="ci1", node_id="n1", question_hash="h1", difficulty=1),
            grade=MagicMock(correct=False, matched_wrong_key="k1", confidence=0.9), evidence=ev, answer_text="?"))
    assert verdict == "none" and ev.verdict is None
    rec.assert_not_called()
    assert deps.loop_state is None


def test_hook_uses_student_confidence_not_grader_confidence():
    """Spec §3.3: the grader's confidence is diagnosis-only and never enters the
    rule. A grader-confident wrong answer with no student confidence is `unknown`."""
    import asyncio
    from agents.tools import check as check_mod
    from learning.evidence import Evidence

    deps = _loop_deps()
    ctx = MagicMock(); ctx.deps = deps
    grade = MagicMock(correct=False, matched_wrong_key="k1", confidence=0.99)
    ev = Evidence(node_id="n1", channel="free_response", correct=False, confidence=0.99)
    with patch.object(check_mod, "record") as rec:
        verdict = asyncio.run(check_mod.apply_misconception_rule(
            ctx, item=MagicMock(id="ci1", node_id="n1", question_hash="h1", difficulty=2), grade=grade, evidence=ev, answer_text="x"))
    assert verdict == "unknown"
    rec.assert_not_called()
```

If the loop state is a model (Task 2), replace the `deps.loop_state["attempts"]` / `["confront"]` reads with attribute access via `attempts_of(...)` and `.confront`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_misconceptions.py -q -k hook`
Expected: FAIL — `AttributeError: module 'agents.tools.check' has no attribute 'apply_misconception_rule'`.

- [ ] **Step 3: Implement**

In `agents/tools/check.py`, add the import `from learning.misconceptions import Attempt, attempts_for_node, attempts_of, record, slip_or_misconception` (never `rollup` — inv 17) and the hook:

```python
async def apply_misconception_rule(ctx, *, item, grade, evidence, answer_text: str | None) -> str:
    """PKG-10: append this attempt to the session log, run the spec §3.3 rule
    over this concept's attempts, stamp the Evidence, and record a
    misconception. Student-stated confidence only: `grade.confidence` is the
    grader's and is deliberately not read here. Inert unless the loop is on."""
    deps = ctx.deps
    if not getattr(deps, "learning_loop", False) or deps.loop_state is None:
        return "none"
    log = attempts_of(deps.loop_state)
    prior_same_node = [a for a in log if a.get("node_id") == item.node_id and a.get("question_hash") != item.question_hash]
    wrong_key = (getattr(grade, "matched_wrong_key", None) or None) or None
    attempt = Attempt(
        question_hash=item.question_hash,
        node_id=item.node_id,
        correct=bool(grade.correct),
        wrong_key=wrong_key,
        confidence=_student_confidence(ctx),
        difficulty=int(item.difficulty),
        idk=(evidence.channel == "idk"),
        isomorph_of=prior_same_node[-1]["question_hash"] if prior_same_node else None,
    )
    log.append(attempt.model_dump())
    verdict = slip_or_misconception(attempts_for_node(log, item.node_id))
    evidence.verdict = verdict
    evidence.wrong_key = wrong_key
    if verdict == "misconception" and wrong_key:
        await asyncio.to_thread(record, deps.user_id, item.node_id, item.id, wrong_key, answer_text)
        _set_confront(deps.loop_state, {"node_id": item.node_id, "wrong_key": wrong_key, "check_item_id": item.id})
    return verdict
```

`_student_confidence(ctx)`: if HANDOFF-05 says `graded_check_tool` takes a student confidence argument, thread it through (add a `student_confidence: float | None = None` keyword to the hook and pass it); if not, return `None` and record the gap in the hand-off (only the two-isomorph path yields `misconception` until the tier exists). `_set_confront` / `attempts_of` follow the one loop-state shape chosen in Task 2. A `misconception` with `wrong_key is None` (confidence-only path) stamps the verdict but records nothing — the store keys on `wrong_key`.

Call site: in `graded_check_tool`, immediately after the `Evidence` is built and BEFORE it is appended to `ctx.deps.pending_evidence` (so the route persists `verdict`/`wrong_key` on the evidence row's JSON — `apply_graph_update` ignores the two fields), add
```python
    verdict = await apply_misconception_rule(ctx, item=item, grade=grade, evidence=evidence, answer_text=answer)
```
and include `verdict` in the tool's return value to the model (the existing typed result gains `verdict: str`; the tool description gains one sentence: "`verdict` names the diagnosis: `misconception` means confront with a contradiction, `slip` means move on, `novice` means step down to the lowest prerequisite."). Keep the grader's `unavailable` path untouched — no grade, no hook.

- [ ] **Step 4: Run the reopened package's suite, this package, invariants, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_check_tool.py tests/test_learning_misconceptions.py tests/test_learning_loop_invariants.py -q && venv/bin/ruff check .`
Expected: all passed (`inv_17` green: `check.py` is an allowed importer and never names `rollup`); `All checks passed!`. If a PKG-05 test pins the tool's return shape and now fails on the new `verdict` field, update THAT assertion in the same commit and say so in HANDOFF-05's Post-hoc line — do not weaken it.

- [ ] **Step 5: Commit**

```
git add backend/agents/tools/check.py backend/tests/test_learning_misconceptions.py backend/tests/test_learning_check_tool.py
git commit -m "fix(learning-loop): PKG-05 — graded_check_tool runs the slip/misconception rule (post-hoc for PKG-10)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 6: Post-hoc PKG-07 + PKG-09 — confrontation line, isomorph re-ask, brief hook

Two reopened packages, two commits (`fix(learning-loop): PKG-07 — …`, `fix(learning-loop): PKG-09 — …`); their suites stay green; ledger rows `07 | reopened`, `09 | reopened`; Post-hoc lines in Task 7.

**Files:**
- Modify: `backend/routes/learn_loop.py` (PKG-07), `backend/learning/learner_brief.py` (PKG-09)
- Test: `backend/tests/test_learn_loop_routes.py` (append), `backend/tests/test_learning_close_brief.py` (append)

**Interfaces:**
- Consumes: HANDOFF-07's prefix builder (call it `_build_loop_prefix` below; use the real name) and item-selection site; HANDOFF-04's check-item reader (call it `get_check_item(id)`); HANDOFF-09's `build_brief(user_id, course_id, ...)`.
- Produces: `routes/learn_loop.py::_confrontation_line(loop_state) -> str | None`; the isomorph preference at item selection; `learner_brief.build_brief` misconception lines.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_learn_loop_routes.py` (mirror that module's fixtures for the loop state and the check-item read; patch `routes.learn_loop.get_check_item` or whatever HANDOFF-04's reader is imported as):

```python
def test_prefix_confronts_recorded_misconception_once(monkeypatch):
    from routes import learn_loop
    state = {"attempts": [], "confront": {"node_id": "n1", "wrong_key": "k1", "check_item_id": "ci1"}}
    item = MagicMock(common_wrong_json=[{"key": "k1", "text": "the derivative of x^2 is x"}])
    monkeypatch.setattr(learn_loop, "get_check_item", lambda _id: item)
    line = learn_loop._confrontation_line(state)
    assert line == 'The student holds misconception "the derivative of x^2 is x": create a contradiction they must resolve; do not simply state the correction.'
    assert state.get("confront") is None, "cleared after one use"
    assert learn_loop._confrontation_line(state) is None


def test_prefix_confrontation_absent_when_key_unknown(monkeypatch):
    from routes import learn_loop
    state = {"attempts": [], "confront": {"node_id": "n1", "wrong_key": "zz", "check_item_id": "ci1"}}
    monkeypatch.setattr(learn_loop, "get_check_item", lambda _id: MagicMock(common_wrong_json=[{"key": "k1", "text": "t"}]))
    assert learn_loop._confrontation_line(state) is None


def test_prefix_builder_includes_confrontation_after_brief(monkeypatch):
    """The line sits after the learner-brief block and before the phase instruction."""
    from routes import learn_loop
    # build a prefix with a confront set, using this module's existing prefix fixture
    prefix = ...  # call the real builder as the module's other prefix tests do
    i_brief, i_line, i_phase = prefix.find("<brief-marker>"), prefix.find("holds misconception"), prefix.find("<phase-marker>")
    assert 0 <= i_brief < i_line < i_phase


def test_item_selection_prefers_isomorph_after_unknown(monkeypatch):
    from routes import learn_loop
    # arrange: loop_state.attempts tail for n1 is a single wrong attempt on h1 (verdict unknown);
    # candidates contain h2 (isomorph) and h3 (different difficulty). Assert h2 is chosen.
    ...
```

Fill the two `...` bodies from the module's existing prefix/selection tests — they exist (HANDOFF-07 §Verify) and already build the loop state; copy their arrange step, do not invent a second fixture. Replace `<brief-marker>`/`<phase-marker>` with the literal heading strings HANDOFF-07 names for those blocks.

Append to `tests/test_learning_close_brief.py`:

```python
def test_brief_lists_open_misconceptions_bounded(monkeypatch):
    from learning import learner_brief
    from learning.params import LEARNER_BRIEF_MAX_CHARS, LEARNER_BRIEF_MAX_MISCONCEPTIONS
    rows = [{"node_id": f"n{i}", "wrong_key": f"k{i}", "count": 9 - i} for i in range(LEARNER_BRIEF_MAX_MISCONCEPTIONS + 3)]
    monkeypatch.setattr(learner_brief, "open_for", lambda uid, ids: rows)
    brief = ...  # build via the module's existing brief fixture with node names n0.. mapped
    lines = [l for l in brief.splitlines() if l.startswith("- misconception ")]
    assert len(lines) == LEARNER_BRIEF_MAX_MISCONCEPTIONS
    assert "k0" in lines[0] and "(×9)" in lines[0]
    assert len(brief) <= LEARNER_BRIEF_MAX_CHARS


def test_brief_survives_open_for_failure(monkeypatch):
    from learning import learner_brief
    monkeypatch.setattr(learner_brief, "open_for", lambda uid, ids: (_ for _ in ()).throw(RuntimeError("x")))
    brief = ...  # same fixture
    assert "misconception" not in brief
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && venv/bin/python -m pytest tests/test_learn_loop_routes.py tests/test_learning_close_brief.py -q -k "confront or isomorph or misconception"`
Expected: FAIL — `AttributeError: module 'routes.learn_loop' has no attribute '_confrontation_line'`; brief tests FAIL on `open_for` (`AttributeError: … has no attribute 'open_for'`).

- [ ] **Step 3: Implement**

`routes/learn_loop.py`:
```python
from learning.misconceptions import attempts_for_node, attempts_of, slip_or_misconception

_CONFRONT_LINE = 'The student holds misconception "{text}": create a contradiction they must resolve; do not simply state the correction.'


def _confrontation_line(loop_state) -> str | None:
    """PKG-10: one line, once, for the misconception the check tool just
    recorded. Text comes from the item's decrypted common_wrong_json; a
    missing item or key yields no line. Clears the marker on the way out."""
    confront = _take_confront(loop_state)   # pops loop_state.confront → dict | None (one loop-state shape)
    if not confront:
        return None
    try:
        item = get_check_item(confront["check_item_id"])
    except Exception:
        logger.warning("confrontation: check item read failed", exc_info=True)
        return None
    if item is None:
        return None
    for entry in item.common_wrong_json or []:
        if entry.get("key") == confront["wrong_key"] and entry.get("text"):
            return _CONFRONT_LINE.format(text=entry["text"])
    return None
```
Edit point in the prefix builder: after the learner-brief block is appended and before the phase-instruction block, `line = _confrontation_line(deps.loop_state); if line: parts.append(line)`. Do the same for BOTH the JSON and the streamed loop turns if the builder is not shared — HANDOFF-07 says whether it is.

Item selection: where the route picks the next check item for a node, before the existing choice:
```python
    tail = attempts_for_node(attempts_of(deps.loop_state), node_id)
    if tail and slip_or_misconception(tail) == "unknown":
        iso = next_isomorph(last_item, candidates)
        if iso is not None:
            return iso
```
(`last_item` = the item of `tail[-1].question_hash`; `next_isomorph` from `learning.policy`.)

`learning/learner_brief.py`: import `open_for` from `learning.misconceptions`; after the top-states section, `rows = open_for(user_id, [s.node_id for s in top_states])[:LEARNER_BRIEF_MAX_MISCONCEPTIONS]` inside `try/except Exception` (→ no lines), one line per row `- misconception {wrong_key} on {concept_name} (×{count})`, then the existing `LEARNER_BRIEF_MAX_CHARS` truncation applies unchanged.

- [ ] **Step 4: Run the reopened packages' suites, invariants, full suite, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learn_loop_routes.py tests/test_learning_close_brief.py tests/test_learning_loop_invariants.py -q && venv/bin/python -m pytest tests/ -q && venv/bin/ruff check .`
Expected: all passed; full suite `N₀ + (tests added by Tasks 1–6)` with zero failures; `All checks passed!`

- [ ] **Step 5: Commit — two commits**

```
git add backend/routes/learn_loop.py backend/tests/test_learn_loop_routes.py
git commit -m "fix(learning-loop): PKG-07 — confrontation line and isomorph re-ask on the loop route (post-hoc for PKG-10)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
git add backend/learning/learner_brief.py backend/tests/test_learning_close_brief.py
git commit -m "fix(learning-loop): PKG-09 — learner brief lists open misconceptions (post-hoc for PKG-10)

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 7: Hand-off + ledger

- [ ] **Step 1:** Write `docs/superpowers/plans/learning-loop/HANDOFF-10.md` from `HANDOFF-template.md`. "Verify commands" must be exactly these four lines:

```
cd backend && venv/bin/python -m pytest tests/test_learning_misconceptions.py -q                → N passed (N ≥ 10)
ls backend/db/migrations/*_learning_misconceptions.sql                                           → 1 file
grep -c "HAVING count(DISTINCT m.user_id) >= 5" backend/db/migrations/*_learning_misconceptions.sql → 1
grep -cE "^def (record|slip_or_misconception|rollup)\(" backend/learning/misconceptions.py        → 3
```

Constants chosen: the §Named constants table, with `GAP_CONFIDENCE_MAX = 0.4 †`. Deviations (also appended to `LEDGER.md` Deviations): `Verdict` carries a seventh value `none` for a plain correct attempt (spec §3.3 enumerates six) → needed because the rule runs on every graded attempt; `sessions.loop_state` gains sibling keys `attempts` and `confront` beside the per-`question_hash` entries (spec §4 describes only the latter) → ids/enums/bools/numbers only, the "no free text" rule holds; `GAP_CONFIDENCE_MAX` † invented; any PKG-01 constant you had to add. Known gaps: student-stated confidence is `None` until a confidence tier exists (PKG-13 candidate), so only the two-isomorph path produces `misconception` today; `resolve()` has no caller yet (PKG-12's review grading is the natural one); `rollup()` has no caller (instructor surface / quiz-agent switch are open questions). Open questions: should `quiz`'s `read_misconceptions_for_course` switch to `rollup()` (it would need the course→graph_nodes join, not offerings, and the consent check at `graph_read.py:516` stays); should `misconception_rollup` also feed `offering_concept_stats.common_misconceptions`.

- [ ] **Step 2:** Ledger rows: `| 10 | misconceptions | done | feat/learning-loop-10-misconceptions | <sha> | tests/test_learning_misconceptions.py (+ appended to 4 modules) | — | HANDOFF-10.md |`; `| 05 | grader-check-tool | verified | … | (10, <date>, tests/test_learning_check_tool.py → N passed) |`; the same `verified` row for 06; `reopened` rows for 03, 05, 06, 07, 09 each naming the post-hoc commit SHA. Append the "Post-hoc changes" line to `HANDOFF-03.md`, `HANDOFF-05.md`, `HANDOFF-06.md`, `HANDOFF-07.md`, `HANDOFF-09.md`: `PKG-10 <date>: <what> — commit <sha>`.

- [ ] **Step 3: Commit**

```
git add docs/superpowers/plans/learning-loop/HANDOFF-10.md docs/superpowers/plans/learning-loop/HANDOFF-0{3,5,6,7,9}.md docs/superpowers/plans/learning-loop/LEDGER.md
git commit -m "docs(learning-loop): PKG-10 — hand-off, reopened-package notes, ledger

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 8: PR

- [ ] **Step 1: Run the self-check loop once more (all seven steps), then open the PR**

```
gh pr create --title "feat(learning): PKG-10 misconceptions" --body-file - <<'EOF'
Learning loop series, package 10 of 15. Spec: docs/superpowers/specs/2026-09-26-learning-loop-design.md §3.3, §4 (PKG-10).

- `misconceptions` table + `misconception_rollup(text)` (SECURITY DEFINER, service_role only, HAVING ≥ MISCONCEPTION_ROLLUP_MIN_USERS distinct users); `evidence_text` encrypted, `wrong_key` plaintext key
- `learning/misconceptions.py`: pure `slip_or_misconception` (unknown/slip/misconception/gap/not_known/novice, plus `none`), fail-closed `record`/`resolve`/`open_for`, backend-only `rollup` — NOT a tutor tool (ADR 0023 §5; inv 17)
- post-hoc: PKG-03 `Evidence.verdict`/`wrong_key`; PKG-06 `policy.next_isomorph`, loop-state `attempts`/`confront`; PKG-05 `graded_check_tool` runs the rule and records; PKG-07 confrontation line + isomorph re-ask; PKG-09 brief lists open misconceptions
- constants: `MISCONCEPTION_MIN_ISOMORPHS = 2`, `GAP_CONFIDENCE_MAX = 0.4 †`

Flag-off: `learning.misconceptions` is imported only by loop-only surfaces; the hook returns before any read when `deps.learning_loop` is False (tested).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
```

## Self-check loop (run after every task, and once more before the PR)

1. `cd backend && venv/bin/ruff check . && venv/bin/ruff format --check learning tests/test_learning_*.py`
2. `venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q`
3. `venv/bin/python -m pytest tests/ -q` (no `SAPLING_MODEL_MODE` exported)
4. Prompts/tool descriptions touched? **Yes, one sentence on `graded_check_tool`'s description and a `verdict` field on its result (Task 5).** The tool description is part of the loop tutor's prompt surface, so replay `tests/evals/loop_tutor.py` and `tests/evals/grader.py`: `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/loop_tutor.py && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/grader.py` → every evaluator ≥ baseline. If the loop_tutor cassette's frozen tool schema no longer matches (a `verdict` field appeared), re-record ONLY that dataset with `SAPLING_EVAL_MODE=record` and re-baseline with `SAPLING_EVAL_UPDATE_BASELINES=1`, and say so in the hand-off. The confrontation line is route-assembled context, not a system prompt — no `_PROMPT_HASH` changes. No new agent, no new eval dataset.
5. Request-path agent or route touched? **Yes** (`agents/tools/check.py`, `routes/learn_loop.py`). Run one E2E cycle under the stack lock: `flock /tmp/claude-$(id -u)/sapling-e2e-stack.lock sh -c 'make e2e-up && (cd frontend && npx playwright test) ; (cd backend && venv/bin/python -m e2e_oracles) ; make e2e-down'` → Chapter 1 journeys pass (the loop journey `e2e/learn-loop.spec.ts` is PKG-13's; only the pre-series journeys must pass here), oracles exit 0 (the `ciphertext` oracle must not flag `misconceptions.evidence_text` — if it scans only listed columns, add the column to its list in the same commit as the migration and note it), migration replay applies `<ts>_learning_misconceptions.sql` cleanly. No new `E2E_*` constant: no new task.
6. Scope check: `git diff --stat main...HEAD` — every path must be in this prompt's Files lists. Anything else: `git checkout main -- <path>` or record a Deviation.
7. Sync check: `grep -o "E2E_[A-Z_]*" backend/agents/function_handlers_e2e.py | sort -u` unchanged from `main`.

Green = all seven clean. Max 5 iterations per loop; then write a `BLOCKED` row in `LEDGER.md` with hypothesis, commands, outputs, and stop.

## Regression guard

- Pre-series suite count N₀ (State of the world) unchanged except for tests this package adds. Zero failures, zero new skips outside `test_learning_loop_invariants.py`.
- Dependency and reopened modules stay green and are not weakened: `tests/test_learning_check_tool.py` (05), `tests/test_learning_zpd_policy.py` (06), `tests/test_learning_evidence_apply.py` (03), `tests/test_learn_loop_routes.py` (07), `tests/test_learning_close_brief.py` (09), `tests/test_learning_bkt.py`, `tests/test_learning_fsrs.py`, `tests/test_learning_check_items.py`.
- Pre-series suites this package's surface touches: `tests/test_graph_service.py` (the evidence path reads two more optional fields), `tests/test_event_capture_seams.py` (taxonomy untouched), `tests/test_model_mode_seam.py`, `tests/test_quiz_*.py` (the quiz agent's `read_misconceptions_for_course` is untouched), `tests/test_chunk_visibility.py` (consent precedent untouched).
- Evals: `grader`, `loop_tutor` ≥ baselines (step 4 above); `chat_tutor` cassettes untouched (its tool list does not change).
- With `LEARNING_LOOP_ENABLED` unset: no route reads `learning.misconceptions`, `graded_check_tool` is not registered, the migration's table has no reader on the legacy path — byte-identical.

## Acceptance criteria (the next session pastes these)

1. `cd backend && venv/bin/python -m pytest tests/test_learning_misconceptions.py -q` → `N passed` (N ≥ 10; the rule table alone is 18 cases)
2. `ls backend/db/migrations/*_learning_misconceptions.sql` → 1 file
3. `grep -c "HAVING count(DISTINCT m.user_id) >= 5" backend/db/migrations/*_learning_misconceptions.sql` → `1`
4. `grep -cE "^def (record|slip_or_misconception|rollup)\(" backend/learning/misconceptions.py` → `3`
5. `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_07 or inv_08 or inv_09 or inv_17"` → `4 passed`
6. `grep -rn "misconception_rollup" backend/agents/` → no output
7. `grep -cE "^(MISCONCEPTION_MIN_ISOMORPHS|GAP_CONFIDENCE_MAX) = " backend/learning/params.py` → `2`
8. `cd backend && venv/bin/python -m pytest tests/ -q` → zero failures; `venv/bin/ruff check .` → `All checks passed!`
9. `git diff --stat main...HEAD` lists only: `backend/learning/{params,misconceptions,evidence,policy,learner_brief}.py`, the loop-state file if changed (PKG-06's), `backend/agents/tools/check.py`, `backend/routes/learn_loop.py`, `backend/db/migrations/*_learning_misconceptions.sql`, `backend/tests/test_learning_misconceptions.py`, `backend/tests/test_learning_loop_invariants.py`, `backend/tests/test_learning_evidence_apply.py`, `backend/tests/test_learning_zpd_policy.py`, `backend/tests/test_learning_check_tool.py` (only if a return-shape pin moved), `backend/tests/test_learn_loop_routes.py`, `backend/tests/test_learning_close_brief.py`, `backend/tests/evals/{cassettes,baselines.json}` for `loop_tutor` only if step 4 re-recorded, `docs/superpowers/plans/learning-loop/{HANDOFF-10.md,HANDOFF-03.md,HANDOFF-05.md,HANDOFF-06.md,HANDOFF-07.md,HANDOFF-09.md,LEDGER.md}`.
10. `LEDGER.md` has row `10 | misconceptions | done | …`, `verified` rows for 05 and 06, `reopened` rows for 03, 05, 06, 07, 09.

## Hand-off

`docs/superpowers/plans/learning-loop/HANDOFF-10.md` per the template, headings fixed: What changed · Symbols added · Constants chosen · Deviations from spec · Known gaps · Verify commands (the four-line block in Task 7, verbatim) · Open questions for the series owner · Post-hoc changes. Symbols to list: `learning/misconceptions.py::{Attempt,Verdict,slip_or_misconception,record,resolve,open_for,rollup,attempts_of,attempts_for_node}`, `learning/policy.py::next_isomorph`, `learning/evidence.py::Evidence.{verdict,wrong_key}`, loop-state `attempts`/`confront`, `agents/tools/check.py::apply_misconception_rule`, `routes/learn_loop.py::_confrontation_line`, table `misconceptions`, function `misconception_rollup(text)`, params `MISCONCEPTION_MIN_ISOMORPHS`, `GAP_CONFIDENCE_MAX †`.

## Do not

- Do not register `rollup`, `misconception_rollup`, or any misconception read on `chat_tutor`, `loop_tutor`, or `quiz` (ADR 0023 §5). Do not touch `agents/tools/graph_read.py::read_misconceptions_for_course` or its consent check at `:516`.
- Do not filter, join, or `UNIQUE` on `evidence_text`; encrypt it with `encrypt_if_present` at the write boundary and never read it back into a prompt in this package.
- Do not write `graph_nodes`, `graph_edges`, `node_mastery_events`, or `learner_state` from `learning/misconceptions.py` or the hook — `verdict`/`wrong_key` reach the evidence row only through the route's `apply_graph_update` call (inv 1).
- Do not feed the grader's confidence into the rule; `Attempt.confidence` is the student's stated confidence or `None`.
- Do not add `evidence_text` (free text) to `sessions.loop_state`; the attempt log holds ids, enums, bools, numbers only.
- Do not lower the `HAVING` literal, move it into Python, or add a code-side "n ≥ 5" that could drift from the SQL — the test pins the literal to `MISCONCEPTION_ROLLUP_MIN_USERS`.
- All Supabase access through `db/connection.py::table()`/`rpc()`; no `httpx`, no `supabase` import.
- Migrations: UTC-timestamp prefix, `_learning_` infix, append-only, never edited after creation; a role-guard fix is a NEW migration.
- No numeric literal in loop code outside `learning/params.py`; the SQL literal is the sanctioned exception, pinned by test.
- No `lru_cache` in this package. No new event type. No new `AgentTask`, no new `E2E_*` constant.
- Do not skip, xfail, weaken, or delete any pre-existing test. Do not hand-edit eval cassettes or baselines (re-record if step 4 requires it, and say so).
- Reopened packages get their own `fix(learning-loop): PKG-MM — …` commit first, ledger `reopened` row, and a Post-hoc line in their hand-off — never a silent edit.
- Logscan `ALLOWLIST` in `backend/e2e_oracles/logscan.py` stays `()`.
- End every commit with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`; end the PR body with the Claude Code attribution line.

## If you get stuck

1. Re-read §Spec/Behaviour item 2 (the decision order) and spec §3.3 before guessing; the rule table in Task 4 IS the contract.
2. A HANDOFF-0N symbol name in this prompt is a placeholder (`get_check_item`, `_build_loop_prefix`, the loop-state type) — the real name is in that hand-off's §Symbols added. Grep for it; never invent a parallel symbol.
3. Three failed iterations on one task → append a `BLOCKED` row to `LEDGER.md` (hypothesis, commands run, outputs), commit what is green, open the PR as draft, stop.
4. Never widen scope to unblock (no instructor route, no frontend, no quiz-agent switch). Never disable a test to unblock.
5. Ambiguity → choose the option closest to the spec, mark it `†` in the hand-off, continue.
