# Sapling Frontend Audit — 00 · Overview

> **Purpose of this audit.** Produce an exhaustive, structured inventory of the existing Sapling frontend so the product can be rebuilt end-to-end without reading the original source. This document is Phase 1: stack, conventions, build/run, and the explicit exclusion boundary. Phases 2–5 build on this foundation.

---

## 1. Stack & framework

Source-of-truth: `frontend/package.json`, `frontend/next.config.ts`, `frontend/tsconfig.json`.

| Concern | Choice |
| --- | --- |
| Framework | **Next.js 16.1.6** (App Router, React Server Components capable) |
| React | **19.2.3** |
| Language | **TypeScript 5** (strict — see `tsconfig.json`) |
| Build modes | Default `output: "standalone"` with `/api/*` rewrites to `BACKEND_URL`; optional `STATIC_EXPORT=true` emits `output: "export"` with unoptimized images (`next.config.ts:3-19`) |
| Experimental | `reactCompiler: true` (React Compiler on; `babel-plugin-react-compiler@1.0.0` installed) |
| Styling | **Tailwind CSS v4** via `@tailwindcss/postcss` (`postcss.config.mjs`) + CSS custom properties in `src/app/globals.css` |
| Fonts | `next/font/google` — Spectral, DM Sans, Inter, Playfair Display, JetBrains Mono wired as CSS variables on `<html>` in `src/app/layout.tsx:12-55` |
| Icons | `lucide-react` 0.577.0 |
| Animation | `framer-motion` 12.38.0 |
| Math rendering | `katex` + `react-markdown` + `remark-math` + `rehype-katex` |
| Data viz | `d3` 7.9.0 (knowledge graph) |
| Auth / realtime / storage SDK | `@supabase/supabase-js` 2.99.3 (browser client for Realtime only — see §5) |
| Testing | `jest` 30 + `jest-environment-jsdom` + `@testing-library/react` + `@testing-library/user-event` |

**No state-management library.** No Redux, no Zustand, no React Query, no SWR. State is React Context (one provider: `UserContext`) plus per-page `useState`/`useEffect`/`useRef`. Data is fetched through typed wrappers in `src/lib/api.ts`; caching is ad hoc.

**No i18n library.** All copy is hard-coded English. There is no `next-intl`, `next-i18next`, or locale switch in the UI. Assume en-US only for now (flagged in `QUESTIONS.md`).

**No feature-flag library.** The only runtime gate observed so far is `NEXT_PUBLIC_LOCAL_MODE=true`, which short-circuits `middleware.ts` to allow all routes (`src/middleware.ts:54-56`). Full flag audit deferred to Phase 4.

---

## 2. Folder conventions

All frontend code lives under `frontend/src/`. Path alias `@/*` → `frontend/src/*` (see `tsconfig.json`).

```
frontend/src/
├── app/                 # Next.js App Router — every route is a folder with page.tsx
│   ├── layout.tsx       # Root layout: providers, Navbar, global modals, toasts
│   ├── page.tsx         # Landing / marketing (OUT OF SCOPE)
│   ├── error.tsx        # Root error boundary page
│   ├── globals.css      # Tailwind base + CSS custom properties (theme tokens)
│   ├── icon.svg         # Next.js metadata icon
│   ├── api/             # Next.js route handlers (server)
│   │   └── auth/session/route.ts   # POST/DELETE session cookie bridge
│   └── <feature>/page.tsx          # One folder per top-level route
├── components/          # Flat directory of reusable + page-level components
├── context/
│   └── UserContext.tsx  # Auth + profile context (the one global store)
├── lib/
│   ├── api.ts           # Typed fetch helpers for every backend endpoint
│   ├── supabase.ts      # Browser Supabase client singleton (Realtime only)
│   ├── sessionToken.ts  # HMAC session-token helpers (shared with middleware)
│   ├── avatarUtils.ts
│   ├── graphUtils.ts
│   └── types.ts         # Shared TS types (API shapes, user roles, etc.)
├── middleware.ts        # Auth + approval guard for PROTECTED routes
├── __mocks__/           # Jest mocks for ESM-only packages and CSS imports
└── __tests__/           # Jest suites (component + unit)
```

Conventions worth noting before the deep-dive phases:

- **Flat `components/` directory.** No `ui/`, `features/`, or `shared/` sub-folders. Components span presentational (`Avatar`, `RoleBadge`) through page-level orchestrators (`ChatPanel`, `RoomChat`, `OnboardingFlow`). A rebuild can impose structure.
- **`'use client'` everywhere by default.** Every page under `app/` that has been spot-checked is a client component. The App Router's Server Component story is not exercised; only `app/api/auth/session/route.ts` is server-only.
- **No co-location.** Tests live under `src/__tests__/`, not alongside components. Styles are Tailwind utility classes on JSX; there are no `*.module.css` files.
- **`lib/api.ts` is the only HTTP surface.** Pages call typed functions from `lib/api.ts`; they do not `fetch` directly. (Exceptions exist for Supabase Realtime in `RoomChat.tsx` — to be catalogued in Phase 3.)
- **No `hooks/` directory.** Custom hooks, if any, are inlined in the component that uses them. To be confirmed in Phase 4.

---

## 3. Build, run, test

From `frontend/package.json:5-12`:

| Script | Command | Notes |
| --- | --- | --- |
| Dev | `npm run dev` → `next dev` | Listens on `http://localhost:3000`. Expects backend on `http://localhost:5000` (default for `BACKEND_URL`/`NEXT_PUBLIC_API_URL`). |
| Build | `npm run build` → `next build` | Standalone by default; set `STATIC_EXPORT=true` for a static export build. |
| Start | `npm run start` → `next start` | Runs the standalone build. |
| Lint | `npm run lint` → `eslint` | Config: `eslint.config.mjs`, extends `eslint-config-next`. |
| Test | `npm test` → `jest` | Always run with `--watchAll=false` in CI per `CLAUDE.md`. |
| Test (watch) | `npm run test:watch` → `jest --watch` |  |

**Docker.** `frontend/Dockerfile` + root `docker-compose.yml` orchestrate frontend + backend. Not audited here; flagged in `QUESTIONS.md` in case Dockerfile contains build-time env surprises.

**Environment variables referenced by the frontend so far:**

| Var | Purpose | File |
| --- | --- | --- |
| `NEXT_PUBLIC_API_URL` | Base URL of the FastAPI backend (used in `lib/api.ts` and `middleware.ts`). | `src/middleware.ts:11`, many |
| `BACKEND_URL` | Used only at build time by `next.config.ts` to rewrite `/api/*`. | `next.config.ts:4` |
| `NEXT_PUBLIC_LOCAL_MODE` | If `'true'`, `middleware.ts` bypasses auth for every route. | `src/middleware.ts:54` |
| `STATIC_EXPORT` | Build-time toggle for `next export`-style output. | `next.config.ts:3` |
| `NEXT_PUBLIC_SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Browser Supabase client (Realtime chat subscription). | `src/lib/supabase.ts` (to confirm in Phase 4) |
| `SAPLING_SESSION_SECRET` (or equivalent) | HMAC secret used by `lib/sessionToken.ts` and middleware. | `src/lib/sessionToken.ts` (to confirm) |

A full env-var inventory is deferred to Phase 4 (`05-auth-and-permissions.md` and `07-integrations.md`).

---

## 4. Global app shell

Every route is wrapped by `src/app/layout.tsx:53-68`:

```
<html> (font CSS variables)
└─ <body>
   └─ <UserProvider>                                 # auth + profile context
      └─ <Navbar />                                  # top nav, auth-aware
      └─ <main>
         └─ <ErrorBoundary>                          # React error boundary
            └─ <ToastProvider>                       # toast notification context
               └─ {children}                         # the current route
      └─ <Suspense><FeedbackFlow /></Suspense>       # global "report feedback" flow
      └─ <Suspense><SessionFeedbackGlobal /></Suspense> # post-session feedback prompt
```

Implications for Phase 3/4:
- `UserContext`, `ToastProvider`, and `ErrorBoundary` wrap **all** routes — including landing. So in-scope pages can safely assume `useUser()`, `useToast()` (or equivalent), and error-boundary coverage are always available.
- `FeedbackFlow` and `SessionFeedbackGlobal` are mounted globally — they are not page-scoped, they listen for route changes / events and present flows on top of any page.
- `Navbar` is rendered on every page but adapts itself to "public" vs "authed" modes (see §5 below).

---

## 5. Auth, approval, and route guards (summary — full doc in Phase 4)

From `src/middleware.ts`:

- **Protected route matchers** (middleware runs on these paths):
  `/signin`, `/dashboard/**`, `/learn/**`, `/study/**`, `/tree/**`, `/flashcards/**`, `/library/**`, `/calendar/**`, `/social/**`, `/settings/**`, `/achievements/**`, `/admin/**` (`src/middleware.ts:113-122`).
- **`/signin` behavior:** if already signed-in-and-approved → redirect `/dashboard`; signed-in-and-unapproved → `/pending`; otherwise redirect to `${API_URL}/api/auth/google` unless an `?error=` param is present (then render the signin page). (`src/middleware.ts:60-68`)
- **Other PROTECTED routes:** require a valid `sapling_session` cookie (HMAC verified in `verifySession`) **and** a live backend check to `GET /api/auth/me` that returns `is_approved: true`. Unapproved → `/pending`; missing/invalid/expired token → Google OAuth (`src/middleware.ts:70-108`).
- **Local-mode bypass:** `NEXT_PUBLIC_LOCAL_MODE=true` disables the entire middleware (`src/middleware.ts:54-56`).
- **Navbar public-mode paths** (what Navbar treats as unauthenticated/marketing): `/`, `/signin/callback`, `/about`, `/terms`, `/privacy`, and any `/careers/*` (`src/components/Navbar.tsx:75-76`).

Observations:
- `/profile/**`, `/pending`, `/signin/callback`, and `/api/auth/session` are **not** in the middleware matcher. They are reachable without a session token at the middleware layer, but may gate themselves in client code (to confirm in Phase 3).
- The middleware calls `/api/auth/me` on *every* protected navigation so approval revocation takes effect immediately (comment on `src/middleware.ts:83`).

---

## 6. Exclusion boundary (hard rules for Phases 2–5)

The user's hard exclusion: **do not analyze, open, or document landing / marketing / pre-auth public pages.** The following files and routes are OUT OF SCOPE and will not be opened or documented, except where a marketing file *hosts* an in-scope flow (see "edge cases" below).

### 6.1 Out of scope — landing / marketing

| Path | File | Reason |
| --- | --- | --- |
| `/` | `src/app/page.tsx` | Landing page (`LandingPage` component, animated hero, `HowItWorks` section). |
| `/about` | `src/app/about/page.tsx` | Marketing "About" page. |
| `/privacy` | `src/app/privacy/page.tsx` | Privacy policy — pure marketing copy. |
| `/terms` | `src/app/terms/page.tsx` | Terms of service — pure marketing copy. |
| `/careers` | `src/app/careers/page.tsx` | Public careers listing page. |
| `/careers/[slug]` | `src/app/careers/[slug]/page.tsx` | Public job detail page. |
| `/careers/[slug]` form | `src/app/careers/[slug]/ApplyForm.tsx` | Job application form — public/recruitment, not authenticated-app surface. |
| `/careers/*` data | `src/app/careers/jobs.ts` | Static job list used only by the careers pages. |
| n/a | `src/components/HowItWorks.tsx` | Used only by `app/page.tsx` (verified via grep). |

Rationale and verification:
- Navbar's `publicPaths` array explicitly lists `/`, `/about`, `/terms`, `/privacy`, and `/careers/*` as public/marketing (`src/components/Navbar.tsx:75-76`).
- `HowItWorks` has exactly one import, in `app/page.tsx:8` (verified with grep).
- `ApplyForm` and `jobs.ts` are only reachable from `/careers/**`.

### 6.2 In scope — auth, app, admin

Everything else under `src/app/`:

- `/signin` and `/signin/callback` (auth flows gate the authenticated app).
- `/api/auth/session/route.ts` (server route that completes the auth handshake).
- `/pending` (approval holding page).
- `/dashboard`, `/learn`, `/study`, `/tree`, `/flashcards`, `/library`, `/calendar`, `/social`, `/settings`, `/achievements`, `/admin`.
- `/profile` (public user profile — part of the authenticated social surface).

Every component imported by in-scope routes. Every file under `src/lib/`, `src/context/`, `src/middleware.ts`.

### 6.3 Edge cases flagged for the user

These are handled explicitly in `QUESTIONS.md` so we don't silently drift into or out of the marketing area:

1. **`OnboardingFlow` mounted inside `app/page.tsx`.** The landing page hosts the `<OnboardingFlow />` component for authenticated-but-not-onboarded users (`src/app/page.tsx:7`, used at line referenced in later audit). The onboarding component itself is **in scope** (it gates the authenticated app); the surrounding landing-page scaffolding is not. The audit will document `OnboardingFlow` as a standalone feature and treat the landing page only as its host.
2. **`SpaceBackground.tsx` appears to be unused.** A case-insensitive grep across `src/` finds only its own definition (`src/components/SpaceBackground.tsx:3`). Candidate for `zz-dead-code.md`; will confirm in Phase 4 before declaring dead.
3. **`/profile` is not in the middleware matcher** but displays authenticated social-app data. Treating it as in-scope.
4. **`/pending` is not in the middleware matcher** but is only meaningful after sign-in. In scope.
5. **`/signin/callback` is listed as a Navbar public path** but is strictly the OAuth landing handler. In scope (auth flow).

### 6.4 Components of uncertain scope (to resolve in Phase 3 by checking import graph)

None known to be landing-only besides `HowItWorks`. `SchoolDirectory`, `SpaceBackground`, and `OnboardingFlow` were spot-checked:
- `SchoolDirectory` is imported by `/social/page.tsx` → in scope.
- `OnboardingFlow` is imported by `/` (landing) but represents post-signin onboarding → in scope, treated independently of its host.
- `SpaceBackground` has no importers → dead-code candidate.

All other components in `src/components/` will be catalogued in Phase 4 (`02-components.md`) with their importers to make any additional dead code explicit.

---

## 7. What Phase 1 did NOT do

To keep the exclusion boundary sanity-checkable before going deep, Phase 1 deliberately skipped:

- Reading any page under `src/app/` other than `page.tsx` (and that only enough to confirm the landing identity and the `OnboardingFlow` mount).
- Reading any component file other than `Navbar.tsx` (only the `publicPaths` lines), `layout.tsx` (full), and the import headers of `page.tsx`.
- Enumerating the contents of `src/lib/api.ts` — every endpoint will be catalogued in `04-api-surface.md` during Phase 4.
- Cataloguing Tailwind theme tokens from `globals.css` — deferred to `02-components.md` (design tokens section) in Phase 4.
- Reviewing any test under `src/__tests__/`. Tests will be consulted in later phases only where they clarify behavior that code alone does not.

These are intentional gaps, not oversights. If the exclusion boundary above is accepted, Phase 2 opens by enumerating every in-scope `app/` route file in one pass.

---

## 8. Stop point

Per the task brief: **stop here so the user can sanity-check the exclusion boundary before Phase 2.** Once the boundary is confirmed (and any additions/removals landed in `QUESTIONS.md` or this doc), Phase 2 will produce `01-routes.md`.
