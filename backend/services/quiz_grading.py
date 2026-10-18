"""Deterministic grading for bounded written answers. Never evaluates code."""
from __future__ import annotations

import re
import unicodedata
from fractions import Fraction
from services.quiz_algebra import equivalent_algebra

WRITTEN_TYPES = {"short_answer", "numeric", "symbolic"}


def normalize_answer(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def numeric_value(value: str) -> Fraction | None:
    """Parse exact decimal, scientific, fraction, or percentage notation.

    Bounded digits/exponents avoid pathological integer allocation. Units and
    algebra are intentionally rejected rather than guessed or executed.
    """
    value = unicodedata.normalize("NFKC", value).strip().replace("−", "-").replace("⁄", "/")
    if len(value) > 128:
        return None
    percent = value.endswith("%")
    if percent:
        value = value[:-1].strip()
    value = re.sub(r"\s*/\s*", "/", value)
    number = r"[+-]?(?:\d{1,40}(?:\.\d{0,40})?|\.\d{1,40})(?:[eE][+-]?\d{1,2})?"
    if not re.fullmatch(rf"{number}(?:/{number})?", value):
        return None
    try:
        parts = value.split("/")
        result = Fraction(parts[0])
        if len(parts) == 2:
            result /= Fraction(parts[1])
        return result / 100 if percent else result
    except (ValueError, ZeroDivisionError, OverflowError):
        return None


def grade_written(question: dict, answer: str) -> bool:
    expected = question.get("correct_answer", "")
    if not isinstance(expected, str) or not expected.strip() or not answer.strip():
        return False
    if question.get("type") == "numeric":
        actual = numeric_value(answer)
        target = numeric_value(expected)
        return actual is not None and target is not None and actual == target
    if question.get("type") == "symbolic":
        return equivalent_algebra(answer, expected)
    accepted = [expected, *question.get("accepted_answers", [])]
    return any(isinstance(a, str) and normalize_answer(answer) == normalize_answer(a) for a in accepted)
