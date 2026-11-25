"""The `prompt_version` an agent stamps on its metadata and usage rows.

The first PROMPT_HASH_CHARS hex digits of the prompt text's sha256. Eval
cassettes key their freshness on it and the flag-off digests compare it, so
the rule (utf-8, sha256, that prefix length) must never change.
"""

from __future__ import annotations

import hashlib

#: Hex digits of the sha256 kept as the version.
PROMPT_HASH_CHARS = 12


def prompt_version(text: str) -> str:
    """The prompt's version: its sha256 (utf-8), first PROMPT_HASH_CHARS hex digits."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:PROMPT_HASH_CHARS]
