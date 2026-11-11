"""Served text (A38, A84): the leak rung, the ladder's fallback lines and the
`served_*` renderers, `served_model_text` and the items a turn states.
"""
from __future__ import annotations

from learning.ladder import Rung
from learning.leak import detect_leak
from learning.served_scan import ScanSet
from learning.turn_shape import (
    FIELD_JOIN,
    TurnTemplate,
    clamp_model_ceiling,
    labels_new_content,
    render_partial,
    render_turn,
)

from services.loop.constants import _FEEDBACK_ANSWER_LEAD, _FEEDBACK_VERDICT_LINES


# ── The served text (route + tests/evals/loop_tutor.py) ────────────────────


def loop_leak_rung(*, phase: str, rung: Rung, ceiling: Rung, answer_released: bool) -> Rung:
    """The rung model text is served at: H6 once the answer is released, the
    hint rung on a hint turn, else the ceiling — clamped below H6 while the
    answer is unreleased (clamp_model_ceiling: model text never writes H6)."""
    at = rung if phase == "hint" else ceiling
    if answer_released:
        at = Rung.H6
    return Rung(clamp_model_ceiling(at, answer_released))


def released_lead(reference: str) -> str:
    """m1 (review round 3): the stored reference, served FROM CODE above the
    model's released feedback turn — the model is never asked to state or
    compute it, and the turn still ends on its question."""
    return _FEEDBACK_ANSWER_LEAD + (reference or "").strip() + FIELD_JOIN


#: Fix round 2 (N1): what a turn whose model text still leaks after its one
#: retry is served — a fixed, student-facing line per rung (never the
#: model's text with the answer masked in place: the mask's position is itself
#: the signal). Rung by rung it adds no content above the rung's intent.
LADDER_FALLBACK_LINES: dict[int, str] = {
    0: "What will you do next on this item?",
    1: "What is the first thing you need to figure out here?",
    2: "What does your course material say about the idea behind this item?",
    3: "What is the very next step you would take on this item?",
    4: "Which step of the item would you try next?",
    5: "Which part of the item would you fill in next?",
}


#: Fix round 2: the served key idea of an item turn at H0/H1 — those rungs add
#: no content (RUNG_INTENT), so the key idea is the verdict (feedback) or the
#: focus of a hint, from code; recorded model key ideas there stated a
#: definition (judged H2). Spec §13 A121, v2 variant on: a
#: correct-verdict feedback turn serves NO key idea there — the grader's
#: verdict line, served first, says it.
LOW_RUNG_KEY_IDEAS: dict[str, str] = {
    "feedback_correct": "Your answer was graded correct.",
    "hint": "Start by pinning down what the item asks you to find.",
}


def _served_fields(
    out, *, phase: str, rung: Rung, verdict: str | None = None, v2: bool = False
):
    """The structured turn as served (fix round 2). The ladder fixes what the
    lowest rungs may say, so code serves those fields: at an H2 hint the
    question is the ladder's (H2 is a concept pointer: reread the definition —
    recorded model questions named the item's own objects, judged H3); at
    H0/H1 the key idea of a hint or a correct-verdict feedback turn is
    LOW_RUNG_KEY_IDEAS' — or, the v2 variant on (A121), the
    feedback turn's is left out: its verdict line leads the turn. The model
    writes everything else."""
    at = int(rung)
    served = dict(out)
    if phase == "hint" and at == int(Rung.H2) and "question" in out:
        served["question"] = LADDER_FALLBACK_LINES[at]
    if at <= int(Rung.H1) and "key_idea" in out:
        if phase == "hint":
            served["key_idea"] = LOW_RUNG_KEY_IDEAS["hint"]
        elif phase == "feedback" and verdict == "correct":
            served["key_idea"] = "" if v2 else LOW_RUNG_KEY_IDEAS["feedback_correct"]
    return served


def served_template(
    *,
    phase: str,
    rung: Rung,
    poses_check: bool = False,
    answer_check: bool = False,
    v2: bool = False,
    question_text: str | None = None,
) -> TurnTemplate:
    """Spec §13 A121: how this turn is served. Always: no question of its own
    when it poses a check (the card is the one open prompt). With the
    v2 variant on: the "Key idea:" label only on a turn with new
    content (`labels_new_content`: teach or hint at H2+, never feedback), and
    the verdict line first when it answers the reply to the tutor's own
    question. Off, the label is on every turn, exactly as at 7fa9cd0e — the
    rendering every recorded rung judgement was made of. Spec §13 A139:
    `question_text`, a self-explanation prompt code serves in place of the
    model's question (None: the model's, as before)."""
    return TurnTemplate(
        label=labels_new_content(phase, int(rung)) if v2 else True,
        question=not poses_check,
        answer_check=answer_check,
        question_text=question_text,
    )


def served_render(
    out,
    *,
    phase: str,
    rung: Rung,
    verdict: str | None = None,
    poses_check: bool = False,
    answer_check: bool = False,
    v2: bool = False,
    question_text: str | None = None,
) -> str:
    """`render_turn` of the turn as served (`_served_fields`, `served_template`)."""
    return render_turn(
        _served_fields(out, phase=phase, rung=rung, verdict=verdict, v2=v2),
        served_template(
            phase=phase,
            rung=rung,
            poses_check=poses_check,
            answer_check=answer_check,
            v2=v2,
            question_text=question_text,
        ),
    )


def served_partial(
    partial,
    *,
    phase: str,
    rung: Rung,
    verdict: str | None = None,
    poses_check: bool = False,
    answer_check: bool = False,
    v2: bool = False,
    question_text: str | None = None,
) -> str:
    """`render_partial` of a streamed partial as served — the same fields and
    template as `served_render`, so the stream is a prefix of the final text."""
    return render_partial(
        _served_fields(partial, phase=phase, rung=rung, verdict=verdict, v2=v2),
        served_template(
            phase=phase,
            rung=rung,
            poses_check=poses_check,
            answer_check=answer_check,
            v2=v2,
            question_text=question_text,
        ),
    )


def served_lead(*, reference: str, answer_released: bool, verdict: str | None = None) -> str:
    """What code serves ABOVE an item turn's model text: with the answer-verdict
    variant on, a feedback turn's grader verdict as a plain line first (spec
    §13 A121: the turn opens with whether the answer was right, before
    anything else — the hard-level template's own words,
    `_FEEDBACK_VERDICT_LINES`; callers pass `verdict` only then), then the
    released answer (m1, `released_lead`)."""
    lead = _FEEDBACK_VERDICT_LINES[verdict] + FIELD_JOIN if verdict else ""
    return lead + (released_lead(reference) if answer_released else "")


def _item_check_kwargs(
    *,
    reference: str,
    final_answer: str,
    canonical_answer: str | None,
    correct_option: str | None,
    option_text: str | None,
) -> dict:
    return {
        "reference": reference,
        "final_answer": final_answer,
        "canonical_answer": canonical_answer,
        "correct_option": correct_option,
        "option_text": option_text,
        "strict": True,
    }


def served_model_text(
    reply: str,
    *,
    leak_rung: Rung,
    reference: str,
    final_answer: str,
    canonical_answer: str | None = None,
    correct_option: str | None = None,
    option_text: str | None = None,
    answer_released: bool = False,
    given: str = "",
    verdict: str | None = None,
):
    """What the student is served for model-written `reply` against the active
    item. The check is STRICT and in SERVED MODE (`detect_leak(given=…)`,
    fix round 2): a copy of text the model was `given` this turn is no leak,
    and number words / standalone letters count only in answer position. A
    reply that still leaks is NEVER masked in place (N1): it is replaced by the
    rung's LADDER_FALLBACK_LINES line (the model already had its one leak
    retry, `deps.loop_leak`). Code's lead goes in front (`served_lead`): a
    feedback turn's `verdict` line (A121), then the released answer (m1).
    Returns (text, LeakVerdict)."""
    item = _item_check_kwargs(
        reference=reference,
        final_answer=final_answer,
        canonical_answer=canonical_answer,
        correct_option=correct_option,
        option_text=option_text,
    )
    leak_verdict = detect_leak(emitted=reply, rung=leak_rung, given=given, **item)
    text = LADDER_FALLBACK_LINES[int(Rung(leak_rung))] if leak_verdict.leaked else reply
    lead = served_lead(reference=reference, answer_released=answer_released, verdict=verdict)
    return lead + text, leak_verdict


_POSES = "posttest_poses"  # spec §13 A87: the post-test commits when it is opened


# ── Served reveals of OPEN, POSED items (PKG-14, spec §13 A88; A86's scope) ──
# A served tutor turn is never withheld on account of item answers. Its served
# text is scanned (strict served mode) against the items the student has SEEN
# the prompt of and that are still OPEN — the active check item of any open
# loop session, an open review item, an open post-test pose (an item turn's own
# active item excluded: its leak check is the item turn's). Each stated item is
# recorded in learning_reveals (keyed by the student, durable the moment it is
# served — the opener has no session row), so it is never selected again and
# grades with no unassisted credit (`_reveal_floor`). Open items that cannot be
# read leave an 'unscanned' marker: every item posed at or before it grades as
# assisted. A failed write falls back to the session's loop_state.

def stated_items(text: str, items, *, rung: Rung, given: str) -> list[str]:
    """The sorted question hashes of the servable `items` whose answer `text`
    states (strict served mode). An item the check raises on counts as stated
    (fail closed on the evidence side); a non-servable one is skipped. One
    compiled scan (learning.served_scan, spec §13 A101); nothing is a leak at H6."""
    if Rung(rung) >= Rung.H6:
        return []
    return ScanSet.build(items, given=given).stated(text)
