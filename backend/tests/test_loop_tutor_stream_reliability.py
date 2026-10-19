"""Real FunctionModel/agent regressions for the live structured-stream outage.

No provider, database or learner evidence: the production validator, request
limits, producer and route accounting run against deterministic model output.
"""

from __future__ import annotations

import asyncio
import json
from types import MethodType, SimpleNamespace
from unittest.mock import MagicMock

import pytest
import httpx
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.usage import RunUsage

from agents import LOOP_LIMITS
from learning.turn_shape import render_partial, render_turn
from services.chat_stream import stream_structured_turn
from tests.test_chat_stream import (
    _TURN,
    _loop_agent,
    _loop_deps,
    _streamed_model,
    collect_structured,
)

# The live final failure was question_shape:2 sentences, not necessarily two
# question marks. A declarative preface in the question field is invalid too.
_BAD = {**_TURN, "question": "Review the stopping condition. Which input should stop it?"}


@pytest.mark.parametrize("bad_rounds", [0, 1, 2, 3])
def test_real_agent_shape_retries_are_bounded_and_settle_usage_once(bad_rounds, caplog):
    turns = [_BAD] * bad_rounds + ([_TURN] if bad_rounds < 3 else [])
    model, calls = _streamed_model(turns)
    usage = RunUsage()
    completed, incomplete, persisted, rescued = [], [], [], []

    async def fallback(messages):
        rescued.append(messages)
        return {"reply": "must not silently retry after tokens"}

    events = asyncio.run(
        collect_structured(
            _loop_agent(),
            _loop_deps(),
            model,
            lambda reply, graph, mastery: persisted.append(reply) or {},
            nonstream_fallback=fallback,
            on_usage=completed.append,
            on_incomplete_usage=incomplete.append,
            run_kwargs={"usage": usage, "usage_limits": LOOP_LIMITS},
        )
    )
    types = [event.type for event in events]
    assert calls["n"] == usage.requests == min(bad_rounds + 1, 3)
    assert calls["n"] <= LOOP_LIMITS.request_limit
    assert rescued == []
    if bad_rounds < 3:
        assert types[-1] == "done" and "error" not in types
        assert types.count("retract") == bad_rounds
        assert persisted == [render_turn(_TURN)]
        assert len(completed) == 1 and completed[0].usage == usage
        assert incomplete == []
    else:
        assert types[-1] == "error" and types.count("error") == 1
        assert "done" not in types and types.count("retract") == 2
        assert completed == persisted == [] and incomplete == [usage]
        assert usage.input_tokens > 0 and usage.output_tokens > 0
        assert "question_shape:2 sentences" in caplog.text
        assert "usage is incomplete" in caplog.text


@pytest.mark.parametrize("when", ["before_tokens", "after_tokens", "after_retry"])
@pytest.mark.parametrize("hook_fails", [False, True])
def test_consumer_cancel_accounts_known_usage_without_completing_or_retrying(when, hook_fails):
    async def run():
        waiting = asyncio.Event()
        calls = []
        usage = RunUsage()
        completed, incomplete, persisted, events = [], [], [], []

        async def stream(messages, info):
            calls.append(1)
            if when == "before_tokens" or (when == "after_retry" and len(calls) == 2):
                waiting.set()
                await asyncio.Event().wait()
            text = json.dumps(_BAD if when == "after_retry" else _TURN)
            for index in range(0, len(text), 6):
                if when == "after_tokens" and index > len(text) // 2:
                    waiting.set()
                    await asyncio.Event().wait()
                yield text[index : index + 6]

        def nonstream(messages, info):
            raise AssertionError("cancellation must not start a nonstream rescue")

        deps = _loop_deps()

        def record_incomplete(known_usage):
            incomplete.append(known_usage)
            if hook_fails:
                raise RuntimeError("instrumentation is unavailable")

        async def consume():
            async for event in stream_structured_turn(
                agent=_loop_agent(),
                user_message="hi",
                run_kwargs={
                    "deps": deps,
                    "model": FunctionModel(nonstream, stream_function=stream),
                    "usage": usage,
                    "usage_limits": LOOP_LIMITS,
                },
                deps=deps,
                on_complete=lambda *args: persisted.append(args) or {},
                on_usage=completed.append,
                on_incomplete_usage=record_incomplete,
            ):
                events.append(event)

        task = asyncio.create_task(consume())
        await asyncio.wait_for(waiting.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert incomplete == [usage] and completed == persisted == []
        assert not any(event.type in ("done", "error") for event in events)
        assert len(calls) == (2 if when == "after_retry" else 1)
        assert usage.requests == (0 if when == "before_tokens" else 1)
        if when == "after_retry":
            assert usage.output_tokens > 0  # the first completed failed output is retained
        await asyncio.sleep(0)
        assert all(
            task.done() for task in asyncio.all_tasks() if task is not asyncio.current_task()
        )

    asyncio.run(run())


def test_usage_hooks_cannot_replace_the_original_terminal_error():
    model, calls = _streamed_model([_BAD] * 3)
    hook_calls = []

    def broken(usage):
        hook_calls.append(usage)
        raise RuntimeError("instrumentation is unavailable")

    events = asyncio.run(
        collect_structured(
            _loop_agent(),
            _loop_deps(),
            model,
            lambda *args: pytest.fail("no persistence"),
            on_incomplete_usage=broken,
            run_kwargs={"usage": RunUsage(), "usage_limits": LOOP_LIMITS},
        )
    )
    assert calls["n"] == 3 and len(hook_calls) == 1
    assert events[-1].type == "error" and events[-1].data["retryable"] is True
    assert sum(event.type == "error" for event in events) == 1
    assert not any(event.type == "done" for event in events)


def test_successful_producer_usage_is_settled_even_if_consumer_closes_at_first_token():
    model, _ = _streamed_model([_TURN])
    completed, incomplete, persisted = [], [], []

    async def run():
        deps = _loop_deps()
        settled = asyncio.Event()

        def record(result):
            completed.append(result)
            settled.set()

        gen = stream_structured_turn(
            agent=_loop_agent(),
            user_message="hi",
            run_kwargs={"deps": deps, "model": model, "usage": RunUsage()},
            deps=deps,
            on_complete=lambda *args: persisted.append(args) or {},
            on_usage=record,
            on_incomplete_usage=incomplete.append,
        )
        async for event in gen:
            if event.type == "token":
                await asyncio.wait_for(settled.wait(), timeout=2)
                await gen.aclose()
                break

    asyncio.run(run())
    assert len(completed) == 1 and incomplete == []
    assert persisted == []  # accounting never makes a disconnected turn successful


def test_successful_usage_hook_failure_does_not_change_the_valid_reply():
    model, calls = _streamed_model([_TURN])
    usage = []

    def broken(result):
        usage.append(result)
        raise RuntimeError("instrumentation is unavailable")

    events = asyncio.run(
        collect_structured(
            _loop_agent(),
            _loop_deps(),
            model,
            lambda *args: {},
            on_usage=broken,
        )
    )
    assert len(usage) == calls["n"] == 1
    assert events[-1].type == "done" and events[-1].data["reply"] == render_turn(_TURN)


def _route_turn(model):
    from routes import learn_loop

    deps = _loop_deps()
    turn = SimpleNamespace(
        user_id="u1",
        session_id="s1",
        request_id="r1",
        band="develop",
        slot="loop_tutor",
        tier="standard",
        paused=False,
        run_requests=0,
        state={"tutor_requests": 2, "deep_requests": 1},
        arm=None,
        confront_used=None,
        agent=_loop_agent(),
        deps=deps,
        assembled="hi",
        run_kwargs={"deps": deps, "model": model, "usage_limits": LOOP_LIMITS},
        plan=MagicMock(),
        pre_events=lambda: [],
        redact=lambda text: text,
        serve=lambda text: text,
        render=render_turn,
        render_partial=render_partial,
        record_relayed=MagicMock(),
        touch_served_at=MagicMock(),
        complete=MagicMock(side_effect=lambda reply, graph, mastery: {"reply": reply}),
    )
    turn.record_usage = MethodType(learn_loop._LoopTurn.record_usage, turn)
    turn.budget_counters = MethodType(learn_loop._LoopTurn.budget_counters, turn)
    return turn


@pytest.mark.parametrize("rescue", ["model_free", "succeeds", "fails"])
def test_route_accounts_failed_primary_and_rescue_independently_once(rescue, monkeypatch):
    from routes import learn_loop

    stream_calls, rescue_calls, bills = [], [], []

    async def stream(messages, info):
        stream_calls.append(1)
        yield "not json"  # completes/bills, but no parsed partial can be shown

    def nonstream(messages, info):
        rescue_calls.append(1)
        return ModelResponse(parts=[TextPart(json.dumps(_BAD if rescue == "fails" else _TURN))])

    model = FunctionModel(nonstream, stream_function=stream)
    turn = _route_turn(model)
    monkeypatch.setattr(
        learn_loop.ai_budget, "check", lambda *args, **kwargs: SimpleNamespace(level="ok")
    )
    counted = MagicMock()
    monkeypatch.setattr(learn_loop.ai_budget, "count_tutor_call", counted)
    monkeypatch.setattr(learn_loop, "served_model_name", lambda *args: "function-loop")

    def record(result, **kwargs):
        bills.append((learn_loop._requests_of(result), kwargs["feature"]))
        return result

    monkeypatch.setattr(learn_loop, "record_agent_usage", record)
    if rescue == "model_free":

        async def model_free(turn, messages):
            return "An explicit model-free response."

        monkeypatch.setattr(learn_loop, "_continue_turn", model_free)

    async def run():
        return [event async for event in learn_loop._stream_turn(turn)]

    events = asyncio.run(run())
    assert len(stream_calls) == 3
    expected_bills = {
        "model_free": [(3, "loop_tutor")],
        "succeeds": [(3, "loop_tutor"), (1, "loop_tutor")],
        "fails": [(3, "loop_tutor"), (3, "loop_tutor")],
    }
    assert bills == expected_bills[rescue]
    assert turn.run_requests == {"model_free": 3, "succeeds": 4, "fails": 6}[rescue]
    assert len(rescue_calls) == (0 if rescue == "model_free" else 3 if rescue == "fails" else 1)
    assert counted.call_count == (1 if rescue == "model_free" else 2)
    if rescue == "fails":
        turn.complete.assert_not_called()
        assert sum(event["event"] == "error" for event in events) == 1
        assert not any(event["event"] == "done" for event in events)
    else:
        turn.complete.assert_called_once()
        assert sum(event["event"] == "done" for event in events) == 1


@pytest.mark.parametrize("when", ["before_tokens", "after_tokens", "during_rescue"])
def test_route_cancellation_keeps_only_known_primary_and_rescue_usage(when, monkeypatch):
    from routes import learn_loop

    async def run():
        waiting = asyncio.Event()
        stream_calls, rescue_calls, bills, events = [], [], [], []

        async def stream(messages, info):
            stream_calls.append(1)
            if when == "before_tokens":
                waiting.set()
                await asyncio.Event().wait()
            if when == "during_rescue":
                yield "not json"
                return
            text = json.dumps(_TURN)
            for index in range(0, len(text), 6):
                if index > len(text) // 2:
                    waiting.set()
                    await asyncio.Event().wait()
                yield text[index : index + 6]

        async def nonstream(messages, info):
            rescue_calls.append(1)
            if len(rescue_calls) == 2:
                waiting.set()
                await asyncio.Event().wait()
            return ModelResponse(parts=[TextPart(json.dumps(_BAD))])

        turn = _route_turn(FunctionModel(nonstream, stream_function=stream))
        monkeypatch.setattr(
            learn_loop.ai_budget, "check", lambda *args, **kwargs: SimpleNamespace(level="ok")
        )
        monkeypatch.setattr(learn_loop.ai_budget, "count_tutor_call", MagicMock())
        monkeypatch.setattr(learn_loop, "served_model_name", lambda *args: "function-loop")

        def record(result, **kwargs):
            bills.append(learn_loop._requests_of(result))
            return result

        monkeypatch.setattr(learn_loop, "record_agent_usage", record)

        async def consume():
            async for event in learn_loop._stream_turn(turn):
                events.append(event)

        task = asyncio.create_task(consume())
        await asyncio.wait_for(waiting.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert (
            bills
            == {
                "before_tokens": [],  # no reported request/tokens: do not fabricate a bill
                "after_tokens": [1],  # one known request; its token total may be unavailable
                "during_rescue": [3, 1],  # both runs retain their known usage, once each
            }[when]
        )
        assert len(stream_calls) == (3 if when == "during_rescue" else 1)
        assert len(rescue_calls) == (2 if when == "during_rescue" else 0)
        assert (
            turn.run_requests == {"before_tokens": 0, "after_tokens": 1, "during_rescue": 4}[when]
        )
        assert not any(event["event"] in ("done", "error") for event in events)
        turn.complete.assert_not_called()
        turn.touch_served_at.assert_called_once()

    asyncio.run(run())


@pytest.mark.parametrize("confronting", [False, True])
def test_continuation_checks_known_work_without_mutating_saved_cap_units(confronting, monkeypatch):
    from learning import params
    from routes import learn_loop
    from services.ai_budget import BudgetDecision

    turn = _route_turn(MagicMock())
    turn.tier = "deep"
    turn.run_requests = 3
    turn.confront_used = {} if confronting else None
    spent = 3 if confronting else 1  # same existing units as _apply_turn
    cap = params.LOOP_SESSION_MAX_DEEP_REQUESTS
    turn.state = {"tutor_requests": 2, "deep_requests": cap - spent}
    saved = dict(turn.state)
    counters = []

    def budget(*args, **kwargs):
        counters.append(kwargs)
        assert kwargs["session_deep_requests"] == cap
        return BudgetDecision(level="soft", tier_ceiling="standard", scope="session_deep")

    monkeypatch.setattr(learn_loop.ai_budget, "check", budget)
    counted = MagicMock()
    monkeypatch.setattr(learn_loop.ai_budget, "count_tutor_call", counted)
    billed = MagicMock()
    monkeypatch.setattr(learn_loop, "record_agent_usage", billed)
    # A fresh planning read is still exactly the saved counters. The continuation
    # is the only caller that opts in to known work from its uncompleted turn.
    assert turn.budget_counters()["session_deep_requests"] == cap - spent
    assert turn.budget_counters()["session_tutor_requests"] == 2
    assert asyncio.run(learn_loop._loop_continuation_text(turn, [])) is None
    assert counters[0]["session_tutor_requests"] == 3
    assert turn.state == saved and turn.run_requests == 3
    counted.assert_not_called()
    billed.assert_not_called()  # refused/model-free rescue adds no invented work


@pytest.mark.parametrize("failure", ["shape", "timeout", "cancel"])
def test_continuation_usage_hook_failure_preserves_original_failure(failure, monkeypatch):
    from routes import learn_loop

    calls, bills = [], []

    async def fn(messages, info):
        calls.append(1)
        if len(calls) == 2:
            if failure == "timeout":
                raise httpx.ReadTimeout("provider timeout marker")
            if failure == "cancel":
                raise asyncio.CancelledError("consumer cancellation marker")
        return ModelResponse(parts=[TextPart(json.dumps(_BAD))])

    turn = _route_turn(FunctionModel(fn))
    turn.run_requests = 3  # known failed primary, already accounted separately
    monkeypatch.setattr(
        learn_loop.ai_budget, "check", lambda *args, **kwargs: SimpleNamespace(level="ok")
    )
    monkeypatch.setattr(learn_loop.ai_budget, "count_tutor_call", MagicMock())

    def broken(result, **kwargs):
        bills.append(learn_loop._requests_of(result))
        raise RuntimeError("instrumentation must not replace the original failure")

    monkeypatch.setattr(learn_loop, "record_agent_usage", broken)
    expected = {
        "shape": UnexpectedModelBehavior,
        "timeout": httpx.ReadTimeout,
        "cancel": asyncio.CancelledError,
    }
    with pytest.raises(expected[failure]):
        asyncio.run(learn_loop._loop_continuation_text(turn, []))
    known = 3 if failure == "shape" else 1
    assert bills == [known] and turn.run_requests == 3 + known
    assert len(calls) == (3 if failure == "shape" else 2)
    turn.complete.assert_not_called()
