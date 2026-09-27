# PKG-06b ai-budget-and-usage — Learning Loop series (9 of 17)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> You are a fresh session. Nothing outside this file, `docs/superpowers/plans/learning-loop/LEDGER.md`, `HANDOFF-01.md`/`HANDOFF-03.md`/`HANDOFF-05.md`/`HANDOFF-05b.md`/`HANDOFF-06.md`, and the files this prompt lists is known to you. Do not infer intent from chat history you do not have. Do not read the whole research corpus; read the sections named below.

## Package id + goal

**PKG-06b `ai-budget-and-usage`.** After this package: `backend/services/ai_budget.py` enforces the owner-approved per-student caps and the degradation ladder of spec §3.5 (band-aware daily $, monthly $, daily tokens, per-session request caps, a grader cap, a per-user rate limit, a platform alert) from ONE `llm_usage` read per request, and never calls a model; `ai_budget.check(` runs before every `grader`, `grader_second` and `decision` run (reopen commits of PKG-05 and PKG-05b), so a capped attempt writes no evidence for EITHER outcome; `enforce_rate_limit` is a ready FastAPI dependency whose 429 body is `{"detail": "ai budget reached", "reset_at": …}`; `ai.budget_capped` is in the taxonomy; every `llm_usage` row now records `cached_tokens` and `thinking_tokens` and bills cached input at the cached rate (A21). Nothing a student sees changes: PKG-07 attaches the tutor checks and the rate limit, PKG-09 the close check, PKG-12 the review pause. `tests/test_learning_ai_budget.py`, `test_inv_23` and the cap half of `test_inv_28` prove it.

Depends on (spec §14): **03, 06** (code — PKG-06 provides `learning/policy.py`'s `Band`, `Tier`, `BudgetLevel` aliases this module imports). The series runs strictly one package at a time in the §14 order (… 05, 05b, 06, **06b**, 07 …), so PKG-05, PKG-05b and PKG-06 are merged before you start; you wire `ai_budget.check` into the PKG-05 and PKG-05b run sites as reopen commits (Task 7).

Branch: `feat/learning-loop-06b-ai-budget-and-usage`. PR title: `feat(learning): PKG-06b ai-budget-and-usage`.

## Read before you start (in this order)

0. `docs/superpowers/specs/2026-09-26-learning-loop-design.md` **§13 Amendments log** — in force; where this file and §13 disagree, §13 wins. Your rows: **A20** (cost guard), **A21** (usage observability), A15 (the tier ceiling you return), A22 (grader-cap symmetry), A14 (the loop is the default for every student at launch, dark during the build). Re-read it before Task 1. Then §3.5–§3.6 (cost/routing/decision constants), §7 (two-phase gate), §8 (invariants 13–29), §14 (order and dependencies).
1. `docs/superpowers/plans/learning-loop/LEDGER.md` — refuse to start if any row is `blocked` or `in-progress`. Rows 00–06 and 05b must be `done` or `verified`.
2. `HANDOFF-05b.md`, `HANDOFF-05.md`, `HANDOFF-06.md`, `HANDOFF-03.md`, `HANDOFF-01.md` — "Symbols added" and "Post-hoc changes". Before Task 1 write down (a lookup, not a deviation; a differing name → use the real one everywhere):
   - `agents/grader.py`: `async def grade(item, *, format, student_answer, deps) -> GradeResult`, `GradeResult(unavailable=True)`, the agent `grader_agent`, and EVERY function holding a `grader_agent.run(` (this prompt: `_run_once(message, deps, *, second_opinion=False)` holds both the first run and the `grader_second` run; `grade` catches `UsageLimitExceeded`/`UnexpectedModelBehavior` into `unavailable`).
   - `services/decisions.py::_run_decision(decision, state, deps)` — the ONLY `decision_agent.run(` (agent in `agents/decision.py`); it returns `None` when unavailable and its callers turn `None` into their unavailable path.
   - `learning/policy.py`'s `Band`, `Tier`, `BudgetLevel` aliases (PKG-06).
   - PKG-05's `test_inv_28_symmetric_missingness` outage half: its locals `item`, `check` (`agents.tools.check`), `SaplingDeps`, `asyncio`, and its `grade_answer(item, answer, deps=deps, node_id=…)` call shape.
3. `CLAUDE.md` §Conventions and §Gotchas — the standing rules the "Do not" list below repeats (all Supabase through `db/connection.py`, append-only timestamped migrations, `lru_cache` rules, the E2E stack lock).
4. Spec §3.5 in full (Budget table, **Degradation ladder**, "At the hard level these keep working", **Validity rule for every cap**), §3.4 (`GRADER_LIMITS`, second opinion), §4 (the PKG-06b DDL), §6 (`ai.budget_capped`), §8 invariants 5, 23, 28, §9 (the rate limit applies to every model-calling loop route, never to `GET /status` or `GET /sessions`), §11.1 item 4 (what the launch gate later checks from this package).
5. `docs/superpowers/plans/learning-loop/README.md` — series conventions ("Touching an earlier package's code"). `HANDOFF-template.md` — what you write at the end.
6. Code you will modify: `backend/config.py` (env style, :1–60), `backend/learning/params.py` (append only), `backend/services/llm_pricing.py:29–40` (`MODEL_PRICING`) and `:103–132` (`cost_usd`), `backend/services/events_service.py:97–170` (`EVENT_TAXONOMY` + the docstring table above it) and `:229–268` (`log_llm_usage`), `backend/agents/usage.py:105–135` (`record_agent_usage`), `backend/tests/test_event_capture_seams.py:84–` (`test_event_taxonomy_is_pinned`), `backend/tests/conftest.py:63–86` (the autouse reset fixtures), `backend/main.py:208–272` (exception handlers), `backend/agents/grader.py` (`grade`, `_run_once`), `backend/services/decisions.py` (`_run_decision`), `backend/tests/test_learning_loop_invariants.py` (`test_inv_28` from PKG-05).
7. Code you will mirror: `backend/db/connection.py:160–232` (`page_all`, `MAX_ROWS` — an unpaged read past 1000 rows truncates silently), `backend/services/auth_guard.py:68–86` (`get_session_user_id`), `backend/routes/extract.py:27–41` (a 429 dependency with `Retry-After`), `backend/services/request_context.py:31–49` (`current_request_id`), `backend/tests/test_events_service.py:15–50` (fake `events_service.table` + `flush_now()`), `backend/tests/test_agent_usage.py`, `backend/db/migrations/0035_observability.sql:45–62` (`llm_usage`: `user_id`, `provider`, `idx_llm_usage_user_created`), and pydantic-ai 1.107 in `backend/venv`: `pydantic_ai/models/google.py::_metadata_as_usage` (`details["cached_content_tokens"]`, `details["thoughts_tokens"]`) and `pydantic_ai/usage.py::RunUsage` (`cache_read_tokens`, `details`).

## State of the world

Verify the base before Task 1. Every row must match. The PKG-00, PKG-03, PKG-05, PKG-05b and PKG-06 rows are those packages' hand-off Verify blocks, verbatim.

| check | command | expected |
|---|---|---|
| ledger | `grep -E "^\| 0[0-6]b? " docs/superpowers/plans/learning-loop/LEDGER.md` | 00–06, 05b: the LATEST row of each listed package is `done`, `verified` or `reopened` (README "Ledger reading"; earlier rows are history); no package's latest row is `planned`, `blocked` or `in-progress` |
| hermetic suite green | `cd backend && venv/bin/python -m pytest tests/ -q -x` | `… passed`, zero failures (note the count N₀) |
| lint green | `cd backend && venv/bin/ruff check .` | `All checks passed!` |
| PKG-00 | `cd backend && venv/bin/python -m pytest tests/test_learning_gate.py -q` | 13 passed |
| PKG-00 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q` | 4 passed, 8 skipped (later packages raise the passed count) — expect it higher now; zero failures |
| PKG-00 | `cd backend && venv/bin/python -m pytest tests/test_learning_deps.py tests/test_learning_settings_flag.py tests/test_learning_loop_beta_migration.py -q` | all passed |
| PKG-00 | `grep -n "^LEARNING_LOOP_ENABLED" backend/config.py` | 1 hit |
| PKG-00 | `ls backend/db/migrations/*_learning_loop_beta.sql` | 1 file |
| PKG-03 | `cd backend && venv/bin/python -m pytest tests/test_learning_evidence_apply.py tests/test_graph_service.py -q` | all passed |
| PKG-03 | `ls backend/db/migrations/*_learning_learner_state.sql` | 1 file |
| PKG-03 | `grep -c '"evidence"' backend/services/graph_service.py` | ≥ 1 |
| PKG-03 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k inv_01` | 1 passed |
| PKG-05 | `cd backend && venv/bin/python -m pytest tests/test_learning_check_tool.py -q` | N passed (N ≥ 16) |
| PKG-05 | `grep -c '"grader"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py` | ≥ 1 each |
| PKG-05 | `grep -c '"grader_second"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py` | ≥ 1 each |
| PKG-05 | `grep -c "^async def grade_answer" backend/agents/tools/check.py` | 1 |
| PKG-05 | `ls backend/db/migrations/*_learning_grader_backend.sql` | 1 file |
| PKG-05 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_14 or inv_28"` | 2 passed |
| PKG-05 | `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/grader.py` | every evaluator ≥ baseline |
| PKG-05b | `cd backend && venv/bin/python -m pytest tests/test_learning_decisions.py -q` | N passed (N ≥ 12) |
| PKG-05b | `grep -c '"decision"' backend/agents/_providers.py backend/agents/function_handlers_e2e.py` | ≥ 1 each |
| PKG-05b | `grep -c '"decision\.' backend/services/events_service.py` | 3 |
| PKG-05b | `grep -rlE "^[[:space:]]*(import\|from)[[:space:]]+typesafe" backend --include=*.py --exclude-dir=venv --exclude-dir=tests \| wc -l` | 0 |
| PKG-05b | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_24 or inv_25"` | 2 passed |
| PKG-05b | `cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/decisions.py` | every evaluator ≥ baseline |
| PKG-05b | `ls docs/decisions/*decision-seam*.md` | 1 file |
| PKG-06 | `cd backend && venv/bin/python -m pytest tests/test_learning_zpd_policy.py -q` | N passed (N ≥ 35) |
| PKG-06 | `grep -cE "^def (ceiling\|band_control\|evidence_for_rung\|wheelspin\|model_tier\|context_policy)\(" backend/learning/policy.py` | 6 |
| PKG-06 | `grep -cE "^def (check_pose\|deterministic_content)\(" backend/learning/ladder.py` | 2 |
| PKG-06 | `grep -c '"zpd\.' backend/services/events_service.py` | 6 |
| PKG-06 | `ls backend/db/migrations/*_learning_session_loop_state.sql` | 1 file |
| PKG-06 | `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_02 or inv_04 or inv_05"` | 3 passed |
| `llm_usage` base (0035) | `grep -cE "provider +TEXT NOT NULL DEFAULT 'gemini'\|idx_llm_usage_user_created +ON llm_usage \(user_id, created_at DESC\)" backend/db/migrations/0035_observability.sql` | 2 |
| token columns absent | `grep -rlE "cached_tokens\|thinking_tokens" backend/db/migrations \| wc -l` | 0 |
| policy aliases (PKG-06) | `grep -cE "^(Band\|Tier\|BudgetLevel) = " backend/learning/policy.py` | 3 |
| module absent, no `ai.` event yet | `ls backend/services/ai_budget.py 2>/dev/null \| wc -l; grep -c '"ai\.' backend/services/events_service.py` | 0 then 0 |
| latest migration prefix | `ls backend/db/migrations \| tail -1` | a `2026…` timestamped file; your migration's prefix must sort after it |

Rule: any red row → STOP. Diagnose, repair on this branch as commit `fix(learning-loop): PKG-NN — <what>` (NN = the package whose row is red), record the deviation in `LEDGER.md` (row `NN | reopened`), append "Post-hoc changes" to that `HANDOFF-NN.md`, re-run all rows. Never build on a broken base. After the rows pass, append `verified` rows for 05, 05b and 06 (and 03 if its latest row is not `verified`) with today's date and the command → output.

## Spec

### Behaviour

1. **Where it lives.** `backend/services/ai_budget.py`, outside `backend/learning/` (spec §2, §12). It reads `llm_usage` and decides; it imports nothing from `agents`, `pydantic_ai` or `google` and never calls a model. Public: `Kind`, `Scope`, `EventLevel`, `BudgetDecision`, `AIBudgetExceeded`, `check`, `rate_limited`, `enforce_rate_limit_for`, `enforce_rate_limit`, `budget_exceeded_handler`, `reset_for_tests`, and the module constants in §Named constants.
2. **One usage read per request.** `_usage(user_id)` reads every `llm_usage` row of the user since the UTC month start through `page_all(table("llm_usage"), "id,cost_usd,total_tokens,task,created_at", filters={"user_id": "eq.<uid>", "created_at": "gte.<month start>"}, order="created_at.asc,id.asc")` (one logical read on `idx_llm_usage_user_created`; paged because PostgREST truncates past `MAX_ROWS`) and summarises it: `month_usd`, `day_usd` and `day_tokens` (rows since UTC midnight; `sum(cost_usd)` with NULL as 0, `sum(total_tokens)`), `day_grades` (today's rows with `task ∈ GRADE_TASKS`), `minute_rows` / `minute_oldest` (rows in the last `RATE_LIMIT_WINDOW_S`). Every row with that `user_id` counts, legacy included (spec §3.5). The summary is cached per `(current_request_id(), user_id)` in a bounded dict (no `lru_cache`); outside a request (no request id) nothing is cached. A read error → `logger.warning("ai_budget: llm_usage read failed for %s: %s", …)` and `None`: the $, token, grade and rate scopes fail OPEN (see Error semantics); the session counters, which need no read, still apply.
3. **`check(user_id, kind, band=None, *, session_tutor_requests=0, session_deep_requests=0, arm_session=False) -> BudgetDecision`** — sync (routes and `grade()` call it inline, like `learning_loop_active`). `BudgetDecision` is a frozen dataclass `(level: BudgetLevel, tier_ceiling: Tier, scope: Scope | None = None, reset_at: datetime | None = None, pause_novice: bool = False)`. `kind ∉ Kind` or `kind == "tutor"` with `band is None` → `ValueError` (programming error). Falsy `user_id` → normal (system actors carry no student budget). The band's daily cap is `STUDENT_DAILY_BUDGET_USD × (BUDGET_NOVICE_MULTIPLIER if band == "novice" else 1.0)`.
   - **`tutor`** — hard when ANY of: `day_usd ≥` band cap (`daily_usd`), `month_usd ≥ STUDENT_MONTHLY_BUDGET_USD` (`monthly_usd`), `day_tokens ≥ STUDENT_DAILY_TOKENS` (`daily_tokens`), `session_tutor_requests ≥ LOOP_SESSION_MAX_TUTOR_REQUESTS` (`session_requests`), `minute_rows ≥ LEARN_RATE_LIMIT_PER_MIN` (`rate_limit`). Hard → `tier_ceiling="none"`, `pause_novice=True` — EXCEPT when `rate_limit` is the only hard trigger: then `pause_novice=False` (a 60-second burst pauses tutor turns, but never drops novice-band concepts from review or the check surfaces; spec §3.5 keeps review and flashcards working). Otherwise soft when ANY of: `day_usd ≥ STUDENT_SOFT_FRACTION ×` band cap (`daily_usd`), `day_tokens ≥ STUDENT_SOFT_FRACTION × STUDENT_DAILY_TOKENS` (`daily_tokens`), `session_deep_requests ≥` the band's deep cap — `LOOP_SESSION_MAX_DEEP_REQUESTS_NOVICE` for novice, else `LOOP_SESSION_MAX_DEEP_REQUESTS` (`session_deep`). Soft → `tier_ceiling="standard"` for develop/profic; for novice `"deep"` unless `session_deep` is among the triggers (the $- and token-based soft level never downgrades novice deep turns; only the novice deep-request cap does — spec §3.5 soft row). `arm_session=True` → every soft trigger still emits its event but the decision is `normal`/`"deep"` (arms are exempt from downgrades and pause at hard instead; †, see Open questions). Nothing → `normal`/`"deep"`.
   - **`grader`, `decision`** — only the grader cap: `day_grades ≥ STUDENT_DAILY_GRADES` → `hard`, `scope="daily_grades"`, `tier_ceiling="none"`, `pause_novice=False`; event level `grader_cap`. `band` is ignored. A tutor-hard student still grades below the grade cap (spec §3.5: "grading has its own cap").
   - **`close`** — hard on the spend scopes only (`daily_usd` at the band cap — `band="novice"` applies the novice allowance, `None`/`develop`/`profic` the develop/profic one; PKG-09 passes `"novice"` when the session checked a concept that started in the novice band — `monthly_usd`, `daily_tokens`); never soft (one call; nothing to downgrade); no rate limit (that is the routes'). PKG-09 turns hard into `fallback_close` (A25).
4. **Scope and reset.** Among the triggered hard scopes the decision reports the one whose `reset_at` is LATEST (ties: `daily_usd, monthly_usd, daily_tokens, session_requests, rate_limit` order), so a pause banner never promises an early resume; `session_requests` (reset `None`: a new session resets it) is reported only when no timed scope triggered. Resets: daily scopes → next UTC midnight; `monthly_usd` → first instant of next UTC month; `rate_limit` → `minute_oldest + RATE_LIMIT_WINDOW_S`; `session_deep` → `None`. Soft reports its first trigger in the order above.
5. **`ai.budget_capped`** (spec §6; category `usage`): emitted by `check`, `enforce_rate_limit` and the platform alert, at most once per process per `(user, scope, level, UTC day)` (`level ∈ {soft, hard, grader_cap}`; the platform alert keys on user `"platform"`). Payload `{user_id, scope, band, level, spent_usd, cap_usd}` with `None` values omitted, never zeroed: `spent_usd` = month $ for `monthly_usd`, else today's $; `cap_usd` only for the $ scopes (band cap, monthly cap, platform budget).
6. **Platform alert (alert-only).** When `PLATFORM_DAILY_BUDGET_USD` is set, `check` starts at most one platform read per `PLATFORM_CHECK_INTERVAL_S` per process, on a daemon thread (`_spawn`), never on the request path: today's `sum(cost_usd)` over all users; `≥ PLATFORM_ALERT_FRACTION × PLATFORM_DAILY_BUDGET_USD` → one `logger.warning` + `ai.budget_capped{scope: platform, level: soft}` (user_id omitted). It never changes a decision. Unset (the default) → no read at all.
7. **Rate limit.** `rate_limited(user_id) -> bool` = `minute_rows ≥ LEARN_RATE_LIMIT_PER_MIN` (cross-worker because it counts `llm_usage` rows; Redis is off by default; `services/request_limits.py` is per-process and is not used). `enforce_rate_limit_for(user_id)` is the inline form (for routes where only some bodies run a model, e.g. PKG-12's `/review/answer` with `kind="check"`); `enforce_rate_limit(request)` is a sync FastAPI dependency that calls it: `user_id = get_session_user_id(request)` (401 as today without a session), then on a hit emits the event and raises `AIBudgetExceeded(BudgetDecision(level="hard", tier_ceiling="none", scope="rate_limit", reset_at=…))`. `main.py` registers `budget_exceeded_handler` for `AIBudgetExceeded`: HTTP 429, body `{"detail": "ai budget reached", "reset_at": <iso or null>, "scope": <scope>, "request_id": <id>}` (the spec's two keys plus the house `request_id` and the scope), headers `Retry-After` (seconds to `reset_at`, ≥ 1, when known) and `X-Request-ID`. PKG-07 attaches the dependency to every model-calling `/api/learn/loop/*` route and raises the same exception for a tutor-hard decision; this package attaches it nowhere.
8. **Usage observability (A21).** Migration `<ts>_learning_llm_usage_tokens.sql` (spec §4 DDL). `agents/usage.py::_cache_and_thinking(usage)` reads pydantic-ai 1.107's Google usage: `cached = max(usage.cache_read_tokens, details["cached_content_tokens"])`, `thinking = details["thoughts_tokens"]`; Gemini omits zero counts, so a `RunUsage` without the key yields `0`; a usage shape with no such fields at all yields `None` (NULL). `record_agent_usage` passes both to `events_service.log_llm_usage(…, cached_tokens=, thinking_tokens=)`, which writes both keys on EVERY `llm_usage` row (`None` when unmeasured — uniform keys keep PostgREST bulk inserts valid) and passes `cached_tokens` to `llm_pricing.cost_usd`. Cost = uncached input × input rate + cached × `CACHED_INPUT_PRICING[model]` + output (already including thinking) × output rate; a model with no cached rate bills cached input at its full input rate (the no-cache upper bound, never lower); `cached_tokens` is clamped to `[0, prompt_tokens]`.
9. **Reopen PKG-05** (`agents/grader.py`): `grade`'s first statement is `if ai_budget.check(deps.user_id, "grader").level == "hard": return GradeResult(unavailable=True)` — before the message is built and before ANY run, so the attempt is `unavailable` whatever its outcome and `grade_answer` writes zero evidence for either outcome (A22, invariant 28). `_run_once` (the run site of both runs) also starts with `ai_budget.check(deps.user_id, "grader")` and on hard raises `UsageLimitExceeded("ai budget: grader cap reached")`, which `grade`'s existing honest-degrade branch turns into `unavailable` — so the second opinion is guarded too and invariant 23 sees every run site.
10. **Reopen PKG-05b** (`services/decisions.py::_run_decision`): first statement `if ai_budget.check(deps.user_id, "decision").level == "hard": return None` — no model call; the caller's existing unavailable path runs unchanged (PKG-05b emits `decision.fallback{reason: both_failed}` there; spec §6's reason enum has no budget value and this package adds none — Open question (f)). `grade_rubric_items`/`reason_is_correct` need no change: their Gemini backend is `grader.grade()`, capped by item 9.
11. **Dark during the build.** `ai_budget` is reached only from `grade()` and the decision run site, which only loop paths call (`grade_answer` is inert when `deps.learning_loop` is False; loop routes 404 while the gate is false). The legacy `/api/learn/*` handlers, `services/chat_stream.py` and `routes/learn.py` are untouched (PKG-14b adds the kill-switch-path check). A21 is deliberately not flag-gated: it is observability on every `llm_usage` row, invisible to students; `cost_usd` changes only where a cache hit is reported (lower — the real bill).

### Schema (exact)

```sql
-- <ts>_learning_llm_usage_tokens.sql
-- Learning loop series PKG-06b (spec §4, §13 A21): usage observability.
-- cached_tokens   = Gemini usage_metadata.cached_content_token_count (implicit-cache hits)
-- thinking_tokens = Gemini usage_metadata.thoughts_token_count (already inside completion_tokens)
-- Filled by agents/usage.py::record_agent_usage; NULL on rows written before this migration
-- and on usage shapes that carry no such field. Counts only; never content.
-- llm_usage already has user_id, provider and idx_llm_usage_user_created (0035).
ALTER TABLE llm_usage
  ADD COLUMN IF NOT EXISTS cached_tokens int,
  ADD COLUMN IF NOT EXISTS thinking_tokens int;
```

### Named constants

Every number this package uses, once. Tasks cite the NAME. `†` = engineering choice with no validated cut-point (spec §3.5 marks them; keep `†` in the hand-off).

| Name | Value | Where it lives | Spec ref |
|---|---|---|---|
| `STUDENT_DAILY_BUDGET_USD` | 0.20 † | `config.py` (env-overridable) | §3.5 |
| `BUDGET_NOVICE_MULTIPLIER` | 2.5 † | `config.py` | §3.5 |
| `STUDENT_SOFT_FRACTION` | 0.8 † | `config.py` | §3.5 |
| `STUDENT_MONTHLY_BUDGET_USD` | 2.00 † | `config.py` | §3.5 |
| `STUDENT_DAILY_TOKENS` | 400_000 † | `config.py` | §3.5 |
| `STUDENT_DAILY_GRADES` | 300 † | `config.py` | §3.5 |
| `LEARN_RATE_LIMIT_PER_MIN` | 20 † | `config.py` | §3.5 |
| `PLATFORM_DAILY_BUDGET_USD` | unset → `None` (owner sets it) | `config.py` | §3.5 |
| `PLATFORM_ALERT_FRACTION` | 0.8 † | `config.py` | §3.5 |
| `PLATFORM_CHECK_INTERVAL_S` | 300 † | `config.py` | §3.5 |
| `LOOP_SESSION_MAX_TUTOR_REQUESTS` | 40 † | `learning/params.py` (appended on PKG-01's behalf) | §3.5 |
| `LOOP_SESSION_MAX_DEEP_REQUESTS` | 6 † | `learning/params.py` | §3.5 |
| `LOOP_SESSION_MAX_DEEP_REQUESTS_NOVICE` | 12 † | `learning/params.py` | §3.5 |
| `CACHED_INPUT_PRICING` | per 1K: `gemini-2.5-flash-lite` 0.00001, `gemini-2.5-flash` 0.00003, `gemini-2.5-pro` 0.000125 (10% of input) | `services/llm_pricing.py` | A21 |
| `GRADE_TASKS` / `RATE_LIMIT_WINDOW_S` | `{"grader", "grader_second", "decision"}` / 60 | `services/ai_budget.py` | §3.5 `STUDENT_DAILY_GRADES` / "last 60 s" |
| `BUDGET_REACHED_DETAIL` / `BUDGET_CAPPED_EVENT` | `"ai budget reached"` / `"ai.budget_capped"` | `services/ai_budget.py` | §3.5, A20 / §6 |
| `_REQUEST_CACHE_MAX` | 512 (entries; a memory bound, not a policy) | `services/ai_budget.py` | new name |

`STUDENT_*`, `BUDGET_*`, `LEARN_*` and `PLATFORM_*` live in `config.py`, not `params.py` (spec §3.5 places them there: they are deploy-time knobs, e.g. a paid tier may raise `STUDENT_DAILY_BUDGET_USD`). `ai_budget` reads `config.<NAME>` at call time, never a copy taken at import, so tests and a redeploy both see the current value. Every test below derives its inputs from these names, never from a numeral.

### Invariants asserted by this package (spec §8 numbering)

- (23, new) `test_inv_23_ai_budget_checked_before_every_run`: every function under `backend/` (excluding `venv/`, `tests/`) that calls `.run(`/`.run_stream(`/`.iter(`/`.run_sync(` on a module-level `Agent(` defined in `agents/{grader,decision,loop_tutor,session_close}.py`, or passes such an agent to `stream_agent_turn(`, calls `ai_budget.check(` on an earlier line of the same function body (AST scan; nested functions are their own scope). The scan self-tests on three synthetic sources and refuses to pass vacuously (≥ 2 run sites found). PKG-07 and PKG-09 inherit it: their agents are picked up the moment the stub modules define them.
- (28, extended) `test_inv_28_symmetric_missingness` gains its cap half: with `STUDENT_DAILY_GRADES` grade rows today, `grade_answer` on a correct AND on a wrong `mc_reason` attempt returns `unavailable` and appends zero evidence in both cases, and the grader agent never runs. Same function, no parametrization (the canonical verify line counts `inv_23 or inv_28` as exactly 2 tests).
- (5, covered) `"ai.budget_capped"` is the only `"ai.` literal under `backend/` and it is in `EVENT_TAXONOMY` (PKG-06's `test_inv_05` scans the `ai.` prefix).
- (10, n/a) no `lru_cache` anywhere in this package.

### Error semantics

- `llm_usage` read failure → WARNING, fail OPEN for the $, token, grade and rate scopes; session caps still apply. † (spec is silent): a failed read means PostgREST is failing, which already fails the route's own reads; a fail-closed guard would turn a partial PostgREST blip into a platform-wide tutor pause. The bound that remains: `LOOP_LIMITS`/per-run `max_tokens` (PKG-07), the session counters, Gemini's project spend limit.
- Grader capped → `GradeResult(unavailable=True)`; no model call, no evidence for either outcome, no second prompt stack, no fallback verdict (ADR 0024 honest degrade); the event is the record, no extra log line.
- Decision capped → `_run_decision` returns `None`; the caller's unavailable path (and its `decision.fallback`) runs as for an outage.
- Rate limited → `AIBudgetExceeded` → 429 before the route body runs.
- Platform read failure → WARNING, no event; never blocks a request.
- Malformed budget env value → `ValueError` at import: boot fails loudly (as `PORT` does). `record_agent_usage` and `log_llm_usage` still never raise or block.

### Events added

`ai.budget_capped` — category `usage`; payload `user_id, scope (daily_usd/monthly_usd/daily_tokens/session_requests/session_deep/daily_grades/rate_limit/platform), band, level (soft/hard/grader_cap), spent_usd, cap_usd` (spec §6), ids/enums/numbers only. Added to `EVENT_TAXONOMY` and the pin test in the same commit (Task 4).

## Non-goals

- No agent task, no function-mode handler, no eval dataset, no prompt or tool-description change (no LLM call exists here; the PKG-05/05b evals are re-run only to prove they did not move).
- No route mount, no route change, no dependency attached anywhere; no loop-tutor wiring (PKG-07: session counters in `loop_state`, tier ceilings, the stream `budget` event, `enforce_rate_limit` on routes); no close wiring (PKG-09); no review pause (PKG-12); no frontend (PKG-13); no change to the legacy `/api/learn/*` handlers (PKG-14b).
- No Redis, no SQL aggregate function or RPC (spec §4's PKG-06b DDL is the two columns), no admin route, no `.env.example` or deployed-config change.
- No `lru_cache`; no verdict cache (spec §3.5: none is built).

## Tasks

Code blocks use one blank line between definitions to save space; `ruff format` restores the house spacing — run it on the series files each step names (never on whole pre-series files).

### Task 1: Invariants — add inv_23, extend inv_28

**Files:**
- Modify: `backend/tests/test_learning_loop_invariants.py`

**Interfaces:**
- Consumes: the source tree under `backend/`; `agents.grader`, `agents.tools.check.grade_answer`, `services.ai_budget` (the cap half, from Task 7 on).
- Produces: `test_inv_23_ai_budget_checked_before_every_run`; the cap half of `test_inv_28_symmetric_missingness`.

- [ ] **Step 1: Write the tests** (append inv_23; add `import ast` to the imports if absent — `os`, `pathlib` and `BACKEND` are already there)

```python
# ── invariant 23 (PKG-06b; spec §8.23, §13 A20) ──────────────────────────────
BUDGETED_AGENT_MODULES = ("grader", "decision", "loop_tutor", "session_close")
AGENT_RUN_METHODS = frozenset({"run", "run_stream", "iter", "run_sync"})
_SCAN_SKIP_DIRS = frozenset({"venv", ".venv", "tests", "__pycache__", "node_modules"})

def _is_agent_ctor(func: ast.expr) -> bool:
    func = func.value if isinstance(func, ast.Subscript) else func  # Agent[Deps, Out](...)
    return _last_name(func) == "Agent"

def _budgeted_agent_names() -> set[str]:
    """Module-level ``NAME = Agent(...)`` in the modules whose slots spec §8.23
    budgets. A stub module adds nothing and starts counting once it defines its agent."""
    names: set[str] = set()
    for mod in BUDGETED_AGENT_MODULES:
        path = BACKEND / "agents" / f"{mod}.py"
        if not path.exists():
            continue
        for node in ast.parse(path.read_text()).body:
            value = getattr(node, "value", None)
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(value, ast.Call) and _is_agent_ctor(value.func):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                names |= {t.id for t in targets if isinstance(t, ast.Name)}
    return names

def _last_name(expr: ast.expr) -> str | None:
    return expr.id if isinstance(expr, ast.Name) else expr.attr if isinstance(expr, ast.Attribute) else None

def _own_nodes(fn: ast.AST):
    """The function's own body; nested defs, lambdas and classes are their own scope."""
    stack = list(getattr(fn, "body", []))
    while stack:
        node = stack.pop()
        yield node
        stack.extend(c for c in ast.iter_child_nodes(node)
                     if not isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)))

def _budget_scan(source: str, agents: set[str], label: str) -> tuple[int, list[str]]:
    """(run sites found, run sites with no earlier ``ai_budget.check(`` in the same function)."""
    found, bad = 0, []
    for fn in ast.walk(ast.parse(source)):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        runs, checks = [], []
        for node in _own_nodes(fn):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr in AGENT_RUN_METHODS and _last_name(f.value) in agents:
                runs.append(node.lineno)
            elif _last_name(f) == "stream_agent_turn" and any(
                    _last_name(a) in agents for a in [*node.args, *(k.value for k in node.keywords)]):
                runs.append(node.lineno)
            elif isinstance(f, ast.Attribute) and f.attr == "check" and _last_name(f.value) == "ai_budget":
                checks.append(node.lineno)
        found += len(runs)
        bad += [f"{label}:{fn.name}:{line}" for line in runs if not any(c < line for c in checks)]
    return found, bad

def _backend_sources():
    for root, dirs, files in os.walk(BACKEND):
        dirs[:] = [d for d in dirs if d not in _SCAN_SKIP_DIRS and not d.startswith(".")]
        for name in files:
            if name.endswith(".py"):
                yield pathlib.Path(root) / name

def test_inv_23_ai_budget_checked_before_every_run():
    agents = {"grader_agent"}
    good = "async def f(deps):\n    ai_budget.check(deps.user_id, 'grader')\n    return await grader_agent.run('m')\n"
    late = "async def f(deps):\n    r = await grader_agent.run('m')\n    ai_budget.check(deps.user_id, 'grader')\n    return r\n"
    nested = ("async def f(deps):\n    ai_budget.check(deps.user_id, 'grader')\n"
              "    async def g():\n        return await grader_agent.run('m')\n    return await g()\n")
    assert _budget_scan(good, agents, "good") == (1, [])
    assert _budget_scan(late, agents, "late")[1] == ["late:f:2"]
    assert _budget_scan(nested, agents, "nested")[1] == ["nested:g:4"]

    names = _budgeted_agent_names()
    assert names, "no module-level Agent( in agents/grader.py or agents/decision.py: the scan would be vacuous"
    found, bad = 0, []
    for path in _backend_sources():
        n, b = _budget_scan(path.read_text(), names, str(path.relative_to(BACKEND)))
        found, bad = found + n, bad + b
    assert found >= 2, f"expected at least the grader and decision run sites, found {found}"
    assert bad == [], f"agent run with no earlier ai_budget.check( in the same function: {bad}"
```

- [ ] **Step 2: Extend inv_28 in place.** Append this block to the END of the existing `test_inv_28_symmetric_missingness` body; the outage half stays first and unchanged, and its locals `item`, `check`, `SaplingDeps`, `asyncio` are reused (if `grade_answer` reads an item attribute not listed below, add it from HANDOFF-04's `CheckItem`):

```python
    # ── cap half (PKG-06b; spec §3.5 grader cap, §8.28) ──
    import config
    from pydantic_ai.models.function import FunctionModel
    from agents import grader
    from services import ai_budget
    # Put the real grade() back on the SAME target the outage half stubbed (never monkeypatch.undo():
    # it would also drop conftest's hermetic Supabase/LLM guards, which share this monkeypatch).
    monkeypatch.setattr(check, "grade", grader.grade)
    stamp = ai_budget._utcnow().isoformat()
    capped = [{"id": f"g{i}", "cost_usd": 0, "total_tokens": 0, "task": "grader", "created_at": stamp}
              for i in range(config.STUDENT_DAILY_GRADES)]
    monkeypatch.setattr(ai_budget, "_load_rows", lambda user_id, since: capped)
    runs: list[int] = []

    def _grader_must_not_run(messages, info):
        runs.append(1)
        raise AssertionError("the grader ran under the grader cap")

    full = SimpleNamespace(**vars(item), prompt="Q?", reference_answer="right", rubric=[{"id": "r1", "text": "t"}],
                           common_wrong=[{"key": "w_1", "text": "wrong"}], stepwise=False, canonical_answer=None,
                           tolerance=None, source_chunk_ids=[])
    with grader.grader_agent.override(model=FunctionModel(_grader_must_not_run)):
        for option in ("A", "B"):  # the same correct and wrong attempts as the outage half
            deps = SaplingDeps(user_id="u1", course_id="c1", supabase=None, request_id="r1",
                               session_id="s1", feature="tutor", learning_loop=True)
            answer = check.CheckAnswer(question_hash="qh-28", selected_option=option, reason="because")
            out = asyncio.run(check.grade_answer(full, answer, deps=deps, node_id="n-28"))
            assert out.unavailable is True and out.evidence is None, option
            assert deps.pending_evidence == [], f"evidence written for option {option} under the grader cap"
    assert runs == []
```

- [ ] **Step 3: Run to see the current state**

Run: `cd backend && venv/bin/ruff format tests/test_learning_loop_invariants.py && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_23 or inv_28"`
Expected: `test_inv_23` FAILS listing `agents/grader.py:_run_once:<line>` (twice) and `services/decisions.py:_run_decision:<line>` (the self-tests pass); `test_inv_28` FAILS at the cap half — `ImportError: cannot import name 'ai_budget' from 'services'`. Both turn green in Task 7; until then these two are the only permitted failures in the self-check loop.

- [ ] **Step 4: Commit** (red is expected)

```
git add backend/tests/test_learning_loop_invariants.py
git commit -m "test(learning-loop): PKG-06b — invariant 23 and the grader-cap half of invariant 28

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 2: Migration, usage capture, cached-input pricing (A21)

**Files:**
- Create: `backend/db/migrations/<UTC>_learning_llm_usage_tokens.sql`, `backend/tests/test_learning_ai_budget.py`
- Modify: `backend/services/llm_pricing.py`, `backend/services/events_service.py` (`log_llm_usage` only), `backend/agents/usage.py`

**Interfaces:**
- Consumes: pydantic-ai 1.107 `RunUsage` (`cache_read_tokens`, `details`).
- Produces: columns `llm_usage.cached_tokens`/`thinking_tokens`; `llm_pricing.CACHED_INPUT_PRICING`; `llm_pricing.cost_usd(model, prompt_tokens, completion_tokens, cached_tokens=None)`; `events_service.log_llm_usage(..., cached_tokens=None, thinking_tokens=None)`; `agents.usage._cache_and_thinking(usage) -> tuple[int | None, int | None]`.

- [ ] **Step 1: Write the failing tests** — create `backend/tests/test_learning_ai_budget.py` (later tasks append; each task adds the imports its tests need so `ruff` stays clean after every task)

```python
"""PKG-06b — AI budget and usage (spec §3.5, §6, §13 A20/A21). llm_usage rows
come from a fake table and the clock is fixed: no DB, no LLM, no network."""
from __future__ import annotations

import pathlib
import re
from types import SimpleNamespace

import pytest

from services import events_service, llm_pricing

BACKEND = pathlib.Path(__file__).resolve().parents[1]
MIG_DIR = BACKEND / "db" / "migrations"
UID = "user_andres"

def _usage_sink(monkeypatch) -> list:
    rows: list = []
    monkeypatch.setattr(events_service, "table", lambda name: SimpleNamespace(insert=lambda r: rows.append((name, r)) or r))
    return rows

# ── A21: migration, pricing, usage capture ───────────────────────────────────

def test_llm_usage_tokens_migration_is_the_spec_ddl():
    hits = sorted(MIG_DIR.glob("*_learning_llm_usage_tokens.sql"))
    assert len(hits) == 1, f"expected exactly one llm_usage_tokens migration, got {hits}"
    assert re.fullmatch(r"\d{14}_learning_llm_usage_tokens\.sql", hits[0].name), hits[0].name
    sql = hits[0].read_text()
    assert "ALTER TABLE llm_usage" in sql
    for column in ("cached_tokens", "thinking_tokens"):
        assert re.search(rf"ADD COLUMN IF NOT EXISTS {column} int\b", sql), column
    assert "NOT NULL" not in sql, "historical rows and unrecognised usage shapes stay NULL"

def test_cost_bills_cached_input_at_the_cached_rate():
    # flash per 1K: input 0.0003, cached 0.00003, output 0.0025 → (600×0.0003 + 400×0.00003 + 1000×0.0025)/1000
    assert llm_pricing.cost_usd("gemini-2.5-flash", 1000, 1000, cached_tokens=400) == pytest.approx(0.002692)
    # pro: (2000×0.00125 + 8000×0.000125 + 2000×0.010)/1000
    assert llm_pricing.cost_usd("gemini-2.5-pro", 10_000, 2_000, cached_tokens=8_000) == pytest.approx(0.0235)
    assert llm_pricing.cost_usd("gemini-2.5-flash", 1000, 1000) == pytest.approx(0.0028)  # no cache: unchanged

def test_cached_rates_are_ten_percent_of_input_and_clamped():
    cost = llm_pricing.cost_usd
    for model in ("gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-2.5-pro"):
        assert llm_pricing.CACHED_INPUT_PRICING[model] == pytest.approx(llm_pricing.MODEL_PRICING[model][0] * 0.1)
        assert cost(model, 1234, 567) == cost(model, 1234, 567, cached_tokens=0)
    assert cost("gemini-2.5-flash", 100, 0, cached_tokens=500) == cost("gemini-2.5-flash", 100, 0, cached_tokens=100)
    # a model with no cached rate bills cached input at its full input rate (the no-cache upper bound)
    assert cost("gemini-2.0-flash", 1000, 10, cached_tokens=400) == cost("gemini-2.0-flash", 1000, 10)

def test_record_agent_usage_captures_cached_and_thinking_tokens(monkeypatch):
    from pydantic_ai.usage import RunUsage
    from agents.usage import record_agent_usage
    rows = _usage_sink(monkeypatch)
    run_usage = RunUsage(input_tokens=1000, output_tokens=600, cache_read_tokens=400,
                         details={"cached_content_tokens": 400, "thoughts_tokens": 500})
    result = SimpleNamespace(usage=lambda: run_usage, all_messages=lambda: [],
                             response=SimpleNamespace(model_name="gemini-2.5-flash"))
    assert record_agent_usage(result, feature="learn_loop", task="grader", user_id=UID) is result
    events_service.flush_now()
    row = rows[0][1][0]
    assert (row["cached_tokens"], row["thinking_tokens"]) == (400, 500)
    assert row["cost_usd"] == pytest.approx(llm_pricing.cost_usd("gemini-2.5-flash", 1000, 600, cached_tokens=400))

def test_every_llm_usage_row_carries_both_token_keys(monkeypatch):
    from pydantic_ai.usage import RunUsage
    from agents.usage import _cache_and_thinking
    rows = _usage_sink(monkeypatch)
    events_service.log_llm_usage(
        feature="quiz", task="quiz", model="gemini-2.5-flash", usage={"prompt_tokens": 10, "completion_tokens": 5}
    )
    events_service.flush_now()
    row = rows[0][1][0]
    assert row["cached_tokens"] is None and row["thinking_tokens"] is None  # uniform keys for bulk inserts
    assert _cache_and_thinking(RunUsage(input_tokens=5, output_tokens=5)) == (0, 0)  # Gemini omits zero counts
    assert _cache_and_thinking(SimpleNamespace(input_tokens=5)) == (None, None)  # no such fields at all
```

- [ ] **Step 2: Run to verify they fail.** `cd backend && venv/bin/python -m pytest tests/test_learning_ai_budget.py -v` → FAIL — `expected exactly one llm_usage_tokens migration, got []`; `TypeError: cost_usd() got an unexpected keyword argument 'cached_tokens'`; `AttributeError: … CACHED_INPUT_PRICING`; `KeyError: 'cached_tokens'`; `ImportError: cannot import name '_cache_and_thinking'`.

- [ ] **Step 3: Implement**

Migration: prefix from `date -u +%Y%m%d%H%M%S`; content = §Schema verbatim, comments included.

`backend/services/llm_pricing.py` — below `MODEL_PRICING`:
```python
# Cached-input rates per 1K tokens (spec §13 A21): 10% of the input rate —
# Flash-Lite $0.01/M, Flash $0.03/M, Pro $0.125/M. A model missing here bills
# cached input at its full input rate (the no-cache upper bound), never lower.
CACHED_INPUT_PRICING: dict[str, float] = {
    "gemini-2.5-pro": 0.000125,
    "gemini-2.5-flash": 0.00003,
    "gemini-2.5-flash-lite": 0.00001,
}
```
and `cost_usd` gains `cached_tokens: int | None = None` (docstring: "cached input, already inside `prompt_tokens`, billed at `CACHED_INPUT_PRICING`; spec §13 A21"); replace the body from `in_rate, out_rate = rates` down with:
```python
    in_rate, out_rate = rates
    canonical = model if model in MODEL_PRICING else _canonical_model(model)
    cached = min(max(int(cached_tokens or 0), 0), int(prompt_tokens))
    cached_rate = CACHED_INPUT_PRICING.get(canonical, in_rate)
    cost = (
        Decimal(str(in_rate)) * Decimal(int(prompt_tokens) - cached)
        + Decimal(str(cached_rate)) * Decimal(cached)
        + Decimal(str(out_rate)) * Decimal(int(completion_tokens))
    ) / Decimal(1000)
    return float(cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))
```

`backend/services/events_service.py::log_llm_usage` gains keyword-only `cached_tokens: int | None = None, thinking_tokens: int | None = None`; the row gains `"cached_tokens": cached_tokens, "thinking_tokens": thinking_tokens` (always both keys — PostgREST rejects a bulk insert whose objects' keys differ, PGRST102), and the cost call becomes `llm_pricing.cost_usd(model, tokens["prompt_tokens"], tokens["completion_tokens"], cached_tokens=cached_tokens)`. Docstring: one sentence citing A21.

`backend/agents/usage.py` — add above `record_agent_usage`:
```python
def _cache_and_thinking(usage: Any) -> tuple[int | None, int | None]:
    """(cached_tokens, thinking_tokens) for the llm_usage row (spec §13 A21), as pydantic-ai
    1.107 carries Gemini's counts (models/google.py::_metadata_as_usage). Gemini omits zero
    counts, so a RunUsage without the key means 0; a shape with no such fields means None."""
    details = getattr(usage, "details", None)
    details = details if isinstance(details, dict) else None
    thinking = int(details.get("thoughts_tokens") or 0) if details is not None else None
    if details is None and not hasattr(usage, "cache_read_tokens"):
        return None, thinking
    cached = max(
        int(getattr(usage, "cache_read_tokens", 0) or 0),
        int((details or {}).get("cached_content_tokens") or 0),
    )
    return cached, thinking
```
and in `record_agent_usage` replace the first `try` body with:
```python
        usage = result.usage()
        cached_tokens, thinking_tokens = _cache_and_thinking(usage)
        events_service.log_llm_usage(
            feature=feature, task=task, model=served_model_name(result, task), usage=usage,
            user_id=user_id, cached_tokens=cached_tokens, thinking_tokens=thinking_tokens,
        )
```

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/ruff format tests/test_learning_ai_budget.py && venv/bin/python -m pytest tests/test_learning_ai_budget.py tests/test_llm_pricing.py tests/test_events_service.py tests/test_agent_usage.py tests/test_usage_instrumentation_coverage.py tests/test_learning_loop_invariants.py::test_inv_08_series_migrations_named_and_never_modified -q && venv/bin/ruff check .`
Expected: all passed (the pre-series usage/pricing tests unchanged and green); `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/db/migrations/*_learning_llm_usage_tokens.sql backend/services/llm_pricing.py backend/services/events_service.py backend/agents/usage.py backend/tests/test_learning_ai_budget.py
git commit -m "feat(learning-loop): PKG-06b — llm_usage cached/thinking tokens and the cached-input rate

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 3: Named constants

**Files:**
- Modify: `backend/config.py`, `backend/learning/params.py`, `backend/tests/test_learning_ai_budget.py`

**Interfaces:**
- Produces: the ten `config` names and the three `params` names of §Named constants.

- [ ] **Step 1: Write the failing tests** (append; add `import config` and `from learning import params` to the imports)

```python
# ── constants (spec §3.5) ────────────────────────────────────────────────────

_CONFIG_DEFAULTS = {
    "STUDENT_DAILY_BUDGET_USD": "0.20", "BUDGET_NOVICE_MULTIPLIER": "2.5", "STUDENT_SOFT_FRACTION": "0.8",
    "STUDENT_MONTHLY_BUDGET_USD": "2.00", "STUDENT_DAILY_TOKENS": "400000", "STUDENT_DAILY_GRADES": "300",
    "LEARN_RATE_LIMIT_PER_MIN": "20", "PLATFORM_ALERT_FRACTION": "0.8", "PLATFORM_CHECK_INTERVAL_S": "300",
}

def test_budget_defaults_in_config_match_spec():
    # Parsed from source: a developer's .env may override the live values, never the defaults.
    src = (BACKEND / "config.py").read_text()
    for name, default in _CONFIG_DEFAULTS.items():
        assert re.search(rf'^{name}\b.*os\.getenv\("{name}", "{re.escape(default)}"\)', src, re.M), name
    assert re.search(r'os\.getenv\("PLATFORM_DAILY_BUDGET_USD", ""\)', src), "platform budget is owner-set"
    assert isinstance(config.STUDENT_DAILY_TOKENS, int) and isinstance(config.STUDENT_DAILY_GRADES, int)
    assert config.PLATFORM_DAILY_BUDGET_USD is None or isinstance(config.PLATFORM_DAILY_BUDGET_USD, float)

def test_session_caps_in_params_match_spec():
    assert (params.LOOP_SESSION_MAX_TUTOR_REQUESTS, params.LOOP_SESSION_MAX_DEEP_REQUESTS,
            params.LOOP_SESSION_MAX_DEEP_REQUESTS_NOVICE) == (40, 6, 12)
```

- [ ] **Step 2: Run to verify they fail.** `cd backend && venv/bin/python -m pytest tests/test_learning_ai_budget.py -v -k "defaults or session_caps"` → FAIL — `AssertionError: STUDENT_DAILY_BUDGET_USD`; `AttributeError: module 'learning.params' has no attribute 'LOOP_SESSION_MAX_TUTOR_REQUESTS'`.

- [ ] **Step 3: Implement**

`backend/config.py`, after the `LEARNING_LOOP_ENABLED` block:
```python
# AI budget (spec §3.5, §13 A20): owner-approved caps (†), env-overridable so a deploy or a
# paid tier can move them without a code change. services/ai_budget.py reads them at call time.
STUDENT_DAILY_BUDGET_USD = float(os.getenv("STUDENT_DAILY_BUDGET_USD", "0.20"))
BUDGET_NOVICE_MULTIPLIER = float(os.getenv("BUDGET_NOVICE_MULTIPLIER", "2.5"))
STUDENT_SOFT_FRACTION = float(os.getenv("STUDENT_SOFT_FRACTION", "0.8"))
STUDENT_MONTHLY_BUDGET_USD = float(os.getenv("STUDENT_MONTHLY_BUDGET_USD", "2.00"))
STUDENT_DAILY_TOKENS = int(os.getenv("STUDENT_DAILY_TOKENS", "400000"))
STUDENT_DAILY_GRADES = int(os.getenv("STUDENT_DAILY_GRADES", "300"))
LEARN_RATE_LIMIT_PER_MIN = int(os.getenv("LEARN_RATE_LIMIT_PER_MIN", "20"))
# Platform spend alert: alert-only, never blocks a request. Unset = no alert (the owner sets it).
_platform_budget = os.getenv("PLATFORM_DAILY_BUDGET_USD", "").strip()
PLATFORM_DAILY_BUDGET_USD: float | None = float(_platform_budget) if _platform_budget else None
PLATFORM_ALERT_FRACTION = float(os.getenv("PLATFORM_ALERT_FRACTION", "0.8"))
PLATFORM_CHECK_INTERVAL_S = int(os.getenv("PLATFORM_CHECK_INTERVAL_S", "300"))
```

`backend/learning/params.py`, appended at the end:
```python
# PKG-06b (spec §3.5, §13 A20): per-session loop request caps. The counters live in
# sessions.loop_state as ints tutor_requests / deep_requests (PKG-07 maintains them).
LOOP_SESSION_MAX_TUTOR_REQUESTS = 40  # † reaching it = hard (an optimized 10-turn session uses ≈ 7)
LOOP_SESSION_MAX_DEEP_REQUESTS = 6  # † develop/profic: reaching it = soft (deep → standard)
LOOP_SESSION_MAX_DEEP_REQUESTS_NOVICE = 12  # † novice: reaching it turns novice deep turns into standard
```

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_ai_budget.py tests/test_learning_bkt.py tests/test_learning_fsrs.py -q && venv/bin/ruff check .`
Expected: all passed (PKG-01/02 suites prove no `params.py` value moved); `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/config.py backend/learning/params.py backend/tests/test_learning_ai_budget.py
git commit -m "feat(learning-loop): PKG-06b — budget constants in config, session caps in params

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 4: `ai.budget_capped` — taxonomy, pin, emit helper, module skeleton

**Files:** (this task precedes `check` so the `"ai.budget_capped"` literal never exists outside the taxonomy — PKG-06's `test_inv_05` scans the `ai.` prefix)
- Create: `backend/services/ai_budget.py`
- Modify: `backend/services/events_service.py` (`EVENT_TAXONOMY` + docstring table), `backend/tests/test_event_capture_seams.py` (pin), `backend/tests/conftest.py` (autouse reset), `backend/tests/test_learning_ai_budget.py`

**Interfaces:**
- Consumes: `services.events_service.log_event`.
- Produces: taxonomy member `ai.budget_capped`; `ai_budget.Kind`, `Scope`, `EventLevel`, `BUDGET_CAPPED_EVENT`, `_utcnow()`, `_emit_capped(...)`, `reset_for_tests()`; conftest fixture `_reset_ai_budget`.

- [ ] **Step 1: Write the failing tests** (append; add `from datetime import datetime, timedelta, timezone` and `from services import ai_budget` to the imports, `NOW = datetime(2026, 9, 26, 15, 0, 0, tzinfo=timezone.utc)` beside `UID`)

```python
# ── ai.budget_capped (spec §6) ───────────────────────────────────────────────

@pytest.fixture
def events(monkeypatch):
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(ai_budget, "log_event", lambda event_type, **kw: calls.append((event_type, kw)))
    return calls

def test_budget_capped_is_in_the_taxonomy():
    assert "ai.budget_capped" in events_service.EVENT_TAXONOMY
    assert ai_budget.BUDGET_CAPPED_EVENT == "ai.budget_capped"

def test_emit_capped_once_per_user_scope_level_and_utc_day(events, monkeypatch):
    monkeypatch.setattr(ai_budget, "_utcnow", lambda: NOW)
    for _ in range(3):
        ai_budget._emit_capped(UID, "daily_usd", "hard", band="develop", spent_usd=0.25, cap_usd=0.2)
    ai_budget._emit_capped(UID, "daily_usd", "soft", band="develop", spent_usd=0.17, cap_usd=0.2)
    assert [kw["payload"]["level"] for _, kw in events] == ["hard", "soft"]
    event_type, kw = events[0]
    assert (event_type, kw["category"], kw["user_id"]) == ("ai.budget_capped", "usage", UID)
    assert kw["payload"] == {"user_id": UID, "scope": "daily_usd", "band": "develop", "level": "hard",
                             "spent_usd": 0.25, "cap_usd": 0.2}
    monkeypatch.setattr(ai_budget, "_utcnow", lambda: NOW + timedelta(days=1))
    ai_budget._emit_capped(UID, "daily_usd", "hard", band="develop")
    assert len(events) == 3, "a new UTC day re-arms the event"
    assert "spent_usd" not in events[2][1]["payload"], "None values are omitted, never zeroed"

def test_ai_budget_runs_no_model_and_lives_outside_learning():
    path = BACKEND / "services" / "ai_budget.py"
    roots = {m.group(1).split(".")[0] for m in re.finditer(r"^\s*(?:from|import)\s+([\w.]+)", path.read_text(), re.M)}
    assert not roots & {"agents", "pydantic_ai", "google"}, roots
    assert not (BACKEND / "learning" / "ai_budget.py").exists()
```

- [ ] **Step 2: Run to verify they fail.** `cd backend && venv/bin/python -m pytest tests/test_learning_ai_budget.py -v` → collection ERROR — `ImportError: cannot import name 'ai_budget' from 'services'`.

- [ ] **Step 3: Implement**

`backend/services/events_service.py`: add `"ai.budget_capped",` to `EVENT_TAXONOMY` with the comment `# PKG-06b (spec §6, §13 A20): a per-student AI cap was hit. category="usage": it fires at most once per user/scope/level/day, but for many students at once near a price change; the /errors feed must not drown in it.` and one row in the module docstring table (unquoted, the table's style): `ai.budget_capped              usage     user_id, scope, band, level, spent_usd, cap_usd`. The quoted literal appears exactly once in the file.

`backend/tests/test_event_capture_seams.py::test_event_taxonomy_is_pinned`: add `"ai.budget_capped",           # PKG-06b: a per-student AI cap was hit`.

`backend/tests/conftest.py`, after `_reset_events_service`:
```python
@pytest.fixture(autouse=True)
def _reset_ai_budget():
    """PKG-06b: reset ai_budget's per-process state (request cache, once-per-day event set,
    platform timestamp) so one test's caps never leak into another."""
    from services import ai_budget
    ai_budget.reset_for_tests()
    yield
    ai_budget.reset_for_tests()
```

`backend/services/ai_budget.py` (Task 5 and 6 append to it):
```python
"""Per-student AI cost guard: caps, degradation ladder, rate limit (spec §3.5, §13 A20). PKG-06b.

Outside backend/learning/ (spec §2, §12): reads llm_usage, never calls a model. Every grader,
grader_second, decision, loop_tutor* and session_close run site calls ``ai_budget.check(`` first
(invariant 23) and turns ``level == "hard"`` into "no model call", never into a verdict (spec §3.5
validity rule, invariant 28). ONE paged llm_usage read since the UTC month start, cached per request
id — no lru_cache (CLAUDE.md #98); tests/conftest.py resets the module state around every test.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Literal, NamedTuple

from learning.policy import Band
from services.events_service import log_event

logger = logging.getLogger("sapling.ai_budget")

Kind = Literal["tutor", "grader", "decision", "close"]
Scope = Literal["daily_usd", "monthly_usd", "daily_tokens", "session_requests",
                "session_deep", "daily_grades", "rate_limit", "platform"]
EventLevel = Literal["soft", "hard", "grader_cap"]

BUDGET_CAPPED_EVENT = "ai.budget_capped"  # spec §6

class _EmitKey(NamedTuple):
    user: str
    scope: str
    level: str
    day: str

_lock = threading.Lock()
_emitted: set[_EmitKey] = set()

def _utcnow() -> datetime:
    """The module clock; tests monkeypatch it."""
    return datetime.now(timezone.utc)

def _emit_capped(user_id: str | None, scope: Scope, level: EventLevel, *, band: Band | None = None,
                 spent_usd: float | None = None, cap_usd: float | None = None) -> None:
    """ai.budget_capped, at most once per process per (user, scope, level, UTC day) (spec §3.5)."""
    day = _utcnow().date().isoformat()
    key = _EmitKey(user_id or "platform", scope, level, day)
    with _lock:
        if key in _emitted:
            return
        _emitted.difference_update({k for k in _emitted if k.day != day})  # keep only today's keys
        _emitted.add(key)
    payload = {"user_id": user_id, "scope": scope, "band": band, "level": level,
               "spent_usd": spent_usd, "cap_usd": cap_usd}
    log_event(BUDGET_CAPPED_EVENT, category="usage", user_id=user_id,
              payload={k: v for k, v in payload.items() if v is not None})

def reset_for_tests() -> None:
    """Clear the per-process state (tests/conftest.py::_reset_ai_budget)."""
    with _lock:
        _emitted.clear()
```

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_ai_budget.py tests/test_event_capture_seams.py tests/test_events_service.py tests/test_learning_loop_invariants.py -q -k "not inv_23 and not inv_28" && venv/bin/ruff check .`
Expected: all passed — `test_inv_05` finds `ai.budget_capped` in the taxonomy; `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/services/ai_budget.py backend/services/events_service.py backend/tests/test_event_capture_seams.py backend/tests/conftest.py backend/tests/test_learning_ai_budget.py
git commit -m "feat(learning-loop): PKG-06b — ai.budget_capped in the taxonomy with a once-per-day emit helper

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 5: `ai_budget.check` and the degradation ladder

**Files:**
- Modify: `backend/services/ai_budget.py`, `backend/tests/test_learning_ai_budget.py`

**Interfaces:**
- Consumes: `db.connection.page_all`/`table`, the `config` budget names, `learning.params.LOOP_SESSION_MAX_*`, `learning.policy.Band`/`BudgetLevel`/`Tier`, `services.request_context.current_request_id`.
- Produces: `BudgetDecision`, `check(...)`, `_usage`, `_load_rows(user_id, since)` (the seam invariant 28 patches), `_next_day`, `_next_month`, the platform alert (`_maybe_check_platform`, `_check_platform`, `_spawn`).

- [ ] **Step 1: Write the failing tests** (append; add `import itertools` to the imports and `_ids = itertools.count()` beside `NOW`)

```python
# ── check(): the degradation ladder (spec §3.5) ──────────────────────────────

class _UsageTable:
    """Fake llm_usage for page_all: honours the user_id and created_at filters."""
    def __init__(self, rows, raises=None):
        self.rows, self.raises, self.reads = rows, raises, 0

    def select_with_count(self, columns, filters=None, order=None, limit=None, offset=None):
        if self.raises:
            raise self.raises
        self.reads += 1
        since = datetime.fromisoformat(filters["created_at"].removeprefix("gte.").replace("Z", "+00:00"))
        user = filters.get("user_id", "eq.").removeprefix("eq.")
        hits = [r for r in self.rows
                if datetime.fromisoformat(r["created_at"]) >= since and (not user or r["user_id"] == user)]
        return hits[(offset or 0):(offset or 0) + limit], len(hits)

def _row(*, cost=0.0, tokens=0, task="loop_tutor", ago_s=3600, user=UID):
    return {"id": f"row-{next(_ids)}", "user_id": user, "cost_usd": cost, "total_tokens": tokens,
            "task": task, "created_at": (NOW - timedelta(seconds=ago_s)).isoformat()}

@pytest.fixture
def usage(monkeypatch):
    monkeypatch.setattr(ai_budget, "_utcnow", lambda: NOW)
    monkeypatch.setattr(config, "PLATFORM_DAILY_BUDGET_USD", None)
    def install(rows, raises=None):
        fake = _UsageTable(list(rows), raises)
        monkeypatch.setattr(ai_budget, "table", lambda name: fake)
        return fake
    return install

def _develop_cap() -> float:
    return config.STUDENT_DAILY_BUDGET_USD

def _novice_cap() -> float:
    return config.STUDENT_DAILY_BUDGET_USD * config.BUDGET_NOVICE_MULTIPLIER

def _lt(d) -> tuple:
    return (d.level, d.tier_ceiling)

def test_below_the_soft_level_is_normal(usage, events):
    from learning import policy
    assert ai_budget.Tier is policy.Tier and ai_budget.BudgetLevel is policy.BudgetLevel
    usage([_row(cost=_develop_cap() * config.STUDENT_SOFT_FRACTION / 2)])
    d = ai_budget.check(UID, "tutor", "develop")
    assert (d.level, d.tier_ceiling, d.scope, d.pause_novice) == ("normal", "deep", None, False)
    assert events == []

@pytest.mark.parametrize("scope", ["daily_usd", "daily_tokens", "session_deep"])
def test_develop_soft_level_turns_deep_into_standard(usage, events, scope):
    rows, kw = [], {}
    if scope == "daily_usd":
        rows = [_row(cost=_develop_cap() * config.STUDENT_SOFT_FRACTION)]
    elif scope == "daily_tokens":
        rows = [_row(tokens=int(config.STUDENT_DAILY_TOKENS * config.STUDENT_SOFT_FRACTION))]
    else:
        kw = {"session_deep_requests": params.LOOP_SESSION_MAX_DEEP_REQUESTS}
    usage(rows)
    d = ai_budget.check(UID, "tutor", "develop", **kw)
    assert (d.level, d.tier_ceiling, d.scope, d.pause_novice) == ("soft", "standard", scope, False)
    assert [(e, k["payload"]["scope"], k["payload"]["level"]) for e, k in events] == [("ai.budget_capped", scope, "soft")]

@pytest.mark.parametrize("scope", ["daily_usd", "monthly_usd", "daily_tokens", "session_requests", "rate_limit"])
def test_hard_level_pauses_the_tutor_and_novice_concepts(usage, events, scope):
    rows, kw = [], {}
    if scope == "daily_usd":
        rows = [_row(cost=_develop_cap())]
    elif scope == "monthly_usd":
        rows = [_row(cost=config.STUDENT_MONTHLY_BUDGET_USD, ago_s=3 * 86_400)]  # earlier this month, not today
    elif scope == "daily_tokens":
        rows = [_row(tokens=config.STUDENT_DAILY_TOKENS)]
    elif scope == "rate_limit":
        rows = [_row(ago_s=5) for _ in range(config.LEARN_RATE_LIMIT_PER_MIN)]
    else:
        kw = {"session_tutor_requests": params.LOOP_SESSION_MAX_TUTOR_REQUESTS}
    usage(rows)
    for _ in range(3):
        d = ai_budget.check(UID, "tutor", "develop", **kw)
    # a rate-limit-only hard level pauses tutor turns but never novice concepts (spec §3.5)
    assert (d.level, d.tier_ceiling, d.scope, d.pause_novice) == ("hard", "none", scope, scope != "rate_limit")
    assert len(events) == 1, "once per (user, scope, level, UTC day)"
    payload = events[0][1]["payload"]
    assert (payload["scope"], payload["level"], payload["band"]) == (scope, "hard", "develop")
    if scope == "daily_usd":
        assert payload["spent_usd"] == pytest.approx(_develop_cap()) and payload["cap_usd"] == pytest.approx(_develop_cap())

def test_reset_at_reports_the_scope_that_lasts_longest(usage):
    usage([_row(cost=config.STUDENT_MONTHLY_BUDGET_USD)])  # today: daily AND monthly
    d = ai_budget.check(UID, "tutor", "develop")
    assert (d.scope, d.reset_at) == ("monthly_usd", datetime(2026, 10, 1, tzinfo=timezone.utc))
    usage([_row(cost=_develop_cap())])
    d = ai_budget.check(UID, "tutor", "develop")
    assert (d.scope, d.reset_at) == ("daily_usd", datetime(2026, 9, 27, tzinfo=timezone.utc))
    assert ai_budget._next_month(datetime(2026, 12, 15, tzinfo=timezone.utc)) == datetime(2027, 1, 1, tzinfo=timezone.utc)

def test_novice_band_rules(usage):
    usage([_row(cost=_develop_cap())])  # a develop turn is hard here; a novice turn runs to the novice allowance
    assert ai_budget.check(UID, "tutor", "develop").level == "hard"
    assert _lt(ai_budget.check(UID, "tutor", "novice")) == ("normal", "deep")
    usage([_row(cost=_novice_cap() * config.STUDENT_SOFT_FRACTION)])  # the $-soft level never downgrades novice deep
    assert _lt(ai_budget.check(UID, "tutor", "novice")) == ("soft", "deep")
    usage([])  # only the novice deep-request cap does; the develop cap does not apply to novice turns
    novice = params.LOOP_SESSION_MAX_DEEP_REQUESTS_NOVICE
    assert _lt(ai_budget.check(UID, "tutor", "novice", session_deep_requests=params.LOOP_SESSION_MAX_DEEP_REQUESTS)) == ("normal", "deep")
    assert _lt(ai_budget.check(UID, "tutor", "novice", session_deep_requests=novice)) == ("soft", "standard")
    usage([_row(cost=_novice_cap())])  # novice-band concepts pause at the novice hard level
    d = ai_budget.check(UID, "tutor", "novice")
    assert (d.level, d.tier_ceiling, d.pause_novice) == ("hard", "none", True)

def test_arm_sessions_are_not_downgraded_but_pause_at_hard(usage, events):
    usage([_row(cost=_develop_cap() * config.STUDENT_SOFT_FRACTION)])
    assert _lt(ai_budget.check(UID, "tutor", "develop", arm_session=True)) == ("normal", "deep")
    assert events[-1][1]["payload"]["level"] == "soft", "the cap hit is still recorded (spec §10 covariate)"
    d = ai_budget.check(UID, "tutor", "develop", arm_session=True,
                        session_tutor_requests=params.LOOP_SESSION_MAX_TUTOR_REQUESTS)
    assert _lt(d) == ("hard", "none")

def test_grader_cap_counts_grader_second_opinion_and_decision_rows(usage, events):
    per_task = config.STUDENT_DAILY_GRADES // 3
    rows = [_row(task=t) for t in ("grader", "grader_second", "decision") for _ in range(per_task)]
    rows += [_row(task="grader") for _ in range(config.STUDENT_DAILY_GRADES - len(rows))]
    rows += [_row(task="loop_tutor") for _ in range(5)]  # tutor rows never count as grades
    usage(rows)
    d = ai_budget.check(UID, "grader")
    assert (d.level, d.scope, d.pause_novice) == ("hard", "daily_grades", False)
    assert events[-1][1]["payload"] == {"user_id": UID, "scope": "daily_grades", "level": "grader_cap", "spent_usd": 0.0}
    assert ai_budget.check(UID, "decision").level == "hard"

def test_grading_below_the_grade_cap_survives_the_tutor_hard_level(usage):
    usage([_row(cost=config.STUDENT_MONTHLY_BUDGET_USD)]
          + [_row(task="grader") for _ in range(config.STUDENT_DAILY_GRADES - 1)])
    assert ai_budget.check(UID, "tutor", "develop").level == "hard"
    assert ai_budget.check(UID, "grader").level == "normal"
    assert ai_budget.check(UID, "decision").level == "normal"

def test_close_is_hard_on_spend_only_and_kinds_are_closed(usage):
    usage([_row(cost=_develop_cap() * config.STUDENT_SOFT_FRACTION)])
    assert ai_budget.check(UID, "close").level == "normal"  # no soft level for the close
    usage([_row(cost=_develop_cap())])
    assert ai_budget.check(UID, "close").level == "hard"
    assert ai_budget.check(UID, "close", "novice").level == "normal"  # band-aware: the novice allowance
    usage([_row(ago_s=5) for _ in range(config.LEARN_RATE_LIMIT_PER_MIN)])
    assert ai_budget.check(UID, "close").level == "normal"  # the rate limit belongs to the routes
    assert ai_budget.check("", "grader").level == "normal"  # system actors carry no student budget
    for bad in ((UID, "tutor"), (UID, "chat")):  # tutor without a band; unknown kind
        with pytest.raises(ValueError):
            ai_budget.check(*bad)

def test_one_usage_read_per_request(usage):
    from services import request_context
    fake = usage([_row(task="grader")])
    token = request_context._REQUEST_ID_CTX.set("req-budget-0001")
    try:
        for kind, band in (("grader", None), ("tutor", "develop"), ("close", None)):
            ai_budget.check(UID, kind, band)
    finally:
        request_context._REQUEST_ID_CTX.reset(token)
    assert fake.reads == 1
    ai_budget.check(UID, "grader")  # outside a request: no cache
    assert fake.reads == 2

def test_usage_read_failure_fails_open_but_session_caps_hold(usage, caplog):
    usage([], raises=RuntimeError("pg down"))
    with caplog.at_level("WARNING"):
        assert ai_budget.check(UID, "tutor", "develop").level == "normal"
        assert ai_budget.check(UID, "grader").level == "normal"
    assert any("llm_usage read failed" in r.getMessage() for r in caplog.records)
    d = ai_budget.check(UID, "tutor", "develop", session_tutor_requests=params.LOOP_SESSION_MAX_TUTOR_REQUESTS)
    assert (d.level, d.scope) == ("hard", "session_requests")

def test_platform_alert_is_alert_only_and_fires_once(usage, events, monkeypatch, caplog):
    monkeypatch.setattr(config, "PLATFORM_DAILY_BUDGET_USD", 10.0)
    monkeypatch.setattr(ai_budget, "_spawn", lambda fn: fn())
    fake = usage([_row(cost=10.0 * config.PLATFORM_ALERT_FRACTION, user="someone_else")])
    with caplog.at_level("WARNING"):
        assert ai_budget.check(UID, "grader").level == "normal"  # never blocks a request
    platform = [kw for _, kw in events if kw["payload"]["scope"] == "platform"]
    assert len(platform) == 1 and platform[0]["user_id"] is None and platform[0]["payload"]["level"] == "soft"
    assert any("platform spend" in r.getMessage() for r in caplog.records)
    reads = fake.reads
    ai_budget.check(UID, "grader")  # inside PLATFORM_CHECK_INTERVAL_S: only the per-user read
    assert fake.reads == reads + 1
```

- [ ] **Step 2: Run to verify they fail.** `cd backend && venv/bin/python -m pytest tests/test_learning_ai_budget.py -v` → the Task 2–4 tests still pass; every new test FAILS — `AttributeError: module 'services.ai_budget' has no attribute 'check'` (and `… 'table'` from the fixture).

- [ ] **Step 3: Implement** — extend `backend/services/ai_budget.py`. Imports become:

```python
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Literal, NamedTuple, get_args

import config
from db.connection import page_all, table
from learning import params
from learning.policy import Band, BudgetLevel, Tier
from services.events_service import log_event
from services.request_context import current_request_id
```

Below `BUDGET_CAPPED_EVENT` add:

```python
GRADE_TASKS = frozenset({"grader", "grader_second", "decision"})  # spec §3.5 STUDENT_DAILY_GRADES
RATE_LIMIT_WINDOW_S = 60  # spec §3.5: LEARN_RATE_LIMIT_PER_MIN counts rows in the last 60 s
_REQUEST_CACHE_MAX = 512  # entries; a memory bound, not a policy threshold
_DECEMBER = 12
_USAGE_COLUMNS = "id,cost_usd,total_tokens,task,created_at"
_USAGE_ORDER = "created_at.asc,id.asc"  # page_all needs a total order
_HARD_ORDER: tuple[Scope, ...] = ("daily_usd", "monthly_usd", "daily_tokens", "session_requests", "rate_limit")

@dataclass(frozen=True)
class BudgetDecision:
    """spec §3.5. ``tier_ceiling`` caps what policy.model_tier may choose; ``pause_novice``
    (tutor kind, hard level) = serve no check for a novice-band concept on any surface except the probe."""
    level: BudgetLevel
    tier_ceiling: Tier
    scope: Scope | None = None
    reset_at: datetime | None = None
    pause_novice: bool = False

_NORMAL = BudgetDecision(level="normal", tier_ceiling="deep")

@dataclass(frozen=True)
class _Usage:
    month_usd: float
    day_usd: float
    day_tokens: int
    day_grades: int
    minute_rows: int
    minute_oldest: datetime | None

_request_cache: dict[tuple[str, str], _Usage] = {}
_platform_checked_at: float | None = None
```

Extend `reset_for_tests` to also clear `_request_cache` and reset `_platform_checked_at = None` (declared `global`). Add the one- or two-line helpers, no code given: `_day_start(now)` (UTC midnight), `_next_day(now)`, `_month_start(now)`, `_next_month(now)` (December → January of the next year, compared against `_DECEMBER`), `_iso(ts)` (`"%Y-%m-%dT%H:%M:%SZ"`), `_parse_ts(value) -> datetime | None` (`fromisoformat` after `"Z" → "+00:00"`; naive → UTC; unparseable → `None` and the row is skipped), `_daily_cap(band)` (Behaviour 3), `_rate_reset(usage, now)` (`(usage.minute_oldest or now) + timedelta(seconds=RATE_LIMIT_WINDOW_S)`), `_spend_fields(scope, usage, cap) -> dict` (Behaviour 5; `{}` when `usage` is `None`), `_binding(hard: dict[Scope, datetime | None]) -> Scope` (Behaviour 4: the latest `reset_at` among the timed scopes in `_HARD_ORDER` order — `max` keeps the first on a tie — else the first triggered scope). Then:

```python
def _load_rows(user_id: str, since: datetime) -> list[dict]:
    """Every llm_usage row of the user since ``since``: one logical read, paged past max_rows."""
    return list(page_all(
        table("llm_usage"), _USAGE_COLUMNS,
        filters={"user_id": f"eq.{user_id}", "created_at": f"gte.{_iso(since)}"},
        order=_USAGE_ORDER,
    ))

def _summarise(rows: list[dict], now: datetime) -> _Usage:
    day0, minute0 = _day_start(now), now - timedelta(seconds=RATE_LIMIT_WINDOW_S)
    month_usd = day_usd = 0.0
    day_tokens = day_grades = minute_rows = 0
    oldest: datetime | None = None
    for row in rows:
        ts = _parse_ts(row.get("created_at"))
        if ts is None:
            continue
        cost = float(row.get("cost_usd") or 0)
        month_usd += cost
        if ts >= day0:
            day_usd += cost
            day_tokens += int(row.get("total_tokens") or 0)
            day_grades += row.get("task") in GRADE_TASKS
        if ts >= minute0:
            minute_rows += 1
            oldest = ts if oldest is None or ts < oldest else oldest
    return _Usage(month_usd, day_usd, day_tokens, day_grades, minute_rows, oldest)

def _usage(user_id: str) -> _Usage | None:
    """One llm_usage read per (request, user); None on a read error (fail open)."""
    rid = current_request_id()
    key = (rid, user_id) if rid else None
    if key is not None:
        with _lock:
            hit = _request_cache.get(key)
        if hit is not None:
            return hit
    now = _utcnow()
    try:
        rows = _load_rows(user_id, _month_start(now))
    except Exception as exc:  # fail open — see HANDOFF-06b Open questions
        logger.warning("ai_budget: llm_usage read failed for %s: %s", user_id, exc)
        return None
    summary = _summarise(rows, now)
    if key is not None:
        with _lock:
            if len(_request_cache) >= _REQUEST_CACHE_MAX:
                _request_cache.pop(next(iter(_request_cache)))
            _request_cache[key] = summary
    return summary

def _grade_decision(user_id: str, usage: _Usage | None, now: datetime) -> BudgetDecision:
    if usage is None or usage.day_grades < config.STUDENT_DAILY_GRADES:
        return _NORMAL
    _emit_capped(user_id, "daily_grades", "grader_cap", **_spend_fields("daily_grades", usage, 0.0))
    return BudgetDecision(level="hard", tier_ceiling="none", scope="daily_grades", reset_at=_next_day(now))

def _spend_decision(
    user_id: str, kind: Kind, band: Band | None, usage: _Usage | None, now: datetime,
    *, tutor_requests: int, deep_requests: int, arm_session: bool,
) -> BudgetDecision:
    cap = _daily_cap(band)
    hard: dict[Scope, datetime | None] = {}
    if usage is not None:
        if usage.day_usd >= cap:
            hard["daily_usd"] = _next_day(now)
        if usage.month_usd >= config.STUDENT_MONTHLY_BUDGET_USD:
            hard["monthly_usd"] = _next_month(now)
        if usage.day_tokens >= config.STUDENT_DAILY_TOKENS:
            hard["daily_tokens"] = _next_day(now)
        if kind == "tutor" and usage.minute_rows >= config.LEARN_RATE_LIMIT_PER_MIN:
            hard["rate_limit"] = _rate_reset(usage, now)
    if kind == "tutor" and tutor_requests >= params.LOOP_SESSION_MAX_TUTOR_REQUESTS:
        hard["session_requests"] = None
    if hard:
        scope = _binding(hard)
        _emit_capped(user_id, scope, "hard", band=band, **_spend_fields(scope, usage, cap))
        return BudgetDecision(level="hard", tier_ceiling="none", scope=scope, reset_at=hard[scope],
                              pause_novice=kind == "tutor")
    if kind == "close":
        return _NORMAL
    soft: list[Scope] = []
    if usage is not None and usage.day_usd >= config.STUDENT_SOFT_FRACTION * cap:
        soft.append("daily_usd")
    if usage is not None and usage.day_tokens >= config.STUDENT_SOFT_FRACTION * config.STUDENT_DAILY_TOKENS:
        soft.append("daily_tokens")
    deep_cap = (params.LOOP_SESSION_MAX_DEEP_REQUESTS_NOVICE if band == "novice"
                else params.LOOP_SESSION_MAX_DEEP_REQUESTS)
    if deep_requests >= deep_cap:
        soft.append("session_deep")
    if not soft:
        return _NORMAL
    scope = soft[0]
    _emit_capped(user_id, scope, "soft", band=band, **_spend_fields(scope, usage, cap))
    if arm_session:
        return _NORMAL  # arms are exempt from downgrades; they pause at hard (spec §3.5)
    novice_keeps_deep = band == "novice" and "session_deep" not in soft
    return BudgetDecision(level="soft", tier_ceiling="deep" if novice_keeps_deep else "standard", scope=scope,
                          reset_at=None if scope == "session_deep" else _next_day(now))

def check(
    user_id: str, kind: Kind, band: Band | None = None, *,
    session_tutor_requests: int = 0, session_deep_requests: int = 0, arm_session: bool = False,
) -> BudgetDecision:
    """The degradation ladder of spec §3.5. Call it module-qualified — ``ai_budget.check(`` —
    before every grader, grader_second, decision, loop_tutor* and session_close run
    (invariant 23). ``band`` is required for ``tutor`` and ignored for the grader cap; the
    session counters are the ints PKG-07 keeps in sessions.loop_state."""
    if kind not in get_args(Kind):
        raise ValueError(f"ai_budget.check: unknown kind {kind!r}")
    if kind == "tutor" and band is None:
        raise ValueError("ai_budget.check: band is required for kind='tutor' (spec §3.5)")
    _maybe_check_platform()
    if not user_id:
        return _NORMAL  # system actors carry no student budget
    usage, now = _usage(user_id), _utcnow()
    if kind in ("grader", "decision"):
        return _grade_decision(user_id, usage, now)
    return _spend_decision(user_id, kind, band, usage, now, tutor_requests=session_tutor_requests,
                           deep_requests=session_deep_requests, arm_session=arm_session)
```

Platform alert (Behaviour 6), three functions: `_spawn(fn)` starts `threading.Thread(target=fn, name="ai-budget-platform", daemon=True)` (tests replace it with an inline call); `_maybe_check_platform()` returns at once when `config.PLATFORM_DAILY_BUDGET_USD is None`, otherwise, under `_lock`, compares `time.monotonic()` with the `global _platform_checked_at` against `config.PLATFORM_CHECK_INTERVAL_S`, stamps it, and `_spawn(_check_platform)`; `_check_platform()` sums `cost_usd` over `page_all(table("llm_usage"), "id,cost_usd,created_at", filters={"created_at": f"gte.{_iso(_day_start(_utcnow()))}"}, order=_USAGE_ORDER)` (no user filter), logs `"ai_budget: platform spend read failed: %s"` and returns on any exception, and when `spent >= config.PLATFORM_ALERT_FRACTION * budget` logs one WARNING containing `platform spend` and calls `_emit_capped(None, "platform", "soft", spent_usd=spent, cap_usd=budget)`.

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/ruff format services/ai_budget.py tests/test_learning_ai_budget.py && venv/bin/python -m pytest tests/test_learning_ai_budget.py -q && venv/bin/ruff check .`
Expected: all passed; `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/services/ai_budget.py backend/tests/test_learning_ai_budget.py
git commit -m "feat(learning-loop): PKG-06b — ai_budget.check and the band-aware degradation ladder

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 6: Rate limit, the FastAPI dependency, the 429 handler

**Files:**
- Modify: `backend/services/ai_budget.py`, `backend/main.py`, `backend/tests/test_learning_ai_budget.py`

**Interfaces:**
- Consumes: `services.auth_guard.get_session_user_id`.
- Produces: `rate_limited(user_id) -> bool`, `enforce_rate_limit_for(user_id) -> None` (inline), `enforce_rate_limit(request) -> None` (dependency), `AIBudgetExceeded(decision)`, `budget_exceeded_handler(request, exc)`, `BUDGET_REACHED_DETAIL`; the handler registered in `main.py`.

- [ ] **Step 1: Write the failing tests** (append)

```python
# ── rate limit and the 429 body (spec §3.5, §9, A20) ─────────────────────────

def _budget_app():
    from fastapi import Depends, FastAPI
    app = FastAPI()
    app.add_exception_handler(ai_budget.AIBudgetExceeded, ai_budget.budget_exceeded_handler)

    @app.post("/model", dependencies=[Depends(ai_budget.enforce_rate_limit)])
    def model_route():
        return {"ok": True}
    return app

def test_rate_limited_counts_llm_usage_rows_in_the_last_minute(usage):
    usage([_row(ago_s=5) for _ in range(config.LEARN_RATE_LIMIT_PER_MIN - 1)]
          + [_row(ago_s=120) for _ in range(5)])
    assert ai_budget.rate_limited(UID) is False
    usage([_row(ago_s=5) for _ in range(config.LEARN_RATE_LIMIT_PER_MIN)])
    assert ai_budget.rate_limited(UID) is True

def test_enforce_rate_limit_answers_429_with_reset_at(usage, events, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setattr(ai_budget, "get_session_user_id", lambda request: UID)
    usage([_row(ago_s=30) for _ in range(config.LEARN_RATE_LIMIT_PER_MIN)])
    r = TestClient(_budget_app()).post("/model")
    assert r.status_code == 429
    body = r.json()
    assert body["detail"] == "ai budget reached" == ai_budget.BUDGET_REACHED_DETAIL
    assert body["reset_at"] == (NOW + timedelta(seconds=30)).isoformat()
    assert body["scope"] == "rate_limit"
    assert int(r.headers["Retry-After"]) >= 1
    assert events[-1][1]["payload"]["scope"] == "rate_limit"
    usage([])
    assert TestClient(_budget_app()).post("/model").json() == {"ok": True}

def test_main_registers_the_budget_handler():
    from main import app
    assert app.exception_handlers.get(ai_budget.AIBudgetExceeded) is ai_budget.budget_exceeded_handler
```

- [ ] **Step 2: Run to verify they fail.** `cd backend && venv/bin/python -m pytest tests/test_learning_ai_budget.py -v -k "rate_limit or 429 or registers"` → FAIL — `AttributeError: module 'services.ai_budget' has no attribute 'AIBudgetExceeded'` / `'rate_limited'`.

- [ ] **Step 3: Implement** — add to the `ai_budget` imports `from fastapi import Request, status`, `from fastapi.responses import JSONResponse`, `from services.auth_guard import get_session_user_id`; add `BUDGET_REACHED_DETAIL = "ai budget reached"  # spec §3.5 / A20 429 body` beside the other constants; then:

```python
class AIBudgetExceeded(Exception):
    """Over budget; main.py maps it to the §3.5 429 body. Raised by PKG-07 (tutor hard) and enforce_rate_limit."""
    def __init__(self, decision: BudgetDecision):
        super().__init__(BUDGET_REACHED_DETAIL)
        self.decision = decision

def _rate_limit_decision(user_id: str) -> BudgetDecision | None:
    usage = _usage(user_id)
    if usage is None or usage.minute_rows < config.LEARN_RATE_LIMIT_PER_MIN:
        return None
    return BudgetDecision(level="hard", tier_ceiling="none", scope="rate_limit",
                          reset_at=_rate_reset(usage, _utcnow()))

def rate_limited(user_id: str) -> bool:
    """llm_usage rows of the user in the last RATE_LIMIT_WINDOW_S ≥ LEARN_RATE_LIMIT_PER_MIN.
    Cross-worker (it counts DB rows); fails open on a read error."""
    return _rate_limit_decision(user_id) is not None

def enforce_rate_limit_for(user_id: str) -> None:
    """The rate limit, callable inline where only SOME bodies of a route run a model
    (PKG-12's /review/answer checks it for kind="check" only — a self-rated flashcard
    runs none and is never rate-limited, spec §3.5)."""
    decision = _rate_limit_decision(user_id)
    if decision is None:
        return
    _emit_capped(user_id, "rate_limit", "hard")
    raise AIBudgetExceeded(decision)


def enforce_rate_limit(request: Request) -> None:
    """FastAPI dependency. PKG-07 attaches it to every model-calling /api/learn/loop/*
    route — never to GET /status or GET /sessions (spec §9)."""
    enforce_rate_limit_for(get_session_user_id(request))

async def budget_exceeded_handler(request: Request, exc: AIBudgetExceeded) -> JSONResponse:
    rid = getattr(request.state, "request_id", None) or current_request_id()
    reset_at = exc.decision.reset_at
    headers: dict[str, str] = {}
    if reset_at is not None:
        headers["Retry-After"] = str(max(1, int((reset_at - _utcnow()).total_seconds())))
    if rid:
        headers["X-Request-ID"] = rid
    content = {"detail": BUDGET_REACHED_DETAIL, "reset_at": reset_at.isoformat() if reset_at else None,
               "scope": exc.decision.scope, "request_id": rid}
    return JSONResponse(status_code=status.HTTP_429_TOO_MANY_REQUESTS, content=content, headers=headers)
```

`backend/main.py`: `from services import ai_budget` with the other service imports, and after the three `@app.exception_handler` blocks (before the router mounts):
```python
# PKG-06b (spec §3.5, A20): an over-budget model call answers 429 {"detail": "ai budget reached", "reset_at": …}.
app.add_exception_handler(ai_budget.AIBudgetExceeded, ai_budget.budget_exceeded_handler)
```

- [ ] **Step 4: Run tests, lint**

Run: `cd backend && venv/bin/python -m pytest tests/test_learning_ai_budget.py tests/test_event_capture_seams.py tests/test_learn_routes.py -q && venv/bin/ruff check .`
Expected: all passed (the legacy learn routes unchanged); `All checks passed!`

- [ ] **Step 5: Commit**

```
git add backend/services/ai_budget.py backend/main.py backend/tests/test_learning_ai_budget.py
git commit -m "feat(learning-loop): PKG-06b — per-user rate limit dependency and the 429 budget body

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 7: Reopen PKG-05 and PKG-05b — the run sites check the budget first

Two commits, one per reopened package (README "Touching an earlier package's code"; they need Task 5's `ai_budget.check`).

**Files:**
- Modify: `backend/agents/grader.py`, `backend/services/decisions.py`, `backend/tests/test_learning_ai_budget.py`, `docs/superpowers/plans/learning-loop/{HANDOFF-05.md,HANDOFF-05b.md,LEDGER.md}`

**Interfaces:**
- Consumes: `ai_budget.check`; PKG-05 `grade`, `_run_once`, `grader_agent`, `GradeResult`; PKG-05b `_run_decision`, `decision_agent`.
- Produces: capped `grade()` → `GradeResult(unavailable=True)` with no model call; capped `_run_once` → `UsageLimitExceeded`; capped `_run_decision` → `None` with no model call.

- [ ] **Step 1: Write the failing tests** (append; add `import asyncio` to the imports)

```python
# ── reopens: grader and decision run sites check the grade cap first (A20, A22) ──

def _deps():
    from agents.deps import SaplingDeps
    return SaplingDeps(user_id=UID, course_id="course-1", supabase=None, request_id="req-1", learning_loop=True)

def _must_not_run(runs: list):
    def fn(messages, info):
        runs.append(1)
        raise AssertionError("an agent ran under the grader cap")
    return fn

def test_grade_is_unavailable_at_the_grader_cap_without_a_model_call(usage):
    from pydantic_ai.exceptions import UsageLimitExceeded
    from pydantic_ai.models.function import FunctionModel
    from agents import grader
    usage([_row(task="grader") for _ in range(config.STUDENT_DAILY_GRADES)])
    runs: list = []
    item = SimpleNamespace(id="item-1", prompt="Q?", reference_answer="REF",
                           rubric=[{"id": "r1", "text": "t"}], common_wrong=[], format="free")
    with grader.grader_agent.override(model=FunctionModel(_must_not_run(runs))):
        result = asyncio.run(grader.grade(item, format="free", student_answer="an answer", deps=_deps()))
        with pytest.raises(UsageLimitExceeded):  # the second-opinion run site is guarded too
            asyncio.run(grader._run_once("m", _deps(), second_opinion=True))
    assert result.unavailable is True and runs == []

def test_decision_run_is_skipped_at_the_grader_cap(usage):
    from pydantic_ai.models.function import FunctionModel
    from agents.decision import decision_agent
    from services import decisions
    usage([_row(task="decision") for _ in range(config.STUDENT_DAILY_GRADES)])
    runs: list = []
    with decision_agent.override(model=FunctionModel(_must_not_run(runs))):
        assert asyncio.run(decisions._run_decision("judge_leak", None, _deps())) is None
    assert runs == []
```

- [ ] **Step 2: Run to verify they fail.** `cd backend && venv/bin/python -m pytest tests/test_learning_ai_budget.py -v -k "grader_cap"` → FAIL: `AssertionError: an agent ran under the grader cap` (or an `AttributeError` on the `None` state, reached only because nothing checked the cap).

- [ ] **Step 3: Reopen PKG-05.** In `agents/grader.py` add `from services import ai_budget`; make the first statement of `grade`
```python
    if ai_budget.check(deps.user_id, "grader").level == "hard":  # spec §3.5 grader cap (PKG-06b), invariant 28
        return GradeResult(unavailable=True)
```
and of `_run_once` (the run site of both runs; invariant 23)
```python
    if ai_budget.check(deps.user_id, "grader").level == "hard":  # grade() maps this to unavailable
        raise UsageLimitExceeded("ai budget: grader cap reached")
```
Run: `cd backend && venv/bin/python -m pytest tests/test_learning_check_tool.py tests/test_learning_ai_budget.py -q -k "not decision_run"` → all passed. Append `| 05 | grader-check-tool | reopened | feat/learning-loop-06b-ai-budget-and-usage | <sha> | test_grade_is_unavailable_at_the_grader_cap_without_a_model_call | — | HANDOFF-05.md |` to `LEDGER.md`, and to `HANDOFF-05.md` "Post-hoc changes": `PKG-06b <date>: grade() and _run_once check ai_budget.check(user_id, "grader") first; hard → GradeResult(unavailable=True) (spec §3.5, §13 A20) — commit <sha>`.
```
git add backend/agents/grader.py backend/tests/test_learning_ai_budget.py docs/superpowers/plans/learning-loop/HANDOFF-05.md docs/superpowers/plans/learning-loop/LEDGER.md
git commit -m "fix(learning-loop): PKG-05 — grade() checks the grader cap first

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 4: Reopen PKG-05b.** In `services/decisions.py` add `from services import ai_budget` and make the first statement of `_run_decision` (the only `decision_agent.run(`)
```python
    if ai_budget.check(deps.user_id, "decision").level == "hard":  # spec §3.5: decisions count as grades
        return None  # the callers' existing unavailable path runs
```
Run: `cd backend && venv/bin/python -m pytest tests/test_learning_decisions.py tests/test_learning_ai_budget.py -q` → all passed. Ledger `| 05b | decision-seam | reopened | … |`; `HANDOFF-05b.md` "Post-hoc changes": `PKG-06b <date>: _run_decision checks ai_budget.check(user_id, "decision") first; hard → None (the unavailable path) — commit <sha>`.
```
git add backend/services/decisions.py backend/tests/test_learning_ai_budget.py docs/superpowers/plans/learning-loop/HANDOFF-05b.md docs/superpowers/plans/learning-loop/LEDGER.md
git commit -m "fix(learning-loop): PKG-05b — decision runs check the budget first

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 5: Re-verify both reopened packages and the invariants.** Run every PKG-05 and PKG-05b row of §State of the world, then `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_23 or inv_28"`. Expected: every row as listed (eval replays: every evaluator ≥ baseline — a budget read for the harness's `eval-user` finds nothing or fails open with one WARNING, never changing a verdict); `2 passed`. Append `verified` rows for 05 and 05b (verified-by `06b, <date>, <command> → <output>`); they are committed with Task 8.

### Task 8: Hand-off + ledger

- [ ] **Step 1:** Write `docs/superpowers/plans/learning-loop/HANDOFF-06b.md` from `HANDOFF-template.md`. "Verify commands" must be exactly these six lines (they become PKG-07/09/12/13/14's State-of-the-world rows):

```
cd backend && venv/bin/python -m pytest tests/test_learning_ai_budget.py -q                     → N passed (N ≥ 15)
ls backend/db/migrations/*_learning_llm_usage_tokens.sql                                         → 1 file
grep -cE "^(async )?def (check|rate_limited|enforce_rate_limit)\(" backend/services/ai_budget.py → 3
grep -c '"ai\.budget_capped"' backend/services/events_service.py                                 → 1
grep -c "cached_tokens" backend/agents/usage.py                                                  → ≥ 1
cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_23 or inv_28" → 2 passed
```

"Symbols added": every public name of `services/ai_budget.py` with its contract (`check` is SYNC; call it module-qualified as `ai_budget.check(` or invariant 23 will not see it; `pause_novice` means "skip a novice-band concept" and is meaningful on `check(user_id, "tutor", "novice")`; `AIBudgetExceeded(decision)` is how a route returns the 429), `llm_pricing.CACHED_INPUT_PRICING` and the `cost_usd(..., cached_tokens=)` keyword, `events_service.log_llm_usage(..., cached_tokens=, thinking_tokens=)`, `agents.usage._cache_and_thinking`, columns `llm_usage.cached_tokens`/`thinking_tokens`, event `ai.budget_capped`, the conftest fixture `_reset_ai_budget`, the three `params` names, the ten `config` names. "Constants chosen": the §Named constants table with every `†`. "Deviations": the 429 body carries `scope` and `request_id` beside the spec's `detail`/`reset_at` (additive; the house error envelope); the event lands (Task 4) before `check` (Task 5) so the `ai.` literal never exists outside the taxonomy. "Known gaps": no caller of `check("tutor")`/`enforce_rate_limit` (PKG-07), `check("close")` (PKG-09), the review pause (PKG-12), the kill-switch path (PKG-14b); invariant 23 matches `stream_agent_turn` only when the agent is passed by name — PKG-07 keeps that shape or extends `_budget_scan`; the month read grows with the month (`page_all` pages at 1000; an aggregate RPC would be one round trip); rows land ≤ 1 s after a call (events queue), so a request can overshoot a cap by its own calls; `llm_usage` rows written without `user_id` (document uploads and a few legacy routes) do not count toward a student's budget; caps are inert when `EVENTS_LOGGING_ENABLED=false` (no rows are written); the platform read scans all of today's rows every `PLATFORM_CHECK_INTERVAL_S` per process (off the request thread); `tests/evals/_replay.make_deps()` uses user `eval-user`, so an eval replay performs one budget read. "Open questions for the series owner": (a) arm sessions below hard get `normal` — no soft behaviour at all (RAG k, search, tier) — reading "exempt from downgrades" as full exemption so the arms stay comparable; the event still fires (took: full exemption); (b) an `llm_usage` read error fails open for the $/token/grade/rate scopes (took: fail open, session caps kept); (c) `check(…, "close")` is hard on spend only, never soft, `band=None` = develop/profic allowance (took: that); (d) `cached_tokens`/`thinking_tokens` are `0`, not NULL, for a Gemini response that reports none — the spec's "None when absent" read as "the usage shape has no such field" so §11.1's non-null smoke check can pass (took: that); (e) the owner sets `PLATFORM_DAILY_BUDGET_USD` on staging/production (unset = no alert); (f) a capped decision takes PKG-05b's unavailable path, so it emits `decision.fallback{reason: both_failed}` — a `budget` reason would read better but spec §6's enum has none (took: no new enum value).

- [ ] **Step 2:** Ledger: append `| 06b | ai-budget-and-usage | done | feat/learning-loop-06b-ai-budget-and-usage | <sha> | N tests (test_learning_ai_budget.py) + inv_23, inv_28 cap half | — | HANDOFF-06b.md |`, plus the 05/05b `verified` rows from Task 7 Step 5 if not yet appended. Deviations: `PKG-06b: spec §3.5 names LOOP_SESSION_MAX_* for params.py → appended on PKG-01's behalf → A6 convention` and the 429-body line above. `HANDOFF-01.md` "Post-hoc changes": `PKG-06b <date>: appended LOOP_SESSION_MAX_TUTOR_REQUESTS, LOOP_SESSION_MAX_DEEP_REQUESTS, LOOP_SESSION_MAX_DEEP_REQUESTS_NOVICE (spec §3.5) — commit <sha>`.

- [ ] **Step 3: Commit**

```
git add docs/superpowers/plans/learning-loop/HANDOFF-06b.md docs/superpowers/plans/learning-loop/HANDOFF-01.md docs/superpowers/plans/learning-loop/LEDGER.md
git commit -m "docs(learning-loop): PKG-06b — hand-off and ledger

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

### Task 9: PR

- [ ] **Step 1:** Run the self-check loop once more (below), including the E2E cycle, then:

```
gh pr create --title "feat(learning): PKG-06b ai-budget-and-usage" --body-file - <<'EOF'
Learning loop series, package 9 of 17. Spec: docs/superpowers/specs/2026-09-26-learning-loop-design.md §3.5, §4, §6, §8 (23, 28), §13 A20/A21.

- services/ai_budget.py: band-aware per-student caps and the degradation ladder (daily $ with the novice multiplier, monthly $, daily tokens, session request caps, grader cap, rate limit), one llm_usage read per request, a once-per-day ai.budget_capped event, an alert-only platform check; no model calls
- enforce_rate_limit dependency + AIBudgetExceeded → 429 {"detail": "ai budget reached", "reset_at": …} (registered in main.py, attached nowhere yet — PKG-07)
- reopens PKG-05 (grade() checks the grader cap first) and PKG-05b (decision runs check the budget first): a capped attempt writes no evidence for either outcome (invariant 28)
- llm_usage.cached_tokens / thinking_tokens (A21) + the cached-input rate in cost_usd
- invariant 23 asserted (AST scan of every grader/decision run site; picks up loop_tutor and session_close when they land)

Students see nothing new: the checks sit only on loop-path run sites, and the loop is dark during the build. † caps: STUDENT_DAILY_BUDGET_USD, BUDGET_NOVICE_MULTIPLIER, STUDENT_SOFT_FRACTION, STUDENT_MONTHLY_BUDGET_USD, STUDENT_DAILY_TOKENS, STUDENT_DAILY_GRADES, LEARN_RATE_LIMIT_PER_MIN, LOOP_SESSION_MAX_*.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
```

## Self-check loop (run after every task, and once more before the PR)

1. `cd backend && venv/bin/ruff check . && venv/bin/ruff format --check services/ai_budget.py tests/test_learning_ai_budget.py tests/test_learning_loop_invariants.py learning`
2. `venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q` (until Task 7 lands, `test_inv_23` and `test_inv_28` are the only permitted failures)
3. `venv/bin/python -m pytest tests/ -q` (no `SAPLING_MODEL_MODE` exported; same two permitted failures until Task 7)
4. Prompts/tool descriptions touched? **No** → no new eval. The grader and decision code paths changed (Task 7), so re-run `SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/grader.py` and `tests/evals/decisions.py` once after Task 7: every evaluator ≥ baseline.
5. Request-path agent or route touched? **Yes, a request-path service**: every `llm_usage` write now carries two new columns, and `main.py` gained a handler. Run ONE E2E cycle before the PR, in ONE flock invocation, and prove the columns fill on PG15: `flock /tmp/claude-$(id -u)/sapling-e2e-stack.lock -c 'make e2e-up && (cd frontend && npx playwright test) && (cd backend && venv/bin/python -m e2e_oracles) && psql "<local stack DB URL from docs/local-supabase.md>" -tAc "SELECT count(*) FROM llm_usage WHERE cached_tokens IS NOT NULL AND thinking_tokens IS NOT NULL"; rc=$?; make e2e-down; exit $rc'` → journeys pass unchanged (the loop flag is unset in the stack), oracles exit 0 (`logscan` shows no `events flush dropped`), the count is ≥ 1 (function-mode runs report a `RunUsage`). No new spec, no handler constants.
6. Scope check: `git diff --stat main...HEAD` — every path must be in this prompt's Files lists. Anything else: `git checkout main -- <path>` or record a Deviation.
7. Sync check: `grep -o "E2E_[A-Z_]*" backend/agents/function_handlers_e2e.py | sort -u` unchanged from `main`.

Green = all seven clean. Max 5 iterations per loop; then write a `BLOCKED` row in `LEDGER.md` with hypothesis, commands, outputs, and stop.

## Regression guard

- Pre-series suite count N₀ (from State of the world) unchanged except for the tests this package adds. Zero failures, zero new skips outside `test_learning_loop_invariants.py`.
- Dependency suites unchanged and green: PKG-00 (`test_learning_gate.py`, `test_learning_deps.py`), PKG-01/02 (`test_learning_bkt.py`, `test_learning_fsrs.py` — no `params.py` value moved), PKG-03 (`test_learning_evidence_apply.py`, `test_graph_service.py`), PKG-05 (`test_learning_check_tool.py`), PKG-05b (`test_learning_decisions.py`), PKG-06 (`test_learning_zpd_policy.py`).
- Pre-series suites this package touches, unchanged except the one pinned string and the two new row keys: `test_event_capture_seams.py`, `test_events_service.py`, `test_llm_pricing.py`, `test_agent_usage.py`, `test_usage_instrumentation_coverage.py`, `test_admin_analytics_routes.py`; untouched and green: `test_learn_routes.py`, `test_learn_stream_routes.py`, `test_chat_stream.py`, `test_model_mode_seam.py`.
- With `LEARNING_LOOP_ENABLED` unset or set: no route behaviour changes (`grep -rn "ai_budget\|enforce_rate_limit" backend/routes` → nothing).

## Acceptance criteria (the next session pastes these)

1. `cd backend && venv/bin/python -m pytest tests/test_learning_ai_budget.py -q` → `N passed (N ≥ 15)`
2. `ls backend/db/migrations/*_learning_llm_usage_tokens.sql` → `1 file`
3. `grep -cE "^(async )?def (check|rate_limited|enforce_rate_limit)\(" backend/services/ai_budget.py` → `3`
4. `grep -c '"ai\.budget_capped"' backend/services/events_service.py` → `1`
5. `grep -c "cached_tokens" backend/agents/usage.py` → `≥ 1`
6. `cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_23 or inv_28"` → `2 passed`
7. `cd backend && venv/bin/python -m pytest tests/test_learning_check_tool.py tests/test_learning_decisions.py -q` → all passed (the reopened packages stay green)
8. `grep -c "add_exception_handler(ai_budget.AIBudgetExceeded" backend/main.py` → `1`; `grep -rn "ai_budget\|enforce_rate_limit" backend/routes` → no output
9. `grep -rnE "^\s*(from|import)\s+(agents|pydantic_ai|google)\b" backend/services/ai_budget.py` → no output
10. `cd backend && venv/bin/python -m pytest tests/ -q` → zero failures; `venv/bin/ruff check .` → `All checks passed!`
11. `git diff --stat main...HEAD` lists only: `backend/config.py`, `backend/learning/params.py`, `backend/services/{ai_budget,llm_pricing,events_service}.py`, `backend/agents/{usage,grader}.py`, `backend/services/decisions.py`, `backend/main.py`, `backend/db/migrations/*_learning_llm_usage_tokens.sql`, `backend/tests/{test_learning_ai_budget,test_learning_loop_invariants,test_event_capture_seams,conftest}.py`, `docs/superpowers/plans/learning-loop/{HANDOFF-06b.md,HANDOFF-05.md,HANDOFF-05b.md,HANDOFF-01.md,LEDGER.md}`.
12. `LEDGER.md` has `06b | ai-budget-and-usage | done | …`, `05 | … | reopened` and `05b | … | reopened` rows, and later `verified` rows for 05 and 05b.

## Hand-off

`docs/superpowers/plans/learning-loop/HANDOFF-06b.md` per the template; the Verify commands block is fixed above (Task 8) and is the canonical PKG-06b block every later State of the world copies. Symbols, Constants, Deviations, Known gaps and Open questions: as Task 8 lists them.

## Do not

- Do not call a model, import `agents`/`pydantic_ai`/`google`, or put `ai_budget` under `backend/learning/`. No `lru_cache`, no Redis, no SQL function or RPC, no migration other than §Schema's.
- Do not attach `enforce_rate_limit` or call `ai_budget` from any route, `services/chat_stream.py` or `routes/learn.py` (PKG-07 wires the loop routes; PKG-14b the kill-switch path). Do not mount `routes/learn_loop.py`. Never read `model_pref`.
- A cap never creates, weakens or re-channels evidence and never records one outcome while dropping the other: a capped grader returns `unavailable`, never a verdict; never route a capped grade to another backend or to code comparison.
- Every threshold is a named constant (`config.*`, `params.*` or an `ai_budget` module constant); no numeral other than `0`/`1`/`0.0`/`1.0` in `ai_budget.py` logic. Never change a spec value; `†` values move only by owner decision in spec §13.
- All Supabase access through `db.connection.table()`/`page_all`; no `httpx`, no `supabase` import.
- Migration: UTC-timestamp prefix, `_learning_` infix, §Schema DDL verbatim, append-only, never edited after creation.
- Do not add a second event, put `"ai.` in quotes anywhere else in `events_service.py`, or make `log_event` enforce membership. Never put student text in an event payload.
- Do not write `LEARNING_LOOP_ENABLED` or any budget value into `.env.example`, docker-compose or a deployed config.
- Do not skip, xfail, or delete any pre-existing test. Do not hand-edit eval cassettes or baselines. Logscan `ALLOWLIST` in `backend/e2e_oracles/logscan.py` stays `()`.
- End every commit with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; end the PR body with the Claude Code attribution line.

## If you get stuck

1. Re-read §Spec and the spec file's §3.5 (the Degradation ladder table and the validity rule) and §8.23/§8.28 before guessing.
2. Three failed iterations on one task → append a `BLOCKED` row to `LEDGER.md` (hypothesis, commands run, outputs), commit what is green, open the PR as draft, stop.
3. Never widen scope to unblock. Never disable a test to unblock. If a PKG-05/05b name differs from this prompt, it is a lookup (Read-before item 2), not a deviation.
4. Ambiguity → choose the option closest to the spec, mark it `†` in the hand-off, continue.
