"""
RAG retrieval service.

Embeds queries and documents with gemini-embedding-001 using the correct
task types (RETRIEVAL_QUERY for queries, RETRIEVAL_DOCUMENT for indexing),
then calls the match_course_chunks Supabase RPC for ANN retrieval.
"""
import hashlib
import os

from google import genai
from google.genai import types as genai_types

from db.connection import rpc, table

_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY", ""))
_EMBED_MODEL = "gemini-embedding-001"
_OUTPUT_DIM = 768


def _embed_query(text: str) -> list[float]:
    resp = _client.models.embed_content(
        model=_EMBED_MODEL,
        contents=[text],
        config=genai_types.EmbedContentConfig(
            output_dimensionality=_OUTPUT_DIM,
            task_type="RETRIEVAL_QUERY",
        ),
    )
    return list(resp.embeddings[0].values)


def _embed_document(text: str) -> list[float]:
    resp = _client.models.embed_content(
        model=_EMBED_MODEL,
        contents=[text],
        config=genai_types.EmbedContentConfig(
            output_dimensionality=_OUTPUT_DIM,
            task_type="RETRIEVAL_DOCUMENT",
        ),
    )
    return list(resp.embeddings[0].values)


def _embed_documents_batch(texts: list[str]) -> list[list[float]]:
    resp = _client.models.embed_content(
        model=_EMBED_MODEL,
        contents=texts,
        config=genai_types.EmbedContentConfig(
            output_dimensionality=_OUTPUT_DIM,
            task_type="RETRIEVAL_DOCUMENT",
        ),
    )
    return [list(e.values) for e in resp.embeddings]


def retrieve_chunks(
    query: str,
    course_id: str | None = None,
    k: int = 5,
    min_similarity: float = 0.55,
) -> list[dict]:
    """Return up to k chunks similar to query, optionally filtered by course_id.

    Each result: {"course_id": str, "chunk_text": str, "similarity": float}
    """
    try:
        embedding = _embed_query(query)
        params: dict = {
            "query_embedding": embedding,
            "match_count": k,
            "filter_course_id": course_id,
        }
        rows = rpc("match_course_chunks", params)
        return [r for r in rows if r.get("similarity", 0) >= min_similarity]
    except Exception as e:
        print(f"[RAG] retrieve_chunks failed: {e}")
        return []


def index_document_chunks(
    course_code: str,
    doc_id: str,
    uploader_id: str,
    chunks: list[str],
) -> int:
    """Embed and upsert document chunks to course_chunks.

    Returns the number of chunks upserted. Uses RETRIEVAL_DOCUMENT task
    type for all embeddings. Upsert is idempotent — re-indexing the same
    doc_id produces the same chunk IDs and merges cleanly.
    """
    if not chunks:
        return 0

    records = []
    for i, chunk_text in enumerate(chunks):
        raw = f"{doc_id}::{i}::{chunk_text}"
        cid = hashlib.sha256(raw.encode()).hexdigest()
        records.append({
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
        })

    # Embed in batches of 50 (API limit)
    BATCH = 50
    for i in range(0, len(records), BATCH):
        batch = records[i : i + BATCH]
        texts = [r["chunk_text"] for r in batch]
        try:
            vecs = _embed_documents_batch(texts)
            for rec, vec in zip(batch, vecs):
                rec["embedding"] = vec
        except Exception as e:
            print(f"[RAG] embed failed for doc {doc_id} batch {i}: {e}")

    table("course_chunks").upsert(records, on_conflict="id")
    return len(records)


def format_rag_context(chunks: list[dict]) -> str:
    """Format retrieved chunks into a text block for prompt injection."""
    if not chunks:
        return ""
    lines = ["RETRIEVED COURSE CONTEXT (semantically relevant to this question):"]
    for i, chunk in enumerate(chunks, 1):
        sim = chunk.get("similarity", 0)
        lines.append(f"\n[{i}] (relevance {sim:.2f})\n{chunk.get('chunk_text', '')}")
    return "\n".join(lines)
