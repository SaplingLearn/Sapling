"""
backend/services/admin/users.py

Admin user access: remove a user's access and put them back on the
waitlist. The waitlist read goes through the auth package
(``services.auth.waitlist_entries``).

Moved verbatim out of ``routes/admin.py`` (#118); the route keeps the
auth checks and maps ``services.admin.errors`` to HTTP statuses.
"""
from __future__ import annotations

import logging

import services.auth as auth_service
from db.connection import table
from services.admin.errors import Conflict
from services.auth_guard import clear_account_state_cache
from services.admin_audit import log_admin_action
from services.encryption import decrypt_if_present

logger = logging.getLogger(__name__)


def _back_on_waitlist(email: str, user_id: str) -> None:
    """Put `email` back on the waitlist as an unapproved signup, so a user whose
    access was removed shows up in Admin → Allowlist. Every case twin is reset,
    and each keeps `joined_user_id` pointing at the account: users.email is
    encrypted with a per-call nonce, so that link is the only way approving the
    entry again can reach the account (#757). Best-effort: access is already
    gone."""
    try:
        twins = auth_service.waitlist_entries(email, "id,email,approved_at")
        if twins:
            table("newsletter_emails").update(
                {"approved_at": None, "joined_at": None, "joined_user_id": user_id},
                filters={"id": f"in.({','.join(r['id'] for r in twins)})"},
            )
        else:
            table("newsletter_emails").upsert(
                {"email": email.strip().lower(), "joined_user_id": user_id},
                on_conflict="email",
            )
    except Exception:
        logger.warning("could not put a removed user back on the waitlist", exc_info=True)


def unapprove_user(user_id: str, actor: str | None):
    """Remove a user's access. They leave Admin → Users and reappear in
    Admin → Allowlist as a signup; their account and data are kept."""
    if user_id == actor:
        raise Conflict("You cannot remove your own access.")
    rows = table("users").update({"is_approved": False}, filters={"id": f"eq.{user_id}"})
    clear_account_state_cache(user_id)  # #756: the guard refuses it now, not at the TTL
    email = (decrypt_if_present((rows or [{}])[0].get("email")) or "").strip()
    if "@" in email:
        _back_on_waitlist(email, user_id)
    log_admin_action(actor_id=actor, action="user.unapprove", target_type="user", target_id=user_id)
    return {"unapproved": True}
