"""Short constructors for the items of a guide section, so the class modules
read as content and every item is a contract model from the start.

A section is drafted once for every length it is read at: ``Part`` says which
lengths have an item. A draft item is not yet part of a guide, so three fields hold stand-ins that
``guides.py`` resolves when it puts the section into one:

- ``id`` is empty (the place in the section decides it);
- a citation and a ``source_id`` hold a document KEY, not a source id;
- a mistake's ``evidence_id`` holds the position of the recorded mistake it
  answers, in the concept's quiz digest.
"""
from __future__ import annotations

from dataclasses import dataclass

from db.local_study_data.spec import Concept
from models.study_guide import (
    ChartBlock,
    ChartMarker,
    ChartPoint,
    ChartReadout,
    ChartSeries,
    CheckBlock,
    CheckOption,
    ComparisonBlock,
    ComparisonRow,
    ConceptMapBlock,
    ConceptMapNode,
    FormulaBlock,
    Item,
    KeyTerm,
    KeyTermsBlock,
    Mistake,
    MistakesBlock,
    Paragraph,
    ProseItem,
    WorkedExampleBlock,
    WorkedStep,
)

_LETTERS = "abcd"


@dataclass(frozen=True)
class Part:
    """One item of a section draft and the lengths of the section that have
    it (``spec.LENGTHS``): every length from ``at`` to ``upto``. A
    ``standard`` passage is in a standard and a deep section and is left out
    of a cram one."""

    item: Item
    at: str = "cram"
    upto: str = "deep"


def prose(
    *paragraphs: str | tuple[str, ...], summary: str, at: str = "cram", upto: str = "deep",
) -> Part:
    """A passage. A paragraph is its text, or ``(text, document key, ...)``
    when it cites. ``at`` and ``upto`` are the shortest and the longest
    section that has it."""
    item = ProseItem(
        id="",
        paragraphs=[
            Paragraph(text=p) if isinstance(p, str) else Paragraph(text=p[0], citations=list(p[1:]))
            for p in paragraphs
        ],
        summary=summary,
    )
    return Part(item=item, at=at, upto=upto)


def at(length: str, block: Item) -> Part:
    """A block that only sections of ``length`` or longer have. Without this
    a block is in standard and deep sections, and the check in every one
    (``guides.py``)."""
    return Part(item=block, at=length)


def formula(name: str, latex: str, spoken: str, source: str | None = None) -> FormulaBlock:
    return FormulaBlock(id="", name=name, latex=latex, spoken=spoken, source_id=source)


def example(
    title: str, problem: str, *steps: tuple[str, str, str], source: str | None = None,
) -> WorkedExampleBlock:
    """A worked example. A step is ``(title, math, why)``."""
    return WorkedExampleBlock(
        id="", title=title, problem=problem, source_id=source,
        steps=[WorkedStep(title=t, math=m, why=w) for t, m, w in steps],
    )


def compare(
    title: str, columns: tuple[str, ...], *rows: tuple[str, ...], emphasis: int,
) -> ComparisonBlock:
    """A comparison table. A row is ``(label, cell, cell, ...)``; ``emphasis``
    is the position of the one row most tested."""
    return ComparisonBlock(
        id="", title=title, columns=list(columns),
        rows=[
            ComparisonRow(label=row[0], cells=list(row[1:]), emphasis=position == emphasis)
            for position, row in enumerate(rows)
        ],
    )


def concept_map(title: str, *nodes: tuple[Concept, str]) -> ConceptMapBlock:
    """What the section builds on. A node is ``(concept, where it sits)``."""
    return ConceptMapBlock(
        id="", title=title,
        nodes=[ConceptMapNode(concept=concept.name, step=step) for concept, step in nodes],
    )


def terms(*entries: Concept | tuple[str, str], title: str = "Key terms") -> KeyTermsBlock:
    """Key terms. An entry is a concept (its name and definition) or
    ``(term, definition)``."""
    pairs = [(e.name, e.definition) if isinstance(e, Concept) else e for e in entries]
    return KeyTermsBlock(
        id="", title=title, terms=[KeyTerm(term=t, definition=d) for t, d in pairs],
    )


def check(question: str, options: tuple[str, ...], correct: int, right: str, wrong: str) -> CheckBlock:
    """A check-yourself question on the section's own concept. ``correct`` is
    the position of the right option."""
    return CheckBlock(
        id="", question=question,
        options=[CheckOption(id=_LETTERS[i], text=text) for i, text in enumerate(options)],
        correct_id=_LETTERS[correct], explain_correct=right, explain_incorrect=wrong,
    )


def mistakes(*entries: tuple[int, str, str], title: str = "From your quizzes") -> MistakesBlock:
    """Common mistakes. An entry is ``(position in the concept's quiz digest,
    title, fix)``."""
    return MistakesBlock(
        id="", title=title,
        mistakes=[Mistake(title=t, fix=fix, evidence_id=str(position)) for position, t, fix in entries],
    )


def line(label: str, *points: tuple[float, float], after: bool = False) -> ChartSeries:
    return ChartSeries(
        label=label, points=[ChartPoint(x=x, y=y) for x, y in points],
        state="after" if after else "both",
    )


def marker(x: float, y: float, x_label: str, y_label: str, after: bool = False) -> ChartMarker:
    return ChartMarker(x=x, y=y, x_label=x_label, y_label=y_label, state="after" if after else "before")


def readout(label: str, before: str, after: str, change: str) -> ChartReadout:
    return ChartReadout(label=label, before=before, after=after, change=change)


def chart(
    title: str, x_label: str, y_label: str, *series: ChartSeries, alt: str,
    source: str | None = None, markers: tuple[ChartMarker, ...] = (),
    readouts: tuple[ChartReadout, ...] = (), after_label: str = "After",
) -> ChartBlock:
    """A line chart. Whether it is plotted from data is decided when the
    section goes into a guide, by the same check the server runs."""
    return ChartBlock(
        id="", title=title, x_label=x_label, y_label=y_label, series=list(series),
        markers=list(markers), readouts=list(readouts), after_label=after_label,
        alt=alt, source_id=source,
    )
