# Feature · Dashboard

> Covers: `/dashboard` (`src/app/dashboard/page.tsx`, 1536 lines). The post-signin home — greeting, knowledge graph, courses management, assignments, stats, recommendations.

---

## 1. Overview

The dashboard is one very large client component. It fetches four datasets in parallel on mount (`getGraph`, `getRecommendations`, `getUpcomingAssignments`, `getCourses`) and stitches them into:

- A **center panel** with the `KnowledgeGraph` (courses as hub nodes with concept satellites), an AI recommendation popup when `?suggest=` is present, and an "Upcoming" assignments strip below.
- A **left panel** (desktop only) with a typewriter greeting, random quote, collapsible per-course mastery rows, and a "Manage Courses" button that opens a modal.
- A **right panel** (desktop) / **bottom Stats tab** (mobile) with streak + 7-day activity dots, per-tier knowledge counts, top-3 recommendations, "Quick Quiz" / "Study Room" shortcuts, and Recent Activity.
- A **fullscreen graph overlay** (desktop only) toggled by a Maximize2 button.
- A **Courses modal** for add/delete/recolor.

Mobile collapses the layout into a stack with two toggle tabs (`My Courses` / `Stats & More`).

---

## 2. User flows

### 2.1 Flow: initial load (happy path)

1. Middleware gates — user is approved.
2. `DashboardInner` mounts. `userReady`/`userId` populated by `UserContext`.
3. `useEffect` fires once (`page.tsx:197-224`):
   ```ts
   const [graphData, recData, assignData, courseData] = await Promise.all([
     getGraph(userId),
     getRecommendations(userId),
     getUpcomingAssignments(userId),
     getCourses(userId),
   ]);
   setNodes(graphData.nodes); setEdges(graphData.edges); setStats(graphData.stats);
   setRecommendations(recData.recommendations.slice(0, 3));
   setAllAssignments(assignData.assignments);
   setCourseList(courseData.courses);
   // derive courseColorMap from courses[].color
   ```
   Any failure → `setFetchError(e.message || 'Failed to load dashboard data.')`.
4. `setLoading(false)`. The container renders a spinner until then (`page.tsx:425-431`).
5. Parallel effects run:
   - **Typewriter greeting** (`page.tsx:258-274`): types `${getTimeGreeting()}, ${userName.split(' ')[0]}.` one char / 55ms; `greetingDone=true` 300ms after completion.
   - **Blinking cursor** (`page.tsx:277-284`): toggles every 530ms until `greetingDone`, then hidden.
   - **Random quote** (`page.tsx:227-229`): picks from a 13-entry array (literary quotes + "Fun fact: …"). Runs client-only to avoid SSR/CSR hydration mismatch.
   - **ResizeObserver** on `containerRef` (`page.tsx:286-307`) → `graphDimensions`, debounced 250ms after first observation.

### 2.2 Flow: clicking a concept in the graph

- `handleNodeClick(node)` (`page.tsx:334-336`) → `router.push('/learn?topic=' + encodeURIComponent(node.concept_name))`.
- Clicking a **subject_root** node (course hub) — same handler. The `/learn` page is expected to handle course-level topics (to confirm in `features/learn.md`).

### 2.3 Flow: AI-recommendation popup (`?suggest=`)

Trigger: Navbar "What should I learn next?" while on `/dashboard` — Navbar pushes `/dashboard?suggest=<concept>` (`src/components/Navbar.tsx:86-103`).

1. `suggestConcept = searchParams.get('suggest') ?? ''` (`page.tsx:88`).
2. `suggestNode = useMemo(...)` looks up the matching `GraphNode` by `concept_name`.
3. If found → render a floating card overlaid on the bottom of the graph (`page.tsx:821-890`):
   - Label: "AI Recommendation"
   - Title: the concept name
   - Copy: "Based on your knowledge graph, this concept will have the highest impact on your mastery."
   - Buttons: **Dismiss** → `router.replace('/')` *[note: this routes to `/` (landing) — likely a bug; should be `/dashboard` without `?suggest=`. Flag in QUESTIONS]*. **Start Quiz →** → `router.push('/learn?topic=...&mode=quiz')`.
4. `highlightId={suggestNode.id}` is passed to `KnowledgeGraph`; the node is visually emphasized.

### 2.4 Flow: manage courses (modal)

Trigger: "Manage Courses" button in the left panel (or per-course row actions).

The modal (`page.tsx:1250-1400+`) supports:

1. **Add course** — debounced 200ms (`page.tsx:339-356`) typeahead against `GET /api/onboarding/courses?q=<input>`. Filters out already-enrolled course IDs. Max 5 suggestions. Picking a suggestion calls `handleAddCourseFromCatalog`:
   - Derives next available color from `PRESET_COURSE_COLORS` (skipping already-used ones), falls back to `PRESET_COURSE_COLORS[0]`.
   - `addCourse(userId, course.id, pickedColor)` → 200 with `already_existed: true` surfaces a specific error message; `error` field surfaces any backend error.
   - On success: clears input, refetches both courses and graph (course changes alter subject_root nodes).
2. **Inline color picker** — click the color swatch → `setEditingColorFor(courseId)` and `setColorHexInput(current)`. `handleColorChange` validates `/^#[0-9a-fA-F]{6}$/` before calling `updateCourseColor`; refetches graph.
3. **Delete course** — two-step confirm: first button press sets `confirmDeleteCourse=courseId`, shows Cancel/Confirm pills. Confirm calls `handleDeleteCourse` → `deleteCourse(userId, courseId)` → refetch graph (removed subject root disappears).
4. **Dropdown dropdown portal positioning**: course search suggestions are rendered via `createPortal` to keep them above the modal's scroll container. The `courseInputRect` state is kept in sync with the input's `getBoundingClientRect()` via a `useLayoutEffect` watching `resize` + capturing `scroll` events (`page.tsx:237-255`).

### 2.5 Flow: fullscreen graph

Trigger: "Fullscreen" button on the graph (`page.tsx:771-801`, desktop only).

1. `setGraphFullscreen(true)` → renders a fixed-position overlay (`page.tsx:893-954`).
2. `useLayoutEffect` (`page.tsx:309-332`):
   - Attaches a `ResizeObserver` to `fullscreenGraphRef` → updates `fullscreenGraphDimensions`.
   - Binds `keydown` listener for Escape → exits.
   - Sets `document.body.style.overflow = 'hidden'`; restores on cleanup.
3. Exit button (Minimize2 icon) or Escape → `setGraphFullscreen(false)`.

### 2.6 Flow: weekly streak display

- `weekInfo` (`page.tsx:145-161`) — derived Mon–Sun ISO dates for the current week (locale-independent: always Monday-first via `dow === 0 ? 6 : dow - 1`).
- `activeDaysThisWeek` (`page.tsx:164-174`) — set of ISO dates that have at least one node with `last_studied_at` matching.
- Rendering (`page.tsx:1098-1136`):
  - Today's label highlighted orange + bold.
  - Active days render a 🔥 emoji.
  - Inactive today/past → bordered circle (dim outline).
  - Inactive future → bordered circle (dimmer outline).
- Streak count pulled from `stats.streak` (`page.tsx:1091-1095`).

### 2.7 Flow: per-course progress (left panel)

`page.tsx:~500-700` (collapsible list):
- Each course can be collapsed/expanded (`collapsedCourses: Set<string>` keyed by course name).
- Progress bar = average `mastery_score` across all non-subject-root nodes with matching `subject`.
- Also renders per-course **assignments** filtered from `allAssignments` where `course_name` matches.

---

## 3. State

| State | Type | Source |
|---|---|---|
| `nodes` / `edges` | `GraphNode[]` / `GraphEdge[]` | `getGraph(userId)` |
| `stats` | `GraphStats` | `getGraph(userId)` |
| `recommendations` | `Recommendation[]` (top 3) | `getRecommendations(userId)` |
| `allAssignments` | `Assignment[]` | `getUpcomingAssignments(userId)` |
| `courseList` | `EnrolledCourse[]` | `getCourses(userId)` |
| `courseColorMap` | `Record<course_name, hex>` | derived from `courseList[].color` |
| `loading`, `fetchError` | ui | initial fetch state |
| `graphDimensions`, `fullscreenGraphDimensions` | `{width, height}` | ResizeObserver |
| `graphFullscreen` | `boolean` | Maximize button |
| `mobileSidebarTab` | `'courses' \| 'stats' \| null` | Mobile toggle tabs |
| `displayedGreeting`, `greetingDone`, `cursorVisible` | typewriter state | `useEffect` interval |
| `quote` | `string` | random pick client-side |
| `collapsedCourses` | `Set<string>` | per-course collapse toggles |
| `showCourses` | `boolean` | manage-courses modal |
| `courseSearchInput`, `courseSuggestions`, `courseSearchFocused`, `courseInputRect` | course search modal state | — |
| `courseAdding`, `courseDeleting`, `courseError` | action-in-flight flags + error copy | — |
| `editingColorFor`, `colorHexInput` | inline color picker state | — |
| `confirmDeleteCourse` | `string \| null` | two-step delete confirm |

**No memoization** of the major panels — every state change re-renders the whole page. React Compiler (enabled via `next.config.ts:20`) likely helps here.

**No caching across navigations** — leaving and returning to `/dashboard` refetches everything.

---

## 4. API calls

| Call | When | Notes |
|---|---|---|
| `getGraph(userId)` → `GET /api/graph/:userId` | mount; also after add/delete/recolor course | Returns `{nodes, edges, stats}` |
| `getRecommendations(userId)` → `GET /api/graph/:userId/recommendations` | mount | Only top 3 shown |
| `getUpcomingAssignments(userId)` → `GET /api/calendar/upcoming/:userId` | mount | Top 4 shown in the strip |
| `getCourses(userId)` → `GET /api/graph/:userId/courses` | mount; after add/delete | Returns `EnrolledCourse[]` including per-course `color` |
| `addCourse(userId, courseId, color)` → `POST /api/graph/:userId/courses` | Add-course flow | 200 with `already_existed` possible |
| `updateCourseColor(userId, courseId, color)` → `PATCH /api/graph/:userId/courses/:courseId/color` | Color picker save | — |
| `deleteCourse(userId, courseId)` → `DELETE /api/graph/:userId/courses/:courseId` | Confirm-delete | Refetch graph to drop subject_root |
| `GET ${API_URL}/api/onboarding/courses?q=` | Course search typeahead (direct fetch, not via `lib/api.ts`) | Debounced 200ms |

**No optimistic updates.** Every mutation waits for the server and then refetches. Simpler, slower.

---

## 5. Components involved

| Component | File | Where |
|---|---|---|
| `KnowledgeGraph` | `src/components/KnowledgeGraph.tsx` | Center + fullscreen overlay |
| (inline) Courses panel, Upcoming strip, Stats card, Learn-Next card, Actions card, Recent-Activity card, Courses modal | `src/app/dashboard/page.tsx` | All defined inline |
| `Link` (next/link) | — | Links to `/calendar`, `/learn?mode=quiz`, `/social`, `/learn?topic=...` |
| `Maximize2` / `Minimize2` from `lucide-react` | — | Fullscreen toggle |

---

## 6. Interactive patterns

| Pattern | Impl |
|---|---|
| Escape to exit fullscreen | `useLayoutEffect` binds `keydown`, calls `setGraphFullscreen(false)` |
| Body scroll-lock (fullscreen) | `document.body.style.overflow = 'hidden'`; restore on cleanup |
| Debounced search | `setTimeout(200)` + `courseDebounceRef` |
| Portal-positioned dropdown | `createPortal` (imported at `page.tsx:4`) with `courseInputRect` from `getBoundingClientRect()` + listener on `resize` and capturing `scroll` |
| Two-step confirm | `confirmDeleteCourse` state; Cancel resets |
| Collapsible rows | `Set<string>` of collapsed subject names |
| Mobile tab toggle | Single `mobileSidebarTab` prop switches between 'courses'/'stats'/null |
| ResizeObserver for graph canvas | debounced 250ms after first observation to avoid janky re-measures |
| Typewriter greeting | `setInterval(55)` appending one char at a time |
| Blinking cursor | `setInterval(530)` while typing |

---

## 7. Loading / empty / error states

- **Loading** (entire page): centered "Loading your dashboard..." (`page.tsx:425-431`).
- **Error** (entire page): centered card with error message + "Retry" button that forces `window.location.reload()` (`page.tsx:433-446`).
- **Graph loading** (after outer loading resolves): centered "Loading graph…" until `graphDimensions.width > 0` (`page.tsx:803-807`).
- **No assignments**: "No upcoming assignments" (`page.tsx:966-967`).
- **No courses** (mobile panel): "No courses yet".
- **No courses** (modal): "No courses added yet."
- **Course-search no matches**: suggestions panel simply doesn't render. (Silent — could be improved.)
- **`suggestConcept` without matching `suggestNode`**: popup doesn't render. User sees no indication the suggestion target is missing.

---

## 8. Edge cases

1. **`suggestConcept` with no matching node**: silent. User clicked the recommendation but the concept has since been renamed/removed — nothing happens. Consider a toast.
2. **Dismiss button routes to `/`** (landing page) instead of clearing the query param (`page.tsx:857`). Likely a bug. Should be `router.replace('/dashboard')`.
3. **`formatDueDate` / `formatRelativeTime`** live in `lib/graphUtils.ts`. Not catalogued here — cover in Phase 4.
4. **`filteredEdges` hides cross-subject edges** (`page.tsx:179-189`). Subject-root edges always kept. Concept-to-concept edges only kept if both endpoints share a subject. Prevents visual clutter when showing multiple courses.
5. **Date math is local-timezone sensitive** (`weekInfo` uses `setHours(0,0,0,0)` and `getDay()`). A user crossing midnight or in an unexpected timezone might see yesterday's streak dot still highlighted. Not obviously broken but worth noting.
6. **`quote` is picked in a `useEffect`** (`page.tsx:227-229`) to avoid SSR hydration mismatch — if moved to the render body it would cause a mismatch on first paint.
7. **Random-quote array includes both quotes and "Fun fact:" entries** (`page.tsx:46-59`). If the rebuild changes the format, keep both styles or choose one.
8. **Course-search failure path** (`handleAddCourseFromCatalog` `catch`, `page.tsx:381-388`) attempts to parse the error message as JSON and extract `.detail` — because FastAPI error responses are JSON-shaped. Preserve this if backend keeps returning `{detail: ...}`.

---

## 9. Accessibility

- No `aria-label` on the Fullscreen / Exit-fullscreen buttons' icons — only visible text labels ("Fullscreen" / "Exit"), which is fine for icon+text buttons.
- Delete confirmation uses two real `<button>` elements (Cancel / Confirm) — keyboard reachable. ✅
- The course search's typeahead dropdown does not use ARIA combobox roles. Autocomplete is keyboard-navigable via Tab, but arrow keys don't move through suggestions. Regression opportunity in the rebuild — add `role="combobox"`/`role="listbox"`/`aria-activedescendant`.
- Streak-day circles are purely visual. A screen reader user gets no indication of the week's activity. Consider `aria-label` on the day containers.

---

## 10. Responsive behavior

- Breakpoint: 768px (`useIsMobile` helper, reused across many pages).
- Desktop layout: 3-column (`300px` left | flex center | `320px` right), `height: calc(100vh - 48px)` fixed.
- Mobile layout: vertical stack with `My Courses`/`Stats & More` toggle tabs. Each tab reveals the corresponding panel. Left panel is *not* shown on mobile (`!isMobile &&`).
- Graph fullscreen is desktop-only (`!isMobile &&` guard).

---

## 11. Things to preserve in the rebuild

- Four-parallel-fetch mount pattern (`Promise.all`) with a single spinner + single error card.
- AI-recommendation popup with **Dismiss** and **Start Quiz** actions — fix the Dismiss `/` regression.
- `?suggest=<concept>` deep link contract (Navbar and other pages emit this).
- Fullscreen graph overlay with Escape to exit + body scroll lock.
- Courses modal with three capabilities: search-to-add, inline color picker (hex input), two-step delete.
- Portal-positioned dropdowns inside scrollable modals.
- Monday-first weekly streak strip with today highlighted orange.
- Streak count + activity dots derived from `node.last_studied_at`.
- Typewriter greeting with blinking cursor — tasteful but optional; the greeting text itself (time-of-day + first name) should remain.
- Random quote on mount — make sure to render client-only to avoid hydration mismatch, or seed deterministically.
- `getCourseColor` / `getMasteryColor` / `getMasteryLabel` / `formatDueDate` / `formatRelativeTime` / `PRESET_COURSE_COLORS` / `RAINBOW_COLORS` from `lib/graphUtils.ts` — these helpers are reused across Dashboard, Tree, Learn, Calendar, Library. Preserve their signatures or migrate them as a cohesive unit.
- Quick Quiz shortcut → `/learn?mode=quiz` (direct deep link, no topic specified — Learn will prompt).
- Study Room shortcut → `/social`.

## 12. Question surfaced by this deep-dive

**Q14.** Dashboard's AI-recommendation "Dismiss" button routes to `/` (landing) instead of `/dashboard`. `src/app/dashboard/page.tsx:857`. Appears to be a copy-paste error — `/social` uses the same pattern but routes to `/social` (`src/app/social/page.tsx:264`). Confirm it's a bug; fix in rebuild.
