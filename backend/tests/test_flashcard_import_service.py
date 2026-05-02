"""Unit tests for services.flashcard_import_service."""
import io
import json
import os
import sqlite3
import time
import zipfile
from unittest.mock import MagicMock, patch

import pytest

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

    def test_filters_by_topic_when_course_id_is_none(self):
        with patch("services.flashcard_import_service.table") as t:
            t.return_value.select.return_value = []
            svc.dedup_against_existing("u1", None, [], topic="Bio")
            call_kwargs = t.return_value.select.call_args
            assert "Bio" in str(call_kwargs)
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


# ── extract_cards_from_image ─────────────────────────────────────────────────

class TestExtractFromImage:
    def test_runs_extraction_then_gemini_split(self):
        with patch("services.flashcard_import_service.extraction_service") as ext, \
             patch("services.flashcard_import_service.call_gemini") as gem:
            ext.extract_text_from_file.return_value = "# Notes\nMitosis: cell division\nMeiosis: halving"
            gem.return_value = json.dumps([
                {"front": "Mitosis", "back": "cell division"},
                {"front": "Meiosis", "back": "halving"},
            ])
            cards = svc.extract_cards_from_image(b"\x89PNG_fake_bytes", filename="notes.png")

        ext.extract_text_from_file.assert_called_once()
        assert cards == [
            {"front": "Mitosis", "back": "cell division"},
            {"front": "Meiosis", "back": "halving"},
        ]

    def test_returns_empty_on_empty_extraction(self):
        with patch("services.flashcard_import_service.extraction_service") as ext, \
             patch("services.flashcard_import_service.call_gemini") as gem:
            ext.extract_text_from_file.return_value = ""
            cards = svc.extract_cards_from_image(b"", filename="x.png")
        assert cards == []
        gem.assert_not_called()


# ── gemini_generate_cards ────────────────────────────────────────────────────

class TestGenerateCards:
    def test_calls_gemini_with_prompt_and_returns_parsed(self):
        with patch("services.flashcard_import_service.call_gemini") as gem:
            gem.return_value = json.dumps([
                {"front": "Q1", "back": "A1"},
                {"front": "Q2", "back": "A2"},
            ])
            cards = svc.gemini_generate_cards("source notes", count=2, difficulty="recall")
        assert cards == [{"front": "Q1", "back": "A1"}, {"front": "Q2", "back": "A2"}]
        sent = gem.call_args.args[0]
        assert "source notes" in sent
        assert "recall" in sent
        assert "2" in sent

    def test_invalid_json_returns_empty(self):
        with patch("services.flashcard_import_service.call_gemini") as gem:
            gem.return_value = "not valid json"
            assert svc.gemini_generate_cards("x", count=5, difficulty="recall") == []


# ── gemini_cleanup_cards ─────────────────────────────────────────────────────

class TestCleanupCards:
    def test_replaces_cards_in_input_order(self):
        cards = [{"front": "miotsis", "back": "cell div."}]
        with patch("services.flashcard_import_service.call_gemini") as gem:
            gem.return_value = json.dumps([{"front": "Mitosis", "back": "Cell division"}])
            out = svc.gemini_cleanup_cards(cards)
        assert out == [{"front": "Mitosis", "back": "Cell division"}]

    def test_falls_back_to_input_on_invalid_response(self):
        cards = [{"front": "X", "back": "Y"}]
        with patch("services.flashcard_import_service.call_gemini") as gem:
            gem.return_value = "garbage"
            out = svc.gemini_cleanup_cards(cards)
        assert out == cards


# ── gemini_cloze ─────────────────────────────────────────────────────────────

class TestCloze:
    def test_generates_cloze_cards(self):
        with patch("services.flashcard_import_service.call_gemini") as gem:
            gem.return_value = json.dumps([
                {"front": "{{...}} is the powerhouse of the cell.", "back": "Mitochondria"},
            ])
            cards = svc.gemini_cloze("Mitochondria is the powerhouse of the cell.")
        assert cards == [{"front": "{{...}} is the powerhouse of the cell.", "back": "Mitochondria"}]
