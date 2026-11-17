"""The quiz channel's evidence rules (learning-loop spec §13 A132). Pure: no
I/O, no model; imports learning.evidence, learning.item_lint, learning.params
and (lazily, in `is_idk_answer`) two names of learning.gates only (listed in
tests/test_learning_loop_invariants.py::PURE_MODULES).

The quiz (routes/quiz.py) writes one `mc` Evidence per graded question through
the single writer. Two things ride on that evidence here:

1. The student's stated confidence. The quiz question screen carries A127's
   optional 3-point control ("Guessing" / "Fairly sure" / "Sure"). The answer
   body sends the label; POST /api/quiz/attempts/{id}/answer stores its
   params.STUDENT_CONFIDENCE_LEVELS value in `quiz_responses.confidence` (an
   idk written answer states none); submit puts that value on the question's
   Evidence as `student_confidence` — never a weight, never the grader's
   `confidence` — so the admin's metacognitive calibration (A127 (i)) covers
   the quiz channel. The column is `real` (float4): `stored_label` reads a
   stored value back to its label within float4 precision, so the evidence
   journal and the resume payload carry the exact level, never a float4
   neighbour of it that the calibration report would keep apart.

2. Item quality. Quiz items are written per request by a model and reviewed
   by nobody, so a flawed item's outcome would reach BKT unchecked. Every
   stored question is linted with A113's deterministic linter
   (`learning/item_lint.py`) when its attempt is assembled, the codes kept
   with it (`lint_flags` in the encrypted `questions_json`, never sent to a
   client: a code such as `correct_longest` names where the key is). At submit
   an answer to an item carrying one of EVIDENCE_EXCLUDING_FLAGS is kept out
   of mastery evidence (both outcomes); the quiz's score and what the student
   sees are unchanged.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from learning.evidence import StudentConfidence, stated_confidence
from learning.item_lint import (
    ALL_OR_NONE_OF_ABOVE,
    CORRECT_LONGEST,
    CORRECT_REPEATS_STEM,
    DUPLICATE_OPTIONS,
    LINT_FLAGS,
    NEGATIVE_STEM,
    lint_item,
)
from learning.params import STUDENT_CONFIDENCE_LEVELS

# ── Stated confidence ───────────────────────────────────────────────────────

#: `quiz_responses.confidence` is `real`: a level written as 0.55 can read back
#: as 0.550000011920929 through a cast to double. Seven significant digits
#: separate two float4 values, and the levels are 0.35 apart, so this
#: tolerance names a level exactly and nothing else.
_REAL_TOLERANCE = 1e-6


def stored_label(value: float | None) -> StudentConfidence | None:
    """The label of a stored `quiz_responses.confidence` value: the
    STUDENT_CONFIDENCE_LEVELS level it equals within float4 precision. None
    when none was stated, and for a value no label names (a float written by
    a client before A132, when the body took any number in [0, 1]): that is no
    A127 statement, so it reaches neither the resume nor the evidence."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return next(
        (
            label
            for label, level in STUDENT_CONFIDENCE_LEVELS.items()
            if abs(level - number) <= _REAL_TOLERANCE
        ),
        None,
    )


def evidence_confidence(value: float | None) -> float | None:
    """`Evidence.student_confidence` for a stored response: the exact level
    value of its label (`stored_label`), or None when it states none."""
    return stated_confidence(stored_label(value))


def is_idk_answer(text: str | None) -> bool:
    """A16's idk split for a written quiz answer, the loop route's rule
    (services/loop/claims.py::_is_idk_phrase; parity pinned by test): the text
    holds a gates.IDK_PATTERNS phrase that `gates.non_attempt_phrases`
    returns, so a hedged answer ("idk maybe 7") is an answer, and "idk" is
    none. An idk states no confidence (A127 (c)).

    learning.gates is a PKG-06 module, which the app does not load at boot
    (tests/test_learning_zpd_policy.py's inertness scan and app-load probe):
    these two pure names are imported here, on the first written answer, and
    are the layer's only reach from the quiz (sanctioned there, A132)."""
    from learning.gates import IDK_PATTERNS, non_attempt_phrases

    return any(p in IDK_PATTERNS for p in non_attempt_phrases(text or ""))


# ── Item quality ────────────────────────────────────────────────────────────

#: † Spec §13 A132: the A113 flags that keep a quiz answer out of mastery
#: evidence. Each makes the item's OUTCOME no measurement of the concept:
#: - correct_longest, correct_repeats_stem: a cue finds the key without the
#:   knowledge ("pick the longest", "pick the one that echoes the question").
#:   A correct answer may be the cue, and the quiz has no reason to read (the
#:   loop's selected-response items ask for one, A22), so nothing tells the
#:   two apart;
#: - all_or_none_of_above: an "all of the above" key is found from two true
#:   options, a "none of the above" key names no answer, and the code cannot
#:   tell a key from a distractor;
#: - duplicate_options: two options say one thing, so a student who knows the
#:   answer can pick its twin and be graded wrong, or a twin distractor pair
#:   shrinks the choice the channel's guess parameter assumes.
#: Both outcomes are left out, never only the correct ones: dropping just the
#: answers a cue could have produced would bias every estimate downward.
#: negative_stem COUNTS: its key is unambiguous and uncued, the item still
#: asks for the concept (naming the false statement needs the true ones), and
#: its known cost, a misread negation, is a slip the channel's slip parameter
#: already models.
EVIDENCE_EXCLUDING_FLAGS: frozenset[str] = frozenset(
    {CORRECT_LONGEST, CORRECT_REPEATS_STEM, ALL_OR_NONE_OF_ABOVE, DUPLICATE_OPTIONS}
)
#: The flags whose answers still count (see above). With
#: EVIDENCE_EXCLUDING_FLAGS it partitions item_lint.LINT_FLAGS (pinned by
#: test), so a code the linter gains later fails that test until it is decided.
EVIDENCE_COUNTING_FLAGS: frozenset[str] = frozenset({NEGATIVE_STEM})


def lint_question(question: Mapping) -> list[str]:
    """The A113 flags (LINT_FLAGS order) of one stored quiz question, in its
    stored wire shape: the options' texts in label order and the index of the
    one marked `correct`. A written question (no options) is read for the stem
    rule only, as A113 reads an item without options."""
    options = [o for o in (question.get("options") or []) if isinstance(o, Mapping)]
    correct = next((i for i, o in enumerate(options) if o.get("correct") is True), None)
    return lint_item(
        str(question.get("question") or ""),
        [str(o.get("text") or "") for o in options],
        correct,
    )


def question_lint_flags(question: Mapping) -> list[str]:
    """The flags a stored question carries (`lint_flags`, written when its
    attempt was assembled), or the linter's answer now for a question stored
    without them (an attempt generated before A132): the rule is about the
    item, not about when it was written. A stored value that is not a list of
    known codes is read as absent."""
    stored = question.get("lint_flags")
    if isinstance(stored, list) and all(isinstance(f, str) and f in LINT_FLAGS for f in stored):
        return [f for f in LINT_FLAGS if f in stored]
    return lint_question(question)


def evidence_exclusion(flags: Iterable[str]) -> list[str]:
    """The flags (LINT_FLAGS order) that keep an answer to an item carrying
    `flags` out of mastery evidence; [] means the answer counts."""
    held = set(flags)
    return [f for f in LINT_FLAGS if f in held and f in EVIDENCE_EXCLUDING_FLAGS]


__all__ = [
    "EVIDENCE_COUNTING_FLAGS",
    "EVIDENCE_EXCLUDING_FLAGS",
    "evidence_confidence",
    "evidence_exclusion",
    "is_idk_answer",
    "lint_question",
    "question_lint_flags",
    "stored_label",
]
