# Learning Loop — Design Spec (series source of truth)

Status: approved design. Build state 2026-09-27: PKG-00, PKG-01, PKG-02 built; PKG-03 in progress; PKG-11 built early (branch `feat/learning-loop-11-quiz-flashcards`, cut from PKG-03's review round `a1a416b`; ledger `11 | done`; see §14); everything else unbuilt. Every prompt in `docs/superpowers/plans/learning-loop/` cites this file by section heading. Numbers live here once, under a name; code cites the name.

Research basis: `docs/research/learning-loop/AI tutor learning loop research.md` (loop, learner model, scheduler, guardrails, evaluation) and `docs/research/learning-loop/ZPD lever tradeoffs and upgrades.md` (§"Sapling ZPD policy spec" for the ladder/ceiling/gates; §"Re-verification" for corrected numbers). Design page: Canopy artifact `sapling-learning-loop-research-backed-design`. Cost and Jev basis: the 2026-09-26 cost-reduction and Jev decision report and the owner decisions of the same day (§13 A14–A26); every number from it that the series uses is restated in §3.5/§3.6 so this file stands alone.

## 1. Goal and invariant statement

Only graded checks change what Sapling believes a student knows. The belief is a per-(student, concept) probability from Bayesian Knowledge Tracing (BKT) with fixed priors and a separate guess/slip pair per evidence channel. It decays toward the prior between checks along an FSRS-6 forgetting curve and is scheduled for review near 90% recall. How much help the tutor may give is computed in code from the learner state, never from the student's text, and every hint is one rung of a fixed ladder gated by a genuine attempt. Learning is measured by unassisted success on the next opportunity and on tool-removed, delayed checks; never by in-session accuracy or by the change in the belief.

**End state: the learning loop is the default learning system for every student, with no opt-in (§13 A14).** During the build, every package ships dark behind `LEARNING_LOOP_ENABLED` (build-phase parse: unset → off) so a merged, partially built package never reaches students; `user_settings.learning_loop_beta` is a staff/QA toggle set by SQL or the seed and read only by the gate. It is in no settings API field, and students can never patch it or see it (A31). PKG-14 half B (the launch, §11) makes the gate env-only with the default ON; from then on `LEARNING_LOOP_ENABLED=false` is only a kill switch. Exact semantics of both phases: §7. With the env var unset during the build, every pre-series test passes unchanged; after the launch, the legacy-route test modules run as explicit kill-switch tests (§11.5).

**Cost envelope (§13 A15–A26, owner decision 2026-09-26).** The loop runs on the routed tutor plan: code picks the tutor tier from phase × band (§3.5 `LOOP_MODEL_TIER`), loop routes ignore `model_pref`, and there is no student-visible model toggle on the loop. Target ≈ $0.36 per student-month ≈ $355 per 1,000 students per month (no-cache upper bound). Per-student caps with a degradation ladder (§3.5) bound the tail; a cap may remove learning opportunities but never creates, weakens or re-channels evidence, and never records one outcome of an attempt while dropping the other.

## 2. Module map

```
backend/learning/                 pure policy + math; NO imports from agents/, pydantic_ai, google, db/ in bkt.py, fsrs.py, policy.py, gates.py, ladder.py, leak.py, probe.py, planner.py
  gate.py            learning_loop_active(user_id) -> bool (build: env AND beta; after PKG-14b: env only)  PKG-00 (PKG-14b rewrites)
  params.py          every named constant in §3 (except those §3.5/§3.6 place in config.py / decisions.py)  PKG-01 (each package appends its own)
  bkt.py             update(), decayed_p(), propagate_prereq(), band(), tier_for()             PKG-01
  fsrs.py            retrievability(), interval(), next_state(), rating_for(), order_due(),   PKG-02
                     budget_select(), successive_relearning state machine
  evidence.py        Evidence model + channel enum; flush_pending()                           PKG-03 (PKG-05 adds flush_pending, grader_backend)
  learner_state.py   read_state (decayed) / write_state; learner_state table access via table() PKG-03
  checks.py          CheckItem models, question_hash(), select_item(), posttest_reserve_hash()  PKG-04
                     (A34: answer_tokens() — the answer normalisation leak.py shares; is_servable())
  ladder.py          Rung enum H0..H6 + rung intent text; check_pose(), deterministic_content()  PKG-06 (A17)
  policy.py          ceiling(), evidence_for_rung(), band_control(), wheelspin(),              PKG-06
                     model_tier() (A15), context_policy() (A18)
  gates.py           genuine_attempt(), rung_unlock(), h6_allowed(), offer_allowed()           PKG-06
  leak.py            detect_leak(reference, emitted, rung, *, final_answer,                    PKG-06
                     canonical_answer=None) -> LeakVerdict; strip_leak(emitted, reference, *,
                     final_answer, canonical_answer=None) (A34: the item's structured answer)
  loop_state_store.py load/save sessions.loop_state (A12); revealed_hashes(), seen_hashes() (A23)  PKG-06 (PKG-07 adds the A23 readers)
  zpd_events.py      typed zpd.* emit helpers (A12)                                            PKG-06
  probe.py           next_probe_item(), probe_done(), novice_floor()                           PKG-08
  planner.py         outer_fringe(), plan()                                                    PKG-08
  session_close.py   build_close(), store_close()                                              PKG-09
  learner_brief.py   build_brief() bounded; store_brief() -> sessions.loop_brief (A19)         PKG-09
  misconceptions.py  record(), slip_or_misconception(), rollup() (n>=5)                        PKG-10
  review.py          due_queue(), serve(), grade_review()                                      PKG-12
backend/agents/_providers.py      slots: check_items (04), grader + grader_second (05), decision (05b),
                                  loop_tutor_lite + loop_tutor + loop_tutor_deep (07), session_close (09)
backend/agents/check_items.py     task "check_items"  (ingest-time item generation)           PKG-04
backend/agents/grader.py          task "grader" (+ slot "grader_second", same prompt)          PKG-05
backend/agents/tools/check.py     grade_answer() ROUTE helper (A16): pre-checks, grader via    PKG-05 (PKG-05b routes it through services/decisions.py)
                                  the decision seam, Evidence appended to deps.pending_evidence;
                                  never persists; NOT a tutor tool (no graded_check_tool exists)
backend/agents/decision.py        task "decision" (Flash-Lite, thinking off; one prompt; typed output per family)  PKG-05b
backend/agents/_jev.py            Jev backend; the ONLY importer of typesafe-sdk (pinned ==0.7.2)  PKG-15 (post-series)
backend/agents/loop_tutor.py      ONE prompt stack; tier slot chosen per run by policy.model_tier (A15)  PKG-07
backend/services/decisions.py     typed decision seam: gemini / function / deterministic backends (jev: PKG-15)  PKG-05b
backend/services/ai_budget.py     per-student caps, degradation ladder, rate limit (A20)      PKG-06b
backend/agents/usage.py, backend/services/llm_pricing.py  cached/thinking tokens + cached-input rate (A21)  PKG-06b
backend/services/rag_service.py::chunks_for_ids(chunk_ids, *, user_id)  visibility-aware by-id reader (A17/A18)  PKG-07
backend/routes/learn_loop.py      /api/learn/loop/* (route table in §9)                        PKG-07..14
backend/services/check_item_service.py  CRUD for check_items (encrypted columns); course_has_items(); coverage; retire_items_for_documents()/_for_uploader() (A23 withdrawal)  PKG-04
backend/scripts/backfill_check_items.py (--course, --all-courses; --regenerate-missing-final-answer, A34), backend/scripts/derive_zpd_metrics.py  PKG-04, PKG-14
backend/db/migrations/<ts>_learning_grader_backend.sql, <ts>_learning_llm_usage_tokens.sql      PKG-05, PKG-06b
backend/db/migrations/<ts>_learning_check_items_final_answer.sql                              PKG-06 (reopens PKG-04, A34)
backend/db/migrations/20260927182054_learning_mastery_event_seq.sql  node_mastery_events.evidence_seq (A36)  PKG-03 reopen
backend/tests/test_learning_loop_invariants.py   grows every package                          PKG-00..14
backend/tests/evals/decisions.py  decision-seam eval harness + §3.6 promotion gates            PKG-05b
frontend/src/components/learn/LoopLearn.tsx, frontend/e2e/learn-loop.spec.ts                 PKG-13
```

## 3. Named constants (single source; `backend/learning/params.py` unless a table says otherwise)

### 3.1 BKT

| Name | Value | Meaning / source |
|---|---|---|
| `BKT_L0` | 0.35 | prior P(known) for a new concept (van de Sande worked example 0.36; report §"Replace the scalar") |
| `BKT_T` | 0.15 | learn-transition probability per opportunity |
| `BKT_G_MAX` | 0.30 | Cognitive Tutor bound on guess |
| `BKT_S_MAX` | 0.30 | slip ceiling for the noisiest channel; `G + S < 1` always |
| `BKT_PROFICIENT` | 0.95 | proficient threshold |
| `BKT_MASTERED` | 0.98 | mastered threshold (Rori 2025) |
| `BKT_MASTERED_MIN_STRONG` | 3 | strong-channel unassisted observations required for "mastered" |
| `BKT_P_MAX` | 0.999 † | ceiling on `bkt.update`'s output, so belief stays below 1 and a wrong answer or `idk` always lowers it; from the cap one wrong `free_response` stays ≥ `BKT_MASTERED` (0.992), two drop below (0.943); `BKT_MASTERED < BKT_P_MAX < 1` (A30) |
| `BAND_NOVICE_MAX` | 0.30 | p_known below → band `novice` |
| `BAND_DEVELOP_MAX` | 0.80 | p_known below → `develop`; else `profic` |
| `WEIGHT_ASSISTED` | 0.5 | correct after H1–H3 |
| `WEIGHT_SAME_SESSION_RECHECK` | 0.5 † | re-check of the same `question_hash` within one session (an unvalidated heuristic, not a research finding; A30) |
| `WEIGHT_PROPAGATION` | 0.5 | one-hop prerequisite propagation |
| `WEIGHT_LOW_CONFIDENCE` | 0.5 | grader confidence below `GRADER_LOW_CONFIDENCE` |

Channel table (`CHANNELS`):

| channel | G | S | strong? | notes |
|---|---|---|---|---|
| `free_response` | 0.08 | 0.10 | yes | rubric-graded against reference |
| `mc_reasoned` | 0.10 | 0.10 | yes | correct option + graded one-sentence reason |
| `mc` | 0.25 | 0.10 | no | 4-option, no reason |
| `teachback_llm` | 0.25 | 0.20 | no | LLM-rubric graded explanation |
| `chat_turn` | 0.30 | 0.30 | no | tutor's judgment of an ungraded turn; contributes almost nothing by design |
| `idk` | (channel's G) | `S_IDK` = 0.02 | — | explicit "I don't know": treated as incorrect with slip 0.02 |

Update (van de Sande 2013), with `w` the observation weight (1.0 unless a §3.1 weight applies; `P' = P + w·(P_post − P)` then learn step `P'' = P' + (1 − P')·T` only when `w == 1.0`):

```
correct:   P_post = P(1−S) / [P(1−S) + (1−P)G]
incorrect: P_post = P·S    / [P·S    + (1−P)(1−G)]
```
`bkt.update` returns its result (`P''`, or `P'` when `w < 1`) capped at `BKT_P_MAX` (A30): any `P` in [0, 1] is a valid input, and the output lies in [0, `BKT_P_MAX`]. Without the cap, back-to-back corrects round `P` to exactly 1.0, where the incorrect posterior is 1 and no contrary evidence can lower it.

Validity asserted at import: `G + S < 1`, `G ≤ BKT_G_MAX`, `S ≤ BKT_S_MAX`, `0 < T < 1 − S/(1−G)` for every channel.

Decay at read: `P_now = BKT_L0 + (P_stored − BKT_L0) · R(Δt, S_c)` where `R` is §3.2 retrievability and `S_c` the concept's FSRS stability; if no FSRS state exists, `S_c = FSRS_S0_GOOD`.

Propagation, one hop, asymmetric, edges `graph_edges.relationship_type = 'prerequisite'` with `source_node_id` = prerequisite, `target_node_id` = dependent (`EDGE_PREREQ_SOURCE_IS_PREREQ = True`; PKG-08 verifies against live data and flips the constant if the convention is reversed):
- correct at c → each prerequisite parent gets a `chat_turn`-strength correct observation at `WEIGHT_PROPAGATION`;
- incorrect at c → each dependent child gets a `chat_turn`-strength incorrect observation at `WEIGHT_PROPAGATION`; parents untouched.

Tier mirror into `graph_nodes.mastery_tier` (CHECK unchanged) on the loop path: `p < 0.10 → unexplored`, `< BAND_NOVICE_MAX → struggling`, `< BKT_PROFICIENT → learning`, else `mastered`. (`TIER_UNEXPLORED_MAX = 0.10`.) Legacy tiers 0.1/0.45/0.75 remain for flag-off until PKG-14 half B, which moves every mirror (`Learn.tsx::tierForScore`, `lib/quiz/proposals.ts`, `lib/graph/nodeStyle.ts` + its table test, `e2e/graph.spec.ts::tierFor`) to these cuts (§11.2).

### 3.2 FSRS-6

```
FSRS_W = [0.212, 1.2931, 2.3065, 8.2956, 6.4133, 0.8334, 3.0194, 0.001, 1.8722, 0.1666,
          0.796, 1.4835, 0.0614, 0.2629, 1.6483, 0.6014, 1.8729, 0.5425, 0.0912, 0.0658, 0.1542]
factor        = 0.9^(−1/w20) − 1
R(t,S)        = (1 + factor·t/S)^(−w20)
I(r,S)        = (S/factor)·(r^(−1/w20) − 1)
S0(G)         = w[G−1]                          G ∈ {1 Again, 2 Hard, 3 Good, 4 Easy}
D0raw(G)      = w4 − e^(w5·(G−1)) + 1           unclamped; D0raw(4) = −4.7716
D0(G)         = clamp(D0raw(G), 1, 10)          first rating: (D0(G), S0(G)); no MC cap, no floor applies
ΔD = −w6·(G−3);  D' = D + ΔD·(10−D)/9;  D'' = clamp(w7·D0raw(4) + (1−w7)·D', 1, 10)
                                                mean reversion toward the UNCLAMPED D0(4); every later rating, same-day included
S_recall      = S·( e^(w8)·(11−D)·S^(−w9)·(e^(w10·(1−R)) − 1)·[w15 if Hard]·[w16 if Easy] + 1 )    G ≥ 2, not same-day
S_lapse       = min( w11·D^(−w12)·((S+1)^(w13) − 1)·e^(w14·(1−R)),  S / e^(w17·w18) )             G = 1, not same-day: a lapse never raises S
SInc          = e^(w17·(G−3+w18))·S^(−w19)
S_same_day    = S·max(1, SInc) for G ≥ 2;  S·SInc for G = 1                                       a same-day pass never lowers S
S'            = max( S_x, FSRS_STABILITY_MIN ),  S_x after the MC cap (S_x ≤ S·MC_STABILITY_GAIN_CAP)  every later S' ≥ 0.001 d
```
The three stability forms use the pre-update `D` and `S`, and `R = R(days since the last review, S)`. Same-day means less than one day since the last review (`now − fsrs_last_review_at < 1 day`, the caller's test in PKG-03/PKG-11; py-fsrs uses `(review − last).days < 1`). The `min`/`max` guards, the unclamped reversion target and the floor are the FSRS-6 reference forms that PKG-02 shipped (A28). With them, `next_state` matches py-fsrs 6.3.2 (whose default weights equal `FSRS_W`) to within 4e-15 relative error at every S.

| Name | Value | Meaning |
|---|---|---|
| `FSRS_RETENTION_DEFAULT` | 0.90 | desired retention |
| `FSRS_RETENTION_LARGE_SET` | 0.85 | when a user has > `FSRS_LARGE_SET_CONCEPTS` scheduled concepts in a course |
| `FSRS_LARGE_SET_CONCEPTS` | 150 | |
| `FSRS_RETENTION_EXAM` | 0.95 | when a syllabus exam is within `FSRS_EXAM_WINDOW_DAYS` |
| `FSRS_EXAM_WINDOW_DAYS` | 14 | |
| `FSRS_S0_GOOD` | `FSRS_W[2]` = 2.3065 days | default stability before first review |
| `FSRS_STABILITY_MIN` | 0.001 days | floor on every stability `next_state` returns after the first rating, applied after the MC cap (FSRS-6 `STABILITY_MIN`; A28) |
| `REVIEW_ORDER_THRESHOLD` | 0.33 | order due items by `abs(R − 0.33)` ascending (DASH) |
| `REVIEW_DAILY_BUDGET_MIN` | 12 | minutes/day |
| `REVIEW_SECONDS_PER_CHECK` | 45 | budget → item count |
| `MC_STABILITY_GAIN_CAP` | 2.0 | `S' ≤ S·cap` after an unassisted MC correct |
| `SR_INITIAL_CRITERION` | 3 | successive relearning: correct recalls in the acquisition session |
| `SR_RELEARN_SESSIONS` | 3 | later sessions each to 1 correct recall |

Rating map (`rating_for(channel, correct, max_rung)`): unassisted correct `free_response`/`teachback_llm`/`mc_reasoned` → Good(3); unassisted correct `mc` → Good with `MC_STABILITY_GAIN_CAP`; correct after H1–H3 → Hard(2); wrong at any rung → Again(1); correct after H4–H6 → Again(1) and a re-ask of an isomorph next session. Easy(4) is never emitted in v1.

### 3.3 Ladder, ceiling, gates, bands (from the ZPD report's policy spec)

Ladder (`Rung` enum): `H0` confirm a correct step · `H1` pump/focus question · `H2` concept pointer, cited course passage · `H3` leading question about the next step · `H4` worked example on an isomorph · `H5` completion problem (last steps blanked) · `H6` full solution.

Ceiling (`policy.ceiling(state) -> Rung`), inputs are typed state only:
```
exam_mode                                   → H1
band == profic                              → H1; H3 after 2 failed genuine attempts
band == develop                             → H3; +1 rung per failed genuine attempt; H6 after ≥ 2
band == novice and prerequisite proficient  → attempt-first, ceiling H5
band == novice and prerequisite not known   → worked example FIRST (H4), then H5, then near-transfer
student showed own work / buggy step        → floor at H3 (never below), outside exam mode only: the exam_mode cap wins over this floor (A4)
```

| Name | Value | Meaning |
|---|---|---|
| `GATE_INDEPENDENT_MIN_S` | 45 † | seconds alone before an attempt counts (develop/profic) |
| `GATE_INDEPENDENT_MIN_S_NOVICE` | 90 † | |
| `GATE_RUNG_DWELL_MIN_S` | 8 † | seconds on the current rung before the next unlocks |
| `H6_MIN_GENUINE_ATTEMPTS` | 2 | plus `item.taught == True`, `item.practice == True` and `item.graded == False`; ungraded is not the same as practice (predicates below, A32) |
| `OFFER_BANDS` | {`novice`} | error-triggered "want a hint?" offer only for novices |

† = engineering choice with no validated cut-point; first A/B candidates; must be marked † in hand-offs.

H6 item predicates (A32). The gate is `gates.h6_allowed(step, *, item_taught, item_practice, item_graded) -> bool` = `step.genuine_attempts ≥ H6_MIN_GENUINE_ATTEMPTS and item_taught and item_practice and not item_graded and not step.exam_mode`. The loop route supplies the three booleans:
- `taught`: the item's concept got at least one served teach turn, or one check with its feedback turn, in this session before the item was activated. PKG-07 records it on the item's `loop_state` entry at activation. A "Check me" on a concept not yet taught is not taught, so the gate fails closed.
- `practice`: the item is the session's active in-session check (`loop_state["active"]`). Only `_activate_next_item` sets that key, and it never selects the concept's post-test reserve (A23, A27). No column marks practice, because every `check_items` row is practice material by construction: PKG-04 drafts items only from shared `course_material` (A23), and a student's `completed_work` (coursework, graded or not) is never a source. Assessment is a property of the use, not the row. The probe (placement, no hints), review (no hints before the attempt), the post-test (ceiling H0) and the post-test reserve never reach H6.
- `graded`: the stored `check_items.graded` coursework flag. It is false on every generated item, and a missing item fails closed.

`not graded` alone never admits H6. Any future path that imports coursework into `check_items` must first add an explicit column in a new migration.

Genuine attempt = a submitted answer or shown work, not `idk`/"just tell me", after the independent-time gate. "just tell me"/"give me the answer" patterns are detected by a small deterministic list in `gates.py` (`NON_ATTEMPT_PATTERNS`), never by an LLM. The independent-time gate decides whether an attempt counts toward hint unlocking; it never blocks grading of an explicit submission (A16).

Success bands (rolling window `BAND_WINDOW = 8` first attempts):

| Phase | Target | Name |
|---|---|---|
| probe | expected P(correct) 0.50–0.62 | `PROBE_TARGET_LO/HI` |
| acquisition (assisted) | 0.75–0.90 | `ACQ_TARGET_LO/HI` |
| practice (unassisted) | 0.65–0.85 | `PRACTICE_TARGET_LO/HI` |
| review | arrive at R = `FSRS_RETENTION_*` | |
| exam prep | 0.70–0.85 unassisted | `EXAM_TARGET_LO/HI` |
| peer / ConcepTest | ask the room only when 0.35–0.70 of ≥ `PI_MIN_ROOM` (5) are initially correct | `PI_LO/HI`, `PI_MIN_ROOM` |

Band control (`policy.band_control(window)`):
```
unassisted_next > 0.90 for 2 windows AND p ≥ BKT_PROFICIENT AND stable → stop practice, hand to scheduler
unassisted_next > 0.90, p < BKT_PROFICIENT                             → item difficulty +1 step; ceiling −1 rung
0.65 ≤ unassisted_next ≤ 0.90                                          → hold
unassisted_next < 0.65                                                  → check prerequisites; difficulty down freely; ceiling +1 rung
wheelspin                                                               → stop more-of-the-same; prerequisite repair; flag instructor; emit zpd.wheelspin
```
`wheelspin = opps ≥ WHEELSPIN_OPPS (10) AND streak_unassisted never reached 3, OR (opps ≥ 6 AND unassisted_next < 0.50)`.

Evidence mapping by rung (`policy.evidence_for_rung`):
- unassisted first-attempt correct → full strong-channel observation; counts toward `streak_unassisted`; FSRS Good
- correct after H1–H3 → `WEIGHT_ASSISTED`; counts 0 toward streak; FSRS Hard
- correct after H4–H6 → no upward BKT evidence; FSRS Again; schedule isomorph re-ask
- wrong at any rung → standard incorrect observation; corrective feedback WITH the answer, immediately
- same-session re-check → `WEIGHT_SAME_SESSION_RECHECK`
- confidence / reason tier → diagnosis only; never a hint gate
- a deterministic H2/H4 payload that fails the leak check and is served anyway is recorded as H6 (A17)

Slip / misconception / novice rule (`misconceptions.slip_or_misconception`):
- wrong once → `unknown`: standard update; re-ask an isomorph (different surface, same `node_id`, different `question_hash`)
- wrong then right on the isomorph → `slip`: no misconception record
- wrong on ≥ 2 isomorphs with the same `wrong_key`, or wrong with stated confidence ≥ `MISCONCEPTION_CONFIDENCE (0.7)` → `misconception`: record; tutor confronts with a contradiction
- wrong with low confidence → `gap`: teach
- right answer, wrong reason → `not_known`: treat as a miss
- 3 misses at difficulty 1 or repeated `idk` (`NOVICE_FLOOR_MISSES = 3`) → `novice`: exit probe; novice step format on the lowest prerequisite
- a `wrong_key` enters this rule only when the student's reason matched it (the grader's `matched_wrong_key`, or later a decision-seam Choice); an `mc_reason` option → key map is a prior, never a record on its own (A22)

### 3.4 Probe, plan, step, brief, limits

| Name | Value |
|---|---|
| `PROBE_ITEMS_PER_SKILL_MIN` / `MAX` | 4 / 6 |
| `PROBE_SESSION_CAP` | 12 |
| `PROBE_STOP_DELTA` | 0.05 (stop when the last two posteriors move less than this) |
| `PLAN_MAX_CONCEPTS` | 5 independent (`PLAN_MAX_COUPLED = 2` when tightly coupled: share a parent) |
| `PLAN_ORDER` | due reviews → new material → interleaved siblings |
| `STEP_MAX_SENTENCES` | 5 (prompt + evaluator) |
| `STEP_QUESTIONS_PER_TURN` | 1 |
| `LOOP_HISTORY_MAX_MESSAGES` | 20 (replaces unbounded `_load_message_history` on the loop path; upper bound — the loop holds 10–19 messages, trimmed in blocks of `LOOP_HISTORY_TRIM_BLOCK`, A19) |
| `LEARNER_BRIEF_MAX_CHARS` | 1800 |
| `LEARNER_BRIEF_LAST_CLOSES` | 3 |
| `LEARNER_BRIEF_TOP_STATES` | 5 |
| `LEARNER_BRIEF_MAX_MISCONCEPTIONS` | 5 |
| `LOOP_LIMITS` | request 4 / tool calls 3 / tokens 40_000 † (`agents/__init__.py`; A18 — was 14/14/120_000) |
| `GRADER_LIMITS` | request 2 / tool calls 0 / tokens 20_000 |
| `GRADER_LOW_CONFIDENCE` | 0.6 → `WEIGHT_LOW_CONFIDENCE`; below `GRADER_SECOND_OPINION_CONFIDENCE` (0.4) → ONE second call on slot `grader_second` (A22), still below → `unavailable` |
| `LEAK_NGRAM` | 6 tokens of the reference answer appearing verbatim in emitted text at rung < H6 → leak; also a match of the item's structured final_answer (and canonical_answer when present) (A34) |
| `CHECK_ITEM_FORMATS` | `free`, `teachback`, `mc_reason` |
| `CHECK_ITEM_DIFFICULTIES` | 1, 2, 3 |
| `CHECK_ITEM_MIN_RUBRIC` | 2 |
| `CHECK_ITEM_MIN_WRONG` | 1 |
| `MISCONCEPTION_ROLLUP_MIN_USERS` | 5 |
| `ZPD_RATING_EVERY_N_CHECKS` | 30 (perceived difficulty prompt: too_easy / appropriate / too_hard) |
| `LOOP_TEACH_TURNS_BEFORE_CHECK` | 2 † (served teach turns on the current concept before its next check item is activated, A27) |
| `LOOP_CHECKS_PER_CONCEPT` | 2 † (graded in-session checks per plan concept before the cursor advances; = the "+ 2 isomorphs" of `CHECK_ITEM_INITIAL_PER_CONCEPT`, A27) |
| `LOOP_CHECK_DIFFICULTY_BY_BAND` | `{novice: 1, develop: 2, profic: 3}` † (target difficulty of an activated check item; `select_item` falls back to the nearest, A27) |

### 3.5 Cost and routing (§13 A15–A23, A25, A26, A35)

**Target.** Routed tutor plan ≈ $0.36 per student-month ≈ $355 per 1,000 students per month, a no-cache upper bound (all input billed at the full rate; ≈ $331 with Gemini's default implicit caching). Modelled tier mix 25% lite / 60% standard / 15% deep (Pro, thinking ≤ 1,024, averaging 800) †; template turns are free. These are estimates until A21's `llm_usage` columns and PKG-14's metrics measure the real mix. A novice session costs ≈ 3–3.5× an average one, so every cap is band-aware.

Loop tutor (`learning/params.py`; `LOOP_LIMITS` lives in `agents/__init__.py`, §3.4):

| Name | Value | Meaning |
|---|---|---|
| `LOOP_PRO_THINKING_BUDGET` | 1024 † | deep slot thinking cap (2.5 Pro cannot go below 128; never send 0) |
| `LOOP_FLASH_THINKING_BUDGET` | 0 | standard slot thinking |
| `LOOP_MAX_VISIBLE_TOKENS` | 400 † | per-run `max_tokens` = the slot's thinking budget + this (Gemini's `max_output_tokens` includes thinking) — makes the per-run bound hard |
| `LOOP_HISTORY_TRIM_BLOCK` | 10 † | history keeps `n` messages when `n < 10`, else `10 + (n mod 10)`: 10–19 messages, the window start moves in blocks (A19) |
| `LOOP_RAG_K_TEACH` | 5 | RAG k in the teach phase (unchanged from legacy) |
| `LOOP_RAG_K_TEACH_SOFT` | 3 † | teach RAG k at the soft budget level (named by this spec; the report states the value) |
| `LOOP_SOURCE_CHUNKS_MAX` | 2 † | the item's own source chunks given to feedback and hint turns |
| `LOOP_SESSION_MAX_TUTOR_REQUESTS` | 40 † | per-session tutor requests (an optimized 10-turn session uses ≈ 7); reaching it = hard |
| `LOOP_SESSION_MAX_DEEP_REQUESTS` | 6 † | develop/profic: reaching it = soft (deep → standard) |
| `LOOP_SESSION_MAX_DEEP_REQUESTS_NOVICE` | 12 † | novice: reaching it turns novice deep turns into standard (a novice 10-turn session uses 4.4–5.9) |
| `GRADER_SECOND_OPINION_SLOT` | `"grader_second"` | the second grader call runs on a different model (A22) |

Model slots (`agents/_providers.py::_DEFAULTS`; `SAPLING_MODEL_<TASK>` overrides apply; `llm_usage.task` records the slot name):

| slot | model | settings | package |
|---|---|---|---|
| `loop_tutor_lite` | gemini-2.5-flash-lite | thinking off; `max_tokens = LOOP_MAX_VISIBLE_TOKENS` | PKG-07 |
| `loop_tutor` (standard) | gemini-2.5-flash | `thinking_budget = LOOP_FLASH_THINKING_BUDGET` | PKG-07 |
| `loop_tutor_deep` | gemini-2.5-pro | `thinking_budget = LOOP_PRO_THINKING_BUDGET` | PKG-07 |
| `grader_second` | gemini-2.5-flash | `thinking_budget = 0`; same prompt as `grader` | PKG-05 |
| `decision` | gemini-2.5-flash-lite | thinking off | PKG-05b |

The three tutor slots and the two grader slots each share ONE agent and ONE system prompt; the slot is chosen per run (`agent.run(..., model=model_for(slot), model_settings=...)`), never by a second `Agent(` (invariant 12).

`LOOP_MODEL_TIER` (`policy.model_tier`, PKG-06; the first five rows pick the base tier, first match wins; the two `then:` rows adjust it):

| State | Tier |
|---|---|
| hard budget level | `none` (deterministic only); novice-band concepts pause |
| check pose; H2 and H4 when a leak-clean deterministic payload exists; H6 | `none` (template) |
| feedback after a correct answer; proficient-band verification | `lite` |
| teach in the novice band; H4 with no usable sibling; H5; misconception confrontation (PKG-10); ≥ 2 failed genuine attempts | `deep` |
| opener; teach in the develop or proficient band; H1/H3; feedback after a wrong answer | `standard` |
| then: soft level (develop/profic turns) or `LOOP_SESSION_MAX_DEEP_REQUESTS` reached | `deep` → `standard`; `loop_arm` sessions are not downgraded (they pause at the hard level instead) |
| then: `LOOP_SESSION_MAX_DEEP_REQUESTS_NOVICE` reached (novice turns) | `deep` → `standard`; the $-based soft level never downgrades novice deep turns |

Budget (`config.py`, env-overridable; "spend" = today's (UTC) `sum(llm_usage.cost_usd)` for the user, every row including legacy, one read on `idx_llm_usage_user_created`, cached per request):

| Name | Value | Meaning |
|---|---|---|
| `STUDENT_DAILY_BUDGET_USD` | 0.20 † | band daily cap for develop/profic turns (≈ 7–8 routed sessions) |
| `BUDGET_NOVICE_MULTIPLIER` | 2.5 † | novice-band turns run to 0.20 × 2.5 = $0.50/day |
| `STUDENT_SOFT_FRACTION` | 0.8 † | soft level starts at this fraction of the band's daily $ or token budget |
| `STUDENT_MONTHLY_BUDGET_USD` | 2.00 † | calendar month (UTC); ≈ 5.6× the routed estimate; reaching it = hard |
| `STUDENT_DAILY_TOKENS` | 400_000 † | secondary guard immune to price-table drift (input + output incl. thinking; ≈ 8–9 sessions) |
| `STUDENT_DAILY_GRADES` | 300 † | grader cap: the user's `llm_usage` rows today with `task` ∈ {`grader`, `grader_second`, `decision`} (a heavy day is ≈ 52–53 grades incl. second opinions) |
| `LEARN_RATE_LIMIT_PER_MIN` | 20 † | `llm_usage` rows of the user in the last 60 s; over it → HTTP 429 (Redis is off by default) |
| `PLATFORM_DAILY_BUDGET_USD` | unset (the owner sets it) | platform spend alert; never blocks a request |
| `PLATFORM_ALERT_FRACTION` | 0.8 † | alert level for the platform budget (named by this spec) |
| `PLATFORM_CHECK_INTERVAL_S` | 300 † | the platform aggregate is read at most once per this per process (named by this spec) |

Check items (`learning/params.py`):

| Name | Value | Meaning |
|---|---|---|
| `CHECK_ITEM_INITIAL_PER_CONCEPT` | 9 † | = `len(CHECK_ITEM_FORMATS) × len(CHECK_ITEM_DIFFICULTIES)`; ≥ `PROBE_ITEMS_PER_SKILL_MAX` + 2 isomorphs + 1 post-test reserve |
| `CHECK_ITEM_CONCEPTS_PER_CALL` | 3 † | concepts per `check_items` agent call |
| `FLEX_TIMEOUT_S` | 900 | `service_tier='flex'` timeout; background prefill only |
| `CHECK_ITEM_ANSWER_KINDS` | `("free", "numeric")` | `symbolic`/`exact` deferred (need a CAS dependency and an equivalence eval) |
| `CHECK_ITEM_BACKFILL_MIN_CHUNK_SCORE` | 1 † | the backfill drafts a concept only when a shared passage contains ≥ this many of its tokens (A23 relevance floor) |
| `CHECK_ITEM_FINAL_ANSWER_MAX_TOKENS` | 20 † | the most answer tokens (`checks.answer_tokens`) a check item's structured `final_answer` may hold (A34) |

Uploads (`config.py`; defined and consumed on the decision seam by #641, outside the series — no series package adds them):

| Name | Value |
|---|---|
| `UPLOAD_CLASSIFY_EXCERPT_TOKENS` | 2_000 † |
| `RERANK_CANDIDATES` | 20 |
| `RERANK_KEEP` | 5 |

**Class summary (A35).** With the loop on, the class summary costs nothing: `update_course_context` writes the class numbers to `offering_summary` with no prose (`summary_text` and `summary_hash` NULL), and no other code writes the prose, because nothing reads it. So a student's spend has no class-summary term, on the answer path or off it. Before A35 every evidence flush regenerated the prose on gemini-2.5-flash for each of the student's offerings of the course: ≈ $0.0022 per offering per flush, ≈ 15× the cost of the grade itself (live sequence test 2026-09-27: 10 calls, $0.021969, 84% of the run; grading $0.000573 in all). A reader that brings the prose back needs its own amendment, and that amendment must meet four conditions. It adds the cost to this envelope. It keeps the call off the answer path. If a background task writes the prose, the task claims each offering across app instances (as `services/index_sweeper.py` does with `SKIP LOCKED`), so N instances do not pay N times. It also caps retries of a failing call. That cost is platform spend: the `course_summary` call records no `user_id`, so the A20 per-student caps never see it.

There is no verdict cache and no `GRADER_CACHE_MIN_CONFIDENCE` (< $1 per 1,000 students per month). If one is ever built: key (item id, rubric hash, sha256 of the exact answer), scoped per user.

**Degradation ladder** (`services/ai_budget.py::check(user_id, kind, band=None, *, session_tutor_requests=0, session_deep_requests=0, arm_session=False) -> BudgetDecision{level: "normal"|"soft"|"hard", tier_ceiling: Tier, scope, reset_at, pause_novice: bool}`; `kind ∈ {"tutor","grader","decision","close"}`; `band` is required for `tutor` and ignored for the grader cap; the session counters live in `sessions.loop_state` as ints `tutor_requests`/`deep_requests`, maintained by PKG-07; spend and grade counts come from ONE `llm_usage` read since the UTC month start, cached per request):

| Level | Trigger | Behaviour |
|---|---|---|
| normal | below the soft level | routed as designed |
| soft | ≥ `STUDENT_SOFT_FRACTION` of the band's daily $ or `STUDENT_DAILY_TOKENS`, or the band's per-session deep cap | develop/profic deep → standard; novice deep turns keep running until the novice $ allowance is spent (only the novice deep-request cap downgrades them); teach RAG k = `LOOP_RAG_K_TEACH_SOFT`; search disabled via `tool_choice='none'` (declarations unchanged); H4 uses a deterministic sibling only when one passes the isomorph and leak rules; `loop_arm` sessions are exempt from downgrades |
| hard | ≥ 100% of the band's daily $, `STUDENT_MONTHLY_BUDGET_USD`, `STUDENT_DAILY_TOKENS`, `LOOP_SESSION_MAX_TUTOR_REQUESTS`, or the rate limit | `loop_tutor*` make no calls; novice-band concepts pause (no check is served for them on any surface except the probe) — except when the rate limit is the only trigger (`pause_novice=false`: a 60-second burst never drops review items); tutor routes answer HTTP 429 `{"detail": "ai budget reached", "reset_at": <iso>}` and the stream emits a `budget` event; the UI shows "Tutor chat paused until <reset>. Practice and review keep working." |
| grader cap | ≥ `STUDENT_DAILY_GRADES` (kind `grader`/`decision` grading only) | free-text and `mc_reason` attempts return `GradeResult(unavailable=True)` and **no evidence is written for either outcome**; quiz `mc` (graded in code) is unaffected |

At the hard level these keep working: a template session opener (`_LOOP_OPENER_TEMPLATE`, so a capped student can still start a session and reach the probe, A27), probe selection (grading has its own cap), the check-pose template and grading for develop/profic concepts, pure `mc` grading, leak-checked H2, H6 (under `h6_allowed`) and the H4 sibling, BKT/FSRS updates, the review queue, self-rated flashcards, a deterministic session close (`model_written=false`, A8/A25). Every cap hit emits `ai.budget_capped` at most once per process per (user, scope, level, UTC day).

**Validity rule for every cap.** A cap may remove learning opportunities. It never creates evidence, weakens evidence, or moves an answer to another channel. Missingness never depends on the outcome: if one outcome of an attempt cannot be graded, neither is recorded (invariant 28). A cap never routes grading to a backend that has not passed §3.6's gates.

### 3.6 Decision seam (`services/decisions.py` settings — NOT `learning/params.py`; PKG-05b defines them, Jev absent)

Only `JEV_ENABLED` and the `DECISION_BACKEND_<NAME>` env values are read in the series; the rest are consumed by PKG-15 (post-series) and by `tests/evals/decisions.py`.

Selection: each decision reads env `DECISION_BACKEND_<NAME>` ∈ {`gemini` (default), `jev`, `shadow_jev`}; `JEV_ENABLED=false` (the default) overrides all of them to `gemini`. Until PKG-15, `jev` is served by `gemini` with a `decision.fallback` event (reason `jev_absent`) and `shadow_jev` is a no-op. `SAPLING_MODEL_MODE=function` serves every decision from fixed `E2E_DECISION_*` constants; the loop's routing decisions are `deterministic` (`policy.model_tier`, `policy.context_policy`) and never call a model.

Jev client (PKG-15):

| Name | Value |
|---|---|
| `JEV_ENABLED` | false |
| `JEV_MODEL` | `"jev-1.13.0"` (pinned; never an alias) |
| `JEV_SDK_VERSION` | `typesafe-sdk==0.7.2` (exact pin in `requirements.txt`; Python SDK; no Java SDK exists) |
| `JEV_TIMEOUT_MS` | 800 † |
| `JEV_MAX_RETRIES` | 1 |
| `JEV_CIRCUIT_FAILS` | 5 † |
| `JEV_CIRCUIT_COOLDOWN_S` | 300 † |
| `JEV_STATE_MAX_TOKENS` | 28_000 † (under the 32k state + longest-question limit; oversize states go to Gemini, never truncated) |

Promotion gates (per decision, shadow → serve; all must pass on pinned `jev-1.13.0`):

| Name | Value | Gate |
|---|---|---|
| `DECISION_PROMOTE_MIN_GOLD` | 200 † | gold labels per decision (synthetic or consented de-identified until the privacy gate passes; grading sets include partial-credit answers; numeric items tracked separately) |
| `DECISION_PROMOTE_MAX_ACC_DROP` | 0.02 † | accuracy vs the Gemini backend on the same gold set |
| `GRADER_PROMOTE_MIN_KAPPA` | 0.70 † | κ with gold; `tests/evals/grader.py` agreement ≥ baseline |
| `DECISION_PROMOTE_MAX_ECE` | 0.05 † | calibration; thresholds refit per question form, never copied from Gemini |
| `SHARE_FALSE_POSITIVE_MAX` | 0.01 † | shareability false-share rate (also ≤ Gemini's); grading false-yes ≤ Gemini's; router false "easy" on hard turns ≤ 5% |
| `GRADER_BKT_REPLAY_MAX_DELTA` | 0.02 † | mean `abs(Δp_known)` when gold verdicts are replayed through `bkt.update` |
| `DECISION_SHADOW_MIN_DAYS` | 7 | live shadow duration |
| `DECISION_SHADOW_MIN_N` | 1000 † | live shadow volume; 100 disagreements hand-labelled |
| `DECISION_SHADOW_MIN_AGREEMENT` | 0.90 † | agreement with Gemini in shadow |
| `DECISION_P95_MS` | 300 † | p95 measured from Sapling's host |
| `DECISION_MAX_ERROR_RATE` | 0.005 † | error rate; measured $/decision ≤ Gemini's; injection-fixture flip rate ≤ Gemini's |

## 4. Schemas (DDL written by the named package; prefixes generated with `date -u +%Y%m%d%H%M%S`; basename `<ts>_learning_<desc>.sql`)

```sql
-- PKG-00: <ts>_learning_loop_beta.sql   (APPLIED; its header says "per-user opt-in for the new tutor loop" —
-- that describes the build phase and is immutable; the cutover ADR records the column as a retired staff/QA toggle)
ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS learning_loop_beta boolean NOT NULL DEFAULT false;

-- PKG-03: <ts>_learning_learner_state.sql
CREATE TABLE IF NOT EXISTS learner_state (
  user_id            text NOT NULL,
  node_id            text NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
  p_known            double precision NOT NULL,
  n_strong_unassisted int NOT NULL DEFAULT 0,
  streak_unassisted  int NOT NULL DEFAULT 0,
  max_streak_unassisted int NOT NULL DEFAULT 0,   -- Amendment A3: wheelspin needs "ever reached 3"
  opps               int NOT NULL DEFAULT 0,
  fsrs_d             double precision,
  fsrs_s             double precision,
  fsrs_last_review_at timestamptz,
  fsrs_due_at        timestamptz,
  htc_k              double precision,
  unassisted_next    double precision,
  assist_gap         double precision,
  in_zone            boolean,
  last_evidence_at   timestamptz,
  updated_at         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, node_id)
);
CREATE INDEX IF NOT EXISTS learner_state_due_idx ON learner_state (user_id, fsrs_due_at);
ALTER TABLE node_mastery_events
  ADD COLUMN IF NOT EXISTS channel text,
  ADD COLUMN IF NOT EXISTS correct boolean,
  ADD COLUMN IF NOT EXISTS weight double precision,
  ADD COLUMN IF NOT EXISTS assisted boolean,
  ADD COLUMN IF NOT EXISTS max_rung smallint,
  ADD COLUMN IF NOT EXISTS p_before double precision,
  ADD COLUMN IF NOT EXISTS p_after double precision,
  ADD COLUMN IF NOT EXISTS session_id text,
  ADD COLUMN IF NOT EXISTS check_item_id text,
  ADD COLUMN IF NOT EXISTS question_hash text,
  ADD COLUMN IF NOT EXISTS confidence double precision;
-- evidence rows use event_type = 'evidence'; delta = p_after - p_before keeps legacy readers valid.

-- PKG-04: <ts>_learning_check_items.sql
-- Check items are COURSE assets, not per-student rows. graph_nodes is keyed per
-- (user, course, concept_name), so a node_id FK would bind an item to the
-- uploader. Key on (course_id, concept_key) instead, where concept_key =
-- services/graph_service._normalize_concept(concept_name). A student's node maps
-- to its items via _normalize_concept(graph_nodes.concept_name). (Amendment A2.)
CREATE TABLE IF NOT EXISTS check_items (
  id                text PRIMARY KEY,
  course_id         text NOT NULL,
  concept_key       text NOT NULL,
  document_id       text,
  format            text NOT NULL CHECK (format IN ('free','teachback','mc_reason')),
  difficulty        smallint NOT NULL CHECK (difficulty BETWEEN 1 AND 3),
  prompt            text NOT NULL,          -- encrypted
  reference_answer  text NOT NULL,          -- encrypted
  rubric_json       text NOT NULL,          -- encrypted JSON: [{"id": "...", "text": "..."}], >= CHECK_ITEM_MIN_RUBRIC
  common_wrong_json text NOT NULL,          -- encrypted JSON: [{"key": "...", "text": "..."}]; key is the plaintext id used elsewhere
  options_json      text,                   -- encrypted JSON [{"letter","text","wrong_key"}]; mc_reason only; exactly 1 correct (A22)
  correct_option    text,                   -- encrypted letter; mc_reason only (A22)
  answer_kind       text NOT NULL DEFAULT 'free' CHECK (answer_kind IN ('free','numeric')),   -- A22
  canonical_answer  text,                   -- encrypted; numeric only; parseable (A22)
  tolerance         double precision,       -- numeric only (A22)
  canonical_verified boolean NOT NULL DEFAULT false,  -- true ONLY on independent second-model agreement or instructor confirmation (A22)
  stepwise          boolean NOT NULL DEFAULT false,   -- reference has >= 2 numbered steps; H4 sibling eligibility (A17)
  source_chunk_ids  text[] NOT NULL DEFAULT '{}',
  source_document_ids text[] NOT NULL DEFAULT '{}',  -- documents whose passages drafted this item; withdrawal deletes by these (A23)
  question_hash     text NOT NULL,          -- sha256 of PLAINTEXT prompt (ADR 0025 pattern)
  graded            boolean NOT NULL DEFAULT false,   -- graded coursework flag; false on every generated item. Ungraded is not "practice" (H6 predicates, §3.3, A32)
  created_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (course_id, concept_key, question_hash)
);
CREATE INDEX IF NOT EXISTS check_items_concept_idx ON check_items (course_id, concept_key, format, difficulty);
CREATE INDEX IF NOT EXISTS check_items_source_docs_idx ON check_items USING gin (source_document_ids);

-- PKG-06 (reopens PKG-04): <ts>_learning_check_items_final_answer.sql  (A34)
ALTER TABLE public.check_items ADD COLUMN IF NOT EXISTS
  final_answer text;                        -- encrypted; verbatim from reference_answer (A34)
-- nullable only so existing rows migrate; checks.select_item / posttest_reserve_hash never
-- serve a row without one, and the backfill's --regenerate-missing-final-answer redrafts it.

-- PKG-05: <ts>_learning_grader_backend.sql  (A22)
ALTER TABLE node_mastery_events ADD COLUMN IF NOT EXISTS grader_backend text
  CHECK (grader_backend IS NULL OR grader_backend IN ('deterministic','gemini','gemini_second','jev'));

-- PKG-03 reopen: 20260927182054_learning_mastery_event_seq.sql  (A36)
ALTER TABLE node_mastery_events ADD COLUMN IF NOT EXISTS evidence_seq integer
  CHECK (evidence_seq IS NULL OR evidence_seq >= 0);
-- 0..n-1 in apply order within one apply_graph_update call, whose journal rows share one created_at;
-- NULL on legacy rows and on evidence rows written before it. A reader orders by (created_at, evidence_seq, id) (A36).

-- PKG-06: <ts>_learning_session_loop_state.sql
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS loop_state jsonb NOT NULL DEFAULT '{}'::jsonb;
-- keyed by question_hash: {rung, attempts, first_shown_at, last_rung_at, attempted_at[]}; no free text.
-- top-level id lists added later: "revealed" (A23, H4 siblings shown), "probe", "plan", "sr", "review" (PKG-08/12).

-- PKG-06b: <ts>_learning_llm_usage_tokens.sql  (A21; llm_usage already has user_id, provider, idx_llm_usage_user_created — 0035)
ALTER TABLE llm_usage
  ADD COLUMN IF NOT EXISTS cached_tokens int,
  ADD COLUMN IF NOT EXISTS thinking_tokens int;

-- PKG-09: <ts>_learning_session_close.sql
ALTER TABLE sessions
  ADD COLUMN IF NOT EXISTS close_json text,          -- encrypted JSON {summary, self_eval, if_then, concepts:[{node_id, p_before, p_after}], misconceptions:[wrong_key]}
  ADD COLUMN IF NOT EXISTS close_phase text CHECK (close_phase IN ('probe','plan','teach','check','feedback','close')),
  ADD COLUMN IF NOT EXISTS loop_brief text;          -- encrypted learner brief, built once per session (A19)

-- PKG-10: <ts>_learning_misconceptions.sql
CREATE TABLE IF NOT EXISTS misconceptions (
  id             text PRIMARY KEY,
  user_id        text NOT NULL,
  node_id        text NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
  check_item_id  text,
  wrong_key      text NOT NULL,             -- plaintext enum key from common_wrong_json
  evidence_text  text,                      -- encrypted
  count          int NOT NULL DEFAULT 1,
  first_seen_at  timestamptz NOT NULL DEFAULT now(),
  last_seen_at   timestamptz NOT NULL DEFAULT now(),
  resolved_at    timestamptz
);
CREATE INDEX IF NOT EXISTS misconceptions_user_node_idx ON misconceptions (user_id, node_id, wrong_key);
-- graph_nodes rows are per user, so the rollup groups by the COURSE concept, never by
-- node_id (A29). concept_key mirrors services/graph_service._normalize_concept (runs of
-- whitespace become one space, trimmed, case-folded) and equals check_items.concept_key
-- (A2). SQL lower() stands in for Python casefold(): they agree on ASCII names and
-- can differ on some non-ASCII characters (e.g. ß, which casefold expands).
CREATE OR REPLACE FUNCTION misconception_rollup(p_course_id text)
RETURNS TABLE (concept_key text, wrong_key text, users int)
LANGUAGE sql SECURITY DEFINER AS $$
  SELECT lower(btrim(regexp_replace(g.concept_name, '\s+', ' ', 'g'))), m.wrong_key,
         count(DISTINCT m.user_id)::int
  FROM misconceptions m JOIN graph_nodes g ON g.id = m.node_id
  WHERE g.course_id = p_course_id AND m.resolved_at IS NULL
  GROUP BY g.course_id, lower(btrim(regexp_replace(g.concept_name, '\s+', ' ', 'g'))), m.wrong_key
  HAVING count(DISTINCT m.user_id) >= 5
$$;
REVOKE ALL ON FUNCTION misconception_rollup(text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION misconception_rollup(text) TO service_role;

-- PKG-11: <ts>_learning_flashcards_fsrs.sql
ALTER TABLE flashcards
  ADD COLUMN IF NOT EXISTS fsrs_d double precision,
  ADD COLUMN IF NOT EXISTS fsrs_s double precision,
  ADD COLUMN IF NOT EXISTS due_at timestamptz,
  ADD COLUMN IF NOT EXISTS reps int NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS lapses int NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS flashcards_due_idx ON flashcards (user_id, due_at);

-- PKG-12: <ts>_learning_sessions_mode_review.sql  (Amendment A9)
-- 0025 constrains sessions.mode to socratic/expository/teachback; review sessions need 'review'.
ALTER TABLE sessions DROP CONSTRAINT IF EXISTS sessions_mode_check;
ALTER TABLE sessions ADD CONSTRAINT sessions_mode_check
  CHECK (mode IN ('socratic','expository','teachback','review'));

-- PKG-14: <ts>_learning_loop_arm.sql
ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS loop_arm text;
```

Encryption: `prompt`, `reference_answer`, `rubric_json`, `common_wrong_json`, `options_json`, `correct_option`, `canonical_answer`, `final_answer` (check_items), `evidence_text` (misconceptions), `close_json`, `loop_brief` (sessions) use `services/encryption.py` (`encrypt_if_present` / `encrypt_json` at write, `decrypt_if_present` / `decrypt_json` at read; decrypted in memory only, including before any decision-seam state). Never filter or join on them. `question_hash`, `wrong_key`, `answer_kind`, `tolerance`, `canonical_verified`, `stepwise`, `grader_backend`, `evidence_seq`, `cached_tokens`, `thinking_tokens` are plaintext. `learning_loop_beta` is in no settings API field: `routes/profile.py` never selects, patches or returns it, and only `learning/gate.py` reads it (A31).

## 5. Evidence model (`backend/learning/evidence.py`)

```python
class Evidence(BaseModel):
    node_id: str
    channel: Literal["free_response","mc_reasoned","mc","teachback_llm","chat_turn"]  # the ITEM's channel
    idk: bool = False               # Amendment A1: explicit "I don't know" → correct=False, slip S_IDK, channel's G
    correct: bool
    assisted: bool = False          # any rung H1..H3 used before the answer
    max_rung: int = 0               # 0..6
    weight: float = 1.0             # product of applicable §3.1 weights
    session_id: str | None = None
    check_item_id: str | None = None
    question_hash: str | None = None
    confidence: float | None = None # grader confidence 0..1
    same_session_recheck: bool = False
    grader_backend: Literal["deterministic","gemini","gemini_second","jev"] | None = None  # A22; PKG-05 reopens PKG-03
    verdict: str | None = None      # PKG-10 (slip/misconception rule result)
    wrong_key: str | None = None    # PKG-10; set only when the student's reason matched the key (A22)
```
`apply_graph_update(user_id, graph_update, course_id=None)` accepts `graph_update["evidence"] = [Evidence-as-dict, ...]` (and `graph_update["retention"]: float`, PKG-12). When present: for each evidence, read decayed state, run `bkt.update`, apply propagation, upsert `learner_state`, mirror `graph_nodes.mastery_score = p_known` and tier per §3.1, append one `node_mastery_events` row with `event_type='evidence'` and the new columns (including `grader_backend`, and `evidence_seq` = 0..n−1 in apply order within the call, A36), update FSRS state via `fsrs.next_state(rating_for(...))`. When absent, the legacy `updated_nodes` path runs byte-identically. No other module writes `graph_nodes`, `graph_edges`, `node_mastery_events` or `learner_state`.

Evidence is appended to `deps.pending_evidence` only by `agents/tools/check.py::grade_answer` (and by the probe/quiz/review routes that build it from a code-side verdict) and persisted only by a route through `flush_pending` → `apply_graph_update` (A16).

## 6. Events (add to `EVENT_TAXONOMY` with the pin test; the emitting package adds its own)

| type | category | payload keys (ids/counts/enums/numbers only) | package |
|---|---|---|---|
| `zpd.step` | usage | request_id, user_id, concept_id, question_hash, phase, channel, band, ceiling, ceiling_reason, first_attempt_correct, n_attempts, max_rung_used, rungs[{rung,dwell_ms}], time_to_first_attempt_ms, time_to_correct_ms, independent_time_ms, assisted, confidence, fsrs_rating, p_known_before, p_known_after, r_before, item_difficulty, **tier** (lite/standard/deep/none, A15), **grader_backend** (A22/A24), variant (A8) | PKG-06 (keys), PKG-07 (emits) |
| `zpd.offer` | usage | accepted, band | PKG-06 |
| `zpd.band_adjust` | usage | direction, trigger, window_stats | PKG-06 |
| `zpd.wheelspin` | error | concept_id, opps, unassisted_next, htc_k, prerequisite_ids | PKG-06 |
| `zpd.leak` | error | rung_emitted, ceiling, detector, request_id | PKG-06 |
| `zpd.rating` | usage | rating (too_easy/appropriate/too_hard), checks_since_last | PKG-06 |
| `learn.check_items_failed` | error | document_id, course_id, reason (A8) | PKG-04 |
| `learn.probe_done` | usage | items, misses, novice_floor, skills | PKG-08 |
| `learn.plan_approved` | usage | concept_ids, n_reviews_first | PKG-08 |
| `learn.session_closed` | usage | session_id, concepts, misconceptions, has_if_then, model_written (A8) | PKG-09 |
| `review.served` | usage | kind (flashcard/check), n, budget_min, retention_target | PKG-12 |
| `review.graded` | usage | kind, correct, rating | PKG-12 |
| `ai.budget_capped` | usage | user_id, scope (daily_usd/monthly_usd/daily_tokens/session_requests/session_deep/daily_grades/rate_limit/platform), band, level (soft/hard/grader_cap), spent_usd, cap_usd | PKG-06b |
| `decision.made` | usage | decision, backend, request_id, latency_ms, confidence, fallback | PKG-05b |
| `decision.shadow` | usage | decision, request_id, primary_value, shadow_value, primary_confidence, shadow_confidence, agreement, shadow_latency_ms, shadow_input_tokens, error_code — never student text | PKG-05b (plumbing; fires from PKG-15) |
| `decision.fallback` | error | decision, from_backend, to_backend, reason (http_401/http_422/http_429/http_529/timeout/circuit_open/low_confidence/jev_absent/both_failed), request_id | PKG-05b |

## 7. Flag and gate (two phases, §13 A14)

**Build phase (PKG-00 through PKG-14 half A; code as built by PKG-00).**
- `config.LEARNING_LOOP_ENABLED = os.getenv("LEARNING_LOOP_ENABLED", "false").strip().lower() == "true"` — unset, empty, or any value other than `true` (any case) → off.
- `learning/gate.py::learning_loop_active(user_id: str) -> bool` = env AND `user_settings.learning_loop_beta`. Env off → `False` with no read. Env on → one `table("user_settings").select(...)` read per call (no per-request cache exists; PKG-07 records the decision); missing row, missing key, or a read error → `False` (fail closed).
- `learning_loop_beta` is a staff/QA toggle, set by SQL or the seed only, and read only by `learning/gate.py` (which fails closed on a missing column or a read error). It is in no settings API field: it is not in `routes/profile.py::_SETTINGS_COLS` or `ALLOWED`, nor in `models.UpdateSettingsBody` or `SettingsResponse`. The settings GET does not return it, and a PATCH carrying it answers 200 and writes nothing (A31; the CodeRabbit PR #673 reopen of PKG-00, commit 2349294, already shipped this). Why: a settings select that names a column whose migration has not been applied yet breaks settings GET/PATCH for every student. No admin route is built in the series, and the toggle is never shown in the student UI.

**After launch (PKG-14 half B).** Exact code:
```python
_raw = os.getenv("LEARNING_LOOP_ENABLED", "").strip().lower()
# Kill switch (spec §13 A14): any falsy spelling turns the loop off; unset or empty means ON.
LEARNING_LOOP_ENABLED = _raw not in {"false", "0", "off", "no"}
```
- Unset → ON; `""` → ON; `true`/`1`/`yes`/anything else → ON; `false`/`FALSE`/`0`/`off`/`no` (any case, surrounding whitespace ignored) → OFF.
- `learning_loop_active(user_id)` keeps its signature, returns `config.LEARNING_LOOP_ENABLED`, reads no `user_settings`, and no longer imports `table`. `learning_loop_beta` is retired: the column stays (dead; the cutover ADR says so), and nothing reads it.

**Evaluation points.**
- Build phase: route entry in `routes/learn.py` (`start_session`, `/start-session/stream`, `/chat`, `/chat/stream`, `/action`, `end_session`) delegating to `routes/learn_loop.py` when true; `routes/quiz.py::submit_quiz`, `routes/flashcards.py::rate_card`/`get_flashcards` (PKG-11 — build phase only); every `/api/learn/loop/*` route; the Learn and Study screens via `GET /api/learn/loop/status`. Never inside `services/chat_stream.py` (invariant 15).
- After launch: the quiz and flashcard gate branches are removed (evidence-only for everyone). The `routes/learn.py` delegation lines and the `/api/learn/loop/*` 404 stay and read the env-only gate — they are the kill switch (§11.6).
- PKG-04's ingest-time item hook is gated on `config.LEARNING_LOOP_ENABLED` (course level: items are course assets), not on the per-user gate. On any environment where the env flag is on, every upload drafts items.
- The class summary (A35, a PKG-03 reopen): `services/course_context_service.py::update_course_context` branches on `config.LEARNING_LOOP_ENABLED` (class level: `offering_summary` belongs to an offering, and a class mixes students on and off the loop), not on the per-user gate. On any environment where the env flag is on, the next refresh of every offering writes the class numbers and clears `summary_text` and `summary_hash`, including in classes with no student in the beta. Nothing reads the prose. The branch stays after launch: when the kill switch turns the flag off, the first refresh of each offering writes the prose once.
- `/api/learn/loop/*` returns 404 `{"detail": "learning loop not enabled"}` when the gate is false.

**Deps and tools.**
- `SaplingDeps.learning_loop: bool = False`, `SaplingDeps.loop_state: Any = None`, `SaplingDeps.pending_evidence: list = field(default_factory=list)`.
- `chat_tutor._build_tools(learning_loop: bool = False)`: `True` → exactly `search_course_materials` and `read_graph_neighborhood`, declared in every phase (A18); no `graded_check_tool` (evidence comes only from the explicit-submission route, A16), no `update_mastery_tool`, no `apply_graph_update_tool`, no `read_session_history_tool` / `read_user_progress_tool` / `read_concepts_for_user`. `False` → today's seven tools, byte-identical, until PKG-14b drops `update_mastery_tool` from the legacy set.

**Values per environment** (owner-set; no package writes the value into `.env.example`, docker-compose, or a deployed config):

| env | build phase | launch and after |
|---|---|---|
| local | `true` while working on the loop; the E2E lane exports `true` from PKG-13 until PKG-14b | unset (ON); `false` only for the kill-switch lane |
| staging | unset before PKG-07; `true` from PKG-07 onward, with `learning_loop_beta` set by SQL on staff/QA accounts only (every other staging account stays on the legacy UI). While `true`, every staging upload drafts check items (the hook is env-gated), and the next class-summary refresh of every staging offering clears its prose, beta accounts or not (A35; nothing reads it) — both expected | `true` or unset (ON) once half B merges |
| production | UNSET (build-phase default: off). Before the half B PR merges, the owner pins `LEARNING_LOOP_ENABLED=false` so an unrelated `make promote` cannot launch | the §11.7 runbook deletes the variable (or sets `true`) after the production backfill |

## 8. Invariants (asserted in `backend/tests/test_learning_loop_invariants.py`)

1. No write to `graph_nodes`, `graph_edges`, `node_mastery_events`, `learner_state` outside `services/graph_service.py::apply_graph_update` (source grep over `backend/` for `table("graph_nodes")`/`.upsert(`/`.update(`/`.insert(` co-occurrence outside that function; `learner_state.write_state` is only called from `apply_graph_update`; `learner_state.write_metrics` only from `scripts/derive_zpd_metrics.py`, PKG-14).
2. `learning/bkt.py`, `fsrs.py`, `policy.py`, `gates.py`, `ladder.py`, `leak.py`, `probe.py`, `planner.py` import nothing from `agents`, `pydantic_ai`, `google`, `db`. `ladder.deterministic_content` receives resolved, visibility-filtered, decrypted passage text as an argument (A17).
3. Every channel satisfies `G + S < 1`, `G ≤ BKT_G_MAX`, `S ≤ BKT_S_MAX`, `0 < BKT_T < 1 − S/(1−G)`.
4. `policy.ceiling`, `policy.band_control`, `policy.model_tier` and `policy.context_policy` take no `str` parameter (phase, band and level are `Literal`/enum-typed state); `policy.py` imports neither `re` nor `gates`.
5. Every `zpd.*`, `learn.*`, `review.*`, `ai.*`, `decision.*` literal in `backend/` (grep, excluding tests) is in `EVENT_TAXONOMY`.
6. Every series `AgentTask` literal (`check_items`, `grader`, `grader_second`, `decision`, `loop_tutor`, `loop_tutor_lite`, `loop_tutor_deep`, `session_close`) has a handler registered in `agents/function_handlers_e2e.py`.
7. Learning tables are accessed only via `db.connection.table()`/`rpc()`.
8. Series migrations match `^\d{14}_learning_[a-z_]+\.sql$`; `git log --diff-filter=M -- backend/db/migrations/*_learning_*.sql` is empty.
9. No `UNIQUE` and no `eq.` filter on `prompt`, `reference_answer`, `rubric_json`, `common_wrong_json`, `options_json`, `correct_option`, `canonical_answer`, `final_answer`, `evidence_text`, `close_json`, `loop_brief`.
10. Any `lru_cache` under `backend/learning/` has a `clear_<name>_cache` function referenced from `tests/conftest.py::_clear_lru_caches`.
11. Two phases (test `test_inv_11_gate_false_when_env_unset`; rewritten in place at PKG-14b, name kept, docstring says the name is historical). Build phase: with `LEARNING_LOOP_ENABLED` unset, `learning_loop_active` returns False for every fixture user and reads no table. After PKG-14b: unset or `""` → True for every user; any of `false`/`0`/`off`/`no` (any case) → False; no table read in either case.
12. Each series agent module (`check_items`, `grader`, `decision`, `loop_tutor`, `session_close`) defines exactly one system prompt and one `Agent(`/`Agent[` (no `_fallback_prompt`); tier and second-opinion slots pick the model per run.

Series-local invariants already named by the prompts (numbers never reused):

| # | test | package |
|---|---|---|
| 13 | `test_inv_13_fsrs_weights_pinned` | PKG-02 |
| 13a | `test_inv_13a_spec_constants_match_function_handlers` | PKG-13 |
| 13b | `test_inv_13b_seed_opts_in_exactly_the_loop_users` (loop seed users only; rewritten at PKG-14b to "no journey depends on `learning_loop_beta`", name kept) | PKG-13 |
| 14 | `test_inv_14_tools_never_write_graph_tables` (covers `agents/tools/check.py::grade_answer`) | PKG-05 |
| 15 | `test_inv_15_gate_never_inside_chat_stream` (the PKG-07 prompt's `test_inv_13_gate_never_inside_chat_stream`, renumbered to avoid the PKG-02 clash) | PKG-07 |
| 16 | `test_inv_16_probe_planner_pure` | PKG-08 |
| 17 | `test_inv_17_rollup_not_a_tutor_tool` | PKG-10 |
| 18 | reserved, unused — never assign | — |
| 19 | `test_inv_19_review_grades_through_grader_only` (through `grade_answer`) | PKG-12 |
| 20 | `test_inv_20_metrics_script_idempotent` | PKG-14a |
| 21 | `test_inv_21_no_legacy_mastery_writers` | PKG-14b |

Cost and decision-seam invariants (§13 A15–A26):

| # | test | assertion | asserted by |
|---|---|---|---|
| 22 | `test_inv_22_loop_routes_ignore_model_pref` | `routes/learn_loop.py` contains no `model_pref` (grep) | PKG-07 |
| 23 | `test_inv_23_ai_budget_checked_before_every_run` | every function that runs an agent on a `grader`, `grader_second`, `decision`, `loop_tutor*` or `session_close` slot (`.run(`/`.run_stream(`/`.iter(` on those agents, or `stream_agent_turn` with the loop agent) calls `ai_budget.check(` earlier in the same function body (AST scan) | PKG-06b (grader, decision sites); PKG-07 extends (loop_tutor slots); PKG-09 extends (session_close) |
| 24 | `test_inv_24_typesafe_only_in_jev` | no Python file under `backend/` (excluding `venv/`, `tests/`) other than `agents/_jev.py` imports `typesafe`; when `_jev.py` exists its client is built only under `model_mode() == "real"` and `JEV_ENABLED` | PKG-05b (vacuous until PKG-15); PKG-15 extends |
| 25 | `test_inv_25_decision_states_carry_no_identifiers` | no State model in `services/decisions.py` has a field named `user_id`, `email`, `name`, `first_name` or `last_name` | PKG-05b |
| 26 | `test_inv_26_evidence_only_from_explicit_submission` | in `routes/learn_loop.py`, `flush_pending`/`apply_graph_update` are called only from the explicit-submission handlers (check answer, probe answer, review answer, post-test answer — AST allow-list); plus the route test: a message typed during the check phase, or an `[ACTION: …]` turn, writes no evidence | PKG-07 (PKG-08/12/14 add their handler to the allow-list) |
| 27 | `test_inv_27_deterministic_payloads_leak_checked` | every payload returned by `ladder.deterministic_content` passes `leak.detect_leak(active_reference, payload, rung, final_answer=active_final_answer, canonical_answer=active_canonical_answer)` in the same function before it is emitted (AST: the call passes `final_answer=`; A34), plus a route test with a leaking H2 passage | PKG-07 |
| 28 | `test_inv_28_symmetric_missingness` | with the grader unavailable (outage) or capped (`STUDENT_DAILY_GRADES`), `grade_answer` on a correct and on a wrong `mc_reason` attempt — and on a matching and a clearly mismatching answer to a `canonical_verified` numeric item — appends zero evidence in every case (behavioural; grader monkeypatched; no DB) | PKG-05 (outage); PKG-06b extends (cap) |
| 29 | `test_inv_29_source_chunks_visibility_aware` | `source_chunk_ids` are resolved only through `rag_service.chunks_for_ids(ids, user_id=...)`: no other module under `backend/` (excluding tests and the check-item writer) reads `course_chunks` by those ids (source scan) | PKG-07 |

Extensions of earlier invariants by these amendments: 5 (`ai.*`, `decision.*`), 6 (the four new slots), 9 (`options_json`, `correct_option`, `canonical_answer` by PKG-04; `final_answer` by PKG-06's reopen of PKG-04, A34; `loop_brief` by PKG-09), 2 (`ladder.deterministic_content` takes passages as an argument; PKG-06).

## 9. Session phases (loop path)

`probe` (PKG-08) → `plan` (PKG-08, student approves; the learner brief is built and stored here, A19) → per concept: `teach` (PKG-07) ⇄ `check` (PKG-07 poses the item from a template, A17; the student answers through the explicit-submission route, A16) → `feedback` (PKG-07; ONE turn with the verdict in the phase prefix) → `close` (PKG-09). `sessions.close_phase` records where the session stopped. A session row may not exist until the first loop write (lazy); every loop write goes through the insert-if-missing helper (A11) — never `upsert` on `sessions`.

**Item activation and the current concept (A27; owner PKG-07, fed by PKG-08, re-ask by PKG-10).** `loop_state["plan"] = {"approved": [node ids], "cursor": int}` and `loop_state["concept"]` (the node id of `approved[cursor]`) are set by PKG-08 at `/plan/approve` (cursor 0, `teach_turns` 0, `concept_checks` 0). PKG-07's `routes/learn_loop.py::_activate_next_item(user_id, course_id, state, *, now) -> str | None` is the only code that SETS `loop_state["active"]` (feedback and withdrawal only clear it): for `state["concept"]` it resolves the concept key (A2), reads `list_items(course_id, concept_key)`, drops the concept's `posttest_reserve_hash`, and calls `checks.select_item(items, format=…, difficulty=LOOP_CHECK_DIFFICULTY_BY_BAND[band], exclude_hashes = seen_hashes(user_id) ∪ revealed_hashes(user_id) ∪ <every question_hash already keyed in this loop_state>)` over `CHECK_ITEM_FORMATS` (rotated by the concept's checks so far) (PKG-10 first tries `policy.next_isomorph` after an `unknown` verdict, inside the same exclusion set); a hit sets `state["active"] = qh` and `state[qh] = {rung: 0, attempts: 0, wrong: 0, first_shown_at: now, check_item_id, node_id: state["concept"], feedback_given: false, taught: bool(state["teach_turns"] or state["concept_checks"])}` (`taught` is the H6 predicate, §3.3, A32); no servable item for the concept advances the cursor (next approved concept, counters reset) and tries again; an exhausted plan sets `state["plan"]["done"] = true` and returns `None` (the UI offers the close). Triggers: (1) the `complete` of a served teach turn that brings `state["teach_turns"]` to `LOOP_TEACH_TURNS_BEFORE_CHECK`; (2) `POST /check/next` ("Check me", no model call). Either way the check pose (`ladder.check_pose`, tier `none`) is saved as an assistant message and returned as `check: {question_hash, format, difficulty, prompt, options}` (JSON key; SSE `check` event before `done`). After a feedback turn: `concept_checks += 1`, `teach_turns = 0`; the cursor advances once `concept_checks ≥ LOOP_CHECKS_PER_CONCEPT`. Without a plan (`state["concept"]` absent: before `/plan/approve`, or a course with no check items) nothing is activated — teaching only. The band, ceiling and budget band of every teach, hint, check and feedback turn come from the active item's node, else from `state["concept"]`, else `BKT_L0` (openers only).

Stream events added to `services/agent_events.py::SaplingEventType` (PKG-07): `phase` (data: {phase}), `check` (data: {question_hash, format, difficulty}), `hint_offer` (data: {rung}), `learner_state` (data: {node_id, p_known, band}), `budget` (data: {level, reset_at}; A20/A26).

Loop routes (`/api/learn/loop`; every one `require_self` + gate → 404 when false; the A20 rate limit applies to every route that can run a model — as a dependency, or inline (`ai_budget.enforce_rate_limit_for`) where only some bodies run one: `/review/answer` checks it for `kind="check"` only, so a self-rated flashcard is never rate-limited — and never to `GET /status` or `GET /sessions`, whose failure would drop the UI to the legacy screen):

| route | owner |
|---|---|
| `GET /status` | PKG-07 |
| `POST /start-session`, `/start-session/stream`, `/chat`, `/chat/stream`, `/action`, `/step/attempt`, `/hint` | PKG-07 |
| `POST /check/answer` (JSON) and `/check/answer/stream` (SSE): the ONLY loop-chat evidence path (A16) | PKG-07 |
| `POST /check/next` ("Check me": activates the current concept's next item and returns its pose; no model call, A27) | PKG-07 |
| `POST /probe/next`, `/probe/answer`; `GET /plan`; `POST /plan/approve` | PKG-08 |
| `POST /close` | PKG-09 |
| `GET /review/next`, `POST /review/answer`, `GET /review/summary` | PKG-12 |
| `GET /sessions` (open loop sessions, for resume; A26) | PKG-13 |
| `POST /rating`, `/posttest/start`, `/posttest/answer` | PKG-14a |

## 10. Evaluation ladder (PKG-11..14)

Rung 1 offline: `tests/evals/grader.py` (leakage: output never contains reference text; rubric agreement vs gold ≥ baseline; logs confidence vs gold agreement so `GRADER_LOW_CONFIDENCE` can be calibrated), `tests/evals/loop_tutor.py` (answer-leak fixtures, "student insists on a wrong claim" sycophancy fixtures, ceiling compliance, feedback-never-ends-in-answer, ≤ `STEP_MAX_SENTENCES`, one question) run **per tier slot** — each of `loop_tutor_lite`, `loop_tutor`, `loop_tutor_deep` must pass every evaluator before `policy.model_tier` may route to it (A15), `tests/evals/decisions.py` (PKG-05b: gold loaders — synthetic or consented de-identified only — and every §3.6 gate as a check). Rung 2 online: A/B on unassisted next-opportunity success and first-attempt correctness at next review (`scripts/derive_zpd_metrics.py`; `user_settings.loop_arm` for within-student concept randomization; arms may compare tier policies, e.g. standard vs deep for develop-band teach; arm sessions are exempt from tier downgrades and pause at the hard cap; analysis is intention-to-treat plus the tier actually served (`zpd.step.tier`) with a cap-hit covariate). `derive_zpd_metrics.py` also reports cost per session and per band, tier mix, cap hits and the `grader_backend` mix. Rung 3: tool-removed post-test endpoint (`learn_loop.py::posttest`, ceiling H0, no RAG, no brief; grades through `grade_answer`; serves the concept's post-test reserve item, excluding seen and revealed hashes, A23). Rung 4: delayed proctored retention (out of series scope; the log fields make it possible).

KPIs: share of steps with rolling unassisted success inside the phase band; `htc_k` trend per concept (must fall); unassisted next-opportunity success on the following session's first item. Gates (not KPIs): 0 solution reveals, ≤ 5% earnest-revise, ≥ 95% ceiling compliance.

## 11. Cutover = launch (PKG-14 half B)

Half B is the launch: the loop becomes the default for every student with no opt-in (§13 A14). It starts only after the launch gate (§11.1) passes, and the owner runs the rollout (§11.7).

### 11.1 Launch gate (PKG-14's half B STOP gate)

All of the following; the session asks the owner to confirm each item that git cannot show:
1. Half A merged; `LEDGER.md` row 14 reads `done (half A)`; the latest row of each of 00–13, 05b, 06b is `done`, `verified` or `reopened` (README "Ledger reading").
2. CI green on `main`, including every test in `frontend/e2e/learn-loop.spec.ts` (loop journey, resume, budget cap) and `python -m e2e_oracles`; the no-check-items state is covered by PKG-13's vitest and PKG-08's route test.
3. Staging has check items for the smoke course, then the staging smoke passes. Uploads made before staging's flag went `true` (§7 table: from PKG-07) drafted no items — the ingest hook runs only on uploads — so the owner first runs the staging backfill: `cd backend && dotenv -f .env.staging run -- env LEARNING_LOOP_ENABLED=true venv/bin/python scripts/backfill_check_items.py --all-courses --project <staging ref> --dry-run` (the printed `Project:` line is the staging ref), then the same without `--dry-run`; the smoke course prints `coverage <course_id> N/M` with N > 0. Smoke under the build-phase config (env `true`; a staff/QA account with `learning_loop_beta` set by SQL): probe → plan → teach → check (the pose appears and `/check/answer` grades it) → close completes.
3b. Kill-switch mechanics drilled on staging: the owner sets staging `LEARNING_LOOP_ENABLED=false` and redeploys → `/api/learn/loop/status` 404, `/learn` shows `tutor-topic-picker`, `/study` hides `review-due-panel`, an upload drafts no `check_items` rows; then restores the value, redeploys, and `/status` is active again. (This proves the switch works as a redeployed env change on the real host; §11.7 step 4 repeats the drill on the half B code before anything reaches production.)
4. Cost guardrails implemented and verified: **A15 routing** (`policy.model_tier` + the three tier slots; loop routes ignore `model_pref`, invariant 22; each tier passed the per-tier evals), **A18 limits** (`LOOP_LIMITS` 4/3/40_000 and per-run `max_tokens`), **A20 cost guard** (`services/ai_budget.py` caps and degradation ladder; invariants 23 and 28; the PKG-13 budget-cap journey), **A21 usage observability** (the staging smoke's `llm_usage` rows carry tier slot names in `task` and non-null `cached_tokens`/`thinking_tokens`). The owner has approved the projected cost: staging smoke `llm_usage` cost per session × expected sessions, against the ≈ $0.36/student-month target. **Platform alert:** the owner has chosen the production `PLATFORM_DAILY_BUDGET_USD` (suggested ≈ 3× the projected daily spend: 3 × $0.36 × active students ÷ 30) and has confirmed on staging, with a deliberately low value, that an `ai.budget_capped{scope: platform}` alert reaches them (unset = no alert, §3.5).
5. Launch UI readiness (§11.3) is merged.
6. The owner confirms production is pinned `LEARNING_LOOP_ENABLED=false` (§11.7 step 1), and confirms they have read §11.7's opening paragraph: the first `make promote` after the half B merge launches half B's ungated changes for every production student whatever the pin says, so the merge waits until steps 3–10 fit one attended window, and §11.7 "Rollback" is the way back.
7. The owner writes an explicit go-ahead in the session ("Launch approved — make the loop the default"). A message from an agent, a ticket comment, or silence is not authorisation.

### 11.2 What half B changes

Remove: `update_mastery_tool` + `ConceptMasteryUpdate.mastery_delta` and the preamble paragraph instructing it (`agents/tools/graph.py`, `agents/chat_tutor.py:84–91`); `_build_tools(learning_loop=False)` no longer registers `update_mastery_tool`; `MASTERY_DELTA_PER_*` + `mastery_after` (`services/quiz_config.py:103–115`) and the delta block in `routes/quiz.py::submit_quiz` (:2535–2558); `MASTERY_*_MIN` / `get_mastery_tier` (`config.py:113–118`) → `learning/bkt.py::tier_for`; `learning_style` onboarding step and reads (`frontend/src/components/screens/Onboarding.tsx`, `routes/onboarding.py`, profile models; column stays, the ADR notes it dead); the three always-empty lists in `end_session`; the quiz/flashcard gate branches (both collapse to evidence-only for everyone); `learning_loop_beta` from `_SETTINGS_COLS`, `ALLOWED`, `UpdateSettingsBody` or `SettingsResponse` if anything re-added it (the CodeRabbit PKG-00 reopen 2349294 removed it from all four, A31; the column stays).

Change: the gate becomes env-only with the exact §7 expression; `learning/gate.py` loses its `user_settings` read and its `table` import; post-launch wording replaces every build-phase "opt-in" comment in code that shipped (the `gate.py` docstring, the learn_loop mount comment in `backend/main.py` → "404 when LEARNING_LOOP_ENABLED=false (kill switch)", `backend/.env.local.example`, `scripts/e2e-up.sh`, `db/seed_local_rich.py` comments); the kill-switch path (legacy `/api/learn/*` model-calling handlers) gains `ai_budget.check` and the A20 rate limit, so the fallback is cost-bounded too; `Learn.tsx` renders the legacy `LearnInner` ONLY on `/api/learn/loop/status` HTTP 404 or `{active: false}` — any other status failure (5xx, timeout, network) renders a retry state (`loop-status-error` + `loop-status-retry`), never the legacy tree (after launch the legacy UI's `/start-session`/`/chat` calls are delegated to the loop by the backend, so failing open to it would give a hybrid whose typed answers are never graded and whose smart/fast toggle is ignored).

Keep (the kill switch): the `routes/learn.py` delegation lines and the `/api/learn/loop/*` 404, reading the env-only gate; the legacy `chat_tutor` agents (`socratic_agent`/`expository_agent`/`teachback_agent`), their mode prompts, the `chat_tutor` AgentTask, `_DEFAULTS` entry and `E2E_TUTOR_REPLY` handler. The mode prompts fold into `loop_tutor.py` only in the follow-up ticket that deletes `LEARNING_LOOP_ENABLED` — not in PKG-14b. `loop_tutor.py` is unchanged by half B.

Update in the same commits: `tests/test_quiz_scoring_e.py`; `frontend/e2e/quiz.spec.ts` and `support/quiz.ts` (+0.09 → the evidence-derived BKT posterior from the function-mode constants); `frontend/e2e/quiz-integration.spec.ts:50,130` (flat `3 * 0.03` → the same BKT expectation) and `quiz-journeys.spec.ts`; `tests/test_mastery_tier_unification.py` + `Learn.tsx::tierForScore` + `lib/quiz/proposals.ts:17` + `frontend/src/lib/graph/nodeStyle.ts:111–121` and its table test + `frontend/e2e/graph.spec.ts:54–59` `tierFor` (all pinned to `learning.params`); `tests/evals/chat_tutor.py` drops `MASTERY_DELTA_MIN/MAX`, `_mastery_updates`, `MasteryUpdateEmittedEvaluator` and the stub's `mastery_delta` handling (`NoToolMisuseEvaluator` keeps banning `update_mastery_tool`; no evidence evaluator — the legacy tutor records no evidence), and the `chat_tutor` cassettes are re-recorded against the edited preamble; PKG-13's `test_inv_13b` (rewritten, name kept) and `test_legacy_users_are_not_opted_in` (retired under the deleted-test naming rule); the `learn-loop.spec.ts` legacy-user test becomes "every student gets the loop by default" plus "kill switch restores the legacy Learn screen" (skipped unless `killSwitchLane`, §11.4); PKG-13's seed and `scripts/e2e-up.sh` comments. No E2E user is opted in by half B — the gate never reads the column.

Record in the cutover ADR (`docs/decisions/<next>-learning-loop-cutover.md`; 0028 expected, PKG-05b's decision-seam ADR takes 0027): the evidence-only rule, the default-on decision (A14), `learning_loop_beta` as a build-phase staff/QA toggle retired at half B, `user_settings.learning_loop_beta` and `user_profiles.learning_style` left dead, the applied PKG-00 migration header describes the build phase, and what the kill switch does not restore (§11.6). Half B's hand-off Known gaps list both dead columns and the env-var removal ticket.

### 11.3 Launch UI readiness (built by PKG-13; required by §11.1)

- `LoopLearn` lists the student's open loop sessions for the course (`GET /api/learn/loop/sessions`: `loop_state` non-empty, `close_json` null, `ended_at` null; newest first) and resumes the newest one — phase from `loop_state`/`close_phase`, messages through the existing session-messages route. A probe starts only when the student has no open loop session for that course or chooses "New session". A reload of `/learn` mid-session never starts a probe.
- A `/learn?resume=<id>` whose id is NOT an open loop session (after launch the Dashboard "Where you left off" cards and the Tree resume links still list pre-launch LEGACY sessions) opens that session read-only in `LoopLearn` through the existing `GET /api/learn/sessions/{id}/resume`, with a "Start a new session" button (`loop-readonly-transcript`, `loop-readonly-new-session`). It never falls through to a new session or a probe on its own.
- `LoopLearn` keeps the knowledge-map rail (or a `/tree` link where the rail does not fit).
- `DueQueue.tsx` (PKG-12) is the launch Study surface; PKG-13 owns its launch polish (budget pause banner, "All caught up", testids). PKG-12's "PKG-13 replaces this" sentence is deleted.
- Empty state when the course has no check items (`no_check_items: true` from `/probe/next`, A23): "No check items for this course yet"; teaching still works, no evidence is written.
- No model toggle and no `model_pref`; the budget pause banner (A26).
- vitest: `Learn()` renders `LoopLearn` for `/status` → `{active: true}`, with `/status` as its only input (no settings field carries `learning_loop_beta`, A31); a reload mid-session calls no probe route; a `?resume=` id that is not an open loop session renders read-only and calls no `/start-session` or `/probe/*`.

### 11.4 E2E after launch

Two lanes under ONE stack-lock invocation, run back to back; each exports the value in the same shell for the stack and Playwright:
- **One lane parse, one source.** `frontend/e2e/support/fixtures.ts` exports `killSwitchLane = ["false", "0", "off", "no"].includes((process.env.LEARNING_LOOP_ENABLED ?? "").trim().toLowerCase())` — the §7 post-launch parse — and every lane guard uses it (`test.skip(!killSwitchLane, "legacy path: kill-switch lane only")` / `test.skip(killSwitchLane, "loop path: default lane only")`), never a raw string compare. `scripts/e2e-up.sh` fails fast when `backend/.env` contains a `LEARNING_LOOP_ENABLED=` line (`load_dotenv()` would fill an unset variable from it for the backend while Playwright sees it unset, so the lanes would disagree); `frontend/e2e/global-setup.ts` asserts `GET /api/learn/loop/status` for the default fixture user matches the lane (kill-switch lane → 404; default lane → `{active: true}`).
- **Default lane:** `make e2e-up` with no `LEARNING_LOOP_ENABLED` at all — half B removes the explicit `true` export from `scripts/e2e-up.sh`, `.github/workflows/e2e.yml` and `scripts/explore.sh`, so the code default is what runs. Every journey not marked legacy-only passes (every `learn-loop.spec.ts` test except the kill-switch one, `quiz`, `quiz-integration`, `quiz-journeys`, `onboarding` without the learning-style step, `study-room`, `study-recent-guides`, `study-semester`, every `gallery-shots` recipe except the `/learn` one); oracles exit 0. AskPanel (the quiz "Ask about this" sheet) calls `/api/learn/start-session/stream`, which delegates to the loop opener: in this lane it shows the loop opener reply (`E2E_LOOP_TUTOR_REPLY`), and `quiz-journeys.spec.ts` asserts that. `study-semester.spec.ts` also asserts that `review-due-panel` and the semester flashcard deck coexist on `/study?mode=cards` (PKG-12 renders the DueQueue above the legacy filter bar).
- **Kill-switch lane:** `LEARNING_LOOP_ENABLED=false make e2e-up`. Legacy-only tests are exactly those that need the legacy Learn screen — `tutor.spec.ts`, `streaming.spec.ts`, the single `/learn` recipe in `gallery-shots.spec.ts` — plus "kill switch restores the legacy Learn screen"; they carry `test.skip(!killSwitchLane, …)`. Everything else in the default lane's list except the loop-only tests runs here too, lane-aware where the lanes differ (AskPanel shows `E2E_TUTOR_REPLY`; `study-semester` asserts `review-due-panel` is absent); oracles exit 0. The quiz has no legacy path after half B, so its expectations are the same in both lanes.
- CI: `.github/workflows/e2e.yml` runs both lanes (matrix: `default` sets no variable; `kill-switch` sets `"false"`).

### 11.5 Hermetic suite after launch

- Every backend test module that exercises code gated by `config.LEARNING_LOOP_ENABLED` (directly, or through `learning_loop_active`) without pinning the flag itself runs as an explicit kill-switch test: it declares `pytestmark = pytest.mark.kill_switch`, and an autouse fixture in `tests/conftest.py` monkeypatches `config.LEARNING_LOOP_ENABLED = False` for marked tests (marker registered in the pytest config). That is the legacy `/api/learn/*` modules (`tests/test_learn_routes.py`, `test_learn_stream_routes.py`, `test_event_capture_seams.py`, `test_xp_wiring.py`, `test_achievement_dispatch.py`, `test_graph_context_block.py`, plus any other non-loop hit of `grep -ln '/api/learn/' backend/tests`) AND the upload-route module `tests/test_documents_routes.py`: under the default, PKG-04's upload hook schedules `_index_then_check_items` instead of `index_document`, so `tasks["index_document"]` (`:858`) raises `KeyError` and `test_sync_upload_is_indexed` (`:468–476`) runs the real `generate_for_document` in the TestClient background task. Find the rest with `grep -rln "LEARNING_LOOP_ENABLED\|learning_loop_active" backend/routes backend/services` → every test module that drives those files without patching the flag. (Alternative per module, recorded in the hand-off: keep it unmarked and update its assertions to the default — e.g. expect the `index_then_check_items` post-roll and patch `routes.documents.generate_for_document`.)
- `tests/test_learning_gate.py`: every env-on test becomes "env on → True for any row state, no `table()` call"; `test_read_error_fails_closed` is removed under the deleted-test naming rule (there is no read); env-off tests keep the no-read assertion; `test_env_flag_defaults_on` is parametrized over `(None, True), ("", True), ("true", True), ("1", True), ("false", False), ("FALSE", False), ("0", False), ("off", False), ("no", False)`. Every reload of `config`/`learning.gate` in a test (these, and `test_inv_11`) goes through PKG-00's `reload_gate(monkeypatch, raw)` helper (`tests/test_learning_loop_invariants.py`), never a bare `importlib.reload`: `config.py` calls `load_dotenv()` at import, so a bare reload refills a deleted variable from `backend/.env`, and the recomputed flag would leak into every later module.

### 11.6 What the kill switch does after launch

`LEARNING_LOOP_ENABLED=false` plus a redeploy returns every student to the pre-loop Learn screen, the legacy `chat_tutor` agents (without the mastery tool) and the legacy Study flashcards UI, and 404s `/api/learn/loop/*`. It does NOT restore quiz/flashcard mastery deltas or the 0.1/0.45/0.75 tier cuts (no legacy path exists after half B), and on that path the tutor records no mastery at all. Undoing those takes a revert of the half B merge plus `make promote` (§11.7 Rollback). The cutover ADR says so.

### 11.7 Launch runbook (owner-run; PKG-14 writes it into HANDOFF-14 as Task B9 and stops)

Merging half B to `main` launches STAGING (`main` = staging). The first `make promote` after that merge — step 6 below, or ANY unrelated promote — carries half B to production. The production pin (`LEARNING_LOOP_ENABLED=false`) turns off only what the gate controls: the loop UI and the `/api/learn/loop/*` routes. It does NOT hold back half B's ungated changes, which reach every production student with that promote: quiz and flashcards become evidence-only (no per-item mastery deltas), the tier cuts become 0.10/0.30/0.95 on every graph and Learn screen, the legacy tutor — the only tutor while pinned — records no mastery, the learning-style onboarding step disappears, and the legacy tutor routes gain the budget check and rate limit. The kill switch cannot undo those (§11.6); only the Rollback below can. Therefore: merge half B only when steps 3–10 can run in one owner-attended window, and run NO unrelated `make promote` between the half B merge and step 8.
1. **Pin production off; set the platform alert.** Before the half B PR merges, the owner sets `LEARNING_LOOP_ENABLED=false` on the production host and the production `PLATFORM_DAILY_BUDGET_USD` chosen at §11.1 item 4, and confirms both in the session.
2. **Merge half B** (only inside the window above). Staging now runs the loop for everyone (staging env `true` or unset).
3. **Staging backfill, then staging smoke.** Re-run the §11.1 item 3 staging backfill (dry run first; the `Project:` line is the staging ref; idempotent — covers uploads since). Then, on an account with NO `learning_loop_beta` and pre-existing legacy sessions and graph: `/api/learn/loop/status` → `{"active": true}`; `/learn` shows `loop-phase`; probe → plan → teach → check (the pose appears; `/check/answer` grades) → close completes; clicking a pre-launch "Where you left off" card on the Dashboard shows its transcript read-only (`loop-readonly-transcript`) with no `/probe/*` call; `/study` shows the DueQueue panel; the session's `llm_usage` rows carry tier slot names and token columns.
4. **Kill-switch drill on staging — go/no-go before any production step.** Set staging `LEARNING_LOOP_ENABLED=false` and redeploy → `/api/learn/loop/status` 404; `/learn` shows `tutor-topic-picker` and one legacy tutor turn completes; `/study` hides `review-due-panel`; an upload drafts no `check_items` rows. Remove the override, redeploy, `/status` active again. Any failure → STOP: no promote; fix forward on `main` or take the Rollback.
5. **Abort criteria agreed.** The owner writes them into the session before step 6 (defaults below, under Rollback).
6. **`make promote`** (still pinned). Production now runs half B code with the loop off — and half B's ungated changes are live for every production student (intro). The abort-criteria watch starts now. Production gets PKG-04's `check_items` migration only here, so the production backfill must follow this step.
7. **Production check-items backfill.** First confirm, by name only (never print values), that the production env file the promotion runbook uses (`.env.production`) defines `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `ENCRYPTION_KEY`, `GEMINI_API_KEY` and `SAPLING_MODEL_MODE=real` — the script fills anything missing from `.env.staging` and `backend/.env`, which would encrypt with the wrong key or write to the wrong project. Then `cd backend && dotenv -f .env.production run -- env LEARNING_LOOP_ENABLED=true venv/bin/python scripts/backfill_check_items.py --all-courses --project <production ref> --dry-run` and confirm the printed `Project:` line is the production ref (the script refuses to run when `--project` differs from the project `SUPABASE_URL` points at); then the same command without `--dry-run`; the owner reviews the `coverage <course_id> <with_items>/<concepts>` lines (A23).
8. **Unpin:** delete the production variable (or set it to `true`; under the §7 parse an empty value also means ON) and redeploy; `make promote ARGS="--verify-only"`.
9. **Re-run the step-7 backfill** (idempotent; covers uploads made between steps 7 and 8).
10. **Production smoke on a non-staff account:** `/api/learn/loop/status` → `{"active": true}`; one probe item answered; one check posed and graded; one review served; `llm_usage` rows for the tiers used.
11. **Keep coverage complete.** The owner schedules the idempotent `--all-courses` backfill as a recurring production job (nightly, beside `scripts/derive_zpd_metrics.py`; it runs on the flex tier with `user_id=None`, and a covered concept costs nothing). The upload hook drafts at most `CHECK_ITEM_MAX_CONCEPTS_PER_DOC` concepts per upload and nothing else adds items, so without it coverage erodes; PKG-14's metrics REPORT prints per-course coverage so erosion is visible.
12. Append `Launched: <date>` to the cutover ADR.

**Rollback (the owner decides; the session never does).**
- Abort criteria (defaults; the owner may tighten them at step 5), watched for 7 days from step 6: the 5xx rate on `/api/learn/*` or `/api/learn/loop/*` above 2× its pre-launch 7-day baseline for 15 minutes; an `ai.budget_capped{scope: platform}` alert; measured `llm_usage` cost per active student-day above 2× the target (the target is $0.36/student-month ≈ $0.012/day) for a full UTC day; any `zpd.leak` event or an e2e-oracle data-integrity finding on production data.
- Loop only (after step 8): `LEARNING_LOOP_ENABLED=false` + redeploy — the kill switch (§11.6).
- Everything half B changed (after step 6; this is the only way back from the ungated changes): `git revert -m 1 <half B merge sha>` on `main` (staging), verify staging, then `make promote`. The revert restores the build-phase gate (env AND `learning_loop_beta`), so production is off whatever the variable says. Evidence rows, `learner_state` and the backfilled `check_items` stay (append-only; the legacy path ignores them; `graph_nodes.mastery_score` keeps the BKT values written meanwhile, and legacy deltas resume from them). Half B adds no migration, so none is reverted.

## 12. Do-not-build list

Learning-style routing; a standalone growth-mindset module; deep knowledge tracing or any neural learner model; full Bayesian-network inference over the graph; a Socratic-only mode; an LLM anywhere inside `backend/learning/`; a student-visible model toggle on the loop; explicit context caching (break-even needs ≈ 4 hits per cached token per hour on Pro/Flash, ≈ 11 on Flash-Lite, and pydantic-ai strips `system_instruction`/`tools` with `google_cached_content`); the Batch API (a fifth raw `genai.Client` site; Flex gives the same discount inside pydantic-ai); an embedding pre-screen for grading; a verdict cache; code-issued "correct" verdicts on a strong channel; `symbolic`/`exact` answer kinds; `system-one-adapter-python` in application code (offline benchmark scripts only); any Jev network code before PKG-15; a Java SDK.

## 13. Amendments log (in force; override the prompt files where they disagree)

Recorded 2026-09-26 during the prompt-authoring consistency pass (A1–A13), the default-on decision (A14) and the cost/Jev owner decisions (A15–A26); A27 and the A20/A22/A23 and §11 additions dated 2026-09-27 come from the review of that amendment; A28–A32 (2026-09-27) ratify the CodeRabbit PR #673 review fixes and the docs review that followed them; A34 (2026-09-27) records the series coordinator's structured-final-answer decision (A33 is reserved by a concurrent grader-guard fix on another branch); A35–A36 (2026-09-27) record the fixes for the findings of the live sequence test of PR #673 (real Gemini on the local stack). A prompt that references the older wording follows this section. Each executing session re-reads this section before Task 1. The prompt files of built packages (PKG-00, 01, 02, and PKG-11, which ran early — §14) and of PKG-03 (being built) are never edited; where a row below changes what one of them says, the wording reaches its hand-off as a "Post-hoc changes" line (PKG-11: §14), and a change to their code lands as a reopen commit (`fix(learning-loop): PKG-MM — <what>`) in the later package named in the row.

| id | change | affects |
|---|---|---|
| A1 | `Evidence` has no `"idk"` channel. `channel` is always the item's channel; `idk: bool = False` marks an explicit "I don't know" (observation = incorrect with `S_IDK`, channel's G). `bkt.update(p, channel, correct, *, weight, idk)` matches. | PKG-01, 03, 05, 08 |
| A2 | `check_items` keyed on `(course_id, concept_key)`; no FK to `graph_nodes`; `concept_key = services/graph_service._normalize_concept(concept_name)`; UNIQUE `(course_id, concept_key, question_hash)`; index `(course_id, concept_key, format, difficulty)`. `check_item_service.list_items(course_id, concept_key, ...)`. A student's node → items via `_normalize_concept(graph_nodes.concept_name)`. Items remain course assets shared by every enrolled student. | PKG-04, 05, 08, 12, 13 |
| A3 | `learner_state.max_streak_unassisted int NOT NULL DEFAULT 0`, maintained by `apply_graph_update`; `policy.wheelspin` reads `ever_streak3 = max_streak_unassisted >= 3`. | PKG-03, 06 |
| A4 | Ceiling precedence: `exam_mode` wins over the shown-work floor (exam → H1 always). | PKG-06, 07 |
| A5 | Gates take an injectable clock (`now: float`) and scale every `GATE_*` seconds constant by `config.LEARNING_GATE_TIME_SCALE` (env `LEARNING_GATE_TIME_SCALE`, default `1.0`; the E2E env sets `0.01`). Production never sets it. `params.py` exposes `gate_seconds(name) -> float`. | PKG-06, 13 |
| A6 | New named constants (values chosen by the authoring pass; † where no validated cut-point): `GAP_CONFIDENCE_MAX = 0.4 †` (verdict `gap` when stated confidence ≤ this), `NOVICE_FLOOR_IDK = 2 †`, `PROBE_DIFFICULTY_SHIFT = {1: +0.15, 2: 0.0, 3: −0.15} †`, `RUNG_ASSISTED_MIN = 1`, `RUNG_ASSISTED_MAX = 3`, `RUNG_NO_CREDIT_MIN = 4`, `LADDER_MAX_RUNG = 6`, `GRADER_SECOND_OPINION_CONFIDENCE = 0.4`, `FLASHCARD_RATING_TO_FSRS = {1: 1, 2: 2, 3: 3}`, `REVIEW_SECONDS_PER_FLASHCARD = 15 †`, `CHECK_ITEM_MAX_CHUNKS = 8 †`, `CHECK_ITEM_MAX_CONCEPTS_PER_DOC = 10 †`, `CHECK_ITEM_OUTPUT_RETRIES = 2`, `CLOSE_SUMMARY_MAX_CHARS = 500 †`, `CLOSE_SELF_EVAL_MAX_CHARS = 200 †`, `CLOSE_IF_THEN_MAX_CHARS = 200 †`, `CLOSE_TRANSCRIPT_TURN_MAX_CHARS = 400 †`, `CLOSE_LIMITS = 2/0/20_000`, `HTC_K_WINDOW = 5`, `ZPD_IN_ZONE_MIN_GAP = 0.25`, `ZPD_IN_ZONE_MIN_ASSISTED = 0.6`, `ZPD_IN_ZONE_MAX_UNASSISTED = 0.85`, `POSTTEST_MIN_AGE_DAYS = 2`, `POSTTEST_MAX_ITEMS = 10 †`, `KPI_TREND_WEEKS = 4`, `GATE_INDEPENDENT_MIN_S_VARIANT_B = 90 †`. All live in `learning/params.py`. | PKG-01 owns the file; each package adds its own |
| A7 | Rating map additions: `chat_turn` unassisted-correct → Hard; `retention_target`: exam rule beats large-set rule; never-reviewed rows have R = 1.0. | PKG-02, 12 |
| A8 | Events: add `learn.check_items_failed` (category `error`; payload document_id, course_id, reason enum). `zpd.step.phase` may be `"posttest"`; `zpd.step` payload gains `variant`. `learn.session_closed` payload gains `model_written: bool`. | PKG-04, 09, 14 |
| A9 | Migration `<ts>_learning_sessions_mode_review.sql` widens the `sessions.mode` CHECK to include `'review'` (DDL in §4). | PKG-12 |
| A10 | Quiz evidence is always channel `mc` today: `AnswerItem` carries no reason field. `mc_reasoned` from the quiz waits for a reason tier (post-series). | PKG-11 |
| A11 | `main.py` mounts routers at `:274–299` (CLAUDE.md corrected). Sessions rows are created by the same insert-if-missing helper for `loop_state`, `close_json`, and review sessions; never `upsert` on `sessions`. | PKG-06, 07, 09, 12 |
| A12 | Module map additions: `learning/loop_state_store.py` (PKG-06), `learning/zpd_events.py` (PKG-06), `agents/session_close.py` (PKG-09, task `"session_close"`), `frontend/src/components/learn/loopState.ts` + `DueQueue.tsx` (PKG-12/13). | — |
| A13 | Planner goal filter starts as `None`: no syllabus-week resolver exists. `services/exam_proximity.days_until_next_exam` DOES exist and drives `retention_target` and the brief's goal line. | PKG-08, 09, 12 |
| A14 | **The learning loop is the new default learning system for every student — no opt-in** (owner decision 2026-09-26). <br>• Build phase (PKG-00 … PKG-14a): code stays dark behind `LEARNING_LOOP_ENABLED` (build-phase parse, §7: unset → off; gate = env AND `learning_loop_beta`, no read when env is off) so merged partial packages never reach students. <br>• `user_settings.learning_loop_beta` is a staff/QA toggle, set by SQL or the seed and read only by `learning/gate.py`, which fails closed. It is in no settings API field: not in `_SETTINGS_COLS`, `ALLOWED`, `UpdateSettingsBody` or `SettingsResponse` (A31; the CodeRabbit PR #673 reopen of PKG-00, commit 2349294, shipped this, and PKG-04 Task 0 only verifies it). No admin route in the series; never in the student UI. <br>• Launch (PKG-14 half B, §11): the gate becomes env-only with the exact §7 parse (unset/empty → ON; `false`/`0`/`off`/`no` → OFF), no `user_settings` read; the loop UI is what every student sees on Learn and Study; the legacy tutor (kept, minus the mastery tool) stays reachable only through the kill switch until a follow-up deletes the env var. <br>• Launch gate (§11.1) replaces the old "≥ 2 weeks of beta + written sign-off": all packages verified; CI green including every `learn-loop.spec.ts` test + oracles; a staging smoke run (probe → close); the cost guardrails **A15 routing, A18 limits, A20 cost guard, A21 usage observability** implemented and verified; launch UI readiness (§11.3); production pinned `false`; owner go-ahead. The production check-items backfill (`--all-courses`, A23) is a runbook step (§11.7). <br>• Env values (§7 table): local `true` while working on the loop; staging `true` from PKG-07 onward with `learning_loop_beta` set by SQL on staff/QA accounts only (every staging upload drafts check items while `true`); production UNSET during the build, pinned `false` by the owner before the half B PR merges, unpinned by the §11.7 runbook. | PKG-00 (reopened by the CodeRabbit PR #673 fix 2349294, A31), PKG-04, 07, 11 (built early; wording via a HANDOFF-11 Post-hoc changes line, §14), 12, 13, 14 (half B rewritten), README |
| A15 | **Tutor tier routing in code** (owner decision 2: routed plan, ≈ $0.36/student-month, $355 per 1,000/month no-cache upper bound). <br>• Slots in `agents/_providers.py` (§3.5): `loop_tutor_lite` (2.5-flash-lite), `loop_tutor` (2.5-flash, `thinking_budget = LOOP_FLASH_THINKING_BUDGET`), `loop_tutor_deep` (2.5-pro, `LOOP_PRO_THINKING_BUDGET`); `SAPLING_MODEL_*` overrides apply; each needs a function-mode handler (invariant 6). One `loop_tutor_agent`, one prompt; the slot is chosen per run. <br>• Pure `learning/policy.model_tier(phase, band, rung, failed_genuine_attempts, misconception_active, *, deterministic_payload=False, budget_level="normal", deep_cap_reached=False, novice_deep_cap_reached=False, arm_session=False) -> Tier` (`lite`/`standard`/`deep`/`none`) implements `LOOP_MODEL_TIER` (§3.5) — PKG-06. <br>• Loop routes **ignore `model_pref`** (invariant 22); there is no student-visible model toggle on the loop; `llm_usage.task` carries the slot name; `zpd.step.tier` records the tier served. <br>• A tier is routable only after it passes the per-tier evals (§10). | PKG-06, 07, 13, 14; §3.5, §8, §10 |
| A16 | **Grade in the route, on explicit submissions only.** <br>• The attempt box posts `POST /api/learn/loop/check/answer` (JSON) or `/check/answer/stream` (SSE) with `{session_id, user_id, question_hash, answer \| (option, reason), idk}`. Plain chat messages in the check phase and `[ACTION: …]` turns are never graded (invariant 26). <br>• The route first runs idk detection and `gates.matches_non_attempt`: `idk: true` or an idk phrase → idk evidence (A1) and the answer is released; another non-attempt phrase ("just tell me", "give me the answer", "what's the answer") → no evidence, served as a hint request under the ceiling. The independent-time gate never blocks grading; it only decides whether the attempt counts toward hint unlocking. <br>• Otherwise: `grade_answer(item, answer, deps=...)` → `flush_pending(deps, course_id)` → ONE feedback-phase turn with the verdict in the phase prefix (tier per §3.5). <br>• PKG-05 builds `agents/tools/check.py::grade_answer` — the single grading helper, shared by the check route (PKG-07), probe (PKG-08), review (PKG-12) and post-test (PKG-14). No `graded_check_tool` is built; `_build_tools(learning_loop=True)` registers neither it nor `update_mastery_tool` (§7). PKG-10's slip/misconception hook lives in `grade_answer`. <br>• Test: a question typed during the check phase writes no evidence. | PKG-05, 07, 08, 10, 12, 13, 14; §7, §9 |
| A17 | **Deterministic turns, leak-checked** (owner decision 4). <br>• Check pose = the item prompt verbatim through `ladder.check_pose(prompt)` — no model call (the prompt was leak-checked at generation by `validate_draft`). <br>• H2 = the item's source passage(s), ≤ `LOOP_SOURCE_CHUNKS_MAX`, resolved at serve time through `rag_service.chunks_for_ids(ids, user_id=<requesting user>)` (visibility-aware; invariant 29); chunks no longer visible are dropped; none left → the LLM writes H2. <br>• H6 = the stored reference, only under `gates.h6_allowed`. <br>• H4 = a sibling item with the same `concept_key`, format **and** difficulty and a different `question_hash`, shown with its reference, only when the sibling's stored `stepwise` flag is true †; otherwise the deep tier writes H4. <br>• `ladder.deterministic_content(rung, item, siblings, passages) -> DeterministicPayload \| None` (PKG-06, pure; `passages` is resolved, decrypted text passed in, invariant 2). Every payload passes `leak.detect_leak(active_reference, payload, rung, final_answer=…, canonical_answer=…)` — the active item's structured answer, A34 — before emission (invariant 27); on a leak the turn falls back to the LLM rung (with `strip_leak`); if served anyway the step is recorded as H6 with no upward BKT credit. <br>• A sibling shown as H4 is appended to `sessions.loop_state["revealed"]` (ids only) and excluded from that student's future checks (A23). References are model-generated and unverified; nothing calls them verified. | PKG-04 (`stepwise`), 06, 07 |
| A18 | **Context and tool policy by phase, plus tighter limits.** <br>• Pure `learning/policy.context_policy(phase, *, opener, budget_level) -> ContextPolicy{rag_k, graph_block, source_chunks, catalog, tool_choice}` (PKG-06): teach → RAG `LOOP_RAG_K_TEACH` (`LOOP_RAG_K_TEACH_SOFT` at the soft level) + the graph block; feedback and hint → the item's ≤ `LOOP_SOURCE_CHUNKS_MAX` source chunks, resolved as in A17; check → nothing; catalog on the opener only. <br>• Tools: `read_graph_neighborhood` and `search_course_materials` are declared in **every** phase so the cached prefix is stable; outside teach (and at the soft level) the run passes `ModelSettings(tool_choice='none')` (pydantic-ai 1.107 keeps the declarations and sets Gemini function calling to NONE). `read_session_history_tool`, `read_user_progress_tool`, `read_concepts_for_user` are not on the loop. <br>• PKG-07 assembles loop context from `context_policy` (reusing the legacy block builders) instead of reusing `_prepare_chat_run` verbatim; `model_pref` is never read. <br>• `LOOP_LIMITS = 4/3/40_000 †`; per-run `max_tokens` = slot thinking budget + `LOOP_MAX_VISIBLE_TOKENS`. | PKG-06, 07; §3.4, §3.5 |
| A19 | **Stable prefix.** <br>• The learner brief is built once per session — at `/plan/approve` (PKG-09's post-hoc edit of the PKG-08 handler), or on the first loop turn of a session that has no plan — and stored encrypted in `sessions.loop_brief` (PKG-09 migration; §4 encryption list; invariant 9). `loop_state` stays free of free text. <br>• `_load_loop_history` returns the brief as a synthetic first history message followed by the last `n` messages when `n < LOOP_HISTORY_TRIM_BLOCK`, else the last `LOOP_HISTORY_TRIM_BLOCK + (n mod LOOP_HISTORY_TRIM_BLOCK)` (10–19), so the window start moves in blocks. <br>• The brief can go stale within a session (the current band rides in the phase prefix). The saving over default implicit caching is unmeasured until A21. | PKG-07, 08 (post-hoc), 09; §3.4, §4 |
| A20 | **Cost guard** (owner decision 3: caps accepted as proposed). <br>• `services/ai_budget.py` (PKG-06b, outside `backend/learning/`): the band-aware caps and degradation ladder of §3.5, `check(user_id, kind, band=None, *, session_tutor_requests=0, session_deep_requests=0, arm_session=False) -> BudgetDecision`, `rate_limited(user_id) -> bool`, and a FastAPI dependency for the rate limit. <br>• Every run site of `grader`/`grader_second`/`decision` (wired by PKG-06b as reopens of PKG-05/05b), `loop_tutor*` (PKG-07) and `session_close` (PKG-09) calls `ai_budget.check` first (invariant 23). <br>• Hard level: tutor chat pauses (HTTP 429 `{"detail": "ai budget reached", "reset_at": …}` + stream `budget` event); practice, review and flashcards keep working; novice-band concepts pause (not on a rate-limit-only hard level, §3.5); never evidence for only one outcome (invariant 28). `loop_arm` sessions are exempt from downgrades and pause instead. <br>• Rate limit `LEARN_RATE_LIMIT_PER_MIN` on every model-calling `/api/learn/loop/*` route (PKG-07 attaches the dependency per route; `/review/answer` checks it inline for `kind="check"` only, PKG-12; never on `GET /status` or `GET /sessions`) and, from PKG-14b, on the legacy `/api/learn/*` model-calling handlers (the kill-switch path). <br>• Event `ai.budget_capped` (§6). Platform budget: alert-only (`PLATFORM_*`, §3.5). | PKG-06b, 07, 08, 09, 12, 13, 14 |
| A21 | **Usage observability** (the #639 portion). <br>• Migration `<ts>_learning_llm_usage_tokens.sql` adds `llm_usage.cached_tokens int` and `thinking_tokens int`, filled by `agents/usage.py::record_agent_usage` from the provider usage (`cached_content_token_count`, `thoughts_token_count`). <br>• `services/llm_pricing.py` gains a cached-input rate per model (10% of input: 2.5 Flash-Lite $0.01/M, Flash $0.03/M, Pro $0.125/M); cost = uncached input × input rate + cached × cached rate + output (incl. thinking) × output rate. <br>• Prerequisite for measuring cache hits, A19, the deep-tier thinking average and the thinking caps. | PKG-06b |
| A22 | **Deterministic pre-checks, never a sole "correct" verdict.** <br>• `check_items` gains `options_json`, `correct_option`, `answer_kind` (`free`/`numeric`), `canonical_answer`, `tolerance`, `canonical_verified` (DDL §4, PKG-04); the `check_items` agent outputs options with a `wrong_key` per distractor, `correct_option`, `answer_kind`, `canonical_answer`, `tolerance`, `stepwise`; `canonical_verified` is set only by an independent second-model agreement check (off by default, so the numeric gate forwards everything). Validation: `mc_reason` has exactly 1 correct option and every distractor maps to a listed `wrong_key`; `stepwise` requires ≥ 2 numbered steps in the reference †; `numeric` requires a parseable `canonical_answer`. <br>• Grading (`grade_answer`, PKG-05): `mc_reason` — the option is compared in code and the reason check runs for **both** outcomes; correct = option matches AND reason correct; evidence is written only when the reason check returns, with weight from its confidence for both outcomes; unavailable (cap, outage, second opinion unavailable) → nothing for either outcome. A wrong option carries its option's `wrong_key` only when the reason check matches that key; otherwise `wrong_key=None` (the option → key map is only a prior; PKG-10 records only matched keys). `numeric` — parse-and-compare, applied only after the rubric grader returned (the grader runs for both outcomes, so an outage or the grade cap records nothing for either — invariant 28): a clear mismatch against a `canonical_verified` answer overrides the verdict to incorrect (`grader_backend="deterministic"`); a match, a parse failure or an unverified key keeps the grader's verdict. Code never issues "correct" on a strong channel. <br>• Second opinion on slot `grader_second` (2.5-flash, thinking 0), same prompt. <br>• `Evidence.grader_backend` (§5; PKG-05 reopens PKG-03) + column `node_mastery_events.grader_backend` in PKG-05's migration `<ts>_learning_grader_backend.sql`. <br>• PKG-12 serves the stored `options_json` (never rebuilt from the reference; correctness never marked). <br>• Invariant 9 gains `options_json`, `correct_option`, `canonical_answer`. | PKG-04, 05, 08, 10, 12 |
| A23 | **Check-item economy, privacy, seen/revealed sets.** <br>• Generate only when a `(course_id, concept_key)` has fewer than `CHECK_ITEM_INITIAL_PER_CONCEPT` items; ≤ `CHECK_ITEM_CONCEPTS_PER_CALL` concepts per agent call; `CHECK_ITEM_MAX_CONCEPTS_PER_DOC` still bounds each upload. <br>• Source only from documents with `shareability='course_material'` **and** shared visibility (fixes the leak of `completed_work`/opted-out text into the class pool). Coverage cost: a course with no shared course material gets no items; `check_item_service.course_has_items(course_id)` feeds `/probe/next`'s `no_check_items: true` and the A26 empty state. <br>• Background prefill uses `ModelSettings(service_tier='flex')` with `FLEX_TIMEOUT_S` and retries on 503/429; in-session top-ups run on the standard tier. <br>• The initial set is 9 items per concept (every format × difficulty, teachback included). `checks.posttest_reserve_hash(items)` names one reserve per concept — the lowest `question_hash` among `free` items at `CHECK_ITEM_DIFFICULTIES[1]` (else the lowest hash overall); probe, in-session checks and review never serve it; the post-test serves it. <br>• Seen = every `question_hash` in the user's evidence rows; revealed = evidence rows with `correct=false` or `max_rung >= RUNG_NO_CREDIT_MIN` (the reference was shown) plus `sessions.loop_state["revealed"]` across the user's sessions (H4 siblings, A17) — `loop_state_store.seen_hashes(user_id)` / `revealed_hashes(user_id)` (PKG-07). Post-test and review pass seen ∪ revealed as `exclude_hashes`; review falls back to excluding only revealed hashes when that leaves nothing, and skips the concept (`unservable`) when still empty. <br>• `scripts/backfill_check_items.py --all-courses` (PKG-04): iterates every course with `graph_nodes`, skips a `(course_id, concept_key)` that already has ≥ `CHECK_ITEM_INITIAL_PER_CONCEPT` items before any agent call (each concept drafted once however many students share it; a re-run costs nothing), prints `coverage <course_id> <with_items>/<concepts>`; idempotent. It drafts a concept only when at least one shared course-material passage scores ≥ `CHECK_ITEM_BACKFILL_MIN_CHUNK_SCORE` on `rank_chunks_for_concept` (a concept token appears in it) — a concept from a private note or a tutor chat that no shared passage covers makes no agent call and counts as uncovered, never an off-topic item with an ungrounded reference. It requires `--project <ref>`, prints `Project: <ref>`, and refuses (exit 2) when `<ref>` is not the project `SUPABASE_URL` points at; `--dry-run` prints the plan and makes no agent call and no write. <br>• **Withdrawal (consent is answerable for items too).** `check_items.source_document_ids` records every document whose passages drafted an item. `check_item_service.retire_items_for_documents(document_ids)` DELETES every item citing any of them; it runs when a document is deleted (`routes/documents.py::delete_document`) and, through `retire_items_for_uploader(user_id)`, when a student turns `share_class_context` off (`routes/profile.py`, beside the chunk-visibility resync). Neither call is gated on `LEARNING_LOOP_ENABLED` (withdrawal must hold under the kill switch too). Evidence rows keep their `check_item_id`/`question_hash`; nothing serves a deleted item again. | PKG-04, 07, 08, 12, 13, 14 |
| A24 | **Decision seam now; Jev post-series** (owner decision 5). <br>• PKG-05b builds `services/decisions.py` (typed `Verdict`/`YesNo`/`Pick`; State models with no identifiers, invariant 25) with `gemini`, `function` and `deterministic` backends; `agents/decision.py` (task `"decision"`, one prompt, function handler); `grade_rubric_items` and `reason_is_correct` delegate to the existing `agents/grader.grade()` (no second prompt stack), and `grade_answer` calls through them (reopen of PKG-05); `match_wrong_reason` (PKG-10), `item_answerable` (PKG-04 stub hook, off) and `judge_leak` (additive; may only block) run on the `decision` agent; `classify_upload`/`rerank`/`route_turn` belong to #641/#640 outside the series (State models only here). Events `decision.made`, `decision.shadow`, `decision.fallback`; `zpd.step` gains `tier` and `grader_backend`. The §3.6 settings (incl. promotion gates) are defined; Jev is absent. An ADR (`docs/decisions/<next>-decision-seam.md`, 0027 expected) amends ADR 0024 to admit one non-Gemini model seam. <br>• PKG-15 (post-series, #642): the `jev` backend in `agents/_jev.py` — the only `typesafe` importer (invariant 24), Python `typesafe-sdk==0.7.2` pinned exactly (no Java SDK exists), model `jev-1.13.0`, client built only when `model_mode()=="real"` and `JEV_ENABLED`, a Choice (never a Noul) for every confidence-gated decision, `llm_usage` rows with `provider='typesafe'`, per-decision flags `DECISION_BACKEND_<NAME>` with `JEV_ENABLED=false` as the global kill switch. <br>• Privacy gate before ANY student-derived text reaches Typesafe (live, shadow, historical or eval sets): an enterprise contract with zero data retention, a signed DPA with the subprocessor list reviewed, FERPA "school official" and under-18 terms, a privacy-notice update naming Typesafe, SOC 2 or equivalent, US hosting accepted, data minimisation in code. Until it passes, Jev runs only offline on synthetic or consented de-identified sets. Promotion is per decision against §3.6. | PKG-05, 05b, 06, 06b, 10, 14; PKG-15 |
| A25 | **Session close economy.** No close LLM call when the session has zero evidence rows, or when `ai_budget.check(kind="close")` returns hard: `build_close` runs deterministically and stores `fallback_close` with `model_written=false`. | PKG-09 |
| A26 | **Frontend** (plus launch UI readiness, §11.3). <br>• LoopLearn shows no model toggle and sends no `model_pref`. <br>• The attempt box submits an explicit answer to `/check/answer(/stream)` (A16), never a plain chat message. <br>• It renders the budget-pause banner from the 429 body or the `budget` stream event, and a "no check items for this course yet" state (A23). <br>• Deterministic turns render like any other turn. <br>• Resume and list open sessions (`GET /api/learn/loop/sessions`, PKG-13), knowledge-map rail or `/tree` link, DueQueue polish. <br>• E2E: a budget-cap journey on a dedicated seeded user (`rich-user-capped`, `learning_loop_beta=true` during the build, `llm_usage` rows stamped `now()` summing past the novice allowance) asserts the pause banner on `/learn` and that review still serves and grades on `/study`. A lane-wide low `STUDENT_DAILY_BUDGET_USD` is not used: it would cap every loop journey. | PKG-13, 14 |
| A27 | **Item activation and the current concept** (review fix 2026-09-27: no package made an in-session check item active, so the check phase, `/check/answer`, the template pose and the feedback tiers were unreachable; teach turns had no node, so novice teach never routed to `deep` nor got the novice allowance). <br>• §9 "Item activation and the current concept" is the contract: PKG-08 stores `loop_state["plan"] = {approved, cursor}` and `loop_state["concept"]` at `/plan/approve`; PKG-07 builds `_activate_next_item` (the only code that sets `loop_state["active"]`), the teach → check trigger (`LOOP_TEACH_TURNS_BEFORE_CHECK` †), `POST /check/next`, and the post-feedback advance (`LOOP_CHECKS_PER_CONCEPT` †); PKG-10 puts `next_isomorph` inside `_activate_next_item`; PKG-13 renders the `check` object and a "Check me" control (`loop-check-me`). <br>• Band, ceiling and the `ai_budget.check` band of teach/hint/check/feedback turns come from the active item's node, else `loop_state["concept"]`, else `BKT_L0` (openers). A novice-band concept in teach routes to `deep` (`LOOP_MODEL_TIER`), is budgeted at the novice allowance, and gets the novice ceiling. <br>• Openers never block the probe: at the hard level `/start-session(/stream)` serves the template opener `_LOOP_OPENER_TEMPLATE` (tier `none`, pause notice) instead of a 429 (§3.5 "At the hard level these keep working"). | PKG-07, 08, 10, 13; §3.4, §3.5, §9 |
| A28 | **FSRS-6 reference guards in §3.2** (this ratifies what PKG-02 shipped in review; HANDOFF-02 Open question (4) proposed the text as "A14", a number the default-on decision already holds, so it is recorded here as A28). <br>• Same-day: `S_same_day = S·max(1, SInc)` for Hard/Good/Easy and unfloored for Again, with `SInc = e^(w17·(G−3+w18))·S^(−w19)`. A same-day pass never lowers S. <br>• Lapse cap: `S_lapse = min(w11·D^(−w12)·((S+1)^w13 − 1)·e^(w14·(1−R)), S / e^(w17·w18))`. A lapse never raises S. <br>• Mean reversion targets the UNCLAMPED `D0raw(4) = w4 − e^(3·w5) + 1 = −4.7716`, and then `D''` is clamped to [1, 10]. <br>• `FSRS_STABILITY_MIN = 0.001` days (`learning/params.py`): every stability after the first rating is floored at it, after the MC cap. <br>• Code: `fsrs.py` a8a83e7, 45b85ca, 6d6cb3b and 93631c9; `params.py` 9cf1919 (a PKG-01 reopen). `next_state` matches py-fsrs 6.3.2 (default weights equal `FSRS_W`) to within 4e-15 relative error. The frozen PKG-02 prompt keeps its pre-guard reference values; HANDOFF-02 and this row are the record. No code change. | PKG-02 (built), 03 and 11 (built; the `same_day` callers), 12; §3.2 |
| A29 | **The class misconception rollup keys on the course concept, not the node.** `graph_nodes` rows are per user (`UNIQUE (user_id, course_id, concept_name)`), so grouping `misconceptions` by `m.node_id` put each student in a separate group and the `MISCONCEPTION_ROLLUP_MIN_USERS` distinct-user floor could never be met. <br>• `misconception_rollup(p_course_id)` joins `graph_nodes` for the course and the concept name and groups by (course, `concept_key`, `wrong_key`). `concept_key` is `lower(btrim(regexp_replace(concept_name, '\s+', ' ', 'g')))`, the SQL mirror of `services/graph_service._normalize_concept`, equal to `check_items.concept_key` (A2). <br>• It returns `(concept_key, wrong_key, users)`, never a node id. `HAVING count(DISTINCT m.user_id) >= 5` is unchanged. <br>• Known gap: SQL `lower()` stands in for `casefold()`. They agree on ASCII names but can differ on some non-ASCII characters (for example `ß`, which `casefold` expands), and such a concept keys differently in SQL and in Python. DDL in §4. | PKG-10; §4 |
| A30 | **`BKT_P_MAX = 0.999 †`** (the CodeRabbit PR #673 fix to PKG-01, commit 09f3a64; ledger `01 \| reopened`; HANDOFF-01 Post-hoc changes). <br>• `bkt.update` caps its result at `BKT_P_MAX` (§3.1 update rule). Without the cap, 15 back-to-back corrects on `free_response` rounded p to exactly 1.0, where the incorrect posterior is 1, so no wrong answer or `idk` could lower the belief again. <br>• The cap keeps belief below 1, so contrary evidence always lowers it, and it sits above `BKT_MASTERED`, so mastery stays reachable: from the cap one wrong `free_response` gives 0.99224 (still mastered), two give 0.94297 (not), and an `idk` gives 0.96258. `BKT_MASTERED < BKT_P_MAX < 1` is pinned by `tests/test_learning_bkt.py`. <br>• The same commit marks `WEIGHT_SAME_SESSION_RECHECK = 0.5` with † (an unvalidated heuristic; value unchanged). §3.1 table and update rule. | PKG-01 (built), 03 (built); §3.1 |
| A31 | **`learning_loop_beta` is in no settings API field** (the CodeRabbit PR #673 reopen of PKG-00, commit 2349294; ledger `00 \| reopened`; HANDOFF-00 Post-hoc changes). <br>• The column is not in `routes/profile.py::_SETTINGS_COLS` or `ALLOWED`, nor in `models.UpdateSettingsBody` or `SettingsResponse`. The settings GET does not return it, and a PATCH carrying it answers 200 and writes nothing. <br>• Why: the settings select named the column, so code deployed before `20260926231744_learning_loop_beta.sql` broke settings GET/PATCH for every student, even with the loop off. <br>• Only `learning/gate.py` reads the column, and it fails closed: a missing column or a read error gives `False` (pinned in `tests/test_learning_settings_flag.py`). <br>• This supersedes A14's earlier "readable in the settings GET, not student-patchable" bullet and its PKG-04 Task 0 reopen. PKG-04 Task 0 now only verifies the shipped state (a grep plus the settings tests); it makes no commit and appends no `00 \| reopened` row. The frontend never reads the key (§11.3 vitest: `/status` is the only input). | PKG-00 (built), 04, 13, 14; §1, §4, §7, §11.2, §11.3, §14, README, LEDGER rules |
| A32 | **H6 needs a practice item; ungraded is not practice** (ZPD report §"GATES": `item.practice = true`; "ungraded coursework never gets H6"). <br>• `gates.h6_allowed(step, *, item_taught, item_practice, item_graded) -> bool` (PKG-06) = `genuine_attempts ≥ H6_MIN_GENUINE_ATTEMPTS and item_taught and item_practice and not item_graded and not exam_mode`. <br>• Representation: a derived predicate with no new column. Every `check_items` row is practice material by construction, because PKG-04 drafts only from shared `course_material` (A23) and never from `completed_work`. So `item_practice` is true exactly when the item is the session's active in-session check (`loop_state["active"]`, set only by `_activate_next_item`, which never selects the post-test reserve). The probe, review and post-test have no hint ladder and never call the gate. <br>• `item_graded` is the stored `check_items.graded` flag, false on every generated item; a missing item fails closed. `item_taught` is recorded on the item's `loop_state` entry at activation: the concept got a served teach turn, or a check with its feedback turn, earlier in the session. <br>• Any future import of coursework into `check_items` must first add an explicit column in a new migration. §3.3 (H6 row and predicates), §4 (`graded` comment), §9 (activation). | PKG-04 (DDL comment), 06, 07; §3.3, §4, §9 |
| A34 | **Check items state a structured final answer; the leak check never parses a reference** (series coordinator's design decision, 2026-09-27, ending an oscillation between PKG-06 review rounds). <br>• Why: PKG-06's final-answer rule had to extract "the final answer" from a free-text reference — cue words, `=` clauses, the last standalone number, power terms, justifications, Markdown — an unbounded heuristic that failed review round after round (review round 5's version read "The derivative of 4x^3 + 7 is 12x^2" as the answer `7`). The check-item generator knows the answer, so it states it. <br>• PKG-04 (reopened by PKG-06): migration `<ts>_learning_check_items_final_answer.sql` adds `check_items.final_answer text` — encrypted, invariant 9, nullable only so existing rows migrate (§4). `CheckItemDraft.final_answer` is required: the exact final answer the reference concludes with, copied verbatim from it — the number with its unit, the final expression, the correct option's text (`mc_reason`), or, for a conceptual/teachback item, the short decisive claim — at most `CHECK_ITEM_FINAL_ANSWER_MAX_TOKENS` (20 †) tokens; the reference closes with "Final answer: <final_answer>." (the schema descriptions carry that contract; an `mc_reason` reference quotes the correct option's text). `validate_draft` rejects, each reason naming `final_answer`: empty; over the cap; not in `reference_answer`; in the prompt (an answer the question prints is no secret); the concept name or a part of it as a hint may spell it — an article or determiner aside (the/a/an/its/their/this/that/these/those), a hyphen between two words read as a space, the name's last word in either regular number (+s/+es) — ("The base case.", "Base cases", "the base-case" for "Base Case"; it would block every hint that names the concept; PKG-06 review rounds 7–8); a numeric item whose stated value is not `canonical_answer`; an `mc_reason` answer that is not the correct option's text (equal, not merely containing it: "A: <text>" would let a hint quote the text unflagged; PKG-06 review round 7) — all compared as runs of `checks.answer_tokens` (numbers by value — `0.5` = `.50`, `1,250` = `1250`; whitespace; `**` as `^`; unicode superscripts as `^` plus their characters, a run as one span; unicode minus and en dash as `-`; `×` `·` `*` as juxtaposition; NFKC; surrounding punctuation and brackets dropped). `checks.select_item` and `checks.posttest_reserve_hash` consider only items that state one (`checks.is_servable`; fail closed), and so do PKG-08's probe and PKG-10's isomorph re-ask (`next_isomorph` runs over the servable candidates only). `scripts/backfill_check_items.py --regenerate-missing-final-answer` (explicit) retires a course's rows without one and redrafts their concepts; nothing ever derives a final answer from reference text. The `check_items` eval gains `FinalAnswerValid` (every accepted draft's final answer is copied verbatim — a substring, not only a normalised match, which `validate_draft` already enforces — from its reference and is not in its prompt), required at 1.0. <br>• PKG-06: `leak.detect_leak(reference, emitted, rung, *, final_answer, canonical_answer=None)` and `leak.strip_leak(emitted, reference, *, final_answer, canonical_answer=None)`. The final-answer rule is token-run containment of `final_answer` in the emitted text under that normalisation, plus — when `canonical_answer` is present — any number with its value: its mantissa (an e-notation exponent is not part of it), or its full value written in any notation — a number with an exponent right after it (e-notation, `× 10^k`, `x 10^k`, a superscript), so `2.5 × 10^-3`, `2.5e-3` and `0.0025` are one value, and a bare number of that value counts whatever exponent follows it (PKG-06 review round 7). The `LEAK_NGRAM` rule is unchanged. A missing or empty `final_answer` raises `ValueError`. The PKG-06 text heuristics are deleted. <br>• Callers pass the ACTIVE item's decrypted `final_answer` and `canonical_answer` (PKG-07's model-turn check and strip, `_leak_checked_payload` — invariant 27 — and the PKG-07/14 leak evals). No client payload (probe, check, review, post-test) carries `final_answer`. <br>• Known limits, measured by PKG-07's leak evals: a free item's number-with-unit answer ("9.8 m/s^2") matches only as its whole run, so a bare "9.8" is caught only on a numeric item (by `canonical_answer`); a paraphrase of a teachback claim is not a token-run match; an answer spelled in words ("six x squared") is not normalised. Accepted by the owner as documented known gaps in PKG-06 review round 7 and pinned by tests (`test_known_gaps_of_the_final_answer_rule_are_pinned`): an `mc_reason` item's correct option LETTER ("The answer is C.": the final answer is the option's text); LaTeX macros (`\cdot`, `\times`, `\text{}`, `\mathrm{}`, `\frac{}{}`, `\pi`, `\sqrt`, `\left`/`\right`) split a run in both directions (a LaTeX hint for a plain final answer, or a final answer copied in LaTeX), and U+2044 / U+2215 are not "/" ("½" misses "1/2"); `strip_leak` withholds a bracket's partner with its run when only whitespace parts them (review round 8: "10^(-3)" and `$6x^{2}$` leave no stray ")" or "}"), so only a partner beyond a token outside the run stays ("10^(-3 + 1)" → "[withheld] + 1)"); a hyphenated answer vs its spaced spelling; a bare power of ten (`10^3` for canonical `1e3`); the decisive part of a final answer of `LEAK_NGRAM`+ tokens (37 of 39 accepted drafts in the recorded eval; the cap is 20 †). On the validation side a percent ("25%" states 25) and a non-terminating quotient ("1/3" vs `0.333`) drop the draft (fail closed), and an irregular plural of the concept name ("matrices" for "Matrix") is another word to the concept-name rule. | PKG-04 (reopened), 06, 07, 08, 10, 12, 13, 14; §2, §3.4, §3.5, §4, §8 (9, 27) |
| A35 | **With the loop on, the class summary is numbers only: no prose and no `course_summary` call** (finding A of the live sequence test of PR #673, 2026-09-27, and the review of its first fix; a PKG-03 reopen, commits 3e03377, 1c4bb4d and 3fbe966, ledger `03 \| reopened`, HANDOFF-03 Post-hoc changes). <br>• Finding: each evidence flush runs `apply_graph_update` → `update_course_context` for every offering the student has in the touched course. That call regenerated `offering_summary.summary_text` on gemini-2.5-flash whenever its hash moved. The hash keyed on the raw per-concept scores, and on the loop they move on every graded answer: 10 `course_summary` calls cost $0.021969, 84% of a run whose grading cost $0.000573 (≈ $0.0044 per flush for a student in two offerings), outside §3.5's envelope. A failed refresh was swallowed (`except: pass`). <br>• What the code supports: the prose has no reader on any request path. The last `get_course_context` caller went with #472, and `docs/audits/student-data-inventory.md` lists `summary_text` as unread. No series package reads it. `offering_concept_stats` (read by the misconceptions tool) and the `offering_summary` numbers still refresh on every flush. <br>• Loop on (`config.LEARNING_LOOP_ENABLED`, a §7 evaluation point; process-wide, because in the build phase one class mixes students on and off the loop and a per-user gate cannot pick the regime of a class artifact): `update_course_context` upserts the same numbers the pre-series regime writes (student count, class average, top-5 struggling and mastered lists) with `summary_text` and `summary_hash` NULL. Nothing else writes the prose, so the loop makes 0 `course_summary` calls, on the answer path or off it. The old prose is cleared rather than kept, because text from before the loop turned on would contradict the numbers the loop keeps moving. <br>• Rejected: re-keying the hash alone, because a tier change would still put a synchronous Flash call on the answer path. Also rejected: the first fix (commit e650d35), a lifespan refresher that rewrote the prose off the answer path whenever a tier-keyed hash moved. Its review found four problems. The key moved on ≈ 13–24% of flushes in simulation (1 in 5 in the live run), so it cost about one call per offering per active 15-minute interval: up to 96 per offering per day, ≈ $8 per offering per month. It paid that once per app instance, because nothing claimed an offering across instances. A failing call retried every pass. And none of it was visible to the A20 per-student caps (no `user_id`). All of that bought text that nothing reads. A future reader brings the prose back only through a new amendment that meets §3.5's conditions. <br>• Loop off: the pre-series behaviour, byte-identical (raw-stats hash, the average to 0.1%, synchronous regeneration). Kill switch: the NULL hash never matches the stats hash, so the first refresh after the loop turns off writes the prose once per offering. Both are pinned by `tests/test_course_summary_refresh.py`. It also pins, by AST over every backend module, that `_generate_summary_with_gemini` is the only code that reaches the agent: by its name (bare or under an import alias), as a module attribute, as a string, or through a fresh agent on the `course_summary` model slot (`model_for` / `model_name_for`). The behavioural tests catch any path the AST misses that runs through `update_course_context`. <br>• Both regimes: a failed course-context refresh is logged (`logger.warning(..., exc_info=True)`) instead of swallowed. This covers every caller in `services/graph_service.py`, through one helper, `_refresh_course_context`: `apply_graph_update`, `add_course`, `delete_node` and `delete_course`. The write the refresh follows stands. <br>• When the loop turns on, each offering's first refresh clears its prose. That holds in every class on the environment, including classes with no student in the beta: on staging it starts when the flag turns on at PKG-07 (§7). After PKG-14b the flag is on by default, so this is the product's regime. §3.5 (class summary), §7 (evaluation points, staging value). | PKG-03 (built); §3.5, §7 |
| A36 | **Evidence journal rows carry their apply order** (finding B of the live sequence test of PR #673, 2026-09-27; a PKG-03 reopen, commit 4de10d3, reader order f127a51, ledger `03 \| reopened`, HANDOFF-03 Post-hoc changes). <br>• Finding: the rows one `apply_graph_update` call writes to `node_mastery_events` share one `created_at` and have random uuid ids, so nothing orders them for a replay. A 3-question quiz had to be re-ordered from its `p_before → p_after` links, which cannot decide between two rows that start from the same p. <br>• Migration `20260927182054_learning_mastery_event_seq.sql` adds `evidence_seq integer`, nullable, `CHECK (evidence_seq IS NULL OR evidence_seq >= 0)` (§4). `_apply_evidence` journals 0..n−1 in apply order within the call, counting journaled rows only: a skipped evidence (not owned, or outside the course) takes no number, and a propagation writes no row. Legacy rows never carry the key; evidence rows from before the migration stay NULL. <br>• Every reader that orders journal rows orders by `created_at, evidence_seq, id`, in the same direction for all three (PostgREST `order="created_at.asc,evidence_seq.asc,id.asc"`, or `.desc` on all three). `id` is only a deterministic tie-break. Evidence rows from before the migration all carry NULL, so within their shared `created_at` they stay in no true order. PostgREST's default places NULLs last ascending and first descending, and that default is harmless: one call's rows are written by one code version, so no `created_at` mixes NULL and numbered evidence rows. <br>• The unbuilt readers this binds follow this row where their prompt text says otherwise. PKG-09's close read (`order="created_at.asc"`) feeds `build_close`'s first `p_before` and last `p_after` per node. PKG-14's `derive_zpd_metrics._evidence` (`order="created_at.desc,id.desc"`) cuts the last `BAND_WINDOW`/`HTC_K_WINDOW` opportunities through one flush's rows. Its `unassisted_next_session` KPI counts "the FIRST row" of each session in `created_at` order. A multi-question check on one concept writes exactly the tied rows these reads cut through. PKG-07's seen/revealed-hash readers build sets and do not depend on order. <br>• The single-writer invariant holds: only `apply_graph_update`'s evidence path writes the column (invariant 1). Plaintext. §2, §4, §5. | PKG-03 (built), 09, 14; §2, §4, §5 |

## 14. Packages, dependencies, execution order

Executed strictly one at a time in this order: **00, 01, 02, 03, 04, 05, 05b, 06, 06b, 07, 08, 09, 10, 11, 12, 13, 14** (14 = half A, then half B after §11.1). PKG-15 is post-series and independent of 14.

Exception on record: **PKG-11 ran early**, right after PKG-03's review round (branch `feat/learning-loop-11-quiz-flashcards`, merge-base `a1a416b`; ledger `11 | done` at `fb708a2`). Its code dependencies (02, 03) were met, so it is kept: it is `done`, its prompt is frozen like 00–03 (never edited), and the order continues at 04 and skips 11 when it gets there. PKG-12 and PKG-14 find it done. Its hand-off predates A14/A20; when this amendment lands, HANDOFF-11 gets one "Post-hoc changes" line (no code change, no `reopened` row): `spec §13 A14/A20 (2026-09-26, recorded post-hoc): "the seeded student is opted out" reads "the loop is dark during the build"; "At cutover the seeded student moves to the loop path" reads "At launch (spec §11.2) the quiz becomes evidence-only for everyone"; frontend/e2e/quiz-integration.spec.ts:49–50,130 (ALL_CORRECT_DELTA = 3 * 0.03) is a legacy-path pin too (PKG-14 §Behaviour B.9 owns it); the quiz/flashcard gate branches exist in the build phase only (PKG-14b removes them); quiz submit makes no LLM call, so pure mc evidence keeps working under every cap (A20).`

| pkg | slug | depends on (code) | notes |
|---|---|---|---|
| 00 | foundation | — | built |
| 01 | bkt-core | 00 | built |
| 02 | fsrs-core | 00 | built |
| 03 | evidence-state | 01, 02 | in progress |
| 04 | check-items | 00 | Task 0 verifies that `learning_loop_beta` is on no settings path (A31; no reopen); A22/A23 columns and rules |
| 05 | grader-check-tool | 03, 04 | builds `grade_answer` (A16); reopens PKG-03 (`Evidence.grader_backend`, the column write) and PKG-01 (renames `GRADER_RETRY_BELOW` → `GRADER_SECOND_OPINION_CONFIDENCE`, A6; HANDOFF-01 Known gap (i)) |
| 05b | decision-seam | 05 | new; reopens PKG-05 (`grade_answer` calls through the seam) |
| 06 | zpd-policy | 03, 04 | `model_tier`, `context_policy`, `check_pose`, `deterministic_content`; reopens PKG-04 (A34: `check_items.final_answer`, the answer normalisation, servable-only selection, the regenerate backfill mode) |
| 06b | ai-budget-and-usage | 03, 06 | new; imports `learning/policy.py`'s `Band`/`Tier`/`BudgetLevel` (PKG-06); wires `ai_budget.check` into the PKG-05 and PKG-05b run sites (both earlier in the order) as reopen commits |
| 07 | loop-tutor | 05, 05b, 06, 06b | tier slots, check-answer route, deterministic turns, context policy, rate limit |
| 08 | probe-planner | 07 (and 04, 05, 06b through it) | probe grades through `grade_answer` |
| 09 | close-brief | 07, 08, 06b | brief stored at `/plan/approve` (post-hoc PKG-08) |
| 10 | misconceptions | 05, 05b, 06, 07, 09 | reopens 03, 05, 06, 07, 09 as already planned |
| 11 | quiz-flashcards | 02, 03 | built early (after 03); prompt frozen; HANDOFF-11 Post-hoc changes line (above) |
| 12 | review-surfaces | 05, 06b, 07, 11 | |
| 13 | frontend-e2e | 08, 09, 12 (and 06b for the cap journey) | launch UI readiness (§11.3) |
| 14 | eval-ladder-cutover | all of 00–13, 05b, 06b | half B = launch (§11) |
| 15 | jev-backend (post-series) | 05b + the A24 privacy gate + waitlist access | not part of the launch gate |
