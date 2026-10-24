"""Rung 1 of the streaming fallback ladder against the REAL provider (#356 item 3).

The hermetic suite pins the ladder's mechanics with scripted agents
(test_chat_stream.py: the fallback owns persistence, on_complete never runs on
the fallback branch; test_learn_stream_routes.py: the route wiring). What it
structurally cannot prove is the two provider-shaped facts Rung 1 depends on:

  1. a real pre-token agent failure (here: a nonexistent model name, which the
     Google API rejects before any text) surfaces as an exception
     `stream_agent_turn` catches — across whatever exception wrapping the
     INSTALLED pydantic-ai does (the 1.x → 2.x drift in exactly this seam broke
     every main e2e run once, #459);
  2. the nonstream fallback — since #151a a plain `Agent.run()` on the fast
     tier (D2), the same shape `_chat_turn_json`/`_start_session_agent` run —
     can then serve the turn live, and the client-visible shape is a SINGLE
     token event carrying the whole fallback reply followed by `done` — "the
     fallback reply arrives as one message".

Both rungs now ride the same Pydantic AI provider stack (the gemini_service
seam is gone from learn.py), so what this lane really exercises is the live
Google provider erroring on one model while serving another within one
process. Costs one real Gemini call. Skipped unless RUN_LIVE_STREAM_RUNGS=1
and a real key is set (same opt-in posture as test_vision_ocr_live.py).
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.live_llm

_PLACEHOLDER_KEYS = {"", "dummy-key-for-import", "dummy-not-used-in-tests", "test-key"}


def _requires_live_rungs():
    if os.getenv("RUN_LIVE_STREAM_RUNGS") != "1":
        pytest.skip("billable live-model lane is opt-in (RUN_LIVE_STREAM_RUNGS=1)")
    if (os.getenv("GEMINI_API_KEY") or "").strip() in _PLACEHOLDER_KEYS:
        pytest.skip("needs a real GEMINI_API_KEY — this test makes live model calls")


def test_rung1_real_agent_failure_degrades_to_live_fast_tier_agent(monkeypatch):
    _requires_live_rungs()

    from pydantic_ai import Agent

    from agents._providers import google_model, model_for
    from services.chat_stream import stream_agent_turn

    # A model name the API cannot serve → the agent fails before any token.
    monkeypatch.setenv("SAPLING_MODEL_CHAT_TUTOR", "gemini-model-that-does-not-exist")
    monkeypatch.delenv("SAPLING_MODEL_MODE", raising=False)  # real mode

    agent = Agent(model=model_for("chat_tutor"))
    deps = SimpleNamespace(graph_updates=[], mastery_changes=[])
    persisted: list[str] = []

    def on_complete(reply, merged, mastery):
        persisted.append(reply)
        return {}

    async def fallback():
        # The D2 shape: a GOOD fast-tier model via a plain Agent.run(), the
        # same second chance _chat_turn_json(model_pref="fast") takes live.
        good_agent = Agent(
            model=google_model("gemini-2.5-flash-lite"),
            system_prompt=(
                "You are a terse test assistant. Answer in one short sentence."
            ),
        )
        result = await good_agent.run("Reply with the single word: pineapple")
        return {"reply": result.output}

    async def collect():
        events = []
        async for ev in stream_agent_turn(
            agent=agent,
            user_message="hello",
            run_kwargs={},
            deps=deps,
            on_complete=on_complete,
            nonstream_fallback=fallback,
            request_id="live-rung1",
        ):
            events.append(ev)
        return events

    events = asyncio.run(collect())
    types = [ev.type for ev in events]

    # status:start → ONE token (the whole fallback reply as a single message)
    # → done. No error event: the fallback served the turn.
    assert types == ["status", "token", "done"], types
    token, done = events[1], events[2]
    assert token.data["delta"] == done.data["reply"]
    assert "pineapple" in done.data["reply"].lower()
    # The fallback owns persistence — on_complete must not have run (the
    # hermetic twin pins this too; here it holds under the real failure shape).
    assert persisted == []
