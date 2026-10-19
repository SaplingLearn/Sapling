"""PKG-06 reopen (PKG-07 fix round 2, N1/n2): detect_leak's served mode.

`given` is the text the model was GIVEN this turn (the item prompt and source
passages as sent, the student's message, the served history). In served mode:
- a hit inside a run the model copied verbatim from `given` (at least
  LEAK_PROVENANCE_MIN_TOKENS answer tokens, reaching past the hit) is no leak:
  it reveals nothing the student cannot already see — and masking it in place
  would (the reviewer's "3x^[withheld]");
- strict mode's number-word and standalone-letter rules count only in ANSWER
  POSITION: right after an answer/result/equals construction, a copula or an
  "=", or standing alone as a clause.
Default mode (the grader hint) is unchanged: no `given`, no position gate.
"""

from __future__ import annotations

import pytest

from learning.ladder import Rung
from learning.leak import detect_leak, leak_spans

G = dict(
    reference="g'(x) = 6x + 2 has two nonzero terms. Final answer: 2.",
    final_answer="2",
    canonical_answer="2",
)
G_PROMPT = "After differentiating g(x) = 3x^2 + 2x, how many nonzero terms does g'(x) have?"


def _served(text: str, given: str = G_PROMPT, **item) -> bool:
    item = item or G
    return detect_leak(emitted=text, rung=Rung.H3, strict=True, given=given, **item).leaked


def test_a_copy_of_the_given_item_is_not_a_leak():
    text = "What is the derivative of the first term, 3x^2?"
    assert detect_leak(emitted=text, rung=Rung.H3, strict=True, **G).leaked, "the old reading"
    assert not _served(text)
    assert not _served("Start from g(x) = 3x^2 + 2x and differentiate each term.")


@pytest.mark.parametrize(
    "text",
    [
        "The answer is 2.",
        "There are 2 nonzero terms.",
        "The answer is two.",
        "It equals two.",
        "Two.",
    ],
)
def test_a_genuine_statement_of_the_answer_still_leaks(text):
    assert _served(text), text


def test_number_words_count_only_in_answer_position():
    assert not _served("Add the two results together.", given="")
    assert _served("The result is two.", given="")


def test_a_standalone_key_letter_counts_only_in_answer_position():
    mito = dict(
        reference="It is the mitochondrion.", final_answer="Mitochondrion", correct_option="C"
    )
    assert not _served("Let C be the constant of integration.", given="", **mito)
    assert _served("The answer is C.", given="", **mito)
    assert _served("C.", given="", **mito)
    assert _served("Pick c.", given="", **mito)


def test_the_student_s_own_words_are_given_too():
    msg = "I think g'(x) = 6x + 2, right?"
    assert not _served("You wrote g'(x) = 6x + 2.", given=G_PROMPT + "\n" + msg)


def test_leak_spans_are_the_filtered_hits():
    text = "The first term is 3x^2. The answer is 2."
    spans = leak_spans(emitted=text, strict=True, given=G_PROMPT, **G)
    assert [text[a:b] for a, b in spans] == ["2"] and spans[0][0] > text.index("answer")


def test_a_number_word_quantifying_the_items_own_object_is_in_answer_position():
    """Final round: "It has two nonzero terms." states the count the item asks
    for — the number word is followed by the item's own noun ("terms")."""
    assert _served("It has two nonzero terms.")
    assert not _served("Add the two results together.")


def test_a_number_word_or_letter_named_as_the_answer_after_it_is_in_answer_position():
    """PKG-10 fix round 4 (R4-3, spec §13 A77): answer position read AFTER the
    hit too — "<hit> as the (final) answer / as your result" names it the answer
    exactly as "the answer is <hit>" does. Served mode missed number words and
    key letters written that way ("Write two as the final answer.")."""
    assert _served("You might write two as the final answer.", given="")
    assert _served("Take two as the result here.", given="")
    assert not _served("Treat two as a constant factor.", given="")
    mito = dict(
        reference="It is the mitochondrion.", final_answer="Mitochondrion", correct_option="C"
    )
    assert _served("Put C as your answer.", given="", **mito)
    assert not _served("Let C be the constant, as the answer depends on it.", given="", **mito)
