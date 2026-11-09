-- Stateless per-replica state, part 2 (Trov #117): lazy tutor sessions that
-- any replica can see, behind the `stateless_tutor_sessions` flag.
--
-- Why
-- ---
-- A tutor session is "pending" between start-session and its first chat turn:
-- it has no `sessions` row yet (sessions nobody chats in never reach the
-- session list, the achievements or `session.started`). Until now the pending
-- record, its end/delete tombstone and the lock that serialises its
-- materialisation all lived in ONE process (services/tutor_sessions.py:
-- PENDING_SESSIONS, _DISCARDED, materialization_lock). Behind a load balancer
-- with two API replicas, a session started on one and continued on the other
-- 404s, and a session ended on one can be revived on the other.
--
-- What this adds
-- --------------
-- public.tutor_pending_sessions: one row per pending session (state
--   'pending') or per recent discard (state 'ended' / 'deleted', a tombstone).
--   Columns 🔒 are column-encrypted by the backend (services/encryption.py):
--     assistant_reply  encrypt_if_present(greeting) — the SAME format as
--                      messages.content, so materialisation copies it as is.
--   topic / mode / course_id / offering_id / graph_update are plaintext, as
--   they are on `sessions` and `messages` (sessions.topic, graph_update_json).
--   A tombstone keeps only ids, the state and the time (the payload columns
--   are cleared when a session is discarded).
--
-- public.stash_tutor_session(...)          -> boolean (always true)
--   start-session: insert the pending row. In the same call, drop pending
--   rows older than p_ttl_seconds and tombstones older than
--   p_tombstone_ttl_seconds, then evict the oldest pending rows / tombstones
--   so that each stays under p_max_entries — the bounds the in-process store
--   enforces per process (PENDING_TTL_SECONDS, DISCARD_TOMBSTONE_TTL_SECONDS,
--   PENDING_MAX_ENTRIES), now across replicas.
-- public.materialize_tutor_session(p_session_id, p_user_id, p_ttl_seconds,
--                                  p_tombstone_ttl_seconds)
--     -> TABLE (outcome text, session_mode text, session_topic text,
--               session_offering_id text)
--   The first turn: ONE transaction that locks the row (FOR UPDATE), and if it
--   is the caller's live pending session writes the `sessions` row (ON
--   CONFLICT DO NOTHING) and the greeting `messages` row and deletes the
--   pending row. outcome: 'materialized' | 'none' (not pending: never was,
--   expired, or materialised already) | 'foreign' (another user's pending
--   session) | 'ended' / 'deleted' (the caller's tombstone, within its TTL).
--   Atomic, so a row is never half-materialised and the per-process lock is
--   not needed: concurrent turns serialise on the row lock, and the loser
--   sees 'none' and carries on against the row the winner wrote.
-- public.discard_tutor_session(p_session_id, p_user_id, p_reason,
--                              p_only_if_pending, p_ttl_seconds) -> boolean
--   end-session / delete: turn the row into a tombstone (p_reason 'ended' or
--   'deleted'), returning whether the session was still pending (then it has
--   no `sessions` row and the caller is done). With p_only_if_pending a
--   session that is not pending is left alone (end-session of a live session
--   closes the real row instead); without it a tombstone is written anyway
--   (delete), so a turn already past its ownership check on another replica
--   answers 404 instead of writing into a deleted session.
--
-- Reads (ownership, tombstones, resume) and the pending rename are plain
-- PostgREST calls on the table.
--
-- Access: service-only (RLS bucket E, docs/security/rls-step2-plan.md): RLS
-- on, no policies, nothing granted to anon/authenticated; the functions are
-- SECURITY INVOKER with EXECUTE for service_role only. The backend reaches
-- all of it under service_scope (services/tutor_sessions.py).
--
-- Inert until used: nothing reads or writes any of this until the
-- `stateless_tutor_sessions` flag (default off) is turned on. Idempotent
-- (IF NOT EXISTS / OR REPLACE / guarded DO blocks), additive, touches no
-- existing data.
--
-- Reverse (by hand, as the migration role). Turn `stateless_tutor_sessions`
-- off first; sessions still pending in the table are then simply never
-- materialised (their first turn answers 404, as an expired one does today).
--   DROP FUNCTION IF EXISTS public.discard_tutor_session(text, text, text, boolean, integer);
--   DROP FUNCTION IF EXISTS public.materialize_tutor_session(text, text, integer, integer);
--   DROP FUNCTION IF EXISTS public.stash_tutor_session(text, text, text, text, text, text, boolean, text, jsonb, integer, integer, integer);
--   DROP TABLE IF EXISTS public.tutor_pending_sessions;   -- drops its indexes too
-- (Only greetings of sessions nobody has chatted in yet, and short-lived
-- tombstones, are lost.)

CREATE TABLE IF NOT EXISTS public.tutor_pending_sessions (
    session_id         TEXT PRIMARY KEY,
    user_id            TEXT NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    state              TEXT NOT NULL DEFAULT 'pending',
    mode               TEXT,
    topic              TEXT,
    course_id          TEXT,
    offering_id        TEXT,
    use_shared_context BOOLEAN NOT NULL DEFAULT TRUE,
    assistant_reply    TEXT,            -- 🔒 cleared on discard
    graph_update       JSONB,
    stashed_at         TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    discarded_at       TIMESTAMPTZ,
    CONSTRAINT tutor_pending_sessions_state_check
        CHECK (state IN ('pending', 'ended', 'deleted')),
    CONSTRAINT tutor_pending_sessions_pending_shape_check
        CHECK (state <> 'pending' OR (mode IS NOT NULL AND topic IS NOT NULL
                                      AND assistant_reply IS NOT NULL)),
    CONSTRAINT tutor_pending_sessions_tombstone_shape_check
        CHECK (state = 'pending' OR discarded_at IS NOT NULL)
);

COMMENT ON TABLE public.tutor_pending_sessions IS
    'Lazy tutor sessions before their first turn, and end/delete tombstones (#117, stateless_tutor_sessions). Service-only; assistant_reply is column-encrypted.';

-- The users ON DELETE CASCADE and the account wipe look rows up by user.
CREATE INDEX IF NOT EXISTS idx_tutor_pending_sessions_user
    ON public.tutor_pending_sessions (user_id);
-- The TTL sweep and the oldest-first eviction, per state.
CREATE INDEX IF NOT EXISTS idx_tutor_pending_sessions_state_stashed
    ON public.tutor_pending_sessions (state, stashed_at);

-- ── access: service-only ────────────────────────────────────────────────────

ALTER TABLE public.tutor_pending_sessions ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON TABLE public.tutor_pending_sessions FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT ALL ON TABLE public.tutor_pending_sessions TO service_role;
    END IF;
END $$;

-- ── stash_tutor_session ─────────────────────────────────────────────────────

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
    p_max_entries            INTEGER
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
        use_shared_context, assistant_reply, graph_update, stashed_at)
    VALUES (
        p_session_id, p_user_id, 'pending', p_mode, p_topic, p_course_id, p_offering_id,
        COALESCE(p_use_shared_context, TRUE), p_assistant_reply, p_graph_update, v_now);
    RETURN TRUE;  -- a body PostgREST answers with (a void function answers 204, no JSON)
END;
$$;

COMMENT ON FUNCTION public.stash_tutor_session(TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, BOOLEAN, TEXT, JSONB, INTEGER, INTEGER, INTEGER) IS
    'start-session (#117): record a pending tutor session, after the TTL sweep and the oldest-first eviction.';

-- ── materialize_tutor_session ───────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.materialize_tutor_session(
    p_session_id            TEXT,
    p_user_id               TEXT,
    p_ttl_seconds           INTEGER,
    p_tombstone_ttl_seconds INTEGER
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

    INSERT INTO public.sessions (id, user_id, mode, topic, offering_id)
    VALUES (r.session_id, r.user_id, r.mode, r.topic, NULLIF(r.offering_id, ''))
    ON CONFLICT (id) DO NOTHING;

    INSERT INTO public.messages (session_id, role, content, graph_update_json, created_at)
    VALUES (r.session_id, 'assistant', r.assistant_reply, r.graph_update, v_now);

    DELETE FROM public.tutor_pending_sessions t WHERE t.session_id = p_session_id;

    outcome := 'materialized';
    session_mode := r.mode;
    session_topic := r.topic;
    session_offering_id := r.offering_id;
    RETURN NEXT;
END;
$$;

COMMENT ON FUNCTION public.materialize_tutor_session(TEXT, TEXT, INTEGER, INTEGER) IS
    'First tutor turn (#117): atomically write a pending session''s sessions row + greeting and drop the pending row.';

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
            assistant_reply = NULL, graph_update = NULL;

    RETURN v_pending;
END;
$$;

COMMENT ON FUNCTION public.discard_tutor_session(TEXT, TEXT, TEXT, BOOLEAN, INTEGER) IS
    'end-session / delete (#117): leave an ended/deleted tombstone; true when the session was still pending (no sessions row).';

DO $$
DECLARE
    f TEXT;
    r TEXT;
BEGIN
    FOREACH f IN ARRAY ARRAY[
        'public.stash_tutor_session(text, text, text, text, text, text, boolean, text, jsonb, integer, integer, integer)',
        'public.materialize_tutor_session(text, text, integer, integer)',
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
