"""Stable, short content fingerprints for log correlation.

Use case: we want to log a value (a prompt body, a quiz answer, a span
attribute) without putting the actual content in stdout. A truncated
SHA-256 is short enough for greppability and stable enough that the
same input fingerprints to the same string across runs and machines.

This is correlation-only — NOT a security boundary. Truncation makes
collisions theoretically possible (~2^48 inputs at 12 hex chars) but
the use sites only need "if I see fp=abc123def456 again, that's the
same drift." Adversarial collisions don't matter.
"""

from __future__ import annotations

import hashlib

# ASCII unit-separator. Won't appear in any user-typed text (concept
# names, quiz options, prompt bodies), so joining a list with this
# avoids the ambiguity that `|` introduces when items contain pipes.
SEPARATOR = "\x1f"


def fingerprint(*parts: str | int | float | bool | None, length: int = 12) -> str:
    """Return a short, stable fingerprint of `parts` joined by SEPARATOR.

    Each part is str()'d. None becomes the empty string. Lists/tuples
    are flattened with the same separator (one level deep). Output is
    `length` lowercase hex chars (default 12 = 48 bits).

        >>> fingerprint("hello", "world")  # noqa
        '...'  # 12 hex chars
        >>> fingerprint("hello", "world") == fingerprint("hello", "world")
        True
    """
    flat: list[str] = []
    for p in parts:
        if isinstance(p, (list, tuple)):
            flat.append(SEPARATOR.join("" if x is None else str(x) for x in p))
        else:
            flat.append("" if p is None else str(p))
    body = SEPARATOR.join(flat)
    digest = hashlib.sha256(body.encode("utf-8", errors="replace")).hexdigest()
    return digest[:length]


def fingerprint_text(value: str, length: int = 16) -> str:
    """Single-string convenience used by the Logfire scrubber. Default
    length is 16 chars (64 bits) for that callsite's redaction-trace
    use; quiz drift logs use the 12-char form via `fingerprint(...)`.
    """
    return hashlib.sha256(
        value.encode("utf-8", errors="replace"),
    ).hexdigest()[:length]
