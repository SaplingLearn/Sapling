# HANDOFF-08 — probe-planner

Written by the session that executed `PKG-08-probe-planner.md`. Read by every later package that depends on 08. Keep every heading, even if the answer is "none".

**Status: done on `feat/learning-loop-08-probe-planner`; awaiting the coordinator** (LEDGER is the coordinator's: no row is written here). `feat/learning-loop` (PKG-07) was merged in first (ed668b24); every PKG-08 route binds to PKG-07's post-merge names (`_gate`, `_session_scope`, `_request_id`, `_RATE_LIMITED`, `_update_loop_state`, `_is_idk_phrase`, `_band_for`, `_pose_payload`, `_agent_turn_or_http_error`, the A52 grading-claim discipline). No push, no PR, no E2E run (session override).

## What changed

A loop session now opens with a *probe* and moves into a *plan* the student approves, behind the gate. `learning/probe.py` (expected success through the channel likelihood, the probe-band item picker with per-skill and session caps, the stop rule, the session-wide novice floor) and `learning/planner.py` (outer fringe over oriented prerequisite edges; `plan()` in `PLAN_ORDER` with the coupled cap) are pure (`test_inv_16`). Four routes join PKG-07's router at `/api/learn/loop`: `POST /probe/next`, `POST /probe/answer`, `GET /plan`, `POST /plan/approve`. `/probe/next` fixes the skill set on first call (the outer fringe, capped at `PROBE_MAX_SKILLS`), ends at once with `no_check_items: true` for a course without items (A23/A26), and never serves a concept's post-test reserve (A23), an item whose answer the student has been shown (`revealed_hashes`), an `unavailable` one, or one without a final answer (A34); a posed item is served again until answered. `/probe/answer` grades through `grade_answer` only (A16; no tutor turn) under a grading claim on the posed item (the A52 discipline), writes the one Evidence dict through ONE `flush_pending`, re-reads the decayed `p_known`, and records the observation; a refusal is read before `unavailable` and its `CHECK_REFUSALS_AS_IDK`-th occurrence on the same item is graded as idk (A33); `unavailable` (and a withdrawn item) counts as not asked (invariant 28). `GET /plan` proposes due reviews → new fringe material → proficient siblings and stores the proposal; `/plan/approve` stores the student's subset/order, points PKG-07's activation at it (`plan.cursor` 0, `concept`, counters 0; A27) and moves to `teach`. No PKG-08 route reads the tutor budget or counts a tutor call (A20, pinned in source); `/probe/answer` carries the rate limit. `learn.probe_done` and `learn.plan_approved` are in the taxonomy and emitted.

## Symbols added

- `backend/learning/probe.py`: `ProbeItem` (Protocol: `id, node_id, format, difficulty, question_hash`), `ProbeObservation` (TypedDict: `node_id, question_hash, difficulty, channel, correct, idk, p_after`), `expected_success(p_known, item_difficulty, channel) -> float` (KeyError on an unknown channel), `next_probe_item(states, items, asked_hashes, *, channel_for_format) -> ProbeItem | None`, `novice_floor(history) -> bool`, `probe_done(history, *, skills=None) -> bool`.
- `backend/learning/planner.py`: `PlanConcept(node_id, kind: "review"|"new"|"sibling")`, `Plan(concepts, order=PLAN_ORDER)`, `outer_fringe(states, prereq_edges) -> list[str]`, `plan(fringe, due_reviews, siblings_fn, goal_filter, *, proficient=frozenset(), max_concepts=PLAN_MAX_CONCEPTS, max_coupled=PLAN_MAX_COUPLED) -> Plan`.
- `backend/learning/params.py` (PKG-01 file): `PROBE_DIFFICULTY_SHIFT`, `NOVICE_FLOOR_IDK`, `PROBE_EASIEST_DIFFICULTY`, `PROBE_MAX_SKILLS`.
- `backend/services/events_service.py::EVENT_TAXONOMY` + `learn.probe_done`, `learn.plan_approved` (pinned in `tests/test_event_capture_seams.py`).
- `backend/models/__init__.py`: `ProbeNextBody{session_id, user_id}`, `ProbeAnswerBody{session_id, user_id, question_hash, answer, option, reason, idk}` (`answer`/`option`/`reason` `max_length=GRADER_ANSWER_MAX_CHARS` → 422), `PlanApproveBody{session_id, user_id, concept_ids (min_length 1)}` — no `course_id`, no `model_pref`.
- `backend/routes/learn_loop.py`:
  - Routes: `probe_next` `POST /probe/next`; `probe_answer` `POST /probe/answer` (A20 rate limit inline after the gate: `ai_budget.enforce_rate_limit_for`); `plan_get` `GET /plan?session_id=&user_id=`; `plan_approve` `POST /plan/approve`.
  - Writer: `_probe_submission(body, request, *, loop_on) -> dict` — invariant 26's probe writer (grade_answer → ONE flush_pending under the claim).
  - Seams: `_BoundItem(item, node_id)` (frozen; delegates every other attribute to the `CheckItem`; `.item` is what `grade_answer` takes), `_probe_items(user_id, course_id, node_ids) -> list[_BoundItem]` (PKG-08's node → `concept_key` → items resolver, the inverse of PKG-07's `_node_for_item`: one `graph_nodes` read + one `items_for_concepts` read; unfiltered), `_probe_course_has_items(course_id)`, `_plan_states(user_id, course_id) -> {node_id: decayed p_known}` (BKT_L0 without a row), `_plan_prereq_edges(user_id, node_ids)` (oriented by `EDGE_PREREQ_SOURCE_IS_PREREQ`), `_plan_node_names(user_id, node_ids)`, `_plan_due_reviews(user_id, node_ids, *, now=None)` (`fsrs_due_at ≤ now` → `order_due` → `budget_select`).
  - Fix round: `_update_if_changed(session_id, doc, mutate)`, `_probe_plan_read_limit(user_id)`; `learning.probe.next_probe_item(..., asked_per_node=None)`; `learning.planner._components` (iterative Tarjan) behind the SCC-aware `outer_fringe`; PKG-07 reopen: `_loop_phase` (moved), `_TEACHING_CLOSED`, `_require_teaching(state)`, `_teaching_open(session_id, user_id)`, `/status` `loop_phase`.
  - Helpers: `_loop_phase(doc)`, `_require_phase(doc, phase)` (409 `"phase is <phase>"`), `_probe_doc(doc)`, `_probe_done_payload`, `_emit_probe_done`, `_claim_live`, `_on_posed`, `_under_probe_claim`, `_release`, `_not_asked`, `_PROBE_NOT_POSED = "not the posed probe item"`.
- `sessions.loop_state` keys (ids, hashes, numbers, booleans only): top-level `phase` (`probe` → `plan` → `teach`; a missing key reads `probe` unless `plan.approved` is set); `probe = {skills, history: [ProbeObservation], current: {check_item_id, question_hash, node_id, difficulty, channel, grading_claim?, grading_claim_at?} | null, unavailable: [qh], refusals: {qh: n}}`; `plan = {proposed, proposed_kinds, approved, cursor}` (+ PKG-07's `done`), top-level `concept`, `teach_turns`, `concept_checks` at approve. PKG-07's top-level `current` / `steps` are never written by PKG-08.
- Response shapes (PKG-13 builds against these):
  - `/probe/next` → `{"done": false, "check_item_id", "question_hash", "node_id", "format", "difficulty", "prompt", "options": [{"letter", "text"}] | null}` | `{"done": true, "phase": "plan"}` | `{"done": true, "phase": "plan", "no_check_items": true}`.
  - `/probe/answer` → `{"graded": true, "correct", "p_known", "probe_done", "novice_floor", "reference_answer"?}` (`reference_answer` only when not correct — a wrong answer or an idk) | `{"graded": false, "unavailable": true}` | `{"graded": false, "refused": true}` | `{"graded": false, "recorded": false}` (claim lost before the write); 409 `"not the posed probe item"` / `"already graded"` / `"loop state changed, retry"` / `"phase is …"`; 422 over-long body; 429 rate limit.
  - `GET /plan` → `{"concepts": [{node_id, concept_name, kind, p_known}], "order": list(PLAN_ORDER)}` | `{"concepts": [], "order", "empty": true, "phase": "teach"}` (nothing to plan: the session moves to teach with `plan.approved = []`).
  - `/probe/next`, `GET /plan`: 429 `"too many requests"` (+ `Retry-After`) past `PROBE_PLAN_READS_PER_MIN`; PKG-07's teaching routes: 409 `"finish the probe first"` / `"finish the plan first"`; `/status` `loop_phase`.
  - `/plan/approve` → `{"phase": "teach", "concept_ids": [...]}`; 422 empty / duplicate / outside the proposal.
- Events: `learn.probe_done {items, misses, novice_floor, skills}`, `learn.plan_approved {concept_ids, n_reviews_first}` (category `usage`, `request_id` set).
- Tests: `tests/test_learning_probe_planner.py` (92 after the fix round: 28 pure + 64 route cases); `test_inv_16_probe_planner_pure`.

## Constants chosen

- `PROBE_DIFFICULTY_SHIFT = {1: +0.15, 2: 0.0, 3: -0.15}` † (spec §13 A6; no calibrated item parameters, research §Probe) — `learning/params.py`; `test_probe_difficulty_shift_covers_exactly_the_item_difficulties` pins that its keys are `CHECK_ITEM_DIFFICULTIES`.
- `PROBE_PLAN_READS_PER_MIN = 30` † (fix round; per-user limit on /probe/next and GET /plan; spec §13 A55(e)).
- `NOVICE_FLOOR_IDK = 2` † (spec §13 A6; "repeated idk", §3.3).
- `PROBE_EASIEST_DIFFICULTY = min(CHECK_ITEM_DIFFICULTIES)`, `PROBE_MAX_SKILLS = PROBE_SESSION_CAP // PROBE_ITEMS_PER_SKILL_MIN` (derived, = 3).
- `EDGE_PREREQ_SOURCE_IS_PREREQ = True` †verified against: seeds only (`db/seed_local_rich.py`, `db/seed_staging.py` prerequisite edges: source is the prerequisite); unchanged.
- Consumed: `CHECK_REFUSALS_AS_IDK = 2` (PKG-05 reopen), `LOOP_GRADING_CLAIM_STALE_S = 120` † (PKG-07), `BKT_PROFICIENT`, `BKT_L0`, `PLAN_ORDER`, `PLAN_MAX_CONCEPTS`, `PLAN_MAX_COUPLED`, `REVIEW_DAILY_BUDGET_MIN`, `REVIEW_SECONDS_PER_CHECK`, the `PROBE_*` §3.4 rows.
- `CHANNEL_FOR_FORMAT` is PKG-05's, imported from `agents.tools.check` by the route and the tests and passed to `next_probe_item`.

## Deviations from spec

- `PLAN_ORDER` names → the on-disk `("due_reviews", "new_material", "interleaved_siblings")`, not the prompt's `("reviews", "new", "siblings")`; `PlanConcept.kind` stays `review`/`new`/`sibling` (sections keyed by name, so a reorder never mislabels) → the constant already existed (PKG-01).
- `learning/params.py` touched (four names) → PKG-01 reopened (commit 76611adb; HANDOFF-01 Post-hoc).
- `plan(..., proficient=)`, `probe_done(..., skills=)`, `next_probe_item(..., channel_for_format=)` keyword extensions; the coupled rule read as "skip a candidate already sharing a parent with ≥ `max_coupled` chosen new concepts"; the novice floor is session-wide → as the prompt specifies.
- `_load_loop_state` / `_save_loop_state` → PKG-07 (post-A38) has no `_save_loop_state`: every write is `_update_loop_state(session_id, mutate)` (compare-and-set); `_load_loop_state` is PKG-07's own → the prompt predates A38 06(q).
- Evidence: "ONE direct `apply_graph_update` in the handler body" → ONE `flush_pending(deps, course_id)` (PKG-05's sanctioned persister, the path PKG-07 uses) inside `_probe_submission`, which `probe_answer` calls; `inv_26` gains `EVIDENCE_WRITERS += {"_probe_submission"}`, `EVIDENCE_WRITER_CALLERS += {"probe_answer"}` → the prompt allows the flush helper; a direct `{"evidence": …}` payload would be a second persister (`test_no_production_caller_passes_evidence_yet`) and the writer must be callable concurrently to test the claim.
- `/probe/answer` grades under a claim (PKG-07's A52 discipline on `probe.current.grading_claim`): claim → grade → ONE flush → re-read `p_after` → record under the claim (history, `current` cleared, `probe_done`, phase) → a double submit is a 409 and never writes twice; a post-flush conflict is a 409 with the claim held; a stale claim is moved past by `/probe/next` (→ `unavailable`) → the prompt had a plain load/save.
- Body models carry no `course_id` (the course is `_session_scope`'s; `GET /plan` takes no `course_id` query) → ownership (the body's course is never trusted).
- `ProbeAnswerBody` answer fields are `answer`/`option`/`reason`/`idk` (PKG-07's `LoopCheckAnswerBody` names) instead of `selected_option`, and there is no `confidence` field (PKG-05's `CheckAnswer` has none to forward) → one client shape for every loop answer.
- Selection also excludes `revealed_hashes(user_id)` (items whose answer the student has seen; A23) and `seen_hashes(user_id)` (items the student already has evidence on), falling back to the seen items only when nothing unseen is servable (review's A23 rule) → the prompt excluded only the reserve and `unavailable`; a new session would otherwise re-probe correctly answered items and write full-weight evidence again (spec §13 A55(b)).
- Excluded items are excluded only while UNasked: an asked item stays in `next_probe_item`'s list so it still counts toward `PROBE_ITEMS_PER_SKILL_MAX` (a wrong answer reveals its own item) → otherwise the per-skill cap undercounts.
- `/probe/next` with an item posed serves it again (never a skip); `/probe/answer` for a withdrawn item → 200 `{"graded": false, "unavailable": true}` (not asked) → PKG-07's `/check/answer` answers 409 `"check item withdrawn"`, which would leave the probe stuck.
- Typed idk: `idk = body.idk or _is_idk_phrase(answer or reason)` (PKG-07's, `gates.IDK_PATTERNS`, A40) — "idk maybe 7" is graded, not idk.
- Seam names prefixed `_probe_*` / `_plan_*` (`_plan_states`, `_plan_prereq_edges`, `_plan_node_names`, `_plan_due_reviews`, `_probe_course_has_items`, `_probe_items(user_id, course_id, node_ids)`); no `_grade` seam (tests patch `routes.learn_loop.grade_answer`) → avoids collisions with PKG-12's review helpers in the same module.
- `_plan_due_reviews(user_id, node_ids, *, now=None)` (no `course_id`; the due filter `fsrs_due_at ≤ now` runs BEFORE `order_due`) → never-reviewed and not-yet-due nodes are not reviews.
- `grade_answer(..., max_rung=0)` (default): the probe has no hint ladder (A32).
- `SaplingDeps.feature = "loop_probe"`; `learning_loop` is the `_gate` value read once at route entry (A38 00).
- Rate limit: inline `ai_budget.enforce_rate_limit_for(user_id)` right after `_gate` in `/probe/answer` (PKG-12's pattern), not PKG-07's `dependencies=_RATE_LIMITED` → a dependency runs before the handler, so a gate-off student could get a 429 instead of the 404 (fix round). `/probe/next` and `GET /plan` add a per-user in-process limit (`services/request_limits.check_rate_limit`, `PROBE_PLAN_READS_PER_MIN`) after the gate and skip the compare-and-set write when the document is unchanged (`_update_if_changed`).
- `/probe/next` and `/probe/answer` call `_consume_pending` (materialise a lazy session, as PKG-07's `/check/next` does); the plan routes do not (the session exists by then).
- Tests: the gate fixtures patch `routes.learn_loop.learning_loop_for_request` (A38's route-entry gate), not `learning_loop_active`; the loop-state fake is PKG-07's in-memory CAS store (the real `update_loop_state` runs).
- Outside the Files lists: `tests/test_learn_loop_routes.py` `MODEL_ROUTES += /probe/answer`, `NO_MODEL_ROUTES += /probe/next, /plan, /plan/approve`; `tests/test_learning_evidence_apply.py::test_fsrs_importers_are_sanctioned` sanctions `routes/learn_loop.py`; `tests/test_learning_fsrs.py::_calls_gate` accepts the A38 route-entry gate `learning_loop_for_request` as well as `learning_loop_active` (+2 detector cases) → the route imports `learning.fsrs` and calls the gate through PKG-07's `_gate`.
- Fix round (three reviews; spec §13 A55 records every adaptation): an empty proposal exits `plan` from GET /plan (not an approve of `[]`); `outer_fringe` is SCC-aware (a prerequisite cycle is one unit — the prompt's rule hid every member of a cycle); the per-skill cap counts the recorded observations (`asked_per_node`), not today's item list; the grading claim is re-taken before the write (A52 extended); PKG-07's teaching routes 409 during the probe and the plan (PKG-07 reopen); the refusal count is per session (per probe).

## Known gaps

- Review round 2 residuals (2026-09-29, recorded by the coordinator):
  - `/probe/answer`'s inline rate limit (after `_gate`) overrides spec §9's "inline only where some bodies run a model" and A20's dependency form for this route, so a gate-off student gets 404, never 429 (A55(e)).
  - Until PKG-13's UI exists, a beta/staff student on the legacy UI (`/api/learn/chat`, `/chat/stream`, `/action` delegate to the loop routes) gets 409 "finish the probe first" on every chat after the opener greeting.
  - `/start-session(/stream)` (and `/api/notes/chat`) open a fresh unguarded surface: a student mid-probe can ask for the posed item's answer there. Blocking routes cannot close an answer sourced from another surface; the probe is a prior estimate, not proof. Mitigation for later: run `detect_leak` on opener replies against the student's open posed probe items.
  - The probe's seen-item fallback (only once no unseen item is servable) re-credits previously correct items at full weight: slow drift, not student-steerable. Option: record the observation but skip or down-weight the flush for fallback items.
  - `PROBE_PLAN_READS_PER_MIN` is per worker process (×workers, lost on restart); move it to `services/cache` (Redis) when that is on.
  - A loop_state document from before PKG-08 (no `phase`, no `plan.approved`) reads as `probe`: harmless while dark, but a PKG-07 teach session resumed after launch would be sent back to the probe.

- `goal_filter=None`: nothing maps a syllabus week or an assignment to concept ids.
- `wrong_key` / `matched_wrong_key` ignored by the route (PKG-10's hook lives inside `grade_answer`).
- No frontend (PKG-13). `/status` exposes `loop_phase` (probe | plan | teach) beside PKG-07's `phase` (fix round, PKG-07 reopen).
- The skill set is fixed on the first `/probe/next` and never re-derived within a session. Two first calls racing: the first stored skill set wins; the other request's item list was built for its own set (it serves from it once; later calls are consistent).
- At the grader cap every answer comes back `unavailable`; the probe ends only when the candidates run out (each skill's items minus its reserve, all answered ungraded).
- A grade slower than `LOOP_GRADING_CLAIM_STALE_S` whose claim /probe/next took away writes nothing (`{"graded": false, "recorded": false}`): the claim is re-taken with a fresh stamp right before `flush_pending` (fix round m1); the student's answer was graded but not recorded, and the item is already in `unavailable`.
- A post-flush compare-and-set loss leaves the item claimed; `/probe/next` moves past it (into `unavailable`) once the claim is stale, so its written evidence is never an observation and does not count toward the caps.
- The read limit on /probe/next and GET /plan is per process (services/request_limits); a multi-instance deploy multiplies it.
- The seen/revealed exclusion reads the student's evidence rows twice per `/probe/next` (`seen_hashes` and `revealed_hashes` each page them).
- E2E not run (session override); the flag is off in the lane, so the legacy journeys are untouched by construction (every new route 404s before any read).

## Verify commands

```
cd backend && venv/bin/python -m pytest tests/test_learning_probe_planner.py -q                 → N passed (N ≥ 15)
grep -cE "^def (next_probe_item|probe_done|novice_floor)\(" backend/learning/probe.py            → 3
grep -cE "^def (outer_fringe|plan)\(" backend/learning/planner.py                                → 2
grep -c '"learn\.probe_done"\|"learn\.plan_approved"' backend/services/events_service.py         → 2
```

(Observed at hand-off (fix round): `92 passed`; `3`; `2`; `2`. Full suite `7389 passed, 136 skipped` with the CI ignore set; `SAPLING_EVAL_MODE=replay tests/evals/run_all.py` all 13 datasets PASS; `ruff check .` clean.)

## Open questions for the series owner

1. Edge direction: nothing enforces the seed convention (`source` = prerequisite) on tutor-emitted `new_edges` (`agents/chat_tutor.py` names types, not direction) — should PKG-14's cutover add a prompt line or a write-side check? Took: trust `EDGE_PREREQ_SOURCE_IS_PREREQ`.
2. Goal filter from `exam_proximity` (assignments within `FSRS_EXAM_WINDOW_DAYS`) once PKG-12 lands? Took: `None`.
3. Initial phase: PKG-07's start-session writes no `phase`; the missing key reads `probe` (unless `plan.approved`). Fix round: PKG-07's `/chat`, `/chat/stream`, `/hint`, `/action`, `/check/next` now answer 409 `"finish the probe first"` / `"finish the plan first"` during the probe and the plan (PKG-07 reopen, spec §13 A55(a)). Open: should `/start-session`'s opener also wait, or keep greeting before the probe? Took: it greets.
4. Should `/probe/next` finish the probe early after consecutive `unavailable` grades (the grader-cap gap) instead of serving items nobody can grade? Took: no.
5. Due-review overlap with PKG-12's review queue: `GET /plan`'s review section and PKG-12's `/review/next` both draw on `fsrs_due_at ≤ now`; a concept can be reviewed in the plan and again in Study the same day. Should PKG-12 skip nodes in an open session's approved plan (or the plan skip what PKG-12 served today)? Took: independent.
6. `GET /plan` writes the proposal (so `/plan/approve` can check against it); a re-GET overwrites it. Acceptable, or should the proposal be frozen once shown? Took: overwrite.

## Post-hoc changes

(Appended by later packages that modified this package's code. Format: `PKG-MM <date>: <what> — commit <sha>`.)
- PKG-09 2026-09-29 (spec §13 A19): `POST /plan/approve` now calls `learning.learner_brief.store_brief(session_id, user_id, course_id, concept_ids)` after saving the approved plan (the course is `_session_scope`'s return, which the handler already read — no `_session_course_id` seam); failures are logged (exception class only) and never change the response, its event or its status codes. Tests: `tests/test_learning_probe_planner.py` +3 (stores the brief; survives a brief failure; a rejected approve stores none) — commit <sha-approve>
