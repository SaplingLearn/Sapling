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
