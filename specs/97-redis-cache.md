# Spec: Redis cache wrapper + OCR content-cache (#97, scoped)

## Scope decision

#97 as filed targets caching `gemini_service.call_gemini*`. The agent migration
(#144–#147) moved those calls onto Pydantic AI agents that bypass `call_gemini`,
so that surface is largely obsolete. This lands the **durable, migration-proof**
part: the `services/cache.py` Redis wrapper + the **OCR/extraction content-cache**.
The Gemini-response cache is deliberately out of scope (documented in the issue).

## Requirements

### R1 — Redis wrapper (`services/cache.py`)
- Off by default: no `REDIS_URL` → every call is a zero-overhead no-op, app behaves
  identically. `enabled()` is False.
- Never fails a request: any redis error (missing dep, unreachable, bad URL) disables
  the cache for the process, logs a warning, and returns a clean miss.
- Lazy `redis` import (optional dependency), memoized client, `reset()` for tests.
- API: `enabled()`, `get_str(key)`, `set_str(key, value, ttl_seconds)`. Mockable like
  `db/connection.py`.

### R2 — OCR content-cache
- `extraction_service.extract_text_from_file` checks the cache first; on a hit it
  returns without running OCR; on a miss it extracts, stores, and returns. Keyed on
  `ocr:{sha256(file_bytes)}:{engine}:{got_ocr_enabled}` (content + engine addressed),
  TTL 30 days. When `cache.enabled()` is False it skips the key computation entirely
  (no hashing cost) and calls the unchanged extraction path.
- Extraction behavior/output is byte-identical to before when the cache is off.

### R3 — Dependency + config
- `redis>=5.0` added to `requirements.txt` (only imported at runtime when `REDIS_URL`
  is set). `REDIS_URL` documented in `.env.example` and CLAUDE.md Gotchas.

### R4 — Tests
- Wrapper: no-`REDIS_URL` no-op; round-trips str↔bytes via a fake client; a backend
  error yields a clean miss (never raises).
- OCR cache: disabled → extracts (no cache); hit → skips extraction; miss → extracts
  then stores under an `ocr:` key; different bytes → different key.

## Acceptance
1. `services/cache.py` exists (off-by-default, graceful-degrade, mockable).
2. OCR extraction is cached content-addressed; identical behavior when Redis is off.
3. `redis` optional dep declared; `REDIS_URL` documented.
4. Tests cover no-op, fake-redis round-trip, error-swallow, and the three OCR paths.
5. `pytest tests/ -q` shows no new failures vs `main`; `ruff` clean.

## Out of scope (documented)
- Gemini-response caching — obsolete post agent-migration (agents don't use
  `call_gemini`); the wrapper is the seam if that need returns.
- Actually provisioning Redis (ops); this lands dormant until `REDIS_URL` is set.
