"""What the New study guide modal offers for one class: what a guide can be
for, the class's materials, and the materials pre-selected for each scope.
"""
from __future__ import annotations

from models.study_guide import GuideOptions, ScopeOption
from services.study_guides import materials, scopes


async def aget_options(user_id: str, course_id: str, semester: str | None) -> GuideOptions:
    """The whole course first, then the class's exams and assignments by
    date. ``GuideNotFound`` when the student is not in the class."""
    offering_id = await scopes.aresolve_offering(user_id, course_id, semester)
    class_scopes = await scopes.alist_scopes(user_id, offering_id)
    class_materials = await materials.alist_materials(user_id, offering_id)
    return GuideOptions(
        scopes=[
            ScopeOption(
                kind=scope.kind,
                id=scope.id,
                title=scope.title,
                due_date=scope.due_date,
                suggested_material_ids=materials.suggest_materials(
                    class_materials, scope, class_scopes,
                ),
            )
            for scope in class_scopes
        ],
        materials=class_materials,
    )
