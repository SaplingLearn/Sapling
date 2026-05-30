"""
backend/services/integrations/gradescope.py

Fetches courses, assignments, and grades from Gradescope and normalises
them into Sapling's existing assignments + course_categories schema.

Depends on: gradescopeapi  (pip install gradescopeapi)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from db.connection import table
from services.encryption import encrypt, decrypt, encrypt_if_present

try:
    from gradescopeapi.classes.connection import GSConnection
    GRADESCOPE_AVAILABLE = True
except ImportError:
    GRADESCOPE_AVAILABLE = False


# ---------------------------------------------------------------------------
# Credential helpers
# ---------------------------------------------------------------------------

def save_credentials(user_id: str, email: str, password: str) -> None:
    """Encrypt and persist Gradescope credentials for a user."""
    import json
    raw = json.dumps({"email": email, "password": password})
    encrypted = encrypt(raw)
    table("external_connections").upsert(
        {
            "user_id": user_id,
            "provider": "gradescope",
            "credentials": encrypted,
            "status": "active",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="user_id,provider",
    )


def load_credentials(user_id: str) -> dict | None:
    """Return decrypted {"email": ..., "password": ...} or None."""
    import json
    rows = table("external_connections").select(
        "credentials,status",
        filters={"user_id": f"eq.{user_id}", "provider": "eq.gradescope"},
        limit=1,
    )
    if not rows or rows[0].get("status") == "disconnected":
        return None
    raw = decrypt(rows[0]["credentials"])
    try:
        return json.loads(raw)
    except Exception:
        return None


def mark_connection_error(user_id: str, message: str) -> None:
    table("external_connections").update(
        {"status": "error", "updated_at": datetime.now(timezone.utc).isoformat()},
        filters={"user_id": f"eq.{user_id}", "provider": "eq.gradescope"},
    )
    _log_sync_event(user_id, "error", error_message=message)


def mark_connection_synced(user_id: str, courses: int, assignments: int) -> None:
    table("external_connections").update(
        {
            "status": "active",
            "last_synced_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        filters={"user_id": f"eq.{user_id}", "provider": "eq.gradescope"},
    )
    _log_sync_event(user_id, "success", courses_synced=courses, assignments_synced=assignments)


def _log_sync_event(
    user_id: str,
    status: str,
    courses_synced: int = 0,
    assignments_synced: int = 0,
    error_message: str | None = None,
) -> None:
    table("external_sync_events").insert({
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "provider": "gradescope",
        "status": status,
        "courses_synced": courses_synced,
        "assignments_synced": assignments_synced,
        "error_message": error_message,
    })


# ---------------------------------------------------------------------------
# Sync logic
# ---------------------------------------------------------------------------

def sync_user(user_id: str) -> dict[str, Any]:
    """
    Full sync for one user. Returns {"courses_synced": N, "assignments_synced": M}.

    Raises ValueError on auth failure or missing credentials.
    Raises RuntimeError if gradescopeapi is not installed.
    """
    if not GRADESCOPE_AVAILABLE:
        raise RuntimeError("gradescopeapi is not installed. Run: pip install gradescopeapi")

    creds = load_credentials(user_id)
    if not creds:
        raise ValueError("No Gradescope credentials found for this user.")

    # Authenticate
    conn = GSConnection()
    try:
        conn.login(creds["email"], creds["password"])
    except Exception as exc:
        mark_connection_error(user_id, f"Login failed: {exc}")
        raise ValueError(f"Gradescope login failed: {exc}") from exc

    courses_synced = 0
    assignments_synced = 0

    try:
        account = conn.account
        courses = account.get_courses() or {}
    except Exception as exc:
        mark_connection_error(user_id, f"Failed to fetch courses: {exc}")
        raise ValueError(f"Failed to fetch Gradescope courses: {exc}") from exc

    # gradescopeapi returns {"student": {...}, "instructor": {...}}
    all_courses: dict = {}
    for role_bucket in courses.values():
        if isinstance(role_bucket, dict):
            all_courses.update(role_bucket)

    for course_id_gs, course_obj in all_courses.items():
        try:
            sapling_course_id = _upsert_course(user_id, course_id_gs, course_obj)
            n = _upsert_assignments(user_id, sapling_course_id, course_id_gs, conn)
            assignments_synced += n
            courses_synced += 1
        except Exception:
            # Don't abort the whole sync if one course fails.
            continue

    mark_connection_synced(user_id, courses_synced, assignments_synced)
    return {"courses_synced": courses_synced, "assignments_synced": assignments_synced}


# ---------------------------------------------------------------------------
# Course upsert
# ---------------------------------------------------------------------------

def _upsert_course(user_id: str, gs_course_id: str, course_obj: Any) -> str:
    """
    Find or create a course + user_courses enrollment.
    Returns the Sapling course id.
    """
    name: str = getattr(course_obj, "name", None) or str(course_obj) or gs_course_id
    # Derive a stable Sapling id from the Gradescope course id so re-syncs
    # don't create duplicates.
    sapling_course_id = f"gs_{gs_course_id}"

    existing = table("courses").select("id", filters={"id": f"eq.{sapling_course_id}"}, limit=1)
    if not existing:
        table("courses").insert({
            "id": sapling_course_id,
            "course_code": _extract_code(name),
            "course_name": name,
            "semester": _current_semester(),
            "source": "gradescope",
        })

    # Enroll the user if not already enrolled.
    enrolled = table("user_courses").select(
        "id",
        filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{sapling_course_id}"},
        limit=1,
    )
    if not enrolled:
        table("user_courses").insert({
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "course_id": sapling_course_id,
        })

    return sapling_course_id


# ---------------------------------------------------------------------------
# Assignment upsert
# ---------------------------------------------------------------------------

def _upsert_assignments(
    user_id: str,
    sapling_course_id: str,
    gs_course_id: str,
    conn: Any,
) -> int:
    """Fetch and upsert assignments for one course. Returns count inserted."""
    try:
        assignments = conn.account.get_assignments(gs_course_id) or []
    except Exception:
        return 0

    # Existing titles for dedup (same pattern as gradebook_service apply_syllabus)
    existing = table("assignments").select(
        "title",
        filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{sapling_course_id}"},
    )
    seen_titles = {r["title"] for r in existing}

    to_insert = []
    for a in assignments:
        title = getattr(a, "name", None) or getattr(a, "title", None) or "Untitled"
        if title in seen_titles:
            # Update grade if available rather than skipping entirely.
            _maybe_update_grade(user_id, sapling_course_id, title, a)
            continue
        seen_titles.add(title)
        to_insert.append(_build_assignment_row(user_id, sapling_course_id, title, a))

    if to_insert:
        table("assignments").insert(to_insert)

    return len(to_insert)


def _build_assignment_row(
    user_id: str,
    course_id: str,
    title: str,
    a: Any,
) -> dict:
    due_date = _parse_date(getattr(a, "due_date", None))
    points_possible = _to_float(getattr(a, "total_points", None))
    points_earned = _to_float(getattr(a, "score", None))
    return {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "course_id": course_id,
        "title": title,
        "due_date": due_date,
        "assignment_type": "assignment",
        "points_possible": encrypt_if_present(points_possible),
        "points_earned": encrypt_if_present(points_earned),
        "category_id": None,
        "notes": None,
        "source": "gradescope",
    }


def _maybe_update_grade(
    user_id: str,
    course_id: str,
    title: str,
    a: Any,
) -> None:
    """If Gradescope has a score for an already-known assignment, write it."""
    points_earned = _to_float(getattr(a, "score", None))
    points_possible = _to_float(getattr(a, "total_points", None))
    if points_earned is None and points_possible is None:
        return
    patch: dict = {}
    if points_earned is not None:
        patch["points_earned"] = encrypt_if_present(points_earned)
    if points_possible is not None:
        patch["points_possible"] = encrypt_if_present(points_possible)
    table("assignments").update(
        patch,
        filters={
            "user_id": f"eq.{user_id}",
            "course_id": f"eq.{course_id}",
            "title": f"eq.{title}",
        },
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_code(name: str) -> str:
    """Best-effort: return first whitespace-delimited token as course code."""
    parts = name.strip().split()
    return parts[0] if parts else name[:16]


def _current_semester() -> str:
    """Return e.g. 'Fall 2025' based on current month."""
    now = datetime.now(timezone.utc)
    season = "Spring" if now.month < 7 else "Fall"
    return f"{season} {now.year}"


def _parse_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    s = str(value)
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:19], fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None