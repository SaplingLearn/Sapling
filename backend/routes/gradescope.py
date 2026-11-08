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
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from gradescopeapi.classes.connection import GSConnection
from pydantic import BaseModel, Field

from db.connection import page_all, table
from services import gradescope_jobs, gradescope_service
from services.academics import (
    current_term,
    enrollment_id_for,
    offering_course_id,
    scoped_user_enrollments,
    term_id_for_label,
)
from services.auth_guard import require_self, guard_off_loop
from services.encryption import encrypt, decrypt, encrypt_if_present
from services.request_context import current_request_id
from services.request_limits import check_rate_limit

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Body models ────────────────────────────────────────────────────────────


AuthMode = Literal["password", "cookies"]


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


class StoredCreds(BaseModel):
    auth_mode: AuthMode
    email: str | None = None
    password: str | None = None
    gradescope_session: str | None = None
    signed_token: str | None = None
    # Row metadata, not secrets: which saved version these are (the guard for
    # marking them stale) and whether they were already known to be rejected.
    updated_at: str | None = None
    needs_reauth: bool = False


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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_connection_state(user_id: str, fields: dict[str, Any], *, only_version: str | None = None) -> None:
    """Persist connection/sync-outcome columns on the credentials row. Never
    raises: the state is bookkeeping, and a failed write must not turn a
    finished sync (or its real error) into a 500.

    ``only_version`` pins the write to the credential version that produced the
    outcome (``updated_at`` as read with the creds): marking credentials stale
    must not land on a newer set the user saved while this request was running.
    """
    filters = {"user_id": f"eq.{user_id}"}
    if only_version:
        filters["updated_at"] = f"eq.{only_version}"
    try:
        table("gradescope_credentials").update(fields, filters=filters)
    except Exception:
        logger.warning("Failed to record Gradescope connection state for user_id=%s", user_id, exc_info=True)


def _reauth_required(user_id: str, creds: StoredCreds, message: str, **outcome: Any) -> JSONResponse:
    """Stored credentials were rejected: mark them stale, answer 409."""
    _write_connection_state(user_id, {"needs_reauth": True, **outcome}, only_version=creds.updated_at)
    return _gs_error(409, GS_REAUTH_REQUIRED, message or "Gradescope rejected the saved credentials. Reconnect Gradescope.")


def _not_connected() -> JSONResponse:
    return _gs_error(404, GS_NOT_CONNECTED, "No Gradescope credentials saved")


def _load_creds(user_id: str) -> StoredCreds | None:
    """Fetch and decrypt stored Gradescope credentials for user_id. Returns None if none saved."""
    rows = table("gradescope_credentials").select(
        "auth_mode,email_encrypted,password_encrypted,cookies_encrypted,updated_at,needs_reauth",
        filters={"user_id": f"eq.{user_id}"},
        limit=1,
    )
    if not rows:
        return None
    row = rows[0]
    mode: AuthMode = row.get("auth_mode") or "password"
    meta = {"updated_at": row.get("updated_at"), "needs_reauth": bool(row.get("needs_reauth"))}
    try:
        if mode == "password":
            return StoredCreds(
                auth_mode="password",
                email=decrypt(row["email_encrypted"]) if row.get("email_encrypted") else None,
                password=decrypt(row["password_encrypted"]) if row.get("password_encrypted") else None,
                **meta,
            )
        else:  # cookies
            raw = decrypt(row["cookies_encrypted"]) if row.get("cookies_encrypted") else None
            payload = json.loads(raw) if raw else {}
            return StoredCreds(
                auth_mode="cookies",
                gradescope_session=payload.get("_gradescope_session"),
                signed_token=payload.get("signed_token"),
                **meta,
            )
    except Exception:
        logger.exception("Failed to decrypt Gradescope creds for user_id=%s", user_id)
        raise HTTPException(
            status_code=500, detail="Stored credentials could not be read."
        )


def _establish_connection(creds: StoredCreds) -> GSConnection:
    """Re-establish an authenticated Gradescope session from stored creds.
    Picks the right login path based on the user's chosen mode."""
    if creds.auth_mode == "password":
        if not creds.email or not creds.password:
            raise HTTPException(
                status_code=500, detail="Password-mode creds missing email/password"
            )
        return gradescope_service.login(creds.email, creds.password)
    else:
        return gradescope_service.login_with_cookies(
            signed_token=creds.signed_token,
            gradescope_session=creds.gradescope_session,
        )


def _enrollment_for(user_id: str, sapling_course_id: str) -> str | None:
    """Resolve (user, abstract course) → the user's enrollment id, or None.

    Doubles as the ownership check this module used to do against
    `user_courses` — a table that stopped existing when 0020 renamed it to
    `enrollments` (offering-keyed). No enrollment means the user isn't in the
    course, which is the same 404 the old check produced.

    Gradescope links key on `enrollment_id` (0027), not the abstract course:
    grades land on enrollment-scoped `assignments` (0021), so a link has to
    name the specific class instance the grades belong to — otherwise a retake
    gives two enrollments and the sync cannot tell which term's assignments to
    write. The HTTP boundary still speaks `course_id` per the repo convention;
    resolution happens here.
    """
    return enrollment_id_for(user_id, sapling_course_id)


def _enrollments_in(user_id: str, semester: str | None, sapling_course_id: str | None = None) -> list[dict]:
    """The user's enrollments ({id, offering_id}), optionally narrowed to a
    course and/or a semester label.

    An explicit semester that doesn't resolve to a term matches nothing — it
    never widens to every term.
    """
    term_id = None
    if semester is not None:
        term_id = term_id_for_label(semester)
        if not term_id:
            return []
    return scoped_user_enrollments(user_id, course_id=sapling_course_id, term_id=term_id)


def _all_enrollments_for(user_id: str, sapling_course_id: str, semester: str | None = None) -> list[str]:
    """Owned enrollments in this course, optionally restricted to a semester.

    An explicit term never falls back to a different enrollment. Without a
    term, search all enrollments so legacy links survive a term rollover.
    """
    return [e["id"] for e in _enrollments_in(user_id, semester, sapling_course_id)]


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
        payload: dict[str, Any] = {
            "user_id": body.user_id,
            "auth_mode": "password",
            "email_encrypted": encrypt(body.email),
            "password_encrypted": encrypt(body.password),
            "cookies_encrypted": None,
        }
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
        cookie_blob = json.dumps(
            {
                "_gradescope_session": body.gradescope_session,
                "signed_token": body.signed_token or None,
            }
        )
        payload = {
            "user_id": body.user_id,
            "auth_mode": "cookies",
            "email_encrypted": None,
            "password_encrypted": None,
            "cookies_encrypted": encrypt(cookie_blob),
        }

    payload["updated_at"] = _now_iso()
    # Fresh, verified credentials: whatever marked the old ones stale is moot.
    payload["needs_reauth"] = False
    payload["last_sync_error"] = None
    table("gradescope_credentials").upsert(payload, on_conflict="user_id")
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
    await asyncio.to_thread(_enforce_gs_rate_limit, body.user_id, "bu-sso",
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

    cookie_blob = json.dumps({
        "_gradescope_session": cookies.get("_gradescope_session"),
        "signed_token": cookies.get("signed_token") or None,
    })
    await asyncio.to_thread(  # #117: an async handler; keep the write off the loop
        table("gradescope_credentials").upsert,
        {
            "user_id": body.user_id,
            "auth_mode": "cookies",
            "email_encrypted": None,
            "password_encrypted": None,
            "cookies_encrypted": encrypt(cookie_blob),
            "updated_at": _now_iso(),
            "needs_reauth": False,
            "last_sync_error": None,
        },
        on_conflict="user_id",
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
    rows = table("gradescope_credentials").select(
        "auth_mode,last_synced_at,updated_at,needs_reauth,last_attempt_at,last_sync_error",
        filters={"user_id": f"eq.{user_id}"},
        limit=1,
    )
    if not rows:
        return {
            "state": "disconnected",
            "connected": False,
            "has_credentials": False,
            "needs_reauth": False,
            "auth_mode": None,
            "last_synced_at": None,
            "last_attempt_at": None,
            "last_sync_error": None,
        }
    row = rows[0]
    needs_reauth = bool(row.get("needs_reauth"))
    return {
        "state": "needs_reauth" if needs_reauth else "connected",
        "connected": not needs_reauth,
        "has_credentials": True,
        "needs_reauth": needs_reauth,
        "auth_mode": row.get("auth_mode") or "password",
        "last_synced_at": row.get("last_synced_at"),
        "last_attempt_at": row.get("last_attempt_at"),
        "last_sync_error": row.get("last_sync_error"),
        "credentials_updated_at": row.get("updated_at"),
    }


# ── Course listing + linking ───────────────────────────────────────────────


@router.get("/courses")
def list_gradescope_courses(user_id: str, request: Request):
    """Hit Gradescope live with the saved creds, list student-role courses."""
    require_self(user_id, request)
    _enforce_gs_rate_limit(user_id, "courses", limit=10, window_sec=300)
    creds = _load_creds(user_id)
    if not creds:
        return _not_connected()
    conn = None
    try:
        conn = _establish_connection(creds)
        courses = gradescope_service.list_student_courses(conn)
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
    enrollments = _enrollments_in(user_id, semester)
    if not enrollments:
        return {"links": []}

    course_by_enrollment = {
        e["id"]: offering_course_id(e.get("offering_id")) for e in enrollments
    }
    rows = table("gradescope_course_links").select(
        "id,enrollment_id,gradescope_course_id,last_synced_at",
        filters={"enrollment_id": f"in.({','.join(course_by_enrollment)})"},
    )
    links = [
        {
            "id": r["id"],
            "sapling_course_id": course_by_enrollment[r.get("enrollment_id")],
            "gradescope_course_id": r.get("gradescope_course_id"),
            "last_synced_at": r.get("last_synced_at"),
        }
        for r in rows
        # Drop rather than answer sapling_course_id: null — an offering whose
        # course can't be resolved has no id the client could act on, and a
        # null there reads as a real link the UI can't do anything with.
        if course_by_enrollment.get(r.get("enrollment_id"))
    ]
    return {"links": links}


@router.post("/link")
def upsert_link(body: LinkBody, request: Request):
    """Create or replace the link between a Sapling course and a Gradescope course."""
    require_self(body.user_id, request)
    scoped = _all_enrollments_for(body.user_id, body.sapling_course_id, body.semester)
    if body.semester is not None:
        if len(scoped) > 1:
            raise HTTPException(status_code=409, detail="Multiple enrollments match this semester. Contact support to resolve the course enrollment.")
        enrollment_id = scoped[0] if scoped else None
    else:
        enrollment_id = _enrollment_for(body.user_id, body.sapling_course_id)
    if not enrollment_id:
        raise HTTPException(status_code=404, detail="Sapling course not found for user")

    # Legacy callers replace the course's mapping across terms. Semester-aware
    # callers replace only that term, preserving mappings for other enrollments.
    all_enrollments = scoped
    if all_enrollments:
        table("gradescope_course_links").delete(
            filters={"enrollment_id": f"in.({','.join(all_enrollments)})"}
        )
    inserted = table("gradescope_course_links").insert({
        "enrollment_id": enrollment_id,
        "gradescope_course_id": body.gradescope_course_id,
    })
    link = dict(inserted[0]) if inserted else None
    if link is not None:
        # Answer in the API's vocabulary, not the table's.
        link["sapling_course_id"] = body.sapling_course_id
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


def _due_to_date_string(iso: str | None) -> str | None:
    """Sapling stores due_date as a date string (YYYY-MM-DD). Gradescope
    gives us a full ISO timestamp; pull just the date portion."""
    if not iso:
        return None
    try:
        return iso.split("T")[0] if "T" in iso else iso
    except Exception:
        return None


@router.post("/sync/{sapling_course_id}")
def sync_course(sapling_course_id: str, user_id: str, request: Request, semester: str | None = None) -> dict[str, Any]:
    """Pull assignments from the linked Gradescope course and upsert into the Sapling gradebook."""
    require_self(user_id, request)
    _enforce_gs_rate_limit(user_id, "sync", limit=10, window_sec=300)
    all_enrollments = _all_enrollments_for(user_id, sapling_course_id, semester)
    if not all_enrollments:
        raise HTTPException(status_code=404, detail="Sapling course not found for user")

    # Find the link across every enrollment in the course, then key the whole
    # sync on THAT row's enrollment — not on a re-derived term guess. The
    # grades belong to the class instance the link was made against, and after
    # a term rollover the heuristic points at a different one (#265 review).
    link_rows = table("gradescope_course_links").select(
        "id,enrollment_id,gradescope_course_id",
        filters={"enrollment_id": f"in.({','.join(all_enrollments)})"},
    )
    if not link_rows:
        raise HTTPException(
            status_code=400,
            detail="No Gradescope course is linked to this Sapling course",
        )
    if len(link_rows) > 1 and semester is None:
        # A retake leaves a link on each term's enrollment. A caller that names
        # no semester means the current one; only stay ambiguous when the
        # current term doesn't settle it.
        term = current_term()
        current = {
            e["id"]
            for e in scoped_user_enrollments(user_id, course_id=sapling_course_id, term_id=term["id"])
        } if term else set()
        link_rows = [r for r in link_rows if r.get("enrollment_id") in current] or link_rows
    if len(link_rows) != 1:
        raise HTTPException(status_code=409, detail="Multiple Gradescope links match this course. Select a semester and reconnect the course.")
    gs_course_id = link_rows[0]["gradescope_course_id"]
    enrollment_id = link_rows[0]["enrollment_id"]
    link_id = link_rows[0]["id"]

    # #116: `jobs_queue` on -> the login, scrape and gradebook writes below run
    # in the worker (services/gradescope_jobs.py) and this request waits for
    # the outcome, answering exactly as below (202 when it outlasts the wait).
    # None -> sync here after all.
    if gradescope_jobs.should_queue(user_id):
        queued = gradescope_jobs.sync_via_queue(
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
    answer = gradescope_jobs.status_response(
        gradescope_jobs.latest_sync(user_id, all_enrollments))
    if answer is None:
        raise HTTPException(status_code=404, detail="No Gradescope sync found for this course")
    return answer


#: The 502 detail when no assignment could be saved.
SYNC_WRITE_FAILED_DETAIL = "No assignments could be saved. Please retry; if this continues, contact support."


def _sync_linked_course(user_id: str, gs_course_id: str, enrollment_id: str, link_id: str | None) -> dict[str, Any] | JSONResponse:
    """The inline sync: run it and answer with its outcome (the counts, a
    typed JSONResponse, or a raised HTTPException)."""
    return gradescope_jobs.response_for_outcome(
        _run_linked_sync(user_id, gs_course_id, enrollment_id, link_id))


def _run_linked_sync(
    user_id: str, gs_course_id: str, enrollment_id: str, link_id: str | None,
    *, still_linked: Callable[[], bool] | None = None,
) -> gradescope_jobs.SyncOutcome:
    """Log in with the stored credentials, scrape the linked Gradescope course
    and upsert it into the enrollment's gradebook, recording the outcome on
    gradescope_credentials. Returns the typed outcome; raises only on an
    unexpected error. The request runs it inline; with `jobs_queue` on, the
    `gradescope.sync` worker runs it (services/gradescope_jobs.py), passing
    `still_linked`, checked right before the first write: False ends the
    sync as ``link_changed`` with nothing written."""
    Outcome = gradescope_jobs.SyncOutcome
    try:
        creds = _load_creds(user_id)
    except HTTPException:  # _load_creds' one raise: the stored row would not decrypt
        return Outcome.failed(gradescope_jobs.ERR_CREDS)
    if not creds:
        return Outcome.failed(gradescope_jobs.ERR_NOT_CONNECTED)
    if creds.auth_mode == "password" and not (creds.email and creds.password):
        # _establish_connection's own refusal, classified before the call.
        return Outcome.failed(gradescope_jobs.ERR_CREDS_INCOMPLETE)

    conn = None
    try:
        conn = _establish_connection(creds)
        gs_assignments = gradescope_service.list_assignments(conn, gs_course_id)
    except gradescope_service.GradescopeAuthError as e:
        # Stored credentials rejected: mark them stale (as _reauth_required does).
        _write_connection_state(
            user_id, {"needs_reauth": True, "last_sync_error": "auth_failed", "last_attempt_at": _now_iso()},
            only_version=creds.updated_at,
        )
        return Outcome.failed(gradescope_jobs.ERR_AUTH, str(e))
    except gradescope_service.GradescopeFetchError as e:
        # An outage says nothing about the credentials: needs_reauth untouched.
        _write_connection_state(user_id, {"last_sync_error": "fetch_failed", "last_attempt_at": _now_iso()})
        return Outcome.failed(gradescope_jobs.ERR_FETCH, str(e))
    finally:
        if conn is not None:
            conn.session.close()

    if still_linked is not None and not still_linked():
        return Outcome.failed(gradescope_jobs.ERR_LINK_CHANGED)

    # Load existing assignments keyed by gradescope_assignment_id so we
    # know whether each incoming one is an insert or an update.
    existing = page_all(
        table("assignments"),
        "id,gradescope_assignment_id",
        filters={"enrollment_id": f"eq.{enrollment_id}"},
        order="id",
    )
    by_gs_id: dict[str, str] = {
        r["gradescope_assignment_id"]: r["id"]
        for r in existing
        if r.get("gradescope_assignment_id")
    }

    # Build a normalized category-name → id map for auto-matching new assignments.
    # A new assignment whose title contains a category name (e.g. "Homework 3"
    # contains "homework") is automatically categorized; otherwise category_id
    # stays None and the user can link it manually.
    # 0021 renamed course_categories -> gradebook_categories, enrollment-keyed.
    cats = page_all(
        table("gradebook_categories"),
        "id,name",
        filters={"enrollment_id": f"eq.{enrollment_id}"},
        order="sort_order,id",
    )
    cats_by_name: dict[str, str] = {
        c["name"].lower().strip(): c["id"]
        for c in cats
        if c.get("name", "").strip() and c.get("id")
    }

    def _infer_category_id(title: str) -> str | None:
        t = title.lower()
        for name, cat_id in cats_by_name.items():
            if name in t:
                return cat_id
        return None

    inserted = updated = skipped = failed = 0
    # A scrape can repeat an assignment id; the first occurrence wins and the
    # rest are skipped rather than overwriting it as an "update".
    seen: set[str] = set()
    for a in gs_assignments:
        gs_id = a.get("id")
        if not gs_id or gs_id in seen:
            skipped += 1
            continue
        seen.add(gs_id)
        title = a.get("name") or "(untitled)"
        due_date = _due_to_date_string(a.get("due_date"))
        points_earned = a.get("points_earned")
        points_possible = a.get("points_possible")

        record_write: dict[str, Any] = {
            "title": title,
            "due_date": due_date,
            "source": "gradescope",
            "gradescope_assignment_id": gs_id,
        }
        # Only include grade fields when Gradescope returned a value —
        # absent grades (None) must not overwrite previously synced data.
        if points_earned is not None:
            record_write["points_earned"] = encrypt_if_present(points_earned)
        if points_possible is not None:
            record_write["points_possible"] = encrypt_if_present(points_possible)
        try:
            if gs_id in by_gs_id:
                table("assignments").update(
                    record_write,
                    filters={"id": f"eq.{by_gs_id[gs_id]}"},
                )
                updated += 1
            else:
                assignment_id = str(uuid.uuid4())
                table("assignments").insert({
                    "id": assignment_id,
                    "enrollment_id": enrollment_id,
                    "category_id": _infer_category_id(title),
                    **record_write,
                })
                by_gs_id[gs_id] = assignment_id
                inserted += 1
        except Exception:
            logger.exception("Failed to upsert Gradescope assignment %s", gs_id)
            failed += 1

    now_iso = _now_iso()
    # The login worked, so whatever the write outcome the credentials are good.
    outcome: dict[str, Any] = {"needs_reauth": False, "last_attempt_at": now_iso}
    if failed and not (inserted or updated):
        _write_connection_state(user_id, {**outcome, "last_sync_error": "write_failed"})
        return Outcome.failed(gradescope_jobs.ERR_WRITE)
    # last_synced_at represents a complete import, not a partial or failed one.
    if failed:
        _write_connection_state(user_id, {**outcome, "last_sync_error": "partial_write"})
    else:
        _write_connection_state(user_id, {**outcome, "last_sync_error": None, "last_synced_at": now_iso})
        table("gradescope_course_links").update(
            {"last_synced_at": now_iso}, filters={"id": f"eq.{link_id}"},
        )

    return Outcome.done(inserted=inserted, updated=updated, skipped=skipped, failed=failed)
