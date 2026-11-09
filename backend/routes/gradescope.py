"""
backend/routes/gradescope.py

Per-user Gradescope sync with encrypted passwords or session cookies.
Each import verifies authentication and writes to an enrollment's assignments
using `gradescope_assignment_id` for repeat imports.

Endpoints (mounted under /api/gradescope):
- POST   /credentials                  Test login then save encrypted creds
- DELETE /credentials                  Remove creds (course links are kept)
- GET    /status                       Connection state + last sync outcome
- GET    /courses                      List the user's Gradescope student courses
- GET    /links                        List sapling-course -> gradescope-course mappings
- POST   /link                         Create/update a mapping
- DELETE /link/{sapling_course_id}     Remove a mapping
- POST   /sync/{sapling_course_id}     Pull assignments, upsert grades

Error contract (#770). 401 belongs to Sapling's own session (require_self) and
nothing else: the frontend's global handling owns it. A Gradescope credential
failure is a different state with a different remedy, so it is answered with a
typed non-401 carrying ``error.code`` (ApiError.code on the client):

- 422 ``gradescope_auth_failed``      credentials the user just submitted were
                                      rejected; nothing was saved.
- 409 ``gradescope_reauth_required``  the STORED credentials were rejected (an
                                      expired cookie session, a changed password);
                                      the row is marked ``needs_reauth``.
- 404 ``gradescope_not_connected``    no credentials stored (e.g. after a
                                      disconnect, which keeps course links).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from db.connection import table
from routes._errors import domain_status
from services.auth_guard import require_self, guard_off_loop
from services.gradescope import client as gradescope_service
from services.gradescope import jobs as gradescope_jobs
from services.gradescope.errors import (
    AmbiguousEnrollment,
    AmbiguousLink,
    CourseNotFound,
    GradescopeCredsError,
    GradescopeLinkError,
    NoCourseLink,
)
# Credentials, links and the sync body live in services/gradescope/ (#118);
# the old names stay importable here.
from services.gradescope.credentials import (  # noqa: F401  (re-export, #118)
    AuthMode,
    StoredCreds,
    connection_status,
    save_cookie_creds,
    save_password_creds,
    _establish_connection,
    _load_creds,
    _now_iso,
    _write_connection_state,
)
from services.gradescope.links import (  # noqa: F401  (re-export, #118)
    _all_enrollments_for,
    _enrollment_for,
    _enrollments_in,
    course_links,
    link_course,
    linked_course,
)
from services.gradescope.sync import _due_to_date_string, _run_linked_sync  # noqa: F401  (re-export, #118)
from services.request_context import current_request_id
from services.request_limits import check_rate_limit

logger = logging.getLogger(__name__)
router = APIRouter()

# ── Body models ────────────────────────────────────────────────────────────


class CredentialsBody(BaseModel):
    """Either {auth_mode: 'password', email, password} OR
    {auth_mode: 'cookies', gradescope_session, signed_token?}."""

    user_id: str
    auth_mode: AuthMode = "password"
    # password mode
    email: str | None = None
    password: str | None = None
    # cookies mode
    gradescope_session: str | None = None
    signed_token: str | None = None


class BuSsoBody(BaseModel):
    """Live BU SSO + Duo flow. Username + password are used in-memory only;
    we never persist them. The resulting session cookies are persisted as
    if the user had pasted them themselves (auth_mode='cookies')."""

    user_id: str
    bu_username: str = Field(min_length=1)
    bu_password: str = Field(min_length=1)
    # Caps the time the headless browser spends parked on the Duo iframe
    # waiting for the user's tap. Frontend should match this on its
    # request-timeout side.
    duo_timeout_seconds: int = Field(default=120, ge=15, le=300)


class LinkBody(BaseModel):
    user_id: str
    sapling_course_id: str
    gradescope_course_id: str
    semester: str | None = None


class SyncResult(BaseModel):
    inserted: int
    updated: int
    skipped: int
    failed: int


# ── Helpers ────────────────────────────────────────────────────────────────


# Typed Gradescope error codes (#770) — see the module docstring.
GS_AUTH_FAILED = "gradescope_auth_failed"
GS_REAUTH_REQUIRED = "gradescope_reauth_required"
GS_NOT_CONNECTED = "gradescope_not_connected"


def _gs_error(status_code: int, code: str, message: str) -> JSONResponse:
    """A typed Gradescope error in the coded envelope the frontend reads
    (``error.code`` -> ApiError.code, ``error.message`` -> humanizeError), with
    the legacy ``detail`` kept for older clients.

    Returned rather than raised: main.py's HTTPException handler only emits the
    coded envelope on quiz paths, and a Gradescope code must not depend on that.
    """
    rid = current_request_id()
    return JSONResponse(
        status_code=status_code,
        content={
            "detail": message,
            "error": {"code": code, "message": message, "request_id": rid},
            "request_id": rid,
        },
    )


def _reauth_required(user_id: str, creds: StoredCreds, message: str, **outcome: Any) -> JSONResponse:
    """Stored credentials were rejected: mark them stale, answer 409."""
    _write_connection_state(user_id, {"needs_reauth": True, **outcome}, only_version=creds.updated_at)
    return _gs_error(409, GS_REAUTH_REQUIRED, message or "Gradescope rejected the saved credentials. Reconnect Gradescope.")


def _not_connected() -> JSONResponse:
    return _gs_error(404, GS_NOT_CONNECTED, "No Gradescope credentials saved")


def _enforce_gs_rate_limit(user_id: str, action: str, *, limit: int, window_sec: int) -> None:
    """Per-user sliding-window guard for the live-scrape / headless-browser
    endpoints. Each of these drives a real login + scrape against Gradescope
    (and bu-sso launches a Chromium that blocks a worker thread up to ~300s),
    so without a cap an authenticated user could exhaust workers or get the
    app's IP throttled/banned by Gradescope.
    """
    retry = check_rate_limit(
        f"gradescope:{action}:{user_id}", limit=limit, window_sec=window_sec
    )
    if retry is not None:
        # main.py's HTTPException handler forwards exc.headers as of #544, so
        # the budget rides in a real Retry-After. It stays in the detail
        # string too — clients that only surface the message keep working.
        raise HTTPException(
            status_code=429,
            detail=f"Too many Gradescope {action} requests. Retry in {retry}s.",
            headers={"Retry-After": str(retry)},
        )


# ── Credentials CRUD ───────────────────────────────────────────────────────


@router.post("/credentials")
def save_credentials(body: CredentialsBody, request: Request):
    """Test the login first, then encrypt-and-save. Never persist creds
    that don't authenticate — the user sees a clean error instead.

    Two modes:
      - 'password': test login(email, password). For accounts with a
        Gradescope-side password.
      - 'cookies':  test login_with_cookies(signed_token, _gradescope_session).
        For SSO-only accounts (BU/Shibboleth/Duo), where the user pastes
        their browser session cookies.
    """
    require_self(body.user_id, request)
    # Each save tests a live login against Gradescope before persisting.
    _enforce_gs_rate_limit(body.user_id, "credential", limit=10, window_sec=300)

    if body.auth_mode == "password":
        if not body.email or not body.password:
            raise HTTPException(
                status_code=400, detail="email and password are required for password mode"
            )
        try:
            connection = gradescope_service.login(body.email, body.password)
            connection.session.close()
        except gradescope_service.GradescopeAuthError as e:
            return _gs_error(422, GS_AUTH_FAILED, str(e) or "Gradescope rejected those credentials.")
        except gradescope_service.GradescopeFetchError as e:
            raise HTTPException(status_code=502, detail=str(e))
        save_password_creds(body.user_id, body.email, body.password)
    else:  # cookies
        if not body.gradescope_session:
            raise HTTPException(
                status_code=400,
                detail="_gradescope_session cookie is required for cookies mode",
            )
        try:
            connection = gradescope_service.login_with_cookies(
                signed_token=body.signed_token,
                gradescope_session=body.gradescope_session,
            )
            connection.session.close()
        except gradescope_service.GradescopeAuthError as e:
            return _gs_error(422, GS_AUTH_FAILED, str(e) or "Gradescope rejected those cookies.")
        except gradescope_service.GradescopeFetchError as e:
            raise HTTPException(status_code=502, detail=str(e))
        save_cookie_creds(body.user_id, body.gradescope_session, body.signed_token)
    return {"ok": True}


@router.post("/credentials/bu-sso")
async def save_credentials_via_bu_sso(body: BuSsoBody, request: Request):
    """Live BU SSO via Playwright. Drives a headless Chromium through
    Gradescope → School Credentials → BU WebLogin → Duo. Blocks the
    request until the user taps Duo on their phone (or times out), then
    persists the resulting session cookies as auth_mode='cookies'.

    BU password is held in memory for the duration of the request only;
    we never write it to disk. The frontend should configure a request
    timeout slightly longer than `duo_timeout_seconds` so the spinner can
    sit while we wait for the tap.
    """
    await guard_off_loop(require_self, body.user_id, request)
    # Strictest cap: each call launches a Chromium that pins a worker thread for
    # up to duo_timeout_seconds and fires a Duo push at the user's phone.
    # #117: off the loop -- with `stateless_rate_limit` on, the limiter is a
    # PostgREST call.
    await run_in_threadpool(_enforce_gs_rate_limit, body.user_id, "bu-sso",
                            limit=3, window_sec=600)

    try:
        # sync_playwright wants its own event loop; run the whole flow in
        # a worker thread so FastAPI's loop stays free and Playwright
        # doesn't fight Windows's SelectorEventLoop. ~30s–125s blocking
        # call (mostly idle while we wait on Duo).
        cookies = await asyncio.to_thread(
            gradescope_service.login_via_bu_sso,
            body.bu_username,
            body.bu_password,
            body.duo_timeout_seconds,
        )
    except gradescope_service.GradescopeDuoTimeout as e:
        # 408 reads more honestly than 401 here — the credentials may be
        # fine, the user just didn't tap in time.
        raise HTTPException(status_code=408, detail=str(e) or "Duo push timed out.")
    except gradescope_service.GradescopeAuthError as e:
        return _gs_error(422, GS_AUTH_FAILED, str(e) or "Gradescope auth failed.")
    except Exception:
        logger.exception("Unexpected error in BU SSO flow")
        raise HTTPException(
            status_code=500,
            detail="BU sign-in is unavailable. Please retry or connect using session cookies.",
        )

    # Cookie presence does not prove the SAML callback created a usable login.
    try:
        connection = await asyncio.to_thread(
            gradescope_service.login_with_cookies,
            cookies.get("signed_token"), cookies.get("_gradescope_session"),
        )
        connection.session.close()
    except gradescope_service.GradescopeAuthError as e:
        return _gs_error(422, GS_AUTH_FAILED, str(e) or "Gradescope auth failed.")
    except gradescope_service.GradescopeFetchError as e:
        raise HTTPException(status_code=502, detail=str(e))

    await run_in_threadpool(  # #117: an async handler; keep the write off the loop
        save_cookie_creds, body.user_id,
        cookies.get("_gradescope_session"), cookies.get("signed_token"),
    )
    return {"ok": True}


@router.delete("/credentials")
def delete_credentials(user_id: str, request: Request):
    """Remove stored Gradescope credentials for user_id.

    Course links are deliberately KEPT (#770 decided default): a link names
    which Gradescope course feeds which enrollment, which stays true across a
    disconnect, so reconnecting resumes syncing without re-picking every
    course. While no credentials exist /status reports ``state:
    'disconnected'`` and /sync and /courses answer ``gradescope_not_connected``,
    so a surviving link never reads as a working connection.
    """
    require_self(user_id, request)
    table("gradescope_credentials").delete(filters={"user_id": f"eq.{user_id}"})
    return {"ok": True}


@router.get("/status")
def get_status(user_id: str, request: Request):
    """The connection state and the last sync outcome.

    ``state`` is the one field a client should branch on:
      - ``disconnected``  no credentials saved (course links may still exist)
      - ``needs_reauth``  credentials saved, but Gradescope rejected them on
                          the last login; they will fail until replaced
      - ``connected``     credentials saved and not known to be rejected
    ``has_credentials`` stays for older clients; ``connected`` is
    ``state == 'connected'``. ``last_synced_at`` is the last COMPLETE import;
    ``last_attempt_at`` / ``last_sync_error`` describe the last attempt.
    """
    require_self(user_id, request)
    return connection_status(user_id)


# ── Course listing + linking ───────────────────────────────────────────────


@router.get("/courses")
def list_gradescope_courses(user_id: str, request: Request):
    """Hit Gradescope live with the saved creds, list student-role courses."""
    require_self(user_id, request)
    _enforce_gs_rate_limit(user_id, "courses", limit=10, window_sec=300)
    try:
        creds = _load_creds(user_id)
    except GradescopeCredsError as e:
        raise HTTPException(status_code=500, detail=e.detail)
    if not creds:
        return _not_connected()
    conn = None
    try:
        conn = _establish_connection(creds)
        courses = gradescope_service.list_student_courses(conn)
    except GradescopeCredsError as e:
        raise HTTPException(status_code=500, detail=e.detail)
    except gradescope_service.GradescopeAuthError as e:
        return _reauth_required(user_id, creds, str(e))
    except gradescope_service.GradescopeFetchError as e:
        raise HTTPException(status_code=502, detail=str(e))
    finally:
        if conn is not None:
            conn.session.close()
    if creds.needs_reauth:
        # The saved credentials just logged in, so they are not stale after all.
        _write_connection_state(user_id, {"needs_reauth": False})
    return {"courses": courses}


@router.get("/links")
def list_links(user_id: str, request: Request, semester: str | None = None):
    """List all sapling-course → gradescope-course mappings for user_id.

    The table keys on `enrollment_id` (0027) while the API keeps the abstract
    `sapling_course_id`, so each row is mapped back out to its course before it
    leaves — the frontend contract is unchanged.
    """
    require_self(user_id, request)
    return {"links": course_links(user_id, semester)}


@router.post("/link")
def upsert_link(body: LinkBody, request: Request):
    """Create or replace the link between a Sapling course and a Gradescope course."""
    require_self(body.user_id, request)
    try:
        link = link_course(body.user_id, body.sapling_course_id, body.gradescope_course_id, body.semester)
    except GradescopeLinkError as e:
        raise _link_http_error(e)
    return {"link": link}


@router.delete("/link/{sapling_course_id}")
def remove_link(sapling_course_id: str, user_id: str, request: Request, semester: str | None = None):
    """Remove the Gradescope link for a Sapling course (one semester's, when given)."""
    require_self(user_id, request)
    # Without a semester, across ALL the user's enrollments in the course: a
    # link created under a previous term must still be removable once the term
    # has rolled over. With one, only that term's enrollment. Either way a
    # delete that removed nothing is a 404, never ok:true — answering success
    # while deleting nothing is the #265 review bug.
    all_enrollments = _all_enrollments_for(user_id, sapling_course_id, semester)
    deleted = []
    if all_enrollments:
        deleted = table("gradescope_course_links").delete(
            filters={"enrollment_id": f"in.({','.join(all_enrollments)})"}
        )
    if not deleted:
        raise HTTPException(status_code=404, detail="No Gradescope link found for this course")
    return {"ok": True}


# ── Sync ───────────────────────────────────────────────────────────────────


@router.post("/sync/{sapling_course_id}")
def sync_course(sapling_course_id: str, user_id: str, request: Request, semester: str | None = None) -> dict[str, Any]:
    """Pull assignments from the linked Gradescope course and upsert into the Sapling gradebook."""
    require_self(user_id, request)
    _enforce_gs_rate_limit(user_id, "sync", limit=10, window_sec=300)
    try:
        gs_course_id, enrollment_id, link_id = linked_course(user_id, sapling_course_id, semester)
    except GradescopeLinkError as e:
        raise _link_http_error(e)

    # #116: `jobs_queue` on -> the login, scrape and gradebook writes below run
    # in the worker (services/gradescope/jobs.py) and this request waits for
    # the outcome, answering exactly as below (202 when it outlasts the wait).
    # None -> sync here after all.
    if gradescope_jobs.should_queue(user_id):
        queued = sync_via_queue(
            user_id=user_id, enrollment_id=enrollment_id, link_id=link_id,
            gradescope_course_id=gs_course_id,
        )
        if queued is not None:
            return queued
    return _sync_linked_course(user_id, gs_course_id, enrollment_id, link_id)


@router.get("/sync/{sapling_course_id}/status")
def sync_status(sapling_course_id: str, user_id: str, request: Request, semester: str | None = None):
    """The latest queued sync of this course (#116, `jobs_queue` on): 202
    while it runs, then exactly what POST /sync would have answered (the
    counts, or the same typed error). The client polls it after a POST that
    answered 202 / 504. 404 when the course has no staged sync."""
    require_self(user_id, request)
    all_enrollments = _all_enrollments_for(user_id, sapling_course_id, semester)
    if not all_enrollments:
        raise HTTPException(status_code=404, detail="Sapling course not found for user")
    answer = status_response(gradescope_jobs.latest_sync(user_id, all_enrollments))
    if answer is None:
        raise HTTPException(status_code=404, detail="No Gradescope sync found for this course")
    return answer


#: The 502 detail when no assignment could be saved.
SYNC_WRITE_FAILED_DETAIL = "No assignments could be saved. Please retry; if this continues, contact support."


def _sync_linked_course(user_id: str, gs_course_id: str, enrollment_id: str, link_id: str | None) -> dict[str, Any] | JSONResponse:
    """The inline sync: run it and answer with its outcome (the counts, a
    typed JSONResponse, or a raised HTTPException)."""
    return response_for_outcome(
        _run_linked_sync(user_id, gs_course_id, enrollment_id, link_id))


# ── Sync answers: outcome -> HTTP (#118: moved from services/gradescope_jobs.py) ──


def response_for_outcome(outcome: gradescope_jobs.SyncOutcome):
    """The sync route's answer for an outcome: the counts JSON, the typed
    JSONResponse (404 not connected / 409 reauth), or the HTTPException the
    inline route raises. The inline route (flag off) answers through this
    too, so the two paths cannot drift."""
    gj = gradescope_jobs
    code = outcome.error_code
    if code is None:
        counts = outcome.counts or {}
        return SyncResult(**{k: int(counts.get(k) or 0) for k in gj.COUNT_KEYS}).model_dump()
    if code == gj.ERR_NOT_CONNECTED:
        return _not_connected()
    if code == gj.ERR_AUTH:
        return _gs_error(409, GS_REAUTH_REQUIRED, outcome.message or gj._REAUTH_MESSAGE)
    if code == gj.ERR_FETCH:
        detail = outcome.message if outcome.message is not None else gj._FETCH_MESSAGE
        raise HTTPException(status_code=502, detail=detail)
    if code == gj.ERR_WRITE:
        raise HTTPException(status_code=502, detail=SYNC_WRITE_FAILED_DETAIL)
    if code == gj.ERR_CREDS:
        raise HTTPException(status_code=500, detail=gj._CREDS_MESSAGE)
    if code == gj.ERR_CREDS_INCOMPLETE:
        raise HTTPException(status_code=500, detail=gj._CREDS_INCOMPLETE_MESSAGE)
    if code == gj.ERR_LINK_CHANGED:
        raise HTTPException(status_code=400, detail=gj.NO_LINK_MESSAGE)
    if code == gj.ERR_INTERNAL:
        raise HTTPException(status_code=500, detail=gj._INTERNAL_MESSAGE)
    raise HTTPException(status_code=502, detail=gj._FAILED_MESSAGE)


def pending_response(row: dict):
    """202: the sync is still running; poll the status route."""
    return JSONResponse(status_code=202, content={
        "pending": True, "sync_id": str(row.get("id") or ""),
        "stage": row.get("stage") or gradescope_jobs.QUEUED, "detail": gradescope_jobs.TIMEOUT_MESSAGE,
    })


def response_for(answer: gradescope_jobs.SyncOutcome | gradescope_jobs.Watch):
    """The route's answer for an outcome, or for how a watch ended (pending:
    202, timeout: 504)."""
    if isinstance(answer, gradescope_jobs.SyncOutcome):
        return response_for_outcome(answer)
    if answer.kind == gradescope_jobs.PENDING:
        return pending_response(answer.row or {})
    raise HTTPException(status_code=504, detail=gradescope_jobs.TIMEOUT_MESSAGE)


def sync_via_queue(*, user_id: str, enrollment_id: str, link_id: str | None,
                   gradescope_course_id: str):
    """POST /sync through the queue (services/gradescope/jobs.py::queue_sync).
    Returns what the route returns (or raises the HTTPException it would
    raise), or None when staging failed and the caller must sync inline."""
    answer = gradescope_jobs.queue_sync(
        user_id=user_id, enrollment_id=enrollment_id, link_id=link_id,
        gradescope_course_id=gradescope_course_id)
    return None if answer is None else response_for(answer)


def status_response(row: dict | None):
    """GET /sync/{course}/status's answer for the latest staged sync: as the
    POST would have answered it, 202 while it runs, None when none (404)."""
    answer = gradescope_jobs.status_outcome(row)
    return None if answer is None else response_for(answer)


_LINK_STATUS = {CourseNotFound: 404, NoCourseLink: 400, AmbiguousEnrollment: 409, AmbiguousLink: 409}


def _link_http_error(e: GradescopeLinkError) -> HTTPException:
    """The HTTPException a link error answered with before the split (#118)."""
    return HTTPException(status_code=domain_status(e, _LINK_STATUS), detail=e.detail)
