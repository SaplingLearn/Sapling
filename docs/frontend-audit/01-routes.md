# Sapling Frontend Audit — 01 · Route Inventory

> **Scope.** Every in-scope route in the Next.js App Router tree, its component, its auth/guard behavior, the query-params it reads, which layout wraps it, and what it is for. Out-of-scope marketing routes are listed at the bottom with one line each, for completeness only. Per-feature flows (what happens when you click around inside a route) are deferred to Phase 3.

---

## 1. Layout tree — every in-scope route uses the root layout only

- `frontend/src/app/layout.tsx` is the **only** layout in the entire App Router tree — verified by glob (`app/**/layout.tsx` returns exactly one file). No nested layouts, no route groups, no parallel routes (`@*`), no intercepting routes (`(.)`), no `loading.tsx`, and no `not-found.tsx`.
- Root layout wraps every route with: `<UserProvider>` → `<Navbar />` → `<main><ErrorBoundary><ToastProvider>{children}` → `<FeedbackFlow />` (Suspense) + `<SessionFeedbackGlobal />` (Suspense). (`src/app/layout.tsx:53-68`)
- `frontend/src/app/error.tsx` is the root error boundary page (`'use client'`, renders a "Something went wrong" card with a `reset()` button). Triggered automatically by Next on any uncaught render error in a page below the root.
- Navbar hides itself on "public" paths (`/`, `/signin/callback`, `/about`, `/terms`, `/privacy`, and anything starting with `/careers`). See `Navbar.tsx:75-84`. All in-scope pages therefore show the Navbar **except** `/signin/callback` (intentionally — it's the OAuth spinner screen).

Implication for the rebuild: every in-scope page can assume `useUser()`, `useToast()`, `ErrorBoundary`, and the global `FeedbackFlow`/`SessionFeedbackGlobal` are already mounted.

---

## 2. Middleware guard behavior (summary from Phase 1)

Declared in `src/middleware.ts`:

- **Matcher** (`src/middleware.ts:113-122`): `/signin`, `/dashboard/:path*`, `/learn/:path*`, `/study/:path*`, `/tree/:path*`, `/flashcards/:path*`, `/library/:path*`, `/calendar/:path*`, `/social/:path*`, `/settings/:path*`, `/achievements/:path*`, `/admin/:path*`.
- **`/signin`** (`src/middleware.ts:60-68`): if signed-in-and-approved → redirect `/dashboard`; if signed-in-and-unapproved → redirect `/pending`; else if `?error=` is in URL, render the page; else redirect to `${NEXT_PUBLIC_API_URL}/api/auth/google`.
- **Every other matched route** (`src/middleware.ts:70-108`): require valid HMAC `sapling_session` cookie **and** live `GET /api/auth/me` returning `is_approved: true`. Unapproved → `/pending`. Missing/invalid/expired/backend-down → Google OAuth.
- **Bypass**: `NEXT_PUBLIC_LOCAL_MODE=true` → middleware is a no-op (`src/middleware.ts:54-56`).

Not in the middleware matcher (and therefore not guarded by Next middleware): `/`, `/about`, `/privacy`, `/terms`, `/careers/**`, `/signin/callback`, `/pending`, `/api/*` (Next route handler). Any gating on those pages happens client-side (or in the Route Handler for `/api/auth/session`).

---

## 3. In-scope route table

Legend: **Auth** — `middleware` = guarded by `middleware.ts`; `client` = additional client-side redirect; `none` = no guard. **Deep links** = query-params the page reacts to.

| Path | Component file(s) | Auth | Entry points (who navigates here) | Deep links | Purpose |
|---|---|---|---|---|---|
| `/error.tsx` (root error boundary) | `src/app/error.tsx` (`GlobalError`) | n/a | Auto — fires on uncaught render errors | n/a | Full-viewport "Something went wrong" with `reset()` button. |
| `/signin` | `src/app/signin/page.tsx` (`SignInPage` → `Suspense` → `SignInInner`) | `middleware` (redirect-heavy; see §2) | `Navbar → Sign out` → `router.push('/')` → middleware redirect; `/pending` "Sign out" → `router.replace('/signin')`; direct bookmark | `?error=<not_approved\|invalid_domain\|google_not_configured\|signin_failed\|...>` | Google sign-in landing. If `?error=` present, shows error copy + "Try again with Google" button that hard-redirects to `${API}/api/auth/google`. On mount, if `localStorage.sapling_user.id` exists, POSTs to `/api/auth/session` to re-establish the cookie (200 → `/dashboard`, 403 → `/pending`). Suspense wrapper is required because `useSearchParams` needs it in app router. |
| `/signin/callback` | `src/app/signin/callback/page.tsx` (`CallbackPage` → `Suspense` → `CallbackInner`) | none (middleware does not match `/signin/callback`) | Backend OAuth redirect from `/api/auth/google/callback` | `?user_id`, `?name`, `?avatar`, `?is_approved=true\|false`, `?auth_token`, `?error=not_approved` | OAuth return handler. Validates the required params, calls `setActiveUser` + `confirmApproved` on UserContext, POSTs to `/api/auth/session` with `{userId, authToken}`, then chooses destination: if `sessionStorage.sapling_onboarding_pending` is set → `/`; else hits `/api/auth/me` and routes to `/dashboard` if `onboarding_completed`, otherwise sets `sessionStorage.sapling_onboarding_pending='true'` and goes to `/`. Errors → `/signin?error=...`. Renders only a "Signing you in..." spinner. |
| `/api/auth/session` (route handler) | `src/app/api/auth/session/route.ts` | Server route — `SESSION_SECRET` guards the fast-path | Client fetch from `/signin`, `/signin/callback`, `UserContext.signOut()` | n/a | Next.js Route Handler (server). **POST**: accepts `{userId, authToken?}`; if `authToken` present, HMAC-verifies it locally (no backend round-trip); otherwise falls back to calling backend `/api/auth/me` to verify `is_approved`. On success, signs an HMAC session with `signSession()` and sets `sapling_session` as HTTP-only `sameSite=lax` cookie for `SESSION_MAX_AGE`. Returns 400/401/403/500/502 on various failure modes. **DELETE**: clears `sapling_session` (max-age 0). Uses Web Crypto (`crypto.subtle`) for HMAC verification, not Node's `crypto`. |
| `/pending` | `src/app/pending/page.tsx` (`PendingPage`) | none (middleware doesn't match; unapproved users are redirected *to* here by middleware) | Middleware redirect from any protected route when `is_approved !== true`; `/signin` client-side POST returning 403 | none | Dead-simple waitlist screen with the Sapling wordmark, a "You're on the waitlist" heading, a single paragraph of explanatory copy, and a "Sign out" button that calls `useUser().signOut()` then `router.replace('/signin')`. Uses CSS custom properties `--bg-base`, `--brand-text1/2` (dark theme tokens). |
| `/dashboard` | `src/app/dashboard/page.tsx` (`DashboardInner` wrapped by `Suspense` via `DashboardInner` import — actually exports default — see note) | `middleware` (requires approved session) | Middleware redirect after sign-in; Navbar "Dashboard"; logo-to-home link | `?suggest=<concept>` (from Navbar "What should I learn next?") | Main landing page post-signin. Greeting with typewriter animation, random quote, weekly activity strip (Mon–Sun derived from `node.last_studied_at`), main **KnowledgeGraph** panel with fullscreen toggle, **Courses** side panel (list + search/add/delete + inline color picker), **Stats** summary (mastered/learning/struggling/unexplored), upcoming assignments strip, top-3 recommendations. Mobile: collapsible sidebar with `courses`/`stats` tabs. Fetches `getGraph`, `getRecommendations`, `getUpcomingAssignments`, `getCourses` in parallel. |
| `/learn` | `src/app/learn/page.tsx` (`LearnInner` wrapped in `Suspense`) | `middleware` | Navbar "Learn"; `?suggest=` from Navbar; from `/social` RoomOverview "open in learn"; from Dashboard recommendations | `?topic=<string>`, `?mode=socratic\|expository\|teachback\|quiz`, `?suggest=<concept>`, `?testFeedback=session` | AI tutoring session. Left side: **KnowledgeGraph** with suggestion highlighting; Right side: **ChatPanel** or **QuizPanel** or **SessionSummary**; above: **ModeSelector** + course `CustomSelect` + `SharedContextToggle` + `AIDisclaimerChip`. Mobile: toggles between `chat`/`graph` views. Persists shared-context toggle in `localStorage.sapling_shared_ctx`. Tracks session-end count in `localStorage.sapling_session_end_count` and triggers `SessionFeedbackFlow` every 5th end. Calls `startSession`, `sendChat`, `sendAction`, `endSession`, `switchMode`, `resumeSession`, `deleteSession`, `getSessions`, `getGraph`, `getCourses`. |
| `/study` | `src/app/study/page.tsx` → `src/app/study/StudyClient.tsx` (+ `src/app/study/FlashcardsPanel.tsx`) | `middleware` | Navbar "Study"; Calendar (if linked) | none (mode toggled via in-page state: `'study-guide'` / `'flashcards'`) | Exam study hub. Uses raw `fetch` (not `lib/api.ts`) against `/api/study-guide/...` and `/api/flashcards/...`. Two modes — **Study Guide** (selection → loading → rendered guide; course + exam pickers; cached guides list with open/regenerate; overview + topic cards each listing concepts) and **Flashcards** (delegates to `FlashcardsPanel`). Mobile layout is vertical. |
| `/tree` | `src/app/tree/page.tsx` (`TreePageInner` wrapped in `Suspense`) | `middleware` | Navbar "Tree"; `?suggest=` from Navbar | `?suggest=<concept>` | Full-viewport **KnowledgeGraph**. Side panel with filter chips (`all`/`mastered`/`learning`/`struggling`/`unexplored`) and a text search. Selecting a node opens a detail card with mastery meta and last-studied time. Edges across different subjects are hidden (only same-subject edges + subject roots shown). |
| `/flashcards` | `src/app/flashcards/page.tsx` (`FlashcardsPage`) | `middleware` | **No in-app link from any page** (orphaned — see §4). Direct URL only. | none | Flashcard deck browser + AI flashcard generator + study mode. Tabs `cards`/`generate` on mobile. Flashcards filtered by `topic`. Study mode: flip animation, spaced-repetition-style rating (`rateFlashcard`). Calls `generateFlashcards`, `getFlashcards`, `rateFlashcard`, `deleteFlashcard`, `getCourses`. |
| `/library` | `src/app/library/page.tsx` (`LibraryPage`) | `middleware` | Navbar "Library"; possible from `/calendar` upload flow | none | Document library. Course-pill sidebar + category chips (`syllabus`/`lecture_notes`/`slides`/`reading`/`assignment`/`study_guide`/`other`). Grid of doc cards; clicking one opens a right-side detail panel showing summary, reveal-on-click card list, and delete confirmation. Upload CTA opens `DocumentUploadModal`. Calls `getCourses`, `getDocuments`, `deleteDocument`. |
| `/calendar` | `src/app/calendar/page.tsx` (wrapped in `Suspense`) | `middleware` | Navbar "Calendar"; Google Calendar OAuth return | `?connected=true` (set after Google OAuth callback) | Assignment calendar — **month/week/day** views, per-type color coding (`exam`/`project`/`homework`/`quiz`/`reading`/`other`). Google Calendar integration: connect, sync-to-Google, import-from-Google, disconnect. Upload modal triggers syllabus re-processing (assignments re-pulled 1.5s after close to catch insert race). Calls `getAllAssignments`, `getCalendarStatus`, `syncToGoogleCalendar`, `importGoogleEvents`, `disconnectGoogleCalendar`, `getCourses`. |
| `/social` | `src/app/social/page.tsx` (`SocialPageInner` wrapped in `Suspense`) | `middleware` | Navbar "Social"; `?suggest=` from Navbar | `?suggest=<concept>` | Study-rooms hub. Left sidebar: `RoomList`. Main area: either `SchoolDirectory` (when "school view" is active) or a tabbed room panel with **Overview** (`RoomOverview`), **Chat** (`RoomChat` — Supabase Realtime subscription), **Study Match** (`StudyMatch`), **Activity** (inline activity feed). A "Members" button toggles a `RoomMembers` panel. If `?suggest` present, auto-focuses Overview and the matching node. Accepting a suggestion routes to `/learn?topic=<>&mode=quiz`. |
| `/settings` | `src/app/settings/page.tsx` (`SettingsPage`) | `middleware` | User-menu (Navbar) "Settings" | none | Settings page with left sidebar grouped into **Identity** (Profile, Account), **Preferences** (Notifications, Appearance, Privacy), **Personalization** (Cosmetics), **Manage** (Danger Zone). Profile form with live username availability check (debounced). Cosmetics editor (`CosmeticsManager`). Featured achievements picker (`AchievementShowcase`). Avatar upload (`uploadAvatar`). Danger Zone: `exportData`, `deleteAccount`. Hosts a **Profile Preview modal** that fetches `fetchPublicProfile` + `fetchAchievements` to show how your public profile looks. |
| `/achievements` | `src/app/achievements/page.tsx` (`AchievementsPage`) | `middleware` | **No in-app link from any page** (orphaned — see §4). Direct URL only. | none | Full achievements gallery with category pill filters (`all`/`activity`/`social`/`milestone`/`special`). Cards via `AchievementCard`, expandable per-achievement. Fetches `fetchAchievements(userId)` → `{ earned, available }`. |
| `/admin` | `src/app/admin/page.tsx` (`AdminPage`) | `middleware` + client-side `isAdmin` check — non-admins are `router.push('/dashboard')` on mount and the page returns `null` | User-menu (Navbar) "Admin" — only rendered when `isAdmin` | none | Admin panel with four tabs: **Users** (list + approve), **Roles** (create role with name/slug/color; assign/revoke elsewhere), **Achievements** (create achievement with name/slug/category/rarity; grant-to-user form with user-id + achievement-id inputs), **Cosmetics** (create cosmetic with type/name/slug/rarity). Calls `adminFetchUsers`, `adminApproveUser`, `adminAssignRole`, `adminRevokeRole`, `adminCreateRole`, `adminCreateAchievement`, `adminGrantAchievement`, `adminCreateCosmetic`. Shows toasts for success/error via `useToast`. |

### 3.1 Query-param deep-link cheatsheet

One-page reference so the rebuild can keep the same URL contracts.

| URL | Used by |
|---|---|
| `/signin?error=not_approved` | Callback when backend returns `is_approved=false`; also from `/signin/callback` on missing fields |
| `/signin?error=invalid_domain` | Backend OAuth reject for non-school email |
| `/signin?error=google_not_configured` | Middleware when `NEXT_PUBLIC_API_URL` is missing |
| `/signin?error=signin_failed` | Callback when required params (`user_id`/`name`) are missing |
| `/signin/callback?user_id&name&avatar&is_approved&auth_token` | Backend OAuth success redirect |
| `/dashboard?suggest=<concept>` | Navbar "What should I learn next?" when user is on `/dashboard` |
| `/learn?topic=<string>` | Set as starting topic for a new session |
| `/learn?mode=<socratic\|expository\|teachback\|quiz>` | Set initial tutoring mode; `quiz` auto-enables `quizMode` |
| `/learn?suggest=<concept>` | Navbar recommendation routing |
| `/learn?testFeedback=session` | Dev/QA trigger to force the session feedback modal to open |
| `/tree?suggest=<concept>` | Navbar recommendation routing |
| `/social?suggest=<concept>` | Navbar recommendation routing; auto-focuses the matching concept in the current user's Room graph |
| `/calendar?connected=true` | Google Calendar OAuth success return — sets `googleConnected = true` and renders the "connected" state |

### 3.2 Persistence keys referenced by routes

| Storage | Key | Set by | Read by | Purpose |
|---|---|---|---|---|
| Cookie (HTTP-only) | `sapling_session` | `/api/auth/session` POST | `middleware.ts` (+ `lib/sessionToken.ts`) | HMAC session token; `SESSION_MAX_AGE` |
| `localStorage` | `sapling_user` | `UserContext` on sign-in | `/signin` to auto-exchange | Cached user `{id, name, avatar}` for post-logout/pre-login hand-off |
| `localStorage` | `sapling_shared_ctx` | `/learn` toggle | `/learn` initial state | Remember "shared course context" toggle |
| `localStorage` | `sapling_session_end_count` | `/learn` on session end | `/learn` + `SessionFeedbackGlobal` | Every 5th increment triggers session feedback modal |
| `sessionStorage` | `sapling_onboarding_pending` | `/signin/callback` when `onboarding_completed=false` | `/signin/callback` on subsequent mount; also cleared by `OnboardingFlow` on completion (verify in Phase 3) | Keeps user on `/` (the landing-hosted `OnboardingFlow`) until they finish onboarding |

Additional keys may exist inside feature components (ChatPanel, DisclaimerModal, etc.) — those will be caught in Phase 4 (`03-state.md`).

---

## 4. Orphaned routes — reachable only by direct URL

A ripgrep of the entire `src/` tree for `"/flashcards"` and `"/achievements"` returns only `src/middleware.ts` mentions. No `<Link>`, `router.push`, or hard-coded anchor in any component points at them.

- **`/flashcards`** — the page exists and is functional, but the Navbar does not include it in the `LINKS` array (`Navbar.tsx:11-19` lists Dashboard, Learn, Study, Library, Calendar, Social, Tree). The only in-app flashcard surface wired into the nav is `FlashcardsPanel` embedded inside `/study` — which is the same flashcards feature, duplicated.
- **`/achievements`** — the page exists but is not linked anywhere. `/settings` shows a featured-achievements showcase but does not link to the full gallery.

This is a potential product-decision question for the rebuild (flagged in `QUESTIONS.md` Q9/Q10): is `/flashcards` intentionally hidden because `/study > Flashcards` replaces it, and is `/achievements` meant to be reached only through an eventual profile link (the missing `/profile` route — see §6)?

---

## 5. Out-of-scope routes (for completeness only, not opened)

The audit will not document these. Listed so the rebuild knows which URLs existed and can reproduce them as marketing pages if desired.

| Path | File | Category |
|---|---|---|
| `/` | `src/app/page.tsx` | Landing / hero / HowItWorks — **also hosts `<OnboardingFlow />` for authenticated-but-not-onboarded users (the onboarding component is in-scope, the landing shell is not).** |
| `/about` | `src/app/about/page.tsx` | Marketing |
| `/privacy` | `src/app/privacy/page.tsx` | Marketing |
| `/terms` | `src/app/terms/page.tsx` | Marketing |
| `/careers` | `src/app/careers/page.tsx` | Marketing (job board) |
| `/careers/[slug]` | `src/app/careers/[slug]/page.tsx` + `ApplyForm.tsx` + `jobs.ts` | Marketing (dynamic route; uses static `jobs.ts` list) |

---

## 6. Notable gaps vs. the repo CLAUDE.md

The root `CLAUDE.md` mentions the following which are **stale** — noted here so the rebuild doesn't chase ghosts. None of these change the route inventory, but they change expectations set by the README-style docs.

- **`/profile/page.tsx`** is documented in `CLAUDE.md` but **does not exist** in `src/app/`. No `profile/` directory exists. Verified by `ls` and Glob. Public-profile data (`fetchPublicProfile`) is only rendered inside `/settings` as a preview modal. Components named `ProfileBanner` and `AvatarFrame` exist but `ProfileBanner` is not imported anywhere in `src/` — candidate for `zz-dead-code.md` in Phase 4 (also noted in `QUESTIONS.md` Q10).
- **`UploadZone.tsx` vs `DocumentUploadModal.tsx`.** CLAUDE.md mentions `UploadZone.tsx` as the upload component; the routes actually import `DocumentUploadModal.tsx`. Both files exist; importer analysis for `UploadZone` is deferred to Phase 4.

These observations are additive to the ones in `QUESTIONS.md`.

---

## 7. What Phase 2 did NOT do

- Did not document what each page *does* beyond a one-paragraph purpose line — flow-by-flow walk-throughs live in Phase 3.
- Did not enumerate the components imported by each page — that's Phase 4's `02-components.md` job, where the component library gets its own inventory with prop surfaces and importer lists.
- Did not open any marketing file.
- Did not resolve Q1–Q10 in `QUESTIONS.md`.

Proceeding to Phase 3 unless you want boundary tweaks first.
