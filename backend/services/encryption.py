"""AES-256-GCM column-level encryption for sensitive Supabase columns.

The 32-byte key is loaded once from the ENCRYPTION_KEY env var (64 hex chars)
at import time. Every encrypt() call mints a fresh 12-byte nonce; the on-disk
representation is base64(nonce || ciphertext_with_tag).

Reads use the *_if_present helpers, which try to decrypt and fall back to the
raw input on failure — this lets legacy plaintext rows continue to load while
a backfill is pending. The fallback logs a warning so unintended plaintext
reads are visible.

ROLLOUT NOTES
─────────────
1. A backfill script is required before the legacy-plaintext fallback can be
   removed: walk every encrypted column listed in the marker pass and rewrite
   each row through encrypt_if_present / encrypt_json. Until that runs, every
   read on an old row will log a warning.
2. Two table columns must be retyped before encrypted writes succeed:
       assignments.points_possible NUMERIC -> TEXT
       assignments.points_earned   NUMERIC -> TEXT
       documents.concept_notes     JSONB   -> TEXT
   These migrations are tracked separately and are NOT part of this rollout.
3. messages.content, room_messages.text, and sessions.summary_json ARE
   encrypted — this note previously claimed otherwise, which was stale
   documentation rather than a real gap. All three are wired at write time
   (see the "🔒" markers in db/seed_local_rich.py, which calls
   encrypt_if_present for messages.content/room_messages.text and
   encrypt_json for sessions.summary_json) and are listed as encrypted in
   the root CLAUDE.md Gotchas section. frontend/e2e/tutor.spec.ts and
   frontend/e2e/study-room.spec.ts additionally assert ciphertext-at-rest
   for messages.content and room_messages.text against the live stack.
"""
from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)

_NONCE_BYTES = 12  # AES-GCM standard nonce length


def _load_key() -> bytes:
    raw = os.getenv("ENCRYPTION_KEY", "").strip()
    if not raw:
        raise RuntimeError(
            "ENCRYPTION_KEY env var is not set. Generate one with: "
            "python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    if len(raw) != 64:
        raise RuntimeError(
            f"ENCRYPTION_KEY must be 64 hex chars (32 bytes); got {len(raw)} chars."
        )
    try:
        key = bytes.fromhex(raw)
    except ValueError as e:
        raise RuntimeError("ENCRYPTION_KEY is not valid hex") from e
    if len(key) != 32:
        raise RuntimeError("ENCRYPTION_KEY must decode to exactly 32 bytes")
    return key


_KEY = _load_key()
_AESGCM = AESGCM(_KEY)


def encrypt(value: str) -> str:
    nonce = os.urandom(_NONCE_BYTES)
    ct = _AESGCM.encrypt(nonce, value.encode("utf-8"), None)
    return base64.b64encode(nonce + ct).decode("ascii")


def decrypt(value: str) -> str:
    raw = base64.b64decode(value)
    nonce, ct = raw[:_NONCE_BYTES], raw[_NONCE_BYTES:]
    return _AESGCM.decrypt(nonce, ct, None).decode("utf-8")


def encrypt_if_present(value: Any) -> str | None:
    if value is None:
        return None
    return encrypt(str(value))


def decrypt_if_present(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    try:
        return decrypt(value)
    except Exception as e:
        logger.warning("decrypt_if_present fallback to raw value: %s", e)
        return value


def decrypt_numeric(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(decrypt(value))
    except Exception as e:
        logger.warning("decrypt_numeric fallback: %s", e)
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


def encrypt_json(value: dict | list) -> str:
    return encrypt(json.dumps(value, separators=(",", ":")))


def decrypt_json(value: str) -> dict | list:
    try:
        return json.loads(decrypt(value))
    except Exception as e:
        logger.warning("decrypt_json fallback to plaintext: %s", e)
        try:
            return json.loads(value)
        except Exception:
            raise e


def decrypt_json_column(value: Any) -> Any:
    """Read-boundary guard for JSON columns that may hold either legacy
    plaintext JSONB (arrives as dict/list) or ciphertext (str). #521/#518."""
    if value is None or isinstance(value, (dict, list)):
        return value
    return decrypt_json(value)
