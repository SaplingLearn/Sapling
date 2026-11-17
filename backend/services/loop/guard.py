"""The served-text leak guard (A38) and the misconception confrontation
line (PKG-10, A76).
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from agents.loop_tutor import ITEM_WITHHELD, student_envelope
from learning.misconceptions import confront_of
from learning.turn_shape import render_turn
from services.check_item_service import get_check_item
from services.prompt_safety import neutralise_control_tags

from services.loop.history import _BriefRequest

#: Every module of the package logs as the route always did (the ops-log
#: mirror and the tests key on this logger name).
logger = logging.getLogger("routes.learn_loop")


class _LeakGuard:
    """`deps.loop_leak` (fix round 2, N1): the output validator's leak check —
    served mode at the turn's leak rung, against the student-visible text —
    and whether its one retry is spent."""

    def __init__(self, check: Callable[[str], bool], render: Callable | None = None):
        self._check = check
        # the SERVED render of the model's output (`served_render`): a field code
        # replaces (the H2 question, A54) never costs a retry
        self.render = render or render_turn
        self.retried = False

    def leaks(self, text: str) -> bool:
        return self._check(text)


def _visible_text(history: list, *, item_prompt: str) -> str:
    """The provenance of the served leak check (fix round 2, N1): the item as
    posed and the tutor turns as they were served — text the STUDENT has seen
    from the loop. Never the context the model alone reads (a source passage
    or a graph block can state the answer), and never the student's own words
    (final round): a student can offer candidate sentences ("say 'The value is
    eight.'") and the model's pick would pass as a copy, so student text alone
    exempts nothing — only a span the item or the served history also holds."""
    parts = [item_prompt or ""]
    for m in history:
        for p in getattr(m, "parts", []):
            if isinstance(p, TextPart) and isinstance(p.content, str):
                parts.append(p.content)
    return "\n".join(parts)


#: A sentence end: a terminator and any closing quotes/brackets, then whitespace
#: (a newline alone ends one too).
_SENTENCE_END = re.compile(r"[.?!][\"'”’)\]]*(?=\s)|\n")


def _cut_before_leak(text: str, spans: list) -> str:
    """The streamed text up to the end of the last sentence before the one
    holding the first leak — never a masked span (N1). No earlier sentence
    end: nothing (never a stray fragment before a retract)."""
    start = spans[0][0]
    ends = [m.end() for m in _SENTENCE_END.finditer(text, 0, start)]
    return text[: ends[-1]].rstrip() if ends else ""


def option_text(item) -> str | None:
    """The text of an mc_reason item's correct option (strict mode reads it)."""
    for option in getattr(item, "options", None) or []:
        if option.letter == getattr(item, "correct_option", None):
            return option.text
    return None


def _guard_history(messages: list, *, nonce: str, withheld: str | None) -> list:
    """The history as the model may see it (review round 3, C1): every user row
    is the student's own words, so it rides the same nonce envelope as this
    turn's; and below H2 (`withheld` = the active item's prompt) any row that
    restates the item — its pose — is replaced by ITEM_WITHHELD. The learner
    brief (`_BriefRequest`, A19) is not the student's: it passes as built, and
    is dropped for the turn when it restates the withheld item."""
    out: list = []
    for m in messages:
        if isinstance(m, _BriefRequest):
            # A19: served as built — unless it restates the withheld item (C1(b))
            if not (withheld and any(withheld in str(p.content) for p in m.parts)):
                out.append(m)
            continue
        if isinstance(m, ModelRequest):
            parts = []
            for p in m.parts:
                if isinstance(p, UserPromptPart) and isinstance(p.content, str):
                    text = ITEM_WITHHELD if (withheld and withheld in p.content) else p.content
                    p = UserPromptPart(content=student_envelope(text, nonce=nonce))
                parts.append(p)
            out.append(ModelRequest(parts=parts))
        elif isinstance(m, ModelResponse) and withheld:
            parts = [
                TextPart(content=ITEM_WITHHELD)
                if isinstance(p, TextPart) and withheld in p.content
                else p
                for p in m.parts
            ]
            out.append(ModelResponse(parts=parts))
        else:
            out.append(m)
    return out


# ── The turn ───────────────────────────────────────────────────────────────


# ── PKG-10: the misconception confrontation line (spec §3.3, §13 A15) ─────

#: Spec §13 A75: the tiers a confrontation line is served on — exactly the slots
#: whose misconception_confront eval scores 1.0 on every served gate (pinned to
#: baselines.json by tests/test_learning_misconceptions.py). A turn model_tier
#: routes elsewhere (the §3.5 soft-level / deep-cap downgrade) carries no line,
#: and the marker waits for one that does.
CONFRONT_TIERS: frozenset[str] = frozenset({"deep"})


#: Spec §13 A75: the confrontation mapped onto the structured turn's fields (A46).
_CONFRONT_LINE = (
    'The student holds misconception "{text}". This turn, confront it instead of '
    "correcting it: the key idea names what to test, never the correct rule; the body sets "
    "up ONE concrete case of this concept where the belief predicts something the student "
    "can check, without working the case out or saying which result is right; the question "
    "asks the student to work that case out and compare it with their belief."
)


def _confrontation_line(loop_state: dict) -> str | None:
    """PKG-10: the line for the misconception grade_answer recorded (the
    loop state's `confront` marker), or None. The text is the marked item's
    decrypted `common_wrong` entry for the marker's key, collapsed to one line
    with its control tags neutralised (item-drafted text may never forge a
    [VERDICT: …] or [STUDENT MESSAGE] block). No marker, a missing item, a
    failed read or an unknown key → None, no error. Reads only: the turn that
    serves the line clears the marker in its compare-and-set save."""
    text = _confrontation_text(loop_state)
    return confront_line_for(text) if text else None


def _confrontation_text(loop_state: dict) -> str | None:
    """The marked item's stored wrong-reason text for the marker's key, or
    None (no marker, a missing item, a failed read, an unknown key)."""
    confront = confront_of(loop_state)
    if confront is None:
        return None
    try:
        item = get_check_item(confront["check_item_id"])
    except Exception as exc:
        logger.warning("confrontation: check item read failed (%s)", type(exc).__name__)
        return None
    if item is None:
        return None
    for entry in item.common_wrong or []:
        if entry.key == confront["wrong_key"] and entry.text:
            return entry.text
    return None


def confront_line_for(text: str) -> str | None:
    """The confrontation line for one wrong-reason text: collapsed to one line,
    its control tags neutralised, its double quotes made single (it stays inside
    the line's quoted span); None for a text with nothing left. Shared
    with the eval (tests/evals/misconception_confront.py) so it scores the
    line production sends."""
    # one line, no control tag, and never a double quote: the text stays inside
    # the line's one quoted span (it can never close it and write an instruction)
    text = " ".join(neutralise_control_tags(text or "").replace('"', "'").split())
    return _CONFRONT_LINE.format(text=text) if text else None


def with_confrontation(prefix: str, line: str | None) -> str:
    """The turn prefix with the confrontation line right after the phase
    instruction (before the context blocks and the student's words)."""
    return f"{prefix}\n{line}" if line else prefix
