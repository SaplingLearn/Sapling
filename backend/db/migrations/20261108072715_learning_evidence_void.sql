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
