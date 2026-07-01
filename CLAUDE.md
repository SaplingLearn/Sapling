# Sapling

A FastAPI + Supabase backend that ingests student documents, calls Gemini to classify/summarize/extract assignments, and serves a knowledge-graph-backed tutoring chat to a React frontend.

## Stack

- FastAPI: HTTP layer; app + router mounts in `backend/main.py`.
- Supabase (PostgREST): primary datastore; accessed via `httpx` REST through `db/connection.py`.
- Gemini (`google-genai`): current LLM provider; wrapped in `services/gemini_service.py` (being deprecated).
- Pydantic AI: agent framework (`pydantic-ai-slim[google]` in `requirements.txt`); agents live under `backend/agents/`.
- React frontend: lives in `frontend/` (out of scope for backend sessions).
- pytest: backend test runner, fixtures in `tests/conftest.py`.

## Repo map

- backend/main.py:87 — FastAPI app + CORS; every router mount lives in the block at :150–168.
- backend/routes/documents.py:182 — `_process_document` single-call classify/summarize/extract (refactor target #1).
- backend/routes/documents.py:603 — `upload_document` POST `/api/documents/upload` pipeline.
- backend/routes/learn.py:261 — `build_system_prompt` for the streaming tutor (SSE).
- backend/routes/quiz.py:1 — quiz session create/answer/score endpoints.
- backend/routes/notes.py:32 — `/api/notes` notetaker CRUD, concept link/unlink, and agent actions (`summarize`/`extract-concepts`/`chat`/`send-to-tutor`/`generate-quiz`).
- backend/routes/academics.py — `/api` terms/offerings/enrollments endpoints over the redesigned schema.
- backend/routes/auth.py:1 — Google OAuth + HMAC session token issuance.
- backend/services/academics.py — term/offering/enrollment resolver (`current_term`/`list_terms`/`resolve_offering`/`offering_course_id`/`user_offering_ids_for_course`/`term_for_offering`); the API boundary keeps the abstract `course_id`.
- backend/services/profiles.py — `get_display_name`/`get_display_names`, decrypting the name off `user_profiles`.
- backend/services/gemini_service.py:64 — `call_gemini` plain-text call (LLM seam being deprecated).
- backend/services/gemini_service.py:135 — `call_gemini_json` JSON-mode helper used by document/quiz prompts.
- backend/services/notes_service.py:49 — notes CRUD with column encryption (`create_note`/`update_note`/`save_summary`/`link_concept`).
- backend/services/graph_service.py:461 — `apply_graph_update` (becomes a Pydantic AI tool).
- backend/services/extraction_service.py:1 — OCR engine router (Docling / GOT-OCR / Tesseract).
- backend/services/auth_guard.py:68 — `require_self` / `require_admin` FastAPI dependencies.
- backend/agents/note_summary.py, note_concepts.py, note_chat.py — Pydantic AI agents backing the `/api/notes` agent actions (model slots in `agents/_providers.py`).
- backend/db/connection.py:102 — `table()` factory; the only sanctioned Supabase entry point (PostgREST, no DDL).
- backend/db/migrate.py — raw-DDL migration runner (psycopg over `SUPABASE_DB_URL`); migrations are append-only `db/migrations/*.sql` (now at 0028).

## Commands

Backend (run from `backend/`, with `.env` populated from `.env.example`):

```
python main.py                  # uvicorn on PORT (see config.py), reload=True
python -m pytest tests/ -q      # backend test suite
```

Database (run from `backend/`; migrations are raw DDL, never dashboard SQL):

```
python -m db.migrate              # apply pending migrations (needs SUPABASE_DB_URL = direct conn string)
python -m db.migrate --baseline   # record migrations as applied without running them
python -m db.seed_staging         # idempotent fake demo dataset on the new schema
```

The `db/` scripts read `.env` by default; for staging/prod ops run them under
`dotenv -f .env.staging run -- python -m db.<script>` so they hit the right project.
Migrations are immutable once applied — add a new numbered file, never edit an old one.

Docker (full stack from repo root):

```
docker-compose up
```

Lint (run from `backend/`):

```
ruff check .                    # lint, gated in CI against the ruff.toml baseline (#193)
ruff format .                   # formatter — available, not yet CI-gated (see ruff.toml)
```

## Conventions

- All Supabase access goes through `db/connection.py::table()`. Do not instantiate `httpx` clients or import `supabase` directly elsewhere. The one sanctioned exception is `db/migrate.py`, which connects with psycopg to run DDL.
- Schema changes are append-only numbered migrations in `backend/db/migrations/` (applied via `python -m db.migrate`); never edit an applied migration or run DDL in the Supabase dashboard.
- Term/offering/enrollment resolution goes through `services/academics.py`. The HTTP boundary keeps the abstract `course_id`; the graph stays on the abstract course, gradebook keys on `enrollment_id`, and study/analytics key on `offering_id`.
- Display names are resolved via `services/profiles.py` (`get_display_name`/`get_display_names`), which decrypts off `user_profiles` — don't read name columns off `users`.
- All current LLM calls route through `services/gemini_service.py` (`call_gemini`, `call_gemini_json`, `call_gemini_multiturn`). New LLM-driven code should be written as Pydantic AI agents in `backend/agents/` rather than extending `gemini_service.py`.
- Knowledge-graph mutations go through `services/graph_service.py::apply_graph_update` — routes never write `graph_nodes`/`graph_edges` directly.
- Backend tests live in `backend/tests/` and run via `pytest`; shared fixtures (mock Supabase, mock Gemini) are in `tests/conftest.py`.
- Routers are mounted in `main.py` with `/api/<name>` prefixes; new routes follow that pattern.

## Pointers

- For architectural decisions, see `docs/decisions/` (read the latest 3).
- For things that didn't work, see `docs/attempts/`.
- For the current architecture overview, see `docs/architecture.md`.
- For agent-building patterns, run `/sync-context` at session start.

## Gotchas

- Column-level encryption is on for sensitive columns: `user_profiles.name`/`first_name`/`last_name`/`bio`/`location` (these moved off `users` to `user_profiles` in the 0024 identity split), Google OAuth tokens, `messages.content`, `room_messages.text`, `sessions.summary_json`, `documents.summary` + `concept_notes`, `notes.title`/`body`/`last_summary`, and `assignments.notes`/`points_possible`/`points_earned` (the enrollment-keyed gradebook table; points columns carry numeric semantics — use `decrypt_numeric` at read). Helpers live in `backend/services/encryption.py`; use `encrypt_if_present` at write boundaries and `decrypt_if_present` / `decrypt_numeric` at read boundaries (including before injecting into AI prompts). `ENCRYPTION_KEY` must be set (32 bytes as 64 hex chars; generate via `python -c "import secrets; print(secrets.token_hex(32))"`).
- Knowledge-graph mastery is now an append-only `node_mastery_events` table (replaced the `graph_nodes.mastery_events` JSON column in 0023); node/edge dedup is enforced by UNIQUE constraints. Don't read/write a `mastery_events` column.
- HTTP caching (#99): conditional GETs use `services/http_cache.py` (`make_etag`/`conditional`/`cached_json`). `Cache-Control` on these routes is **always `private`, never `public`** — the responses carry user-scoped, app-decrypted columns that must never be cached at a shared proxy/CDN. Derive the ETag from cheap change-keys (ids, `updated_at`, existing content hashes), not from the fully-built payload.
