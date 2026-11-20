"""Per-export pseudonyms for the trial's long table.

An id leaves the database only as HMAC-SHA256(salt, kind || parts), truncated
to 64 bits, under a salt drawn fresh for every export (32 bytes from
`secrets`) and never written, printed or pickled. Within one export equal
inputs map to equal pseudonyms, so the crossed student x concept structure
survives; across exports nothing links, so one export cannot be joined to
another, or back to the database, by id.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

PREFIXES = {"student": "s_", "course": "c_", "concept": "k_", "item": "i_"}
#: hex digits kept per pseudonym (64 bits: collision-free at trial scale)
DIGEST_HEX = 16
SALT_BYTES = 32


class Pseudonymizer:
    """`p("student", user_id)` -> "s_<16 hex>"; `p("concept", course_id, key)`
    -> "k_<16 hex>". The salt is private to the instance."""

    __slots__ = ("_salt",)

    def __init__(self, salt: bytes | None = None) -> None:
        salt = secrets.token_bytes(SALT_BYTES) if salt is None else salt
        if not isinstance(salt, bytes) or len(salt) < 16:
            raise ValueError("salt must be at least 16 bytes")
        self._salt = salt

    def __call__(self, kind: str, *parts: str) -> str:
        prefix = PREFIXES.get(kind)
        if prefix is None:
            raise ValueError(f"unknown pseudonym kind {kind!r}")
        if not parts or any(not isinstance(p, str) or not p for p in parts):
            raise ValueError("pseudonym parts must be non-empty strings")
        message = "\x1f".join((kind, *parts)).encode("utf-8")
        return prefix + hmac.new(self._salt, message, hashlib.sha256).hexdigest()[:DIGEST_HEX]

    def __repr__(self) -> str:
        return "Pseudonymizer(salt=<hidden>)"

    def __reduce__(self):
        raise TypeError("a Pseudonymizer cannot be pickled: its salt must not leave the process")
