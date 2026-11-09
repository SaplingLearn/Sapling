"""
backend/services/gradescope/sync.py

The Gradescope sync body (#118, moved from routes/gradescope.py): log in with
the stored credentials, scrape the linked course, upsert it into the
enrollment's gradebook and record the outcome. The inline route and the
``gradescope.sync`` worker (services/gradescope/jobs.py) both run
``_run_linked_sync``.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Callable

from db.connection import page_all, table
from services.encryption import encrypt_if_present
from services.gradescope import client as gradescope_service
from services.gradescope import jobs as gradescope_jobs
from services.gradescope.credentials import (
    _establish_connection,
    _load_creds,
    _now_iso,
    _write_connection_state,
)
from services.gradescope.errors import GradescopeCredsError

logger = logging.getLogger(__name__)


def _due_to_date_string(iso: str | None) -> str | None:
    """Sapling stores due_date as a date string (YYYY-MM-DD). Gradescope
    gives us a full ISO timestamp; pull just the date portion."""
    if not iso:
        return None
    try:
        return iso.split("T")[0] if "T" in iso else iso
    except Exception:
        return None


def _run_linked_sync(
    user_id: str, gs_course_id: str, enrollment_id: str, link_id: str | None,
    *, still_linked: Callable[[], bool] | None = None,
) -> gradescope_jobs.SyncOutcome:
    """Log in with the stored credentials, scrape the linked Gradescope course
    and upsert it into the enrollment's gradebook, recording the outcome on
    gradescope_credentials. Returns the typed outcome; raises only on an
    unexpected error. The request runs it inline; with `jobs_queue` on, the
    `gradescope.sync` worker runs it (services/gradescope/jobs.py), passing
    `still_linked`, checked right before the first write: False ends the
    sync as ``link_changed`` with nothing written."""
    Outcome = gradescope_jobs.SyncOutcome
    try:
        creds = _load_creds(user_id)
    except GradescopeCredsError:  # _load_creds' one raise: the stored row would not decrypt
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
