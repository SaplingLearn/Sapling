"""Logfire scrubber that redacts user content from agent spans.

Pydantic AI's logfire integration writes the full prompt text and model
output to span attributes. For Sapling that means uploaded document
text — which contains user names, email addresses, course materials,
sometimes student work — flowing to logfire.pydantic.dev.

This scrubber redacts the highest-risk attributes BEFORE they leave
the process. Truncates to a length cap and hashes content past it,
so we keep a fingerprint for debugging without shipping the body.

Wiring: applied via ``logfire.configure(scrubbing=ScrubbingOptions(
callback=scrub_value, extra_patterns=EXTRA_PATTERNS))``. The callback
fires only when an attribute path matches one of our patterns OR a
default Logfire pattern (password, secret, api[._ -]?key, ...). For
attributes that match, the callback returns the sanitized value; for
default-pattern matches, returning the value unchanged keeps Logfire's
normal behavior of fully redacting it.

See https://logfire.pydantic.dev/docs/how-to-guides/scrubbing/ for the
ScrubbingOptions API surface.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from logfire import ScrubMatch


# Path components that indicate the value contains user-supplied prompt
# text or model output. These are matched against any segment of the
# JsonPath the scrubber walks (e.g. ('attributes', 'gen_ai.prompt'),
# ('attributes', 'all_messages_events', 0, 'content')). Conservative —
# easier to add safe attrs to the allowlist than to retract a leak.
_RISKY_PATH_TOKENS = (
    "input.value",
    "output.value",
    "ai.input.messages",
    "ai.output.value",
    "gen_ai.prompt",
    "gen_ai.completion",
    "all_messages_events",
    "events",
    "messages",
    "user_prompt",
    "prompt",
    "completion",
    "content",
)

# Compiled into a single regex so it can also be passed to Logfire as
# `extra_patterns` — making sure the callback fires for these names even
# when the default pattern set wouldn't match.
EXTRA_PATTERNS: tuple[str, ...] = (
    r"prompt",
    r"completion",
    r"messages",
    r"all_messages_events",
    r"input\.value",
    r"output\.value",
    r"ai\.input\.messages",
    r"ai\.output\.value",
    r"gen_ai\.prompt",
    r"gen_ai\.completion",
    r"user_prompt",
    r"\bcontent\b",
)

# Header of the truncated body; rest replaced with a content hash.
_PREVIEW_CHARS = 80

_RISKY_RE = re.compile("|".join(EXTRA_PATTERNS), re.IGNORECASE)


def _fingerprint(value: str) -> str:
    """Short, stable hash for matching a redacted body to a re-uploaded copy."""
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:16]


def _path_is_risky(path: tuple[Any, ...] | str) -> bool:
    """True if any segment of the JsonPath looks like a prompt/output attr."""
    if isinstance(path, str):
        return bool(_RISKY_RE.search(path))
    for seg in path:
        if isinstance(seg, str) and _RISKY_RE.search(seg):
            return True
    return False


def _sanitize(value: Any, path: tuple[Any, ...] | str) -> Any:
    """Truncate strings, recurse into lists/dicts."""
    if isinstance(value, str):
        if len(value) <= _PREVIEW_CHARS:
            return value
        return (
            f"{value[:_PREVIEW_CHARS]}…[redacted, {len(value)} chars, "
            f"sha256:{_fingerprint(value)}]"
        )
    if isinstance(value, list):
        return [_sanitize(v, path) for v in value]
    if isinstance(value, dict):
        return {k: _sanitize(v, path) for k, v in value.items()}
    return value


def scrub_value(match: ScrubMatch) -> Any:
    """Logfire scrubber callback.

    Returning ``None`` lets Logfire perform its default redaction (full
    replacement with ``[Scrubbed due to '<pattern>']``). Returning the
    sanitized value short-circuits Logfire's redaction and keeps the
    truncated/fingerprinted form.

    For attributes whose path looks like prompt/output content we return
    a truncated form with a sha256 fingerprint. For everything else
    (e.g. default-pattern matches like "password" or "api_key") we
    return ``None`` so Logfire applies its normal full redaction.
    """
    path = match.path
    if not _path_is_risky(path):
        # Let Logfire's default behavior win — most likely a sensitive
        # word (password, secret, ...) that we don't want to preserve at
        # all.
        return None
    return _sanitize(match.value, path)


# Back-compat / direct-call helper used by the unit test. Keeps the
# pure transformation testable without constructing a ScrubMatch.
def scrub_attribute(name: str, value: Any) -> Any:
    """Pure transformation entry point used by tests and ad-hoc callers."""
    if not _path_is_risky(name):
        return value
    return _sanitize(value, name)
