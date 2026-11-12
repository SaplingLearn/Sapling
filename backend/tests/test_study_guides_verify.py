"""`services.study_guides.verify`: what a written section is held to."""
from __future__ import annotations

import pytest

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
    KeyTerm,
    KeyTermsBlock,
    Mistake,
    MistakesBlock,
    Paragraph,
    ProseItem,
    Section,
    WorkedExampleBlock,
    WorkedStep,
)
from services.study_guides import verify
from services.study_guides.signals import QuizMistake
from services.study_guides.verify import Facts, check_block, check_section, tree_name

DOC = "document:doc-1"
OTHER_DOC = "document:doc-2"
FACTS = Facts(
    sources={
        DOC: "Demand falls from 40 units to 25 when the price rises from $4 to $5.50.",
        OTHER_DOC: "No numbers here.",
    },
    mistakes=[
        QuizMistake(id="m1", concept="Elasticity", text="Divides the wrong way round"),
        QuizMistake(id="m2", concept="Supply and Demand", text="Mixes up shifts and movements"),
    ],
    concepts=["Elasticity", "Supply and Demand", "Consumer Surplus"],
)


def _chart(points, *, source_id=DOC, markers=(), illustrative=True) -> ChartBlock:
    return ChartBlock(
        id="s1-i2", title="Demand", x_label="Price", y_label="Quantity", alt="A falling line.",
        series=[ChartSeries(label="Demand", points=[ChartPoint(x=x, y=y) for x, y in points])],
        markers=[ChartMarker(x=x, y=y, x_label="P", y_label="Q") for x, y in markers],
        source_id=source_id, illustrative=illustrative,
    )


def _check(**over) -> CheckBlock:
    fields = dict(
        id="s1-i9", question="What is the elasticity?",
        options=[CheckOption(id="a", text="0.5"), CheckOption(id="b", text="1.5"),
                 CheckOption(id="c", text="15")],
        correct_id="b",
        explain_correct="15 divided by 10 is 1.5.",
        explain_incorrect="Work out the ratio first.",
        concept="Elasticity",
    )
    return CheckBlock(**{**fields, **over})


def _mistakes(*evidence_ids: str) -> MistakesBlock:
    return MistakesBlock(id="s1-i3", title="From your quizzes", mistakes=[
        Mistake(title=f"Slip {n}", fix="Do it the other way.", evidence_id=evidence_id,
                evidence="Quiz 4, question 3")
        for n, evidence_id in enumerate(evidence_ids, start=1)
    ])


# ── Citations and sources ─────────────────────────────────────────────────────


def test_a_citation_that_is_not_one_of_the_guides_sources_is_dropped():
    prose = ProseItem(id="s1-i1", summary="Short.", paragraphs=[
        Paragraph(text="A fact.", citations=[DOC, "document:someone-elses", OTHER_DOC]),
        Paragraph(text="Another.", citations=["quiz-history"]),
    ])

    section = check_section(Section(id="s1", title="Demand", items=[prose]), FACTS)

    (checked,) = section.items
    assert [p.citations for p in checked.paragraphs] == [[DOC, OTHER_DOC], []]
    assert [p.text for p in checked.paragraphs] == ["A fact.", "Another."]
    assert checked.summary == "Short."


def test_a_block_source_that_is_not_one_of_the_guides_sources_is_cleared():
    formula = FormulaBlock(id="s1-i2", name="Elasticity", latex="e = a / b", spoken="a over b",
                           source_id="document:someone-elses")
    cited = formula.model_copy(update={"source_id": DOC})

    assert check_block(formula, FACTS).source_id is None
    assert check_block(cited, FACTS) == cited


def test_a_source_label_left_inside_a_block_is_stripped():
    example = WorkedExampleBlock(
        id="s1-i4", title="Find the elasticity [S1]", problem="Price rises 10% [S2, S3].",
        steps=[WorkedStep(title="Divide", math="15 / 10", why="By definition [s1]."),
               WorkedStep(title="Read it", math="1.5", why="Above one is elastic.")],
    )
    terms = KeyTermsBlock(id="s1-i5", title="Terms", terms=[
        KeyTerm(term="Elastic", definition="Quantity responds strongly [S1]."),
        KeyTerm(term="Inelastic", definition="Quantity barely responds."),
    ])

    checked_example, checked_terms = check_block(example, FACTS), check_block(terms, FACTS)

    assert checked_example.title == "Find the elasticity"
    assert checked_example.problem == "Price rises 10%."
    assert checked_example.steps[0].why == "By definition."
    assert checked_example.id == "s1-i4"
    assert checked_terms.terms[0].definition == "Quantity responds strongly."
    assert checked_terms.terms[1] == terms.terms[1]


# ── Mistakes ──────────────────────────────────────────────────────────────────


def test_a_mistakes_evidence_is_written_from_the_real_quiz_history():
    (first, second) = check_block(_mistakes("m2", "m1"), FACTS).mistakes

    # Whatever the model wrote there ("Quiz 4, question 3") is replaced.
    assert first.evidence == "From your quizzes on Supply and Demand."
    assert second.evidence == "From your quizzes on Elasticity."
    assert (first.title, first.fix) == ("Slip 1", "Do it the other way.")


def test_a_mistake_that_cites_no_recorded_mistake_is_dropped():
    checked = check_block(_mistakes("m9", "m1", "made-up"), FACTS)

    assert [m.evidence_id for m in checked.mistakes] == ["m1"]


def test_a_mistakes_block_with_nothing_real_to_cite_is_dropped():
    assert check_block(_mistakes("m9"), FACTS) is None
    # No history offered (history off, or none on this section's concept).
    no_history = Facts(sources=FACTS.sources, mistakes=[], concepts=FACTS.concepts)
    assert check_block(_mistakes("m1"), no_history) is None


def test_a_concept_name_too_long_for_the_evidence_line_is_left_out_of_it():
    facts = Facts(sources={}, concepts=[],
                  mistakes=[QuizMistake(id="m1", concept="x" * 200, text="Slips")])

    (mistake,) = check_block(_mistakes("m1"), facts).mistakes

    assert mistake.evidence == "From your quizzes."


# ── Check questions ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "broken",
    [
        {"correct_id": None},
        {"correct_id": "d"},
        {"options": [CheckOption(id="a", text="0.5"), CheckOption(id="b", text="1.5"),
                     CheckOption(id="b", text="15")]},
    ],
    ids=["no answer", "answer not an option", "two options share an id"],
)
def test_a_check_that_cannot_be_graded_is_dropped(broken):
    assert check_block(_check(**broken), FACTS) is None


def test_a_sound_check_is_kept_as_written():
    check = _check()
    assert check_block(check, FACTS) == check


def test_a_checks_concept_is_the_trees_spelling_or_nothing():
    respelled = check_block(_check(concept="  supply AND   demand "), FACTS)
    unknown = check_block(_check(concept="Game Theory"), FACTS)

    assert respelled.concept == "Supply and Demand"
    assert unknown.concept is None
    assert unknown.correct_id == "b"


@pytest.mark.parametrize(
    ("written", "shown"),
    [
        ("Correct. 15 divided by 10 is 1.5.", "15 divided by 10 is 1.5."),
        ("Correct! it is 1.5.", "It is 1.5."),
        ("Not quite. Work out the ratio first.", "Work out the ratio first."),
        ("not quite, try the ratio.", "Try the ratio."),
        ("Correct answers divide quantity by price.", "Correct answers divide quantity by price."),
        ("Correct.", None),
    ],
)
def test_the_readers_own_opening_words_are_stripped_from_explanations(written, shown):
    checked = check_block(_check(explain_correct=written, explain_incorrect=written), FACTS)

    assert (checked.explain_correct, checked.explain_incorrect) == (shown, shown)


# ── Concept names ─────────────────────────────────────────────────────────────


def test_a_sections_concept_is_the_trees_spelling_or_nothing():
    known = check_section(Section(id="s1", title="Demand", concept="consumer  surplus"), FACTS)
    unknown = check_section(Section(id="s2", title="Games", concept="Game Theory"), FACTS)

    assert known.concept == "Consumer Surplus"
    assert unknown.concept is None
    assert (unknown.id, unknown.title) == ("s2", "Games")


def test_tree_name_matches_on_case_and_spacing_only():
    assert tree_name("ELASTICITY", FACTS.concepts) == "Elasticity"
    assert tree_name("Elastic", FACTS.concepts) is None
    assert tree_name(None, FACTS.concepts) is None
    assert tree_name("", FACTS.concepts) is None
    # A tree name the contract cannot hold counts as not there.
    assert tree_name("x" * 121, ["x" * 121]) is None


def test_a_concept_map_keeps_only_the_students_concepts():
    block = ConceptMapBlock(id="s1-i6", title="Builds on", nodes=[
        ConceptMapNode(concept="supply and demand", step="Foundations"),
        ConceptMapNode(concept="Game Theory", step="Aside"),
        ConceptMapNode(concept="Elasticity", step="This section"),
        ConceptMapNode(concept="ELASTICITY", step="Again"),
    ])

    checked = check_block(block, FACTS)

    assert [(n.concept, n.step) for n in checked.nodes] == [
        ("Supply and Demand", "Foundations"), ("Elasticity", "This section"),
    ]


def test_a_concept_map_with_fewer_than_two_known_concepts_is_dropped():
    block = ConceptMapBlock(id="s1-i6", title="Builds on", nodes=[
        ConceptMapNode(concept="Elasticity", step="This section"),
        ConceptMapNode(concept="Game Theory", step="Aside"),
    ])

    assert check_block(block, FACTS) is None


# ── Comparisons ───────────────────────────────────────────────────────────────


def _comparison(*cell_counts: int) -> ComparisonBlock:
    return ComparisonBlock(id="s1-i7", title="Elastic and inelastic", columns=["Elastic", "Inelastic"],
                           rows=[ComparisonRow(label=f"Row {n}", cells=["x"] * cells)
                                 for n, cells in enumerate(cell_counts, start=1)])


def test_a_comparison_row_that_does_not_fit_the_columns_is_dropped():
    checked = check_block(_comparison(2, 3, 2), FACTS)

    assert [row.label for row in checked.rows] == ["Row 1", "Row 3"]
    assert check_block(_comparison(2, 2), FACTS) == _comparison(2, 2)


def test_a_comparison_with_fewer_than_two_sound_rows_is_dropped():
    assert check_block(_comparison(2, 3, 3), FACTS) is None


# ── Charts ────────────────────────────────────────────────────────────────────


def test_a_chart_is_plotted_from_data_when_every_number_is_in_its_source():
    # 4, 5.5, 40 and 25 are all in the source: as `$4`, `$5.50`, `40`, `25`.
    chart = _chart([(4, 40), (5.5, 25)], markers=[(4.0, 40.0)])

    assert check_block(chart, FACTS).illustrative is False


@pytest.mark.parametrize(
    "chart",
    [
        _chart([(4, 40), (5.5, 26)], illustrative=False),
        _chart([(4, 40), (5.5, 25)], markers=[(6, 25)], illustrative=False),
        _chart([(0, 0), (4, 40)], illustrative=False),
        _chart([(4, 40), (5.5, 25)], source_id=None, illustrative=False),
        _chart([(4, 40), (5.5, 25)], source_id=OTHER_DOC, illustrative=False),
        _chart([(4, 40), (5.5, 25)], source_id="document:someone-elses", illustrative=False),
    ],
    ids=["a point not in the source", "a marker not in the source", "an origin the source never gives",
         "no source cited", "the wrong source cited", "a source the guide does not have"],
)
def test_any_other_chart_is_illustrative_whatever_the_model_said(chart):
    assert check_block(chart, FACTS).illustrative is True


def test_a_charts_readouts_and_marker_labels_are_held_to_the_source_too():
    """A readout or a marker label shows a number as plainly as a point does."""
    sourced = _chart([(4, 40), (5.5, 25)], markers=[(4, 40)]).model_copy(update={
        "markers": [ChartMarker(x=4, y=40, x_label="P = $4", y_label="Q = 40")],
        "readouts": [ChartReadout(label="Price", before="$4", after="$5.50", change="Rises")],
    })
    invented_readout = sourced.model_copy(update={
        "readouts": [ChartReadout(label="Revenue", before="$999", after="$12345", change="Rises")],
    })
    invented_label = sourced.model_copy(update={
        "markers": [ChartMarker(x=4, y=40, x_label="P", y_label="Q=777")],
    })

    assert check_block(sourced, FACTS).illustrative is False
    assert check_block(invented_readout, FACTS).illustrative is True
    assert check_block(invented_label, FACTS).illustrative is True


def _written_chart(**texts) -> ChartBlock:
    """A chart drawn from the source's numbers, with `texts` written on it."""
    series_label = texts.pop("series_label", "Demand")
    readout = {"label": "Price", "before": "$4", "after": "$5.50", "change": "Rises",
               **texts.pop("readout", {})}
    return ChartBlock(
        id="s1-i2", source_id=DOC, illustrative=False,
        series=[ChartSeries(label=series_label, points=[ChartPoint(x=4, y=40), ChartPoint(x=5.5, y=25)])],
        readouts=[ChartReadout(**readout)],
        **{"title": "Demand", "x_label": "Price", "y_label": "Quantity", "alt": "A falling line.",
           **texts},
    )


@pytest.mark.parametrize(
    "texts",
    [
        {"title": "Supply at 5 units"},
        {"x_label": "Price in 2019 dollars"},
        {"y_label": "Quantity (per 100)"},
        {"series_label": "Demand in 2019"},
        {"after_label": "After the $2 tax"},
        {"alt": "A line falling to 12."},
        {"readout": {"label": "Price in 2019"}},
        {"readout": {"change": "Up 7%"}},
    ],
    ids=["title", "x axis", "y axis", "series", "after label", "alt", "readout label", "readout change"],
)
def test_a_number_the_source_never_gives_anywhere_in_a_charts_text_makes_it_illustrative(texts):
    """The reader shows all of it beside the plot, so one invented number in
    any of it and the chart is not plotted from data."""
    assert check_block(_written_chart(**texts), FACTS).illustrative is True


def test_a_charts_text_may_carry_the_sources_own_numbers():
    chart = _written_chart(
        title="Demand at $4 and $5.50", x_label="Price, $4 to $5.50", y_label="Units, 25 to 40",
        series_label="Demand, 40 to 25", after_label="At $5.50", alt="A line falling from 40 to 25.",
        readout={"label": "Price from $4", "change": "Down to 25"},
    )

    assert check_block(chart, FACTS).illustrative is False


def test_the_reviews_probe_a_change_and_a_title_the_source_does_not_hold():
    facts = Facts(sources={DOC: "The points are 0 1 2 3."}, mistakes=[], concepts=[])
    chart = ChartBlock(
        id="s1-i2", title="Supply at 5 units", x_label="Price", y_label="Quantity",
        alt="A rising line.", source_id=DOC,
        series=[ChartSeries(label="Supply", points=[ChartPoint(x=0, y=1), ChartPoint(x=2, y=3)])],
        readouts=[ChartReadout(label="Quantity", before="1", after="3", change="Up 7%")],
    )

    assert check_block(chart, facts).illustrative is True
    plain = chart.model_copy(update={
        "title": "Supply",
        "readouts": [ChartReadout(label="Quantity", before="1", after="3", change="Up")],
    })
    assert check_block(plain, facts).illustrative is False


@pytest.mark.parametrize(
    ("text", "numbers"),
    [
        ("4, 4.0 and $4", {4.0}),
        ("costs $1,250.50 for 1,000 units", {1250.5, 1000.0}),
        ("falls by -2.5 or −3", {-2.5, -3.0}),
        ("pages 3-5", {3.0, 5.0}),
        ("x2 and v1.2 and H2O", set()),
        ("50% of .5", {50.0, 0.5}),
        ("lists 3,4,5", {3.0, 4.0, 5.0}),
    ],
)
def test_numbers_are_read_from_text_as_numbers(text, numbers):
    assert verify._numbers_in(text) == numbers


# ── A whole section ───────────────────────────────────────────────────────────


def test_a_section_keeps_its_order_and_loses_only_what_fails():
    prose = ProseItem(id="s1-i1", paragraphs=[Paragraph(text="Elasticity measures response.")])
    section = Section(id="s1", title="Elasticity", concept="elasticity", tier="struggling", weight=40,
                      one_line="How much quantity responds to price.", status="written",
                      items=[prose, _chart([(4, 40), (5.5, 25)]), _mistakes("m9"), _comparison(2, 3, 3),
                             _mistakes("m1"), _check(correct_id=None), _check(id="s1-i10")])

    checked = check_section(section, FACTS)

    assert [item.type for item in checked.items] == ["prose", "chart", "mistakes", "check"]
    assert [item.id for item in checked.items] == ["s1-i1", "s1-i2", "s1-i3", "s1-i10"]
    assert checked.concept == "Elasticity"
    assert (checked.tier, checked.weight, checked.status) == ("struggling", 40, "written")


def test_a_section_keeps_one_check_and_it_comes_last():
    """Every check can be answered and each first answer moves mastery, so a
    section has one: the first that holds up, after everything else."""
    prose = ProseItem(id="s1-i1", paragraphs=[Paragraph(text="Elasticity measures response.")])
    after = ProseItem(id="s1-i5", paragraphs=[Paragraph(text="One more thing.")])
    section = Section(id="s1", title="Elasticity", items=[
        prose, _check(id="s1-i2", correct_id=None), _check(id="s1-i3"), _check(id="s1-i4"), after,
    ])

    checked = check_section(section, FACTS)

    assert [item.id for item in checked.items] == ["s1-i1", "s1-i5", "s1-i3"]
    # A section with one check, already last, is left as it is.
    assert check_section(checked, FACTS).items == checked.items
