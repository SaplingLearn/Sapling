-- 20261108115157_learning_evidence_void_grants.sql
-- Learning loop spec §13 A123: the backend holds SELECT and INSERT only on the
-- two append-only records 20261108072715_learning_evidence_void.sql created,
-- learning_evidence_voids and misconception_attempts.
--
-- That migration revoked PUBLIC, anon and authenticated, and granted
-- service_role SELECT and INSERT. On Supabase that grant changes nothing:
-- Supabase's default privileges already give service_role ALL on every new
-- public table (the 20260928022711_feature_flags.sql note covers the same
-- defaults for anon and authenticated). So service_role kept UPDATE, DELETE,
-- TRUNCATE, REFERENCES and TRIGGER, and the backend could delete a void row.
-- The append-only trigger refuses only an UPDATE. A plain Postgres has no
-- such defaults, which is why the PostgreSQL 16 proof did not show it. The
-- integration lane on the local stack does:
-- test_the_void_record_is_append_only_and_backend_only.
--
-- Nothing else needs the dropped privileges. The backend reads both tables and
-- inserts through the void commit and misconception_record, both SECURITY
-- INVOKER. No code path updates or deletes either table. A foreign-key cascade
-- (from node_mastery_events or misconceptions) runs as the table owner, not as
-- service_role.
--
-- Guarded: a plain Postgres has no service_role. Idempotent: REVOKE ALL, then
-- the same GRANT.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        REVOKE ALL ON TABLE learning_evidence_voids FROM service_role;
        REVOKE ALL ON TABLE misconception_attempts FROM service_role;
        GRANT SELECT, INSERT ON TABLE learning_evidence_voids TO service_role;
        GRANT SELECT, INSERT ON TABLE misconception_attempts TO service_role;
    END IF;
END $$;
