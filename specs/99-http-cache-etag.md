# Spec: HTTP Cache-Control + ETag for stable GET endpoints (#99)

## Scope (backend core; frontend React Query deferred)

Milestone #2 (caching/perf). This lands the **backend** conditional-GET layer. The issue's frontend
React Query adoption + per-endpoint 304 metrics are deferred to a follow-up (React Query is a repo-wide
frontend dependency the issue itself flags for scope review).

## Requirements

### R1 — Helper
- `services/http_cache.py`: `make_etag(*parts)` (strong ETag from cheap change-keys, `\x1f`-joined),
  `conditional(request, etag) -> Response|None` (304 with ETag+Cache-Control on `If-None-Match` match,
  handling `W/` weak prefix, comma lists, and `*`), `cached_json(payload, etag)` (200 JSONResponse with
  headers). `Cache-Control: private, max-age=30, stale-while-revalidate=60`.

### R2 — Convert ≥3 GET endpoints (private, correct ETag source)
- `GET /api/study-guide/{user_id}/cached` — ETag from each guide's `(id, generated_at)`; 304 skips the
  per-offering course-name enrichment + serialization.
- `GET /api/notes/user/{user_id}` — ETag from each note's `(id, updated_at)`.
- `GET /api/profile/{user_id}/settings` — ETag from `user_settings.updated_at`.
- Every converted route uses `private` (user-scoped, app-decrypted data).

### R3 — Correctness
- The ETag derives from cheap change-keys (ids / `updated_at`), never the full payload, and provably
  invalidates on the real write patterns (regenerate replaces the study_guide row; note create/edit/delete
  bumps the set/`updated_at`; settings patch bumps `updated_at`).
- Response bodies are byte-identical to before (existing route tests unchanged).

### R4 — Docs
- CLAUDE.md Gotchas: HTTP-cache routes are always `private`, never `public` (decrypted user data); derive
  ETag from change-keys not the payload.

## Acceptance
1. `services/http_cache.py` helper exists (ETag + If-None-Match → 304).
2. ≥3 endpoints converted, `private` everywhere.
3. CLAUDE.md gotcha documents the shared-cache prohibition.
4. Tests: helper (etag determinism/change, 304 match/weak/list, mismatch); each endpoint (200+ETag+private,
   304 on match, changed data → new ETag).
5. `pytest tests/ -q` shows no new failures vs `main`; `ruff` clean.

## Deferred (follow-up)
- Frontend: adopt React Query + migrate one screen (Study) as PoC.
- Per-endpoint 304-rate metrics/logs.
- More endpoints (course-context, gradebook) as clean `updated_at` sources are confirmed.
