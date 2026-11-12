"""Study-guide agents.

Three agents write a guide (`docs/design/study-guide-redesign.md`, section 5),
all on the `study_guide` slot:

- `study_guide_outline_agent` plans it: a small structured `GuideOutline`.
- `study_guide_section_agent` writes one section as TEXT: prose with fenced
  JSON blocks, which `services.study_guides.markup` turns into items. The item
  union in `models/study_guide.py` is far past the structured-output budget
  (`tests/test_agent_output_schemas.py`), which is why this is not structured.
- `study_guide_block_agent` rewrites one block, as one fenced JSON block.

`study_guide_agent` (with `StudyGuide` and `Topic`) is the pre-redesign agent.
The old route still imports it; all three go when that route is replaced.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from agents._bounded import clip_list, clip_prose
from agents._providers import model_for
from agents.deps import SaplingDeps
from services.prompt_safety import INJECTION_GUARD_PROMPT


class Topic(BaseModel):
    """One study-guide topic."""

    name: str = Field(description="Topic name.")
    importance: str = Field(
        description="One sentence explaining why this topic matters for the exam.",
    )
    concepts: list[str] = Field(
        description="3-5 surface-level concept bullet points the student should understand.",
    )


class StudyGuide(BaseModel):
    """Typed study guide. Serializes to the legacy JSON contract via model_dump()."""

    exam: str = Field(description="The exam title.")
    due_date: str = Field(description="The exam due date, YYYY-MM-DD.")
    overview: str = Field(
        description="2-3 sentence overview of what this exam covers and how to approach it.",
    )
    topics: list[Topic] = Field(description="The topics that make up the study guide.")


_SYSTEM_PROMPT = (
    "You are a study guide generator for a student exam-prep tool. Given an "
    "exam and the student's course material, break the material into clear "
    "topics. For each topic provide a topic name, 3-5 surface-level concept "
    "bullet points the student should understand, and one sentence explaining "
    "why the topic matters for the exam. Also produce a 2-3 sentence overview "
    "of what the exam covers and how to approach it. Stay grounded in the "
    "provided material; do not invent topics the material does not support. "
    "Echo the exam title and due date you are given."
)
_PROMPT_HASH = hashlib.sha256(_SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]


study_guide_agent = Agent[SaplingDeps, StudyGuide](
    model=model_for("study_guide"),
    deps_type=SaplingDeps,
    output_type=StudyGuide,
    # #153: bounded output-validation retry budget for this idempotent
    # generation task. Tool-less agent, so `retries=` IS the output budget
    # (see the validation-retry policy note in agents/__init__.py).
    retries=2,
    system_prompt=_SYSTEM_PROMPT,
    metadata={"prompt_version": _PROMPT_HASH, "agent": "study_guide"},
)


def _hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]


# ── Outline ───────────────────────────────────────────────────────────────────

#: The most sections an outline keeps. The range the prompt asks for
#: (`services.study_guides.prompts`) must sit inside it.
MAX_OUTLINE_SECTIONS = 12


class OutlineSection(BaseModel):
    title: str = Field(max_length=120)
    concept: str | None = Field(
        default=None,
        max_length=120,
        description="A concept name copied exactly from CONCEPTS, or null.",
    )
    one_line: Annotated[str, clip_prose(240, "study_guide.outline.one_line")] = Field(
        max_length=240, description="The section's main idea, stated in one sentence."
    )
    keep_id: str | None = Field(
        default=None,
        max_length=40,
        description=(
            "Update runs only: the id of the CURRENT OUTLINE section to keep "
            "as written. Null otherwise."
        ),
    )


class GuideOutline(BaseModel):
    """The plan of a guide. The server adds each section's id, tier and weight
    (`services.study_guides.plan`); the model never decides those."""

    title: str = Field(max_length=120)
    deck: Annotated[str, clip_prose(240, "study_guide.outline.deck")] = Field(
        max_length=240, description="One sentence on what the guide covers."
    )
    takeaways: Annotated[list[str], clip_list(3, "study_guide.outline.takeaways")] = Field(
        max_length=3, description="The three things most worth remembering."
    )
    sections: Annotated[
        list[OutlineSection], clip_list(MAX_OUTLINE_SECTIONS, "study_guide.outline.sections")
    ] = Field(min_length=1, max_length=MAX_OUTLINE_SECTIONS)


_OUTLINE_PROMPT = f"""\
You plan a study guide for one student in Sapling, a study app. You do not \
write the guide. You write its outline: a title, a one-line deck, three \
takeaways and the list of sections. A second writer then writes each section \
from your outline, one at a time, so every section must stand as its own topic.

WHAT YOU ARE GIVEN
The message carries labelled parts:
- SCOPE: what the guide is for (an exam, an assignment or the whole course), \
with GOAL and DEPTH.
- SECTIONS: the range of sections to plan, for example "3 to 5".
- CONCEPTS: the names of the concepts this student is tracking in the class.
- SOURCES: the student's own course material, each labelled S1, S2 and so on.
- CURRENT OUTLINE, in an update run only: the sections the guide already has, \
each with its id, and which sources are new since it was written.

WHAT TO WRITE
- title: a short name for the guide's subject, like a chapter title. Not \
"Study guide for ...".
- deck: one plain sentence telling the student what the guide covers.
- takeaways: exactly three. Each is one plain sentence the student could \
repeat from memory: the three things in the material that matter most for \
this scope.
- sections: stay inside the SECTIONS range and choose the number the material \
supports. A few full sections serve a student better than many thin ones. Put \
them in the order a student should learn them.

For each section:
- title: a few words naming the topic.
- concept: the one name from CONCEPTS this section teaches, copied character \
for character, or null when no name fits. The app uses it to look up how well \
the student knows the topic, so a near miss is worse than null. Use a name \
for at most one section.
- one_line: the main idea itself in one sentence ("A loop repeats a block \
until its condition turns false."), not a description of the section ("This \
section covers loops.").
- keep_id: null, except in an update run (below).

UPDATE RUNS
When the message has a CURRENT OUTLINE, the guide exists and new material has \
arrived. Plan the whole outline again with the new material folded in. For a \
current section the new material does not change, set keep_id to its id and \
repeat its title, concept and one_line as they are: the app keeps that section \
exactly as written, with the student's progress on it. Give keep_id null to a \
section that is new or that the new material changes; it is written fresh. \
Use each id at most once, and only ids that appear in CURRENT OUTLINE.

GROUNDING
Plan only what SOURCES teach. Do not add a section for a topic the sources do \
not cover, even when it appears in CONCEPTS or is a usual part of such a \
course. State no fact in a takeaway or one_line that the sources do not \
support.

{INJECTION_GUARD_PROMPT}
"""

study_guide_outline_agent = Agent[SaplingDeps, GuideOutline](
    model=model_for("study_guide"),
    deps_type=SaplingDeps,
    output_type=GuideOutline,
    # #153: a tool-less structured agent, so `retries=` is the output budget.
    retries=2,
    system_prompt=_OUTLINE_PROMPT,
    metadata={"prompt_version": _hash(_OUTLINE_PROMPT), "agent": "study_guide_outline"},
)


# ── Blocks, as the model writes them ──────────────────────────────────────────
#
# One sample per block type: what the model writes, which is the contract's
# block minus the fields the server owns (`id`, `illustrative`, `evidence`),
# and with a source LABEL ("source": "S1") where the contract has `source_id`.
# The prompts print these, and `tests/test_study_guide_agents.py` parses each
# one through `markup.parse_block`, so a contract change that the prompt has
# not followed fails there.
_BLOCK_SHAPES: dict[str, dict] = {
    "chart": {
        "type": "chart",
        "title": "What the chart shows",
        "x_label": "The x quantity",
        "y_label": "The y quantity",
        "series": [
            {
                "label": "Name of this line",
                "points": [{"x": 0, "y": 0}, {"x": 5, "y": 10}],
                "state": "both",
            }
        ],
        "markers": [
            {"x": 5, "y": 10, "x_label": "Short x name", "y_label": "Short y name", "state": "before"}
        ],
        "readouts": [
            {"label": "A quantity", "before": "Its value before", "after": "Its value after", "change": "Rises"}
        ],
        "after_label": "After",
        "alt": "The chart described in words, for a screen reader.",
        "source": "S1",
    },
    "mistakes": {
        "type": "mistakes",
        "title": "From your quizzes",
        "mistakes": [
            {
                "title": "The slip, named in a few words",
                "fix": "What to do instead, in one or two sentences.",
                "evidence_id": "The QUIZ HISTORY entry's id",
            }
        ],
    },
    "formula": {
        "type": "formula",
        "name": "What the formula is called",
        "latex": "\\bar{x} = \\frac{a + b}{2}",
        "spoken": "The formula read aloud in plain words.",
        "source": "S1",
    },
    "worked_example": {
        "type": "worked_example",
        "title": "What the problem practises",
        "problem": "The problem, stated in full.",
        "steps": [
            {
                "title": "What this step does",
                "math": "The working for this step",
                "why": "Why this is the right move.",
            },
            {"title": "The next step", "math": "Its working", "why": "Its reason."},
        ],
        "source": "S1",
    },
    "comparison": {
        "type": "comparison",
        "title": "What is being compared",
        "columns": ["First thing", "Second thing"],
        "rows": [
            {
                "label": "A point of comparison",
                "cells": ["How the first thing does it", "How the second does it"],
                "emphasis": False,
            },
            {
                "label": "The point most tested",
                "cells": ["The first thing here", "The second thing here"],
                "emphasis": True,
            },
        ],
    },
    "concept_map": {
        "type": "concept_map",
        "title": "What this section builds on",
        "nodes": [
            {"concept": "A name from CONCEPTS", "step": "Foundations"},
            {"concept": "Another name from CONCEPTS", "step": "This section"},
        ],
    },
    "key_terms": {
        "type": "key_terms",
        "title": "New in this section",
        "terms": [
            {"term": "A term", "definition": "What it means, in one plain sentence."},
            {"term": "Another term", "definition": "What that one means."},
        ],
    },
    "check": {
        "type": "check",
        "question": "One question on the section's main idea.",
        "options": [
            {"id": "a", "text": "An answer"},
            {"id": "b", "text": "Another answer"},
            {"id": "c", "text": "Another answer"},
        ],
        "correct_id": "b",
        "explain_correct": "Why that answer is right.",
        "explain_incorrect": "A nudge toward the method, without giving the answer away.",
        "concept": "The section's concept",
    },
}

# When each block earns its place, and the limits a block is rejected for
# breaking (the contract's strict lengths and counts).
_BLOCK_RULES: dict[str, str] = {
    "chart": (
        "For a relationship between two quantities whose shape matters: growth, a "
        "shift, a before and after. 1 to 4 series of 2 to 12 points each. A series "
        'with "state": "after" is drawn only in the After state, so use it for the '
        "line that changes; leave the rest \"both\". Optional: up to 2 markers "
        '(a labelled point; "state" is "before" or "after"; each label at most 16 '
        "characters), up to 2 readouts (each value at most 24 characters) and "
        "after_label (what the After state is called). Axis labels at most 32 "
        "characters. Use only numbers that appear in the source you cite. When "
        "the source gives no numbers, the chart can still show the shape: keep "
        "the coordinates simple and do not refer to them as data in your prose, "
        "because the page labels such a chart as an illustrative shape and "
        "hides its axis numbers."
    ),
    "mistakes": (
        "Only when the message has QUIZ HISTORY entries that bear on this "
        "section. 1 to 3 mistakes. Each names the slip, gives the fix, and "
        "carries the id of the entry it comes from in evidence_id, copied "
        "exactly. Never write a mistake that is not in QUIZ HISTORY, and do not "
        "say how often it happened or on which quiz: the app adds that line "
        "from its own records."
    ),
    "formula": (
        "For a relationship the student must be able to write down or apply. "
        "Only formulas the sources give. latex has no $ signs."
    ),
    "worked_example": (
        "For a kind of problem the student will be asked to solve. 2 to 6 "
        "steps. The page reveals one step at a time, so each step carries its "
        "own working in math and its own reason in why. Prefer a problem from "
        "the sources; then cite it."
    ),
    "comparison": (
        "For two or three things students mix up. columns names the 2 or 3 "
        "things; every row has a label and one cell per column, 2 to 6 rows. "
        'Set "emphasis": true on at most one row, the one most likely to be '
        "tested."
    ),
    "concept_map": (
        "To show where this section's concept sits among the others the student "
        "is learning. 2 to 5 nodes in learning order. Every concept is a name "
        "from CONCEPTS, copied exactly: the page looks up the student's mastery "
        "by that name, so a name that is not in CONCEPTS cannot be shown. step "
        "is a short position label of at most 24 characters. Skip this block "
        "when fewer than two CONCEPTS names truly relate to the section."
    ),
    "key_terms": (
        "When the section introduces several terms. 2 to 6 terms, each at most "
        "60 characters, with a one-sentence definition. Do not define a term an "
        "earlier section of the outline already owns."
    ),
    "check": (
        "One question that tests the section's main idea. 3 or 4 options with "
        'ids "a", "b", "c", "d" in order, exactly one of them correct. '
        "explain_incorrect is shown after a wrong pick, when the student may "
        "try again, so point at the method and do not reveal the answer. "
        "concept is the SECTION's concept, copied exactly (null when the "
        "section has none), because a first answer moves the student's mastery "
        "of that concept. A section has at most one check, and it is the last "
        "thing in the section."
    ),
}

_FENCE = "```"

_BLOCK_REFERENCE = "\n\n".join(
    f"{kind}\n{json.dumps(shape)}\n{_BLOCK_RULES[kind]}" for kind, shape in _BLOCK_SHAPES.items()
)

_BLOCK_FORMAT = f"""\
A block is one JSON object inside a fence: a line that is exactly {_FENCE}block, \
the JSON, then a line that is exactly {_FENCE}. One block per fence. Write \
valid JSON: double quotes, no trailing commas, no comments. Inside a JSON \
string a LaTeX backslash is written twice, as in the formula sample below.

Never write "id", "illustrative" or "evidence": the app sets those. A block \
that draws on a source names it by label, "source": "S2". Leave "source" out \
when the block comes from no single source.

Keep every title under 80 characters. The samples show each type's fields; \
the words in them describe what goes there and are not content to copy.

{_BLOCK_REFERENCE}"""

_GROUNDING = """\
Everything you state comes from SOURCES, and for a mistakes block from QUIZ \
HISTORY. You may explain and connect what the sources say in your own words. \
Do not add facts, numbers, dates, quotations or quiz results that are not \
there, and never give a page or slide number: a citation names a document and \
nothing finer. A worked example or a check question may use small made-up \
values to practise a method the sources teach, as long as nothing presents \
them as something the course said. When the sources say little about the \
topic, write less. A short honest section is better than a padded one."""


# ── Section writer ────────────────────────────────────────────────────────────

_SECTION_PROMPT = f"""\
You write one section of a study guide for one student in Sapling, a study \
app. The outline is already planned. You are given one of its sections and \
you write that section only. A program parses your text and the student reads \
the result on a page that shows prose and interactive blocks, so the format \
below is exact.

WHAT YOU ARE GIVEN
The message carries labelled parts:
- GUIDE: the guide's title, what it is for, its GOAL and DEPTH, and the full \
outline, so you know what the other sections cover and do not repeat them.
- SECTION: the title, concept and one-line main idea of the section to write. \
It may also say how well the student knows the concept and what share of the \
guide this section gets.
- CONCEPTS: the names of the concepts this student is tracking in the class.
- SOURCES: the student's own course material, each labelled S1, S2 and so on.
- QUIZ HISTORY, when the student has one: mistakes this student made on \
quizzes, each with an id.

VOICE
Write as a tutor writing to one student. Plain words, short sentences, second \
person ("you"). Be concrete: prefer an example to an abstraction, and say the \
thing instead of announcing it ("A loop repeats ...", never "In this section \
we will look at loops"). Keep the exam in view: where the sources show how \
something is asked or what is stressed, tell the student. No praise, no \
filler, no exclamation marks.

GROUNDING
{_GROUNDING}

FORMAT
Write prose and blocks in the order the student should read them, and nothing \
else: no heading (the page prints the section title), no opening line about \
what you are going to do, no closing remark.

Prose
- Plain paragraphs with a blank line between them. No lists, headings, tables \
or code fences in prose. Keep a paragraph under about 120 words.
- Mark a key term with double asterisks the first time it appears: \
**base case**. Inline math goes in $...$.
- When a sentence states something from a source, end it with that source's \
label in square brackets: ... before every pass [S2]. Cite only labels that \
appear in SOURCES.
- After each run of one to three paragraphs, write one line that starts with \
">> ". It is the skim summary of that run: one or two plain sentences that \
replace those paragraphs when the student switches to Skim mode. A run with \
no summary line disappears in Skim mode, so give every run one.

Blocks
{_BLOCK_FORMAT}

SHAPE
A section reads like this, where each JSON line stands for one whole block:

A paragraph. It marks a **key term** and ends a sourced sentence with a label [S1].

A second paragraph of the same run.

>> One or two sentences that stand in for the two paragraphs above.

{_FENCE}block
{{"type": "formula", "name": "...", "latex": "...", "spoken": "...", "source": "S1"}}
{_FENCE}

The next run of prose.

>> Its summary.

{_FENCE}block
{{"type": "check", "question": "...", "options": [...], "correct_id": "...", "explain_correct": "...", "explain_incorrect": "...", "concept": "..."}}
{_FENCE}

CHOOSING BLOCKS
A block has to earn its place: use one where it shows something better than a \
paragraph would, and never repeat in a block what the prose beside it just \
said. Most sections want prose first, then blocks between further passages. \
Do not use the same block type twice in a section, except worked_example when \
the goal or depth below asks for more practice.

GOAL AND DEPTH
DEPTH sets how much you write.
- cram: the shortest useful version. One short passage and at most two \
blocks: what to memorise and nothing else.
- standard: two or three passages and the two to four blocks the material \
calls for.
- deep: fuller. Explain why as well as what, cover the edge cases the sources \
raise, and add worked examples. Up to five passages.

GOAL sets what you lean on.
- practice: prose is brief setup for doing. Use more worked examples and \
always end with a check.
- review: help the student organise what they have already seen. Lean on \
comparison and key_terms, and connect this section to the others.
- exam prep: put what is most likely to be tested first, say how it is \
usually asked, and mark it (the emphasis row of a comparison, the problem \
type of a worked example). Follow what the sources themselves stress.

When SECTION says how well the student knows the concept: for a concept they \
are struggling with or have not explored, start from the basics and go \
slower, with more examples; for one they have mastered, write a brief \
refresher. A larger share of the guide means a longer section, within what \
DEPTH allows.

{INJECTION_GUARD_PROMPT}
"""

study_guide_section_agent = Agent[SaplingDeps, str](
    model=model_for("study_guide"),
    deps_type=SaplingDeps,
    output_type=str,
    system_prompt=_SECTION_PROMPT,
    metadata={"prompt_version": _hash(_SECTION_PROMPT), "agent": "study_guide_section"},
)


# ── Block rewriter ────────────────────────────────────────────────────────────

#: The line `services.study_guides.prompts` puts directly above the block in
#: the block agent's user message. The block agent's system prompt names it,
#: and the function-mode handler (`agents/function_handlers_e2e.py`) tells a
#: block rewrite from a section by it: both run on the `study_guide` task and
#: both answer in text. A section message must therefore never carry it.
BLOCK_REWRITE_MARKER = "BLOCK TO REWRITE:"

_BLOCK_PROMPT = f"""\
You rewrite one block of a study-guide section for one student in Sapling, a \
study app. The rest of the section stays as it is. Your reply replaces that \
one block, and a program parses it, so the format below is exact.

WHAT YOU ARE GIVEN
The message carries the labelled parts the section was written from (GUIDE, \
SECTION, CONCEPTS, SOURCES and, when the student has one, QUIZ HISTORY), says \
why the block is being rewritten, and ends with the line "{BLOCK_REWRITE_MARKER}" \
followed by the block as it stands.

WHAT TO WRITE
Reply with exactly one fenced block of the same type as the one you were \
given, and nothing before or after the fence.
- When the block was rejected (broken JSON, a missing field, a limit \
exceeded), write what it was trying to say in a form that follows every rule \
below.
- When the student asked for a new version, write a fresh take on the same \
point: a different example, question or wording, not a copy.

GROUNDING
{_GROUNDING}

FORMAT
{_BLOCK_FORMAT}

{INJECTION_GUARD_PROMPT}
"""

study_guide_block_agent = Agent[SaplingDeps, str](
    model=model_for("study_guide"),
    deps_type=SaplingDeps,
    output_type=str,
    system_prompt=_BLOCK_PROMPT,
    metadata={"prompt_version": _hash(_BLOCK_PROMPT), "agent": "study_guide_block"},
)
