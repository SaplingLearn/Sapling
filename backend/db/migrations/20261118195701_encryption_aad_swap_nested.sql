-- Compare-and-swap for the AAD backfill's NESTED ciphertexts (finding M13,
-- docs/security/encryption-aad-plan.md phase 3; PR #866 review fix C6;
-- db/backfill_encryption_aad.py).
--
-- services/encryption.py::NESTED_CIPHERTEXTS names ciphertexts stored INSIDE a
-- plaintext JSONB column: the learning loop's goal text
-- (loop_state.goal.text_encrypted) and a step's or probe's sealed grade
-- checkpoint (…grade_checkpoint), both bound to their session with
-- `nested_bind`. They live in sessions.loop_state and, for a lazy loop
-- session not yet materialised, in tutor_pending_sessions.loop_state (the
-- same ciphertext, copied by SQL at materialisation: it is bound to the
-- session id, which both rows key on). The column-level swap
-- (20261116162200_encryption_aad_swap.sql) rewrites a whole cell, so it cannot
-- re-seal one value inside a document; this one can.
--
-- public.encryption_aad_swap_nested(table, pk, path, old_md5, new)
--   UPDATE <table> SET loop_state = jsonb_set(loop_state, path, to_jsonb(new))
--    WHERE <pk> = pk AND loop_state #> path is a JSON string
--      AND md5(loop_state #>> path) = old_md5
--   -> TRUE when the value was rewritten, FALSE when it changed (or is gone).
-- Only the value at `path` changes; the rest of the document is the row's as
-- it stands at the UPDATE (row-locked), so a concurrent app write elsewhere in
-- the document is never lost. On sessions the write also bumps
-- loop_state_rev, the app's compare-and-set revision
-- (learning/loop_state_store.py::save_loop_state): a turn that read the
-- document before the swap loses its CAS and re-applies to the re-sealed one
-- instead of writing the old value back. Only the two holder tables are
-- accepted; anything else raises.
--
-- Access: SECURITY INVOKER, EXECUTE for service_role only (it can already
-- write both tables; this adds no privilege), the 20261116162200 posture.
-- Inert until the backfill calls it.

CREATE OR REPLACE FUNCTION public.encryption_aad_swap_nested(
    p_table   TEXT,
    p_pk      TEXT,
    p_path    TEXT[],
    p_old_md5 TEXT,
    p_new     TEXT
)
RETURNS BOOLEAN
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path = ''
AS $$
DECLARE
    v_n INTEGER;
BEGIN
    IF p_path IS NULL OR cardinality(p_path) = 0 THEN
        RAISE EXCEPTION 'encryption_aad_swap_nested: an empty path';
    END IF;
    IF p_table = 'sessions' THEN
        UPDATE public.sessions
           SET loop_state = pg_catalog.jsonb_set(loop_state, p_path, pg_catalog.to_jsonb(p_new), false),
               loop_state_rev = loop_state_rev + 1
         WHERE id::text = p_pk
           AND pg_catalog.jsonb_typeof(loop_state #> p_path) = 'string'
           AND pg_catalog.md5(loop_state #>> p_path) = p_old_md5;
    ELSIF p_table = 'tutor_pending_sessions' THEN
        UPDATE public.tutor_pending_sessions
           SET loop_state = pg_catalog.jsonb_set(loop_state, p_path, pg_catalog.to_jsonb(p_new), false)
         WHERE session_id::text = p_pk
           AND pg_catalog.jsonb_typeof(loop_state #> p_path) = 'string'
           AND pg_catalog.md5(loop_state #>> p_path) = p_old_md5;
    ELSE
        RAISE EXCEPTION 'encryption_aad_swap_nested: public.% holds no nested ciphertext', p_table;
    END IF;
    GET DIAGNOSTICS v_n = ROW_COUNT;
    RETURN v_n > 0;
END;
$$;

COMMENT ON FUNCTION public.encryption_aad_swap_nested(TEXT, TEXT, TEXT[], TEXT, TEXT) IS
    'AAD backfill (M13): re-seal one ciphertext inside a loop_state document only if it still holds the value read (md5). Service-only.';

DO $$
DECLARE
    f CONSTANT TEXT := 'public.encryption_aad_swap_nested(text, text, text[], text, text)';
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
