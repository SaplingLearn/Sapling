# RLS step 2 SQL: drafts and generator

These files back the plan in `../rls-step2-plan.md`. They are not in `backend/db/migrations/` and `db/migrate.py` never applies them. Each step became a real, timestamp-prefixed migration, in the order the plan's section 6.1 gives:

| File | Migration | What it does |
| --- | --- | --- |
| `m1_app_auth_helpers.sql` | step 2a, `20261108092633_rls_app_auth_helpers.sql` | `app_auth.uid()` and the membership helpers; revoke function EXECUTE from PUBLIC/anon/authenticated. The migration differs from this draft (see its header). |
| `m2_policies.sql` | step 2b, `20261108094129_rls_policies.sql` | 137 policies, all `TO authenticated`, keyed on `app_auth.uid()` (no effect until 2c grants). Same body as the migration. |
| `m3_grants.sql` | step 2c, `20261108094130_rls_authenticated_grants.sql` | table, column and function grants to `authenticated`. Same body as the migration. |
| `verify.sql` | test aid | the original scratch-replay cross-user checks; superseded by `backend/tests/integration/test_rls_policies_db.py` |
| `gen_policies.py` | generator | the bucket inventory, and the bodies of `m2`/`m3` and both migrations, plus their reverse SQL |

`python docs/security/rls-step2/gen_policies.py check < tables.txt` fails if a public table is in no bucket. `backend/tests/integration/test_rls_policies_db.py` runs the same check against the live schema.

The step 2b and 2c migrations were verified on a throwaway `supabase/postgres:15.8.1.085` container: full chain replay, both applied twice, then the integration modules run against it. A migration is immutable once applied, so a later change to the generator ships as a new migration.
