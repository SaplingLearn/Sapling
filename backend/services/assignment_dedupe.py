"""
Shared assignment deduplication keys (#16).

Used by calendar import, syllabus extraction, and document upload saves.
"""
from __future__ import annotations


def assignment_dedupe_key(title: str | None, due_date: str | None) -> tuple[str, str]:
    """
    Canonical key: same trimmed title + same calendar day (YYYY-MM-DD) → one row.
    ISO datetimes are normalized to the date part only.
    """
    t = (title or "").strip()
    d = (due_date or "").strip()
    if len(d) >= 10 and d[4] == "-" and d[7] == "-":
        d = d[:10]
    return (t, d)
