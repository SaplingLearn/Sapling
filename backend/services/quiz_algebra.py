"""Bounded rational-polynomial equivalence, without eval or symbolic runtime.

Supports + - * / ^, parentheses, single-letter variables and implicit
multiplication. Expressions are equivalent wherever both are defined.
Functions, units, equations and non-integer powers are outside this grammar.
"""
from __future__ import annotations

import re
import unicodedata
from fractions import Fraction

Poly = dict[tuple[tuple[str, int], ...], Fraction]


def _add(a: Poly, b: Poly) -> Poly:
    out = dict(a)
    for key, value in b.items():
        out[key] = out.get(key, Fraction(0)) + value
    return {key: value for key, value in out.items() if value}


def _mul(a: Poly, b: Poly) -> Poly:
    if len(a) * len(b) > 256:
        raise ValueError("Expression too complex")
    out: Poly = {}
    for left, x in a.items():
        for right, y in b.items():
            powers = dict(left)
            for symbol, degree in right:
                powers[symbol] = powers.get(symbol, 0) + degree
            if sum(powers.values()) > 24:
                raise ValueError("Degree too high")
            key = tuple(sorted(powers.items()))
            out[key] = out.get(key, Fraction(0)) + x * y
    out = {key: value for key, value in out.items() if value}
    if len(out) > 64 or any(v.numerator.bit_length() > 4096 or v.denominator.bit_length() > 4096 for v in out.values()):
        raise ValueError("Expression too complex")
    return out


class _Parser:
    def __init__(self, text: str):
        text = unicodedata.normalize("NFKC", text).replace("−", "-").replace("×", "*").replace("÷", "/")
        if not text.strip() or len(text) > 256:
            raise ValueError("Invalid length")
        # Requiring single-letter identifiers avoids silently reading sin(x)
        # as a product. Students can write x*y or x y explicitly.
        pattern = r"\d{1,20}(?:\.\d{0,20})?(?:[eE][+-]?\d{1,2})?|\.\d{1,20}|[a-zA-Z]+|[()+*/^\-]"
        self.tokens = re.findall(pattern, text)
        if re.sub(r"\s+", "", text) != "".join(self.tokens) or len(self.tokens) > 96:
            raise ValueError("Unsupported notation")
        self.pos = 0

    def peek(self) -> str:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else ""

    def take(self) -> str:
        value = self.peek()
        self.pos += 1
        return value

    def expression(self):
        left = self.term()
        while self.peek() in ("+", "-"):
            op = self.take()
            right = self.term()
            numerator = _mul(right[0], left[1])
            if op == "-":
                numerator = {key: -v for key, v in numerator.items()}
            left = (_add(_mul(left[0], right[1]), numerator), _mul(left[1], right[1]))
        return left

    def term(self):
        left = self.unary()
        while True:
            token = self.peek()
            implicit = bool(token) and (token == "(" or token[0].isalnum() or token.startswith("."))
            if token not in ("*", "/") and not implicit:
                return left
            op = "*" if implicit else self.take()
            right = self.unary()
            if op == "/":
                if not right[0]:
                    raise ValueError("Division by zero")
                right = (right[1], right[0])
            left = (_mul(left[0], right[0]), _mul(left[1], right[1]))

    def unary(self):
        if self.peek() in ("+", "-"):
            op = self.take()
            a, b = self.unary()
            return ({key: -v for key, v in a.items()} if op == "-" else a, b)
        return self.power()

    def power(self):
        value = self.atom()
        if self.peek() == "^":
            self.take()
            sign = -1 if self.peek() == "-" else 1
            if self.peek() in ("-", "+"):
                self.take()
            exponent = self.take()
            if not exponent.isdigit() or len(exponent) > 1 or int(exponent) > 8:
                raise ValueError("Use integer powers from -8 to 8")
            n = sign * int(exponent)
            if n < 0:
                if not value[0]:
                    raise ValueError("Division by zero")
                value = value[1], value[0]
            result = ({(): Fraction(1)}, {(): Fraction(1)})
            for _ in range(abs(n)):
                result = _mul(result[0], value[0]), _mul(result[1], value[1])
            value = result
        return value

    def atom(self):
        token = self.take()
        if token == "(":
            value = self.expression()
            if self.take() != ")":
                raise ValueError("Unbalanced parentheses")
            return value
        if re.fullmatch(r"[a-zA-Z]", token):
            return {((token, 1),): Fraction(1)}, {(): Fraction(1)}
        try:
            number = Fraction(token)
            return ({(): number} if number else {}), {(): Fraction(1)}
        except (ValueError, ZeroDivisionError):
            raise ValueError("Unsupported atom") from None


def parse_algebra(text: str):
    parser = _Parser(text)
    value = parser.expression()
    if parser.peek() or not value[1]:
        raise ValueError("Invalid expression")
    return value


def equivalent_algebra(answer: str, expected: str) -> bool:
    try:
        a, b = parse_algebra(answer)
        c, d = parse_algebra(expected)
        return _mul(a, d) == _mul(c, b)
    except (ValueError, ZeroDivisionError, OverflowError, RecursionError):
        return False
