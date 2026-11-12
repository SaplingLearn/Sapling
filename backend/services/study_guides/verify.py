"""The check a written section passes before it is saved: citations and
blocks are held to what the guide was really made from.

The writer is a model, so nothing it says about the student or the sources is
taken on trust. A citation must name one of the guide's sources. A mistake
must cite a mistake the quiz history really holds, and its evidence line is
written here. A check question must have its answer among its options, and a
section keeps one, last. A concept name must be one in the student's tree, in
the tree's spelling, because mastery is looked up and moved by that name. A
chart counts as plotted from data only when every number in it appears in the
source it cites.

Pure functions, no I/O.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import TypeAdapter

from models.study_guide import (
    Block,
    ChartBlock,
    CheckBlock,
    ComparisonBlock,
    ConceptMapBlock,
    Item,
    MistakesBlock,
    ProseItem,
    Section,
)
from services.study_guides.markup import CITATION
from services.study_guides.signals import QuizMistake, concept_key

_ITEM = TypeAdapter(Item)
_EVIDENCE_MAX = 160
#: The contract's cap on a concept name. A longer name in the tree cannot be
#: stored on a section or a block, so it counts as not there.
_CONCEPT_MAX = 120
#: The reader opens a check's explanation with these words itself.
_VERDICT = re.compile(r"^\s*(?:correct|not quite)\s*[.!:,]\s*", re.IGNORECASE)
#: A number in running text: `4`, `4.0`, `$4`, `1,000`, `-2.5`. Not the digits
#: inside a word or a version (`x2`, `v1.2`).
_NUMBER = re.compile(r"(?<![\w.])([-−]?)(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?|\.\d+)")


@dataclass(frozen=True)
class Facts:
    """What a section is checked against."""

    #: The guide's sources: source id to the text the writer was given.
    sources: dict[str, str]
    #: The quiz mistakes the writer was offered.
    mistakes: list[QuizMistake]
    #: The student's concept names, as their tree spells them.
    concepts: list[str]


def tree_name(name: str | None, concepts: list[str]) -> str | None:
    """The tree's own spelling of a concept name, or None when the student's
    tree does not have it."""
    if not name:
        return None
    key = concept_key(name)
    fits = (concept for concept in concepts if len(concept) <= _CONCEPT_MAX)
    return next((concept for concept in fits if concept_key(concept) == key), None)


def check_section(section: Section, facts: Facts) -> Section:
    """The section with every item checked. An item that fails is dropped."""
    items = [checked for item in section.items if (checked := _item(item, facts)) is not None]
    return section.model_copy(update={
        "concept": tree_name(section.concept, facts.concepts),
        "items": _one_check_last(items),
    })


def _one_check_last(items: list[Item]) -> list[Item]:
    """The items with the first check question after everything else, and no
    other. Each check can be answered, and a first answer moves mastery, so
    two in one section would move it twice."""
    checks = [item for item in items if item.type == "check"]
    return [*(item for item in items if item.type != "check"), *checks[:1]]


def check_block(block: Block, facts: Facts) -> Block | None:
    """One block, checked. None when it has to be dropped."""
    block = _without_labels(block)
    source_id = getattr(block, "source_id", None)
    if source_id is not None and source_id not in facts.sources:
        block = block.model_copy(update={"source_id": None})
    rule = _RULES.get(block.type)
    return rule(block, facts) if rule else block


def _item(item: Item, facts: Facts) -> Item | None:
    return _prose(item, facts) if isinstance(item, ProseItem) else check_block(item, facts)


def _prose(item: ProseItem, facts: Facts) -> ProseItem:
    paragraphs = [
        paragraph.model_copy(
            update={"citations": [c for c in paragraph.citations if c in facts.sources]},
        )
        for paragraph in item.paragraphs
    ]
    return item.model_copy(update={"paragraphs": paragraphs})


# ── Source labels left in a block ─────────────────────────────────────────────


def _unlabelled(value):
    if isinstance(value, str):
        return CITATION.sub("", value)
    if isinstance(value, list):
        return [_unlabelled(entry) for entry in value]
    if isinstance(value, dict):
        return {key: _unlabelled(entry) for key, entry in value.items()}
    return value


def _without_labels(block: Block) -> Block:
    """The block with any `[S1]` taken out of its text. A block names its
    source in `source_id`; a label inside a string would be shown as written."""
    return _ITEM.validate_python(_unlabelled(block.model_dump()))


# ── Charts ────────────────────────────────────────────────────────────────────


def _numbers_in(text: str) -> set[float]:
    found = set()
    for sign, digits in _NUMBER.findall(text):
        number = float(digits.replace(",", ""))
        found.add(-number if sign else number)
    return found


def _chart_numbers(chart: ChartBlock) -> set[float]:
    """Every number the chart shows: the coordinates it draws, and the ones
    written in a marker's labels and a readout's values."""
    points = [point for series in chart.series for point in series.points]
    drawn = {n for at in [*points, *chart.markers] for n in (at.x, at.y)}
    written = [
        *(label for marker in chart.markers for label in (marker.x_label, marker.y_label)),
        *(value for readout in chart.readouts for value in (readout.before, readout.after)),
    ]
    return drawn.union(*(_numbers_in(text) for text in written))


def _chart(chart: ChartBlock, facts: Facts) -> ChartBlock:
    """Plotted from data only when the chart cites a source and every number
    it shows is in that source's text. Numbers are compared as numbers."""
    text = facts.sources.get(chart.source_id) if chart.source_id else None
    plotted = text is not None and _chart_numbers(chart) <= _numbers_in(text)
    return chart.model_copy(update={"illustrative": not plotted})


# ── Mistakes ──────────────────────────────────────────────────────────────────


def _evidence(mistake: QuizMistake) -> str:
    line = f"From your quizzes on {mistake.concept}."
    return line if len(line) <= _EVIDENCE_MAX else "From your quizzes."


def _mistakes(block: MistakesBlock, facts: Facts) -> MistakesBlock | None:
    recorded = {mistake.id: mistake for mistake in facts.mistakes}
    cited = [
        mistake.model_copy(update={"evidence": _evidence(recorded[mistake.evidence_id])})
        for mistake in block.mistakes
        if mistake.evidence_id in recorded
    ]
    return block.model_copy(update={"mistakes": cited}) if cited else None


# ── Check questions ───────────────────────────────────────────────────────────


def _without_verdict(explanation: str | None) -> str | None:
    text = _VERDICT.sub("", explanation or "", count=1)
    return text[:1].upper() + text[1:] if text else None


def _check(check: CheckBlock, facts: Facts) -> CheckBlock | None:
    option_ids = [option.id for option in check.options]
    if check.correct_id not in option_ids or len(set(option_ids)) != len(option_ids):
        return None
    return check.model_copy(update={
        "concept": tree_name(check.concept, facts.concepts),
        "explain_correct": _without_verdict(check.explain_correct),
        "explain_incorrect": _without_verdict(check.explain_incorrect),
    })


# ── Concept maps and comparisons ──────────────────────────────────────────────


def _concept_map(block: ConceptMapBlock, facts: Facts) -> ConceptMapBlock | None:
    nodes = {}
    for node in block.nodes:
        name = tree_name(node.concept, facts.concepts)
        if name:
            nodes.setdefault(name, node.model_copy(update={"concept": name}))
    if len(nodes) < 2:
        return None
    return block.model_copy(update={"nodes": list(nodes.values())})


def _comparison(block: ComparisonBlock, facts: Facts) -> ComparisonBlock | None:
    rows = [row for row in block.rows if len(row.cells) == len(block.columns)]
    return block.model_copy(update={"rows": rows}) if len(rows) >= 2 else None


_RULES = {
    "chart": _chart,
    "mistakes": _mistakes,
    "check": _check,
    "concept_map": _concept_map,
    "comparison": _comparison,
}
