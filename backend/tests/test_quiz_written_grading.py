import pytest

from models import AnswerQuestionBody
from services.quiz_grading import grade_written
from services.quiz_algebra import equivalent_algebra


@pytest.mark.parametrize("answer", ["0.5", "1/2", "2 / 4", "50%", "5e-1", "+.5", "０.５"])
def test_equivalent_numeric_formats(answer):
    assert grade_written({"type": "numeric", "correct_answer": "1/2"}, answer)


@pytest.mark.parametrize("answer", ["", "nan", "inf", "1/0", "5e9999999", "__import__('os')", "0.5 kg", "0.50001", "1+1", "2**99999999"])
def test_numeric_rejects_invalid_or_inexact_answers(answer):
    assert not grade_written({"type": "numeric", "correct_answer": "0.5"}, answer)


def test_short_answer_accepts_only_explicit_equivalents():
    question = {"type": "short_answer", "correct_answer": "World Health Organization", "accepted_answers": ["WHO"]}
    assert grade_written(question, "  world   HEALTH organization ")
    assert grade_written(question, "who")
    assert not grade_written(question, "World Trade Organization")
    assert not grade_written(question, "")


@pytest.mark.parametrize(("answer", "expected"), [
    ("2(x + 1)", "2x + 2"), ("(x+1)^2", "x^2+2*x+1"),
    ("x/2", "0.5x"), ("1/x", "x^-1"), ("-x^2", "-(x*x)"),
    ("(x^2-1)/(x-1)", "x+1"), ("x*y+y*x", "2*x*y"),
    ("x-x", "0"), ("x/100", "0.01x"),
])
def test_equivalent_algebra_formats(answer, expected):
    assert equivalent_algebra(answer, expected)
    assert grade_written({"type": "symbolic", "correct_answer": expected}, answer)


@pytest.mark.parametrize("answer", ["2x+3", "x=1", "sin(x)", "__import__('os')", "1/0", "x^9999999", "x^(1/2)", "(" * 300, "", "x**2"])
def test_algebra_rejects_wrong_unsupported_and_abusive_input(answer):
    assert not equivalent_algebra(answer, "2x+2")


@pytest.mark.parametrize("body", [{}, {"selected_index": 0, "answer_text": "x"}, {"answer_text": "   "}, {"answer_text": "x" * 2001}])
def test_answer_requires_one_bounded_nonempty_response(body):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        AnswerQuestionBody(question_index=0, **body)


def test_written_wire_projection_never_exposes_grading_key():
    from agents.quiz import QuizQuestion
    from routes.quiz import _agent_question_to_wire, _is_wire_question, _strip_answer_key
    q = QuizQuestion(question="Name the organization.", type="short_answer", difficulty="easy",
                     correct_answer="World Health Organization", accepted_answers=["WHO"],
                     explanation="A UN health agency.", concept="Global health")
    wire = _agent_question_to_wire(q, 1)
    assert _is_wire_question(wire)
    served = _strip_answer_key([wire])[0]
    assert served["type"] == "short_answer"
    assert not {"correct_answer", "accepted_answers", "explanation", "question_hash"} & served.keys()


def test_invalid_symbolic_key_is_not_servable():
    from routes.quiz import _validate_wire_question
    assert not _validate_wire_question({"type": "symbolic", "options": [], "correct_answer": "sin(x)"})


# ── #726 review: one malformed item drops per item, never fails the quiz ──


def _item(**overrides):
    base = {"question": "Name it.", "type": "short_answer", "difficulty": "easy",
            "options": [], "correct_answer": "base case", "accepted_answers": [],
            "explanation": "x", "concept": "Recursion"}
    return {**base, **overrides}


def test_one_malformed_item_is_dropped_per_item_not_for_the_whole_quiz():
    """A single bad item used to raise inside Quiz validation, which burns the
    agent's output retries and 502s the whole request. It must survive output
    validation and be dropped by the route's per-item check instead."""
    from agents.quiz import Quiz
    from routes.quiz import _agent_question_to_wire

    good_mcq = _item(type="multiple_choice", options=["a", "b", "c", "d"], correct_answer="a")
    quiz = Quiz.model_validate({"questions": [
        good_mcq,
        _item(),  # good written
        _item(type="multiple_choice", options=["a", "b", "c"], correct_answer="a"),
        _item(options=["a", "b", "c", "d"]),
        _item(correct_answer="   "),
        _item(correct_answer="x" * 2001),
    ]})
    kept = [_agent_question_to_wire(q, i + 1) is not None for i, q in enumerate(quiz.questions)]
    assert kept == [True, True, False, False, False, False]


def test_blank_or_unbounded_accepted_answers_are_filtered_not_fatal():
    from agents.quiz import Quiz
    from routes.quiz import _agent_question_to_wire

    quiz = Quiz.model_validate({"questions": [
        _item(accepted_answers=["the base case", " ", "y" * 2001]),
    ]})
    wire = _agent_question_to_wire(quiz.questions[0], 1)
    assert wire is not None and wire["accepted_answers"] == ["the base case"]


def test_quiz_output_list_caps_are_clipped_not_declared_in_the_schema():
    # The nested maxItems bounds 400'd live on gemini-2.5-flash-lite ("too
    # many states for serving"); the caps moved into validation. Full
    # coverage: tests/test_quiz_schema_states.py.
    from agents.quiz import Quiz
    item = Quiz.model_json_schema()["$defs"]["QuizQuestion"]["properties"]
    assert "maxItems" not in item["options"]
    assert "maxItems" not in item["accepted_answers"]
    q = Quiz.model_validate({"questions": [
        _item(accepted_answers=[f"a{i}" for i in range(12)]),
    ]}).questions[0]
    assert len(q.accepted_answers) == 8


# ── #726 review: implicit products and scientific-notation ambiguity ──


@pytest.mark.parametrize(("answer", "expected"), [
    ("2xy", "2*x*y"), ("xy", "y*x"), ("3ab^2", "3*a*b*b"), ("xy(x+1)", "x^2*y+x*y"),
    ("2e+1", "2*e+1"), ("2e", "e+e"), ("1e-2*x", "e-2x"),
])
def test_implicit_products_of_single_letter_variables(answer, expected):
    assert equivalent_algebra(answer, expected)


@pytest.mark.parametrize("answer", ["2e+1", "1e1"])
def test_variable_e_is_never_read_as_scientific_notation(answer):
    assert not equivalent_algebra(answer, "21" if answer == "2e+1" else "10")


@pytest.mark.parametrize("answer", ["sin(x)", "xsin(x)", "ln(x)", "sqrt(x)", "cos x", "log(x)"])
def test_function_names_are_rejected_not_read_as_products(answer):
    # s*i*n*x would be a silent misreading; functions are outside the grammar.
    assert not equivalent_algebra(answer, answer)


# ── #726 review: short-answer normalisation and numeric notation ──


@pytest.mark.parametrize("answer", ["base case.", "the base case", "The Base Case.", "A base case", "\"base case\"", "base case;"])
def test_short_answer_ignores_surrounding_punctuation_and_leading_article(answer):
    assert grade_written({"type": "short_answer", "correct_answer": "base case"}, answer)


def test_short_answer_normalises_the_key_too_and_stays_exact():
    question = {"type": "short_answer", "correct_answer": "The base case.", "accepted_answers": []}
    assert grade_written(question, "base case")
    for wrong in ["base", "recursive case", "base cases", "case", "the", "basecase"]:
        assert not grade_written(question, wrong), wrong


def test_short_answer_keeps_meaningful_symbols():
    assert not grade_written({"type": "short_answer", "correct_answer": "C#"}, "C")
    assert not grade_written({"type": "short_answer", "correct_answer": "C++"}, "C")
    assert grade_written({"type": "short_answer", "correct_answer": "a"}, "A")


@pytest.mark.parametrize(("answer", "expected"), [
    ("1,000", "1000"), ("-1,234,567.5", "-1234567.5"), ("1,000%", "10"),
    ("1 1/2", "3/2"), ("-1 1/2", "-3/2"), ("2 3/4", "2.75"),
])
def test_numeric_accepts_thousands_separators_and_mixed_numbers(answer, expected):
    assert grade_written({"type": "numeric", "correct_answer": expected}, answer)


@pytest.mark.parametrize("answer", ["1,00", "1,5", "10,00,000", "1 2", "1 1/2/3", "1 -1/2", ",100"])
def test_numeric_rejects_ambiguous_separators(answer):
    from services.quiz_grading import numeric_value
    assert numeric_value(answer) is None


# ── #726 review: the top-up retry instruction follows the requested format ──


def _topup_message(question_format, first):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from fastapi.testclient import TestClient

    from agents.quiz import Quiz
    from main import app
    from tests.test_quiz_scoring_e import _generate_factory

    run = AsyncMock(side_effect=[
        SimpleNamespace(output=Quiz.model_validate({"questions": first})),
        SimpleNamespace(output=Quiz.model_validate({"questions": [_item(question="Fresh?")]})),
    ])
    with (
        patch("routes.quiz.table", side_effect=_generate_factory()),
        patch("routes.quiz.quiz_agent.run", new=run),
    ):
        TestClient(app).post("/api/quiz/generate", json={
            "user_id": "user_andres", "concept_node_id": "node1", "num_questions": 3,
            "difficulty": "easy", "use_shared_context": False, "question_format": question_format,
        })
    assert run.call_count == 2
    return run.call_args_list[1][0][0]


def test_written_top_up_does_not_demand_options():
    mcq = _item(type="multiple_choice", options=["a", "b", "c", "d"], correct_answer="a")
    message = _topup_message("short_answer", [_item(), {**mcq, "question": "Q2?"}, {**mcq, "question": "Q3?"}])
    assert "VERBATIM in options" not in message
    assert "options must be empty" in message


def test_multiple_choice_top_up_keeps_the_verbatim_rule():
    bad = _item(type="multiple_choice", options=["a", "b", "c", "d"], correct_answer="NOPE")
    good = _item(type="multiple_choice", options=["a", "b", "c", "d"], correct_answer="a")
    message = _topup_message("multiple_choice", [good, {**bad, "question": "Q2?"}, {**bad, "question": "Q3?"}])
    assert "VERBATIM in options" in message
    assert "options must be empty" not in message


def test_mixed_top_up_states_both_rules():
    bad = _item(type="multiple_choice", options=["a", "b", "c"], correct_answer="a")
    message = _topup_message("mixed", [_item(), {**bad, "question": "Q2?"}, {**bad, "question": "Q3?"}])
    assert "VERBATIM in options" in message and "options must be empty" in message


# ── Live click-through (2026-10-19): items a student cannot answer fairly ──
# Dropped per item at GENERATION only (_agent_question_to_wire), never in
# _validate_wire_question, which also re-checks stored attempts on resume.


def _wire(**overrides):
    from agents.quiz import QuizQuestion
    from routes.quiz import _agent_question_to_wire
    return _agent_question_to_wire(QuizQuestion.model_validate(_item(**overrides)), 1)


@pytest.mark.parametrize("answer", [
    "lambda", "eigenvalue", "2theta", "alpha + beta",
    # Short constant names are words too: "pi r^2" grades as p*i*r^2.
    "pi r^2", "rho V", "2 tau",
])
def test_symbolic_key_spelled_as_a_word_is_dropped(answer):
    """A letter run is an implicit product, so 'lambda' parsed as a*a*b*d*l*m:
    served live as 'what is lambda?', it graded the real answer 'eigenvalue'
    wrong and the anagram 'adlmba' right."""
    assert _wire(type="symbolic", correct_answer=answer) is None


@pytest.mark.parametrize("answer", [
    "2xy", "mgh", "x^2 - 1", "2(x + 1)", "ab/c",
    # m*u is mass times initial velocity, an ordinary mechanics product.
    "mu", "mv - mu", "mu^2/2",
])
def test_symbolic_key_with_short_products_is_kept(answer):
    assert _wire(type="symbolic", correct_answer=answer) is not None


@pytest.mark.parametrize("answer", [
    "The base case is a condition that stops the recursion, preventing infinite calls. "
    "It's crucial because without it, the function would call itself indefinitely.",
    "It converts glucose and oxygen into ATP through cellular respiration in the cell",
    "Stops recursion. Prevents overflow.",
    "It is ATP. It stores energy.",
    "It ended in 1945. Then peace.",
    "Glycolysis; then the Krebs cycle",
    # A full stop after punctuation ends a sentence too (#737 review).
    "Mitosis (cell division). Then cytokinesis",
    '"ATP". It stores energy',
    "About 10%. Then less",
    "No. It is not.",
])
def test_short_answer_key_that_is_a_sentence_is_dropped(answer):
    """Exact-match grading cannot accept a paragraph: served live, the student
    wrote the right idea ('the condition that stops the recursion') and was
    marked wrong against a two-sentence key."""
    assert _wire(correct_answer=answer) is None


@pytest.mark.parametrize("answer", [
    "Cellular respiration", "Krebs cycle and electron transport chain", "ATP", "base case.",
])
def test_short_answer_key_that_is_a_term_is_kept(answer):
    assert _wire(correct_answer=answer) is not None


@pytest.mark.parametrize("answer", [
    "John F. Kennedy", "U.S. Constitution", "St. Louis", "Mt. Everest", "Dr. Seuss",
    "Prof. Xavier", "Sept. 11, 2001", "Capt. James Cook", "Dept. of Energy", "Pres. Lincoln",
    "e.g. mitochondria",
])
def test_short_answer_key_with_an_abbreviation_is_not_a_sentence(answer):
    """An initial or abbreviation is not a sentence break; dropping these
    shortened the quiz for keys exact matching handles fine."""
    assert _wire(correct_answer=answer) is not None


def test_short_answer_sentence_key_with_a_term_alias_is_kept():
    """The grader accepts the alias, so a student who writes the term gets it
    right even though the canonical key is a sentence."""
    item = _wire(
        correct_answer="The condition that stops the recursion before the stack overflows",
        accepted_answers=["base case"],
    )
    assert item is not None


@pytest.mark.parametrize("question", [
    "Which structure is shown?\n",
    "What is the output of this code?\n```\nprint(1)\n```\n",
    "What molecule is called the energy currency? ",
    "The powerhouse of the cell is the ___ ",
])
def test_whole_stem_with_trailing_whitespace_is_kept_and_trimmed(question):
    """Trailing whitespace after the question mark, a code fence or a blank
    is padding on a whole stem, not a cut."""
    item = _wire(question=question)
    assert item is not None
    assert item["question"] == question.rstrip()


@pytest.mark.parametrize("item", [
    _item(question="What molecule is often referred to as the "),
    # The cut can land after punctuation too: the quote followed ": " or ", ".
    _item(question="Fill in the blank: "),
    _item(question="Consider the term, "),
    _item(question="Read the code:\n"),
    # A cut right after a sentence: the quote it stopped at held the question.
    _item(question="Consider this definition. "),
    _item(type="multiple_choice", options=["a", "b", "c", "d"], correct_answer="a",
          question="Which is called the "),
])
def test_stem_cut_off_mid_string_is_dropped(item):
    """Gemini sometimes ends a function-call string at an inner double quote:
    served live as 'What molecule is often referred to as the ' (the model was
    writing the "energy currency"). The trailing whitespace is the tell."""
    from agents.quiz import QuizQuestion
    from routes.quiz import _agent_question_to_wire
    assert _agent_question_to_wire(QuizQuestion.model_validate(item), 1) is None


def test_resume_still_accepts_a_stored_item_the_generation_guards_would_drop():
    from routes.quiz import _validate_wire_question
    assert _validate_wire_question({"type": "short_answer", "options": [],
                                    "correct_answer": "The base case stops it. Always."})
