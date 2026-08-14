# Sapling

A FastAPI + Supabase backend that ingests student documents, calls Gemini to classify/summarize/extract assignments, and serves a knowledge-graph-backed tutoring chat to a React frontend.

## Stack

- FastAPI: HTTP layer; app + router mounts in `backend/main.py`.
- Supabase (PostgREST): primary datastore; accessed via `httpx` REST through `db/connection.py`.
- Gemini (`google-genai`): LLM provider, reached only through Pydantic AI agents (the legacy `services/gemini_service.py` seam was deleted — ADR 0024).
- Pydantic AI: agent framework (`pydantic-ai-slim[google]` in `requirements.txt`); agents live under `backend/agents/`.
- React frontend: lives in `frontend/` (out of scope for backend sessions).
- pytest: backend test runner, fixtures in `tests/conftest.py`.

## Repo map

- backend/main.py:87 — FastAPI app + CORS; every router mount lives in the block at :150–169.
- backend/routes/documents.py — `upload_document` POST `/api/documents/upload` streaming SSE pipeline (+ `/upload/sync` JSON twin) over the classifier/summary/concepts/syllabus agents.
- backend/routes/learn.py — tutor routes; streamed turns (`POST /api/learn/chat/stream` + `/start-session/stream`) run through `services/chat_stream.py::stream_agent_turn` (#349).
- backend/routes/quiz.py:1 — quiz session create/answer/score endpoints.
- backend/routes/notes.py:32 — `/api/notes` notetaker CRUD, concept link/unlink, and agent actions (`summarize`/`extract-concepts`/`chat`/`send-to-tutor`/`generate-quiz`).
- backend/routes/academics.py — `/api` terms/offerings/enrollments endpoints over the redesigned schema.
- backend/routes/auth.py:1 — Google OAuth + HMAC session token issuance; also `POST /api/auth/test-login`, the local/test-only session minter for pytest + Playwright (404s unless `APP_ENV in {local, test}`).
- backend/services/session_tokens.py — canonical `mint_session` / `SESSION_COOKIE_NAME`; the only place the `sapling_session` wire format is built.
- backend/services/academics.py — term/offering/enrollment resolver (`current_term`/`list_terms`/`resolve_offering`/`offering_course_id`/`user_offering_ids_for_course`/`term_for_offering`); the API boundary keeps the abstract `course_id`.
- backend/services/profiles.py — `get_display_name`/`get_display_names`, decrypting the name off `user_profiles`.
- backend/agents/_providers.py — per-task model slots (`model_for`) + the `SAPLING_MODEL_MODE` seam; the single LLM chokepoint every agent runs through.
- backend/services/notes_service.py:49 — notes CRUD with column encryption (`create_note`/`update_note`/`save_summary`/`link_concept`).
- backend/services/graph_service.py:461 — `apply_graph_update` (becomes a Pydantic AI tool).
- backend/services/tool_signals.py — `report_empty_result`: the silent-empty detector every agent read tool routes its result through (F5). Zero rows for a user who plausibly should have data → WARN + `quiz.tool_empty`.
- backend/services/prompt_dimensions.py — per-request prompt-composition capture (F6); rides `quiz.started`, joins to `llm_usage` on `request_id`.
- backend/services/quiz_identity.py — `question_hash`: the stable cross-attempt identity of one quiz item (E5). Paired with `services/quiz_repetition.py`, the recently-asked read behind the repetition guard (E6).
- backend/routes/admin_analytics.py — admin-only `/api/admin/analytics` usage/cost rollups over the `events`/`llm_usage` tables (#375); writes go through `services/events_service.py` + `agents/usage.py::record_agent_usage`.
- backend/services/extraction_service.py:1 — OCR engine router (Docling / GOT-OCR / Tesseract).
- backend/services/auth_guard.py:68 — `require_self` / `require_admin` FastAPI dependencies.
- backend/agents/note_summary.py, note_concepts.py, note_chat.py — Pydantic AI agents backing the `/api/notes` agent actions (model slots in `agents/_providers.py`).
- backend/db/connection.py:102 — `table()` factory; the only sanctioned Supabase entry point (PostgREST, no DDL).
- backend/db/migrate.py — raw-DDL migration runner (psycopg over `SUPABASE_DB_URL`); migrations are append-only `db/migrations/*.sql`, named with a UTC timestamp prefix (`YYYYMMDDHHMMSS_description.sql`). See `db/migrations/README.md`.

## Commands

Backend (run from `backend/`, with `.env` populated from `.env.example`):

```
python main.py                  # uvicorn on PORT (see config.py), reload=True
python -m pytest tests/ -q      # backend test suite
```

Database (run from `backend/`; migrations are raw DDL, never dashboard SQL):

```
python -m db.migrate              # apply pending migrations (SUPABASE_DB_URL = SESSION-mode pooler URI, port 5432)
python -m db.migrate --baseline   # record migrations as applied without running them
python -m db.seed_staging         # idempotent fake demo dataset on the new schema
```

The `db/` scripts read `.env` by default; for staging/prod ops run them under
`dotenv -f .env.staging run -- python -m db.<script>` so they hit the right project.
Migrations are immutable once applied — add a new timestamp-prefixed file
(`date -u +%Y%m%d%H%M%S`), never edit an old one. `SUPABASE_DB_URL` must be the
SESSION-mode pooler URI (port 5432, user `postgres.<ref>`); the direct
`db.<ref>.supabase.co` host is IPv6-only and unreachable from most networks, and
port 6543 is transaction mode and breaks DDL. `scripts/pooler_url.py` builds it.

Promotion (repo root; full runbook backend/promotion/README.md):

```
make promote                          # staging -> prod: preflight, migrate, confirm, merge, verify
make promote ARGS="--verify-only"     # re-check the live deploy only (wait + smoke)
make promote ARGS="--yes"             # skip the confirmation prompt (CI)
```

Docker (full stack from repo root):

```
docker-compose up
```

Lint (run from `backend/`):

```
ruff check .                    # lint, gated in CI against the ruff.toml baseline (#193)
ruff format .                   # formatter — available, not yet CI-gated (see ruff.toml)
```

E2E (repo root; full guide `docs/e2e-exploration.md`, stack guide `docs/local-supabase.md`):

```
make e2e-up                        # deterministic local stack: Supabase PG15 from config.toml + backend + frontend, function-mode LLM seam, rich seed
cd frontend && npx playwright test # Chapter 1 journeys (frontend/e2e/*.spec.ts) — needs the stack up
cd backend && venv/bin/python -m e2e_oracles   # deterministic judges (graph|counts|ciphertext|logscan|orphans); exit 0 clean / 1 findings / 2 infra
make e2e-down                      # ALWAYS tear down, even after failures
make explore                       # Chapter 2: bounded AI exploration of the running app (interactive: /explore); local-only, never CI
```

## Conventions

- All Supabase access goes through `db/connection.py::table()`. Do not instantiate `httpx` clients or import `supabase` directly elsewhere. The one sanctioned exception is `db/migrate.py`, which connects with psycopg to run DDL.
- Schema changes are append-only migrations in `backend/db/migrations/` (applied via `python -m db.migrate`); never edit an applied migration or run DDL in the Supabase dashboard. **New migrations use a UTC timestamp prefix** — `date -u +%Y%m%d%H%M%S` — because sequential `NNNN_` numbers are claimed at write time and only validated at merge, so concurrent branches collide. The 48 existing `NNNN_` files are frozen and must never be renamed: the ledger keys on basename, so a rename re-runs the migration. The count is 48 rather than 45 because three migrations applied out-of-band to staging had to be recovered under the exact basenames the live ledger recorded — the only reconciliation that clears an orphan without hand-editing a production ledger. That is the sole reason a new `NNNN_` file is ever sanctioned; anything genuinely new uses a timestamp. Full rationale in `backend/db/migrations/README.md`.
- Term/offering/enrollment resolution goes through `services/academics.py`. The HTTP boundary keeps the abstract `course_id`; the graph stays on the abstract course, gradebook keys on `enrollment_id`, and study/analytics key on `offering_id`.
- Display names are resolved via `services/profiles.py` (`get_display_name`/`get_display_names`), which decrypts off `user_profiles` — don't read name columns off `users`.
- All LLM calls are Pydantic AI agents in `backend/agents/` (model slots in `agents/_providers.py`); there is no other sanctioned LLM seam (ADR 0024). Exactly two raw `google.genai.Client` sites remain: `services/rag_service.py`'s embedding client (request-path, `model_mode()`-gated per #439) and `scripts/_raw_gemini.py` (offline benchmark baseline, outside the request path — its docstring forbids importing it from application code).
- Knowledge-graph mutations go through `services/graph_service.py::apply_graph_update` — routes never write `graph_nodes`/`graph_edges` directly.
- **An agent read tool that can return zero rows routes that result through `services/tool_signals.py::report_empty_result`.** Three personalization inputs were silently empty for months (#529's swallowed 42P10, the misconceptions `offering_id`/course-id keyspace mismatch, the digest key drift) because an empty list is indistinguishable from "this student has nothing yet". The helper supplies the missing half — whether the student *plausibly should* have data — and emits `quiz.tool_empty` when the two disagree. It is feature-agnostic (`feature=` names the caller), so tutor tools use it too.
- `functools.lru_cache` is reserved for **deterministic, per-process reads** (#98) — either immutable mappings that never need invalidation (e.g. `academics.offering_course_id`) or reads with a matching `clear_*_cache()` hook that every mutator calls (e.g. `course_context_service.get_course_context` is cleared by `update_course_context`). Cache only hashable-arg functions; return a deep copy if the cached value is mutable; never cache without a clear invalidation story. The autouse `_clear_lru_caches` fixture in `tests/conftest.py` resets these between tests.
- Backend tests live in `backend/tests/` and run via `pytest`; shared fixtures (mock Supabase, mock Gemini) are in `tests/conftest.py`.
- Routers are mounted in `main.py` with `/api/<name>` prefixes; new routes follow that pattern.
- **Verify substantive changes against the E2E lanes before merge**: hermetic suite + the Chapter 1 Playwright lane + the oracles (all three where applicable — `e2e.yml` re-runs the lane on every push to main, but pre-merge is the gate that can still say no). A bug fix in E2E-covered territory pairs with a promoted regression journey in `frontend/e2e/` (triage/promotion recipe: `docs/e2e-exploration.md` §7–§8; journey style: fixtures-based `test` from `support/fixtures.ts`, DB asserts via `support/db.ts`, testids per `docs/frontend-testids.md` "Adding a surface").
- **The local E2E stack is a machine singleton.** Serialize ALL stack use (yours and every subagent's) via `flock` on `/tmp/claude-<uid>/sapling-e2e-stack.lock`, wrapping each whole up→test→down cycle in ONE flock invocation — never separate flock calls for up and down (detached servers inherit the lock fd; a separately-flocked teardown deadlocks). `make explore` manages its own lock.
- **Function-mode seam**: the E2E lanes run `SAPLING_MODEL_MODE=function` with fixed handler constants from `agents/function_handlers_e2e.py` (the seam serves STREAMED runs too since #349 — the SSE tutor replays the same constants) — every upload "summarizing" gradient descent is the seam working as designed, not a data bug (the tell: byte-match to an `E2E_*` constant). New request-path agent tasks need a handler registered there (unregistered tasks raise `UnregisteredHandlerError`); post-response BackgroundTask handlers stay deliberately unregistered. Keep handler constants ↔ spec assertions ↔ `tests/test_e2e_function_handlers.py` in sync. Code below the `agents/_providers.py` seam must never construct a raw `google.genai.Client` without a `model_mode()` gate (#439).

## Pointers

- For architectural decisions, see `docs/decisions/` (read the latest 3).
- For things that didn't work, see `docs/attempts/`.
- For the current architecture overview, see `docs/architecture.md`.
- For agent-building patterns, run `/sync-context` at session start.
- For E2E testing (Chapter 1 scripted journeys + Chapter 2 AI exploration, oracles, triage, promotion), see `docs/e2e-exploration.md`.

## Gotchas

- Column-level encryption is on for sensitive columns: `user_profiles.name`/`first_name`/`last_name`/`bio`/`location` (these moved off `users` to `user_profiles` in the 0024 identity split), Google OAuth tokens, `messages.content`, `room_messages.text`, `sessions.summary_json`, `documents.summary` + `concept_notes` + `extracted_text` (the RAG OCR text added in 0030), `notes.title`/`body`/`last_summary`, `assignments.notes`/`points_possible`/`points_earned` (the enrollment-keyed gradebook table; points columns carry numeric semantics — use `decrypt_numeric` at read), `feedback.comment`/`topic` + `issue_reports.topic`/`description` (free-text user input, #520), `quiz_attempts.questions_json`/`answers_json` + `quiz_context.context_json` (quiz performance data, #521; scalar analytics columns — score/total/difficulty/completed_at — stay plaintext), and `flashcards.front`/`back` + `study_guides.content` + `room_summaries.summary` (derived content, #518; `study_guides.content` uses the JSON pair, `room_summaries.summary` keys its cache on the separate plaintext `member_hash` column so encryption doesn't affect cache-hit lookups). Helpers live in `backend/services/encryption.py`; use `encrypt_if_present` at write boundaries and `decrypt_if_present` / `decrypt_numeric` at read boundaries (including before injecting into AI prompts). `ENCRYPTION_KEY` must be set (32 bytes as 64 hex chars; generate via `python -c "import secrets; print(secrets.token_hex(32))"`). Deliberate exception: `newsletter_emails.email` stays plaintext (ADR 0026) — the UNIQUE constraint, lookup index, and both subscribe/allowlist upserts key on the value, and AES-GCM's per-call nonce breaks value equality.
- Knowledge-graph mastery is now an append-only `node_mastery_events` table (replaced the `graph_nodes.mastery_events` JSON column in 0023); node/edge dedup is enforced by UNIQUE constraints. Don't read/write a `mastery_events` column.
- Optional cross-worker cache (#97): `services/cache.py` wraps Redis and is **off by default** — with no `REDIS_URL` set it's a zero-overhead no-op and never fails a request (any Redis error → clean miss + warning). Currently backs the content-addressed OCR/extraction cache (`extraction_service.extract_text_from_file`, keyed on `sha256(file_bytes)` + engine). The `redis` dependency is only imported when `REDIS_URL` is set.
- HTTP caching (#99): conditional GETs use `services/http_cache.py` (`make_etag`/`conditional`/`cached_json`). `Cache-Control` on these routes is **always `private`, never `public`** — the responses carry user-scoped, app-decrypted columns that must never be cached at a shared proxy/CDN. Derive the ETag from cheap change-keys (ids, `updated_at`, existing content hashes), not from the fully-built payload.