"""Remove an account's stored third-party credentials (owner decision 2026-11-14).

A student's own account delete removes them AT ONCE
(services/profile/deletion.py::delete_account): it reads the Google tokens
(:func:`google_tokens`), hides the account, then deletes the rows
(:func:`delete_credentials`) and revokes the grant with the tokens it read.
Nothing is deleted before the hide, so a failed hide is a 500 whose retry
still finds the tokens to revoke. A row delete that fails AFTER the hide is
retried, with backoff, by the after-response task that revokes the grant
(:func:`finish_removal`); and the daily purge pass
(services/account_purge_sweeper.py::sweep_leftover_credentials) removes the
credentials any soft-deleted account still holds
(:func:`deleted_accounts_with_credentials`), with no grace period, so a
credential the delete could not remove is gone within a day. The 30-day
purge (services/account_purge.py) runs the removal once more
(:func:`remove_credentials`).

* ``oauth_tokens`` — the Google sign-in / Calendar grant. Its tokens are
  read (and decrypted) before the row goes so the grant can be REVOKED at
  Google afterwards: deleting our copy alone would leave Sapling's access to
  the student's Google account live until they removed it themselves.
* ``gradescope_credentials`` — the student's Gradescope login.

Revocation (:func:`revoke_google_tokens`) is best effort and never raises: it
runs after the response, and a failed revoke must never undo or block the
delete. It does not run under pytest or outside real model mode (the E2E
stacks hold fake tokens), the same gate the PostHog seam uses.

Google's revoke endpoint is a third-party REST call, not Supabase access, so
it uses ``httpx`` directly (the CLAUDE.md exception for small, obviously
non-Supabase calls). Nothing about a token is ever logged.
"""
from __future__ import annotations

import asyncio
import logging
import sys

import httpx

from db.connection import table
from db.scope import runs_as_service
from services.encryption import decrypt

logger = logging.getLogger(__name__)

GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
_REVOKE_TIMEOUT_S = 10.0

#: The tables that hold a student's third-party credentials (one row each).
CREDENTIAL_TABLES = ("oauth_tokens", "gradescope_credentials")
#: The wait before each after-response retry of a failed credential delete.
DELETE_RETRY_DELAYS_S = (2.0, 8.0)
#: Most credential rows per table one purge pass looks at.
LEFTOVER_SCAN_LIMIT = 500

_sleep = asyncio.sleep  # seam: tests do not wait out the backoff


def _plain(value) -> str | None:
    """A stored token decrypted, or None when absent or unreadable (an
    undecryptable value is never sent anywhere)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return decrypt(value) or None
    except Exception:  # noqa: BLE001 — an unreadable token is never sent anywhere
        return None


def google_tokens(user_id: str) -> list[str]:
    """`user_id`'s stored Google tokens, decrypted, to revoke: refresh token
    first (revoking it ends the whole grant; the access token is the
    fallback). Reads only. Raises on a database failure."""
    rows = table("oauth_tokens").select(
        "access_token,refresh_token", filters={"user_id": f"eq.{user_id}"},
    )
    row = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else {}
    tokens = [t for t in (_plain(row.get("refresh_token")), _plain(row.get("access_token"))) if t]
    return list(dict.fromkeys(tokens))


def delete_credentials(user_id: str) -> None:
    """Delete `user_id`'s OAuth tokens and Gradescope credentials. Raises on
    a database failure. Read :func:`google_tokens` FIRST: once the row is
    gone nothing can revoke the grant."""
    table("oauth_tokens").delete(filters={"user_id": f"eq.{user_id}"})
    table("gradescope_credentials").delete(filters={"user_id": f"eq.{user_id}"})


@runs_as_service
async def _retry_delete(user_id: str) -> bool:
    """Retry :func:`delete_credentials` with backoff. True once it lands;
    False (logged with the user id) when every retry failed. Never raises.

    The backoff is an ``asyncio.sleep`` and each (sync) delete runs on a
    worker thread, so the retries hold neither the event loop nor a
    threadpool worker while they wait. Service role (carried into the
    thread with the context): it runs after the account delete's response,
    where the request's (now deleted) student scope would still apply."""
    error = "none"
    for delay in DELETE_RETRY_DELAYS_S:
        await _sleep(delay)
        try:
            await asyncio.to_thread(delete_credentials, user_id)
            return True
        except Exception as exc:  # noqa: BLE001 — never raises; logged after the last retry
            error = type(exc).__name__
    logger.error(
        "[account] credentials of deleted account %s are still stored after %d retries (%s);"
        " the daily purge pass removes them", user_id, len(DELETE_RETRY_DELAYS_S), error,
    )
    return False


async def finish_removal(user_id: str, tokens: list[str], *, retry_delete: bool) -> None:
    """The account delete's after-response half: an ``async def``, so
    Starlette awaits it on the loop instead of parking a threadpool worker
    for the whole backoff. Never raises.

    `retry_delete`: the delete could not remove the credential rows, so retry
    that first (:func:`_retry_delete`). Then revoke the grant with `tokens`
    (read before the account was hidden), whether or not the rows went; the
    revoke is a blocking HTTP call, so it runs on a worker thread."""
    if retry_delete:
        await _retry_delete(user_id)
    try:
        await asyncio.to_thread(revoke_google_tokens, tokens)
    except Exception as exc:  # noqa: BLE001 — revoke never raises; this keeps the promise if it ever does
        logger.warning("[account] Google token revoke for %s failed: %s", user_id, type(exc).__name__)


def deleted_accounts_with_credentials(limit: int = LEFTOVER_SCAN_LIMIT) -> list[str]:
    """Soft-deleted accounts that still hold a credential row: a delete that
    could not remove it (or a row written after it). Any age, not only past
    the purge's grace. Raises on a database failure."""
    owners: list[str] = []
    for name in CREDENTIAL_TABLES:
        rows = table(name).select(
            "user_id,users!inner(deleted_at)",
            filters={"users.deleted_at": "not.is.null"},
            limit=limit,
        ) or []
        # Re-check the embed: a non-`!inner` regression would return every
        # live account's row with a null `deleted_at`, and those must never
        # be removed.
        owners += [
            r["user_id"] for r in rows
            if isinstance(r, dict) and r.get("user_id")
            and isinstance(r.get("users"), dict) and r["users"].get("deleted_at")
        ]
    return list(dict.fromkeys(owners))


def remove_credentials(user_id: str) -> list[str]:
    """Read the Google tokens, then delete both credential rows. Returns the
    tokens to revoke afterwards. Raises on a database failure."""
    tokens = google_tokens(user_id)
    delete_credentials(user_id)
    return tokens


def _revoke_disabled() -> bool:
    from agents._providers import model_mode  # lazy: pulls in pydantic-ai

    return "pytest" in sys.modules or model_mode() != "real"


def revoke_google_tokens(tokens: list[str]) -> bool:
    """Revoke the Google grant behind `tokens` (tried in order until one is
    accepted). True when Google accepted one. Never raises."""
    if not tokens or _revoke_disabled():
        return False
    for token in tokens:
        try:
            resp = httpx.post(
                GOOGLE_REVOKE_URL, data={"token": token},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=_REVOKE_TIMEOUT_S,
            )
        except Exception as exc:  # noqa: BLE001 — network, TLS, timeout: best effort, never raises
            logger.warning("[account] Google token revoke failed: %s", type(exc).__name__)
            continue
        if resp.status_code == 200:
            return True
        # 400 invalid_token: already revoked or expired; the next token may
        # still be live. Only the status is logged, never the token.
        logger.info("[account] Google token revoke answered %s", resp.status_code)
    return False
