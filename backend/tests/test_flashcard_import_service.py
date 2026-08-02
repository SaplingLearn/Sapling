"""Unit tests for services.flashcard_import_service."""
import io
import os
import sqlite3
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.exceptions import ContentFilterError, ModelHTTPError, UnexpectedModelBehavior

from services import flashcard_import_service as svc


# ── dedup_against_existing ───────────────────────────────────────────────────

class TestDedup:
    def _existing_rows(self, fronts):
        return [{"front": f} for f in fronts]

    def test_skips_exact_match(self):
        with patch("services.flashcard_import_service.table") as t:
            t.return_value.select.return_value = self._existing_rows(["What is mitosis?"])
            new = [{"front": "What is mitosis?", "back": "Cell division."}]
            keep, skipped = svc.dedup_against_existing("u1", "c1", new)
        assert keep == []
        assert skipped == new

    def test_skips_near_match_within_levenshtein_3(self):
        with patch("services.flashcard_import_service.table") as t:
            t.return_value.select.return_value = self._existing_rows(["What is mitosis?"])
            new = [{"front": "what is mitosis", "back": "Cell division."}]
            keep, skipped = svc.dedup_against_existing("u1", "c1", new)
        assert keep == []
        assert len(skipped) == 1

    def test_keeps_distinct_card(self):
        with patch("services.flashcard_import_service.table") as t:
            t.return_value.select.return_value = self._existing_rows(["What is mitosis?"])
            new = [{"front": "What is photosynthesis?", "back": "Plants making food."}]
            keep, skipped = svc.dedup_against_existing("u1", "c1", new)
        assert keep == new
        assert skipped == []

    def test_filters_by_offering_id(self):
        # Migration 0025 renamed the flashcards link column course_id -> offering_id.
        with patch("services.flashcard_import_service.table") as t:
            t.return_value.select.return_value = []
            svc.dedup_against_existing("u1", "off1", [])
            _, kwargs = t.return_value.select.call_args
            assert kwargs["filters"] == {"user_id": "eq.u1", "offering_id": "eq.off1"}

    def test_filters_by_topic_when_offering_id_is_none(self):
        with patch("services.flashcard_import_service.table") as t:
            t.return_value.select.return_value = []
            svc.dedup_against_existing("u1", None, [], topic="Bio")
            call_kwargs = t.return_value.select.call_args
            assert "Bio" in str(call_kwargs)
            assert "offering_id" not in str(call_kwargs)
            assert "course_id" not in str(call_kwargs)


# ── check_rate_limit ─────────────────────────────────────────────────────────

class TestRateLimit:
    def setup_method(self):
        svc._rate_state.clear()

    def test_allows_first_5_calls(self):
        for _ in range(5):
            assert svc.check_rate_limit("u1") is None

    def test_sixth_call_returns_retry_after(self):
        for _ in range(5):
            svc.check_rate_limit("u1")
        retry = svc.check_rate_limit("u1")
        assert retry is not None
        assert 0 < retry <= 60

    def test_isolated_per_user(self):
        for _ in range(5):
            svc.check_rate_limit("u1")
        assert svc.check_rate_limit("u2") is None

    def test_resets_after_window(self, monkeypatch):
        now = [1000.0]
        monkeypatch.setattr(svc.time, "time", lambda: now[0])
        for _ in range(5):
            svc.check_rate_limit("u1")
        now[0] = 1061.0  # past 60-second window
        assert svc.check_rate_limit("u1") is None

    def test_retry_capped_at_window_on_coincident_timestamps(self, monkeypatch):
        # Windows' coarse timer (~15.6ms tick) reliably lands a tight loop of
        # calls on the identical time.time() value, so elapsed == 0.0 exactly
        # and the retry hint must still stay within (0, window] (#346).
        monkeypatch.setattr(svc.time, "time", lambda: 1000.0)
        for _ in range(5):
            svc.check_rate_limit("u1")
        assert svc.check_rate_limit("u1") == 60

    def test_retry_uses_ceiling_of_remaining_window(self, monkeypatch):
        now = [1000.0]
        monkeypatch.setattr(svc.time, "time", lambda: now[0])
        for _ in range(5):
            svc.check_rate_limit("u1")
        now[0] = 1059.5  # 0.5s of the window left -> ceil to 1
        assert svc.check_rate_limit("u1") == 1


# ── parse_xlsx ───────────────────────────────────────────────────────────────

from openpyxl import Workbook


def _build_xlsx(rows):
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TestParseXlsx:
    def test_extracts_first_two_columns(self):
        bytes_ = _build_xlsx([
            ("Mitosis", "Cell division for somatic cells"),
            ("Meiosis", "Halving for gametes"),
        ])
        cards = svc.parse_xlsx(bytes_)
        assert cards == [
            {"front": "Mitosis", "back": "Cell division for somatic cells"},
            {"front": "Meiosis", "back": "Halving for gametes"},
        ]

    def test_skips_blank_rows(self):
        bytes_ = _build_xlsx([
            ("Mitosis", "Cell division"),
            ("", ""),
            ("Meiosis", "Halving"),
        ])
        cards = svc.parse_xlsx(bytes_)
        assert len(cards) == 2

    def test_ignores_extra_columns(self):
        bytes_ = _build_xlsx([
            ("Mitosis", "Cell division", "Bio", "Chapter 5"),
        ])
        cards = svc.parse_xlsx(bytes_)
        assert cards == [{"front": "Mitosis", "back": "Cell division"}]

    def test_handles_unicode(self):
        bytes_ = _build_xlsx([("π", "Pi — circumference / diameter 🥧")])
        cards = svc.parse_xlsx(bytes_)
        assert cards[0]["back"].startswith("Pi")


# ── parse_anki_apkg ──────────────────────────────────────────────────────────

def _build_apkg(notes: list[tuple[str, str]]) -> bytes:
    """Build a minimal .apkg = zip containing collection.anki2 SQLite with a
    single notes table whose flds field is \\x1f-separated."""
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".anki2", delete=False) as tmp:
        path = tmp.name
    try:
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, flds TEXT NOT NULL)")
        for i, (front, back) in enumerate(notes):
            conn.execute("INSERT INTO notes (id, flds) VALUES (?, ?)", (i + 1, f"{front}\x1f{back}"))
        conn.commit()
        conn.close()
        with open(path, "rb") as f:
            db_bytes = f.read()
    finally:
        os.unlink(path)

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as z:
        z.writestr("collection.anki2", db_bytes)
    return zip_buf.getvalue()


class TestParseAnki:
    def test_extracts_notes(self):
        bytes_ = _build_apkg([("Mitosis", "Cell division"), ("Meiosis", "Halving")])
        cards = svc.parse_anki_apkg(bytes_)
        assert cards == [
            {"front": "Mitosis", "back": "Cell division"},
            {"front": "Meiosis", "back": "Halving"},
        ]

    def test_strips_html(self):
        bytes_ = _build_apkg([("<b>Mitosis</b>", "<i>Cell</i> division <br>here")])
        cards = svc.parse_anki_apkg(bytes_)
        assert cards[0]["front"] == "Mitosis"
        assert "Cell division here" in cards[0]["back"]

    def test_raises_on_corrupt_zip(self):
        with pytest.raises(ValueError, match="Anki"):
            svc.parse_anki_apkg(b"not a zip file")

    def test_raises_when_collection_missing(self):
        zip_buf = io.BytesIO()
        with zipfile.ZipFile(zip_buf, "w") as z:
            z.writestr("media", "{}")
        with pytest.raises(ValueError, match="collection.anki2"):
            svc.parse_anki_apkg(zip_buf.getvalue())


# ── scrape_quizlet_url ───────────────────────────────────────────────────────

_QUIZLET_PAYLOAD = """
<html><body>
<script>window.Quizlet = window.Quizlet || {}; window.Quizlet["setPageData"] = {"set":{"id":1,"terms":[{"word":"Mitosis","definition":"Cell division"},{"word":"Meiosis","definition":"Halving"}]}};</script>
</body></html>
"""


class TestScrapeQuizlet:
    def test_extracts_terms_from_set_page_data(self):
        resp = MagicMock(status_code=200, text=_QUIZLET_PAYLOAD)
        with patch("services.flashcard_import_service.httpx.get", return_value=resp):
            cards = svc.scrape_quizlet_url("https://quizlet.com/123/abc")
        assert cards == [
            {"front": "Mitosis", "back": "Cell division"},
            {"front": "Meiosis", "back": "Halving"},
        ]

    def test_raises_on_login_wall(self):
        resp = MagicMock(status_code=200, text="<html><body>Please log in</body></html>")
        with patch("services.flashcard_import_service.httpx.get", return_value=resp):
            with pytest.raises(svc.QuizletBlocked):
                svc.scrape_quizlet_url("https://quizlet.com/123/abc")

    def test_raises_on_403(self):
        resp = MagicMock(status_code=403, text="")
        with patch("services.flashcard_import_service.httpx.get", return_value=resp):
            with pytest.raises(svc.QuizletBlocked):
                svc.scrape_quizlet_url("https://quizlet.com/123/abc")


# ── flashcard agent helpers (#146) ───────────────────────────────────────────

def _agent_returning(cards):
    """AsyncMock for flashcard_agent.run returning a Flashcards of these dicts."""
    from agents.flashcard import Flashcards, FlashCard
    fc = Flashcards(cards=[FlashCard(front=c["front"], back=c["back"]) for c in cards])
    return AsyncMock(return_value=SimpleNamespace(output=fc))


# ── extract_cards_from_image ─────────────────────────────────────────────────

class TestExtractFromImage:
    def test_runs_extraction_then_agent_split(self):
        run = _agent_returning([
            {"front": "Mitosis", "back": "cell division"},
            {"front": "Meiosis", "back": "halving"},
        ])
        with patch("services.flashcard_import_service.extraction_service") as ext, \
             patch("services.flashcard_import_service.flashcard_agent.run", new=run):
            ext.extract_text_from_file.return_value = "# Notes\nMitosis: cell division\nMeiosis: halving"
            cards = svc.extract_cards_from_image(b"\x89PNG_fake_bytes", filename="notes.png")

        ext.extract_text_from_file.assert_called_once()
        assert cards == [
            {"front": "Mitosis", "back": "cell division"},
            {"front": "Meiosis", "back": "halving"},
        ]

    def test_returns_empty_on_empty_extraction(self):
        run = _agent_returning([])
        with patch("services.flashcard_import_service.extraction_service") as ext, \
             patch("services.flashcard_import_service.flashcard_agent.run", new=run):
            ext.extract_text_from_file.return_value = ""
            cards = svc.extract_cards_from_image(b"", filename="x.png")
        assert cards == []
        run.assert_not_called()


# ── gemini_generate_cards ────────────────────────────────────────────────────

class TestGenerateCards:
    def test_calls_agent_with_prompt_and_returns_cards(self):
        run = _agent_returning([
            {"front": "Q1", "back": "A1"},
            {"front": "Q2", "back": "A2"},
        ])
        with patch("services.flashcard_import_service.flashcard_agent.run", new=run):
            cards = svc.gemini_generate_cards("source notes", count=2, difficulty="recall")
        assert cards == [{"front": "Q1", "back": "A1"}, {"front": "Q2", "back": "A2"}]
        sent = run.call_args.args[0]  # the rendered prompt handed to the agent
        assert "source notes" in sent
        assert "recall" in sent
        assert "2" in sent

    def test_bad_model_output_degrades_to_empty(self):
        # A model whose output can't satisfy the schema is "bad output" → [].
        run = AsyncMock(side_effect=UnexpectedModelBehavior("unparseable"))
        with patch("services.flashcard_import_service.flashcard_agent.run", new=run):
            assert svc.gemini_generate_cards("x", count=5, difficulty="recall") == []

    def test_transport_failure_propagates(self):
        # Transport/runtime errors must NOT masquerade as "no cards" — they
        # propagate so the route surfaces a retryable 502.
        run = AsyncMock(side_effect=RuntimeError("boom"))
        with patch("services.flashcard_import_service.flashcard_agent.run", new=run):
            with pytest.raises(RuntimeError):
                svc.gemini_generate_cards("x", count=5, difficulty="recall")

    def test_content_filter_propagates(self):
        # A provider content-filter block (e.g. Gemini RECITATION, which the
        # close-grounding flashcard prompt invites) is NOT schema noncompliance.
        # ContentFilterError subclasses UnexpectedModelBehavior, so without its
        # own carve-out it would degrade to [] and the route would answer a
        # misleading 200 with zero cards; it must propagate → route 502 (#340).
        run = AsyncMock(side_effect=ContentFilterError("blocked: RECITATION"))
        with patch("services.flashcard_import_service.flashcard_agent.run", new=run):
            with pytest.raises(ContentFilterError):
                svc.gemini_generate_cards("x", count=5, difficulty="recall")

    def test_non_transient_http_error_propagates(self):
        run = AsyncMock(side_effect=ModelHTTPError(status_code=400, model_name="gemini-2.5-flash"))
        with patch("services.flashcard_import_service.flashcard_agent.run", new=run):
            with pytest.raises(ModelHTTPError):
                svc.gemini_generate_cards("x", count=5, difficulty="recall")

    def test_transient_http_error_retries_then_succeeds(self):
        # 429/5xx is retried once (mirrors the old call_gemini retries=1).
        from agents.flashcard import Flashcards, FlashCard
        ok = SimpleNamespace(output=Flashcards(cards=[FlashCard(front="Q1", back="A1")]))
        run = AsyncMock(side_effect=[
            ModelHTTPError(status_code=429, model_name="gemini-2.5-flash"),
            ok,
        ])
        with patch("services.flashcard_import_service.flashcard_agent.run", new=run), \
             patch("services.flashcard_import_service.time.sleep") as sleep:
            cards = svc.gemini_generate_cards("x", count=1, difficulty="recall")
        assert cards == [{"front": "Q1", "back": "A1"}]
        assert run.call_count == 2
        sleep.assert_called_once()

    def test_transient_http_error_reraises_after_retries_exhausted(self):
        run = AsyncMock(side_effect=ModelHTTPError(status_code=503, model_name="gemini-2.5-flash"))
        with patch("services.flashcard_import_service.flashcard_agent.run", new=run), \
             patch("services.flashcard_import_service.time.sleep"):
            with pytest.raises(ModelHTTPError):
                svc.gemini_generate_cards("x", count=1, difficulty="recall")
        assert run.call_count == 2  # initial + 1 retry

    def test_filters_cards_missing_a_side(self):
        run = _agent_returning([
            {"front": "keep", "back": "yes"},
            {"front": "", "back": "no front"},
            {"front": "no back", "back": ""},
        ])
        with patch("services.flashcard_import_service.flashcard_agent.run", new=run):
            cards = svc.gemini_generate_cards("x", count=3, difficulty="recall")
        assert cards == [{"front": "keep", "back": "yes"}]


# ── gemini_cleanup_cards ─────────────────────────────────────────────────────

class TestCleanupCards:
    def test_replaces_cards_in_input_order(self):
        cards = [{"front": "miotsis", "back": "cell div."}]
        run = _agent_returning([{"front": "Mitosis", "back": "Cell division"}])
        with patch("services.flashcard_import_service.flashcard_agent.run", new=run):
            out = svc.gemini_cleanup_cards(cards)
        assert out == [{"front": "Mitosis", "back": "Cell division"}]

    def test_falls_back_to_input_on_bad_output(self):
        # Cleanup is non-destructive polish: when the model returns nothing
        # usable it keeps the user's original cards rather than erroring.
        cards = [{"front": "X", "back": "Y"}]
        run = AsyncMock(side_effect=UnexpectedModelBehavior("unparseable"))
        with patch("services.flashcard_import_service.flashcard_agent.run", new=run):
            out = svc.gemini_cleanup_cards(cards)
        assert out == cards

    def test_transport_failure_propagates(self):
        # A real outage still propagates (→ route 502), not a silent no-op.
        cards = [{"front": "X", "back": "Y"}]
        run = AsyncMock(side_effect=RuntimeError("boom"))
        with patch("services.flashcard_import_service.flashcard_agent.run", new=run):
            with pytest.raises(RuntimeError):
                svc.gemini_cleanup_cards(cards)

    def test_content_filter_propagates(self):
        # A content-filter block propagates (→ route 502) even on the cleanup
        # path — unlike schema-noncompliant output, which falls back to the
        # user's original cards (#340).
        cards = [{"front": "X", "back": "Y"}]
        run = AsyncMock(side_effect=ContentFilterError("blocked: SAFETY"))
        with patch("services.flashcard_import_service.flashcard_agent.run", new=run):
            with pytest.raises(ContentFilterError):
                svc.gemini_cleanup_cards(cards)


# ── gemini_cloze ─────────────────────────────────────────────────────────────

class TestCloze:
    def test_generates_cloze_cards(self):
        run = _agent_returning([
            {"front": "{{...}} is the powerhouse of the cell.", "back": "Mitochondria"},
        ])
        with patch("services.flashcard_import_service.flashcard_agent.run", new=run):
            cards = svc.gemini_cloze("Mitochondria is the powerhouse of the cell.")
        assert cards == [{"front": "{{...}} is the powerhouse of the cell.", "back": "Mitochondria"}]


# ── generate_flashcards (moved off gemini_service in #146) ────────────────────

class TestGenerateFlashcards:
    def test_returns_agent_cards_with_grounded_prompt(self):
        run = _agent_returning([
            {"front": "What is a base case?", "back": "The stopping condition of a recursion."},
        ])
        with patch("services.flashcard_import_service.flashcard_agent.run", new=run):
            cards = svc.generate_flashcards(
                "Recursion", count=1, weak_concepts=["base case"],
            )
        assert cards == [
            {"front": "What is a base case?", "back": "The stopping condition of a recursion."},
        ]
        sent = run.call_args.args[0]
        assert "Recursion" in sent
        assert "base case" in sent  # weak-concept focus threaded into the prompt

    def test_prompt_grounds_on_documents_and_context(self):
        # Exercises the doc_blocks/concept_notes loop and the extra_block branch:
        # the rendered prompt must carry the document, its concepts, and the
        # free-text context, and the category must be upper-cased.
        run = _agent_returning([{"front": "Q", "back": "A"}])
        documents = [
            {
                "file_name": "week3_lecture.pdf",
                "category": "lecture",  # lowercase → proves category.upper()
                "summary": "Overview of tree traversals.",
                "concept_notes": [
                    {"name": "DFS", "description": "Depth-first traversal."},
                    {"name": "BFS"},  # no description → bare "- BFS" line
                    "not-a-dict",  # non-dict entry is skipped, not fatal
                    {"description": "orphan"},  # missing name → skipped
                ],
            }
        ]
        with patch("services.flashcard_import_service.flashcard_agent.run", new=run):
            cards = svc.generate_flashcards(
                "Data Structures",
                count=3,
                context="Focus on the midterm review session.",
                documents=documents,
                weak_concepts=["recursion depth"],
            )
        assert cards == [{"front": "Q", "back": "A"}]
        sent = run.call_args.args[0]
        # Topic + weak-concept coverage preserved.
        assert "Data Structures" in sent
        assert "recursion depth" in sent
        # Document block: upper-cased category, file name, summary.
        assert "[LECTURE] week3_lecture.pdf" in sent
        assert "Overview of tree traversals." in sent
        # Concept notes: with and without a description.
        assert "- DFS: Depth-first traversal." in sent
        assert "- BFS" in sent
        # Free-text context branch.
        assert "Focus on the midterm review session." in sent


class TestRateLimitClockSkew:
    def test_retry_capped_when_clock_steps_backward(self, monkeypatch):
        # NTP can step time.time() BACKWARD between calls: now < bucket[0]
        # makes the remaining window exceed the 60s window, and bare ceil()
        # would report an impossible retry hint. The min() cap is load-bearing
        # exactly here (#346).
        now = [1000.0]
        monkeypatch.setattr(svc.time, "time", lambda: now[0])
        for _ in range(5):
            svc.check_rate_limit("u-skew")
        now[0] = 998.5  # clock stepped back 1.5s
        assert svc.check_rate_limit("u-skew") == 60
