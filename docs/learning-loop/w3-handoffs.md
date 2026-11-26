# W3.4 — Learn ↔ Study ↔ Quiz handoffs

**Status:** landed (copy + deep links; W3.3b Practice entry on wrap-up / Hub)  
**Branch:** `feat/learning-loop-reland`  
**Plan:** [alvar-trilogy-implementation-plan.md](alvar-trilogy-implementation-plan.md) W3.4 / W8.5 / W3.3b

One learner model already ranks due / misconceptions / ready (`learner_next`).
This workstream makes the **exits** between Tutor, Study, and Quiz read as one
interface: the same labels, the same deep-link builders, and no link to a page
a `hide_*` flag has removed.

## Copy (stable)

| Intent | Label | Typical href |
|---|---|---|
| Due reviews | **Due on Study** | `studyHref(courseId)` → `/study?course=` |
| Practice (cue stream) | **Practice what's due** | `handoffPracticeDueHref` → lead due / course+`start=1` |
| Continue teaching | **Continue in Tutor** / **Continue learning: {name}** | `handoffLearnHref` → `/learn?topic=&concept=&mode=socratic&course=` |
| Quiz a concept | **Quiz this concept** | `buildQuizHref({ concept }, …, { start: true })` |
| Knowledge map | **See on your map** | `/tree?node=` or `/tree?course=` |

Source of truth: `frontend/src/lib/learningHandoffs.ts` (`HANDOFF_COPY` + CTA helpers).

## Surfaces

| Surface | CTAs added / aligned | hide_* |
|---|---|---|
| Tutor wrap-up (`ClosePanel`) | Due on Study; Practice what's due; Quiz this concept (down / first measured); See on your map; retention unchanged | `hide_study` / `hide_quiz` / `hide_tree` |
| Study Hub Due Reviews | Practice what's due (`due-reviews-quiz`) beside Flashcards | `hide_quiz` + loop/plan flags |
| LoopNotices (budget) | Review flashcards → course-scoped Study | `hide_study` |
| LoopNotices (practice unavailable) | Due on Study; Quiz this concept (first unavailable id) | `hide_study` / `hide_quiz` |
| Tutor home / SessionPanel | Due on Study; See on your map | `hide_study` / `hide_tree` |
| Study Hub Focus | Continue in Tutor (beside Start quiz / cards) | `hide_tutor` / `hide_quiz` |
| Quiz results (`LearningBlock`) | Due on Study (N); Continue learning: {name}; See on your map | `hide_study` / `hide_tutor` / `hide_tree` + loop probe for review |
| Retention empty / finished | Due on Study; Continue in Tutor | `hide_study` / `hide_tutor` |
| Study Guide concept map | Quiz this concept (already W7.D2) | `hide_quiz` |

## Non-goals

- **Full Practice cue stream** — no `scope=due&start=1` arming, no multi-due
  shell, no second Learn teach session (entry is W3.3b only).
- No new Anthropic / LLM slots.
- No layout redesign — additive links in existing flex rows.

## Tests

- `frontend/src/lib/learningHandoffs.test.ts` — copy, hrefs, hide_* filtering.
- Existing surface tests updated for labels / course-scoped Study
  (`LearningBlock.test.tsx`, `LoopLearn*.test.tsx`, `StudyHub.test.tsx`).
