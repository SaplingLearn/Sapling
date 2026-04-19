# Revamp Frontend — Gap Plan vs. Main

Cross-reference of the rebuild contract (`99-rebuild-checklist.md` + `features/*.md`) against the current state of `frontend/` on the `revamp` branch. Each section lists what the new frontend already has, what's missing or stubbed, and an ordered implementation plan.

Legend: ✅ done · 🟡 partial / visual-only · ❌ missing.

---

## 0 · Quick scoreboard

| Area | Status | Biggest gaps |
|---|---|---|
| Auth & session | 🟡 | No `?error=<code>` page, no `sapling_onboarding_pending` bridge, no live-revoke proof |
| Onboarding | 🟡 | 4-step visual flow; doesn't POST `/api/onboarding/profile`; no course typeahead |
| Global shell | ❌ | No `ToastProvider`, no global `FeedbackFlow`, no `SessionFeedbackGlobal`, no `ErrorBoundary`, no `AIDisclaimer` |
| Dashboard | 🟡 | Missing recommendations, typewriter + quote, weekly activity, Quick Quiz, Fullscreen, Courses modal, `?suggest=` |
| Learn | 🟡 | No `SessionSummary`, no quiz phases, no quick actions, no end-session, no mode-switch API, no KaTeX/markdown, no Class Intel toggle |
| Study (guide) | ❌ | Page shows flashcards instead of study guide; no course→exam picker; no guide generator |
| Flashcards | 🟡 | Standalone deck works; no generation UI, no topic pills, no context chip, no delete |
| Tree | 🟡 | "Learn this" / "Quick quiz" inert; no mastery filter pills, no search, no fullscreen, no `?suggest=` |
| Library | 🟡 | No multi-file drag-and-drop `DocumentUploadModal`, no 4-min abort, no per-file review/re-analyze, no detail panel with flashcards |
| Calendar | 🟡 | Only 2-week grid; missing month/week/day, editable table, Google Calendar OAuth, syllabus upload flow |
| Social | 🟡 | No Realtime chat, no optimistic send, no mentions/reactions grid/reply/edit/image uploads, no partner-comparison outline rings, no SchoolDirectory |
| Achievements | 🟡 | No progress bars on locked, no editable showcase, no `AchievementUnlockToast` |
| Profile | ❌ | No public `/profile/[userId]`; cosmetics primitives missing (`AvatarFrame`, `NameColorRenderer`, `TitleFlair`, `RoleBadge`) |
| Settings | 🟡 | No avatar upload, no cosmetics tabs (frames / banners / name colors / titles), no username availability check |
| Admin | 🟡 | Only Users/Analytics tabs; missing Roles, Achievements, Cosmetics tabs and create-forms |
| Feedback & reports | ❌ | Modal present but submit is a TODO; no screenshots/Supabase Storage; no global `FeedbackFlow`; no `SessionFeedbackFlow`; no `ReportIssueFlow` |
| KnowledgeGraph | 🟡 | d3-force done; missing comparison rings, highlight ring for `?suggest`, per-tier mastery colors, animated tier transitions |
| Cross-cutting | ❌ | No toasts, no two-step confirms, no KaTeX, no mobile bottom-sheet patterns, no 768px breakpoint, no `CustomSelect` primitive |

---

## 1 · Phase-ordered plan

Phases are ordered so earlier work unblocks later work. Each item references the checklist ID from `99-rebuild-checklist.md` (e.g. `A.1`).

### Phase 1 — Cross-cutting primitives (must ship before features)

These are building blocks used everywhere else. Do them first or features below can't be wired correctly.

1. **ToastProvider + `useToast`** (`A.3`, `B`) — portal-rendered stack, 5s auto-dismiss, manual close, accepts ReactNode content. Mount at `app/layout.tsx`. Replace the `alert()` / `confirm()` sprinkled through `Settings.tsx` and `Admin.tsx`.
2. **ErrorBoundary + `app/error.tsx`** (`A.3`) — full-page reset button.
3. **`CustomSelect`** (`B`) — styled dropdown used by Learn (course picker, resume-session picker, quiz count/difficulty), Library (category), Admin (role assignment). Currently every screen uses native `<select>`.
4. **`useIsMobile` hook at 768px** (`B`) — single source of truth; wire into Tree node panel, Library detail, Learn two-pane → tabs, Dashboard stats panel.
5. **Two-step confirm helper** (`B`) — first click arms, second click confirms, 3s auto-disarm. Used for delete document, delete flashcard, kick room member, leave room.
6. **Cosmetics primitives** (`A.15`):
   - `Avatar` — already exists (`src/components/Avatar.tsx`) — verify `referrerPolicy="no-referrer"` and 6-color initials palette.
   - `AvatarFrame` — PNG overlay wrapper around `Avatar`.
   - `NameColorRenderer` — solid + gradient text (`background-clip: text`).
   - `TitleFlair` — styled title text with rarity token.
   - `RoleBadge` — role color + `color-mix` translucent bg + optional icon.
   - Rarity CSS tokens `--rarity-{common,uncommon,rare,epic,legendary}(-bg)` in `globals.css`.
7. **Markdown + KaTeX renderer** (`B`) — lightweight wrapper (remark-math + rehype-katex, mocked in tests) used by `ChatPanel` and `SessionSummary`. Add to `package.json`: `react-markdown`, `remark-math`, `rehype-katex`, `katex`. Copy existing jest mocks from main (`src/__mocks__/{remarkMath,rehypeKatex}.js`).

### Phase 2 — Global shell & auth polish

8. **Global shell additions** (`A.3`):
   - Mount `ErrorBoundary`, `ToastProvider`, `FeedbackFlow` (passive global), `SessionFeedbackGlobal` (navigate-away from /learn), `DisclaimerModal` first-view in `app/(shell)/layout.tsx`.
   - Navbar "What should I learn next?" button wired to top recommendation → `?suggest=<concept>`.
   - Navbar report-issue entry opens `ReportIssueFlow`.
9. **Auth `?error=<code>` page** (`A.1`) — `/auth` currently ignores errors. Add param handling for `not_approved | invalid_domain | google_not_configured | signin_failed | ...` with specific copy per code. Also clear `sessionStorage.sapling_onboarding_pending` in `signOut()`.
10. **Deep-link `/auth/callback`** (`A.1`) — already exists; verify the POST `/api/auth/session` path handles `authToken` HMAC fast-path, falls back to backend `/api/auth/me` when absent, and routes to `/onboarding` if `onboarding_completed=false`, else `/dashboard`.
11. **Middleware live revocation** — spec says fetch `/api/auth/me` on every protected nav with 3s `AbortController` timeout; verify current impl matches.

### Phase 3 — Onboarding (contract-breaking if skipped)

12. **6-step flow** (`A.2`): Google → Name → School + Year → Academics (majors + minors) → Courses → Learning Style. Current is 4-step visual-only. Wire final step to `POST /api/onboarding/profile { user_id, first_name, last_name, year, majors, minors, course_ids, learning_style }`.
13. **Course typeahead** — debounced 200ms `GET /api/onboarding/courses?q=`; `addCourse()` returns the full course record.
14. **Learning-style IDs** must match backend contract: `visual | reading | auditory | hands-on | mixed`.
15. **Escape + X button close; Continue gated per-step.** Optional: persist draft to `localStorage.sapling_onboarding_draft`.

### Phase 4 — Feedback & reports (needed before dashboard/learn to catch session signals)

16. **Global passive `FeedbackFlow`** (`A.17`) — 45s delay, 3-day cooldown via `localStorage.sapling_last_feedback`, rating emojis + checkboxes + comment. Wire `POST /api/feedback` (already in `lib/api.ts` as `submitFeedback`).
17. **`SessionFeedbackFlow` + `SessionFeedbackGlobal`** (`A.5`) — every-5-sessions via `localStorage.sapling_session_end_count` and navigate-away from `/learn` with 3-day cooldown. 4-step card UI.
18. **`ReportIssueFlow`** (`A.17`) — topic picker + comment + up-to-5 screenshots uploaded to Supabase Storage bucket `issues-media-files`; `POST /api/feedback/issue-report` via existing `submitIssueReport`.
19. **Current `FeedbackModal.tsx`** — wire the submit handler to `submitFeedback`, persist type pills to state, replace TODO with the actual call; add toast on success.
20. **Dev hooks**: `?testFeedback=global|session` override the cooldowns.

### Phase 5 — Knowledge graph finishing

21. **Per-tier mastery colors** — the spec tier colors are `mastered=#4a7d5c (green) / learning=#c89b5e (amber) / struggling=#b25855 (red) / unexplored=#9a9a9a (gray) / subject_root=#8a7bc4 (purple)`. Current code uses a uniform `color` prop + opacity ramp. Add tier-aware fill when `variant` allows, kept opt-in so the organism look is preserved on dashboard.
22. **Highlight ring** — when `suggestNode?.id` or `topicNode?.id` is set, render a separate pulsing stroke layer that does NOT reseed the simulation (separate effect from node data).
23. **Comparison outline rings** — optional `comparison?: { partnerNodes }` prop renders 4-color stroke rings: you-only cyan / them-only orange / both-missing red / both-mastered green (used by Social → Overview).
24. **Animated tier transitions** — 500ms `d3.transition` on fill/opacity when `animate=true` (used on `/learn` post-chat so the graph pane reacts visibly).
25. **Drift RAF** — per-node sin/cos idle drift. Pause RAF when the SVG is off-screen via `IntersectionObserver`.

### Phase 6 — Learn page (largest rebuild surface)

26. **ChatPanel with markdown + KaTeX** — migrate text rendering to `react-markdown` with component overrides for `code/pre/strong/ul/ol/li/p`. Render `messages[].content` through it.
27. **Quick action buttons** (`A.5`) — hint / confused / skip inline under the textarea; call `POST /api/learn/action` (add to `lib/api.ts`).
28. **End session** — `POST /api/learn/end-session` + `SessionSummary` modal (concepts covered pills, mastery changes with ± deltas color-coded, time spent, recommended next). Wire it to the "End Session" button.
29. **Mode switch mid-session** — currently a local state change. Call `POST /api/learn/mode-switch` and prefill input with `"Continue in {mode} mode on {topic}..."`.
30. **Resume-session dropdown** — per-item delete (`DELETE /api/learn/sessions/:id?user_id=`). Display `message_count > 0` sessions only.
31. **URL contract** — `?topic`, `?mode=socratic|expository|teachback|quiz`, `?suggest`, `?testFeedback=session`. `?suggest=` Dismiss must preserve other query params (use `URLSearchParams`, not `router.replace('/learn')`).
32. **`SharedContextToggle` (Class Intel)** (`A.5`) — labeled button with hover tooltip about aggregated class-level patterns + privacy; persists to `localStorage.sapling_shared_ctx` (default `true`).
33. **`AIDisclaimerChip` + first-view `DisclaimerModal`** — `localStorage.sapling_disclaimer_ack` gate. Show modal once per user.
34. **Quiz mode** (`A.5` big one) — four-phase `QuizPanel`: select / active / review / results.
    - Select: concept radios filtered by selected course; `CustomSelect` for count (5/10/15) and difficulty (easy/medium/hard/adaptive); Start Quiz → `generateQuiz` (exists in `lib/api.ts`).
    - Active: option buttons A/B/C/D, Submit triggers local correctness check + explanation panel.
    - Review: color-coded options, "Explain this" opens `/learn` on `q.concept_tested`.
    - Results: score %, mastery delta, Retake, Learn Weak Areas. `submitQuiz` writes to backend.
35. **Live graph pane** — right-side `KnowledgeGraph` refreshed after every chat turn; click a node → `beginSession(concept, mode, course_id)`.
36. **Every-5-sessions + navigate-away feedback** — tied to Phase 4.
37. **Mobile**: two-pane collapses to `Chat` / `Graph` tab at 768px.

### Phase 7 — Dashboard

38. **Four parallel fetches** (`A.4`) — `getGraph, getRecommendations, getUpcomingAssignments, getCourses` — single spinner, single error card with Retry. Currently fetches `getSessions` but not `getRecommendations`.
39. **Left panel**: typewriter greeting (55ms/char, blinking cursor at 530ms) + random quote + per-course progress bars with collapse + Manage Courses modal.
40. **Right panel / mobile tab**: Streak + weekly activity strip (Mon-first, today orange, 🔥 on active days from `last_studied_at`) + knowledge tier counts + top-3 Learn Next + Quick Quiz button (`/learn?mode=quiz`) + Study Room button (`/social`) + Recent Activity (sorted by `last_studied_at`).
41. **Fullscreen graph overlay** — Esc exits, body scroll lock while open.
42. **Manage Courses modal**: search-to-add (typeahead against `/api/onboarding/courses`), inline color picker validated `^#[0-9a-fA-F]{6}$`, two-step delete. Uses `addCourse` / `deleteCourse` (both already exported from `lib/api.ts`).
43. **`?suggest=<concept>` popup** with Dismiss (preserve query) and Start Quiz → `/learn?topic=&mode=quiz`.
44. **Mobile "My Courses" / "Stats & More" tabs.**

### Phase 8 — Tree

45. **Floating controls overlay** (`A.8`) — search input + mastery filter pills (all / mastered / learning / struggling / unexplored) + "N nodes" counter.
46. **Right-side detail panel** (desktop) / bottom sheet (mobile) already present; wire:
    - "Learn this" → `router.push('/learn?topic=' + encodeURIComponent(node.name) + '&mode=socratic')`.
    - "Quick quiz" → `router.push('/learn?topic=' + name + '&mode=quiz')`.
    - "View sessions for this concept" (if history exists).
47. **`?suggest=<concept>`** → scroll/zoom to matching node, show highlight ring, open detail panel.
48. **Fullscreen toggle** — parity with dashboard overlay.

### Phase 9 — Library

49. **`DocumentUploadModal`** (`A.9`) — drag-and-drop multi-file upload, 5 file max, 15 MB each, PDF/DOCX/PPTX only. Per-file AbortController with 4-minute timeout + friendly abort message. Per-file review step with AI-picked category + override dropdown + Re-analyze button.
50. **Disallow close during active uploads** (confirm overlay).
51. **Inline "+ Add course"** within the modal using `addCourse`.
52. **Right-side detail panel**: summary + key takeaways + Q/A flashcards (reveal-on-click) + delete (two-step).
53. **Course sidebar** (currently just category pills). Group documents by course; add `All / Uncategorized` entries.
54. **Post-upload hook**: if any uploaded doc has `category='syllabus'`, refetch assignments (used by Calendar).

### Phase 10 — Calendar

55. **Three views**: month / week / day with view toggle; type-color coded chips (exam / project / homework / quiz / reading / other).
56. **Editable `AssignmentTable`**: drag-to-reorder (Manual order only), inline edit (title/course/type/date), multi-select with export to CSV.
57. **Google Calendar OAuth flow**: Connect → `GET /api/calendar/auth-url` → backend redirect → returns with `?connected=true` → state flips `googleConnected=true`. Clear query after handling.
58. **Sync to Google / Import from Google / Disconnect** with confirm.
59. **Syllabus upload**: reuse `DocumentUploadModal`; on `syllabus` upload, refetch assignments + 1.5s delayed refetch for insert races.
60. **"Due soon" = within 24 hours** (currently relative days).
61. Replace `window.confirm` / `alert()` with in-app confirms + toasts.

### Phase 11 — Social

62. **Supabase Realtime chat** (`A.11`, `06-realtime.md`) — subscribe to `room_messages` INSERT/UPDATE + `room_reactions` INSERT/DELETE, filtered by `room_id` (fix cross-room flood bug from main).
63. **Presence channel** — typing indicators with 3s idle timeout.
64. **Optimistic send** — `tmp_${Date.now()}` id, rollback on error; de-dupe when real INSERT lands.
65. **Reply / Edit / Delete** — context menu on message hover; edit writes `is_edited`; delete is soft (`is_deleted`) with "Message deleted" placeholder.
66. **Reactions** — 50-emoji grid picker; toggle via `toggleRoomReaction` (already in api.ts).
67. **@mention autocomplete** — Arrow/Tab/Enter/Escape control; highlight mentions with member-name escaping in rendered messages.
68. **Image attachments** — upload to Supabase Storage (bucket `chat-images`), not data URLs.
69. **Message pagination** — backend must support; client shows "Load earlier messages" button.
70. **`StudyMatch`** already wired; add best-match popup on first find.
71. **`RoomMembers`** panel with Leader tag, kick (leader only) with two-step confirm, leave with two-step confirm.
72. **`SchoolDirectory`** — grid of students with initials, top concepts, courses, "You" tag.
73. **Partner-comparison graph** — use `KnowledgeGraph` with the new `comparison` prop; overlay in Overview tab.
74. **`?suggest=` auto-focuses Overview tab + matching node.**

### Phase 12 — Study guide (missing entirely as feature)

Current `/study` page is a flashcard deck. The spec's `/study` is a study-guide generator with flashcards as an optional panel.

75. **Mode toggle**: Study Guide ↔ Flashcards (keep `FlashcardsPanel` mounted).
76. **Study Guide generator**: Course → Exam cascading picker (`/api/study-guide/generate` — add backend wrapper in `lib/api.ts`); loading state; rendered guide = Exam card (title + due date + overview) + per-topic cards (name + importance + bulleted concepts); "Recent guides" sidebar; Regenerate button.
77. **Flashcards panel**: generator using enrolled courses (max 10 cards, one-click per course); "Generated using N library docs / M weak concepts" chip when `context_used` returned; topic filter pills; 3D flip (0.55s cubic-bezier); rating 1/2/3; auto-advance 300ms; delete via `×`; Space to flip, 1/2/3 to rate.

### Phase 13 — Standalone Flashcards decision

78. Decide: retire `/flashcards` and redirect to `/study?mode=flashcards`, OR keep as standalone page (same component as `FlashcardsPanel`). Either is fine — picking the redirect gets us closer to main's structure.

### Phase 14 — Settings

79. **Grouped nav**: Identity (Profile, Account), Preferences (Notifications, Appearance, Privacy), Personalization (Cosmetics), Manage (Danger Zone).
80. **Avatar upload** — hidden `<input type="file" accept="image/*">` wired to `POST /api/profile/:userId/avatar` (multipart). Show pending state; toast on success.
81. **Username availability check** — separate `GET /api/profile/username-available?u=...`, not a mutating PATCH (fix noted in audit).
82. **Appearance dark mode** — `.dark` class on `<html>` (if we decide to un-lock the theme). For now the project is hard-locked to light per prior feedback; leave the toggle but gate it behind a feature flag.
83. **Cosmetics tabs**: Avatar Frames / Banners / Name Colors / Titles. Equip by click; re-click to unequip. Call `equipCosmetic(slot, id | null)` + `refreshProfile()`. Lock UI behind rarity tokens from Phase 1.
84. **Profile Preview modal** — fetch public profile + achievements.
85. **Danger Zone** — Export (already done) + Delete (already done) + toast on every mutation.

### Phase 15 — Admin

86. **Four tabs**: Users, Roles, Achievements, Cosmetics (current: Users + Analytics stub).
87. **Users tab**: add `RoleBadge` per user; role assignment dropdown → `adminAssignRole` / `adminRevokeRole`.
88. **Roles tab**: create-role form (Name, Slug, Color); list of roles with edit/delete.
89. **Achievements tab**: create-achievement form (rarity, category, name, description, icon); grant-achievement form using user + achievement pickers (not raw UUIDs).
90. **Cosmetics tab**: create-cosmetic form + asset upload to Supabase Storage.
91. Toast on every action; replace native `<select>` with `CustomSelect` from Phase 1.

### Phase 16 — Achievements

92. **Progress bars on locked cards** (`A.14`) — parse progress from API (`earned_count` / `total_needed`).
93. **Edit Showcase** — drag / click-to-feature up to 5 earned achievements; save via `POST /api/profile/:userId/featured-achievements`. Currently a static "+ add to showcase" box.
94. **Secret achievements** hidden until earned (name + description replaced with "?" + generic copy).
95. **`AchievementUnlockToast`** — subscribe to achievement-unlock signals (check `refreshProfile()` delta on focus; toast via `useToast`).

### Phase 17 — Public profile page

96. **`/profile/[userId]/page.tsx`** (currently missing) — render public profile: banner, avatar with frame, display name with name color, title flair, role badges, featured achievements strip, academic info, stats (streak, mastered, courses). Uses `fetchPublicProfile(userId)`.
97. **Link from Social members list**, room chat sender names, and leaderboards.

### Phase 18 — Misc polish & checklist tail

98. Remove `console.log` in `KnowledgeGraph.tsx` (line ~106 in main spec — check if carried over).
99. Body scroll-lock on all full-viewport overlays.
100. Accessibility pass: `aria-live` on chat log, `role="radiogroup"` on quiz options, keyboard-reachable tooltips, skip-to-content link.
101. Clear `?connected=true` after Calendar OAuth success.
102. Timezone-safe date math in Calendar.
103. `reduceMotion` accessibility setting (respect `prefers-reduced-motion` for graph drift + flashcard flip).
104. Copy-to-clipboard with 2s "Copied!" feedback on invite codes and share links.

---

## 2 · New files to add (non-exhaustive)

```
src/components/
  Toast.tsx              ← provider + hook + portal
  ErrorBoundaryClient.tsx
  CustomSelect.tsx
  AvatarFrame.tsx
  NameColorRenderer.tsx
  TitleFlair.tsx
  RoleBadge.tsx
  MarkdownChat.tsx       ← react-markdown + remark-math + rehype-katex
  DisclaimerModal.tsx
  AIDisclaimerChip.tsx
  SharedContextToggle.tsx
  SessionSummary.tsx
  SessionFeedbackFlow.tsx
  SessionFeedbackGlobal.tsx
  FeedbackFlow.tsx       ← global passive
  ReportIssueFlow.tsx
  QuizPanel.tsx
  DocumentUploadModal.tsx
  AssignmentTable.tsx
  RoomChat.tsx           ← realtime chat
  RoomMembers.tsx
  SchoolDirectory.tsx
  StudyGuide.tsx
  FlashcardsPanel.tsx    ← extracted from /study for shared use
  AchievementUnlockToast.tsx

src/app/
  profile/[userId]/page.tsx
  error.tsx              ← global error boundary
  study/page.tsx         ← refactor to host StudyGuide + FlashcardsPanel

src/lib/
  toast.tsx              ← already implied by ToastProvider
  useIsMobile.ts
  markdown.tsx           ← shared renderer
```

API wrappers to add to `src/lib/api.ts` (backend endpoints already exist — see `docs/frontend-audit/04-api-surface.md`):

```ts
learnAction(sessionId, userId, action, mode, useSharedContext)
endLearnSession(sessionId, userId)
switchLearnMode(sessionId, userId, newMode)
onboardingCoursesSearch(q)                       // GET /api/onboarding/courses?q=
submitOnboardingProfile(payload)                 // POST /api/onboarding/profile
usernameAvailable(username)                      // GET /api/profile/username-available
uploadAvatar(userId, file)                       // POST /api/profile/:userId/avatar
generateStudyGuide(userId, courseId, examTopic)  // POST /api/study-guide/generate
calendarAuthUrl()                                // GET /api/calendar/auth-url
calendarSync(userId)                             // POST /api/calendar/sync
calendarDisconnect(userId)                       // POST /api/calendar/disconnect
uploadIssueScreenshot(file)                      // Supabase Storage direct upload
```

---

## 3 · Suggested execution order (milestones)

| Milestone | Phases | Est. effort | Unblocks |
|---|---|---|---|
| M1 · Plumbing | 1, 2 | 1–2 days | every feature below |
| M2 · Auth + Onboarding | 3, 4 | 1 day | user can actually finish signup |
| M3 · Learn parity | 5, 6 | 3–4 days | core product loop |
| M4 · Dashboard parity | 7 | 1–2 days | landing page tells the truth |
| M5 · Content pages | 8, 9, 10 | 2–3 days | library/calendar/tree work end-to-end |
| M6 · Social realtime | 11 | 2 days | rooms chat works |
| M7 · Study guide + flashcards | 12, 13 | 1–2 days | `/study` matches spec |
| M8 · Profile / Settings / Admin / Achievements | 14, 15, 16, 17 | 2–3 days | cosmetics, admin moderation |
| M9 · Polish & a11y | 18 | 1 day | definition-of-done |

Total: ~2–3 weeks for a single engineer with the audit as source of truth.

---

## 4 · How to verify each phase

For every phase check:
1. Checklist boxes in `99-rebuild-checklist.md` turn to `[x]`.
2. Feature doc's user flows re-read and manually reproduced in local dev (`npm run dev`).
3. `npm run typecheck` + `npm run lint` green.
4. `npm test` green (add mocks for new ESM deps in `src/__mocks__/` + `jest.config.js`).
5. Manual QA with `NEXT_PUBLIC_LOCAL_MODE=true` — extend `lib/localData.ts` as needed so features are testable without the backend.
6. Then the real test: re-run with `NEXT_PUBLIC_LOCAL_MODE=false` against the live backend and confirm behavior matches.

---

## 5 · Open decisions (from `QUESTIONS.md`)

These need a call before the relevant phase starts:

- **Q9** — retire `/flashcards` or keep standalone? (affects Phase 13)
- **Q10** — reintroduce `/profile/[userId]`? (Phase 17 assumes yes)
- **Q13** — multi-school generalization or hard-code BU? (Phase 3)
- **Q15** — session feedback cooldown is 2 days (CLAUDE.md) or 3 days (audit)? (Phase 4)
- **Q16** — SSE streaming for `/api/learn/chat` now or later? (Phase 6; nice-to-have)

Default assumption if no decision: keep `/flashcards` as redirect, reintroduce `/profile/[userId]`, hard-code BU for now, use 3-day cooldown per audit, defer SSE to a follow-up.
