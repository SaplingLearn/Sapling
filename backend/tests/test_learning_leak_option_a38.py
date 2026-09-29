"""A38 fix round (M1, m7): the option-letter rule and the grader hint's strict mode.

leak.detect_leak's option rule was a keyword list: "C is right", "it's C.",
"**C**", "[C]", "choice (c)", a fullwidth "Ｃ" and more all leaked the key. Now:

- every text is NFKC-normalised and look-alikes folded (learning._confusables,
  the table answer_guard reads) before the option rule matches;
- default mode (tutor prose, where a false positive withholds a word the
  student reads): the context rule, case-insensitive inside brackets, quotes and
  emphasis and after the keyword set (the lowercase article/pronoun "a"/"i"
  before a word excepted), plus "X is/was (the) correct/right/answer" and
  "it's X";
- `strict=True` (the grader hint, where a false positive only drops a hint):
  ANY standalone key letter, the correct option's restated text
  (`option_text`), and, for a numeric answer, its value written as a number
  word, a LaTeX fraction, a percentage or an equivalent fraction.
"""

from __future__ import annotations

import random
import time

import pytest

REF = "Option C holds: it never terminates, since nothing stops the calls."
FINAL = "It never terminates"
KW = {"final_answer": FINAL, "correct_option": "C"}

# Every phrasing the reviews found leaking under the old keyword rule.
OWNER_PHRASINGS = [
    "C is right",
    "it's C.",
    "**C**",
    "answer: **C**",
    "[C]",
    "choice (c)",
    "option c",
    "answer is c",
    "Ｃ",
    "option—C",
    "option – C",
    "correct: C",
    "answer => C",
    "A/B/C/D → C",
    "opt. C",
]
# Default mode catches every one of them but the bare fullwidth capital (a bare
# capital is no context), and that one in context.
DEFAULT_LEAKS = [p for p in OWNER_PHRASINGS if p != "Ｃ"] + [
    "option Ｃ",
    "It is C, look again.",
    "Was it c? It was C was the answer.",
    "C was the correct one.",
    "c is correct",
    "(C) is it",
    "*C*",
    "__C__",
    "`C`",
    "'C'",
    "“C”",
    "The key: ​C",  # a zero-width space hides nothing
    "option С",  # Cyrillic Es reads as C
    "the answer is (c).",
    "Pick c",
]
# Honest non-leaks in default mode (key C unless noted). Documented decisions:
# a bare capital or a letter inside a word is no option context; "part C" and
# "(see part C)" name a part, not an option ("(see part C)" was withheld as
# "C)" and left an unbalanced "(").
DEFAULT_CLEAN = [
    "vitamin C",
    "C++ has pointers.",
    "You would get a grade C for that.",
    "part C of the lab",
    "(see part C)",
    "Consider the calls.",
    "option B fails because it has a base case.",
    "(B) and (D) share a flaw.",
    "optionC is one token.",
    "ABC) is not a label.",
    "It's clear that the calls pile up.",
]
DEFAULT_CLEAN_KEY_A = [
    "A derivative is a rate of change.",
    "Answer a smaller question first.",
    "Choose a function that stops.",
    "The answer is a function of n.",
    "It's a trap.",
    "Pick an option you can defend.",
]


def _detect(text, *, strict=False, key="C", **over):
    from learning.ladder import Rung
    from learning.leak import detect_leak

    kw = {"final_answer": FINAL, "correct_option": key, **over}
    return detect_leak(reference=REF, emitted=text, rung=Rung.H0, strict=strict, **kw)


def _strip(text, *, strict=False, key="C", **over):
    from learning.leak import strip_leak

    kw = {"final_answer": FINAL, "correct_option": key, **over}
    return strip_leak(emitted=text, reference=REF, strict=strict, **kw)


@pytest.mark.parametrize("hint", OWNER_PHRASINGS)
def test_every_owner_phrasing_leaks_in_strict_mode(hint):
    assert _detect(hint, strict=True) == (True, "option"), hint


@pytest.mark.parametrize("hint", DEFAULT_LEAKS)
def test_the_context_rule_catches_them_in_default_mode(hint):
    assert _detect(hint) == (True, "option"), hint


@pytest.mark.parametrize("hint", DEFAULT_CLEAN)
def test_honest_non_leaks_in_default_mode(hint):
    assert _detect(hint) == (False, "none"), hint
    assert _strip(hint) == hint


@pytest.mark.parametrize("hint", DEFAULT_CLEAN_KEY_A)
def test_the_article_a_is_no_leak_for_key_a_in_default_mode(hint):
    assert _detect(hint, key="A") == (False, "none"), hint
    assert _strip(hint, key="A") == hint


def test_the_letter_a_still_leaks_for_key_a_where_it_is_a_label():
    for hint in ("The answer is a.", "option a", "(a)", "It's A.", "A is correct", "pick a!"):
        assert _detect(hint, key="A") == (True, "option"), hint


@pytest.mark.parametrize("hint", ["vitamin C", "C++", "grade C", "part C of the lab"])
def test_strict_mode_flags_any_standalone_key_letter(hint):
    """The hint is dropped on these (a false positive costs one hint), by design."""
    assert _detect(hint, strict=True) == (True, "option"), hint


def test_strict_mode_never_flags_the_letter_inside_a_word_or_another_letter():
    for hint in ("Consider the calls.", "optionC", "ABC", "option B", "(D)", "c2c"):
        assert _detect(hint, strict=True) == (False, "none"), hint


def test_strict_mode_catches_the_restated_correct_option_text():
    text = "The calls pile up until the stack overflows"
    hint = "Could it be that the calls pile up until the stack overflows?"
    assert _detect(hint, option_text=text) == (False, "none"), "default: no option text rule"
    assert _detect(hint, strict=True, option_text=text) == (True, "option")
    assert _detect("Think about the stack.", strict=True, option_text=text) == (False, "none")
    once = _strip(hint, strict=True, option_text=text)
    assert "overflows" not in once
    assert _detect(once, strict=True, option_text=text) == (False, "none")


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("hint", OWNER_PHRASINGS + DEFAULT_LEAKS)
def test_strip_withholds_and_is_idempotent(hint, strict):
    once = _strip(hint, strict=strict)
    assert _detect(once, strict=strict) == (False, "none"), once
    assert _strip(once, strict=strict) == once
    if _detect(hint, strict=strict).leaked:
        assert "[withheld]" in once


def test_see_part_c_strips_to_balanced_brackets_in_strict_mode():
    once = _strip("(see part C)", strict=True)
    assert once == "(see part [withheld])"
    assert once.count("(") == once.count(")")


def test_random_texts_strip_clean_and_idempotent_in_both_modes():
    """Property: for random mixes of option contexts, markup, separators,
    look-alikes, invisible characters and existing markers, one strip pass leaves
    nothing the same mode flags, and a second pass is a no-op."""
    pieces = [
        "option", "opt.", "choice", "answer", "answer is", "correct:", "it's", "It is",
        "pick", "is right", "was the answer", "→", "=>", "->", "—", "–", ":", "-",
        "(", ")", "[", "]", "**", "*", "_", "`", "'", '"', "“", "”",
        "A", "a", "B", "c", "C", "Ｃ", "С", "D", "​", "́", "part", "see",
        "vitamin", "grade", "a derivative", "[withheld]", "\n", " ", " ", " ",
        "the calls pile up", "7", "seven", "1/2",
    ]  # fmt: skip
    rng = random.Random(3838)
    for _ in range(1500):
        text = "".join(
            rng.choice(pieces) + rng.choice(["", " "]) for _ in range(rng.randint(1, 14))
        )
        key = rng.choice("ABCD")
        for strict in (False, True):
            extra = {"option_text": "the calls pile up"} if strict else {}
            once = _strip(text, strict=strict, key=key, **extra)
            assert _detect(once, strict=strict, key=key, **extra) == (False, "none"), (
                text,
                once,
                key,
                strict,
            )
            assert _strip(once, strict=strict, key=key, **extra) == once, (text, key, strict)


@pytest.mark.parametrize("strict", [False, True])
def test_no_redos_on_a_long_adversarial_text(strict):
    chunks = ["option ", "(", "[", "**", "answer is ", "—", " ", "c", "it's ", "→ ", "C) "]
    text = "".join(chunks[i % len(chunks)] for i in range(12_000))[:50_000]
    for adversarial in (text, "(" * 50_000, "option " * 7_000, "*" * 50_000 + "C"):
        t0 = time.perf_counter()
        _detect(adversarial, strict=strict)
        _strip(adversarial, strict=strict)
        assert time.perf_counter() - t0 < 1.0, adversarial[:40]


# ── m7: the grader hint's numeric forms (strict mode, numeric answers) ───────

NUM_REF = "Add the two parts: three plus four gives the total."


def _num(text, final, canonical=None, *, strict=True):
    from learning.ladder import Rung
    from learning.leak import detect_leak

    return detect_leak(
        reference=NUM_REF,
        emitted=text,
        rung=Rung.H0,
        final_answer=final,
        canonical_answer=canonical,
        strict=strict,
    )


@pytest.mark.parametrize(
    "hint, final, canonical",
    [
        ("Is it seven?", "7", "7"),
        ("So the total is Seven, right?", "7 apples", "7"),
        ("twenty-five, perhaps?", "25", "25"),
        ("one hundred and five", "105", "105"),
        ("Try one half.", "1/2", "0.5"),
        ("a half of it", "0.5", "0.5"),
        ("three quarters", "0.75", "0.75"),
        ("It is \\frac{1}{2}.", "0.5", "0.5"),
        ("$\\dfrac{3}{4}$", "3/4", None),
        ("About 50%.", "0.5", "0.5"),
        ("fifty percent", "0.5", "0.5"),
        ("Maybe 0.5?", "50%", "50"),
        ("Is it 5/10?", "1/2", "0.5"),
        ("Is it 10 / 20?", "0.5", None),
    ],
)
def test_numeric_paraphrases_leak_in_strict_mode(hint, final, canonical):
    assert _num(hint, final, canonical) == (True, "final_answer"), hint
    once = _strip_num(hint, final, canonical)
    assert _num(once, final, canonical) == (False, "none"), once


def _strip_num(text, final, canonical):
    from learning.leak import strip_leak

    return strip_leak(
        emitted=text,
        reference=NUM_REF,
        final_answer=final,
        canonical_answer=canonical,
        strict=True,
    )


@pytest.mark.parametrize(
    "hint, final, canonical",
    [
        ("Is it seven?", "8", "8"),
        ("Try one step at a time.", "7", "7"),
        ("About 50%.", "0.4", "0.4"),
        ("Is it 5/11?", "1/2", "0.5"),
        ("Count the halves of the interval.", "3", "3"),
        ("It is \\frac{1}{3}.", "0.5", "0.5"),
    ],
)
def test_numeric_non_leaks_in_strict_mode(hint, final, canonical):
    assert _num(hint, final, canonical) == (False, "none"), hint


def test_numeric_paraphrases_are_strict_mode_only():
    """Tutor prose keeps the value rules it had: "take one step" is no leak of 1."""
    assert _num("Is it seven?", "7", "7", strict=False) == (False, "none")
    assert _num("Take one step back.", "1", "1", strict=False) == (False, "none")
    assert _num("Take one step back.", "1", "1") == (True, "final_answer")


def test_a_verbal_paraphrase_is_a_documented_residual():
    """ "linear time" for O(n) is no token the checker reads: judge_leak's job."""
    assert _num("It grows in linear time.", "O(n)") == (False, "none")
