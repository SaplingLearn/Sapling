from fastapi import APIRouter

from services.academics import list_terms

router = APIRouter()


@router.get("/semesters")
def get_semesters():
    """All terms (semesters), most recent first — for the frontend SemesterChips (#138)."""
    return {"semesters": list_terms()}
