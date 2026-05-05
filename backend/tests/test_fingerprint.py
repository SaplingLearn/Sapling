"""Unit tests for services.fingerprint.

Covers: deterministic hashing, the unit-separator delimiter (so
ambiguous-pipe collisions are impossible), list/tuple flattening,
None handling, custom length.
"""

from __future__ import annotations

from services.fingerprint import SEPARATOR, fingerprint, fingerprint_text


def test_deterministic_same_inputs_same_fingerprint():
    a = fingerprint("hello", "world")
    b = fingerprint("hello", "world")
    assert a == b
    assert len(a) == 12


def test_default_length_12_hex_chars():
    fp = fingerprint("anything")
    assert len(fp) == 12
    assert all(c in "0123456789abcdef" for c in fp)


def test_custom_length():
    fp = fingerprint("anything", length=20)
    assert len(fp) == 20


def test_unit_separator_avoids_pipe_ambiguity():
    """If options contain `|`, naive `'|'.join(...)` would collapse
    distinct option lists into the same string. The unit-separator
    keeps them distinct."""
    a = fingerprint("answer", ["a|b", "c"])
    b = fingerprint("answer", ["a", "b|c"])
    assert a != b, (
        "Fingerprint must distinguish [a|b, c] from [a, b|c]; "
        "the unit-separator is supposed to prevent this collision."
    )


def test_list_arg_flattens_with_separator():
    """A list argument is one part, joined with SEPARATOR internally."""
    fp_list = fingerprint("x", ["a", "b", "c"])
    # Equivalent direct call: hash("x" + sep + "a" + sep + "b" + sep + "c")
    direct = fingerprint_text("x" + SEPARATOR + "a" + SEPARATOR + "b" + SEPARATOR + "c", length=12)
    assert fp_list == direct


def test_none_becomes_empty_string():
    """None parts collapse to empty so the fingerprint stays stable
    across Optional fields without special-casing each call site."""
    fp_none = fingerprint("a", None, "b")
    fp_empty = fingerprint("a", "", "b")
    assert fp_none == fp_empty


def test_int_and_bool_coerced_to_string():
    fp_int = fingerprint(42)
    fp_str = fingerprint("42")
    assert fp_int == fp_str
    fp_true = fingerprint(True)
    fp_str_true = fingerprint("True")
    assert fp_true == fp_str_true


def test_fingerprint_text_default_length_16():
    fp = fingerprint_text("hello")
    assert len(fp) == 16


def test_separator_is_unit_separator():
    """Sanity check that the constant is what we documented."""
    assert SEPARATOR == "\x1f"
    assert ord(SEPARATOR) == 31
