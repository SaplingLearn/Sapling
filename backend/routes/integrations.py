"""
backend/routes/integrations.py

Endpoints for connecting and syncing external LMS providers.
Currently supports: Gradescope.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from services.auth_guard import require_self
from services.integrations import gradescope as gs_service

router = APIRouter()


# ---------------------------------------------------------------------------
# Gradescope
# ---------------------------------------------------------------------------

class GradescopeConnectBody(BaseModel):
    user_id: str
    email: str
    password: str


class GradescopeSyncBody(BaseModel):
    user_id: str


@router.post("/gradescope/connect")
def connect_gradescope(body: GradescopeConnectBody, request: Request):
    """
    Save Gradescope credentials and immediately run a first sync.

    Credentials are AES-256-GCM encrypted at rest (same as other PII
    columns). We never return them to the client.
    """
    require_self(body.user_id, request)

    try:
        gs_service.save_credentials(body.user_id, body.email, body.password)
        result = gs_service.sync_user(body.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return {
        "connected": True,
        "courses_synced": result["courses_synced"],
        "assignments_synced": result["assignments_synced"],
    }


@router.post("/gradescope/sync")
def sync_gradescope(body: GradescopeSyncBody, request: Request):
    """
    Re-sync Gradescope data for a user who is already connected.
    """
    require_self(body.user_id, request)

    try:
        result = gs_service.sync_user(body.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return {
        "synced": True,
        "courses_synced": result["courses_synced"],
        "assignments_synced": result["assignments_synced"],
    }


@router.delete("/gradescope/disconnect")
def disconnect_gradescope(request: Request, user_id: str):
    """
    Mark the connection as disconnected and wipe stored credentials.
    Does not delete synced courses or assignments.
    """
    require_self(user_id, request)

    from db.connection import table
    table("external_connections").update(
        {"status": "disconnected", "credentials": None},
        filters={"user_id": f"eq.{user_id}", "provider": "eq.gradescope"},
    )
    return {"disconnected": True}


@router.get("/gradescope/status")
def gradescope_status(request: Request, user_id: str):
    """Return connection status and last sync time for the UI."""
    require_self(user_id, request)

    from db.connection import table
    rows = table("external_connections").select(
        "status,last_synced_at",
        filters={"user_id": f"eq.{user_id}", "provider": "eq.gradescope"},
        limit=1,
    )
    if not rows:
        return {"connected": False}
    row = rows[0]
    return {
        "connected": row["status"] == "active",
        "status": row["status"],
        "last_synced_at": row.get("last_synced_at"),
    }