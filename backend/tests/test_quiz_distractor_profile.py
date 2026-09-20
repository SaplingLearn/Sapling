"""#554 (Workstream H2, epic #537): mine answers_json into the digest.

`quiz_attempts.answers_json` has recorded which distractor a student picked,
per question, on every submit since the table existed — and nothing ever read
it back. The post-submit digest agent was handed `results`, which carries only
LABELS: "question 3, picked B, the answer was C". Asking a model to name a
misconception from that is asking it to guess; the option TEXT is what makes a
wrong answer mean something.

Joined against questions_json it is a per-concept mistake profile, which is
what this module builds.
"""
from services.quiz_distractors import DIGEST_SCHEMA_VERSION, build_distractor_profile


def _q(qid, stem, concept, options, difficulty="medium"):
    return {
        "id": qid,
        "question": stem,
        "concept_tested": concept,
        "difficulty": difficulty,
        "options": options,
    }


QUESTIONS = [
    _q(1, "What does memoization avoid?", "Recursion", [
        {"label": "A", "text": "Recomputation", "correct": True},
        {"label": "B", "text": "Recursion itself", "correct": False},
    ]),
    _q(2, "What is a base case for?", "Recursion", [
        {"label": "A", "text": "Terminating the recursion", "correct": True},
        {"label": "B", "text": "Speeding up the recursion", "correct": False},
    ]),
]


def test_only_wrong_answers_enter_the_profile():
    """It is a MISTAKE profile. A correct answer says nothing about what the
    student misunderstands, and padding the prompt with correct answers spends
    tokens to say 'no problem here'."""
    results = [
        {"question_id": "1", "selected": "A", "correct": True},
        {"question_id": "2", "selected": "B", "correct": False},
    ]
    profile = build_distractor_profile(QUESTIONS, results)

    assert len(profile) == 1
    assert profile[0]["question"] == "What is a base case for?"


def test_the_profile_carries_option_TEXT_not_labels():
    """The whole point. 'Picked B' is not a misconception; 'thinks a base case
    speeds up recursion' is."""
    results = [{"question_id": "2", "selected": "B", "correct": False}]
    entry = build_distractor_profile(QUESTIONS, results)[0]

    assert entry["chose"] == "Speeding up the recursion"
    assert entry["correct_answer"] == "Terminating the recursion"
    assert entry["concept"] == "Recursion"
    assert "B" not in entry.values()


def test_an_unanswered_question_is_not_a_mistake():
    """Skipped is not wrong. A blank selection carries no information about
    what the student believes, and recording it as a distractor choice would
    invent a misconception out of silence."""
    results = [{"question_id": "2", "selected": "", "correct": False}]
    assert build_distractor_profile(QUESTIONS, results) == []


def test_a_malformed_item_with_no_correct_option_is_skipped():
    """#129's shape: an item with no correct option grades as wrong for
    everyone. Reporting 'the correct answer was <nothing>' would teach the
    digest a misconception that does not exist."""
    broken = [_q(9, "Broken?", "X", [{"label": "A", "text": "a", "correct": False}])]
    results = [{"question_id": "9", "selected": "A", "correct": False}]
    assert build_distractor_profile(broken, results) == []


def test_a_result_with_no_matching_question_is_ignored():
    results = [{"question_id": "404", "selected": "B", "correct": False}]
    assert build_distractor_profile(QUESTIONS, results) == []


def test_the_profile_is_bounded():
    """It rides a prompt. An attempt is capped at 10 questions today, but the
    cap is here so a future longer attempt cannot quietly inflate the digest
    prompt."""
    from services.quiz_distractors import MAX_PROFILE_ENTRIES

    many = [
        _q(i, f"stem {i}", "C", [
            {"label": "A", "text": "right", "correct": True},
            {"label": "B", "text": f"wrong {i}", "correct": False},
        ])
        for i in range(MAX_PROFILE_ENTRIES + 5)
    ]
    results = [
        {"question_id": str(i), "selected": "B", "correct": False}
        for i in range(MAX_PROFILE_ENTRIES + 5)
    ]
    assert len(build_distractor_profile(many, results)) == MAX_PROFILE_ENTRIES


def test_never_raises_on_garbage():
    """It runs inside the post-submit background task, after the attempt is
    already graded and written. A crash here must not be able to cost the
    student their digest."""
    assert build_distractor_profile(None, None) == []
    assert build_distractor_profile([{"nope": 1}], [{"also": 2}]) == []
    assert build_distractor_profile(QUESTIONS, "not-a-list") == []


def test_schema_version_is_declared_and_positive():
    """#554 asks for a version on the digest so the NEXT key drift is caught.
    The last one (the coercer reading `common_errors` while the agent wrote
    `common_mistakes`) went unnoticed until #548."""
    assert isinstance(DIGEST_SCHEMA_VERSION, int)
    assert DIGEST_SCHEMA_VERSION >= 1


def test_the_prompt_template_has_a_slot_for_the_profile():
    """Guards the wiring, not the words: a renamed placeholder would leave the
    profile computed, stringified and dropped on the floor — silently, since
    `str.replace` on a missing token is a no-op."""
    from pathlib import Path

    tpl = (
        Path(__file__).resolve().parents[1] / "prompts/quiz_context_update.txt"
    ).read_text()
    assert "{distractor_profile_json}" in tpl


# ── digest schema version, reader side (#554 review findings 1 and 3) ────────


def test_the_version_is_stamped_by_the_server_not_by_the_model():
    """It must NOT be a field on the agent's output schema.

    The digest prompt feeds the previous context back in under "update your
    notes", so a model that helpfully bumped a field named "version" would
    trip the reader's unknown-shape warning on every later read for that
    (user, concept) — forever, with no real drift. One that lowered it would
    kill the guard just as quietly. So the model never sees the field, and
    `save_quiz_context` stamps it.
    """
    from unittest.mock import patch as _patch

    from agents.quiz_context import QuizContext
    from services import quiz_context_service

    assert "schema_version" not in QuizContext.model_fields

    with _patch.object(quiz_context_service, "table") as t, \
            _patch.object(quiz_context_service, "encrypt_json", side_effect=lambda v: v):
        quiz_context_service.save_quiz_context("u1", "n1", {"notes": "x"})

    written = t.return_value.upsert.call_args[0][0]["context_json"]
    assert written["schema_version"] == DIGEST_SCHEMA_VERSION
    assert written["notes"] == "x"


def test_a_versioned_digest_that_reads_as_nothing_is_flagged(caplog):
    """The drift #554 actually cites: a key RENAME at the SAME version. A
    version comparison cannot see that — it needs someone to remember to bump
    the version in the same commit as the rename, which is the discipline that
    failed in #548. Catch it by outcome instead."""
    from agents.tools.quiz_history import _coerce_summary

    with caplog.at_level("WARNING"):
        out = _coerce_summary(
            {"schema_version": DIGEST_SCHEMA_VERSION, "renamed_key": "content"}
        )

    assert out is None
    assert "renamed out from under this coercer" in caplog.text


def test_a_healthy_digest_is_silent(caplog):
    from agents.tools.quiz_history import _coerce_summary

    with caplog.at_level("WARNING"):
        out = _coerce_summary(
            {"schema_version": DIGEST_SCHEMA_VERSION, "notes": "they confuse base cases"}
        )

    assert out == "they confuse base cases"
    assert caplog.text == ""


def test_an_unversioned_legacy_digest_is_not_a_discrepancy(caplog):
    """Every row written before #554 lacks the field. Warning on those would
    fire on the entire existing corpus."""
    from agents.tools.quiz_history import _coerce_summary

    with caplog.at_level("WARNING"):
        assert _coerce_summary({"unknown": "shape"}) is None
    assert caplog.text == ""
