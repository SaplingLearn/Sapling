# Unified assessment study guide

## Student flow

Open **Study → Study Guide** (`/study?mode=guide`) and choose a course.
The old `/study?mode=plan` URL opens the same combined workspace. The feature
also remains available from **Knowledge map → course → Study guide**.
The UI keeps PR #728's cream/sage surface and shared typography.
All enrolled courses are shown as active; there is no semester selector or global
semester filtering in this feature. Ownership remains enrollment-scoped internally,
with the backend resolving the current or most recent owned enrollment. Choose **New assessment** or
**Create a study plan**, enter a quiz/exam name and date, then describe its
coverage and/or select assignments and library documents from that enrollment.
Choose study days and a start date. Sapling recommends daily study time from the
topics, remaining dates, and concept progress; students do not enter hours. Dates use the
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

Topic checklist checkboxes and daily-session checkboxes share the same study
activity: checking a topic finishes its initial study session (or review for an
already-mastered topic). They never update graph mastery. The checklist separately
shows topics studied and topics mastered.
Plan topics, including added topics, can be edited or removed. Saving topic edits
rebuilds unfinished sessions and retains completed sessions for retained topics.
Renaming a topic can change its graph match. Material selection/coverage is fixed
after creation; create a new assessment plan for different source coverage.

## Scheduling

Scheduling is deterministic, without another model call. Automatic estimates
use 25-minute focus blocks and distribute work across available days. Suggested
daily time is capped at 120 minutes; unrealistic deadlines produce coverage
warnings rather than an unlimited workload. It prioritizes weak and
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
  "study_days": [0, 1, 2, 3, 4]
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

## Local testing without resetting your database

The October 26 environment check confirmed this machine's backend and frontend
point to local Supabase, with matching session secrets. The feature's 31 pending
local migrations were applied using the existing runner, including the encrypted
assessment-plan table. No database reset, hosted migration, or environment-file
change was performed.

Keep Docker Desktop and the existing local Supabase stack running. Restart your
backend and frontend after switching to `feature/unified-assessment-guide`:

```powershell
# Terminal 1, from repository root
cd backend
.\venv\Scripts\python.exe -X utf8 main.py

# Terminal 2, from repository root
cd frontend
npm run dev
```

Open `http://localhost:3000/study?mode=guide` and sign in normally. Choose any enrolled course. Create an assessment, manually enter a future
date, and attach documents/assignments and/or describe its coverage. The date does
not need to exist in the material. Check the overview and study points alongside
the schedule, finish a session and reload, edit a topic, and move/replan sessions.
Then choose **New assessment**: the previous name, date and sources must be cleared.

For a repeatable **no-paid-AI**, real-storage check (from `backend/`):

```powershell
.\venv\Scripts\python.exe -X utf8 -m scripts.smoke_assessment_guide
```

This uses the existing rich seed account/course, creates an undated temporary
document and assessment through the real service/routes, checks encrypted storage
through an independent SQL connection, and deletes only its own temporary rows.
It checks guide content, scheduling, persistence, unchanged mastery, stale-edit
rejection, rescheduling, semester isolation and deletion. It refuses non-loopback
database/API URLs or non-local/test environments. It does not reset or reseed your
database. `--user-id`, `--course-id` and `--semester` can name another existing local
enrollment. No separately running frontend/backend is needed for this smoke check.

Real guide generation uses the `assessment_guide` Anthropic slot, matching the
current implementation's loop-safe Claude native-output profile. It requires
`ANTHROPIC_API_KEY` on the backend; a missing key returns a clear error before any
generation reservation. No key was added or edited here.

To test the UI without a model key, start the backend from a fresh PowerShell
terminal using the existing deterministic handler seam:

```powershell
cd C:\Users\luke6\sapling\backend
$env:SAPLING_MODEL_MODE = 'function'
$env:SAPLING_FUNCTION_HANDLERS = 'agents.function_handlers_e2e'
.\venv\Scripts\python.exe -X utf8 main.py
```

Keep the local database running and start the frontend normally in another
terminal. These are **sample responses**, not live AI. Use the seeded CS course
with coverage such as `Recursion and Variables and Types` for this deterministic
handler. The standalone smoke check above exercises this flow automatically.
Use a fresh backend terminal without those mode overrides when a real Anthropic
key becomes available. No live Anthropic generation has been verified here.

## Deployment

The migration must be reviewed and applied through the normal staging/promotion
workflow before deploying the backend. No hosted migration has been applied here.
Keep actual `.env` files out of the PR. This branch retains its PR #728 baseline.
Assessment guides use Anthropic token counting and receipts. The append-only
`20261027012000_assessment_anthropic_receipts.sql` migration extends settlement
to the pinned Haiku slot while preserving existing Gemini course-checklist
receipts and conservative reservation limits. It was applied only locally.

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
7. Select another course; neither plans nor selectable materials should leak
   between courses. Changing the global semester must not hide study-guide courses. Check the stacked schedule/checklist on a narrow screen.

### Implementation validation (October 26, 2026 — latest follow-up)

- Creation conflicts no longer masquerade as stale edits; the draft's old Gemini
  generation path was replaced for this feature with Anthropic, and missing-key
  failures occur before reserving capacity.
- The guide is now an interactive topic checklist with synchronized daily focus
  sessions, automatic study-time recommendations, and explicit Library attachments.
- Anthropic native SDK serialization/counting and receipts are tested using only
  an in-process mock. SQL settlement and replay were tested inside a rolled-back
  local transaction. No live Anthropic call was made.


- Real local Supabase smoke passed with an undated document, a manually entered
  date, guide content, encrypted SQL storage, persistence, unchanged mastery,
  rescheduling, stale-write rejection, semester isolation and deletion.
- Real browser → Next.js → FastAPI → local Supabase check passed: guide creation,
  overview/study points and schedule, completion/reload, topic editing and mobile
  overflow check. Model output was deterministic; no paid AI calls were made.
- The new-assessment form regression was reproduced before fixing it and passes
  after clearing reused form state. Local sign-in defaults preserve the backend
  fix without weakening shared-deployment defaults.
- The existing reset-based integration suite remains opt-in; it was not run against
  the developer's populated database. Use the non-destructive smoke above instead.
- Regression checks: 1,792 frontend tests passed (2 skipped), 353 backend tests
  passed, typecheck and production build passed, and lint passed with the existing
  frontend warnings.
- No shared database changes, environment-file edits, commits or pushes were made.


### Final course-selection adjustment

All enrolled courses are treated as active in the study guide. The global semester
filter cannot hide its courses, and both the standalone guide and graph-embedded
panel omit semester controls. Saved-guide history is filtered by course only.
The backend still resolves an owned enrollment automatically; no stored records
or enrollment relationships were rewritten. Eighteen targeted frontend tests,
including the global-filter regression, passed after this change.
