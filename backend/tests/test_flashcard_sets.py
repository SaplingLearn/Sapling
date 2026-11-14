"""Route tests for saved flashcard sets (`/api/flashcards/sets`) and the
`due_at` field of the card list (always null until a scheduler writes it).

A set is a name, a course, concept names and two options; it owns no cards.
The routes are thin: the rules live in `services/flashcards/sets.py`, driven
here through the real routes against an in-memory PostgREST stand-in that
honours the filters, order and limit the service sends, so "another user's
set" is decided by the same `user_id` filter production uses.
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from services.flashcards import sets as sets_service

client = TestClient(app, raise_server_exceptions=False)

ME, OTHER = "user_sets_me", "user_sets_other"
COURSE, OTHER_COURSE = "course-cs", "course-bio"
MY_ENROLLMENT = "enr-me-cs"

SET_KEYS = {"id", "name", "course_id", "concepts", "options", "exam_id", "created_at", "updated_at"}


# ── A tiny PostgREST stand-in ───────────────────────────────────────────────


def _matches(row: dict, filters: dict | None) -> bool:
    for col, cond in (filters or {}).items():
        value = None if row.get(col) is None else str(row.get(col))
        if cond.startswith("eq."):
            if value != cond[3:]:
                return False
        elif cond.startswith("in.("):
            if value not in cond[4:-1].split(","):
                return False
        else:
            raise AssertionError(f"filter {col}={cond} not modelled")
    return True


class FakeDB:
    def __init__(self):
        self.rows: dict[str, list[dict]] = {"flashcard_sets": [], "assignments": []}
        self.writes: list[tuple[str, str]] = []

    def add_set(self, set_id, user_id=ME, course_id=COURSE, **over):
        row = {
            "id": set_id, "user_id": user_id, "course_id": course_id, "name": f"Set {set_id}",
            "concepts": ["Recursion"], "options": {}, "exam_id": None,
            "created_at": "2026-11-01T00:00:00+00:00", "updated_at": "2026-11-01T00:00:00+00:00",
            **over,
        }
        self.rows["flashcard_sets"].append(row)
        return row

    def stored(self, set_id):
        return next((r for r in self.rows["flashcard_sets"] if r["id"] == set_id), None)

    def table(self, name):
        db = self

        class _T:
            def select(self, columns="*", filters=None, order=None, limit=None, **_):
                rows = [dict(r) for r in db.rows[name] if _matches(r, filters)]
                for part in reversed((order or "").split(",")):
                    if part:
                        col, _, direction = part.partition(".")
                        rows.sort(key=lambda r: str(r.get(col) or ""), reverse=direction == "desc")
                rows = rows[:limit] if limit else rows
                if columns == "*":
                    return rows
                return [{c: r.get(c) for c in columns.split(",")} for r in rows]

            def insert(self, data):
                db.writes.append(("insert", name))
                db.rows[name].append(dict(data))
                return [dict(data)]

            def update(self, data, filters, **_):
                db.writes.append(("update", name))
                hit = [r for r in db.rows[name] if _matches(r, filters)]
                for r in hit:
                    r.update(data)
                return [dict(r) for r in hit]

            def delete(self, filters):
                db.writes.append(("delete", name))
                gone = [r for r in db.rows[name] if _matches(r, filters)]
                db.rows[name] = [r for r in db.rows[name] if r not in gone]
                return gone

        return _T()


@pytest.fixture
def db(monkeypatch):
    """The sets service on the fake, with ME enrolled in COURSE only (one
    enrollment, holding the assignment `exam-mine`)."""
    fake = FakeDB()
    fake.rows["assignments"] += [
        {"id": "exam-mine", "enrollment_id": MY_ENROLLMENT},
        {"id": "exam-theirs", "enrollment_id": "enr-other-cs"},
    ]
    monkeypatch.setattr(sets_service, "table", fake.table)
    monkeypatch.setattr(
        sets_service, "is_enrolled_in_course",
        lambda user_id, course_id: (user_id, course_id) == (ME, COURSE),
    )
    monkeypatch.setattr(
        sets_service, "scoped_user_enrollments",
        lambda user_id, *, course_id=None, term_id=None: (
            [{"id": MY_ENROLLMENT, "offering_id": "off-cs"}]
            if (user_id, course_id) == (ME, COURSE) else []
        ),
    )
    return fake


def _create(**over):
    body = {"user_id": ME, "name": "Midterm 1", "course_id": COURSE,
            "concepts": ["Recursion", "Big-O"], **over}
    return client.post("/api/flashcards/sets", json=body)


def _detail(response) -> str:
    return str(response.json().get("detail"))


# ── Create ──────────────────────────────────────────────────────────────────


class TestCreate:
    def test_saves_and_returns_the_set(self, db):
        r = _create(options={"only_due": True}, exam_id="exam-mine")

        assert r.status_code == 200
        saved = r.json()["set"]
        assert set(saved) == SET_KEYS
        assert saved["name"] == "Midterm 1" and saved["course_id"] == COURSE
        assert saved["concepts"] == ["Recursion", "Big-O"]
        assert saved["options"] == {"only_due": True, "shuffle": True}
        assert saved["exam_id"] == "exam-mine"
        assert saved["created_at"] and saved["created_at"] == saved["updated_at"]
        row = db.stored(saved["id"])
        assert row["user_id"] == ME
        # Labels are stored as the plaintext they are (like flashcards.topic).
        assert row["name"] == "Midterm 1" and row["concepts"] == ["Recursion", "Big-O"]

    def test_options_default_to_not_only_due_and_shuffled(self, db):
        saved = _create().json()["set"]
        assert saved["options"] == {"only_due": False, "shuffle": True}
        assert saved["exam_id"] is None

    def test_name_is_trimmed_and_concepts_trimmed_and_deduplicated_in_order(self, db):
        r = _create(name="  Finals week  ",
                    concepts=[" Recursion ", "Big-O", "recursion", "BIG-O", "Trees", "Trees "])
        assert r.status_code == 200
        saved = r.json()["set"]
        assert saved["name"] == "Finals week"
        assert saved["concepts"] == ["Recursion", "Big-O", "Trees"]  # first spelling wins

    def test_limits_are_inclusive(self, db):
        r = _create(name="n" * 80, concepts=[f"{i:03d}" + "c" * 117 for i in range(100)])
        assert r.status_code == 200
        assert len(r.json()["set"]["concepts"]) == 100

    @pytest.mark.parametrize("name", ["", "   ", "n" * 81])
    def test_name_must_be_1_to_80_characters(self, db, name):
        r = _create(name=name)
        assert r.status_code == 422 and "name must be 1 to 80 characters" in _detail(r)
        assert db.writes == []

    @pytest.mark.parametrize("concepts,message", [
        ([], "concepts must list 1 to 100 concept names"),
        ([f"c{i}" for i in range(101)], "concepts must list 1 to 100 concept names"),
        (["Recursion", "   "], "each concept name must be 1 to 120 characters"),
        (["c" * 121], "each concept name must be 1 to 120 characters"),
    ])
    def test_concepts_rules(self, db, concepts, message):
        r = _create(concepts=concepts)
        assert r.status_code == 422 and message in _detail(r)
        assert db.writes == []

    @pytest.mark.parametrize("options,message", [
        ({"only_due": True, "autoplay": True}, "unknown option(s): autoplay"),
        ({"shuffle": "yes"}, "option shuffle must be true or false"),
        ({"only_due": 1}, "option only_due must be true or false"),
    ])
    def test_options_take_only_the_two_boolean_keys(self, db, options, message):
        r = _create(options=options)
        assert r.status_code == 422 and message in _detail(r)
        assert db.writes == []

    def test_options_must_be_an_object(self, db):
        assert _create(options=["shuffle"]).status_code == 422
        assert db.writes == []

    def test_course_the_user_is_not_enrolled_in_is_404(self, db):
        r = _create(course_id=OTHER_COURSE)
        assert r.status_code == 404 and _detail(r) == "Course not found."
        assert db.writes == []

    def test_exam_that_is_not_the_users_is_404(self, db):
        r = _create(exam_id="exam-theirs")
        assert r.status_code == 404 and _detail(r) == "Exam not found."
        assert db.writes == []

    def test_at_most_100_sets_per_user(self, db):
        for i in range(sets_service.MAX_SETS_PER_USER - 1):
            db.add_set(f"s{i:03d}")
        for i in range(5):
            db.add_set(f"theirs{i}", user_id=OTHER)  # someone else's never count

        assert _create(name="the hundredth").status_code == 200
        over = _create(name="one too many")

        assert over.status_code == 409
        assert "up to 100 flashcard sets" in _detail(over)
        mine = [r for r in db.rows["flashcard_sets"] if r["user_id"] == ME]
        assert len(mine) == 100 and "one too many" not in {r["name"] for r in mine}


# ── List ────────────────────────────────────────────────────────────────────


class TestList:
    def test_newest_updated_first_and_only_the_users_own(self, db):
        db.add_set("old", updated_at="2026-11-01T00:00:00+00:00")
        db.add_set("new", updated_at="2026-11-05T00:00:00+00:00")
        db.add_set("mid", updated_at="2026-11-03T00:00:00+00:00")
        db.add_set("theirs", user_id=OTHER, updated_at="2026-11-09T00:00:00+00:00")

        r = client.get(f"/api/flashcards/sets/{ME}")

        assert r.status_code == 200
        listed = r.json()["sets"]
        assert [s["id"] for s in listed] == ["new", "mid", "old"]
        assert all(set(s) == SET_KEYS for s in listed)  # never user_id

    def test_course_id_narrows_to_one_course(self, db):
        db.add_set("cs")
        db.add_set("bio", course_id=OTHER_COURSE)

        only_bio = client.get(f"/api/flashcards/sets/{ME}", params={"course_id": OTHER_COURSE})
        everything = client.get(f"/api/flashcards/sets/{ME}")

        assert [s["id"] for s in only_bio.json()["sets"]] == ["bio"]
        assert {s["id"] for s in everything.json()["sets"]} == {"cs", "bio"}

    def test_no_sets_is_an_empty_list(self, db):
        assert client.get(f"/api/flashcards/sets/{ME}").json() == {"sets": []}

    @pytest.mark.parametrize("stored,expected", [
        ({}, {"only_due": False, "shuffle": True}),
        ({"only_due": True}, {"only_due": True, "shuffle": True}),
        ({"only_due": True, "shuffle": False}, {"only_due": True, "shuffle": False}),
        ({"shuffle": "no", "legacy": 1}, {"only_due": False, "shuffle": True}),
        (None, {"only_due": False, "shuffle": True}),
    ])
    def test_options_always_carry_both_keys_whatever_is_stored(self, db, stored, expected):
        db.add_set("s1", options=stored)
        [listed] = client.get(f"/api/flashcards/sets/{ME}").json()["sets"]
        assert listed["options"] == expected


# ── Patch ───────────────────────────────────────────────────────────────────


class TestPatch:
    def _patch(self, set_id, **body):
        return client.patch(f"/api/flashcards/sets/{set_id}", json={"user_id": ME, **body})

    def test_only_the_fields_sent_change(self, db):
        db.add_set("s1", name="Before", concepts=["A", "B"], exam_id="exam-mine",
                   options={"only_due": True, "shuffle": False})

        r = self._patch("s1", name="  After  ")

        assert r.status_code == 200
        out = r.json()["set"]
        assert out["name"] == "After"
        assert out["concepts"] == ["A", "B"] and out["exam_id"] == "exam-mine"
        assert out["options"] == {"only_due": True, "shuffle": False}
        assert out["course_id"] == COURSE
        assert out["updated_at"] > out["created_at"]

    def test_concepts_are_replaced_and_cleaned(self, db):
        db.add_set("s1", concepts=["A", "B"])
        out = self._patch("s1", concepts=[" C ", "c", "D"]).json()["set"]
        assert out["concepts"] == ["C", "D"]
        assert db.stored("s1")["concepts"] == ["C", "D"]

    def test_options_merge_over_the_stored_ones(self, db):
        db.add_set("s1", options={"only_due": True, "shuffle": False})
        out = self._patch("s1", options={"shuffle": True}).json()["set"]
        assert out["options"] == {"only_due": True, "shuffle": True}

    def test_exam_id_null_clears_and_absent_leaves_it(self, db):
        db.add_set("s1", exam_id="exam-mine")

        assert self._patch("s1", name="renamed").json()["set"]["exam_id"] == "exam-mine"
        cleared = self._patch("s1", exam_id=None)

        assert cleared.status_code == 200 and cleared.json()["set"]["exam_id"] is None
        assert db.stored("s1")["exam_id"] is None

    def test_exam_id_can_be_set_to_one_of_the_users_exams_only(self, db):
        db.add_set("s1")
        assert self._patch("s1", exam_id="exam-mine").json()["set"]["exam_id"] == "exam-mine"
        r = self._patch("s1", exam_id="exam-theirs")
        assert r.status_code == 404 and _detail(r) == "Exam not found."
        assert db.stored("s1")["exam_id"] == "exam-mine"

    def test_a_patched_set_moves_to_the_top_of_the_list(self, db):
        db.add_set("older", updated_at="2026-11-01T00:00:00+00:00")
        db.add_set("newer", updated_at="2026-11-02T00:00:00+00:00")
        self._patch("older", name="touched")
        listed = client.get(f"/api/flashcards/sets/{ME}").json()["sets"]
        assert [s["id"] for s in listed] == ["older", "newer"]

    def test_an_empty_patch_changes_nothing(self, db):
        row = db.add_set("s1")
        r = self._patch("s1")
        assert r.status_code == 200 and r.json()["set"]["updated_at"] == row["updated_at"]
        assert db.writes == []

    def test_options_null_changes_nothing(self, db):
        """`options: null` is "no options sent" (as on create), not a change:
        nothing is written, so the set keeps its place in the list."""
        row = db.add_set("s1", options={"only_due": True, "shuffle": False})
        r = self._patch("s1", options=None)
        assert r.status_code == 200
        assert r.json()["set"]["options"] == {"only_due": True, "shuffle": False}
        assert r.json()["set"]["updated_at"] == row["updated_at"] and db.writes == []

    @pytest.mark.parametrize("body", [
        {"name": "   "}, {"name": None}, {"concepts": []}, {"concepts": None},
        {"concepts": ["c" * 121]}, {"options": {"autoplay": True}}, {"options": {"shuffle": 0}},
    ])
    def test_the_create_rules_apply_to_a_patch(self, db, body):
        db.add_set("s1")
        assert self._patch("s1", **body).status_code == 422
        assert db.writes == []

    def test_another_users_set_is_404_and_untouched(self, db):
        theirs = dict(db.add_set("theirs", user_id=OTHER, name="Not yours"))

        r = self._patch("theirs", name="mine now", exam_id=None)

        assert r.status_code == 404 and _detail(r) == "Flashcard set not found."
        assert db.stored("theirs") == theirs and db.writes == []

    def test_a_set_that_does_not_exist_is_the_same_404(self, db):
        r = self._patch("nope", name="x")
        assert r.status_code == 404 and _detail(r) == "Flashcard set not found."


# ── Delete ──────────────────────────────────────────────────────────────────


class TestDelete:
    def test_deletes_the_users_set(self, db):
        db.add_set("s1")
        db.add_set("s2")

        r = client.delete("/api/flashcards/sets/s1", params={"user_id": ME})

        assert r.status_code == 200 and r.json() == {"deleted": True}
        assert db.stored("s1") is None and db.stored("s2") is not None

    def test_another_users_set_is_404_and_kept(self, db):
        db.add_set("theirs", user_id=OTHER)

        r = client.delete("/api/flashcards/sets/theirs", params={"user_id": ME})

        assert r.status_code == 404 and _detail(r) == "Flashcard set not found."
        assert db.stored("theirs") is not None and db.writes == []

    def test_a_set_that_does_not_exist_is_404(self, db):
        r = client.delete("/api/flashcards/sets/nope", params={"user_id": ME})
        assert r.status_code == 404

    def test_the_set_route_is_not_shadowed_by_the_card_delete_route(self, db):
        """`DELETE /{card_id}` sits on the same router; `/sets/<id>` must reach
        the set handler and never touch `flashcards`."""
        db.add_set("s1")
        with patch("services.flashcards.cards.table") as cards_table:
            r = client.delete("/api/flashcards/sets/s1", params={"user_id": ME})
        assert r.json() == {"deleted": True}
        cards_table.assert_not_called()


# ── Guards every set route sits behind ──────────────────────────────────────


def test_every_set_route_checks_the_caller_is_the_user(db):
    db.add_set("s1")
    with patch("routes.flashcards.require_self") as guard:
        client.get(f"/api/flashcards/sets/{ME}")
        _create()
        client.patch("/api/flashcards/sets/s1", json={"user_id": ME, "name": "x"})
        client.delete("/api/flashcards/sets/s1", params={"user_id": ME})
    assert [c.args[0] for c in guard.call_args_list] == [ME, ME, ME, ME]


def test_a_refused_caller_reaches_no_set(db):
    from fastapi import HTTPException

    db.add_set("s1")
    before = dict(db.stored("s1"))
    with patch("routes.flashcards.require_self", side_effect=HTTPException(403, "Forbidden")):
        answers = [
            client.get(f"/api/flashcards/sets/{ME}"),
            _create(),
            client.patch("/api/flashcards/sets/s1", json={"user_id": ME, "name": "x"}),
            client.delete("/api/flashcards/sets/s1", params={"user_id": ME}),
        ]
    assert [a.status_code for a in answers] == [403, 403, 403, 403]
    assert db.stored("s1") == before and db.writes == []


def test_the_set_routes_are_hidden_with_the_study_feature(db, monkeypatch):
    """They are mounted on the flashcards router, so `hide_study` 404s them
    like the rest of `/api/flashcards` (services/feature_flags.NAV_FEATURE_API)."""
    db.add_set("s1")
    monkeypatch.setenv("SAPLING_FLAG_HIDE_STUDY", "on")
    answers = [
        client.get(f"/api/flashcards/sets/{ME}"),
        _create(),
        client.patch("/api/flashcards/sets/s1", json={"user_id": ME, "name": "x"}),
        client.delete("/api/flashcards/sets/s1", params={"user_id": ME}),
    ]
    assert [(a.status_code, a.json().get("detail")) for a in answers] == [(404, "Not found")] * 4
    assert db.stored("s1")["name"] == "Set s1" and db.writes == []


# ── `due_at` on the card list ───────────────────────────────────────────────


def _cards_table(rows, captured):
    def side_effect(name):
        m = MagicMock()
        if name == "flashcards":
            def _select(columns, filters=None, order=None, **_):
                captured["columns"] = columns
                return [dict(r) for r in rows]
            m.select.side_effect = _select
        else:
            m.select.return_value = []
        return m
    return side_effect


_CARD = {"id": "f1", "user_id": ME, "topic": "Recursion", "offering_id": None,
         "front": "q", "back": "a", "times_reviewed": 2, "last_rating": 3,
         "last_reviewed_at": "2026-11-01T00:00:00+00:00", "created_at": "2026-10-01T00:00:00+00:00"}


class TestCardListDueAt:
    def test_a_stored_due_at_is_never_surfaced(self):
        """Nothing writes `flashcards.due_at` (there is no scheduler), so a
        value on a database that still carries the reverted learning-loop
        column is stale: a card frozen "due" forever. The list answers
        `due_at: null` for every card, keeping the key."""
        captured = {}
        rows = [{**_CARD, "due_at": "2026-11-12T09:00:00+00:00"},
                {**_CARD, "id": "f2", "due_at": None}]
        with patch("services.flashcards.cards.table", side_effect=_cards_table(rows, captured)):
            r = client.get(f"/api/flashcards/user/{ME}")
        assert r.status_code == 200
        cards = {c["id"]: c for c in r.json()["flashcards"]}
        assert set(cards) == {"f1", "f2"}
        assert all("due_at" in c and c["due_at"] is None for c in cards.values())

    def test_due_at_is_null_on_a_database_without_the_column(self):
        """No migration here adds `flashcards.due_at`, so the read must not
        name it: a row that lacks the key still lists, with `due_at: null`."""
        captured = {}
        with patch("services.flashcards.cards.table", side_effect=_cards_table([_CARD], captured)):
            r = client.get(f"/api/flashcards/user/{ME}")
        assert r.status_code == 200
        [card] = r.json()["flashcards"]
        assert "due_at" in card and card["due_at"] is None
        assert "due_at" not in captured["columns"]

    def test_only_the_card_fields_are_returned(self):
        """The read is `*`; scheduler bookkeeping a database may carry beside
        `due_at` is not part of the card."""
        captured = {}
        rows = [{**_CARD, "due_at": None, "fsrs_s": 3.2, "fsrs_d": 5.1, "reps": 4, "lapses": 1}]
        with patch("services.flashcards.cards.table", side_effect=_cards_table(rows, captured)):
            [card] = client.get(f"/api/flashcards/user/{ME}").json()["flashcards"]
        assert set(card) == {
            "id", "user_id", "topic", "offering_id", "front", "back", "times_reviewed",
            "last_rating", "last_reviewed_at", "created_at", "due_at", "course_id",
        }
