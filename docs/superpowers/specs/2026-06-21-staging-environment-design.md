# Staging Environment — Design Spec

**Date:** 2026-06-21
**Status:** Approved (brainstorm phase complete)
**Owner:** saplinglearn

## Summary

Stand up a fully-hosted **staging environment** — a parallel "mini-prod" that mirrors the
production stack but shares nothing live with it — so database migrations, data-integrity
fixes, and frontend bugs can be exercised end-to-end before anything reaches prod.

The stack already runs in two halves: the Next.js frontend on **Cloudflare Workers**
(`saplinglearn.com`) and the FastAPI container on **Railway** (`api.saplinglearn.com`), both
backed by a single **Supabase** project. Staging clones each half into an isolated copy:

```
                 PRODUCTION                          STAGING
  ┌──────────────────────────────┐   ┌──────────────────────────────────┐
  Frontend  saplinglearn.com           staging.saplinglearn.com
   (Cloudflare Worker, prod env)        (same Worker, [env.staging])
        │                                      │
        ▼                                      ▼
  Backend   api.saplinglearn.com        api.staging.saplinglearn.com
   (Railway, production env)             (Railway, staging environment)
        │                                      │
        ▼                                      ▼
  Database  Supabase prod project        Supabase STAGING project
            (real users, prod key)        (fake data, staging-only key)
```

**Golden rule:** staging shares no live state with prod — separate database, separate
`ENCRYPTION_KEY`, separate Google OAuth client, separate `SESSION_SECRET`. The only things
deliberately shared are the Cloudflare account/zone and (optionally) the Gemini API key.

## Goals

- A shareable `staging.saplinglearn.com` URL that runs the full app against an isolated database.
- A safe place to rehearse every schema migration / FK / UNIQUE / index / dedup change before
  prod, with a **reproducible apply path** so staging and prod can't drift.
- Staging data that contains the exact broken-row shapes the backlog's data-integrity issues
  must handle, so each fix can be *proven*, not just deployed.
- A clear promotion flow: change → verify on staging → promote identical change to prod.

## Non-goals (v1)

- Cloned/anonymized production data (start with synthetic + targeted dirty fixtures instead).
- Automated CI gating that *blocks* prod deploys on staging checks (manual discipline for v1).
- Per-PR ephemeral preview environments (one long-lived staging environment for now).
- A staging copy of every third-party integration beyond auth + DB (e.g. separate Logfire
  project, separate Gemini key) — optional, not required for v1.

## User-facing decisions

| Decision | Choice | Rationale |
|---|---|---|
| Fidelity | Fully-hosted parallel stack (shareable URL) | Lets testers exercise the real app, not just local dev. |
| Backend staging | Railway **second environment** in the same project | Railway environments give isolated variables + deploy per env without a new project. |
| Frontend staging | `[env.staging]` in `frontend/wrangler.toml`, deployed `--env staging` | Native Workers named-environment pattern; no second repo/worker to maintain. |
| Database | New Supabase **staging project**, own `ENCRYPTION_KEY` | Total isolation; staging key means no prod ciphertext is ever decryptable in staging. |
| Test data | Synthetic seed **+ deliberately broken rows** | Broken rows reproduce the issues' failure modes so fixes are provably correct. No prod PII. |
| Migration plumbing | **Phase 0: minimal migration runner** (`schema_migrations` table + ordered apply script) | Closes #197; makes "apply to staging then prod" reproducible and drift-free. |
| Subdomains | `staging.saplinglearn.com` + `api.staging.saplinglearn.com` | Mirrors the prod `app` / `api` split; both already inside the Cloudflare zone. |
| Auth | Separate "Sapling Staging" Google OAuth client | Keeps prod consent screen / quotas / redirect URIs clean. |
| Git model | **Trunk-based**: `main` is the single source of truth; staging & prod deploy the *same commit* | Staging differs by config, not code — nothing to reconcile, no long-lived branch to drift. |
| Access control | **Cloudflare Access** (Zero Trust) on both staging hostnames + `noindex` | Edge-level admin allowlist, zero app-code; only allowlisted admins ever reach staging. |

## Code & config changes

Staging is mostly configuration + new DB tooling — **no business-logic file changes**.

| File | Change | Why |
|---|---|---|
| `frontend/wrangler.toml` | **New** `[env.staging]` block (`BACKEND_URL`, `NEXT_PUBLIC_API_URL`, `COOKIE_DOMAIN`) | Points the staging Worker at the staging backend. |
| `frontend/package.json` | Add `cf:deploy:staging` script (`wrangler deploy --env staging`) | Convenience. |
| `backend/db/migrate.py` | **New** migration runner (~50 lines) + `schema_migrations` table | Ordered, idempotent apply path. Closes #197. |
| `backend/db/migration_*.sql` | Numeric prefixes for ordering; make `migration_cosmetics.sql` idempotent | Locks apply order; fixes #196. |
| `backend/db/seed_staging.py` | **New** | Fake users/courses/graphs, encrypted with the *staging* key via `encrypt_if_present`. |
| `backend/db/dirty_fixtures.sql` | **New** | The deliberately-broken rows. |
| `backend/config.py` | *Optional*: recognize `APP_ENV=staging` | Only if the app must know it's staging (emit `noindex`, show a STAGING banner). |

Everything else lives in **dashboards, not the repo**: Railway staging environment + variables,
Cloudflare Worker route + Access policy, the Google staging OAuth client, and DNS.

## Architecture

### Component 1 — Staging Supabase project

A brand-new Supabase project (free tier is fine for staging). Bootstrapped by applying, in
order: `backend/db/supabase_schema.sql`, every `backend/db/migration_*.sql`, the
`avatars` storage bucket, then the seed (Component 6). Reconstructing the *correct* order is
exactly the gap #197 describes — see the migration runner below.

- Own `SUPABASE_URL` + `SUPABASE_SERVICE_KEY`.
- Own `ENCRYPTION_KEY` (32 bytes / 64 hex, generated fresh — **never** reuse prod's).
- Storage bucket `avatars` (per `migration_avatars_bucket.sql` / `config.py:STORAGE_BUCKET`).

### Component 2 — Staging backend on Railway

A second **environment** named `staging` inside the existing Railway project. Same Docker
image / `backend/Dockerfile`, different variables. Custom domain `api.staging.saplinglearn.com`.

### Component 3 — Staging frontend on Cloudflare Workers

Add an `[env.staging]` block to `frontend/wrangler.toml` overriding `BACKEND_URL`,
`NEXT_PUBLIC_API_URL`, and `COOKIE_DOMAIN` to the staging values; deploy with
`wrangler deploy --env staging`; bind the route `staging.saplinglearn.com`. Because the
frontend rewrites `/api/*` → `BACKEND_URL` (same-origin from the browser's view), the staging
Worker proxies to the staging Railway backend and cookies are set on the staging frontend
domain — so `COOKIE_DOMAIN` must match the staging subdomain.

### Component 4 — Staging Google OAuth client

A separate OAuth client ("Sapling Staging") in the same Google Cloud project. Authorized
redirect URIs:
- `https://api.staging.saplinglearn.com/api/auth/google/callback`
- `https://api.staging.saplinglearn.com/api/calendar/callback`

Its client id/secret become the staging `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`.

### Component 5 — DNS

Two records in the Cloudflare zone: `staging` (frontend, proxied to the Worker) and
`api.staging` (backend, to the Railway custom domain).

### Component 6 — Seed data (`backend/db/seed_staging.py` + dirty fixtures)

Sensitive columns are encrypted by the Python helpers in `services/encryption.py`, so the
seed for those columns must run through `encrypt_if_present` with the **staging** key — i.e. a
small `seed_staging.py`, not raw SQL. The deliberately-broken rows (which are about *structure*,
not encrypted content) can be a raw `dirty_fixtures.sql`:

- A handful of fake users / courses / graph nodes+edges / notes / sessions to click around in.
- Targeted broken rows mirroring backlog failure modes: orphan `graph_edges.user_id` (#179),
  duplicate graph nodes (#181), duplicate edges (#195), null FK rows in `notes` (#180),
  a zero-question quiz (#184). Each migration/bugfix can then be verified against the row it targets.

### Environment variable matrix

| Variable | Prod | Staging |
|---|---|---|
| `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` | prod project | **staging project** |
| `ENCRYPTION_KEY` | prod key | **fresh staging key** |
| `SESSION_SECRET` | prod secret | **fresh staging secret** |
| `GOOGLE_CLIENT_ID` / `_SECRET` | prod OAuth client | **staging OAuth client** |
| `GOOGLE_REDIRECT_URI` / `GOOGLE_AUTH_REDIRECT_URI` | `api.saplinglearn.com/...` | `api.staging.saplinglearn.com/...` |
| `FRONTEND_URL` (CORS) | `https://saplinglearn.com` | `https://staging.saplinglearn.com` |
| `APP_ENV` | `production` | `production` (staging behaves fail-closed like prod) |
| `GEMINI_API_KEY` | prod key | shared, or separate to isolate quota/cost |
| `BACKEND_URL` / `COOKIE_DOMAIN` (Worker) | `api.saplinglearn.com` / `.saplinglearn.com` | `api.staging.saplinglearn.com` / `.staging.saplinglearn.com` |

### Migration runner (Phase 0 — closes #197)

A minimal, dependency-free runner so the same ordered set of migrations applies identically to
staging then prod:

- A `schema_migrations` table (`filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ DEFAULT now()`).
- A small `backend/db/migrate.py` that lists `migration_*.sql` in lexicographic order, skips any
  already recorded in `schema_migrations`, applies the rest in a transaction, and records them.
- Rename/prefix existing migrations with a sortable numeric prefix to lock ordering, and make the
  known non-idempotent one (`migration_cosmetics.sql`, #196) idempotent (`IF NOT EXISTS` guards)
  as part of bringing them under the runner.

This is the backbone that makes "promote staging → prod" trustworthy; without it the two
databases drift the moment someone hand-applies SQL to one and not the other.

## Development workflow & git model

**Trunk-based.** `main` is the single source of truth; staging and prod deploy the *same commit*,
staging first. Staging differs from prod by **configuration (env vars), not code** — so there is
no divergent codebase to reconcile and no long-lived `staging` branch to drift. The staging-only
files (`seed_staging.py`, `dirty_fixtures.sql`, the `[env.staging]` block) live on `main` too;
they simply never *run* in prod.

Lifecycle of a change:

1. Feature branch → PR → merge to `main`.
2. `main` **auto-deploys to staging** (Railway staging env + `wrangler deploy --env staging`).
3. Run `migrate.py` against the **staging** DB; verify on `staging.saplinglearn.com` against the dirty fixtures.
4. **Promote to prod by fast-forwarding the `production` branch** to the verified `main` commit
   (`git checkout production && git merge --ff-only main && git push`); the `production` branch is
   what deploys to prod. Run the *same* `migrate.py` against the **prod** DB.

Concretely: `main` is *continuously staging* (every merge lands on `staging.saplinglearn.com`), and
`production` is just `main` frozen at a verified commit. There is never different *code* between the
two — only a different commit on the same line — so promotion is a fast-forward, never a merge conflict.

| | Today | With staging |
|---|---|---|
| Where you test | Local → prod | Local → **staging** → prod |
| Migrations | Hand-pasted into prod SQL editor | `migrate.py` on staging → verify → same `migrate.py` on prod |
| Promotion | Push → prod | Merge to main → auto-staging → verify → promote same commit to prod |
| Blast radius of a mistake | Prod users | Fake staging data |

## Access control

Staging is admin-only, gated at the **edge** so no app business-logic changes are needed:

1. **Cloudflare Access (Zero Trust) on `staging.saplinglearn.com`** — an Access application with a
   policy allowlisting specific admin emails (or the org Google domain). Non-allowlisted users hit
   a Google login wall before the app loads. Free up to 50 users.
2. **Cloudflare Access on `api.staging.saplinglearn.com` too** — the backend hostname is
   independently reachable, and the Worker proxies `/api/*` to it server-side. Gate it as well and
   have the Worker send an Access **service token** (`CF-Access-Client-Id` / `CF-Access-Client-Secret`)
   on that hop. (Alternative: a shared-secret header the Worker injects and the backend requires.)
3. **`noindex` on staging** — set `X-Robots-Tag: noindex` on the staging Worker so staging never
   appears in search. This is where the optional `APP_ENV=staging` awareness earns its keep.
4. **Defense-in-depth (optional)** — mark the fake staging users as admins and, if desired, reject
   non-admin sessions when `APP_ENV=staging` (`auth_guard.py::require_admin`, `migration_roles.sql`).
   Redundant given the Access allowlist, so not required for v1.

## Build phases

- **Phase 0** — migration runner + ordered/idempotent migrations (closes #197, hardens #196).
- **Phase 1** — staging Supabase project; apply schema via the runner; `seed_staging.py` + `dirty_fixtures.sql`.
- **Phase 2** — staging Google OAuth client + redirect URIs.
- **Phase 3** — Railway `staging` environment + variables + `api.staging.saplinglearn.com` domain.
- **Phase 4** — `[env.staging]` in `wrangler.toml` + `staging.saplinglearn.com` route.
- **Phase 5** — DNS records + end-to-end smoke test (log in, upload a doc, render the graph) on the staging URL.
- **Phase 6** — Cloudflare Access on both hostnames (service token on the Worker→backend hop) + `noindex`.
- **Phase 7** — wire trunk-based deploys: `main` auto-deploys to staging; document the promote-to-prod step.

## Issues this environment unblocks

Staging exists to de-risk this backlog. The links below tie each cluster to what staging enables.

**Migration plumbing — addressed directly by Phase 0:**

| Issue | Title |
|---|---|
| [#197](https://github.com/saplinglearn/sapling/issues/197) | Hand-applied migrations have no runner/ordering table — drift hazard |
| [#196](https://github.com/saplinglearn/sapling/issues/196) | `migration_cosmetics.sql` adds FK constraints non-idempotently — re-run fails |

**Data-integrity migrations — rehearsed on staging against the dirty fixtures:**

| Issue | Title |
|---|---|
| [#195](https://github.com/saplinglearn/sapling/issues/195) | No UNIQUE constraint backs edge dedup — concurrent/duplicate edges |
| [#181](https://github.com/saplinglearn/sapling/issues/181) | No UNIQUE constraint backs graph-node dedup |
| [#180](https://github.com/saplinglearn/sapling/issues/180) | `notes.user_id` / `notes.course_id` have no FOREIGN KEY constraints |
| [#179](https://github.com/saplinglearn/sapling/issues/179) | `graph_edges.user_id` has no FOREIGN KEY (orphan-row risk) |

**Index additions — index-build cost/locking validated on staging first:**

| Issue | Title |
|---|---|
| [#178](https://github.com/saplinglearn/sapling/issues/178) | `quiz_attempts` and `study_guides` lack indexes on filter columns |
| [#177](https://github.com/saplinglearn/sapling/issues/177) | `documents` has no `user_id` index — library/study-guide full-scan |
| [#176](https://github.com/saplinglearn/sapling/issues/176) | `sessions` has no `user_id` index — history/profile full-scan |
| [#161](https://github.com/saplinglearn/sapling/issues/161) | `messages` has no `(session_id, created_at)` index |
| [#160](https://github.com/saplinglearn/sapling/issues/160) | `graph_edges` has zero indexes |

**Backend bugs — reproducible end-to-end on the staging API:**

| Issue | Title |
|---|---|
| [#158](https://github.com/saplinglearn/sapling/issues/158) | `social.get_students` selects nonexistent `courses.user_id` → 400s |
| [#168](https://github.com/saplinglearn/sapling/issues/168) | Backend session token has a hard 5-minute lifetime with no refresh path |

**Frontend bugs — need real flows/data + a hosted URL to repro:**

| Issue | Title |
|---|---|
| [#191](https://github.com/saplinglearn/sapling/issues/191) | auth/callback persists localStorage identity before confirming live session |
| [#186](https://github.com/saplinglearn/sapling/issues/186) | Library upload: inline '+ Add a course' never appears in dropdown |
| [#185](https://github.com/saplinglearn/sapling/issues/185) | Calendar initial-load failure swallowed → valid-looking empty calendar |
| [#184](https://github.com/saplinglearn/sapling/issues/184) | QuizPanel strands user on blank screen when a quiz has zero questions |
| [#183](https://github.com/saplinglearn/sapling/issues/183) | Flashcard import: switching back to Paste tab wipes the deck |
| [#166](https://github.com/saplinglearn/sapling/issues/166) | Gradebook modal save/delete swallow errors (looks like a dead button) |
| [#165](https://github.com/saplinglearn/sapling/issues/165) | Settings 'Cosmetics' tab unreachable — CosmeticsManager is dead code |
| [#164](https://github.com/saplinglearn/sapling/issues/164) | Dashboard 'Where you left off' / Tree session links are dead |

**Prerequisite for staging↔prod build parity:**

| Issue | Title |
|---|---|
| [#163](https://github.com/saplinglearn/sapling/issues/163) | Backend dependencies are unpinned with no lockfile — non-reproducible builds |

> Note: #163 (pin/lock backend deps) is worth doing **before or alongside** staging — without it,
> the staging container and the prod container can build different dependency trees, undermining
> the whole "staging mirrors prod" guarantee.

## Risks / things to watch

- **Supabase free-tier projects pause after ~1 week idle** — expect a cold start, or ping it.
- **Never reuse `ENCRYPTION_KEY` / `SESSION_SECRET`** across environments.
- **CORS + cookie domain** must line up: staging backend `FRONTEND_URL` allows the staging origin;
  Worker `COOKIE_DOMAIN` matches the staging subdomain (see `SECURITY.md` / #221 same-origin CSRF).
- **Railway second environment = extra usage cost** (modest, not zero).
- **Reconstructing migration order (#197)** is real work — there is no recorded ordering today.

## Open questions / deferred decisions

- Share the prod Gemini key with staging, or provision a separate key to isolate quota/cost?
- Do we want a separate Logfire project for staging observability, or accept mixed traces?

**Resolved:** git model = trunk-based (`main` auto-deploys to staging, same commit promoted to
prod); access = Cloudflare Access on both hostnames + `noindex`.
