"""#354/#436: `agents._providers._LoopSafeGoogleModel` must never let a
`GoogleModel`'s provider (and hence its `google.genai`/httpx client) survive
across two different asyncio event loops — that is exactly the bug that
produced `RuntimeError: Event loop is closed` on every SECOND real call
through `run_agent_sync`, and identically on any test/agent that ends up
calling `asyncio.run()` more than once against the same shared agent in one
process (`test_ocr_pipeline.py::test_save_to_db`'s failure on main).

Fix-round-1 (PR review finding): the FIRST version of `_LoopSafeGoogleModel`
resolved the right provider under a lock, then handed it off through a
single shared mutable `self._provider` attribute — and `self` is a
module-level singleton shared by every concurrent call to the agent it
backs. A different thread's own resolve-and-hand-off, running concurrently
(exactly what happens under concurrent requests: every sync-`def` route
drives `run_agent_sync` on a fresh thread + throwaway loop), could stomp
that shared attribute during another thread's await gap, so the first
thread would resume and read a provider bound to someone ELSE's — possibly
already-closed — loop. Confirmed empirically: 6 threads x 20 sequential
`asyncio.run` calls against one shared instance, with an `asyncio.sleep`
standing in for the real await gap, produced 95/120 mismatches.

The fix removes the hand-off: `.client` is now a PROPERTY that resolves
`asyncio.get_running_loop()` -> the loop-keyed cache fresh, at the moment of
every access, with no instance-attribute write in between "resolve" and
"use". `TestConcurrentAccessIsRaceFree` below is the regression test for
that: it reproduces the reviewer's repro shape (N threads, each doing
sequential `asyncio.run` calls, with a deliberate await gap between
"provider ensured" and "client read") first against a minimal stand-in of
the ORIGINAL (buggy) hand-off design — proving the test shape itself would
have caught it — and then against the real, fixed `_LoopSafeGoogleModel`.

All tests here are hermetic: no actual `.request()`/network call, so no
dependence on GEMINI_API_KEY being a real key and nothing for the autouse
hermetic-LLM-guard fixture to intercept.
"""
from __future__ import annotations

import asyncio
import gc
import threading

from agents._providers import _LoopSafeGoogleModel, google_model, model_for


def test_model_for_real_mode_returns_loop_safe_model(monkeypatch):
    monkeypatch.delenv("SAPLING_MODEL_MODE", raising=False)
    m = model_for("classifier")
    assert isinstance(m, _LoopSafeGoogleModel)


def test_google_model_shim_returns_loop_safe_model():
    m = google_model("gemini-2.5-flash-lite")
    assert isinstance(m, _LoopSafeGoogleModel)


def test_fresh_provider_per_new_event_loop():
    """The core #354 regression: three SEPARATE, SEQUENTIAL asyncio.run()
    loops (exactly what `run_agent_sync` does per call, and what two
    independent test functions calling `asyncio.run()` do in the same
    process) must never share a provider — that sharing is what ties a
    client to a loop that is about to close."""
    m = _LoopSafeGoogleModel("gemini-2.5-flash-lite")

    seen = []

    async def _touch():
        seen.append(m._provider_for_current_loop())

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
        seen.append(m._provider_for_current_loop())
        seen.append(m._provider_for_current_loop())

    asyncio.run(_touch_twice())

    assert seen[0] is seen[1]


def test_client_property_resolves_per_loop_too():
    """The public `.client` property — what every inherited GoogleModel
    method (`request`, `count_tokens`, `request_stream`, `_generate_content`)
    actually reads — must show the same per-loop behavior as the private
    resolver: fresh across loops, stable within one."""
    m = _LoopSafeGoogleModel("gemini-2.5-flash-lite")
    clients_by_run = []

    async def _touch():
        clients_by_run.append((m.client, m.client))

    asyncio.run(_touch())
    asyncio.run(_touch())

    (a1, a2), (b1, b2) = clients_by_run
    assert a1 is a2, "same loop: .client should be stable across two reads"
    assert b1 is b2, "same loop: .client should be stable across two reads"
    assert a1 is not b1, "different (sequential) loops must not share a client"


def test_loop_cache_self_cleans_after_loop_is_collected():
    """The per-loop cache is a WeakKeyDictionary keyed by the loop object
    itself, so a disposable `run_agent_sync`/`asyncio.run()` loop's entry
    must not linger forever — a long process making many such calls over its
    lifetime must not accumulate one provider per call."""
    m = _LoopSafeGoogleModel("gemini-2.5-flash-lite")

    async def _touch():
        m._provider_for_current_loop()

    asyncio.run(_touch())
    gc.collect()
    assert len(m._loop_providers) == 0


def test_no_running_loop_is_a_safe_fallback_to_the_template():
    """Calling this outside any running loop (e.g. a test that inspects
    `.client` synchronously, like `test_hermetic_llm_guard.py`) must not
    raise — it falls back to the fixed template provider set at
    construction, since with no loop there is nothing to race."""
    m = _LoopSafeGoogleModel("gemini-2.5-flash-lite")
    assert m._provider_for_current_loop() is m._provider
    assert m.client is m._provider.client


class _PointerHandoffStandin:
    """Minimal reproduction of the ORIGINAL (buggy) `_LoopSafeGoogleModel`
    design that fix-round-1 replaced: `_bind_to_current_loop()` resolves the
    right provider under a lock, keyed correctly per loop — but then hands
    it off through ONE shared mutable `self._provider` attribute. A
    concurrent thread's own `_bind_to_current_loop()` call, running on a
    DIFFERENT loop, can rebind that same attribute during this thread's
    await gap, so a later read sees someone else's provider instead of the
    one that was just resolved for THIS loop.

    The real fix (`_LoopSafeGoogleModel.client`, tested below) never does
    this hand-off: it resolves straight from the loop-keyed dict at the
    exact point of read, with no shared instance attribute in between.
    """

    def __init__(self):
        self._loop_providers = {}
        self._lock = threading.Lock()
        self._provider = None

    def _bind_to_current_loop(self):
        loop = asyncio.get_running_loop()
        with self._lock:
            provider = self._loop_providers.get(loop)
            if provider is None:
                provider = object()
                self._loop_providers[loop] = provider
            self._provider = provider  # <-- the buggy shared hand-off
        return provider

    @property
    def client(self):
        return self._provider


def _hammer_for_mismatches(one_call, *, n_threads=6, n_calls=20):
    """Run `n_threads` threads, each doing `n_calls` sequential
    `asyncio.run(one_call())` calls. Mirrors the reviewer's repro shape
    (6 threads x 20 sequential asyncio.run calls against one shared model).
    """
    def _worker():
        for _ in range(n_calls):
            asyncio.run(one_call())

    threads = [threading.Thread(target=_worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


class TestConcurrentAccessIsRaceFree:
    """Fix-round-1 regression coverage: N threads, each running sequential
    `asyncio.run` calls against ONE shared model, with a deliberate await
    gap (mirroring the real `await self._build_content_and_config(...)` gap
    in pydantic-ai's `GoogleModel._generate_content`) between "the provider
    for this loop has been ensured/resolved" and "read the client actually
    used to make the request". Deterministic, hermetic, no network.
    """

    def test_pointer_handoff_standin_reproduces_the_original_race(self):
        """Sanity-checks the test shape itself against the ORIGINAL (buggy)
        design fix-round-1 replaced: it MUST mismatch under concurrent
        threads. If this ever stopped failing, the test shape below would no
        longer be trusted to catch a regression back to a shared pointer."""
        standin = _PointerHandoffStandin()
        mismatches = []
        mismatches_lock = threading.Lock()

        async def _one_call():
            expected = standin._bind_to_current_loop()
            await asyncio.sleep(0.001)  # the gap a concurrent thread exploits
            actual = standin.client
            if actual is not expected:
                with mismatches_lock:
                    mismatches.append((expected, actual))

        _hammer_for_mismatches(_one_call)

        assert mismatches, (
            "expected the buggy pointer-handoff stand-in to mismatch under "
            "concurrent threads — if it didn't, this test's shape no longer "
            "reproduces the original race and can't be trusted to catch a "
            "regression back to it"
        )

    def test_loop_safe_google_model_never_cross_wires_providers(self):
        """The actual fix-round-1 regression test: same shape as above, but
        reading through the REAL `.client` property. Must be zero
        mismatches — `.client` resolves from `asyncio.get_running_loop()` at
        read time, so it can't be affected by what any other thread does to
        its OWN loop's cache entry."""
        model = _LoopSafeGoogleModel("gemini-2.5-flash-lite")
        mismatches = []
        mismatches_lock = threading.Lock()

        async def _one_call():
            loop = asyncio.get_running_loop()
            # "Provider ensured" — a real request path's equivalent of the
            # first touch that would create this loop's cache entry.
            expected_provider = model._provider_for_current_loop()
            await asyncio.sleep(0.001)  # the same gap that broke the hand-off
            # "Client read" — the real path every inherited GoogleModel
            # method (request/count_tokens/request_stream) actually uses.
            actual_client = model.client
            if actual_client is not expected_provider.client:
                with mismatches_lock:
                    mismatches.append((loop, expected_provider, actual_client))

        _hammer_for_mismatches(_one_call)

        assert mismatches == []
