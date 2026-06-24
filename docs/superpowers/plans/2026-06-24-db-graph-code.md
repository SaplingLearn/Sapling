# db/graph-code — knowledge-graph integrity

Slice of the DB modular redesign. Rewire `services/graph_service.py` graph-node/edge
writes onto the integrity guarantees added by migration `0023_graph_integrity.sql`:
UNIQUE-backed upserts (no more select-then-insert), append-only mastery events
(no more non-atomic JSON read-modify-write), and the new CHECK enum sets.

Base branch: `db/academics-code` (has `services/academics.py` resolver + migrations 0019–0027).

## Exact schema facts from 0023_graph_integrity.sql

`graph_nodes` (DROP/CREATE — no user data to preserve):
- PK `id TEXT` (gen_random_uuid()::text default; we keep hand-building ids via `uuid.uuid4()`).
- `user_id TEXT NOT NULL` → `users(id)` ON DELETE CASCADE.
- `course_id TEXT` → `courses(id)` ON DELETE SET NULL (nullable; ABSTRACT course, the graph key — UNCHANGED).
- `concept_name TEXT NOT NULL`, `subject`, `mastery_score DOUBLE PRECISION DEFAULT 0.0`.
- `mastery_tier TEXT DEFAULT 'unexplored'` **CHECK IN ('unexplored','struggling','learning','mastered','subject_root')**.
- `times_studied INTEGER DEFAULT 0`, `last_studied_at`, `color`, `created_at`, `updated_at`.
- **UNIQUE NULLS NOT DISTINCT (user_id, course_id, concept_name)** — backs dedup; retires `db/dedup_nodes.py`.
- Indexes: `idx_graph_nodes_user(user_id)`, `idx_graph_nodes_course(course_id)`.
- `updated_at` maintained by trigger `trg_graph_nodes_updated_at`.
- **`mastery_events` JSONB column is GONE.** Line 27 of 0023 states it is replaced by `node_mastery_events`. Confirmed: it does NOT appear in the new `graph_nodes` DDL.

`node_mastery_events` (NEW, append-only — fixes the non-atomic RMW, #247):
- PK `id TEXT`.
- `node_id TEXT NOT NULL` → `graph_nodes(id)` ON DELETE CASCADE.
- `delta DOUBLE PRECISION NOT NULL`.
- `reason TEXT` (nullable).
- `created_at TIMESTAMPTZ DEFAULT now()`.
- Index: `idx_node_mastery_events_node(node_id, created_at)`.
- NOTE: schema has NO `event_type` column — only `delta`, `reason`, `created_at`. The old JSON
  blob carried `ts`/`delta`/`reason`/`event_type`; the new table drops `event_type`. We map
  the old per-event `ts` → `created_at` and let DB default it (we still pass an explicit
  `created_at` for deterministic velocity math + so tests can assert).

`graph_edges` (DROP/CREATE):
- PK `id TEXT`.
- `user_id TEXT NOT NULL` → `users(id)` ON DELETE CASCADE (FK ADDED, #179).
- `source_node_id`, `target_node_id` TEXT NOT NULL → `graph_nodes(id)` ON DELETE CASCADE.
- `relationship_type TEXT DEFAULT 'related'` **CHECK IN ('related','prerequisite','builds_on','part_of')**.
- `strength DOUBLE PRECISION DEFAULT 0.5`, `created_at`.
- **UNIQUE (user_id, source_node_id, target_node_id, relationship_type)** — backs dedup (#195).
- Indexes: `idx_graph_edges_user(user_id)`, `idx_graph_edges_source(source_node_id)`,
  `idx_graph_edges_target(target_node_id)`.

## Did 0023 drop graph_nodes.mastery_events? YES.

The JSONB column is dropped and replaced by the append-only `node_mastery_events` table.
So `graph_service.py` must stop reading/writing `graph_nodes.mastery_events` as a column and
instead:
- On a mastery change (apply_graph_update updated_nodes): UPDATE only the scalar columns
  (`mastery_score`, `mastery_tier`, `times_studied`, `last_studied_at`) and INSERT one row
  into `node_mastery_events` (append-only). No JSON blob rewrite.
- In `get_graph`: compute `learning_velocity` and the trimmed event history by reading
  `node_mastery_events` for the user's nodes (one batched select), not from a node column.

## File-by-file change map

### services/graph_service.py (ONLY the graph-integrity parts)

1. `_compute_velocity(events)` — adapt to the new event row shape. Old events keyed on
   `e["ts"]`; new rows key on `e["created_at"]`. Make the timestamp lookup tolerant of both
   (`created_at` first, then `ts`) so it works for DB rows and any legacy callers. Keep the
   14-day window + positive-gain-per-day formula unchanged.

2. `get_graph` (mastery_events / velocity block, ~L154-157):
   - Replace `n.get("mastery_events")` (column) with a batched read from `node_mastery_events`:
     select `node_id,delta,reason,created_at` filtered to this user's node ids
     (`node_id=in.(...)`, `order=created_at.asc`), then group by `node_id` in Python.
   - For each real node: `learning_velocity = _compute_velocity(events_for_node)`;
     `mastery_events = events_for_node[-5:]` (preserve the existing API field — last 5 for UI).
   - Guard against empty node set (no `in.()` call) and wrap the read in try/except → `{}` so a
     missing/empty events table never breaks the graph response. Subject-root synthesized nodes
     keep getting no events (unchanged; they're built later and never carried events).
   - Everything else in get_graph (enrollment reshape, subject roots, stats, colors) is
     academics-owned / untouched.

3. `apply_graph_update`:
   - Bulk-fetch select: drop `mastery_events` from the column list
     (`id,concept_name,mastery_score,times_studied,course_id`).
   - **New nodes:** replace `table("graph_nodes").insert({... "mastery_events": []})` with
     `table("graph_nodes").upsert({... no mastery_events ...}, on_conflict="user_id,course_id,concept_name")`.
     Use the upsert's returned representation to capture the canonical `id` (fallback to the id
     we generated if the mock/representation is empty). Drop the `"mastery_events": []` key from
     both the insert payload and the in-batch tracking dict.
   - **Updated nodes:** stop building/trimming `updated_events`; UPDATE only
     `mastery_score`, `mastery_tier`, `times_studied`, `last_studied_at`. THEN append one row to
     `node_mastery_events`: `{id, node_id, delta, reason, created_at}` (no `event_type` — not in
     schema; `reason` carries `upd.get("reason","")`). Append-only ⇒ no read of prior events.
   - **New edges:** replace the select-then-insert with
     `table("graph_edges").upsert({user_id, source_node_id, target_node_id, relationship_type, strength},
     on_conflict="user_id,source_node_id,target_node_id,relationship_type")`. Keep the existing
     guards (skip blank names, skip self-edges, clamp strength). Drop the duplicate-edge SELECT.
   - `relationship_type` is taken from the LLM payload (default `'related'`); values outside the
     CHECK set would be rejected by the DB — we pass through what the agent emits (the agent
     contract already uses the enum). `get_mastery_tier` already returns only the 4 non-root
     CHECK tiers, so node writes satisfy the mastery_tier CHECK.
   - The `touched_courses` → `update_course_context` side-effect block is UNCHANGED (academics-owned).

4. Delete `db/dedup_nodes.py` — its (user_id, concept_name) dedup is superseded by the UNIQUE
   constraint (0023 comment explicitly retires it, #181).

### CRITICAL — DO NOT TOUCH (academics-owned, already rewired)
`_reshape_enrollment`, `_user_enrolled_courses`, `get_courses`, `add_course`,
`update_course_color`, `update_course_nickname`, `delete_course`, and every
offering-resolution / `update_course_context` call site. Graph stays keyed on the ABSTRACT
`course_id`. `get_recommendations`, `update_node_color`, `delete_node` node/edge deletes,
`ensure_user_exists`, `update_streak` are left as-is (delete_node already deletes edges by
source/target then the node — correct under the new FKs).

## Tests (tests/test_graph_service.py)

Update existing apply_graph_update tests + add coverage:
- Existing-node fixtures: drop the now-irrelevant `"mastery_events": []` key (harmless to keep,
  but tidy). Bulk-fetch no longer selects that column.
- `test_inserts_new_node`: assert `graph_nodes.upsert` (not `.insert`) called with
  `on_conflict="user_id,course_id,concept_name"`; payload has no `mastery_events`. (Node-id
  capture falls back to the generated uuid when the mock returns `[]`.)
- `test_skips_insert_for_existing_node_case_insensitive` / `test_dedups_within_a_single_batch`
  / `test_skips_blank_concept_names`: assert on `.upsert` instead of `.insert`.
- `test_updates_mastery_score` / case-insensitive update / clamp tests: still assert the
  returned mastery_changes; ADD that the update payload no longer contains `mastery_events`,
  and that `node_mastery_events.insert` was called once with the delta + reason.
- NEW `test_mastery_change_appends_event_row`: a single updated_node appends exactly one
  `node_mastery_events` row carrying the correct `delta` and `reason`, and the node UPDATE
  carries no `mastery_events` key (proves append-only, fixes RMW).
- NEW `test_edge_upsert_uses_unique_conflict`: a new edge calls `graph_edges.upsert` with
  `on_conflict="user_id,source_node_id,target_node_id,relationship_type"`; no select-then-insert.
- `test_does_not_add_duplicate_edge`: re-aimed — with UNIQUE-backed upsert we no longer pre-check;
  rewrite to assert the upsert is called (DB dedups). Keep `test_skips_self_edges` (still skipped
  pre-DB).
- get_graph velocity: add a fixture where `node_mastery_events` returns event rows for a node and
  assert `learning_velocity > 0` and `mastery_events` is the trimmed (≤5) tail. Existing
  empty-graph / tier-count / subject-root tests keep passing (events table mock returns []).

`tests/test_shared_course_context.py`: its 3 apply_graph_update tests assert only on
`update_course_context` resolution; they pass `mastery_events: []` in node rows but never assert
on event handling. The `node_mastery_events` table is a fresh MagicMock there (insert is a no-op),
so they keep passing. Touch ONLY if an assertion breaks (expected: none).

## Out of scope
- `routes/quiz.py` L392-433 ALSO reads/writes `graph_nodes.mastery_events` as a column and will
  break against the real post-0023 DB. Quiz is a different slice's file — DO NOT edit it here.
  Flagged for the quiz/analytics slice. (Its unit tests mock the table, so they stay green.)
- `services/academics.py`, `services/course_context_service.py`, `routes/graph_read.py` —
  academics/analytics owned.
- Enrollment / course / offering logic; analytics tables.

## Gate
`PY -m pytest tests/ -q` → no new failures beyond the 2 pre-existing env-only
`tests/test_storage_service.py` failures. `RUFF check .` clean. Commit incl. this plan; push
`db/graph-code`; no PR.
