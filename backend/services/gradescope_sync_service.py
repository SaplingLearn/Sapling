"""backend/services/gradescope_sync_service.py

Orchestrates syncing one linked course from Gradescope into the Sapling
gradebook. Course matching is explicit (via the gradescope_links table,
set up through POST /api/gradescope/link) — no fuzzy name-matching.

⚠️ TWO PLACEHOLDERS BELOW, marked "TODO(wire-me)":
  - `_get_or_create_gradescope_category()` needs your real category
    get-or-create call
  - `_upsert_assignment()` needs your real assignment create/update call

Both raise NotImplementedError until wired up.
"""
from __future__ import annotations

import logging
from typing import Any, Literal, Optional

from models.gradescope import GradescopeSyncResult
from services import gradescope_service as gs
from services.encryption import decrypt_if_present, encrypt_if_present

logger = logging.getLogger(__name__)


class GradescopeSyncError(Exception):
    pass


# ────────────────────────────────────────────────────────────────────────────
# TODO(wire-me): replace with your actual data-access calls
# ────────────────────────────────────────────────────────────────────────────

def _get_or_create_gradescope_category(sapling_course_id: str) -> str:
    """Return the id of a 'Gradescope Import' category on this course,
    creating it if it doesn't exist yet.

    STUB — replace with your real category get-or-create logic (whatever
    routes/gradebook.py already uses, e.g. the same path
    POST /api/gradebook/courses/{course_id}/categories goes through).
    """
    raise NotImplementedError(
        "_get_or_create_gradescope_category is a placeholder — wire it to "
        "your real category get-or-create call."
    )


def _upsert_assignment(
    *,
    sapling_course_id: str,
    category_id: str,
    external_id: Optional[str],
    name: str,
    points_earned: Optional[float],
    points_possible: Optional[float],
) -> Literal["inserted", "updated", "skipped"]:
    """Create or update one assignment row, matched by external_id
    (preferred) or case-insensitive name (fallback).

    STUB — replace with your real assignment create/update call (ideally
    the same one createGradedAssignment / updateGradedAssignment in
    api.ts hit, so behavior stays consistent across import paths).
    """
    raise NotImplementedError(
        "_upsert_assignment is a placeholder — wire it to your real "
        "assignment create/update call."
    )


# ────────────────────────────────────────────────────────────────────────────
# Credential storage (built on encryption.py — this part is real)
# ────────────────────────────────────────────────────────────────────────────

def build_credential_row(
    *,
    auth_mode: str,
    email: Optional[str] = None,
    password: Optional[str] = None,
    gradescope_session: Optional[str] = None,
    signed_token: Optional[str] = None,
) -> dict[str, Any]:
    """Encrypt inputs into the row shape for the gradescope_credentials table."""
    return {
        "auth_mode": auth_mode,
        "encrypted_email": encrypt_if_present(email),
        "encrypted_password": encrypt_if_present(password),
        "encrypted_gradescope_session": encrypt_if_present(gradescope_session),
        "encrypted_signed_token": encrypt_if_present(signed_token),
    }


def connect_from_credential_row(row: dict[str, Any]):
    """Decrypt a stored credential row and produce a logged-in GSConnection."""
    auth_mode = row["auth_mode"]
    if auth_mode == "password":
        email = decrypt_if_present(row.get("encrypted_email"))
        password = decrypt_if_present(row.get("encrypted_password"))
        return gs.login(email, password)
    elif auth_mode == "cookies":
        session_cookie = decrypt_if_present(row.get("encrypted_gradescope_session"))
        signed_token = decrypt_if_present(row.get("encrypted_signed_token"))
        return gs.login_with_cookies(signed_token, session_cookie)
    raise GradescopeSyncError(f"Unknown auth_mode: {auth_mode!r}")


# ────────────────────────────────────────────────────────────────────────────
# Main entry points
# ────────────────────────────────────────────────────────────────────────────

def list_courses_for_linking(credential_row: dict[str, Any]) -> list[dict[str, Any]]:
    """Used by GET /api/gradescope/courses — logs in and returns the raw
    Gradescope course list so the user can pick which one maps to which
    Sapling course."""
    conn = connect_from_credential_row(credential_row)
    return gs.list_student_courses(conn)


def sync_course(
    credential_row: dict[str, Any],
    link: dict[str, Any],
) -> GradescopeSyncResult:
    """Sync one linked course. `link` is a row from gradescope_links:
    {sapling_course_id, gradescope_course_id, ...}.

    Raises gs.GradescopeAuthError / gs.GradescopeFetchError /
    GradescopeSyncError on failure so the route can record last_error.
    """
    result = GradescopeSyncResult()

    conn = connect_from_credential_row(credential_row)
    sapling_course_id = link["sapling_course_id"]
    gradescope_course_id = link["gradescope_course_id"]

    category_id = _get_or_create_gradescope_category(sapling_course_id)
    assignments = gs.list_assignments(conn, gradescope_course_id)

    for a in assignments:
        try:
            outcome = _upsert_assignment(
                sapling_course_id=sapling_course_id,
                category_id=category_id,
                external_id=f"gradescope-{a['id']}" if a.get("id") else None,
                name=a["name"],
                points_earned=a.get("points_earned"),
                points_possible=a.get("points_possible"),
            )
        except Exception as e:  # noqa: BLE001 - per-assignment failure shouldn't abort the whole sync
            logger.warning("Failed to upsert assignment %r: %s", a.get("name"), e)
            result.failed += 1
            continue

        if outcome == "inserted":
            result.inserted += 1
        elif outcome == "updated":
            result.updated += 1
        else:
            result.skipped += 1

    return result