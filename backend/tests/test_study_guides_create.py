"""Making a guide and the modal's options (services/study_guides/create.py,
options.py), with the scope, material and store calls replaced where the
modules look them up.
"""
from __future__ import annotations

import asyncio

import pytest

from models.study_guide import GuideRequest, MaterialOption
from services import request_limits
from services.study_guides import create, limits, options
from services.study_guides.errors import GuideInvalid, GuideNotFound, GuideRateLimited
from services.study_guides.scopes import WHOLE_COURSE, Scope

ME = "user_create_me"
COURSE = "course-cs"
OFFERING = "off-cs-f26"
MIDTERM = Scope(kind="exam", id="exam-1", title="Midterm 1", due_date="2026-10-20")
HOMEWORK = Scope(kind="assignment", id="hw-1", title="Homework 3", due_date="2026-11-02")


def _material(doc_id: str, created_at: str, category: str = "lecture_notes") -> MaterialOption:
    return MaterialOption(
        id=doc_id, file_name=f"{doc_id}.pdf", category=category, created_at=created_at,
    )


MATERIALS = [
    _material("doc-syllabus", "2026-09-01T00:00:00+00:00", "syllabus"),
    _material("doc-1", "2026-09-10T00:00:00+00:00"),
    _material("doc-2", "2026-10-25T00:00:00+00:00"),
]


def _request(**over) -> GuideRequest:
    fields = dict(
        course_id=COURSE, scope_kind="exam", scope_id="exam-1",
        material_ids=["doc-2", "doc-1"], goal="review", depth="deep", use_history=False,
    )
    return GuideRequest(**{**fields, **over})


@pytest.fixture
def world(monkeypatch):
    """The student's class: one offering, three scopes, three materials."""
    seen = {"offering": [], "scope": [], "inserted": []}
    state = {"scope": MIDTERM, "materials": MATERIALS, "unreadable": set()}

    async def aresolve_offering(user_id, course_id, semester):
        seen["offering"].append((user_id, course_id, semester))
        if course_id != COURSE:
            raise GuideNotFound("Class not found.")
        return OFFERING

    async def ascope_of(user_id, offering_id, scope_kind, scope_id):
        seen["scope"].append((user_id, offering_id, scope_kind, scope_id))
        if isinstance(state["scope"], Exception):
            raise state["scope"]
        return state["scope"]

    async def alist_scopes(user_id, offering_id):
        assert (user_id, offering_id) == (ME, OFFERING)
        return [WHOLE_COURSE, MIDTERM, HOMEWORK]

    async def alist_materials(user_id, offering_id):
        assert (user_id, offering_id) == (ME, OFFERING)
        return state["materials"]

    async def aload_sources(user_id, offering_id, material_ids):
        assert (user_id, offering_id) == (ME, OFFERING)
        return [doc_id for doc_id in material_ids if doc_id not in state["unreadable"]]

    async def per_process_limiter():
        return False

    async def acourse_names(course_ids):
        return {COURSE: "Intro to CS"} if COURSE in course_ids else {}

    async def ainsert_guide(**row):
        seen["inserted"].append(row)
        return "guide-new"

    for module in (create, options):
        monkeypatch.setattr(module.scopes, "aresolve_offering", aresolve_offering)
        monkeypatch.setattr(module.scopes, "ascope_of", ascope_of)
        monkeypatch.setattr(module.scopes, "alist_scopes", alist_scopes)
        monkeypatch.setattr(module.materials, "alist_materials", alist_materials)
    monkeypatch.setattr(create.materials, "aload_sources", aload_sources)
    monkeypatch.setattr(create.cards, "acourse_names", acourse_names)
    monkeypatch.setattr(request_limits, "_astateless", per_process_limiter)
    monkeypatch.setattr(request_limits, "_rate_state", {})
    monkeypatch.setattr(create.store, "ainsert_guide", ainsert_guide)
    return seen, state


# ── Create ────────────────────────────────────────────────────────────────────


def test_create_inserts_the_row_for_the_resolved_scope(world):
    seen, _ = world
    guide_id = asyncio.run(create.acreate_guide(ME, _request(semester="Fall 2026")))
    assert guide_id == "guide-new"
    assert seen["offering"] == [(ME, COURSE, "Fall 2026")]
    assert seen["scope"] == [(ME, OFFERING, "exam", "exam-1")]
    (row,) = seen["inserted"]
    content = row.pop("content")
    assert row == {
        "user_id": ME, "offering_id": OFFERING, "scope_kind": "exam", "exam_id": "exam-1",
        "goal": "review", "depth": "deep", "use_history": False,
        "material_ids": ["doc-1", "doc-2"],
    }
    assert (content.title, content.scope_label, content.sections) == ("Midterm 1", "Midterm 1", [])


def test_the_stored_kind_is_the_one_the_row_reads_as(world):
    seen, state = world
    state["scope"] = HOMEWORK
    asyncio.run(create.acreate_guide(ME, _request(scope_kind="exam", scope_id="hw-1")))
    assert (seen["inserted"][0]["scope_kind"], seen["inserted"][0]["exam_id"]) == ("assignment", "hw-1")


def test_a_whole_course_guide_is_titled_with_the_course_name(world):
    seen, state = world
    state["scope"] = WHOLE_COURSE
    asyncio.run(create.acreate_guide(ME, _request(scope_kind="course", scope_id=None)))
    (row,) = seen["inserted"]
    assert (row["scope_kind"], row["exam_id"]) == ("course", None)
    assert (row["content"].title, row["content"].scope_label) == ("Intro to CS", "Whole course")


def test_materials_from_elsewhere_are_dropped_and_the_rest_kept_oldest_first(world):
    seen, _ = world
    request = _request(material_ids=["doc-2", "someone-elses", "doc-2", "doc-syllabus"])
    asyncio.run(create.acreate_guide(ME, request))
    assert seen["inserted"][0]["material_ids"] == ["doc-syllabus", "doc-2"]


@pytest.mark.parametrize("chosen", [[], ["someone-elses"]])
def test_no_material_of_the_class_is_refused_before_any_insert(world, chosen):
    seen, _ = world
    with pytest.raises(GuideInvalid) as refused:
        asyncio.run(create.acreate_guide(ME, _request(material_ids=chosen)))
    assert refused.value.detail == "Choose at least one of this class's materials."
    assert seen["inserted"] == []


def test_materials_with_nothing_to_read_are_refused_before_any_insert(world):
    """A guide made only from documents with no text could never be written:
    generate would answer 422 for ever and the row would stay `generating`."""
    seen, state = world
    state["unreadable"] = {"doc-1", "doc-2"}

    with pytest.raises(GuideInvalid) as refused:
        asyncio.run(create.acreate_guide(ME, _request()))

    assert refused.value.detail == "None of these materials can be read yet."
    assert seen["inserted"] == [] and request_limits._rate_state == {}
    # One readable material is enough, and the others stay chosen.
    state["unreadable"] = {"doc-1"}
    asyncio.run(create.acreate_guide(ME, _request()))
    assert seen["inserted"][0]["material_ids"] == ["doc-1", "doc-2"]


def test_creating_guides_has_an_hourly_limit_of_its_own(world, monkeypatch):
    seen, _ = world
    assert limits.STUDY_GUIDE_CREATE_LIMIT == 60
    monkeypatch.setattr(limits, "STUDY_GUIDE_CREATE_LIMIT", 2)

    for _ in range(2):
        asyncio.run(create.acreate_guide(ME, _request()))
    with pytest.raises(GuideRateLimited) as limited:
        asyncio.run(create.acreate_guide(ME, _request()))

    assert limited.value.status_code == 429 and len(seen["inserted"]) == 2
    # Creating a guide does not spend the budget for writing one, and a
    # request that is refused for another reason is not counted.
    assert list(request_limits._rate_state) == [f"study-guide-create:{ME}"]
    with pytest.raises(GuideInvalid):
        asyncio.run(create.acreate_guide(ME, _request(material_ids=[])))
    assert len(request_limits._rate_state[f"study-guide-create:{ME}"]) == 2


def test_a_guide_that_could_not_be_inserted_is_not_counted(world, monkeypatch):
    seen, _ = world
    refunds: list[str] = []
    refund = limits.refund_rate_limit

    def counted(key, slot):
        refunds.append(key)
        refund(key, slot)

    async def failing_insert(**row):
        raise RuntimeError("the database is away")

    monkeypatch.setattr(limits, "refund_rate_limit", counted)
    key = f"study-guide-create:{ME}"

    # A guide that is made is counted, and nothing is given back for it.
    asyncio.run(create.acreate_guide(ME, _request()))
    assert len(request_limits._rate_state[key]) == 1 and refunds == []

    monkeypatch.setattr(create.store, "ainsert_guide", failing_insert)
    with pytest.raises(RuntimeError, match="the database is away"):
        asyncio.run(create.acreate_guide(ME, _request()))

    assert len(request_limits._rate_state[key]) == 1 and refunds == [key]
    assert len(seen["inserted"]) == 1


def test_a_class_the_student_is_not_in_is_not_found(world):
    seen, _ = world
    with pytest.raises(GuideNotFound):
        asyncio.run(create.acreate_guide(ME, _request(course_id="course-other")))
    assert seen["scope"] == [] and seen["inserted"] == []


@pytest.mark.parametrize("refusal", [
    GuideNotFound("That exam or assignment was not found. Pick another one."),
    GuideInvalid("A whole-course guide is not for one exam or assignment."),
])
def test_a_scope_that_does_not_hold_up_is_refused_before_any_insert(world, refusal):
    seen, state = world
    state["scope"] = refusal
    with pytest.raises(type(refusal)):
        asyncio.run(create.acreate_guide(ME, _request()))
    assert seen["inserted"] == []


def test_a_long_exam_title_is_cut_to_the_contracts_lengths(world):
    seen, state = world
    state["scope"] = Scope(kind="exam", id="exam-1", title="M" * 300, due_date=None)
    asyncio.run(create.acreate_guide(ME, _request()))
    content = seen["inserted"][0]["content"]
    assert (len(content.title), len(content.scope_label)) == (120, 200)


# ── Options ───────────────────────────────────────────────────────────────────


def test_options_list_the_whole_course_first_then_scopes_by_date(world):
    out = asyncio.run(options.aget_options(ME, COURSE, None))
    assert [(s.kind, s.id, s.title, s.due_date) for s in out.scopes] == [
        ("course", None, "Whole course", None),
        ("exam", "exam-1", "Midterm 1", "2026-10-20"),
        ("assignment", "hw-1", "Homework 3", "2026-11-02"),
    ]
    assert out.materials == MATERIALS


def test_each_scope_carries_its_suggested_materials(world):
    out = asyncio.run(options.aget_options(ME, COURSE, None))
    suggested = {scope.title: scope.suggested_material_ids for scope in out.scopes}
    assert suggested == {
        "Whole course": ["doc-syllabus", "doc-1", "doc-2"],
        # Up to the exam's date, never the syllabus.
        "Midterm 1": ["doc-1"],
        # Since the exam before it.
        "Homework 3": ["doc-2"],
    }


def test_options_resolve_the_offering_once(world):
    """The scopes are listed for the offering already resolved, not looked
    up again from the course and term."""
    seen, _ = world
    asyncio.run(options.aget_options(ME, COURSE, "Fall 2026"))
    assert seen["offering"] == [(ME, COURSE, "Fall 2026")]


def test_options_for_a_class_the_student_is_not_in_are_not_found(world):
    with pytest.raises(GuideNotFound):
        asyncio.run(options.aget_options(ME, "course-other", None))
