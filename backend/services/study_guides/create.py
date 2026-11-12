"""Make a new guide from the New study guide modal's choices: check them
against the student's own class and insert the row. Nothing is written yet;
the reader starts the generation when it opens the guide.
"""
from __future__ import annotations

from models.study_guide import GuideContent, GuideRequest
from services.study_guides import cards, materials, scopes, store
from services.study_guides.errors import GuideInvalid
from services.study_guides.legacy import UNTITLED
from services.study_guides.scopes import Scope

NO_MATERIALS_DETAIL = "Choose at least one of this class's materials."

# The strict lengths of ``GuideContent.title`` and ``scope_label``.
_TITLE_MAX = 120
_LABEL_MAX = 200


async def _aclass_material_ids(user_id: str, offering_id: str, chosen: list[str]) -> list[str]:
    """The chosen ids that are the class's materials, oldest first. An id from
    another class, another student or a deleted document is left out."""
    wanted = set(chosen)
    mine = await materials.alist_materials(user_id, offering_id)
    kept = [material.id for material in mine if material.id in wanted]
    if not kept:
        raise GuideInvalid(NO_MATERIALS_DETAIL)
    return kept


async def _atitle(scope: Scope, course_id: str) -> str:
    """The guide's title until the outline names it: what it is for, or the
    course's name for a whole-course guide."""
    if scope.kind != "course":
        return scope.title or UNTITLED
    names = await cards.acourse_names({course_id})
    return names.get(course_id) or UNTITLED


async def acreate_guide(user_id: str, request: GuideRequest) -> str:
    """Insert the guide and return its id. ``GuideNotFound`` when the class or
    the exam is not the student's, ``GuideInvalid`` when the scope's kind and
    id disagree or none of the chosen materials is the class's."""
    offering_id = await scopes.aresolve_offering(user_id, request.course_id, request.semester)
    scope = await scopes.ascope_of(user_id, offering_id, request.scope_kind, request.scope_id)
    material_ids = await _aclass_material_ids(user_id, offering_id, request.material_ids)
    title = await _atitle(scope, request.course_id)
    return await store.ainsert_guide(
        user_id=user_id,
        offering_id=offering_id,
        # The kind the row reads as now, which is not always the one sent.
        scope_kind=scope.kind,
        exam_id=scope.id,
        goal=request.goal,
        depth=request.depth,
        use_history=request.use_history,
        material_ids=material_ids,
        content=GuideContent(title=title[:_TITLE_MAX], scope_label=scope.title[:_LABEL_MAX]),
    )
