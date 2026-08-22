from __future__ import annotations

import base64
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config import is_weak
from db.connection import table
from services.academics import resolve_offering, term_id_for_label
from services.auth_guard import require_self, get_session_user_id
from services.achievement_service import check_achievements
from services.encryption import decrypt_if_present, decrypt_json, encrypt_if_present
from services.flashcard_import_service import (
    dedup_against_existing,
    check_rate_limit,
    parse_xlsx,
    parse_anki_apkg,
    scrape_quizlet_url,
    extract_cards_from_image,
    QuizletBlocked,
    gemini_generate_cards,
    gemini_cleanup_cards,
    gemini_cloze,
    generate_flashcards as _generate,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Request / Response models ──────────────────────────────────────────────────

class GenerateFlashcardsBody(BaseModel):
    user_id: str
    topic: str
    count: int = 5
    session_id: str | None = None
    # Optional term label (#141): grounds generation in the SELECTED term's
    # course documents instead of always the current term's.
    semester: str | None = None


class FlashcardRatingBody(BaseModel):
    user_id: str
    card_id: str
    rating: int  # 1 = forgot, 2 = hard, 3 = easy


class CardInput(BaseModel):
    front: str
    back: str


class ImportParseBody(BaseModel):
    user_id: str
    source: Literal["anki", "xlsx", "url", "ocr"]
    payload: str  # base64 for files, plain text for url; filename in options
    options: dict = {}


class ImportCommitBody(BaseModel):
    user_id: str
    course_id: str | None = None
    topic: str
    cards: list[CardInput]
    dedup: bool = True


class ImportGenerateBody(BaseModel):
    user_id: str
    source: Literal["paste", "library_doc"]
    text: str | None = None
    document_id: str | None = None
    count: int = 25
    difficulty: Literal["recall", "application", "conceptual"] = "recall"


class ImportCleanupBody(BaseModel):
    user_id: str
    cards: list[CardInput]


class ImportClozeBody(BaseModel):
    user_id: str
    paragraph: str


# ── Context helpers ────────────────────────────────────────────────────────────

def _get_session_summary(session_id: str) -> str:
    try:
        rows = table("sessions").select(
            "summary_json", filters={"id": f"eq.{session_id}"}, limit=1
        )
        if not rows or not rows[0].get("summary_json"):
            return ""
        raw = rows[0]["summary_json"]
        if isinstance(raw, str):
            try:
                return json.dumps(decrypt_json(raw))
            except Exception:
                return raw
        return json.dumps(raw)
    except Exception:
        return ""


def _get_course_documents(
    user_id: str, course_name: str, semester: str | None = None
) -> list[dict]:
    """
    Return the library documents grounding generation for `course_name`.

    Documents key on the offering (0025): match the abstract course by name,
    resolve it to the current-term offering — or, with a ``semester`` (#141),
    STRICTLY to that term's offering — then read documents by offering.

    Fallback rules (#475 F2): with a ``semester``, a term with no offering of
    the course AND a course-name miss both contribute NO documents — an
    explicit term gives the all-docs fallback nothing to anchor to. Without a
    ``semester``, a course-name miss keeps the pre-existing fallback to all of
    the user's documents, byte-identical.
    """
    try:
        course_rows = table("courses").select(
            "id", filters={"user_id": f"eq.{user_id}", "course_name": f"eq.{course_name}"}, limit=1
        )
        if course_rows:
            if semester:
                term_id = term_id_for_label(semester)
                offering_id = (
                    resolve_offering(course_rows[0]["id"], term_id, fallback=False)
                    if term_id
                    else None
                )
            else:
                offering_id = resolve_offering(course_rows[0]["id"])
            if offering_id is None:
                docs = []
            else:
                docs = table("documents").select(
                    "file_name,category,summary,concept_notes",
                    filters={
                        "user_id": f"eq.{user_id}",
                        "offering_id": f"eq.{offering_id}",
                        "deleted_at": "is.null",
                    },
                )
        elif semester:
            # Course-name miss + explicit term: nothing to scope the fallback
            # to — no documents (#475 F2).
            docs = []
        else:
            docs = table("documents").select(
                "file_name,category,summary,concept_notes",
                filters={"user_id": f"eq.{user_id}", "deleted_at": "is.null"},
            )
        docs = docs or []
        for d in docs:
            d["summary"] = decrypt_if_present(d.get("summary"))
            notes_raw = d.get("concept_notes")
            if isinstance(notes_raw, str):
                d["concept_notes"] = decrypt_json(notes_raw)
        return docs
    except Exception:
        return []


def _get_weak_concepts(user_id: str, course_name: str) -> list[str]:
    """
    Return concept names the student is weak on — below the "learning" floor
    in `config.get_mastery_tier`, i.e. "struggling" or "unexplored".

    Was a local `< 0.4` (#557), which is not any tier boundary: concepts in
    [0.4, 0.45) read as "struggling" on the Tree but were never offered for
    practice here — the surface whose entire job is drilling weak concepts
    silently skipped a slice of them.
    """
    try:
        rows = table("graph_nodes").select(
            "concept_name,mastery_score",
            filters={"user_id": f"eq.{user_id}", "subject": f"eq.{course_name}"},
        )
        if not rows:
            # Try without subject filter — return all low-mastery concepts
            rows = table("graph_nodes").select(
                "concept_name,mastery_score",
                filters={"user_id": f"eq.{user_id}"},
            )
        weak = sorted(
            (r for r in (rows or []) if is_weak(r.get("mastery_score") or 0)),
            key=lambda r: r.get("mastery_score") or 0,
        )
        # Weakest first, THEN cap. The cap used to truncate in PostgREST row
        # order, which was survivable while the floor was 0.4 and is not now
        # that #557 widened it to 0.45: the newly-admitted [0.4, 0.45)
        # concepts could displace 0.0-0.1 ones purely on row order, leaving
        # the surface whose job is drilling the weakest concepts drilling the
        # least-weak of the weak.
        return [r["concept_name"] for r in weak[:15]]
    except Exception:
        return []


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/generate")
def generate(body: GenerateFlashcardsBody, request: Request):
    """
    Generate AI flashcards grounded in the student's actual course material.
    Pulls library documents + weak concepts from the knowledge graph automatically.
    """
    require_self(body.user_id, request)

    # 1. Session summary (optional extra context)
    context = ""
    if body.session_id:
        context = _get_session_summary(body.session_id)

    # 2. Library documents for this course (term-scoped when a semester is
    #    selected, #141)
    documents = _get_course_documents(body.user_id, body.topic, semester=body.semester)

    # 3. Concepts the student is weak on
    weak_concepts = _get_weak_concepts(body.user_id, body.topic)

    # 4. Generate with full context
    try:
        cards = _generate(
            topic=body.topic,
            count=body.count,
            context=context,
            documents=documents,
            weak_concepts=weak_concepts,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini error: {e}")

    now = datetime.now(timezone.utc).isoformat()
    rows_to_insert = [
        {
            "id": str(uuid.uuid4()),
            "user_id": body.user_id,
            "topic": body.topic,
            "front": encrypt_if_present(c["front"]),
            "back": encrypt_if_present(c["back"]),
            "times_reviewed": 0,
            "last_reviewed_at": None,
            "created_at": now,
        }
        for c in cards
    ]

    try:
        for row in rows_to_insert:
            table("flashcards").insert(row)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save flashcards. Has the flashcards table been created in Supabase? Error: {e}"
        )

    # Check for achievements after flashcard generation
    try:
        from services.achievement_service import check_achievements
        check_achievements(body.user_id, "flashcards_created", {})
    except Exception:
        pass

    # rows_to_insert holds the ciphertext just written; the response the
    # frontend renders (freshly generated cards, before any list re-fetch)
    # must carry plaintext front/back, not the encrypted insert payload.
    response_cards = [
        {**row, "front": decrypt_if_present(row["front"]), "back": decrypt_if_present(row["back"])}
        for row in rows_to_insert
    ]

    return {
        "flashcards": response_cards,
        "context_used": {
            "documents_found": len(documents),
            "weak_concepts_found": len(weak_concepts),
        }
    }


@router.get("/user/{user_id}")
def get_flashcards(
    user_id: str,
    request: Request,
    topic: str | None = None,
    semester: str | None = None,
):
    require_self(user_id, request)

    if not user_id:
        return {"flashcards": []}

    filters = {"user_id": f"eq.{user_id}"}
    if topic:
        filters["topic"] = f"eq.{topic}"

    try:
        rows = table("flashcards").select(
            "id,user_id,topic,offering_id,front,back,times_reviewed,last_rating,last_reviewed_at,created_at",
            filters=filters, order="created_at.desc"
        ) or []
        for r in rows:
            r["front"] = decrypt_if_present(r.get("front"))
            r["back"] = decrypt_if_present(r.get("back"))
        if semester:
            # Term scoping (#141). This route is user-wide (no course id), so
            # the filter works on the cards' offering: cards from the selected
            # term stay, other terms' cards are hidden, and term-LESS cards
            # (offering_id NULL — e.g. AI-generated) stay visible under any
            # selection so picking a term never strands them. An unknown label
            # degrades to term-less cards only — never a 500.
            term_id = term_id_for_label(semester)
            allowed: set[str] = set()
            if term_id:
                offs = table("course_offerings").select(
                    "id", filters={"term_id": f"eq.{term_id}"}
                ) or []
                allowed = {o["id"] for o in offs if o.get("id")}
            rows = [
                r for r in rows
                if r.get("offering_id") is None or r["offering_id"] in allowed
            ]
        return {"flashcards": rows}
    except Exception as e:
        err_str = str(e).lower()
        if "not found" in err_str or "does not exist" in err_str or "42p01" in err_str:
            return {"flashcards": []}
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rate")
def rate_card(body: FlashcardRatingBody, request: Request):
    require_self(body.user_id, request)

    try:
        rows = table("flashcards").select(
            "id,times_reviewed",
            filters={"id": f"eq.{body.card_id}", "user_id": f"eq.{body.user_id}"},
            limit=1,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not rows:
        raise HTTPException(status_code=404, detail="Flashcard not found")

    current = rows[0]["times_reviewed"] or 0
    table("flashcards").update(
        {
            "times_reviewed": current + 1,
            "last_rating": body.rating,
            "last_reviewed_at": datetime.now(timezone.utc).isoformat(),
        },
        filters={"id": f"eq.{body.card_id}"},
    )

    # The review counter is the only thing that advances `flashcards_reviewed`
    # (Quick Draw: review 100 cards), so this is its only possible dispatch
    # point. Post-commit: the review is already recorded, so a failing check
    # must not fail the rating.
    try:
        check_achievements(body.user_id, "flashcards_reviewed", {})
    except Exception:
        logger.exception(
            "achievement dispatch failed after card rating user=%s card=%s",
            body.user_id, body.card_id,
        )

    return {"ok": True}


@router.delete("/{card_id}")
def delete_card(card_id: str, user_id: str, request: Request):
    require_self(user_id, request)

    try:
        rows = table("flashcards").select(
            "id",
            filters={"id": f"eq.{card_id}", "user_id": f"eq.{user_id}"},
            limit=1,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if not rows:
        raise HTTPException(status_code=404, detail="Flashcard not found")

    table("flashcards").delete(filters={"id": f"eq.{card_id}"})
    return {"ok": True}


# ── Import routes ──────────────────────────────────────────────────────────────

_MAX_UPLOAD_BYTES = 5 * 1024 * 1024


@router.post("/import/commit")
def import_commit(body: ImportCommitBody, request: Request):
    require_self(body.user_id, request)

    # The body carries an abstract course id (optional); flashcards key on the
    # offering. Resolve it (None stays None — flashcards.offering_id is nullable).
    # CREATE path: imported cards land on the CURRENT term's offering by design
    # (#141 scopes the reads only; new content belongs to the term it's made in).
    offering_id = resolve_offering(body.course_id) if body.course_id else None

    cards = [{"front": c.front, "back": c.back} for c in body.cards]
    skipped_count = 0

    if body.dedup:
        keep, skipped = dedup_against_existing(
            body.user_id, offering_id, cards, topic=body.topic
        )
        cards = keep
        skipped_count = len(skipped)

    now = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "id": str(uuid.uuid4()),
            "user_id": body.user_id,
            "topic": body.topic,
            "offering_id": offering_id,
            "front": encrypt_if_present(c["front"]),
            "back": encrypt_if_present(c["back"]),
            "times_reviewed": 0,
            "last_reviewed_at": None,
            "created_at": now,
        }
        for c in cards
    ]

    if rows:
        try:
            table("flashcards").insert(rows)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Insert failed: {e}")

    try:
        check_achievements(body.user_id, "flashcards_created", {"count": len(rows)})
    except Exception:
        pass

    return {"inserted": len(rows), "skipped_duplicates": skipped_count}


@router.post("/import/parse")
def import_parse(body: ImportParseBody, request: Request):
    require_self(body.user_id, request)

    if body.source in ("anki", "xlsx", "ocr"):
        try:
            file_bytes = base64.b64decode(body.payload, validate=True)
        except Exception:
            raise HTTPException(status_code=400, detail="payload must be valid base64")
        if len(file_bytes) > _MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="File exceeds 5MB limit")

        try:
            if body.source == "xlsx":
                cards = parse_xlsx(file_bytes)
            elif body.source == "anki":
                cards = parse_anki_apkg(file_bytes)
            else:  # ocr
                filename = (body.options or {}).get("filename", "image.png")
                cards = extract_cards_from_image(file_bytes, filename=filename)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Parser error: {e}")
        return {"cards": cards, "errors": []}

    if body.source == "url":
        try:
            cards = scrape_quizlet_url(body.payload)
        except QuizletBlocked as e:
            raise HTTPException(status_code=422, detail=str(e))
        return {"cards": cards, "errors": []}

    raise HTTPException(status_code=400, detail=f"Unsupported source: {body.source}")


@router.post("/import/generate")
def import_generate(body: ImportGenerateBody, request: Request):
    require_self(body.user_id, request)

    retry = check_rate_limit(body.user_id)
    if retry is not None:
        return JSONResponse(
            status_code=429,
            content={"detail": f"Rate limit hit. Try again in {retry}s."},
            headers={"Retry-After": str(retry)},
        )

    if body.source == "paste":
        if not body.text:
            raise HTTPException(status_code=400, detail="`text` is required for paste source")
        source_text = body.text
    else:  # library_doc
        if not body.document_id:
            raise HTTPException(status_code=400, detail="`document_id` is required for library_doc source")
        rows = table("documents").select(
            "id,user_id,summary,concept_notes,file_name",
            filters={
                "id": f"eq.{body.document_id}",
                "user_id": f"eq.{body.user_id}",
                "deleted_at": "is.null",
            },
            limit=1,
        )
        if not rows:
            raise HTTPException(status_code=404, detail="Document not found")
        doc = rows[0]
        doc_summary = decrypt_if_present(doc.get("summary")) or ""
        notes_raw = doc.get("concept_notes")
        if isinstance(notes_raw, str):
            try:
                doc_notes = decrypt_json(notes_raw)
            except Exception:
                doc_notes = notes_raw
        else:
            doc_notes = notes_raw or {}
        parts = [doc_summary, str(doc_notes)]
        source_text = "\n\n".join(p for p in parts if p)

    try:
        cards = gemini_generate_cards(source_text, count=body.count, difficulty=body.difficulty)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini error: {e}")

    return {"cards": cards}


@router.post("/import/cleanup")
def import_cleanup(body: ImportCleanupBody, request: Request):
    require_self(body.user_id, request)

    retry = check_rate_limit(body.user_id)
    if retry is not None:
        return JSONResponse(
            status_code=429,
            content={"detail": f"Rate limit hit. Try again in {retry}s."},
            headers={"Retry-After": str(retry)},
        )

    cards = [{"front": c.front, "back": c.back} for c in body.cards]
    try:
        out = gemini_cleanup_cards(cards)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini error: {e}")
    return {"cards": out}


@router.post("/import/cloze")
def import_cloze(body: ImportClozeBody, request: Request):
    require_self(body.user_id, request)

    retry = check_rate_limit(body.user_id)
    if retry is not None:
        return JSONResponse(
            status_code=429,
            content={"detail": f"Rate limit hit. Try again in {retry}s."},
            headers={"Retry-After": str(retry)},
        )

    try:
        cards = gemini_cloze(body.paragraph)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini error: {e}")
    return {"cards": cards}