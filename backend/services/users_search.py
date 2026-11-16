"""
Paginated user listing for the admin portal.

Without a search query, we paginate at the DB layer (offset+limit) and decrypt
only the page we return. With a search query, we have to decrypt the whole
table because users.name and users.email use AEAD with random nonces and are
not directly searchable. This is acceptable at admin scale and lives behind
require_admin.
"""

import base64
import binascii
from typing import Optional

from db.connection import table
from db.scope import runs_as_service
from services.encryption import bind, decrypt_if_present
from services.profiles import get_display_names

_DEFAULT_PAGE_SIZE = 50
_MAX_PAGE_SIZE = 200

# After migration 0024 the display `name` lives on user_profiles, not users.
_USERS_COLS = "id,email,is_approved,created_at,last_sign_in_at"
# Admin → Users lists the people who have access. Everyone waiting on approval
# lives in Admin → Allowlist (the waitlist), so the two pages never overlap.
_APPROVED = {"is_approved": "eq.true"}

# base64(12-byte nonce || ciphertext || 16-byte GCM tag): the shortest blob
# services/encryption.py can write. A decrypted email/name never looks like one.
_MIN_CIPHERTEXT_BYTES = 12 + 16


#: ids per `in.(…)` filter — keeps the query string bounded, the same ceiling
#: account_bundle / account_summary / admin.allowlist use.
_IN_CHUNK = 50

_ROLE_COLS = (
    "roles(id,name,slug,color,icon,description,"
    "is_staff_assigned,is_earnable,display_priority)"
)


def _chunks(items: list[str], size: int = _IN_CHUNK):
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _attach_roles(users: list[dict]) -> None:
    """Attach each user's roles, in one query per CHUNK rather than per user.

    This read was `for user in users: table("user_roles").select(... eq.id)` —
    one PostgREST round-trip per row. `page_size` goes up to 200, so a single
    admin page load could issue 200 sequential queries and wait for all of
    them in series. Batching by `in.(…)` makes it at most four, and the
    chunking keeps the query string inside the same bound every other
    batched read here respects.

    `_attach_names` already resolves the whole page's names in one call; this
    is the same shape, applied to the join it sits next to.
    """
    for user in users:
        user["roles"] = []
    ids = [u["id"] for u in users if u.get("id")]
    if not ids:
        return

    by_user: dict[str, list[dict]] = {}
    for chunk in _chunks(ids):
        rows = table("user_roles").select(
            f"user_id,{_ROLE_COLS}",
            filters={"user_id": f"in.({','.join(chunk)})"},
        )
        for row in rows or []:
            role = row.get("roles")
            user_id = row.get("user_id")
            # `roles` is None when the join target was deleted but the
            # user_roles row remained — an orphan to drop, as before.
            if role and user_id:
                by_user.setdefault(user_id, []).append(role)

    for user in users:
        user["roles"] = by_user.get(user["id"], [])


def _still_encrypted(value: Optional[str]) -> bool:
    """Whether a value that already went through decrypt_if_present is still
    ciphertext: it fails soft, so a row sealed under a different ENCRYPTION_KEY
    comes back as the raw blob rather than raising."""
    if not value:
        return False
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return False
    return len(raw) >= _MIN_CIPHERTEXT_BYTES


def _decrypt_emails(users: list[dict]) -> None:
    """Decrypt each row's email in place. A stored value the seam refused (a
    v2 email that does not open in this row) reads as None; it is flagged so
    the list still says "unreadable" rather than showing a blank."""
    for user in users:
        stored = user.get("email")
        user["email"] = decrypt_if_present(stored, bind=bind("users", "email", user))
        if stored and user["email"] is None:
            user["_email_refused"] = True


def _mark_undecryptable(users: list[dict]) -> None:
    """Blank ciphertext this key can't open and flag the row, so the admin list
    shows "unreadable" instead of rendering the blob as a name/email."""
    for user in users:
        bad_email = user.pop("_email_refused", False) or _still_encrypted(user.get("email"))
        bad_name = _still_encrypted(user.get("name"))
        if bad_email:
            user["email"] = None
        if bad_name:
            user["name"] = ""
        user["undecryptable"] = bad_email or bad_name


def _attach_names(users: list[dict]) -> None:
    """Resolve each user's display name off user_profiles (🔒, decrypted)."""
    names = get_display_names([u["id"] for u in users if u.get("id")])
    for user in users:
        user["name"] = names.get(user["id"], "")


@runs_as_service  # #115: admin user directory (every user)
def paginate_users(
    q: Optional[str],
    page: int = 1,
    page_size: int = _DEFAULT_PAGE_SIZE,
) -> dict:
    page = max(1, int(page))
    page_size = max(1, min(_MAX_PAGE_SIZE, int(page_size)))
    offset = (page - 1) * page_size

    if not q:
        rows, total = table("users").select_with_count(
            columns=_USERS_COLS,
            filters=_APPROVED,
            order="created_at.desc",
            limit=page_size,
            offset=offset,
        )
        _decrypt_emails(rows)
        _attach_names(rows)
        _mark_undecryptable(rows)
        _attach_roles(rows)
        return {"users": rows, "total": total, "page": page, "page_size": page_size}

    # Search path: name moved to user_profiles, so PostgREST can't filter it
    # (AEAD nonces aren't searchable anyway). Decrypt emails + resolve every
    # name, then filter and paginate in Python. Admin-scale, behind require_admin.
    all_rows = table("users").select(columns=_USERS_COLS, filters=_APPROVED, order="created_at.desc")
    _decrypt_emails(all_rows)
    _attach_names(all_rows)
    _mark_undecryptable(all_rows)
    needle = q.lower()
    filtered = [
        u for u in all_rows
        if needle in (u.get("name") or "").lower()
        or needle in (u.get("email") or "").lower()
    ]
    total = len(filtered)
    page_rows = filtered[offset : offset + page_size]
    _attach_roles(page_rows)
    return {"users": page_rows, "total": total, "page": page, "page_size": page_size}
