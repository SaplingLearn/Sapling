-- 20261111030019_learning_account_erase.sql
-- The admin account wipe (services/account_wipe.py::wipe_account_data) erases
-- a student's learning-loop rows. Owner decision: every row the student owns
-- in every learning-loop table goes; the users row stays, so the loop tables'
-- `REFERENCES users(id) ON DELETE CASCADE` never fires for a wipe.
--
-- The wipe reaches PostgREST as service_role. That role holds DELETE on every
-- student-keyed loop table except the two teach-prompt records, which
-- 20261108184825_learning_teach_prompts.sql and 20261109032302_learning_loop_rls.sql
-- narrowed on purpose: learning_prequestions is SELECT + INSERT,
-- learning_self_explanations SELECT + INSERT + UPDATE. No request path may
-- delete from either, and that stays true. This function is the one sanctioned
-- erase of them: it deletes exactly one student's rows from those two tables
-- and nothing else, and returns how many it deleted.
--
-- SECURITY DEFINER, so it runs as its owner (the migration role, which owns
-- both tables and so is not subject to their RLS), with search_path pinned.
-- EXECUTE: service_role only (the 20261109032302 posture for every loop
-- function); PUBLIC, anon and authenticated hold nothing, so it is never
-- reachable through /rest/v1/rpc with a user's token.
--
-- learning_evidence_voids and misconception_attempts (SELECT + INSERT only as
-- well) need no function: their rows go by their ON DELETE CASCADE, from
-- node_mastery_events (itself cascaded from graph_nodes) and misconceptions,
-- both of which the wipe deletes. A cascade runs as the table owner.
--
-- Idempotent (CREATE OR REPLACE; the grants are re-stated). No data is touched
-- by applying it. Reverse: DROP FUNCTION learning_account_erase(text).

CREATE OR REPLACE FUNCTION learning_account_erase(p_user_id text)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    n_self_explanations bigint;
    n_prequestions bigint;
BEGIN
    IF p_user_id IS NULL OR btrim(p_user_id) = '' THEN
        RAISE EXCEPTION 'learning_account_erase needs a user id';
    END IF;
    DELETE FROM learning_self_explanations WHERE user_id = p_user_id;
    GET DIAGNOSTICS n_self_explanations = ROW_COUNT;
    DELETE FROM learning_prequestions WHERE user_id = p_user_id;
    GET DIAGNOSTICS n_prequestions = ROW_COUNT;
    RETURN jsonb_build_object(
        'learning_self_explanations', n_self_explanations,
        'learning_prequestions', n_prequestions
    );
END
$$;

REVOKE ALL ON FUNCTION learning_account_erase(text) FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON FUNCTION learning_account_erase(text) FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT EXECUTE ON FUNCTION learning_account_erase(text) TO service_role;
    END IF;
END $$;

-- PostgREST resolves functions from its schema cache; reload it (a no-op with
-- no listener).
NOTIFY pgrst, 'reload schema';
