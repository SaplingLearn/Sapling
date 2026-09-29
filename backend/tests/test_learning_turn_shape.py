"""learning/turn_shape.py — the loop tutor's structured turn (PKG-07 unblock S1).

Pure: no LLM, no I/O. The shape makes the spec §3.4 turn bound (at most
STEP_MAX_SENTENCES sentences, exactly STEP_QUESTIONS_PER_TURN question, a
`Key idea:` line, question last) true by construction instead of by prompt.
"""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from learning import params
from learning.ladder import Rung
from learning.turn_shape import (
    LoopTurnOut,
    TurnLimits,
    clamp_model_ceiling,
    render_partial,
    render_turn,
    sentences,
    turn_limits,
    validate_turn,
)

GOOD: LoopTurnOut = {
    "key_idea": "The derivative measures an instantaneous rate of change.",
    "body": "Look at how the slope behaves near the point.",
    "question": "What happens to the secant slope as h shrinks?",
}


def _codes(problems: list[str]) -> set[str]:
    return {p.split(":", 1)[0] for p in problems}


# ── sentences ────────────────────────────────────────────────────────────────


def test_sentences_decimal_safe():
    assert sentences("Pi is about 3.14 here. Next one.") == ["Pi is about 3.14 here.", "Next one."]
    assert sentences("Use 0.5 m/s. Then 2.75 s.") == ["Use 0.5 m/s.", "Then 2.75 s."]


def test_sentences_question_and_exclamation_end_sentences():
    assert sentences("Nice! Why? Because.") == ["Nice!", "Why?", "Because."]


def test_sentences_abbreviations_do_not_split():
    assert sentences("Use a unit, e.g. meters. Then i.e. seconds vs. minutes.") == [
        "Use a unit, e.g. meters.",
        "Then i.e. seconds vs. minutes.",
    ]


def test_sentences_blank_line_is_a_boundary_and_blank_text_is_empty():
    assert sentences("Key idea: slope\n\nLook closer.") == ["Key idea: slope", "Look closer."]
    assert sentences("   ") == []
    assert sentences("No terminator") == ["No terminator"]


def test_sentences_closing_quote_stays_with_its_sentence():
    assert sentences('He said "stop." Then left.') == ['He said "stop."', "Then left."]


# ── render_turn ──────────────────────────────────────────────────────────────


def test_render_turn_orders_key_idea_body_question():
    out = render_turn(GOOD)
    assert out == (
        "Key idea: The derivative measures an instantaneous rate of change.\n\n"
        "Look at how the slope behaves near the point.\n\n"
        "What happens to the secant slope as h shrinks?"
    )
    assert out.endswith("?")  # question always last: feedback never ends on the answer


def test_render_turn_strips_fields_and_rejects_missing_key():
    padded = {k: f"  {v}  " for k, v in GOOD.items()}
    assert render_turn(padded) == render_turn(GOOD)
    with pytest.raises(ValueError, match="body"):
        render_turn({"key_idea": "A.", "question": "B?"})


def test_rendered_valid_turn_fits_the_step_bound():
    limits = turn_limits("teach", Rung.H6, answer_released=False)
    turn: LoopTurnOut = {
        "key_idea": "Limits describe approach.",
        "body": "One. Two. Three.",
        "question": "What next?",
    }
    assert validate_turn(turn, limits) == []
    rendered = render_turn(turn)
    assert len(sentences(rendered)) <= params.STEP_MAX_SENTENCES
    assert rendered.count("?") == params.STEP_QUESTIONS_PER_TURN


# ── turn_limits / clamp_model_ceiling ────────────────────────────────────────


def test_model_ceiling_clamped_to_h5():
    assert clamp_model_ceiling(Rung.H6, answer_released=False) == Rung.H5
    assert clamp_model_ceiling(Rung.H6, answer_released=True) == Rung.H6
    assert clamp_model_ceiling(Rung.H2, answer_released=False) == Rung.H2
    assert clamp_model_ceiling(3, answer_released=True) == Rung.H3
    assert turn_limits("teach", Rung.H6, answer_released=False).ceiling == Rung.H5
    for bad in (-1, params.LADDER_MAX_RUNG + 1):
        with pytest.raises(ValueError, match="ceiling"):
            clamp_model_ceiling(bad, answer_released=True)


def test_turn_limits_body_sentences_by_ceiling():
    by_rung = {r: turn_limits("hint", r, answer_released=False).body_max_sentences for r in Rung}
    assert by_rung[Rung.H0] == by_rung[Rung.H1] == 1
    assert by_rung[Rung.H2] == by_rung[Rung.H3] == 2
    top = params.STEP_MAX_SENTENCES - 2
    assert by_rung[Rung.H4] == by_rung[Rung.H5] == by_rung[Rung.H6] == top


def test_turn_limits_rejects_bad_phase_and_release_outside_feedback():
    with pytest.raises(ValueError, match="phase"):
        turn_limits("check", Rung.H1, answer_released=False)
    with pytest.raises(ValueError, match="answer_released"):
        turn_limits("teach", Rung.H6, answer_released=True)
    limits = turn_limits("feedback", Rung.H6, answer_released=True)
    assert isinstance(limits, TurnLimits) and limits.latex_ok and limits.ceiling == Rung.H6
    with pytest.raises(AttributeError):
        limits.latex_ok = False  # type: ignore[misc]  # frozen


# ── validate_turn ────────────────────────────────────────────────────────────


def test_valid_turn_has_no_problems():
    for rung in Rung:
        assert validate_turn(GOOD, turn_limits("teach", rung, answer_released=False)) == []


def test_validate_turn_reports_missing_and_blank_keys():
    limits = turn_limits("teach", Rung.H3, answer_released=False)
    problems = validate_turn({"key_idea": "A.", "body": "   "}, limits)
    assert "missing:body" in problems and "missing:question" in problems


def test_validate_turn_rejects_control_tag_echo():
    limits = turn_limits("feedback", Rung.H3, answer_released=False)
    for tag in (
        "[LOOP PHASE: teach]",
        "[VERDICT: correct]",
        "[CHECK ITEM]",
        "[ACTION: x]",
        "[STUDENT QUESTION]",
        "[GRAPH CONTEXT]",
    ):
        turn = {**GOOD, "body": f"{tag} Look at the slope."}
        assert "control_tag:body" in validate_turn(turn, limits), tag
    assert "control_tag:key_idea" in validate_turn(
        {**GOOD, "key_idea": "[LOOP PHASE: hint] Slope."}, limits
    )


def test_validate_turn_rejects_question_in_body():
    limits = turn_limits("teach", Rung.H3, answer_released=False)
    problems = validate_turn({**GOOD, "body": "Is it the slope? Look closer."}, limits)
    assert "question_outside_question:body" in problems
    problems = validate_turn({**GOOD, "key_idea": "What is a limit?"}, limits)
    assert "question_outside_question:key_idea" in problems


def test_validate_turn_requires_exactly_one_question():
    limits = turn_limits("teach", Rung.H3, answer_released=False)
    bad = (
        "Try the next step.",  # no question mark
        "What is f(x)? And f'(x)?",  # two questions
        "Is it zero?? Maybe.",  # doubled mark, second sentence
        "Look at the slope. What is it?",  # two sentences
        "Why?? ",  # two marks in one sentence
    )
    for q in bad:
        assert "question_shape" in _codes(validate_turn({**GOOD, "question": q}, limits)), q


def test_validate_turn_body_limit_by_ceiling():
    two = "First look at the slope. Then look at the limit."
    four = "One. Two. Three. Four."
    low = turn_limits("hint", Rung.H1, answer_released=False)
    mid = turn_limits("hint", Rung.H3, answer_released=False)
    high = turn_limits("hint", Rung.H5, answer_released=False)
    assert "body_sentences" in _codes(validate_turn({**GOOD, "body": two}, low))
    assert validate_turn({**GOOD, "body": two}, mid) == []
    assert "body_sentences" in _codes(validate_turn({**GOOD, "body": four}, mid))
    assert "body_sentences" in _codes(validate_turn({**GOOD, "body": four}, high))
    assert validate_turn({**GOOD, "body": "One. Two. Three."}, high) == []


def test_validate_turn_key_idea_is_one_sentence():
    limits = turn_limits("teach", Rung.H5, answer_released=False)
    problems = validate_turn({**GOOD, "key_idea": "Slope matters. So does the limit."}, limits)
    assert "key_idea_sentences" in _codes(problems)


def test_validate_turn_rejects_latex_below_h6():
    limits = turn_limits("teach", Rung.H5, answer_released=False)
    for body in (
        r"The slope is \frac{1}{2} here.",
        "The slope is $x^2$ here.",
        r"Use \cdot to multiply.",
    ):
        assert "latex:body" in validate_turn({**GOOD, "body": body}, limits), body
    # plain-text math and a lone dollar amount are fine
    assert (
        validate_turn({**GOOD, "body": "The slope is (x^2 - 1)/(x - 1) at $5 each."}, limits) == []
    )


def test_latex_allowed_when_released():
    limits = turn_limits("feedback", Rung.H6, answer_released=True)
    assert (
        validate_turn({**GOOD, "body": r"So the slope is \frac{1}{2} and $x^2$ grows."}, limits)
        == []
    )


# ── LoopTurnOut is a pydantic-validatable TypedDict ──────────────────────────


def test_loop_turn_out_validates_and_supports_partial():
    ta = TypeAdapter(LoopTurnOut)
    assert ta.validate_python(GOOD) == GOOD
    with pytest.raises(ValidationError):
        ta.validate_python({**GOOD, "body": "x" * (params.TURN_BODY_MAX_CHARS + 1)})
    partial = ta.validate_json(
        '{"key_idea": "Slope. ", "body": "Look', experimental_allow_partial="trailing-strings"
    )  # as pydantic-ai streams
    assert partial == {"key_idea": "Slope. ", "body": "Look"}


# ── render_partial ───────────────────────────────────────────────────────────


def test_render_partial_emits_completed_sentences_only():
    assert render_partial({}) == ""
    assert render_partial({"key_idea": "The deriv"}) == ""
    assert render_partial({"key_idea": "Pi is 3."}) == ""  # "3." may be "3.14"
    # a later key being present completes the earlier field
    assert render_partial({"key_idea": "Slope", "body": ""}) == "Key idea: Slope"
    assert (
        render_partial({"key_idea": "Slope.", "body": "Look. Then l"})
        == "Key idea: Slope.\n\nLook."
    )
    assert (
        render_partial({"key_idea": "Slope.", "body": "Look.", "question": "What is"})
        == "Key idea: Slope.\n\nLook."
    )


def test_render_partial_waits_for_earlier_fields():
    # out-of-order emission never skips ahead of a field that has not started
    assert render_partial({"question": "Why? "}) == ""
    assert render_partial({"key_idea": "Slope. ", "question": "Why? "}) == "Key idea: Slope."


def test_render_partial_is_a_prefix_of_the_final_render():
    final = {
        "key_idea": "Limits describe approach at 3.5 units.",
        "body": "Look at values near the point, e.g. 2.9. Then compare sides.",
        "question": "What value do both sides approach?",
    }
    full = render_turn(final)
    seen = ""
    order = ("key_idea", "body", "question")
    for i, key in enumerate(order):
        for n in range(len(final[key]) + 1):
            partial = {k: final[k] for k in order[:i]}
            partial[key] = final[key][:n]
            text = render_partial(partial)
            assert full.startswith(text), (key, n, text)
            assert text.startswith(seen), (key, n)  # monotone: deltas only append
            seen = text


# ── review round 3: below H4 no math of the model's own (provenance) ────────


def test_invented_math_is_a_letter_digit_expression_the_inputs_never_wrote():
    from learning.turn_shape import invented_math

    turn = {
        "key_idea": "The power rule turns x^n into n*x^(n-1).",
        "body": "For example, the derivative of x^3 is 3x^2.",
        "question": "How would the rule apply to your 5x^4?",
    }
    source = "Student: can we practise derivatives like 5x^4?"
    assert invented_math(turn, source) == ["x^3", "3x^2"], (
        "x^n, n-1 and the student's 5x^4 are fine"
    )
    assert (
        invented_math({"key_idea": "At n == 0 it stops.", "body": "", "question": "Why?"}, "") == []
    )
    assert (
        invented_math({"key_idea": "It is O(n^2).", "body": "", "question": "Why?"}, "O(n^2) time")
        == []
    )


def test_validate_turn_retries_invented_math_below_h4_only():
    from learning.turn_shape import turn_limits, validate_turn

    turn = {
        "key_idea": "The power rule differentiates a power.",
        "body": "For example, x^3 becomes 3x^2.",
        "question": "Where would you use it?",
    }
    below = validate_turn(turn, turn_limits("teach", 3, False), source="practise derivatives")
    assert "invented_math:x^3,3x^2" in below
    assert validate_turn(turn, turn_limits("teach", 4, False), source="practise derivatives") == []
    released = turn_limits("feedback", 3, True)
    assert not any(p.startswith("invented_math") for p in validate_turn(turn, released, source=""))
    assert validate_turn(turn, turn_limits("teach", 3, False)) == [], "no source: not judged"
