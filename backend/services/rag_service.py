"""
RAG retrieval service.

Embeds a query with Gemini gemini-embedding-001 and calls the
match_course_chunks Supabase RPC to return the top-k semantically
similar course chunks.
"""

import os

from google import genai
from google.genai import types as genai_types

from db.connection import rpc

_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY", ""))
_EMBED_MODEL = "gemini-embedding-001"
_OUTPUT_DIM = 768


def _embed(text: str) -> list[float]:
    resp = _client.models.embed_content(
        model=_EMBED_MODEL,
        contents=[text],
        config=genai_types.EmbedContentConfig(output_dimensionality=_OUTPUT_DIM),
    )
    return list(resp.embeddings[0].values)


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
        embedding = _embed(query)
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


def format_rag_context(chunks: list[dict]) -> str:
    """Format retrieved chunks into a text block for prompt injection."""
    if not chunks:
        return ""
    lines = ["RETRIEVED COURSE CONTEXT (semantically relevant to this question):"]
    for i, chunk in enumerate(chunks, 1):
        sim = chunk.get("similarity", 0)
        lines.append(f"\n[{i}] (relevance {sim:.2f})\n{chunk.get('chunk_text', '')}")
    return "\n".join(lines)
