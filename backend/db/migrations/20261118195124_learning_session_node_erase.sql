-- 20261118195124_learning_session_node_erase.sql
-- PR #866 review fixes C8 and C9: the two append-only teach-prompt records
-- (learning_prequestions, learning_self_explanations; spec §13 A138/A139,
-- 20261108184825_learning_teach_prompts.sql) outlived what they belong to.
-- service_role holds no DELETE on either (and no UPDATE on prequestions)
-- since 20261109032302_learning_loop_rls.sql, and that stays true: as in
-- 20261111030019_learning_account_erase.sql, two SECURITY DEFINER functions,
-- EXECUTE for service_role only, are the one sanctioned way to touch them.
--
-- C8 — a deleted tutor session kept the student's own words: the guess they
-- typed at a prequestion (guess_json) and their self-explanation reply
-- (reply_text), both encrypted, keyed by the session. The session delete
-- (services/tutor/sessions.py::delete_session) now clears that TEXT for the
-- session through learning_session_text_erase(user, session). The row stays:
-- an answered prequestion is a release that A76's re-check rule reads for its
-- window across sessions (learning/misconceptions.py::recheck_after_release,
-- through learning/prequestion_store.py::releases: format, difficulty and
-- answered_at only), so deleting it would let a session delete turn a
-- re-check into fresh evidence; a self-explanation row keeps its status and
-- reply length for the admin report. `text_erased_at` records the erase, and
-- each table's text CHECK now allows the cleared state for an erased row only:
--   learning_prequestions:      no_idea = (guess_json IS NULL), or erased with
--                               guess_json NULL;
--   learning_self_explanations: (status = 'replied') = (reply_text IS NOT NULL),
--                               or erased with reply_text NULL.
-- Every other CHECK of both tables is unchanged.
--
-- C9 — a deleted concept node left its teach-prompt rows behind (node_id, no
-- FK). graph_service.delete_node now removes them through
-- learning_node_erase(user, node), with the node's post-test rows
-- (posttest_poses/posttest_skips, which service_role may delete directly).
-- No re-check can need them: a grade is always on a live node, and a node
-- re-added for the same concept is a new node id.
--
-- Both functions are owner-scoped (user AND session/node), refuse a blank id,
-- touch exactly the two tables, and return a count per table. Idempotent:
-- ADD COLUMN IF NOT EXISTS, a constraint swap guarded by name and by
-- definition, CREATE OR REPLACE, grants re-stated. No data is touched by
-- applying it. Reverse (by hand): drop the two functions; restore the two
-- original CHECKs once no row has text_erased_at set; drop the columns.

ALTER TABLE public.learning_prequestions ADD COLUMN IF NOT EXISTS text_erased_at timestamptz;
ALTER TABLE public.learning_self_explanations ADD COLUMN IF NOT EXISTS text_erased_at timestamptz;

DO $$
DECLARE
    v_name TEXT;
BEGIN
    -- The original, unnamed text CHECKs, found by their definition.
    FOR v_name IN
        SELECT c.conname FROM pg_constraint c
         WHERE c.conrelid = 'public.learning_prequestions'::regclass AND c.contype = 'c'
           AND pg_get_constraintdef(c.oid) ~ 'no_idea = \(guess_json IS NULL\)'
           AND c.conname <> 'learning_prequestions_guess_check'
    LOOP
        EXECUTE format('ALTER TABLE public.learning_prequestions DROP CONSTRAINT %I', v_name);
    END LOOP;
    FOR v_name IN
        SELECT c.conname FROM pg_constraint c
         WHERE c.conrelid = 'public.learning_self_explanations'::regclass AND c.contype = 'c'
           AND pg_get_constraintdef(c.oid) ~ 'reply_text IS NOT NULL'
           AND c.conname <> 'learning_self_explanations_reply_check'
    LOOP
        EXECUTE format('ALTER TABLE public.learning_self_explanations DROP CONSTRAINT %I', v_name);
    END LOOP;

    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'learning_prequestions_guess_check'
                      AND conrelid = 'public.learning_prequestions'::regclass) THEN
        ALTER TABLE public.learning_prequestions ADD CONSTRAINT learning_prequestions_guess_check
            CHECK (CASE WHEN text_erased_at IS NULL THEN no_idea = (guess_json IS NULL)
                        ELSE guess_json IS NULL END);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'learning_self_explanations_reply_check'
                      AND conrelid = 'public.learning_self_explanations'::regclass) THEN
        ALTER TABLE public.learning_self_explanations ADD CONSTRAINT learning_self_explanations_reply_check
            CHECK (CASE WHEN text_erased_at IS NULL THEN (status = 'replied') = (reply_text IS NOT NULL)
                        ELSE reply_text IS NULL END);
    END IF;
END $$;

-- C8: one session's typed text, cleared; the rows stay.
CREATE OR REPLACE FUNCTION learning_session_text_erase(p_user_id text, p_session_id text)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    n_self_explanations bigint;
    n_prequestions bigint;
BEGIN
    IF p_user_id IS NULL OR btrim(p_user_id) = ''
       OR p_session_id IS NULL OR btrim(p_session_id) = '' THEN
        RAISE EXCEPTION 'learning_session_text_erase needs a user id and a session id';
    END IF;
    UPDATE learning_self_explanations
       SET reply_text = NULL, text_erased_at = clock_timestamp()
     WHERE user_id = p_user_id AND session_id = p_session_id AND reply_text IS NOT NULL;
    GET DIAGNOSTICS n_self_explanations = ROW_COUNT;
    UPDATE learning_prequestions
       SET guess_json = NULL, text_erased_at = clock_timestamp()
     WHERE user_id = p_user_id AND session_id = p_session_id AND guess_json IS NOT NULL;
    GET DIAGNOSTICS n_prequestions = ROW_COUNT;
    RETURN jsonb_build_object(
        'learning_self_explanations', n_self_explanations,
        'learning_prequestions', n_prequestions
    );
END
$$;

-- C9: one deleted node's teach-prompt rows, removed.
CREATE OR REPLACE FUNCTION learning_node_erase(p_user_id text, p_node_id text)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    n_self_explanations bigint;
    n_prequestions bigint;
BEGIN
    IF p_user_id IS NULL OR btrim(p_user_id) = ''
       OR p_node_id IS NULL OR btrim(p_node_id) = '' THEN
        RAISE EXCEPTION 'learning_node_erase needs a user id and a node id';
    END IF;
    DELETE FROM learning_self_explanations WHERE user_id = p_user_id AND node_id = p_node_id;
    GET DIAGNOSTICS n_self_explanations = ROW_COUNT;
    DELETE FROM learning_prequestions WHERE user_id = p_user_id AND node_id = p_node_id;
    GET DIAGNOSTICS n_prequestions = ROW_COUNT;
    RETURN jsonb_build_object(
        'learning_self_explanations', n_self_explanations,
        'learning_prequestions', n_prequestions
    );
END
$$;

REVOKE ALL ON FUNCTION learning_session_text_erase(text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION learning_node_erase(text, text) FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON FUNCTION learning_session_text_erase(text, text) FROM %I', r);
            EXECUTE format('REVOKE ALL ON FUNCTION learning_node_erase(text, text) FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT EXECUTE ON FUNCTION learning_session_text_erase(text, text) TO service_role;
        GRANT EXECUTE ON FUNCTION learning_node_erase(text, text) TO service_role;
    END IF;
END $$;

-- PostgREST resolves functions and columns from its schema cache; reload it
-- (a no-op with no listener).
NOTIFY pgrst, 'reload schema';
