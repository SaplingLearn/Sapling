"""Integration tests for /api/flashcards/import/* routes."""
import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from tests.split_patches import patch_flashcards

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
             patch_flashcards("resolve_offering", return_value="off1") as ro, \
             patch_flashcards("table") as t, \
             patch_flashcards("check_achievements"):
            t.return_value.insert.return_value = []
            r = client.post("/api/flashcards/import/commit", json=body)

        assert r.status_code == 200, r.text
        assert r.json()["inserted"] == 2
        assert r.json()["skipped_duplicates"] == 0
        # Abstract course id resolved to the offering; the row keys on it.
        ro.assert_called_once_with("c1")
        inserted_rows = t.return_value.insert.call_args[0][0]
        assert all(row["offering_id"] == "off1" for row in inserted_rows)
        assert all("course_id" not in row for row in inserted_rows)

    def test_skips_duplicates_when_dedup_true(self):
        body = {
            "user_id": "u1",
            "course_id": "c1",
            "topic": "Bio",
            "cards": [{"front": "Mitosis", "back": "Cell division"}],
            "dedup": True,
        }
        with _mock_self(), \
             patch_flashcards("dedup_against_existing") as ddp, \
             patch_flashcards("table"), \
             patch_flashcards("check_achievements"):
            ddp.return_value = ([], body["cards"])
            r = client.post("/api/flashcards/import/commit", json=body)
        assert r.status_code == 200
        assert r.json()["inserted"] == 0
        assert r.json()["skipped_duplicates"] == 1

    def test_rejects_other_users(self):
        from services.auth_guard import _real_require_self
        body = {
            "user_id": "u1",
            "course_id": "c1",
            "topic": "Bio",
            "cards": [{"front": "F", "back": "B"}],
        }
        with patch("routes.flashcards.require_self", _real_require_self), \
             patch("services.auth_guard.get_session_user_id", return_value="u2"):
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
        with _mock_self(), patch_flashcards("parse_xlsx") as p:
            p.return_value = [{"front": "F", "back": "B"}]
            r = client.post("/api/flashcards/import/parse", json=body)
        assert r.status_code == 200
        assert r.json()["cards"] == [{"front": "F", "back": "B"}]

    def test_parse_anki_route(self):
        body = {"user_id": "u1", "source": "anki", "payload": self._b64(b"fake apkg")}
        with _mock_self(), patch_flashcards("parse_anki_apkg") as p:
            p.return_value = [{"front": "F", "back": "B"}]
            r = client.post("/api/flashcards/import/parse", json=body)
        assert r.status_code == 200
        assert r.json()["cards"][0]["front"] == "F"

    def test_parse_url_route(self):
        body = {"user_id": "u1", "source": "url", "payload": "https://quizlet.com/x"}
        with _mock_self(), patch_flashcards("scrape_quizlet_url") as p:
            p.return_value = [{"front": "F", "back": "B"}]
            r = client.post("/api/flashcards/import/parse", json=body)
        assert r.status_code == 200
        assert r.json()["cards"][0]["front"] == "F"

    def test_url_blocked_returns_422(self):
        from services.flashcards.importing import QuizletBlocked
        body = {"user_id": "u1", "source": "url", "payload": "https://quizlet.com/x"}
        with _mock_self(), patch_flashcards("scrape_quizlet_url", side_effect=QuizletBlocked("blocked")):
            r = client.post("/api/flashcards/import/parse", json=body)
        assert r.status_code == 422
        assert "blocked" in r.json()["detail"].lower()

    def test_url_rejected_returns_400(self):
        from services.flashcards.importing import QuizletURLRejected
        body = {"user_id": "u1", "source": "url", "payload": "http://169.254.169.254/"}
        with _mock_self(), patch_flashcards(
            "scrape_quizlet_url",
            side_effect=QuizletURLRejected("Only https://quizlet.com set links can be imported."),
        ):
            r = client.post("/api/flashcards/import/parse", json=body)
        assert r.status_code == 400
        assert "quizlet.com" in r.json()["detail"]

    def test_url_ssrf_target_rejected_end_to_end(self):
        # No scraper patch: the real policy runs and refuses before any fetch.
        body = {"user_id": "u1", "source": "url", "payload": "http://169.254.169.254/latest/meta-data/"}
        with _mock_self(), patch("services.flashcards.importing._quizlet_client") as g:
            r = client.post("/api/flashcards/import/parse", json=body)
        assert r.status_code == 400
        g.assert_not_called()

    def test_url_redirected_away_returns_422_not_400(self):
        # A redirect leaving quizlet.com is upstream behaviour, not a bad
        # student URL: 422 so the URL tab offers its Paste fallback.
        import httpx

        def handler(request):
            return httpx.Response(302, headers={"location": "http://169.254.169.254/"})

        body = {"user_id": "u1", "source": "url", "payload": "https://quizlet.com/123/abc"}
        with _mock_self(), patch(
            "services.flashcards.importing.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("104.16.1.1", 443))],
        ), patch(
            "services.flashcards.importing._quizlet_client",
            side_effect=lambda resolver: httpx.Client(transport=httpx.MockTransport(handler)),
        ):
            r = client.post("/api/flashcards/import/parse", json=body)
        assert r.status_code == 422
        assert "redirected away" in r.json()["detail"]

    def test_parse_ocr_route(self):
        body = {
            "user_id": "u1",
            "source": "ocr",
            "payload": self._b64(b"png bytes"),
            "options": {"filename": "notes.png"},
        }
        with _mock_self(), patch_flashcards("extract_cards_from_image") as p:
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
             patch_flashcards("gemini_generate_cards") as gen, \
             patch_flashcards("check_rate_limit", return_value=None):
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
             patch("services.flashcards.cards.table") as t, \
             patch_flashcards("gemini_generate_cards") as gen, \
             patch_flashcards("check_rate_limit", return_value=None):
            t.return_value.select.return_value = [{
                "id": "doc1", "user_id": "u1", "summary": "doc summary text", "concept_notes": {}
            }]
            gen.return_value = [{"front": "F", "back": "B"}]
            r = client.post("/api/flashcards/import/generate", json=body)
        assert r.status_code == 200
        assert "doc summary text" in gen.call_args.args[0]

    def test_rate_limit_returns_429(self):
        body = {"user_id": "u1", "source": "paste", "text": "x", "count": 5, "difficulty": "recall"}
        with _mock_self(), patch_flashcards("check_rate_limit", return_value=42):
            r = client.post("/api/flashcards/import/generate", json=body)
        assert r.status_code == 429
        assert r.headers.get("Retry-After") == "42"
        # The import limiter's own body: `detail` and nothing else.
        assert r.json() == {"detail": "Rate limit hit. Try again in 42s."}

    def test_paste_without_text_returns_400(self):
        body = {"user_id": "u1", "source": "paste", "count": 5, "difficulty": "recall"}
        with _mock_self(), patch_flashcards("check_rate_limit", return_value=None):
            r = client.post("/api/flashcards/import/generate", json=body)
        assert r.status_code == 400

    def test_content_filter_block_returns_502(self):
        # A Gemini content-filter block (e.g. RECITATION) raised at the agent
        # seam must surface as the route's 502 — never 200 {"cards": []} with
        # a success toast for zero cards (#340). Mocks the agent seam (not the
        # service) so the service's exception handling is exercised end-to-end.
        from pydantic_ai.exceptions import ContentFilterError
        body = {"user_id": "u1", "source": "paste", "text": "notes", "count": 5, "difficulty": "recall"}
        run = AsyncMock(side_effect=ContentFilterError("blocked: RECITATION"))
        with _mock_self(), \
             patch("services.flashcards.importing.flashcard_agent.run", new=run), \
             patch_flashcards("check_rate_limit", return_value=None):
            r = client.post("/api/flashcards/import/generate", json=body)
        assert r.status_code == 502
        assert "RECITATION" in r.json()["detail"]

    def test_library_doc_belonging_to_other_user_returns_404(self):
        body = {"user_id": "u1", "source": "library_doc", "document_id": "doc1", "count": 5, "difficulty": "recall"}
        with _mock_self(), \
             patch("services.flashcards.cards.table") as t, \
             patch_flashcards("check_rate_limit", return_value=None):
            t.return_value.select.return_value = []
            r = client.post("/api/flashcards/import/generate", json=body)
        assert r.status_code == 404


# ── /import/cleanup ───────────────────────────────────────────────────────────

class TestImportCleanup:
    def test_cleanup_returns_rewritten(self):
        body = {"user_id": "u1", "cards": [{"front": "miotsis", "back": "cell div"}]}
        with _mock_self(), \
             patch_flashcards("gemini_cleanup_cards") as cln, \
             patch_flashcards("check_rate_limit", return_value=None):
            cln.return_value = [{"front": "Mitosis", "back": "Cell division"}]
            r = client.post("/api/flashcards/import/cleanup", json=body)
        assert r.status_code == 200
        assert r.json()["cards"][0]["front"] == "Mitosis"

    def test_cleanup_rate_limited(self):
        body = {"user_id": "u1", "cards": [{"front": "F", "back": "B"}]}
        with _mock_self(), patch_flashcards("check_rate_limit", return_value=10):
            r = client.post("/api/flashcards/import/cleanup", json=body)
        assert r.status_code == 429


# ── /import/cloze ─────────────────────────────────────────────────────────────

class TestImportCloze:
    def test_cloze_returns_cards(self):
        body = {"user_id": "u1", "paragraph": "Mitochondria is the powerhouse of the cell."}
        with _mock_self(), \
             patch_flashcards("gemini_cloze") as cz, \
             patch_flashcards("check_rate_limit", return_value=None):
            cz.return_value = [{"front": "{{...}} is the powerhouse...", "back": "Mitochondria"}]
            r = client.post("/api/flashcards/import/cloze", json=body)
        assert r.status_code == 200
        assert r.json()["cards"][0]["back"] == "Mitochondria"


# ── #838: an LLM budget refusal is the budget's 429, not the generic 502 ─────

from services.llm_budget import ERROR_CODE, LLMBudgetExceeded, next_reset  # noqa: E402


def _refused(*_a, **_k):
    raise LLMBudgetExceeded(limit=1, used=2, reset_at=next_reset())


@pytest.mark.parametrize("path,target,body", [
    ("/api/flashcards/import/generate", "gemini_generate_cards",
     {"user_id": "u1", "source": "paste", "text": "x", "count": 5, "difficulty": "recall"}),
    ("/api/flashcards/import/cleanup", "gemini_cleanup_cards",
     {"user_id": "u1", "cards": [{"front": "f", "back": "b"}]}),
    ("/api/flashcards/import/cloze", "gemini_cloze",
     {"user_id": "u1", "paragraph": "The mitochondria is the powerhouse of the cell."}),
])
def test_import_llm_routes_answer_a_budget_refusal_with_its_429(path, target, body):
    with _mock_self(), patch_flashcards(target, side_effect=_refused), \
         patch_flashcards("check_rate_limit", return_value=None):
        r = client.post(path, json=body)
    assert r.status_code == 429, r.text
    assert r.json()["error"]["code"] == ERROR_CODE
    assert "Retry-After" in r.headers


def test_ocr_parse_answers_a_budget_refusal_with_its_429():
    """`/import/parse` with source `ocr` runs the flashcard agent: a refused
    run is the budget's 429, not a 502 "Parser error"."""
    body = {"user_id": "u1", "source": "ocr", "payload": base64.b64encode(b"img").decode()}
    with _mock_self(), patch_flashcards("extract_cards_from_image", side_effect=_refused):
        r = client.post("/api/flashcards/import/parse", json=body)
    assert r.status_code == 429, r.text
    assert r.json()["error"]["code"] == ERROR_CODE


def test_a_parser_crash_is_a_502():
    body = {"user_id": "u1", "source": "xlsx", "payload": base64.b64encode(b"x").decode()}
    with _mock_self(), patch_flashcards("parse_xlsx", side_effect=RuntimeError("corrupt")):
        r = client.post("/api/flashcards/import/parse", json=body)
    assert r.status_code == 502 and r.json()["detail"] == "Parser error: corrupt"


def test_generate_answers_a_budget_refusal_with_its_429():
    body = {"user_id": "u1", "topic": "Biology", "count": 3}
    with _mock_self(), patch_flashcards("generate_flashcards", side_effect=_refused), \
         patch_flashcards("table") as t, \
         patch_flashcards("check_achievements"):
        t.return_value.select.return_value = []
        r = client.post("/api/flashcards/generate", json=body)
    assert r.status_code == 429, r.text
    t.return_value.insert.assert_not_called()


def test_other_failures_keep_the_502():
    body = {"user_id": "u1", "paragraph": "p"}
    with _mock_self(), patch_flashcards("gemini_cloze", side_effect=RuntimeError("x")), \
         patch_flashcards("check_rate_limit", return_value=None):
        r = client.post("/api/flashcards/import/cloze", json=body)
    assert r.status_code == 502


def test_the_agent_runner_lets_a_budget_refusal_through_unlogged(caplog):
    from services.flashcards import importing as svc

    with patch.object(svc, "run_agent_sync", side_effect=_refused), \
         patch.object(svc.flashcard_agent, "run", new=lambda *_a, **_k: None), \
         caplog.at_level("ERROR"), pytest.raises(LLMBudgetExceeded):
        svc._run_flashcard_agent("prompt")
    assert not [r for r in caplog.records if r.levelname == "ERROR"]
