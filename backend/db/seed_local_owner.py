"""Owner-specific writer for the local rich seed; never rewrites existing rows."""
from __future__ import annotations

import hashlib
from uuid import NAMESPACE_URL, uuid5

from db import seed_helpers as h
from db.connection import page_all, table
from services.encryption import decrypt
from services.profiles import get_display_name

_ACTIVE = "rich-user-active"
_PEER = "rich-user-second"
_SHARED = {"schools", "courses", "course_offerings", "offering_concept_stats"}
#: Never copied onto an owner. user_roles: a sample dataset must never grant
#: the developer admin rights. feedback/issue_reports: the rich seed keeps them
#: as ciphertext-oracle baseline rows; on a real account they would read as
#: submissions the developer never made.
_SKIPPED = {"user_roles", "feedback", "issue_reports"}


def resolve_owner(*, email: str | None = None, user_id: str | None = None) -> dict:
    """Look up an existing account; encrypted email cannot be filtered in SQL."""
    if user_id is not None:
        rows = table("users").select(
            "id,onboarding_completed", filters={"id": f"eq.{user_id.strip()}"}, limit=1,
        )
    else:
        wanted = (email or "").strip().casefold()
        rows = []
        undecryptable = 0
        for row in page_all(table("users"), "id,email,onboarding_completed", order="id"):
            if not row.get("email"):
                continue
            try:
                stored_email = decrypt(row["email"]).strip().casefold()
            except Exception:
                # One stray row under another key must not block every other account.
                undecryptable += 1
                continue
            if stored_email == wanted:
                rows.append(row)
        if not rows and undecryptable:
            raise ValueError(
                f"No account matched, and {undecryptable} local user email(s) could not be "
                "decrypted. Check the local ENCRYPTION_KEY, or use --owner-user-id."
            )
    if len(rows) != 1:
        raise ValueError(
            "Expected exactly one existing account. Sign in locally with Google first; "
            "use --owner-user-id if more than one account has this email."
        )
    return rows[0]


class OwnerSeedWriter:
    """Reuse the rich fixtures with stable owner IDs and remapped foreign keys.

    Natural-key matches retain their actual IDs so a developer's pre-existing
    enrollment or concept can be referenced without changing it or its children.
    The normal rich-user fixtures are never transferred to the owner.
    """

    def __init__(self, owner_id: str):
        self.owner_id = owner_id
        self.ids = {_ACTIVE: owner_id}
        self._name: str | None = None
        # Upper-case: the join route upper-cases what the user types.
        self.invite_prefix = hashlib.sha256(owner_id.encode()).hexdigest()[:16].upper()

    def _owner_name(self) -> str:
        # Room chat renders the stored user_name, not the profile.
        if self._name is None:
            self._name = get_display_name(self.owner_id) or "You"
        return self._name

    def _id(self, table_name: str, source_id: str) -> str:
        value = str(uuid5(NAMESPACE_URL, f"sapling-rich-owner:{self.owner_id}:{table_name}:{source_id}"))
        # room_messages.id is UUID; the remaining fixture tables use TEXT.
        return value if table_name == "room_messages" else f"rich-owner-{value}"

    def _write(self, table_name: str, source: dict, keys: str) -> None:
        if table_name in _SKIPPED:
            return
        if table_name == "users" and source["id"] != _PEER:
            return
        if table_name == "user_profiles" and source["user_id"] != _PEER:
            return
        if table_name in {"enrollments", "notes"} and source["user_id"] != _ACTIVE:
            return

        row = {
            key: self.ids.get(value, value) if isinstance(value, str) else value
            for key, value in source.items()
        }
        source_id = source.get("id")
        if source_id and table_name not in _SHARED | {"users"}:
            row["id"] = self._id(table_name, source_id)
        if table_name == "room_messages" and row.get("user_id") == self.owner_id:
            row["user_name"] = self._owner_name()
        if table_name == "rooms":
            row["invite_code"] = f"OWNER-{self.invite_prefix}-{source['invite_code']}"

        key_columns = keys.split(",")
        filters = {key: f"eq.{row[key]}" for key in key_columns}
        # Key columns (+ the id, to remap children onto an existing row) only:
        # select("*") would drag back ciphertext and 768-float embeddings.
        columns = ",".join(dict.fromkeys(key_columns + (["id"] if source_id else [])))
        existing = table(table_name).select(columns, filters=filters, limit=1)
        if existing:
            if source_id:
                self.ids[source_id] = existing[0]["id"]
            h.record(table_name, created=False)
            return

        table(table_name).insert(row)
        if source_id:
            self.ids[source_id] = row["id"]
        h.record(table_name, created=True)

    def upsert(self, table_name: str, row: dict, on_conflict: str) -> None:
        self._write(table_name, row, on_conflict)

    def insert_if_absent(self, table_name: str, row_id: str, row: dict) -> None:
        self._write(table_name, {"id": row_id, **row}, "id")

    def insert_by_keys(self, table_name: str, row: dict, keys: str) -> None:
        self._write(table_name, row, keys)
