# Sapling — New Frontend

A redesigned Next.js frontend for Sapling based on the `Sapling Rebuild` design prototype.

Visual system: warm paper neutrals, botanical forest-green accent, serif (Spectral) + display serif (Playfair Display) + humanist sans (DM Sans), JetBrains Mono accents. Light theme only, with density tokens (compact/spacious) and three knowledge graph variants (orb/constellation/organism).

## Run

```bash
cd frontend
npm install          # Node >= 20.9, npm >= 10.9 <11 — enforced, see below
npm run dev          # http://localhost:3000
```

Backend `/api/*` calls are rewritten to `http://localhost:5000` by default (override via `BACKEND_URL`). For the real local backend stack, see `docs/local-supabase.md`.

### If your npm is 11 or newer

`.npmrc` sets `engine-strict=true` against a `npm >=10.9.0 <11` pin, and that blocks **`npm ci` as well as `npm install`** — verified on npm 12.0.1 (exit 1, `EBADENGINE`). The failure mode is quiet: `node_modules` stays empty, so `npm run lint` / `npm run typecheck` stop being a real gate rather than reporting an error. Either install the pinned npm:

```bash
npm install -g npm@10.9.2      # what CI does before `npm ci`
```

or unblock the read path only:

```bash
npm_config_engine_strict=false npm ci    # restores node_modules + the lint gate
```

**Never pair that bypass with `npm install` and commit the regenerated `package-lock.json`.** Cloudflare Workers Builds runs `npm ci` on npm 10.9.2 and rejects an off-pin lockfile with `Missing X from lock file`, breaking the deploy — that is the entire reason the pin exists. See `frontend/.npmrc` for the full rationale and the relax-plan for when CF upgrades its runner.

## Build & deploy

```bash
npm run build       # next build
npm run test        # vitest
npm run lint        # eslint
npm run typecheck   # tsc --noEmit
```

Browser-test hooks: the six surfaces the Playwright suite drives (sign-in, the
approval gate, the upload modal, the tutor composer, the quiz answer flow, the
graph container) carry `data-testid` attributes. Naming rules, the current
inventory, and the ESLint rule that keeps new controls from drifting are in
`docs/frontend-testids.md`.

Deployed to Cloudflare Workers via OpenNext:

```bash
npm run cf:preview          # build + local wrangler preview
npm run cf:deploy           # build + deploy (production)
npm run cf:deploy:staging   # build + deploy --env staging
```

`BACKEND_URL` must be set as a build-time variable for any deploy (prod: `https://api.saplinglearn.com`, staging: `https://api.staging.saplinglearn.com`) — the build fails loudly otherwise, and `wrangler.toml [vars]` (runtime-only) will not fix it. Signed-in sessions also need `SESSION_SECRET` (matching the backend) and `COOKIE_DOMAIN`.

## Layout

- `src/app/` — App Router with two route groups: `(shell)` (the signed-in app — `ShellFrame` sidebar + top bar) and `(public)` (the pre-auth marketing surface — landing, about, careers, privacy, terms). `onboarding` sits outside both, full-bleed. Sign-in is a modal triggered from the landing page.
- `src/components/` — shared UI primitives (`ui/`) and per-screen components (`screens/`).
- `src/context/UserContext.tsx` — signed-in user context provider (mounted in the root layout).
- `src/lib/` — `api.ts` (typed same-origin `/api/*` client), `data.ts`, plus shared hooks and helpers.

## Routes

`/dashboard` `/learn` `/tree` `/study` `/quiz` `/library` `/notetaker` `/gradebook` `/course-planner` `/calendar` `/social` `/achievements` `/profile` `/settings` `/admin` — wrapped by the `(shell)` layout.

`/` (landing) `/about` `/careers` `/privacy` `/terms` — the `(public)` marketing group.

`/onboarding` — full-bleed.

A Report button (bottom-right, `FloatingActions` in the shell) opens the feedback modal.
