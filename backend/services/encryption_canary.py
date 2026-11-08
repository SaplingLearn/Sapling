"""Boot-time check that ENCRYPTION_KEY matches the database it is pointed at.

Every environment has its own ENCRYPTION_KEY, and services/encryption.py's
read helpers fail SOFT (a value they cannot open comes back as raw base64).
So a backend holding the wrong key does not error: it serves garbage and,
worse, re-encrypts whatever it writes under its own key, leaving rows the real
environment can never read. On 2026-10-21 a laptop running a feature branch
against prod's SUPABASE_URL did exactly that to one account's email, name and
OAuth tokens on a single sign-in.

The `encryption_key_check` table holds one known plaintext sealed under the
environment's key. The first backend to boot against an empty table seeds it;
every boot after that must be able to open it, or the lifespan raises and the
process never serves a request.

Only a definite mismatch is fatal. A missing table (code deployed ahead of its
migration), an unreachable database, or an empty read are logged and skipped:
whether the database is up is not this check's question.

Rotating ENCRYPTION_KEY: re-encrypt every 🔒 column, then delete the row so the
new key re-seeds it on the next boot.
"""

import logging
from urllib.parse import urlparse

import httpx

from config import SUPABASE_URL
from db.connection import table
from services.encryption import decrypt, encrypt

logger = logging.getLogger(__name__)

CANARY_PLAINTEXT = "sapling-encryption-key-check:v1"


class EncryptionKeyMismatch(RuntimeError):
    """ENCRYPTION_KEY cannot open the canary this database was seeded with."""


def _read_canary() -> str | None:
    rows = table("encryption_key_check").select("canary", filters={"id": "eq.1"})
    return rows[0].get("canary") if rows else None


def _check(canary: str) -> None:
    try:
        ok = decrypt(canary) == CANARY_PLAINTEXT
    except Exception:
        ok = False
    if not ok:
        host = urlparse(SUPABASE_URL or "").hostname or "<unset>"
        raise EncryptionKeyMismatch(
            f"ENCRYPTION_KEY does not match the database at {host}: it cannot "
            "decrypt that database's key canary, so every encrypted column there "
            "would read as garbage and every write would be unreadable to the "
            "real environment. Check that SUPABASE_URL and ENCRYPTION_KEY come "
            "from the SAME environment (a local backend belongs on the local "
            "stack or staging, never prod's SUPABASE_URL)."
        )


def verify_encryption_key() -> str:
    """Return "ok" | "seeded" | "skipped"; raise EncryptionKeyMismatch on a
    definite mismatch."""
    try:
        canary = _read_canary()
        if canary is None:
            # DO NOTHING on conflict: never overwrite a canary another key wrote.
            # Re-read either way, so losing a seed race to a different key is
            # caught here rather than on the next boot.
            table("encryption_key_check").upsert(
                {"id": 1, "canary": encrypt(CANARY_PLAINTEXT)},
                on_conflict="id",
                ignore_duplicates=True,
            )
            canary = _read_canary()
            if canary is None:
                logger.warning("encryption key check: canary could not be seeded; skipping")
                return "skipped"
            _check(canary)
            logger.info("encryption key check: seeded the key canary")
            return "seeded"
    except httpx.HTTPError as e:
        logger.warning("encryption key check skipped (%s): %s", type(e).__name__, e)
        return "skipped"
    _check(canary)
    return "ok"
