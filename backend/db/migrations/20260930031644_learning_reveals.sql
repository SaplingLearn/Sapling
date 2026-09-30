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
