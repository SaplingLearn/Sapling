"""#354/#436: `agents._providers._LoopSafeGoogleModel` must never let a
`GoogleModel`'s provider (and hence its `google.genai`/httpx client) survive
across two different asyncio event loops — that is exactly the bug that
produced `RuntimeError: Event loop is closed` on every SECOND real call
through `run_agent_sync`, and identically on any test/agent that ends up
calling `asyncio.run()` more than once against the same shared agent in one
process (`test_ocr_pipeline.py::test_save_to_db`'s failure on main).

These tests are hermetic: they only exercise `_bind_to_current_loop`'s
bookkeeping (which provider object is currently bound), never an actual
`.request()` — so no live Gemini call, no dependence on GEMINI_API_KEY being a
real key, and nothing for the autouse hermetic-LLM-guard fixture to intercept.
"""
from __future__ import annotations

import asyncio
import gc

from agents._providers import _LoopSafeGoogleModel, google_model, model_for


def test_model_for_real_mode_returns_loop_safe_model(monkeypatch):
    monkeypatch.delenv("SAPLING_MODEL_MODE", raising=False)
    m = model_for("classifier")
    assert isinstance(m, _LoopSafeGoogleModel)


def test_google_model_shim_returns_loop_safe_model():
    m = google_model("gemini-2.5-flash-lite")
    assert isinstance(m, _LoopSafeGoogleModel)


def test_fresh_provider_per_new_event_loop():
    """The core #354 regression: two SEPARATE asyncio.run() loops (exactly
    what `run_agent_sync` does per call, and what two independent test
    functions calling `asyncio.run()` do in the same process) must never
    share a provider — that sharing is what ties a client to a loop that is
    about to close."""
    m = _LoopSafeGoogleModel("gemini-2.5-flash-lite")

    seen = []

    async def _touch():
        m._bind_to_current_loop()
        seen.append(m._provider)

    asyncio.run(_touch())
    asyncio.run(_touch())
    asyncio.run(_touch())

    assert len(seen) == 3
    assert seen[0] is not seen[1]
    assert seen[1] is not seen[2]
    assert seen[0] is not seen[2]


def test_same_provider_reused_within_one_loop():
    """Within a single loop's lifetime (e.g. FastAPI's persistent per-process
    loop across many `await agent.run(...)` calls, or a multi-step agent run
    that calls the model more than once), the provider — and its connection
    pool — should be reused rather than rebuilt on every call."""
    m = _LoopSafeGoogleModel("gemini-2.5-flash-lite")
    seen = []

    async def _touch_twice():
        m._bind_to_current_loop()
        seen.append(m._provider)
        m._bind_to_current_loop()
        seen.append(m._provider)

    asyncio.run(_touch_twice())

    assert seen[0] is seen[1]


def test_loop_cache_self_cleans_after_loop_is_collected():
    """The per-loop cache is a WeakKeyDictionary keyed by the loop object
    itself, so a disposable `run_agent_sync`/`asyncio.run()` loop's entry
    must not linger forever — a long process making many such calls over its
    lifetime must not accumulate one provider per call."""
    m = _LoopSafeGoogleModel("gemini-2.5-flash-lite")

    async def _touch():
        m._bind_to_current_loop()

    asyncio.run(_touch())
    gc.collect()
    assert len(m._loop_providers) == 0


def test_no_running_loop_is_a_safe_no_op():
    """Calling this outside any running loop (e.g. a test that just inspects
    the model) must not raise — it leaves whatever provider is already set."""
    m = _LoopSafeGoogleModel("gemini-2.5-flash-lite")
    before = m._provider
    m._bind_to_current_loop()
    assert m._provider is before
