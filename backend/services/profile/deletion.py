"""A student's own account delete (#118, moved from ``routes/profile.py``).

``DELETE /api/profile/{user_id}/account`` checks the session and maps
:class:`DeletionNotConfirmed` to its 400; everything else is here.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable

from db.connection import table
from db.scope import service_scope
from services.account_credentials import delete_credentials, google_tokens, revoke_google_tokens
from services.analytics_consent import clear_analytics_consent_cache
from services.auth_guard import clear_account_state_cache
from services.posthog_client import delete_person as delete_posthog_person
from services.profile.errors import DeletionNotConfirmed

logger = logging.getLogger(__name__)

#: What the student types to confirm the delete.
CONFIRMATION = "DELETE"


def delete_account(
    user_id: str,
    confirmation: str,
    *,
    after_response: Callable[..., object],
) -> dict:
    """Hide `user_id`'s account and remove its credentials now.

    `after_response(fn, *args)` schedules `fn(*args)` to run after the
    response (the route passes ``BackgroundTasks.add_task``). Raises
    :class:`DeletionNotConfirmed` unless `confirmation` is ``"DELETE"``; a
    database failure before the account is hidden propagates (a 500 the
    student retries, with nothing removed yet).
    """
    if confirmation != CONFIRMATION:
        raise DeletionNotConfirmed(f"Confirmation must be '{CONFIRMATION}'")

    # #115: the soft delete is account state (`users` is SELECT-only for the
    # student's token) -> service role.
    with service_scope():
        # Owner decision 2026-11-14: the Google tokens and the Gradescope
        # login go NOW, not with the 30-day purge (services/account_purge.py).
        # Read the tokens to revoke, but delete nothing until the account is
        # hidden: a failure up to the hide is a 500 the student retries, and
        # the retry must still find the tokens, or the Google grant would
        # stay live with nothing left to revoke it.
        tokens = google_tokens(user_id)
        table("users").update(
            {"deleted_at": datetime.now(timezone.utc).isoformat()},
            filters={"id": f"eq.{user_id}"},
        )
    try:
        with service_scope():
            delete_credentials(user_id)
    except Exception as exc:
        # The account is hidden, so the guard refuses a retry. Do not fail
        # the delete that happened: the grant is still revoked below with the
        # tokens read above, and the purge removes the leftover rows.
        logger.warning("[account] credential delete failed after the soft delete: %s",
                       type(exc).__name__)
    # ADR 0028: from here on the PostHog worker's consent check reads
    # deleted_at, so nothing — not even items already queued — names this user
    # (which would re-create the person the delete below removes). Drop the
    # cached "allowed" answer now.
    clear_analytics_consent_cache(user_id)
    # #756: the auth guard refuses a deleted account; drop its cached "active"
    # answer so this process stops honouring the session now, not at the TTL.
    clear_account_state_cache(user_id)
    # Best-effort PostHog person + event delete, AFTER the response so it adds
    # no latency and cannot fail the deletion (it never raises; unconfigured
    # -> WARN + skip). It drains our queue and the SDK's first, and repeats
    # after the consent TTL. Only reached once the soft delete landed.
    after_response(delete_posthog_person, user_id)
    # Revoke the Google grant itself (best effort, never raises): our copy of
    # the tokens is gone (or goes with the purge), this ends Sapling's access
    # at Google.
    after_response(revoke_google_tokens, tokens)
    return {"deleted": True}
