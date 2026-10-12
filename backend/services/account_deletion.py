"""Deleting an account deletes the account.

`DELETE /api/profile/{id}/account` used to stamp `users.deleted_at`, which
nothing read: signing in again restored the account with every row intact,
while Settings promised "Permanently delete your account and all data."

`delete_account` hard-deletes the `users` row, so the ON DELETE CASCADE
foreign keys remove the profile, settings, roles, achievements, cosmetics,
Gradescope credentials, graph, documents, notes, flashcards, sessions and
messages, quizzes, study guides, feedback, XP, friendships and the contributor
ledger. What cascades cannot reach is handled first, in this order:

1. **Preflight.** `admin_audit_log.actor_id` is ON DELETE RESTRICT — audit
   history outlives the admin who made it — so an account with audit rows is
   refused (AccountDeletionBlocked) before anything is touched.
2. **Google.** The stored OAuth refresh token is revoked at Google
   (best-effort: a revoke that fails is logged, not fatal — the row holding
   the token is deleted regardless).
3. **Retrieval chunks.** Private chunks are deleted. The user leaves the
   contributor ledger of every shared chunk; a shared chunk left with no
   contributor is deleted, one a classmate also contributes stays (it is
   theirs too) — the same rule as document deletion and the opt-out resync.
   `course_chunks.uploader_id` has no FK, so none of this would cascade.
4. **Study rooms.** The `rooms*` foreign keys have no ON DELETE. The user's
   reactions, messages (replies to them are detached first — `reply_to_id`
   would block the delete), activity and memberships are deleted. A room the
   user created or owns passes to its longest-standing remaining member, or is
   deleted with its children if nobody is left. Cached room summaries for
   every room the user was in are dropped: they are generated text that can
   name them.
5. **Storage.** Avatar, chat images the user posted, and issue-report
   screenshots. Best-effort, logged at ERROR: an orphaned file is the lesser
   failure next to a database delete that stops half-way because a bucket is
   missing in some environment. The report says whether it completed.
6. **Remaining NO ACTION rows:** `oauth_tokens`, `enrollments` (gradebook
   rows cascade from the enrollment).
7. **Telemetry.** `events` and `llm_usage` have no FK to users; their
   `user_id` is cleared so the counts survive without the identity.
8. **The users row.**

Every step is idempotent, so a run that fails part-way can simply be run
again: the route reports the failure and the user retries.

Not removed, because they are not tied to the account: the newsletter /
waitlist row (keyed by email, its own consent — removed on request) and job
applications (keyed by email; the privacy policy gives them their own
retention).
"""

from __future__ import annotations

import logging

import httpx

from db.connection import page_all, table
from services.chunk_visibility import PRIVATE, SHARED
from services.encryption import decrypt
from services.storage_service import delete_folder, delete_objects
from config import STORAGE_BUCKET

logger = logging.getLogger(__name__)

GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
CHAT_IMAGES_BUCKET = "chat-images"
ISSUE_BUCKET = "issues-media-files"
_BATCH = 100


class AccountDeletionBlocked(Exception):
    """The account cannot be deleted automatically (admin audit history)."""


def _in(ids) -> str:
    return f"in.({','.join(ids)})"


def _batches(ids: list[str]):
    for i in range(0, len(ids), _BATCH):
        yield ids[i:i + _BATCH]


def _all(name: str, columns: str, filters: dict, order: str) -> list[dict]:
    return list(page_all(table(name), columns, filters=filters, order=order))


# ── 2. Google ───────────────────────────────────────────────────────────────

def revoke_google_token(user_id: str) -> bool:
    rows = table("oauth_tokens").select(
        "refresh_token,access_token", filters={"user_id": f"eq.{user_id}"}, limit=1,
    )
    if not rows:
        return False
    try:
        # Revoking the refresh token also invalidates its access tokens.
        token = decrypt(rows[0].get("refresh_token") or rows[0]["access_token"])
        resp = httpx.post(GOOGLE_REVOKE_URL, data={"token": token}, timeout=10.0)
        # 400 invalid_token = already revoked or expired: the goal is met.
        if resp.status_code not in (200, 400):
            logger.warning("[account-delete] Google revoke returned %s for %s",
                           resp.status_code, user_id)
            return False
        return True
    except Exception:
        logger.warning("[account-delete] Google revoke failed for %s", user_id, exc_info=True)
        return False


# ── 3. retrieval chunks ─────────────────────────────────────────────────────

def withdraw_user_chunks(user_id: str) -> dict:
    private = [r["id"] for r in _all(
        "course_chunks", "id",
        {"uploader_id": f"eq.{user_id}", "visibility": f"eq.{PRIVATE}"}, "id",
    )]
    for batch in _batches(private):
        table("course_chunks").delete(filters={"id": _in(batch), "uploader_id": f"eq.{user_id}"})

    # Shared rows this user fed: every ledger entry, plus rows they last wrote
    # (pre-ledger rows can lack an entry for a co-uploader).
    shared = {r["chunk_id"] for r in _all(
        "course_chunk_contributors", "chunk_id", {"user_id": f"eq.{user_id}"}, "chunk_id",
    )}
    shared |= {r["id"] for r in _all(
        "course_chunks", "id",
        {"uploader_id": f"eq.{user_id}", "visibility": f"eq.{SHARED}"}, "id",
    )}
    orphaned: list[str] = []
    for batch in _batches(sorted(shared)):
        table("course_chunk_contributors").delete(
            filters={"user_id": f"eq.{user_id}", "chunk_id": _in(batch)},
        )
        remaining = {r["chunk_id"] for r in table("course_chunk_contributors").select(
            "chunk_id", filters={"chunk_id": _in(batch)},
        ) or []}
        orphaned.extend(i for i in batch if i not in remaining)
    for batch in _batches(orphaned):
        table("course_chunks").delete(filters={"id": _in(batch)})
    return {"private_deleted": len(private), "shared_withdrawn": len(shared),
            "shared_deleted": len(orphaned)}


# ── 4. study rooms ──────────────────────────────────────────────────────────

def _chat_image_path(url: str | None) -> str | None:
    marker = f"/{CHAT_IMAGES_BUCKET}/"
    if not url or marker not in url:
        return None
    return url.split(marker, 1)[1].split("?", 1)[0] or None


def _delete_room(room_id: str) -> None:
    room = {"room_id": f"eq.{room_id}"}
    messages = [r["id"] for r in _all("room_messages", "id", room, "id")]
    for batch in _batches(messages):
        # Detach replies inside the room before deleting what they point at.
        table("room_messages").update({"reply_to_id": None}, filters={"reply_to_id": _in(batch)})
    table("room_messages").delete(filters=room)  # reactions cascade
    table("room_activity").delete(filters=room)
    table("room_summaries").delete(filters=room)
    table("room_members").delete(filters=room)
    table("rooms").delete(filters={"id": f"eq.{room_id}"})


def remove_from_rooms(user_id: str) -> dict:
    me = {"user_id": f"eq.{user_id}"}
    member_of = {r["room_id"] for r in _all("room_members", "room_id", me, "room_id")}

    table("room_reactions").delete(filters=me)
    my_messages = _all("room_messages", "id,image_url", me, "id")
    images = [p for p in (_chat_image_path(m.get("image_url")) for m in my_messages) if p]
    for batch in _batches([m["id"] for m in my_messages]):
        table("room_messages").update({"reply_to_id": None}, filters={"reply_to_id": _in(batch)})
    table("room_messages").delete(filters=me)
    table("room_activity").delete(filters=me)
    table("room_members").delete(filters=me)

    owned = {r["id"]: r for r in table("rooms").select(
        "id,created_by,owner_id",
        filters={"or": f"(created_by.eq.{user_id},owner_id.eq.{user_id})"},
    ) or []}
    transferred = deleted = 0
    for room_id, room in owned.items():
        heir = table("room_members").select(
            "user_id", filters={"room_id": f"eq.{room_id}"}, order="joined_at.asc", limit=1,
        )
        if heir:
            new_owner = heir[0]["user_id"]
            patch = {k: new_owner for k in ("created_by", "owner_id") if room.get(k) == user_id}
            table("rooms").update(patch, filters={"id": f"eq.{room_id}"})
            transferred += 1
        else:
            _delete_room(room_id)
            deleted += 1

    for batch in _batches(sorted(member_of - set(owned))):
        table("room_summaries").delete(filters={"room_id": _in(batch)})
    return {"rooms_transferred": transferred, "rooms_deleted": deleted, "chat_images": images}


# ── 5. storage ──────────────────────────────────────────────────────────────

def delete_user_files(user_id: str, chat_image_paths: list[str]) -> bool:
    ok = True
    for what, step in (
        ("avatar", lambda: delete_folder(STORAGE_BUCKET, f"avatars/{user_id}")),
        ("issue screenshots", lambda: delete_folder(ISSUE_BUCKET, user_id)),
        ("chat images", lambda: delete_objects(CHAT_IMAGES_BUCKET, chat_image_paths)),
    ):
        try:
            step()
        except Exception:
            ok = False
            logger.error("[account-delete] could not delete %s for %s; remove by hand",
                         what, user_id, exc_info=True)
    return ok


# ── the whole thing ─────────────────────────────────────────────────────────

def delete_account(user_id: str) -> dict:
    me = {"user_id": f"eq.{user_id}"}

    if table("admin_audit_log").select("id", filters={"actor_id": f"eq.{user_id}"}, limit=1):
        raise AccountDeletionBlocked(
            "this account has admin audit history, which is retained; "
            "contact support to close it"
        )

    report: dict = {"google_revoked": revoke_google_token(user_id)}
    report |= withdraw_user_chunks(user_id)
    report |= remove_from_rooms(user_id)
    report["storage_complete"] = delete_user_files(user_id, report.pop("chat_images"))

    table("oauth_tokens").delete(filters=me)
    table("enrollments").delete(filters=me)

    for name in ("events", "llm_usage"):
        table(name).update({"user_id": None}, filters=me, prefer_return_minimal=True)

    table("users").delete(filters={"id": f"eq.{user_id}"})
    logger.info("[account-delete] %s deleted: %s", user_id, report)
    return report

