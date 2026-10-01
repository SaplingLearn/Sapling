"""A38 fix round (M1(b)/(d), m7): the grader hint's leak check runs
leak.detect_leak in strict mode, with the correct option's text threaded
through the seam's GraderItem (as lane E threaded final_answer)."""

from __future__ import annotations

import pytest


# ── the grader hint runs the strict mode, with the correct option's text ─────


def _reason_item(**over):
    from services import decisions

    state = decisions.ReasonState(
        question="Why does f recurse forever?",
        reference="Option C: nothing stops the calls, so it never terminates.",
        rubric={"r1": "Names the missing base case."},
        wrong={"w_loop": "Thinks it is a loop."},
        selected_option="B",
        correct_option="C",
        reason="it stops",
        options={
            "A": "It returns early",
            "B": "It loops",
            "C": "Nothing stops the calls",
            "D": "It overflows the heap",
        },
        final_answer="It never terminates",
        **over,
    )
    return decisions.grader_item_from(state)


def test_the_grader_item_carries_the_correct_option_text():
    assert _reason_item().correct_option_text == "Nothing stops the calls"


@pytest.mark.parametrize(
    "hint, leaks",
    [
        ("Think about vitamin C.", True),  # strict: any standalone key letter
        ("C is right.", True),
        ("Ｃ.", True),
        ("Maybe nothing stops the calls?", True),  # the correct option's text
        ("Think about what ends a recursion.", False),
        ("Option B has a flaw.", False),
        ("Is it the third one?", True),  # the key's position (C is third)
        ("Is there a smaller subproblem?", False),
    ],
)
def test_the_grader_hint_check_is_strict(hint, leaks):
    from agents import grader

    assert grader._hint_leaks(_reason_item(), hint, format="mc_reason") is leaks, hint


def test_the_grader_hint_check_reads_numeric_paraphrases():
    from agents import grader
    from services import decisions

    state = decisions.GradeState(
        question="What is 3 + 4?",
        reference="Three plus four is 7.",
        rubric={"r1": "States 7."},
        wrong={},
        answer="8",
        format="free",
        final_answer="7",
        canonical_answer="7",
    )
    item = decisions.grader_item_from(state)
    assert grader._hint_leaks(item, "Is it seven?", format="free") is True
    assert grader._hint_leaks(item, "Count again from three.", format="free") is False
