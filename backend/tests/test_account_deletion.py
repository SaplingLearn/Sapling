"""Deleting an account deletes it (2026-10 audit).

The route used to stamp `users.deleted_at`, which nothing read; signing in
again restored everything. These drive `services.account_deletion` over an
in-memory stand-in for the tables whose foreign keys do NOT cascade from
`users` — the part the database cannot do on its own.
"""

from unittest.mock import patch

import pytest

from services import account_deletion
from services.account_deletion import AccountDeletionBlocked, delete_account

ME, CLASSMATE = "user_me", "user_them"


class FakeTable:
    def __init__(self, rows):
        self.rows = rows

    @staticmethod
    def _cond(row, col, expr):
        op, _, val = expr.partition(".")
        if op == "eq":
            return str(row.get(col)) == val
        if op == "in":
            return str(row.get(col)) in val.strip("()").split(",")
        raise AssertionError(f"unsupported filter {col}={expr}")

    def _match(self, row, filters):
        for col, expr in (filters or {}).items():
            if col == "or":
                terms = [t.split(".", 1) for t in expr.strip("()").split(",")]
                if not any(self._cond(row, c, e) for c, e in terms):
                    return False
            elif not self._cond(row, col, expr):
                return False
        return True

    def select(self, columns="*", filters=None, order=None, limit=None, **_):
        out = [dict(r) for r in self.rows if self._match(r, filters)]
        if order:
            col, _, direction = order.split(",")[0].partition(".")
            out.sort(key=lambda r: str(r.get(col)), reverse=direction == "desc")
        return out[:limit] if limit else out

    def select_with_count(self, columns="*", filters=None, order=None, limit=None, offset=None):
        rows = self.select(columns, filters, order)
        start = offset or 0
        page = rows[start:start + limit] if limit else rows[start:]
        return page, len(rows)

    def delete(self, filters):
        self.rows[:] = [r for r in self.rows if not self._match(r, filters)]
        return []

    def update(self, data, filters, **_):
        for r in self.rows:
            if self._match(r, filters):
                r.update(data)
        return []


TABLES = (
    "users", "admin_audit_log", "oauth_tokens", "enrollments", "events", "llm_usage",
    "course_chunks", "course_chunk_contributors",
    "rooms", "room_members", "room_messages", "room_reactions", "room_activity", "room_summaries",
)


@pytest.fixture
def db():
    data = {t: [] for t in TABLES}
    fakes = {t: FakeTable(rows) for t, rows in data.items()}
    data["users"] += [{"id": ME}, {"id": CLASSMATE}]
    with patch("services.account_deletion.table", side_effect=lambda n: fakes[n]), \
         patch("services.account_deletion.delete_folder") as folders, \
         patch("services.account_deletion.delete_objects") as objects, \
         patch("services.account_deletion.httpx.post") as revoke, \
         patch("services.account_deletion.decrypt", side_effect=lambda v: f"plain:{v}"):
        revoke.return_value.status_code = 200
        data["_mocks"] = {"folders": folders, "objects": objects, "revoke": revoke}
        yield data


def test_admin_audit_history_blocks_before_anything_is_touched(db):
    db["admin_audit_log"].append({"id": "a1", "actor_id": ME})
    db["oauth_tokens"].append({"user_id": ME, "refresh_token": "r", "access_token": "a"})
    with pytest.raises(AccountDeletionBlocked):
        delete_account(ME)
    assert {u["id"] for u in db["users"]} == {ME, CLASSMATE}
    assert db["oauth_tokens"]
    db["_mocks"]["revoke"].assert_not_called()


def test_the_users_row_and_non_cascading_rows_are_gone(db):
    db["oauth_tokens"].append({"user_id": ME, "refresh_token": "r", "access_token": "a"})
    db["enrollments"] += [{"id": "e1", "user_id": ME}, {"id": "e2", "user_id": CLASSMATE}]
    db["events"] += [{"id": "ev1", "user_id": ME}]
    db["llm_usage"] += [{"id": "l1", "user_id": ME}]

    report = delete_account(ME)

    assert [u["id"] for u in db["users"]] == [CLASSMATE]
    assert db["oauth_tokens"] == []
    assert [e["id"] for e in db["enrollments"]] == ["e2"]
    # telemetry keeps its counts, loses the identity
    assert db["events"] == [{"id": "ev1", "user_id": None}]
    assert db["llm_usage"] == [{"id": "l1", "user_id": None}]
    assert report["google_revoked"] is True
    db["_mocks"]["revoke"].assert_called_once()
    assert db["_mocks"]["revoke"].call_args.kwargs["data"] == {"token": "plain:r"}


def test_chunks_private_deleted_shared_released(db):
    db["course_chunks"] += [
        {"id": "p1", "visibility": "private", "uploader_id": ME},
        {"id": "s_alone", "visibility": "shared", "uploader_id": ME},
        {"id": "s_both", "visibility": "shared", "uploader_id": ME},
        {"id": "s_theirs", "visibility": "shared", "uploader_id": CLASSMATE},
        {"id": "p_theirs", "visibility": "private", "uploader_id": CLASSMATE},
    ]
    db["course_chunk_contributors"] += [
        {"chunk_id": "s_alone", "user_id": ME},
        {"chunk_id": "s_both", "user_id": ME},
        {"chunk_id": "s_both", "user_id": CLASSMATE},
        {"chunk_id": "s_theirs", "user_id": CLASSMATE},
    ]

    delete_account(ME)

    assert {c["id"] for c in db["course_chunks"]} == {"s_both", "s_theirs", "p_theirs"}
    assert all(r["user_id"] == CLASSMATE for r in db["course_chunk_contributors"])


def test_rooms_pass_to_a_member_or_are_deleted_when_empty(db):
    db["rooms"] += [
        {"id": "r_shared", "created_by": ME, "owner_id": ME},
        {"id": "r_alone", "created_by": ME, "owner_id": ME},
        {"id": "r_theirs", "created_by": CLASSMATE, "owner_id": CLASSMATE},
    ]
    db["room_members"] += [
        {"room_id": "r_shared", "user_id": ME, "joined_at": "1"},
        {"room_id": "r_shared", "user_id": CLASSMATE, "joined_at": "2"},
        {"room_id": "r_alone", "user_id": ME, "joined_at": "1"},
        {"room_id": "r_theirs", "user_id": ME, "joined_at": "1"},
        {"room_id": "r_theirs", "user_id": CLASSMATE, "joined_at": "2"},
    ]
    db["room_messages"] += [
        {"id": "m_mine", "room_id": "r_theirs", "user_id": ME, "reply_to_id": None,
         "image_url": "https://x.supabase.co/storage/v1/object/public/chat-images/r_theirs/me-1-a.png"},
        {"id": "m_reply", "room_id": "r_theirs", "user_id": CLASSMATE, "reply_to_id": "m_mine",
         "image_url": None},
        {"id": "m_alone", "room_id": "r_alone", "user_id": ME, "reply_to_id": None, "image_url": None},
    ]
    db["room_reactions"] += [{"id": "x1", "message_id": "m_reply", "user_id": ME}]
    db["room_summaries"] += [{"room_id": "r_theirs"}, {"room_id": "r_alone"}]

    delete_account(ME)

    rooms = {r["id"]: r for r in db["rooms"]}
    assert set(rooms) == {"r_shared", "r_theirs"}
    assert rooms["r_shared"]["created_by"] == CLASSMATE
    assert rooms["r_shared"]["owner_id"] == CLASSMATE
    assert all(m["user_id"] != ME for m in db["room_members"])
    msgs = {m["id"]: m for m in db["room_messages"]}
    assert set(msgs) == {"m_reply"}
    assert msgs["m_reply"]["reply_to_id"] is None   # detached, not deleted
    assert db["room_reactions"] == []
    assert db["room_summaries"] == []               # summaries may name them
    db["_mocks"]["objects"].assert_any_call("chat-images", ["r_theirs/me-1-a.png"])


def test_storage_failure_is_reported_not_fatal(db):
    db["_mocks"]["folders"].side_effect = RuntimeError("bucket missing")

    report = delete_account(ME)

    assert report["storage_complete"] is False
    assert [u["id"] for u in db["users"]] == [CLASSMATE]


def test_it_is_safe_to_run_twice(db):
    delete_account(ME)
    delete_account(ME)
    assert [u["id"] for u in db["users"]] == [CLASSMATE]


def test_chat_image_path_parsing():
    assert account_deletion._chat_image_path(
        "https://p.supabase.co/storage/v1/object/public/chat-images/room/u-1-f.png?t=1"
    ) == "room/u-1-f.png"
    assert account_deletion._chat_image_path(None) is None
    assert account_deletion._chat_image_path("https://elsewhere/x.png") is None
