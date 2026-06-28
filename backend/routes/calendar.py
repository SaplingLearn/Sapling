"""
backend/routes/calendar.py

Syllabus extraction, assignment CRUD, Google Calendar OAuth and sync.
Migrated from SQLite to Supabase REST API.
"""

import json
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi import Request as FastAPIRequest

from config import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    FRONTEND_URL,
)
from db.connection import table
from models import SaveAssignmentsBody, StudyBlockBody, ExportBody, SyncBody
from services import academics
from services.auth_guard import require_self, get_session_user_id
from services.calendar_service import extract_assignments_from_file, insert_new_assignments
from services.encryption import encrypt, encrypt_if_present, decrypt, decrypt_if_present
from services.request_context import current_request_id

try:
    from google_auth_oauthlib.flow import Flow
    from googleapiclient.discovery import build
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False

router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_refreshed_credentials(token_row: dict) -> "Credentials":
    creds = Credentials(
        token=decrypt(token_row["access_token"]),
        refresh_token=decrypt(token_row["refresh_token"]),
        client_id=GOOGLE_CLIENT_ID,
        client_secret=GOOGLE_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
    )

    needs_refresh = False
    if token_row.get("expires_at"):
        try:
            expiry = datetime.fromisoformat(token_row["expires_at"])
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if (expiry - datetime.now(timezone.utc)).total_seconds() < 300:
                needs_refresh = True
        except ValueError:
            needs_refresh = True
    else:
        needs_refresh = True

    if needs_refresh and creds.refresh_token:
        creds.refresh(Request())
        table("oauth_tokens").update(
            {
                "access_token": encrypt(creds.token),
                "expires_at": creds.expiry.isoformat() if creds.expiry else "",
            },
            filters={"user_id": f"eq.{token_row['user_id']}"},
        )

    return creds


def _require_google_creds(user_id: str) -> "Credentials":
    if not GOOGLE_AVAILABLE or not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=400, detail="Google Calendar not configured")
    token_rows = table("oauth_tokens").select(
        "user_id,access_token,refresh_token,expires_at",
        filters={"user_id": f"eq.{user_id}"},
    )
    if not token_rows:
        raise HTTPException(
            status_code=401,
            detail="Not connected to Google Calendar. Visit /api/calendar/auth-url?user_id=<id> to connect.",
        )
    return _get_refreshed_credentials(token_rows[0])


def _course_meta_cached(offering_id, cache):
    if not offering_id:
        return {}
    if offering_id not in cache:
        course_id = academics.offering_course_id(offering_id)
        course = {}
        if course_id:
            rows = table("courses").select(
                "id,course_code,course_name",
                filters={"id": f"eq.{course_id}"}, limit=1,
            )
            course = rows[0] if rows else {}
        cache[offering_id] = {
            "course_id": course_id,
            "course_code": course.get("course_code"),
            "course_name": course.get("course_name"),
        }
    return cache[offering_id]


def _owned_enrollment_ids(user_id) -> set:
    return {e["id"] for e in academics.user_enrollment_ids(user_id)}


def _read_assignments(user_id, *, due_gte=None, limit=None):
    enrollments = academics.user_enrollment_ids(user_id)
    if not enrollments:
        return []
    offering_by_enrollment = {e["id"]: e.get("offering_id") for e in enrollments}
    ids = ",".join(offering_by_enrollment.keys())
    filters = {"enrollment_id": f"in.({ids})"}
    if due_gte:
        filters["due_date"] = f"gte.{due_gte}"
    rows = table("assignments").select(
        "id,enrollment_id,title,due_date,assignment_type,notes,google_event_id,source",
        filters=filters, order="due_date.asc", limit=limit,
    )
    cache = {}
    out = []
    for r in rows:
        meta = _course_meta_cached(offering_by_enrollment.get(r.get("enrollment_id")), cache)
        out.append({
            "id": r["id"],
            "user_id": user_id,
            "title": r["title"],
            "due_date": r["due_date"],
            "assignment_type": r.get("assignment_type"),
            "notes": decrypt_if_present(r.get("notes")),
            "google_event_id": r.get("google_event_id"),
            "course_id": meta.get("course_id"),
            "course_code": meta.get("course_code") or "",
            "course_name": meta.get("course_name") or "",
        })
    return out


# ── Syllabus extraction ───────────────────────────────────────────────────────

@router.post("/extract")
async def extract(request: FastAPIRequest, file: UploadFile = File(...), user_id: str = Form(None)):
    if user_id:
        require_self(user_id, request)
    else:
        user_id = get_session_user_id(request)
    file_bytes = await file.read()
    filename = file.filename or "upload"
    content_type = file.content_type or "application/octet-stream"
    request_id = (
        getattr(request.state, "request_id", None)
        or current_request_id()
        or ""
    )
    try:
        result = await extract_assignments_from_file(
            file_bytes, filename, content_type,
            user_id=user_id or "",
            request_id=request_id,
        )
        return result
    except Exception as e:
        return {"error": str(e), "assignments": [], "warnings": [str(e)]}


# ── Assignment CRUD ───────────────────────────────────────────────────────────

@router.post("/save")
def save_assignments(body: SaveAssignmentsBody, request: FastAPIRequest):
    require_self(body.user_id, request)
    payload = [
        {
            "title": a.title,
            "course_id": a.course_id,
            "due_date": a.due_date,
            "assignment_type": a.assignment_type,
            "notes": a.notes,  # raw; insert_new_assignments encrypts
        }
        for a in body.assignments
    ]
    saved = insert_new_assignments(body.user_id, payload, source="manual")
    return {"saved_count": saved}


@router.get("/upcoming/{user_id}")
def get_upcoming(user_id: str, request: FastAPIRequest):
    require_self(user_id, request)
    today = datetime.utcnow().strftime("%Y-%m-%d")
    return {"assignments": _read_assignments(user_id, due_gte=today, limit=20)}


@router.get("/all/{user_id}")
def get_all_assignments(user_id: str, request: FastAPIRequest):
    """Return all assignments for a user (past and future) for the calendar view."""
    require_self(user_id, request)
    return {"assignments": _read_assignments(user_id)}


@router.patch("/assignments/{assignment_id}")
def update_assignment(assignment_id: str, body: dict, request: FastAPIRequest):
    user_id = body.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    require_self(user_id, request)

    owned = _owned_enrollment_ids(user_id)
    if not owned:
        raise HTTPException(status_code=404, detail="Assignment not found")
    existing = table("assignments").select(
        "id",
        filters={"id": f"eq.{assignment_id}", "enrollment_id": f"in.({','.join(owned)})"},
        limit=1,
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Assignment not found")

    ALLOWED = {"title", "due_date", "assignment_type"}  # course_id no longer settable here
    patch = {k: v for k, v in body.items() if k in ALLOWED}
    if not patch:
        return {"updated": False}
    table("assignments").update(
        patch, filters={"id": f"eq.{assignment_id}", "enrollment_id": f"in.({','.join(owned)})"}
    )
    return {"updated": True}


@router.delete("/assignments/{assignment_id}")
def delete_assignment(assignment_id: str, request: FastAPIRequest, user_id: str = Query(...)):
    require_self(user_id, request)
    owned = _owned_enrollment_ids(user_id)
    if not owned:
        raise HTTPException(status_code=404, detail="Assignment not found")
    existing = table("assignments").select(
        "id",
        filters={"id": f"eq.{assignment_id}", "enrollment_id": f"in.({','.join(owned)})"},
        limit=1,
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Assignment not found")
    table("assignments").delete(
        filters={"id": f"eq.{assignment_id}", "enrollment_id": f"in.({','.join(owned)})"}
    )
    return {"deleted": True}


@router.post("/suggest-study-blocks")
def suggest_study_blocks(body: StudyBlockBody, request: FastAPIRequest):
    require_self(body.user_id, request)
    today = datetime.utcnow().strftime("%Y-%m-%d")
    assignments = _read_assignments(body.user_id, due_gte=today)
    blocks = []
    for a in assignments:
        cc = a.get("course_code") or ""
        cn = a.get("course_name") or ""
        course_label = f"[{cc}] " if cc else (f"{cn}: " if cn else "")
        blocks.append({
            "topic": f"{course_label}{a['title']}" if course_label else a["title"],
            "suggested_date": a["due_date"],
            "duration_minutes": 60,
            "reason": f"Due {a['due_date']}",
            "related_assignment_id": a["id"],
        })
    return {"study_blocks": blocks[:5]}


@router.get("/status/{user_id}")
def calendar_status(user_id: str, request: FastAPIRequest):
    require_self(user_id, request)
    rows = table("oauth_tokens").select(
        "access_token,expires_at",
        filters={"user_id": f"eq.{user_id}"},
    )
    if not rows or not rows[0].get("access_token"):
        return {"connected": False}
    return {"connected": True, "expires_at": rows[0]["expires_at"]}


@router.delete("/disconnect/{user_id}")
def disconnect(user_id: str, request: FastAPIRequest):
    require_self(user_id, request)
    table("oauth_tokens").delete({"user_id": f"eq.{user_id}"})
    return {"disconnected": True}


# ── Google Calendar import ────────────────────────────────────────────────────

@router.get("/import/{user_id}")
def import_from_google(
    user_id: str,
    request: FastAPIRequest,
    max_results: int = Query(50, ge=1, le=250),
    days_ahead: int = Query(30, ge=1, le=365),
):
    require_self(user_id, request)
    creds = _require_google_creds(user_id)
    service = build("calendar", "v3", credentials=creds)
    now = datetime.now(timezone.utc)
    result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=(now + timedelta(days=days_ahead)).isoformat(),
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    events = []
    for item in result.get("items", []):
        start = item.get("start", {})
        end = item.get("end", {})
        events.append({
            "google_event_id": item.get("id"),
            "title": item.get("summary", "(No title)"),
            "description": item.get("description", ""),
            "start_date": start.get("date") or start.get("dateTime", "")[:10],
            "end_date": end.get("date") or end.get("dateTime", "")[:10],
            "start_datetime": start.get("dateTime"),
            "end_datetime": end.get("dateTime"),
            "all_day": "date" in start,
            "html_link": item.get("htmlLink"),
            "location": item.get("location", ""),
        })
    return {"events": events, "count": len(events)}


# ── Sync (push all unsynced assignments to Google) ────────────────────────────

@router.post("/sync")
def sync_to_google(body: SyncBody, request: FastAPIRequest):
    require_self(body.user_id, request)
    creds = _require_google_creds(body.user_id)
    service = build("calendar", "v3", credentials=creds)

    unsynced = table("assignments").select(
        "id,title,due_date,notes,google_event_id,courses!left(course_code,course_name)",
        filters={
            "user_id": f"eq.{body.user_id}",
            "google_event_id": "is.null",
        },
    )
    # Also catch empty-string google_event_id
    unsynced += table("assignments").select(
        "id,title,due_date,notes,google_event_id,courses!left(course_code,course_name)",
        filters={
            "user_id": f"eq.{body.user_id}",
            "google_event_id": "eq.",
        },
    )

    synced = 0
    for a in unsynced:
        if not a.get("due_date"):
            continue

        course = a.get("courses", {}) if isinstance(a.get("courses"), dict) else {}
        course_code = course.get("course_code") or ""
        course_name = course.get("course_name") or ""
        course_label = f"[{course_code}] " if course_code else (f"{course_name}: " if course_name else "")

        event = {
            "summary": f"{course_label}{a['title']}" if course_label else a["title"],
            "description": decrypt_if_present(a.get("notes")) or "",
            "start": {"date": a["due_date"]},
            "end": {"date": a["due_date"]},
        }
        created = service.events().insert(calendarId="primary", body=event).execute()
        # Scope the write-back by user_id too (defense in depth), matching export.
        table("assignments").update(
            {"google_event_id": created["id"]},
            filters={"id": f"eq.{a['id']}", "user_id": f"eq.{body.user_id}"},
        )
        synced += 1

    return {"synced_count": synced}


# ── Export (push selected assignments to Google) ──────────────────────────────

@router.post("/export")
def export_to_google(body: ExportBody, request: FastAPIRequest):
    require_self(body.user_id, request)
    creds = _require_google_creds(body.user_id)
    service = build("calendar", "v3", credentials=creds)

    exported = 0
    skipped = 0
    for aid in body.assignment_ids:
        # #123: scope by user_id, not just id. Without this an authenticated
        # caller could pass another user's assignment UUIDs to read+decrypt
        # their private notes, push them into the caller's calendar, and stamp
        # google_event_id onto the victim's row. Every sibling endpoint
        # (update/delete/sync) already scopes by user_id; a non-owned id now
        # returns no row and is skipped.
        rows = table("assignments").select(
            "id,title,due_date,notes,google_event_id,courses!left(course_code,course_name)",
            filters={"id": f"eq.{aid}", "user_id": f"eq.{body.user_id}"},
        )
        if not rows:
            continue
        a = rows[0]

        if a.get("google_event_id"):
            skipped += 1
            continue

        course = a.get("courses", {}) if isinstance(a.get("courses"), dict) else {}
        course_code = course.get("course_code") or ""
        course_name = course.get("course_name") or ""
        course_label = f"[{course_code}] " if course_code else (f"{course_name}: " if course_name else "")

        event = {
            "summary": f"{course_label}{a['title']}" if course_label else a["title"],
            "description": decrypt_if_present(a.get("notes")) or "",
            "start": {"date": a["due_date"]},
            "end": {"date": a["due_date"]},
        }
        created = service.events().insert(calendarId="primary", body=event).execute()
        # Scope the write-back by user_id too (defense in depth): never stamp
        # google_event_id onto a row the caller doesn't own.
        table("assignments").update(
            {"google_event_id": created["id"]},
            filters={"id": f"eq.{aid}", "user_id": f"eq.{body.user_id}"},
        )
        exported += 1

    return {"exported_count": exported, "skipped_count": skipped}
