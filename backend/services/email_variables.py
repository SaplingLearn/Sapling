"""Personalization variables for admin broadcasts.

An admin writes `{{first_name}}` (or `{{first_name|friend}}`) in a broadcast's
subject or body, and each recipient's copy gets their own value. The fallback
after `|` replaces the variable's built-in one when the recipient has no value,
so "Hi {{first_name}}," never becomes "Hi ,".

The two link variables always have a value, so for them the text after `|` is
the LABEL instead: in the email's HTML a link alone on its line becomes a
button ("Open Sapling", or `{{signin_link|Join the beta}}`), and one inside a
sentence becomes a link on that label. The plain-text part gets the URL.

Filling happens on the admin's PLAIN TEXT, before email_templates escapes and
linkifies it, so a value can never inject markup. An unknown variable is
rejected at send time (models validate with `unknown_variables`) rather than
mailed out as literal braces.
"""

from __future__ import annotations

import re
from typing import Mapping

import config

#: In display order. `fallback` is used when the recipient has no value and the
#: admin gave none; `example` is what the admin sees in docs and tooltips.
VARIABLES: list[dict[str, str]] = [
    {"key": "first_name", "label": "First name", "fallback": "there", "example": "Ada"},
    {"key": "name", "label": "Full name", "fallback": "there", "example": "Ada Lovelace"},
    {"key": "email", "label": "Email address", "fallback": "", "example": "ada@bu.edu"},
    {"key": "app_link", "label": "Link to Sapling", "fallback": "", "example": "https://saplinglearn.com/dashboard",
     "button": "Open Sapling"},
    {"key": "signin_link", "label": "Sign-in link", "fallback": "", "example": "https://saplinglearn.com",
     "button": "Sign in to Sapling"},
]
_FALLBACKS = {v["key"]: v["fallback"] for v in VARIABLES}
#: Link variables → their default button label.
LINK_LABELS = {v["key"]: v["button"] for v in VARIABLES if "button" in v}

#: Marks a link in filled HTML-bound text: \x00 can't come from an admin's
#: plain text (the composer is a textarea) and survives escaping untouched.
LINK_TOKEN_RE = re.compile("\x00L(\\d+)\x00")


def _site() -> str:
    return (getattr(config, "FRONTEND_URL", "") or "").rstrip("/") or "https://saplinglearn.com"


def link_values() -> dict[str, str]:
    """The link variables' URLs (the same for every recipient)."""
    return {"app_link": f"{_site()}/dashboard", "signin_link": _site()}


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


def _value(key: str, values: Mapping[str, str | None]) -> str:
    value = " ".join((values.get(key) or "").split())
    return value or (link_values()[key] if key in LINK_LABELS else "")


def fill(text: str, values: Mapping[str, str | None]) -> str:
    """Plain text: every known variable replaced by the recipient's value, its
    `|fallback`, or the built-in fallback, in that order. A link variable
    becomes its URL ("Label: URL" when the admin gave a label). Unknown
    variables are left exactly as typed (sends reject them before this runs)."""

    def sub(m: re.Match) -> str:
        key, given = m.group(1), m.group(2)
        if key not in _FALLBACKS:
            return m.group(0)
        value = _value(key, values)
        if key in LINK_LABELS:
            label = (given or "").strip()
            return f"{label}: {value}" if label else value
        if value:
            return value
        return given.strip() if given is not None else _FALLBACKS[key]

    return _VAR_RE.sub(sub, text or "")


def fill_for_html(text: str, values: Mapping[str, str | None]) -> tuple[str, list[tuple[str, str]]]:
    """Like `fill`, but each link variable becomes a placeholder token (see
    LINK_TOKEN_RE) so the template can draw it as a button or a labelled link
    AFTER escaping. Returns the text and the (url, label) of each token."""
    links: list[tuple[str, str]] = []
    # A NUL can't be typed in the composer, but the API would take one; drop
    # it so nothing but this function can make a link token.
    text = (text or "").replace("\x00", "")

    def sub(m: re.Match) -> str:
        key, given = m.group(1), m.group(2)
        if key not in LINK_LABELS:
            return fill(m.group(0), values)
        links.append((_value(key, values), (given or "").strip() or LINK_LABELS[key]))
        return f"\x00L{len(links) - 1}\x00"

    return _VAR_RE.sub(sub, text), links
