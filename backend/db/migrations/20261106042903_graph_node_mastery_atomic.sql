-- #766: graph_nodes mastery updates become one atomic statement; the tier
-- CHECK loses a value that is never stored.
--
-- 1. apply_mastery_delta
--    services/graph_service.py::apply_graph_update read mastery_score and
--    times_studied in Python, added the delta, and wrote score, tier and
--    times_studied back by id: a blind read-modify-write. Two concurrent
--    writers on one node (a quiz submit and a tutor turn, two tabs) both read
--    the same `before` and the later write erased the earlier delta and its
--    times_studied increment. The append-only node_mastery_events log (0023)
--    kept the events, but the scalar the whole app reads drifted from them.
--
--    This function locks the row, applies the clamped delta, recomputes the
--    tier and increments times_studied in one transaction, and returns the
--    before/after it actually applied, so concurrent deltas compose.
--
--    The tier thresholds are PARAMETERS, not literals: config.py
--    (MASTERY_*_MIN) stays their one home, and the caller passes them. A
--    threshold change therefore takes effect on the next write of each node;
--    rows nobody studies keep their old stored tier until
--    scripts/backfill_mastery_tiers.py (dry-run by default) recomputes them.
--
--    'unexplored' still covers both "never studied" and "studied, score below
--    the struggling floor"; times_studied = 0 is the discriminator. Splitting
--    the tier would ripple through the CHECK, the frontend tier mirror
--    (Learn.tsx::tierForScore) and every tier filter, so it stays documented
--    rather than split.
--
-- 2. 'subject_root' leaves the CHECK
--    It is a synthetic tier graph_service.get_graph stamps on the per-course
--    hub node it builds in the response payload; no writer ever persists it.
--    Allowing it in storage only let a bad write through. Any such row (none
--    are expected) is reset to 'unexplored' first so the new constraint
--    validates; the backfill script then recomputes it from its score.

CREATE OR REPLACE FUNCTION apply_mastery_delta(
    p_node_id        TEXT,
    p_user_id        TEXT,
    p_delta          DOUBLE PRECISION,
    p_mastered_min   DOUBLE PRECISION,
    p_learning_min   DOUBLE PRECISION,
    p_struggling_min DOUBLE PRECISION
)
RETURNS TABLE (before_score DOUBLE PRECISION, after_score DOUBLE PRECISION, new_tier TEXT)
LANGUAGE plpgsql
VOLATILE
AS $$
DECLARE
    v_before DOUBLE PRECISION;
    v_after  DOUBLE PRECISION;
    v_tier   TEXT;
BEGIN
    -- FOR UPDATE: a concurrent writer waits here and then reads the score the
    -- first one committed, instead of the stale one it would have read.
    SELECT g.mastery_score INTO v_before
      FROM graph_nodes g
     WHERE g.id = p_node_id AND g.user_id = p_user_id
       FOR UPDATE;
    IF NOT FOUND THEN
        RETURN;  -- deleted (or not this user's): no row, the caller skips it
    END IF;

    v_after := GREATEST(0.0, LEAST(1.0, v_before + COALESCE(p_delta, 0.0)));
    v_tier := CASE
        WHEN v_after >= p_mastered_min   THEN 'mastered'
        WHEN v_after >= p_learning_min   THEN 'learning'
        WHEN v_after >= p_struggling_min THEN 'struggling'
        ELSE 'unexplored'
    END;

    UPDATE graph_nodes g
       SET mastery_score   = v_after,
           mastery_tier    = v_tier,
           times_studied   = g.times_studied + 1,
           last_studied_at = now()
     WHERE g.id = p_node_id;

    before_score := v_before;
    after_score  := v_after;
    new_tier     := v_tier;
    RETURN NEXT;
END;
$$;

REVOKE ALL ON FUNCTION apply_mastery_delta(
    TEXT, TEXT, DOUBLE PRECISION, DOUBLE PRECISION, DOUBLE PRECISION, DOUBLE PRECISION
) FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format(
                'REVOKE ALL ON FUNCTION apply_mastery_delta(TEXT, TEXT, DOUBLE PRECISION, '
                'DOUBLE PRECISION, DOUBLE PRECISION, DOUBLE PRECISION) FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT EXECUTE ON FUNCTION apply_mastery_delta(
            TEXT, TEXT, DOUBLE PRECISION, DOUBLE PRECISION, DOUBLE PRECISION, DOUBLE PRECISION
        ) TO service_role;
    END IF;
END;
$$;

-- 2. Drop 'subject_root' from the stored tier vocabulary.
UPDATE graph_nodes SET mastery_tier = 'unexplored' WHERE mastery_tier = 'subject_root';

DO $$
DECLARE
    c TEXT;
BEGIN
    -- The 0023 inline CHECK is auto-named; find it by what it checks rather
    -- than trusting the generated name.
    FOR c IN
        SELECT con.conname
          FROM pg_constraint con
         WHERE con.conrelid = 'graph_nodes'::regclass
           AND con.contype = 'c'
           AND pg_get_constraintdef(con.oid) LIKE '%mastery_tier%'
    LOOP
        EXECUTE format('ALTER TABLE graph_nodes DROP CONSTRAINT %I', c);
    END LOOP;
END;
$$;

ALTER TABLE graph_nodes
    ADD CONSTRAINT graph_nodes_mastery_tier_check
    CHECK (mastery_tier IN ('unexplored', 'struggling', 'learning', 'mastered'));
