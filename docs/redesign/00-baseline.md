# Redesign baseline: Learn, Library, Tutor (prompt 00)

Integration record for the cream-and-sage redesign of **Learn, Library and
Tutor only**. It names the code the later prompts edit, what they must keep,
and which wireframe affordances have no backend contract. Recorded 2026-10-19.

- Design source (editable Pen): https://app.pen.dev/s/sxEA2n5Ikk7KWUOanWPghMWYFFS0SbPgbkwkIm9dLYA
- Published wireframe PDF (Trov artifact): https://trov.dev/saplinglearn/#artifacts/sapling-redesign-learn-library-tutor-wireframes
- Handoff package: `Sapling-Redesign-Handoff/` (Jose's Trov handoffs #8–#10). Read-only. Its `pdf/`, `wireframes/*.png`, `assets/` and `components/` are cited below. The package is not committed here.

## 1. Revisions and the agreed base

| Source | Revision | State at audit |
| --- | --- | --- |
| `main` | `84e19c3a` (Merge #715) | Unchanged since the handoff audit |
| PR #673 `feat/learning-loop` (Jose; draft; CONFLICTING) | `a8abd006` | Unchanged. Already contains main up to #726 (`2b6f1ce4`) and all of PR #692 (`epic/learning-loop-handover` @ `5f61c851`: 0 commits not in #673) |
| PR #727 `feature/fa26-mvp1-ui` (lpcooper-arch / Luke; draft; CONFLICTING) | `49c108bf` | Unchanged. Based on `f852e119`, 80 commits behind main |
| PR #726 `feature/mvp1-quiz-and-map` (Luke) | merged to main 2026-10-19 | Carries the reviewed versions of #727's first three commits |

**Base decision (default plan, taken on Andres's behalf):** `feat/redesign-base`
= `main` 84e19c3a, then #673 merged, then #727 merged. Both merges are real
merge commits. Neither PR branch was rebased or squashed.

| Commit | What |
| --- | --- |
| `6bc91a21` | Merge #673 into main |
| `35413511` | Merge #727 |

The redesign foundation (prompt 01) branches from this base as
`feat/redesign-foundation`. Prompts 02–05 build on the foundation.

No product or ownership call was needed. #727's Learn changes are styling only
(the start form, the chat bar, the rail default and labels). They sit in the
classic `LearnInner` tree. #673's loop lives in `LoopLearn`. The two never
implement the same screen two ways.

### Conflict resolution

**Merge 1 (#673).** All four conflicts came from main's #715 local owner seed
meeting the loop seed.

- `backend/main.py` keeps both shutdown hooks. `shutdown_draft_pool()` stays first, because A38 m8 requires it.
- `backend/db/seed_local_rich.py`:
  - keeps #715's `_seed_dataset(writer)` and `seed_owner`;
  - the no-flag fixture seed also runs `seed_learning_loop()`, which writes fixed loop and capped users plus shared course assets;
  - the owner seed never runs it.
- `backend/tests/test_seed_local_rich.py` and `test_learning_seed_loop_user.py` keep both test sets. Two assertions follow the new step structure.

**Merge 2 (#727).** #727's commits `cc77339a`, `ac7f61df` and `3811181c` are the
**pre-review** versions of #726. `git cherry` and a patch diff show
context-only differences. #726 then added nine review-fix commits.

- All 27 conflicts in that superseded content resolve to the reviewed #726 side.
- `20261012232101_topic_checklists.sql` is not re-added. #726 renamed it to `20261019005643_topic_checklists.sql`, so carrying both would run the DDL twice.
- The UI commit `49c108bf` was then applied in full (3-way). It conflicted only in:
  - `ShellFrame.tsx`: the FA26 shell is kept, and #620's `NavFeatureGate` still wraps the page.
  - `screens/Learn.tsx`: both sides deleted dead code (`startNextFromSummary` and `modeOptions`).
- `fa26/Navigation.tsx` now applies the #620 `hide_<feature>` flags and carries the `nav-link-<route>` test ids that `e2e/feature-flags.spec.ts` uses. Two new tests cover this.

**Migrations.** #673 adds 27 `*_learning_*` migrations. None of them collide by
timestamp or name with main's or #727's. `20261018010000_quiz_written_responses.sql`
was add/add and resolves to main's guarded version.

### Overlapping files (#673 ∩ #727, measured from #727's base)

- **Backend:** `agents/_providers.py`, `agents/function_handlers_e2e.py`, `e2e_oracles/gather.py`, `.env.example`, `main.py`, `models/__init__.py`, `routes/quiz.py`, `services/quiz_config.py`, `services/topic_checklist_service.py`, and the matching tests.
- **Frontend:** `screens/Learn.tsx`, `Study.tsx`, `Tree.tsx`, `Tree.quiz.test.tsx`, `TopicChecklistPanel*`, `quiz/question/QuizQuestion*`, `quiz/results/MissedList.tsx`, `lib/quiz/types.ts`, `lib/types.ts`, `e2e/upload.spec.ts`, `e2e/quiz-written.spec.ts`, `eslint.config.mjs`, `docs/frontend-testids.md`, `docs/quiz-formats.md`.
- Every quiz and checklist overlap was already reconciled by #726. The only true UI overlap is `screens/Learn.tsx`.

### Not pulled in (report only)

- `docs/superpowers/plans/learning-loop/CONTINUE.md` (on #673) is the 2026-09-29 handover and is stale. The packages it lists as open (PKG-07…15, A33) have since merged into #673 and are verified in `LEDGER.md`.
- The ledger's remaining "Blocked notes" are eval-quota and live-model items. No code needs to be in the redesign base.
- #692 is already fully inside #673.

## 2. Route, controller and API map

### Learn and Tutor: one engine on `/learn`

- **Route:** `frontend/src/app/(shell)/learn/page.tsx` → `components/screens/Learn.tsx` `Learn()` (:329).
- **Gate:** `useLoopStatus(userId, userReady)` (`components/learn/useLoopStatus.ts`) calls `getLoopStatus` (GET `/api/learn/loop/review/active`) with a 2.5 s timeout.
  - **Legacy** (`LearnInner`) is selected only by a definitive answer: 200 `{active:false}`, a gated 404 (`lib/api.ts:995`), or an empty `userId`.
  - **Timeout, network or 5xx** shows `loop-status-error` with `loop-status-retry`. It never falls through to legacy.
  - Tested by `learn/LearnBranch.test.tsx` and `useLoopStatus.test.tsx`.
  - **Preserve this behaviour exactly.**
- **Loop controller:** `components/learn/LoopLearn.tsx`.
  - State: `useReducer(reduceLoopEvent)` from `loopState.ts`. The `hint` stream phase maps to `check` via `uiPhaseOf`.
  - Server phases are `probe | plan | teach | check | feedback | close`. The UI labels them `STEPS` (:113): Check-in, Plan, Learn (teach/check/feedback), Wrap-up.
  - Render order: sessions error → no course → read-only → start error → loading → goal editor (`LearningScope.tsx` `GoalEditor`, only in probe/plan) → `ProbePanel` → `PlanPanel` → `ClosePanel` → otherwise teach/check/feedback (`ChatPanel` + `CheckCard`, with the private radiogroup `OptionList`).
  - Hint: `postLoopAttempt` → `requestLoopHint` → `requestLoopHintTurn`.
  - Rating appears only when `ask_rating` is set.
  - Close is idempotent; a 409 goes through `enterClosed`.
  - `BudgetPausedBanner` is rendered at :1250.
  - The `AbortController` is the `streamAbort` ref. Stop, unmount, closing and a session switch all abort it.
- **Session discovery** (`loadSessions`):
  1. `?resume=` (or the older `?session=`) in any course resumes that session. A legacy or closed session opens read-only.
  2. Otherwise the newest open session resumes.
  3. Otherwise a new session starts.
  - A list failure sets `loop-sessions-error` with Retry and never starts a session.
  - `?topic=` while a session is open shows the `loop-topic-offer` banner; it never discards the session.
  - The deep link (`resume`, `topic`, `course`, `mode`, `suggest`) is read once and then stripped.
- **Classic Learn (legacy / kill switch):** `LearnInner` (Learn.tsx:363).
  - Sessions list, resume, rename and delete.
  - Modes socratic/expository/teachback, synced to `?mode=`.
  - `ModelToggle` and `SharedContextToggle`, inside "Session options".
  - The knowledge-map rail (`SidebarKnowledgeGraph` → `KnowledgeGraph`): collapsible and drag-resizable, with chat/graph tabs on mobile.
  - Interrupted-turn Retry (`retryText` + `handleRetry`).
  - Two-click End session.
- **Shell labels:**
  - The FA26 rail labels `/learn` **"Clov"** (`fa26/Navigation.tsx`); labels show as hover/focus tooltips.
  - Classic Learn's TopBar title is "Clov". LoopLearn's title is the course name.
  - `lib/navFeatures.ts` still labels `/learn` "Tutor", but only the admin flag tab shows that label.
  - `SideNav`/`TopNav` are no longer mounted after #727; only their tests import them.
  - **Open IA decision for 02/04:** the wireframes show separate **Learn** (pencil) and **Tutor** (tree) nav entries. Both must open `/learn`, the same session and the same reducer. No second route or store. Decide the entry mechanism (for example a view parameter on `/learn`) in prompt 02 and keep `navFlagForPath('/learn') === 'hide_tutor'` covering both.

### Library

- **Route:** `frontend/src/app/(shell)/library/page.tsx` → `components/screens/Library.tsx` `Library()`.
- **State:** `cat`, `courseFilter` (all / uncategorized / course_id), `query`, `view` (grid/list) and `detail`.
- **Loading:** `getDocuments` + `getCourses`. Courses are de-duplicated.
  - **Gap:** a fetch failure only reaches `console.error`, so the user sees the empty "library is quiet" state.
  - **Gap:** the detail overlay is a custom portal with no `role=dialog`, no Escape and no focus trap (scroll lock only).
- **Actions:**
  - Doc scan → `scanDocumentConcepts`.
  - Course scan → `scanCourseConcepts`, only when a specific course is selected.
  - Delete uses a two-click `useConfirm`.
- **Upload:** `components/DocumentUploadModal.tsx` (role=dialog via `useOverlayBehaviour`).
  - PDF/DOCX/PPTX, at most 5 files, 100 MB each, a 4-minute timeout.
  - **SSE only** (`uploadDocumentStream`, POST `/api/documents/upload`). The sync fallback was retired in #151b; `/upload/sync` is used only by `uploadSyllabus`.
  - Retry, re-analyze, category change (`updateDocumentCategory`), inline add-course, and a copyable request id.
- **Semester:** Library and LoopLearn ignore the active semester. Classic Learn filters by it (`useActiveSemester`, `courseInTerm`).
- **User:** always `useUser().userId`. Ownership is enforced server-side.

### API clients (`frontend/src/lib/api.ts`, same-origin `fetchJSON`, cookies)

- **Loop**, all under `/api/learn/loop`. Loop POSTs go through `loopPost`.

  | Client | Method and path |
  | --- | --- |
  | `getLoopStatus` | GET `/review/active` |
  | `listLoopSessionsFor` | GET `/sessions` |
  | `getLoopSessionStatus` | GET `/status` |
  | `startLoopSession` | POST `/start-session` |
  | `setLoopGoal` | POST `/goal` |
  | `nextLoopProbe` | POST `/probe/next` |
  | `answerLoopProbe` | POST `/probe/answer` |
  | `getLoopPlan` | GET `/plan` |
  | `approveLoopPlan` | POST `/plan/approve` |
  | `streamLoopChat` | SSE `/chat/stream` |
  | `nextLoopCheck` | POST `/check/next` |
  | `streamLoopCheckAnswer` | SSE `/check/answer/stream` |
  | `postLoopAttempt` | POST `/step/attempt` |
  | `requestLoopHint` | POST `/hint` |
  | `requestLoopHintTurn` | POST `/action` |
  | `submitLoopRating` | POST `/rating` |
  | `closeLoopSession` | POST `/close` |

  Retention and review clients (`/posttest/*`, `/review/*`) serve `/study`.
- **Classic**, under `/api/learn`: `startSession`, `startSessionStream`, `streamChat`, `sendChat`, `learnAction`, `switchMode`, `endSession`, `getSessions`, `resumeSession`, `renameSession`, `deleteSession`.
- **Documents**, under `/api/documents`:

  | Client | Method and path |
  | --- | --- |
  | `getDocuments` | GET `/user/{id}` |
  | `uploadDocumentStream` | POST `/upload` |
  | `uploadDocument` | POST `/upload/sync` |
  | `updateDocumentCategory` | PATCH `/doc/{id}` |
  | `scanDocumentConcepts` | POST `/doc/{id}/scan-concepts` |
  | `scanCourseConcepts` | POST `/course/{id}/scan-concepts` |
  | `deleteDocument` | DELETE `/doc/{id}` |
- **Graph:** `getGraph` (GET `/api/graph/{id}?semester`) and `getCourses` (GET `/api/graph/{id}/courses`).
- **Backend mounts:** `backend/main.py` mounts `learn` at `/api/learn` and `learn_loop` at `/api/learn/loop` (which 404s when `LEARNING_LOOP_ENABLED=false`). `documents` is at `/api/documents`.

## 3. Preserved-feature inventory (must survive 02–04)

- **Gate:** the loop/legacy gate and its error/Retry. `LEARNING_LOOP_ENABLED` remains the env kill switch.
- **Learning model:** server-owned phases; goal = whole course or 1–12 confirmed concept ids, plus an optional objective of at most 500 characters.
- **Diagnosis:** truthful status text. A plan needs explicit approval with `goal_version`.
- **Checks:**
  - free / teachback / mc_reason, using served letters and order;
  - `idk`; the question hash;
  - grading only through `/check/answer/stream`, never through chat;
  - hint gating with its denial reasons.
- **Session handling:**
  - rating only on request;
  - idempotent close, with 409 reconciliation;
  - budget pause (chat paused; checks and study stay reachable);
  - session discovery and resume;
  - read-only past sessions;
  - the topic offer;
  - stream abort on session or course switch.
- **Classic tutor:** modes, the model picker, the shared-context toggle, the knowledge-map rail, interrupted-turn Retry, rename/delete/resume, and the mobile chat/graph tabs.
- **ChatPanel:** markdown, math, code, mermaid and plots; streaming text; Stop; Retry (when it is wired); hint/confused/skip actions; the draft seed.
- **Library:** search across filename and summary; category, course and uncategorized filters; grid and list; detail with concept notes; doc and course scan; two-click delete; the full upload modal (above).
- **Shell:** the #727 FA26 rail; the account menu (Settings, Grades, Course planner, Achievements, Community, Admin for admins); the notification, settings and report utilities; `hide_<feature>` flags and route redirects; the skip link; `data-testid="app-shell"`.
- **Test ids:** every `loop-*`, `tutor-*`, `library-*`, `upload-modal-*` and `nav-link-*` id listed in `docs/frontend-testids.md`, and the ids found in this audit (see LoopLearn, LearningScope, Learn, ChatPanel, Library and DocumentUploadModal). Migrate an id only with equivalent coverage.

## 4. Unsupported wireframe affordances, and their supported mapping

| Wireframe affordance | Contract today | Mapping (do not stub success) |
| --- | --- | --- |
| Library "Open original material", page preview, "12 pages", file size | No original-file URL, page count or thumbnail on `Document` | Omit it, or show the summary clearly labelled as a summary. Needs an API extension that is agreed separately. |
| Library "Notes" tab | No notes collection on documents (`/notetaker` is a separate feature) | Remove the tab, or link to `/notetaker` honestly. Never a fake collection. |
| Library "File type" filter | `category` is not a MIME type | Derive the extension from `file_name` locally and document it, or keep the category filter. |
| Library "Ask Clov about this" | No contract attaches a document id to a chat turn | Navigate to `/learn?course=…` (or `?topic=`) with honest copy. No citation chips. |
| Tutor "Materials" in composer | No direct chat attachment | Make it a link or sheet to real Library material for the course. Not an upload. |
| Tutor and Loop "Retry response" | LoopLearn passes no `onRetry`. Interrupted loop turns carry no `retryText`. | Needs new UI wiring over `streamLoopChat`, for conversational turns only. Checks recover status-first (`getLoopSessionStatus`). Tests are required (prompt 04). |
| "How sure do you feel?" chips (u1gDw) | No confidence endpoint. Rating is `/rating`, only when `ask_rating` is set. | Optional self-report that is never sent, or drop the chips. Never mastery evidence. |
| "Session history" / "History" | `listLoopSessionsFor` + `getLoopSessionStatus` (loop); `getSessions` / `resumeSession` (classic) | Open sessions resume; past sessions are read-only. Already supported. |
| "+ New session" | Close, then start | A confirmation is needed; cancel leaves the current work untouched (prompt 04). |
| "I'm confused" / "Another example" (ULhG3) | Classic: `learnAction` hint/confused/skip. Loop: chat only. | Classic: existing actions. Loop: seed a chat message. Never graded. |
| Search box ⌘K in top bar | No global search endpoint | Out of scope. Omit it. |
| Knowledge graph art (`knowledge-graph-reference.svg`) | Sample data | A reference only. Production keeps `KnowledgeGraph` bound to real data and its original colors. |
| Mobile bottom tab bar (AS0Yn) | The FA26 shell has no bottom bar (a 64 px rail below 700 px) | A shell-wide change, so a product call for Andres. Prompts 02–04 keep the rail unless he decides otherwise. |

## 5. Visual references

- **Learn:** `u1gDw` (desktop), `zF4QB` (mobile).
- **Library:** `KTCuj` (desktop), `AS0Yn` (mobile).
- **Tutor:**
  - active: `ULhG3` (desktop), `rIzSa` (mobile)
  - start: `s3Kxuz` (desktop), `wRolX` (mobile)
  - plan: `W14qiJ` (desktop), `QgtPP` (mobile)
  - check: `Z0WKXz` (desktop), `lzEyB` (mobile)
  - desktop context: `HHU6e`
  - mobile Map: `WCplx`
  - mobile goal and plan: `cSgSE`
  - supporting states: `hgkZT`
- All frames are in `wireframes/` except the overview `T8rfm`, which is listed but not exported. The PDFs are `pdf/Sapling-Learn-Library-Tutor-Wireframes.pdf` (8 pp) and `pdf/Sapling-Redesign-Implementation-Handoff.pdf` (31 pp).
- **Approved assets** (`assets/asset-manifest.json`, SHA-256 verified on copy):
  - `sapling-wordmark-approved.svg`
  - `nav-{today,learn,library,tutor,calendar}.svg`
  - `paper.svg`
  - `clov-avatar.svg`
  - Aleo, SUSE and IBM Plex Mono with their OFL texts
- `knowledge-graph-reference.svg` is sample art and is not shipped. `figma-source-alternatives/` is not approved and is ignored.

## 6. Dependency order

1. **01 foundation:** tokens, fonts, assets and primitives on `feat/redesign-foundation`. It changes no behaviour.
2. **02 Learn:** `LoopLearn.tsx`, `LearningScope.tsx`, `LoopLearn.module.css`. Adopt `PhaseStrip`, `GoalSummary`, `ChoiceGroup` and `ContextPanel`. Settle the Learn/Tutor nav entry.
3. **03 Library:** `Library.tsx`, `DocumentUploadModal.tsx`. A visible load failure and Retry; the detail view becomes `ContextPanel`/`ContextSheet`. Independent of 02 and 04.
4. **04 Tutor:** `ChatPanel.tsx` (+ IME guard), `Learn.tsx`, and the teach view of `LoopLearn.tsx`. Loop Retry wiring and the new-session confirmation. **Collides with 02 on `LoopLearn.tsx`:** run it after 02, or split by region.
5. **05 verification:** the full matrix, E2E lanes and screenshots.
6. **Shared hot files:** `lib/api.ts` (no payload changes expected), `ChatPanel.tsx` (04 only), `fa26/Navigation.tsx` (02 only, for the IA decision).

## 7. Commands (from `frontend/package.json`, `.github/workflows/{ci,e2e}.yml`, `Makefile`)

**Frontend.** Run from `frontend/` with npm 10.9.x. On npm 11 and later, the read path only is `npm_config_engine_strict=false npm ci`; never commit a lockfile from it.

```sh
npm ci
npm run typecheck
npm run lint
npm test                 # vitest run
npm run build:test       # next build with the non-secret E2E env (plain `npm run build` requires BACKEND_URL)
```

**Backend.** Run from `backend/` in a venv built from the hash-pinned lock (CI installs exactly this). The non-secret dummy env comes from `ci.yml`.

```sh
pip install --require-hashes -r requirements.lock
ruff check .
ENCRYPTION_KEY=$(printf '0%.0s' {1..64}) GEMINI_API_KEY=dummy SUPABASE_URL=https://dummy.supabase.co \
SUPABASE_SERVICE_KEY=dummy SESSION_SECRET=dummy python -m pytest tests/ -q --ignore=tests/evals \
  --ignore=tests/test_docling_integration.py --ignore=tests/test_ocr_pipeline.py --ignore=tests/test_extraction_backends.py
```

**E2E** (repo root). The stack is a machine singleton, so take the lock for the whole cycle.

```sh
flock /tmp/claude-$(id -u)/sapling-e2e-stack.lock bash -c '
  export SAPLING_MODEL_MODE=function SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e
  make e2e-up && (cd frontend && npx playwright test e2e/); (cd backend && venv/bin/python -m e2e_oracles); make e2e-down'
```

Never set `SAPLING_MODEL_MODE` for the hermetic pytest run.

## Refresh 2026-10-19

`feat/redesign-base` re-merged #673 at its new head **ad1b1bd5** (23 commits after a8abd006: learning evidence transactions and replayable grade checkpoints, checklist budget reservation, durable tutor-turn recovery, the LoopLearn hydration/pending-feedback/withdrawal/late-cancellation/practice-preflight behaviours, and Jose's own `6eb31fff` merge of main 84e19c3a). #727 (49c108bf) and main (84e19c3a) had not moved.

- **New migrations from #673:** `20261019125459_checklist_budget.sql`, `20261019131339_learning_evidence_transaction.sql`, `20261019141950_learning_evidence_forward_repair.sql`. All sort after every existing basename (latest before was `20261019010000_learning_planning_observation.sql`), so the runner applies them in order; none was renamed or edited. No `requirements.lock` or `package-lock.json` change.
- **Conflicts (3), none with #727:** `backend/db/seed_local_rich.py`, `backend/tests/test_learning_seed_loop_user.py`, `backend/tests/test_seed_local_rich.py`. Both this base (6bc91a21) and Jose (6eb31fff) had merged the same main 84e19c3a into #673 and resolved the #715 owner-seed overlap independently. Jose's resolution is the canonical one for his branch (behavioural `main([])` ordering test, `SEED_LOOP_CONCEPTS` node count, owner seed never copies loop QA users/budget), so all three take #673's side. A check confirmed the two main merges differ only in these three files.
- **#727 overlap:** none new. The merge result equals ad1b1bd5 plus exactly the #727 delta (and this doc) that 35413511 introduced; its ShellFrame/Learn.tsx/#726-checklist resolutions carry over unchanged.
