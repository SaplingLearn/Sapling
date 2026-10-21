# Unified assessment study guide

## Student flow

Open **Study → Study Plans** (`/study?mode=plan`) and choose a course. The feature
also remains available from **Knowledge map → course → Study plan**. The UI uses
PR #728's cream/sage surface and shared heading and typography.
For retaken courses, select the intended semester. Choose **New assessment** or
**Create a study plan**, enter a quiz/exam name and date, then describe its
coverage and/or select assignments and library documents from that enrollment.
Choose study days, a start date, and daily available minutes. Dates use the
browser's IANA timezone, stored with the plan.

Neither an existing assignment nor a date extracted from a document is required.
Enter the assessment date manually; an optional existing quiz/exam selector can
prefill it when available. Undated quizzes/exams remain selectable and say
**Add date manually**. Documents and related assignments stay selectable without
dates. The Library document detail links to a new plan with its material
preselected. Earlier saved guides remain available as read-only history in the same workspace;
there is no second assessment-creation or regeneration flow.

Generation suggests academic topics from those selected sources only, using the
bounded, metered assessment-guide agent through the existing checklist budget
and usage-receipt pipeline. One generation returns an overview, topics and
grounded study points; scheduling does not make another model call. The full course catalog is not
treated as assessment coverage. Generic exam titles may produce no topics;
describe the coverage or attach substantive materials in that case. Source text
is capped at 10,000 characters each and 60,000 serialized characters overall;
shortening is surfaced as a warning. Documents must belong to the student and
selected offering; assignments must belong to the selected enrollment.

The resulting page contains an assessment overview, daily schedule and expandable
topic groups with concise study points and source references.
Topic indicators reflect live course graph mastery using the current shared
`learning.bkt.in_mastered_tier` rule. Name matching is normalized and exact; generated topics reuse tracked
concept names where possible. An unmatched topic remains unassessed, rather than
receiving an invented score. This is concept progress, not an exam-readiness score.
Mastery is cumulative across the abstract course, as in the knowledge map.

Session checkboxes record study activity only. They never update graph mastery.
Plan topics, including added topics, can be edited or removed. Saving topic edits
rebuilds unfinished sessions and retains completed sessions for retained topics.
Renaming a topic can change its graph match. Material selection/coverage is fixed
after creation; create a new assessment plan for different source coverage.

## Scheduling

Scheduling is deterministic, without another model call. It prioritizes weak and
important concepts, visits prerequisites before dependents, allocates first
coverage before repeat review, and reviews already mastered topics. Sessions use
25-minute estimates (or the daily limit if smaller). Review repeats occur on a
later study day at least two days after initial study, when capacity permits.
Schedules exclude the assessment day and respect selected weekdays and daily
time budgets. Unscheduled first-coverage topics generate an explicit warning.

Students can move sessions, finish them, change dates/availability, or choose
**Replan unfinished work** after missing days. Replanning retains completed
sessions without repeating completed initial study. Moving a session is validated
against current dates, available weekdays and capacity. Explicit moves are user
choices and may override the originally generated prerequisite/review ordering.
Plans for different assessments are independent; cross-assessment workload
balancing, detailed worked study notes, practice-question generation and calendar
integration are outside this release.

**Refresh progress** reads the latest mastery without regenerating topics or
changing dates. Reopening the panel or returning to its browser tab also refreshes.
No background process is required.

## API

All paths below are relative to
`/api/topic-checklist/{user_id}/courses/{course_id}` and accept optional `semester`.
Every endpoint checks the session user and owned enrollment.

| Method | Path | Result |
| --- | --- | --- |
| GET | `/plans/sources` | Owned document and assignment metadata |
| GET | `/plans` | Persisted plans with live mastery |
| POST | `/plans` | Generate guide/topics and persist an encrypted schedule (201) |
| PATCH | `/plans/{uuid}` | Edit title/topics/timing, move/complete a session, or replan |
| DELETE | `/plans/{uuid}` | Delete one owned plan |

POST body example:

```json
{
  "title": "Biology midterm",
  "assessment_type": "exam",
  "start_date": "2026-10-22",
  "assessment_date": "2026-10-30",
  "timezone": "America/New_York",
  "coverage": "Cell structure and membranes",
  "document_ids": [],
  "assignment_ids": [],
  "study_days": [0, 1, 2, 3, 4],
  "minutes_per_day": 60
}
```

PATCH always includes the last saved integer `version`. A stale or raced update
returns 409 without overwriting newer work. Other fields: `title`, `topics`
(editable fields only, excluding computed mastery/status), `settings` (the POST
shape, retaining original source selection/coverage), `regenerate: true`, or
`session: {"id": "session-uuid", "scheduled_date": "2026-10-25", "completed": true}`.
Session edits cannot be combined with schedule rebuilds in the same request.
Invalid hierarchy, prerequisites, source IDs, dates and unavailable materials are
rejected. Generation permits six requests per user per minute per backend process
and uses the existing 60-second agent timeout. Generation shares the current
checklist admission, AI-budget checks and durable usage-receipt reconciliation,
without replacing the course checklist cache with assessment-specific topics.
Failure leaves saved plans intact.

Existing guide history is read through `GET /api/study-guide/{user_id}/saved/{guide_id}`.
It checks ownership, reads the saved encrypted content, and never generates or writes.
The new guide overview and study points are stored inside the existing encrypted
assessment-plan payload; no additional schema change is needed for unification.

## Deployment

When running against a hosted database, a local frontend/backend still writes to
that hosted project. Do not use the live project to trial a branch's migrations.
The October 21 read-only check found 34 pending migrations on the configured live
project, including the FSRS flashcard fields, learner state, check items and this
feature's table. These explain flashcard/review errors; Docker is unrelated.
Use a separate development/staging Supabase project and its environment settings
to apply and test the pending schema. No hosted migration was applied here.

Missing tables/columns/functions now produce a safe 503 with migration guidance.
The Study view displays the error and offers retry, rather than reporting an
empty library of flashcards. The sidebar's remembered collapse is restored in a
layout effect; it no longer renders an inert inline script during client mounts.

Apply `20261021214512_assessment_study_plans.sql` through the existing migration
runner before deploying the backend. Use the normal staging/promotion workflow;
do not apply DDL directly to production. The additive table has enrollment-delete
cascade, RLS, service-role-only grants and encrypted content. Existing
`ENCRYPTION_KEY` and topic-checklist model configuration are reused; no new
environment variables are required. Existing course checklist data is preserved.

## Verification

From `backend/`:

```powershell
.\venv\Scripts\python.exe -X utf8 -m pytest tests/test_study_plan.py tests/test_study_plan_budget.py tests/test_checklist_budget.py tests/test_topic_checklist_routes.py tests/test_topic_checklist.py -q
.\venv\Scripts\python.exe -m ruff check services/study_plan_service.py routes/topic_checklist.py tests/test_study_plan.py tests/test_topic_checklist_routes.py
```

From `frontend/`:

```powershell
npm exec vitest run src/components/StudyPlanPanel.test.tsx src/lib/studyPlanApi.test.ts
npm run typecheck
npm run lint
npm run build
```

The opt-in real-storage test is `backend/tests/integration/test_study_plan.py`.
Run it with `RUN_INTEGRATION=1` only against the disposable local Supabase stack
(the test harness resets that database). The browser journey is
`frontend/e2e/topic-checklist.spec.ts`; boot the documented `make e2e-up` stack,
then run `npm exec playwright test e2e/topic-checklist.spec.ts`. E2E oracles cover
plan ciphertext and enrollment orphans.

Manual checks:

1. Generate a plan from a quiz/exam date and selected materials. Confirm the topic
   sources and that sessions stop before the assessment.
2. Finish a session, reload, and confirm the session persists without raising mastery.
3. Practice a tracked concept or take a Sapling quiz. Refresh progress and confirm
   the matching topic reflects the course mastery score.
4. Add/edit/remove topics, move a session, change availability and replan.
   Completed sessions for retained topics should remain.
5. Try an unrealistic deadline/time budget and confirm an explicit coverage warning.
6. Open the same plan in two windows, edit one, then edit the other. Confirm the
   stale edit is rejected and refreshing loads the saved version.
7. Switch course/semester; neither plans nor selectable materials should leak
   between enrollments. Check the stacked schedule/checklist on a narrow screen.

### Implementation validation (October 21, 2026)

- Baseline: PR #728 head `a4c99e7c`. Environment files and unrelated local skill
  changes were preserved. Nothing was pushed or applied to hosted databases.
- Full frontend unit suite: 1,791 passed, 2 skipped. Obsolete tests for the removed
  second guide-creation flow were replaced with unified-flow and saved-history tests.
- Frontend typecheck and production build passed; lint passed with 19 existing warnings.
- Backend regression selections: 248 passed, including the combined-agent evidence test. These exercise scheduling, manual dates, undated sources,
  access control, encrypted payloads, concurrency, budgets and existing checklist behavior.
- Backend lint passed. Scoped `.gitattributes` preserves canonical graph SVG LF bytes.
- The memory-only browser preview uses the real plan service/routes with fixed sample
  generation and external requests blocked. Verified guide overview/study points,
  manual dates, schedule bounds, completion/reload and no external requests. Its data
  lasts until the preview process stops; this is not real-storage validation.
- The new migration was not applied. Real-storage integration and full-app Playwright
  tests still require a disposable database. The live project's missing migrations
  prevent claiming a verified production deployment.
