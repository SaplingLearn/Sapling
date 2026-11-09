# Promotion runbook

`make promote` — staging (`main`) to production. Replaces the hand-run sequence
that shipped #515.

## Before you run it

- Production's `SUPABASE_DB_URL` in `backend/.env.production` must be the
  SESSION-mode pooler URI. Build it:
  `python scripts/pooler_url.py .env.production aws-0-us-west-2 --raw`
- `STAGING_SUPABASE_DB_URL` must be set (staging is on the `aws-1-us-west-2`
  cluster) so the runner can refuse DDL that staging has never executed. If it
  is unset and migrations are pending, preflight **blocks** with a
  `staging-unknown` finding rather than guessing — `--skip-staging-check` is the
  deliberate override.
- `gh` must be authenticated.
- A `pg_dump` must be reachable for the pre-migrate backup (stage 2): either
  a host `pg_dump`/`pg_restore` at least as new as the server (15), or
  `podman`/`docker` for the container fallback. See "Backups" below.
- Run it from a checkout of `main` that is up to date. Preflight **blocks** if
  the local `db/migrations/` differs from `origin/main` in any way (modified,
  missing or extra tracked files, or untracked strays) — the thing being
  promoted is `origin/main`, and both the audit and `db.migrate` read local
  files. Fix: `git checkout main && git pull`, remove stray files, re-run.
- If production carries a hotfix/revert that was never back-merged to `main`,
  preflight **blocks** (`production-diverged`): back-merge production into
  main first, or the merge would fail only after migrations had applied.
  Neither of these two guards has an override flag. Production-only commits
  that change no content do NOT block (#666): step 7's merge commit exists
  only on `production`, but its tree is the `main` commit it merged, so the
  next run needs no zero-file back-merge. The test is exact: `production`'s
  tree must equal the tree of its (single) merge base with `main`.

## What it does

1. **Preflight** (read-only): local `db/migrations/` matches `origin/main`,
   production carries no content main lacks, target-identity, ledger exists, no
   orphans, staging-ran-it-first, no destructive DDL, something to promote.
2. **Backup** production: a full `pg_dump -Fc` (schema + data) into
   `backups/prod-<UTC>.dump`, validated with `pg_restore --list`. If the dump
   fails, or is not a plausible archive (too small, wrong magic, no table
   data), the run **stops here** with exit 1 and production untouched. See
   "Backups" below.
3. **Snapshot** production.
4. **Migrate** production (`db.migrate`) — this is the irreversible step.
5. **Snapshot** again and print the diff.
6. **Pause** — the only prompt. By this point the migration in step 4 has
   already run and cannot be undone; this confirms the merge, not the
   database change. Ctrl-C or a closed stdin here counts as answering `n`.
7. **Merge** `main` → `production`, **pinned to the SHA preflight audited**
   (`gh --match-head-commit`): commits that land on main while you sit at the
   prompt were never scanned, so GitHub itself rejects the merge and the
   runner fails fast telling you to re-run — that rejection is deterministic
   and does not burn the retry loop, which exists only for the known
   transient `gh` 502.
8. **Wait** until `/api/health` reports the merge commit now on
   `origin/production` — not main's tip, which is never what gets deployed
   (10 min timeout). Three outcomes: verified (proceed), timeout (**no**
   smoke — a deploy failure must not read as a smoke failure), or, when the
   whole window reports commit `unknown` (the host injects no SHA),
   **UNVERIFIED**: smoke still runs, but the completion line says the deploy
   itself was never confirmed.
9. **Smoke** the live surface.

If there are pending migrations but no new commits to promote (production's
code already matches main — see "Re-running" below), steps 6-8 are skipped
entirely after step 5: `gh pr create` would fail outright with "No commits
between production and main". Step 9 (smoke) still runs, since a migration
that broke the running app is exactly the failure that stage exists to catch.

Exit codes: `0` success or nothing to promote, `1` failure, `2` you declined.

Flags: `--verify-only` (stages 8-9 only; no backup, it touches no database),
`--allow-destructive`, `--skip-staging-check`, `--yes`, `--skip-backup`
(dangerous, see "Backups").

## The ordering you need to know about

Migrations apply **before** the code merges. Between stages 4 and 7 the OLD
production code runs against the NEW schema. Additive DDL is fine there;
destructive DDL is not, which is why preflight blocks on it and
`--allow-destructive` is an explicit decision.

**If you answer `n` at the prompt (or Ctrl-C it), the migrations are already
applied.** Production's schema will be ahead of its code. Re-running resumes at
the merge. The same is true when the merge is rejected because main moved:
re-run to audit and promote the new tip.

## When smoke fails

Nothing is reverted, deliberately: the migrations cannot be rolled back, so
reverting the code would leave old code against a newer schema. When this run
merged code, the runner prints the revert command; reverting is your call. On
runs that merged nothing (migrations-only, or `--verify-only`) there is no
revert recipe — production's HEAD is a previous promotion's merge commit, and
reverting it would undo an unrelated, previously-working deploy.

## Re-running

Safe. Preflight is read-only and `db.migrate` skips what the ledger already
records, so a re-run after a failure repeats no work.

If the promotion already merged and you only want to re-check the live deploy —
the deploy was slow, smoke failed and you have since fixed something, or the
run failed after the merge landed (the runner points at this flag itself in
that case) — use:

```
make promote ARGS="--verify-only"
```

That skips preflight, snapshots, migrate and the merge entirely, and runs only
the deploy wait against `origin/production`'s tip followed by smoke. A plain
re-run would instead report `nothing-to-promote` and exit 0 without re-checking
anything, because by then there is genuinely nothing left to promote.

## Backups

Production and staging are on the Supabase **Free plan: no platform backups,
no point-in-time recovery.** A dump this tooling takes is the only way back
from a bad migration, so stage 2 of every promotion that gets past preflight
takes one before anything changes. (A run that preflight blocks, or that has
nothing to promote, dumps nothing; `--verify-only` touches no database and
dumps nothing.)

Take one by hand at any time — before a backfill, a manual fix, or a risky
admin operation:

```
make backup-db ENV=prod       # reads SUPABASE_DB_URL from backend/.env.production
make backup-db ENV=staging    # ... from backend/.env.staging
make backup-db ENV=local      # the local Supabase stack (127.0.0.1:${SUPABASE_DB_PORT:-54322})
```

Both paths run `promotion/backup.py` (`python -m promotion.backup --env <env>`
with `SUPABASE_DB_URL` set). It refuses a mislabelled target: `--env local`
must be a loopback database, `prod`/`staging` must not be.

**What you get.** `backups/<env>-<UTC timestamp>.dump` at the repo root
(gitignored, directory `0700`, file `0600`): `pg_dump --format=custom` of the
whole database, schema **and** data, including Supabase's own schemas
(`auth`, `storage`, `vault`, ...). It is written to `*.dump.partial` and only
renamed once validated: at least 1 KiB, the `PGDMP` magic, and a
`pg_restore --list` that succeeds and lists table data. Any failure deletes
the partial file and, inside `make promote`, stops the run.

**Which pg_dump.** A host `pg_dump` whose major version is >= the server's
(15) if there is one; otherwise `pg_dump` inside a container (`podman`, else
`docker`) from the first image in `backup.CONTAINER_IMAGES` that is new enough,
preferring one already pulled (`public.ecr.aws/supabase/postgres:15.8.1.085`
is, if you have run the local stack) and otherwise pulling the closest major.
The container uses host networking and streams the archive to stdout; nothing
is mounted.

**Secrets.** The database password is never on a command line or in the
output: it is stripped from the URI and passed as `PGPASSWORD` (`-e
PGPASSWORD`, name only, for the container), and every printed URL is masked.

**Treat every dump as sensitive.** Encrypted columns (see CLAUDE.md
"Column-level encryption") are in it as ciphertext, readable by anyone who
also has that environment's `ENCRYPTION_KEY`; everything else (ids, emails
where plaintext, scores, timestamps, the course catalog, `auth`/`storage`
metadata) is in it as plain text. Never commit one, never attach one to an
issue or PR, never copy one off this machine unencrypted. Restoring a dump
into another environment does not make it readable there: that environment
has a different `ENCRYPTION_KEY`, and the backend's key canary will refuse to
boot against rows written under another key.

**Retention is manual.** Nothing prunes `backups/`. Keep at least the dump
from the last promotion; delete older ones yourself.

**Restoring.** `pg_restore` must be at least as new as the `pg_dump` that
wrote the archive — the tool line printed with the backup says which major
that was. Without host client tools, run it from the same image (feed the
file on stdin, or `podman cp` it into a running container for `-j`):

```
IMG=public.ecr.aws/supabase/postgres:15.8.1.085

# What is in it?
podman run --rm -i --entrypoint pg_restore $IMG --list < backups/prod-<ts>.dump

# Rehearse first: restore into the LOCAL stack or a scratch container and look.
# One table's rows back into an existing table (target password via env, never argv):
PGPASSWORD=... podman run --rm -i --network host -e PGPASSWORD --entrypoint pg_restore $IMG \
  --data-only --table=<table> --dbname 'postgresql://postgres.<ref>@<pooler-host>:5432/postgres' \
  < backups/prod-<ts>.dump

# The app schema only, objects owned by whoever restores:
... pg_restore --schema=public --no-owner --dbname '<target>' < backups/prod-<ts>.dump
```

Restoring Supabase-managed objects (`auth`, `storage`, default privileges
owned by `supabase_admin`) as `postgres` reports permission errors — expected;
restore the schemas/tables you actually need (`--schema`, `--table`,
`--data-only`), not the whole archive over a live project. Restoring over
production is a deliberate, by-hand decision: take a fresh dump first.
