# Sapling DB — Modular Redesign (Design Spec)

**Date:** 2026-06-23
**Status:** Design approved (domain map + conventions). Per-domain DDL below is the proposed application of the conventions — review before implementing.
**Author:** Andres + Claude (brainstorm)

---

## 1. Context & goal

Make the Postgres/Supabase schema **modular and well-designed**: bounded domains, one
entity = one concept, referential integrity enforced in the DB, consistent conventions.

**The unlock:** production has **no real user data — only the course catalog** ("mass
course list"). So we design the *correct* shapes directly (drop & recreate user-data
tables) and only **transform the existing catalog** once. No dual-read / backfill window.

**Scope:** full sweep — all 8 domains + ops. This **supersedes** the narrower Model-A plan
in epic #142 / #137 (which kept `semester` on a single mixed `courses` table).

**Trigger:** the semester work (#137/#138/#142/#259/#260) exposed that `courses` conflates
three concepts; fixing that properly pulls in the rest of the schema's drift.

---

## 2. Conventions charter (the house rules)

Every per-domain change below is one of these applied.

1. **One PK type: `uuid`** — `id uuid PRIMARY KEY DEFAULT gen_random_uuid()`. Retires the
   current mix (text app-ids, integer sequences, uuid). *(Open decision #1.)*
2. **FKs mandatory, explicit `ON DELETE`** — `CASCADE` for owned children, `SET NULL` for
   optional links, `RESTRICT` for catalog rows. No orphan-able `*_id`.
3. **Consistent timestamps** — `created_at timestamptz NOT NULL DEFAULT now()` on every
   table; `updated_at` on anything mutable (trigger-maintained).
4. **Real types, not text** — `date` / `timestamptz` / `numeric`. **Text only where column
   encryption forces it** (ciphertext can't be a native numeric/date) — tagged 🔒.
5. **Enums / lookups over magic strings** — CHECK-constrained.
6. **UNIQUE backs every dedup** — no Python-side dedup.
7. **Naming** — snake_case, plural tables, `<entity>_id` FKs, join tables `<a>_<b>` with
   composite PKs.
8. **Soft-delete only where recovery matters** (`users`, `courses`, `notes`, `documents`)
   via `deleted_at`; everything else hard-deletes via cascade.
9. **Encryption boundary documented** — every 🔒 column listed; encrypt at write, decrypt at
   read (incl. before AI prompts). Policy unchanged, just made visible.

> **Convention #4 ↔ encryption tension (important):** a column can be DB-native-typed *or*
> column-encrypted, not both. Encrypted numerics (gradebook points) stay **`text`
> ciphertext** and are decrypted+cast at the read boundary (`decrypt_numeric`). These are
> the 🔒 exceptions to rule #4.

---

## 3. Domain map

| Domain | Disposition | Tables |
|---|---|---|
| Identity & Access | **Restructure** | `users`, **`user_profiles`** (new), `user_settings`, `oauth_tokens` |
| Academics | **Restructure** | `schools?` (new), **`terms`** (new), `courses` (now abstract), **`course_offerings`** (new), `enrollments` (was `user_courses`) |
| Gradebook | **Repoint** | `gradebook_categories` (was `course_categories`), `assignments` |
| Knowledge Graph | **Fix** | `graph_nodes`, `graph_edges`, **`node_mastery_events`** (new) |
| Study & Sessions | **Fix** | `documents`, `notes`, `note_concepts`, `flashcards`, `quiz_attempts`, `quiz_context`, `study_guides`, `sessions`, `messages` |
| Class Analytics | **Repoint** | `offering_concept_stats` (was `course_concept_stats`), `offering_summary` (was `course_summary`) |
| Social / Rooms | **Keep (out of scope)** | `rooms`, `room_members`, `room_activity`, `room_messages`, `room_reactions`, `room_summaries` |
| Gamification | **Keep (template)** | `roles`, `user_roles`, `achievements`, `achievement_triggers`, `user_achievements`, `achievement_cosmetics`, `cosmetics`, `role_cosmetics`, `user_cosmetics` |
| Ops / Misc | **Fix** | `feedback`, `issue_reports`, `job_applications`, `newsletter_emails`, `admin_audit_log`, `schema_migrations` |

**The headline:** `courses` (catalog + offering + free-text term, all in one) splits into
**`courses`** (abstract: code/name/credits) + **`course_offerings`** (per-term:
instructor/room/section) + **`terms`** (orderable, date-ranged). `user_courses → enrollments`
FK to an *offering*. "Current term" is date-derived (today ∈ `[start_date, end_date]`).
Grades & analytics inherit the term through joins they already have.

**Term-scoping principle (Open decision #2):** *concept mastery* is cumulative across
terms → the **knowledge graph stays on the abstract `course_id`**. *Class artifacts*
(documents, notes, sessions, study guides, gradebook, analytics) are created within a
specific class instance → they reference **`offering_id`**. "Cumulative view" = query across
a user's offerings of the same course; "this term" = filter to the current term's offerings.

---

## 4. Per-domain target DDL

> uuid PKs shown per charter #1 (pending Open decision #1). 🔒 = column-encrypted (stays
> `text`). Enum value sets marked *(confirm)* must be read off the code before finalizing.

### 4.1 Identity & Access

```sql
-- Identity + auth only
CREATE TABLE users (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email                text,                    -- 🔒
  google_id            text UNIQUE,
  auth_provider        text NOT NULL DEFAULT 'google' CHECK (auth_provider IN ('google')),
  is_approved          boolean NOT NULL DEFAULT false,
  onboarding_completed boolean NOT NULL DEFAULT false,
  streak_count         integer NOT NULL DEFAULT 0,
  last_active_date     date,
  current_room_id      uuid REFERENCES rooms(id) ON DELETE SET NULL,
  last_sign_in_at      timestamptz,
  created_at           timestamptz NOT NULL DEFAULT now(),
  updated_at           timestamptz NOT NULL DEFAULT now(),
  deleted_at           timestamptz
);

-- Public profile (1:1) — single source of truth for display fields
CREATE TABLE user_profiles (
  user_id        uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  name           text,                  -- 🔒
  first_name     text,                  -- 🔒
  last_name      text,                  -- 🔒
  username       text UNIQUE,
  avatar_url     text,
  bio            text,                  -- 🔒
  location       text,                  -- 🔒
  website        text,
  year           text,                  -- (confirm: enum freshman..grad?)
  majors         text[] NOT NULL DEFAULT '{}',
  minors         text[] NOT NULL DEFAULT '{}',
  learning_style text,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now()
);

-- Preferences only (1:1) — NO duplicated profile fields
CREATE TABLE user_settings (
  user_id                  uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  profile_visibility       text NOT NULL DEFAULT 'public' CHECK (profile_visibility IN ('public','private')),
  activity_status_visible  boolean NOT NULL DEFAULT true,
  notification_email       boolean NOT NULL DEFAULT true,
  notification_push        boolean NOT NULL DEFAULT false,
  notification_in_app      boolean NOT NULL DEFAULT true,
  theme                    text NOT NULL DEFAULT 'light'  CHECK (theme IN ('light','dark')),
  font_size                text NOT NULL DEFAULT 'medium' CHECK (font_size IN ('small','medium','large')),
  accent_color             text,
  featured_role_id         uuid REFERENCES roles(id)     ON DELETE SET NULL,
  featured_achievement_ids text[] NOT NULL DEFAULT '{}',
  equipped_avatar_frame_id uuid REFERENCES cosmetics(id) ON DELETE SET NULL,
  equipped_banner_id       uuid REFERENCES cosmetics(id) ON DELETE SET NULL,
  equipped_name_color_id   uuid REFERENCES cosmetics(id) ON DELETE SET NULL,
  equipped_title_id        uuid REFERENCES cosmetics(id) ON DELETE SET NULL,
  created_at               timestamptz NOT NULL DEFAULT now(),
  updated_at               timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE oauth_tokens (
  user_id       uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  access_token  text NOT NULL,          -- 🔒
  refresh_token text NOT NULL,          -- 🔒
  expires_at    timestamptz NOT NULL,   -- was text
  updated_at    timestamptz NOT NULL DEFAULT now()
);
```

**Changes:** kills the `users ↔ user_settings` duplication (`name/bio/location/website` were
on both) by giving profile its own table; `oauth_tokens.expires_at` text→timestamptz;
`last_active_date` text→date; `auth_provider`/visibility/theme/font become CHECK enums.

### 4.2 Academics

```sql
CREATE TABLE schools (                  -- optional (Open decision #3)
  id   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  slug text NOT NULL UNIQUE,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE terms (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  term       text NOT NULL CHECK (term IN ('Fall','Spring','Summer','Winter')),
  year       integer NOT NULL,
  label      text NOT NULL,              -- 'Fall 2025'
  start_date date NOT NULL,
  end_date   date NOT NULL,
  sort_key   integer NOT NULL,           -- year*10 + term ordinal (orderable)
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (term, year)
);
-- "current term" = SELECT * FROM terms WHERE current_date BETWEEN start_date AND end_date;

CREATE TABLE courses (                   -- ABSTRACT catalog
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  school_id   uuid REFERENCES schools(id) ON DELETE RESTRICT,
  course_code text NOT NULL,             -- 'CS 101'
  course_name text NOT NULL,
  department  text,
  credits     integer,
  description text,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  deleted_at  timestamptz,
  UNIQUE (school_id, course_code)
);

CREATE TABLE course_offerings (          -- a course taught in a term
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  course_id       uuid NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  term_id         uuid NOT NULL REFERENCES terms(id)   ON DELETE RESTRICT,
  section         text,
  instructor_name text,
  meeting_times   text,
  location        text,
  syllabus_url    text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (course_id, term_id, section)
);

CREATE TABLE enrollments (               -- was user_courses
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         uuid NOT NULL REFERENCES users(id)            ON DELETE CASCADE,
  offering_id     uuid NOT NULL REFERENCES course_offerings(id) ON DELETE CASCADE,
  color           text,
  nickname        text,
  letter_scale    jsonb,
  syllabus_doc_id uuid REFERENCES documents(id) ON DELETE SET NULL,
  enrolled_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, offering_id)
);
CREATE INDEX idx_enrollments_user ON enrollments(user_id);
```

### 4.3 Gradebook

```sql
CREATE TABLE gradebook_categories (      -- was course_categories
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  enrollment_id uuid NOT NULL REFERENCES enrollments(id) ON DELETE CASCADE,
  name          text NOT NULL,
  weight        numeric NOT NULL,
  sort_order    integer NOT NULL DEFAULT 0,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_gradebook_categories_enrollment ON gradebook_categories(enrollment_id);

CREATE TABLE assignments (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  enrollment_id   uuid REFERENCES enrollments(id)         ON DELETE CASCADE,   -- nullable: calendar-only
  category_id     uuid REFERENCES gradebook_categories(id) ON DELETE SET NULL,
  title           text NOT NULL,
  due_date        date,                  -- was text
  assignment_type text,                  -- (confirm) CHECK ('homework','quiz','exam','project',...)
  notes           text,                  -- 🔒
  points_possible text,                  -- 🔒 (numeric semantics, decrypt_numeric at read)
  points_earned   text,                  -- 🔒
  source          text NOT NULL DEFAULT 'manual' CHECK (source IN ('manual','extracted','google')),
  google_event_id text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_assignments_enrollment ON assignments(enrollment_id);
CREATE INDEX idx_assignments_due        ON assignments(due_date);
```

**Changes:** re-keyed from `(user_id, course_id)` to `enrollment_id` (a student's specific
class); `due_date` text→date; `source`/`assignment_type` enums. Points stay 🔒 text.

### 4.4 Knowledge Graph

```sql
CREATE TABLE graph_nodes (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         uuid NOT NULL REFERENCES users(id)   ON DELETE CASCADE,
  course_id       uuid REFERENCES courses(id)          ON DELETE SET NULL,   -- abstract course; nullable
  concept_name    text NOT NULL,
  subject         text,
  mastery_score   double precision NOT NULL DEFAULT 0.0,
  mastery_tier    text NOT NULL DEFAULT 'unexplored'
                    CHECK (mastery_tier IN ('unexplored','struggling','familiar','mastered')),  -- (confirm set)
  times_studied   integer NOT NULL DEFAULT 0,
  last_studied_at timestamptz,
  color           text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE NULLS NOT DISTINCT (user_id, course_id, concept_name)   -- PG15+; backs dedup (#181)
);
CREATE INDEX idx_graph_nodes_user   ON graph_nodes(user_id);
CREATE INDEX idx_graph_nodes_course ON graph_nodes(course_id);

-- mastery_events jsonb extracted to rows → fixes non-atomic RMW (#247)
CREATE TABLE node_mastery_events (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  node_id    uuid NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
  delta      double precision NOT NULL,
  reason     text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_node_mastery_events_node ON node_mastery_events(node_id, created_at);

CREATE TABLE graph_edges (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id           uuid NOT NULL REFERENCES users(id)       ON DELETE CASCADE,   -- FK added (#179)
  source_node_id    uuid NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
  target_node_id    uuid NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
  relationship_type text NOT NULL DEFAULT 'related'
                      CHECK (relationship_type IN ('related','prerequisite','builds_on','part_of')),  -- (confirm set)
  strength          double precision NOT NULL DEFAULT 0.5,
  created_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, source_node_id, target_node_id, relationship_type)   -- backs dedup (#195)
);
CREATE INDEX idx_graph_edges_user   ON graph_edges(user_id);
CREATE INDEX idx_graph_edges_source ON graph_edges(source_node_id);
CREATE INDEX idx_graph_edges_target ON graph_edges(target_node_id);   -- (#160)
```

### 4.5 Study & Sessions

```sql
CREATE TABLE documents (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       uuid NOT NULL REFERENCES users(id)            ON DELETE CASCADE,
  offering_id   uuid NOT NULL REFERENCES course_offerings(id) ON DELETE CASCADE,
  file_name     text NOT NULL,
  category      text NOT NULL,           -- (confirm) CHECK enum
  summary       text,                    -- 🔒
  concept_notes text,                    -- 🔒
  flashcards    jsonb,
  request_id    text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  processed_at  timestamptz,
  deleted_at    timestamptz
);
CREATE INDEX idx_documents_user     ON documents(user_id);      -- (#177)
CREATE INDEX idx_documents_offering ON documents(offering_id);

CREATE TABLE notes (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         uuid NOT NULL REFERENCES users(id)            ON DELETE CASCADE,   -- FK added (#180)
  offering_id     uuid NOT NULL REFERENCES course_offerings(id) ON DELETE CASCADE,   -- FK added (#180)
  title           text,                  -- 🔒
  body            text,                  -- 🔒
  tags            text[] NOT NULL DEFAULT '{}',
  last_summary    text,                  -- 🔒
  last_summary_at timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  deleted_at      timestamptz
);
CREATE INDEX idx_notes_user     ON notes(user_id);
CREATE INDEX idx_notes_offering ON notes(offering_id);

CREATE TABLE note_concepts (
  note_id         uuid NOT NULL REFERENCES notes(id)       ON DELETE CASCADE,
  concept_node_id uuid NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,   -- FK added
  created_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (note_id, concept_node_id)
);

CREATE TABLE flashcards (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id          uuid NOT NULL REFERENCES users(id)            ON DELETE CASCADE,
  offering_id      uuid REFERENCES course_offerings(id)          ON DELETE SET NULL,   -- nullable
  topic            text NOT NULL,
  front            text NOT NULL,
  back             text NOT NULL,
  times_reviewed   integer NOT NULL DEFAULT 0,
  last_rating      integer,
  last_reviewed_at timestamptz,
  created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_flashcards_user ON flashcards(user_id);

CREATE TABLE sessions (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      uuid NOT NULL REFERENCES users(id)   ON DELETE CASCADE,
  offering_id  uuid REFERENCES course_offerings(id) ON DELETE SET NULL,   -- nullable: general tutoring
  mode         text NOT NULL,            -- (confirm) CHECK enum
  topic        text NOT NULL,
  name         text,
  summary_json text,                     -- 🔒
  started_at   timestamptz NOT NULL DEFAULT now(),
  ended_at     timestamptz
);
CREATE INDEX idx_sessions_user ON sessions(user_id);   -- (#176)

CREATE TABLE messages (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id        uuid NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  role              text NOT NULL CHECK (role IN ('user','assistant','system')),
  content           text NOT NULL,       -- 🔒
  graph_update_json jsonb,
  created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_messages_session ON messages(session_id, created_at);   -- (#161)

CREATE TABLE quiz_attempts (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         uuid NOT NULL REFERENCES users(id)       ON DELETE CASCADE,
  concept_node_id uuid REFERENCES graph_nodes(id)          ON DELETE SET NULL,
  score           integer,
  total           integer,
  difficulty      text,                  -- (confirm) CHECK enum
  questions_json  jsonb,
  answers_json    jsonb,
  completed_at    timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_quiz_attempts_user    ON quiz_attempts(user_id);          -- (#178)
CREATE INDEX idx_quiz_attempts_concept ON quiz_attempts(concept_node_id);

CREATE TABLE quiz_context (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         uuid NOT NULL REFERENCES users(id)       ON DELETE CASCADE,
  concept_node_id uuid NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
  context_json    jsonb NOT NULL,
  updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE study_guides (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      uuid NOT NULL REFERENCES users(id)            ON DELETE CASCADE,
  offering_id  uuid NOT NULL REFERENCES course_offerings(id) ON DELETE CASCADE,
  exam_id      text NOT NULL,
  content      jsonb NOT NULL,
  generated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_study_guides_user ON study_guides(user_id);   -- (#178)
```

### 4.6 Class Analytics

```sql
CREATE TABLE offering_concept_stats (    -- was course_concept_stats (free-text semester gone)
  id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  offering_id            uuid NOT NULL REFERENCES course_offerings(id) ON DELETE CASCADE,
  concept_name           text NOT NULL,
  student_count          integer NOT NULL DEFAULT 0,
  avg_mastery_score      double precision NOT NULL DEFAULT 0.0,
  pct_mastered           double precision NOT NULL DEFAULT 0.0,
  pct_struggling         double precision NOT NULL DEFAULT 0.0,
  pct_unexplored         double precision NOT NULL DEFAULT 0.0,
  common_misconceptions  text[] NOT NULL DEFAULT '{}',
  effective_explanations text[] NOT NULL DEFAULT '{}',
  prerequisite_gaps      text[] NOT NULL DEFAULT '{}',
  updated_at             timestamptz NOT NULL DEFAULT now(),
  UNIQUE (offering_id, concept_name)
);

CREATE TABLE offering_summary (          -- was course_summary
  offering_id             uuid PRIMARY KEY REFERENCES course_offerings(id) ON DELETE CASCADE,
  student_count           integer NOT NULL DEFAULT 0,
  avg_class_mastery       double precision NOT NULL DEFAULT 0.0,
  top_struggling_concepts text[] NOT NULL DEFAULT '{}',
  top_mastered_concepts   text[] NOT NULL DEFAULT '{}',
  summary_text            text,
  summary_hash            text,
  updated_at              timestamptz NOT NULL DEFAULT now()
);
```

> `course_context_service.py`'s `on_conflict="course_id,concept_name,semester"` becomes
> `on_conflict="offering_id,concept_name"`.

### 4.7 Ops / Misc

```sql
-- feedback: PK integer→uuid, add FKs
CREATE TABLE feedback (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id          uuid NOT NULL REFERENCES users(id)    ON DELETE CASCADE,
  session_id       uuid REFERENCES sessions(id)          ON DELETE SET NULL,
  type             text NOT NULL,
  rating           integer NOT NULL,
  selected_options jsonb NOT NULL DEFAULT '[]',
  comment          text,
  topic            text,
  created_at       timestamptz NOT NULL DEFAULT now()
);

-- issue_reports: PK integer→uuid, add FK
CREATE TABLE issue_reports (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  topic           text NOT NULL,
  description     text NOT NULL,
  screenshot_urls jsonb NOT NULL DEFAULT '[]',
  created_at      timestamptz NOT NULL DEFAULT now()
);
```

`job_applications`, `newsletter_emails`, `admin_audit_log`, `schema_migrations` — already
conform; no change.

### 4.8 Social / Rooms & Gamification — **unchanged (out of scope)**

Left as-is per decision. Gamification is already the convention template (uuid PKs, clean
join tables, CHECK enums). Optional later nicety: standardize `rooms.id` text→uuid for
cross-table consistency — **deferred**, not in this redesign.

---

## 5. Course-catalog transform (the only data migration)

The existing `courses` rows are the one thing to preserve. Each current row carries
abstract + offering + term fields mixed together. Transform:

1. **Seed `terms`** — one row per distinct existing `courses.semester` string (e.g.
   'Spring 2026') with real `start_date`/`end_date`/`sort_key`, plus canonical recent/future
   terms so date-derived "current" works.
2. **Abstract `courses`** — one row per distinct `course_code` (carry name/dept/credits/
   description/school).
3. **`course_offerings`** — one row per *existing* `courses` row → map to its abstract
   `course_id` + the `term_id` for its semester string; carry instructor/meeting/location/
   syllabus.
4. **No enrollments to migrate** (no user data). `seed_staging.py` (#258) creates *fake*
   enrollments + supporting rows for staging against this new schema.

New uuid ids are generated during the transform; nothing user-side references the old
catalog ids (no user data), so regeneration is safe.

---

## 6. Migration sequencing (ordered files, via the #252 runner)

Drop-and-recreate is fine (no user data) except step 3's catalog transform. FK dependency
order:

1. `NNNN_conventions.sql` — `updated_at` trigger fn; shared enums/lookups if used.
2. `NNNN_identity.sql` — `users`, `user_profiles`, `user_settings`, `oauth_tokens`.
3. `NNNN_academics.sql` — `schools?`, `terms`, `courses`, `course_offerings`, `enrollments`
   **+ §5 catalog transform**.
4. `NNNN_gradebook.sql` — `gradebook_categories`, `assignments`.
5. `NNNN_graph.sql` — `graph_nodes`, `node_mastery_events`, `graph_edges`.
6. `NNNN_study.sql` — `documents`, `notes`, `note_concepts`, `flashcards`, `sessions`,
   `messages`, `quiz_attempts`, `quiz_context`, `study_guides`.
7. `NNNN_analytics.sql` — `offering_concept_stats`, `offering_summary`.
8. `NNNN_ops.sql` — `feedback`, `issue_reports`.

`enrollments.syllabus_doc_id → documents` is a forward reference (documents created in step
6): declare that FK in step 6, or make it deferrable. Social & gamification untouched.

---

## 7. Downstream code impact (high-level — for the implementation plan)

- **`db/connection.py::table()`** — table renames: `user_courses→enrollments`,
  `course_categories→gradebook_categories`, `course_concept_stats→offering_concept_stats`,
  `course_summary→offering_summary`.
- **Routes** — `gradebook.py` (semester filter → `offering.term_id`; join through
  `enrollment`), `onboarding.py` / `graph.py::add_course` (enroll into an *offering*),
  `documents.py`, `notes.py`, `learn.py`, `quiz.py`, `social` (analytics rename).
- **Services** — `course_context_service.py` (offering-keyed conflict), `graph_service.py`
  (mastery events table; UNIQUE-driven upserts), `gradebook_service.py` (GPA: per-term via
  offering, cumulative across offerings; `decrypt_numeric` on 🔒 points).
- **Insert paths** — if Open decision #1 = uuid, every `table().insert()` that hand-builds a
  text id drops the id (DB generates it).
- **`seed_staging.py` (#258)** — author against this schema (fake catalog offerings + fake
  enrollments).
- **Frontend (#260)** — `EnrolledCourse` gains term; `SemesterChips` from real terms;
  `/api/semesters` (#138) from `terms`.

**Issue reconciliation:** supersedes #137/#138/#142/#259/#260 (fold into this);
closes #176/#177/#178/#160/#161 (indexes), #179/#180 (FKs), #181/#195 (UNIQUE dedup),
#247 (atomic mastery via events table); #258 re-scoped to seed the new schema.

---

## 8. Open decisions (confirm before coding)

1. **PK type — uuid vs keep text.** uuid is the charter default (cleanest/standard) but
   touches every insert path that hand-builds an id. Prod has no data, so *data* cost = 0;
   *code* cost is real. → **Recommend uuid.**
   - **Cascade caveat:** `users.id` text→uuid forces every column that references it to flip
     type too — including the "unchanged" Social/Gamification/Ops tables (`room_members.user_id`,
     `rooms.created_by`, `room_messages.user_id`, `user_roles.user_id`, `user_achievements.user_id`,
     `user_cosmetics.user_id`, `admin_audit_log.actor_id`, …). Their *design* is unchanged, but
     the FK **column type** changes. Likewise promote `rooms.id` text→uuid so `users.current_room_id`
     and the room-child FKs stay uuid-consistent. If decision = keep text, none of this applies.
2. **Study-artifact scope — `offering_id` (this spec) vs abstract `course_id`.** This spec
   ties class artifacts to the offering (preserves term, lets UI show cumulative *or* per
   term). Epic originally leaned "cumulative" (abstract course). → **Recommend offering_id.**
3. **`schools` table now vs defer** (`courses.school` is free text today). → Lightweight;
   recommend adding now since we're already here.
4. **Encrypted numerics stay 🔒 `text`** (points) — confirm acceptance of the rule-#4
   exception (can't be `numeric` + encrypted).
5. **Enum value sets** — read exact sets off code before finalizing: `mastery_tier`
   (`graph_service.py`), `relationship_type`, `session.mode`, `assignment_type`,
   `documents.category`, `quiz.difficulty`, `user_profiles.year`.

---

## 9. Next steps (resume here)

1. Resolve §8 open decisions.
2. Confirm enum value sets from code.
3. Run the **writing-plans** skill to turn this into an ordered implementation plan
   (migrations + per-route code changes + `seed_staging.py` + tests).
4. Implement domain-by-domain in the §6 order; each migration + code change ships reviewable.
