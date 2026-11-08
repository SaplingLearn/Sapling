# The §13 amendments, indexed

The design spec's §13 ([the spec](../superpowers/specs/2026-09-26-learning-loop-design.md),
"Amendments log") records every change made since the spec was approved. Its
rows **override** the spec's earlier sections and the original build prompts
where they disagree, so when a section of the spec and a §13 row conflict,
the row wins — and when a row and the code conflict, the code is the truth and
the row (or this guide) has a bug.

The table is long (about 450 KB) because each row carries its reasoning, its
review history and its commits. This page gives one line per row so you can
find the right one; read the row itself before you change the code it names.

**How to read a row.** Each row has three cells: `id | change | affects`. The
"affects" cell names the build packages (`PKG-04`, `PKG-07` …) and hand-off
notes (`HANDOFF-14` …) of the original series, and the spec sections the row
amends. Recurring markers: **†** after a constant means "an engineering choice
without a validated cut-point" (a candidate for an A/B test, not a research
finding); "reopen" means the row changed a package that was already built;
"owner decision" means the product owner decided it, not a reviewer.

**Numbering.** Rows run from A1 to A147. **A56–A59 and A64–A69 were never
assigned** (packages built in parallel reserved number ranges; nothing in the
repository cites those numbers; since A142 the spec's table says so where
they would be). There are 137 rows, all indexed below. A143–A147 are one
package, the quiz in the learning system (five flags, all off by default).

**Status markers.** Most rows are in force. These are not, or not wholly:

- A81 was retired by A83 (reverted); A84 was superseded by A86; A86's scope,
  store and markers were superseded by A88 ("served unchanged, never withheld"
  stands).
- A45 and A63 are "recorded, not decided". A45's two-seam question was later
  resolved by [ADR 0032](../decisions/0032-separate-learning-decisions-from-tutor-observation.md)
  — where a row names the decision seam for the loop's judgments, read
  `backend/services/learning_decisions.py` and
  `backend/agents/learning_decision.py` (task `learning_decision`); the files
  the rows name, `backend/services/decisions.py` and
  `backend/agents/decision.py`, are now main's observe-only tutor router seam.
- A42 and A43 are decision records with no code of their own.

**Decisions outside §13.** Some loop behaviour was decided in ADRs on PR #673
rather than in §13 rows: confirmed goals and observed diagnostic boundaries
([ADR 0033](../decisions/0033-goal-scoped-observed-diagnosis.md)), evidence
integrity ([0034](../decisions/0034-evidence-integrity-and-goal-continuation.md)),
durable planning observations ([0035](../decisions/0035-durable-planning-observations.md)),
durable tutor-turn recovery ([0036](../decisions/0036-durable-tutor-turn-recovery.md)),
atomic evidence ([0037](../decisions/0037-atomic-learning-evidence.md)) and
replayable grade checkpoints ([0038](../decisions/0038-replayable-grade-checkpoints.md)).
Read those alongside the rows below.

**Wave 4.** A138 (segment prequestion), A139 (self-explanation prompts),
A140 (surface-varied isomorphs) and A141 (multi-concept items) are merged,
each behind its own per-student flag that ships off (`segment_prequestion`,
`self_explanation_prompts`, `varied_isomorphs`, `multi_concept_items`).
Off, each is byte-identical to the code before it; on, each waits for a live
eval recording of its new prompts. A142 reconciled the spec, this guide and
the code, and left the two owner questions at the end of this page.

"Main code" is the single best place to start reading; most rows touch more
files, which the row lists. A dash means the row has no code of its own.

## By theme

### Evidence and the learner model (16)

| A | Area | Change | Main code |
|---|---|---|---|
| A1 | BKT | "I don't know" is a flag on the item's channel, not a channel of its own | `backend/learning/bkt.py::update` |
| A7 | FSRS | FSRS rating-map additions; exam retention beats large-set retention; never-reviewed recall is 1.0 | `backend/learning/fsrs.py::rating_for` |
| A10 | quiz | Quiz evidence is the `mc` channel: a quiz answer carries no reason | `backend/routes/quiz.py` |
| A22 | grading | Code checks (option letter, numeric answer), run after the grader, can only veto a "correct" (A142); a second-opinion slot | `backend/agents/tools/check.py` |
| A28 | FSRS | FSRS-6 reference guards (same-day reviews, stability floors) ratified | `backend/learning/fsrs.py::next_state` |
| A30 | BKT | Belief is capped at 0.999 so contrary evidence can always lower it | `backend/learning/bkt.py::update` |
| A36 | evidence write | Journal rows carry their apply order (`evidence_seq`) | `backend/db/migrations/20260927182054_learning_mastery_event_seq.sql` |
| A71 | evidence write | The review retention target is an `apply_graph_update` keyword, not a payload key | `backend/services/graph_service.py::apply_graph_update` |
| A74 | FSRS | Never-scheduled flashcards enter the review pool; a stored stability must be positive | `backend/db/migrations/20260929111535_learning_fsrs_stability_positive.sql` |
| A76 | evidence weight | Re-check after release: the next graded item on a concept after its answer was shown counts as a half-weight re-check | `backend/learning/misconceptions.py::recheck_after_release` |
| A95 | tiers | Stored mastery tiers are re-derived with the launch cuts | `backend/db/migrations/20261001013855_learning_rederive_mastery_tier.sql` |
| A116 | grading | Evidence names the provider that graded (`grader_backend` admits `claude`) | `backend/services/learning_decisions.py::evidence_backend` |
| A127 | confidence | The student states a confidence, and misconceptions resolve | `backend/learning/misconceptions.py::resolve` |
| A132 | quiz | The quiz states a confidence, and a flawed quiz item is no evidence | `backend/learning/quiz_evidence.py::evidence_exclusion` |
| A144 | quiz | The learner model chooses each quiz question's difficulty and misconception target; the model only writes it, behind `quiz_planned_questions` | `backend/learning/quiz_plan.py::question_specs` |
| A146 | quiz | The quiz records a "Sure" wrong answer's tagged misconception and resolves one (A127), behind `quiz_misconceptions` | `backend/services/quiz_learning.py::misconceptions_after_submit` |

### Measurement and evaluation (16)

| A | Area | Change | Main code |
|---|---|---|---|
| A47 | evals | The eval-side rung judge is the authority on ceiling compliance | `backend/tests/evals/_rung_judge.py` |
| A48 | evals | Tier routability is judged on the served text, not the raw model text | `backend/routes/learn_loop.py::served_model_text` |
| A49 | evals | A tier routes only after three fresh recordings all pass | `backend/agents/loop_tutor.py::LOOP_ROUTABLE_TIERS` |
| A79 | metrics | The evaluation ladder as built: nightly metrics, within-student arms, `write_metrics` | `backend/scripts/derive_zpd_metrics.py` |
| A82 | metrics | `zpd.step` carries the session id, so cost is reported per session | `backend/learning/zpd_events.py::emit_zpd_step` |
| A87 | post-test | The tool-removed post-test commits when opened (`posttest_poses`) | `backend/db/migrations/20260930024005_learning_posttest_poses.sql` |
| A89 | post-test | A post-test pose expires after 24 h; help since the pose removes unassisted credit | `backend/learning/params.py::POSTTEST_POSE_TTL_HOURS` |
| A90 | metrics | The zero-leak gate counts solution reveals actually served | `backend/routes/admin_analytics.py` |
| A107 | evals | Jev promotion-gate fixes (a missing Jev cost fails instead of passing) | `backend/tests/evals/decisions.py::shadow_stats` |
| A108 | evals | Tier re-records and their decisions: the lite tier stays unrouted, only deep confronts | `backend/tests/evals/loop_tutor.py` |
| A109 | metrics | The earnest-revise gate is measured | `backend/learning/earnest_revise.py::earnest_revise` |
| A110 | calibration | Evidence hardening from the 2026-11-07 audit: BKT calibration KPI and grader agreement | `backend/learning/calibration.py::calibration` |
| A112 | post-test | The delayed post-test is an outcome measure: fixed windows, recorded delay, a pre/post report | `backend/learning/learning_gain.py::learning_gain` |
| A126 | post-test | The post-test can support a learning claim: missing outcomes counted, intervals, matched items, latency | `backend/learning/learning_gain.py::posttest_funnel` |
| A130 | post-test | A matched pretest form, behind the `probe_matched_pretest` flag | `backend/learning/checks.py::pretest_form` |
| A133 | metrics | Help abuse is measured (bottom-outs, pace, the attempts that bought them) | `backend/learning/help_abuse.py::help_abuse` |

### Item quality (17)

| A | Area | Change | Main code |
|---|---|---|---|
| A2 | schema | Check items are course assets keyed on (course, concept key), not on one student's graph node | `backend/services/check_item_service.py::concept_key` |
| A23 | economy | Item economy, peer-material sourcing, the seen and revealed exclusion sets, and withdrawal | `backend/learning/loop_state_store.py::seen_hashes` |
| A34 | keys | Items state a structured final answer; the leak check never parses a free-text reference | `backend/learning/checks.py::answer_tokens` |
| A37 | drafting | `mc_reason` drafts give options as objects; code letters them and places the key; the top-up agent | `backend/agents/check_items_topup.py` |
| A41 | drafting | Low-severity fixes: failed drafting is billed, redrafting is bounded, ciphertext coverage, pool shutdown | `backend/db/migrations/20260929050242_learning_check_item_draft_failures.sql` |
| A43 | keys | Peer-sourced answer keys are accepted for the beta (an accepted risk; A124 later checks keys) | — |
| A77 | keys | "A wrong reason states the answer" is one decision, shared by drafting and serving | `backend/learning/checks.py::states_final_answer` |
| A80 | drafting | The final answer stays capped at 20 tokens (measured) | `backend/learning/params.py::CHECK_ITEM_FINAL_ANSWER_MAX_TOKENS` |
| A113 | lint/review | Item quality guards: student reports, a flaw linter, a clean-first post-test, a staff review queue | `backend/learning/item_lint.py::lint_item` |
| A119 | alignment | Alignment: the rubric asks only what the question asks, and the item is filed under the concept it tests | `backend/learning/item_alignment.py::align` |
| A123 | holds/voids | A broken item: a reversible hold, and void evidence with a deterministic recompute | `backend/learning/evidence_void.py::is_void_row` |
| A124 | keys | Keys are checked by an independent blind solve; a disputed key is held; staff audit a sample | `backend/learning/item_keys.py::compare` |
| A129 | selection | Every picker prefers a confirmed key, then clean lint | `backend/learning/checks.py::serve_quality` |
| A131 | lint/review | Classical item statistics in the staff review queue | `backend/learning/item_stats.py::item_statistics` |
| A140 | surface | Surface-varied isomorphs and the cue-familiarity dial, behind the `varied_isomorphs` flag | `backend/learning/surface.py::familiarity_by_hash` |
| A141 | multi-concept | Multi-concept items, gated on proficiency in every component, one half-weight observation on the apex, behind the `multi_concept_items` flag | `backend/learning/multi_concept.py::gate_open` |
| A145 | quiz gates | Quiz questions pass A119's concept check and A124's blind solve (on `quiz_check`, another model) before they can be evidence; a disputed one is never served, behind `quiz_item_gates` | `backend/learning/quiz_gates.py::decide` |

### Teaching policy (31)

| A | Area | Change | Main code |
|---|---|---|---|
| A3 | bands | `learner_state` keeps the longest unassisted streak, for the wheelspin rule | `backend/learning/policy.py::wheelspin` |
| A4 | ceiling | Exam mode beats the shown-work floor: in exam mode the ceiling is H1 | `backend/learning/policy.py::ceiling_with_reason` |
| A5 | gates | Gates take an injectable clock; every gate time scales with `LEARNING_GATE_TIME_SCALE` (E2E only) | `backend/learning/params.py::gate_seconds` |
| A13 | planning | No syllabus-week filter for the planner; exam proximity drives the retention target and the brief | `backend/services/exam_proximity.py::days_until_next_exam` |
| A17 | ladder | Deterministic turns (check pose, H2 passages, H4 sibling, H6 reference), each leak-checked | `backend/learning/ladder.py::deterministic_content` |
| A27 | activation | Item activation and the current concept: the plan cursor drives which item is posed | `backend/routes/learn_loop.py::_activate_next_item` |
| A29 | misconceptions | The class misconception rollup groups by course concept, not by per-student node | `backend/learning/misconceptions.py::rollup` |
| A32 | ladder | H6 (the full solution) needs a practice item; ungraded is not practice | `backend/learning/gates.py::h6_allowed` |
| A40 | bands | Tuning decisions: eval floors are min-of-3, "harder" needs four attempts, "no idea" is I-don't-know | `backend/learning/policy.py::band_control` |
| A46 | tutor turn | The tutor's turn is structured: key idea, body, question (question last) | `backend/learning/turn_shape.py::render_turn` |
| A53 | gates | `/step/attempt` counts at most one new, distinct attempt per rung | `backend/routes/learn_loop.py::step_attempt` |
| A54 | ladder | The ladder serves the fields its lowest rungs fix, instead of model text | `backend/routes/learn_loop.py::_served_fields` |
| A55 | probe/plan | The probe and the plan as built (phases, routes, approval) | `backend/routes/learn_loop.py::probe_next` |
| A60 | close | The session close as built: one close per session, by claim | `backend/routes/learn_loop.py::close_session` |
| A70 | review queue | Review answers are claims; the open review item is stable across reloads | `backend/learning/review.py::claim_item` |
| A75 | misconceptions | The misconception loop as built: record, confront, re-ask an isomorph, class rollup | `backend/learning/misconceptions.py::slip_or_misconception` |
| A81 | tutor turn | Retired by A83: at a teach ceiling of H0/H1 the question would come from the ladder | — |
| A83 | tutor turn | A81 is retired and reverted | — |
| A85 | gates | A reasoned wrong claim in the teach phase is a genuine attempt for that turn's ceiling | `backend/learning/gates.py::teach_attempt` |
| A114 | review queue | Interleave confusable concepts in the daily review | `backend/learning/interleave.py::serve_order` |
| A115 | review queue | The review session view carries the served (open) items | `backend/learning/review.py::_session_view` |
| A117 | close | The close reports honest baselines and counts check-in answers apart | `backend/learning/session_close.py::build_close` |
| A118 | graph | Uploads write prerequisite edges, behind the `upload_prereq_edges` flag | `backend/services/concept_prereqs.py::resolve_prerequisites` |
| A120 | gates | A hedge beside an answer is still an attempt; probe answers feed the misconception rule | `backend/learning/gates.py::vetoes_attempt` |
| A121 | tutor turn | The tutor's turn template; v2 behind the `loop_tutor_v2` flag | `backend/agents/loop_tutor.py::variant_run_args` |
| A122 | bands | The band controller and worked-example-first, wired into the plan | `backend/learning/policy.py::band_verdict` |
| A134 | gates | A stricter genuine-attempt gate, behind the `help_gate_strict` flag | `backend/learning/gates.py::strict_genuine_attempt` |
| A138 | prequestion | A teaching segment opens on one ungraded prequestion, and its answer and explanation follow at once, behind the `segment_prequestion` flag | `backend/learning/prequestion.py::segment_open` |
| A139 | self-explanation | At a code-decided juncture the turn's question becomes "why does this follow?"; the reply is stored for diagnosis only, behind the `self_explanation_prompts` flag | `backend/learning/self_explain.py::juncture` |
| A143 | quiz plan | The quiz home proposes concepts from the learner model (FSRS-due first, then open misconceptions, then the ready fringe), behind `quiz_concept_plan` | `backend/learning/quiz_plan.py::rank_concepts` |
| A147 | quiz results | The quiz results show each skill meter that moved, what is due and the next step (review, or Learn), behind `quiz_results_routing` | `backend/services/quiz_learning.py::results_block` |

### Safety and integrity (20)

| A | Area | Change | Main code |
|---|---|---|---|
| A16 | grading | Grade only explicit answer submissions, in the route; chat messages are never graded | `backend/agents/tools/check.py::grade_answer` |
| A33 | answer guard | An answer addressed to the grader is refused, never graded (prompt-injection guard) | `backend/learning/answer_guard.py::screen` |
| A51 | prompt safety | A student's words can never steer the loop tutor (nonce envelope, rules on every turn) | `backend/agents/loop_tutor.py::student_envelope` |
| A52 | grading | Grading a check item is a claim: one grade per posed item, taken by compare-and-set | `backend/routes/learn_loop.py::_grade_submission` |
| A61 | prompt safety | The tutor's rules ride `instructions=` so they reach every turn, not only the first | `backend/agents/loop_tutor.py::loop_tutor_agent` |
| A62 | brief | The learner brief carries no model-written free text | `backend/learning/learner_brief.py::build_brief` |
| A84 | reveals | Superseded by A86: teach turns never state check answers | — |
| A86 | reveals | Scope superseded by A88: a served teach turn is scanned, never withheld | `backend/learning/reveal_store.py` |
| A88 | reveals | Each served tutor turn is scanned against the student's open posed items; reveals are durable at serve time | `backend/learning/reveal_store.py::record_reveals` |
| A93 | help ledger | A per-student help ledger: a grade's help floor is the most help ever had on that item | `backend/learning/help_ledger.py::max_help` |
| A94 | quiz | Quiz evidence cannot be farmed: answer keys admin-only, one evidence per question per window | `backend/routes/quiz.py` |
| A97 | answer guard | A correct answer the student disowns earns no credit | `backend/learning/answer_guard.py::disowned` |
| A99 | help ledger | The quiz "Ask about this" panel opens a `quiz_ask` session whose help lands on the quiz item's ledger | `backend/services/quiz_ask.py` |
| A100 | quiz | Quiz farming: a rolling 24-hour window, decided by an atomic claim | `backend/db/migrations/20261001060408_learning_quiz_evidence_claims.sql` |
| A101 | reveals | The served-text scan keeps open seen items, compiles once per turn, runs off the event loop | `backend/learning/served_scan.py::ScanSet` |
| A102 | help ledger | Correction: exactly what writes a help row | `backend/learning/help_ledger.py::record_help` |
| A103 | answer guard | `disowned()`: one more form, and its accepted limits | `backend/learning/answer_guard.py::disowned` |
| A104 | privacy | The Jev privacy gate is an allowlist of environments | `backend/agents/_jev.py::privacy_gate_open` |
| A105 | reveals | The served scan: a word-token window, a whole final pass, fail-closed errors | `backend/learning/served_scan.py::ScanSet` |
| A125 | outside surfaces | AI surfaces outside the loop never see a posed item and never state its key | `backend/services/integrity_guard.py::open_guard` |

### Cost and model routing (16)

| A | Area | Change | Main code |
|---|---|---|---|
| A15 | routing | Code picks the tutor tier (lite, standard, deep) from phase and band | `backend/learning/policy.py::model_tier` |
| A18 | context | What context and tools each phase gets, with tighter limits | `backend/learning/policy.py::context_policy` |
| A19 | brief | Stable prompt prefix: the learner brief is built once per session and stored encrypted | `backend/learning/learner_brief.py::store_brief` |
| A20 | budget | Per-student AI budget: caps, a degradation ladder and a rate limit | `backend/services/ai_budget.py::check` |
| A21 | usage | `llm_usage` records cached and thinking tokens; pricing knows the cached-input rate | `backend/agents/usage.py::record_agent_usage` |
| A24 | decision seam | A typed decision seam now, the Jev backend later (the loop's seam was split off by ADR 0032) | `backend/services/learning_decisions.py` |
| A25 | close | No close model call for a session with no evidence or at the hard cap: a deterministic close | `backend/learning/session_close.py::fallback_close` |
| A35 | class summary | With the loop on, the class summary is numbers only: no prose and no `course_summary` model call | `backend/services/course_context_service.py::update_course_context` |
| A39 | budget | AI budget owner decisions, including a daily cap on tutor call count | `backend/db/migrations/20260929050404_learning_ai_tutor_daily_calls.sql` |
| A44 | usage | Upload-time drafting is billed to the uploading student | `backend/agents/check_items.py` |
| A50 | routing | One tool round per loop tutor run | `backend/agents/loop_tutor.py::_tools_until_first_round` |
| A63 | caching | Recorded, not decided: a per-session history nonce to lengthen the cacheable prefix | — |
| A92 | usage | `llm_usage.session_id` | `backend/db/migrations/20260930042516_learning_llm_usage_session_id.sql` |
| A98 | decision seam | The Jev decision backend as built (SDK, retries, shadow runs, gates) | `backend/agents/_jev.py` |
| A111 | providers | The loop slots are Claude-ready; their defaults stay on Gemini until a live Claude eval passes | `backend/agents/_providers.py::LOOP_SLOTS_PENDING_CLAUDE_EVAL` |
| A137 | cost | Cost readiness for the Claude move, and the loop's cost per learning gain | `backend/learning/cost_per_gain.py::cost_per_gain` |

### Operations and process (21)

| A | Area | Change | Main code |
|---|---|---|---|
| A6 | constants | A batch of new named constants (probe shift, rung bounds, close limits, item caps) | `backend/learning/params.py` |
| A8 | events | New events and payload keys (`learn.check_items_failed`, post-test phase, variant, `model_written`) | `backend/services/events_service.py::EVENT_TAXONOMY` |
| A9 | schema | `sessions.mode` admits `review` | `backend/db/migrations/20260929081946_learning_sessions_mode_review.sql` |
| A11 | schema | A `sessions` row is created only by an insert-if-missing helper, never by an upsert | `backend/learning/session_close.py::ensure_session_row` |
| A12 | module map | Module-map additions: loop-state store, `zpd.*` emitters, close agent, frontend loop state and DueQueue | `backend/learning/loop_state_store.py` |
| A14 | gate | The loop is every student's default with no opt-in; `LEARNING_LOOP_ENABLED` becomes a kill switch | `backend/learning/gate.py::learning_loop_active` |
| A26 | frontend | Frontend contract: no model toggle, explicit answers, the budget-pause banner, resume | `frontend/src/components/learn/LoopLearn.tsx::LoopLearn` |
| A31 | gate | The retired `learning_loop_beta` toggle is in no settings API field | `backend/routes/profile.py::_SETTINGS_COLS` |
| A38 | decision record | Owner decisions before PKG-07: step-state layout, compare-and-set saves, option-letter leak, one gate read per request | `backend/learning/loop_state_store.py::update_loop_state` |
| A42 | decision record | Keep as built: the hand-offs' answers to open questions stand | — |
| A45 | decision record | Recorded, not decided: two competing decision seams and ADR numbering (resolved by ADR 0032) | `docs/decisions/0032-separate-learning-decisions-from-tutor-observation.md` |
| A72 | frontend | The loop status probe (`/review/active`) and a read-only review summary | `backend/routes/learn_loop.py::review_active` |
| A73 | sessions | Review sessions are not tutor sessions; tutor-session readers skip them | `backend/services/session_modes.py::NOT_REVIEW` |
| A78 | frontend | The student UI's server seams as built (status probe, resume, review) | `frontend/src/components/learn/useLoopStatus.ts::useLoopStatus` |
| A91 | rollout | The cutover (PKG-14 half B) as built: kill-switch parse, legacy cost bound, E2E lanes | `backend/config.py::LEARNING_LOOP_ENABLED` |
| A96 | decision record | PKG-14 review round: smaller fixes and one correction | `backend/routes/learn.py` |
| A106 | sessions | Quiz-ask sessions stay on the quiz node's course and out of session metrics | `backend/services/quiz_ask.py::resolve_quiz_ask` |
| A128 | degraded mode | Degraded mode is honest: failed retrieval, embeddings breaker, unsourced items, "preparing", slot guard | `backend/agents/_providers.py::check_slot_guards` |
| A135 | a11y | The student UI is accessible, and an axe lane keeps it so | `frontend/e2e/a11y.spec.ts` |
| A136 | schema | Every float the backend reads through PostgREST is exact | `backend/db/migrations/20261108162223_learning_exact_floats.sql` |
| A142 | reconciliation | Spec, docs and code reconciled: the guide's list of disagreements, each settled (code fixed, text corrected, or recorded) | `backend/db/migrations/20261108193927_learning_report_course_key.sql` |

## In A-number order

| A | Theme | Area | Change |
|---|---|---|---|
| A1 | Evidence and the learner model | BKT | "I don't know" is a flag on the item's channel, not a channel of its own |
| A2 | Item quality | schema | Check items are course assets keyed on (course, concept key), not on one student's graph node |
| A3 | Teaching policy | bands | `learner_state` keeps the longest unassisted streak, for the wheelspin rule |
| A4 | Teaching policy | ceiling | Exam mode beats the shown-work floor: in exam mode the ceiling is H1 |
| A5 | Teaching policy | gates | Gates take an injectable clock; every gate time scales with `LEARNING_GATE_TIME_SCALE` (E2E only) |
| A6 | Operations and process | constants | A batch of new named constants (probe shift, rung bounds, close limits, item caps) |
| A7 | Evidence and the learner model | FSRS | FSRS rating-map additions; exam retention beats large-set retention; never-reviewed recall is 1.0 |
| A8 | Operations and process | events | New events and payload keys (`learn.check_items_failed`, post-test phase, variant, `model_written`) |
| A9 | Operations and process | schema | `sessions.mode` admits `review` |
| A10 | Evidence and the learner model | quiz | Quiz evidence is the `mc` channel: a quiz answer carries no reason |
| A11 | Operations and process | schema | A `sessions` row is created only by an insert-if-missing helper, never by an upsert |
| A12 | Operations and process | module map | Module-map additions: loop-state store, `zpd.*` emitters, close agent, frontend loop state and DueQueue |
| A13 | Teaching policy | planning | No syllabus-week filter for the planner; exam proximity drives the retention target and the brief |
| A14 | Operations and process | gate | The loop is every student's default with no opt-in; `LEARNING_LOOP_ENABLED` becomes a kill switch |
| A15 | Cost and model routing | routing | Code picks the tutor tier (lite, standard, deep) from phase and band |
| A16 | Safety and integrity | grading | Grade only explicit answer submissions, in the route; chat messages are never graded |
| A17 | Teaching policy | ladder | Deterministic turns (check pose, H2 passages, H4 sibling, H6 reference), each leak-checked |
| A18 | Cost and model routing | context | What context and tools each phase gets, with tighter limits |
| A19 | Cost and model routing | brief | Stable prompt prefix: the learner brief is built once per session and stored encrypted |
| A20 | Cost and model routing | budget | Per-student AI budget: caps, a degradation ladder and a rate limit |
| A21 | Cost and model routing | usage | `llm_usage` records cached and thinking tokens; pricing knows the cached-input rate |
| A22 | Evidence and the learner model | grading | Code checks (option letter, numeric answer), run after the grader, can only veto a "correct" (A142); a second-opinion slot |
| A23 | Item quality | economy | Item economy, peer-material sourcing, the seen and revealed exclusion sets, and withdrawal |
| A24 | Cost and model routing | decision seam | A typed decision seam now, the Jev backend later (the loop's seam was split off by ADR 0032) |
| A25 | Cost and model routing | close | No close model call for a session with no evidence or at the hard cap: a deterministic close |
| A26 | Operations and process | frontend | Frontend contract: no model toggle, explicit answers, the budget-pause banner, resume |
| A27 | Teaching policy | activation | Item activation and the current concept: the plan cursor drives which item is posed |
| A28 | Evidence and the learner model | FSRS | FSRS-6 reference guards (same-day reviews, stability floors) ratified |
| A29 | Teaching policy | misconceptions | The class misconception rollup groups by course concept, not by per-student node |
| A30 | Evidence and the learner model | BKT | Belief is capped at 0.999 so contrary evidence can always lower it |
| A31 | Operations and process | gate | The retired `learning_loop_beta` toggle is in no settings API field |
| A32 | Teaching policy | ladder | H6 (the full solution) needs a practice item; ungraded is not practice |
| A33 | Safety and integrity | answer guard | An answer addressed to the grader is refused, never graded (prompt-injection guard) |
| A34 | Item quality | keys | Items state a structured final answer; the leak check never parses a free-text reference |
| A35 | Cost and model routing | class summary | With the loop on, the class summary is numbers only: no prose and no `course_summary` model call |
| A36 | Evidence and the learner model | evidence write | Journal rows carry their apply order (`evidence_seq`) |
| A37 | Item quality | drafting | `mc_reason` drafts give options as objects; code letters them and places the key; the top-up agent |
| A38 | Operations and process | decision record | Owner decisions before PKG-07: step-state layout, compare-and-set saves, option-letter leak, one gate read per request |
| A39 | Cost and model routing | budget | AI budget owner decisions, including a daily cap on tutor call count |
| A40 | Teaching policy | bands | Tuning decisions: eval floors are min-of-3, "harder" needs four attempts, "no idea" is I-don't-know |
| A41 | Item quality | drafting | Low-severity fixes: failed drafting is billed, redrafting is bounded, ciphertext coverage, pool shutdown |
| A42 | Operations and process | decision record | Keep as built: the hand-offs' answers to open questions stand |
| A43 | Item quality | keys | Peer-sourced answer keys are accepted for the beta (an accepted risk; A124 later checks keys) |
| A44 | Cost and model routing | usage | Upload-time drafting is billed to the uploading student |
| A45 | Operations and process | decision record | Recorded, not decided: two competing decision seams and ADR numbering (resolved by ADR 0032) |
| A46 | Teaching policy | tutor turn | The tutor's turn is structured: key idea, body, question (question last) |
| A47 | Measurement and evaluation | evals | The eval-side rung judge is the authority on ceiling compliance |
| A48 | Measurement and evaluation | evals | Tier routability is judged on the served text, not the raw model text |
| A49 | Measurement and evaluation | evals | A tier routes only after three fresh recordings all pass |
| A50 | Cost and model routing | routing | One tool round per loop tutor run |
| A51 | Safety and integrity | prompt safety | A student's words can never steer the loop tutor (nonce envelope, rules on every turn) |
| A52 | Safety and integrity | grading | Grading a check item is a claim: one grade per posed item, taken by compare-and-set |
| A53 | Teaching policy | gates | `/step/attempt` counts at most one new, distinct attempt per rung |
| A54 | Teaching policy | ladder | The ladder serves the fields its lowest rungs fix, instead of model text |
| A55 | Teaching policy | probe/plan | The probe and the plan as built (phases, routes, approval) |
| A60 | Teaching policy | close | The session close as built: one close per session, by claim |
| A61 | Safety and integrity | prompt safety | The tutor's rules ride `instructions=` so they reach every turn, not only the first |
| A62 | Safety and integrity | brief | The learner brief carries no model-written free text |
| A63 | Cost and model routing | caching | Recorded, not decided: a per-session history nonce to lengthen the cacheable prefix |
| A70 | Teaching policy | review queue | Review answers are claims; the open review item is stable across reloads |
| A71 | Evidence and the learner model | evidence write | The review retention target is an `apply_graph_update` keyword, not a payload key |
| A72 | Operations and process | frontend | The loop status probe (`/review/active`) and a read-only review summary |
| A73 | Operations and process | sessions | Review sessions are not tutor sessions; tutor-session readers skip them |
| A74 | Evidence and the learner model | FSRS | Never-scheduled flashcards enter the review pool; a stored stability must be positive |
| A75 | Teaching policy | misconceptions | The misconception loop as built: record, confront, re-ask an isomorph, class rollup |
| A76 | Evidence and the learner model | evidence weight | Re-check after release: the next graded item on a concept after its answer was shown counts as a half-weight re-check |
| A77 | Item quality | keys | "A wrong reason states the answer" is one decision, shared by drafting and serving |
| A78 | Operations and process | frontend | The student UI's server seams as built (status probe, resume, review) |
| A79 | Measurement and evaluation | metrics | The evaluation ladder as built: nightly metrics, within-student arms, `write_metrics` |
| A80 | Item quality | drafting | The final answer stays capped at 20 tokens (measured) |
| A81 | Teaching policy | tutor turn | Retired by A83: at a teach ceiling of H0/H1 the question would come from the ladder |
| A82 | Measurement and evaluation | metrics | `zpd.step` carries the session id, so cost is reported per session |
| A83 | Teaching policy | tutor turn | A81 is retired and reverted |
| A84 | Safety and integrity | reveals | Superseded by A86: teach turns never state check answers |
| A85 | Teaching policy | gates | A reasoned wrong claim in the teach phase is a genuine attempt for that turn's ceiling |
| A86 | Safety and integrity | reveals | Scope superseded by A88: a served teach turn is scanned, never withheld |
| A87 | Measurement and evaluation | post-test | The tool-removed post-test commits when opened (`posttest_poses`) |
| A88 | Safety and integrity | reveals | Each served tutor turn is scanned against the student's open posed items; reveals are durable at serve time |
| A89 | Measurement and evaluation | post-test | A post-test pose expires after 24 h; help since the pose removes unassisted credit |
| A90 | Measurement and evaluation | metrics | The zero-leak gate counts solution reveals actually served |
| A91 | Operations and process | rollout | The cutover (PKG-14 half B) as built: kill-switch parse, legacy cost bound, E2E lanes |
| A92 | Cost and model routing | usage | `llm_usage.session_id` |
| A93 | Safety and integrity | help ledger | A per-student help ledger: a grade's help floor is the most help ever had on that item |
| A94 | Safety and integrity | quiz | Quiz evidence cannot be farmed: answer keys admin-only, one evidence per question per window |
| A95 | Evidence and the learner model | tiers | Stored mastery tiers are re-derived with the launch cuts |
| A96 | Operations and process | decision record | PKG-14 review round: smaller fixes and one correction |
| A97 | Safety and integrity | answer guard | A correct answer the student disowns earns no credit |
| A98 | Cost and model routing | decision seam | The Jev decision backend as built (SDK, retries, shadow runs, gates) |
| A99 | Safety and integrity | help ledger | The quiz "Ask about this" panel opens a `quiz_ask` session whose help lands on the quiz item's ledger |
| A100 | Safety and integrity | quiz | Quiz farming: a rolling 24-hour window, decided by an atomic claim |
| A101 | Safety and integrity | reveals | The served-text scan keeps open seen items, compiles once per turn, runs off the event loop |
| A102 | Safety and integrity | help ledger | Correction: exactly what writes a help row |
| A103 | Safety and integrity | answer guard | `disowned()`: one more form, and its accepted limits |
| A104 | Safety and integrity | privacy | The Jev privacy gate is an allowlist of environments |
| A105 | Safety and integrity | reveals | The served scan: a word-token window, a whole final pass, fail-closed errors |
| A106 | Operations and process | sessions | Quiz-ask sessions stay on the quiz node's course and out of session metrics |
| A107 | Measurement and evaluation | evals | Jev promotion-gate fixes (a missing Jev cost fails instead of passing) |
| A108 | Measurement and evaluation | evals | Tier re-records and their decisions: the lite tier stays unrouted, only deep confronts |
| A109 | Measurement and evaluation | metrics | The earnest-revise gate is measured |
| A110 | Measurement and evaluation | calibration | Evidence hardening from the 2026-11-07 audit: BKT calibration KPI and grader agreement |
| A111 | Cost and model routing | providers | The loop slots are Claude-ready; their defaults stay on Gemini until a live Claude eval passes |
| A112 | Measurement and evaluation | post-test | The delayed post-test is an outcome measure: fixed windows, recorded delay, a pre/post report |
| A113 | Item quality | lint/review | Item quality guards: student reports, a flaw linter, a clean-first post-test, a staff review queue |
| A114 | Teaching policy | review queue | Interleave confusable concepts in the daily review |
| A115 | Teaching policy | review queue | The review session view carries the served (open) items |
| A116 | Evidence and the learner model | grading | Evidence names the provider that graded (`grader_backend` admits `claude`) |
| A117 | Teaching policy | close | The close reports honest baselines and counts check-in answers apart |
| A118 | Teaching policy | graph | Uploads write prerequisite edges, behind the `upload_prereq_edges` flag |
| A119 | Item quality | alignment | Alignment: the rubric asks only what the question asks, and the item is filed under the concept it tests |
| A120 | Teaching policy | gates | A hedge beside an answer is still an attempt; probe answers feed the misconception rule |
| A121 | Teaching policy | tutor turn | The tutor's turn template; v2 behind the `loop_tutor_v2` flag |
| A122 | Teaching policy | bands | The band controller and worked-example-first, wired into the plan |
| A123 | Item quality | holds/voids | A broken item: a reversible hold, and void evidence with a deterministic recompute |
| A124 | Item quality | keys | Keys are checked by an independent blind solve; a disputed key is held; staff audit a sample |
| A125 | Safety and integrity | outside surfaces | AI surfaces outside the loop never see a posed item and never state its key |
| A126 | Measurement and evaluation | post-test | The post-test can support a learning claim: missing outcomes counted, intervals, matched items, latency |
| A127 | Evidence and the learner model | confidence | The student states a confidence, and misconceptions resolve |
| A128 | Operations and process | degraded mode | Degraded mode is honest: failed retrieval, embeddings breaker, unsourced items, "preparing", slot guard |
| A129 | Item quality | selection | Every picker prefers a confirmed key, then clean lint |
| A130 | Measurement and evaluation | post-test | A matched pretest form, behind the `probe_matched_pretest` flag |
| A131 | Item quality | lint/review | Classical item statistics in the staff review queue |
| A132 | Evidence and the learner model | quiz | The quiz states a confidence, and a flawed quiz item is no evidence |
| A133 | Measurement and evaluation | metrics | Help abuse is measured (bottom-outs, pace, the attempts that bought them) |
| A134 | Teaching policy | gates | A stricter genuine-attempt gate, behind the `help_gate_strict` flag |
| A135 | Operations and process | a11y | The student UI is accessible, and an axe lane keeps it so |
| A136 | Operations and process | schema | Every float the backend reads through PostgREST is exact |
| A137 | Cost and model routing | cost | Cost readiness for the Claude move, and the loop's cost per learning gain |
| A138 | Teaching policy | prequestion | A teaching segment opens on one ungraded prequestion, and its answer and explanation follow at once, behind the `segment_prequestion` flag |
| A139 | Teaching policy | self-explanation | At a code-decided juncture the turn's question becomes "why does this follow?"; the reply is stored for diagnosis only, behind the `self_explanation_prompts` flag |
| A140 | Item quality | surface | Surface-varied isomorphs and the cue-familiarity dial, behind the `varied_isomorphs` flag |
| A141 | Item quality | multi-concept | Multi-concept items, gated on proficiency in every component, one half-weight observation on the apex, behind the `multi_concept_items` flag |
| A142 | Operations and process | reconciliation | Spec, docs and code reconciled: the guide's list of disagreements, each settled (code fixed, text corrected, or recorded) |
| A143 | Teaching policy | quiz plan | The quiz home proposes concepts from the learner model, behind `quiz_concept_plan` |
| A144 | Evidence and the learner model | quiz | The learner model chooses each quiz question; the model only writes it, behind `quiz_planned_questions` |
| A145 | Item quality | quiz gates | Quiz questions pass the loop's concept check and blind key solve before they can be evidence, behind `quiz_item_gates` |
| A146 | Evidence and the learner model | quiz | The quiz records and resolves misconceptions, behind `quiz_misconceptions` |
| A147 | Teaching policy | quiz results | The quiz results route into the learning system, behind `quiz_results_routing` |

## Where the spec and the code disagree

The list this guide first published (fourteen items, checked at `f9eca612`)
was settled by §13 A142: each was fixed in the code with tests, corrected in
the spec or the docs, or recorded as intended — read the row for each
resolution and the test that proves it. The spec's earlier sections were
corrected in place where they were simply wrong; amendment rows were not
rewritten, and A142 says which row each correction supersedes. Schema notes
are in [data-model.md](data-model.md#the-specs-4-and-the-migrations).

Two questions remain open. Each is a product decision that the code does
not make on its own; what the code does meanwhile is stated with each:

1. **The novice exit's step format on an untested prerequisite** (§3.3, A142
   (d)). After a novice floor the probe ends and the plan starts on the
   lowest unproficient prerequisites (`backend/learning/probe.py::novice_floor`,
   `backend/learning/planner.py::prerequisite_ready`; the test
   `backend/tests/test_learning_goals.py::test_a_novice_floor_exits_the_probe_onto_the_lowest_prerequisite`).
   Each concept is taught in its own band's format, so a prerequisite the
   probe did not reach starts at the prior (`BKT_L0` = 0.35, the develop
   band) until its first graded answer. **Waits on the owner:** whether a
   novice exit should carry the novice format (worked example first) to such
   a concept, which would add a session-level input to the ceiling's typed
   state.
2. **Which surface enters exam mode** (§3.3's first ceiling row, A4, A142
   (e)). The row is implemented
   (`backend/learning/policy.py::ceiling_with_reason`,
   `backend/learning/gates.py::h6_allowed`) and reserved: no production code
   sets a step's `exam_mode`, which
   `backend/tests/test_learning_zpd_policy.py::test_exam_mode_is_reserved_no_production_code_sets_it`
   pins. **Waits on the owner:** a timed practice exam, an exam-proximity
   rule beside A13's retention target, or neither; that amendment updates the
   test.
