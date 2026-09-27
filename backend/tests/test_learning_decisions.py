"""PKG-05b: the typed decision seam (spec §3.6, §6, §8.24–25, §13 A24). Hermetic:
FunctionModel for the decision agent; the grader stubbed at agents.grader.grade;
events captured by patching events_service.log_event. No DB, no network."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import pathlib
import re
import sys

import httpx
import pytest
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior, UsageLimitExceeded
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RequestUsage

from agents.deps import SaplingDeps

BACKEND = pathlib.Path(__file__).resolve().parents[1]
QUESTION = "Why does every recursive function need a base case?"
REFERENCE = "The base case stops the recursion; without it the stack grows until overflow."
RUBRIC = {"r1": "names the base case", "r2": "explains unbounded growth"}
WRONG = {
    "w_loop": "confuses recursion with a loop",
    "w_speed": "says the base case is only for speed",
}


def _deps(**over) -> SaplingDeps:
    kw = dict(
        user_id="u1",
        course_id="c1",
        supabase=None,
        request_id="r1",
        session_id="s1",
        feature="tutor",
        learning_loop=True,
    )
    return SaplingDeps(**{**kw, **over})


def _scripted(outputs: list[dict]):
    """FunctionModel emitting each dict in turn through the run's output tool."""
    calls = {"n": 0, "prompts": []}

    def handler(messages, info):
        calls["prompts"].append(messages[-1].parts[-1].content)
        payload = outputs[min(calls["n"], len(outputs) - 1)]
        calls["n"] += 1
        return ModelResponse(
            parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=payload)]
        )

    return FunctionModel(handler), calls


@pytest.fixture
def events(monkeypatch):
    from services import events_service

    got: list[tuple[str, dict]] = []
    monkeypatch.setattr(events_service, "log_event", lambda et, **kw: got.append((et, kw)))
    return got


def _kinds(events) -> list[str]:
    return [et for et, _ in events]


@pytest.fixture
def _function_lane(monkeypatch):
    """Cold seam, env-module lane (the test_e2e_function_handlers posture)."""
    import agents._providers as providers

    providers.clear_function_handlers()
    monkeypatch.setattr(providers, "_ENV_HANDLERS_LOADED", False)
    sys.modules.pop("agents.function_handlers_e2e", None)
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    monkeypatch.setenv("SAPLING_FUNCTION_HANDLERS", "agents.function_handlers_e2e")
    yield
    providers.clear_function_handlers()
    sys.modules.pop("agents.function_handlers_e2e", None)


# ── Task 2: decision agent, slot, function handler ─────────────────────────


def test_decision_slot_is_flash_lite_thinking_off_one_prompt(monkeypatch):
    from agents import decision as d
    from agents._providers import _DEFAULTS, model_name_for

    monkeypatch.delenv("SAPLING_MODEL_DECISION", raising=False)
    assert _DEFAULTS["decision"] == model_name_for("decision") == "gemini-2.5-flash-lite"
    assert d.decision_agent.model_settings["google_thinking_config"].thinking_budget == 0
    src = (BACKEND / "agents" / "decision.py").read_text()
    assert src.count("_SYSTEM_PROMPT = ") == 1 and len(re.findall(r"\bAgent[\[(]", src)) == 1
    text = d.build_decision_message(
        "Which?", [("STUDENT ANSWER", "a loop")], [("w_loop", "l"), ("w_speed", "s")]
    )
    assert text.startswith("QUESTION: Which?") and "\nSTATE:\nSTUDENT ANSWER:\na loop" in text
    assert re.findall(r"^OPTION (\S+):", text, re.M) == ["w_loop", "w_speed"]


def test_e2e_decision_handler_serves_both_output_types(_function_lane):
    from agents._providers import model_for
    from agents.decision import DecisionPickOutput, build_decision_message, decision_agent
    from agents.function_handlers_e2e import E2E_DECISION_CONFIDENCE, E2E_DECISION_YES_TOKEN

    opts = [("w_loop", "loop"), ("w_speed", "speed")]
    hit = build_decision_message(f"Q {E2E_DECISION_YES_TOKEN}", [("S", "x")], opts)
    miss = build_decision_message("Q", [("S", "x")], opts)
    with decision_agent.override(model=model_for("decision")):
        picks = [
            decision_agent.run_sync(m, deps=_deps(), output_type=DecisionPickOutput).output
            for m in (hit, miss)
        ]
        yes, no = (decision_agent.run_sync(m, deps=_deps()).output for m in (hit, miss))
    assert [p.choice for p in picks] == ["w_loop", "none"] and (yes.answer, no.answer) == (
        "yes",
        "no",
    )
    assert yes.confidence == picks[1].confidence == E2E_DECISION_CONFIDENCE


# ── Task 3: services/decisions.py ─────────────────────────────────────────


@pytest.fixture
def seam(monkeypatch, events):
    from services import decisions

    monkeypatch.delenv("SAPLING_MODEL_MODE", raising=False)
    for name in decisions.DECISION_NAMES:
        monkeypatch.delenv(f"DECISION_BACKEND_{name.upper()}", raising=False)
    monkeypatch.setattr(decisions, "JEV_ENABLED", False)
    return decisions


def _grade_result(ok: bool = True, conf: float = 0.9, **over):
    from agents.grader import GradeResult

    kw = dict(
        item_results={"r1": ok, "r2": ok},
        all_yes=ok,
        confidence=conf,
        matched_wrong_key="" if ok else "w_loop",
        feedback_hint="Think about what stops the calls.",
    )
    return GradeResult(**{**kw, **over})


@pytest.fixture
def grader_spy(monkeypatch):
    import agents.grader as g

    spy = {"calls": [], "result": _grade_result()}

    async def _grade(item, *, format, student_answer, deps):
        spy["calls"].append((item, format, student_answer))
        return spy["result"]

    monkeypatch.setattr(g, "grade", _grade)
    return spy


def _gstate(seam):
    return seam.GradeState(
        question=QUESTION,
        reference=REFERENCE,
        rubric=RUBRIC,
        wrong=WRONG,
        answer="It stops the calls.",
        format="free",
    )


async def _must_not_run(*a, **k):
    raise AssertionError("must not run")


@pytest.mark.parametrize("value", [None, "jev", "shadow_jev", "gemini", "JEV", "nonsense"])
def test_jev_disabled_serves_gemini_whatever_the_env(seam, monkeypatch, value):
    if value is not None:
        monkeypatch.setenv("DECISION_BACKEND_MATCH_WRONG_REASON", value)
    sel = seam.select_backend("match_wrong_reason")
    assert (sel.served, sel.fallback_reason, sel.shadow) == ("gemini", None, False)
    monkeypatch.setenv("SAPLING_MODEL_MODE", "function")
    assert seam.select_backend("match_wrong_reason").served == "function"


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, False),
        ("", False),
        ("false", False),
        ("yes", False),
        ("true", True),
        (" TRUE ", True),
    ],
)
def test_jev_enabled_parse_fails_closed(seam, raw, expected):
    assert seam.parse_jev_enabled(raw) is expected


def test_jev_is_served_by_gemini_and_shadow_is_a_noop(seam, monkeypatch, grader_spy, events):
    monkeypatch.setattr(seam, "JEV_ENABLED", True)
    monkeypatch.setenv("DECISION_BACKEND_GRADE_RUBRIC_ITEMS", "jev")
    v = asyncio.run(seam.grade_rubric_items(_gstate(seam), deps=_deps()))
    assert (v.backend, v.fallback) == ("gemini", True)
    assert [kw["payload"] for et, kw in events if et == "decision.fallback"] == [
        {
            "decision": "grade_rubric_items",
            "from_backend": "jev",
            "to_backend": "gemini",
            "reason": "jev_absent",
            "request_id": "r1",
        }
    ]
    events.clear()
    monkeypatch.setenv("DECISION_BACKEND_GRADE_RUBRIC_ITEMS", "shadow_jev")
    v = asyncio.run(seam.grade_rubric_items(_gstate(seam), deps=_deps()))
    assert (v.backend, v.fallback) == ("gemini", False) and _kinds(events) == ["decision.made"]
    assert len(grader_spy["calls"]) == 2


def test_grade_rubric_items_sends_the_grader_the_identical_message(seam, grader_spy, monkeypatch):
    """The grader sees exactly the message it would build from the item itself:
    the State keeps rubric/wrong order, and the rebuilt item carries
    learning.checks models (build_grader_message reads r.id / w.key, HANDOFF-05)."""
    from types import SimpleNamespace

    from agents.grader import build_grader_message
    from learning.checks import RubricItem, WrongReason

    recorded = []
    monkeypatch.setattr(seam, "record_agent_usage", lambda r, **kw: recorded.append(kw) or r)
    item = SimpleNamespace(
        id="ci-1",
        prompt=QUESTION,
        reference_answer=REFERENCE,
        rubric=[RubricItem(id=k, text=v) for k, v in RUBRIC.items()],
        common_wrong=[WrongReason(key=k, text=v) for k, v in WRONG.items()],
    )
    v = asyncio.run(seam.grade_rubric_items(_gstate(seam), deps=_deps(), item_id="ci-1"))
    [(passed, fmt, answer)] = grader_spy["calls"]
    assert (fmt, answer, passed.id) == ("free", "It stops the calls.", "ci-1")
    assert build_grader_message(passed, format=fmt, student_answer=answer) == build_grader_message(
        item, format="free", student_answer="It stops the calls."
    )
    assert v.items["r1"].value is True and v.items["r1"].p_yes == pytest.approx(0.9)
    assert v.result.all_yes is True and v.backend == "gemini"
    assert recorded == [], "grade() writes the llm_usage rows; the seam adds none"


def test_unavailable_grade_is_none_with_both_failed(seam, grader_spy, events):
    from agents.grader import GradeResult

    grader_spy["result"] = GradeResult(unavailable=True)
    assert asyncio.run(seam.grade_rubric_items(_gstate(seam), deps=_deps())) is None
    [(et, kw)] = events
    assert (et, kw["category"]) == ("decision.fallback", "error")
    assert kw["payload"] == {
        "decision": "grade_rubric_items",
        "from_backend": "gemini",
        "to_backend": "none",
        "reason": "both_failed",
        "request_id": "r1",
    }


def test_reason_is_correct_runs_the_grader_as_mc_reason(seam, grader_spy):
    st = seam.ReasonState(
        question=QUESTION,
        reference=REFERENCE,
        rubric=RUBRIC,
        wrong=WRONG,
        selected_option="B",
        correct_option="B",
        reason="because it stops",
    )
    v = asyncio.run(seam.reason_is_correct(st, deps=_deps(), item_id="ci-1"))
    [(_, fmt, answer)] = grader_spy["calls"]
    assert (fmt, answer) == ("mc_reason", "Selected option: B\nReason: because it stops")
    assert v.value is True and v.result.all_yes is True


def test_match_wrong_reason_with_prior_makes_no_call(seam, monkeypatch, events):
    from agents.decision import decision_agent
    from agents.grader import GradeResult

    monkeypatch.setattr(decision_agent, "run", _must_not_run)
    st = seam.WrongReasonState(question=QUESTION, answer="it just loops", wrong=WRONG)
    hit = asyncio.run(
        seam.match_wrong_reason(
            st, deps=_deps(), prior=_grade_result(False, matched_wrong_key="w_loop")
        )
    )
    miss = asyncio.run(
        seam.match_wrong_reason(
            st, deps=_deps(), prior=_grade_result(False, matched_wrong_key="w_new")
        )
    )
    assert (hit.value, miss.value, hit.latency_ms, hit.backend) == (
        "w_loop",
        seam.NO_MATCH,
        0,
        "gemini",
    )
    assert _kinds(events) == ["decision.made", "decision.made"]
    events.clear()
    assert (
        asyncio.run(seam.match_wrong_reason(st, deps=_deps(), prior=GradeResult(unavailable=True)))
        is None
    )
    assert events == []


def test_match_wrong_reason_without_prior_runs_decision_and_never_invents(seam, monkeypatch):
    from agents.decision import decision_agent

    recorded = []
    monkeypatch.setattr(seam, "record_agent_usage", lambda r, **kw: recorded.append(kw) or r)
    st = seam.WrongReasonState(question=QUESTION, answer="it only makes it faster", wrong=WRONG)
    model, calls = _scripted(
        [{"choice": "w_speed", "confidence": 0.8}, {"choice": "w_made_up", "confidence": 0.99}]
    )
    with decision_agent.override(model=model):
        v = asyncio.run(seam.match_wrong_reason(st, deps=_deps()))
        invented = asyncio.run(seam.match_wrong_reason(st, deps=_deps()))
    assert (v.value, v.probs, invented.value) == ("w_speed", {"w_speed": 0.8}, seam.NO_MATCH)
    assert re.findall(r"^OPTION (\S+):", calls["prompts"][0], re.M) == ["w_loop", "w_speed"]
    assert recorded[0] == {"feature": "tutor", "task": "decision", "user_id": "u1"}


@pytest.mark.parametrize(
    "answer,value,p_yes", [("yes", True, 0.8), ("no", False, 0.2), ("unclear", False, None)]
)
def test_yes_no_decisions_map_answers(seam, answer, value, p_yes):
    from agents.decision import decision_agent

    model, calls = _scripted([{"answer": answer, "confidence": 0.8}])
    leak = seam.LeakState(reference=REFERENCE, emitted="Once it stops, the calls end.", rung=1)
    ok = seam.AnswerableState(
        passages=["A base case ends recursion."], question=QUESTION, reference=REFERENCE
    )
    with decision_agent.override(model=model):
        verdicts = [
            asyncio.run(seam.judge_leak(leak, deps=_deps())),
            asyncio.run(seam.item_answerable(ok, deps=_deps())),
        ]
    for v in verdicts:
        assert v.value is value and v.backend == "gemini"
        assert v.p_yes == pytest.approx(seam.P_YES_UNCLEAR if p_yes is None else p_yes)
    assert "HINT RUNG:\nH1" in calls["prompts"][0] and "PASSAGE 1:" in calls["prompts"][1]


@pytest.mark.parametrize(
    "exc",
    [
        UsageLimitExceeded("budget"),
        UnexpectedModelBehavior("garbage"),
        # The provider itself: the same set agents.grader.grade() degrades on
        # (a 503/429 outage, and the raw httpx errors google-genai re-raises).
        ModelHTTPError(status_code=503, model_name="gemini-2.5-flash-lite", body="overloaded"),
        httpx.ReadTimeout("read timed out"),
        httpx.ConnectError("connection refused"),
    ],
)
def test_decision_agent_failure_degrades_to_none(seam, monkeypatch, caplog, events, exc):
    from agents.decision import decision_agent

    async def _boom(*a, **k):
        raise exc

    monkeypatch.setattr(decision_agent, "run", _boom)
    rows = _llm_usage_rows(monkeypatch)
    with caplog.at_level("WARNING"):
        state = seam.LeakState(reference=REFERENCE, emitted="x", rung=1)
        assert asyncio.run(seam.judge_leak(state, deps=_deps())) is None
    assert any("decision unavailable" in r.getMessage() for r in caplog.records)
    assert [kw["payload"]["reason"] for _, kw in events] == ["both_failed"]
    assert rows == []  # no response → nothing was billed


def _llm_usage_rows(monkeypatch) -> list[dict]:
    """Spy one level BELOW record_agent_usage: what reaches the llm_usage writer."""
    from services import events_service

    rows: list[dict] = []
    monkeypatch.setattr(events_service, "log_llm_usage", lambda **kw: rows.append(kw))
    return rows


def _billed(payload: dict, usage: RequestUsage | None = None):
    """A FunctionModel emitting `payload` on every request, each billed `usage`
    (None: the FunctionModel estimate)."""
    calls = {"n": 0}

    def handler(messages, info):
        calls["n"] += 1
        response = ModelResponse(
            parts=[ToolCallPart(tool_name=info.output_tools[0].name, args=payload)]
        )
        if usage is not None:
            response.usage = usage
        return response

    return FunctionModel(handler), calls


def test_a_decision_run_over_the_token_cap_still_records_what_it_billed(seam, monkeypatch):
    """GRADER_LIMITS' token cap is checked AFTER the response, so the provider has
    billed it. The §3.5 caps (STUDENT_DAILY_GRADES counts task='decision') and the
    admin cost analytics read llm_usage only (the agents.grader._run_once posture)."""
    from agents import GRADER_LIMITS
    from agents.decision import decision_agent

    over = RequestUsage(input_tokens=GRADER_LIMITS.total_tokens_limit + 1, output_tokens=7)
    model, calls = _billed({"answer": "yes", "confidence": 0.9}, over)
    rows = _llm_usage_rows(monkeypatch)
    with decision_agent.override(model=model):
        state = seam.LeakState(reference=REFERENCE, emitted="x", rung=1)
        assert asyncio.run(seam.judge_leak(state, deps=_deps())) is None
    assert calls["n"] == 1
    [row] = rows
    assert (row["task"], row["feature"], row["user_id"]) == ("decision", "tutor", "u1")
    assert row["usage"].requests == 1 and row["usage"].input_tokens == over.input_tokens


def test_exhausted_decision_retries_record_every_billed_request(seam, monkeypatch):
    from agents import GRADER_LIMITS
    from agents.decision import decision_agent

    model, calls = _billed({"answer": "maybe", "confidence": 7})
    rows = _llm_usage_rows(monkeypatch)
    with decision_agent.override(model=model):
        state = seam.LeakState(reference=REFERENCE, emitted="x", rung=1)
        assert asyncio.run(seam.judge_leak(state, deps=_deps())) is None
    assert calls["n"] == GRADER_LIMITS.request_limit
    [row] = rows
    assert row["task"] == "decision" and row["usage"].requests == calls["n"]
    assert row["usage"].total_tokens > 0


def test_deterministic_and_evidence_backend(seam, events):
    v = seam.deterministic_yes_no("numeric_gate", False, deps=_deps())
    assert (v.backend, v.value, v.confidence, v.latency_ms) == ("deterministic", False, 1.0, 0)
    assert seam.evidence_backend(v) == "deterministic"
    with pytest.raises(ValueError):
        seam.deterministic_yes_no("numeric_gate", True, deps=_deps())
    g = seam.YesNo(backend="gemini", confidence=0.9, latency_ms=5, value=True, p_yes=0.9)
    assert (
        seam.evidence_backend(g)
        == seam.evidence_backend(g.model_copy(update={"backend": "function"}))
        == "gemini"
    )
    assert seam.evidence_backend(g, second_opinion=True) == "gemini_second"
    assert _kinds(events) == ["decision.made"]


def test_spec_3_6_settings_and_ownership(seam):
    names = (
        "JEV_MODEL JEV_SDK_VERSION JEV_TIMEOUT_MS JEV_MAX_RETRIES JEV_CIRCUIT_FAILS "
        "JEV_CIRCUIT_COOLDOWN_S JEV_STATE_MAX_TOKENS DECISION_PROMOTE_MIN_GOLD "
        "DECISION_PROMOTE_MAX_ACC_DROP GRADER_PROMOTE_MIN_KAPPA DECISION_PROMOTE_MAX_ECE "
        "SHARE_FALSE_POSITIVE_MAX GRADER_BKT_REPLAY_MAX_DELTA DECISION_SHADOW_MIN_DAYS "
        "DECISION_SHADOW_MIN_N DECISION_SHADOW_MIN_AGREEMENT DECISION_P95_MS "
        "DECISION_MAX_ERROR_RATE"
    ).split()
    assert [getattr(seam, n) for n in names] == [
        "jev-1.13.0",
        "typesafe-sdk==0.7.2",
        800,
        1,
        5,
        300,
        28_000,
        200,
        0.02,
        0.70,
        0.05,
        0.01,
        0.02,
        7,
        1000,
        0.90,
        300,
        0.005,
    ]
    assert not any(
        hasattr(seam, n) for n in ("classify_upload", "rerank", "route_turn")
    )  # #641/#640
    for path in (BACKEND / "learning").rglob("*.py"):
        rel = path.relative_to(BACKEND).as_posix()
        assert not _seam_refs(path.read_text(), rel), rel


# ── Task 4: decision.* events ──────────────────────────────────────────────


def _app_files():
    for top in sorted(BACKEND.iterdir()):
        if top.name not in {"venv", ".venv", "tests", "__pycache__"}:
            yield from (
                [top] if top.suffix == ".py" else sorted(top.rglob("*.py")) if top.is_dir() else []
            )


def test_decision_events_are_in_the_taxonomy():
    from services.events_service import EVENT_TAXONOMY

    assert {"decision.made", "decision.shadow", "decision.fallback"} <= EVENT_TAXONOMY


def test_decision_made_payload_is_ids_enums_numbers(seam, grader_spy, events):
    asyncio.run(seam.grade_rubric_items(_gstate(seam), deps=_deps()))
    [(et, kw)] = events
    assert (et, kw["category"], kw["user_id"]) == ("decision.made", "usage", "u1")
    p = kw["payload"]
    assert set(p) == {"decision", "backend", "request_id", "latency_ms", "confidence", "fallback"}
    assert (p["decision"], p["backend"], p["fallback"]) == ("grade_rubric_items", "gemini", False)
    assert isinstance(p["latency_ms"], int)
    assert all(not isinstance(v, str) or len(v) <= seam.EVENT_ENUM_MAX_CHARS for v in p.values())
    assert not any(t in json.dumps(kw) for t in (QUESTION, REFERENCE, "It stops the calls."))


def test_emit_shadow_payload_refuses_text_and_has_no_caller(seam, events, caplog):
    shadow = dict(
        primary_value="w_loop",
        shadow_value="none",
        primary_confidence=0.8,
        shadow_confidence=0.6,
        agreement=False,
        shadow_latency_ms=90,
        shadow_input_tokens=300,
    )
    seam.emit_shadow("match_wrong_reason", deps=_deps(), **shadow)
    [(et, kw)] = events
    assert (et, kw["category"]) == ("decision.shadow", "usage")
    assert set(kw["payload"]) == {"decision", "request_id", "error_code", *shadow}
    with caplog.at_level("WARNING"):
        seam.emit_shadow(
            "match_wrong_reason",
            deps=_deps(),
            **{**shadow, "primary_value": "it just loops forever"},
        )
    assert len(events) == 1 and any(
        "decision.shadow dropped" in r.getMessage() for r in caplog.records
    )
    assert [
        p.relative_to(BACKEND).as_posix() for p in _app_files() if "emit_shadow(" in p.read_text()
    ] == ["services/decisions.py"]
    assert (BACKEND / "services" / "decisions.py").read_text().count("emit_shadow(") == 1


# ── Task 5: grade_answer through the seam (PKG-05 reopened) ───────────────
NODE = "node-recursion"  # grade_answer's node_id (the caller resolves it from item.concept_key, A2)


def _pkg05(name: str, **over):
    """PKG-05's own helpers (_item/_answer/_deps; names per Read-before (f)) — the exact
    shapes grade_answer was built against."""
    import tests.test_learning_check_tool as t

    return getattr(t, name)(**over)


def _rubric_verdict(seam, ok=True, second=False):
    result = _grade_result(
        ok, backend="gemini_second" if second else "gemini"
    )  # GradeResult.backend (b)
    items = {
        rid: seam.YesNo(
            backend="gemini", confidence=0.9, latency_ms=1, value=v, p_yes=0.9 if v else 0.1
        )
        for rid, v in result.item_results.items()
    }
    return seam.RubricVerdict(
        backend="gemini", confidence=0.9, latency_ms=1, items=items, result=result
    )


@pytest.mark.parametrize("second,expected", [(False, "gemini"), (True, "gemini_second")])
def test_grade_answer_free_goes_through_grade_rubric_items(seam, monkeypatch, second, expected):
    import agents.tools.check as c

    calls = []

    async def _spy(state, *, deps, item_id="-"):
        calls.append((state, item_id))
        return _rubric_verdict(seam, True, second)

    monkeypatch.setattr(seam, "grade_rubric_items", _spy)
    monkeypatch.setattr(seam, "reason_is_correct", _must_not_run)
    item, deps = _pkg05("_item", format="free"), _pkg05("_deps")
    out = asyncio.run(c.grade_answer(item, _pkg05("_answer"), deps=deps, node_id=NODE))
    [(state, item_id)] = calls
    assert (state.question, state.format, item_id) == (item.prompt, "free", item.id)
    assert (out.unavailable, out.correct, out.grader_backend) == (False, True, expected)
    assert deps.pending_evidence[-1]["grader_backend"] == expected


def test_grade_answer_mc_reason_goes_through_reason_is_correct(seam, monkeypatch):
    import agents.tools.check as c

    calls = []

    async def _spy(state, *, deps, item_id="-"):
        calls.append(state)
        return seam.ReasonVerdict(
            backend="gemini",
            confidence=0.9,
            latency_ms=1,
            value=True,
            p_yes=0.9,
            result=_grade_result(True, backend="gemini"),
        )

    monkeypatch.setattr(seam, "reason_is_correct", _spy)
    monkeypatch.setattr(seam, "grade_rubric_items", _must_not_run)
    out = asyncio.run(
        c.grade_answer(
            _pkg05("_item", format="mc_reason", correct_option="B"),
            _pkg05("_answer", selected_option="B", reason="because it stops"),
            deps=_pkg05("_deps"),
            node_id=NODE,
        )
    )
    assert (calls[0].selected_option, calls[0].correct_option, calls[0].reason) == (
        "B",
        "B",
        "because it stops",
    )
    assert (out.correct, out.grader_backend) == (True, "gemini")


def test_grade_answer_unavailable_or_loop_off_writes_nothing(seam, monkeypatch, events):
    import agents.tools.check as c

    async def _none(*a, **k):
        return None

    monkeypatch.setattr(seam, "grade_rubric_items", _none)
    deps = _pkg05("_deps")
    out = asyncio.run(
        c.grade_answer(_pkg05("_item", format="free"), _pkg05("_answer"), deps=deps, node_id=NODE)
    )
    assert out.unavailable is True and out.evidence is None and deps.pending_evidence == []
    monkeypatch.setattr(seam, "grade_rubric_items", _must_not_run)
    off = asyncio.run(
        c.grade_answer(
            _pkg05("_item", format="free"),
            _pkg05("_answer"),
            deps=_pkg05("_deps", learning_loop=False),
            node_id=NODE,
        )
    )
    assert off.unavailable is True and events == []


def test_grade_answer_sends_the_grader_the_same_messages(seam, monkeypatch):
    """Byte-identity (A24): through the seam the grader receives exactly the message
    PKG-05 built directly — same item fields, format and answer."""
    import agents.grader as g
    import agents.tools.check as c

    seen = []

    async def _grade(item, *, format, student_answer, deps):
        seen.append(g.build_grader_message(item, format=format, student_answer=student_answer))
        return _grade_result(True, backend="gemini")

    monkeypatch.setattr(g, "grade", _grade)
    free_item, free_answer = _pkg05("_item", format="free"), _pkg05("_answer")
    mc_item = _pkg05("_item", format="mc_reason", correct_option="B")
    asyncio.run(c.grade_answer(free_item, free_answer, deps=_pkg05("_deps"), node_id=NODE))
    asyncio.run(
        c.grade_answer(
            mc_item,
            _pkg05("_answer", selected_option="B", reason="because it stops"),
            deps=_pkg05("_deps"),
            node_id=NODE,
        )
    )
    assert seen == [
        g.build_grader_message(free_item, format="free", student_answer=free_answer.answer_text),
        g.build_grader_message(
            mc_item,
            format="mc_reason",
            student_answer="Selected option: B\nReason: because it stops",
        ),
    ]


def test_grade_answer_numeric_mismatch_is_stamped_deterministic(seam, monkeypatch, events):
    """A22 as amended: the rubric grade runs FIRST for both numeric outcomes (invariant 28);
    a clear mismatch against the verified key then overrides the verdict."""
    import agents.tools.check as c

    calls = []

    async def _spy(state, *, deps, item_id="-"):
        calls.append(state)
        return _rubric_verdict(seam, True, False)  # the rubric grade said yes

    monkeypatch.setattr(seam, "grade_rubric_items", _spy)
    item = _pkg05(
        "_item",
        format="free",
        answer_kind="numeric",
        canonical_answer="42",
        tolerance=None,
        canonical_verified=True,
    )
    out = asyncio.run(
        c.grade_answer(
            item, _pkg05("_answer", answer_text="17"), deps=_pkg05("_deps"), node_id=NODE
        )
    )
    assert len(calls) == 1
    assert (out.correct, out.grader_backend) == (False, "deterministic")
    assert [(et, kw["payload"]["backend"]) for et, kw in events] == [
        ("decision.made", "deterministic")
    ]


SEAM_MODULE = "services.decisions"


def _absolute(module: str | None, level: int, rel: str) -> str:
    """The absolute module an ImportFrom names, resolving a relative one against `rel`."""
    if not level:
        return module or ""
    package = rel.removesuffix(".py").split("/")[:-1]
    base = package[: len(package) - (level - 1)] if level - 1 <= len(package) else []
    return ".".join([*base, *([module] if module else [])])


def _seam_refs(source: str, rel: str = "") -> list[tuple[int, str]]:
    """(line, what) for each import of services.decisions in `source` (the file at
    backend-relative `rel`): any spelling — a multi-name or parenthesized
    `from services import …`, `import services.decisions`, a relative import from
    inside services/, or a dynamic import by name. Comments and prose never count
    (the PKG-05 `_grading_refs` shape)."""
    import ast

    refs: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            refs += [
                (node.lineno, f"import {a.name}")
                for a in node.names
                if a.name == SEAM_MODULE or a.name.startswith(SEAM_MODULE + ".")
            ]
        elif isinstance(node, ast.ImportFrom):
            module = _absolute(node.module, node.level, rel)
            names = {a.name for a in node.names}
            targets = {module} | {f"{module}.{n}" for n in names}
            if any(t == SEAM_MODULE or t.startswith(SEAM_MODULE + ".") for t in targets):
                refs.append((node.lineno, f"from {'.' * node.level}{node.module or ''} import"))
        elif isinstance(node, ast.Constant) and node.value == SEAM_MODULE:
            refs.append((node.lineno, f"names {node.value!r}"))
    return refs


@pytest.mark.parametrize(
    ("source", "rel", "hits"),
    [
        ("from services import decisions", "", 1),
        ("from services.decisions import judge_leak", "", 1),
        ("import services.decisions as seam", "", 1),
        ("from services import events_service, decisions", "", 1),
        ("from services import (\n    events_service,\n    decisions,\n)", "", 1),
        ("import importlib\nimportlib.import_module('services.decisions')", "", 1),
        ("from . import decisions", "services/x.py", 1),
        ("from .decisions import judge_leak", "services/x.py", 1),
        ("from .. import decisions", "agents/tools/x.py", 0),
        ("# the route calls services.decisions.judge_leak", "", 0),
        ('"""Read services/decisions.py::item_answerable."""', "", 0),
        ("from services import events_service\nfrom agents import decision", "", 0),
    ],
)
def test_seam_ref_detector(source, rel, hits):
    """Mutation cases for the flag-dark importer scan below."""
    assert len(_seam_refs(source, rel)) == hits, _seam_refs(source, rel)


def test_seam_callers_are_only_grade_answer():
    importers = sorted(
        p.relative_to(BACKEND).as_posix()
        for p in _app_files()
        if _seam_refs(p.read_text(), p.relative_to(BACKEND).as_posix())
    )
    assert importers == ["agents/tools/check.py"]


# ── Task 6: eval harness (gold loaders + §3.6 gates) ──────────────────────


@pytest.fixture(scope="module")
def ev():
    saved = list(sys.path)
    try:
        spec = importlib.util.spec_from_file_location(
            "decisions_eval", BACKEND / "tests" / "evals" / "decisions.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path[:] = saved  # the eval puts tests/evals on sys.path; keep the suite's clean
    return mod


def _results(ev, *gots):
    golds = [
        ("grade_rubric_items", {"r1": "yes", "r2": "yes"}, ()),
        ("grade_rubric_items", {"r1": "yes", "r2": "no"}, ()),
        ("reason_is_correct", {"answer": "no"}, ("injection",)),
    ]
    return [
        ev.CaseResult(decision=d, gold=g, got=got or g, confidence=1.0, tags=t)
        for (d, g, t), got in zip(golds, gots or (None, None, None))
    ]


def test_gold_loader_refuses_unconsented_provenance_and_fixtures_comply(ev, tmp_path):
    for provenance in ("production", "student_answers", None):
        path = tmp_path / "judge_leak.json"
        path.write_text(
            json.dumps({"decision": "judge_leak", "provenance": provenance, "cases": []})
        )
        with pytest.raises(ev.GoldProvenanceError):
            ev.load_gold(path)
    files = sorted(ev.FIXTURES.glob("*.json"))
    assert {p.stem for p in files} == {
        "grade_rubric_items",
        "reason_is_correct",
        "match_wrong_reason",
        "item_answerable",
        "judge_leak",
    }
    for path in files:
        doc = json.loads(path.read_text())
        assert doc["provenance"] == "synthetic" and doc["decision"] == path.stem
        assert 1 <= len(doc["cases"]) <= ev.DECISION_EVAL_MAX_CASES
    cases = ev.all_cases()
    assert len({c.name for c in cases}) == len(cases) and any(
        "injection" in c.inputs.tags for c in cases
    )


def test_promotion_checks_pass_an_identical_candidate_and_catch_a_worse_one(ev):
    base = _results(ev)
    same = ev.promotion_checks(base, base)
    worse = ev.promotion_checks(
        _results(ev, None, {"r1": "yes", "r2": "yes"}, {"answer": "yes"}), base
    )
    assert same["DECISION_PROMOTE_MIN_GOLD"] is False  # 3 < 200: the series' gold promotes nothing
    for name in (
        "DECISION_PROMOTE_MAX_ACC_DROP",
        "GRADER_PROMOTE_MIN_KAPPA",
        "DECISION_PROMOTE_MAX_ECE",
        "false_positive_not_worse",
        "injection_flip_not_worse",
        "GRADER_BKT_REPLAY_MAX_DELTA",
    ):
        assert same[name] is True and worse[name] is False, name
    live = (
        "DECISION_SHADOW_MIN_DAYS",
        "DECISION_SHADOW_MIN_N",
        "DECISION_SHADOW_MIN_AGREEMENT",
        "DECISION_P95_MS",
        "DECISION_MAX_ERROR_RATE",
        "cost_not_worse",
    )
    assert all(same[n] is None for n in (*live, "SHARE_FALSE_POSITIVE_MAX"))
    good = ev.ShadowStats(
        days=7,
        n=1000,
        agreement=0.95,
        p95_ms=120,
        error_rate=0.001,
        cost_per_decision_usd=0.00003,
        gemini_cost_per_decision_usd=0.00007,
    )
    assert all(ev.promotion_checks(base, base, shadow=good)[n] is True for n in live)


def test_grade_answer_through_the_seam_on_the_e2e_lane(_function_lane, events):
    """The E2E lane end to end (PKG-07's /check/answer will run exactly this): function
    mode serves the grader from the env module's handler THROUGH the seam — backend
    `function` on the event, `gemini` on the evidence (the Gemini slot it stands in for)."""
    import agents.grader as g
    import agents.tools.check as c
    from agents._providers import model_for
    from agents.function_handlers_e2e import E2E_GRADER_CORRECT_TOKEN

    deps = _pkg05("_deps")
    answer = _pkg05("_answer", answer_text=f"{E2E_GRADER_CORRECT_TOKEN}: it stops the calls")
    with g.grader_agent.override(model=model_for("grader")):
        out = asyncio.run(c.grade_answer(_pkg05("_item"), answer, deps=deps, node_id=NODE))
    assert (out.unavailable, out.correct, out.grader_backend) == (False, True, "gemini")
    assert deps.pending_evidence[-1]["grader_backend"] == "gemini"
    assert [(et, kw["payload"]["backend"]) for et, kw in events] == [("decision.made", "function")]
