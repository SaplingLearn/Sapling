# PKG-11 quiz-flashcards — Learning Loop series (12 of 15)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> You are a fresh session. Nothing outside this file, `docs/superpowers/plans/learning-loop/LEDGER.md`, the hand-offs it points at, and the files this prompt lists is known to you. Do not infer intent from chat history you do not have. Do not read the whole research corpus; read the sections named below.

## Package id + goal

**PKG-11 `quiz-flashcards`.** After this package: when `learning_loop_active(user_id)` is true, `POST /api/quiz/submit` hands `apply_graph_update` one `Evidence` dict per graded question instead of the flat `±MASTERY_DELTA_PER_*` delta, and never calls `quiz_config.mastery_after`; `POST /api/flashcards/rate` advances FSRS state (`fsrs_d`, `fsrs_s`, `due_at`, `reps`, `lapses`) beside the legacy columns; `GET /api/flashcards/user/{user_id}` returns the FSRS columns, orders due cards first via `learning.fsrs.order_due`, and honours `?due_only=true`. When the gate is false, all three handlers issue byte-identical queries and payloads to today's — proven by snapshot tests — and the E2E seeded student stays on the legacy path so `frontend/e2e/quiz.spec.ts`'s `+0.09` pin still holds. `tests/test_learning_flashcards_fsrs.py` and the new cases in `tests/test_quiz_scoring_e.py` prove it.

Branch: `feat/learning-loop-11-quiz-flashcards`. PR title: `feat(learning): PKG-11 quiz-flashcards`.

Depends on: PKG-02 (`learning/fsrs.py`), PKG-03 (`Evidence` model + the `"evidence"` path in `apply_graph_update`). Both must be `done` or `verified` in the ledger.

## Read before you start (in this order)

0. `docs/superpowers/specs/2026-09-26-learning-loop-design.md` **§13 Amendments log** — in force; where this file and §13 disagree, §13 wins. Re-read it before Task 1.
1. `docs/superpowers/plans/learning-loop/LEDGER.md` — refuse to start if any row is `blocked` or `in-progress`. Rows 00, 02, 03 must be `done` or `verified`.
2. `docs/superpowers/plans/learning-loop/HANDOFF-02.md` §Symbols added — the EXACT signatures of `learning.fsrs.next_state`, `interval`, `order_due`, and whatever names PKG-02 gave the rating integers (Again/Hard/Good). This prompt assumes the shapes in §Spec/"Interfaces consumed"; if HANDOFF-02 differs, HANDOFF-02 wins and you adapt the two adapter helpers named in Tasks 4–5, then record the difference under Deviations.
3. `docs/superpowers/plans/learning-loop/HANDOFF-03.md` §Symbols added — the `Evidence` field set, the dict shape `apply_graph_update` accepts under `"evidence"`, and what it RETURNS on that path (this prompt assumes a list of change dicts carrying `before`/`after`, as the legacy path does).
4. `CLAUDE.md` §Conventions and §Gotchas — the standing rules the "Do not" list below repeats.
5. `docs/superpowers/specs/2026-09-26-learning-loop-design.md` §3.2 (FSRS-6 constants and the rating map), §4 (the PKG-11 DDL block), §5 (Evidence model), §7 (flag and gate — the two routes this package wires), §8 invariant 1, §11 (cutover — what PKG-14 removes from the code you touch).
6. `docs/superpowers/plans/learning-loop/README.md` — series conventions, especially "Touching an earlier package's code" (Task 1 does this).
7. `docs/superpowers/plans/learning-loop/HANDOFF-template.md` — what you write at the end.
8. Code you will modify:
   - `backend/routes/quiz.py::submit_quiz` :2391–2720. Anchors: gate-free entry :2391–2393; grading loop :2479–2511 (`results[]` carries per-question `correct`); the delta block :2531–2536 (`mastery_after` call); `event_type` bucketing :2544–2550; `apply_graph_update` call :2558–2571; the `applied` reduction :2578–2585; `quiz_attempts` snapshot write :2587–2603; quiz-context background update :2613–2676; response :2717–2718.
   - `backend/services/quiz_config.py:95–115` — `MASTERY_DELTA_PER_CORRECT`/`PER_WRONG`/`mastery_after`. Read only; you do not change it (PKG-14 deletes it).
   - `backend/routes/flashcards.py` — imports :1–34, `FlashcardRatingBody` :51–54 (`rating` 1 forgot / 2 hard / 3 easy), `get_flashcards` :295–342 (select column string :313, `order="created_at.desc"` :314, semester filter :319–336), `rate_card` :345–383 (select :350–354, update payload :362–369, achievement dispatch :375–381).
   - `backend/services/quiz_identity.py` — `question_hash` :57 and `wire_question_hash` :78 (reads the STORED wire shape: trusts a stored `question_hash`, else recomputes via `question_hash`; returns `None` when the stored item has no usable identity).
   - `backend/tests/test_learning_loop_invariants.py::test_inv_01_single_graph_writer` as PKG-03 wrote it.
9. Code you will mirror:
   - `backend/tests/test_quiz_routes.py:22–29` (`_noop_ctx_agent`), `:66–132` (`SAMPLE_QUESTIONS`, `_make_table`, `_submit_quiz_mocks`), `:617–668` (`TestSubmitQuizMasteryWrite` — the legacy `updated_nodes` payload pin you must not break).
   - `backend/tests/test_flashcards_routes.py:1–100` (`CARDS`, `_tables`, `TestListFlashcards`).
   - `backend/tests/test_learning_loop_beta_migration.py` (PKG-00's migration-invariant style).
   - `backend/tests/test_graph_service.py:25–38` (`_mock_table`).
10. Pins you must keep green: `backend/tests/test_quiz_scoring_e.py::TestMasteryModelSeam` (:74–115) and `frontend/e2e/quiz.spec.ts:56–57` + `:142` + `:299` (`EXPECTED_DELTA = masteryAfter(0, QUIZ_LENGTH, QUIZ_LENGTH)` — the `+0.09` pin; `frontend/e2e/support/quiz.ts:58` is the JS twin of `mastery_after`). `docs/quiz-mastery-model.md` §"Constraint on whoever decides" explains why the pin exists.
11. Frontend you will NOT modify but must understand: `frontend/src/components/screens/Study.tsx:628–680` — `load()` calls `getFlashcards(userId, undefined, semester)` and renders `res.flashcards` in the order the API returns them; `rate(r)` posts `rateFlashcard(userId, card.id, r)` with `r ∈ {1,2,3}` (keyboard `1/2/3` :701–703) and advances `idx` locally. `frontend/src/lib/api.ts:822–836` (`getFlashcards`, `rateFlashcard`). Extra response keys are ignored by both.
12. Research (only these sections): `docs/research/learning-loop/AI tutor learning loop research.md` §"Schedule review with FSRS-6 at 90% retention and successive relearning" (~:98–121; the format-aware rating rule and the `|R − 0.33|` ordering) and the two sentences in §"Replace the scalar mastery score with per-channel BKT plus decay" (~:13–16) that name today's `±0.03/−0.02` per-item delta as the thing this package replaces.

## State of the world

Verify the base is green before Task 1. Every row must match.

| check | command | expected |
|---|---|---|
| hermetic suite green | `cd backend && venv/bin/python -m pytest tests/ -q -x` | `… passed` (note N₀; it is the regression baseline for this package) |
| lint green | `cd backend && venv/bin/ruff check .` | `All checks passed!` |
| ledger | `grep -E "^\| (00\|02\|03) " docs/superpowers/plans/learning-loop/LEDGER.md \| tail -3` | the LAST row for each of 00, 02, 03 is `done` or `verified` |
| latest migration prefix | `ls backend/db/migrations \| tail -1` | a `2026…` timestamped file; your migration's prefix must sort after it |
| PKG-11 stub is inert | `grep -c "def test_" backend/tests/test_learning_flashcards_fsrs.py` | `0` (docstring-only stub from PKG-00) |
| PKG-00 | `cd backend && venv/bin/python -m pytest tests/test_learning_gate.py -q` | `11 passed` |
| PKG-00 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q` | `4 passed, 8 skipped (later packages raise the passed count)` |
| PKG-00 | `cd backend && venv/bin/python -m pytest tests/test_learning_deps.py tests/test_learning_settings_flag.py tests/test_learning_loop_beta_migration.py -q` | `all passed` |
| PKG-00 | `grep -n "^LEARNING_LOOP_ENABLED" backend/config.py` | `1 hit` |
| PKG-00 | `ls backend/db/migrations/*_learning_loop_beta.sql` | `1 file` |
| PKG-02 | `cd backend && venv/bin/python -m pytest tests/test_learning_fsrs.py -q` | `N passed (N ≥ 15)` |
| PKG-02 | `grep -cE "^def (retrievability\|interval\|next_state\|rating_for\|order_due\|budget_select)\(" backend/learning/fsrs.py` | `6` |
| PKG-02 | `cd backend && venv/bin/python -c "from learning.params import FSRS_W; assert len(FSRS_W)==21; print('ok')"` | `ok` |
| PKG-03 | `cd backend && venv/bin/python -m pytest tests/test_learning_evidence_apply.py tests/test_graph_service.py -q` | `all passed` |
| PKG-03 | `ls backend/db/migrations/*_learning_learner_state.sql` | `1 file` |
| PKG-03 | `grep -c '"evidence"' backend/services/graph_service.py` | `≥ 1` |
| PKG-03 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k inv_01` | `1 passed` |

(The PKG-00 invariants row reads `4 passed, 8 skipped` at PKG-00 time; by now PKG-01/02/03 have raised the passed count. Any number of passed is fine; zero failures is the requirement.)

Rule: any red row → STOP. Diagnose, repair on this branch as commit `fix(learning-loop): repair base — <what>`, record the deviation in `LEDGER.md`, re-run all rows. Never build on a broken base. If the repair touches PKG-02 or PKG-03 code, follow README "Touching an earlier package's code".

After the rows pass, mark 02 and 03 `verified` in the ledger (one new row each, `verified-by = PKG-11, <date>, <the command> → <output>`).

## Spec

### Behaviour

**Gate.** Both routes import `from learning.gate import learning_loop_active` at module level (so tests patch `routes.quiz.learning_loop_active` / `routes.flashcards.learning_loop_active`) and evaluate it ONCE per request, at route entry, into a local `loop_on`. With `LEARNING_LOOP_ENABLED` unset the gate does no DB read (PKG-00), so the flag-off path adds zero queries.

**Quiz (`submit_quiz`), `loop_on` true.**
1. Grading is unchanged: `results[]` (one per stored question, `correct: bool`) and `score`/`total` are computed exactly as today.
2. At the delta block: build `evidence = [ … ]`, one dict per `(question, result)` pair in stored order, with exactly these keys: `node_id = concept_node_id`, `channel = "mc"`, `correct = result["correct"]`, `question_hash = wire_question_hash(question)` (may be `None`), `check_item_id = None`, `session_id = None`. Every other `Evidence` field takes the model default (spec §5). `channel` is always `"mc"`: `models.AnswerItem` (:136–138) carries `question_id` + `selected_label` only and `quiz_responses` records `selected_index` + optional `time_ms`/`confidence` — no reason text exists on the quiz wire, so `"mc_reasoned"` is never emitted here. The student's self-reported `confidence` is NOT copied into `Evidence.confidence` (that field is GRADER confidence, spec §5).
3. Call `apply_graph_update(user_id, {"evidence": evidence}, course_id=node.get("course_id"))`. No `"updated_nodes"` key. `mastery_after` is NOT called; no `quiz_correct`/`quiz_partial`/`quiz_confusion` `event_type` is computed (PKG-03 writes `event_type='evidence'` rows).
4. The `quiz_attempts` snapshot (`mastery_before`/`mastery_after`) and the response still report a before/after: `before` = the FIRST recognisable change's `before` (default `node["mastery_score"]`), `after` = the LAST recognisable change's `after` (default `before`). "Recognisable" = a dict whose `after` is not `None`, as the legacy reduction at :2578–2585 already defines. Implemented as a small `_mastery_span(applied, default_before)` helper used only on the loop path; the legacy reduction loop is untouched.
5. Everything after the snapshot write — the quiz-context background task, XP, achievements, `quiz.completed` — runs unchanged.

**Quiz, `loop_on` false.** The delta block, `event_type` bucketing, `apply_graph_update` payload, `applied` reduction, and every write are byte-identical to today (the code moves under an `else:`; nothing inside it changes).

**Flashcards `rate_card`, `loop_on` true.**
1. Select `"id,times_reviewed,last_reviewed_at,fsrs_d,fsrs_s,reps,lapses"` (legacy: `"id,times_reviewed"`).
2. `fsrs_rating = FLASHCARD_RATING_TO_FSRS[body.rating]`; a `body.rating` outside the map → `HTTPException(422, "rating must be one of 1, 2, 3")` BEFORE any write (loop path only; the legacy path keeps accepting any int, as today).
3. `days_since = (now − parse_ts(row["last_reviewed_at"])) / timedelta(days=1)` clamped at `0.0`; `0.0` when `last_reviewed_at` is null.
4. `(d_new, s_new) = next_state(row["fsrs_d"], row["fsrs_s"], fsrs_rating, days_since)` — first review passes `None, None` and PKG-02 seeds `D0(G)`/`S0(G)` (spec §3.2).
5. `due_at = now + timedelta(days=interval(FSRS_RETENTION_DEFAULT, s_new))`.
6. Update payload = the legacy three keys (`times_reviewed`, `last_rating`, `last_reviewed_at`) PLUS `fsrs_d`, `fsrs_s`, `due_at` (ISO), `reps = (row["reps"] or 0) + 1`, `lapses = (row["lapses"] or 0) + 1` when `fsrs_rating` is Again else unchanged. One `update` call, as today.
7. Achievement dispatch unchanged. Response gains `"due_at"` and `"fsrs_rating"` beside `"ok": True`.

**Flashcards `rate_card`, `loop_on` false.** Select string, update payload (exactly the three legacy keys), response `{"ok": True}` — byte-identical.

**Flashcards `get_flashcards`, `loop_on` true.**
1. New query param `due_only: bool = False`.
2. Select the legacy column string + `",fsrs_d,fsrs_s,due_at,reps,lapses"`; same `filters`, same `order="created_at.desc"`; decrypt and semester-filter exactly as today.
3. Then partition: `due` = rows with `due_at` not null and `parse_ts(due_at) <= now`; `fresh` = rows with `fsrs_s` null (never rated on the loop path); `later` = the rest. Order = `_order_due_rows(due, now)` (a thin adapter around `learning.fsrs.order_due`, which sorts by `|R − REVIEW_ORDER_THRESHOLD|` ascending — spec §3.2), then `fresh` in the query's `created_at.desc` order, then `later` by `due_at` ascending.
4. `due_only=true` → return only the `due` bucket (a card with null `due_at` is NOT due; PKG-12 decides whether never-reviewed cards count — Known gap).
5. Response `{"flashcards": rows, "due_count": len(due)}`.

**Flashcards `get_flashcards`, `loop_on` false.** `due_only` is ignored; select string, filters, order, semester filter, and response shape `{"flashcards": rows}` are byte-identical.

### Interfaces consumed (assumed; HANDOFF-02/03 win on conflict)

| symbol | assumed contract | where the route isolates it |
|---|---|---|
| `learning.fsrs.next_state(d, s, rating, days_since)` | `d`/`s` are `float \| None`; returns `(d_new, s_new)` floats | `routes/flashcards.py::_fsrs_advance` |
| `learning.fsrs.interval(retention, s)` | days as `float` | `routes/flashcards.py::_fsrs_advance` |
| `learning.fsrs.order_due(items, now)` | takes the due rows (dicts with `fsrs_s`, `last_reviewed_at`) and returns them re-ordered | `routes/flashcards.py::_order_due_rows` |
| rating integers | Again = 1, Hard = 2, Good = 3 (spec §3.2 `G`); use PKG-02's names if it exported any (e.g. `RATING_AGAIN`), else the `params.py` names Task 4 adds | `learning/params.py::FLASHCARD_RATING_TO_FSRS` |
| `learning.evidence.Evidence` | fields per spec §5; the route sends plain dicts, PKG-03 validates | `routes/quiz.py::_quiz_evidence` |
| `apply_graph_update(user_id, {"evidence": [...]}, course_id=...)` | returns a list of change dicts with `before`/`after` | `routes/quiz.py::_mastery_span` |

If `order_due` wants a different input shape (e.g. `(id, S, elapsed_days)` tuples), `_order_due_rows` builds it and maps the result back to rows by `id`. Do not change the route body for that; change the adapter.

### Schema (exact)

```sql
-- <ts>_learning_flashcards_fsrs.sql
-- Learning loop series PKG-11: FSRS-6 state on flashcards (spec §3.2, §4).
-- Written only by routes/flashcards.py::rate_card when
-- learning.gate.learning_loop_active() is true; NULL on every legacy row.
ALTER TABLE flashcards
  ADD COLUMN IF NOT EXISTS fsrs_d double precision,
  ADD COLUMN IF NOT EXISTS fsrs_s double precision,
  ADD COLUMN IF NOT EXISTS due_at timestamptz,
  ADD COLUMN IF NOT EXISTS reps int NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS lapses int NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS flashcards_due_idx ON flashcards (user_id, due_at);
```

The DDL after the header comment is spec §4's PKG-11 block verbatim.

### Named constants

| name | value | source | used by |
|---|---|---|---|
| `FSRS_RETENTION_DEFAULT` | 0.90 | spec §3.2 (exists in `learning/params.py` since PKG-02) | `rate_card` `due_at` |
| `REVIEW_ORDER_THRESHOLD` | 0.33 | spec §3.2 (PKG-02; inside `order_due`) | cited only — the route never touches it |
| `FLASHCARD_RATING_TO_FSRS` † | `{1: 1, 2: 2, 3: 3}` — UI forgot→Again, hard→Hard, easy→Good | NEW in `learning/params.py` (spec §3.2 rating map says Easy(4) is never emitted in v1; the spec has no flashcard-UI→FSRS table, so this is an engineering choice) | `rate_card` |
| `MASTERY_DELTA_PER_CORRECT` / `MASTERY_DELTA_PER_WRONG` | 0.03 / 0.02 | `services/quiz_config.py:102–103` (legacy, untouched; PKG-14 deletes) | legacy path only |
| E2E quiz pin | `+0.09` = 3 × `MASTERY_DELTA_PER_CORRECT` | `frontend/e2e/quiz.spec.ts:56–57`, `support/quiz.ts:58` | must keep passing; changes at PKG-14 cutover |

The route files contain no numeric literal from this table. `FLASHCARD_RATING_TO_FSRS` is a mapping, not a number, but it lives in `params.py` for the same reason: one place, named, marked †, and recorded under "Constants chosen" in the hand-off.

### Invariants asserted by this package (spec §8 numbering)

- (1) — widened, post-hoc to PKG-03: `routes/quiz.py` and `routes/flashcards.py` contain no `table("graph_nodes"|"graph_edges"|"node_mastery_events"|"learner_state").insert|update|upsert|delete(` (multi-line tolerant), and `routes/quiz.py` contains `apply_graph_update(`. Reads (`.select(`) stay allowed — `submit_quiz` reads `graph_nodes` at :2520 for the IDOR check.
- (7), (8) — already asserted; your migration and route code must keep them green (they run in the self-check loop).
- Package-specific (route tests, not the invariants module): gate-off byte-identity of the three handlers; gate-on evidence shape; `mastery_after` uncalled on the loop path.

### Error semantics

- The gate fails closed (PKG-00): a gate error is the legacy path.
- On the loop path, a failure inside `apply_graph_update` propagates exactly as it does on the legacy path today (the route does not catch it; the atomic `completed_at` claim already makes a retry 409 — see :2408–2414).
- `rate_card` loop path: an invalid rating is a 422 before any write. An exception from `next_state`/`interval` is NOT swallowed — the legacy `update` has not happened yet, so the card is unchanged and the client sees a 500, which is the honest outcome (a silent fallback to the legacy write would leave `reps` and `due_at` drifting from `times_reviewed`).
- No agent runs in this package, so no ADR 0024 degrade path.

### Events added

None. `EVENT_TAXONOMY` is untouched. (`review.served`/`review.graded` are PKG-12's, spec §6. `quiz.completed` keeps firing on both paths.)

## Non-goals

- No review endpoint, no daily budget, no `budget_select`, no exam-aware retention target (PKG-12 owns `/api/learn/loop/review/*` and the `FSRS_RETENTION_EXAM`/`LARGE_SET` selection; this package uses `FSRS_RETENTION_DEFAULT` only).
- No frontend change: `Study.tsx` keeps rendering the API's order and ignoring the new keys; PKG-13 surfaces `due_count` and due-first ordering in the UI.
- No change to `quiz_config.py`, `agents/quiz.py`, `quiz_context` prompts, `frontend/e2e/quiz.spec.ts`, `support/quiz.ts`, or the seed (`backend/db/seed_local_rich.py`). The seeded student stays on the legacy path.
- No `mc_reasoned` channel on the quiz (no reason field exists on the wire); no student-confidence → Evidence mapping.
- No successive-relearning state machine on flashcards (spec §3.2 `SR_*` — PKG-12).
- No taxonomy change, no `chat_stream.py` change, no migration other than the one above.

## Tasks

### Task 1: Widen `test_inv_01` to the two route callers (post-hoc edit to PKG-03)

**Files:**
- Modify: `backend/tests/test_learning_loop_invariants.py` (only `test_inv_01_single_graph_writer` and, if needed, one module-level constant)
- Modify: `docs/superpowers/plans/learning-loop/HANDOFF-03.md` (append under "Post-hoc changes")
- Modify: `docs/superpowers/plans/learning-loop/LEDGER.md` (append one row `03 | evidence-state | reopened | …`)

**Interfaces:**
- Consumes: the filesystem under `backend/`.
- Produces: `test_inv_01` covers `routes/quiz.py` and `routes/flashcards.py` explicitly. The test NAME does not change (PKG-03's `-k inv_01` verify line must still print `1 passed`).

Why: spec §8 (1) names `apply_graph_update` as the single writer; the two routes this package puts on the loop path are the callers most likely to regress into direct writes.

- [ ] **Step 1: Read PKG-03's test body.** Run: `grep -n "def test_inv_01" -A 40 backend/tests/test_learning_loop_invariants.py`. Note whether it scans an explicit file list or a glob over `backend/`.

- [ ] **Step 2: Add the route assertion INSIDE the same test** (append to its body; do not create a second `test_inv_01*` function). Add this module-level constant near `PURE_MODULES` and this block at the end of the test:

```python
ROUTE_GRAPH_CALLERS = ("routes/quiz.py", "routes/flashcards.py")
_GRAPH_WRITE = re.compile(
    r'table\(\s*"(graph_nodes|graph_edges|node_mastery_events|learner_state)"\s*\)'
    r'\s*\.\s*(insert|update|upsert|delete)\s*\(',
    re.S,
)
```

```python
    # PKG-11: the two routes on the loop path never write graph tables
    # directly; the quiz route reaches the graph only through apply_graph_update.
    for rel in ROUTE_GRAPH_CALLERS:
        text = (BACKEND / rel).read_text()
        hits = [m.group(0) for m in _GRAPH_WRITE.finditer(text)]
        assert not hits, f"{rel} writes a graph table directly: {hits}"
    assert "apply_graph_update(" in (BACKEND / "routes/quiz.py").read_text(), (
        "routes/quiz.py must reach the graph through apply_graph_update"
    )
```

If PKG-03's scan already iterates every `backend/**/*.py`, the negative half is redundant but harmless; keep the positive `apply_graph_update(` assertion regardless.

- [ ] **Step 3: Run**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k inv_01 -v`
Expected: `1 passed` (today's `routes/quiz.py` already routes through `apply_graph_update`; `routes/flashcards.py` touches no graph table).

- [ ] **Step 4: Prove the negative half bites** (throwaway, not committed): temporarily append `table("graph_nodes").update({}, filters={})` inside a comment-free line of `routes/flashcards.py`, re-run, expect `FAIL … writes a graph table directly`, then `git checkout -- backend/routes/flashcards.py`.

- [ ] **Step 5: Post-hoc protocol.** Append to `HANDOFF-03.md` under "Post-hoc changes": `PKG-11 <date>: test_inv_01 now also scans routes/quiz.py and routes/flashcards.py for direct graph-table writes and asserts quiz.py calls apply_graph_update — commit <sha>`. Append to `LEDGER.md`: `| 03 | evidence-state | reopened | feat/learning-loop-11-quiz-flashcards | <sha> | +0 (inv_01 widened) | PKG-11, <date>, pytest -k inv_01 → 1 passed | HANDOFF-03.md (Post-hoc) |`.

- [ ] **Step 6: Commit (the separate first commit the README requires)**

```
git add backend/tests/test_learning_loop_invariants.py docs/superpowers/plans/learning-loop/HANDOFF-03.md docs/superpowers/plans/learning-loop/LEDGER.md
git commit -m "fix(learning-loop): PKG-03 — inv_01 scans routes/quiz.py and routes/flashcards.py

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 2: Migration `learning_flashcards_fsrs`

**Files:**
- Create: `backend/db/migrations/<UTC>_learning_flashcards_fsrs.sql`
- Modify: `backend/tests/test_learning_flashcards_fsrs.py` (replace the PKG-00 stub docstring; this task adds the `TestMigration` class, later tasks append)

**Interfaces:**
- Consumes: nothing.
- Produces: columns `flashcards.fsrs_d`, `fsrs_s`, `due_at`, `reps`, `lapses`; index `flashcards_due_idx (user_id, due_at)`.

- [ ] **Step 1: Write the failing test** — the module header plus the migration class:

```python
"""PKG-11: FSRS state on flashcards + the quiz/flashcard gate seams.

Route tests mock `table` (tests/test_graph_service.py::_mock_table style) and
patch the gate at the route module (`routes.flashcards.learning_loop_active`).
FSRS maths is PKG-02's (tests/test_learning_fsrs.py); here `next_state`,
`interval` and `order_due` are patched at the route module so these tests
prove WIRING — what the route reads, what it writes, in what order — not
the curve. Flag-off tests snapshot the exact legacy query strings and
payload key sets: the pre-series behaviour must be byte-identical.
"""
from __future__ import annotations

import pathlib
import re
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)

MIG_DIR = pathlib.Path(__file__).resolve().parents[1] / "db" / "migrations"
USER_ID = "user_test"

LEGACY_LIST_COLS = (
    "id,user_id,topic,offering_id,front,back,times_reviewed,last_rating,"
    "last_reviewed_at,created_at"
)
LEGACY_RATE_COLS = "id,times_reviewed"
LEGACY_RATE_KEYS = {"times_reviewed", "last_rating", "last_reviewed_at"}
FSRS_COLS = ",fsrs_d,fsrs_s,due_at,reps,lapses"
FSRS_KEYS = {"fsrs_d", "fsrs_s", "due_at", "reps", "lapses"}


# ── Migration ────────────────────────────────────────────────────────────────


def _migration() -> str:
    hits = sorted(MIG_DIR.glob("*_learning_flashcards_fsrs.sql"))
    assert len(hits) == 1, f"expected exactly one learning_flashcards_fsrs migration, got {hits}"
    return hits[0].read_text()


class TestMigration:
    def test_prefix_is_a_utc_timestamp(self):
        name = sorted(MIG_DIR.glob("*_learning_flashcards_fsrs.sql"))[0].name
        assert re.fullmatch(r"\d{14}_learning_flashcards_fsrs\.sql", name), name

    @pytest.mark.parametrize("col,decl", [
        ("fsrs_d", r"double precision"),
        ("fsrs_s", r"double precision"),
        ("due_at", r"timestamptz"),
        ("reps", r"int\s+NOT NULL\s+DEFAULT\s+0"),
        ("lapses", r"int\s+NOT NULL\s+DEFAULT\s+0"),
    ])
    def test_columns_are_declared_per_spec(self, col, decl):
        assert re.search(rf"ADD COLUMN IF NOT EXISTS\s+{col}\s+{decl}", _migration()), col

    def test_due_index_is_user_scoped(self):
        assert re.search(
            r"CREATE INDEX IF NOT EXISTS flashcards_due_idx ON flashcards \(user_id, due_at\)",
            _migration(),
        )

    def test_only_touches_flashcards(self):
        sql = _migration()
        assert "ALTER TABLE flashcards" in sql
        assert not re.search(r"ALTER TABLE (?!flashcards)", sql)
        assert "DROP" not in sql.upper()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_flashcards_fsrs.py -v`
Expected: 8 FAIL — `expected exactly one learning_flashcards_fsrs migration, got []`.

- [ ] **Step 3: Write the migration.** Prefix from `date -u +%Y%m%d%H%M%S`. Content is §Spec/Schema verbatim, including the header comment.

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_flashcards_fsrs.py tests/test_learning_loop_invariants.py -q -k "Migration or inv_08" && venv/bin/ruff check .`
Expected: `9 passed`; `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/db/migrations/*_learning_flashcards_fsrs.sql backend/tests/test_learning_flashcards_fsrs.py
git commit -m "feat(learning-loop): PKG-11 — flashcards FSRS columns migration

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 3: Quiz submit — Evidence on the loop path, legacy delta otherwise

**Files:**
- Modify: `backend/routes/quiz.py` (imports; `submit_quiz` :2531–2585; two small helpers above the route)
- Modify: `backend/tests/test_quiz_scoring_e.py` (append one class; nothing existing changes)

**Interfaces:**
- Consumes: `learning.gate.learning_loop_active`, `services.quiz_identity.wire_question_hash` (already imported at :52), `apply_graph_update` (already imported at :43).
- Produces: `routes.quiz._quiz_evidence(concept_node_id, questions, results) -> list[dict]`, `routes.quiz._mastery_span(applied, default_before) -> tuple[float, float]`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_quiz_scoring_e.py`:

```python
# ── PKG-11: learning loop — evidence instead of the flat delta ──────────────
#
# Fixture questions carry the STORED wire shape (`question` + option `text`,
# routes/quiz.py::_agent_question_to_wire). Q1 carries a stored
# question_hash (post-E5 row); Q2 does not (pre-E5 row) so the recompute
# branch of wire_question_hash is exercised too.

LOOP_QUESTIONS = [
    {
        "id": 1,
        "question": "What does a for-loop do?",
        "options": [
            {"label": "A", "text": "iterates", "correct": True},
            {"label": "B", "text": "allocates", "correct": False},
        ],
        "explanation": "A.",
        "question_hash": "deadbeefdeadbeef",
    },
    {
        "id": 2,
        "question": "What is a function?",
        "options": [
            {"label": "C", "text": "a loop", "correct": False},
            {"label": "D", "text": "a reusable block", "correct": True},
        ],
        "explanation": "D.",
    },
]


def _loop_table(questions=LOOP_QUESTIONS):
    def factory(name):
        mock = MagicMock()
        if name == "quiz_attempts":
            mock.select.return_value = [{
                "id": "quiz1",
                "user_id": "user_andres",
                "concept_node_id": "node1",
                "difficulty": "medium",
                "questions_json": questions,
            }]
        elif name == "graph_nodes":
            mock.select.return_value = [{
                "mastery_score": 0.5,
                "concept_name": "Loops",
                "course_id": "course1",
            }]
        else:
            mock.select.return_value = []
        mock.update.return_value = [{"id": "updated"}]
        return mock
    return factory


def _noop_ctx_agent():
    return AsyncMock(
        return_value=SimpleNamespace(output=SimpleNamespace(model_dump=lambda: {}))
    )


def _submit_one_right_one_wrong(*, gate: bool, apply_mock: MagicMock, mastery_after_mock: MagicMock):
    ctx_run = _noop_ctx_agent()
    with (
        patch("routes.quiz.table", side_effect=_loop_table()),
        patch("routes.quiz.learning_loop_active", return_value=gate),
        patch("routes.quiz.apply_graph_update", new=apply_mock),
        patch("routes.quiz.mastery_after", new=mastery_after_mock),
        patch("routes.quiz.get_quiz_context", return_value={}),
        patch("routes.quiz.quiz_context_agent.run", new=ctx_run),
        patch("routes.quiz.save_quiz_context"),
    ):
        r = client.post("/api/quiz/submit", json={
            "quiz_id": "quiz1",
            "answers": [
                {"question_id": 1, "selected_label": "A"},   # correct
                {"question_id": 2, "selected_label": "C"},   # wrong
            ],
        })
    return r, ctx_run


class TestLearningLoopEvidencePath:
    def test_gate_on_submits_one_evidence_per_question(self):
        from services.quiz_identity import question_hash

        apply_mock = MagicMock(return_value=[
            {"before": 0.5, "after": 0.58},
            {"before": 0.58, "after": 0.51},
        ])
        mastery_after_mock = MagicMock(side_effect=AssertionError("legacy delta on the loop path"))
        r, _ = _submit_one_right_one_wrong(
            gate=True, apply_mock=apply_mock, mastery_after_mock=mastery_after_mock,
        )
        assert r.status_code == 200, r.text
        apply_mock.assert_called_once()
        args, kwargs = apply_mock.call_args
        assert args[0] == "user_andres"
        assert kwargs["course_id"] == "course1"
        payload = args[1]
        assert set(payload) == {"evidence"}, "no updated_nodes on the loop path"
        ev = payload["evidence"]
        assert len(ev) == 2
        for e in ev:
            assert set(e) == {
                "node_id", "channel", "correct", "question_hash",
                "check_item_id", "session_id",
            }
            assert e["node_id"] == "node1"
            assert e["channel"] == "mc"
            assert e["check_item_id"] is None and e["session_id"] is None
        assert [e["correct"] for e in ev] == [True, False]
        assert ev[0]["question_hash"] == "deadbeefdeadbeef"          # stored hash trusted
        assert ev[1]["question_hash"] == question_hash(                # recomputed
            "What is a function?", ["a loop", "a reusable block"],
        )
        mastery_after_mock.assert_not_called()

    def test_gate_on_snapshot_spans_first_before_to_last_after(self):
        apply_mock = MagicMock(return_value=[
            {"before": 0.5, "after": 0.58},
            {"before": 0.58, "after": 0.51},
        ])
        r, _ = _submit_one_right_one_wrong(
            gate=True, apply_mock=apply_mock, mastery_after_mock=MagicMock(),
        )
        data = r.json()
        assert data["mastery_before"] == pytest.approx(0.5)
        assert data["mastery_after"] == pytest.approx(0.51)

    def test_gate_on_unrecognisable_return_reports_no_change(self):
        apply_mock = MagicMock(return_value=[])
        r, _ = _submit_one_right_one_wrong(
            gate=True, apply_mock=apply_mock, mastery_after_mock=MagicMock(),
        )
        data = r.json()
        assert data["mastery_before"] == pytest.approx(0.5)
        assert data["mastery_after"] == pytest.approx(0.5)

    def test_gate_on_keeps_the_quiz_context_background_update(self):
        apply_mock = MagicMock(return_value=[{"before": 0.5, "after": 0.6}])
        r, ctx_run = _submit_one_right_one_wrong(
            gate=True, apply_mock=apply_mock, mastery_after_mock=MagicMock(),
        )
        assert r.status_code == 200
        assert ctx_run.call_count == 1, "quiz_context update must still run on the loop path"

    def test_gate_on_hash_is_none_when_the_stored_item_has_no_identity(self):
        legacy_shape = [{
            "id": 1,
            "text": "no stem key, no option text",
            "options": [{"label": "A", "correct": True}, {"label": "B", "correct": False}],
            "explanation": "A.",
        }]
        apply_mock = MagicMock(return_value=[{"before": 0.5, "after": 0.6}])
        ctx_run = _noop_ctx_agent()
        with (
            patch("routes.quiz.table", side_effect=_loop_table(legacy_shape)),
            patch("routes.quiz.learning_loop_active", return_value=True),
            patch("routes.quiz.apply_graph_update", new=apply_mock),
            patch("routes.quiz.get_quiz_context", return_value={}),
            patch("routes.quiz.quiz_context_agent.run", new=ctx_run),
            patch("routes.quiz.save_quiz_context"),
        ):
            r = client.post("/api/quiz/submit", json={
                "quiz_id": "quiz1",
                "answers": [{"question_id": 1, "selected_label": "A"}],
            })
        assert r.status_code == 200
        ev = apply_mock.call_args[0][1]["evidence"]
        assert ev == [{
            "node_id": "node1", "channel": "mc", "correct": True,
            "question_hash": None, "check_item_id": None, "session_id": None,
        }]

    def test_gate_off_is_the_legacy_delta_path(self):
        from services.quiz_config import mastery_after as real_mastery_after

        apply_mock = MagicMock(return_value=[])
        mastery_after_mock = MagicMock(side_effect=real_mastery_after)
        r, _ = _submit_one_right_one_wrong(
            gate=False, apply_mock=apply_mock, mastery_after_mock=mastery_after_mock,
        )
        assert r.status_code == 200
        mastery_after_mock.assert_called_once_with(0.5, score=1, total=2)
        payload = apply_mock.call_args[0][1]
        assert set(payload) == {"updated_nodes"}, "the legacy payload must not change"
        node = payload["updated_nodes"][0]
        assert set(node) == {"concept_name", "mastery_delta", "reason", "event_type"}
        assert node["reason"] == "Quiz: 1/2 correct"
        assert node["event_type"] == "quiz_partial"
        # 1 right, 1 wrong → +PER_CORRECT − PER_WRONG, exactly the seam's arithmetic.
        assert node["mastery_delta"] == pytest.approx(real_mastery_after(0.5, score=1, total=2) - 0.5)

    def test_gate_is_evaluated_once_per_submit(self):
        gate = MagicMock(return_value=True)
        apply_mock = MagicMock(return_value=[{"before": 0.5, "after": 0.6}])
        with (
            patch("routes.quiz.table", side_effect=_loop_table()),
            patch("routes.quiz.learning_loop_active", new=gate),
            patch("routes.quiz.apply_graph_update", new=apply_mock),
            patch("routes.quiz.get_quiz_context", return_value={}),
            patch("routes.quiz.quiz_context_agent.run", new=_noop_ctx_agent()),
            patch("routes.quiz.save_quiz_context"),
        ):
            client.post("/api/quiz/submit", json={
                "quiz_id": "quiz1",
                "answers": [{"question_id": 1, "selected_label": "A"}],
            })
        gate.assert_called_once_with("user_andres")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_quiz_scoring_e.py -q -k LearningLoop`
Expected: 7 errors/failures — `AttributeError: <module 'routes.quiz'> does not have the attribute 'learning_loop_active'` (the `patch` target does not exist yet).

- [ ] **Step 3: Implement.** In `backend/routes/quiz.py`:

Imports (next to the other `services` imports; keep `ruff` import order):
```python
from learning.gate import learning_loop_active
```

Helpers, placed directly above `@router.post("/submit")`:
```python
def _quiz_evidence(concept_node_id: str, questions: list, results: list[dict]) -> list[dict]:
    """PKG-11: one `learning.evidence.Evidence` dict per graded question.

    `channel` is always "mc": the quiz wire carries a selected label and no
    reason text, so it can never be the stronger "mc_reasoned" channel
    (spec §3.1). `question_hash` reads the stored identity (E5) or recomputes
    it; None when the stored item has none. The other Evidence fields keep
    their model defaults — a quiz is unassisted, rung 0, weight 1.0.
    """
    return [
        {
            "node_id": concept_node_id,
            "channel": "mc",
            "correct": bool(result["correct"]),
            "question_hash": wire_question_hash(question),
            "check_item_id": None,
            "session_id": None,
        }
        for question, result in zip(questions, results)
    ]


def _mastery_span(applied, default_before: float) -> tuple[float, float]:
    """PKG-11: (first before, last after) over the changes the graph reported.

    The loop path applies one evidence per question, so the attempt's
    before/after snapshot spans the whole sequence. An unrecognisable
    return degrades to "no change", as the legacy reduction does.
    """
    recognised = [
        c for c in (applied or [])
        if isinstance(c, dict) and c.get("after") is not None
    ]
    if not recognised:
        return default_before, default_before
    before = recognised[0].get("before", default_before)
    return before, recognised[-1]["after"]
```

In `submit_quiz`, right after `user_id = attempt["user_id"]` (:2393):
```python
    # PKG-11 (spec §7): evaluated once, at route entry. With
    # LEARNING_LOOP_ENABLED unset this is a constant False and no read.
    loop_on = learning_loop_active(user_id)
```

Replace :2531–2585 (from `mastery_before = node["mastery_score"]` through the end of the `for change in applied` loop) with:
```python
    mastery_before = node["mastery_score"]
    if loop_on:
        # PKG-11: graded evidence, not a flat per-item delta (spec §5). The
        # graph runs BKT per question and writes event_type='evidence' rows;
        # this route only reports what it wrote.
        applied = apply_graph_update(
            user_id,
            {"evidence": _quiz_evidence(concept_node_id, questions, results)},
            course_id=node.get("course_id"),
        )
        mastery_before, mastery_score_after = _mastery_span(applied, mastery_before)
        mastery_delta = mastery_score_after - mastery_before
    else:
        <the legacy block :2532–2585, moved verbatim under this else, re-indented one level>
```

Everything from the `quiz_attempts` snapshot write (:2587) onward is untouched. `mastery_after` stays imported (the legacy branch uses it); the tests patch `routes.quiz.mastery_after`, so keep the `from services.quiz_config import (… mastery_after …)` import as is.

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_quiz_scoring_e.py tests/test_quiz_routes.py tests/test_quiz_lifecycle_d.py tests/test_quiz_answers_c.py tests/test_quiz_abandon_g4.py tests/test_quiz_gamification_g8.py tests/test_learning_loop_invariants.py -q && venv/bin/ruff check .`
Expected: all passed (22 pre-existing + 7 new in `test_quiz_scoring_e.py`; the legacy pins in `TestMasteryModelSeam` and `TestSubmitQuizMasteryWrite` untouched); `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/routes/quiz.py backend/tests/test_quiz_scoring_e.py
git commit -m "feat(learning-loop): PKG-11 — quiz submit sends Evidence when the loop is on

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 4: Flashcard rating → FSRS state

**Files:**
- Modify: `backend/learning/params.py` (add `FLASHCARD_RATING_TO_FSRS` †)
- Modify: `backend/routes/flashcards.py` (imports; `FlashcardRatingBody` docstring; `rate_card`; one helper)
- Modify: `backend/tests/test_learning_flashcards_fsrs.py` (append `TestRateCard`)

**Interfaces:**
- Consumes: `learning.gate.learning_loop_active`, `learning.fsrs.next_state`, `learning.fsrs.interval`, `learning.params.FSRS_RETENTION_DEFAULT`, `learning.params.FLASHCARD_RATING_TO_FSRS`, `services.timestamps.parse_ts`.
- Produces: `routes.flashcards._fsrs_advance(row, fsrs_rating, now) -> dict` (the five FSRS payload keys).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_learning_flashcards_fsrs.py`:

```python
# ── rate_card ────────────────────────────────────────────────────────────────

# Real "now" at import: the route reads the clock itself, so due/elapsed
# fixtures are relative to it (a run takes seconds; tolerances are minutes).
NOW = datetime.now(timezone.utc)
TWO_DAYS_AGO = (NOW - timedelta(days=2)).isoformat()


def _rate_tables(row: dict):
    """table() stand-in for rate_card: one select hit, an update that records
    its payload on `calls`."""
    calls: dict = {}

    def _select(cols, **kw):
        calls["select_cols"] = cols
        return [dict(row)]

    def _update(payload, **kw):
        calls["update"] = payload
        return [{"id": row["id"]}]

    def side_effect(name):
        m = MagicMock()
        if name == "flashcards":
            m.select.side_effect = _select
            m.update.side_effect = _update
        else:
            m.select.return_value = []
        return m
    return side_effect, calls


def _rate(rating: int, *, gate: bool, row: dict, next_state=None, interval=None):
    side_effect, calls = _rate_tables(row)
    ns = next_state or MagicMock(return_value=(4.5, 9.0))
    iv = interval or MagicMock(return_value=8.0)
    with (
        patch("routes.flashcards.table", side_effect=side_effect),
        patch("routes.flashcards.learning_loop_active", return_value=gate),
        patch("routes.flashcards.next_state", new=ns),
        patch("routes.flashcards.interval", new=iv),
        patch("routes.flashcards.check_achievements"),
    ):
        r = client.post("/api/flashcards/rate", json={
            "user_id": USER_ID, "card_id": "card-1", "rating": rating,
        })
    return r, calls, ns, iv


FRESH_ROW = {"id": "card-1", "times_reviewed": 0, "last_reviewed_at": None,
             "fsrs_d": None, "fsrs_s": None, "reps": 0, "lapses": 0}
SEEN_ROW = {"id": "card-1", "times_reviewed": 3, "last_reviewed_at": TWO_DAYS_AGO,
            "fsrs_d": 5.2, "fsrs_s": 3.1, "reps": 3, "lapses": 1}


class TestRateCard:
    @pytest.mark.parametrize("ui_rating,fsrs_rating", [(1, 1), (2, 2), (3, 3)])
    def test_rating_map_forgot_hard_easy_to_again_hard_good(self, ui_rating, fsrs_rating):
        from learning.params import FLASHCARD_RATING_TO_FSRS

        assert FLASHCARD_RATING_TO_FSRS[ui_rating] == fsrs_rating
        r, calls, ns, _ = _rate(ui_rating, gate=True, row=SEEN_ROW)
        assert r.status_code == 200, r.text
        assert ns.call_args[0][2] == fsrs_rating

    def test_easy_is_never_emitted(self):
        from learning.params import FLASHCARD_RATING_TO_FSRS

        assert 4 not in FLASHCARD_RATING_TO_FSRS.values()

    def test_gate_on_selects_the_fsrs_columns(self):
        _, calls, _, _ = _rate(3, gate=True, row=SEEN_ROW)
        assert calls["select_cols"] == "id,times_reviewed,last_reviewed_at,fsrs_d,fsrs_s,reps,lapses"

    def test_gate_on_writes_state_beside_the_legacy_columns(self):
        r, calls, ns, iv = _rate(3, gate=True, row=SEEN_ROW)
        payload = calls["update"]
        assert set(payload) == LEGACY_RATE_KEYS | FSRS_KEYS
        assert payload["times_reviewed"] == 4 and payload["last_rating"] == 3
        assert payload["fsrs_d"] == 4.5 and payload["fsrs_s"] == 9.0
        assert payload["reps"] == 4 and payload["lapses"] == 1
        iv.assert_called_once()
        retention, s = iv.call_args[0]
        from learning.params import FSRS_RETENTION_DEFAULT
        assert retention == FSRS_RETENTION_DEFAULT and s == 9.0
        due = datetime.fromisoformat(payload["due_at"])
        written = datetime.fromisoformat(payload["last_reviewed_at"])
        assert abs((due - written) - timedelta(days=8.0)) < timedelta(seconds=1)
        assert r.json()["due_at"] == payload["due_at"]
        assert r.json()["fsrs_rating"] == 3

    def test_gate_on_passes_prior_state_and_elapsed_days(self):
        _, _, ns, _ = _rate(2, gate=True, row=SEEN_ROW)
        d, s, rating, days_since = ns.call_args[0]
        assert (d, s, rating) == (5.2, 3.1, 2)
        assert days_since == pytest.approx(2.0, abs=0.01)

    def test_gate_on_first_review_passes_none_state_and_zero_days(self):
        _, calls, ns, _ = _rate(3, gate=True, row=FRESH_ROW)
        d, s, _, days_since = ns.call_args[0]
        assert d is None and s is None and days_since == 0.0
        assert calls["update"]["reps"] == 1 and calls["update"]["lapses"] == 0

    def test_again_increments_lapses(self):
        _, calls, _, _ = _rate(1, gate=True, row=SEEN_ROW)
        assert calls["update"]["lapses"] == 2

    def test_gate_on_rejects_a_rating_outside_the_map_before_any_write(self):
        r, calls, ns, _ = _rate(5, gate=True, row=SEEN_ROW)
        assert r.status_code == 422
        assert "update" not in calls
        ns.assert_not_called()

    def test_gate_off_is_byte_identical(self):
        r, calls, ns, iv = _rate(5, gate=False, row=SEEN_ROW)   # legacy accepts any int
        assert r.status_code == 200
        assert r.json() == {"ok": True}
        assert calls["select_cols"] == LEGACY_RATE_COLS
        assert set(calls["update"]) == LEGACY_RATE_KEYS
        assert calls["update"]["times_reviewed"] == 4 and calls["update"]["last_rating"] == 5
        ns.assert_not_called()
        iv.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_flashcards_fsrs.py -q -k RateCard`
Expected: FAIL — `ImportError: cannot import name 'FLASHCARD_RATING_TO_FSRS' from 'learning.params'` and `AttributeError: <module 'routes.flashcards'> does not have the attribute 'learning_loop_active'`.

- [ ] **Step 3: Implement.**

`backend/learning/params.py` — append in the FSRS section, same style as PKG-02's entries:
```python
# PKG-11 † — flashcard UI rating (1 forgot / 2 hard / 3 easy, routes/flashcards.py)
# → FSRS rating (1 Again / 2 Hard / 3 Good). Easy(4) is never emitted in v1
# (spec §3.2 rating map). Engineering choice: the spec has no flashcard row.
FLASHCARD_RATING_TO_FSRS: dict[int, int] = {1: 1, 2: 2, 3: 3}
```
If PKG-02 exported rating names (check HANDOFF-02), use them as the values instead of literals.

`backend/routes/flashcards.py` imports:
```python
from learning.fsrs import interval, next_state, order_due
from learning.gate import learning_loop_active
from learning.params import FLASHCARD_RATING_TO_FSRS, FSRS_RETENTION_DEFAULT
from services.timestamps import parse_ts
```
(`order_due` is used in Task 5; importing it now keeps one import commit. `datetime`/`timedelta`/`timezone` — extend the existing `from datetime import …` line.)

Helper, above `rate_card`:
```python
_FSRS_AGAIN = min(FLASHCARD_RATING_TO_FSRS.values())  # 1 — the lapse rating


def _fsrs_advance(row: dict, fsrs_rating: int, now: datetime) -> dict:
    """PKG-11: the five FSRS columns after one rating (spec §3.2).

    Adapter around learning.fsrs.next_state/interval — if PKG-02's signature
    differs from HANDOFF-02's assumptions, change THIS function only.
    """
    last = parse_ts(row.get("last_reviewed_at"))
    days_since = max(0.0, (now - last) / timedelta(days=1)) if last else 0.0
    d_new, s_new = next_state(row.get("fsrs_d"), row.get("fsrs_s"), fsrs_rating, days_since)
    due_at = now + timedelta(days=interval(FSRS_RETENTION_DEFAULT, s_new))
    return {
        "fsrs_d": d_new,
        "fsrs_s": s_new,
        "due_at": due_at.isoformat(),
        "reps": (row.get("reps") or 0) + 1,
        "lapses": (row.get("lapses") or 0) + (1 if fsrs_rating == _FSRS_AGAIN else 0),
    }
```

`rate_card` body:
```python
    require_self(body.user_id, request)
    loop_on = learning_loop_active(body.user_id)

    fsrs_rating: int | None = None
    if loop_on:
        fsrs_rating = FLASHCARD_RATING_TO_FSRS.get(body.rating)
        if fsrs_rating is None:
            raise HTTPException(status_code=422, detail="rating must be one of 1, 2, 3")

    cols = "id,times_reviewed"
    if loop_on:
        cols = "id,times_reviewed,last_reviewed_at,fsrs_d,fsrs_s,reps,lapses"
    try:
        rows = table("flashcards").select(
            cols,
            filters={"id": f"eq.{body.card_id}", "user_id": f"eq.{body.user_id}"},
            limit=1,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not rows:
        raise HTTPException(status_code=404, detail="Flashcard not found")

    now = datetime.now(timezone.utc)
    current = rows[0]["times_reviewed"] or 0
    payload = {
        "times_reviewed": current + 1,
        "last_rating": body.rating,
        "last_reviewed_at": now.isoformat(),
    }
    if loop_on:
        payload.update(_fsrs_advance(rows[0], fsrs_rating, now))
    table("flashcards").update(payload, filters={"id": f"eq.{body.card_id}"})
    <achievement block unchanged>
    if loop_on:
        return {"ok": True, "due_at": payload["due_at"], "fsrs_rating": fsrs_rating}
    return {"ok": True}
```

The legacy `last_reviewed_at` value is `datetime.now(timezone.utc).isoformat()` today (:366); computing `now` once and reusing it produces the same string format, so the flag-off payload is unchanged.

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_flashcards_fsrs.py tests/test_flashcards_routes.py tests/test_flashcard_import_routes.py tests/test_learning_loop_invariants.py -q && venv/bin/ruff check .`
Expected: all passed (`test_learning_flashcards_fsrs.py`: 8 migration + 11 rate = 19); `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/learning/params.py backend/routes/flashcards.py backend/tests/test_learning_flashcards_fsrs.py
git commit -m "feat(learning-loop): PKG-11 — flashcard ratings advance FSRS state when the loop is on

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 5: Flashcard list — due-first ordering and `due_only`

**Files:**
- Modify: `backend/routes/flashcards.py` (`get_flashcards`; one helper)
- Modify: `backend/tests/test_learning_flashcards_fsrs.py` (append `TestListFlashcards`)

**Interfaces:**
- Consumes: `learning.fsrs.order_due`, `services.timestamps.parse_ts`.
- Produces: `GET /api/flashcards/user/{user_id}?due_only=true|false`; `routes.flashcards._order_due_rows(rows, now) -> list[dict]`; response key `due_count` (loop path only).

- [ ] **Step 1: Write the failing tests** — append:

```python
# ── get_flashcards ───────────────────────────────────────────────────────────

def _card(cid, *, created, due=None, s=None, d=None, reps=0, lapses=0):
    return {"id": cid, "user_id": USER_ID, "topic": "T", "offering_id": None,
            "front": "q", "back": "a", "times_reviewed": reps, "last_rating": None,
            "last_reviewed_at": None, "created_at": created,
            "fsrs_d": d, "fsrs_s": s, "due_at": due, "reps": reps, "lapses": lapses}


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# Query order is created_at.desc (newest first), as the route requests it.
LIST_ROWS = [
    _card("later-b", created="2026-09-26T00:00:00Z", due=_iso(NOW + timedelta(days=3)), s=6.0, d=5.0, reps=2),
    _card("fresh-new", created="2026-09-25T00:00:00Z"),
    _card("due-old", created="2026-09-24T00:00:00Z", due=_iso(NOW - timedelta(days=2)), s=2.0, d=5.0, reps=1),
    _card("fresh-older", created="2026-09-23T00:00:00Z"),
    _card("due-recent", created="2026-09-22T00:00:00Z", due=_iso(NOW - timedelta(hours=1)), s=4.0, d=5.0, reps=3),
    _card("later-a", created="2026-09-21T00:00:00Z", due=_iso(NOW + timedelta(days=1)), s=6.0, d=5.0, reps=2),
]


def _list(*, gate: bool, query: str = "", order_due=None):
    calls: dict = {}

    def side_effect(name):
        m = MagicMock()
        if name == "flashcards":
            def _select(cols, **kw):
                calls["select_cols"] = cols
                calls["select_kwargs"] = kw
                return [dict(r) for r in LIST_ROWS]
            m.select.side_effect = _select
        else:
            m.select.return_value = []
        return m

    od = order_due or MagicMock(side_effect=lambda rows, now: list(reversed(rows)))
    with (
        patch("routes.flashcards.table", side_effect=side_effect),
        patch("routes.flashcards.learning_loop_active", return_value=gate),
        patch("routes.flashcards.order_due", new=od),
    ):
        r = client.get(f"/api/flashcards/user/{USER_ID}{query}")
    return r, calls, od


class TestListFlashcards:
    def test_gate_on_selects_fsrs_columns_with_the_same_query(self):
        r, calls, _ = _list(gate=True)
        assert r.status_code == 200, r.text
        assert calls["select_cols"] == LEGACY_LIST_COLS + FSRS_COLS
        assert calls["select_kwargs"] == {"filters": {"user_id": f"eq.{USER_ID}"}, "order": "created_at.desc"}

    def test_gate_on_orders_due_then_fresh_then_later(self):
        r, _, od = _list(gate=True)
        ids = [c["id"] for c in r.json()["flashcards"]]
        # order_due is patched to REVERSE its input, proving the route honours
        # its output rather than the query order.
        assert ids == ["due-recent", "due-old", "fresh-new", "fresh-older", "later-a", "later-b"]
        od.assert_called_once()
        passed_ids = [c["id"] for c in od.call_args[0][0]]
        assert passed_ids == ["due-old", "due-recent"]
        assert r.json()["due_count"] == 2

    def test_gate_on_due_only_returns_the_due_bucket_only(self):
        r, _, _ = _list(gate=True, query="?due_only=true")
        ids = [c["id"] for c in r.json()["flashcards"]]
        assert ids == ["due-recent", "due-old"]
        assert r.json()["due_count"] == 2

    def test_gate_on_a_null_due_at_is_not_due(self):
        r, _, _ = _list(gate=True, query="?due_only=true")
        assert not any(c["id"].startswith("fresh") for c in r.json()["flashcards"])

    def test_gate_on_response_rows_carry_the_fsrs_columns(self):
        r, _, _ = _list(gate=True)
        first = r.json()["flashcards"][0]
        assert FSRS_KEYS <= set(first)

    def test_gate_off_is_byte_identical(self):
        r, calls, od = _list(gate=False, query="?due_only=true")
        assert r.status_code == 200
        assert calls["select_cols"] == LEGACY_LIST_COLS
        assert calls["select_kwargs"] == {"filters": {"user_id": f"eq.{USER_ID}"}, "order": "created_at.desc"}
        body = r.json()
        assert set(body) == {"flashcards"}, "no due_count on the legacy path"
        assert [c["id"] for c in body["flashcards"]] == [c["id"] for c in LIST_ROWS]
        od.assert_not_called()

    def test_gate_off_topic_filter_unchanged(self):
        r, calls, _ = _list(gate=False, query="?topic=T")
        assert calls["select_kwargs"]["filters"] == {"user_id": f"eq.{USER_ID}", "topic": "eq.T"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_flashcards_fsrs.py -q -k ListFlashcards`
Expected: `test_gate_on_*` FAIL — `assert 'id,user_id,…,created_at' == 'id,user_id,…,created_at,fsrs_d,…'` (the loop path does not exist yet); `test_gate_off_*` PASS already (they pin today's behaviour — that is the point).

- [ ] **Step 3: Implement.** Helper above `get_flashcards`:

```python
_LEGACY_LIST_COLS = (
    "id,user_id,topic,offering_id,front,back,times_reviewed,last_rating,"
    "last_reviewed_at,created_at"
)
_FSRS_LIST_COLS = ",fsrs_d,fsrs_s,due_at,reps,lapses"


def _order_due_rows(rows: list[dict], now: datetime) -> list[dict]:
    """PKG-11: due cards in learning.fsrs.order_due's order (|R − threshold|
    ascending, spec §3.2). Adapter: if HANDOFF-02's order_due wants a different
    input shape, build it here and map back to rows by id — change THIS
    function only."""
    if not rows:
        return []
    return list(order_due(rows, now))


def _loop_order(rows: list[dict], now: datetime) -> tuple[list[dict], list[dict]]:
    """Return (ordered rows, due rows): due first, then never-rated (query
    order), then not-yet-due by due_at ascending."""
    due, fresh, later = [], [], []
    for r in rows:
        due_at = parse_ts(r.get("due_at"))
        if due_at is not None and due_at <= now:
            due.append(r)
        elif r.get("fsrs_s") is None:
            fresh.append(r)
        else:
            later.append(r)
    later.sort(key=lambda r: parse_ts(r.get("due_at")) or now)
    ordered_due = _order_due_rows(due, now)
    return ordered_due + fresh + later, ordered_due
```

`get_flashcards` signature gains `due_only: bool = False` after `semester`. Body: compute `loop_on = learning_loop_active(user_id)` after `require_self`; `cols = _LEGACY_LIST_COLS + (_FSRS_LIST_COLS if loop_on else "")` replaces the literal at :313 (the flag-off string is the same characters); after the semester filter and before `return`:

```python
        if loop_on:
            now = datetime.now(timezone.utc)
            rows, due = _loop_order(rows, now)
            if due_only:
                rows = due
            return {"flashcards": rows, "due_count": len(due)}
        return {"flashcards": rows}
```

Keep the existing `try/except` and its "not found → empty list" degrade around all of it.

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_flashcards_fsrs.py tests/test_flashcards_routes.py tests/test_flashcard_import_routes.py tests/test_learning_loop_invariants.py -q && venv/bin/ruff check .`
Expected: all passed (`test_learning_flashcards_fsrs.py`: 26); `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/routes/flashcards.py backend/tests/test_learning_flashcards_fsrs.py
git commit -m "feat(learning-loop): PKG-11 — flashcard list orders due cards first when the loop is on

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 6: Hand-off + ledger

- [ ] **Step 1: Run the full self-check loop (below), including the E2E cycle.** The seeded student (`backend/db/seed_local_rich.py::USER_ACTIVE`) has no `user_settings.learning_loop_beta = true` row and the stack does not export `LEARNING_LOOP_ENABLED`, so `frontend/e2e/quiz.spec.ts` must still assert `+0.09` and `study-*.spec.ts` must still pass. If either fails, the flag-off path is not byte-identical — fix the route, never the spec.

- [ ] **Step 2:** Write `docs/superpowers/plans/learning-loop/HANDOFF-11.md` from `HANDOFF-template.md`. Required content beyond the template headings:
  - **Symbols added**: `routes.quiz._quiz_evidence`, `routes.quiz._mastery_span`, `routes.flashcards._fsrs_advance`, `routes.flashcards._order_due_rows`, `routes.flashcards._loop_order`, query param `GET /api/flashcards/user/{id}?due_only`, response keys `due_count` (list) and `due_at`/`fsrs_rating` (rate), columns `flashcards.fsrs_d/fsrs_s/due_at/reps/lapses`, index `flashcards_due_idx`, `learning.params.FLASHCARD_RATING_TO_FSRS`.
  - **Constants chosen**: `FLASHCARD_RATING_TO_FSRS = {1: 1, 2: 2, 3: 3} †`; `FSRS_RETENTION_DEFAULT` used unconditionally for flashcards.
  - **Known gaps**: (a) flashcards ignore `FSRS_RETENTION_EXAM`/`LARGE_SET` (PKG-12); (b) a never-rated card is not "due" under `due_only` (PKG-12 decides); (c) `due_only` is silently ignored when the gate is false; (d) no successive-relearning on flashcards; (e) same-session quiz re-checks are not weighted (`same_session_recheck` stays default — the quiz has no session id); (f) `Study.tsx` does not yet show `due_count` (PKG-13).
  - **Open questions**: whether `mastery_before`/`mastery_after` on the loop path should be BKT `p_known` (what PKG-03 returns) or a legacy-scaled number for the results screen — this package reports what the graph returned.
  - **A section headed `## For PKG-14 (cutover)`** stating verbatim: "`frontend/e2e/quiz.spec.ts:56–57` (`EXPECTED_DELTA = masteryAfter(0, QUIZ_LENGTH, QUIZ_LENGTH)`, the `+0.09` pin), `frontend/e2e/support/quiz.ts:58` (`masteryAfter`) and `backend/tests/test_quiz_scoring_e.py::TestMasteryModelSeam` are LEGACY-PATH pins. They hold today because the seeded student is opted out. At cutover (spec §11) the seeded student moves to the loop path, `mastery_after` is deleted, and the pin becomes the BKT posterior the function-mode constants produce for 3/3 `mc` correct from `SEEDED_MASTERY` — recompute it from `learning.bkt` with the `mc` channel, do not hard-code. Update the spec, the support helper and the backend test in the same commit as the deletion (docs/quiz-mastery-model.md §Constraint)."
  - **Verify commands** — exactly these three lines:

```
cd backend && venv/bin/python -m pytest tests/test_learning_flashcards_fsrs.py tests/test_quiz_scoring_e.py -q → all passed
ls backend/db/migrations/*_learning_flashcards_fsrs.sql                                          → 1 file
grep -c "learning_loop_active" backend/routes/quiz.py backend/routes/flashcards.py               → ≥ 1 each
```

- [ ] **Step 3:** Append the ledger row: `| 11 | quiz-flashcards | done | feat/learning-loop-11-quiz-flashcards | <sha> | 33 (26 flashcards_fsrs + 7 scoring_e) | — | HANDOFF-11.md |`. Add to Deviations: `PKG-11: spec has no flashcard-UI→FSRS rating row → FLASHCARD_RATING_TO_FSRS = {1:1, 2:2, 3:3} in params.py → the UI has three buttons and Easy(4) is never emitted in v1 → †`. Add any HANDOFF-02/03 signature adaptation as its own Deviation line.

- [ ] **Step 4: Commit**

```
git add docs/superpowers/plans/learning-loop/HANDOFF-11.md docs/superpowers/plans/learning-loop/LEDGER.md
git commit -m "docs(learning-loop): PKG-11 — hand-off and ledger

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

### Task 7: PR

- [ ] **Step 1:** Run the self-check loop once more, end to end.

- [ ] **Step 2:**

```
git push -u origin feat/learning-loop-11-quiz-flashcards
gh pr create --title "feat(learning): PKG-11 quiz-flashcards" --body-file - <<'EOF'
Learning loop series, package 11 of 15. Spec: docs/superpowers/specs/2026-09-26-learning-loop-design.md §3.2, §4, §5, §7.

- routes/quiz.py::submit_quiz: when learning_loop_active(user_id), one Evidence dict per graded question (channel "mc") goes to apply_graph_update; mastery_after and the quiz_correct/partial/confusion event_type are not computed. Gate off: byte-identical legacy delta.
- routes/flashcards.py::rate_card: gate on → FSRS Again/Hard/Good from the 1/2/3 UI rating, next_state + interval → fsrs_d/fsrs_s/due_at/reps/lapses beside the legacy columns. Gate off: identical select and payload.
- routes/flashcards.py::get_flashcards: gate on → FSRS columns, due-first ordering via learning.fsrs.order_due, ?due_only=true, due_count. Gate off: identical query and response.
- migration <ts>_learning_flashcards_fsrs.sql (spec §4 verbatim).
- test_inv_01 widened to routes/quiz.py + routes/flashcards.py (post-hoc to PKG-03; HANDOFF-03 updated).
- FLASHCARD_RATING_TO_FSRS † in learning/params.py.

The E2E seeded student stays on the legacy path: frontend/e2e/quiz.spec.ts's +0.09 pin is unchanged and green. HANDOFF-11.md tells PKG-14 how that pin changes at cutover.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
```

## Self-check loop (run after every task, and once more before the PR)

1. `cd backend && venv/bin/ruff check . && venv/bin/ruff format --check learning tests/test_learning_*.py`
2. `venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q`
3. `venv/bin/python -m pytest tests/ -q` (no `SAPLING_MODEL_MODE` exported)
4. Prompts/tool descriptions touched? **No** in this package → skip evals. (If you find yourself editing anything under `backend/agents/`, stop: scope creep. The quiz-context prompt file `quiz_context_update.txt` is out of scope too.)
5. Request-path agent or route touched? **Yes** — `routes/quiz.py::submit_quiz` and both flashcard handlers → run the E2E cycle after Task 5 and again before the PR, all inside ONE lock:
   ```
   flock /tmp/claude-$(id -u)/sapling-e2e-stack.lock sh -c '
     make e2e-up &&
     (cd frontend && npx playwright test e2e/quiz.spec.ts e2e/quiz-journeys.spec.ts e2e/quiz-errors.spec.ts e2e/quiz-integration.spec.ts e2e/study-semester.spec.ts e2e/study-recent-guides.spec.ts) &&
     (cd backend && venv/bin/python -m e2e_oracles);
     make e2e-down'
   ```
   Expected: every journey passed (the quiz mastery journey still asserts `+0.09`); oracles exit 0. No new `E2E_*` constants: no agent task was added.
6. Scope check: `git diff --stat main...HEAD` — every path must be in this prompt's Files lists. Anything else: `git checkout main -- <path>` or record a Deviation.
7. Sync check: `grep -o "E2E_[A-Z_]*" backend/agents/function_handlers_e2e.py | sort -u` unchanged from `main`.

Green = all seven clean. Max 5 iterations per loop; then write a `BLOCKED` row in `LEDGER.md` with hypothesis, commands, outputs, and stop.

## Regression guard

- Pre-series suite count N₀ (from State of the world) must be unchanged except for the 33 tests this package adds. Zero failures, zero new skips.
- Dependency modules unchanged and green: `tests/test_learning_fsrs.py` (PKG-02), `tests/test_learning_evidence_apply.py` + `tests/test_graph_service.py` (PKG-03), `tests/test_learning_gate.py` (PKG-00).
- Pre-series suites this package's routes are covered by, unchanged and green: `tests/test_quiz_routes.py` (esp. `TestSubmitQuizMasteryWrite` — the legacy `updated_nodes` payload pin), `tests/test_quiz_scoring_e.py::TestMasteryModelSeam` (the `0.03/0.02` and `+0.09` pins — no line of it changes), `tests/test_quiz_lifecycle_d.py`, `tests/test_quiz_answers_c.py`, `tests/test_quiz_abandon_g4.py`, `tests/test_quiz_gamification_g8.py`, `tests/test_quiz_context_repair.py`, `tests/test_flashcards_routes.py`, `tests/test_flashcard_import_routes.py`, `tests/test_seed_quiz_fixture.py`, `tests/test_event_capture_seams.py`.
- With `LEARNING_LOOP_ENABLED` unset: `submit_quiz`, `rate_card`, `get_flashcards` issue the same queries with the same column strings, the same filters, the same update payload key sets, and return the same response keys as on `main` (the `gate_off` tests are the proof; the E2E quiz lane is the second proof).
- `git diff main...HEAD -- backend/services/quiz_config.py frontend/e2e backend/db/seed_local_rich.py backend/agents backend/services/graph_service.py` is empty.

## Acceptance criteria (the next session pastes these)

1. `cd backend && venv/bin/python -m pytest tests/test_learning_flashcards_fsrs.py tests/test_quiz_scoring_e.py -q` → `all passed` (55: 26 + 29)
2. `ls backend/db/migrations/*_learning_flashcards_fsrs.sql` → `1 file`
3. `grep -c "learning_loop_active" backend/routes/quiz.py backend/routes/flashcards.py` → `≥ 1 each`
4. `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k inv_01` → `1 passed`
5. `cd backend && venv/bin/python -m pytest tests/ -q` → zero failures
6. `cd backend && venv/bin/ruff check .` → `All checks passed!`
7. `grep -c "FLASHCARD_RATING_TO_FSRS" backend/learning/params.py backend/routes/flashcards.py` → `≥ 1 each`
8. `grep -n "0\.03\|0\.02\|0\.09\|0\.9\b\|0\.33" backend/routes/quiz.py backend/routes/flashcards.py` → no NEW hits versus `main` (`git diff main...HEAD -- backend/routes | grep -E "^\+.*(0\.03|0\.02|0\.09|0\.9\b|0\.33)"` prints nothing)
9. `git diff --stat main...HEAD` lists only: `backend/routes/quiz.py`, `backend/routes/flashcards.py`, `backend/learning/params.py`, `backend/db/migrations/*_learning_flashcards_fsrs.sql`, `backend/tests/test_learning_flashcards_fsrs.py`, `backend/tests/test_quiz_scoring_e.py`, `backend/tests/test_learning_loop_invariants.py`, `docs/superpowers/plans/learning-loop/{HANDOFF-11.md,HANDOFF-03.md,LEDGER.md}`.
10. `LEDGER.md` has rows `03 | evidence-state | reopened | …` and `11 | quiz-flashcards | done | …`, and `HANDOFF-11.md` has a `## For PKG-14 (cutover)` section naming `frontend/e2e/quiz.spec.ts` and `+0.09`.
11. E2E (under the lock): `frontend/e2e/quiz.spec.ts` passed with the `+0.09` assertion intact; oracles exit 0.

## Hand-off

`docs/superpowers/plans/learning-loop/HANDOFF-11.md` per the template; the Verify commands block is fixed above (Task 6). Fixed extra section: `## For PKG-14 (cutover)` (Task 6 gives the text). Open questions to record: the loop-path `mastery_before/after` semantics for the results screen (BKT posterior vs a display scale); whether PKG-12's review surface should reuse `_loop_order` or own its ordering; whether `due_only` should 400 when the gate is false instead of being ignored.

## Do not

- Do not change `services/quiz_config.py`, `frontend/e2e/quiz.spec.ts`, `frontend/e2e/support/quiz.ts`, `backend/db/seed_local_rich.py` (no `learning_loop_beta` for the seeded student), `frontend/src/components/screens/Study.tsx`, `frontend/src/lib/api.ts`, `services/graph_service.py`, `learning/fsrs.py`, `learning/evidence.py`, or anything under `backend/agents/`. The legacy delta is deleted by PKG-14, not here.
- Do not write `graph_nodes`, `graph_edges`, `node_mastery_events`, or `learner_state` from a route; `apply_graph_update` is the only writer (spec §8 (1); Task 1 makes the test say so).
- Do not call the gate more than once per request, and never inside `services/chat_stream.py`.
- Do not emit `"mc_reasoned"` from the quiz; no reason text exists on the wire. Do not copy student `confidence` into `Evidence.confidence`.
- Do not swallow a `next_state`/`interval` failure into a legacy-only write on the loop path.
- Do not add events; `EVENT_TAXONOMY` and its pin test are untouched.
- All Supabase access through `db/connection.py::table()`; no `httpx`, no `supabase` import. Never filter on `front`/`back` (encrypted).
- Migrations: UTC-timestamp prefix, `_learning_` infix, append-only, never edited after creation. Exactly one migration in this package.
- No `lru_cache` in this package.
- No numeric literal from the Named-constants table in route code; `FLASHCARD_RATING_TO_FSRS` and `FSRS_RETENTION_DEFAULT` are imported from `learning/params.py`.
- Do not skip, xfail, rename, or delete any pre-existing test (including `test_inv_01_single_graph_writer`'s name). Do not hand-edit eval cassettes or baselines.
- Logscan `ALLOWLIST` in `backend/e2e_oracles/logscan.py` stays `()`.
- Every E2E cycle inside one `flock` on `/tmp/claude-$(id -u)/sapling-e2e-stack.lock`; always `make e2e-down`.
- End every commit with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`; end the PR body with the Claude Code attribution line.

## If you get stuck

1. Re-read §Spec, HANDOFF-02 and HANDOFF-03 §Symbols added, and the spec file's §3.2/§5/§7 before guessing. A signature mismatch is fixed in the two adapters (`_fsrs_advance`, `_order_due_rows`) and `_mastery_span`, plus the matching test stubs — then a Deviation line.
2. If the E2E quiz journey's `+0.09` fails: the flag-off path is not byte-identical, or the seed/stack accidentally enables the loop. Check `grep -rn "learning_loop_beta\|LEARNING_LOOP_ENABLED" backend/db/seed_local_rich.py scripts/e2e-up.sh .github/workflows/e2e.yml` (expected: no hits) before touching the route.
3. Three failed iterations on one task → append a `BLOCKED` row to `LEDGER.md` (hypothesis, commands run, outputs), commit what is green, open the PR as draft, stop.
4. Never widen scope to unblock. Never disable a test to unblock.
5. Ambiguity → choose the option closest to the spec, mark it `†` in the hand-off, continue.
