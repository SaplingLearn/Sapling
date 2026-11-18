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
