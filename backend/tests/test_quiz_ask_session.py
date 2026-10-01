"""PKG-14 final fix round (spec §13 A99): the quiz "Ask about this" session.

The E2E cycle found the launch blocker: with the loop on, the panel's
start-session opened a session in `probe`, and its follow-up chat 409'd
("finish the probe first"). And asking the tutor about the CURRENT quiz
question, then answering it, would have earned unassisted quiz evidence —
laundering, which A93's help ledger exists to stop.

A quiz-ask session (StartSessionBody.origin = "quiz_ask" + the attempt id and
question index) resolves the question's identity from the attempt row the
student owns, records a help row at RUNG_NO_CREDIT_MIN for its question_hash
BEFORE any tutor text exists, and — on the loop path — starts in `teach` on the
quiz's concept node. The quiz submit's floor is pinned in
tests/test_quiz_evidence_only.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from learning import params
from tests import test_learn_loop_routes as _routes
from tests.agent_run_fakes import run_result
from tests.test_learn_loop_routes import client

gate_on, no_rate_limit, seams = _routes.gate_on, _routes.no_rate_limit, _routes.seams

QH = "quiz-qh-1"
QUESTIONS = [
    {"id": 1, "question": "Q1?", "options": [{"label": "A", "text": "a"}], "question_hash": QH},
    {"id": 2, "question": "Q2?", "options": [{"label": "A", "text": "b"}], "question_hash": "quiz-qh-2"},
]
ASK = {"origin": "quiz_ask", "quiz_attempt_id": "att-1", "quiz_question_index": 0}


def _tables(*, owner="u1", node_course="c-node", questions=QUESTIONS, nodes=True):
    def factory(name):
        m = MagicMock()
        if name == "quiz_attempts":
            m.select.return_value = [
                {"user_id": owner, "concept_node_id": "node-1", "questions_json": questions}
            ]
        elif name == "graph_nodes":
            m.select.return_value = [{"id": "node-1", "course_id": node_course}] if nodes else []
        else:
            m.select.return_value = []
        return m

    return factory


# ── the body ─────────────────────────────────────────────────────────────────


def test_a_quiz_ask_body_must_name_its_question():
    from pydantic import ValidationError

    from models import StartSessionBody

    with pytest.raises(ValidationError):
        StartSessionBody(user_id="u1", topic="Recursion", origin="quiz_ask")
    with pytest.raises(ValidationError):
        StartSessionBody(user_id="u1", origin="quiz_ask", quiz_attempt_id="a", quiz_question_index=-1)
    with pytest.raises(ValidationError):
        StartSessionBody(user_id="u1", origin="anything_else")
    body = StartSessionBody(user_id="u1", **ASK)
    assert (body.origin, body.quiz_attempt_id, body.quiz_question_index) == ("quiz_ask", "att-1", 0)
    assert StartSessionBody(user_id="u1").origin is None  # every other session is unchanged


# ── resolution: the server's own question_hash, from the student's own attempt ──


def test_the_question_is_resolved_from_the_owned_attempt_row():
    from services.quiz_ask import resolve_quiz_ask

    with patch("services.quiz_ask.table", side_effect=_tables()):
        target = resolve_quiz_ask("u1", "att-1", 0)
    assert (target.question_hash, target.node_id, target.course_id) == (QH, "node-1", "c-node")


def test_a_question_without_a_stored_hash_gets_the_recomputed_identity():
    from services.quiz_ask import resolve_quiz_ask
    from services.quiz_identity import wire_question_hash

    q = {"id": 1, "question": "What is X?", "options": [{"label": "A", "text": "x"}, {"label": "B", "text": "y"}]}
    with patch("services.quiz_ask.table", side_effect=_tables(questions=[q])):
        target = resolve_quiz_ask("u1", "att-1", 0)
    assert target.question_hash == wire_question_hash(q) and target.question_hash


@pytest.mark.parametrize(
    "kwargs, index",
    [
        ({"owner": "someone-else"}, 0),  # another student's attempt: not found, never revealed
        ({}, 2),  # no such question
        ({"questions": [{"id": 1}]}, 0),  # a question with no identity
        ({"nodes": False}, 0),  # the concept node is not the student's
    ],
)
def test_an_unresolvable_question_is_a_404(kwargs, index):
    from services.quiz_ask import resolve_quiz_ask

    with patch("services.quiz_ask.table", side_effect=_tables(**kwargs)):
        with pytest.raises(HTTPException) as exc:
            resolve_quiz_ask("u1", "att-1", index)
    assert exc.value.status_code == 404


def test_open_quiz_ask_records_the_help_row_at_the_reveal_rung():
    from models import StartSessionBody
    from services.quiz_ask import QUIZ_ASK_HELP_RUNG, open_quiz_ask

    assert QUIZ_ASK_HELP_RUNG == params.RUNG_NO_CREDIT_MIN
    with (
        patch("services.quiz_ask.table", side_effect=_tables()),
        patch("services.quiz_ask.record_help") as record,
    ):
        target = open_quiz_ask(StartSessionBody(user_id="u1", **ASK), session_id="s-9")
    record.assert_called_once_with("u1", QH, params.RUNG_NO_CREDIT_MIN, source="quiz", session_id="s-9")
    assert target.question_hash == QH


def test_open_quiz_ask_is_a_no_op_for_every_other_session():
    from models import StartSessionBody
    from services.quiz_ask import open_quiz_ask

    with patch("services.quiz_ask.table") as tbl, patch("services.quiz_ask.record_help") as record:
        assert open_quiz_ask(StartSessionBody(user_id="u1", topic="Recursion"), session_id="s") is None
    tbl.assert_not_called()
    record.assert_not_called()


def test_a_failed_help_write_refuses_the_session():
    from models import StartSessionBody
    from services.quiz_ask import open_quiz_ask

    with (
        patch("services.quiz_ask.table", side_effect=_tables()),
        patch("services.quiz_ask.record_help", side_effect=RuntimeError("down")),
    ):
        with pytest.raises(HTTPException) as exc:
            open_quiz_ask(StartSessionBody(user_id="u1", **ASK), session_id="s")
    assert exc.value.status_code == 503


def test_the_help_ledger_names_the_quiz_source():
    from learning.help_ledger import SOURCES
    from services.quiz_ask import QUIZ_ASK_SOURCE

    assert QUIZ_ASK_SOURCE in SOURCES


# ── the loop path: teach on the quiz's concept, no probe, help recorded first ──


def _opener(path: str, *, agent=None, stream=None, record=None):
    topic_p, offering_p, graph_p = _routes._opener_patches()
    patches = [
        topic_p,
        offering_p,
        graph_p,
        patch("services.quiz_ask.table", side_effect=_tables()),
        patch("services.quiz_ask.record_help", **({"side_effect": record} if record else {})),
    ]
    if agent is not None:
        patches += [
            patch("routes.learn_loop.loop_tutor_agent", agent),
            patch("routes.learn_loop.record_agent_usage", side_effect=lambda r, **k: r),
        ]
    if stream is not None:
        patches.append(patch("routes.learn_loop.stream_structured_turn", stream))
    from contextlib import ExitStack

    with ExitStack() as stack:
        mocks = [stack.enter_context(p) for p in patches]
        r = client.post(path, json={"user_id": "u1", "topic": "Recursion", **ASK})
        return r, mocks[4]


def test_the_loop_quiz_ask_session_starts_in_teach_on_the_quiz_concept(gate_on, seams):
    from routes.learn_loop import PENDING_SESSIONS, quiz_ask_state

    order: list = []
    agent, seen = _routes._json_agent("Key idea: the base case. Which input stops it?")
    real_run = agent.run

    async def run(*a, **k):
        order.append("model")
        return await real_run(*a, **k)

    agent.run = run
    r, record = _opener(
        "/api/learn/loop/start-session", agent=agent, record=lambda *a, **k: order.append("help")
    )
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]
    assert order == ["help", "model"]  # recorded before any tutor text exists
    pending = PENDING_SESSIONS.pop(sid)
    assert pending["loop_state"] == quiz_ask_state("node-1")
    assert pending["loop_state"]["phase"] == "teach" and pending["loop_state"]["concept"] == "node-1"
    assert pending["course_id"] == "c-node"  # the quiz node's course, not the topic's guess
    # the opener's band is the quiz concept's (node-1, p_known 0.5), not the BKT prior's
    assert seams.ai_budget.check.call_args.args[2] == "develop"
    assert "node-1" in [c.args[1][0] for c in seams.read_states.call_args_list if c.args[1]]


def test_the_loop_quiz_ask_stream_records_help_before_the_first_token(gate_on, seams):
    from routes.learn_loop import PENDING_SESSIONS

    order: list = []
    fake = _routes._fake_stream("Key idea: the base case. Ready?")

    async def stream(**kw):
        order.append("stream")
        async for ev in fake(**kw):
            yield ev

    r, _ = _opener(
        "/api/learn/loop/start-session/stream", stream=stream, record=lambda *a, **k: order.append("help")
    )
    evs = _routes._sse_events(r.text)
    done = evs[-1]["data"]
    assert order == ["help", "stream"]
    assert PENDING_SESSIONS.pop(done["session_id"])["loop_state"]["phase"] == "teach"


def test_a_failed_help_write_is_a_503_and_no_model_runs(gate_on, seams):
    agent = MagicMock()
    agent.run = AsyncMock(side_effect=AssertionError("the model ran"))

    def boom(*a, **k):
        raise RuntimeError("ledger down")

    r, _ = _opener("/api/learn/loop/start-session", agent=agent, record=boom)
    assert r.status_code == 503
    r, _ = _opener("/api/learn/loop/start-session/stream", stream=MagicMock(side_effect=AssertionError), record=boom)
    assert r.status_code == 503


def test_a_plain_loop_session_still_probes_first(gate_on, seams):
    from routes.learn_loop import PENDING_SESSIONS

    agent, _ = _routes._json_agent("Welcome.")
    topic_p, offering_p, graph_p = _routes._opener_patches()
    with (
        patch("routes.learn_loop.loop_tutor_agent", agent),
        patch("routes.learn_loop.record_agent_usage", side_effect=lambda r, **k: r),
        patch("services.quiz_ask.record_help") as record,
        topic_p,
        offering_p,
        graph_p,
    ):
        r = client.post("/api/learn/loop/start-session", json={"user_id": "u1", "topic": "Recursion"})
    assert r.status_code == 200
    assert "loop_state" not in PENDING_SESSIONS.pop(r.json()["session_id"])
    record.assert_not_called()


def test_the_materialised_quiz_ask_row_carries_its_teach_doc_so_chat_is_open():
    """The 409 the E2E cycle hit: the follow-up chat's _teaching_open read a
    document with no phase (probe). The pending loop_state is inserted with the
    row, and a teach document passes the teaching check."""
    from routes.learn import PENDING_SESSIONS, _consume_pending
    from routes.learn_loop import _require_teaching, quiz_ask_state

    PENDING_SESSIONS["s-q"] = {
        "user_id": "u1",
        "mode": "socratic",
        "topic": "Recursion",
        "offering_id": "off-1",
        "assistant_reply": "Hi.",
        "graph_update": {},
        "loop": True,
        "loop_state": quiz_ask_state("node-1"),
    }
    sessions = MagicMock()
    with (
        patch("routes.learn.table", side_effect=lambda n: sessions if n == "sessions" else MagicMock()),
        patch("routes.learn.save_message"),
        patch("routes.learn.events_service"),
    ):
        _consume_pending("s-q", "u1")
    row = sessions.insert.call_args.args[0]
    assert row["loop_state"] == quiz_ask_state("node-1")
    _require_teaching(row["loop_state"])  # no 409
    with pytest.raises(HTTPException) as exc:
        _require_teaching({})  # what the row used to carry: the probe
    assert exc.value.status_code == 409


# ── the kill-switch path: the legacy tutor, the same help row ─────────────────


@pytest.mark.kill_switch
@pytest.mark.parametrize("path", ["/api/learn/start-session", "/api/learn/start-session/stream"])
def test_the_kill_switch_quiz_ask_records_the_same_help_row(path):
    from routes.learn import PENDING_SESSIONS

    agent = MagicMock()
    agent.run = AsyncMock(return_value=run_result("Here is why."))
    tables: dict = {}

    def factory(name):
        tables.setdefault(name, MagicMock(select=MagicMock(return_value=[])))
        return tables[name]

    with (
        patch("routes.learn.table", side_effect=factory),
        patch("routes.learn.agent_for_mode", return_value=agent),
        patch("routes.learn._get_course_id_for_topic", return_value="c1"),
        patch("routes.learn.resolve_offering", return_value="off-1"),
        patch("routes.learn.get_graph", return_value={"nodes": [], "edges": []}),
        patch("services.quiz_ask.table", side_effect=_tables(owner="user_andres")),
        patch("services.quiz_ask.record_help") as record,
        patch("routes.learn._kill_switch_budget"),
    ):
        r = client.post(path, json={"user_id": "user_andres", "topic": "Recursion", **ASK})
    assert r.status_code == 200, r.text
    record.assert_called_once()
    args, kwargs = record.call_args
    assert args[:3] == ("user_andres", QH, params.RUNG_NO_CREDIT_MIN) and kwargs["source"] == "quiz"
    assert kwargs["session_id"]
    PENDING_SESSIONS.clear()


@pytest.mark.kill_switch
def test_a_kill_switch_quiz_ask_whose_help_write_fails_runs_no_model():
    agent = MagicMock()
    agent.run = AsyncMock(side_effect=AssertionError("the model ran"))
    with (
        patch("routes.learn.agent_for_mode", return_value=agent),
        patch("services.quiz_ask.table", side_effect=_tables(owner="user_andres")),
        patch("services.quiz_ask.record_help", side_effect=RuntimeError("down")),
        patch("routes.learn._kill_switch_budget"),
    ):
        r = client.post(
            "/api/learn/start-session", json={"user_id": "user_andres", "topic": "Recursion", **ASK}
        )
    assert r.status_code == 503


def test_the_e2e_mirror_of_the_help_rung_is_pinned():
    """frontend/e2e/support/quiz.ts asserts the quiz-ask help row's rung on the
    database; its constant is this module's."""
    import re
    from pathlib import Path

    from services.quiz_ask import QUIZ_ASK_HELP_RUNG

    src = (Path(__file__).resolve().parents[2] / "frontend/e2e/support/quiz.ts").read_text()
    (found,) = re.findall(r"export const QUIZ_ASK_HELP_RUNG = (\d+);", src)
    assert int(found) == QUIZ_ASK_HELP_RUNG


# ── PKG-14/15 review m2 (spec §13 A106): the course is the quiz node's, or none ──


def test_a_quiz_node_with_no_course_is_a_422_and_records_no_help():
    from models import StartSessionBody
    from services.quiz_ask import open_quiz_ask, resolve_quiz_ask

    with patch("services.quiz_ask.table", side_effect=_tables(node_course=None)):
        with pytest.raises(HTTPException) as exc:
            resolve_quiz_ask("u1", "att-1", 0)
    assert exc.value.status_code == 422
    with (
        patch("services.quiz_ask.table", side_effect=_tables(node_course=None)),
        patch("services.quiz_ask.record_help") as record,
    ):
        with pytest.raises(HTTPException) as exc:
            open_quiz_ask(StartSessionBody(user_id="u1", course_id="c-client", **ASK), session_id="s")
    assert exc.value.status_code == 422
    record.assert_not_called()


def test_the_loop_opener_never_falls_back_to_the_clients_course(gate_on, seams):
    agent = MagicMock()
    agent.run = AsyncMock(side_effect=AssertionError("the model ran"))
    topic_p, offering_p, graph_p = _routes._opener_patches()
    with (
        topic_p,
        offering_p,
        graph_p,
        patch("routes.learn_loop.loop_tutor_agent", agent),
        patch("services.quiz_ask.table", side_effect=_tables(node_course=None)),
        patch("services.quiz_ask.record_help") as record,
    ):
        r = client.post(
            "/api/learn/loop/start-session",
            json={"user_id": "u1", "topic": "Recursion", "course_id": "c-client", **ASK},
        )
    assert r.status_code == 422
    record.assert_not_called()


@pytest.mark.kill_switch
@pytest.mark.parametrize("path", ["/api/learn/start-session", "/api/learn/start-session/stream"])
def test_the_kill_switch_quiz_ask_runs_on_the_quiz_nodes_course(path):
    from routes.learn import PENDING_SESSIONS

    agent = MagicMock()
    agent.run = AsyncMock(return_value=run_result("Here is why."))

    def factory(name):
        return MagicMock(select=MagicMock(return_value=[]))

    with (
        patch("routes.learn.table", side_effect=factory),
        patch("routes.learn.agent_for_mode", return_value=agent),
        patch("routes.learn._get_course_id_for_topic", return_value="c-topic"),
        patch("routes.learn.resolve_offering", return_value="off-1") as offering,
        patch("routes.learn.get_graph", return_value={"nodes": [], "edges": []}),
        patch("services.quiz_ask.table", side_effect=_tables(owner="user_andres")),
        patch("services.quiz_ask.record_help"),
        patch("routes.learn._kill_switch_budget"),
    ):
        r = client.post(
            path,
            json={"user_id": "user_andres", "topic": "Recursion", "course_id": "c-client", **ASK},
        )
    assert r.status_code == 200, r.text
    assert {c.args[0] for c in offering.call_args_list} == {"c-node"}
    PENDING_SESSIONS.clear()


def test_quiz_ask_session_ids_reads_the_origin_marker():
    from services.quiz_ask import quiz_ask_session_ids

    handle = MagicMock()
    handle.select_with_count.return_value = ([{"id": "sq1"}, {"id": "sq2"}, {"id": None}], 3)
    assert quiz_ask_session_ids(handle, to_iso="2026-10-01T00:00:00+00:00") == {"sq1", "sq2"}
    filters = handle.select_with_count.call_args.kwargs["filters"]
    assert filters["loop_state->>origin"] == "eq.quiz_ask"
    assert filters["started_at"] == "lte.2026-10-01T00:00:00+00:00"  # sessions has no created_at
    assert "created_at" not in filters
