"""Deterministic grading for bounded written answers. Never evaluates code."""
from __future__ import annotations

import re
import unicodedata
from fractions import Fraction
from services.quiz_algebra import equivalent_algebra

WRITTEN_TYPES = {"short_answer", "numeric", "symbolic"}


# Sentence punctuation and quotes a student (or the model's key) wraps an
# answer in. Deliberately not every punctuation character: "C#" and "C++" must
# not collapse to "C", and "n!" must not collapse to "n".
_WRAPPING = ".,;:?\"'\u201c\u201d\u2018\u2019`"
_LEADING_ARTICLE = re.compile(r"^(?:a|an|the)\s+(?=\S)")


def normalize_answer(value: str) -> str:
    """Fold case, whitespace, wrapping punctuation and one leading article.

    Applied to BOTH sides, so "The base case." and "base case" agree. Still an
    exact comparison afterwards: no substring or fuzzy matching.
    """
    text = " ".join(unicodedata.normalize("NFKC", value).casefold().split())
    text = text.strip(_WRAPPING + " ")
    text = _LEADING_ARTICLE.sub("", text)
    return text.strip(_WRAPPING + " ")


_THOUSANDS = re.compile(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d*)?")
_MIXED = re.compile(r"([+-]?)(\d{1,40})\s+(\d{1,40}/\d{1,40})")


def numeric_value(value: str) -> Fraction | None:
    """Parse exact decimal, scientific, fraction, mixed-number (``1 1/2``),
    thousands-separated (``1,000``) or percentage notation.

    Bounded digits/exponents avoid pathological integer allocation. Units and
    algebra are intentionally rejected rather than guessed or executed, and a
    comma is accepted only in strict groups of three (``1,5`` stays ambiguous).
    """
    value = unicodedata.normalize("NFKC", value).strip().replace("−", "-").replace("⁄", "/")
    if len(value) > 128:
        return None
    percent = value.endswith("%")
    if percent:
        value = value[:-1].strip()
    if _THOUSANDS.fullmatch(value):
        value = value.replace(",", "")
    value = re.sub(r"\s*/\s*", "/", value)
    mixed = _MIXED.fullmatch(value)
    if mixed:
        whole = numeric_value(mixed.group(2)) or Fraction(0)
        part = numeric_value(mixed.group(3))
        if part is None:
            return None
        result = whole + part
        result = -result if mixed.group(1) == "-" else result
        return result / 100 if percent else result
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


_METRIC_BASE_UNITS = frozenset({"m", "g", "s", "L", "N", "J", "W", "Pa", "Hz", "V", "A", "mol"})
_METRIC_PREFIX_EXPONENTS = {
    "T": 12, "G": 9, "M": 6, "k": 3, "h": 2, "da": 1,
    "d": -1, "c": -2, "m": -3, "μ": -6, "u": -6, "n": -9, "p": -12,
}


def numeric_quantity(value: str) -> tuple[Fraction, str] | None:
    number, separator, unit = unicodedata.normalize("NFKC", value).strip().rpartition(" ")
    amount = numeric_value(number) if separator else None
    if amount is None or not re.fullmatch(r"[A-Za-zμΩ°][A-Za-zμΩ°0-9*/^·.−+-]{0,31}", unit):
        return None
    if unit not in _METRIC_BASE_UNITS:
        for prefix, exponent in _METRIC_PREFIX_EXPONENTS.items():
            base = unit.removeprefix(prefix)
            if base != unit and base in _METRIC_BASE_UNITS:
                return amount * Fraction(10) ** exponent, base
    return amount, unit


def _numeric_quantity_keys(question: dict) -> list[tuple[Fraction, str]]:
    keys = [expected_written_answer(question), *question.get("accepted_answers", [])]
    return [
        quantity for key in keys
        if isinstance(key, str) and (quantity := numeric_quantity(key)) is not None
    ]


def expected_written_answer(question: dict) -> str:
    answer = question.get("correct_answer", "")
    unit = question.get("numeric_unit")
    return f"{answer} {unit}" if question.get("type") == "numeric" and unit else answer


def written_feedback(question: dict, answer: str) -> str:
    explanation = question.get("explanation", "")
    if question.get("type") != "numeric" or not answer.strip() or grade_written(question, answer):
        return explanation
    if question.get("numeric_unit"):
        actual = numeric_quantity(answer)
        if actual is None:
            return f"Enter a number followed by its unit. {explanation}".strip()
        accepted = _numeric_quantity_keys(question)
        if all(actual[1] != unit for _, unit in accepted):
            return f"The unit you entered does not match an accepted unit for this question. {explanation}".strip()
        if (-actual[0], actual[1]) in accepted:
            return f"Check the sign of your result. {explanation}".strip()
    else:
        actual = numeric_value(answer)
        if actual is None:
            return f"Enter a number in the requested format. {explanation}".strip()
        key = question.get("correct_answer")
        expected = numeric_value(key) if isinstance(key, str) else None
        if expected is not None and actual == -expected:
            return f"Check the sign of your result. {explanation}".strip()
    return explanation


def grade_written(question: dict, answer: str) -> bool:
    expected = question.get("correct_answer", "")
    if not isinstance(expected, str) or not expected.strip() or not answer.strip():
        return False
    if question.get("type") == "numeric":
        if question.get("numeric_unit"):
            actual_quantity = numeric_quantity(answer)
            return actual_quantity is not None and actual_quantity in _numeric_quantity_keys(question)
        actual = numeric_value(answer)
        target = numeric_value(expected)
        return actual is not None and target is not None and actual == target
    if question.get("type") == "symbolic":
        return equivalent_algebra(answer, expected)
    accepted = [expected, *question.get("accepted_answers", [])]
    return any(isinstance(a, str) and normalize_answer(answer) == normalize_answer(a) for a in accepted)
