-- PR #866 Z15: re-seal an append-only prequestion guess without UPDATE.
--
-- learning_prequestions is append-only (spec §13 A138): service_role holds
-- SELECT and INSERT only (20261108184825, restated by 20261109032302), and the
-- integration lane pins that. But `guess_json` is a 🔒 column
-- (services/encryption.ENCRYPTED_COLUMNS), so the AAD backfill
-- (db/backfill_encryption_aad.py, finding M13 phase 3) must re-seal each
-- legacy v1 guess as v2, and an ENCRYPTION_KEY rotation must re-seal every
-- guess. Both rewrote the cell through `encryption_aad_swap`, a SECURITY
-- INVOKER UPDATE run as service_role: refused (42501), so the backfill
-- crashed at this column, the cells after it in the run were never reached,
-- and its dry run never reached the exit-0 gate for
-- ENCRYPTION_LEGACY_READS=refuse.
--
-- learning_prequestion_guess_reseal(id, old_md5, new): the one write a re-seal
-- needs, and nothing else. SECURITY DEFINER, so the UPDATE runs as the owner,
-- and narrowed so it cannot be used to edit a guess:
--   * one cell: learning_prequestions.guess_json, by primary key;
--   * a compare-and-swap: the cell must still hold the value the caller read
--     (md5 of the stored text, the backfill's `_md5`), so a concurrent write
--     is never overwritten (that row is retried on the next run);
--   * only a stored guess, and only by a v2 ciphertext (`enc2:` prefix): it
--     never clears a guess (that is learning_session_text_erase's, C8), never
--     writes one where "no idea" stored none, and never writes plaintext.
-- It cannot check that the new ciphertext seals the same plaintext (the key
-- never reaches the database); service_role, the only role that may call it,
-- already reads every guess and holds the key. The table grants are unchanged.
--
-- Deploy order: before the AAD backfill runs with --apply (it probes the
-- function first and aborts, writing nothing, when it is missing); either
-- side of the code. Idempotent; no data is touched.
-- Reverse (by hand): DROP FUNCTION IF EXISTS
--   learning_prequestion_guess_reseal(text, text, text);

CREATE OR REPLACE FUNCTION learning_prequestion_guess_reseal(
    p_id      text,
    p_old_md5 text,
    p_new     text
)
RETURNS boolean
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_n integer;
BEGIN
    IF p_new IS NULL OR left(p_new, 5) <> 'enc2:' THEN
        RAISE EXCEPTION 'learning_prequestion_guess_reseal: a guess is re-sealed only as a v2 ciphertext';
    END IF;
    UPDATE learning_prequestions
       SET guess_json = p_new
     WHERE id = p_id
       AND guess_json IS NOT NULL
       AND md5(guess_json) = p_old_md5;
    GET DIAGNOSTICS v_n = ROW_COUNT;
    RETURN v_n > 0;
END
$$;

COMMENT ON FUNCTION learning_prequestion_guess_reseal(text, text, text) IS
    'PR #866 Z15: re-seal one learning_prequestions.guess_json as v2 (AAD backfill, key rotation); compare-and-swap; service-only.';

REVOKE ALL ON FUNCTION learning_prequestion_guess_reseal(text, text, text) FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format(
                'REVOKE ALL ON FUNCTION learning_prequestion_guess_reseal(text, text, text) FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT EXECUTE ON FUNCTION learning_prequestion_guess_reseal(text, text, text) TO service_role;
    END IF;
END $$;

-- PostgREST resolves functions from its schema cache; reload it (a no-op with
-- no listener).
NOTIFY pgrst, 'reload schema';
