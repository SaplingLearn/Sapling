"""Route tests for /api/flashcards — the semester-scoped read/list and the
term-scoped generation context (#141).

The list route (`GET /user/{user_id}`) is user-wide (no course id), so its
`semester` filter works on the cards' `offering_id`: cards whose offering
belongs to the selected term stay, cards from other terms are hidden, and
term-less cards (offering_id NULL — e.g. AI-generated ones) stay visible under
ANY selection so picking a term never makes them unreachable. An unknown label
degrades to "term-less cards only" — never a 500, never everything.

Generation (`POST /generate`) grounds its context in the course's documents;
with a `semester` those documents come from THAT term's offering — a term with
no offering contributes no documents rather than falling back to another
term's (or all of the user's) material.
"""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from main import app
from routes.flashcards import _get_course_documents

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
        with patch("routes.flashcards.table", side_effect=_tables([])):
            r = client.get(f"/api/flashcards/user/{USER_ID}")
        assert r.status_code == 200
        assert [c["id"] for c in r.json()["flashcards"]] == [
            "f-fall", "f-spring", "f-unscoped",
        ]

    def test_semester_keeps_that_terms_cards_plus_termless_ones(self):
        with patch("routes.flashcards.table", side_effect=_tables([{"id": "off-f25"}])), \
             patch("routes.flashcards.term_id_for_label", return_value="term-f25") as tl:
            r = client.get(f"/api/flashcards/user/{USER_ID}?semester=Fall+2025")
        assert r.status_code == 200
        ids = [c["id"] for c in r.json()["flashcards"]]
        assert ids == ["f-fall", "f-unscoped"]  # spring card hidden
        tl.assert_called_once_with("Fall 2025")

    def test_unknown_semester_degrades_to_termless_cards_only(self):
        with patch("routes.flashcards.table", side_effect=_tables([])), \
             patch("routes.flashcards.term_id_for_label", return_value=None):
            r = client.get(f"/api/flashcards/user/{USER_ID}?semester=Never+2099")
        assert r.status_code == 200
        assert [c["id"] for c in r.json()["flashcards"]] == ["f-unscoped"]


class TestCourseDocumentsTermScope:
    @staticmethod
    def _tables(docs, captured):
        def side_effect(name):
            m = MagicMock()
            if name == "courses":
                m.select.return_value = [{"id": "c1"}]
            elif name == "documents":
                def _select(cols, filters=None, order=None, limit=None):
                    captured["filters"] = filters or {}
                    return docs
                m.select.side_effect = _select
            else:
                m.select.return_value = []
            return m
        return side_effect

    def test_no_semester_keeps_current_term_resolution(self):
        captured = {}
        with patch("routes.flashcards.table", side_effect=self._tables([], captured)), \
             patch("routes.flashcards.resolve_offering", return_value="off-cur") as ro:
            _get_course_documents(USER_ID, "Intro CS")
        ro.assert_called_once_with("c1")
        assert captured["filters"]["offering_id"] == "eq.off-cur"

    def test_semester_scopes_the_documents_to_that_terms_offering(self):
        captured = {}
        doc = {"file_name": "a.pdf", "category": "notes",
               "summary": None, "concept_notes": None}
        with patch("routes.flashcards.table", side_effect=self._tables([doc], captured)), \
             patch("routes.flashcards.term_id_for_label", return_value="term-f25") as tl, \
             patch("routes.flashcards.resolve_offering", return_value="off-f25") as ro:
            docs = _get_course_documents(USER_ID, "Intro CS", semester="Fall 2025")
        tl.assert_called_once_with("Fall 2025")
        ro.assert_called_once_with("c1", "term-f25", fallback=False)
        assert captured["filters"]["offering_id"] == "eq.off-f25"
        assert len(docs) == 1

    def test_no_course_match_with_semester_yields_no_docs(self):
        """#475 F2: with an explicit semester there is no term to anchor the
        all-docs fallback to — a course-name miss returns NO documents, never
        every document the user owns."""
        captured = {}

        def side_effect(name):
            m = MagicMock()
            if name == "courses":
                m.select.return_value = []  # no course match
            elif name == "documents":
                def _select(cols, filters=None, order=None, limit=None):
                    captured["filters"] = filters or {}
                    return [{"file_name": "x", "category": None,
                             "summary": None, "concept_notes": None}]
                m.select.side_effect = _select
            else:
                m.select.return_value = []
            return m

        with patch("routes.flashcards.table", side_effect=side_effect):
            docs = _get_course_documents(USER_ID, "Ghost Course", semester="Fall 2025")
        assert docs == []
        assert "filters" not in captured  # the all-docs query never ran

    def test_no_course_match_without_semester_keeps_the_all_docs_fallback(self):
        # Pre-existing behavior, byte-identical: no semester + no course match
        # → every non-deleted document the user owns.
        captured = {}

        def side_effect(name):
            m = MagicMock()
            if name == "courses":
                m.select.return_value = []
            elif name == "documents":
                def _select(cols, filters=None, order=None, limit=None):
                    captured["filters"] = filters or {}
                    return [{"file_name": "x", "category": None,
                             "summary": None, "concept_notes": None}]
                m.select.side_effect = _select
            else:
                m.select.return_value = []
            return m

        with patch("routes.flashcards.table", side_effect=side_effect):
            docs = _get_course_documents(USER_ID, "Ghost Course")
        assert len(docs) == 1
        assert captured["filters"] == {
            "user_id": f"eq.{USER_ID}", "deleted_at": "is.null",
        }

    def test_semester_with_no_offering_yields_no_docs_not_all_docs(self):
        captured = {}
        with patch("routes.flashcards.table", side_effect=self._tables(
                 [{"file_name": "x"}], captured)), \
             patch("routes.flashcards.term_id_for_label", return_value="term-su26"), \
             patch("routes.flashcards.resolve_offering", return_value=None):
            docs = _get_course_documents(USER_ID, "Intro CS", semester="Summer 2026")
        assert docs == []
        # The all-user-documents fallback must NOT fire for a term miss.
        assert "filters" not in captured


class TestGenerateThreadsSemester:
    def test_route_passes_the_semester_into_the_docs_context(self):
        with patch("routes.flashcards._get_course_documents", return_value=[]) as gd, \
             patch("routes.flashcards._get_weak_concepts", return_value=[]), \
             patch("routes.flashcards._generate", return_value=[{"front": "q", "back": "a"}]), \
             patch("routes.flashcards.table", side_effect=_tables([])), \
             patch("services.achievement_service.check_achievements"):
            r = client.post("/api/flashcards/generate", json={
                "user_id": USER_ID, "topic": "Intro CS", "count": 1,
                "semester": "Fall 2025",
            })
        assert r.status_code == 200
        gd.assert_called_once_with(USER_ID, "Intro CS", semester="Fall 2025")


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


class TestFlashcardEncryption:
    def test_generated_cards_encrypted_at_write(self):
        from services.encryption import decrypt

        plaintext_front = "What is a variable?"
        plaintext_back = "A named storage location for a value."
        plaintext_topic = "CS Basics"
        captured_inserts: list[dict] = []

        with patch("routes.flashcards._get_course_documents", return_value=[]), \
             patch("routes.flashcards._get_weak_concepts", return_value=[]), \
             patch("routes.flashcards._generate", return_value=[
                 {"front": plaintext_front, "back": plaintext_back},
             ]), \
             patch("routes.flashcards.table",
                   side_effect=_table_recording_flashcard_inserts(captured_inserts)), \
             patch("services.achievement_service.check_achievements"):
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
             patch("routes.flashcards.resolve_offering", return_value=None), \
             patch("routes.flashcards.table", side_effect=side_effect), \
             patch("routes.flashcards.check_achievements"):
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

        with patch("routes.flashcards.table", side_effect=side_effect):
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

        with patch("routes.flashcards.table", side_effect=side_effect):
            r = client.get(f"/api/flashcards/user/{USER_ID}")

        assert r.status_code == 200
        card = r.json()["flashcards"][0]
        assert card["front"] == "Q"
        assert card["back"] == "A"
