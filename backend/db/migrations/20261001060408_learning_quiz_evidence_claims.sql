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
