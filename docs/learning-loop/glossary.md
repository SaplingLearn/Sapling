# Glossary

Spec term, in plain words, and where it lives in code. Terms are grouped by
area; within a group, the order follows the order you meet them. "Spec" is
[the learning-loop design spec](../superpowers/specs/2026-09-26-learning-loop-design.md);
"A*n*" is a row of its §13 amendments table (index: [amendments.md](amendments.md)).

## The learner model

| Spec term | Plain words | Code |
|---|---|---|
| Evidence | One graded observation of one student on one concept: correct or not, on which channel, with how much help. The only input that may change what Sapling believes a student knows (spec §1). | `backend/learning/evidence.py::Evidence` |
| BKT (Bayesian Knowledge Tracing) | The belief model: a probability that the student knows a concept, updated by Bayes' rule after each observation, with a fixed chance to learn per opportunity. | `backend/learning/bkt.py::update` |
| `p_known` | That probability, per (student, concept). Stored in `learner_state`, mirrored into `graph_nodes.mastery_score`. | `backend/learning/learner_state.py::LearnerState` |
| Prior, `BKT_L0` | The belief before any evidence: 0.35. | `backend/learning/params.py::BKT_L0` |
| Guess (G) and slip (S) | The chance a student who does not know answers correctly (guess), and the chance one who knows answers wrongly (slip). Each channel has its own pair. | `backend/learning/params.py::CHANNELS` |
| Channel | The kind of check an observation came from: `free_response`, `mc_reasoned` (multiple choice plus a reason), `mc`, `teachback_llm`, `chat_turn`. The channel is always the item's, never the student's choice. | `backend/learning/params.py::CHANNELS` |
| Strong channel | A channel hard to pass by guessing (`free_response`, `mc_reasoned`). Mastery needs three strong unassisted observations. | `backend/learning/params.py::STRONG_CHANNELS` |
| idk | An explicit "I don't know". It is a flag, not a channel: an incorrect observation with a near-zero slip (`S_IDK`), A1. | `backend/learning/evidence.py::Evidence` |
| Weight | How much one observation moves the belief. 1.0 is full; a correct answer after H1–H3 (assisted), a re-check and a grader confidence below 0.6 each halve it, and so does a multi-concept answer, right or wrong (A141); a correct answer after H4–H6 gets 0 (no upward credit). Help never discounts a wrong answer. Derived from the flags in code, never taken from the caller. | `backend/learning/evidence.py::evidence_weight` |
| Propagation | One hop along prerequisite edges, asymmetric: a correct answer adds a weak (`chat_turn`-strength, half-weight) correct observation to each direct prerequisite; a wrong answer adds a wrong observation to each direct dependent. | `backend/learning/bkt.py::propagate_prereq` |
| Decay at read | Belief drifts back toward the prior between checks along the forgetting curve; it is computed when read, not stored. | `backend/learning/bkt.py::decayed_p` |
| Band | A coarse level from `p_known`: novice (below 0.30), develop (0.30 to below 0.80), profic (0.80 and up). The band sets how much help is allowed. | `backend/learning/bkt.py::band` |
| Mastery tier | The display level stored on `graph_nodes.mastery_tier`: unexplored (below 0.10), struggling (below 0.30), learning (below 0.95), mastered. Not the same as a band, and not the same as a model tier. | `backend/learning/bkt.py::tier_for` |
| Proficient, mastered | `p_known` ≥ 0.95; mastered also needs ≥ 0.98 and three strong unassisted observations. | `backend/learning/bkt.py::is_mastered` |
| FSRS-6 | The spaced-repetition scheduler. It models memory with a stability (days until recall drops to 90%), a difficulty (1 to 10) and the retrievability R (the current chance of recall). | `backend/learning/fsrs.py::next_state` |
| Retention target | The recall level at which the next review is due: 0.90 by default, 0.95 near an exam, 0.85 for a large set. | `backend/learning/fsrs.py::retention_target` |
| Rating | FSRS's grade of one review (Again, Hard, Good; the loop never emits Easy), derived from correctness and help. | `backend/learning/fsrs.py::rating_for` |
| Journal | `node_mastery_events`: the append-only log of every evidence row. State is a projection of it. | `backend/services/graph_service.py::apply_graph_update` |
| `evidence_seq` | The order of rows written by one evidence commit (they share a timestamp), A36. | `backend/db/migrations/20260927182054_learning_mastery_event_seq.sql` |
| Single writer | The one function allowed to write the graph and learner tables. | `backend/services/graph_service.py::apply_graph_update` |
| Operation receipt | The record that one evidence batch committed as a whole, so a retry after an ambiguous failure never double-counts (ADR 0037). | `backend/learning/evidence_transaction.py::commit_evidence_transaction` |
| Snapshot | The owner- and course-scoped read the writer plans from: nodes, learner rows, prerequisite edges and prior exposures, with row versions checked at commit. | `backend/learning/evidence_transaction.py::EvidencePlan` |
| Stated confidence | The student's own 3-point confidence on a graded answer, stored as `student_confidence`; never a weight, A127. Distinct from the grader's `confidence`. | `backend/learning/evidence.py::stated_confidence` |

## Check items

| Spec term | Plain words | Code |
|---|---|---|
| Check item | A generated question with a rubric, a reference answer, a structured final answer and, for multiple choice, options. A course asset shared by every student of the course, keyed on (course, concept key). | `backend/learning/checks.py::CheckItem` |
| Format | `free` (free response), `teachback` (explain it back), `mc_reason` (pick an option and give a reason). Each format maps to one channel. | `backend/agents/tools/check.py::CHANNEL_FOR_FORMAT` |
| Concept key | The normalised concept name an item is filed under (whitespace collapsed, case-folded). | `backend/services/check_item_service.py::concept_key` |
| `question_hash` | The stable identity of an item, a hash of its plaintext prompt. Every seen, revealed, reported and void set is a set of these. | `backend/learning/checks.py::question_hash` |
| Final answer | The short answer stated verbatim in the reference; the leak check matches it instead of parsing the reference, A34. | `backend/learning/checks.py::answer_tokens` |
| Drafting | Generating items for a concept from course passages after an upload. | `backend/services/check_item_service.py::generate_for_concepts` |
| Top-up | A second drafting call that adds `mc_reason` items a concept is short of, A37. | `backend/agents/check_items_topup.py` |
| Lint flag | A stable code for an item-writing flaw (for example the correct option is uniquely longest), stored in `check_items.lint_flags`, A113. | `backend/learning/item_lint.py::lint_item` |
| Alignment check | A model check that each rubric criterion is asked by the question and that the item tests the concept it is filed under, A119. | `backend/learning/item_alignment.py::align` |
| Key check, blind solve | A different model solves the item without seeing the key; code compares its answer with the key, A124. | `backend/learning/item_keys.py::compare` |
| `canonical_verified` | True only when an independent solve agreed, staff approved the item or an audit found the key correct. | `backend/services/check_item_service.py::confirm_course_item` |
| Hold | A lint code that keeps an item from every student: a key hold (`key_disputed`, `key_unsolved`, `key_audit_wrong`, `key_audit_ambiguous`, while the key is unconfirmed) or a staff hold (`reports_threshold`, `staff_retired`). | `backend/learning/checks.py::held_flags` |
| Servable | States a final answer and is not held. Only servable items are ever posed. | `backend/learning/checks.py::is_servable` |
| Report, quarantine | A student's "Report this question". Two reporters put the item on a staff hold (quarantine); nothing is deleted. | `backend/learning/item_reports.py::record_report` |
| Staff retire | An admin decision that an item is broken: it is held, every student's evidence on it is voided, then it is deleted. | `backend/services/check_item_service.py::retire_course_item` |
| Audit | Staff judge a stratified sample of keys; the report gives a key-error rate with a Wilson 95% interval. | `backend/learning/item_audit.py::wilson` |
| Unsourced item | An item drafted from a document's extracted text because indexing failed, so it has no passage to show at H2, A128. | `backend/learning/checks.py::unsourced` |
| Isomorph | Another item on the same concept, in the same format and difficulty, with a different hash: the same question in a different surface. | `backend/learning/policy.py::next_isomorph` |
| Serve quality | The tie-break every picker applies: a confirmed key first, then clean lint, then sourced over unsourced, A129. | `backend/learning/checks.py::serve_quality` |
| Surface descriptor | How a varied item presents its idea: a representation (`verbal`, `symbolic`, `numeric`, `visual`, `applied`; plaintext) and a scenario label of at most four words (encrypted), A140. | `backend/learning/surface.py::surface_of` |
| Cue familiarity | How many of an item's surface parts (representation, scenario) the student has already met on the concept; pickers prefer the least familiar among items otherwise equal. An item with no descriptor is neutral. A140. | `backend/learning/surface.py::familiarity_by_hash` |
| Definitional item | A difficulty-1 check item (recall or definition). With `varied_isomorphs` on, review never interleaves it, A140. | `backend/learning/params.py::INTERLEAVE_DEFINITIONAL_DIFFICULTY` |
| Multi-concept item, combination | One question that combines an **apex** concept with one or two of its direct prerequisites (its **components**) and can be answered only by using them all; stored under the components' joined keys, A141. | `backend/learning/multi_concept.py::combo_key` |
| Component gate | A multi-concept item is posed only when every component is proficient: p ≥ 0.95 with a strong unassisted observation behind it. | `backend/learning/multi_concept.py::gate_open` |
| Ideas-combined dial | When a multi-concept item may replace a concept's next check: at most once a session per concept, after a graded check on the concept, while its difficulty is at the top, never in a goal session. | `backend/learning/multi_concept.py::dial_open` |
| Apex observation | The one half-weight observation a multi-concept answer records, on the apex only; the components move only by propagation. | `backend/learning/params.py::WEIGHT_MULTI_CONCEPT` |

## A session

| Spec term | Plain words | Code |
|---|---|---|
| Loop | The tutoring system as a whole: probe → plan → teach ⇄ check → feedback → close, plus spaced review and the delayed post-test. | `backend/routes/learn_loop.py` |
| Phase | Where a session is: `probe`, `plan`, `teach`, `check`, `feedback`, `close`. | `backend/learning/params.py::CLOSE_PHASES` |
| `loop_state` | The session's JSON state document on `sessions.loop_state`, saved only by compare-and-set on `loop_state_rev`. | `backend/learning/loop_state_store.py::update_loop_state` |
| Compare-and-set (CAS) | A save that succeeds only if the row's revision is still the one loaded; the loser reloads and reapplies its change. | `backend/learning/loop_state_store.py::save_loop_state` |
| Goal | Concepts the student confirms they want to learn (one to twelve); planning is limited to them and their prerequisites (ADR 0033). | `backend/learning/goals.py::encode_goal` |
| Probe, check-in | The opening diagnostic: a few unaided questions per concept to find where the student is. Answers are graded evidence. | `backend/learning/probe.py::next_probe_item` |
| Strand | One concept the probe is testing. | `backend/learning/probe.py::graded_strands` |
| Novice floor | A session-wide stop for the probe after enough misses or "I don't know"s; a fatigue stop, not proof of a floor. | `backend/learning/probe.py::novice_floor` |
| Outer fringe | Concepts not yet proficient whose prerequisites all are: what the student is ready to learn next. | `backend/learning/planner.py::outer_fringe` |
| Plan | The ordered concepts for this session: due reviews, then new fringe concepts (at most five), then siblings. The student approves it. | `backend/learning/planner.py::plan` |
| Learner brief | A bounded description of where the student stands, built from structured data once per session and stored encrypted. | `backend/learning/learner_brief.py::build_brief` |
| Teach turn | A tutor turn in the teach phase: key idea, body, one question. | `backend/learning/turn_shape.py::render_turn` |
| Model tier | Which tutor model a turn runs on: `lite`, `standard`, `deep` or `none` (no model call). Chosen in code. | `backend/learning/policy.py::model_tier` |
| Pose | Showing a check item to the student. A posed item is open until it is graded. | `backend/learning/help_ledger.py::record_posed` |
| Activation | Picking the next item for the plan's current concept and making it the active check. | `backend/services/loop/practice.py::_activate_next_item` |
| Seen set | Every item hash in the student's evidence rows. Pickers exclude it (the probe falls back to a seen item only when nothing unseen is left). | `backend/learning/loop_state_store.py::seen_hashes` |
| Revealed set | Items whose answer the student has been shown (wrong answer, worked solution, a served tutor text that stated it). Excluded like seen items. | `backend/learning/loop_state_store.py::revealed_hashes` |
| Reported set | Items the student reported; excluded for that student. | `backend/learning/loop_state_store.py::reported_hashes` |
| Explicit submission | An answer sent through the answer box (`/check/answer`, `/probe/answer`, `/review/answer`, `/posttest/answer`). The only thing ever graded, A16. | `backend/routes/learn_loop.py::_grade_submission` |
| Grading claim | A marker taken by CAS before grading, so one posed item is graded once, A52. | `backend/routes/learn_loop.py::_grade_submission` |
| Grade checkpoint | An encrypted, owner-bound record of a finished grade saved before its evidence commits, so a crash is recovered without grading twice (ADR 0038). | `backend/learning/grade_checkpoint.py::seal` |
| Turn activity | Prose-free timing and fencing for a tutor turn, so an interrupted turn cannot earn help-gate time (ADR 0036). | `backend/learning/turn_activity.py::begin` |
| Feedback turn | One tutor turn after a graded answer, opening with the verdict, never ending on the answer. | `backend/routes/learn_loop.py::_LoopTurn` |
| Close | The end-of-session record: a summary, a self-evaluation prompt and an "If …, then …" plan, stored encrypted on `sessions.close_json`. | `backend/learning/session_close.py::build_close` |
| Segment | The stretch of a session spent on one concept, from the moment the plan's cursor reaches it until it moves on. | `backend/learning/prequestion.py::segment_open` |
| Segment prequestion | One ungraded guess at a vetted question when a segment opens, followed at once by the answer and why. Never evidence; the item becomes revealed. A138, flag `segment_prequestion`. | `backend/learning/prequestion.py::choose` |
| Pool rule | A prequestion item is taken only if enough fresh items stay for the segment's graded checks (`PREQUESTION_MIN_CHECKS_LEFT`). | `backend/learning/params.py::PREQUESTION_MIN_CHECKS_LEFT` |
| Self-explanation prompt | A "why does this follow?" question that replaces the turn's own question at a code-decided juncture; the reply is stored for diagnosis only, never evidence. A139, flag `self_explanation_prompts`. | `backend/learning/self_explain.py::PROMPTS` |
| Juncture | Where a self-explanation prompt may appear: a worked example (H4), a released solution (H5, H6 or answer feedback), or a first unhelped correct answer. At most one per concept per session. | `backend/learning/self_explain.py::juncture` |

## Help: the ladder and its gates

| Spec term | Plain words | Code |
|---|---|---|
| Rung, H0–H6 | One level of help. H0 acknowledge, H1 focus question, H2 point at the course passage, H3 leading question about the next step, H4 worked example on an isomorph, H5 completion problem, H6 full solution. | `backend/learning/ladder.py::RUNG_INTENT` |
| Assisted | Any rung H1 or above was used before the answer. A correct assisted answer after H1–H3 counts at half weight and FSRS Hard. | `backend/learning/params.py::RUNG_ASSISTED_MAX` |
| No credit | A correct answer after H4–H6 (the student saw a worked example or more): weight 0, no upward belief change, FSRS Again. | `backend/learning/params.py::RUNG_NO_CREDIT_MIN` |
| Ceiling | The highest rung a turn may reach, computed in code from band, phase, attempts and mode — never from the student's text. | `backend/learning/policy.py::ceiling_with_reason` |
| Genuine attempt | An attempt that counts toward unlocking the next rung: non-empty text or shown work, not a plea alone such as "just tell me", made after the band's independent time (45 s; 90 s for a novice). | `backend/learning/gates.py::is_genuine_attempt` |
| Strict attempt | The stricter rule behind the `help_gate_strict` flag: time alone with the latest hint, and something new, A134. | `backend/learning/gates.py::strict_genuine_attempt` |
| Rung unlock | The next rung opens after a dwell time on the current one and a genuine attempt since it was shown. | `backend/learning/gates.py::rung_unlock` |
| H6 gate | The full solution only after two genuine attempts on a taught, practice, ungraded item, never in exam mode, A32. | `backend/learning/gates.py::h6_allowed` |
| Deterministic content | Help assembled by code, not a model: the H2 passages, an H4 sibling, the H6 reference. | `backend/learning/ladder.py::deterministic_content` |
| Worked example first | A novice whose prerequisite is not known opens on a worked example (H4), then a completion problem, then near transfer, A122. | `backend/learning/policy.py::opens_on_worked_example` |
| Band controller | After a graded check, makes the next item harder, easier or stops practice, from the concept's recent unassisted first attempts, A122. | `backend/learning/policy.py::band_verdict` |
| Wheelspin | Many opportunities with no progress: the loop repairs a prerequisite instead. | `backend/learning/policy.py::wheelspin` |
| Help ledger | Per student and item, the most help ever served, in any session or surface. A grade's help floor is that maximum, A93. | `backend/learning/help_ledger.py::max_help` |
| Earnest-revise | A measured gate: how often a student with a genuine attempt was denied a rung, A109. | `backend/learning/earnest_revise.py::earnest_revise` |
| Help abuse, bottom-out | Climbing quickly to solution-level help (H5/H6) through attempts that say nothing; reported for staff, A133. | `backend/learning/help_abuse.py::help_abuse` |

## Answer withholding

| Spec term | Plain words | Code |
|---|---|---|
| Leak | Tutor text that states an item's answer: a run of reference tokens, the final answer, or the item's stem. | `backend/learning/leak.py::detect_leak` |
| Leak cut, `retract` | How a served turn avoids a leak: the stream stops before the sentence that would state the answer and a `retract` event tells the client to discard what it showed; a final text that still leaks is replaced by the ladder's fallback line. Nothing is masked in place (A51); the unused stripper was removed (A142). | `backend/services/loop/served.py::served_model_text` |
| Served text | The text the student actually receives, after the code-side template and the strip. Evals score this, not raw model output, A48. | `backend/services/loop/served.py::served_model_text` |
| Served scan, reveal | Every served tutor text is scanned against the student's open posed items; an item it states is recorded as revealed, at serve time, A88. | `backend/learning/served_scan.py::ScanSet` |
| Unscanned marker | When a turn's open items cannot be read or scanned, an `unscanned` row is written instead, and every item posed before it is then graded as assisted (fail closed). | `backend/learning/reveal_store.py::record_unscanned` |
| Answer guard | Deterministic screen of the student's answer before grading: text addressed to the grader is refused, A33. | `backend/learning/answer_guard.py::screen` |
| Disowned answer | A correct answer the student frames as false ("a common misconception is …") earns no credit, A97. | `backend/learning/answer_guard.py::disowned` |
| Envelope, nonce | Student text reaches the tutor model only inside a delimiter with a fresh random nonce, so it cannot pose as instructions, A51. | `backend/agents/loop_tutor.py::student_envelope` |
| Outside surfaces | The notes chat and summaries and the flashcard generators: they refuse a pasted posed item and withhold its key, A125. | `backend/services/integrity_guard.py::open_guard` |

## Misconceptions

| Spec term | Plain words | Code |
|---|---|---|
| Wrong key | A plaintext id for a known wrong reason listed on an item; stored only when the student's reason matched it. | `backend/learning/misconceptions.py::is_key` |
| Slip / misconception / novice | The three readings of a wrong answer: a careless error, a stable wrong belief (same wrong key on two isomorphs, or a confident wrong answer) or not yet knowing. Each gets a different response. | `backend/learning/misconceptions.py::slip_or_misconception` |
| Confront | A feedback turn that names the wrong belief and contrasts it with the right one. | `backend/learning/misconceptions.py::confront_of` |
| Isomorph re-ask | After an unknown or released answer, the next check on the concept is an isomorph. | `backend/learning/misconceptions.py::owed_isomorph` |
| Re-check after release | An item served after its concept's answer was shown counts as a re-check, at reduced weight, A76. An answered segment prequestion is such a release (A138). | `backend/learning/misconceptions.py::recheck_after_release` |
| Resolve | An open misconception closes on a correct unassisted answer to an isomorph, or when its evidence is voided, A127, A123. | `backend/learning/misconceptions.py::resolve` |
| Rollup | Per course concept, the wrong keys held by at least five students (never per student). | `backend/learning/misconceptions.py::rollup` |

## Review and the post-test

| Spec term | Plain words | Code |
|---|---|---|
| Due queue | Today's review: due flashcards and due concepts, ordered and cut to a daily time budget. | `backend/learning/review.py::due_queue_with_stats` |
| DASH order | Serve first the items whose predicted recall is nearest 0.33 (overdue triage). | `backend/learning/fsrs.py::order_due` |
| Confusable, interleave | Concepts easily mixed up (prerequisite siblings, or sharing an open wrong key) are served next to each other in review, A114. | `backend/learning/interleave.py::serve_order` |
| Review session | A daily `sessions` row with `mode='review'`; not a tutor session, A73. | `backend/learning/review.py::review_session_id` |
| Post-test | A delayed, tool-removed check: no hints, no course passages, no brief. The outcome measure. | `backend/routes/learn_loop.py::posttest_start` |
| Anchor | A concept's first graded evidence; post-test windows count from it. Practice cannot move it. | `backend/learning/posttest_store.py::posttest_anchors` |
| Window | A fixed delay after the anchor at which the post-test is offered: 7 and 28 days; the last window closes at 56 days. | `backend/learning/learning_gain.py::window_at` |
| Reserve | Up to two items per concept protected for the post-test: never used in the probe, checks or review. | `backend/learning/checks.py::posttest_reserve_hashes` |
| Pose TTL | An unanswered post-test pose is void after 24 hours, A89. | `backend/learning/params.py::POSTTEST_POSE_TTL_HOURS` |
| Skip reason | Why a due window had nothing to pose: `no_items`, `exhausted`, `reported`. | `backend/learning/checks.py::posttest_skip_reason` |
| Pretest, matched pretest | The concept's first graded answer, used as the "before" of a pair; behind `probe_matched_pretest` the probe asks a form parallel to the reserves, A130. | `backend/learning/checks.py::pretest_form` |
| Learning-gain pair | One (student, concept, window) with both a pretest and a post-test outcome. | `backend/learning/learning_gain.py::learning_gain` |
| Funnel | Per window: due, posed, answered, expired, skipped — so missing outcomes are counted, A126. | `backend/learning/learning_gain.py::posttest_funnel` |
| Calibration | Does BKT's predicted chance of a correct unassisted answer match how often students were correct (Brier score, ECE). | `backend/learning/calibration.py::calibration` |

## Voids

| Spec term | Plain words | Code |
|---|---|---|
| Void | A journal row that no longer counts as evidence because its item was staff retired. Marked by an append-only row in `learning_evidence_voids`; the journal row itself is never edited or deleted, A123. | `backend/learning/evidence_void.py::is_void_row` |
| Recompute, replay | After a void, the student's state is rebuilt from the non-void journal with the same code the writer uses. | `backend/learning/evidence_replay.py::replay` |
| Evidence reader vs exposure reader | Readers of evidence (spans, planning, close, brief, item statistics) leave void rows out; readers of exposure (seen, revealed) keep them. | `backend/learning/void_store.py::voided_event_ids` |

## The quiz

| Spec term | Plain words | Code |
|---|---|---|
| Quiz plan | The quiz home's proposals from the learner model: FSRS-due reviews, then concepts with an open misconception, then concepts the student is ready for, A143. | `backend/learning/quiz_plan.py::rank_concepts` |
| Question spec | What one planned quiz question must be: its slot, its difficulty, and the misconception one distractor targets, A144. | `backend/learning/quiz_plan.py::QuestionSpec` |
| Tag | The misconception key a quiz distractor embodies, kept only when the plan named it; stored, never served, A144. | `backend/learning/quiz_gates.py::validate_tags` |
| Gate (quiz) | A generated quiz question's verdict from the loop's concept check and blind key solve: verified (evidence), practice (served, never evidence) or dropped (never served), A145. | `backend/learning/quiz_gates.py::decide` |
| `quiz_check` | The model slot the quiz's checks run on, which must differ from the quiz writer's, A145. | `backend/services/quiz_learning.py::checks_independent` |
| Learning block | The quiz results' account of what changed: the skill meters that moved, what is due, the next step, A147. | `backend/services/quiz_learning.py::results_block` |

## Models, cost and modes

| Spec term | Plain words | Code |
|---|---|---|
| Slot, task | A named model role (`grader`, `loop_tutor`, …) with a default model and settings. | `backend/agents/_providers.py::model_for` |
| Effort | Claude's quality/cost dial per slot (`low`, `medium`, `high`). | `backend/agents/_providers.py::_ANTHROPIC_EFFORT` |
| Pending Claude eval | The loop slots that still default to Gemini until their eval datasets are re-recorded on Claude. | `backend/agents/_providers.py::LOOP_SLOTS_PENDING_CLAUDE_EVAL` |
| Evidence slot | A slot whose output is evidence or what evidence is graded against; running one on an unevaluated model logs a warning and an event. | `backend/agents/_providers.py::EVIDENCE_SLOTS` |
| Second opinion | A re-grade on a different model (`grader_second`): it replaces a first run that is invalid or below 0.4 confidence, and confirms a verdict that credits something when the first run contradicts itself or the answer looks suspicious (then both must credit). | `backend/agents/grader.py::grade` |
| Learning decision seam | The loop's typed closed judgments (is this reason correct, which wrong key matched) with selectable backends, including Jev. | `backend/services/learning_decisions.py` |
| Jev | TypeSafe's typed decision model, reached only through the decision seams. | `backend/agents/_jev.py` |
| Model mode | `SAPLING_MODEL_MODE`: `real` (call providers, the default) or `function` (deterministic handlers); `cassette` is reserved and raises; any other value is an error. Frozen at boot. | `backend/agents/_providers.py::model_mode` |
| Function handler | A fixed reply registered per task for function mode; the E2E lanes assert its constants verbatim. | `backend/agents/_providers.py::register_function_handler` |
| Routable tier | A tutor tier that passed three fresh eval recordings; today `standard` and `deep`. Lite turns route up. | `backend/agents/loop_tutor.py::LOOP_ROUTABLE_TIERS` |
| Cassette, baseline | A recorded model response replayed by the eval suite; the scores it must keep. | `backend/tests/evals/_replay.py` |
| AI budget, degradation ladder | Per-student dollar, token and call caps; at the soft level context shrinks, at the hard level no model runs. | `backend/services/ai_budget.py::check` |
| Arm, variant | Within-student randomisation of concepts to policy variants for trials (`user_settings.loop_arm`). | `backend/learning/arms.py::variant_for` |

## Switches

| Spec term | Plain words | Code |
|---|---|---|
| Kill switch | `LEARNING_LOOP_ENABLED=false` (or `0`, `off`, `no`) turns the loop off for everyone at the next process start; unset means on. | `backend/learning/gate.py::learning_loop_active` |
| Feature flag | A per-student switch declared in code and configured in the database; `off` is always the safe default. | `backend/services/feature_flags.py::REGISTRY` |
| Release fence | The rule that a migration a code change depends on is applied before the code ships. | `docs/operations/learning-engineering-readiness.md` |
| Package (PKG-*nn*), hand-off | The build units of the original series and their completion notes; the spec's "affects" column cites them. | `docs/superpowers/specs/2026-09-26-learning-loop-design.md` |
