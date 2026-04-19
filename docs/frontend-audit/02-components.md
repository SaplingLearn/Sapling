# Sapling Frontend Audit — 02 · Component Library Inventory

> Every in-scope component under `src/components/` plus the notable inline ones. For each: purpose, importers, props, variants, and a note on what in feature docs covers it in detail.

Out-of-scope components (not catalogued): `HowItWorks.tsx` (landing-only).

---

## 1. Summary table

| Component | File | Importers (in-scope) | Key props | Deep-dive doc |
|---|---|---|---|---|
| `Avatar` | `Avatar.tsx` | `AvatarFrame`, `RoomChat`, `RoomMembers`, various inline | `userId, name, size?=32, avatarUrl?, className?` | `features/profile-and-cosmetics.md` |
| `AvatarFrame` | `AvatarFrame.tsx` | `Navbar`, `Settings`, `CosmeticsManager` | `frameUrl?, frameSlug?(unused), userId, name, size?, avatarUrl?` | `features/profile-and-cosmetics.md` |
| `NameColorRenderer` | `NameColorRenderer.tsx` | `Settings`, `CosmeticsManager` | `name, cssValue?` | `features/profile-and-cosmetics.md` |
| `TitleFlair` | `TitleFlair.tsx` | `Settings`, `CosmeticsManager` | `title, rarity` | `features/profile-and-cosmetics.md` |
| `RoleBadge` | `RoleBadge.tsx` | `Admin`, `Settings` | `role, size?='sm'|'md'` | `features/profile-and-cosmetics.md` |
| `AchievementCard` | `AchievementCard.tsx` | `Achievements`, `AchievementShowcase` | `achievement, earned, earnedAt?, progress?, isSecret?, compact?, onPress?` | `features/achievements.md` |
| `AchievementShowcase` | `AchievementShowcase.tsx` | `Settings` (profile preview) | `achievements, isOwnProfile, onEditShowcase?` | `features/achievements.md` |
| `AchievementUnlockToast` | `AchievementUnlockToast.tsx` | **no importers (dead)** | `achievement:{name, icon, rarity}` | `features/achievements.md` |
| `AIDisclaimerChip` | `AIDisclaimerChip.tsx` | `/learn`, `/flashcards` | — (manages its own modal) | `features/learn.md` |
| `AssignmentTable` | `AssignmentTable.tsx` | `/calendar` | `assignments, onChange, selectedIds?, onToggleSelect?` | `features/calendar.md` |
| `ChatPanel` | `ChatPanel.tsx` | `/learn` | `messages, onSend, onAction, onEndSession, loading, mode, prefillInput?` | `features/learn.md` |
| `CosmeticsManager` | `CosmeticsManager.tsx` | `/settings` | `userId` | `features/settings.md` |
| `CustomSelect` | `CustomSelect.tsx` | `/learn`, `/study`, `DocumentUploadModal`, `/calendar`, `QuizPanel`, `/admin` (not used), elsewhere | `value, onChange, options, placeholder?, style?, compact?, openUpward?, onDelete?` | See §3 below |
| `DisclaimerModal` | `DisclaimerModal.tsx` | `AIDisclaimerChip` | `onClose` | `features/learn.md` |
| `DocumentUploadModal` | `DocumentUploadModal.tsx` | `/library`, `/calendar` | `open, onClose, userId, courses, onCoursesChanged, onDocConfirmed?, initialCourseId?, title?, subtitle?` | `features/library.md` |
| `ErrorBoundary` | `ErrorBoundary.tsx` | root layout | `children, fallback?` | See §4 below |
| `FeedbackFlow` | `FeedbackFlow.tsx` | root layout | — | `features/feedback-and-reports.md` |
| `KnowledgeGraph` | `KnowledgeGraph.tsx` | `/dashboard`, `/learn`, `/tree`, `RoomOverview` | `nodes, edges, width, height, animate?, highlightId?, interactive?, onNodeClick?, comparison?, courseColorMap?` | `features/knowledge-graph.md` |
| `ModeSelector` | `ModeSelector.tsx` | `/learn` | `mode, onChange, showQuiz?, quizActive?, onToggleQuiz?` | `features/learn.md` |
| `Navbar` | `Navbar.tsx` | root layout | — (reads `UserContext` + `usePathname`) | See §5 below |
| `OnboardingFlow` | `OnboardingFlow.tsx` | landing page (`/`) (treated in scope — onboarding is in scope) | `visible, onClose, onFinish, activeStep, completed, setActiveStep, setCompleted` | `features/onboarding.md` |
| `ProfileBanner` | `ProfileBanner.tsx` | **no importers (dead)** | `bannerUrl?` | `features/profile-and-cosmetics.md` |
| `QuizPanel` | `QuizPanel.tsx` | `/learn` | `nodes, userId, selectedCourse?, onLearnConcept?, preselectedNodeId?, useSharedContext?` | `features/learn.md` |
| `ReportIssueFlow` | `ReportIssueFlow.tsx` | `Navbar` | `visible, onDismiss` | `features/feedback-and-reports.md` |
| `RoomChat` | `RoomChat.tsx` | `/social` | `roomId, userId, members` | `features/social.md` |
| `RoomList` | `RoomList.tsx` | `/social` | `rooms, activeRoomId, userId, onSelectRoom, onRoomsChange, schoolActive?, onSchoolClick?` | `features/social.md` |
| `RoomMembers` | `RoomMembers.tsx` | `/social` | `roomId, roomName, leaderId, members, currentUserId, onLeave, onMembersChange` | `features/social.md` |
| `RoomOverview` | `RoomOverview.tsx` | `/social` | `room, members, aiSummary, myUserId, suggestNodeId?, suggestConcept?, onSuggestDismiss?, onSuggestAccept?` | `features/social.md` |
| `SchoolDirectory` | `SchoolDirectory.tsx` | `/social` | `currentUserId` | `features/social.md` |
| `SessionFeedbackFlow` | `SessionFeedbackFlow.tsx` | `/learn`, `SessionFeedbackGlobal` | `visible, topic?, sessionId?, onDismiss` | `features/learn.md` / `features/feedback-and-reports.md` |
| `SessionFeedbackGlobal` | `SessionFeedbackGlobal.tsx` | root layout | — | `features/feedback-and-reports.md` |
| `SessionSummary` | `SessionSummary.tsx` | `/learn` | `summary, onDashboard, onNewSession` | `features/learn.md` |
| `SharedContextToggle` | `SharedContextToggle.tsx` | `/learn` | `enabled, onToggle` | `features/learn.md` |
| `SpaceBackground` | `SpaceBackground.tsx` | **no importers (dead)** | — | see `zz-dead-code.md` |
| `StudyMatch` | `StudyMatch.tsx` | `/social` | `matches, onFindMatches, loading, userId` | `features/social.md` |
| `ToastProvider` / `useToast()` | `ToastProvider.tsx` | root layout + every consumer | `showToast(content, {duration?})` | See §6 below |
| `UploadZone` | `UploadZone.tsx` | **no importers (dead)** | `onFile, loading?, filename?` | see `zz-dead-code.md` |
| Inline study components: `StudyClient`, `FlashcardsPanel` | under `src/app/study/` | `/study` | various | `features/study.md` |

Plus the landing-page component `HowItWorks.tsx` — **out of scope**.

---

## 2. Variants & visual grammar (inferred)

Recurring presentational patterns across components:

- **Pill buttons** (small, rounded-full, muted-bg default → accent-dim + accent-border when active). Used for: filter categories, nav tabs, mode selectors, emoji ratings, assignment-type chips.
- **Glass cards** (`background: #ffffff; border: 1px solid rgba(107,114,128,0.15); border-radius: 10px`). Shared across Dashboard, Calendar, Library panels. Codified as a `GLASS` const in multiple pages — candidate for a shared `<Card>` component in the rebuild.
- **Slide-in panels** (`.panel-in` + `.panel-in-1/2/3` animation classes in `globals.css`). The class names suggest a staged entrance animation per page.
- **Bottom-right feedback cards** (`@keyframes sfSlideUp/Down`). Shared between `FeedbackFlow` and `SessionFeedbackFlow`. Same visual language.
- **Modal overlays**: `rgba(0,0,0,0.4–0.45)` backdrop with click-to-close; content card with `boxShadow: 0 20px 60px rgba(0,0,0,0.15)`. Used by `SessionSummary`, courses modal in Dashboard, `DocumentUploadModal`, `StudyMatch` best-match popup, `DisclaimerModal`.
- **Flip card** (`transform: rotateY(180deg)`, `transform-style: preserve-3d`). Used by both `/flashcards` and `FlashcardsPanel` — duplicated code.
- **Typewriter** effect. Used by `/dashboard` greeting.

---

## 3. `CustomSelect` — the universal dropdown

Used everywhere a native `<select>` would otherwise appear. Key implementation details:

- **Portal-rendered dropdown** (`createPortal(..., document.body)`) so it escapes overflow-hidden parents.
- **`z-index: 2147483647`** — max signed int, for layering above every modal.
- **Trigger rect tracking**: `getBoundingClientRect()` on open; `scroll` listener (capturing) updates the rect while the dropdown is open.
- **`openUpward`** prop for use near the bottom of a panel (e.g., exam picker inside `/study`).
- **`onDelete`** prop for per-item delete (used by `/learn` Resume Session dropdown).
- **Closes on outside click** (document-level `mousedown` listener).

Preserve this component or its contract when rebuilding — many features assume its portal behavior, the `openUpward` affordance, and the optional `onDelete`.

---

## 4. `ErrorBoundary`

Classic React class-component error boundary.

- `getDerivedStateFromError` captures the error + flips `hasError`.
- Default fallback: "Something went wrong" card with `reset()` button.
- Custom `fallback` prop supported.
- Wrapped around every route in the root layout (`app/layout.tsx:60`).
- `app/error.tsx` is a separate Next.js App Router error page (distinct from this component). Both exist and do similar things — `error.tsx` handles full-page render errors; `ErrorBoundary` handles children errors.

---

## 5. `Navbar`

Not catalogued in a feature doc in Phase 3; documenting here for completeness.

### 5.1 Public/private mode

- `publicPaths = ['/', '/signin/callback', '/about', '/terms', '/privacy']` + any path starting with `/careers`.
- If on a public path → `return null` (nav hidden).
- If not public and user is not authenticated (after `userReady`) → `router.push('/')`. The nav never shows to unauthenticated visitors of protected pages because middleware would already have bounced them; this is a belt-and-braces.

### 5.2 Primary links

`LINKS = [{Dashboard, Learn, Study, Library, Calendar, Social, Tree}]`. That's it — 7 top-level destinations. Notable omissions: `/flashcards` and `/achievements` (both orphaned, see QUESTIONS Q9).

### 5.3 User menu (right side)

- Avatar + name button → opens a menu with:
  - "Signed in as **{userName}**" header.
  - **Settings** link (`/settings`).
  - **Admin** link — only rendered when `useUser().isAdmin`.
  - Sign out button → `signOut()` + `router.push('/')`.
- Escape key closes the menu.

### 5.4 Mobile

- Hamburger button replaces the inline links on narrow screens.
- Tapping opens the same link list as a dropdown below the hamburger.
- "What should I learn next?" call-to-action is appended below the links on mobile.

### 5.5 "What should I learn next?" action

- `getRecommendations(userId)` → take top recommendation → `router.push('${currentPath}?suggest=<encoded_concept_name>')`.
- Special case: on `/calendar`, routes to `/learn?suggest=` instead (because `/calendar` doesn't render a graph).
- Other pages all respond to `?suggest=` with a popup or highlighted node (`/dashboard`, `/learn`, `/tree`, `/social`).

### 5.6 Report issue

- Navbar contains an entry that opens `<ReportIssueFlow visible=... />` — see `features/feedback-and-reports.md` §2.4.

---

## 6. `ToastProvider`

Context-based toast system mounted in the root layout.

- `useToast()` exposes `showToast(content, {duration?=5000})`.
- Toasts render in a fixed position (top: 60px, right: 16px) via `createPortal`.
- Each toast: card with content + `×` dismiss button. Auto-removed after `duration` via `setTimeout`.
- Content can be ReactNode (so feature code can pass rich content, e.g. `<AchievementUnlockToast achievement={...} />` — though that's not actually wired yet).
- Toast IDs are a monotonic counter kept in a ref.

Consumers: every mutation in `/admin`, `/settings`, `/dashboard` course modal, `/calendar` (sparse), and more. Consistent pattern: catch API error → `showToast(e.message)`.

---

## 7. `lib/` utilities

Not components per se, but cross-cutting primitives every feature depends on.

### 7.1 `lib/api.ts` (528 lines)

Every HTTP endpoint used by the frontend is in here except:
- Supabase Realtime / Storage calls in `RoomChat.tsx` and `ReportIssueFlow.tsx`.
- Raw `fetch` in `StudyClient.tsx` (study-guide endpoints — anomaly, flag).
- Raw `fetch` in `/signin/callback` for `/api/auth/me` (could be routed through `lib/api.ts`).

Fetches go through `fetchJSON<T>`, which short-circuits to `handleLocalRequest` when `NEXT_PUBLIC_LOCAL_MODE=true`. In normal mode, it prepends `NEXT_PUBLIC_API_URL` to the path.

The full endpoint inventory is in `04-api-surface.md`.

### 7.2 `lib/avatarUtils.ts`

Two pure functions:
- `getInitials(name)` — first char of each word, up to 2 chars, uppercase.
- `getAvatarColor(userId)` — deterministic hash → one of 6 brand colors (`#1a5c2a, #2563eb, #7c3aed, #dc2626, #d97706, #0891b2`).

### 7.3 `lib/graphUtils.ts`

Course + mastery palette + formatting helpers:
- `COURSE_COLOR_PALETTE` (12 colors: indigo/teal/amber/red/violet/cyan/lime/pink/orange/emerald/blue/purple).
- `hashString(s)` — djb2-style non-crypto hash.
- `getCourseColor(subject, overrideHex?)` — hashed palette lookup with optional explicit hex override.
- `hexToCourseColor(hex)` — build a `CourseColor` from any 6-digit hex.
- `PRESET_COURSE_COLORS` (exported palette) + `RAINBOW_COLORS` (8-color rainbow).
- `MASTERY_COLORS` / `MASTERY_HIGHLIGHT_COLORS` — per-tier palette.
- `getMasteryColor(tier)`, `getMasteryHighlightColor(tier)`, `getMasteryLabel(score)` → "N%".
- `getNodeRadius(score)` → `7 + score*7` (7–14 px).
- `filterCrossSubjectEdges(nodes, edges)` — reused by Dashboard, Tree, Learn (each also has a local copy inline — refactor opportunity).
- `computeGraphDiff(prev, next)` — not currently used (refactor remnant).
- `formatRelativeTime(iso|null)`, `formatDueDate(dateStr)`, `daysUntil(dateStr)`.

### 7.4 `lib/supabase.ts`

Lazy-initialized `SupabaseClient` exported as a `Proxy` so `next build` can prerender without the env vars. Only used by `RoomChat.tsx` (Realtime + presence) and `ReportIssueFlow.tsx` (Storage uploads).

Env vars required at runtime: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`.

### 7.5 `lib/sessionToken.ts`

HMAC-SHA-256 session token helpers using Web Crypto. Covered in detail in `features/auth.md` and `05-auth-and-permissions.md`.

### 7.6 `lib/types.ts`

Shared TypeScript types: `GraphNode`, `GraphEdge`, `GraphStats`, `ChatMessage`, `TeachingMode`, `Assignment`, `Room`, `RoomMember`, `RoomMessageRow`, `StudyMatch`, `UserProfile`, `UserSettings`, `UserRole`, `UserAchievement`, `Achievement`, `UserCosmetic`, `CosmeticType`, `RarityTier`, `AchievementCategory`, `Role`, `EquippedCosmetics`, `SessionSummary`, `Recommendation`, `QuizQuestion`, `QuizResult`, `Document`.

---

## 8. Design tokens (inferred; full audit in a future pass)

Referenced as CSS custom properties (defined in `globals.css`, not audited in full):

**Colors**:
- `--accent` (brand forest green `#1a5c2a`-ish), `--accent-border`, `--accent-dim`, `--accent-active`, `--accent-glow`.
- `--text`, `--text-primary`, `--text-secondary`, `--text-muted`, `--text-dim`, `--text-placeholder`.
- `--bg`, `--bg-panel`, `--bg-subtle`, `--bg-input`, `--bg-topbar`, `--bg-base`.
- `--border`, `--border-mid`, `--border-light`.
- `--brand-success`, `--brand-progress`, `--brand-struggle`, `--brand-text1`, `--brand-text2`.
- `--rarity-common/uncommon/rare/epic/legendary` + `-bg` variants.

**Radii**: `--radius-sm`, `--radius-md`, `--radius-lg`, `--radius-full`.

**Shadows**: `--shadow-sm`, `--shadow-md`.

**Durations**: `--dur-fast`, `--dur-base`.

**Easings**: `--ease-out`, `--ease-in-out`.

**Fonts**: `--font-dm-sans`, `--font-spectral`, `--font-inter`, `--font-playfair`, `--font-jetbrains` (all via `next/font/google`).

This list is *inferred* from usage; a complete audit requires reading `globals.css` (deferred to future Phase 4 pass).

---

## 9. Patterns ripe for consolidation

Repeated patterns across multiple components — targets for a shared UI kit in the rebuild:

- **Inline `isMobile` hook** with `matchMedia('(max-width: 768px)')` + `addEventListener('change')`. Redefined verbatim in `/dashboard`, `/learn`, `/tree`, `/library`, `/calendar`, `/flashcards`, `/study/StudyClient`, `/social`, `FlashcardsPanel`, `RoomOverview`. Extract to `hooks/useMedia` or `hooks/useIsMobile`.
- **Glass-card object** (`const GLASS = { background: '#fff', border: ..., borderRadius: '10px' }`). Multiple pages declare this. Extract a `<Card>` component.
- **Course typeahead** (`fetch /api/onboarding/courses?q=` debounced 200ms). Duplicated in `/dashboard` and `OnboardingFlow`.
- **`filterCrossSubjectEdges`** — helper exists in `lib/graphUtils.ts` but pages re-implement it inline. Use the helper.
- **Two-step confirm button** — delete course, leave room, kick member, delete message all implement this independently.
- **Flashcards generator + deck + study mode** — duplicated in `/flashcards/page.tsx` and `FlashcardsPanel.tsx`.
