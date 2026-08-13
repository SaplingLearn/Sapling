# Handoff — quiz backend batch (epic #537)

Paste everything below the line into a fresh session. It is self-contained.

---

You are picking up the **pre-revamp quiz backend batch** in `~/Projects/sapling` (epic #537).
Five of six workstreams are merged to `main`. Read this whole brief before touching anything.

## Where things stand

| | Issue | PR | State |
|---|---|---|---|
| A — adaptive difficulty, `/api/quiz/config`, error envelope | #540 | #547 | **merged** |
| B — adaptive context loop (#529) | #529 | #548 | **merged** |
| C — server-authoritative grading | #541 | #549 | **merged** |
| D — attempt lifecycle | #542 | #550 | **merged** |
| E — scoring seam, generation honesty | #543 | #551 | **merged** |
| F — cost, abuse, observability | #544 | **#552** | **OPEN — finish this first** |

Every merged PR went through: TDD (test written first, watched fail), a full local E2E cycle
(Playwright + oracles + integration lane), and an `xhigh`/`high` multi-agent code review whose
findings were fixed before merge. Reviews caught **44 real defects in my own fixes** across the
four reviewed PRs — assume the same rate applies to your work and budget for it.

### Your first task: land #552

Branch `feat/544-quiz-cost-observability` is pushed with review fixes committed
(`14854788`). When I stopped, its verification cycle had passed Playwright (45) and the
oracles (0 findings) and was still running the integration lane. Re-run the full cycle,
then merge.

```bash
# ALWAYS one flock around the whole up→test→down cycle. Never separate calls.
cd ~/Projects/sapling
export SAPLING_MODEL_MODE=function
export SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e   # e2e-up does NOT set these
rm -rf frontend/test-results frontend/e2e/results               # stale artifacts poison review
flock /tmp/claude-1000/sapling-e2e-stack.lock -c '
  make e2e-up
  (cd frontend && npx playwright test)
  (cd backend && venv/bin/python -m e2e_oracles)
  (cd backend && RUN_INTEGRATION=1 venv/bin/python -m pytest tests/integration -m integration -q)
  make e2e-down'
```

Read pass/skip **counts**, never the exit code — the integration lane once reported
"1 passed / 27 skipped, exit 0" and was believed for weeks.

## The addendum you must action

The user delivered an addendum mid-batch. Parts 3 and 4 are **already filed as issues**
(#553–#561, listed at the bottom). **Part 2 is not done** — that is your main body of work
after #552 merges.

### Part 2 — was meant to fold into E and F

E merged before the addendum arrived, so E5–E8 **cannot** fold into it. Ship them as one
new PR against #543 (reopen it or open a follow-up). F5–F7 can still fold into #552 if you
get there before merging it; otherwise same treatment.

**E5. Question identity + provenance.** Into the existing `questions_json` shape (no
migration): a stable `question_hash` from the normalized stem + option set, the retrieved
chunk ids that grounded it, the served model, and `prompt_version`. Chunk ids are discarded
today after prompt assembly (`_course_material_block` returns a formatted string — you must
thread ids out of it); the prompt hash exists only as `_PROMPT_HASH` in `agents/quiz.py`
trace metadata. Then use `question_hash` for the within-attempt duplicate check instead of
the current stem-string comparison.

⚠️ The user explicitly said: **if E5's chunk threading turns out substantially bigger than
described, stop and report before building.** Same for E7's migration.

**E6. Repetition guard.** Past `questions_json` for a concept is never re-read, so a student
can be served the same question repeatedly with nothing detecting it. At generation, pull the
last ~15 stems (hashes once E5 lands) for this student+concept and pass them as a
do-not-repeat list. Precomputing this into the `quiz_context` digest is the preferred
end-state; fetching raw is acceptable now — **note which you did**.

**E7. Stop dropping `event_type`.** Submit computes correct/partial/confusion from the score
ratio and then discards it when writing `node_mastery_events`
(`services/graph_service.py` ~:740). The column doesn't exist — small migration, persist the
value, keep the write backward-compatible for non-quiz callers.

**E8. Grounding is a silent accident.** A course with no indexed chunks generates ungrounded
questions with no signal. Add a coverage check before generation, record grounded-vs-not and
k-chunks on the attempt. **Do not block generation on it.**

**F5. Silent-empty detection — the general fix.** Three personalization inputs returned zero
rows for months with no error (`quiz_context`'s 42P10, class misconceptions' wrong id filter,
the digest keys that never matched). Nothing distinguishes *legitimately empty* from *empty
because the query is wrong*. Add a shared helper every agent tool routes its result through:
zero rows for a user who plausibly should have data (has attempts / enrollments / a populated
graph) → WARN + a `quiz.tool_empty` event carrying the tool name. **Put it somewhere the
tutor can use it too** — this is the piece that stops a fourth instance of this bug class.

**F6. Measure the prompt before anyone tunes it.** `llm_usage.prompt_tokens` already records
truth per call. Emit enough dimensionality (which blocks were included, k chunks, digest
present or absent) to attribute tokens to sections. The audit estimates ~2–4k in today —
**verify rather than inherit it.**

**F7.** Add `quiz.tool_empty` and `quiz.rag_uncovered` to the pinned event taxonomy
(`services/events_service.py::EVENT_TAXONOMY`, plus the pin test in
`tests/test_event_capture_seams.py`).

### Blocker you must raise with the user

The addendum says *"Commit both audit documents to `docs/audits/` if they aren't already"* —
`docs/audits/student-data-inventory.md` and `student-signals.yaml`, pinned at `7681c481`.
**Neither file exists in the repo and neither was provided.** `find` across the tree returns
nothing. Ask for them; don't reconstruct them from the addendum's summary.

## Answers to the addendum's Part 1 (already established — don't redo)

1. **C2 storage:** normalized **`quiz_responses` table**, not the encrypted blob. Migration
   `20260812214402_quiz_responses.sql`. Columns: `attempt_id` (FK cascade), `question_index`,
   `selected_index`, `is_correct`, `time_ms`, `confidence`, `answered_at`, with
   `UNIQUE (attempt_id, question_index)` as the idempotency contract.
2. **Blob race:** N/A — the table was chosen, so there is no decrypt-modify-re-encrypt path.
3. **Table rationale:** written durably in the migration's header comment (plaintext
   behavioural scalars, same category as the already-plaintext `score`/`total` per #521; no
   free text in the table, so nothing needs encrypting). **Still owed:** confirm the
   encryption oracle's column manifest (`backend/e2e_oracles/gather.py` ~:195) was a
   deliberate non-update — `quiz_responses` is absent from it by design, and that should be
   stated where the manifest lives, not only in the migration.
4. **B completeness — both extra bugs were fixed**, in #548's review-fix commit, not left
   for follow-up:
   - the coercer now reads `common_mistakes` (the key the agent actually writes) alongside
     the legacy `misconceptions`/`common_errors` — `_SUMMARY_LIST_KEYS`,
     `agents/tools/quiz_history.py:68`;
   - `recommended_difficulty` now has a reader and reaches the digest as
     "Recommended next difficulty: …" (same file, ~:112).
   A later review also caught that the *coercer rewrite itself* had introduced a bug —
   non-list values under list-shaped keys were iterated per character, spraying
   `- r`/`- e`/`- c` into the prompt. Guarded with `isinstance(list)`.
5. **D3 blast radius (measured, both environments):**
   | | attempts | `completed_at` | `score` | `quizzes_10` |
   |---|---|---|---|---|
   | prod | 58 | 2 | 2 | **granted 2026-08-12** |
   | staging | 2 | 0 | 0 | not granted |

   One user holds every prod attempt; 56 of 58 were never scored. Their stat drops **58 → 2**.
   Nothing is revoked: `check_achievements` drops already-earned triggers *before* evaluating
   the stat, and there is **no revocation path in the codebase at all** (`user_achievements`
   is insert-only — verified). Posted as a comment on #542.
6. **Citations vs reality:** all ten Rule-0 claims re-verified against `origin/main` before
   any change; **nine confirmed, one overstated** — the audit said nothing reads attempt
   history, but `agents/tools/quiz_history.py::read_recent_quiz_attempts` has always read the
   last five completed attempts and is one of three tools generation calls. No *HTTP* route
   read it (D added one). The #529 42P10 finding was additionally **live-DB verified** —
   staging `pg_constraint` shows only the PK and two FKs, 0 rows, 0 duplicate pairs.
   **The misconceptions id mismatch is still code-only and unverified** — that is #553's
   first instruction.

## What the six merged workstreams actually changed

Read `backend/routes/quiz.py` — it is the centre of all of it. Then
`services/quiz_config.py` (every tunable lives there with its reasoning) and
`services/quiz_errors.py` (the coded error envelope).

- **A** — `adaptive` is a real difficulty resolved by the agent and echoed as
  `resolved_difficulty`; `GET /api/quiz/config` is the single source of selector truth
  (`QuizPanel` builds its selects from it); every quiz 4xx/5xx returns
  `{error:{code,message,detail?,request_id}}` with the legacy `detail` key preserved.
  The 10-question cap is **measured, not chosen**: 15- and 20-question schemas are
  *rejected outright* by gemini-2.5-flash-lite ("too many states for serving") —
  `scripts/bench_quiz_question_cap.py`.
- **B** — UNIQUE restored (`20260812210033`), the swallow replaced with ERROR log +
  `quiz.context_write_failed` event + re-raise under `config.IS_LOCAL`, the digest reader
  widened, and `/api/admin/analytics/errors` re-keyed from the `error.*` **name prefix** to
  `category = error` so non-HTTP failures actually appear.
- **C** — `POST /api/quiz/attempts/{id}/answer` (owner-checked, 409 after completion,
  idempotent on `(attempt_id, question_index)`, optional `question_id` cross-check),
  `quiz_responses`, `include_answer_key` (default true, logged, removal tracked in **#546**),
  and submit reconciling recorded responses over the payload — persisting **what it graded**.
- **D** — mastery snapshot on the attempt, derived status (`completed_at` → completed,
  `abandoned_at` → abandoned, else in_progress) with a 24h TTL that respects answer
  activity, resume, paginated history, completed-**and-scored**-only achievements.
  `_strip_answer_key` is an **allowlist** — it previously shipped `explanation` (which names
  the answer in prose) and passed unknown stored shapes through intact.
- **E** — mastery model is a named seam (`mastery_after()`), **numbers unchanged**, options
  written up in `docs/quiz-mastery-model.md`. `requested_count`/`delivered_count` reported
  and surfaced in the UI. The top-up retry gates on **questions actually dropped** (an
  earlier version fired on every ordinary generation and discarded its own retry).
- **F (in flight)** — per-user rate limit with `Retry-After` **refunded on failure**, a
  **paged** daily spend read (an unpaged one plateaued below the cap and could never trip),
  per-run generation timeouts that preserve partial quizzes, `quiz.generation_failed` events.

## Non-negotiables

- **The `#393` E2E journey is a wire contract.** `agents/function_handlers_e2e.py` pins a
  fixed 3-question quiz with correct labels **B, C, A**, and `frontend/e2e/quiz.spec.ts`
  asserts **+0.09** mastery three ways. Changing the mastery model means updating that
  journey **in the same commit** with a comment saying why. The seam also returns 3 questions
  regardless of what was requested — that is what exposed E's miskeyed top-up.
- **Real DB for DB assertions.** The hermetic suite mocks `table()`, which is exactly why
  #529 survived 51 days. Encryption round-trips, constraint behaviour and IDOR negatives go
  in `backend/tests/integration/` (the hermetic lane stubs `require_self` to a no-op, so it
  *structurally cannot* test ownership).
- **Migrations:** append-only, UTC-timestamp prefix (`date -u +%Y%m%d%H%M%S`), idempotent DDL,
  applied to staging **before** the merge (`venv/bin/dotenv -f .env.staging run -- venv/bin/python -m db.migrate`).
- **Code review gates the merge** — run it on each PR *before* merging, never as a wrap-up.
- **Subagents switch the primary checkout's branch.** A review workflow silently moved the
  tree mid-run and a commit landed on the wrong branch. Check `git branch --show-current`
  immediately before every `git add`.

## Issues filed and waiting

**Workstream H — after #552:** #553 (misconceptions id mismatch — *verify live first*),
#554 (mine `answers_json` into the digest + schema version), #555 (exam proximity, dates
only), #556 (cheap blind spots, behind F6), #557 (unify mastery-tier thresholds).

**Out of scope, filed so they don't evaporate:** #558 (no k-anonymity floor on class
aggregates, propose n≥5), #559 (leaderboard exposure), #560 (RAG chunks never term-scoped or
deleted), #561 (stale security docs + ADR 0025's unscheduled `chunk_text` gap).

**Also open:** #546 (flip then delete `include_answer_key`), #545 (the batch's cross-cutting
test gate).

A published report of the verification, forensics, blast radius and cap measurements:
https://claude.ai/code/artifact/063b9b21-0216-492c-80e2-dfc40503b65b
