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

- **Used by the backend only** (`backend/services/gemini_service.py`). Frontend never calls Gemini directly.
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

## 6. External services NOT used

Worth being explicit: no evidence of any of these in the frontend. If the rebuild adds them, they're greenfield.

- Stripe / Paddle / billing.
- Intercom / Crisp / in-app chat widgets.
- Mixpanel / Segment / Heap / analytics.
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
- **Decide on analytics**: product should pick one (Plausible/Mixpanel/PostHog) before rebuild so it can be wired consistently, not bolted on later.
- **Add Sentry (or equivalent)**: the rebuild will have new bugs; client error tracking is cheap insurance.
- **Replace `SpaceBackground.tsx` dead import (if later added)** — currently unused.
