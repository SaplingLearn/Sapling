"""Personalization variables for admin broadcasts.

An admin writes `{{first_name}}` (or `{{first_name|friend}}`) in a broadcast's
subject or body, and each recipient's copy gets their own value. The fallback
after `|` replaces the variable's built-in one when the recipient has no value,
so "Hi {{first_name}}," never becomes "Hi ,".

Filling happens on the admin's PLAIN TEXT, before email_templates escapes and
linkifies it, so a value can never inject markup. An unknown variable is
rejected at send time (models validate with `unknown_variables`) rather than
mailed out as literal braces.
"""

from __future__ import annotations

import re
from typing import Mapping

#: In display order. `fallback` is used when the recipient has no value and the
#: admin gave none; `example` is what the admin sees in docs and tooltips.
VARIABLES: list[dict[str, str]] = [
    {"key": "first_name", "label": "First name", "fallback": "there", "example": "Ada"},
    {"key": "name", "label": "Full name", "fallback": "there", "example": "Ada Lovelace"},
    {"key": "email", "label": "Email address", "fallback": "", "example": "ada@bu.edu"},
    {"key": "app_link", "label": "Link to Sapling", "fallback": "", "example": "https://saplinglearn.com/dashboard"},
    {"key": "signin_link", "label": "Sign-in link", "fallback": "", "example": "https://saplinglearn.com"},
]
_FALLBACKS = {v["key"]: v["fallback"] for v in VARIABLES}

# {{ key }} or {{ key | fallback }}; the fallback can't contain braces.
_VAR_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:\|([^{}]*))?\}\}")


def unknown_variables(*texts: str) -> list[str]:
    """Variable names used in `texts` that aren't real variables, in order of
    first use, each once."""
    seen: list[str] = []
    for text in texts:
        for m in _VAR_RE.finditer(text or ""):
            key = m.group(1)
            if key not in _FALLBACKS and key not in seen:
                seen.append(key)
    return seen


def unknown_variables_message(names: list[str]) -> str:
    known = ", ".join("{{" + v["key"] + "}}" for v in VARIABLES)
    listed = ", ".join("{{" + n + "}}" for n in names)
    noun = "variable" if len(names) == 1 else "variables"
    return f"Unknown {noun} {listed}. Use one of: {known}."


def fill(text: str, values: Mapping[str, str | None]) -> str:
    """`text` with every known variable replaced by the recipient's value, its
    `|fallback`, or the built-in fallback, in that order. Unknown variables are
    left exactly as typed (sends reject them before this runs)."""

    def sub(m: re.Match) -> str:
        key, given = m.group(1), m.group(2)
        if key not in _FALLBACKS:
            return m.group(0)
        value = " ".join((values.get(key) or "").split())
        if value:
            return value
        return given.strip() if given is not None else _FALLBACKS[key]

    return _VAR_RE.sub(sub, text or "")
