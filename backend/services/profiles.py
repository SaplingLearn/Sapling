"""Display-name reads off `user_profiles`.

Migration 0024 split the public profile out of `users` into a 1:1
`user_profiles` table (PK/FK `user_id`). The display `name` column lives there
and is 🔒 column-encrypted. Cross-domain callers that used to read
`users.name` use these helpers to resolve a human-readable name again.

A freshly FK-stubbed user (see graph_service.ensure_user_exists) has no
`user_profiles` row yet — onboarding/oauth create it — so reads tolerate a
missing row and return "" (single) / omit the id (bulk).
"""

from db.connection import table
from services.encryption import decrypt_if_present


def get_display_name(user_id: str) -> str:
    """Return the decrypted display name for a single user, or "" if unset."""
    rows = table("user_profiles").select("name", filters={"user_id": f"eq.{user_id}"})
    if not rows:
        return ""
    return decrypt_if_present(rows[0].get("name")) or ""


def get_display_names(user_ids: list[str]) -> dict[str, str]:
    """Bulk-resolve decrypted display names keyed by user_id.

    Ids with no `user_profiles` row (or a null name) are simply omitted from the
    returned mapping; callers default per their own response shape.
    """
    ids = list(dict.fromkeys(user_ids))  # dedup, preserve order
    if not ids:
        return {}
    rows = table("user_profiles").select(
        "user_id,name", filters={"user_id": f"in.({','.join(ids)})"}
    )
    out: dict[str, str] = {}
    for r in rows or []:
        name = decrypt_if_present(r.get("name"))
        if name:
            out[r["user_id"]] = name
    return out
