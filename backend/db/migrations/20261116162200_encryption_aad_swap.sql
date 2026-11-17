-- Compare-and-swap for the AAD backfill (finding M13,
-- docs/security/encryption-aad-plan.md phase 3; db/backfill_encryption_aad.py).
--
-- The backfill re-seals each legacy (v1) 🔒 value as v2, bound to its cell. It
-- must never overwrite a value the live app wrote after the backfill read the
-- row, so the write is conditional on the cell still holding the value it
-- read. A PostgREST `column=eq.<old>` filter cannot carry that condition for a
-- large value (documents.extracted_text runs to megabytes, past any URL limit)
-- or for a JSONB column holding a JSON string (quiz_attempts.questions_json,
-- study_guides.content, ...), so the condition is an md5 of the old value,
-- checked here.
--
-- public.encryption_aad_swap(table, column, pk_column, pk, old_md5, new)
--   UPDATE public.<table> SET <column> = new
--    WHERE <pk_column>::text = pk AND md5(<column> as text) = old_md5
--   -> TRUE when the row was rewritten, FALSE when it changed (or is gone).
-- `new` is stored as TEXT, or as a JSON string for a JSONB column; any other
-- column type is refused. md5 of a JSONB string is taken over the string, not
-- its JSON quoting (`to_jsonb(col) #>> '{}'`), so the caller hashes the value
-- exactly as PostgREST returned it.
--
-- Access: SECURITY INVOKER, EXECUTE for service_role only (it can already
-- write these tables; this adds no privilege). Identifiers go through
-- format('%I'), values through parameters. Inert until the backfill calls it.

CREATE OR REPLACE FUNCTION public.encryption_aad_swap(
    p_table     TEXT,
    p_column    TEXT,
    p_pk_column TEXT,
    p_pk        TEXT,
    p_old_md5   TEXT,
    p_new       TEXT
)
RETURNS BOOLEAN
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
SET search_path = ''
AS $$
DECLARE
    v_rel  REGCLASS := to_regclass(format('public.%I', p_table));
    v_type TEXT;
    v_set  TEXT;
    v_n    INTEGER;
BEGIN
    IF v_rel IS NULL THEN
        RAISE EXCEPTION 'encryption_aad_swap: no table public.%', p_table;
    END IF;
    SELECT format_type(a.atttypid, a.atttypmod) INTO v_type
      FROM pg_catalog.pg_attribute a
     WHERE a.attrelid = v_rel AND a.attname = p_column AND NOT a.attisdropped;
    IF v_type = 'jsonb' THEN
        v_set := 'to_jsonb($1::text)';
    ELSIF v_type = 'text' THEN
        v_set := '$1';
    ELSE
        RAISE EXCEPTION 'encryption_aad_swap: public.%.% is %, not text or jsonb',
            p_table, p_column, coalesce(v_type, 'missing');
    END IF;
    EXECUTE format(
        'UPDATE public.%I SET %I = %s WHERE %I::text = $2 AND md5(to_jsonb(%I) #>> ''{}'') = $3',
        p_table, p_column, v_set, p_pk_column, p_column
    ) USING p_new, p_pk, p_old_md5;
    GET DIAGNOSTICS v_n = ROW_COUNT;
    RETURN v_n > 0;
END;
$$;

COMMENT ON FUNCTION public.encryption_aad_swap(TEXT, TEXT, TEXT, TEXT, TEXT, TEXT) IS
    'AAD backfill (M13): rewrite one 🔒 cell only if it still holds the value read (md5). Service-only.';

DO $$
DECLARE
    f CONSTANT TEXT := 'public.encryption_aad_swap(text, text, text, text, text, text)';
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
