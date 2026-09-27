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
# wheelspin opps>=6 arm) are unnamed in spec §3.3; PKG-06 names them here.

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
GRADER_SECOND_OPINION_CONFIDENCE = 0.4  # spec §3.4 / §13 A6 — below this, ONE second grader call on slot grader_second (A22)
LEAK_NGRAM = 6
CHECK_ITEM_FORMATS = ("free", "teachback", "mc_reason")
CHECK_ITEM_DIFFICULTIES = (1, 2, 3)
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
