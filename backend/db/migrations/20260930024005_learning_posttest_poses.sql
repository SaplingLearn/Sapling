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
