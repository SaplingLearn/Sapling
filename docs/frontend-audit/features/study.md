# Feature · Study (Guide + Flashcards)

> Covers: `/study` → `StudyClient` + `FlashcardsPanel`. The study hub is a dual-mode page: AI-generated study guides for upcoming exams, and an embedded flashcards experience. Shares the flashcards backend API with the standalone `/flashcards` route.

---

## 1. Overview

`/study/page.tsx` is a Suspense shell. `StudyClient` (`src/app/study/StudyClient.tsx`, 316 lines) owns all logic. A top-bar toggle switches between two modes:

- **Study Guide** — pick a course + upcoming exam → generate a structured study guide → render it full-page.
- **Flashcards** — embedded `FlashcardsPanel` (`src/app/study/FlashcardsPanel.tsx`, 322 lines) with its own generator + deck browser + study mode (flip cards + rating).

**Important**: the flashcards experience inside `/study` is a **separate** copy of the logic used by `/flashcards` (the standalone page, see `features/flashcards.md`). They use the same backend endpoints (`generateFlashcards`, `getFlashcards`, `rateFlashcard`, `deleteFlashcard`) and very similar UI, but diverge in layout and minor behaviors. A rebuild should unify them.

StudyClient uses **raw `fetch`** (not `lib/api.ts`) for study-guide endpoints (`StudyClient.tsx:10-20`). Every other feature uses `lib/api.ts`. Odd but documented here so a rebuild doesn't miss it when consolidating.

---

## 2. User flows

### 2.1 Flow: generate a study guide

1. Mount: `fetchJSON('/api/study-guide/:userId/courses')` populates the Course picker (`StudyClient.tsx:68-74`). Simultaneously `loadCached()` hits `/api/study-guide/:userId/cached` for the "Recent guides" list on the right.
2. User selects a Course from `CustomSelect` → `selectedCourseId` state.
3. Course-change effect hits `/api/study-guide/:userId/exams?course_id=<id>` → populates Exam picker (`StudyClient.tsx:76-83`).
4. User selects an Exam.
5. "Generate Guide" button → `handleGenerate()` → `GET /api/study-guide/:userId/guide?course_id&exam_id`. Phase: `selection` → `loading` (spinner overlay, `StudyClient.tsx:216-229`) → `guide`.
6. Guide rendered full-page at `mode === 'study-guide' && guideState === 'guide'` (`StudyClient.tsx:175-213`). Layout:
   - Top bar: `←` back (reset to `selection`), "Study Guide", exam name, `Regenerate` button.
   - Card 1: Exam — title, optional "Due {date}", overview paragraph.
   - For each topic: name, importance (italic one-liner), bulleted concept list.
   - Footer: "Generated at {timestamp}".
7. `Regenerate` button → `POST /api/study-guide/regenerate {user_id, course_id, exam_id}` (`StudyClient.tsx:120-137`). Overwrites the cached guide. On success, `loadCached()` refreshes the "Recent guides" sidebar.

### 2.2 Flow: open a cached guide

Trigger: user clicks a "Recent guides" card on the right panel.

- `handleOpenCached(cached)` (`StudyClient.tsx:103-118`): sets selected course/exam from the cached row's IDs, phase → `loading`, fetches `/api/study-guide/:userId/guide?course_id=<>&exam_id=<>`, renders.

### 2.3 Flow: flashcards (embedded `FlashcardsPanel`)

`FlashcardsPanel` is the same component pattern as `/flashcards/page.tsx` but called as a child of `/study`. It receives `onStudyModeChange(active)` which `StudyClient` uses to hide the ModeToggle while the user is studying a deck full-screen.

Two sub-modes:

- **Browse**: left panel (generator + per-topic study buttons) + right panel (card grid filtered by topic).
  - Generator: list of enrolled course names (no free-text topic). Click a course → `generateFlashcards(userId, courseName, 10)` → prepends `res.flashcards` into the deck (`FlashcardsPanel.tsx:54-69`). Shows a "Generated using N library docs / M weak concepts" chip if `res.context_used` is present.
  - Topic filter pills: `['', ...topics]` — each shows the count of cards with that topic.
  - Card: Topic pill + last rating pill (Forgot/Hard/Easy, color-coded) + Q/A blocks + `times_reviewed` meta + delete X.
- **Study mode**: full-page flip-card with `perspective: 1200px`, 0.55s 3D Y-flip animation. Top bar: back arrow, topic, `1 / N`, progress bar. Card: Question side + "tap to reveal" → Answer side. Three rating buttons (Forgot=1 / Hard=2 / Easy=3) revealed after flip. On rate:
  - `rateFlashcard(userId, cardId, rating)` optimistically updates card.
  - 300ms after, auto-advances to next card (or exits study mode if last).
- Entering study mode: `startStudy(topicFilter?)` filters the deck by topic and sets `studyCards`. Calls `onStudyModeChange(true)` so parent hides the ModeToggle.

### 2.4 Flow: mode toggle (Study Guide vs Flashcards)

- Top-bar toggle: two pill buttons (`StudyClient.tsx:155-170`). `FlashcardsPanel` is **always mounted** (`display: mode==='flashcards' ? 'flex' : 'none'`) so its state survives mode switches. Study guide state (`guideState`, `guide`) also persists across toggles.
- Mobile: same layout, stacked vertically.

---

## 3. State

`StudyClient`:
- `mode`: `'study-guide' | 'flashcards'` (default `'study-guide'`)
- `flashcardStudyMode`: boolean — hides the ModeToggle when true
- `guideState`: `'selection' | 'loading' | 'guide'`
- `courses`, `exams`, `cachedGuides`: server data
- `selectedCourseId`, `selectedExamId`: picker state
- `guide`: `StudyGuide | null`
- `generatedAt`: timestamp string
- `error`: error copy for the generator
- `regenerating`: flag

`FlashcardsPanel`:
- `cards`, `courses` (names array), `loading`, `error`
- `topic`: last-generated topic name (pill on the course button)
- `generating`: in-flight
- `filterTopic`: active filter pill
- `studyMode`, `studyIndex`, `flipped`, `studyCards`: study-mode state
- `lastContextUsed`: `{documents_found, weak_concepts_found} | null` (for the "Generated using N library docs" chip)

---

## 4. API calls

Study-guide (raw fetch, not `lib/api.ts`):
- `GET /api/study-guide/:userId/courses`
- `GET /api/study-guide/:userId/exams?course_id=`
- `GET /api/study-guide/:userId/guide?course_id=&exam_id=`
- `GET /api/study-guide/:userId/cached`
- `POST /api/study-guide/regenerate`

Flashcards (via `lib/api.ts`):
- `generateFlashcards(userId, topic, 10)` → `POST /api/flashcards/generate`
- `getFlashcards(userId)` → `GET /api/flashcards/user/:userId`
- `rateFlashcard(userId, cardId, rating)` → `POST /api/flashcards/rate`
- `deleteFlashcard(userId, cardId)` → `DELETE /api/flashcards/:cardId?user_id=`
- `getCourses(userId)` → `GET /api/graph/:userId/courses`

---

## 5. Components involved

| Component | Role |
|---|---|
| `StudyClient` | Top-level mode switcher + study-guide flow |
| `FlashcardsPanel` | Embedded flashcard experience |
| `CustomSelect` | Course + Exam pickers (`openUpward` on the Exam one since it's near the bottom) |

---

## 6. Edge cases

1. **Raw `fetch` instead of `lib/api.ts`.** `StudyClient` does not respect `IS_LOCAL_MODE` — in local mode, the study guide endpoints will 404. Flashcards section inside `/study` does respect local mode because `FlashcardsPanel` uses `lib/api.ts`.
2. **Divergent FlashcardsPanel / flashcards page.** Both exist. They share the API but the UI differs. See `features/flashcards.md` for the differences.
3. **Hidden `FlashcardsPanel` stays mounted** — preserves its state on mode toggle (good UX), but also runs its mount `useEffect` with `getFlashcards` + `getCourses` once and never refetches when the user adds cards elsewhere. A rebuild could refetch on mode-toggle.
4. **"Generated using N library docs" chip only persists until the next generation**, and there's no UI to inspect *which* docs.
5. **Rating and `times_reviewed` increments are optimistic.** The server's response isn't used; if the POST fails, local state is wrong until reload.
6. **Study mode auto-advances after a 300ms delay** — no way to change your mind.
7. **`/study` has no `?` query-param deep link** — even though `/flashcards/:topic` would be a natural URL. If the rebuild wants shareable study-guide links, add a `?course=<>&exam=<>` contract.

---

## 7. Interactive patterns

| Pattern | Impl |
|---|---|
| Flip card | CSS `perspective: 1200px` + `transform: rotateY(180deg)` + `transform-style: preserve-3d` + `backface-visibility: hidden` |
| Auto-advance after rating | `setTimeout(300)` + increment `studyIndex` or exit |
| Mode-toggle with preserved state | `display: none`-based hiding (not conditional unmount) |
| Spinner | inline `@keyframes spin` + CSS border trick |
| Topic filter pills | `setFilterTopic('')` for All, else topic string |

---

## 8. Empty / loading / error states

- Courses list empty: "No courses found. Add courses in the Dashboard first." (FlashcardsPanel).
- No cards: "🃏 No flashcards yet / Generate some using the panel on the left."
- No cached guides: "No guides yet / Generate your first study guide on the left."
- Exam picker disabled (opacity 0.5) when no course selected; placeholder text changes accordingly (`StudyClient.tsx:258`).
- Generation errors → red banner above the generator form.
- Study-guide generation spinner: full takeover, the ModeToggle shows with a spinner + "Generating your study guide..."

---

## 9. Things to preserve in the rebuild

- Two-mode toggle with shared keepalive state.
- Course → Exam cascading picker with live fetch on Course change.
- "Recent guides" sidebar for one-click access to past guides.
- Regenerate button on the guide header.
- Flashcard **rating-based auto-advance** (Forgot/Hard/Easy = 1/2/3 mapping).
- "Generated using N library docs / M weak concepts" chip after generation (preserves the AI transparency).
- 3D flip animation (don't drop it — it's an anchor interaction).
- Keyboard: a rebuild should add Space-to-flip and 1/2/3-to-rate; the current UI requires mouse taps.

## 10. Things to rework

- Consolidate `FlashcardsPanel` (inside `/study`) and `/flashcards/page.tsx` into one canonical component. They've already drifted (see `features/flashcards.md`).
- Migrate `StudyClient` raw fetches to `lib/api.ts` so local mode works.
- Add keyboard shortcuts to flashcard study mode.
- Expose study-guide URL params so guides are shareable.
