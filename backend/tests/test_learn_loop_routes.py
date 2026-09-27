"""PKG-07: /api/learn/loop/* routes, the turn pipeline, the explicit-submission
check route, deterministic turns, and delegation from the legacy learn routes.

Everything below the model is patched at the `routes.learn_loop.<name>` seam;
no DB, no LLM. The pure PKG-06 layer (gates, ladder, policy, leak) runs for
real — policy functions are wrapped so a test can read their arguments or pin
a return value. The loop-state store is a small in-memory fake that round-trips
through PKG-06's typed `LoopState`, so every save is validated exactly as the
real store validates it.
"""

from __future__ import annotations

import json
from contextlib import ExitStack
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from agents import LOOP_LIMITS
from learning import leak, policy
from learning.checks import CheckItem, RubricItem, WrongReason
from learning.ladder import Rung
from learning.learner_state import LearnerState
from learning.params import (
    LOOP_HISTORY_MAX_MESSAGES,
    LOOP_MAX_VISIBLE_TOKENS,
    LOOP_PRO_THINKING_BUDGET,
)
from learning.policy import LoopState
from main import app
from services import ai_budget
from services.agent_events import SaplingEvent
from tests.agent_run_fakes import run_result

client = TestClient(app)

T0 = 1_790_000_000.0  # when the active item was first shown (float seconds, PKG-06's store)
NOW = T0 + 600.0  # the route clock in these tests: ten minutes of independent work

ITEM = CheckItem(
    id="item-1",
    course_id="c1",
    concept_key="recursion",
    format="free",
    difficulty=2,
    prompt="What stops factorial(0) from recursing?",
    reference_answer="The base case returns 1 when n equals 0 without a recursive call.",
    final_answer="The base case returns 1",  # A34 (PKG-04's structured answer)
    canonical_answer=None,
    rubric=[RubricItem(id="r1", text="names the base case"), RubricItem(id="r2", text="returns 1")],
    common_wrong=[WrongReason(key="no_base", text="no base case")],
    source_chunk_ids=["ch-1", "ch-2", "ch-3"],
    stepwise=False,
    question_hash="qh-1",
)
RESET = datetime(2026, 9, 27, tzinfo=timezone.utc)
RESET_ISO = RESET.isoformat()
NORMAL = SimpleNamespace(level="normal", reset_at=None, pause_novice=False, tier_ceiling="deep", scope=None)
SOFT = SimpleNamespace(
    level="soft", reset_at=RESET, pause_novice=False, tier_ceiling="standard", scope="daily_usd"
)
HARD = SimpleNamespace(level="hard", reset_at=RESET, pause_novice=True, tier_ceiling="none", scope="daily_usd")
CORRECT = SimpleNamespace(
    correct=True,
    confidence=0.9,
    unavailable=False,
    grader_backend="gemini",
    feedback_hint="",
    matched_wrong_key=None,
    wrong_key=None,
    evidence={"node_id": "node-1", "channel": "free_response", "correct": True, "assisted": False},
)
WRONG = SimpleNamespace(
    **{
        **vars(CORRECT),
        "correct": False,
        "evidence": {"node_id": "node-1", "channel": "free_response", "correct": False, "assisted": False},
    }
)
UNAVAILABLE = SimpleNamespace(**{**vars(CORRECT), "correct": None, "unavailable": True, "evidence": None})
# Tasks 6-7b extend these as their endpoints land.
MODEL_ROUTES = ["/chat", "/chat/stream", "/check/answer", "/check/answer/stream"]
NO_MODEL_ROUTES = ["/status"]


def _sse_events(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        if line.startswith("data:"):
            out.append(json.loads(line.split("data:", 1)[1]))
    return out


def _step(**fields) -> dict:
    step = {
        "rung": 1,
        "attempts": 0,
        "first_shown_at": T0,
        "last_rung_at": None,
        "attempted_at": [],
        "showed_work": False,
        "exam_mode": False,
        "check_item_id": "item-1",
        "node_id": "node-1",
        "taught": True,
        "feedback_given": False,
    }
    step.update(fields)
    return step


def _state(**step_fields) -> dict:
    """A session with qh-1 active (PKG-06's document: `current` + `steps`)."""
    return {"current": "qh-1", "steps": {"qh-1": _step(**step_fields)}}


def _graded(verdict: str, **over) -> dict:
    """qh-1 graded by _grade_submission, its feedback turn not served yet."""
    correct = verdict == "correct"
    return _state(
        graded_at=NOW - 5,
        graded=1,
        wrong=0 if correct else 1,
        last_correct=correct,
        last_verdict=verdict,
        first_attempt_correct=correct,
        max_rung=1,
        assisted=True,
        channel="free_response",
        confidence=0.9,
        grader_backend="gemini",
        fsrs_rating=2 if correct else 1,
        p_before=0.5,
        **over,
    )


def _json_agent(reply: str = "Key idea: the base case. Which input stops it?"):
    agent, seen = MagicMock(), {}

    async def _run(msg, **kw):
        seen["msg"], seen["kw"] = msg, kw
        return run_result(reply)

    agent.run = _run
    return agent, seen


@pytest.fixture(autouse=True)
def no_rate_limit():
    """The A20 dependency reads llm_usage; route tests override it (a dedicated
    test proves which routes declare it)."""
    app.dependency_overrides[ai_budget.enforce_rate_limit] = lambda: None
    yield
    app.dependency_overrides.pop(ai_budget.enforce_rate_limit, None)


@pytest.fixture
def gate_on():
    with patch("routes.learn_loop.learning_loop_active", return_value=True) as g:
        yield g


@pytest.fixture
def seams():
    """Every impure dependency the loop routes touch, patched at the route seam."""
    store = {"doc": _state()}

    def _load(session_id):
        return LoopState.from_json(json.loads(json.dumps(store["doc"])))

    def _save(session_id, state):
        store["doc"] = json.loads(json.dumps(state.to_json()))
        return True

    p_known = {"node-1": 0.5}

    def _read_states(user_id, node_ids, **kw):
        return {
            n: LearnerState(user_id=user_id, node_id=n, p_known=p_known[n], exists=True)
            for n in node_ids
            if n in p_known
        }

    with ExitStack() as stack:

        def p(name, **kw):
            return stack.enter_context(patch(f"routes.learn_loop.{name}", **kw))

        ns = SimpleNamespace(store=store, p_known=p_known)
        ns.load = p("load_loop_state", side_effect=_load)
        ns.save = p("save_loop_state", side_effect=_save)
        ns.scope = p("_session_scope", return_value=("off-1", "c1"))
        ns.item = p("get_check_item", return_value=ITEM)
        ns.list_items = p("list_items", return_value=[])
        ns.node = p("_node_for_item", return_value="node-1")
        ns.prereq = p("_prereq_proficient", return_value=True)
        ns.read_states = p("read_states", side_effect=_read_states)
        ns.model_tier = p("policy.model_tier", wraps=policy.model_tier)
        ns.ceiling = p("policy.ceiling_with_reason", wraps=policy.ceiling_with_reason)
        ns.context_policy = p("policy.context_policy", wraps=policy.context_policy)
        ns.ai_budget = p("ai_budget")
        ns.detect = p("detect_leak", wraps=leak.detect_leak)
        ns.strip = p("strip_leak", side_effect=lambda emitted, ref, **kw: "STRIPPED")
        ns.zpd = p("zpd_events")
        ns.save_msg = p("save_message")
        ns.events = p("events_service")
        ns.consume = p("_consume_pending")
        p("_load_message_history", return_value=[])
        ns.blocks = p("_context_blocks", return_value=["CTX"])
        ns.by_id = p("chunks_for_ids", return_value=[])
        ns.tier_run_kwargs = p(
            "tier_run_kwargs",
            side_effect=lambda tier, *, tool_choice=None: {
                "model": f"MODEL:{tier}",
                "model_settings": {"tool_choice": tool_choice},
            },
        )
        p("_now_s", return_value=NOW)
        ns.grade = p("grade_answer", new_callable=AsyncMock, return_value=CORRECT)
        ns.flush = p("flush_pending", return_value=[{"node_id": "node-1"}])
        ns.ai_budget.check.return_value = NORMAL
        yield ns


# ── Gate + rate limit ─────────────────────────────────────────────────────

_EVERY_ENDPOINT = [
    ("GET", "/api/learn/loop/status?user_id=u1&session_id=s1", None),
    ("POST", "/api/learn/loop/chat", {"session_id": "s1", "user_id": "u1", "message": "hi"}),
    ("POST", "/api/learn/loop/chat/stream", {"session_id": "s1", "user_id": "u1", "message": "hi"}),
    (
        "POST",
        "/api/learn/loop/check/answer",
        {"session_id": "s1", "user_id": "u1", "question_hash": "qh-1", "answer": "n == 0"},
    ),
    (
        "POST",
        "/api/learn/loop/check/answer/stream",
        {"session_id": "s1", "user_id": "u1", "question_hash": "qh-1", "answer": "n == 0"},
    ),
]


@pytest.mark.parametrize("method,path,body", _EVERY_ENDPOINT)
def test_every_loop_endpoint_404s_when_gate_false(method, path, body):
    # The gate's own body tells this 404 from FastAPI's default for an unmounted path.
    with patch("routes.learn_loop.learning_loop_active", return_value=False) as gate, \
         patch("routes.learn_loop._consume_pending") as consume:
        r = client.get(path) if method == "GET" else client.post(path, json=body)
    assert r.status_code == 404
    # spec §7 body; the house error envelope adds its request_id
    assert r.json()["detail"] == "learning loop not enabled"
    gate.assert_called_once_with("u1")
    consume.assert_not_called()  # nothing is materialised for a student the loop is dark for


def _loop_prefix() -> str | None:
    """Where main.py mounts the loop router. fastapi 0.138 keeps an included
    router as one entry in app.routes (no flattened `.path`s; see
    tests/test_auth_test_login.py), so the router's own routes are the seam."""
    from routes import learn_loop

    for r in app.routes:
        ctx = getattr(r, "include_context", None)
        if ctx is not None and ctx.included_router is learn_loop.router:
            return ctx.prefix
    return None


def _declared() -> dict:
    from routes import learn_loop

    return {
        _loop_prefix() + r.path: {d.call for d in r.dependant.dependencies}
        for r in learn_loop.router.routes
    }


def test_router_mounted_under_learn_loop_prefix():
    assert _loop_prefix() == "/api/learn/loop"
    assert {"/api/learn/loop/status", "/api/learn/loop/chat", "/api/learn/loop/chat/stream"} <= set(
        _declared()
    )


def test_rate_limit_dependency_on_model_routes_only():
    declared = _declared()
    assert set(declared) == {"/api/learn/loop" + s for s in (*MODEL_ROUTES, *NO_MODEL_ROUTES)}
    for suffix in MODEL_ROUTES:
        assert ai_budget.enforce_rate_limit in declared["/api/learn/loop" + suffix], suffix
    for suffix in NO_MODEL_ROUTES:
        assert ai_budget.enforce_rate_limit not in declared["/api/learn/loop" + suffix], suffix


def test_rate_limited_model_route_answers_429(gate_on, seams):
    def _limited():
        raise HTTPException(status_code=429, detail="ai budget reached")

    app.dependency_overrides[ai_budget.enforce_rate_limit] = _limited
    r = client.post("/api/learn/loop/chat", json={"session_id": "s1", "user_id": "u1", "message": "hi"})
    assert r.status_code == 429
    seams.ai_budget.check.assert_not_called()


def test_a_session_of_another_user_is_refused(gate_on, seams):
    """HANDOFF-06: the store keys on the session id alone — the route checks
    that the session is the requesting student's before it reads or writes."""
    seams.scope.side_effect = HTTPException(status_code=403, detail="Session user mismatch")
    r = client.post("/api/learn/loop/chat", json={"session_id": "s1", "user_id": "u1", "message": "hi"})
    assert r.status_code == 403
    seams.save.assert_not_called()
    seams.ai_budget.check.assert_not_called()


def test_session_scope_reads_the_owner_and_the_course():
    from routes.learn_loop import _session_scope

    handle = MagicMock()
    handle.select.return_value = [{"user_id": "u1", "offering_id": "off-1"}]
    with patch("routes.learn_loop.table", return_value=handle) as tbl, \
         patch("routes.learn_loop.offering_course_id", return_value="c1"):
        assert _session_scope("s1", "u1") == ("off-1", "c1")
        with pytest.raises(HTTPException) as other:
            _session_scope("s1", "u2")
    assert other.value.status_code == 403
    tbl.assert_called_with("sessions")
    handle.select.return_value = []
    with patch("routes.learn_loop.table", return_value=handle), pytest.raises(HTTPException) as gone:
        _session_scope("s1", "u1")
    assert gone.value.status_code == 404


# ── Pure helpers ──────────────────────────────────────────────────────────


def test_phase_for():
    from routes.learn_loop import _phase_for

    assert _phase_for({}) == "teach"
    assert _phase_for({"current": "q", "steps": {}}) == "teach"
    assert _phase_for({"current": "q", "steps": {"q": {"rung": 0}}}) == "check"
    assert _phase_for({"current": "q", "steps": {"q": {"rung": 0, "graded_at": 1.0}}}) == "feedback"
    assert (
        _phase_for({"current": "q", "steps": {"q": {"rung": 0, "graded_at": 1.0, "feedback_given": True}}})
        == "teach"
    )


def test_ceiling_for_passes_typed_state_only():
    """Invariant 4 at the call site: the policy gets a LearnerView and a
    StepState — typed state, never the message — and the shown-work floor is
    the only thing the message decides (gates.is_genuine_attempt, fed
    has_non_attempt_phrase, HANDOFF-06)."""
    from routes.learn_loop import _ceiling_for, _learner_view, _step_state

    step = _step_state(_state(attempts=1), "qh-1")
    learner = _learner_view(None, band="develop", prereq_proficient=True)
    with patch("routes.learn_loop.policy.ceiling_with_reason", wraps=policy.ceiling_with_reason) as spy:
        ceiling, reason = _ceiling_for(
            step=step, learner=learner, message="here is my work: 3*2", independent_s=50.0
        )
    assert ceiling == Rung.H4 and reason == policy.CeilingReason.DEVELOP  # H3 + 1 failed genuine attempt
    (lv, st), kwargs = spy.call_args
    assert kwargs == {} and isinstance(lv, policy.LearnerView) and isinstance(st, policy.StepState)
    assert lv.band == "develop" and lv.prereq_proficient is True
    assert st.genuine_attempts == 1 and st.showed_work is True and st.exam_mode is False
    assert not any(isinstance(v, str) and "work" in v for v in vars(st).values()), "no message text"
    # a plea is never shown work (has_non_attempt_phrase vetoes it)
    with patch("routes.learn_loop.policy.ceiling_with_reason", wraps=policy.ceiling_with_reason) as spy:
        _ceiling_for(step=step, learner=learner, message="idk man", independent_s=500.0)
    assert spy.call_args.args[1].showed_work is False


def test_ceiling_for_the_profic_floor_needs_genuine_work():
    from routes.learn_loop import _ceiling_for, _learner_view, _step_state

    step = _step_state(_state(), "qh-1")
    learner = _learner_view(None, band="profic", prereq_proficient=True)
    assert _ceiling_for(step=step, learner=learner, message="", independent_s=500.0)[0] == Rung.H1
    shown = _ceiling_for(step=step, learner=learner, message="I tried n = 0 first", independent_s=500.0)
    assert shown == (Rung.H3, policy.CeilingReason.SHOWED_WORK_FLOOR)
    too_fast = _ceiling_for(step=step, learner=learner, message="I tried n = 0 first", independent_s=1.0)
    assert too_fast[0] == Rung.H1  # the independent-time gate (GATE_INDEPENDENT_MIN_S)


def test_failed_on_concept_counts_the_session_across_isomorphs():
    from routes.learn_loop import _failed_on_concept

    state = {
        "current": "a",
        "tutor_requests": 3,
        "steps": {
            "a": {"node_id": "n1", "attempts": 1},
            "b": {"node_id": "n1", "attempts": 1},
            "c": {"node_id": "n2", "attempts": 1},
        },
    }
    assert _failed_on_concept(state, "n1") == 2 and _failed_on_concept(state, None) == 0


def test_load_loop_history_is_bounded():
    from routes.learn_loop import _load_loop_history

    rows = [f"m{i}" for i in range(LOOP_HISTORY_MAX_MESSAGES + 7)]
    with patch("routes.learn_loop._load_message_history", return_value=rows):
        got = _load_loop_history("s1")
    assert got == rows[-LOOP_HISTORY_MAX_MESSAGES:]


def test_loop_state_adapters_round_trip_through_the_typed_store():
    """The route works on PKG-06's JSON document (`LoopState.to_json()`); a save
    re-validates it through `LoopState.from_json`, so a malformed PKG-06 field
    written by the route raises instead of reaching the database."""
    from routes.learn_loop import _load_loop_state, _save_loop_state

    doc = _state(wrong=1, custom=["x"])
    doc["tutor_requests"] = 2
    with patch("routes.learn_loop.load_loop_state", return_value=LoopState.from_json(doc)), \
         patch("routes.learn_loop.save_loop_state", return_value=True) as save:
        got = _load_loop_state("s1")
        assert got["current"] == "qh-1" and got["steps"]["qh-1"]["wrong"] == 1
        assert got["tutor_requests"] == 2 and got["steps"]["qh-1"]["custom"] == ["x"]
        assert _save_loop_state("s1", got) is True
        assert save.call_args.args[1].to_json() == got
        got["steps"]["qh-1"]["rung"] = 9  # off the ladder
        with pytest.raises(ValueError):
            _save_loop_state("s1", got)


def test_context_blocks_follow_the_policy():
    from routes.learn_loop import _context_blocks

    with patch("routes.learn_loop._get_course_info", return_value={"course_code": "CS111"}), \
         patch("routes.learn_loop._get_catalog_chunk", return_value="CATALOG") as cat, \
         patch("routes.learn_loop.retrieve_chunks", return_value=[{"chunk_text": "r"}]) as rag, \
         patch("routes.learn_loop.format_rag_context", return_value="RAG"), \
         patch(
             "routes.learn_loop.chunks_for_ids",
             return_value=[{"id": "ch-1", "course_id": "c1", "chunk_text": "SRC"}],
         ) as by_id, \
         patch("routes.learn_loop.build_graph_context_block", return_value="GRAPH"):
        teach = _context_blocks(
            user_id="u1",
            course_id="c1",
            user_message="hi",
            item=None,
            context=policy.ContextPolicy(3, True, 0, False, "none"),
        )
        assert teach == ["RAG", "GRAPH"]
        assert rag.call_args.kwargs == {"course_id": "CS111", "k": 3, "user_id": "u1"}
        cat.assert_not_called()
        by_id.assert_not_called()
        hint = _context_blocks(
            user_id="u1",
            course_id="c1",
            user_message="hi",
            item=ITEM,
            context=policy.ContextPolicy(0, False, 2, False, "none"),
        )
        assert len(hint) == 1 and "SRC" in hint[0] and "UNTRUSTED" in hint[0].upper()
        assert by_id.call_args.args[0] == ["ch-1", "ch-2"] and by_id.call_args.kwargs == {"user_id": "u1"}
        opener = _context_blocks(
            user_id="u1",
            course_id="c1",
            user_message="hi",
            item=None,
            context=policy.ContextPolicy(5, True, 0, True, "auto"),
        )
        assert opener[0].startswith("COURSE CATALOG INFO (official BU course data):")
        nothing = _context_blocks(
            user_id="u1", course_id="", user_message="hi", item=None,
            context=policy.ContextPolicy(5, True, 0, True, "auto"),
        )
        assert nothing == []  # no course: no catalog, no RAG, no graph block


def test_prepare_loop_run_uses_the_tier_slot_and_loop_limits():
    from agents.loop_tutor import loop_tutor_agent
    from routes.learn_loop import _prepare_loop_run

    with patch("routes.learn_loop._context_blocks", return_value=["CTX"]):
        agent, assembled, run_kwargs, deps = _prepare_loop_run(
            user_id="u1",
            session_id="s1",
            course_id="c1",
            user_message="hi",
            message_history=[],
            request_id="r1",
            prefix="[LOOP PHASE: teach]\nrule",
            state={"x": 1},
            tier="deep",
            item=None,
            context=policy.ContextPolicy(5, True, 0, False, "none"),
        )
    assert agent is loop_tutor_agent
    assert assembled == "[LOOP PHASE: teach]\nrule\n\nCTX\n\n[STUDENT QUESTION]\nhi"
    assert run_kwargs["usage_limits"] is LOOP_LIMITS
    assert run_kwargs["model_settings"]["tool_choice"] == "none"
    assert run_kwargs["model_settings"]["max_tokens"] == LOOP_PRO_THINKING_BUDGET + LOOP_MAX_VISIBLE_TOKENS
    assert deps.learning_loop is True and deps.loop_state == {"x": 1} and deps.feature == "loop_tutor"
    assert deps.course_id == "c1" and deps.session_id == "s1"
    with patch("routes.learn_loop._context_blocks", return_value=[]):
        _, bare, _, _ = _prepare_loop_run(
            user_id="u1", session_id="s1", course_id="", user_message="hi", message_history=[],
            request_id="r1", prefix="P", state={}, tier="lite", item=None,
            context=policy.ContextPolicy(5, True, 0, False, "auto"),
        )
    assert bare == "P\n\nhi"


def test_template_feedback_shapes():
    from routes.learn_loop import _template_feedback

    assert _template_feedback("correct", None).startswith("Correct.")
    released = _template_feedback("not_yet", ITEM.reference_answer)
    assert released.startswith("Not yet.") and ITEM.reference_answer in released
    assert _template_feedback("idk", ITEM.reference_answer).startswith("No problem")


# ── Status ────────────────────────────────────────────────────────────────


def test_status_payload(gate_on, seams):
    r = client.get("/api/learn/loop/status?user_id=u1&session_id=s1")
    assert r.status_code == 200
    body = r.json()
    assert body["active"] is True and body["session_id"] == "s1"
    assert body["phase"] == "check" and body["active_question_hash"] == "qh-1"
    assert body["ceiling"] == int(Rung.H3) and body["band"] == "develop"
    assert body["items"] == 1 and body["rung"] == 1
    assert "reference_answer" not in json.dumps(body) and ITEM.reference_answer not in json.dumps(body)
    seams.ai_budget.check.assert_not_called()


def test_status_of_a_lazy_session_is_a_fresh_state(gate_on, seams):
    from routes.learn_loop import PENDING_SESSIONS

    seams.scope.side_effect = HTTPException(status_code=404, detail="Session not found")
    PENDING_SESSIONS["s-lazy"] = {"user_id": "u1"}
    try:
        r = client.get("/api/learn/loop/status?user_id=u1&session_id=s-lazy")
    finally:
        PENDING_SESSIONS.pop("s-lazy", None)
    assert r.status_code == 200 and r.json()["phase"] == "teach" and r.json()["items"] == 0
    seams.load.assert_not_called()


# ── Streamed and JSON chat turns ──────────────────────────────────────────


def _fake_stream(reply="Key idea: the base case. What input stops it?"):
    async def fake(**kwargs):
        yield SaplingEvent(type="status", step="start", message="Starting.")
        yield SaplingEvent(type="token", step="reply", message="", data={"delta": reply})
        extra = kwargs["on_complete"](reply, {}, []) or {}
        yield SaplingEvent(
            type="done",
            step="reply",
            message="Complete.",
            data={"reply": reply, "graph_update": {}, "mastery_changes": [], **extra},
        )

    return fake


def test_teach_stream_checks_budget_routes_the_tier_and_counts_the_request(gate_on, seams):
    seams.store["doc"] = {}
    with patch("routes.learn_loop.stream_agent_turn", _fake_stream()):
        r = client.post(
            "/api/learn/loop/chat/stream",
            json={"session_id": "s1", "user_id": "u1", "message": "hi", "model_pref": "smart"},
        )
    assert r.status_code == 200 and "text/event-stream" in r.headers["content-type"]
    evs = _sse_events(r.text)
    assert [e["type"] for e in evs][:2] == ["phase", "status"] and evs[-1]["type"] == "done"
    assert evs[0]["data"] == {"phase": "teach"}
    done = evs[-1]["data"]
    assert done["tier"] == "standard" and done["phase"] == "teach" and done["leak_redacted"] is False
    # no concept yet: the opener-less teach band comes from BKT_L0 (develop)
    seams.ai_budget.check.assert_called_once_with(
        "u1", "tutor", "develop", session_tutor_requests=0, session_deep_requests=0, arm_session=False
    )
    assert seams.model_tier.call_args.kwargs["budget_level"] == "normal"
    seams.tier_run_kwargs.assert_called_once_with("standard", tool_choice="auto")  # no fast/smart knob
    assert seams.model_tier.call_args.args[0] == "teach"
    assert [c.args[1] for c in seams.save_msg.call_args_list] == ["user", "assistant"]
    assert seams.store["doc"]["tutor_requests"] == 1 and seams.store["doc"].get("deep_requests", 0) == 0
    assert seams.store["doc"]["phase_served"] == "teach"
    seams.events.log_event.assert_called_once()
    assert seams.events.log_event.call_args.args[0] == "chat.message_sent"


def test_check_phase_chat_serves_the_pose_without_a_model(gate_on, seams):
    never = MagicMock(side_effect=AssertionError("the check pose never reaches the model"))
    with patch("routes.learn_loop.stream_agent_turn", never):
        r = client.post(
            "/api/learn/loop/chat/stream", json={"session_id": "s1", "user_id": "u1", "message": "is it n == 0?"}
        )
    evs = _sse_events(r.text)
    assert [e["type"] for e in evs] == ["phase", "check", "learner_state", "done"]
    assert evs[1]["data"] == {"question_hash": "qh-1", "format": "free", "difficulty": 2}
    assert evs[2]["data"] == {"node_id": "node-1", "p_known": 0.5, "band": "develop"}
    done = evs[-1]["data"]
    assert done["reply"] == ITEM.prompt and done["tier"] == "none" and done["phase"] == "check"
    seams.model_tier.assert_not_called()
    assert seams.store["doc"].get("tutor_requests", 0) == 0
    assert seams.store["doc"]["current"] == "qh-1", "a message typed in the check phase closes nothing"


def test_hard_budget_pauses_a_teach_stream_and_persists_nothing(gate_on, seams):
    seams.store["doc"] = {}
    seams.ai_budget.check.return_value = HARD
    never = MagicMock(side_effect=AssertionError("no model at the hard level"))
    with patch("routes.learn_loop.stream_agent_turn", never):
        r = client.post("/api/learn/loop/chat/stream", json={"session_id": "s1", "user_id": "u1", "message": "hi"})
    evs = _sse_events(r.text)
    assert [e["type"] for e in evs] == ["phase", "budget"]
    assert evs[1]["data"] == {"level": "hard", "reset_at": RESET_ISO}
    seams.save_msg.assert_not_called()
    seams.save.assert_not_called()


def test_hard_budget_json_chat_is_429_with_reset_at(gate_on, seams):
    seams.store["doc"] = {}
    seams.ai_budget.check.return_value = HARD
    r = client.post("/api/learn/loop/chat", json={"session_id": "s1", "user_id": "u1", "message": "hi"})
    assert r.status_code == 429  # AIBudgetExceeded → PKG-06b's registered handler
    assert r.json()["detail"] == "ai budget reached" and r.json()["reset_at"] == RESET_ISO
    seams.save.assert_not_called()


def test_novice_check_pose_pauses_at_the_hard_level(gate_on, seams):
    """§3.5: novice-band concepts pause (no check is served for them)."""
    seams.p_known["node-1"] = 0.1
    seams.ai_budget.check.return_value = HARD
    r = client.post("/api/learn/loop/chat", json={"session_id": "s1", "user_id": "u1", "message": "?"})
    assert r.status_code == 429
    seams.ai_budget.check.assert_called_once_with(
        "u1", "tutor", "novice", session_tutor_requests=0, session_deep_requests=0, arm_session=False
    )


def test_develop_check_pose_is_served_at_the_hard_level_with_the_notice(gate_on, seams):
    seams.ai_budget.check.return_value = SimpleNamespace(**{**vars(HARD), "pause_novice": False})
    r = client.post("/api/learn/loop/chat", json={"session_id": "s1", "user_id": "u1", "message": "?"})
    assert r.status_code == 200
    body = r.json()
    assert body["reply"] == ITEM.prompt and body["tier"] == "none"
    assert body["budget"] == {"level": "hard", "reset_at": RESET_ISO}


def test_soft_level_reaches_tier_and_context_policy(gate_on, seams):
    seams.store["doc"] = {}
    seams.ai_budget.check.return_value = SOFT
    with patch("routes.learn_loop.stream_agent_turn", _fake_stream()):
        client.post("/api/learn/loop/chat/stream", json={"session_id": "s1", "user_id": "u1", "message": "hi"})
    assert seams.model_tier.call_args.kwargs["budget_level"] == "soft"
    seams.context_policy.assert_called_once_with("teach", opener=False, budget_level="soft")
    seams.tier_run_kwargs.assert_called_once_with("standard", tool_choice="none")


def test_leak_path_on_a_model_turn_redacts_persists_stripped_and_emits(gate_on, seams):
    seams.store["doc"] = _graded("correct")
    leaky = "The base case returns 1 when n equals 0 without a recursive call. Done?"
    with patch("routes.learn_loop.stream_agent_turn", _fake_stream(leaky)):
        r = client.post("/api/learn/loop/chat/stream", json={"session_id": "s1", "user_id": "u1", "message": "ok"})
    done = _sse_events(r.text)[-1]["data"]
    assert done["reply"] == "STRIPPED" and done["leak_redacted"] is True and done["phase"] == "feedback"
    assert seams.detect.call_args.args[0] == ITEM.reference_answer
    assert seams.detect.call_args.kwargs == {"final_answer": ITEM.final_answer, "canonical_answer": None}
    assert seams.strip.call_args.kwargs == {"final_answer": ITEM.final_answer, "canonical_answer": None}
    assert seams.detect.call_args.args[2] == Rung.H3, "a correct verdict does not release the answer"
    seams.zpd.emit_zpd_leak.assert_called_once()
    leak_kw = seams.zpd.emit_zpd_leak.call_args.kwargs
    assert leak_kw["ceiling"] == Rung.H3 and leak_kw["detector"] == "ngram" and leak_kw["user_id"] == "u1"
    assistant_row = [c for c in seams.save_msg.call_args_list if c.args[1] == "assistant"][0]
    assert assistant_row.args[2] == "STRIPPED", "the stripped text is what persists"
    assert ITEM.reference_answer not in json.dumps(seams.zpd.emit_zpd_leak.call_args.kwargs)


def test_feedback_recovery_after_wrong_releases_answer_emits_step_and_clears_active(gate_on, seams):
    import routes.learn_loop as ll

    seams.store["doc"] = _graded("not_yet", rungs=[{"rung": 1, "at": T0 + 100}])
    reply = "You wrote 1. The base case is n == 0. Try factorial(1) next?"
    with patch("routes.learn_loop.stream_agent_turn", _fake_stream(reply)), \
         patch("routes.learn_loop.phase_prefix", wraps=ll.phase_prefix) as prefix:
        r = client.post("/api/learn/loop/chat/stream", json={"session_id": "s1", "user_id": "u1", "message": "ok"})
    evs = _sse_events(r.text)
    assert evs[0]["data"] == {"phase": "feedback"}
    assert prefix.call_args.kwargs["verdict"] == "not_yet" and prefix.call_args.kwargs["answer_released"] is True
    assert seams.model_tier.call_args.args[0] == "feedback_wrong"
    assert seams.detect.call_args.args[2] == Rung.H6, "a wrong graded attempt releases the answer (spec §3.3)"
    doc = seams.store["doc"]
    assert doc["current"] is None and doc["steps"]["qh-1"]["feedback_given"] is True
    seams.zpd.emit_zpd_step.assert_called_once()
    step = seams.zpd.emit_zpd_step.call_args.kwargs
    assert step["tier"] == "standard" and step["grader_backend"] == "gemini" and step["question_hash"] == "qh-1"
    assert step["phase"] == "check" and step["channel"] == "free_response" and step["concept_id"] == "node-1"
    assert step["first_attempt_correct"] is False and step["n_attempts"] == 1
    assert step["max_rung_used"] == Rung.H1 and step["assisted"] is True and step["fsrs_rating"] == 1
    assert step["p_known_before"] == 0.5 and step["p_known_after"] == 0.5, "honest: the re-read p"
    assert step["rungs"] == [{"rung": 1, "dwell_ms": 495_000}], "H1 shown at T0+100, graded at NOW-5"
    assert step["time_to_correct_ms"] is None and step["independent_time_ms"] == 100_000
    assert step["r_before"] is None, "unknown to the route: null, never zero"
    assert ITEM.reference_answer not in json.dumps(step, default=str)


def test_feedback_after_correct_runs_lite(gate_on, seams):
    seams.store["doc"] = _graded("correct")
    with patch("routes.learn_loop.stream_agent_turn", _fake_stream("Right. Next?")):
        r = client.post("/api/learn/loop/chat/stream", json={"session_id": "s1", "user_id": "u1", "message": "ok"})
    assert _sse_events(r.text)[-1]["data"]["tier"] == "lite"
    assert seams.model_tier.call_args.args[0] == "feedback_correct"


def test_rung1_fallback_is_the_json_turn_on_the_same_tier(gate_on, seams):
    seams.store["doc"] = {}

    async def fake(**kwargs):
        result = await kwargs["nonstream_fallback"]()
        yield SaplingEvent(type="done", step="reply", message="Complete.", data=result)

    agent, seen = _json_agent("fb")
    with patch("routes.learn_loop.stream_agent_turn", fake), \
         patch("routes.learn_loop.loop_tutor_agent", agent), \
         patch("routes.learn_loop.record_agent_usage", side_effect=lambda r, **k: r) as usage:
        r = client.post("/api/learn/loop/chat/stream", json={"session_id": "s1", "user_id": "u1", "message": "hi"})
    assert "fb" in r.text
    assert seen["kw"]["model"] == "MODEL:standard" and usage.call_args.kwargs["task"] == "loop_tutor"
    assert seams.ai_budget.check.call_count == 2, "every run site checks the budget (invariant 23)"
    assert seams.store["doc"]["tutor_requests"] == 1, "the re-run is the same turn"


def test_chat_json_runs_once_on_the_policy_slot_and_counts_deep(gate_on, seams):
    seams.store["doc"] = {}
    seams.model_tier.return_value = "deep"
    agent, seen = _json_agent()
    with patch("routes.learn_loop.loop_tutor_agent", agent), \
         patch("routes.learn_loop.record_agent_usage", side_effect=lambda r, **k: r) as usage:
        r = client.post(
            "/api/learn/loop/chat",
            json={"session_id": "s1", "user_id": "u1", "message": "hi", "model_pref": "fast"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["reply"].startswith("Key idea") and body["tier"] == "deep" and body["phase"] == "teach"
    assert seen["kw"]["model"] == "MODEL:deep" and seen["kw"]["usage_limits"] is LOOP_LIMITS
    assert seen["msg"].startswith("[LOOP PHASE: teach]")
    assert usage.call_args.kwargs["task"] == "loop_tutor_deep" and usage.call_args.kwargs["feature"] == "loop_tutor"
    assert seams.store["doc"]["tutor_requests"] == 1 and seams.store["doc"]["deep_requests"] == 1


def test_deep_caps_reach_the_tier_router(gate_on, seams):
    from learning.params import LOOP_SESSION_MAX_DEEP_REQUESTS

    seams.store["doc"] = {"tutor_requests": 9, "deep_requests": LOOP_SESSION_MAX_DEEP_REQUESTS}
    agent, _ = _json_agent()
    with patch("routes.learn_loop.loop_tutor_agent", agent), \
         patch("routes.learn_loop.record_agent_usage", side_effect=lambda r, **k: r):
        client.post("/api/learn/loop/chat", json={"session_id": "s1", "user_id": "u1", "message": "hi"})
    kw = seams.model_tier.call_args.kwargs
    assert kw["deep_cap_reached"] is True and kw["novice_deep_cap_reached"] is False
    assert kw["arm_session"] is False and kw["deterministic_payload"] is False
    seams.ai_budget.check.assert_called_once_with(
        "u1", "tutor", "develop", session_tutor_requests=9,
        session_deep_requests=LOOP_SESSION_MAX_DEEP_REQUESTS, arm_session=False,
    )


def test_a_textless_json_turn_is_rescued_by_the_continuation(gate_on, seams):
    from tests.agent_run_fakes import textless_run_result

    seams.store["doc"] = {}
    agent = MagicMock()

    async def _run(msg, **kw):
        return textless_run_result("stale")

    agent.run = _run
    with patch("routes.learn_loop.loop_tutor_agent", agent), \
         patch("routes.learn_loop.record_agent_usage", side_effect=lambda r, **k: r), \
         patch("routes.learn_loop._loop_continuation_text", AsyncMock(return_value="rescued")) as cont:
        body = client.post(
            "/api/learn/loop/chat", json={"session_id": "s1", "user_id": "u1", "message": "hi"}
        ).json()
    assert body["reply"] == "rescued"
    cont.assert_awaited_once()
    with patch("routes.learn_loop.loop_tutor_agent", agent), \
         patch("routes.learn_loop.record_agent_usage", side_effect=lambda r, **k: r), \
         patch("routes.learn_loop._loop_continuation_text", AsyncMock(return_value=None)):
        r = client.post("/api/learn/loop/chat", json={"session_id": "s1", "user_id": "u1", "message": "hi"})
    assert r.status_code == 502


def test_loop_continuation_is_tool_less_budget_checked_and_capped():
    import asyncio

    from agents import CONTINUATION_LIMITS
    from routes.learn_loop import _loop_continuation_text

    order, seen = [], {}
    agent = MagicMock()

    class _Ctx:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _override(**kw):
        seen["override"] = kw
        return _Ctx()

    async def _run(nudge, **kw):
        order.append("run")
        seen["run"] = kw
        return run_result("finished reply")

    agent.override, agent.run = _override, _run
    turn = SimpleNamespace(
        user_id="u1",
        band="develop",
        slot="loop_tutor",
        agent=agent,
        run_kwargs={"deps": SimpleNamespace(user_id="u1"), "model": "M", "model_settings": {}},
        budget_counters=lambda: {"session_tutor_requests": 0, "session_deep_requests": 0, "arm_session": False},
    )
    with patch("routes.learn_loop.ai_budget") as budget, \
         patch(
             "routes.learn_loop.record_agent_usage",
             side_effect=lambda r, **k: (seen.__setitem__("usage", k), r)[1],
         ):
        budget.check.side_effect = lambda *a, **k: (order.append("check"), NORMAL)[1]
        assert asyncio.run(_loop_continuation_text(turn, run_result("x"))) == "finished reply"
        assert order == ["check", "run"]
        assert seen["override"] == {"tools": [], "toolsets": []}
        assert seen["run"]["usage_limits"] is CONTINUATION_LIMITS and seen["run"]["model"] == "M"
        assert "message_history" in seen["run"] and "usage" not in seen["run"]
        assert seen["usage"]["task"] == "loop_tutor" and seen["usage"]["feature"] == "loop_tutor_continuation"
        budget.check.side_effect = None
        budget.check.return_value = HARD
        order.clear()
        assert asyncio.run(_loop_continuation_text(turn, run_result("x"))) is None and order == []


def test_a_withdrawn_active_item_is_dropped_and_the_turn_teaches(gate_on, seams):
    """A23 withdrawal: the item is gone, so the turn drops it and runs as teach."""
    seams.item.return_value = None
    agent, seen = _json_agent()
    with patch("routes.learn_loop.loop_tutor_agent", agent), \
         patch("routes.learn_loop.record_agent_usage", side_effect=lambda r, **k: r):
        body = client.post(
            "/api/learn/loop/chat", json={"session_id": "s1", "user_id": "u1", "message": "hi"}
        ).json()
    assert body["phase"] == "teach" and seen["msg"].startswith("[LOOP PHASE: teach]")
    doc = seams.store["doc"]
    assert doc["current"] is None and "qh-1" in doc["steps"], "the entry stays for bookkeeping"


# ── Task 6: the explicit-submission route (A16) ────────────────────────────


def _answer(**kw) -> dict:
    return {"session_id": "s1", "user_id": "u1", "question_hash": "qh-1", **kw}


def _feedback_agent(reply="Right: the base case stops it. What would factorial(1) return?"):
    agent, seen = _json_agent(reply)
    return (
        patch("routes.learn_loop.loop_tutor_agent", agent),
        patch("routes.learn_loop.record_agent_usage", side_effect=lambda r, **k: r),
        seen,
    )


def test_idk_phrases_are_non_attempt_patterns():
    from learning.gates import NON_ATTEMPT_PATTERNS
    from routes.learn_loop import IDK_PHRASES

    assert set(IDK_PHRASES) <= set(NON_ATTEMPT_PATTERNS)


@pytest.mark.parametrize(
    "text,idk",
    [
        ("idk", True),
        ("I don't know", True),
        ("I don’t know", True),
        ("idk, just tell me", True),  # the route checks idk first (A16)
        ("just tell me", False),
        ("idk maybe 7", False),  # a hedged answer is graded (HANDOFF-06 (B))
        ("even, idk", False),
        ("n == 0", False),
    ],
)
def test_is_idk_phrase_is_the_a16_routing_rule(text, idk):
    """HANDOFF-06: the idk split is gates.non_attempt_phrases, so a hedged answer
    is graded, never turned into idk evidence."""
    from routes.learn_loop import _is_idk_phrase

    assert _is_idk_phrase(text) is idk


def test_render_submission():
    from models import LoopCheckAnswerBody
    from routes.learn_loop import _render_submission

    body = LoopCheckAnswerBody(**_answer(answer="n == 0"))
    assert _render_submission(body, idk=False) == "n == 0"
    mc = LoopCheckAnswerBody(**_answer(option="B", reason="it stops"))
    assert _render_submission(mc, idk=False) == "(B) it stops"
    assert _render_submission(LoopCheckAnswerBody(**_answer(idk=True)), idk=True) == "I don't know"
    assert _render_submission(LoopCheckAnswerBody(**_answer(reason="why")), idk=False) == "why"


def test_check_answer_grades_flushes_once_then_one_feedback_turn(gate_on, seams):
    agent_p, usage_p, seen = _feedback_agent()
    with agent_p, usage_p as usage:
        r = client.post("/api/learn/loop/check/answer", json=_answer(answer="n == 0 returns 1"))
    assert r.status_code == 200
    body = r.json()
    assert body["graded"] is True and body["verdict"] == "correct" and body["answer_released"] is False
    assert body["phase"] == "feedback" and body["tier"] == "lite" and body["unavailable"] is False
    seams.grade.assert_awaited_once()
    item, answer = seams.grade.call_args.args
    assert item is ITEM and answer.answer_text == "n == 0 returns 1" and answer.idk is False
    assert answer.question_hash == "qh-1"
    kw = seams.grade.call_args.kwargs
    assert kw["max_rung"] == 1 and kw["node_id"] == "node-1"
    assert kw["deps"].learning_loop is True and kw["deps"].feature == "loop_check"
    assert kw["deps"].session_id == "s1" and kw["deps"].course_id == "c1"
    seams.flush.assert_called_once_with(kw["deps"], "c1")
    assert "[VERDICT: correct]" in seen["msg"] and ITEM.reference_answer not in seen["msg"]
    assert seams.model_tier.call_args.args[0] == "feedback_correct"
    assert usage.call_args.kwargs["task"] == "loop_tutor_lite"
    step = seams.zpd.emit_zpd_step.call_args.kwargs
    assert step["tier"] == "lite" and step["grader_backend"] == "gemini" and step["question_hash"] == "qh-1"
    assert step["first_attempt_correct"] is True and step["n_attempts"] == 1
    assert step["time_to_correct_ms"] == 600_000 and step["confidence"] == 0.9
    entry = seams.store["doc"]["steps"]["qh-1"]
    assert seams.store["doc"]["current"] is None and entry["feedback_given"] is True
    assert entry["graded"] == 1 and entry["last_verdict"] == "correct" and entry["graded_at"] == NOW
    assert entry["attempted_at"] == [NOW], "a genuine attempt counts toward hint unlocking"
    assert entry["attempts"] == 0, "a correct attempt closes the step: it is no failed attempt"
    assert entry["p_before"] == 0.5 and entry["fsrs_rating"] == policy.evidence_for_rung(True, Rung.H1).fsrs_rating
    assert [c.args[1] for c in seams.save_msg.call_args_list] == ["user", "assistant"]
    assert seams.save_msg.call_args_list[0].args[2] == "n == 0 returns 1"


def test_check_answer_wrong_releases_the_answer_in_the_feedback_turn(gate_on, seams):
    seams.grade.return_value = WRONG
    agent_p, usage_p, seen = _feedback_agent(
        "Not quite: factorial(0) returns 1 at the base case. Try factorial(1) next?"
    )
    with agent_p, usage_p:
        body = client.post("/api/learn/loop/check/answer", json=_answer(answer="it calls factorial(-1)")).json()
    assert body["verdict"] == "not_yet" and body["answer_released"] is True and body["tier"] == "standard"
    assert "[VERDICT: not_yet]" in seen["msg"] and "state the correct answer" in seen["msg"].lower()
    assert seams.detect.call_args.args[2] == Rung.H6
    entry = seams.store["doc"]["steps"]["qh-1"]
    assert entry["wrong"] == 1 and entry["last_correct"] is False and entry["attempts"] == 1
    assert entry["first_attempt_correct"] is False


@pytest.mark.parametrize("payload", [{"idk": True}, {"answer": "I don't know"}])
def test_check_answer_idk_writes_idk_evidence_and_releases(gate_on, seams, payload):
    seams.grade.return_value = WRONG
    agent_p, usage_p, _ = _feedback_agent("No problem. The base case returns 1 at n == 0. Try factorial(1)?")
    with agent_p, usage_p:
        body = client.post("/api/learn/loop/check/answer", json=_answer(**payload)).json()
    assert seams.grade.call_args.args[1].idk is True
    assert body["verdict"] == "idk" and body["answer_released"] is True
    seams.flush.assert_called_once()
    entry = seams.store["doc"]["steps"]["qh-1"]
    assert entry["attempted_at"] == [] and entry["attempts"] == 0, "an idk is never a genuine attempt"


def test_check_answer_non_attempt_is_a_hint_request_with_no_evidence(gate_on, seams):
    agent_p, usage_p, seen = _feedback_agent("Look at the smallest input first. Which n needs no recursive call?")
    with agent_p, usage_p:
        body = client.post("/api/learn/loop/check/answer", json=_answer(answer="just tell me")).json()
    seams.grade.assert_not_awaited()
    seams.flush.assert_not_called()
    assert body["graded"] is False and body["phase"] == "hint" and body["verdict"] is None
    assert seen["msg"].startswith("[LOOP PHASE: hint]") and "at most rung H1" in seen["msg"]
    doc = seams.store["doc"]
    assert doc["current"] == "qh-1" and "graded_at" not in doc["steps"]["qh-1"]


def test_check_answer_unavailable_writes_nothing_and_keeps_the_item_open(gate_on, seams):
    from routes.learn_loop import _GRADE_UNAVAILABLE_REPLY

    seams.grade.return_value = UNAVAILABLE
    never = MagicMock(side_effect=AssertionError("no feedback model turn without a verdict"))
    with patch("routes.learn_loop.loop_tutor_agent", MagicMock(run=never)):
        body = client.post("/api/learn/loop/check/answer", json=_answer(answer="n == 0")).json()
    assert body["graded"] is False and body["unavailable"] is True and body["reply"] == _GRADE_UNAVAILABLE_REPLY
    assert body["tier"] == "none" and body["phase"] == "check"
    seams.flush.assert_not_called()
    seams.zpd.emit_zpd_step.assert_not_called()
    entry = seams.store["doc"]["steps"]["qh-1"]
    assert seams.store["doc"]["current"] == "qh-1" and "graded_at" not in entry
    assert entry["attempted_at"] == [NOW] and entry["attempts"] == 1, "only the attempt bookkeeping"


def test_independent_time_gate_never_blocks_grading(gate_on, seams):
    seams.store["doc"] = _state(first_shown_at=NOW - 1)  # answered too fast to count toward hint unlocking
    agent_p, usage_p, _ = _feedback_agent()
    with agent_p, usage_p:
        client.post("/api/learn/loop/check/answer", json=_answer(answer="n == 0"))
    seams.grade.assert_awaited_once()
    assert seams.store["doc"]["steps"]["qh-1"]["attempted_at"] == []


def test_check_answer_hard_budget_serves_template_feedback_not_429(gate_on, seams):
    seams.grade.return_value = WRONG
    seams.ai_budget.check.return_value = SimpleNamespace(**{**vars(HARD), "pause_novice": False})
    never = MagicMock(side_effect=AssertionError("no model at the hard level"))
    with patch("routes.learn_loop.loop_tutor_agent", MagicMock(run=never)):
        r = client.post("/api/learn/loop/check/answer", json=_answer(answer="it calls factorial(-1)"))
    assert r.status_code == 200
    body = r.json()
    assert ITEM.reference_answer in body["reply"] and body["tier"] == "none"
    assert body["reply"].startswith("Not yet.")
    assert body["budget"] == {"level": "hard", "reset_at": RESET_ISO}
    seams.flush.assert_called_once()  # grading has its own cap; the evidence still lands
    assert seams.zpd.emit_zpd_step.call_args.kwargs["tier"] == "none"


def test_check_answer_stream_grades_before_streaming(gate_on, seams):
    order = []
    seams.grade.side_effect = lambda *a, **k: (order.append("grade"), CORRECT)[1]

    def fake_factory():
        inner = _fake_stream("Right. What would factorial(1) return?")

        async def fake(**kwargs):
            order.append("stream")
            async for ev in inner(**kwargs):
                yield ev

        return fake

    with patch("routes.learn_loop.stream_agent_turn", fake_factory()):
        r = client.post("/api/learn/loop/check/answer/stream", json=_answer(answer="n == 0 returns 1"))
    evs = _sse_events(r.text)
    assert order == ["grade", "stream"]
    assert [e["type"] for e in evs] == ["phase", "status", "token", "learner_state", "done"]
    assert evs[0]["data"] == {"phase": "feedback"}
    done = evs[-1]["data"]
    assert done["verdict"] == "correct" and done["graded"] is True and done["unavailable"] is False


@pytest.mark.parametrize("path", ["/api/learn/loop/check/answer", "/api/learn/loop/check/answer/stream"])
def test_a_failed_flush_is_a_mapped_502_before_any_stream(gate_on, seams, path):
    seams.flush.side_effect = RuntimeError("apply_graph_update failed")
    never = MagicMock(side_effect=AssertionError("no stream after a failed flush"))
    with patch("routes.learn_loop.stream_agent_turn", never):
        r = client.post(path, json=_answer(answer="n == 0"))
    assert r.status_code == 502
    assert "graded_at" not in seams.store["doc"]["steps"]["qh-1"]


def test_check_answer_unknown_or_inactive_item_is_404(gate_on, seams):
    r = client.post("/api/learn/loop/check/answer", json=_answer(question_hash="nope", answer="x"))
    assert r.status_code == 404
    seams.store["doc"] = dict(_state(), current=None)
    r = client.post("/api/learn/loop/check/answer", json=_answer(answer="x"))
    assert r.status_code == 404
    seams.grade.assert_not_awaited()


def test_check_answer_on_a_withdrawn_item_is_409(gate_on, seams):
    seams.item.return_value = None
    r = client.post("/api/learn/loop/check/answer", json=_answer(answer="x"))
    assert r.status_code == 409 and r.json()["detail"] == "check item withdrawn"
    seams.grade.assert_not_awaited()


def test_check_answer_with_no_graph_node_is_409(gate_on, seams):
    seams.node.return_value = None
    r = client.post("/api/learn/loop/check/answer", json=_answer(answer="x"))
    assert r.status_code == 409 and r.json()["detail"] == "no graph node for this item"
    seams.grade.assert_not_awaited()
    seams.save.assert_not_called()


def test_an_over_long_answer_is_a_422_before_anything_runs(gate_on, seams):
    from learning.params import GRADER_ANSWER_MAX_CHARS

    r = client.post("/api/learn/loop/check/answer", json=_answer(answer="x" * (GRADER_ANSWER_MAX_CHARS + 1)))
    assert r.status_code == 422
    gate_on.assert_not_called()
    seams.grade.assert_not_awaited()


def test_a_chat_message_in_the_check_phase_writes_no_evidence(gate_on, seams):
    """Invariant 26's route half: only /check/answer grades."""
    for path in ("/api/learn/loop/chat", "/api/learn/loop/chat/stream"):
        client.post(path, json={"session_id": "s1", "user_id": "u1", "message": "the answer is n == 0"})
    seams.grade.assert_not_awaited()
    seams.flush.assert_not_called()
