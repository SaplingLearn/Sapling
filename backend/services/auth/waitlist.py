"""The landing-page waitlist (``newsletter_emails``) as sign-in and /pending
see it (#118, moved from ``routes/auth.py``)."""
import logging

from db.connection import like_literal, pg_quote_value, table
from services.encryption import encrypt

logger = logging.getLogger(__name__)


def _waitlist_entries(email: str, columns: str = "id,email,approved_at,joined_at") -> list[dict]:
    """Every waitlist row (`newsletter_emails`) for `email`, approved first.

    Case-insensitive, because the waitlist keeps the email as typed — so one
    address can have case twins, and every admin write (approve, revoke,
    unapprove) must reach all of them or it can miss the row sign-in reads.
    Re-checked in Python because PostgREST rewrites `*` to a wildcard that
    `like_literal` cannot escape. Raises on a lookup error: the caller decides
    whether that fails closed (sign-in) or loud (an admin write).
    """
    wanted = email.strip().lower()
    if not wanted:
        return []
    needle = pg_quote_value(like_literal(wanted))
    rows = table("newsletter_emails").select(
        columns, filters={"or": f"(email.ilike.{needle})"},
    )
    matches = [r for r in rows or [] if (r.get("email") or "").strip().lower() == wanted]
    # Two rows can differ only by case; prefer an approved one.
    matches.sort(key=lambda r: not r.get("approved_at"))
    return matches


def _waitlist_entry(email: str) -> dict | None:
    """The landing-page waitlist row (`newsletter_emails`) for `email`, if any.

    Admin → Allowlist sets its `approved_at` (`POST /api/admin/allowlist/approve`),
    which lets the student in on their first sign-in instead of an admin
    approving the `users` row after they hit /pending; `joined_at` records that
    they actually got in. Of case twins, the approved one wins. Fails closed: a
    lookup error reads as "not on the waitlist", leaving the user pending
    rather than breaking sign-in.
    """
    try:
        matches = _waitlist_entries(email)
    except Exception:
        logger.warning("waitlist lookup failed", exc_info=True)
        return None
    return matches[0] if matches else None


def _mark_waitlist_joined(entry_id: str, user_id: str) -> None:
    """Stamp the waitlist row as joined. Best-effort: never breaks sign-in."""
    from datetime import datetime, timezone
    try:
        table("newsletter_emails").update(
            {"joined_user_id": user_id, "joined_at": datetime.now(timezone.utc).isoformat()},
            filters={"id": f"eq.{entry_id}", "joined_at": "is.null"},
        )
    except Exception:
        logger.warning("waitlist joined stamp failed", exc_info=True)


def _pending_standing(email: str, entry: dict | None) -> dict:
    """The /pending view of `email`: on the waitlist at all, and approved yet.

    `approved` lets /pending say "you're in — sign in again" once an admin
    approves the address while the student sits on the page: the pending token
    is not a session, so only a fresh sign-in can let them in.
    """
    return {
        "email": email,
        "on_waitlist": entry is not None,
        "approved": bool(entry and entry.get("approved_at")),
    }


def join_waitlist(email: str, first_name: str, entry: dict | None) -> None:
    """Put `email` on the waitlist (`entry` = its current row, if any), or
    fill in a missing first name. Idempotent; raises on a write error."""
    if entry is None:
        # The first name (from Google) lets the "you're in" email greet them.
        table("newsletter_emails").upsert(
            {"email": email, "first_name": encrypt(first_name) if first_name else None},
            on_conflict="email",
        )
    elif first_name:
        table("newsletter_emails").update(
            {"first_name": encrypt(first_name)},
            filters={"id": f"eq.{entry['id']}", "first_name": "is.null"},
        )
