"""What an account holds right now, for the admin tools' review step.

`summarize_account(user_id)` answers "what will Seed / Wipe / Copy delete?"
before the admin confirms one: exact row counts for the user-facing study
tables, the courses the account is enrolled in, and its XP. Read-only — it
never takes the per-user operation lock, so a review is never refused because
another operation is running (the action itself still is).

Every counted table is one the wipe empties (`account_wipe.wiped_tables()`,
pinned by tests/test_account_summary.py), so each number is a lower bound on
what an action will remove — never a table the action leaves alone.

Shape (also the internal `/api/internal/account-sync/summary` body)::

    {"exists": bool,
     "courses": [{"code", "name", "term_id"}],   # enrollments → offerings → courses
     "counts": {<table>: n},                      # every key of SUMMARY_TABLES
     "total_xp": int,
     "empty": bool}                               # no counted rows and no XP

A missing or soft-deleted account is `exists=False` with zero counts.
"""

from __future__ import annotations

from typing import Iterator

from db.connection import page_all, pg_quote_value, table

#: Tables counted, with the column that identifies one row (the count's
#: projection). `assignments` hangs off the user's enrollments; every other
#: table carries `user_id`.
SUMMARY_TABLES: tuple[tuple[str, str], ...] = (
    ("enrollments", "id"),
    ("assignments", "id"),
    ("graph_nodes", "id"),
    ("notes", "id"),
    ("documents", "id"),
    ("flashcards", "id"),
    ("quiz_attempts", "id"),
    ("sessions", "id"),
    ("study_guides", "id"),
    ("xp_events", "id"),
    ("user_achievements", "achievement_id"),
)

_IN_CHUNK = 50  # ids per `in.(…)` filter — keeps the query string bounded


def _chunks(items: list[str], size: int = _IN_CHUNK) -> Iterator[list[str]]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _in(values: list[str]) -> str:
    return f"in.({','.join(pg_quote_value(str(v)) for v in values)})"


def empty_summary(*, exists: bool = False) -> dict:
    """The summary of an account with nothing in it (or no account at all)."""
    return {
        "exists": exists,
        "courses": [],
        "counts": {name: 0 for name, _ in SUMMARY_TABLES},
        "total_xp": 0,
        "empty": True,
    }


def _count(name: str, filters: dict, key: str) -> int:
    """Exact row count via PostgREST's `Prefer: count=exact` (one row fetched).

    `select_with_count` reports 0 when Content-Range is missing or unparseable;
    a row in hand beside a 0 total is that case, and the rows are counted by
    paging instead — never reported as zero.
    """
    rows, total = table(name).select_with_count(key, filters=filters, limit=1)
    if total or not rows:
        return int(total or 0)
    return sum(1 for _ in page_all(table(name), key, filters=filters, order=key))


def _courses(offering_ids: list[str]) -> list[dict]:
    offerings: list[dict] = []
    for chunk in _chunks(offering_ids):
        offerings.extend(
            table("course_offerings").select("id,course_id,term_id", filters={"id": _in(chunk)})
            or []
        )
    course_ids = sorted({o["course_id"] for o in offerings if o.get("course_id")})
    courses: dict[str, dict] = {}
    for chunk in _chunks(course_ids):
        for c in table("courses").select(
            "id,course_code,course_name", filters={"id": _in(chunk)},
        ) or []:
            courses[c["id"]] = c
    out = []
    for o in offerings:
        c = courses.get(o.get("course_id"))
        if c is None:
            continue
        out.append({
            "code": c.get("course_code") or "",
            "name": c.get("course_name") or "",
            "term_id": o.get("term_id"),
        })
    return sorted(out, key=lambda c: (c["code"], str(c["term_id"] or "")))


def summarize_account(user_id: str) -> dict:
    """Counts, courses and XP for `user_id` here. Read-only; never raises for
    a missing account (`exists=False`)."""
    if not isinstance(user_id, str) or not user_id.strip():
        return empty_summary()
    users = table("users").select(
        "id,total_xp", filters={"id": f"eq.{user_id}", "deleted_at": "is.null"}, limit=1,
    ) or []
    if not users:
        return empty_summary()

    enrollments = list(page_all(
        table("enrollments"), "id,offering_id",
        filters={"user_id": f"eq.{user_id}"}, order="id",
    ))
    enrollment_ids = [e["id"] for e in enrollments if e.get("id")]

    counts: dict[str, int] = {}
    for name, key in SUMMARY_TABLES:
        if name == "enrollments":
            counts[name] = len(enrollment_ids)
        elif name == "assignments":
            counts[name] = sum(
                _count(name, {"enrollment_id": _in(chunk)}, key)
                for chunk in _chunks(enrollment_ids)
            )
        else:
            counts[name] = _count(name, {"user_id": f"eq.{user_id}"}, key)

    try:
        total_xp = max(int(users[0].get("total_xp") or 0), 0)
    except (TypeError, ValueError):
        total_xp = 0
    offering_ids = sorted({e["offering_id"] for e in enrollments if e.get("offering_id")})
    return {
        "exists": True,
        "courses": _courses(offering_ids),
        "counts": counts,
        "total_xp": total_xp,
        "empty": total_xp == 0 and not any(counts.values()),
    }
