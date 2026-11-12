"""Route tests for /api/flashcards — the semester-scoped read/list and the
term-scoped generation context (#141).

The list route (`GET /user/{user_id}`) is user-wide (no course id), so its
`semester` filter works on the cards' `offering_id`: cards whose offering
belongs to the selected term stay, cards from other terms are hidden, and
term-less cards (offering_id NULL — e.g. AI-generated ones) stay visible under
ANY selection so picking a term never makes them unreachable. An unknown label
degrades to "term-less cards only" — never a 500, never everything.

Generation (`POST /generate`) grounds its context in the user's own documents
for the course (by `course_id` when sent, else the topic matched against the
user's enrolled courses); with a `semester` those documents come from THAT
term's offering — a term with no offering contributes no documents. No
course → no documents: never every document the user owns (#829).
"""
from unittest.mock import MagicMock, patch

import pytest

from fastapi.testclient import TestClient

from main import app
from routes.flashcards import _COURSE_DOC_LIMIT, _get_course_documents
from tests.split_patches import patch_flashcards

client = TestClient(app)

USER_ID = "user_test"

CARDS = [
    {"id": "f-fall", "user_id": USER_ID, "topic": "CS Basics",
     "offering_id": "off-f25", "front": "q1", "back": "a1",
     "times_reviewed": 0, "last_rating": None, "last_reviewed_at": None,
     "created_at": "2026-01-03T00:00:00Z"},
    {"id": "f-spring", "user_id": USER_ID, "topic": "Linear Algebra",
     "offering_id": "off-s26", "front": "q2", "back": "a2",
     "times_reviewed": 0, "last_rating": None, "last_reviewed_at": None,
     "created_at": "2026-01-02T00:00:00Z"},
    {"id": "f-unscoped", "user_id": USER_ID, "topic": "Trivia",
     "offering_id": None, "front": "q3", "back": "a3",
     "times_reviewed": 0, "last_rating": None, "last_reviewed_at": None,
     "created_at": "2026-01-01T00:00:00Z"},
]


def _tables(term_offerings):
    """table() stand-in: all CARDS for flashcards, `term_offerings` rows for
    the course_offerings term lookup."""
    def side_effect(name):
        m = MagicMock()
        if name == "flashcards":
            m.select.return_value = list(CARDS)
        elif name == "course_offerings":
            m.select.return_value = term_offerings
        else:
            m.select.return_value = []
        return m
    return side_effect


class TestListFlashcards:
    def test_unscoped_returns_every_card(self):
        with patch("services.flashcards.cards.table", side_effect=_tables([])):
            r = client.get(f"/api/flashcards/user/{USER_ID}")
        assert r.status_code == 200
        assert [c["id"] for c in r.json()["flashcards"]] == [
            "f-fall", "f-spring", "f-unscoped",
        ]

    def test_semester_keeps_that_terms_cards_plus_termless_ones(self):
        with patch("services.flashcards.cards.table", side_effect=_tables([{"id": "off-f25"}])), \
             patch("services.flashcards.cards.term_id_for_label", return_value="term-f25") as tl:
            r = client.get(f"/api/flashcards/user/{USER_ID}?semester=Fall+2025")
        assert r.status_code == 200
        ids = [c["id"] for c in r.json()["flashcards"]]
        assert ids == ["f-fall", "f-unscoped"]  # spring card hidden
        tl.assert_called_once_with("Fall 2025")

    def test_unknown_semester_degrades_to_termless_cards_only(self):
        with patch("services.flashcards.cards.table", side_effect=_tables([])), \
             patch("services.flashcards.cards.term_id_for_label", return_value=None):
            r = client.get(f"/api/flashcards/user/{USER_ID}?semester=Never+2099")
        assert r.status_code == 200
        assert [c["id"] for c in r.json()["flashcards"]] == ["f-unscoped"]


def _doc_tables(captured, *, courses=(), docs=None, documents_raise=None):
    """table() stand-in for _get_course_documents: records the filters (and
    order/limit) sent to `courses` and `documents`."""
    docs = [{"file_name": "a.pdf", "category": "notes",
             "summary": None, "concept_notes": None}] if docs is None else docs

    def side_effect(name):
        m = MagicMock()
        if name == "courses":
            def _courses(cols, filters=None, order=None, limit=None):
                captured["courses"] = {"filters": filters or {}, "order": order, "limit": limit}
                return list(courses)
            m.select.side_effect = _courses
        elif name == "documents":
            def _docs(cols, filters=None, order=None, limit=None):
                if documents_raise:
                    raise documents_raise
                captured["documents"] = {"filters": filters or {}, "order": order, "limit": limit}
                return [dict(d) for d in docs]
            m.select.side_effect = _docs
        else:
            m.select.return_value = []
        return m
    return side_effect


class TestCourseDocumentsByCourseId:
    """#829 root fix: the Study screen sends the selected course's id, so the
    documents resolve by id — no name matching at all."""

    def test_course_id_reads_the_users_docs_in_every_offering_of_the_course(self):
        captured = {}
        with patch("services.flashcards.context.table", side_effect=_doc_tables(captured)), \
             patch("services.flashcards.context.course_offering_ids",
                   return_value=["off-f25", "off-s26"]) as co, \
             patch("services.flashcards.context.user_enrolled_course_ids") as enrolled:
            docs = _get_course_documents(USER_ID, "Intro CS", course_id="c1")
        co.assert_called_once_with("c1")
        enrolled.assert_not_called()  # no name match, no enrollment gate
        assert "courses" not in captured
        assert captured["documents"]["filters"] == {
            "user_id": f"eq.{USER_ID}",
            "offering_id": "in.(off-f25,off-s26)",
            "deleted_at": "is.null",
        }
        assert captured["documents"]["order"] == "created_at.desc"
        assert captured["documents"]["limit"] == _COURSE_DOC_LIMIT
        assert len(docs) == 1

    def test_course_id_ignores_a_misleading_topic(self):
        # The topic is only the prompt label once a course id is present.
        captured = {}
        with patch("services.flashcards.context.table", side_effect=_doc_tables(captured)), \
             patch("services.flashcards.context.course_offering_ids", return_value=["off-1"]):
            _get_course_documents(USER_ID, "Some Other Name", course_id="c1")
        assert "courses" not in captured
        assert captured["documents"]["filters"]["offering_id"] == "in.(off-1)"

    def test_course_id_with_semester_is_strict_to_that_terms_offering(self):
        captured = {}
        with patch("services.flashcards.context.table", side_effect=_doc_tables(captured)), \
             patch("services.flashcards.context.term_id_for_label", return_value="term-f25") as tl, \
             patch("services.flashcards.context.resolve_offering", return_value="off-f25") as ro, \
             patch("services.flashcards.context.course_offering_ids") as co:
            docs = _get_course_documents(USER_ID, "Intro CS", semester="Fall 2025", course_id="c1")
        tl.assert_called_once_with("Fall 2025")
        ro.assert_called_once_with("c1", "term-f25", fallback=False)
        co.assert_not_called()
        assert captured["documents"]["filters"]["offering_id"] == "in.(off-f25)"
        assert len(docs) == 1

    def test_semester_with_no_offering_yields_no_docs(self):
        captured = {}
        with patch("services.flashcards.context.table", side_effect=_doc_tables(captured)), \
             patch("services.flashcards.context.term_id_for_label", return_value="term-su26"), \
             patch("services.flashcards.context.resolve_offering", return_value=None):
            docs = _get_course_documents(USER_ID, "Intro CS", semester="Summer 2026", course_id="c1")
        assert docs == []
        assert "documents" not in captured  # never widened to other terms

    def test_unknown_semester_label_yields_no_docs(self):
        captured = {}
        with patch("services.flashcards.context.table", side_effect=_doc_tables(captured)), \
             patch("services.flashcards.context.term_id_for_label", return_value=None), \
             patch("services.flashcards.context.resolve_offering") as ro:
            assert _get_course_documents(USER_ID, "Intro CS", semester="Nope", course_id="c1") == []
        ro.assert_not_called()
        assert "documents" not in captured

    def test_offering_scope_unknown_yields_no_docs(self):
        # course_offering_ids -> None = "could not tell" (it logs); never all docs.
        captured = {}
        with patch("services.flashcards.context.table", side_effect=_doc_tables(captured)), \
             patch("services.flashcards.context.course_offering_ids", return_value=None):
            assert _get_course_documents(USER_ID, "Intro CS", course_id="c1") == []
        assert "documents" not in captured


class TestCourseDocumentsByName:
    """No course id (an older client, or a free-text topic): the name is
    matched against the courses the user is ENROLLED in. Regression for the
    original bug: the lookup filtered `courses.user_id`, a column the abstract
    catalog does not have (0020) — PostgREST 400'd, the blanket except
    returned [], and every generation ran with no documents."""

    def test_name_matched_within_enrolled_courses_deterministically(self):
        captured = {}
        with patch("services.flashcards.context.table",
                   side_effect=_doc_tables(captured, courses=[{"id": "c-a"}])), \
             patch("services.flashcards.context.user_enrolled_course_ids",
                   return_value={"c-b", "c-a"}) as enrolled, \
             patch("services.flashcards.context.course_offering_ids", return_value=["off-1"]) as co:
            docs = _get_course_documents(USER_ID, "Intro CS")
        enrolled.assert_called_once_with(USER_ID)
        assert captured["courses"] == {
            "filters": {"course_name": "eq.Intro CS", "id": "in.(c-a,c-b)"},
            "order": "id.asc",
            "limit": 1,
        }
        co.assert_called_once_with("c-a")
        assert captured["documents"]["filters"]["user_id"] == f"eq.{USER_ID}"
        assert len(docs) == 1

    def test_name_match_with_semester_is_strict(self):
        captured = {}
        with patch("services.flashcards.context.table",
                   side_effect=_doc_tables(captured, courses=[{"id": "c1"}])), \
             patch("services.flashcards.context.user_enrolled_course_ids", return_value={"c1"}), \
             patch("services.flashcards.context.term_id_for_label", return_value="term-f25"), \
             patch("services.flashcards.context.resolve_offering", return_value="off-f25") as ro:
            _get_course_documents(USER_ID, "Intro CS", semester="Fall 2025")
        ro.assert_called_once_with("c1", "term-f25", fallback=False)
        assert captured["documents"]["filters"]["offering_id"] == "in.(off-f25)"

    def test_no_enrolled_course_matches_yields_no_docs_never_the_whole_library(self):
        captured = {}
        with patch("services.flashcards.context.table", side_effect=_doc_tables(captured, courses=[])), \
             patch("services.flashcards.context.user_enrolled_course_ids", return_value={"c-other"}):
            docs = _get_course_documents(USER_ID, "Mitosis")
        assert docs == []
        assert "documents" not in captured  # the all-docs read is gone

    def test_no_enrollments_yields_no_docs_without_a_courses_read(self):
        captured = {}
        with patch("services.flashcards.context.table", side_effect=_doc_tables(captured)), \
             patch("services.flashcards.context.user_enrolled_course_ids", return_value=set()):
            assert _get_course_documents(USER_ID, "Intro CS") == []
            assert _get_course_documents(USER_ID, "Intro CS", semester="Fall 2025") == []
        assert captured == {}


class TestCourseDocumentsFailure:
    def test_lookup_failure_is_logged_and_degrades_to_no_docs(self, caplog):
        captured = {}
        with patch("services.flashcards.context.table", side_effect=_doc_tables(
                 captured, documents_raise=RuntimeError("PostgREST 400"))), \
             patch("services.flashcards.context.course_offering_ids", return_value=["off-1"]), \
             caplog.at_level("WARNING", logger="services.flashcards.context"):
            assert _get_course_documents(USER_ID, "Intro CS", course_id="c1") == []
        assert "could not load course documents" in caplog.text
        assert any(r.exc_info for r in caplog.records)


class TestGenerateThreadsSemester:
    def test_route_passes_the_semester_into_the_docs_context(self):
        with patch_flashcards("_get_course_documents", return_value=[]) as gd, \
             patch_flashcards("_get_weak_concepts", return_value=[]), \
             patch_flashcards("generate_flashcards", return_value=[{"front": "q", "back": "a"}]), \
             patch_flashcards("table", side_effect=_tables([])), \
             patch_flashcards("check_achievements"):
            r = client.post("/api/flashcards/generate", json={
                "user_id": USER_ID, "topic": "Intro CS", "count": 1,
                "semester": "Fall 2025",
            })
        assert r.status_code == 200
        gd.assert_called_once_with(USER_ID, "Intro CS", semester="Fall 2025", course_id=None)

    def test_route_passes_the_course_id_into_the_docs_context(self):
        with patch_flashcards("_get_course_documents", return_value=[]) as gd, \
             patch_flashcards("_get_weak_concepts", return_value=[]), \
             patch_flashcards("generate_flashcards", return_value=[{"front": "q", "back": "a"}]), \
             patch_flashcards("table", side_effect=_tables([])), \
             patch_flashcards("check_achievements"):
            r = client.post("/api/flashcards/generate", json={
                "user_id": USER_ID, "topic": "Intro CS", "count": 1, "course_id": "c1",
            })
        assert r.status_code == 200
        gd.assert_called_once_with(USER_ID, "Intro CS", semester=None, course_id="c1")


# ── Encryption at rest (#518) ────────────────────────────────────────────────

def _table_recording_flashcard_inserts(captured_inserts):
    """table() stand-in that records every row passed to flashcards.insert()
    into `captured_inserts`, and returns [] for every other select (so
    _get_course_documents/_get_weak_concepts helpers, when not mocked out,
    degrade harmlessly)."""
    def side_effect(name):
        m = MagicMock()
        m.select.return_value = []
        if name == "flashcards":
            m.insert.side_effect = lambda row: captured_inserts.append(row)
        return m
    return side_effect


class TestGeneratedCardsAreFiledUnderTheirCourse:
    """A card generated for a course is stamped with one of that course's
    offerings, so the list can say which course it belongs to (before this
    every generated card came back with no course at all) — and with the
    offering the list will look for it under: the SELECTED semester's, else
    the one the student is enrolled in, else what the import route uses."""

    def _generate(self, body, *, term_offering=None, enrolled=None, fallback="off-any",
                  term_id="term-f25"):
        """`resolve_offering` answers `term_offering` when asked for a term and
        `fallback` when not; `enrolled` is the student's own offering."""
        captured: list[dict] = []

        def resolve(course_id, term=None, **kwargs):
            return term_offering if term else fallback

        with patch_flashcards("_get_course_documents", return_value=[]), \
             patch_flashcards("_get_weak_concepts", return_value=[]), \
             patch_flashcards("generate_flashcards", return_value=[{"front": "Q", "back": "A"}]), \
             patch_flashcards("resolve_offering", side_effect=resolve) as resolve_mock, \
             patch_flashcards("enrolled_offering_for_course", return_value=enrolled) as enrolled_mock, \
             patch_flashcards("term_id_for_label", return_value=term_id), \
             patch_flashcards("table",
                              side_effect=_table_recording_flashcard_inserts(captured)), \
             patch_flashcards("check_achievements"):
            r = client.post("/api/flashcards/generate", json={"user_id": USER_ID, "count": 1, **body})
        assert r.status_code == 200
        self.response_cards = r.json()["flashcards"]
        self.enrolled_mock = enrolled_mock
        return captured, resolve_mock

    def test_the_selected_semesters_offering_wins(self):
        """With a semester selected the list keeps only that term's cards
        (and term-less ones): filed under the current term's offering instead,
        the cards vanished on reload and were generated (and billed) again."""
        rows, resolve = self._generate(
            {"topic": "Recursion", "course_id": "c1", "semester": "Fall 2025"},
            term_offering="off-f25", enrolled="off-s26",
        )
        resolve.assert_called_once_with("c1", "term-f25", fallback=False)
        self.enrolled_mock.assert_not_called()
        assert [r["offering_id"] for r in rows] == ["off-f25"]

    def test_a_semester_without_an_offering_of_the_course_falls_to_the_enrollment(self):
        rows, _ = self._generate(
            {"topic": "Recursion", "course_id": "c1", "semester": "Summer 2026"},
            term_offering=None, enrolled="off-s26",
        )
        self.enrolled_mock.assert_called_once_with(USER_ID, "c1")
        assert [r["offering_id"] for r in rows] == ["off-s26"]

    def test_an_unknown_semester_label_falls_to_the_enrollment(self):
        rows, resolve = self._generate(
            {"topic": "Recursion", "course_id": "c1", "semester": "Nonsense"},
            term_offering="never", enrolled="off-s26", term_id=None,
        )
        resolve.assert_not_called()
        assert [r["offering_id"] for r in rows] == ["off-s26"]

    def test_without_a_semester_the_students_enrolled_offering_is_stamped(self):
        rows, resolve = self._generate({"topic": "Recursion", "course_id": "c1"}, enrolled="off-s26")
        resolve.assert_not_called()
        assert [r["offering_id"] for r in rows] == ["off-s26"]

    def test_with_a_course_the_student_is_not_enrolled_in_the_offering_is_stamped(self):
        """The import route's rule, last: the course's current-term offering."""
        rows, resolve = self._generate({"topic": "Recursion", "course_id": "c1"}, fallback="off-1")
        resolve.assert_called_once_with("c1")
        assert [r["offering_id"] for r in rows] == ["off-1"]

    def test_without_a_course_the_card_stays_unfiled(self):
        rows, resolve = self._generate({"topic": "Anything"})
        resolve.assert_not_called()
        self.enrolled_mock.assert_not_called()
        assert [r["offering_id"] for r in rows] == [None]

    def test_a_course_id_that_matches_no_offering_leaves_the_card_unfiled(self):
        """`resolve_offering` answers None for an unknown course: the cards are
        still generated and saved, with no course."""
        rows, resolve = self._generate({"topic": "Recursion", "course_id": "no-such-course"},
                                       fallback=None)
        resolve.assert_called_once_with("no-such-course")
        assert [r["offering_id"] for r in rows] == [None]
        assert [c["course_id"] for c in self.response_cards] == [None]

    def test_the_response_says_which_course_the_cards_were_filed_under(self):
        """`course_id` is the key the card list derives; the response carries
        it too, so the page need not guess before its next list fetch. It is
        not a `flashcards` column, so it is never part of the insert."""
        rows, _ = self._generate({"topic": "Recursion", "course_id": "c1"}, enrolled="off-s26")
        assert [(c["course_id"], c["offering_id"]) for c in self.response_cards] == [("c1", "off-s26")]
        assert all("course_id" not in row for row in rows)

    def test_a_failed_offering_lookup_costs_no_generation(self):
        """The offering is resolved BEFORE the model is called, so a database
        failure there never throws away cards the student's budget paid for."""
        with patch_flashcards("_get_course_documents", return_value=[]), \
             patch_flashcards("_get_weak_concepts", return_value=[]), \
             patch_flashcards("generate_flashcards") as model, \
             patch_flashcards("resolve_offering", side_effect=RuntimeError("db down")), \
             patch_flashcards("table") as t:
            r = TestClient(app, raise_server_exceptions=False).post(
                "/api/flashcards/generate",
                json={"user_id": USER_ID, "topic": "Recursion", "count": 1, "course_id": "c1"},
            )
        assert r.status_code == 500
        model.assert_not_called()
        t.return_value.insert.assert_not_called()


class TestFlashcardEncryption:
    def test_generated_cards_encrypted_at_write(self):
        from services.encryption import decrypt

        plaintext_front = "What is a variable?"
        plaintext_back = "A named storage location for a value."
        plaintext_topic = "CS Basics"
        captured_inserts: list[dict] = []

        with patch_flashcards("_get_course_documents", return_value=[]), \
             patch_flashcards("_get_weak_concepts", return_value=[]), \
             patch_flashcards("generate_flashcards", return_value=[
                 {"front": plaintext_front, "back": plaintext_back},
             ]), \
             patch_flashcards("table",
                   side_effect=_table_recording_flashcard_inserts(captured_inserts)), \
             patch_flashcards("check_achievements"):
            r = client.post("/api/flashcards/generate", json={
                "user_id": USER_ID, "topic": plaintext_topic, "count": 1,
            })

        assert r.status_code == 200
        assert len(captured_inserts) == 1
        for row in captured_inserts:
            assert row["front"] != plaintext_front
            assert row["back"] != plaintext_back
            assert decrypt(row["front"]) == plaintext_front
            assert decrypt(row["back"]) == plaintext_back
            # topic stays plaintext (it's a filter column):
            assert row["topic"] == plaintext_topic

        # The API response itself still carries plaintext front/back — the
        # frontend must not see ciphertext for cards it just generated.
        returned = r.json()["flashcards"]
        assert len(returned) == 1
        assert returned[0]["front"] == plaintext_front
        assert returned[0]["back"] == plaintext_back

    def test_import_commit_cards_encrypted_at_write(self):
        from services.encryption import decrypt

        plaintext_front = "Mitosis"
        plaintext_back = "Cell division"
        captured_inserts: list[dict] = []

        def side_effect(name):
            m = MagicMock()
            m.select.return_value = []
            if name == "flashcards":
                m.insert.side_effect = lambda rows: captured_inserts.extend(rows)
            return m

        with patch("routes.flashcards.require_self", return_value=None), \
             patch_flashcards("resolve_offering", return_value=None), \
             patch_flashcards("table", side_effect=side_effect), \
             patch_flashcards("check_achievements"):
            r = client.post("/api/flashcards/import/commit", json={
                "user_id": USER_ID,
                "topic": "Bio",
                "cards": [{"front": plaintext_front, "back": plaintext_back}],
                "dedup": False,
            })

        assert r.status_code == 200
        assert len(captured_inserts) == 1
        row = captured_inserts[0]
        assert row["front"] != plaintext_front
        assert row["back"] != plaintext_back
        assert decrypt(row["front"]) == plaintext_front
        assert decrypt(row["back"]) == plaintext_back

    def test_list_decrypts_front_and_back(self):
        from services.encryption import encrypt

        def side_effect(name):
            m = MagicMock()
            if name == "flashcards":
                m.select.return_value = [{
                    "id": "f1", "user_id": USER_ID, "topic": "Bio",
                    "offering_id": None,
                    "front": encrypt("Q"), "back": encrypt("A"),
                    "times_reviewed": 0, "last_rating": None,
                    "last_reviewed_at": None, "created_at": "2026-01-01T00:00:00Z",
                }]
            else:
                m.select.return_value = []
            return m

        with patch("services.flashcards.cards.table", side_effect=side_effect):
            r = client.get(f"/api/flashcards/user/{USER_ID}")

        assert r.status_code == 200
        card = r.json()["flashcards"][0]
        assert card["front"] == "Q"
        assert card["back"] == "A"

    def test_list_tolerates_legacy_plaintext_rows(self):
        def side_effect(name):
            m = MagicMock()
            if name == "flashcards":
                m.select.return_value = [{
                    "id": "f1", "user_id": USER_ID, "topic": "Bio",
                    "offering_id": None,
                    "front": "Q", "back": "A",
                    "times_reviewed": 0, "last_rating": None,
                    "last_reviewed_at": None, "created_at": "2026-01-01T00:00:00Z",
                }]
            else:
                m.select.return_value = []
            return m

        with patch("services.flashcards.cards.table", side_effect=side_effect):
            r = client.get(f"/api/flashcards/user/{USER_ID}")

        assert r.status_code == 200
        card = r.json()["flashcards"][0]
        assert card["front"] == "Q"
        assert card["back"] == "A"


# ── POST /rate and DELETE /{card_id}: the caller's own card only ─────────────


def _one_card_table(found):
    cards_table = MagicMock()
    cards_table.select.return_value = found
    return cards_table


class TestRateAndDeleteAreTheOwnersOnly:
    """Both look the card up by id AND user id; a card that is another
    student's answers exactly like one that does not exist, and is not
    written. The write carries the same two filters."""

    OWN = {"id": "eq.f1", "user_id": f"eq.{USER_ID}"}

    def test_rating_records_the_review_on_the_users_card(self):
        cards_table = _one_card_table([{"id": "f1", "times_reviewed": 2}])
        with patch_flashcards("table", return_value=cards_table), \
             patch_flashcards("check_achievements"):
            r = client.post("/api/flashcards/rate",
                            json={"user_id": USER_ID, "card_id": "f1", "rating": 2})
        assert r.status_code == 200 and r.json() == {"ok": True}
        assert cards_table.select.call_args.kwargs["filters"] == self.OWN
        written, = cards_table.update.call_args.args
        assert (written["times_reviewed"], written["last_rating"]) == (3, 2)
        assert written["last_reviewed_at"]
        assert cards_table.update.call_args.kwargs["filters"] == self.OWN

    def test_rating_a_card_that_is_not_the_users_is_404_and_unwritten(self):
        cards_table = _one_card_table([])
        with patch_flashcards("table", return_value=cards_table), \
             patch_flashcards("check_achievements") as check:
            r = client.post("/api/flashcards/rate",
                            json={"user_id": USER_ID, "card_id": "f1", "rating": 3})
        assert r.status_code == 404 and r.json()["detail"] == "Flashcard not found"
        cards_table.update.assert_not_called()
        check.assert_not_called()

    def test_delete_removes_the_users_card(self):
        cards_table = _one_card_table([{"id": "f1"}])
        with patch_flashcards("table", return_value=cards_table):
            r = client.delete("/api/flashcards/f1", params={"user_id": USER_ID})
        assert r.status_code == 200 and r.json() == {"ok": True}
        assert cards_table.select.call_args.kwargs["filters"] == self.OWN
        assert cards_table.delete.call_args.kwargs["filters"] == self.OWN

    def test_deleting_a_card_that_is_not_the_users_is_404_and_kept(self):
        cards_table = _one_card_table([])
        with patch_flashcards("table", return_value=cards_table):
            r = client.delete("/api/flashcards/f1", params={"user_id": USER_ID})
        assert r.status_code == 404 and r.json()["detail"] == "Flashcard not found"
        cards_table.delete.assert_not_called()

    def test_a_failed_card_read_is_a_500_with_the_error(self):
        cards_table = MagicMock()
        cards_table.select.side_effect = RuntimeError("connection reset")
        with patch_flashcards("table", return_value=cards_table):
            rated = client.post("/api/flashcards/rate",
                                json={"user_id": USER_ID, "card_id": "f1", "rating": 3})
            deleted = client.delete("/api/flashcards/f1", params={"user_id": USER_ID})
        assert (rated.status_code, deleted.status_code) == (500, 500)
        assert rated.json()["detail"] == "connection reset"
        cards_table.update.assert_not_called()
        cards_table.delete.assert_not_called()


class TestListErrors:
    def test_a_database_without_the_table_lists_no_cards(self):
        with patch("services.flashcards.cards.table",
                   side_effect=RuntimeError('relation "flashcards" does not exist')):
            r = client.get(f"/api/flashcards/user/{USER_ID}")
        assert r.status_code == 200 and r.json() == {"flashcards": []}

    def test_any_other_failure_is_a_500_with_the_error(self):
        with patch("services.flashcards.cards.table", side_effect=RuntimeError("connection reset")):
            r = client.get(f"/api/flashcards/user/{USER_ID}")
        assert r.status_code == 500 and r.json()["detail"] == "connection reset"



# ── Weak concepts: the request's course only ─────────────────────────────────


#: (course, concept, mastery). `graph_nodes.subject` is NULL on every row, as
#: it is for a real account: only seeds ever write it.
_NODES = [
    ("c-cs", "Recursion", 0.10),
    ("c-cs", "Pointers and Memory", 0.20),
    ("c-cs", "Control Flow", 0.90),
    ("c-math", "Eigenvalues", 0.05),
    ("c-math", "Determinants", 0.15),
]


def _graph_tables(reads):
    """`graph_nodes` honouring the `user_id` / `course_id` / `subject` filters
    the weak-concepts read sends; every read's filters land in `reads`."""
    def side_effect(name):
        m = MagicMock()
        m.select.return_value = []
        if name == "graph_nodes":
            def _select(columns, filters=None, **_):
                reads.append(dict(filters or {}))
                if "subject" in (filters or {}):
                    return []
                course = (filters or {}).get("course_id", "").removeprefix("eq.")
                return [{"concept_name": n, "mastery_score": s}
                        for c, n, s in _NODES if not course or c == course]
            m.select.side_effect = _select
        return m
    return side_effect


class TestWeakConceptsStayInTheRequestsCourse:
    """Generation is told to prioritise the student's weak concepts. With no
    course on the read it took them from EVERY course (the `subject` filter
    matches nothing on a real account, so the fall-back to all nodes always
    fired): a "Recursion" deck in CS was told to prioritise linear algebra."""

    def _weak(self, topic, course_id=None):
        from services.flashcards import context

        reads: list[dict] = []
        with patch("services.flashcards.context.table", side_effect=_graph_tables(reads)):
            return context._get_weak_concepts(USER_ID, topic, course_id=course_id), reads

    def test_a_course_id_reads_that_courses_concepts_only(self):
        weak, reads = self._weak("Intro to CS", course_id="c-cs")
        assert weak == ["Recursion", "Pointers and Memory"]  # weakest first
        assert reads == [{"user_id": f"eq.{USER_ID}", "course_id": "eq.c-cs"}]

    def test_a_course_with_no_concepts_never_falls_back_to_other_courses(self):
        weak, reads = self._weak("Intro to Bio", course_id="c-bio")
        assert weak == []
        assert reads == [{"user_id": f"eq.{USER_ID}", "course_id": "eq.c-bio"}]

    @pytest.mark.parametrize("topic", ["Recursion", "  recursion "])
    def test_a_topic_that_is_itself_a_concept_gets_no_other_weak_concepts(self, topic):
        weak, _ = self._weak(topic, course_id="c-cs")
        assert weak == []

    def test_without_a_course_a_concept_topic_still_pulls_in_no_other_course(self):
        """A free-text topic has no course to scope by; when it names one of
        the student's concepts the answer is still "nothing else"."""
        weak, _ = self._weak("Recursion")
        assert weak == []

    def test_without_a_course_a_free_topic_keeps_the_old_whole_graph_answer(self):
        weak, reads = self._weak("Exam cram")
        assert weak[:2] == ["Eigenvalues", "Recursion"] and len(weak) == 4
        assert [sorted(r) for r in reads] == [["subject", "user_id"], ["user_id"]]

    def _prompt_for(self, topic):
        """The prompt the flashcard agent is handed by a real `/generate`."""
        prompts: list[str] = []
        reads: list[dict] = []

        def fake_agent(prompt):
            prompts.append(prompt)
            return [{"front": "Q", "back": "A"}]

        with patch("services.flashcards.context.table", side_effect=_graph_tables(reads)), \
             patch("services.flashcards.importing._run_flashcard_agent", side_effect=fake_agent), \
             patch_flashcards("_get_course_documents", return_value=[]), \
             patch_flashcards("resolve_offering", return_value="off-cs"), \
             patch_flashcards("enrolled_offering_for_course", return_value="off-cs"), \
             patch_flashcards("table"), \
             patch_flashcards("check_achievements"):
            r = client.post("/api/flashcards/generate", json={
                "user_id": USER_ID, "topic": topic, "count": 2, "course_id": "c-cs",
            })
        assert r.status_code == 200
        [prompt] = prompts
        return prompt, r.json()

    def test_the_prompt_for_one_concept_names_no_other_concept(self):
        prompt, body = self._prompt_for("Recursion")
        assert 'Course/Topic: "Recursion"' in prompt
        assert "LOW MASTERY" not in prompt
        for other in ("Eigenvalues", "Determinants", "Pointers and Memory"):
            assert other not in prompt
        assert body["context_used"]["weak_concepts_found"] == 0

    def test_the_prompt_for_a_course_prioritises_that_courses_weak_concepts(self):
        prompt, body = self._prompt_for("Intro to CS")
        assert "prioritize them: Recursion, Pointers and Memory" in prompt
        assert "Eigenvalues" not in prompt and "Determinants" not in prompt
        assert body["context_used"]["weak_concepts_found"] == 2

    def test_the_route_hands_the_course_to_the_weak_concepts_read(self):
        with patch_flashcards("_get_course_documents", return_value=[]), \
             patch_flashcards("_get_weak_concepts", return_value=[]) as weak, \
             patch_flashcards("generate_flashcards", return_value=[]), \
             patch_flashcards("resolve_offering", return_value=None), \
             patch_flashcards("enrolled_offering_for_course", return_value=None), \
             patch_flashcards("table"), \
             patch_flashcards("check_achievements"):
            client.post("/api/flashcards/generate", json={
                "user_id": USER_ID, "topic": "Recursion", "count": 1, "course_id": "c-cs",
            })
        weak.assert_called_once_with(USER_ID, "Recursion", course_id="c-cs")
