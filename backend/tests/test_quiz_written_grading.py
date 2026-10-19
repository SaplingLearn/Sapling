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
    ("x-x", "0"), ("1e-2*x", "x/100"),
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
