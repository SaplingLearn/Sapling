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
