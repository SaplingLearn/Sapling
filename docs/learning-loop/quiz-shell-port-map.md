# Quiz shell port map (W7 kickoff)

**Status:** kickoff map (not a full reskin)  
**Branch:** `feat/learning-loop-reland`  
**Design source:** `~/Downloads/Design system audit and implementation (1)/` — `HANDOFF.md`, `notes/repo-findings.md`  
**Plan:** `docs/learning-loop/alvar-trilogy-implementation-plan.md` § W7  

Goal: map handoff artifacts → production files, name the **first slice (W7.1–W7.3)**, and pin the existing `GET /api/quiz/plan` client so launcher work reuses it instead of inventing a second plan path.

---

## 1. Handoff artifact → production

| Handoff artifact | Spec steps | Production target(s) | Notes |
|---|---|---|---|
| `Quiz Component Library.dc.html` | 1 | `frontend/src/components/quiz/quiz.css` + shared `components/ui/*` (`AnswerOption`, `ProgressDots`, `Chip`, …) + `components/graph/ConceptNode.tsx` / `lib/graph/nodeStyle.ts` | Tokens already live in `app/globals.css`. Empty states → `home/HomeStates.tsx`. Mastery blobs → existing `ConceptNode`, not plant-stage strings. |
| `Quiz Shell.dc.html` | 2–3 | `QuizScreen.tsx`, `question/QuizQuestion.tsx`, `question/question.css`, `question/LeaveDialog.tsx`, `question/AskPanel.tsx` | **Shipped:** attempt phases use `SessionTop` + `data-quiz-session` (SideNav hidden). Home / results / error keep app `TopBar` + Study back link (W7.D1). Hint / Skip / Study guide / prereq banner live; Returning + exam-distance pips live ([`w7-meta-chips.md`](./w7-meta-chips.md)); wager still deferred. |
| `Quiz Components 7.1–7.18*.dc.html` + `quiz-kit.js` / `quiz-data-*.js` | 4–5 | `question/*Answer.tsx` + `lib/quiz/*Interaction.ts` (Sort…Connect match/map) + core MC/written | Kit stubs on `short_answer` wire; generation does not emit `interaction` yet. Demo prompts remain **UI fixtures only**. |
| `Quiz Session.dc.html` | 6–7 | `QuizScreen.tsx` phases + `home/` start path + `results/QuizResults.tsx` (+ `LearningBlock.tsx`) | Practice / Exam Twin start, leave, generating skeleton, summary. Generating already exists as a question phase. |
| Study Hub / Guide / Settings recreations | 8–9 | `components/study/**`, `components/studyGuide/**`, `components/screens/Settings.tsx` | Port on **copies** of design files; production edits go to these React trees. Hub Quiz button → launcher (W7.9). |
| Launcher (not built in handoff) | 10 | Evolve `home/QuizHome.tsx` (+ Map = `KnowledgeGraph2D` / `ConceptNode`, same as Tree) | Concept list + Map. Reuse plan ranking, do not fork. |
| `sapling-graph.js` | — | `lib/graph/blobShape.ts`, `ConceptNode`, `KnowledgeGraph2D` | Already ported in-app; do not re-import the DC script. |
| Clickable prototype (17.3) | 17.3 | Playwright journeys under `frontend/e2e/` | Optional; E2E supersedes DC links. |

Shared primitives (handoff “ui/” under quiz): live in `frontend/src/components/ui/`, not `components/quiz/ui/`.

---

## 2. First slice — W7.1–W7.3 (what the first PR owns)

### W7.1 — Shell chrome (visual only; no new mastery writer)

| Shell frame concern | Port into | Anchor today |
|---|---|---|
| Full-screen focus session (no SideNav) | `QuizScreen.tsx` when `QUESTION_PHASES` | **done** — `SessionTop` + `data-quiz-session`; home/results keep TopBar |
| 64px session top: X / course+topic / “Question N of M” + bar / XP+streak / `?` | `QuizQuestion.tsx` `SessionTop` | Progress + leave done; XP/streak stay off session top (W7.D1) |
| Meta row: concept pill (blob) + skill chip + exam-distance pips + source + “Returning” | `QuizQuestion.tsx` + concept summary from `QuizScreen` | Concept pill + tier + Returning + exam-distance done ([`w7-meta-chips.md`](./w7-meta-chips.md)); Bloom skill chip still deferred (no field) |
| Action bar: Hint / Study guide \| wager \| Skip / Check | `QuizQuestion.tsx` | Hint / Study guide / Skip / Check **done**; wager deferred |
| Feedback / verdict panel tones | `question.css` + `components/ui/AnswerOption.tsx` | Correct/incorrect states exist; partial/hint/info tones from handoff |
| Accent = brand forest vs `--quiz-accent` course tint | `QuizScreen.tsx` `rootStyle` | Confirm with product before flipping (plan W7 open question) |

**Out of W7.1:** interactive question types (7.2+), hub/guide/settings, launcher Map.

### W7.2 — Question kit (phased)

| Phase | Types | Status |
|---|---|---|
| Core | MC / short / numeric / algebra on SessionTop | **done** |
| Interactive stubs | Sort…Rank + Connect match + concept-map | **twelve stubs + Connect map mode done** |
| Later | Generation emits `interaction`; richer per-criterion grading | deferred |

Stubs use `short_answer` wire + client `interaction`; generation does not emit kit payloads yet. Do not block shell chrome on full 7.1–7.18 parity.

### W7.3 — Plan API hook points (already exist — extend, don’t duplicate)

| Concern | Exact function / file | Behavior |
|---|---|---|
| HTTP client | `getQuizPlan(userId, courseId?)` in `frontend/src/lib/quiz/api.ts` | `GET /api/quiz/plan?user_id=&course_id=` |
| Flag gate | `useQuizPlanFlag()` in `lib/quiz/useQuizHome.ts` | `quiz_concept_plan` **and** `learning_loop` both `"on"` |
| Bootstrap | `useQuizHome` → `Promise.all` plan reads (~L310–319) | All-courses plan + optional `?course=` plan; failure → tier ranking |
| Rank / due | `rankFromPlan`, `dueFromPlan`, `plannedCourseQueue` in `lib/quiz/proposals.ts` | Plan order = FSRS due → misconceptions → ready fringe |
| Home UI | `QuizHome.tsx` / `ProposalCard` / `TopicsColumn` via `home.planned`, `planOf` | Card + topics already plan-aware when flag on |
| Types | `QuizPlan` / plan concept shape in `lib/quiz/types.ts` | Mirror backend `learning/quiz_plan.py` |
| Tests | `useQuizHome.plan.test.ts`, `api.test.ts`, `proposals.plan.test.ts` | Flag-off = pre-loop ranking |
| Start / Adjust | `useQuizSession` + `home/useHomeCard.ts` / `AdjustDialog` | First PR: ensure Start/Adjust pass **planned concept ids** when `home.planned`; generation flags (`quiz_planned_questions`, gates) stay server-side |

**Launcher (step 10) rule:** read the same `useQuizHome` / `getQuizPlan` path (or extract a thin `useQuizPlan` that both Home and Launcher call). Never a second ranking.

---

## 3. Suggested production files for the first W7 PR

Touch list (chrome + plan continuity; no full UI rewrite):

1. `frontend/src/components/quiz/QuizScreen.tsx` — session vs home layout; keep plan-fed home
2. `frontend/src/components/quiz/question/QuizQuestion.tsx` — session chrome / action bar hooks
3. `frontend/src/components/quiz/question/question.css` (+ maybe `quiz.css`) — shell tokens
4. `frontend/src/components/quiz/home/QuizHome.tsx` — launcher entry / plan-aware copy only if needed
5. `frontend/src/lib/quiz/useQuizHome.ts` — **read-only reuse** of plan bootstrap (extract only if launcher needs it)
6. `frontend/src/lib/quiz/api.ts` — `getQuizPlan` (unchanged unless query params grow)
7. `frontend/src/lib/quiz/types.ts` — shell/session mode types **only if** Practice vs Exam Twin lands in the same PR (else defer)

Optional later in the same epic: `results/QuizResults.tsx`, `results/LearningBlock.tsx`, `study/HubHeader.tsx`, study-guide reader callouts, Settings Quiz section.

---

## 4. Hard wiring rules (from plan W7)

1. Kit demo prompts ≠ production items.  
2. Mastery from `graph_nodes` / submit deltas only.  
3. “Returning” / exam-distance pips — **done** ([`w7-meta-chips.md`](./w7-meta-chips.md); `lib/quiz/metaChips.ts`).  
4. Keep Ask-tutor (`AskPanel` / `quiz-ask` origin).  
5. Empty library → honest empty state (`HomeStates`), not fake concepts.

---

## 5. Open questions (HANDOFF §4E) — resolved in W7.D1

Full table: [`w7-design-decisions.md`](./w7-design-decisions.md). Summary for W7.1:

1. **PR #866 branch** — `feat/learning-loop-reland` (PR [#866](https://github.com/SaplingLearn/Sapling/pull/866)).
2. **MATH 151 concept list** — **deferred** to W7.D3 / seed-catalog; honest empty states only in production.
3. **Question container** — **open** (no Practice question card); `.card` for feedback/hint/drawers.
4. **Definitive / Mixed / Conceptual selector** — **stay omitted** (≠ Settings answer Format Mixed).
5. **Accent** — chrome = brand forest; `--quiz-accent` = course identity only.
6. **XP / streak in session top bar** — **drop**; keep on results / summary only.

---

## 6. Design debt parallel track (W7.D*)

| ID | Work | Blocks code? |
|---|---|---|
| W7.D1 | Decisions doc landed; browser-verify unchecked pages (checklist in `w7-design-decisions.md`) | Soft — prefer before copying pixels |
| W7.D2 | Hub/Guide/Settings decisions: [`w7-d2-hub-guide-settings.md`](./w7-d2-hub-guide-settings.md); DC copies optional polish | Soft for W7.1; hard for W7.9 |
| W7.D3 | Launcher + Map: [`w7-d3-launcher-map.md`](./w7-d3-launcher-map.md) (no fake MATH 151) | Hard for Map/empty-course (W7.10) |
| W7.D4 | 17.3 clickable prototype | No — E2E preferred |
| W7.D5 | Ask / confidence / loop flags in shell (card vs open resolved → open) | Soft for chrome CSS; hard for W7.4–W7.5 |
