"""The quiz's choices, made by the learner model in code (spec §13 A143,
A144, A147).

Pure: imports only learning.bkt, learning.fsrs, learning.planner and
learning.params (all pure), so it is listed in
tests/test_learning_loop_invariants.py::PURE_MODULES. The service
(services/quiz_learning.py) reads the student's state and hands it in; the
quiz route acts on the answers.

Three choices live here, each behind its own flag:

- **Which concepts the quiz proposes** (A143, flag `quiz_concept_plan`):
  `rank_concepts` orders the student's concepts the way the loop's planner
  does — due reviews first (FSRS due date passed; the DASH overdue triage of
  `fsrs.order_due`), then concepts with an open misconception, then the outer
  fringe (`planner.outer_fringe`: below proficiency, every prerequisite
  proficient), in the planner's own order. A concept whose prerequisites are
  not proficient is not proposed (its weakest prerequisite is, in the
  fringe), and a proficient concept that is not due is left until it is.
- **What each question asks for** (A144, flag `quiz_planned_questions`):
  `question_specs` gives every question its difficulty and at most one
  misconception to target. An explicit difficulty the student asked for is
  theirs; "adaptive" is the band's loop check difficulty (`difficulty_for`).
  The targets are the student's open misconceptions on the concept first,
  then the concept's vetted bank keys, each targeted at most once per quiz.
  The writing model is told exactly this and chooses nothing else.
- **What the results say next** (A147, flag `quiz_results_routing`):
  `skill_changes` lists what moved, in plain words; `next_step` routes the
  student to the review queue when something is due, else to the weakest
  concept they are ready to learn.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from learning import bkt, fsrs, planner
from learning.params import (
    LOOP_CHECK_DIFFICULTY_BY_BAND,
    MISCONCEPTION_KEY_MAX_CHARS,
    QUIZ_DIFFICULTY_NAMES,
    QUIZ_MISCONCEPTION_KEYS_MAX,
    QUIZ_PLAN_MAX_CONCEPTS,
    QUIZ_RESULTS_MIN_CHANGE,
)

#: A misconception key as the store keeps one (learning/misconceptions.py
#: KEY_PATTERN, restated because that module does IO; pinned equal by test).
_KEY = re.compile(rf"[a-z0-9][a-z0-9_]{{0,{MISCONCEPTION_KEY_MAX_CHARS - 1}}}")

#: The request's "let the learner model choose" difficulty (services/
#: quiz_config.py REQUESTED_DIFFICULTIES' fourth value).
ADAPTIVE = "adaptive"

#: Where a planned question's difficulty came from (stored with it).
FROM_REQUEST = "requested"
FROM_LEARNER_MODEL = "learner_model"

#: The formats whose items have distractors a misconception can be tagged on.
_TAGGABLE_FORMATS = ("multiple_choice", "mixed")


def is_key(key: object) -> bool:
    """An identifier-shaped misconception key (snake_case, bounded)."""
    return isinstance(key, str) and _KEY.fullmatch(key) is not None


def key_words(key: str) -> str:
    """A key read as words, for a key no vetted text describes."""
    return key.replace("_", " ")


# ── A144: what each question asks for ──────────────────────────────────────


def difficulty_for(p_known: float) -> str:
    """The quiz difficulty of the band's loop check level
    (LOOP_CHECK_DIFFICULTY_BY_BAND: novice 1, develop 2, profic 3)."""
    return QUIZ_DIFFICULTY_NAMES[LOOP_CHECK_DIFFICULTY_BY_BAND[bkt.band(p_known)] - 1]


@dataclass(frozen=True)
class MisconceptionKey:
    """One misconception a planned quiz may target or tag a distractor with."""

    key: str
    text: str  # what the misconception says, for the writing model
    held: bool  # the student holds it: an open misconception on the concept


def misconception_keys(
    open_keys: Iterable[tuple[str, int]], bank: Iterable[tuple[str, str]]
) -> list[MisconceptionKey]:
    """The keys a planned quiz names, in target order: the student's open
    misconceptions on the concept (most often recorded first, then by key),
    then the concept's vetted bank keys (`check_items.common_wrong`, in the
    bank's order). Identifier-shaped keys only, each once, at most
    QUIZ_MISCONCEPTION_KEYS_MAX. An open key keeps the bank's text when the
    bank has one, else its own words."""
    texts: dict[str, str] = {}
    for key, text in bank:
        if is_key(key) and key not in texts and str(text or "").strip():
            texts[key] = " ".join(str(text).split())
    out: list[MisconceptionKey] = []
    seen: set[str] = set()
    for key, _count in sorted(
        ((k, c) for k, c in open_keys if is_key(k)), key=lambda kc: (-int(kc[1] or 0), kc[0])
    ):
        if key not in seen:
            seen.add(key)
            out.append(MisconceptionKey(key, texts.get(key) or key_words(key), True))
    for key, text in texts.items():
        if key not in seen:
            seen.add(key)
            out.append(MisconceptionKey(key, text, False))
    return out[:QUIZ_MISCONCEPTION_KEYS_MAX]


@dataclass(frozen=True)
class QuestionSpec:
    """What one planned question must be: its 1-based slot, its difficulty
    and the misconception (a key of `misconception_keys`) one of its
    distractors must embody, or None."""

    slot: int
    difficulty: str
    target: str | None = None


def difficulty_source(requested: str) -> str:
    """FROM_REQUEST when the student named a difficulty, else FROM_LEARNER_MODEL."""
    return FROM_LEARNER_MODEL if requested == ADAPTIVE else FROM_REQUEST


def question_specs(
    count: int,
    *,
    requested: str,
    p_known: float,
    keys: Sequence[MisconceptionKey],
    question_format: str,
) -> list[QuestionSpec]:
    """One spec per question. The difficulty is the requested one when the
    student named it, else `difficulty_for(p_known)` for every question.
    Targets go to slots in order, each key once (the held keys come first in
    `keys`); a format with no distractors (a written format) targets none."""
    if count < 1:
        return []
    if requested == ADAPTIVE:
        difficulty = difficulty_for(p_known)
    elif requested in QUIZ_DIFFICULTY_NAMES:
        difficulty = requested
    else:
        raise ValueError(f"unknown quiz difficulty {requested!r}")
    targets = [k.key for k in keys] if question_format in _TAGGABLE_FORMATS else []
    return [
        QuestionSpec(slot, difficulty, targets[slot - 1] if slot <= len(targets) else None)
        for slot in range(1, count + 1)
    ]


# ── A143: which concepts the quiz proposes ─────────────────────────────────

#: Why a concept is proposed, in proposal order.
DUE = "due"
MISCONCEPTION = "misconception"
READY = "ready"
REASONS = (DUE, MISCONCEPTION, READY)


@dataclass(frozen=True)
class ConceptState:
    """One concept of the student's, as the plan reads it."""

    node_id: str
    p_known: float  # decayed at read
    fsrs_s: float | None = None
    fsrs_last_review_at: datetime | None = None
    fsrs_due_at: datetime | None = None
    open_misconceptions: int = 0


@dataclass(frozen=True)
class PlannedConcept:
    node_id: str
    reason: str
    p_known: float
    band: str
    due_at: datetime | None
    open_misconceptions: int


def _due(state: ConceptState, now: datetime) -> bool:
    return state.fsrs_due_at is not None and state.fsrs_due_at <= now


def rank_concepts(
    states: Sequence[ConceptState],
    prereq_edges: Iterable[tuple[str, str]],
    now: datetime,
) -> list[PlannedConcept]:
    """The concepts the quiz proposes, in order (see the module docstring).
    `prereq_edges` are (prerequisite, dependent) pairs among the states'
    nodes. At most QUIZ_PLAN_MAX_CONCEPTS."""
    by_id = {s.node_id: s for s in states}
    due_rows = [
        {
            "node_id": s.node_id,
            "fsrs_s": s.fsrs_s,
            "fsrs_last_review_at": s.fsrs_last_review_at,
        }
        for s in sorted(states, key=lambda s: s.node_id)
        if _due(s, now)
    ]
    order: list[tuple[str, str]] = [(row["node_id"], DUE) for row in fsrs.order_due(due_rows, now)]
    listed = {node for node, _ in order}
    for s in sorted(
        (s for s in states if s.open_misconceptions > 0 and s.node_id not in listed),
        key=lambda s: (-s.open_misconceptions, s.p_known, s.node_id),
    ):
        order.append((s.node_id, MISCONCEPTION))
        listed.add(s.node_id)
    fringe = planner.outer_fringe({s.node_id: s.p_known for s in states}, prereq_edges)
    order.extend((node, READY) for node in fringe if node not in listed)
    return [
        PlannedConcept(
            node_id=node,
            reason=reason,
            p_known=by_id[node].p_known,
            band=bkt.band(by_id[node].p_known),
            due_at=by_id[node].fsrs_due_at,
            open_misconceptions=by_id[node].open_misconceptions,
        )
        for node, reason in order[:QUIZ_PLAN_MAX_CONCEPTS]
    ]


# ── A147: what the results say ─────────────────────────────────────────────

@dataclass(frozen=True)
class SkillChange:
    node_id: str
    before: float
    after: float
    band_before: str
    band_after: str


def skill_changes(
    before: Mapping[str, float], after: Mapping[str, float], order: Sequence[str]
) -> list[SkillChange]:
    """Every node in `order` whose decayed p_known moved by at least
    QUIZ_RESULTS_MIN_CHANGE between the two reads, in `order`'s order (the
    quizzed concept first). A node read on one side only is not listed."""
    out = []
    for node in order:
        if node not in before or node not in after:
            continue
        if abs(after[node] - before[node]) < QUIZ_RESULTS_MIN_CHANGE:
            continue
        out.append(
            SkillChange(node, before[node], after[node], bkt.band(before[node]), bkt.band(after[node]))
        )
    return out


#: The next steps the results can offer.
NEXT_REVIEW = "review"
NEXT_LEARN = "learn"
NEXT_NONE = "none"


@dataclass(frozen=True)
class NextStep:
    kind: str  # NEXT_REVIEW / NEXT_LEARN / NEXT_NONE
    due_count: int  # concepts of the course due for review now
    learn_node_id: str | None  # the weakest concept the student is ready to learn


def weakest_ready(
    p_known: Mapping[str, float], prereq_edges: Iterable[tuple[str, str]]
) -> str | None:
    """The concept with the lowest p_known among the ready ones below
    proficiency (`planner.outer_fringe`'s set), ties by node id; None."""
    fringe = planner.outer_fringe(dict(p_known), prereq_edges)
    if not fringe:
        return None
    return min(fringe, key=lambda n: (p_known[n], n))


def next_step(
    states: Sequence[ConceptState], prereq_edges: Iterable[tuple[str, str]], now: datetime
) -> NextStep:
    """Review what is due when anything in the course is (spaced retrieval
    first, as the loop's plan puts due reviews first); else practise the
    weakest concept the student is ready for in Learn; else nothing. The
    learn target is always named when there is one, so a client without the
    review queue (the learning loop switched off) can offer it instead."""
    due = sum(1 for s in states if _due(s, now))
    learn = weakest_ready({s.node_id: s.p_known for s in states}, prereq_edges)
    if due:
        return NextStep(NEXT_REVIEW, due, learn)
    if learn is not None:
        return NextStep(NEXT_LEARN, 0, learn)
    return NextStep(NEXT_NONE, 0, None)

