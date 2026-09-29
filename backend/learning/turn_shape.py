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

`sentences` is the ONE sentence splitter for the loop: the tutor evals
(tests/evals/loop_tutor.py `_sentences`) should count with it too.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Annotated, Mapping, TypedDict

from pydantic import Field

from learning import params

# Mirrors agents/loop_tutor.py LOOP_PHASES (learning/ may not import agents/).
TURN_PHASES = ("teach", "hint", "feedback")
TURN_FIELDS = ("key_idea", "body", "question")
KEY_IDEA_PREFIX = "Key idea: "
FIELD_JOIN = "\n\n"


class LoopTurnOut(TypedDict, total=False):
    """One structured tutor turn. A TypedDict (not a BaseModel) so pydantic's
    partial validation can parse the streamed output; `total=False` because a
    partial lacks keys — `validate_turn` checks the final one has all three."""

    key_idea: Annotated[
        str,
        Field(
            description=(
                "The one idea this turn teaches, as a single declarative sentence. "
                "No question mark. Rendered after 'Key idea: ' — do not write that label."
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
                "in a single '?'. Never states the answer."
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


def turn_limits(phase: str, ceiling: int, answer_released: bool) -> TurnLimits:
    if phase not in TURN_PHASES:
        raise ValueError(f"unknown loop phase {phase!r}; the model sees {TURN_PHASES}")
    if answer_released and phase != "feedback":
        raise ValueError("answer_released is only meaningful in the feedback phase")
    rung = clamp_model_ceiling(ceiling, answer_released)
    remainder = (
        params.STEP_MAX_SENTENCES
        - params.TURN_KEY_IDEA_MAX_SENTENCES
        - params.STEP_QUESTIONS_PER_TURN
    )
    body = params.TURN_BODY_MAX_SENTENCES_BY_RUNG.get(rung, remainder)
    return TurnLimits(
        ceiling=rung, body_max_sentences=min(body, remainder), latex_ok=answer_released
    )


# ── render / validate ────────────────────────────────────────────────────────


def render_turn(out: Mapping[str, str]) -> str:
    """ "Key idea: {key_idea}\\n\\n{body}\\n\\n{question}" — question always last."""
    missing = [k for k in TURN_FIELDS if k not in out]
    if missing:
        raise ValueError(f"render_turn: missing {missing}")
    key_idea, body, question = (out[k].strip() for k in TURN_FIELDS)
    return FIELD_JOIN.join((KEY_IDEA_PREFIX + key_idea, body, question))


_CONTROL_TAG = re.compile(
    r"\[(LOOP PHASE|VERDICT|CHECK ITEM|ACTION|STUDENT QUESTION|STUDENT MESSAGE|GRAPH CONTEXT)"
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


def _math_atoms(text: str) -> list[str]:
    atoms: list[str] = []
    for m in _MATH_RUN.finditer(text or ""):
        run = m.group().strip(".")
        power = "^" in run and any(c.isdigit() for c in run)
        if (power or _COEFFICIENT.fullmatch(run)) and run not in atoms:
            atoms.append(run)
    return atoms


def invented_math(out: Mapping[str, str], source: str) -> list[str]:
    """The math expressions in the turn that `source` (everything the model was
    given: the prompt, the history, tool results) never wrote — an example or
    exercise of the model's own. Structural provenance, no word list."""
    given = set(_math_atoms(source))
    text = " ".join((out.get(k) or "") for k in TURN_FIELDS)
    return [a for a in _math_atoms(text) if a not in given]


def validate_turn(
    out: Mapping[str, str], limits: TurnLimits, *, source: str | None = None
) -> list[str]:
    """Named problems with a FINAL turn ([] = valid). Codes, "code:detail":
    missing:<field>, control_tag:<field>, latex:<field>,
    question_outside_question:<field>, key_idea_sentences:<n>>max,
    body_sentences:<n>>max, question_shape:<why>, and — when `source` (what
    the model was given) is passed and the model ceiling is below H4, where no
    worked example, isomorph or practice problem is allowed —
    invented_math:<expr,...> (`invented_math`)."""
    problems: list[str] = []
    text = {k: (out.get(k) or "").strip() for k in TURN_FIELDS}
    problems += [f"missing:{k}" for k in TURN_FIELDS if not text[k]]
    for k in TURN_FIELDS:
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
    q = text["question"]
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
        own = invented_math(out, source)
        if own:
            problems.append("invented_math:" + ",".join(own))
    return problems


def render_partial(partial: Mapping[str, str]) -> str:
    """The completed-sentence text of a streamed partial turn, in render order.

    A field counts only once every field before it (render order) has started,
    so out-of-order emission delays text instead of skipping ahead. A field
    followed by a started field is complete; the last started field contributes
    only its completed sentences. Under in-order emission the result is always
    a prefix of `render_turn(final)` and grows monotonically, so the caller can
    send the difference as a delta and flush with `render_turn` at the end."""
    parts: list[str] = []
    for i, key in enumerate(TURN_FIELDS):
        if key not in partial:
            break
        raw = (partial[key] or "").lstrip()
        later_started = any(k in partial for k in TURN_FIELDS[i + 1 :])
        done = raw.rstrip() if later_started else _completed_prefix(raw)
        if done:
            parts.append(KEY_IDEA_PREFIX + done if key == "key_idea" else done)
        if not later_started:
            break
    return FIELD_JOIN.join(parts)
