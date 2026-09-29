"""PKG-06 reopen (PKG-07 review round 3, C1(c)): strict mode folds simple
inflections of a WORD answer.

The loop's served path runs detect_leak/strip_leak in strict mode against the
active item. A word answer's other inflections ("mitochondria" for
"Mitochondrion", "viruses" for "virus") state it just as plainly; the rule is
structural — two alphabetic answer tokens are one lemma when they share a stem
of at least LEAK_STEM_MIN_CHARS characters and each differs from it by at most
LEAK_INFLECTION_MAX_CHARS trailing characters — never a list of words.
"""

from __future__ import annotations

import pytest

from learning.ladder import Rung
from learning.leak import WITHHELD, detect_leak, strip_leak
from learning.params import LEAK_INFLECTION_MAX_CHARS, LEAK_STEM_MIN_CHARS

MITO = dict(
    reference="The ATP-producing stages happen in the mitochondrion. Final answer: Mitochondrion.",
    final_answer="Mitochondrion",
    correct_option="B",
)


def _leaks(text: str, *, strict: bool = True, **item) -> bool:
    return detect_leak(emitted=text, rung=Rung.H2, strict=strict, **item).leaked


@pytest.mark.parametrize(
    "text",
    [
        "It's the mitochondria.",
        "Mitochondrial respiration happens there.",
        "MITOCHONDRIONS everywhere.",
    ],
)
def test_strict_mode_catches_an_inflection_of_a_word_answer(text):
    assert _leaks(text, **MITO)
    assert not _leaks(text, strict=False, **MITO), "default mode keeps its exact-token rule"


@pytest.mark.parametrize(
    "final_answer, text",
    [
        ("virus", "Both viruses replicate."),
        ("analysis", "Two analyses agree."),
        ("base case returns 1", "The base cases return 1."),
    ],
)
def test_every_word_of_a_multi_word_answer_folds(final_answer, text):
    assert _leaks(text, reference="x", final_answer=final_answer)


@pytest.mark.parametrize(
    "final_answer, text",
    [
        ("mitosis", "Meiosis halves the chromosomes."),  # different stem
        ("photosynthesis", "The photosystem absorbs light."),  # stem shared, ending too long
        ("cell", "The cat sat."),  # no shared stem
        ("8", "Write eighty words."),  # numbers are compared by value, never folded
    ],
)
def test_a_different_word_is_not_an_inflection(final_answer, text):
    assert not _leaks(text, reference="x", final_answer=final_answer)


def test_the_rule_is_the_stem_bounds_not_a_word_list():
    stem = "q" * LEAK_STEM_MIN_CHARS
    answer = stem + "a" * LEAK_INFLECTION_MAX_CHARS
    assert _leaks(stem + "z" * LEAK_INFLECTION_MAX_CHARS, reference="x", final_answer=answer)
    assert not _leaks(
        stem + "z" * (LEAK_INFLECTION_MAX_CHARS + 1), reference="x", final_answer=answer
    )
    short = "q" * (LEAK_STEM_MIN_CHARS - 1)
    assert not _leaks(short + "zz", reference="x", final_answer=short + "a")


def test_strip_withholds_the_inflection_and_leaves_nothing_the_detector_flags():
    text = "Key idea: the mitochondria make ATP.\n\nWhich organelle is it?"
    out = strip_leak(emitted=text, strict=True, **MITO)
    assert "mitochondri" not in out.lower() and WITHHELD in out
    assert not _leaks(out, **MITO)


def test_strict_mode_catches_the_numeric_answer_written_in_words():
    item = dict(reference="f'(1) = 8. Final answer: 8.", final_answer="8", canonical_answer="8")
    assert _leaks("f'(one) is eight", **item)
    assert "eight" not in strip_leak(emitted="f'(one) is eight", strict=True, **item)
