"""The loop's per-student feature flags (`loop_tutor_v2`, `help_gate_strict`,
`segment_prequestion`, `self_explanation_prompts`), the loop_state keys they
gate, and the server-side `[ACTION: ...]` cues.
"""
from __future__ import annotations

from services.feature_flags import flag_on


#: Spec §13 A121: loop_state key — True when the last SERVED turn ended with the
#: tutor's own open question (a model teach or feedback turn that rendered its
#: question; never a hint, a pose, a template or a turn that posed a check).
#: With the v2 variant on, the next teach-phase chat message is
#: then the student's reply to it, and that turn opens with the verdict
#: (`_LoopTurn._answer_check_due`). Kept with the flag off too, so a student
#: turned on mid-session is judged from the right turn. A flag only: the
#: question's text lives in the (encrypted) message history, never here.
OPEN_QUESTION_KEY = "open_question"


#: Spec §13 A121: the v2 tutor variant's flag (services/feature_flags.py) —
#: every tutor-prompt change that needs a live eval re-record sits behind it.
TUTOR_V2_FLAG = "loop_tutor_v2"


def _tutor_v2_on(user_id: str | None) -> bool:
    """The `loop_tutor_v2` flag for this student (spec §13 A121),
    resolved ONCE per turn by `_LoopTurn._derive` and carried on the turn: it
    picks the prompt and schema variant (`variant_run_args`), the answer check,
    the verdict lines, the label rules and the plan focus, so one turn never
    sees two answers. No student means off; the resolver fails closed
    (feature_flags)."""
    return bool(user_id) and flag_on(TUTOR_V2_FLAG, user_id)


#: Spec §13 A134: the strict genuine-attempt rule's flag (services/feature_flags.py).
HELP_GATE_STRICT_FLAG = "help_gate_strict"


def _help_gate_strict_on(user_id: str | None) -> bool:
    """The `help_gate_strict` flag for this student (spec §13 A134), read once
    per request where it matters: POST /step/attempt counts an attempt by the
    strict rule when on, and POST /hint words its time-alone denial by it. No
    student means off; the resolver fails closed (feature_flags)."""
    return bool(user_id) and flag_on(HELP_GATE_STRICT_FLAG, user_id)


#: Spec §13 A138: the segment prequestion's flag (services/feature_flags.py).
PREQUESTION_FLAG = "segment_prequestion"


#: Spec §13 A139: the self-explanation prompts' flag.
SELF_EXPLAIN_FLAG = "self_explanation_prompts"


def _prequestion_on(user_id: str | None) -> bool:
    """The `segment_prequestion` flag for this student (spec §13 A138), read
    once per request where a segment can start or a prequestion be answered.
    Off: nothing is posed, explained or written. Two reads stay (review item 9):
    A76's release rule and `revealed_hashes` read `learning_prequestions`
    whatever the flag says, because a prequestion answered while it was on
    stays a release and a reveal after it goes off. No student means off; the
    resolver fails closed (feature_flags)."""
    return bool(user_id) and flag_on(PREQUESTION_FLAG, user_id)


def _self_explain_on(user_id: str | None) -> bool:
    """The `self_explanation_prompts` flag for this student (spec §13 A139),
    read once per turn. Off: no juncture is ever a prompt and no
    acknowledgement line is sent."""
    return bool(user_id) and flag_on(SELF_EXPLAIN_FLAG, user_id)


#: Spec §13 A138: the server cue of the turn that explains an answered
#: prequestion (trusted route text, like an [ACTION: …] turn's).
_PREQUESTION_CUE = "[ACTION: The student has just answered the prequestion; explain its answer now.]"


_NO_OPEN_PREQUESTION = "no open prequestion"


_NO_OPEN_SELF_EXPLAIN = "no open self-explanation prompt"


_GUESS_IN_FLIGHT = "your guess is being saved; try again in a moment"


#: Spec §13 A138: the help ledger's / learning_reveals' `source` for a
#: prequestion's pose and reveal (learning.help_ledger.SOURCES)
PREQUESTION_SOURCE = "prequestion"


#: Spec §13 A138 (review fix): the answer claim's keys on the card's record
_ANSWER_CLAIM = "answer_claim"


#: The three "[ACTION: ...]" texts, copied verbatim from routes/learn.py::_action_turn
#: (:1406–1411), where they are a local dict.
_ACTION_PROMPTS = {
    "hint": "The student asked for a hint. Give a small scaffold or clue without giving away the answer.",
    "confused": "The student said they are confused. Identify the likely point of confusion and re-explain with a different analogy.",
    "skip": "The student wants to skip this concept. Acknowledge and transition to the next recommended concept.",
}
