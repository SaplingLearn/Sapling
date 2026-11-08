from fastapi import APIRouter, Depends

from db.scope import service_route

from services.academics import current_term, list_terms

router = APIRouter()


# #115: public (no session) catalog read -> service role under db_user_scope.
@router.get("/semesters", dependencies=[Depends(service_route)])
def get_semesters():
    """All terms (semesters), most recent first — for the frontend SemesterChips (#138).

    ``current_term_id`` is the SERVER's answer to "which term is now" (#766):
    the browser clock and timezone can disagree with it on a boundary day, so
    the frontend takes this rather than recomputing from ``new Date()``.
    """
    cur = current_term()
    return {"semesters": list_terms(), "current_term_id": cur["id"] if cur else None}
