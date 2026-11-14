"""The study-guide contract: what a guide IS, on disk and on the wire.

One file owns the shape. The agents write it (`agents/study_guide.py`), the
`services/study_guides` package stores and serves it, and the frontend mirrors
it in `frontend/src/lib/studyGuide/types.ts`. The two sides are pinned together
by `backend/tests/fixtures/study_guide_contract.json`, which a backend test
validates against these models and a frontend test type-checks.

A guide is prose with typed blocks inline. A section's `items` is one ordered
list of `prose` passages and blocks, each validated against the `Item` union.
The section writer is a TEXT agent: it writes prose with fenced JSON blocks,
and `services.study_guides.markup` turns that into items (the union is far
past the structured-output schema budget in `tests/test_agent_output_schemas`).
A block that fails validation is dropped (or retried once) without losing the
section around it: see `parse_items`. Item ids are assigned by the server.

Bounds are local (CLAUDE.md, "Structured-output bounds are local on Claude"):
free prose is clipped, lists are clipped, and identifier-like fields keep a
strict length.
"""

from __future__ import annotations

import logging
from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from agents._bounded import clip_list, clip_prose

logger = logging.getLogger(__name__)

#: `study_guides.format` of a row whose `content` is a `GuideContent`. Rows
#: written before the redesign are format 1 (`{exam, due_date, overview,
#: topics}`) and are upgraded on read by `services.study_guides.legacy`.
GUIDE_FORMAT = 2

Goal = Literal["practice", "review", "exam_prep"]
Depth = Literal["cram", "standard", "deep"]
ScopeKind = Literal["exam", "assignment", "course"]
GuideStatus = Literal["generating", "ready", "failed"]
SectionStatus = Literal["queued", "written", "failed"]
#: `config.get_mastery_tier`'s vocabulary, unchanged.
Tier = Literal["mastered", "learning", "struggling", "unexplored"]
Feedback = Literal["yes", "no"]

#: The source id of the student's own quiz history (never a document).
QUIZ_HISTORY_SOURCE = "quiz-history"


def _prose(limit: int, field: str):
    return clip_prose(limit, f"study_guide.{field}")


def _items(limit: int, field: str):
    return clip_list(limit, f"study_guide.{field}")


# ── Prose ─────────────────────────────────────────────────────────────────────


class Paragraph(BaseModel):
    """One written paragraph. `**term**` marks a key term the reader highlights;
    `$...$` is inline math."""

    text: Annotated[str, _prose(1200, "paragraph.text")] = Field(max_length=1200)
    citations: Annotated[list[str], _items(3, "paragraph.citations")] = Field(
        default_factory=list,
        max_length=3,
        description="Source ids from the SOURCES list this paragraph draws on.",
    )


class ProseItem(BaseModel):
    """A passage of one to three paragraphs. Skim mode shows `summary` in its
    place; a passage with no summary is hidden in Skim."""

    type: Literal["prose"] = "prose"
    id: str = Field(max_length=40)
    paragraphs: Annotated[list[Paragraph], _items(3, "prose.paragraphs")] = Field(
        min_length=1, max_length=3
    )
    summary: Annotated[str | None, _prose(280, "prose.summary")] = Field(
        default=None,
        max_length=280,
        description="One or two plain sentences that stand in for the passage in Skim mode.",
    )


# ── Blocks ────────────────────────────────────────────────────────────────────


#: A coordinate the reader can draw: never NaN or an infinity (which JSON
#: cannot carry either).
Coordinate = Annotated[float, Field(allow_inf_nan=False)]


class ChartPoint(BaseModel):
    x: Coordinate
    y: Coordinate


class ChartSeries(BaseModel):
    label: str = Field(max_length=40)
    points: Annotated[list[ChartPoint], _items(12, "chart.points")] = Field(
        min_length=2, max_length=12
    )
    state: Literal["both", "after"] = Field(
        default="both",
        description="'after' = drawn dashed and only in the After state.",
    )


class ChartMarker(BaseModel):
    """A labelled point with guide lines to both axes (an equilibrium, a peak)."""

    x: Coordinate
    y: Coordinate
    x_label: str = Field(max_length=16)
    y_label: str = Field(max_length=16)
    state: Literal["before", "after"] = "before"


class ChartReadout(BaseModel):
    """One number panel beside the chart: its value before and after."""

    label: str = Field(max_length=24)
    before: str = Field(max_length=24)
    after: str = Field(max_length=24)
    change: str = Field(max_length=24, description="What happened, e.g. 'Rises'.")


class ChartBlock(BaseModel):
    """A line chart with an optional Before / After toggle.

    `illustrative` is decided by the server, never the model
    (`services.study_guides.verify`): a chart is plotted from data only when
    every number in it appears in the cited source. Anything else is labelled
    illustrative and drawn without axis numbers.
    """

    type: Literal["chart"] = "chart"
    id: str = Field(max_length=40)
    title: str = Field(max_length=80)
    x_label: str = Field(max_length=32)
    y_label: str = Field(max_length=32)
    series: Annotated[list[ChartSeries], _items(4, "chart.series")] = Field(
        min_length=1, max_length=4
    )
    markers: Annotated[list[ChartMarker], _items(2, "chart.markers")] = Field(
        default_factory=list, max_length=2
    )
    readouts: Annotated[list[ChartReadout], _items(2, "chart.readouts")] = Field(
        default_factory=list, max_length=2
    )
    after_label: str = Field(default="After", max_length=24)
    alt: Annotated[str, _prose(300, "chart.alt")] = Field(
        max_length=300, description="What the chart shows, in words, for screen readers."
    )
    source_id: str | None = None
    illustrative: bool = True


class Mistake(BaseModel):
    title: str = Field(max_length=120)
    fix: Annotated[str, _prose(320, "mistake.fix")] = Field(max_length=320)
    evidence_id: str = Field(
        max_length=40,
        description="The id of the QUIZ HISTORY entry this mistake comes from.",
    )
    #: Stamped by the server from the real quiz history, never by the model.
    evidence: str = Field(default="", max_length=160)


class MistakesBlock(BaseModel):
    """Common mistakes from the student's own quiz history. Only written when
    the guide was made with quiz history on and there is history to cite."""

    type: Literal["mistakes"] = "mistakes"
    id: str = Field(max_length=40)
    title: str = Field(max_length=80)
    mistakes: Annotated[list[Mistake], _items(3, "mistakes")] = Field(
        min_length=1, max_length=3
    )


class FormulaBlock(BaseModel):
    type: Literal["formula"] = "formula"
    id: str = Field(max_length=40)
    name: str = Field(max_length=80)
    latex: str = Field(max_length=300, description="The formula as LaTeX, no $ delimiters.")
    spoken: Annotated[str, _prose(240, "formula.spoken")] = Field(
        max_length=240, description="The formula read aloud, in plain words."
    )
    source_id: str | None = None


class WorkedStep(BaseModel):
    title: str = Field(max_length=80)
    math: str = Field(max_length=200)
    why: Annotated[str, _prose(240, "step.why")] = Field(max_length=240)


class WorkedExampleBlock(BaseModel):
    """A problem solved one revealed step at a time."""

    type: Literal["worked_example"] = "worked_example"
    id: str = Field(max_length=40)
    title: str = Field(max_length=80)
    problem: Annotated[str, _prose(500, "example.problem")] = Field(max_length=500)
    steps: Annotated[list[WorkedStep], _items(6, "example.steps")] = Field(
        min_length=2, max_length=6
    )
    source_id: str | None = None


class ComparisonRow(BaseModel):
    label: str = Field(max_length=60)
    cells: Annotated[list[str], _items(3, "comparison.cells")] = Field(
        min_length=2, max_length=3
    )
    emphasis: bool = Field(default=False, description="True for the one row most tested.")


class ComparisonBlock(BaseModel):
    type: Literal["comparison"] = "comparison"
    id: str = Field(max_length=40)
    title: str = Field(max_length=80)
    columns: Annotated[list[str], _items(3, "comparison.columns")] = Field(
        min_length=2, max_length=3
    )
    rows: Annotated[list[ComparisonRow], _items(6, "comparison.rows")] = Field(
        min_length=2, max_length=6
    )


class ConceptMapNode(BaseModel):
    concept: str = Field(
        max_length=120, description="A concept name, exactly as given in CONCEPTS."
    )
    step: str = Field(max_length=24, description="Where it sits, e.g. 'Foundations'.")


class ConceptMapBlock(BaseModel):
    """What the section builds on, in learning order. Each node's mastery is
    joined live from the student's tree, so the block stores names only."""

    type: Literal["concept_map"] = "concept_map"
    id: str = Field(max_length=40)
    title: str = Field(max_length=80)
    nodes: Annotated[list[ConceptMapNode], _items(5, "concept_map.nodes")] = Field(
        min_length=2, max_length=5
    )


class KeyTerm(BaseModel):
    term: str = Field(max_length=60)
    definition: Annotated[str, _prose(240, "term.definition")] = Field(max_length=240)


class KeyTermsBlock(BaseModel):
    type: Literal["key_terms"] = "key_terms"
    id: str = Field(max_length=40)
    title: str = Field(max_length=80)
    terms: Annotated[list[KeyTerm], _items(6, "key_terms")] = Field(
        min_length=2, max_length=6
    )


class CheckOption(BaseModel):
    id: Literal["a", "b", "c", "d"]
    text: str = Field(max_length=200)


class CheckBlock(BaseModel):
    """A check-yourself question. The first answer counts toward mastery of
    `concept`. `correct_id` and both explanations are withheld from the reader
    until the student has answered (`services.study_guides.detail`)."""

    type: Literal["check"] = "check"
    id: str = Field(max_length=40)
    question: Annotated[str, _prose(400, "check.question")] = Field(max_length=400)
    options: Annotated[list[CheckOption], _items(4, "check.options")] = Field(
        min_length=3, max_length=4
    )
    correct_id: Literal["a", "b", "c", "d"] | None = None
    explain_correct: Annotated[str | None, _prose(320, "check.explain_correct")] = Field(
        default=None, max_length=320
    )
    explain_incorrect: Annotated[str | None, _prose(320, "check.explain_incorrect")] = Field(
        default=None,
        max_length=320,
        description="A nudge toward the method, without giving the answer away.",
    )
    concept: str | None = Field(
        default=None,
        max_length=120,
        description="The concept this tests, exactly as given in CONCEPTS.",
    )


Block = (
    ChartBlock
    | MistakesBlock
    | FormulaBlock
    | WorkedExampleBlock
    | ComparisonBlock
    | ConceptMapBlock
    | KeyTermsBlock
    | CheckBlock
)
Item = Annotated[ProseItem | Block, Field(discriminator="type")]

BLOCK_TYPES: tuple[str, ...] = (
    "chart",
    "mistakes",
    "formula",
    "worked_example",
    "comparison",
    "concept_map",
    "key_terms",
    "check",
)

_ITEM = TypeAdapter(Item)


def parse_items(raw: list) -> tuple[list, list[dict]]:
    """Validate each raw item on its own: `(valid items, rejected raw items)`.

    This is what keeps a section alive when one block is malformed. The caller
    decides what to do with the rejects (retry the block once, then drop it).
    Already-validated models pass straight through.
    """
    valid: list = []
    rejected: list[dict] = []
    for entry in raw:
        if isinstance(entry, BaseModel):
            valid.append(entry)
            continue
        try:
            valid.append(_ITEM.validate_python(entry))
        except ValidationError as exc:
            kind = entry.get("type") if isinstance(entry, dict) else None
            logger.warning("study guide item rejected (type=%s): %d errors", kind, exc.error_count())
            if isinstance(entry, dict):
                rejected.append(entry)
    return valid, rejected


# ── The guide ─────────────────────────────────────────────────────────────────


class Source(BaseModel):
    """One thing the guide was made from. `id` is `document:<documents.id>` for
    the student's own material, or `QUIZ_HISTORY_SOURCE`. A citation can point
    at a document, never at a page: no page provenance is stored."""

    id: str = Field(max_length=80)
    name: str = Field(max_length=200)
    kind: str = Field(max_length=12, description="PDF, DOCX, PPTX, or Sapling.")


class Section(BaseModel):
    id: str = Field(max_length=40)
    title: str = Field(max_length=120)
    #: The student's graph concept this section teaches (exact name), or None.
    concept: str | None = Field(default=None, max_length=120)
    #: Mastery tier of `concept` when the guide was written: it decided how
    #: much room the section got, and a `mastered` section opens collapsed.
    tier: Tier = "unexplored"
    #: Share of the guide, 1-100. The shares of a guide's sections sum to 100.
    weight: int = Field(default=0, ge=0, le=100)
    one_line: Annotated[str, _prose(240, "section.one_line")] = Field(default="", max_length=240)
    status: SectionStatus = "queued"
    items: list[Item] = Field(default_factory=list)


class GuideContent(BaseModel):
    """`study_guides.content` (encrypted JSON) for a format-2 row."""

    title: str = Field(max_length=120)
    deck: Annotated[str, _prose(240, "deck")] = Field(default="", max_length=240)
    takeaways: Annotated[list[str], _items(3, "takeaways")] = Field(
        default_factory=list, max_length=3
    )
    sections: list[Section] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    #: What the guide is for, as the student named it ("Midterm 2"); "Whole
    #: course" for a course-scope guide.
    scope_label: str = Field(default="", max_length=200)
    #: The highest section number (`s<n>`) the guide has ever used, so a new
    #: section never takes the id of one an Update dropped. Stored with the
    #: content (`store`), never sent: `exclude` keeps it out of every dump.
    #: 0 on content from before it was kept: its sections' ids then say.
    last_section_number: int = Field(default=0, ge=0, exclude=True)
    #: When the materials this content was planned from were chosen or read
    #: (ISO), stored the same way: the guide is dated from it once it is
    #: ready, so a lecture uploaded after it still counts as new. None on
    #: content from before it was kept.
    materials_read_at: str | None = Field(default=None, exclude=True)


# ── Wire shapes ───────────────────────────────────────────────────────────────


class SectionBar(BaseModel):
    """One segment of the "how this guide spends its space" bar."""

    title: str
    tier: Tier
    weight: int


class GuideCounts(BaseModel):
    sections: int
    blocks: int
    practice: int
    minutes: int


class GuideCard(BaseModel):
    """One guide on the Study Guides home (and in the Library when saved)."""

    id: str
    title: str
    course_id: str
    course_name: str
    #: The class's short code ("CS 101"); its name when it has none.
    course_code: str
    semester: str | None = None
    scope_kind: ScopeKind
    scope_label: str
    goal: Goal
    depth: Depth
    status: GuideStatus
    generated_at: str | None
    created_at: str
    saved_at: str | None
    new_materials: int
    bars: list[SectionBar]
    counts: GuideCounts


class CheckAnswer(BaseModel):
    """What the student picked on a check block. Stored encrypted."""

    option_id: str
    correct: bool


class GuideDetail(GuideCard):
    """One guide, as the reader renders it."""

    content: GuideContent
    scope_id: str | None
    due_date: str | None
    use_history: bool
    read_sections: list[str]
    answers: dict[str, CheckAnswer]
    feedback: Feedback | None
    #: Live mastery tier per concept name the guide mentions.
    mastery: dict[str, Tier]


class ScopeOption(BaseModel):
    """One thing a guide can be for. `id` is None for the whole course."""

    kind: ScopeKind
    id: str | None
    title: str
    due_date: str | None
    #: The materials pre-selected for this scope.
    suggested_material_ids: list[str]


class MaterialOption(BaseModel):
    id: str
    file_name: str
    category: str
    created_at: str


class GuideOptions(BaseModel):
    scopes: list[ScopeOption]
    materials: list[MaterialOption]


class GuideRequest(BaseModel):
    """The New study guide modal's choices."""

    course_id: str
    semester: str | None = None
    scope_kind: ScopeKind = "course"
    scope_id: str | None = None
    goal: Goal = "exam_prep"
    depth: Depth = "standard"
    material_ids: Annotated[list[str], _items(30, "request.material_ids")] = Field(
        default_factory=list, max_length=30
    )
    use_history: bool = True


class PlanSection(BaseModel):
    title: str
    tier: Tier
    weight: int


class GuidePlan(BaseModel):
    """The planned outline: decided from the choices, before any model runs."""

    sections: list[PlanSection]
    minutes: int


class GuidePatch(BaseModel):
    """Small state changes from the reader. Omitted fields are left alone."""

    read_sections: list[str] | None = None
    saved: bool | None = None
    feedback: Feedback | None = None


class GuideState(BaseModel):
    """What a `GuidePatch` leaves behind."""

    read_sections: list[str]
    saved_at: str | None
    feedback: Feedback | None


class GenerateBody(BaseModel):
    #: `resume` writes whatever is still queued (a new guide, or one whose
    #: stream was cut). `update` folds in material added since. `regenerate`
    #: rewrites the whole guide. The last two keep the previous version.
    mode: Literal["resume", "update", "regenerate"] = "resume"


class AnswerBody(BaseModel):
    option_id: Literal["a", "b", "c", "d"]


class MasteryChange(BaseModel):
    concept: str
    before: Tier
    after: Tier


class AnswerResult(BaseModel):
    correct: bool
    correct_id: str
    explanation: str
    #: False when this block had already been answered: only the first answer
    #: moves mastery.
    counted: bool
    mastery: MasteryChange | None = None


class GenerationStep(BaseModel):
    """`data` of a `status` SSE event: how far the generation is. The label is
    the event's `message`. The stream speaks `services.agent_events`'s
    envelope: `status` (this), `progress` with step `outline`
    (`{content: GuideContent}`) or `section` (`{section: Section}`), `done`
    (`{guide: GuideDetail}`) and `error` (`{retryable: bool}`)."""

    step: int
    total: int
