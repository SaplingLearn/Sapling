"""Wipe one account's study data, keeping the account itself (admin tools).

`wipe_account_data(user_id)` deletes the "account data" set named in
docs/superpowers/specs/2026-11-08-admin-account-tools-design.md ("Wipe scope")
and resets the gamification counters. It never deletes the `users` row.

Deleted (directly, or through the FK cascades noted):

* enrollments → gradebook_categories, assignments, gradescope_course_links,
  topic_checklists (→ topic_checklist_progress), gradescope_syncs
* documents — chunks withdrawn FIRST via `chunk_visibility.withdraw_document_chunks`,
  then any private `course_chunks` still carrying `uploader_id = user`
* notes → note_concepts
* flashcards
* sessions → messages (feedback.session_id is SET NULL; feedback is kept)
* study_guides
* quiz_attempts → quiz_responses
* quiz_context
* graph_nodes → graph_edges, node_mastery_events, note_concepts
* xp_events, user_achievements
* document_uploads, tutor_pending_sessions (in-flight work, never bundled)

Kept: users row, user_profiles, user_settings (its `featured_achievement_ids`
is emptied, since every achievement it named is gone), user_roles,
oauth_tokens, gradescope_credentials, user_cosmetics, social (rooms,
friendships, …), feedback, issue_reports, events, llm_usage, admin_audit_log,
and class-wide aggregates (offering_concept_stats).

Not atomic — PostgREST has no transactions. Each step selects the ids it is
about to delete and deletes exactly those, in bounded batches, so the counts
are exact and the URLs stay short. Re-running after a mid-way failure
converges; a second run on a wiped account deletes nothing and returns zeros.

No per-process cache keys on any of this data (the academics/course-context/
growth caches hold immutable or class-wide mappings; the consent/account-state/
roles caches read tables the wipe keeps), so there is nothing to invalidate.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from db.connection import page_all, pg_quote_value, table
from services import chunk_visibility

logger = logging.getLogger(__name__)

#: Ids per `in.(…)` delete. Ids are short (uuid text / sha256 hex), so 100
#: quoted ids keep a DELETE URL around 4–7 KB.
_BATCH = 100

#: Tables wiped by `user_id` AFTER enrollments and documents, in order, with
#: the column that identifies one row of the user's. Order is for FK safety and
#: readability: nothing here blocks another (every cross-reference among them
#: is CASCADE or SET NULL), but children go before the parents they point at
#: so no cascade is relied on where a direct delete is cheap (quiz rows before
#: the graph nodes they reference; notes before graph nodes, both of which
#: cascade note_concepts).
_USER_TABLES: tuple[tuple[str, str], ...] = (
    ("notes", "id"),
    ("flashcards", "id"),
    ("sessions", "id"),
    ("study_guides", "id"),
    ("quiz_attempts", "id"),
    ("quiz_context", "id"),
    ("graph_nodes", "id"),
    ("xp_events", "id"),
    ("user_achievements", "achievement_id"),
    # #116 staged uploads (the queued pipeline's transient rows). Wiped, never
    # copied: a staged upload is in-flight work, not account data — a finished
    # one is already a `documents` row, which the bundle copies.
    ("document_uploads", "id"),
    # #117 tutor sessions not yet started, and end/delete tombstones (flag
    # stateless_tutor_sessions). Transient like document_uploads: wiped, never
    # copied — a session someone chats in is a `sessions` row.
    ("tutor_pending_sessions", "session_id"),
)

#: Every table the wipe deletes from directly.
WIPED_DIRECTLY: frozenset[str] = frozenset(
    ("enrollments", "documents", *(name for name, _ in _USER_TABLES)),
)

#: Tables the wipe empties through an ON DELETE CASCADE, child -> parent (the
#: parent is itself wiped directly or by cascade). The FKs are pinned against
#: the migrations by tests/test_account_wipe.py.
WIPED_BY_CASCADE: dict[str, str] = {
    "gradebook_categories": "enrollments",
    "assignments": "enrollments",
    "gradescope_course_links": "enrollments",
    "gradescope_syncs": "enrollments",  # #116 queued-sync bookkeeping
    "topic_checklists": "enrollments",
    "topic_checklist_progress": "topic_checklists",
    "graph_edges": "graph_nodes",
    "node_mastery_events": "graph_nodes",
    "note_concepts": "notes",
    "messages": "sessions",
    "quiz_responses": "quiz_attempts",
}


def wiped_tables() -> frozenset[str]:
    """Every per-user table `wipe_account_data` empties, directly or by cascade."""
    return WIPED_DIRECTLY | frozenset(WIPED_BY_CASCADE)


#: The `users` gamification counters and their column defaults
#: (20260731193214_gamification.sql; streak_count from the baseline).
#: `last_active_date` goes too: `touch_streak` treats "last active today" as
#: already counted, so a zeroed streak beside today's date would stay 0 for
#: the rest of the day.
_COUNTER_RESET = {
    "total_xp": 0,
    "level": 1,
    "streak_count": 0,
    "longest_streak": 0,
    "last_active_date": None,
}


class AccountWipeIncomplete(RuntimeError):
    """A step could not finish; re-running the wipe resumes from where it stopped."""


def _in_list(values: list[str]) -> str:
    return f"in.({','.join(pg_quote_value(str(v)) for v in values)})"


def _owned_keys(name: str, user_id: str, key: str = "id", extra: dict | None = None) -> list[str]:
    filters = {"user_id": f"eq.{user_id}", **(extra or {})}
    return [r[key] for r in page_all(table(name), key, filters=filters, order=key)
            if r.get(key) is not None]


def _delete_keys(name: str, keys: list[str], *, key: str = "id",
                 owner_col: str | None = "user_id", owner: str | None = None) -> int:
    """Delete exactly `keys` from `name` in batches. With `owner_col`, the
    delete is also scoped to that owner, so a stale id can never reach another
    account's row."""
    for i in range(0, len(keys), _BATCH):
        filters = {key: _in_list(keys[i : i + _BATCH])}
        if owner_col and owner is not None:
            filters[owner_col] = f"eq.{owner}"
        table(name).delete(filters=filters)
    return len(keys)


def _delete_owned(name: str, user_id: str, key: str = "id") -> int:
    return _delete_keys(name, _owned_keys(name, user_id, key), key=key, owner=user_id)


def _wipe_documents(user_id: str) -> dict[str, int]:
    """Withdraw every document's chunks, then delete the documents.

    Every live document is soft-deleted (`deleted_at`) BEFORE any withdrawal:
    `withdraw_document_chunks` keeps a chunk (and the user's contributor row)
    while another LIVE document still produces it, so withdrawing one by one
    over still-live siblings would leave the shared text this account
    contributed through two of its own uploads in the class pool. Already
    soft-deleted documents are withdrawn again too (idempotent) — their
    original withdrawal may have failed.

    A failed withdrawal stops the wipe before any document is hard-deleted:
    the source ledger names the document, and keeping the (soft-deleted) row
    is what lets a re-run finish the job.
    """
    doc_ids = _owned_keys("documents", user_id)
    counts = {"documents": 0, "course_chunks": 0, "course_chunk_contributors": 0}
    if doc_ids:
        table("documents").update(
            {"deleted_at": datetime.now(timezone.utc).isoformat()},
            filters={"user_id": f"eq.{user_id}", "deleted_at": "is.null"},
            prefer_return_minimal=True,
        )
        failed: list[str] = []
        for doc_id in doc_ids:
            out = chunk_visibility.withdraw_document_chunks(doc_id, user_id) or {}
            if out.get("failed"):
                failed.append(doc_id)
                continue
            counts["course_chunks"] += int(out.get("chunks_deleted") or 0)
            counts["course_chunk_contributors"] += int(out.get("contributors_removed") or 0)
        if failed:
            raise AccountWipeIncomplete(
                f"chunk withdrawal failed for {len(failed)} document(s) of {user_id}; "
                "they are soft-deleted and kept so a re-run can finish"
            )
        counts["documents"] = _delete_keys("documents", doc_ids, owner=user_id)

    # Private rows that still name this uploader: written before the source
    # ledger existed under a doc_id that no longer matches, or by a lost ledger
    # write. Private rows are never another student's, so they go. Shared rows
    # carrying this uploader_id are jointly owned (uploader_id names only the
    # last writer of a deduped row) and are the withdrawal's business, not ours.
    orphans = [
        r["id"] for r in page_all(
            table("course_chunks"), "id,category",
            filters={"uploader_id": f"eq.{user_id}", "visibility": "eq.private"},
            order="id",
        )
        if r.get("id") and r.get("category") != "catalog"
    ]
    counts["course_chunks"] += _delete_keys(
        "course_chunks", orphans, owner_col="uploader_id", owner=user_id,
    )
    return counts


def wipe_account_data(user_id: str) -> dict[str, int]:
    """Delete `user_id`'s account data and reset its counters; keep the account.

    Returns rows deleted per table (directly issued deletes only; FK cascades
    such as assignments or messages are not counted). Raises `ValueError` for
    a blank id and `AccountWipeIncomplete` when a chunk withdrawal failed.
    """
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("wipe_account_data needs a non-empty user_id")

    counts: dict[str, int] = {}
    # Enrollments first: enrollments.user_id has no ON DELETE, and its
    # dependants (gradebook, assignments, gradescope links, topic checklists)
    # all cascade from it. syllabus_doc_id → documents is SET NULL, so this
    # order also never leaves an enrollment pointing at a deleted document.
    counts["enrollments"] = _delete_owned("enrollments", user_id)
    counts.update(_wipe_documents(user_id))
    for name, key in _USER_TABLES:
        counts[name] = _delete_owned(name, user_id, key)

    table("users").update(
        dict(_COUNTER_RESET), filters={"id": f"eq.{user_id}"}, prefer_return_minimal=True,
    )
    table("user_settings").update(
        {"featured_achievement_ids": []},
        filters={"user_id": f"eq.{user_id}"}, prefer_return_minimal=True,
    )

    logger.info(
        "[account-wipe] wiped %s: %s row(s) deleted (%s)", user_id, sum(counts.values()),
        ", ".join(f"{k}={v}" for k, v in counts.items() if v) or "nothing to delete",
    )
    return counts
