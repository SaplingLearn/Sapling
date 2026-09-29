-- Learning loop PKG-04, A38 fix round (m1): check_item_draft_failures is
-- backend-only. 20260929050242_learning_check_item_draft_failures.sql created
-- it with no RLS, and PostgREST exposes every public-schema table to the anon
-- key the frontend ships, so anyone holding it could reset a concept's count
-- or stall a course's drafting. RLS with no policy denies every non-bypass
-- role; service_role (the backend) bypasses RLS. Role statements are guarded
-- because those roles are Supabase's: a plain Postgres has none of them, and an
-- unguarded REVOKE naming one aborts the whole migration. Same idiom as
-- 20260929050404_learning_ai_tutor_daily_calls.sql.
ALTER TABLE check_item_draft_failures ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE check_item_draft_failures FROM PUBLIC;
DO $$
DECLARE
    r TEXT;
BEGIN
    FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
            EXECUTE format('REVOKE ALL ON TABLE check_item_draft_failures FROM %I', r);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE check_item_draft_failures TO service_role;
    END IF;
END $$;
