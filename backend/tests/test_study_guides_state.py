"""The reader's small state (services/study_guides/state.py), with the store
replaced where the module looks it up.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from models.study_guide import GuideContent, GuidePatch, Section
from services import events_service
from services.study_guides import state
from services.study_guides.errors import GuideInvalid, GuideNotFound
from services.study_guides.store import GuideRow

ME = "user_state_me"
MADE_AT = "2026-10-01T12:00:00+00:00"
SAVED_AT = "2026-10-03T09:00:00+00:00"
NOW = "2026-11-01T00:00:00+00:00"


def _guide(**over) -> GuideRow:
    content = GuideContent(title="Control flow", sections=[
        Section(id="s1", title="Loops"), Section(id="s2", title="Branches"),
        Section(id="s3", title="Functions"),
    ])
    fields = dict(
        id="g1", user_id=ME, offering_id="off-cs-f26", exam_id=None, scope_kind="course",
        goal="review", depth="standard", use_history=True, status="ready", format=2,
        content=content, material_ids=[], read_sections=["s1"], answers={},
        feedback=None, saved_at=None, generating_at=None, generated_at=MADE_AT,
        created_at=MADE_AT, updated_at=MADE_AT,
    )
    return GuideRow(**{**fields, **over})


@pytest.fixture
def stored(monkeypatch, sink):
    """One guide in a stand-in store that applies a patch the way the real
    one does; `calls` holds what `apatch_state` was asked to change."""
    box = {"guide": _guide(), "calls": [], "events": sink}

    async def aload_guide(user_id, guide_id):
        if (user_id, guide_id) != (ME, "g1"):
            raise GuideNotFound("Study guide not found.")
        return box["guide"]

    async def apatch_state(user_id, guide_id, *, read_sections=None, saved=None, feedback=None):
        box["calls"].append({"read_sections": read_sections, "saved": saved, "feedback": feedback})
        guide = box["guide"]
        box["guide"] = replace(
            guide,
            read_sections=guide.read_sections if read_sections is None else read_sections,
            saved_at=guide.saved_at if saved is None else (NOW if saved else None),
            feedback=guide.feedback if feedback is None else feedback,
        )
        return box["guide"]

    monkeypatch.setattr(state.store, "aload_guide", aload_guide)
    monkeypatch.setattr(state.store, "apatch_state", apatch_state)
    return box


def _patch(stored, **fields):
    return asyncio.run(state.apatch_guide(ME, "g1", GuidePatch(**fields)))


def _saved_events(stored) -> list[dict]:
    events_service.flush_now()
    return [e for e in stored["events"] if e["event_type"] == "study_guide.saved"]


# ── Read sections ─────────────────────────────────────────────────────────────


def test_read_sections_are_stored_once_each_in_section_order(stored):
    out = _patch(stored, read_sections=["s3", "s1", "s3"])
    assert out.read_sections == ["s1", "s3"]
    assert stored["calls"] == [{"read_sections": ["s1", "s3"], "saved": None, "feedback": None}]


def test_an_empty_list_clears_the_read_marks(stored):
    assert _patch(stored, read_sections=[]).read_sections == []


def test_a_section_the_guide_does_not_have_is_refused_and_nothing_is_written(stored):
    with pytest.raises(GuideInvalid):
        _patch(stored, read_sections=["s1", "s9"])
    assert stored["calls"] == [] and stored["guide"].read_sections == ["s1"]


# ── Saved ─────────────────────────────────────────────────────────────────────


def test_saving_stamps_saved_at_and_emits_once(stored):
    out = _patch(stored, saved=True)
    assert out.saved_at == NOW
    (event,) = _saved_events(stored)
    assert (event["category"], event["user_id"], event["payload"]) == ("usage", ME, {"guide_id": "g1"})


def test_saving_a_saved_guide_again_keeps_its_time_and_emits_nothing(stored):
    stored["guide"] = _guide(saved_at=SAVED_AT)
    out = _patch(stored, saved=True)
    assert out.saved_at == SAVED_AT
    assert stored["calls"][0]["saved"] is None and _saved_events(stored) == []


def test_unsaving_clears_saved_at_and_emits_nothing(stored):
    stored["guide"] = _guide(saved_at=SAVED_AT)
    assert _patch(stored, saved=False).saved_at is None
    assert _saved_events(stored) == []


# ── Feedback and the rest ─────────────────────────────────────────────────────


def test_feedback_is_stored_as_given(stored):
    assert _patch(stored, feedback="no").feedback == "no"
    assert stored["calls"] == [{"read_sections": None, "saved": None, "feedback": "no"}]


def test_fields_the_patch_did_not_send_are_left_alone(stored):
    stored["guide"] = _guide(saved_at=SAVED_AT, feedback="yes")
    out = _patch(stored, read_sections=["s2"])
    assert out.model_dump() == {"read_sections": ["s2"], "saved_at": SAVED_AT, "feedback": "yes"}


def test_an_empty_patch_returns_the_state_as_it_is(stored):
    assert _patch(stored).model_dump() == {"read_sections": ["s1"], "saved_at": None, "feedback": None}


def test_someone_elses_guide_is_not_found(stored):
    with pytest.raises(GuideNotFound):
        asyncio.run(state.apatch_guide("user_other", "g1", GuidePatch(saved=True)))
    assert stored["calls"] == [] and _saved_events(stored) == []
