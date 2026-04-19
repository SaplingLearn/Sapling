# Sapling Frontend Audit — 99 · Rebuild Checklist

> The contract the revamped frontend must satisfy. Every item here is either (a) an existing behavior the rebuild must preserve, or (b) a known gap that should be closed as part of the rebuild. Grouped by priority: **Core** (can't ship without), **Secondary** (needed for parity), **Nice-to-have** (opportunistic improvements). Cross-references point at the feature / cross-cutting docs with implementation detail.

When a box is checked, it means the behavior is captured and testable. Use this list as the acceptance criteria for rebuild sign-off.

---

## A · CORE (ship-blocking)

### A.1 Auth & session
- [ ] Google OAuth entry point: redirect to `${API}/api/auth/google`. (`features/auth.md`)
- [ ] OAuth callback at `/signin/callback` reads `user_id, name, avatar, is_approved, auth_token, error` query params; sets UserContext; POSTs to `/api/auth/session` with `{userId, authToken}`; routes to `/dashboard` or `/` based on `onboarding_completed`.
- [ ] `/api/auth/session` POST: fast-path HMAC verify of `authToken`; fallback to `GET /api/auth/me` when `authToken` absent; issue 30-day HTTP-only `sameSite=lax` `sapling_session` cookie; return 400/401/403/500/502 with appropriate messages.
- [ ] `/api/auth/session` DELETE: clear cookie.
- [ ] Middleware guards these paths: `/signin`, `/dashboard/**`, `/learn/**`, `/study/**`, `/tree/**`, `/flashcards/**`, `/library/**`, `/calendar/**`, `/social/**`, `/settings/**`, `/achievements/**`, `/admin/**`. (`05-auth-and-permissions.md`)
- [ ] Middleware re-checks `GET /api/auth/me` on every protected navigation with a 3-second AbortController timeout.
- [ ] Unapproved users redirect to `/pending` on every protected nav (live revocation).
- [ ] `/signin?error=<code>` renders the error UI; all other `/signin` visits redirect to Google OAuth (or to `/dashboard`/`/pending` if signed in).
- [ ] `/pending` waitlist screen: logo, heading, Sign Out button.
- [ ] `signOut()` clears cookie + localStorage + in-memory state + `sessionStorage.sapling_onboarding_pending` (fix for Q11).
- [ ] `NEXT_PUBLIC_LOCAL_MODE=true` bypasses middleware and routes `lib/api.ts` through an in-memory mock layer.

### A.2 Onboarding
- [ ] 6-step form: Google → Name → School + Year → Academics (majors + minors) → Courses → Learning Style. (`features/onboarding.md`)
- [ ] `sessionStorage.sapling_onboarding_pending` bridges Google's redirect back into the onboarding resume flow.
- [ ] Course search via debounced `GET /api/onboarding/courses?q=` (200ms debounce).
- [ ] Completion POSTs to `/api/onboarding/profile` with `{user_id, first_name, last_name, year, majors, minors, course_ids, learning_style}`.
- [ ] Learning-style IDs: `visual`, `reading`, `auditory`, `hands-on`, `mixed` (contract with backend prompt system).
- [ ] Escape closes; X button closes; "Continue" button gated by per-step validation.

### A.3 Global shell
- [ ] Root layout mounts `UserProvider`, `Navbar`, `ErrorBoundary`, `ToastProvider`, global `FeedbackFlow`, global `SessionFeedbackGlobal`.
- [ ] `app/error.tsx` full-page error boundary with reset button.
- [ ] `ToastProvider` + `useToast()` with portal-rendered stack, 5s default duration, manual dismiss, ReactNode content.
- [ ] Navbar public-mode hides itself on `/`, `/signin/callback`, `/about`, `/terms`, `/privacy`, `/careers/*`.
- [ ] Navbar links: Dashboard / Learn / Study / Library / Calendar / Social / Tree.
- [ ] Navbar user menu: "Signed in as {name}", Settings, Admin (if isAdmin), Sign out.
- [ ] Navbar "What should I learn next?" button uses top recommendation and routes to `${currentPath}?suggest=<concept>` (or `/learn?suggest=` when on `/calendar`).
- [ ] Outside-click and Escape close the menu.
- [ ] Report-issue entry in Navbar opens `ReportIssueFlow`.

### A.4 Dashboard
- [ ] Four parallel fetches on mount: `getGraph`, `getRecommendations`, `getUpcomingAssignments`, `getCourses`. Single spinner; single error card with Retry.
- [ ] KnowledgeGraph center panel + Upcoming assignments strip below.
- [ ] Left panel: typewriter greeting + random quote + per-course progress bars with collapse + Manage Courses modal.
- [ ] Right panel / mobile stats tab: Streak (from `stats.streak`) + weekly activity (Mon-first, today orange, 🔥 on active days) + knowledge tier counts + top-3 Learn Next + Quick Quiz (`/learn?mode=quiz`) + Study Room (`/social`) + Recent Activity (sorted by `last_studied_at`).
- [ ] Fullscreen graph overlay with Escape to exit + body scroll lock.
- [ ] Courses modal: search-to-add (debounced typeahead against `/api/onboarding/courses`), inline color picker (hex validated `^#[0-9a-fA-F]{6}$`), two-step delete.
- [ ] `?suggest=<concept>` popup with Dismiss (clears param — fix Q14) and Start Quiz → `/learn?topic=&mode=quiz`.
- [ ] Mobile layout with "My Courses" / "Stats & More" toggle tabs.

### A.5 Learn (AI Tutoring)
- [ ] Three modes with exact vocabulary: **Socratic**, **Expository**, **TeachBack**. (`features/learn.md`)
- [ ] `ChatPanel`: Enter sends, Shift+Enter newline; markdown + KaTeX math rendering; mode description banner.
- [ ] Quick actions: hint / confused / skip → `POST /api/learn/action`.
- [ ] End session → `POST /api/learn/end-session` → `SessionSummary` modal (concepts covered, mastery changes with color-coded deltas, time spent, recommended next).
- [ ] Mode switch mid-session → `POST /api/learn/mode-switch` + prefill input with "Continue in {mode} mode on {topic}...".
- [ ] Resume session dropdown with per-item delete.
- [ ] URL contract: `?topic`, `?mode=socratic|expository|teachback|quiz`, `?suggest`, `?testFeedback=session`.
- [ ] `?suggest=` Dismiss preserves other query params (URLSearchParams pattern, not `router.replace('/learn')`).
- [ ] **Shared Course Context toggle** labeled "Class Intel" with hover tooltip explaining aggregated class-level patterns + privacy notice. Persists to `localStorage.sapling_shared_ctx` (default `true`).
- [ ] AI disclaimer first-view modal; `AIDisclaimerChip` in top bar; `localStorage.sapling_disclaimer_ack`.
- [ ] Quiz mode (four phases: select / active / review / results) with `CustomSelect` for question count + difficulty; concept list filtered by course; local correctness check; "Explain this" escape hatch on review; "Retake" + "Learn Weak Areas" on results.
- [ ] Live graph pane updates after every chat turn; highlight ring on `suggestNode?.id ?? topicNode?.id`.
- [ ] Click a graph node → `beginSession(concept, mode, course_id)`.
- [ ] Every-5-sessions feedback trigger via `localStorage.sapling_session_end_count`.
- [ ] Navigate-away feedback trigger via `SessionFeedbackGlobal` with 3-day cooldown (resolve Q15 — confirm 3 days, not 2).
- [ ] `SessionFeedbackFlow` 4-step card with rating emojis, categorized checkboxes, optional comment, thank-you auto-dismiss.

### A.6 Study (Guide + Embedded Flashcards)
- [ ] Mode toggle between Study Guide and Flashcards; FlashcardsPanel stays mounted across toggles.
- [ ] Course → Exam cascading picker; Generate Guide → loading → rendered guide.
- [ ] Guide layout: Exam card (title + due date + overview) + per-topic cards (name + importance + bulleted concepts).
- [ ] "Recent guides" sidebar with click-to-open.
- [ ] Regenerate button.

### A.7 Flashcards (standalone or merged)
- [ ] Decision: keep `/flashcards` standalone OR remove and redirect to `/study?mode=flashcards`. Flag in Q9.
- [ ] Generator using enrolled courses (one-click per course), max 10 cards.
- [ ] "Generated using N library docs / M weak concepts" chip when `context_used` returned.
- [ ] Full-screen study mode with 3D flip card (0.55s cubic-bezier `rotateY(180deg)`).
- [ ] Rating: Forgot / Hard / Easy → 1 / 2 / 3 → `rateFlashcard`.
- [ ] Auto-advance 300ms after rating.
- [ ] Topic filter pills on the deck view.
- [ ] Delete card via `×` icon.

### A.8 Tree (Full KnowledgeGraph)
- [ ] Full-viewport graph with floating controls (search + mastery filter pills + "N nodes" counter).
- [ ] Per-node detail panel (right on desktop, bottom sheet on mobile) with mastery/tier/last-studied.
- [ ] `?suggest=` popup; Dismiss clears param.

### A.9 Library (Documents)
- [ ] Course sidebar + category pills (`syllabus`, `lecture_notes`, `slides`, `reading`, `assignment`, `study_guide`, `other`).
- [ ] Card grid; click opens right-side detail panel.
- [ ] Detail panel: summary + key takeaways + Q/A flashcards (reveal-on-click) + delete (two-step).
- [ ] `DocumentUploadModal`: drag-and-drop multi-file upload, 5 file max, 15 MB each, PDF/DOCX/PPTX only. (`features/library.md`)
- [ ] Per-file upload with 4-minute AbortController timeout; friendly abort message.
- [ ] Per-file review step with AI-picked category + override + Re-analyze.
- [ ] Disallow close during active uploads.
- [ ] Inline "+ Add course" within upload flow.
- [ ] Post-upload: if any doc is `category='syllabus'`, parent page refetches assignments (Calendar syllabus flow).

### A.10 Calendar
- [ ] Three views: month / week / day; type-color coded chips.
- [ ] Editable `AssignmentTable` with drag reorder (Manual order only), inline edit, multi-select for export.
- [ ] Google Calendar: Connect → `GET /api/calendar/auth-url` → OAuth → `?connected=true` → `googleConnected=true`.
- [ ] Sync to Google / Import from Google / Disconnect (with confirm).
- [ ] Syllabus upload via `DocumentUploadModal` triggers assignment refetch (plus 1.5s delayed re-fetch for insert races).
- [ ] "Due soon" = within 24 hours.

### A.11 Social (Rooms / Chat / Match / School Directory)
- [ ] `RoomList` sidebar: Create/Join buttons, room list, "My School" entry.
- [ ] Create room → invite code + Copy (2s "Copied!"); Join room → by invite code.
- [ ] Tabs: Overview / Chat / Study Match / Activity + Members button (top-right of main panel).
- [ ] Overview: AI summary, invite code, partner-comparison graph with 4-color outline rings (you-only cyan / them-only orange / both-missing red / both-mastered green).
- [ ] Chat (`RoomChat`): Supabase Realtime subscriptions for `room_messages` INSERT/UPDATE and `room_reactions` INSERT/DELETE (+ scope reactions by room — fix cross-room flood).
- [ ] Presence channel for typing indicators with 3s idle timeout.
- [ ] Optimistic send with `tmp_${Date.now()}` ID and rollback on error.
- [ ] Reply + Edit + Delete + Reactions (50-emoji grid) with context menu.
- [ ] @mention autocomplete with Arrow / Tab / Enter / Escape.
- [ ] Image attachments (rebuild: upload to Supabase Storage instead of data URLs).
- [ ] Message pagination (rebuild addition — `getRoomMessages` currently returns all).
- [ ] `StudyMatch`: Find Study Partners → sorted matches; best-match popup on first find.
- [ ] `RoomMembers`: list with Leader tag, kick (leader only) with two-step confirm, leave with two-step confirm.
- [ ] `SchoolDirectory`: grid of students with initials, courses, top concepts, "You" tag.
- [ ] `?suggest=` auto-focuses Overview tab and the matching node.

### A.12 Settings
- [ ] Grouped nav: Identity (Profile, Account), Preferences (Notifications, Appearance, Privacy), Personalization (Cosmetics), Manage (Danger Zone).
- [ ] Profile form: display_name, username, bio, location, website; avatar upload via hidden file input.
- [ ] **Fix** username "availability check" to be a separate GET, not a PATCH that mutates.
- [ ] Appearance: dark mode via `.dark` on `<html>`; saves to `saveSettings({theme})`; revert on save error.
- [ ] Cosmetics tabs: Avatar Frames / Banners / Name Colors / Titles with equip/unequip (re-click to unequip). `refreshProfile()` on change.
- [ ] Profile Preview modal fetching public profile + achievements.
- [ ] Danger Zone: Export data → JSON download; Delete account requires typed "DELETE" → on success, sign out + redirect to `/signin`.
- [ ] Toast feedback on every mutation.

### A.13 Admin
- [ ] Middleware + client-side `isAdmin` guard; redirect non-admins to `/dashboard`.
- [ ] Four tabs: Users, Roles, Achievements, Cosmetics.
- [ ] Users tab: list + Approve for pending users; `RoleBadge` per role.
- [ ] Create-role form (Name, Slug, Color).
- [ ] Create-achievement form + Grant-achievement form (pickers, not raw UUIDs — rebuild improvement).
- [ ] Create-cosmetic form + asset upload (rebuild improvement; current UI has no asset upload).
- [ ] Role-assignment/revocation UI (rebuild — currently missing despite `lib/api.ts` support).
- [ ] Toast feedback on every action.

### A.14 Achievements (decide one of)
- [ ] `/achievements` gallery with category pill filter (all / activity / social / milestone / special).
- [ ] `AchievementCard` with rarity borders/bg (common/uncommon/rare/epic/legendary), progress bar for locked, earned date.
- [ ] Secret achievements: hide name+description until earned.
- [ ] `AchievementShowcase` 5-slot featured strip with editable ordering + "Edit showcase" action.
- [ ] Either link `/achievements` from Navbar or `/settings`, or pick an alternative discovery path. (Resolves Q9.)
- [ ] Wire `AchievementUnlockToast` to fire via `useToast` on unlock detection.

### A.15 Profile & Cosmetics primitives
- [ ] `Avatar` with `referrerPolicy="no-referrer"`, initials fallback on deterministic color (6-color palette).
- [ ] `AvatarFrame` with PNG overlay.
- [ ] `NameColorRenderer` supporting solid colors and gradients (`background-clip: text`).
- [ ] `TitleFlair` with rarity tokens.
- [ ] `RoleBadge` with role color + `color-mix`-based translucent background + optional icon.
- [ ] `equipCosmetic(slot, cosmeticId | null)` to equip/unequip.
- [ ] Rarity CSS tokens: `--rarity-common/uncommon/rare/epic/legendary` + `-bg`.
- [ ] `featured_role` and `featured_achievements` persist and display on public-visible surfaces.

### A.16 Realtime / async
- [ ] Supabase Realtime for chat + presence (covered by A.11).
- [ ] Supabase Storage for issue-report screenshots (covered by A.17).
- [ ] Optimistic updates for chat send + reactions.
- [ ] Cleanup on unmount for every Realtime subscription.

### A.17 Feedback & issue reports
- [ ] Global passive `FeedbackFlow`: 45s delay after mount, 3-day cooldown; rating emojis + improvement checkboxes + optional comment.
- [ ] Post-session `SessionFeedbackFlow`: 4-step card triggered every 5 sessions + on navigate-away from `/learn` (3-day cooldown).
- [ ] `ReportIssueFlow` full-screen: topic picker + comment + up to 5 screenshots via drag/pick → upload to Supabase Storage `issues-media-files` bucket → `submitIssueReport`.
- [ ] `?testFeedback=global|session` dev overrides.
- [ ] Fire-and-forget submissions (with improved error surfacing — see rebuild improvement).

### A.18 KnowledgeGraph (cross-cutting)
- [ ] `d3.forceSimulation` with center, x/y, link, charge, collide forces; alphaDecay 0.04.
- [ ] Matte course colors + mastery-opacity encoding (1.0/0.75/0.55/0.28/1.0).
- [ ] Subject-root nodes R=22, labeled in course text color.
- [ ] Drift RAF animation (per-node sin/cos).
- [ ] Node entry fade (400ms), tier transition (500ms) when `animate=true`.
- [ ] Hover tooltip (name / subject dot / mastery % / last studied).
- [ ] Click → `onNodeClick(node)`.
- [ ] Drag to reposition (released nodes rejoin simulation).
- [ ] Zoom/pan via `d3.zoom`, scale 0.3–3.
- [ ] Highlight ring via separate effect (doesn't reseed simulation).
- [ ] Comparison outline rings (4-color) when `comparison={partnerNodes}`.
- [ ] `React.memo` with topology keys (`nodeIdsKey`, `edgeIdsKey`).
- [ ] Consumers should pass stable `onNodeClick` (ref-backed or `useCallback`).
- [ ] **Remove the production `console.log` at `KnowledgeGraph.tsx:106`.**
- [ ] Pause RAF when graph is off-screen (rebuild improvement).

### A.19 Routing contract (deep links)
- [ ] `/signin?error=<not_approved|invalid_domain|google_not_configured|signin_failed|...>`
- [ ] `/signin/callback?user_id&name&avatar&is_approved&auth_token&error`
- [ ] `/dashboard?suggest=<concept>`
- [ ] `/learn?topic=&mode=socratic|expository|teachback|quiz&suggest=&testFeedback=session`
- [ ] `/tree?suggest=<concept>`
- [ ] `/social?suggest=<concept>`
- [ ] `/calendar?connected=true`

### A.20 Build & runtime
- [ ] Next.js App Router; standalone output in production.
- [ ] `/api/*` rewrites to `BACKEND_URL` at build time.
- [ ] Env vars: `NEXT_PUBLIC_API_URL`, `SESSION_SECRET` (≥32 bytes, enforced), `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `NEXT_PUBLIC_LOCAL_MODE`, `BACKEND_URL`, `STATIC_EXPORT`.
- [ ] Dev mode: `npm run dev` on port 3000 against backend on 5000.
- [ ] Test: `npm test`. Current suite in `src/__tests__/`.

---

## B · SECONDARY (parity polish)

- [ ] Every mutation Toasts success; every caught error Toasts the message.
- [ ] Two-step delete/kick/leave confirms.
- [ ] Typed-phrase confirm for account deletion ("DELETE").
- [ ] Copy-to-clipboard with 2s "Copied!" feedback.
- [ ] Body scroll-lock on full-viewport overlays.
- [ ] `CustomSelect` across the app (replace native `<select>` in `/admin`).
- [ ] KaTeX math rendering in chat (`katex/dist/katex.min.css`).
- [ ] Markdown component overrides in chat (code, pre, strong, ul, ol, li, p).
- [ ] @mention highlighting with member-name escaping in chat.
- [ ] Two-level delete/archive for chat messages (soft-delete via `is_deleted`).
- [ ] Dashboard typewriter greeting (55ms/char) + blinking cursor (530ms) + random quote client-only.
- [ ] Monday-first weekly activity strip derived from `last_studied_at`.
- [ ] `getCourseColor(subject, overrideHex?)` deterministic palette (12 colors) with override support.
- [ ] Category color map for assignments (exam/project/homework/quiz/reading/other).
- [ ] Per-tier mastery colors (mastered=green / learning=amber / struggling=red / unexplored=gray / subject_root=purple).
- [ ] React Compiler enabled via `reactCompiler: true`.
- [ ] Bottom-sheet panels on mobile for detail views (Tree node detail, Library doc detail).
- [ ] 768px breakpoint for mobile-switch across every page.
- [ ] Drag-to-reorder `AssignmentTable` rows (Manual order only).
- [ ] Flip-card 3D animation for flashcard study mode.
- [ ] Dashboard graph Fullscreen / Escape / Exit pattern.
- [ ] ResizeObserver debounced at 200–250ms for graph panes.

---

## C · NICE-TO-HAVE (rebuild wins)

- [ ] Real SSE/streaming for `/api/learn/chat` (token-by-token reply rendering). Resolves Q16.
- [ ] Polling or Realtime on `/pending` so approval propagates without manual refresh.
- [ ] React Query / SWR across the app — eliminate refetch-on-navigate flicker.
- [ ] `useIsMobile` extracted to a single hook.
- [ ] Consolidate `FlashcardsPanel` and `/flashcards/page.tsx` into one component.
- [ ] Migrate `StudyClient` raw `fetch` calls to `lib/api.ts`.
- [ ] Persist onboarding draft to `localStorage.sapling_onboarding_draft` so mid-flow exits don't lose work.
- [ ] Surface onboarding POST errors with Toast + Retry.
- [ ] Source majors/minors/school list from backend rather than hardcoding BU.
- [ ] Keyboard shortcuts:
  - [ ] Flashcard study mode: Space to flip, 1/2/3 to rate.
  - [ ] Quiz: A/B/C/D to select option, Enter to submit.
  - [ ] Tree: `/` focuses search.
- [ ] Skeleton loading states for card grids.
- [ ] Standardize modal chrome (focus trap, focus restore, `role="dialog"`, `aria-modal`).
- [ ] Replace `window.confirm`/`alert()` in `/calendar` with in-app affordances.
- [ ] Accessibility: `aria-live` on chat logs, `role="radiogroup"` on quiz options, keyboard-reachable tooltips, skip-to-content link.
- [ ] Timezone-safe date math in Calendar.
- [ ] Clear `?connected=true` from URL after Calendar OAuth success.
- [ ] Reintroduce `/profile/[userId]` public page (resolves Q10) or formalize absence.
- [ ] Navbar link to `/achievements` (resolves Q9).
- [ ] Decide `/flashcards` vs `/study → Flashcards` (resolves Q9).
- [ ] Admin panel: role-assignment UI, cosmetic asset upload, user/achievement pickers.
- [ ] Paginate room message history.
- [ ] Filter Supabase `room_reactions` subscription by room (reduce cross-room traffic).
- [ ] Upload chat images to Supabase Storage instead of data URLs.
- [ ] Replace inline CSS with a design-system component library (Card, Modal, Tooltip, Autocomplete, Toggle, etc.).
- [ ] Remove `console.log` in `KnowledgeGraph.tsx`.
- [ ] Pause `KnowledgeGraph` RAF when hidden.
- [ ] `reduceMotion` accessibility setting.
- [ ] Add Sentry (or equivalent) client error tracking.
- [ ] Decide on analytics before rebuild (Plausible/PostHog/Mixpanel).

---

## D · Resolve before / during rebuild (from QUESTIONS.md)

- [ ] Q1 — `OnboardingFlow` scope split with landing-page host.
- [ ] Q2 — `SpaceBackground.tsx` dead-code confirmation.
- [ ] Q3 — `/profile` page gating decision.
- [ ] Q4 — `/pending` direct-access policy.
- [ ] Q5 — `/signin/callback` as in-scope auth flow (confirmation only).
- [ ] Q6 — i18n: en-US only vs. forward-looking.
- [ ] Q7 — Feature-flag tooling decision.
- [ ] Q8 — Dockerfile review.
- [ ] Q9 — `/flashcards` and `/achievements` orphan routes: retire / keep / link.
- [ ] Q10 — `/profile` route reintroduction.
- [ ] Q11 — `signOut()` clear `sapling_onboarding_pending`.
- [ ] Q12 — Onboarding POST error surfacing.
- [ ] Q13 — Multi-school generalization.
- [ ] Q14 — Dashboard Dismiss route (/ → /dashboard).
- [ ] Q15 — Session feedback cooldown (3 days code vs. 2 days in CLAUDE.md).
- [ ] Q16 — SSE streaming for `/api/learn/chat`.
- [ ] Q17 — Graph-node-click mid-session orphans old session.

---

## Definition of done

A new team given:
- `docs/frontend-audit/00-overview.md` through `08-interaction-patterns.md`
- `docs/frontend-audit/features/*.md` (15 feature docs)
- `docs/frontend-audit/zz-dead-code.md`
- This checklist (`99-rebuild-checklist.md`)
- `docs/frontend-audit/QUESTIONS.md` with your decisions filled in

should be able to produce a frontend that ticks every **Core** box and `n` **Secondary** boxes equal to prior parity. They should not need to read the original `frontend/src/` to produce a working rebuild.

If they do need to dip into the old source, it's a documentation bug — please flag it back for an update.
