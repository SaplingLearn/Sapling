"""The class's study guides, as ``study_guides`` rows.

A guide is put together the way a generation run would leave it: its sources
are the documents that taught its concepts and existed when it was made, each
section gets its tier from the student's mastery and its share from the
server's own weights, and every written section goes through the server's
citation and block check (``services.study_guides.verify``). That check is
what decides whether a chart is plotted from data, and it stamps the evidence
line on a quiz mistake, so what is stored is what the app would have stored.
"""
from __future__ import annotations

from config import get_mastery_tier
from db.local_study_data import clock, coursework, materials
from db.local_study_data.placement import Placement
from db.local_study_data.spec import ClassData, Concept, GuideSpec, LegacyGuide, Material
from models.study_guide import (
    GUIDE_FORMAT,
    QUIZ_HISTORY_SOURCE,
    GuideContent,
    Item,
    MistakesBlock,
    ProseItem,
    Section,
    Source,
)
from services.study_guides import signals, verify
from services.study_guides.plan import weights

WHOLE_COURSE = "Whole course"
#: ``study_guides.format`` of a row from before the redesign.
LEGACY_FORMAT = 1


# ── What a guide was made from ────────────────────────────────────────────────


def used_materials(data: ClassData, spec: GuideSpec) -> list[Material]:
    """The documents that teach one of the guide's concepts and were already
    uploaded when it was made, oldest first."""
    wanted = set(spec.sections)
    there = [
        m for m in data.materials
        if m.days_ago * 24 + clock.UPLOAD_LEAD_HOURS > spec.made_hours_ago
    ]
    return sorted((m for m in there if wanted & set(m.concepts)), key=lambda m: -m.days_ago)


def _source_id(place: Placement, material_key: str) -> str:
    return f"document:{place.document_id(material_key)}"


def digest_texts(data: ClassData, concept_key: str) -> list[str]:
    """The mistakes a concept's quiz digest holds, in the order the app reads
    them: common mistakes, then weak areas."""
    digest = data.digest(concept_key)
    return [*digest.common_mistakes, *digest.weak_areas] if digest else []


def recorded_mistakes(data: ClassData, used: list[Material]) -> list[signals.QuizMistake]:
    """The quiz mistakes a writer is offered for these documents, numbered as
    ``signals.amistakes`` numbers them."""
    taught = dict.fromkeys(key for material in used for key in material.concepts)
    picked = [
        (data.concept(key).name, text)
        for key in taught
        for text in digest_texts(data, key)[: signals.MAX_MISTAKES_PER_CONCEPT]
    ][: signals.MAX_MISTAKES]
    return [
        signals.QuizMistake(id=f"m{number}", concept=concept, text=text)
        for number, (concept, text) in enumerate(picked, start=1)
    ]


def _facts(place: Placement, spec: GuideSpec, used: list[Material]) -> verify.Facts:
    """What the guide's sections are checked against."""
    data = place.data
    return verify.Facts(
        sources={_source_id(place, m.key): materials.source_text(data, m) for m in used},
        mistakes=recorded_mistakes(data, used) if spec.use_history else [],
        concepts=[concept.name for concept in data.concepts],
    )


def _sources(place: Placement, used: list[Material], facts: verify.Facts) -> list[Source]:
    listed = [
        Source(
            id=_source_id(place, m.key), name=m.file_name,
            kind=m.file_name.rpartition(".")[2].upper(),
        )
        for m in used
    ]
    if facts.mistakes:
        listed.append(Source(id=QUIZ_HISTORY_SOURCE, name="Your quiz history", kind="Sapling"))
    return listed


# ── A draft item, placed in a guide ───────────────────────────────────────────


def _cited(item: ProseItem, place: Placement) -> ProseItem:
    paragraphs = [
        p.model_copy(update={"citations": [_source_id(place, key) for key in p.citations]})
        for p in item.paragraphs
    ]
    return item.model_copy(update={"paragraphs": paragraphs})


def _evidenced(
    block: MistakesBlock, data: ClassData, concept: Concept, facts: verify.Facts,
) -> MistakesBlock:
    """Each mistake pointed at the recorded mistake it answers."""
    texts = digest_texts(data, concept.key)
    offered = {m.text: m.id for m in facts.mistakes if m.concept == concept.name}
    mistakes = [
        m.model_copy(update={"evidence_id": offered[texts[int(m.evidence_id)]]})
        for m in block.mistakes
    ]
    return block.model_copy(update={"mistakes": mistakes})


def _placed(item: Item, place: Placement, concept: Concept, facts: verify.Facts) -> Item:
    """A draft item with its stand-ins resolved (see ``blocks.py``)."""
    if item.type == "prose":
        return _cited(item, place)
    if item.type == "mistakes":
        return _evidenced(item, place.data, concept, facts)
    if item.type == "check":
        return item.model_copy(update={"concept": concept.name})
    if getattr(item, "source_id", None):
        return item.model_copy(update={"source_id": _source_id(place, item.source_id)})
    return item


def _items(
    place: Placement, spec: GuideSpec, section_id: str, concept: Concept, facts: verify.Facts,
) -> list[Item]:
    """The concept's drafted items, numbered. A guide made without quiz
    history has no mistakes block."""
    drafted = place.data.sections[concept.key].items
    kept = [item for item in drafted if spec.use_history or item.type != "mistakes"]
    return [
        _placed(item, place, concept, facts).model_copy(update={"id": f"{section_id}-i{number}"})
        for number, item in enumerate(kept, start=1)
    ]


# ── Sections ──────────────────────────────────────────────────────────────────


def _as_written(section: Section) -> list[dict]:
    """The section's items without the two things the check decides: whether
    a chart is illustrative, and a mistake's evidence line."""
    items = [item.model_dump(exclude={"illustrative"}) for item in section.items]
    for item in items:
        for mistake in item.get("mistakes", []):
            mistake["evidence"] = ""
    return items


def _checked(section: Section, facts: verify.Facts) -> Section:
    """The section as the server's check leaves it. The check quietly drops
    or rewrites what it cannot stand behind, so beyond its two own decisions
    any change it makes here is a mistake in the data."""
    checked = verify.check_section(section, facts)
    if _as_written(checked) != _as_written(section):
        raise ValueError(f"The study guide check changed the section {section.title!r}.")
    return checked


def _status(spec: GuideSpec, concept_key: str) -> str:
    if spec.generating:
        return "queued"
    return "failed" if concept_key in spec.failed else "written"


def _section(
    place: Placement, spec: GuideSpec, number: int, concept_key: str,
    tier: str, share: int, facts: verify.Facts,
) -> Section:
    concept = place.data.concept(concept_key)
    draft = place.data.sections.get(concept_key)
    section = Section(
        id=f"s{number}",
        title=draft.title if draft else concept.name,
        concept=concept.name,
        tier=tier,
        weight=share,
        one_line=draft.one_line if draft else concept.definition,
        status=_status(spec, concept_key),
    )
    if section.status != "written":
        return section
    items = _items(place, spec, section.id, concept, facts)
    return _checked(section.model_copy(update={"items": items}), facts)


def _tiers(data: ClassData, spec: GuideSpec) -> list[str]:
    """Each section's tier when the guide was written. Made without history,
    every section is ``unexplored``."""
    if not spec.use_history:
        return ["unexplored"] * len(spec.sections)
    return [get_mastery_tier(data.concept(key).score) for key in spec.sections]


def scope_label(data: ClassData, scope: str | None) -> str:
    return data.assessment(scope).title if scope else WHOLE_COURSE


def content(place: Placement, spec: GuideSpec) -> GuideContent:
    data = place.data
    used = used_materials(data, spec)
    facts = _facts(place, spec, used)
    tiers = _tiers(data, spec)
    shares = weights(tiers, use_history=spec.use_history)
    return GuideContent(
        title=spec.title,
        deck=spec.deck,
        takeaways=list(spec.takeaways),
        sections=[
            _section(place, spec, number, key, tier, share, facts)
            for number, (key, tier, share) in enumerate(zip(spec.sections, tiers, shares), start=1)
        ],
        sources=_sources(place, used, facts),
        scope_label=scope_label(data, spec.scope),
    )


# ── Rows ──────────────────────────────────────────────────────────────────────


def _scope_kind(data: ClassData, scope: str | None) -> str:
    if scope is None:
        return "course"
    return "exam" if coursework.is_exam(data.assessment(scope)) else "assignment"


def _base(place: Placement, key: str, scope: str | None, made_hours_ago: int) -> dict:
    """A ``study_guides`` row with every column this seed writes, at its
    defaults. Every row has the same columns, as one bulk write needs."""
    made = clock.utc(clock.hours_ago(place.now, made_hours_ago))
    return {
        "id": place.guide_id(key),
        "user_id": place.owner_id,
        "offering_id": place.enrolled.offering_id,
        "exam_id": place.assessment_id(scope) if scope else None,
        "scope_kind": _scope_kind(place.data, scope),
        "goal": "exam_prep",
        "depth": "standard",
        "use_history": True,
        "status": "ready",
        "format": GUIDE_FORMAT,
        "content": None,
        "material_ids": [],
        "read_sections": [],
        "answers": None,
        "feedback": None,
        "saved_at": None,
        "generating_at": None,
        "generated_at": made,
        "created_at": made,
    }


def _check_answers(spec: GuideSpec, written: GuideContent) -> dict | None:
    """``answers``: what was picked on a section's check, by block id."""
    answers = {}
    for key, section in zip(spec.sections, written.sections):
        if key in spec.answers:
            check = next(item for item in section.items if item.type == "check")
            picked = spec.answers[key]
            answers[check.id] = {"option_id": picked, "correct": picked == check.correct_id}
    return answers or None


def _saved_at(place: Placement, spec: GuideSpec) -> str | None:
    if spec.saved_hours_ago is None:
        return None
    return clock.utc(clock.hours_ago(place.now, spec.saved_hours_ago))


def _guide(place: Placement, spec: GuideSpec) -> dict:
    written = content(place, spec)
    row = _base(place, spec.key, spec.scope, spec.made_hours_ago)
    row.update({
        "goal": spec.goal,
        "depth": spec.depth,
        "use_history": spec.use_history,
        "content": written.model_dump(mode="json"),
        "material_ids": [place.document_id(m.key) for m in used_materials(place.data, spec)],
        "read_sections": [
            f"s{number}" for number, key in enumerate(spec.sections, start=1) if key in spec.read
        ],
        "answers": _check_answers(spec, written),
        "feedback": spec.feedback,
        "saved_at": _saved_at(place, spec),
    })
    if spec.generating:
        # A fresh claim: the reader shows the outline as being written, and
        # takes the guide over once the claim goes stale.
        row.update({"status": "generating", "generated_at": None, "generating_at": clock.utc(place.now)})
    return row


def _legacy(place: Placement, guide: LegacyGuide) -> dict:
    """A row from before the redesign: ``{exam, due_date, overview, topics}``
    as format 1, with no materials recorded."""
    exam = place.data.assessment(guide.scope)
    row = _base(place, guide.key, guide.scope, guide.made_hours_ago)
    row.update({
        "format": LEGACY_FORMAT,
        "content": {
            "exam": exam.title,
            "due_date": clock.due_day(place.now, exam.in_days),
            "overview": guide.overview,
            "topics": [
                {"name": name, "importance": importance, "concepts": list(bullets)}
                for name, importance, bullets in guide.topics
            ],
        },
    })
    return row


def study_guides(place: Placement) -> list[dict]:
    data = place.data
    return [
        *(_guide(place, spec) for spec in data.guides),
        *(_legacy(place, guide) for guide in data.legacy_guides),
    ]
