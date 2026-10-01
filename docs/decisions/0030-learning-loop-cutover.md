# 0030: The learning loop replaces LLM-moved mastery, and becomes every student's default

- Status: accepted; cutover pending owner launch
  - learning_loop_beta retired: 2026-09-30 (PKG-14b) — the gate no longer
    reads it; the column stays dead.
  - Cutover built, not executed: the half B code (`feat/learning-loop-14b-cutover`)
    merges into `feat/learning-loop` with half A after the B6 two-lane E2E gate;
    nothing is merged to `main` yet, and PR #673 is a draft until the owner
    launches. The owner's runbook (HANDOFF-14 §Launch runbook) appends
    `Cutover executed: <date>, <merge commit>` and `Launched: <date>`.
  - Review round 2026-09-30/10-01: spec §13 A93–A97 (the per-student help
    ledger, quiz-evidence farming, the stored-tier re-derive, the smaller fixes,
    disowned answers earn no credit).
- Date: 2026-09-29
- Relates to: `docs/superpowers/specs/2026-09-26-learning-loop-design.md` (the
  spec; §1, §5, §7, §10, §11, §13 A14–A23, A33, A40, A45, A79), ADR 0024 (honest
  degrade — one Pydantic AI seam, no second prompt on failure), ADR 0027 (the
  typed decision seam, PKG-05b), ADR 0015 (the tutor this replaces), #620
  (feature flags — no flag system in this series), PR #673
- Supersedes: none
- Number: 0027, 0028 and 0029 are claimed by the open PRs #672, #677 and #705
  (spec §13 A45); this ADR takes the next free number, 0030.

## Context

Before the series, a student's mastery score moved two ways, and neither was
evidence. The legacy tutor held an `update_mastery_tool` and chose, by itself,
how far a concept moved after a chat turn. The quiz added a flat
`MASTERY_DELTA_PER_CORRECT` / `_PER_WRONG` per answer. The Learn and Tree
screens then cut the score at 0.10 / 0.45 / 0.75 into tiers. Nothing
separated knowing an answer from being told it, a hint from an unaided
answer, or a guess from a slip.

The research the series is built on (`docs/research/learning-loop/`) says the
same thing from three sides. Mastery should be a per-concept knowledge
estimate (BKT) updated only by graded observations, with guess and slip per
channel. Forgetting should be modelled (FSRS). Help should be a ladder
bounded by the learner's state (the zone of proximal development). And
learning should be measured by tool-removed, delayed checks, not by in-session
accuracy.

The owner decided on 2026-09-26 that the loop is the new default learning
system for every student, with no opt-in and no beta-cohort waiting period
(spec §13 A14). In the same set of decisions the owner chose the cost plan:
routed model tiers at about $0.36 per student-month (A15), accepted the
proposed caps (A20), and recorded 06b's usage fields (A21).

## Options considered

1. **Keep the tool, tighten its bounds.** Clamp `update_mastery_tool`'s delta,
   require a quoted student sentence, keep the quiz deltas smaller. Rejected:
   the model still decides what counts as evidence, and no bound turns a chat
   impression into an observation with a known guess and slip rate.
2. **Evidence-only writes behind a flag, then cut over** (chosen). Build the
   loop dark behind a build-phase gate. Make graded evidence through
   `apply_graph_update` the only mastery writer. Measure it with the ladder
   below. Then flip the default in one reviewed change (half B) that deletes
   the legacy writers.
3. **Big-bang rewrite.** Replace the tutor, the quiz scoring and the tiers in
   one release with no dark period. Rejected: no way to verify each package
   against the real stack before students see it, and no kill switch.

## Decision

**Evidence-only mastery (spec §1, §5).** A mastery score moves only when
graded evidence reaches `services/graph_service.py::apply_graph_update`: a
check, probe, review or post-test answer graded through
`agents/tools/check.py::grade_answer`, or a quiz or flashcard answer (PKG-11).
No tutor tool, no quiz delta and no route writes `learner_state`,
`node_mastery_events` or `graph_nodes.mastery_score` any other way (spec §8
invariants 1, 14, 26; half B adds invariant 21).

- **One deliberate exception** (spec §13 A79, PKG-14):
  `learning/learner_state.py::write_metrics`. It UPDATEs only the four
  derived ZPD columns (`htc_k`, `unassisted_next`, `assist_gap`, `in_zone`)
  and `updated_at`, and only `scripts/derive_zpd_metrics.py` calls it
  (invariants 1 and 20). It never creates a row and never touches `p_known`.

**The loop is the default for every student, with no opt-in (spec §13 A14).**
The flag has two phases (spec §7):

- **Build phase (PKG-00 … PKG-14a).** Everything is dark behind
  `LEARNING_LOOP_ENABLED` (unset means off) AND `user_settings.learning_loop_beta`.
  The second is a staff/QA toggle, set by SQL or the local seed, read only by
  `learning/gate.py`, and in no settings API field (A31). It fails closed.
- **After launch (half B).** The gate is env-only, with the exact parse:
  unset or empty means ON; `false`, `0`, `off` or `no` (any case, whitespace
  ignored) means OFF. It reads no `user_settings`.
  - `learning_loop_beta` is retired: the column stays and nothing reads it.
  - `LEARNING_LOOP_ENABLED` survives only as a kill switch.

**What the kill switch restores, and what it does not (spec §11.6).**
`LEARNING_LOOP_ENABLED=false` plus a redeploy restores:

- the pre-loop Learn screen;
- the legacy `chat_tutor` agents, without the mastery tool;
- the legacy Study flashcards UI;
- a 404 on `/api/learn/loop/*`.

It does NOT restore:

- quiz or flashcard mastery deltas;
- the 0.1 / 0.45 / 0.75 tier cuts;
- any mastery recording on that path.

No legacy writer exists after half B, so the legacy tutor records no
mastery at all. The kill-switch path is cost-bounded too: the rate limit, and
`ai_budget.check(user, "tutor", "develop")` before any legacy agent runs (A20).
A passing check also counts one tutor call (`ai_budget.count_tutor_call`), so
the A39 daily call-count cap holds on that path even when `llm_usage` reads
nothing (spec §13 A91).

**After launch, the Learn screen never fails open to the legacy tree** (spec
§11.2, §13 A91). Only `/api/learn/loop/status` 404 or `{active: false}` — the
kill switch — renders it; a 5xx, a network error or a timeout renders a retry
state (`loop-status-error`), because the backend delegates the legacy calls to
the loop and a legacy screen over them would be a hybrid.

**The cost guardrails the launch gate requires (spec §11.1 item 4).**

- **A15 routing.** `policy.model_tier` picks one of three tier slots
  (`loop_tutor_lite`, `loop_tutor`, `loop_tutor_deep`). A slot routes only
  when three fresh recordings all pass every served-path eval (A49). The loop
  routes never read `model_pref` (invariant 22).
- **A18 limits.** `LOOP_LIMITS` and per-run `max_tokens`.
- **A20 cost guard.** `services/ai_budget.py`: band-aware per-student caps,
  the degradation ladder, and the daily tutor-call count cap (A39).
  - **Arm sessions** (`user_settings.loop_arm` non-empty) are never
    downgraded; they pause at the hard level instead.
  - **Platform budget: alert-only.** Production sets
    `PLATFORM_DAILY_BUDGET_USD=5` (A39 (e)), after the owner has proved the
    staging alert fires with a deliberately low value.
- **A21 usage observability.** `llm_usage` rows carry the tier slot in `task`
  and `cached_tokens` / `thinking_tokens`.

The target is about **$0.36 per student-month**.

**The evaluation ladder (spec §10), and what Sapling implements for each rung.**

1. **Offline evals** (`tests/evals/`). They run per tier slot and gate the
   SERVED text, not the raw model text. The datasets are `grader`,
   `check_items`, `decisions`, `loop_tutor` (answer-leak, "student insists on
   a wrong claim" and ceiling fixtures), `misconception_confront` and
   `session_close`.
   - Each floor is the minimum of three recordings (A40 06(s)), written by
     `tests/evals/floors.py` from `SAPLING_EVAL_RUNS_LOG`.
2. **Online metrics.**
   - `scripts/derive_zpd_metrics.py` runs nightly. It derives the four ZPD
     columns and prints a cost report: per band, per session (`zpd.step`
     carries the session id, spec §13 A82; per user-day only for rows with no
     session key), tier mix, `grader_backend` mix, cap hits and check-item
     coverage.
   - `GET /api/admin/analytics/learning-loop` (admin only) serves the three
     KPIs and two measurable gates. The KPIs are: the in-band share, the
     `htc_k` trend per concept, and unassisted success on the next session's
     first item. The gates are zero leaks and ≥ 95 % ceiling compliance.
   - Within-student A/B arms: `user_settings.loop_arm` plus
     `learning/arms.variant_for`, which hashes (arm, user, node). They are
     plumbing only. With `loop_arm` NULL (everyone, until the owner sets one
     by SQL), every concept is variant A and nothing changes.
     - The first experiment (owner decision, 2026-09-29) is the variant-B
       independent-time gate: `GATE_INDEPENDENT_MIN_S_VARIANT_B` (90 s)
       against `GATE_INDEPENDENT_MIN_S` (45 s) for develop/profic concepts;
       novice concepts keep `GATE_INDEPENDENT_MIN_S_NOVICE` in both arms. The
       owner starts it by setting `loop_arm` by SQL.
     - `zpd.step` carries `variant`.
     - Analysis is intention-to-treat by the assigned variant, plus the tier
       actually served (`zpd.step.tier`), with a cap-hit covariate
       (`ai.budget_capped` for that user-day).
   - A perceived-difficulty prompt runs every `ZPD_RATING_EVERY_N_CHECKS`
     graded checks and emits `zpd.rating`.
3. **Tool-removed, delayed post-test.** `POST /api/learn/loop/posttest/start`
   and `/answer`.
   - **What it serves.** It serves concepts whose last evidence is at least
     `POSTTEST_MIN_AGE_DAYS` old. For each one it serves the concept's
     reserve item (A23), which probe, in-session checks and review never
     serve; it never serves a seen or revealed item.
   - **How it grades.** The answer is graded through the same `grade_answer`
     at rung H0, with no session, no RAG, no brief and no tutor.
   - **What it records.** The evidence is unassisted, with `max_rung` 0.
     `zpd.step` carries `phase: "posttest"` and
     `ceiling_reason: "posttest"`, and no `tier`.
   - **It commits when opened** (spec §13 A87, A89). The pose is recorded in
     `posttest_poses`, and a repeat start returns the same item. The answer
     grades only the open pose, under a database claim (one conditional
     UPDATE). The claim is re-validated, and the pose closed, before the one
     flush, so a taken-over claim writes nothing and a failed flush never
     reopens it.
   - **A pose expires** after `POSTTEST_POSE_TTL_HOURS` (24 †, owner): it is
     void, may be posed again, and a late answer is a 409. An item revealed
     since it was posed, or a node with any evidence journaled after
     `posed_at`, grades with no unassisted credit.
4. **Delayed proctored retention.** Out of the series' scope. The logged
   fields make it possible later.

**The launch plan (spec §11).**

- **The §11.1 gate** has eight items, including a staging smoke, a
  kill-switch drill, the cost guardrails above and the owner's written
  go-ahead. There is no beta waiting period.
- **Half B's changes (§11.2)** delete:
  - the tutor mastery tool;
  - the quiz deltas;
  - the legacy tier cuts;
  - the learning-style onboarding step;
  - the three always-empty session-summary lists.

  Half B also makes the gate env-only.
- **The owner-run launch runbook (§11.7)** is written into HANDOFF-14 and is
  never run by a build session. It covers the production pin, the staging
  backfill and smoke, the drill, `make promote`, the production backfill, the
  unpin, the production smoke and the recurring backfill.

**The legacy tutor's mode prompts stay.** The `chat_tutor` mode prompts are
not folded into `loop_tutor.py` in this series. The legacy agents stay, minus
the mastery tool, because the kill switch serves them. The fold waits for the
follow-up that deletes `LEARNING_LOOP_ENABLED`.

**Payload and phase additions (spec §13 A8).**

- `zpd.step` gains a `variant` key, present when the route knows it.
- `posttest` is a `zpd.step.phase` value only: the `sessions.close_phase`
  CHECK is unchanged.

## Consequences

- **Half B deletes these:**
  - `update_mastery_tool`, `MasteryUpdateInput`, `ConceptMasteryUpdate`,
    `TUTOR_EVENT_TYPES` and the preamble paragraph that instructs the tool;
  - `apply_graph_update`'s `updated_nodes` branch;
  - `MASTERY_DELTA_PER_*`, `mastery_after` and the quiz delta block;
  - `config.MASTERY_*_MIN`, `get_mastery_tier`, `is_mastered` and `is_weak`
    (every caller uses `learning/bkt.tier_for`);
  - the learning-style onboarding step;
  - the three always-empty `end_session` summary lists.

  The quiz `mastery_delta` key becomes `p_delta`.
- **A follow-up ticket, not this series,** deletes `LEARNING_LOOP_ENABLED`
  entirely and folds the legacy tutor.
- **Columns left dead on purpose:**
  - `user_profiles.learning_style`;
  - `user_settings.learning_loop_beta`, the retired build-phase toggle;
  - the `graph_nodes.mastery_events`-era columns.
- **The PKG-00 migration header is out of date.** The applied migration
  `20260926231744_learning_loop_beta.sql` still describes the column as
  "per-user opt-in for the new tutor loop". That is the build-phase meaning,
  and applied migrations are immutable, so it stays as written.
- **The earnest-revise gate** (spec §10, ≤ 5 %) is not measured: no event
  carries that signal. Making it measurable needs a `zpd.step` key or a grader
  flag; that is a follow-up.
  Amended: measured since 2026-10-01 (A109) — the feedback `zpd.step`'s
  `earnest_blocked` bool, reported with its ≤ 5 % gate by the admin
  learning-loop KPI and `scripts/derive_zpd_metrics.py`.
- **Cost per session covers the requests an event names.** `zpd.step`,
  `learn.session_closed` and `chat.message_sent` carry the session id
  (A82), joined on (user_id, request_id). A loop request none of them names
  (the opener, the probe and review grades, a hint action) is still costed
  per user-day. **`llm_usage.session_id` is built in half B (owner
  decision, spec §13 A92):** migration
  `20260930042516_learning_llm_usage_session_id.sql` (additive, nullable),
  the writes in `agents/usage.py::record_agent_usage` wherever a session is
  known, and the report preferring the column. It is the one migration half B
  adds, against spec §11.7's "half B adds no migration": a Rollback revert of
  half B leaves the column in place (additive; the build-phase code never
  names it). A deploy ahead of the migration drops the column from its
  `llm_usage` inserts and retries, so no usage row is lost.
- **Tests deleted with their code in half B** (each named in its commit): the
  mastery-tool and `updated_nodes` tests (B2), the flat-delta and gate-branch
  quiz/flashcard tests (B3), `test_tier_for_is_not_the_legacy_tier` (B4), the
  build-phase gate tests (`test_env_on_row_true_is_true`,
  `test_env_on_row_false_is_false`, `test_env_on_missing_row_is_false`,
  `test_env_on_missing_key_is_false`, `test_read_error_fails_closed` and their
  route-entry, settings-flag and meta twins, B5) and
  `test_legacy_users_are_not_opted_in` (B5b).
- **Stored tiers from the old cuts.** `graph_nodes.mastery_tier` rows written
  before half B carry the 0.1 / 0.45 / 0.75 cuts until each node's next write
  (a new node, a graded evidence). Whether to re-derive them once is an owner
  question (spec §13 A91, recorded, not decided).
- **Served tutor turns are never withheld; what they reveal is recorded**
  (spec §13 A86 for "never withheld", A88 for the scope and the store).
  - **Scope: open, posed items only.** The model never sees an item the
    student has not been posed (the verified precondition), so only the
    active check item, an open review item and an open post-test pose can be
    stated. Every served model turn is scanned against those; an item turn
    skips its own active item, whose leak check already redacted it.
  - **Durable at serve time.** A stated item is written to
    `learning_reveals` before the turn's state write — the opener too — and
    `revealed_hashes` reads it, so no path has to consume anything first. A
    stream that ends early (error, disconnect, cancellation) still records
    what it relayed.
  - **Fail closed.** A revealed item grades with no unassisted credit. If the
    open items cannot be read, an `unscanned` marker makes every item posed at
    or before it grade as assisted.
  - **The gate is honest** (A90). `zpd.leak` is a caught, redacted leak and is
    reported as `caught_leaks`; the zero-leak gate counts `served_reveals`,
    the answers a served turn actually stated (`zpd.reveal`).
- **A reasoned claim is a genuine attempt for that teach turn's ceiling**
  (spec §13 A85): the existing genuine-attempt rule, one rung, capped per band,
  and no evidence change. Owner-accepted limitation: any non-empty message
  with no non-attempt phrase qualifies once the time gate passes.

