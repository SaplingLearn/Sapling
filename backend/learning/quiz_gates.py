"""The quiz's item gates and its misconception rules (spec §13 A145, A146).

Pure: imports learning.item_alignment, learning.item_keys, learning.params and
learning.quiz_plan only (all pure), so it is listed in
tests/test_learning_loop_invariants.py::PURE_MODULES. The model calls are the
service's (services/quiz_learning.py); this module turns their answers into
decisions, and reads stored questions.

**The gates (A145, flag `quiz_item_gates`).** A generated quiz question can
become mastery evidence only after the same two checks a loop check item
passes, run on the same agents and prompts:

- the A119 concept check (`agents/check_items_verify.py`): which ONE of the
  course's concepts does the question test? A quiz question has no rubric, so
  part (a) of that check has nothing to judge; part (b) is the quiz's
  alignment question, because the evidence lands on the attempt's concept.
  ALIGNED when the answer is the attempt's concept; MISALIGNED when it is
  another listed concept or none (A119 rejects those too); unverified when no
  complete answer came back.
- the A124 blind key solve (`agents/check_items_solve.py`): solved from the
  question, a multiple-choice item's options under their served labels, and
  the passages the question was written from — never the key or the
  explanation. Compared in code (`key_outcome`): a multiple-choice letter
  exactly (`item_keys.compare`); a written answer by the quiz's own grader,
  the rule a student's answer is graded with (a number or an expression that
  parses and is not accepted is a dispute; a short answer the grader does not
  accept goes to the A124 key match).

`decide` combines them: DROPPED (never served) when the question tests
another concept or none, when the solve disagrees with the key, or when the
passages it was written from do not settle one answer (A124's hold: a held
item is served to no one); VERIFIED (served, evidence-eligible) when it is
aligned and its key agreed; PRACTICE (served, never evidence) otherwise —
no complete verdict, a check unavailable, a solve not independent of the
writer, or no passages to settle an "unsolved" against.

**The tags and the misconception rules (A146, flags
`quiz_planned_questions` and `quiz_misconceptions`).** A planned question's
distractors carry the misconception key the writing model tagged them with,
kept only when it is one of the keys the plan named (`validate_tags`).
`misconception_to_record` is §3.3's stated-confidence branch for a
multiple-choice answer: a distractor tagged with a key, chosen with stated
confidence at or above MISCONCEPTION_CONFIDENCE ("Sure"), on a verified
question. `keys_listed` is what a correct answer to a verified question can
close (A127's "whose item lists the key").
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from learning import item_keys
from learning.item_alignment import NONE, concept_key
from learning.params import MISCONCEPTION_CONFIDENCE
from learning.quiz_plan import is_key

#: A stored question's gate (`questions_json[i]["gate"]`) and an option's tag
#: (`options[j]["misconception"]`): internal keys, never served.
GATE_KEY = "gate"
TAG_KEY = "misconception"
#: A planned question's record of what it was asked for (A144), internal.
PLANNED_KEY = "planned"

# The gate's outcome for one question.
VERIFIED = "verified"  # aligned and its key agreed: served, evidence-eligible
PRACTICE = "practice"  # served, never evidence
DROPPED = "dropped"  # never served, never stored
STATUSES = (VERIFIED, PRACTICE, DROPPED)

# The alignment half.
ALIGNED = "aligned"
MISALIGNED = "misaligned"
ALIGNMENT_UNVERIFIED = "alignment_unverified"

# The key half.
KEY_AGREED = "key_agreed"
KEY_DISPUTED = "key_disputed"
KEY_UNSOLVED = "key_unsolved"
KEY_UNVERIFIED = "key_unverified"
#: The solve would run on the writer's own model: no independent verdict (A124).
KEY_NOT_INDEPENDENT = "key_not_independent"
#: A question stored before the gates (a re-served one) under the gates flag.
NOT_CHECKED = "not_checked"

_MC = "multiple_choice"
_NUMERIC = "numeric"
_SYMBOLIC = "symbolic"
_WRITTEN = ("short_answer", _NUMERIC, _SYMBOLIC)


@dataclass(frozen=True)
class Gate:
    status: str
    alignment: str
    key: str

    def stored(self) -> dict:
        return {"status": self.status, "alignment": self.alignment, "key": self.key}


def item_id(position: int) -> str:
    """The id a question goes under on the checks' ITEM lines (1-based)."""
    return f"q{position}"


def option_rows(question: Mapping) -> tuple[tuple[str, str], ...]:
    """(label, text) of a stored question's options, in served order."""
    return tuple(
        (str(o.get("label") or ""), str(o.get("text") or ""))
        for o in question.get("options") or []
        if isinstance(o, Mapping)
    )


def correct_option(question: Mapping) -> tuple[str, str] | None:
    """(label, text) of the one option marked correct, or None."""
    marked = [
        (str(o.get("label") or ""), str(o.get("text") or ""))
        for o in question.get("options") or []
        if isinstance(o, Mapping) and o.get("correct") is True
    ]
    return marked[0] if len(marked) == 1 else None


def is_multiple_choice(question: Mapping) -> bool:
    return question.get("type") not in _WRITTEN and bool(question.get("options"))


# ── the alignment half (A119 (b)) ───────────────────────────────────────────


def collect_concepts(rows: Iterable[tuple[str, str]]) -> dict[str, str]:
    """The concept check's (item id, concept) rows as one answer per item. An
    item answered twice with two different concepts gets none: a conflict is
    never read as either answer (A119's rule)."""
    seen: dict[str, str] = {}
    conflicted: set[str] = set()
    for item, concept in rows:
        item = str(item).strip()
        if item in seen and _answer_key(seen[item]) != _answer_key(concept):
            conflicted.add(item)
        seen.setdefault(item, str(concept))
    return {item: concept for item, concept in seen.items() if item not in conflicted}


def _answer_key(answer) -> str:
    """item_alignment's spelling forgiveness: quotes and a closing full stop."""
    return concept_key(str(answer or "").strip().strip("\"'“”‘’").rstrip("."))


def alignment_of(answer: str | None, target: str) -> str:
    """ALIGNED when the check named the attempt's concept, MISALIGNED when it
    named any other (another listed concept, `none`, or one not listed: A119
    rejects all three), ALIGNMENT_UNVERIFIED when it gave no answer."""
    if answer is None:
        return ALIGNMENT_UNVERIFIED
    key = _answer_key(answer)
    if key and key == concept_key(target) and key != NONE:
        return ALIGNED
    return MISALIGNED


# ── the key half (A124) ─────────────────────────────────────────────────────


def mc_subject(question: Mapping) -> item_keys.KeySubject | None:
    """A multiple-choice question as A124's comparison reads an mc_reason
    item: the options under their served labels and the key's label."""
    correct = correct_option(question)
    if correct is None:
        return None
    return item_keys.KeySubject(
        format="mc_reason",
        prompt=str(question.get("question") or ""),
        options=option_rows(question),
        answer_kind="free",
        correct_option=correct[0],
        canonical_answer=None,
        tolerance=None,
        final_answer=correct[1],
    )


def key_outcome(
    question: Mapping,
    solved: item_keys.Solved | None,
    *,
    accepted: bool | None = None,
    parsed: bool | None = None,
) -> str:
    """One question's comparison in code: item_keys' AGREE, DISPUTED,
    UNSOLVED, NO_VERDICT or TO_MATCH. A written question's comparison is the
    quiz grader's: `accepted` is whether it accepts the solver's answer,
    `parsed` whether a numeric or symbolic answer parses at all (the caller
    runs services/quiz_grading on both; pure code cannot)."""
    if solved is None:
        return item_keys.NO_VERDICT
    if not solved.solvable:
        return item_keys.UNSOLVED
    if is_multiple_choice(question):
        subject = mc_subject(question)
        return item_keys.compare(subject, solved) if subject else item_keys.NO_VERDICT
    if not solved.answer.strip():
        return item_keys.NO_VERDICT
    if accepted:
        return item_keys.AGREE
    kind = question.get("type")
    if kind in (_NUMERIC, _SYMBOLIC):
        if parsed:
            return item_keys.DISPUTED  # two values the grader compares, and they differ
        return item_keys.NO_VERDICT if kind == _NUMERIC else item_keys.TO_MATCH
    return item_keys.TO_MATCH


def key_of(outcome: str, same: bool | None = None) -> str:
    """The key half's code for a compared question (`same`: the key match's
    answer for a TO_MATCH pair, None when it gave none)."""
    check = item_keys.settle(outcome, same)
    if check.verified:
        return KEY_AGREED
    if check.flag == item_keys.KEY_DISPUTED:
        return KEY_DISPUTED
    if check.flag == item_keys.KEY_UNSOLVED:
        return KEY_UNSOLVED
    return KEY_UNVERIFIED


def decide(alignment: str, key: str, *, grounded: bool) -> Gate:
    """The gate for one question (see the module docstring). `grounded`:
    the question was written from retrieved course passages, which the solve
    read — an "unsolved" then means they do not settle one answer (dropped),
    while without passages it says nothing about the question (practice)."""
    if (
        alignment == MISALIGNED
        or key == KEY_DISPUTED
        or (key == KEY_UNSOLVED and grounded)
    ):
        return Gate(DROPPED, alignment, key)
    if alignment == ALIGNED and key == KEY_AGREED:
        return Gate(VERIFIED, alignment, key)
    return Gate(PRACTICE, alignment, key)


def gate_of(question: Mapping) -> dict | None:
    """A stored question's gate, or None for one stored without (flags off)."""
    gate = question.get(GATE_KEY)
    return gate if isinstance(gate, Mapping) else None


def verified(question: Mapping) -> bool:
    gate = gate_of(question)
    return gate is not None and gate.get("status") == VERIFIED


def evidence_exclusion(question: Mapping) -> list[str]:
    """Why a stored question's answer is no evidence under its gate: [] for a
    question with no gate (every question while the flag is off: unchanged)
    or a verified one; else its gate's codes (the alignment and key halves
    that kept it from VERIFIED)."""
    gate = gate_of(question)
    if gate is None or gate.get("status") == VERIFIED:
        return []
    codes = [
        str(code)
        for code in (gate.get("alignment"), gate.get("key"))
        if code and code not in (ALIGNED, KEY_AGREED)
    ]
    return codes or [NOT_CHECKED]


# ── the tags (A144) and the misconception rules (A146) ──────────────────────


def validate_tags(
    raw: Sequence[str] | None, *, options: int, correct_index: int, allowed: Iterable[str]
) -> list[str | None]:
    """Each option's tag, kept only when it is exactly one of `allowed` (the
    keys the plan named) and the option is a distractor; a tag list whose
    length is not the option count is dropped whole (it cannot be matched to
    the options)."""
    allowed = {k for k in allowed if is_key(k)}
    if raw is None or len(raw) != options:
        return [None] * options
    out: list[str | None] = []
    for i, tag in enumerate(raw):
        tag = str(tag or "").strip()
        out.append(tag if i != correct_index and tag in allowed else None)
    return out


def option_tag(question: Mapping, label: str | None) -> str | None:
    """The tag on the option with this label, or None."""
    for o in question.get("options") or []:
        if isinstance(o, Mapping) and o.get("label") == label:
            tag = o.get(TAG_KEY)
            return tag if is_key(tag) else None
    return None


def misconception_to_record(
    question: Mapping, selected_label: str | None, stated: float | None
) -> str | None:
    """§3.3's stated-confidence branch on a quiz answer: the key of the
    tagged distractor the student chose with stated confidence at or above
    MISCONCEPTION_CONFIDENCE, on a verified multiple-choice question; None
    otherwise. A distractor's tag alone is A22's prior, never a record; the
    student's own "Sure" is what separates a held misconception from a guess
    (the three-tier tests' confidence tier, Hasan et al. 1999)."""
    if not verified(question) or not is_multiple_choice(question):
        return None
    if stated is None or stated < MISCONCEPTION_CONFIDENCE:
        return None
    correct = correct_option(question)
    if correct is None or not selected_label or selected_label == correct[0]:
        return None
    return option_tag(question, selected_label)


def keys_listed(question: Mapping) -> list[str]:
    """The misconception keys a verified question lists: its distractors'
    tags, sorted, each once ([] for an unverified or untagged question)."""
    if not verified(question):
        return []
    return sorted(
        {
            o.get(TAG_KEY)
            for o in question.get("options") or []
            if isinstance(o, Mapping) and is_key(o.get(TAG_KEY)) and o.get("correct") is not True
        }
    )
