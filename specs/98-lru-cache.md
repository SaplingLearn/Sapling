# Spec: functools.lru_cache for hot deterministic reads (#98)

## Scope

Milestone #2 (perf). Per-process (per-worker) caching of hot, deterministic reads with a clear
invalidation story. Composes with the HTTP cache (#99) and a future cross-worker Redis layer (#97).

## Requirements

### R1 — Cache immutable academics resolvers (no invalidation needed)
- `services/academics.offering_course_id(offering_id)` — `@lru_cache`. An offering's `course_id` is set
  at creation and never changes → deterministic immutable mapping; returns an immutable `str`/`None`.
- `services/academics.term_for_offering(offering_id)` — `@lru_cache` on the private body; the public
  function returns a `copy.deepcopy` (mutable dict) so callers can't corrupt the cache. Offering→term is
  immutable and terms are seeded reference data.
- `services/academics.clear_academics_caches()` clears both (for tests).

### R2 — Cache course-context with an invalidation hook
- `services/course_context_service.get_course_context(offering_id)` — `@lru_cache` on the private body;
  the public function returns a `copy.deepcopy`.
- `clear_course_context_cache()` is called from `update_course_context` on **every** write path (the
  no-enrollment purge and the final upsert). `update_course_context` is the choke point that
  `apply_graph_update` and the doc/grade post-rolls funnel through, so a graph/doc/grade change that
  moves the aggregates always drops the stale cached read.

### R3 — Test isolation
- An autouse `_clear_lru_caches` fixture in `tests/conftest.py` clears all these caches around every test
  so one test's mocked DB state can't leak into another via a cached read.

### R4 — Docs
- CLAUDE.md Conventions: `lru_cache` is reserved for deterministic per-process reads — immutable mappings
  (no invalidation) or reads with a matching `clear_*_cache()` every mutator calls; hashable args only;
  deep-copy mutable returns.

## Acceptance
1. 3+ functions cached, each provably safe (immutable, or hooked + deep-copied).
2. `clear_course_context_cache()` invoked from `update_course_context`'s write paths.
3. CLAUDE.md documents the convention.
4. Tests: cache hit avoids a 2nd DB read; distinct keys not conflated; deep-copy immunity; mutate via
   `update_course_context` → next read returns fresh.
5. `pytest tests/ -q` shows no new failures vs `main` (proves the conftest fixture stops cache leakage);
   `ruff` clean.

## Deliberately NOT cached (documented risk)
- Graph reads (`get_graph`) — large mutable structures with hot, per-turn invalidation; deep-copy cost +
  invalidation surface outweigh the win here. Revisit with the Redis layer (#97).
- Token decode / `require_self` — security-sensitive and needs a TTL bounded to token lifetime; out of
  scope for a plain `lru_cache`.
