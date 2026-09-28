"""GET /api/flags — the signed-in student's client-visible flags (#620)."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from services import feature_flags
from services.auth_guard import get_session_user_id

router = APIRouter()


@router.get("")
def get_flags(request: Request):
    try:
        user_id = get_session_user_id(request)
    except HTTPException:
        user_id = None
    return JSONResponse(
        {"flags": feature_flags.resolved_client_flags(user_id)},
        headers={"Cache-Control": "private, no-store"},
    )
