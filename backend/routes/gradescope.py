"""backend/routes/gradescope.py

Matches the contract already defined in frontend/src/lib/api.ts exactly:
URLs, param placement (user_id as query param, like the rest of this
app's routes — e.g. calendar/status/{userId}), and response shapes.

⚠️ STORAGE PLACEHOLDER: `_load_credential_row` / `_save_credential_row` /
`_delete_credential_row` / `_update_sync_metadata` and the
gradescope_links row helpers are stubbed against a guessed
`db.connection.table(...)` PostgREST-style helper. Replace with your real
data-access call.

Deliberately NOT implemented: POST /api/gradescope/credentials/bu-sso.
frontend/src/lib/api.ts already calls this (connectGradescopeViaBuSso) but
I'm not building server-side automation of a university SSO/Duo login —
see conversation for why. Point that button at something else, or remove
it from api.ts / the UI.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

from models.gradescope import (
    GradescopeCourse,
    GradescopeCredentialsIn,
    GradescopeLink,
    GradescopeLinkIn,
    GradescopeStatus,
    GradescopeSyncResult,
)
from services import gradescope_service as gs
from services.gradescope_sync_service import (
    GradescopeSyncError,
    build_credential_row,
    list_courses_for_linking,
    sync_course,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/gradescope", tags=["gradescope"])


# ────────────────────────────────────────────────────────────────────────────
# TODO(wire-me): replace with your real table access
# ────────────────────────────────────────────────────────────────────────────

def _load_credential_row(user_id: str) -> Optional[dict[str, Any]]:
    from db.connection import table  # type: ignore[import-not-found]

    rows = table("gradescope_credentials").select("*").eq("user_id", user_id).execute()
    data = getattr(rows, "data", None) or []
    return data[0] if data else None


def _save_credential_row(user_id: str, row: dict[str, Any]) -> None:
    from db.connection import table  # type: ignore[import-not-found]

    payload = {**row, "user_id": user_id, "updated_at": datetime.now(timezone.utc).isoformat()}
    table("gradescope_credentials").upsert(payload, on_conflict="user_id").execute()


def _delete_credential_row(user_id: str) -> None:
    from db.connection import table  # type: ignore[import-not-found]

    table("gradescope_credentials").delete().eq("user_id", user_id).execute()


def _update_sync_metadata(
    user_id: str, sapling_course_id: str, *, last_error: Optional[str]
) -> None:
    from db.connection import table  # type: ignore[import-not-found]

    now = datetime.now(timezone.utc).isoformat()
    table("gradescope_credentials").update({"last_error": last_error}).eq(
        "user_id", user_id
    ).execute()
    table("gradescope_links").update({"last_synced_at": now}).eq(
        "user_id", user_id
    ).eq("sapling_course_id", sapling_course_id).execute()


def _load_link(user_id: str, sapling_course_id: str) -> Optional[dict[str, Any]]:
    from db.connection import table  # type: ignore[import-not-found]

    rows = (
        table("gradescope_links")
        .select("*")
        .eq("user_id", user_id)
        .eq("sapling_course_id", sapling_course_id)
        .execute()
    )
    data = getattr(rows, "data", None) or []
    return data[0] if data else None


def _list_links(user_id: str) -> list[dict[str, Any]]:
    from db.connection import table  # type: ignore[import-not-found]

    rows = table("gradescope_links").select("*").eq("user_id", user_id).execute()
    return getattr(rows, "data", None) or []


def _save_link(user_id: str, sapling_course_id: str, gradescope_course_id: str) -> dict[str, Any]:
    from db.connection import table  # type: ignore[import-not-found]

    payload = {
        "user_id": user_id,
        "sapling_course_id": sapling_course_id,
        "gradescope_course_id": gradescope_course_id,
    }
    result = table("gradescope_links").upsert(
        payload, on_conflict="user_id,sapling_course_id"
    ).execute()
    data = getattr(result, "data", None) or []
    return data[0] if data else payload


def _delete_link(user_id: str, sapling_course_id: str) -> None:
    from db.connection import table  # type: ignore[import-not-found]

    table("gradescope_links").delete().eq("user_id", user_id).eq(
        "sapling_course_id", sapling_course_id
    ).execute()


# ────────────────────────────────────────────────────────────────────────────
# Routes — URLs/params match frontend/src/lib/api.ts exactly
# ────────────────────────────────────────────────────────────────────────────

@router.get("/status", response_model=GradescopeStatus)
def get_status(user_id: str):
    row = _load_credential_row(user_id)
    if row is None:
        return GradescopeStatus(has_credentials=False)
    return GradescopeStatus(
        has_credentials=True,
        auth_mode=row.get("auth_mode"),
        last_synced_at=row.get("last_synced_at"),
        credentials_updated_at=row.get("updated_at"),
    )


@router.post("/credentials")
def save_credentials(body: GradescopeCredentialsIn):
    try:
        body.validate_mode()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    # Verify the credentials actually work before storing them, so a typo
    # doesn't sit silently until the next sync attempt fails.
    try:
        if body.auth_mode == "password":
            gs.login(body.email, body.password)
        else:
            gs.login_with_cookies(body.signed_token, body.gradescope_session)
    except gs.GradescopeAuthError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    row = build_credential_row(
        auth_mode=body.auth_mode,
        email=body.email,
        password=body.password,
        gradescope_session=body.gradescope_session,
        signed_token=body.signed_token,
    )
    _save_credential_row(body.user_id, row)
    return {"ok": True}


@router.delete("/credentials")
def delete_credentials(user_id: str):
    _delete_credential_row(user_id)
    return {"ok": True}


@router.get("/courses")
def list_courses(user_id: str):
    row = _load_credential_row(user_id)
    if row is None:
        raise HTTPException(status_code=400, detail="Gradescope isn't connected yet.")
    try:
        raw_courses = list_courses_for_linking(row)
    except gs.GradescopeAuthError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    except gs.GradescopeFetchError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {"courses": [GradescopeCourse(**c) for c in raw_courses]}


@router.get("/links")
def list_links(user_id: str):
    return {"links": [GradescopeLink(**link) for link in _list_links(user_id)]}


@router.post("/link")
def link_course(body: GradescopeLinkIn):
    link = _save_link(body.user_id, body.sapling_course_id, body.gradescope_course_id)
    return {"link": GradescopeLink(**link) if link else None}


@router.delete("/link/{sapling_course_id}")
def unlink_course(sapling_course_id: str, user_id: str):
    _delete_link(user_id, sapling_course_id)
    return {"ok": True}


@router.post("/sync/{sapling_course_id}", response_model=GradescopeSyncResult)
def sync(sapling_course_id: str, user_id: str):
    credential_row = _load_credential_row(user_id)
    if credential_row is None:
        raise HTTPException(status_code=400, detail="Gradescope isn't connected yet.")

    link = _load_link(user_id, sapling_course_id)
    if link is None:
        raise HTTPException(
            status_code=400,
            detail="This course isn't linked to a Gradescope course yet.",
        )

    try:
        result = sync_course(credential_row, link)
    except (gs.GradescopeAuthError, gs.GradescopeFetchError, GradescopeSyncError) as e:
        _update_sync_metadata(user_id, sapling_course_id, last_error=str(e))
        raise HTTPException(status_code=502, detail=str(e)) from e

    _update_sync_metadata(user_id, sapling_course_id, last_error=None)
    return result