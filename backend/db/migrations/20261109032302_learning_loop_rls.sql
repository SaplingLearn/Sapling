-- 20261109032302_learning_loop_rls.sql
-- Learning loop spec §13 A148: every table the learning loop's migrations
-- create holds main's backend-only posture (RLS step 2, #115, bucket E).
--
-- Why
-- ---
-- Main's lockdown (20261108082151_rls_on_every_table.sql) enables RLS on every
-- public table and revokes anon/authenticated, and step 2a
-- (20261108092633_rls_app_auth_helpers.sql) revokes function EXECUTE from
-- PUBLIC/anon/authenticated. Both loop over what exists WHEN THEY RUN. On a
-- fresh database the files run in name order, so the loop's tables created
-- before 20261108082151 are covered and the rest rely on the default
-- privileges those two set. Production meets the other order: main's RLS
-- migrations ran first, and the loop's migrations (all pending there) run
-- after them. learner_state and check_items never enabled RLS in their own
-- migrations, so there they would stay open to any role that held a grant.
-- This migration states the posture explicitly, last in both orders, so the
-- end state does not depend on which ran first.
--
-- What it does, for the 19 loop tables (every CREATE TABLE in the loop's
-- *_learning_* and checklist_budget migrations):
--   1. ENABLE ROW LEVEL SECURITY. No policy is added and any found is a
--      failure: bucket E is service-only, a role without BYPASSRLS sees no row.
--   2. REVOKE ALL from PUBLIC, anon and authenticated (tables and their
--      sequences). The 20261108094130 step-2c grant list is unchanged:
--      authenticated holds nothing on any loop table.
--   3. service_role: ALL, as main grants every backend-only table, EXCEPT the
--      four records the loop deliberately narrowed (A123, A138, A139): the
--      append-only learning_evidence_voids, misconception_attempts and
--      learning_prequestions keep SELECT + INSERT, learning_self_explanations
--      SELECT + INSERT + UPDATE (the reply closes the row). Restated here
--      (REVOKE ALL first, as 20261108115157 does) so neither order of apply
--      can leave service_role holding UPDATE or DELETE on an append-only
--      record. tests/integration/test_rls_lockdown_db.py pins this exception
--      list exactly; every other public table still needs full access.
--   4. Every function the loop's migrations create (all overloads, by name):
--      no EXECUTE for PUBLIC, anon or authenticated; EXECUTE for service_role.
--      Trigger functions included, as step 2a does (a trigger needs no EXECUTE
--      to fire).
--   5. `authenticated` gets A136's `extra_float_digits = 3`. A136
--      (20261108162223_learning_exact_floats.sql) set it on service_role
--      because the backend reached PostgREST as service_role only, and its
--      own rule says any other role PostgREST runs the backend as needs the
--      same. Main's `db_user_scope` flag (RLS step 2, shadow/enforce) now runs
--      a request's reads as `authenticated` (a backend-minted JWT): without
--      this, a user-scoped read of a float column would come back rounded to
--      15 significant digits (real: 6), which A136 showed can flip a decision
--      (a documents.shareability_confidence just under the share floor read
--      as the floor). anon and authenticator keep the server default.
--
-- Why it is inert for the backend: it reaches PostgREST as service_role
-- (BYPASSRLS), which keeps exactly the privileges the loop already used; the
-- migration runner, oracles and integration lane connect as `postgres`, the
-- owner. Under the `db_user_scope` flag the loop's reads and writes of these
-- tables run as service (the loop router is a service route, and every loop
-- store reached from a user-scoped route is @runs_as_service).
--
-- Guarded like main's role-touching migrations: role statements are skipped on
-- a bare Postgres without the Supabase roles. Idempotent: every statement is
-- safe to re-run. A missing table fails the migration (rolled back), which is
-- the right outcome for schema drift. No data is touched.
--
-- Reverse (by hand, as the migration role): nothing to restore — before this
-- ran the same tables were either already in this state (fresh databases) or
-- open by omission (learner_state, check_items in production order), which is
-- not a state worth restoring. To drop the explicit service_role narrowing,
-- re-run the GRANTs of 20261108115157 / 20261108184825 as they stand.

DO $$
DECLARE
    t        TEXT;
    r        TEXT;
    s        TEXT;
    fn       TEXT;
    n        INTEGER;
    tables   CONSTANT TEXT[] := ARRAY[
        'learner_state',
        'check_items',
        'check_item_draft_failures',
        'ai_tutor_daily_calls',
        'misconceptions',
        'posttest_poses',
        'learning_reveals',
        'quiz_evidence_claims',
        'checklist_budget_accounts',
        'checklist_budget_reservations',
        'learning_evidence_operations',
        'check_item_reports',
        'check_item_reviews',
        'learning_evidence_voids',
        'misconception_attempts',
        'check_item_audits',
        'posttest_skips',
        'learning_prequestions',
        'learning_self_explanations'
    ];
    functions CONSTANT TEXT[] := ARRAY[
        'ai_budget_bump_tutor_calls',
        'check_item_hold_flags',
        'check_item_report',
        'check_item_report_quarantine',
        'check_item_review_decide',
        'check_items_staff_hold',
        'checklist_budget_admit',
        'checklist_budget_read',
        'checklist_budget_reconcile',
        'checklist_budget_start',
        'learning_bump_evidence_version',
        'learning_evidence_commit',
        'learning_evidence_receipt',
        'learning_evidence_snapshot',
        'learning_evidence_void_commit',
        'learning_evidence_void_pending',
        'learning_evidence_void_snapshot',
        'learning_evidence_voids_append_only',
        'learning_float_probe',
        'misconception_record',
        'misconception_rollup',
        'posttest_anchors'
    ];
    has_service CONSTANT BOOLEAN := EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role');
BEGIN
    -- 1-3: tables
    FOREACH t IN ARRAY tables LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);

        SELECT count(*) INTO n FROM pg_policies WHERE schemaname = 'public' AND tablename = t;
        IF n > 0 THEN
            RAISE EXCEPTION 'learning loop table % has % RLS polic(ies); it is service-only', t, n;
        END IF;

        EXECUTE format('REVOKE ALL ON TABLE public.%I FROM PUBLIC', t);
        FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                EXECUTE format('REVOKE ALL ON TABLE public.%I FROM %I', t, r);
            END IF;
        END LOOP;

        IF has_service THEN
            IF t IN ('learning_evidence_voids', 'misconception_attempts', 'learning_prequestions') THEN
                EXECUTE format('REVOKE ALL ON TABLE public.%I FROM service_role', t);
                EXECUTE format('GRANT SELECT, INSERT ON TABLE public.%I TO service_role', t);
            ELSIF t = 'learning_self_explanations' THEN
                EXECUTE format('REVOKE ALL ON TABLE public.%I FROM service_role', t);
                EXECUTE format('GRANT SELECT, INSERT, UPDATE ON TABLE public.%I TO service_role', t);
            ELSE
                EXECUTE format('GRANT ALL ON TABLE public.%I TO service_role', t);
            END IF;
        END IF;

        -- the table's own sequences (an identity or serial column)
        FOR s IN
            SELECT seq.relname
              FROM pg_depend d
              JOIN pg_class seq ON seq.oid = d.objid AND seq.relkind = 'S'
             WHERE d.refobjid = format('public.%I', t)::regclass
               AND d.deptype IN ('a', 'i')
        LOOP
            FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                    EXECUTE format('REVOKE ALL ON SEQUENCE public.%I FROM %I', s, r);
                END IF;
            END LOOP;
            IF has_service THEN
                EXECUTE format('GRANT ALL ON SEQUENCE public.%I TO service_role', s);
            END IF;
        END LOOP;
    END LOOP;

    -- 4: functions (every overload; extension members never match these names)
    FOR fn IN
        SELECT p.oid::regprocedure::text
          FROM pg_proc p
         WHERE p.pronamespace = 'public'::regnamespace
           AND p.proname = ANY (functions)
         ORDER BY 1
    LOOP
        EXECUTE format('REVOKE EXECUTE ON ROUTINE %s FROM PUBLIC', fn);
        FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                EXECUTE format('REVOKE EXECUTE ON ROUTINE %s FROM %I', fn, r);
            END IF;
        END LOOP;
        IF has_service THEN
            EXECUTE format('GRANT EXECUTE ON ROUTINE %s TO service_role', fn);
        END IF;
    END LOOP;
END $$;

-- 5: the role a user-scoped request runs as reads floats exactly (A136).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        ALTER ROLE authenticated SET extra_float_digits = 3;
    END IF;
END $$;

-- PostgREST caches table privileges in its schema cache and applies role
-- settings from its config cache; reload both (no-ops with no listener).
NOTIFY pgrst, 'reload schema';
NOTIFY pgrst, 'reload config';
