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
