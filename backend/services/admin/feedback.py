"""
backend/services/admin/feedback.py

Feedback + issue reports (#520). These tables are 🔒 at rest
(comment/topic/description); the Supabase dashboard shows ciphertext, so the
admin portal is the only human-readable surface.

Moved verbatim out of ``routes/admin.py`` (#118); the route keeps the
auth checks and maps ``services.admin.errors`` to HTTP statuses.
"""
from __future__ import annotations

from db.connection import table
from services.encryption import decrypt_if_present
from services.profiles import get_display_names


def list_feedback(limit: int = 200):
    rows = table("feedback").select(
        "id,user_id,type,rating,selected_options,comment,session_id,topic,created_at",
        order="created_at.desc",
        limit=max(1, min(int(limit), 500)),
    ) or []
    names = get_display_names([r["user_id"] for r in rows])
    for r in rows:
        r["comment"] = decrypt_if_present(r.get("comment"))
        r["topic"] = decrypt_if_present(r.get("topic"))
        r["user_name"] = names.get(r["user_id"], "")
    return {"feedback": rows}


def list_issue_reports(limit: int = 200):
    rows = table("issue_reports").select(
        "id,user_id,topic,description,screenshot_urls,created_at",
        order="created_at.desc",
        limit=max(1, min(int(limit), 500)),
    ) or []
    names = get_display_names([r["user_id"] for r in rows])
    for r in rows:
        r["topic"] = decrypt_if_present(r.get("topic"))
        r["description"] = decrypt_if_present(r.get("description"))
        r["user_name"] = names.get(r["user_id"], "")
    return {"reports": rows}
