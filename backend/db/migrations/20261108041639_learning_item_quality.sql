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
