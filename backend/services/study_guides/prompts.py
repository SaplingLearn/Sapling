"""The user messages for the three study-guide agents.

The agents' system prompts (`agents/study_guide.py`) name the labelled parts a
message carries: this file writes them. The outline message has SCOPE, GOAL,
DEPTH, SECTIONS, CONCEPTS, SOURCES and, on an update, CURRENT OUTLINE. The
section and block messages have GUIDE, SECTION, CONCEPTS, SOURCES and, when
there is one to cite, QUIZ HISTORY. Only the block message ends with
`BLOCK_REWRITE_MARKER` and the block.

Everything that came from a document, from the student or from a model is
untrusted here (`services/prompt_safety.py`): source text with its file name,
quiz mistakes and the block to rewrite go inside an envelope, and short
values (concept names, titles the outline agent wrote from the sources) are
neutralised and kept on one line.

Pure functions, no I/O.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from agents.study_guide import BLOCK_REWRITE_MARKER
from models.study_guide import Block, Depth, Goal, GuideContent, ScopeKind, Section, Tier
from services.prompt_safety import neutralize_delimiters, wrap_untrusted
from services.study_guides.materials import SourceText
from services.study_guides.signals import QuizMistake, concept_key

#: Why a block is rewritten, as the block agent's system prompt tells the two
#: cases apart.
REWRITE_REJECTED = (
    "The app could not use this block: broken JSON, a missing field or a limit "
    "exceeded. Write what it was trying to say in a form that follows every rule."
)
REWRITE_ASKED = "The student asked for a new version of this block."

_GOALS: dict[Goal, str] = {"practice": "practice", "review": "review", "exam_prep": "exam prep"}
_SCOPES: dict[ScopeKind, str] = {"exam": "an exam", "assignment": "an assignment"}
#: What the marker reads as when a document or a block happens to hold it: the
#: block agent, and the function-mode handler, find the block by the real one.
_MARKER_IN_DATA = BLOCK_REWRITE_MARKER.replace(":", " (quoted):")


@dataclass(frozen=True)
class Brief:
    """What every message about one guide is written from."""

    scope_kind: ScopeKind
    scope_label: str
    goal: Goal
    depth: Depth
    sources: list[SourceText]
    #: The student's concept names in the class, as their tree spells them.
    concepts: list[str]
    #: Mastery tier per concept name. Empty when the guide is made without
    #: the student's history.
    tiers: dict[str, Tier]
    #: The quiz mistakes there are to cite. Empty without history.
    mistakes: list[QuizMistake]

    def labels(self) -> dict[str, str]:
        """Source label (`S1`) to source id, as `markup` reads citations."""
        return {source.label: source.source.id for source in self.sources}

    def mistakes_for(self, section: Section) -> list[QuizMistake]:
        """The mistakes the section's writer is offered: the ones made on the
        concept it teaches."""
        if not section.concept:
            return []
        key = concept_key(section.concept)
        return [mistake for mistake in self.mistakes if concept_key(mistake.concept) == key]


# ── Untrusted values ──────────────────────────────────────────────────────────


def _line(text: str | None) -> str:
    """A short student-derived value on one line, unable to close an envelope."""
    return " ".join(neutralize_delimiters(text or "").split())


def _source(source: SourceText) -> str:
    # The envelope's label is the server's own (`S1`). The file name is the
    # student's, so it goes inside with the text.
    named = f"File: {_line(source.source.name)}\n{source.text}"
    return wrap_untrusted(named, source=source.label)


def _quoted(text: str) -> str:
    """Text with any copy of the rewrite marker defused."""
    return text.replace(BLOCK_REWRITE_MARKER, _MARKER_IN_DATA)


# ── Parts ─────────────────────────────────────────────────────────────────────


def _scope(brief: Brief) -> str:
    if brief.scope_kind == "course":
        return "the whole course"
    return f"{_line(brief.scope_label)} ({_SCOPES[brief.scope_kind]})"


def _goal_and_depth(brief: Brief) -> list[str]:
    return [f"GOAL: {_GOALS[brief.goal]}", f"DEPTH: {brief.depth}"]


def _concepts(brief: Brief) -> str:
    if not brief.concepts:
        return "CONCEPTS: none yet. Every concept field is null."
    if not brief.tiers:
        return "\n".join(["CONCEPTS:", *(f"- {_line(name)}" for name in brief.concepts)])
    lines = [f"- [{brief.tiers.get(name, 'unexplored')}] {_line(name)}" for name in brief.concepts]
    return "\n".join([
        "CONCEPTS (in brackets, how well the student knows each one; the name is what follows):",
        *lines,
    ])


def _sources(brief: Brief) -> str:
    return "\n".join(["SOURCES:", *(_source(source) for source in brief.sources)])


def _quiz_history(mistakes: list[QuizMistake]) -> str:
    if not mistakes:
        return ""
    entries = "\n".join(f"{mistake.id}: {' '.join(mistake.text.split())}" for mistake in mistakes)
    return "QUIZ HISTORY:\n" + wrap_untrusted(entries, source="the student's quiz mistakes, by id")


def _current_outline(current: list[Section], new_labels: list[str]) -> str:
    lines = [
        f"- id: {section.id} | title: {_line(section.title)} | "
        f"concept: {_line(section.concept) or 'null'} | one_line: {_line(section.one_line)}"
        for section in current
    ]
    return "\n".join([
        "CURRENT OUTLINE:",
        *lines,
        f"New since it was written: {', '.join(new_labels)}",
    ])


def _guide(brief: Brief, content: GuideContent) -> str:
    outline = [
        f"{number}. {_line(section.title)}: {_line(section.one_line)}"
        for number, section in enumerate(content.sections, start=1)
    ]
    return "\n".join([
        "GUIDE:",
        f"Title: {_line(content.title)}",
        f"For: {_scope(brief)}",
        *_goal_and_depth(brief),
        "Outline:",
        *outline,
    ])


def _section(brief: Brief, content: GuideContent, section: Section) -> str:
    number = next(
        (n for n, other in enumerate(content.sections, start=1) if other.id == section.id), 1,
    )
    lines = [
        "SECTION:",
        f"Number: {number} of {len(content.sections)}",
        f"Title: {_line(section.title)}",
        f"Concept: {_line(section.concept) or 'none'}",
        f"Main idea: {_line(section.one_line)}",
    ]
    if section.concept and brief.tiers:
        lines.append(f"How well the student knows it: {section.tier}")
    lines.append(f"Share of the guide: {section.weight}%")
    return "\n".join(lines)


def _joined(parts: list[str]) -> str:
    return _quoted("\n\n".join(part for part in parts if part))


# ── Messages ──────────────────────────────────────────────────────────────────


def outline_message(
    brief: Brief,
    *,
    low: int,
    high: int,
    current: list[Section] | None = None,
    new_labels: list[str] | None = None,
) -> str:
    """The outline agent's message. `low` to `high` is the number of sections
    to plan. On an update `current` is the sections that can be kept as
    written and `new_labels` the sources added since."""
    scope = "\n".join([
        f"SCOPE: {_scope(brief)}",
        *_goal_and_depth(brief),
        f"SECTIONS: {low} to {high}" if low < high else f"SECTIONS: {high}",
    ])
    update = _current_outline(current, new_labels or []) if current else ""
    return _joined([scope, _concepts(brief), _sources(brief), update])


def section_message(brief: Brief, content: GuideContent, section: Section) -> str:
    """The section writer's message for one section of `content`."""
    return _joined([
        _guide(brief, content),
        _section(brief, content, section),
        _concepts(brief),
        _sources(brief),
        _quiz_history(brief.mistakes_for(section)),
    ])


def block_message(
    brief: Brief, content: GuideContent, section: Section, *, block_text: str, why: str,
) -> str:
    """The block agent's message: what the section was written from, why the
    block is rewritten (`REWRITE_REJECTED` or `REWRITE_ASKED`), then the
    marker and the block as it stands. The block is enveloped (a rejected
    one is raw model output); the marker stays a line of its own above it."""
    block = wrap_untrusted(_quoted(block_text), source="the block as it stands")
    return "\n\n".join([
        section_message(brief, content, section),
        f"WHY: {why}",
        f"{BLOCK_REWRITE_MARKER}\n{block}",
    ])


def block_as_written(block: Block, brief: Brief) -> str:
    """A stored block the way the section writer writes one: no server-owned
    field, and its source by label."""
    data = block.model_dump(mode="json", exclude={"id", "illustrative", "source_id"})
    source_id = getattr(block, "source_id", None)
    label = next((s.label for s in brief.sources if s.source.id == source_id), None)
    if label:
        data["source"] = label
    for mistake in data.get("mistakes", []):
        mistake.pop("evidence", None)
    return json.dumps(data, ensure_ascii=False)
