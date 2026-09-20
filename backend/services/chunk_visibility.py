"""Who may retrieve a `course_chunks` row (#629).

`user_settings.share_class_context` (migration 0037) is the persisted Class
Intel opt-out. It was enforced at exactly one write chokepoint — the
class-aggregate rollup in `course_context_service` — and nowhere in RAG, so an
opted-out student's upload still landed in the shared course pool and still
surfaced in a classmate's tutor.

Three pieces close that, and they are here rather than in `rag_service`
because `rag_service` is the embed/persist layer: it should be told what
visibility to write, not work it out.

**The contributor ledger is the load-bearing part.** Chunk ids are
content-addressed per course (`rag_service.chunk_id`), so identical text from
two uploaders is ONE row and `uploader_id` names only whoever uploaded last.
Without a ledger, "make my chunks private" is unanswerable: the column cannot
say whether a student contributed a row they are not the last writer of.
`course_chunk_contributors` records every uploader of a shared row, and a
shared row stays shared while at least one contributor is still opted in.

**Private rows deliberately have no contributor row.** An opted-out upload is
hashed into a private id namespace keyed on its uploader, so exactly one user
can ever own it and `uploader_id` is exact for those rows. Keeping them out of
the ledger is also what makes the resync below safe: it walks contributor rows,
so it only ever reconsiders SHARED-namespace ids. Flipping a private-namespace
row to `shared` would be wrong — its id can never merge with the shared row
for the same text, so the pool would hold two rows for one passage.

The consequence, recorded deliberately: a student who uploads while opted out
and later opts back in does NOT retroactively share those uploads. Re-sharing
them means re-indexing under the shared id (`scripts/backfill_document_chunks.py`),
not a metadata flip. That asymmetry fails in the safe direction — private
stays private — which is the right default for a privacy control.
"""
import logging
from collections.abc import Iterable

from db.connection import page_all, table

logger = logging.getLogger(__name__)

#: `course_chunks.visibility`. Mirrors the CHECK constraint in the migration.
SHARED = "shared"
PRIVATE = "private"

#: Ids per `in.(…)` filter. PostgREST takes the filter in the query string, so
#: an unbounded list becomes an unbounded URL; a student with thousands of
#: chunks would blow past the server's request-line limit and the write would
#: fail as a whole rather than page.
_ID_BATCH = 200


def shares_class_context(user_id: str) -> bool:
    """The uploader's STORED opt-in, as RAG indexing must read it.

    A missing `user_settings` row counts as opted IN, matching 0037's
    ``DEFAULT true`` and the class-aggregate filter — only an explicit
    ``false`` opts a student out.

    A read FAILURE counts as opted out. That is deliberately not the column
    default: falling back to "opted in" would publish an opted-out student's
    upload to their whole class because PostgREST blipped for one request, and
    a content-addressed shared row cannot be un-published by re-running the
    upload. Erring private costs that student some corpus reach and nothing
    else, and `resync_user_chunk_visibility` repairs it the next time the
    toggle moves.
    """
    try:
        rows = table("user_settings").select(
            "share_class_context",
            filters={"user_id": f"eq.{user_id}"},
            limit=1,
        )
    except Exception:
        logger.warning(
            "[RAG] share_class_context read failed for user %s — indexing "
            "this upload as PRIVATE (fail closed, #629)",
            user_id, exc_info=True,
        )
        return False
    if not rows:
        return True
    return rows[0].get("share_class_context") is not False


def visibility_for(user_id: str) -> str:
    """`SHARED` or `PRIVATE` for a new upload by `user_id`."""
    return SHARED if shares_class_context(user_id) else PRIVATE


def record_contributors(chunk_ids: Iterable[str], user_id: str) -> None:
    """Record `user_id` as a contributor of each SHARED chunk id.

    Best-effort: the chunks themselves are already upserted by the time this
    runs, and losing a ledger row must not undo that. The cost of a lost row
    is that this student's later opt-out will not flip that chunk private —
    which is why the failure is logged rather than swallowed.
    """
    ids = [c for c in dict.fromkeys(chunk_ids) if c]
    if not ids:
        return
    rows = [{"chunk_id": cid, "user_id": user_id} for cid in ids]
    try:
        for i in range(0, len(rows), _ID_BATCH):
            table("course_chunk_contributors").upsert(
                rows[i : i + _ID_BATCH], on_conflict="chunk_id,user_id"
            )
    except Exception:
        logger.warning(
            "[RAG] could not record %s contributor row(s) for user %s — a "
            "later opt-out will not flip those chunks private (#629)",
            len(rows), user_id, exc_info=True,
        )


def _share_flags(user_ids: Iterable[str]) -> dict[str, bool]:
    """Stored `share_class_context` per user id, defaulting to opted in.

    Only an explicit ``false`` opts out, so users with no row are simply
    absent from the result and every caller must treat absence as True.
    """
    ids = [u for u in dict.fromkeys(user_ids) if u]
    if not ids:
        return {}
    flags: dict[str, bool] = {}
    for i in range(0, len(ids), _ID_BATCH):
        batch = ids[i : i + _ID_BATCH]
        rows = table("user_settings").select(
            "user_id,share_class_context",
            filters={"user_id": f"in.({','.join(batch)})"},
        )
        for row in rows or []:
            flags[row["user_id"]] = row.get("share_class_context") is not False
    return flags


def resync_user_chunk_visibility(user_id: str) -> dict:
    """Recompute `visibility` on every shared-namespace chunk `user_id` fed.

    Runs when the Class Intel toggle moves (`PATCH /api/profile/{id}/settings`).
    A chunk is `shared` while at least one of its contributors is opted in, and
    `private` once none are — at which point it stays retrievable for its
    contributors through `match_course_chunks`' contributor clause and for
    nobody else.

    Returns a counts dict so the caller can log what moved.
    """
    contributed = [
        r["chunk_id"]
        for r in page_all(
            table("course_chunk_contributors"),
            "chunk_id",
            filters={"user_id": f"eq.{user_id}"},
            order="chunk_id",
        )
        if r.get("chunk_id")
    ]
    chunk_ids = list(dict.fromkeys(contributed))
    if not chunk_ids:
        return {"to_private": 0, "to_shared": 0, "considered": 0}

    # Every contributor of those chunks, not just this user: the rule is "any
    # opted-in contributor keeps it shared", so the other uploaders' flags
    # decide the outcome as much as this one's.
    contributors: dict[str, set[str]] = {}
    for i in range(0, len(chunk_ids), _ID_BATCH):
        batch = chunk_ids[i : i + _ID_BATCH]
        rows = table("course_chunk_contributors").select(
            "chunk_id,user_id",
            filters={"chunk_id": f"in.({','.join(batch)})"},
        )
        for row in rows or []:
            contributors.setdefault(row["chunk_id"], set()).add(row["user_id"])

    flags = _share_flags({u for users in contributors.values() for u in users})

    current: dict[str, str] = {}
    for i in range(0, len(chunk_ids), _ID_BATCH):
        batch = chunk_ids[i : i + _ID_BATCH]
        rows = table("course_chunks").select(
            "id,visibility", filters={"id": f"in.({','.join(batch)})"},
        )
        for row in rows or []:
            current[row["id"]] = row.get("visibility") or SHARED

    to_private: list[str] = []
    to_shared: list[str] = []
    for cid in chunk_ids:
        if cid not in current:
            continue
        users = contributors.get(cid) or {user_id}
        desired = SHARED if any(flags.get(u, True) for u in users) else PRIVATE
        if current[cid] == desired:
            continue
        (to_private if desired == PRIVATE else to_shared).append(cid)

    for ids, desired in ((to_private, PRIVATE), (to_shared, SHARED)):
        for i in range(0, len(ids), _ID_BATCH):
            batch = ids[i : i + _ID_BATCH]
            table("course_chunks").update(
                {"visibility": desired},
                filters={"id": f"in.({','.join(batch)})"},
                prefer_return_minimal=True,
            )

    if to_private or to_shared:
        logger.info(
            "[RAG] resynced chunk visibility for user %s: %s -> private, "
            "%s -> shared (of %s contributed)",
            user_id, len(to_private), len(to_shared), len(chunk_ids),
        )
    return {
        "to_private": len(to_private),
        "to_shared": len(to_shared),
        "considered": len(chunk_ids),
    }
