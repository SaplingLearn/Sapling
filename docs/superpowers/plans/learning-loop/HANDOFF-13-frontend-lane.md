# HANDOFF-13 — frontend-e2e: Frontend lane

Written by the session that built PKG-13's FRONTEND lane (Tasks 5, 6, 7) on `feat/learning-loop-13-fe-lane` (cut from the PKG-10 tip 4da6166d), in parallel with the backend lane (Tasks 1–4, 8; `HANDOFF-13.md`). This file is the "Frontend lane" section to merge into `HANDOFF-13.md`. Task 9 (the Playwright journeys + full E2E) runs after both lanes merge; no e2e spec was written here and the stack was not started.

## Frontend lane

### What changed

`Learn()` now makes ONE status probe (`getLoopStatus` → `GET /api/learn/loop/review/active`, PKG-12's A72 probe) and renders `LoopLearn` for `{active: true}`; `{active: false}` (the gate's 404), and any error, keep the legacy `LearnInner` tree byte-for-byte (build phase: fail closed). `LoopLearn` is the loop-path Learn screen: it lists the student's open loop sessions for the course (`GET /sessions`) and resumes the newest (or the `?resume=` one); a `?resume=` id that is not an open loop session opens read-only; a failed list is a retry state, never a probe; a new session + probe starts only when none is open or on "New session". The phase (probe → plan → teach ⇄ check → feedback → close) is server-driven through a pure reducer. The attempt box submits only to `/check/answer/stream` (A16); streamed turns honour `retract` (A46) and render `done.reply` as the settled text; the budget pause banner renders from a 429 body or a hard `budget` event with the A39 session-capped copy; the close renders the A60 record with the self-evaluation as a reflection prompt only. `DueQueue` got its launch polish (budget banner, "All caught up", no stale item). No model toggle, no `model_pref` anywhere on the loop path.

Commits: d72c0a06 (Task 5), 99686de7 (Task 6), c5067472 (Task 7), ff7383ab (Suspense boundary).

### Symbols added

- `frontend/src/lib/api.ts`:
  - `ChatResult.leak_redacted?`; `StreamChatHandlers` + `onRetract(reason)`, `onPhase(phase: string)`, `onCheck(item)`, `onHintOffer(rung)`, `onLearnerState(state)`, `onBudget(notice)`; `consumeChatStream` dispatches `retract`, `phase`, `check`, `hint_offer`, `learner_state`, `budget` (legacy callers pass none of them — `api.stream.test.ts` unchanged and green).
  - Types: `LoopPhase`, `LoopBand`, `LoopFormat`, `LoopOption`, `LoopCheckItem`, `LoopProbeItem`, `LoopProbeNext`, `LoopProbeAnswerResult`, `LoopLearnerState`, `LoopPlanConcept`, `LoopPlan`, `LoopOpenSession`, `LoopBudgetNotice`, `LoopStartResult`, `LoopTurnResult`, `LoopCheckNext`, `LoopHintResponse`, `LoopAttemptResult`, `LoopCloseRecord`, `LoopCloseResponse`, `LoopCheckAnswer`, `LoopBudgetPause`.
  - Functions: `budgetPauseOf(err) -> {resetAt, sessionCapped} | null`, `listLoopSessions(userId, courseId) -> LoopOpenSession[]`, `startLoopSession(userId, courseId, topic)`, `nextLoopProbe(sessionId, userId)`, `answerLoopProbe(sessionId, userId, qh, answer)`, `getLoopPlan(sessionId, userId)`, `approveLoopPlan(sessionId, userId, conceptIds)`, `streamLoopChat(sessionId, userId, message, handlers)`, `streamLoopCheckAnswer(sessionId, userId, qh, answer, handlers)`, `postLoopAttempt(sessionId, userId, qh, attemptText)`, `nextLoopCheck(sessionId, userId)`, `requestLoopHint(sessionId, userId, qh)`, `requestLoopHintTurn(sessionId, userId)`, `closeLoopSession(sessionId, userId)`. PKG-12's `getLoopStatus` is reused unchanged (it already resolves 404 → `{active: false}`).
- `frontend/src/components/learn/loopState.ts`: `LoopUiState`, `LoopUiEvent` (`phase`, `check`, `hint_offer`, `hint_taken`, `learner_state`, `done`, `budget`, `budget_clear`, `reset`), `initialLoopState()`, `reduceLoopEvent(state, ev)`, `uiPhaseOf(phase)`.
- `frontend/src/components/learn/useLoopStatus.ts`: `useLoopStatus(userId, userReady) -> boolean | null`.
- `frontend/src/components/learn/LoopLearn.tsx`: `LoopLearn()`.
- `frontend/src/components/learn/BudgetPausedBanner.tsx`: `BudgetPausedBanner({testId, resetAt, sessionCapped?, message, children?})`, `formatResetAt(iso)`, `tutorPauseMessage(resetAt, sessionCapped)`.
- `frontend/src/components/learn/resumeParam.ts`: `readResumeParam` (moved from `screens/Learn.tsx`, which re-exports it — `Learn.resume.test.ts` unchanged).
- `frontend/src/components/screens/Learn.tsx`: `Learn()` branches on `useLoopStatus`; `LoopLearn` sits in the same Suspense boundary as `LearnInner`. Nothing below `Learn()` changed.
- `frontend/src/components/learn/DueQueue.tsx`: `getReviewSummary` read once on mount (failures ignored), `review-budget-paused`, new `review-empty` copy, a failed reload clears the item, `review-next` also while paused.
- `frontend/eslint.config.mjs`: `LoopLearn.tsx`, `BudgetPausedBanner.tsx` added to the testid `files` array (`DueQueue.tsx` was already there from PKG-12).
- `docs/frontend-testids.md`: `Learning loop | loop` table row, the `### loop` inventory, the `### review` owner line + `review-budget-paused`.
- Testids added — `loop`: `loop-phase`, `loop-session-picker`, `loop-session-{sessionId}`, `loop-new-session`, `loop-sessions-error`, `loop-sessions-retry`, `loop-no-course`, `loop-readonly-transcript`, `loop-readonly-new-session`, `loop-budget-paused`, `loop-budget-study-link`, `loop-no-check-items`, `loop-tree-link`, `loop-rail`, `loop-learner-state`, `loop-probe-item`, `loop-probe-input`, `loop-probe-option-{letter}`, `loop-probe-reason`, `loop-probe-submit`, `loop-probe-idk`, `loop-probe-reference`, `loop-probe-next`, `loop-plan-concept-{nodeId}`, `loop-plan-approve`, `loop-messages`, `loop-teach-start`, `loop-check-me`, `loop-check-prompt`, `loop-attempt-input`, `loop-attempt-option-{letter}`, `loop-attempt-reason`, `loop-attempt-submit`, `loop-attempt-idk`, `loop-hint-button`, `loop-hint-denied`, `loop-hint-reply`, `loop-hint-offer`, `loop-continue`, `loop-close-button`, `loop-close-summary`, `loop-close-self-eval`, `loop-close-if-then`, `loop-close-done`. `review`: `review-budget-paused`.
- Tests: `src/lib/api.loop.test.ts` (27), `src/components/learn/loopState.test.ts` (16), `src/components/learn/LoopLearn.test.tsx` (38), `src/components/learn/LearnBranch.test.tsx` (3), `src/components/learn/DueQueue.test.tsx` (+7 in a new `describe`; the file's `@/lib/api` mock now spreads the real module and adds `getReviewSummary`).

### Backend routes and fields this lane depends on

| route | request | fields read |
|---|---|---|
| `GET /review/active` (PKG-12, via `getLoopStatus`) | `user_id` | 200 → active, 404 → inactive |
| `GET /sessions` (**backend lane, Task 4**) | `user_id`, `course_id` | `sessions[{session_id, topic, started_at, phase}]` newest first |
| `GET /api/learn/sessions/{id}/resume` (legacy) | — | `session.topic`, `messages[{id, role, content}]` |
| `GET /api/graph/{uid}/courses`, `GET /api/graph/{uid}` (legacy) | — | first enrolled `course_id`, `course_name`, `course_code`; graph nodes/edges for the rail |
| `POST /start-session` | `{user_id, topic, course_id}` | `session_id`, `initial_message`, `budget{level, reset_at, session_capped}` |
| `POST /probe/next` | `{session_id, user_id}` | `done, phase, no_check_items` / `question_hash, node_id, format, prompt, options` |
| `POST /probe/answer` | `{session_id, user_id, question_hash, answer \| (option, reason) \| idk}` | `graded, probe_done, reference_answer`; `graded:false` + `unavailable` / `refused` / `recorded:false` |
| `GET /plan` | `session_id`, `user_id` | `concepts[{node_id, concept_name, kind}]`, `empty`, `phase` |
| `POST /plan/approve` | `{session_id, user_id, concept_ids}` | `phase` |
| `POST /chat/stream` | `{session_id, user_id, message}` | SSE `token, retract, phase, check, hint_offer, learner_state, budget, error, done{reply, leak_redacted, phase, check, budget}` |
| `POST /check/answer/stream` | `{session_id, user_id, question_hash, answer \| (option, reason), idk}` | as `/chat/stream` + `done.graded / unavailable / refused` |
| `POST /check/next` | `{session_id, user_id}` | `phase, check{question_hash, format, difficulty, prompt, options} \| null, plan_done` |
| `POST /step/attempt` | `{session_id, user_id, question_hash, attempt_text}` | `counted` |
| `POST /hint` | `{session_id, user_id, question_hash}` | `denied` \| `rung, intent` |
| `POST /action` | `{session_id, user_id, action_type: "hint"}` | `reply, phase, budget` |
| `POST /close` | `{session_id, user_id}` | `close{summary, self_eval, if_then, concepts[{node_id, p_before, p_after}]}`; 409 `detail` |
| `GET /review/next`, `POST /review/answer`, `GET /review/summary` (PKG-12) | unchanged | + `summary.paused`, `summary.due` |
| any 429 | — | `detail == "ai budget reached"`, `reset_at`, `session_capped` |

`GET /sessions` does not exist on this branch: the client and `LoopLearn` are coded against the Task 4 contract, which the backend lane's HANDOFF-13.md confirms verbatim (`{"sessions": [{session_id, topic, started_at, phase}]}`, `phase ∈ probe|plan|teach|check|feedback`, 404 when the gate is off, `{"sessions": []}` when not enrolled, never 429). Until the lanes merge, every loop student's `/learn` shows the `loop-sessions-error` retry state (the 404 of an unknown path is not the gate's 404, and the screen never falls through to a probe).

### Constants chosen

- `RAIL_WIDTH = 300` †, `RAIL_GRAPH_HEIGHT = 240` † (`LoopLearn.tsx`; the legacy rail is 280 high inside a wider column).
- `CONTINUE_MESSAGE = "Let's continue."` † — what "Continue" sends as the next chat turn after feedback.
- Copy (not tunables): `NO_CHECK_ITEMS_COPY`, `PLAN_DONE_COPY` (both verbatim from the prompt), `NO_ITEM_COPY`, `PROBE_UNAVAILABLE_COPY` (verbatim), `PROBE_REFUSED_COPY`, `HINT_DENIED_COPY` (one line per `/hint` denial reason), `CLOSE_RETRY_COPY` (the two A60 409 details), `tutorPauseMessage` (A39: "Tutor chat paused for this session. Practice and review keep working." when `session_capped`, else "Tutor chat paused until <local time>. Practice and review keep working."; "… paused for now. …" when `reset_at` is null), DueQueue's `answerPauseMessage` / `pausedConceptsMessage` (the prompt's copy).
- No timers: no client-side gate timer, no banner timeout (the pause clears on the next successful tutor turn or a reload).

### Deviations from spec

- `nextLoopProbe(sessionId, userId)`, `getLoopPlan(sessionId, userId)` take no `courseId` → `ProbeNextBody` / `GET /plan` carry no course (the session's course is `_session_scope`'s; HANDOFF-08). The prompt's vitest assertions `nextLoopProbe` `toHaveBeenCalledWith("s2", "u1", "c1")` became `("s2", "u1")`.
- `answerLoopProbe` sends `option` (not `selected_option`) → `ProbeAnswerBody` reuses PKG-07's `LoopCheckAnswerBody` field names (HANDOFF-08).
- `postLoopAttempt` sends `attempt_text` (not `text`) → `LoopAttemptBody`.
- Hint: `/hint` returns `{denied}` or `{rung, intent}` (not `{allowed, reason, reply}`); the hint TEXT is a follow-up `POST /action {action_type: "hint"}` JSON turn (`requestLoopHintTurn`) → PKG-07's design (HANDOFF-07 Open question (e)).
- `/step/attempt` is posted when the student asks for a hint, with the current draft, and again only if the server did not count that exact text — not on the first keystroke † → PKG-07's `/step/attempt` judges the TEXT (`is_genuine_attempt`: length + independent time + non-attempt phrases) and counts at most one attempt per rung anchor and one per distinct digest (M1). A one-character first-keystroke post would never be genuine and, under the prompt's once-per-`question_hash` ref, the student's real attempt would never be recorded, so `no_genuine_attempt` would deny every hint. Task 9's hint poll must type an attempt into `loop-attempt-input` before clicking `loop-hint-button`.
- `/close` takes no answers and returns the A60 record → `loop-close-self-eval` is the reflection prompt (no input), `loop-close-if-then` the stored plan (rendered only when non-empty), and `loop-close-submit` does not exist; `loop-close-done` renders with the record (A60 amendment).
- A resumed session in `check` restores its pose with `POST /check/next` (idempotent while the item is being answered: PKG-07 returns the open item with no write and no model call) → the pose is not in `/sessions` or the transcript as structured data. It is the one call made on resume; `probe` resumes with `/probe/next`, `plan` with `GET /plan`, `teach`/`feedback` send nothing.
- After `/plan/approve` no turn runs (HANDOFF-08 / backend lane: "the first teach turn is the client's next /chat/stream") → LoopLearn sends none on its own; `loop-teach-start` ("Start with <first plan concept>") sends `Teach me about <name>.` as a student-initiated first turn †, and "Check me" works at once.
- The last probe answer (`probe_done: true`) goes straight to `GET /plan` (after the reference answer's "Next", when there is one) → the server already moved the session to `plan`, so another `/probe/next` would 409 `"phase is plan"`. `loop-probe-next` added for the reference card.
- A turn's `phase` event of `hint` (a hint turn during the check) is shown as `check` (`uiPhaseOf`) → `data-phase` stays in the six UI phases.
- The `check` stream event carries only `{question_hash, format, difficulty}`; the reducer keeps the pose it already has for that hash, and the full pose comes from `done.check` / `/check/next` (HANDOFF-07). The pose names no node, so `loop-learner-state` and `loop-tree-link` follow the LAST `learner_state` event's `node_id` (`focusNodeId`), not `item.node_id`.
- A pose that a teach turn or "Check me" activated is also appended to the chat log as an assistant message (the server saves it as an assistant row, so a reload shows the same log).
- `budgetPauseOf` returns `{resetAt, sessionCapped}` (the prompt's `{resetAt}` + A39). The reducer's `reset` keeps a daily pause across a session switch and drops a session-capped one.
- `getLoopStatus` stays where PKG-12 put it (it already returns `{active: false}` on 404 and probes `/review/active`, since `/status` needs a `session_id`); the new loop block sits after it. `StreamEvent.type` was already `string`, so no union changed.
- `readResumeParam` moved to `components/learn/resumeParam.ts` (re-exported from `screens/Learn.tsx`) → LoopLearn reads the same deep link without a `Learn.tsx` ↔ `LoopLearn.tsx` import cycle. The file is outside the prompt's Files list but inside `frontend/src/components/learn/*` (acceptance 12).
- `LoopLearn` is wrapped in the same `Suspense` boundary as `LearnInner` (`useSearchParams`); the prompt's `Learn()` rendered it bare.
- Course: the first enrolled course, with a `CustomSelect` course switcher when the student has more than one †. No enrolled course → `loop-no-course` (new testid).
- DueQueue 429 copy: "AI tutor paused until <time>. Flashcards and review keep working." (the prompt's Task 7 copy); `review-next` also renders while paused (the prompt's test: "Next still re-polls") — a re-poll may re-serve the same open check item (A70).
- DueQueue.test.tsx's `@/lib/api` mock now spreads the real module and mocks `getReviewSummary` too (every pre-existing test unchanged in body).
- Lint: `DueQueue.tsx` carried three `react/no-unescaped-entities` ERRORS from PKG-12 (`npm run lint` exited 1 on the base); fixed in Task 7's copy change. No suppressed code was deleted, so `eslint-suppressions.json` is untouched.

### Known gaps

- `GET /sessions` lands with the backend lane; this branch alone shows the retry state for loop students (above).
- No Playwright journey, no E2E run (Task 9, after the merge). The component is proven by jsdom tests with every loop client mocked.
- The novice hint offer rides the feedback turn, after the item closed (HANDOFF-07 Known gaps), so `loop-hint-offer` renders only while an item is current (inside the check card) and is usually not seen in the loop as built.
- A hint's text is a JSON `/action` turn (not streamed); it is appended to the log when it returns.
- "Continue" persists `Let's continue.` as a student row; a nicer "next step" affordance needs a server route (none exists).
- The self-evaluation is not answerable (A60); the if-then plan is display-only.
- A student who clicks "New session" before the first `/sessions` answer lands starts that session (the explicit click wins over the boot's resume).
- The rail refreshes the graph on mount, after each graded submission and after the close — not on every `graph_update` event.
- `next build` passed in this worktree (hardlinked `node_modules`, `NEXT_PUBLIC_API_URL= BACKEND_URL=http://localhost:5000 npx next build`, exit 0); the Task 9 E2E cycle is still the build gate for the merged tree.

### Verify commands (frontend lane)

```
cd frontend && npx tsc --noEmit                                         → clean
cd frontend && npm run lint                                             → 0 errors (22 pre-existing warnings; base: 3 errors, 22 warnings)
cd frontend && npm test                                                 → 111 files, 1219 passed, 2 skipped (base: 107 files, 1128 passed, 2 skipped)
cd frontend && npx vitest run src/components/learn src/lib/api.loop.test.ts src/lib/api.stream.test.ts → all passed
grep -cE "ModelToggle|useModelPref|model_pref" frontend/src/components/learn/LoopLearn.tsx → 0
```

### Open questions for the series owner

- Should `/step/attempt` get an explicit client trigger other than "Hint" (e.g. on blur of a non-empty draft), so time-to-first-attempt is recorded without a hint request?
- Should the plan screen show the band (the response carries `p_known` but no `band`; the UI never computes one from a literal)?
- Should the hint text stream (`/action` has no SSE twin)?
