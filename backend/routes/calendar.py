"""
backend/routes/calendar.py

Syllabus extraction, assignment CRUD, Google Calendar OAuth and sync.
Migrated from SQLite to Supabase REST API.
"""

import json
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from config import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    FRONTEND_URL,
)
from db.connection import table
from models import SaveAssignmentsBody, StudyBlockBody, ExportBody, SyncBody
from services.calendar_service import extract_assignments_from_file, insert_new_assignments

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
        token=token_row["access_token"],
        refresh_token=token_row["refresh_token"],
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
                "access_token": creds.token,
                "expires_at": creds.expiry.isoformat() if creds.expiry else "",
            },
            filters={"user_id": f"eq.{token_row['user_id']}"},
        )

    return creds


def _require_google_creds(user_id: str) -> "Credentials":
    if not GOOGLE_AVAILABLE or not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=400, detail="Google Calendar not configured")
    token_rows = table("oauth_tokens").select("*", filters={"user_id": f"eq.{user_id}"})
    if not token_rows:
        raise HTTPException(
            status_code=401,
            detail="Not connected to Google Calendar. Visit /api/calendar/auth-url?user_id=<id> to connect.",
        )
    return _get_refreshed_credentials(token_rows[0])


# ── Syllabus extraction ───────────────────────────────────────────────────────

@router.post("/extract")
async def extract(file: UploadFile = File(...), user_id: str = Form(None)):
    file_bytes = await file.read()
    filename = file.filename or "upload"
    content_type = file.content_type or "application/octet-stream"
    try:
        result = extract_assignments_from_file(file_bytes, filename, content_type)
        return result
    except Exception as e:
        return {"error": str(e), "assignments": [], "warnings": [str(e)]}


# ── Assignment CRUD ───────────────────────────────────────────────────────────

@router.post("/save")
def save_assignments(body: SaveAssignmentsBody):
    payload = [
        {
            "title": a.title,
            "course_id": a.course_id,
            "due_date": a.due_date,
            "assignment_type": a.assignment_type,
            "notes": a.notes,
        }
        for a in body.assignments
    ]
    saved = insert_new_assignments(body.user_id, payload)
    return {"saved_count": saved}


@router.get("/upcoming/{user_id}")
def get_upcoming(user_id: str):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    # Join with courses to get course_code and course_name
    rows = table("assignments").select(
        "*,courses!inner(course_code,course_name)",
        filters={"user_id": f"eq.{user_id}", "due_date": f"gte.{today}"},
        order="due_date.asc",
        limit=20,
    )
    # Transform to include course info at top level
    assignments = []
    for r in rows:
        course = r.get("courses", {}) if isinstance(r.get("courses"), dict) else {}
        assignments.append({
            "id": r["id"],
            "user_id": r["user_id"],
            "title": r["title"],
            "due_date": r["due_date"],
            "assignment_type": r.get("assignment_type"),
            "notes": r.get("notes"),
            "google_event_id": r.get("google_event_id"),
            "course_id": r.get("course_id"),
            "course_code": course.get("course_code", ""),
            "course_name": course.get("course_name", ""),
        })
    return {"assignments": assignments}


@router.get("/all/{user_id}")
def get_all_assignments(user_id: str):
    """Return all assignments for a user (past and future) for the calendar view."""
    # Join with courses to get course_code and course_name
    rows = table("assignments").select(
        "*,courses!inner(course_code,course_name)",
        filters={"user_id": f"eq.{user_id}"},
        order="due_date.asc",
    )
    # Transform to include course info at top level
    assignments = []
    for r in rows:
        course = r.get("courses", {}) if isinstance(r.get("courses"), dict) else {}
        assignments.append({
            "id": r["id"],
            "user_id": r["user_id"],
            "title": r["title"],
            "due_date": r["due_date"],
            "assignment_type": r.get("assignment_type"),
            "notes": r.get("notes"),
            "google_event_id": r.get("google_event_id"),
            "course_id": r.get("course_id"),
            "course_code": course.get("course_code", ""),
            "course_name": course.get("course_name", ""),
        })
    return {"assignments": assignments}


@router.post("/suggest-study-blocks")
def suggest_study_blocks(body: StudyBlockBody):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    assignments = table("assignments").select(
        "*,courses!inner(course_code,course_name)",
        filters={"user_id": f"eq.{body.user_id}", "due_date": f"gte.{today}"},
        order="due_date.asc",
    )
    blocks = []
    for a in assignments:
        course = a.get("courses", {}) if isinstance(a.get("courses"), dict) else {}
        course_label = f"[{course.get('course_code', '')}] " if course.get('course_code') else ""
        blocks.append({
            "topic": a["title"],
            "suggested_date": a["due_date"],
            "duration_minutes": 60,
            "reason": f"Due {a['due_date']}",
            "related_assignment_id": a["id"],
        })
    return {"study_blocks": blocks[:5]}


@router.get("/status/{user_id}")
def calendar_status(user_id: str):
    rows = table("oauth_tokens").select(
        "access_token,expires_at", filters={"user_id": f"eq.{user_id}"}
    )
    if not rows or not rows[0]["access_token"]:
        return {"connected": False}
    return {"connected": True, "expires_at": rows[0]["expires_at"]}


@router.delete("/disconnect/{user_id}")
def disconnect(user_id: str):
    table("oauth_tokens").delete({"user_id": f"eq.{user_id}"})
    return {"disconnected": True}


# ── Google Calendar import ────────────────────────────────────────────────────

@router.get("/import/{user_id}")
def import_from_google(
    user_id: str,
    max_results: int = Query(50, ge=1, le=250),
    days_ahead: int = Query(30, ge=1, le=365),
):
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
def sync_to_google(body: SyncBody):
    creds = _require_google_creds(body.user_id)
    service = build("calendar", "v3", credentials=creds)

    unsynced = table("assignments").select(
        "*,courses!inner(course_code,course_name)",
        filters={
            "user_id": f"eq.{body.user_id}",
            "google_event_id": "is.null",
        },
    )
    # Also catch empty-string google_event_id
    unsynced += table("assignments").select(
        "*,courses!inner(course_code,course_name)",
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
        course_code = course.get("course_code", "")
        course_name = course.get("course_name", "")
        course_label = f"[{course_code}] " if course_code else ""
        
        event = {
            "summary": f"{course_label}{a['title']}" if course_label else a["title"],
            "description": a.get("notes") or "",
            "start": {"date": a["due_date"]},
            "end": {"date": a["due_date"]},
        }
        created = service.events().insert(calendarId="primary", body=event).execute()
        table("assignments").update(
            {"google_event_id": created["id"]},
            filters={"id": f"eq.{a['id']}"},
        )
        synced += 1

    return {"synced_count": synced}


# ── Export (push selected assignments to Google) ──────────────────────────────

@router.post("/export")
def export_to_google(body: ExportBody):
    creds = _require_google_creds(body.user_id)
    service = build("calendar", "v3", credentials=creds)

    exported = 0
    skipped = 0
    for aid in body.assignment_ids:
        rows = table("assignments").select("*,courses!inner(course_code,course_name)", filters={"id": f"eq.{aid}"})
        if not rows:
            continue
        a = rows[0]

        if a.get("google_event_id"):
            skipped += 1
            continue

        course = a.get("courses", {}) if isinstance(a.get("courses"), dict) else {}
        course_code = course.get("course_code", "")
        course_name = course.get("course_name", "")
        course_label = f"[{course_code}] " if course_code else ""

        event = {
            "summary": f"{course_label}{a['title']}" if course_label else a["title"],
            "description": a.get("notes") or "",
            "start": {"date": a["due_date"]},
            "end": {"date": a["due_date"]},
        }
        created = service.events().insert(calendarId="primary", body=event).execute()
        table("assignments").update(
            {"google_event_id": created["id"]},
            filters={"id": f"eq.{aid}"},
        )
        exported += 1

    return {"exported_count": exported, "skipped_count": skipped}
