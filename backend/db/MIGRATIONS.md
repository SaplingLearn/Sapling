# Database migrations (#197)

Ordering used to live only in prose inside each `migration_*.sql` header
("Run once…", "needs `documents` first"), which is a drift hazard: a fresh
environment applying files alphabetically can fail or silently skip FKs. This
directory now has an explicit, tested order and an applied-migration ledger.

## How it works

- **Baseline** — `supabase_schema.sql` is the canonical full snapshot. Apply it
  first when standing up a brand-new database.
- **Ledger** — `schema_migrations(version, applied_at)` records which
  incremental migrations have run (`migration_schema_migrations.sql`, or created
  automatically by the runner).
- **Runner** — `db/migrate.py` holds the ordered `MANIFEST` and applies any
  pending migration exactly once, in order.

```bash
# from backend/
python -m db.migrate --status     # list applied / pending (no DB writes)
python -m db.migrate --apply      # apply pending migrations in order
```

`--apply` needs a direct Postgres connection (the PostgREST client can't run
DDL): set `DATABASE_URL` and `pip install 'psycopg[binary]'`. `--status`
without `DATABASE_URL` just prints the manifest order.

## Adding a migration

1. Add `migration_<name>.sql` here. Make it idempotent
   (`CREATE … IF NOT EXISTS`, and guard `ADD CONSTRAINT` behind a
   `pg_constraint` `IF NOT EXISTS` check — see `migration_gradebook.sql`).
2. Append its filename to the **end** of `MANIFEST` in `db/migrate.py` (or
   earlier if it has a hard dependency, like the legacy-grade drop preceding the
   gradebook rebuild).
3. Mirror the change into `supabase_schema.sql` so fresh databases match.

`tests/test_migration_runner.py` fails if a `migration_*.sql` file is missing
from `MANIFEST`, so step 2 can't be forgotten silently.
