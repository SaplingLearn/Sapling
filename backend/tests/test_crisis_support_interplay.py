"""The crisis-support path beside the wave-2 learning-loop changes
(docs/safety/crisis-support.md).

A crisis message is screened before anything else a route does. On the merged
base, that order holds against two later changes:

- A125's integrity guard on the notes actions. The crisis screen runs first, so
  a student in crisis gets the card, never an integrity refusal, and no read of
  their posed items is made. The case is one note that both states a crisis and
  quotes an open check.
- A121's turn template. A crisis session start gets the card, never the
  probe-phase template opener, and stashes no session. A crisis chat turn runs
  no activation trial and poses no check.
- A128's embeddings breaker. With it open, a crisis turn still gets the card,
  and no retrieval is attempted (no materials note, no trial call).

Each case is paired with its control: the same request without the crisis
reaches the A125 guard, the A121 template or the activation trial. No model
runs: every agent is a stub or refuses.
"""

from __future__ import annotations

import copy
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from learning import params
from learning.turn_shape import LOOP_PROBE_OPENER
from main import app
from services import integrity_guard
from services.integrity_guard import REFUSED_DETAIL, REFUSED_REPLY
from tests import test_learn_loop_routes as _routes
from tests.test_crisis_support_routes import CRISIS
from tests.test_learn_loop_routes import ITEM, _opener_patches, _plan_state, _sse_events
from tests.test_learning_outside_integrity import posed, records  # noqa: F401  (fixtures)
from tests.test_learning_turn_template import CHAT, _chat
from tests.test_notes_routes import fake_get_note

gate_on, no_rate_limit, seams = _routes.gate_on, _routes.no_rate_limit, _routes.seams

client = TestClient(app)


@pytest.fixture
def crisis_flag(monkeypatch):
    def _set(variant: str) -> None:
        monkeypatch.setenv("SAPLING_FLAG_CRISIS_SUPPORT", variant)

    _set("on")
    return _set


# ── A125: the notes actions screen for crisis before the integrity guard ─────


NOTE_ACTIONS = {
    "chat": {"user_id": "u1", "message": "Explain my note please."},
    "summarize": {"user_id": "u1"},
    "extract-concepts": {"user_id": "u1"},
}


def _note_action(action: str, body: str, guard: MagicMock):
    """POST a notes agent action over a note holding `body`. Every agent
    refuses to run, and the guard's opening is spied on (it still runs)."""
    refuse = AsyncMock(side_effect=AssertionError("a model ran"))
    with (
        patch("routes.notes.get_note", side_effect=fake_get_note(body=body)),
        patch("routes.notes.offering_course_id", return_value="c1"),
        patch("routes.notes.note_chat_agent.run", refuse),
        patch("routes.notes.note_summary_agent.run", refuse),
        patch("routes.notes.note_concepts_agent.run", refuse),
        patch("services.integrity_guard.open_guard", guard),
    ):
        return client.post(f"/api/notes/n1/{action}", json=NOTE_ACTIONS[action])


@pytest.mark.parametrize("action", sorted(NOTE_ACTIONS))
def test_a_note_in_crisis_gets_the_card_before_the_integrity_guard(
    action, crisis_flag, posed, records  # noqa: F811  (fixtures)
):
    """The note states a crisis AND quotes the student's open check (A125
    would refuse it). The card wins: the guard never opens, the posed items
    are never read, and no help row or integrity event is written."""
    note = f"{CRISIS}\nTo ask the AI: {ITEM.prompt}"
    guard = MagicMock(side_effect=integrity_guard.open_guard)
    r = _note_action(action, note, guard)
    assert r.status_code == 200, r.text
    assert r.json()["crisis_support"]
    assert r.json().get("integrity") is None
    guard.assert_not_called()
    posed.assert_not_called()
    records.help.assert_not_called()
    records.event.assert_not_called()

    # control: with the crisis path off, the same note meets A125's guard
    crisis_flag("off")
    r = _note_action(action, note, guard)
    guard.assert_called_once()
    records.help.assert_called_once()
    if action == "chat":
        assert r.status_code == 200 and r.json()["reply"] == REFUSED_REPLY
        assert r.json()["integrity"] == "refused"
    else:
        assert r.status_code == 409 and r.json()["detail"] == REFUSED_DETAIL


# ── A121: a crisis start never gets the template opener ──────────────────────


def _start(path: str, topic: str) -> tuple[str, dict]:
    """POST a loop session start; returns (the served reply, the body)."""
    agent = MagicMock()
    agent.run = AsyncMock(side_effect=AssertionError("the opener ran the model"))
    topic_p, offering_p, graph_p = _opener_patches()
    with (
        patch("routes.learn_loop.loop_tutor_agent", agent),
        patch("routes.learn_loop.stream_structured_turn", MagicMock(side_effect=AssertionError)),
        topic_p,
        offering_p,
        graph_p,
    ):
        r = client.post(path, json={"user_id": "u1", "topic": topic})
    assert r.status_code == 200, r.text
    if path.endswith("/stream"):
        body = _sse_events(r.text)[-1]["data"]
        return body["reply"], body
    return r.json()["initial_message"], r.json()


@pytest.mark.parametrize(
    "path", ["/api/learn/loop/start-session", "/api/learn/loop/start-session/stream"]
)
def test_a_crisis_start_gets_the_card_never_the_template_opener(
    path, crisis_flag, gate_on, seams
):
    from routes.learn_loop import PENDING_SESSIONS

    pending = dict(PENDING_SESSIONS)
    reply, body = _start(path, CRISIS)
    assert body["crisis_support"] and body["session_id"] is None
    assert reply != LOOP_PROBE_OPENER and LOOP_PROBE_OPENER not in reply
    assert dict(PENDING_SESSIONS) == pending, "no session was stashed"

    # control: an ordinary topic is served A121's probe-phase template
    reply, body = _start(path, "Hash tables")
    assert reply == LOOP_PROBE_OPENER and "crisis_support" not in body
    PENDING_SESSIONS.pop(body["session_id"])


# ── A121: a crisis chat turn runs no activation trial ────────────────────────


def test_a_crisis_chat_turn_runs_no_activation_trial_and_poses_no_check(
    crisis_flag, gate_on, seams
):
    """A teach turn due to pose a check (A121 decides that by a read-only
    activation trial before the model runs). A crisis message there gets the
    card: no trial, no check, and the loop state is untouched."""
    from routes import learn_loop

    seams.store["doc"] = _plan_state(teach_turns=params.LOOP_TEACH_TURNS_BEFORE_CHECK - 1)
    seams.list_items.return_value = [ITEM]
    before = copy.deepcopy(seams.store["doc"])
    trial = MagicMock(side_effect=learn_loop._activate_next_item)
    with patch("routes.learn_loop._activate_next_item", trial):
        r = client.post("/api/learn/loop/chat", json={**CHAT, "message": CRISIS})
        assert r.status_code == 200, r.text
        assert r.json()["crisis_support"] and not r.json().get("check")
        trial.assert_not_called()
        assert seams.store["doc"] == before
        seams.save_msg.assert_not_called()

        # control: the same turn with an ordinary message runs the trial and poses it
        body, _ = _chat()
    assert trial.called
    assert body["check"]["question_hash"] == ITEM.question_hash


# ── A128: the embeddings breaker is open ─────────────────────────────────────


def test_with_the_breaker_open_a_crisis_turn_gets_the_card_and_retrieves_nothing(
    crisis_flag, gate_on, seams
):
    """Spec §13 A128's embeddings breaker is open, so a turn's retrieval would
    fail and the turn would carry the materials note. A crisis message gets
    the card and nothing else: no context assembly, so no retrieval is even
    attempted, no note, and the breaker is left as it was (no trial call)."""
    from services import rag_service

    seams.store["doc"] = _plan_state(teach_turns=0)  # a teach turn: the model runs
    for _ in range(rag_service.EMBED_BREAKER_FAILURES):
        rag_service._BREAKER.failed(RuntimeError("embeddings down"))
    assert rag_service.embedding_blocked()
    retrieval = MagicMock(side_effect=AssertionError("a retrieval ran on a crisis turn"))
    with patch("routes.learn_loop.retrieve_chunks_detailed", retrieval):
        r = client.post("/api/learn/loop/chat", json={**CHAT, "message": CRISIS})
        assert r.status_code == 200, r.text
        assert r.json()["crisis_support"] and "materials_unavailable" not in r.json()
        seams.blocks.assert_not_called()  # the context assembly, where retrieval runs
        retrieval.assert_not_called()
        assert rag_service.embedding_breaker_state() == "open"

        # control: an ordinary message on the same session assembles the context
        _chat()
    seams.blocks.assert_called_once()
