# Plan — `db/seed_staging.py` (DB modular redesign, #258)

A self-contained, idempotent seed that lays a small **fake** demo dataset on top
of the **new** (post-0019–0027) schema so the live staging app renders the graph,
gradebook, and courses-with-term against a real DB.

It is **staging-only** (fake data), never prod. It only ever talks to whatever
`db/connection.py::table()` is configured for via env — no hardcoded URLs/keys.

## Preconditions (already true on staging)

- Migrations **0019–0027 applied**. The 4 canonical `terms`
  (`fall-2025` / `spring-2026` / `summer-2026` / `fall-2026`) are seeded by 0019.
- The real ~8192-row course catalog already exists. **The seed does not touch,
  duplicate, or depend on it** — all demo rows are namespaced under a demo school
  with deterministic `seed-…` ids.

## Entities seeded + counts

| Table | Count | Notes |
|---|---|---|
| `schools` | 1 | `seed-school-demo` (demo namespace; upsert on `slug`) |
| `courses` (abstract) | 3 | CS101, MATH210, BIO110 under the demo school |
| `terms` | 0 (reused) | query existing `fall-2025` + `spring-2026` by id; never inserted |
| `course_offerings` | 4 | CS101 offered in **2 terms** (fall-2025 + spring-2026); MATH210 + BIO110 once each |
| `users` (slim) | 1 | `seed-user-demo` (id/email/onboarding/streak/is_approved) |
| `user_profiles` | 1 | 🔒 name/first_name/last_name |
| `enrollments` | 4 | demo user → all 4 offerings (incl. **CS101 in both terms**); `curve_mode`, `drop_lowest` via category |
| `graph_nodes` | 9 | per **abstract** `course_id` (3 per course); valid `mastery_tier` |
| `graph_edges` | 4 | within-course `prerequisite` / `builds_on` / `related` |
| `node_mastery_events` | 6 | append-only (0023): a couple per "studied" node |
| `gradebook_categories` | 4 | one per enrollment; one with `drop_lowest=1` |
| `assignments` | 6 | on enrollment+category; 🔒 points; valid `source`/`assignment_type` |
| `documents` | 1 | on the CS101 fall-2025 offering; 🔒 `summary`/`concept_notes`; valid `category` |
| `notes` | 1 | on the same offering; 🔒 `title`/`body` |

All ids deterministic, prefixed `seed-`. All FKs point at other `seed-` rows or
the pre-seeded canonical `terms`.

## Idempotency strategy

Safe to run repeatedly; a re-run inserts nothing new and never errors.

- **Deterministic ids** everywhere (`seed-school-demo`, `seed-course-cs101`,
  `seed-off-cs101-fall2025`, `seed-user-demo`, `seed-node-cs101-variables`, …).
- Two mechanics, both check-then-act:
  - `_upsert(table, rows, on_conflict=…)` for tables with a natural UNIQUE
    (`schools.slug`, `courses(school_id,course_code)`, `users.id`,
    `user_profiles.user_id`, `graph_nodes(user_id,course_id,concept_name)`,
    `graph_edges(user_id,source,target,rel_type)`,
    `course_offerings(course_id,term_id,section)`). Re-runs merge-duplicate → no dupes.
  - `_insert_if_absent(table, id, row)` for tables with no natural key
    (`enrollments`, `gradebook_categories`, `assignments`, `documents`, `notes`,
    `node_mastery_events`): `select id` by deterministic id first; insert only if
    missing. (`node_mastery_events` is append-only with no UNIQUE, so the explicit
    presence check is what keeps it from growing on every run.)
- `terms` are only **read** (by id), never written → cannot collide with 0019.
- A per-table counter distinguishes `created` vs `skipped (exists)` and is printed
  in the summary, so a 2nd run visibly shows all-skips.

## Encryption boundary (🔒)

Every encrypted column is passed through `services.encryption.encrypt_if_present`
at the write boundary (the helper is a no-op on `None`). Columns covered:

- `user_profiles.name` / `first_name` / `last_name`
- `notes.title` / `body` / `last_summary`
- `documents.summary` / `concept_notes`
- `assignments.points_possible` / `points_earned` / `notes`

`users.email` is also encrypted (staging encrypts it). The script calls the helper
only; when run with staging env the helper uses staging's `ENCRYPTION_KEY`. Upserts
re-encrypt with a fresh nonce each run — the row content is unchanged and the unique
key (id / natural key) is plaintext, so idempotency holds regardless of nonce churn.

## Enum values (read off migrations — no guesses)

- `enrollments.curve_mode` ∈ {`raw`,`curved`} (0021) — demo uses `raw` and one `curved`.
- `graph_nodes.mastery_tier` ∈ {`unexplored`,`struggling`,`learning`,`mastered`,`subject_root`} (0023);
  derived from score via `config.get_mastery_tier` so tier ↔ score stay consistent.
- `graph_edges.relationship_type` ∈ {`related`,`prerequisite`,`builds_on`,`part_of`} (0023).
- `assignments.source` ∈ {`manual`,`syllabus`}; `assignment_type` ∈
  {`homework`,`exam`,`reading`,`project`,`quiz`,`other`} (0021).
- `documents.category` ∈ {`syllabus`,`lecture_notes`,`slides`,`reading`,`assignment`,`study_guide`,`other`} (0025).
- `sessions.mode` ∈ {`socratic`,`expository`,`teachback`} (0025) — not seeded but documented for completeness.
- `terms.term` ∈ {`Fall`,`Spring`,`Summer`,`Winter`} (0019) — reused, not written.

## How multi-term is exercised

- The **same abstract course** `seed-course-cs101` gets **two offerings**:
  `seed-off-cs101-fall2025` (term `fall-2025`) and `seed-off-cs101-spring2026`
  (term `spring-2026`).
- The demo user is **enrolled in both**. Because the knowledge graph is keyed on
  the **abstract** `course_id` (not the offering), the CS101 graph nodes/mastery
  accumulate **across both terms** — exactly the cumulative-across-terms behaviour
  the redesign targets. Gradebook/analytics stay offering-scoped (separate
  enrollments, categories, assignments per term), demonstrating both halves of the
  bridge in `services/academics.py`.

## Run command (against staging)

From `backend/`, with staging env loaded (`SUPABASE_URL`, `SUPABASE_SERVICE_KEY`,
`ENCRYPTION_KEY` from `backend/.env.staging`):

```
python -m db.seed_staging
```

Prints a per-table created/skipped summary at the end. Re-running is a no-op.

## Tests (`tests/test_seed_staging.py`, hermetic — no real DB)

`db.seed_staging.table` is patched to a recording mock (FakeTable) backed by an
in-memory store keyed per table. Assertions:

1. `main()` inserts/upserts into every expected table.
2. FK consistency: every `course_offerings.course_id` exists in `courses`; every
   `enrollments.offering_id` exists in `course_offerings`; `enrollments.user_id`
   exists in `users`; `user_profiles.user_id` exists in `users`;
   `graph_edges` source/target ids exist in `graph_nodes`; `node_mastery_events.node_id`
   exists in `graph_nodes`; gradebook/assignments/notes/documents FKs resolve.
3. Enum validity: collected `mastery_tier` / `relationship_type` / `assignment_type` /
   `source` / `category` / `curve_mode` values are all within the migration CHECK sets.
4. Multi-term: ≥2 distinct `term_id` across CS101 offerings; demo user enrolled in both.
5. Encryption: `user_profiles.name`, `notes.title`, `documents.summary`,
   `assignments.points_possible` are ciphertext that `decrypt()`s back to the plaintext.
6. Idempotency: a 2nd `main()` over the same store adds **no** new rows.

Gate: zero NEW failures vs the 2 pre-existing env-only `test_storage_service.py`
failures; the new test file passes; `ruff check .` clean.
