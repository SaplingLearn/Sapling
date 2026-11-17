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

Scripts that WRITE encrypted data (backfills, seeders, catalog ingest) are
stricter than the server: ``require_key_for_write`` aborts them unless the
canary positively opens. A missing table, an unreachable database or an empty
canary all abort too, because ``db/backfill_encryption.py --apply`` treats
every value it cannot decrypt as plaintext and encrypts it, so one run under
the wrong key double-encrypts a whole environment beyond recovery. Only the
seeders that build a FRESH database (``allow_seed=True``) may seed an empty
canary, exactly as the first server boot would.
"""

import logging
import sys
from urllib.parse import urlparse

import httpx

from config import SUPABASE_URL
from db.connection import table
from services.encryption import bind, decrypt, encrypt

logger = logging.getLogger(__name__)

CANARY_PLAINTEXT = "sapling-encryption-key-check:v1"

#: The canary's AES-GCM binding (docs/security/encryption-aad-plan.md). A seed
#: is ALWAYS v1, whatever ENCRYPTION_WRITE_V2 says, and a read always accepts
#: the legacy v1 canary, whatever ENCRYPTION_LEGACY_READS says: it is a key
#: check, not data, and the AAD backfill never rewrites it. A v2 canary would
#: make a rollback to pre-v2 code (which cannot parse ``enc2:``) refuse to
#: boot. A v2 canary seeded by an older build still verifies.
CANARY_BINDING = bind("encryption_key_check", "canary", 1)


class EncryptionKeyMismatch(RuntimeError):
    """ENCRYPTION_KEY cannot open the canary this database was seeded with."""


class EncryptionKeyUnverified(RuntimeError):
    """A write-mode script could not positively verify ENCRYPTION_KEY."""


def _read_canary() -> str | None:
    rows = table("encryption_key_check").select("canary", filters={"id": "eq.1"})
    return rows[0].get("canary") if rows else None


def _check(canary: str) -> None:
    try:
        ok = decrypt(canary, bind=CANARY_BINDING, allow_legacy=True) == CANARY_PLAINTEXT
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


def verify_encryption_key(*, seed: bool = True) -> str:
    """Return "ok" | "seeded" | "skipped" (| "absent" when ``seed`` is False
    and the table holds no canary); raise EncryptionKeyMismatch on a definite
    mismatch."""
    try:
        canary = _read_canary()
        if canary is None and not seed:
            return "absent"
        if canary is None:
            # DO NOTHING on conflict: never overwrite a canary another key wrote.
            # Re-read either way, so losing a seed race to a different key is
            # caught here rather than on the next boot.
            table("encryption_key_check").upsert(
                {"id": 1, "canary": encrypt(CANARY_PLAINTEXT, bind=CANARY_BINDING, v2=False)},
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


def require_key_for_write(script: str, *, allow_seed: bool = False) -> str:
    """Abort a write-mode script unless ENCRYPTION_KEY provably matches the
    database; return the canary status ("ok", or "seeded" under
    ``allow_seed``).

    Raises EncryptionKeyMismatch on a mismatch and EncryptionKeyUnverified
    on anything short of a positive check (no table, database unreachable,
    no canary). ``allow_seed`` is for seeders that build a fresh database:
    an empty canary is then seeded with this key, as the first server boot
    would. A backfill over existing rows never passes it.
    """
    host = urlparse(SUPABASE_URL or "").hostname or "<unset>"
    try:
        status = verify_encryption_key(seed=allow_seed)
    except EncryptionKeyMismatch:
        logger.error("%s: ENCRYPTION_KEY does not match the database at %s; aborting", script, host)
        raise
    except Exception as e:  # missing table, auth, config: anything but a pass
        raise EncryptionKeyUnverified(
            f"{script}: could not verify ENCRYPTION_KEY against {host} "
            f"({type(e).__name__}); refusing to write. Run against a reachable "
            "database whose encryption_key_check canary this key opens."
        ) from e
    allowed = ("ok", "seeded") if allow_seed else ("ok",)
    if status not in allowed:
        reason = {
            "skipped": "the database or its encryption_key_check table was unreachable",
            "absent": "encryption_key_check holds no canary (boot a backend on this "
                      "environment's key first, so it seeds one)",
        }.get(status, status)
        raise EncryptionKeyUnverified(
            f"{script}: ENCRYPTION_KEY is unverified against {host}: {reason}; refusing to write."
        )
    logger.info("%s: ENCRYPTION_KEY verified against %s (%s)", script, host, status)
    return status


def abort_unless_key_verified(script: str, *, allow_seed: bool = False) -> None:
    """CLI form of ``require_key_for_write``: print why and exit 2."""
    try:
        require_key_for_write(script, allow_seed=allow_seed)
    except (EncryptionKeyMismatch, EncryptionKeyUnverified) as e:
        print(f"ABORT: {e}", file=sys.stderr)
        raise SystemExit(2) from e
