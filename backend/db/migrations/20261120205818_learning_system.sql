-- 20261120205818_learning_system.sql
-- The learning system (#866): the learning loop, Tutor V2, the quiz's learning
-- features and their fixes. These are the 62 migrations written for it,
-- consolidated into one file before any environment applied them (staging's and
-- production's ledgers held none), concatenated unchanged in their original
-- filename order.
--
-- Each original starts at its "-- @@ unit <original filename>" line, so a test,
-- script or doc can still name the migration a change came from
-- (db/migration_units.py reads them back). The runner applies this file as ONE
-- migration in ONE transaction: any failure rolls back all of it.
--
-- Deploy order: before the code (make promote does this). Without it, every
-- session and concept delete returns 500 (the learning_session_node_erase unit).

-- @@ unit 20260926231744_learning_loop_beta.sql
-- 20260926231744_learning_loop_beta.sql
-- Learning loop series PKG-00: per-user opt-in for the new tutor loop.
-- Paired with the LEARNING_LOOP_ENABLED env var (config.py); both must be
-- true for learning.gate.learning_loop_active() to return True.
ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS learning_loop_beta boolean NOT NULL DEFAULT false;

-- @@ unit 20260927024349_learning_learner_state.sql
-- 20260927024349_learning_learner_state.sql
-- Learning loop series PKG-03: per-(user, concept) BKT/FSRS state and the
-- evidence columns on the mastery journal. Spec §4 PKG-03 block, verbatim
-- (including max_streak_unassisted, spec §13 Amendment A3).
-- Deploy order: this migration BEFORE the code (apply_graph_update names the
-- new node_mastery_events columns and the learner_state table).
CREATE TABLE IF NOT EXISTS learner_state (
  user_id            text NOT NULL,
  node_id            text NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
  p_known            double precision NOT NULL,
  n_strong_unassisted int NOT NULL DEFAULT 0,
  streak_unassisted  int NOT NULL DEFAULT 0,
  max_streak_unassisted int NOT NULL DEFAULT 0,   -- Amendment A3: wheelspin needs "ever reached 3"
  opps               int NOT NULL DEFAULT 0,
  fsrs_d             double precision,
  fsrs_s             double precision,
  fsrs_last_review_at timestamptz,
  fsrs_due_at        timestamptz,
  htc_k              double precision,
  unassisted_next    double precision,
  assist_gap         double precision,
  in_zone            boolean,
  last_evidence_at   timestamptz,
  updated_at         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, node_id)
);
CREATE INDEX IF NOT EXISTS learner_state_due_idx ON learner_state (user_id, fsrs_due_at);
ALTER TABLE node_mastery_events
  ADD COLUMN IF NOT EXISTS channel text,
  ADD COLUMN IF NOT EXISTS correct boolean,
  ADD COLUMN IF NOT EXISTS weight double precision,
  ADD COLUMN IF NOT EXISTS assisted boolean,
  ADD COLUMN IF NOT EXISTS max_rung smallint,
  ADD COLUMN IF NOT EXISTS p_before double precision,
  ADD COLUMN IF NOT EXISTS p_after double precision,
  ADD COLUMN IF NOT EXISTS session_id text,
  ADD COLUMN IF NOT EXISTS check_item_id text,
  ADD COLUMN IF NOT EXISTS question_hash text,
  ADD COLUMN IF NOT EXISTS confidence double precision;
-- evidence rows use event_type = 'evidence'; delta = p_after - p_before keeps legacy readers valid.

-- @@ unit 20260927035346_learning_flashcards_fsrs.sql
-- 20260927035346_learning_flashcards_fsrs.sql
-- Learning loop series PKG-11: FSRS-6 state on flashcards (spec §3.2, §4).
-- Written only by routes/flashcards.py::rate_card when
-- learning.gate.learning_loop_active() is true; NULL on every legacy row.
ALTER TABLE flashcards
  ADD COLUMN IF NOT EXISTS fsrs_d double precision,
  ADD COLUMN IF NOT EXISTS fsrs_s double precision,
  ADD COLUMN IF NOT EXISTS due_at timestamptz,
  ADD COLUMN IF NOT EXISTS reps int NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS lapses int NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS flashcards_due_idx ON flashcards (user_id, due_at);

-- @@ unit 20260927065932_learning_check_items.sql
-- 20260927065932_learning_check_items.sql
-- Learning loop series PKG-04: ingest-time check items per course concept.
-- prompt / reference_answer / rubric_json / common_wrong_json / options_json /
-- correct_option / canonical_answer are encrypted (services/encryption.py);
-- question_hash is the plaintext lookup key.
-- Check items are COURSE assets, not per-student rows. graph_nodes is keyed per
-- (user, course, concept_name), so a node_id FK would bind an item to the
-- uploader. Key on (course_id, concept_key) instead, where concept_key =
-- services/graph_service._normalize_concept(concept_name). A student's node maps
-- to its items via _normalize_concept(graph_nodes.concept_name). (Amendment A2.)
CREATE TABLE IF NOT EXISTS check_items (
  id                text PRIMARY KEY,
  course_id         text NOT NULL,
  concept_key       text NOT NULL,
  document_id       text,
  format            text NOT NULL CHECK (format IN ('free','teachback','mc_reason')),
  difficulty        smallint NOT NULL CHECK (difficulty BETWEEN 1 AND 3),
  prompt            text NOT NULL,          -- encrypted
  reference_answer  text NOT NULL,          -- encrypted
  rubric_json       text NOT NULL,          -- encrypted JSON: [{"id": "...", "text": "..."}], >= CHECK_ITEM_MIN_RUBRIC
  common_wrong_json text NOT NULL,          -- encrypted JSON: [{"key": "...", "text": "..."}]; key is the plaintext id used elsewhere
  options_json      text,                   -- encrypted JSON [{"letter","text","wrong_key"}]; mc_reason only; exactly 1 correct (A22)
  correct_option    text,                   -- encrypted letter; mc_reason only (A22)
  answer_kind       text NOT NULL DEFAULT 'free' CHECK (answer_kind IN ('free','numeric')),   -- A22
  canonical_answer  text,                   -- encrypted; numeric only; parseable (A22)
  tolerance         double precision,       -- numeric only (A22)
  canonical_verified boolean NOT NULL DEFAULT false,  -- true ONLY on independent second-model agreement or instructor confirmation (A22)
  stepwise          boolean NOT NULL DEFAULT false,   -- reference has >= 2 numbered steps; H4 sibling eligibility (A17)
  source_chunk_ids  text[] NOT NULL DEFAULT '{}',
  source_document_ids text[] NOT NULL DEFAULT '{}',  -- documents whose passages drafted this item; withdrawal deletes by these (A23)
  question_hash     text NOT NULL,          -- sha256 of PLAINTEXT prompt (ADR 0025 pattern)
  graded            boolean NOT NULL DEFAULT false,   -- graded coursework flag; false on every generated item. Ungraded is not "practice" (H6 predicates, §3.3, A32)
  created_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (course_id, concept_key, question_hash)
);
CREATE INDEX IF NOT EXISTS check_items_concept_idx ON check_items (course_id, concept_key, format, difficulty);
CREATE INDEX IF NOT EXISTS check_items_source_docs_idx ON check_items USING gin (source_document_ids);

-- @@ unit 20260927093149_learning_grader_backend.sql
-- Learning loop PKG-05 (reopens PKG-03; spec §4, §13 A22): which backend
-- produced an evidence verdict. Plaintext enum; written only on evidence rows
-- by apply_graph_update, null on every legacy journal row.
ALTER TABLE node_mastery_events ADD COLUMN IF NOT EXISTS grader_backend text
  CHECK (grader_backend IS NULL OR grader_backend IN ('deterministic','gemini','gemini_second','jev'));

-- @@ unit 20260927093843_learning_session_loop_state.sql
-- 20260927093843_learning_session_loop_state.sql
-- Learning loop series PKG-06: per-session ZPD loop state (spec §4, §9).
-- keyed by question_hash: {rung, attempts, first_shown_at, last_rung_at, attempted_at[]}; no free text.
-- top-level id lists added later: "revealed" (A23, H4 siblings shown), "probe", "plan", "sr", "review" (PKG-08/12).
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS loop_state jsonb NOT NULL DEFAULT '{}'::jsonb;

-- @@ unit 20260927165158_learning_check_items_final_answer.sql
-- 20260927165158_learning_check_items_final_answer.sql
-- Learning loop PKG-04, reopened by PKG-06 (spec §4, §13 A34): each check item
-- states its final answer, copied verbatim from its reference_answer by the
-- generator, so the tutor's leak check matches a structured answer instead of
-- parsing reference text for one. The value is encrypted at the app layer
-- (services/encryption.py) like the item's prompt and reference; it is never
-- a key and never filtered on (invariant 9). Nullable only so existing rows
-- migrate: item selection never serves a row whose final_answer is NULL, and
-- scripts/backfill_check_items.py --regenerate-missing-final-answer redrafts
-- its concept.
ALTER TABLE public.check_items ADD COLUMN IF NOT EXISTS final_answer text;

-- @@ unit 20260927182054_learning_mastery_event_seq.sql
-- 20260927182054_learning_mastery_event_seq.sql
-- Learning loop, PKG-03 reopen (spec §4, §13 A36): the apply order of the
-- evidence journal. Every row one apply_graph_update call journals shares one
-- created_at and has a random uuid id, so nothing else orders them for a replay
-- (the 2026-09-27 live sequence test had to re-order a 3-question quiz from its
-- p_before -> p_after links). The evidence path sets 0..n-1 in apply order
-- within the call; a replay orders by (created_at, evidence_seq). NULL on every
-- legacy journal row and on evidence rows written before this migration.
-- Deploy order: this migration BEFORE the code (the evidence path names it).
ALTER TABLE node_mastery_events ADD COLUMN IF NOT EXISTS evidence_seq integer
  CHECK (evidence_seq IS NULL OR evidence_seq >= 0);

-- @@ unit 20260927194913_learning_llm_usage_tokens.sql
-- 20260927194913_learning_llm_usage_tokens.sql
-- Learning loop series PKG-06b (spec §4, §13 A21): usage observability.
-- cached_tokens   = Gemini usage_metadata.cached_content_token_count (implicit-cache hits)
-- thinking_tokens = Gemini usage_metadata.thoughts_token_count (already inside completion_tokens)
-- Filled by agents/usage.py::record_agent_usage; NULL on rows written before this migration
-- and on usage shapes that carry no such field. Counts only; never content.
-- llm_usage already has user_id, provider and idx_llm_usage_user_created (0035).
ALTER TABLE llm_usage
  ADD COLUMN IF NOT EXISTS cached_tokens int,
  ADD COLUMN IF NOT EXISTS thinking_tokens int;

-- @@ unit 20260929050242_learning_check_item_draft_failures.sql
-- 20260929050242_learning_check_item_draft_failures.sql
-- Learning loop PKG-04, post-hoc (owner decision A38, low-severity 2): bounded
-- redrafting. A concept whose drafts always fail validation was redrafted on
-- every upload and every backfill. This table counts a concept's consecutive
-- failed drafting passes against source_fp, a fingerprint of the passages the
-- pass drafted from (services/check_item_service._source_fingerprint). At
-- CHECK_ITEM_REDRAFT_MAX_FAILURES failures on an unchanged source the concept is
-- skipped; a pass that stores an item resets failures to 0, and a changed
-- source starts the count over. Course assets like check_items (A2): keyed on
-- (course_id, concept_key), no student id, no free text, nothing encrypted.
-- The bookkeeping fails open: a missing table or a failed read/write drafts.
CREATE TABLE IF NOT EXISTS check_item_draft_failures (
  course_id    text NOT NULL,
  concept_key  text NOT NULL,
  failures     int NOT NULL DEFAULT 0 CHECK (failures >= 0),
  source_fp    text NOT NULL,          -- sha256 over the drafted-from passages' ids + texts
  updated_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (course_id, concept_key)
);

-- @@ unit 20260929050404_learning_ai_tutor_daily_calls.sql
-- 20260929050404_learning_ai_tutor_daily_calls.sql
-- Learning loop, owner decision A38 on HANDOFF-06b ("New"): a daily cap on the
-- COUNT of tutor calls per student. Every $/token cap in services/ai_budget.py
-- reads llm_usage, and llm_usage is blind twice over: its cost read 0 on every
-- deployed backend for two months (#689), and EVENTS_LOGGING_ENABLED=false
-- writes no rows at all. This counter is written directly, never through
-- events_service, so it holds in both cases.
--
-- One row per (student, UTC day); `day` is passed by the backend (the UTC date
-- of its clock), so the database's timezone never moves a day boundary.
-- Counts only, never content. Rows of past days are inert (the cap reads today's
-- row only); nothing prunes them yet.
CREATE TABLE IF NOT EXISTS ai_tutor_daily_calls (
  user_id    text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  day        date NOT NULL,
  calls      integer NOT NULL DEFAULT 0 CHECK (calls >= 0),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, day)
);

-- The atomic increment: one statement, so two workers counting the same
-- student's calls can never lose one (a read-then-write from Python would).
-- Returns the new count. CREATE OR REPLACE: functions have no IF NOT EXISTS
-- form, and replacing with the identical body is the no-op a re-run wants.
CREATE OR REPLACE FUNCTION ai_budget_bump_tutor_calls(p_user_id text, p_day date)
RETURNS integer
LANGUAGE sql
VOLATILE
AS $$
    INSERT INTO ai_tutor_daily_calls (user_id, day, calls)
    VALUES (p_user_id, p_day, 1)
    ON CONFLICT (user_id, day) DO UPDATE
        SET calls = ai_tutor_daily_calls.calls + 1,
            updated_at = now()
    RETURNING calls;
$$;

-- Backend-only. The frontend ships the anon key and PostgREST exposes every
-- public-schema table and function, so without this anyone holding it could
-- read another student's counter or reset their own cap. RLS with no policy
-- denies every non-bypass role; service_role (the backend) bypasses RLS.
-- Role statements are guarded because those roles are Supabase's: a plain
-- Postgres has none of them, and an unguarded REVOKE naming one aborts the
-- whole migration. Same idiom as 20260921041555_canopy_active_users.sql.
ALTER TABLE ai_tutor_daily_calls ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE ai_tutor_daily_calls FROM PUBLIC;
REVOKE ALL ON FUNCTION ai_budget_bump_tutor_calls(text, date) FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON TABLE ai_tutor_daily_calls FROM %I', r);
            EXECUTE format(
                'REVOKE ALL ON FUNCTION ai_budget_bump_tutor_calls(text, date) FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE ai_tutor_daily_calls TO service_role;
        GRANT EXECUTE ON FUNCTION ai_budget_bump_tutor_calls(text, date) TO service_role;
    END IF;
END $$;

-- PostgREST resolves /rpc/<name> from its schema cache; the local stack does
-- not reliably reload on DDL (docs/local-supabase.md). NOTIFY is delivered at
-- COMMIT and is a no-op with no listener.
NOTIFY pgrst, 'reload schema';

-- @@ unit 20260929050800_learning_loop_state_rev.sql
-- 20260929050800_learning_loop_state_rev.sql
-- Learning loop, PKG-06 reopen (owner decision A38 06(q)): a compare-and-set
-- revision on sessions.loop_state. A streamed teach turn and /check/next can
-- overlap on one session; each save filters loop_state_rev=eq.<loaded> and
-- sets it to loaded + 1, so a stale writer updates zero rows (a conflict it
-- re-applies on the fresh state) instead of overwriting the other's changes.
-- 0 on every existing row. Deploy order: this migration BEFORE the code (the
-- store selects and filters on it). Existing table: RLS/grants unchanged.
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS loop_state_rev bigint NOT NULL DEFAULT 0;

-- @@ unit 20260929064939_learning_check_item_draft_failures_rls.sql
-- Learning loop PKG-04, A38 fix round (m1): check_item_draft_failures is
-- backend-only. 20260929050242_learning_check_item_draft_failures.sql created
-- it with no RLS, and PostgREST exposes every public-schema table to the anon
-- key the frontend ships, so anyone holding it could reset a concept's count
-- or stall a course's drafting. RLS with no policy denies every non-bypass
-- role; service_role (the backend) bypasses RLS. Role statements are guarded
-- because those roles are Supabase's: a plain Postgres has none of them, and an
-- unguarded REVOKE naming one aborts the whole migration. Same idiom as
-- 20260929050404_learning_ai_tutor_daily_calls.sql.
ALTER TABLE check_item_draft_failures ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE check_item_draft_failures FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON TABLE check_item_draft_failures FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE check_item_draft_failures TO service_role;
    END IF;
END $$;

-- @@ unit 20260929073325_learning_check_item_draft_failures_solo.sql
-- Learning loop PKG-04, A38 fix round 3: remember a combination-only failure.
-- A multi-concept drafting call whose output never validated is split and each
-- concept re-run alone (services/check_item_service.py). When every concept of
-- the split stored items alone, the failure was the combination's, so they are
-- marked `solo` and drafted alone on later passes (N calls, not 1 + N) while
-- source_fp is unchanged and updated_at is within
-- CHECK_ITEM_REDRAFT_FAILURE_TTL_DAYS. Deploy BEFORE the code: the code reads
-- and writes the column, and a missing column makes the bookkeeping fail open
-- (a WARNING; every concept drafted batched, as before).
ALTER TABLE check_item_draft_failures ADD COLUMN IF NOT EXISTS solo boolean NOT NULL DEFAULT false;

-- @@ unit 20260929081946_learning_sessions_mode_review.sql
-- 20260929081946_learning_sessions_mode_review.sql  (spec §4, Amendment A9)
-- Learning loop series PKG-12: daily review sessions are `sessions` rows so
-- successive-relearning counters can live in sessions.loop_state (PKG-06)
-- without a new column. 0025 constrained mode to socratic/expository/
-- teachback; widen it. The inline CHECK's default name is sessions_mode_check.
-- Existing table: RLS/grants unchanged.
ALTER TABLE sessions DROP CONSTRAINT IF EXISTS sessions_mode_check;
ALTER TABLE sessions ADD CONSTRAINT sessions_mode_check
    CHECK (mode IN ('socratic','expository','teachback','review'));

-- @@ unit 20260929111535_learning_fsrs_stability_positive.sql
-- 20260929111535_learning_fsrs_stability_positive.sql  (spec §4; PKG-12 fix round)
-- Learning loop series PKG-12: an FSRS stability is a finite positive number of
-- days, or NULL (never scheduled: the reader uses FSRS_S0_GOOD). The review queue
-- skips a row that breaks this (learning/review.py::InvalidStability); this makes
-- the database refuse one. In Postgres 'NaN' compares greater than every number,
-- including 'Infinity', so `< 'Infinity'` excludes both NaN and +Infinity.
-- Existing rows: the only writers are graph_service._fsrs_after (learner_state)
-- and learning/flashcard_fsrs.flashcard_fsrs_update (flashcards), both through
-- learning.fsrs.next_state, which floors every new stability at
-- FSRS_STABILITY_MIN (0.001) and is finite for finite input
-- (tests/test_learning_review.py::test_fsrs_writers_never_store_an_invalid_stability).
-- Existing tables: RLS/grants unchanged.
ALTER TABLE learner_state DROP CONSTRAINT IF EXISTS learner_state_fsrs_s_positive;
ALTER TABLE learner_state ADD CONSTRAINT learner_state_fsrs_s_positive
    CHECK (fsrs_s IS NULL OR (fsrs_s > 0 AND fsrs_s < 'Infinity'::double precision));
ALTER TABLE flashcards DROP CONSTRAINT IF EXISTS flashcards_fsrs_s_positive;
ALTER TABLE flashcards ADD CONSTRAINT flashcards_fsrs_s_positive
    CHECK (fsrs_s IS NULL OR (fsrs_s > 0 AND fsrs_s < 'Infinity'::double precision));

-- @@ unit 20260929112944_learning_session_close.sql
-- 20260929112944_learning_session_close.sql
-- Learning loop series PKG-09: the end-of-session close (model-written
-- summary, self-evaluation prompt, if-then plan), the phase the session
-- stopped in, and the session's learner brief. close_json is encrypted JSON
-- (services/encryption.py::encrypt_json); loop_brief is encrypted (A19)
-- (services/encryption.py::encrypt_if_present), built once per session.
-- Never filter or join on either. Spec §4 / §9 / §13 A19.
-- Existing table: RLS/grants unchanged (as 20260929050800_learning_loop_state_rev.sql);
-- both text columns hold ciphertext only, close_phase an enum value.
ALTER TABLE sessions
  ADD COLUMN IF NOT EXISTS close_json text,          -- encrypted JSON {summary, self_eval, if_then, concepts:[{node_id, p_before, p_after}], misconceptions:[wrong_key]}
  ADD COLUMN IF NOT EXISTS close_phase text CHECK (close_phase IN ('probe','plan','teach','check','feedback','close')),
  ADD COLUMN IF NOT EXISTS loop_brief text;          -- encrypted learner brief, built once per session (A19)

-- @@ unit 20260929132008_learning_misconceptions.sql
-- 20260929132008_learning_misconceptions.sql
-- Learning loop series PKG-10: per-student misconception store fed by the
-- grader's matched wrong key (spec §3.3 rule, §4 PKG-10 block), plus the
-- class rollup. `evidence_text` is encrypted (services/encryption.py) and is
-- never filtered on; `wrong_key` is the plaintext key from common_wrong_json.
-- The rollup returns nothing below MISCONCEPTION_ROLLUP_MIN_USERS distinct
-- students (learning/params.py mirrors the literal below; the test pins them
-- equal) and is executable by service_role only — it is a backend function,
-- not a tutor tool (ADR 0023 §5).
CREATE TABLE IF NOT EXISTS misconceptions (
  id             text PRIMARY KEY,
  user_id        text NOT NULL,
  node_id        text NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
  check_item_id  text,
  wrong_key      text NOT NULL,             -- plaintext enum key from common_wrong_json
  evidence_text  text,                      -- encrypted
  count          int NOT NULL DEFAULT 1,
  first_seen_at  timestamptz NOT NULL DEFAULT now(),
  last_seen_at   timestamptz NOT NULL DEFAULT now(),
  resolved_at    timestamptz
);
CREATE INDEX IF NOT EXISTS misconceptions_user_node_idx ON misconceptions (user_id, node_id, wrong_key);
-- graph_nodes rows are per user, so the rollup groups by the COURSE concept, never by
-- node_id (A29). concept_key mirrors services/graph_service._normalize_concept (runs of
-- whitespace become one space, trimmed, case-folded) and equals check_items.concept_key
-- (A2). SQL lower() stands in for Python casefold(): they agree on ASCII names and
-- can differ on some non-ASCII characters (e.g. ß, which casefold expands).
-- SECURITY DEFINER pins its search_path, so no caller-controlled schema can
-- shadow `misconceptions` or `graph_nodes` inside it (PKG-10 Deviation to §4).
CREATE OR REPLACE FUNCTION misconception_rollup(p_course_id text)
RETURNS TABLE (concept_key text, wrong_key text, users int)
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT lower(btrim(regexp_replace(g.concept_name, '\s+', ' ', 'g'))), m.wrong_key,
         count(DISTINCT m.user_id)::int
  FROM misconceptions m JOIN graph_nodes g ON g.id = m.node_id
  WHERE g.course_id = p_course_id AND m.resolved_at IS NULL
  GROUP BY g.course_id, lower(btrim(regexp_replace(g.concept_name, '\s+', ' ', 'g'))), m.wrong_key
  HAVING count(DISTINCT m.user_id) >= 5
$$;

-- Backend-only. The frontend ships the anon key and PostgREST exposes every
-- public-schema table and function: without this anyone holding it could read
-- another student's misconceptions or call the rollup below its floor's
-- intent. RLS with no policy denies every non-bypass role; service_role (the
-- backend) bypasses RLS. Functions grant EXECUTE to PUBLIC by default, so
-- PUBLIC is revoked outright. Role statements are guarded because those roles
-- are Supabase's: a plain Postgres has none of them, and an unguarded REVOKE
-- naming one aborts the whole migration. Same idiom as
-- 20260929050404_learning_ai_tutor_daily_calls.sql.
ALTER TABLE misconceptions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE misconceptions FROM PUBLIC;
REVOKE ALL ON FUNCTION misconception_rollup(text) FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON TABLE misconceptions FROM %I', r);
            EXECUTE format('REVOKE ALL ON FUNCTION misconception_rollup(text) FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE misconceptions TO service_role;
        GRANT EXECUTE ON FUNCTION misconception_rollup(text) TO service_role;
    END IF;
END $$;

-- PostgREST resolves /rpc/<name> from its schema cache; the local stack does
-- not reliably reload on DDL (docs/local-supabase.md). NOTIFY is delivered at
-- COMMIT and is a no-op with no listener.
NOTIFY pgrst, 'reload schema';

-- @@ unit 20260929143810_learning_misconceptions_atomic.sql
-- 20260929143810_learning_misconceptions_atomic.sql
-- Learning loop PKG-10 fix round (F5, F6; spec §13 A75). A NEW migration:
-- 20260929132008_learning_misconceptions.sql is applied and never edited.
--
-- F5: learning.misconceptions.record was a read-then-insert/update from
-- Python, so two concurrent grades could open two rows for one key or lose an
-- increment. One open row per (student, node, key) is now a partial UNIQUE
-- index (never on the encrypted evidence_text), and the insert-or-increment is
-- ONE statement, misconception_record(...), INSERT ... ON CONFLICT on that
-- index. Open duplicates a racing writer may have left are merged first (their
-- counts summed onto the most recently seen row).
--
-- F6: the class rollup joins each row's node to its OWN student
-- (g.user_id = m.user_id) as defense in depth: a row naming another student's
-- node never counts. Same signature, same floor, same grants.
WITH ranked AS (
  SELECT id,
         row_number() OVER (PARTITION BY user_id, node_id, wrong_key
                            ORDER BY last_seen_at DESC, id) AS rn,
         sum(count) OVER (PARTITION BY user_id, node_id, wrong_key) AS total
  FROM misconceptions
  WHERE resolved_at IS NULL
)
UPDATE misconceptions m SET count = r.total
FROM ranked r
WHERE m.id = r.id AND r.rn = 1 AND m.count <> r.total;

WITH ranked AS (
  SELECT id,
         row_number() OVER (PARTITION BY user_id, node_id, wrong_key
                            ORDER BY last_seen_at DESC, id) AS rn
  FROM misconceptions
  WHERE resolved_at IS NULL
)
DELETE FROM misconceptions m USING ranked r WHERE m.id = r.id AND r.rn > 1;

CREATE UNIQUE INDEX IF NOT EXISTS misconceptions_open_key_uidx
  ON misconceptions (user_id, node_id, wrong_key) WHERE resolved_at IS NULL;

CREATE OR REPLACE FUNCTION misconception_record(
  p_id text, p_user_id text, p_node_id text, p_check_item_id text,
  p_wrong_key text, p_evidence_text text
)
RETURNS TABLE (id text, count int)
LANGUAGE sql SET search_path = public, pg_temp AS $$
  INSERT INTO misconceptions
    (id, user_id, node_id, check_item_id, wrong_key, evidence_text, count)
  VALUES (p_id, p_user_id, p_node_id, p_check_item_id, p_wrong_key, p_evidence_text, 1)
  ON CONFLICT (user_id, node_id, wrong_key) WHERE resolved_at IS NULL
  DO UPDATE SET count = misconceptions.count + 1,
                last_seen_at = now(),
                check_item_id = EXCLUDED.check_item_id,
                evidence_text = EXCLUDED.evidence_text
  RETURNING misconceptions.id, misconceptions.count
$$;

CREATE OR REPLACE FUNCTION misconception_rollup(p_course_id text)
RETURNS TABLE (concept_key text, wrong_key text, users int)
LANGUAGE sql SECURITY DEFINER SET search_path = public, pg_temp AS $$
  SELECT lower(btrim(regexp_replace(g.concept_name, '\s+', ' ', 'g'))), m.wrong_key,
         count(DISTINCT m.user_id)::int
  FROM misconceptions m JOIN graph_nodes g ON g.id = m.node_id
  WHERE g.course_id = p_course_id AND g.user_id = m.user_id AND m.resolved_at IS NULL
  GROUP BY g.course_id, lower(btrim(regexp_replace(g.concept_name, '\s+', ' ', 'g'))), m.wrong_key
  HAVING count(DISTINCT m.user_id) >= 5
$$;

-- Backend-only, like the rollup (20260929132008): functions grant EXECUTE to
-- PUBLIC by default; the Supabase roles are guarded (a plain Postgres has none).
REVOKE ALL ON FUNCTION misconception_record(text, text, text, text, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION misconception_rollup(text) FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON FUNCTION misconception_record(text, text, text, text, text, text) FROM %I', r);
            EXECUTE format('REVOKE ALL ON FUNCTION misconception_rollup(text) FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT EXECUTE ON FUNCTION misconception_record(text, text, text, text, text, text) TO service_role;
        GRANT EXECUTE ON FUNCTION misconception_rollup(text) TO service_role;
    END IF;
END $$;

NOTIFY pgrst, 'reload schema';

-- @@ unit 20260929175715_learning_loop_arm.sql
-- 20260929175715_learning_loop_arm.sql
-- Learning loop series PKG-14: within-student A/B arm label. NULL = no
-- experiment (every concept is variant A). learning/policy.py::variant_for
-- hashes (arm, user_id, node_id) so concepts are randomised WITHIN a student.
ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS loop_arm text;

-- @@ unit 20260930024005_learning_posttest_poses.sql
-- 20260930024005_learning_posttest_poses.sql
-- Learning loop series PKG-14 (review fix round, spec §13 A87): the tool-removed
-- post-test commits when it is opened. /api/learn/loop/posttest/start records
-- the item it poses for a (student, node); a repeat start returns the SAME item
-- (no shopping), and /posttest/answer grades only the open pose, under a claim
-- taken by one conditional UPDATE (answered_at IS NULL, claim free or stale) —
-- a database claim, so a double submit never grades twice in any number of
-- backend processes. One row per (student, node); a later post-test of the
-- node (due again once its newest evidence is old enough) replaces it.
-- Hashes, ids and timestamps only — never item or answer text.
CREATE TABLE IF NOT EXISTS posttest_poses (
  user_id       text        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  node_id       text        NOT NULL,
  course_id     text        NOT NULL,
  question_hash text        NOT NULL,
  posed_at      timestamptz NOT NULL DEFAULT now(),
  answered_at   timestamptz,
  claim         text,
  claimed_at    timestamptz,
  PRIMARY KEY (user_id, node_id)
);

-- Backend-only (the 20260929050404_learning_ai_tutor_daily_calls.sql idiom):
-- RLS with no policy denies every non-bypass role; service_role bypasses it.
-- Role statements are guarded because those roles are Supabase's.
ALTER TABLE posttest_poses ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE posttest_poses FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON TABLE posttest_poses FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE posttest_poses TO service_role;
    END IF;
END $$;

-- PostgREST serves the new table from its schema cache; reload it (a no-op with
-- no listener).
NOTIFY pgrst, 'reload schema';

-- @@ unit 20260930031644_learning_reveals.sql
-- 20260930031644_learning_reveals.sql
-- Learning loop series PKG-14 (re-review fix round, spec §13 A88): the items a
-- served tutor turn revealed, and the fail-closed markers of turns whose open
-- items could not be read — keyed by the STUDENT, not by a session row, so a
-- reveal is durable the moment it is served (the loop opener has no session
-- row yet) and every grading and selection path reads it
-- (loop_state_store.revealed_hashes, routes/learn_loop.py::_reveal_floor).
--
-- kind = 'reveal':    question_hash names an OPEN, POSED item (the active check
--                     item, an open review item, an open post-test pose) whose
--                     answer the served text stated; it is never selected again
--                     and grades with no unassisted credit.
-- kind = 'unscanned': the turn's open items could not be read; every item posed
--                     at or before `at` and still open grades as assisted.
-- Append-only; hashes, ids and timestamps only — never item or tutor text.
CREATE TABLE IF NOT EXISTS learning_reveals (
  id            text        PRIMARY KEY DEFAULT gen_random_uuid()::text,
  user_id       text        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind          text        NOT NULL CHECK (kind IN ('reveal', 'unscanned')),
  question_hash text,
  session_id    text,
  source        text,
  at            timestamptz NOT NULL DEFAULT now(),
  CHECK ((kind = 'reveal') = (question_hash IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS learning_reveals_user_kind_at ON learning_reveals (user_id, kind, at);

-- Backend-only (the 20260929050404_learning_ai_tutor_daily_calls.sql idiom).
ALTER TABLE learning_reveals ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE learning_reveals FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON TABLE learning_reveals FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE learning_reveals TO service_role;
    END IF;
END $$;

NOTIFY pgrst, 'reload schema';

-- @@ unit 20260930042516_learning_llm_usage_session_id.sql
-- Learning loop series PKG-14 half B (owner decision 2026-09-29, spec §13 A89):
-- the loop session an llm_usage row's run belonged to, when the run site knew it
-- (agents/usage.py::record_agent_usage(session_id=…)). scripts/derive_zpd_metrics.py
-- costs a row per session from this column first and falls back to the A82 event
-- join, then to per user-day, for rows that carry no session (every row written
-- before this migration, and runs with no session: course-asset drafting, the
-- post-test grade, non-tutor features). An id only — never content.
-- Additive and nullable: no default, no backfill, no index (the report reads a
-- created_at window through idx_llm_usage_user_created, 0035). llm_usage's RLS
-- and grants are table-level (0035) and cover the new column unchanged. A deploy
-- that reaches a database before this migration drops the column from its
-- inserts and retries (services/events_service.py), so no usage row is lost.
ALTER TABLE llm_usage
  ADD COLUMN IF NOT EXISTS session_id text;

-- PostgREST serves the new column from its schema cache; reload it (a no-op with
-- no listener).
NOTIFY pgrst, 'reload schema';

-- @@ unit 20261001010805_learning_help_ledger.sql
-- Learning loop series PKG-14 (review fix round, owner decision 1, spec §13 A93):
-- the per-student HELP LEDGER, on half A's learning_reveals table.
--
-- kind = 'help':  question_hash got help at `rung` (0..LADDER_MAX_RUNG = 6):
--                 a hint rung above H0 (any session or surface), an H4 sibling
--                 payload (recorded at RUNG_NO_CREDIT_MIN = 4 on the sibling),
--                 an H6 release / worked solution / deterministic reference.
--                 Written as the help is served, never at turn end.
-- kind = 'posed': the student was shown question_hash's prompt (a loop check,
--                 a probe item, a review item, a post-test pose). `graded_at`
--                 is set once the item is graded; every ungraded posed item is
--                 in the served-text scan set (bounded by LOOP_SCAN_POSED_MAX).
-- 'reveal' and 'unscanned' keep half A's meaning (20260930031644).
--
-- Every grade's floor is the MAX help ever recorded for (student, item), a
-- 'reveal' counting as RUNG_NO_CREDIT_MIN — re-read inside the grading claim,
-- right before the one evidence write. Append-only except `graded_at`; hashes,
-- ids, rungs and timestamps only — never item or tutor text. Idempotent.
ALTER TABLE learning_reveals ADD COLUMN IF NOT EXISTS rung smallint;
ALTER TABLE learning_reveals ADD COLUMN IF NOT EXISTS graded_at timestamptz;

ALTER TABLE learning_reveals DROP CONSTRAINT IF EXISTS learning_reveals_kind_check;
ALTER TABLE learning_reveals ADD CONSTRAINT learning_reveals_kind_check
  CHECK (kind IN ('reveal', 'unscanned', 'help', 'posed'));

-- half A's "(kind = 'reveal') = (question_hash IS NOT NULL)" becomes: only an
-- 'unscanned' marker has no question hash
ALTER TABLE learning_reveals DROP CONSTRAINT IF EXISTS learning_reveals_check;
ALTER TABLE learning_reveals DROP CONSTRAINT IF EXISTS learning_reveals_hash_check;
ALTER TABLE learning_reveals ADD CONSTRAINT learning_reveals_hash_check
  CHECK ((kind = 'unscanned') = (question_hash IS NULL));

ALTER TABLE learning_reveals DROP CONSTRAINT IF EXISTS learning_reveals_rung_check;
ALTER TABLE learning_reveals ADD CONSTRAINT learning_reveals_rung_check
  CHECK ((kind = 'help') = (rung IS NOT NULL) AND (rung IS NULL OR rung BETWEEN 0 AND 6));

ALTER TABLE learning_reveals DROP CONSTRAINT IF EXISTS learning_reveals_graded_check;
ALTER TABLE learning_reveals ADD CONSTRAINT learning_reveals_graded_check
  CHECK (graded_at IS NULL OR kind = 'posed');

CREATE INDEX IF NOT EXISTS learning_reveals_user_hash ON learning_reveals (user_id, question_hash);
CREATE INDEX IF NOT EXISTS learning_reveals_posed_open
  ON learning_reveals (user_id, at DESC) WHERE kind = 'posed' AND graded_at IS NULL;

-- RLS and the backend-only grants are table-level (20260930031644) and unchanged.
NOTIFY pgrst, 'reload schema';

-- @@ unit 20261001013855_learning_rederive_mastery_tier.sql
-- Learning loop series PKG-14 half B (review fix round, regression M2, spec §13 A95):
-- re-derive every stored graph_nodes.mastery_tier from mastery_score with the
-- ONE tier function's cuts (learning/bkt.py::tier_for over learning/params.py
-- TIER_UNEXPLORED_MAX 0.10 / BAND_NOVICE_MAX 0.30 / BKT_PROFICIENT 0.95).
-- Rows written under the retired 0.1 / 0.45 / 0.75 cuts would otherwise keep
-- them until their next write — a "mastered" 0.8 node demoted after a good quiz.
-- The CASE mirrors tier_for exactly (pinned by
-- tests/test_learning_tier_rederive_migration.py). Scores are clamped to [0, 1]
-- as tier_for's callers clamp. 'subject_root' rows (CHECK, 0023) are left alone.
-- Idempotent: only rows whose tier differs are touched; a second run is a no-op.
-- Runs at the migration step of the launch runbook (half B ships it).
UPDATE graph_nodes
SET mastery_tier = CASE
    WHEN p >= 0.95 THEN 'mastered'
    WHEN p >= 0.30 THEN 'learning'
    WHEN p >= 0.10 THEN 'struggling'
    ELSE 'unexplored'
  END
FROM (
  SELECT id AS node_id, LEAST(1.0, GREATEST(0.0, COALESCE(mastery_score, 0.0))) AS p
  FROM graph_nodes
) AS s
WHERE graph_nodes.id = s.node_id
  AND graph_nodes.mastery_tier IS DISTINCT FROM 'subject_root'
  AND graph_nodes.mastery_tier IS DISTINCT FROM (
    CASE
      WHEN s.p >= 0.95 THEN 'mastered'
      WHEN s.p >= 0.30 THEN 'learning'
      WHEN s.p >= 0.10 THEN 'struggling'
      ELSE 'unexplored'
    END
  );

-- @@ unit 20261001060408_learning_quiz_evidence_claims.sql
-- 20261001060408_learning_quiz_evidence_claims.sql
-- Learning loop series PKG-14 (final fix round, spec §13 A100; tightens A94):
-- quiz evidence cannot be farmed. /api/quiz/submit writes at most ONE quiz
-- evidence per (student, question_hash) per ROLLING 24 h window, decided by a
-- CLAIM on this table — not by counting node_mastery_events, which (a) raced:
-- two concurrent submits sharing a hash both read "not counted" and both wrote,
-- and (b) failed open: a dropped evidence insert left nothing to count.
--
-- The claim is taken BEFORE the evidence write, per hash, by two statements the
-- database arbitrates:
--   1. INSERT ... ON CONFLICT (user_id, question_hash) DO NOTHING — a fresh
--      hash is claimed by exactly one submitter (the loser's row is ignored);
--   2. UPDATE ... SET claimed_at = now WHERE claimed_at < now - 24 h — a stale
--      claim is renewed by exactly one submitter (READ COMMITTED re-checks the
--      WHERE after the winner commits).
-- A hash neither statement returned is not this submit's: it writes no
-- evidence for it. A claim taken whose evidence write then fails stays taken
-- (fail closed: that question earns nothing for the window).
-- One row per (student, hash); hashes, ids and timestamps only.
CREATE TABLE IF NOT EXISTS quiz_evidence_claims (
  user_id       text        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  question_hash text        NOT NULL,
  attempt_id    text        NOT NULL,
  claimed_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, question_hash)
);

-- Backend-only (the 20260929050404_learning_ai_tutor_daily_calls.sql idiom):
-- RLS with no policy denies every non-bypass role; service_role bypasses it.
ALTER TABLE quiz_evidence_claims ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE quiz_evidence_claims FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON TABLE quiz_evidence_claims FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE quiz_evidence_claims TO service_role;
    END IF;
END $$;

NOTIFY pgrst, 'reload schema';

-- @@ unit 20261019010000_learning_planning_observation.sql
-- Evidence provenance for cross-session goal readiness. Legacy NULL is unknown;
-- do not backfill independence from weight, scores or old session summaries.
ALTER TABLE node_mastery_events
  ADD COLUMN IF NOT EXISTS planning_observation jsonb
  CHECK (planning_observation IS NULL OR jsonb_typeof(planning_observation) = 'object');

-- This column is deliberately NOT an optional-column write downgrade. Tagged
-- loop grades must append the event before scalar writes, or return retryable
-- unavailable. Apply before serving the new tagged grading path.

-- @@ unit 20261019125459_checklist_budget.sql
-- Checklist-participant capacity admission, not a global/provider invoice cap.
-- Apply before the service. Account lock serializes all participating operations.
-- USD estimate = 50,000 cumulative input * .0003/1000 +
-- 3 * 8,192 output (including thinking) * .0025/1000 = .0764400000.
-- The native full-input count is a provider oracle estimate, not an invoice bound.
CREATE TABLE IF NOT EXISTS checklist_budget_accounts (
    user_id text PRIMARY KEY,
    policy text NOT NULL DEFAULT 'flash-50k-3x8192-v1' CHECK (policy = 'flash-50k-3x8192-v1'),
    daily_usd numeric(18,10) NOT NULL DEFAULT .20 CHECK (daily_usd > 0 AND daily_usd <= .20),
    monthly_usd numeric(18,10) NOT NULL DEFAULT 2.00 CHECK (monthly_usd > 0 AND monthly_usd <= 2.00),
    daily_tokens bigint NOT NULL DEFAULT 400000 CHECK (daily_tokens > 0 AND daily_tokens <= 400000),
    blocked boolean NOT NULL DEFAULT false,
    next_fence bigint NOT NULL DEFAULT 0
);
-- Deliberately no cascade: deleting an enrollment/user cannot erase possible bills.
CREATE TABLE IF NOT EXISTS checklist_budget_reservations (
    operation_id uuid PRIMARY KEY,
    user_id text NOT NULL REFERENCES checklist_budget_accounts(user_id),
    enrollment_id text NOT NULL,
    input_hash text NOT NULL,
    fence bigint NOT NULL,
    state text NOT NULL CHECK (state IN ('prepared','started','unknown','settled','released')),
    held_usd numeric(18,10) NOT NULL DEFAULT .0764400000 CHECK (held_usd = .0764400000),
    held_tokens bigint NOT NULL DEFAULT 74576 CHECK (held_tokens = 74576),
    created_at timestamptz NOT NULL,
    dispatch_at timestamptz,
    expires_at timestamptz NOT NULL,
    receipt_id text NOT NULL UNIQUE,
    receipt jsonb,
    fingerprint text,
    reason text,
    cache_published boolean NOT NULL DEFAULT false,
    UNIQUE (user_id, fence)
);
CREATE UNIQUE INDEX IF NOT EXISTS checklist_budget_active_enrollment
    ON checklist_budget_reservations(enrollment_id) WHERE state IN ('prepared','started');
CREATE INDEX IF NOT EXISTS checklist_budget_holds ON checklist_budget_reservations(user_id, state);

CREATE OR REPLACE FUNCTION checklist_budget_admit(
    p_user_id text, p_enrollment_id text, p_input_hash text,
    p_operation_id uuid, p_receipt_id text, p_policy text,
    p_daily_usd numeric, p_monthly_usd numeric, p_daily_tokens bigint
) RETURNS jsonb LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
DECLARE
    a checklist_budget_accounts%ROWTYPE;
    r checklist_budget_reservations%ROWTYPE;
    t timestamptz;
    d timestamptz;
    m timestamptz;
    day_spend numeric; month_spend numeric; tokens bigint;
    day_holds numeric; month_holds numeric; token_holds bigint;
BEGIN
    IF p_user_id IS NULL OR length(p_user_id) NOT BETWEEN 1 AND 255
       OR p_input_hash !~ '^[0-9a-f]{64}$' OR p_operation_id IS NULL
       OR p_receipt_id IS NULL OR p_policy IS DISTINCT FROM 'flash-50k-3x8192-v1'
       OR p_input_hash IS NULL OR p_daily_usd IS NULL OR p_daily_usd <= 0
       OR p_monthly_usd IS NULL OR p_monthly_usd <= 0 OR p_daily_tokens IS NULL OR p_daily_tokens <= 0
       OR p_daily_usd::text IN ('NaN','Infinity','-Infinity') OR p_monthly_usd::text IN ('NaN','Infinity','-Infinity') THEN
        RAISE EXCEPTION 'Invalid checklist admission identity/policy';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM enrollments e JOIN course_offerings o ON o.id=e.offering_id
                   JOIN courses c ON c.id=o.course_id
                   WHERE e.id=p_enrollment_id AND e.user_id=p_user_id AND c.deleted_at IS NULL) THEN
        RETURN jsonb_build_object('status','ownership');
    END IF;
    INSERT INTO checklist_budget_accounts(user_id) VALUES(p_user_id) ON CONFLICT DO NOTHING;
    SELECT * INTO a FROM checklist_budget_accounts WHERE user_id=p_user_id FOR UPDATE;
    t := clock_timestamp();
    -- Workers may only tighten stored policy. A stale/looser worker cannot
    -- undo a lower cap; changing it upward requires an explicit DB policy edit.
    UPDATE checklist_budget_accounts SET daily_usd=least(daily_usd,p_daily_usd),
        monthly_usd=least(monthly_usd,p_monthly_usd),daily_tokens=least(daily_tokens,p_daily_tokens)
        WHERE user_id=p_user_id RETURNING * INTO a;
    -- Prepared leases may be released: start is a fenced compare-and-swap under
    -- this same mutex, so an expired prepared operation can never dispatch later.
    UPDATE checklist_budget_reservations SET state='released', reason='prepared_expired'
        WHERE user_id=p_user_id AND state='prepared' AND expires_at <= t;
    -- A started timeout is exposure, never a refund. It ceases to own the cache
    -- claim so a deliberate later refresh may reserve additional capacity.
    UPDATE checklist_budget_reservations SET state='unknown', reason='dispatch_outcome_unknown'
        WHERE user_id=p_user_id AND state='started' AND expires_at <= t;
    SELECT * INTO r FROM checklist_budget_reservations WHERE operation_id=p_operation_id;
    IF FOUND THEN
        IF r.user_id IS DISTINCT FROM p_user_id OR r.enrollment_id IS DISTINCT FROM p_enrollment_id
           OR r.input_hash IS DISTINCT FROM p_input_hash OR r.receipt_id IS DISTINCT FROM p_receipt_id THEN
            RETURN jsonb_build_object('status','conflict');
        END IF;
        RETURN jsonb_build_object('status','replay','reservation',to_jsonb(r));
    END IF;
    IF EXISTS (SELECT 1 FROM topic_checklists WHERE enrollment_id=p_enrollment_id AND input_hash=p_input_hash) THEN
        RETURN jsonb_build_object('status','cached');
    END IF;
    SELECT * INTO r FROM checklist_budget_reservations
        WHERE enrollment_id=p_enrollment_id AND state IN ('prepared','started');
    IF FOUND THEN RETURN jsonb_build_object('status','busy','reservation',to_jsonb(r)); END IF;
    IF a.blocked THEN RETURN jsonb_build_object('status','blocked'); END IF;
    d := date_trunc('day', t AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';
    m := date_trunc('month', t AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';
    -- Unknown legacy prices/negative or malformed counters cannot establish
    -- remaining headroom. No coalesce(NULL cost,0) financial fallback.
    IF EXISTS (SELECT 1 FROM llm_usage WHERE user_id=p_user_id AND created_at >= m
               AND (cost_usd IS NULL OR cost_usd < 0 OR cost_usd::text IN ('NaN','Infinity','-Infinity')
                    OR total_tokens IS NULL OR total_tokens < 0)) THEN
        RETURN jsonb_build_object('status','usage_unavailable');
    END IF;
    SELECT coalesce(sum(cost_usd) FILTER (WHERE created_at >= d),0), coalesce(sum(cost_usd),0),
           coalesce(sum(total_tokens) FILTER (WHERE created_at >= d AND
              coalesce(task,'') NOT IN ('decision_shadow','decision_jev_extra')),0)
        INTO day_spend, month_spend, tokens FROM llm_usage WHERE user_id=p_user_id AND created_at >= m;
    SELECT coalesce(sum(held_usd) FILTER (WHERE coalesce(dispatch_at,created_at) >= d),0),
           coalesce(sum(held_usd) FILTER (WHERE coalesce(dispatch_at,created_at) >= m),0),
           coalesce(sum(held_tokens) FILTER (WHERE coalesce(dispatch_at,created_at) >= d),0)
        INTO day_holds,month_holds,token_holds FROM checklist_budget_reservations
        WHERE user_id=p_user_id AND state IN ('prepared','started','unknown');
    IF day_spend + day_holds + .07644 > a.daily_usd
       OR month_spend + month_holds + .07644 > a.monthly_usd
       OR tokens + token_holds + 74576 > a.daily_tokens THEN
        RETURN jsonb_build_object('status','denied','retry_at', CASE
            WHEN month_spend + month_holds + .07644 > a.monthly_usd THEN m + interval '1 month'
            ELSE d + interval '1 day' END);
    END IF;
    UPDATE checklist_budget_accounts SET next_fence=next_fence+1 WHERE user_id=p_user_id RETURNING * INTO a;
    INSERT INTO checklist_budget_reservations(operation_id,user_id,enrollment_id,input_hash,fence,state,
        created_at,expires_at,receipt_id) VALUES(p_operation_id,p_user_id,p_enrollment_id,p_input_hash,
        a.next_fence,'prepared',t,t + interval '2 minutes',p_receipt_id) RETURNING * INTO r;
    RETURN jsonb_build_object('status','admitted','reservation',to_jsonb(r));
END $$;

CREATE OR REPLACE FUNCTION checklist_budget_start(p_user_id text,p_operation_id uuid,p_fence bigint)
RETURNS jsonb LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
DECLARE
    r checklist_budget_reservations%ROWTYPE;
    a checklist_budget_accounts%ROWTYPE;
    t timestamptz;
    d timestamptz;
    m timestamptz;
    ds numeric; ms numeric; ts bigint;
    dh numeric; mh numeric; th bigint;
BEGIN
    SELECT * INTO a FROM checklist_budget_accounts WHERE user_id=p_user_id FOR UPDATE;
    t := clock_timestamp();
    SELECT * INTO r FROM checklist_budget_reservations WHERE operation_id=p_operation_id AND user_id=p_user_id;
    IF NOT FOUND OR r.fence IS DISTINCT FROM p_fence THEN RETURN jsonb_build_object('status','conflict'); END IF;
    IF r.state <> 'prepared' OR r.expires_at <= t OR EXISTS (SELECT 1 FROM checklist_budget_accounts WHERE user_id=p_user_id AND blocked) THEN RETURN jsonb_build_object('status','not_started','reservation',to_jsonb(r)); END IF;
    IF NOT EXISTS (SELECT 1 FROM enrollments e JOIN course_offerings o ON o.id=e.offering_id
                   JOIN courses c ON c.id=o.course_id
                   WHERE e.id=r.enrollment_id AND e.user_id=p_user_id AND c.deleted_at IS NULL) THEN
        UPDATE checklist_budget_reservations SET state='released',reason='ownership_changed' WHERE operation_id=p_operation_id;
        RETURN jsonb_build_object('status','ownership');
    END IF;
    -- Do not move a prepared hold across UTC windows. Re-admit after midnight.
    IF (t AT TIME ZONE 'UTC')::date <> (r.created_at AT TIME ZONE 'UTC')::date THEN
        UPDATE checklist_budget_reservations SET state='released',reason='window_changed' WHERE operation_id=p_operation_id;
        RETURN jsonb_build_object('status','window_changed');
    END IF;
    d := date_trunc('day', t AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';
    m := date_trunc('month', t AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';
    IF EXISTS (SELECT 1 FROM llm_usage WHERE user_id=p_user_id AND created_at>=m
               AND (cost_usd IS NULL OR cost_usd<0 OR cost_usd::text IN ('NaN','Infinity','-Infinity')
                    OR total_tokens IS NULL OR total_tokens<0)) THEN
        UPDATE checklist_budget_reservations SET state='released',reason='usage_unavailable' WHERE operation_id=p_operation_id;
        RETURN jsonb_build_object('status','usage_unavailable');
    END IF;
    SELECT coalesce(sum(cost_usd) FILTER (WHERE created_at>=d),0),coalesce(sum(cost_usd),0),
           coalesce(sum(total_tokens) FILTER (WHERE created_at>=d AND
              coalesce(task,'') NOT IN ('decision_shadow','decision_jev_extra')),0)
        INTO ds,ms,ts FROM llm_usage WHERE user_id=p_user_id AND created_at>=m;
    SELECT coalesce(sum(held_usd) FILTER (WHERE coalesce(dispatch_at,created_at)>=d),0),
           coalesce(sum(held_usd) FILTER (WHERE coalesce(dispatch_at,created_at)>=m),0),
           coalesce(sum(held_tokens) FILTER (WHERE coalesce(dispatch_at,created_at)>=d),0)
        INTO dh,mh,th FROM checklist_budget_reservations WHERE user_id=p_user_id AND state IN ('prepared','started','unknown');
    -- This includes the already-reserved operation, not another new hold.
    IF ds+dh>a.daily_usd OR ms+mh>a.monthly_usd OR ts+th>a.daily_tokens THEN
        UPDATE checklist_budget_reservations SET state='released',reason='capacity_changed' WHERE operation_id=p_operation_id;
        RETURN jsonb_build_object('status','denied');
    END IF;
    UPDATE checklist_budget_reservations SET state='started', dispatch_at=t,
        expires_at=t+interval '2 minutes' WHERE operation_id=p_operation_id RETURNING * INTO r;
    -- Only this successful CAS authorizes one logical run. A replay NEVER grants
    -- dispatch; an ambiguous start acknowledgment must not launch a second call.
    RETURN jsonb_build_object('status','started','reservation',to_jsonb(r));
END $$;

CREATE OR REPLACE FUNCTION checklist_budget_read(p_user_id text,p_operation_id uuid)
RETURNS jsonb LANGUAGE sql STABLE SET search_path = public, pg_temp AS $$
    SELECT jsonb_build_object('status','found','reservation',to_jsonb(r))
    FROM checklist_budget_reservations r WHERE user_id=p_user_id AND operation_id=p_operation_id;
$$;

CREATE OR REPLACE FUNCTION checklist_budget_reconcile(
    p_user_id text,p_operation_id uuid,p_fence bigint,p_action text,
    p_receipt jsonb DEFAULT NULL,p_fingerprint text DEFAULT NULL,p_content text DEFAULT NULL
) RETURNS jsonb LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
DECLARE
    r checklist_budget_reservations%ROWTYPE;
    bill llm_usage%ROWTYPE;
    expected numeric;
    published boolean := false;
BEGIN
    PERFORM 1 FROM checklist_budget_accounts WHERE user_id=p_user_id FOR UPDATE;
    SELECT * INTO r FROM checklist_budget_reservations WHERE operation_id=p_operation_id AND user_id=p_user_id;
    IF NOT FOUND OR r.fence IS DISTINCT FROM p_fence THEN RETURN jsonb_build_object('status','conflict'); END IF;
    IF p_action='settle' THEN
        IF r.state='settled' THEN
            IF r.receipt IS DISTINCT FROM p_receipt OR r.fingerprint IS DISTINCT FROM p_fingerprint THEN
                RETURN jsonb_build_object('status','conflict');
            END IF;
            RETURN jsonb_build_object('status','settled','reservation',to_jsonb(r));
        END IF;
        IF r.state NOT IN ('started','unknown') OR p_receipt IS NULL
           OR p_fingerprint IS NULL OR p_fingerprint !~ '^[0-9a-f]{64}$' THEN RETURN jsonb_build_object('status','conflict'); END IF;
        bill := jsonb_populate_record(NULL::llm_usage,p_receipt);
        expected := round(((bill.prompt_tokens-coalesce(bill.cached_tokens,0)) * .0003
                    + coalesce(bill.cached_tokens,0) * .00003 + bill.completion_tokens * .0025)/1000,10);
        IF bill.id IS DISTINCT FROM r.receipt_id OR bill.user_id IS DISTINCT FROM p_user_id
           OR bill.feature IS DISTINCT FROM 'topic_checklist' OR bill.task IS DISTINCT FROM 'topic_checklist'
           OR bill.model IS DISTINCT FROM 'gemini-2.5-flash' OR bill.provider IS DISTINCT FROM 'gemini'
           OR bill.created_at IS DISTINCT FROM r.dispatch_at OR bill.session_id IS NOT NULL
           OR bill.prompt_tokens IS NULL OR bill.prompt_tokens <= 0 OR bill.completion_tokens IS NULL OR bill.completion_tokens <= 0
           OR bill.total_tokens IS DISTINCT FROM bill.prompt_tokens+bill.completion_tokens
           OR bill.cached_tokens IS NULL OR bill.cached_tokens < 0 OR bill.cached_tokens > bill.prompt_tokens
           OR bill.thinking_tokens IS NULL OR bill.thinking_tokens < 0 OR bill.thinking_tokens > bill.completion_tokens
           OR bill.cost_usd IS NULL OR bill.cost_usd::text IN ('NaN','Infinity','-Infinity')
           OR bill.cost_usd IS DISTINCT FROM expected OR expected <= 0
           OR p_receipt - ARRAY['id','user_id','request_id','feature','task','model','provider','prompt_tokens',
                'completion_tokens','total_tokens','cached_tokens','thinking_tokens','session_id','cost_usd','created_at'] <> '{}'::jsonb
        THEN RETURN jsonb_build_object('status','conflict'); END IF;
        -- Stable id plus exact content verification makes ambiguous insert ACKs
        -- safe to replay; NEVER additionally enqueue this checklist bill.
        INSERT INTO llm_usage(id,user_id,request_id,feature,task,model,provider,prompt_tokens,completion_tokens,
            total_tokens,cached_tokens,thinking_tokens,session_id,cost_usd,created_at)
        VALUES(bill.id,bill.user_id,bill.request_id,bill.feature,bill.task,bill.model,bill.provider,bill.prompt_tokens,
            bill.completion_tokens,bill.total_tokens,bill.cached_tokens,bill.thinking_tokens,bill.session_id,bill.cost_usd,bill.created_at)
        ON CONFLICT(id) DO NOTHING;
        IF NOT EXISTS (SELECT 1 FROM llm_usage u WHERE u.id=bill.id AND u.created_at=bill.created_at AND (to_jsonb(u)-'created_at') @> (p_receipt-'created_at')) THEN
            RAISE EXCEPTION 'Checklist receipt identity already has different content';
        END IF;
        IF bill.cost_usd > r.held_usd OR bill.total_tokens > r.held_tokens THEN
            UPDATE checklist_budget_accounts SET blocked=true WHERE user_id=p_user_id;
        END IF;
        -- A late old result may settle its bill but cannot overwrite a newer
        -- operation's cache, even when that newer operation failed/was released.
        IF p_content IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM checklist_budget_reservations n WHERE n.enrollment_id=r.enrollment_id AND (n.created_at>r.created_at OR (n.user_id=r.user_id AND n.fence>r.fence))
        ) AND EXISTS (SELECT 1 FROM enrollments e JOIN course_offerings o ON o.id=e.offering_id JOIN courses c ON c.id=o.course_id
                      WHERE e.id=r.enrollment_id AND e.user_id=p_user_id AND c.deleted_at IS NULL FOR SHARE OF e,o,c) THEN
            INSERT INTO topic_checklists(enrollment_id,input_hash,content,generated_at)
                VALUES(r.enrollment_id,r.input_hash,p_content,clock_timestamp())
                ON CONFLICT(enrollment_id) DO UPDATE SET input_hash=excluded.input_hash,content=excluded.content,generated_at=excluded.generated_at;
            published := true;
        END IF;
        UPDATE checklist_budget_reservations SET state='settled',receipt=p_receipt,fingerprint=p_fingerprint,
            cache_published=published,reason=NULL WHERE operation_id=p_operation_id RETURNING * INTO r;
        RETURN jsonb_build_object('status','settled','reservation',to_jsonb(r));
    ELSIF p_action='no_dispatch' AND r.state IN ('prepared','started','unknown') THEN
        -- Trusted backend proof: this process never entered the generation
        -- handler. Counter-only requests are not billed generation. A process
        -- crash cannot provide this proof, so its started hold remains unknown.
        -- p_content here is exclusively the explicit local FunctionModel seam
        -- in the trusted backend; it never creates a paid usage row.
        IF p_content IS NOT NULL AND r.state='prepared' AND NOT EXISTS (
            SELECT 1 FROM checklist_budget_reservations n WHERE n.enrollment_id=r.enrollment_id
            AND (n.created_at>r.created_at OR (n.user_id=r.user_id AND n.fence>r.fence))
        ) AND EXISTS (SELECT 1 FROM enrollments e JOIN course_offerings o ON o.id=e.offering_id JOIN courses c ON c.id=o.course_id
                      WHERE e.id=r.enrollment_id AND e.user_id=p_user_id AND c.deleted_at IS NULL FOR SHARE OF e,o,c) THEN
            INSERT INTO topic_checklists(enrollment_id,input_hash,content,generated_at)
                VALUES(r.enrollment_id,r.input_hash,p_content,clock_timestamp())
                ON CONFLICT(enrollment_id) DO UPDATE SET input_hash=excluded.input_hash,content=excluded.content,generated_at=excluded.generated_at;
            published := true;
        END IF;
        UPDATE checklist_budget_reservations SET state='released',cache_published=published,reason='no_generation_dispatched'
            WHERE operation_id=p_operation_id RETURNING * INTO r;
    ELSIF p_action='unknown' AND r.state IN ('started','unknown') THEN
        -- Preserve exclusivity until grace expiry; admission changes expired
        -- started -> unknown and retains the entire financial hold.
        UPDATE checklist_budget_reservations SET reason='dispatch_outcome_unknown'
            WHERE operation_id=p_operation_id RETURNING * INTO r;
    ELSIF p_action='no_dispatch' AND r.state='released' THEN NULL;
    ELSE RETURN jsonb_build_object('status','conflict');
    END IF;
    RETURN jsonb_build_object('status',r.state,'reservation',to_jsonb(r));
END $$;

ALTER TABLE checklist_budget_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE checklist_budget_reservations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE checklist_budget_accounts,checklist_budget_reservations FROM PUBLIC;
REVOKE ALL ON FUNCTION checklist_budget_admit(text,text,text,uuid,text,text,numeric,numeric,bigint), checklist_budget_start(text,uuid,bigint),
    checklist_budget_read(text,uuid), checklist_budget_reconcile(text,uuid,bigint,text,jsonb,text,text) FROM PUBLIC;
DO $$ DECLARE role_name text; BEGIN
    FOREACH role_name IN ARRAY ARRAY['anon','authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=role_name) THEN
            EXECUTE format('REVOKE ALL ON TABLE checklist_budget_accounts,checklist_budget_reservations FROM %I',role_name);
            EXECUTE format('REVOKE ALL ON FUNCTION checklist_budget_admit(text,text,text,uuid,text,text,numeric,numeric,bigint), checklist_budget_start(text,uuid,bigint), checklist_budget_read(text,uuid), checklist_budget_reconcile(text,uuid,bigint,text,jsonb,text,text) FROM %I',role_name);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN
        GRANT SELECT,INSERT,UPDATE ON TABLE checklist_budget_accounts,checklist_budget_reservations TO service_role;
        GRANT EXECUTE ON FUNCTION checklist_budget_admit(text,text,text,uuid,text,text,numeric,numeric,bigint), checklist_budget_start(text,uuid,bigint),
            checklist_budget_read(text,uuid), checklist_budget_reconcile(text,uuid,bigint,text,jsonb,text,text) TO service_role;
    END IF;
END $$;
NOTIFY pgrst, 'reload schema';

-- @@ unit 20261019131339_learning_evidence_transaction.sql
-- Atomic evidence: Python computes BKT/FSRS; SQL only validates,
-- checks optimistic snapshots under locks, and persists the complete plan.
-- Apply BEFORE deploying the tagged writer. No historical provenance backfill.
ALTER TABLE learner_state ADD COLUMN IF NOT EXISTS evidence_version bigint NOT NULL DEFAULT 0;
ALTER TABLE graph_nodes ADD COLUMN IF NOT EXISTS evidence_version bigint NOT NULL DEFAULT 0;

CREATE OR REPLACE FUNCTION learning_bump_evidence_version()
RETURNS trigger LANGUAGE plpgsql SET search_path=public,pg_temp AS $$
BEGIN
    NEW.evidence_version := OLD.evidence_version + 1;
    RETURN NEW;
END $$;
CREATE TRIGGER learner_state_evidence_version BEFORE UPDATE ON learner_state
    FOR EACH ROW EXECUTE FUNCTION learning_bump_evidence_version();
CREATE TRIGGER graph_nodes_evidence_version BEFORE UPDATE ON graph_nodes
    FOR EACH ROW EXECUTE FUNCTION learning_bump_evidence_version();

CREATE TABLE learning_evidence_operations (
    operation_id uuid PRIMARY KEY,
    user_id text NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    course_id text,
    input_fingerprint text NOT NULL CHECK(input_fingerprint ~ '^[0-9a-f]{64}$'),
    plan jsonb NOT NULL CHECK(jsonb_typeof(plan)='object'),
    changes jsonb NOT NULL CHECK(jsonb_typeof(changes)='array'),
    committed_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
ALTER TABLE learning_evidence_operations ENABLE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION learning_evidence_receipt(p_user_id text,p_operation_id uuid)
RETURNS jsonb LANGUAGE plpgsql SET search_path=public,pg_temp
SET lock_timeout='2s' SET statement_timeout='10s' AS $$
DECLARE r learning_evidence_operations%ROWTYPE;
BEGIN
    IF p_user_id IS NULL OR p_user_id='' OR p_operation_id IS NULL THEN
        RAISE EXCEPTION 'Invalid evidence operation identity';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('learning-evidence:'||p_user_id,0));
    SELECT * INTO r FROM learning_evidence_operations WHERE operation_id=p_operation_id;
    IF NOT FOUND THEN RETURN jsonb_build_object('status','missing'); END IF;
    IF r.user_id IS DISTINCT FROM p_user_id THEN RETURN jsonb_build_object('status','conflict'); END IF;
    RETURN jsonb_build_object('status','committed','receipt',jsonb_build_object(
        'operation_id',r.operation_id,'user_id',r.user_id,'course_id',r.course_id,
        'input_fingerprint',r.input_fingerprint,'changes',r.changes,'posteriors',(
            SELECT jsonb_object_agg(value->>'id',value->'mastery_score') FROM jsonb_array_elements(r.plan->'mirrors'))));
END $$;

CREATE OR REPLACE FUNCTION learning_evidence_snapshot(
    p_user_id text,p_course_id text,p_node_ids text[],p_checks jsonb
) RETURNS jsonb LANGUAGE plpgsql SET search_path=public,pg_temp
SET lock_timeout='2s' SET statement_timeout='10s' AS $$
DECLARE ids text[]; ns jsonb; ss jsonb; es jsonb; cs jsonb;
BEGIN
    IF p_user_id IS NULL OR p_user_id='' OR coalesce(cardinality(p_node_ids),0)=0
       OR jsonb_typeof(p_checks) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'Invalid evidence snapshot identity';
    END IF;
    IF (SELECT count(*) FROM graph_nodes n WHERE n.id=ANY(p_node_ids)
        AND n.user_id=p_user_id AND (p_course_id IS NULL OR n.course_id=p_course_id))
        <> cardinality(p_node_ids) THEN RETURN jsonb_build_object('status','ownership'); END IF;
    -- Prerequisite propagation is course-local, including when no course was
    -- explicitly supplied. Foreign-user/course edges cannot introduce targets.
    SELECT coalesce(jsonb_agg(jsonb_build_object('source',e.source_node_id,'target',e.target_node_id)
               ORDER BY e.source_node_id,e.target_node_id),'[]') INTO es
      FROM graph_edges e JOIN graph_nodes s ON s.id=e.source_node_id
      JOIN graph_nodes t ON t.id=e.target_node_id
      WHERE e.user_id=p_user_id AND e.relationship_type='prerequisite'
        AND s.user_id=p_user_id AND t.user_id=p_user_id
        AND s.course_id IS NOT DISTINCT FROM t.course_id
        AND (p_course_id IS NULL OR s.course_id=p_course_id)
        AND (e.source_node_id=ANY(p_node_ids) OR e.target_node_id=ANY(p_node_ids));
    SELECT array_agg(DISTINCT id ORDER BY id) INTO ids FROM (
        SELECT unnest(p_node_ids) AS id UNION
        SELECT value->>'source' FROM jsonb_array_elements(es) UNION
        SELECT value->>'target' FROM jsonb_array_elements(es)) q;
    SELECT jsonb_agg(jsonb_build_object('id',n.id,'user_id',n.user_id,'course_id',n.course_id,
        'concept_name',n.concept_name,'mastery_score',n.mastery_score,'times_studied',n.times_studied,
        'evidence_version',n.evidence_version) ORDER BY n.id) INTO ns
        FROM graph_nodes n WHERE n.id=ANY(ids);
    SELECT coalesce(jsonb_agg(to_jsonb(s) ORDER BY s.node_id),'[]') INTO ss
        FROM learner_state s WHERE s.user_id=p_user_id AND s.node_id=ANY(ids);
    SELECT coalesce(jsonb_agg(jsonb_build_object('session_id',c.value->>'session_id',
        'question_hash',c.value->>'question_hash','count',(
            SELECT count(*) FROM node_mastery_events e JOIN graph_nodes n ON n.id=e.node_id
            WHERE n.user_id=p_user_id AND e.event_type='evidence'
              AND e.session_id=c.value->>'session_id' AND e.question_hash=c.value->>'question_hash'))
        ORDER BY c.value->>'session_id',c.value->>'question_hash'),'[]') INTO cs
        FROM jsonb_array_elements(p_checks) c;
    RETURN jsonb_build_object('status','snapshot','nodes',ns,'states',ss,'edges',es,'checks',cs);
END $$;

CREATE OR REPLACE FUNCTION learning_evidence_commit(
    p_user_id text,p_course_id text,p_operation_id uuid,p_input_fingerprint text,p_plan jsonb
) RETURNS jsonb LANGUAGE plpgsql SET search_path=public,pg_temp
SET lock_timeout='2s' SET statement_timeout='10s' AS $$
DECLARE r learning_evidence_operations%ROWTYPE; x jsonb; v bigint; ids text[];
    grade_ids text[]; es jsonb; n graph_nodes%ROWTYPE; s learner_state%ROWTYPE;
    ev node_mastery_events%ROWTYPE; obs jsonb; expected_count bigint; actual_count bigint;
BEGIN
    IF p_user_id IS NULL OR p_user_id='' OR p_operation_id IS NULL
       OR p_input_fingerprint IS NULL OR p_input_fingerprint !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(p_plan) IS DISTINCT FROM 'object'
       OR (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(p_plan) k)
          IS DISTINCT FROM ARRAY['changes','checks','edges','events','mirrors','nodes','observed_at','state_rows','states_expected']::text[]
       OR EXISTS(SELECT 1 FROM jsonb_each(p_plan) p WHERE p.key<>'observed_at' AND jsonb_typeof(p.value)<>'array')
       OR jsonb_typeof(p_plan->'observed_at') NOT IN ('null','string') THEN
        RAISE EXCEPTION 'Invalid evidence transaction envelope';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('learning-evidence:'||p_user_id,0));
    SELECT * INTO r FROM learning_evidence_operations WHERE operation_id=p_operation_id;
    IF FOUND THEN
        IF r.user_id IS DISTINCT FROM p_user_id OR r.course_id IS DISTINCT FROM p_course_id
           OR r.input_fingerprint IS DISTINCT FROM p_input_fingerprint OR r.plan IS DISTINCT FROM p_plan THEN
            RETURN jsonb_build_object('status','conflict');
        END IF;
        RETURN jsonb_build_object('status','replay','receipt',jsonb_build_object(
            'operation_id',r.operation_id,'user_id',r.user_id,'course_id',r.course_id,
            'input_fingerprint',r.input_fingerprint,'changes',r.changes,'posteriors',(
                SELECT jsonb_object_agg(value->>'id',value->'mastery_score') FROM jsonb_array_elements(r.plan->'mirrors'))));
    END IF;
    SELECT array_agg(value->>'id' ORDER BY value->>'id') INTO ids FROM jsonb_array_elements(p_plan->'nodes');
    SELECT array_agg(DISTINCT value->>'node_id' ORDER BY value->>'node_id') INTO grade_ids
        FROM jsonb_array_elements(p_plan->'events');
    IF coalesce(cardinality(ids),0)=0 OR coalesce(cardinality(grade_ids),0)=0
       OR cardinality(ids)<>(SELECT count(DISTINCT unnest) FROM unnest(ids))
       OR jsonb_array_length(p_plan->'changes')<>jsonb_array_length(p_plan->'events') THEN
        RAISE EXCEPTION 'Invalid evidence transaction members';
    END IF;
    -- Short, bounded coarse lock closes phantom edge inserts AND relation/
    -- endpoint edits/deletes from legacy writers. Acquire it before node locks
    -- so a legacy edge FK check cannot form a node/table lock-order inversion.
    LOCK TABLE graph_edges IN SHARE MODE;
    PERFORM 1 FROM graph_nodes WHERE id=ANY(ids) ORDER BY id FOR UPDATE;
    IF (SELECT count(*) FROM graph_nodes WHERE id=ANY(ids) AND user_id=p_user_id
        AND (p_course_id IS NULL OR course_id=p_course_id))<>cardinality(ids) THEN
        RETURN jsonb_build_object('status','ownership');
    END IF;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'nodes') LOOP
        IF jsonb_typeof(x->'version') IS DISTINCT FROM 'number' OR (x->>'version') !~ '^[0-9]+$' THEN
            RAISE EXCEPTION 'Invalid graph version';
        END IF;
        SELECT evidence_version INTO v FROM graph_nodes WHERE id=x->>'id';
        IF v IS DISTINCT FROM (x->>'version')::bigint THEN RETURN jsonb_build_object('status','stale'); END IF;
    END LOOP;
    SELECT coalesce(jsonb_agg(jsonb_build_object('source',e.source_node_id,'target',e.target_node_id)
               ORDER BY e.source_node_id,e.target_node_id),'[]') INTO es
      FROM graph_edges e JOIN graph_nodes a ON a.id=e.source_node_id JOIN graph_nodes b ON b.id=e.target_node_id
      WHERE e.user_id=p_user_id AND e.relationship_type='prerequisite'
        AND a.user_id=p_user_id AND b.user_id=p_user_id AND a.course_id IS NOT DISTINCT FROM b.course_id
        AND (p_course_id IS NULL OR a.course_id=p_course_id)
        AND (e.source_node_id=ANY(grade_ids) OR e.target_node_id=ANY(grade_ids));
    IF es IS DISTINCT FROM p_plan->'edges' THEN RETURN jsonb_build_object('status','stale'); END IF;
    PERFORM 1 FROM learner_state WHERE user_id=p_user_id AND node_id=ANY(ids) ORDER BY node_id FOR UPDATE;
    IF jsonb_array_length(p_plan->'states_expected')<>cardinality(ids)
       OR (SELECT count(DISTINCT value->>'node_id') FROM jsonb_array_elements(p_plan->'states_expected'))<>cardinality(ids)
       OR EXISTS(SELECT 1 FROM jsonb_array_elements(p_plan->'states_expected') WHERE NOT (value->>'node_id'=ANY(ids))) THEN
        RAISE EXCEPTION 'Invalid learner-state snapshot';
    END IF;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'states_expected') LOOP
        IF jsonb_typeof(x->'version') NOT IN ('number','null')
           OR (x->>'version' IS NOT NULL AND (x->>'version') !~ '^[0-9]+$') THEN
            RAISE EXCEPTION 'Invalid learner-state version';
        END IF;
        SELECT evidence_version INTO v FROM learner_state WHERE user_id=p_user_id AND node_id=x->>'node_id';
        IF v IS DISTINCT FROM (x->>'version')::bigint THEN RETURN jsonb_build_object('status','stale'); END IF;
    END LOOP;
    IF p_plan->>'observed_at' IS NOT NULL AND EXISTS(
        SELECT 1 FROM learner_state l WHERE l.user_id=p_user_id
        AND l.node_id IN (SELECT value->>'node_id' FROM jsonb_array_elements(p_plan->'state_rows'))
        AND l.last_evidence_at > (p_plan->>'observed_at')::timestamptz
    ) THEN RETURN jsonb_build_object('status','superseded'); END IF;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'checks') LOOP
        SELECT count(*) INTO actual_count FROM node_mastery_events e JOIN graph_nodes g ON g.id=e.node_id
            WHERE g.user_id=p_user_id AND e.event_type='evidence' AND e.session_id=x->>'session_id'
              AND e.question_hash=x->>'question_hash';
        IF actual_count IS DISTINCT FROM (x->>'count')::bigint THEN RETURN jsonb_build_object('status','stale'); END IF;
    END LOOP;
    IF jsonb_array_length(p_plan->'state_rows')=0
       OR jsonb_array_length(p_plan->'state_rows')<>jsonb_array_length(p_plan->'mirrors')
       OR (SELECT count(DISTINCT value->>'node_id') FROM jsonb_array_elements(p_plan->'state_rows'))<>jsonb_array_length(p_plan->'state_rows')
       OR (SELECT count(DISTINCT value->>'id') FROM jsonb_array_elements(p_plan->'mirrors'))<>jsonb_array_length(p_plan->'mirrors')
       OR EXISTS(SELECT 1 FROM unnest(grade_ids) id WHERE NOT EXISTS(
            SELECT 1 FROM jsonb_array_elements(p_plan->'state_rows') s WHERE s->>'node_id'=id)) THEN
        RAISE EXCEPTION 'Invalid transaction row sets';
    END IF;
    -- Validate the WHOLE plan before its first mutation. SQL does no BKT,
    -- FSRS, weighting, threshold or propagation arithmetic.
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'state_rows') LOOP
        s := jsonb_populate_record(NULL::learner_state,x);
        IF s.user_id IS DISTINCT FROM p_user_id OR NOT(s.node_id=ANY(ids))
           OR s.p_known IS NULL OR NOT(s.p_known BETWEEN 0 AND 1)
           OR s.n_strong_unassisted<0 OR s.streak_unassisted<0 OR s.max_streak_unassisted<0 OR s.opps<0
           OR EXISTS(SELECT 1 FROM jsonb_object_keys(x) k WHERE k NOT IN (
                'user_id','node_id','p_known','n_strong_unassisted','streak_unassisted','max_streak_unassisted','opps',
                'fsrs_d','fsrs_s','fsrs_last_review_at','fsrs_due_at','last_evidence_at','updated_at'))
           OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_plan->'mirrors') m WHERE m->>'id'=s.node_id) THEN
            RAISE EXCEPTION 'Invalid transaction learner state';
        END IF;
    END LOOP;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'events') LOOP
        ev := jsonb_populate_record(NULL::node_mastery_events,x);
        IF ev.id IS NULL OR NOT(ev.node_id=ANY(grade_ids)) OR NOT(ev.node_id=ANY(ids))
           OR ev.event_type IS DISTINCT FROM 'evidence' OR ev.correct IS NULL
           OR ev.p_before IS NULL OR NOT(ev.p_before BETWEEN 0 AND 1)
           OR ev.p_after IS NULL OR NOT(ev.p_after BETWEEN 0 AND 1)
           OR ev.weight IS NULL OR NOT(ev.weight BETWEEN 0 AND 1)
           OR ev.created_at IS NULL OR ev.evidence_seq IS NULL OR ev.evidence_seq<0
           OR jsonb_typeof(x->'correct') IS DISTINCT FROM 'boolean'
           OR jsonb_typeof(x->'assisted') IS DISTINCT FROM 'boolean'
           OR EXISTS(SELECT 1 FROM jsonb_object_keys(x) k WHERE k NOT IN (
                'id','node_id','delta','reason','created_at','event_type','channel','correct','weight','assisted','max_rung',
                'p_before','p_after','session_id','check_item_id','question_hash','confidence','grader_backend','evidence_seq','planning_observation')) THEN
            RAISE EXCEPTION 'Invalid transaction evidence';
        END IF;
        obs := ev.planning_observation;
        IF obs IS NOT NULL AND (
            jsonb_typeof(obs) IS DISTINCT FROM 'object'
            OR obs->>'node_id' IS DISTINCT FROM ev.node_id OR obs->>'question_hash' IS DISTINCT FROM ev.question_hash
            OR obs->>'check_item_id' IS DISTINCT FROM ev.check_item_id OR obs->>'channel' IS DISTINCT FROM ev.channel
            OR obs->'correct' IS DISTINCT FROM to_jsonb(ev.correct)
            OR obs->'assisted' IS DISTINCT FROM to_jsonb(ev.assisted)
            OR obs->'max_rung' IS DISTINCT FROM to_jsonb(ev.max_rung)
            OR jsonb_typeof(obs->'independent') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'same_session_recheck') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'idk') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'synthetic_idk') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'previously_seen') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'difficulty') IS DISTINCT FROM 'number'
            OR (obs->>'difficulty') NOT IN ('1','2','3')
            OR NOT(obs ?& ARRAY['check_item_id','difficulty','synthetic_idk','previously_seen','node_id',
                'question_hash','channel','correct','idk','assisted','max_rung','same_session_recheck','independent'])
            OR EXISTS(SELECT 1 FROM jsonb_object_keys(obs) k WHERE k NOT IN (
                'check_item_id','difficulty','synthetic_idk','previously_seen','node_id','question_hash',
                'channel','correct','idk','assisted','max_rung','same_session_recheck','independent'))
            OR (obs->>'idk')::boolean AND ev.correct
            OR (obs->>'synthetic_idk')::boolean AND NOT (obs->>'idk')::boolean
            OR ev.assisted IS DISTINCT FROM (ev.max_rung>0)
            OR (obs->>'independent')::boolean IS DISTINCT FROM (NOT (
                ev.max_rung>0 OR ev.assisted OR (obs->>'same_session_recheck')::boolean
                OR (obs->>'synthetic_idk')::boolean OR (obs->>'previously_seen')::boolean))) THEN
            RAISE EXCEPTION 'Invalid final planning provenance';
        END IF;
    END LOOP;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'state_rows') LOOP
        s := jsonb_populate_record(NULL::learner_state,x);
        INSERT INTO learner_state(user_id,node_id,p_known,n_strong_unassisted,streak_unassisted,max_streak_unassisted,
            opps,fsrs_d,fsrs_s,fsrs_last_review_at,fsrs_due_at,last_evidence_at,updated_at)
        VALUES(s.user_id,s.node_id,s.p_known,s.n_strong_unassisted,s.streak_unassisted,s.max_streak_unassisted,
            s.opps,s.fsrs_d,s.fsrs_s,s.fsrs_last_review_at,s.fsrs_due_at,s.last_evidence_at,s.updated_at)
        ON CONFLICT(user_id,node_id) DO UPDATE SET p_known=EXCLUDED.p_known,n_strong_unassisted=EXCLUDED.n_strong_unassisted,
            streak_unassisted=EXCLUDED.streak_unassisted,max_streak_unassisted=EXCLUDED.max_streak_unassisted,
            opps=EXCLUDED.opps,fsrs_d=EXCLUDED.fsrs_d,fsrs_s=EXCLUDED.fsrs_s,
            fsrs_last_review_at=EXCLUDED.fsrs_last_review_at,fsrs_due_at=EXCLUDED.fsrs_due_at,
            last_evidence_at=EXCLUDED.last_evidence_at,updated_at=EXCLUDED.updated_at;
    END LOOP;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'mirrors') LOOP
        IF NOT(x->>'id'=ANY(ids)) OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_plan->'state_rows') t WHERE t->>'node_id'=x->>'id')
           OR jsonb_typeof(x->'mastery_score') IS DISTINCT FROM 'number'
           OR NOT((x->>'mastery_score')::double precision BETWEEN 0 AND 1)
           OR EXISTS(SELECT 1 FROM jsonb_object_keys(x) k WHERE k NOT IN ('id','mastery_score','mastery_tier','times_studied','last_studied_at')) THEN
            RAISE EXCEPTION 'Invalid transaction mirror';
        END IF;
        UPDATE graph_nodes SET mastery_score=(x->>'mastery_score')::double precision,mastery_tier=x->>'mastery_tier',
            times_studied=CASE WHEN x ? 'times_studied' THEN (x->>'times_studied')::int ELSE times_studied END,
            last_studied_at=CASE WHEN x ? 'last_studied_at' THEN (x->>'last_studied_at')::timestamptz ELSE last_studied_at END
            WHERE id=x->>'id' AND user_id=p_user_id;
    END LOOP;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'events') LOOP
        ev := jsonb_populate_record(NULL::node_mastery_events,x);
        INSERT INTO node_mastery_events(id,node_id,delta,reason,created_at,event_type,channel,correct,weight,assisted,max_rung,
            p_before,p_after,session_id,check_item_id,question_hash,confidence,grader_backend,evidence_seq,planning_observation)
        VALUES(ev.id,ev.node_id,ev.delta,ev.reason,ev.created_at,ev.event_type,ev.channel,ev.correct,ev.weight,ev.assisted,ev.max_rung,
            ev.p_before,ev.p_after,ev.session_id,ev.check_item_id,ev.question_hash,ev.confidence,ev.grader_backend,ev.evidence_seq,ev.planning_observation);
    END LOOP;
    INSERT INTO learning_evidence_operations(operation_id,user_id,course_id,input_fingerprint,plan,changes)
        VALUES(p_operation_id,p_user_id,p_course_id,p_input_fingerprint,p_plan,p_plan->'changes');
    RETURN learning_evidence_receipt(p_user_id,p_operation_id);
END $$;

REVOKE ALL ON TABLE learning_evidence_operations FROM PUBLIC;
REVOKE ALL ON FUNCTION learning_evidence_receipt(text,uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION learning_evidence_snapshot(text,text,text[],jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION learning_evidence_commit(text,text,uuid,text,jsonb) FROM PUBLIC;
DO $$ DECLARE r text; BEGIN
    FOREACH r IN ARRAY ARRAY['anon','authenticated'] LOOP
        IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=r) THEN
            EXECUTE format('REVOKE ALL ON TABLE learning_evidence_operations FROM %I',r);
            EXECUTE format('REVOKE ALL ON FUNCTION learning_evidence_receipt(text,uuid) FROM %I',r);
            EXECUTE format('REVOKE ALL ON FUNCTION learning_evidence_snapshot(text,text,text[],jsonb) FROM %I',r);
            EXECUTE format('REVOKE ALL ON FUNCTION learning_evidence_commit(text,text,uuid,text,jsonb) FROM %I',r);
        END IF;
    END LOOP;
    IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN
        GRANT ALL ON TABLE learning_evidence_operations TO service_role;
        GRANT EXECUTE ON FUNCTION learning_evidence_receipt(text,uuid),learning_evidence_snapshot(text,text,text[],jsonb),
            learning_evidence_commit(text,text,uuid,text,jsonb) TO service_role;
    END IF;
END $$;
NOTIFY pgrst,'reload schema';

-- @@ unit 20261019141950_learning_evidence_forward_repair.sql
-- Forward repair of the immutable original Evidence transaction migration.
-- Apply all migrations before deploying receipt/checkpoint consumers. No backfill.
-- Derived metric timestamps are not evidence: preserve legacy NULL causality.
ALTER TABLE learner_state ADD COLUMN IF NOT EXISTS evidence_touch_at timestamptz;

CREATE OR REPLACE FUNCTION learning_evidence_receipt(p_user_id text,p_operation_id uuid)
RETURNS jsonb LANGUAGE plpgsql SET search_path=public,pg_temp
SET lock_timeout='2s' SET statement_timeout='10s' AS $$
DECLARE r learning_evidence_operations%ROWTYPE;
BEGIN
    IF p_user_id IS NULL OR p_user_id='' OR p_operation_id IS NULL THEN
        RAISE EXCEPTION 'Invalid evidence operation identity';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('learning-evidence:'||p_user_id,0));
    SELECT * INTO r FROM learning_evidence_operations WHERE operation_id=p_operation_id;
    IF NOT FOUND THEN RETURN jsonb_build_object('status','missing'); END IF;
    IF r.user_id IS DISTINCT FROM p_user_id THEN RETURN jsonb_build_object('status','conflict'); END IF;
    RETURN jsonb_build_object('status','committed','receipt',jsonb_build_object(
        'operation_id',r.operation_id,'user_id',r.user_id,'course_id',r.course_id,
        'input_fingerprint',r.input_fingerprint,'changes',r.changes,'posteriors',(
            SELECT jsonb_object_agg(value->>'id',value->'mastery_score') FROM jsonb_array_elements(r.plan->'mirrors')),
        'observations',(SELECT coalesce(jsonb_agg(entry.value->'planning_observation' ORDER BY entry.position),'[]')
            FROM jsonb_array_elements(r.plan->'events') WITH ORDINALITY entry(value,position)
            WHERE jsonb_typeof(entry.value->'planning_observation')='object')));
END $$;

CREATE OR REPLACE FUNCTION learning_evidence_snapshot(
    p_user_id text,p_course_id text,p_node_ids text[],p_checks jsonb
) RETURNS jsonb LANGUAGE plpgsql SET search_path=public,pg_temp
SET lock_timeout='2s' SET statement_timeout='10s' AS $$
DECLARE ids text[]; ns jsonb; ss jsonb; es jsonb; cs jsonb;
BEGIN
    IF p_user_id IS NULL OR p_user_id='' OR coalesce(cardinality(p_node_ids),0)=0
       OR jsonb_typeof(p_checks) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'Invalid evidence snapshot identity';
    END IF;
    IF (SELECT count(*) FROM graph_nodes n WHERE n.id=ANY(p_node_ids)
        AND n.user_id=p_user_id AND (p_course_id IS NULL OR n.course_id=p_course_id))
        <> cardinality(p_node_ids) THEN RETURN jsonb_build_object('status','ownership'); END IF;
    -- Prerequisite propagation is course-local, including when no course was
    -- explicitly supplied. Foreign-user/course edges cannot introduce targets.
    SELECT coalesce(jsonb_agg(jsonb_build_object('source',e.source_node_id,'target',e.target_node_id)
               ORDER BY e.source_node_id,e.target_node_id),'[]') INTO es
      FROM graph_edges e JOIN graph_nodes s ON s.id=e.source_node_id
      JOIN graph_nodes t ON t.id=e.target_node_id
      WHERE e.user_id=p_user_id AND e.relationship_type='prerequisite'
        AND s.user_id=p_user_id AND t.user_id=p_user_id
        AND s.course_id IS NOT DISTINCT FROM t.course_id
        AND (p_course_id IS NULL OR s.course_id=p_course_id)
        AND (e.source_node_id=ANY(p_node_ids) OR e.target_node_id=ANY(p_node_ids));
    SELECT array_agg(DISTINCT id ORDER BY id) INTO ids FROM (
        SELECT unnest(p_node_ids) AS id UNION
        SELECT value->>'source' FROM jsonb_array_elements(es) UNION
        SELECT value->>'target' FROM jsonb_array_elements(es)) q;
    SELECT jsonb_agg(jsonb_build_object('id',n.id,'user_id',n.user_id,'course_id',n.course_id,
        'concept_name',n.concept_name,'mastery_score',n.mastery_score,'times_studied',n.times_studied,
        'evidence_version',n.evidence_version) ORDER BY n.id) INTO ns
        FROM graph_nodes n WHERE n.id=ANY(ids);
    SELECT coalesce(jsonb_agg(to_jsonb(s) ORDER BY s.node_id),'[]') INTO ss
        FROM learner_state s WHERE s.user_id=p_user_id AND s.node_id=ANY(ids);
    SELECT coalesce(jsonb_agg(jsonb_build_object('session_id',c.value->>'session_id',
        'question_hash',c.value->>'question_hash','count',(
            SELECT count(*) FROM node_mastery_events e JOIN graph_nodes n ON n.id=e.node_id
            WHERE n.user_id=p_user_id AND e.event_type='evidence'
              AND e.session_id=c.value->>'session_id' AND e.question_hash=c.value->>'question_hash'),
        'global_count',(SELECT count(*) FROM node_mastery_events e JOIN graph_nodes n ON n.id=e.node_id
            WHERE n.user_id=p_user_id AND e.event_type='evidence'
              AND e.question_hash=c.value->>'question_hash'))
        ORDER BY c.value->>'session_id',c.value->>'question_hash'),'[]') INTO cs
        FROM jsonb_array_elements(p_checks) c;
    RETURN jsonb_build_object('status','snapshot','nodes',ns,'states',ss,'edges',es,'checks',cs);
END $$;

CREATE OR REPLACE FUNCTION learning_evidence_commit(
    p_user_id text,p_course_id text,p_operation_id uuid,p_input_fingerprint text,p_plan jsonb
) RETURNS jsonb LANGUAGE plpgsql SET search_path=public,pg_temp
SET lock_timeout='2s' SET statement_timeout='10s' AS $$
DECLARE r learning_evidence_operations%ROWTYPE; x jsonb; v bigint; ids text[];
    grade_ids text[]; es jsonb; n graph_nodes%ROWTYPE; s learner_state%ROWTYPE;
    ev node_mastery_events%ROWTYPE; obs jsonb; expected_count bigint; actual_count bigint;
BEGIN
    IF p_user_id IS NULL OR p_user_id='' OR p_operation_id IS NULL
       OR p_input_fingerprint IS NULL OR p_input_fingerprint !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(p_plan) IS DISTINCT FROM 'object'
       OR (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(p_plan) k)
          IS DISTINCT FROM ARRAY['changes','checks','edges','events','mirrors','nodes','observed_at','state_rows','states_expected']::text[]
       OR EXISTS(SELECT 1 FROM jsonb_each(p_plan) p WHERE p.key<>'observed_at' AND jsonb_typeof(p.value)<>'array')
       OR jsonb_typeof(p_plan->'observed_at') NOT IN ('null','string') THEN
        RAISE EXCEPTION 'Invalid evidence transaction envelope';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('learning-evidence:'||p_user_id,0));
    SELECT * INTO r FROM learning_evidence_operations WHERE operation_id=p_operation_id;
    IF FOUND THEN
        IF r.user_id IS DISTINCT FROM p_user_id OR r.course_id IS DISTINCT FROM p_course_id
           OR r.input_fingerprint IS DISTINCT FROM p_input_fingerprint OR r.plan IS DISTINCT FROM p_plan THEN
            RETURN jsonb_build_object('status','conflict');
        END IF;
        RETURN jsonb_build_object('status','replay','receipt',jsonb_build_object(
            'operation_id',r.operation_id,'user_id',r.user_id,'course_id',r.course_id,
            'input_fingerprint',r.input_fingerprint,'changes',r.changes,'posteriors',(
                SELECT jsonb_object_agg(value->>'id',value->'mastery_score') FROM jsonb_array_elements(r.plan->'mirrors')),
            'observations',(SELECT coalesce(jsonb_agg(entry.value->'planning_observation' ORDER BY entry.position),'[]')
                FROM jsonb_array_elements(r.plan->'events') WITH ORDINALITY entry(value,position)
                WHERE jsonb_typeof(entry.value->'planning_observation')='object')));
    END IF;
    SELECT array_agg(value->>'id' ORDER BY value->>'id') INTO ids FROM jsonb_array_elements(p_plan->'nodes');
    SELECT array_agg(DISTINCT value->>'node_id' ORDER BY value->>'node_id') INTO grade_ids
        FROM jsonb_array_elements(p_plan->'events');
    IF coalesce(cardinality(ids),0)=0 OR coalesce(cardinality(grade_ids),0)=0
       OR cardinality(ids)<>(SELECT count(DISTINCT unnest) FROM unnest(ids))
       OR jsonb_array_length(p_plan->'changes')<>jsonb_array_length(p_plan->'events') THEN
        RAISE EXCEPTION 'Invalid evidence transaction members';
    END IF;
    -- Short, bounded coarse lock closes phantom edge inserts AND relation/
    -- endpoint edits/deletes from legacy writers. Acquire it before node locks
    -- so a legacy edge FK check cannot form a node/table lock-order inversion.
    LOCK TABLE graph_edges IN SHARE MODE;
    PERFORM 1 FROM graph_nodes WHERE id=ANY(ids) ORDER BY id FOR UPDATE;
    IF (SELECT count(*) FROM graph_nodes WHERE id=ANY(ids) AND user_id=p_user_id
        AND (p_course_id IS NULL OR course_id=p_course_id))<>cardinality(ids) THEN
        RETURN jsonb_build_object('status','ownership');
    END IF;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'nodes') LOOP
        IF jsonb_typeof(x->'version') IS DISTINCT FROM 'number' OR (x->>'version') !~ '^[0-9]+$' THEN
            RAISE EXCEPTION 'Invalid graph version';
        END IF;
        SELECT evidence_version INTO v FROM graph_nodes WHERE id=x->>'id';
        IF v IS DISTINCT FROM (x->>'version')::bigint THEN RETURN jsonb_build_object('status','stale'); END IF;
    END LOOP;
    SELECT coalesce(jsonb_agg(jsonb_build_object('source',e.source_node_id,'target',e.target_node_id)
               ORDER BY e.source_node_id,e.target_node_id),'[]') INTO es
      FROM graph_edges e JOIN graph_nodes a ON a.id=e.source_node_id JOIN graph_nodes b ON b.id=e.target_node_id
      WHERE e.user_id=p_user_id AND e.relationship_type='prerequisite'
        AND a.user_id=p_user_id AND b.user_id=p_user_id AND a.course_id IS NOT DISTINCT FROM b.course_id
        AND (p_course_id IS NULL OR a.course_id=p_course_id)
        AND (e.source_node_id=ANY(grade_ids) OR e.target_node_id=ANY(grade_ids));
    IF es IS DISTINCT FROM p_plan->'edges' THEN RETURN jsonb_build_object('status','stale'); END IF;
    PERFORM 1 FROM learner_state WHERE user_id=p_user_id AND node_id=ANY(ids) ORDER BY node_id FOR UPDATE;
    IF jsonb_array_length(p_plan->'states_expected')<>cardinality(ids)
       OR (SELECT count(DISTINCT value->>'node_id') FROM jsonb_array_elements(p_plan->'states_expected'))<>cardinality(ids)
       OR EXISTS(SELECT 1 FROM jsonb_array_elements(p_plan->'states_expected') WHERE NOT (value->>'node_id'=ANY(ids))) THEN
        RAISE EXCEPTION 'Invalid learner-state snapshot';
    END IF;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'states_expected') LOOP
        IF jsonb_typeof(x->'version') NOT IN ('number','null')
           OR (x->>'version' IS NOT NULL AND (x->>'version') !~ '^[0-9]+$') THEN
            RAISE EXCEPTION 'Invalid learner-state version';
        END IF;
        SELECT evidence_version INTO v FROM learner_state WHERE user_id=p_user_id AND node_id=x->>'node_id';
        IF v IS DISTINCT FROM (x->>'version')::bigint THEN RETURN jsonb_build_object('status','stale'); END IF;
    END LOOP;
    IF p_plan->>'observed_at' IS NOT NULL AND EXISTS(
        SELECT 1 FROM learner_state l WHERE l.user_id=p_user_id
        AND l.node_id IN (SELECT value->>'node_id' FROM jsonb_array_elements(p_plan->'state_rows'))
        AND (l.last_evidence_at > (p_plan->>'observed_at')::timestamptz
             OR l.evidence_touch_at > (p_plan->>'observed_at')::timestamptz)
    ) THEN RETURN jsonb_build_object('status','superseded'); END IF;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'checks') LOOP
        IF jsonb_typeof(x->'count') IS DISTINCT FROM 'number'
           OR (x->>'count') !~ '^[0-9]+$'
           OR jsonb_typeof(x->'global_count') IS DISTINCT FROM 'number'
           OR (x->>'global_count') !~ '^[0-9]+$' THEN
            RAISE EXCEPTION 'Invalid exposure snapshot';
        END IF;
        SELECT count(*) INTO actual_count FROM node_mastery_events e JOIN graph_nodes g ON g.id=e.node_id
            WHERE g.user_id=p_user_id AND e.event_type='evidence' AND e.session_id=x->>'session_id'
              AND e.question_hash=x->>'question_hash';
        IF actual_count IS DISTINCT FROM (x->>'count')::bigint THEN RETURN jsonb_build_object('status','stale'); END IF;
        SELECT count(*) INTO actual_count FROM node_mastery_events e JOIN graph_nodes g ON g.id=e.node_id
            WHERE g.user_id=p_user_id AND e.event_type='evidence' AND e.question_hash=x->>'question_hash';
        IF actual_count IS DISTINCT FROM (x->>'global_count')::bigint THEN RETURN jsonb_build_object('status','stale'); END IF;
    END LOOP;
    IF jsonb_array_length(p_plan->'state_rows')=0
       OR jsonb_array_length(p_plan->'state_rows')<>jsonb_array_length(p_plan->'mirrors')
       OR (SELECT count(DISTINCT value->>'node_id') FROM jsonb_array_elements(p_plan->'state_rows'))<>jsonb_array_length(p_plan->'state_rows')
       OR (SELECT count(DISTINCT value->>'id') FROM jsonb_array_elements(p_plan->'mirrors'))<>jsonb_array_length(p_plan->'mirrors')
       OR EXISTS(SELECT 1 FROM unnest(grade_ids) id WHERE NOT EXISTS(
            SELECT 1 FROM jsonb_array_elements(p_plan->'state_rows') state_entry(value)
            WHERE state_entry.value->>'node_id'=id)) THEN
        RAISE EXCEPTION 'Invalid transaction row sets';
    END IF;
    -- Validate the WHOLE plan before its first mutation. SQL does no BKT,
    -- FSRS, weighting, threshold or propagation arithmetic.
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'state_rows') LOOP
        s := jsonb_populate_record(NULL::learner_state,x);
        IF s.user_id IS DISTINCT FROM p_user_id OR NOT(s.node_id=ANY(ids))
           OR s.p_known IS NULL OR NOT(s.p_known BETWEEN 0 AND 1)
           OR s.updated_at IS NULL
           OR s.n_strong_unassisted<0 OR s.streak_unassisted<0 OR s.max_streak_unassisted<0 OR s.opps<0
           OR EXISTS(SELECT 1 FROM jsonb_object_keys(x) k WHERE k NOT IN (
                'user_id','node_id','p_known','n_strong_unassisted','streak_unassisted','max_streak_unassisted','opps',
                'fsrs_d','fsrs_s','fsrs_last_review_at','fsrs_due_at','last_evidence_at','updated_at'))
           OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_plan->'mirrors') m WHERE m->>'id'=s.node_id) THEN
            RAISE EXCEPTION 'Invalid transaction learner state';
        END IF;
    END LOOP;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'events') LOOP
        ev := jsonb_populate_record(NULL::node_mastery_events,x);
        IF ev.id IS NULL OR NOT(ev.node_id=ANY(grade_ids)) OR NOT(ev.node_id=ANY(ids))
           OR ev.event_type IS DISTINCT FROM 'evidence' OR ev.correct IS NULL
           OR ev.p_before IS NULL OR NOT(ev.p_before BETWEEN 0 AND 1)
           OR ev.p_after IS NULL OR NOT(ev.p_after BETWEEN 0 AND 1)
           OR ev.weight IS NULL OR NOT(ev.weight BETWEEN 0 AND 1)
           OR ev.created_at IS NULL OR ev.evidence_seq IS NULL OR ev.evidence_seq<0
           OR jsonb_typeof(x->'correct') IS DISTINCT FROM 'boolean'
           OR jsonb_typeof(x->'assisted') IS DISTINCT FROM 'boolean'
           OR EXISTS(SELECT 1 FROM jsonb_object_keys(x) k WHERE k NOT IN (
                'id','node_id','delta','reason','created_at','event_type','channel','correct','weight','assisted','max_rung',
                'p_before','p_after','session_id','check_item_id','question_hash','confidence','grader_backend','evidence_seq','planning_observation')) THEN
            RAISE EXCEPTION 'Invalid transaction evidence';
        END IF;
        obs := ev.planning_observation;
        IF obs IS NOT NULL AND (
            jsonb_typeof(obs) IS DISTINCT FROM 'object'
            OR obs->>'node_id' IS DISTINCT FROM ev.node_id OR obs->>'question_hash' IS DISTINCT FROM ev.question_hash
            OR obs->>'check_item_id' IS DISTINCT FROM ev.check_item_id OR obs->>'channel' IS DISTINCT FROM ev.channel
            OR obs->'correct' IS DISTINCT FROM to_jsonb(ev.correct)
            OR obs->'assisted' IS DISTINCT FROM to_jsonb(ev.assisted)
            OR obs->'max_rung' IS DISTINCT FROM to_jsonb(ev.max_rung)
            OR jsonb_typeof(obs->'independent') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'same_session_recheck') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'idk') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'synthetic_idk') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'previously_seen') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'difficulty') IS DISTINCT FROM 'number'
            OR (obs->>'difficulty') NOT IN ('1','2','3')
            OR NOT(obs ?& ARRAY['check_item_id','difficulty','synthetic_idk','previously_seen','node_id',
                'question_hash','channel','correct','idk','assisted','max_rung','same_session_recheck','independent'])
            OR EXISTS(SELECT 1 FROM jsonb_object_keys(obs) k WHERE k NOT IN (
                'check_item_id','difficulty','synthetic_idk','previously_seen','node_id','question_hash',
                'channel','correct','idk','assisted','max_rung','same_session_recheck','independent'))
            OR (obs->>'idk')::boolean AND ev.correct
            OR (obs->>'synthetic_idk')::boolean AND NOT (obs->>'idk')::boolean
            OR ev.assisted IS DISTINCT FROM (ev.max_rung>0)
            OR (obs->>'independent')::boolean IS DISTINCT FROM (NOT (
                ev.max_rung>0 OR ev.assisted OR (obs->>'same_session_recheck')::boolean
                OR (obs->>'synthetic_idk')::boolean OR (obs->>'previously_seen')::boolean))) THEN
            RAISE EXCEPTION 'Invalid final planning provenance';
        END IF;
    END LOOP;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'state_rows') LOOP
        s := jsonb_populate_record(NULL::learner_state,x);
        INSERT INTO learner_state(user_id,node_id,p_known,n_strong_unassisted,streak_unassisted,max_streak_unassisted,
            opps,fsrs_d,fsrs_s,fsrs_last_review_at,fsrs_due_at,last_evidence_at,updated_at,evidence_touch_at)
        VALUES(s.user_id,s.node_id,s.p_known,s.n_strong_unassisted,s.streak_unassisted,s.max_streak_unassisted,
            s.opps,s.fsrs_d,s.fsrs_s,s.fsrs_last_review_at,s.fsrs_due_at,s.last_evidence_at,s.updated_at,s.updated_at)
        ON CONFLICT(user_id,node_id) DO UPDATE SET p_known=EXCLUDED.p_known,n_strong_unassisted=EXCLUDED.n_strong_unassisted,
            streak_unassisted=EXCLUDED.streak_unassisted,max_streak_unassisted=EXCLUDED.max_streak_unassisted,
            opps=EXCLUDED.opps,fsrs_d=EXCLUDED.fsrs_d,fsrs_s=EXCLUDED.fsrs_s,
            fsrs_last_review_at=EXCLUDED.fsrs_last_review_at,fsrs_due_at=EXCLUDED.fsrs_due_at,
            last_evidence_at=EXCLUDED.last_evidence_at,updated_at=EXCLUDED.updated_at,
            evidence_touch_at=greatest(learner_state.evidence_touch_at,EXCLUDED.evidence_touch_at);
    END LOOP;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'mirrors') LOOP
        IF NOT(x->>'id'=ANY(ids)) OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_plan->'state_rows') t WHERE t->>'node_id'=x->>'id')
           OR jsonb_typeof(x->'mastery_score') IS DISTINCT FROM 'number'
           OR NOT((x->>'mastery_score')::double precision BETWEEN 0 AND 1)
           OR EXISTS(SELECT 1 FROM jsonb_object_keys(x) k WHERE k NOT IN ('id','mastery_score','mastery_tier','times_studied','last_studied_at')) THEN
            RAISE EXCEPTION 'Invalid transaction mirror';
        END IF;
        UPDATE graph_nodes SET mastery_score=(x->>'mastery_score')::double precision,mastery_tier=x->>'mastery_tier',
            times_studied=CASE WHEN x ? 'times_studied' THEN (x->>'times_studied')::int ELSE times_studied END,
            last_studied_at=CASE WHEN x ? 'last_studied_at' THEN (x->>'last_studied_at')::timestamptz ELSE last_studied_at END
            WHERE id=x->>'id' AND user_id=p_user_id;
    END LOOP;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'events') LOOP
        ev := jsonb_populate_record(NULL::node_mastery_events,x);
        INSERT INTO node_mastery_events(id,node_id,delta,reason,created_at,event_type,channel,correct,weight,assisted,max_rung,
            p_before,p_after,session_id,check_item_id,question_hash,confidence,grader_backend,evidence_seq,planning_observation)
        VALUES(ev.id,ev.node_id,ev.delta,ev.reason,ev.created_at,ev.event_type,ev.channel,ev.correct,ev.weight,ev.assisted,ev.max_rung,
            ev.p_before,ev.p_after,ev.session_id,ev.check_item_id,ev.question_hash,ev.confidence,ev.grader_backend,ev.evidence_seq,ev.planning_observation);
    END LOOP;
    INSERT INTO learning_evidence_operations(operation_id,user_id,course_id,input_fingerprint,plan,changes)
        VALUES(p_operation_id,p_user_id,p_course_id,p_input_fingerprint,p_plan,p_plan->'changes');
    RETURN learning_evidence_receipt(p_user_id,p_operation_id);
END $$;

REVOKE ALL ON TABLE learning_evidence_operations FROM PUBLIC;
REVOKE ALL ON FUNCTION learning_evidence_receipt(text,uuid) FROM PUBLIC;
REVOKE ALL ON FUNCTION learning_evidence_snapshot(text,text,text[],jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION learning_evidence_commit(text,text,uuid,text,jsonb) FROM PUBLIC;
DO $$ DECLARE r text; BEGIN
    FOREACH r IN ARRAY ARRAY['anon','authenticated'] LOOP
        IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=r) THEN
            EXECUTE format('REVOKE ALL ON TABLE learning_evidence_operations FROM %I',r);
            EXECUTE format('REVOKE ALL ON FUNCTION learning_evidence_receipt(text,uuid) FROM %I',r);
            EXECUTE format('REVOKE ALL ON FUNCTION learning_evidence_snapshot(text,text,text[],jsonb) FROM %I',r);
            EXECUTE format('REVOKE ALL ON FUNCTION learning_evidence_commit(text,text,uuid,text,jsonb) FROM %I',r);
        END IF;
    END LOOP;
    IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN
        GRANT ALL ON TABLE learning_evidence_operations TO service_role;
        GRANT EXECUTE ON FUNCTION learning_evidence_receipt(text,uuid),learning_evidence_snapshot(text,text,text[],jsonb),
            learning_evidence_commit(text,text,uuid,text,jsonb) TO service_role;
    END IF;
END $$;
NOTIFY pgrst,'reload schema';

-- @@ unit 20261108033310_checklist_budget_no_course_soft_delete.sql
-- The learning loop's checklist budget functions (20261019125459) gate on
-- `courses.deleted_at IS NULL`, a column main's state-machine audit drops
-- (#771, 20261106055333_state_machines_audit.sql: nothing ever set it). Once
-- dropped, every call raised "column c.deleted_at does not exist", which
-- PostgREST answers 400 and the checklist refresh reported as a 503.
--
-- Re-create the three functions that read it with that one condition removed
-- and NOTHING else changed (bodies copied from 20261019125459). CREATE OR
-- REPLACE keeps their existing grants (service_role only) and signatures.
-- checklist_budget_read never read the column and is untouched.

CREATE OR REPLACE FUNCTION checklist_budget_admit(
    p_user_id text, p_enrollment_id text, p_input_hash text,
    p_operation_id uuid, p_receipt_id text, p_policy text,
    p_daily_usd numeric, p_monthly_usd numeric, p_daily_tokens bigint
) RETURNS jsonb LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
DECLARE
    a checklist_budget_accounts%ROWTYPE;
    r checklist_budget_reservations%ROWTYPE;
    t timestamptz;
    d timestamptz;
    m timestamptz;
    day_spend numeric; month_spend numeric; tokens bigint;
    day_holds numeric; month_holds numeric; token_holds bigint;
BEGIN
    IF p_user_id IS NULL OR length(p_user_id) NOT BETWEEN 1 AND 255
       OR p_input_hash !~ '^[0-9a-f]{64}$' OR p_operation_id IS NULL
       OR p_receipt_id IS NULL OR p_policy IS DISTINCT FROM 'flash-50k-3x8192-v1'
       OR p_input_hash IS NULL OR p_daily_usd IS NULL OR p_daily_usd <= 0
       OR p_monthly_usd IS NULL OR p_monthly_usd <= 0 OR p_daily_tokens IS NULL OR p_daily_tokens <= 0
       OR p_daily_usd::text IN ('NaN','Infinity','-Infinity') OR p_monthly_usd::text IN ('NaN','Infinity','-Infinity') THEN
        RAISE EXCEPTION 'Invalid checklist admission identity/policy';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM enrollments e JOIN course_offerings o ON o.id=e.offering_id
                   JOIN courses c ON c.id=o.course_id
                   WHERE e.id=p_enrollment_id AND e.user_id=p_user_id) THEN
        RETURN jsonb_build_object('status','ownership');
    END IF;
    INSERT INTO checklist_budget_accounts(user_id) VALUES(p_user_id) ON CONFLICT DO NOTHING;
    SELECT * INTO a FROM checklist_budget_accounts WHERE user_id=p_user_id FOR UPDATE;
    t := clock_timestamp();
    -- Workers may only tighten stored policy. A stale/looser worker cannot
    -- undo a lower cap; changing it upward requires an explicit DB policy edit.
    UPDATE checklist_budget_accounts SET daily_usd=least(daily_usd,p_daily_usd),
        monthly_usd=least(monthly_usd,p_monthly_usd),daily_tokens=least(daily_tokens,p_daily_tokens)
        WHERE user_id=p_user_id RETURNING * INTO a;
    -- Prepared leases may be released: start is a fenced compare-and-swap under
    -- this same mutex, so an expired prepared operation can never dispatch later.
    UPDATE checklist_budget_reservations SET state='released', reason='prepared_expired'
        WHERE user_id=p_user_id AND state='prepared' AND expires_at <= t;
    -- A started timeout is exposure, never a refund. It ceases to own the cache
    -- claim so a deliberate later refresh may reserve additional capacity.
    UPDATE checklist_budget_reservations SET state='unknown', reason='dispatch_outcome_unknown'
        WHERE user_id=p_user_id AND state='started' AND expires_at <= t;
    SELECT * INTO r FROM checklist_budget_reservations WHERE operation_id=p_operation_id;
    IF FOUND THEN
        IF r.user_id IS DISTINCT FROM p_user_id OR r.enrollment_id IS DISTINCT FROM p_enrollment_id
           OR r.input_hash IS DISTINCT FROM p_input_hash OR r.receipt_id IS DISTINCT FROM p_receipt_id THEN
            RETURN jsonb_build_object('status','conflict');
        END IF;
        RETURN jsonb_build_object('status','replay','reservation',to_jsonb(r));
    END IF;
    IF EXISTS (SELECT 1 FROM topic_checklists WHERE enrollment_id=p_enrollment_id AND input_hash=p_input_hash) THEN
        RETURN jsonb_build_object('status','cached');
    END IF;
    SELECT * INTO r FROM checklist_budget_reservations
        WHERE enrollment_id=p_enrollment_id AND state IN ('prepared','started');
    IF FOUND THEN RETURN jsonb_build_object('status','busy','reservation',to_jsonb(r)); END IF;
    IF a.blocked THEN RETURN jsonb_build_object('status','blocked'); END IF;
    d := date_trunc('day', t AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';
    m := date_trunc('month', t AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';
    -- Unknown legacy prices/negative or malformed counters cannot establish
    -- remaining headroom. No coalesce(NULL cost,0) financial fallback.
    IF EXISTS (SELECT 1 FROM llm_usage WHERE user_id=p_user_id AND created_at >= m
               AND (cost_usd IS NULL OR cost_usd < 0 OR cost_usd::text IN ('NaN','Infinity','-Infinity')
                    OR total_tokens IS NULL OR total_tokens < 0)) THEN
        RETURN jsonb_build_object('status','usage_unavailable');
    END IF;
    SELECT coalesce(sum(cost_usd) FILTER (WHERE created_at >= d),0), coalesce(sum(cost_usd),0),
           coalesce(sum(total_tokens) FILTER (WHERE created_at >= d AND
              coalesce(task,'') NOT IN ('decision_shadow','decision_jev_extra')),0)
        INTO day_spend, month_spend, tokens FROM llm_usage WHERE user_id=p_user_id AND created_at >= m;
    SELECT coalesce(sum(held_usd) FILTER (WHERE coalesce(dispatch_at,created_at) >= d),0),
           coalesce(sum(held_usd) FILTER (WHERE coalesce(dispatch_at,created_at) >= m),0),
           coalesce(sum(held_tokens) FILTER (WHERE coalesce(dispatch_at,created_at) >= d),0)
        INTO day_holds,month_holds,token_holds FROM checklist_budget_reservations
        WHERE user_id=p_user_id AND state IN ('prepared','started','unknown');
    IF day_spend + day_holds + .07644 > a.daily_usd
       OR month_spend + month_holds + .07644 > a.monthly_usd
       OR tokens + token_holds + 74576 > a.daily_tokens THEN
        RETURN jsonb_build_object('status','denied','retry_at', CASE
            WHEN month_spend + month_holds + .07644 > a.monthly_usd THEN m + interval '1 month'
            ELSE d + interval '1 day' END);
    END IF;
    UPDATE checklist_budget_accounts SET next_fence=next_fence+1 WHERE user_id=p_user_id RETURNING * INTO a;
    INSERT INTO checklist_budget_reservations(operation_id,user_id,enrollment_id,input_hash,fence,state,
        created_at,expires_at,receipt_id) VALUES(p_operation_id,p_user_id,p_enrollment_id,p_input_hash,
        a.next_fence,'prepared',t,t + interval '2 minutes',p_receipt_id) RETURNING * INTO r;
    RETURN jsonb_build_object('status','admitted','reservation',to_jsonb(r));
END $$;

CREATE OR REPLACE FUNCTION checklist_budget_start(p_user_id text,p_operation_id uuid,p_fence bigint)
RETURNS jsonb LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
DECLARE
    r checklist_budget_reservations%ROWTYPE;
    a checklist_budget_accounts%ROWTYPE;
    t timestamptz;
    d timestamptz;
    m timestamptz;
    ds numeric; ms numeric; ts bigint;
    dh numeric; mh numeric; th bigint;
BEGIN
    SELECT * INTO a FROM checklist_budget_accounts WHERE user_id=p_user_id FOR UPDATE;
    t := clock_timestamp();
    SELECT * INTO r FROM checklist_budget_reservations WHERE operation_id=p_operation_id AND user_id=p_user_id;
    IF NOT FOUND OR r.fence IS DISTINCT FROM p_fence THEN RETURN jsonb_build_object('status','conflict'); END IF;
    IF r.state <> 'prepared' OR r.expires_at <= t OR EXISTS (SELECT 1 FROM checklist_budget_accounts WHERE user_id=p_user_id AND blocked) THEN RETURN jsonb_build_object('status','not_started','reservation',to_jsonb(r)); END IF;
    IF NOT EXISTS (SELECT 1 FROM enrollments e JOIN course_offerings o ON o.id=e.offering_id
                   JOIN courses c ON c.id=o.course_id
                   WHERE e.id=r.enrollment_id AND e.user_id=p_user_id) THEN
        UPDATE checklist_budget_reservations SET state='released',reason='ownership_changed' WHERE operation_id=p_operation_id;
        RETURN jsonb_build_object('status','ownership');
    END IF;
    -- Do not move a prepared hold across UTC windows. Re-admit after midnight.
    IF (t AT TIME ZONE 'UTC')::date <> (r.created_at AT TIME ZONE 'UTC')::date THEN
        UPDATE checklist_budget_reservations SET state='released',reason='window_changed' WHERE operation_id=p_operation_id;
        RETURN jsonb_build_object('status','window_changed');
    END IF;
    d := date_trunc('day', t AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';
    m := date_trunc('month', t AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';
    IF EXISTS (SELECT 1 FROM llm_usage WHERE user_id=p_user_id AND created_at>=m
               AND (cost_usd IS NULL OR cost_usd<0 OR cost_usd::text IN ('NaN','Infinity','-Infinity')
                    OR total_tokens IS NULL OR total_tokens<0)) THEN
        UPDATE checklist_budget_reservations SET state='released',reason='usage_unavailable' WHERE operation_id=p_operation_id;
        RETURN jsonb_build_object('status','usage_unavailable');
    END IF;
    SELECT coalesce(sum(cost_usd) FILTER (WHERE created_at>=d),0),coalesce(sum(cost_usd),0),
           coalesce(sum(total_tokens) FILTER (WHERE created_at>=d AND
              coalesce(task,'') NOT IN ('decision_shadow','decision_jev_extra')),0)
        INTO ds,ms,ts FROM llm_usage WHERE user_id=p_user_id AND created_at>=m;
    SELECT coalesce(sum(held_usd) FILTER (WHERE coalesce(dispatch_at,created_at)>=d),0),
           coalesce(sum(held_usd) FILTER (WHERE coalesce(dispatch_at,created_at)>=m),0),
           coalesce(sum(held_tokens) FILTER (WHERE coalesce(dispatch_at,created_at)>=d),0)
        INTO dh,mh,th FROM checklist_budget_reservations WHERE user_id=p_user_id AND state IN ('prepared','started','unknown');
    -- This includes the already-reserved operation, not another new hold.
    IF ds+dh>a.daily_usd OR ms+mh>a.monthly_usd OR ts+th>a.daily_tokens THEN
        UPDATE checklist_budget_reservations SET state='released',reason='capacity_changed' WHERE operation_id=p_operation_id;
        RETURN jsonb_build_object('status','denied');
    END IF;
    UPDATE checklist_budget_reservations SET state='started', dispatch_at=t,
        expires_at=t+interval '2 minutes' WHERE operation_id=p_operation_id RETURNING * INTO r;
    -- Only this successful CAS authorizes one logical run. A replay NEVER grants
    -- dispatch; an ambiguous start acknowledgment must not launch a second call.
    RETURN jsonb_build_object('status','started','reservation',to_jsonb(r));
END $$;

CREATE OR REPLACE FUNCTION checklist_budget_reconcile(
    p_user_id text,p_operation_id uuid,p_fence bigint,p_action text,
    p_receipt jsonb DEFAULT NULL,p_fingerprint text DEFAULT NULL,p_content text DEFAULT NULL
) RETURNS jsonb LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
DECLARE
    r checklist_budget_reservations%ROWTYPE;
    bill llm_usage%ROWTYPE;
    expected numeric;
    published boolean := false;
BEGIN
    PERFORM 1 FROM checklist_budget_accounts WHERE user_id=p_user_id FOR UPDATE;
    SELECT * INTO r FROM checklist_budget_reservations WHERE operation_id=p_operation_id AND user_id=p_user_id;
    IF NOT FOUND OR r.fence IS DISTINCT FROM p_fence THEN RETURN jsonb_build_object('status','conflict'); END IF;
    IF p_action='settle' THEN
        IF r.state='settled' THEN
            IF r.receipt IS DISTINCT FROM p_receipt OR r.fingerprint IS DISTINCT FROM p_fingerprint THEN
                RETURN jsonb_build_object('status','conflict');
            END IF;
            RETURN jsonb_build_object('status','settled','reservation',to_jsonb(r));
        END IF;
        IF r.state NOT IN ('started','unknown') OR p_receipt IS NULL
           OR p_fingerprint IS NULL OR p_fingerprint !~ '^[0-9a-f]{64}$' THEN RETURN jsonb_build_object('status','conflict'); END IF;
        bill := jsonb_populate_record(NULL::llm_usage,p_receipt);
        expected := round(((bill.prompt_tokens-coalesce(bill.cached_tokens,0)) * .0003
                    + coalesce(bill.cached_tokens,0) * .00003 + bill.completion_tokens * .0025)/1000,10);
        IF bill.id IS DISTINCT FROM r.receipt_id OR bill.user_id IS DISTINCT FROM p_user_id
           OR bill.feature IS DISTINCT FROM 'topic_checklist' OR bill.task IS DISTINCT FROM 'topic_checklist'
           OR bill.model IS DISTINCT FROM 'gemini-2.5-flash' OR bill.provider IS DISTINCT FROM 'gemini'
           OR bill.created_at IS DISTINCT FROM r.dispatch_at OR bill.session_id IS NOT NULL
           OR bill.prompt_tokens IS NULL OR bill.prompt_tokens <= 0 OR bill.completion_tokens IS NULL OR bill.completion_tokens <= 0
           OR bill.total_tokens IS DISTINCT FROM bill.prompt_tokens+bill.completion_tokens
           OR bill.cached_tokens IS NULL OR bill.cached_tokens < 0 OR bill.cached_tokens > bill.prompt_tokens
           OR bill.thinking_tokens IS NULL OR bill.thinking_tokens < 0 OR bill.thinking_tokens > bill.completion_tokens
           OR bill.cost_usd IS NULL OR bill.cost_usd::text IN ('NaN','Infinity','-Infinity')
           OR bill.cost_usd IS DISTINCT FROM expected OR expected <= 0
           OR p_receipt - ARRAY['id','user_id','request_id','feature','task','model','provider','prompt_tokens',
                'completion_tokens','total_tokens','cached_tokens','thinking_tokens','session_id','cost_usd','created_at'] <> '{}'::jsonb
        THEN RETURN jsonb_build_object('status','conflict'); END IF;
        -- Stable id plus exact content verification makes ambiguous insert ACKs
        -- safe to replay; NEVER additionally enqueue this checklist bill.
        INSERT INTO llm_usage(id,user_id,request_id,feature,task,model,provider,prompt_tokens,completion_tokens,
            total_tokens,cached_tokens,thinking_tokens,session_id,cost_usd,created_at)
        VALUES(bill.id,bill.user_id,bill.request_id,bill.feature,bill.task,bill.model,bill.provider,bill.prompt_tokens,
            bill.completion_tokens,bill.total_tokens,bill.cached_tokens,bill.thinking_tokens,bill.session_id,bill.cost_usd,bill.created_at)
        ON CONFLICT(id) DO NOTHING;
        IF NOT EXISTS (SELECT 1 FROM llm_usage u WHERE u.id=bill.id AND u.created_at=bill.created_at AND (to_jsonb(u)-'created_at') @> (p_receipt-'created_at')) THEN
            RAISE EXCEPTION 'Checklist receipt identity already has different content';
        END IF;
        IF bill.cost_usd > r.held_usd OR bill.total_tokens > r.held_tokens THEN
            UPDATE checklist_budget_accounts SET blocked=true WHERE user_id=p_user_id;
        END IF;
        -- A late old result may settle its bill but cannot overwrite a newer
        -- operation's cache, even when that newer operation failed/was released.
        IF p_content IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM checklist_budget_reservations n WHERE n.enrollment_id=r.enrollment_id AND (n.created_at>r.created_at OR (n.user_id=r.user_id AND n.fence>r.fence))
        ) AND EXISTS (SELECT 1 FROM enrollments e JOIN course_offerings o ON o.id=e.offering_id JOIN courses c ON c.id=o.course_id
                      WHERE e.id=r.enrollment_id AND e.user_id=p_user_id FOR SHARE OF e,o,c) THEN
            INSERT INTO topic_checklists(enrollment_id,input_hash,content,generated_at)
                VALUES(r.enrollment_id,r.input_hash,p_content,clock_timestamp())
                ON CONFLICT(enrollment_id) DO UPDATE SET input_hash=excluded.input_hash,content=excluded.content,generated_at=excluded.generated_at;
            published := true;
        END IF;
        UPDATE checklist_budget_reservations SET state='settled',receipt=p_receipt,fingerprint=p_fingerprint,
            cache_published=published,reason=NULL WHERE operation_id=p_operation_id RETURNING * INTO r;
        RETURN jsonb_build_object('status','settled','reservation',to_jsonb(r));
    ELSIF p_action='no_dispatch' AND r.state IN ('prepared','started','unknown') THEN
        -- Trusted backend proof: this process never entered the generation
        -- handler. Counter-only requests are not billed generation. A process
        -- crash cannot provide this proof, so its started hold remains unknown.
        -- p_content here is exclusively the explicit local FunctionModel seam
        -- in the trusted backend; it never creates a paid usage row.
        IF p_content IS NOT NULL AND r.state='prepared' AND NOT EXISTS (
            SELECT 1 FROM checklist_budget_reservations n WHERE n.enrollment_id=r.enrollment_id
            AND (n.created_at>r.created_at OR (n.user_id=r.user_id AND n.fence>r.fence))
        ) AND EXISTS (SELECT 1 FROM enrollments e JOIN course_offerings o ON o.id=e.offering_id JOIN courses c ON c.id=o.course_id
                      WHERE e.id=r.enrollment_id AND e.user_id=p_user_id FOR SHARE OF e,o,c) THEN
            INSERT INTO topic_checklists(enrollment_id,input_hash,content,generated_at)
                VALUES(r.enrollment_id,r.input_hash,p_content,clock_timestamp())
                ON CONFLICT(enrollment_id) DO UPDATE SET input_hash=excluded.input_hash,content=excluded.content,generated_at=excluded.generated_at;
            published := true;
        END IF;
        UPDATE checklist_budget_reservations SET state='released',cache_published=published,reason='no_generation_dispatched'
            WHERE operation_id=p_operation_id RETURNING * INTO r;
    ELSIF p_action='unknown' AND r.state IN ('started','unknown') THEN
        -- Preserve exclusivity until grace expiry; admission changes expired
        -- started -> unknown and retains the entire financial hold.
        UPDATE checklist_budget_reservations SET reason='dispatch_outcome_unknown'
            WHERE operation_id=p_operation_id RETURNING * INTO r;
    ELSIF p_action='no_dispatch' AND r.state='released' THEN NULL;
    ELSE RETURN jsonb_build_object('status','conflict');
    END IF;
    RETURN jsonb_build_object('status',r.state,'reservation',to_jsonb(r));
END $$;

-- @@ unit 20261108041639_learning_item_quality.sql
-- 20261108041639_learning_item_quality.sql
-- Learning loop check-item quality guards (spec §13 A113; GitHub #695; the
-- 2026-11-07 direction audit, "Item quality"). Check items are drafted by a
-- model from classmates' uploads and keyed from peer material; no instructor
-- reviews them. Three guards:
--
-- 1. check_items.lint_flags — the item-flaw linter's codes
--    (learning/item_lint.py: correct_longest, correct_repeats_stem,
--    all_or_none_of_above, duplicate_options, negative_stem), written with the
--    item by services/check_item_service.py and for older rows by
--    scripts/backfill_check_item_lint.py. NULL = never linted, '{}' = clean.
--    Codes only, never item text, so the column is plaintext.
--
-- 2. check_item_reports — a student's "Report this question": one row per
--    (student, question_hash), the reason an enum (no free text is ever
--    stored). The row is what stops the item being served to its reporter
--    (learning/loop_state_store.py::reported_hashes, beside the seen/revealed
--    sets every selection already excludes). Evidence already written from the
--    item stays.
--
-- 3. check_item_reviews — the decision on one course item (course_id,
--    question_hash): 'retired' (ITEM_REPORT_RETIRE_MIN_REPORTERS distinct
--    reporters, or an admin) or 'approved' (an admin cleared it from the review
--    queue; a report newer than the approval re-opens it and counts afresh).
--    A retired question is never stored for the course again.
--
-- check_item_report(...) records a report and decides, under a per-item
-- advisory lock, whether it is the report that reaches the threshold: two
-- reporters arriving together are counted one after the other (READ COMMITTED
-- reads the first's committed row once the lock is free), so exactly one of
-- them is told to retire the item; the backend then deletes it through
-- check_item_service's A23 retire path. check_item_review_decide(...) is an
-- admin's decision under the same lock; a retired item is never approved.
-- Timestamps are clock_timestamp() taken under the lock, so their order is the
-- lock's order. Hashes, ids, enums and timestamps only. Backend-only.

ALTER TABLE public.check_items ADD COLUMN IF NOT EXISTS lint_flags text[];

CREATE TABLE IF NOT EXISTS check_item_reports (
  user_id       text        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  question_hash text        NOT NULL,
  course_id     text        NOT NULL,
  reason        text        NOT NULL CHECK (reason IN ('wrong_answer','unclear','not_from_my_course')),
  surface       text        NOT NULL CHECK (surface IN ('loop','review')),
  created_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, question_hash)
);
CREATE INDEX IF NOT EXISTS check_item_reports_item_idx
  ON check_item_reports (course_id, question_hash);

CREATE TABLE IF NOT EXISTS check_item_reviews (
  course_id     text        NOT NULL,
  question_hash text        NOT NULL,
  status        text        NOT NULL CHECK (status IN ('approved','retired')),
  decided_by    text        NOT NULL CHECK (decided_by IN ('reports','admin')),
  reviewed_by   text        REFERENCES users(id) ON DELETE SET NULL,
  reviewed_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (course_id, question_hash)
);

-- One report. Returns one row: first_report (this student had not reported the
-- item before; a repeat records nothing), reporters (distinct reporters of the
-- course item since its last approval, this one included) and retire (this
-- report is the one that reached p_min_reporters on an item not yet retired —
-- the caller retires it). CREATE OR REPLACE: functions have no IF NOT EXISTS.
CREATE OR REPLACE FUNCTION check_item_report(
  p_user_id text,
  p_course_id text,
  p_question_hash text,
  p_reason text,
  p_surface text,
  p_min_reporters integer
)
RETURNS TABLE (first_report boolean, reporters integer, retire boolean)
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
  v_first boolean;
  v_status text;
  v_since timestamptz;
  v_count integer;
BEGIN
  IF coalesce(p_user_id, '') = '' OR coalesce(p_course_id, '') = ''
     OR coalesce(p_question_hash, '') = '' OR coalesce(p_min_reporters, 0) < 1 THEN
    RAISE EXCEPTION 'Invalid check item report';
  END IF;
  PERFORM pg_advisory_xact_lock(
    hashtextextended('check-item-review:' || p_course_id || ':' || p_question_hash, 0));
  INSERT INTO check_item_reports (user_id, question_hash, course_id, reason, surface, created_at)
  VALUES (p_user_id, p_question_hash, p_course_id, p_reason, p_surface, clock_timestamp())
  ON CONFLICT (user_id, question_hash) DO NOTHING;
  v_first := FOUND;
  SELECT r.status, r.reviewed_at INTO v_status, v_since
    FROM check_item_reviews r
   WHERE r.course_id = p_course_id AND r.question_hash = p_question_hash;
  SELECT count(*)::integer INTO v_count
    FROM check_item_reports c
   WHERE c.course_id = p_course_id AND c.question_hash = p_question_hash
     AND (v_status IS DISTINCT FROM 'approved' OR c.created_at > v_since);
  first_report := v_first;
  reporters := v_count;
  retire := v_first AND v_count >= p_min_reporters AND v_status IS DISTINCT FROM 'retired';
  IF retire THEN
    INSERT INTO check_item_reviews (course_id, question_hash, status, decided_by, reviewed_by, reviewed_at)
    VALUES (p_course_id, p_question_hash, 'retired', 'reports', NULL, clock_timestamp())
    ON CONFLICT (course_id, question_hash) DO UPDATE
      SET status = 'retired', decided_by = 'reports', reviewed_by = NULL,
          reviewed_at = EXCLUDED.reviewed_at;
  END IF;
  RETURN NEXT;
END
$$;

-- An admin's decision ('approved' | 'retired'). Returns one row: previous (the
-- status before, NULL for none) and applied (false only when approving an item
-- already retired: a retired item stays retired).
CREATE OR REPLACE FUNCTION check_item_review_decide(
  p_course_id text,
  p_question_hash text,
  p_status text,
  p_reviewed_by text
)
RETURNS TABLE (previous text, applied boolean)
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
  v_prev text;
BEGIN
  IF coalesce(p_course_id, '') = '' OR coalesce(p_question_hash, '') = ''
     OR coalesce(p_status, '') NOT IN ('approved', 'retired') THEN
    RAISE EXCEPTION 'Invalid check item review';
  END IF;
  PERFORM pg_advisory_xact_lock(
    hashtextextended('check-item-review:' || p_course_id || ':' || p_question_hash, 0));
  SELECT r.status INTO v_prev
    FROM check_item_reviews r
   WHERE r.course_id = p_course_id AND r.question_hash = p_question_hash;
  previous := v_prev;
  applied := NOT (v_prev IS NOT DISTINCT FROM 'retired' AND p_status = 'approved');
  IF applied THEN
    INSERT INTO check_item_reviews (course_id, question_hash, status, decided_by, reviewed_by, reviewed_at)
    VALUES (p_course_id, p_question_hash, p_status, 'admin', p_reviewed_by, clock_timestamp())
    ON CONFLICT (course_id, question_hash) DO UPDATE
      SET status = EXCLUDED.status, decided_by = 'admin', reviewed_by = EXCLUDED.reviewed_by,
          reviewed_at = EXCLUDED.reviewed_at;
  END IF;
  RETURN NEXT;
END
$$;

-- Backend-only (the 20260929050404_learning_ai_tutor_daily_calls.sql idiom):
-- RLS with no policy denies every non-bypass role; service_role (the backend)
-- bypasses it. Functions grant EXECUTE to PUBLIC by default, so that is revoked.
-- Role statements are guarded because those roles are Supabase's: a plain
-- Postgres has none of them, and an unguarded REVOKE naming one aborts the
-- whole migration.
ALTER TABLE check_item_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE check_item_reviews ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE check_item_reports FROM PUBLIC;
REVOKE ALL ON TABLE check_item_reviews FROM PUBLIC;
REVOKE ALL ON FUNCTION check_item_report(text, text, text, text, text, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION check_item_review_decide(text, text, text, text) FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON TABLE check_item_reports FROM %I', r);
            EXECUTE format('REVOKE ALL ON TABLE check_item_reviews FROM %I', r);
            EXECUTE format(
                'REVOKE ALL ON FUNCTION check_item_report(text, text, text, text, text, integer) FROM %I', r);
            EXECUTE format(
                'REVOKE ALL ON FUNCTION check_item_review_decide(text, text, text, text) FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE check_item_reports TO service_role;
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE check_item_reviews TO service_role;
        GRANT EXECUTE ON FUNCTION check_item_report(text, text, text, text, text, integer) TO service_role;
        GRANT EXECUTE ON FUNCTION check_item_review_decide(text, text, text, text) TO service_role;
    END IF;
END $$;

-- PostgREST resolves the new tables and /rpc/<name> from its schema cache; the
-- local stack does not reliably reload on DDL (docs/local-supabase.md). NOTIFY
-- is delivered at COMMIT and is a no-op with no listener.
NOTIFY pgrst, 'reload schema';

-- @@ unit 20261108041742_learning_posttest_windows.sql
-- 20261108041742_learning_posttest_windows.sql
-- Learning loop, spec §13 A112 (docs/research/learning-loop/2026-11-07-direction-
-- audit.md rec. 2; the 2026-10-18 foundation audit's "fixed follow-up windows"):
-- the tool-removed post-test becomes an analyzable outcome measure, posed at
-- FIXED follow-up windows instead of "the last evidence is old enough" (which
-- every review postponed).
--
-- 1. One pose row per (student, node, window): `window_days` (a value of
--    learning/params.py POSTTEST_WINDOWS_DAYS) joins the primary key. Every
--    existing row was posed under the one-pose-per-node rule; it maps to the
--    7-day window and keeps its item, times and claim.
-- 2. The window's anchor: the concept's FIRST graded evidence, which practice
--    cannot move (node_mastery_events is append-only) — `anchor_event_id` (that
--    journal row's id) and `anchor_at` (its time).
-- 3. The delay the pose actually had: `last_evidence_at` (the concept's last
--    journaled evidence before the pose) and `days_since_evidence` (posed_at
--    minus it, in days), so an analysis can tell a truly delayed outcome from a
--    recently practised one.
-- 4. The outcome, written by the conditional UPDATE that closes the pose:
--    `correct`, and `max_rung` (the rung the grade carried; 0 = unassisted).
--
-- Rows posed before this migration keep NULL in 2-4: unknown, never inferred.
-- Hashes, ids, timestamps and numbers only — never item or answer text. RLS and
-- the backend-only grants are table-level (20260930024005) and unchanged.
-- Idempotent.

ALTER TABLE posttest_poses ADD COLUMN IF NOT EXISTS window_days integer;
UPDATE posttest_poses SET window_days = 7 WHERE window_days IS NULL;
ALTER TABLE posttest_poses ALTER COLUMN window_days SET NOT NULL;
ALTER TABLE posttest_poses DROP CONSTRAINT IF EXISTS posttest_poses_window_days_check;
ALTER TABLE posttest_poses ADD CONSTRAINT posttest_poses_window_days_check
  CHECK (window_days > 0);

-- Re-key on (user_id, node_id, window_days). The existing rows are unique on
-- (user_id, node_id), so with window 7 they stay unique. Guarded on the catalog:
-- a re-run with the new key in place changes nothing.
DO $$
DECLARE
    pk_name text;
    pk_def  text;
BEGIN
    SELECT conname, pg_get_constraintdef(oid) INTO pk_name, pk_def
      FROM pg_constraint
     WHERE conrelid = 'public.posttest_poses'::regclass AND contype = 'p';
    IF pk_def IS DISTINCT FROM 'PRIMARY KEY (user_id, node_id, window_days)' THEN
        IF pk_name IS NOT NULL THEN
            EXECUTE format('ALTER TABLE public.posttest_poses DROP CONSTRAINT %I', pk_name);
        END IF;
        ALTER TABLE public.posttest_poses
          ADD CONSTRAINT posttest_poses_pkey PRIMARY KEY (user_id, node_id, window_days);
    END IF;
END $$;

ALTER TABLE posttest_poses ADD COLUMN IF NOT EXISTS anchor_event_id text;
ALTER TABLE posttest_poses ADD COLUMN IF NOT EXISTS anchor_at timestamptz;
ALTER TABLE posttest_poses ADD COLUMN IF NOT EXISTS last_evidence_at timestamptz;
ALTER TABLE posttest_poses ADD COLUMN IF NOT EXISTS days_since_evidence double precision;
ALTER TABLE posttest_poses ADD COLUMN IF NOT EXISTS correct boolean;
ALTER TABLE posttest_poses ADD COLUMN IF NOT EXISTS max_rung smallint;

ALTER TABLE posttest_poses DROP CONSTRAINT IF EXISTS posttest_poses_days_since_evidence_check;
ALTER TABLE posttest_poses ADD CONSTRAINT posttest_poses_days_since_evidence_check
  CHECK (days_since_evidence IS NULL OR days_since_evidence >= 0);

-- An outcome is both columns or neither, only on an answered pose, and its rung
-- is a ladder rung (H0..H6). A renewal (A89/A93) resets all three together.
ALTER TABLE posttest_poses DROP CONSTRAINT IF EXISTS posttest_poses_outcome_check;
ALTER TABLE posttest_poses ADD CONSTRAINT posttest_poses_outcome_check
  CHECK (
    (correct IS NULL) = (max_rung IS NULL)
    AND (correct IS NULL OR answered_at IS NOT NULL)
    AND (max_rung IS NULL OR max_rung BETWEEN 0 AND 6)
  );

-- The admin learning-gain report reads the outcomes answered in a date range.
CREATE INDEX IF NOT EXISTS posttest_poses_answered_at
  ON posttest_poses (answered_at) WHERE answered_at IS NOT NULL;

-- PostgREST serves the new columns and key from its schema cache; reload it (a
-- no-op with no listener).
NOTIFY pgrst, 'reload schema';

-- @@ unit 20261108050630_learning_grader_backend_claude.sql
-- Learning loop spec §13 A116: node_mastery_events.grader_backend names the
-- provider that graded. 20260927093149_learning_grader_backend.sql allowed
-- ('deterministic','gemini','gemini_second','jev') and agents/grader.py wrote
-- 'gemini' / 'gemini_second' whatever model the grader slots ran, so with
-- SAPLING_MODEL_GRADER=claude-* every evidence row named Gemini while
-- llm_usage named Claude. The grader now writes 'claude' / 'claude_second' for
-- a run on a claude-* slot; this widens the CHECK to admit them.
--
-- Historical rows are not relabelled: a row written as 'gemini' keeps it.
-- (Rows graded by Claude before this change cannot be told apart in this
-- table; llm_usage, by session_id and time, is the only record of them.)
--
-- Matches on the constraint BODY, not an assumed name (the
-- 20260828172725_assignments_source_check_by_definition.sql lesson: a DROP by
-- the default name no-ops on a suffixed variant, and the narrow CHECK stays
-- enforced beside the wide one). The inline CHECK's default name is
-- node_mastery_events_grader_backend_check; the widened one keeps it.
--
-- Idempotent: on a re-run the first block matches nothing (every grader_backend
-- CHECK already names 'claude_second') and the guarded ADD is skipped.

DO $$
DECLARE
  r RECORD;
BEGIN
  FOR r IN
    SELECT c.conname
    FROM pg_constraint c
    WHERE c.conrelid = 'public.node_mastery_events'::regclass
      AND c.contype = 'c'
      AND pg_get_constraintdef(c.oid) ILIKE '%grader_backend%'
      AND pg_get_constraintdef(c.oid) NOT ILIKE '%claude_second%'
  LOOP
    EXECUTE format('ALTER TABLE public.node_mastery_events DROP CONSTRAINT %I', r.conname);
    RAISE NOTICE 'dropped narrow node_mastery_events.grader_backend CHECK: %', r.conname;
  END LOOP;
END $$;

-- NOT VALID for lock behaviour, not data: the old list is a strict subset of
-- this one, so no existing row can violate it, and a validating ADD would hold
-- ACCESS EXCLUSIVE on the append-only evidence journal (every grade writes to
-- it) for a full-table scan that buys nothing. New and updated rows are
-- checked either way. The same choice 0042 and 20260828172725 make.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conrelid = 'public.node_mastery_events'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) ILIKE '%grader_backend%'
      AND pg_get_constraintdef(oid) ILIKE '%claude_second%'
  ) THEN
    ALTER TABLE public.node_mastery_events
      ADD CONSTRAINT node_mastery_events_grader_backend_check
      CHECK (grader_backend IS NULL OR grader_backend IN ('deterministic','gemini','gemini_second','claude','claude_second','jev')) NOT VALID;
  END IF;
END $$;

-- @@ unit 20261108051912_learning_item_alignment.sql
-- 20261108051912_learning_item_alignment.sql
-- Learning loop check-item alignment (spec §13 A119). A drafted item is
-- stored only after an alignment check (agents/check_items_verify.py) has
-- answered, per item, whether its question asks for each rubric criterion
-- and which course concept it tests; code drops an unasked criterion,
-- re-tags the item to the concept it tests, or rejects it
-- (learning/item_alignment.py). What changed is recorded in the A113
-- lint_flags column beside the linter's codes (rubric_unasked_dropped,
-- concept_retagged), so the admin review queue lists it.
--
-- check_items.aligned_at — when the alignment check last passed the row.
-- NULL = never checked: every row stored before A119 (and one stored without
-- the check, which only tests and evals do). The alignment backfill
-- (scripts/backfill_check_item_alignment.py) reads `aligned_at IS NULL` by
-- default. A timestamp, never text, so the column is plaintext. Only the
-- generation write and the backfill touch it: no request-path read selects
-- it.

ALTER TABLE public.check_items ADD COLUMN IF NOT EXISTS aligned_at timestamptz;

-- PostgREST resolves the new column from its schema cache; the local stack
-- does not reliably reload on DDL (docs/local-supabase.md). NOTIFY is
-- delivered at COMMIT and is a no-op with no listener.
NOTIFY pgrst, 'reload schema';

-- @@ unit 20261108072715_learning_evidence_void.sql
-- 20261108072715_learning_evidence_void.sql
-- Learning loop spec §13 A123: a broken check item's evidence is VOIDED, and
-- the student report that used to delete an item for the whole course now only
-- QUARANTINES it until staff decide. Hashes, ids, enums, numbers and
-- timestamps only — never item or answer text. Idempotent; no row of
-- node_mastery_events is ever updated or deleted here.
--
-- 1. Quarantine (A113 amended), as a HOLD (A124's). ITEM_REPORT_QUARANTINE_MIN_REPORTERS
--    distinct reporters put a course item in check_item_reviews with status
--    'quarantined' (decided_by 'reports'): nothing is deleted, no evidence
--    changes. Staff decide in the admin queue: 'approved' lifts it, 'retired'
--    (decided_by 'admin', the ONLY way an item becomes 'retired') deletes it
--    and voids its evidence (3, 5). Only a staff retire blocks re-drafting the
--    question for the course. `approved_at` remembers the last approval, so
--    reporters still count "since the last approval" while an item sits in
--    quarantine. Rows the A113 auto-retire wrote ('retired' by 'reports') were
--    never a staff decision: they become 'quarantined'.
--    What keeps the item from every student is the one hold of spec §13 A124:
--    a hold code in check_items.lint_flags, which every student read drops
--    (learning/checks.py held_flags / is_servable). Two codes are the staff's,
--    DERIVED from this table and never written by hand: 'reports_threshold'
--    while the status is 'quarantined', 'staff_retired' while it is 'retired'
--    (its rows wait there for the void and the delete). check_item_hold_flags
--    is the one derivation: the report and decision functions apply it to the
--    course item's rows in the decision's own transaction, and a trigger on
--    check_items applies it to every row written later — a re-draft of a
--    quarantined question, a re-lint, an alignment or key-check rewrite, an
--    audit — so no write path can drop or forge one. A confirmed key
--    (canonical_verified, A124) lifts neither.
--    check_item_report_quarantine(...) is the report function now;
--    check_item_report(...) keeps its signature for a backend deployed before
--    this migration and never retires anything (its `retire` is always false).
--
-- 2. The evidence journal records every input its replay needs. Three nullable
--    node_mastery_events columns, written by the single graph writer from now
--    on: `retention` (the FSRS retention target the row was scheduled at — the
--    review passes a non-default one), `same_session_recheck` (the writer's
--    final flag; the weight alone also says it for the rows where it matters)
--    and `propagated_to` (the node ids the row's one-hop prerequisite
--    propagation moved, as a JSON array). Rows written before keep NULL there:
--    unknown, never backfilled (the replay's rule for them is spec §13 A123).
--
-- 3. learning_evidence_voids — one APPEND-ONLY row per voided evidence row,
--    keyed by the evidence id (node_mastery_events.id), with the item it was
--    graded against and the void operation. A void is a staff judgement about
--    an item, not an observation of the learner, so it is a record of its own
--    rather than a journal event; the journal stays exactly as written. Written
--    only by learning_evidence_void_commit (5), under the single graph writer.
--
-- 4. learning_evidence_commit (the single writer's transaction, ADR 0037) is
--    replaced: (a) it takes a SHARED lock on each check item a batch grades and
--    refuses the batch (status 'retired', nothing written) when staff retired
--    one — check_item_review_decide holds the same key EXCLUSIVELY, so no grade
--    in flight when a retire is decided can leave a non-void row behind; (b) it
--    accepts and journals the three new columns. Everything else is the
--    20261019141950 definition, verbatim.
--
-- 5. learning_evidence_void_snapshot / learning_evidence_void_commit — one
--    student's void + recompute, as ONE transaction under the same owner lock,
--    item lock, topology lock, row locks and version checks as an evidence
--    commit: insert the void rows, write the learner_state rows and graph_nodes
--    mirrors the Python replay of the NON-void journal computed (only where they
--    differ, so a re-run writes nothing), and close the misconceptions whose
--    every supporting attempt is void. learning_evidence_void_pending lists the
--    students who still have non-void evidence on a retired item.
--
-- 6. misconception_attempts — one row per misconception increment (the item it
--    was recorded from), so "every supporting attempt is void" is answerable;
--    misconceptions.resolved_reason names a void closure. The 7-argument
--    misconception_record(...) takes the attempt's question_hash and records
--    nothing for an item staff retired (shared item lock, as 4).

-- ── 1. quarantine ───────────────────────────────────────────────────────────

ALTER TABLE check_item_reviews ADD COLUMN IF NOT EXISTS approved_at timestamptz;
UPDATE check_item_reviews SET approved_at = reviewed_at
 WHERE status = 'approved' AND approved_at IS NULL;

-- Widen the status CHECK. Matches the constraint BODY, never an assumed name
-- (the 20260828172725 lesson); a re-run finds the wide one and skips both.
DO $$
DECLARE
  r RECORD;
BEGIN
  FOR r IN
    SELECT c.conname
      FROM pg_constraint c
     WHERE c.conrelid = 'public.check_item_reviews'::regclass
       AND c.contype = 'c'
       AND pg_get_constraintdef(c.oid) ILIKE '%status%'
       AND pg_get_constraintdef(c.oid) NOT ILIKE '%quarantined%'
  LOOP
    EXECUTE format('ALTER TABLE public.check_item_reviews DROP CONSTRAINT %I', r.conname);
  END LOOP;
END $$;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conrelid = 'public.check_item_reviews'::regclass AND contype = 'c'
       AND pg_get_constraintdef(oid) ILIKE '%quarantined%'
  ) THEN
    ALTER TABLE public.check_item_reviews
      ADD CONSTRAINT check_item_reviews_status_check
      CHECK (status IN ('approved', 'quarantined', 'retired'));
  END IF;
END $$;

-- The A113 auto-retire was never a staff decision.
UPDATE check_item_reviews SET status = 'quarantined'
 WHERE status = 'retired' AND decided_by = 'reports';

-- The staff holds. A course item's lint_flags with its staff-hold code set to
-- what its decision says: 'reports_threshold' while 'quarantined',
-- 'staff_retired' while 'retired', neither otherwise; every other code, and
-- their order, kept (the staff codes are stored last, after A124's key holds:
-- learning/checks.py HOLD_FLAGS). A never-linted row (NULL) stays NULL unless a
-- hold must be written onto it. Pure.
CREATE OR REPLACE FUNCTION check_item_hold_flags(p_flags text[], p_status text)
RETURNS text[]
LANGUAGE sql
IMMUTABLE
SET search_path = public, pg_temp
AS $$
  SELECT CASE p_status
    WHEN 'quarantined' THEN
      coalesce(array_remove(array_remove(p_flags, 'reports_threshold'), 'staff_retired'), '{}'::text[])
        || 'reports_threshold'::text
    WHEN 'retired' THEN
      coalesce(array_remove(array_remove(p_flags, 'reports_threshold'), 'staff_retired'), '{}'::text[])
        || 'staff_retired'::text
    ELSE array_remove(array_remove(p_flags, 'reports_threshold'), 'staff_retired')
  END
$$;

-- Every row written after a decision carries the decision's hold. A row
-- JOINING a course item (an insert, or a move to another course item) first
-- takes the item's lock SHARED — a decision in flight holds it exclusively —
-- so either the decision's own UPDATE sees this row or this row sees the
-- decision. A row already in the course item takes no lock (its row lock is
-- held before a BEFORE trigger runs, and the decision updates that row while
-- holding the item lock: taking the lock here could deadlock); the status read
-- below is a fresh snapshot, and a decision that commits after it updates this
-- row once this write commits, so the last writer is always the derivation.
CREATE OR REPLACE FUNCTION check_items_staff_hold()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
  v_status text;
BEGIN
  IF TG_OP = 'INSERT' OR NEW.course_id IS DISTINCT FROM OLD.course_id
     OR NEW.question_hash IS DISTINCT FROM OLD.question_hash THEN
    PERFORM pg_advisory_xact_lock_shared(
      hashtextextended('check-item-review:' || NEW.course_id || ':' || NEW.question_hash, 0));
  END IF;
  SELECT r.status INTO v_status
    FROM check_item_reviews r
   WHERE r.course_id = NEW.course_id AND r.question_hash = NEW.question_hash;
  NEW.lint_flags := check_item_hold_flags(NEW.lint_flags, v_status);
  RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS check_items_staff_hold ON check_items;
CREATE TRIGGER check_items_staff_hold
  BEFORE INSERT OR UPDATE OF lint_flags, course_id, question_hash ON check_items
  FOR EACH ROW EXECUTE FUNCTION check_items_staff_hold();

-- Every stored row of a decided course item, held as its decision says (the
-- retired-but-still-stored rows of an unfinished retire included).
UPDATE check_items c
   SET lint_flags = check_item_hold_flags(c.lint_flags, r.status)
  FROM check_item_reviews r
 WHERE r.course_id = c.course_id AND r.question_hash = c.question_hash
   AND c.lint_flags IS DISTINCT FROM check_item_hold_flags(c.lint_flags, r.status);

-- One report. Returns first_report (this student had not reported the item
-- before; a repeat records nothing), reporters (distinct reporters of the
-- course item since its last approval) and quarantine (this report is the one
-- that reached p_min_reporters on an item neither quarantined nor retired: it
-- is quarantined now, and every stored row of it held — `reports_threshold` —
-- in this same transaction). Under the per-item advisory lock, so of reporters
-- arriving together exactly one is told it quarantined the item.
CREATE OR REPLACE FUNCTION check_item_report_quarantine(
  p_user_id text,
  p_course_id text,
  p_question_hash text,
  p_reason text,
  p_surface text,
  p_min_reporters integer
)
RETURNS TABLE (first_report boolean, reporters integer, quarantine boolean)
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
  v_first boolean;
  v_status text;
  v_approved timestamptz;
  v_count integer;
BEGIN
  IF coalesce(p_user_id, '') = '' OR coalesce(p_course_id, '') = ''
     OR coalesce(p_question_hash, '') = '' OR coalesce(p_min_reporters, 0) < 1 THEN
    RAISE EXCEPTION 'Invalid check item report';
  END IF;
  PERFORM pg_advisory_xact_lock(
    hashtextextended('check-item-review:' || p_course_id || ':' || p_question_hash, 0));
  INSERT INTO check_item_reports (user_id, question_hash, course_id, reason, surface, created_at)
  VALUES (p_user_id, p_question_hash, p_course_id, p_reason, p_surface, clock_timestamp())
  ON CONFLICT (user_id, question_hash) DO NOTHING;
  v_first := FOUND;
  SELECT r.status, r.approved_at INTO v_status, v_approved
    FROM check_item_reviews r
   WHERE r.course_id = p_course_id AND r.question_hash = p_question_hash;
  SELECT count(*)::integer INTO v_count
    FROM check_item_reports c
   WHERE c.course_id = p_course_id AND c.question_hash = p_question_hash
     AND (v_approved IS NULL OR c.created_at > v_approved);
  first_report := v_first;
  reporters := v_count;
  quarantine := v_first AND v_count >= p_min_reporters
    AND v_status IS DISTINCT FROM 'quarantined' AND v_status IS DISTINCT FROM 'retired';
  IF quarantine THEN
    INSERT INTO check_item_reviews (course_id, question_hash, status, decided_by, reviewed_by, reviewed_at)
    VALUES (p_course_id, p_question_hash, 'quarantined', 'reports', NULL, clock_timestamp())
    ON CONFLICT (course_id, question_hash) DO UPDATE
      SET status = 'quarantined', decided_by = 'reports', reviewed_by = NULL,
          reviewed_at = EXCLUDED.reviewed_at;
    UPDATE check_items c
       SET lint_flags = check_item_hold_flags(c.lint_flags, 'quarantined')
     WHERE c.course_id = p_course_id AND c.question_hash = p_question_hash
       AND c.lint_flags IS DISTINCT FROM check_item_hold_flags(c.lint_flags, 'quarantined');
  END IF;
  RETURN NEXT;
END
$$;

-- The A113 signature, for a backend deployed before this migration: the same
-- report, and never a retire (a report alone no longer deletes anything).
CREATE OR REPLACE FUNCTION check_item_report(
  p_user_id text,
  p_course_id text,
  p_question_hash text,
  p_reason text,
  p_surface text,
  p_min_reporters integer
)
RETURNS TABLE (first_report boolean, reporters integer, retire boolean)
LANGUAGE sql
SET search_path = public, pg_temp
AS $$
  SELECT q.first_report, q.reporters, false
    FROM check_item_report_quarantine(
      p_user_id, p_course_id, p_question_hash, p_reason, p_surface, p_min_reporters) q
$$;

-- A staff decision ('approved' | 'retired') under the same lock. Returns
-- previous (the status before, NULL for none) and applied (false only when
-- approving an item already retired: a retire is final). An approval clears a
-- quarantine and records approved_at, from which reporters count afresh. The
-- course item's stored rows take the decision's hold in this same
-- transaction: an approval lifts `reports_threshold`, a retire holds every row
-- (`staff_retired`) until the void and the delete finish.
CREATE OR REPLACE FUNCTION check_item_review_decide(
  p_course_id text,
  p_question_hash text,
  p_status text,
  p_reviewed_by text
)
RETURNS TABLE (previous text, applied boolean)
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
  v_prev text;
  v_now timestamptz;
BEGIN
  IF coalesce(p_course_id, '') = '' OR coalesce(p_question_hash, '') = ''
     OR coalesce(p_status, '') NOT IN ('approved', 'retired') THEN
    RAISE EXCEPTION 'Invalid check item review';
  END IF;
  PERFORM pg_advisory_xact_lock(
    hashtextextended('check-item-review:' || p_course_id || ':' || p_question_hash, 0));
  v_now := clock_timestamp();
  SELECT r.status INTO v_prev
    FROM check_item_reviews r
   WHERE r.course_id = p_course_id AND r.question_hash = p_question_hash;
  previous := v_prev;
  applied := NOT (v_prev IS NOT DISTINCT FROM 'retired' AND p_status = 'approved');
  IF applied THEN
    INSERT INTO check_item_reviews
      (course_id, question_hash, status, decided_by, reviewed_by, reviewed_at, approved_at)
    VALUES (p_course_id, p_question_hash, p_status, 'admin', p_reviewed_by, v_now,
            CASE WHEN p_status = 'approved' THEN v_now END)
    ON CONFLICT (course_id, question_hash) DO UPDATE
      SET status = EXCLUDED.status, decided_by = 'admin', reviewed_by = EXCLUDED.reviewed_by,
          reviewed_at = EXCLUDED.reviewed_at,
          approved_at = CASE WHEN EXCLUDED.status = 'approved' THEN EXCLUDED.approved_at
                             ELSE check_item_reviews.approved_at END;
    UPDATE check_items c
       SET lint_flags = check_item_hold_flags(c.lint_flags, p_status)
     WHERE c.course_id = p_course_id AND c.question_hash = p_question_hash
       AND c.lint_flags IS DISTINCT FROM check_item_hold_flags(c.lint_flags, p_status);
  END IF;
  RETURN NEXT;
END
$$;

-- ── 2. the journal's replay inputs ──────────────────────────────────────────

ALTER TABLE node_mastery_events ADD COLUMN IF NOT EXISTS retention double precision;
ALTER TABLE node_mastery_events ADD COLUMN IF NOT EXISTS same_session_recheck boolean;
ALTER TABLE node_mastery_events ADD COLUMN IF NOT EXISTS propagated_to jsonb;

-- NOT VALID: every existing row is NULL in these columns, and a validating ADD
-- would hold ACCESS EXCLUSIVE on the journal for a scan that buys nothing (the
-- 20261108050630 choice). New rows are checked either way.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conrelid = 'public.node_mastery_events'::regclass
       AND conname = 'node_mastery_events_retention_check'
  ) THEN
    ALTER TABLE public.node_mastery_events
      ADD CONSTRAINT node_mastery_events_retention_check
      CHECK (retention IS NULL OR (retention > 0 AND retention <= 1)) NOT VALID;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conrelid = 'public.node_mastery_events'::regclass
       AND conname = 'node_mastery_events_propagated_to_check'
  ) THEN
    ALTER TABLE public.node_mastery_events
      ADD CONSTRAINT node_mastery_events_propagated_to_check
      CHECK (propagated_to IS NULL OR jsonb_typeof(propagated_to) = 'array') NOT VALID;
  END IF;
END $$;

-- ── 3. the void record ──────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS learning_evidence_voids (
  event_id         text        PRIMARY KEY REFERENCES node_mastery_events(id) ON DELETE CASCADE,
  user_id          text        NOT NULL,
  node_id          text        NOT NULL,
  course_id        text        NOT NULL,
  question_hash    text        NOT NULL,
  check_item_id    text        NOT NULL,
  session_id       text,
  event_created_at timestamptz NOT NULL,  -- the voided row's journal time
  reason           text        NOT NULL CHECK (reason IN ('item_retired')),
  operation_id     uuid        NOT NULL,
  voided_at        timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS learning_evidence_voids_user_idx ON learning_evidence_voids (user_id);
CREATE INDEX IF NOT EXISTS learning_evidence_voids_node_idx ON learning_evidence_voids (node_id);
CREATE INDEX IF NOT EXISTS learning_evidence_voids_item_idx
  ON learning_evidence_voids (course_id, question_hash);
CREATE INDEX IF NOT EXISTS learning_evidence_voids_time_idx
  ON learning_evidence_voids (event_created_at);

-- Append-only: a void is never edited. (A delete happens only by cascade, when
-- its journal row goes with the student's node or account.)
CREATE OR REPLACE FUNCTION learning_evidence_voids_append_only()
RETURNS trigger LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
BEGIN
  RAISE EXCEPTION 'learning_evidence_voids is append-only';
END
$$;
DROP TRIGGER IF EXISTS learning_evidence_voids_no_update ON learning_evidence_voids;
CREATE TRIGGER learning_evidence_voids_no_update BEFORE UPDATE ON learning_evidence_voids
  FOR EACH ROW EXECUTE FUNCTION learning_evidence_voids_append_only();

-- ── 6. misconception support ────────────────────────────────────────────────

ALTER TABLE misconceptions ADD COLUMN IF NOT EXISTS resolved_reason text;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conrelid = 'public.misconceptions'::regclass
       AND conname = 'misconceptions_resolved_reason_check'
  ) THEN
    ALTER TABLE public.misconceptions
      ADD CONSTRAINT misconceptions_resolved_reason_check
      CHECK (resolved_reason IS NULL OR resolved_reason IN ('evidence_void'));
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS misconception_attempts (
  id               bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  misconception_id text        NOT NULL REFERENCES misconceptions(id) ON DELETE CASCADE,
  course_id        text,
  question_hash    text,        -- NULL: the attempt's item is unknown
  check_item_id    text,
  recorded_at      timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS misconception_attempts_misconception_idx
  ON misconception_attempts (misconception_id);

-- Insert-or-increment as before (20260929143810), plus the attempt's support
-- row — and nothing at all for an attempt graded against an item staff
-- retired (its evidence is void, so it supports nothing).
CREATE OR REPLACE FUNCTION misconception_record(
  p_id text, p_user_id text, p_node_id text, p_check_item_id text,
  p_wrong_key text, p_evidence_text text, p_question_hash text
)
RETURNS TABLE (id text, count int)
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
#variable_conflict use_column
DECLARE
  v_course text;
  v_id text;
  v_count int;
BEGIN
  SELECT g.course_id INTO v_course
    FROM graph_nodes g WHERE g.id = p_node_id AND g.user_id = p_user_id;
  IF p_question_hash IS NOT NULL AND v_course IS NOT NULL THEN
    PERFORM pg_advisory_xact_lock_shared(
      hashtextextended('check-item-review:' || v_course || ':' || p_question_hash, 0));
    IF EXISTS (
      SELECT 1 FROM check_item_reviews r
       WHERE r.course_id = v_course AND r.question_hash = p_question_hash
         AND r.status = 'retired'
    ) THEN
      RETURN;
    END IF;
  END IF;
  INSERT INTO misconceptions AS m
    (id, user_id, node_id, check_item_id, wrong_key, evidence_text, count)
  VALUES (p_id, p_user_id, p_node_id, p_check_item_id, p_wrong_key, p_evidence_text, 1)
  ON CONFLICT (user_id, node_id, wrong_key) WHERE resolved_at IS NULL
  DO UPDATE SET count = m.count + 1,
                last_seen_at = now(),
                check_item_id = EXCLUDED.check_item_id,
                evidence_text = EXCLUDED.evidence_text
  RETURNING m.id, m.count INTO v_id, v_count;
  INSERT INTO misconception_attempts (misconception_id, course_id, question_hash, check_item_id)
  VALUES (v_id, v_course, p_question_hash, p_check_item_id);
  id := v_id;
  count := v_count;
  RETURN NEXT;
END
$$;

-- The 20260929143810 signature, for a backend deployed before this migration:
-- the item's hash is looked up from its stored row (NULL when it is gone).
CREATE OR REPLACE FUNCTION misconception_record(
  p_id text, p_user_id text, p_node_id text, p_check_item_id text,
  p_wrong_key text, p_evidence_text text
)
RETURNS TABLE (id text, count int)
LANGUAGE sql
SET search_path = public, pg_temp
AS $$
  SELECT r.id, r.count
    FROM misconception_record(
      p_id, p_user_id, p_node_id, p_check_item_id, p_wrong_key, p_evidence_text,
      (SELECT ci.question_hash FROM check_items ci WHERE ci.id = p_check_item_id)) r
$$;

-- ── 4. the evidence commit ──────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION learning_evidence_commit(
    p_user_id text,p_course_id text,p_operation_id uuid,p_input_fingerprint text,p_plan jsonb
) RETURNS jsonb LANGUAGE plpgsql SET search_path=public,pg_temp
SET lock_timeout='2s' SET statement_timeout='10s' AS $$
DECLARE r learning_evidence_operations%ROWTYPE; x jsonb; v bigint; ids text[];
    grade_ids text[]; es jsonb; n graph_nodes%ROWTYPE; s learner_state%ROWTYPE;
    ev node_mastery_events%ROWTYPE; obs jsonb; expected_count bigint; actual_count bigint;
    item record; retired_items jsonb;
BEGIN
    IF p_user_id IS NULL OR p_user_id='' OR p_operation_id IS NULL
       OR p_input_fingerprint IS NULL OR p_input_fingerprint !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(p_plan) IS DISTINCT FROM 'object'
       OR (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(p_plan) k)
          IS DISTINCT FROM ARRAY['changes','checks','edges','events','mirrors','nodes','observed_at','state_rows','states_expected']::text[]
       OR EXISTS(SELECT 1 FROM jsonb_each(p_plan) p WHERE p.key<>'observed_at' AND jsonb_typeof(p.value)<>'array')
       OR jsonb_typeof(p_plan->'observed_at') NOT IN ('null','string') THEN
        RAISE EXCEPTION 'Invalid evidence transaction envelope';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('learning-evidence:'||p_user_id,0));
    SELECT * INTO r FROM learning_evidence_operations WHERE operation_id=p_operation_id;
    IF FOUND THEN
        IF r.user_id IS DISTINCT FROM p_user_id OR r.course_id IS DISTINCT FROM p_course_id
           OR r.input_fingerprint IS DISTINCT FROM p_input_fingerprint OR r.plan IS DISTINCT FROM p_plan THEN
            RETURN jsonb_build_object('status','conflict');
        END IF;
        RETURN jsonb_build_object('status','replay','receipt',jsonb_build_object(
            'operation_id',r.operation_id,'user_id',r.user_id,'course_id',r.course_id,
            'input_fingerprint',r.input_fingerprint,'changes',r.changes,'posteriors',(
                SELECT jsonb_object_agg(value->>'id',value->'mastery_score') FROM jsonb_array_elements(r.plan->'mirrors')),
            'observations',(SELECT coalesce(jsonb_agg(entry.value->'planning_observation' ORDER BY entry.position),'[]')
                FROM jsonb_array_elements(r.plan->'events') WITH ORDINALITY entry(value,position)
                WHERE jsonb_typeof(entry.value->'planning_observation')='object')));
    END IF;
    -- §13 A123: a check item staff retired takes no new evidence. A SHARED lock
    -- per graded item (sorted), against check_item_review_decide's EXCLUSIVE one:
    -- a retire decided while this grade was in flight waits for its commit (and
    -- the void sweep then finds the row); a grade arriving after it is refused.
    FOR item IN
        SELECT DISTINCT g.course_id AS course_id, e.value->>'question_hash' AS question_hash
          FROM jsonb_array_elements(p_plan->'events') e
          JOIN graph_nodes g ON g.id = e.value->>'node_id'
         WHERE jsonb_typeof(e.value->'check_item_id') = 'string'
           AND jsonb_typeof(e.value->'question_hash') = 'string'
           AND g.course_id IS NOT NULL
         ORDER BY 1, 2
    LOOP
        PERFORM pg_advisory_xact_lock_shared(
            hashtextextended('check-item-review:'||item.course_id||':'||item.question_hash,0));
    END LOOP;
    SELECT coalesce(jsonb_agg(jsonb_build_object('course_id',q.course_id,'question_hash',q.question_hash)
               ORDER BY q.course_id,q.question_hash),'[]') INTO retired_items
      FROM (SELECT DISTINCT g.course_id AS course_id, e.value->>'question_hash' AS question_hash
              FROM jsonb_array_elements(p_plan->'events') e
              JOIN graph_nodes g ON g.id = e.value->>'node_id'
             WHERE jsonb_typeof(e.value->'check_item_id') = 'string'
               AND jsonb_typeof(e.value->'question_hash') = 'string'
               AND g.course_id IS NOT NULL) q
     WHERE EXISTS(SELECT 1 FROM check_item_reviews cr WHERE cr.course_id=q.course_id
                  AND cr.question_hash=q.question_hash AND cr.status='retired');
    IF jsonb_array_length(retired_items) > 0 THEN
        RETURN jsonb_build_object('status','retired','items',retired_items);
    END IF;
    SELECT array_agg(value->>'id' ORDER BY value->>'id') INTO ids FROM jsonb_array_elements(p_plan->'nodes');
    SELECT array_agg(DISTINCT value->>'node_id' ORDER BY value->>'node_id') INTO grade_ids
        FROM jsonb_array_elements(p_plan->'events');
    IF coalesce(cardinality(ids),0)=0 OR coalesce(cardinality(grade_ids),0)=0
       OR cardinality(ids)<>(SELECT count(DISTINCT unnest) FROM unnest(ids))
       OR jsonb_array_length(p_plan->'changes')<>jsonb_array_length(p_plan->'events') THEN
        RAISE EXCEPTION 'Invalid evidence transaction members';
    END IF;
    -- Short, bounded coarse lock closes phantom edge inserts AND relation/
    -- endpoint edits/deletes from legacy writers. Acquire it before node locks
    -- so a legacy edge FK check cannot form a node/table lock-order inversion.
    LOCK TABLE graph_edges IN SHARE MODE;
    PERFORM 1 FROM graph_nodes WHERE id=ANY(ids) ORDER BY id FOR UPDATE;
    IF (SELECT count(*) FROM graph_nodes WHERE id=ANY(ids) AND user_id=p_user_id
        AND (p_course_id IS NULL OR course_id=p_course_id))<>cardinality(ids) THEN
        RETURN jsonb_build_object('status','ownership');
    END IF;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'nodes') LOOP
        IF jsonb_typeof(x->'version') IS DISTINCT FROM 'number' OR (x->>'version') !~ '^[0-9]+$' THEN
            RAISE EXCEPTION 'Invalid graph version';
        END IF;
        SELECT evidence_version INTO v FROM graph_nodes WHERE id=x->>'id';
        IF v IS DISTINCT FROM (x->>'version')::bigint THEN RETURN jsonb_build_object('status','stale'); END IF;
    END LOOP;
    SELECT coalesce(jsonb_agg(jsonb_build_object('source',e.source_node_id,'target',e.target_node_id)
               ORDER BY e.source_node_id,e.target_node_id),'[]') INTO es
      FROM graph_edges e JOIN graph_nodes a ON a.id=e.source_node_id JOIN graph_nodes b ON b.id=e.target_node_id
      WHERE e.user_id=p_user_id AND e.relationship_type='prerequisite'
        AND a.user_id=p_user_id AND b.user_id=p_user_id AND a.course_id IS NOT DISTINCT FROM b.course_id
        AND (p_course_id IS NULL OR a.course_id=p_course_id)
        AND (e.source_node_id=ANY(grade_ids) OR e.target_node_id=ANY(grade_ids));
    IF es IS DISTINCT FROM p_plan->'edges' THEN RETURN jsonb_build_object('status','stale'); END IF;
    PERFORM 1 FROM learner_state WHERE user_id=p_user_id AND node_id=ANY(ids) ORDER BY node_id FOR UPDATE;
    IF jsonb_array_length(p_plan->'states_expected')<>cardinality(ids)
       OR (SELECT count(DISTINCT value->>'node_id') FROM jsonb_array_elements(p_plan->'states_expected'))<>cardinality(ids)
       OR EXISTS(SELECT 1 FROM jsonb_array_elements(p_plan->'states_expected') WHERE NOT (value->>'node_id'=ANY(ids))) THEN
        RAISE EXCEPTION 'Invalid learner-state snapshot';
    END IF;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'states_expected') LOOP
        IF jsonb_typeof(x->'version') NOT IN ('number','null')
           OR (x->>'version' IS NOT NULL AND (x->>'version') !~ '^[0-9]+$') THEN
            RAISE EXCEPTION 'Invalid learner-state version';
        END IF;
        SELECT evidence_version INTO v FROM learner_state WHERE user_id=p_user_id AND node_id=x->>'node_id';
        IF v IS DISTINCT FROM (x->>'version')::bigint THEN RETURN jsonb_build_object('status','stale'); END IF;
    END LOOP;
    IF p_plan->>'observed_at' IS NOT NULL AND EXISTS(
        SELECT 1 FROM learner_state l WHERE l.user_id=p_user_id
        AND l.node_id IN (SELECT value->>'node_id' FROM jsonb_array_elements(p_plan->'state_rows'))
        AND (l.last_evidence_at > (p_plan->>'observed_at')::timestamptz
             OR l.evidence_touch_at > (p_plan->>'observed_at')::timestamptz)
    ) THEN RETURN jsonb_build_object('status','superseded'); END IF;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'checks') LOOP
        IF jsonb_typeof(x->'count') IS DISTINCT FROM 'number'
           OR (x->>'count') !~ '^[0-9]+$'
           OR jsonb_typeof(x->'global_count') IS DISTINCT FROM 'number'
           OR (x->>'global_count') !~ '^[0-9]+$' THEN
            RAISE EXCEPTION 'Invalid exposure snapshot';
        END IF;
        SELECT count(*) INTO actual_count FROM node_mastery_events e JOIN graph_nodes g ON g.id=e.node_id
            WHERE g.user_id=p_user_id AND e.event_type='evidence' AND e.session_id=x->>'session_id'
              AND e.question_hash=x->>'question_hash';
        IF actual_count IS DISTINCT FROM (x->>'count')::bigint THEN RETURN jsonb_build_object('status','stale'); END IF;
        SELECT count(*) INTO actual_count FROM node_mastery_events e JOIN graph_nodes g ON g.id=e.node_id
            WHERE g.user_id=p_user_id AND e.event_type='evidence' AND e.question_hash=x->>'question_hash';
        IF actual_count IS DISTINCT FROM (x->>'global_count')::bigint THEN RETURN jsonb_build_object('status','stale'); END IF;
    END LOOP;
    IF jsonb_array_length(p_plan->'state_rows')=0
       OR jsonb_array_length(p_plan->'state_rows')<>jsonb_array_length(p_plan->'mirrors')
       OR (SELECT count(DISTINCT value->>'node_id') FROM jsonb_array_elements(p_plan->'state_rows'))<>jsonb_array_length(p_plan->'state_rows')
       OR (SELECT count(DISTINCT value->>'id') FROM jsonb_array_elements(p_plan->'mirrors'))<>jsonb_array_length(p_plan->'mirrors')
       OR EXISTS(SELECT 1 FROM unnest(grade_ids) id WHERE NOT EXISTS(
            SELECT 1 FROM jsonb_array_elements(p_plan->'state_rows') state_entry(value)
            WHERE state_entry.value->>'node_id'=id)) THEN
        RAISE EXCEPTION 'Invalid transaction row sets';
    END IF;
    -- Validate the WHOLE plan before its first mutation. SQL does no BKT,
    -- FSRS, weighting, threshold or propagation arithmetic.
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'state_rows') LOOP
        s := jsonb_populate_record(NULL::learner_state,x);
        IF s.user_id IS DISTINCT FROM p_user_id OR NOT(s.node_id=ANY(ids))
           OR s.p_known IS NULL OR NOT(s.p_known BETWEEN 0 AND 1)
           OR s.updated_at IS NULL
           OR s.n_strong_unassisted<0 OR s.streak_unassisted<0 OR s.max_streak_unassisted<0 OR s.opps<0
           OR EXISTS(SELECT 1 FROM jsonb_object_keys(x) k WHERE k NOT IN (
                'user_id','node_id','p_known','n_strong_unassisted','streak_unassisted','max_streak_unassisted','opps',
                'fsrs_d','fsrs_s','fsrs_last_review_at','fsrs_due_at','last_evidence_at','updated_at'))
           OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_plan->'mirrors') m WHERE m->>'id'=s.node_id) THEN
            RAISE EXCEPTION 'Invalid transaction learner state';
        END IF;
    END LOOP;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'events') LOOP
        ev := jsonb_populate_record(NULL::node_mastery_events,x);
        IF ev.id IS NULL OR NOT(ev.node_id=ANY(grade_ids)) OR NOT(ev.node_id=ANY(ids))
           OR ev.event_type IS DISTINCT FROM 'evidence' OR ev.correct IS NULL
           OR ev.p_before IS NULL OR NOT(ev.p_before BETWEEN 0 AND 1)
           OR ev.p_after IS NULL OR NOT(ev.p_after BETWEEN 0 AND 1)
           OR ev.weight IS NULL OR NOT(ev.weight BETWEEN 0 AND 1)
           OR ev.created_at IS NULL OR ev.evidence_seq IS NULL OR ev.evidence_seq<0
           OR jsonb_typeof(x->'correct') IS DISTINCT FROM 'boolean'
           OR jsonb_typeof(x->'assisted') IS DISTINCT FROM 'boolean'
           -- §13 A123: the replay inputs, when present, are well formed
           OR (x ? 'retention' AND jsonb_typeof(x->'retention') NOT IN ('number','null'))
           OR (ev.retention IS NOT NULL AND NOT (ev.retention > 0 AND ev.retention <= 1))
           OR (x ? 'same_session_recheck' AND jsonb_typeof(x->'same_session_recheck') NOT IN ('boolean','null'))
           OR (x ? 'propagated_to' AND jsonb_typeof(x->'propagated_to') NOT IN ('array','null'))
           OR (jsonb_typeof(x->'propagated_to') = 'array' AND EXISTS(
                SELECT 1 FROM jsonb_array_elements(x->'propagated_to') t
                 WHERE jsonb_typeof(t) IS DISTINCT FROM 'string' OR NOT ((t #>> '{}')=ANY(ids))
                    OR (t #>> '{}')=ev.node_id
                    OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_plan->'state_rows') sr
                                   WHERE sr->>'node_id'=(t #>> '{}'))))
           OR EXISTS(SELECT 1 FROM jsonb_object_keys(x) k WHERE k NOT IN (
                'id','node_id','delta','reason','created_at','event_type','channel','correct','weight','assisted','max_rung',
                'p_before','p_after','session_id','check_item_id','question_hash','confidence','grader_backend','evidence_seq','planning_observation',
                'retention','same_session_recheck','propagated_to')) THEN
            RAISE EXCEPTION 'Invalid transaction evidence';
        END IF;
        obs := ev.planning_observation;
        IF obs IS NOT NULL AND (
            jsonb_typeof(obs) IS DISTINCT FROM 'object'
            OR obs->>'node_id' IS DISTINCT FROM ev.node_id OR obs->>'question_hash' IS DISTINCT FROM ev.question_hash
            OR obs->>'check_item_id' IS DISTINCT FROM ev.check_item_id OR obs->>'channel' IS DISTINCT FROM ev.channel
            OR obs->'correct' IS DISTINCT FROM to_jsonb(ev.correct)
            OR obs->'assisted' IS DISTINCT FROM to_jsonb(ev.assisted)
            OR obs->'max_rung' IS DISTINCT FROM to_jsonb(ev.max_rung)
            OR jsonb_typeof(obs->'independent') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'same_session_recheck') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'idk') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'synthetic_idk') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'previously_seen') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'difficulty') IS DISTINCT FROM 'number'
            OR (obs->>'difficulty') NOT IN ('1','2','3')
            OR NOT(obs ?& ARRAY['check_item_id','difficulty','synthetic_idk','previously_seen','node_id',
                'question_hash','channel','correct','idk','assisted','max_rung','same_session_recheck','independent'])
            OR EXISTS(SELECT 1 FROM jsonb_object_keys(obs) k WHERE k NOT IN (
                'check_item_id','difficulty','synthetic_idk','previously_seen','node_id','question_hash',
                'channel','correct','idk','assisted','max_rung','same_session_recheck','independent'))
            OR (obs->>'idk')::boolean AND ev.correct
            OR (obs->>'synthetic_idk')::boolean AND NOT (obs->>'idk')::boolean
            OR ev.assisted IS DISTINCT FROM (ev.max_rung>0)
            OR (obs->>'independent')::boolean IS DISTINCT FROM (NOT (
                ev.max_rung>0 OR ev.assisted OR (obs->>'same_session_recheck')::boolean
                OR (obs->>'synthetic_idk')::boolean OR (obs->>'previously_seen')::boolean))) THEN
            RAISE EXCEPTION 'Invalid final planning provenance';
        END IF;
    END LOOP;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'state_rows') LOOP
        s := jsonb_populate_record(NULL::learner_state,x);
        INSERT INTO learner_state(user_id,node_id,p_known,n_strong_unassisted,streak_unassisted,max_streak_unassisted,
            opps,fsrs_d,fsrs_s,fsrs_last_review_at,fsrs_due_at,last_evidence_at,updated_at,evidence_touch_at)
        VALUES(s.user_id,s.node_id,s.p_known,s.n_strong_unassisted,s.streak_unassisted,s.max_streak_unassisted,
            s.opps,s.fsrs_d,s.fsrs_s,s.fsrs_last_review_at,s.fsrs_due_at,s.last_evidence_at,s.updated_at,s.updated_at)
        ON CONFLICT(user_id,node_id) DO UPDATE SET p_known=EXCLUDED.p_known,n_strong_unassisted=EXCLUDED.n_strong_unassisted,
            streak_unassisted=EXCLUDED.streak_unassisted,max_streak_unassisted=EXCLUDED.max_streak_unassisted,
            opps=EXCLUDED.opps,fsrs_d=EXCLUDED.fsrs_d,fsrs_s=EXCLUDED.fsrs_s,
            fsrs_last_review_at=EXCLUDED.fsrs_last_review_at,fsrs_due_at=EXCLUDED.fsrs_due_at,
            last_evidence_at=EXCLUDED.last_evidence_at,updated_at=EXCLUDED.updated_at,
            evidence_touch_at=greatest(learner_state.evidence_touch_at,EXCLUDED.evidence_touch_at);
    END LOOP;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'mirrors') LOOP
        IF NOT(x->>'id'=ANY(ids)) OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_plan->'state_rows') t WHERE t->>'node_id'=x->>'id')
           OR jsonb_typeof(x->'mastery_score') IS DISTINCT FROM 'number'
           OR NOT((x->>'mastery_score')::double precision BETWEEN 0 AND 1)
           OR EXISTS(SELECT 1 FROM jsonb_object_keys(x) k WHERE k NOT IN ('id','mastery_score','mastery_tier','times_studied','last_studied_at')) THEN
            RAISE EXCEPTION 'Invalid transaction mirror';
        END IF;
        UPDATE graph_nodes SET mastery_score=(x->>'mastery_score')::double precision,mastery_tier=x->>'mastery_tier',
            times_studied=CASE WHEN x ? 'times_studied' THEN (x->>'times_studied')::int ELSE times_studied END,
            last_studied_at=CASE WHEN x ? 'last_studied_at' THEN (x->>'last_studied_at')::timestamptz ELSE last_studied_at END
            WHERE id=x->>'id' AND user_id=p_user_id;
    END LOOP;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'events') LOOP
        ev := jsonb_populate_record(NULL::node_mastery_events,x);
        INSERT INTO node_mastery_events(id,node_id,delta,reason,created_at,event_type,channel,correct,weight,assisted,max_rung,
            p_before,p_after,session_id,check_item_id,question_hash,confidence,grader_backend,evidence_seq,planning_observation,
            retention,same_session_recheck,propagated_to)
        VALUES(ev.id,ev.node_id,ev.delta,ev.reason,ev.created_at,ev.event_type,ev.channel,ev.correct,ev.weight,ev.assisted,ev.max_rung,
            ev.p_before,ev.p_after,ev.session_id,ev.check_item_id,ev.question_hash,ev.confidence,ev.grader_backend,ev.evidence_seq,ev.planning_observation,
            ev.retention,ev.same_session_recheck,ev.propagated_to);
    END LOOP;
    INSERT INTO learning_evidence_operations(operation_id,user_id,course_id,input_fingerprint,plan,changes)
        VALUES(p_operation_id,p_user_id,p_course_id,p_input_fingerprint,p_plan,p_plan->'changes');
    RETURN learning_evidence_receipt(p_user_id,p_operation_id);
END $$;

-- ── 5. void + recompute ─────────────────────────────────────────────────────

-- The students who still have a NON-void evidence row graded against a course
-- item ({user_id: rows}), whatever the item's status. Read-only.
CREATE OR REPLACE FUNCTION learning_evidence_void_pending(p_course_id text, p_question_hash text)
RETURNS jsonb LANGUAGE plpgsql SET search_path=public,pg_temp
SET statement_timeout='10s' AS $$
DECLARE pending jsonb;
BEGIN
    IF coalesce(p_course_id,'')='' OR coalesce(p_question_hash,'')='' THEN
        RAISE EXCEPTION 'Invalid evidence void item';
    END IF;
    SELECT coalesce(jsonb_object_agg(q.user_id,q.n),'{}') INTO pending
      FROM (SELECT g.user_id AS user_id, count(*) AS n
              FROM node_mastery_events e JOIN graph_nodes g ON g.id=e.node_id
             WHERE g.course_id=p_course_id AND e.question_hash=p_question_hash
               AND e.event_type='evidence' AND e.check_item_id IS NOT NULL
               AND NOT EXISTS(SELECT 1 FROM learning_evidence_voids v WHERE v.event_id=e.id)
             GROUP BY g.user_id) q;
    RETURN jsonb_build_object('status','pending','users',pending);
END $$;

-- One student's course, as one consistent read: every node with its versions,
-- the learner_state rows, the course's prerequisite edges, the WHOLE evidence
-- journal of the course in the readers' total order (created_at, evidence_seq,
-- id) with each row's void flag, the staff-retired items of the course, and the
-- student's open misconceptions on the course with their recorded attempts.
-- JSON aggregates, so PostgREST's row limit cannot truncate it. Read-only.
CREATE OR REPLACE FUNCTION learning_evidence_void_snapshot(
    p_user_id text,p_course_id text,p_question_hash text
) RETURNS jsonb LANGUAGE plpgsql SET search_path=public,pg_temp
SET lock_timeout='2s' SET statement_timeout='10s' AS $$
DECLARE ns jsonb; ss jsonb; es jsonb; js jsonb; rs jsonb; ms jsonb; retired boolean;
BEGIN
    IF coalesce(p_user_id,'')='' OR coalesce(p_course_id,'')='' OR coalesce(p_question_hash,'')='' THEN
        RAISE EXCEPTION 'Invalid evidence void snapshot identity';
    END IF;
    retired := EXISTS(SELECT 1 FROM check_item_reviews WHERE course_id=p_course_id
                      AND question_hash=p_question_hash AND status='retired');
    SELECT coalesce(jsonb_agg(jsonb_build_object('id',n.id,'concept_name',n.concept_name,
        'mastery_score',n.mastery_score,'mastery_tier',n.mastery_tier,
        'evidence_version',n.evidence_version) ORDER BY n.id),'[]') INTO ns
      FROM graph_nodes n WHERE n.user_id=p_user_id AND n.course_id=p_course_id;
    SELECT coalesce(jsonb_agg(to_jsonb(s) ORDER BY s.node_id),'[]') INTO ss
      FROM learner_state s JOIN graph_nodes n ON n.id=s.node_id
     WHERE s.user_id=p_user_id AND n.user_id=p_user_id AND n.course_id=p_course_id;
    SELECT coalesce(jsonb_agg(jsonb_build_object('source',e.source_node_id,'target',e.target_node_id)
               ORDER BY e.source_node_id,e.target_node_id),'[]') INTO es
      FROM graph_edges e JOIN graph_nodes a ON a.id=e.source_node_id JOIN graph_nodes b ON b.id=e.target_node_id
     WHERE e.user_id=p_user_id AND e.relationship_type='prerequisite'
       AND a.user_id=p_user_id AND b.user_id=p_user_id
       AND a.course_id=p_course_id AND b.course_id=p_course_id;
    SELECT coalesce(jsonb_agg(jsonb_build_object('id',e.id,'node_id',e.node_id,'created_at',e.created_at,
        'evidence_seq',e.evidence_seq,'channel',e.channel,'correct',e.correct,'weight',e.weight,
        'assisted',e.assisted,'max_rung',e.max_rung,'reason',e.reason,'confidence',e.confidence,
        'session_id',e.session_id,'question_hash',e.question_hash,'check_item_id',e.check_item_id,
        'planning_recheck',e.planning_observation->'same_session_recheck',
        'same_session_recheck',e.same_session_recheck,'retention',e.retention,
        'propagated_to',e.propagated_to,'void',(v.event_id IS NOT NULL))
        ORDER BY e.created_at,e.evidence_seq NULLS LAST,e.id),'[]') INTO js
      FROM node_mastery_events e JOIN graph_nodes n ON n.id=e.node_id
      LEFT JOIN learning_evidence_voids v ON v.event_id=e.id
     WHERE n.user_id=p_user_id AND n.course_id=p_course_id AND e.event_type='evidence';
    SELECT coalesce(jsonb_agg(r.question_hash ORDER BY r.question_hash),'[]') INTO rs
      FROM check_item_reviews r WHERE r.course_id=p_course_id AND r.status='retired';
    SELECT coalesce(jsonb_agg(jsonb_build_object('id',m.id,'node_id',m.node_id,'count',m.count,
        'check_item_id',m.check_item_id,'attempts',(
            SELECT coalesce(jsonb_agg(jsonb_build_object('course_id',a.course_id,
                'question_hash',a.question_hash,'check_item_id',a.check_item_id) ORDER BY a.id),'[]')
              FROM misconception_attempts a WHERE a.misconception_id=m.id)) ORDER BY m.id),'[]') INTO ms
      FROM misconceptions m JOIN graph_nodes n ON n.id=m.node_id
     WHERE m.user_id=p_user_id AND n.user_id=p_user_id AND n.course_id=p_course_id
       AND m.resolved_at IS NULL;
    RETURN jsonb_build_object('status','snapshot','retired',retired,'nodes',ns,'states',ss,
        'edges',es,'journal',js,'retired_hashes',rs,'misconceptions',ms);
END $$;

-- One student's void + recompute, all or nothing. The plan (computed by the
-- Python replay, learning/evidence_replay.py, from a void snapshot):
--   voids           every evidence id of this student graded against the item
--   nodes           [{id, version}]   the recomputed nodes' graph versions
--   states_expected [{node_id, version|null}]   their learner_state versions
--   edges           the course's prerequisite edges the replay read
--   state_rows      the recomputed learner_state rows (evidence columns only)
--   mirrors         [{id, mastery_score, mastery_tier}]
--   misconceptions  [{id, count}]     open rows every attempt of which is void
-- A row, mirror or misconception equal to what is stored is not written, so a
-- re-run of the same plan changes nothing (no version moves either).
CREATE OR REPLACE FUNCTION learning_evidence_void_commit(
    p_user_id text,p_course_id text,p_question_hash text,p_operation_id uuid,p_plan jsonb
) RETURNS jsonb LANGUAGE plpgsql SET search_path=public,pg_temp
SET lock_timeout='2s' SET statement_timeout='10s' AS $$
DECLARE x jsonb; v bigint; ids text[]; void_ids text[]; es jsonb; s learner_state%ROWTYPE;
    n_voided int := 0; n_states int := 0; n_mirrors int := 0; n_misc int := 0; n_rows int;
BEGIN
    IF coalesce(p_user_id,'')='' OR coalesce(p_course_id,'')='' OR coalesce(p_question_hash,'')=''
       OR p_operation_id IS NULL
       OR jsonb_typeof(p_plan) IS DISTINCT FROM 'object'
       OR (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(p_plan) k)
          IS DISTINCT FROM ARRAY['edges','mirrors','misconceptions','nodes','state_rows','states_expected','voids']::text[]
       OR EXISTS(SELECT 1 FROM jsonb_each(p_plan) p WHERE jsonb_typeof(p.value)<>'array') THEN
        RAISE EXCEPTION 'Invalid evidence void envelope';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('learning-evidence:'||p_user_id,0));
    PERFORM pg_advisory_xact_lock_shared(
        hashtextextended('check-item-review:'||p_course_id||':'||p_question_hash,0));
    IF NOT EXISTS(SELECT 1 FROM check_item_reviews WHERE course_id=p_course_id
                  AND question_hash=p_question_hash AND status='retired') THEN
        RETURN jsonb_build_object('status','not_retired');
    END IF;
    IF EXISTS(SELECT 1 FROM jsonb_array_elements(p_plan->'voids') t WHERE jsonb_typeof(t) IS DISTINCT FROM 'string') THEN
        RAISE EXCEPTION 'Invalid evidence void';
    END IF;
    SELECT coalesce(array_agg(DISTINCT t #>> '{}' ORDER BY t #>> '{}'),'{}') INTO void_ids
      FROM jsonb_array_elements(p_plan->'voids') t;
    -- Every void names this student's evidence row graded against this item ...
    IF (SELECT count(*) FROM node_mastery_events e JOIN graph_nodes g ON g.id=e.node_id
         WHERE e.id=ANY(void_ids) AND e.event_type='evidence' AND g.user_id=p_user_id
           AND g.course_id=p_course_id AND e.question_hash=p_question_hash
           AND e.check_item_id IS NOT NULL)<>cardinality(void_ids) THEN
        RAISE EXCEPTION 'Invalid evidence void';
    END IF;
    -- ... and every such row is named (none was journaled since the snapshot).
    IF EXISTS(SELECT 1 FROM node_mastery_events e JOIN graph_nodes g ON g.id=e.node_id
               WHERE e.event_type='evidence' AND g.user_id=p_user_id AND g.course_id=p_course_id
                 AND e.question_hash=p_question_hash AND e.check_item_id IS NOT NULL
                 AND NOT (e.id=ANY(void_ids))) THEN
        RETURN jsonb_build_object('status','stale');
    END IF;
    SELECT coalesce(array_agg(value->>'id' ORDER BY value->>'id'),'{}') INTO ids
      FROM jsonb_array_elements(p_plan->'nodes');
    IF cardinality(ids)<>(SELECT count(DISTINCT u) FROM unnest(ids) u)
       OR jsonb_array_length(p_plan->'states_expected')<>cardinality(ids)
       OR jsonb_array_length(p_plan->'state_rows')<>cardinality(ids)
       OR jsonb_array_length(p_plan->'mirrors')<>cardinality(ids)
       OR EXISTS(SELECT 1 FROM jsonb_array_elements(p_plan->'states_expected') t WHERE NOT ((t->>'node_id')=ANY(ids)))
       OR (SELECT count(DISTINCT t->>'node_id') FROM jsonb_array_elements(p_plan->'states_expected') t)<>cardinality(ids)
       OR EXISTS(SELECT 1 FROM jsonb_array_elements(p_plan->'state_rows') t WHERE NOT ((t->>'node_id')=ANY(ids)))
       OR (SELECT count(DISTINCT t->>'node_id') FROM jsonb_array_elements(p_plan->'state_rows') t)<>cardinality(ids)
       OR EXISTS(SELECT 1 FROM jsonb_array_elements(p_plan->'mirrors') t WHERE NOT ((t->>'id')=ANY(ids)))
       OR (SELECT count(DISTINCT t->>'id') FROM jsonb_array_elements(p_plan->'mirrors') t)<>cardinality(ids) THEN
        RAISE EXCEPTION 'Invalid evidence void row sets';
    END IF;
    LOCK TABLE graph_edges IN SHARE MODE;
    PERFORM 1 FROM graph_nodes WHERE id=ANY(ids) ORDER BY id FOR UPDATE;
    IF (SELECT count(*) FROM graph_nodes WHERE id=ANY(ids) AND user_id=p_user_id
        AND course_id=p_course_id)<>cardinality(ids) THEN
        RETURN jsonb_build_object('status','ownership');
    END IF;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'nodes') LOOP
        IF jsonb_typeof(x->'version') IS DISTINCT FROM 'number' OR (x->>'version') !~ '^[0-9]+$' THEN
            RAISE EXCEPTION 'Invalid graph version';
        END IF;
        SELECT evidence_version INTO v FROM graph_nodes WHERE id=x->>'id';
        IF v IS DISTINCT FROM (x->>'version')::bigint THEN RETURN jsonb_build_object('status','stale'); END IF;
    END LOOP;
    SELECT coalesce(jsonb_agg(jsonb_build_object('source',e.source_node_id,'target',e.target_node_id)
               ORDER BY e.source_node_id,e.target_node_id),'[]') INTO es
      FROM graph_edges e JOIN graph_nodes a ON a.id=e.source_node_id JOIN graph_nodes b ON b.id=e.target_node_id
     WHERE e.user_id=p_user_id AND e.relationship_type='prerequisite'
       AND a.user_id=p_user_id AND b.user_id=p_user_id
       AND a.course_id=p_course_id AND b.course_id=p_course_id;
    IF es IS DISTINCT FROM p_plan->'edges' THEN RETURN jsonb_build_object('status','stale'); END IF;
    PERFORM 1 FROM learner_state WHERE user_id=p_user_id AND node_id=ANY(ids) ORDER BY node_id FOR UPDATE;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'states_expected') LOOP
        IF jsonb_typeof(x->'version') NOT IN ('number','null')
           OR (x->>'version' IS NOT NULL AND (x->>'version') !~ '^[0-9]+$') THEN
            RAISE EXCEPTION 'Invalid learner-state version';
        END IF;
        SELECT evidence_version INTO v FROM learner_state WHERE user_id=p_user_id AND node_id=x->>'node_id';
        IF v IS DISTINCT FROM (x->>'version')::bigint THEN RETURN jsonb_build_object('status','stale'); END IF;
    END LOOP;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'misconceptions') LOOP
        IF jsonb_typeof(x->'id') IS DISTINCT FROM 'string' OR jsonb_typeof(x->'count') IS DISTINCT FROM 'number'
           OR (x->>'count') !~ '^[0-9]+$' THEN
            RAISE EXCEPTION 'Invalid evidence void misconception';
        END IF;
        IF NOT EXISTS(SELECT 1 FROM misconceptions m JOIN graph_nodes g ON g.id=m.node_id
                       WHERE m.id=x->>'id' AND m.user_id=p_user_id AND g.user_id=p_user_id
                         AND g.course_id=p_course_id AND m.resolved_at IS NULL
                         AND m.count=(x->>'count')::int) THEN
            RETURN jsonb_build_object('status','stale');
        END IF;
    END LOOP;
    -- Validate every row before the first write. SQL does no BKT/FSRS arithmetic.
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'state_rows') LOOP
        s := jsonb_populate_record(NULL::learner_state,x);
        IF s.user_id IS DISTINCT FROM p_user_id OR s.p_known IS NULL OR NOT(s.p_known BETWEEN 0 AND 1)
           OR s.updated_at IS NULL
           OR s.n_strong_unassisted IS NULL OR s.streak_unassisted IS NULL
           OR s.max_streak_unassisted IS NULL OR s.opps IS NULL
           OR s.n_strong_unassisted<0 OR s.streak_unassisted<0 OR s.max_streak_unassisted<0 OR s.opps<0
           OR EXISTS(SELECT 1 FROM jsonb_object_keys(x) k WHERE k NOT IN (
                'user_id','node_id','p_known','n_strong_unassisted','streak_unassisted','max_streak_unassisted','opps',
                'fsrs_d','fsrs_s','fsrs_last_review_at','fsrs_due_at','last_evidence_at','updated_at')) THEN
            RAISE EXCEPTION 'Invalid evidence void learner state';
        END IF;
    END LOOP;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'mirrors') LOOP
        IF jsonb_typeof(x->'mastery_score') IS DISTINCT FROM 'number'
           OR NOT((x->>'mastery_score')::double precision BETWEEN 0 AND 1)
           OR jsonb_typeof(x->'mastery_tier') IS DISTINCT FROM 'string'
           OR EXISTS(SELECT 1 FROM jsonb_object_keys(x) k WHERE k NOT IN ('id','mastery_score','mastery_tier')) THEN
            RAISE EXCEPTION 'Invalid evidence void mirror';
        END IF;
    END LOOP;
    INSERT INTO learning_evidence_voids(event_id,user_id,node_id,course_id,question_hash,check_item_id,
        session_id,event_created_at,reason,operation_id)
    SELECT e.id,p_user_id,e.node_id,p_course_id,e.question_hash,e.check_item_id,e.session_id,e.created_at,
           'item_retired',p_operation_id
      FROM node_mastery_events e WHERE e.id=ANY(void_ids)
    ON CONFLICT (event_id) DO NOTHING;
    GET DIAGNOSTICS n_voided = ROW_COUNT;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'state_rows') LOOP
        s := jsonb_populate_record(NULL::learner_state,x);
        -- evidence_touch_at is not moved: a void adds no evidence, so it never
        -- supersedes a grade in flight (that grade re-plans on the version).
        INSERT INTO learner_state AS l(user_id,node_id,p_known,n_strong_unassisted,streak_unassisted,
            max_streak_unassisted,opps,fsrs_d,fsrs_s,fsrs_last_review_at,fsrs_due_at,last_evidence_at,updated_at)
        VALUES(s.user_id,s.node_id,s.p_known,s.n_strong_unassisted,s.streak_unassisted,s.max_streak_unassisted,
            s.opps,s.fsrs_d,s.fsrs_s,s.fsrs_last_review_at,s.fsrs_due_at,s.last_evidence_at,s.updated_at)
        ON CONFLICT(user_id,node_id) DO UPDATE SET p_known=EXCLUDED.p_known,
            n_strong_unassisted=EXCLUDED.n_strong_unassisted,streak_unassisted=EXCLUDED.streak_unassisted,
            max_streak_unassisted=EXCLUDED.max_streak_unassisted,opps=EXCLUDED.opps,
            fsrs_d=EXCLUDED.fsrs_d,fsrs_s=EXCLUDED.fsrs_s,fsrs_last_review_at=EXCLUDED.fsrs_last_review_at,
            fsrs_due_at=EXCLUDED.fsrs_due_at,last_evidence_at=EXCLUDED.last_evidence_at,
            updated_at=EXCLUDED.updated_at
        WHERE (l.p_known,l.n_strong_unassisted,l.streak_unassisted,l.max_streak_unassisted,l.opps,
               l.fsrs_d,l.fsrs_s,l.fsrs_last_review_at,l.fsrs_due_at,l.last_evidence_at,l.updated_at)
              IS DISTINCT FROM
              (EXCLUDED.p_known,EXCLUDED.n_strong_unassisted,EXCLUDED.streak_unassisted,
               EXCLUDED.max_streak_unassisted,EXCLUDED.opps,EXCLUDED.fsrs_d,EXCLUDED.fsrs_s,
               EXCLUDED.fsrs_last_review_at,EXCLUDED.fsrs_due_at,EXCLUDED.last_evidence_at,EXCLUDED.updated_at);
        GET DIAGNOSTICS n_rows = ROW_COUNT;
        n_states := n_states + n_rows;
    END LOOP;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'mirrors') LOOP
        UPDATE graph_nodes SET mastery_score=(x->>'mastery_score')::double precision,
               mastery_tier=x->>'mastery_tier'
         WHERE id=x->>'id' AND user_id=p_user_id
           AND (mastery_score,mastery_tier) IS DISTINCT FROM
               ((x->>'mastery_score')::double precision,x->>'mastery_tier');
        GET DIAGNOSTICS n_rows = ROW_COUNT;
        n_mirrors := n_mirrors + n_rows;
    END LOOP;
    UPDATE misconceptions SET resolved_at=clock_timestamp(),resolved_reason='evidence_void'
     WHERE user_id=p_user_id AND resolved_at IS NULL
       AND id IN (SELECT t->>'id' FROM jsonb_array_elements(p_plan->'misconceptions') t);
    GET DIAGNOSTICS n_misc = ROW_COUNT;
    RETURN jsonb_build_object('status','committed','voided',n_voided,'states',n_states,
        'mirrors',n_mirrors,'misconceptions',n_misc);
END $$;

-- ── grants: backend-only ────────────────────────────────────────────────────
-- RLS with no policy denies every non-bypass role; service_role (the backend)
-- bypasses it. Functions grant EXECUTE to PUBLIC by default, so that is
-- revoked. Role statements are guarded: a plain Postgres has none of them.
-- learning_evidence_voids: SELECT and INSERT only (append-only, with the trigger).
ALTER TABLE learning_evidence_voids ENABLE ROW LEVEL SECURITY;
ALTER TABLE misconception_attempts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE learning_evidence_voids FROM PUBLIC;
REVOKE ALL ON TABLE misconception_attempts FROM PUBLIC;
REVOKE ALL ON FUNCTION check_item_report_quarantine(text, text, text, text, text, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION check_item_report(text, text, text, text, text, integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION check_item_review_decide(text, text, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION misconception_record(text, text, text, text, text, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION misconception_record(text, text, text, text, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION learning_evidence_commit(text, text, uuid, text, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION learning_evidence_void_pending(text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION learning_evidence_void_snapshot(text, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION learning_evidence_void_commit(text, text, text, uuid, jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION learning_evidence_voids_append_only() FROM PUBLIC;
REVOKE ALL ON FUNCTION check_item_hold_flags(text[], text) FROM PUBLIC;
REVOKE ALL ON FUNCTION check_items_staff_hold() FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON TABLE learning_evidence_voids FROM %I', r);
            EXECUTE format('REVOKE ALL ON TABLE misconception_attempts FROM %I', r);
            EXECUTE format('REVOKE ALL ON FUNCTION check_item_report_quarantine(text, text, text, text, text, integer) FROM %I', r);
            EXECUTE format('REVOKE ALL ON FUNCTION check_item_report(text, text, text, text, text, integer) FROM %I', r);
            EXECUTE format('REVOKE ALL ON FUNCTION check_item_review_decide(text, text, text, text) FROM %I', r);
            EXECUTE format('REVOKE ALL ON FUNCTION misconception_record(text, text, text, text, text, text, text) FROM %I', r);
            EXECUTE format('REVOKE ALL ON FUNCTION misconception_record(text, text, text, text, text, text) FROM %I', r);
            EXECUTE format('REVOKE ALL ON FUNCTION learning_evidence_commit(text, text, uuid, text, jsonb) FROM %I', r);
            EXECUTE format('REVOKE ALL ON FUNCTION learning_evidence_void_pending(text, text) FROM %I', r);
            EXECUTE format('REVOKE ALL ON FUNCTION learning_evidence_void_snapshot(text, text, text) FROM %I', r);
            EXECUTE format('REVOKE ALL ON FUNCTION learning_evidence_void_commit(text, text, text, uuid, jsonb) FROM %I', r);
            EXECUTE format('REVOKE ALL ON FUNCTION learning_evidence_voids_append_only() FROM %I', r);
            EXECUTE format('REVOKE ALL ON FUNCTION check_item_hold_flags(text[], text) FROM %I', r);
            EXECUTE format('REVOKE ALL ON FUNCTION check_items_staff_hold() FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT SELECT, INSERT ON TABLE learning_evidence_voids TO service_role;
        GRANT SELECT, INSERT ON TABLE misconception_attempts TO service_role;
        GRANT EXECUTE ON FUNCTION
            check_item_report_quarantine(text, text, text, text, text, integer),
            check_item_report(text, text, text, text, text, integer),
            check_item_review_decide(text, text, text, text),
            misconception_record(text, text, text, text, text, text, text),
            misconception_record(text, text, text, text, text, text),
            learning_evidence_commit(text, text, uuid, text, jsonb),
            learning_evidence_void_pending(text, text),
            learning_evidence_void_snapshot(text, text, text),
            learning_evidence_void_commit(text, text, text, uuid, jsonb),
            check_item_hold_flags(text[], text)
          TO service_role;
    END IF;
END $$;

-- PostgREST resolves new tables, columns and /rpc/<name> from its schema cache;
-- the local stack does not reliably reload on DDL (docs/local-supabase.md).
NOTIFY pgrst, 'reload schema';

-- @@ unit 20261108073631_learning_item_keys.sql
-- 20261108073631_learning_item_keys.sql
-- Learning loop check-item key verification (spec §13 A124). A check item's
-- answer key is drafted by a model from classmates' uploads and nobody
-- reviews it before it grades students; wrong-answer feedback then releases
-- that key as the solution. Before a drafted item is stored, a model of
-- another family solves it blind (agents/check_items_solve.py) and code
-- compares its answer with the key (learning/item_keys.py): agreement sets
-- the existing check_items.canonical_verified; a dispute stores the item
-- HELD (key_disputed / key_unsolved in the A113 lint_flags column) — never
-- served until staff confirm or retire it in the review queue.
--
-- 1. check_items.key_checked_at — when the key check last ran on the row
--    (agreed or held). NULL = never checked: every row stored before A124
--    (and one stored without the check, which only tests and evals do). The
--    key backfill (scripts/backfill_check_item_keys.py) reads
--    `key_checked_at IS NULL` by default. A timestamp, never text, so the
--    column is plaintext. Only the generation write and the backfills touch
--    it: no request-path read selects it.
--
-- 2. check_item_audits — staff's verdict on one course item's key
--    (course_id, question_hash): 'correct', 'wrong' or 'ambiguous', from a
--    stratified audit sample (learning/item_audit.py; GET
--    /api/admin/check-items/audit/sample, scripts/audit_check_item_keys.py).
--    The latest verdict wins; key_status is the key's status at its FIRST
--    audit (verified / held / unverified), so the per-status key-error rates
--    stay a measurement of the key check. The stratum (concept_key, format,
--    difficulty) and the item id are copied in, so a verdict outlives the
--    item it judged (an item found wrong is often retired). No foreign key
--    to check_items for the same reason. Hashes, ids, enums and timestamps
--    only. Backend-only.

ALTER TABLE public.check_items ADD COLUMN IF NOT EXISTS key_checked_at timestamptz;

CREATE TABLE IF NOT EXISTS check_item_audits (
  course_id     text        NOT NULL,
  question_hash text        NOT NULL,
  item_id       text        NOT NULL,
  concept_key   text        NOT NULL,
  format        text        NOT NULL,
  difficulty    smallint    NOT NULL,
  key_status    text        NOT NULL CHECK (key_status IN ('verified','held','unverified')),
  verdict       text        NOT NULL CHECK (verdict IN ('correct','wrong','ambiguous')),
  audited_by    text        REFERENCES users(id) ON DELETE SET NULL,
  audited_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (course_id, question_hash)
);

-- Backend-only (the 20261108041639_learning_item_quality.sql idiom): RLS with
-- no policy denies every non-bypass role; service_role (the backend) bypasses
-- it. Role statements are guarded because those roles are Supabase's: a plain
-- Postgres has none of them, and an unguarded REVOKE naming one aborts the
-- whole migration.
ALTER TABLE check_item_audits ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE check_item_audits FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON TABLE check_item_audits FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE check_item_audits TO service_role;
    END IF;
END $$;

-- PostgREST resolves the new column and table from its schema cache; the
-- local stack does not reliably reload on DDL (docs/local-supabase.md). NOTIFY
-- is delivered at COMMIT and is a no-op with no listener.
NOTIFY pgrst, 'reload schema';

-- @@ unit 20261108091912_learning_document_drafting.sql
-- 20261108091912_learning_document_drafting.sql
-- Learning loop: per-document check-item drafting status (spec §13 A128).
--
-- Live, 2026-11-07: an upload's practice questions are drafted after the
-- upload returns (minutes of model calls on a background pool), and until the
-- first item landed the Learn screen told the student "No check items for this
-- course yet" — the same words it uses for a course that will never have any.
-- Nothing recorded that drafting was still under way, so nothing could say so.
--
-- documents.check_items_status — where the upload's drafting is:
--   'pending'      the upload hook set it (routes/documents.py::
--                  _index_then_check_items, before indexing) and no run has
--                  ended yet;
--   'done'         a run ended with every concept it attempted handled (items
--                  stored, already full, or nothing to draft from);
--   'unavailable'  a run ended with a model or check unavailable for some
--                  concept (a later run — the nightly backfill — drafts it);
--   'failed'       a run raised, or the drafting queue refused it.
-- NULL = never drafted: every row before A128, and every upload with the loop
-- off. Written by services/check_item_service.py (mark_drafting /
-- generate_for_document) and read by drafting_pending, which the loop's
-- /probe/next and /check/next ask only when the course has no servable item:
-- a 'pending' mark younger than CHECK_ITEM_DRAFT_PENDING_TTL_S makes them
-- answer `preparing`. A plaintext enum, never text from the document.
--
-- documents.check_items_at — when the status was set (the TTL's clock: a
-- 'pending' left behind by a crash or a deploy's dropped queue stops reading
-- as "preparing" once it is older than the TTL).
--
-- Additive and re-runnable. The CHECK is added NOT VALID: every existing row
-- is NULL (it cannot violate it), so no scan of documents under an ACCESS
-- EXCLUSIVE lock is needed; new writes are checked. Code may ship ahead of
-- this migration: a status write that names an absent column fails, logs a
-- WARNING and changes nothing, and the read answers "not pending".

ALTER TABLE public.documents ADD COLUMN IF NOT EXISTS check_items_status text;
ALTER TABLE public.documents ADD COLUMN IF NOT EXISTS check_items_at timestamptz;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'documents_check_items_status_check'
    ) THEN
        ALTER TABLE public.documents ADD CONSTRAINT documents_check_items_status_check
            CHECK (check_items_status IS NULL
                   OR check_items_status IN ('pending', 'done', 'failed', 'unavailable'))
            NOT VALID;
    END IF;
END $$;

-- The one read: a student's own pending uploads (drafting_pending). Partial,
-- so it holds only the few rows drafting right now.
CREATE INDEX IF NOT EXISTS idx_documents_check_items_pending
    ON public.documents (user_id)
    WHERE check_items_status = 'pending';

-- PostgREST resolves the new columns from its schema cache; the local stack
-- does not reliably reload on DDL (docs/local-supabase.md). NOTIFY is
-- delivered at COMMIT and is a no-op with no listener.
NOTIFY pgrst, 'reload schema';

-- @@ unit 20261108092032_learning_student_confidence.sql
-- 20261108092032_learning_student_confidence.sql
-- Learning loop spec §13 A127: the student's stated confidence ("Guessing" /
-- "Fairly sure" / "Sure" on the loop's check and probe cards and on the review
-- card; never the post-test) is kept with the evidence it was stated on, for
-- the admin metacognitive-calibration report (confidence vs correctness per
-- channel). The value is learning/params.STUDENT_CONFIDENCE_LEVELS[label], a
-- number in [0, 1]; NULL = none stated (a skip, an idk, the post-test, the
-- quiz, every row before A127). Plaintext like the grader's `confidence`
-- beside it: a number, never free text.
--
-- NOT the grader's `confidence` column (PKG-03): that one is the grader's
-- certainty and drives WEIGHT_LOW_CONFIDENCE; this one is the student's and
-- weights nothing.
--
-- The single graph writer (services/graph_service.py::apply_graph_update ->
-- learning/evidence_transaction.py) is the only writer of node_mastery_events
-- (spec §8 invariant 1), through learning_evidence_commit. That function
-- refuses any event key it does not list, so it is re-created here with the
-- new key admitted, validated and inserted — otherwise identical to
-- 20261019141950_learning_evidence_forward_repair.sql's version. Apply this
-- migration BEFORE the code: an evidence row with a stated confidence fails
-- its batch closed against the old function (rows without one are unchanged
-- either way: the writer adds the key only when a confidence was stated).

ALTER TABLE public.node_mastery_events ADD COLUMN IF NOT EXISTS student_confidence double precision;

-- NOT VALID for lock behaviour, not data: every existing row is NULL, which the
-- CHECK admits, and a validating ADD would hold ACCESS EXCLUSIVE on the
-- append-only evidence journal for a full scan that buys nothing (the choice
-- 20261108050630_learning_grader_backend_claude.sql makes). New rows are
-- checked either way. Guarded by the constraint body, so a re-run adds nothing.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conrelid = 'public.node_mastery_events'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) ILIKE '%student_confidence%'
  ) THEN
    ALTER TABLE public.node_mastery_events
      ADD CONSTRAINT node_mastery_events_student_confidence_check
      CHECK (student_confidence IS NULL OR (student_confidence >= 0 AND student_confidence <= 1)) NOT VALID;
  END IF;
END $$;

CREATE OR REPLACE FUNCTION learning_evidence_commit(
    p_user_id text,p_course_id text,p_operation_id uuid,p_input_fingerprint text,p_plan jsonb
) RETURNS jsonb LANGUAGE plpgsql SET search_path=public,pg_temp
SET lock_timeout='2s' SET statement_timeout='10s' AS $$
DECLARE r learning_evidence_operations%ROWTYPE; x jsonb; v bigint; ids text[];
    grade_ids text[]; es jsonb; n graph_nodes%ROWTYPE; s learner_state%ROWTYPE;
    ev node_mastery_events%ROWTYPE; obs jsonb; expected_count bigint; actual_count bigint;
BEGIN
    IF p_user_id IS NULL OR p_user_id='' OR p_operation_id IS NULL
       OR p_input_fingerprint IS NULL OR p_input_fingerprint !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(p_plan) IS DISTINCT FROM 'object'
       OR (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(p_plan) k)
          IS DISTINCT FROM ARRAY['changes','checks','edges','events','mirrors','nodes','observed_at','state_rows','states_expected']::text[]
       OR EXISTS(SELECT 1 FROM jsonb_each(p_plan) p WHERE p.key<>'observed_at' AND jsonb_typeof(p.value)<>'array')
       OR jsonb_typeof(p_plan->'observed_at') NOT IN ('null','string') THEN
        RAISE EXCEPTION 'Invalid evidence transaction envelope';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('learning-evidence:'||p_user_id,0));
    SELECT * INTO r FROM learning_evidence_operations WHERE operation_id=p_operation_id;
    IF FOUND THEN
        IF r.user_id IS DISTINCT FROM p_user_id OR r.course_id IS DISTINCT FROM p_course_id
           OR r.input_fingerprint IS DISTINCT FROM p_input_fingerprint OR r.plan IS DISTINCT FROM p_plan THEN
            RETURN jsonb_build_object('status','conflict');
        END IF;
        RETURN jsonb_build_object('status','replay','receipt',jsonb_build_object(
            'operation_id',r.operation_id,'user_id',r.user_id,'course_id',r.course_id,
            'input_fingerprint',r.input_fingerprint,'changes',r.changes,'posteriors',(
                SELECT jsonb_object_agg(value->>'id',value->'mastery_score') FROM jsonb_array_elements(r.plan->'mirrors')),
            'observations',(SELECT coalesce(jsonb_agg(entry.value->'planning_observation' ORDER BY entry.position),'[]')
                FROM jsonb_array_elements(r.plan->'events') WITH ORDINALITY entry(value,position)
                WHERE jsonb_typeof(entry.value->'planning_observation')='object')));
    END IF;
    SELECT array_agg(value->>'id' ORDER BY value->>'id') INTO ids FROM jsonb_array_elements(p_plan->'nodes');
    SELECT array_agg(DISTINCT value->>'node_id' ORDER BY value->>'node_id') INTO grade_ids
        FROM jsonb_array_elements(p_plan->'events');
    IF coalesce(cardinality(ids),0)=0 OR coalesce(cardinality(grade_ids),0)=0
       OR cardinality(ids)<>(SELECT count(DISTINCT unnest) FROM unnest(ids))
       OR jsonb_array_length(p_plan->'changes')<>jsonb_array_length(p_plan->'events') THEN
        RAISE EXCEPTION 'Invalid evidence transaction members';
    END IF;
    -- Short, bounded coarse lock closes phantom edge inserts AND relation/
    -- endpoint edits/deletes from legacy writers. Acquire it before node locks
    -- so a legacy edge FK check cannot form a node/table lock-order inversion.
    LOCK TABLE graph_edges IN SHARE MODE;
    PERFORM 1 FROM graph_nodes WHERE id=ANY(ids) ORDER BY id FOR UPDATE;
    IF (SELECT count(*) FROM graph_nodes WHERE id=ANY(ids) AND user_id=p_user_id
        AND (p_course_id IS NULL OR course_id=p_course_id))<>cardinality(ids) THEN
        RETURN jsonb_build_object('status','ownership');
    END IF;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'nodes') LOOP
        IF jsonb_typeof(x->'version') IS DISTINCT FROM 'number' OR (x->>'version') !~ '^[0-9]+$' THEN
            RAISE EXCEPTION 'Invalid graph version';
        END IF;
        SELECT evidence_version INTO v FROM graph_nodes WHERE id=x->>'id';
        IF v IS DISTINCT FROM (x->>'version')::bigint THEN RETURN jsonb_build_object('status','stale'); END IF;
    END LOOP;
    SELECT coalesce(jsonb_agg(jsonb_build_object('source',e.source_node_id,'target',e.target_node_id)
               ORDER BY e.source_node_id,e.target_node_id),'[]') INTO es
      FROM graph_edges e JOIN graph_nodes a ON a.id=e.source_node_id JOIN graph_nodes b ON b.id=e.target_node_id
      WHERE e.user_id=p_user_id AND e.relationship_type='prerequisite'
        AND a.user_id=p_user_id AND b.user_id=p_user_id AND a.course_id IS NOT DISTINCT FROM b.course_id
        AND (p_course_id IS NULL OR a.course_id=p_course_id)
        AND (e.source_node_id=ANY(grade_ids) OR e.target_node_id=ANY(grade_ids));
    IF es IS DISTINCT FROM p_plan->'edges' THEN RETURN jsonb_build_object('status','stale'); END IF;
    PERFORM 1 FROM learner_state WHERE user_id=p_user_id AND node_id=ANY(ids) ORDER BY node_id FOR UPDATE;
    IF jsonb_array_length(p_plan->'states_expected')<>cardinality(ids)
       OR (SELECT count(DISTINCT value->>'node_id') FROM jsonb_array_elements(p_plan->'states_expected'))<>cardinality(ids)
       OR EXISTS(SELECT 1 FROM jsonb_array_elements(p_plan->'states_expected') WHERE NOT (value->>'node_id'=ANY(ids))) THEN
        RAISE EXCEPTION 'Invalid learner-state snapshot';
    END IF;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'states_expected') LOOP
        IF jsonb_typeof(x->'version') NOT IN ('number','null')
           OR (x->>'version' IS NOT NULL AND (x->>'version') !~ '^[0-9]+$') THEN
            RAISE EXCEPTION 'Invalid learner-state version';
        END IF;
        SELECT evidence_version INTO v FROM learner_state WHERE user_id=p_user_id AND node_id=x->>'node_id';
        IF v IS DISTINCT FROM (x->>'version')::bigint THEN RETURN jsonb_build_object('status','stale'); END IF;
    END LOOP;
    IF p_plan->>'observed_at' IS NOT NULL AND EXISTS(
        SELECT 1 FROM learner_state l WHERE l.user_id=p_user_id
        AND l.node_id IN (SELECT value->>'node_id' FROM jsonb_array_elements(p_plan->'state_rows'))
        AND (l.last_evidence_at > (p_plan->>'observed_at')::timestamptz
             OR l.evidence_touch_at > (p_plan->>'observed_at')::timestamptz)
    ) THEN RETURN jsonb_build_object('status','superseded'); END IF;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'checks') LOOP
        IF jsonb_typeof(x->'count') IS DISTINCT FROM 'number'
           OR (x->>'count') !~ '^[0-9]+$'
           OR jsonb_typeof(x->'global_count') IS DISTINCT FROM 'number'
           OR (x->>'global_count') !~ '^[0-9]+$' THEN
            RAISE EXCEPTION 'Invalid exposure snapshot';
        END IF;
        SELECT count(*) INTO actual_count FROM node_mastery_events e JOIN graph_nodes g ON g.id=e.node_id
            WHERE g.user_id=p_user_id AND e.event_type='evidence' AND e.session_id=x->>'session_id'
              AND e.question_hash=x->>'question_hash';
        IF actual_count IS DISTINCT FROM (x->>'count')::bigint THEN RETURN jsonb_build_object('status','stale'); END IF;
        SELECT count(*) INTO actual_count FROM node_mastery_events e JOIN graph_nodes g ON g.id=e.node_id
            WHERE g.user_id=p_user_id AND e.event_type='evidence' AND e.question_hash=x->>'question_hash';
        IF actual_count IS DISTINCT FROM (x->>'global_count')::bigint THEN RETURN jsonb_build_object('status','stale'); END IF;
    END LOOP;
    IF jsonb_array_length(p_plan->'state_rows')=0
       OR jsonb_array_length(p_plan->'state_rows')<>jsonb_array_length(p_plan->'mirrors')
       OR (SELECT count(DISTINCT value->>'node_id') FROM jsonb_array_elements(p_plan->'state_rows'))<>jsonb_array_length(p_plan->'state_rows')
       OR (SELECT count(DISTINCT value->>'id') FROM jsonb_array_elements(p_plan->'mirrors'))<>jsonb_array_length(p_plan->'mirrors')
       OR EXISTS(SELECT 1 FROM unnest(grade_ids) id WHERE NOT EXISTS(
            SELECT 1 FROM jsonb_array_elements(p_plan->'state_rows') state_entry(value)
            WHERE state_entry.value->>'node_id'=id)) THEN
        RAISE EXCEPTION 'Invalid transaction row sets';
    END IF;
    -- Validate the WHOLE plan before its first mutation. SQL does no BKT,
    -- FSRS, weighting, threshold or propagation arithmetic.
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'state_rows') LOOP
        s := jsonb_populate_record(NULL::learner_state,x);
        IF s.user_id IS DISTINCT FROM p_user_id OR NOT(s.node_id=ANY(ids))
           OR s.p_known IS NULL OR NOT(s.p_known BETWEEN 0 AND 1)
           OR s.updated_at IS NULL
           OR s.n_strong_unassisted<0 OR s.streak_unassisted<0 OR s.max_streak_unassisted<0 OR s.opps<0
           OR EXISTS(SELECT 1 FROM jsonb_object_keys(x) k WHERE k NOT IN (
                'user_id','node_id','p_known','n_strong_unassisted','streak_unassisted','max_streak_unassisted','opps',
                'fsrs_d','fsrs_s','fsrs_last_review_at','fsrs_due_at','last_evidence_at','updated_at'))
           OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_plan->'mirrors') m WHERE m->>'id'=s.node_id) THEN
            RAISE EXCEPTION 'Invalid transaction learner state';
        END IF;
    END LOOP;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'events') LOOP
        ev := jsonb_populate_record(NULL::node_mastery_events,x);
        IF ev.id IS NULL OR NOT(ev.node_id=ANY(grade_ids)) OR NOT(ev.node_id=ANY(ids))
           OR ev.event_type IS DISTINCT FROM 'evidence' OR ev.correct IS NULL
           OR ev.p_before IS NULL OR NOT(ev.p_before BETWEEN 0 AND 1)
           OR ev.p_after IS NULL OR NOT(ev.p_after BETWEEN 0 AND 1)
           OR ev.weight IS NULL OR NOT(ev.weight BETWEEN 0 AND 1)
           OR ev.created_at IS NULL OR ev.evidence_seq IS NULL OR ev.evidence_seq<0
           OR jsonb_typeof(x->'correct') IS DISTINCT FROM 'boolean'
           OR jsonb_typeof(x->'assisted') IS DISTINCT FROM 'boolean'
           OR EXISTS(SELECT 1 FROM jsonb_object_keys(x) k WHERE k NOT IN (
                'id','node_id','delta','reason','created_at','event_type','channel','correct','weight','assisted','max_rung',
                'p_before','p_after','session_id','check_item_id','question_hash','confidence','grader_backend','evidence_seq','planning_observation',
                'student_confidence'))
           -- spec §13 A127: a stated confidence is a JSON number in [0, 1], or absent/null
           OR (x ? 'student_confidence' AND jsonb_typeof(x->'student_confidence') NOT IN ('number','null'))
           OR NOT (ev.student_confidence IS NULL OR ev.student_confidence BETWEEN 0 AND 1) THEN
            RAISE EXCEPTION 'Invalid transaction evidence';
        END IF;
        obs := ev.planning_observation;
        IF obs IS NOT NULL AND (
            jsonb_typeof(obs) IS DISTINCT FROM 'object'
            OR obs->>'node_id' IS DISTINCT FROM ev.node_id OR obs->>'question_hash' IS DISTINCT FROM ev.question_hash
            OR obs->>'check_item_id' IS DISTINCT FROM ev.check_item_id OR obs->>'channel' IS DISTINCT FROM ev.channel
            OR obs->'correct' IS DISTINCT FROM to_jsonb(ev.correct)
            OR obs->'assisted' IS DISTINCT FROM to_jsonb(ev.assisted)
            OR obs->'max_rung' IS DISTINCT FROM to_jsonb(ev.max_rung)
            OR jsonb_typeof(obs->'independent') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'same_session_recheck') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'idk') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'synthetic_idk') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'previously_seen') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'difficulty') IS DISTINCT FROM 'number'
            OR (obs->>'difficulty') NOT IN ('1','2','3')
            OR NOT(obs ?& ARRAY['check_item_id','difficulty','synthetic_idk','previously_seen','node_id',
                'question_hash','channel','correct','idk','assisted','max_rung','same_session_recheck','independent'])
            OR EXISTS(SELECT 1 FROM jsonb_object_keys(obs) k WHERE k NOT IN (
                'check_item_id','difficulty','synthetic_idk','previously_seen','node_id','question_hash',
                'channel','correct','idk','assisted','max_rung','same_session_recheck','independent'))
            OR (obs->>'idk')::boolean AND ev.correct
            OR (obs->>'synthetic_idk')::boolean AND NOT (obs->>'idk')::boolean
            OR ev.assisted IS DISTINCT FROM (ev.max_rung>0)
            OR (obs->>'independent')::boolean IS DISTINCT FROM (NOT (
                ev.max_rung>0 OR ev.assisted OR (obs->>'same_session_recheck')::boolean
                OR (obs->>'synthetic_idk')::boolean OR (obs->>'previously_seen')::boolean))) THEN
            RAISE EXCEPTION 'Invalid final planning provenance';
        END IF;
    END LOOP;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'state_rows') LOOP
        s := jsonb_populate_record(NULL::learner_state,x);
        INSERT INTO learner_state(user_id,node_id,p_known,n_strong_unassisted,streak_unassisted,max_streak_unassisted,
            opps,fsrs_d,fsrs_s,fsrs_last_review_at,fsrs_due_at,last_evidence_at,updated_at,evidence_touch_at)
        VALUES(s.user_id,s.node_id,s.p_known,s.n_strong_unassisted,s.streak_unassisted,s.max_streak_unassisted,
            s.opps,s.fsrs_d,s.fsrs_s,s.fsrs_last_review_at,s.fsrs_due_at,s.last_evidence_at,s.updated_at,s.updated_at)
        ON CONFLICT(user_id,node_id) DO UPDATE SET p_known=EXCLUDED.p_known,n_strong_unassisted=EXCLUDED.n_strong_unassisted,
            streak_unassisted=EXCLUDED.streak_unassisted,max_streak_unassisted=EXCLUDED.max_streak_unassisted,
            opps=EXCLUDED.opps,fsrs_d=EXCLUDED.fsrs_d,fsrs_s=EXCLUDED.fsrs_s,
            fsrs_last_review_at=EXCLUDED.fsrs_last_review_at,fsrs_due_at=EXCLUDED.fsrs_due_at,
            last_evidence_at=EXCLUDED.last_evidence_at,updated_at=EXCLUDED.updated_at,
            evidence_touch_at=greatest(learner_state.evidence_touch_at,EXCLUDED.evidence_touch_at);
    END LOOP;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'mirrors') LOOP
        IF NOT(x->>'id'=ANY(ids)) OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_plan->'state_rows') t WHERE t->>'node_id'=x->>'id')
           OR jsonb_typeof(x->'mastery_score') IS DISTINCT FROM 'number'
           OR NOT((x->>'mastery_score')::double precision BETWEEN 0 AND 1)
           OR EXISTS(SELECT 1 FROM jsonb_object_keys(x) k WHERE k NOT IN ('id','mastery_score','mastery_tier','times_studied','last_studied_at')) THEN
            RAISE EXCEPTION 'Invalid transaction mirror';
        END IF;
        UPDATE graph_nodes SET mastery_score=(x->>'mastery_score')::double precision,mastery_tier=x->>'mastery_tier',
            times_studied=CASE WHEN x ? 'times_studied' THEN (x->>'times_studied')::int ELSE times_studied END,
            last_studied_at=CASE WHEN x ? 'last_studied_at' THEN (x->>'last_studied_at')::timestamptz ELSE last_studied_at END
            WHERE id=x->>'id' AND user_id=p_user_id;
    END LOOP;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'events') LOOP
        ev := jsonb_populate_record(NULL::node_mastery_events,x);
        INSERT INTO node_mastery_events(id,node_id,delta,reason,created_at,event_type,channel,correct,weight,assisted,max_rung,
            p_before,p_after,session_id,check_item_id,question_hash,confidence,grader_backend,evidence_seq,planning_observation,
            student_confidence)
        VALUES(ev.id,ev.node_id,ev.delta,ev.reason,ev.created_at,ev.event_type,ev.channel,ev.correct,ev.weight,ev.assisted,ev.max_rung,
            ev.p_before,ev.p_after,ev.session_id,ev.check_item_id,ev.question_hash,ev.confidence,ev.grader_backend,ev.evidence_seq,ev.planning_observation,
            ev.student_confidence);
    END LOOP;
    INSERT INTO learning_evidence_operations(operation_id,user_id,course_id,input_fingerprint,plan,changes)
        VALUES(p_operation_id,p_user_id,p_course_id,p_input_fingerprint,p_plan,p_plan->'changes');
    RETURN learning_evidence_receipt(p_user_id,p_operation_id);
END $$;

REVOKE ALL ON FUNCTION learning_evidence_commit(text,text,uuid,text,jsonb) FROM PUBLIC;
DO $$ DECLARE r text; BEGIN
    FOREACH r IN ARRAY ARRAY['anon','authenticated'] LOOP
        IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=r) THEN
            EXECUTE format('REVOKE ALL ON FUNCTION learning_evidence_commit(text,text,uuid,text,jsonb) FROM %I',r);
        END IF;
    END LOOP;
    IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN
        GRANT EXECUTE ON FUNCTION learning_evidence_commit(text,text,uuid,text,jsonb) TO service_role;
    END IF;
END $$;

-- PostgREST resolves the new column from its schema cache; the local stack
-- does not reliably reload on DDL (docs/local-supabase.md). NOTIFY is
-- delivered at COMMIT and is a no-op with no listener.
NOTIFY pgrst, 'reload schema';

-- @@ unit 20261108093359_learning_posttest_outcomes.sql
-- 20261108093359_learning_posttest_outcomes.sql
-- Learning loop, spec §13 A126 (docs/research/learning-loop/2026-11-07-direction-
-- audit.md rec. 2: a 1-week plus a 4-week follow-up, a pretest form, and report
-- missing outcomes and uncertainty): the delayed post-test records enough to
-- support a learning claim.
--
-- 1. posttest_poses records how its item was chosen and what the answer
--    reports beside its outcome:
--    item_match       — the posed item against the student's pretest item (the
--                       concept's FIRST graded item, the A112 anchor): exact |
--                       difficulty | format | none | no_pretest;
--    item_source      — reserve (one of the concept's protected post-test items)
--                       | fallback (a fresh unprotected item);
--    served_at        — the item's first display (POST /posttest/shown, the
--                       server's clock);
--    answer_latency_s — answered_at − served_at, in seconds (NULL: never shown);
--    hidden_count, hidden_s — page-hidden periods and seconds while the item
--                       was on screen: client-reported, clamped by the server,
--                       never read by the grade.
--    A renewal (A89/A93) resets them with the outcome. Rows written before this
--    migration keep NULL: unknown, never inferred.
-- 2. posttest_skips — a due window /posttest/start had nothing fresh to pose
--    for, and why (no_items | exhausted | reported): one row per (student,
--    node, window), the latest reason. With the poses, every due window is
--    countable: answered, expired, open, skipped or never opened.
-- 3. posttest_anchors(...) — each concept's anchor (its FIRST graded evidence
--    time, the A112 anchor) for one student or every student, optionally in an
--    anchor-time range, keyset-paged by node id: PostgREST cannot GROUP BY.
--    STABLE, read-only.
--
-- Hashes, ids, codes, timestamps and numbers only — never item or answer text.
-- Backend-only (RLS on, no policy; service_role bypasses it). Idempotent.

ALTER TABLE posttest_poses ADD COLUMN IF NOT EXISTS item_match text;
ALTER TABLE posttest_poses ADD COLUMN IF NOT EXISTS item_source text;
ALTER TABLE posttest_poses ADD COLUMN IF NOT EXISTS served_at timestamptz;
ALTER TABLE posttest_poses ADD COLUMN IF NOT EXISTS answer_latency_s double precision;
ALTER TABLE posttest_poses ADD COLUMN IF NOT EXISTS hidden_count integer;
ALTER TABLE posttest_poses ADD COLUMN IF NOT EXISTS hidden_s double precision;

ALTER TABLE posttest_poses DROP CONSTRAINT IF EXISTS posttest_poses_item_match_check;
ALTER TABLE posttest_poses ADD CONSTRAINT posttest_poses_item_match_check
  CHECK (item_match IS NULL OR item_match IN ('exact', 'difficulty', 'format', 'none', 'no_pretest'));
ALTER TABLE posttest_poses DROP CONSTRAINT IF EXISTS posttest_poses_item_source_check;
ALTER TABLE posttest_poses ADD CONSTRAINT posttest_poses_item_source_check
  CHECK (item_source IS NULL OR item_source IN ('reserve', 'fallback'));

-- What an answer reports exists only on an answered pose: a latency needs the
-- display it is measured from, and the hidden telemetry is both values or
-- neither, never negative.
ALTER TABLE posttest_poses DROP CONSTRAINT IF EXISTS posttest_poses_answer_telemetry_check;
ALTER TABLE posttest_poses ADD CONSTRAINT posttest_poses_answer_telemetry_check
  CHECK (
    (answer_latency_s IS NULL
       OR (answer_latency_s >= 0 AND answered_at IS NOT NULL AND served_at IS NOT NULL))
    AND (hidden_count IS NULL) = (hidden_s IS NULL)
    AND (hidden_count IS NULL
       OR (hidden_count >= 0 AND hidden_s >= 0 AND answered_at IS NOT NULL))
  );

CREATE TABLE IF NOT EXISTS posttest_skips (
  user_id     text        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  node_id     text        NOT NULL,
  window_days integer     NOT NULL CHECK (window_days > 0),
  course_id   text        NOT NULL,
  reason      text        NOT NULL CHECK (reason IN ('no_items', 'exhausted', 'reported')),
  skipped_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, node_id, window_days)
);

-- Each concept's anchor. p_user_id NULL = every student (the admin funnel);
-- p_anchor_from / p_anchor_to bound the anchor (inclusive, NULL = open);
-- p_after_node_id is the keyset cursor (node ids after it); p_limit is clamped
-- to 1..1000, PostgREST's max rows. A node with no course is never posed, so
-- never returned. CREATE OR REPLACE: functions have no IF NOT EXISTS.
CREATE OR REPLACE FUNCTION posttest_anchors(
  p_user_id text,
  p_anchor_from timestamptz,
  p_anchor_to timestamptz,
  p_after_node_id text,
  p_limit integer
)
RETURNS TABLE (node_id text, user_id text, course_id text, concept_name text, anchor_at timestamptz)
LANGUAGE plpgsql
STABLE
SET search_path = public, pg_temp
AS $$
#variable_conflict use_column
DECLARE
  v_limit integer := LEAST(GREATEST(coalesce(p_limit, 1000), 1), 1000);
BEGIN
  IF p_user_id IS NOT NULL THEN
    RETURN QUERY
    SELECT g.id, g.user_id, g.course_id, g.concept_name, a.first_at
      FROM graph_nodes g
      CROSS JOIN LATERAL (
        SELECT min(e.created_at) AS first_at
          FROM node_mastery_events e
         WHERE e.node_id = g.id AND e.event_type = 'evidence'
      ) a
     WHERE g.user_id = p_user_id
       AND g.course_id IS NOT NULL
       AND a.first_at IS NOT NULL
       AND (p_anchor_from IS NULL OR a.first_at >= p_anchor_from)
       AND (p_anchor_to IS NULL OR a.first_at <= p_anchor_to)
       AND (p_after_node_id IS NULL OR g.id > p_after_node_id)
     ORDER BY g.id
     LIMIT v_limit;
  ELSE
    RETURN QUERY
    SELECT g.id, g.user_id, g.course_id, g.concept_name, a.first_at
      FROM (
        -- the cursor bounds the aggregate itself: a page groups only the
        -- nodes after the previous page, never the whole journal again
        SELECT e.node_id AS anchored_node, min(e.created_at) AS first_at
          FROM node_mastery_events e
         WHERE e.event_type = 'evidence'
           AND (p_after_node_id IS NULL OR e.node_id > p_after_node_id)
         GROUP BY e.node_id
      ) a
      JOIN graph_nodes g ON g.id = a.anchored_node
     WHERE g.course_id IS NOT NULL
       AND (p_anchor_from IS NULL OR a.first_at >= p_anchor_from)
       AND (p_anchor_to IS NULL OR a.first_at <= p_anchor_to)
     ORDER BY g.id
     LIMIT v_limit;
  END IF;
END
$$;

-- Backend-only (the 20261108041639_learning_item_quality.sql idiom): RLS with no
-- policy denies every non-bypass role; service_role (the backend) bypasses it.
-- Functions grant EXECUTE to PUBLIC by default, so that is revoked. Role
-- statements are guarded because those roles are Supabase's: a plain Postgres
-- has none of them, and an unguarded REVOKE naming one aborts the migration.
ALTER TABLE posttest_skips ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE posttest_skips FROM PUBLIC;
REVOKE ALL ON FUNCTION posttest_anchors(text, timestamptz, timestamptz, text, integer) FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON TABLE posttest_skips FROM %I', r);
            EXECUTE format(
                'REVOKE ALL ON FUNCTION posttest_anchors(text, timestamptz, timestamptz, text, integer) FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE posttest_skips TO service_role;
        GRANT EXECUTE ON FUNCTION posttest_anchors(text, timestamptz, timestamptz, text, integer) TO service_role;
    END IF;
END $$;

-- PostgREST serves the new columns, table and /rpc/posttest_anchors from its
-- schema cache; reload it (a no-op with no listener).
NOTIFY pgrst, 'reload schema';

-- @@ unit 20261108103333_learning_evidence_commit_reconcile.sql
-- 20261108103333_learning_evidence_commit_reconcile.sql
-- Learning loop spec §13 A123 × A127: the one definition of
-- learning_evidence_commit that carries BOTH branches' changes.
--
-- Two wave-2 migrations re-create this function, each from a different base:
--   * 20261108072715_learning_evidence_void.sql (A123) takes a SHARED advisory
--     lock on every check item a batch grades (key check-item-review:<course>:<hash>,
--     the key check_item_review_decide holds EXCLUSIVELY), refuses a batch that
--     grades an item staff retired (status 'retired', nothing written), and
--     admits and journals the replay inputs `retention`, `same_session_recheck`
--     and `propagated_to`;
--   * 20261108092032_learning_student_confidence.sql (A127) was written on the
--     pre-A123 body (20261019141950) and admits and journals `student_confidence`.
-- Migrations apply in filename order, so A127's CREATE OR REPLACE ran last and
-- dropped all of A123's changes: no item lock, no retired refusal, and every
-- evidence row that journals A123's replay keys refused as invalid.
--
-- This migration re-creates the function as A123's definition with A127's
-- three edits, verbatim: `student_confidence` in the key whitelist, its type
-- and range check, and its insert column and value. Neither earlier migration
-- is edited (both are kept byte-identical to their branches). No wave-2
-- migration had been applied anywhere when this was written; apply it in the
-- same run as the two above, before the code (rollout:
-- docs/operations/learning-engineering-readiness.md). The registry in
-- backend/tests/test_learning_migration_functions.py pins that the last
-- definition keeps every change an earlier migration made.

CREATE OR REPLACE FUNCTION learning_evidence_commit(
    p_user_id text,p_course_id text,p_operation_id uuid,p_input_fingerprint text,p_plan jsonb
) RETURNS jsonb LANGUAGE plpgsql SET search_path=public,pg_temp
SET lock_timeout='2s' SET statement_timeout='10s' AS $$
DECLARE r learning_evidence_operations%ROWTYPE; x jsonb; v bigint; ids text[];
    grade_ids text[]; es jsonb; n graph_nodes%ROWTYPE; s learner_state%ROWTYPE;
    ev node_mastery_events%ROWTYPE; obs jsonb; expected_count bigint; actual_count bigint;
    item record; retired_items jsonb;
BEGIN
    IF p_user_id IS NULL OR p_user_id='' OR p_operation_id IS NULL
       OR p_input_fingerprint IS NULL OR p_input_fingerprint !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(p_plan) IS DISTINCT FROM 'object'
       OR (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(p_plan) k)
          IS DISTINCT FROM ARRAY['changes','checks','edges','events','mirrors','nodes','observed_at','state_rows','states_expected']::text[]
       OR EXISTS(SELECT 1 FROM jsonb_each(p_plan) p WHERE p.key<>'observed_at' AND jsonb_typeof(p.value)<>'array')
       OR jsonb_typeof(p_plan->'observed_at') NOT IN ('null','string') THEN
        RAISE EXCEPTION 'Invalid evidence transaction envelope';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('learning-evidence:'||p_user_id,0));
    SELECT * INTO r FROM learning_evidence_operations WHERE operation_id=p_operation_id;
    IF FOUND THEN
        IF r.user_id IS DISTINCT FROM p_user_id OR r.course_id IS DISTINCT FROM p_course_id
           OR r.input_fingerprint IS DISTINCT FROM p_input_fingerprint OR r.plan IS DISTINCT FROM p_plan THEN
            RETURN jsonb_build_object('status','conflict');
        END IF;
        RETURN jsonb_build_object('status','replay','receipt',jsonb_build_object(
            'operation_id',r.operation_id,'user_id',r.user_id,'course_id',r.course_id,
            'input_fingerprint',r.input_fingerprint,'changes',r.changes,'posteriors',(
                SELECT jsonb_object_agg(value->>'id',value->'mastery_score') FROM jsonb_array_elements(r.plan->'mirrors')),
            'observations',(SELECT coalesce(jsonb_agg(entry.value->'planning_observation' ORDER BY entry.position),'[]')
                FROM jsonb_array_elements(r.plan->'events') WITH ORDINALITY entry(value,position)
                WHERE jsonb_typeof(entry.value->'planning_observation')='object')));
    END IF;
    -- §13 A123: a check item staff retired takes no new evidence. A SHARED lock
    -- per graded item (sorted), against check_item_review_decide's EXCLUSIVE one:
    -- a retire decided while this grade was in flight waits for its commit (and
    -- the void sweep then finds the row); a grade arriving after it is refused.
    FOR item IN
        SELECT DISTINCT g.course_id AS course_id, e.value->>'question_hash' AS question_hash
          FROM jsonb_array_elements(p_plan->'events') e
          JOIN graph_nodes g ON g.id = e.value->>'node_id'
         WHERE jsonb_typeof(e.value->'check_item_id') = 'string'
           AND jsonb_typeof(e.value->'question_hash') = 'string'
           AND g.course_id IS NOT NULL
         ORDER BY 1, 2
    LOOP
        PERFORM pg_advisory_xact_lock_shared(
            hashtextextended('check-item-review:'||item.course_id||':'||item.question_hash,0));
    END LOOP;
    SELECT coalesce(jsonb_agg(jsonb_build_object('course_id',q.course_id,'question_hash',q.question_hash)
               ORDER BY q.course_id,q.question_hash),'[]') INTO retired_items
      FROM (SELECT DISTINCT g.course_id AS course_id, e.value->>'question_hash' AS question_hash
              FROM jsonb_array_elements(p_plan->'events') e
              JOIN graph_nodes g ON g.id = e.value->>'node_id'
             WHERE jsonb_typeof(e.value->'check_item_id') = 'string'
               AND jsonb_typeof(e.value->'question_hash') = 'string'
               AND g.course_id IS NOT NULL) q
     WHERE EXISTS(SELECT 1 FROM check_item_reviews cr WHERE cr.course_id=q.course_id
                  AND cr.question_hash=q.question_hash AND cr.status='retired');
    IF jsonb_array_length(retired_items) > 0 THEN
        RETURN jsonb_build_object('status','retired','items',retired_items);
    END IF;
    SELECT array_agg(value->>'id' ORDER BY value->>'id') INTO ids FROM jsonb_array_elements(p_plan->'nodes');
    SELECT array_agg(DISTINCT value->>'node_id' ORDER BY value->>'node_id') INTO grade_ids
        FROM jsonb_array_elements(p_plan->'events');
    IF coalesce(cardinality(ids),0)=0 OR coalesce(cardinality(grade_ids),0)=0
       OR cardinality(ids)<>(SELECT count(DISTINCT unnest) FROM unnest(ids))
       OR jsonb_array_length(p_plan->'changes')<>jsonb_array_length(p_plan->'events') THEN
        RAISE EXCEPTION 'Invalid evidence transaction members';
    END IF;
    -- Short, bounded coarse lock closes phantom edge inserts AND relation/
    -- endpoint edits/deletes from legacy writers. Acquire it before node locks
    -- so a legacy edge FK check cannot form a node/table lock-order inversion.
    LOCK TABLE graph_edges IN SHARE MODE;
    PERFORM 1 FROM graph_nodes WHERE id=ANY(ids) ORDER BY id FOR UPDATE;
    IF (SELECT count(*) FROM graph_nodes WHERE id=ANY(ids) AND user_id=p_user_id
        AND (p_course_id IS NULL OR course_id=p_course_id))<>cardinality(ids) THEN
        RETURN jsonb_build_object('status','ownership');
    END IF;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'nodes') LOOP
        IF jsonb_typeof(x->'version') IS DISTINCT FROM 'number' OR (x->>'version') !~ '^[0-9]+$' THEN
            RAISE EXCEPTION 'Invalid graph version';
        END IF;
        SELECT evidence_version INTO v FROM graph_nodes WHERE id=x->>'id';
        IF v IS DISTINCT FROM (x->>'version')::bigint THEN RETURN jsonb_build_object('status','stale'); END IF;
    END LOOP;
    SELECT coalesce(jsonb_agg(jsonb_build_object('source',e.source_node_id,'target',e.target_node_id)
               ORDER BY e.source_node_id,e.target_node_id),'[]') INTO es
      FROM graph_edges e JOIN graph_nodes a ON a.id=e.source_node_id JOIN graph_nodes b ON b.id=e.target_node_id
      WHERE e.user_id=p_user_id AND e.relationship_type='prerequisite'
        AND a.user_id=p_user_id AND b.user_id=p_user_id AND a.course_id IS NOT DISTINCT FROM b.course_id
        AND (p_course_id IS NULL OR a.course_id=p_course_id)
        AND (e.source_node_id=ANY(grade_ids) OR e.target_node_id=ANY(grade_ids));
    IF es IS DISTINCT FROM p_plan->'edges' THEN RETURN jsonb_build_object('status','stale'); END IF;
    PERFORM 1 FROM learner_state WHERE user_id=p_user_id AND node_id=ANY(ids) ORDER BY node_id FOR UPDATE;
    IF jsonb_array_length(p_plan->'states_expected')<>cardinality(ids)
       OR (SELECT count(DISTINCT value->>'node_id') FROM jsonb_array_elements(p_plan->'states_expected'))<>cardinality(ids)
       OR EXISTS(SELECT 1 FROM jsonb_array_elements(p_plan->'states_expected') WHERE NOT (value->>'node_id'=ANY(ids))) THEN
        RAISE EXCEPTION 'Invalid learner-state snapshot';
    END IF;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'states_expected') LOOP
        IF jsonb_typeof(x->'version') NOT IN ('number','null')
           OR (x->>'version' IS NOT NULL AND (x->>'version') !~ '^[0-9]+$') THEN
            RAISE EXCEPTION 'Invalid learner-state version';
        END IF;
        SELECT evidence_version INTO v FROM learner_state WHERE user_id=p_user_id AND node_id=x->>'node_id';
        IF v IS DISTINCT FROM (x->>'version')::bigint THEN RETURN jsonb_build_object('status','stale'); END IF;
    END LOOP;
    IF p_plan->>'observed_at' IS NOT NULL AND EXISTS(
        SELECT 1 FROM learner_state l WHERE l.user_id=p_user_id
        AND l.node_id IN (SELECT value->>'node_id' FROM jsonb_array_elements(p_plan->'state_rows'))
        AND (l.last_evidence_at > (p_plan->>'observed_at')::timestamptz
             OR l.evidence_touch_at > (p_plan->>'observed_at')::timestamptz)
    ) THEN RETURN jsonb_build_object('status','superseded'); END IF;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'checks') LOOP
        IF jsonb_typeof(x->'count') IS DISTINCT FROM 'number'
           OR (x->>'count') !~ '^[0-9]+$'
           OR jsonb_typeof(x->'global_count') IS DISTINCT FROM 'number'
           OR (x->>'global_count') !~ '^[0-9]+$' THEN
            RAISE EXCEPTION 'Invalid exposure snapshot';
        END IF;
        SELECT count(*) INTO actual_count FROM node_mastery_events e JOIN graph_nodes g ON g.id=e.node_id
            WHERE g.user_id=p_user_id AND e.event_type='evidence' AND e.session_id=x->>'session_id'
              AND e.question_hash=x->>'question_hash';
        IF actual_count IS DISTINCT FROM (x->>'count')::bigint THEN RETURN jsonb_build_object('status','stale'); END IF;
        SELECT count(*) INTO actual_count FROM node_mastery_events e JOIN graph_nodes g ON g.id=e.node_id
            WHERE g.user_id=p_user_id AND e.event_type='evidence' AND e.question_hash=x->>'question_hash';
        IF actual_count IS DISTINCT FROM (x->>'global_count')::bigint THEN RETURN jsonb_build_object('status','stale'); END IF;
    END LOOP;
    IF jsonb_array_length(p_plan->'state_rows')=0
       OR jsonb_array_length(p_plan->'state_rows')<>jsonb_array_length(p_plan->'mirrors')
       OR (SELECT count(DISTINCT value->>'node_id') FROM jsonb_array_elements(p_plan->'state_rows'))<>jsonb_array_length(p_plan->'state_rows')
       OR (SELECT count(DISTINCT value->>'id') FROM jsonb_array_elements(p_plan->'mirrors'))<>jsonb_array_length(p_plan->'mirrors')
       OR EXISTS(SELECT 1 FROM unnest(grade_ids) id WHERE NOT EXISTS(
            SELECT 1 FROM jsonb_array_elements(p_plan->'state_rows') state_entry(value)
            WHERE state_entry.value->>'node_id'=id)) THEN
        RAISE EXCEPTION 'Invalid transaction row sets';
    END IF;
    -- Validate the WHOLE plan before its first mutation. SQL does no BKT,
    -- FSRS, weighting, threshold or propagation arithmetic.
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'state_rows') LOOP
        s := jsonb_populate_record(NULL::learner_state,x);
        IF s.user_id IS DISTINCT FROM p_user_id OR NOT(s.node_id=ANY(ids))
           OR s.p_known IS NULL OR NOT(s.p_known BETWEEN 0 AND 1)
           OR s.updated_at IS NULL
           OR s.n_strong_unassisted<0 OR s.streak_unassisted<0 OR s.max_streak_unassisted<0 OR s.opps<0
           OR EXISTS(SELECT 1 FROM jsonb_object_keys(x) k WHERE k NOT IN (
                'user_id','node_id','p_known','n_strong_unassisted','streak_unassisted','max_streak_unassisted','opps',
                'fsrs_d','fsrs_s','fsrs_last_review_at','fsrs_due_at','last_evidence_at','updated_at'))
           OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_plan->'mirrors') m WHERE m->>'id'=s.node_id) THEN
            RAISE EXCEPTION 'Invalid transaction learner state';
        END IF;
    END LOOP;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'events') LOOP
        ev := jsonb_populate_record(NULL::node_mastery_events,x);
        IF ev.id IS NULL OR NOT(ev.node_id=ANY(grade_ids)) OR NOT(ev.node_id=ANY(ids))
           OR ev.event_type IS DISTINCT FROM 'evidence' OR ev.correct IS NULL
           OR ev.p_before IS NULL OR NOT(ev.p_before BETWEEN 0 AND 1)
           OR ev.p_after IS NULL OR NOT(ev.p_after BETWEEN 0 AND 1)
           OR ev.weight IS NULL OR NOT(ev.weight BETWEEN 0 AND 1)
           OR ev.created_at IS NULL OR ev.evidence_seq IS NULL OR ev.evidence_seq<0
           OR jsonb_typeof(x->'correct') IS DISTINCT FROM 'boolean'
           OR jsonb_typeof(x->'assisted') IS DISTINCT FROM 'boolean'
           -- §13 A123: the replay inputs, when present, are well formed
           OR (x ? 'retention' AND jsonb_typeof(x->'retention') NOT IN ('number','null'))
           OR (ev.retention IS NOT NULL AND NOT (ev.retention > 0 AND ev.retention <= 1))
           OR (x ? 'same_session_recheck' AND jsonb_typeof(x->'same_session_recheck') NOT IN ('boolean','null'))
           OR (x ? 'propagated_to' AND jsonb_typeof(x->'propagated_to') NOT IN ('array','null'))
           OR (jsonb_typeof(x->'propagated_to') = 'array' AND EXISTS(
                SELECT 1 FROM jsonb_array_elements(x->'propagated_to') t
                 WHERE jsonb_typeof(t) IS DISTINCT FROM 'string' OR NOT ((t #>> '{}')=ANY(ids))
                    OR (t #>> '{}')=ev.node_id
                    OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_plan->'state_rows') sr
                                   WHERE sr->>'node_id'=(t #>> '{}'))))
           OR EXISTS(SELECT 1 FROM jsonb_object_keys(x) k WHERE k NOT IN (
                'id','node_id','delta','reason','created_at','event_type','channel','correct','weight','assisted','max_rung',
                'p_before','p_after','session_id','check_item_id','question_hash','confidence','grader_backend','evidence_seq','planning_observation',
                'retention','same_session_recheck','propagated_to',
                'student_confidence'))
           -- spec §13 A127: a stated confidence is a JSON number in [0, 1], or absent/null
           OR (x ? 'student_confidence' AND jsonb_typeof(x->'student_confidence') NOT IN ('number','null'))
           OR NOT (ev.student_confidence IS NULL OR ev.student_confidence BETWEEN 0 AND 1) THEN
            RAISE EXCEPTION 'Invalid transaction evidence';
        END IF;
        obs := ev.planning_observation;
        IF obs IS NOT NULL AND (
            jsonb_typeof(obs) IS DISTINCT FROM 'object'
            OR obs->>'node_id' IS DISTINCT FROM ev.node_id OR obs->>'question_hash' IS DISTINCT FROM ev.question_hash
            OR obs->>'check_item_id' IS DISTINCT FROM ev.check_item_id OR obs->>'channel' IS DISTINCT FROM ev.channel
            OR obs->'correct' IS DISTINCT FROM to_jsonb(ev.correct)
            OR obs->'assisted' IS DISTINCT FROM to_jsonb(ev.assisted)
            OR obs->'max_rung' IS DISTINCT FROM to_jsonb(ev.max_rung)
            OR jsonb_typeof(obs->'independent') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'same_session_recheck') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'idk') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'synthetic_idk') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'previously_seen') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'difficulty') IS DISTINCT FROM 'number'
            OR (obs->>'difficulty') NOT IN ('1','2','3')
            OR NOT(obs ?& ARRAY['check_item_id','difficulty','synthetic_idk','previously_seen','node_id',
                'question_hash','channel','correct','idk','assisted','max_rung','same_session_recheck','independent'])
            OR EXISTS(SELECT 1 FROM jsonb_object_keys(obs) k WHERE k NOT IN (
                'check_item_id','difficulty','synthetic_idk','previously_seen','node_id','question_hash',
                'channel','correct','idk','assisted','max_rung','same_session_recheck','independent'))
            OR (obs->>'idk')::boolean AND ev.correct
            OR (obs->>'synthetic_idk')::boolean AND NOT (obs->>'idk')::boolean
            OR ev.assisted IS DISTINCT FROM (ev.max_rung>0)
            OR (obs->>'independent')::boolean IS DISTINCT FROM (NOT (
                ev.max_rung>0 OR ev.assisted OR (obs->>'same_session_recheck')::boolean
                OR (obs->>'synthetic_idk')::boolean OR (obs->>'previously_seen')::boolean))) THEN
            RAISE EXCEPTION 'Invalid final planning provenance';
        END IF;
    END LOOP;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'state_rows') LOOP
        s := jsonb_populate_record(NULL::learner_state,x);
        INSERT INTO learner_state(user_id,node_id,p_known,n_strong_unassisted,streak_unassisted,max_streak_unassisted,
            opps,fsrs_d,fsrs_s,fsrs_last_review_at,fsrs_due_at,last_evidence_at,updated_at,evidence_touch_at)
        VALUES(s.user_id,s.node_id,s.p_known,s.n_strong_unassisted,s.streak_unassisted,s.max_streak_unassisted,
            s.opps,s.fsrs_d,s.fsrs_s,s.fsrs_last_review_at,s.fsrs_due_at,s.last_evidence_at,s.updated_at,s.updated_at)
        ON CONFLICT(user_id,node_id) DO UPDATE SET p_known=EXCLUDED.p_known,n_strong_unassisted=EXCLUDED.n_strong_unassisted,
            streak_unassisted=EXCLUDED.streak_unassisted,max_streak_unassisted=EXCLUDED.max_streak_unassisted,
            opps=EXCLUDED.opps,fsrs_d=EXCLUDED.fsrs_d,fsrs_s=EXCLUDED.fsrs_s,
            fsrs_last_review_at=EXCLUDED.fsrs_last_review_at,fsrs_due_at=EXCLUDED.fsrs_due_at,
            last_evidence_at=EXCLUDED.last_evidence_at,updated_at=EXCLUDED.updated_at,
            evidence_touch_at=greatest(learner_state.evidence_touch_at,EXCLUDED.evidence_touch_at);
    END LOOP;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'mirrors') LOOP
        IF NOT(x->>'id'=ANY(ids)) OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_plan->'state_rows') t WHERE t->>'node_id'=x->>'id')
           OR jsonb_typeof(x->'mastery_score') IS DISTINCT FROM 'number'
           OR NOT((x->>'mastery_score')::double precision BETWEEN 0 AND 1)
           OR EXISTS(SELECT 1 FROM jsonb_object_keys(x) k WHERE k NOT IN ('id','mastery_score','mastery_tier','times_studied','last_studied_at')) THEN
            RAISE EXCEPTION 'Invalid transaction mirror';
        END IF;
        UPDATE graph_nodes SET mastery_score=(x->>'mastery_score')::double precision,mastery_tier=x->>'mastery_tier',
            times_studied=CASE WHEN x ? 'times_studied' THEN (x->>'times_studied')::int ELSE times_studied END,
            last_studied_at=CASE WHEN x ? 'last_studied_at' THEN (x->>'last_studied_at')::timestamptz ELSE last_studied_at END
            WHERE id=x->>'id' AND user_id=p_user_id;
    END LOOP;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'events') LOOP
        ev := jsonb_populate_record(NULL::node_mastery_events,x);
        INSERT INTO node_mastery_events(id,node_id,delta,reason,created_at,event_type,channel,correct,weight,assisted,max_rung,
            p_before,p_after,session_id,check_item_id,question_hash,confidence,grader_backend,evidence_seq,planning_observation,
            retention,same_session_recheck,propagated_to,
            student_confidence)
        VALUES(ev.id,ev.node_id,ev.delta,ev.reason,ev.created_at,ev.event_type,ev.channel,ev.correct,ev.weight,ev.assisted,ev.max_rung,
            ev.p_before,ev.p_after,ev.session_id,ev.check_item_id,ev.question_hash,ev.confidence,ev.grader_backend,ev.evidence_seq,ev.planning_observation,
            ev.retention,ev.same_session_recheck,ev.propagated_to,
            ev.student_confidence);
    END LOOP;
    INSERT INTO learning_evidence_operations(operation_id,user_id,course_id,input_fingerprint,plan,changes)
        VALUES(p_operation_id,p_user_id,p_course_id,p_input_fingerprint,p_plan,p_plan->'changes');
    RETURN learning_evidence_receipt(p_user_id,p_operation_id);
END $$;

REVOKE ALL ON FUNCTION learning_evidence_commit(text,text,uuid,text,jsonb) FROM PUBLIC;
DO $$ DECLARE r text; BEGIN
    FOREACH r IN ARRAY ARRAY['anon','authenticated'] LOOP
        IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=r) THEN
            EXECUTE format('REVOKE ALL ON FUNCTION learning_evidence_commit(text,text,uuid,text,jsonb) FROM %I',r);
        END IF;
    END LOOP;
    IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN
        GRANT EXECUTE ON FUNCTION learning_evidence_commit(text,text,uuid,text,jsonb) TO service_role;
    END IF;
END $$;

-- PostgREST resolves functions from its schema cache; the local stack does not
-- reliably reload on DDL (docs/local-supabase.md). NOTIFY is delivered at
-- COMMIT and is a no-op with no listener.
NOTIFY pgrst, 'reload schema';

-- @@ unit 20261108105254_learning_posttest_anchors_void.sql
-- 20261108105254_learning_posttest_anchors_void.sql
-- Learning loop spec §13 A123 × A126: the delayed post-test's concept anchors
-- leave void evidence out.
--
-- A concept's post-test windows run from its ANCHOR, its first graded evidence
-- (A112). Since A123 a row graded against an item staff retired is void, is no
-- evidence, and never anchors: loop_state_store.evidence_spans (the anchor the
-- route poses from) and the trial export's restatement both skip the rows that
-- learning_evidence_voids names. A126's posttest_anchors
-- (20261108093359_learning_posttest_outcomes.sql), written before A123 was
-- merged, took the earliest evidence row of any kind, so its readers (the
-- student's "retention check due" read and the admin funnel's due windows)
-- could anchor a concept on a void row, while the route posted from the first
-- valid one.
--
-- This migration re-creates the function as A126's definition with one change
-- in each branch: the void record's rows are left out of the first-evidence
-- read. A126's migration itself is not edited; the registry in
-- backend/tests/test_learning_migration_functions.py pins that the last
-- definition keeps A126's contract and A123's rule.

CREATE OR REPLACE FUNCTION posttest_anchors(
  p_user_id text,
  p_anchor_from timestamptz,
  p_anchor_to timestamptz,
  p_after_node_id text,
  p_limit integer
)
RETURNS TABLE (node_id text, user_id text, course_id text, concept_name text, anchor_at timestamptz)
LANGUAGE plpgsql
STABLE
SET search_path = public, pg_temp
AS $$
#variable_conflict use_column
DECLARE
  v_limit integer := LEAST(GREATEST(coalesce(p_limit, 1000), 1), 1000);
BEGIN
  IF p_user_id IS NOT NULL THEN
    RETURN QUERY
    SELECT g.id, g.user_id, g.course_id, g.concept_name, a.first_at
      FROM graph_nodes g
      CROSS JOIN LATERAL (
        SELECT min(e.created_at) AS first_at
          FROM node_mastery_events e
         WHERE e.node_id = g.id AND e.event_type = 'evidence'
           -- spec §13 A123: a void row is no evidence and never anchors
           AND NOT EXISTS (SELECT 1 FROM learning_evidence_voids v WHERE v.event_id = e.id)
      ) a
     WHERE g.user_id = p_user_id
       AND g.course_id IS NOT NULL
       AND a.first_at IS NOT NULL
       AND (p_anchor_from IS NULL OR a.first_at >= p_anchor_from)
       AND (p_anchor_to IS NULL OR a.first_at <= p_anchor_to)
       AND (p_after_node_id IS NULL OR g.id > p_after_node_id)
     ORDER BY g.id
     LIMIT v_limit;
  ELSE
    RETURN QUERY
    SELECT g.id, g.user_id, g.course_id, g.concept_name, a.first_at
      FROM (
        -- the cursor bounds the aggregate itself: a page groups only the
        -- nodes after the previous page, never the whole journal again
        SELECT e.node_id AS anchored_node, min(e.created_at) AS first_at
          FROM node_mastery_events e
         WHERE e.event_type = 'evidence'
           AND (p_after_node_id IS NULL OR e.node_id > p_after_node_id)
           -- spec §13 A123: a void row is no evidence and never anchors
           AND NOT EXISTS (SELECT 1 FROM learning_evidence_voids v WHERE v.event_id = e.id)
         GROUP BY e.node_id
      ) a
      JOIN graph_nodes g ON g.id = a.anchored_node
     WHERE g.course_id IS NOT NULL
       AND (p_anchor_from IS NULL OR a.first_at >= p_anchor_from)
       AND (p_anchor_to IS NULL OR a.first_at <= p_anchor_to)
     ORDER BY g.id
     LIMIT v_limit;
  END IF;
END
$$;

REVOKE ALL ON FUNCTION posttest_anchors(text, timestamptz, timestamptz, text, integer) FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format(
                'REVOKE ALL ON FUNCTION posttest_anchors(text, timestamptz, timestamptz, text, integer) FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT EXECUTE ON FUNCTION posttest_anchors(text, timestamptz, timestamptz, text, integer) TO service_role;
    END IF;
END $$;

-- PostgREST resolves functions from its schema cache; the local stack does not
-- reliably reload on DDL (docs/local-supabase.md). NOTIFY is delivered at
-- COMMIT and is a no-op with no listener.
NOTIFY pgrst, 'reload schema';

-- @@ unit 20261108110805_learning_misconception_resolved_reason.sql
-- 20261108110805_learning_misconception_resolved_reason.sql
-- Learning loop spec §13 A127 × A123: misconceptions.resolved_reason names why
-- an open misconception closed.
--
-- A123 (20261108072715_learning_evidence_void.sql) added the column with a
-- CHECK that admits one value, 'evidence_void': the void closure, which runs
-- when every attempt supporting a misconception was graded against a retired
-- item. A127's misconceptions.resolve() closes a misconception when the student
-- answers an isomorph (the same concept, another question) correctly and
-- unassisted. It now records 'correct_unassisted_isomorph', so the CHECK admits
-- both. These are the only two writers of resolved_at. A row closed before
-- this change keeps NULL (unknown, never inferred).
--
-- Apply it BEFORE the code. Against the old CHECK, resolve()'s UPDATE is
-- refused (23514); resolve() fails closed (it logs a WARNING and closes
-- nothing), so a misconception stays open rather than closing without its
-- reason.
--
-- Matches on the constraint BODY, not an assumed name (the
-- 20260828172725_assignments_source_check_by_definition.sql lesson, as A116's
-- 20261108050630 does: a DROP by name no-ops on a suffixed variant, and the
-- narrow CHECK stays enforced beside the wide one). The widened one keeps
-- A123's name, misconceptions_resolved_reason_check.
--
-- Idempotent: on a re-run the first block matches nothing (every
-- resolved_reason CHECK already names 'correct_unassisted_isomorph') and the
-- guarded ADD is skipped. No row is written.

DO $$
DECLARE
  r RECORD;
BEGIN
  FOR r IN
    SELECT c.conname
    FROM pg_constraint c
    WHERE c.conrelid = 'public.misconceptions'::regclass
      AND c.contype = 'c'
      AND pg_get_constraintdef(c.oid) ILIKE '%resolved_reason%'
      AND pg_get_constraintdef(c.oid) NOT ILIKE '%correct_unassisted_isomorph%'
  LOOP
    EXECUTE format('ALTER TABLE public.misconceptions DROP CONSTRAINT %I', r.conname);
    RAISE NOTICE 'dropped narrow misconceptions.resolved_reason CHECK: %', r.conname;
  END LOOP;
END $$;

-- NOT VALID for lock behaviour, not data: the old list is a strict subset of
-- this one, so no existing row can violate it, and a validating ADD would hold
-- ACCESS EXCLUSIVE on misconceptions (every wrong answer with a matched key
-- writes to it) for a scan that buys nothing. New and updated rows are checked
-- either way. The same choice A116 and 20260828172725 make.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conrelid = 'public.misconceptions'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) ILIKE '%resolved_reason%'
      AND pg_get_constraintdef(oid) ILIKE '%correct_unassisted_isomorph%'
  ) THEN
    ALTER TABLE public.misconceptions
      ADD CONSTRAINT misconceptions_resolved_reason_check
      CHECK (resolved_reason IS NULL OR resolved_reason IN ('evidence_void','correct_unassisted_isomorph')) NOT VALID;
  END IF;
END $$;

-- @@ unit 20261108115157_learning_evidence_void_grants.sql
-- 20261108115157_learning_evidence_void_grants.sql
-- Learning loop spec §13 A123: the backend holds SELECT and INSERT only on the
-- two append-only records 20261108072715_learning_evidence_void.sql created,
-- learning_evidence_voids and misconception_attempts.
--
-- That migration revoked PUBLIC, anon and authenticated, and granted
-- service_role SELECT and INSERT. On Supabase that grant changes nothing:
-- Supabase's default privileges already give service_role ALL on every new
-- public table (the 20260928022711_feature_flags.sql note covers the same
-- defaults for anon and authenticated). So service_role kept UPDATE, DELETE,
-- TRUNCATE, REFERENCES and TRIGGER, and the backend could delete a void row.
-- The append-only trigger refuses only an UPDATE. A plain Postgres has no
-- such defaults, which is why the PostgreSQL 16 proof did not show it. The
-- integration lane on the local stack does:
-- test_the_void_record_is_append_only_and_backend_only.
--
-- Nothing else needs the dropped privileges. The backend reads both tables and
-- inserts through the void commit and misconception_record, both SECURITY
-- INVOKER. No code path updates or deletes either table. A foreign-key cascade
-- (from node_mastery_events or misconceptions) runs as the table owner, not as
-- service_role.
--
-- Guarded: a plain Postgres has no service_role. Idempotent: REVOKE ALL, then
-- the same GRANT.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        REVOKE ALL ON TABLE learning_evidence_voids FROM service_role;
        REVOKE ALL ON TABLE misconception_attempts FROM service_role;
        GRANT SELECT, INSERT ON TABLE learning_evidence_voids TO service_role;
        GRANT SELECT, INSERT ON TABLE misconception_attempts TO service_role;
    END IF;
END $$;

-- @@ unit 20261108115720_learning_evidence_snapshot_exact_floats.sql
-- 20261108115720_learning_evidence_snapshot_exact_floats.sql
-- Learning loop spec §13 A123 (and §5's single writer): the two snapshot
-- functions the evidence writer plans from return every double precision
-- value exactly, whatever the server's extra_float_digits.
--
-- The Supabase image's postgresql.conf sets extra_float_digits = 0 (pg_settings
-- source "configuration file"; PostgreSQL's own default is 1). At 0, float8
-- output is rounded to 15 significant digits. That applies to text, and to
-- to_jsonb(), which formats a float8 with its output function. A learner_state
-- row stored as p_known = 0.30000000000000004 reads back through
-- learning_evidence_snapshot as 0.3.
--
-- So the writer planned each operation from a state rounded to 15 digits, while
-- the stored state, and A123's replay of the journal
-- (learning/evidence_replay.py, which reads a state back exactly as stored),
-- kept all 17. A staff retire's recompute then differed from the writer's own
-- state in the last digits. The integration lane shows it:
-- test_a_staff_retire_voids_the_items_evidence_and_recomputes_a_history_without_it
-- (p_known 0.892252117844727 against 0.892252117844728). PostgreSQL 16's
-- default (1) hides it.
--
-- A function-level setting makes both snapshots exact on any server and changes
-- nothing else. Above 0, float8 output is the shortest text that reads back as
-- the same double. Every other read, through PostgREST or psql, keeps the
-- server's setting. learning_evidence_receipt and learning_evidence_commit
-- return only stored jsonb (the plan the backend sent), so they are exact
-- already.
--
-- ALTER FUNCTION ... SET changes only this parameter: search_path, lock_timeout
-- and statement_timeout stay. A later CREATE OR REPLACE of either function
-- must carry the setting itself, because it replaces every SET clause
-- (tests/test_learning_evidence_void.py pins this). Idempotent.

ALTER FUNCTION learning_evidence_snapshot(text, text, text[], jsonb) SET extra_float_digits = 3;
ALTER FUNCTION learning_evidence_void_snapshot(text, text, text) SET extra_float_digits = 3;

-- @@ unit 20261108162223_learning_exact_floats.sql
-- 20261108162223_learning_exact_floats.sql
-- Learning loop spec §13 A136: every double precision and real value the
-- backend reads through PostgREST comes back exact.
--
-- The Supabase Postgres image sets extra_float_digits = 0 in its
-- postgresql.conf (supabase/postgres, ansible/files/postgresql_config/
-- postgresql.conf.j2, the file the Docker image copies and the hosted AMI
-- templates). PostgreSQL's own default is 1. At 0, float8 output is rounded to
-- 15 significant digits and float4 output to 6, in text and in to_jsonb(). Every
-- PostgREST response body is built that way, so the backend read
-- p_known = 0.30000000000000004 back as 0.3, and a real column such as
-- quiz_responses.confidence to 6 digits. 20261108115720 fixed the two learning
-- evidence snapshot functions only; the backend's other reads of learner_state,
-- graph_nodes, node_mastery_events, flashcards, check_items, posttest_poses,
-- documents and the float-returning functions stayed rounded.
--
-- The backend reaches PostgREST with the service key only, so every request
-- runs as service_role. PostgREST logs in as authenticator and switches role
-- per request; PostgreSQL applies role settings at login only, so a setting on
-- service_role is applied by PostgREST itself: since PostgREST 11.0.0 it reads
-- the settings of the roles authenticator may switch to (those a user may set,
-- pg_settings.context = 'user', as extra_float_digits is) and applies each as a
-- transaction-scoped set_config on every request that runs as the role. It
-- reads them at start and on NOTIFY pgrst, 'reload config' (below). Above 0,
-- float output is the shortest text that reads back as the same value.
--
-- Hosted Supabase allows it: supautils lists service_role* among the reserved
-- roles, and the trailing * lets the privileged role change their settings;
-- Supabase's own docs change role settings this way (ALTER ROLE ... SET
-- statement_timeout, then NOTIFY pgrst, 'reload config').
--
-- Unchanged: the server default (every other connection: psql, the
-- dashboard, the migration runner), and 20261108115720's function-level
-- settings on the two snapshot functions, which keep them exact on any path.
--
-- learning_float_probe() returns known values for the release fence
-- (scripts/learning_release_verify.py --rest-float-probe) and the integration
-- lane: read through PostgREST as service_role, the exact path the backend
-- uses, they parse back to the same doubles only when the setting is applied.
-- No data, no write: STABLE, so PostgREST runs a GET of it read-only. It sets
-- no extra_float_digits of its own, or it would measure nothing.
--
-- Deploy: apply before or after the code (the code reads either way; this
-- makes its reads exact). Then run the fence's probe. Role statements are
-- guarded (a plain Postgres has no Supabase roles). Idempotent.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        ALTER ROLE service_role SET extra_float_digits = 3;
    END IF;
END $$;

CREATE OR REPLACE FUNCTION public.learning_float_probe()
RETURNS TABLE (float8_value double precision, float4_value real, jsonb_value jsonb, digits text)
LANGUAGE sql
STABLE
SET search_path = ''
AS $$
    SELECT 0.30000000000000004::double precision,
           0.12345679::real,
           pg_catalog.to_jsonb(0.30000000000000004::double precision),
           pg_catalog.current_setting('extra_float_digits')
$$;

REVOKE ALL ON FUNCTION public.learning_float_probe() FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON FUNCTION public.learning_float_probe() FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT EXECUTE ON FUNCTION public.learning_float_probe() TO service_role;
    END IF;
END $$;

-- The role setting reaches PostgREST on a config reload; the function on a
-- schema reload. Both are delivered at COMMIT, and are no-ops with no listener.
NOTIFY pgrst, 'reload config';
NOTIFY pgrst, 'reload schema';

-- @@ unit 20261108163653_learning_llm_usage_course_id.sql
-- 20261108163653_learning_llm_usage_course_id.sql
-- Learning loop spec §13 A137: the course an llm_usage row's run served, when
-- the run site knows it (agents/usage.py::record_agent_usage(course_id=…)), so
-- the admin cost-per-learning-gain report (learning/cost_per_gain.py) can put
-- every loop dollar on its course.
--
-- A loop session names its course (sessions.offering_id), so a session row was
-- attributable already through its session_id (A92). The runs with no session
-- were not: check-item drafting and its alignment and key checks (course
-- assets, run on upload or by the backfill) and the post-test's grade and
-- decisions. Those run sites now record the abstract course id their deps
-- carry (the course the graph, the items and posttest_poses key on). Rows
-- written before this migration keep NULL: unknown, never inferred; the
-- report counts them as unattributed.
--
-- Additive and nullable: no default, no backfill, no index (the report reads a
-- created_at window). llm_usage's RLS and grants are table-level (0035) and
-- cover the new column unchanged. A deploy that reaches a database before this
-- migration drops the column from its inserts and retries
-- (services/events_service.py _OPTIONAL_COLUMNS), so no usage row is lost and
-- the budget caps keep reading every row; the admin report reads without it.
ALTER TABLE llm_usage ADD COLUMN IF NOT EXISTS course_id text;

-- PostgREST serves the new column from its schema cache; reload it (a no-op with
-- no listener).
NOTIFY pgrst, 'reload schema';

-- @@ unit 20261108184825_learning_teach_prompts.sql
-- 20261108184825_learning_teach_prompts.sql
-- Learning loop spec §13 A138 (the segment prequestion, flag
-- `segment_prequestion`) and A139 (self-explanation prompts, flag
-- `self_explanation_prompts`): what each stores. Neither is evidence — no row
-- here ever reaches node_mastery_events, learner_state, misconceptions or the
-- help ledger's rungs.
--
-- 1. learning_prequestions — one ANSWERED prequestion: the student's guess at
--    the vetted item posed when the plan reached a new concept (or "no idea"),
--    and when. Append-only, one row per (student, session, concept): a retried
--    answer request inserts nothing new. `guess_json` is ENCRYPTED JSON
--    {option, reason, answer} (services/encryption.encrypt_json); NULL exactly
--    when the student said "no idea". `format` and `difficulty` are the item's
--    isomorph class, which A76's re-check rule reads for 24 hours after the
--    answer (learning/prequestion_store.py::releases).
-- 2. learning_self_explanations — one SERVED self-explanation prompt and, when
--    the student replied, the reply. Written 'open' when the turn that carries
--    the prompt is served (its id is the prompt id the client echoes), then
--    'replied' (reply_text ENCRYPTED, reply_chars its length) or 'skipped'. A
--    prompt the student moved past stays 'open' (never replied). Read only by
--    the admin learning-loop report.
--
-- Ids, hashes, enums, counts and timestamps in plaintext; student text only
-- in the two encrypted columns. Backend-only (RLS on, no policy; service_role
-- bypasses it): learning_prequestions SELECT + INSERT, learning_self_explanations
-- SELECT + INSERT + UPDATE (the reply closes the row). Idempotent.
--
-- Deploy order: BEFORE the code that writes them. With the flags off nothing
-- writes either table; the A76 read (recheck_after_release) reads
-- learning_prequestions on every grade and treats a failed read as "decides
-- nothing", so a backend deployed first grades exactly as before.

CREATE TABLE IF NOT EXISTS learning_prequestions (
  id            text        PRIMARY KEY DEFAULT gen_random_uuid()::text,
  user_id       text        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  session_id    text        NOT NULL,
  course_id     text,
  node_id       text        NOT NULL,
  check_item_id text,
  question_hash text        NOT NULL,
  format        text        NOT NULL CHECK (format IN ('free', 'teachback', 'mc_reason')),
  difficulty    smallint    NOT NULL CHECK (difficulty BETWEEN 1 AND 3),
  no_idea       boolean     NOT NULL,
  guess_json    text,
  posed_at      timestamptz NOT NULL,
  answered_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, session_id, node_id),
  CHECK (no_idea = (guess_json IS NULL))
);
CREATE INDEX IF NOT EXISTS learning_prequestions_user_node_answered
  ON learning_prequestions (user_id, node_id, answered_at);

CREATE TABLE IF NOT EXISTS learning_self_explanations (
  id            text        PRIMARY KEY,
  user_id       text        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  session_id    text        NOT NULL,
  course_id     text,
  node_id       text        NOT NULL,
  question_hash text,
  juncture      text        NOT NULL
                CHECK (juncture IN ('worked_example', 'released_solution', 'first_correct')),
  rung          smallint    CHECK (rung IS NULL OR rung BETWEEN 0 AND 6),
  prompted_at   timestamptz NOT NULL,
  status        text        NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'replied', 'skipped')),
  closed_at     timestamptz,
  reply_text    text,
  reply_chars   integer     CHECK (reply_chars IS NULL OR reply_chars >= 0),
  CHECK ((status = 'replied') = (reply_text IS NOT NULL)),
  CHECK ((status = 'replied') = (reply_chars IS NOT NULL)),
  CHECK ((status = 'open') = (closed_at IS NULL))
);
CREATE INDEX IF NOT EXISTS learning_self_explanations_prompted
  ON learning_self_explanations (prompted_at, id);
CREATE INDEX IF NOT EXISTS learning_self_explanations_user_node
  ON learning_self_explanations (user_id, node_id, prompted_at);

-- Backend-only (the 20261108093359_learning_posttest_outcomes.sql idiom), and
-- the backend holds only what it uses (the 20261108115157 lesson: Supabase's
-- default privileges give service_role ALL on a new table, so REVOKE first).
-- Role statements are guarded: a plain Postgres has none of these roles.
ALTER TABLE learning_prequestions ENABLE ROW LEVEL SECURITY;
ALTER TABLE learning_self_explanations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE learning_prequestions FROM PUBLIC;
REVOKE ALL ON TABLE learning_self_explanations FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON TABLE learning_prequestions FROM %I', r);
            EXECUTE format('REVOKE ALL ON TABLE learning_self_explanations FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        REVOKE ALL ON TABLE learning_prequestions FROM service_role;
        REVOKE ALL ON TABLE learning_self_explanations FROM service_role;
        GRANT SELECT, INSERT ON TABLE learning_prequestions TO service_role;
        GRANT SELECT, INSERT, UPDATE ON TABLE learning_self_explanations TO service_role;
    END IF;
END $$;

-- PostgREST serves the new tables from its schema cache; reload it (a no-op
-- with no listener).
NOTIFY pgrst, 'reload schema';

-- @@ unit 20261108185101_learning_varied_practice.sql
-- 20261108185101_learning_varied_practice.sql
-- Learning loop varied practice (spec §13 A140, A141). Four nullable
-- check_items columns; every row stored before keeps NULL in all four and
-- reads exactly as before.
--
-- A140, surface-varied isomorphs (flag `varied_isomorphs`): the varied
-- drafter states each item's surface (learning/surface.py).
--   surface_representation — how the question presents the idea, one of
--     learning.params.SURFACE_REPRESENTATIONS. A closed enum says nothing
--     about the item's content: plaintext.
--   surface_context — a short label naming the item's scenario. That IS item
--     content: encrypted at write (services/encryption.py), decrypted at read.
--   A descriptor is whole or absent: both columns or neither.
--
-- A141, multi-concept items (flag `multi_concept_items`,
-- learning/multi_concept.py): an item combining its apex concept with one or
-- two of the apex's direct prerequisites.
--   apex_key — the apex's concept key (plaintext, like concept_key); the
--     multi-concept picker's lookup.
--   component_keys — the components' concept keys, the apex first (plaintext,
--     like concept_key).
--   Such a row's concept_key is its components joined by the ASCII unit
--     separator (chr(31)), which no concept key ever holds
--     (graph_service._normalize_concept collapses it as whitespace): no
--     per-concept read, picker, reserve or post-test ever meets one.
--
-- Deploy order: this migration may run before or after the code. No read on
-- the request path selects these columns while both flags are off, and a
-- write names them only for a flag-on drafting run.

ALTER TABLE public.check_items ADD COLUMN IF NOT EXISTS surface_representation text;
ALTER TABLE public.check_items ADD COLUMN IF NOT EXISTS surface_context text;
ALTER TABLE public.check_items ADD COLUMN IF NOT EXISTS apex_key text;
ALTER TABLE public.check_items ADD COLUMN IF NOT EXISTS component_keys text[];

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'check_items_surface_representation_known'
    ) THEN
        ALTER TABLE public.check_items ADD CONSTRAINT check_items_surface_representation_known
            CHECK (
                surface_representation IS NULL
                OR surface_representation IN ('verbal', 'symbolic', 'numeric', 'visual', 'applied')
            );
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'check_items_surface_whole') THEN
        ALTER TABLE public.check_items ADD CONSTRAINT check_items_surface_whole
            CHECK ((surface_representation IS NULL) = (surface_context IS NULL));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'check_items_multi_concept_shape') THEN
        ALTER TABLE public.check_items ADD CONSTRAINT check_items_multi_concept_shape
            CHECK (
                (apex_key IS NULL AND component_keys IS NULL AND strpos(concept_key, chr(31)) = 0)
                OR (
                    apex_key IS NOT NULL
                    AND component_keys IS NOT NULL
                    AND cardinality(component_keys) BETWEEN 2 AND 3
                    AND component_keys[1] = apex_key
                    AND concept_key = array_to_string(component_keys, chr(31))
                )
            );
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_check_items_apex
    ON public.check_items (course_id, apex_key)
    WHERE apex_key IS NOT NULL;

-- PostgREST resolves the new columns from its schema cache; the local stack
-- does not reliably reload on DDL (docs/local-supabase.md). NOTIFY is
-- delivered at COMMIT and is a no-op with no listener.
NOTIFY pgrst, 'reload schema';

-- @@ unit 20261108193927_learning_report_course_key.sql
-- 20261108193927_learning_report_course_key.sql
-- Learning loop spec §13 A142: two integrity fixes found while reconciling the
-- engineer's guide (docs/learning-loop/) with the code.
--
-- 1. A report is keyed per COURSE item. check_item_reports' primary key was
--    (user_id, question_hash), but a report is about one course's item:
--    check_item_reviews, the reporter count and the per-item advisory lock
--    all key on (course_id, question_hash), and question_hash is a hash of the
--    plaintext prompt, so the same question drafted in two courses shares it.
--    A student's report of the second course's copy therefore hit
--    ON CONFLICT DO NOTHING and was dropped: that course's item counted one
--    reporter short, and its other students kept being served an item the
--    reports should have quarantined. The primary key becomes
--    (user_id, course_id, question_hash). It is a superset of the old key, so
--    every stored row stays unique and nothing is rewritten.
--    check_item_report_quarantine is re-created with the matching ON CONFLICT
--    target; the rest of its body is 20261108072715's, verbatim. The A113
--    signature (check_item_report) goes through it and is unchanged.
--
-- 2. misconception_record records nothing for a node the student does not
--    own. The seven-argument function (20261108072715) already read the
--    node's course with the owner filter, but inserted anyway when that read
--    found nothing, with no course for the retired-item check. A caller bug
--    could then store a misconception of one student on another student's
--    node, and that student deleting the node would cascade into the first
--    student's misconceptions. Every caller passes the student's own node
--    today; the function now refuses any other, returning no row — the
--    Python wrapper's "nothing recorded", as for an attempt on a retired item.
--    The rest of its body is 20261108072715's, verbatim; the six-argument
--    form goes through it and is unchanged.
--
-- Deploy order: either side of the backend code. The backend's calls and
-- their arguments are unchanged, and an old backend reads the same results.
-- Idempotent: the key change runs only while the old key is in place, and
-- CREATE OR REPLACE keeps each function's owner and grants.

-- ── 1. check_item_reports: one report per (student, course item) ───────────

DO $$
DECLARE
  v_name text;
  v_cols text[];
BEGIN
  SELECT c.conname, array_agg(a.attname::text ORDER BY k.ord)
    INTO v_name, v_cols
    FROM pg_constraint c
    CROSS JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord)
    JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
   WHERE c.conrelid = 'public.check_item_reports'::regclass AND c.contype = 'p'
   GROUP BY c.conname;
  IF v_cols IS DISTINCT FROM ARRAY['user_id', 'course_id', 'question_hash'] THEN
    IF v_name IS NOT NULL THEN
      EXECUTE format('ALTER TABLE public.check_item_reports DROP CONSTRAINT %I', v_name);
    END IF;
    ALTER TABLE public.check_item_reports ADD PRIMARY KEY (user_id, course_id, question_hash);
  END IF;
END $$;

-- One report. Returns one row: first_report (this student had not reported
-- this course's item before; a repeat records nothing), reporters (distinct
-- reporters of the course item since its last approval) and quarantine (this
-- report is the one that reached p_min_reporters on an item neither
-- quarantined nor retired: it is quarantined now, and every stored row of it
-- held — `reports_threshold` — in this same transaction). Under the per-item
-- advisory lock, so of reporters arriving together exactly one is told it
-- quarantined the item.
CREATE OR REPLACE FUNCTION check_item_report_quarantine(
  p_user_id text,
  p_course_id text,
  p_question_hash text,
  p_reason text,
  p_surface text,
  p_min_reporters integer
)
RETURNS TABLE (first_report boolean, reporters integer, quarantine boolean)
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
  v_first boolean;
  v_status text;
  v_approved timestamptz;
  v_count integer;
BEGIN
  IF coalesce(p_user_id, '') = '' OR coalesce(p_course_id, '') = ''
     OR coalesce(p_question_hash, '') = '' OR coalesce(p_min_reporters, 0) < 1 THEN
    RAISE EXCEPTION 'Invalid check item report';
  END IF;
  PERFORM pg_advisory_xact_lock(
    hashtextextended('check-item-review:' || p_course_id || ':' || p_question_hash, 0));
  INSERT INTO check_item_reports (user_id, question_hash, course_id, reason, surface, created_at)
  VALUES (p_user_id, p_question_hash, p_course_id, p_reason, p_surface, clock_timestamp())
  ON CONFLICT (user_id, course_id, question_hash) DO NOTHING;
  v_first := FOUND;
  SELECT r.status, r.approved_at INTO v_status, v_approved
    FROM check_item_reviews r
   WHERE r.course_id = p_course_id AND r.question_hash = p_question_hash;
  SELECT count(*)::integer INTO v_count
    FROM check_item_reports c
   WHERE c.course_id = p_course_id AND c.question_hash = p_question_hash
     AND (v_approved IS NULL OR c.created_at > v_approved);
  first_report := v_first;
  reporters := v_count;
  quarantine := v_first AND v_count >= p_min_reporters
    AND v_status IS DISTINCT FROM 'quarantined' AND v_status IS DISTINCT FROM 'retired';
  IF quarantine THEN
    INSERT INTO check_item_reviews (course_id, question_hash, status, decided_by, reviewed_by, reviewed_at)
    VALUES (p_course_id, p_question_hash, 'quarantined', 'reports', NULL, clock_timestamp())
    ON CONFLICT (course_id, question_hash) DO UPDATE
      SET status = 'quarantined', decided_by = 'reports', reviewed_by = NULL,
          reviewed_at = EXCLUDED.reviewed_at;
    UPDATE check_items c
       SET lint_flags = check_item_hold_flags(c.lint_flags, 'quarantined')
     WHERE c.course_id = p_course_id AND c.question_hash = p_question_hash
       AND c.lint_flags IS DISTINCT FROM check_item_hold_flags(c.lint_flags, 'quarantined');
  END IF;
  RETURN NEXT;
END
$$;

-- ── 2. misconception_record: only on the student's own node ────────────────

-- Insert-or-increment as before (20260929143810), plus the attempt's support
-- row — and nothing at all for an attempt graded against an item staff
-- retired (its evidence is void, so it supports nothing), or for a node that
-- is not the student's (spec §13 A142).
CREATE OR REPLACE FUNCTION misconception_record(
  p_id text, p_user_id text, p_node_id text, p_check_item_id text,
  p_wrong_key text, p_evidence_text text, p_question_hash text
)
RETURNS TABLE (id text, count int)
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
#variable_conflict use_column
DECLARE
  v_course text;
  v_owned boolean;
  v_id text;
  v_count int;
BEGIN
  SELECT true, g.course_id INTO v_owned, v_course
    FROM graph_nodes g WHERE g.id = p_node_id AND g.user_id = p_user_id;
  IF v_owned IS NOT TRUE THEN
    RETURN;  -- not the student's node: nothing is recorded
  END IF;
  IF p_question_hash IS NOT NULL AND v_course IS NOT NULL THEN
    PERFORM pg_advisory_xact_lock_shared(
      hashtextextended('check-item-review:' || v_course || ':' || p_question_hash, 0));
    IF EXISTS (
      SELECT 1 FROM check_item_reviews r
       WHERE r.course_id = v_course AND r.question_hash = p_question_hash
         AND r.status = 'retired'
    ) THEN
      RETURN;
    END IF;
  END IF;
  INSERT INTO misconceptions AS m
    (id, user_id, node_id, check_item_id, wrong_key, evidence_text, count)
  VALUES (p_id, p_user_id, p_node_id, p_check_item_id, p_wrong_key, p_evidence_text, 1)
  ON CONFLICT (user_id, node_id, wrong_key) WHERE resolved_at IS NULL
  DO UPDATE SET count = m.count + 1,
                last_seen_at = now(),
                check_item_id = EXCLUDED.check_item_id,
                evidence_text = EXCLUDED.evidence_text
  RETURNING m.id, m.count INTO v_id, v_count;
  INSERT INTO misconception_attempts (misconception_id, course_id, question_hash, check_item_id)
  VALUES (v_id, v_course, p_question_hash, p_check_item_id);
  id := v_id;
  count := v_count;
  RETURN NEXT;
END
$$;

NOTIFY pgrst, 'reload schema';

-- @@ unit 20261108205812_learning_varied_practice_review.sql
-- 20261108205812_learning_varied_practice_review.sql
-- Learning loop spec §13 A141, the review's fixes to 20261108185101. Two
-- changes; every row and every evidence plan the code writes with
-- multi_concept_items off is exactly as before.
--
-- (1) check_items_multi_concept_shape, closed. The constraint 20261108185101
--     added let through a row the code never writes: array_to_string skips
--     NULL elements, so apex_key 'a', component_keys '{a,NULL}' and
--     concept_key 'a' passed, and a per-concept read (concept_key=eq.a) would
--     have met that row. Distinct, non-empty components and a component free
--     of the separator were unenforced too. The replacement keeps the
--     single-concept branch (no apex, no components, no separator) and
--     requires on the multi-concept branch: a one-dimensional array indexed
--     from 1 holding 2 or 3 components, none NULL or empty, all distinct, the
--     first the apex; a concept_key that holds the separator (chr(31)), is
--     exactly the components joined by it, and holds one separator per join
--     (so no component holds one). A CHECK passes on NULL, so the whole
--     expression is COALESCE(..., false): any NULL it meets fails the row.
--     Every stored row passes it (learning/multi_concept.combo_key writes
--     nothing else; a concept's own row is the unchanged first branch).
--
-- (2) node_mastery_events.multi_concept: the evidence journal says which rows
--     a multi-concept item graded (spec §13 A141 (e), (f)). The item's
--     check_items row cannot say it for good: an A23 consent withdrawal or a
--     staff retire deletes it, and the item statistics (learning/item_stats.py)
--     must still keep its answers out of the apex's own items' rest scores and
--     its voids out of their change times. NULL on every other row (no
--     default; adding the column rewrites nothing).
--     learning_evidence_commit is re-created as 20261108103333's definition
--     with three edits, verbatim otherwise: 'multi_concept' in the event key
--     whitelist, its type check (a JSON boolean or null), and its insert
--     column and value. The writer (services/graph_service.py) names the key
--     only on a multi-concept row, so every other row, plan and operation is
--     exactly as before. The registry in
--     backend/tests/test_learning_migration_functions.py pins that this
--     definition keeps every earlier change.
--
-- Deploy order: apply before the code. The item statistics read
-- (routes/admin_check_items.py) selects the new column; nothing else needs
-- it while multi_concept_items is off, and older code never names it.
--
-- Locks (amended before any apply, the second review; sanctioned in
-- tests/test_learning_loop_invariants.py::_AMENDED_BEFORE_ANY_APPLY). This
-- file runs in one transaction (db/migrate.py), and every lock it takes is
-- ACCESS EXCLUSIVE and held to its commit: check_items for the constraint,
-- node_mastery_events for the column. Two rules keep that brief:
--   * lock_timeout 5s: a lock that does not come within 5s fails the file
--     (rolled back, nothing recorded; run it again), instead of queueing
--     every learning_evidence_commit (its own lock_timeout is 2s) behind a
--     waiting ALTER until a long reader finishes;
--   * the CHECK is added NOT VALID, so nothing scans check_items under the
--     lock (new and updated rows are checked at once).
--     20261108224511_learning_varied_practice_validate.sql validates it in its
--     own transaction, under SHARE UPDATE EXCLUSIVE, which blocks no read or
--     write.

SET LOCAL lock_timeout = '5s';

ALTER TABLE public.check_items DROP CONSTRAINT IF EXISTS check_items_multi_concept_shape;
ALTER TABLE public.check_items ADD CONSTRAINT check_items_multi_concept_shape
    CHECK (COALESCE(
        (apex_key IS NULL AND component_keys IS NULL AND strpos(concept_key, chr(31)) = 0)
        OR (
            apex_key IS NOT NULL
            AND component_keys IS NOT NULL
            AND array_ndims(component_keys) = 1
            AND array_lower(component_keys, 1) = 1
            AND cardinality(component_keys) BETWEEN 2 AND 3
            AND array_position(component_keys, NULL) IS NULL
            AND array_position(component_keys, '') IS NULL
            AND component_keys[1] = apex_key
            AND component_keys[1] <> component_keys[2]
            AND (
                cardinality(component_keys) = 2
                OR (component_keys[3] <> component_keys[1] AND component_keys[3] <> component_keys[2])
            )
            AND strpos(concept_key, chr(31)) > 0
            AND concept_key = array_to_string(component_keys, chr(31))
            AND length(concept_key) - length(replace(concept_key, chr(31), ''))
                = cardinality(component_keys) - 1
        ),
        false
    )) NOT VALID;

ALTER TABLE public.node_mastery_events ADD COLUMN IF NOT EXISTS multi_concept boolean;

CREATE OR REPLACE FUNCTION learning_evidence_commit(
    p_user_id text,p_course_id text,p_operation_id uuid,p_input_fingerprint text,p_plan jsonb
) RETURNS jsonb LANGUAGE plpgsql SET search_path=public,pg_temp
SET lock_timeout='2s' SET statement_timeout='10s' AS $$
DECLARE r learning_evidence_operations%ROWTYPE; x jsonb; v bigint; ids text[];
    grade_ids text[]; es jsonb; n graph_nodes%ROWTYPE; s learner_state%ROWTYPE;
    ev node_mastery_events%ROWTYPE; obs jsonb; expected_count bigint; actual_count bigint;
    item record; retired_items jsonb;
BEGIN
    IF p_user_id IS NULL OR p_user_id='' OR p_operation_id IS NULL
       OR p_input_fingerprint IS NULL OR p_input_fingerprint !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(p_plan) IS DISTINCT FROM 'object'
       OR (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(p_plan) k)
          IS DISTINCT FROM ARRAY['changes','checks','edges','events','mirrors','nodes','observed_at','state_rows','states_expected']::text[]
       OR EXISTS(SELECT 1 FROM jsonb_each(p_plan) p WHERE p.key<>'observed_at' AND jsonb_typeof(p.value)<>'array')
       OR jsonb_typeof(p_plan->'observed_at') NOT IN ('null','string') THEN
        RAISE EXCEPTION 'Invalid evidence transaction envelope';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('learning-evidence:'||p_user_id,0));
    SELECT * INTO r FROM learning_evidence_operations WHERE operation_id=p_operation_id;
    IF FOUND THEN
        IF r.user_id IS DISTINCT FROM p_user_id OR r.course_id IS DISTINCT FROM p_course_id
           OR r.input_fingerprint IS DISTINCT FROM p_input_fingerprint OR r.plan IS DISTINCT FROM p_plan THEN
            RETURN jsonb_build_object('status','conflict');
        END IF;
        RETURN jsonb_build_object('status','replay','receipt',jsonb_build_object(
            'operation_id',r.operation_id,'user_id',r.user_id,'course_id',r.course_id,
            'input_fingerprint',r.input_fingerprint,'changes',r.changes,'posteriors',(
                SELECT jsonb_object_agg(value->>'id',value->'mastery_score') FROM jsonb_array_elements(r.plan->'mirrors')),
            'observations',(SELECT coalesce(jsonb_agg(entry.value->'planning_observation' ORDER BY entry.position),'[]')
                FROM jsonb_array_elements(r.plan->'events') WITH ORDINALITY entry(value,position)
                WHERE jsonb_typeof(entry.value->'planning_observation')='object')));
    END IF;
    -- §13 A123: a check item staff retired takes no new evidence. A SHARED lock
    -- per graded item (sorted), against check_item_review_decide's EXCLUSIVE one:
    -- a retire decided while this grade was in flight waits for its commit (and
    -- the void sweep then finds the row); a grade arriving after it is refused.
    FOR item IN
        SELECT DISTINCT g.course_id AS course_id, e.value->>'question_hash' AS question_hash
          FROM jsonb_array_elements(p_plan->'events') e
          JOIN graph_nodes g ON g.id = e.value->>'node_id'
         WHERE jsonb_typeof(e.value->'check_item_id') = 'string'
           AND jsonb_typeof(e.value->'question_hash') = 'string'
           AND g.course_id IS NOT NULL
         ORDER BY 1, 2
    LOOP
        PERFORM pg_advisory_xact_lock_shared(
            hashtextextended('check-item-review:'||item.course_id||':'||item.question_hash,0));
    END LOOP;
    SELECT coalesce(jsonb_agg(jsonb_build_object('course_id',q.course_id,'question_hash',q.question_hash)
               ORDER BY q.course_id,q.question_hash),'[]') INTO retired_items
      FROM (SELECT DISTINCT g.course_id AS course_id, e.value->>'question_hash' AS question_hash
              FROM jsonb_array_elements(p_plan->'events') e
              JOIN graph_nodes g ON g.id = e.value->>'node_id'
             WHERE jsonb_typeof(e.value->'check_item_id') = 'string'
               AND jsonb_typeof(e.value->'question_hash') = 'string'
               AND g.course_id IS NOT NULL) q
     WHERE EXISTS(SELECT 1 FROM check_item_reviews cr WHERE cr.course_id=q.course_id
                  AND cr.question_hash=q.question_hash AND cr.status='retired');
    IF jsonb_array_length(retired_items) > 0 THEN
        RETURN jsonb_build_object('status','retired','items',retired_items);
    END IF;
    SELECT array_agg(value->>'id' ORDER BY value->>'id') INTO ids FROM jsonb_array_elements(p_plan->'nodes');
    SELECT array_agg(DISTINCT value->>'node_id' ORDER BY value->>'node_id') INTO grade_ids
        FROM jsonb_array_elements(p_plan->'events');
    IF coalesce(cardinality(ids),0)=0 OR coalesce(cardinality(grade_ids),0)=0
       OR cardinality(ids)<>(SELECT count(DISTINCT unnest) FROM unnest(ids))
       OR jsonb_array_length(p_plan->'changes')<>jsonb_array_length(p_plan->'events') THEN
        RAISE EXCEPTION 'Invalid evidence transaction members';
    END IF;
    -- Short, bounded coarse lock closes phantom edge inserts AND relation/
    -- endpoint edits/deletes from legacy writers. Acquire it before node locks
    -- so a legacy edge FK check cannot form a node/table lock-order inversion.
    LOCK TABLE graph_edges IN SHARE MODE;
    PERFORM 1 FROM graph_nodes WHERE id=ANY(ids) ORDER BY id FOR UPDATE;
    IF (SELECT count(*) FROM graph_nodes WHERE id=ANY(ids) AND user_id=p_user_id
        AND (p_course_id IS NULL OR course_id=p_course_id))<>cardinality(ids) THEN
        RETURN jsonb_build_object('status','ownership');
    END IF;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'nodes') LOOP
        IF jsonb_typeof(x->'version') IS DISTINCT FROM 'number' OR (x->>'version') !~ '^[0-9]+$' THEN
            RAISE EXCEPTION 'Invalid graph version';
        END IF;
        SELECT evidence_version INTO v FROM graph_nodes WHERE id=x->>'id';
        IF v IS DISTINCT FROM (x->>'version')::bigint THEN RETURN jsonb_build_object('status','stale'); END IF;
    END LOOP;
    SELECT coalesce(jsonb_agg(jsonb_build_object('source',e.source_node_id,'target',e.target_node_id)
               ORDER BY e.source_node_id,e.target_node_id),'[]') INTO es
      FROM graph_edges e JOIN graph_nodes a ON a.id=e.source_node_id JOIN graph_nodes b ON b.id=e.target_node_id
      WHERE e.user_id=p_user_id AND e.relationship_type='prerequisite'
        AND a.user_id=p_user_id AND b.user_id=p_user_id AND a.course_id IS NOT DISTINCT FROM b.course_id
        AND (p_course_id IS NULL OR a.course_id=p_course_id)
        AND (e.source_node_id=ANY(grade_ids) OR e.target_node_id=ANY(grade_ids));
    IF es IS DISTINCT FROM p_plan->'edges' THEN RETURN jsonb_build_object('status','stale'); END IF;
    PERFORM 1 FROM learner_state WHERE user_id=p_user_id AND node_id=ANY(ids) ORDER BY node_id FOR UPDATE;
    IF jsonb_array_length(p_plan->'states_expected')<>cardinality(ids)
       OR (SELECT count(DISTINCT value->>'node_id') FROM jsonb_array_elements(p_plan->'states_expected'))<>cardinality(ids)
       OR EXISTS(SELECT 1 FROM jsonb_array_elements(p_plan->'states_expected') WHERE NOT (value->>'node_id'=ANY(ids))) THEN
        RAISE EXCEPTION 'Invalid learner-state snapshot';
    END IF;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'states_expected') LOOP
        IF jsonb_typeof(x->'version') NOT IN ('number','null')
           OR (x->>'version' IS NOT NULL AND (x->>'version') !~ '^[0-9]+$') THEN
            RAISE EXCEPTION 'Invalid learner-state version';
        END IF;
        SELECT evidence_version INTO v FROM learner_state WHERE user_id=p_user_id AND node_id=x->>'node_id';
        IF v IS DISTINCT FROM (x->>'version')::bigint THEN RETURN jsonb_build_object('status','stale'); END IF;
    END LOOP;
    IF p_plan->>'observed_at' IS NOT NULL AND EXISTS(
        SELECT 1 FROM learner_state l WHERE l.user_id=p_user_id
        AND l.node_id IN (SELECT value->>'node_id' FROM jsonb_array_elements(p_plan->'state_rows'))
        AND (l.last_evidence_at > (p_plan->>'observed_at')::timestamptz
             OR l.evidence_touch_at > (p_plan->>'observed_at')::timestamptz)
    ) THEN RETURN jsonb_build_object('status','superseded'); END IF;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'checks') LOOP
        IF jsonb_typeof(x->'count') IS DISTINCT FROM 'number'
           OR (x->>'count') !~ '^[0-9]+$'
           OR jsonb_typeof(x->'global_count') IS DISTINCT FROM 'number'
           OR (x->>'global_count') !~ '^[0-9]+$' THEN
            RAISE EXCEPTION 'Invalid exposure snapshot';
        END IF;
        SELECT count(*) INTO actual_count FROM node_mastery_events e JOIN graph_nodes g ON g.id=e.node_id
            WHERE g.user_id=p_user_id AND e.event_type='evidence' AND e.session_id=x->>'session_id'
              AND e.question_hash=x->>'question_hash';
        IF actual_count IS DISTINCT FROM (x->>'count')::bigint THEN RETURN jsonb_build_object('status','stale'); END IF;
        SELECT count(*) INTO actual_count FROM node_mastery_events e JOIN graph_nodes g ON g.id=e.node_id
            WHERE g.user_id=p_user_id AND e.event_type='evidence' AND e.question_hash=x->>'question_hash';
        IF actual_count IS DISTINCT FROM (x->>'global_count')::bigint THEN RETURN jsonb_build_object('status','stale'); END IF;
    END LOOP;
    IF jsonb_array_length(p_plan->'state_rows')=0
       OR jsonb_array_length(p_plan->'state_rows')<>jsonb_array_length(p_plan->'mirrors')
       OR (SELECT count(DISTINCT value->>'node_id') FROM jsonb_array_elements(p_plan->'state_rows'))<>jsonb_array_length(p_plan->'state_rows')
       OR (SELECT count(DISTINCT value->>'id') FROM jsonb_array_elements(p_plan->'mirrors'))<>jsonb_array_length(p_plan->'mirrors')
       OR EXISTS(SELECT 1 FROM unnest(grade_ids) id WHERE NOT EXISTS(
            SELECT 1 FROM jsonb_array_elements(p_plan->'state_rows') state_entry(value)
            WHERE state_entry.value->>'node_id'=id)) THEN
        RAISE EXCEPTION 'Invalid transaction row sets';
    END IF;
    -- Validate the WHOLE plan before its first mutation. SQL does no BKT,
    -- FSRS, weighting, threshold or propagation arithmetic.
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'state_rows') LOOP
        s := jsonb_populate_record(NULL::learner_state,x);
        IF s.user_id IS DISTINCT FROM p_user_id OR NOT(s.node_id=ANY(ids))
           OR s.p_known IS NULL OR NOT(s.p_known BETWEEN 0 AND 1)
           OR s.updated_at IS NULL
           OR s.n_strong_unassisted<0 OR s.streak_unassisted<0 OR s.max_streak_unassisted<0 OR s.opps<0
           OR EXISTS(SELECT 1 FROM jsonb_object_keys(x) k WHERE k NOT IN (
                'user_id','node_id','p_known','n_strong_unassisted','streak_unassisted','max_streak_unassisted','opps',
                'fsrs_d','fsrs_s','fsrs_last_review_at','fsrs_due_at','last_evidence_at','updated_at'))
           OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_plan->'mirrors') m WHERE m->>'id'=s.node_id) THEN
            RAISE EXCEPTION 'Invalid transaction learner state';
        END IF;
    END LOOP;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'events') LOOP
        ev := jsonb_populate_record(NULL::node_mastery_events,x);
        IF ev.id IS NULL OR NOT(ev.node_id=ANY(grade_ids)) OR NOT(ev.node_id=ANY(ids))
           OR ev.event_type IS DISTINCT FROM 'evidence' OR ev.correct IS NULL
           OR ev.p_before IS NULL OR NOT(ev.p_before BETWEEN 0 AND 1)
           OR ev.p_after IS NULL OR NOT(ev.p_after BETWEEN 0 AND 1)
           OR ev.weight IS NULL OR NOT(ev.weight BETWEEN 0 AND 1)
           OR ev.created_at IS NULL OR ev.evidence_seq IS NULL OR ev.evidence_seq<0
           OR jsonb_typeof(x->'correct') IS DISTINCT FROM 'boolean'
           OR jsonb_typeof(x->'assisted') IS DISTINCT FROM 'boolean'
           -- §13 A123: the replay inputs, when present, are well formed
           OR (x ? 'retention' AND jsonb_typeof(x->'retention') NOT IN ('number','null'))
           OR (ev.retention IS NOT NULL AND NOT (ev.retention > 0 AND ev.retention <= 1))
           OR (x ? 'same_session_recheck' AND jsonb_typeof(x->'same_session_recheck') NOT IN ('boolean','null'))
           OR (x ? 'propagated_to' AND jsonb_typeof(x->'propagated_to') NOT IN ('array','null'))
           OR (jsonb_typeof(x->'propagated_to') = 'array' AND EXISTS(
                SELECT 1 FROM jsonb_array_elements(x->'propagated_to') t
                 WHERE jsonb_typeof(t) IS DISTINCT FROM 'string' OR NOT ((t #>> '{}')=ANY(ids))
                    OR (t #>> '{}')=ev.node_id
                    OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_plan->'state_rows') sr
                                   WHERE sr->>'node_id'=(t #>> '{}'))))
           OR EXISTS(SELECT 1 FROM jsonb_object_keys(x) k WHERE k NOT IN (
                'id','node_id','delta','reason','created_at','event_type','channel','correct','weight','assisted','max_rung',
                'p_before','p_after','session_id','check_item_id','question_hash','confidence','grader_backend','evidence_seq','planning_observation',
                'retention','same_session_recheck','propagated_to',
                'student_confidence',
                'multi_concept'))
           -- spec §13 A127: a stated confidence is a JSON number in [0, 1], or absent/null
           OR (x ? 'student_confidence' AND jsonb_typeof(x->'student_confidence') NOT IN ('number','null'))
           OR NOT (ev.student_confidence IS NULL OR ev.student_confidence BETWEEN 0 AND 1)
           -- spec §13 A141: a multi-concept item's row says so: a JSON boolean, or absent/null
           OR (x ? 'multi_concept' AND jsonb_typeof(x->'multi_concept') NOT IN ('boolean','null')) THEN
            RAISE EXCEPTION 'Invalid transaction evidence';
        END IF;
        obs := ev.planning_observation;
        IF obs IS NOT NULL AND (
            jsonb_typeof(obs) IS DISTINCT FROM 'object'
            OR obs->>'node_id' IS DISTINCT FROM ev.node_id OR obs->>'question_hash' IS DISTINCT FROM ev.question_hash
            OR obs->>'check_item_id' IS DISTINCT FROM ev.check_item_id OR obs->>'channel' IS DISTINCT FROM ev.channel
            OR obs->'correct' IS DISTINCT FROM to_jsonb(ev.correct)
            OR obs->'assisted' IS DISTINCT FROM to_jsonb(ev.assisted)
            OR obs->'max_rung' IS DISTINCT FROM to_jsonb(ev.max_rung)
            OR jsonb_typeof(obs->'independent') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'same_session_recheck') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'idk') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'synthetic_idk') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'previously_seen') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'difficulty') IS DISTINCT FROM 'number'
            OR (obs->>'difficulty') NOT IN ('1','2','3')
            OR NOT(obs ?& ARRAY['check_item_id','difficulty','synthetic_idk','previously_seen','node_id',
                'question_hash','channel','correct','idk','assisted','max_rung','same_session_recheck','independent'])
            OR EXISTS(SELECT 1 FROM jsonb_object_keys(obs) k WHERE k NOT IN (
                'check_item_id','difficulty','synthetic_idk','previously_seen','node_id','question_hash',
                'channel','correct','idk','assisted','max_rung','same_session_recheck','independent'))
            OR (obs->>'idk')::boolean AND ev.correct
            OR (obs->>'synthetic_idk')::boolean AND NOT (obs->>'idk')::boolean
            OR ev.assisted IS DISTINCT FROM (ev.max_rung>0)
            OR (obs->>'independent')::boolean IS DISTINCT FROM (NOT (
                ev.max_rung>0 OR ev.assisted OR (obs->>'same_session_recheck')::boolean
                OR (obs->>'synthetic_idk')::boolean OR (obs->>'previously_seen')::boolean))) THEN
            RAISE EXCEPTION 'Invalid final planning provenance';
        END IF;
    END LOOP;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'state_rows') LOOP
        s := jsonb_populate_record(NULL::learner_state,x);
        INSERT INTO learner_state(user_id,node_id,p_known,n_strong_unassisted,streak_unassisted,max_streak_unassisted,
            opps,fsrs_d,fsrs_s,fsrs_last_review_at,fsrs_due_at,last_evidence_at,updated_at,evidence_touch_at)
        VALUES(s.user_id,s.node_id,s.p_known,s.n_strong_unassisted,s.streak_unassisted,s.max_streak_unassisted,
            s.opps,s.fsrs_d,s.fsrs_s,s.fsrs_last_review_at,s.fsrs_due_at,s.last_evidence_at,s.updated_at,s.updated_at)
        ON CONFLICT(user_id,node_id) DO UPDATE SET p_known=EXCLUDED.p_known,n_strong_unassisted=EXCLUDED.n_strong_unassisted,
            streak_unassisted=EXCLUDED.streak_unassisted,max_streak_unassisted=EXCLUDED.max_streak_unassisted,
            opps=EXCLUDED.opps,fsrs_d=EXCLUDED.fsrs_d,fsrs_s=EXCLUDED.fsrs_s,
            fsrs_last_review_at=EXCLUDED.fsrs_last_review_at,fsrs_due_at=EXCLUDED.fsrs_due_at,
            last_evidence_at=EXCLUDED.last_evidence_at,updated_at=EXCLUDED.updated_at,
            evidence_touch_at=greatest(learner_state.evidence_touch_at,EXCLUDED.evidence_touch_at);
    END LOOP;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'mirrors') LOOP
        IF NOT(x->>'id'=ANY(ids)) OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_plan->'state_rows') t WHERE t->>'node_id'=x->>'id')
           OR jsonb_typeof(x->'mastery_score') IS DISTINCT FROM 'number'
           OR NOT((x->>'mastery_score')::double precision BETWEEN 0 AND 1)
           OR EXISTS(SELECT 1 FROM jsonb_object_keys(x) k WHERE k NOT IN ('id','mastery_score','mastery_tier','times_studied','last_studied_at')) THEN
            RAISE EXCEPTION 'Invalid transaction mirror';
        END IF;
        UPDATE graph_nodes SET mastery_score=(x->>'mastery_score')::double precision,mastery_tier=x->>'mastery_tier',
            times_studied=CASE WHEN x ? 'times_studied' THEN (x->>'times_studied')::int ELSE times_studied END,
            last_studied_at=CASE WHEN x ? 'last_studied_at' THEN (x->>'last_studied_at')::timestamptz ELSE last_studied_at END
            WHERE id=x->>'id' AND user_id=p_user_id;
    END LOOP;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'events') LOOP
        ev := jsonb_populate_record(NULL::node_mastery_events,x);
        INSERT INTO node_mastery_events(id,node_id,delta,reason,created_at,event_type,channel,correct,weight,assisted,max_rung,
            p_before,p_after,session_id,check_item_id,question_hash,confidence,grader_backend,evidence_seq,planning_observation,
            retention,same_session_recheck,propagated_to,
            multi_concept,
            student_confidence)
        VALUES(ev.id,ev.node_id,ev.delta,ev.reason,ev.created_at,ev.event_type,ev.channel,ev.correct,ev.weight,ev.assisted,ev.max_rung,
            ev.p_before,ev.p_after,ev.session_id,ev.check_item_id,ev.question_hash,ev.confidence,ev.grader_backend,ev.evidence_seq,ev.planning_observation,
            ev.retention,ev.same_session_recheck,ev.propagated_to,
            ev.multi_concept,
            ev.student_confidence);
    END LOOP;
    INSERT INTO learning_evidence_operations(operation_id,user_id,course_id,input_fingerprint,plan,changes)
        VALUES(p_operation_id,p_user_id,p_course_id,p_input_fingerprint,p_plan,p_plan->'changes');
    RETURN learning_evidence_receipt(p_user_id,p_operation_id);
END $$;

REVOKE ALL ON FUNCTION learning_evidence_commit(text,text,uuid,text,jsonb) FROM PUBLIC;
DO $$ DECLARE r text; BEGIN
    FOREACH r IN ARRAY ARRAY['anon','authenticated'] LOOP
        IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=r) THEN
            EXECUTE format('REVOKE ALL ON FUNCTION learning_evidence_commit(text,text,uuid,text,jsonb) FROM %I',r);
        END IF;
    END LOOP;
    IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN
        GRANT EXECUTE ON FUNCTION learning_evidence_commit(text,text,uuid,text,jsonb) TO service_role;
    END IF;
END $$;

-- PostgREST resolves functions and columns from its schema cache; the local
-- stack does not reliably reload on DDL (docs/local-supabase.md). NOTIFY is
-- delivered at COMMIT and is a no-op with no listener.
NOTIFY pgrst, 'reload schema';

-- @@ unit 20261108224511_learning_varied_practice_validate.sql
-- 20261108224511_learning_varied_practice_validate.sql
-- Learning loop spec §13 A141: validate the closed multi-concept shape CHECK
-- that 20261108205812_learning_varied_practice_review.sql adds NOT VALID.
--
-- VALIDATE CONSTRAINT scans check_items under SHARE UPDATE EXCLUSIVE, which
-- blocks no read or write (only other schema changes and VACUUM), in its own
-- transaction: the review migration's ACCESS EXCLUSIVE locks are released by
-- then. Every stored row passes the constraint (the code writes nothing
-- else); a row that did not would fail this file, and nothing would be
-- recorded. lock_timeout 5s: a lock that does not come within 5s fails the
-- file (rolled back; run it again).
--
-- Deploy order: right after 20261108205812, in the same run, before the code
-- (the rollout entry in docs/operations/learning-engineering-readiness.md).
-- Until it runs, new and updated rows are checked already.

SET LOCAL lock_timeout = '5s';

ALTER TABLE public.check_items VALIDATE CONSTRAINT check_items_multi_concept_shape;

-- @@ unit 20261109032302_learning_loop_rls.sql
-- 20261109032302_learning_loop_rls.sql
-- Learning loop spec §13 A148: every table the learning loop's migrations
-- create holds main's backend-only posture (RLS step 2, #115, bucket E).
--
-- Why
-- ---
-- Main's lockdown (20261108082151_rls_on_every_table.sql) enables RLS on every
-- public table and revokes anon/authenticated, and step 2a
-- (20261108092633_rls_app_auth_helpers.sql) revokes function EXECUTE from
-- PUBLIC/anon/authenticated. Both loop over what exists WHEN THEY RUN. On a
-- fresh database the files run in name order, so the loop's tables created
-- before 20261108082151 are covered and the rest rely on the default
-- privileges those two set. Production meets the other order: main's RLS
-- migrations ran first, and the loop's migrations (all pending there) run
-- after them. learner_state and check_items never enabled RLS in their own
-- migrations, so there they would stay open to any role that held a grant.
-- This migration states the posture explicitly, last in both orders, so the
-- end state does not depend on which ran first.
--
-- What it does, for the 19 loop tables (every CREATE TABLE in the loop's
-- *_learning_* and checklist_budget migrations):
--   1. ENABLE ROW LEVEL SECURITY. No policy is added and any found is a
--      failure: bucket E is service-only, a role without BYPASSRLS sees no row.
--   2. REVOKE ALL from PUBLIC, anon and authenticated (tables and their
--      sequences). The 20261108094130 step-2c grant list is unchanged:
--      authenticated holds nothing on any loop table.
--   3. service_role: ALL, as main grants every backend-only table, EXCEPT the
--      four records the loop deliberately narrowed (A123, A138, A139): the
--      append-only learning_evidence_voids, misconception_attempts and
--      learning_prequestions keep SELECT + INSERT, learning_self_explanations
--      SELECT + INSERT + UPDATE (the reply closes the row). Restated here
--      (REVOKE ALL first, as 20261108115157 does) so neither order of apply
--      can leave service_role holding UPDATE or DELETE on an append-only
--      record. tests/integration/test_rls_lockdown_db.py pins this exception
--      list exactly; every other public table still needs full access.
--   4. Every function the loop's migrations create (all overloads, by name):
--      no EXECUTE for PUBLIC, anon or authenticated; EXECUTE for service_role.
--      Trigger functions included, as step 2a does (a trigger needs no EXECUTE
--      to fire).
--   5. `authenticated` gets A136's `extra_float_digits = 3`. A136
--      (20261108162223_learning_exact_floats.sql) set it on service_role
--      because the backend reached PostgREST as service_role only, and its
--      own rule says any other role PostgREST runs the backend as needs the
--      same. Main's `db_user_scope` flag (RLS step 2, shadow/enforce) now runs
--      a request's reads as `authenticated` (a backend-minted JWT): without
--      this, a user-scoped read of a float column would come back rounded to
--      15 significant digits (real: 6), which A136 showed can flip a decision
--      (a documents.shareability_confidence just under the share floor read
--      as the floor). anon and authenticator keep the server default.
--
-- Why it is inert for the backend: it reaches PostgREST as service_role
-- (BYPASSRLS), which keeps exactly the privileges the loop already used; the
-- migration runner, oracles and integration lane connect as `postgres`, the
-- owner. Under the `db_user_scope` flag the loop's reads and writes of these
-- tables run as service (the loop router is a service route, and every loop
-- store reached from a user-scoped route is @runs_as_service).
--
-- Guarded like main's role-touching migrations: role statements are skipped on
-- a bare Postgres without the Supabase roles. Idempotent: every statement is
-- safe to re-run. A missing table fails the migration (rolled back), which is
-- the right outcome for schema drift. No data is touched.
--
-- Reverse (by hand, as the migration role): nothing to restore — before this
-- ran the same tables were either already in this state (fresh databases) or
-- open by omission (learner_state, check_items in production order), which is
-- not a state worth restoring. To drop the explicit service_role narrowing,
-- re-run the GRANTs of 20261108115157 / 20261108184825 as they stand.

DO $$
DECLARE
    t        TEXT;
    r        TEXT;
    s        TEXT;
    fn       TEXT;
    n        INTEGER;
    tables   CONSTANT TEXT[] := ARRAY[
        'learner_state',
        'check_items',
        'check_item_draft_failures',
        'ai_tutor_daily_calls',
        'misconceptions',
        'posttest_poses',
        'learning_reveals',
        'quiz_evidence_claims',
        'checklist_budget_accounts',
        'checklist_budget_reservations',
        'learning_evidence_operations',
        'check_item_reports',
        'check_item_reviews',
        'learning_evidence_voids',
        'misconception_attempts',
        'check_item_audits',
        'posttest_skips',
        'learning_prequestions',
        'learning_self_explanations'
    ];
    functions CONSTANT TEXT[] := ARRAY[
        'ai_budget_bump_tutor_calls',
        'check_item_hold_flags',
        'check_item_report',
        'check_item_report_quarantine',
        'check_item_review_decide',
        'check_items_staff_hold',
        'checklist_budget_admit',
        'checklist_budget_read',
        'checklist_budget_reconcile',
        'checklist_budget_start',
        'learning_bump_evidence_version',
        'learning_evidence_commit',
        'learning_evidence_receipt',
        'learning_evidence_snapshot',
        'learning_evidence_void_commit',
        'learning_evidence_void_pending',
        'learning_evidence_void_snapshot',
        'learning_evidence_voids_append_only',
        'learning_float_probe',
        'misconception_record',
        'misconception_rollup',
        'posttest_anchors'
    ];
    has_service CONSTANT BOOLEAN := EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role');
BEGIN
    -- 1-3: tables
    FOREACH t IN ARRAY tables LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);

        SELECT count(*) INTO n FROM pg_policies WHERE schemaname = 'public' AND tablename = t;
        IF n > 0 THEN
            RAISE EXCEPTION 'learning loop table % has % RLS polic(ies); it is service-only', t, n;
        END IF;

        EXECUTE format('REVOKE ALL ON TABLE public.%I FROM PUBLIC', t);
        FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                EXECUTE format('REVOKE ALL ON TABLE public.%I FROM %I', t, r);
            END IF;
        END LOOP;

        IF has_service THEN
            IF t IN ('learning_evidence_voids', 'misconception_attempts', 'learning_prequestions') THEN
                EXECUTE format('REVOKE ALL ON TABLE public.%I FROM service_role', t);
                EXECUTE format('GRANT SELECT, INSERT ON TABLE public.%I TO service_role', t);
            ELSIF t = 'learning_self_explanations' THEN
                EXECUTE format('REVOKE ALL ON TABLE public.%I FROM service_role', t);
                EXECUTE format('GRANT SELECT, INSERT, UPDATE ON TABLE public.%I TO service_role', t);
            ELSE
                EXECUTE format('GRANT ALL ON TABLE public.%I TO service_role', t);
            END IF;
        END IF;

        -- the table's own sequences (an identity or serial column)
        FOR s IN
            SELECT seq.relname
              FROM pg_depend d
              JOIN pg_class seq ON seq.oid = d.objid AND seq.relkind = 'S'
             WHERE d.refobjid = format('public.%I', t)::regclass
               AND d.deptype IN ('a', 'i')
        LOOP
            FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                    EXECUTE format('REVOKE ALL ON SEQUENCE public.%I FROM %I', s, r);
                END IF;
            END LOOP;
            IF has_service THEN
                EXECUTE format('GRANT ALL ON SEQUENCE public.%I TO service_role', s);
            END IF;
        END LOOP;
    END LOOP;

    -- 4: functions (every overload; extension members never match these names)
    FOR fn IN
        SELECT p.oid::regprocedure::text
          FROM pg_proc p
         WHERE p.pronamespace = 'public'::regnamespace
           AND p.proname = ANY (functions)
         ORDER BY 1
    LOOP
        EXECUTE format('REVOKE EXECUTE ON ROUTINE %s FROM PUBLIC', fn);
        FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                EXECUTE format('REVOKE EXECUTE ON ROUTINE %s FROM %I', fn, r);
            END IF;
        END LOOP;
        IF has_service THEN
            EXECUTE format('GRANT EXECUTE ON ROUTINE %s TO service_role', fn);
        END IF;
    END LOOP;
END $$;

-- 5: the role a user-scoped request runs as reads floats exactly (A136).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        ALTER ROLE authenticated SET extra_float_digits = 3;
    END IF;
END $$;

-- PostgREST caches table privileges in its schema cache and applies role
-- settings from its config cache; reload both (no-ops with no listener).
NOTIFY pgrst, 'reload schema';
NOTIFY pgrst, 'reload config';

-- @@ unit 20261111030007_tutor_pending_loop_state.sql
-- Stateless per-replica state, part 3 (Trov #117): learning-loop sessions in
-- the replica-safe pending store, behind the same `stateless_tutor_sessions`
-- flag as 20261109024225_tutor_pending_sessions.sql.
--
-- Why
-- ---
-- A learning-loop session is lazy like a tutor session: start-session serves
-- the opener and records the session as pending; the first loop write
-- materialises the `sessions` row. A loop session's pending record carries
-- one thing a tutor session's does not: the loop document it starts with
-- (`sessions.loop_state` once materialised) — a quiz-ask session's teach
-- phase on the quiz's concept (spec §13 A99), a confirmed goal (ADR 0033),
-- the open-question key and the retrieval-failure note (A121, A128). Until
-- now the loop kept that record in ONE process (PENDING_SESSIONS) whatever
-- the flag said, so with two replicas a loop session started on one 404'd on
-- the other, or materialised there without its document.
--
-- What this changes
-- -----------------
-- tutor_pending_sessions.loop_state JSONB (NULL for a tutor session): the
--   pending loop document, in the format `sessions.loop_state` stores (ids,
--   flags and counters in plaintext; the goal text inside is already
--   encrypted by learning/goals.py::encode_goal). Must be a JSON object.
--   Cleared on discard, like every other payload column.
-- stash_tutor_session(..., p_loop_state JSONB DEFAULT NULL): the old
--   12-argument signature is replaced by one with a 13th, defaulted argument,
--   so a backend that does not send it (the previous release) still resolves
--   to it by name and stores NULL, exactly as before. Dropped and recreated
--   rather than overloaded: two candidates would make PostgREST's call by
--   named arguments ambiguous.
-- materialize_tutor_session (same signature and result): the `sessions` row
--   it writes takes the pending loop document (`sessions.loop_state` is NOT
--   NULL DEFAULT '{}', so a tutor session still gets '{}').
-- discard_tutor_session (same signature and result): a tombstone also clears
--   loop_state.
--
-- Additive and idempotent (ADD COLUMN IF NOT EXISTS, a guarded constraint,
-- DROP IF EXISTS + CREATE OR REPLACE). Inert until the flag is on: nothing
-- reads or writes the store with it off.
--
-- Reverse (by hand, as the migration role; turn the flag off first):
--   DROP FUNCTION IF EXISTS public.stash_tutor_session(text, text, text, text, text, text, boolean, text, jsonb, integer, integer, integer, jsonb);
--   then re-run the stash/materialize/discard definitions of
--   20261109024225_tutor_pending_sessions.sql, and
--   ALTER TABLE public.tutor_pending_sessions DROP COLUMN IF EXISTS loop_state;
-- (Only the documents of loop sessions nobody has answered in yet are lost.)

ALTER TABLE public.tutor_pending_sessions
    ADD COLUMN IF NOT EXISTS loop_state JSONB;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'tutor_pending_sessions_loop_state_shape_check'
           AND conrelid = 'public.tutor_pending_sessions'::regclass
    ) THEN
        ALTER TABLE public.tutor_pending_sessions
            ADD CONSTRAINT tutor_pending_sessions_loop_state_shape_check
            CHECK (loop_state IS NULL OR jsonb_typeof(loop_state) = 'object');
    END IF;
END $$;

COMMENT ON COLUMN public.tutor_pending_sessions.loop_state IS
    'A pending learning-loop session''s starting loop document (sessions.loop_state format); NULL for a tutor session.';

-- ── stash_tutor_session ─────────────────────────────────────────────────────

DROP FUNCTION IF EXISTS public.stash_tutor_session(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, BOOLEAN, TEXT, JSONB, INTEGER, INTEGER, INTEGER);

CREATE OR REPLACE FUNCTION public.stash_tutor_session(
    p_session_id             TEXT,
    p_user_id                TEXT,
    p_mode                   TEXT,
    p_topic                  TEXT,
    p_course_id              TEXT,
    p_offering_id            TEXT,
    p_use_shared_context     BOOLEAN,
    p_assistant_reply        TEXT,
    p_graph_update           JSONB,
    p_ttl_seconds            INTEGER,
    p_tombstone_ttl_seconds  INTEGER,
    p_max_entries            INTEGER,
    p_loop_state             JSONB DEFAULT NULL
)
RETURNS BOOLEAN
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path = ''
AS $$
DECLARE
    v_now TIMESTAMPTZ := clock_timestamp();
    v_max INTEGER := GREATEST(COALESCE(p_max_entries, 2000), 1);
BEGIN
    -- Expired pending sessions and tombstones go first.
    DELETE FROM public.tutor_pending_sessions t
     WHERE (t.state = 'pending'
            AND t.stashed_at < v_now - pg_catalog.make_interval(secs => p_ttl_seconds))
        OR (t.state <> 'pending'
            AND t.discarded_at < v_now - pg_catalog.make_interval(secs => p_tombstone_ttl_seconds));

    -- Then the oldest pending sessions, so this one fits under the cap.
    DELETE FROM public.tutor_pending_sessions t
     WHERE t.session_id IN (
         SELECT o.session_id
           FROM public.tutor_pending_sessions o
          WHERE o.state = 'pending'
          ORDER BY o.stashed_at DESC
         OFFSET v_max - 1);

    INSERT INTO public.tutor_pending_sessions (
        session_id, user_id, state, mode, topic, course_id, offering_id,
        use_shared_context, assistant_reply, graph_update, loop_state, stashed_at)
    VALUES (
        p_session_id, p_user_id, 'pending', p_mode, p_topic, p_course_id, p_offering_id,
        COALESCE(p_use_shared_context, TRUE), p_assistant_reply, p_graph_update,
        p_loop_state, v_now);
    RETURN TRUE;  -- a body PostgREST answers with (a void function answers 204, no JSON)
END;
$$;

COMMENT ON FUNCTION public.stash_tutor_session(TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, BOOLEAN, TEXT, JSONB, INTEGER, INTEGER, INTEGER, JSONB) IS
    'start-session (#117): record a pending tutor or learning-loop session (with its loop document), after the TTL sweep and the oldest-first eviction.';

-- ── materialize_tutor_session ───────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.materialize_tutor_session(
    p_session_id            TEXT,
    p_user_id               TEXT,
    p_ttl_seconds           INTEGER,
    p_tombstone_ttl_seconds INTEGER,
    p_created_at            TIMESTAMPTZ
)
RETURNS TABLE (outcome TEXT, session_mode TEXT, session_topic TEXT, session_offering_id TEXT)
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path = ''
AS $$
DECLARE
    v_now TIMESTAMPTZ := clock_timestamp();
    r     public.tutor_pending_sessions%ROWTYPE;
BEGIN
    SELECT * INTO r
      FROM public.tutor_pending_sessions t
     WHERE t.session_id = p_session_id
       FOR UPDATE;

    IF NOT FOUND THEN
        outcome := 'none';
        RETURN NEXT;
        RETURN;
    END IF;

    IF r.state <> 'pending' THEN
        -- A tombstone answers only its own user, and only within its TTL.
        IF r.user_id = p_user_id
           AND r.discarded_at >= v_now - pg_catalog.make_interval(secs => p_tombstone_ttl_seconds) THEN
            outcome := r.state;
        ELSE
            outcome := 'none';
        END IF;
        RETURN NEXT;
        RETURN;
    END IF;

    IF r.stashed_at < v_now - pg_catalog.make_interval(secs => p_ttl_seconds) THEN
        outcome := 'none';  -- expired: answers like an evicted session
        RETURN NEXT;
        RETURN;
    END IF;

    IF r.user_id <> p_user_id THEN
        outcome := 'foreign';
        RETURN NEXT;
        RETURN;
    END IF;

    -- A learning-loop session keeps the document it started with (a quiz-ask
    -- session's teach phase, a goal); a tutor session gets the column default.
    INSERT INTO public.sessions (id, user_id, mode, topic, offering_id, loop_state)
    VALUES (r.session_id, r.user_id, r.mode, r.topic, NULLIF(r.offering_id, ''),
            COALESCE(r.loop_state, '{}'::jsonb))
    ON CONFLICT (id) DO NOTHING;

    INSERT INTO public.messages (session_id, role, content, graph_update_json, created_at)
    VALUES (r.session_id, 'assistant', r.assistant_reply, r.graph_update,
            COALESCE(p_created_at, v_now));

    DELETE FROM public.tutor_pending_sessions t WHERE t.session_id = p_session_id;

    outcome := 'materialized';
    session_mode := r.mode;
    session_topic := r.topic;
    session_offering_id := r.offering_id;
    RETURN NEXT;
END;
$$;

-- ── discard_tutor_session ───────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.discard_tutor_session(
    p_session_id      TEXT,
    p_user_id         TEXT,
    p_reason          TEXT,
    p_only_if_pending BOOLEAN,
    p_ttl_seconds     INTEGER
)
RETURNS BOOLEAN
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path = ''
AS $$
DECLARE
    v_now     TIMESTAMPTZ := clock_timestamp();
    v_pending BOOLEAN := FALSE;
    r         public.tutor_pending_sessions%ROWTYPE;
BEGIN
    IF p_reason IS NULL OR p_reason NOT IN ('ended', 'deleted') THEN
        RAISE EXCEPTION 'discard_tutor_session: invalid reason'
            USING ERRCODE = '22023';
    END IF;

    SELECT * INTO r
      FROM public.tutor_pending_sessions t
     WHERE t.session_id = p_session_id
       FOR UPDATE;

    IF FOUND THEN
        v_pending := r.state = 'pending'
            AND r.stashed_at >= v_now - pg_catalog.make_interval(secs => p_ttl_seconds);
    END IF;

    IF COALESCE(p_only_if_pending, FALSE) AND NOT v_pending THEN
        RETURN FALSE;
    END IF;

    INSERT INTO public.tutor_pending_sessions AS t (session_id, user_id, state, discarded_at)
    VALUES (p_session_id, p_user_id, p_reason, v_now)
    ON CONFLICT (session_id) DO UPDATE
        SET user_id = EXCLUDED.user_id,
            state = EXCLUDED.state,
            discarded_at = EXCLUDED.discarded_at,
            mode = NULL, topic = NULL, course_id = NULL, offering_id = NULL,
            assistant_reply = NULL, graph_update = NULL, loop_state = NULL;

    RETURN v_pending;
END;
$$;

-- ── access: service_role only, as before ────────────────────────────────────

DO $$
DECLARE
    f TEXT;
    r TEXT;
BEGIN
    FOREACH f IN ARRAY ARRAY[
        'public.stash_tutor_session(text, text, text, text, text, text, boolean, text, jsonb, integer, integer, integer, jsonb)',
        'public.materialize_tutor_session(text, text, integer, integer, timestamptz)',
        'public.discard_tutor_session(text, text, text, boolean, integer)'
    ] LOOP
        EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC', f);
        FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                EXECUTE format('REVOKE ALL ON FUNCTION %s FROM %I', f, r);
            END IF;
        END LOOP;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
            EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO service_role', f);
        END IF;
    END LOOP;
END $$;

-- @@ unit 20261111030019_learning_account_erase.sql
-- 20261111030019_learning_account_erase.sql
-- The admin account wipe (services/account_wipe.py::wipe_account_data) erases
-- a student's learning-loop rows. Owner decision: every row the student owns
-- in every learning-loop table goes; the users row stays, so the loop tables'
-- `REFERENCES users(id) ON DELETE CASCADE` never fires for a wipe.
--
-- The wipe reaches PostgREST as service_role. That role holds DELETE on every
-- student-keyed loop table except the two teach-prompt records, which
-- 20261108184825_learning_teach_prompts.sql and 20261109032302_learning_loop_rls.sql
-- narrowed on purpose: learning_prequestions is SELECT + INSERT,
-- learning_self_explanations SELECT + INSERT + UPDATE. No request path may
-- delete from either, and that stays true. This function is the one sanctioned
-- erase of them: it deletes exactly one student's rows from those two tables
-- and nothing else, and returns how many it deleted.
--
-- SECURITY DEFINER, so it runs as its owner (the migration role, which owns
-- both tables and so is not subject to their RLS), with search_path pinned.
-- EXECUTE: service_role only (the 20261109032302 posture for every loop
-- function); PUBLIC, anon and authenticated hold nothing, so it is never
-- reachable through /rest/v1/rpc with a user's token.
--
-- learning_evidence_voids and misconception_attempts (SELECT + INSERT only as
-- well) need no function: their rows go by their ON DELETE CASCADE, from
-- node_mastery_events (itself cascaded from graph_nodes) and misconceptions,
-- both of which the wipe deletes. A cascade runs as the table owner.
--
-- Idempotent (CREATE OR REPLACE; the grants are re-stated). No data is touched
-- by applying it. Reverse: DROP FUNCTION learning_account_erase(text).

CREATE OR REPLACE FUNCTION learning_account_erase(p_user_id text)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    n_self_explanations bigint;
    n_prequestions bigint;
BEGIN
    IF p_user_id IS NULL OR btrim(p_user_id) = '' THEN
        RAISE EXCEPTION 'learning_account_erase needs a user id';
    END IF;
    DELETE FROM learning_self_explanations WHERE user_id = p_user_id;
    GET DIAGNOSTICS n_self_explanations = ROW_COUNT;
    DELETE FROM learning_prequestions WHERE user_id = p_user_id;
    GET DIAGNOSTICS n_prequestions = ROW_COUNT;
    RETURN jsonb_build_object(
        'learning_self_explanations', n_self_explanations,
        'learning_prequestions', n_prequestions
    );
END
$$;

REVOKE ALL ON FUNCTION learning_account_erase(text) FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON FUNCTION learning_account_erase(text) FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT EXECUTE ON FUNCTION learning_account_erase(text) TO service_role;
    END IF;
END $$;

-- PostgREST resolves functions from its schema cache; reload it (a no-op with
-- no listener).
NOTIFY pgrst, 'reload schema';

-- @@ unit 20261118052843_claim_tutor_session.sql
-- The learning loop's close of a never-answered session (#117 stateless_tutor_sessions;
-- services/tutor_sessions.py::claim_pending).
--
-- One locked statement: for the CALLER'S OWN live pending row, return its payload
-- (the row as it was) and turn it into an 'ended' tombstone, the payload cleared
-- exactly as discard_tutor_session clears it. Before this, the close either
-- deleted the row (DELETE ... RETURNING: no tombstone, so a first turn racing the
-- close found neither a pending row nor a tombstone) or read the payload and then
-- discarded in a second call (a rename between the two was lost, and the payload
-- snapshot was not the row it tombstoned). Another student's row, an expired one,
-- or a tombstone returns no row and changes nothing.

CREATE OR REPLACE FUNCTION public.claim_tutor_session(
    p_session_id  TEXT,
    p_user_id     TEXT,
    p_ttl_seconds INTEGER
)
RETURNS SETOF public.tutor_pending_sessions
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path = ''
AS $$
DECLARE
    v_now TIMESTAMPTZ := clock_timestamp();
    r     public.tutor_pending_sessions%ROWTYPE;
BEGIN
    SELECT * INTO r
      FROM public.tutor_pending_sessions t
     WHERE t.session_id = p_session_id
       FOR UPDATE;

    IF NOT FOUND
       OR r.user_id IS DISTINCT FROM p_user_id
       OR r.state <> 'pending'
       OR r.stashed_at < v_now - pg_catalog.make_interval(secs => p_ttl_seconds) THEN
        RETURN;
    END IF;

    UPDATE public.tutor_pending_sessions t
       SET state = 'ended',
           discarded_at = v_now,
           mode = NULL, topic = NULL, course_id = NULL, offering_id = NULL,
           assistant_reply = NULL, graph_update = NULL, loop_state = NULL
     WHERE t.session_id = p_session_id;

    RETURN NEXT r;
END;
$$;

-- ── access: service_role only, like the table's other functions ─────────────

DO $$
DECLARE
    f TEXT := 'public.claim_tutor_session(text, text, integer)';
    r TEXT;
BEGIN
    EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC', f);
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON FUNCTION %s FROM %I', f, r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO service_role', f);
    END IF;
END $$;

NOTIFY pgrst, 'reload schema';

-- @@ unit 20261118194745_checklist_budget_any_model.sql
-- The checklist budget priced one model only. 20261019125459 fixed every hold
-- at gemini-2.5-flash's worst case (.0764400000 USD, 74576 tokens) and
-- settlement re-priced each bill at flash's rates and refused any other
-- model or provider. The topic_checklist slot defaults to claude-haiku-5-5
-- (agents/_providers.py, ADR 0030), with gemini-2.5-flash as its llm_fallback,
-- so every real-mode refresh was refused (PR #866 review B1).
--
-- Now the backend prices the hold from services/llm_pricing for the models
-- that can serve the run (the slot's model and its fallback,
-- services/checklist_budget.py::price_hold) and admission stores the hold with
-- those models as `provider:model` labels. Settlement accepts a bill from one
-- of the reservation's own models only, priced by the backend: a bill over its
-- hold still blocks the account for reconciliation, as before.
--
-- 20261019125459 and 20261108033310 are applied and stay as they are. Here:
--   * checklist_budget_reservations: held_usd/held_tokens lose their fixed
--     CHECKs and defaults (any positive hold, stated at admission); a new
--     NOT NULL `models`, filled for existing rows with the one model every one
--     of them was admitted and priced for.
--   * checklist_budget_accounts.policy: the policy is 'checklist-50k-3x8192-v2'.
--   * checklist_budget_admit: a new signature (+ p_held_usd, p_held_tokens,
--     p_models), the one the backend calls (PostgREST picks an overload by its
--     argument names). The 9-argument function stays as it is (the learning
--     release verifier inventories every declared signature) but can no longer
--     admit anything: its INSERT names no hold or models, which now have no
--     default, so a worker still on the old code fails and rolls back instead
--     of holding the old fixed amount.
--   * checklist_budget_reconcile: the same signature; no fixed model, provider
--     or price.
-- checklist_budget_start and checklist_budget_read are unchanged: start sums
-- the stored holds, whatever they are.

DO $$ DECLARE c record; BEGIN
    FOR c IN
        SELECT conrelid::regclass AS tbl, conname FROM pg_constraint
        WHERE contype = 'c' AND (
            (conrelid = 'checklist_budget_reservations'::regclass
             AND (pg_get_constraintdef(oid) LIKE '%held_usd%' OR pg_get_constraintdef(oid) LIKE '%held_tokens%'))
            OR (conrelid = 'checklist_budget_accounts'::regclass AND pg_get_constraintdef(oid) LIKE '%policy%'))
    LOOP
        EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I', c.tbl, c.conname);
    END LOOP;
END $$;

ALTER TABLE checklist_budget_reservations
    ALTER COLUMN held_usd DROP DEFAULT,
    ALTER COLUMN held_tokens DROP DEFAULT,
    ADD COLUMN IF NOT EXISTS models text[];
UPDATE checklist_budget_reservations SET models = ARRAY['gemini:gemini-2.5-flash'] WHERE models IS NULL;
ALTER TABLE checklist_budget_reservations
    ALTER COLUMN models SET NOT NULL,
    ADD CONSTRAINT checklist_budget_reservations_hold_check CHECK (held_usd > 0 AND held_tokens > 0),
    ADD CONSTRAINT checklist_budget_reservations_models_check
        CHECK (cardinality(models) > 0 AND array_position(models, NULL) IS NULL);

UPDATE checklist_budget_accounts SET policy = 'checklist-50k-3x8192-v2';
ALTER TABLE checklist_budget_accounts
    ALTER COLUMN policy SET DEFAULT 'checklist-50k-3x8192-v2',
    ADD CONSTRAINT checklist_budget_accounts_policy_check CHECK (policy = 'checklist-50k-3x8192-v2');

-- 20261108033310's body, with the hold and its models taken from the caller.
CREATE OR REPLACE FUNCTION checklist_budget_admit(
    p_user_id text, p_enrollment_id text, p_input_hash text,
    p_operation_id uuid, p_receipt_id text, p_policy text,
    p_daily_usd numeric, p_monthly_usd numeric, p_daily_tokens bigint,
    p_held_usd numeric, p_held_tokens bigint, p_models text[]
) RETURNS jsonb LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
DECLARE
    a checklist_budget_accounts%ROWTYPE;
    r checklist_budget_reservations%ROWTYPE;
    t timestamptz;
    d timestamptz;
    m timestamptz;
    day_spend numeric; month_spend numeric; tokens bigint;
    day_holds numeric; month_holds numeric; token_holds bigint;
BEGIN
    IF p_user_id IS NULL OR length(p_user_id) NOT BETWEEN 1 AND 255
       OR p_input_hash !~ '^[0-9a-f]{64}$' OR p_operation_id IS NULL
       OR p_receipt_id IS NULL OR p_policy IS DISTINCT FROM 'checklist-50k-3x8192-v2'
       OR p_input_hash IS NULL OR p_daily_usd IS NULL OR p_daily_usd <= 0
       OR p_monthly_usd IS NULL OR p_monthly_usd <= 0 OR p_daily_tokens IS NULL OR p_daily_tokens <= 0
       OR p_daily_usd::text IN ('NaN','Infinity','-Infinity') OR p_monthly_usd::text IN ('NaN','Infinity','-Infinity')
       OR p_held_usd IS NULL OR p_held_usd::text IN ('NaN','Infinity','-Infinity') OR p_held_usd <= 0
       OR round(p_held_usd, 10) <> p_held_usd OR p_held_tokens IS NULL OR p_held_tokens <= 0
       OR p_models IS NULL OR cardinality(p_models) = 0 OR array_position(p_models, NULL) IS NOT NULL
       OR EXISTS (SELECT 1 FROM unnest(p_models) AS label WHERE label !~ '^[a-z]+:[A-Za-z0-9._-]+$') THEN
        RAISE EXCEPTION 'Invalid checklist admission identity/policy';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM enrollments e JOIN course_offerings o ON o.id=e.offering_id
                   JOIN courses c ON c.id=o.course_id
                   WHERE e.id=p_enrollment_id AND e.user_id=p_user_id) THEN
        RETURN jsonb_build_object('status','ownership');
    END IF;
    INSERT INTO checklist_budget_accounts(user_id) VALUES(p_user_id) ON CONFLICT DO NOTHING;
    SELECT * INTO a FROM checklist_budget_accounts WHERE user_id=p_user_id FOR UPDATE;
    t := clock_timestamp();
    -- Workers may only tighten stored policy. A stale/looser worker cannot
    -- undo a lower cap; changing it upward requires an explicit DB policy edit.
    UPDATE checklist_budget_accounts SET daily_usd=least(daily_usd,p_daily_usd),
        monthly_usd=least(monthly_usd,p_monthly_usd),daily_tokens=least(daily_tokens,p_daily_tokens)
        WHERE user_id=p_user_id RETURNING * INTO a;
    -- Prepared leases may be released: start is a fenced compare-and-swap under
    -- this same mutex, so an expired prepared operation can never dispatch later.
    UPDATE checklist_budget_reservations SET state='released', reason='prepared_expired'
        WHERE user_id=p_user_id AND state='prepared' AND expires_at <= t;
    -- A started timeout is exposure, never a refund. It ceases to own the cache
    -- claim so a deliberate later refresh may reserve additional capacity.
    UPDATE checklist_budget_reservations SET state='unknown', reason='dispatch_outcome_unknown'
        WHERE user_id=p_user_id AND state='started' AND expires_at <= t;
    SELECT * INTO r FROM checklist_budget_reservations WHERE operation_id=p_operation_id;
    IF FOUND THEN
        IF r.user_id IS DISTINCT FROM p_user_id OR r.enrollment_id IS DISTINCT FROM p_enrollment_id
           OR r.input_hash IS DISTINCT FROM p_input_hash OR r.receipt_id IS DISTINCT FROM p_receipt_id
           OR r.held_usd IS DISTINCT FROM p_held_usd OR r.held_tokens IS DISTINCT FROM p_held_tokens
           OR r.models IS DISTINCT FROM p_models THEN
            RETURN jsonb_build_object('status','conflict');
        END IF;
        RETURN jsonb_build_object('status','replay','reservation',to_jsonb(r));
    END IF;
    IF EXISTS (SELECT 1 FROM topic_checklists WHERE enrollment_id=p_enrollment_id AND input_hash=p_input_hash) THEN
        RETURN jsonb_build_object('status','cached');
    END IF;
    SELECT * INTO r FROM checklist_budget_reservations
        WHERE enrollment_id=p_enrollment_id AND state IN ('prepared','started');
    IF FOUND THEN RETURN jsonb_build_object('status','busy','reservation',to_jsonb(r)); END IF;
    IF a.blocked THEN RETURN jsonb_build_object('status','blocked'); END IF;
    d := date_trunc('day', t AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';
    m := date_trunc('month', t AT TIME ZONE 'UTC') AT TIME ZONE 'UTC';
    -- Unknown legacy prices/negative or malformed counters cannot establish
    -- remaining headroom. No coalesce(NULL cost,0) financial fallback.
    IF EXISTS (SELECT 1 FROM llm_usage WHERE user_id=p_user_id AND created_at >= m
               AND (cost_usd IS NULL OR cost_usd < 0 OR cost_usd::text IN ('NaN','Infinity','-Infinity')
                    OR total_tokens IS NULL OR total_tokens < 0)) THEN
        RETURN jsonb_build_object('status','usage_unavailable');
    END IF;
    SELECT coalesce(sum(cost_usd) FILTER (WHERE created_at >= d),0), coalesce(sum(cost_usd),0),
           coalesce(sum(total_tokens) FILTER (WHERE created_at >= d AND
              coalesce(task,'') NOT IN ('decision_shadow','decision_jev_extra')),0)
        INTO day_spend, month_spend, tokens FROM llm_usage WHERE user_id=p_user_id AND created_at >= m;
    SELECT coalesce(sum(held_usd) FILTER (WHERE coalesce(dispatch_at,created_at) >= d),0),
           coalesce(sum(held_usd) FILTER (WHERE coalesce(dispatch_at,created_at) >= m),0),
           coalesce(sum(held_tokens) FILTER (WHERE coalesce(dispatch_at,created_at) >= d),0)
        INTO day_holds,month_holds,token_holds FROM checklist_budget_reservations
        WHERE user_id=p_user_id AND state IN ('prepared','started','unknown');
    IF day_spend + day_holds + p_held_usd > a.daily_usd
       OR month_spend + month_holds + p_held_usd > a.monthly_usd
       OR tokens + token_holds + p_held_tokens > a.daily_tokens THEN
        RETURN jsonb_build_object('status','denied','retry_at', CASE
            WHEN month_spend + month_holds + p_held_usd > a.monthly_usd THEN m + interval '1 month'
            ELSE d + interval '1 day' END);
    END IF;
    UPDATE checklist_budget_accounts SET next_fence=next_fence+1 WHERE user_id=p_user_id RETURNING * INTO a;
    INSERT INTO checklist_budget_reservations(operation_id,user_id,enrollment_id,input_hash,fence,state,
        created_at,expires_at,receipt_id,held_usd,held_tokens,models) VALUES(p_operation_id,p_user_id,
        p_enrollment_id,p_input_hash,a.next_fence,'prepared',t,t + interval '2 minutes',p_receipt_id,
        p_held_usd,p_held_tokens,p_models) RETURNING * INTO r;
    RETURN jsonb_build_object('status','admitted','reservation',to_jsonb(r));
END $$;

-- 20261108033310's body; the settle check names no model, provider or price.
CREATE OR REPLACE FUNCTION checklist_budget_reconcile(
    p_user_id text,p_operation_id uuid,p_fence bigint,p_action text,
    p_receipt jsonb DEFAULT NULL,p_fingerprint text DEFAULT NULL,p_content text DEFAULT NULL
) RETURNS jsonb LANGUAGE plpgsql SET search_path = public, pg_temp AS $$
DECLARE
    r checklist_budget_reservations%ROWTYPE;
    bill llm_usage%ROWTYPE;
    published boolean := false;
BEGIN
    PERFORM 1 FROM checklist_budget_accounts WHERE user_id=p_user_id FOR UPDATE;
    SELECT * INTO r FROM checklist_budget_reservations WHERE operation_id=p_operation_id AND user_id=p_user_id;
    IF NOT FOUND OR r.fence IS DISTINCT FROM p_fence THEN RETURN jsonb_build_object('status','conflict'); END IF;
    IF p_action='settle' THEN
        IF r.state='settled' THEN
            IF r.receipt IS DISTINCT FROM p_receipt OR r.fingerprint IS DISTINCT FROM p_fingerprint THEN
                RETURN jsonb_build_object('status','conflict');
            END IF;
            RETURN jsonb_build_object('status','settled','reservation',to_jsonb(r));
        END IF;
        IF r.state NOT IN ('started','unknown') OR p_receipt IS NULL
           OR p_fingerprint IS NULL OR p_fingerprint !~ '^[0-9a-f]{64}$' THEN RETURN jsonb_build_object('status','conflict'); END IF;
        bill := jsonb_populate_record(NULL::llm_usage,p_receipt);
        -- The bill comes from one of the models this hold was priced for, and
        -- the backend priced it (services/llm_pricing): positive and finite.
        IF bill.id IS DISTINCT FROM r.receipt_id OR bill.user_id IS DISTINCT FROM p_user_id
           OR bill.feature IS DISTINCT FROM 'topic_checklist' OR bill.task IS DISTINCT FROM 'topic_checklist'
           OR bill.model IS NULL OR bill.provider IS NULL
           OR NOT (bill.provider || ':' || bill.model = ANY(r.models))
           OR bill.created_at IS DISTINCT FROM r.dispatch_at OR bill.session_id IS NOT NULL
           OR bill.prompt_tokens IS NULL OR bill.prompt_tokens <= 0 OR bill.completion_tokens IS NULL OR bill.completion_tokens <= 0
           OR bill.total_tokens IS DISTINCT FROM bill.prompt_tokens+bill.completion_tokens
           OR bill.cached_tokens IS NULL OR bill.cached_tokens < 0 OR bill.cached_tokens > bill.prompt_tokens
           -- NULL: a provider that bills thinking inside its output reports no count
           OR (bill.thinking_tokens IS NOT NULL
               AND (bill.thinking_tokens < 0 OR bill.thinking_tokens > bill.completion_tokens))
           OR bill.cost_usd IS NULL OR bill.cost_usd::text IN ('NaN','Infinity','-Infinity') OR bill.cost_usd <= 0
           OR p_receipt - ARRAY['id','user_id','request_id','feature','task','model','provider','prompt_tokens',
                'completion_tokens','total_tokens','cached_tokens','thinking_tokens','session_id','cost_usd','created_at'] <> '{}'::jsonb
        THEN RETURN jsonb_build_object('status','conflict'); END IF;
        -- Stable id plus exact content verification makes ambiguous insert ACKs
        -- safe to replay; NEVER additionally enqueue this checklist bill.
        INSERT INTO llm_usage(id,user_id,request_id,feature,task,model,provider,prompt_tokens,completion_tokens,
            total_tokens,cached_tokens,thinking_tokens,session_id,cost_usd,created_at)
        VALUES(bill.id,bill.user_id,bill.request_id,bill.feature,bill.task,bill.model,bill.provider,bill.prompt_tokens,
            bill.completion_tokens,bill.total_tokens,bill.cached_tokens,bill.thinking_tokens,bill.session_id,bill.cost_usd,bill.created_at)
        ON CONFLICT(id) DO NOTHING;
        IF NOT EXISTS (SELECT 1 FROM llm_usage u WHERE u.id=bill.id AND u.created_at=bill.created_at AND (to_jsonb(u)-'created_at') @> (p_receipt-'created_at')) THEN
            RAISE EXCEPTION 'Checklist receipt identity already has different content';
        END IF;
        IF bill.cost_usd > r.held_usd OR bill.total_tokens > r.held_tokens THEN
            UPDATE checklist_budget_accounts SET blocked=true WHERE user_id=p_user_id;
        END IF;
        -- A late old result may settle its bill but cannot overwrite a newer
        -- operation's cache, even when that newer operation failed/was released.
        IF p_content IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM checklist_budget_reservations n WHERE n.enrollment_id=r.enrollment_id AND (n.created_at>r.created_at OR (n.user_id=r.user_id AND n.fence>r.fence))
        ) AND EXISTS (SELECT 1 FROM enrollments e JOIN course_offerings o ON o.id=e.offering_id JOIN courses c ON c.id=o.course_id
                      WHERE e.id=r.enrollment_id AND e.user_id=p_user_id FOR SHARE OF e,o,c) THEN
            INSERT INTO topic_checklists(enrollment_id,input_hash,content,generated_at)
                VALUES(r.enrollment_id,r.input_hash,p_content,clock_timestamp())
                ON CONFLICT(enrollment_id) DO UPDATE SET input_hash=excluded.input_hash,content=excluded.content,generated_at=excluded.generated_at;
            published := true;
        END IF;
        UPDATE checklist_budget_reservations SET state='settled',receipt=p_receipt,fingerprint=p_fingerprint,
            cache_published=published,reason=NULL WHERE operation_id=p_operation_id RETURNING * INTO r;
        RETURN jsonb_build_object('status','settled','reservation',to_jsonb(r));
    ELSIF p_action='no_dispatch' AND r.state IN ('prepared','started','unknown') THEN
        -- Trusted backend proof: this process never entered the generation
        -- handler. Counter-only requests are not billed generation. A process
        -- crash cannot provide this proof, so its started hold remains unknown.
        -- p_content here is exclusively the explicit local FunctionModel seam
        -- in the trusted backend; it never creates a paid usage row.
        IF p_content IS NOT NULL AND r.state='prepared' AND NOT EXISTS (
            SELECT 1 FROM checklist_budget_reservations n WHERE n.enrollment_id=r.enrollment_id
            AND (n.created_at>r.created_at OR (n.user_id=r.user_id AND n.fence>r.fence))
        ) AND EXISTS (SELECT 1 FROM enrollments e JOIN course_offerings o ON o.id=e.offering_id JOIN courses c ON c.id=o.course_id
                      WHERE e.id=r.enrollment_id AND e.user_id=p_user_id FOR SHARE OF e,o,c) THEN
            INSERT INTO topic_checklists(enrollment_id,input_hash,content,generated_at)
                VALUES(r.enrollment_id,r.input_hash,p_content,clock_timestamp())
                ON CONFLICT(enrollment_id) DO UPDATE SET input_hash=excluded.input_hash,content=excluded.content,generated_at=excluded.generated_at;
            published := true;
        END IF;
        UPDATE checklist_budget_reservations SET state='released',cache_published=published,reason='no_generation_dispatched'
            WHERE operation_id=p_operation_id RETURNING * INTO r;
    ELSIF p_action='unknown' AND r.state IN ('started','unknown') THEN
        -- Preserve exclusivity until grace expiry; admission changes expired
        -- started -> unknown and retains the entire financial hold.
        UPDATE checklist_budget_reservations SET reason='dispatch_outcome_unknown'
            WHERE operation_id=p_operation_id RETURNING * INTO r;
    ELSIF p_action='no_dispatch' AND r.state='released' THEN NULL;
    ELSE RETURN jsonb_build_object('status','conflict');
    END IF;
    RETURN jsonb_build_object('status',r.state,'reservation',to_jsonb(r));
END $$;

REVOKE ALL ON FUNCTION checklist_budget_admit(text,text,text,uuid,text,text,numeric,numeric,bigint,numeric,bigint,text[]) FROM PUBLIC;
DO $$ DECLARE role_name text; BEGIN
    FOREACH role_name IN ARRAY ARRAY['anon','authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=role_name) THEN
            EXECUTE format('REVOKE ALL ON FUNCTION checklist_budget_admit(text,text,text,uuid,text,text,numeric,numeric,bigint,numeric,bigint,text[]) FROM %I',role_name);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN
        GRANT EXECUTE ON FUNCTION checklist_budget_admit(text,text,text,uuid,text,text,numeric,numeric,bigint,numeric,bigint,text[]) TO service_role;
    END IF;
END $$;
NOTIFY pgrst, 'reload schema';

-- @@ unit 20261118195124_learning_session_node_erase.sql
-- 20261118195124_learning_session_node_erase.sql
-- PR #866 review fixes C8 and C9: the two append-only teach-prompt records
-- (learning_prequestions, learning_self_explanations; spec §13 A138/A139,
-- 20261108184825_learning_teach_prompts.sql) outlived what they belong to.
-- service_role holds no DELETE on either (and no UPDATE on prequestions)
-- since 20261109032302_learning_loop_rls.sql, and that stays true: as in
-- 20261111030019_learning_account_erase.sql, two SECURITY DEFINER functions,
-- EXECUTE for service_role only, are the one sanctioned way to touch them.
--
-- C8 — a deleted tutor session kept the student's own words: the guess they
-- typed at a prequestion (guess_json) and their self-explanation reply
-- (reply_text), both encrypted, keyed by the session. The session delete
-- (services/tutor/sessions.py::delete_session) now clears that TEXT for the
-- session through learning_session_text_erase(user, session). The row stays:
-- an answered prequestion is a release that A76's re-check rule reads for its
-- window across sessions (learning/misconceptions.py::recheck_after_release,
-- through learning/prequestion_store.py::releases: format, difficulty and
-- answered_at only), so deleting it would let a session delete turn a
-- re-check into fresh evidence; a self-explanation row keeps its status and
-- reply length for the admin report. `text_erased_at` records the erase, and
-- each table's text CHECK now allows the cleared state for an erased row only:
--   learning_prequestions:      no_idea = (guess_json IS NULL), or erased with
--                               guess_json NULL;
--   learning_self_explanations: (status = 'replied') = (reply_text IS NOT NULL),
--                               or erased with reply_text NULL.
-- Every other CHECK of both tables is unchanged.
--
-- C9 — a deleted concept node left its teach-prompt rows behind (node_id, no
-- FK). graph_service.delete_node now removes them through
-- learning_node_erase(user, node), with the node's post-test rows
-- (posttest_poses/posttest_skips, which service_role may delete directly).
-- No re-check can need them: a grade is always on a live node, and a node
-- re-added for the same concept is a new node id.
--
-- Both functions are owner-scoped (user AND session/node), refuse a blank id,
-- touch exactly the two tables, and return a count per table. Idempotent:
-- ADD COLUMN IF NOT EXISTS, a constraint swap guarded by name and by
-- definition, CREATE OR REPLACE, grants re-stated. No data is touched by
-- applying it. Reverse (by hand): drop the two functions; restore the two
-- original CHECKs once no row has text_erased_at set; drop the columns.

ALTER TABLE public.learning_prequestions ADD COLUMN IF NOT EXISTS text_erased_at timestamptz;
ALTER TABLE public.learning_self_explanations ADD COLUMN IF NOT EXISTS text_erased_at timestamptz;

DO $$
DECLARE
    v_name TEXT;
BEGIN
    -- The original, unnamed text CHECKs, found by their definition.
    FOR v_name IN
        SELECT c.conname FROM pg_constraint c
         WHERE c.conrelid = 'public.learning_prequestions'::regclass AND c.contype = 'c'
           AND pg_get_constraintdef(c.oid) ~ 'no_idea = \(guess_json IS NULL\)'
           AND c.conname <> 'learning_prequestions_guess_check'
    LOOP
        EXECUTE format('ALTER TABLE public.learning_prequestions DROP CONSTRAINT %I', v_name);
    END LOOP;
    FOR v_name IN
        SELECT c.conname FROM pg_constraint c
         WHERE c.conrelid = 'public.learning_self_explanations'::regclass AND c.contype = 'c'
           AND pg_get_constraintdef(c.oid) ~ 'reply_text IS NOT NULL'
           AND c.conname <> 'learning_self_explanations_reply_check'
    LOOP
        EXECUTE format('ALTER TABLE public.learning_self_explanations DROP CONSTRAINT %I', v_name);
    END LOOP;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'learning_prequestions_guess_check'
                      AND conrelid = 'public.learning_prequestions'::regclass) THEN
        ALTER TABLE public.learning_prequestions ADD CONSTRAINT learning_prequestions_guess_check
            CHECK (CASE WHEN text_erased_at IS NULL THEN no_idea = (guess_json IS NULL)
                        ELSE guess_json IS NULL END);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'learning_self_explanations_reply_check'
                      AND conrelid = 'public.learning_self_explanations'::regclass) THEN
        ALTER TABLE public.learning_self_explanations ADD CONSTRAINT learning_self_explanations_reply_check
            CHECK (CASE WHEN text_erased_at IS NULL THEN (status = 'replied') = (reply_text IS NOT NULL)
                        ELSE reply_text IS NULL END);
    END IF;
END $$;

-- C8: one session's typed text, cleared; the rows stay.
CREATE OR REPLACE FUNCTION learning_session_text_erase(p_user_id text, p_session_id text)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    n_self_explanations bigint;
    n_prequestions bigint;
BEGIN
    IF p_user_id IS NULL OR btrim(p_user_id) = ''
       OR p_session_id IS NULL OR btrim(p_session_id) = '' THEN
        RAISE EXCEPTION 'learning_session_text_erase needs a user id and a session id';
    END IF;
    UPDATE learning_self_explanations
       SET reply_text = NULL, text_erased_at = clock_timestamp()
     WHERE user_id = p_user_id AND session_id = p_session_id AND reply_text IS NOT NULL;
    GET DIAGNOSTICS n_self_explanations = ROW_COUNT;
    UPDATE learning_prequestions
       SET guess_json = NULL, text_erased_at = clock_timestamp()
     WHERE user_id = p_user_id AND session_id = p_session_id AND guess_json IS NOT NULL;
    GET DIAGNOSTICS n_prequestions = ROW_COUNT;
    RETURN jsonb_build_object(
        'learning_self_explanations', n_self_explanations,
        'learning_prequestions', n_prequestions
    );
END
$$;

-- C9: one deleted node's teach-prompt rows, removed.
CREATE OR REPLACE FUNCTION learning_node_erase(p_user_id text, p_node_id text)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    n_self_explanations bigint;
    n_prequestions bigint;
BEGIN
    IF p_user_id IS NULL OR btrim(p_user_id) = ''
       OR p_node_id IS NULL OR btrim(p_node_id) = '' THEN
        RAISE EXCEPTION 'learning_node_erase needs a user id and a node id';
    END IF;
    DELETE FROM learning_self_explanations WHERE user_id = p_user_id AND node_id = p_node_id;
    GET DIAGNOSTICS n_self_explanations = ROW_COUNT;
    DELETE FROM learning_prequestions WHERE user_id = p_user_id AND node_id = p_node_id;
    GET DIAGNOSTICS n_prequestions = ROW_COUNT;
    RETURN jsonb_build_object(
        'learning_self_explanations', n_self_explanations,
        'learning_prequestions', n_prequestions
    );
END
$$;

REVOKE ALL ON FUNCTION learning_session_text_erase(text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION learning_node_erase(text, text) FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON FUNCTION learning_session_text_erase(text, text) FROM %I', r);
            EXECUTE format('REVOKE ALL ON FUNCTION learning_node_erase(text, text) FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT EXECUTE ON FUNCTION learning_session_text_erase(text, text) TO service_role;
        GRANT EXECUTE ON FUNCTION learning_node_erase(text, text) TO service_role;
    END IF;
END $$;

-- PostgREST resolves functions and columns from its schema cache; reload it
-- (a no-op with no listener).
NOTIFY pgrst, 'reload schema';

-- @@ unit 20261118195701_encryption_aad_swap_nested.sql
-- Compare-and-swap for the AAD backfill's NESTED ciphertexts (finding M13,
-- docs/security/encryption-aad-plan.md phase 3; PR #866 review fix C6;
-- db/backfill_encryption_aad.py).
--
-- services/encryption.py::NESTED_CIPHERTEXTS names ciphertexts stored INSIDE a
-- plaintext JSONB column: the learning loop's goal text
-- (loop_state.goal.text_encrypted) and a step's or probe's sealed grade
-- checkpoint (…grade_checkpoint), both bound to their session with
-- `nested_bind`. They live in sessions.loop_state and, for a lazy loop
-- session not yet materialised, in tutor_pending_sessions.loop_state (the
-- same ciphertext, copied by SQL at materialisation: it is bound to the
-- session id, which both rows key on). The column-level swap
-- (20261116162200_encryption_aad_swap.sql) rewrites a whole cell, so it cannot
-- re-seal one value inside a document; this one can.
--
-- public.encryption_aad_swap_nested(table, pk, path, old_md5, new)
--   UPDATE <table> SET loop_state = jsonb_set(loop_state, path, to_jsonb(new))
--    WHERE <pk> = pk AND loop_state #> path is a JSON string
--      AND md5(loop_state #>> path) = old_md5
--   -> TRUE when the value was rewritten, FALSE when it changed (or is gone).
-- Only the value at `path` changes; the rest of the document is the row's as
-- it stands at the UPDATE (row-locked), so a concurrent app write elsewhere in
-- the document is never lost. On sessions the write also bumps
-- loop_state_rev, the app's compare-and-set revision
-- (learning/loop_state_store.py::save_loop_state): a turn that read the
-- document before the swap loses its CAS and re-applies to the re-sealed one
-- instead of writing the old value back. Only the two holder tables are
-- accepted; anything else raises.
--
-- Access: SECURITY INVOKER, EXECUTE for service_role only (it can already
-- write both tables; this adds no privilege), the 20261116162200 posture.
-- Inert until the backfill calls it.

CREATE OR REPLACE FUNCTION public.encryption_aad_swap_nested(
    p_table   TEXT,
    p_pk      TEXT,
    p_path    TEXT[],
    p_old_md5 TEXT,
    p_new     TEXT
)
RETURNS BOOLEAN
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path = ''
AS $$
DECLARE
    v_n INTEGER;
BEGIN
    IF p_path IS NULL OR cardinality(p_path) = 0 THEN
        RAISE EXCEPTION 'encryption_aad_swap_nested: an empty path';
    END IF;
    IF p_table = 'sessions' THEN
        UPDATE public.sessions
           SET loop_state = pg_catalog.jsonb_set(loop_state, p_path, pg_catalog.to_jsonb(p_new), false),
               loop_state_rev = loop_state_rev + 1
         WHERE id::text = p_pk
           AND pg_catalog.jsonb_typeof(loop_state #> p_path) = 'string'
           AND pg_catalog.md5(loop_state #>> p_path) = p_old_md5;
    ELSIF p_table = 'tutor_pending_sessions' THEN
        UPDATE public.tutor_pending_sessions
           SET loop_state = pg_catalog.jsonb_set(loop_state, p_path, pg_catalog.to_jsonb(p_new), false)
         WHERE session_id::text = p_pk
           AND pg_catalog.jsonb_typeof(loop_state #> p_path) = 'string'
           AND pg_catalog.md5(loop_state #>> p_path) = p_old_md5;
    ELSE
        RAISE EXCEPTION 'encryption_aad_swap_nested: public.% holds no nested ciphertext', p_table;
    END IF;
    GET DIAGNOSTICS v_n = ROW_COUNT;
    RETURN v_n > 0;
END;
$$;

COMMENT ON FUNCTION public.encryption_aad_swap_nested(TEXT, TEXT, TEXT[], TEXT, TEXT) IS
    'AAD backfill (M13): re-seal one ciphertext inside a loop_state document only if it still holds the value read (md5). Service-only.';

DO $$
DECLARE
    f CONSTANT TEXT := 'public.encryption_aad_swap_nested(text, text, text[], text, text)';
    r TEXT;
BEGIN
    EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC', f);
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON FUNCTION %s FROM %I', f, r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO service_role', f);
    END IF;
END $$;

NOTIFY pgrst, 'reload schema';

-- @@ unit 20261120055517_learning_check_items_question_hash.sql
-- PR #866 Z36: an index led by check_items.question_hash.
--
-- The served-text scan set (services/loop/posed.py::posed_items: every loop
-- turn, and every notes or flashcards request through the integrity guard,
-- while the student has an open pose, probe or ledger hash) reads the items
-- of its hashes through check_item_service.items_by_hash, filtered on
-- `question_hash IN (...)` across every course; item_rows_for reads by hash
-- the same way. No index had question_hash as its leading column: the UNIQUE
-- (course_id, concept_key, question_hash) leads with course_id, the concept
-- index with (course_id, concept_key, ...). So each of those reads was a
-- sequential scan of every course's bank of wide encrypted rows, growing
-- with the bank, on the request path.
--
-- Locks: CREATE INDEX holds SHARE on check_items for the build (reads go on,
-- writes wait); the table is the loop's own and small before launch. This
-- file runs in one transaction (db/migrate.py), so the lock_timeout below
-- makes a lock that does not come within 5s fail the file (rolled back,
-- nothing recorded; run it again) instead of queueing every drafting write
-- behind a long reader. Idempotent (IF NOT EXISTS); no data is touched.
--
-- Reverse (by hand): DROP INDEX IF EXISTS public.check_items_question_hash_idx;

SET LOCAL lock_timeout = '5s';

CREATE INDEX IF NOT EXISTS check_items_question_hash_idx
    ON public.check_items (question_hash);

-- @@ unit 20261120055827_learning_prequestion_guess_reseal.sql
-- PR #866 Z15: re-seal an append-only prequestion guess without UPDATE.
--
-- learning_prequestions is append-only (spec §13 A138): service_role holds
-- SELECT and INSERT only (20261108184825, restated by 20261109032302), and the
-- integration lane pins that. But `guess_json` is a 🔒 column
-- (services/encryption.ENCRYPTED_COLUMNS), so the AAD backfill
-- (db/backfill_encryption_aad.py, finding M13 phase 3) must re-seal each
-- legacy v1 guess as v2, and an ENCRYPTION_KEY rotation must re-seal every
-- guess. Both rewrote the cell through `encryption_aad_swap`, a SECURITY
-- INVOKER UPDATE run as service_role: refused (42501), so the backfill
-- crashed at this column, the cells after it in the run were never reached,
-- and its dry run never reached the exit-0 gate for
-- ENCRYPTION_LEGACY_READS=refuse.
--
-- learning_prequestion_guess_reseal(id, old_md5, new): the one write a re-seal
-- needs, and nothing else. SECURITY DEFINER, so the UPDATE runs as the owner,
-- and narrowed so it cannot be used to edit a guess:
--   * one cell: learning_prequestions.guess_json, by primary key;
--   * a compare-and-swap: the cell must still hold the value the caller read
--     (md5 of the stored text, the backfill's `_md5`), so a concurrent write
--     is never overwritten (that row is retried on the next run);
--   * only a stored guess, and only by a v2 ciphertext (`enc2:` prefix): it
--     never clears a guess (that is learning_session_text_erase's, C8), never
--     writes one where "no idea" stored none, and never writes plaintext.
-- It cannot check that the new ciphertext seals the same plaintext (the key
-- never reaches the database); service_role, the only role that may call it,
-- already reads every guess and holds the key. The table grants are unchanged.
--
-- Deploy order: before the AAD backfill runs with --apply (it probes the
-- function first and aborts, writing nothing, when it is missing); either
-- side of the code. Idempotent; no data is touched.
-- Reverse (by hand): DROP FUNCTION IF EXISTS
--   learning_prequestion_guess_reseal(text, text, text);

CREATE OR REPLACE FUNCTION learning_prequestion_guess_reseal(
    p_id      text,
    p_old_md5 text,
    p_new     text
)
RETURNS boolean
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_n integer;
BEGIN
    IF p_new IS NULL OR left(p_new, 5) <> 'enc2:' THEN
        RAISE EXCEPTION 'learning_prequestion_guess_reseal: a guess is re-sealed only as a v2 ciphertext';
    END IF;
    UPDATE learning_prequestions
       SET guess_json = p_new
     WHERE id = p_id
       AND guess_json IS NOT NULL
       AND md5(guess_json) = p_old_md5;
    GET DIAGNOSTICS v_n = ROW_COUNT;
    RETURN v_n > 0;
END
$$;

COMMENT ON FUNCTION learning_prequestion_guess_reseal(text, text, text) IS
    'PR #866 Z15: re-seal one learning_prequestions.guess_json as v2 (AAD backfill, key rotation); compare-and-swap; service-only.';

REVOKE ALL ON FUNCTION learning_prequestion_guess_reseal(text, text, text) FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format(
                'REVOKE ALL ON FUNCTION learning_prequestion_guess_reseal(text, text, text) FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT EXECUTE ON FUNCTION learning_prequestion_guess_reseal(text, text, text) TO service_role;
    END IF;
END $$;

-- PostgREST resolves functions from its schema cache; reload it (a no-op with
-- no listener).
NOTIFY pgrst, 'reload schema';

-- @@ unit 20261120070405_learning_evidence_seeds.sql
-- 20261120070405_learning_evidence_seeds.sql
-- Learning loop spec §13 A150 (#866 K03, owner decision 2026-11-19): a
-- concept with no learner_state row starts BKT from its stored map score
-- (graph_nodes.mastery_score above 0, clamped to BKT_P_MAX; a never-studied
-- concept, score 0, from the prior BKT_L0). This journals that starting score,
-- so the A123 void replay (learning/evidence_replay.py) starts every node from
-- exactly the belief the original write did, instead of the prior.
--
-- (1) node_mastery_events.seeds jsonb: {node id: stored score} for each node
--     the row is the first to reach while it had no learner_state row (its own
--     concept, or a node its one-hop propagation moved). NULL on every other
--     row (no default; adding the column rewrites nothing), so an operation
--     that starts no node plans and fingerprints exactly as before. The CHECK
--     is NOT VALID: every existing row is NULL (the 20261108072715 choice).
-- (2) learning_evidence_commit is re-created as 20261108205812's definition
--     with three edits, verbatim otherwise: 'seeds' in the event key
--     whitelist; its check (an object, or absent/null, whose keys are plan
--     nodes with a state row in the plan and NO learner_state row yet, and
--     whose values are JSON numbers in [0, 1]); its insert column and value.
-- (3) learning_evidence_void_snapshot is re-created as 20261108072715's
--     definition with one edit: each journal row carries its `seeds`. A CREATE
--     OR REPLACE replaces every SET clause, so it carries 20261108115720's
--     extra_float_digits = 3 itself (exact floats in the snapshot the void
--     replays from).
-- The registry in backend/tests/test_learning_migration_functions.py pins
-- that both definitions keep every earlier change.
--
-- Deploy order: apply before the code (the writer names the key, and the
-- old commit function refuses it). Older code never names it.
--
-- Locks: one transaction (db/migrate.py); the ALTER takes ACCESS EXCLUSIVE on
-- node_mastery_events for a catalog-only change, bounded by lock_timeout 5s
-- (rolled back, nothing recorded, when the lock does not come: run it again)
-- so it never queues every learning_evidence_commit (lock_timeout 2s) behind
-- it. Idempotent: ADD COLUMN IF NOT EXISTS, a guarded constraint, CREATE OR
-- REPLACE, and grants that are re-applied as they stand. node_mastery_events
-- keeps its RLS posture (20261109032302) and its place in the account wipe,
-- bundle and purge (a column, not a table).

SET LOCAL lock_timeout = '5s';

ALTER TABLE public.node_mastery_events ADD COLUMN IF NOT EXISTS seeds jsonb;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conrelid = 'public.node_mastery_events'::regclass
       AND conname = 'node_mastery_events_seeds_check'
  ) THEN
    ALTER TABLE public.node_mastery_events
      ADD CONSTRAINT node_mastery_events_seeds_check
      CHECK (seeds IS NULL OR jsonb_typeof(seeds) = 'object') NOT VALID;
  END IF;
END $$;

CREATE OR REPLACE FUNCTION learning_evidence_commit(
    p_user_id text,p_course_id text,p_operation_id uuid,p_input_fingerprint text,p_plan jsonb
) RETURNS jsonb LANGUAGE plpgsql SET search_path=public,pg_temp
SET lock_timeout='2s' SET statement_timeout='10s' AS $$
DECLARE r learning_evidence_operations%ROWTYPE; x jsonb; v bigint; ids text[];
    grade_ids text[]; es jsonb; n graph_nodes%ROWTYPE; s learner_state%ROWTYPE;
    ev node_mastery_events%ROWTYPE; obs jsonb; expected_count bigint; actual_count bigint;
    item record; retired_items jsonb;
BEGIN
    IF p_user_id IS NULL OR p_user_id='' OR p_operation_id IS NULL
       OR p_input_fingerprint IS NULL OR p_input_fingerprint !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(p_plan) IS DISTINCT FROM 'object'
       OR (SELECT array_agg(k ORDER BY k) FROM jsonb_object_keys(p_plan) k)
          IS DISTINCT FROM ARRAY['changes','checks','edges','events','mirrors','nodes','observed_at','state_rows','states_expected']::text[]
       OR EXISTS(SELECT 1 FROM jsonb_each(p_plan) p WHERE p.key<>'observed_at' AND jsonb_typeof(p.value)<>'array')
       OR jsonb_typeof(p_plan->'observed_at') NOT IN ('null','string') THEN
        RAISE EXCEPTION 'Invalid evidence transaction envelope';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('learning-evidence:'||p_user_id,0));
    SELECT * INTO r FROM learning_evidence_operations WHERE operation_id=p_operation_id;
    IF FOUND THEN
        IF r.user_id IS DISTINCT FROM p_user_id OR r.course_id IS DISTINCT FROM p_course_id
           OR r.input_fingerprint IS DISTINCT FROM p_input_fingerprint OR r.plan IS DISTINCT FROM p_plan THEN
            RETURN jsonb_build_object('status','conflict');
        END IF;
        RETURN jsonb_build_object('status','replay','receipt',jsonb_build_object(
            'operation_id',r.operation_id,'user_id',r.user_id,'course_id',r.course_id,
            'input_fingerprint',r.input_fingerprint,'changes',r.changes,'posteriors',(
                SELECT jsonb_object_agg(value->>'id',value->'mastery_score') FROM jsonb_array_elements(r.plan->'mirrors')),
            'observations',(SELECT coalesce(jsonb_agg(entry.value->'planning_observation' ORDER BY entry.position),'[]')
                FROM jsonb_array_elements(r.plan->'events') WITH ORDINALITY entry(value,position)
                WHERE jsonb_typeof(entry.value->'planning_observation')='object')));
    END IF;
    -- §13 A123: a check item staff retired takes no new evidence. A SHARED lock
    -- per graded item (sorted), against check_item_review_decide's EXCLUSIVE one:
    -- a retire decided while this grade was in flight waits for its commit (and
    -- the void sweep then finds the row); a grade arriving after it is refused.
    FOR item IN
        SELECT DISTINCT g.course_id AS course_id, e.value->>'question_hash' AS question_hash
          FROM jsonb_array_elements(p_plan->'events') e
          JOIN graph_nodes g ON g.id = e.value->>'node_id'
         WHERE jsonb_typeof(e.value->'check_item_id') = 'string'
           AND jsonb_typeof(e.value->'question_hash') = 'string'
           AND g.course_id IS NOT NULL
         ORDER BY 1, 2
    LOOP
        PERFORM pg_advisory_xact_lock_shared(
            hashtextextended('check-item-review:'||item.course_id||':'||item.question_hash,0));
    END LOOP;
    SELECT coalesce(jsonb_agg(jsonb_build_object('course_id',q.course_id,'question_hash',q.question_hash)
               ORDER BY q.course_id,q.question_hash),'[]') INTO retired_items
      FROM (SELECT DISTINCT g.course_id AS course_id, e.value->>'question_hash' AS question_hash
              FROM jsonb_array_elements(p_plan->'events') e
              JOIN graph_nodes g ON g.id = e.value->>'node_id'
             WHERE jsonb_typeof(e.value->'check_item_id') = 'string'
               AND jsonb_typeof(e.value->'question_hash') = 'string'
               AND g.course_id IS NOT NULL) q
     WHERE EXISTS(SELECT 1 FROM check_item_reviews cr WHERE cr.course_id=q.course_id
                  AND cr.question_hash=q.question_hash AND cr.status='retired');
    IF jsonb_array_length(retired_items) > 0 THEN
        RETURN jsonb_build_object('status','retired','items',retired_items);
    END IF;
    SELECT array_agg(value->>'id' ORDER BY value->>'id') INTO ids FROM jsonb_array_elements(p_plan->'nodes');
    SELECT array_agg(DISTINCT value->>'node_id' ORDER BY value->>'node_id') INTO grade_ids
        FROM jsonb_array_elements(p_plan->'events');
    IF coalesce(cardinality(ids),0)=0 OR coalesce(cardinality(grade_ids),0)=0
       OR cardinality(ids)<>(SELECT count(DISTINCT unnest) FROM unnest(ids))
       OR jsonb_array_length(p_plan->'changes')<>jsonb_array_length(p_plan->'events') THEN
        RAISE EXCEPTION 'Invalid evidence transaction members';
    END IF;
    -- Short, bounded coarse lock closes phantom edge inserts AND relation/
    -- endpoint edits/deletes from legacy writers. Acquire it before node locks
    -- so a legacy edge FK check cannot form a node/table lock-order inversion.
    LOCK TABLE graph_edges IN SHARE MODE;
    PERFORM 1 FROM graph_nodes WHERE id=ANY(ids) ORDER BY id FOR UPDATE;
    IF (SELECT count(*) FROM graph_nodes WHERE id=ANY(ids) AND user_id=p_user_id
        AND (p_course_id IS NULL OR course_id=p_course_id))<>cardinality(ids) THEN
        RETURN jsonb_build_object('status','ownership');
    END IF;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'nodes') LOOP
        IF jsonb_typeof(x->'version') IS DISTINCT FROM 'number' OR (x->>'version') !~ '^[0-9]+$' THEN
            RAISE EXCEPTION 'Invalid graph version';
        END IF;
        SELECT evidence_version INTO v FROM graph_nodes WHERE id=x->>'id';
        IF v IS DISTINCT FROM (x->>'version')::bigint THEN RETURN jsonb_build_object('status','stale'); END IF;
    END LOOP;
    SELECT coalesce(jsonb_agg(jsonb_build_object('source',e.source_node_id,'target',e.target_node_id)
               ORDER BY e.source_node_id,e.target_node_id),'[]') INTO es
      FROM graph_edges e JOIN graph_nodes a ON a.id=e.source_node_id JOIN graph_nodes b ON b.id=e.target_node_id
      WHERE e.user_id=p_user_id AND e.relationship_type='prerequisite'
        AND a.user_id=p_user_id AND b.user_id=p_user_id AND a.course_id IS NOT DISTINCT FROM b.course_id
        AND (p_course_id IS NULL OR a.course_id=p_course_id)
        AND (e.source_node_id=ANY(grade_ids) OR e.target_node_id=ANY(grade_ids));
    IF es IS DISTINCT FROM p_plan->'edges' THEN RETURN jsonb_build_object('status','stale'); END IF;
    PERFORM 1 FROM learner_state WHERE user_id=p_user_id AND node_id=ANY(ids) ORDER BY node_id FOR UPDATE;
    IF jsonb_array_length(p_plan->'states_expected')<>cardinality(ids)
       OR (SELECT count(DISTINCT value->>'node_id') FROM jsonb_array_elements(p_plan->'states_expected'))<>cardinality(ids)
       OR EXISTS(SELECT 1 FROM jsonb_array_elements(p_plan->'states_expected') WHERE NOT (value->>'node_id'=ANY(ids))) THEN
        RAISE EXCEPTION 'Invalid learner-state snapshot';
    END IF;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'states_expected') LOOP
        IF jsonb_typeof(x->'version') NOT IN ('number','null')
           OR (x->>'version' IS NOT NULL AND (x->>'version') !~ '^[0-9]+$') THEN
            RAISE EXCEPTION 'Invalid learner-state version';
        END IF;
        SELECT evidence_version INTO v FROM learner_state WHERE user_id=p_user_id AND node_id=x->>'node_id';
        IF v IS DISTINCT FROM (x->>'version')::bigint THEN RETURN jsonb_build_object('status','stale'); END IF;
    END LOOP;
    IF p_plan->>'observed_at' IS NOT NULL AND EXISTS(
        SELECT 1 FROM learner_state l WHERE l.user_id=p_user_id
        AND l.node_id IN (SELECT value->>'node_id' FROM jsonb_array_elements(p_plan->'state_rows'))
        AND (l.last_evidence_at > (p_plan->>'observed_at')::timestamptz
             OR l.evidence_touch_at > (p_plan->>'observed_at')::timestamptz)
    ) THEN RETURN jsonb_build_object('status','superseded'); END IF;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'checks') LOOP
        IF jsonb_typeof(x->'count') IS DISTINCT FROM 'number'
           OR (x->>'count') !~ '^[0-9]+$'
           OR jsonb_typeof(x->'global_count') IS DISTINCT FROM 'number'
           OR (x->>'global_count') !~ '^[0-9]+$' THEN
            RAISE EXCEPTION 'Invalid exposure snapshot';
        END IF;
        SELECT count(*) INTO actual_count FROM node_mastery_events e JOIN graph_nodes g ON g.id=e.node_id
            WHERE g.user_id=p_user_id AND e.event_type='evidence' AND e.session_id=x->>'session_id'
              AND e.question_hash=x->>'question_hash';
        IF actual_count IS DISTINCT FROM (x->>'count')::bigint THEN RETURN jsonb_build_object('status','stale'); END IF;
        SELECT count(*) INTO actual_count FROM node_mastery_events e JOIN graph_nodes g ON g.id=e.node_id
            WHERE g.user_id=p_user_id AND e.event_type='evidence' AND e.question_hash=x->>'question_hash';
        IF actual_count IS DISTINCT FROM (x->>'global_count')::bigint THEN RETURN jsonb_build_object('status','stale'); END IF;
    END LOOP;
    IF jsonb_array_length(p_plan->'state_rows')=0
       OR jsonb_array_length(p_plan->'state_rows')<>jsonb_array_length(p_plan->'mirrors')
       OR (SELECT count(DISTINCT value->>'node_id') FROM jsonb_array_elements(p_plan->'state_rows'))<>jsonb_array_length(p_plan->'state_rows')
       OR (SELECT count(DISTINCT value->>'id') FROM jsonb_array_elements(p_plan->'mirrors'))<>jsonb_array_length(p_plan->'mirrors')
       OR EXISTS(SELECT 1 FROM unnest(grade_ids) id WHERE NOT EXISTS(
            SELECT 1 FROM jsonb_array_elements(p_plan->'state_rows') state_entry(value)
            WHERE state_entry.value->>'node_id'=id)) THEN
        RAISE EXCEPTION 'Invalid transaction row sets';
    END IF;
    -- Validate the WHOLE plan before its first mutation. SQL does no BKT,
    -- FSRS, weighting, threshold or propagation arithmetic.
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'state_rows') LOOP
        s := jsonb_populate_record(NULL::learner_state,x);
        IF s.user_id IS DISTINCT FROM p_user_id OR NOT(s.node_id=ANY(ids))
           OR s.p_known IS NULL OR NOT(s.p_known BETWEEN 0 AND 1)
           OR s.updated_at IS NULL
           OR s.n_strong_unassisted<0 OR s.streak_unassisted<0 OR s.max_streak_unassisted<0 OR s.opps<0
           OR EXISTS(SELECT 1 FROM jsonb_object_keys(x) k WHERE k NOT IN (
                'user_id','node_id','p_known','n_strong_unassisted','streak_unassisted','max_streak_unassisted','opps',
                'fsrs_d','fsrs_s','fsrs_last_review_at','fsrs_due_at','last_evidence_at','updated_at'))
           OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_plan->'mirrors') m WHERE m->>'id'=s.node_id) THEN
            RAISE EXCEPTION 'Invalid transaction learner state';
        END IF;
    END LOOP;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'events') LOOP
        ev := jsonb_populate_record(NULL::node_mastery_events,x);
        IF ev.id IS NULL OR NOT(ev.node_id=ANY(grade_ids)) OR NOT(ev.node_id=ANY(ids))
           OR ev.event_type IS DISTINCT FROM 'evidence' OR ev.correct IS NULL
           OR ev.p_before IS NULL OR NOT(ev.p_before BETWEEN 0 AND 1)
           OR ev.p_after IS NULL OR NOT(ev.p_after BETWEEN 0 AND 1)
           OR ev.weight IS NULL OR NOT(ev.weight BETWEEN 0 AND 1)
           OR ev.created_at IS NULL OR ev.evidence_seq IS NULL OR ev.evidence_seq<0
           OR jsonb_typeof(x->'correct') IS DISTINCT FROM 'boolean'
           OR jsonb_typeof(x->'assisted') IS DISTINCT FROM 'boolean'
           -- §13 A123: the replay inputs, when present, are well formed
           OR (x ? 'retention' AND jsonb_typeof(x->'retention') NOT IN ('number','null'))
           OR (ev.retention IS NOT NULL AND NOT (ev.retention > 0 AND ev.retention <= 1))
           OR (x ? 'same_session_recheck' AND jsonb_typeof(x->'same_session_recheck') NOT IN ('boolean','null'))
           OR (x ? 'propagated_to' AND jsonb_typeof(x->'propagated_to') NOT IN ('array','null'))
           OR (jsonb_typeof(x->'propagated_to') = 'array' AND EXISTS(
                SELECT 1 FROM jsonb_array_elements(x->'propagated_to') t
                 WHERE jsonb_typeof(t) IS DISTINCT FROM 'string' OR NOT ((t #>> '{}')=ANY(ids))
                    OR (t #>> '{}')=ev.node_id
                    OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_plan->'state_rows') sr
                                   WHERE sr->>'node_id'=(t #>> '{}'))))
           OR EXISTS(SELECT 1 FROM jsonb_object_keys(x) k WHERE k NOT IN (
                'id','node_id','delta','reason','created_at','event_type','channel','correct','weight','assisted','max_rung',
                'p_before','p_after','session_id','check_item_id','question_hash','confidence','grader_backend','evidence_seq','planning_observation',
                'retention','same_session_recheck','propagated_to',
                'student_confidence',
                'seeds',
                'multi_concept'))
           -- spec §13 A127: a stated confidence is a JSON number in [0, 1], or absent/null
           OR (x ? 'student_confidence' AND jsonb_typeof(x->'student_confidence') NOT IN ('number','null'))
           OR NOT (ev.student_confidence IS NULL OR ev.student_confidence BETWEEN 0 AND 1)
           -- spec §13 A141: a multi-concept item's row says so: a JSON boolean, or absent/null
           OR (x ? 'multi_concept' AND jsonb_typeof(x->'multi_concept') NOT IN ('boolean','null'))
           -- spec §13 A150: the starting scores, when present: an object naming
           -- plan nodes that start now (no learner_state row) and each one's
           -- score, a JSON number in [0, 1]
           OR (x ? 'seeds' AND jsonb_typeof(x->'seeds') NOT IN ('object','null'))
           OR (jsonb_typeof(x->'seeds') = 'object' AND EXISTS(
                SELECT 1 FROM jsonb_each(x->'seeds') t
                 WHERE NOT (t.key=ANY(ids))
                    OR CASE WHEN jsonb_typeof(t.value) = 'number'
                            THEN NOT ((t.value #>> '{}')::double precision BETWEEN 0 AND 1)
                            ELSE true END
                    OR EXISTS(SELECT 1 FROM learner_state l WHERE l.user_id=p_user_id AND l.node_id=t.key)
                    OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_plan->'state_rows') sr
                                   WHERE sr->>'node_id'=t.key))) THEN
            RAISE EXCEPTION 'Invalid transaction evidence';
        END IF;
        obs := ev.planning_observation;
        IF obs IS NOT NULL AND (
            jsonb_typeof(obs) IS DISTINCT FROM 'object'
            OR obs->>'node_id' IS DISTINCT FROM ev.node_id OR obs->>'question_hash' IS DISTINCT FROM ev.question_hash
            OR obs->>'check_item_id' IS DISTINCT FROM ev.check_item_id OR obs->>'channel' IS DISTINCT FROM ev.channel
            OR obs->'correct' IS DISTINCT FROM to_jsonb(ev.correct)
            OR obs->'assisted' IS DISTINCT FROM to_jsonb(ev.assisted)
            OR obs->'max_rung' IS DISTINCT FROM to_jsonb(ev.max_rung)
            OR jsonb_typeof(obs->'independent') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'same_session_recheck') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'idk') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'synthetic_idk') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'previously_seen') IS DISTINCT FROM 'boolean'
            OR jsonb_typeof(obs->'difficulty') IS DISTINCT FROM 'number'
            OR (obs->>'difficulty') NOT IN ('1','2','3')
            OR NOT(obs ?& ARRAY['check_item_id','difficulty','synthetic_idk','previously_seen','node_id',
                'question_hash','channel','correct','idk','assisted','max_rung','same_session_recheck','independent'])
            OR EXISTS(SELECT 1 FROM jsonb_object_keys(obs) k WHERE k NOT IN (
                'check_item_id','difficulty','synthetic_idk','previously_seen','node_id','question_hash',
                'channel','correct','idk','assisted','max_rung','same_session_recheck','independent'))
            OR (obs->>'idk')::boolean AND ev.correct
            OR (obs->>'synthetic_idk')::boolean AND NOT (obs->>'idk')::boolean
            OR ev.assisted IS DISTINCT FROM (ev.max_rung>0)
            OR (obs->>'independent')::boolean IS DISTINCT FROM (NOT (
                ev.max_rung>0 OR ev.assisted OR (obs->>'same_session_recheck')::boolean
                OR (obs->>'synthetic_idk')::boolean OR (obs->>'previously_seen')::boolean))) THEN
            RAISE EXCEPTION 'Invalid final planning provenance';
        END IF;
    END LOOP;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'state_rows') LOOP
        s := jsonb_populate_record(NULL::learner_state,x);
        INSERT INTO learner_state(user_id,node_id,p_known,n_strong_unassisted,streak_unassisted,max_streak_unassisted,
            opps,fsrs_d,fsrs_s,fsrs_last_review_at,fsrs_due_at,last_evidence_at,updated_at,evidence_touch_at)
        VALUES(s.user_id,s.node_id,s.p_known,s.n_strong_unassisted,s.streak_unassisted,s.max_streak_unassisted,
            s.opps,s.fsrs_d,s.fsrs_s,s.fsrs_last_review_at,s.fsrs_due_at,s.last_evidence_at,s.updated_at,s.updated_at)
        ON CONFLICT(user_id,node_id) DO UPDATE SET p_known=EXCLUDED.p_known,n_strong_unassisted=EXCLUDED.n_strong_unassisted,
            streak_unassisted=EXCLUDED.streak_unassisted,max_streak_unassisted=EXCLUDED.max_streak_unassisted,
            opps=EXCLUDED.opps,fsrs_d=EXCLUDED.fsrs_d,fsrs_s=EXCLUDED.fsrs_s,
            fsrs_last_review_at=EXCLUDED.fsrs_last_review_at,fsrs_due_at=EXCLUDED.fsrs_due_at,
            last_evidence_at=EXCLUDED.last_evidence_at,updated_at=EXCLUDED.updated_at,
            evidence_touch_at=greatest(learner_state.evidence_touch_at,EXCLUDED.evidence_touch_at);
    END LOOP;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'mirrors') LOOP
        IF NOT(x->>'id'=ANY(ids)) OR NOT EXISTS(SELECT 1 FROM jsonb_array_elements(p_plan->'state_rows') t WHERE t->>'node_id'=x->>'id')
           OR jsonb_typeof(x->'mastery_score') IS DISTINCT FROM 'number'
           OR NOT((x->>'mastery_score')::double precision BETWEEN 0 AND 1)
           OR EXISTS(SELECT 1 FROM jsonb_object_keys(x) k WHERE k NOT IN ('id','mastery_score','mastery_tier','times_studied','last_studied_at')) THEN
            RAISE EXCEPTION 'Invalid transaction mirror';
        END IF;
        UPDATE graph_nodes SET mastery_score=(x->>'mastery_score')::double precision,mastery_tier=x->>'mastery_tier',
            times_studied=CASE WHEN x ? 'times_studied' THEN (x->>'times_studied')::int ELSE times_studied END,
            last_studied_at=CASE WHEN x ? 'last_studied_at' THEN (x->>'last_studied_at')::timestamptz ELSE last_studied_at END
            WHERE id=x->>'id' AND user_id=p_user_id;
    END LOOP;
    FOR x IN SELECT value FROM jsonb_array_elements(p_plan->'events') LOOP
        ev := jsonb_populate_record(NULL::node_mastery_events,x);
        INSERT INTO node_mastery_events(id,node_id,delta,reason,created_at,event_type,channel,correct,weight,assisted,max_rung,
            p_before,p_after,session_id,check_item_id,question_hash,confidence,grader_backend,evidence_seq,planning_observation,
            retention,same_session_recheck,propagated_to,
            multi_concept,
            seeds,
            student_confidence)
        VALUES(ev.id,ev.node_id,ev.delta,ev.reason,ev.created_at,ev.event_type,ev.channel,ev.correct,ev.weight,ev.assisted,ev.max_rung,
            ev.p_before,ev.p_after,ev.session_id,ev.check_item_id,ev.question_hash,ev.confidence,ev.grader_backend,ev.evidence_seq,ev.planning_observation,
            ev.retention,ev.same_session_recheck,ev.propagated_to,
            ev.multi_concept,
            ev.seeds,
            ev.student_confidence);
    END LOOP;
    INSERT INTO learning_evidence_operations(operation_id,user_id,course_id,input_fingerprint,plan,changes)
        VALUES(p_operation_id,p_user_id,p_course_id,p_input_fingerprint,p_plan,p_plan->'changes');
    RETURN learning_evidence_receipt(p_user_id,p_operation_id);
END $$;

CREATE OR REPLACE FUNCTION learning_evidence_void_snapshot(
    p_user_id text,p_course_id text,p_question_hash text
) RETURNS jsonb LANGUAGE plpgsql SET search_path=public,pg_temp
SET lock_timeout='2s' SET statement_timeout='10s' SET extra_float_digits=3 AS $$
DECLARE ns jsonb; ss jsonb; es jsonb; js jsonb; rs jsonb; ms jsonb; retired boolean;
BEGIN
    IF coalesce(p_user_id,'')='' OR coalesce(p_course_id,'')='' OR coalesce(p_question_hash,'')='' THEN
        RAISE EXCEPTION 'Invalid evidence void snapshot identity';
    END IF;
    retired := EXISTS(SELECT 1 FROM check_item_reviews WHERE course_id=p_course_id
                      AND question_hash=p_question_hash AND status='retired');
    SELECT coalesce(jsonb_agg(jsonb_build_object('id',n.id,'concept_name',n.concept_name,
        'mastery_score',n.mastery_score,'mastery_tier',n.mastery_tier,
        'evidence_version',n.evidence_version) ORDER BY n.id),'[]') INTO ns
      FROM graph_nodes n WHERE n.user_id=p_user_id AND n.course_id=p_course_id;
    SELECT coalesce(jsonb_agg(to_jsonb(s) ORDER BY s.node_id),'[]') INTO ss
      FROM learner_state s JOIN graph_nodes n ON n.id=s.node_id
     WHERE s.user_id=p_user_id AND n.user_id=p_user_id AND n.course_id=p_course_id;
    SELECT coalesce(jsonb_agg(jsonb_build_object('source',e.source_node_id,'target',e.target_node_id)
               ORDER BY e.source_node_id,e.target_node_id),'[]') INTO es
      FROM graph_edges e JOIN graph_nodes a ON a.id=e.source_node_id JOIN graph_nodes b ON b.id=e.target_node_id
     WHERE e.user_id=p_user_id AND e.relationship_type='prerequisite'
       AND a.user_id=p_user_id AND b.user_id=p_user_id
       AND a.course_id=p_course_id AND b.course_id=p_course_id;
    SELECT coalesce(jsonb_agg(jsonb_build_object('id',e.id,'node_id',e.node_id,'created_at',e.created_at,
        'evidence_seq',e.evidence_seq,'channel',e.channel,'correct',e.correct,'weight',e.weight,
        'assisted',e.assisted,'max_rung',e.max_rung,'reason',e.reason,'confidence',e.confidence,
        'session_id',e.session_id,'question_hash',e.question_hash,'check_item_id',e.check_item_id,
        'planning_recheck',e.planning_observation->'same_session_recheck',
        'same_session_recheck',e.same_session_recheck,'retention',e.retention,
        'propagated_to',e.propagated_to,'seeds',e.seeds,'void',(v.event_id IS NOT NULL))
        ORDER BY e.created_at,e.evidence_seq NULLS LAST,e.id),'[]') INTO js
      FROM node_mastery_events e JOIN graph_nodes n ON n.id=e.node_id
      LEFT JOIN learning_evidence_voids v ON v.event_id=e.id
     WHERE n.user_id=p_user_id AND n.course_id=p_course_id AND e.event_type='evidence';
    SELECT coalesce(jsonb_agg(r.question_hash ORDER BY r.question_hash),'[]') INTO rs
      FROM check_item_reviews r WHERE r.course_id=p_course_id AND r.status='retired';
    SELECT coalesce(jsonb_agg(jsonb_build_object('id',m.id,'node_id',m.node_id,'count',m.count,
        'check_item_id',m.check_item_id,'attempts',(
            SELECT coalesce(jsonb_agg(jsonb_build_object('course_id',a.course_id,
                'question_hash',a.question_hash,'check_item_id',a.check_item_id) ORDER BY a.id),'[]')
              FROM misconception_attempts a WHERE a.misconception_id=m.id)) ORDER BY m.id),'[]') INTO ms
      FROM misconceptions m JOIN graph_nodes n ON n.id=m.node_id
     WHERE m.user_id=p_user_id AND n.user_id=p_user_id AND n.course_id=p_course_id
       AND m.resolved_at IS NULL;
    RETURN jsonb_build_object('status','snapshot','retired',retired,'nodes',ns,'states',ss,
        'edges',es,'journal',js,'retired_hashes',rs,'misconceptions',ms);
END $$;

REVOKE ALL ON FUNCTION learning_evidence_commit(text,text,uuid,text,jsonb) FROM PUBLIC;
REVOKE ALL ON FUNCTION learning_evidence_void_snapshot(text,text,text) FROM PUBLIC;
DO $$ DECLARE r text; BEGIN
    FOREACH r IN ARRAY ARRAY['anon','authenticated'] LOOP
        IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=r) THEN
            EXECUTE format('REVOKE ALL ON FUNCTION learning_evidence_commit(text,text,uuid,text,jsonb) FROM %I',r);
            EXECUTE format('REVOKE ALL ON FUNCTION learning_evidence_void_snapshot(text,text,text) FROM %I',r);
        END IF;
    END LOOP;
    IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN
        GRANT EXECUTE ON FUNCTION learning_evidence_commit(text,text,uuid,text,jsonb) TO service_role;
        GRANT EXECUTE ON FUNCTION learning_evidence_void_snapshot(text,text,text) TO service_role;
    END IF;
END $$;

-- PostgREST resolves functions and columns from its schema cache; the local
-- stack does not reliably reload on DDL (docs/local-supabase.md). NOTIFY is
-- delivered at COMMIT and is a no-op with no listener.
NOTIFY pgrst, 'reload schema';
