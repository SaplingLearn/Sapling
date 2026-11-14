"""Remove an account's stored third-party credentials (owner decision 2026-11-14).

A student's own account delete removes them AT ONCE, before the account is
hidden (routes/profile.py::delete_account); the 30-day purge
(services/account_purge.py) runs the same removal again, so a credential
written after the delete (none should be: the guard refuses a deleted
account's session) is still gone in the end.

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

import logging
import sys

import httpx

from db.connection import table
from services.encryption import decrypt

logger = logging.getLogger(__name__)

GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
_REVOKE_TIMEOUT_S = 10.0


def _plain(value) -> str | None:
    """A stored token decrypted, or None when absent or unreadable (an
    undecryptable value is never sent anywhere)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return decrypt(value) or None
    except Exception:
        return None


def remove_credentials(user_id: str) -> list[str]:
    """Delete `user_id`'s OAuth tokens and Gradescope credentials.

    Returns the Google tokens to revoke afterwards, refresh token first
    (revoking it ends the whole grant; the access token is the fallback).
    Raises on a database failure, so a caller can stop before hiding the
    account — the student can then retry the delete.
    """
    rows = table("oauth_tokens").select(
        "access_token,refresh_token", filters={"user_id": f"eq.{user_id}"},
    )
    row = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else {}
    tokens = [t for t in (_plain(row.get("refresh_token")), _plain(row.get("access_token"))) if t]
    table("oauth_tokens").delete(filters={"user_id": f"eq.{user_id}"})
    table("gradescope_credentials").delete(filters={"user_id": f"eq.{user_id}"})
    return list(dict.fromkeys(tokens))


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
        except Exception as exc:  # network, TLS, timeout: best effort
            logger.warning("[account] Google token revoke failed: %s", type(exc).__name__)
            continue
        if resp.status_code == 200:
            return True
        # 400 invalid_token: already revoked or expired; the next token may
        # still be live. Only the status is logged, never the token.
        logger.info("[account] Google token revoke answered %s", resp.status_code)
    return False
