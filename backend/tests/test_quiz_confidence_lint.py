"""Learning-loop spec §13 A132: the quiz's stated confidence and item quality.

- The answer body takes A127's label; the response row stores its
  STUDENT_CONFIDENCE_LEVELS value; an idk written answer states none; the
  resume payload reads it back as the label.
- Submit carries the stated value onto the question's evidence as
  `student_confidence` (never a weight, never the grader's `confidence`).
- Every question of an assembled attempt is linted (A113's linter) and keeps
  its codes; an answer to an item with an excluding code is no evidence, and
  is counted by one `quiz.evidence_excluded` event. The score is unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.quiz import Quiz, QuizQuestion
from learning import params, quiz_evidence
from learning.evidence import Evidence, evidence_weight
from learning.item_lint import (
    ALL_OR_NONE_OF_ABOVE,
    CORRECT_LONGEST,
    CORRECT_REPEATS_STEM,
    DUPLICATE_OPTIONS,
    LINT_FLAGS,
    NEGATIVE_STEM,
)
from tests.test_quiz_answers_c import (
    _ResponsesTable,
    _fake_quiz,
    _generate_factory,
    _post_generate,
    _tables,
    client,
)
from tests.split_patches import patch_quiz
from tests.db_fakes import with_async_twins

LEVELS = params.STUDENT_CONFIDENCE_LEVELS


def _q(qid, stem, texts, correct, **extra):
    """A stored multiple-choice question in the wire shape (labels in order,
    `correct` on the key)."""
    return {
        "id": qid,
        "question": stem,
        "options": [
            {"label": "ABCD"[i], "text": t, "correct": i == correct} for i, t in enumerate(texts)
        ],
        "explanation": "Because.",
        "concept_tested": "Loops",
        "difficulty": "medium",
        "question_hash": f"hash-{qid}",
        **extra,
    }


#: One stored question per lint code (and a clean one): each trips exactly the
#: code it is named after (pinned below), so a route test reads one decision.
FLAGGED = {
    None: ("Which keyword starts a loop in Python?", ["for", "def", "try", "let"], 0),
    CORRECT_LONGEST: ("Which option is right?", ["x", "a much longer correct option text", "y", "z"], 1),
    CORRECT_REPEATS_STEM: (
        "Which organelle produces cellular energy?",
        [
            "organelle producing cellular energy",
            "ribosome assembling protein chains",
            "nucleus storing genetic material",
            "vacuole holding water reserves",
        ],
        0,
    ),
    ALL_OR_NONE_OF_ABOVE: ("Which keyword starts a loop in Python?", ["for", "def", "try", "None of the above"], 0),
    DUPLICATE_OPTIONS: ("What stops a recursion?", ["The base case", "the base cases", "a loop", "a stack"], 2),
    NEGATIVE_STEM: ("Which of these is NOT a loop keyword?", ["for", "while", "def", "do"], 2),
}


def _flagged(code, qid=1, **extra):
    stem, texts, correct = FLAGGED[code]
    return _q(qid, stem, texts, correct, **extra)


@pytest.mark.parametrize("code", list(FLAGGED))
def test_each_fixture_trips_exactly_its_code(code):
    assert quiz_evidence.lint_question(_flagged(code)) == ([] if code is None else [code])


# ── The per-code decision ──────────────────────────────────────────────────


def test_every_lint_code_is_decided_once():
    """The two sets partition LINT_FLAGS: a code the linter gains later fails
    here until A132's table decides whether its answers count."""
    excluding = quiz_evidence.EVIDENCE_EXCLUDING_FLAGS
    counting = quiz_evidence.EVIDENCE_COUNTING_FLAGS
    assert excluding | counting == set(LINT_FLAGS)
    assert not excluding & counting


def test_the_decision_per_code():
    assert quiz_evidence.EVIDENCE_EXCLUDING_FLAGS == {
        CORRECT_LONGEST,  # a cue finds the key
        CORRECT_REPEATS_STEM,  # a cue finds the key
        ALL_OR_NONE_OF_ABOVE,  # partial knowledge finds an AOTA key; NOTA names none
        DUPLICATE_OPTIONS,  # the keyed answer is ambiguous
    }
    assert quiz_evidence.EVIDENCE_COUNTING_FLAGS == {NEGATIVE_STEM}
    assert quiz_evidence.evidence_exclusion([NEGATIVE_STEM]) == []
    assert quiz_evidence.evidence_exclusion([NEGATIVE_STEM, CORRECT_LONGEST]) == [CORRECT_LONGEST]
    assert quiz_evidence.evidence_exclusion([DUPLICATE_OPTIONS, CORRECT_LONGEST]) == [
        CORRECT_LONGEST,
        DUPLICATE_OPTIONS,
    ]


def test_stored_flags_win_and_an_unlinted_question_is_linted_now():
    clean_options_flagged_store = _flagged(None, lint_flags=[CORRECT_LONGEST])
    assert quiz_evidence.question_lint_flags(clean_options_flagged_store) == [CORRECT_LONGEST]
    # stored before A132: no key — the linter answers for it now
    assert quiz_evidence.question_lint_flags(_flagged(CORRECT_LONGEST)) == [CORRECT_LONGEST]
    # a stored value that is not a list of known codes is read as absent
    assert quiz_evidence.question_lint_flags(_flagged(CORRECT_LONGEST, lint_flags=["bogus"])) == [
        CORRECT_LONGEST
    ]
    assert quiz_evidence.question_lint_flags(_flagged(CORRECT_LONGEST, lint_flags="x")) == [
        CORRECT_LONGEST
    ]


def test_a_written_question_is_read_for_the_stem_rule_only():
    written = {"id": 1, "type": "short_answer", "question": "Which of these is not a loop?", "options": []}
    assert quiz_evidence.lint_question(written) == [NEGATIVE_STEM]
    assert quiz_evidence.lint_question({**written, "question": "Name the base case."}) == []


# ── The measurement the decision was made on ───────────────────────────────

CASSETTES = Path(__file__).parent / "evals" / "cassettes" / "quiz_generation"


def test_the_recorded_quiz_cassettes_flag_rates():
    """A132 measured the codes on the recorded quiz_generation cassettes (real
    model outputs, replayed): every question through the route's own wire
    mapping, linted in its stored shape. 29 multiple-choice items; 10 carry
    correct_longest (34.5%), no other code fires. A change to the linter or a
    re-record moves these numbers, and A132's table cites them."""
    from routes.quiz import _agent_question_to_wire

    counts = dict.fromkeys(LINT_FLAGS, 0)
    linted = 0
    for path in sorted(CASSETTES.glob("*.json")):
        for i, raw in enumerate(json.loads(path.read_text())["questions"], start=1):
            wire = _agent_question_to_wire(QuizQuestion.model_validate(raw), i)
            assert wire is not None and not wire.get("type")
            linted += 1
            for flag in quiz_evidence.lint_question(wire):
                counts[flag] += 1
    assert linted == 29
    assert counts == {
        CORRECT_LONGEST: 10,
        CORRECT_REPEATS_STEM: 0,
        ALL_OR_NONE_OF_ABOVE: 0,
        DUPLICATE_OPTIONS: 0,
        NEGATIVE_STEM: 0,
    }


def test_the_e2e_quiz_fixtures_lint_clean():
    """The function-mode quiz (agents/function_handlers_e2e.py) feeds journeys
    that count one evidence per question; a flagged fixture would silently
    drop one. Both its multiple-choice and its written questions lint clean."""
    from agents.function_handlers_e2e import _E2E_QUIZ_QUESTIONS
    from routes.quiz import _agent_question_to_wire

    for i, raw in enumerate(_E2E_QUIZ_QUESTIONS, start=1):
        wire = _agent_question_to_wire(QuizQuestion.model_validate(raw), i)
        assert quiz_evidence.lint_question(wire) == [], raw["question"]
    for kind in ("short_answer", "numeric", "symbolic"):
        stem = f"E2E written question 1: enter the {kind} fixture answer."
        assert quiz_evidence.lint_question({"question": stem, "options": []}) == []


def test_the_e2e_mirror_of_the_confidence_levels():
    """frontend/e2e/support/quiz.ts asserts the stored values against its own
    copy of STUDENT_CONFIDENCE_LEVELS; pin the copy to the source."""
    import re

    src = (Path(__file__).resolve().parents[2] / "frontend/e2e/support/quiz.ts").read_text()
    match = re.search(r"export const CONFIDENCE_LEVELS = \{([^}]*)\} as const;", src)
    assert match, "CONFIDENCE_LEVELS missing from frontend/e2e/support/quiz.ts"
    mirror = {k: float(v) for k, v in re.findall(r"(\w+): ([0-9.]+)", match.group(1))}
    assert mirror == LEVELS


# ── The answer body ─────────────────────────────────────────────────────────


def _answer(body, questions=None):
    factory, responses = _tables()
    with patch("tests.test_quiz_answers_c.QUESTIONS", questions or _two_mc()), patch_quiz(
        "table", side_effect=with_async_twins(factory)
    ):
        r = client.post("/api/quiz/attempts/quiz1/answer", json=body)
    return r, responses.rows


def _two_mc():
    return [_flagged(None, qid=1), _flagged(None, qid=2)]


@pytest.mark.parametrize("label", list(LEVELS))
def test_a_label_is_stored_as_its_level(label):
    r, rows = _answer({"question_index": 0, "selected_index": 0, "confidence": label})
    assert r.status_code == 200, r.text
    assert rows[0]["confidence"] == LEVELS[label]


def test_a_skip_is_stored_as_absent_never_a_default():
    r, rows = _answer({"question_index": 0, "selected_index": 0})
    assert r.status_code == 200, r.text
    assert rows[0]["confidence"] is None


@pytest.mark.parametrize("value", [0.8, 0.85, 1, "Sure", "very_sure", "", True])
def test_anything_but_a_label_is_a_422_and_records_nothing(value):
    r, rows = _answer({"question_index": 0, "selected_index": 0, "confidence": value})
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "QUIZ_VALIDATION_ERROR"
    assert rows == []


def _written(kind="short_answer", key="base case"):
    return [{
        "id": 1, "type": kind, "question": "What stops a recursion?", "options": [],
        "correct_answer": key, "explanation": "The base case.", "difficulty": "easy",
        "question_hash": "hash-w1",
    }]


@pytest.mark.parametrize("text", ["idk", "I don't know", "no idea", "dunno lol"])
def test_an_idk_written_answer_states_no_confidence(text):
    r, rows = _answer({"question_index": 0, "answer_text": text, "confidence": "sure"}, _written())
    assert r.status_code == 200, r.text
    assert rows[0]["confidence"] is None
    assert r.json()["is_correct"] is False


def test_a_hedged_written_answer_is_an_answer_and_keeps_its_confidence():
    r, rows = _answer(
        {"question_index": 0, "answer_text": "idk maybe 0.5", "confidence": "guessing"},
        _written("numeric", "0.5"),
    )
    assert r.status_code == 200, r.text
    assert rows[0]["confidence"] == LEVELS["guessing"]


def test_a_written_answer_keeps_its_confidence():
    r, rows = _answer(
        {"question_index": 0, "answer_text": "base case", "confidence": "fairly_sure"}, _written()
    )
    assert r.status_code == 200, r.text
    assert rows[0]["confidence"] == LEVELS["fairly_sure"]
    assert r.json()["is_correct"] is True


def test_the_quiz_idk_rule_is_the_loops():
    """One A16 idk split: the quiz's reads the loop route's rule."""
    from services.loop.claims import _is_idk_phrase

    for text in (
        "idk", "IDK", "i dont know", "I don't know", "no idea", "dunno", "idk lmao",
        "idk, can I get a hint", "idk maybe 7", "the mitochondria idk", "even, idk",
        "it isn't, idk", "just tell me", "what's the answer", "base case", "", "7",
        "no", "I think it is", "not sure", "idk 2x+2",
    ):
        assert quiz_evidence.is_idk_answer(text) is _is_idk_phrase(text), text


# ── Resume ──────────────────────────────────────────────────────────────────


def test_resume_reads_the_stored_value_back_as_its_label():
    responses = _ResponsesTable()
    for index, value in enumerate([LEVELS["sure"], 0.550000011920929, 0.8, None]):
        responses.insert({
            "attempt_id": "quiz1", "question_index": index, "selected_index": 0,
            "is_correct": True, "time_ms": None, "confidence": value,
            "answered_at": "2026-11-08T00:00:00+00:00",
        })
    questions = [_flagged(None, qid=i + 1) for i in range(5)]
    factory, _ = _tables(responses=responses)
    with patch("tests.test_quiz_answers_c.QUESTIONS", questions), patch_quiz(
        "table", side_effect=with_async_twins(factory)
    ):
        r = client.get("/api/quiz/attempts/quiz1")
    assert r.status_code == 200, r.text
    # the level; a float4 neighbour of a level is that level; a number no
    # label names (written before A132) and a skip are no statement
    assert [x["confidence"] for x in r.json()["responses"]] == ["sure", "fairly_sure", None, None]


@pytest.mark.parametrize(
    "value,label",
    [
        (0.2, "guessing"),
        (0.200000002980232, "guessing"),
        (0.55, "fairly_sure"),
        (0.85, "sure"),
        (0.850000023841858, "sure"),
        (0.5, None),
        (None, None),
        ("0.85", "sure"),
        ("bad", None),
        (True, None),
    ],
)
def test_stored_label(value, label):
    assert quiz_evidence.stored_label(value) == label
    expected = None if label is None else LEVELS[label]
    assert quiz_evidence.evidence_confidence(value) == expected


# ── Submit: the evidence ───────────────────────────────────────────────────


def _submit(questions, recorded=(), answers=()):
    """Submit attempt quiz1 over `questions` with `recorded` quiz_responses
    rows; return (response, the evidence dicts written, the events logged,
    the hashes the farm guard claimed)."""
    responses = _ResponsesTable()
    for row in recorded:
        responses.insert({"attempt_id": "quiz1", "is_correct": True, **row})
    claimed: list[str] = []
    base, _ = _tables(responses=responses)

    def factory(name):
        if name == "quiz_evidence_claims":
            mock = MagicMock()

            def claim(rows, on_conflict=None):
                claimed.extend(r["question_hash"] for r in rows)
                return list(rows)

            mock.insert_ignore_duplicates.side_effect = claim
            mock.update.return_value = []
            return mock
        return base(name)

    apply_mock = MagicMock(return_value=[])
    with (
        patch("tests.test_quiz_answers_c.QUESTIONS", questions),
        patch_quiz("table", side_effect=with_async_twins(factory)),
        patch_quiz("apply_graph_update", new=apply_mock),
        patch_quiz("max_help_many", return_value={}),
        patch_quiz("get_quiz_context", return_value={}),
        patch(
            "services.quiz.submission.quiz_context_agent.run",
            new=AsyncMock(return_value=SimpleNamespace(output=SimpleNamespace(model_dump=lambda: {}))),
        ),
        patch_quiz("save_quiz_context"),
        patch("services.events_service.log_event") as log_event,
    ):
        r = client.post("/api/quiz/submit", json={"quiz_id": "quiz1", "answers": list(answers)})
    written = apply_mock.call_args.args[1]["evidence"] if apply_mock.called else []
    events = [c for c in log_event.call_args_list if c.args[0] == "quiz.evidence_excluded"]
    return r, written, events, claimed


def test_the_stated_confidence_rides_the_evidence_and_a_skip_rides_nothing():
    questions = [_flagged(None, qid=i) for i in (1, 2, 3, 4)]
    r, written, events, _ = _submit(
        questions,
        recorded=[
            {"question_index": 0, "selected_index": 0, "confidence": LEVELS["sure"]},
            {"question_index": 1, "selected_index": 1, "confidence": 0.200000002980232, "is_correct": False},
            {"question_index": 2, "selected_index": 0, "confidence": None},
        ],
        # question 4 only in the payload: no recorded response, no statement
        answers=[{"question_id": 4, "selected_label": "A"}],
    )
    assert r.status_code == 200, r.text
    assert r.json()["score"] == 3
    assert events == []
    assert [e.get("student_confidence") for e in written] == [LEVELS["sure"], LEVELS["guessing"], None, None]
    # absent, not None: an evidence dict without a statement is the pre-A132 dict
    assert "student_confidence" not in written[2] and "student_confidence" not in written[3]
    for raw in written:
        ev = Evidence(**raw)
        assert ev.confidence is None  # never the grader's confidence
        assert ev.weight == evidence_weight(Evidence(**{**raw, "student_confidence": None}))


def test_a_number_no_label_names_reaches_no_evidence():
    r, written, _, _ = _submit(
        [_flagged(None)], recorded=[{"question_index": 0, "selected_index": 0, "confidence": 0.8}]
    )
    assert r.status_code == 200, r.text
    assert "student_confidence" not in written[0]


@pytest.mark.parametrize("code", [c for c in FLAGGED if c is not None])
@pytest.mark.parametrize("correct", [True, False])
def test_the_lint_decision_per_code_at_submit(code, correct):
    """An answer to an item with an excluding code writes no evidence (either
    outcome) and claims nothing; one event says so. negative_stem counts."""
    question = _flagged(code, lint_flags=[code])
    key = next(i for i, o in enumerate(question["options"]) if o["correct"])
    chosen = key if correct else (key + 1) % 4
    clean = _flagged(None, qid=2)
    r, written, events, claimed = _submit(
        [question, clean],
        recorded=[
            {"question_index": 0, "selected_index": chosen, "confidence": LEVELS["sure"], "is_correct": correct},
            {"question_index": 1, "selected_index": 0},
        ],
    )
    assert r.status_code == 200, r.text
    # the score and the results are the quiz's, untouched
    assert r.json()["score"] == int(correct) + 1
    assert [x["correct"] for x in r.json()["results"]] == [correct, True]
    if code in quiz_evidence.EVIDENCE_EXCLUDING_FLAGS:
        assert [e["question_hash"] for e in written] == ["hash-2"]
        assert claimed == ["hash-2"]
        (event,) = events
        assert event.kwargs["category"] == "system"
        assert event.kwargs["user_id"] == "user_andres"
        assert event.kwargs["payload"] == {
            "quiz_id": "quiz1",
            "concept_node_id": "node1",
            "question_hash": "hash-1",
            "flags": [code],
            "excluded_by": [code],
            "correct": correct,
        }
    else:
        assert [e["question_hash"] for e in written] == ["hash-1", "hash-2"]
        assert written[0]["correct"] is correct
        assert written[0]["student_confidence"] == LEVELS["sure"]
        assert sorted(claimed) == ["hash-1", "hash-2"]
        assert events == []


def test_a_question_stored_before_a132_is_linted_at_submit():
    """An attempt generated before the deploy carries no `lint_flags`: the
    rule is about the item, so the linter answers for it at submit."""
    question = _flagged(CORRECT_LONGEST)
    assert "lint_flags" not in question
    r, written, events, _ = _submit(
        [question], recorded=[{"question_index": 0, "selected_index": 1}]
    )
    assert r.status_code == 200, r.text
    assert r.json()["score"] == 1
    assert written == []
    (event,) = events
    assert event.kwargs["payload"]["excluded_by"] == [CORRECT_LONGEST]


def test_every_item_excluded_writes_nothing_and_reports_no_move():
    r, written, events, claimed = _submit(
        [_flagged(DUPLICATE_OPTIONS, lint_flags=[DUPLICATE_OPTIONS])],
        recorded=[{"question_index": 0, "selected_index": 2}],
    )
    assert r.status_code == 200, r.text
    assert written == [] and claimed == []
    assert len(events) == 1
    body = r.json()
    assert body["score"] == 1
    assert body["p_delta"] == 0
    assert body["mastery_after"] == body["mastery_before"]


# ── Generate: the codes are stored, never served ───────────────────────────


def _cued_quiz():
    return Quiz(questions=[
        QuizQuestion(
            question="Which option is right?", type="multiple_choice", difficulty="easy",
            options=["x", "a much longer correct option text", "y", "z"],
            correct_answer="a much longer correct option text", explanation="ok", concept="Loops",
        ),
    ])


@pytest.mark.parametrize("quiz,flags", [(_fake_quiz, []), (_cued_quiz, [CORRECT_LONGEST])])
@pytest.mark.parametrize("keyed", [False, True])
def test_generate_stores_the_codes_and_never_serves_them(quiz, flags, keyed):
    from services.encryption import decrypt_json_column

    factory, captured = _generate_factory()
    with (
        patch_quiz("table", side_effect=with_async_twins(factory)),
        patch("services.quiz.generation.quiz_agent.run", new=AsyncMock(return_value=SimpleNamespace(output=quiz()))),
        patch_quiz("require_admin"),
    ):
        r = _post_generate({"include_answer_key": keyed})
    assert r.status_code == 200, r.text
    stored = decrypt_json_column(captured["payload"]["questions_json"])
    assert [q["lint_flags"] for q in stored] == [flags]
    served = r.json()["questions"][0]
    assert "lint_flags" not in served
    assert any(o.get("correct") for o in served["options"]) is keyed


def test_assembly_relints_a_reserved_question():
    """G5 re-serves stored questions verbatim; the assembly lints every
    question of the new attempt, so a re-served item carries the current
    linter's answer, never its source attempt's."""
    from services.quiz.generation import _lint_questions

    stale = _flagged(CORRECT_LONGEST, lint_flags=[])
    clean = _flagged(None, qid=2, lint_flags=[NEGATIVE_STEM])
    assert [q["lint_flags"] for q in _lint_questions([stale, clean])] == [[CORRECT_LONGEST], []]
