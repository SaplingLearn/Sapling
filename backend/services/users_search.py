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

_DEFAULT_PAGE_SIZE = 50
_MAX_PAGE_SIZE = 200


def _attach_roles(users: list[dict]) -> None:
    for user in users:
        rows = table("user_roles").select(
            "roles(id,name,slug,color,icon,description,is_staff_assigned,is_earnable,display_priority)",
            filters={"user_id": f"eq.{user['id']}"},
        )
        user["roles"] = [r["roles"] for r in (rows or []) if r.get("roles")]


def _decrypt(user: dict) -> dict:
    user["name"] = decrypt_if_present(user.get("name"))
    user["email"] = decrypt_if_present(user.get("email"))
    return user


def paginate_users(
    q: Optional[str],
    page: int = 1,
    page_size: int = _DEFAULT_PAGE_SIZE,
) -> dict:
    page = max(1, int(page))
    page_size = max(1, min(_MAX_PAGE_SIZE, int(page_size)))
    offset = (page - 1) * page_size
    columns = "id,name,email,is_approved,created_at,last_sign_in_at"

    if not q:
        rows, total = table("users").select_with_count(
            columns=columns,
            order="created_at.desc",
            limit=page_size,
            offset=offset,
        )
        for u in rows:
            _decrypt(u)
        _attach_roles(rows)
        return {"users": rows, "total": total, "page": page, "page_size": page_size}

    # Search path: decrypt everything, then filter and paginate in Python.
    all_rows = table("users").select(columns=columns, order="created_at.desc")
    for u in all_rows:
        _decrypt(u)
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
