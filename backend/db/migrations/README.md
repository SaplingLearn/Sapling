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

### The one case where a new `NNNN_` file is correct

The same primary-key fact cuts the other way when the ledger records a filename
the repo does not have — an "orphan", meaning that environment ran SQL this repo
has never seen. `migrate-staging.yml`'s preflight refuses to apply anything on
top of that, so the backlog freezes until it is reconciled.

Because the ledger keys on basename, the only fix that does not involve
hand-editing a live ledger is to restore the file under the **exact recorded
name**. A timestamped name would leave the orphan in place *and* re-run the DDL.

Three files exist for this reason — `0019_newsletter_approved_at.sql`,
`0032_retire_summer_2026.sql`, `0033_offering_section_not_null.sql` — which is
why the frozen count is 48 rather than 45. These are recovered history, not
newly claimed numbers: the numbers were already spoken for by rows in a
production ledger, so they carry none of the concurrent-branch collision risk
the timestamp convention exists to prevent.

Recovering an orphan is the *only* sanctioned reason to add an `NNNN_` file.
`tests/test_migration_naming.py` pins the count at 48 so anything else fails CI.

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
