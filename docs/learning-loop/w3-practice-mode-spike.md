# W3.3 spike — Practice mode (Study cue stream)

**Status:** entry slice landed (W3.3b) — not full cue stream  
**Plan row:** Alvar trilogy W3.3 / claim **AP** (“Practice as distinct cue-demand stream”)  
**Branch context:** `feat/learning-loop-reland`  
**Date:** 2026-11-23  
**Siblings:** `w3-plan-dependency-spike.md` (W3.1), `w3-covered-vs-understood-spike.md` (W3.2) — do not conflate; this is **not** a second Learn teach.

---

## Verdict

| Question | Answer |
|---|---|
| Is there a Practice mode surface today? | **Entry only (W3.3b).** Hub Due Reviews + Learn wrap-up link into Quiz via `dueReviewsQuizHref` / `handoffPracticeDueHref`. No dedicated Practice shell or multi-due auto-start stream. |
| Can Study / wrap-up already reach due practice? | **Hub yes (W8.3b + W3.3b copy).** Due Reviews → “Practice what's due” → lead due id + `start=1`. **Wrap-up yes (W3.3b):** `loop-close-practice-link` → lead due id when `getStudyNext` returns due[], else `?course=&start=1`. Study link kept. |
| Safe trivial deep-link this spike? | **Entry done.** Full stream still needs `?start=1` + `scope=due` arming and multi-due UX if product wants one-click all-due. |
| Enough data for full W3.3 without schema? | **Mostly yes** for v1 routing on `learner_next` buckets + Quiz launcher params. Cue-dial / multi-concept item serve needs existing flags (`varied_isomorphs`, `multi_concept_items`), not new tables. |

**Bottom line:** Practice mode = **Quiz (and later retention/review) as the cue-demand stream**, fed by the same `learner_next` buckets Hub/Quiz already share — entered from Study Hub / wrap-up, **never** a parallel LoopLearn teach session. W3.3b lands the entry + Practice-vs-Teach copy; full cue stream remains follow-on.

**Code landed this spike / W3.3b:** see §7.

---

## 1. Existing entry points (do not fork ranking)

### Shared brain

| Layer | Path | Shape |
|---|---|---|
| Pure buckets | `backend/learning/learner_next.py` | `LearnerNext{due, misconceptions, ready}` → `ordered` = due → misc → ready |
| IO assemble | `backend/services/learner_next.py` | Loads states + prereq edges; `learner_next(user, course)` |
| Study route | `GET /api/study/{user_id}/next` → `services/study/next.py` | Same three buckets, uncapped |
| Quiz plan | `learning/quiz_plan.rank_concepts` → caps `learner_next` for home | Same order, per-course cap |
| Client type | `frontend/src/lib/studyApi.ts` `StudyNext` | `{ due, misconceptions, ready }` |

**Invariant (W8.6):** Hub Focus / Due Reviews and Quiz plan must not invent a second ranking. Practice mode reads these buckets (or Quiz’s capped plan), never a new heuristic.

### Study Hub (W8.3 / W8.3b — shipped; W3.3b copy)

| Surface | Behavior |
|---|---|
| Focus card “Start quiz” | Per-concept `buildQuizHref({ concept }, …, { start: true })` |
| Due Reviews → Flashcards | Primary CTA (`due-reviews-flashcards`) |
| Due Reviews → Practice | Secondary CTA (`due-reviews-quiz`) labeled **Practice what's due** via `dueReviewsQuizHref` → lead due id + `return=/study?course=…` + `start=1` |
| Gate | `learning_loop` **and** `quiz_concept_plan` (see `useStudyNext`); `hide_quiz` hides Practice |

Files: `StudyHub.tsx`, `QuickReviews.tsx`, `FocusCard.tsx`, `studyModel.ts` (`dueReviewsQuizHref`, `dueReviewsFromNext`, `examQueueFromNext`), `useHubView.ts`.

### Quiz launcher (existing deep links)

`frontend/src/lib/quiz/source.ts` — `buildQuizHref` / `parseEntry`:

| Param | Meaning |
|---|---|
| `concept=` | One node (Hub Due Quiz, Focus, Library) |
| `course=` | Course practice queue |
| `scope=due` | “Review everything due” card / queue (all courses’ FSRS-due set) |
| `start=1` | Auto-start **concept** or **course** card only — **not** `scope=due` (`QuizHome.tsx` armed effect) |
| `from` / `return` | Origin + safe same-origin path |

Generate API: `POST /api/quiz/generate` takes a **single** `concept_node_id` (plus optional `source_attempt_id` for G5). Queues of due ids are client-side sequential starts, not a multi-id body.

### Learn wrap-up / Tutor (W3.3b)

| Surface | Link |
|---|---|
| `ClosePanel` “Due on Study” (`loop-close-study-link`) | `/study?course=` (gated `hide_study`) |
| `ClosePanel` “Practice what's due” (`loop-close-practice-link`) | `handoffPracticeDueHref` / `dueReviewsQuizHref`-shaped: due lead when next loads, else `course`+`start=1`; gated Study **and** Quiz visible |
| `ClosePanel` “Quiz this concept” (`loop-close-quiz-link`) | Measured weak/first concept (W3.4); still `hide_quiz` |
| Retention CTA | `retentionHref([courseId])` when Study visible |

Copy source: `frontend/src/lib/learningHandoffs.ts` (`HANDOFF_COPY.practiceWhatsDue`).

### Not W3.3 (do not overload)

| Thing | Why it is different |
|---|---|
| LoopLearn teach / plan / checks | Installs knowledge; Practice solidifies cues (**O** / **AP**) |
| G5 missed re-practice (`services/quiz/practice.py`) | Re-serve questions from one finished attempt |
| Quiz gate verdict `practice` (A145) | Unverified item served, never evidence — item economy, not a mode |
| SessionMap “practiced” outline (W3.2) | Covered-vs-understood paint inside Learn |

---

## 2. Proposed UX (v1 Practice mode)

**One sentence:** From Study (or wrap-up), open the **Quiz cue stream** on due → misconceptions → ready (unfamiliar / fringe), with varied / multi-concept items when those flags are on — **no teach prose, no plan approve, no LoopLearn session.**

### Student-facing v1

1. **Entry label:** “Practice what's due”. Copy must say **practice / review**, never “continue learning” / teach.
2. **Primary entry:** Study Hub Due Reviews + Focus when reason is due/misc/ready.
3. **Wrap-up secondary (W3.3b landed):** when Quiz nav is visible (`!hide_quiz`) **and** Study visible, additive Practice link next to `/study` — course-scoped lead due id (same as W8.3b) or `?course=&start=1` if due empty; Study link kept (W3.4).
4. **Stream content (not yet):** sequential single-concept quizzes in `learner_next.ordered` order. Home “Review everything due” (`scope=due`) is the multi-due cousin; extend `?start=1` to arm due mode if product wants one-click multi-due.
5. **Cue demand:** prefer items/surfaces the student has not met when `varied_isomorphs` is on (`learning/surface.py`); serve a multi-concept item when `multi_concept_items` is on.
6. **Exit:** `return` back to Study Hub (or wrap-up `return=/study?course=`); results next-step can point Learn only for **ready/fringe teach**, never auto-open a teach session from Practice entry.

### What the student should feel

| Practice mode | Learn teach |
|---|---|
| Retrieval / cue demand | Explanation + worked path |
| Short Quiz rounds | Session with plan + SessionMap |
| Due & weak first | Approved plan cursor |
| Mastery from graded quiz evidence (existing gates) | Mastery from measured loop checks |

---

## 3. Flags

| Flag | Role for W3.3 |
|---|---|
| `learning_loop` | Master gate; without it no Study next / loop semantics |
| `quiz_concept_plan` | Hub next + Quiz plan from FSRS/misc/ready (required with loop for Hub buckets) |
| `hide_study` | Hides Hub / wrap-up Study + Practice CTAs (Practice returns to Study) |
| `hide_quiz` | Hides Quiz — wrap-up/Hub→Practice must respect this |
| `varied_isomorphs` | Unfamiliar surfaces / isomorphs in the stream |
| `multi_concept_items` | Multi-concept items when open |
| `quiz_results_routing` | Results “what’s due / next” after a practice round |

**Do not add** a `practice_mode` flag for v1 unless product wants a kill switch separate from `quiz_concept_plan`. Prefer composing the flags above.

---

## 4. E2E / testids

### Existing (reuse) + W3.3b

| testid / journey | Use |
|---|---|
| `due-reviews-quiz` / `due-reviews-flashcards` | Hub; label “Practice what's due” |
| `focus-card` | Focus → quiz |
| `quiz-home` | Launcher |
| `loop-close-study-link` | Wrap-up → Study (keep) |
| `loop-close-practice-link` | Wrap-up → Practice (W3.3b); absent under `hide_quiz` / `hide_study` |
| `StudyHub.test.tsx` / `learningHandoffs.test.ts` | Lead-id href + course fallback + hide_* |

### Still for full W3.3

| Item | Notes |
|---|---|
| `?start=1` arms `scope=due` | QuizHome gap |
| Playwright journey | Hub / wrap-up → Quiz due lead |
| Docs | `docs/frontend-testids.md` — `loop-close-practice-link` registered |

---

## 5. Effort estimate (full W3.3 remainder)

| Slice | Size | Notes |
|---|---|---|
| ~~Copy / framing on Hub Due + wrap-up Practice~~ | ~~XS–S~~ | **W3.3b done** |
| ~~Wrap-up → Quiz practice CTA + `hide_quiz`~~ | ~~S~~ | **W3.3b done** |
| `?start=1` arms `scope=due` | S | QuizHome armed effect gap |
| Multi-due queue UX (explicit Practice stream shell) | M | Optional |
| Wire varied / multi-concept into Quiz serve path if missing | M–L | Verify, don’t fork |
| E2E + oracles | S–M | |

---

## 6. Non-goals

- **Not a second Learn teach** — no LoopLearn session, plan approve, teach prose, SessionMap rail, or generative-core beat inside Practice mode.  
- **Not replacing** Learn close / retention / Flashcards Due Reviews.  
- **Not** a new mastery writer — Quiz submit / existing gates only.  
- **Not** inventing `concept_ids[]` on generate for v1.  
- **Not** SessionMap dual encoding (W3.2) or plan DAG (W3.1).  
- **Not** Anthropic / new LLM slots for this spike or v1 routing.

---

## 7. Code landed (spike docs + W3.3b entry)

| Change | File |
|---|---|
| Spike doc | `docs/learning-loop/w3-practice-mode-spike.md` |
| Practice copy + wrap-up CTAs | `frontend/src/lib/learningHandoffs.ts` (`practiceWhatsDue`, `handoffPracticeDueHref`, `closeHandoffCtas`) |
| Due href empty → course+start | `frontend/src/components/study/studyModel.ts` (`dueReviewsQuizHref` opts) |
| Hub Due label | `frontend/src/components/study/QuickReviews.tsx` |
| Wrap-up due fetch + Practice link | `frontend/src/components/learn/ClosePanel.tsx` |
| Unit tests | `learningHandoffs.test.ts`, `studyModel.test.ts`, `StudyHub.test.tsx`, `LoopLearn.test.tsx`, `LoopLearn.tutorV2.test.tsx` |

**Still out of this slice:** `scope=due&start=1` auto-start, multi-due Practice shell, E2E journey.

---

## 8. Pointers

- Plan: `docs/learning-loop/alvar-trilogy-implementation-plan.md` (W3.3, W8.3b, W8.6)  
- Handoffs: `docs/learning-loop/w3-handoffs.md`  
- Flags: `docs/learning-loop/flag-rollout.md` (`quiz_concept_plan`, varied / multi-concept)  
- Audit: `docs/learning-loop/day2-plan-compliance-audit.md` (Hub Due Quiz PASS slice; E2E gap)  
