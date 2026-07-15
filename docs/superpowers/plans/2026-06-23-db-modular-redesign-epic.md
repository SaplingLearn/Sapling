# DB Modular Redesign — Epic Rollout Plan

> **For agentic workers:** REQUIRED SUB-SKILL: each PR below is implemented as its own
> detailed plan via `superpowers:writing-plans`, then executed with
> `superpowers:subagent-driven-development`. This document is the **epic index** — branch
> strategy, global constraints, and the ordered PR slices. PR 1 is fully detailed as the
> runnable starting point; PRs 2–10 are scoped specs whose granular TDD steps are generated
> when each is picked up (after reading that slice's real code, so no guessed code lands).

**Goal:** Restructure the Postgres/Supabase schema into bounded, well-designed domains
(catalog/offering/term split, FKs everywhere, consistent conventions) and update all code
that touches it, delivered as one reviewable PR per domain accumulating on an epic branch.

**Architecture:** An epic branch (`epic/db-modular-redesign`) cut from `main`. Each
DB-affecting change is a **vertical slice** — migration + the route/service code that uses
those tables + updated tests — landed as its own PR **targeting the epic branch**. The epic
branch may be WIP-red between slices; the **final `epic → main` PR is the green cutover**.
Prod has no user data (only the catalog), so each slice is a hard cutover (no
expand/contract dual-write), and the same migration files promote staging → prod by swapping
`SUPABASE_DB_URL`.

**Tech Stack:** FastAPI · Supabase PostgREST via `db/connection.py::table()` · raw-DDL
migrations via `db/migrate.py` (#252, psycopg over the direct `SUPABASE_DB_URL`) · pytest ·
column encryption via `services/encryption.py`.

**Source spec:** `docs/superpowers/specs/2026-06-23-db-modular-redesign-design.md`

---

## Global Constraints

Copied from the spec; every PR's requirements implicitly include these.

- **All Supabase reads/writes go through `db/connection.py::table()`** — never instantiate
  `httpx` or import `supabase` elsewhere. The **only** exception is `db/migrate.py` (raw DDL
  over the direct connection).
- **Knowledge-graph mutations go through `services/graph_service.py::apply_graph_update`** —
  routes never write `graph_nodes`/`graph_edges` directly.
- **Encryption boundary:** encrypt at write (`encrypt_if_present`), decrypt at read
  (`decrypt_if_present` / `decrypt_numeric`), including before injecting into AI prompts.
  Encrypted columns stay `text` (the 🔒 exception to the typed-columns rule) — gradebook
  `points_possible`/`points_earned`, `messages.content`, `notes.*`, `documents.summary`/
  `concept_notes`, `sessions.summary_json`, `users`/profile name fields, OAuth tokens.
- **Migrations are immutable once applied to a shared DB** — never edit an applied file; add a
  new `NNNN_` file. Continue numbering from `0018`.
- **New LLM code is Pydantic AI agents under `backend/agents/`**, not extensions to
  `gemini_service.py` (relevant where slices touch `graph_read`/`course_context`).

### Resolved open decisions (flip here if you disagree)

| # | Decision | Resolution | Why |
|---|---|---|---|
| 1 | PK type | **Keep `text` ids** (standardized; drop only integer-sequence PKs where no inbound FK) | uuid on `users.id` cascades to every user-FK column → forces a big-bang foundation migration, which breaks the clean per-PR slicing. Revisit as an optional future sweep. |
| 2 | Study-artifact scope | **`offering_id`** | preserves term; UI chooses cumulative vs per-term as a query |
| 3 | `schools` table | **Add now** | lightweight; we're already in academics |
| 4 | Encrypted numerics | **Stay 🔒 `text`** | can't be `numeric` + encrypted; decrypt+cast at read |
| 5 | Enum value sets | **Read off code per slice** before finalizing CHECK lists | no guessed enum members |

---

## Branch & PR mechanics

```bash
# one-time: cut the epic branch from main
git checkout main && git pull
git checkout -b epic/db-modular-redesign
git push -u origin epic/db-modular-redesign

# per slice: branch off the EPIC branch, PR back into it
git checkout epic/db-modular-redesign && git pull
git checkout -b db/2-academics-split      # one per PR below
# ...work...
gh pr create --base epic/db-modular-redesign --head db/2-academics-split --title "..." --body "..."

# final: the big cutover PR
gh pr create --base main --head epic/db-modular-redesign --title "DB modular redesign"
```

Each slice PR's body links its spec section + the issues it closes. Keep slices small enough
that a reviewer can reject one without blocking its neighbors.

---

## PR slices (ordered)

Dependency graph: **PR1** and **PR6** are independent foundations · **PR2** is the spine ·
**PR3/PR4/PR5** depend on PR2 · **PR7** depends on PR2+PR5 · **PR8** independent · **PR9**
depends on the full schema · **PR10** is the cutover. PR3/4/5 can be worked in parallel once
PR2 merges to the epic branch.

Code-surface numbers below are measured `grep` counts in `backend/` (refs, incl. tests).

### PR 1 — Conventions + `terms` + `schools` (additive, non-breaking) — **detailed below**
- **Migration** `0019_conventions_terms_schools.sql`: `set_updated_at()` trigger fn; `terms`;
  `schools` (decision #3); seed `terms` (one per existing distinct `courses.semester` + recent
  & next terms with real dates/sort_key).
- **Code:** none breaks (purely additive). Optional: `GET /api/semesters` can wait for PR2.
- **Closes / advances:** #137 (terms entity), part of #142.
- **Acceptance:** runner applies cleanly; `SELECT … WHERE current_date BETWEEN start_date AND
  end_date` returns exactly one term.

### PR 2 — Academics split: `courses`/`course_offerings`/`enrollments` (spine) — ~65 + 26 refs
- **Migration** `0020_academics_split.sql`: rename `courses → course_offerings` (it already
  holds the offering fields); add `course_offerings.term_id` (FK, backfill from the legacy
  `semester` string), add `course_offerings.course_id`; create abstract `courses` (one row per
  distinct `course_code`); point offerings at it; drop the abstract columns from offerings and
  the legacy `semester` text; create `enrollments` (was `user_courses`, empty) FK→offering.
- **Code:** `user_courses → enrollments` + course→offering/enrollment repoint in
  `routes/gradebook.py`, `routes/onboarding.py`, `routes/learn.py`, `routes/profile.py`,
  `services/graph_service.py`, `services/course_context_service.py`,
  `agents/tools/graph_read.py`, `models/__init__.py`. Surface `term`/`offering` on
  `/api/graph/<user>/courses`. Add `GET /api/semesters` (#138).
- **Tests:** `test_gradebook_routes`, `test_onboarding_routes`, `test_learn_routes`,
  `test_graph_service`, `test_graph_read_tools`, `test_shared_course_context`.
- **Closes / supersedes:** #137/#138/#259 spine; unblocks #260.
- **Acceptance:** enroll into an offering; getCourses returns its term; current-term is the
  default; the `'Spring 2026'` literal is gone from academics code.

### PR 3 — Gradebook → `enrollment` + `gradebook_categories` — ~13 refs
- **Migration** `0021_gradebook.sql`: `course_categories → gradebook_categories`, re-key to
  `enrollment_id`; `assignments` → `enrollment_id` + `category_id`, `due_date text→date`,
  `source`/`assignment_type` CHECK enums (read sets off code). Points stay 🔒 `text`.
- **Code:** `routes/gradebook.py`, `services/gradebook_service.py` — per-semester GPA (per
  offering) + cumulative/transcript (credit-weighted across offerings), `decrypt_numeric` at
  read. Coordinate with #126 (gradebook encryption boundary).
- **Tests:** `test_gradebook_routes` + a hand-computed GPA fixture.
- **Closes:** #138 GPA/transcript, #139 backend needs.
- **Acceptance:** transcript returns per-semester + cumulative GPA matching the fixture.

### PR 4 — Class analytics → `offering` — ~16 + 20 refs
- **Migration** `0022_analytics.sql`: `course_concept_stats → offering_concept_stats`
  (`offering_id`, drop `semester`, `UNIQUE(offering_id, concept_name)`); `course_summary →
  offering_summary` (`offering_id` PK).
- **Code:** `services/course_context_service.py` (`on_conflict="offering_id,concept_name"`),
  `services/graph_service.py`, `routes/social.py`.
- **Tests:** `test_shared_course_context`.
- **Acceptance:** the last free-text `semester` columns are gone; class-intel endpoints read
  by offering.

### PR 5 — Knowledge-graph integrity — FKs / UNIQUE / indexes / mastery events
- **Migration** `0023_graph_integrity.sql`: `graph_nodes` `UNIQUE NULLS NOT DISTINCT
  (user_id, course_id, concept_name)` + `course_id` FK; `graph_edges` `user_id` FK +
  `UNIQUE(user_id, source, target, type)` + indexes (`#160`); `node_mastery_events` table +
  index; `mastery_tier`/`relationship_type` CHECK enums (read sets off `graph_service.py`).
- **Code:** `services/graph_service.py` — UNIQUE-driven upserts; append-only
  `node_mastery_events` (fixes non-atomic RMW #247); delete `dedup_nodes.py` (#181).
- **Tests:** `test_graph_service`.
- **Closes:** #160, #179, #181, #195, #247.

### PR 6 — Identity split: `user_profiles` (independent) — 4 files
- **Migration** `0024_identity_split.sql`: create `user_profiles` (1:1); move
  `name/first_name/last_name/username/bio/location/website/avatar_url/year/majors/minors/
  learning_style` out of `users` and out of the duplicate columns on `user_settings`; CHECK
  enums on settings; `oauth_tokens.expires_at text→timestamptz`; `users.last_active_date
  text→date`.
- **Code:** `routes/auth.py`, `routes/profile.py` (read/write profile from `user_profiles`).
- **Tests:** `test_profile_routes`.
- **Acceptance:** one source of truth for each profile field; no column lives on both tables.

### PR 7 — Study & sessions integrity (depends on PR2 + PR5)
- **Migration** `0025_study_integrity.sql`: `notes` FKs `user_id`/`offering_id` (#180);
  `note_concepts.concept_node_id` FK; repoint `documents`/`notes`/`sessions`/`study_guides`/
  `flashcards` class link → `offering_id`; indexes `#161/#176/#177/#178`; `messages.role`/
  `sessions.mode`/`quiz.difficulty`/`documents.category` enums (read off code); `deleted_at`
  on `notes`/`documents`.
- **Code:** `services/notes_service.py`, `routes/documents.py`, `routes/learn.py`,
  `routes/quiz.py`, `routes/study_guide.py`.
- **Tests:** notes/documents/learn/quiz suites.
- **Closes:** #161, #176, #177, #178, #180.

### PR 8 — Ops cleanup (independent)
- **Migration** `0026_ops.sql`: `feedback` FKs (`user_id` cascade, `session_id` set-null);
  `issue_reports` FK `user_id`; integer-seq PKs → text/uuid per decision #1.
- **Code:** `routes/feedback.py`.
- **Tests:** feedback route smoke.

### PR 9 — `seed_staging.py` against the new schema (#258)
- **Code:** new `backend/db/seed_staging.py` — fake catalog (abstract courses + offerings
  across ≥2 terms) + fake enrollments + minimal supporting rows so graph + gradebook render.
  Wire into `docs/staging/setup-checklist.md` Step 6 (`migrate`, then seed).
- **Acceptance:** fresh staging → `python -m db.migrate` → `seed_staging.py` →
  `/api/graph/<user>/courses` returns the catalog and the gradebook grid renders.
- **Closes:** #258.

### PR 10 — Cutover: `epic/db-modular-redesign → main`
- **Docs:** update `docs/architecture.md`, `CLAUDE.md` (repo map + gotchas: new table names,
  encryption list), and append the **Promotion runbook** (below) to the staging checklist.
- **Verify:** full `pytest` green; `ruff check .` clean; apply the full migration set against a
  scratch DB end-to-end.
- The big PR body summarizes every slice and the issues closed/superseded.

---

## Staging → prod promotion runbook

The committed `0019+` files **are** the saved steps; promotion is just pointing the runner at
prod. Order of operations the first time:

1. **Baseline prod** (only if prod isn't already tracked by `#252`): record existing files as
   applied-without-running so the runner won't try to re-run `0001`–`0018`:
   ```
   SUPABASE_DB_URL=<prod-direct> python -m db.migrate --baseline
   ```
   Confirm with `SELECT count(*) FROM schema_migrations;` (should list 0001–0018).
2. **Apply the redesign** (after the epic→main PR merges and CI is green on staging):
   ```
   SUPABASE_DB_URL=<prod-direct> python -m db.migrate     # applies 0019+ only
   ```
3. The **PR 2 catalog-transform migration is data-driven** — it reads prod's real `courses`
   rows (distinct `course_code`/`semester`) and rewrites them into abstract courses +
   offerings + terms, exactly as it did on staging.
4. **Never** make schema changes in the Supabase dashboard/SQL editor — the repo is the only
   source of truth, or staging and prod silently diverge.

---

## PR 1 — detailed steps (start here tomorrow)

**Files:**
- Create: `backend/db/migrations/0019_conventions_terms_schools.sql`
- (Verify) `backend/db/migrate.py` — no change; runner picks the file up by numeric prefix.

**Interfaces produced (later slices rely on these):**
- `terms(id text, term text, year int, label text, start_date date, end_date date,
  sort_key int, created_at timestamptz)`, `UNIQUE(term, year)`.
- `schools(id text, name text, slug text UNIQUE, created_at timestamptz)`.
- `set_updated_at()` trigger function (reused by every later mutable table).
- "current term" = the row where `current_date BETWEEN start_date AND end_date`.

- [ ] **Step 1 — Write the migration file.** Create
  `backend/db/migrations/0019_conventions_terms_schools.sql`:

```sql
-- 0019: shared conventions + term/school entities (additive, non-breaking)

-- Reusable updated_at trigger (every later mutable table attaches this)
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE TABLE IF NOT EXISTS schools (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    slug       TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS terms (
    id         TEXT PRIMARY KEY,
    term       TEXT NOT NULL CHECK (term IN ('Fall','Spring','Summer','Winter')),
    year       INTEGER NOT NULL,
    label      TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date   DATE NOT NULL,
    sort_key   INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (term, year)
);

-- Seed: every distinct existing courses.semester string, mapped to real dates.
-- sort_key = year*10 + term ordinal (Spring=1, Summer=2, Fall=3, Winter=4).
INSERT INTO terms (id, term, year, label, start_date, end_date, sort_key) VALUES
  ('spring-2026', 'Spring', 2026, 'Spring 2026', '2026-01-12', '2026-05-08', 20261),
  ('fall-2025',   'Fall',   2025, 'Fall 2025',   '2025-08-25', '2025-12-19', 20253),
  ('fall-2026',   'Fall',   2026, 'Fall 2026',   '2026-08-24', '2026-12-18', 20263)
ON CONFLICT (term, year) DO NOTHING;
```

> Before finalizing the seed: run `SELECT DISTINCT semester FROM courses;` against the target
> DB and add a `terms` row for any value not covered above. Today's data is the single
> default `'Spring 2026'`; the extra rows give date-derived "current" something to resolve to.

- [ ] **Step 2 — Apply against staging and verify it lands.**

Run:
```
cd backend && SUPABASE_DB_URL=<staging-direct> python -m db.migrate
```
Expected: `Applied 1 migration(s):  - 0019_conventions_terms_schools.sql`

- [ ] **Step 3 — Verify the "current term" invariant.**

Run (psql or Supabase SQL editor against staging):
```sql
SELECT count(*) FROM terms WHERE current_date BETWEEN start_date AND end_date;
```
Expected: exactly `1`. (If `0` or `>1`, fix the seeded date ranges so they're contiguous and
non-overlapping, then add a corrective `0020_…` — do **not** edit `0019` once applied.)

- [ ] **Step 4 — Verify idempotency / re-run safety.**

Run `python -m db.migrate` again. Expected: `No pending migrations.` (filename already in
`schema_migrations`).

- [ ] **Step 5 — Commit on the slice branch.**

```bash
git checkout epic/db-modular-redesign && git pull
git checkout -b db/1-conventions-terms
git add backend/db/migrations/0019_conventions_terms_schools.sql
git commit -m "feat(db): add terms + schools entities and shared updated_at trigger (#137)"
git push -u origin db/1-conventions-terms
gh pr create --base epic/db-modular-redesign --title "db: conventions + terms + schools" \
  --body "First slice of the DB modular redesign. Adds the terms entity (#137), schools, and the shared set_updated_at() trigger. Purely additive — no code paths change. Spec: docs/superpowers/specs/2026-06-23-db-modular-redesign-design.md"
```

---

## Self-review notes

- **Spec coverage:** every §4 domain maps to a PR (Identity→6, Academics→2, Gradebook→3,
  Graph→5, Study→7, Analytics→4, Ops→8); §5 transform→PR2; §6 ordering→the slice order; §7
  code impact→per-slice code lists; §8 decisions→resolved table; promotion (§ from chat)→
  runbook. Social/Gamification intentionally untouched.
- **Per-slice TDD detail** for PRs 2–10 is deferred to per-PR `writing-plans` runs on purpose:
  the exact CHECK enum members and the 65/16/20-ref edit sites must be read off the real code
  at execution time rather than guessed here (would otherwise be banned placeholders).
- **Granularity:** PR2 is the largest (the spine); if review feels too big, it may split into
  2a (migration + models) / 2b (route repoint) on the epic branch — but they must land
  together to leave the epic branch green for that domain.
