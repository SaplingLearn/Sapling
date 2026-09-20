"""Small, conservative decisions for tutor context assembly."""

from __future__ import annotations

import re


_NO_CONTEXT = re.compile(
    r"^(?:thanks?|thank you|thx|ok(?:ay)?|got it|understood|makes sense|"
    r"sounds good|perfect|great|cool|that helps|i see)[.!?,\s]*$",
    re.IGNORECASE,
)


def needs_context(message: str) -> bool:
    """Return whether a tutor turn needs course/RAG/graph context.

    This intentionally only skips short acknowledgement turns. Questions,
    follow-ups, and anything ambiguous keep the historical context behavior;
    the decision seam in #640 can replace this conservative heuristic later.
    """
    normalized = " ".join(message.split())
    return bool(normalized) and not _NO_CONTEXT.fullmatch(normalized)
