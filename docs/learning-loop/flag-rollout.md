# Turning on the learning-loop flags

Every newer learning-loop behaviour ships behind its own feature flag, off by default. With a flag off, its code path is byte-identical to before it existed. This page is the checklist for switching each one on: what it changes, what must be true first, how to roll it out, what to watch, and how to roll it back.

Nothing here is switched on by this document. Turning a flag on is the owner's call.

## The master flag: `learning_loop`

Every flag below only matters for a student who has the learning system at all. That is the per-student `learning_loop` flag (`off` | `on`, ships `off`): the loop tutor and its routes, Study's review queue and retention check, the retention badge, the quiz learning features, the integrity guard on notes and flashcards, and check-item drafting on their uploads. Off is the pre-loop app. Roll it out the same way as any flag (yourself, then a class, then everyone).

Above it sits the env kill switch `LEARNING_LOOP_ENABLED`: `false`/`0`/`off`/`no` turns the loop off for everyone, whatever the flag says, with no database read. Unset means "the flag decides" — it no longer means on. `SAPLING_FLAG_LEARNING_LOOP=off` forces the flag off without touching the kill switch. Both off paths answer the loop routes as 404 (`invariants.md` §9) and each has its own E2E lane (kill switch, flag-off).

The showcase drivers (`scripts/gallery-shots.sh`, `scripts/figma-capture.sh`) boot the flag-off lane: their recipes and `backend/agents/function_handlers_showcase.py` photograph production's default, the pre-loop app. Before the flag is on for everyone, give them loop recipes and showcase handlers for the loop slots, or the public gallery keeps showing the legacy tutor.

## How to switch a flag

Flags live in `backend/services/feature_flags.py::REGISTRY`; their stored configuration is in the `feature_flags` and `feature_flag_targets` tables. Change them through the admin Flags tab, or the admin API (`routes/admin_flags.py`):

| Step | Admin API | Effect |
|---|---|---|
| 1. Try it on yourself | `PUT /api/admin/flags/{key}/targets` with your user | On for the listed users only |
| 2. Partial rollout | `PATCH /api/admin/flags/{key}` with `rollout_percent` and `rollout_variant: "on"` | On for a stable percentage of students |
| 3. Everyone | `PATCH /api/admin/flags/{key}` with `default_variant: "on"` | On for all students |
| Check one student | `GET /api/admin/flags/{key}/explain` | Which rule decided their variant; for a learning-loop flag the kill switch, then their `learning_loop` flag, come first (`learning/gate.py::served_flag`) |
| **Roll back** | `PATCH` with `default_variant: "off"`, `rollout_percent: 0`; or set the env var `SAPLING_FLAG_<KEY>=off` on the backend | Off at once; the env var overrides everything stored |

Per-student flags are resolved once per request (or once per quiz generation and submit), so a rollback takes effect on the student's next action.

### The shared blocker: live eval recordings

Several flags change a prompt or an output schema, so their eval datasets must be recorded live and pass before the flag goes on (`backend/tests/evals/README.md`; record with `SAPLING_EVAL_MODE=record`, three recordings for a floor).

**As of 2026-11-24 (A111 on #866 + Day 9 W0.3b/W0.5):** `LOOP_SLOTS_PENDING_CLAUDE_EVAL` is empty. Default-path Claude cassettes + floors landed for `loop_tutor*`, confront, grader, check_items, decisions; plus `__pedagogy`, `__flags`, `__v2`, and `check_item_gates` (verify/solve/topup/varied/combo). Only `deep` is routable on Claude (`LOOP_ROUTABLE_TIERS`). `__v2` served gates (incl. SycophancyResists + ServedAnswerLeak) are **1.0** ×3 on lite/standard/deep (`baselines.json`, prompt `ca02dcf9e63b`); W0.5 three E2E lanes green. `loop_tutor_v2` / `learning_loop` population enable remains **operator-only**.

`SAPLING_EVAL_USAGE_LOG=<path>` records each run's token cost, so a recording also measures what the flag will cost.

## Recommended order

1. **Read-only, no eval needed:** `quiz_concept_plan`, `quiz_results_routing`, `item_reports`.
2. **Safety, after copy review:** `crisis_support`.
3. **Prompt changes, after their evals:** `loop_tutor_v2`, `segment_prequestion`, `self_explanation_prompts`, `quiz_planned_questions`, `quiz_item_gates`, then `quiz_misconceptions`.
4. **Drafting changes, after their evals:** `varied_isomorphs`, `multi_concept_items`, `upload_prereq_edges`.
5. **Measurement-protocol changes, only at a trial boundary:** `probe_matched_pretest`, `retention_due_badge`, `help_gate_strict`.

## Flag by flag

### quiz_concept_plan (A143) — client-visible
- **Changes:** the quiz home suggests concepts from the learner model: FSRS-due reviews first, then open misconceptions, then concepts whose prerequisites are proficient. "Review everything due" means due by FSRS.
- **Before:** nothing; it only reads. Check the plan on a seeded student (`GET /api/quiz/plan`).
- **Watch:** quiz starts per student. A failed plan read falls back to the old tier ranking, so check the backend log for plan errors.
- **Roll back:** off restores the tier ranking.

### quiz_results_routing (A147)
- **Changes:** quiz results show how each skill meter moved, what is due, and a next step (review queue, or Learn on the weakest ready concept).
- **Before:** nothing; it only reads.
- **Watch:** clicks on the next-step links; results-page errors.

### item_reports (A113, A123) — client-visible
- **Changes:** students can report a check question. Two reports hold it from the whole course until staff approve or retire it in the admin check-items queue.
- **Before:** someone on staff owns the review queue (`/api/admin/check-items`) and checks it daily.
- **Watch:** queue length and how long items stay held; a held item reduces the course's servable pool.

### crisis_support — safety
- **Changes:** a message stating suicidal ideation, self-harm or acute danger gets a fixed resources card (988, Crisis Text Line, campus counseling, 911) instead of a model reply, on every tutor, learning-loop and notes AI surface.
- **Before:** the owner reviews the copy in `services/crisis_support_copy.py` against `docs/safety/crisis-support.md`, including the campus counseling details for each school served.
- **Watch:** card count per day; read a sample for false positives (with privacy care).
- **Roll back:** off returns the normal model reply path.

### loop_tutor_v2 (A121)
- **Changes:** the tutor opens with a plain verdict on the student's reply, labels only new content "Key idea:", and names the plan's current concept and why.
- **Before:** `loop_tutor` and `misconception_confront` re-recorded live under `LOOP_EVAL_VARIANT=v2` (their own cassettes), every served gate passing. Once a v2 namespace is recorded, `run_all.py` (and CI) replays it beside the default one, so a later edit to a v2 prompt line fails like any regression.
- **Watch:** `zpd.leak` events, tutor turn retries, session wrap-up ratings.

### segment_prequestion (A138)
- **Changes:** each new concept opens with one ungraded guess at a vetted question; the answer and an explanation follow at once.
- **Before:** the prequestion explaining path recorded live and passing: `teach_explains_prequestion` in the `loop_tutor` flag-path datasets (`<slot>__flags`; `LOOP_EVAL_FLAGS=1 SAPLING_EVAL_MODE=record python tests/evals/loop_tutor.py`). They score the same served gates as the routing datasets but never decide which tier routes; `run_all.py` replays them once recorded.
- **Watch:** `learn.prequestion` events (posed, skipped by reason, answered, superseded); a high `pool_for_checks` skip rate means courses need more items.

### self_explanation_prompts (A139)
- **Changes:** after a worked example, a shown solution or a first unaided correct answer, the turn's question becomes a "why does this follow?" prompt with its own reply box. Replies are stored encrypted and never graded.
- **Before:** the acknowledging turn recorded live and passing: `teach_acknowledges_self_explanation` in the same `loop_tutor` flag-path datasets.
- **Watch:** the admin report's `self_explanation` block: reply rate, and next-item success after a reply.

### next_probe_hint (W2.4)
- **Changes:** when reason-before-submit / self-explain plaintext is available, activation may prefer an already-eligible check whose stem overlaps that text (deterministic keywords). Never mastery.
- **Before:** nothing eval-gated (no prompt change). Prefer after W2.3 storage is in use and a decrypt path into activation exists; until then the call site is a no-op even when on (no plaintext threaded). See [w2-next-probe-hint.md](w2-next-probe-hint.md).
- **Watch:** activation still respects exclusions / post-test reserves; no `apply_graph_update` from this path.
- **Roll back:** off restores ordinary `select_item` preference.

### quiz_planned_questions (A144)
- **Changes:** the learner model sets each quiz question's difficulty and the misconception a distractor targets; the model only writes them.
- **Before:** `quiz_generation_planned` recorded live and passing.
- **Watch:** quiz generation latency and failures; distractor tag rate.

### quiz_item_gates (A145)
- **Changes:** every generated quiz question gets a concept check and a blind key solve on the `quiz_check` slot before it is served; only verified questions count as evidence.
- **Before:** a live smoke of the checks on real quiz questions (`quiz_item_gates` eval) and a measured cost: it adds two to three model calls per quiz.
- **Watch:** `quiz.items_gated` codes (dropped, practice, verified), and passes marked `unavailable` (the checks were down, or cut at their generation run's time bound: the run and its checks share `QUIZ_GENERATION_TIMEOUT_SEC`); top-up rate; cost per quiz.

### quiz_misconceptions (A146)
- **Changes:** a "Sure" wrong answer on a verified quiz question whose option embodies a known misconception records it; a later correct, unassisted answer closes it.
- **Before:** `quiz_planned_questions` and `quiz_item_gates` both on for the same students (it acts only on questions generated with both).
- **Watch:** misconceptions recorded and closed per day from the `quiz` surface.

### varied_isomorphs (A140)
- **Changes:** uploads draft each concept's items with varied scenarios and representations; picks prefer a surface the student hasn't met.
- **Before:** `check_items_varied` (`tests/evals/check_item_gates.py`: the varied drafter on a three-concept call and the varied top-up) recorded live and passing. Takes effect per uploader on new uploads.
- **Watch:** drafting failures; `backend/scripts/project_varied_practice_cost.py` for the cost.

### multi_concept_items (A141)
- **Changes:** uploads also draft items combining a concept with its direct prerequisites; a proficient student gets one per session.
- **Before:** `check_items_combo` (`tests/evals/check_item_gates.py`: the combination drafter and its component check) recorded live and passing.
- **Watch:** `learn.multi_concept_served`; drafting cost.

### upload_prereq_edges (A118)
- **Changes:** uploads extract prerequisite relations and write them as graph edges, so propagation, prerequisite bands, wheelspin repair and plan order start acting on them.
- **Before:** `concept_extraction__relations` (`CONCEPT_EVAL_RELATIONS=1 python tests/evals/concept_extraction.py`: the relations variant, scored on the edges code would write) recorded live and passing; a manual look at the edges written for a few real uploads.
- **Watch:** cycles broken and edges dropped per document (logged by `concept_prereqs.resolve_prerequisites`); plan order complaints.
- **Roll back:** off stops new edges; edges already written stay. It acts only while the learning loop is on for the uploader, so the `LEARNING_LOOP_ENABLED` kill switch (or the uploader's `learning_loop` flag off) stops it too.

### probe_matched_pretest (A130) — measurement protocol
- **Changes:** a concept's first probe question is matched in form to its delayed post-test items, so pre/post pairs compare like with like.
- **Before:** a trial boundary: switching mid-trial mixes two protocols in one analysis.

### retention_due_badge (A126) — measurement protocol, client-visible
- **Changes:** a badge on Study and the Dashboard says a retention check is due (push instead of pull).
- **Before:** a trial boundary: it changes who takes the post-test and when.
- **Watch:** the learning-gain funnel (`posttest_funnel`): answered vs expired windows.

### help_gate_strict (A134)
- **Changes:** a hint unlocks only after the band's independent time (45 s; 90 s for a novice) with the latest hint, and only for a novel attempt that isn't a paste of the question.
- **Before:** a baseline from the admin help-abuse report (`help_abuse.by_gate`) with the flag off; a trial boundary if a trial is running.
- **Watch:** the same report with it on: bottom-outs, earnest-blocked steps, and session abandonment.
