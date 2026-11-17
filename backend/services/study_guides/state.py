"""The reader's small state on a guide: which sections are read, whether it is
saved to the Library, and the feedback answer.
"""
from __future__ import annotations

from models.study_guide import GuidePatch, GuideState
from services import events_service
from services.study_guides import store
from services.study_guides.errors import GuideInvalid
from services.study_guides.store import GuideRow

UNKNOWN_SECTION_DETAIL = "That section is not in this guide."


def _read_sections(guide: GuideRow, sent: list[str] | None) -> list[str] | None:
    """The read marks to store: the guide's own section ids, once each, in
    section order. None when the patch did not send any."""
    if sent is None:
        return None
    section_ids = [section.id for section in guide.content.sections]
    wanted = set(sent)
    if not wanted <= set(section_ids):
        raise GuideInvalid(UNKNOWN_SECTION_DETAIL)
    return [section_id for section_id in section_ids if section_id in wanted]


def _saved(guide: GuideRow, sent: bool | None) -> bool | None:
    """The save change to make. Saving a saved guide again changes nothing,
    so it keeps the time it was first saved."""
    return None if sent == bool(guide.saved_at) else sent


async def apatch_guide(user_id: str, guide_id: str, patch: GuidePatch) -> GuideState:
    """Apply the fields the patch sent. ``GuideNotFound`` when the guide is
    not the user's, ``GuideInvalid`` for a section the guide does not have."""
    guide = await store.aload_guide(user_id, guide_id)
    saved = _saved(guide, patch.saved)
    row = await store.apatch_state(
        user_id,
        guide_id,
        read_sections=_read_sections(guide, patch.read_sections),
        saved=saved,
        feedback=patch.feedback,
    )
    if saved:
        events_service.log_event(
            "study_guide.saved",
            category="usage",
            user_id=user_id,
            payload={"guide_id": guide_id},
        )
    return GuideState(
        read_sections=row.read_sections, saved_at=row.saved_at, feedback=row.feedback,
    )
