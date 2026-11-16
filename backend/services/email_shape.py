"""A loose "is this one email address" check that is safe on hostile input.

Shared by the public careers form and the admin allowlist bodies. Two rules
make it safe on a 1 MB form field:

* the LENGTH is checked before any pattern runs, so the pattern only ever
  sees a short string;
* the pattern is linear anyway: the domain's first label excludes ".", so
  there is exactly one way to split ``label.rest``. The old shape,
  ``[^@\\s]+@[^@\\s]+\\.[^@\\s]+``, let the engine try every dot in the
  domain as the split point, and on ``"a@" + "." * N + " "`` that is
  quadratic (a 1 MB value pinned a uvicorn worker for about 50 minutes).

The one behaviour change from the old shape: a domain that STARTS with a
dot (``a@.b.c``) is refused, which no deliverable address does.
"""
from __future__ import annotations

import re

#: RFC 5321's practical ceiling for a whole address.
MAX_EMAIL_LEN = 320

#: Characters neither part may contain beyond "@" and whitespace, per caller.
_PATTERNS: dict[str, re.Pattern[str]] = {}


def _pattern(extra_forbidden: str) -> re.Pattern[str]:
    pat = _PATTERNS.get(extra_forbidden)
    if pat is None:
        cls = "@\\s" + re.escape(extra_forbidden)
        pat = re.compile(rf"^[^{cls}]+@[^{cls}.]+\.[^{cls}]+$")
        _PATTERNS[extra_forbidden] = pat
    return pat


def is_email_shape(value: str, *, max_len: int = MAX_EMAIL_LEN, extra_forbidden: str = "") -> bool:
    """True when ``value`` is one address: one "@", no whitespace (nor any of
    ``extra_forbidden``), a dot inside the domain, at most ``max_len`` chars.
    Length first, then a linear pattern."""
    if not value or len(value) > max_len:
        return False
    return _pattern(extra_forbidden).match(value) is not None
