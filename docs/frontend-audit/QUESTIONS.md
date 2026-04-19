# Sapling Frontend Audit — Open Questions

Questions raised during the audit. Each entry names file paths and awaits a decision from you before I dig further. Updated as later phases progress.

---

## Phase 1 — exclusion-boundary questions

### Q1. Landing-page-hosted onboarding: where does `OnboardingFlow` belong?
- **Where I saw it:** `src/app/page.tsx:7` imports `OnboardingFlow` from `@/components/OnboardingFlow`. The landing page renders `<OnboardingFlow />` for authenticated-but-not-onboarded users.
- **My current plan:** treat `OnboardingFlow` itself as in-scope (it gates the authenticated app) and treat the surrounding landing-page scaffolding (hero animation, HowItWorks, etc.) as out-of-scope. The audit will document `OnboardingFlow` as a standalone feature.
- **Decision needed:** confirm this split, or tell me you'd rather treat the entire landing page as the onboarding entry point (in which case the hero-to-onboarding transition animations become in-scope too).

### Q2. `SpaceBackground.tsx` appears unused — dead code?
- **Where I saw it:** `src/components/SpaceBackground.tsx:3` exports `SpaceBackground`. A case-insensitive grep of `src/` finds no importer.
- **My current plan:** list it in `zz-dead-code.md` in Phase 4. Will not open or document its contents unless you want it preserved.
- **Decision needed:** keep as dead-code note, or is this meant to be used somewhere (e.g., a WIP page)?

### Q3. `/profile` is not in the middleware matcher — is it really public?
- **Where I saw it:** the middleware matcher (`src/middleware.ts:113-122`) lists protected routes but not `/profile/**`. Navbar's `publicPaths` array also does not include `/profile`. CLAUDE.md describes it as the "public user profile" page.
- **My current plan:** treat `/profile/**` as in-scope (authenticated social surface) and note that it is reachable without a session cookie at the middleware level, so any gating happens client-side.
- **Decision needed:** confirm `/profile` is intended to be viewable by anyone (including logged-out visitors), or should it be gated?

### Q4. `/pending` is not in the middleware matcher — intentional?
- **Where I saw it:** `src/middleware.ts:113-122` does not include `/pending`. It is the destination when the middleware detects an unapproved user (`src/middleware.ts:46`, `src/middleware.ts:104`), so leaving it unguarded makes sense — unapproved users need to land here — but it also means a logged-out visitor can navigate to it directly.
- **My current plan:** treat as in-scope and document behavior as-is.
- **Decision needed:** confirm direct access is fine, or should `/pending` redirect anonymous visitors somewhere?

### Q5. `/signin/callback` listed as a public Navbar path — confirm scope
- **Where I saw it:** `src/components/Navbar.tsx:75` lists `/signin/callback` alongside `/about`, `/terms`, `/privacy`. Despite being "public" in the nav-chrome sense, it is the OAuth landing handler.
- **My current plan:** treat as **in-scope** auth flow and document alongside `/signin`.
- **Decision needed:** none, unless you disagree with treating it as an auth surface rather than a marketing surface.

### Q6. Internationalization
- **Where I saw it:** no i18n library in `package.json`; no locale switch in any file scanned so far; copy appears hard-coded English.
- **My current plan:** state explicitly in the audit that the product is en-US only and that any future i18n is a greenfield concern.
- **Decision needed:** confirm i18n is genuinely out-of-scope for the rebuild, or flag it as a forward-looking requirement.

### Q7. Feature flags / experiments
- **Where I saw it:** only `NEXT_PUBLIC_LOCAL_MODE` has been observed (`src/middleware.ts:54`). No LaunchDarkly, GrowthBook, etc. in `package.json`.
- **My current plan:** note absence in Phase 4. A fuller sweep during Phase 3 may turn up home-grown flags.
- **Decision needed:** none yet; flagging so you can tell me if there is a flag service integrated elsewhere (e.g., via the backend `/api/*`).

### Q8. Frontend Dockerfile — any build-time surprises?
- **Where I saw it:** `frontend/Dockerfile` exists; `CLAUDE.md` describes it as the container image. I have not opened it.
- **My current plan:** open it during Phase 4 if it reveals additional env vars or build steps that materially change the rebuild contract; otherwise ignore.
- **Decision needed:** none.

---

## Phase 2 — route-inventory questions

### Q9. Orphaned routes `/flashcards` and `/achievements`
- **Where I saw it:** neither path has any in-app `Link`, `router.push`, or anchor. Verified with `Grep` across `src/` — only `src/middleware.ts` references them (as guard paths). `Navbar.LINKS` (`src/components/Navbar.tsx:11-19`) does not include them.
- **My current plan:** preserve both routes in the rebuild, but flag the gap.
  - For `/flashcards`: the flashcards experience is also available inside `/study → Flashcards` (`src/app/study/StudyClient.tsx`), so the standalone `/flashcards` page may be legacy. Two divergent implementations may also exist (`flashcards/page.tsx` vs `study/FlashcardsPanel.tsx`) — Phase 3 will flag divergence.
  - For `/achievements`: `/settings` shows *featured* achievements via `AchievementShowcase`, but never links out to the full gallery.
- **Decision needed:**
  - Should `/flashcards` be retired in favor of `/study → Flashcards`, or do you want both?
  - Should `/achievements` be linked from Navbar user-menu, from `/settings`, from a future `/profile`, or stay direct-URL-only?

### Q10. `/profile` route documented in `CLAUDE.md` but does not exist
- **Where I saw it:** `CLAUDE.md` §"Directory Structure" lists `src/app/profile/page.tsx`, and `CLAUDE.md` §"Architecture Notes" describes a separate `/profile` (public view) vs `/settings` (editing) split. In practice, no `profile/` directory exists under `src/app/` (verified by `ls` and Glob). Public-profile data is rendered inside `/settings` as a preview modal (`src/app/settings/page.tsx:183`).
- **Observation:** `src/components/ProfileBanner.tsx` exists but has no importer anywhere in `src/` (verified by Grep).
- **My current plan:** treat `/profile` as **does-not-exist** for the rebuild unless you want it restored. Add `ProfileBanner.tsx` to `zz-dead-code.md` in Phase 4 pending your call.
- **Decision needed:**
  - Was `/profile` removed intentionally, or is it planned work that never shipped?
  - Should the rebuild reintroduce a public `/profile/[userId]` page, or fold public-profile rendering into `/settings` preview only (status quo)?

---

## Phase 3 — feature-deep-dive questions

### Q11. `signOut()` does not clear `sessionStorage.sapling_onboarding_pending`
- **Where I saw it:** `src/context/UserContext.tsx:151-167` clears `localStorage.sapling_user` and in-memory state, but does not touch `sessionStorage`. `sapling_onboarding_pending` is only cleared when the landing page consumes it (`src/app/page.tsx:71`).
- **Repro risk:** on a shared browser, user A aborts mid-onboarding → `sapling_onboarding_pending='true'` is set; user A signs out; user B signs in → `/signin/callback` keeps the flag (sessionStorage survives signout), B is dropped onto the landing-page onboarding overlay with an empty form.
- **My current plan:** flag as a minor bug; the rebuild should unconditionally clear `sessionStorage.sapling_onboarding_pending` in `signOut()`.
- **Decision needed:** confirm this is a bug (fix in the rebuild) vs. intentional (keep as-is).

### Q12. Onboarding POST errors are silent
- **Where I saw it:** `src/app/page.tsx:569-571` — `catch (e) { console.error(...); }`. User is sent to `/dashboard` regardless of whether `POST /api/onboarding/profile` succeeded.
- **My current plan:** rebuild should surface the error with a Toast and a "Retry" affordance before redirecting.
- **Decision needed:** confirm stronger error handling is wanted (vs. the current "never block the user" philosophy).

### Q15. Navigate-away session feedback cooldown: 3 days in code, 2 days in CLAUDE.md
- **Where I saw it:** `src/components/SessionFeedbackGlobal.tsx:9` → `COOLDOWN_MS = 3 * 86_400_000` (3 days). `CLAUDE.md` §"Architecture Notes" says "2-day cooldown".
- **Decision needed:** confirm which value is intended; update whichever source is wrong.

### Q16. Learn chat says streaming (SSE) in CLAUDE.md but frontend uses plain JSON
- **Where I saw it:** `CLAUDE.md` describes `backend/routes/learn.py` as "streaming AI tutoring chat endpoint (SSE)". The frontend (`src/lib/api.ts:90-94`, `sendChat`) does `fetchJSON<...>` — a normal `fetch` consuming `.json()`. No `EventSource`, no `ReadableStream` handling anywhere in `/learn`.
- **Decision needed:** is the backend actually streaming (and the frontend just ignores the stream, waiting for the closing JSON payload)? If so, the rebuild should implement real streaming (typewriter-style reply rendering) — this is a big UX win. If not, drop "(SSE)" from CLAUDE.md.

### Q17. Clicking a graph node during an active Learn session orphans the old session
- **Where I saw it:** `src/app/learn/page.tsx:338-343` (`handleNodeClick`) calls `beginSession(newTopic, mode, courseId)` without first calling `endSession(oldSessionId, userId)`. The old session stays in the DB with `is_active=true` until a server-side timeout cleans it up (if any exists).
- **My current plan:** flag as a bug; rebuild should `endSession` before starting a new one (or the backend should enforce single-active-session-per-user).
- **Decision needed:** confirm it's a bug vs. a deliberate design that relies on a backend cleanup job.

### Q14. Dashboard "Dismiss" on AI-recommendation popup routes to `/` instead of `/dashboard`
- **Where I saw it:** `src/app/dashboard/page.tsx:857` — `onClick={() => router.replace('/')}` on the Dismiss button. `/social` has the same popup pattern and correctly routes back to itself (`src/app/social/page.tsx:264`).
- **My current plan:** treat as a bug; rebuild should `router.replace('/dashboard')` (or just clear the `?suggest=` query param).
- **Decision needed:** confirm it's a bug.

### Q13. Onboarding hardcodes Boston University
- **Where I saw it:** `src/components/OnboardingFlow.tsx:137` sets `school: 'Boston University'` in initial state and the step 2 UI renders it as an uneditable block (`OnboardingFlow.tsx:434-441`). `BU_MAJORS`/`BU_MINORS` are hardcoded arrays.
- **My current plan:** if multi-school is on the roadmap, source these from the backend.
- **Decision needed:** is Sapling intended to stay single-school, or should the rebuild generalize this?

---

*This file will grow in later phases. Every new question includes the exact file path and line range that triggered it.*
