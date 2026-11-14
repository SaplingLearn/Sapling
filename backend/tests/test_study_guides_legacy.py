"""`services/study_guides/legacy.py`: a pre-redesign guide as `GuideContent`."""
from __future__ import annotations

from models.study_guide import GuideContent
from services.study_guides.legacy import UNTITLED, content_from_topics

LEGACY = {
    "exam": "Midterm 1",
    "due_date": "2026-10-20",
    "overview": "Covers loops and functions. Trace code by hand before the exam.",
    "topics": [
        {
            "name": "Loops",
            "importance": "Most trace questions are loops.",
            "concepts": ["while loops", "for loops", "off-by-one errors"],
        },
        {
            "name": "Functions",
            "importance": "Every program on the exam calls one.",
            "concepts": ["parameters", "return values"],
        },
        {
            "name": "Scope",
            "importance": "Name lookup decides what a call can see.",
            "concepts": ["local names"],
        },
    ],
}


def test_each_topic_becomes_a_written_section():
    content = content_from_topics(LEGACY)

    assert content.title == "Midterm 1"
    assert content.scope_label == "Midterm 1"
    assert content.deck == LEGACY["overview"]
    assert content.takeaways == []
    assert content.sources == []
    assert [s.id for s in content.sections] == ["s1", "s2", "s3"]
    assert [s.title for s in content.sections] == ["Loops", "Functions", "Scope"]
    assert {s.status for s in content.sections} == {"written"}
    assert {s.tier for s in content.sections} == {"unexplored"}
    assert {s.concept for s in content.sections} == {None}

    loops = content.sections[0]
    assert loops.one_line == "Most trace questions are loops."
    assert [item.type for item in loops.items] == ["prose"]
    passage = loops.items[0]
    assert passage.id == "s1-i1"
    assert [p.text for p in passage.paragraphs] == [
        "Most trace questions are loops.",
        "- while loops\n- for loops\n- off-by-one errors",
    ]
    assert passage.summary == "Most trace questions are loops."


def test_weights_are_equal_and_sum_to_100():
    assert [s.weight for s in content_from_topics(LEGACY).sections] == [34, 33, 33]

    seven = {"topics": [{"name": f"T{i}"} for i in range(7)]}
    weights = [s.weight for s in content_from_topics(seven).sections]
    assert sum(weights) == 100
    assert max(weights) - min(weights) <= 1


def test_the_result_is_valid_format_2_content():
    content = content_from_topics(LEGACY)
    assert GuideContent.model_validate(content.model_dump(mode="json")) == content


def test_a_long_overview_is_split_at_a_sentence_not_clipped():
    first = "The exam covers recursion, sorting and the cost of both in detail. " * 3
    overview = f"{first.strip()} Work the practice problems. Sleep before the exam."
    content = content_from_topics({"exam": "Final", "overview": overview, "topics": []})

    assert len(content.deck) <= 240
    assert not content.deck.endswith("…")
    assert overview.startswith(content.deck)
    assert " ".join([content.deck, *content.takeaways]) == overview


def test_missing_and_malformed_fields_do_not_raise():
    content = content_from_topics({
        "topics": [
            "not a topic",
            {"name": "", "importance": None, "concepts": "not a list"},
            {"name": "Sorting", "concepts": ["merge sort", 7, "  "]},
        ],
    })

    assert content.title == UNTITLED
    assert content.deck == ""
    assert [s.title for s in content.sections] == ["Topic 1", "Sorting"]
    assert content.sections[0].items == []
    assert [p.text for p in content.sections[1].items[0].paragraphs] == ["- merge sort"]
    assert content.sections[1].items[0].summary is None
    assert sum(s.weight for s in content.sections) == 100

    assert content_from_topics({}).sections == []


def test_long_names_are_cut_to_the_title_limit():
    content = content_from_topics({"exam": "E" * 300, "topics": [{"name": "N" * 300}]})
    assert len(content.title) == 120
    assert len(content.sections[0].title) == 120
