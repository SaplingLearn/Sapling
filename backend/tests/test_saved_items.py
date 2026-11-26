"""The Tutor's Saved tab (`/api/learn/saved`, services/saved_items.py; Tutor
redesign, owner decision 2026-11-26), behind the `saved_items` flag.

Driven through the real routes against an in-memory PostgREST stand-in that
honours the filters, order and limit the service sends, so "another student's
item" is decided by the same `user_id` filter production uses. The title and
the text are 🔒 columns: stored sealed to the row, read back in the clear.
"""
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import app
from services import encryption
from services import saved_items as svc

client = TestClient(app, raise_server_exceptions=False)
ME, OTHER = "user_saved_me", "user_saved_other"


def _matches(row: dict, filters: dict | None) -> bool:
    for col, cond in (filters or {}).items():
        assert cond.startswith("eq."), f"filter {col}={cond} not modelled"
        if (None if row.get(col) is None else str(row.get(col))) != cond[3:]:
            return False
    return True


class FakeDB:
    def __init__(self):
        self.rows: dict[str, list[dict]] = {
            "tutor_saved_items": [],
            "sessions": [
                {"id": "ses-mine", "user_id": ME, "offering_id": "off-cs"},
                {"id": "ses-theirs", "user_id": OTHER, "offering_id": "off-cs"},
            ],
        }

    def table(self, name):
        db = self

        class _T:
            def select(self, columns="*", filters=None, order=None, limit=None, **_):
                rows = [dict(r) for r in db.rows[name] if _matches(r, filters)]
                if order:
                    col, _, direction = order.partition(".")
                    rows.sort(key=lambda r: str(r.get(col) or ""), reverse=direction == "desc")
                return rows[:limit] if limit else rows

            def insert(self, data):
                row = {"created_at": f"2026-11-26T00:00:{len(db.rows[name]):02d}+00:00", **data}
                db.rows[name].append(row)
                return [dict(row)]

            def delete(self, filters):
                gone = [r for r in db.rows[name] if _matches(r, filters)]
                db.rows[name] = [r for r in db.rows[name] if r not in gone]
                return gone

        return _T()


@pytest.fixture
def db(monkeypatch):
    monkeypatch.setenv("SAPLING_FLAG_SAVED_ITEMS", "on")
    fake = FakeDB()
    monkeypatch.setattr(svc, "table", fake.table)
    monkeypatch.setattr(svc, "offering_course_id", lambda off: {"off-cs": "course-cs"}.get(off))
    return fake


def _save(**over):
    return client.post("/api/learn/saved", json={"user_id": ME, "session_id": "ses-mine",
                                                  "title": "Linear probing", "content": "A worked example.", **over})


def test_saving_seals_the_text_to_its_row_and_lists_it_back(db):
    r = _save()
    assert r.status_code == 200, r.text
    item = r.json()["item"]
    assert item["title"] == "Linear probing" and item["content"] == "A worked example."
    assert item["session_id"] == "ses-mine" and item["course_id"] == "course-cs"  # the session's course
    [stored] = db.rows["tutor_saved_items"]
    assert "A worked example." not in str(stored["content"]) and "Linear probing" not in str(stored["title"])
    assert encryption.decrypt_if_present(
        stored["content"], bind=encryption.bind("tutor_saved_items", "content", {"id": stored["id"]})) == "A worked example."
    listed = client.get(f"/api/learn/saved/{ME}", params={"session_id": "ses-mine"}).json()["items"]
    assert [(i["id"], i["title"]) for i in listed] == [(item["id"], "Linear probing")]
    by_course = client.get(f"/api/learn/saved/{ME}", params={"course_id": "course-cs"}).json()["items"]
    assert len(by_course) == 1


def test_a_title_defaults_to_the_texts_first_line(db):
    item = _save(title="", content="Key idea: probing\nThe rest of it.").json()["item"]
    assert item["title"] == "Key idea: probing"


def test_only_your_own_session_holds_your_saves(db):
    assert _save(session_id="ses-theirs").status_code == 404
    assert _save(session_id="ses-missing").status_code == 404
    assert db.rows["tutor_saved_items"] == []


def test_empty_or_full_is_refused(db):
    assert _save(content="   ").status_code == 422
    for i in range(svc.PER_SESSION_MAX):
        db.rows["tutor_saved_items"].append({"id": f"x{i}", "user_id": ME, "session_id": "ses-mine"})
    assert _save().status_code == 409


def test_delete_takes_only_your_own_item(db):
    mine = _save().json()["item"]["id"]
    db.rows["tutor_saved_items"].append({"id": "theirs", "user_id": OTHER, "session_id": "ses-theirs"})
    theirs = client.delete("/api/learn/saved/theirs", params={"user_id": ME})
    assert theirs.status_code == 404
    gone = client.delete(f"/api/learn/saved/{mine}", params={"user_id": ME})
    assert gone.json() == {"deleted": True}
    assert [r["id"] for r in db.rows["tutor_saved_items"]] == ["theirs"]


def test_every_route_checks_the_caller_is_the_user(db):
    with patch("routes.saved_items.require_self", side_effect=HTTPException(403, "Forbidden")):
        assert client.get(f"/api/learn/saved/{ME}").status_code == 403
        assert _save().status_code == 403
        deleted = client.delete("/api/learn/saved/x", params={"user_id": ME})
        assert deleted.status_code == 403
    assert db.rows["tutor_saved_items"] == []


def test_the_flag_off_is_a_404(db, monkeypatch):
    monkeypatch.setenv("SAPLING_FLAG_SAVED_ITEMS", "off")
    assert client.get(f"/api/learn/saved/{ME}").status_code == 404
    assert _save().status_code == 404
