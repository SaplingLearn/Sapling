"""Integration tests for /api/flashcards/import/* routes."""
import base64
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def _mock_self():
    return patch("routes.flashcards.require_self", return_value=None)


# ── /import/commit ────────────────────────────────────────────────────────────

class TestImportCommit:
    def test_inserts_cards_and_returns_count(self):
        body = {
            "user_id": "u1",
            "course_id": "c1",
            "topic": "Bio",
            "cards": [
                {"front": "Mitosis", "back": "Cell division"},
                {"front": "Meiosis", "back": "Halving"},
            ],
            "dedup": False,
        }
        with _mock_self(), \
             patch("routes.flashcards.table") as t, \
             patch("routes.flashcards.check_achievements"):
            t.return_value.insert.return_value = []
            r = client.post("/api/flashcards/import/commit", json=body)

        assert r.status_code == 200, r.text
        assert r.json()["inserted"] == 2
        assert r.json()["skipped_duplicates"] == 0

    def test_skips_duplicates_when_dedup_true(self):
        body = {
            "user_id": "u1",
            "course_id": "c1",
            "topic": "Bio",
            "cards": [{"front": "Mitosis", "back": "Cell division"}],
            "dedup": True,
        }
        with _mock_self(), \
             patch("routes.flashcards.dedup_against_existing") as ddp, \
             patch("routes.flashcards.table"), \
             patch("routes.flashcards.check_achievements"):
            ddp.return_value = ([], body["cards"])
            r = client.post("/api/flashcards/import/commit", json=body)
        assert r.status_code == 200
        assert r.json()["inserted"] == 0
        assert r.json()["skipped_duplicates"] == 1

    def test_rejects_other_users(self):
        body = {
            "user_id": "u1",
            "course_id": "c1",
            "topic": "Bio",
            "cards": [{"front": "F", "back": "B"}],
        }
        with patch("services.auth_guard.get_session_user_id", return_value="u2"):
            r = client.post("/api/flashcards/import/commit", json=body)
        assert r.status_code == 403


# ── /import/parse ─────────────────────────────────────────────────────────────

class TestImportParse:
    def _b64(self, b: bytes) -> str:
        return base64.b64encode(b).decode()

    def test_parse_xlsx_route(self):
        body = {
            "user_id": "u1",
            "source": "xlsx",
            "payload": self._b64(b"fake xlsx bytes"),
            "options": {},
        }
        with _mock_self(), patch("routes.flashcards.parse_xlsx") as p:
            p.return_value = [{"front": "F", "back": "B"}]
            r = client.post("/api/flashcards/import/parse", json=body)
        assert r.status_code == 200
        assert r.json()["cards"] == [{"front": "F", "back": "B"}]

    def test_parse_anki_route(self):
        body = {"user_id": "u1", "source": "anki", "payload": self._b64(b"fake apkg")}
        with _mock_self(), patch("routes.flashcards.parse_anki_apkg") as p:
            p.return_value = [{"front": "F", "back": "B"}]
            r = client.post("/api/flashcards/import/parse", json=body)
        assert r.status_code == 200
        assert r.json()["cards"][0]["front"] == "F"

    def test_parse_url_route(self):
        body = {"user_id": "u1", "source": "url", "payload": "https://quizlet.com/x"}
        with _mock_self(), patch("routes.flashcards.scrape_quizlet_url") as p:
            p.return_value = [{"front": "F", "back": "B"}]
            r = client.post("/api/flashcards/import/parse", json=body)
        assert r.status_code == 200
        assert r.json()["cards"][0]["front"] == "F"

    def test_url_blocked_returns_422(self):
        from services.flashcard_import_service import QuizletBlocked
        body = {"user_id": "u1", "source": "url", "payload": "https://quizlet.com/x"}
        with _mock_self(), patch("routes.flashcards.scrape_quizlet_url", side_effect=QuizletBlocked("blocked")):
            r = client.post("/api/flashcards/import/parse", json=body)
        assert r.status_code == 422
        assert "blocked" in r.json()["detail"].lower()

    def test_parse_ocr_route(self):
        body = {
            "user_id": "u1",
            "source": "ocr",
            "payload": self._b64(b"png bytes"),
            "options": {"filename": "notes.png"},
        }
        with _mock_self(), patch("routes.flashcards.extract_cards_from_image") as p:
            p.return_value = [{"front": "F", "back": "B"}]
            r = client.post("/api/flashcards/import/parse", json=body)
        assert r.status_code == 200
        assert r.json()["cards"][0]["front"] == "F"

    def test_payload_too_large_returns_413(self):
        big = self._b64(b"x" * (5 * 1024 * 1024 + 1))
        body = {"user_id": "u1", "source": "xlsx", "payload": big}
        with _mock_self():
            r = client.post("/api/flashcards/import/parse", json=body)
        assert r.status_code == 413


# ── /import/generate ──────────────────────────────────────────────────────────

class TestImportGenerate:
    def test_generate_from_paste_text(self):
        body = {
            "user_id": "u1",
            "source": "paste",
            "text": "Long lecture notes about mitosis...",
            "count": 10,
            "difficulty": "recall",
        }
        with _mock_self(), \
             patch("routes.flashcards.gemini_generate_cards") as gen, \
             patch("routes.flashcards.check_rate_limit", return_value=None):
            gen.return_value = [{"front": "F", "back": "B"}]
            r = client.post("/api/flashcards/import/generate", json=body)
        assert r.status_code == 200
        assert r.json()["cards"][0]["front"] == "F"
        gen.assert_called_once()
        assert "lecture notes" in gen.call_args.args[0]

    def test_generate_from_library_doc(self):
        body = {
            "user_id": "u1",
            "source": "library_doc",
            "document_id": "doc1",
            "count": 5,
            "difficulty": "conceptual",
        }
        with _mock_self(), \
             patch("routes.flashcards.table") as t, \
             patch("routes.flashcards.gemini_generate_cards") as gen, \
             patch("routes.flashcards.check_rate_limit", return_value=None):
            t.return_value.select.return_value = [{
                "id": "doc1", "user_id": "u1", "summary": "doc summary text", "concept_notes": {}
            }]
            gen.return_value = [{"front": "F", "back": "B"}]
            r = client.post("/api/flashcards/import/generate", json=body)
        assert r.status_code == 200
        assert "doc summary text" in gen.call_args.args[0]

    def test_rate_limit_returns_429(self):
        body = {"user_id": "u1", "source": "paste", "text": "x", "count": 5, "difficulty": "recall"}
        with _mock_self(), patch("routes.flashcards.check_rate_limit", return_value=42):
            r = client.post("/api/flashcards/import/generate", json=body)
        assert r.status_code == 429
        assert r.headers.get("Retry-After") == "42"

    def test_paste_without_text_returns_400(self):
        body = {"user_id": "u1", "source": "paste", "count": 5, "difficulty": "recall"}
        with _mock_self(), patch("routes.flashcards.check_rate_limit", return_value=None):
            r = client.post("/api/flashcards/import/generate", json=body)
        assert r.status_code == 400

    def test_library_doc_belonging_to_other_user_returns_404(self):
        body = {"user_id": "u1", "source": "library_doc", "document_id": "doc1", "count": 5, "difficulty": "recall"}
        with _mock_self(), \
             patch("routes.flashcards.table") as t, \
             patch("routes.flashcards.check_rate_limit", return_value=None):
            t.return_value.select.return_value = []
            r = client.post("/api/flashcards/import/generate", json=body)
        assert r.status_code == 404


# ── /import/cleanup ───────────────────────────────────────────────────────────

class TestImportCleanup:
    def test_cleanup_returns_rewritten(self):
        body = {"user_id": "u1", "cards": [{"front": "miotsis", "back": "cell div"}]}
        with _mock_self(), \
             patch("routes.flashcards.gemini_cleanup_cards") as cln, \
             patch("routes.flashcards.check_rate_limit", return_value=None):
            cln.return_value = [{"front": "Mitosis", "back": "Cell division"}]
            r = client.post("/api/flashcards/import/cleanup", json=body)
        assert r.status_code == 200
        assert r.json()["cards"][0]["front"] == "Mitosis"

    def test_cleanup_rate_limited(self):
        body = {"user_id": "u1", "cards": [{"front": "F", "back": "B"}]}
        with _mock_self(), patch("routes.flashcards.check_rate_limit", return_value=10):
            r = client.post("/api/flashcards/import/cleanup", json=body)
        assert r.status_code == 429


# ── /import/cloze ─────────────────────────────────────────────────────────────

class TestImportCloze:
    def test_cloze_returns_cards(self):
        body = {"user_id": "u1", "paragraph": "Mitochondria is the powerhouse of the cell."}
        with _mock_self(), \
             patch("routes.flashcards.gemini_cloze") as cz, \
             patch("routes.flashcards.check_rate_limit", return_value=None):
            cz.return_value = [{"front": "{{...}} is the powerhouse...", "back": "Mitochondria"}]
            r = client.post("/api/flashcards/import/cloze", json=body)
        assert r.status_code == 200
        assert r.json()["cards"][0]["back"] == "Mitochondria"
