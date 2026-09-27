# Sapling Frontend Audit — 07 · Integrations

> Third-party services, libraries, and external systems the frontend integrates with. Listed so the rebuild can keep (or deliberately replace) each.

---

## 1. Authentication & identity

### 1.1 Google OAuth

- Handled entirely by the **backend** (`backend/routes/auth.py`). Frontend just redirects to `${API}/api/auth/google` and receives the callback at `/signin/callback`.
- Frontend never sees a Google access token. The handoff token (`auth_token` query param) is HMAC-signed with the shared `SESSION_SECRET`.
- Google profile images returned in the callback require `referrerPolicy="no-referrer"` on `<img>` tags (see `Avatar.tsx:17`).

### 1.2 Supabase

Two uses:

1. **Realtime** — `RoomChat.tsx` subscribes to `postgres_changes` on `room_messages` and `room_reactions` + a presence channel. See `06-realtime.md`.
2. **Storage** — `ReportIssueFlow.tsx` uploads issue-report screenshots to the `issues-media-files` bucket.

**Not used**: Supabase Auth (the app uses its own HMAC session cookie, not Supabase JWTs), Supabase Edge Functions, Supabase Database client-side RPC (message persistence goes through the backend).

Env vars: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`.

### 1.3 Google Calendar

- `/calendar` integrates with Google Calendar via the **backend** (OAuth handled server-side).
- Frontend calls `getCalendarAuthUrl` → redirects to Google → Google redirects back to the backend → backend redirects to `/calendar?connected=true`.
- Import / sync / export / disconnect are all REST calls to the backend, which holds the Google Calendar client.

---

## 2. AI / content

### 2.1 Google Gemini

- **Used by the backend only** (Pydantic AI agents under `backend/agents/`; the former `services/gemini_service.py` seam was deleted in ADR 0024). Frontend never calls Gemini directly.
- Referenced in the user-facing disclaimer (`DisclaimerModal.tsx`, `AIDisclaimerChip.tsx`): "Sapling uses Google Gemini to tutor, quiz, and track your progress."
- CLAUDE.md mentions the backend does streaming via SSE but the frontend consumes non-streaming JSON. See QUESTIONS Q16.

### 2.2 KaTeX (math rendering)

- `katex` + `remark-math` + `rehype-katex` used by `ChatPanel.tsx` to render LaTeX inside AI assistant messages.
- `katex/dist/katex.min.css` imported at `ChatPanel.tsx:7`.
- ESM-only packages (`remark-math`, `rehype-katex`) mocked for Jest in `src/__mocks__/`.

### 2.3 react-markdown

- Used by `ChatPanel.tsx` for assistant message rendering. Custom `components` override: `p`, `ul`, `ol`, `li`, `code`, `pre`, `strong`.
- Enables GFM + math + styled code blocks inside AI replies.

---

## 3. UI libraries

| Library | Version | Where used |
|---|---|---|
| `lucide-react` | 0.577.0 | Every icon in the app (Navbar, Settings sidebar icons, Maximize2/Minimize2, chevrons, etc.) |
| `framer-motion` | 12.38.0 | Installed — grep shows **no import sites** in `src/`. Either unused or imported at some path I missed. |
| `d3` | 7.9.0 | `KnowledgeGraph.tsx` (only user) |
| `next/font/google` | built-in | Spectral, DM Sans, Inter, Playfair Display, JetBrains Mono → CSS variables on `<html>` |
| `tailwindcss` | 4.x | Utility classes throughout; CSS tokens in `globals.css` |

---

## 4. Dev tooling / build

| Tool | Notes |
|---|---|
| Next.js 16.1.6 | App Router; `reactCompiler: true` |
| React 19.2.3 | With React Compiler (`babel-plugin-react-compiler@1.0.0`) |
| TypeScript 5 | Strict |
| Jest 30 | With `jest-environment-jsdom`; ESM mocks in `src/__mocks__/` |
| `@testing-library/react` 16.x | Suite in `src/__tests__/` |
| ESLint 9 + `eslint-config-next` | — |
| PostCSS + Tailwind v4 PostCSS plugin | — |
| Docker | `frontend/Dockerfile` wraps the standalone Next.js build |

No Sentry. No Datadog. No LogRocket. No analytics scripts detected (Plausible, Mixpanel, GA, etc.). Verify during rebuild if silent analytics were added later — grep found no imports.

---

## 5. Static assets

- `public/sapling-icon.svg` — app icon (used as favicon and as `Metadata.icons`).
- `public/sapling-word-icon.png` — wordmark used on `/signin` and `/pending`.
- `src/app/icon.svg` — Next.js metadata icon (same as `sapling-icon.svg` in practice).

---

## 5a. Product analytics (PostHog US)

- **Who and where: signed-in students who have not opted out, inside the app shell only.** posthog-js (`src/lib/analytics.ts`, the only module that talks to it) is never loaded on public/marketing pages, `/auth/*`, onboarding, or for anyone signed out. "App shell" is `lib/appRoutes.ts` (`isAppShellRoute`, the `(shell)` routes — the same list the UserProvider and middleware use). Route matching is by path segment (`/profile` and `/profile/x`, never `/profiles`), and the same list feeds middleware.ts and robots.ts. On the first shell page of a page load the UserProvider reads `GET /api/profile/{user_id}/settings` (never on public or `/auth` routes); only `analytics_opt_out: false` loads and starts posthog-js. `true`, a missing field, or a failed read → off until the student next enters the shell. DNT / GPC → always off. The capture gate (`before_send`) checks the **live** route too, so a client-side navigation out of the shell (Settings → /privacy) sends nothing for that page, and the next shell pageview doesn't carry `$prev_pageview_*` pointing at it.
- **What is captured: pageviews and pageleave only.** Autocapture, rageclicks, dead clicks, heatmaps and web vitals are all off — element chains carry hrefs, relative ones included; product usage comes from backend events. `identify(uuid)` runs in posthog-js's `loaded` hook, before its initial `$pageview`, so a page load sends `$identify` + exactly one `$pageview`.
- **Nothing is stored in the browser.** `persistence: 'memory'` — no posthog cookies, localStorage or sessionStorage — and posthog-js's own opt-out/opt-in (which would write localStorage) is never called. The account flag is the single source of truth, read afresh each page load; no analytics session continuity across full reloads (accepted).
- **Opt-out switch** (Settings → Data, the shared `Toggle`): disabled until the account answers, while a save is in flight, and under DNT/GPC (with the reason). Opting **out** closes the gate at once, then PATCHes `analytics_opt_out: true`; if that save fails the switch shows **"Off for this visit only"** with a *Retry saving* button (`off_unsaved`) — never "Saved". Opting **in** PATCHes `false` first and only then starts capture (reported as saved whenever the PATCH succeeded, applied only if the same student is still signed in). One toggle at a time; the generation counter is bumped before and after each save, so no account read begun before or during a toggle can overwrite it. If the posthog-js chunk fails to load (a blocker), the switch says it couldn't start (`on_not_running`) and the next entry into the shell tries once more — no retry loop.
- **What goes on the wire.** Only those events. Feature flags are off (`advanced_disable_flags`), so no `/flags` request, and posthog-js then skips remote config too. Surveys, product tours, conversations, web experiments and site apps are disabled explicitly.
- **URLs.** The `/auth/callback` handoff params are masked by posthog-js at the source (`custom_personal_data_properties`); `before_send` strips every query string and fragment — absolute, protocol-relative and root-relative URLs alike — recursively. `disable_capture_url_hashes` is on.
- **`/ingest` proxy — same-origin, and not an open relay.** `src/app/ingest/[...path]/route.ts` + `src/lib/ingestProxy.ts`, not a `next.config` rewrite (OpenNext's rewrite proxy forwards every header, the `sapling_session` cookie included). It forwards only the endpoints this SDK config uses (`POST /e/`, `/i/v0/e/`, `/batch/`; `GET/HEAD /static/<bundle>.js`); only when the `sapling_session` cookie **verifies** (`verifySession()` — the same local HMAC + expiry check middleware.ts runs, no backend call; 403 otherwise; the cookie is never forwarded); with request bodies capped at 1 MiB (Content-Length up front, plus a byte count while reading → 413); and only event bodies whose `api_key`/`token` is this build's `NEXT_PUBLIC_POSTHOG_KEY` (403 otherwise), so the Worker can't relay into another PostHog project. posthog-js runs with `disable_compression`, so bodies are plain JSON (or base64 `data=` for `sendBeacon`) and nothing is ever decompressed — a gzip body is refused (400) rather than inflated past the cap. The body is therefore buffered (≤ 1 MiB), not streamed. Upstream headers come from an allowlist (conditional `if-none-match` / `if-modified-since` included, so revalidation can 304); encoded dot/slash/backslash/percent and dot segments are refused; versioned bundles are `immutable`. `INGEST_PREFIX` is posthog-js's `api_host`; `NEXT_PUBLIC_POSTHOG_HOST` may only move it to another same-origin path, never to an external host that would bypass all of this.
- **Unbatched.** `request_batching: false`: each event is sent as it happens, so sign-out never strands a queued batch (after sign-out the proxy 403s, and posthog-js never retries a 4xx).
- **Trailing slashes.** `skipTrailingSlashRedirect` lets PostHog's slash-terminated endpoints through; a `redirects()` rule restores the 308 for every other path (`/api/*` included) — only `/ingest/*` is excluded. Encoded slugs keep their encoding (`/notes/a%20b/` → `/notes/a%20b`, `/news/caf%C3%A9/` → `/news/caf%C3%A9`), verified under `next start` and `wrangler dev`.
- **Client IP — deliberately not forwarded.** No `X-Forwarded-For`, never `cf-connecting-ip`; PostHog only sees the Worker's egress address, and every event carries `$geoip_disable: true` (posthog-js's `ip` option is a documented no-op). **The PostHog project setting "Discard client IP data" must be ON.**
- **Build gating / deploy.** No `NEXT_PUBLIC_POSTHOG_KEY`, local UI mode, or the E2E/test build → none of this runs, not even the settings read (`e2e/analytics.spec.ts`). The key is inlined at build time: set it as a Cloudflare Workers Builds **build** variable on `frontend` and `frontend-staging`. Unset = off.
- **Follow-up.** Carrying `analytics_opt_out` on `/api/auth/me` would save the settings read on the first shell page of each load (needs a backend change).

---

## 6. External services NOT used

Worth being explicit: no evidence of any of these in the frontend. If the rebuild adds them, they're greenfield.

- Stripe / Paddle / billing.
- Intercom / Crisp / in-app chat widgets.
- Mixpanel / Segment / Heap (analytics is PostHog — §5a).
- Sentry / Rollbar / error-tracking SDKs.
- TipTap / Monaco / ProseMirror / rich-text editors.
- Chart.js / Recharts / Victory — the only data viz is the d3 `KnowledgeGraph`.
- WebSockets other than Supabase Realtime.
- Push notifications / Service workers / Web Push.

---

## 7. Env var catalog (authoritative)

Collected from every `process.env.*` reference in `src/`:

| Var | Scope | Required for | Referenced in |
|---|---|---|---|
| `NEXT_PUBLIC_API_URL` | browser + server | Backend API base | middleware, `lib/api.ts`, UserContext, `/signin`, `/signin/callback`, landing page, `OnboardingFlow`, `StudyClient`, `/dashboard`, session route handler |
| `BACKEND_URL` | build time only | `next.config.ts` rewrites | `next.config.ts` |
| `SESSION_SECRET` | server only | HMAC session signing | `lib/sessionToken.ts`, `/api/auth/session` route |
| `NEXT_PUBLIC_LOCAL_MODE` | browser + server | Offline dev bypass | middleware, UserContext, `lib/api.ts` |
| `NEXT_PUBLIC_SUPABASE_URL` | browser | Supabase client | `lib/supabase.ts` |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | browser | Supabase client | `lib/supabase.ts` |
| `STATIC_EXPORT` | build time only | `next export` toggle | `next.config.ts` |
| `NEXT_PUBLIC_POSTHOG_KEY` | browser (build-time inlined) | PostHog product analytics; unset = off | `lib/analytics.ts` (started from `context/UserContext.tsx`) |
| `NEXT_PUBLIC_POSTHOG_HOST` | browser (build-time inlined) | Optional `api_host` override — a same-origin path only (`/…`); anything else falls back to the `/ingest` proxy | `lib/analytics.ts` |

`NEXT_PUBLIC_*` are bundled into the client — never put secrets in them.

---

## 8. Things to preserve

- The **backend-centric auth pattern** — frontend never holds OAuth tokens for Google or Google Calendar.
- Supabase Realtime for chat (low-latency; offloads traffic from FastAPI).
- Supabase Storage for user-uploaded screenshots.
- KaTeX rendering for math inside AI messages.
- Next.js `next/font/google` for typography — keeps the font files self-hosted and avoids FOUT.
- Lucide icons (consistent icon set).

## 9. Things to rework / decide

- **`framer-motion` appears unused** — check if the rebuild needs it; otherwise drop.
- ~~**Decide on analytics**~~ — decided: PostHog (US). Wired in `src/lib/analytics.ts` (started by the UserProvider for signed-in, not-opted-out students only), proxied same-origin through `src/app/ingest/[...path]/route.ts`; pageviews only (click autocapture, heatmaps and session replay all off), app-shell routes only, account-wide opt-out in Settings → Data. Details and the required "Discard client IP data" project setting in §5a.
- **Add Sentry (or equivalent)**: the rebuild will have new bugs; client error tracking is cheap insurance.
- **Replace `SpaceBackground.tsx` dead import (if later added)** — currently unused.
