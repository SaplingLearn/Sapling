"""
backend/routes/integrations_piazza.py

Piazza endpoints, kept in their own router file rather than appended to
routes/integrations.py, since that file currently has two different
in-flight versions of the Gradescope service underneath it and I didn't
want to add merge conflicts on top of that. Mount alongside the existing
integrations router in main.py:

    from routes import integrations_piazza
    app.include_router(integrations_piazza.router, prefix="/api/integrations")

Or, once the Gradescope situation is settled, just move these functions
into routes/integrations.py directly -- they follow the same shape as its
gradescope endpoints on purpose.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from services.auth_guard import require_self
from services.integrations import piazza as pz_service

router = APIRouter()


class PiazzaConnectBody(BaseModel):
    user_id: str
    email: str
    password: str


class PiazzaLinkCourseBody(BaseModel):
    user_id: str
    course_id: str
    network_id: str


class PiazzaSyncBody(BaseModel):
    user_id: str


@router.post("/piazza/connect")
def connect_piazza(body: PiazzaConnectBody, request: Request):
    """Save Piazza credentials. Does NOT sync anything yet -- there's
    nothing to sync until at least one course is linked via
    /piazza/link-course, since piazza-api can't enumerate a user's
    classes on its own."""
    require_self(body.user_id, request)
    try:
        pz_service.save_credentials(body.user_id, body.email, body.password)
    except pz_service.PiazzaAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except pz_service.PiazzaUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"connected": True}


@router.post("/piazza/link-course")
def link_course(body: PiazzaLinkCourseBody, request: Request):
    """Attach a Piazza network_id (from the course's Piazza URL) to a
    course already in the user's gradebook, and run the first sync."""
    require_self(body.user_id, request)
    try:
        result = pz_service.link_course(body.user_id, body.course_id, body.network_id)
    except pz_service.PiazzaAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except pz_service.PiazzaUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"linked": True, **result}


@router.delete("/piazza/link-course")
def unlink_course(request: Request, user_id: str = Query(...), course_id: str = Query(...)):
    require_self(user_id, request)
    pz_service.unlink_course(user_id, course_id)
    return {"unlinked": True}


@router.post("/piazza/sync")
def sync_piazza(body: PiazzaSyncBody, request: Request):
    """Re-sync every course this user has linked."""
    require_self(body.user_id, request)
    try:
        result = pz_service.sync_user(body.user_id)
    except pz_service.PiazzaAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except pz_service.PiazzaUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"synced": True, **result}


@router.get("/piazza/posts")
def get_posts(
    request: Request,
    user_id: str = Query(...),
    course_id: str = Query(...),
    limit: int = Query(50, le=200),
):
    """Cached read -- serves whatever was captured on the last sync.
    Doesn't hit Piazza live, so it's fast and works even if Piazza is
    down or credentials have lapsed."""
    require_self(user_id, request)
    try:
        posts = pz_service.list_posts(user_id, course_id, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"posts": posts}