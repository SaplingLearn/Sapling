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
them means re-indexing under the shared id (`scripts/backfill_document_chunks.py
--doc <id>`), not a metadata flip. That asymmetry fails in the safe direction — private
stays private — which is the right default for a privacy control.

Two known costs of that remedy, unfixed here rather than unnoticed:

* Re-indexing does not delete the private row, so for its owner BOTH rows then
  match — the new one as `shared`, the old one through `uploader_id` — and
  `retrieve_chunks_detailed` does not dedupe on text. That student spends two
  retrieval slots on one passage until the private row is cleaned up. Dropping
  duplicate text at retrieval belongs with #634's ranking work, not here (and
  #484 encrypts `chunk_text`, which changes how such a comparison has to be
  written).
* Nothing re-drives an INDEXED document on its own: the indexing sweeper
  (#482) only takes documents that have not finished, and these finished fine
  under the private namespace. So the remedy is an operator action —
  `scripts/backfill_document_chunks.py --doc <id>` or
  `POST /api/admin/documents/{id}/reindex`, both of which force — not a
  background repair.
"""
import logging
from collections.abc import Iterable

from db.connection import page_all, pg_quote_value, table
from services.events_service import log_event

logger = logging.getLogger(__name__)

#: `course_chunks.visibility`. Mirrors the CHECK constraint in the migration.
SHARED = "shared"
PRIVATE = "private"

#: `documents.shareability` / the classifier's `shareability` field (#630).
#: Whose document this is, which is a different question from whether its owner
#: consents to sharing — completed homework must stay private even from a
#: student who has consented, because it was never the course's material to
#: share. Mirrored by a Literal in `agents/classifier.py`; the two are pinned
#: together by `tests/test_chunk_visibility.py`.
COURSE_MATERIAL = "course_material"
PERSONAL_NOTES = "personal_notes"
COMPLETED_WORK = "completed_work"
SHAREABILITY_VALUES = (COURSE_MATERIAL, PERSONAL_NOTES, COMPLETED_WORK)

#: Classifier self-reported confidence below which a document is not shared.
#:
#: A FLOOR AGAINST DRIFT, not a discriminator, and the measurement says so: over
#: the 29 documents in tests/evals/cassettes/document_classification the minimum
#: recorded confidence is 0.80 and nothing falls under 0.6, so on real input this
#: gate does not fire. It is here to catch a future prompt or model change that
#: starts producing hedged classifications, not to sort today's uploads.
#:
#: Know what it measures, because it is not quite the right thing: `confidence`
#: is the model's certainty about the classification as a whole, not about
#: `shareability` specifically. A document it is sure is course material but torn
#: between `slides` and `lecture_notes` reports a middling number and is withheld
#: (at INFO). Giving shareability its own confidence costs an output-schema slot
#: (#153's budget), so the mismatch is accepted and recorded; #641 owns turning
#: this into a measured decision-seam parameter.
MIN_SHARE_CONFIDENCE = 0.6

#: Ids per `in.(…)` filter. PostgREST takes the filter in the query string, so
#: an unbounded list becomes an unbounded URL and a student with thousands of
#: chunks would get a 414 instead of a paged read. 50 because these are quoted
#: 64-char sha256 ids: 50 of them is ~3.4 KB of query string, comfortably under
#: the 8 KB request-line default that usually sits in front of PostgREST, and it
#: matches the repo's existing precedent for hex-id `in.()` reads
#: (`scripts/dedupe_course_chunks.py`). 200 would have been ~13 KB.
_ID_BATCH = 50


def shares_class_context(user_id: str) -> bool:
    """The uploader's STORED opt-in, as RAG indexing must read it.

    A missing `user_settings` row counts as opted IN, matching 0037's
    ``DEFAULT true`` and the class-aggregate filter — only an explicit
    ``false`` opts a student out.

    A read FAILURE counts as opted out. That is deliberately not the column
    default: falling back to "opted in" would publish an opted-out student's
    upload to their whole class because PostgREST blipped for one request, and
    a content-addressed shared row cannot be un-published by re-running the
    upload.

    Be clear about the cost, because it is not self-repairing. A blip here
    indexes that upload into the PRIVATE id namespace with no ledger row, and
    `resync_user_chunk_visibility` walks the ledger — so no later toggle flip
    can ever bring those chunks back into the class pool. The only remedy is a
    re-index under the shared id (`scripts/backfill_document_chunks.py`, which
    resolves the flag again). That is still the right trade: one student's
    document is missing from the shared corpus until an operator re-indexes,
    versus another student's document published to a class that was told it
    would not be.
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


def decide_visibility(
    user_id: str,
    *,
    shareability: str | None,
    confidence: float | None,
) -> str:
    """Whether a new upload may join the shared course pool.

    Two independent gates, and BOTH must pass (#630 on top of #629):

    1. Is this document the course's to share? Only `course_material` is —
       `completed_work` is the student's own answers, and serving those to a
       classmate is an academic-integrity failure, not merely a privacy one.
       `personal_notes` is private by default.
    2. Does its uploader consent? That is `shares_class_context`.

    Every unknown answer resolves to PRIVATE: a missing `shareability` (what
    the output schema falls back to when the model omits the field), a missing
    or low `confidence`, or a value from outside `SHAREABILITY_VALUES` — an
    enum widened upstream must not arrive here as shareable by default.

    The asymmetry is the point. A wrongly-private chunk costs its owner some
    corpus reach and is repaired by a re-index; a wrongly-shared one has
    already been served to the class and cannot be recalled.
    """
    if shareability is None:
        logger.warning(
            "[RAG] classifier returned no shareability for an upload by %s — "
            "indexing PRIVATE (#630)", user_id,
        )
        return PRIVATE
    if shareability not in SHAREABILITY_VALUES:
        logger.warning(
            "[RAG] unknown shareability %r for an upload by %s — indexing "
            "PRIVATE (#630)", shareability, user_id,
        )
        return PRIVATE
    if shareability != COURSE_MATERIAL:
        return PRIVATE
    if confidence is None or confidence < MIN_SHARE_CONFIDENCE:
        logger.info(
            "[RAG] course_material at confidence %s is below the %s share "
            "floor — indexing PRIVATE (#630)", confidence, MIN_SHARE_CONFIDENCE,
        )
        return PRIVATE
    return visibility_for(user_id)


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


def _in_list(values: list[str]) -> str:
    """A PostgREST ``in.(…)`` operand list, each value quoted.

    Chunk ids are sha256 hex and safe by construction, but user ids are not
    ours to characterise — inside a logic list a bare value ends at the first
    comma or paren, so one unlucky id would silently reshape the filter into a
    different (wider or narrower) query rather than erroring. `pg_quote_value`
    is the repo's rule for any interpolated value; applied uniformly here so
    the two call sites cannot drift apart.
    """
    return f"in.({','.join(pg_quote_value(v) for v in values)})"


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
            filters={"user_id": _in_list(batch)},
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

    Returns a counts dict so the caller can log what moved. Raises nothing:
    every read below raises on a PostgREST error, and this runs as a
    post-response BackgroundTask where an exception would vanish — the student
    would see the toggle succeed while their uploads stayed in classmates'
    retrieval indefinitely. A failure is logged and counted
    (`rag.visibility_resync_failed`) so the gap is visible and an operator can
    re-run it; the function is idempotent, so re-running is always safe.
    """
    try:
        return _resync_user_chunk_visibility(user_id)
    except Exception as e:
        logger.error(
            "[RAG] chunk-visibility resync FAILED for user %s — their Class "
            "Intel setting is not yet reflected in course_chunks (#629)",
            user_id, exc_info=True,
        )
        log_event(
            "rag.visibility_resync_failed",
            category="error",
            user_id=user_id,
            payload={"error_type": type(e).__name__},
        )
        return {"to_private": 0, "to_shared": 0, "considered": 0, "failed": True}


def _resync_user_chunk_visibility(user_id: str) -> dict:
    """`resync_user_chunk_visibility` without the error boundary."""
    contributed = [
        r["chunk_id"]
        for r in page_all(
            table("course_chunk_contributors"),
            "chunk_id",
            filters={"user_id": f"eq.{user_id}"},
            # Total order, as `page_all` requires: the PK is
            # (chunk_id, user_id) and `user_id` is pinned by the filter, so
            # `chunk_id` alone is unique across this result set.
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
    #
    # PAGED, and that is load-bearing rather than tidiness. A popular chunk has
    # one ledger row per uploader, so a class of 60 students who all uploaded
    # the same slide deck puts ~60 rows behind every chunk id in the batch. A
    # plain `select` would hit PostgREST's `max_rows` cap, which answers 206 —
    # a 2xx, so `raise_for_status()` lets it through — and the chunks whose rows
    # fell off the end would look uncontributed. Privatising THOSE is not the
    # safe direction: it withdraws material 59 opted-in students legitimately
    # shared, from the whole class, on the strength of a truncated read.
    contributors: dict[str, set[str]] = {}
    for i in range(0, len(chunk_ids), _ID_BATCH):
        batch = chunk_ids[i : i + _ID_BATCH]
        for row in page_all(
            table("course_chunk_contributors"),
            "chunk_id,user_id",
            filters={"chunk_id": _in_list(batch)},
            # Total order: (chunk_id, user_id) is the primary key.
            order="chunk_id,user_id",
        ):
            contributors.setdefault(row["chunk_id"], set()).add(row["user_id"])

    flags = _share_flags({u for users in contributors.values() for u in users})

    current: dict[str, str] = {}
    for i in range(0, len(chunk_ids), _ID_BATCH):
        batch = chunk_ids[i : i + _ID_BATCH]
        rows = table("course_chunks").select(
            "id,visibility", filters={"id": _in_list(batch)},
        )
        for row in rows or []:
            current[row["id"]] = row.get("visibility") or SHARED

    to_private: list[str] = []
    to_shared: list[str] = []
    for cid in chunk_ids:
        if cid not in current:
            continue
        users = contributors.get(cid)
        if not users:
            # The id came OUT of this user's ledger rows, so a complete read
            # cannot return none for it: their own row was deleted between the
            # two reads. SKIP rather than assume sole ownership — assuming it
            # would privatise a chunk whose co-contributors we simply failed to
            # see, and the chunk is no longer this user's to withdraw anyway.
            logger.info(
                "[RAG] chunk %s lost its contributor rows mid-resync for user "
                "%s — leaving its visibility alone", cid, user_id,
            )
            continue
        desired = SHARED if any(flags.get(u, True) for u in users) else PRIVATE
        if current[cid] == desired:
            continue
        (to_private if desired == PRIVATE else to_shared).append(cid)

    for ids, desired in ((to_private, PRIVATE), (to_shared, SHARED)):
        for i in range(0, len(ids), _ID_BATCH):
            batch = ids[i : i + _ID_BATCH]
            table("course_chunks").update(
                {"visibility": desired},
                filters={"id": _in_list(batch)},
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
