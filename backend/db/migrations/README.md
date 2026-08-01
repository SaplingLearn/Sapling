# Migrations

Raw DDL, applied in filename order by `python -m db.migrate`.

## Naming: use a UTC timestamp

```
YYYYMMDDHHMMSS_short_description.sql
```

Generate the prefix when you create the file:

```bash
date -u +%Y%m%d%H%M%S      # e.g. 20260731224500
```

So: `20260731224500_documents_file_sha256.sql`.

### Why not sequential numbers

The old `NNNN_` scheme claims a number when a branch is **written** but only
validates it when the branch **merges**. Two branches open at the same time
routinely pick the same number, and nobody finds out until merge — or later,
since an unpushed branch is invisible to everyone. One branch hit this twice in
a single lifetime: first against `main`'s `0042`, then against an unpushed
branch already holding `0043`/`0044`.

A timestamp has no shared counter. Two branches would have to be created in the
same second to collide.

## The legacy `NNNN_` files are frozen — never rename them

`schema_migrations.filename` is the ledger's primary key, and
`pending_migrations` treats any basename it has not recorded as unapplied. So
**renaming an applied migration makes the runner apply it again.**

That is not a theoretical problem here. `0021_gradebook.sql` DROPs and
re-CREATEs the enrollment-keyed `assignments` table; re-running it against an
environment that already has data would destroy the gradebook.

The two conventions coexist permanently. Ordering still works, though for a
narrower reason than "timestamps are longer" — sorting is character by
character, so length decides nothing. Every legacy file starts with `0`, every
timestamp this millennium starts with `2`, and `0` < `2`. (A sequential
migration numbered 3000+ would break that, which is another reason the legacy
set is closed.)

## Rules that have not changed

- **Append-only.** Never edit a migration that has been applied anywhere.
  Add a new one.
- **Write idempotent DDL** — `IF NOT EXISTS`, guarded `ALTER`s — so a partially
  applied environment can be reconciled without hand-editing the ledger.
- **Never run DDL in the Supabase dashboard.** Schema lives here, in version
  control. `0039_rag_vector_store.sql` exists because that rule was broken and
  the RAG vector store had to be recovered into code afterwards.

## Applying

```bash
python -m db.migrate              # apply pending
python -m db.migrate --baseline   # record as applied WITHOUT running
```

`db/` scripts read `.env` by default. For staging/prod, run them under
`dotenv -f .env.staging run -- python -m db.migrate` so they hit the right
project.

On Windows, set `PYTHONUTF8=1` — the runner reads files with the platform
default encoding otherwise and dies on a non-cp1252 migration.

## Guards

`tests/test_migration_naming.py` fails if a new `NNNN_` file appears or a
prefix is unsortable. `tests/test_migrations.py` pins apply order, including
the three legacy duplicate-prefix pairs whose order is load-bearing.
