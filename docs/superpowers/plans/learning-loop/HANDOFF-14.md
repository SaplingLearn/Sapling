Half A only — half B (cutover) pending the series owner's confirmation.

# HANDOFF-14 — eval-ladder-cutover (half A)

Written by the session that executed half A of `PKG-14-eval-ladder-cutover.md` (Tasks A1–A8; A9, the PR, skipped by the session overrides — the integrator merges into `feat/learning-loop`). Read by half B and by every later session. Keep every heading, even if the answer is "none".

**Status (owner round 2, 2026-09-29): A1–A6 and A8 done; A7 BLOCKED — this time by the Gemini API daily quota, not a failing gate.** Owner round 2 applied: A81 reverted (A83); the teach-turn leak fix (A84, PKG-07 reopen) and "a reasoned claim is a genuine attempt" (A85, PKG-06 + PKG-07 reopens) are built, test-first, and committed; `sycophancy_insists_wrong_limit` takes its ceiling from the policy (H2). The re-record got through run 1 only: `loop_tutor_lite` and `loop_tutor` complete — **every served gate 1.000 on both, the H1 claim case included** (lite RetriesUsed 0.375) — then `gemini-2.5-pro` hit `generate_requests_per_model_per_day` (limit 1000; retry in ~22 h), so `loop_tutor_deep` and the rung judge (also 2.5-pro) raised in run 1 and every case raised in runs 2–3. Nothing was raised or worked around. The eval work and run 1 are on `wip/pkg14a-sycophancy-h1-fixture` @ `16229bac` (the resume point); this branch keeps the PKG-07 dataset and `LOOP_ROUTABLE_TIERS` unchanged. Earlier owner round: A80 kept at 20, first `loop_arm` experiment = variant-B gate, A82 per-session cost.

## What changed

- **Nightly ZPD metrics** (`backend/scripts/derive_zpd_metrics.py`). For every `learner_state` row with opportunities, it recomputes `htc_k`, `unassisted_next`, `assist_gap` and `in_zone` from the node's evidence journal.
  - It writes only through `learning/learner_state.py::write_metrics`, an UPDATE of those four columns.
  - Every run prints one read-only `REPORT <json>` line: cost per band, cost per session (or per user-day), the check_items total, the tier and `grader_backend` mix, cap hits, and each course's check-item coverage.
  - `--dry-run` writes nothing. Exit 2 on the silent-empty keyspace mismatch. `REPORT_FAIL` gives exit 1.
- **Admin KPIs.** `GET /api/admin/analytics/learning-loop` serves the three KPIs and the two measurable gates of spec §10.
  - KPIs: in-band share, the `htc_k` trend per concept, and unassisted success on the next session's first item.
  - Gates: zero leaks, and ceiling compliance ≥ 95 %.
- **Perceived-difficulty rating.**
  - The check-answer handler counts `loop_state.checks_since_rating` once per flushed grade.
  - When the count reaches `ZPD_RATING_EVERY_N_CHECKS`, the feedback turn carries `ask_rating: true`, and `LoopLearn` shows the three-button `loop-rating` prompt.
  - `POST /api/learn/loop/rating` emits `zpd.rating` and resets the counter.
- **Tool-removed post-test.** `POST /api/learn/loop/posttest/start` and `/answer`.
  - It serves each old-enough concept's reserve item (A23), never a seen or revealed one.
  - It grades through `grade_answer` at H0, with no session, no RAG, no brief and no tutor.
  - It records unassisted evidence and a `zpd.step` with `phase: "posttest"`.
- **Within-student arms, as plumbing.**
  - A `user_settings.loop_arm` column, plus `learning/arms.py::variant_for`.
  - The genuine-attempt gate reads the concept's variant.
  - `zpd.step` carries `variant`.
  - An arm session passes `arm_session=True` to every tutor budget and tier call.
  - With `loop_arm` NULL for everyone, nothing changes.
- **ADR 0030** (`docs/decisions/0030-learning-loop-cutover.md`) records the evidence-only rule, the default-on decision, the kill switch, the cost guardrails, the ladder and the launch plan.
- **Min-of-3 eval floors tooling.** `SAPLING_EVAL_RUNS_LOG` plus `tests/evals/floors.py`.

## Symbols added

Backend:

- **Migration** `backend/db/migrations/20260929175715_learning_loop_arm.sql`: `ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS loop_arm text;` (spec §4, verbatim).
- **`backend/learning/params.py`**, the PKG-14 block: `HTC_K_WINDOW`, `ZPD_IN_ZONE_MIN_GAP`, `ZPD_IN_ZONE_MIN_ASSISTED`, `ZPD_IN_ZONE_MAX_UNASSISTED`, `KPI_TREND_WEEKS`, `GATE_LEAKS_MAX`, `GATE_CEILING_COMPLIANCE_MIN`, `POSTTEST_MIN_AGE_DAYS`, `POSTTEST_MAX_ITEMS`, `GATE_INDEPENDENT_MIN_S_VARIANT_B`.
- **`backend/learning/arms.py`** (new, pure, in `PURE_MODULES`):
  - `Variant = Literal["A", "B"]`;
  - `variant_for(user_id, node_id, arm) -> Variant`: "A" when `arm` is None or empty; else the parity of sha256(`f"{arm}:{user_id}:{node_id}"`)'s first byte (even is "A").
- **`backend/learning/policy.py`** (PKG-06 reopen):
  - `independent_gate(band: Band, variant: Variant) -> str` returns the `GATE_*` name;
  - `independent_min_s(band, variant) -> int`;
  - an unknown variant raises;
  - `CeilingReason.POSTTEST = "posttest"`.
- **`backend/learning/gates.py::is_genuine_attempt(..., variant="A")`** (PKG-06 reopen) reads the threshold through `independent_gate`.
- **`backend/learning/zpd_events.py::emit_zpd_step(..., variant=None)`** (PKG-06 reopen): the payload gains `variant` when given.
- **`backend/learning/learner_state.py`:**
  - `write_metrics(user_id, node_id, *, htc_k, unassisted_next, assist_gap, in_zone)`: an UPDATE of those four columns plus `updated_at` on the primary key. Its only caller is the metrics script.
  - `opportunity_states(user_id=None) -> list[dict]`: paged `(user_id, node_id, opps)` rows with `opps > 0`.
  - `states_last_evidence_before(user_id, cutoff) -> list[dict]`: paged `(node_id, last_evidence_at)` rows, oldest first.
  - `_LearnerStateRead`: the read-only `page_all` handle (the check_item_service pattern).
- **`backend/scripts/derive_zpd_metrics.py`:**
  - `compute(opps) -> dict`: pure; `opps` are newest first.
  - `_opportunities(rows)`;
  - `report(usage, steps, caps, *, sessions_by_request) -> dict`: pure;
  - `main(argv) -> int`;
  - `SERIES_SLOTS`: equal to the invariants module's `SERIES_AGENT_TASKS`, pinned;
  - `_now()`.
- **`backend/routes/admin_analytics.py`:**
  - `GET /learning-loop` returns `LearningLoopKpis` (`range`, `steps_total`, `banded_steps`, `in_band`, `in_band_share`, `htc_k_trend`, `unassisted_next_session`, `leak_count`, `ceiling_compliance`, `gates`, `truncated`);
  - response models `WeekPoint`, `ConceptTrend`, `CeilingCompliance`, `NextSessionSuccess`, `Gates`;
  - helpers `_rung_int`, `_phase_band`, `_in_band_share(steps) -> (in_band, banded)`, `_htc_k_trend`, `_next_session_rate`, `_ceiling_compliance`.
- **`backend/routes/learn_loop.py`:**
  - `_loop_arm(user_id) -> str | None`; `_arm_for(user_id, request)`, read once per request on `request.state.loop_arm`.
  - `POST /rating` (`rating()`, `LoopRatingBody`).
  - `POST /posttest/start` (`posttest_start`, `PosttestStartBody`) and `POST /posttest/answer` (`posttest_answer`, `PosttestAnswerBody`; rate-limited).
  - `STEP_PHASES` (the values of `zpd_events.Phase`); `posttest_item(items, excluded)`.
  - `_posttest_now()`, `_posttest_cutoff`, `_due_for_posttest`, `_posttest_excluded`, `_posttest_node`, `_posttest_eligible`.
  - `_POSTTEST_LOCKS`: per (student, item).
  - `_Submission.ask_rating`. The submission turn's data carries `ask_rating: true` only when true.
- **`backend/models/__init__.py`:** `LoopRatingBody`, `PosttestStartBody`, `PosttestAnswerBody` (the answer fields have `max_length=GRADER_ANSWER_MAX_CHARS`).
- **`backend/routes/learn_loop.py`** (PKG-07 reopen, A81): `TEACH_LOW_RUNG_QUESTIONS = {0: "What will you try next?", 1: "What is the first thing you need to figure out here?"}`; `_without_questions(text)`; `_served_fields` serves a teach turn at H0/H1 with the ladder's question and drops any asking sentence from the model's key idea/body.
- **`backend/learning/zpd_events.py::emit_zpd_step(..., session_id=None)`** (A82): `session_id` in the payload when given; `_emit_step` passes the loop session.
- **`backend/scripts/derive_zpd_metrics.py::sessions_by_request(events)`** (A82); the report's event read adds `chat.message_sent`; `report()` returns both `cost_per_session` and `cost_per_user_day` (the latter only for rows with no session key).
- **Tests (owner round):** `tests/test_learning_step_session.py` (3); `tests/test_learn_loop_hardening.py` +5 (A81); `tests/test_learning_zpd_metrics_script.py` 31 → 33.
- **`backend/tests/evals/_replay.py`:** `RUNS_LOG_ENV = "SAPLING_EVAL_RUNS_LOG"`, `_log_run`.
- **`backend/tests/evals/floors.py`:** `recorded_runs`, `floor_of`, `apply_floors`, `main`.
- **Tests:**
  - `tests/test_learning_zpd_metrics_script.py` (31);
  - `tests/test_admin_learning_loop_kpis.py` (20);
  - `tests/test_learn_loop_rating.py` (18);
  - `tests/test_learning_posttest.py` (25);
  - `tests/test_learning_arms.py` (20);
  - `tests/test_eval_floors.py` (6);
  - invariants: `test_inv_20_metrics_script_idempotent`; `inv_01` gains a `write_metrics` caller block and sanctions `write_metrics`' update; `inv_26` adds `posttest_answer` to `EVIDENCE_WRITERS`; `arms.py` joins `PURE_MODULES`.

Frontend:

- **`frontend/src/lib/api.ts`:**
  - `LoopTurnResult.ask_rating?`;
  - `LoopRating`;
  - `submitLoopRating(sessionId, rating)`, which posts `{session_id, rating}`; the user is the session cookie's.
- **`frontend/src/components/learn/LoopLearn.tsx`:**
  - `askRating` state, set from a graded submission's `done.ask_rating` and cleared on a session switch;
  - `RatingPrompt`;
  - testids `loop-rating`, `loop-rating-{too_easy,appropriate,too_hard}` (in `docs/frontend-testids.md`).
- **Tests:** `LoopLearn.test.tsx` (+4), `api.loop.test.ts` (+1).

Docs:

- `docs/decisions/0030-learning-loop-cutover.md` (**ADR number 0030**: 0027/0028/0029 are claimed by #672/#677/#705; #512's 0026 also collides with the existing 0026 but is not this package's).
- Spec §13 **A79** (half A as built) and **A80** (the 06(t) measurement); the §3.5 `CHECK_ITEM_FINAL_ANSWER_MAX_TOKENS` row.

Side branch, not for merge:

- `wip/pkg14a-sycophancy-h1-fixture` @ `94a4a976`: the second sycophancy fixture, its three recordings and floors (Known gaps).

## Constants chosen

- `HTC_K_WINDOW = 5` † (ZPD report LOG block, "last k=5 opportunities").
- `ZPD_IN_ZONE_MIN_GAP = 0.25` †, `ZPD_IN_ZONE_MIN_ASSISTED = 0.6` †, `ZPD_IN_ZONE_MAX_UNASSISTED = 0.85` † (the ZPD report's `in_zone` flag). "Assisted" in `in_zone` is the correct share among the assisted opportunities in the window.
- `KPI_TREND_WEEKS = 4` † (A6).
- `POSTTEST_MIN_AGE_DAYS = 2` † (research: rung 3 is ≥ 2 days delayed).
- `POSTTEST_MAX_ITEMS = 10` † (an engineering cap).
- `GATE_INDEPENDENT_MIN_S_VARIANT_B = 90` † — the first `loop_arm` experiment (owner decision 2026-09-29).
- `GATE_LEAKS_MAX = 0`, `GATE_CEILING_COMPLIANCE_MIN = 0.95` (spec §10 gates; not †).
- **`CHECK_ITEM_FINAL_ANSWER_MAX_TOKENS` stays 20 †** (A40 06(t) measured, spec §13 A80).
  - **Distribution.** The `final_answer` lengths (`checks.answer_run`) of the 53 drafts the committed `check_items` recording stores are 1×1, 3×4, 3×5, 5×6, 5×7, 6×8, 5×9, 5×10, 4×11, 5×12, 4×13, 3×14, 3×15 and 1×16. The one rejected draft has 1 token. So 16 is the smallest cap that keeps every stored draft.
  - **Recorded at both caps.** The prompt states the cap, so each value was recorded under its own prompt, three times each:

    | cap | DraftValid | McOptionsValid |
    |---|---|---|
    | 16 | 0.963 / 0.852 / 0.815 (min 0.815) | 1.000 / 1.000 / 0.944 |
    | 20 | 0.778 / 0.870 / 0.981 (min 0.778) | 1.000 ×3 |

  - **Why it stays 20.** At 16, one recording had one A37 option-rule failure. PKG-04 pins that contract at 1.0 (`TestMcReasonEval::test_the_baselines_pin_the_option_contract_and_the_recorded_yield`). Adopting 16 would mean lowering that pinned bar, so the constant, its prompt, its cassettes and its baselines stay unchanged. **Owner decision (2026-09-29): keep 20** (A80).

Eval recordings (A40 06(s): floors are the min of 3). These numbers come from the `loop_tutor` experiment on the side branch; none of them is committed on this branch:

| slot | gate | run 1 / run 2 / run 3 | floor |
|---|---|---|---|
| `loop_tutor_lite` | SycophancyResists | 0.875 / 0.875 / 0.875 | 0.875 |
| `loop_tutor_lite` | RetriesUsed | 0.500 / 0.625 / 0.500 | 0.500 |
| `loop_tutor` | CeilingCompliance | 0.875 / 0.875 / 0.875 | 0.875 |
| `loop_tutor` | RetriesUsed | 0.875 / 1.000 / 1.000 | 0.875 |
| `loop_tutor_deep` | CeilingCompliance | 0.875 / 0.875 / 0.875 | 0.875 |
| `loop_tutor_deep` | RetriesUsed | 1.000 / 1.000 / 0.875 | 0.875 |

Every other gate is 1.000 in every run of every slot, and no case raised.

## Deviations from spec

- **`write_metrics` is a second writer.** Spec §5 says only `apply_graph_update` writes `learner_state` → `learning/learner_state.py::write_metrics` UPDATEs the four derived columns (†, spec §13 A79). `inv_01` sanctions its update beside `write_state`'s upsert. Its callers are pinned to the script and its tests.
- **`inv_20` and the preamble.** The prompt's `".insert(" not in text` rule → `(?<!sys\.path)\.insert\(` → the prompt's own script preamble requires `sys.path.insert`.
- **The script's state read.** The prompt's `_states` called `page_all(table("learner_state"), …)` inside the script, which `inv_20` forbids → `learner_state.opportunity_states`. The graph_nodes course read uses a read-only handle, as `inv_01`'s ast half requires.
- **Journal order.** The prompt's `created_at desc, id desc` → `created_at.desc,evidence_seq.desc.nullslast,id.desc` → spec §13 A36 (rows that one apply call writes share `created_at`).
- **The env file on import.** The script's env file loads only on an operator run (`if __name__ == "__main__"`), never on import → the tests import it (the #benchmark_quiz `.env.staging` clobber class).
- **`variant_for`'s module.** `policy.variant_for` → `learning/arms.variant_for` → invariant 4 holds policy's public functions to typed, text-free parameters. `independent_min_s` stays in policy with `(Band, Variant)`.
- **`loop_arm` and the settings API.** The prompt says "`loop_arm` readable in the settings GET" → it is in NO settings API field → CONTINUE §4.4 (the PKG-14 note, A31's reason). The loop route reads it directly.
- **Where the threshold is read.** "The one call site that reads the independent-time threshold" is in `learning/gates.py`, not the route. So `is_genuine_attempt` gains `variant=` (a PKG-06 reopen), and the route passes the concept's variant at all three `_genuine` call sites.
- **The `ceiling_reason` value.** A post-test `zpd.step` needs a `ceiling_reason` value → `CeilingReason.POSTTEST` (a PKG-06 reopen) → `emit_zpd_step` builds the reason from the enum.
- **Which items the post-test grades.** The prompt says only that the answer route loads the item → it grades only the node's CURRENT post-test item: an eligible concept, and not seen or revealed. Anything else is a 409. The route holds a per-(student, item) lock across the check, the grade and the flush → otherwise a double submit or a replay of an answered item would flush evidence twice. The backend runs as one process (`backend/Dockerfile` CMD), so the in-process lock covers the deployment.
- **The re-check on the post-test.** The post-test also calls `recheck_after_release` → spec §13 A76 and PKG-10's structural pin (every grading caller).
- **The post-test's lookups.**
  - The post-test reads items with `items_for_concepts` (one select), not `list_items` per concept.
  - Nodes come from one `graph_nodes` read for the student's course.
  - An `mc_reason` answer without `selected_option`, or a free answer without `answer`, is a 422, as `/review/answer` does.
- **The fallback after the reserve** (†). The prompt describes it; recorded here as its †: a free item nearest `CHECK_ITEM_DIFFICULTIES[1]` first, then the lowest-hash servable item. A34: an item without a `final_answer` is never served, not even as the fallback.
- **The route pin** (`tests/test_learn_loop_routes.py`, outside the Files lists). It learns `/rating` and `/posttest/start` as no-model routes and `/posttest/answer` as a model route. This is the same kind of edit PKG-13 made for `/sessions`.
- **`tests/test_learning_loop_invariants.py`.** Beyond the `inv_26` allow-list entry that the regression guard names, it also gains `inv_20`, the `inv_01` `write_metrics` block (the prompt's Task A1) and `arms.py` in `PURE_MODULES`.
- **The eval gap check** (A7 Step 1) — **not merged.** The dataset already had 8 cases (the cap) with 1 sycophancy fixture. The second one replaces `teach_develop_derivatives` (same phase, band and ceiling as `sycophancy_insists_wrong_derivative`). `SycophancyResists` reads the eval-only confront judge instead of a `CONTRADICTION_MARKERS` word list → the owner's rule: a structured source over a heuristic. The fixture's recordings fail (Known gaps), so the change lives on the side branch only.
- **The fixture recordings** (A7 Step 3). The prompt says "record ONLY the new cases, once per slot" → the whole dataset, three times per slot → A40 06(s) (a floor is the min of 3 recordings), and the served gate's semantics changed.

## Known gaps

- **BLOCKED — the A7 re-record needs three runs, and the Gemini API daily quota for `gemini-2.5-pro` ran out in run 1** (owner round 2).
  - **History.** Before any fix: standard and deep asked an H3 question at the profic teach ceiling H1 (3/3). A81 (code-served H0/H1 teach question): standard and deep still failed — the key idea carried the concept — so A81 was retired (A83, reverted afb857ae).
  - **Round 2 (A84 + A85).** A reasoned claim after a realistic independent time is a genuine attempt, so the case's ceiling is the policy's H2 (never hard-coded); teach turns never state the concept's item answers (A84). Run 1 (`wip/…` @ `16229bac`): `loop_tutor_lite` and `loop_tutor` complete with **every served gate 1.000** (the H1 claim case included; lite RetriesUsed 0.375); `loop_tutor_deep` raised on a 429 (`generate_requests_per_model_per_day`, limit 1000, `gemini-2.5-pro`), and runs 2–3 raised on every case (the deep slot and the rung judge are 2.5-pro).
  - **Resume** (after the quota resets, ~22 h after 2026-09-29 16:00 local): check out the wip branch's `backend/tests/evals/loop_tutor.py`, `tests/test_learning_eval_ladder.py` and `tests/test_loop_tutor_agent.py` onto this branch, delete the `teach_develop_derivatives` cassettes, record 3× per slot with `SAPLING_EVAL_RUNS_LOG`, run `tests/evals/floors.py --runs 3 … --routing loop_tutor_routing`, and set `LOOP_ROUTABLE_TIERS` to exactly the tiers whose three runs all pass; STOP if standard or deep fail. About $0.95 of calls.
  - **Parity gap until then.** A84 and A85 change what production serves on teach turns; this branch's eval still scores teach turns raw with the PKG-07 dataset (the parity change is on the wip branch, pending the recordings).
  - **Half B's launch gate** (§11.1 item 4) is open until the re-record passes.
- **The earnest-revise gate** (spec §10, ≤ 5 %) is not measured: no event carries the signal. **Cheapest measurable signal, proposed for half B (not built):** the research's gate counts earnest attempts the ceiling over-blocked. The loop already records both halves — a counted genuine attempt (`steps[qh].attempted_at`, `/step/attempt`) and a `/hint` denial with its reason. Add ONE per-step counter in `loop_state.steps[qh]`, `earnest_blocked`, incremented when `/hint` denies at the ceiling (reason not `no_genuine_attempt`) while the step has at least one genuine attempt; carry it on the feedback `zpd.step` as a bool `earnest_blocked` (a payload key, no new event); the KPI endpoint's rate = check steps with `earnest_blocked` / check steps, gated ≤ 5 %. No model call, no new table.
- **The rating prompt has no E2E coverage.** It needs 30 graded checks in one session. The backend and vitest cover it.
- **`loop_arm` is NULL for everyone** until the owner starts the first experiment — decided (owner, 2026-09-29): the variant-B independent-time gate (`GATE_INDEPENDENT_MIN_S_VARIANT_B` 90 s vs `GATE_INDEPENDENT_MIN_S` 45 s, develop/profic; ADR 0030). Until the owner sets `loop_arm` by SQL every student is variant A and the plumbing is inert.
- **Per-session cost covers the requests an event names** (A82). `zpd.step`, `learn.session_closed` and `chat.message_sent` carry the session id; a loop request none of them names — the opener, probe and review grades, an `[ACTION: hint]` turn — is still costed per user-day. A `session_id` column on `llm_usage` (migration + `agents/usage.py`) would make every row attributable; not built.
- **The post-test has no frontend.** No UI calls `/posttest/*`; it is a backend endpoint for the ladder, and no journey covers it.
- **The post-test lock is in-process.** A scale-out to more than one backend process or replica needs a database claim for `/posttest/answer` first — a precondition in the B9 runbook (integrator's call).
- **Only the local `loop_tutor` eval was recorded live.** The `grader`, `decisions`, `check_items` (except the 06(t) experiment, reverted) and `misconception_confront` baselines are unchanged, and their floors are still single-recording (A40 applies where half A re-sets a floor; half A re-set none).
- **No E2E was run** (session override). The PKG-13 lane row and Task B6 carry the E2E gate for all of PKG-14.

## Verify commands

```
cd backend && venv/bin/python -m pytest tests/test_learning_zpd_metrics_script.py tests/test_admin_learning_loop_kpis.py tests/test_learn_loop_rating.py tests/test_learning_posttest.py tests/test_learning_arms.py -q → 114 passed
cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_20 or inv_01" → 2 passed
cd backend && venv/bin/python -m pytest tests/test_learning_loop_invariants.py -q -k "inv_26 or inv_28" → 3 passed (inv_26, its scan self-test, inv_28)
ls backend/db/migrations/*_learning_loop_arm.sql                                                  → 1 file
ls docs/decisions/*learning-loop-cutover*.md                                                      → 1 file (0030)
cd backend && SAPLING_EVAL_MODE=replay venv/bin/python tests/evals/run_all.py                    → PASS for every dataset (16)
grep -c '"check_items"\|"grader"\|"decisions"\|"loop_tutor"' backend/tests/evals/run_all.py      → 4
grep -n '"/learning-loop"' backend/routes/admin_analytics.py                                     → 1 hit
grep -c "posttest/start\|posttest/answer\|/rating" backend/routes/learn_loop.py                   → ≥ 3
grep -c "arm_session=bool(" backend/routes/learn_loop.py                                          → ≥ 1
grep -c "REPORT" backend/scripts/derive_zpd_metrics.py                                            → ≥ 1
cd backend && venv/bin/python -m pytest tests/test_eval_floors.py tests/test_learning_step_session.py -q → 9 passed
cd backend && venv/bin/python -m pytest tests/test_learn_loop_hardening.py -q -k "low_rung or low_teach or profic_teach or teach_partial" → 5 passed
```

Observed at the end of half A (no stack), at `b1bc30dc`, with the hermetic suite under the override command and neither `SAPLING_MODEL_MODE` nor `SAPLING_FUNCTION_HANDLERS` set: **8254 passed, 140 skipped, 0 failed** (N₀ 8133 / 140 → +121 tests, no new skips); invariants → 34 passed, 1 skipped; `ruff check .` → All checks passed!; `SAPLING_EVAL_MODE=replay tests/evals/run_all.py` → 16/16 PASS. Frontend: `npx tsc --noEmit` clean; `npx vitest run` → 112 files, 1260 passed, 2 skipped; `npx eslint` on the changed files → clean.

Live spend (metered per request at `services/llm_pricing` list prices; output tokens include thinking):

- `loop_tutor` 3 × 3 slots, with the rung and confront judges: **$0.935** (upper bound $1.569 if thinking were billed on top of output).
- `check_items` 06(t), 3 recordings at 16 and 3 at 20: **$0.065**.
- **Total ≈ $1.00** for the first round.
- Owner round: `loop_tutor` 3 × 3 slots after A81: **$0.955**.
- Owner round 2: the A84/A85 re-record (run 1, then quota): **$0.314**. **Grand total ≈ $2.27.**

## Open questions for the series owner

Owner decisions of 2026-09-29 (Andres), applied: (1) option (a), built as A81 — did not pass, STOPPED; (2) keep `CHECK_ITEM_FINAL_ANSWER_MAX_TOKENS = 20` (A80); (3) the first `loop_arm` experiment is the variant-B gate (ADR 0030); (4) `zpd.step` carries the session id, report per session (A82). Integrator's calls: earnest-revise → a proposal (Known gaps), not built; the post-test DB claim → a B9 precondition; A45 → flagged for half B's gate.

Owner round 2 (2026-09-29) applied: A81 retired (A83); A85 (a reasoned claim is a genuine attempt, the 120 s case time approved with the fast-claim proviso test); A84 (teach-turn leak fix); `llm_usage.session_id` → half B (below).

Still open:

1. **The A7 re-record** is blocked by the `gemini-2.5-pro` daily quota (see Known gaps for the resume steps). Run 1 passed on lite and standard.
2. **Lite's routability** will be decided by the three runs (run 1: every served gate 1.000).
3. **The grader cap is blind without events** (A45). Flagged for the half B STOP gate.

## For half B

- **ADR.** It is 0030. Append `learning_loop_beta retired: <date> (PKG-14b)` and `Cutover executed: <date>, PR #<n>`.
- **The launch gate is not met.** §11.1 item 4 needs every tier to pass the per-tier evals; the second sycophancy fixture (off-branch) fails standard and deep even after A81. Half B's STOP gate must put Open question 1 to the owner.
- **Kill-switch marking.** The new modules (`test_learning_posttest.py`, `test_learn_loop_rating.py`, `test_learning_arms.py`, `test_admin_learning_loop_kpis.py`, `test_learning_zpd_metrics_script.py`, `test_eval_floors.py`) patch the gate themselves (`learning_loop_for_request`) or never reach it, so B's `kill_switch` marking should not need them. Check them with the B5 grep.
- **The rating's user.** `/rating` and `/posttest/*` take an optional `user_id` and fall back to the session cookie (the `CloseBody` pattern).
- **`loop_arm` stays out of the settings API.** Keep it that way (CONTINUE §4.4).
- **Frontend.** `LoopLearn`'s rating prompt is inside the loop tree, so the kill-switch lane never renders it.
- **The runbook** (Task B9) gets these owner steps, listed and never run:
  - production `PLATFORM_DAILY_BUDGET_USD=5` (A39 (e)); before that, prove the alert on staging: set a deliberately low value (e.g. `0.01`), drive one tutor turn, confirm the `ai.budget_capped{scope: platform}` alert reaches you, then restore the staging value;
  - **precondition before running more than one backend process or replica:** give `/posttest/answer` a database claim (its double-submit lock is in-process today).
- **A45** (grader cap blind without events) stays flagged for the STOP gate.
- **`llm_usage.session_id` — half B work (owner decision, round 2):** a migration adding `llm_usage.session_id text` (UTC-timestamp prefix, `_learning_` infix); the writes in `agents/usage.py::record_agent_usage` (the run's `deps.session_id`); and `scripts/derive_zpd_metrics.py` preferring the row's own `session_id` over the event mapping (A82), keeping the per user-day fallback only for older rows without it.
- **The first `loop_arm` experiment** is the variant-B gate (owner): starting it is an owner SQL step, not a build step.
- **E2E note for B6:** A84 withholds a teach turn that states a concept item's answer — the seeded items' final answer (`E2E_LOOP_FINAL_ANSWER`) is absent from the function-mode teach turn, but B6 should confirm the loop walk's teach turns are served as written; A85 needs a `served_at` anchor and a timed student message, which the seeded users (novice, ceiling H5 = cap) never raise.

## Post-hoc changes

(Appended by later packages that modified this package's code. Format: `PKG-MM <date>: <what> — commit <sha>`.)
