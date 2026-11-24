# Day 1–2 plan compliance audit

**Against:** [`alvar-trilogy-implementation-plan.md`](alvar-trilogy-implementation-plan.md)  
**Date:** 2026-11-23  
**Method:** Re-read acceptance rows; inspect landed code/docs; run focused unit tests. Not a substitute for W0 Claude evals or E2E.

Legend: **PASS** = acceptance met for this slice · **PARTIAL** = directionally correct, plan acceptance incomplete · **FAIL** = contradicts plan · **SPIKE** = docs only by design · **BLOCKED** = needs W0/spend

---

## Scoreboard

| Track | Verdict | vs plan acceptance |
|---|---|---|
| W6 docs | **PASS** | Adopted/narrowed/refused table + glossary Alvar V1 + README pointer |
| W1.1 Safe-anchor | **PARTIAL** | Shared `_LOOP_SYSTEM_PROMPT` all tiers + pins; cases `teach_safe_anchor_novice_open` / `teach_safe_anchor_lecture_says` in `PEDAGOGY_CASES` (cassette record still W0) |
| W1.2 Motivated derivation | **PARTIAL** | Prompt + teach/band copy + pins; case `teach_motivated_step_develop` in `PEDAGOGY_CASES` (cassette record still W0) |
| W1.3 Generative core | **PARTIAL** | `practice_formats` + pins; case `teach_generative_core_close` in `PEDAGOGY_CASES`; **no** E2E close-beat journey; Claude cassette still W0 |
| W1.4 Worked-first align | **PASS** | `NOVICE_WORKED_FIRST_FORMAT` + novice/develop/profic bands |
| W1.5 Docs pedagogy | **PASS** | Glossary “Alvar V1 pedagogy” + amendments refused “feels obvious” (not a new §13 row — guide acceptance met) |
| W0 readiness runbook | **PASS** | Plan §W0 readiness present |
| W0.1–W0.3 Claude evals | **FAIL** (blocked on key) | Day-3 lite record attempt: key present but Anthropic **401 invalid x-api-key**; no cassettes written; 7 slots still pending |
| W0.4–W0.5 Flag rollout | **FAIL** (correctly deferred) | Not rolled out; no PR test-plan proof of 3 E2E lanes for this wave |
| W8.6 learner_next | **PASS** | Pure + IO; quiz `rank_concepts` through helper; tests green |
| W8.7 Dashboard Learn-next / retention | **PASS** | Flag-on Learn-next → `getStudyNext` → `learner_next` (`recommendationsFromNext`); flag-off → graph `/recommendations`. A126 badge stays `GET /posttest/due` via `RetentionDueContext` (not FSRS due). Unit: `learnerNext.test`, Dashboard characterize W8.7 cases, `RetentionDueContext.test`, `api.loop` `fetchRetentionDue`; backend `test_study_next` / `test_learner_next`. **gap:** Flag-on E2E |
| W8.3 Hub ← next | **PASS** (slice) | `/next` → Focus/Due; Due Reviews Flashcards + Quiz (`dueReviewsQuizHref`); flag-off unchanged; **gap:** no E2E |
| W8.1 Library handoff | **PASS** | Tree `?course=` + Quiz concept-aware; list stamps `concept_notes[].node_id`; upload resolves via graph; **gap:** no E2E |
| W8.2 Tree actions | **PARTIAL** | Teach/Quiz/Cards/Guide menu; **gaps:** Guide ≠ concept-scoped; Cards/Guide lack E2E |
| W3.1 Plan deps | **PASS** (slice) | API + PlanPanel + SessionPanel (`PlanDeps` / `session-plan-deps`); **gap:** E2E stack assert still optional |
| W3.2 Covered/understood | **PASS** (slice) | `practicedIds` outline + mastery fill; legend “Practiced”; from `learnerState` keys |
| W2.3 Reason-before-submit | **PASS** (slice) | Encrypted nest + UI + route/unit + `test_inv_31_reason_before_submit_never_writes_mastery` + Playwright stubs in learn-loop; **gap:** full E2E stack not yet executed |
| W2.1–W2.2 Flag enables | **BLOCKED** | Correctly not enabled pre-W0 |
| W7 port map + D1 | **PASS** | `quiz-shell-port-map.md` + `w7-design-decisions.md` |
| W7.D2 / W7.D3 | **FAIL** | Hub/Guide/Settings design + launcher MATH151 — not started |
| W7.1 Shell chrome | **PASS** (slice) | Focus session + SessionTop + forest progress/Check/pager (course accent = pill only); Hint/Skip slots unwired; no E2E — acceptable for W7.1 first slice |
| W4 visuals | **SPIKE** | Spike only; first build after W0 = grounded-cite |
| Graded-only belief | **PASS** | No free-text→mastery path in W2.3/`check_reason`; W1 stop = graded check |

---

## Orchestration integrity

```text
learner model (graded only)
    → learner_next (due | misconceptions | ready)
        → Quiz plan (capped)     ✅ W8.6
        → Study Hub Focus        ✅ W8.3
        → Dashboard Learn-next   ✅ W8.7 (flag-on)
        → Learn plan + edges     ✅ W3.1 API/UI
    → A126 retention badge       ✅ posttest/due only (not FSRS)
    → Teach spine W1             ✅ prompts; ⚠️ evals missing
    → Sensing W2.3               ✅ sealed, not evidence
    → Visible spine W8.1/W8.2    ✅ deep links
    → Quiz chrome W7.1           ⚠️ partial vs decisions
    → Flags / Claude trust       ❌ W0 still open
```

**No second brain detected:** Tree/Library/Hub/Dashboard Learn-next reuse deep links + `learner_next`; Quiz plan still caps on its path; retention badge is post-test due, not FSRS.

---

## Must-fix before claiming “plan on track”

1. **W0 Claude re-record** (unblocks flags + clears W1/W1.3 prompt-hash drift).  
2. Add **eval cases** `teach_safe_anchor_*` / `teach_motivated_step_*` / generative-core (plan W1 acceptance) — **cases exist** at `teach_safe_anchor_novice_open`, `teach_safe_anchor_lecture_says`, `teach_motivated_step_develop`, `teach_generative_core_close` in `tests/evals/loop_tutor.py` (`PEDAGOGY_CASES`, namespace `<slot>__pedagogy`). Judges are listable/unit-scorable without cassettes; **W0 must still record** (`LOOP_EVAL_PEDAGOGY=1 SAPLING_EVAL_MODE=record`) before CI scores live Claude turns.  

3. **W7.1** follow-up: confirm session chrome CTAs/progress use brand forest per `w7-design-decisions.md`; finish or explicitly defer 64px bar / hint-skip placeholders.  
4. E2E: PlanPanel deps; generative-core close; reason-before-submit; Hub next (when flags dogfood).  
5. Do **not** enable W5 flags until (1) is green.

## Independent re-audits

| Auditor | Scope | Outcome |
|---|---|---|
| W1 pedagogy | W1.1–W1.5 + graded-only / STRUCTURED TURN / flag defaults | Confirms PARTIAL/PASS table above; flags correctly off-first |
| W6 / W8.6 / W3 | W6, W8.6, W3.1, W3.2 | W6/W8.6 PASS; W3.1 PARTIAL (no SessionPanel/E2E); W3.2 spike-only |
| W0 / W2.3 / W7 / W4 | Foundation + sensing + quiz shell + visuals | W0 FAIL (not recorded); W2.3 PARTIAL (no E2E); W7.1 PARTIAL; W7.D2–D3 FAIL; W4 spike PASS |
| W8 spine + in-flight | W8.1–W8.3, W2.3, W7.1 | All landed in tree; acceptance PARTIAL except W2.3 code/invariants OK; graded-only belief holds |
| W8.7 verify (Day 7) | Dashboard Learn-next + A126 vs FSRS | **PASS** — code/tests as scoreboard; no code drift; checklist marked done |

---

## Focused tests run (this audit)

Backend (subset): `test_learner_next`, `test_learning_check_reason`, `test_study_next`, generative-core policy pin, W2.3 route invariant, plan `prereq_edges` — see shell output in session.  
Frontend: `PlanPanel.test`, `treeNodeActions.test`, `libraryNext.test`, `StudyHub.test` — see shell output.  
W8.7 verify (2026-11-23): frontend `learnerNext.test` + Dashboard characterize (flag-on `getStudyNext` / flag-off legacy) + `RetentionDueContext.test` + `api.loop` `fetchRetentionDue` (93); backend `test_study_next` + `test_learner_next` (11).
