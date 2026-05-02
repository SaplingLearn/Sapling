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
from services import extraction_service


class Card(TypedDict):
    front: str
    back: str


class QuizletBlocked(Exception):
    """Raised when scrape_quizlet_url cannot extract cards."""


_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")


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


def _guess_content_type(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".jpg") or lower.endswith(".jpeg"):
        return "image/jpeg"
    if lower.endswith(".gif"):
        return "image/gif"
    if lower.endswith(".webp"):
        return "image/webp"
    return "image/png"


def extract_cards_from_image(file_bytes: bytes, filename: str = "image.png") -> list[Card]:
    """OCR the image via the existing extraction pipeline, then ask Gemini
    to split the markdown into Q/A pairs."""
    content_type = _guess_content_type(filename)
    markdown = extraction_service.extract_text_from_file(file_bytes, filename, content_type) or ""
    if not markdown.strip():
        return []
    prompt = _load_prompt("flashcard_ocr_split.txt").replace("{markdown}", markdown)
    raw = call_gemini(prompt, json_mode=True)
    return _parse_card_json(raw)


def gemini_generate_cards(source_text: str, count: int, difficulty: str) -> list[Card]:
    prompt = (
        _load_prompt("flashcard_generation.txt")
        .replace("{count}", str(count))
        .replace("{difficulty}", difficulty)
        .replace("{source}", source_text)
    )
    raw = call_gemini(prompt, json_mode=True)
    return _parse_card_json(raw)


def gemini_cleanup_cards(cards: list[Card]) -> list[Card]:
    prompt = _load_prompt("flashcard_cleanup.txt").replace(
        "{cards_json}", json.dumps(cards, ensure_ascii=False)
    )
    raw = call_gemini(prompt, json_mode=True)
    out = _parse_card_json(raw)
    return out if out else cards


def gemini_cloze(paragraph: str) -> list[Card]:
    prompt = _load_prompt("flashcard_cloze.txt").replace("{paragraph}", paragraph)
    raw = call_gemini(prompt, json_mode=True)
    return _parse_card_json(raw)
