# Redesign review package: Learn, Library and the Clov tutor (prompt 05)

**For:** Andres (implementation owner). **Branch:** `feat/redesign-integration`
(pushed). **Status:** integrated and verified against the deterministic local
stack. NOT merged, NOT deployed, no PR opened. This file is meant to be used as the
PR description.

- Design source (Pen): https://app.pen.dev/s/sxEA2n5Ikk7KWUOanWPghMWYFFS0SbPgbkwkIm9dLYA
- Wireframe PDF (Trov artifact): https://trov.dev/saplinglearn/#artifacts/sapling-redesign-learn-library-tutor-wireframes
- Handoff package (Jose's Trov handoffs #8–#10; read-only, not committed):
  `Sapling-Redesign-Handoff/pdf/Sapling-Learn-Library-Tutor-Wireframes.pdf` (8 pp),
  `pdf/Sapling-Redesign-Implementation-Handoff.pdf` (31 pp), `assets/asset-manifest.json`
  (the approved wordmark, botanical nav, `paper.svg` and `clov-avatar.svg` exports, SHA-256 verified on copy).
- Screenshot evidence (outside the repo, in the handoff bundle):
  `sapling-redesign-bundle/evidence/{01-foundation,02-learn,03-library,04-tutor,05-integrated}/`.

## Problem and result

Learn, Library and the tutor looked like three products on top of one learning
engine: PR #673's loop inside Luke's FA26 shell (PR #727). This branch applies the
approved cream-and-sage design to those three surfaces only, using shared
primitives. The design uses paper `#F7F4E9`, sage `#E5EBDD`, ink `#253D2F` and olive
`#416207`, with Aleo and SUSE type and the authored assets.

- **Learn and the Clov tutor are two views of ONE controller.** They share the same
  `/learn` route, session, goal, plan and server phase. Switching views changes only
  `?view=`.
- **Library is rebuilt.** It adds the visible failure, Retry, offline and
  scan-result states that the baseline did not have.
- **No new backend contract is used.** The only backend change is the `tutor_view`
  flag declaration and its test.
- **Graph colours are untouched.** The knowledge map keeps its original palette.

## Branch chain

| Branch | SHA | What |
| --- | --- | --- |
| `feat/redesign-base` | `f56ef77e` | `main` 84e19c3a + merge PR #673 (learning loop) + merge PR #727 (FA26 UI) + `docs/redesign/00-baseline.md` |
| `feat/redesign-foundation` | `5bbe8dbd` | Tokens, fonts, approved assets, shared primitives in `components/sapling/`, scoped to `/learn` and `/library` |
| `feat/redesign-learn` | `e98c4ea3` | Learning Studio redesign plus the confirmed new session (prompt 02) |
| `feat/redesign-tutor` | `7edf8756` | The Clov tutor view (`/learn?view=tutor`, `tutor_view` flag) and safe Retry (prompt 04) |
| `feat/redesign-library` | `58d5279b` | Course Library and the upload modal (prompt 03); a sibling of learn/tutor |
| **`feat/redesign-integration`** | **`c91554bf`** (code, verified) + the docs commit carrying this file | tutor + `--no-ff` merge of library (`362e721c`) + the prompt-05 repairs below |

**Merge:** the library merge auto-merged with no conflicts. I checked the known
overlap points by hand, and both sides survive:

- `sapling/primitives.tsx`: Learn's `GoalSummary action` is kept.
- `sapling/ContextPanel.tsx`: Library's `ContextSheet className` and
  `ContextPanel sheetClassName` are kept.
- `docs/frontend-testids.md`: both surfaces' id tables are kept.
- `eslint-suppressions.json`: Library's removal of its two `no-explicit-any`
  entries is kept, and lint still exits 0.

**Prompt-05 commits on top of the merge:**

| Commit | Change |
| --- | --- |
| `52f3618c` | Library honours `?course=`. Learn and Tutor link to `/library?course=<id>`. |
| `8e600ddc`, `8f04d661` | testids doc; 04-tutor gap marked resolved |
| `b15232c6` | upload.spec: Upload locator scoped to the shell's `<main>` (open item 1, below) |
| `449a5ed5` | Tutor session menu: Escape on its trigger closes it (keyboard pass finding) |
| `6b28d0f4` | Composer box: visible 2px focus ring (keyboard pass finding) |
| `c91554bf` | `redesign-journey.spec.ts` (default lane) + `redesign-evidence.spec.ts` (gated evidence) |

## Per-surface before / after

The "before" screenshots are the foundation-state captures in
`evidence/01-foundation/`: the baseline screens with tokens only.

**Learn (Learning Studio), prompt 02.** Evidence is in `evidence/02-learn/` (goal,
probe, plan approval, check, hint denied, feedback, wrap-up, failure Retry,
new-session confirm, route sheet; 1440/768/390/320) and in `05-integrated/03*`.

- The heading carries the course and names the phase.
- The phase strip (Check-in / Plan / Learn / Wrap-up) is read-only.
- The goal is a `GoalSummary`. It is editable only in probe and plan, and
  read-only while teaching.
- One explicit answer form serves check-in and checks:
  - `mc_reason` is a native radio group in the served order (sage only means
    selected), with an optional reason;
  - free and teachback answers use a labelled textarea;
  - "I don't know yet" submits `idk`.
- The plan lists numbered rows in server order with their reasons, the diagnosis
  limits, and an explicit approve step.
- The route, the map (original colours) and the sources sit in a rail from
  1024 px and in a labelled sheet below that.
- New session asks for confirmation when a session is open.

**Library, prompt 03.** Evidence is in `evidence/03-library/` (list, grid, detail
rail and sheet, upload in progress, saved, failure, fetch failure) and in
`05-integrated/01*, 02*, 06*, 07*`.

- Rows and cards use the approved `paper.svg`. The selected row is sage with
  `aria-pressed`.
- Course is a labelled `<select>`. Category and file type sit behind "More
  filters" on phones.
- The detail view is a desktop rail. Below 900 px it becomes a full-height
  labelled sheet with Escape, focus return and scroll lock.
- New states: a visible load failure with Retry, a refresh failure that keeps
  the data, a course-list failure, offline, scan results with real counts, and a
  failed delete with "Try delete again".
- Upload rows show Sending, then Processing (the server's stage), then Saved,
  and say Saved only after the result event.
- The upload modal lists rejected files with their reasons, offers per-row
  cancel and Retry, and reports partial success.
- **New in 05:** `/library?course=<id>` pre-selects that course.

**Clov tutor, prompt 04.** Evidence is in `evidence/04-tutor/` (start/welcome,
check-in, plan approval, active, goal & plan, map, materials, history,
streaming/Stop, interrupted/Retry, offline, knowledge check, same session in the
studio, budget pause; 1440/768/390/320) and in `05-integrated/04*, 05*, 09*`.

- The welcome shows only after discovery succeeds with nothing open. Starters
  fill the composer and send nothing.
- The top bar has the course, History, + New session (confirmed) and a session
  menu.
- Goal & plan, Materials and Map open as context chips: a panel from 1024 px, a
  sheet below that.
- History separates open sessions, which resume, from past sessions, which open
  read-only.
- Stop and Retry are safe; see the checklist.

**Integrated (05).** Evidence is in `evidence/05-integrated/`. It covers the
journey Library list → detail → "Ask Clov" → studio (plan) → keyboard plan
approval → teach → tutor → Materials → Library filtered to the course, at 1440,
390 and 320. It also covers three 200 % zoom captures (`07–09`), the Back probe
(`10`) and `keyboard-report.json`.

## Behaviour-preservation checklist

Status was checked on the integrated branch. The "pinned by" column names the tests
that hold each behaviour. Every E2E spec named here is green in the final run.

| # | Contract (handoff 02-learn / 00-baseline §3) | Pinned by |
| --- | --- | --- |
| L1 | **Gate.** The loop is the default. `LEARNING_LOOP_ENABLED=false` gives the legacy tree. A gate failure shows Retry and never the hybrid. | learn-loop.spec "every student gets the loop by default", "kill switch restores the legacy Learn screen"; `useLoopStatus.test`; the kill-switch lane (below) |
| L2 | **Server-owned phases.** The phase strip is display only; nothing advances on a click or a timer. | `LoopLearn.test` (phase strip); learn-loop.spec main journey |
| L3 | **Goal.** Whole course, or 1–12 confirmed concepts plus an objective of at most 500 characters. Text alone selects nothing. Editable in probe/plan; read-only while teaching, where a new goal means a confirmed new session. | `LearningScope.test`, `LoopLearn.test`; learn-loop.spec "a phone learner confirms a goal…" |
| L4 | **Truthful diagnosis.** Limited, partial, untested and inconsistent results are never shown as a known edge. No numeric certainty. | `LearningScope.test`; backend `test_learning_*` (hermetic suite) |
| L5 | **Plan.** Server order and reasons. Explicit approval with `goal_version`. A continuation plan needs approval again in the same session. | learn-loop.spec "independent prerequisite recovery unlocks a fresh goal plan requiring approval in the same session" |
| L6 | **Explicit grading only.** Grading goes only through `/check/answer/stream`, using served letters and order, `idk` and the question hash. Chat never grades. | learn-loop.spec main journey; `LoopLearn.test` (radio order, Enter-to-submit); tutor-view.spec asserts no answer request during chat |
| L7 | **Hint gating.** Denial reasons are shown. An earned hint can retry. A late hint cannot reopen a graded check. | learn-loop.spec main journey (gated hint), "an earned hint arriving late cannot reopen a graded check" |
| L8 | **Resume and discovery.** A reload resumes the same session and item with no new probe. A list failure starts nothing. The topic offer and cross-course `?resume=` work. Past sessions are read-only. | learn-loop.spec "a reload mid-session resumes the same loop session and calls no probe route"; `LoopLearn.test`; tutor history tests |
| L9 | **Budget, isolation and close.** Budget pause keeps checks and study reachable. A switch aborts the stream and drops late responses. Close is idempotent, with 409 reconciliation. | learn-loop.spec "budget cap…", "switching sessions cancels a pending tutor stream…"; `LoopLearn.tutor.test` (late events) |
| L+ | **New-session confirm.** Cancel keeps everything. Confirm waits for `/close`. A 409 or failure starts nothing. | `LoopLearn.test` (cancel, Escape, wait, failure, no-prompt); keyboard pass (Escape returns focus to `loop-new-session`) |
| Lib | **Library capabilities.** Combined search/course/category/file-type in list and grid; duplicate enrollments deduped; detail with concept notes; doc and course scan with real counts; two-click delete with recovery; upload (PDF/DOCX/PPTX, 5 files, 100 MB, course binding, inline course add, cancel, per-file stages, partial failure and Retry); syllabus re-poll; post-upload refresh. | `Library.test` (incl. 2 new `?course=` tests), `DocumentUploadModal.test`; upload.spec (both journeys, Postgres readback + #435 course filter) |
| T1 | **Tutor Retry.** Only the latest conversational turn of the current session, one at a time. It reads the stored transcript first. If the turn was saved, nothing is re-sent; otherwise there is exactly ONE re-send; if the read fails, nothing is sent. | `LoopLearn.tutor.test` (35); tutor-view.spec (Stop → Retry and failed stream → Retry each leave exactly one stored user row, ciphertext at rest) |
| T2 | **No re-grade.** A broken feedback stream or a 409 already-graded reads `GET /status` first (`loop-recovery-note`). A submission is never replayed. | `LoopLearn.tutor.test` (broken feedback / already graded: one submission) |
| X1 | **One controller.** Studio ↔ tutor keeps the same session, with no new sessions row and no start request. Library → Learn keeps the course. Tutor Materials → Library keeps the course. | **new** redesign-journey.spec (DB-asserted via `support/db.ts`) |

## Open items from the surface agents, resolved

1. **`upload.spec.ts:73` on the tutor branch: a pre-existing test race, fixed in
   the test.**
   - I reproduced it on `7edf8756` in isolation, as the first test after boot. It
     is not ordering or seed pollution: every test re-seeds the database first.
   - The failing trace's DOM snapshots show the cause. `(shell)/loading.tsx`
     (from #466) makes every shell page a Suspense boundary, so React streams the
     page into a hidden `<div hidden id="S:0">` at the end of `<body>` and moves it
     into place when it reveals the page.
   - Right after `goto`, the only Upload button is that hidden server copy. While
     the client render lands inside `nav-feature-gate`, the hidden copy can still
     exist. The unscoped `getByTestId('library-upload')` then sees two disabled
     buttons (courses not loaded yet). A strict-mode violation fails at once
     instead of retrying.
   - Nothing user-visible is duplicated, and Tutor's Materials panel is not
     involved. The tutor branch's timing exposed the race.
   - **Fix:** both upload journeys read the button inside the shell's `<main>`
     (`app-shell`). The assertions are unchanged.
   - **Proof:** on the tutor SHA plus the fix, cold upload.spec gave 2/2 and
     tutor-view then upload gave 3/3. Without the fix, cold gave 1 failed and 1
     passed.
2. **Kill-switch lane: both streaming failures are caused by #727; zero
   regressions come from the redesign.** The lane was run as `e2e.yml` runs it
   (`LEARNING_LOOP_ENABLED=false` for both the stack and Playwright).
   - `feat/redesign-base` f56ef77e: **93 passed, 10 failed, 26 skipped**.
   - Integration (b15232c6 + then-uncommitted specs): **93 passed, 10 failed,
     34 skipped**.
   - The failure sets are identical: the 8 known #727 failures plus
     `streaming.spec.ts:189` and `:234`. #727 moved `tutor-back-to-learn` into the
     collapsed "Session options" `<details>`, so these fail on base too. I left
     them for #727.
   - The +8 skips are the new loop-only specs (tutor-view, tutor-evidence,
     redesign-journey, redesign-evidence).
   - Oracles: 0 findings on both.
3. **Library `?course=`: done, and contained.**
   - Library reads `?course=` once, after its courses load. It applies only an
     enrolled course, and never over a filter the student already picked.
   - Learn's Library links (studio composer, route rail source link, goal editor's
     no-concepts link) and the tutor's "Open course Library" now carry the course.
   - Library's own filter behaviour is unchanged.
4. **Same session and course across surfaces: confirmed, and DB-asserted** in
   `redesign-journey.spec.ts`, with one gap (G1).

## Keyboard-only pass and 200 % zoom

I ran Playwright, keyboard only, in `redesign-evidence.spec.ts`; the output is
`evidence/05-integrated/keyboard-report.json`. The final run's result is
`4 passed (26.6s)` with every soft check green.

- **Tab order is logical, and every stop shows a visible focus ring** on Library,
  the studio and the tutor at 1440 (24 stops each). The order is: skip link, nav,
  the page's own controls in reading order, then the shell utilities.
- **Escape closes the surface and focus returns to its opener** for:
  - the upload modal (focus moves to its first field on open);
  - the new-session confirmation;
  - the tutor history sheet;
  - the tutor session menu;
  - the tutor context sheet at 390, 320 and 200 % zoom (the desktop panel's Close
    returns focus to its chip);
  - the Library detail sheet at 390 and 320;
  - the learning-route sheet at 390 and 320.
- **No horizontal page scroll** at 390, 320 or 200 % zoom on any of the three
  surfaces. 200 % zoom is a 720 px layout at deviceScaleFactor 2.
- **The primary control is inside the viewport and not covered** (checked with
  `elementFromPoint`): plan approval at 390 and 320, and the tutor composer at
  1440, 390 and 320.
- **Two real findings, both fixed:**
  1. The tutor session menu kept focus on its trigger after opening, but only the
     panel handled Escape. The trigger now closes the open menu on Escape. A unit
     test covers it and fails without the fix.
  2. The composer textarea's only focus cue was a 1px border-colour change. It now
     has the same 2px olive ring as the other redesign controls.
- **Not covered by fixtures:** radio arrow keys on a served `mc_reason` set. The
  seeded check-in items are free-text, so the E2E pass could not reach a radio
  group. Native radio semantics and the served order are unit-tested
  (`LoopLearn.test`); arrow navigation is the browser's native behaviour there,
  not exercised end to end.
- The pass did not test real assistive technology (screen reader output), the
  software keyboard on a physical phone, or IME composition.

## Tests: exact commands and results

**Frontend**, from `frontend/` in the integration worktree. Install was
`npm_config_engine_strict=false npm ci`: the machine has npm 12 against the repo's
10.9.x pin, and no lockfile was committed.

| Command | Result |
| --- | --- |
| `npm run typecheck` | exit 0 |
| `npm run lint` | exit 0 (0 errors, 19 warnings; same count as before the merge) |
| `npx vitest run` | exit 0. **135 files; 1550 passed, 2 skipped** (1552) |
| `npm run build:test` | exit 0 (`✓ Compiled successfully`) |

**Backend**, from `backend/`, exactly as `ci.yml` runs it:

- Dummy env: `ENCRYPTION_KEY=0…0`, `GEMINI_API_KEY=dummy-not-used-in-tests`,
  `SUPABASE_URL=https://dummy.supabase.co`, `SUPABASE_SERVICE_KEY`,
  `SESSION_SECRET`. No `SAPLING_MODEL_MODE`, and `backend/.env` was hidden for the
  run.
- Command: `python -m pytest tests/ -q --ignore=tests/evals
  --ignore=tests/test_docling_integration.py --ignore=tests/test_ocr_pipeline.py
  --ignore=tests/test_extraction_backends.py`.
- Result: **9769 passed, 202 skipped**, exit 0.
- `ruff check .`: `All checks passed!`
- That run was on the merge commit. No later commit touches `backend/`.
- The docs/05 focused backend targets (`test_learning_*`, `test_learn_*`,
  `test_documents_routes.py`) are part of that suite.
- Not run: the OCR/docling suites (excluded by CI), the DB integration lane
  (`-m integration`) and live-model evals.

**E2E.** Each up→test→down cycle ran inside ONE
`flock /tmp/claude-1000/sapling-e2e-stack.lock`, with `SAPLING_MODEL_MODE=function`,
`SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e` and the rest of the
`e2e.yml` env (`GEMINI_API_KEY` dummy, `QUIZ_GENERATE_RATE_LIMIT=1000`,
`LEARNING_GATE_TIME_SCALE=0.01`, `LEARN_RATE_LIMIT_PER_MIN=1000`).

| Run | Result |
| --- | --- |
| **FINAL, default lane, `npx playwright test e2e/` on `c91554bf` (clean tree)** | **`8 failed` · `30 skipped` · `99 passed (12.9m)`**: the 8 failures are exactly the #727 list below |
| FINAL, oracles (`venv/bin/python -m e2e_oracles`) | exit 0: `0 finding(s), 0 suppressed (allowlisted).` |
| FINAL, evidence (`REDESIGN_EVIDENCE_DIR=… npx playwright test e2e/redesign-evidence.spec.ts`) | `4 passed (26.6s)` with every soft check green |
| Kill-switch lane, base f56ef77e | 93 passed, 10 failed, 26 skipped; oracles 0 findings |
| Kill-switch lane, integration b15232c6 | 93 passed, 10 failed, 34 skipped; oracles 0 findings |
| Diagnosis, default lane, merge 362e721c (+ WIP) | 98 passed, 9 failed (8 × #727 + the first draft of the new journey spec, since fixed), 26 skipped; oracles 0 findings |
| upload.spec on tutor 7edf8756, cold | 1 failed / 1 passed (reproduction) → with the fix 2/2, then tutor-view + upload 3/3 |

Every learn-loop, tutor, tutor-view, upload/library and redesign spec in the final
default lane: all green. That is learn-loop.spec 12/12 (its kill-switch test is skipped in this lane), tutor-view.spec 1/1, upload.spec 2/2 and redesign-journey.spec 1/1. tutor.spec (the legacy tutor) runs only in the kill-switch lane, where it is green. tutor-evidence.spec and redesign-evidence.spec are gated evidence specs, skipped here and run separately.

## Known failures from #727 (out of scope, left as they are)

These fail on `feat/redesign-base` with the redesign absent:

- `auth-session.spec.ts:32`
- `dashboard.spec.ts:21`
- `graph.spec.ts:214` (SVG node labels)
- `room-public.spec.ts:20`
- `semester-scope.spec.ts:24`
- `study-semester.spec.ts:31` (`dashboard-courses-key-toggle`)
- `viewport-fit.spec.ts:88`
- `viewport-fit.spec.ts:120`

The kill-switch lane adds `streaming.spec.ts:189` and `:234`, where
`tutor-back-to-learn` is now inside the collapsed "Session options".

## Unresolved contract gaps (merged from all surfaces)

- **G1 (new in 05; pre-existing loop behaviour from #673): the course is not kept
  in the URL.**
  - The loop consumes `?course=` at mount and cleans it from the URL. With no
    `?course=`, it selects the first enrolled course.
  - So the browser **Back** button from Library returns to `/learn?view=tutor`,
    which opens the default course (observed: CS101 welcome, no new row), not the
    open MATH210 session. A reload of `/learn` on a non-first course does the
    same. In the studio, that start-path can begin a check-in on the first course.
  - The in-app paths keep the course: "Ask Clov", the course select, History, and
    view switches. The open session is never lost; it stays in History and in the
    course select.
  - Fix proposal: carry `course` in the loop's URL alongside `view`, synced on
    course change. That changes tutor-view.spec's "nothing else in the URL" pin, so
    it needs your call.
- **G2 (04):** after a reload mid-teach, Goal & plan shows the goal concepts only.
  `GET /plan` requires the plan phase, so there is no read-only plan read.
- **G3 (03):** no original-file URL, page count, preview or byte size on
  `Document`. No Notes collection. No document-to-chat attachment or citation.
  These are omitted rather than faked, and each needs an agreed API extension.
- **G4 (04):**
  - The tutor's material rows have no "open" arrow, because there is no
    original-file URL.
  - The "Course chat / Guided learning" composer labels are omitted (the loop has
    one mode).
  - The knowledge-check "· CONCEPT" tag is omitted (the pose carries no concept
    name).
  - "Review" is labelled "Wrap-up".
- **G5 (02):** the "How sure do you feel?" confidence chips are dropped. There is
  no confidence endpoint, and `/rating` is used only when the server asks for it.
- **G6:** the radio arrow-key pass needs an `mc_reason` fixture item end to end
  (unit-tested only).
- **G7 (pre-existing shell, observed in 05):** any client-side exit from `/learn`
  opens the session-feedback pulse (`SessionFeedbackGlobal`), and the general
  pulse (`FeedbackFlow`) opens after 45 s. On the Learn → Library hop both can
  stack over the page. The new specs stamp their cooldowns. Worth a product look.
- **G8 (pre-existing loop behaviour, observed):** a bare `/learn?view=tutor` shows
  the default course's welcome even when another course has an open session. The
  session can be reached through the course select and History. This is related
  to G1.
- Not run: a live-model pilot, real OCR uploads, DB integration, and real-device
  or screen-reader checks. Fixture coverage shows the UI wiring and server
  contracts behave. It does not prove learning outcomes.

## Refresh: #673 @ ad1b1bd5 (2026-10-19)

Jose pushed 23 commits to #673 after a8abd006. `feat/redesign-base` re-merged
#673 at ad1b1bd5 (04a29a73), and this branch merged that base (537ea4b0). #727
(49c108bf) and main (84e19c3a) had not moved.

**Base (04a29a73).** There were 3 conflicts, none of them with #727:
`seed_local_rich.py`, `test_learning_seed_loop_user.py` and
`test_seed_local_rich.py`. Both sides had merged the same main into #673 and
resolved the #715 seed overlap separately. All three take Jose's resolution. The
result is ad1b1bd5 plus exactly the #727 delta. There are 3 new migrations
(`20261019125459_checklist_budget`, `20261019131339_learning_evidence_transaction`,
`20261019141950_learning_evidence_forward_repair`). Each sorts after every
existing basename, and none is renamed or edited. No lockfile changed.

**Integration (537ea4b0).** 2 files conflicted: `LoopLearn.tsx` (14 hunks) and
`LoopLearn.test.tsx` (2 hunks). The redesign's markup, testids and a11y are
kept. Every #673 behaviour is ported onto that markup:

- **Interrupted turns.** In `runTurn`, the redesign's interrupted-turn marking and
  status-first `loop-recovery-note` now combine with #673's
  `feedbackStarted`/`recoveringFeedback` reconcile and turn epoch. The note still
  appears only for a submission.
- **Busy guard.** `sessionTransitionBusy` (hydration, scope, probe, plan, goal,
  close and pending grade) now gates every redesign path to a new session:
  - the studio and tutor-bar `loop-new-session`;
  - `requestNewSession` and its confirmation;
  - `loop-topic-start`, `loop-goal-new-session` and `loop-readonly-new-session`;
  - the tutor welcome.
- **Pending grade.** `loop-pending-grade` and `loop-recover-grade` are rebuilt in
  the redesign style and shared by both views. While a grade is pending,
  `loop-set-goal`, `loop-close-button` and the tutor menu's End session are
  disabled. On the probe screen the teaching-only close control is absent, as
  #673's e2e expects.
- **Pending feedback.** `loop-continue` reads "Retry feedback" in both views.
  `loop-check-me` is disabled and shows the pending copy. Chat, conversation
  seeds and the tutor's Retry wait while the session hydrates
  (`starting`/`scopeLoading`) or a grade is pending.
- **Practice preflight.** `loop-practice-unavailable` is rebuilt on
  `StatusMessage` and the sapling actions; its copy and testids are unchanged.
  The `goal_progress` copy follows #673.
- **Probe recovery.** `ProbePanel` shows a recovered probe's corrective answer when
  no pose survives.

**Adapted tests (selector or mock only; no behaviour assertion was weakened).**

- `LoopLearn.test.tsx`: Jose's `viewport.mobile` mock is merged into the
  redesign's `viewport.compact`, because the two mocks clashed.
- `LoopLearn.test.tsx`, "holds New session until the resumed probe/plan has
  settled" (×2): the click now goes through `loop-new-session-confirm-start`. The
  test also asserts that no dialog opens while loading.
- `e2e/learn-loop.spec.ts`, "rapid New session waits for the resumed probe/plan"
  (×4):
  - The click now goes through the same confirmation, and the no-dialog check is
    added.
  - `loop-goal-summary` is checked with `toContainText("Explore the whole course")`
    and not "Your goal". The redesign's `GoalSummary` renders "Your scope" and the
    scope as separate text, where #673 rendered one string, "Scope: Explore the
    whole course".
- **New tests:** three tutor-view tests in `LoopLearn.tutor.test.tsx` cover
  pending-grade recovery, Retry feedback and the practice notice.
- **Docs:** `frontend-testids.md` documents the new ids.

**Gates on this branch:**

| Gate | Result |
| --- | --- |
| `npm run typecheck` | exit 0 |
| `npm run lint` | exit 0 (0 errors, 19 warnings) |
| `npm test` | **136 files, 1612 passed, 2 skipped** (`LoopLearn.test.tsx` 132 tests, `LoopLearn.tutor.test.tsx` 38) |
| `npm run build:test` | exit 0 |
| Backend, the `ci.yml` command (shared lock venv, no `SAPLING_MODEL_MODE`) | **10336 passed, 243 skipped**, exit 0 |
| `ruff check .` | All checks passed |
| E2E default lane, `npx playwright test --project=chromium` on 537ea4b0 (one flock'd cycle, `e2e.yml` env) | **110 passed, 12 failed, 30 skipped (29.8m)** |
| Oracles | exit 0, `0 finding(s), 0 suppressed` |
| E2E rerun, `e2e/learn-loop.spec.ts`, after the spec adaptation | **23 passed, 1 skipped** (the kill-switch test); oracles 0 findings |

**The 12 E2E failures:**

- **8 are the known #727 failures listed above:** auth-session:32, dashboard:21,
  graph:214, room-public:20, semester-scope:24, study-semester:31 and
  viewport-fit:88/:120.
- **4 were caused by the merge:** learn-loop.spec.ts:431 at probe and plan,
  1440px and 390px. Jose's new spec clicked New session and expected `/close`
  straight away; the redesign confirms first. After the selector adaptation all
  4 pass (rerun above).

Every new #673 browser journey passes under the redesign: learn-grade-recovery
(4 cases), pending-feedback retry/end, practice-unavailable, and stream
completion. tutor-view.spec and redesign-journey.spec pass too.

**For Andres or Jose.** `loop-practice-sources` links to plain `/library`, which
#673's e2e asserts. The redesign's other Library links keep the course
(`libraryHref`, `?course=`). Switching this link is a one-line change, but it
changes Jose's assertion, so it was left as he wrote it.

## Decisions pending for Andres

1. **Phone bottom tab bar** (AS0Yn). This is a shell-wide change and is not
   implemented. Phones keep the FA26 64 px rail, and every surface passed at 390
   and 320 with it.
2. **Learn vs Tutor nav entries.**
   - The Tutor agent's proposal: during the rollout, keep the single "Clov" rail
     entry → `/learn`, and reach the tutor from "Open Clov tutor" in the studio.
   - If two entries are wanted (the wireframes' pencil and tree icons), point them
     at `/learn` and `/learn?view=tutor`, keep both under `hide_tutor`
     (`navFlagForPath('/learn')`), and mark the active one by `view`.
   - No new route or store is needed either way.
3. **`tutor_view` rollout.**
   - The flag is declared in `services/feature_flags.py` (`off` | `on`,
     client-visible) and defaults to off, so production behaviour does not change
     until it is targeted.
   - Suggested order: staff/admin users, then a cohort, then the default.
     `SAPLING_FLAG_TUTOR_VIEW` is the kill switch.
   - Decide whether "Open Clov tutor" should also be offered while the flag is off
     (today it is not).
4. **Ship separately from #727, or together?**
   - The base contains #727. Its 8 (+2 kill-switch) red specs are #727's.
   - Shipping the redesign without #727 means rebasing the chain onto
     `main` + #673. The foundation builds on #727's shell (`fa26/DesignIcon.tsx`,
     `fa26/Navigation.test.tsx`, `ShellFrame.tsx`, the FA26 rail it draws the
     botanical icons into), so that is a real port rather than a cherry-pick.
   - Recommendation: land #727 (with its spec fixes) first, then this branch.
5. **G1 (course in the URL).** Approve the URL contract change, or accept Back and
   reload landing on the default course for now.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01HCPW7RnBaf93YSGFRXKiRA
