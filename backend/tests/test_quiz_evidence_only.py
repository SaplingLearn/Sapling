"""PKG-14b: submit_quiz moves mastery only through evidence; the flat delta model is gone (spec §11.2)."""

import inspect
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from learning import params
from learning.bkt import update
from tests.test_quiz_scoring_e import _loop_table, _noop_ctx_agent, client
from test_learning_loop_invariants import LEGACY_MASTERY_SYMBOLS

# The retired symbols are named once, in inv_21's list (spec §8 invariant 21
# greps the literals), and every absence check here reads them from it.
LEGACY_DELTA_KEY, LEGACY_DELTA_CONSTANTS, _ = LEGACY_MASTERY_SYMBOLS

REPO = Path(__file__).resolve().parents[2]


def test_quiz_config_has_no_delta_model():
    import services.quiz_config as qc

    assert [n for n in dir(qc) if n.startswith(LEGACY_DELTA_CONSTANTS)] == []
    assert not hasattr(qc, "mastery_after")


def test_three_mc_corrects_from_prior():
    """spec PKG-14 §Derived expectations: 0.710733 → 0.913664 → 0.978259."""
    p = params.BKT_L0
    seen = []
    for _ in range(3):
        p = update(p, "mc", True, weight=1.0)
        seen.append(round(p, 6))
    assert seen == [0.710733, 0.913664, 0.978259]


def test_frontend_mirror_of_bkt_constants():
    src = (REPO / "frontend/e2e/support/quiz.ts").read_text()
    found = {k: float(v) for k, v in re.findall(r"export const (BKT_L0|BKT_T|MC_G|MC_S) = ([0-9.]+);", src)}
    assert found == {
        "BKT_L0": params.BKT_L0,
        "BKT_T": params.BKT_T,
        "MC_G": params.CHANNELS["mc"]["G"],
        "MC_S": params.CHANNELS["mc"]["S"],
    }
    assert "MASTERY_PER_CORRECT" not in src and "masteryAfter" not in src
    assert "export function bktAfterCorrect(" in src


def test_frontend_mirror_reproduces_the_backend_posterior():
    """The TS function body is the §3.1 correct update + learn step; replay
    its arithmetic here so a drifted formula (not just drifted constants) fails."""
    src = (REPO / "frontend/e2e/support/quiz.ts").read_text()
    body = src[src.index("export function bktAfterCorrect(") :]
    body = body[: body.index("\n}\n")]
    assert "(p * (1 - MC_S)) / (p * (1 - MC_S) + (1 - p) * MC_G)" in body
    assert "post + (1 - post) * BKT_T" in body


def test_quiz_and_flashcards_read_no_gate():
    from routes import flashcards, quiz

    for mod in (quiz, flashcards):
        assert "learning_loop_active" not in inspect.getsource(mod), mod.__name__


def _submit(apply_mock, *, answers):
    with (
        patch("routes.quiz.table", side_effect=_loop_table()),
        patch("routes.quiz.apply_graph_update", new=apply_mock),
        patch("routes.quiz.get_quiz_context", return_value={}),
        patch("routes.quiz.quiz_context_agent.run", new=_noop_ctx_agent()),
        patch("routes.quiz.save_quiz_context"),
        patch("routes.quiz.events_service.log_event") as log_event,
    ):
        r = client.post("/api/quiz/submit", json={"quiz_id": "quiz1", "answers": answers})
    return r, log_event


@pytest.mark.parametrize("flag", [True, False])
def test_submit_is_evidence_only_under_either_flag(monkeypatch, flag):
    """No gate: the kill switch does not bring the flat delta back (spec §11.6)."""
    import config

    monkeypatch.setattr(config, "LEARNING_LOOP_ENABLED", flag)
    apply_mock = MagicMock(return_value=[{"before": 0.5, "after": 0.58}, {"before": 0.58, "after": 0.51}])
    r, _ = _submit(
        apply_mock,
        answers=[{"question_id": 1, "selected_label": "A"}, {"question_id": 2, "selected_label": "C"}],
    )
    assert r.status_code == 200, r.text
    apply_mock.assert_called_once()
    assert set(apply_mock.call_args[0][1]) == {"evidence"}


def test_submit_reports_p_delta_not_the_legacy_key():
    apply_mock = MagicMock(return_value=[{"before": 0.5, "after": 0.58}, {"before": 0.58, "after": 0.51}])
    r, log_event = _submit(
        apply_mock,
        answers=[{"question_id": 1, "selected_label": "A"}, {"question_id": 2, "selected_label": "C"}],
    )
    body = r.json()
    assert "p_delta" in body and LEGACY_DELTA_KEY not in body
    assert body["mastery_after"] == pytest.approx(body["mastery_before"] + body["p_delta"])
    assert body["p_delta"] == pytest.approx(0.01)
    (completed,) = [c for c in log_event.call_args_list if c.args and c.args[0] == "quiz.completed"]
    payload = completed.kwargs["payload"]
    assert LEGACY_DELTA_KEY not in payload
    assert payload["p_delta"] == pytest.approx(0.01)


# ── owner decision 2 (spec §13 A94): quiz farming ─────────────────────────────


def _farm_tables(counted_today: list[str], *, fail=False, calls=None):
    """_loop_table's world plus a node_mastery_events read (today's evidence)."""
    base = _loop_table()

    def factory(name):
        if name == "node_mastery_events":
            h = MagicMock()

            def select(columns="*", filters=None, **kw):
                if calls is not None:
                    calls.append((columns, dict(filters or {})))
                if fail:
                    raise RuntimeError("down")
                return [{"question_hash": q, "graph_nodes": {"user_id": "user_andres"}} for q in counted_today]

            h.select.side_effect = select
            return h
        return base(name)

    return factory


def _submit_with(factory, apply_mock):
    with (
        patch("routes.quiz.table", side_effect=factory),
        patch("routes.quiz.apply_graph_update", new=apply_mock),
        patch("routes.quiz.get_quiz_context", return_value={}),
        patch("routes.quiz.quiz_context_agent.run", new=_noop_ctx_agent()),
        patch("routes.quiz.save_quiz_context"),
        patch("routes.quiz.events_service.log_event"),
    ):
        return client.post(
            "/api/quiz/submit",
            json={
                "quiz_id": "quiz1",
                "answers": [{"question_id": 1, "selected_label": "A"}, {"question_id": 2, "selected_label": "C"}],
            },
        )


def test_a_question_already_counted_today_writes_no_second_evidence():
    from tests.test_quiz_scoring_e import LOOP_QUESTIONS

    counted = LOOP_QUESTIONS[0]["question_hash"]
    calls: list = []
    apply_mock = MagicMock(return_value=[{"before": 0.5, "after": 0.45}])
    r = _submit_with(_farm_tables([counted], calls=calls), apply_mock)
    assert r.status_code == 200, r.text
    (ev,) = apply_mock.call_args[0][1]["evidence"]
    assert ev["question_hash"] != counted  # only the not-yet-counted question
    (columns, filters), = calls
    assert "graph_nodes!inner(user_id)" in columns
    assert filters["graph_nodes.user_id"] == "eq.user_andres"
    assert filters["event_type"] == "eq.evidence" and filters["created_at"].startswith("gte.")


def test_every_question_counted_today_moves_nothing():
    from tests.test_quiz_scoring_e import LOOP_QUESTIONS
    from services.quiz_identity import question_hash

    hashes = [
        LOOP_QUESTIONS[0]["question_hash"],
        question_hash("What is a function?", ["a loop", "a reusable block"]),
    ]
    apply_mock = MagicMock(return_value=[])
    r = _submit_with(_farm_tables(hashes), apply_mock)
    assert r.status_code == 200, r.text
    apply_mock.assert_not_called()
    body = r.json()
    assert body["mastery_after"] == body["mastery_before"] and body["p_delta"] == 0


def test_an_unreadable_daily_count_fails_closed():
    apply_mock = MagicMock(return_value=[])
    r = _submit_with(_farm_tables([], fail=True), apply_mock)
    assert r.status_code == 200, r.text
    apply_mock.assert_not_called()


def test_hashless_questions_count_once_per_attempt():
    from routes.quiz import _farm_guard

    evs = [
        {"question_hash": None, "node_id": "n", "correct": True},
        {"question_hash": None, "node_id": "n", "correct": True},
        {"question_hash": "h1", "node_id": "n", "correct": True},
        {"question_hash": "h1", "node_id": "n", "correct": False},  # the same item twice
    ]
    with patch("routes.quiz.table", side_effect=_farm_tables([])):
        kept = _farm_guard("user_andres", evs)
    assert [e["question_hash"] for e in kept] == [None, "h1"]


def test_students_cannot_ask_for_the_answer_key(monkeypatch):
    """Owner decision 2: include_answer_key=true is admin-only (403 before any
    generation); the shipped client always sends false."""
    import services.auth_guard as ag
    import routes.quiz as quiz

    monkeypatch.setattr(quiz, "require_admin", ag._real_require_admin)
    monkeypatch.setattr(ag, "table", lambda name: MagicMock(select=MagicMock(return_value=[])))
    run = MagicMock(side_effect=AssertionError("generation ran"))
    with patch("routes.quiz.quiz_agent.run", new=run):
        r = client.post(
            "/api/quiz/generate",
            json={"user_id": "user_andres", "concept_node_id": "node1", "include_answer_key": True},
        )
    assert r.status_code == 403
    run.assert_not_called()
