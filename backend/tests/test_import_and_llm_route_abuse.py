"""sec2 H2 / M4: the flashcard import parsers survive hostile files, and every
model-reaching route charges a per-user budget.

The bombs are tiny and built in-test; each guard is tested on its own.
"""
from __future__ import annotations

import base64
import io
import os
import sqlite3
import tempfile
import time
import zipfile
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from main import app
from services import abuse_limits
from services.archive_limits import ArchiveTooLarge, check_zip_bounds
from services.flashcards import importing as svc

client = TestClient(app)


# ── helpers ──────────────────────────────────────────────────────────────────


def _sqlite_bytes(*statements: str) -> bytes:
    fd, path = tempfile.mkstemp(suffix=".anki2")
    os.close(fd)
    try:
        conn = sqlite3.connect(path)
        for sql in statements:
            conn.execute(sql)
        conn.commit()
        conn.close()
        with open(path, "rb") as f:
            return f.read()
    finally:
        os.unlink(path)


def _apkg(db_bytes: bytes, extra: dict[str, bytes] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("collection.anki2", db_bytes)
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return buf.getvalue()


# ── Anki: the SQLite file is attacker-shaped ─────────────────────────────────


def test_a_notes_view_over_a_recursive_cte_is_refused_before_any_row_is_read():
    # 4 KB of SQLite that would yield millions of rows through SELECT flds FROM notes.
    db = _sqlite_bytes(
        "CREATE VIEW notes AS WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c "
        "WHERE x < 100000000) SELECT 'a' || char(31) || 'b' AS flds FROM c",
    )
    t0 = time.perf_counter()
    with pytest.raises(ValueError, match="no notes table"):
        svc.parse_anki_apkg(_apkg(db))
    assert time.perf_counter() - t0 < 1.0


def test_a_generated_flds_column_is_refused():
    db = _sqlite_bytes(
        "CREATE TABLE notes (id INTEGER PRIMARY KEY, "
        "flds TEXT GENERATED ALWAYS AS (zeroblob(900000000)) VIRTUAL)",
        "INSERT INTO notes (id) VALUES (1)",
    )
    with pytest.raises(ValueError, match="unexpected notes table"):
        svc.parse_anki_apkg(_apkg(db))


def test_more_notes_than_the_import_cap_is_refused(monkeypatch):
    monkeypatch.setattr(svc, "MAX_IMPORT_CARDS", 5)
    stmts = ["CREATE TABLE notes (id INTEGER PRIMARY KEY, flds TEXT NOT NULL)"]
    stmts += [f"INSERT INTO notes (flds) VALUES ('f{i}' || char(31) || 'b{i}')" for i in range(6)]
    with pytest.raises(ValueError, match="more than 5 notes"):
        svc.parse_anki_apkg(_apkg(_sqlite_bytes(*stmts)))


def test_the_collection_is_opened_read_only():
    stmts = [
        "CREATE TABLE notes (id INTEGER PRIMARY KEY, flds TEXT NOT NULL)",
        "INSERT INTO notes (flds) VALUES ('F' || char(31) || 'B')",
    ]
    seen = []
    real = sqlite3.connect

    def spy(*args, **kwargs):
        seen.append((args, kwargs))
        return real(*args, **kwargs)

    apkg = _apkg(_sqlite_bytes(*stmts))
    with patch.object(svc.sqlite3, "connect", side_effect=spy):
        assert svc.parse_anki_apkg(apkg) == [{"front": "F", "back": "B"}]
    (args, kwargs), = seen
    assert args[0].startswith("file:") and args[0].endswith("?mode=ro")
    assert kwargs == {"uri": True}


def test_a_runaway_query_is_stopped_by_the_deadline(monkeypatch):
    monkeypatch.setattr(svc, "ANKI_QUERY_SECONDS", 0.0)
    stmts = ["CREATE TABLE notes (id INTEGER PRIMARY KEY, flds TEXT NOT NULL)"]
    stmts += ["INSERT INTO notes (flds) SELECT 'a' || char(31) || 'b' FROM "
              "(WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c WHERE x < 50000) "
              "SELECT x FROM c)"]
    with pytest.raises(ValueError, match="not a valid .apkg"):
        svc.parse_anki_apkg(_apkg(_sqlite_bytes(*stmts)))


def test_a_collection_that_inflates_past_the_cap_is_refused_before_it_is_read(monkeypatch):
    monkeypatch.setattr(svc, "MAX_IMPORT_UNCOMPRESSED", 1024 * 1024)
    bomb = _apkg(b"\0" * (2 * 1024 * 1024))  # ~2 KB deflated
    assert len(bomb) < 20_000
    with patch.object(zipfile.ZipFile, "read", side_effect=AssertionError("read")):
        with pytest.raises(ArchiveTooLarge):
            svc.parse_anki_apkg(bomb)


def test_html_parsing_is_bounded_per_field():
    long_field = "<b>" + "x" * (svc.MAX_FIELD_CHARS * 5) + "</b>"
    assert len(svc._strip_html(long_field)) <= svc.MAX_FIELD_CHARS
    # Plain text skips the parser entirely.
    with patch.object(svc, "BeautifulSoup", side_effect=AssertionError("parsed")):
        assert svc._strip_html("plain  text") == "plain text"


def test_html_parsing_is_bounded_per_deck(monkeypatch):
    monkeypatch.setattr(svc, "MAX_HTML_CHARS", 100)
    stmts = ["CREATE TABLE notes (id INTEGER PRIMARY KEY, flds TEXT NOT NULL)"]
    stmts += [f"INSERT INTO notes (flds) VALUES ('{'f' * 40}' || char(31) || '{'b' * 40}')"
              for _ in range(3)]
    with pytest.raises(ValueError, match="too large"):
        svc.parse_anki_apkg(_apkg(_sqlite_bytes(*stmts)))


# ── zip bounds (shared with the Office parsers) ──────────────────────────────


def test_zip_entry_count_is_capped():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i in range(11):
            z.writestr(f"m{i}", b"")
    with pytest.raises(ArchiveTooLarge, match="too many parts"):
        check_zip_bounds(buf.getvalue(), max_entries=10)
    check_zip_bounds(buf.getvalue(), max_entries=11)


def test_non_zip_bytes_pass_the_bounds_check():
    check_zip_bounds(b"not a zip")


def test_an_xlsx_bomb_is_refused(monkeypatch):
    monkeypatch.setattr(svc, "MAX_IMPORT_UNCOMPRESSED", 1024 * 1024)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/worksheets/sheet1.xml", b" " * (2 * 1024 * 1024))
    with pytest.raises(ArchiveTooLarge):
        svc.parse_xlsx(buf.getvalue())


# ── OCR: the type comes from the bytes, not options.filename ─────────────────


def _parse(source, payload: bytes, **options):
    return client.post("/api/flashcards/import/parse", json={
        "user_id": "u1", "source": source,
        "payload": base64.b64encode(payload).decode(), "options": options,
    })


def test_ocr_refuses_bytes_that_are_not_an_image_or_pdf():
    with patch("services.flashcards.import_flow.extract_cards_from_image") as ext:
        r = _parse("ocr", b"PK\x03\x04 a zip pretending", filename="notes.png")
    assert r.status_code == 422
    ext.assert_not_called()


def test_ocr_names_the_file_by_its_bytes():
    with patch("services.flashcards.import_flow.extract_cards_from_image", return_value=[]) as ext:
        r = _parse("ocr", b"%PDF-1.4 a pdf", filename="photo.png")
    assert r.status_code == 200
    assert ext.call_args.kwargs["filename"] == "import.pdf"


# ── /import/parse is charged to the import limiter ───────────────────────────


def test_import_parse_is_rate_limited_per_user():
    with patch("services.flashcards.import_flow.parse_xlsx", return_value=[]) as p:
        codes = [_parse("xlsx", b"x").status_code for _ in range(svc._RATE_LIMIT + 1)]
    assert codes == [200] * svc._RATE_LIMIT + [429]
    assert p.call_count == svc._RATE_LIMIT


# ── Quizlet: the page read is capped ─────────────────────────────────────────


def test_an_oversize_quizlet_page_stops_reading(monkeypatch):
    monkeypatch.setattr(svc, "_QUIZLET_MAX_BYTES", 1000)

    def handler(request):
        return httpx.Response(200, content=b"x" * 5000)

    with patch.object(svc.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("104.16.1.1", 443))]), \
         patch.object(svc, "_quizlet_client",
                      side_effect=lambda resolver: httpx.Client(transport=httpx.MockTransport(handler))):
        with pytest.raises(svc.QuizletBlocked, match="too large"):
            svc.scrape_quizlet_url("https://quizlet.com/1/x")


# ── count is bounded ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("path,body", [
    ("/api/flashcards/generate", {"user_id": "u1", "topic": "Bio", "count": 1000}),
    ("/api/flashcards/generate", {"user_id": "u1", "topic": "Bio", "count": 0}),
    ("/api/flashcards/import/generate",
     {"user_id": "u1", "source": "paste", "text": "t", "count": 1000}),
])
def test_card_counts_are_bounded(path, body):
    assert client.post(path, json=body).status_code == 422


# ── every model-reaching route charges its budget ────────────────────────────


def _refuse(limit, subject):
    raise HTTPException(status_code=429, detail=f"limited:{limit.name}:{subject}")


async def _arefuse(limit, subject):
    _refuse(limit, subject)


@pytest.mark.parametrize("module,fn,method,path,body,limit", [
    ("routes.documents", "enforce_abuse_limit", "post", "/api/documents/doc/d1/scan-concepts",
     {"user_id": "user_andres"}, abuse_limits.CONCEPT_SCAN),
    ("routes.documents", "enforce_abuse_limit", "post", "/api/documents/course/c1/scan-concepts",
     {"user_id": "user_andres"}, abuse_limits.CONCEPT_SCAN),
    ("routes.flashcards", "aenforce_abuse_limit", "post", "/api/flashcards/generate",
     {"user_id": "user_andres", "topic": "Bio"}, abuse_limits.FLASHCARD_GENERATE),
    ("routes.graph", "enforce_abuse_limit", "post", "/api/graph/user_andres/courses",
     {"course_id": "c1"}, abuse_limits.GRAPH_EDIT),
    ("routes.graph", "enforce_abuse_limit", "delete", "/api/graph/user_andres/courses/c1",
     None, abuse_limits.GRAPH_EDIT),
    ("routes.graph", "enforce_abuse_limit", "post", "/api/graph/user_andres/nodes",
     {"concept_name": "X", "course_id": "c1"}, abuse_limits.GRAPH_EDIT),
    ("routes.graph", "enforce_abuse_limit", "delete", "/api/graph/user_andres/nodes/n1",
     None, abuse_limits.GRAPH_EDIT),
    ("routes.graph", "enforce_abuse_limit", "post", "/api/graph/user_andres/concept-description",
     {"concept": "X"}, abuse_limits.CONCEPT_DESCRIBE),
    ("routes.social", "enforce_abuse_limit", "get", "/api/social/rooms/r1/overview",
     None, abuse_limits.ROOM_OVERVIEW),
    ("routes.profile", "enforce_abuse_limit", "patch", "/api/profile/user_andres/settings",
     {"theme": "dark"}, abuse_limits.SETTINGS_WRITE),
    ("routes.study_guide", "aenforce_abuse_limit", "post",
     "/api/study-guide/user_andres/guides/g1/blocks/b1/answer",
     {"option_id": "a"}, abuse_limits.STUDY_GUIDE_ANSWER),
])
def test_model_reaching_routes_charge_a_budget_before_any_work(module, fn, method, path, body, limit):
    import importlib

    mod = importlib.import_module(module)
    stub = _arefuse if fn.startswith("a") else _refuse
    with patch.object(mod, fn, side_effect=stub) as charged, \
         patch("db.connection.table", MagicMock(side_effect=AssertionError("db read"))):
        kwargs = {"json": body} if body is not None else {}
        r = getattr(client, method)(path, **kwargs)
    assert r.status_code == 429, r.text
    assert charged.call_args.args[0] == limit
    assert charged.call_args.args[1] == "user_andres"
