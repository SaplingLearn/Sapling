"""
Paginated user listing for the admin portal.

Without a search query, we paginate at the DB layer (offset+limit) and decrypt
only the page we return. With a search query, we have to decrypt the whole
table because users.name and users.email use AEAD with random nonces and are
not directly searchable. This is acceptable at admin scale and lives behind
require_admin.
"""

from typing import Optional

from db.connection import table
from services.encryption import decrypt_if_present
from services.profiles import get_display_names

_DEFAULT_PAGE_SIZE = 50
_MAX_PAGE_SIZE = 200

# After migration 0024 the display `name` lives on user_profiles, not users.
_USERS_COLS = "id,email,is_approved,created_at,last_sign_in_at"


def _attach_roles(users: list[dict]) -> None:
    for user in users:
        rows = table("user_roles").select(
            "roles(id,name,slug,color,icon,description,is_staff_assigned,is_earnable,display_priority)",
            filters={"user_id": f"eq.{user['id']}"},
        )
        user["roles"] = [r["roles"] for r in (rows or []) if r.get("roles")]


def _attach_names(users: list[dict]) -> None:
    """Resolve each user's display name off user_profiles (🔒, decrypted)."""
    names = get_display_names([u["id"] for u in users if u.get("id")])
    for user in users:
        user["name"] = names.get(user["id"], "")


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
            order="created_at.desc",
            limit=page_size,
            offset=offset,
        )
        for u in rows:
            u["email"] = decrypt_if_present(u.get("email"))
        _attach_names(rows)
        _attach_roles(rows)
        return {"users": rows, "total": total, "page": page, "page_size": page_size}

    # Search path: name moved to user_profiles, so PostgREST can't filter it
    # (AEAD nonces aren't searchable anyway). Decrypt emails + resolve every
    # name, then filter and paginate in Python. Admin-scale, behind require_admin.
    all_rows = table("users").select(columns=_USERS_COLS, order="created_at.desc")
    for u in all_rows:
        u["email"] = decrypt_if_present(u.get("email"))
    _attach_names(all_rows)
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
