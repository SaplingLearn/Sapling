"""Who has access: the waitlist gate and the `open_access` flag.

docs/design/open-access-gate.md. Access is COMPUTED, never migrated:

    has access = is_approved
                 OR (open_access is on AND open_access_at IS NOT NULL)

`users.is_approved` is an admin's approval (Admin → Allowlist, or local dev's
auto-approve). `users.open_access_at` marks an account that came in through
the open gate without one; it is what tells such an account apart from one an
admin removed (both have `is_approved = false`), so Remove access and an
Allowlist revoke clear it. Flipping the flag therefore writes nothing:
closing the gate puts every open-access account back on the waitlist, and
opening it again lets them back in.

The flag is resolved GLOBALLY (a new person has no id at sign-in) and fails
closed: an unreadable flag store reads as "off", the gated side.

The email domain decides nothing here. `is_school_email` is a label for
Admin → Allowlist ("Non-BU"), nothing else.
"""
from __future__ import annotations

from services.feature_flags import flag_on

FLAG = "open_access"

ACCESS_APPROVED = "approved"
ACCESS_OPEN = "open"
ACCESS_NONE = "none"

#: The school's email domains, for the "Non-BU" label only. A subdomain
#: (cs.bu.edu) counts.
SCHOOL_EMAIL_DOMAINS: tuple[str, ...] = ("bu.edu",)


def gate_open() -> bool:
    """Whether the waitlist requirement is lifted right now (may read the
    flag store; call it off the event loop or where a sync read is fine)."""
    return flag_on(FLAG, None)


def access_kind(row: dict, *, open_now: bool) -> str:
    """`approved` | `open` | `none` for a `users` row carrying `is_approved`
    and `open_access_at`. Deletion is the caller's business."""
    if row.get("is_approved"):
        return ACCESS_APPROVED
    if open_now and row.get("open_access_at"):
        return ACCESS_OPEN
    return ACCESS_NONE


def has_access(row: dict, *, open_now: bool) -> bool:
    return access_kind(row, open_now=open_now) != ACCESS_NONE


def access_filter(*, open_now: bool) -> dict[str, str]:
    """PostgREST filters for "has access" (callers add `deleted_at` etc.).
    Uses the `or` key, so a caller must not need one of its own."""
    if open_now:
        return {"or": "(is_approved.eq.true,open_access_at.not.is.null)"}
    return {"is_approved": "eq.true"}


def is_school_email(email: str | None) -> bool:
    domain = (email or "").strip().lower().rsplit("@", 1)[-1]
    if not domain or "@" not in (email or ""):
        return False
    return any(domain == d or domain.endswith("." + d) for d in SCHOOL_EMAIL_DOMAINS)
