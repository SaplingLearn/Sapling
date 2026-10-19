"""Content-free fallback redaction for attributes Logfire sends to its callback.

Agent content capture must also be disabled at the instrumentation source:
Logfire deliberately exempts several standard GenAI attributes from scrubbing.
This callback is defense in depth, not a sanitizer for arbitrary logging,
exception messages, span names or request URLs.
"""

from __future__ import annotations

import json
import re
from typing import Any

from logfire import ScrubMatch

from services.fingerprint import fingerprint_text


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
    r"system.?instructions",
    r"user_prompt",
    r"\bcontent\b",
    r"tool[._](?:arguments|response|result)",
    r"final_result",
)

_RISKY_RE = re.compile("|".join(EXTRA_PATTERNS), re.IGNORECASE)


def _path_is_risky(path: tuple[Any, ...] | str) -> bool:
    if isinstance(path, str):
        return bool(_RISKY_RE.search(path))
    return any(isinstance(part, str) and _RISKY_RE.search(part) for part in path)


def _sanitize(value: Any) -> str:
    """Replace the WHOLE value, including nested keys and non-string answers.

    No prefix survives, even for one-character or empty answers. Unsupported or
    cyclic objects fail closed without invoking their repr/str methods.
    """
    if isinstance(value, str):
        payload, kind, size = value, "string", len(value)
    else:
        try:
            payload = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError, RecursionError):
            return "[redacted]"
        kind = (
            "object"
            if isinstance(value, dict)
            else "array"
            if isinstance(value, (list, tuple))
            else "scalar"
        )
        size = len(value) if isinstance(value, (dict, list, tuple)) else 1
    fingerprint = fingerprint_text(payload, length=16)
    return f"[redacted, type:{kind}, length:{size}, sha256:{fingerprint}]"


def scrub_value(match: ScrubMatch) -> Any:
    """Redact routed content; delegate default secret patterns to Logfire."""
    if not _path_is_risky(match.path):
        return None
    return _sanitize(match.value)


def scrub_attribute(name: str, value: Any) -> Any:
    """Pure helper; does not imply Logfire routes every attribute here."""
    return _sanitize(value) if _path_is_risky(name) else value
