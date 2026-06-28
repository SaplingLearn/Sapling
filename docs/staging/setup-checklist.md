# Staging Setup Checklist (operator)

The step-by-step for standing up staging in the dashboards. Companion to the design
(`docs/superpowers/specs/2026-06-21-staging-environment-design.md`) and plan
(`docs/superpowers/plans/2026-06-21-staging-environment.md`).

**Mental model:** staging runs the *same code* as prod; only **environment variables**
differ. **Secrets never live in a git-tracked file** — they go straight into Railway
variables, Cloudflare worker secrets, or a local gitignored `backend/.env.staging`.

---

## Do it in this order (each step feeds the next)

### Step 1 — Supabase (the staging database)
- [ ] Create a new project `sapling-staging` (same region as prod).
- [ ] Copy **Settings → API → Project URL** → `SUPABASE_URL`.
- [ ] Copy **Settings → API → service_role key** → `SUPABASE_SERVICE_KEY` (backend only — never the frontend).
- [ ] Copy **Settings → Database → Connection string → "Direct connection" (port 5432, not the pooler)** → `SUPABASE_DB_URL`.
- [ ] Generate a staging encryption key → `ENCRYPTION_KEY`:
      `python -c "import secrets; print(secrets.token_hex(32))"`
- [ ] Create storage buckets `avatars` and `cosmetic-assets` (match prod).
- [ ] Once you have the keys locally (Step 6), apply schema: `SUPABASE_DB_URL=<direct> python -m db.migrate`.

### Step 2 — Google Cloud (OAuth) — you can do this NOW
- [ ] Create OAuth client "Sapling Staging" (Web application).
- [ ] Authorized **redirect URIs** (must match exactly):
  - `https://api.staging.saplinglearn.com/api/auth/google/callback`
  - `https://api.staging.saplinglearn.com/api/calendar/callback`
- [ ] Authorized **JavaScript origin**: `https://staging.saplinglearn.com`
- [ ] Copy client id/secret → `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`.
- [ ] If the consent screen is in "testing", add your testers as test users.
- [ ] Decide sign-in domains: keep `ALLOWED_EMAIL_DOMAINS=bu.edu`, widen (`bu.edu,saplinglearn.com`), or leave empty to allow any account (safe — Access gates it).

### Step 3 — Railway (the backend service)
- [ ] In the existing Railway project: **Environments → create `staging`** (duplicate of production).
- [ ] Set its **Variables** from `backend/.env.staging.example` (real values; this is where the backend secrets live).
- [ ] Set **deploy branch = `main`** (trunk-based: main → staging).
- [ ] Add **custom domain `api.staging.saplinglearn.com`** to the staging service — Railway shows you the DNS target for Step 5.

### Step 4 — Cloudflare Workers (the frontend service)
- [ ] The `[env.staging]` block in `frontend/wrangler.toml` is already in the repo (Phase 4). Deploy: `cd frontend && npm run cf:deploy:staging` → publishes a `frontend-staging` worker.
- [ ] Add the worker secrets for the Access hop (Step 5):
      `wrangler secret put CF_ACCESS_CLIENT_ID --env staging` and `... CF_ACCESS_CLIENT_SECRET --env staging`.

### Step 5 — DNS + Cloudflare Access (the security gate)
- [ ] `api.staging.saplinglearn.com` → point at the Railway target from Step 3 (proxied).
- [ ] `staging.saplinglearn.com` → bind as a **custom domain** on the `frontend-staging` worker (wires route + DNS together).
- [ ] **Cloudflare Access (Zero Trust)** application on **both** hostnames; policy = allowlist of admin emails (IdP: Google).
- [ ] Create an Access **service token**; allow it on the `api.staging` app; its id/secret are the worker secrets from Step 4.

### Step 6 — Local tooling + smoke test
- [ ] `cp backend/.env.staging.example backend/.env.staging` and fill real values (gitignored — for running migrate/seed against staging from your machine).
- [ ] Apply schema, then seed demo data: `python -m db.migrate`, then `python -m db.seed_staging` (idempotent fake demo dataset — graph + gradebook + courses-with-term; safe to re-run).
- [ ] Visit `https://staging.saplinglearn.com`: Access wall → Google login → upload a doc → graph renders.

---

## What secret goes where

| Secret | Railway (staging env) | Cloudflare worker | Local `backend/.env.staging` | In git? |
|---|---|---|---|---|
| `SUPABASE_SERVICE_KEY` | ✅ | ❌ | ✅ (for migrate/seed) | ❌ never |
| `SUPABASE_DB_URL` | ✅ | ❌ | ✅ | ❌ |
| `ENCRYPTION_KEY` / `SESSION_SECRET` | ✅ | ❌ | ✅ (encryption key only, for seed) | ❌ |
| `GOOGLE_CLIENT_ID` / `_SECRET` | ✅ | ❌ | ✅ | ❌ |
| `CF_ACCESS_CLIENT_ID` / `_SECRET` | ❌ | ✅ (`wrangler secret put`) | ❌ | ❌ |
| `BACKEND_URL` / `COOKIE_DOMAIN` (non-secret) | ❌ | ✅ (`wrangler.toml` vars) | ❌ | ✅ (config, not secret) |

## URLs — create now vs. later

| URL | When | How |
|---|---|---|
| Google OAuth redirect URIs | **Now** | Just strings in the OAuth client; endpoints needn't exist yet. |
| `api.staging.saplinglearn.com` | When you make the Railway staging env (Step 3) | Add as a Railway custom domain → it gives the DNS target. |
| `staging.saplinglearn.com` | After the `frontend-staging` worker exists (Step 4–5) | Bind as a worker custom domain in Cloudflare. |

Don't create bare DNS records before their targets exist — they'd point at nothing.

## Security must-dos
- Fresh `ENCRYPTION_KEY` + `SESSION_SECRET` — never prod's.
- `COOKIE_DOMAIN=.staging.saplinglearn.com` — **not** `.saplinglearn.com` (that would share cookies with prod).
- `SUPABASE_SERVICE_KEY` lives only in Railway / local `.env.staging` — never in the frontend or git.
- Fake data only in staging.
- Both hostnames behind Cloudflare Access; `noindex` on staging (Phase 6).
