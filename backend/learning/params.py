"""Learning loop named constants — the single source (spec §3).

Every number the loop uses lives here under the spec's name; code cites the
name. A numeric literal in loop code is a review failure (series README).
Stdlib only: the pure modules (bkt, fsrs, policy, gates, ladder, leak) depend
on this one and are forbidden any dependency on agents/, pydantic_ai, google,
db/ (spec §8 invariant 2), so nothing impure may enter here either.

Legend in comments: † = engineering choice without a validated cut-point
(first A/B candidates); ‡ = value from the spec, name assigned by PKG-01.
Spec: docs/superpowers/specs/2026-09-26-learning-loop-design.md §3.1–§3.4.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

# --------------------------------------------------------------- §3.1 BKT
BKT_L0 = 0.35
BKT_T = 0.15
BKT_G_MAX = 0.30
BKT_S_MAX = 0.30
BKT_PROFICIENT = 0.95
BKT_MASTERED = 0.98
BKT_MASTERED_MIN_STRONG = 3
# † Ceiling on bkt.update's output (not a spec §3.1 name; spec §13 row
# pending). Without it back-to-back corrects round p to exactly 1.0, where the
# incorrect posterior is 1·S/(1·S + 0) = 1 and no wrong answer or idk moves it.
# Keeps belief interior so contrary evidence always lowers it; must stay above
# BKT_MASTERED so mastery is still reachable (from the cap one wrong
# free_response stays mastered, two do not). Inputs up to 1.0 remain valid.
BKT_P_MAX = 0.999
BAND_NOVICE_MAX = 0.30
BAND_DEVELOP_MAX = 0.80
TIER_UNEXPLORED_MAX = 0.10
WEIGHT_ASSISTED = 0.5
WEIGHT_SAME_SESSION_RECHECK = 0.5  # † half-weight recheck is a heuristic, not a research finding
WEIGHT_PROPAGATION = 0.5
WEIGHT_LOW_CONFIDENCE = 0.5
S_IDK = 0.02

# Per-channel guess/slip (KT-IDEM). `idk` is NOT a row: it is the idk=True
# flag on bkt.update, which uses the item channel's G with S_IDK.
CHANNELS: dict[str, dict[str, float | bool]] = {
    "free_response": {"G": 0.08, "S": 0.10, "strong": True},
    "mc_reasoned": {"G": 0.10, "S": 0.10, "strong": True},
    "mc": {"G": 0.25, "S": 0.10, "strong": False},
    "teachback_llm": {"G": 0.25, "S": 0.20, "strong": False},
    "chat_turn": {"G": 0.30, "S": 0.30, "strong": False},
}
STRONG_CHANNELS = frozenset(k for k, v in CHANNELS.items() if v["strong"])  # ‡
PROPAGATION_CHANNEL = "chat_turn"  # ‡ spec §3.1: "chat_turn-strength observation"
EDGE_PREREQ_SOURCE_IS_PREREQ = True  # PKG-08 verifies against live data

# ------------------------------------------------------------ §3.2 FSRS-6
FSRS_W = (
    0.212,
    1.2931,
    2.3065,
    8.2956,
    6.4133,
    0.8334,
    3.0194,
    0.001,
    1.8722,
    0.1666,
    0.796,
    1.4835,
    0.0614,
    0.2629,
    1.6483,
    0.6014,
    1.8729,
    0.5425,
    0.0912,
    0.0658,
    0.1542,
)
FSRS_RETENTION_DEFAULT = 0.90
FSRS_RETENTION_LARGE_SET = 0.85
FSRS_LARGE_SET_CONCEPTS = 150
FSRS_RETENTION_EXAM = 0.95
FSRS_EXAM_WINDOW_DAYS = 14
FSRS_S0_GOOD = FSRS_W[2]
REVIEW_ORDER_THRESHOLD = 0.33
REVIEW_DAILY_BUDGET_MIN = 12
REVIEW_SECONDS_PER_CHECK = 45
MC_STABILITY_GAIN_CAP = 2.0
# FSRS-6 reference floor on every new stability, in days (py-fsrs 6.3.2
# STABILITY_MIN, same weights as FSRS_W). Spec §3.2's transcription omits it;
# added by PKG-02 (fsrs.next_state), HANDOFF-02 Deviations / Open question (4).
FSRS_STABILITY_MIN = 0.001
SR_INITIAL_CRITERION = 3
SR_RELEARN_SESSIONS = 3
# spec §3.2: each relearn (and done) session needs one correct recall (PKG-12)
SR_RELEARN_SESSION_TARGET = 1
# PKG-11 † — flashcard UI rating (1 forgot / 2 hard / 3 easy, routes/flashcards.py)
# → FSRS rating (1 Again / 2 Hard / 3 Good; learning.fsrs.Rating, which this
# module cannot import: fsrs imports params). Easy(4) is never emitted in v1
# (spec §3.2 rating map). Engineering choice: the spec has no flashcard row;
# §13 A6 records the value.
FLASHCARD_RATING_TO_FSRS: dict[int, int] = {1: 1, 2: 2, 3: 3}

# ------------------------------------- §3.3 ladder, ceiling, gates, bands
GATE_INDEPENDENT_MIN_S = 45  # †
GATE_INDEPENDENT_MIN_S_NOVICE = 90  # †
GATE_RUNG_DWELL_MIN_S = 8  # †
H6_MIN_GENUINE_ATTEMPTS = 2
OFFER_BANDS = frozenset({"novice"})
BAND_WINDOW = 8
# † Owner decision A38 06(m): band_control moves difficulty up (HARDER) only on
# at least this many first attempts in the window; fewer high ones HOLD.
BAND_CONTROL_HARDER_MIN_ATTEMPTS = 4
PROBE_TARGET_LO = 0.50
PROBE_TARGET_HI = 0.62
ACQ_TARGET_LO = 0.75
ACQ_TARGET_HI = 0.90
PRACTICE_TARGET_LO = 0.65
PRACTICE_TARGET_HI = 0.85
EXAM_TARGET_LO = 0.70
EXAM_TARGET_HI = 0.85
PI_LO = 0.35
PI_HI = 0.70
PI_MIN_ROOM = 5
WHEELSPIN_OPPS = 10
MISCONCEPTION_CONFIDENCE = 0.7
NOVICE_FLOOR_MISSES = 3
# PKG-10 (spec §3.3 "wrong on >= 2 isomorphs with the same wrong_key").
MISCONCEPTION_MIN_ISOMORPHS = 2
# PKG-10 † (spec §13 A6): spec §3.3 says "wrong with low confidence -> gap" with
# no cut-point. Student-stated confidence at or below this is "low"; above it
# and below MISCONCEPTION_CONFIDENCE is "unknown" (re-ask an isomorph). A/B
# candidate. Unused on the served path until a student confidence field exists.
GAP_CONFIDENCE_MAX = 0.4
# PKG-10: the longest wrong_key the misconception store keeps and the learner
# brief renders (an identifier: [a-z0-9][a-z0-9_]*; PKG-09's brief pattern).
MISCONCEPTION_KEY_MAX_CHARS = 64
# PKG-10 (spec §13 A75): the lowest model ceiling a confrontation turn may run
# at while the answer is unreleased. A confrontation poses a concrete case the
# belief gets wrong — a different problem of the concept, H4 content in
# ladder.RUNG_INTENT (the misconception_confront eval's rung judge read every
# H3-ceiling confrontation as H4) — so below H4 the ceiling wins and the
# confrontation marker waits.
MISCONCEPTION_CONFRONT_MIN_RUNG = 4
# Spec §3.2 rating map / §3.3 evidence mapping: correct after H1..H3 is "assisted"
# (FSRS Hard, WEIGHT_ASSISTED); correct after H4..H6 is FSRS Again. Name from
# §13 A6, added by PKG-02 (fsrs.rating_for); PKG-03 Evidence.assisted and
# PKG-06 evidence_for_rung cite it.
RUNG_ASSISTED_MAX = 3
# PKG-03 (§13 A6 names). Rungs H1..H6 unlock in order (PKG-06 gates), so any
# rung >= RUNG_ASSISTED_MIN means help was used (Evidence.assisted); a correct
# answer after a rung >= RUNG_NO_CREDIT_MIN (H4 worked example..H6) is "no
# upward BKT evidence" (spec §3.3); Evidence.max_rung is bounded by
# LADDER_MAX_RUNG (spec §5 "0..6"), which PKG-06's Rung enum reuses.
RUNG_ASSISTED_MIN = 1
RUNG_NO_CREDIT_MIN = 4
LADDER_MAX_RUNG = 6
# Band-control cut-points (unassisted_next 0.90 / 0.65, "2 windows", the
# wheelspin opps>=6 arm) are unnamed in spec §3.3; PKG-06 names them in its
# block below (0.65 is PRACTICE_TARGET_LO).

# ------------------------------------- §3.4 probe, plan, step, brief, limits
PROBE_ITEMS_PER_SKILL_MIN = 4
PROBE_ITEMS_PER_SKILL_MAX = 6
PROBE_SESSION_CAP = 12
PROBE_STOP_DELTA = 0.05
PLAN_MAX_CONCEPTS = 5
PLAN_MAX_COUPLED = 2
PLAN_ORDER = ("due_reviews", "new_material", "interleaved_siblings")
STEP_MAX_SENTENCES = 5
STEP_QUESTIONS_PER_TURN = 1
LOOP_HISTORY_MAX_MESSAGES = 20
LEARNER_BRIEF_MAX_CHARS = 1800
LEARNER_BRIEF_LAST_CLOSES = 3
LEARNER_BRIEF_TOP_STATES = 5
LEARNER_BRIEF_MAX_MISCONCEPTIONS = 5
# ‡ plain dicts: PKG-07/05 build pydantic_ai UsageLimits(**X) in agents/__init__.py
LOOP_LIMITS = {"request_limit": 14, "tool_calls_limit": 14, "total_tokens_limit": 120_000}
GRADER_LIMITS = {"request_limit": 2, "tool_calls_limit": 0, "total_tokens_limit": 20_000}
GRADER_LOW_CONFIDENCE = 0.6
# Spec §3.4 / §13 A6: below GRADER_SECOND_OPINION_CONFIDENCE, ONE second grader
# call runs on the GRADER_SECOND_OPINION_SLOT model slot (spec §3.5, A22; PKG-05).
GRADER_SECOND_OPINION_CONFIDENCE = 0.4
GRADER_SECOND_OPINION_SLOT = "grader_second"
FEEDBACK_HINT_MAX_SENTENCES = 2  # † PKG-05 grader brief: the hint is short; not a spec value
GRADER_HINT_MAX_CHARS = 300  # † PKG-05 GraderOutput.feedback_hint schema guard; not a spec value
# † PKG-05: the student answer is the one unbounded part of a grader message;
# past this many characters grade() refuses it (`too_long`, spec §13 A33 — the
# length is the student's choice, so never an outage) before any call, so an
# oversized answer is never sent or billed. A size guard on the RAW answer,
# not a token guarantee: at roughly one token per character the answer alone,
# on both requests a run may make, stays under GRADER_LIMITS' token cap, but
# the "> " quote on every answer line (up to 3x for a newline-heavy answer), the
# system prompt, the item fields and multi-token characters ride on top. A run
# that still trips the cap is metered (llm_usage) and comes back unavailable.
GRADER_ANSWER_MAX_CHARS = 4_000
# † PKG-05 numeric gate (A22): float noise at the tolerance edge. An answer
# exactly `tolerance` away in decimal lands a hair either side in binary
# (|0.4 − 0.3| = 0.10000000000000003), so a gap within this relative slack of
# the operands' magnitude still counts as on the edge. Not a spec value: orders
# of magnitude above double-precision error (~1e-16), below any tolerance.
NUMERIC_GATE_EDGE_SLACK = 1e-12
# † PKG-05 reopen (CodeRabbit PR #673; spec §13 A33): the digits in the fresh
# random label each rubric item is shown under in one grading call
# (agents/grader.rubric_labels): the first 2-9, 80,000 labels. Made after the
# answer is submitted and never shown to the student, so no verdict in an answer
# can name one; a label the message's text holds is drawn again, and at this
# length a GRADER_ANSWER_MAX_CHARS answer holds under 5% of them, so a redraw
# stays rare. Not a spec value.
GRADER_RUBRIC_LABEL_CHARS = 5
# † PKG-a33 (grader-guard round a33, the coordinator's ruling; spec §13 A33): a
# credited rubric item needs a quote from the answer (GraderOutput.support) whose
# words in the answer have at least this many letters and digits — or are the
# whole answer, when that is shorter ("12") — before the span check may confirm
# it (learning/answer_guard.support_span). A lone "2/2" or "r1" supports
# nothing; "is 12" and "slope" do. Not a spec value.
GRADER_SUPPORT_MIN_CHARS = 4
# † PKG-a33 (the ruling's re-measure; spec §13 A33): the answer's words behind a
# quote are the longest run of the quote's words that the answer holds, and that
# run must be at least this share of the quote's words (or of a passage the quote
# sets in quotation marks): the student's words inside the grader's own framing
# ("The student's answer says …") count, the reference answer or a paraphrase
# sharing a word or two does not (answer_guard.support_span). Not a spec value.
GRADER_SUPPORT_MIN_SHARE = 0.5
# † PKG-05 reopen (spec §3.4, §13 A33): a refusal is never a skip, and never the
# first answer an honest student loses. The route asks again; the Nth refusal of
# the same item (the tutor's check, PKG-07; the probe, PKG-08) records it as idk.
CHECK_REFUSALS_AS_IDK = 2
LEAK_NGRAM = 6
# † PKG-06 reopen (PKG-07 review round 3, C1(c); fix round 2, n2): strict mode
# folds simple inflections of a WORD answer ("mitochondria" for
# "Mitochondrion"): two alphabetic answer tokens are one lemma when they share
# a stem of at least LEAK_STEM_MIN_CHARS characters that is at least
# LEAK_STEM_MIN_SHARE of the longer word ("less"/"lesson" and "heat"/"heater"
# stay apart) (learning/leak.py `_same_lemma`). Not spec values.
LEAK_STEM_MIN_CHARS = 4
LEAK_STEM_MIN_SHARE = 0.75
# † PKG-06 reopen (PKG-07 fix round 2, N1): in served mode a leak hit inside a
# run of at least this many answer tokens the model copied verbatim from the
# text it was given (and reaching past the hit) is no leak (learning/leak.py
# `_copied_runs`).
LEAK_PROVENANCE_MIN_TOKENS = 3
# † served mode: how far before a hit (characters) answer position is read
LEAK_POSITION_WINDOW_CHARS = 60
CHECK_ITEM_FORMATS = ("free", "teachback", "mc_reason")
CHECK_ITEM_DIFFICULTIES = (1, 2, 3)
# PKG-08 † — engineering choices with no validated cut-point (spec §13 A6 values).
# Difficulty shifts p_known before the §3.1 observation likelihood; LLM-generated
# items carry no calibrated parameters (research §Probe, last sentence).
PROBE_DIFFICULTY_SHIFT: dict[int, float] = {1: 0.15, 2: 0.0, 3: -0.15}
# "repeated idk" (§3.3) given a number.
NOVICE_FLOOR_IDK = 2
# Derived, so no literal repeats the spec's "difficulty 1" or the skill count.
PROBE_EASIEST_DIFFICULTY = min(CHECK_ITEM_DIFFICULTIES)
PROBE_MAX_SKILLS = PROBE_SESSION_CAP // PROBE_ITEMS_PER_SKILL_MIN
# PKG-08 † — per-user calls a minute to /probe/next and GET /plan, the two
# no-model loop routes that write state (services/request_limits sliding window).
PROBE_PLAN_READS_PER_MIN = 30
CHECK_ITEM_MIN_RUBRIC = 2
CHECK_ITEM_MIN_WRONG = 1
MISCONCEPTION_ROLLUP_MIN_USERS = 5
ZPD_RATING_EVERY_N_CHECKS = 30

# ── PKG-04: check items (spec §3.4, §3.5, §13 A6/A22/A23) ─────────────────
# CHECK_ITEM_FORMATS / _DIFFICULTIES / _MIN_RUBRIC / _MIN_WRONG are the §3.4
# rows PKG-01 defines above; this block adds the rest.
CHECK_ITEM_MAX_CHUNKS = 8  # † A6
CHECK_ITEM_MAX_CONCEPTS_PER_DOC = 10  # † A6; per upload — the backfill is uncapped
CHECK_ITEM_OUTPUT_RETRIES = 2  # A6; mirrors agents/note_concepts.py
CHECK_HASH_VERSION = "v1"
CHECK_ITEM_INITIAL_PER_CONCEPT = 9  # † §3.5 = len(FORMATS) x len(DIFFICULTIES)
CHECK_ITEM_CONCEPTS_PER_CALL = 3  # † §3.5
FLEX_TIMEOUT_S = 900  # §3.5; background prefill only
CHECK_ITEM_ANSWER_KINDS = ("free", "numeric")  # §3.5, A22; symbolic/exact deferred (§12)
CHECK_ITEM_STEPWISE_MIN_STEPS = 2  # † A17/A22 "≥ 2 numbered steps"; spec lacks the name
CHECK_ITEM_FLEX_RETRIES = 2  # † A23 "retries on 503/429"; spec lacks the count
CHECK_ITEM_BACKFILL_MIN_CHUNK_SCORE = 1  # † §3.5, A23 relevance floor (backfill only)
CHECK_ITEM_DRAFT_WORKERS = 2  # † upload-time drafting pool; a Flex run holds a thread for minutes
# † bounded redrafting of concepts whose drafts always fail (owner decision A38 low-severity 2)
CHECK_ITEM_REDRAFT_MAX_FAILURES = 3
# † how long a stalled concept stays skipped: past this many days since its
# last recorded failure it is drafted once more (A38 fix round, M2 expiry)
CHECK_ITEM_REDRAFT_FAILURE_TTL_DAYS = 14
# † leak.py (A38 fix round 4): how far back the option rule looks for the
# enumeration a letter continues ("A, B", "b or c") — a letter (or a masked
# "[withheld]"), markup, a separator and markup
LEAK_ENUM_LOOKBACK_CHARS = 26
# † A34 (PKG-06's reopen): the most tokens (checks.answer_tokens) a check item's
# structured final_answer may hold — the decisive core the leak check matches,
# never the whole reference, yet room for a number with its unit, an
# expression, an mc_reason option's text or a teachback claim.
CHECK_ITEM_FINAL_ANSWER_MAX_TOKENS = 20
# † A37: options per mc_reason item — A22's four (A–D). The agent writes them as
# objects; code letters them and places the correct one (checks.lettered_options).
CHECK_ITEM_MC_OPTIONS = 4
# A37 (series coordinator's ruling, 2026-09-28): a generation pass leaves every
# concept it drafted with at least this many stored mc_reason items, or tops it
# up (services/check_item_service.py; agents/check_items_topup.py).
CHECK_ITEM_MC_MIN_PER_CONCEPT = 2
# † focused mc_reason-only top-up calls per concept per pass, each for exactly
# the missing count; a concept still below is left to the next run or backfill.
CHECK_ITEM_MC_TOPUP_CALLS = 1

# ── PKG-06: ZPD policy layer (spec §3.2 / §3.3 / §3.5, §13 A15/A17/A18) ────
# FSRS grade indices (§3.2 rating map). They equal learning.fsrs.Rating
# AGAIN/HARD/GOOD/EASY, which this module cannot import (fsrs imports params);
# tests/test_learning_zpd_policy.py pins the equality. Read by
# policy.evidence_for_rung.
FSRS_RATING_AGAIN = 1
FSRS_RATING_HARD = 2
FSRS_RATING_GOOD = 3
FSRS_RATING_EASY = 4  # never emitted in v1 (§3.2)
# §3.3 band control: "unassisted_next > 0.90 for 2 windows" (the lower edge
# "< 0.65" is PRACTICE_TARGET_LO above).
BAND_CONTROL_HI = 0.90
BAND_CONTROL_STOP_WINDOWS = 2
# §3.3 ceiling: profic "H3 after 2 failed genuine attempts"; develop "H6 after ≥ 2".
CEILING_PROFIC_ESCALATE_FAILS = 2
CEILING_DEVELOP_H6_FAILS = 2
# §3.3 wheelspin, clause 2: "opps ≥ 6 AND unassisted_next < 0.50".
WHEELSPIN_OPPS_EARLY = 6
WHEELSPIN_UNASSISTED_MAX = 0.50
# §3.5 loop tutor context policy (A17/A18) and LOOP_MODEL_TIER (A15).
LOOP_RAG_K_TEACH = 5  # teach-phase RAG k (unchanged from legacy)
LOOP_RAG_K_TEACH_SOFT = 3  # † teach RAG k at the soft (and hard) budget level
LOOP_SOURCE_CHUNKS_MAX = 2  # † the item's own source chunks for hint/feedback turns and H2
LOOP_TIER_DEEP_MIN_FAILS = 2  # LOOP_MODEL_TIER: "≥ 2 failed genuine attempts" → deep
# §6 zpd.* payloads carry ids, counts, enums and bools only (PKG-06 Behaviour
# 10): no payload string is longer than a sha256 question_hash (64 hex chars).
EVENT_PAYLOAD_STR_MAX = 64


def gate_seconds(name: str, scale: float = 1.0) -> float:
    """A `GATE_*` seconds constant times `scale` (spec §13 A5).

    A5 scales every gate by `config.LEARNING_GATE_TIME_SCALE` (default 1.0; the
    E2E lane sets 0.01). This module is stdlib-only and must not import config,
    so the factor is an argument: `learning.gates` threads it from its callers'
    `time_scale=`, and the route layer reads the config value (HANDOFF-06)."""
    value = globals().get(name) if name.startswith("GATE_") else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"gate_seconds: {name!r} is not a GATE_* seconds constant")
    if not (math.isfinite(scale) and scale > 0):
        raise ValueError(f"gate_seconds: scale must be finite and > 0, got {scale!r}")
    return float(value) * scale


# ------------------------------------------------------ §3.1 validity check
def validate_channels(channels: Mapping[str, Mapping[str, float | bool]], t: float) -> None:
    """Raise ValueError unless every channel satisfies spec §3.1 validity.

    G + S < 1 (else the update inverts and correct answers lower belief),
    G <= BKT_G_MAX, S <= BKT_S_MAX, and 0 < t < 1 - S/(1-G) (van de Sande 2013).
    """
    if not 0.0 < t:
        raise ValueError(f"BKT_T must be > 0, got {t}")
    for name, row in channels.items():
        g = float(row["G"])
        s = float(row["S"])
        if not (0.0 < g and 0.0 < s):
            raise ValueError(f"channel {name}: G and S must be > 0, got G={g} S={s}")
        if g + s >= 1.0:
            raise ValueError(f"channel {name}: G + S = {g + s} must be < 1")
        if g > BKT_G_MAX:
            raise ValueError(f"channel {name}: G {g} exceeds BKT_G_MAX {BKT_G_MAX}")
        if s > BKT_S_MAX:
            raise ValueError(f"channel {name}: S {s} exceeds BKT_S_MAX {BKT_S_MAX}")
        t_max = 1.0 - s / (1.0 - g)
        if not t < t_max:
            raise ValueError(f"channel {name}: BKT_T {t} must be < 1 - S/(1-G) = {t_max:.4f}")


validate_channels(CHANNELS, BKT_T)


# PKG-06b (spec §3.5, §13 A20): per-session loop request caps. The counters live in
# sessions.loop_state as ints tutor_requests / deep_requests (PKG-07 maintains them).
LOOP_SESSION_MAX_TUTOR_REQUESTS = 40  # † reaching it = hard (an optimized 10-turn session uses ≈ 7)
LOOP_SESSION_MAX_DEEP_REQUESTS = 6  # † develop/profic: reaching it = soft (deep → standard)
# † novice: reaching it turns novice deep turns into standard (a trailing comment would wrap the name)
LOOP_SESSION_MAX_DEEP_REQUESTS_NOVICE = 12

# ── Loop tutor tiers (PKG-07; spec §3.5, A15/A18) ──────────────────────────
# † deep slot thinking cap; 2.5 Pro cannot go below 128 — never send 0
LOOP_PRO_THINKING_BUDGET = 1024
LOOP_FLASH_THINKING_BUDGET = 0  # standard slot
# † per-run max_tokens = the slot's thinking budget + this (Gemini's max_output_tokens includes thinking)
LOOP_MAX_VISIBLE_TOKENS = 400
# ── Structured loop turn (PKG-07 unblock; learning/turn_shape.py) ──────────
# † sentences allowed in the key_idea field; key idea + body + question stay
# within STEP_MAX_SENTENCES, so the body gets what is left after this and
# STEP_QUESTIONS_PER_TURN
TURN_KEY_IDEA_MAX_SENTENCES = 1
# † body sentence limit by (model) ceiling rung: H0–H1 confirm/pump in one
# sentence, H2–H3 pointer/leading step in two; a rung not listed (H4+) gets
# the remainder, STEP_MAX_SENTENCES − key idea − question
TURN_BODY_MAX_SENTENCES_BY_RUNG = {0: 1, 1: 1, 2: 2, 3: 2}
# † highest rung model text may write before the answer is released: H5
# (H6, the full solution, only once released; turn_shape.validate_turn also
# holds math to plain text below H6 — owner decision A38 06(r))
TURN_MODEL_CEILING_UNRELEASED = 5
# † first rung at which model text may carry an example of its own — H4, the
# isomorph worked example (spec §3.3); below it turn_shape.validate_turn retries
# a math expression the model's inputs never wrote (review round 3)
TURN_OWN_EXAMPLE_MIN_RUNG = 4
# † per-field character caps (LoopTurnOut max_length); together under
# LOOP_MAX_VISIBLE_TOKENS at ~4 characters per token (1340 chars ≈ 335 tokens)
TURN_KEY_IDEA_MAX_CHARS = 200
TURN_BODY_MAX_CHARS = 900
TURN_QUESTION_MAX_CHARS = 240
# ── Item activation and the current concept (PKG-07; spec §3.4, §9, A27) ───
# † served teach turns on the current concept before its next check item is activated
LOOP_TEACH_TURNS_BEFORE_CHECK = 2
# † graded in-session checks per plan concept before the cursor advances
LOOP_CHECKS_PER_CONCEPT = 2
# † target difficulty of an activated check item; select_item falls back to the nearest
LOOP_CHECK_DIFFICULTY_BY_BAND = {"novice": 1, "develop": 2, "profic": 3}
# † Owner decision A38 06(q): update_loop_state's compare-and-set retries after
# the first conflict on sessions.loop_state_rev; exhausted -> LoopStateConflict.
LOOP_STATE_CAS_RETRIES = 3
# † PKG-07 review round 3 (C2): /check/answer grades under a per-item claim in
# loop_state (steps[qh].grading_claim); a claim is never re-taken, so an item
# left claimed (a crash mid-grade, a conflict after the flush) is never graded
# twice. Once its claim is older than this, /check/next treats the item as
# closed and activates the next one (longer than any grader call).
LOOP_GRADING_CLAIM_STALE_S = 120
# ── PKG-09 close + brief (spec §3.4, §3.5, §4, §9, §13 A19/A25) ────────────
CLOSE_PHASES = ("probe", "plan", "teach", "check", "feedback", "close")  # spec §4 CHECK / §9
# † engineering choice, no validated cut-point (PKG-09): one close (summary +
# plan) fits in half a LEARNER_BRIEF_MAX_CHARS brief, so the newest close
# always renders; older closes are cut by the brief's hard bound
CLOSE_SUMMARY_MAX_CHARS = 500
CLOSE_SELF_EVAL_MAX_CHARS = 200  # † engineering choice, no validated cut-point (PKG-09)
CLOSE_IF_THEN_MAX_CHARS = 200  # † engineering choice, no validated cut-point (PKG-09)
# † engineering choice, no validated cut-point (PKG-09): per-turn cap in the close draft
CLOSE_TRANSCRIPT_TURN_MAX_CHARS = 400
# † engineering choice, no validated cut-point (PKG-09): spec §3.5 / §13 A19 —
# the loop history keeps n messages when n < 10, else 10 + (n mod 10) (10–19),
# so the window start moves in blocks and consecutive turns share their prefix
LOOP_HISTORY_TRIM_BLOCK = 10

# ── PKG-12 review surfaces (spec §3.2; † = engineering choice, see HANDOFF-12) ──
REVIEW_SECONDS_PER_FLASHCARD = 15  # † budget cost of one self-rated card
REVIEW_DIFFICULTY_BY_BAND = {"novice": 1, "develop": 2, "profic": 3}  # †
REVIEW_FORMAT_BY_BAND = {"novice": "mc_reason", "develop": "mc_reason", "profic": "free"}  # †
# † engineering choice, no validated cut-point (PKG-09 fix round): the close
# model run's wall-clock bound (flash-lite, one structured request + one retry);
# a timed-out run is the unavailable agent — the deterministic close is stored
CLOSE_RUN_TIMEOUT_S = 20
# † engineering choice (PKG-09 fix round, review M1): a failed learner-brief
# build is retried after this many seconds, not on every loop turn
LEARNER_BRIEF_RETRY_AFTER_S = 300
# † engineering choice (PKG-09 fix round 2): the weakest-nodes fallback of a
# brief built on a loop turn reads this many lowest-mastery course nodes and
# keeps the first LEARNER_BRIEF_TOP_STATES that map to a course concept
LEARNER_BRIEF_CANDIDATE_NODES = 50
