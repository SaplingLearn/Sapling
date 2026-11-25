# W0.4 / W5 — self-target dogfood runbook

Owner-run only. This is the one runbook for turning the learning-system flags on **for your own account**. It stops at "ready for self-target dogfood". It never changes `backend/services/feature_flags.py::REGISTRY`, and it never sets a stored `default_variant` or `rollout_percent` for anyone. Class, percentage and everyone come later, as the owner's call (step 6). Background per flag: [flag-rollout.md](flag-rollout.md). Plan: W0.4 / W5 in [alvar-trilogy-implementation-plan.md](alvar-trilogy-implementation-plan.md). PR [#866](https://github.com/SaplingLearn/Sapling/pull/866).

**Re-checked 2026-11-24 against the code** (`feature_flags.py`, `learning/gate.py`, `agents/_providers.py`, `tests/evals/floors.py --check`).

## Where things stand

Every flag below is `off` | `on`, ships off (no migration seeds a stored row, so an unconfigured flag answers `off`), and has the env kill switch `SAPLING_FLAG_<KEY>=off`. "Loop-gated" means the flag is in `learning/gate.py::LOOP_FLAGS`: it acts only where `learning_loop` is on for the same student, and `LEARNING_LOOP_ENABLED=false` turns it off too.

| Step | Flag | Client-visible | Loop-gated | Ready for self-target? |
|---|---|---|---|---|
| 0 | `learning_loop` | yes | (master) | **Yes**, once the three E2E lanes are re-run on the current tip (handoff B). Note the `check_items` re-record below. |
| 1a | `quiz_concept_plan` | yes | yes | **Yes** — reads only |
| 1b | `quiz_results_routing` | no | yes | **Yes** — reads only |
| 1c | `item_reports` | yes | yes | **Yes**, once a named staff owner checks the check-items queue daily |
| 1d | `next_probe_hint` | no | yes | **Yes** — no prompt change, never mastery |
| 2a | `segment_prequestion` | no | yes | **Yes** — `<slot>__flags` recorded; floors pass |
| 2b | `self_explanation_prompts` | no | yes | **Yes** — same `__flags` datasets |
| 3 | `loop_tutor_v2` | no | yes | **No — blocked.** `__v2` floors fail `floors.py --check`; see step 3 |
| 4 | W5.E3–E4 pack | no | yes | Partly; see [W5.E2–E4 readiness](#w5e2e4-readiness) |
| — | `crisis_support` | no | **no** | **No** — owner copy review first; see [Crisis copy review](#crisis-copy-review-before-broad-crisis_support) |

Two facts the older text of this page got wrong:

- **The `__v2` floors do not hold.** `cd backend && venv/bin/python tests/evals/floors.py --check` reports 10 problems, all `__v2`. The committed run logs (`tests/evals/runs/loop_tutor_v2_2026-11-24.jsonl`, `misconception_confront_v2_2026-11-24.jsonl`) show safety gates below the hand-set floor of 1.0 in at least one of three runs: `loop_tutor__v2` RawAnswerLeak / ServedAnswerLeak / SycophancyResists 0.9; `loop_tutor_lite__v2` SycophancyResists 0.9; `loop_tutor_deep__v2` ServedNoReveal 0.9; `misconception_confront__loop_tutor__v2` Confronts and FeedbackNeverEndsInAnswer 0.875; `misconception_confront__loop_tutor_deep__v2` Confronts 0.875. `tests/test_eval_floors.py` fails for the same reason, so the backend suite and the Evals workflow are red on the PR until this is fixed.
- **`LOOP_SLOTS_PENDING_CLAUDE_EVAL` being empty does not mean every loop path is evaluated.** The set and the A128 slot guard (`system.unevaluated_slot`, the admin report's `slot_warnings`) track model **slots**. They know nothing of the `__v2` variant, the `__flags` paths, or a dataset whose floor is below its contract. An empty set today overstates readiness. (Follow-up for the lead; no code change made here.)

## Before you start (once)

1. **The code is deployed.** #866 merged and running on staging (`main`). Dogfood on staging first. Prod only after a promote, and only once the owner's prod-deploy hold is lifted.
2. **Admin with a recent sign-in.** Adding or removing a target needs `require_admin_recent`; sign in again if the Flags tab refuses.
3. **Your user id.** `GET /api/auth/me` → `id` (`user_<google id>`).
4. **Nothing is forced.** Admin → Flags: the `learning_loop` row shows no env override and no "forced" state. `GET /api/admin/flags/learning_loop/explain?user_id=<you>` answers `off`, step `default`. On the backend service, `LEARNING_LOOP_ENABLED` is unset (or a true value) and no `SAPLING_FLAG_LEARNING_LOOP` is set.
5. **A course to study.** Enrolled, with uploads. Check items are drafted on uploads made while the loop is on for the uploader, so either use a course that already has items, or upload one document after step 0.
6. **A baseline.** Save the admin learning-loop report for the last 7 days (`GET /api/admin/analytics/learning-loop`, Admin → Analytics → Learning loop), and run the event count below once.

```sql
-- learning-loop events for one student, last 7 days (Supabase SQL editor, staging)
select event_type, count(*) from events
where user_id = '<you>' and created_at > now() - interval '7 days'
  and (event_type like 'learn.%' or event_type like 'zpd.%' or event_type like 'quiz.%'
       or event_type = 'system.unevaluated_slot')
group by 1 order by 2 desc;
```

## How every step works

| Action | Admin → Flags | Admin API |
|---|---|---|
| Turn on for yourself | Flag row → add a user rule: your account, `on` | `PUT /api/admin/flags/<key>/targets` with `{"target_type":"user","target_id":"<you>","variant":"on"}` |
| Check what you get | Flag row → Check a student | `GET /api/admin/flags/<key>/explain?user_id=<you>` → `on`, step `user`. Step `requires` means `learning_loop` is off for you; step `kill_switch` means `LEARNING_LOOP_ENABLED=false` |
| **Flag drill** (roll back) | Remove your rule | `DELETE /api/admin/flags/<key>/targets/user/<you>` → explain answers `off` |
| **Env drill** (staging only) | — | Set `SAPLING_FLAG_<KEY>=off` on the backend service and redeploy. Explain → step `env_override`; the Flags row shows it forced. Remove the variable, redeploy, explain → `on`, step `user` again |

A change reaches the server within 30 s (the flag snapshot TTL). A client-visible flag needs a page reload. Never use `PATCH /api/admin/flags/<key>` in this runbook: that is the stored default and the rollout.

Turn flags on one at a time. Give each at least one real study session, ideally across two days, before the next.

## Step 0 — `learning_loop` (yourself)

- **Turn on:** your user rule on `learning_loop`.
- **Try:** Tutor (`/learn`): start a session on the course; take the probe, approve the plan, get taught, answer checks, wrap up. Study: the review queue and the retention check. Dashboard: Learn next. Upload one document and see its check items drafted.
- **Watch:**
  - Admin learning-loop report: `served_reveals` must stay 0; `caught_leaks` and `unscanned_turns` low; `ceiling_compliance`; `slot_warnings` must be `[]` (and see the caveat above: it does not cover `__v2`).
  - Events: `zpd.leak` (category `error`) and `system.unevaluated_slot` should not appear.
  - Backend log: no 5xx on `/api/learn/loop/*`; no check-item drafting failures on your upload.
- **Kill-switch drill:**
  1. Flag drill → `/learn` is the legacy tutor; `/api/learn/loop/*` answers 404.
  2. Env drill A: `SAPLING_FLAG_LEARNING_LOOP=off` → same as above for everyone; your rule stays stored.
  3. Env drill B: `LEARNING_LOOP_ENABLED=false` (restart; `config.py` reads it at boot) → explain answers step `kill_switch` for `learning_loop` **and** every loop-gated flag; loop routes 404. Unset it and restart.
- **Go:** several sessions with no served reveal, no 5xx, no grade you dispute, `slot_warnings` empty, and all three drills behaving as written.
- **No-go:** any `served_reveals > 0`, a `zpd.leak` you can tie to a served turn, a wrong grade, or a drill that does not take effect. Remove your rule and file it.
- **Open item:** the default `check_items` dataset recorded `McOptionsValid` 0.875 against its A37 contract of 1.0 (2 of 3 runs drew option-less `mc_reason` drafts). The drafter now retries such an output (`9bd4bd9a`), but the three-run re-record on that code is still owed. Fine for self-target; required before a class.

## Step 1 — read-only flags (yourself)

Each needs step 0 on for you.

### 1a. `quiz_concept_plan` (client-visible)
- **Try:** Quiz home on the course. Proposals come in this order: FSRS-due reviews, then open misconceptions, then concepts whose prerequisites are proficient. "Review everything due" means due by FSRS. Direct read: `GET /api/quiz/plan?user_id=<you>&course_id=<course>`.
- **Watch:** quiz starts; the backend log for plan read errors. A failed read falls back silently to the old tier ranking, so the log is the only sign.
- **Go:** the order matches what you know is due; no plan errors. **No-go:** plan errors, or a proposal for a concept you have never met ahead of a due review.

### 1b. `quiz_results_routing`
- **Try:** finish a quiz. Results show "Your skill meters", what is due, and Next: Due on Study / Continue learning / See on your map.
- **Watch:** results-page errors; that each Next link lands on the right page. Note the copy issue in [copy-pass-2026-11-24.md](copy-pass-2026-11-24.md) section G (a percent mastery line and "Your mastery didn't change" beside the skill meters).
- **Go:** the block reads true to the quiz you took.

### 1c. `item_reports` (client-visible)
- **Before:** name the staff member who checks Admin → Check items (`/api/admin/check-items/queue`, `/stats`) daily.
- **Try:** report one loop check question ("Report this question" on the check card or Study's review queue).
- **Watch:** `learn.check_item_reported` events; queue length and how long items stay held. Two reporters hold an item for the whole course; your one report excludes it for you only.
- **Drill note:** turning the flag off hides the control. Reports already made keep excluding their items. Staff approve to release.
- **Go:** the report lands in the queue and staff can approve or retire it.

### 1d. `next_probe_hint`
- **Try:** answer checks with reason-before-submit text. Since W2.4b the flag opens your sealed reasoning and may prefer an eligible next check whose stem overlaps it.
- **Watch:** no event of its own. Activation must still respect exclusions and post-test reserves. It never writes mastery (`test_inv_32_*`).
- **Go:** nothing odd. "No visible change" is an acceptable result.

## Step 2 — prompt children (yourself)

Each sends a changed tutor prompt on one path. Their `<slot>__flags` datasets are recorded and pass `floors.py --check`.

### 2a. `segment_prequestion`
- **Try:** reach a new concept in a loop session. You get one ungraded guess, then the answer and an explanation that starts from your guess.
- **Watch:** `learn.prequestion` events by `status` and `reason`. Many `pool_for_checks` skips mean the course needs more items.
- **Go:** never graded, never moves mastery, skip reasons make sense.

```sql
select payload->>'status' status, payload->>'reason' reason, count(*) from events
where event_type = 'learn.prequestion' and user_id = '<you>'
group by 1, 2 order by 3 desc;
```

### 2b. `self_explanation_prompts`
- **Try:** after a worked example, a shown solution or a first unaided correct answer, the question becomes "why does this follow?" with its own reply box. Reply once.
- **Watch:** `learn.self_explanation` events; the admin report's `self_explanation` block (reply rate, next-item success).
- **Go:** the next turn acknowledges your reply briefly; nothing is graded.

## Step 3 — `loop_tutor_v2` (yourself only) — BLOCKED

Not ready, even for self-target. The `__v2` served-gate floors fail (see "Where things stand"). Do not add a rule until all of these are true:

1. The lead applies the prepared prompt fix (`.v2_prompt_fix.patch` in the #866 worktree; it moves `V2_PROMPT_VERSION` from `ca02dcf9e63b` to `683e0486fd8f`).
2. Three fresh Claude recordings under `LOOP_EVAL_VARIANT=v2` for `loop_tutor_lite`, `loop_tutor`, `loop_tutor_deep` and both `misconception_confront` tiers, with `SAPLING_EVAL_RUNS_LOG` set. This needs a working `ANTHROPIC_API_KEY`.
3. `floors.py --log … --runs 3` writes the floors, and `floors.py --check` exits 0 with RawAnswerLeak, ServedAnswerLeak, ServedNoReveal, SycophancyResists, Confronts and FeedbackNeverEndsInAnswer at **1.0** in all three runs.
4. The A121 journey in `e2e/learn-loop.spec.ts` stays green in the default lane.

Then: your own rule only. **Population HOLD** while `LOOP_ROUTABLE_TIERS = {deep}` (`agents/loop_tutor.py`).

- **Watch:** `zpd.leak`; `served_reveals`; tutor turn retries; session wrap-up ratings.
- **Drill:** flag drill and `SAPLING_FLAG_LOOP_TUTOR_V2=off`. Either returns the tutor request to byte-identical pre-A121.

## Step 4 — W5.E3–E4 pack (yourself or a test class only)

Only the flags marked ready in [W5.E2–E4 readiness](#w5e2e4-readiness). Two cautions:

- The drafting flags (`varied_isomorphs`, `multi_concept_items`, `upload_prereq_edges`) are read for the **uploader**. Items are course assets, so your uploads change what classmates in that course are served. Dogfood them on a test course.
- `upload_prereq_edges`: edges already written stay when the flag goes off.

Per-flag watch lists: [flag-rollout.md](flag-rollout.md).

## Ready for self-target dogfood

This runbook ends here. Today that means steps 0–2 on your own account, with the three E2E lanes re-run on the current tip. Steps 3 and most of 4 wait on evals.

## Step 6 — class → % → default (not part of this runbook)

The owner's decision, after self-target dogfood is clean. Gates in [flag-rollout.md](flag-rollout.md): class targets first, then `rollout_percent`, and only then a stored `default_variant: "on"` through Admin → Flags. Never by editing `REGISTRY`. Before any class: the `check_items` re-record (step 0), and the three E2E lanes green on the deployed commit.

## W5.E2–E4 readiness

"Evals" means recorded live on Claude, three runs, floors passing. "E2E" means a journey in the default lane (function mode). Status as of 2026-11-24.

| Phase | Flag | Code | Evals | E2E | Blockers |
|---|---|---|---|---|---|
| E2 | `segment_prequestion` | ready | `<slot>__flags` recorded, floors pass | `learn-loop.spec.ts` A138 | none for self-target |
| E2 | `self_explanation_prompts` | ready | same `__flags` datasets | `learn-loop.spec.ts` A139 | none for self-target |
| E2 | `loop_tutor_v2` | ready; prompt fix prepared, not applied | **fail**: `__v2` floors below 1.0 (step 3) | `learn-loop.spec.ts` A121 | prompt fix + 3-run Claude re-record (needs a working Anthropic key); population HOLD while `LOOP_ROUTABLE_TIERS={deep}` |
| E3 | `quiz_planned_questions` | ready | **not recorded**: `quiz_generation_planned` has no cassettes and is not in `run_all.py` | `quiz-learning.spec.ts` | live record + baseline |
| E3 | `quiz_item_gates` | ready | **not recorded**: `quiz_item_gates` live smoke has no cassettes | `quiz-learning.spec.ts` | live smoke + a measured cost (two to three extra calls per quiz on `quiz_check`, Sonnet) |
| E3 | `quiz_misconceptions` | ready | no own dataset; acts only on questions made with both flags above | `quiz-learning.spec.ts` ("Sure" wrong answer) | both E3 flags above on for the same students |
| E4 | `varied_isomorphs` | ready | `check_items_varied` recorded ×3; floors pass (SurfacesVary floor 0.667) | `learn-varied-practice.spec.ts` | none for a test course; see the `check_items` note. The option-less `mc_reason` retry (`9bd4bd9a`) is on the default drafter only, not the varied one |
| E4 | `multi_concept_items` | ready | `check_items_combo` recorded ×3; floors pass | `learn-varied-practice.spec.ts` | none for a test course |
| E4 | `upload_prereq_edges` | ready | **not recorded**: `concept_extraction__relations` has no cassettes | `upload.spec.ts` (A118) | live record; a manual look at the edges on a few real uploads |

## Crisis copy review (before broad `crisis_support`)

`crisis_support` is **not** loop-gated. It covers the legacy tutor, notes and flashcards as well as the loop (`docs/safety/crisis-support.md`, "Surfaces covered"). Keep it off for everyone until this review is signed.

**What copy, and where it lives**

| Copy | Where |
|---|---|
| The card: `TITLE`, `INTRO`, `RESOURCES_HEADING`, the resources (`LIFELINE_988`, `CRISIS_TEXT_LINE`, `EMERGENCY`, `INTERNATIONAL`), `CLOSING`, `DISMISS_LABEL` ("Back to studying") | `backend/services/crisis_support_copy.py` |
| Resource order | `resources()` in the same file |
| Campus counseling | `DEFAULT_CAMPUS_COUNSELING` (no phone number on purpose) and `CAMPUS_COUNSELING` (empty today) in the same file |
| The model-side backstop, **live whatever the flag says** | `MODEL_SAFETY_PROMPT` in the same file, part of the chat tutor, note chat and loop tutor system prompts. A change to it changes those prompts' hashes, so their eval cassettes must be re-recorded |
| What triggers the card | the phrase lists and guards in `backend/services/crisis_detection.py` |
| The card's frame (no strings of its own) | `frontend/src/components/safety/CrisisSupportCard.tsx` |

**Review checklist**

- [ ] Read the copy file top to bottom. The card renders nothing else.
- [ ] Check the US resources are current: 988 (call or text), Crisis Text Line (text HOME to 741741), 911, findahelpline.com.
- [ ] Decide the resource order.
- [ ] Add the school's counseling service to `CAMPUS_COUNSELING`, phone and URL checked on the school's own site, or accept the generic default. A wrong number is worse than none. Decide whether `courses.school_id` gets populated (until then everyone sees the default).
- [ ] Read `MODEL_SAFETY_PROMPT` as student-facing text: the model may say it.
- [ ] Read the phrase lists. Decide the first-person rule and the hyperbole that still matches ("I want to die lol").
- [ ] Decide the surfaces, including the open question of quiz answers (not screened today).
- [ ] Name who reads `safety.crisis_support_shown` and how often. Nothing alerts anyone today.
- [ ] Bump `COPY_VERSION`, set `REVIEW_STATUS = "approved"`, and update `test_the_copy_is_pending_owner_review` (`backend/tests/test_crisis_support_routes.py`) in the same PR.

**Who signs off**

- **Required:** the owner (Andres), by approving the PR that sets `REVIEW_STATUS = "approved"`.
- **Recommended second reader:** someone with counseling or student-wellbeing background, for the copy and the phrase lists. Record their name in the PR.
- **The campus entry:** whoever adds it confirms the number against the school's own page, and says so in the PR.

**After sign-off:** staff (or self) target first, check every surface with a test account using the phrases in `test_crisis_support_routes.py`, confirm a `safety.crisis_support_shown` row appears, add the crisis E2E journey and its a11y scan, then the owner decides the default. Kill switch: `SAPLING_FLAG_CRISIS_SUPPORT=off`.

## The three E2E lanes

Required on the commit you dogfood, and before any class rollout. Export lane env in the **same shell** that boots the stack and runs Playwright (`frontend/e2e/support/lane.ts`; `global-setup.ts` asserts agreement). Never put `LEARNING_LOOP_ENABLED` in `backend/.env` (`scripts/e2e-up.sh` refuses). Never on `:3000`/`:5000`.

```sh
# from the repo root; cycles pick a free slot
export SAPLING_MODEL_MODE=function
export SAPLING_FUNCTION_HANDLERS=agents.function_handlers_e2e

# Default (e2e-up sets SAPLING_FLAG_LEARNING_LOOP=on)
unset LEARNING_LOOP_ENABLED SAPLING_FLAG_LEARNING_LOOP
scripts/e2e-cycle.sh -- bash -c 'cd frontend && npx playwright test e2e/learn-loop.spec.ts e2e/tutor.spec.ts --reporter=list'

# Kill-switch
LEARNING_LOOP_ENABLED=false scripts/e2e-cycle.sh -- bash -c 'cd frontend && npx playwright test e2e/learn-loop.spec.ts e2e/tutor.spec.ts --reporter=list'

# Flag-off (production's default)
unset LEARNING_LOOP_ENABLED
SAPLING_FLAG_LEARNING_LOOP=off scripts/e2e-cycle.sh -- bash -c 'cd frontend && npx playwright test e2e/learn-loop.spec.ts e2e/tutor.spec.ts --reporter=list'
```

Use `set -o pipefail` if you tee the log: plain `| tee` masks a Playwright failure. The full suite is `make e2e` with the same exports. CI runs the matrix on `main` (`.github/workflows/e2e.yml`, `lane: [default, kill-switch, flag-off]`).

**Last measured (W0.5 head, 2026-11-24; the tip has moved since):** default 31 passed / 7 skipped; kill-switch 6 / 32; flag-off 5 / 33 (first flag-off pass hit a mid-suite re-seed 503).

## What this runbook does not do

- Turn any flag on for anyone but you.
- Change `REGISTRY`, a stored default, or a rollout percentage.
- Turn on `loop_tutor_v2` before its re-record passes, or for a population while `LOOP_ROUTABLE_TIERS={deep}`.
- Turn on `crisis_support` before the copy is signed.
