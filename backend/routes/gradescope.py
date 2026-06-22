"""
backend/routes/gradescope.py

Per-user Gradescope sync. Stores email/password encrypted at rest, logs in
fresh on each call (no persisted session), and upserts grades into the
existing assignments table keyed on `gradescope_assignment_id`.

Endpoints (mounted under /api/gradescope):
- POST   /credentials                  Test login then save encrypted creds
- DELETE /credentials                  Remove creds
- GET    /status                       Has creds? last_synced_at?
- GET    /courses                      List the user's Gradescope student courses
- GET    /links                        List sapling-course -> gradescope-course mappings
- POST   /link                         Create/update a mapping
- DELETE /link/{sapling_course_id}     Remove a mapping
- POST   /sync/{sapling_course_id}     Pull assignments, upsert grades
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from gradescopeapi.classes.connection import GSConnection
from pydantic import BaseModel, Field

from db.connection import table
from services import gradescope_service
from services.auth_guard import require_self
from services.encryption import encrypt, decrypt, encrypt_if_present
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


def _load_creds(user_id: str) -> StoredCreds | None:
    """Fetch and decrypt stored Gradescope credentials for user_id. Returns None if none saved."""
    rows = table("gradescope_credentials").select(
        "auth_mode,email_encrypted,password_encrypted,cookies_encrypted",
        filters={"user_id": f"eq.{user_id}"},
        limit=1,
    )
    if not rows:
        return None
    row = rows[0]
    mode: AuthMode = row.get("auth_mode") or "password"
    try:
        if mode == "password":
            return StoredCreds(
                auth_mode="password",
                email=decrypt(row["email_encrypted"]) if row.get("email_encrypted") else None,
                password=decrypt(row["password_encrypted"]) if row.get("password_encrypted") else None,
            )
        else:  # cookies
            raw = decrypt(row["cookies_encrypted"]) if row.get("cookies_encrypted") else None
            payload = json.loads(raw) if raw else {}
            return StoredCreds(
                auth_mode="cookies",
                gradescope_session=payload.get("_gradescope_session"),
                signed_token=payload.get("signed_token"),
            )
    except Exception as e:
        logger.exception("Failed to decrypt Gradescope creds")
        raise HTTPException(
            status_code=500, detail=f"Stored credentials unreadable: {e}"
        ) from e


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


def _user_owns_course(user_id: str, sapling_course_id: str) -> bool:
    """Return True if user_id is enrolled in sapling_course_id."""
    rows = table("user_courses").select(
        "id",
        filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{sapling_course_id}"},
        limit=1,
    )
    return bool(rows)


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
        # main.py's HTTPException handler drops exc.headers, so the retry budget
        # rides in the detail string rather than a Retry-After header.
        raise HTTPException(
            status_code=429,
            detail=f"Too many Gradescope {action} requests. Retry in {retry}s.",
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
            gradescope_service.login(body.email, body.password)
        except gradescope_service.GradescopeAuthError as e:
            raise HTTPException(status_code=401, detail=str(e))
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
            gradescope_service.login_with_cookies(
                signed_token=body.signed_token,
                gradescope_session=body.gradescope_session,
            )
        except gradescope_service.GradescopeAuthError as e:
            raise HTTPException(status_code=401, detail=str(e))
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

    now_iso = datetime.now(timezone.utc).isoformat()
    payload["updated_at"] = now_iso
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
    require_self(body.user_id, request)
    # Strictest cap: each call launches a Chromium that pins a worker thread for
    # up to duo_timeout_seconds and fires a Duo push at the user's phone.
    _enforce_gs_rate_limit(body.user_id, "bu-sso", limit=3, window_sec=600)

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
        raise HTTPException(status_code=401, detail=str(e) or "Gradescope auth failed.")
    except Exception as e:
        # Never let a blank `crashed:` reach the client again — surface
        # type, message, and a request id so the user can paste a useful
        # error.
        logger.exception("Unexpected error in BU SSO flow")
        msg = str(e) or repr(e) or "no message"
        raise HTTPException(
            status_code=500,
            detail=f"SSO flow crashed: {type(e).__name__}: {msg}",
        )

    cookie_blob = json.dumps({
        "_gradescope_session": cookies.get("_gradescope_session"),
        "signed_token": cookies.get("signed_token") or None,
    })
    now_iso = datetime.now(timezone.utc).isoformat()
    table("gradescope_credentials").upsert(
        {
            "user_id": body.user_id,
            "auth_mode": "cookies",
            "email_encrypted": None,
            "password_encrypted": None,
            "cookies_encrypted": encrypt(cookie_blob),
            "updated_at": now_iso,
        },
        on_conflict="user_id",
    )
    return {"ok": True}


@router.delete("/credentials")
def delete_credentials(user_id: str, request: Request):
    """Remove stored Gradescope credentials for user_id."""
    require_self(user_id, request)
    table("gradescope_credentials").delete(filters={"user_id": f"eq.{user_id}"})
    return {"ok": True}


@router.get("/status")
def get_status(user_id: str, request: Request):
    """Return whether the user has saved credentials and when they last synced."""
    require_self(user_id, request)
    rows = table("gradescope_credentials").select(
        "auth_mode,last_synced_at,updated_at",
        filters={"user_id": f"eq.{user_id}"},
        limit=1,
    )
    if not rows:
        return {"has_credentials": False, "auth_mode": None, "last_synced_at": None}
    return {
        "has_credentials": True,
        "auth_mode": rows[0].get("auth_mode") or "password",
        "last_synced_at": rows[0].get("last_synced_at"),
        "credentials_updated_at": rows[0].get("updated_at"),
    }


# ── Course listing + linking ───────────────────────────────────────────────


@router.get("/courses")
def list_gradescope_courses(user_id: str, request: Request):
    """Hit Gradescope live with the saved creds, list student-role courses."""
    require_self(user_id, request)
    _enforce_gs_rate_limit(user_id, "courses", limit=10, window_sec=300)
    creds = _load_creds(user_id)
    if not creds:
        raise HTTPException(status_code=404, detail="No Gradescope credentials saved")
    try:
        conn = _establish_connection(creds)
        courses = gradescope_service.list_student_courses(conn)
    except gradescope_service.GradescopeAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except gradescope_service.GradescopeFetchError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"courses": courses}


@router.get("/links")
def list_links(user_id: str, request: Request):
    """List all sapling-course → gradescope-course mappings for user_id."""
    require_self(user_id, request)
    rows = table("gradescope_course_links").select(
        "id,sapling_course_id,gradescope_course_id,last_synced_at",
        filters={"user_id": f"eq.{user_id}"},
    )
    return {"links": rows}


@router.post("/link")
def upsert_link(body: LinkBody, request: Request):
    """Create or replace the link between a Sapling course and a Gradescope course."""
    require_self(body.user_id, request)
    if not _user_owns_course(body.user_id, body.sapling_course_id):
        raise HTTPException(status_code=404, detail="Sapling course not found for user")

    # Manual upsert: delete any existing link for this (user, sapling_course) then insert.
    table("gradescope_course_links").delete(
        filters={
            "user_id": f"eq.{body.user_id}",
            "sapling_course_id": f"eq.{body.sapling_course_id}",
        }
    )
    inserted = table("gradescope_course_links").insert({
        "user_id": body.user_id,
        "sapling_course_id": body.sapling_course_id,
        "gradescope_course_id": body.gradescope_course_id,
    })
    return {"link": inserted[0] if inserted else None}


@router.delete("/link/{sapling_course_id}")
def remove_link(sapling_course_id: str, user_id: str, request: Request):
    """Remove the Gradescope link for a Sapling course."""
    require_self(user_id, request)
    table("gradescope_course_links").delete(
        filters={
            "user_id": f"eq.{user_id}",
            "sapling_course_id": f"eq.{sapling_course_id}",
        }
    )
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
def sync_course(sapling_course_id: str, user_id: str, request: Request) -> dict[str, Any]:
    """Pull assignments from the linked Gradescope course and upsert into the Sapling gradebook."""
    require_self(user_id, request)
    _enforce_gs_rate_limit(user_id, "sync", limit=10, window_sec=300)
    if not _user_owns_course(user_id, sapling_course_id):
        raise HTTPException(status_code=404, detail="Sapling course not found for user")

    link_rows = table("gradescope_course_links").select(
        "id,gradescope_course_id",
        filters={
            "user_id": f"eq.{user_id}",
            "sapling_course_id": f"eq.{sapling_course_id}",
        },
        limit=1,
    )
    if not link_rows:
        raise HTTPException(
            status_code=400,
            detail="No Gradescope course is linked to this Sapling course",
        )
    gs_course_id = link_rows[0]["gradescope_course_id"]

    creds = _load_creds(user_id)
    if not creds:
        raise HTTPException(status_code=404, detail="No Gradescope credentials saved")

    try:
        conn = _establish_connection(creds)
        gs_assignments = gradescope_service.list_assignments(conn, gs_course_id)
    except gradescope_service.GradescopeAuthError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except gradescope_service.GradescopeFetchError as e:
        raise HTTPException(status_code=502, detail=str(e))

    # Load existing assignments keyed by gradescope_assignment_id so we
    # know whether each incoming one is an insert or an update.
    existing = table("assignments").select(
        "id,gradescope_assignment_id",
        filters={
            "user_id": f"eq.{user_id}",
            "course_id": f"eq.{sapling_course_id}",
        },
    )
    by_gs_id: dict[str, str] = {
        r["gradescope_assignment_id"]: r["id"]
        for r in existing
        if r.get("gradescope_assignment_id")
    }

    inserted = updated = skipped = failed = 0
    for a in gs_assignments:
        gs_id = a.get("id")
        if not gs_id:
            skipped += 1
            continue
        title = a.get("name") or "(untitled)"
        due_date = _due_to_date_string(a.get("due_date"))
        points_earned = a.get("points_earned")
        points_possible = a.get("points_possible")

        record_write: dict[str, Any] = {
            "title": title,
            "due_date": due_date,
            "points_earned": encrypt_if_present(points_earned),
            "points_possible": encrypt_if_present(points_possible),
            "source": "gradescope",
            "gradescope_assignment_id": gs_id,
        }
        try:
            if gs_id in by_gs_id:
                table("assignments").update(
                    record_write,
                    filters={"id": f"eq.{by_gs_id[gs_id]}"},
                )
                updated += 1
            else:
                table("assignments").insert({
                    "id": str(uuid.uuid4()),
                    "user_id": user_id,
                    "course_id": sapling_course_id,
                    "category_id": None,  # user can re-categorize later
                    **record_write,
                })
                inserted += 1
        except Exception:
            logger.exception("Failed to upsert Gradescope assignment %s", gs_id)
            failed += 1

    now_iso = datetime.now(timezone.utc).isoformat()
    table("gradescope_credentials").update(
        {"last_synced_at": now_iso},
        filters={"user_id": f"eq.{user_id}"},
    )
    table("gradescope_course_links").update(
        {"last_synced_at": now_iso},
        filters={
            "user_id": f"eq.{user_id}",
            "sapling_course_id": f"eq.{sapling_course_id}",
        },
    )

    return SyncResult(
        inserted=inserted, updated=updated, skipped=skipped, failed=failed
    ).model_dump()
