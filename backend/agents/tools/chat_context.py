"""Chat-tutor read tools for Pydantic AI agents.

Per ADR 0001 (adopt Pydantic AI) and refactor #3 (chat tutor), the chat
tutor agent fetches grounding context on demand instead of having every
piece of state stuffed into a single system prompt by
`routes/learn.py::build_system_prompt`. Each function in this module is
one such on-demand fetch:

  - `search_course_materials` — pull document summaries + concept notes
    relevant to the student's current question, scored by simple keyword
    overlap (no embeddings yet — the corpus per course is small enough
    that BM25-lite is fine; revisit when courses cross ~200 docs).
  - `read_session_history` — quick lookup of the last N messages in the
    current session. The agent already gets full multi-turn via
    Pydantic AI's `message_history`, so this exists only for mid-response
    self-reference (e.g. "what did the student just say their major was?").
  - `read_user_progress` — aggregated mastery counts for a course so the
    agent can decide whether to introduce new material or reinforce
    existing weak areas.

Each tool exposes two surfaces, mirroring the pattern in
`graph_read.py` and `quiz_history.py`:

  - The pure async function — callable from routes/tests, takes ids
    explicitly so it can be unit-tested without a `RunContext`.
  - The `*_tool` wrapper — registers on a Pydantic AI Agent and pulls
    the security-sensitive ids (user_id, course_id, session_id) from
    `ctx.deps`. The LLM is only allowed to choose the *query string* /
    `last_n`; it can never specify whose data to read.

Encryption: `documents.summary`, `documents.concept_notes`, and
`messages.content` are encrypted at rest (see CLAUDE.md / encryption.py).
Every read in this file decrypts at the boundary before returning to
the agent, so the tool contract never leaks ciphertext to the LLM.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Literal

from pydantic import BaseModel, Field
from pydantic_ai import RunContext

from agents.deps import SaplingDeps
from db.connection import table
from services.encryption import decrypt_if_present, decrypt_json

logger = logging.getLogger(__name__)


# Words that show up in nearly every academic question and would otherwise
# dominate the keyword-overlap score. Filtering them keeps short queries
# like "what is recursion?" from matching every document with the word
# "what" in its summary.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
        "of", "in", "on", "at", "to", "for", "with", "by", "from", "as",
        "and", "or", "but", "not", "no", "so", "if", "then", "than", "that",
        "this", "these", "those", "it", "its", "i", "you", "we", "they",
        "he", "she", "him", "her", "them", "us", "do", "does", "did", "done",
        "have", "has", "had", "what", "which", "who", "whom", "whose",
        "when", "where", "why", "how", "can", "could", "would", "should",
        "will", "may", "might", "must", "about", "into", "over", "under",
    }
)

# Token = run of word chars, lowercased. Same shape across query and
# document text so overlap math is symmetric.
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _tokenize(text: str | None) -> set[str]:
    """Lowercase and tokenize, dropping stopwords. Returns a set so
    repeated occurrences in the doc do not game the overlap score (we
    want to know whether a term is present, not how many times)."""
    if not text:
        return set()
    return {
        t.lower()
        for t in _TOKEN_RE.findall(text)
        if t.lower() not in _STOPWORDS and len(t) > 1
    }


# search_course_materials


class CourseMaterial(BaseModel):
    """One document's worth of grounding context for the chat tutor."""

    document_id: str
    file_name: str
    summary: str | None = None
    # Each entry is {"name": str, "description": str}. Stored as list[dict]
    # rather than a typed nested model so we can pass through whatever
    # shape the document agent wrote without forcing migrations on legacy
    # rows (some older docs use {"name", "description"}, some add extras).
    concept_notes: list[dict] = Field(default_factory=list)


def _coerce_concept_notes(value: Any) -> list[dict]:
    """Normalize a documents.concept_notes payload into list[dict].

    The column has been written under several historical shapes:
      - list[dict] (current document agent output)
      - dict (single concept; older legacy rows)
      - None / empty string (extraction failed)

    Anything we cannot recognize collapses to []. We deliberately do not
    raise — the agent should still get the doc back (with summary), just
    without notes, when concept extraction was incomplete.
    """
    if not value:
        return []
    if isinstance(value, dict):
        return [value]
    if isinstance(value, list):
        return [n for n in value if isinstance(n, dict)]
    return []


def _score_material(query_tokens: set[str], doc: dict) -> int:
    """Keyword-overlap score: count of distinct query tokens that appear
    in the doc's filename + summary + concept-note text. Filename is
    included because a student asking 'the syllabus' should pull the
    file literally named 'syllabus.pdf' even if the summary doesn't echo
    that word."""
    if not query_tokens:
        # No query => everything ties at 0; caller falls back to insertion order.
        return 0
    doc_text_parts: list[str] = [doc.get("file_name") or "", doc.get("summary") or ""]
    for note in doc.get("concept_notes") or []:
        if isinstance(note, dict):
            doc_text_parts.append(note.get("name") or "")
            doc_text_parts.append(note.get("description") or "")
    doc_tokens = _tokenize(" ".join(doc_text_parts))
    return len(query_tokens & doc_tokens)


async def search_course_materials(
    course_id: str | None,
    query: str,
    limit: int = 5,
    *,
    user_id: str,
) -> list[CourseMaterial]:
    """Return the top `limit` documents owned by `user_id` in `course_id`,
    ranked by keyword overlap with `query`.

    #125: documents are user-scoped *within* a shared course, so the query
    MUST filter on user_id as well as course_id — otherwise another enrolled
    student's private summary/concept_notes get decrypted into this user's LLM
    context. user_id is keyword-only and required so no caller can silently
    omit the scope.

    Drops rows that have neither a summary nor concept notes — there's
    nothing to ground on, and including them would waste a tool-result
    slot on an empty payload. When `course_id` is None we return [];
    the chat tutor only grounds on materials inside the active course
    (cross-course search would leak other-class context into the chat).

    Failures degrade silently to []. The agent can always answer from
    its base knowledge — losing course materials downgrades quality but
    shouldn't 500 the chat.
    """
    if not course_id:
        return []

    def _fetch() -> list[dict[str, Any]]:
        try:
            return (
                table("documents").select(
                    "id,file_name,summary,concept_notes",
                    filters={
                        "course_id": f"eq.{course_id}",
                        "user_id": f"eq.{user_id}",
                    },
                    order="created_at.desc",
                )
                or []
            )
        except Exception:
            logger.exception(
                "search_course_materials fetch failed course=%s",
                course_id,
            )
            return []

    rows = await asyncio.to_thread(_fetch)

    # Decrypt at the boundary. Both summary and concept_notes are
    # encrypted at rest — never hand ciphertext to the LLM.
    decrypted: list[dict[str, Any]] = []
    for r in rows:
        summary = decrypt_if_present(r.get("summary"))
        notes_raw = r.get("concept_notes")
        if isinstance(notes_raw, str) and notes_raw:
            try:
                notes = _coerce_concept_notes(decrypt_json(notes_raw))
            except Exception:
                logger.warning(
                    "search_course_materials: concept_notes decrypt failed doc=%s",
                    r.get("id"),
                )
                notes = []
        else:
            notes = _coerce_concept_notes(notes_raw)

        # Drop entries with nothing groundable. A doc with no summary AND
        # no notes is effectively a filename — useless to the tutor.
        if not summary and not notes:
            continue

        decrypted.append(
            {
                "id": r.get("id") or "",
                "file_name": r.get("file_name") or "",
                "summary": summary,
                "concept_notes": notes,
            }
        )

    query_tokens = _tokenize(query)
    # Sort descending by score; stable sort preserves recency order
    # (already sorted DESC by created_at) for ties — most-recent wins.
    decrypted.sort(key=lambda d: _score_material(query_tokens, d), reverse=True)

    capped = decrypted[: max(0, int(limit))]
    return [
        CourseMaterial(
            document_id=d["id"],
            file_name=d["file_name"],
            summary=d["summary"],
            concept_notes=d["concept_notes"],
        )
        for d in capped
        if d["id"]
    ]


async def search_course_materials_tool(
    ctx: RunContext[SaplingDeps],
    query: str,
    limit: int = 5,
) -> list[CourseMaterial]:
    """Pydantic AI tool wrapper.

    The LLM supplies `query` (and optionally `limit`); `course_id` and
    `user_id` are pulled from `ctx.deps` so the model can't aim a search at
    another course's — or another user's — materials.
    """
    return await search_course_materials(
        ctx.deps.course_id, query, limit, user_id=ctx.deps.user_id
    )


# read_session_history


class SessionMessage(BaseModel):
    """One past chat turn in the current session."""

    role: Literal["user", "model"]
    content: str
    created_at: str


# Map storage role values to the tool's public role values. The
# messages.role column historically used 'assistant'; the agent-facing
# contract uses 'model' to align with Pydantic AI / Gemini terminology.
_ROLE_MAP: dict[str, Literal["user", "model"]] = {
    "user": "user",
    "model": "model",
    "assistant": "model",
    "system": "model",  # legacy; collapse into model so it's never lost.
}


async def read_session_history(
    session_id: str,
    last_n: int = 10,
) -> list[SessionMessage]:
    """Return up to `last_n` most-recent messages from `session_id`.

    Newest first — the agent typically wants 'what was just said' rather
    than the start of the session. Decrypts `content` at the boundary so
    the LLM never sees ciphertext, and skips any row whose role doesn't
    map to {user, model} or whose content decrypts to empty.

    Failures degrade to []. A history-less response is degraded but not
    broken; raising would kill the chat turn entirely.
    """
    if not session_id:
        return []
    n = max(0, int(last_n))
    if n == 0:
        return []

    def _fetch() -> list[dict[str, Any]]:
        try:
            return (
                table("messages").select(
                    "role,content,created_at",
                    filters={"session_id": f"eq.{session_id}"},
                    order="created_at.desc",
                    limit=n,
                )
                or []
            )
        except Exception:
            logger.exception(
                "read_session_history fetch failed session=%s",
                session_id,
            )
            return []

    rows = await asyncio.to_thread(_fetch)
    out: list[SessionMessage] = []
    for r in rows:
        raw_role = (r.get("role") or "").lower()
        role = _ROLE_MAP.get(raw_role)
        if role is None:
            continue
        content = decrypt_if_present(r.get("content"))
        if not content:
            continue
        out.append(
            SessionMessage(
                role=role,
                content=str(content),
                created_at=str(r.get("created_at") or ""),
            )
        )
    return out


async def read_session_history_tool(
    ctx: RunContext[SaplingDeps],
    last_n: int = 10,
) -> list[SessionMessage]:
    """Pydantic AI tool wrapper.

    `session_id` is read off `ctx.deps` rather than accepted from the
    LLM — letting the model supply it would let it read other students'
    chat history. The LLM supplies only `last_n`.
    """
    if not ctx.deps.session_id:
        return []
    return await read_session_history(ctx.deps.session_id, last_n)


# read_user_progress


# Mastery thresholds — duplicated here (rather than imported from
# graph_service) so the tool stays self-contained and the agent's
# definitions of 'mastered' / 'weak' can evolve independently from the
# spaced-repetition scheduling logic.
_MASTERED_THRESHOLD = 0.7
_WEAK_THRESHOLD = 0.4


class CourseProgress(BaseModel):
    """The student's overall progress in a course (or globally if no
    course is in scope). All counts are non-negative; `avg_mastery` is
    clamped to [0, 1] and is 0.0 when there are no concepts."""

    total_concepts: int = Field(ge=0)
    mastered_count: int = Field(ge=0)  # mastery >= 0.7
    weak_count: int = Field(ge=0)  # mastery < 0.4
    in_progress_count: int = Field(ge=0)  # 0.4 <= mastery < 0.7
    avg_mastery: float = Field(ge=0.0, le=1.0)


def _empty_progress() -> CourseProgress:
    return CourseProgress(
        total_concepts=0,
        mastered_count=0,
        weak_count=0,
        in_progress_count=0,
        avg_mastery=0.0,
    )


async def read_user_progress(
    user_id: str,
    course_id: str | None,
) -> CourseProgress:
    """Aggregate the user's mastery across `course_id` (or globally if
    None). Reads all `graph_nodes` for the user/course filter and bins
    them in Python — the per-(user, course) graph is small (low hundreds
    of nodes max) so a fetch-and-aggregate is cheaper than a custom RPC.

    Returns zeros on empty graph or fetch error so the agent can still
    plan a turn ('I don't see any concepts for this course yet — want
    to upload your syllabus?').
    """

    def _fetch() -> list[dict[str, Any]]:
        filters = {"user_id": f"eq.{user_id}"}
        if course_id:
            filters["course_id"] = f"eq.{course_id}"
        try:
            return (
                table("graph_nodes").select(
                    "mastery_score",
                    filters=filters,
                )
                or []
            )
        except Exception:
            logger.exception(
                "read_user_progress fetch failed user=%s course=%s",
                user_id,
                course_id,
            )
            return []

    rows = await asyncio.to_thread(_fetch)
    if not rows:
        return _empty_progress()

    mastered = 0
    weak = 0
    in_progress = 0
    total = 0
    mastery_sum = 0.0
    for r in rows:
        try:
            m = float(r.get("mastery_score") or 0.0)
        except (TypeError, ValueError):
            continue
        # Defensive clamp — old rows occasionally drift outside [0, 1].
        m = max(0.0, min(1.0, m))
        total += 1
        mastery_sum += m
        if m >= _MASTERED_THRESHOLD:
            mastered += 1
        elif m < _WEAK_THRESHOLD:
            weak += 1
        else:
            in_progress += 1

    if total == 0:
        return _empty_progress()

    return CourseProgress(
        total_concepts=total,
        mastered_count=mastered,
        weak_count=weak,
        in_progress_count=in_progress,
        avg_mastery=round(mastery_sum / total, 4),
    )


async def read_user_progress_tool(
    ctx: RunContext[SaplingDeps],
) -> CourseProgress:
    """Pydantic AI tool wrapper. Reads user_id and course_id from deps."""
    return await read_user_progress(ctx.deps.user_id, ctx.deps.course_id)
