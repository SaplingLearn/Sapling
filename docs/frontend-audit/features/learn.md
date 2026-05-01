# Feature · Learn (AI Tutoring Session)

> Covers: `/learn` (`src/app/learn/page.tsx`, 594 lines) — the main AI tutoring experience. Orchestrates `ChatPanel`, `QuizPanel`, `ModeSelector`, `SharedContextToggle`, `AIDisclaimerChip`, `DisclaimerModal`, `SessionSummary`, `SessionFeedbackFlow`, and a second `KnowledgeGraph`. This is the largest and most interconnected feature surface in the app.

---

## 1. Overview

A Learn session is a real-time conversation with a Gemini-backed AI tutor, scoped to a `topic` (either a concept name or a course name) within a chosen teaching **mode** (Socratic, Expository, TeachBack). The page also hosts a parallel **Quiz mode** that generates multiple-choice questions on the same concepts, scores them, and writes mastery changes back to the user's knowledge graph.

Main layout (desktop):
- **Top bar** (52px): back-to-home arrow, course `CustomSelect`, "Resume session" `CustomSelect` (with per-item delete), current topic + mastery label, `AIDisclaimerChip`, `SharedContextToggle`, `ModeSelector` (Socratic/Expository/TeachBack + Quiz toggle).
- **Left pane**: `ChatPanel` when not in Quiz mode, `QuizPanel` when in Quiz mode. `ChatPanel` renders markdown with KaTeX math via `remark-math` + `rehype-katex`.
- **Right pane**: a live `KnowledgeGraph` updated after every chat turn; "View Full Tree" link bottom-right; AI recommendation popup (when `?suggest=`).
- **Bottom overlays**: `SessionSummary` modal when a session ends; `SessionFeedbackFlow` when feedback is due.

Mobile collapses the two panes into a tabbed `Chat` / `Graph` view.

---

## 2. User flows

### 2.1 Flow: start a session from URL params

Trigger: user navigates to `/learn?topic=<concept>&mode=socratic` (Navbar `?suggest=` / Dashboard recommendation card / recommendations list / tree click).

1. `LearnInner` mounts. `topicParam = searchParams.get('topic')`; `modeParam = searchParams.get('mode')` (falls back to `'socratic'`). `modeParam === 'quiz'` sets `quizMode=true` and `?initialQuiz=true`.
2. Initial graph loads (`getGraph` + `getSessions`) on `userReady` (`page.tsx:143-151`). Recent sessions are filtered to those with `message_count > 0`.
3. `useEffect` (`page.tsx:176-179`): if `topicParam && !quizMode`, calls `beginSession(topicParam, mode)`. Else, user picks a course/topic from the top bar.
4. `beginSession(topic, mode, courseId?)`:
   - `POST /api/learn/start-session {user_id, topic, mode, use_shared_context, course_id}` → `{session_id, initial_message, graph_state}`.
   - `setSessionId`, replaces `nodes`/`edges` with returned `graph_state`, pushes initial assistant message.
   - Errors: tries `JSON.parse(e.message).detail`; falls back to generic. Displays inline red banner at top of chat (`page.tsx:464-476`).
5. First turn is the AI's opening message (specific to mode).

### 2.2 Flow: chat turn

Trigger: user types into `ChatPanel` textarea and presses Enter or clicks Send (`ChatPanel.tsx:48-50`).

1. `handleSend(message)` (`page.tsx:207-234`):
   - Appends user's message to `messages` state immediately (optimistic).
   - `setChatLoading(true)` → `ChatPanel` renders `···` typing indicator in an assistant-styled bubble.
   - `POST /api/learn/chat {session_id, user_id, message, mode, use_shared_context}` → `{reply, graph_update, mastery_changes}`.
   - On success: pushes assistant reply, refetches the graph (fire-and-forget `getGraph` — `graph_update` in the response is unused in the current implementation).
   - On first user message (`messages.filter(m=>m.role==='user').length === 0`), refetches recent sessions so the new session appears in the "Resume session" dropdown.
   - On error: `console.error` — user sees their own message echoed but nothing else. No error surfaced. (Improvement opportunity.)
2. ChatPanel auto-scrolls on every new message (`ChatPanel.tsx:34-39`).

### 2.3 Flow: quick action (hint / confused / skip)

Trigger: one of three inline text buttons at the bottom of the chat input area (`ChatPanel.tsx:174-180`).

1. `onAction(action)` on `ChatPanel` → `handleAction` on `/learn` page (`page.tsx:236-253`):
   - `POST /api/learn/action {session_id, user_id, action_type, mode, use_shared_context}` → `{reply, graph_update}`.
   - Assistant reply is appended; no user-side "you asked for a hint" message is shown (the AI's reply is self-describing).
   - Graph is refetched after.

### 2.4 Flow: mode switch

Trigger: user clicks Socratic/Expository/TeachBack in the `ModeSelector`.

1. `handleModeChange(newMode)` (`page.tsx:274-291`):
   - Short-circuit if `newMode === mode`.
   - `setMode(newMode)` — `ChatPanel`'s "mode description" banner updates.
   - If a session is in progress, `POST /api/learn/mode-switch {session_id, user_id, new_mode}` → `{reply}`. Appends assistant reply + sets `prefillInput = "Continue in ${newMode} mode on ${topic}..."` which `ChatPanel` picks up via `useEffect` (`ChatPanel.tsx:30-32`) and pre-fills into the textarea.

### 2.5 Flow: quiz mode

Trigger: user clicks the Quiz toggle in `ModeSelector` (`onToggleQuiz`), or arrives with `?mode=quiz`.

Quiz is a **separate component** (`QuizPanel`) that replaces `ChatPanel` in the left pane. It has four phases (`QuizPanel.tsx:17`):

- **`select`**: scrollable list of concept radio buttons (only for the currently selected course — `subjectFilter` derived from `selectedCourse` or `preselectedNode?.subject`). Each row shows concept name + mastery percentage pill. Fixed bottom controls: Questions count (5/10/15 via `CustomSelect`), Difficulty (`easy`/`medium`/`hard`/`adaptive` via `CustomSelect`), and a "Start Quiz" button.
  - `startQuiz()`: `POST /api/quiz/generate {user_id, concept_node_id, num_questions, difficulty, use_shared_context}` → `{quiz_id, questions}`. Phase → `active`.
  - If `subjectFilter` is empty (no course selected), shows "Select a course first" text.
- **`active`**: renders one question with `q.options` as buttons. Options have `label` (A/B/C/...) + `text`. Selecting sets `selectedAnswer`; Submit fires `submitAnswer()`:
  - Computes correctness locally by comparing to `opt.correct`.
  - Builds a `QuizResult` with `correct_answer`, `explanation`, etc.
  - Pushes into local `answers` array (sent to server at quiz-end).
  - Phase → `review`.
- **`review`**: the same question with color-coded options (green for correct, red for user's wrong pick) + the `q.explanation` panel + optional "Explain this" button (shown only if answer was wrong and `onLearnConcept` prop exists). Clicking "Explain this" calls `onLearnConcept(q.concept_tested)` → `/learn` exits quiz mode and starts a chat session on that concept. "Next" (or "See Results" on last question) advances.
- **`results`**: shows `score/total`, percentage, mastery delta (green if positive else red), per-question Y/N list, and two buttons: **Retake** (reset to `select`) and **Learn Weak Areas** (calls `onLearnConcept('')` which in `/learn` means exit quiz without a target concept).
  - `finishQuiz()`: `POST /api/quiz/submit {quiz_id, answers}` → `{score, total, mastery_before, mastery_after, results}`.

### 2.6 Flow: resume a session

Trigger: user picks a session from the "Resume session…" `CustomSelect` in the top bar.

1. `handleResumeSession(sid)` (`page.tsx:313-332`):
   - `GET /api/learn/sessions/:id/resume` → `{session: {id, user_id, topic, mode, course_id, started_at, ended_at}, messages: [{id, role, content, created_at}]}`.
   - Hydrates `sessionId`, `topic`, `mode`, `messages` (mapped with `timestamp: m.created_at`).
2. The UI continues from where they left off — `ChatPanel` renders the full history.

Per-item delete: `CustomSelect` calls `onDelete` (`handleDeleteSession`, `page.tsx:304-311`) → `DELETE /api/learn/sessions/:id?user_id=` → filter out of `recentSessions`.

### 2.7 Flow: end a session

Trigger: user clicks "End Session" in the chat input footer (`ChatPanel.tsx:181-185`).

1. `handleEndSession()` (`page.tsx:255-272`):
   - `POST /api/learn/end-session {session_id, user_id}` → `{summary}`.
   - `setSummary(res.summary)` → `SessionSummary` modal appears.
   - Increments `localStorage.sapling_session_end_count`. Every `SESSION_FEEDBACK_EVERY_N` (`=5`) ends, sets `feedbackDueRef.current = true` and resets the counter to 0.
2. `SessionSummary` modal (`SessionSummary.tsx`) renders:
   - Heading: "Session Complete"
   - Concepts Covered — pills
   - Mastery Changes — concept name + delta % (green/red)
   - Time Spent — formatted minutes
   - Recommended Next — list of concept names
   - Two buttons: **Dashboard** (`router.push('/dashboard')`, optionally deferred behind feedback modal) and **New Session** (clear `sessionId`/`messages`, optionally open feedback).
3. If `feedbackDueRef.current` is true:
   - **Dashboard**: stores `pendingNavRef = '/dashboard'`, opens `SessionFeedbackFlow`; on dismiss, `router.push(pendingNavRef)`.
   - **New Session**: just opens `SessionFeedbackFlow`; on dismiss user stays on `/learn`.

### 2.8 Flow: the session feedback card

Source: `src/components/SessionFeedbackFlow.tsx`. A bottom-right-anchored toast-card with `slide-up`/`slide-down` keyframes.

Four internal steps (`SessionFeedbackFlow.tsx:34`):

- **`rating`**: 5 emoji buttons (😞 / 😕 / 😐 / 🙂 / 😊). Click → after 300ms → step `detail`.
- **`detail`**: 7 checkbox-style pill options (`Explanations were unclear`, `Responses felt too generic`, `Difficulty felt off`, `Session went off-track`, `Something seemed inaccurate`, `Pacing was too fast / slow`, `Not enough examples`). Two buttons: **Skip** (dismiss) / **Next →** (step `text`).
- **`text`**: optional free-text comment (textarea, 4 rows). **← Back** / **Submit** buttons. Submit fires `submitFeedback({user_id, type:'session', rating, selected_options, comment, session_id, topic})` — fire-and-forget (`.catch(() => {})`).
- **`done`**: shows either 🌱 (rating ≥ 3, "Keep growing!") or 🙏 (otherwise, "We'll use this to improve."). Auto-dismisses after 1800ms.

Header copy adapts per step:
- rating: "How was your last learn session?"
- detail (rating ≥ 3): "Any areas for improvement?"
- detail (rating < 3): "What fell short?"
- text: "Anything else to add? / **We will listen to YOU!**"
- done: "Thanks for the feedback!"

### 2.9 Flow: navigate-away feedback trigger (global)

Source: `src/components/SessionFeedbackGlobal.tsx` (mounted in root layout).

- Tracks the previous `usePathname()`.
- When leaving `/learn` → anywhere else:
  - Checks `localStorage.sapling_learn_had_session === 'true'` (set by `/learn` when `messages.length > 0 && sessionId`, `page.tsx:136-140`).
  - Checks `localStorage.sapling_session_feedback_nav_last_shown` (timestamp). Cooldown `COOLDOWN_MS = 3 * 86_400_000` = **3 days**.
  - If both pass: clear the had-session flag, stamp the last-shown timestamp, `queueMicrotask` → `setVisible(true)` → render the same `SessionFeedbackFlow` component (but without topic/sessionId since the user already left).
  - This is separate from the every-5-sessions trigger described in §2.7.

**Discrepancy with `CLAUDE.md`**: `CLAUDE.md` says "2-day cooldown on navigate-away" — actual value is 3 days. See `QUESTIONS.md` Q15.

### 2.10 Flow: AI-disclaimer first-view + chip

Source: `AIDisclaimerChip.tsx` (top-right of top bar, desktop only).

- On mount, if `localStorage.sapling_disclaimer_ack` is not set, opens `DisclaimerModal` automatically.
- `DisclaimerModal` (`src/components/DisclaimerModal.tsx`, uses `createPortal` to `document.body`): four disclaimer sections (Accuracy / Academic integrity / Content you share / Privacy) + "I understand, continue to Sapling" button. Close via button or overlay click → sets `sapling_disclaimer_ack=1`.
- Hover tooltip on the chip shows a short preview ("Sapling uses Google Gemini...", "Verify with your course materials"). Clicking the chip re-opens the modal.
- **Currently only rendered by `/learn`** (desktop). `/flashcards` also imports `AIDisclaimerChip` but only shows it on that page. Never shown on mobile — mobile users never see it, which is an accessibility / transparency gap.

### 2.11 Flow: shared-course-context toggle

Source: `SharedContextToggle.tsx`. A pill-shaped switch labeled **"Class Intel"**.

- Hover reveals a tooltip explaining what the feature does (aggregated class-level patterns) and reassuring about privacy.
- Clicking toggles `useSharedContext` (persisted to `localStorage.sapling_shared_ctx` — the `/learn` page owns this state).
- The boolean is passed into every API call that supports it: `startSession`, `sendChat`, `sendAction`, `switchMode`, `generateQuiz`. The backend uses it to decide whether to inject the `shared_context.txt` prompt fragment.

### 2.12 Flow: click a node in the right-pane graph

Trigger: user clicks a concept node in the `KnowledgeGraph`.

1. `handleNodeClick(n)` (`page.tsx:338-343`):
   - Uses a `ref` (`nodeClickPayloadRef`) so the callback identity stays stable across re-renders — important because `KnowledgeGraph`'s D3 `useEffect` has `onNodeClick` as a dependency and would reseed the simulation on every change otherwise.
   - Sets `topic = n.concept_name`.
   - Calls `beginSession(n.concept_name, mode, n.course_id)` — ends any current session in `state` (not on the server — see edge cases) and starts a new one.

### 2.13 Flow: `?suggest=` popup

Identical in shape to `/dashboard`'s popup but **correctly** clears `?suggest=` from the URL on Dismiss (`page.tsx:548-553`):

```ts
const params = new URLSearchParams(searchParams.toString());
params.delete('suggest');
router.replace(q ? `/learn?${q}` : '/learn');
```

"Start Quiz →" navigates to `/learn?topic=<concept>&mode=quiz` which re-enters quiz mode.

---

## 3. State (`/learn` page)

| State | Type | Source |
|---|---|---|
| `mode` | `TeachingMode` (`socratic`\|`expository`\|`teachback`) | query param → state |
| `quizMode` | `boolean` | `?mode=quiz` or toggle |
| `nodes`, `edges`, `graphReady` | graph state | `getGraph(userId)` and `startSession.graph_state` |
| `messages` | `ChatMessage[]` | inline appends |
| `sessionId` | `string \| null` | `startSession` / `resumeSession` |
| `chatLoading`, `sessionLoading`, `sessionError` | ui flags | — |
| `summary` | `SessionSummary \| null` | `endSession` result |
| `showSessionFeedback` | `boolean` | every-5-sessions trigger + `?testFeedback=session` dev override |
| `topic`, `selectedCourse`, `prefillInput` | strings | user input |
| `recentSessions` | session list | `getSessions(userId, 10)` |
| `useSharedContext` | `boolean` | `localStorage.sapling_shared_ctx` (default true) |
| `mobileView` | `'chat' \| 'graph'` | mobile tab toggle |
| `apiCourseNames`, `enrolledCourses`, `courseColorMap` | course context | `getCourses(userId)` |
| `graphDimensions` | `{width,height}` | ResizeObserver (debounced 200ms) |
| `feedbackDueRef` | `boolean` ref | every-5-sessions flag |
| `pendingNavRef` | `string \| null` ref | destination deferred behind feedback modal |

### 3.1 State inside `ChatPanel`

- `input` (`string`) — textarea contents
- `messagesContainerRef` — for auto-scroll

### 3.2 State inside `QuizPanel`

| State | Type |
|---|---|
| `phase` | `'select'\|'active'\|'review'\|'results'` |
| `selectedNodeId` | `string` |
| `numQuestions` | `number` (5/10/15) |
| `difficulty` | `string` (easy/medium/hard/adaptive) |
| `quizId` | `string` |
| `questions` | `QuizQuestion[]` |
| `currentQ` | `number` |
| `selectedAnswer` | `string \| null` |
| `answers` | `{question_id, selected_label}[]` |
| `reviewData` | `QuizResult \| null` |
| `results` | full results object |
| `loading`, `error` | ui |

---

## 4. API calls

| Call | When |
|---|---|
| `getGraph(userId)` → `GET /api/graph/:userId` | mount + after every chat turn / action |
| `getSessions(userId, 10)` → `GET /api/learn/sessions/:userId?limit=10` | mount + after first user message |
| `getCourses(userId)` → `GET /api/graph/:userId/courses` | mount |
| `startSession(userId, topic, mode, courseId?, useSharedCtx)` → `POST /api/learn/start-session` | `beginSession` |
| `sendChat(sessionId, userId, message, mode, useSharedCtx)` → `POST /api/learn/chat` | `handleSend` |
| `sendAction(sessionId, userId, action, mode, useSharedCtx)` → `POST /api/learn/action` | hint/confused/skip |
| `switchMode(sessionId, userId, newMode)` → `POST /api/learn/mode-switch` | `handleModeChange` |
| `endSession(sessionId, userId)` → `POST /api/learn/end-session` | End Session button |
| `resumeSession(sessionId)` → `GET /api/learn/sessions/:id/resume` | Resume session dropdown |
| `deleteSession(sessionId, userId)` → `DELETE /api/learn/sessions/:id?user_id=` | per-item delete in dropdown |
| `generateQuiz(userId, conceptNodeId, n, difficulty, useSharedCtx)` → `POST /api/quiz/generate` | QuizPanel "Start Quiz" |
| `submitQuiz(quizId, answers)` → `POST /api/quiz/submit` | end of quiz |
| `submitFeedback({user_id, type:'session', ...})` → `POST /api/feedback` | `SessionFeedbackFlow` submit |

**No streaming.** CLAUDE.md mentions the backend uses SSE for the learn endpoint (`routes/learn.py` described as "streaming AI tutoring chat endpoint (SSE)"), but the frontend uses a **regular `fetch`** to a non-streaming `.json()` response. The backend must be serving a non-streamed JSON response to `/api/learn/chat`, OR the SSE route is unused. Flag in QUESTIONS.

**No retries.** All calls fail silently (except `startSession` which surfaces a banner).

---

## 5. Components involved

| Component | Role | Notes |
|---|---|---|
| `ChatPanel` | Message list + input + quick actions + End Session | Uses `ReactMarkdown` with `remark-math` + `rehype-katex`; KaTeX CSS imported top-of-file. Enter (no shift) sends. |
| `QuizPanel` | 4-phase quiz UI | Local correctness check; submits full answer set only at end. |
| `ModeSelector` | 3 mode buttons + Quiz toggle | Hover tooltips describe each mode. |
| `SharedContextToggle` | "Class Intel" switch | Hover tooltip; persists to `localStorage.sapling_shared_ctx`. |
| `AIDisclaimerChip` | Auto-opens `DisclaimerModal` on first view | Persists `sapling_disclaimer_ack`. |
| `DisclaimerModal` | Portal-rendered fullscreen modal | 4 disclaimer sections + single ack button. |
| `SessionSummary` | End-of-session modal | Concepts covered, mastery changes, time spent, recommended next. |
| `SessionFeedbackFlow` | 4-step bottom-right feedback card | Also used by the navigate-away trigger in `SessionFeedbackGlobal`. |
| `KnowledgeGraph` | Right pane (desktop) / Graph tab (mobile) | Highlights `suggestNode?.id ?? topicNode?.id`. |
| `CustomSelect` | Course picker + Resume Session dropdown | Resume dropdown uses `onDelete` to support per-item delete. |

---

## 6. Edge cases

1. **Clicking a graph node while a session is active** does not call `endSession` on the server — it just starts a new one. The old session is orphaned (still "active" in the DB). Backend probably tracks `is_active` based on `end_session` calls; leaving multiple active sessions may or may not be safe. Flag.
2. **Chat error handling** (`handleSend` catch, `page.tsx:229-233`): `console.error` only. No assistant error bubble, no toast. User thinks the AI is just silent.
3. **Session-start error parsing** assumes FastAPI's `{detail: ...}` shape (`page.tsx:200`): `JSON.parse(e.message)?.detail ?? msg`. If the backend changes error shape, this fails silently.
4. **`handleAction` dispatches before the server responds** but does not append a "you asked for a hint" user message — so the message history looks like the assistant just started being more helpful out of nowhere. Intentional for UX minimalism but could confuse.
5. **`graph_update` response field is ignored** (`page.tsx:225` discards `res.graph_update` and refetches `getGraph(userId)` instead). Every chat turn therefore makes two network calls. Opportunity to merge `graph_update` client-side and skip the refetch.
6. **Quiz `onLearnConcept('')` means "learn weak areas"** — empty-string is overloaded. Works because the handler checks `if (concept)` (`page.tsx:453-458`). Fragile.
7. **`CustomSelect` with `onDelete` and the Resume Session dropdown**: deleting the currently-active session from the dropdown doesn't end the session on the server — it just removes it from the list. The active chat keeps working; the user just can't find it again by name.
8. **`?testFeedback=session` query param** (`page.tsx:54-56`) force-opens the feedback flow for QA. Preserve or remove intentionally in the rebuild.
9. **`messages.length > 0 && sessionId`** → sets `sapling_learn_had_session=true`. But `signOut` doesn't clear this (like `sapling_onboarding_pending` — same pattern).
10. **Mode switch after no session started**: `handleModeChange` skips the backend call if `!sessionId`. Good.
11. **Prefill input has no effect if `prefillInput` is the same string as previous** (React's `useEffect` on `prefillInput` would still run, but `setInput(prefillInput)` is idempotent). Harmless.

---

## 7. Interactive patterns

| Pattern | Impl |
|---|---|
| Enter-to-send / Shift+Enter for newline | `ChatPanel.tsx:48-50` |
| Auto-scroll on new message | `messagesContainerRef.current.scrollTop = scrollHeight` on `[messages, loading]` |
| Typing indicator | Bubble with `···` character repeat |
| Markdown + math rendering | `ReactMarkdown` + `remark-math` + `rehype-katex` + `katex/dist/katex.min.css` |
| Markdown code blocks | Custom `components` map: inline `code` uses accent-dim bg + monospace; block `pre` has its own styled bg |
| Hover tooltips | `onMouseEnter`/`onMouseLeave` + conditional div; `pointer-events: none`, fixed width (240-290px), z-index 9999 |
| Bottom-right slide-in/out feedback card | Inline `@keyframes` in component scope (`SessionFeedbackFlow.tsx:303-312`) |
| 4-phase progression | Discrete `step` / `phase` enums with guarded transitions |
| Suggestion popup dismiss that preserves other query params | `URLSearchParams` clone, `.delete('suggest')`, `router.replace` |

---

## 8. Storage

| Storage | Key | Purpose |
|---|---|---|
| `localStorage` | `sapling_shared_ctx` | Remember Class Intel toggle |
| `localStorage` | `sapling_session_end_count` | Every-5-sessions feedback trigger |
| `localStorage` | `sapling_learn_had_session` | Navigate-away feedback trigger |
| `localStorage` | `sapling_session_feedback_nav_last_shown` | Navigate-away cooldown timestamp |
| `localStorage` | `sapling_disclaimer_ack` | First-view disclaimer modal ack |
| ref-only | `feedbackDueRef`, `pendingNavRef`, `nodeClickPayloadRef` | non-render state |

---

## 9. Accessibility

- Chat bubbles are plain divs — no `role="log"` or `aria-live="polite"` on the messages container. Screen reader users won't hear new AI replies.
- Action buttons (hint/confused/skip) are unlabeled lowercase text buttons. Their contrast against the toolbar background is low. Add `aria-label` / improve contrast.
- The `ModeSelector` tooltips are `pointer-events: none` so they cannot be read by tabbing. Tooltip content is meaningful (describes each mode) — consider `aria-describedby` or a secondary "help" surface.
- Quiz option buttons receive focus naturally and selected state is visible, but they lack `role="radio"`/`role="radiogroup"`. Screen reader experience may not convey the group's single-selection semantics.
- `DisclaimerModal` does not trap focus or restore focus to the chip on close. No `role="dialog"`/`aria-modal`. Add focus trap in the rebuild.
- `SessionFeedbackFlow`'s emoji buttons have `title` attributes for the rating labels but no `aria-label` — screen readers will read only the raw emoji name.

---

## 10. Things to preserve in the rebuild

- **Three teaching modes** with the existing descriptions and the mid-session "Continue in X mode..." prefill prompt.
- **Quick actions** (hint / confused / skip) as cheap one-click turns.
- **Quiz mode** as a separate pane inside `/learn` (not a separate route). The 4-phase progression (`select` → `active` → `review` → `results`) is well-designed — keep it.
- **Markdown + KaTeX math rendering** in assistant messages.
- **Live graph updates** after each turn (even if sourced more efficiently than a full refetch).
- **Resume Session dropdown** with per-item delete.
- **Shared-course-context toggle** labeled "Class Intel" (or an equivalent privacy-respecting framing).
- **First-view disclaimer modal** with the four section headings.
- **Session end summary** with concepts / mastery deltas / time / recommended next.
- **Every-5-sessions feedback trigger** + **3-day navigate-away cooldown** (separate triggers that both surface the same `SessionFeedbackFlow`).
- **`?topic`, `?mode`, `?suggest`, `?testFeedback` URL contracts.**
- **Dismiss-preserves-other-query-params** pattern — the right way to clear one suggestion without nuking a deep link.
- **Stable-callback pattern** for `handleNodeClick` using a ref — keeps the graph's D3 simulation from re-seeding on every parent render.

## 11. Questions surfaced by this deep-dive

**Q15.** `CLAUDE.md` says "2-day cooldown" on the navigate-away session feedback trigger; actual code is **3 days** (`src/components/SessionFeedbackGlobal.tsx:9` → `COOLDOWN_MS = 3 * 86_400_000`). Confirm which is intended.

**Q16.** `CLAUDE.md` describes `routes/learn.py` as a streaming SSE endpoint, but `/learn` consumes `POST /api/learn/chat` with a regular `.json()` response — no streaming on the frontend. Is the backend actually streaming (frontend just ignores the stream and awaits the terminal JSON)? If so, the rebuild should implement real streaming. If not, the "(SSE)" note in `CLAUDE.md` is stale.

**Q17.** Clicking a graph node while a session is active orphans the old session (never calls `endSession`). Intentional or a bug? (Backend probably has a session-timeout / idle-kill but that's not verified.)
