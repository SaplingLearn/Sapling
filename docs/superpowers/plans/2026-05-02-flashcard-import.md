# Flashcard Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a five-tab flashcard import modal (Paste / Upload / URL / AI / Photo) to Sapling's `FlashcardsMode`, plus the backend services that power it.

**Architecture:** One additive DB migration (`flashcards.course_id`). One new service module (`flashcard_import_service.py`) for server-side parsing and Gemini wrappers. Five new routes under `/api/flashcards/import/*`. One modal + per-tab subcomponents + a pure parser library on the frontend. Client-side parses paste / csv / tsv / json; backend parses xlsx / Anki .apkg / Quizlet URL / image OCR.

**Tech Stack:** FastAPI, Supabase (REST via custom `table()` wrapper), Gemini 2.5 Flash (`gemini_service.call_gemini`), pytest, Next.js + React, Papaparse, Sapling's existing `extraction_service` for OCR.

**Spec:** `docs/superpowers/specs/2026-05-02-flashcard-import-design.md`

**Frontend testing note:** Per `CLAUDE.md`, this branch has no automated frontend test framework. Frontend tasks use type-check (`npx tsc --noEmit`) + manual smoke as the verification gate, **not** Jest/Vitest. Backend tasks use real TDD with pytest.

---

## File Map

**Created:**
- `backend/db/migration_flashcard_course_id.sql`
- `backend/services/flashcard_import_service.py`
- `backend/prompts/flashcard_generation.txt`
- `backend/prompts/flashcard_cleanup.txt`
- `backend/prompts/flashcard_cloze.txt`
- `backend/prompts/flashcard_ocr_split.txt`
- `backend/tests/test_flashcard_import_service.py`
- `backend/tests/test_flashcard_import_routes.py`
- `backend/tests/fixtures/sample.apkg` (synthetic; built in-test)
- `backend/tests/fixtures/sample.xlsx` (synthetic; built in-test)
- `frontend/src/components/flashcards/FlashcardImportModal.tsx`
- `frontend/src/components/flashcards/ParsedCardsTable.tsx`
- `frontend/src/components/flashcards/tabs/PasteTab.tsx`
- `frontend/src/components/flashcards/tabs/UploadTab.tsx`
- `frontend/src/components/flashcards/tabs/UrlTab.tsx`
- `frontend/src/components/flashcards/tabs/AiTab.tsx`
- `frontend/src/components/flashcards/tabs/PhotoTab.tsx`
- `frontend/src/lib/flashcardParsers.ts`

**Modified:**
- `backend/db/supabase_schema.sql` — add `course_id` to the `flashcards` CREATE TABLE
- `backend/requirements.txt` — add `openpyxl`, `beautifulsoup4`, `python-Levenshtein`
- `backend/routes/flashcards.py` — add 5 new routes + their Pydantic models
- `frontend/package.json` — add `papaparse` + `@types/papaparse`
- `frontend/src/lib/api.ts` — add 5 new helpers
- `frontend/src/components/screens/Study.tsx` — wire "Import" button into `FlashcardsMode`

---

## Phase 0 — Database

### Task 1: Add `course_id` migration

**Files:**
- Create: `backend/db/migration_flashcard_course_id.sql`
- Modify: `backend/db/supabase_schema.sql:279-291`

- [ ] **Step 1: Write the migration**

Create `backend/db/migration_flashcard_course_id.sql`:

```sql
-- Adds course_id to flashcards so imports can attach to a real course
-- without renaming the existing topic column. Existing rows stay NULL.

ALTER TABLE flashcards
  ADD COLUMN IF NOT EXISTS course_id TEXT REFERENCES courses(id);

CREATE INDEX IF NOT EXISTS idx_flashcards_user_course
  ON flashcards(user_id, course_id);
```

- [ ] **Step 2: Update the canonical schema**

In `backend/db/supabase_schema.sql`, replace the existing `flashcards` CREATE TABLE (lines 279-289) with:

```sql
-- Flashcards
CREATE TABLE IF NOT EXISTS flashcards (
    id               TEXT PRIMARY KEY,
    user_id          TEXT NOT NULL REFERENCES users(id),
    topic            TEXT NOT NULL,
    course_id        TEXT REFERENCES courses(id),
    front            TEXT NOT NULL,
    back             TEXT NOT NULL,
    times_reviewed   INTEGER DEFAULT 0,
    last_rating      INTEGER,
    last_reviewed_at TIMESTAMPTZ,
    created_at       TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_flashcards_user_topic ON flashcards(user_id, topic);
CREATE INDEX IF NOT EXISTS idx_flashcards_user_course ON flashcards(user_id, course_id);
```

- [ ] **Step 3: Apply migration locally**

Run via the Supabase SQL editor (or `psql` against the local DB):

```bash
# If using psql:
psql "$SUPABASE_DB_URL" -f backend/db/migration_flashcard_course_id.sql
```

Expected: `ALTER TABLE` and `CREATE INDEX` succeed; re-running is a no-op due to `IF NOT EXISTS`.

- [ ] **Step 4: Commit**

```bash
git add backend/db/migration_flashcard_course_id.sql backend/db/supabase_schema.sql
git commit -m "feat(db): add course_id to flashcards"
```

---

## Phase 1 — Backend dependencies and service skeleton

### Task 2: Add Python dependencies

**Files:**
- Modify: `backend/requirements.txt`

- [ ] **Step 1: Append deps**

Append to `backend/requirements.txt`:

```
openpyxl
beautifulsoup4
python-Levenshtein
```

- [ ] **Step 2: Install**

Run:

```bash
cd backend && source venv/bin/activate && pip install -r requirements.txt
```

Expected: three new packages install cleanly.

- [ ] **Step 3: Commit**

```bash
git add backend/requirements.txt
git commit -m "chore(backend): add openpyxl, bs4, python-Levenshtein"
```

### Task 3: Create empty service module

**Files:**
- Create: `backend/services/flashcard_import_service.py`

- [ ] **Step 1: Write the module skeleton**

```python
"""
Server-side parsers and Gemini wrappers for flashcard import.

Pure functions only — no Supabase or HTTP coupling beyond the Gemini
client. Each function returns plain dicts the routes can serialize.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import sqlite3
import time
import zipfile
from pathlib import Path
from typing import TypedDict

import httpx
from bs4 import BeautifulSoup
from Levenshtein import distance as _levenshtein

from db.connection import table
from services.gemini_service import call_gemini


class Card(TypedDict):
    front: str
    back: str


class QuizletBlocked(Exception):
    """Raised when scrape_quizlet_url cannot extract cards."""


_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")
```

- [ ] **Step 2: Verify import**

```bash
cd backend && source venv/bin/activate && python -c "from services import flashcard_import_service"
```

Expected: no error.

- [ ] **Step 3: Commit**

```bash
git add backend/services/flashcard_import_service.py
git commit -m "feat(backend): add flashcard_import_service skeleton"
```

---

## Phase 2 — Backend pure functions (TDD)

### Task 4: Dedup function

**Files:**
- Modify: `backend/services/flashcard_import_service.py`
- Create: `backend/tests/test_flashcard_import_service.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_flashcard_import_service.py`:

```python
"""Unit tests for services.flashcard_import_service."""
from unittest.mock import patch

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
            new = [{"front": "What is meiosis?", "back": "Halving."}]
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
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_flashcard_import_service.py::TestDedup -v
```

Expected: FAIL — `AttributeError: module 'services.flashcard_import_service' has no attribute 'dedup_against_existing'`.

- [ ] **Step 3: Implement**

Append to `backend/services/flashcard_import_service.py`:

```python
def _normalize(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text).strip().lower()


def dedup_against_existing(
    user_id: str,
    course_id: str | None,
    cards: list[Card],
    topic: str | None = None,
) -> tuple[list[Card], list[Card]]:
    """Return (keep, skipped) where skipped have a near-duplicate front
    (Levenshtein <= 3 on normalized front) among the user's existing cards
    in the same course (or topic when course_id is None)."""
    filters = {"user_id": f"eq.{user_id}"}
    if course_id:
        filters["course_id"] = f"eq.{course_id}"
    elif topic:
        filters["topic"] = f"eq.{topic}"

    existing = table("flashcards").select("front", filters=filters) or []
    existing_norm = [_normalize(r.get("front", "")) for r in existing]

    keep: list[Card] = []
    skipped: list[Card] = []
    for card in cards:
        norm = _normalize(card.get("front", ""))
        is_dup = any(_levenshtein(norm, e) <= 3 for e in existing_norm if e)
        (skipped if is_dup else keep).append(card)
    return keep, skipped
```

- [ ] **Step 4: Run tests to verify pass**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_flashcard_import_service.py::TestDedup -v
```

Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add backend/services/flashcard_import_service.py backend/tests/test_flashcard_import_service.py
git commit -m "feat(backend): dedup_against_existing with Levenshtein"
```

### Task 5: Rate-limit helper

**Files:**
- Modify: `backend/services/flashcard_import_service.py`
- Modify: `backend/tests/test_flashcard_import_service.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_flashcard_import_service.py`:

```python
import time

from services import flashcard_import_service as svc


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
```

- [ ] **Step 2: Run to verify fail**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_flashcard_import_service.py::TestRateLimit -v
```

Expected: FAIL — `AttributeError: module ... has no attribute '_rate_state'`.

- [ ] **Step 3: Implement**

Append to `backend/services/flashcard_import_service.py`:

```python
_RATE_WINDOW_SEC = 60
_RATE_LIMIT = 5
_rate_state: dict[str, list[float]] = {}


def check_rate_limit(user_id: str) -> int | None:
    """Returns None if call allowed, else seconds until allowed again."""
    now = time.time()
    bucket = [t for t in _rate_state.get(user_id, []) if now - t < _RATE_WINDOW_SEC]
    if len(bucket) >= _RATE_LIMIT:
        retry = int(_RATE_WINDOW_SEC - (now - bucket[0])) + 1
        _rate_state[user_id] = bucket
        return retry
    bucket.append(now)
    _rate_state[user_id] = bucket
    return None
```

- [ ] **Step 4: Run to verify pass**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_flashcard_import_service.py::TestRateLimit -v
```

Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add backend/services/flashcard_import_service.py backend/tests/test_flashcard_import_service.py
git commit -m "feat(backend): add per-user rate limit helper for AI imports"
```

### Task 6: Parse `.xlsx`

**Files:**
- Modify: `backend/services/flashcard_import_service.py`
- Modify: `backend/tests/test_flashcard_import_service.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_flashcard_import_service.py`:

```python
import io
from openpyxl import Workbook

from services import flashcard_import_service as svc


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
```

- [ ] **Step 2: Run to verify fail**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_flashcard_import_service.py::TestParseXlsx -v
```

Expected: FAIL — `parse_xlsx` not defined.

- [ ] **Step 3: Implement**

Append to `backend/services/flashcard_import_service.py`:

```python
def parse_xlsx(file_bytes: bytes) -> list[Card]:
    """Read a .xlsx workbook, treating col A as front and col B as back."""
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
    ws = wb.active
    cards: list[Card] = []
    for row in ws.iter_rows(values_only=True):
        if not row:
            continue
        front = (str(row[0]) if len(row) > 0 and row[0] is not None else "").strip()
        back = (str(row[1]) if len(row) > 1 and row[1] is not None else "").strip()
        if front and back:
            cards.append({"front": front, "back": back})
    return cards
```

- [ ] **Step 4: Run to verify pass**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_flashcard_import_service.py::TestParseXlsx -v
```

Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add backend/services/flashcard_import_service.py backend/tests/test_flashcard_import_service.py
git commit -m "feat(backend): parse_xlsx for flashcard import"
```

### Task 7: Parse Anki `.apkg`

**Files:**
- Modify: `backend/services/flashcard_import_service.py`
- Modify: `backend/tests/test_flashcard_import_service.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_flashcard_import_service.py`:

```python
import sqlite3
import zipfile

from services import flashcard_import_service as svc


def _build_apkg(notes: list[tuple[str, str]]) -> bytes:
    """Build a minimal .apkg = zip containing collection.anki2 SQLite with a
    single notes table whose flds field is \\x1f-separated."""
    db_buf = io.BytesIO()
    # Build SQLite into a temp file because sqlite3 wants a path
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
```

- [ ] **Step 2: Run to verify fail**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_flashcard_import_service.py::TestParseAnki -v
```

Expected: FAIL — `parse_anki_apkg` not defined.

- [ ] **Step 3: Implement**

Append to `backend/services/flashcard_import_service.py`:

```python
def _strip_html(text: str) -> str:
    soup = BeautifulSoup(text or "", "html.parser")
    return re.sub(r"\s+", " ", soup.get_text(" ")).strip()


def parse_anki_apkg(file_bytes: bytes) -> list[Card]:
    """Extract notes from an Anki .apkg (zip with a SQLite collection.anki2)."""
    import tempfile

    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
            names = z.namelist()
            if "collection.anki2" not in names:
                raise ValueError("Anki package is missing collection.anki2")
            db_bytes = z.read("collection.anki2")
    except zipfile.BadZipFile as e:
        raise ValueError(f"Anki file is not a valid .apkg: {e}")

    with tempfile.NamedTemporaryFile(suffix=".anki2", delete=False) as tmp:
        tmp.write(db_bytes)
        path = tmp.name

    try:
        conn = sqlite3.connect(path)
        rows = conn.execute("SELECT flds FROM notes").fetchall()
        conn.close()
    finally:
        os.unlink(path)

    cards: list[Card] = []
    for (flds,) in rows:
        if not flds:
            continue
        parts = flds.split("\x1f")
        if len(parts) < 2:
            continue
        front = _strip_html(parts[0])
        back = _strip_html(parts[1])
        if front and back:
            cards.append({"front": front, "back": back})
    return cards
```

- [ ] **Step 4: Run to verify pass**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_flashcard_import_service.py::TestParseAnki -v
```

Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add backend/services/flashcard_import_service.py backend/tests/test_flashcard_import_service.py
git commit -m "feat(backend): parse_anki_apkg with HTML stripping"
```

### Task 8: Scrape Quizlet URL

**Files:**
- Modify: `backend/services/flashcard_import_service.py`
- Modify: `backend/tests/test_flashcard_import_service.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_flashcard_import_service.py`:

```python
from unittest.mock import MagicMock, patch

from services import flashcard_import_service as svc


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
```

- [ ] **Step 2: Run to verify fail**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_flashcard_import_service.py::TestScrapeQuizlet -v
```

Expected: FAIL — `scrape_quizlet_url` not defined.

- [ ] **Step 3: Implement**

Append to `backend/services/flashcard_import_service.py`:

```python
_QUIZLET_PAYLOAD_RE = re.compile(
    r'window\.Quizlet\["setPageData"\]\s*=\s*(\{.*?\});',
    re.DOTALL,
)


def scrape_quizlet_url(url: str) -> list[Card]:
    """Best-effort fetch of a public Quizlet set. Raises QuizletBlocked on
    bot wall, login redirect, or unparseable payload."""
    try:
        resp = httpx.get(
            url,
            timeout=15.0,
            headers={"User-Agent": "Mozilla/5.0 (Sapling flashcard import)"},
            follow_redirects=True,
        )
    except httpx.HTTPError as e:
        raise QuizletBlocked(f"Could not reach Quizlet: {e}")

    if resp.status_code != 200:
        raise QuizletBlocked(f"Quizlet returned status {resp.status_code}")

    match = _QUIZLET_PAYLOAD_RE.search(resp.text)
    if not match:
        raise QuizletBlocked(
            "Couldn't extract cards from this URL. Quizlet may be blocking "
            "scrapers — try exporting the set and pasting the text instead."
        )

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as e:
        raise QuizletBlocked(f"Quizlet payload was not valid JSON: {e}")

    terms = (data.get("set") or {}).get("terms") or []
    cards: list[Card] = []
    for t in terms:
        front = (t.get("word") or "").strip()
        back = (t.get("definition") or "").strip()
        if front and back:
            cards.append({"front": front, "back": back})
    if not cards:
        raise QuizletBlocked("No terms found in the Quizlet payload.")
    return cards
```

- [ ] **Step 4: Run to verify pass**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_flashcard_import_service.py::TestScrapeQuizlet -v
```

Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add backend/services/flashcard_import_service.py backend/tests/test_flashcard_import_service.py
git commit -m "feat(backend): scrape_quizlet_url with graceful blocking"
```

### Task 9: Image OCR → Q/A pairs

**Files:**
- Modify: `backend/services/flashcard_import_service.py`
- Modify: `backend/tests/test_flashcard_import_service.py`
- Create: `backend/prompts/flashcard_ocr_split.txt`

- [ ] **Step 1: Write the prompt**

Create `backend/prompts/flashcard_ocr_split.txt`:

```
You are extracting flashcards from OCR'd notes.

Input below is markdown extracted from a photo of a student's notes.
Identify question/answer or term/definition pairs and return them as a
JSON array of {"front": "...", "back": "..."} objects. If a section is
prose without clear pairs, generate sensible recall flashcards from it.

Return ONLY the JSON array — no surrounding prose or markdown fences.

INPUT:
{markdown}
```

- [ ] **Step 2: Write the failing test**

Append to `backend/tests/test_flashcard_import_service.py`:

```python
class TestExtractFromImage:
    def test_runs_extraction_then_gemini_split(self):
        with patch("services.flashcard_import_service.extraction_service") as ext, \
             patch("services.flashcard_import_service.call_gemini") as gem:
            ext.extract_text_from_bytes.return_value = "# Notes\nMitosis: cell division\nMeiosis: halving"
            gem.return_value = json.dumps([
                {"front": "Mitosis", "back": "cell division"},
                {"front": "Meiosis", "back": "halving"},
            ])
            cards = svc.extract_cards_from_image(b"\x89PNG_fake_bytes", filename="notes.png")

        ext.extract_text_from_bytes.assert_called_once()
        assert cards == [
            {"front": "Mitosis", "back": "cell division"},
            {"front": "Meiosis", "back": "halving"},
        ]

    def test_returns_empty_on_empty_extraction(self):
        with patch("services.flashcard_import_service.extraction_service") as ext, \
             patch("services.flashcard_import_service.call_gemini") as gem:
            ext.extract_text_from_bytes.return_value = ""
            cards = svc.extract_cards_from_image(b"", filename="x.png")
        assert cards == []
        gem.assert_not_called()
```

- [ ] **Step 3: Run to verify fail**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_flashcard_import_service.py::TestExtractFromImage -v
```

Expected: FAIL — `extract_cards_from_image` not defined.

- [ ] **Step 4: Implement**

Append to `backend/services/flashcard_import_service.py` (and add `from services import extraction_service` at the top of the file's imports):

```python
def _parse_card_json(text: str) -> list[Card]:
    """Best-effort parse a Gemini JSON-array response into Card list."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if fence:
        text = fence.group(1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    out: list[Card] = []
    for item in data if isinstance(data, list) else []:
        front = str(item.get("front") or item.get("term") or "").strip()
        back = str(item.get("back") or item.get("definition") or "").strip()
        if front and back:
            out.append({"front": front, "back": back})
    return out


def extract_cards_from_image(file_bytes: bytes, filename: str = "image.png") -> list[Card]:
    """OCR the image via the existing extraction pipeline, then ask Gemini
    to split the markdown into Q/A pairs."""
    markdown = extraction_service.extract_text_from_bytes(file_bytes, filename=filename) or ""
    if not markdown.strip():
        return []
    prompt = _load_prompt("flashcard_ocr_split.txt").replace("{markdown}", markdown)
    raw = call_gemini(prompt, json_mode=True)
    return _parse_card_json(raw)
```

- [ ] **Step 5: Run to verify pass**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_flashcard_import_service.py::TestExtractFromImage -v
```

Expected: 2 PASSED.

- [ ] **Step 6: Commit**

```bash
git add backend/services/flashcard_import_service.py backend/tests/test_flashcard_import_service.py backend/prompts/flashcard_ocr_split.txt
git commit -m "feat(backend): extract_cards_from_image via OCR + Gemini split"
```

---

## Phase 3 — Backend AI generators

### Task 10: AI generation prompts

**Files:**
- Create: `backend/prompts/flashcard_generation.txt`
- Create: `backend/prompts/flashcard_cleanup.txt`
- Create: `backend/prompts/flashcard_cloze.txt`

- [ ] **Step 1: Write `flashcard_generation.txt`**

```
You are creating high-quality flashcards from study material.

DIFFICULTY: {difficulty}
- recall: short, atomic facts (one term -> one definition).
- application: cards that ask the student to apply a concept to a scenario.
- conceptual: cards that probe relationships, "why" and "how", trade-offs.

COUNT: {count}

Return EXACTLY {count} flashcards as a JSON array of
{"front": "...", "back": "..."} objects. Front is the question or term,
back is the answer. Keep each side <= 350 characters. Prefer plain
markdown — no HTML.

Return ONLY the JSON array — no surrounding prose or fences.

SOURCE:
{source}
```

- [ ] **Step 2: Write `flashcard_cleanup.txt`**

```
You are reviewing flashcards a student imported from another source.

For each card:
- Fix obvious typos and spelling errors.
- Normalize formatting (consistent capitalization, no trailing
  whitespace, no leftover HTML tags).
- If a definition exceeds ~350 characters, shorten to its essence
  without losing accuracy.
- Do NOT change the meaning, do NOT add new facts, do NOT remove cards.

Return the cleaned cards as a JSON array of {"front": "...", "back": "..."}
in the same order as the input. Return ONLY the JSON array — no prose
or fences.

CARDS:
{cards_json}
```

- [ ] **Step 3: Write `flashcard_cloze.txt`**

```
Generate fill-in-the-blank (cloze deletion) flashcards from this
paragraph. For each cloze, pick a single key term to remove.

Front side: the sentence with the term replaced by "{{...}}".
Back side: the removed term itself.

Aim for 3–8 cards depending on the paragraph's density. Skip filler
words. Prefer terms that test conceptual understanding.

Return ONLY a JSON array of {"front": "...", "back": "..."} — no prose
or fences.

PARAGRAPH:
{paragraph}
```

- [ ] **Step 4: Commit**

```bash
git add backend/prompts/flashcard_generation.txt backend/prompts/flashcard_cleanup.txt backend/prompts/flashcard_cloze.txt
git commit -m "feat(backend): add prompts for flashcard AI generation, cleanup, cloze"
```

### Task 11: `gemini_generate_cards`

**Files:**
- Modify: `backend/services/flashcard_import_service.py`
- Modify: `backend/tests/test_flashcard_import_service.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_flashcard_import_service.py`:

```python
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
```

- [ ] **Step 2: Run to verify fail**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_flashcard_import_service.py::TestGenerateCards -v
```

Expected: FAIL — `gemini_generate_cards` not defined.

- [ ] **Step 3: Implement**

Append to `backend/services/flashcard_import_service.py`:

```python
def gemini_generate_cards(source_text: str, count: int, difficulty: str) -> list[Card]:
    prompt = (
        _load_prompt("flashcard_generation.txt")
        .replace("{count}", str(count))
        .replace("{difficulty}", difficulty)
        .replace("{source}", source_text)
    )
    raw = call_gemini(prompt, json_mode=True)
    return _parse_card_json(raw)
```

- [ ] **Step 4: Run to verify pass**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_flashcard_import_service.py::TestGenerateCards -v
```

Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add backend/services/flashcard_import_service.py backend/tests/test_flashcard_import_service.py
git commit -m "feat(backend): gemini_generate_cards"
```

### Task 12: `gemini_cleanup_cards`

**Files:**
- Modify: `backend/services/flashcard_import_service.py`
- Modify: `backend/tests/test_flashcard_import_service.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
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
```

- [ ] **Step 2: Run to verify fail**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_flashcard_import_service.py::TestCleanupCards -v
```

Expected: FAIL.

- [ ] **Step 3: Implement**

Append to `backend/services/flashcard_import_service.py`:

```python
def gemini_cleanup_cards(cards: list[Card]) -> list[Card]:
    prompt = _load_prompt("flashcard_cleanup.txt").replace(
        "{cards_json}", json.dumps(cards, ensure_ascii=False)
    )
    raw = call_gemini(prompt, json_mode=True)
    out = _parse_card_json(raw)
    return out if out else cards
```

- [ ] **Step 4: Run to verify pass**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_flashcard_import_service.py::TestCleanupCards -v
```

Expected: 2 PASSED.

- [ ] **Step 5: Commit**

```bash
git add backend/services/flashcard_import_service.py backend/tests/test_flashcard_import_service.py
git commit -m "feat(backend): gemini_cleanup_cards with safe fallback"
```

### Task 13: `gemini_cloze`

**Files:**
- Modify: `backend/services/flashcard_import_service.py`
- Modify: `backend/tests/test_flashcard_import_service.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
class TestCloze:
    def test_generates_cloze_cards(self):
        with patch("services.flashcard_import_service.call_gemini") as gem:
            gem.return_value = json.dumps([
                {"front": "{{...}} is the powerhouse of the cell.", "back": "Mitochondria"},
            ])
            cards = svc.gemini_cloze("Mitochondria is the powerhouse of the cell.")
        assert cards == [{"front": "{{...}} is the powerhouse of the cell.", "back": "Mitochondria"}]
```

- [ ] **Step 2: Run to verify fail**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_flashcard_import_service.py::TestCloze -v
```

- [ ] **Step 3: Implement**

Append to `backend/services/flashcard_import_service.py`:

```python
def gemini_cloze(paragraph: str) -> list[Card]:
    prompt = _load_prompt("flashcard_cloze.txt").replace("{paragraph}", paragraph)
    raw = call_gemini(prompt, json_mode=True)
    return _parse_card_json(raw)
```

- [ ] **Step 4: Run to verify pass**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_flashcard_import_service.py::TestCloze -v
```

Expected: PASSED.

- [ ] **Step 5: Commit**

```bash
git add backend/services/flashcard_import_service.py backend/tests/test_flashcard_import_service.py
git commit -m "feat(backend): gemini_cloze for paragraph -> fill-in-the-blank"
```

---

## Phase 4 — Backend routes

### Task 14: Pydantic models for import routes

**Files:**
- Modify: `backend/routes/flashcards.py`

- [ ] **Step 1: Add models**

After the existing `FlashcardRatingBody` class in `backend/routes/flashcards.py`, append:

```python
from typing import Literal

class CardInput(BaseModel):
    front: str
    back: str


class ImportParseBody(BaseModel):
    user_id: str
    source: Literal["anki", "xlsx", "url", "ocr"]
    payload: str  # base64 for files, plain text for url; filename in options
    options: dict = {}


class ImportCommitBody(BaseModel):
    user_id: str
    course_id: str | None = None
    topic: str
    cards: list[CardInput]
    dedup: bool = True


class ImportGenerateBody(BaseModel):
    user_id: str
    source: Literal["paste", "library_doc"]
    text: str | None = None
    document_id: str | None = None
    count: int = 25
    difficulty: Literal["recall", "application", "conceptual"] = "recall"


class ImportCleanupBody(BaseModel):
    user_id: str
    cards: list[CardInput]


class ImportClozeBody(BaseModel):
    user_id: str
    paragraph: str
```

- [ ] **Step 2: Verify import path still loads**

```bash
cd backend && source venv/bin/activate && python -c "from routes import flashcards"
```

Expected: no error.

- [ ] **Step 3: Commit**

```bash
git add backend/routes/flashcards.py
git commit -m "feat(backend): add Pydantic models for flashcard import routes"
```

### Task 15: `POST /flashcards/import/commit`

**Files:**
- Modify: `backend/routes/flashcards.py`
- Create: `backend/tests/test_flashcard_import_routes.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_flashcard_import_routes.py`:

```python
"""Integration tests for /api/flashcards/import/* routes."""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def _auth_query(uid="u1"):
    return f"?user_id={uid}"


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
        with patch("routes.flashcards.table") as t, \
             patch("routes.flashcards.check_achievements"):
            t.return_value.insert.return_value = []
            r = client.post(f"/api/flashcards/import/commit{_auth_query('u1')}", json=body)

        assert r.status_code == 200
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
        with patch("routes.flashcards.dedup_against_existing") as ddp, \
             patch("routes.flashcards.table"), \
             patch("routes.flashcards.check_achievements"):
            ddp.return_value = ([], body["cards"])
            r = client.post(f"/api/flashcards/import/commit{_auth_query('u1')}", json=body)
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
        # Auth as a different user
        r = client.post(f"/api/flashcards/import/commit{_auth_query('u2')}", json=body)
        assert r.status_code == 403
```

- [ ] **Step 2: Run to verify fail**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_flashcard_import_routes.py::TestImportCommit -v
```

Expected: FAIL — 404 (route doesn't exist).

- [ ] **Step 3: Implement the route**

Append to `backend/routes/flashcards.py` (and add at the top: `from fastapi import Request` and `from services.auth_guard import require_self` and `from services.achievement_service import check_achievements` and `from services.flashcard_import_service import dedup_against_existing`):

```python
@router.post("/import/commit")
def import_commit(body: ImportCommitBody, request: Request):
    require_self(body.user_id, request)

    cards = [{"front": c.front, "back": c.back} for c in body.cards]
    skipped_count = 0

    if body.dedup:
        keep, skipped = dedup_against_existing(
            body.user_id, body.course_id, cards, topic=body.topic
        )
        cards = keep
        skipped_count = len(skipped)

    now = datetime.utcnow().isoformat()
    rows = [
        {
            "id": str(uuid.uuid4()),
            "user_id": body.user_id,
            "topic": body.topic,
            "course_id": body.course_id,
            "front": c["front"],
            "back": c["back"],
            "times_reviewed": 0,
            "last_reviewed_at": None,
            "created_at": now,
        }
        for c in cards
    ]

    if rows:
        try:
            table("flashcards").insert(rows)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Insert failed: {e}")

    try:
        check_achievements(body.user_id, "flashcards_created", {"count": len(rows)})
    except Exception:
        pass

    return {"inserted": len(rows), "skipped_duplicates": skipped_count}
```

- [ ] **Step 4: Run to verify pass**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_flashcard_import_routes.py::TestImportCommit -v
```

Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add backend/routes/flashcards.py backend/tests/test_flashcard_import_routes.py
git commit -m "feat(backend): POST /flashcards/import/commit with dedup"
```

### Task 16: `POST /flashcards/import/parse`

**Files:**
- Modify: `backend/routes/flashcards.py`
- Modify: `backend/tests/test_flashcard_import_routes.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
import base64

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
        with patch("routes.flashcards.parse_xlsx") as p:
            p.return_value = [{"front": "F", "back": "B"}]
            r = client.post(f"/api/flashcards/import/parse{_auth_query('u1')}", json=body)
        assert r.status_code == 200
        assert r.json()["cards"] == [{"front": "F", "back": "B"}]

    def test_parse_anki_route(self):
        body = {"user_id": "u1", "source": "anki", "payload": self._b64(b"fake apkg")}
        with patch("routes.flashcards.parse_anki_apkg") as p:
            p.return_value = [{"front": "F", "back": "B"}]
            r = client.post(f"/api/flashcards/import/parse{_auth_query('u1')}", json=body)
        assert r.status_code == 200
        assert r.json()["cards"][0]["front"] == "F"

    def test_parse_url_route(self):
        body = {"user_id": "u1", "source": "url", "payload": "https://quizlet.com/x"}
        with patch("routes.flashcards.scrape_quizlet_url") as p:
            p.return_value = [{"front": "F", "back": "B"}]
            r = client.post(f"/api/flashcards/import/parse{_auth_query('u1')}", json=body)
        assert r.status_code == 200
        assert r.json()["cards"][0]["front"] == "F"

    def test_url_blocked_returns_422(self):
        from services.flashcard_import_service import QuizletBlocked
        body = {"user_id": "u1", "source": "url", "payload": "https://quizlet.com/x"}
        with patch("routes.flashcards.scrape_quizlet_url", side_effect=QuizletBlocked("blocked")):
            r = client.post(f"/api/flashcards/import/parse{_auth_query('u1')}", json=body)
        assert r.status_code == 422
        assert "blocked" in r.json()["detail"].lower()

    def test_parse_ocr_route(self):
        body = {
            "user_id": "u1",
            "source": "ocr",
            "payload": self._b64(b"png bytes"),
            "options": {"filename": "notes.png"},
        }
        with patch("routes.flashcards.extract_cards_from_image") as p:
            p.return_value = [{"front": "F", "back": "B"}]
            r = client.post(f"/api/flashcards/import/parse{_auth_query('u1')}", json=body)
        assert r.status_code == 200
        assert r.json()["cards"][0]["front"] == "F"

    def test_payload_too_large_returns_413(self):
        big = self._b64(b"x" * (5 * 1024 * 1024 + 1))
        body = {"user_id": "u1", "source": "xlsx", "payload": big}
        r = client.post(f"/api/flashcards/import/parse{_auth_query('u1')}", json=body)
        assert r.status_code == 413
```

- [ ] **Step 2: Run to verify fail**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_flashcard_import_routes.py::TestImportParse -v
```

Expected: FAIL — 404.

- [ ] **Step 3: Implement**

Append to `backend/routes/flashcards.py` (and add to imports: `import base64` and `from services.flashcard_import_service import (parse_xlsx, parse_anki_apkg, scrape_quizlet_url, extract_cards_from_image, QuizletBlocked)`):

```python
_MAX_UPLOAD_BYTES = 5 * 1024 * 1024


@router.post("/import/parse")
def import_parse(body: ImportParseBody, request: Request):
    require_self(body.user_id, request)

    if body.source in ("anki", "xlsx", "ocr"):
        try:
            file_bytes = base64.b64decode(body.payload, validate=True)
        except Exception:
            raise HTTPException(status_code=400, detail="payload must be valid base64")
        if len(file_bytes) > _MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="File exceeds 5MB limit")

        try:
            if body.source == "xlsx":
                cards = parse_xlsx(file_bytes)
            elif body.source == "anki":
                cards = parse_anki_apkg(file_bytes)
            else:  # ocr
                filename = (body.options or {}).get("filename", "image.png")
                cards = extract_cards_from_image(file_bytes, filename=filename)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Parser error: {e}")
        return {"cards": cards, "errors": []}

    if body.source == "url":
        try:
            cards = scrape_quizlet_url(body.payload)
        except QuizletBlocked as e:
            raise HTTPException(status_code=422, detail=str(e))
        return {"cards": cards, "errors": []}

    raise HTTPException(status_code=400, detail=f"Unsupported source: {body.source}")
```

- [ ] **Step 4: Run to verify pass**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_flashcard_import_routes.py::TestImportParse -v
```

Expected: 6 PASSED.

- [ ] **Step 5: Commit**

```bash
git add backend/routes/flashcards.py backend/tests/test_flashcard_import_routes.py
git commit -m "feat(backend): POST /flashcards/import/parse for xlsx/anki/url/ocr"
```

### Task 17: `POST /flashcards/import/generate`

**Files:**
- Modify: `backend/routes/flashcards.py`
- Modify: `backend/tests/test_flashcard_import_routes.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
class TestImportGenerate:
    def test_generate_from_paste_text(self):
        body = {
            "user_id": "u1",
            "source": "paste",
            "text": "Long lecture notes about mitosis...",
            "count": 10,
            "difficulty": "recall",
        }
        with patch("routes.flashcards.gemini_generate_cards") as gen, \
             patch("routes.flashcards.check_rate_limit", return_value=None):
            gen.return_value = [{"front": "F", "back": "B"}]
            r = client.post(f"/api/flashcards/import/generate{_auth_query('u1')}", json=body)
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
        with patch("routes.flashcards.table") as t, \
             patch("routes.flashcards.gemini_generate_cards") as gen, \
             patch("routes.flashcards.check_rate_limit", return_value=None):
            t.return_value.select.return_value = [{
                "id": "doc1", "user_id": "u1", "summary": "doc summary text", "concept_notes": {}
            }]
            gen.return_value = [{"front": "F", "back": "B"}]
            r = client.post(f"/api/flashcards/import/generate{_auth_query('u1')}", json=body)
        assert r.status_code == 200
        assert "doc summary text" in gen.call_args.args[0]

    def test_rate_limit_returns_429(self):
        body = {"user_id": "u1", "source": "paste", "text": "x", "count": 5, "difficulty": "recall"}
        with patch("routes.flashcards.check_rate_limit", return_value=42):
            r = client.post(f"/api/flashcards/import/generate{_auth_query('u1')}", json=body)
        assert r.status_code == 429
        assert r.headers.get("Retry-After") == "42"

    def test_paste_without_text_returns_400(self):
        body = {"user_id": "u1", "source": "paste", "count": 5, "difficulty": "recall"}
        with patch("routes.flashcards.check_rate_limit", return_value=None):
            r = client.post(f"/api/flashcards/import/generate{_auth_query('u1')}", json=body)
        assert r.status_code == 400

    def test_library_doc_belonging_to_other_user_returns_404(self):
        body = {"user_id": "u1", "source": "library_doc", "document_id": "doc1", "count": 5, "difficulty": "recall"}
        with patch("routes.flashcards.table") as t, \
             patch("routes.flashcards.check_rate_limit", return_value=None):
            t.return_value.select.return_value = []
            r = client.post(f"/api/flashcards/import/generate{_auth_query('u1')}", json=body)
        assert r.status_code == 404
```

- [ ] **Step 2: Run to verify fail**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_flashcard_import_routes.py::TestImportGenerate -v
```

Expected: FAIL.

- [ ] **Step 3: Implement**

Append to `backend/routes/flashcards.py` (and to imports: `from fastapi.responses import JSONResponse` and `from services.flashcard_import_service import gemini_generate_cards, check_rate_limit`):

```python
@router.post("/import/generate")
def import_generate(body: ImportGenerateBody, request: Request):
    require_self(body.user_id, request)

    retry = check_rate_limit(body.user_id)
    if retry is not None:
        return JSONResponse(
            status_code=429,
            content={"detail": f"Rate limit hit. Try again in {retry}s."},
            headers={"Retry-After": str(retry)},
        )

    if body.source == "paste":
        if not body.text:
            raise HTTPException(status_code=400, detail="`text` is required for paste source")
        source_text = body.text
    else:  # library_doc
        if not body.document_id:
            raise HTTPException(status_code=400, detail="`document_id` is required for library_doc source")
        rows = table("documents").select(
            "id,user_id,summary,concept_notes,file_name",
            filters={"id": f"eq.{body.document_id}", "user_id": f"eq.{body.user_id}"},
            limit=1,
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Document not found")
        doc = rows[0]
        parts = [doc.get("summary") or "", str(doc.get("concept_notes") or {})]
        source_text = "\n\n".join(p for p in parts if p)

    try:
        cards = gemini_generate_cards(source_text, count=body.count, difficulty=body.difficulty)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini error: {e}")

    return {"cards": cards}
```

- [ ] **Step 4: Run to verify pass**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_flashcard_import_routes.py::TestImportGenerate -v
```

Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add backend/routes/flashcards.py backend/tests/test_flashcard_import_routes.py
git commit -m "feat(backend): POST /flashcards/import/generate (paste or library doc)"
```

### Task 18: `POST /flashcards/import/cleanup` and `/cloze`

**Files:**
- Modify: `backend/routes/flashcards.py`
- Modify: `backend/tests/test_flashcard_import_routes.py`

- [ ] **Step 1: Write the failing tests**

Append:

```python
class TestImportCleanup:
    def test_cleanup_returns_rewritten(self):
        body = {"user_id": "u1", "cards": [{"front": "miotsis", "back": "cell div"}]}
        with patch("routes.flashcards.gemini_cleanup_cards") as cln, \
             patch("routes.flashcards.check_rate_limit", return_value=None):
            cln.return_value = [{"front": "Mitosis", "back": "Cell division"}]
            r = client.post(f"/api/flashcards/import/cleanup{_auth_query('u1')}", json=body)
        assert r.status_code == 200
        assert r.json()["cards"][0]["front"] == "Mitosis"

    def test_cleanup_rate_limited(self):
        body = {"user_id": "u1", "cards": [{"front": "F", "back": "B"}]}
        with patch("routes.flashcards.check_rate_limit", return_value=10):
            r = client.post(f"/api/flashcards/import/cleanup{_auth_query('u1')}", json=body)
        assert r.status_code == 429


class TestImportCloze:
    def test_cloze_returns_cards(self):
        body = {"user_id": "u1", "paragraph": "Mitochondria is the powerhouse of the cell."}
        with patch("routes.flashcards.gemini_cloze") as cz, \
             patch("routes.flashcards.check_rate_limit", return_value=None):
            cz.return_value = [{"front": "{{...}} is the powerhouse...", "back": "Mitochondria"}]
            r = client.post(f"/api/flashcards/import/cloze{_auth_query('u1')}", json=body)
        assert r.status_code == 200
        assert r.json()["cards"][0]["back"] == "Mitochondria"
```

- [ ] **Step 2: Run to verify fail**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_flashcard_import_routes.py::TestImportCleanup tests/test_flashcard_import_routes.py::TestImportCloze -v
```

Expected: FAIL.

- [ ] **Step 3: Implement**

Append to `backend/routes/flashcards.py` (and to imports: `from services.flashcard_import_service import gemini_cleanup_cards, gemini_cloze`):

```python
@router.post("/import/cleanup")
def import_cleanup(body: ImportCleanupBody, request: Request):
    require_self(body.user_id, request)

    retry = check_rate_limit(body.user_id)
    if retry is not None:
        return JSONResponse(
            status_code=429,
            content={"detail": f"Rate limit hit. Try again in {retry}s."},
            headers={"Retry-After": str(retry)},
        )

    cards = [{"front": c.front, "back": c.back} for c in body.cards]
    try:
        out = gemini_cleanup_cards(cards)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini error: {e}")
    return {"cards": out}


@router.post("/import/cloze")
def import_cloze(body: ImportClozeBody, request: Request):
    require_self(body.user_id, request)

    retry = check_rate_limit(body.user_id)
    if retry is not None:
        return JSONResponse(
            status_code=429,
            content={"detail": f"Rate limit hit. Try again in {retry}s."},
            headers={"Retry-After": str(retry)},
        )

    try:
        cards = gemini_cloze(body.paragraph)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini error: {e}")
    return {"cards": cards}
```

- [ ] **Step 4: Run to verify pass**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/test_flashcard_import_routes.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/routes/flashcards.py backend/tests/test_flashcard_import_routes.py
git commit -m "feat(backend): POST /flashcards/import/cleanup and /import/cloze"
```

---

## Phase 5 — Frontend dependencies and API helpers

### Task 19: Add Papaparse

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: Install**

```bash
cd frontend && npm install papaparse @types/papaparse
```

Expected: installs without warnings beyond the usual peer-dep noise.

- [ ] **Step 2: Verify type-check still clean**

```bash
cd frontend && npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "chore(frontend): add papaparse for client-side CSV parsing"
```

### Task 20: API helpers

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Append helpers**

Append after the existing flashcard helpers (around line 417 of `frontend/src/lib/api.ts`):

```typescript
// Flashcard import
export interface ImportCard { front: string; back: string }
export interface ImportParseResponse { cards: ImportCard[]; errors: { row: number; message: string }[] }
export interface ImportCommitResponse { inserted: number; skipped_duplicates: number }
export interface ImportGenerateResponse { cards: ImportCard[] }

export const importParse = (
  userId: string,
  source: "anki" | "xlsx" | "url" | "ocr",
  payload: string,
  options: Record<string, unknown> = {},
) =>
  fetchJSON<ImportParseResponse>(`/api/flashcards/import/parse?user_id=${encodeURIComponent(userId)}`, {
    method: "POST",
    body: JSON.stringify({ user_id: userId, source, payload, options }),
  });

export const importCommit = (
  userId: string,
  courseId: string | null,
  topic: string,
  cards: ImportCard[],
  dedup = true,
) =>
  fetchJSON<ImportCommitResponse>(`/api/flashcards/import/commit?user_id=${encodeURIComponent(userId)}`, {
    method: "POST",
    body: JSON.stringify({ user_id: userId, course_id: courseId, topic, cards, dedup }),
  });

export const importGenerate = (
  userId: string,
  args:
    | { source: "paste"; text: string; count: number; difficulty: "recall" | "application" | "conceptual" }
    | { source: "library_doc"; documentId: string; count: number; difficulty: "recall" | "application" | "conceptual" },
) =>
  fetchJSON<ImportGenerateResponse>(`/api/flashcards/import/generate?user_id=${encodeURIComponent(userId)}`, {
    method: "POST",
    body: JSON.stringify({
      user_id: userId,
      source: args.source,
      text: args.source === "paste" ? args.text : undefined,
      document_id: args.source === "library_doc" ? args.documentId : undefined,
      count: args.count,
      difficulty: args.difficulty,
    }),
  });

export const importCleanup = (userId: string, cards: ImportCard[]) =>
  fetchJSON<{ cards: ImportCard[] }>(`/api/flashcards/import/cleanup?user_id=${encodeURIComponent(userId)}`, {
    method: "POST",
    body: JSON.stringify({ user_id: userId, cards }),
  });

export const importCloze = (userId: string, paragraph: string) =>
  fetchJSON<{ cards: ImportCard[] }>(`/api/flashcards/import/cloze?user_id=${encodeURIComponent(userId)}`, {
    method: "POST",
    body: JSON.stringify({ user_id: userId, paragraph }),
  });
```

- [ ] **Step 2: Verify type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(frontend): API helpers for flashcard import"
```

---

## Phase 6 — Frontend parser library

### Task 21: `lib/flashcardParsers.ts`

**Files:**
- Create: `frontend/src/lib/flashcardParsers.ts`

> CLAUDE.md says no frontend test framework on this branch, so verification is type-check + manual smoke. Implement directly.

- [ ] **Step 1: Write the module**

Create `frontend/src/lib/flashcardParsers.ts`:

```typescript
import Papa from "papaparse";

export interface ParsedCard {
  front: string;
  back: string;
  row: number;
  error?: string;
}

export type Delim = "\t" | "," | "\n" | ";" | string;

export interface DelimChoice {
  term: Delim;
  card: Delim;
}

const TERM_CANDIDATES: Delim[] = ["\t", ",", " - "];
const CARD_CANDIDATES: Delim[] = ["\n\n", "\n", ";"];

/** Sniff the most likely term/card separators. Picks the combo that yields
 *  the highest fraction of rows with exactly two non-empty fields. */
export function detectDelimiters(text: string): DelimChoice {
  const sample = text.trim();
  if (!sample) return { term: "\t", card: "\n" };

  let best: DelimChoice = { term: "\t", card: "\n" };
  let bestScore = -1;

  for (const card of CARD_CANDIDATES) {
    const lines = sample.split(card).map(l => l.trim()).filter(Boolean);
    if (lines.length < 2) continue;
    for (const term of TERM_CANDIDATES) {
      const valid = lines.filter(l => {
        const parts = l.split(term);
        return parts.length >= 2 && parts[0].trim() && parts.slice(1).join(term).trim();
      }).length;
      const score = valid / lines.length;
      if (score > bestScore) {
        bestScore = score;
        best = { term, card };
      }
    }
  }
  return bestScore >= 0.8 ? best : { term: "\t", card: "\n" };
}

export function splitByDelimiters(text: string, term: Delim, card: Delim): ParsedCard[] {
  const out: ParsedCard[] = [];
  const lines = text.split(card).map(l => l.replace(/\r$/, ""));
  let row = 0;
  for (const line of lines) {
    if (!line.trim()) continue;
    row += 1;
    const idx = line.indexOf(term);
    if (idx === -1) {
      out.push({ front: line.trim(), back: "", row, error: "Missing definition" });
      continue;
    }
    const front = line.slice(0, idx).trim();
    const back = line.slice(idx + term.length).trim();
    if (!front || !back) {
      out.push({ front, back, row, error: "Front or back is empty" });
    } else {
      out.push({ front, back, row });
    }
  }
  return out;
}

export function parseCSV(text: string): ParsedCard[] {
  const result = Papa.parse<string[]>(text, { skipEmptyLines: true });
  return result.data.map((row, i) => {
    const front = (row[0] ?? "").trim();
    const back = (row[1] ?? "").trim();
    const error = front && back ? undefined : "CSV row needs at least 2 columns";
    return { front, back, row: i + 1, error };
  });
}

export function parseTSV(text: string): ParsedCard[] {
  const result = Papa.parse<string[]>(text, { delimiter: "\t", skipEmptyLines: true });
  return result.data.map((row, i) => {
    const front = (row[0] ?? "").trim();
    const back = (row[1] ?? "").trim();
    const error = front && back ? undefined : "TSV row needs at least 2 columns";
    return { front, back, row: i + 1, error };
  });
}

export function parseJSON(text: string): ParsedCard[] {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return [{ front: "", back: "", row: 1, error: "Invalid JSON" }];
  }
  if (!Array.isArray(data)) {
    return [{ front: "", back: "", row: 1, error: "Expected a JSON array" }];
  }
  return data.map((item, i) => {
    const obj = (item ?? {}) as Record<string, unknown>;
    const front = String(obj.front ?? obj.term ?? "").trim();
    const back = String(obj.back ?? obj.definition ?? "").trim();
    const error = front && back ? undefined : "Each item needs front+back or term+definition";
    return { front, back, row: i + 1, error };
  });
}

export function isValid(card: ParsedCard): boolean {
  return !card.error && !!card.front && !!card.back;
}
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 3: Manual smoke check (optional, fast)**

Open a Node REPL or quick script:

```bash
cd frontend && node -e "
const { detectDelimiters, splitByDelimiters } = require('./src/lib/flashcardParsers.ts');
" 2>&1 || echo "Skipping — Node can't run TS directly. Will smoke via the UI later."
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/flashcardParsers.ts
git commit -m "feat(frontend): pure flashcard parsers with smart delimiter detection"
```

---

## Phase 7 — Frontend UI

### Task 22: `ParsedCardsTable.tsx`

**Files:**
- Create: `frontend/src/components/flashcards/ParsedCardsTable.tsx`

- [ ] **Step 1: Write the component**

Create `frontend/src/components/flashcards/ParsedCardsTable.tsx`:

```tsx
"use client";
import React from "react";
import { Icon } from "../Icon";
import { useToast } from "../ToastProvider";
import { useUser } from "@/context/UserContext";
import { importCleanup, type ImportCard } from "@/lib/api";
import type { ParsedCard } from "@/lib/flashcardParsers";

interface Props {
  cards: ParsedCard[];
  onChange: (next: ParsedCard[]) => void;
  reverseEnabled: boolean;
  onReverseToggle: (next: boolean) => void;
}

export function ParsedCardsTable({ cards, onChange, reverseEnabled, onReverseToggle }: Props) {
  const toast = useToast();
  const { userId } = useUser();
  const [cleaning, setCleaning] = React.useState(false);

  const validCount = cards.filter(c => !c.error && c.front && c.back).length;

  const updateRow = (idx: number, patch: Partial<ParsedCard>) => {
    const next = [...cards];
    const merged = { ...next[idx], ...patch };
    if (merged.front && merged.back) merged.error = undefined;
    next[idx] = merged;
    onChange(next);
  };

  const removeRow = (idx: number) => onChange(cards.filter((_, i) => i !== idx));

  const cleanup = async () => {
    if (!userId) return;
    const valid: ImportCard[] = cards.filter(c => c.front && c.back).map(c => ({ front: c.front, back: c.back }));
    if (valid.length === 0) { toast.warn("No valid cards to clean up."); return; }
    setCleaning(true);
    try {
      const res = await importCleanup(userId, valid);
      onChange(res.cards.map((c, i) => ({ front: c.front, back: c.back, row: i + 1 })));
      toast.success("Cleaned up.");
    } catch (err) {
      toast.error(`Cleanup failed: ${String(err)}`);
    } finally {
      setCleaning(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <span className="label-micro">{validCount} valid · {cards.length - validCount} flagged</span>
        <label style={{ fontSize: 12, display: "flex", alignItems: "center", gap: 6 }}>
          <input type="checkbox" checked={reverseEnabled} onChange={e => onReverseToggle(e.target.checked)} />
          Generate reverse cards
        </label>
        <button className="btn btn--sm" onClick={cleanup} disabled={cleaning || cards.length === 0}>
          <Icon name="sparkle" size={11} /> {cleaning ? "Cleaning…" : "Clean up with AI"}
        </button>
      </div>

      <div style={{
        maxHeight: 360, overflowY: "auto", border: "1px solid var(--border)",
        borderRadius: "var(--r-md)", background: "var(--bg-panel)",
      }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead style={{ position: "sticky", top: 0, background: "var(--bg-subtle)" }}>
            <tr>
              <th style={{ padding: "6px 8px", textAlign: "left", width: 36 }}>#</th>
              <th style={{ padding: "6px 8px", textAlign: "left" }}>Term</th>
              <th style={{ padding: "6px 8px", textAlign: "left" }}>Definition</th>
              <th style={{ width: 32 }} />
            </tr>
          </thead>
          <tbody>
            {cards.map((c, i) => (
              <tr key={i} style={{
                borderTop: "1px solid var(--border)",
                borderLeft: c.error ? "3px solid var(--err)" : "3px solid transparent",
              }} title={c.error}>
                <td style={{ padding: "4px 8px", color: "var(--text-muted)" }}>{c.row}</td>
                <td style={{ padding: "4px 8px" }}>
                  <input
                    value={c.front}
                    onChange={e => updateRow(i, { front: e.target.value })}
                    style={{ width: "100%", background: "transparent", border: "none", outline: "none", color: "var(--text)" }}
                  />
                </td>
                <td style={{ padding: "4px 8px" }}>
                  <input
                    value={c.back}
                    onChange={e => updateRow(i, { back: e.target.value })}
                    style={{ width: "100%", background: "transparent", border: "none", outline: "none", color: "var(--text)" }}
                  />
                </td>
                <td>
                  <button onClick={() => removeRow(i)} className="btn btn--sm btn--ghost" style={{ color: "var(--err)" }} title="Delete row">
                    <Icon name="x" size={11} />
                  </button>
                </td>
              </tr>
            ))}
            {cards.length === 0 && (
              <tr><td colSpan={4} style={{ padding: 16, textAlign: "center", color: "var(--text-muted)" }}>
                No cards parsed yet.
              </td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/flashcards/ParsedCardsTable.tsx
git commit -m "feat(frontend): ParsedCardsTable with inline edit and AI cleanup"
```

### Task 23: `tabs/PasteTab.tsx`

**Files:**
- Create: `frontend/src/components/flashcards/tabs/PasteTab.tsx`

- [ ] **Step 1: Write the component**

```tsx
"use client";
import React from "react";
import { CustomSelect } from "../../CustomSelect";
import { useToast } from "../../ToastProvider";
import { useUser } from "@/context/UserContext";
import { importCloze } from "@/lib/api";
import { detectDelimiters, splitByDelimiters, type ParsedCard } from "@/lib/flashcardParsers";

interface Props {
  cards: ParsedCard[];
  onCards: (next: ParsedCard[]) => void;
}

const TERM_OPTIONS = [
  { value: "\t", label: "Tab" },
  { value: ",", label: "Comma" },
  { value: " - ", label: "Hyphen" },
  { value: "custom", label: "Custom…" },
];

const CARD_OPTIONS = [
  { value: "\n", label: "New line" },
  { value: "\n\n", label: "Blank line" },
  { value: ";", label: "Semicolon" },
  { value: "custom", label: "Custom…" },
];

export function PasteTab({ cards, onCards }: Props) {
  const toast = useToast();
  const { userId } = useUser();
  const [text, setText] = React.useState("");
  const [termSel, setTermSel] = React.useState<string>("\t");
  const [cardSel, setCardSel] = React.useState<string>("\n");
  const [termCustom, setTermCustom] = React.useState("");
  const [cardCustom, setCardCustom] = React.useState("");
  const [autoDetectedOnce, setAutoDetectedOnce] = React.useState(false);
  const [clozeMode, setClozeMode] = React.useState(false);
  const [clozing, setClozing] = React.useState(false);

  const term = termSel === "custom" ? termCustom : termSel;
  const card = cardSel === "custom" ? cardCustom : cardSel;

  // Smart auto-detect on first paste
  React.useEffect(() => {
    if (!text || autoDetectedOnce) return;
    if (text.length < 20) return;
    const detected = detectDelimiters(text);
    setTermSel(detected.term);
    setCardSel(detected.card);
    setAutoDetectedOnce(true);
  }, [text, autoDetectedOnce]);

  // Live re-parse
  React.useEffect(() => {
    if (clozeMode) return;
    if (!text || !term || !card) { onCards([]); return; }
    const parsed = splitByDelimiters(text, term, card);
    onCards(parsed);
  }, [text, term, card, clozeMode, onCards]);

  const runCloze = async () => {
    if (!userId || !text.trim()) return;
    setClozing(true);
    try {
      const res = await importCloze(userId, text);
      onCards(res.cards.map((c, i) => ({ front: c.front, back: c.back, row: i + 1 })));
      toast.success(`Generated ${res.cards.length} cloze cards.`);
    } catch (err) {
      toast.error(`Cloze failed: ${String(err)}`);
    } finally {
      setClozing(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", gap: 8, fontSize: 12 }}>
        <button
          className="btn btn--sm"
          onClick={() => setClozeMode(false)}
          style={{ opacity: clozeMode ? 0.5 : 1, fontWeight: clozeMode ? 400 : 600 }}
        >Term / Definition</button>
        <button
          className="btn btn--sm"
          onClick={() => setClozeMode(true)}
          style={{ opacity: clozeMode ? 1 : 0.5, fontWeight: clozeMode ? 600 : 400 }}
        >Cloze deletion (AI)</button>
      </div>

      <textarea
        value={text}
        onChange={e => setText(e.target.value)}
        placeholder={clozeMode
          ? "Paste a paragraph. Claude will pick key terms to remove and generate fill-in-the-blank cards."
          : "Paste your cards here. Use Tab between term and definition, Enter between cards."}
        style={{
          minHeight: 180, padding: 12, borderRadius: "var(--r-md)",
          background: "var(--bg-panel)", border: "1px solid var(--border)",
          color: "var(--text)", fontFamily: "inherit", fontSize: 13, resize: "vertical",
        }}
      />

      {!clozeMode && (
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <div style={{ minWidth: 180 }}>
            <div className="label-micro">Between term and definition</div>
            <CustomSelect value={termSel} onChange={setTermSel} options={TERM_OPTIONS} />
            {termSel === "custom" && (
              <input
                value={termCustom}
                onChange={e => setTermCustom(e.target.value)}
                placeholder="Custom separator"
                style={{ marginTop: 4, padding: 6, fontSize: 12, width: "100%" }}
              />
            )}
          </div>
          <div style={{ minWidth: 180 }}>
            <div className="label-micro">Between cards</div>
            <CustomSelect value={cardSel} onChange={setCardSel} options={CARD_OPTIONS} />
            {cardSel === "custom" && (
              <input
                value={cardCustom}
                onChange={e => setCardCustom(e.target.value)}
                placeholder="Custom separator"
                style={{ marginTop: 4, padding: 6, fontSize: 12, width: "100%" }}
              />
            )}
          </div>
        </div>
      )}

      {clozeMode && (
        <button className="btn btn--sm btn--primary" onClick={runCloze} disabled={clozing || !text.trim()}>
          {clozing ? "Generating cloze cards…" : "Generate cloze cards"}
        </button>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/flashcards/tabs/PasteTab.tsx
git commit -m "feat(frontend): PasteTab with delimiter auto-detect and cloze mode"
```

### Task 24: `tabs/UploadTab.tsx`

**Files:**
- Create: `frontend/src/components/flashcards/tabs/UploadTab.tsx`

- [ ] **Step 1: Write the component**

```tsx
"use client";
import React from "react";
import { Icon } from "../../Icon";
import { useToast } from "../../ToastProvider";
import { useUser } from "@/context/UserContext";
import { importParse } from "@/lib/api";
import { parseCSV, parseTSV, parseJSON, type ParsedCard } from "@/lib/flashcardParsers";

interface Props { onCards: (cards: ParsedCard[]) => void }

const MAX_BYTES = 5 * 1024 * 1024;

async function readAsText(file: File): Promise<string> {
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(String(r.result ?? ""));
    r.onerror = () => rej(r.error);
    r.readAsText(file);
  });
}

async function readAsBase64(file: File): Promise<string> {
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => {
      const dataUrl = String(r.result ?? "");
      res(dataUrl.split(",", 2)[1] ?? "");
    };
    r.onerror = () => rej(r.error);
    r.readAsDataURL(file);
  });
}

export function UploadTab({ onCards }: Props) {
  const toast = useToast();
  const { userId } = useUser();
  const [busy, setBusy] = React.useState(false);
  const inputRef = React.useRef<HTMLInputElement>(null);

  const handleFile = async (file: File) => {
    if (!userId) return;
    if (file.size > MAX_BYTES) { toast.error("File exceeds 5MB. Try splitting it."); return; }
    setBusy(true);
    try {
      const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
      if (ext === "csv") onCards(parseCSV(await readAsText(file)));
      else if (ext === "tsv") onCards(parseTSV(await readAsText(file)));
      else if (ext === "txt") onCards(parseTSV(await readAsText(file))); // tab/newline default
      else if (ext === "json") onCards(parseJSON(await readAsText(file)));
      else if (ext === "xlsx") {
        const res = await importParse(userId, "xlsx", await readAsBase64(file));
        onCards(res.cards.map((c, i) => ({ front: c.front, back: c.back, row: i + 1 })));
      } else if (ext === "apkg") {
        const res = await importParse(userId, "anki", await readAsBase64(file));
        onCards(res.cards.map((c, i) => ({ front: c.front, back: c.back, row: i + 1 })));
      } else {
        toast.error(`Unsupported file type: .${ext}`);
      }
    } catch (err) {
      toast.error(`Couldn't parse: ${String(err)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      onDragOver={e => { e.preventDefault(); }}
      onDrop={e => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) handleFile(f); }}
      style={{
        border: "2px dashed var(--border)", borderRadius: "var(--r-md)",
        padding: 32, textAlign: "center", color: "var(--text-muted)",
        cursor: "pointer",
      }}
      onClick={() => inputRef.current?.click()}
    >
      <Icon name="upload" size={20} />
      <div style={{ marginTop: 8, fontSize: 13 }}>
        {busy ? "Parsing…" : "Drop or click to upload .csv, .tsv, .txt, .json, .xlsx, .apkg"}
      </div>
      <div style={{ fontSize: 11, marginTop: 4 }}>Max 5MB</div>
      <input
        ref={inputRef}
        type="file"
        accept=".csv,.tsv,.txt,.json,.xlsx,.apkg"
        style={{ display: "none" }}
        onChange={e => { const f = e.target.files?.[0]; if (f) handleFile(f); e.target.value = ""; }}
      />
    </div>
  );
}
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/flashcards/tabs/UploadTab.tsx
git commit -m "feat(frontend): UploadTab routes by extension to client/server parser"
```

### Task 25: `tabs/UrlTab.tsx`

**Files:**
- Create: `frontend/src/components/flashcards/tabs/UrlTab.tsx`

- [ ] **Step 1: Write the component**

```tsx
"use client";
import React from "react";
import { useToast } from "../../ToastProvider";
import { useUser } from "@/context/UserContext";
import { importParse } from "@/lib/api";
import type { ParsedCard } from "@/lib/flashcardParsers";

interface Props { onCards: (cards: ParsedCard[]) => void }

export function UrlTab({ onCards }: Props) {
  const toast = useToast();
  const { userId } = useUser();
  const [url, setUrl] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [blocked, setBlocked] = React.useState<string | null>(null);

  const fetchUrl = async () => {
    if (!userId || !url.trim()) return;
    setBusy(true);
    setBlocked(null);
    try {
      const res = await importParse(userId, "url", url.trim());
      onCards(res.cards.map((c, i) => ({ front: c.front, back: c.back, row: i + 1 })));
      toast.success(`Found ${res.cards.length} cards.`);
    } catch (err) {
      const msg = String(err);
      if (msg.toLowerCase().includes("blocked") || msg.includes("422")) {
        setBlocked(msg);
      } else {
        toast.error(`Fetch failed: ${msg}`);
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ fontSize: 13, color: "var(--text-dim)" }}>
        Paste a public Quizlet set URL.
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <input
          value={url}
          onChange={e => setUrl(e.target.value)}
          placeholder="https://quizlet.com/12345/some-set"
          style={{ flex: 1, padding: 10, borderRadius: "var(--r-md)", background: "var(--bg-panel)", border: "1px solid var(--border)", color: "var(--text)" }}
        />
        <button className="btn btn--sm btn--primary" onClick={fetchUrl} disabled={busy || !url.trim()}>
          {busy ? "Fetching…" : "Fetch cards"}
        </button>
      </div>
      {blocked && (
        <div className="card" style={{ padding: 14, fontSize: 13, color: "var(--text-dim)" }}>
          <div style={{ fontWeight: 600, color: "var(--text)", marginBottom: 6 }}>
            Couldn't fetch this URL
          </div>
          Quizlet may be blocking automated requests. Try the <strong>Paste</strong> tab
          instead — open the set in your browser, click <em>Export</em> in the
          three-dot menu, then paste the export text.
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/flashcards/tabs/UrlTab.tsx
git commit -m "feat(frontend): UrlTab with graceful blocked-fallback hint"
```

### Task 26: `tabs/AiTab.tsx`

**Files:**
- Create: `frontend/src/components/flashcards/tabs/AiTab.tsx`

- [ ] **Step 1: Write the component**

```tsx
"use client";
import React from "react";
import { CustomSelect } from "../../CustomSelect";
import { useToast } from "../../ToastProvider";
import { useUser } from "@/context/UserContext";
import { importGenerate } from "@/lib/api";
import type { ParsedCard } from "@/lib/flashcardParsers";

interface LibraryDoc { id: string; file_name: string; category?: string }

interface Props {
  documents: LibraryDoc[];
  onCards: (cards: ParsedCard[]) => void;
}

const COUNT_OPTIONS = [
  { value: "10", label: "10 cards" },
  { value: "25", label: "25 cards" },
  { value: "50", label: "50 cards" },
  { value: "auto", label: "Auto" },
];

const DIFFICULTY_OPTIONS = [
  { value: "recall", label: "Recall" },
  { value: "application", label: "Application" },
  { value: "conceptual", label: "Conceptual" },
];

export function AiTab({ documents, onCards }: Props) {
  const toast = useToast();
  const { userId } = useUser();
  const [mode, setMode] = React.useState<"paste" | "library_doc">("paste");
  const [text, setText] = React.useState("");
  const [docId, setDocId] = React.useState("");
  const [count, setCount] = React.useState<string>("25");
  const [difficulty, setDifficulty] = React.useState<"recall" | "application" | "conceptual">("recall");
  const [busy, setBusy] = React.useState(false);

  const numericCount = count === "auto" ? 25 : parseInt(count, 10);

  const generate = async () => {
    if (!userId) return;
    setBusy(true);
    try {
      const res = mode === "paste"
        ? await importGenerate(userId, { source: "paste", text, count: numericCount, difficulty })
        : await importGenerate(userId, { source: "library_doc", documentId: docId, count: numericCount, difficulty });
      onCards(res.cards.map((c, i) => ({ front: c.front, back: c.back, row: i + 1 })));
      toast.success(`Generated ${res.cards.length} cards.`);
    } catch (err) {
      toast.error(`Generate failed: ${String(err)}`);
    } finally {
      setBusy(false);
    }
  };

  const canGo = mode === "paste" ? text.trim().length > 0 : !!docId;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", gap: 8 }}>
        <button className="btn btn--sm" style={{ fontWeight: mode === "paste" ? 600 : 400 }} onClick={() => setMode("paste")}>Paste notes</button>
        <button className="btn btn--sm" style={{ fontWeight: mode === "library_doc" ? 600 : 400 }} onClick={() => setMode("library_doc")}>From library</button>
      </div>

      {mode === "paste" ? (
        <textarea
          value={text}
          onChange={e => setText(e.target.value)}
          placeholder="Paste lecture notes, a study guide, or a course topic."
          style={{ minHeight: 160, padding: 12, borderRadius: "var(--r-md)", background: "var(--bg-panel)", border: "1px solid var(--border)", color: "var(--text)", resize: "vertical" }}
        />
      ) : (
        <CustomSelect
          value={docId}
          onChange={setDocId}
          placeholder={documents.length ? "Pick a document…" : "No library documents yet"}
          options={documents.map(d => ({ value: d.id, label: d.file_name, description: d.category }))}
        />
      )}

      <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
        <div style={{ minWidth: 140 }}>
          <div className="label-micro">Count</div>
          <CustomSelect value={count} onChange={setCount} options={COUNT_OPTIONS} />
        </div>
        <div style={{ minWidth: 180 }}>
          <div className="label-micro">Difficulty</div>
          <CustomSelect
            value={difficulty}
            onChange={v => setDifficulty(v as "recall" | "application" | "conceptual")}
            options={DIFFICULTY_OPTIONS}
          />
        </div>
      </div>

      <button className="btn btn--primary btn--sm" onClick={generate} disabled={busy || !canGo}>
        {busy ? "Generating…" : "Generate cards"}
      </button>
    </div>
  );
}
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/flashcards/tabs/AiTab.tsx
git commit -m "feat(frontend): AiTab generates cards from paste or library doc"
```

### Task 27: `tabs/PhotoTab.tsx`

**Files:**
- Create: `frontend/src/components/flashcards/tabs/PhotoTab.tsx`

- [ ] **Step 1: Write the component**

```tsx
"use client";
import React from "react";
import { Icon } from "../../Icon";
import { useToast } from "../../ToastProvider";
import { useUser } from "@/context/UserContext";
import { importParse } from "@/lib/api";
import type { ParsedCard } from "@/lib/flashcardParsers";

interface Props { onCards: (cards: ParsedCard[]) => void }

const MAX_BYTES = 5 * 1024 * 1024;

async function readAsBase64(file: File): Promise<string> {
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => {
      const dataUrl = String(r.result ?? "");
      res(dataUrl.split(",", 2)[1] ?? "");
    };
    r.onerror = () => rej(r.error);
    r.readAsDataURL(file);
  });
}

export function PhotoTab({ onCards }: Props) {
  const toast = useToast();
  const { userId } = useUser();
  const [busy, setBusy] = React.useState(false);
  const inputRef = React.useRef<HTMLInputElement>(null);

  const handleFile = async (file: File) => {
    if (!userId) return;
    if (file.size > MAX_BYTES) { toast.error("Image exceeds 5MB."); return; }
    setBusy(true);
    try {
      const res = await importParse(userId, "ocr", await readAsBase64(file), { filename: file.name });
      onCards(res.cards.map((c, i) => ({ front: c.front, back: c.back, row: i + 1 })));
      toast.success(`Extracted ${res.cards.length} cards from image.`);
    } catch (err) {
      toast.error(`OCR failed: ${String(err)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      onDragOver={e => e.preventDefault()}
      onDrop={e => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) handleFile(f); }}
      onClick={() => inputRef.current?.click()}
      style={{
        border: "2px dashed var(--border)", borderRadius: "var(--r-md)",
        padding: 32, textAlign: "center", color: "var(--text-muted)", cursor: "pointer",
      }}
    >
      <Icon name="image" size={20} />
      <div style={{ marginTop: 8, fontSize: 13 }}>
        {busy ? "Reading image…" : "Drop or click to upload a photo of notes (.png, .jpg, .pdf)"}
      </div>
      <input
        ref={inputRef}
        type="file"
        accept="image/*,.pdf"
        style={{ display: "none" }}
        onChange={e => { const f = e.target.files?.[0]; if (f) handleFile(f); e.target.value = ""; }}
      />
    </div>
  );
}
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/flashcards/tabs/PhotoTab.tsx
git commit -m "feat(frontend): PhotoTab extracts cards from photo via OCR"
```

### Task 28: `FlashcardImportModal.tsx`

**Files:**
- Create: `frontend/src/components/flashcards/FlashcardImportModal.tsx`

- [ ] **Step 1: Write the component**

```tsx
"use client";
import React from "react";
import { Dialog } from "../Dialog";
import { CustomSelect } from "../CustomSelect";
import { useToast } from "../ToastProvider";
import { useUser } from "@/context/UserContext";
import { importCommit, type EnrolledCourse } from "@/lib/api";
import { isValid, type ParsedCard } from "@/lib/flashcardParsers";
import { ParsedCardsTable } from "./ParsedCardsTable";
import { PasteTab } from "./tabs/PasteTab";
import { UploadTab } from "./tabs/UploadTab";
import { UrlTab } from "./tabs/UrlTab";
import { AiTab } from "./tabs/AiTab";
import { PhotoTab } from "./tabs/PhotoTab";

type TabKey = "paste" | "upload" | "url" | "ai" | "photo";

interface LibraryDoc { id: string; file_name: string; category?: string }

interface Props {
  open: boolean;
  onClose: () => void;
  courses: EnrolledCourse[];
  defaultCourseId?: string;
  defaultTopic?: string;
  documents: LibraryDoc[];
  onImported: (count: number) => void;
}

const TABS: { key: TabKey; label: string }[] = [
  { key: "paste", label: "Paste" },
  { key: "upload", label: "Upload" },
  { key: "url", label: "URL" },
  { key: "ai", label: "AI" },
  { key: "photo", label: "Photo" },
];

export function FlashcardImportModal({
  open, onClose, courses, defaultCourseId, defaultTopic, documents, onImported,
}: Props) {
  const toast = useToast();
  const { userId } = useUser();
  const [tab, setTab] = React.useState<TabKey>("paste");
  const [cards, setCards] = React.useState<ParsedCard[]>([]);
  const [reverse, setReverse] = React.useState(false);
  const [courseId, setCourseId] = React.useState<string>(defaultCourseId ?? courses[0]?.course_id ?? "");
  const [topic, setTopic] = React.useState<string>(defaultTopic ?? "");
  const [committing, setCommitting] = React.useState(false);

  React.useEffect(() => {
    if (open) {
      setCards([]);
      setReverse(false);
      setTab("paste");
      setCourseId(defaultCourseId ?? courses[0]?.course_id ?? "");
      setTopic(defaultTopic ?? "");
    }
  }, [open, defaultCourseId, defaultTopic, courses]);

  const validCards = cards.filter(isValid);
  const finalCards = React.useMemo(() => {
    const base = validCards.map(c => ({ front: c.front, back: c.back }));
    if (!reverse) return base;
    return base.flatMap(c => [c, { front: c.back, back: c.front }]);
  }, [validCards, reverse]);

  const commit = async () => {
    if (!userId) return;
    if (!courseId) { toast.warn("Pick a course first."); return; }
    if (!topic.trim()) { toast.warn("Add a topic name."); return; }
    if (finalCards.length === 0) { toast.warn("No valid cards to import."); return; }
    setCommitting(true);
    try {
      const res = await importCommit(userId, courseId, topic.trim(), finalCards, true);
      const skipNote = res.skipped_duplicates > 0
        ? ` ${res.skipped_duplicates} skipped (duplicates).`
        : "";
      toast.success(`Imported ${res.inserted} card${res.inserted === 1 ? "" : "s"}.${skipNote}`);
      onImported(res.inserted);
      onClose();
    } catch (err) {
      toast.error(`Import failed: ${String(err)}`);
    } finally {
      setCommitting(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} title="Import flashcards" maxWidth={840}>
      <div style={{ display: "flex", flexDirection: "column", gap: 14, padding: 4 }}>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <div style={{ minWidth: 220 }}>
            <div className="label-micro">Course</div>
            <CustomSelect
              value={courseId}
              onChange={setCourseId}
              placeholder="Pick a course…"
              options={courses.map(c => ({
                value: c.course_id,
                label: c.course_code || c.course_name,
                description: c.course_code ? c.course_name : undefined,
              }))}
            />
          </div>
          <div style={{ minWidth: 220, flex: 1 }}>
            <div className="label-micro">Topic / set name</div>
            <input
              value={topic}
              onChange={e => setTopic(e.target.value)}
              placeholder="e.g. Cell Biology — Chapter 5"
              style={{ width: "100%", padding: 8, borderRadius: "var(--r-md)", background: "var(--bg-panel)", border: "1px solid var(--border)", color: "var(--text)" }}
            />
          </div>
        </div>

        <div style={{ display: "flex", borderBottom: "1px solid var(--border)" }}>
          {TABS.map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              style={{
                padding: "8px 14px", fontSize: 13, fontWeight: tab === t.key ? 600 : 500,
                color: tab === t.key ? "var(--accent)" : "var(--text-dim)",
                background: "transparent",
                borderBottom: tab === t.key ? "2px solid var(--accent)" : "2px solid transparent",
              }}
            >{t.label}</button>
          ))}
        </div>

        {tab === "paste" && <PasteTab cards={cards} onCards={setCards} />}
        {tab === "upload" && <UploadTab onCards={setCards} />}
        {tab === "url" && <UrlTab onCards={setCards} />}
        {tab === "ai" && <AiTab documents={documents} onCards={setCards} />}
        {tab === "photo" && <PhotoTab onCards={setCards} />}

        <ParsedCardsTable
          cards={cards}
          onChange={setCards}
          reverseEnabled={reverse}
          onReverseToggle={setReverse}
        />

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 6 }}>
          <button className="btn btn--sm" onClick={onClose}>Cancel</button>
          <button
            className="btn btn--sm btn--primary"
            onClick={commit}
            disabled={committing || finalCards.length === 0 || !courseId || !topic.trim()}
          >
            {committing ? "Importing…" : `Import ${finalCards.length} card${finalCards.length === 1 ? "" : "s"}`}
          </button>
        </div>
      </div>
    </Dialog>
  );
}
```

- [ ] **Step 2: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: zero errors. (If the existing `Dialog` component has a different API, adjust the props accordingly.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/flashcards/FlashcardImportModal.tsx
git commit -m "feat(frontend): FlashcardImportModal shell with 5 tabs and commit flow"
```

### Task 29: Wire into `Study.tsx`

**Files:**
- Modify: `frontend/src/components/screens/Study.tsx`
- Modify: `frontend/src/lib/api.ts` (only if a `getDocuments` helper is missing — verify first)

- [ ] **Step 1: Confirm `getDocuments` helper exists**

```bash
cd /home/andresl/Projects/sapling && grep -n "getDocuments\|/api/documents/user" frontend/src/lib/api.ts | head
```

Expected: a helper that hits `/api/documents/user/{userId}` returning a list with `id`, `file_name`, `category`. If absent, add this helper to `lib/api.ts` first:

```typescript
export const getLibraryDocuments = (userId: string) =>
  fetchJSON<{ documents: { id: string; file_name: string; category?: string }[] }>(
    `/api/documents/user/${encodeURIComponent(userId)}`,
  );
```

- [ ] **Step 2: Add import button + modal mount in `FlashcardsMode`**

In `frontend/src/components/screens/Study.tsx`:

1. Add to the imports near the top:

```typescript
import { FlashcardImportModal } from "../flashcards/FlashcardImportModal";
import { getLibraryDocuments } from "@/lib/api";
```

2. Inside `FlashcardsMode` (after existing state declarations, around line 333):

```typescript
const [importOpen, setImportOpen] = React.useState(false);
const [docs, setDocs] = React.useState<{ id: string; file_name: string; category?: string }[]>([]);

React.useEffect(() => {
  if (!userId) return;
  getLibraryDocuments(userId)
    .then(r => setDocs(r.documents || []))
    .catch(() => setDocs([]));
}, [userId]);
```

3. Replace the existing "Generate cards" button block (around lines 449-455) with both buttons:

```tsx
<button
  className="btn btn--sm"
  onClick={() => setImportOpen(true)}
  disabled={!userId}
>
  <Icon name="upload" size={12} /> Import
</button>
<button
  className="btn btn--sm btn--primary"
  onClick={generate}
  disabled={generating || !userId}
>
  <Icon name="sparkle" size={12} /> {generating ? "Generating…" : "Generate cards"}
</button>
```

4. Just before the closing `</div>` of the outermost return in `FlashcardsMode`, mount the modal:

```tsx
<FlashcardImportModal
  open={importOpen}
  onClose={() => setImportOpen(false)}
  courses={courses}
  defaultCourseId={courseId !== "all" ? courseId : courses[0]?.course_id}
  defaultTopic={topicFilter !== "all" ? topicFilter : ""}
  documents={docs}
  onImported={() => { load(); }}
/>
```

- [ ] **Step 3: Type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/screens/Study.tsx frontend/src/lib/api.ts
git commit -m "feat(frontend): wire Import button + FlashcardImportModal into Study"
```

---

## Phase 8 — Verification

### Task 30: End-to-end smoke test

**Files:** none modified

- [ ] **Step 1: Run all backend tests**

```bash
cd backend && source venv/bin/activate && python -m pytest tests/ -q
```

Expected: zero failures.

- [ ] **Step 2: Frontend type-check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 3: Start dev servers**

In one terminal:

```bash
cd backend && source venv/bin/activate && python main.py
```

In another:

```bash
cd frontend && npm run dev
```

- [ ] **Step 4: Manual smoke matrix in the browser**

Open http://localhost:3000, sign in, go to Study → Flashcards, click **Import**.

Verify each:

1. **Paste — Quizlet-style tab/newline**: paste a 50-row sample. Auto-detect picks tab + newline. All rows show as valid in the table.
2. **Paste — semicolon between cards**: paste, change "Between cards" to Semicolon. Re-parses live.
3. **Paste — cloze mode**: switch to Cloze, paste a paragraph, click Generate. Cards have `{{...}}` on the front.
4. **Upload .csv with quoted multi-line definitions**: row count matches expected; quoted newlines preserved in `back`.
5. **Upload .apkg**: drop a real Anki export. HTML stripped, cards visible.
6. **URL — public Quizlet set**: either fetches cards or gracefully shows the "Couldn't fetch" hint card.
7. **AI — paste notes**: paste lecture notes, count=10, difficulty=recall. Returns 10 cards.
8. **AI — from library**: pick a previously uploaded library doc, count=25, difficulty=conceptual. Returns 25 cards.
9. **Photo OCR**: drop a screenshot of notes. Cards extracted.
10. **Reverse cards toggle**: import 3 cards with reverse on → DB has 6 cards.
11. **Cleanup pass**: import a card with a typo ("miotsis"), click "Clean up with AI". Front becomes "Mitosis".
12. **Dedup**: re-import the same 3 cards. Toast says `"Imported 0 cards. 3 skipped (duplicates)."`
13. **Import button position**: shows next to "Generate cards" in `FlashcardsMode`. After commit, the card list reloads and the new cards appear.

- [ ] **Step 5: Commit any final tweaks discovered during smoke**

```bash
git add -A
git commit -m "chore: smoke-test polish for flashcard import"   # only if needed
```

---

## Self-Review (filled in)

**Spec coverage:**
- 5 import methods → Tasks 23 (paste), 24 (upload), 25 (url), 26 (ai), 27 (photo). ✓
- Smart delimiter detection → `detectDelimiters` in Task 21. ✓
- Live preview re-parse → `useEffect` in PasteTab Task 23. ✓
- Error highlighting in table → `border-left: var(--err)` in ParsedCardsTable Task 22. ✓
- `course_id` migration → Task 1. ✓
- 5 routes → Tasks 15, 16, 17, 18 (cleanup + cloze in one task). ✓
- 4 prompts → Task 9 (ocr split) + Task 10 (gen, cleanup, cloze). ✓
- Dedup with Levenshtein → Task 4. ✓
- Rate limit → Task 5. ✓
- Anki .apkg → Task 7. ✓
- xlsx → Task 6. ✓
- Quizlet URL with graceful blocking → Task 8 + UrlTab fallback (Task 25). ✓
- Image OCR → Task 9. ✓
- AI generation paste + library → Task 17. ✓
- AI cleanup → Task 18. ✓
- AI cloze → Task 18. ✓
- Reverse cards toggle → ParsedCardsTable + commit logic in `FlashcardImportModal` (Task 28). ✓
- 5MB cap → enforced in route (Task 16) and tabs (Task 24, 27). ✓
- Wiring into Study → Task 29. ✓
- Backend tests → Task 4–18 each include tests. ✓

**Placeholder scan:** No "TBD", "TODO", or "implement later" in any code step. All code blocks are complete and runnable.

**Type consistency:** `Card` in backend and `ImportCard` in frontend both shape `{front, back}`. `ParsedCard` adds `row, error?` only on the frontend. Route paths use `/import/parse|commit|generate|cleanup|cloze` consistently. Source enum `anki|xlsx|url|ocr` for `/parse` vs `paste|library_doc` for `/generate` is documented in the spec and the route bodies.
