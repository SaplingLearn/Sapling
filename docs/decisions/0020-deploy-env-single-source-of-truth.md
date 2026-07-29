# 0020 — DEPLOY_ENV as the single source of truth for frontend environment config

**Status:** accepted · **Relates to:** #190, [0018](0018-session-token-lifecycle.md)

## Symptom

Login on `staging.saplinglearn.com` bounced to `/?error=session_expired` with
nothing in the browser console.

## Root cause

The error is a **middleware** redirect (`frontend/src/middleware.ts`), not a
backend one — the backend fails to `/auth?error=…`, only the middleware redirects
to `/?error=…`, and it's a server-side 307 so nothing reaches the console.

The worker serving `staging.saplinglearn.com` was running with the **production**
config: probing `GET https://staging.saplinglearn.com/dashboard` (no cookie)
returned `307 → https://api.saplinglearn.com/api/auth/google` — the *prod*
backend, not `api.staging.saplinglearn.com`. So the `[env.staging]` overrides in
`wrangler.toml` were not in effect (deployed without `--env staging`, or the
custom-domain route was bound to the prod `frontend` worker instead of
`frontend-staging`).

Consequence: staging's login round-tripped through the prod backend, which signs
the handoff token with prod's `SESSION_SECRET` and redirects to prod's
`FRONTEND_URL`. The `sapling_session` cookie that came back was prod-signed and
scoped to `.saplinglearn.com` (a parent-domain cookie, so it *also* reaches
`staging.saplinglearn.com`). Staging's middleware then verified it with staging's
`SESSION_SECRET` → HMAC mismatch → `middleware.ts:56` → `session_expired`. The
staging backend itself was healthy the whole time (clean `401 {"detail":"Not
authenticated"}`, its own OAuth client).

This is the mirror image of the footgun `deployGuard.ts` was built for (#190,
"staging config on the prod worker"). That guard's check that catches an
internally-consistent-but-wrong-target build only arms when `DEPLOY_ENV` is set —
and it wasn't set on either Workers Build, so it slept.

## Decision

Make `DEPLOY_ENV` the single knob that drives every environment-specific value,
with the explicit vars kept as backward-compatible fallbacks.

- `deployGuard.ts` gains pure, unit-tested helpers:
  - `resolveFrontendEnv(env)` — when `DEPLOY_ENV` names a known env, derive
    `apiUrl`/`cookieDomain` from `FRONTEND_ENVS` (cannot drift or half-set);
    otherwise fall back to `BACKEND_URL` → `NEXT_PUBLIC_API_URL` and
    `COOKIE_DOMAIN`, preserving docker/local behaviour.
  - `expectedEnvForHost(host)` / `detectHostConfigMismatch(host, apiUrl)` —
    map the canonical hosts to their env and flag a worker serving one env's
    host while wired to another's backend (returns null for previews/localhost).
- `middleware.ts` derives `API_URL` via `resolveFrontendEnv` and, on a protected
  route, calls `detectHostConfigMismatch`. On mismatch it logs a loud server
  error and redirects with a **distinct** `env_misconfig` code instead of the
  misleading `session_expired`. This is the runtime defence-in-depth for what the
  build-time guard cannot see (a consistent build shipped to the wrong worker).
- `app/api/auth/session/route.ts` derives the cookie `Domain` from
  `resolveFrontendEnv`, so a staging build cannot mint a `.saplinglearn.com`
  cookie that leaks into prod.
- `next.config.ts` derives the build-time `BACKEND_URL` (the `/api` rewrite) and
  the inlined `NEXT_PUBLIC_API_URL`/`COOKIE_DOMAIN` from `DEPLOY_ENV`.
- `wrangler.toml` sets `DEPLOY_ENV = "production"` in `[vars]` and
  `DEPLOY_ENV = "staging"` in `[env.staging.vars]`.

## Operational follow-up (required, not code)

The code change does **not** fix the currently-broken deployment — only a
redeploy does. Each environment is a separate Cloudflare **Workers Build** with
two *distinct* fields — a **Build command** and a **Deploy command** — that must
never be conflated:

- **Build command** — MUST stay `npm run cf:build` (`opennextjs-cloudflare
  build`). This is the step that compiles the app into `.open-next/worker.js`,
  the `main` entry `wrangler.toml` deploys. **Never overwrite the build command
  with a `wrangler deploy` / `wrangler versions upload` line.** A deploy command
  in the build field skips the OpenNext build entirely, `.open-next/` is never
  produced, and every build fails with `ERROR Could not find compiled Open Next
  config, did you run the build command?` — this is exactly what took the
  `frontend-staging` build down for ~16 builds starting 2026-07-20, when the
  build field was replaced with `npx wrangler deploy --env staging` while wiring
  up `DEPLOY_ENV` below.
- **Deploy command** — leave it as the already-green `npx wrangler versions
  upload`; it was never the problem. The staging environment
  (`[env.staging]` → the `frontend-staging` worker) is selected by the staging
  Workers Build's own deploy config / `--env staging` on the *deploy* step — it
  does **not** belong in the build command.
- Set `DEPLOY_ENV` as a **build** variable (`staging` / `production`). This is a
  *variable*, set in the Build variables panel — not a command. `wrangler.toml
  [vars]` are runtime-only; the `/api` rewrite and `NEXT_PUBLIC_*` inlining bake
  at build time (see [0018](0018-session-token-lifecycle.md)).
- Confirm `staging.saplinglearn.com` routes to the `frontend-staging` worker,
  not `frontend`.
- Verify the build is green again, then:
  `curl -sSI https://staging.saplinglearn.com/dashboard` must show
  `Location: https://api.staging.saplinglearn.com/api/auth/google`.

## Note

The repo's `vitest` runner currently crashes at startup on Node 20.12.1
(`util.styleText` receives an array of styles, which needs Node ≥ 20.16/22).
The new pure helpers were verified via `tsx` + `tsc --noEmit`; the vitest specs
are added and will run in CI on a supported Node. Bumping the local Node /
pinning an engines range is a separate cleanup.
