"""`services.study_guides.markup`: the section writer's text as items."""

from __future__ import annotations

import json

import pytest

from models.study_guide import BLOCK_TYPES, QUIZ_HISTORY_SOURCE
from services.study_guides.markup import parse_block, parse_section, put_back

SOURCES = {"S1": "document:doc-1", "S2": "document:doc-2", "S3": QUIZ_HISTORY_SOURCE}

# One realistic block per type, as a model writes it: no id, a source label.
BLOCKS: dict[str, dict] = {
    "chart": {
        "type": "chart",
        "title": "Passes against input size",
        "x_label": "Input size",
        "y_label": "Passes",
        "series": [
            {"label": "One loop", "points": [{"x": 0, "y": 0}, {"x": 10, "y": 10}]},
            {
                "label": "Nested loop",
                "points": [{"x": 0, "y": 0}, {"x": 5, "y": 25}, {"x": 10, "y": 100}],
                "state": "after",
            },
        ],
        "markers": [{"x": 10, "y": 100, "x_label": "n", "y_label": "n squared", "state": "after"}],
        "readouts": [{"label": "Passes", "before": "n", "after": "n squared", "change": "Grows faster"}],
        "after_label": "Nested",
        "alt": "A straight line for one loop and a steeper curve for a nested loop.",
        "source": "S1",
    },
    "mistakes": {
        "type": "mistakes",
        "title": "From your quizzes",
        "mistakes": [
            {
                "title": "Counting one pass too many",
                "fix": "Check the condition with the last value by hand.",
                "evidence_id": "m1",
            }
        ],
    },
    "formula": {
        "type": "formula",
        "name": "Passes of a counting loop",
        "latex": "\\frac{stop - start}{step}",
        "spoken": "Stop minus start, divided by step.",
        "source": "S2",
    },
    "worked_example": {
        "type": "worked_example",
        "title": "Count the passes",
        "problem": "A loop starts i at 2 and adds 3 while i is below 14. How many passes?",
        "steps": [
            {"title": "List the values", "math": "2, 5, 8, 11", "why": "14 is not below 14."},
            {"title": "Count them", "math": "4 passes", "why": "One pass per value."},
        ],
    },
    "comparison": {
        "type": "comparison",
        "title": "While and for",
        "columns": ["While", "For"],
        "rows": [
            {"label": "Use it when", "cells": ["Passes unknown", "Passes known"]},
            {"label": "Common bug", "cells": ["No update", "Off by one"], "emphasis": True},
        ],
    },
    "concept_map": {
        "type": "concept_map",
        "title": "What this section builds on",
        "nodes": [
            {"concept": "Variables", "step": "Foundations"},
            {"concept": "Loops", "step": "This section"},
        ],
    },
    "key_terms": {
        "type": "key_terms",
        "title": "New in this section",
        "terms": [
            {"term": "Condition", "definition": "The test a loop makes before each pass."},
            {"term": "Body", "definition": "The block a loop repeats."},
        ],
    },
    "check": {
        "type": "check",
        "question": "A loop starts i at 0 and adds 2 while i is below 7. How many passes?",
        "options": [{"id": "a", "text": "3"}, {"id": "b", "text": "4"}, {"id": "c", "text": "7"}],
        "correct_id": "b",
        "explain_correct": "i takes 0, 2, 4 and 6.",
        "explain_incorrect": "List every value i takes.",
        "concept": "Loops",
    },
}


def fenced(block: dict | str, language: str = "block") -> str:
    body = block if isinstance(block, str) else json.dumps(block)
    return f"```{language}\n{body}\n```"


def parse(text: str, section_id: str = "s1"):
    return parse_section(text, section_id=section_id, sources=SOURCES)


def kinds(parsed) -> list[str]:
    return [item.type for item in parsed.items]


# ── Prose ─────────────────────────────────────────────────────────────────────


def test_paragraphs_up_to_a_summary_line_are_one_passage():
    parsed = parse(
        "A **while loop** checks its condition first.\n\n"
        "The exam asks how many times it runs.\n\n"
        ">> A while loop repeats while its condition holds.\n"
    )

    (passage,) = parsed.items
    assert passage.type == "prose"
    assert passage.id == "s1-i1"
    assert [p.text for p in passage.paragraphs] == [
        "A **while loop** checks its condition first.",
        "The exam asks how many times it runs.",
    ]
    assert passage.summary == "A while loop repeats while its condition holds."
    assert parsed.rejected == []


def test_a_summary_line_closes_its_passage():
    parsed = parse("First.\n\n>> About the first.\n\nSecond.\n")

    first, second = parsed.items
    assert (first.id, first.summary) == ("s1-i1", "About the first.")
    assert (second.id, second.summary) == ("s1-i2", None)
    assert second.paragraphs[0].text == "Second."


def test_wrapped_lines_are_one_paragraph():
    (passage,) = parse("A loop repeats\na block of code.\n").items

    assert [p.text for p in passage.paragraphs] == ["A loop repeats a block of code."]


def test_more_than_three_paragraphs_split_and_the_summary_stays_last():
    parsed = parse("One.\n\nTwo.\n\nThree.\n\nFour.\n\nFive.\n\n>> All five.\n")

    first, second = parsed.items
    assert [p.text for p in first.paragraphs] == ["One.", "Two.", "Three."]
    assert first.summary is None
    assert [p.text for p in second.paragraphs] == ["Four.", "Five."]
    assert second.summary == "All five."
    assert [first.id, second.id] == ["s1-i1", "s1-i2"]


def test_a_summary_with_no_passage_above_it_is_dropped():
    parsed = parse(f">> Nothing above.\n\n{fenced(BLOCKS['key_terms'])}\n\n>> Still nothing.\n")

    assert kinds(parsed) == ["key_terms"]
    assert parsed.items[0].id == "s1-i1"


def test_citations_are_mapped_and_stripped():
    (passage,) = parse(
        "A loop checks its condition before every pass [S1]. It stops when "
        "the condition is false [S2][S1].\n\n"
        "You got this wrong twice. [s3]\n\n"
        "Both lectures say so [S1, S2].\n"
    ).items

    first, second, third = passage.paragraphs
    assert first.text == (
        "A loop checks its condition before every pass. It stops when the condition is false."
    )
    assert first.citations == ["document:doc-1", "document:doc-2"]
    assert second.text == "You got this wrong twice."
    assert second.citations == [QUIZ_HISTORY_SOURCE]
    assert third.citations == ["document:doc-1", "document:doc-2"]


def test_an_unknown_label_is_dropped_from_text_and_citations():
    (passage,) = parse("A fact from nowhere [S9]. A real one [S2].\n").items

    assert passage.paragraphs[0].text == "A fact from nowhere. A real one."
    assert passage.paragraphs[0].citations == ["document:doc-2"]


def test_a_citation_in_a_summary_is_stripped():
    (passage,) = parse("A fact.\n\n>> The fact [S1].\n").items

    assert passage.summary == "The fact."


def test_a_paragraph_that_is_only_a_citation_is_dropped():
    (passage,) = parse("A fact.\n\n[S1]\n").items

    assert [p.text for p in passage.paragraphs] == ["A fact."]


def test_headings_and_rules_are_dropped():
    parsed = parse("## Loops\nA loop repeats.\n\n---\n\n### More\n\nIt stops.\n")

    (passage,) = parsed.items
    assert [p.text for p in passage.paragraphs] == ["A loop repeats.", "It stops."]


def test_windows_newlines():
    block = fenced(BLOCKS["key_terms"]).replace("\n", "\r\n")
    parsed = parse(f"One.\r\n\r\nTwo.\r\n\r\n>> Both.\r\n\r\n{block}\r\n")

    assert kinds(parsed) == ["prose", "key_terms"]
    assert [p.text for p in parsed.items[0].paragraphs] == ["One.", "Two."]
    assert parsed.items[0].summary == "Both."


def test_empty_text_is_an_empty_section():
    parsed = parse("  \n\n")

    assert parsed.items == [] and parsed.rejected == []


# ── Blocks ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("kind", BLOCK_TYPES)
def test_every_block_type_parses(kind):
    parsed = parse(f"Some prose.\n\n{fenced(BLOCKS[kind])}\n")

    assert parsed.rejected == []
    prose, block = parsed.items
    assert block.type == kind
    assert (prose.id, block.id) == ("s1-i1", "s1-i2")


def test_a_block_closes_the_passage_above_it():
    parsed = parse(f"Before.\n{fenced(BLOCKS['formula'])}\nAfter.\n")

    assert kinds(parsed) == ["prose", "formula", "prose"]
    assert [item.id for item in parsed.items] == ["s1-i1", "s1-i2", "s1-i3"]


def test_a_blocks_source_label_becomes_its_source_id():
    parsed = parse(
        "\n".join([
            fenced(BLOCKS["formula"]),
            fenced({**BLOCKS["formula"], "source": "S9"}),
            fenced({**BLOCKS["formula"], "source": "[s1]"}),
            fenced(BLOCKS["worked_example"]),
        ])
    )

    assert [block.source_id for block in parsed.items] == [
        "document:doc-2",
        None,
        "document:doc-1",
        None,
    ]


def test_server_owned_fields_are_never_the_models():
    chart = {**BLOCKS["chart"], "id": "mine", "illustrative": False, "source_id": "document:forged"}
    mistake = {**BLOCKS["mistakes"]["mistakes"][0], "evidence": "Quiz 4, question 3"}
    mistakes = {**BLOCKS["mistakes"], "mistakes": [mistake]}

    chart_block, mistakes_block = parse(f"{fenced(chart)}\n{fenced(mistakes)}", "s2").items

    assert chart_block.id == "s2-i1"
    assert chart_block.illustrative is True
    assert chart_block.source_id == "document:doc-1"
    assert mistakes_block.id == "s2-i2"
    assert [m.evidence for m in mistakes_block.mistakes] == [""]
    assert mistakes_block.mistakes[0].evidence_id == "m1"


def test_fence_drift_is_read():
    parsed = parse(
        "\n".join([
            fenced(BLOCKS["formula"], "json"),
            "```block   \n" + json.dumps(BLOCKS["key_terms"]) + "\n```  ",
            fenced(json.dumps(BLOCKS["check"], indent=2), ""),
        ])
    )

    assert kinds(parsed) == ["formula", "key_terms", "check"]
    assert parsed.rejected == []


def test_an_unclosed_block_does_not_swallow_the_next_one():
    text = "```block\n" + json.dumps(BLOCKS["formula"]) + "\n" + fenced(BLOCKS["key_terms"])

    assert kinds(parse(text)) == ["formula", "key_terms"]


def test_a_malformed_block_is_rejected_and_its_neighbours_survive():
    broken = '{"type": "formula", "name": "Passes", "latex": "a", "spoken": "a",}'
    parsed = parse(
        f"Before.\n\n{fenced(BLOCKS['key_terms'])}\n\n{fenced(broken)}\n\n"
        f"After.\n\n{fenced(BLOCKS['check'])}\n"
    )

    assert kinds(parsed) == ["prose", "key_terms", "prose", "check"]
    # The rejected block keeps its place, so the ids around it do not move.
    assert [item.id for item in parsed.items] == ["s1-i1", "s1-i2", "s1-i4", "s1-i5"]
    (reject,) = parsed.rejected
    assert reject.id == "s1-i3"
    assert reject.type == "formula"
    assert reject.raw == {}
    assert reject.text == broken


def test_a_block_that_fails_the_contract_is_rejected_with_what_was_written():
    too_few = {"type": "key_terms", "title": "One term", "terms": [BLOCKS["key_terms"]["terms"][0]]}

    parsed = parse(fenced(too_few))

    assert parsed.items == []
    (reject,) = parsed.rejected
    assert (reject.id, reject.type, reject.raw) == ("s1-i1", "key_terms", too_few)


@pytest.mark.parametrize(
    "body",
    [
        '{"type": "flashcards", "cards": []}',
        '{"type": "prose", "paragraphs": [{"text": "Smuggled in."}]}',
        '{"title": "No type"}',
        '[{"type": "formula"}]',
        "not json at all",
        "",
    ],
)
def test_what_is_not_a_block_is_rejected(body):
    parsed = parse(f"{fenced(body)}\n\nProse after it.\n")

    assert kinds(parsed) == ["prose"]
    assert parsed.items[0].id == "s1-i2"
    assert [reject.id for reject in parsed.rejected] == ["s1-i1"]


def test_a_reply_cut_inside_a_block_rejects_the_block():
    parsed = parse('Before.\n\n```block\n{"type": "check", "question": "How ma')

    assert kinds(parsed) == ["prose"]
    assert [(r.id, r.type) for r in parsed.rejected] == [("s1-i2", "check")]


def test_a_number_that_is_not_json_is_rejected():
    body = json.dumps(BLOCKS["chart"]).replace('"y": 100', '"y": NaN')

    assert [r.type for r in parse(fenced(body)).rejected] == ["chart"]


def test_latex_written_with_one_backslash_is_rejected():
    # JSON reads `\t` and `\f` as a tab and a form feed, so `\text` and
    # `\frac` would reach the reader as garbage.
    body = json.dumps(BLOCKS["formula"]).replace("\\\\frac", "\\frac")
    assert "\\frac" in body and "\\\\frac" not in body

    parsed = parse(fenced(body))

    assert parsed.items == []
    assert [r.type for r in parsed.rejected] == ["formula"]


# ── One block ─────────────────────────────────────────────────────────────────


def test_parse_block_reads_the_block_agents_reply():
    block = parse_block(fenced(BLOCKS["formula"]), block_id="s3-i4", sources=SOURCES)

    assert (block.type, block.id, block.source_id) == ("formula", "s3-i4", "document:doc-2")
    assert block.latex == "\\frac{stop - start}{step}"


def test_parse_block_reads_a_bare_object_and_ignores_text_around_a_fence():
    bare = parse_block(json.dumps(BLOCKS["check"]), block_id="s1-i2", sources=SOURCES)
    wrapped = parse_block(
        f"Here is the block.\n\n{fenced(BLOCKS['check'], 'json')}\n\nDone.",
        block_id="s1-i2",
        sources=SOURCES,
    )

    assert bare == wrapped
    assert bare.correct_id == "b"


@pytest.mark.parametrize("reply", ["", "Sorry, I cannot.", fenced('{"type": "formula",}')])
def test_parse_block_answers_none_for_a_reply_with_no_valid_block(reply):
    assert parse_block(reply, block_id="s1-i2", sources=SOURCES) is None


def test_a_rewritten_block_goes_back_where_it_was():
    broken = '{"type": "formula",}'
    parsed = parse(
        "\n\n".join([
            "Before.",
            fenced(broken),
            fenced(BLOCKS["key_terms"]),
            fenced(broken),
            "After.",
            fenced(broken),
        ])
    )
    assert [item.id for item in parsed.items] == ["s1-i1", "s1-i3", "s1-i5"]

    items = parsed.items
    # Any order: each block finds its own place.
    for reject in reversed(parsed.rejected):
        block = parse_block(fenced(BLOCKS["formula"]), block_id=reject.id, sources=SOURCES)
        items = put_back(items, block)

    assert [item.id for item in items] == [f"s1-i{n}" for n in range(1, 7)]
    assert [item.type for item in items] == [
        "prose",
        "formula",
        "key_terms",
        "formula",
        "prose",
        "formula",
    ]
