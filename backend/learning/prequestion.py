"""The segment prequestion (spec §13 A138, flag `segment_prequestion`). Pure:
loop-state documents and check items in, decisions out — no I/O, no model, no
PKG-06 import (rungs are plain ints), so it sits in PURE_MODULES.

A teaching SEGMENT starts when the plan's cursor lands on a concept whose
teaching has not begun in this session. At that moment, flag on, the student
takes one ungraded guess at a vetted question on the concept ("No idea" is a
full answer), and the next teach turn opens with the correct answer and why —
Pan & Carpenter 2023: prequestions help "provided the correct answer follows".
One per segment, never per step (the audit's "Predict-before-explain works per
segment, not per step"), and one open prompt at a time (A121).

The guess is never graded: no grader call, no evidence, no BKT/FSRS change, no
misconception record, no help-ledger rung, no band-control input. Its item's
answer is revealed (A88's durable record), so the item never serves that
student again as a check, a review or a post-test reserve; and because a
worked answer of the item's exact shape was shown, A76's re-check rule treats
the release like any other (learning/misconceptions.py::recheck_after_release).

The loop_state record (`loop_state["prequestion"][node]`) holds ids, ints,
enums and timestamps only (A38: no free text in loop_state); the guess itself
is stored encrypted in `learning_prequestions` (learning/prequestion_store.py).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from learning.checks import is_servable, posttest_reserves, serve_quality
from learning.params import (
    BAND_DEVELOP_MAX,
    CHECK_ITEM_FORMATS,
    PREQUESTION_DIFFICULTIES,
    PREQUESTION_FORMATS,
    PREQUESTION_MIN_CHECKS_LEFT,
    PREQUESTION_SKIP_REASONS,
)

#: loop_state key: node id → that concept's prequestion record this session.
KEY = "prequestion"

#: Record statuses. `posed`: the card is open. `answered`: the guess is stored
#: and the item revealed; its explanation is owed (the next teach turn serves
#: it). `resolved`: the explanation was served. `skipped`: the segment opened
#: without one (`reason`, PREQUESTION_SKIP_REASONS). `superseded`: the student
#: went on (a chat turn on the concept) while the card was open — nothing was
#: revealed, and the item still never serves as a check in this session.
POSED, ANSWERED, RESOLVED, SKIPPED, SUPERSEDED = "posed", "answered", "resolved", "skipped", "superseded"
STATUSES = (POSED, ANSWERED, RESOLVED, SKIPPED, SUPERSEDED)

#: What the card shows above the question (and the saved pose row leads with).
POSE_LEAD = "Take a guess first — this one isn't scored."
#: The rendered guess rows (the user message the answer route saves).
NO_IDEA_TEXT = "No idea."
GUESS_PREFIX = "My guess: "
#: What code serves above the explaining turn: the correct answer (the model
#: is never asked to state it, A51 m1 — the same lead a released feedback turn has).
ANSWER_LEAD = "The answer: "
#: The explaining turn at the hard budget level, after the answer (no model).
HARD_LEVEL_LINE = "Keep this answer in mind — we'll build on it next."

_QUIZ_ASK_ORIGIN = "quiz_ask"  # services/quiz_ask.QUIZ_ASK_ORIGIN (A99)


def records(state: Mapping[str, Any]) -> dict[str, dict]:
    """The session's records, node id → record (an empty dict when none or malformed)."""
    raw = state.get(KEY)
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, dict)}


def record_for(state: Mapping[str, Any], node_id: str | None) -> dict | None:
    return records(state).get(node_id) if node_id else None


def session_hashes(state: Mapping[str, Any]) -> set[str]:
    """Every item the session posed as a prequestion — excluded from its checks
    from the moment it is posed, whatever became of it."""
    return {r["question_hash"] for r in records(state).values() if isinstance(r.get("question_hash"), str)}


def _plan(state: Mapping[str, Any]) -> dict:
    plan = state.get("plan")
    return plan if isinstance(plan, dict) else {}


def segment_open(state: Mapping[str, Any]) -> str | None:
    """The concept whose segment starts NOW, or None. A segment starts when the
    plan's current concept (a plan that is not done) has seen no teaching yet
    in this session: no served teach turn on it since the cursor arrived
    (`teach_turns`), no graded check (`concept_checks`), no step of it in this
    session (a concept the cursor comes back to after a prerequisite repair has
    steps: its segment resumes, it does not start again), and no prequestion
    record. Never in a quiz-ask session (A99): its surface, the quiz's sheet,
    shows no card, and the quiz question it was opened from was the attempt
    before the explanation."""
    concept = state.get("concept")
    plan = _plan(state)
    if not isinstance(concept, str) or not concept or plan.get("done"):
        return None
    if state.get("origin") == _QUIZ_ASK_ORIGIN:
        return None
    if int(state.get("teach_turns") or 0) or int(state.get("concept_checks") or 0):
        return None
    if state.get("current"):
        return None
    steps = state.get("steps") if isinstance(state.get("steps"), dict) else {}
    if any(isinstance(e, dict) and e.get("node_id") == concept for e in steps.values()):
        return None
    if record_for(state, concept) is not None:
        return None
    return concept


def skip_reason(state: Mapping[str, Any], node_id: str, *, p_known: float) -> str | None:
    """Why the segment opens without a prequestion, decided before any item is
    read (None: go on to the item). In order:
      • `review` — the plan proposed the concept as a due review: its segment is
        retrieval of learned material, not new material, and the prequestion
        effect is for material not yet studied (Pan & Carpenter 2023);
      • `proficient` — the learner model already puts it in the proficient band
        (p_known ≥ BAND_DEVELOP_MAX): §3.3's proficient format is verification
        with elaboration only on request, so an explanation it did not ask for
        would be the opposite of that format;
      • `exam_mode` — a step of this session is in §3.3's exam mode, whose H1 cap
        forbids the released answer the explanation shows.
    A probe answer on the concept earlier in the session does NOT count as the
    segment's prequestion: the probe is placement (A112/A126: its first graded
    answer is the pretest), its items are chosen to measure, its feedback came
    at once inside the probe, and it closed before the plan existed — nothing
    of it points the student's attention at this segment's explanation, which
    is the mechanism Pan & Carpenter describe. Its cost is bounded by
    `choose`'s pool rule (the segment always keeps its checks)."""
    kinds = _plan(state).get("proposed_kinds")
    if isinstance(kinds, dict) and kinds.get(node_id) == "review":
        return "review"
    if p_known >= BAND_DEVELOP_MAX:
        return "proficient"
    steps = state.get("steps") if isinstance(state.get("steps"), dict) else {}
    # PKG-06's rule (policy._fresh_step): a stored exam_mode other than False is exam mode
    if any(isinstance(e, dict) and e.get("exam_mode", False) is not False for e in steps.values()):
        return "exam_mode"
    return None


def choose(items: Iterable, exclude: Iterable[str]) -> tuple[Any | None, str | None]:
    """The concept's prequestion item, or (None, reason). `items` is the
    concept's whole bank (list_items order: created_at, id); `exclude` every
    hash the student may not be served (seen ∪ revealed ∪ reported, this
    session's steps and prequestions — A23, A113).

    The pool is the bank a check could still draw: servable (A34, A124/A123
    holds), not a post-test reserve (A23, A126 — the outcome items stay
    unseen), not excluded, in a check format. A candidate is a pool item in
    PREQUESTION_FORMATS at a PREQUESTION_DIFFICULTIES level. With none:
    `no_item`. With one, the pool must keep PREQUESTION_MIN_CHECKS_LEFT items
    beside it for the segment's graded checks, else `pool_for_checks` — graded
    checks are the only evidence (spec §1), and the guess is a learning
    activity. The choice is deterministic: the format order, then the lower
    difficulty (the picker's own rule), then A129's quality order
    (`serve_quality`: a confirmed key, clean lint, sourced), then the bank's
    age (created_at, id) — select_item's tie-break."""
    bank = list(items)
    reserves = posttest_reserves(bank)
    excluded = set(exclude) | set(reserves)
    pool = [
        i for i in bank
        if i.question_hash not in excluded and i.format in CHECK_ITEM_FORMATS and is_servable(i)
    ]
    candidates = [
        i for i in pool if i.format in PREQUESTION_FORMATS and i.difficulty in PREQUESTION_DIFFICULTIES
    ]
    if not candidates:
        return None, "no_item"
    if len(pool) - 1 < PREQUESTION_MIN_CHECKS_LEFT:
        return None, "pool_for_checks"
    best = min(
        candidates,
        key=lambda i: (
            PREQUESTION_FORMATS.index(i.format),
            PREQUESTION_DIFFICULTIES.index(i.difficulty),
            *serve_quality(i),
            i.created_at or "",
            i.id,
        ),
    )
    return best, None


def pose_record(item, node_id: str, now: float) -> dict:
    """The record a pose writes (ids, ints, an enum and a time only)."""
    return {
        "status": POSED,
        "question_hash": item.question_hash,
        "check_item_id": item.id,
        "format": item.format,
        "difficulty": int(item.difficulty),
        "posed_at": float(now),
    }


def skip_record(reason: str) -> dict:
    if reason not in PREQUESTION_SKIP_REASONS:
        raise ValueError(f"unknown prequestion skip reason {reason!r}")
    return {"status": SKIPPED, "reason": reason}


def option_lines(item) -> list[str]:
    """An mc_reason item's stored options as "A. text" lines (A22: letters and
    texts as stored, never marked correct)."""
    if getattr(item, "format", None) != "mc_reason":
        return []
    return [f"{o.letter}. {o.text}" for o in (getattr(item, "options", None) or [])]


def pose_text(item) -> str:
    """The assistant row the pose is saved as: the lead, the question and, for
    a multiple-choice item, its options. The client's card shows the same
    question and hides this row while the card is open (A135's pattern)."""
    parts = [POSE_LEAD, item.prompt.strip()]
    lines = option_lines(item)
    if lines:
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def pose_payload(item, *, answered: bool = False) -> dict:
    """What the client renders: the question as posed, never the key (A22)."""
    options = None
    if item.format == "mc_reason" and item.options:
        options = [{"letter": o.letter, "text": o.text} for o in item.options]
    payload = {
        "question_hash": item.question_hash,
        "format": item.format,
        "difficulty": int(item.difficulty),
        "prompt": item.prompt,
        "options": options,
        "text": pose_text(item),
    }
    if answered:
        payload["answered"] = True
    return payload


def render_guess(*, no_idea: bool, answer: str = "", option: str | None = None, reason: str = "") -> str:
    """The user row the answer route saves for a guess."""
    if no_idea:
        return NO_IDEA_TEXT
    if option:
        reason = (reason or "").strip()
        return f"{GUESS_PREFIX}{option.strip()}" + (f" — {reason}" if reason else "")
    return GUESS_PREFIX + (answer or "").strip()


def answer_lead(item) -> str:
    """The correct answer, served FROM CODE above the explaining turn (A51 m1:
    the model is never asked to state or compute it). A multiple-choice item's
    lead names its correct option by letter and text; any other item's is its
    stored reference — the lead a released feedback turn serves."""
    if item.format == "mc_reason" and item.correct_option:
        for option in item.options or []:
            if option.letter == item.correct_option:
                return f"{ANSWER_LEAD}{option.letter}. {option.text.strip()}"
    return ANSWER_LEAD + (item.reference_answer or "").strip()


def answered(state: Mapping[str, Any], node_id: str | None) -> dict | None:
    """The concept's record while its explanation is owed (status `answered`)."""
    rec = record_for(state, node_id)
    return rec if rec is not None and rec.get("status") == ANSWERED else None


def open_record(state: Mapping[str, Any], node_id: str | None) -> dict | None:
    """The concept's record while its card is open (status `posed`)."""
    rec = record_for(state, node_id)
    return rec if rec is not None and rec.get("status") == POSED else None


def released_on_node(state: Mapping[str, Any] | None, node_id: str) -> list[dict]:
    """This session's answered or resolved prequestions on `node_id` — each a
    release of its item's answer (A76) — as {shape: (format, difficulty), at}."""
    rec = record_for(state or {}, node_id)
    if rec is None or rec.get("status") not in (ANSWERED, RESOLVED):
        return []
    at = rec.get("answered_at")
    if isinstance(at, bool) or not isinstance(at, (int, float)):
        return []
    return [{"shape": (rec.get("format"), rec.get("difficulty")), "at": float(at)}]
