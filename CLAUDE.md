# Sapling

A FastAPI + Supabase backend that ingests student documents, calls Gemini to classify/summarize/extract assignments, and serves a knowledge-graph-backed tutoring chat to a React frontend.

## Stack

- FastAPI: HTTP layer; app + router mounts in `backend/main.py`.
- Supabase (PostgREST): primary datastore; accessed via `httpx` REST through `db/connection.py`.
- Gemini (`google-genai`): current LLM provider; wrapped in `services/gemini_service.py` (being deprecated).
- Pydantic AI: target agent framework; not yet in `requirements.txt`, agents will live under `backend/agents/`.
- React frontend: lives in `frontend/` (out of scope for backend sessions).
- pytest: backend test runner, fixtures in `tests/conftest.py`.

## Repo map

- backend/main.py:24 — FastAPI app, CORS, and every router mount.
- backend/routes/documents.py:149 — `_process_document` single-call classify/summarize/extract (refactor target #1).
- backend/routes/documents.py:265 — `upload_document` POST `/api/documents/upload` pipeline.
- backend/routes/learn.py:152 — `build_system_prompt` for the streaming tutor (SSE).
- backend/routes/quiz.py:1 — quiz session create/answer/score endpoints.
- backend/routes/auth.py:1 — Google OAuth + HMAC session token issuance.
- backend/services/gemini_service.py:62 — `call_gemini` plain-text call (LLM seam being deprecated).
- backend/services/gemini_service.py:129 — `call_gemini_json` JSON-mode helper used by document/quiz prompts.
- backend/services/graph_service.py:375 — `apply_graph_update` (becomes a Pydantic AI tool).
- backend/services/extraction_service.py:1 — OCR engine router (Docling / GOT-OCR / Tesseract).
- backend/services/auth_guard.py:1 — `require_self` / `require_admin` FastAPI dependencies.
- backend/db/connection.py:71 — `table()` factory; the only sanctioned Supabase entry point.

## Commands

Backend (run from `backend/`, with `.env` populated from `.env.example`):

```
python main.py                  # uvicorn on PORT (see config.py), reload=True
python -m pytest tests/ -q      # backend test suite
```

Docker (full stack from repo root):

```
docker-compose up
```

Lint: # TODO: no lint command defined (no ruff/flake8/black config in repo).

## Conventions

- All Supabase access goes through `db/connection.py::table()`. Do not instantiate `httpx` clients or import `supabase` directly elsewhere.
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

- (none recorded yet — add as discovered)
