"""
RAG retrieval service.

Embeds queries and documents with gemini-embedding-001 using the correct
task types (RETRIEVAL_QUERY for queries, RETRIEVAL_DOCUMENT for indexing),
then calls the match_course_chunks Supabase RPC for ANN retrieval.
"""
import hashlib
import json
import logging
import math
import os
from typing import NamedTuple

from google import genai
from google.genai import types as genai_types

from agents._providers import model_mode
from db.connection import rpc, table
from services.chunk_visibility import PRIVATE, SHARED, record_contributors
from services.encryption import decrypt_if_present, encrypt_if_present
from services.events_service import log_event

logger = logging.getLogger(__name__)

# Bound embedding requests so a stalled Gemini call can't hang quiz/tutor
# grounding indefinitely — retrieve_chunks() runs inline on the request path.
_HTTP_TIMEOUT_MS = 60_000
_EMBED_MODEL = "gemini-embedding-001"
_OUTPUT_DIM = 768

# `genai.Client(api_key="")` raises ValueError at construction, so a missing
# GEMINI_API_KEY would break `import main` (routes/quiz.py and routes/learn.py
# both pull this module in) if built eagerly. #439 goes further: the client is
# now built lazily, on first REAL-mode use. `_get_client()` is only ever
# reached from inside an `_embed_*` function AFTER its `model_mode() != "real"`
# gate below, so a non-real run (SAPLING_MODEL_MODE=function — the hermetic
# E2E default, ADR 0019) never constructs a genai.Client and never touches the
# network, instead of constructing one that then degrades by an accidental
# swallowed exception.
_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(
            api_key=os.getenv("GEMINI_API_KEY", "") or "dummy-key-for-import",
            http_options=genai_types.HttpOptions(timeout=_HTTP_TIMEOUT_MS),
        )
    return _client


class _EmbeddingDisabled(RuntimeError):
    """Raised by the `_embed_*` helpers when `SAPLING_MODEL_MODE != 'real'`.

    Every caller (`retrieve_chunks`, `index_document_chunks`) already wraps
    its embed call in a broad try/except — originally there to swallow a real
    Gemini failure so retrieval/upload degrade gracefully instead of 500ing.
    Raising here reuses that exact same degrade path, so function-mode
    behavior is byte-for-byte identical to what an unlucky real-mode failure
    already produced — except now it happens by design on every run, not by
    accident of a swallowed exception (#439).
    """


def _require_real_mode() -> None:
    if model_mode() != "real":
        raise _EmbeddingDisabled(
            "embedding skipped: SAPLING_MODEL_MODE != 'real' (below-seam RAG "
            "embed path, #439)"
        )


def _embed_query(text: str) -> list[float]:
    _require_real_mode()
    resp = _get_client().models.embed_content(
        model=_EMBED_MODEL,
        contents=[text],
        config=genai_types.EmbedContentConfig(
            output_dimensionality=_OUTPUT_DIM,
            task_type="RETRIEVAL_QUERY",
        ),
    )
    return list(resp.embeddings[0].values)


def _embed_document(text: str) -> list[float]:
    _require_real_mode()
    resp = _get_client().models.embed_content(
        model=_EMBED_MODEL,
        contents=[text],
        config=genai_types.EmbedContentConfig(
            output_dimensionality=_OUTPUT_DIM,
            task_type="RETRIEVAL_DOCUMENT",
        ),
    )
    return list(resp.embeddings[0].values)


def embed_document_text(text: str) -> list[float]:
    """Embed one document-side text (RETRIEVAL_DOCUMENT, 768-dim).

    The sanctioned entry point for the one below-seam embed consumer outside
    this module: ``course_relevance`` below, behind routes/documents.py's
    observe-only catalog-relevance score (#628). Routing it through here (lazy
    shared client with the dummy-key fallback, request timeout, and the #439
    real-mode gate) replaced a raw ``genai.Client`` built with an empty-string
    API-key fallback, whose keyless construction ``ValueError`` was swallowed
    into a silent no-index degrade (#413).
    """
    return _embed_document(text)


def parse_vector(value) -> list[float]:
    """A pgvector value as a list of floats, whatever shape it arrived in.

    PostgREST serialises a ``VECTOR`` column as its TEXT form — the JSON
    *string* ``"[0.012,-0.034,…]"``, not a JSON array — so an embedding read
    back through ``table(...).select("embedding")`` is a ``str``. Zipping
    floats against that string pairs each one with a single character, and
    ``float * str`` raises TypeError (#628). Lists pass through, so a freshly
    computed embedding and a stored one can be compared without caring which
    is which.
    """
    if isinstance(value, str):
        return [float(x) for x in json.loads(value)]
    return [float(x) for x in value]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    if not norm:
        return 0.0
    return sum(x * y for x, y in zip(a, b, strict=True)) / norm


def course_relevance(course_code: str, sample_text: str) -> float | None:
    """Cosine similarity of ``sample_text`` to the course's catalog embedding.

    ``None`` when the course has no catalog embedding to compare against (and
    no embed call is spent finding that out). Cosine, not a raw dot product:
    768-d ``gemini-embedding-001`` output is not unit-normalised, and
    ``match_course_chunks`` ranks on cosine (``<=>``), so this score sits on
    the same scale as retrieval's ``similarity``.

    Raises whatever the embed call raises (including ``_EmbeddingDisabled``
    outside real mode) — callers treat the score as advisory and decide what a
    failure means.
    """
    # Newest EMBEDDED row: ingest_catalog.py never deletes a superseded blurb,
    # and on a double embed failure it inserts rows with a NULL embedding.
    rows = table("course_chunks").select(
        "embedding",
        filters={
            "course_id": f"eq.{course_code}",
            "category": "eq.catalog",
            "embedding": "not.is.null",
        },
        order="created_at.desc,id",
        limit=1,
    )
    if not rows or not rows[0].get("embedding"):
        return None
    catalog_vec = parse_vector(rows[0]["embedding"])
    return _cosine_similarity(embed_document_text(sample_text), catalog_vec)


def _embed_documents_batch(texts: list[str]) -> list[list[float]]:
    _require_real_mode()
    resp = _get_client().models.embed_content(
        model=_EMBED_MODEL,
        contents=texts,
        config=genai_types.EmbedContentConfig(
            output_dimensionality=_OUTPUT_DIM,
            task_type="RETRIEVAL_DOCUMENT",
        ),
    )
    return [list(e.values) for e in resp.embeddings]


class Retrieval(NamedTuple):
    """What one retrieval produced, and whether it actually ran.

    `chunks` alone cannot answer that: [] is what "nothing relevant matched"
    returns AND what a failed or disabled retrieval degrades to. A caller that
    reports on grounding (quiz E8) has to tell those apart, or it ends up
    asserting "this course's material doesn't cover the concept" about a
    query that never reached the index.
    """

    #: The matched chunks, best-first. Empty on failure or when nothing
    #: matched. Deliberately has NO default: a `= []` on a NamedTuple field is
    #: evaluated once at class creation, so every no-arg `Retrieval()` would
    #: hand back the SAME list, and one caller mutating it in place would
    #: poison every future empty retrieval in the process.
    chunks: list[dict]
    #: True when retrieval RAISED. False for a clean empty result and for the
    #: #439 seam skip, which is a deliberate mode rather than a fault.
    failed: bool = False


def retrieve_chunks(
    query: str,
    course_id: str | None = None,
    k: int = 5,
    min_similarity: float = 0.55,
    user_id: str | None = None,
) -> list[dict]:
    """Return up to k chunks similar to query, optionally filtered by course_id.

    Each result: {"course_id": str, "chunk_text": str, "similarity": float}

    `user_id` names the READER (#629): the RPC returns shared rows plus the
    rows this reader uploaded or contributed to. Omitting it asks for shared
    rows only — the fail-closed default, so a caller that has not been threaded
    through under-retrieves rather than leaking a classmate's private upload.

    Callers that need to distinguish "nothing matched" from "retrieval broke"
    want `retrieve_chunks_detailed` instead; this stays the shape every
    grounding-is-best-effort caller already expects.
    """
    return retrieve_chunks_detailed(
        query, course_id, k, min_similarity, user_id
    ).chunks


def retrieve_chunks_detailed(
    query: str,
    course_id: str | None = None,
    k: int = 5,
    min_similarity: float = 0.55,
    user_id: str | None = None,
) -> Retrieval:
    """`retrieve_chunks`, plus whether the empty result is a fault or a fact."""
    try:
        embedding = _embed_query(query)
        params: dict = {
            "query_embedding": embedding,
            "match_count": k,
            "filter_course_id": course_id,
            "filter_user_id": user_id,
        }
        rows = rpc("match_course_chunks", params)
        kept = [r for r in rows if r.get("similarity", 0) >= min_similarity]
        # The single decrypt boundary for retrieval (#484). Every consumer —
        # `format_rag_context`, the quiz's catalog de-dup, the benchmarks —
        # reads `chunk_text` off these rows, so decrypting once here keeps them
        # all unchanged rather than spreading the boundary over each of them.
        # Ranking never touched this column (the RPC orders on `embedding`), so
        # encryption costs retrieval nothing but ~k AES-GCM decrypts.
        for row in kept:
            row["chunk_text"] = decrypt_if_present(row.get("chunk_text"))
        return Retrieval(chunks=kept)
    except _EmbeddingDisabled as e:
        # The #439 seam guard, not a failure: below-seam embedding is disabled
        # by design outside real mode, so every function-mode turn lands here.
        # An error event per turn would drown the real signal below in noise.
        logger.info("[RAG] retrieve_chunks skipped: %s", e)
        # NOT `failed`: the seam being off is a configured mode, and marking
        # it as a fault would make every function-mode E2E run report broken
        # retrieval.
        return Retrieval(chunks=[])
    except Exception as e:
        # Degrading to [] is deliberate (grounding is best-effort), but [] is
        # ALSO what "nothing relevant matched" returns — so without this the
        # caller, the logs and the rollups cannot tell an ungrounded turn from
        # a grounded one. Log on the app path and emit a countable event (#482).
        logger.warning("[RAG] retrieve_chunks failed: %s", e, exc_info=True)
        log_event(
            "rag.retrieval_failed",
            category="error",
            payload={"course_id": course_id, "error_type": type(e).__name__},
        )
        return Retrieval(chunks=[], failed=True)


def chunk_id(
    course_code: str,
    chunk_text: str,
    *,
    visibility: str = SHARED,
    uploader_id: str | None = None,
) -> str:
    """Content-addressed chunk id, scoped per course and per row kind.

    Identical text in the same course maps to one row no matter which
    document or uploader supplied it, so N students uploading the same
    slides dedup to one embedding instead of N. doc_id/uploader_id/
    chunk_index on the row are last-writer-wins metadata; retrieval only
    reads course_id + chunk_text.

    The literal "document" segment keeps this keyspace DISJOINT from
    catalog rows: scripts/ingest_catalog.py ids category=catalog rows as
    sha256(course::text) in the SAME course_chunks table (on_conflict=id),
    so an un-namespaced hash would let a document chunk whose text
    byte-matches a catalog chunk silently overwrite the catalog row and
    flip its category — dropping it from every category=eq.catalog reader.

    A PRIVATE chunk gets a third namespace segment plus its uploader (#629),
    for the same structural reason: the shared upsert merges on id under
    `resolution=merge-duplicates`, so an opted-out upload that hashed to the
    shared id would merge INTO the classmates' row — leaving the opted-out
    student's text in the shared pool under a row they can no longer withdraw.
    Per-uploader, not merely per-visibility, so two opted-out students who
    upload the same handout do not end up sharing one row with each other.
    """
    if visibility == PRIVATE:
        if not uploader_id:
            raise ValueError(
                "a private chunk id needs its uploader_id: without one the "
                "private keyspace collapses back onto one key per course and "
                "opted-out uploads re-merge with each other (#629)"
            )
        return hashlib.sha256(
            f"{course_code}::document::private::{uploader_id}::{chunk_text}".encode()
        ).hexdigest()
    return hashlib.sha256(f"{course_code}::document::{chunk_text}".encode()).hexdigest()


class ChunkIndexResult(NamedTuple):
    """What one indexing pass actually did (#482).

    A bare count cannot answer the questions a re-drive needs. Embed failures
    are swallowed per batch and simply lower the count, so "3" is ambiguous
    between complete and partial without `total`; and a 0 means either "the
    #439 seam turned embedding off" (a designed no-op) or "every embed failed"
    (a failure) — only `embedding_disabled` tells them apart.
    """

    upserted: int
    total: int
    embedding_disabled: bool = False
    #: Class name of the last embed exception swallowed, e.g. 'ServerError'.
    #: The class only — an exception message can quote the chunk text.
    embed_error: str | None = None


def index_document_chunks(
    course_code: str,
    doc_id: str,
    uploader_id: str,
    chunks: list[str],
    *,
    visibility: str,
    category: str,
) -> int:
    """Embed and upsert document chunks; the number of unique chunks upserted.

    The count-only form, kept for callers that only log it. Anything deciding
    whether a document is DONE needs `index_document_chunks_detailed`, because
    a count alone cannot tell a partial index or a disabled seam from success.
    """
    return index_document_chunks_detailed(
        course_code, doc_id, uploader_id, chunks,
        visibility=visibility, category=category,
    ).upserted


def index_document_chunks_detailed(
    course_code: str,
    doc_id: str,
    uploader_id: str,
    chunks: list[str],
    *,
    visibility: str,
    category: str,
) -> ChunkIndexResult:
    """Embed and upsert document chunks to course_chunks.

    Returns what landed against what was attempted — see `ChunkIndexResult`. Uses RETRIEVAL_DOCUMENT
    task type for all embeddings. Chunk ids are content-addressed per
    course (see chunk_id), so re-uploads of the same content merge instead
    of duplicating rows. Repeated text within one document is deduped
    before upsert — Postgres rejects an upsert payload that hits the same
    row twice.

    `visibility` is the uploader's stored Class Intel opt-in, resolved by the
    caller through `chunk_visibility.visibility_for` (#629) — this layer
    persists the decision, it does not make it. A SHARED index also records the
    uploader in the contributor ledger, which is what lets a later opt-out
    withdraw a row whose `uploader_id` names somebody else.

    REQUIRED and keyword-only, deliberately. A `= SHARED` default would make
    the write side fail OPEN while retrieval fails closed: the next indexing
    surface (notes, a room upload, a re-index route) that forgot the argument
    would publish to the shared pool and reproduce the original bug verbatim,
    with nothing failing in tests because the default IS the old behaviour. An
    omission has to be a TypeError, not a silent leak.

    `category` is the classifier's category for the document (#630). It was
    hardcoded to the literal "document" here, so every chunk in the store
    claimed to be the same kind of thing even though the classifier's answer
    had already reached the caller and chosen the chunking strategy. Required
    for the same reason `visibility` is, and "catalog" is refused outright:
    that value is the partition `learn._get_catalog_chunk` and the quiz's
    catalog de-dup key on, so a document row claiming it would be served as
    official BU course data.
    """
    if category == "catalog":
        raise ValueError(
            "category='catalog' is the BU course-catalog partition "
            "(scripts/ingest_catalog.py); a document chunk claiming it would "
            "be served to students as official course data"
        )
    if not chunks:
        return ChunkIndexResult(upserted=0, total=0)

    records_by_id: dict[str, dict] = {}
    for i, chunk_text in enumerate(chunks):
        cid = chunk_id(
            course_code, chunk_text, visibility=visibility, uploader_id=uploader_id
        )
        if cid in records_by_id:
            continue
        records_by_id[cid] = {
            "id":          cid,
            "course_id":   course_code,
            "doc_id":      doc_id,
            "uploader_id": uploader_id,
            "chunk_index": i,
            "chunk_text":  chunk_text,
            "chunk_hash":  cid,
            "embedding":   None,
            "category":    category,
            "visibility":  visibility,
            "semester":    "current",
            "section_id":  None,
            "school":      "",
        }

    records = list(records_by_id.values())

    # Embed in batches of 50 (API limit)
    BATCH = 50
    # Distinguishes "the seam turned embedding off" (#439, every function-mode
    # run) from "embedding broke" — only the latter is worth an error event.
    embedding_disabled = False
    embed_error: str | None = None
    for i in range(0, len(records), BATCH):
        batch = records[i : i + BATCH]
        texts = [r["chunk_text"] for r in batch]
        try:
            vecs = _embed_documents_batch(texts)
            for rec, vec in zip(batch, vecs):
                rec["embedding"] = vec
        except _EmbeddingDisabled as e:
            embedding_disabled = True
            logger.info("[RAG] doc %s batch %s not embedded: %s", doc_id, i, e)
        except Exception as e:
            embed_error = type(e).__name__
            logger.warning(
                "[RAG] embed failed for doc %s batch %s: %s", doc_id, i, e, exc_info=True
            )

    # Never persist a chunk whose embedding didn't land. match_course_chunks
    # ranks by vector distance, so a NULL-embedding row can never be returned
    # by retrieval — it is dead weight that nonetheless counted toward the
    # "indexed N chunks" the caller logs, which is how a partial embedding
    # failure used to read as a complete success (#482).
    embedded = [r for r in records if r["embedding"] is not None]
    dropped = len(records) - len(embedded)
    if dropped and embedding_disabled:
        logger.info(
            "[RAG] doc %s: %s/%s chunk(s) not indexed — embedding disabled (#439)",
            doc_id, dropped, len(records),
        )
    elif dropped:
        # Silent data loss behind a successful-looking upload: the documents
        # row lands, the user sees success, and these chunks are simply absent
        # from retrieval forever. Countable so a partial-index rate is visible
        # (#482). The caller records the document `partial` and the indexing
        # sweeper re-drives it (services/document_indexing.py).
        logger.warning(
            "[RAG] doc %s: dropped %s/%s chunk(s) with no embedding — "
            "they would be unretrievable",
            doc_id, dropped, len(records),
        )
        log_event(
            "rag.chunks_dropped",
            category="error",
            user_id=uploader_id,
            payload={"doc_id": doc_id, "dropped": dropped, "total": len(records)},
        )

    if not embedded:
        return ChunkIndexResult(
            upserted=0, total=len(records),
            embedding_disabled=embedding_disabled, embed_error=embed_error,
        )

    # ADR 0025 / #484: `chunk_text` is the same student text that
    # `documents.extracted_text` has been encrypting since 0030, chunked. One
    # column was treated as PII and the other was not, for no recorded reason.
    #
    # Encrypted HERE, last, and not when the record was built: the embed pass
    # above reads `rec["chunk_text"]`, so encrypting earlier would embed
    # ciphertext — every vector would be noise and retrieval would rank nothing,
    # silently. Ids were computed on the plaintext, which is the other half of
    # the ADR: AES-GCM draws a fresh nonce per call, so identical text encrypts
    # differently every time and ciphertext can never be a dedup key.
    for rec in embedded:
        rec["chunk_text"] = encrypt_if_present(rec["chunk_text"])

    table("course_chunks").upsert(embedded, on_conflict="id")
    if visibility == SHARED:
        # Only shared rows get a ledger entry. A private row's id already
        # encodes its single possible owner, and keeping it out of the ledger
        # is what stops `resync_user_chunk_visibility` from later flipping it
        # shared under an id that could never merge with the shared row for the
        # same text (see services/chunk_visibility.py).
        record_contributors([r["id"] for r in embedded], uploader_id)
        # Indexing is a detached post-roll thread, and the rows above cannot be
        # written before the ledger rows that name them (the ledger has an FK to
        # `course_chunks.id`). So there is a window: a student who flips Class
        # Intel off while their upload is mid-index gets a resync that runs
        # before these ledger rows land, finds nothing, and leaves the freshly
        # shared chunks published — permanently, because nothing sweeps later.
        # Re-reading consent AFTER the ledger write closes it down to the width
        # of one read: whichever order the two interleave, at least one of them
        # sees the other's effect.
        _reconcile_if_consent_changed(uploader_id, [r["id"] for r in embedded])
    return ChunkIndexResult(
        upserted=len(embedded), total=len(records),
        embedding_disabled=embedding_disabled, embed_error=embed_error,
    )


def _reconcile_if_consent_changed(uploader_id: str, chunk_ids: list[str]) -> None:
    """Privatise a just-shared index if consent flipped while it ran (#629)."""
    from services.chunk_visibility import resync_user_chunk_visibility, shares_class_context

    try:
        if shares_class_context(uploader_id):
            return
        logger.info(
            "[RAG] %s opted out while %s chunk(s) were indexing — resyncing",
            uploader_id, len(chunk_ids),
        )
        resync_user_chunk_visibility(uploader_id)
    except Exception:
        # Best-effort by construction: the chunks and the ledger are already
        # written, so the worst case here is the same window this exists to
        # narrow, not a broken upload.
        logger.warning(
            "[RAG] post-index consent reconcile failed for %s", uploader_id,
            exc_info=True,
        )


def format_rag_context(chunks: list[dict]) -> str:
    """Format retrieved chunks into a text block for prompt assembly.

    #150: chunk_text is cut from student-uploaded documents, so the chunk
    list ships inside the untrusted-content envelope (one envelope for all
    chunks; embedded delimiter forgeries are neutralized). The header line
    stays trusted framing.
    """
    from services.prompt_safety import wrap_untrusted

    if not chunks:
        return ""
    entries = []
    for i, chunk in enumerate(chunks, 1):
        sim = chunk.get("similarity", 0)
        entries.append(f"[{i}] (relevance {sim:.2f})\n{chunk.get('chunk_text', '')}")
    return (
        "RETRIEVED COURSE CONTEXT (semantically relevant to this question):\n"
        + wrap_untrusted("\n\n".join(entries), source="student-document chunks")
    )
