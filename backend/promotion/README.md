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

## What it does

1. **Preflight** (read-only): target-identity, ledger exists, no orphans,
   staging-ran-it-first, no destructive DDL, something to promote.
2. **Snapshot** production.
3. **Migrate** production (`db.migrate`) — this is the irreversible step.
4. **Snapshot** again and print the diff.
5. **Pause** — the only prompt. By this point the migration in step 3 has
   already run and cannot be undone; this confirms the merge, not the
   database change.
6. **Merge** `main` → `production`, retrying through the known `gh` 502.
7. **Wait** until `/api/health` reports the merge commit now on
   `origin/production` — not main's tip, which is never what gets deployed
   (10 min timeout).
8. **Smoke** the live surface.

If there are pending migrations but no new commits to promote (production's
code already matches main — see "Re-running" below), steps 5-7 are skipped
entirely after step 4: `gh pr create` would fail outright with "No commits
between production and main". Step 8 (smoke) still runs, since a migration
that broke the running app is exactly the failure that stage exists to catch.

Exit codes: `0` success or nothing to promote, `1` failure, `2` you declined.

Flags: `--verify-only` (stages 7-8 only), `--allow-destructive`,
`--skip-staging-check`, `--yes`.

## The ordering you need to know about

Migrations apply **before** the code merges. Between stages 3 and 6 the OLD
production code runs against the NEW schema. Additive DDL is fine there;
destructive DDL is not, which is why preflight blocks on it and
`--allow-destructive` is an explicit decision.

**If you answer `n` at the prompt, the migrations are already applied.**
Production's schema will be ahead of its code. Re-running resumes at the merge.

## When smoke fails

Nothing is reverted, deliberately: the migrations cannot be rolled back, so
reverting the code would leave old code against a newer schema. The runner
prints the revert command; reverting is your call.

## Re-running

Safe. Preflight is read-only and `db.migrate` skips what the ledger already
records, so a re-run after a failure repeats no work.

If the promotion already merged and you only want to re-check the live deploy —
the deploy was slow, or smoke failed and you have since fixed something — use:

```
make promote ARGS="--verify-only"
```

That skips preflight, snapshots, migrate and the merge entirely, and runs only
the deploy wait against `origin/production`'s tip followed by smoke. A plain
re-run would instead report `nothing-to-promote` and exit 0 without re-checking
anything, because by then there is genuinely nothing left to promote.
