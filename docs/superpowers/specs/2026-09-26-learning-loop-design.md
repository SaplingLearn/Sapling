# Learning Loop — Design Spec (series source of truth)

Status: approved design, not yet built. Every prompt in `docs/superpowers/plans/learning-loop/` cites this file by section heading. Numbers live here once, under a name; code cites the name.

Research basis: `docs/research/learning-loop/AI tutor learning loop research.md` (loop, learner model, scheduler, guardrails, evaluation) and `docs/research/learning-loop/ZPD lever tradeoffs and upgrades.md` (§"Sapling ZPD policy spec" for the ladder/ceiling/gates; §"Re-verification" for corrected numbers). Design page: Canopy artifact `sapling-learning-loop-research-backed-design`.

## 1. Goal and invariant statement

Only graded checks change what Sapling believes a student knows. The belief is a per-(student, concept) probability from Bayesian Knowledge Tracing (BKT) with fixed priors and a separate guess/slip pair per evidence channel. It decays toward the prior between checks along an FSRS-6 forgetting curve and is scheduled for review near 90% recall. How much help the tutor may give is computed in code from the learner state, never from the student's text, and every hint is one rung of a fixed ladder gated by a genuine attempt. Learning is measured by unassisted success on the next opportunity and on tool-removed, delayed checks; never by in-session accuracy or by the change in the belief.

Everything ships behind `LEARNING_LOOP_ENABLED` + `user_settings.learning_loop_beta`. With the env var unset, every pre-series test passes unchanged.

## 2. Module map

```
backend/learning/                 pure policy + math; NO imports from agents/, pydantic_ai, google, db/ in bkt.py, fsrs.py, policy.py, gates.py, ladder.py, leak.py
  gate.py            learning_loop_active(user_id) -> bool                                     PKG-00
  params.py          every named constant in §3                                               PKG-01
  bkt.py             update(), decayed_p(), propagate_prereq(), band(), tier_for()             PKG-01
  fsrs.py            retrievability(), interval(), next_state(), rating_for(), order_due(),   PKG-02
                     budget_select(), successive_relearning state machine
  evidence.py        Evidence model + channel enum                                             PKG-03
  learner_state.py   read_state (decayed) / write_state; learner_state table access via table() PKG-03
  checks.py          CheckItem models, question_hash(), select_item()                          PKG-04
  ladder.py          Rung enum H0..H6 + rung intent text                                       PKG-06
  policy.py          ceiling(), evidence_for_rung(), band_control(), wheelspin()               PKG-06
  gates.py           genuine_attempt(), rung_unlock(), h6_allowed(), offer_allowed()           PKG-06
  leak.py            detect_leak(reference, emitted, rung) -> LeakVerdict                      PKG-06
  probe.py           next_probe_item(), probe_done(), novice_floor()                           PKG-08
  planner.py         outer_fringe(), plan()                                                    PKG-08
  session_close.py   build_close(), store_close()                                              PKG-09
  learner_brief.py   build_brief() bounded                                                     PKG-09
  misconceptions.py  record(), slip_or_misconception(), rollup() (n>=5)                        PKG-10
  review.py          due_queue(), serve(), grade_review()                                      PKG-12
backend/agents/check_items.py     task "check_items"  (ingest-time item generation)           PKG-04
backend/agents/grader.py          task "grader"       (rubric grading, sees the key)           PKG-05
backend/agents/tools/check.py     graded_check_tool + record_evidence on deps                  PKG-05
backend/agents/loop_tutor.py      task "loop_tutor"   (phase prompts)                          PKG-07
backend/routes/learn_loop.py      /api/learn/loop/*                                            PKG-07..12
backend/services/check_item_service.py  CRUD for check_items (encrypted columns)              PKG-04
backend/scripts/backfill_check_items.py, backend/scripts/derive_zpd_metrics.py               PKG-04, PKG-14
backend/tests/test_learning_loop_invariants.py   grows every package                          PKG-00..14
frontend/src/components/learn/LoopLearn.tsx, frontend/e2e/learn-loop.spec.ts                 PKG-13
```

## 3. Named constants (single source; `backend/learning/params.py`)

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
| `BAND_NOVICE_MAX` | 0.30 | p_known below → band `novice` |
| `BAND_DEVELOP_MAX` | 0.80 | p_known below → `develop`; else `profic` |
| `WEIGHT_ASSISTED` | 0.5 | correct after H1–H3 |
| `WEIGHT_SAME_SESSION_RECHECK` | 0.5 | re-check of the same `question_hash` within one session |
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
Validity asserted at import: `G + S < 1`, `G ≤ BKT_G_MAX`, `S ≤ BKT_S_MAX`, `0 < T < 1 − S/(1−G)` for every channel.

Decay at read: `P_now = BKT_L0 + (P_stored − BKT_L0) · R(Δt, S_c)` where `R` is §3.2 retrievability and `S_c` the concept's FSRS stability; if no FSRS state exists, `S_c = FSRS_S0_GOOD`.

Propagation, one hop, asymmetric, edges `graph_edges.relationship_type = 'prerequisite'` with `source_node_id` = prerequisite, `target_node_id` = dependent (`EDGE_PREREQ_SOURCE_IS_PREREQ = True`; PKG-08 verifies against live data and flips the constant if the convention is reversed):
- correct at c → each prerequisite parent gets a `chat_turn`-strength correct observation at `WEIGHT_PROPAGATION`;
- incorrect at c → each dependent child gets a `chat_turn`-strength incorrect observation at `WEIGHT_PROPAGATION`; parents untouched.

Tier mirror into `graph_nodes.mastery_tier` (CHECK unchanged) on the loop path: `p < 0.10 → unexplored`, `< BAND_NOVICE_MAX → struggling`, `< BKT_PROFICIENT → learning`, else `mastered`. (`TIER_UNEXPLORED_MAX = 0.10`.) Legacy tiers 0.1/0.45/0.75 remain for flag-off until PKG-14.

### 3.2 FSRS-6

```
FSRS_W = [0.212, 1.2931, 2.3065, 8.2956, 6.4133, 0.8334, 3.0194, 0.001, 1.8722, 0.1666,
          0.796, 1.4835, 0.0614, 0.2629, 1.6483, 0.6014, 1.8729, 0.5425, 0.0912, 0.0658, 0.1542]
factor        = 0.9^(−1/w20) − 1
R(t,S)        = (1 + factor·t/S)^(−w20)
I(r,S)        = (S/factor)·(r^(−1/w20) − 1)
S0(G)         = w[G−1]                          G ∈ {1 Again, 2 Hard, 3 Good, 4 Easy}
D0(G)         = clamp(w4 − e^(w5·(G−1)) + 1, 1, 10)
ΔD = −w6·(G−3);  D' = D + ΔD·(10−D)/9;  D'' = w7·D0(4) + (1−w7)·D'
S_recall      = S·( e^(w8)·(11−D)·S^(−w9)·(e^(w10·(1−R)) − 1)·[w15 if Hard]·[w16 if Easy] + 1 )
S_lapse       = w11·D^(−w12)·((S+1)^(w13) − 1)·e^(w14·(1−R))
S_same_day    = S·e^(w17·(G−3+w18))·S^(−w19)
```

| Name | Value | Meaning |
|---|---|---|
| `FSRS_RETENTION_DEFAULT` | 0.90 | desired retention |
| `FSRS_RETENTION_LARGE_SET` | 0.85 | when a user has > `FSRS_LARGE_SET_CONCEPTS` scheduled concepts in a course |
| `FSRS_LARGE_SET_CONCEPTS` | 150 | |
| `FSRS_RETENTION_EXAM` | 0.95 | when a syllabus exam is within `FSRS_EXAM_WINDOW_DAYS` |
| `FSRS_EXAM_WINDOW_DAYS` | 14 | |
| `FSRS_S0_GOOD` | `FSRS_W[2]` = 2.3065 days | default stability before first review |
| `REVIEW_ORDER_THRESHOLD` | 0.33 | order due items by `|R − 0.33|` ascending (DASH) |
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
student showed own work / buggy step        → floor at H3 (never below)
```

| Name | Value | Meaning |
|---|---|---|
| `GATE_INDEPENDENT_MIN_S` | 45 † | seconds alone before an attempt counts (develop/profic) |
| `GATE_INDEPENDENT_MIN_S_NOVICE` | 90 † | |
| `GATE_RUNG_DWELL_MIN_S` | 8 † | seconds on the current rung before the next unlocks |
| `H6_MIN_GENUINE_ATTEMPTS` | 2 | plus `item.taught == True` and `item.graded == False` |
| `OFFER_BANDS` | {`novice`} | error-triggered "want a hint?" offer only for novices |

† = engineering choice with no validated cut-point; first A/B candidates; must be marked † in hand-offs.

Genuine attempt = a submitted answer or shown work, not `idk`/"just tell me", after the independent-time gate. "just tell me"/"give me the answer" patterns are detected by a small deterministic list in `gates.py` (`NON_ATTEMPT_PATTERNS`), never by an LLM.

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

Slip / misconception / novice rule (`misconceptions.slip_or_misconception`):
- wrong once → `unknown`: standard update; re-ask an isomorph (different surface, same `node_id`, different `question_hash`)
- wrong then right on the isomorph → `slip`: no misconception record
- wrong on ≥ 2 isomorphs with the same `wrong_key`, or wrong with stated confidence ≥ `MISCONCEPTION_CONFIDENCE (0.7)` → `misconception`: record; tutor confronts with a contradiction
- wrong with low confidence → `gap`: teach
- right answer, wrong reason → `not_known`: treat as a miss
- 3 misses at difficulty 1 or repeated `idk` (`NOVICE_FLOOR_MISSES = 3`) → `novice`: exit probe; novice step format on the lowest prerequisite

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
| `LOOP_HISTORY_MAX_MESSAGES` | 20 (replaces unbounded `_load_message_history` on the loop path) |
| `LEARNER_BRIEF_MAX_CHARS` | 1800 |
| `LEARNER_BRIEF_LAST_CLOSES` | 3 |
| `LEARNER_BRIEF_TOP_STATES` | 5 |
| `LEARNER_BRIEF_MAX_MISCONCEPTIONS` | 5 |
| `LOOP_LIMITS` | request 14 / tool calls 14 / tokens 120_000 (`agents/__init__.py`) |
| `GRADER_LIMITS` | request 2 / tool calls 0 / tokens 20_000 |
| `GRADER_LOW_CONFIDENCE` | 0.6 → `WEIGHT_LOW_CONFIDENCE`; below 0.4 → route to a second grader call, else return `unavailable` |
| `LEAK_NGRAM` | 6 tokens of the reference answer appearing verbatim in emitted text at rung < H6 → leak; also exact final numeric/symbolic answer match |
| `CHECK_ITEM_FORMATS` | `free`, `teachback`, `mc_reason` |
| `CHECK_ITEM_DIFFICULTIES` | 1, 2, 3 |
| `CHECK_ITEM_MIN_RUBRIC` | 2 |
| `CHECK_ITEM_MIN_WRONG` | 1 |
| `MISCONCEPTION_ROLLUP_MIN_USERS` | 5 |
| `ZPD_RATING_EVERY_N_CHECKS` | 30 (perceived difficulty prompt: too_easy / appropriate / too_hard) |

## 4. Schemas (DDL written by the named package; prefixes generated with `date -u +%Y%m%d%H%M%S`; basename `<ts>_learning_<desc>.sql`)

```sql
-- PKG-00: <ts>_learning_loop_beta.sql
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
  source_chunk_ids  text[] NOT NULL DEFAULT '{}',
  question_hash     text NOT NULL,          -- sha256 of PLAINTEXT prompt (ADR 0025 pattern)
  graded            boolean NOT NULL DEFAULT false,
  created_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (course_id, concept_key, question_hash)
);
CREATE INDEX IF NOT EXISTS check_items_concept_idx ON check_items (course_id, concept_key, format, difficulty);

-- PKG-06: <ts>_learning_session_loop_state.sql
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS loop_state jsonb NOT NULL DEFAULT '{}'::jsonb;
-- keyed by question_hash: {rung, attempts, first_shown_at, last_rung_at, attempted_at[]}; no free text.

-- PKG-09: <ts>_learning_session_close.sql
ALTER TABLE sessions
  ADD COLUMN IF NOT EXISTS close_json text,          -- encrypted JSON {summary, self_eval, if_then, concepts:[{node_id, p_before, p_after}], misconceptions:[wrong_key]}
  ADD COLUMN IF NOT EXISTS close_phase text CHECK (close_phase IN ('probe','plan','teach','check','feedback','close'));

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
CREATE OR REPLACE FUNCTION misconception_rollup(p_course_id text)
RETURNS TABLE (node_id text, wrong_key text, users int)
LANGUAGE sql SECURITY DEFINER AS $$
  SELECT m.node_id, m.wrong_key, count(DISTINCT m.user_id)::int
  FROM misconceptions m JOIN graph_nodes g ON g.id = m.node_id
  WHERE g.course_id = p_course_id AND m.resolved_at IS NULL
  GROUP BY m.node_id, m.wrong_key
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

Encryption: `prompt`, `reference_answer`, `rubric_json`, `common_wrong_json`, `evidence_text`, `close_json` use `services/encryption.py` (`encrypt_if_present` at write, `decrypt_if_present` at read). Never filter or join on them. `question_hash` and `wrong_key` are the plaintext lookup keys.

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
```
`apply_graph_update(user_id, graph_update, course_id=None)` accepts `graph_update["evidence"] = [Evidence-as-dict, ...]`. When present: for each evidence, read decayed state, run `bkt.update`, apply propagation, upsert `learner_state`, mirror `graph_nodes.mastery_score = p_known` and tier per §3.1, append one `node_mastery_events` row with `event_type='evidence'` and the new columns, update FSRS state via `fsrs.next_state(rating_for(...))`. When absent, the legacy `updated_nodes` path runs byte-identically. No other module writes `graph_nodes`, `graph_edges`, `node_mastery_events` or `learner_state`.

## 6. Events (add to `EVENT_TAXONOMY` with the pin test)

| type | category | payload keys (ids/counts/enums only) |
|---|---|---|
| `zpd.step` | usage | request_id, user_id, concept_id, question_hash, phase, channel, band, ceiling, ceiling_reason, first_attempt_correct, n_attempts, max_rung_used, rungs[{rung,dwell_ms}], time_to_first_attempt_ms, time_to_correct_ms, independent_time_ms, assisted, confidence, fsrs_rating, p_known_before, p_known_after, r_before, item_difficulty |
| `zpd.offer` | usage | accepted, band |
| `zpd.band_adjust` | usage | direction, trigger, window_stats |
| `zpd.wheelspin` | error | concept_id, opps, unassisted_next, htc_k, prerequisite_ids |
| `zpd.leak` | error | rung_emitted, ceiling, detector, request_id |
| `zpd.rating` | usage | rating (too_easy/appropriate/too_hard), checks_since_last |
| `learn.probe_done` | usage | items, misses, novice_floor, skills |
| `learn.plan_approved` | usage | concept_ids, n_reviews_first |
| `learn.session_closed` | usage | session_id, concepts, misconceptions, has_if_then |
| `review.served` | usage | kind (flashcard/check), n, budget_min, retention_target |
| `review.graded` | usage | kind, correct, rating |

## 7. Flag and gate

- `config.LEARNING_LOOP_ENABLED = os.getenv("LEARNING_LOOP_ENABLED", "false").lower() == "true"`.
- `learning/gate.py::learning_loop_active(user_id: str) -> bool` = env AND `user_settings.learning_loop_beta` (one `table("user_settings").select(...)`, cached per request via `services/request_context` if a per-request cache exists; else a plain read).
- Evaluated at route entry in `routes/learn.py` (`start_session`, `/start-session/stream`, `/chat`, `/chat/stream`, `/action`, `end_session`), `routes/quiz.py::submit_quiz`, `routes/flashcards.py::rate_card`/`get_flashcards`. When true the handler delegates to `routes/learn_loop.py`. Never inside `services/chat_stream.py`.
- `SaplingDeps.learning_loop: bool = False`, `SaplingDeps.loop_state: Any = None`, `SaplingDeps.pending_evidence: list = field(default_factory=list)`.
- `chat_tutor._build_tools(learning_loop: bool = False)`: when true registers `graded_check_tool` and omits `update_mastery_tool`.
- `/api/learn/loop/*` returns 404 `{"detail": "learning loop not enabled"}` when the gate is false.

## 8. Invariants (asserted in `backend/tests/test_learning_loop_invariants.py`)

1. No write to `graph_nodes`, `graph_edges`, `node_mastery_events`, `learner_state` outside `services/graph_service.py::apply_graph_update` (source grep over `backend/` for `table("graph_nodes")`/`.upsert(`/`.update(`/`.insert(` co-occurrence outside that function; `learner_state.write_state` is only called from `apply_graph_update`).
2. `learning/bkt.py`, `fsrs.py`, `policy.py`, `gates.py`, `ladder.py`, `leak.py` import nothing from `agents`, `pydantic_ai`, `google`, `db`.
3. Every channel satisfies `G + S < 1`, `G ≤ BKT_G_MAX`, `S ≤ BKT_S_MAX`, `0 < BKT_T < 1 − S/(1−G)`.
4. `policy.ceiling` and `policy.band_control` signatures take no `str` message parameter; `policy.py` does not import `gates.NON_ATTEMPT_PATTERNS` consumers that read text.
5. Every `zpd.*`, `learn.*`, `review.*` literal in `backend/` (grep) is in `EVENT_TAXONOMY`.
6. Every `AgentTask` literal added by the series (`check_items`, `grader`, `loop_tutor`) has a handler registered in `agents/function_handlers_e2e.py`.
7. Learning tables are accessed only via `db.connection.table()`/`rpc()`.
8. Series migrations match `^\d{14}_learning_[a-z_]+\.sql$`; `git log --diff-filter=M -- backend/db/migrations/*_learning_*.sql` is empty.
9. No `UNIQUE` and no `eq.` filter on `prompt`, `reference_answer`, `rubric_json`, `common_wrong_json`, `evidence_text`, `close_json`.
10. Any `lru_cache` under `backend/learning/` has a `clear_<name>_cache` function referenced from `tests/conftest.py::_clear_lru_caches`.
11. With `LEARNING_LOOP_ENABLED` unset, `learning_loop_active` returns False for every fixture user.
12. Each series agent module defines exactly one system prompt (no `_fallback_prompt`, no second `Agent(` with a different prompt for the same task).

## 9. Session phases (loop path)

`probe` (PKG-08) → `plan` (PKG-08, student approves) → per concept: `teach` (PKG-07) ⇄ `check` (PKG-05/07) → `feedback` (PKG-07) → `close` (PKG-09). `sessions.close_phase` records where the session stopped. A session row may not exist until the first `/chat` (lazy); every loop write upserts the row by `session_id`.

Stream events added to `services/agent_events.py::SaplingEventType` (PKG-07): `phase` (data: {phase}), `check` (data: {question_hash, format, difficulty}), `hint_offer` (data: {rung}), `learner_state` (data: {node_id, p_known, band}).

## 10. Evaluation ladder (PKG-11..14)

Rung 1 offline: `tests/evals/grader.py` (leakage: output never contains reference text; rubric agreement vs gold ≥ baseline), `tests/evals/loop_tutor.py` (answer-leak fixtures, "student insists on a wrong claim" sycophancy fixtures, ceiling compliance, feedback-never-ends-in-answer, ≤ `STEP_MAX_SENTENCES`, one question). Rung 2 online: A/B on unassisted next-opportunity success and first-attempt correctness at next review (`scripts/derive_zpd_metrics.py`; `user_settings.loop_arm` for within-student concept randomization). Rung 3: tool-removed post-test endpoint (`learn_loop.py::posttest`, ceiling H0, no RAG, no brief). Rung 4: delayed proctored retention (out of series scope; the log fields make it possible).

KPIs: share of steps with rolling unassisted success inside the phase band; `htc_k` trend per concept (must fall); unassisted next-opportunity success on the following session's first item. Gates (not KPIs): 0 solution reveals, ≤ 5% earnest-revise, ≥ 95% ceiling compliance.

## 11. Cutover (PKG-14, after all packages verified and the flag has been on for the beta cohort)

Remove: `update_mastery_tool` + `ConceptMasteryUpdate.mastery_delta` and the preamble paragraph instructing it (`agents/tools/graph.py`, `agents/chat_tutor.py:84–91`); `MASTERY_DELTA_PER_*` + `mastery_after` (`services/quiz_config.py:103–115`) and the delta block in `routes/quiz.py::submit_quiz` (:2535–2558); `MASTERY_*_MIN` / `get_mastery_tier` (`config.py:113–118`) → `learning/bkt.py::tier_for`; `learning_style` onboarding step and reads (`frontend/src/components/screens/Onboarding.tsx`, `routes/onboarding.py`, profile models; column stays, ADR notes it dead); the three always-empty lists in `end_session`; flag branches collapse to loop-only; `chat_tutor.py` mode prompts fold into `loop_tutor.py`. Update in the same commits: `tests/test_quiz_scoring_e.py`, `frontend/e2e/quiz.spec.ts` (+0.09 → evidence-derived from function-mode constants), `tests/test_mastery_tier_unification.py` + `Learn.tsx::tierForScore`, `tests/evals/chat_tutor.py` `MasteryUpdateEmitted` → evidence evaluator, retire `chat_tutor` cassettes. Record in `docs/decisions/00xx-learning-loop-cutover.md`.

## 12. Do-not-build list

Learning-style routing; a standalone growth-mindset module; deep knowledge tracing or any neural learner model; full Bayesian-network inference over the graph; a Socratic-only mode; an LLM anywhere inside `backend/learning/`.

## 13. Amendments log (in force; override the prompt files where they disagree)

Recorded 2026-09-26 during the prompt-authoring consistency pass. A prompt that references the older wording follows this section. Each executing session re-reads this section before Task 1.

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
