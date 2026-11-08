"""The loop tutor's structured turn (spec §3.3/§3.4; PKG-07 unblock S1). Pure:
stdlib, pydantic types and learning.params only (invariant 2) — no LLM, no
I/O. Rungs are plain ints (Rung is an IntEnum): importing learning.ladder here
would make this module a PKG-06 importer, which the inertness scan
(tests/test_learning_zpd_policy.py) allows only on the loop route.

The tutor returns a `LoopTurnOut` (key idea, body, question) instead of free
text, so the spec §3.4 turn bound holds by construction: `render_turn` puts the
question last (feedback never ends on the answer), `turn_limits` sizes the body
by the ceiling rung, and `validate_turn` names what a FINAL output got wrong.
`render_partial` turns a streamed partial into the completed-sentence prefix
for SSE deltas (a later step strips leaks on the cumulative text).

Spec §13 A121 (the turn template): code, not the model, decides three things
per turn and `TurnTemplate` carries them to the render. The "Key idea:" label
marks only a turn that brings new content (`labels_new_content`: a teach or
hint turn at H2 or above, where RUNG_INTENT first allows content); a turn that
poses a check ends without a question of its own (the check card is its one
open prompt); and a teach turn answering the student's reply to the tutor's
own question opens with the plain verdict line (`ANSWER_VERDICT_LEADS`, from
the model's `answer_verdict` field) before anything else.

`sentences` is the ONE sentence splitter for the loop: the tutor evals
(tests/evals/loop_tutor.py `_sentences`) should count with it too.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Annotated, Literal, Mapping, TypedDict, get_args

from pydantic import Field

from learning import params

# Mirrors agents/loop_tutor.py LOOP_PHASES (learning/ may not import agents/).
TURN_PHASES = ("teach", "hint", "feedback")
TURN_FIELDS = ("key_idea", "body", "question")
KEY_IDEA_PREFIX = "Key idea: "
FIELD_JOIN = "\n\n"

#: Spec §13 A121: the tutor's judgement of the student's reply to the question
#: its previous turn asked — asked for only on such a turn (the phase block's
#: [ANSWER CHECK] line), and only ever about the tutor's own question.
ANSWER_VERDICT_FIELD = "answer_verdict"
AnswerVerdict = Literal["correct", "partly_correct", "incorrect", "not_an_answer"]
ANSWER_VERDICTS: tuple[str, ...] = get_args(AnswerVerdict)
#: The plain line the turn opens with, from code (A121). `not_an_answer` (the
#: reply asked something else, or said "I don't know") opens with none.
ANSWER_VERDICT_LEADS: dict[str, str] = {
    "correct": "That's right.",
    "partly_correct": "That's partly right.",
    "incorrect": "Not quite.",
}

#: Spec §13 A121: the session opener while the session is in the probe phase —
#: a template, never a model turn: a neutral welcome and the check-in's intro.
#: It teaches nothing and asks nothing (the check-in's first question follows it).
LOOP_PROBE_OPENER = (
    "Welcome! We'll start with a quick check-in to see where you are, then plan "
    "your session together."
)
#: The same opener for a course with no check items: its probe ends at once and
#: the plan follows (routes/learn_loop.py::probe_next, `no_check_items`).
LOOP_PLAN_OPENER = (
    "Welcome! This course has no check-in questions yet, so we'll go straight to "
    "planning your session."
)


@dataclass(frozen=True)
class TurnTemplate:
    """How one structured turn is served (spec §13 A121); code decides each.

    `label`: the key idea carries "Key idea: " (a turn with new content only).
    `question`: the model's question closes the turn — False on a turn that
    poses a check, whose card is the one open prompt. `answer_check`: the turn
    answers the student's reply to the tutor's own question, so the model's
    `answer_verdict` leads it as a plain line (and then no label: one lead)."""

    label: bool = True
    question: bool = True
    answer_check: bool = False


DEFAULT_TEMPLATE = TurnTemplate()


def labels_new_content(phase: str, rung: int) -> bool:
    """Spec §13 A121: whether a model turn served at `rung` brings new content —
    a teach or hint turn at TURN_NEW_CONTENT_MIN_RUNG (H2, the concept pointer)
    or above. H0/H1 add no content by definition (ladder.RUNG_INTENT), and a
    feedback turn relays a verdict: neither carries the "Key idea:" label."""
    return phase in ("teach", "hint") and int(rung) >= params.TURN_NEW_CONTENT_MIN_RUNG


def verdict_lead(out: Mapping[str, str], template: TurnTemplate) -> str:
    """The plain verdict line an answer-check turn opens with ("" when none)."""
    if not template.answer_check:
        return ""
    return ANSWER_VERDICT_LEADS.get(str(out.get(ANSWER_VERDICT_FIELD) or "").strip(), "")


class LoopTurnOut(TypedDict, total=False):
    """One structured tutor turn. A TypedDict (not a BaseModel) so pydantic's
    partial validation can parse the streamed output; `total=False` because a
    partial lacks keys — `validate_turn` checks the final one has what its
    `TurnLimits` require. `answer_verdict` comes first: on the turn that asks
    for it, it is the line the student reads first (A121)."""

    answer_verdict: Annotated[
        AnswerVerdict,
        Field(
            description=(
                "ONLY when the phase block has an [ANSWER CHECK] line, and then first: "
                "your verdict on the student's reply to the question your previous turn "
                "asked — correct, partly_correct, incorrect, or not_an_answer when the "
                "reply does not try to answer it. The system shows it to the student first. "
                "Leave this key out on every other turn."
            ),
        ),
    ]
    key_idea: Annotated[
        str,
        Field(
            description=(
                "The one idea this turn teaches, as a single declarative sentence. "
                "No question mark and no label: the system adds 'Key idea: ' only on a "
                "turn that brings new content."
            ),
            max_length=params.TURN_KEY_IDEA_MAX_CHARS,
        ),
    ]
    body: Annotated[
        str,
        Field(
            description=(
                "The explanation, within the turn's sentence limit. No question mark; "
                "plain-text math (x^2, (a+b)/c), no LaTeX unless the answer is released."
            ),
            max_length=params.TURN_BODY_MAX_CHARS,
        ),
    ]
    question: Annotated[
        str,
        Field(
            description=(
                "Exactly one question for the student's next step: one sentence ending "
                "in a single '?'. Never states the answer. Empty (\"\") only when the "
                "phase block says a check question follows this turn."
            ),
            max_length=params.TURN_QUESTION_MAX_CHARS,
        ),
    ]


# ── the shared sentence splitter ─────────────────────────────────────────────

# A boundary is a run of terminators (plus closing quotes/brackets) followed by
# whitespace or the end of the text, or a blank line. Requiring whitespace
# after the terminator keeps "3.14" one sentence. A period that closes one of
# these abbreviations is not a boundary (so "e.g. meters" does not split; an
# abbreviation that really ends a sentence merges it with the next — the
# lenient direction). Deliberately simple: no initials, no "No.".
_BOUNDARY = re.compile(r"[.!?]+[\"'”’)\]]*(?=\s|$)|\n[ \t]*\n")
_ABBREVIATIONS = frozenset(
    {
        "e.g.",
        "i.e.",
        "etc.",
        "vs.",
        "cf.",
        "approx.",
        "dr.",
        "mr.",
        "mrs.",
        "ms.",
        "prof.",
        "fig.",
        "eq.",
    }
)


def _boundaries(text: str) -> list[tuple[int, int]]:
    """(end of sentence, start of the gap) for each sentence boundary."""
    out: list[tuple[int, int]] = []
    for m in _BOUNDARY.finditer(text):
        if m.group(0).startswith("\n"):
            out.append((m.start(), m.end()))
            continue
        head = text[: m.end()].split()
        token = head[-1].lstrip("([\"'“‘").lower() if head else ""
        if m.group(0) == "." and token in _ABBREVIATIONS:
            continue
        out.append((m.end(), m.end()))
    return out


def sentences(text: str) -> list[str]:
    """Split `text` into stripped, non-empty sentences. "?" and "!" end a
    sentence, "." does unless it is inside a number or closes a listed
    abbreviation, and a blank line ends one too."""
    parts: list[str] = []
    start = 0
    for end, gap in _boundaries(text):
        parts.append(text[start:end])
        start = gap
    parts.append(text[start:])
    return [p.strip() for p in parts if p.strip()]


def _completed_prefix(text: str) -> str:
    """The prefix of `text` up to its last boundary that more text cannot
    move: one followed by whitespace (a terminator at the very end may still
    grow into "3.14" or "e.g.")."""
    done = 0
    for end, _gap in _boundaries(text):
        if end < len(text):
            done = end
    return text[:done].rstrip()


# ── limits ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TurnLimits:
    ceiling: int  # the MODEL ceiling rung (clamp_model_ceiling applied)
    body_max_sentences: int
    latex_ok: bool
    # Spec §13 A121: False when the turn poses a check — its question is never
    # served, so validation neither requires nor judges it
    question: bool = True
    # Spec §13 A121: the turn must carry a valid `answer_verdict`
    answer_check: bool = False


def clamp_model_ceiling(ceiling: int, answer_released: bool) -> int:
    """Model text never writes H6 (a full solution) unless the answer is
    released; below that the model's ceiling is at most H5
    (TURN_MODEL_CEILING_UNRELEASED). Returns a plain int rung: a
    learning.ladder.Rung is an IntEnum, so it compares equal and Rung(result)
    converts back."""
    rung = int(ceiling)
    if not 0 <= rung <= params.LADDER_MAX_RUNG:
        raise ValueError(f"ceiling {ceiling!r} outside H0..H{params.LADDER_MAX_RUNG}")
    return rung if answer_released else min(rung, params.TURN_MODEL_CEILING_UNRELEASED)


def turn_limits(
    phase: str,
    ceiling: int,
    answer_released: bool,
    *,
    question: bool = True,
    answer_check: bool = False,
) -> TurnLimits:
    """`question=False`: the turn poses a check (no question of its own, A121);
    `answer_check=True`: a teach turn answering the reply to the tutor's own
    question (A121) — both only in teach, the one phase whose turns do either."""
    if phase not in TURN_PHASES:
        raise ValueError(f"unknown loop phase {phase!r}; the model sees {TURN_PHASES}")
    if answer_released and phase != "feedback":
        raise ValueError("answer_released is only meaningful in the feedback phase")
    if (answer_check or not question) and phase != "teach":
        raise ValueError("only a teach turn poses a check or answers a reply to its question")
    rung = clamp_model_ceiling(ceiling, answer_released)
    remainder = (
        params.STEP_MAX_SENTENCES
        - params.TURN_KEY_IDEA_MAX_SENTENCES
        - params.STEP_QUESTIONS_PER_TURN
    )
    body = params.TURN_BODY_MAX_SENTENCES_BY_RUNG.get(rung, remainder)
    return TurnLimits(
        ceiling=rung,
        body_max_sentences=min(body, remainder),
        latex_ok=answer_released,
        question=question,
        answer_check=answer_check,
    )


# ── render / validate ────────────────────────────────────────────────────────


def render_turn(out: Mapping[str, str], template: TurnTemplate = DEFAULT_TEMPLATE) -> str:
    """The served turn, in this order (spec §13 A121): the plain verdict line on
    an answer-check turn; the key idea, labelled "Key idea: " only when
    `template.label` and no verdict line leads; the body; the question — always
    last, and absent when the turn poses a check. The default template is the
    original "Key idea: {key_idea}\\n\\n{body}\\n\\n{question}". An empty key
    idea is left out (code serves none at an H0/H1 correct-verdict feedback)."""
    required = ("key_idea", "body") + (("question",) if template.question else ())
    missing = [k for k in required if k not in out]
    if missing:
        raise ValueError(f"render_turn: missing {missing}")
    lead = verdict_lead(out, template)
    key_idea = (out.get("key_idea") or "").strip()
    parts = [lead] if lead else []
    if key_idea:
        parts.append((KEY_IDEA_PREFIX if template.label and not lead else "") + key_idea)
    parts.append((out.get("body") or "").strip())
    if template.question:
        parts.append((out.get("question") or "").strip())
    return FIELD_JOIN.join(parts)


_CONTROL_TAG = re.compile(
    r"\[(LOOP PHASE|VERDICT|ANSWER CHECK|CHECK ITEM|ACTION|STUDENT QUESTION|STUDENT MESSAGE"
    r"|GRAPH CONTEXT)"
    r"|<<(?:end_)?student_text"
)
# A backslash macro (\frac, \cdot), a \( or \[ math delimiter, or $…$ inline math.
_LATEX = re.compile(r"\\[A-Za-z]+|\\[(\[]|\$[^$\n]+\$")


# A math expression of the model's own (review round 3): a run of letters,
# digits, "^" and "." that is a power with a digit ("x^3", "3x^2", "n^2") or a
# coefficient on a one-letter variable ("2x", "0.5n"). Letters-only notation
# ("x^n", "n*x^(n-1)" splits into "x^", "n", "1") and chemical formulas
# ("H2O") are not expressions of this kind.
_MATH_RUN = re.compile(r"[A-Za-z0-9^.]+")
_COEFFICIENT = re.compile(r"[0-9]+(?:\.[0-9]+)?[a-z]")
# A coefficient is math only beside an operator ("2x + 3", "(2x)"), never in
# prose ("3d printing", "5s to load") — fix round 2.
_OPERATORS = frozenset("+-*/=()<>^")


def _beside_operator(text: str, start: int, end: int) -> bool:
    before = text[:start].rstrip()
    after = text[end:].lstrip()
    return bool((before and before[-1] in _OPERATORS) or (after and after[0] in _OPERATORS))


def _math_atoms(text: str, *, in_context: bool = True) -> list[str]:
    """Powers with a digit, and — beside an operator (`in_context`; every one
    when reading the given text, whose copies are all allowed) — coefficients."""
    atoms: list[str] = []
    text = text or ""
    for m in _MATH_RUN.finditer(text):
        run = m.group().strip(".")
        power = "^" in run and any(c.isdigit() for c in run)
        coefficient = bool(_COEFFICIENT.fullmatch(run)) and (
            not in_context or _beside_operator(text, m.start(), m.end())
        )
        if (power or coefficient) and run not in atoms:
            atoms.append(run)
    return atoms


def invented_math(
    out: Mapping[str, str], source: str, fields: tuple[str, ...] = TURN_FIELDS
) -> list[str]:
    """The math expressions in the turn's served `fields` that `source`
    (everything the model was given: the prompt, the history, tool results)
    never wrote — an example or exercise of the model's own. Structural
    provenance, no word list."""
    given = set(_math_atoms(source, in_context=False))
    text = " ".join((out.get(k) or "") for k in fields)
    return [a for a in _math_atoms(text) if a not in given]


def validate_turn(
    out: Mapping[str, str], limits: TurnLimits, *, source: str | None = None
) -> list[str]:
    """Named problems with a FINAL turn ([] = valid). Codes, "code:detail":
    missing:<field>, control_tag:<field>, latex:<field>,
    question_outside_question:<field>, key_idea_sentences:<n>>max,
    body_sentences:<n>>max, question_shape:<why>, answer_verdict:<why>, and —
    when `source` (what the model was given) is passed and the model ceiling
    is below H4, where no worked example, isomorph or practice problem is
    allowed — invented_math:<expr,...> (`invented_math`).

    Spec §13 A121: on a turn that poses a check (`limits.question` False) the
    question is never served, so it is neither required nor judged; on an
    answer-check turn `answer_verdict` must be one of ANSWER_VERDICTS (it is
    ignored on every other turn — code never serves it there)."""
    problems: list[str] = []
    served = TURN_FIELDS if limits.question else ("key_idea", "body")
    text = {k: (out.get(k) or "").strip() for k in TURN_FIELDS}
    if limits.answer_check:
        verdict = str(out.get(ANSWER_VERDICT_FIELD) or "").strip()
        if verdict not in ANSWER_VERDICTS:
            problems.append(f"answer_verdict:{verdict or 'missing'}")
    problems += [f"missing:{k}" for k in served if not text[k]]
    for k in served:
        if _CONTROL_TAG.search(text[k]):
            problems.append(f"control_tag:{k}")
        if not limits.latex_ok and _LATEX.search(text[k]):
            problems.append(f"latex:{k}")
    for k in ("key_idea", "body"):
        if "?" in text[k]:
            problems.append(f"question_outside_question:{k}")
    n_key = len(sentences(text["key_idea"]))
    if n_key > params.TURN_KEY_IDEA_MAX_SENTENCES:
        problems.append(f"key_idea_sentences:{n_key}>{params.TURN_KEY_IDEA_MAX_SENTENCES}")
    n_body = len(sentences(text["body"]))
    if n_body > limits.body_max_sentences:
        problems.append(f"body_sentences:{n_body}>{limits.body_max_sentences}")
    q = text["question"] if limits.question else ""
    if q:
        n_q = len(sentences(q))
        marks = q.count("?")
        if n_q != 1:
            problems.append(f"question_shape:{n_q} sentences")
        elif marks != params.STEP_QUESTIONS_PER_TURN or not q.endswith("?"):
            problems.append(f"question_shape:{marks} '?', ends {q[-1]!r}")
    if (
        source is not None
        and limits.ceiling < params.TURN_OWN_EXAMPLE_MIN_RUNG
        and not limits.latex_ok
    ):
        own = invented_math(out, source, served)
        if own:
            problems.append("invented_math:" + ",".join(own))
    return problems


def render_partial(partial: Mapping[str, str], template: TurnTemplate = DEFAULT_TEMPLATE) -> str:
    """The completed-sentence text of a streamed partial turn, in render order.

    A field counts only once every field before it (render order) has started,
    so out-of-order emission delays text instead of skipping ahead. A field
    followed by a started field is complete; the last started field contributes
    only its completed sentences. Under in-order emission the result is always
    a prefix of `render_turn(final, template)` and grows monotonically, so the
    caller can send the difference as a delta and flush with `render_turn` at
    the end.

    Spec §13 A121: an answer-check turn renders `answer_verdict` first, and its
    line only once a later field has started (the value is then whole); a turn
    that poses a check never renders its question, though a started question
    still completes the body before it."""
    order = ((ANSWER_VERDICT_FIELD,) if template.answer_check else ()) + TURN_FIELDS
    parts: list[str] = []
    lead = ""
    for i, key in enumerate(order):
        if key not in partial:
            break
        later_started = any(k in partial for k in order[i + 1 :])
        if key == ANSWER_VERDICT_FIELD:
            if not later_started:
                break
            lead = verdict_lead(partial, template)
            if lead:
                parts.append(lead)
            continue
        if key == "question" and not template.question:
            break
        raw = (partial[key] or "").lstrip()
        done = raw.rstrip() if later_started else _completed_prefix(raw)
        if done:
            label = key == "key_idea" and template.label and not lead
            parts.append(KEY_IDEA_PREFIX + done if label else done)
        if not later_started:
            break
    return FIELD_JOIN.join(parts)
