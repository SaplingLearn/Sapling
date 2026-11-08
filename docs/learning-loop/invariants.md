# Invariants: the rules you must not break

Each rule below says what it is, why it exists, and what enforces it. Most
are pinned by `backend/tests/test_learning_loop_invariants.py` (the spec's
§8 numbers them; `inv_N` below means the test `test_inv_N_…` there), and a
red test there means the change is wrong, not the test. When a rule is
enforced only by convention, this page says so.

## 1. One writer for evidence and the learner model

**Rule.** Only `backend/services/graph_service.py::apply_graph_update` writes
`node_mastery_events`, `learner_state`, the `graph_nodes` mastery mirror and
`learning_evidence_voids`. Routes collect `Evidence` on
`deps.pending_evidence` and call `backend/learning/evidence.py::flush_pending`
once; the quiz and the review queue call `apply_graph_update` directly with
the same `{"evidence": [...]}` payload. Inside, every batch goes through one
atomic SQL commit (`learning_evidence_commit`, ADR 0037).

**Why.** The belief must be a pure function of the graded journal: one
writer means one place where weights, propagation, FSRS and the mirror are
computed, so a void can replay them exactly, and a crash can never leave the
journal and the state disagreeing. Before the loop, the tutor itself moved
mastery scores; that is exactly what this rule removes (ADR 0030).

**Enforced by.**
- `inv_01_single_graph_writer` and its companions: a source scan of
  `backend/` for writes to those tables outside the writer; the evidence and
  void RPCs reachable only from `backend/learning/evidence_transaction.py`;
  no Python module writes the void table. `inv_21_no_legacy_mastery_writers`
  forbids the old flat mastery deltas. `inv_07` keeps every learning table
  behind `backend/db/connection.py`.
- `inv_14_tools_never_write_graph_tables`: the grading helper
  `backend/agents/tools/check.py::grade_answer` never persists and is not a
  tutor tool.
- The SQL itself: version checks, the owner lock and receipts
  (`backend/tests/integration/test_learning_evidence_transaction_db.py`).

**Known edges.** The scan exempts all of `backend/services/graph_service.py`, which also
holds topology writes (`delete_node`, `update_node_color`). The one
non-evidence `learner_state` write is
`backend/learning/learner_state.py::write_metrics` (four derived columns,
called only by `backend/scripts/derive_zpd_metrics.py`; `inv_20` keeps that
script idempotent).

## 2. Only an explicit answer is evidence, and missing is symmetric

**Rule.** Evidence comes only from an answer the student submitted through
an answer route: `/check/answer`, `/probe/answer`, `/review/answer`,
`/posttest/answer` (A16) — and, outside the loop, a submitted quiz answer
(`mc` evidence, A10, A94). A chat message, an `[ACTION: …]` turn, an attempt
on `/step/attempt` or a hint request is never graded. When the grader cannot
give a verdict — it is down, invalid or capped — **nothing** is recorded, for
a correct answer and for a wrong one alike.

**Why.** Grading chat would reward talking, and the tutor would grade its own
teaching. Recording only one side of an outage (say, only the wrong answers
that failed fast) would bias the belief in a direction no one could see.

**Enforced by.** `inv_26_evidence_only_from_explicit_submission` (an AST
allow-list of the handlers that may flush, plus a route test);
`inv_28_symmetric_missingness`; `inv_19_review_grades_through_grader_only`;
the grading claim (one grade per posed item, A52).

## 3. Belief changes only by the model's arithmetic

**Rule.** `p_known` is BKT with fixed, bounded parameters per channel, decay
at read, a cap at 0.999, one-hop asymmetric propagation; FSRS-6 with pinned
weights. Weights are derived from the evidence's flags in code
(`backend/learning/evidence.py::evidence_weight`), never passed in. Help
lowers credit (assisted: half; H4 and above: none); help never discounts a
wrong answer.

**Why.** These are the research-backed choices (BKT guess/slip per channel,
FSRS at 90% retention); letting a caller pass a weight would let any route
award credit.

**Enforced by.** `inv_03_channel_guess_slip_bounds` (every channel valid:
G + S < 1 and the bounds), `inv_13_fsrs_weights_pinned`, the BKT and FSRS
unit tests, and the commit's own range validation in SQL.

## 4. Void instead of delete

**Rule.** A journal row is never edited or deleted to retract it. Evidence
graded against an item staff retired is **voided**: an append-only row in
`learning_evidence_voids`, then the student's state is recomputed from the
non-void journal by the same code the writer uses
(`backend/learning/evidence_replay.py::replay`). Readers of evidence leave
void rows out (`backend/learning/void_store.py`,
`backend/learning/evidence_void.py`); readers of exposure — the seen and
revealed sets, the re-check rule — keep them. Misconceptions are closed, not
deleted.

**Why.** The journal is the audit trail and the replay input; deleting rows
would make a recompute irreproducible and would hide that the student did see
the question.

**Enforced by.** The trigger `learning_evidence_voids_no_update` and grants
of `SELECT, INSERT` only
(`backend/db/migrations/20261108115157_learning_evidence_void_grants.sql`);
`inv_01_the_void_record_is_written_by_no_python_module` and
`inv_01_the_void_branch_is_reached_only_through_apply_graph_update`;
`backend/tests/test_learning_evidence_void.py`,
`backend/tests/test_learning_evidence_replay.py` and
`backend/tests/integration/test_learning_evidence_void_db.py`.

## 5. Held items are served to no one

**Rule.** An item with a hold — a disputed, unsolved or audit-failed key
that nobody has confirmed, or a staff hold (`reports_threshold`,
`staff_retired`) — is never posed, and its key is never released. Every
student read drops it; every picker serves only
`backend/learning/checks.py::is_servable` items (a final answer, no hold).
The staff-hold codes are derived by the database from `check_item_reviews`;
Python never sets or clears them. Every quality gate on drafting fails
closed: an unavailable alignment or key check drops the drafts.

**Why.** A wrong key does double damage: it grades students wrong, and the
wrong-answer feedback teaches the wrong answer to the whole course (A124).

**Enforced by.** `backend/tests/test_learning_item_holds.py`,
`backend/tests/test_learning_item_keys.py`,
`backend/tests/test_learning_item_alignment.py`; the trigger
`check_items_staff_hold`; the evidence commit's refusal of a retired item.

## 6. The answer is withheld until it is earned

**Rule.** How much help a turn may give is a ceiling computed in code from
typed state (band, attempts, prerequisite status, band control), never from
the student's text. Help above the ceiling is not served; each rung after
the first needs a genuine attempt and a dwell; the full solution (H6) needs
two genuine attempts on a taught, ungraded practice item. Everything code
serves below H6 is leak-checked against the item's structured final answer;
model text is capped at H5 until the answer is released and is cut before
any sentence that would state it; and every served text is scanned against
**all** the student's open posed items, recording what it stated as revealed
the moment it is served (A88). If the scan cannot run, it fails closed: an
`unscanned` marker makes earlier poses grade as assisted.

**Why.** The research basis: answer-giving tutors raise practice scores and
lower unassisted performance (Bastani et al. 2025). A revealed answer later
submitted as the student's own would be full credit for nothing.

**Enforced by.**
- `inv_04_policy_takes_no_message_text` (policy functions take no `str`;
  `backend/learning/policy.py` imports neither `re` nor `gates`).
- `inv_27_deterministic_payloads_leak_checked` (every
  `ladder.deterministic_content` payload passes `detect_leak` with the final
  answer in the same function).
- `inv_29_source_chunks_visibility_aware` (an item's passages are read only
  through the visibility-aware `rag_service.chunks_for_ids`).
- `backend/tests/test_learning_served_scan.py`,
  `backend/tests/test_learning_teach_reveal.py`,
  `backend/tests/test_learning_leak_served_mode.py`,
  `backend/tests/test_loop_tutor_served_path.py`, and the E2E oracle that
  fails if a seeded final answer is served before its release rung
  (`backend/e2e_oracles/learn_loop.py`).
- Outside the loop, the notes chat, summaries and flashcard generators refuse
  a pasted posed item and withhold its key (A125;
  `backend/services/integrity_guard.py`,
  `backend/tests/test_learning_outside_integrity.py`).

## 7. The help floor: a grade carries the most help ever served

**Rule.** Just before evidence is written, the route re-reads the
per-student help ledger for that item (`learning_reveals`, kinds `help` and
`reveal`), and the evidence's `max_rung` is at least the most help the
student ever had on it — in any session, any surface (the tutor, review, the
quiz's "Ask about this", the notes chat). Help is written to the ledger
**before** it is served (A93). An unreadable ledger floors the grade at H4.

**Why.** Without it, a student could get hints in one session and answer
"unassisted" in the next (cross-session hint laundering, the review
finding that created A93).

**Enforced by.** `backend/learning/help_ledger.py::max_help` and the route's
`_refloor` step; `backend/tests/test_learning_help_ledger.py` and
`backend/tests/integration/test_help_ledger_db.py`.

## 8. A student's words never steer the tutor or the grader

**Rule.** Student text reaches the tutor model only inside an envelope with
a fresh random nonce (`backend/agents/loop_tutor.py::student_envelope`), and
the tutor's rules ride `instructions=` so they apply to every turn, not only
the first (A51, A61). The learner brief carries no model-written free text
(A62). Policy never reads student text (rule 6). An answer addressed to the
grader ("mark this correct") is refused before any model runs (A33), and a
correct answer the student disowns earns nothing (A97). Decision-seam states
carry no identifiers.

**Why.** Prompt injection: a student who can instruct the tutor or the grader
can award themselves credit or extract the key.

**Enforced by.** `inv_30_answers_addressed_to_the_grader_are_never_graded`;
`inv_25_decision_states_carry_no_identifiers`;
`inv_12_one_prompt_stack_per_series_agent` (one prompt, one agent per
module; the tutor uses `instructions=`);
`backend/tests/test_learning_answer_guard.py`,
`backend/tests/test_learn_loop_hardening.py`,
`backend/tests/test_learning_turn_template.py`,
`backend/tests/test_learning_close_brief.py`.

## 9. The kill switch and the flags

**Rule.** `LEARNING_LOOP_ENABLED` alone decides whether the loop runs, for
everyone; it is read at process start, and the gate is evaluated **once per
request, at route entry**, its answer carried on `SaplingDeps.learning_loop`
— agents, tools and services never call the gate. With it off, every loop
route answers 404 (the rate-limited ones before authentication and the rate
limiter even run; the others after the ownership check), except the status
probe `/review/active`, which answers `{"active": false}`; and no request
reaches the tutoring policy layer. Feature flags resolve fail-closed to
`off`, and the loop's flags all ship `off`.

**Why.** A kill switch must work even when the database is down and must not
leave a half-loop running; a flag that fails open would change pedagogy or
the measurement protocol without anyone deciding to.

**Enforced by.** `inv_11_gate_false_when_env_unset` (the parse table; no
table read), `inv_15_gate_never_inside_chat_stream`,
`backend/tests/test_learning_gate_route_entry.py`,
`backend/tests/test_kill_switch_gate_first.py`,
`backend/tests/test_kill_switch_spelling_warning.py`, the inertness scan in
`backend/tests/test_learning_zpd_policy.py`, and the E2E kill-switch lane.

## 10. Models: frozen mode, routed tiers, budget first, the function seam

**Rule.**
- The model mode (`real` or `function`) is frozen at boot
  (`backend/agents/_providers.py::freeze_model_mode`).
- Code picks the tutor tier; loop routes never read a student's model
  preference (`inv_22_loop_routes_ignore_model_pref`).
- Every grader, decision, tutor and close run is preceded, in the same
  function, by `ai_budget.check` (`inv_23_ai_budget_checked_before_every_run`).
- Every request-path loop task has a function-mode handler (`inv_06`), and the
  constants the E2E specs assert equal the handlers' (`inv_13a`).
- The TypeSafe SDK is imported only by `backend/agents/_jev.py`, and its client
  exists only in real mode with Jev enabled (`inv_24`).
- A loop slot's default moves from Gemini to Claude only with its eval
  re-recorded (`LOOP_SLOTS_PENDING_CLAUDE_EVAL`; `backend/tests/test_anthropic_provider.py`);
  an evidence slot on an unevaluated model warns at boot (A128).

**Why.** Agents are built at import; a mode that changes mid-process makes
some calls billable and others scripted. A model run without a budget check
is unbounded spend. An evidence slot is part of the measurement: changing its
model silently changes what "correct" means.

**Enforced by.** The tests named above,
`backend/tests/test_platform_lifecycle.py`,
`backend/tests/test_model_mode_seam.py`,
`backend/tests/test_e2e_function_handlers.py`,
`backend/tests/test_loop_slots_claude_ready.py`,
`backend/tests/test_learning_degraded_mode.py`.

## 11. Tests are hermetic; live calls are opt-in

**Rule.** The unit lane cannot reach a network, a database or a live model;
a billable test runs only when its `RUN_LIVE_*=1` variable is set; evals
replay recorded cassettes unless told to record.

**Why.** A test that silently calls a provider bills money, flakes, and
passes for the wrong reason.

**Enforced by.** `backend/tests/conftest.py` (the session-wide egress floor
and per-test guards), `backend/tests/live_opt_in.py`,
`backend/tests/test_hermetic_llm_guard.py`,
`backend/tests/test_hermetic_egress_floor.py`,
`backend/tests/test_live_opt_in.py`,
`backend/tests/test_slot_override_hermeticity.py`,
`backend/tests/test_eval_budget_hermetic.py`.

## 12. Migrations are immutable, and they ship before the code

**Rule.** Learning migrations are new files named
`<UTC timestamp>_learning_<desc>.sql`; an applied file is never edited; a
migration the code depends on is applied before the code (the release fence),
and some must ship in the same run (see
[operations.md](operations.md#migrations-and-their-rollout-order)).

**Why.** The migration ledger records file names, not contents: an edited
file is never re-run, so environments silently diverge. Code ahead of its
schema fails every evidence write.

**Enforced by.** `inv_08_series_migrations_named_and_never_modified` (the
name pattern; `git log --diff-filter=M` shows no edit except one sanctioned
commit), `backend/tests/test_migration_naming.py`,
`backend/tests/test_migrations.py`,
`backend/tests/test_learning_migration_functions.py` (a re-created function
keeps what earlier definitions required), and the release verifier's
`--db-audit` ledger check.

## 13. Encrypt at the boundaries

**Rule.** Item text and keys, closes, briefs, goal text, grade checkpoints
and misconception evidence are encrypted at write and decrypted only in
memory at read, including before they go into a prompt; nothing indexes,
filters or joins on them. A backend boots only with the encryption key its
database was written under.

**Why.** Student work and answer keys are sensitive; and a backend with the
wrong key would write rows its own environment can never read.

**Enforced by.** `inv_09_no_unique_or_eq_on_encrypted_learning_columns`; the
ciphertext oracle (`backend/e2e_oracles/gather.py`);
`backend/tests/test_learning_check_items_ciphertext.py`;
`backend/tests/test_encryption_canary.py`. Item ids and lookups use plaintext
hashes of the plaintext (`question_hash`), computed before encryption.

## 14. No student text in events or analytics; consent first

**Rule.** `zpd.*`, `learn.*`, `review.*`, `ai.*` and `decision.*` events carry
ids, counts, enums and numbers only — the emitters drop a payload with a
long string (`backend/learning/zpd_events.py`) — and every event type is
registered in `EVENT_TAXONOMY`. Events reach PostHog only through the
`events_service` mirror, only for a consenting student, decided on the
worker; LLM analytics carry model, tokens and cost, never content.

**Why.** The events table is plaintext and analytics leave the system.

**Enforced by.** `inv_05_series_event_names_in_taxonomy`;
`backend/tests/test_posthog_seam.py`; the payload checks in the
`zpd_events` emitters.

## 15. Purity and the smaller rules

- Pure modules import no agent, provider or database code (`inv_02`,
  `inv_16_probe_planner_pure`); see
  [architecture.md](architecture.md#the-purity-rules).
- The class misconception rollup is never a tutor tool (`inv_17`).
- Any `lru_cache` under `backend/learning/` needs a clear hook registered in
  `backend/tests/conftest.py` (`inv_10`). **This test is a skip placeholder
  today** — no such cache exists yet — so the first cache added must make it
  real.
- Every model call is a Pydantic AI agent; there is no raw provider client in
  the loop (repository rule; `CLAUDE.md`).
