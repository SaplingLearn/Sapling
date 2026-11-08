# RLS step 2 draft SQL (not migrations)

These files are **drafts** for the plan in `../rls-step2-plan.md`. They are NOT in `backend/db/migrations/` and are never applied by `db/migrate.py`. Each one becomes a real, timestamp-prefixed migration in its own PR, in the order the plan's section 6.1 gives:

| Draft | Becomes | What it does |
| --- | --- | --- |
| `m1_app_auth_helpers.sql` | step 2a | `app_auth.uid()` and the membership helpers; revoke function EXECUTE from PUBLIC/anon/authenticated |
| `m2_policies.sql` | step 2b | 137 policies, all `TO authenticated`, keyed on `app_auth.uid()` (no effect until 2c grants) |
| `m3_grants.sql` | step 2c | table and column grants to `authenticated` |
| `verify.sql` | test aid | cross-user checks used on the scratch PG 16 replay |
| `gen_policies.py` | generator | produces `m2_policies.sql` |

They were validated on a scratch PostgreSQL 16 cluster with stub Supabase roles, not on a real Supabase stack (prod and `supabase/config.toml` are PG 15). Re-verify on the local Supabase stack before turning any of them into a migration.
