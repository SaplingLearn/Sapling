"""
RAG retrieval service.

Embeds queries and documents with gemini-embedding-001 using the correct
task types (RETRIEVAL_QUERY for queries, RETRIEVAL_DOCUMENT for indexing),
then calls the match_course_chunks Supabase RPC for ANN retrieval.
"""
import hashlib
import logging
import os
from typing import NamedTuple

from google import genai
from google.genai import types as genai_types

from agents._providers import model_mode
from db.connection import rpc, table
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
    this module: routes/documents.py's catalog-relevance gate. Routing it
    through here (lazy shared client with the dummy-key fallback, request
    timeout, and the #439 real-mode gate) replaced a raw ``genai.Client``
    built with an empty-string API-key fallback, whose keyless construction
    ``ValueError`` was swallowed into a silent no-index degrade (#413).
    """
    return _embed_document(text)


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

    #: The matched chunks, best-first. Empty on failure or when nothing matched.
    chunks: list[dict] = []
    #: True when retrieval RAISED. False for a clean empty result and for the
    #: #439 seam skip, which is a deliberate mode rather than a fault.
    failed: bool = False


def retrieve_chunks(
    query: str,
    course_id: str | None = None,
    k: int = 5,
    min_similarity: float = 0.55,
) -> list[dict]:
    """Return up to k chunks similar to query, optionally filtered by course_id.

    Each result: {"course_id": str, "chunk_text": str, "similarity": float}

    Callers that need to distinguish "nothing matched" from "retrieval broke"
    want `retrieve_chunks_detailed` instead; this stays the shape every
    grounding-is-best-effort caller already expects.
    """
    return retrieve_chunks_detailed(query, course_id, k, min_similarity).chunks


def retrieve_chunks_detailed(
    query: str,
    course_id: str | None = None,
    k: int = 5,
    min_similarity: float = 0.55,
) -> Retrieval:
    """`retrieve_chunks`, plus whether the empty result is a fault or a fact."""
    try:
        embedding = _embed_query(query)
        params: dict = {
            "query_embedding": embedding,
            "match_count": k,
            "filter_course_id": course_id,
        }
        rows = rpc("match_course_chunks", params)
        return Retrieval(
            chunks=[r for r in rows if r.get("similarity", 0) >= min_similarity],
        )
    except _EmbeddingDisabled as e:
        # The #439 seam guard, not a failure: below-seam embedding is disabled
        # by design outside real mode, so every function-mode turn lands here.
        # An error event per turn would drown the real signal below in noise.
        logger.info("[RAG] retrieve_chunks skipped: %s", e)
        # NOT `failed`: the seam being off is a configured mode, and marking
        # it as a fault would make every function-mode E2E run report broken
        # retrieval.
        return Retrieval()
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
        return Retrieval(failed=True)


def chunk_id(course_code: str, chunk_text: str) -> str:
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
    """
    return hashlib.sha256(f"{course_code}::document::{chunk_text}".encode()).hexdigest()


def index_document_chunks(
    course_code: str,
    doc_id: str,
    uploader_id: str,
    chunks: list[str],
) -> int:
    """Embed and upsert document chunks to course_chunks.

    Returns the number of unique chunks upserted. Uses RETRIEVAL_DOCUMENT
    task type for all embeddings. Chunk ids are content-addressed per
    course (see chunk_id), so re-uploads of the same content merge instead
    of duplicating rows. Repeated text within one document is deduped
    before upsert — Postgres rejects an upsert payload that hits the same
    row twice.
    """
    if not chunks:
        return 0

    records_by_id: dict[str, dict] = {}
    for i, chunk_text in enumerate(chunks):
        cid = chunk_id(course_code, chunk_text)
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
            "category":    "document",
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
        # (#482); re-index with scripts/backfill_document_chunks.py.
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
        return 0

    table("course_chunks").upsert(embedded, on_conflict="id")
    return len(embedded)


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
