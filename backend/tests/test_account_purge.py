"""The 30-day purge of a self-deleted account: `services/account_purge.py`.

Driven against the same in-memory PostgREST as tests/test_account_wipe.py
(it honours the filters the module sends and models the FK cascades), with
the room cascades added. The REAL admin wipe, chunk withdrawal and
`rooms.leave_room` run against it; only the storage calls and the Google
revoke are recorders.
"""
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import pytest

from services import account_credentials as ac
from services import account_purge as ap
from services import account_wipe as aw
from services import chunk_visibility as cv
from services import events_service, storage_service
from services import social_cache_service
from services.encryption import encrypt
from services.social import rooms as social_rooms
from tests.test_account_wipe import CASCADES, KEPT, WIPED, FakeDB, _seed_user, schema_user_id_columns

U, OTHER = "user_purge", "user_stays"
NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
LONG_AGO = (NOW - timedelta(days=31)).isoformat()

ROOM_CASCADES = {
    "room_members": ("room_id", "rooms", "id"),
    "room_messages": ("room_id", "rooms", "id"),
    "room_activity": ("room_id", "rooms", "id"),
    "room_summaries": ("room_id", "rooms", "id"),
    "room_reactions": ("message_id", "room_messages", "id"),
}


class PurgeDB(FakeDB):
    def _cascade(self, name, gone):
        super()._cascade(name, gone)
        for child, (col, parent, pcol) in ROOM_CASCADES.items():
            if parent != name:
                continue
            keys = {r[pcol] for r in gone}
            dead = [r for r in self.rows.get(child, []) if r.get(col) in keys]
            if dead:
                self.rows[child] = [r for r in self.rows[child] if r not in dead]
                self._cascade(child, dead)


@pytest.fixture
def db(monkeypatch):
    fake = PurgeDB()
    for module in (aw, cv, ap, ac, social_rooms, social_cache_service):
        monkeypatch.setattr(module, "table", fake.table)
    return fake


@pytest.fixture
def storage(monkeypatch):
    deleted: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(storage_service, "delete_objects",
                        lambda bucket, paths: deleted.append((bucket, list(paths))))
    return deleted


@pytest.fixture
def revoked(monkeypatch):
    calls: list[list[str]] = []
    monkeypatch.setattr(ac, "revoke_google_tokens", lambda tokens: calls.append(list(tokens)))
    return calls


@pytest.fixture
def events(monkeypatch):
    logged: list[tuple[str, dict]] = []
    monkeypatch.setattr(events_service, "log_event", lambda t, **kw: logged.append((t, kw)))
    return logged


def _chat_url(path):
    return f"https://proj.supabase.co/storage/v1/object/public/{ap.CHAT_IMAGES_BUCKET}/{path}"


def _seed_account(db, uid, *, deleted_at=None):
    """Study data (the wipe's seed) plus everything the purge adds."""
    _seed_user(db, uid)
    (user,) = db.of("users", id=uid)
    user.update(email="enc-email", google_id=f"g-{uid}", is_approved=True,
                onboarding_completed=True, deleted_at=deleted_at, purged_at=None,
                last_sign_in_at="2026-10-01T00:00:00+00:00", welcomed_at="2026-09-01")
    # _seed_user added one row per KEPT table keyed by user_id; make the ones
    # the purge reads look real.
    db.of("oauth_tokens", user_id=uid)[0].update(
        access_token=encrypt(f"access-{uid}"), refresh_token=encrypt(f"refresh-{uid}"))
    db.of("issue_reports", user_id=uid)[0]["screenshot_urls"] = [f"{uid}/shot.png"]
    db.of("room_members", user_id=uid)[0].update(room_id=f"{uid}-room", joined_at="2026-01-01")
    db.add("rooms", id=f"{uid}-room", owner_id=uid, created_by=uid, updated_at=None)
    db.add("friend_requests", id=f"{uid}-fr", from_user_id=uid, to_user_id="someone")
    db.add("room_bans", room_id="elsewhere", user_id=uid, banned_by="mod")
    db.add("newsletter_emails", id=f"{uid}-nl", email=f"{uid}@bu.edu", joined_user_id=uid)


def _seed_room(db):
    """A room U owns and OTHER is in; U's messages, one OTHER replied to."""
    db.add("rooms", id="r1", owner_id=U, created_by=U, updated_at=None)
    db.add("room_members", room_id="r1", user_id=U, joined_at="2026-01-01")
    db.add("room_members", room_id="r1", user_id=OTHER, joined_at="2026-01-02")
    db.add("room_messages", id="m1", room_id="r1", user_id=U, user_name="Ada Lovelace",
           text="enc-hello", image_url=_chat_url(f"r1/{U}-1-pic.png"), is_deleted=False)
    db.add("room_messages", id="m2", room_id="r1", user_id=OTHER, user_name="Grace",
           text="enc-reply", image_url=None, is_deleted=False, reply_to_id="m1")
    db.add("room_reactions", id="x1", message_id="m2", user_id=U, emoji="+1")
    db.add("room_reactions", id="x2", message_id="m1", user_id=OTHER, emoji="+1")
    db.add("room_activity", id="a1", room_id="r1", user_id=U)
    db.add("room_activity", id="a2", room_id="r1", user_id=OTHER)
    db.add("room_summaries", room_id="r1", summary="enc-sum", member_hash="h")
    # A room only U is in: deleted when U leaves.
    db.add("rooms", id="r2", owner_id=U, created_by=U, updated_at=None)
    db.add("room_members", room_id="r2", user_id=U, joined_at="2026-01-01")


# ── who may be purged ───────────────────────────────────────────────────────


@pytest.mark.parametrize("deleted_at", [None, (NOW - timedelta(days=29)).isoformat(),
                                        (NOW - timedelta(days=30, seconds=-60)).isoformat()])
def test_refuses_an_account_not_deleted_more_than_30_days_ago(db, storage, deleted_at):
    _seed_account(db, U, deleted_at=deleted_at)

    with pytest.raises(ap.PurgeRefused):
        ap.purge_account(U, now=NOW)

    assert db.ops("delete") == [] and db.ops("update") == []
    assert storage == []


def test_refuses_a_missing_account_and_a_blank_id(db):
    with pytest.raises(ap.PurgeRefused):
        ap.purge_account("user_nobody", now=NOW)
    with pytest.raises(ValueError):
        ap.purge_account("  ", now=NOW)


# ── what goes, what stays ───────────────────────────────────────────────────


def test_purges_the_account_and_leaves_another_users_data(db, storage, revoked, events):
    _seed_account(db, U, deleted_at=LONG_AGO)
    _seed_account(db, OTHER)
    _seed_room(db)

    counts = ap.purge_account(U, now=NOW)

    # Study data (the wipe) and every purged table hold nothing of U's.
    for name in WIPED:
        assert db.of(name, user_id=U) == [], name
    for name, column in ap.PURGE_DELETES:
        assert not [r for r in db.rows.get(name, []) if r.get(column) == U], name
    for name in ("oauth_tokens", "gradescope_credentials", "room_members",
                 "course_chunk_contributors"):
        assert db.of(name, user_id=U) == [], name
    # The neighbour is untouched, everywhere.
    for name in (*WIPED, *KEPT):
        assert db.of(name, user_id=OTHER) or db.of(name, id=OTHER), name
    assert db.of("newsletter_emails", joined_user_id=OTHER)
    assert db.of("friend_requests", from_user_id=OTHER)
    # Kept on purpose: billing, telemetry, moderation.
    for name in ap.KEPT_AFTER_PURGE:
        assert db.of(name, user_id=U), name
    assert counts["user_profiles"] == 1 and counts["newsletter_emails"] == 1


def test_the_purge_drops_the_cached_analytics_consent(db, storage, revoked, events, monkeypatch):
    """The purge deletes user_settings (the opt-out the consent check reads),
    so like every mutator of it, it drops the cached answer (CLAUDE.md)."""
    _seed_account(db, U, deleted_at=LONG_AGO)
    cleared: list[str] = []
    monkeypatch.setattr(ap, "clear_analytics_consent_cache", cleared.append)

    ap.purge_account(U, now=NOW)

    assert cleared == [U]
    assert not db.of("user_settings", user_id=U)


def test_the_users_row_becomes_an_anonymised_stub(db, storage, revoked, events):
    _seed_account(db, U, deleted_at=LONG_AGO)

    ap.purge_account(U, now=NOW)

    (stub,) = db.of("users", id=U)
    assert stub["email"] is None and stub["google_id"] is None
    assert stub["is_approved"] is False and stub["onboarding_completed"] is False
    assert stub["last_sign_in_at"] is None and stub["welcomed_at"] is None
    assert stub["purged_at"] == NOW.isoformat()
    assert stub["deleted_at"] == LONG_AGO
    assert stub["total_xp"] == 0  # the wipe's counter reset


def test_room_messages_are_tombstoned_and_rooms_stay_coherent(db, storage, revoked, events):
    _seed_account(db, U, deleted_at=LONG_AGO)
    _seed_account(db, OTHER)
    _seed_room(db)

    counts = ap.purge_account(U, now=NOW)

    (mine,) = db.of("room_messages", id="m1")
    assert mine["is_deleted"] is True and mine["text"] is None and mine["image_url"] is None
    assert mine["user_name"] == ap.TOMBSTONE_NAME and mine["user_id"] == U
    (theirs,) = db.of("room_messages", id="m2")
    assert theirs["text"] == "enc-reply" and theirs["reply_to_id"] == "m1"  # thread intact
    assert db.of("room_reactions", id="x2") and not db.of("room_reactions", user_id=U)
    assert db.of("room_activity", id="a2") and not db.of("room_activity", user_id=U)
    # U left: ownership passed to the remaining member; the empty room is gone.
    (room,) = db.of("rooms", id="r1")
    assert room["owner_id"] == OTHER and room["created_by"] == U
    assert db.of("rooms", id="r2") == []
    assert db.of("room_summaries", room_id="r1") == []  # may have quoted U
    assert counts["room_members"] == 3 and counts["room_messages"] == 1
    assert (ap.CHAT_IMAGES_BUCKET, [f"r1/{U}-1-pic.png"]) in storage


def test_photos_in_a_room_the_student_was_last_in_are_deleted(db, storage, revoked, events):
    """Leaving deletes a room whose last member the student was, and its
    messages cascade with it: the image paths must be collected first, or the
    photos stay in the public bucket with nothing left naming them."""
    _seed_account(db, U, deleted_at=LONG_AGO)
    db.add("rooms", id="solo", owner_id=U, created_by=U, updated_at=None)
    db.add("room_members", room_id="solo", user_id=U, joined_at="2026-01-01")
    db.add("room_messages", id="ms", room_id="solo", user_id=U, user_name="Ada",
           text="enc", image_url=_chat_url(f"solo/{U}-7-pic.png"), is_deleted=False)

    ap.purge_account(U, now=NOW)

    assert db.of("rooms", id="solo") == []  # the room went with the student
    sent = [p for bucket, paths in storage if bucket == ap.CHAT_IMAGES_BUCKET for p in paths]
    assert f"solo/{U}-7-pic.png" in sent


def test_files_and_the_google_grant_go(db, storage, revoked, events):
    _seed_account(db, U, deleted_at=LONG_AGO)

    ap.purge_account(U, now=NOW)

    assert (storage_service.STORAGE_BUCKET, storage_service.avatar_paths(U)) in storage
    assert (ap.ISSUE_BUCKET, [f"{U}/shot.png"]) in storage
    assert revoked == [[f"refresh-{U}", f"access-{U}"]]


def test_client_supplied_references_to_someone_elses_files_are_left_alone(
    db, storage, revoked, events,
):
    """image_url and screenshot_urls come from the request body: a student who
    pointed them at a classmate's file must not get it deleted by the purge."""
    _seed_account(db, U, deleted_at=LONG_AGO)
    db.of("issue_reports", user_id=U)[0]["screenshot_urls"] = [
        f"{OTHER}/theirs.png", f"{U}/../{OTHER}/x.png", f"{U}/mine.png"]
    db.add("rooms", id="r9", owner_id=OTHER, created_by=OTHER, updated_at=None)
    db.add("room_messages", id="m9", room_id="r9", user_id=U, user_name="Ada",
           text="enc", image_url=_chat_url(f"r9/{OTHER}-5-pic.png"), is_deleted=False)

    ap.purge_account(U, now=NOW)

    assert (ap.ISSUE_BUCKET, [f"{U}/mine.png"]) in storage
    assert (ap.CHAT_IMAGES_BUCKET, []) in storage
    assert db.of("room_messages", id="m9")[0]["image_url"] is None  # the reference goes


def test_a_screenshot_whose_name_merely_contains_dots_is_deleted(db, storage, revoked, events):
    """Only a `..` SEGMENT escapes the student's folder (`_object_path`
    refuses it); `a..b.png` is an ordinary file name and must go."""
    _seed_account(db, U, deleted_at=LONG_AGO)
    db.of("issue_reports", user_id=U)[0]["screenshot_urls"] = [
        f"{U}/a..b.png", f"{U}/../{OTHER}/x.png", f"{U}/..", f"{U}/sub/../x.png"]

    ap.purge_account(U, now=NOW)

    assert (ap.ISSUE_BUCKET, [f"{U}/a..b.png"]) in storage


def _encode_uri(path):
    """What supabase-js getPublicUrl does to the object path (encodeURI)."""
    return quote(path, safe=";,/?:@&=+$-_.!~*'()#")


@pytest.mark.parametrize("name", [
    "Screenshot 2026-11-14 at 3.04.12 PM.png",
    "naïve café 写真.png",
    "100% done+final.png",
])
def test_a_public_url_names_the_decoded_object(name):
    path = f"r1/{U}-1-{name}"
    url = _chat_url(_encode_uri(path))
    assert url != _chat_url(path)  # the stored URL really is encoded

    assert ap._storage_path(url, ap.CHAT_IMAGES_BUCKET) == path


@pytest.mark.parametrize("ref", [
    _chat_url(f"r1/%2E%2E/{OTHER}-1-pic.png"),
    _chat_url(f"r1/..%2F{OTHER}-1-pic.png"),
    _chat_url(f"%2Fr1/{U}-1-pic.png"),
    _chat_url(f"r1//{U}-1-pic.png"),
    _chat_url(f"r1/{U}-1-pic%00.png"),
    _chat_url(f"r1/{U}-1-%FF.png"),  # not UTF-8
])
def test_a_url_that_decodes_out_of_its_folder_names_nothing(ref):
    assert ap._storage_path(ref, ap.CHAT_IMAGES_BUCKET) is None


def test_an_encoded_chat_image_is_deleted_by_its_real_name(db, storage, revoked, events):
    _seed_account(db, U, deleted_at=LONG_AGO)
    path = f"r9/{U}-3-Screenshot 2026-11-14 at 3.04.12 PM.png"
    db.add("rooms", id="r9", owner_id=OTHER, created_by=OTHER, updated_at=None)
    db.add("room_messages", id="m9", room_id="r9", user_id=U, user_name="Ada",
           text="enc", image_url=_chat_url(_encode_uri(path)), is_deleted=False)

    ap.purge_account(U, now=NOW)

    assert (ap.CHAT_IMAGES_BUCKET, [path]) in storage


def test_storage_bulk_delete_sends_the_paths_and_raises_on_failure(monkeypatch):
    from unittest.mock import MagicMock

    sent = []
    answers = [MagicMock(status_code=200), MagicMock(status_code=500)]

    def request(method, url, json=None, **kw):
        sent.append((method, url.rsplit("/", 1)[1], json))
        return answers.pop(0)

    monkeypatch.setattr(storage_service.httpx, "request", request)
    storage_service.delete_objects("chat-images", ["r1/a.png"])
    with pytest.raises(RuntimeError, match="status 500"):
        storage_service.delete_objects("chat-images", ["r1/b.png"])
    storage_service.delete_objects("chat-images", [])  # nothing to do: no call

    assert sent == [("DELETE", "chat-images", {"prefixes": ["r1/a.png"]}),
                    ("DELETE", "chat-images", {"prefixes": ["r1/b.png"]})]
    assert storage_service.avatar_paths("u1") == [
        "avatars/u1/avatar.jpg", "avatars/u1/avatar.png",
        "avatars/u1/avatar.webp", "avatars/u1/avatar.gif"]


def test_the_issue_bucket_is_the_one_screenshots_upload_to():
    assert ap.ISSUE_BUCKET == storage_service.ISSUE_BUCKET


def test_a_classmates_shared_chunk_survives(db, storage, revoked, events):
    _seed_account(db, U, deleted_at=LONG_AGO)
    db.add("user_settings", user_id=OTHER, share_class_context=True)
    db.add("documents", id="mine", user_id=U, deleted_at=None)
    db.add("documents", id="theirs", user_id=OTHER, deleted_at=None)
    db.add("course_chunks", id="joint", doc_id="mine", uploader_id=U,
           visibility="shared", category="lecture_notes")
    for d in ("mine", "theirs"):
        db.add("course_chunk_sources", chunk_id="joint", doc_id=d)
    for u in (U, OTHER):
        db.add("course_chunk_contributors", chunk_id="joint", user_id=u)
    # A failed withdrawal's leftovers: a chunk only U held (its document long
    # gone), and a co-owned one still produced by OTHER's live document.
    db.add("course_chunks", id="solo", doc_id="gone", uploader_id=U,
           visibility="shared", category="lecture_notes")
    db.add("course_chunk_contributors", chunk_id="solo", user_id=U)
    db.add("course_chunks", id="held", doc_id="gone2", uploader_id=OTHER,
           visibility="shared", category="lecture_notes")
    db.add("course_chunk_sources", chunk_id="held", doc_id="theirs")
    db.add("course_chunk_contributors", chunk_id="held", user_id=U)

    ap.purge_account(U, now=NOW)

    ids = sorted(r["id"] for r in db.rows["course_chunks"])
    assert "joint" in ids and "held" in ids and "solo" not in ids
    assert db.of("course_chunk_contributors", user_id=U) == []
    assert db.of("course_chunk_contributors", chunk_id="joint", user_id=OTHER)
    assert db.of("documents", id="theirs")


# ── re-runs and failures ────────────────────────────────────────────────────


def test_a_second_purge_changes_nothing(db, storage, revoked, events):
    _seed_account(db, U, deleted_at=LONG_AGO)
    _seed_account(db, OTHER)
    _seed_room(db)
    ap.purge_account(U, now=NOW)
    before = {name: [dict(r) for r in rows] for name, rows in db.rows.items()}

    again = ap.purge_account(U, now=NOW + timedelta(days=1))

    assert set(again.values()) == {0}
    assert db.rows == before  # purged_at kept its first value too


def test_a_failed_step_raises_incomplete_and_leaves_the_account_unpurged(
    db, storage, revoked, events, monkeypatch,
):
    _seed_account(db, U, deleted_at=LONG_AGO)

    def boom(bucket, paths):
        raise RuntimeError("storage down")

    monkeypatch.setattr(storage_service, "delete_objects", boom)
    with pytest.raises(ap.AccountPurgeIncomplete):
        ap.purge_account(U, now=NOW)

    assert db.of("users", id=U)[0]["purged_at"] is None  # retried on a later pass
    assert events == []


def test_the_audit_event_carries_counts_and_no_personal_content(db, storage, revoked, events):
    _seed_account(db, U, deleted_at=LONG_AGO)

    ap.purge_account(U, now=NOW)

    ((event_type, kw),) = events
    assert event_type == "account.purge" and event_type in events_service.EVENT_TAXONOMY
    assert kw["category"] == "audit" and kw.get("user_id") is None
    payload = kw["payload"]
    assert payload["outcome"] == "purged" and payload["days_since_delete"] == 31
    assert all(isinstance(v, int) for v in payload["counts"].values())
    assert U not in repr(kw)


# ── the table lists agree with the schema ───────────────────────────────────


def test_every_table_the_wipe_keeps_is_purged_anonymised_or_kept_for_a_reason():
    purged = ap.purged_tables()
    unaccounted = sorted(set(aw.KEPT_PER_USER) - purged - set(ap.PURGE_ANONYMIZES)
                         - set(ap.KEPT_AFTER_PURGE))
    assert not unaccounted, (
        f"the admin wipe keeps {unaccounted} and the purge neither removes, anonymises "
        "nor keeps them for a stated reason (services/account_purge.py)"
    )
    assert not set(ap.KEPT_AFTER_PURGE) & purged
    assert not set(ap.PURGE_ANONYMIZES) & purged
    assert all(r.strip() for r in (*ap.KEPT_AFTER_PURGE.values(), *ap.PURGE_ANONYMIZES.values()))


def test_every_user_id_table_is_covered_by_the_purge():
    user_tables = {t for t, has in schema_user_id_columns().items() if has}
    covered = ap.purged_tables() | set(ap.PURGE_ANONYMIZES) | set(ap.KEPT_AFTER_PURGE)
    assert not sorted(user_tables - covered)
    stale = sorted(set(ap.KEPT_AFTER_PURGE) - user_tables)
    assert not stale, f"KEPT_AFTER_PURGE names tables with no user_id column: {stale}"


def test_cascades_the_fake_models_are_the_wipes():
    # The purge leans on the wipe's documented cascades; keep the fakes aligned.
    assert {c for c in CASCADES if not c.startswith("course_chunk")} <= set(aw.WIPED_BY_CASCADE)


# ── sign-in after the purge ─────────────────────────────────────────────────


def _sign_in(monkeypatch, users_select):
    from unittest.mock import MagicMock

    from services.auth import signin
    from tests.split_patches import set_auth_table

    mocks: dict[str, MagicMock] = {}

    def factory(name):
        if name not in mocks:
            m = MagicMock()
            m.select.side_effect = users_select if name == "users" else (lambda *a, **k: [])
            mocks[name] = m
        return mocks[name]

    set_auth_table(monkeypatch, factory)
    monkeypatch.setattr(signin, "_waitlist_entry",
                        lambda email: {"id": "w1", "approved_at": "2026-01-01", "joined_at": None})
    monkeypatch.setattr(signin, "_mark_waitlist_joined", lambda *a: None)
    creds = MagicMock(token="tok", refresh_token=None, expiry=None)
    result = signin.record_google_sign_in(
        email="a@bu.edu", google_id="42", name="A B", first_name="A", last_name="B",
        avatar_url="", creds=creds, local_auto_approve=False,
    )
    return result, mocks


def test_a_purged_stub_is_reopened_as_a_fresh_account(monkeypatch):
    def users_select(columns, filters=None, **_):
        if "google_id" in (filters or {}):
            return []  # the stub's google_id was cleared
        return [{"purged_at": "2026-11-01T00:00:00+00:00"}]

    result, mocks = _sign_in(monkeypatch, users_select)

    assert (result.outcome, result.user_id) == ("approved", "user_42")
    row = mocks["users"].upsert.call_args.args[0]
    assert row["id"] == "user_42" and row["google_id"] == "42"
    assert row["deleted_at"] is None and row["purged_at"] is None


def test_a_new_account_without_a_stub_writes_no_purge_columns(monkeypatch):
    result, mocks = _sign_in(monkeypatch, lambda *a, **k: [])

    assert result.outcome == "approved"
    row = mocks["users"].upsert.call_args.args[0]
    assert "deleted_at" not in row and "purged_at" not in row


def test_an_account_pending_deletion_is_still_refused(monkeypatch):
    def users_select(columns, filters=None, **_):
        return [{"id": "user_42", "is_approved": True, "deleted_at": LONG_AGO}]

    result, mocks = _sign_in(monkeypatch, users_select)

    assert result.outcome == "account_deleted"
    assert not mocks["users"].upsert.called and not mocks["users"].update.called
