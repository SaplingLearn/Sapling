# 0030: The learning loop replaces LLM-moved mastery, and becomes every student's default

- Status: accepted
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
- **Cost per session covers the requests an event names.** `zpd.step`,
  `learn.session_closed` and `chat.message_sent` carry the session id
  (A82); a loop request none of them names (the opener, probe and review
  grades, a hint action) is still costed per user-day. A `session_id` column
  on `llm_usage` would close that; it is not built.
- **Teach turns at H0/H1 serve the ladder's question** (spec §13 A81, a
  PKG-07 reopen), the model writing only the key idea and body. The per-tier
  evals did not pass with it (A81), so launch-gate item 4 is open.

