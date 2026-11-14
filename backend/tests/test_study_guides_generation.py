"""`services.study_guides.generation`: a run from prepare to `done`, against
the store's in-memory table.

The first tests run the three real agents through the function-mode seam (the
E2E lanes' handler), end to end. The rest script the writer, to reach the
failures and the update the handler cannot produce.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import anyio
import pytest

import agents._providers as providers
from agents._providers import clear_function_handlers, model_for
from agents.study_guide import (
    GuideOutline,
    study_guide_block_agent,
    study_guide_outline_agent,
    study_guide_section_agent,
)
from models.study_guide import (
    QUIZ_HISTORY_SOURCE,
    CheckBlock,
    CheckOption,
    GuideContent,
    MaterialOption,
    Paragraph,
    ProseItem,
    Section,
    Source,
)
from services import academics, events_service, request_limits
from services.encryption import decrypt_json, encrypt_json
from services.llm_budget import LLMBudgetExceeded
from services.study_guides import cards, generation, limits, materials, signals, store, writer
from services.study_guides.errors import (
    GuideBusy,
    GuideGenerationFailed,
    GuideInvalid,
    GuideNotFound,
    GuideRateLimited,
)
from services.study_guides.legacy import content_from_topics
from services.study_guides.materials import SourceText
from services.study_guides.signals import QuizMistake
from tests.db_fakes import TWINS
from tests.test_study_guides_materials import _Documents
from tests.test_study_guides_store import ME, OFFERING, FakeGuides

#: The real loader, before the `world` fixture stands in for it.
LOAD_SOURCES = materials.aload_sources

COURSE = "course-cs"
GUIDE = "g1"
MADE_AT = "2026-11-01T00:00:00+00:00"
CONCEPTS = ["Recursion", "Control Flow", "Variables and Types"]


def run(coro):
    return asyncio.run(coro)


# ── The world a run reads ─────────────────────────────────────────────────────


def _yielding_twins(fake):
    """The table's async verbs, each with a real await in it as a network
    call has, so a cancelled request is cancelled inside them too."""
    for twin, sync in TWINS:
        async def call(*args, _sync=sync, **kwargs):
            await asyncio.sleep(0)
            return getattr(fake, _sync)(*args, **kwargs)
        setattr(fake, twin, call)
    return fake


class World:
    """The student's documents, tree and quiz history, and what the run did
    to the outside: events logged and details built."""

    def __init__(self):
        self.db = FakeGuides()
        self.documents = {
            "doc-1": ("recursion.pdf", "A recursive function calls itself.", CONCEPTS),
        }
        self.lectures: list[dict] = []
        self.scores = {"Recursion": 0.2, "Control Flow": 0.5, "Variables and Types": 0.9}
        self.mistakes: list[QuizMistake] = []
        self.logged: list[dict] = []

    async def aload_sources(self, user_id, offering_id, material_ids):
        assert offering_id == OFFERING
        found = [doc_id for doc_id in self.documents if doc_id in material_ids]
        return [
            SourceText(
                label=f"S{number}",
                source=Source(id=f"document:{doc_id}", name=self.documents[doc_id][0], kind="PDF"),
                concepts=list(self.documents[doc_id][2]),
                text=self.documents[doc_id][1],
            )
            for number, doc_id in enumerate(found, start=1)
        ]

    async def alist_lecture_docs(self, user_id):
        return list(self.lectures)

    async def alist_materials(self, user_id, offering_id):
        return [
            MaterialOption(id=doc_id, file_name=name, category="lecture_notes", created_at=MADE_AT)
            for doc_id, (name, _, _) in self.documents.items()
        ]

    async def amastery(self, user_id, course_id):
        assert course_id == COURSE
        return dict(self.scores)

    async def amistakes(self, user_id, course_id, concepts):
        return list(self.mistakes)

    def guide(self, **over) -> dict:
        """A new guide, as `create` leaves it: nothing written yet."""
        fields = dict(
            status="generating", generated_at=None, material_ids=["doc-1"],
            content=encrypt_json(
                GuideContent(title="Midterm 1", scope_label="Midterm 1").model_dump(mode="json")),
        )
        return self.db.add(over.pop("guide_id", GUIDE), **{**fields, **over})

    def stored(self, guide_id: str = GUIDE) -> dict:
        return self.db.stored(guide_id)

    def content(self, guide_id: str = GUIDE) -> GuideContent:
        row = self.stored(guide_id)
        stored = decrypt_json(row["content"])
        if row["format"] == 1:
            return content_from_topics(stored)
        return GuideContent.model_validate(stored)


@pytest.fixture
def world(monkeypatch):
    world = World()
    handle = _yielding_twins(world.db)
    monkeypatch.setattr(store, "table", lambda name: {"study_guides": handle}[name])
    monkeypatch.setattr(materials, "aload_sources", world.aload_sources)
    monkeypatch.setattr(materials, "alist_lecture_docs", world.alist_lecture_docs)
    monkeypatch.setattr(materials, "alist_materials", world.alist_materials)
    monkeypatch.setattr(signals, "amastery", world.amastery)
    monkeypatch.setattr(signals, "amistakes", world.amistakes)
    # The real lookup (cached per process), reading one offering row.
    offerings = SimpleNamespace(select=lambda *args, **kwargs: [{"course_id": COURSE}])
    monkeypatch.setattr(academics, "table", lambda name: {"course_offerings": offerings}[name])

    async def abuild_detail(guide):
        # The real one is the serving side's; the run only forwards its dump.
        return SimpleNamespace(model_dump=lambda mode: {
            "id": guide.id, "status": guide.status, "generated_at": guide.generated_at,
        })

    monkeypatch.setattr(generation, "abuild_detail", abuild_detail)
    monkeypatch.setattr(
        events_service, "log_event", lambda name, **kwargs: world.logged.append({"name": name, **kwargs}),
    )

    async def per_process_limiter():
        return False

    monkeypatch.setattr(request_limits, "_astateless", per_process_limiter)
    monkeypatch.setattr(request_limits, "_rate_state", {})
    return world


@pytest.fixture
def function_mode(monkeypatch):
    """The three agents on the function-mode seam, served by the E2E handler."""
    clear_function_handlers()
    monkeypatch.setattr(providers, "_ENV_HANDLERS_LOADED", False)
    sys.modules.pop("agents.function_handlers_e2e", None)
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv("SAPLING_FUNCTION_HANDLERS", "agents.function_handlers_e2e")
    model = model_for("study_guide")
    with (
        study_guide_outline_agent.override(model=model),
        study_guide_section_agent.override(model=model),
        study_guide_block_agent.override(model=model),
    ):
        yield
    clear_function_handlers()
    sys.modules.pop("agents.function_handlers_e2e", None)


async def _follow(world: World, mode: str = "resume", guide_id: str = GUIDE):
    """Prepare and run to the end. Returns the events, and beside each one
    what the row held when it arrived."""
    prepared = await generation.aprepare_generation(ME, guide_id, mode)
    events, rows = [], []
    async for event in generation.stream_generation(prepared):
        events.append(event)
        rows.append({**world.stored(guide_id), "content": world.content(guide_id)})
    return events, rows


def _shape(events) -> list[tuple]:
    return [(e.type, e.step) for e in events]


def _sections_sent(events) -> list[str]:
    return [e.message for e in events if (e.type, e.step) == ("progress", "section")]


# ── A whole run through the function-mode seam ────────────────────────────────


def test_a_new_guide_is_written_outline_first_then_section_by_section(world, function_mode):
    world.guide()

    events, rows = run(_follow(world))

    assert _shape(events) == [
        ("status", "read"),
        ("status", "outline"),
        ("progress", "outline"),
        ("status", "section"), ("progress", "section"),
        ("status", "section"), ("progress", "section"),
        ("status", "section"), ("progress", "section"),
        ("status", "check"),
        ("done", "done"),
    ]
    statuses = [(e.message, e.data) for e in events if e.type == "status"]
    assert statuses == [
        # Until the outline is planned the guide may have the depth's five.
        ("Reading your 1 material", {"step": 1, "total": 8}),
        ("Planning the outline", {"step": 2, "total": 8}),
        ("Outline ready. Writing section 1 of 3", {"step": 3, "total": 6}),
        ("Writing section 2 of 3: Control flow", {"step": 4, "total": 6}),
        ("Writing section 3 of 3: Variables and types", {"step": 5, "total": 6}),
        ("Checking citations and blocks", {"step": 6, "total": 6}),
    ]


def test_the_outline_event_is_the_saved_guide_with_every_section_queued(world, function_mode):
    world.guide()

    events, rows = run(_follow(world))

    outline = GuideContent.model_validate(events[2].data["content"])
    # Saved before it was sent.
    assert rows[2]["content"] == outline
    assert rows[2]["status"] == "generating"
    assert outline.title == "Recursion and what it builds on"
    assert outline.deck == "Three sections written from your own course material."
    assert len(outline.takeaways) == 3
    assert outline.scope_label == "Midterm 1"
    assert outline.sources == [Source(id="document:doc-1", name="recursion.pdf", kind="PDF")]
    # Ids, tiers and weights are the server's: struggling 5, learning 3, mastered 1.
    assert [(s.id, s.title, s.concept, s.tier, s.weight, s.status) for s in outline.sections] == [
        ("s1", "Recursion", "Recursion", "struggling", 56, "queued"),
        ("s2", "Control flow", "Control Flow", "learning", 33, "queued"),
        ("s3", "Variables and types", "Variables and Types", "mastered", 11, "queued"),
    ]
    assert all(section.items == [] and section.one_line for section in outline.sections)


def test_each_section_is_saved_before_its_event_and_checks_are_withheld(world, function_mode):
    world.guide()

    events, rows = run(_follow(world))

    sent = [(Section.model_validate(e.data["section"]), row["content"])
            for e, row in zip(events, rows) if (e.type, e.step) == ("progress", "section")]
    assert [section.id for section, _ in sent] == ["s1", "s2", "s3"]
    for number, (section, saved) in enumerate(sent, start=1):
        stored = saved.sections[number - 1]
        assert (section.status, stored.status) == ("written", "written")
        # The sections after it are still to come.
        assert [s.status for s in saved.sections[number:]] == ["queued"] * (3 - number)
        assert [item.type for item in section.items] == [
            "prose", "formula", "worked_example", "prose",
            "comparison", "key_terms", "concept_map", "check",
        ]
        assert [item.id for item in section.items] == [f"s{number}-i{n}" for n in range(1, 9)]
        # The stored check has its answer; the one sent to the reader does not.
        assert (stored.items[-1].correct_id, stored.items[-1].explain_correct is None) == ("b", False)
        check = section.items[-1]
        assert (check.correct_id, check.explain_correct, check.explain_incorrect) == (None, None, None)
        assert {**stored.model_dump(), "items": None} == {**section.model_dump(), "items": None}
        assert stored.items[:-1] == section.items[:-1]
    first = sent[0][0]
    assert first.items[0].paragraphs[0].citations == ["document:doc-1"]
    assert first.items[1].source_id == "document:doc-1"


def test_a_finished_guide_is_ready_with_no_queued_section_and_the_claim_free(world, function_mode):
    world.guide()

    events, rows = run(_follow(world))

    row = world.stored()
    assert row["status"] == "ready"
    # Dated from when it was made, which is when its materials were chosen.
    assert row["generated_at"] == row["created_at"]
    assert row["generating_at"] is None
    assert row["material_ids"] == ["doc-1"]
    assert row["previous_content"] is None and row["answers"] is None
    assert [s.status for s in world.content().sections] == ["written"] * 3
    # The claim was held for the whole run, refreshed along the way, and
    # given up with the last save: the guide is free when `done` arrives.
    held = [r["generating_at"] for r in rows]
    assert all(held[:-1]) and len(set(held)) > 3
    assert (events[-1].type, held[-1], rows[-1]["status"]) == ("done", None, "ready")
    assert events[-1].data == {
        "guide": {"id": GUIDE, "status": "ready", "generated_at": row["generated_at"]},
    }


def test_a_finished_run_is_logged_with_counts_and_enums_only(world, function_mode):
    world.guide()

    run(_follow(world))

    (event,) = world.logged
    assert (event["name"], event["category"], event["user_id"]) == (
        "study_guide.generated", "usage", ME)
    assert event["payload"] == {
        "guide_id": GUIDE, "mode": "resume", "scope_kind": "exam", "goal": "exam_prep",
        "depth": "standard", "use_history": True, "sources": 1,
        "sections": 3, "sections_written": 3, "sections_failed": 0,
    }


def test_without_history_every_section_is_unexplored_and_equal(world, function_mode):
    world.guide(use_history=False)
    world.mistakes = [QuizMistake(id="m1", concept="Recursion", text="Never offered")]

    run(_follow(world))

    content = world.content()
    assert [(s.concept, s.tier, s.weight) for s in content.sections] == [
        ("Recursion", "unexplored", 34),
        ("Control Flow", "unexplored", 33),
        ("Variables and Types", "unexplored", 33),
    ]
    assert QUIZ_HISTORY_SOURCE not in [source.id for source in content.sources]


def test_concepts_the_tree_does_not_have_are_cleared(world, function_mode):
    world.guide()
    world.scores = {"recursion": 0.9}

    run(_follow(world))

    sections = world.content().sections
    # The tree's own spelling where it has the concept, nothing where it has not.
    assert [(s.concept, s.tier) for s in sections] == [
        ("recursion", "mastered"), (None, "unexplored"), (None, "unexplored")]
    for section in sections:
        kinds = [item.type for item in section.items]
        # One known concept is not a map.
        assert "concept_map" not in kinds
        assert section.items[-1].type == "check" and section.items[-1].concept == "recursion"


def test_the_outline_is_not_capped_by_the_concepts_the_materials_name(world, function_mode):
    """The outline is planned from the source text. A class whose one
    document names one concept still gets the sections the depth allows."""
    world.documents["doc-1"] = ("recursion.pdf", "A recursive function calls itself.", ["Recursion"])
    world.guide(depth="cram")

    run(_follow(world))

    assert [s.title for s in world.content().sections] == [
        "Recursion", "Control flow", "Variables and types"]


def test_quiz_history_is_a_source_when_there_are_mistakes_to_cite(world, function_mode):
    world.guide()
    world.mistakes = [QuizMistake(id="m1", concept="Recursion", text="Forgets the base case")]

    run(_follow(world))

    assert world.content().sources[-1] == Source(
        id=QUIZ_HISTORY_SOURCE, name="Your quiz history", kind="Sapling")


def test_regenerate_keeps_the_previous_version_and_clears_read_state_and_answers(
    world, function_mode,
):
    old = _written_guide()
    world.guide(
        status="ready", generated_at=MADE_AT, content=encrypt_json(old.model_dump(mode="json")),
        read_sections=["s1"], answers=encrypt_json({"s1-i2": {"option_id": "a", "correct": False}}),
    )

    events, rows = run(_follow(world, "regenerate"))

    row = world.stored()
    assert GuideContent.model_validate(decrypt_json(row["previous_content"])) == old
    assert row["read_sections"] == [] and row["answers"] is None
    assert row["status"] == "ready" and row["generated_at"] != MADE_AT
    content = world.content()
    assert content.title == "Recursion and what it builds on"
    # Numbered after the old guide's `s1` and `s2`: no id is used twice, so
    # an answer or a read mark sent for the old guide finds nothing to land on.
    assert [(s.id, s.status) for s in content.sections] == [
        ("s3", "written"), ("s4", "written"), ("s5", "written")]
    old_ids = {item.id for section in old.sections for item in section.items}
    assert not old_ids & {item.id for section in content.sections for item in section.items}
    assert _shape(events)[:3] == [("status", "read"), ("status", "outline"), ("progress", "outline")]
    # The outline is sent, but nothing is replaced until a section is written.
    assert GuideContent.model_validate(events[2].data["content"]).title == content.title
    for row in rows[:4]:
        assert row["content"] == old and row["status"] == "ready"
        assert row["previous_content"] is None and row["read_sections"] == ["s1"]
    # The first written section is saved before its event, with the old
    # version beside it.
    assert _shape(events)[4] == ("progress", "section")
    assert [s.status for s in rows[4]["content"].sections] == ["written", "queued", "queued"]
    assert rows[4]["status"] == "generating" and rows[4]["previous_content"] is not None
    assert world.logged[0]["payload"]["mode"] == "regenerate"


def test_a_guide_from_before_the_redesign_is_regenerated_from_the_classs_materials(
    world, function_mode,
):
    legacy = {"exam": "Midterm 1", "overview": "Loops.", "topics": [
        {"name": "Loops", "importance": "Traced on every exam.", "concepts": ["while"]}]}
    world.guide(status="ready", generated_at=MADE_AT, format=1, material_ids=[],
                content=encrypt_json(legacy))

    run(_follow(world, "regenerate"))

    row = world.stored()
    assert (row["format"], row["status"], row["material_ids"]) == (2, "ready", ["doc-1"])
    previous = GuideContent.model_validate(decrypt_json(row["previous_content"]))
    assert [s.title for s in previous.sections] == ["Loops"]
    assert len(world.content().sections) == 3


# ── Scripted writers ──────────────────────────────────────────────────────────


def _prose(section_id: str, text: str = "Written.") -> ProseItem:
    return ProseItem(id=f"{section_id}-i1", paragraphs=[Paragraph(text=text)], summary="Short.")


def _check(section_id: str, concept: str | None = "Recursion") -> CheckBlock:
    return CheckBlock(
        id=f"{section_id}-i2", question="What does factorial(3) return?",
        options=[CheckOption(id="a", text="3"), CheckOption(id="b", text="6"),
                 CheckOption(id="c", text="9")],
        correct_id="b", explain_correct="3 times 2 times 1.", explain_incorrect="Trace the calls.",
        concept=concept,
    )


def _written_guide() -> GuideContent:
    """A finished guide of two sections, each a passage and a check."""
    sections = [
        Section(id=section_id, title=title, concept=concept, tier="learning", weight=50,
                one_line=f"{title} in one line.", status="written",
                items=[_prose(section_id, f"About {title}."), _check(section_id, concept)])
        for section_id, title, concept in (("s1", "Recursion", "Recursion"),
                                           ("s2", "Control flow", "Control Flow"))
    ]
    return GuideContent(
        title="My midterm guide", deck="Two sections.", takeaways=["One.", "Two.", "Three."],
        sections=sections, scope_label="Midterm 1",
        sources=[Source(id="document:doc-1", name="recursion.pdf", kind="PDF")],
    )


def _outline(*sections: dict, title: str = "Planned") -> GuideOutline:
    return GuideOutline(title=title, deck="A deck.", takeaways=["One.", "Two.", "Three."],
                        sections=list(sections))


def _planned(title: str, concept: str | None = None, keep_id: str | None = None) -> dict:
    return {"title": title, "concept": concept, "one_line": f"{title} in one line.",
            "keep_id": keep_id}


class Script:
    """Stands in for `writer`: one outline, and per section title either
    items to return or an exception to raise. Records what it was asked."""

    def __init__(self, monkeypatch, outline=None, sections=None):
        self.outline = outline
        self.sections = sections or {}
        self.outline_calls: list[dict] = []
        self.written: list[str] = []
        #: The source ids each section's writer was offered.
        self.offered: list[list[str]] = []
        monkeypatch.setattr(writer, "awrite_outline", self.awrite_outline)
        monkeypatch.setattr(writer, "awrite_section", self.awrite_section)

    async def awrite_outline(self, brief, **kwargs):
        self.outline_calls.append({"brief": brief, **kwargs})
        if isinstance(self.outline, BaseException):
            raise self.outline
        return self.outline

    async def awrite_section(self, brief, content, section, *, deps, beat):
        self.written.append(section.title)
        self.offered.append([source.source.id for source in brief.sources])
        result = self.sections.get(section.title, "prose")
        if isinstance(result, BaseException):
            raise result
        if result == "prose":
            return [_prose(section.id)]
        return result(section) if callable(result) else result


def _budget_refusal() -> LLMBudgetExceeded:
    return LLMBudgetExceeded(limit=10, used=11,
                             reset_at=datetime.now(timezone.utc) + timedelta(hours=3))


# ── Failures ──────────────────────────────────────────────────────────────────


def test_a_section_the_writer_fails_on_is_marked_failed_and_the_run_finishes(world, monkeypatch):
    world.guide()
    Script(
        monkeypatch,
        outline=_outline(_planned("One"), _planned("Two"), _planned("Three")),
        sections={"Two": GuideGenerationFailed("no")},
    )

    events, rows = run(_follow(world))

    assert _shape(events)[-2:] == [("status", "check"), ("done", "done")]
    sent = [e.data["section"] for e in events if (e.type, e.step) == ("progress", "section")]
    assert [(s["id"], s["status"]) for s in sent] == [
        ("s1", "written"), ("s2", "failed"), ("s3", "written")]
    assert [(s.status, len(s.items)) for s in world.content().sections] == [
        ("written", 1), ("failed", 0), ("written", 1)]
    assert world.stored()["status"] == "ready"
    payload = world.logged[0]["payload"]
    assert (payload["sections_written"], payload["sections_failed"]) == (2, 1)


def test_a_section_with_nothing_left_after_the_check_is_failed(world, monkeypatch):
    world.guide()

    def ungradable(section):
        return [_check(section.id).model_copy(update={"correct_id": None})]

    Script(monkeypatch, outline=_outline(_planned("One"), _planned("Two")),
           sections={"One": ungradable})

    run(_follow(world))

    assert [(s.status, len(s.items)) for s in world.content().sections] == [
        ("failed", 0), ("written", 1)]


def test_resume_retries_the_failed_and_queued_sections_only(world, monkeypatch):
    content = _written_guide()
    content.sections[1] = content.sections[1].model_copy(update={"status": "failed", "items": []})
    content.sections.append(Section(id="s3", title="Types", weight=0, status="queued"))
    world.guide(status="ready", generated_at=MADE_AT,
                content=encrypt_json(content.model_dump(mode="json")), read_sections=["s1"])
    script = Script(monkeypatch)

    events, rows = run(_follow(world))

    assert script.outline_calls == [] and script.written == ["Control flow", "Types"]
    assert _shape(events) == [
        ("status", "read"),
        ("status", "section"), ("progress", "section"),
        ("status", "section"), ("progress", "section"),
        ("status", "check"), ("done", "done"),
    ]
    assert [(e.message, e.data) for e in events if e.type == "status"] == [
        ("Reading your 1 material", {"step": 1, "total": 4}),
        ("Writing section 2 of 3: Control flow", {"step": 2, "total": 4}),
        ("Writing section 3 of 3: Types", {"step": 3, "total": 4}),
        ("Checking citations and blocks", {"step": 4, "total": 4}),
    ]
    after = world.content()
    assert after.sections[0] == content.sections[0]
    assert [s.status for s in after.sections] == ["written"] * 3
    row = world.stored()
    assert (row["status"], row["read_sections"], row["previous_content"]) == ("ready", ["s1"], None)


def test_a_cut_run_whose_sections_were_all_written_is_just_finished(world, monkeypatch):
    world.guide(content=encrypt_json(_written_guide().model_dump(mode="json")))
    script = Script(monkeypatch)

    events, _ = run(_follow(world))

    assert script.written == []
    assert _shape(events) == [("status", "read"), ("status", "check"), ("done", "done")]
    assert world.stored()["status"] == "ready" and world.stored()["generated_at"]


def test_a_failing_outline_ends_in_an_error_and_a_failed_guide(world, monkeypatch):
    world.guide()
    Script(monkeypatch, outline=GuideGenerationFailed("no"))

    events, _ = run(_follow(world))

    assert _shape(events) == [("status", "read"), ("status", "outline"), ("error", "error")]
    assert events[-1].data == {"retryable": True}
    assert events[-1].message == writer.FAILED_DETAIL
    row = world.stored()
    assert (row["status"], row["generated_at"], row["generating_at"]) == ("failed", None, None)
    assert world.logged == []


def test_a_failed_guide_can_be_resumed(world, monkeypatch):
    world.guide(status="failed")
    Script(monkeypatch, outline=_outline(_planned("One")))

    events, _ = run(_follow(world))

    assert events[-1].type == "done" and world.stored()["status"] == "ready"


def test_a_run_that_writes_no_section_fails_the_guide(world, monkeypatch):
    world.guide()
    Script(monkeypatch, outline=_outline(_planned("One"), _planned("Two")),
           sections={"One": GuideGenerationFailed("no"), "Two": GuideGenerationFailed("no")})

    events, _ = run(_follow(world))

    assert _shape(events)[-1] == ("error", "error") and events[-1].data == {"retryable": True}
    assert ("status", "check") not in _shape(events)
    row = world.stored()
    assert (row["status"], row["generated_at"], row["generating_at"]) == ("failed", None, None)
    assert [s.status for s in world.content().sections] == ["failed", "failed"]


def test_a_budget_refusal_is_an_error_that_cannot_be_retried(world, monkeypatch):
    world.guide()
    refusal = _budget_refusal()
    Script(monkeypatch, outline=refusal)

    events, _ = run(_follow(world))

    assert _shape(events)[-1] == ("error", "error")
    assert events[-1].data == {"retryable": False}
    assert events[-1].message == refusal.detail
    assert world.stored()["status"] == "failed" and world.stored()["generating_at"] is None


def test_a_regenerate_whose_outline_fails_leaves_the_guide_as_it_was(world, monkeypatch):
    old = _written_guide()
    world.guide(status="ready", generated_at=MADE_AT, read_sections=["s1"],
                content=encrypt_json(old.model_dump(mode="json")))
    Script(monkeypatch, outline=GuideGenerationFailed("no"))

    events, _ = run(_follow(world, "regenerate"))

    assert events[-1].type == "error" and events[-1].data == {"retryable": True}
    row = world.stored()
    assert world.content() == old
    assert (row["status"], row["generated_at"], row["read_sections"]) == ("ready", MADE_AT, ["s1"])
    assert row["previous_content"] is None and row["generating_at"] is None


def test_an_unexpected_error_is_an_error_event_not_an_exception(world, monkeypatch, caplog):
    world.guide()
    Script(monkeypatch, outline=_outline(_planned("One")), sections={"One": RuntimeError("boom")})

    events, _ = run(_follow(world))

    assert events[-1].type == "error" and events[-1].data == {"retryable": True}
    assert "boom" not in events[-1].message
    assert world.stored()["status"] == "failed" and world.stored()["generating_at"] is None
    assert any("generation failed" in record.getMessage() for record in caplog.records)


# ── A run that replaces a guide ───────────────────────────────────────────────


def _ready(world: World, **over) -> GuideContent:
    """A finished guide the student has read and answered on."""
    old = _written_guide()
    fields = dict(
        status="ready", generated_at=MADE_AT, read_sections=["s1"],
        content=encrypt_json(old.model_dump(mode="json")),
        answers=encrypt_json({"s1-i2": {"option_id": "a", "correct": False}}),
    )
    world.guide(**{**fields, **over})
    return old


def _unchanged(world: World, before: dict) -> bool:
    """Whether the row is as it was, the claim's own stamps aside."""
    after = world.stored()
    return {**after, "updated_at": None} == {**before, "updated_at": None}


@pytest.mark.parametrize(
    ("failure", "retryable"),
    [(GuideGenerationFailed("no"), True), (RuntimeError("boom"), True), ("budget", False)],
    ids=["every section fails", "an unexpected error", "the daily budget"],
)
def test_a_regenerate_that_writes_no_section_leaves_the_guide_exactly_as_it_was(
    world, monkeypatch, failure, retryable,
):
    """The new outline is planned and sent, then the first section cannot be
    written. The student still has the guide they had."""
    _ready(world)
    before = dict(world.stored())
    failure = _budget_refusal() if failure == "budget" else failure
    Script(monkeypatch, outline=_outline(_planned("One"), _planned("Two")),
           sections={"One": failure, "Two": failure})

    events, rows = run(_follow(world, "regenerate"))

    assert ("progress", "outline") in _shape(events)
    assert _shape(events)[-1] == ("error", "error")
    assert events[-1].data == {"retryable": retryable}
    assert _unchanged(world, before)
    # Not for a moment was it anything else.
    assert all(row["content"] == rows[0]["content"] and row["status"] == "ready" for row in rows)


def test_an_update_that_writes_no_section_leaves_the_guide_exactly_as_it_was(world, monkeypatch):
    _updatable(world)
    before = dict(world.stored())
    Script(monkeypatch, sections={"Types": GuideGenerationFailed("no")}, outline=_outline(
        _planned("Recursion", keep_id="s1"), _planned("Types")))

    events, _ = run(_follow(world, "update"))

    assert _shape(events)[-1] == ("error", "error")
    assert _unchanged(world, before)
    # The lecture was not folded in, so it is still new.
    assert world.stored()["material_ids"] == ["doc-1"]


def test_a_regenerate_that_fails_after_a_section_can_be_resumed(world, monkeypatch):
    old = _ready(world)
    script = Script(monkeypatch, outline=_outline(_planned("One"), _planned("Two")),
                    sections={"Two": RuntimeError("boom")})
    started = datetime.now(timezone.utc)

    events, _ = run(_follow(world, "regenerate"))

    row = world.stored()
    assert events[-1].type == "error" and row["status"] == "failed"
    assert [s.status for s in world.content().sections] == ["written", "queued"]
    assert GuideContent.model_validate(decrypt_json(row["previous_content"])) == old
    # The first section replaced the guide, and with it the materials and
    # when they were read: the two always change together.
    replaced_at = row["generated_at"]
    assert datetime.fromisoformat(replaced_at) >= started
    script.sections.clear()
    events, _ = run(_follow(world))
    assert events[-1].type == "done" and script.written == ["One", "Two", "Two"]
    assert [s.status for s in world.content().sections] == ["written", "written"]
    # The resume read nothing new, so the date is still the regenerate's.
    assert world.stored()["generated_at"] == replaced_at


@pytest.mark.parametrize("left_as", ["generating", "failed"])
def test_a_resume_that_finishes_a_cut_update_keeps_the_updates_date(world, monkeypatch, left_as):
    """The Update saved its first section and its stream was cut (the row
    stays `generating`), or it failed there. Its first save dated the guide
    from when it read the new lecture; the resume reads nothing new, so it
    leaves that date alone."""
    _updatable(world)
    outline = _outline(_planned("Recursion", keep_id="s1"), _planned("Types"), _planned("Scope"))
    script = Script(monkeypatch, outline=outline, sections={"Scope": RuntimeError("boom")})
    started = datetime.now(timezone.utc)
    run(_follow(world, "update"))
    updated_at = world.stored()["generated_at"]
    assert world.stored()["status"] == "failed"
    assert world.stored()["material_ids"] == ["doc-1", "doc-2"]
    assert datetime.fromisoformat(updated_at) >= started
    world.stored()["status"] = left_as

    script.sections.clear()
    events, _ = run(_follow(world))

    row = world.stored()
    assert events[-1].type == "done" and row["status"] == "ready"
    assert row["generated_at"] == updated_at
    assert events[-1].data["guide"]["generated_at"] == row["generated_at"]


def test_a_resume_with_nothing_left_to_write_makes_the_guide_ready_and_keeps_its_date(
    world, monkeypatch,
):
    """Every section was saved, and the run was cut before its last write."""
    world.guide(generated_at=MADE_AT, content=encrypt_json(_written_guide().model_dump(mode="json")))
    script = Script(monkeypatch)

    events, _ = run(_follow(world))

    assert events[-1].type == "done" and script.written == []
    assert (world.stored()["status"], world.stored()["generated_at"]) == ("ready", MADE_AT)


def test_a_lecture_uploaded_while_an_update_writes_is_new_after_it(world, monkeypatch):
    """The Update read its lectures before it started writing. One uploaded
    while it wrote was not read, so the next Update must still find it."""
    _updatable(world)
    world.documents["doc-3"] = ("lecture-10.pdf", "Scope is lexical.", ["Scope"])

    def upload_while_writing(section):
        world.lectures.append({"id": "doc-3", "offering_id": OFFERING,
                               "created_at": datetime.now(timezone.utc).isoformat()})
        return [_prose(section.id)]

    Script(monkeypatch, sections={"Types": upload_while_writing},
           outline=_outline(_planned("Recursion", keep_id="s1"), _planned("Types")))

    events, _ = run(_follow(world, "update"))

    assert events[-1].type == "done"
    guide = run(store.aload_guide(ME, GUIDE))
    assert guide.material_ids == ["doc-1", "doc-2"]
    assert run(generation.anew_lectures(guide)) == ["doc-3"]


def test_a_lecture_uploaded_before_a_new_guide_is_first_opened_is_new_after_it(world, monkeypatch):
    """The guide was made from the materials chosen when it was created. A
    lecture uploaded before the student first opened it (which is when the
    guide is written) was never read, so it is new once the guide is."""
    world.guide()
    world.documents["doc-2"] = ("lecture-9.pdf", "Types are checked at run time.", ["Types"])
    world.lectures = [{"id": "doc-2", "offering_id": OFFERING,
                       "created_at": datetime.now(timezone.utc).isoformat()}]
    Script(monkeypatch, outline=_outline(_planned("One")))

    events, _ = run(_follow(world))

    row = world.stored()
    assert events[-1].type == "done" and row["status"] == "ready"
    # Dated from when the guide was made, not from when it was written.
    assert row["generated_at"] == row["created_at"]
    assert run(generation.anew_lectures(run(store.aload_guide(ME, GUIDE)))) == ["doc-2"]


def test_a_failed_first_section_is_not_saved_until_a_later_one_is_written(world, monkeypatch):
    old = _ready(world)
    Script(monkeypatch, outline=_outline(_planned("One"), _planned("Two")),
           sections={"One": GuideGenerationFailed("no")})

    events, rows = run(_follow(world, "regenerate"))

    sections = [(e, row) for e, row in zip(events, rows) if (e.type, e.step) == ("progress", "section")]
    (failed, held), (written, saved) = sections
    # The reader is told about the failed section, and the row still holds
    # the old guide.
    assert failed.data["section"]["status"] == "failed" and held["content"] == old
    assert written.data["section"]["status"] == "written"
    assert [s.status for s in saved["content"].sections] == ["failed", "written"]
    row = world.stored()
    assert row["status"] == "ready" and events[-1].type == "done"
    assert GuideContent.model_validate(decrypt_json(row["previous_content"])) == old


def test_the_previous_version_is_never_a_half_written_guide(world, monkeypatch):
    """A regenerate that failed half way left a guide that is not worth
    keeping. The next one must not put it where the last good version is."""
    old = _ready(world)
    script = Script(monkeypatch, outline=_outline(_planned("One"), _planned("Two")),
                    sections={"Two": RuntimeError("boom")})
    run(_follow(world, "regenerate"))
    assert world.stored()["status"] == "failed"

    script.sections.clear()
    events, _ = run(_follow(world, "regenerate"))

    row = world.stored()
    assert events[-1].type == "done" and row["status"] == "ready"
    assert GuideContent.model_validate(decrypt_json(row["previous_content"])) == old


def test_a_guide_with_nothing_written_has_no_previous_version_to_keep(world, monkeypatch):
    world.guide(status="failed")
    Script(monkeypatch, outline=_outline(_planned("One")))

    events, _ = run(_follow(world, "regenerate"))

    assert events[-1].type == "done" and world.stored()["previous_content"] is None


# ── Filling in what a finished guide is missing ───────────────────────────────


def _missing_one(world: World) -> GuideContent:
    """A finished guide whose second section failed."""
    content = _written_guide()
    content.sections[1] = content.sections[1].model_copy(update={"status": "failed", "items": []})
    world.guide(status="ready", generated_at=MADE_AT, read_sections=["s1"],
                content=encrypt_json(content.model_dump(mode="json")))
    return content


def test_retrying_a_failed_section_never_makes_a_readable_guide_unreadable(world, monkeypatch):
    content = _missing_one(world)
    Script(monkeypatch, sections={"Control flow": GuideGenerationFailed("no")})

    events, rows = run(_follow(world))

    # The section failed again: the guide is finished as it stands.
    assert _shape(events)[-2:] == [("status", "check"), ("done", "done")]
    assert all(row["status"] == "ready" for row in rows)
    assert world.content() == content and world.stored()["status"] == "ready"


def test_a_refusal_while_retrying_a_section_leaves_the_guide_ready(world, monkeypatch):
    content = _missing_one(world)
    Script(monkeypatch, sections={"Control flow": _budget_refusal()})

    events, _ = run(_follow(world))

    assert events[-1].type == "error" and events[-1].data == {"retryable": False}
    row = world.stored()
    assert (row["status"], row["generating_at"]) == ("ready", None)
    assert world.content() == content


def test_filling_in_a_section_keeps_the_guide_ready_and_its_date(world, monkeypatch):
    """`generated_at` is what a lecture is new against. A resume read no new
    lecture, so it must not make the ones added since look folded in."""
    _missing_one(world)
    Script(monkeypatch)

    events, rows = run(_follow(world))

    assert events[-1].type == "done" and all(row["status"] == "ready" for row in rows)
    assert [s.status for s in world.content().sections] == ["written", "written"]
    assert world.stored()["generated_at"] == MADE_AT


# ── Update ────────────────────────────────────────────────────────────────────


def _updatable(world: World, **over) -> GuideContent:
    """A finished guide, and a lecture uploaded after it was made."""
    old = _written_guide()
    world.documents["doc-2"] = ("lecture-9.pdf", "Types are checked at run time.", ["Types"])
    world.lectures = [{"id": "doc-2", "offering_id": OFFERING,
                       "created_at": "2026-11-05T00:00:00+00:00"}]
    fields = dict(
        status="ready", generated_at=MADE_AT, content=encrypt_json(old.model_dump(mode="json")),
        read_sections=["s1", "s2"],
        answers=encrypt_json({"s1-i2": {"option_id": "b", "correct": True},
                              "s2-i2": {"option_id": "a", "correct": False}}),
    )
    world.guide(**{**fields, **over})
    return old


def test_update_keeps_the_sections_the_outline_keeps_with_their_state(world, monkeypatch):
    old = _updatable(world)
    script = Script(monkeypatch, outline=_outline(
        _planned("Recursion", "Recursion", keep_id="s1"),
        _planned("Types", "Variables and Types"),
        _planned("Control flow, again", "Control Flow"),
        title="A new name",
    ))

    events, rows = run(_follow(world, "update"))

    content, row = world.content(), world.stored()
    kept, types, rewritten = content.sections
    # The kept section is the old one, item for item; only its share moved.
    assert kept == old.sections[0].model_copy(update={"weight": kept.weight})
    # New sections are numbered after every id the guide had, so nothing the
    # student did on old `s2` can land on a new section.
    assert [(s.id, s.status, s.tier) for s in (types, rewritten)] == [
        ("s3", "written", "mastered"), ("s4", "written", "learning")]
    assert sum(s.weight for s in content.sections) == 100
    assert content.title == "My midterm guide" and content.deck == "A deck."
    assert [s.id for s in content.sources] == ["document:doc-1", "document:doc-2"]
    assert row["material_ids"] == ["doc-1", "doc-2"]
    assert row["read_sections"] == ["s1"]
    assert decrypt_json(row["answers"]) == {"s1-i2": {"option_id": "b", "correct": True}}
    assert GuideContent.model_validate(decrypt_json(row["previous_content"])) == old
    assert row["status"] == "ready" and row["generated_at"] != MADE_AT
    assert script.written == ["Types", "Control flow, again"]
    assert [e.message for e in events if e.type == "status"] == [
        "Reading your 2 materials",
        "Planning the outline",
        "Outline ready. Writing section 2 of 3",
        "Writing section 3 of 3: Control flow, again",
        "Checking citations and blocks",
    ]


def test_the_update_outline_is_asked_with_the_current_sections_and_the_new_source(
    world, monkeypatch,
):
    old = _updatable(world)
    script = Script(monkeypatch, outline=_outline(_planned("Recursion", keep_id="s1")))

    run(_follow(world, "update"))

    (call,) = script.outline_calls
    assert call["current"] == old.sections
    assert call["new_labels"] == ["S2"]
    assert [s.label for s in call["brief"].sources] == ["S1", "S2"]
    # The depth's five: more than the two it could keep and the one lecture.
    assert (call["low"], call["high"]) == (3, 5)


def test_the_outline_sent_on_an_update_shows_kept_sections_as_the_reader_may_see_them(
    world, monkeypatch,
):
    _updatable(world)
    Script(monkeypatch, outline=_outline(
        _planned("Recursion", keep_id="s1"), _planned("Control flow", keep_id="s2"),
        _planned("Types"),
    ))

    events, _ = run(_follow(world, "update"))

    sent = GuideContent.model_validate(events[2].data["content"])
    assert [(s.id, s.status) for s in sent.sections] == [
        ("s1", "written"), ("s2", "written"), ("s3", "queued")]
    # Both checks were answered, so both keep their answer for the reader.
    assert [s.items[1].correct_id for s in sent.sections[:2]] == ["b", "b"]


def test_an_answer_given_while_the_outline_was_planned_survives_the_update(world, monkeypatch):
    _updatable(world, answers=None, read_sections=[])
    script = Script(monkeypatch, outline=_outline(_planned("Recursion", keep_id="s1")))
    planned = script.awrite_outline

    async def answer_meanwhile(brief, **kwargs):
        world.stored().update(
            read_sections=["s1", "s2"],
            answers=encrypt_json({"s1-i2": {"option_id": "b", "correct": True}}),
        )
        return await planned(brief, **kwargs)

    monkeypatch.setattr(writer, "awrite_outline", answer_meanwhile)

    run(_follow(world, "update"))

    row = world.stored()
    assert row["read_sections"] == ["s1"]
    assert decrypt_json(row["answers"]) == {"s1-i2": {"option_id": "b", "correct": True}}


def test_a_keep_id_is_honoured_once_and_only_for_a_written_section(world, monkeypatch):
    old = _updatable(world)
    Script(monkeypatch, outline=_outline(
        _planned("Recursion", keep_id="s1"),
        _planned("Recursion twice", keep_id="s1"),
        _planned("Never existed", keep_id="s9"),
    ))

    run(_follow(world, "update"))

    sections = world.content().sections
    assert [s.id for s in sections] == ["s1", "s3", "s4"]
    assert sections[0].items == old.sections[0].items
    assert [s.title for s in sections[1:]] == ["Recursion twice", "Never existed"]


def test_an_update_that_keeps_everything_writes_nothing(world, monkeypatch):
    _updatable(world)
    script = Script(monkeypatch, outline=_outline(
        _planned("Recursion", keep_id="s1"), _planned("Control flow", keep_id="s2")))

    events, _ = run(_follow(world, "update"))

    assert script.written == []
    assert _shape(events) == [
        ("status", "read"), ("status", "outline"), ("progress", "outline"),
        ("status", "check"), ("done", "done"),
    ]
    row = world.stored()
    assert row["read_sections"] == ["s1", "s2"] and row["material_ids"] == ["doc-1", "doc-2"]
    assert row["generated_at"] != MADE_AT


def test_an_update_gives_its_new_lectures_last_so_the_budget_never_cuts_them(world, monkeypatch):
    """Past the source budget the last ids given are read
    (`materials._arows`): the guide's own, oldest first, then the new."""
    _updatable(world, material_ids=["doc-1", "doc-0"])
    asked: list[list[str]] = []
    loaded = world.aload_sources

    async def aload_sources(user_id, offering_id, material_ids):
        asked.append(list(material_ids))
        return await loaded(user_id, offering_id, material_ids)

    monkeypatch.setattr(materials, "aload_sources", aload_sources)

    prepared = run(generation.aprepare_generation(ME, GUIDE, "update"))

    assert asked == [["doc-1", "doc-0", "doc-2"]]
    assert prepared.material_ids == ["doc-1", "doc-0", "doc-2"]


def test_an_update_reads_a_new_lecture_on_a_guide_already_at_the_source_budget(world, monkeypatch):
    """Thirty materials and one new lecture: the lecture is read and the
    oldest material makes room. It used to be the lecture that was cut, and
    the update answered that there was nothing new."""
    documents = _Documents()
    own = [f"doc-{n:02d}" for n in range(1, 31)]
    for n, doc_id in enumerate(own, start=1):
        documents.add(doc_id, user_id=ME, offering_id=OFFERING, text="Old.",
                      created_at=f"2026-09-{n:02d}T09:00:00+00:00")
    documents.add("doc-new", user_id=ME, offering_id=OFFERING, text="New.",
                  created_at="2026-11-05T00:00:00+00:00")
    monkeypatch.setattr(materials, "table", lambda name: {"documents": documents}[name])
    monkeypatch.setattr(materials, "aload_sources", LOAD_SOURCES)
    world.lectures = [{"id": "doc-new", "offering_id": OFFERING,
                       "created_at": "2026-11-05T00:00:00+00:00"}]
    world.guide(status="ready", generated_at=MADE_AT, material_ids=own,
                content=encrypt_json(_written_guide().model_dump(mode="json")))

    prepared = run(generation.aprepare_generation(ME, GUIDE, "update"))

    read = [source.source.id for source in prepared.inputs.brief.sources]
    assert read == [f"document:{doc_id}" for doc_id in [*own[1:], "doc-new"]]
    assert prepared.new_labels == ["S30"]
    # The material that was not read this time is still the guide's.
    assert prepared.material_ids == [*own, "doc-new"]


def test_an_old_guide_made_from_all_the_classs_documents_can_be_updated(world, monkeypatch):
    """It recorded no materials, so every lecture since it was made is new,
    and one that cannot be read yet stays new."""
    _updatable(world, material_ids=[])
    world.documents["doc-3"] = ("lecture-10.pdf", "", [])
    world.lectures.append({"id": "doc-3", "offering_id": OFFERING,
                           "created_at": "2026-11-06T00:00:00+00:00"})
    unreadable = world.aload_sources

    async def aload_sources(user_id, offering_id, material_ids):
        assert material_ids == ["doc-1", "doc-2", "doc-3"]
        return await unreadable(user_id, offering_id, [i for i in material_ids if i != "doc-3"])

    monkeypatch.setattr(materials, "aload_sources", aload_sources)

    prepared = run(generation.aprepare_generation(ME, GUIDE, "update"))

    assert prepared.new_labels == ["S2"] and prepared.material_ids == ["doc-1", "doc-2"]


def test_update_with_nothing_new_is_invalid(world, monkeypatch):
    world.guide(status="ready", generated_at=MADE_AT,
                content=encrypt_json(_written_guide().model_dump(mode="json")))
    Script(monkeypatch)

    with pytest.raises(GuideInvalid, match="nothing new"):
        run(generation.aprepare_generation(ME, GUIDE, "update"))

    # A new lecture with nothing to read yet is not something to add either,
    # and it stays new for a later update.
    world.lectures = [{"id": "doc-3", "offering_id": OFFERING,
                       "created_at": "2026-11-05T00:00:00+00:00"}]
    with pytest.raises(GuideInvalid, match="nothing new"):
        run(generation.aprepare_generation(ME, GUIDE, "update"))
    assert world.stored()["material_ids"] == ["doc-1"]
    assert world.stored()["generating_at"] is None
    assert request_limits._rate_state == {}


# ── Regenerate and the lectures added since ───────────────────────────────────


def _new_lectures(world: World) -> int:
    """How many new lectures the guide's card reports, as the home and the
    reader show it."""
    guide = run(store.aload_guide(ME, GUIDE))
    its_class = cards.GuideClass(
        course_id=COURSE, course_name="Intro to CS", course_code="CS 101", semester=None,
    )
    return cards.card(guide, its_class, world.lectures).new_materials


def test_regenerate_reads_the_lectures_added_since_so_they_are_no_longer_new(world, monkeypatch):
    """A regenerate stamps the guide as made now, which stops every earlier
    lecture counting as new. So it reads them, as an update does."""
    _updatable(world)
    assert _new_lectures(world) == 1
    script = Script(monkeypatch, outline=_outline(_planned("One"), _planned("Two")))

    events, _ = run(_follow(world, "regenerate"))

    assert events[-1].type == "done"
    both = ["document:doc-1", "document:doc-2"]
    (call,) = script.outline_calls
    assert [source.source.id for source in call["brief"].sources] == both
    # Nothing is kept on a regenerate: the outline is planned from scratch.
    assert call["current"] == []
    assert script.offered == [both, both]
    row = world.stored()
    assert row["material_ids"] == ["doc-1", "doc-2"]
    assert [source.id for source in world.content().sources] == both
    # Planned from scratch, and numbered after the two sections it replaces.
    assert [s.id for s in world.content().sections] == ["s3", "s4"]
    # The lecture stopped being new because it is one of the guide's
    # materials now, not only because the date moved.
    assert _new_lectures(world) == 0
    assert materials.new_material_ids(
        world.lectures, offering_id=OFFERING, material_ids=row["material_ids"], since=MADE_AT,
    ) == []


def test_regenerate_with_no_new_lecture_reads_the_guides_own_materials(world, monkeypatch):
    _ready(world)
    # In the class, but not chosen for this guide and older than it.
    world.documents["doc-0"] = ("syllabus-week.pdf", "Office hours are on Friday.", [])
    world.lectures = [
        {"id": "doc-0", "offering_id": OFFERING, "created_at": "2026-10-20T00:00:00+00:00"},
        {"id": "doc-9", "offering_id": "another-class", "created_at": "2026-11-05T00:00:00+00:00"},
    ]
    script = Script(monkeypatch, outline=_outline(_planned("One")))

    events, _ = run(_follow(world, "regenerate"))

    assert events[-1].type == "done"
    assert script.offered == [["document:doc-1"]]
    assert script.outline_calls[0]["new_labels"] == []
    assert world.stored()["material_ids"] == ["doc-1"]


def test_a_regenerate_goes_ahead_without_a_new_lecture_it_cannot_read(world, monkeypatch):
    """An update with nothing readable to add is refused. A regenerate still
    has the whole guide to write."""
    _ready(world)
    world.lectures = [{"id": "doc-3", "offering_id": OFFERING,
                       "created_at": "2026-11-05T00:00:00+00:00"}]

    prepared = run(generation.aprepare_generation(ME, GUIDE, "regenerate"))

    assert prepared.material_ids == ["doc-1"] and prepared.new_labels == []
    assert [source.source.id for source in prepared.inputs.brief.sources] == ["document:doc-1"]


def test_a_resume_reads_no_lecture_added_since(world, monkeypatch):
    """It leaves the guide's date alone, so the lecture is still new after it."""
    _missing_one(world)
    world.documents["doc-2"] = ("lecture-9.pdf", "Types are checked at run time.", ["Types"])
    world.lectures = [{"id": "doc-2", "offering_id": OFFERING,
                       "created_at": "2026-11-05T00:00:00+00:00"}]
    script = Script(monkeypatch)

    events, _ = run(_follow(world))

    assert events[-1].type == "done"
    assert script.offered == [["document:doc-1"]]
    assert world.stored()["material_ids"] == ["doc-1"]
    assert _new_lectures(world) == 1


# ── Prepare ───────────────────────────────────────────────────────────────────


def test_prepare_refuses_what_should_be_an_http_status(world, monkeypatch):
    world.guide()
    world.guide(guide_id="done", status="ready", generated_at=MADE_AT,
                content=encrypt_json(_written_guide().model_dump(mode="json")))
    world.guide(guide_id="unreadable", content="bm90LWNpcGhlcnRleHQtbm90LWNpcGhlcnRleHQ=")
    world.guide(guide_id="empty", material_ids=["doc-gone"])
    world.db.add("theirs", user_id="user_other")

    def prepare(guide_id, mode="resume"):
        return run(generation.aprepare_generation(ME, guide_id, mode))

    with pytest.raises(GuideInvalid, match="mode"):
        prepare(GUIDE, "rewrite")
    with pytest.raises(GuideNotFound):
        prepare("missing")
    with pytest.raises(GuideNotFound):
        prepare("theirs")
    with pytest.raises(GuideInvalid, match="already written"):
        prepare("done")
    with pytest.raises(GuideInvalid, match="cannot be read"):
        prepare("unreadable", "regenerate")
    with pytest.raises(GuideInvalid) as unreadable_materials:
        prepare("empty")
    assert unreadable_materials.value.detail == "None of this guide's materials can be read."
    # None of them was charged for, and none holds a claim.
    assert request_limits._rate_state == {}
    assert all(row["generating_at"] is None for row in world.db.rows)


def test_prepare_holds_nothing_until_the_stream_starts(world, monkeypatch):
    """A client that goes away between prepare and the first event leaves no
    claim behind for the next request to wait out."""
    world.guide()
    Script(monkeypatch, outline=_outline(_planned("One")))

    abandoned = run(generation.aprepare_generation(ME, GUIDE, "resume"))

    assert abandoned.guide.id == GUIDE
    assert world.stored()["generating_at"] is None
    events, _ = run(_follow(world))
    assert events[-1].type == "done"


def test_a_second_prepare_while_a_run_holds_the_guide_is_busy(world, monkeypatch):
    world.guide()
    Script(monkeypatch, outline=_outline(_planned("One")))

    async def scenario():
        first = generation.stream_generation(await generation.aprepare_generation(ME, GUIDE, "resume"))
        await anext(first)
        with pytest.raises(GuideBusy) as busy:
            await generation.aprepare_generation(ME, GUIDE, "resume")
        charged = len(request_limits._rate_state[f"study-guide-generate:{ME}"])
        async for _ in first:
            pass
        return busy.value, charged

    busy, charged = run(scenario())

    assert (busy.status_code, busy.detail) == (409, "Another tab is writing this guide.")
    # The refused request was not counted against the hourly limit.
    assert charged == 1
    assert world.stored()["status"] == "ready"


def test_two_prepared_runs_cannot_both_write(world, monkeypatch):
    """Both were prepared before either started. The claim decides: the
    second stream ends at once, writes nothing and gets its charge back."""
    world.guide()
    script = Script(monkeypatch, outline=_outline(_planned("One")))

    async def scenario():
        first = generation.stream_generation(await generation.aprepare_generation(ME, GUIDE, "resume"))
        second = generation.stream_generation(await generation.aprepare_generation(ME, GUIDE, "resume"))
        await anext(first)
        holder = world.stored()["generating_at"]
        lost = [event async for event in second]
        still_held = world.stored()["generating_at"] == holder
        charged = len(request_limits._rate_state[f"study-guide-generate:{ME}"])
        won = [event async for event in first]
        return lost, still_held, charged, won

    lost, still_held, charged, won = run(scenario())

    assert [(e.type, e.message, e.data) for e in lost] == [
        ("error", "Another tab is writing this guide.", {"retryable": True})]
    assert still_held and charged == 1
    assert won[-1].type == "done" and len(script.outline_calls) == 1


def test_a_run_prepared_before_another_finished_does_not_write_the_guide_again(world, monkeypatch):
    """Both were prepared from the same row; the first ran to the end before
    the second started. The second finds the work done and says so."""
    world.guide()
    script = Script(monkeypatch, outline=_outline(_planned("One")))

    async def scenario():
        first = generation.stream_generation(await generation.aprepare_generation(ME, GUIDE, "resume"))
        second = generation.stream_generation(await generation.aprepare_generation(ME, GUIDE, "resume"))
        won = [event async for event in first]
        finished = dict(world.stored())
        late = [(event, world.stored()["generating_at"]) async for event in second]
        return won, finished, late

    won, finished, late = run(scenario())

    assert won[-1].type == "done"
    ((event, held),) = late
    # `done` for the guide as it is, with the claim already given back.
    assert (event.type, held) == ("done", None)
    assert event.data == won[-1].data
    assert len(script.outline_calls) == 1 and script.written == ["One"]
    assert world.stored()["content"] == finished["content"]
    assert world.stored()["generated_at"] == finished["generated_at"]
    # The run that did nothing was not counted.
    assert len(request_limits._rate_state[f"study-guide-generate:{ME}"]) == 1


def test_a_second_regenerate_fired_with_the_first_keeps_the_real_previous_version(
    world, monkeypatch,
):
    old = _ready(world)
    script = Script(monkeypatch, outline=_outline(_planned("One")))

    async def scenario():
        first = generation.stream_generation(await generation.aprepare_generation(ME, GUIDE, "regenerate"))
        second = generation.stream_generation(await generation.aprepare_generation(ME, GUIDE, "regenerate"))
        return [e async for e in first], [e async for e in second]

    won, late = run(scenario())

    assert won[-1].type == "done" and _shape(late) == [("done", "done")]
    assert len(script.outline_calls) == 1
    assert GuideContent.model_validate(decrypt_json(world.stored()["previous_content"])) == old


def test_a_run_writes_from_the_row_as_it_is_under_the_claim(world, monkeypatch):
    """Another request wrote section one after this run was prepared and
    before it took the claim. This run goes on from there."""
    world.guide()
    script = Script(monkeypatch, outline=_outline(_planned("One"), _planned("Two")))

    async def scenario():
        cut = generation.stream_generation(await generation.aprepare_generation(ME, GUIDE, "resume"))
        late = await generation.aprepare_generation(ME, GUIDE, "resume")
        async for event in cut:
            if (event.type, event.step) == ("progress", "section"):
                break
        await cut.aclose()
        return [event async for event in generation.stream_generation(late)]

    events = run(scenario())

    assert _sections_sent(events) == ["Two"] and events[-1].type == "done"
    assert len(script.outline_calls) == 1 and script.written == ["One", "Two"]
    assert [s.status for s in world.content().sections] == ["written", "written"]


@pytest.mark.parametrize(
    ("gone", "message", "retryable"),
    [
        # Nothing to claim: the reader asks again and is told it is gone.
        ("deleted", "Another tab is writing this guide.", True),
        ("unreadable", store.GUIDE_UNREADABLE_DETAIL, False),
    ],
)
def test_a_guide_that_went_away_before_the_claim_ends_the_stream_at_once(
    world, monkeypatch, gone, message, retryable,
):
    garbage = "bm90LWNpcGhlcnRleHQtbm90LWNpcGhlcnRleHQ="
    world.guide()
    world.guide(guide_id="other")
    script = Script(monkeypatch, outline=_outline(_planned("One")))
    prepared = run(generation.aprepare_generation(ME, GUIDE, "resume"))
    if gone == "deleted":
        world.db.rows.remove(world.stored())
    else:
        world.stored()["content"] = garbage

    async def scenario():
        return [event async for event in generation.stream_generation(prepared)]

    (event,) = run(scenario())

    assert (event.type, event.message, event.data) == ("error", message, {"retryable": retryable})
    assert script.outline_calls == []
    assert request_limits._rate_state[f"study-guide-generate:{ME}"] == []
    if gone == "unreadable":
        row = world.stored()
        assert (row["content"], row["status"], row["generating_at"]) == (garbage, "generating", None)


def test_the_guide_is_free_for_another_request_the_moment_done_arrives(world, monkeypatch):
    """The reader may regenerate a block as soon as it sees `done`."""
    world.guide()
    Script(monkeypatch, outline=_outline(_planned("One")))

    async def scenario():
        stream = generation.stream_generation(await generation.aprepare_generation(ME, GUIDE, "resume"))
        async for event in stream:
            if event.type == "done":
                return await store.aclaim_generation(ME, GUIDE)

    taken = run(scenario())

    # And the finished run does not give the other request's claim back.
    assert taken is not None and world.stored()["generating_at"] == taken


def test_a_stale_claim_does_not_block_a_new_run(world, monkeypatch):
    stale = (datetime.now(timezone.utc) - store.CLAIM_STALE_AFTER - timedelta(seconds=1)).isoformat()
    world.guide(generating_at=stale)
    Script(monkeypatch, outline=_outline(_planned("One")))

    events, _ = run(_follow(world))

    assert events[-1].type == "done" and world.stored()["generating_at"] is None


def test_the_hourly_limit(world, monkeypatch):
    assert limits.STUDY_GUIDE_GENERATE_LIMIT == 20
    world.guide()
    monkeypatch.setattr(limits, "STUDY_GUIDE_GENERATE_LIMIT", 2)

    for _ in range(2):
        run(generation.aprepare_generation(ME, GUIDE, "resume"))
    with pytest.raises(GuideRateLimited) as limited:
        run(generation.aprepare_generation(ME, GUIDE, "resume"))

    assert limited.value.status_code == 429
    # The limit is per student.
    world.guide(guide_id="theirs", user_id="user_other")
    assert run(generation.aprepare_generation("user_other", "theirs", "resume")).guide.id == "theirs"


# ── The claim, however the run ends ───────────────────────────────────────────


def test_the_claim_is_released_when_the_consumer_stops_listening(world, monkeypatch):
    world.guide()
    Script(monkeypatch, outline=_outline(_planned("One"), _planned("Two")))

    async def scenario():
        stream = generation.stream_generation(await generation.aprepare_generation(ME, GUIDE, "resume"))
        async for event in stream:
            if (event.type, event.step) == ("progress", "section"):
                break
        held = world.stored()["generating_at"]
        await stream.aclose()
        return held

    held = run(scenario())

    row = world.stored()
    assert held is not None and row["generating_at"] is None
    # What was written stays, and the guide still reads as being written, so
    # the reader resumes it at the next section.
    assert row["status"] == "generating"
    assert [s.status for s in world.content().sections] == ["written", "queued"]


def test_the_claim_is_released_when_the_request_is_cancelled_mid_section(world, monkeypatch):
    """The request's cancel scope stays cancelled, so the release has to be
    shielded from it or the guide stays claimed until the claim goes stale."""
    world.guide()
    script = Script(monkeypatch, outline=_outline(_planned("One"), _planned("Two")))

    async def never_returns(brief, content, section, *, deps, beat):
        script.written.append(section.title)
        await anyio.sleep_forever()

    monkeypatch.setattr(writer, "awrite_section", never_returns)

    async def scenario():
        prepared = await generation.aprepare_generation(ME, GUIDE, "resume")
        with anyio.CancelScope() as request:
            async with anyio.create_task_group() as tasks:
                async def consume():
                    async for _ in generation.stream_generation(prepared):
                        pass
                tasks.start_soon(consume)
                while not script.written:
                    await anyio.sleep(0)
                held = world.stored()["generating_at"]
                request.cancel()
        return held

    held = anyio.run(scenario)

    row = world.stored()
    assert held is not None and row["generating_at"] is None
    assert row["status"] == "generating"
    assert [s.status for s in world.content().sections] == ["queued", "queued"]


def test_an_overtaken_run_stops_without_writing_or_releasing(world, monkeypatch):
    """The run went silent past the stale window and another request took the
    guide. Its next write finds its token gone: it ends there."""
    world.guide()
    script = Script(monkeypatch, outline=_outline(_planned("One"), _planned("Two")))
    taken_over = "2026-11-12T12:00:00+00:00"

    async def overtaken_while_writing(brief, content, section, *, deps, beat):
        script.written.append(section.title)
        if section.title == "Two":
            world.stored()["generating_at"] = taken_over
        return [_prose(section.id)]

    monkeypatch.setattr(writer, "awrite_section", overtaken_while_writing)

    events, _ = run(_follow(world))

    assert _shape(events)[-1] == ("error", "error")
    assert events[-1].data == {"retryable": True}
    assert events[-1].message == "Another request took over writing this guide."
    row = world.stored()
    # The new holder's claim is untouched, and section two was never saved.
    assert row["generating_at"] == taken_over
    assert row["status"] == "generating"
    assert [s.status for s in world.content().sections] == ["written", "queued"]
    assert world.logged == []


def test_the_claim_is_kept_fresh_before_each_block_rescue(world, monkeypatch):
    world.guide()
    Script(monkeypatch, outline=_outline(_planned("One")))
    tokens: list[str] = []

    async def rescuing(brief, content, section, *, deps, beat):
        for _ in range(2):
            tokens.append(world.stored()["generating_at"])
            await beat()
        tokens.append(world.stored()["generating_at"])
        return [_prose(section.id)]

    monkeypatch.setattr(writer, "awrite_section", rescuing)

    events, _ = run(_follow(world))

    assert events[-1].type == "done" and len(set(tokens)) == 3


def test_a_run_overtaken_between_rescues_stops_there(world, monkeypatch):
    world.guide()
    Script(monkeypatch, outline=_outline(_planned("One")))
    paid: list[str] = []

    async def overtaken_mid_section(brief, content, section, *, deps, beat):
        world.stored()["generating_at"] = "2026-11-12T12:00:00+00:00"
        await beat()
        paid.append(section.title)
        return [_prose(section.id)]

    monkeypatch.setattr(writer, "awrite_section", overtaken_mid_section)

    events, _ = run(_follow(world))

    assert events[-1].message == "Another request took over writing this guide."
    assert paid == [] and world.stored()["generating_at"] == "2026-11-12T12:00:00+00:00"


def test_an_overtaken_run_does_not_pay_for_another_section(world, monkeypatch):
    world.guide()
    script = Script(monkeypatch, outline=_outline(_planned("One"), _planned("Two")))
    saved = store.asave_content

    async def overtaken_after_the_first_section(guide, content, **kwargs):
        row = await saved(guide, content, **kwargs)
        if any(s.status == "written" for s in content.sections):
            world.stored()["generating_at"] = "2026-11-12T12:00:00+00:00"
        return row

    monkeypatch.setattr(store, "asave_content", overtaken_after_the_first_section)

    events, _ = run(_follow(world))

    assert events[-1].type == "error"
    assert script.written == ["One"]


# ── The section count ─────────────────────────────────────────────────────────


def test_a_guide_is_asked_for_the_sections_its_depth_allows(world, monkeypatch):
    world.documents["doc-1"] = ("recursion.pdf", "A recursive function calls itself.", ["Recursion"])
    world.guide()
    script = Script(monkeypatch, outline=_outline(_planned("One")))

    run(_follow(world))

    # One concept named in the materials does not make it a one-section guide.
    assert (script.outline_calls[0]["low"], script.outline_calls[0]["high"]) == (3, 5)


def test_an_outline_longer_than_asked_is_cut_to_the_range(world, monkeypatch):
    world.guide(depth="cram")
    script = Script(monkeypatch, outline=_outline(*[_planned(f"Section {n}") for n in range(1, 7)]))

    run(_follow(world))

    assert (script.outline_calls[0]["low"], script.outline_calls[0]["high"]) == (1, 3)
    assert [s.title for s in world.content().sections] == ["Section 1", "Section 2", "Section 3"]
