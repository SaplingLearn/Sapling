import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db.connection import table
from services.gemini_service import generate_flashcards as _generate

router = APIRouter()


# ── Request / Response models ──────────────────────────────────────────────────

class GenerateFlashcardsBody(BaseModel):
    user_id: str
    topic: str
    count: int = 5
    session_id: str | None = None


class FlashcardRatingBody(BaseModel):
    user_id: str
    card_id: str
    rating: int  # 1 = forgot, 2 = hard, 3 = easy


# ── Context helpers ────────────────────────────────────────────────────────────

def _get_session_summary(session_id: str) -> str:
    try:
        rows = table("sessions").select(
            "summary_json", filters={"id": f"eq.{session_id}"}, limit=1
        )
        if not rows or not rows[0].get("summary_json"):
            return ""
        import json
        return json.dumps(rows[0]["summary_json"])
    except Exception:
        return ""


def _get_course_documents(user_id: str, course_name: str) -> list[dict]:
    """
    Return all library documents for the user that belong to the course
    matching `course_name`. Falls back to all user documents if no course match.
    """
    try:
        # Find the course_id for this course name
        course_rows = table("courses").select(
            "id", filters={"user_id": f"eq.{user_id}", "course_name": f"eq.{course_name}"}, limit=1
        )
        if course_rows:
            course_id = course_rows[0]["id"]
            docs = table("documents").select(
                "file_name,category,summary,key_takeaways,flashcards",
                filters={"user_id": f"eq.{user_id}", "course_id": f"eq.{course_id}"},
            )
        else:
            # Topic might be a concept name — still pull all user docs as context
            docs = table("documents").select(
                "file_name,category,summary,key_takeaways,flashcards",
                filters={"user_id": f"eq.{user_id}"},
            )
        return docs or []
    except Exception:
        return []


def _get_weak_concepts(user_id: str, course_name: str) -> list[str]:
    """
    Return concept names where the student has low mastery (score < 0.4)
    for the given course/subject.
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
        weak = [
            r["concept_name"]
            for r in (rows or [])
            if (r.get("mastery_score") or 0) < 0.4
        ]
        return weak[:15]  # cap to keep prompt reasonable
    except Exception:
        return []


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.post("/generate")
def generate(body: GenerateFlashcardsBody):
    """
    Generate AI flashcards grounded in the student's actual course material.
    Pulls library documents + weak concepts from the knowledge graph automatically.
    """
    # 1. Session summary (optional extra context)
    context = ""
    if body.session_id:
        context = _get_session_summary(body.session_id)

    # 2. Library documents for this course
    documents = _get_course_documents(body.user_id, body.topic)

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

    now = datetime.utcnow().isoformat()
    rows_to_insert = [
        {
            "id": str(uuid.uuid4()),
            "user_id": body.user_id,
            "topic": body.topic,
            "front": c["front"],
            "back": c["back"],
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

    return {
        "flashcards": rows_to_insert,
        "context_used": {
            "documents_found": len(documents),
            "weak_concepts_found": len(weak_concepts),
        }
    }


@router.get("/user/{user_id}")
def get_flashcards(user_id: str, topic: str | None = None):
    if not user_id:
        return {"flashcards": []}

    filters = {"user_id": f"eq.{user_id}"}
    if topic:
        filters["topic"] = f"eq.{topic}"

    try:
        rows = table("flashcards").select(
            "*", filters=filters, order="created_at.desc"
        )
        return {"flashcards": rows or []}
    except Exception as e:
        err_str = str(e).lower()
        if "not found" in err_str or "does not exist" in err_str or "42p01" in err_str:
            return {"flashcards": []}
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rate")
def rate_card(body: FlashcardRatingBody):
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
            "last_reviewed_at": datetime.utcnow().isoformat(),
        },
        filters={"id": f"eq.{body.card_id}"},
    )
    return {"ok": True}


@router.delete("/{card_id}")
def delete_card(card_id: str, user_id: str):
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