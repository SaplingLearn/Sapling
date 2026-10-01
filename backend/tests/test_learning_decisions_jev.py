"""PKG-15: the `jev` and `shadow_jev` backends of services/decisions.py (spec §3.6, §6,
§13 A24, A98). Hermetic: Jev is either a scripted `_jev.ask` or an httpx2.MockTransport;
the decision agent runs on FunctionModel; the grader is stubbed; events and llm_usage
rows are captured by patching events_service."""

from __future__ import annotations

import asyncio
import json

import httpx2
import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from agents import _jev
from agents.deps import SaplingDeps

QUESTION = "Why does every recursive function need a base case?"
REFERENCE = "The base case stops the recursion; without it the stack grows until overflow."
RUBRIC = {"r1": "names the base case", "r2": "explains unbounded growth"}
WRONG = {"w_loop": "confuses recursion with a loop", "w_speed": "says the base case is only for speed"}
ANSWER = "It only makes it faster."


def _deps(**over) -> SaplingDeps:
    kw = dict(
        user_id="user-zz9",
        course_id="course-zz9",
        supabase=None,
        request_id="req-zz9",
        session_id="sess-zz9",
        feature="tutor",
        learning_loop=True,
    )
    return SaplingDeps(**{**kw, **over})


@pytest.fixture
def events(monkeypatch):
    from services import events_service

    got: list[tuple[str, dict]] = []
    monkeypatch.setattr(events_service, "log_event", lambda et, **kw: got.append((et, kw)))
    return got


@pytest.fixture
def usage(monkeypatch):
    from services import events_service

    rows: list[dict] = []
    monkeypatch.setattr(events_service, "log_llm_usage", lambda **kw: rows.append(kw))
    return rows


@pytest.fixture
def seam(monkeypatch, events, usage):
    from services import decisions

    monkeypatch.delenv("SAPLING_MODEL_MODE", raising=False)
    for name in decisions.DECISION_NAMES:
        monkeypatch.delenv(f"DECISION_BACKEND_{name.upper()}", raising=False)
    monkeypatch.setattr(decisions, "JEV_ENABLED", True)
    monkeypatch.setenv(_jev.API_KEY_ENV, "ts-test-key")
    return decisions


def _gemini(answer="no", confidence=0.8, *, choice=None):
    """The decision agent on FunctionModel (yes/no or pick); counts its runs."""
    from agents.decision import decision_agent

    runs = []

    def handler(messages, info):
        runs.append(messages[-1].parts[-1].content)
        args = {"choice": choice, "confidence": confidence} if choice else {"answer": answer, "confidence": confidence}
        return ModelResponse(parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=args)])

    return decision_agent.override(model=FunctionModel(handler)), runs


def _scripted_jev(monkeypatch, seam, *outcomes):
    """Replace _jev.ask: each call takes the next outcome — a dict of {question: (choice,
    confidence, probs)} answered, or a JevUnavailable raised."""
    calls = []

    async def ask(payload, questions):
        calls.append((payload, questions))
        nxt = outcomes[min(len(calls) - 1, len(outcomes) - 1)]
        if isinstance(nxt, BaseException):
            raise nxt
        answers = {
            q: _jev.Answer(choice=c, confidence=conf, probabilities=probs)
            for q, (c, conf, probs) in nxt.items()
        }
        return _jev.Result(answers=answers, model="jev-1.13.0", input_tokens=210, output_tokens=3, latency_ms=41)

    monkeypatch.setattr(_jev, "ask", ask)
    return calls


def _leak(seam):
    return seam.LeakState(reference=REFERENCE, emitted="Once it stops, the calls end.", rung=1)


def _wrong(seam):
    return seam.WrongReasonState(question=QUESTION, answer=ANSWER, wrong=WRONG)


def _payloads(events, kind):
    return [kw["payload"] for et, kw in events if et == kind]


def _run(coro_fn):
    """Run one decision and then every shadow it scheduled, in one loop."""

    async def main():
        out = await coro_fn()
        from services import decisions

        await decisions.drain_shadows()
        return out

    return asyncio.run(main())


# ── `jev`: served from Jev ──────────────────────────────────────────────────


def test_jev_serves_a_yes_no_decision_and_records_typesafe_usage(seam, monkeypatch, events, usage):
    monkeypatch.setenv("DECISION_BACKEND_JUDGE_LEAK", "jev")
    calls = _scripted_jev(monkeypatch, seam, {"q": ("no", 0.93, {"yes": 0.04, "no": 0.93, "unclear": 0.03})})
    cm, runs = _gemini()
    with cm:
        v = _run(lambda: seam.judge_leak(_leak(seam), deps=_deps()))
    assert (v.backend, v.value, v.fallback, v.confidence) == ("jev", False, False, 0.93)
    assert v.p_yes == pytest.approx(0.04)
    assert runs == []  # no Gemini run
    [made] = _payloads(events, "decision.made")
    assert (made["backend"], made["decision"]) == ("jev", "judge_leak")
    assert _payloads(events, "decision.fallback") == []
    [row] = usage
    assert (row["provider"], row["task"], row["model"]) == ("typesafe", "decision", "jev-1.13.0")
    assert row["usage"] == {"input_tokens": 210, "output_tokens": 3}
    assert (row["user_id"], row["request_id"], row["session_id"]) == ("user-zz9", "req-zz9", "sess-zz9")
    payload, questions = calls[0]
    assert set(questions["q"].options) == {"yes", "no", "unclear"}  # a Choice (A24)
    assert payload == {
        "reference_answer": REFERENCE,
        "emitted_text": "Once it stops, the calls end.",
        "hint_rung": "H1",
    }


def test_jev_unclear_blocks_on_judge_leak(seam, monkeypatch):
    monkeypatch.setenv("DECISION_BACKEND_JUDGE_LEAK", "jev")
    _scripted_jev(monkeypatch, seam, {"q": ("unclear", 0.7, {})})
    v = _run(lambda: seam.judge_leak(_leak(seam), deps=_deps()))
    assert (v.backend, v.value, v.p_yes) == ("jev", True, seam.P_YES_UNCLEAR)


@pytest.mark.parametrize(
    "failure,reason",
    [
        (_jev.JevUnavailable("timeout"), "timeout"),
        (_jev.JevUnavailable("http_429"), "http_429"),
        (_jev.JevUnavailable("http_529"), "http_529"),
        (_jev.JevUnavailable("http_401"), "http_401"),
        (_jev.JevUnavailable("circuit_open"), "circuit_open"),
        (_jev.JevUnavailable("oversize"), "oversize"),
        (_jev.JevUnavailable("jev_absent"), "jev_absent"),
        (_jev.JevUnavailable("bad_answer", model="jev-1.13.0", input_tokens=50), "bad_answer"),
        (RuntimeError("a bug below the seam"), "bad_answer"),
        ({"q": ("yes", 0.31, {})}, "low_confidence"),
    ],
)
def test_any_jev_failure_serves_gemini_with_a_fallback_event(seam, monkeypatch, events, usage, failure, reason):
    monkeypatch.setenv("DECISION_BACKEND_ITEM_ANSWERABLE", "jev")
    _scripted_jev(monkeypatch, seam, failure)
    state = seam.AnswerableState(passages=["A base case ends recursion."], question=QUESTION, reference=REFERENCE)
    cm, runs = _gemini("yes", 0.8)
    with cm:
        v = _run(lambda: seam.item_answerable(state, deps=_deps()))
    assert (v.backend, v.value, v.fallback) == ("gemini", True, True)
    assert len(runs) == 1
    assert _payloads(events, "decision.fallback") == [
        {
            "decision": "item_answerable",
            "from_backend": "jev",
            "to_backend": "gemini",
            "reason": reason,
            "request_id": "req-zz9",
        }
    ]
    typesafe = [r for r in usage if r.get("provider") == "typesafe"]
    billed = reason in ("bad_answer", "low_confidence") and not isinstance(failure, RuntimeError)
    assert len(typesafe) == (1 if billed else 0)  # an unusable 200 is still billed


def test_a_capped_student_gets_no_jev_and_no_gemini_run(seam, monkeypatch, events):
    from services import ai_budget

    monkeypatch.setattr(
        ai_budget,
        "check",
        lambda *a, **k: ai_budget.BudgetDecision(level="hard", tier_ceiling="fast", scope="daily_grades"),
    )
    monkeypatch.setenv("DECISION_BACKEND_JUDGE_LEAK", "jev")
    calls = _scripted_jev(monkeypatch, seam, {"q": ("no", 0.9, {})})
    cm, runs = _gemini()
    with cm:
        assert _run(lambda: seam.judge_leak(_leak(seam), deps=_deps())) is None
    assert calls == [] and runs == []
    assert [p["reason"] for p in _payloads(events, "decision.fallback")] == ["budget"]


def test_jev_serves_match_wrong_reason_over_the_prior_and_maps_aliases_back(seam, monkeypatch, events):
    from agents.grader import GradeResult

    monkeypatch.setenv("DECISION_BACKEND_MATCH_WRONG_REASON", "jev")
    wrong = {"w_loop": WRONG["w_loop"], "Speed Key": WRONG["w_speed"]}  # an unclean key → alias
    calls = _scripted_jev(monkeypatch, seam, {"q": ("k2", 0.88, {"k2": 0.88, "w_loop": 0.1, "none": 0.02})})
    prior = GradeResult(confidence=0.9, matched_wrong_key="w_loop", backend="gemini")
    state = seam.WrongReasonState(question=QUESTION, answer=ANSWER, wrong=wrong)
    v = _run(lambda: seam.match_wrong_reason(state, deps=_deps(), prior=prior))
    assert (v.backend, v.value, v.fallback) == ("jev", "Speed Key", False)
    assert v.probs == {"Speed Key": 0.88, "w_loop": 0.1, "none": 0.02}
    assert set(calls[0][1]["q"].options) == {"w_loop", "k2", "none"}
    assert _payloads(events, "decision.made")[0]["prior"] is False


def test_a_failed_jev_match_falls_back_to_the_prior_with_no_model_run(seam, monkeypatch, events):
    from agents.grader import GradeResult

    monkeypatch.setenv("DECISION_BACKEND_MATCH_WRONG_REASON", "jev")
    _scripted_jev(monkeypatch, seam, _jev.JevUnavailable("timeout"))
    prior = GradeResult(confidence=0.9, matched_wrong_key="w_speed", backend="gemini")
    cm, runs = _gemini(choice="w_loop")
    with cm:
        v = _run(lambda: seam.match_wrong_reason(_wrong(seam), deps=_deps(), prior=prior))
    assert (v.backend, v.value, v.fallback) == ("gemini", "w_speed", True) and runs == []
    assert [p["reason"] for p in _payloads(events, "decision.fallback")] == ["timeout"]


# ── `shadow_jev`: Gemini serves, Jev runs in the background ──────────────────


def test_shadow_never_waits_for_jev(seam, monkeypatch, events):
    """The served verdict is returned while the Jev call is still in flight; the shadow
    event comes only after Jev answers."""
    monkeypatch.setenv("DECISION_BACKEND_JUDGE_LEAK", "shadow_jev")
    release = None

    async def ask(payload, questions):
        await release.wait()
        return _jev.Result(
            answers={"q": _jev.Answer("no", 0.9, {"no": 0.9})},
            model="jev-1.13.0",
            input_tokens=200,
            output_tokens=2,
            latency_ms=480,
        )

    monkeypatch.setattr(_jev, "ask", ask)
    cm, runs = _gemini("no", 0.8)

    async def main():
        nonlocal release
        release = asyncio.Event()
        v = await seam.judge_leak(_leak(seam), deps=_deps())
        before = list(_payloads(events, "decision.shadow"))
        release.set()
        await seam.drain_shadows()
        return v, before

    with cm:
        v, before = asyncio.run(main())
    assert (v.backend, v.value, v.fallback) == ("gemini", False, False)
    assert before == []
    [shadow] = _payloads(events, "decision.shadow")
    assert shadow == {
        "decision": "judge_leak",
        "request_id": "req-zz9",
        "primary_value": "no",
        "shadow_value": "no",
        "primary_confidence": 0.8,
        "shadow_confidence": 0.9,
        "agreement": True,
        "shadow_latency_ms": 480,
        "shadow_input_tokens": 200,
        "error_code": None,
    }


def test_a_failing_shadow_never_touches_the_served_answer(seam, monkeypatch, events, usage):
    monkeypatch.setenv("DECISION_BACKEND_JUDGE_LEAK", "shadow_jev")
    _scripted_jev(monkeypatch, seam, _jev.JevUnavailable("http_529", latency_ms=12))
    cm, _ = _gemini("yes", 0.7)
    with cm:
        v = _run(lambda: seam.judge_leak(_leak(seam), deps=_deps()))
    assert (v.backend, v.value, v.fallback) == ("gemini", True, False)
    [shadow] = _payloads(events, "decision.shadow")
    assert (shadow["error_code"], shadow["shadow_value"], shadow["agreement"]) == ("http_529", None, False)
    assert _payloads(events, "decision.fallback") == []  # a shadow failure is not a fallback
    assert [r for r in usage if r.get("provider") == "typesafe"] == []


def test_a_shadow_that_raises_is_swallowed(seam, monkeypatch, events, caplog):
    monkeypatch.setenv("DECISION_BACKEND_JUDGE_LEAK", "shadow_jev")
    monkeypatch.setattr(seam, "emit_shadow", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    _scripted_jev(monkeypatch, seam, {"q": ("no", 0.9, {})})
    cm, _ = _gemini("no", 0.8)
    with cm, caplog.at_level("WARNING"):
        v = _run(lambda: seam.judge_leak(_leak(seam), deps=_deps()))
    assert v.backend == "gemini"
    assert any("decision shadow failed" in r.getMessage() for r in caplog.records)


def test_shadow_usage_is_typesafe_and_never_a_grade(seam, monkeypatch, usage):
    from services import ai_budget

    monkeypatch.setenv("DECISION_BACKEND_JUDGE_LEAK", "shadow_jev")
    _scripted_jev(monkeypatch, seam, {"q": ("no", 0.9, {})})
    monkeypatch.setattr(seam, "record_agent_usage", lambda r, **kw: r)
    cm, _ = _gemini("no", 0.8)
    with cm:
        _run(lambda: seam.judge_leak(_leak(seam), deps=_deps()))
    [row] = [r for r in usage if r.get("provider") == "typesafe"]
    assert row["task"] == "decision_shadow" and row["task"] not in ai_budget.GRADE_TASKS


def test_the_shadow_of_a_grade_compares_the_served_all_yes(seam, monkeypatch, events):
    import agents.grader as g
    from agents.grader import GradeResult

    async def _grade(item, *, format, student_answer, deps):
        return GradeResult(item_results={"r1": True, "r2": False}, all_yes=False, confidence=0.86)

    monkeypatch.setattr(g, "grade", _grade)
    monkeypatch.setenv("DECISION_BACKEND_GRADE_RUBRIC_ITEMS", "shadow_jev")
    calls = _scripted_jev(monkeypatch, seam, {"item_1": ("yes", 0.9, {}), "item_2": ("yes", 0.7, {})})
    state = seam.GradeState(question=QUESTION, reference=REFERENCE, rubric=RUBRIC, wrong=WRONG, answer=ANSWER, format="free")
    v = _run(lambda: seam.grade_rubric_items(state, deps=_deps()))
    assert (v.backend, v.result.all_yes) == ("gemini", False)
    payload, questions = calls[0]
    assert set(questions) == {"item_1", "item_2"}  # positional: no rubric id on the wire
    assert "names the base case" in questions["item_1"].instructions
    assert payload == {"question": QUESTION, "reference_answer": REFERENCE, "student_answer": ANSWER}
    [shadow] = _payloads(events, "decision.shadow")
    assert (shadow["primary_value"], shadow["shadow_value"], shadow["agreement"]) == ("no", "yes", False)
    assert shadow["shadow_confidence"] == 0.7  # the least sure item


@pytest.mark.parametrize("refused", [True, False])
def test_a_refused_or_unavailable_grade_is_never_shadowed(seam, monkeypatch, events, refused):
    import agents.grader as g
    from agents.grader import GradeResult

    result = GradeResult(unavailable=True, refused="addresses_grader" if refused else None)

    async def _grade(item, *, format, student_answer, deps):
        return result

    monkeypatch.setattr(g, "grade", _grade)
    monkeypatch.setenv("DECISION_BACKEND_GRADE_RUBRIC_ITEMS", "shadow_jev")
    calls = _scripted_jev(monkeypatch, seam, {"item_1": ("yes", 0.9, {})})
    state = seam.GradeState(question=QUESTION, reference=REFERENCE, rubric=RUBRIC, wrong=WRONG, answer=ANSWER, format="free")
    _run(lambda: seam.grade_rubric_items(state, deps=_deps()))
    assert calls == [] and _payloads(events, "decision.shadow") == []


def test_the_shadow_of_a_prior_match_makes_no_gemini_run(seam, monkeypatch, events):
    from agents.grader import GradeResult

    monkeypatch.setenv("DECISION_BACKEND_MATCH_WRONG_REASON", "shadow_jev")
    _scripted_jev(monkeypatch, seam, {"q": ("w_speed", 0.8, {})})
    prior = GradeResult(confidence=0.9, matched_wrong_key="w_speed", backend="gemini")
    cm, runs = _gemini(choice="w_loop")
    with cm:
        v = _run(lambda: seam.match_wrong_reason(_wrong(seam), deps=_deps(), prior=prior))
    assert (v.backend, v.value) == ("gemini", "w_speed") and runs == []
    [shadow] = _payloads(events, "decision.shadow")
    assert (shadow["primary_value"], shadow["shadow_value"], shadow["agreement"]) == ("w_speed", "w_speed", True)


def test_the_shadow_in_flight_cap_skips_rather_than_queues(seam, monkeypatch, caplog):
    monkeypatch.setattr(seam, "JEV_SHADOW_MAX_INFLIGHT", 0)
    monkeypatch.setenv("DECISION_BACKEND_JUDGE_LEAK", "shadow_jev")
    calls = _scripted_jev(monkeypatch, seam, {"q": ("no", 0.9, {})})
    cm, _ = _gemini("no", 0.8)
    with cm, caplog.at_level("WARNING"):
        _run(lambda: seam.judge_leak(_leak(seam), deps=_deps()))
    assert calls == [] and any("shadow skipped" in r.getMessage() for r in caplog.records)


# ── the kill switch and the function lane ───────────────────────────────────


@pytest.mark.parametrize("backend", ["jev", "shadow_jev"])
def test_jev_disabled_never_calls_jev(seam, monkeypatch, events, backend):
    monkeypatch.setattr(seam, "JEV_ENABLED", False)
    monkeypatch.setenv("DECISION_BACKEND_JUDGE_LEAK", backend)
    calls = _scripted_jev(monkeypatch, seam, {"q": ("no", 0.9, {})})
    cm, runs = _gemini("no", 0.8)
    with cm:
        v = _run(lambda: seam.judge_leak(_leak(seam), deps=_deps()))
    assert (v.backend, v.fallback) == ("gemini", False) and calls == [] and len(runs) == 1
    assert _payloads(events, "decision.shadow") == []


@pytest.mark.parametrize("backend", ["jev", "shadow_jev"])
def test_function_mode_never_reaches_jev(seam, monkeypatch, backend):
    from agents._providers import clear_function_handlers

    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv("DECISION_BACKEND_JUDGE_LEAK", backend)
    calls = _scripted_jev(monkeypatch, seam, {"q": ("no", 0.9, {})})
    assert seam.select_backend("judge_leak").served == "function"
    cm, _ = _gemini("no", 0.8)
    with cm:
        v = _run(lambda: seam.judge_leak(_leak(seam), deps=_deps()))
    clear_function_handlers()
    assert calls == [] and v.backend == "function"


# ── the wire: what Typesafe sees (no PII) ────────────────────────────────────


def test_the_wire_carries_the_state_text_and_nothing_that_identifies_anyone(seam, monkeypatch):
    seen: list[httpx2.Request] = []

    def handler(request):
        seen.append(request)
        body = json.loads(request.content)
        name = next(iter(body["questions"]))
        return httpx2.Response(
            200,
            json={
                "model": "jev-1.13.0",
                "answers": {name: {"type": "choice", "choice": "w_speed", "confidence": 0.9, "probabilities": {"w_speed": 0.9}}},
                "usage": {"input_tokens": 99, "output_tokens": 1},
            },
        )

    monkeypatch.setattr(_jev, "_transport_override", httpx2.MockTransport(handler))
    _jev.reset_for_tests()
    monkeypatch.setenv("DECISION_BACKEND_MATCH_WRONG_REASON", "jev")
    v = _run(lambda: seam.match_wrong_reason(_wrong(seam), deps=_deps()))
    assert (v.backend, v.value) == ("jev", "w_speed")
    [req] = seen
    raw = req.content.decode() + json.dumps(dict(req.headers))
    for ident in ("user-zz9", "req-zz9", "sess-zz9", "course-zz9"):
        assert ident not in raw
    body = json.loads(req.content)
    assert set(body) == {"state", "model", "questions"} and body["model"] == "jev-1.13.0"
    assert body["state"] == {"question": QUESTION, "student_answer": ANSWER}


def test_every_shadowable_decision_has_a_jev_request(seam):
    states = {
        "grade_rubric_items": seam.GradeState(question=QUESTION, reference=REFERENCE, rubric=RUBRIC, wrong=WRONG, answer=ANSWER, format="free"),
        "reason_is_correct": seam.ReasonState(question=QUESTION, reference=REFERENCE, rubric=RUBRIC, wrong=WRONG, selected_option="B", correct_option="A", reason=ANSWER),
        "match_wrong_reason": _wrong(seam),
        "item_answerable": seam.AnswerableState(passages=["p1", "p2"], question=QUESTION, reference=REFERENCE),
        "judge_leak": _leak(seam),
    }
    assert set(states) == seam.JEV_SHADOWABLE
    assert seam.JEV_SERVABLE == {"match_wrong_reason", "item_answerable", "judge_leak"}
    for decision, state in states.items():
        payload, questions, _ = seam.jev_request(decision, state)
        assert questions and all(isinstance(q, _jev.Question) for q in questions.values())
        assert all(isinstance(v, str) for v in payload.values())
    assert seam.select_backend("numeric_gate").shadow is False


# ── §3.6 live gates from a shadow log (tests/evals/decisions.py) ─────────────


@pytest.fixture(scope="module")
def ev():
    import importlib.util
    import pathlib
    import sys

    saved = list(sys.path)
    try:
        path = pathlib.Path(__file__).resolve().parent / "evals" / "decisions.py"
        spec = importlib.util.spec_from_file_location("decisions_eval_jev", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path[:] = saved
    return mod


def _shadow_row(i, *, decision="judge_leak", agree=True, ms=120, code=None, tokens=300, day=0):
    from datetime import datetime, timedelta, timezone

    at = datetime(2026, 10, 1, tzinfo=timezone.utc) + timedelta(days=day, minutes=i)
    return {
        "event_type": "decision.shadow",
        "created_at": at.isoformat(),
        "payload": {
            "decision": decision,
            "request_id": f"rq{i}",
            "primary_value": "no",
            "shadow_value": None if code else ("no" if agree else "yes"),
            "primary_confidence": 0.8,
            "shadow_confidence": 0.0 if code else 0.9,
            "agreement": bool(agree and not code),
            "shadow_latency_ms": ms,
            "shadow_input_tokens": 0 if code else tokens,
            "error_code": code,
        },
    }


def test_shadow_stats_compute_every_live_gate(ev):
    rows = [_shadow_row(i, day=i % 8, agree=i % 20 != 0, ms=100 + i % 50) for i in range(1000)]
    rows += [_shadow_row(1000 + i, code="timeout", ms=800) for i in range(3)]
    rows += [_shadow_row(2000, code="oversize", ms=0), _shadow_row(2001, code="circuit_open", ms=0)]
    rows.append({"event_type": "decision.made", "payload": {"decision": "judge_leak"}})  # ignored
    usage = [
        {"request_id": f"rq{i}", "task": "decision", "provider": "gemini", "cost_usd": 0.00004}
        for i in range(1000)
    ] + [{"request_id": "rq1", "task": "decision_shadow", "provider": "typesafe", "cost_usd": 1.0}]
    [(name, s)] = ev.shadow_stats(rows, usage_rows=usage).items()
    assert name == "judge_leak" and s.n == 1005 and s.days == 7
    assert s.agreement == pytest.approx(950 / 1000)  # over the answered rows only
    assert s.error_rate == pytest.approx(4 / 1005)  # 3 timeouts + the open circuit; oversize is routing
    assert s.p95_ms == pytest.approx(147.0)  # no-call rows (oversize, circuit_open) excluded
    assert s.cost_per_decision_usd == pytest.approx(1000 * 300 / 1005 * 0.000042 / 1000)
    assert s.gemini_cost_per_decision_usd == pytest.approx(1000 * 0.00004 / 1005)
    assert ev.live_gates(s) == {
        "DECISION_SHADOW_MIN_DAYS": True,
        "DECISION_SHADOW_MIN_N": True,
        "DECISION_SHADOW_MIN_AGREEMENT": True,
        "DECISION_P95_MS": True,
        "DECISION_MAX_ERROR_RATE": True,
        "cost_not_worse": True,
    }


def test_shadow_gates_fail_closed(ev):
    short = [_shadow_row(i, ms=900, agree=i % 2 == 0) for i in range(10)]
    [s] = ev.shadow_stats(short).values()  # no usage rows: the cost gate cannot pass
    gates = ev.live_gates(s)
    assert gates["DECISION_SHADOW_MIN_DAYS"] is False and gates["DECISION_SHADOW_MIN_N"] is False
    assert gates["DECISION_SHADOW_MIN_AGREEMENT"] is False and gates["DECISION_P95_MS"] is False
    assert gates["cost_not_worse"] is False


def test_shadow_report_cli_reads_jsonl_and_exits_on_the_gates(ev, tmp_path, capsys):
    log = tmp_path / "shadow.jsonl"
    log.write_text("\n".join(json.dumps(r) for r in [_shadow_row(i) for i in range(5)]))
    assert ev._shadow_cli(["--shadow-log", str(log)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["judge_leak"]["stats"]["n"] == 5
    assert set(report["judge_leak"]["gates"]) == set(ev.LIVE_GATES)


def test_the_shadow_log_carries_no_text_so_the_report_needs_none(ev):
    row = _shadow_row(0)["payload"]
    assert set(row) == {
        "decision",
        "request_id",
        "primary_value",
        "shadow_value",
        "primary_confidence",
        "shadow_confidence",
        "agreement",
        "shadow_latency_ms",
        "shadow_input_tokens",
        "error_code",
    }


# ── review fix round (PKG-15 R1): budget accounting ─────────────────────────


def _now_rows(task, n, *, tokens=500, cost=0.00002):
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    return now, [
        {"created_at": (now - timedelta(seconds=5)).isoformat(), "task": task, "cost_usd": cost, "total_tokens": tokens}
        for _ in range(n)
    ]


@pytest.mark.parametrize("task", ["decision_shadow", "decision_jev_extra"])
def test_uncounted_jev_rows_never_rate_limit_or_spend_the_token_cap(task):
    """M2 (the reviewer's probe_rate.py): shadow rows (and a served Jev run that does not
    stand in for a Gemini decision) count in $ only — never toward the per-minute rate
    limit, the daily token cap or STUDENT_DAILY_GRADES (spec §13 A98 (d))."""
    from decimal import Decimal

    from services import ai_budget

    now, rows = _now_rows(task, 20)
    u = ai_budget._summarise(rows, now)
    assert (u.minute_rows, u.day_tokens, u.day_grades) == (0, 0, 0)
    assert u.day_usd == u.month_usd == Decimal("0.00002") * 20
    assert task in ai_budget.UNCOUNTED_TASKS and task not in ai_budget.GRADE_TASKS


def test_counted_rows_still_count():
    from services import ai_budget

    now, rows = _now_rows("decision", 3)
    u = ai_budget._summarise(rows, now)
    assert (u.minute_rows, u.day_tokens, u.day_grades) == (3, 1500, 3)


def test_a_billed_jev_fallback_counts_one_grade_not_two(seam, monkeypatch, usage):
    """Minor 5: a billed served-Jev fallback (low_confidence) writes its typesafe row as
    decision_jev_extra; only the Gemini run that serves counts as the grade."""
    from services import ai_budget

    monkeypatch.setenv("DECISION_BACKEND_JUDGE_LEAK", "jev")
    _scripted_jev(monkeypatch, seam, {"q": ("yes", 0.2, {})})
    gemini_rows = []
    monkeypatch.setattr(seam, "record_agent_usage", lambda r, **kw: gemini_rows.append(kw) or r)
    cm, runs = _gemini("no", 0.8)
    with cm:
        v = _run(lambda: seam.judge_leak(_leak(seam), deps=_deps()))
    assert (v.backend, v.fallback) == ("gemini", True)
    tasks = [r["task"] for r in usage if r.get("provider") == "typesafe"] + [r["task"] for r in gemini_rows]
    assert tasks == ["decision_jev_extra", "decision"]
    assert sum(t in ai_budget.GRADE_TASKS for t in tasks) == 1


def test_a_served_jev_match_with_a_prior_costs_no_extra_grade(seam, monkeypatch, usage):
    """Minor 5: under gemini the grader's prior answers match_wrong_reason with no run and
    no grade; under jev the Jev call is recorded as decision_jev_extra (not a grade)."""
    from agents.grader import GradeResult
    from services import ai_budget

    monkeypatch.setenv("DECISION_BACKEND_MATCH_WRONG_REASON", "jev")
    _scripted_jev(monkeypatch, seam, {"q": ("w_speed", 0.9, {})})
    prior = GradeResult(confidence=0.9, matched_wrong_key="w_speed", backend="gemini")
    v = _run(lambda: seam.match_wrong_reason(_wrong(seam), deps=_deps(), prior=prior))
    assert v.backend == "jev"
    [row] = [r for r in usage if r.get("provider") == "typesafe"]
    assert row["task"] == "decision_jev_extra" and row["task"] not in ai_budget.GRADE_TASKS


def test_a_served_jev_decision_without_a_prior_is_one_grade(seam, monkeypatch, usage):
    monkeypatch.setenv("DECISION_BACKEND_JUDGE_LEAK", "jev")
    _scripted_jev(monkeypatch, seam, {"q": ("no", 0.9, {})})
    _run(lambda: seam.judge_leak(_leak(seam), deps=_deps()))
    assert [r["task"] for r in usage if r.get("provider") == "typesafe"] == ["decision"]


# ── review fix round: no shadow event is dropped for a non-enum key ──────────


def test_a_raw_wrong_key_is_normalised_to_its_shown_alias(seam, monkeypatch, events):
    """Minor 9: an item key outside the event enum ("Speed Key") is reported as the
    option alias the model was shown (k2), on both sides, so the event is never dropped."""
    from agents.grader import GradeResult

    monkeypatch.setenv("DECISION_BACKEND_MATCH_WRONG_REASON", "shadow_jev")
    wrong = {"w_loop": WRONG["w_loop"], "Speed Key": WRONG["w_speed"]}
    _scripted_jev(monkeypatch, seam, {"q": ("k2", 0.9, {})})
    prior = GradeResult(confidence=0.9, matched_wrong_key="Speed Key", backend="gemini")
    state = seam.WrongReasonState(question=QUESTION, answer=ANSWER, wrong=wrong)
    v = _run(lambda: seam.match_wrong_reason(state, deps=_deps(), prior=prior))
    assert v.value == "Speed Key"  # the served value is the real key
    [shadow] = _payloads(events, "decision.shadow")
    assert (shadow["primary_value"], shadow["shadow_value"], shadow["agreement"]) == ("k2", "k2", True)


def test_a_closed_privacy_gate_skips_shadows_and_falls_back_served(seam, monkeypatch, events):
    """Minor 3: in production/staging without JEV_PRIVACY_GATE_RECORDED=true, a shadow is
    not scheduled at all and a served jev decision falls back with reason privacy_gate."""
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("JEV_PRIVACY_GATE_RECORDED", raising=False)
    seen = []

    def handler(request):
        seen.append(request)
        return httpx2.Response(500)

    monkeypatch.setattr(_jev, "_transport_override", httpx2.MockTransport(handler))
    _jev.reset_for_tests()
    cm, _ = _gemini("no", 0.8)
    with cm:
        monkeypatch.setenv("DECISION_BACKEND_JUDGE_LEAK", "shadow_jev")
        _run(lambda: seam.judge_leak(_leak(seam), deps=_deps()))
        assert _payloads(events, "decision.shadow") == []
        monkeypatch.setenv("DECISION_BACKEND_JUDGE_LEAK", "jev")
        v = _run(lambda: seam.judge_leak(_leak(seam), deps=_deps()))
    assert (v.backend, v.fallback) == ("gemini", True) and seen == []
    assert [p["reason"] for p in _payloads(events, "decision.fallback")] == ["privacy_gate"]


# ── review fix round: shutdown (minor 7) ────────────────────────────────────


def test_shutdown_drains_bounded_records_finished_rows_and_logs_the_dropped(seam, monkeypatch, usage, caplog):
    monkeypatch.setenv("DECISION_BACKEND_JUDGE_LEAK", "shadow_jev")
    gate = {"n": 0}

    async def ask(payload, questions):
        gate["n"] += 1
        if gate["n"] == 2:
            await asyncio.sleep(30)  # still in flight at shutdown
        return _jev.Result(
            answers={"q": _jev.Answer("no", 0.9, {})}, model="jev-1.13.0", input_tokens=99, output_tokens=1, latency_ms=5
        )

    monkeypatch.setattr(_jev, "ask", ask)
    cm, _ = _gemini("no", 0.8)

    async def main():
        await seam.judge_leak(_leak(seam), deps=_deps())
        await seam.judge_leak(_leak(seam), deps=_deps())
        return await seam.shutdown_shadows(timeout_s=0.1)

    with cm, caplog.at_level("WARNING"):
        dropped = asyncio.run(main())
    assert dropped == 1
    assert [r["task"] for r in usage if r.get("provider") == "typesafe"] == ["decision_shadow"]
    assert any("1 decision shadow(s) dropped at shutdown" in r.getMessage() for r in caplog.records)


def test_the_lifespan_drains_shadows_and_closes_jev_before_the_event_flush():
    import ast
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[1] / "main.py").read_text()
    fn = next(
        n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.AsyncFunctionDef) and n.name == "_lifespan"
    )
    body = ast.unparse(fn)
    after = body[body.index("yield") :]
    assert "shutdown_shadows(" in after and "aclose_clients(" in after
    assert after.index("shutdown_shadows(") < after.index("aclose_clients(") < after.index("events_service.shutdown()")


def test_aclose_clients_closes_this_loops_client(monkeypatch):
    monkeypatch.delenv("SAPLING_MODEL_MODE", raising=False)
    from services import decisions

    monkeypatch.setattr(decisions, "JEV_ENABLED", True)
    monkeypatch.setenv(_jev.API_KEY_ENV, "ts-test-key")
    closed = []

    class _C:
        def __init__(self, **kw):
            pass

        async def aclose(self):
            closed.append(1)

    monkeypatch.setattr(_jev, "_client_class_override", _C)

    async def main():
        _jev._client()
        await _jev.aclose_clients()

    asyncio.run(main())
    assert closed == [1] and _jev._clients == {}
