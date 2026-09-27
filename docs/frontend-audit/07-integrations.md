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

- **Wiring.** `src/lib/analytics.ts` is the only module that talks to posthog-js; `src/instrumentation-client.ts` starts it. It is inert (posthog-js never even loads) without `NEXT_PUBLIC_POSTHOG_KEY`, in local UI mode, and in the E2E/test build (`npm run build:test`); `e2e/analytics.spec.ts` proves the last one in a real browser.
- **Transport.** Same-origin through the `/ingest/*` route handler (`src/app/ingest/[...path]/route.ts` + `src/lib/ingestProxy.ts`), not a `next.config` rewrite — OpenNext's rewrite proxy forwards every request header, the `sapling_session` cookie included. The handler builds the upstream request from a header allowlist (conditional `if-none-match` / `if-modified-since` included, so revalidation can 304), streams the body through, refuses any path with an encoded dot/slash/backslash or a dot segment, and marks versioned SDK bundles (`/ingest/static/*.js?v=…`) `immutable`.
- **Content.** Masked autocapture (`mask_all_text`, `mask_all_element_attributes`), no session replay, no exception capture, no copied text. `identify` carries the user UUID only; `person_profiles: 'identified_only'`. Signing in as a different student on the same browser resets first, so two students are never merged into one person.
- **URLs.** The `/auth/callback` handoff params (`auth_token`, `user_id`, `avatar`, `popup_id`, …) are masked by posthog-js at the source (`custom_personal_data_properties`) — that covers the `/flags` request body and heatmap/web-vitals URLs, which `before_send` cannot fully reach — and `before_send` additionally strips every query string and fragment, recursively.
- **Client IP — deliberately not forwarded.** The proxy never passes the browser's IP upstream (no `X-Forwarded-For`, never `cf-connecting-ip`), so PostHog only sees the Cloudflare Worker's egress address; geolocation of that address would be fiction, and forwarding the real one would be personal data we don't need. posthog-js has no IP switch of its own (its `ip` option is a documented no-op), so every event carries `$geoip_disable: true` instead. **The PostHog project setting "Discard client IP data" (project settings, "IP data capture") must be ON** so the Worker address isn't stored as `$ip` either — check it whenever the project is recreated or the key rotated.
- **Capture gate.** Nothing is captured until the UserProvider knows whose page it is: every event passes a gate (`gatedBeforeSend`) that starts closed on page load. An anonymous visitor opens it at once; for a signed-in student it opens only after `GET /api/profile/{user_id}/settings` has answered and their `analytics_opt_out` has been applied — so on a new device an account-opted-out student sends nothing, not even the first `$pageview`. If that read fails, the gate stays shut for the rest of the page load (fail closed). The swallowed initial `$pageview` is re-sent when the gate opens (not for an opted-out student).
- **Opt-out.** Settings → Data → "Product analytics" flips posthog-js consent in this browser at once and PATCHes `analytics_opt_out` to `/api/profile/{user_id}/settings` (the `user_settings.analytics_opt_out` column, backend PR #677). The UserProvider is the one owner of the account value: only an opt-out is ever applied from it — `false` or a missing field (a backend that predates the column) leaves this browser's own choice alone, so a local opt-out always wins. A failed save of an opt-OUT keeps the browser opted out (and says so); a failed save of an opt-IN is reverted, because the next sign-in would re-apply the account's opt-out. Chosen opt-outs are recorded under `sapling_analytics_opt_out` in localStorage, because every posthog-js consent getter folds Do Not Track / GPC in: that key, not posthog-js, decides what survives `reset()`, so a browser signal is never stored as the student's own opt-out. DNT/GPC show the switch as off and disabled (`respect_dnt`).

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
| `NEXT_PUBLIC_POSTHOG_KEY` | browser (build-time inlined) | PostHog product analytics; unset = off | `lib/analytics.ts` (via `instrumentation-client.ts`) |
| `NEXT_PUBLIC_POSTHOG_HOST` | browser (build-time inlined) | Optional `api_host` override; default is the `/ingest` proxy | `lib/analytics.ts` |

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
- ~~**Decide on analytics**~~ — decided: PostHog (US). Wired in `src/lib/analytics.ts` + `src/instrumentation-client.ts`, proxied same-origin through `src/app/ingest/[...path]/route.ts`; masked autocapture, no session replay, account-wide opt-out in Settings → Data. Details and the required "Discard client IP data" project setting in §5a.
- **Add Sentry (or equivalent)**: the rebuild will have new bugs; client error tracking is cheap insurance.
- **Replace `SpaceBackground.tsx` dead import (if later added)** — currently unused.
