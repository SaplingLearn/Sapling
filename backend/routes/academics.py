from fastapi import APIRouter

from services.academics import current_term, list_terms

router = APIRouter()


@router.get("/semesters")
def get_semesters():
    """All terms (semesters), most recent first — for the frontend SemesterChips (#138).

    ``current_term_id`` is the SERVER's answer to "which term is now" (#766):
    the browser clock and timezone can disagree with it on a boundary day, so
    the frontend takes this rather than recomputing from ``new Date()``.
    """
    cur = current_term()
    return {"semesters": list_terms(), "current_term_id": cur["id"] if cur else None}
