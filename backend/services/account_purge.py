"""Hard-delete a self-deleted account's personal data after 30 days.

Owner decision 2026-11-14. A student's own "delete account"
(services/profile/deletion.py::delete_account) hides the account (`users.deleted_at`)
and removes its Google tokens and Gradescope login at once
(services/account_credentials.py). `GRACE_DAYS` after `deleted_at`,
services/account_purge_sweeper.py claims the account and runs
:func:`purge_account`, which:

1. runs the admin wipe (`account_wipe.wipe_account_data`: every study table,
   documents with their chunks withdrawn the #629/#630 way — a shared chunk a
   classmate still holds survives for them);
2. removes the credentials again (and revokes the Google grant, best effort);
3. TOMBSTONES the student's room messages instead of deleting them: text,
   image and author name are cleared (`is_deleted`, `user_name` =
   `TOMBSTONE_NAME`), exactly what "delete message" already does, so
   classmates' transcripts keep their order and their replies keep a
   "deleted message" to point at rather than losing rows mid-thread; the
   attached chat images are deleted from storage, and the rooms' cached AI
   summaries (which may quote the student) are dropped. This comes BEFORE
   step 4: a room the student was the last member of is deleted there, and
   its messages (with the image URLs naming the files) cascade with it;
4. leaves every study room (ownership passes to the earliest member; a room
   left empty is deleted, `services/social/rooms.py::leave_room`);
5. deletes reactions, the room activity feed, friendships and friend
   requests, feedback and issue reports (+ their screenshots), cosmetics,
   roles, settings, the legal acceptances, the profile (+ the avatar files),
   the waitlist/newsletter row the account was joined from, and any
   chunk-contributor row a failed withdrawal left behind;
6. turns the `users` row into an anonymised STUB (no email, no google_id,
   unapproved, `purged_at` set). The row stays because shared rows point at
   it: `rooms.created_by` (NOT NULL), the tombstoned messages, a former
   admin's `admin_audit_log` rows (ON DELETE RESTRICT), and `llm_usage`'s
   billing key. Its id is the opaque `user_<google id>`; a later Google
   sign-in by the same person starts a fresh account on it
   (services/auth/signin.py).

`KEPT_AFTER_PURGE` names what even the purge keeps, with the reason;
tests/test_account_purge.py requires every table the admin wipe keeps
(`account_wipe.KEPT_PER_USER`) to be purged, anonymised or listed there.

Not atomic (PostgREST has no transactions). Every step is idempotent and
owner-scoped, `purged_at` is written LAST, and a failed step raises
`AccountPurgeIncomplete` so the sweeper retries the whole purge on a later
pass; a re-run over a purged account changes nothing.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

from db.connection import page_all, table
from models import LeaveRoomBody
from services import account_credentials, account_wipe, events_service, storage_service
from services.account_wipe import _delete_keys, _in_list
from services.analytics_consent import clear_analytics_consent_cache
from services.social import rooms
from services.social.errors import Forbidden, NotFound
from services.social_cache_service import invalidate as invalidate_summary

logger = logging.getLogger(__name__)

#: Days between the student's delete and the purge. The claim SQL floors it
#: at 30 too (20261114192918_account_purge.sql), so no caller can go lower.
GRACE_DAYS = 30

#: The author name a purged student's room messages carry.
TOMBSTONE_NAME = "Deleted user"

#: Storage buckets holding the student's own files (besides avatars, which
#: live in config.STORAGE_BUCKET): chat images (frontend Social.tsx) and
#: issue-report screenshots (services/storage_service.py::ISSUE_BUCKET).
CHAT_IMAGES_BUCKET = "chat-images"
ISSUE_BUCKET = storage_service.ISSUE_BUCKET

#: Deleted outright after the wipe: (table, column naming the student).
PURGE_DELETES: tuple[tuple[str, str], ...] = (
    ("room_reactions", "user_id"),
    ("room_activity", "user_id"),
    ("friendships", "user_id"),
    ("friendships", "friend_id"),
    ("friend_requests", "from_user_id"),
    ("friend_requests", "to_user_id"),
    ("feedback", "user_id"),
    ("issue_reports", "user_id"),
    ("user_cosmetics", "user_id"),
    ("user_roles", "user_id"),
    ("user_settings", "user_id"),
    ("user_profiles", "user_id"),
    # The Terms / Privacy versions accepted at onboarding. The admin wipe keeps
    # them (account state); the purge does not, because the Privacy Policy does
    # not say consent records outlive the account, and a reopened stub
    # (services/auth/signin.py) must start without the old account's answers.
    ("legal_acceptances", "user_id"),
    ("newsletter_emails", "joined_user_id"),
)

#: Removed by dedicated steps: table -> how.
PURGED_BY_STEP: dict[str, str] = {
    "oauth_tokens": "account_credentials.remove_credentials (+ Google revoke)",
    "gradescope_credentials": "account_credentials.remove_credentials",
    "room_members": "rooms.leave_room per room (ownership handed on)",
    "course_chunk_contributors": "leftover rows of failed withdrawals",
}

#: Rows the purge keeps but strips of personal content: table -> how.
PURGE_ANONYMIZES: dict[str, str] = {
    "room_messages": "tombstoned: text, image and author name cleared",
    "users": "stub: email, google_id cleared; purged_at set",
}

#: Per-user tables whose rows the purge leaves as they are, with the reason.
KEPT_AFTER_PURGE: dict[str, str] = {
    "llm_usage": (
        "the billing record of model spend: ids, model, token counts and cost, "
        "never content"
    ),
    "events": (
        "telemetry without content (ids, counts, enums; free text only as a "
        "fingerprint); PostHog's copy was deleted at the student's own delete"
    ),
    "room_bans": "moderation record: a (room, user id) pair, no content",
}


class PurgeRefused(RuntimeError):
    """The account is not a self-deleted account past its grace period."""


class AccountPurgeIncomplete(RuntimeError):
    """A step failed; the sweeper retries the whole (idempotent) purge later."""


def purged_tables() -> frozenset[str]:
    """Every per-user table the purge empties of the student's rows."""
    return (account_wipe.wiped_tables() | frozenset(PURGED_BY_STEP)
            | frozenset(name for name, _ in PURGE_DELETES))


def _parse_ts(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _due_account(user_id: str, now: datetime) -> dict:
    """The `users` row, if this account may be purged; else PurgeRefused."""
    rows = table("users").select("id,deleted_at,purged_at", filters={"id": f"eq.{user_id}"})
    if not rows:
        raise PurgeRefused(f"no account {user_id}")
    deleted_at = _parse_ts(rows[0].get("deleted_at"))
    if deleted_at is None or now - deleted_at < timedelta(days=GRACE_DAYS):
        raise PurgeRefused(f"{user_id} was not deleted more than {GRACE_DAYS} days ago")
    return rows[0]


def _delete_where(name: str, column: str, user_id: str) -> int:
    return len(table(name).delete(filters={column: f"eq.{user_id}"}) or [])


def _object_path(path: str) -> str | None:
    """`path` if it names an object inside the bucket, else None: no empty,
    `.` or `..` segment (so no leading or doubled slash) and no NUL."""
    if not path or "\x00" in path:
        return None
    return None if any(seg in ("", ".", "..") for seg in path.split("/")) else path


def _storage_path(ref: str | None, bucket: str) -> str | None:
    """The object path `ref` names in `bucket`: a Storage URL (public or not)
    of that bucket, or a bare object path. None for anything else.

    A URL's path is percent-decoded: supabase-js `getPublicUrl` runs it
    through `encodeURI`, so `a b.png` is stored as `a%20b.png` and only the
    decoded name is the object Storage holds. Validation runs AFTER decoding,
    so an encoded `..` or `/` cannot reach outside the folder it names."""
    if not isinstance(ref, str) or not ref.strip():
        return None
    for marker in (f"/storage/v1/object/public/{bucket}/", f"/storage/v1/object/{bucket}/"):
        if marker in ref:
            raw = ref.split(marker, 1)[1].split("?", 1)[0]
            try:
                return _object_path(unquote(raw, errors="strict"))
            except UnicodeDecodeError:
                return None
    return None if "://" in ref else _object_path(ref.strip().lstrip("/"))


def _leave_rooms(user_id: str) -> int:
    room_ids = [r["room_id"] for r in page_all(
        table("room_members"), "room_id", filters={"user_id": f"eq.{user_id}"}, order="room_id",
    )]
    for room_id in room_ids:
        try:
            rooms.leave_room(room_id, LeaveRoomBody(user_id=user_id))
        except (Forbidden, NotFound):
            pass  # already left (a concurrent leave, or an earlier pass)
    return len(room_ids)


def _tombstone_messages(user_id: str) -> int:
    rows = list(page_all(
        table("room_messages"), "id,room_id,user_name,image_url,is_deleted",
        filters={"user_id": f"eq.{user_id}"}, order="id",
    ))
    todo = [r for r in rows if not (r.get("is_deleted") and r.get("user_name") == TOMBSTONE_NAME
                                    and not r.get("image_url"))]
    # image_url is client-supplied, so only a file the student uploaded goes:
    # the frontend names it `<room>/<user id>-<ms>-<name>` (Social.tsx).
    images = [p for p in (_storage_path(r.get("image_url"), CHAT_IMAGES_BUCKET)
                          for r in todo if r.get("image_url"))
              if p and p.count("/") == 1 and p.split("/", 1)[1].startswith(f"{user_id}-")]
    # Files first: once image_url is cleared nothing names them any more.
    storage_service.delete_objects(CHAT_IMAGES_BUCKET, images)
    ids = [str(r["id"]) for r in todo]
    for i in range(0, len(ids), account_wipe._BATCH):
        table("room_messages").update(
            {"is_deleted": True, "text": None, "image_url": None, "user_name": TOMBSTONE_NAME},
            filters={"id": _in_list(ids[i : i + account_wipe._BATCH]), "user_id": f"eq.{user_id}"},
            prefer_return_minimal=True,
        )
    for room_id in dict.fromkeys(r["room_id"] for r in todo if r.get("room_id")):
        invalidate_summary(room_id)  # a cached summary may quote the student
    return len(ids)


def _delete_files(user_id: str) -> None:
    """The avatar and the issue-report screenshots, before the rows naming them go."""
    storage_service.delete_objects(storage_service.STORAGE_BUCKET, storage_service.avatar_paths(user_id))
    # screenshot_urls is client-supplied too: only paths under the student's
    # own upload prefix (`<user id>/<uuid>.<ext>`, storage_service.upload_issue_screenshot) go.
    # `_storage_path` already refuses a `.`/`..`/empty segment, so the prefix
    # check cannot be climbed out of.
    shots = [
        p for r in page_all(table("issue_reports"), "id,screenshot_urls",
                            filters={"user_id": f"eq.{user_id}"}, order="id")
        for p in (_storage_path(u, ISSUE_BUCKET) for u in (r.get("screenshot_urls") or []))
        if p and p.startswith(f"{user_id}/")
    ]
    storage_service.delete_objects(ISSUE_BUCKET, shots)


def _drop_leftover_contributions(user_id: str) -> int:
    """Contributor rows a failed withdrawal left behind (the wipe's withdrawal
    already handled every document it deleted). The student's row goes; the
    chunk goes with it only when nobody else holds it — no other contributor
    and no live source document — so a classmate's shared chunk survives."""
    chunk_ids = [r["chunk_id"] for r in page_all(
        table("course_chunk_contributors"), "chunk_id",
        filters={"user_id": f"eq.{user_id}"}, order="chunk_id",
    )]
    if not chunk_ids:
        return 0
    _delete_keys("course_chunk_contributors", chunk_ids, key="chunk_id", owner=user_id)
    held: set[str] = set()
    for i in range(0, len(chunk_ids), account_wipe._BATCH):
        batch = _in_list(chunk_ids[i : i + account_wipe._BATCH])
        held.update(r["chunk_id"] for r in table("course_chunk_contributors").select(
            "chunk_id", filters={"chunk_id": batch}) or [])
        sources = table("course_chunk_sources").select("chunk_id,doc_id", filters={"chunk_id": batch}) or []
        docs = sorted({s["doc_id"] for s in sources if s.get("doc_id")})
        live = {d["id"] for d in (table("documents").select(
            "id", filters={"id": _in_list(docs), "deleted_at": "is.null"}) if docs else []) or []}
        held.update(s["chunk_id"] for s in sources if s.get("doc_id") in live)
    orphans = [c for c in chunk_ids if c not in held]
    for i in range(0, len(orphans), account_wipe._BATCH):
        table("course_chunks").delete(filters={
            "id": _in_list(orphans[i : i + account_wipe._BATCH]), "category": "neq.catalog",
        })
    return len(chunk_ids)


def _stub_user(user_id: str, now: datetime) -> None:
    table("users").update(
        {"email": None, "google_id": None, "is_approved": False,
         "onboarding_completed": False, "last_sign_in_at": None, "welcomed_at": None,
         "purged_at": now.isoformat(), "purge_claimed_at": None},
        filters={"id": f"eq.{user_id}", "purged_at": "is.null"},
        prefer_return_minimal=True,
    )


def purge_account(user_id: str, *, now: datetime | None = None) -> dict[str, int]:
    """Hard-delete `user_id`'s personal data (module docstring). Returns rows
    removed or anonymised per table (directly issued deletes; cascades are
    not counted). Raises `PurgeRefused` for an account that is missing, not
    deleted, or inside its grace period, and `AccountPurgeIncomplete` when a
    step failed (nothing is marked purged then)."""
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("purge_account needs a non-empty user_id")
    now = now or datetime.now(timezone.utc)
    account = _due_account(user_id, now)
    try:
        counts = account_wipe.wipe_account_data(user_id)
        account_credentials.revoke_google_tokens(account_credentials.remove_credentials(user_id))
        # Messages BEFORE leaving: leaving deletes a room the student was the
        # last member of, its messages cascade, and their image_url (the only
        # record of which chat-images files are the student's) goes with them.
        counts["room_messages"] = _tombstone_messages(user_id)
        counts["room_members"] = _leave_rooms(user_id)
        _delete_files(user_id)
        counts["course_chunk_contributors"] += _drop_leftover_contributions(user_id)
        for name, column in PURGE_DELETES:
            counts[name] = counts.get(name, 0) + _delete_where(name, column, user_id)
        # user_settings (the analytics opt-out) is gone: drop the cached answer.
        clear_analytics_consent_cache(user_id)
        _stub_user(user_id, now)
    except Exception as exc:
        raise AccountPurgeIncomplete(f"purge of {user_id} stopped: {type(exc).__name__}") from exc

    deleted_at = _parse_ts(account.get("deleted_at"))
    events_service.log_event(
        "account.purge", category="audit",
        payload={"outcome": "purged", "days_since_delete": (now - deleted_at).days if deleted_at else None,
                 "counts": {k: v for k, v in counts.items() if v}},
    )
    logger.info("[account-purge] purged one account: %s row(s)", sum(counts.values()))
    return counts
